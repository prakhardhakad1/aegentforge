# AgentForge — Devpost Field Guide

Every Devpost submission field, in submission order, with exactly what to paste or
upload and from which file in `docs/launch/`. Do this in one sitting (30–45 min)
after the video link exists. Sources: `devpost-copy.md` (D), `shot-list.md` (S),
`video-script.md` (V), `architecture-diagram.md` (A), `pre-submit-checklist.md` (P).

> The Devpost form labels/rows can vary slightly per hackathon; the fields and
> content below are the same. If a field is missing or extra on the day, use the
> closest mapping and note it in `NOTES.md`.

1. **Project title**
   Paste option 1 from D ("Title — 3 options"): `AgentForge — Hire an AI team with one sentence.`

2. **Short description / short pitch** (≤200 chars)
   Paste the exact block from D ("Short description"). It is 191 characters — do not "improve" it, re-count if you edit.

3. **About the project / full description**
   Paste the entire block from D ("Full description") into the rich-text editor.
   Devpost renders Markdown headings and links; after pasting, scroll the preview
   and check: the n8n link resolves, headings render, and the churn numbers
   (24.8% / 37.4% / 15.5% / 7.6% / 13 vs 42) are intact.
   Optional: append the ASCII architecture diagram from A as a final
   ```` ``` ````-fenced code block so the monospace art survives.

4. **Track**
   Select **AI + Business**. Verify against the hackathon's track list; the
   description's final line answers the track prompt sentence-for-sentence.

5. **Cover image**
   Upload `01-landing-hero.png` (from S). It doubles as the hero and reads at
   thumbnail size. (If Devpost shows a dedicated "cover" slot separate from
   screenshots, upload 01 there; do not delete it from screenshots.)

6. **Screenshots** (≥3 required — upload all 6)
   Upload, in this order, from S:
   `01-landing-hero.png` → `02-mission-creator.png` → `03-live-run.png` →
   `04-report-insights.png` → `05-report-recommendations.png` → `06-n8n-export.png`.
   Paste each shot's Devpost caption from S into the caption field.

7. **Video demo link** (mandatory for eligibility)
   Paste the public YouTube URL. Target title/description for the upload are in V
   ("YouTube upload metadata"). Before pasting: video is **Public**, processed,
   and plays at 1080p/60 in an incognito window.

8. **GitHub repository link**
   Paste the repo URL (`<GITHUB_URL>` — the public AgentForge repo). Confirm the
   repo is Public and README.md renders (it is final; do not edit it for Devpost).

9. **Built With tags**
   Paste the tag list from D ("Built With"): comma-separated, 14 tags. If the
   field has a per-tag autocomplete, add them one by one in the same order.

10. **Team members / team name**
    Team name: the team registered for ForgeHacks (fill the agreed name — P has
    the blank). Add the human member(s) with the registered emails. Leave
    "Looking for" fields empty or as the team decided — nothing in the launch kit
    invents roles.

11. **Final review**
    Run `pre-submit-checklist.md` (P) top to bottom, then click **Submit**.
