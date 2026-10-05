"""CSV parsing edge cases: encodings, delimiters, quoting, inference, validation."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from connectors import MAX_COLUMNS, ParsedDataset, parse_csv


# --------------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------------


def _to_bytes(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


BASIC = "name,age,score\nalice,34,91.5\nbob,28,78.0\ncarol,41,88.25\n"


# --------------------------------------------------------------------------- #
# Input uniformity
# ---------------------------------------------------------------------------


def test_parse_csv_from_bytes() -> None:
    parsed = parse_csv(_to_bytes(BASIC), filename="people.csv")
    assert parsed.filename == "people.csv"
    assert parsed.row_count == 3
    assert parsed.columns == ["name", "age", "score"]
    assert parsed.dtypes == {"name": "string", "age": "integer", "score": "float"}


def test_parse_csv_from_file_object_binary() -> None:
    parsed = parse_csv(io.BytesIO(_to_bytes(BASIC)), filename="people.csv")
    assert parsed.row_count == 3
    assert parsed.columns == ["name", "age", "score"]


def test_parse_csv_from_file_object_text() -> None:
    parsed = parse_csv(io.StringIO(BASIC), filename="people.csv")
    assert parsed.row_count == 3


def test_parse_csv_from_path_object(tmp_path: Path) -> None:
    target = tmp_path / "people.csv"
    target.write_text(BASIC, encoding="utf-8")
    parsed = parse_csv(target)
    assert parsed.filename == "people.csv"
    assert parsed.row_count == 3


def test_parse_csv_from_path_string(tmp_path: Path) -> None:
    target = tmp_path / "people.csv"
    target.write_text(BASIC, encoding="utf-8")
    parsed = parse_csv(str(target))
    assert parsed.filename == "people.csv"
    assert parsed.row_count == 3


def test_parse_csv_from_raw_text_string() -> None:
    parsed = parse_csv(BASIC, filename="inline.csv")
    assert parsed.row_count == 3
    assert parsed.columns == ["name", "age", "score"]


def test_parse_csv_unsupported_type_raises_typeerror() -> None:
    with pytest.raises(TypeError):
        parse_csv(12345)  # type: ignore[arg-type]


def test_to_dict_is_pinned_shape_and_json_safe() -> None:
    parsed = parse_csv(_to_bytes(BASIC), filename="people.csv")
    payload = parsed.to_dict()
    assert set(payload) == {
        "filename", "row_count", "columns", "dtypes", "preview", "quality_notes",
    }
    assert payload["row_count"] == 3
    assert isinstance(payload["dtypes"], dict)
    assert all(isinstance(row, list) for row in payload["preview"])


# --------------------------------------------------------------------------- #
# Encoding
# ---------------------------------------------------------------------------


def test_utf8_bom_is_stripped() -> None:
    parsed = parse_csv(b"\xef\xbb\xbf" + _to_bytes(BASIC), filename="bom.csv")
    assert parsed.columns == ["name", "age", "score"]
    assert parsed.encoding == "utf-8-sig"


def test_non_utf8_bytes_decoded_with_note() -> None:
    text = "city,sales\nM\xfcnchen,100\nK\xf8benhavn,80\n"
    parsed = parse_csv(_to_bytes(text, "latin-1"), filename="euro.csv")
    assert parsed.columns == ["city", "sales"]
    assert parsed.row_count == 2
    # \xf8 (o-slash) and \xfc (u-umlaut) are single-byte identical in cp1252 and
    # latin-1; the chain must stop somewhere before latin-1 and flag it.
    assert parsed.encoding in ("cp1252", "latin-1")
    assert any("not UTF-8" in note for note in parsed.quality_notes)
    assert any(row[0] in ("M\xfcnchen", "K\xf8benhavn") for row in parsed.records)


def test_cp1252_bytes_decoded() -> None:
    # U+201C (left smart quote) encodes to byte 0x93 in cp1252, which is
    # invalid utf-8 -- so the chain must land on cp1252 and round-trip it.
    text = "note,value\n“café corner”,5\nplain,7\n"
    parsed = parse_csv(text.encode("cp1252"), filename="cp.csv")
    assert parsed.row_count == 2
    assert parsed.encoding == "cp1252"
    assert parsed.records[0][0] == "“café corner”"
    assert any("not UTF-8" in note for note in parsed.quality_notes)


def test_binary_content_rejected() -> None:
    with pytest.raises(ValueError, match="binary"):
        parse_csv(b"PK\x03\x04\x00\x00 some zip bytes")


# --------------------------------------------------------------------------- #
# Delimiters / structure
# ---------------------------------------------------------------------------


def test_tsv_sniffed_and_parsed() -> None:
    tsv = "name\tage\nalice\t34\nbob\t28\n"
    parsed = parse_csv(_to_bytes(tsv), filename="tab.tsv")
    assert parsed.columns == ["name", "age"]
    assert parsed.delimiter == "\t"
    assert parsed.dtypes["age"] == "integer"


def test_semicolon_delimiter_sniffed() -> None:
    text = "a;b;c\n1;2;3\n4;5;6\n"
    parsed = parse_csv(_to_bytes(text), filename="semi.csv")
    assert parsed.columns == ["a", "b", "c"]
    assert parsed.delimiter == ";"


def test_quoted_fields_with_commas_and_newlines() -> None:
    text = 'name,notes\nsmith,"hello, world"\ndoe,"line one\nline two"\n'
    parsed = parse_csv(_to_bytes(text), filename="quoted.csv")
    assert parsed.row_count == 2
    assert parsed.records[0][1] == "hello, world"
    assert parsed.records[1][1] == "line one\nline two"


def test_escaped_quotes_inside_quoted_field() -> None:
    text = 'phrase,score\n"he said ""hi""",10\nplain,5\n'
    parsed = parse_csv(_to_bytes(text), filename="quotes.csv")
    assert parsed.records[0][0] == 'he said "hi"'


