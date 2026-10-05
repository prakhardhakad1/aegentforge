# backend/realtime — Agent 7 NOTES

Status: **complete and tested** (71 realtime tests + 68 backend regression
tests green). Scope: `backend/realtime/` only, plus additive frontend files in
`frontend/components/live/` and `frontend/hooks/useRunStreamV2.ts` (see
`frontend/components/live/README.md` for wiring).

## File map

| File | Purpose |
|---|---|
| `events.py` | Canonical pinned envelope: `EVENT_TYPES` / `AGENT_ROLES` / `ARTIFACT_KINDS` constants, pydantic envelope + per-type payload models, `make_event(...)`, `validate_event(...)`, `chart_spec(...)` helper, `EventValidationError`. |
| `broadcaster.py` | Full `Broadcaster` + `get_broadcaster()` singleton (replaces the coordinator stub at the same import path). `publish`, `subscribe`, `history`, `replay_after`, `clear`, `subscriber_count`, `reset_broadcaster` (tests). |
| `token_meter.py` | `TokenMeter`: per-agent input/output counters, env-driven cost math, `snapshot()` in the pinned `token_usage` shape, `merge`, `from_snapshot`, `from_events`, `breakdown_table`, `format_breakdown`. |
| `simulate.py` | Offline demo simulator: `SimulatedRunPlayer` + `run_simulation(mission, template_id=None, on_event=None, speed=1.0, run_id=None)`. Deterministic, no LLM/network. |
| `tests/` | `test_events.py`, `test_broadcaster.py`, `test_simulate.py`, `test_token_meter.py` (pytest-asyncio). |
| `__init__.py` | Package doc only (stdlib). |

## Design decisions

### events.py
* **`realtime` is dependency-light on purpose**: only stdlib + pydantic. It
  does NOT import `app.*` (the app imports `realtime`), so orchestrator,
  simulator and tests can use it anywhere. The pinned string constants are
  duplicated from `app/schemas/common.py`; values are asserted byte-identical
  in `test_events.py`.
* Payload models use `extra="allow"`: pinned fields are enforced, producers
  may annotate (e.g. `"simulated": true`) without breaking validation.
* Pydantic wraps validator-raised `ValueError`s, so `make_event` re-wraps
  everything into the single contract exception `EventValidationError`.
* `make_event(event_type, run_id, seq, agent=None, payload=None, *, ts=None)`
  returns a plain **dict** — the canonical currency across broadcaster / WS /
  DB is a dict, never a model instance.

### broadcaster.py (pinned surface, unchanged)
* `get_broadcaster()` → singleton. `publish` supports BOTH pinned call shapes:
  `await bc.publish(run_id, event)` and `await bc.publish(event)` (event must
  carry `run_id`). Arity detection in `app/services.events.publish_event`
  resolves to the 2-arg form.
* **Seq ownership**: an event-provided `seq` (int ≥ 1) is preserved verbatim
  (orchestrator engine and demo player own their numbering). Missing/invalid
  seqs are stamped from a per-run `itertools.count`. A per-run watermark
  guarantees auto-stamped seqs never collide with or regress below
  explicitly-seq'd ones (tested under concurrency: 60 concurrent publishes →
  seqs 1..60 unique, history order == seq order; mixed explicit/stamped test
  included). Stamping is await-free, so one event loop makes it atomic.
* **Slow-consumer isolation**: each subscriber gets a bounded `asyncio.Queue`
  (`SUBSCRIBER_QUEUE_MAXSIZE=512`, drop-oldest). `publish` never awaits on a
  consumer (verified: 30 events to a stalled consumer < 1 s while a healthy
  subscriber receives all 30). On overflow the consumer gets a synthetic
  `{"type": "events_dropped", payload: {"recoverable_via": "replay_after"}}`
  marker so it can re-sync — that's exactly what the client
  `{"type":"replay","after_seq":N}` message is for.
