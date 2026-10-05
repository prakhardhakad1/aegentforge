"""Robust CSV/TSV ingestion for AgentForge.

This module is the parsing engine behind the pinned connector surface
(``connectors.parse_csv`` / ``connectors.parse_pasted_table`` — see
``docs/INTERFACES.md`` and ``backend/connectors/interface.md``).

Responsibilities:
    * accept bytes / file objects / filesystem paths / raw text uniformly,
    * decode with a charset fallback chain (utf-8-sig -> cp1252 -> latin-1),
    * sniff the field delimiter (comma, tab, semicolon, pipe),
    * detect/validate the header row (reject headerless numeric dumps),
    * infer a friendly per-column dtype vocabulary (integer, float, boolean,
      date, string, mixed, empty),
    * collect data-quality notes (missing values %, duplicate rows, constant
      columns, mixed-type columns, suspicious dates, ragged rows, encoding).

Design note: parsing and inference are implemented on the standard library
(``csv`` + ``re`` + ``datetime``) rather than pandas so behaviour is fully
deterministic across pandas major versions (this repo runs pandas 3.x) and so
preview cells are exact raw strings. :meth:`ParsedDataset.to_dataframe`
provides the optional pandas bridge.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Union

__all__ = [
    "ParsedDataset",
    "parse_csv",
    "parse_text_table",
    "sniff_delimiter",
    "detect_encoding",
    "MAX_COLUMNS",
    "PREVIEW_ROWS",
]

# ---------------------------------------------------------------------------
# Tunables / vocabulary
# ---------------------------------------------------------------------------

#: Hard cap on column count (pinned validation rule for /api/upload).
MAX_COLUMNS: int = 100

#: Maximum number of data rows kept in ``ParsedDataset.preview``.
PREVIEW_ROWS: int = 20

#: Datasets smaller than this many data rows get a "very small" note.
SMALL_DATASET_ROWS: int = 5

#: Date formats accepted for a *consistent* date column (tried in order).
_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d-%b-%Y",
    "%d %b %Y",
    "%b %d, %Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%d.%m.%Y",
)

#: Plausible year bounds; dates outside get flagged as suspicious.
_MIN_YEAR: int = 1900
_MAX_YEAR: int = 2100

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\.\d+|\d+(?![\d.]))(?:[eE][+-]?\d+)?$")
_MONTH_ABBREVS = frozenset(
    {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
)
_BOOL_WORDS = frozenset({"true", "false", "yes", "no", "y", "n", "t", "f"})
# 0/1 integer columns are only reported as boolean when the name hints at it.
_BOOL_NAME_RE = re.compile(
    r"^(is_|has_|was_)|(_flag|_indicator)$|^(churned|returned|resolved|converted|active|subscribed|renewed)$",
    re.IGNORECASE,
)
_DELIMITER_CANDIDATES: tuple[str, ...] = (",", "\t", ";", "|")

#: Dtype labels exposed in ``ParsedDataset.dtypes`` (pinned vocabulary).
DTYPES_VOCABULARY: tuple[str, ...] = (
    "integer",
    "float",
    "boolean",
    "date",
    "string",
    "mixed",
    "empty",
)


# ---------------------------------------------------------------------------
# Public data container
# ---------------------------------------------------------------------------


@dataclass
class ParsedDataset:
    """Profile of a parsed tabular dataset (pinned connector contract).

    Attributes:
        filename: Display filename (never a full path).
        row_count: Number of *data* rows (header excluded, blank lines skipped).
        columns: Header names, post-cleanup (stripped, empties auto-named,
            duplicates suffixed).
        dtypes: ``{column_name: dtype}`` using :data:`DTYPES_VOCABULARY`.
        preview: At most :data:`PREVIEW_ROWS` data rows as lists of raw string
            cells, padded/truncated to ``len(columns)``. JSON-safe.
        quality_notes: Human-readable data-quality observations. JSON-safe.
        records: All data rows as raw string cells (extension beyond the
            pinned fields; lets downstream agents rebuild a DataFrame without
            re-reading the file).
    """

    filename: str
    row_count: int
    columns: list[str]
    dtypes: dict[str, str] = field(default_factory=dict)
    preview: list[list[str]] = field(default_factory=list)
    quality_notes: list[str] = field(default_factory=list)
    records: list[list[str]] = field(default_factory=list)
    encoding: str = "utf-8"
    delimiter: str = ","

    def to_dict(self) -> dict[str, Any]:
        """Return the pinned JSON-safe dict shape (exactly the 6 contract keys)."""
        return {
            "filename": self.filename,
            "row_count": self.row_count,
            "columns": list(self.columns),
            "dtypes": dict(self.dtypes),
            "preview": [list(row) for row in self.preview],
            "quality_notes": list(self.quality_notes),
        }

    def to_dataframe(self) -> "Any":  # pragma: no cover - exercised via pandas in CI-less envs
        """Build a :class:`pandas.DataFrame`, coercing numeric/boolean columns.

        Raises:
            ImportError: If pandas is not installed (it is preinstalled in the
                shared AgentForge venv).
        """
        import pandas as pd  # local import: pandas is optional at module import time

        frame = pd.DataFrame(self.records, columns=self.columns)
        for column, dtype in self.dtypes.items():
            if dtype in ("integer", "float"):
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            elif dtype == "boolean":
                mapping = {
                    "true": True, "false": False, "yes": True, "no": False,
                    "y": True, "n": False, "t": True, "f": False, "1": True, "0": False,
                }
                frame[column] = frame[column].map(lambda v: mapping.get(str(v).strip().lower()))
            elif dtype == "date":
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
        return frame


# ---------------------------------------------------------------------------
# Encoding / delimiter detection
# ---------------------------------------------------------------------------


def detect_encoding(raw: bytes) -> tuple[str, str]:
    """Decode ``raw`` with a charset fallback chain.

    Chain: ``utf-8-sig`` (also strips a BOM) -> ``cp1252`` -> ``latin-1``
    (latin-1 maps every byte, so it always succeeds).

    Returns:
        ``(encoding_name, decoded_text)``.
    """
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return encoding, raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return "latin-1", raw.decode("latin-1")


def sniff_delimiter(text: str) -> str:
    """Sniff the field delimiter from the first ~20 non-blank lines.

    Scores each candidate (``,`` tab ``;`` ``|``) by how many lines contain it
    (consistency first, volume second). Falls back to ``,`` (single column).
    """
    lines = [line for line in text.split("\n")[:40] if line.strip()][:20]
    if not lines:
        return ","
    scores: dict[str, tuple[int, int]] = {}
    for candidate in _DELIMITER_CANDIDATES:
        per_line = [line.count(candidate) for line in lines]
        active_lines = sum(1 for count in per_line if count > 0)
        scores[candidate] = (active_lines, sum(per_line))
    best = max(scores.items(), key=lambda item: item[1])
    return best[0] if best[1][0] > 0 else ","


# ---------------------------------------------------------------------------
# Value-kind detection
# ---------------------------------------------------------------------------


def _looks_dateish(value: str) -> bool:
    """Cheap pre-filter before paying for strptime attempts."""
    if not value or len(value) > 32:
        return False
    if not any(char.isdigit() for char in value):
        return False
    first = value.lstrip()[0].lower()
    return first.isdigit() or value.lstrip()[:3].lower() in _MONTH_ABBREVS


def _parse_date(value: str) -> datetime | None:
    """Parse ``value`` with the known formats; reject implausible years."""
    if not _looks_dateish(value):
        return None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if _MIN_YEAR <= parsed.year <= _MAX_YEAR:
            return parsed
        return None  # parses but the year is implausible -> suspicious, not a date
    return None


def _value_kind(value: str) -> str:
    """Classify a single non-empty cell into a coarse value kind."""
    v = value.strip()
    if _INT_RE.match(v):
        return "int"
    if _FLOAT_RE.match(v):
        return "float"
    if v.lower() in _BOOL_WORDS:
        return "bool"
    if _parse_date(v) is not None:
        return "date"
    return "string"


def _consistent_date_format(values: list[str]) -> str | None:
    """Return a strptime format that matches *every* value, else ``None``."""
    candidates = list(_DATE_FORMATS)
    fmt_found: str | None = None
    for value in values:
        matched: str | None = None
        for fmt in candidates:
            try:
                parsed = datetime.strptime(value, fmt)
            except ValueError:
                continue
            if not (_MIN_YEAR <= parsed.year <= _MAX_YEAR):
                return None
            matched = fmt
            break
        if matched is None:
            return None
        candidates = [matched]  # every value must agree on one format
        fmt_found = matched
    return fmt_found


def _fraction_date_like(values: list[str]) -> tuple[float, set[str]]:
    """Fraction of values that parse as *some* date format + formats seen."""
    if not values:
        return 0.0, set()
    formats_seen: set[str] = set()
    hits = 0
    for value in values:
        if _parse_date(value) is not None:
            hits += 1
            for fmt in _DATE_FORMATS:
                try:
                    datetime.strptime(value, fmt)
                except ValueError:
                    continue
                formats_seen.add(fmt)
                break
    return hits / len(values), formats_seen


# ---------------------------------------------------------------------------
# Column inference + quality stats
# ---------------------------------------------------------------------------


def _infer_column(name: str, values: list[str], unique_values: list[str]) -> tuple[str, list[str]]:
    """Infer ``(dtype, extra_quality_notes)`` for one column.

    ``values`` are all raw cells (used for counts); ``unique_values`` are the
    deduplicated non-empty cells (used for type decisions).
    """
    notes: list[str] = []
    if not unique_values:
        return "empty", notes

    kinds = {_value_kind(v) for v in unique_values}

    # Word booleans (true/false/yes/no/...), or 0/1 integers in a boolean-named column.
    if kinds == {"bool"}:
        return "boolean", notes
    if kinds == {"int"} and _BOOL_NAME_RE.search(name) and set(v.strip() for v in unique_values) <= {"0", "1"}:
        return "boolean", notes

    # Dates: every value must agree on a single format.
    if kinds == {"date"}:
        if _consistent_date_format(unique_values[:500]) is not None:
            return "date", notes
        notes.append(
            f"Column '{name}' contains date-like values in inconsistent formats "
            f"(e.g. '{unique_values[0]}', '{unique_values[-1]}')"
        )
        return "string", notes

    if kinds == {"int"}:
        return "integer", notes
    if kinds <= {"int", "float"}:
        return "float", notes
    if len(kinds) == 1:
        dtype = next(iter(kinds))
        if dtype == "string":
            # Suspicious-date check: mostly date-like but not consistently parseable.
            sample = unique_values[:500]
            fraction, formats_seen = _fraction_date_like(sample)
            if fraction >= 0.6 and len(formats_seen) >= 1:
                notes.append(
                    f"Column '{name}' looks like dates stored as text in mixed or "
                    f"non-standard formats ({fraction:.0%} date-like); consider cleaning"
                )
            return "string", notes
        return dtype, notes

    families = ", ".join(sorted(kinds))
    notes.append(f"Column '{name}' has mixed value types ({families})")
    return "mixed", notes


def _dedupe_columns(header: list[str]) -> tuple[list[str], list[str]]:
    """Strip header cells, auto-name empties, suffix duplicates."""
    columns: list[str] = []
    notes: list[str] = []
    seen: dict[str, int] = {}
    renamed: list[str] = []
    for index, cell in enumerate(header):
        name = cell.strip()
        if not name:
            name = f"column_{index + 1}"
            renamed.append(name)
        if name in seen:
            seen[name] += 1
            original = name
            name = f"{name}_{seen[name]}"
            notes.append(f"Duplicate column name '{original}' renamed to '{name}'")
        else:
            seen[name] = 1
        columns.append(name)
    if renamed:
        notes.append(f"Empty header cell(s) auto-named: {', '.join(renamed)}")
    return columns, notes


def _quality_stats(
    columns: list[str], rows: list[list[str]]
) -> tuple[dict[str, str], list[str]]:
    """Compute dtypes and quality notes for the full dataset."""
    notes: list[str] = []
    dtypes: dict[str, str] = {}
    row_count = len(rows)

    # Transpose once: values per column (raw cells).
    per_column: list[list[str]] = [[] for _ in columns]
    for row in rows:
        for index, cell in enumerate(row):
            per_column[index].append(cell)

    for index, name in enumerate(columns):
        values = per_column[index]
        unique_values: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.strip()
            if key and key not in seen:
                seen.add(key)
                unique_values.append(value)
        dtype, extra = _infer_column(name, values, unique_values)
        dtypes[name] = dtype
        notes.extend(extra)

        # Missing values.
        missing = sum(1 for value in values if not value.strip())
        if missing:
            pct = (missing / row_count * 100.0) if row_count else 0.0
            notes.append(f"Column '{name}' has {missing} missing values ({pct:.1f}%)")

        # Constant columns.
        if row_count and unique_values and len(unique_values) == 1:
            constant = unique_values[0].strip()
            shown = constant if len(constant) <= 40 else constant[:37] + "..."
            notes.append(f"Column '{name}' is constant (single value: '{shown}')")

    # Duplicate full rows.
    if row_count:
        row_tuples = (tuple(row) for row in rows)
        seen_rows: set[tuple[str, ...]] = set()
        duplicates = 0
        for row_tuple in row_tuples:
            if row_tuple in seen_rows:
                duplicates += 1
            else:
                seen_rows.add(row_tuple)
        if duplicates:
            pct = duplicates / row_count * 100.0
            notes.append(f"{duplicates} duplicate data rows detected ({pct:.1f}%)")

    # Aggregate missing-value summary.
    total_cells = row_count * len(columns)
    if total_cells:
        missing_cells = sum(
            sum(1 for row in rows if not row[index].strip()) for index in range(len(columns))
        )
        if missing_cells:
            pct = missing_cells / total_cells * 100.0
            notes.insert(
                0, f"{pct:.1f}% of all cells are empty ({missing_cells}/{total_cells})"
            )

    return dtypes, notes


def _cap_missing_notes(notes: list[str]) -> list[str]:
    """Keep per-column note lists readable when many columns share a problem."""
    missing = [n for n in notes if "missing values" in n and "of all cells" not in n]
    if len(missing) > 8:
        for note in missing[8:]:
            notes.remove(note)
        others = len(missing) - 8
        notes.append(f"...and {others} more column(s) with missing values")
    return notes


# ---------------------------------------------------------------------------
# Core text -> ParsedDataset engine
# ---------------------------------------------------------------------------


def parse_text_table(
    text: str,
    *,
    filename: str,
    delimiter: str | None = None,
    encoding: str = "utf-8",
) -> ParsedDataset:
    """Parse already-decoded table text into a :class:`ParsedDataset`.

    Args:
        text: The full table as text (any newline convention).
        filename: Display filename for the result.
        delimiter: Force a delimiter; ``None`` sniffs one from the text.
        encoding: Encoding name used to decode the source (for quality notes).

    Raises:
        ValueError: On empty input, binary content, > MAX_COLUMNS columns, or
            a first row that cannot be a header.
    """
    if "\x00" in text:
        raise ValueError(
            "Input looks like a binary file (contains NUL bytes); a CSV text file was expected"
        )

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if delimiter is None:
        delimiter = sniff_delimiter(normalized)

    reader = csv.reader(
        io.StringIO(normalized), delimiter=delimiter, quotechar='"', skipinitialspace=True
    )
    all_rows = [row for row in reader if any(cell.strip() for cell in row)]

    if not all_rows:
        raise ValueError("CSV appears to be empty (no header or data rows found)")

    if len(all_rows[0]) > MAX_COLUMNS:
        raise ValueError(
            f"CSV has {len(all_rows[0])} columns; the maximum supported is {MAX_COLUMNS}"
        )

    # --- Header detection -------------------------------------------------
    header_row = all_rows[0]
    if len(all_rows) > 1:
        second_row = all_rows[1]
        first_kinds = {_value_kind(cell) for cell in header_row if cell.strip()}
        second_kinds = {_value_kind(cell) for cell in second_row if cell.strip()}
        numericish = {"int", "float", "date"}
        if (
            first_kinds
            and first_kinds <= numericish
            and second_kinds
            and second_kinds <= numericish
        ):
            raise ValueError(
                "No header row detectable: the first row looks like data "
                "(all values are numeric or date-like). Provide a CSV whose "
                "first row contains column names."
            )

    columns, header_notes = _dedupe_columns(header_row)
    if len(columns) > MAX_COLUMNS:
        raise ValueError(
            f"CSV has {len(columns)} columns; the maximum supported is {MAX_COLUMNS}"
        )
    data_rows = all_rows[1:]

    # --- Ragged row handling ----------------------------------------------
    ragged: list[str] = []
    padded = 0
    truncated = 0
    width = len(columns)
    for row in data_rows:
        if len(row) < width:
            row.extend([""] * (width - len(row)))
            padded += 1
        elif len(row) > width:
            del row[width:]
            truncated += 1
    if padded:
        ragged.append(f"{padded} row(s) had fewer fields than the header and were padded with empty cells")
    if truncated:
        ragged.append(f"{truncated} row(s) had extra fields and were truncated to {width} columns")

    # --- Inference + stats --------------------------------------------------
    dtypes, quality = _quality_stats(columns, data_rows)
    quality = _cap_missing_notes(quality)

    notes: list[str] = []
    notes.extend(header_notes)
    notes.extend(ragged)
    if encoding not in ("utf-8", "utf-8-sig"):
        notes.append(
            f"File was decoded as {encoding} (not UTF-8); special characters may be affected"
        )
    if len(data_rows) < SMALL_DATASET_ROWS:
        notes.append(f"Very small dataset (< {SMALL_DATASET_ROWS} data rows)")
    notes.extend(quality)

    return ParsedDataset(
        filename=filename,
        row_count=len(data_rows),
        columns=columns,
        dtypes=dtypes,
        preview=[list(row[:width]) for row in data_rows[:PREVIEW_ROWS]],
        quality_notes=notes,
        records=[list(row) for row in data_rows],
        encoding=encoding,
        delimiter=delimiter,
    )


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------

_Source = Union[BinaryIO, bytes, bytearray, str, "os.PathLike[str]"]  # noqa: F821


def _coerce_to_bytes(source: Any) -> bytes:
    """Normalize every accepted source type to raw bytes."""
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if isinstance(source, str):
        candidate = Path(source)
        if candidate.is_file():
            return candidate.read_bytes()
        return source.encode("utf-8")
    if isinstance(source, Path):
        if not source.is_file():
            raise ValueError(f"File not found: {source}")
        return source.read_bytes()
    if hasattr(source, "read"):
        payload = source.read()
        if isinstance(payload, str):
            return payload.encode("utf-8")
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)
    raise TypeError(
        "parse_csv expects a file object, bytes, a filesystem path, or text; "
        f"got {type(source).__name__}"
    )


def parse_csv(source: Any, filename: str | None = None) -> ParsedDataset:
    """Parse a CSV/TSV from a file object, bytes, path, or raw text.

    Args:
        source: One of:
            * open file object (binary or text mode, anything with ``.read``),
            * ``bytes`` / ``bytearray`` (the /api/upload path),
            * :class:`pathlib.Path` or a ``str`` that is an existing file path,
            * a ``str`` containing the raw CSV text (used when the string is
              not an existing file).
        filename: Display filename override; defaults to the path's basename
            or ``"upload.csv"``.

    Returns:
        ParsedDataset: Profiled dataset (see the module docstring).

    Raises:
        ValueError: Empty input, binary content, more than
            :data:`MAX_COLUMNS` columns, or no detectable header row. The API
            layer surfaces these messages to the client.
        TypeError: Unsupported source type.
        OSError: Path given but unreadable.
    """
    raw = _coerce_to_bytes(source)
    if not raw.strip():
        raise ValueError("CSV appears to be empty (0 bytes of input)")

    encoding, text = detect_encoding(raw)

    resolved_name = filename
    if resolved_name is None:
        if isinstance(source, Path):
            resolved_name = source.name
        elif isinstance(source, str) and Path(source).is_file():
            resolved_name = Path(source).name
        else:
            resolved_name = "upload.csv"

    return parse_text_table(text, filename=resolved_name, encoding=encoding)
