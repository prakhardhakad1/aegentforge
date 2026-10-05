# NOTES — packages/orchestrator (Agent 3: orchestration engine)

Module owner: **Agent 3** · ForgeHacks Online 2026 · AgentForge.
Read `docs/SPEC.md` + `docs/INTERFACES.md` first — the event envelope,
RunResult shape and `execute_run` signature are pinned contracts.

## What this module is

The heart of AgentForge: a planner spawns specialist AI agents
(researcher / analyst / forecaster / critic) that work a business mission as
a DAG, stream every pinned event live, and deliver a structured report.

```
mission ─▶ Planner (LLM or heuristic) ─▶ validated DAG
        ─▶ topological execution (retry ≤ 2 per step)
        ─▶ Critic review ─▶ ONE revision pass (conditional slots)
        ─▶ finalize ─▶ orchestrator.report.build_report ─▶ RunResult
```

## File map

| File | Purpose |
|---|---|
| `orchestrator/llm.py` | Provider-agnostic OpenAI-compatible client. Mock mode (deterministic, labeled), retries + backoff, fallback model, `complete_json()` with robust JSON extraction, per-call token usage. |
| `orchestrator/planner.py` | `Planner` (LLM plan when live, template plan when Agent 8 lands, heuristic fallback offline) + `Subtask`/`Plan` + strict DAG validation/normalization. |
| `orchestrator/agents/base.py` | `Worker` base: context assembly, OpenAI-style tool function-calling loop, structured-output contract, artifact extraction, token hooks. |
| `orchestrator/agents/{researcher,analyst,forecaster,critic}.py` | The four specialists (role prompts, allowed tools, output contracts). Critic also owns `verdict()` → `CriticVerdict`. |
| `orchestrator/messages.py` | `TaskAssignment`, `WorkerOutput`, `RevisionRequest`, `CriticVerdict` dataclasses. |
| `orchestrator/engine.py` | `execute_run()` + `RunResult` + `_Emitter` (pinned envelopes, monotonic seq), retry policy, critic revision pass, honest degradation, report integration. |
| `orchestrator/tokens.py` | `TokenAccountant`: per-agent counters, USD cost from env, `token_update` payloads, pinned `token_usage` shape. |
| `orchestrator/memory.py` | `MemoryStore` protocol + `InMemoryJSONStore` (token-overlap search, optional JSON persistence). Interface only — no fake cloud calls. |
| `orchestrator/examples/` | 3 worked missions (churn w/ CSV, EV chargers, support tickets w/ CSV) + `python -m orchestrator.examples.run_demo`. |
| `tests/` | 90 pytest cases: JSON extraction edge cases, mock routing, live retries/fallback (httpx.MockTransport), DAG validation, engine happy/retry/revision/degradation/budget paths, tokens, memory, messages. |

## Design decisions

1. **Mock mode is a first-class feature, not a stub.** `LLM_MODE=mock` never
   constructs the httpx client (asserted by a test). The mock responder is
   role-aware (detects `ROLE: <role>` in the system prompt), produces a
   realistic two-phase worker loop (round 0: tool call when a tool makes
   sense; then final structured JSON), and labels every payload `MOCK`.
   Token usage is a deterministic ~4-chars/token estimate so the cost meter
   exercises end-to-end offline.
2. **Role detection is marker-first.** Upstream digests mention other roles
   ("(analyst, status=completed)"), so the mock responder only trusts the
   exact `ROLE: <role>` marker in the system message, with word-boundary
   fallbacks. This was a real bug caught by the engine happy-path test.
3. **Planner LRU: template → LLM → heuristic.** Template plans (Agent 8) are
   consumed via a defensive adapter (`get_template(template_id)` or
   `TEMPLATES[...]`, guarded by try/except — Agent 8's API is unknown at
   authoring time). LLM plans are normalized (dedupe ids, drop unknown
   deps, wire the critic to see every worker) then validated; any violation
   falls back to the transparent heuristic planner, so a bad LLM answer can
   never produce an unrunnable DAG.