* **Bounded memory**: per-run history capped (`DEFAULT_HISTORY_LIMIT=2000`,
  drop-oldest); idle runs evicted past `DEFAULT_MAX_RUNS=500`;
  `clear(run_id)` frees everything for a finished run.
* `subscribe(run_id)` registers its queue when the generator body first runs
  (first `__anext__`) — the WS route already does
  `asyncio.create_task(subscription.__anext__())` immediately, and the
  subscribe→history snapshot ordering in `runs.py` is safe (buffered queue +
  `last_sent_seq` dedupe). Unsubscribe happens in the generator `finally` on
  `aclose()`, `break`-then-`aclose`, or task cancellation (all tested).

### token_meter.py
* Rates read from env `COST_PER_1M_INPUT_TOKENS` / `COST_PER_1M_OUTPUT_TOKENS`
  at construction; unset/invalid/negative → defaults 0.11 / 0.11.
* `ingest_token_update` honours a producer-declared `cost_usd` (engines with
  their own pricing) and recomputes otherwise. `merge` re-computes per-agent
  cost at the receiving meter's rates so merged snapshots stay consistent.
* `snapshot()` returns the pinned `RunResult.token_usage` shape
  (`{"per_agent": {...}, "totals": {"input_tokens","output_tokens","cost_usd"}}`).

### simulate.py
* **Deterministic**: content is fully scripted; PRNG seeded from
  `crc32(template_id|mission)` (or `SIMULATION_SEED=20261005` fallback) —
  two runs of the same mission produce identical payloads (tests compare full
  fingerprints; only `ts`/`run_id` differ).
* **Honest numbers**: every metric is a measured fact of the bundled sample
  CSVs (per `data/samples/EXPECTED_INSIGHTS.md`): saas_churn 24.8% overall /
  basic 37.4% vs pro 15.5% vs enterprise 7.6% / median logins 13 vs 42;
  ecommerce Nov+Dec 27.1% of revenue / Dec $121k / mobile 33%→44% / returns
  7.9% (apparel 12.0%, books 1.8%); support billing 31% + login_bug 25% = 56% /
  integration 32.5h vs 10.0h (3.2x) / response 5.3h→7.6h / corr(csat) −0.27;
  marketing signups/$ email 1.011 > search 0.388 > content 0.321 > referral
  0.273 > social 0.034 / content compounding 0.242→0.380. Artifacts, thoughts,
  predictions and recommendations are labeled `"simulated": true`, and
  `run_started.data_grounding` names the sample dataset.
* **Story routing**: `auto_select_template(mission)` scores the 3 pinned
  template ids by keyword hits (deterministic default: `market_research_team`);
  `resolve_story_key` maps to `saas_churn` / `ecommerce_sales` /
  `support_tickets` / `marketing_spend` (mission keywords can override the
  template default — a churn mission under any template tells the churn story).
* **Plan**: uses the template's `expected_dag` when well-formed and role-pinned
  (validates ids/agents/deps), else the canonical 6-node DAG
  (planner → researcher → analyst ×2 → forecaster → critic). Artifacts include
  ChartSpec bar/pie/line charts, TableData tables, text notes, a prediction,
  a recommendation set and a final `report_markdown`.
* **Pacing**: ~33 s at `speed=1.0` for the canonical plan (static test asserts
  the designed delay sum stays within 25–45 s). `speed` divides delays;
  `speed <= 0` (or huge) plays instantly — tests run at speed 5000. Sleeps
  < 5 ms are skipped.
* **Token updates**: one `token_update` per subtask via `TokenMeter`
  (deterministic counts ~0.9–3k input / ~0.2–0.7k output; `run_total_usd`
  cumulative; math asserted against the 0.11/0.11 defaults).
