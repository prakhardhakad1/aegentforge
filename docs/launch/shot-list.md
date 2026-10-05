# AgentForge — Devpost Shot List (6 screenshots)

**Global settings for every shot**
- Chrome/Edge, clean profile, AgentForge tab only, notifications off.
- Viewport exactly **1600×900 px** at **100% zoom** (DevTools → Toggle device toolbar → Responsive → 1600×900, or resize the window). Capture with Win+Shift+S region select or ShareX → save as PNG under the exact filenames below.
- Servers: backend `uvicorn app.main:app` (cwd `backend/`), frontend `npm run dev`, demo mode env (`RUN_MODE=demo`, `LLM_MODE=mock`, `NEXT_PUBLIC_DEMO_MODE=1`).
- Use ONE finished churn run for shots 3–5 so captions and numbers match the video.
- Devpost requires at least 1 image; we upload all 6 (≥3 satisfies the checklist).

---

### 1. `01-landing-hero.png` — Landing hero
- **URL:** `http://localhost:3000/`
- **Steps:** open the landing page, wait for fonts, position the page at the very top.
- **Must be visible:** the hero headline with the pitch ("Hire an AI team with one sentence."), the goal-in-plain-language subline, the primary CTA, and the top edge of the how-it-works or template gallery strip.
- **Devpost caption:** `AgentForge landing — describe a business goal, attach a CSV, and hire a team of AI agents.`

### 2. `02-mission-creator.png` — Mission creator with CSV attached
- **URL:** `http://localhost:3000/new`
- **Steps:** type EXACTLY into the goal textarea: `Analyze why our churn spiked and recommend 3 fixes` — then upload `data/samples/saas_churn.csv` via the CSV uploader and wait for the dataset confirmation (row count + columns + any quality notes).
- **Must be visible:** the typed mission text (exact string above), the attached `saas_churn.csv` confirmation (2,000 rows / column list), and the template picker showing **Market Research Team**, **Sales Insights Team**, **Support Triage Team** (default selection fine).
- **Devpost caption:** `Mission creator — the churn mission with the 2,000-row saas_churn.csv attached and the three prebuilt team templates.`

### 3. `03-live-run.png` — Live run mid-flight (agents streaming + token meter)
- **URL:** `http://localhost:3000/runs/{run_id}` (launch a fresh run from shot 2's mission; capture ~15–20 seconds in, while the analyst or forecaster is still streaming).
- **Steps:** start the run, watch the event feed, capture when at least three agent panels show activity and artifacts have begun landing.
- **Must be visible:** the plan DAG / subtask list with per-agent statuses, a streaming `thought_summary` or `tool_call` entry, at least one artifact in the feed, and the **token/cost meter** (per-agent rows). The in-product DEMO MODE badge must stay visible — do not crop it out.
- **Devpost caption:** `Live run view — planner DAG, streaming agent thoughts and tool calls, artifacts landing, and the per-agent token/cost meter (demo mode: deterministic simulated agents).`

### 4. `04-report-insights.png` — Report top (insights + chart)
- **URL:** `http://localhost:3000/runs/{run_id}/report`
- **Steps:** open the finished run's report, position at the top.
- **Must be visible:** the report title + mission echo, the executive summary, the ranked insights list with evidence and strength badges (top insight: basic 37.4% vs pro 15.5% vs enterprise 7.6% churn; overall 24.8%), and at least one chart (churn by plan or logins comparison).
- **Devpost caption:** `Report top — executive summary, insights ranked by evidence strength, and a chart from the churn run (numbers measured on the bundled sample dataset).`

### 5. `05-report-recommendations.png` — Report recommendations
- **URL:** `http://localhost:3000/runs/{run_id}/report` (same run as shot 4)
- **Steps:** scroll to the predictions + recommendations section.
- **Must be visible:** predictions with stated confidence and basis, then the 3 ranked recommendations with priority / expected impact / S-M-L effort (save offers on declining usage, early-tenure onboarding push, annual plans for basic customers), and the **Download Markdown / PDF** buttons.
- **Devpost caption:** `Report bottom — predictions with stated confidence and the three fixes ranked by impact vs. effort, downloadable as Markdown or PDF.`

### 6. `06-n8n-export.png` — n8n export JSON
- **Primary option (n8n Cloud canvas):** visit n8n Cloud → *Workflows* → **Import from File** → select `backend/integrations/examples/sales_insights_team_workflow.json` (a real committed example export, not a mock) → capture the canvas showing the imported graph: **Webhook Trigger → Mission Context (Set) → per-subtask Set + HTTP Request chain → Critic Verdict (IF) → Assemble Report (Code) → Deliver Report (HTTP)**.
- **Fallback option (no n8n account):** open `backend/integrations/examples/sales_insights_team_workflow.json` in VS Code with JSON syntax highlighting, collapsed enough that node names are readable; or show the JSON in the browser right after clicking the run's **Export n8n** button.
- **Must be visible:** the workflow name containing the run id, and enough of the node graph (or JSON) to read `Webhook Trigger`, the per-subtask step nodes, and the `Critic Verdict` IF node.
- **Devpost caption:** `One-click n8n export — this run's plan DAG as an importable n8n workflow (real example file from backend/integrations/examples/).`

---

**Check before upload:** every image is exactly 1600×900, text is legible at Devpost thumbnail size (no dark-on-dark), the demo-mode badge is intact in shot 3, and no personal file paths or unrelated tabs are visible.
