"""Google-Sheets-style pasted-table parsing for AgentForge.

Handles text pasted from spreadsheet apps (Excel, Google Sheets, Numbers) or
typed CSV: tab- or comma-separated, clipboard padding (trailing tabs/spaces
per line), trailing blank lines, mixed line endings, and quoted cells.

The module normalizes the paste and delegates to
:func:`connectors.csv_parser.parse_text_table` for delimiter-consistent
parsing, type inference, and quality notes.
"""

from __future__ import annotations

from collections import Counter

from .csv_parser import ParsedDataset, parse_text_table

__all__ = ["parse_pasted_table", "clean_pasted_text", "detect_paste_delimiter"]

#: Delimiters considered when sniffing a paste (in priority order).
_PASTE_DELIMITERS: tuple[str, ...] = ("\t", ",", ";", "|")


def clean_pasted_text(text: str) -> str:
    """Normalize clipboard text.

    * unify line endings (CRLF / CR -> LF),
    * strip the UTF-8 BOM if a BOM'd text slipped through,
    * remove trailing tabs/spaces on every line (Sheets pads cells),
    * drop trailing blank lines (clipboard usually ends with one).
    """
    cleaned = text.replace("﻿", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip("\t ") for line in cleaned.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def detect_paste_delimiter(cleaned: str) -> str:
    """Pick the delimiter used by a cleaned paste (majority vote across lines).

    Tab wins on ties because spreadsheet copies (Excel / Google Sheets) paste
    tab-separated rows; typed pastes are usually comma-separated.
    """
    lines = [line for line in cleaned.split("\n") if line.strip()][:50]
    votes: Counter[str] = Counter()
    for line in lines:
        for delimiter in _PASTE_DELIMITERS:
            if delimiter in line:
                votes[delimiter] += 1
    if not votes:
        return ","
    best_count = max(votes.values())
    for delimiter in _PASTE_DELIMITERS:
        if votes.get(delimiter, 0) == best_count:
            return delimiter
    return ","  # pragma: no cover - unreachable


def parse_pasted_table(text: str, filename: str = "pasted_table.csv") -> ParsedDataset:
    """Parse pasted table text (Google-Sheets-style) into a ParsedDataset.

    Accepts tab- or comma-separated pastes (semicolons and pipes are also
    sniffed), strips clipboard padding and trailing blank lines, then runs the
    shared parsing engine (type inference, quality notes, <=20-row preview).

    Args:
        text: Raw pasted text (may include trailing tabs, CRLF, blank lines).
        filename: Display filename for the resulting dataset.

    Returns:
        ParsedDataset: Profiled dataset, same shape as :func:`parse_csv`.

    Raises:
        ValueError: Empty paste, binary content, > 100 columns, or no
            detectable header row (surfaced verbatim by /api/upload).
    """
    if not isinstance(text, str):
        raise TypeError(
            f"parse_pasted_table expects pasted text (str); got {type(text).__name__}"
        )
    cleaned = clean_pasted_text(text)
    if not cleaned.strip():
        raise ValueError("Pasted table appears to be empty (no usable rows found)")
    delimiter = detect_paste_delimiter(cleaned)
    return parse_text_table(cleaned, filename=filename, delimiter=delimiter)
