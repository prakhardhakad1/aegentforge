# AgentForge — Launch Video Script (v1.0, final)

- **Target runtime:** 3:00 (eligibility window is 2:30–3:30; the six scene budgets below sum to exactly 180s).
- **Format:** single continuous screen recording of the app in **demo mode** (`RUN_MODE=demo`, `LLM_MODE=mock`, `NEXT_PUBLIC_DEMO_MODE=1`), voiceover recorded separately or live-to-tape. Demo run length ≈ 35 seconds — scene 3 (60s) is built around that.
- **Tone:** first person, student builder, zero hype. No invented metrics — every number spoken in this script is a measured fact from `data/samples/EXPECTED_INSIGHTS.md` (saas_churn sample).
- **Honesty rule:** the demo-mode badge stays visible during the run scene (captions 8), and line 8 says "demo mode: deterministic simulated agents" out loud. Do not cut it.

## Shot equipment

- Browser: Chrome/Edge window sized to exactly **1600×900 viewport at 100% zoom** (DevTools device toolbar or a resized window).
- Recorder: OBS Studio at **60 fps**, region 1600×900 (or full screen 1920×1080 and crop in the edit), bitrate ≥ 8,000 kbps.
- Mic: headset or any external mic at mouth height, ~15 cm away; record in a quiet room with the door shut. Do a 10-second test clip first.
- One clean browser profile, AgentForge tabs only, notifications off.

## Scene-by-scene script

| # | Time | On-screen action | Voiceover (EXACT spoken line) | On-screen caption |
|---|------|------------------|-------------------------------|-------------------|
| 1a | 0:00–0:08 | Landing page `/` hero at rest, then a slow scroll toward "How it works". | "Every business already has the data to answer its most important questions. The problem is, those answers get stuck — buried in dashboards nobody has time to explore, or waiting weeks in a consultant's queue." | "Business answers are stuck in dashboards and consultant queues." |
| 1b | 0:08–0:20 | Scroll back to hero; cursor moves to the "Start a mission" CTA. | "What if you could just ask, and a whole team got to work?" | "AgentForge — hire an AI team with one sentence." |
| 2a | 0:20–0:27 | Click CTA → navigate to `/new`. | "This is AgentForge. I type the mission in plain language:" | "/new — mission creator" |
| 2b | 0:27–0:38 | Type into the goal textarea (EXACT text, typed visibly): `Analyze why our churn spiked and recommend 3 fixes`. Then click upload and pick `saas_churn.csv` — the dataset confirmation appears (2,000 rows, columns listed). | "analyze why our churn spiked, and recommend three fixes. Then I attach our customer CSV — two thousand rows of plans, usage, and churn flags." | "Mission + saas_churn.csv (2,000 rows)" |
| 2c | 0:38–0:46 | Template picker briefly visible (Market Research Team / Sales Insights Team / Support Triage Team); leave default; click **Launch**. | "I pick a team, hit launch, and AgentForge staffs the job: a planner, a researcher, an analyst, a forecaster, and a critic." | "One mission → five specialists" |
| 2d | 0:46–0:50 | Redirect to `/runs/{id}` live run view. | *(2s silence — let the redirect breathe)* | "Live run view" |
| 3a | 0:50–0:58 | Run begins (~click at 0:51, run_finished lands ≈ 1:47). `plan_created` event lands; plan DAG renders with subtasks + dependencies. | "The planner goes first, breaking the mission into a DAG of subtasks and assigning each to a specialist." | "Planner → DAG of subtasks" |
| 3b | 0:58–1:06 | Researcher panel: `agent_started`, `thought_summary`, `tool_call`/`tool_result` streaming. | "The researcher pulls outside context — churn benchmarks and industry reports — and summarizes what it finds." | "Researcher: outside context" |
| 3c | 1:06–1:16 | Analyst panel streaming; first `artifact_created` lands in the artifact feed (a table artifact from the CSV profile). | "Meanwhile the analyst opens my CSV, profiles the columns, and runs pandas — landing real tables and charts in the feed." | "Analyst: pandas over your CSV" |
| 3d | 1:16–1:24 | Forecaster panel streaming; a prediction artifact lands. | "The forecaster projects what's next; every prediction carries its own confidence and its basis." | "Forecaster: predictions with stated confidence" |
| 3e | 1:24–1:36 | Critic panel streaming; hover the flagged claim (downgraded strength) if the UI allows. | "Then the critic. It just flagged a claim that was too strong, downgraded it, and forced another ranking pass — nothing unreviewed reaches the report." | "Critic: flags weak claims before the report" |
| 3f | 1:36–1:50 | Pan to the token/cost meter; hover per-agent rows. `run_finished` banner lands (~1:47). Click through to the report. | "That meter tracks every token per agent with running cost — no black box. And this run is demo mode: deterministic simulated agents, so it plays the same offline; live mode swaps in the real model." | "Token meter: every token, per agent · DEMO MODE — deterministic simulated agents" |
| 4a | 1:50–2:12 | Report page top (`/runs/{id}/report`): executive summary, then ranked insights with strength badges. | "Thirty-five seconds after launch, the report is ready. It opens with an executive summary, then the insights, ranked by evidence strength. The top one: basic-plan customers churn at thirty-seven point four percent — almost three times the company average of just under twenty-five." | "Report: exec summary + insights ranked by evidence strength" |
| 4b | 2:12–2:30 | Scroll to the chart (churn by plan / logins comparison), then predictions, then the recommendations block. | "Here's the driver: churned customers had a median of thirteen logins last month; active ones, forty-two. The forecaster scores who's at risk next. Then my three fixes, ranked by impact versus effort: save offers when usage drops, an onboarding push early, and annual plans for basic customers." | "Churned median 13 logins vs 42 active · 3 fixes ranked by impact vs effort" |
| 5a | 2:30–2:40 | Navigate to `/templates` — the three team cards visible. | "No need to rebuild this by hand. The template marketplace ships three ready teams — market research, sales insights, support triage." | "3 prebuilt teams in the marketplace" |
| 5b | 2:40–2:50 | Back on the finished run: click **Export n8n** — the workflow JSON is on screen (Webhook → per-subtask chain → Critic IF → report nodes). | "And any finished run exports in one click as an n8n workflow — import it into n8n Cloud and wire it into your stack." | "One-click n8n export (importable into n8n Cloud)" |
| 6 | 2:50–3:00 | Cut back to the landing hero; end card with repo URL. | "That's AgentForge — hired with one sentence. Next I'd build step-level retries from n8n and a hosted live-mode deployment. Thanks for watching." | "AgentForge · repo link below" |

