"""Pasted-table parsing: Sheets-style tabs, clipboard junk, delimiter sniffing."""

from __future__ import annotations

import pytest

from connectors import parse_pasted_table


def test_tab_paste_from_google_sheets() -> None:
    text = "name\tqty\tprice\nWidget\t3\t9.99\nGadget\t1\t24.50\n"
    parsed = parse_pasted_table(text, filename="paste.tsv")
    assert parsed.filename == "paste.tsv"
    assert parsed.columns == ["name", "qty", "price"]
    assert parsed.row_count == 2
    assert parsed.dtypes["qty"] == "integer"
    assert parsed.dtypes["price"] == "float"


def test_clipboard_padding_and_trailing_newlines_stripped() -> None:
    text = "a\tb\t\n1\t2\t\n3\t4\t\n\n\n"
    parsed = parse_pasted_table(text)
    assert parsed.columns == ["a", "b"]
    assert parsed.row_count == 2
    assert parsed.records == [["1", "2"], ["3", "4"]]


def test_comma_paste_detected() -> None:
    text = "city,pop\nparis,2100\nlima,970\n"
    parsed = parse_pasted_table(text)
    assert parsed.columns == ["city", "pop"]
    assert parsed.delimiter == ","
    assert parsed.dtypes["pop"] == "integer"


def test_quoted_cell_with_comma_in_tab_paste() -> None:
    text = 'phrase\tn\n"hello, world"\t1\nplain\t2\n'
    parsed = parse_pasted_table(text)
    assert parsed.row_count == 2
    assert parsed.records[0][0] == "hello, world"


def test_empty_paste_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_pasted_table("   \n\t\n")


def test_non_string_rejected() -> None:
    with pytest.raises(TypeError):
        parse_pasted_table(b"bytes paste")  # type: ignore[arg-type]


def test_headerless_numeric_paste_rejected() -> None:
    with pytest.raises(ValueError, match="[Nn]o header"):
        parse_pasted_table("1\t2\n3\t4\n5\t6\n")


def test_default_filename_applied() -> None:
    parsed = parse_pasted_table("a\n1\n")
    assert parsed.filename == "pasted_table.csv"


def test_crlf_paste() -> None:
    parsed = parse_pasted_table("a,b\r\n1,2\r\n3,4\r\n")
    assert parsed.row_count == 2
