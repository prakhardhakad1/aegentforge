# docs/launch/ — NOTES (Agent 10)

Scope: this agent touched ONLY `docs/launch/`. No git operations.

## Sources used (all final versions)
- `docs/SPEC.md`, `docs/INTERFACES.md` — pinned routes, event types, template ids, API shapes.
- `README.md` — product facts, quickstart, n8n export guide (incl. n8n Cloud `$env` caveat), test counts.
- `SPONSORS.md` — honest exists-today / would-plug-in framing reused in copy.
- `data/samples/EXPECTED_INSIGHTS.md` — every number quoted in the script and copy (24.8%, 37.4/15.5/7.6%, 13 vs 42 logins, template names) is measured there; nothing else is quoted.

## Tone decisions
- First person, student-builder voice throughout; zero superlatives ("revolutionary", "game-changing" banned). The only strong claims are the pinned pitch line and the factual "not a chatbot wrapper" framing, which SPEC.md explicitly asks us to defend.
- Demo mode is disclosed three ways, on purpose: spoken (voiceover line 8), on-screen (caption/badge during the run scene), and written (Devpost description + video description). Rationale: judges punish wrappers and faking; proactive disclosure is also a differentiator.
- The "human + 10 AI agents" note is written matter-of-factly (what was done, where the contracts live) — sincerity over spectacle, and it doubles as the DevSwarm tie-in without naming sponsors.
- No invented metrics anywhere: no users, no revenue, no testimonials, no "as seen by hundreds of teams". Real-world impact is argued structurally (time-to-decision, evidence-on-every-claim), not numerically.

## Timing rationale
- Scene budgets (20+30+60+40+20+10 = 180s) come straight from the brief; the cut targets 3:00, comfortably inside the mandatory 2:30–3:30 window and leaves slack under the 3:30 ceiling for one padded scene.
- The 60s live-run scene is built around the measured ~35s demo run: launch at ~0:51 → `run_finished` ~1:47, with the token-meter + demo-mode beat absorbing the tail. Padding guidance says hover/zoom, never silence.
- Voiceover is ~400 words ≈ 2:40 of speech at ~150 wpm — a relaxed fit, with per-beat word counts checked. Scene 4b (47 words / 18s) is the densest; the script allows stealing ≤2s from scene 5a.
- Numbers are spoken precisely ("thirty-seven point four percent") because they are checkable against the shipped dataset and rubric.

## Key content decisions
- Mission string used everywhere verbatim: "Analyze why our churn spiked and recommend 3 fixes" (typed on screen), spoken line uses "three" naturally.
- Recommended title = the pinned pitch sentence, so the Devpost page, video title, and README all echo one line.
- Shot 6 (n8n JSON) primary path uses the committed real example `backend/integrations/examples/sales_insights_team_workflow.json` imported into n8n Cloud; an offline fallback (editor/browser view) is documented because we cannot assume an n8n Cloud account on recording day.
- Field guide follows the brief's field order; a caveat notes Devpost form labels can vary slightly so nobody freezes if a row is named differently.
- Pre-submit checklist includes a working-back mini-timeline (Oct 7/8/9) because the internal deadline (Oct 9 EOD IST) is a full day before the hard one (Oct 10 12:00 PM EDT / 9:30 PM IST).
- After-submit Q&A answers reuse the honest framings from README/SPONSORS ("exists today" vs "would plug in") rather than fresh claims.

## DEVIATIONS
- None from pinned contracts. Notes: (1) The brief's shot-list item "n8n export JSON" allowed either a live export or the example files; both are covered with a primary + fallback. (2) The brief said "narrate the token meter too" — done as voiceover line 8, merged with the mandatory demo-mode disclosure to protect the 60s scene budget. (3) Devpost field labels/order verified only against the brief's list, not a live form (submission not open to this agent); the field guide flags this.
- Placeholder `<GITHUB_URL>` appears in video-script.md and field-guide.md — fill with the public repo URL at upload time (repo URL was not pinned in the brief).
- Team name left as an explicit fill-in; the brief did not pin one.
