# AgentForge × ForgeHacks Sponsors

How each sponsor perk maps to a concrete integration point in AgentForge.
Everything under "exists today" is in this repo; everything under "would plug
in" is a real next step, not a claim that it works today. No fabricated
integrations, no invented metrics.

---

## n8n — workflow automation *(built)*

One click on a finished run (or `POST /api/runs/{id}/export/n8n`) returns an
importable n8n workflow JSON: a Webhook trigger → per-subtask chain mirroring
that run's plan DAG (Set + HTTP Request + NoOp joins) → an IF node on the critic
verdict → a Code node that assembles the report and an HTTP Request that
delivers it. Implementation: `backend/integrations/n8n_export.py` (core node
types only; deterministic output; every URL points at your AgentForge backend
via `$env.AGENTFORGE_API_URL`). Two committed examples live in
`backend/integrations/examples/`, and the import flow is documented in the
README's n8n export guide.

## Momen — no-code app front-end

Exists today: AgentForge's backend is a clean REST + WebSocket API (pinned in
`docs/INTERFACES.md`) with configurable CORS (`CORS_ORIGINS`), so any external
front-end can drive it. Would plug in: a Momen app could serve as the mission
front-end — forms calling `POST /api/missions` and `POST /api/missions/{id}/runs`,
list views over `GET /api/missions`, and embedded AgentForge report views
(`GET /api/runs/{id}/report`) inside a Momen page. No backend changes should be
required beyond allowing the Momen origin in `CORS_ORIGINS`.

## Featherless — open-model LLM provider

Exists today: the LLM layer is provider-agnostic with an OpenAI-compatible
client configured entirely by env (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`,
`LLM_FALLBACK_MODEL` — see `.env.example`); model ids are never hardcoded.
Would plug in: pointing `LLM_BASE_URL` at Featherless' OpenAI-compatible
endpoint and setting `LLM_MODEL` to a hosted open model switches AgentForge's
planner/researcher/analyst/forecaster/critic onto Featherless with zero code
changes; the existing `LLM_FALLBACK_MODEL` chain maps naturally onto trying a
second open model on failure.

## Adaption — agent evaluation & analytics

Exists today: every run emits the pinned event envelope (`agent_started`,
`thought_summary`, `tool_call`/`tool_result`, `step_completed`, `token_update`,
...) which is persisted to the `agent_steps` table and queryable via
`GET /api/runs/{id}/events?after_seq=N` — a ready-made, seq-ordered telemetry
feed of what each agent did and what it cost. Would plug in: an exporter/sender
that streams or webhooks that event log to Adaption for step-level evaluation
and analytics; the data contract already exists, the sender does not (yet).

## YouCam (Perfect Corp) — imaging / product-shot AI

Exists today: a typed Tool interface (`agentforge_tools.base.Tool` with
`parameters_json_schema` and `run() -> ToolResult` carrying artifact dicts) and
the `market_research_team` template that researcher/analyst agents execute
under. Would plug in: a YouCam product-shot analysis tool registered in the
tool registry so the market-research team can ingest product imagery and emit a
"visual audit" artifact alongside its tables and charts; this needs a new tool
module (and likely one new artifact kind) and has not been built.

## Agentboxd — agent marketplace

Exists today: the three prebuilt teams — `market_research_team`,
`sales_insights_team`, `support_triage_team` — are JSON-defined agent-team
specs (team roles + system prompts, planner prompt, sample mission,
`expected_dag`, report outline) served at `GET /api/templates`. Would plug in:
each template is a natural marketplace listing unit for Agentboxd; publishing
them would mean packaging that JSON (plus sample mission + expected DAG) as a
listing. Packaging/listing itself is not built.

## DevSwarm — multi-agent development

Exists today, as the development method: this repo was built by ten parallel
agents working from frozen contracts (`docs/SPEC.md`, `docs/INTERFACES.md`)
with strict module ownership — the same planner → workers → critic pattern
AgentForge itself implements. The pinned event envelope and run-snapshot shape
are what let independently-written frontend, backend, orchestrator, tools, and
integration modules merge without integration drift. A write-up of that
contract-first multi-agent workflow is fair game for a DevSwarm showcase.

## ProjectAAL — open agent language

Exists today: plans are structured DAGs — `plan_created` events carry
`{"subtasks": [{"id","title","agent","depends_on"}, ...]}` — and the n8n
exporter (`backend/integrations/n8n_export.py`) already consumes exactly that
shape to generate executable workflow graphs. Would plug in: a ProjectAAL
exporter as a sibling module mapping the same subtask DAG into the AAL agent
language, giving runs a second open, tool-agnostic serialization; the exporter
interface precedent (`export_n8n(run_snapshot) -> dict`) exists, the AAL module
does not yet.

## Kariaa — deployment / hosting

Exists today: a deployment-shaped stack — FastAPI backend (uvicorn entrypoint,
`/healthz`, Alembic migration, env-driven `DATABASE_URL`/`CORS_ORIGINS`,
SQLite by default), Next.js 14 frontend, and a demo-first mode that runs with
zero external keys. Would plug in: containerizing the two services (the repo
plans a `docker-compose.yml`) and hosting them on Kariaa; the live-mode env
vars (`LLM_*`) are the only secrets a deployment needs. Nothing is deployed
yet — the quickstart in the README is the local path.
