"""End-to-end document conversions: docx, xlsx, pptx, csv, rtf, md, odt, epub.

Every fixture is synthesized locally in ``tmp_path``, so the module needs no
external assets and no FFmpeg. Each reader library is guarded with
``pytest.importorskip``: if one is missing the whole module is skipped instead
of failing.
"""

import zipfile
from pathlib import Path

import pytest

docx = pytest.importorskip("docx", reason="python-docx is required for the document tests")
openpyxl = pytest.importorskip("openpyxl", reason="openpyxl is required for the document tests")
pptx = pytest.importorskip("pptx", reason="python-pptx is required for the document tests")
pytest.importorskip("striprtf", reason="striprtf is required for the document tests")
pytest.importorskip("odf", reason="odfpy is required for the document tests")
pytest.importorskip("markdown", reason="Markdown is required for the document tests")

from tangerine import catalog, engines, tools

ROUTES = {
    ".docx": ("txt", "pdf", "jpg", "png"),
    ".xlsx": ("csv", "pdf", "jpg", "png"),
    ".pptx": ("txt", "pdf", "jpg", "png"),
    ".csv": ("xlsx", "pdf", "jpg", "png", "txt"),
    ".rtf": ("txt", "pdf", "jpg", "png"),
    ".md": ("txt", "html", "pdf", "jpg", "png"),
    ".odt": ("txt", "pdf", "jpg", "png"),
    ".epub": ("txt",),
}

EPUB_MIMETYPE = "application/epub+zip"
EPUB_CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
EPUB_PACKAGE = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:tangerine-fixture</dc:identifier>
    <dc:title>Tangerine fixture</dc:title>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
  </spine>
</package>"""
EPUB_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 1</title></head>
<body><h1>Chapter One</h1><p>Hello from the EPUB fixture.</p></body>
</html>"""


def _write_docx(path: Path) -> None:
    document = docx.Document()
    document.add_heading("Tangerine fixture", level=1)
    document.add_paragraph("A paragraph with plain text for the converter.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "Alpha"
    table.cell(1, 1).text = "42"
    document.save(str(path))


def _write_xlsx(path: Path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in range(1, 4):
        for column in range(1, 5):
            sheet.cell(row=row, column=column, value=f"R{row}C{column}")
    workbook.save(str(path))


def _write_pptx(path: Path) -> None:
    presentation = pptx.Presentation()
    first = presentation.slides.add_slide(presentation.slide_layouts[1])
    first.shapes.title.text = "First slide"
    first.placeholders[1].text = "First bullet"
    second = presentation.slides.add_slide(presentation.slide_layouts[1])
    second.shapes.title.text = "Second slide"
    second.placeholders[1].text = "Second bullet"
    presentation.save(str(path))


def _write_csv(path: Path) -> None:
    path.write_text("Name,Value\nalpha,1\nbeta,2\n", encoding="utf-8")


def _write_rtf(path: Path) -> None:
    path.write_text(
        r"{\rtf1\ansi\deff0{\fonttbl{\f0 Times New Roman;}}"
        r"\f0\fs24 Tangerine RTF fixture.\par}",
        encoding="utf-8",
    )


def _write_md(path: Path) -> None:
    path.write_text(
        "# Tangerine fixture\n\n"
        "A **Markdown** paragraph with a [link](https://example.com).\n\n"
        "- first item\n- second item\n",
        encoding="utf-8",
    )


def _write_odt(path: Path) -> None:
    from odf.opendocument import OpenDocumentText
    from odf.text import P

    document = OpenDocumentText()
    document.text.addElement(P(text="First ODT paragraph"))
    document.text.addElement(P(text="Second ODT paragraph"))
    document.save(str(path))


def _write_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"), EPUB_MIMETYPE, compress_type=zipfile.ZIP_STORED
        )
        archive.writestr("META-INF/container.xml", EPUB_CONTAINER)
        archive.writestr("OEBPS/content.opf", EPUB_PACKAGE)
        archive.writestr("OEBPS/chapter1.xhtml", EPUB_CHAPTER)


BUILDERS = {
    ".docx": _write_docx,
    ".xlsx": _write_xlsx,
    ".pptx": _write_pptx,
    ".csv": _write_csv,
    ".rtf": _write_rtf,
    ".md": _write_md,
    ".odt": _write_odt,
    ".epub": _write_epub,
}

PAIRS = [(ext, target) for ext, targets in ROUTES.items() for target in targets]
PAIR_IDS = [f"{ext.lstrip('.')}-to-{target}" for ext, target in PAIRS]


@pytest.fixture
def documents(tmp_path):
    paths = {}
    for ext, builder in BUILDERS.items():
        path = tmp_path / f"fixture{ext}"
        builder(path)
        assert path.stat().st_size > 0, f"fixture for {ext} was not written"
        paths[ext] = path
    return paths


@pytest.mark.parametrize(("ext", "target"), PAIRS, ids=PAIR_IDS)
def test_document_route_converts(documents, ext, target):
    source = documents[ext]

    offered = {conversion.target_ext for conversion in catalog.conversions_for([source])}
    assert target in offered, f"{ext} -> {target} is not offered by the catalog"

    outputs = engines.convert_single(source, target, engines.Ctx(), set())
    assert outputs, f"{ext} -> {target} produced no outputs"
    for output in outputs:
        assert isinstance(output, Path)
        assert output.exists(), f"{ext} -> {target}: missing {output}"
        assert output.stat().st_size > 0, f"{ext} -> {target}: empty {output}"
        assert output.suffix.lower() == f".{target}", f"{ext} -> {target}: wrong suffix {output}"


def test_compress_document_never_grows(documents):
    source = documents[".docx"]
    original_size = source.stat().st_size

    output = tools.compress_document(source, engines.Ctx(), set())

    assert output.exists()
    assert output.stat().st_size > 0
    assert output.stat().st_size <= original_size


def test_broken_docx_raises_friendly_engine_error(tmp_path):
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"this is not an OOXML package at all")

    with pytest.raises(engines.EngineError) as raised:
        engines.convert_single(broken, "txt", engines.Ctx(), set())

    assert "could not be opened" in str(raised.value).lower()