**Total spoken word count:** ~400 words ≈ 2:40 of narration at a relaxed ~150 wpm, leaving natural pauses inside the 3:00 runtime.

**Timing notes for the editor**
- The demo run takes ~35s: click Launch at ~0:51 → `run_finished` ~1:47. If your take finishes early, pad scene 3 by hovering artifacts/the DAG (never pad with silence).
- Scene 4b is the densest (47 words / 18s). If it feels rushed, steal up to 2 seconds from scene 5a.
- Keep 1.5–2s of lead-in silence on every scene cut.

## YouTube upload metadata (paste-ready)

- **Title:** `AgentForge — Hire an AI team with one sentence (ForgeHacks Online 2026)`
- **Description:**
  ```
  AgentForge (ForgeHacks Online 2026, AI + Business track): describe a business
  goal, optionally attach a CSV, and a team of AI agents — planner, researcher,
  analyst, forecaster, critic — plans the work as a DAG, streams every step live,
  and delivers a decision-ready report with ranked insights, charts, predictions,
  and ranked recommendations. Any finished run exports as an importable n8n workflow.

  Chapters:
  0:00 The problem
  0:20 A mission + a CSV
  0:50 Watching the agents work live
  1:50 The report
  2:30 Templates + n8n export
  2:50 What's next

  Repo: <GITHUB_URL>
  This demo is recorded in AgentForge's demo mode: deterministic simulated agents,
  clearly labeled in the product. Live mode runs the same pipeline with a real LLM.
  Built for the AI + Business track: turning business data into clear insights,
  predictions, and recommendations.
  ```
- **Visibility:** Public. Verify the processed video plays at 1080p/60 before pasting the link into Devpost.

## Recording checklist

- [ ] Fresh browser profile; only AgentForge tabs open; other apps closed; OS notifications off (Focus assist on).
- [ ] Browser viewport exactly 1600×900 at 100% zoom.
- [ ] Backend (`uvicorn app.main:app` from `backend/`) and frontend (`npm run dev`) both running; `/healthz` returns ok.
- [ ] Demo mode env confirmed: `RUN_MODE=demo`, `LLM_MODE=mock`, `NEXT_PUBLIC_DEMO_MODE=1`.
- [ ] Do one throwaway end-to-end run first to confirm artifacts land as scripted; then delete that run and record with a fresh run.
- [ ] OBS: 60 fps, 1600×900 region, ≥ 8,000 kbps; 15s test recording checked for audio levels and framing.
- [ ] Record scene by scene; leave 2s of silence at the head and tail of each take.
- [ ] Capture the 6 screenshots from `shot-list.md` right after the video take, while the same run is still open.
- [ ] Edit: add captions exactly as scripted; keep the demo-mode badge on screen through scene 3.
- [ ] Upload to YouTube **Public**, paste title/description above, verify playback, copy the link.

## Retake policy (good enough > perfect)

- A take is **good enough** when: voiceover is clear and audible, every on-screen action lands within ±2 seconds of its script slot, and no stray tabs/notifications are visible. Ship it.
- **Maximum 2 retakes per scene.** If a third would be needed, fix it in the edit instead (trim, zoom-in, caption) — do not re-record.
- One stumbled word does not justify a retake if the meaning is obvious.
- Never re-record the whole video for one scene; scene-level retakes only.
- The deadline beats the perfect take: if total editing time exceeds the schedule in `pre-submit-checklist.md`, ship the best complete take.