def test_blank_lines_skipped() -> None:
    text = "a,b\n1,2\n\n\n3,4\n"
    parsed = parse_csv(_to_bytes(text), filename="blanks.csv")
    assert parsed.row_count == 2
    assert parsed.preview == [["1", "2"], ["3", "4"]]


def test_ragged_rows_padded_and_truncated_with_notes() -> None:
    text = "a,b,c\n1,2\n3,4,5,6\n7,8,9\n"
    parsed = parse_csv(_to_bytes(text), filename="ragged.csv")
    assert parsed.row_count == 3
    assert parsed.records[0] == ["1", "2", ""]
    assert parsed.records[1] == ["3", "4", "5"]
    assert any("padded" in note for note in parsed.quality_notes)
    assert any("truncated" in note for note in parsed.quality_notes)


def test_crlf_line_endings() -> None:
    parsed = parse_csv(_to_bytes("a,b\r\n1,2\r\n3,4\r\n"), filename="crlf.csv")
    assert parsed.row_count == 2


def test_preview_capped_at_20_rows() -> None:
    text = "n\n" + "\n".join(str(i) for i in range(50)) + "\n"
    parsed = parse_csv(_to_bytes(text), filename="long.csv")
    assert parsed.row_count == 50
    assert len(parsed.preview) == 20
    assert all(isinstance(cell, str) for row in parsed.preview for cell in row)


def test_preview_cells_are_raw_strings() -> None:
    parsed = parse_csv(_to_bytes("m,r,u,v\n2026-01,west,120,4800.50\n"), filename="x.csv")
    assert parsed.preview[0] == ["2026-01", "west", "120", "4800.50"]


# --------------------------------------------------------------------------- #
# Validation (pinned rules)
# ---------------------------------------------------------------------------


def test_empty_bytes_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_csv(b"", filename="empty.csv")


def test_whitespace_only_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_csv(b"\n \n\t\n", filename="blank.csv")


def test_too_many_columns_rejected() -> None:
    header = ",".join(f"col_{i}" for i in range(MAX_COLUMNS + 1))
    with pytest.raises(ValueError, match="columns"):
        parse_csv(_to_bytes(header + "\n" + ",".join(["1"] * (MAX_COLUMNS + 1))))


def test_headerless_numeric_dump_rejected() -> None:
    text = "1,2,3\n4,5,6\n7,8,9\n"
    with pytest.raises(ValueError, match="[Nn]o header"):
        parse_csv(_to_bytes(text), filename="headerless.csv")


def test_headerless_single_numeric_column_rejected() -> None:
    with pytest.raises(ValueError, match="[Nn]o header"):
        parse_csv(_to_bytes("42\n43\n44\n"))


def test_headers_only_file_is_valid() -> None:
    parsed = parse_csv(_to_bytes("col_a,col_b\n"), filename="headers.csv")
    assert parsed.row_count == 0
    assert parsed.columns == ["col_a", "col_b"]
    assert any("small" in note.lower() for note in parsed.quality_notes)


# --------------------------------------------------------------------------- #
# Type inference
# ---------------------------------------------------------------------------


