"""Faithful HTML rendering (v1.8).

The builders are pure Python and run anywhere; only the final
``html_to_pdf`` step needs QtWebEngine on the GUI thread, so the suite
covers the markup here and the PDF round-trip skips under the offscreen
platform used by the tests (a live check runs it for real).
"""

import os

import pytest

from tangerine import render


def test_markdown_renders_headings_tables_and_code():
    source = (
        "# Title\n\n"
        "Some **bold** text.\n\n"
        "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
        "```python\nprint('hi')\n```\n"
    )
    page = render.markdown_to_html(source)
    assert "<title>Title</title>" in page
    assert "<h1>Title</h1>" in page
    assert "<table>" in page
    assert "codehilite" in page
    assert "<style>" in page


def test_markdown_title_comes_from_argument_or_first_heading():
    assert "<title>Custom</title>" in render.markdown_to_html("no heading", "Custom")
    assert "<title>Hello</title>" in render.markdown_to_html("# Hello\n\ntext")


def test_table_to_html_shapes_rows():
    page = render.table_to_html([["h1", "h2"], ["a", "b"]])
    assert page == (
        "<table><thead><tr><th>h1</th><th>h2</th></tr></thead>"
        "<tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    )
    assert render.table_to_html([]) == "<p></p>"


def test_csv_escapes_markup(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("name,note\nx,<script>alert(1)</script>\n", "utf-8")
    page = render.csv_to_html(csv_path)
    assert "&lt;script&gt;" in page
    assert "<script>" not in page
    assert "<title>sample</title>" in page


def test_docx_renders_paragraphs(tmp_path):
    docx = pytest.importorskip("docx")
    path = tmp_path / "sample.docx"
    document = docx.Document()
    document.add_paragraph("Hola mundo")
    document.save(path)

    page = render.docx_to_html(path)
    assert "Hola mundo" in page
    assert "<p>" in page
    assert "<title>sample</title>" in page


def test_xlsx_renders_cell_values(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "sample.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet["A1"] = "hola"
    sheet["B1"] = 42
    workbook.save(path)

    page = render.xlsx_to_html(path)
    assert "hola" in page
    assert "42" in page
    assert "<title>sample</title>" in page


def test_html_to_pdf_without_renderer_is_false(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "_renderer", None)
    assert render.html_to_pdf("<p>x</p>", tmp_path / "x.pdf") is False


def test_pdf_roundtrip_needs_a_real_platform(tmp_path):
    if os.environ.get("QT_QPA_PLATFORM", "") == "offscreen":
        pytest.skip("QtWebEngine needs a real platform")
    if not render.available():
        pytest.skip("QtWebEngine not installed")

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    assert app is not None
    assert render.ensure_ready()

    out = tmp_path / "roundtrip.pdf"
    assert render.html_to_pdf("<h1>Hola</h1><p>Render fiel</p>", out)
    assert out.stat().st_size > 0
