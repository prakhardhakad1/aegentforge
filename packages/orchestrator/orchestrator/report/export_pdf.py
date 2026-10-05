"""PDF export for AgentForge reports (Agent 6).

    export_pdf(source, out_path) -> Path

``source`` may be a report dict, a :class:`Report` model, or an already
rendered Markdown string. Pipeline:

    report -> GitHub-flavored Markdown -> HTML (python-markdown, tables ext)
           -> minimal block parse -> fpdf2 PDF

fpdf2 is pure Python and works on Windows (no weasyprint, no native deps).
The renderer produces: a cover block (title, mission, meta), headings,
paragraphs, bullet lists, blockquotes, bordered tables with header fill,
embedded chart images when the artifact file exists on disk, horizontal
rules, and page-number footers.

Text is sanitized to latin-1 (fpdf2 core fonts) with a mapping for common
typographic characters; anything exotic degrades to '?' instead of crashing.
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import markdown
from fpdf import FPDF
from fpdf.fonts import FontFace

from .render_markdown import render_markdown

__all__ = ["export_pdf"]

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp")
_MARGIN = 16.0
_ACCENT = (37, 99, 235)      # blue rules / cover accents
_DARK = (24, 30, 42)         # heading ink
_GRAY = (110, 118, 129)      # meta text

_UNICODE_MAP = {
    "\u2014": "-", "\u2013": "-", "\u2022": "-", "\u2192": "->",
    "\u2265": ">=", "\u2264": "<=", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00a0": " ",
    "\u00d7": "x", "\u2713": "ok", "\u20ac": "EUR", "\u2705": "ok",
}


def _latin(text: str) -> str:
    """Map common unicode punctuation then force latin-1 (fpdf2 core fonts)."""
    for src, dst in _UNICODE_MAP.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


# ---------------------------------------------------------------------------
# Markdown -> HTML -> blocks
# ---------------------------------------------------------------------------


class _Block:
    """One renderable block: (kind, payload...)."""

    __slots__ = ("kind", "args")

    def __init__(self, kind: str, *args: Any) -> None:
        self.kind = kind
        self.args = args

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"_Block({self.kind!r}, {self.args!r})"


class _HTMLBlockParser(HTMLParser):
    """Parse the small HTML subset python-markdown emits into blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._buf: list[str] = []
        self._mode: str | None = None          # p|h|bq|li|pre|cell
        self._heading_level = 0
        self._list_items: list[str] = []
        self._table: dict[str, Any] | None = None
        self._row: list[str] | None = None
        self._in_head = False

    # -- helpers ----------------------------------------------------------
    def _flush_paragraph(self) -> None:
        text = "".join(self._buf).strip()
        self._buf = []
        if text:
            self.blocks.append(_Block("p", text))

    def _flush_block(self) -> None:
        text = "".join(self._buf).strip()
        self._buf = []
        if self._mode == "h":
            level = min(max(self._heading_level, 1), 3)
            if text:
                self.blocks.append(_Block(f"h{level}", text))
        elif self._mode == "bq":
            if text:
                self.blocks.append(_Block("blockquote", text))
        elif self._mode == "pre":
            if text:
                self.blocks.append(_Block("pre", text))
        elif self._mode == "li":
            if text:
                self._list_items.append(text)
        elif self._mode == "p":
            if text:
                self.blocks.append(_Block("p", text))
        self._mode = None

    # -- parser hooks ------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {k: (v or "") for k, v in attrs}
        if tag in ("h1", "h2", "h3"):
            self._flush_paragraph()
            self._mode = "h"
            self._heading_level = int(tag[1])
        elif tag == "p":
            if self._mode not in ("cell",):
                self._flush_paragraph()
                self._mode = "p"
        elif tag == "blockquote":
            self._flush_paragraph()
            self._mode = "bq"
        elif tag == "pre":
            self._flush_paragraph()
            self._mode = "pre"
        elif tag in ("ul", "ol"):
            self._flush_paragraph()
            self._list_items = []
        elif tag == "li":
            self._flush_paragraph()
            self._mode = "li"
        elif tag == "table":
            self._flush_paragraph()
            self._table = {"headers": [], "rows": [], "in_head": False}
        elif tag == "thead":
            if self._table is not None:
                self._table["in_head"] = True
        elif tag == "tbody":
            if self._table is not None:
                self._table["in_head"] = False
        elif tag == "tr":
            if self._table is not None:
                self._row = []
        elif tag in ("th", "td"):
            self._buf = []
            self._mode = "cell"
        elif tag == "br":
            self._buf.append("\n")
        elif tag == "hr":
            self._flush_paragraph()
            self.blocks.append(_Block("hr"))
        elif tag == "img":
            self._flush_paragraph()
            self.blocks.append(_Block("img", attributes.get("src", ""), attributes.get("alt", "")))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2", "h3", "p", "blockquote", "pre", "li"):
            if self._mode == "cell" and tag == "p":
                return  # <p> inside a table cell: keep collecting
            self._flush_block()
        elif tag in ("ul", "ol"):
            if self._list_items:
                self.blocks.append(_Block("ul", list(self._list_items)))
            self._list_items = []
        elif tag in ("th", "td"):
            cell_text = "".join(self._buf).strip()
            self._buf = []
            self._mode = None
            if self._table is not None and self._row is not None:
                self._row.append(cell_text)
        elif tag == "tr":
            if self._table is not None and self._row is not None:
                if self._table["in_head"]:
                    # Head row REPLACES (headers stays list[str], not list-of-rows);
                    # first head row wins if the source emits more than one.
                    if not self._table["headers"]:
                        self._table["headers"] = list(self._row)
                else:
                    self._table["rows"].append(self._row)
                self._row = None
        elif tag == "table":
            if self._table is not None:
                headers = self._table["headers"]
                rows = self._table["rows"]
                if not headers and rows:
                    headers = rows.pop(0)
                if headers or rows:
                    self.blocks.append(_Block("table", headers, rows))
                self._table = None

    def handle_data(self, data: str) -> None:
        if self._mode is not None:
            self._buf.append(data)