* **Runner compatibility**: `SimulatedRunPlayer.__init__` accepts every kwarg
  `app/services/runner._try_simulated_player` passes (`run_id`, `mission`,
  `mission_text`, `goal`, `template`, `template_id`, `dataset_path`,
  `dataset_columns`, `dataset_info`, `on_event`), plus `speed`/`seed`;
  `play(on_event=None)` is the awaitable entrypoint the runner looks for.
  Events are validated with `make_event` before hitting the sink, and a
  raising sink cannot kill the run.

## Event flow

```
SimulatedRunPlayer.play()                 orchestrator engine (live)
  └─ on_event = EventEmitter.sync_sink()  ── same sink ──┐
                                                        ▼
                                    EventEmitter.process_event()
                                    ├─ normalize (fill run_id/seq/ts/agent)
                                    ├─ broadcaster.publish(run_id, ev)   ← WS subscribers
                                    └─ persist → agent_steps / artifacts  ← DB / snapshot API
```

The player stamps its own `seq` (1..N); `EventEmitter.observe_seq` keeps the
emitter's counter aligned, so nothing is renumbered.

## Wiring instructions

1. **Backend**: nothing to change to build/test — `runner.py` already prefers
   `realtime.simulate.SimulatedRunPlayer` in `RUN_MODE=demo` … except for the
   one-line bug below. After that fix, demo runs stream from the player.
2. **Env vars**: only the existing canonical pair
   `COST_PER_1M_INPUT_TOKENS` / `COST_PER_1M_OUTPUT_TOKENS` (already listed in
   `.env.example`). The simulator needs no env/network/keys.
3. **Frontend**: see `frontend/components/live/README.md` — swap
   `useRunStream` → `useRunStreamV2` (drop-in), add `CostBreakdown` under the
   TokenMeter card, optional `simulated`/`dataGrounding` badge.

## Tests

```
# from repo root (per brief):
python -m pytest backend/realtime/tests -q      → 71 passed in ~1s
# regression (cwd=backend, per backend/NOTES.md):
cd backend && python -m pytest tests -q         → 68 passed (WS + events + runs)
```

Also verified end-to-end manually: player → `EventEmitter.sync_sink()` →
DB persistence + broadcaster → WS-style subscriber receives the full run.

## DEVIATIONS

1. **BLOCKER in `app/services/runner.py` (Agent 2's file — I did not touch
   it):** `_try_simulated_player` iterates the signature mapping wrong:

   ```python
   for name, p in inspect.signature(SimulatedRunPlayer.__init__).parameters
   ```

   `.parameters` is a mapping, so iterating yields keys; unpacking any param
   name longer than 2 chars raises `ValueError: too many values to unpack`,
   the adapter gives up, and demo runs silently fall back to the internal
   `demo_runner` emitter. One-line fix: append `.items()`. My constructor is
   compatible with the full candidate-kwarg set (test
   `test_player_accepts_runner_kwargs_and_template_dag`), so no other change
   is needed.
2. **`artifact_created.payload.data` extension**: structured artifact bodies
   (ChartSpec / `{columns, rows}` / `{markdown}` / prediction / recommendation
   dicts) ride along as an extra `data` key beyond the pinned payload fields.
   Consumed by `useRunStreamV2` + Agent 1's `ArtifactFeed` (already renders
   `data`); documented in `frontend/components/live/README.md`.
3. **`events_dropped` control frame**: the broadcaster emits this synthetic
   non-pinned frame to lagging subscribers. Producers/consumers that filter on
   pinned `EVENT_TYPES` (frontend `parseEvent`, `EventEmitter` warnings)
   already ignore unknown types; it is a delivery marker, never persisted.
4. **`run_simulation` returns `list[dict]`** (the emitted envelopes) instead
   of `None` — needed by tests, useful for standalone demos; the brief's
   signature is otherwise unchanged.
5. **Pinned constants duplicated** in `realtime.events` (vs importing
   `app.schemas.common`) to keep `realtime` importable without the FastAPI
   app; identity is asserted by tests.
