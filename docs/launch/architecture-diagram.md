# AgentForge — Architecture Diagram (paste-ready for Devpost)

Paste the fenced block below into the Devpost description as a code block so the
monospace art survives. The data-flow walkthrough under it can be pasted as plain
Markdown.

````text
                          ┌─────────────────────────────────────────────┐
                          │               Browser (user)                │
                          │      Next.js 14 · App Router · Tailwind     │
                          │   /   /new   /runs/[id]   /runs/[id]/report │
                          │                 /templates                  │
                          └──────────────┬────────────────┬─────────────┘
                     REST (fetch)        │                │  WebSocket
        POST /api/upload · /api/missions │                │  WS /api/runs/{id}/stream
        POST /api/missions/{id}/runs     │                │  pinned event envelopes,
        GET /api/runs/{id} · /report     │                │  replay-by-seq fallback
                          ┌──────────────▼────────────────▼─────────────┐
                          │        FastAPI backend (uvicorn)            │
                          │  routes · SQLite (SQLAlchemy + Alembic)     │
                          │  runner ──► orchestrator.execute_run(       │
                          │      mission, template_id, dataset,         │
                          │      dataset_columns, on_event)             │
                          └──────────────┬────────────────┬─────────────┘
                                         │                │ every event:
             ┌───────────────────────────▼──┐   ┌───────────▼──────────────┐
             │  orchestrator (pip package)  │   │ realtime broadcaster     │
             │  planner → DAG of subtasks   │   │ per-run event history +  │
             │  workers, topological order: │   │ WS fan-out; events also  │
             │    researcher · analyst ·    │   │ persisted (DB fallback   │
             │    forecaster → critic loop  │   │ replay after_seq=N)      │
             │  critic: downgrade weak      │   └──────────────────────────┘
             │  claims, re-rank; token/cost │
             │  meter per agent             │   Event envelope (pinned):
             └───────────────┬──────────────┘   {type, run_id, seq, ts,
                             │ Tool interface    agent, payload}
                             │ run() → ToolResult + artifacts
             ┌───────────────▼───────────────────────────────────────────┐
             │  agentforge_tools (pip package)                           │
             │  web_search · csv_analyzer (pandas over uploaded CSV) ·   │
             │  sandboxed python (timeout + memory caps) · charts        │
             │  (matplotlib) · files                                     │
             └───────────────┬───────────────────────────────────────────┘
                             │ RunResult (plan, steps, artifacts, token_usage)
             ┌───────────────▼───────────────────────────────────────────┐
             │  orchestrator.report                                      │
             │  build_report() → executive summary · insights (ranked,   │
             │  evidence + strength) · ChartSpecs · predictions          │
             │  (confidence + basis) · recommendations (priority)        │
             │  → render_markdown() · export_pdf() (fpdf2)               │
             └───────────────────────────────────────────────────────────┘

  LLM layer (provider-agnostic, env-driven): LLM_BASE_URL / LLM_MODEL /
  LLM_FALLBACK_MODEL — OpenAI-compatible client; default targets a GLM endpoint.
  LLM_MODE=mock → deterministic offline responses. RUN_MODE=demo → SimulatedRunPlayer
  drives the same event pipeline with no LLM at all.

  Post-run export:  POST /api/runs/{id}/export/n8n
    └► integrations.n8n_export.export_n8n(run_snapshot)
        └► importable n8n workflow JSON (core node types only):
           Webhook Trigger → Mission Context (Set)
             → per subtask (topological): Context (Set) → Run Step (HTTP Request)
             → Critic Verdict (IF) → Assemble Report (Code) → Deliver Report (HTTP)
````

## Data-flow walkthrough: one run of the churn mission

1. **Upload.** On `/new` the browser `POST`s `saas_churn.csv` to `/api/upload`; the connector profiles it (row count, columns, dtypes, preview, quality notes) and returns a `dataset_id`.
2. **Mission.** The frontend `POST`s `/api/missions` with `{goal: "Analyze why our churn spiked and recommend 3 fixes", dataset_id}` — a Mission row is stored.
3. **Run start.** `POST /api/missions/{id}/runs` returns `{id, status: "queued"}` and the backend runner invokes `orchestrator.execute_run(...)` with the mission, dataset path/columns, and an `on_event` callback.
4. **Planning.** The planner produces a DAG of subtasks assigned to researcher/analyst/forecaster/critic; `run_started` and `plan_created` (subtasks with `depends_on`) are emitted through `on_event`.
5. **Fan-out.** Every event goes two places at once: to the realtime broadcaster (per-run history + WebSocket fan-out to the `/runs/[id]` page) and to persistence, so a reconnecting client can replay by sequence number.
6. **Workers.** The engine walks the DAG in topological order. Per subtask it emits `agent_started`, `thought_summary`, `tool_call`/`tool_result`, `artifact_created`, `step_completed`, `agent_finished`. The researcher calls the web-search tool; the analyst runs the pandas CSV analyzer and charting; the forecaster computes projections — each `ToolResult` carries artifacts (tables, charts, predictions).
7. **Meter.** Along the way `token_update` events feed the per-agent token/cost meter shown in the run view.
8. **Critic loop.** After the workers, the critic reviews their outputs: weak claims get downgraded (strength low/medium), and recommendations are re-ranked by expected impact vs. S/M/L effort.
9. **Report.** In finalize, the engine calls `orchestrator.report.build_report(run_result)` → the canonical report dict (executive summary, ranked insights, ChartSpecs, predictions with confidence, priority-ranked recommendations). `GET /api/runs/{id}/report?format=markdown|pdf` renders/downloads it; `run_finished {report_ready: true}` closes the stream.
10. **Failure path.** Any uncaught stage failure emits `run_failed {error, stage}` and the run view shows it honestly — nothing partial is dressed up as a report.
11. **Export.** One click `POST`s `/api/runs/{id}/export/n8n`; `export_n8n(run_snapshot)` converts the plan DAG into an importable n8n workflow (Webhook → per-subtask Set/HTTP chain → critic IF → report nodes).
12. **Modes.** Steps 3–11 run unchanged in every mode: `LLM_MODE=live` against an OpenAI-compatible GLM endpoint (env-configured), `LLM_MODE=mock` with deterministic canned responses, or `RUN_MODE=demo` with the SimulatedRunPlayer driving the same events — which is how the demo video runs offline.
