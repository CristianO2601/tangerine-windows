"""OCR end-to-end: scanned (image-only) PDFs are read back as text.

The optional OCR engine (rapidocr-onnxruntime) is required; the module skips
when it is missing. A small scanned page is synthesized in tmp_path, so the
suite needs no external assets and runs the engine at 250 dpi on one page.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

pytest.importorskip(
    "rapidocr_onnxruntime", reason="rapidocr-onnxruntime is required for the OCR tests"
)
docx = pytest.importorskip("docx", reason="python-docx is required for the OCR docx test")

from tangerine import catalog, engines

MARKER = "TANGERINE OCR TEST 12345"


def _marker_font(size: int):
    for name in ("arialbd.ttf", "consola.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


@pytest.fixture(scope="module")
def scanned_pdf(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("ocr")
    path = folder / "scanned.pdf"
    image = Image.new("RGB", (1000, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 90), MARKER, font=_marker_font(56), fill="black")
    image.save(path, "PDF", resolution=150.0)
    return path


def test_catalog_advertises_ocr_engine():
    assert "ocr" in catalog.available_engines()


def test_scanned_pdf_ocr_to_txt(scanned_pdf):
    outputs = engines.convert_single(scanned_pdf, "txt", engines.Ctx(), set())
    text = outputs[0].read_text("utf-8")
    assert "TANGERINE" in text.upper()
    assert "12345" in text


def test_scanned_pdf_ocr_to_docx(scanned_pdf):
    outputs = engines.convert_single(scanned_pdf, "docx", engines.Ctx(), set())
    document = docx.Document(str(outputs[0]))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "TANGERINE" in text.upper()
    assert "12345" in text


def test_ocr_missing_error_mentions_install_command(scanned_pdf, monkeypatch):
    monkeypatch.setattr(engines, "_ocr_available", lambda: False)
    with pytest.raises(engines.EngineError) as raised:
        engines.convert_single(scanned_pdf, "txt", engines.Ctx(), set())
    message = str(raised.value)
    assert "no selectable text" in message
    assert "pip install rapidocr-onnxruntime" in message


def test_docx_falls_back_to_page_images_without_ocr(scanned_pdf, monkeypatch):
    monkeypatch.setattr(engines, "_ocr_available", lambda: False)
    outputs = engines.convert_single(scanned_pdf, "docx", engines.Ctx(), set())
    document = docx.Document(str(outputs[0]))
    assert len(document.inline_shapes) >= 1
