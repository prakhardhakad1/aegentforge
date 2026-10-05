# orchestrator.report — Agent 6 NOTES

The insight engine: turns a finished agent run (`RunResult.to_dict()`) into the
pinned structured deliverable (Markdown + PDF). Owns ONLY
`packages/orchestrator/orchestrator/report/`.

## Public surface (pinned)

```python
from orchestrator.report import build_report, render_markdown, export_pdf

report: dict = build_report(run_result.to_dict(), style="sales_insights")  # pinned dict shape
markdown: str = render_markdown(report)          # accepts dict | Report model
path: Path    = export_pdf(report, "out.pdf")    # accepts dict | Report model | markdown str
```

`__init__.py` also exposes `run_critic_checklist` (alias `critic_checklist`),
`models` (Report/Insight/Prediction/Recommendation/ChartSpec/Strength/Effort),
and `styles` (StyleProfile/get_style/list_styles).

## File map

| File | Role |
|---|---|
| `models.py` | Pinned pydantic models + defensive coercion (never rejects sloppy input it can repair) |
| `build.py` | `build_report` pipeline: parse → collect → extract → rank → assemble → checklist → summary → appendix |
| `critic_checklist.py` | R1-R7 rejection rules; strips unsupported claims before summarization |
| `render_markdown.py` | GitHub-flavored markdown renderer, style-ordered sections |
| `export_pdf.py` | markdown → HTML (python-markdown) → block parse → fpdf2 (pure python, Windows-safe) |
| `styles/__init__.py` | 4 frozen StyleProfile dataclasses (default + 3 marketplace teams) |
| `tests/` | 145 tests: fixtures (churn/empty/partial/unsupported runs), build, checklist, markdown, PDF, styles, package surface |

## Pipeline design (build.py)

1. **Parse** — defensive normalization; missing/None/non-list fields tolerated;
   `run_result` must be a dict (TypeError otherwise).
2. **Collect** — artifacts grouped by pinned kind (text/table/chart/prediction/
   recommendation/other), order preserved.
3. **Extract** — candidate insights from artifact summaries (max 4 sentences per
   artifact) and step outputs (max 2 per step, failed/skipped steps excluded).
   Recommendation-shaped sentences ("we recommend...") are excluded from the
   insight stream. Prediction artifacts also become forecast-titled candidates.
4. **Rank** — see heuristics below. Cap per style profile.
5. **Charts** — chart artifacts → validated ChartSpecs; explicit-but-invalid
   `kind` drops the chart (counted in `meta.stats.charts_dropped`); missing kind
   defaults to `bar`. ChartSpec gets additive `path`/`artifact_id` provenance.
6. **Predictions** — from prediction artifacts (`claim/confidence/basis` or
   `probability/rationale`), falling back to parsing confidence out of free text
   ("82%", "0.82"). Missing confidence → 0.5 + `confidence_assumed` flag;
   missing basis → derived honest placeholder + `basis_derived` flag. If no
   prediction artifacts exist, a forecaster step output may produce one.
7. **Recommendations** — impact/effort priority matrix; `priority` 1..n
   written 1 = do first (clamped 5).
8. **Critic checklist** runs BEFORE the summary, so flagged claims never leak
   into the executive summary.
9. **Exec summary** — deterministic template synthesis, block order follows the
   style's `exec_summary_emphasis`. Optional LLM polish only when
   `LLM_MODE=live` AND `orchestrator.llm` is importable; any failure falls back
   silently. Zero-LLM is the default and the tested path.
10. **Appendix** — run details, plan, token usage (formatted), errors, data
    coverage, honest notes about empty required sections and critic issues.

## Ranking heuristics (deterministic)

`score = min(#evidence refs, 3) + 1.5 if numeric grounding + 0.5 if a percentage
+ 1.0 if ≥2 distinct refs (cross-source corroboration) + 0.5 if detail > 120
chars (specificity proxy) − 0.5 if hedged ("maybe/might/could")`.

Strength mapping: score ≥ 3.0 → high, ≥ 1.8 → medium, else low. Thresholds chosen
so a single-ref numeric claim ranks medium, a step+artifact cross-cited numeric
claim ranks high, and any vague uncited sentence stays low. Near-duplicate claims
deduped by normalized opening (best-evidenced copy kept).

## Critic checklist rules (critic_checklist.py)

- **R1 `unsupported_claim`** — zero evidence refs AND no numeric grounding →
  strength → low + flag.