def _markdown_to_blocks(markdown_text: str) -> list[_Block]:
    """Convert GFM markdown to renderable blocks via python-markdown."""
    html = markdown.markdown(
        markdown_text or "",
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )
    parser = _HTMLBlockParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 — malformed HTML must not kill export
        fallback = [line.strip() for line in (markdown_text or "").splitlines() if line.strip()]
        return [_Block("p", _latin(line)) for line in fallback] or [_Block("p", "(empty report)")]
    blocks = parser.blocks
    if not blocks:
        blocks = [_Block("p", "(empty report)")]
    return blocks


def _cover_from_report(report: "dict[str, Any] | None") -> dict[str, str]:
    """Cover fields from a report dict when one was given."""
    if not isinstance(report, dict):
        return {}
    cover: dict[str, str] = {}
    if report.get("title"):
        cover["title"] = str(report["title"])
    if report.get("mission"):
        cover["mission"] = str(report["mission"])
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    bits = []
    if meta.get("style_profile") or report.get("style"):
        bits.append(f"Style: {meta.get('style_profile') or report.get('style')}")
    if meta.get("run_status"):
        bits.append(f"Run status: {meta['run_status']}")
    if meta.get("generated_at"):
        bits.append(f"Generated: {str(meta['generated_at'])[:19].replace('T', ' ')} UTC")
    if bits:
        cover["meta"] = "  |  ".join(bits)
    return cover


def _cover_from_blocks(blocks: list[_Block]) -> dict[str, str]:
    """Fallback cover: first heading is the title, first blockquote the mission."""
    cover: dict[str, str] = {}
    for block in blocks:
        if block.kind == "h1" and "title" not in cover:
            cover["title"] = str(block.args[0])
        elif block.kind == "blockquote" and "mission" not in cover:
            cover["mission"] = re.sub(r"\s+", " ", str(block.args[0]))
    return cover


