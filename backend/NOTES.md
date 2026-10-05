# AgentForge backend — Agent 2 NOTES

Status: **complete**. All pinned routes implemented per `docs/INTERFACES.md`;
`python -m pytest tests/ -x -q` → **68 passed** (from `backend/`). Standalone
boot verified: `cd backend && uvicorn app.main:app` → `/healthz`,
`/api/templates`, `/openapi.json` (all 10 pinned HTTP paths registered).

## File map

```
backend/
├── alembic.ini                  # alembic config at backend/ (as pinned)
├── alembic/
│   ├── env.py                   # DATABASE_URL from env → app.config; batch mode for sqlite
│   ├── script.py.mako
│   └── versions/e823894fa14b_initial_schema.py   # full initial migration (upgrade/downgrade verified)
├── requirements.txt             # mirror of the shared venv
├── pytest.ini                   # asyncio_mode=auto, testpaths=tests
├── app/
│   ├── main.py                  # app factory, CORS, exception handlers, tags, lifespan (init_db+seed)
│   ├── config.py                # pydantic-settings; canonical env vars documented in docstring
│   ├── models.py                # User, Mission, Run, AgentStep, Artifact, Template, Dataset
│   ├── templates_data.py        # the 3 pinned templates (real prompts) + seed/lookup helpers
│   ├── db/base.py               # lazy engine/sessionmaker, session_scope(), init_db(), template seeding
│   ├── schemas/                 # common (envelope), mission, run, upload, template
│   ├── api/deps.py              # get_db, require_api_key (X-API-Key only when API_KEY set), WS auth
│   ├── api/router.py            # /api aggregation; /healthz mounted at root, no auth
│   ├── api/routes/              # missions, runs (+WS), uploads, templates, integrations, health
│   └── services/
│       ├── events.py            # EventEmitter: envelope build/normalize, broadcaster publish (signature-adaptive), DB persistence
│       ├── runner.py            # background execution: demo (player→fallback) / live (orchestrator), finalization
│       ├── demo_runner.py       # internal fallback demo emitter (deterministic, labeled simulated)
│       └── snapshot.py          # RunSnapshot assembly; broadcaster-first, DB-fallback history
└── tests/                       # 68 tests: every route, auth on/off, WS, lifecycle, 501/404 paths, units
```

## Key design decisions

1. **Event pipeline.** One `EventEmitter` per run owns seq allocation
   (per-run monotonic from 1, seeded from DB max on re-drive), publishes via
   the broadcaster, and persists every event to `agent_steps` (pinned
   envelope). `artifact_created` events upsert `artifacts` rows;
   `token_update` events accumulate the run's token/cost meter;
   `plan_created` is stored on the run. The broadcaster's *returned* event is
   treated as canonical (respects any seq stamping Agent 7 adds).
2. **Broadcaster signature adaptivity.** INTERFACES.md shows
   `publish(event)`; the coordinator stub uses `publish(run_id, event)`.
   `publish_event()` inspects the installed broadcaster once (cached attr) and
   adapts, so Agent 7's replacement drops in without backend changes.
3. **History source of truth.** Live serving prefers the in-memory broadcaster;
   if it has nothing for a run (process restart), events are replayed from
   `agent_steps`. WS connect subscribes *before* snapshotting history and
   dedupes by seq, so no event is lost or duplicated across the handoff.
4. **Run execution.** `POST .../runs` inserts the Run (queued) and schedules
   `execute_run_background` with `asyncio.create_task` on the server loop
   (strong ref kept in `runner._tasks`). Demo: try
   `realtime.simulate.SimulatedRunPlayer` (kwargs filtered by its signature;
   `play/run/execute/start` coroutine probed) → on any failure falls back to
   `app/services/demo_runner.py`. Live: `orchestrator.engine.execute_run` with
   the pinned signature and a sync `on_event` sink; import failure → run
   **failed** with `run_failed {stage: "startup"}` — never faked.
   `RunResult.to_dict()` feeds `token_usage_json` / `report_json` / status
   (succeeded|failed|partial).