- **R2 `overclaim`** — strength high with <2 refs and no numbers → medium + flag.
- **R3 `absolute_claim`** — "guaranteed/always/never/everyone..." without a real
  citation (numeric grounding or an explicit source phrase) → low + flag;
  predictions get confidence capped at 0.6.
- **R4** — every prediction needs confidence + basis; missing basis patched with
  an honest placeholder (+`missing_basis`), missing confidence assumed 0.5
  (+`confidence_assumed`, issue recorded).
- **R5** — every recommendation needs action + expected_impact; patched with
  honest placeholders (+flags).
- **R6** — charts without data points are dropped.
- **R7** — insights re-sorted strongest-first after downgrades.

Returns `(report, issues)`; issues also written to `report.meta["critic_issues"]`
/ `meta["critic_clean"]`. Flagged/low insights are excluded from the executive
summary ("without endorsement" note when everything was flagged).

## PDF renderer (export_pdf.py)

markdown → HTML (`python-markdown`, tables/fenced_code/sane_lists) → minimal
HTMLParser block extraction → fpdf2. Cover block (title/mission/meta), headings
with rules, paragraphs, blockquotes, bullets, bordered tables with header fill,
embedded chart images (when the artifact path exists on disk), page-number
footers. Text sanitized to latin-1 via a typographic-char map (fpdf2 core
fonts); anything exotic degrades instead of crashing.

**Robustness (fixes the reported integration bug):** the HTML parser used to
hand `_write_table` a list of ROWS as `headers`, crashing on the first
table-heavy report (`'list' object has no attribute 'strip'`) and again in the
fallback (`TypeError` joining lists). Now: head rows replace (not append), all
cells coerced to str via `_cell_text`, tables squared to one column count
(pad/truncate), `_col_widths` hints only applied on exact known-table shapes
(a wrong-length hint raises inside fpdf2), and any residual fpdf2 failure falls
back to plain-paragraph rendering. Verified: fpdf2 wraps >300-char unbroken
tokens natively.

## Styles

`default` (insight-led), `market_research` (insight+charts required,
"market signal" vocabulary), `sales_insights` (recommendations lead, required
insights+recommendations), `support_triage` (predictions lead). Each controls
section order, exec-summary emphasis/length, section caps. `get_style` also
accepts marketplace template ids (`sales_insights_team`) by stripping the
`_team` suffix — the engine passes `template_id` straight through as `style`.

## Test coverage

`python -m pytest packages/orchestrator/orchestrator/report/tests -q` →
**145 passed**. Fixtures in `tests/fixtures.py`: succeeded churn run (text +
chart + prediction + recommendation artifacts), empty run, partial run with a
failed step, unsupported-claims run. Includes the table-heavy PDF regression,
unicode/emoji PDF, multipage PDF, ragged tables, style switching, ranking
invariants, checklist rejection, and the pinned `__init__` surface/signatures.

## DEVIATIONS

- **Additive report fields** (beyond the pinned contract): `Insight.flags/score/
  rank`, `Prediction.evidence/flags`, `Recommendation.evidence/flags`,
  `ChartSpec.path/artifact_id`, `Report.meta` (run diagnostics incl.
  `critic_issues`, `stats`, `style_fallback`). Consumers reading only pinned
  keys are unaffected.
- **`get_style` accepts `<style>_team` template ids** (strips suffix). Needed
  because `engine.execute_run` calls `build_report(..., style=template_id)`;
  without it every marketplace run would silently render as `default`.
- **pyproject deps**: this subpackage imports `fpdf2` + `markdown`, which are
  NOT in `packages/orchestrator/pyproject.toml` `dependencies` (httpx, pydantic
  only — Agent 3 owns that file, I cannot touch it). Both are in the pinned
  shared venv (fpdf 2.8.9, markdown 3.11) so the repo runs as-is. Coordinator:
  consider `extras = {"report": ["fpdf2>=2.7", "markdown>=3.5"]}` at merge.
- **Import isolation**: the subpackage imports only stdlib + pydantic + fpdf2 +
  markdown at import time. `orchestrator.llm` is imported lazily inside
  `_llm_polish_summary`, guarded by `LLM_MODE=live`, wrapped in try/except —
  the report pipeline never depends on orchestrator core or an LLM.

## Env vars used

- `LLM_MODE` (read-only, optional polish gate; anything but `live` = deterministic mode).
- `AGENTFORGE_DEBUG` (export_pdf: re-raise table fallback errors for debugging).

No env vars added; nothing needs `.env.example` changes.
