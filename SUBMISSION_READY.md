# SUBMISSION_READY — AgentForge · ForgeHacks Online 2026

**Track:** AI + Business · **Deadline:** Oct 10, 2026, 12:00 PM EDT (**9:30 PM IST**)
**Internal target:** Oct 9 EOD IST · **Submitted by:** Prakh Dhakad

The build is complete and verified ([BUILD_COMPLETE.md](BUILD_COMPLETE.md)). What
follows is exactly what remains between here and the submit button. Everything
copy-paste ready lives in `docs/launch/`.

---

## Prakhar's remaining actions (in order)

### 1. One live-mode sanity run (≈10 min, recommended before recording)
```bash
cd backend
cp ../.env.example .env        # then edit: RUN_MODE=live, LLM_MODE=live, LLM_API_KEY=<your GLM key>
../.venv/Scripts/python -m uvicorn app.main:app --reload
```
Create one mission in the UI (`http://localhost:3000/new`) and confirm the real
LLM path works. If you skip this, the demo video is still fully valid in demo
mode (say so on screen — `docs/launch/` copy already discloses it).

### 2. Record the video (MANDATORY for eligibility — 2–4 min, public YouTube)
- Script: [docs/launch/video-script.md](docs/launch/video-script.md) — 3:00 target,
  scene-by-scene with exact voiceover lines and captions.
- Voiceover only (TTS-friendly): [docs/launch/voiceover-only.txt](docs/launch/voiceover-only.txt)
- Record at 1600×900, 60 fps. Run in demo mode (default). Retake policy inside.
- Upload to YouTube (public or unlisted-public per Devpost rules), title/description
  suggested in the script doc. Add the GitHub URL once step 3 is done.

### 3. Capture 6 screenshots
- Exact steps: [docs/launch/shot-list.md](docs/launch/shot-list.md)
  (landing, mission+CSV, live run + token meter, report insights, recommendations, n8n JSON).
- n8n example JSONs for the last shot: `backend/integrations/examples/*.json`.

### 4. Push the repo to GitHub (public)
```bash
cd ~/workspace/forgehacks-agentforge/agentforge
git remote add origin https://github.com/prakhardhakad1/agentforge.git
git push -u origin main
```
(Repo is committed and clean — 249 files, single commit. Rename if you prefer a
different repo slug, then update the video description + Devpost field.)

### 5. Fill the Devpost form
- Field-by-field map: [docs/launch/field-guide.md](docs/launch/field-guide.md)
- Paste-ready text: [docs/launch/devpost-copy.md](docs/launch/devpost-copy.md)
- Track: **AI + Business** (must be selected explicitly)

### 6. Pre-submit checklist
[docs/launch/pre-submit-checklist.md](docs/launch/pre-submit-checklist.md) — video public ✅,
repo public ✅, ≥3 screenshots ✅, track selected ✅, built-with tags ✅, n8n JSON
import test ✅, deadline reminder.

### 7. Submit — then read
[docs/launch/after-submit.md](docs/launch/after-submit.md) (edit window, sharing
plan, judge Q&A prep, LLM-key-failure fallback pitch).

## Devpost field → source map (summary)

| Devpost field | Source |
|---|---|
| Project title | `docs/launch/devpost-copy.md` (3 options + recommended) |
| Short description (≤200 chars) | `docs/launch/devpost-copy.md` |
| Full description | `docs/launch/devpost-copy.md` (problem + users · technical approach · impact) |
| Track | AI + Business |
| Cover image / screenshots | `docs/launch/shot-list.md` (6 shots, captions included) |
| Demo video link | YouTube URL after recording (script: `docs/launch/video-script.md`) |
| GitHub repo link | `https://github.com/prakhardhakad1/<repo>` after step 4 |
| Built With tags | `docs/launch/devpost-copy.md` |
| Architecture diagram (optional) | `docs/launch/architecture-diagram.md` (paste-ready ASCII) |

## Two placeholders to fill at upload time

1. `<GITHUB_URL>` in the video description / field guide → your repo URL.
2. Registered team name on Devpost (solo entry: your name).

## Honest state of the submission

- Everything in the video/demo works offline in demo mode — deterministic, no keys.
- Live LLM mode is wired and tested with mocked HTTP but **not yet run against a
  real key** — do step 1 if you want it proven on camera.
- The n8n export JSON is generated and committed, but hasn't been imported into a
  real n8n Cloud tenant yet — 2-minute manual test before you claim it on camera
  (n8n: Workflows → Import from File; note: n8n Cloud blocks `$env`, so swap the
  base-URL expression for a literal if asked).
- No metrics, users, or traction are claimed anywhere — all numbers trace to the
  bundled sample datasets.