4. **Revision loop as conditional slots.** Plans end with the critic plus a
   `*_rev` revision slot depending on it. The engine runs at most ONE
   revision pass: re-run flagged subtasks (their own specialists, with the
   critic's instruction attached), then re-review once. Unused slots are
   reported `skipped` — the plan always shows the loop was available.
5. **Honest degradation.** A subtask that exhausts its retries is marked
   `failed`, appended to `errors`, and *downstream steps still run* with
   degraded upstream context. Status is `succeeded` / `partial` / `failed`
   and `run_failed` events carry a `stage`. The engine never raises
   outward; even a crashing `on_event` subscriber can't kill a run.
6. **Tools are duck-typed and optional.** The worker loop consumes
   Agent 4's `ToolRegistry` via `function_calling_specs()` / `run()` with
   `getattr` access; if `agentforge_tools` isn't importable the registry is
   `None`, no tools are offered, and workers still complete. Tool calls
   never raise outward (`ok=False` + honest `tool_result` event).
7. **Token honesty in mock mode.** The heuristic planner makes zero LLM
   calls in mock mode, so `planner` correctly has no entry in
   `token_usage.per_agent` there. In live mode planner usage is captured
   through `LLMClient.last_response` + a `Planner(on_usage=...)` callback.
8. **Test seams without polluting the pinned signature.** `execute_run`
   matches INTERFACES.md exactly; test injection happens through
   module-level factories in `engine.py` — `_default_llm_client`,
   `_default_tool_registry(run_id)`, `_build_workers` — which tests
   monkeypatch.

## Planner heuristic rules (offline fallback)

Signals (substring match on lowercased mission, or dataset presence):

* **research**: market, research, competitor, competitive, landscape,
  benchmark, industry, feedback, best practice, what are, why do, trend,
  "ev ", charging, review site
* **data**: data, csv, dataset, metric, churn, revenue, sales, ticket,
  conversion, retention, kpi, stats, spike, decline, dropped, analyze,
  analysis, usage, numbers, q3, quarter — OR `dataset_columns` provided
* **predict**: predict, forecast, projection, outlook, next quarter,
  next month, trajectory, anticipate, expect, will grow, adoption

Chain: researcher (research) → analyst (data) → forecaster (predict);
if nothing matches, default researcher + critic. Always: one critic
depending on every worker, then one conditional revision slot.
Validation contract: unique safe ids, worker roles only, known deps, no
cycles (Kahn), exactly one critic, nothing after the critic except
revision slots, ≤ 10 subtasks.

## Env vars consumed (canonical names, see .env.example)

| Var | Default | Use |
|---|---|---|
| `LLM_BASE_URL` | GLM/Zhipu v4 | chat-completions base URL |
| `LLM_API_KEY` | "" | bearer token (mock mode ignores) |
| `LLM_MODEL` / `LLM_FALLBACK_MODEL` | glm-4-flash | primary/fallback model ids |
| `LLM_MODE` | mock | `live` \| `mock` |
| `LLM_TIMEOUT_SECONDS` | 60 | per-request timeout |
| `LLM_MAX_RETRIES` | 2 | retries per model (extra, optional) |
| `COST_PER_1M_INPUT_TOKENS` / `COST_PER_1M_OUTPUT_TOKENS` | 0.11 | USD per 1M tokens (defaults mirror .env.example) |
| `AGENTFORGE_*` | — | none; runtime sandbox workspace goes to `<tmp>/agentforge_runs/<run8>/` (never writes repo dirs) |

## Dependencies

Core: `httpx`, `pydantic` only (pinned). `agentforge_tools`,
`orchestrator.report`, `orchestrator.templates` are imported defensively at
call time — this package installs and runs without them.

## DEVIATIONS

1. **Additive event payload fields.** `plan_created` payload carries an
   extra `"strategy"` key next to the pinned `subtasks`; `agent_finished`
   carries `{subtask_id, ok, summary|error}` and `run_started` carries
   `{mission, template_id, mode, has_dataset}` (these payloads were not
   pinned in INTERFACES.md — shapes chosen for the live view). Consumers
   reading only the pinned keys are unaffected.
2. **`RunResult.plan` entries include `guidance`.** The pinned payload for
   `plan_created` events omits it (`to_dicts(include_guidance=False)`), but
   RunResult keeps it so the report/export can show why each step existed.
3. **`plan_created` seq = 2, not emitted for the planner's own "agent
   lifecycle".** The planner is not a scheduled subtask, so it has no
   `agent_started`/`agent_finished` events; it emits `plan_created` and
   (live mode only) `token_update`s as agent `planner`.
4. **Mock analyst stats/charts are canned**, not derived from the real
   csv_analyzer output (the real tool still runs and its result is fed to
   the mock conversation for realism). Canned numbers are labeled `MOCK` —
   required for a deterministic offline demo; live mode replaces them.
5. **`execute_run` performs a revision re-review even when the budget gets
   tight** (it may skip it if `max_steps` is exhausted) — the critic's
   remaining objections are then recorded in `errors` rather than silently
   dropped.

## Verified

* `python -m pytest packages/orchestrator/tests -q` → **90 passed**
* `python -m orchestrator.examples.run_demo --example churn|ev|support`
  all finish `succeeded` fully offline (`LLM_MODE=mock`), events stream in
  pinned order, report builds via Agent 6's `orchestrator.report`.
