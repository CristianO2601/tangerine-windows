"""Document conversions: Word, Excel, PowerPoint, CSV, RTF, Markdown, ODT, EPUB.

Readers turn each source into plain text or table rows; writers render those to
TXT/PDF/CSV/XLSX/HTML. For JPG/PNG targets the document is first laid out as a
temporary PDF (through the same reportlab pipelines) and then rasterized by the
shared pypdfium2 renderer in ``engines`` at 300 dpi.
"""

from __future__ import annotations

import csv as _csv
import html as _html
import posixpath
import re
import shutil
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import i18n, render
from .engines import (
    Ctx, EngineError, _open_pdf_document, _pdf_mono_font, _render_pdf_pages,
    _unique, text_to_pdf, verify_writable,
)


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _iter_docx_blocks(document):
    """Yield paragraphs and tables from a document in body order."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _docx_table_rows(table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        rows.append([" ".join(cell.text.split()) for cell in row.cells])
    return rows


def _open_docx(path: Path):
    try:
        import docx
    except ImportError as exc:
        raise EngineError(i18n.tr("err.doc_package_docx")) from exc
    try:
        return docx.Document(str(path))
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_open")) from exc


def _read_docx_text(path: Path) -> str:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = _open_docx(path)
    parts: list[str] = []
    for block in _iter_docx_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                parts.append(text)
        elif isinstance(block, Table):
            for row in _docx_table_rows(block):
                parts.append("\t".join(row))
    return "\n".join(parts)


def _read_xlsx_rows(path: Path, ctx: Ctx | None = None) -> list[list[str]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise EngineError(i18n.tr("err.doc_package_xlsx")) from exc
    try:
        workbook = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_spreadsheet")) from exc
    rows: list[list[str]] = []
    try:
        sheet = workbook.active
        for index, values in enumerate(sheet.iter_rows(values_only=True)):
            if ctx is not None and index % 500 == 0 and ctx.cancelled():
                raise EngineError(i18n.tr("err.cancelled"))
            rows.append(["" if value is None else str(value) for value in values])
    except EngineError:
        raise
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_spreadsheet")) from exc
    finally:
        try:
            workbook.close()
        except Exception:
            pass
    return rows


def _read_csv_rows(path: Path) -> list[list[str]]:
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            return [list(row) for row in _csv.reader(handle)]
    except OSError as exc:
        raise EngineError(i18n.tr("err.doc_file")) from exc


def _open_presentation(path: Path):
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise EngineError(i18n.tr("err.doc_package_pptx")) from exc
    try:
        return Presentation(str(path))
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_presentation")) from exc


def _slide_text(slide) -> tuple[str, list[str]]:
    """Return (title, bullet lines) for one slide; the title is kept apart."""
    title_shape = slide.shapes.title
    title_element = title_shape.element if title_shape is not None else None
    title = ""
    bullets: list[str] = []
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        if title_element is not None and shape.element is title_element:
            title = " ".join(shape.text_frame.text.split())
            continue
        for paragraph in shape.text_frame.paragraphs:
            text = " ".join(paragraph.text.split())
            if text:
                bullets.append(text)
    return title, bullets


def _read_pptx_text(path: Path) -> str:
    presentation = _open_presentation(path)
    parts: list[str] = []
    for number, slide in enumerate(presentation.slides, start=1):
        title, bullets = _slide_text(slide)
        parts.append(f"Slide {number}")
        if title:
            parts.append(title)
        parts.extend(bullets)
        parts.append("")
    return "\n".join(parts).strip()


def _read_pptx_slides(path: Path) -> list[tuple[str, list[str]]]:
    """(title, bullets) per slide, for the faithful-ish HTML/PDF render."""
    presentation = _open_presentation(path)
    return [_slide_text(slide) for slide in presentation.slides]


def _read_rtf_text(path: Path) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError as exc:
        raise EngineError(i18n.tr("err.doc_package_rtf")) from exc
    try:
        source = path.read_text("utf-8", errors="replace")
        return rtf_to_text(source)
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_open")) from exc


def _markdown_library():
    try:
        import markdown as markdown_library
    except ImportError as exc:
        raise EngineError(i18n.tr("err.doc_package_md")) from exc
    return markdown_library


def _render_markdown(source: str) -> str:
    library = _markdown_library()
    try:
        return library.markdown(source, extensions=["extra", "sane_lists"])
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_markdown")) from exc


def _read_markdown_text(path: Path) -> str:
    source = path.read_text("utf-8", errors="replace")
    return _html_to_text(_render_markdown(source))


def _read_odt_text(path: Path) -> str:
    try:
        from odf import teletype
        from odf.opendocument import load
        from odf.text import P
    except ImportError as exc:
        raise EngineError(i18n.tr("err.doc_package_odt")) from exc
    try:
        document = load(str(path))
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_open")) from exc
    return "\n".join(
        teletype.extractText(paragraph)
        for paragraph in document.getElementsByType(P)
    )


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _epub_opf_path(archive: zipfile.ZipFile) -> str:
    try:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
    except (KeyError, ElementTree.ParseError) as exc:
        raise EngineError(i18n.tr("err.doc_epub")) from exc
    for element in container.iter():
        if _local_name(element.tag) == "rootfile":
            full_path = element.get("full-path")
            if full_path:
                return full_path.replace("\\", "/")
    raise EngineError(i18n.tr("err.doc_epub"))


def _read_epub_text(path: Path, ctx: Ctx | None = None) -> str:
    chapters: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            opf_path = _epub_opf_path(archive)
            package = ElementTree.fromstring(archive.read(opf_path))
            manifest = {
                element.get("id"): element.get("href")
                for element in package.iter()
                if _local_name(element.tag) == "item"
            }
            base = posixpath.dirname(opf_path)
            for reference in package.iter():
                if _local_name(reference.tag) != "itemref":
                    continue
                if ctx is not None and ctx.cancelled():
                    raise EngineError(i18n.tr("err.cancelled"))
                href = manifest.get(reference.get("idref", ""))
                if not href:
                    continue
                target = posixpath.normpath(posixpath.join(base, href.split("#", 1)[0]))
                try:
                    data = archive.read(target)
                except KeyError:
                    continue
                chapters.append(_html_to_text(data.decode("utf-8", errors="replace")))
    except EngineError:
        raise
    except Exception as exc:
        raise EngineError(i18n.tr("err.doc_epub")) from exc
    return "\n\n".join(chunk for chunk in chapters if chunk.strip()).strip()


def _read_text(path: Path, ctx: Ctx | None = None) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        return _read_docx_text(path)
    if ext == ".pptx":
        return _read_pptx_text(path)
    if ext == ".rtf":
        return _read_rtf_text(path)
    if ext == ".odt":
        return _read_odt_text(path)
    if ext == ".md":
        return _read_markdown_text(path)
    if ext == ".epub":
        return _read_epub_text(path, ctx)
    raise EngineError(i18n.tr("err.doc_unsupported"))


def _read_rows(path: Path, ctx: Ctx | None = None) -> list[list[str]]:
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return _read_xlsx_rows(path, ctx)
    if ext == ".csv":
        return _read_csv_rows(path)
    raise EngineError(i18n.tr("err.doc_unsupported"))


# ---------------------------------------------------------------------------
# HTML stripping (shared by Markdown, EPUB)
# ---------------------------------------------------------------------------

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table",
    "td", "th", "tr", "ul",
}


class _HtmlToText(HTMLParser):
    """Strip HTML to readable plain text, keeping block-level line breaks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        lines: list[str] = []
        for raw in "".join(self._parts).splitlines():
            line = re.sub(r"\s+", " ", raw).strip()
            if line:
                lines.append(line)
            elif lines and lines[-1]:
                lines.append("")
        return "\n".join(lines).strip()


