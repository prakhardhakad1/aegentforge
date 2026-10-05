# AgentForge — Product Spec (v1, frozen 2026-10-05)

ForgeHacks Online 2026 · AI + Business track
One-line pitch: **"Hire an AI team with one sentence."**

A user describes a business goal in plain language; AgentForge spawns a team of
specialized AI agents (planner, researcher, analyst, forecaster, critic) that work
the goal, stream their progress live, and deliver clear insights, predictions, and
recommendations.

## Track prompt (must answer exactly)
"Build an AI-powered solution that turns business data into clear insights,
predictions, or recommendations that help people make better decisions."

## Judging criteria
1. Real-World Impact & Relevance
2. Technical Implementation & AI Use — thoughtful integration (planner → workers →
   critic loop), NOT a chatbot wrapper. Judges explicitly punish wrappers.
3. Innovation & Creativity

## Components (v1)
- **Mission**: user writes a goal ("Analyze why our churn spiked in Q3 and recommend
  3 fixes") + optionally uploads business data (CSV).
- **Planner agent**: breaks the mission into subtasks, assigns specialists (DAG).
- **Specialist agents**:
  - Researcher — web search + summarize
  - Analyst — runs Python on uploaded CSV: stats, trends, charts
  - Forecaster — simple prediction from the data
  - Critic — reviews all outputs, flags weak claims
- **Live run view**: websocket stream of every agent's status, thoughts (summarized),
  and artifacts as they land.
- **Deliverable**: structured report — key insights, charts, predictions, ranked
  recommendations — downloadable as Markdown/PDF.
- **Template marketplace**: 3 prebuilt teams — Market Research Team, Sales Insights
  Team, Support Triage Team.
- **n8n export**: one click turns a finished run into an n8n workflow JSON.
- **Token/cost meter**: every run shows tokens used and estimated cost per agent.

## Stack (fixed — do not deviate)
- Frontend: Next.js 14 (App Router) + Tailwind CSS + TypeScript
- Backend: FastAPI (Python 3.11+; this machine runs 3.13)
- LLM layer: provider-agnostic interface, default GLM (Zhipu) with OpenAI-compatible
  fallback. Model id + base URL come from env vars — never hardcoded.
- Vector memory: pluggable (ship simple local JSON store + interface for
  Pinecone/Qdrant) — optional v1.x, interface only.
- Realtime: websockets.
- **No real API keys in the repo — everything via `.env.example`.**

## Frontend page routes (pinned)
- `/` — landing (hero, how-it-works, template gallery, CTA)
- `/new` — mission creator (goal textarea + CSV upload + team-template picker)
- `/runs/[id]` — live run view (agent timeline, streaming status, artifact feed,
  token/cost meter)
- `/runs/[id]/report` — report view (insights, charts, recommendations, downloads)
- `/templates` — template marketplace

## Backend API routes (pinned — see docs/INTERFACES.md for shapes)
POST /api/missions · GET /api/missions · GET /api/missions/{id} ·
POST /api/missions/{id}/runs · GET /api/runs/{id} · WS /api/runs/{id}/stream ·
POST /api/upload · GET /api/templates · POST /api/runs/{id}/export/n8n ·
GET /api/runs/{id}/report · GET /healthz

## Honesty rules
- No invented integrations, no fake metrics, no placeholder screenshots.
- If a piece is stubbed, say so in BUILD_COMPLETE.md — never fake it.
