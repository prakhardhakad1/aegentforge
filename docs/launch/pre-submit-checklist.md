# AgentForge — Pre-Submit Checklist

Internal deadline: **submit by Thu Oct 9, 2026 end-of-day IST.**
Hard deadline: **Fri Oct 10, 2026, 12:00 PM EDT (9:30 PM IST).** Do not plan to use the hard deadline.

## Suggested mini-timeline (working back from Oct 9 EOD IST)

- [ ] By Oct 7: demo run rehearsed once end-to-end; screenshots captured (`shot-list.md`).
- [ ] By Oct 8: video recorded, edited, captions added (max ~2 retakes per scene — `video-script.md` retake policy).
- [ ] By Oct 9 morning: video uploaded to YouTube Public, Devpost draft filled.
- [ ] Oct 9 by EOD IST: checklist below green, **Submit** clicked.

## Video (mandatory for eligibility)

- [ ] Video is **Public** on YouTube (not unlisted, not private).
- [ ] YouTube title pasted from `video-script.md` metadata block.
- [ ] YouTube description pasted (repo link + chapters + demo-mode disclosure).
- [ ] Runtime is between 2:30 and 3:30 (target cut: 3:00).
- [ ] Watched the processed video once at 1080p/60 in an incognito window; audio audible, captions legible.
- [ ] Demo-mode badge visible during the run scene; line 8 of the voiceover is intact.

## Repository

- [ ] GitHub repo is **Public**.
- [ ] README.md renders and matches the product (final — no last-minute edits).
- [ ] No real API keys anywhere; only `.env.example` in the repo.
- [ ] Quickstart from a clean clone works: `pip install`, `npm install`, backend on :8000, frontend on :3000.

## Demo mode (works offline)

- [ ] Fresh run with `RUN_MODE=demo`, `LLM_MODE=mock`, `NEXT_PUBLIC_DEMO_MODE=1`, **zero API keys** set: mission → run → report → Markdown/PDF download → n8n export all work.
- [ ] Demo mode is clearly labeled in-product (badge on the run view).
- [ ] The churn mission "Analyze why our churn spiked and recommend 3 fixes" on `data/samples/saas_churn.csv` produces the scripted report numbers.

## n8n export

- [ ] Tested import of `backend/integrations/examples/sales_insights_team_workflow.json` into n8n Cloud via *Workflows → Import from File*.
- [ ] Imported graph shows Webhook → per-subtask chain → Critic Verdict (IF) → report nodes.
- [ ] (Optional) also tested a live export from a finished run via the UI button or `POST /api/runs/{id}/export/n8n`.

## Devpost form

- [ ] Track selected: **AI + Business**.
- [ ] Title pasted from `devpost-copy.md` (option 1).
- [ ] Short description pasted (≤200 chars; 191 as written).
- [ ] Full description pasted; Markdown preview checked (headings, n8n link, churn numbers intact).
- [ ] Cover image uploaded (`01-landing-hero.png`).
- [ ] **At least 3 screenshots** uploaded — target all 6 from `shot-list.md`, each with its Devpost caption.
- [ ] Video link pasted and re-checked (opens the Public video).
- [ ] GitHub repo link pasted and re-checked (opens the Public repo).
- [ ] Built-with tags pasted from `devpost-copy.md` (nextjs, typescript, tailwindcss, fastapi, python, websockets, sqlite, alembic, pandas, matplotlib, fpdf2, openai-compatible, glm, n8n).
- [ ] Team name and members filled exactly as registered for ForgeHacks.

## Final gate

- [ ] Read the submitted page top-to-bottom as a judge: no invented metrics, no fake users/revenue claims, demo mode disclosed.
- [ ] Screenshot or PDF the submitted page for records.
- [ ] **Submit by Oct 9 EOD IST.** Then run `after-submit.md`.