5. **WS route.** Handles `{"type":"replay","after_seq":N}` and `{"type":"ping"}`
   (replies `{"type":"pong", run_id, ts}` — a control message outside the
   pinned event list); unknown/bad messages get `{"type":"error", ...}`.
   Unknown run → accept, error message, `close(4404)`; unauthorized →
   `close(4401)`.
6. **Graceful integrations.** n8n export / report routes import
   `integrations.n8n_export` / `orchestrator.report` lazily *inside the
   handler* and return **501 + clear JSON error** when missing (never fake).
   `/api/runs/{id}` always carries the raw `report` dict when the run has one,
   so the frontend can render natively even while the renderers are pending.
7. **Auth.** `X-API-Key` enforced only when `API_KEY` is set (dependency reads
   injected `Settings`, so tests override cleanly). Router-level deps can't run
   for WebSockets, so the runs router applies auth per HTTP route and the WS
   route checks header-or-`?api_key=` itself.

## Env vars consumed

Exactly the pinned set: `API_KEY, RUN_MODE, DATABASE_URL, UPLOAD_DIR,
MAX_UPLOAD_MB, CORS_ORIGINS, COST_PER_1M_INPUT_TOKENS,
COST_PER_1M_OUTPUT_TOKENS, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL,
LLM_FALLBACK_MODEL, LLM_MODE, LLM_TIMEOUT_SECONDS`.

**New var proposed for coordinator's `.env.example`:** `REPORT_DIR`
(default `./data/reports`) — where PDF downloads are rendered before
`FileResponse`. No other new vars.

## DEVIATIONS / assumptions for reconciliation

- **Status codes:** 201 for creates (`POST /missions`, `.../runs`,
  `/upload`), 200 elsewhere; errors are JSON
  `{error, status_code, detail}`. INTERFACES.md doesn't pin these.
- **`report` in RunSnapshot is passed through unvalidated** (plain dict) — it
  crosses the orchestrator boundary; over-validating risks 500s on Agent 6
  variations. Shape is documented in schemas/run.py.
- **`agent_steps` stores every event** (not just agent-attributed ones) — it is
  the run's event log; the model name keeps the brief's contract.
- **Extra Run fields** (`mode`, `template_id`, `error`, `error_stage`) beyond
  the pinned `{id, mission_id, status, created_at, finished_at?}` — additive
  only.
- **`pong` / `error` WS message types** are control frames outside the pinned
  event list (only ever server→client responses).
- **SimulatedRunPlayer adapter is speculative** (Agent 7's module didn't exist
  when built): constructor kwargs filtered via `inspect.signature`, terminal
  coroutine probed among `play/run/execute/start`. If none fits, the run uses
  the internal demo emitter (logged). A player that runs but never emits
  `run_finished`/`run_failed` marks the run failed (honest).
- **Demo mode content is labeled simulated everywhere** (payloads carry
  `"simulated": true`; report appendix states no LLM was used). Demo
  `token_update` counts are deterministic placeholders priced with the
  configured COST_PER_1M_* rates.
- **Alembic + `create_all` at startup:** Alembic is canonical
  (`alembic upgrade head` verified up/down); lifespan also runs
  `create_all` so sqlite demo boots never hit a missing-table wall.
- **SQLAlchemy 2.1 note:** `sessionmaker` no longer supports the context-
  manager protocol; services use `db.base.session_scope()`.
- **Tests:** session-scoped `TestClient` used as a context manager so the
  portal loop survives across requests (background tasks progress between
  calls). Cross-agent modules are pinned in tests via `sys.modules` tricks
  (fake module for 200 paths, `None` sentinel to force ImportError for 501
  paths), so the suite is deterministic regardless of agents 3/6/9 landing
  state. `orchestrator.report`'s real markdown renderer is exercised when
  installed (skipped otherwise).

## Known upstream issues (not mine to fix)

- `orchestrator.report.export_pdf` (Agent 6) currently raises on the demo
  report ("sequence item 0: expected str instance, list found" in
  `_write_table`); the backend surfaces it as a clean 500 with detail.
- `realtime.simulate` (Agent 7) and `integrations.n8n_export` (Agent 9) not
  landed yet → backend uses the documented fallbacks/501s.
