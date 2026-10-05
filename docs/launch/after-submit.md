# AgentForge — After-Submit Ops

## The edit window

- Devpost submissions can be edited up to the hackathon deadline (**Oct 10, 2026 12:00 PM EDT / 9:30 PM IST**). Since we submit Oct 9 EOD IST, that leaves ~20 hours of safe edit window.
- Use the window only for corrections (broken link, typo, missing tag). Re-check the video link and repo link once after submitting — link rot right after upload is the most common fixable failure.
- After the deadline, expect the submission to be locked. If a genuine error surfaces later, message the organizers and ask — do not assume fixes are possible, and do not rely on it.

## Sharing plan (within 24h of submitting, after a final link check)

1. **Build-in-public post (X + LinkedIn), draft:**
   > I built AgentForge for ForgeHacks Online 2026: describe a business goal, attach a CSV, and a team of AI agents — planner, researcher, analyst, forecaster, critic — plans the work as a DAG, streams every step live, and ships a decision-ready report. One-click n8n export too. Demo video + repo in the comments. Built by me + 10 AI agents against frozen interface contracts.
2. Post the **video link first** as a reply, then the **repo link** (keeps the main post clean and drives clicks to both).
3. Share in the ForgeHacks Discord/#submissions channel with the same copy minus the hashtag.
4. Send to 2–3 people who fit the target user (ops/support/marketing lead) and ask one question: "Would you trust the report? What's missing?" Log the answers for judging Q&A.
5. Do **not** buy engagement or post in unrelated communities; judges notice.

## Judges Q&A prep — 3 likely questions, honest answers

**Q1: "Isn't this just a ChatGPT wrapper?"**
> No — there is no single prompt-to-answer path. The planner emits a real DAG of subtasks with dependencies; specialist workers execute through a typed Tool interface (web search, a pandas CSV analyzer, a sandboxed Python runner, charting) and emit structured artifacts; the critic reviews every output and downgrades weak claims before ranking; the deliverable is a validated report model with evidence and confidence on every claim, plus a token meter per agent. You can watch each step arrive as a seq-ordered event over the WebSocket. The LLM calls are the smallest part of the system — the orchestration, tools, and report contract around them are the product.

**Q2: "Are the numbers in your demo real?"**
> They are measured, not invented — from our bundled sample dataset (`saas_churn.csv`, 2,000 customers, deterministically generated with a fixed seed). The repo ships a measurement rubric (`data/samples/EXPECTED_INSIGHTS.md`) so anyone can check the demo output against the data: 24.8% overall churn, basic plan 37.4% vs. pro 15.5% vs. enterprise 7.6%, median 13 vs. 42 logins. We never claim customers or revenue — the product launched this week for this hackathon. The demo video is recorded in demo mode (deterministic simulated agents, labeled in the UI) so it runs identically offline; live mode runs the same pipeline with a real LLM key.

**Q3: "How much does a run cost, and what happens when the model fails?"**
> The token/cost meter answers the first part live: per-agent input/output tokens with an estimated running cost, rates from env vars. For the second part, that is why demo mode exists — `LLM_MODE=mock`/`RUN_MODE=demo` drives the identical event pipeline with deterministic simulated agents, no key and no network. There is also an env-configured fallback model chain, so a live run retries a second model before surfacing a failure (`run_failed` with the stage named).

## If the LLM key fails during judging (the demo-mode pitch)

Switch env to `RUN_MODE=demo` + `LLM_MODE=mock` (frontend `NEXT_PUBLIC_DEMO_MODE=1`) and restart, or just open the frontend in demo mode. Say:

> "The pipeline is identical in demo mode — deterministic simulated agents driving the same event stream, report, and exports — so I can show you the full run right now without any API access. Live mode is the same code path with a real key; the switch is two env vars."

Then run the churn mission end-to-end. If even the local stack misbehaves, show the committed n8n example (`backend/integrations/examples/sales_insights_team_workflow.json`) plus the report screenshots — all real repo artifacts.

## Standing items until winners are announced

- Keep the repo public; respond to GitHub issues/PR comments politely and honestly within a day.
- Watch Devpost comments; answer every judge/user question in-thread (the three prepared answers above cover most).
- Keep the demo environment ready: one rehearsed machine, offline-capable demo mode, the churn mission pre-typed.
- Do not push breaking changes after submission; judge clones should match what was submitted.
