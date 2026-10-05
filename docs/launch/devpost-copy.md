# AgentForge — Devpost Copy (v1.0, final, paste-ready)

## Title — 3 options

1. **(RECOMMENDED)** `AgentForge — Hire an AI team with one sentence.`
   Echoes the pinned pitch line exactly, short, memorable.
2. `AgentForge: your business question in, a decision-ready report out`
   Leads with the deliverable; good if judges skim titles for outcomes.
3. `AgentForge — an AI team you can watch work (planner, researcher, analyst, forecaster, critic)`
   Leads with the multi-agent mechanics; more technical, less punchy.

## Short description (≤200 chars — 191 used, paste exactly)

```
Hire an AI team with one sentence. Describe a business goal, attach a CSV, and watch planner, researcher, analyst, forecaster and critic agents stream their work into a decision-ready report.
```

## Full description (paste into "About the project")

````markdown
# AgentForge — hire an AI team with one sentence

Describe a business goal in plain language, optionally attach a CSV, and AgentForge
spawns a team of specialized AI agents — **planner, researcher, analyst, forecaster,
critic** — that plans the work as a real DAG, streams every step live, and delivers a
structured report: insights ranked by evidence strength, charts, predictions with
stated confidence, and recommendations ranked by impact vs. effort. Any finished run
exports in one click as an importable [n8n](https://n8n.io) workflow.

## The problem

Most business questions ("why did churn spike?", "which channel is wasting our
budget?", "what's driving support load?") already have their answers inside data the
company owns. But those answers get stuck: dashboards answer pre-set questions only,
and an analyst or consultant takes days to weeks per question. Non-technical
operators are left guessing.

**Target users:** small-business owners, ops/marketing/support leads, and indie SaaS
founders — anyone who has the data but not the analyst.

## What it does

1. **Mission** — write a goal ("Analyze why our churn spiked and recommend 3 fixes")
   and optionally upload a CSV.
2. **Planner** — decomposes the mission into a DAG of subtasks assigned to
   specialists (researcher, analyst, forecaster, critic).
3. **Live run view** — every agent's status, summarized thoughts, tool calls,
   artifacts, and a per-agent token/cost meter stream to the browser over a
   WebSocket.
4. **Report** — executive summary, ranked insights (each with evidence and a
   high/medium/low strength rating), charts, predictions with stated confidence and
   basis, and recommendations ranked by expected impact vs. S/M/L effort. Download
   as Markdown or PDF.
5. **Template marketplace** — three prebuilt teams (`market_research_team`,
   `sales_insights_team`, `support_triage_team`), each with a sample mission,
   expected DAG, and report outline.
6. **n8n export** — one click turns a finished run into an importable n8n workflow
   (Webhook → per-subtask chain mirroring the plan DAG → critic IF → report
   delivery), using core n8n node types only.

In our demo (the churn mission on the bundled `saas_churn.csv` sample, 2,000
customers), the report surfaces measured facts: overall churn 24.8%; basic plan
37.4% vs. pro 15.5% vs. enterprise 7.6%; churned customers had a median of 13
logins in their last month vs. 42 for active ones — then ranks the fixes: targeted
save-offers when usage drops, an early-tenure onboarding push, and annual plans for
basic month-to-month customers. These numbers are measured on the sample dataset
(deterministically generated; the measurement rubric is in the repo), not invented.

## Technical approach

This is not a chatbot wrapper — it is an orchestrated pipeline:

- **Planner → workers → critic loop.** The planner emits a real DAG
  (`plan_created` events carry subtasks with `depends_on`). Workers execute in
  topological order. The critic reviews every worker output, downgrades weak claims
  before ranking, and forces a re-ranking pass. Nothing unreviewed reaches the
  report.
- **Backend:** FastAPI (Python), SQLite + SQLAlchemy + Alembic. Routes: missions,
  runs, CSV upload (schema + quality notes), templates, run snapshots, WebSocket
  stream, report downloads, n8n export.
- **Realtime:** a pinned event envelope (`run_started`, `plan_created`,
  `agent_started`, `thought_summary`, `tool_call`/`tool_result`,
  `artifact_created`, `token_update`, `run_finished`, …) is seq-ordered, persisted,
  and fanned out over Websockets — with a polling/replay fallback by sequence
  number on reconnect.
- **Tools:** web search, a pandas CSV analyzer (profiling, stats, trends), a
  sandboxed Python runner (timeout + memory caps), and matplotlib charting, all
  behind one typed Tool interface returning `ToolResult` + artifacts.
- **Report builder:** consumes the run result and renders the structured report;
  Markdown and PDF (fpdf2) exporters.
- **Provider-agnostic LLM layer:** one OpenAI-compatible client; the model id,
  base URL, and fallback model come from environment variables (default targets a
  GLM endpoint). No provider is hardcoded — swap via env with zero code changes.
- **Demo-first honesty:** `LLM_MODE=mock` + `RUN_MODE=demo` runs the entire
  product offline with deterministic simulated agents, clearly labeled in the UI.
  Live mode runs the same pipeline with a real key. The demo video is recorded in
  demo mode.
- **Token/cost meter:** per-agent input/output tokens and estimated cost per run.
- **Frontend:** Next.js 14 (App Router) + Tailwind + TypeScript; five pages
  (landing, mission creator, live run, report, templates).

## Real-world impact

AgentForge compresses a question-to-decision cycle that normally takes a request
queue and days of waiting into a couple of minutes — and it shows its work: you
watch the plan, the tool calls, and the critic's objections, and every claim in the
report carries its evidence and confidence. The three template teams cover the most
common versions of this problem — market research, sales analysis, and support
triage — and the n8n export lets a team wire the same pipeline into their existing
automation without touching the product.

## What we'd build next

Step-level re-drive endpoints so exported n8n workflows can re-run individual
subtasks against a stock deployment; a hosted live-mode deployment; and a second
exporter serializing plan DAGs to an open agent language. (Tracked honestly in the
repo README's roadmap.)

## Built by a human + 10 AI agents

This repo was built for ForgeHacks by one student developer working with ten
parallel AI coding agents, all writing against frozen interface contracts
(`docs/SPEC.md`, `docs/INTERFACES.md`) with strict module ownership. The development
process and the product implement the same pattern: a planner decomposes, workers
execute, a critic reviews. No hype — the contracts are in the repo if you want to
check.

**Track:** AI + Business — an AI-powered solution that turns business data into
clear insights, predictions, and recommendations that help people make better
decisions.
````

## Built With tags (paste as comma-separated)

```
nextjs, typescript, tailwindcss, fastapi, python, websockets, sqlite, alembic, pandas, matplotlib, fpdf2, openai-compatible, glm, n8n
```

## Track

**AI + Business** (select explicitly in the Devpost form — tracks are not auto-detected).