def test_dtype_vocabulary_integer_float_string_date_boolean_mixed() -> None:
    text = (
        "id,count,ratio,when,flag,note,weird\n"
        "a,1,1.5,2026-01-05,true,ok,1\n"
        "b,2,2.5,2026-02-14,false,ok,2\n"
        "c,3,3.0,2026-03-31,true,ok,x\n"
    )
    parsed = parse_csv(_to_bytes(text), filename="types.csv")
    assert parsed.dtypes["id"] == "string"
    assert parsed.dtypes["count"] == "integer"
    assert parsed.dtypes["ratio"] == "float"
    assert parsed.dtypes["when"] == "date"
    assert parsed.dtypes["flag"] == "boolean"
    assert parsed.dtypes["note"] == "string"
    assert parsed.dtypes["weird"] == "mixed"
    assert any("mixed value types" in note for note in parsed.quality_notes)


def test_numeric_flag_column_named_is_x_is_boolean() -> None:
    text = "is_active,score\n1,10\n0,20\n1,30\n"
    parsed = parse_csv(_to_bytes(text), filename="flags.csv")
    assert parsed.dtypes["is_active"] == "boolean"


def test_numeric_0_1_column_without_hint_stays_integer() -> None:
    text = "outcome,score\n1,10\n0,20\n1,30\n"
    parsed = parse_csv(_to_bytes(text), filename="plain.csv")
    assert parsed.dtypes["outcome"] == "integer"


def test_year_month_strings_are_not_dates() -> None:
    text = "month,value\n2026-01,5\n2026-02,6\n2026-03,7\n"
    parsed = parse_csv(_to_bytes(text), filename="months.csv")
    assert parsed.dtypes["month"] == "string"


def test_date_column_with_consistent_slash_format() -> None:
    text = "when,v\n05/02/2026,1\n23/03/2026,2\n01/04/2026,3\n"
    parsed = parse_csv(_to_bytes(text), filename="dates.csv")
    assert parsed.dtypes["when"] == "date"


def test_inconsistent_date_formats_flagged_as_suspicious() -> None:
    text = "when,v\n2026-01-05,1\n05/02/2026,2\n2026-03-31,3\n04/04/2026,4\n"
    parsed = parse_csv(_to_bytes(text), filename="mixeddates.csv")
    assert parsed.dtypes["when"] == "string"
    assert any("inconsistent formats" in note for note in parsed.quality_notes)


def test_empty_column_detected() -> None:
    text = "a,b,c\n1,,2\n3,,4\n"
    parsed = parse_csv(_to_bytes(text), filename="gap.csv")
    assert parsed.dtypes["b"] == "empty"


# --------------------------------------------------------------------------- #
# Quality notes
# ---------------------------------------------------------------------------


def test_missing_values_noted_with_percentages() -> None:
    text = "a,b,c\n1,,x\n2,,y\n3,9,z\n4,,w\n"
    parsed = parse_csv(_to_bytes(text), filename="missing.csv")
    assert any("of all cells are empty" in note for note in parsed.quality_notes)
    assert any("Column 'b' has 3 missing values" in note for note in parsed.quality_notes)


def test_duplicate_rows_noted() -> None:
    text = "a,b\n1,2\n1,2\n1,2\n3,4\n"
    parsed = parse_csv(_to_bytes(text), filename="dupes.csv")
    assert parsed.row_count == 4
    assert any("2 duplicate data rows" in note for note in parsed.quality_notes)


def test_constant_column_noted() -> None:
    text = "a,b\n1,x\n2,x\n3,x\n"
    parsed = parse_csv(_to_bytes(text), filename="const.csv")
    assert parsed.dtypes["b"] == "string"
    assert any("constant" in note and "'x'" in note for note in parsed.quality_notes)


def test_duplicate_and_empty_header_cells_handled() -> None:
    text = "name,name,\nalice,1,x\nbob,2,y\n"
    parsed = parse_csv(_to_bytes(text), filename="hdr.csv")
    assert parsed.columns == ["name", "name_2", "column_3"]
    assert any("renamed" in note for note in parsed.quality_notes)
    assert any("auto-named" in note for note in parsed.quality_notes)


def test_records_extension_holds_all_rows() -> None:
    parsed = parse_csv(_to_bytes(BASIC), filename="people.csv")
    assert len(parsed.records) == 3
    assert parsed.records[2] == ["carol", "41", "88.25"]


def test_isinstance_of_parseddataset() -> None:
    assert isinstance(parse_csv(_to_bytes(BASIC)), ParsedDataset)
