# AgentForge

**Hire an AI team with one sentence.**

AgentForge is a multi-agent product built for ForgeHacks Online 2026 (AI + Business
track). You describe a business goal in plain language — optionally attach a CSV —
and AgentForge spawns a team of specialized AI agents that plans the work, works it,
streams every step live, and delivers a structured report: key insights, charts,
predictions, and ranked recommendations. Any finished run can be exported with one
click as an importable [n8n](https://n8n.io) workflow.

**Why this track:** the track prompt asks for an AI solution that turns business
data into clear insights, predictions, or recommendations for better decisions.
AgentForge answers it with an orchestrated agent pipeline (planner → specialist
workers → critic loop) rather than a chatbot wrapper: the plan is a real DAG, the
critic reviews every claim before it reaches the report, and the deliverable is a
decision-ready document — insights ranked by evidence strength, predictions with
stated confidence, recommendations ranked by impact vs. effort.

---

## How it works

1. **Mission** — you write a goal ("Analyze why our churn spiked in Q3 and recommend
   3 fixes") and optionally upload a CSV dataset.
2. **Planner** — decomposes the mission into a DAG of subtasks assigned to
   specialist agents (researcher, analyst, forecaster, critic).
3. **Specialists** — researcher (web search + summarize), analyst (Python over your
   CSV: stats, trends, tables, charts), forecaster (simple, explainable projections
   with stated confidence), critic (flags weak claims, ranks recommendations).
4. **Live run view** — every agent's status, summarized thoughts, tool calls,
   artifacts, and token/cost meter stream to your browser over a WebSocket.
5. **Report** — a structured deliverable (executive summary, ranked insights,
   charts, predictions, ranked recommendations), downloadable as Markdown or PDF.
6. **n8n export** — one click converts the run into an n8n workflow JSON you can
   import and extend.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Next.js 14 frontend (App Router + Tailwind + TypeScript)                    │
│  /  landing · /new  mission creator · /runs/[id]  live run view ·            │
│  /runs/[id]/report  report + downloads · /templates  template marketplace    │
└───────────────▲───────────────────────────────▲──────────────────────────────┘
                │ REST (fetch)                  │ WebSocket (live events)
┌───────────────┴───────────────────────────────┴──────────────────────────────┐
│  FastAPI backend  (uvicorn app.main:app, cwd = backend/)                     │
│  /api/missions · /api/missions/{id}/runs · /api/runs/{id} (+ /events, /WS)   │
│  /api/upload · /api/templates · /api/runs/{id}/export/n8n · /api/runs/{id}/  │
│  report · /healthz          [ SQLite + SQLAlchemy + Alembic · X-API-Key opt ]│
│                                                                              │
│  runner ──▶ orchestrator.execute_run(mission, template, dataset, on_event)   │
└───────────────┬──────────────────────────────────┬───────────────────────────┘
                │                                  │
┌───────────────▼──────────────────────┐  ┌────────▼───────────────────────────┐
│  orchestrator (pip package)          │  │  realtime broadcaster              │
│  planner ─▶ DAG of subtasks          │  │  per-run event history + WS fan-out│
│  workers: researcher / analyst /     │  │  (DB fallback replay by seq)       │
│           forecaster, then critic    │  └────────▲───────────────────────────┘
│  loop: critic reviews worker output  │           │ pinned Event envelopes
│  token/cost meter per agent          │           │ (seq, ts, agent, payload)
└───────────────┬──────────────────────┘           └────────────────────────────┘
                │ Tool interface (run() -> ToolResult + artifacts)
┌───────────────▼──────────────────────────────────────────────────────────────┐
│  agentforge_tools (pip package)                                              │
│  web_search · csv_analyzer (pandas over uploaded CSV) · sandboxed python ·   │
│  charts (matplotlib) · files                                                 │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │ artifacts + RunResult
┌───────────────▼──────────────────────────────────────────────────────────────┐
│  orchestrator.report                                                         │
│  build_report() → insights (ranked) · ChartSpecs · predictions ·             │
│  recommendations (priority-ordered) → render_markdown() / export_pdf()       │
└──────────────────────────────────────────────────────────────────────────────┘

  Post-run integrations:  POST /api/runs/{id}/export/n8n
  ──▶ integrations.n8n_export.export_n8n(run_snapshot) ──▶ importable n8n
      workflow JSON (Webhook → per-subtask DAG chain → critic IF → report)
```

The LLM layer is provider-agnostic (OpenAI-compatible client); model id and base
URL come from env vars, never hardcoded. `LLM_MODE=mock` runs the whole pipeline
deterministically offline.

## Features

- **Mission → DAG → report pipeline** — planner decomposes, specialists execute,
  critic stress-tests; nothing reaches the report unreviewed.
- **Live run view** — WebSocket stream of agent status, summarized thoughts, tool
  calls/results, and artifacts as they land (with seq-ordered replay fallback).
- **CSV-native analyst** — upload a dataset (or use the bundled samples); the
  analyst profiles columns/dtypes/quality, computes stats and trends, and emits
  table and chart artifacts.
- **Forecaster with stated confidence** — simple, explainable trend projections;
  every prediction carries a confidence and its basis.
- **Critic loop** — weak claims get downgraded before ranking; recommendations are
  ranked by expected impact vs. S/M/L effort.
- **Token/cost meter** — per-agent input/output tokens and estimated cost per run.
- **Template marketplace** — three prebuilt teams (see below) with sample missions
  and expected DAGs.
- **Report downloads** — Markdown and PDF (fpdf2).
- **One-click n8n export** — the run's plan DAG as an importable n8n workflow.
- **Demo-first** — the entire product is demoable offline with deterministic mock
  LLM responses; no keys required.

## 5-minute quickstart

Requirements: Python 3.11+ (developed on 3.13), Node.js 18+.

```bash
# 1) Backend — from the repo root
python -m venv .venv
source .venv/Scripts/activate          # Windows Git Bash (Linux/macOS: .venv/bin/activate)
pip install -r backend/requirements.txt
pip install -e packages/orchestrator -e packages/tools

# 2) Frontend
cd frontend && npm install && cd ..

# 3) Environment (optional — sane defaults work in demo mode)
cp .env.example backend/.env           # backend settings (LLM, DB, costs)
cp .env.example frontend/.env.local    # keep only the NEXT_PUBLIC_* vars

# 4) Run the backend (IMPORTANT: cwd must be backend/)
cd backend && uvicorn app.main:app --reload --port 8000

# 5) In a second terminal, run the frontend
cd frontend && npm run dev
```

Open **http://localhost:3000**. In demo mode (`RUN_MODE=demo` +
`LLM_MODE=mock` + `NEXT_PUBLIC_DEMO_MODE=1`) everything works with zero API
keys: pick a template, launch a mission (or use a sample CSV from
`data/samples/`), watch the live run view, open the report.

**Switch to live mode:** in `backend/.env` set `LLM_MODE=live`, `RUN_MODE=live`,
`LLM_API_KEY=<your key>`, and optionally `LLM_BASE_URL` / `LLM_MODEL` for your
provider (default targets an OpenAI-compatible GLM endpoint). Frontend: set
`NEXT_PUBLIC_DEMO_MODE=0` in `frontend/.env.local`. No code changes — the same
pipeline runs against the real LLM.

## Environment variables

Copy `.env.example` → `backend/.env` (backend vars) and `frontend/.env.local`
(`NEXT_PUBLIC_*` only). Never commit a real `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | OpenAI-compatible LLM endpoint |
| `LLM_API_KEY` | *(empty)* | provider API key (live mode only) |
| `LLM_MODEL` | `glm-4-flash` | primary model id |
| `LLM_FALLBACK_MODEL` | `glm-4-flash` | model tried if the primary fails |
| `LLM_MODE` | `mock` | `live` or `mock` (deterministic offline responses) |
| `LLM_TIMEOUT_SECONDS` | `60` | per-request LLM timeout |
| `API_KEY` | *(empty)* | optional; set to require `X-API-Key` on API routes |
| `RUN_MODE` | `demo` | `demo` (simulated run) or `live` (LLM pipeline) |
| `DATABASE_URL` | `sqlite:///./agentforge.db` | SQLAlchemy database URL |
| `UPLOAD_DIR` | `./data/uploads` | where uploaded CSVs land |
| `MAX_UPLOAD_MB` | `10` | upload size limit |
| `CORS_ORIGINS` | `http://localhost:3000` | allowed browser origins |
| `COST_PER_1M_INPUT_TOKENS` | `0.11` | USD per 1M input tokens (cost estimates) |
| `COST_PER_1M_OUTPUT_TOKENS` | `0.11` | USD per 1M output tokens (cost estimates) |
| `BRAVE_API_KEY` | *(empty)* | optional web-search key (DuckDuckGo provider needs none) |
| `SANDBOX_TIMEOUT_SECONDS` | `20` | analyst sandbox time limit |
| `SANDBOX_MEMORY_MB` | `256` | analyst sandbox memory limit |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | frontend → backend base URL |
| `NEXT_PUBLIC_API_WS_URL` | `ws://localhost:8000` | frontend → backend WebSocket URL |
| `NEXT_PUBLIC_DEMO_MODE` | `1` | `1` = UI runs fully offline on mock data |

## API overview

Base URL `http://localhost:8000`. Auth: optional `X-API-Key` header (enforced
only when `API_KEY` is set).

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/missions` | create a mission `{goal, template_id?, dataset_id?}` |
| GET | `/api/missions` | list missions (`?limit&offset`) |
| GET | `/api/missions/{id}` | mission detail |
| POST | `/api/missions/{id}/runs` | start a run → `{id, status:"queued"}` |
| GET | `/api/runs/{id}` | full run snapshot (run, mission, events, artifacts, token_usage, report?) |
| GET | `/api/runs/{id}/events` | poll events (`?after_seq=N`) — WS fallback |
| WS | `/api/runs/{id}/stream` | live event stream (supports `{"type":"replay","after_seq":N}`) |
| POST | `/api/upload` | multipart CSV upload → schema, preview, quality notes |
| GET | `/api/templates` | the three prebuilt team templates |
| POST | `/api/runs/{id}/export/n8n` | one-click n8n workflow JSON (attachment) |
| GET | `/api/runs/{id}/report` | report download (`?format=markdown\|pdf`) |
| GET | `/healthz` | liveness probe |

## The three templates

| Template | What it does | Sample mission |
|---|---|---|
| **Market Research Team** (`market_research_team`) | Researches a market/product/competitor question end to end: external context, data profile, trend projection, stress-tested recommendations. | "Assess whether there is demand for a subscription meal-planning app in mid-size US cities and recommend a launch position." |
| **Sales Insights Team** (`sales_insights_team`) | Turns a sales/revenue CSV into insights: pipeline profile, drivers and outliers, next-period forecast, ranked revenue actions. | "Analyze last quarter's sales CSV to find which regions and products drove the miss, and recommend 3 fixes for next quarter." |
| **Support Triage Team** (`support_triage_team`) | Profiles a ticket export: themes, SLA risks, load forecast, and ranked triage fixes. | "Our support tickets spiked in September — find the top themes and SLA risks from the ticket CSV and recommend 3 triage fixes." |

Each template pins a team of role-specific agents (planner, researcher, analyst,
forecaster, critic), a planner prompt, a sample mission, an expected DAG, and a
report outline — browsable at `/templates` or via `GET /api/templates`.

## n8n export guide

1. **Run a mission** (demo or live) and wait for it to finish.
2. **Export**: click the export action in the UI, or
   `curl -X POST http://localhost:8000/api/runs/{run_id}/export/n8n -o workflow.json`
   (the run snapshot — plan DAG, mission, report — is baked into the workflow).
3. **Import into n8n Cloud**: *Workflows → Import from File* (or *Import from
   JSON* on the workflow page) and select the downloaded file.
4. **Point it at your backend**: every HTTP node resolves its URL from
   `$env.AGENTFORGE_API_URL || 'http://agentforge-backend:8000'`. On
   self-hosted n8n, set the `AGENTFORGE_API_URL` environment variable and it
   flows through. On **n8n Cloud**, `$env` access in expressions is blocked —
   either replace that fragment with your literal AgentForge URL (two places:
   the "Mission Context" Set node and any expression you re-point) or define an
   n8n Variable and use `$vars.AGENTFORGE_API_URL` instead.
5. **Trigger it**: POST to the workflow's webhook at
   `/<webhook-path>` (path: `agentforge-run-{run_id}`) with an optional JSON body
   `{run_id, mission_id, goal, template_id}` to override the baked-in mission.

What the imported workflow contains (core n8n node types only):

```
Webhook Trigger → Mission Context (Set)
  → per plan subtask, topological order:
      [NoOp join when a step has 2+ dependencies]
      → "Context [agent]: title" (Set, assembles the step's context)
      → "Run Step [agent]: title" (HTTP Request, POSTs context to the backend)
  → Critic Verdict (IF)
      true  → Assemble Report (Code) → Deliver Report (HTTP Request)
      false → Flagged for Rework (NoOp — plug your rework/retry path here)
```

Honest notes, also documented in `backend/integrations/NOTES.md`:

- No plan event in the run? The export falls back to a linear pipeline
  (planner → analyst → critic → report).
- The per-step URLs follow the convention
  `POST {base}/api/runs/{run_id}/steps/{subtask_id}`. The pinned v1 backend
  exposes run-level endpoints, so step-by-step re-driving against a stock
  backend expects a small step-endpoint shim — or repoint those URLs at your own
  workers inside n8n. The DAG wiring, critic branch, and report delivery are real.
- The final node POSTs the assembled report to
  `{base}/api/runs/{run_id}/report`; the pinned API *serves* reports at
  `GET /api/runs/{id}/report` — flip the method in n8n to fetch instead.
- Committed examples (with their input snapshots) live in
  `backend/integrations/examples/` — generated by `make_examples.py`.

## Project structure

```
agentforge/
├── frontend/                     # Next.js 14 App Router UI (landing, /new,
│                                 #   /runs/[id] live view, /runs/[id]/report, /templates)
├── backend/
│   ├── app/                      # FastAPI app: routes, schemas, services, models, templates
│   ├── connectors/               # CSV parsing (upload + pasted tables + samples)
│   ├── integrations/             # n8n export (this repo's sponsor-tie-in module)
│   │   ├── n8n_export.py         #   export_n8n(run_snapshot) -> n8n workflow JSON
│   │   ├── tests/                #   export test suite
│   │   └── examples/             #   committed example exports + generator
│   ├── realtime/                 # WS broadcaster + event helpers
│   ├── alembic/                  # DB migrations (alembic.ini at backend/)
│   ├── tests/                    # backend API test suite
│   └── data/uploads/             # uploaded datasets
├── packages/
│   ├── orchestrator/             # pip pkg `orchestrator`: engine, planner, agents,
│   │   ├── orchestrator/report/  #   report builder + markdown/PDF renderers
│   │   └── orchestrator/templates/ # template logic
│   └── tools/                    # pip pkg `agentforge_tools`: web search, CSV
│                                 #   analyzer, sandbox, charts, files
├── data/samples/                 # 4 sample CSVs + data dictionaries
├── docs/                         # SPEC.md, INTERFACES.md (pinned contracts), launch/
├── scripts/                      # sample-data generator
├── .env.example                  # canonical env vars (coordinator-owned)
├── SPONSORS.md                   # sponsor perk → integration point mapping
└── README.md                     # this file
```

## Testing

All Python tests run in the shared venv (`.venv`). Commands verified on this repo:

```bash
# Backend API suite (routes, auth, WS, run lifecycle, error paths)
cd backend && python -m pytest tests/ -q                 # 68 passed

# n8n export module (from the repo root)
python -m pytest backend/integrations/tests -q           # 17 passed

# CSV connectors
python -m pytest backend/connectors/tests -q

# Orchestrator (engine, planner, agents, templates)
python -m pytest packages/orchestrator/tests -q
python -m pytest packages/orchestrator/orchestrator/report/tests -q
python -m pytest packages/orchestrator/orchestrator/templates/tests -q

# Tools package
python -m pytest packages/tools/tests -q
```

Frontend: `cd frontend && npm run build` for a type-checked production build.

Regenerate the committed n8n examples (deterministic):

```bash
python backend/integrations/examples/make_examples.py
```

## Roadmap

Honest next steps, roughly in order of leverage:

1. **Step-level re-drive endpoint** — a small backend route so the exported n8n
   workflows re-drive individual plan subtasks against a stock deployment
   (the export already targets `POST /api/runs/{id}/steps/{subtask_id}`).
2. **Adaption integration** — stream/ship the pinned run-event log to an
   evaluation service for step-level agent analytics.
3. **ProjectAAL export** — sibling exporter that serializes the plan DAG into
   the open agent language, next to the n8n exporter.
4. **YouCam product-shot tool** — image-analysis tool for the market-research
   team (new `Tool` + artifact kind).
5. **Template marketplace packaging** — publish the three team templates as
   marketplace listings with the template JSON as the contract.
6. **Vector memory (optional v1.x)** — pluggable interface for Pinecone/Qdrant
   alongside the simple local store.
7. **Deployment** — `docker-compose.yml` (backend + frontend + DB) and a hosted
   reference deployment.
8. **Auth hardening** — per-user missions and API keys beyond the single
   optional `X-API-Key`.

## Honesty notes

- Demo mode is clearly labeled in-product; mock LLM output is deterministic
  canned data, never presented as live model output.
- No real API keys exist anywhere in this repo; all configuration flows through
  `.env.example` → local `.env` files.
- Sponsor integrations that exist are marked as built in `SPONSORS.md`; anything
  not built is described as a next step, not a feature.