# ---------------------------------------------------------------------------
# fpdf2 renderer
# ---------------------------------------------------------------------------


class _ReportPDF(FPDF):
    """FPDF subclass with an AgentForge footer (page numbers)."""

    def footer(self) -> None:
        """Draw the page-number footer on every page."""
        self.set_y(-12)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(*_GRAY)
        self.cell(0, 8, _latin(f"AgentForge report  -  page {self.page_no()}"), align="C")
        self.set_text_color(0, 0, 0)


def _cell_text(value: Any) -> str:
    """Coerce any table cell (str, list, dict, None, number) to plain text.

    This is the primary defense against the historical ``_write_table`` crash
    on table-heavy reports: markdown table cells always arrive as strings from
    the HTML parser, but malformed or hand-built sources may carry anything.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(_cell_text(item) for item in value).strip()
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if v is not None).strip()
    return str(value)


def _normalize_table(
    headers: list[Any], rows: list[list[Any]]
) -> tuple[list[str], list[list[str]]]:
    """Coerce cells to str and square the table to a single column count.

    Pads short rows and truncates long rows so fpdf2 never sees a ragged
    table; rows that are empty after normalization are dropped.
    """
    header_cells = [_cell_text(h) for h in headers]
    normalized_rows: list[list[str]] = []
    for row in rows:
        if isinstance(row, (str, bytes)):  # a whole row collapsed to text
            row = [row]
        if not isinstance(row, (list, tuple)):
            row = [row]
        cells = [_cell_text(c) for c in row]
        if any(cells):
            normalized_rows.append(cells)
    column_count = len(header_cells) or (
        max((len(r) for r in normalized_rows), default=0)
    )
    if column_count == 0:
        return [], []
    header_cells = (header_cells + [""] * column_count)[:column_count]
    squared: list[list[str]] = []
    for cells in normalized_rows:
        squared.append((cells + [""] * column_count)[:column_count])
    return header_cells, squared


def _col_widths(headers: list[str]) -> tuple[float, ...] | None:
    """Column width hints for the known AgentForge tables.

    Returns ``None`` (fpdf2 auto-layout) unless ``headers`` matches a known
    table shape exactly — a wrong-length hint would raise inside fpdf2.
    """
    try:
        keys = [str(h).strip().lower() for h in headers]
    except Exception:  # noqa: BLE001 — hints are optional; never fatal
        return None
    hints: tuple[tuple[str, ...], tuple[float, ...]] | None = None
    if "prediction" in keys and "confidence" in keys:
        hints = (("prediction", "confidence", "basis"), (0.06, 0.47, 0.13, 0.34))
    elif "priority" in keys and "effort" in keys:
        hints = (
            ("priority", "recommendation", "action", "expected impact", "effort"),
            (0.09, 0.21, 0.35, 0.27, 0.08),
        )
    elif keys == ["label", "x", "y"]:
        hints = (("label", "x", "y"), (0.40, 0.30, 0.30))
    if hints is None:
        return None
    marker, widths = hints
    if len(keys) != len(widths) or not all(m in keys for m in marker):
        return None
    return widths


def _write_cover(pdf: _ReportPDF, cover: dict[str, str]) -> None:
    """Cover block: title, accent rule, mission, meta line."""
    pdf.ln(6)
    pdf.set_font("helvetica", "B", 19)
    pdf.set_text_color(*_DARK)
    pdf.multi_cell(pdf.epw, 9, _latin(cover.get("title", "AgentForge Report")))
    pdf.ln(2)
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + 60, pdf.get_y())
    pdf.ln(6)
    if cover.get("mission"):
        pdf.set_font("helvetica", "I", 10.5)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(pdf.epw, 5.5, _latin(cover["mission"]))
        pdf.ln(3)
    if cover.get("meta"):
        pdf.set_font("helvetica", "", 8.5)
        pdf.set_text_color(*_GRAY)
        pdf.multi_cell(pdf.epw, 4.5, _latin(cover["meta"]))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)


def _write_heading(pdf: _ReportPDF, level: int, text: str) -> None:
    """Write one heading with size and spacing by level."""
    sizes = {1: 15.5, 2: 12.5, 3: 11}
    pdf.ln(2.5)
    pdf.set_font("helvetica", "B", sizes.get(level, 11))
    pdf.set_text_color(*_DARK)
    pdf.multi_cell(pdf.epw, sizes.get(level, 11) * 0.62, _latin(text))
    if level <= 2:
        pdf.ln(1)
        pdf.set_draw_color(210, 214, 220)
        pdf.set_line_width(0.3)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pdf.epw, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(0, 0, 0)


def _write_paragraph(pdf: _ReportPDF, text: str) -> None:
    """Write a body paragraph."""
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(35, 35, 35)
    pdf.multi_cell(pdf.epw, 5, _latin(text))
    pdf.ln(1.5)
    pdf.set_text_color(0, 0, 0)


def _write_blockquote(pdf: _ReportPDF, text: str) -> None:
    """Write an indented italic blockquote with a left accent bar."""
    x = pdf.l_margin
    pdf.set_x(x + 3)
    pdf.set_font("helvetica", "I", 9.5)
    pdf.set_text_color(60, 60, 60)
    y_before = pdf.get_y()
    pdf.multi_cell(pdf.epw - 6, 5, _latin(text))
    y_after = pdf.get_y()
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(x + 1.2, y_before, x + 1.2, y_after)
    pdf.set_x(x)
    pdf.ln(1.5)
    pdf.set_text_color(0, 0, 0)


def _write_bullets(pdf: _ReportPDF, items: list[str]) -> None:
    """Write a bullet list."""
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(35, 35, 35)
    for item in items:
        pdf.set_x(pdf.l_margin + 2)
        pdf.multi_cell(pdf.epw - 4, 5, _latin(f"- {item}"))
        pdf.ln(0.4)
    pdf.ln(1)
    pdf.set_text_color(0, 0, 0)


def _write_table(pdf: _ReportPDF, headers: list[Any], rows: list[list[Any]]) -> None:
    """Write a bordered table with a filled header row.

    All cells are coerced to plain text and the table is squared to one column
    count first, so table-heavy reports can never crash this path (the
    historical integration bug). If fpdf2 still fails for any reason, the
    content is rendered as plain paragraphs instead.
    """
    header_cells, squared_rows = _normalize_table(list(headers or []), list(rows or []))
    if not header_cells and not squared_rows:
        return
    pdf.set_font("helvetica", "", 8.2)
    pdf.set_text_color(35, 35, 35)
    try:
        with pdf.table(
            col_widths=_col_widths(header_cells),
            text_align="LEFT",
            line_height=4.4,
            padding=1.2,
            headings_style=FontFace(emphasis="BOLD", fill_color=(238, 241, 245)),
            borders_layout="ALL",
        ) as table:
            if header_cells:
                header_row = table.row()
                for header in header_cells:
                    header_row.cell(_latin(header))
            for data_row in squared_rows:
                row = table.row()
                for cell_value in data_row:
                    row.cell(_latin(cell_value))
    except Exception as exc:  # noqa: BLE001 — render the content as text instead
        flat = [c for c in header_cells if c]
        for data_row in squared_rows:
            flat.extend(c for c in data_row if c)
        pdf.multi_cell(pdf.epw, 5, _latin(" | ".join(flat)))
        pdf.ln(1)
        if os.environ.get("AGENTFORGE_DEBUG"):
            raise RuntimeError(f"fpdf2 table rendering failed: {exc}") from exc
    pdf.ln(2.5)
    pdf.set_text_color(0, 0, 0)


def _write_image(pdf: _ReportPDF, src: str, alt: str) -> None:
    """Embed a chart image when the file exists; else a labeled placeholder."""
    resolved = None
    if src:
        for candidate in (src, os.path.join(os.getcwd(), src)):
            try:
                if os.path.isfile(candidate):
                    resolved = candidate
                    break
            except OSError:
                continue
    if resolved and resolved.lower().endswith(_IMAGE_SUFFIXES):
        try:
            pdf.image(resolved, w=pdf.epw * 0.9)
            pdf.ln(2)
            return
        except Exception:  # noqa: BLE001 — unsupported raster falls through
            pass
    pdf.set_font("helvetica", "I", 8.5)
    pdf.set_text_color(*_GRAY)
    pdf.multi_cell(pdf.epw, 5, _latin(f"[chart image unavailable: {alt or src}]"))
    pdf.ln(1.5)
    pdf.set_text_color(0, 0, 0)


def _render_blocks(pdf: _ReportPDF, blocks: list[_Block], cover: dict[str, str]) -> None:
    """Render all blocks, skipping the first h1 (already on the cover)."""
    seen_first_h1 = False
    for block in blocks:
        if block.kind == "h1":
            if not seen_first_h1:
                seen_first_h1 = True
                continue
            _write_heading(pdf, 2, str(block.args[0]))
        elif block.kind == "h2":
            _write_heading(pdf, 2, str(block.args[0]))
        elif block.kind == "h3":
            _write_heading(pdf, 3, str(block.args[0]))
        elif block.kind == "p":
            _write_paragraph(pdf, str(block.args[0]))
        elif block.kind == "blockquote":
            _write_blockquote(pdf, str(block.args[0]))
        elif block.kind == "ul":
            _write_bullets(pdf, [str(i) for i in block.args[0]])
        elif block.kind == "table":
            _write_table(pdf, list(block.args[0]), list(block.args[1]))
        elif block.kind == "img":
            _write_image(pdf, str(block.args[0]), str(block.args[1]))
        elif block.kind == "pre":
            pdf.set_font("courier", "", 8.5)
            pdf.multi_cell(pdf.epw, 4.5, _latin(str(block.args[0])))
            pdf.ln(1.5)
            pdf.set_font("helvetica", "", 9.5)
        elif block.kind == "hr":
            pdf.ln(1.5)
            pdf.set_draw_color(210, 214, 220)
            pdf.set_line_width(0.3)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + pdf.epw, pdf.get_y())
            pdf.ln(2.5)
    # Cover fallback for markdown-only sources that had no heading at all.
    if "title" not in cover:
        pass  # _cover_from_blocks already extracted what it could


def export_pdf(source: "dict[str, Any] | str | object", out_path: "str | Path") -> Path:
    """Export a report (dict/Report/markdown string) to a PDF file.

    Args:
        source: A report dict, a :class:`Report` model, or a Markdown string.
        out_path: Destination file path (parent dirs are created).

    Returns:
        The resolved :class:`~pathlib.Path` of the written PDF.

    Raises:
        ValueError: if ``source`` is neither report-like nor a string.
        RuntimeError: if PDF rendering or writing fails.
    """
    report_dict: dict[str, Any] | None = None
    if isinstance(source, str):
        markdown_text = source
    elif isinstance(source, dict):
        report_dict = source
        markdown_text = render_markdown(source)
    elif hasattr(source, "model_dump"):  # Report model (avoid importing models here)
        report_dict = source.model_dump(mode="json")
        markdown_text = render_markdown(report_dict)
    else:
        raise ValueError(
            "export_pdf source must be a report dict, a Report model, or a "
            f"markdown string; got {type(source).__name__}"
        )

    out = Path(out_path)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)

    blocks = _markdown_to_blocks(markdown_text)
    cover = _cover_from_report(report_dict) or _cover_from_blocks(blocks)
    cover.setdefault("meta", "Generated by AgentForge (orchestrator.report)")

    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    _write_cover(pdf, cover)
    try:
        _render_blocks(pdf, blocks, cover)
        pdf_bytes = bytes(pdf.output())
    except Exception as exc:  # noqa: BLE001 — surface a clear error
        raise RuntimeError(f"PDF rendering failed for {out}: {exc}") from exc
    try:
        out.write_bytes(pdf_bytes)
    except OSError as exc:
        raise RuntimeError(f"Could not write PDF to {out}: {exc}") from exc
    return out
