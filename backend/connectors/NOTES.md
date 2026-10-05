# NOTES — connectors + sample datasets (Agent 5)

## What was built

- `backend/connectors/` package: `csv_parser.py` (engine), `paste_parser.py`
  (Sheets-style paste), `samples.py` (sample loading + dictionaries),
  `__init__.py` (pinned public surface), `interface.md` (contract for
  Agent 2), `tests/` (88 tests).
- `scripts/generate_samples.py` (stdlib only, seed 20261005) generating the
  four CSVs committed under `data/samples/`, plus `DATA_DICTIONARIES.md`
  (machine-parsed by `samples.py` at import) and `EXPECTED_INSIGHTS.md`
  (demo rubric with measured numbers).
- The coordinator stub `__init__.py` was fully replaced; the pinned surface
  (`parse_csv`, `parse_pasted_table`, `ParsedDataset`, `load_sample`,
  `SAMPLE_IDS`) is intact and verified against Agent 2's suite
  (`python -m pytest backend/tests` with cwd=backend: 68 passed).

## Design decisions

1. **Stdlib parsing engine; pandas only as an optional bridge.** Parsing,
   delimiter sniffing, dtype inference, and quality stats are pure
   `csv`/`re`/`datetime`. Rationale: (a) preview cells must be exact raw
   strings (Agent 2's test asserts `preview[0] == ["2026-01","west","120",
   "4800.50"]`), (b) the repo runs pandas 3.x — avoiding read_csv keeps
   behavior stable across pandas majors, (c) 5k rows parse in milliseconds.
   pandas appears only in `ParsedDataset.to_dataframe()` (lazy import,
   coerces numeric/boolean/date columns) for downstream analyst convenience.
2. **Encoding chain** `utf-8-sig -> cp1252 -> latin-1`. cp1252 sits between
   because it decodes the Windows-1252 bytes utf-8 rejects and only byte
   values 0x81/0x8D/0x8F/0x90/0x9D fall through to latin-1. Non-UTF-8
   decodes are flagged with a quality note. NUL bytes are rejected as
   "binary file" with a clear ValueError.
3. **Delimiter sniffing** scores `,` `\t` `;` `|` by (lines containing it,
   total occurrences) over the first ~20 non-blank lines; comma wins ties.
   This handles TSV, European semicolon CSV, and Sheets pastes uniformly.
4. **Header detection / rejection.** If the first row's non-empty cells are
   all numeric/date-like AND a second row exists that is also numeric/date-like,
   there is no detectable header -> ValueError (per brief). Headerless dumps
   and `42
