# AgentForge — Pinned Interfaces (v1, 2026-10-05)

Every agent codes against these contracts. If you must deviate, record it under
`DEVIATIONS` in your module's NOTES.md — the coordinator reconciles at merge.

## Repo layout & ownership (touch ONLY your dirs)

```
agentforge/
├── frontend/                  # Agent 1 (Agent 7 may add frontend/components/live/* + frontend/hooks/*)
├── backend/
│   ├── app/                   # Agent 2 (FastAPI app; runs with cwd=backend, import root)
│   ├── connectors/            # Agent 5 (package import name: connectors)
│   ├── integrations/          # Agent 9 (package import name: integrations)
│   ├── realtime/              # Agent 7 (package import name: realtime)
│   ├── tests/                 # Agent 2 (+ focused tests by 5/7/9 allowed inside their dirs)
│   ├── alembic/               # Agent 2 (migrations; alembic.ini at backend/)
│   └── data/uploads/          # uploaded datasets land here: data/uploads/{dataset_id}.csv
├── packages/orchestrator/     # Agent 3 (pip pkg, import name: orchestrator)
│   └── orchestrator/report/   # Agent 6 (subpackage of orchestrator)
│   └── orchestrator/templates/# Agent 8 (subpackage of orchestrator)
├── packages/tools/            # Agent 4 (pip pkg, import name: agentforge_tools)
├── data/samples/              # Agent 5 (4 sample CSVs + generator script in scripts/)
├── docs/launch/               # Agent 10 (all launch/devpost docs)
├── docs/SPEC.md, INTERFACES.md# coordinator-owned — DO NOT EDIT
├── .env.example               # coordinator-owned — list needed vars in your NOTES.md
├── README.md                  # Agent 9 (full readme)
├── docker-compose.yml         # coordinator-owned
```

Backend is ALWAYS run with `cwd = backend/` (`uvicorn app.main:app`). Import roots
available from there: `app`, `connectors`, `integrations`, `realtime`, plus installed
packages `orchestrator`, `agentforge_tools`.

## Python packaging
- `packages/orchestrator/pyproject.toml` → pip-installable, import package `orchestrator`
  (src layout: `packages/orchestrator/orchestrator/...`). Deps: httpx, pydantic only
  (+ pandas/matplotlib optional via extras — do NOT require them at import time).
- `packages/tools/pyproject.toml` → import package `agentforge_tools`. May require
  pandas, matplotlib, pydantic, httpx.
- Shared venv at `<repo>/.venv` (preinstalled: fastapi uvicorn[standard] sqlalchemy
  alembic pydantic pydantic-settings httpx python-multipart python-dotenv pytest
  pytest-asyncio pandas numpy matplotlib fpdf2 markdown openai websockets).

## Event envelope (WS + DB + frontend — canonical)
```json
{
  "type": "<event_type>",       // see list below
  "run_id": "uuid",
  "seq": 12,                    // monotonic per run, starts at 1
  "ts": "2026-10-05T12:00:00Z", // ISO-8601 UTC
  "agent": "analyst",           // agent role or null
  "payload": { }
}
```
Event types (exact strings): `run_started`, `plan_created`, `agent_started`,
`thought_summary`, `tool_call`, `tool_result`, `artifact_created`, `step_completed`,
`agent_finished`, `run_finished`, `run_failed`, `token_update`.

Payload schemas:
- `plan_created` → `{"subtasks": [{"id","title","agent","depends_on": ["<id>"], "status"}]}`
- `agent_started` → `{"subtask_id","title"}`
- `thought_summary` → `{"subtask_id","summary"}` (1–2 sentences, human-readable)
- `tool_call` / `tool_result` → `{"subtask_id","tool","args_summary","ok"}`
- `artifact_created` → `{"subtask_id","artifact_id","kind","name","summary","path"?}`
- `step_completed` → `{"subtask_id"}`
- `token_update` → `{"agent","input_tokens","output_tokens","cost_usd","run_total_usd"}`
- `run_finished` → `{"report_ready": true}`
- `run_failed` → `{"error","stage"}`

Agent roles (exact strings): `planner`, `researcher`, `analyst`, `forecaster`, `critic`.

## Artifact kinds (exact strings)
`chart` | `table` | `text` | `prediction` | `recommendation` | `report_markdown` |
`report_pdf` | `file`

## Chart spec (tools → report → frontend)
```json
{"id":"chart_1","kind":"bar|line|scatter|pie","title":"...",
 "x_label":"...","y_label":"...",
 "data":[{"label":"...","x":123,"y":456}],"notes":"..."}
```

## Report model (canonical, produced by orchestrator.report)
```json
{
  "title": "...", "mission": "...", "style": "default|market_research|sales_insights|support_triage",
  "executive_summary": "...",
  "insights": [{"title","detail","evidence": ["..."],"strength": "high|medium|low"}],   // ranked
  "charts": [ /* ChartSpec */ ],
  "predictions": [{"claim","confidence": 0.87,"basis": "..."}],
  "recommendations": [{"title","action","expected_impact","effort": "S|M|L","priority": 1}],
  "appendix": "..."
}
```
`priority` 1 = do first. Renderers: `render_markdown(report) -> str`,
`export_pdf(report_or_markdown, out_path) -> Path` (fpdf2; no weasyprint — Windows).

## Tool interface (packages/tools/agentforge_tools/base.py)
```python
class Tool(ABC):
    name: str; description: str
    parameters_json_schema: dict          # JSON Schema for LLM function-calling
    def run(self, inputs: dict) -> ToolResult: ...
@dataclass
class ToolResult:
    ok: bool
    data: dict | None = None              # JSON-serializable
    error: str | None = None
    artifacts: list[dict] = field(default_factory=list)  # e.g. ChartSpec dicts
```

