# connectors — Interface Contract (for Agent 2 / backend)

Owner: Agent 5. Package import name: `connectors` (backend runs with
`cwd=backend`, so `from connectors import parse_csv` works inside `app`).
Pinned by `docs/INTERFACES.md`; this file documents the exact behavior.

## Public surface

```python
from connectors import (
    ParsedDataset,
    parse_csv,
    parse_pasted_table,
    load_sample,
    SAMPLE_IDS,          # ("saas_churn", "ecommerce_sales", "support_tickets", "marketing_spend")
    SAMPLE_META,         # {sample_id: {name, description, row_count, story}}
    DATA_DICTIONARIES,   # {sample_id: {column: {type, units, description}}}
)
```

Also exported (internal-but-stable): `parse_text_table`, `sniff_delimiter`,
`detect_encoding`, `clean_pasted_text`, `detect_paste_delimiter`,
`MAX_COLUMNS` (100), `PREVIEW_ROWS` (20), `DTYPES_VOCABULARY`, `__version__`.

## Functions

### `parse_csv(source, filename=None) -> ParsedDataset`
Accepts **uniformly**: an open file object (binary or text mode), raw
`bytes`/`bytearray` (the /api/upload path), a `pathlib.Path` or a `str` that is
an existing filesystem path, or a `str`/`Path`-less raw CSV text (a `str` is
treated as a path only if it names an existing file). Unsupported types raise
`TypeError`.

Encoding fallback chain: `utf-8-sig` (BOM stripped) -> `cp1252` -> `latin-1`
(always succeeds). A non-UTF-8 decode adds a quality note. NUL bytes →
`ValueError` ("binary file").

Validation (raises `ValueError` — the API maps these to 422 verbatim):
- empty input (0 bytes / whitespace only),
- binary content (NUL bytes),
- more than 100 columns,
- no header detectable (first row all-numeric/date-like while a second,
  also-numeric row exists, or the first row is blank).

Delimiter sniffing: comma, tab, semicolon, pipe — scored by line consistency
across the first ~20 non-blank lines. Blank lines are skipped (not counted in
`row_count`). Quoted fields (embedded commas/newlines/escaped quotes) are
handled per RFC-4180-ish semantics with `skipinitialspace`.

### `parse_pasted_table(text, filename="pasted_table.csv") -> ParsedDataset`
Google-Sheets/Excel-style paste: strips clipboard padding (trailing tabs and
spaces per line), trailing blank lines, CRLF; sniffs tab vs comma vs `;` vs
`|` (tab wins ties — spreadsheet copies are tab-separated); then runs the same
engine as `parse_csv` (same dtypes, quality notes, validation, ValueErrors).

### `load_sample(sample_id) -> (ParsedDataset, data_dictionary)`
`sample_id` must be one of `SAMPLE_IDS` (else `KeyError` naming the valid ids).
Resolves `<repo>/data/samples/{sample_id}.csv` robustly (primary candidate is
derived from the package location, so `cwd=backend` works; falls back to
cwd-relative candidates). Returns `(ParsedDataset, dict)` where the dictionary
is JSON-safe: `{sample_id, name, description, story, row_count, path,
columns: {column: {type, units, description}}, generator}`.

## ParsedDataset (pinned fields)

| field | type | notes |
|---|---|---|
| `filename` | str | display name, never a full path |
| `row_count` | int | data rows, header excluded, blank lines skipped |
| `columns` | list[str] | stripped; empty header cells auto-named `column_N`; duplicates suffixed `_2` (with notes) |
| `dtypes` | dict[str, str] | per column: `integer` \| `float` \| `boolean` \| `date` \| `string` \| `mixed` \| `empty` |
| `preview` | list[list[str]] | ≤ 20 rows, raw **string** cells, padded/truncated to `len(columns)` — JSON-safe |
| `quality_notes` | list[str] | see below |

`.to_dict()` returns exactly the six pinned keys above (JSON-safe).
Extensions beyond the pinned fields (additive, non-breaking): `records`
(all data rows as string cells) and `to_dataframe()` (pandas bridge coercing
numeric/boolean/date columns), plus `encoding` and `delimiter`.

Dtype vocabulary details:
- `date`: all values parse under ONE consistent format (ISO date/datetime,
  `YYYY/MM/DD`, `DD-Mon-YYYY`, `Mon DD, YYYY`, `DD/MM/YYYY`, `MM/DD/YYYY`,
  `DD-MM-YYYY`, `MM-DD-YYYY`, `DD.MM.YYYY`); years outside 1900-2100 are
  rejected. Year-month strings like `2026-01` are `string`, not `date`.
- `boolean`: true/false/yes/no/y/n/t/f words; or all-0/1 integers in a column
  whose name hints at a flag (`is_*`, `has_*`, `*_flag`, `churned`,
  `returned`, `resolved`, ...). Un-hinted 0/1 stays `integer`.
- `mixed`: value kinds span multiple families (e.g. numeric + text) — noted.
- `$1,234`-style currency and `12%` are `string` (deliberately conservative).

Quality notes produced (all optional, only when detected): overall `% of all
cells are empty`, per-column missing counts/percentages, `N duplicate data
rows`, constant columns, mixed-type columns, inconsistent or suspicious date
formats, ragged rows (padded/truncated), duplicate/empty header names, non-UTF-8
encoding, `Very small dataset (< 5 data rows)`.

## /api/upload integration (as implemented in backend/app/api/routes/uploads.py)

```python
parsed = parse_csv(payload_bytes, filename=filename)   # bytes in
# except ValueError -> 422 with str(exc)
# response fields map 1:1 to ParsedDataset fields (all str-safe already)
```

## Sample datasets (data/samples/, generated by scripts/generate_samples.py)

| id | rows | story anchor |
|---|---|---|
| `saas_churn` | 2,000 | 24.8% churn; basic 37% vs enterprise 8%; usage collapse precedes churn |
| `ecommerce_sales` | 5,000 | Q4 spike (Nov+Dec = 27% of revenue); mobile share growth; books declining; 7.9% returns |
| `support_tickets` | 1,500 | billing+login_bug = 56% of volume; integration ~3x median resolution; response times worsening |
| `marketing_spend` | 800 | email/search best ROI; content compounds; social underperforms |

Full rubric with measured numbers: `data/samples/EXPECTED_INSIGHTS.md`.