43
44` single-column files are rejected; a headers-only file is valid
   (row_count 0 + "Very small dataset" note — Agent 2's test depends on the
   word "small"). >100 columns -> ValueError. Empty -> ValueError.
5. **Dtype vocabulary** is the demo-friendly set `integer|float|boolean|date|
   string|mixed|empty`. Dates require ONE consistent format across all values
   (11 common formats; years clamped to 1900-2100). `2026-01` (year-month) is
   deliberately `string`. 0/1 integer columns are `boolean` only when the
   name hints at a flag (`is_*`, `*_flag`, `churned`, ...), else `integer` —
   keeps `is_churned` boolean for plotting while honest about plain numeric
   columns. Currency/percent strings stay `string` (conservative).
6. **Quality notes** cover everything in the brief: overall + per-column
   missing %, duplicate rows, constant columns, mixed-type columns,
   suspicious dates (inconsistent formats / text-stored dates), plus ragged
   rows, duplicate/empty header names, non-UTF-8 encoding, and the
   small-dataset note. Per-column missing notes are capped at 8 with an
   aggregate overflow note.
7. **Sample path resolution** is derived from the package location
   (`backend/connectors/` -> repo root -> `data/samples`), so it works with
   `cwd=backend` (uvicorn), from the repo root, and from tests; cwd-relative
   fallbacks cover exotic installs. Missing samples raise `FileNotFoundError`
   telling the user to run the generator. `DATA_DICTIONARIES` parses the
   markdown at import and degrades to `{}` if the file is missing (import
   never crashes).
8. **Preview** is exactly ≤ 20 raw-string rows padded/truncated to the header
   width — matches the pinned `/api/upload` response and Agent 2's tests.

## Generator story logic (scripts/generate_samples.py)

All datasets come from one master seed (20261005) with per-dataset seed
offsets, so editing one generator never shifts another dataset's random
stream. Regeneration is byte-for-byte reproducible (asserted by a test).

- **saas_churn (2,000)**: month-by-month hazard simulation. Monthly churn
  hazard = plan base (basic .040 / pro .015 / enterprise .006) x usage
  multiplier from that month's simulated logins (<5 → 3.2x, <15 → 1.8x,
  <30 → 1.0x, 30+ → 0.45x) x 1.9 onboarding spike in months 1-2. 15% of
  customers are a "declining" usage class (logins decay 8%/month). Churned
  customers' final-month logins get a 0.6 collapse haircut; churned customers
  raise ~2.4x more tickets. Signups are skewed recent (growing business).
  Result: 24.8% overall churn; basic 37.4% / pro 15.5% / enterprise 7.6%;
  median logins 13 (churned) vs 42 (active); corr(logins, churn) = -0.52.
- **ecommerce_sales (5,000)**: dates sampled from monthly weights (Dec 2.2,
  Nov 1.6 vs ~1.0 baseline) over 2025-10..2026-09. Mobile share grows
  linearly 30%→50% of mix across the year (web shrinks, marketplace flat).
  Books category weight decays 55% across the year. revenue = quantity x
  unit_price (verified consistent). Category-specific return probabilities
  (apparel 12%, books 3%) blend to 7.9% overall. Rows sorted chronologically
  with sequential order ids.
- **support_tickets (1,500)**: category mix billing 30 / login_bug 25 /
  how_to 18 / feature_request 15 / integration 12. Per-category realistic
  subject templates. first_response_hours = priority base x era factor
  (1.0 → 1.2 → 1.8 across the year — the "worsening" story) x lognormal
  noise. resolution base: integration/feature_request 45h, login_bug 14,
  billing 10, how_to 4 (integration lands at 3.2x the others' median).
  Resolution probability decays for recent and low-priority tickets; CSAT
  1-5 only when resolved, penalized by long resolution times (179 missing
  CSAT cells give the parser real missing-data signal).
- **marketing_spend (800)**: 160 Mondays ending 2026-09-28 x 5 channels.
  Spend compounds weekly per channel (content fastest, +0.6%/wk) with Q4
  bumps (search 1.25x, social 1.35x) and noise; impressions from per-channel
  CPM, clicks from CTR, signups from click-to-signup rate (content's rate
  grows +0.5%/week — the compounding), conversions from signups. Resulting
  signups/$: email 1.011 > search 0.388 > content 0.321 (rising 0.24→0.38) >
  referral 0.273 > social 0.034.

## DEVIATIONS

1. **marketing_spend spans 160 weeks (~3.1 years), not "~2 years".** The row
   count pin (800 = 5 channels x 160 weeks) wins over the "~2 years" label;
   104 weeks would yield 520 rows. Brief: "800 rows (weekly, ~2 years)" —
   the exact number is enforced by tests.
2. **pandas not used inside the parser** (brief said "use it for dtype
   inference and quality stats" as guidance). Stdlib inference was chosen for
   determinism under pandas 3.x and exact raw-string previews; pandas is
   exposed via `to_dataframe()`. Interface impact: none.
3. **`ParsedDataset` gains additive fields** (`records`, `encoding`,
   `delimiter`) and a `to_dataframe()` method beyond the pinned six fields +
   `to_dict()`. Purely additive; `to_dict()` still returns exactly the pinned
   six keys. Agent 2's code (`parsed.columns or []` etc.) is unaffected and
   the full backend suite passes.
4. **`str` inputs to `parse_csv` are treated as a path if they name an
   existing file of ANY extension** (the stub limited this to .csv/.txt).
   Needed to load `.tsv` sample paths; multi-line CSV text can never be a
   valid path, so text handling is unchanged in practice.
5. **integration resolution base 45h** (brief story: "3x longer") — tuned so
   the *median* ratio vs all other categories is 3.2x; the first draft (65h)
   produced a 4.7x median, off-story.

## Verification

- `python -m pytest backend/connectors/tests -q` (repo root) → **88 passed**.
- `python -m pytest backend/tests -q` (cwd=backend) → **68 passed**
  (Agent 2's suite incl. all /api/upload tests against the new package).
- `python scripts/generate_samples.py` → writes + verifies 2000/5000/1500/800
  rows and prints the story summary; CSVs are committed on disk at
  `data/samples/`.
- Env vars needed from connectors: none.