## Orchestrator entrypoint (packages/orchestrator/orchestrator/engine.py)
```python
async def execute_run(
    mission: str,
    template_id: str | None = None,
    dataset_path: str | None = None,
    dataset_columns: list[str] | None = None,
    on_event: Callable[[dict], None] | None = None,   # receives pinned Event envelopes
    max_steps: int = 24,
) -> RunResult
```
`RunResult` (dataclass, `.to_dict()` JSON-safe): `{run_id, mission, status
("succeeded"|"failed"|"partial"), plan: [subtask dicts], steps: [step dicts],
artifacts: [artifact dicts], token_usage: {"per_agent": {role: {"input_tokens",
"output_tokens","cost_usd"}}, "totals": {...}}, report: dict | None, errors: [str]}`.
Emit every pinned event via `on_event`. Must work fully offline with `LLM_MODE=mock`.

Report integration: `from orchestrator.report import build_report` →
`build_report(run_result: dict, style: str = "default") -> dict` (Agent 6). Engine
should call it in finalize if importable; degrade gracefully if not.

## Backend API (Agent 2 — Agent 1's typed client mirrors exactly)
Base URL `http://localhost:8000`. CORS: `http://localhost:3000`. Auth: optional
`X-API-Key` header (checked only when env `API_KEY` is set; guest mode otherwise).

| Method | Path | Request → Response |
|---|---|---|
| POST | /api/missions | `{goal, template_id?, dataset_id?}` → Mission |
| GET | /api/missions | `?limit&offset` → `{missions, total}` |
| GET | /api/missions/{id} | → Mission |
| POST | /api/missions/{id}/runs | `{}` (or `{template_id?}`) → Run `{id, status:"queued"}` |
| GET | /api/runs/{id} | → RunSnapshot `{run, mission, events: [Event], artifacts, token_usage, report?}` |
| GET | /api/runs/{id}/events | `?after_seq=N` → `{events: [Event]}` (polling fallback) |
| WS | /api/runs/{id}/stream | server pushes Event envelopes; client may send `{"type":"replay","after_seq":N}` or `{"type":"ping"}` |
| POST | /api/upload | multipart `file` (.csv, ≤ MAX_UPLOAD_MB) → `{id, filename, row_count, columns: [..], dtypes: {..}, preview: [[..≤20 rows]], quality_notes: [..]}` |
| GET | /api/templates | → `{templates: [Template]}` |
| POST | /api/runs/{id}/export/n8n | → n8n workflow JSON (attachment) |
| GET | /api/runs/{id}/report | `?format=markdown\|pdf` → file download |
| GET | /healthz | → `{status:"ok"}` |

Core shapes:
- `Mission`: `{id, goal, template_id?, dataset_id?, created_at}`
- `Run`: `{id, mission_id, status: "queued"|"running"|"succeeded"|"failed"|"partial", created_at, finished_at?}`
- `Template`: `{id, name, description, tags: [], team: [{role, title, system_prompt}], planner_prompt, sample_mission, expected_dag: [{id,title,agent,depends_on}], report_outline: []}`

Template ids (exact): `market_research_team`, `sales_insights_team`, `support_triage_team`.

## Module import contracts
- Broadcaster (Agent 7 owns `backend/realtime/broadcaster.py`; a minimal coordinator
  stub exists until replaced):
  `from realtime.broadcaster import get_broadcaster` → singleton with
  `async publish(event: dict)`, `subscribe(run_id) -> AsyncIterator[dict]`,
  `history(run_id) -> list[dict]`, `replay_after(run_id, seq) -> list[dict]`,
  `clear(run_id)`.
- Connectors (Agent 5 owns `backend/connectors/`; minimal stub exists):
  `from connectors import parse_csv, parse_pasted_table` →
  `ParsedDataset {filename, row_count, columns, dtypes, preview, quality_notes}`.
  Also `load_sample(sample_id) -> tuple[ParsedDataset, dict]` for the 4 samples.
- n8n export (Agent 9): `from integrations.n8n_export import export_n8n` →
  `export_n8n(run_snapshot: dict) -> dict` where run_snapshot = GET /api/runs/{id}
  response shape. Output: `{"name", "nodes": [...], "connections": {...}}` importable
  n8n JSON (core node types only: Webhook, HTTP Request, Set, Code, IF, NoOp).
- Token meter (Agent 7): costs via env `COST_PER_1M_INPUT_TOKENS`,
  `COST_PER_1M_OUTPUT_TOKENS` (USD per 1M tokens).

## Env vars (canonical names — see .env.example)
LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL, LLM_MODE (live|mock),
LLM_TIMEOUT_SECONDS · API_KEY, RUN_MODE (demo|live), DATABASE_URL, UPLOAD_DIR,
MAX_UPLOAD_MB, CORS_ORIGINS · COST_PER_1M_INPUT_TOKENS, COST_PER_1M_OUTPUT_TOKENS ·
BRAVE_API_KEY, SANDBOX_TIMEOUT_SECONDS, SANDBOX_MEMORY_MB · NEXT_PUBLIC_API_BASE_URL,
NEXT_PUBLIC_API_WS_URL, NEXT_PUBLIC_DEMO_MODE

## Demo-first rule
Everything must be demoable offline: `LLM_MODE=mock` (deterministic canned LLM
responses, clearly labeled) + `RUN_MODE=demo` (Agent 7's SimulatedRunPlayer drives
realistic events with no LLM) + frontend `NEXT_PUBLIC_DEMO_MODE=1` (mock API client).
The live demo video will be recorded in demo mode; live mode is the same pipeline
with a real LLM key.