def _html_to_text(markup: str) -> str:
    parser = _HtmlToText()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        return ""
    return parser.text()


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _write_text(text: str, out_path: Path, ctx: Ctx) -> None:
    if not text.strip():
        raise EngineError(i18n.tr("err.doc_no_text"))
    out_path.write_text(text.rstrip() + "\n", "utf-8")
    ctx.progress(1.0)


def _write_csv(rows: list[list[str]], out_path: Path) -> None:
    with open(out_path, "w", encoding="utf-8-sig", newline="") as handle:
        _csv.writer(handle).writerows(rows)


def _write_xlsx(rows: list[list[str]], out_path: Path) -> None:
    try:
        import openpyxl
    except ImportError as exc:
        raise EngineError(i18n.tr("err.doc_package_xlsx_write")) from exc
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(str(out_path))


def _rows_to_text(rows: list[list[str]]) -> str:
    lines: list[str] = []
    for row in rows:
        cells = list(row)
        while cells and not cells[-1]:
            cells.pop()
        lines.append("\t".join(cells))
    return "\n".join(lines)


def _rows_to_pdf(rows: list[list[str]], out_path: Path, ctx: Ctx) -> None:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    if ctx.cancelled():
        raise EngineError(i18n.tr("err.cancelled"))
    if not rows:
        raise EngineError(i18n.tr("err.doc_no_rows"))
    sample = "\n".join("\t".join(row) for row in rows)
    font_name = "Courier"
    bold_name = "Courier-Bold"
    try:
        sample.encode("latin-1")
    except UnicodeEncodeError:
        font_name = bold_name = _pdf_mono_font(sample)
    body_style = ParagraphStyle("TangerineCell", fontName=font_name, fontSize=9.0, leading=11.0)
    head_style = ParagraphStyle("TangerineHead", fontName=bold_name, fontSize=9.0, leading=11.0)
    data = []
    for index, row in enumerate(rows):
        style = head_style if index == 0 else body_style
        data.append([
            Paragraph(_html.escape(cell, quote=False) or " ", style)
            for cell in row
        ])
    columns = max(len(row) for row in rows) or 1
    options = render.print_options()
    page_width, page_height = render.page_size_points(options["page_size"])
    left, top, right, bottom = render.margins_to_points(options["margins_mm"])
    column_width = (page_width - left - right) / columns
    table = Table(data, colWidths=[column_width] * columns, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BBBBBB")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    def check_cancelled(canvas, document) -> None:
        if ctx.cancelled():
            raise EngineError(i18n.tr("err.cancelled"))

    document = SimpleDocTemplate(
        str(out_path), pagesize=(page_width, page_height),
        leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
        title=out_path.stem,
    )
    try:
        document.build([table], onFirstPage=check_cancelled, onLaterPages=check_cancelled)
    except EngineError:
        out_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        out_path.unlink(missing_ok=True)
        raise EngineError(i18n.tr("err.doc_pdf_failed")) from exc
    render.postprocess_pdf(
        out_path, title=out_path.stem,
        page_numbers=bool(options.get("page_numbers", True)),
    )
    ctx.progress(1.0)


def _markdown_to_html(path: Path, out_path: Path, ctx: Ctx) -> None:
    source = path.read_text("utf-8", errors="replace")
    out_path.write_text(render.markdown_to_html(source, path.stem), "utf-8")
    ctx.progress(1.0)


# ---------------------------------------------------------------------------
# Object documents (Word / PowerPoint) to PDF
# ---------------------------------------------------------------------------

class _TextFlow:
    """A minimal flowing-text canvas: wrapping, page breaks, mono fallbacks."""

    def __init__(
        self, out_path: Path, ctx: Ctx,
        options: dict[str, Any] | None = None,
    ) -> None:
        from reportlab.pdfgen import canvas as pdf_canvas

        self._ctx = ctx
        self._out_path = out_path
        options = options or render.print_options()
        self._page_numbers = bool(options.get("page_numbers", True))
        self.page_width, self.page_height = render.page_size_points(options["page_size"])
        left, top, right, bottom = render.margins_to_points(options["margins_mm"])
        self.left_margin = left
        self.right_margin = right
        self.top_margin = top
        self.bottom_margin = bottom
        self._pdf = pdf_canvas.Canvas(
            str(out_path), pagesize=(self.page_width, self.page_height))
        self._y = self.page_height - self.top_margin
        self._finished = False

    def _font_for(self, text: str, bold: bool) -> str:
        try:
            text.encode("latin-1")
            return "Courier-Bold" if bold else "Courier"
        except UnicodeEncodeError:
            return _pdf_mono_font(text)

    def _wrapped(self, text: str, font: str, size: float, indent: float) -> list[str]:
        from reportlab.pdfbase import pdfmetrics

        available = self.page_width - self.left_margin - self.right_margin - indent
        char_width = pdfmetrics.stringWidth("M", font, size)
        max_chars = max(10, int(available / char_width)) if char_width else 84
        lines: list[str] = []
        for raw_line in text.splitlines() or [""]:
            line = raw_line.replace("\t", "    ").rstrip()
            while len(line) > max_chars:
                lines.append(line[:max_chars])
                line = line[max_chars:]
            lines.append(line)
        return lines

    def paragraph(
        self, text: str, size: float = 10.5, bold: bool = False,
        indent: float = 0.0, space_before: float = 0.0, space_after: float = 0.0,
        color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        if self._ctx.cancelled():
            self.discard()
            raise EngineError(i18n.tr("err.cancelled"))
        if not text:
            return
        leading = size * 1.35
        font = self._font_for(text, bold)
        self._y -= space_before
        for line in self._wrapped(text, font, size, indent):
            if self._y - leading < self.bottom_margin:
                self._pdf.showPage()
                self._y = self.page_height - self.top_margin
            self._pdf.setFillColorRGB(*color)
            self._pdf.setFont(font, size)
            self._pdf.drawString(self.left_margin + indent, self._y - size, line)
            self._y -= leading
        self._y -= space_after

    def page_break(self) -> None:
        self._pdf.showPage()
        self._y = self.page_height - self.top_margin

    def finish(self) -> None:
        self._pdf.save()
        self._finished = True
        render.postprocess_pdf(
            self._out_path, title=self._out_path.stem,
            page_numbers=self._page_numbers,
        )

    def discard(self) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            self._pdf.save()
        except Exception:
            pass
        try:
            self._out_path.unlink(missing_ok=True)
        except OSError:
            pass


def _docx_paragraph_style(paragraph) -> tuple[float, bool, float, float, float]:
    """(size, bold, indent, space_before, space_after) for one paragraph."""
    style = (getattr(paragraph.style, "name", "") or "").lower()
    if style.startswith("title"):
        return 20.0, True, 0.0, 6.0, 10.0
    match = re.match(r"heading (\d+)", style)
    if match:
        level = int(match.group(1))
        size = {1: 16.0, 2: 14.0, 3: 12.5, 4: 11.5}.get(level, 11.0)
        return size, True, 0.0, 12.0, 4.0
    indent = 18.0 if "list" in style else 0.0
    bold = any(run.bold for run in paragraph.runs if run.text.strip())
    return 10.5, bold, indent, 0.0, 4.0


def _docx_to_pdf(path: Path, out_path: Path, ctx: Ctx) -> None:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = _open_docx(path)
    flow = _TextFlow(out_path, ctx)
    try:
        blocks = list(_iter_docx_blocks(document))
        total = max(len(blocks), 1)
        for index, block in enumerate(blocks):
            if ctx.cancelled():
                raise EngineError(i18n.tr("err.cancelled"))
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if text:
                    size, bold, indent, before, after = _docx_paragraph_style(block)
                    flow.paragraph(
                        text, size=size, bold=bold, indent=indent,
                        space_before=before, space_after=after,
                    )
            elif isinstance(block, Table):
                for row in _docx_table_rows(block):
                    flow.paragraph("\t".join(row), size=9.0, indent=12.0, space_after=1.0)
                flow.paragraph("", space_after=6.0)
            ctx.progress((index + 1) / total * 0.95)
        flow.finish()
        ctx.progress(1.0)
    except Exception:
        flow.discard()
        raise


def _pptx_to_pdf(path: Path, out_path: Path, ctx: Ctx) -> None:
    presentation = _open_presentation(path)
    flow = _TextFlow(out_path, ctx)
    try:
        slides = list(presentation.slides)
        if not slides:
            raise EngineError(i18n.tr("err.doc_no_slides"))
        total = len(slides)
        for number, slide in enumerate(slides, start=1):
            if ctx.cancelled():
                raise EngineError(i18n.tr("err.cancelled"))
            if number > 1:
                flow.page_break()
            flow.paragraph(
                f"Slide {number}", size=9.0, space_after=4.0,
                color=(0.42, 0.42, 0.42),
            )
            title, bullets = _slide_text(slide)
            if title:
                flow.paragraph(title, size=16.0, bold=True, space_after=8.0)
            for bullet in bullets:
                flow.paragraph(f"- {bullet}", size=11.0, indent=12.0, space_after=3.0)
            ctx.progress(number / total)
        flow.finish()
        ctx.progress(1.0)
    except Exception:
        flow.discard()
        raise


def _render_pdf(
    path: Path, out_path: Path, ctx: Ctx, *, page_numbers: bool = True,
) -> bool:
    """Faithful HTML render (QtWebEngine); False falls back to legacy writers."""
    ext = path.suffix.lower()
    options = render.print_options()
    try:
        if ext == ".md":
            source = path.read_text("utf-8", errors="replace")
            page = render.markdown_to_html(source, path.stem, options)
        elif ext == ".docx":
            page = render.docx_to_html(path, path.stem, options)
        elif ext == ".xlsx":
            page = render.xlsx_to_html(path, path.stem, options)
        elif ext == ".csv":
            page = render.csv_to_html(path, path.stem, options)
        elif ext == ".rtf":
            page = render.paragraphs_to_html(_read_rtf_text(path), path.stem, options)
        elif ext == ".odt":
            page = render.paragraphs_to_html(_read_odt_text(path), path.stem, options)
        elif ext == ".pptx":
            slides = _read_pptx_slides(path)
            if not slides:
                return False
            page = render.slides_to_html(slides, path.stem, options)
        else:
            return False
        if render.html_to_pdf(
            page, out_path, title=path.stem, options=options,
            page_numbers=page_numbers,
        ):
            ctx.progress(1.0)
            return True
    except Exception:
        return False
    return False


def _write_pdf(
    path: Path, out_path: Path, ctx: Ctx, *, page_numbers: bool = True,
) -> None:
    if _render_pdf(path, out_path, ctx, page_numbers=page_numbers):
        return
    ext = path.suffix.lower()
    if ext == ".docx":
        _docx_to_pdf(path, out_path, ctx)
    elif ext == ".pptx":
        _pptx_to_pdf(path, out_path, ctx)
    elif ext in (".xlsx", ".csv"):
        _rows_to_pdf(_read_rows(path, ctx), out_path, ctx)
    else:
        text = _read_text(path, ctx)
        if not text.strip():
            raise EngineError(i18n.tr("err.doc_no_text"))
        text_to_pdf(text, out_path, ctx, page_numbers=page_numbers)


def _document_to_images(
    path: Path, target: str, ctx: Ctx, reserved: set[Path],
) -> list[Path]:
    tmp_dir = Path(tempfile.mkdtemp(prefix="tangerine_doc_"))
    tmp_pdf = tmp_dir / "document.pdf"
    try:
        _write_pdf(path, tmp_pdf, ctx, page_numbers=False)
        try:
            pdf = _open_pdf_document(tmp_pdf)
        except EngineError as exc:
            raise EngineError(
                i18n.tr("err.doc_image_failed", name=path.name)
            ) from exc
        try:
            return _render_pdf_pages(pdf, path.parent, path, target, ctx, reserved)
        finally:
            try:
                pdf.close()
            except Exception:
                pass
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def convert_document(
    path: Path, target: str, ctx: Ctx, reserved: set[Path],
) -> list[Path]:
    verify_writable(path)
    if ctx.cancelled():
        raise EngineError(i18n.tr("err.cancelled"))
    ext = path.suffix.lower()
    ctx.status(i18n.tr("action.converting_file_to", name=path.name, target=target.upper()))
    if target in ("jpg", "png"):
        return _document_to_images(path, target, ctx, reserved)
    out_path = _unique(path.parent, path.stem, f".{target}", reserved)
    if target == "txt":
        if ext in (".xlsx", ".csv"):
            text = _rows_to_text(_read_rows(path, ctx))
        else:
            text = _read_text(path, ctx)
        _write_text(text, out_path, ctx)
    elif target == "csv":
        _write_csv(_read_rows(path, ctx), out_path)
        ctx.progress(1.0)
    elif target == "xlsx":
        _write_xlsx(_read_rows(path, ctx), out_path)
        ctx.progress(1.0)
    elif target == "html":
        if ext != ".md":
            raise EngineError(i18n.tr("err.doc_html_only_md"))
        _markdown_to_html(path, out_path, ctx)
    elif target == "pdf":
        _write_pdf(path, out_path, ctx)
    else:
        raise EngineError(i18n.tr("err.doc_unsupported_conversion", target=target))
    return [out_path]
