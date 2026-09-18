"""Mixed-family selections (v1.8).

Before: picking files of different families (a photo plus a PDF, text plus a
PDF...) produced an empty wheel because ``conversions_for`` bailed out unless
every path shared one family, and ``tools_for`` only knew a couple of mixed
pairs. Now the wheel offers the intersection of conversions every file can
run and the union of batch tools that applies to at least one family.
"""

from pathlib import Path

from tangerine import catalog

ENGINES = {
    "pillow",
    "heic",
    "pdfium",
    "pypdf",
    "docx",
    "xlsx",
    "pptx",
    "rtf",
    "odt",
    "markdown",
    "reportlab",
    "qr",
    "ocr",
    "ffmpeg",
    "unrar",
    "rar",
}


def _paths(*names: str) -> list[Path]:
    return [Path(name) for name in names]


def _targets(conversions) -> list[str]:
    return [conversion.target_ext for conversion in conversions]


def _ids(tools) -> list[str]:
    return [tool.id for tool in tools]


def test_mixed_image_and_pdf_offers_common_targets(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    conversions = catalog.conversions_for(_paths("photo.jpg", "paper.pdf"))
    assert _targets(conversions) == ["png", "docx"]


def test_mixed_image_and_text_offers_common_targets(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    conversions = catalog.conversions_for(_paths("photo.jpg", "notes.txt"))
    assert _targets(conversions) == ["png", "pdf"]


def test_mixed_pdf_and_text_offers_common_targets(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    conversions = catalog.conversions_for(_paths("paper.pdf", "notes.txt"))
    assert _targets(conversions) == ["jpg", "png"]


def test_mixed_document_and_pdf_offers_common_targets(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    conversions = catalog.conversions_for(_paths("report.docx", "paper.pdf"))
    assert _targets(conversions) == ["txt", "jpg", "png"]


def test_mixed_selection_without_common_target_is_empty(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    assert catalog.conversions_for(_paths("photo.jpg", "bundle.zip")) == []


def test_single_family_batch_tools_unchanged(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    assert _ids(catalog.tools_for(_paths("a.jpg", "b.jpg"))) == [
        "img.compress",
        "img.pdf",
        "img.collage",
        "qr.read",
    ]


def test_mixed_tools_union_is_filtered_by_family(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    ids = _ids(catalog.tools_for(_paths("photo.jpg", "paper.pdf")))
    assert ids == ["img.compress", "img.pdf", "qr.read"]

    ids = _ids(catalog.tools_for(_paths("photo.jpg", "second.jpg", "paper.pdf")))
    assert ids == ["img.compress", "img.pdf", "img.collage", "qr.read"]

    ids = _ids(catalog.tools_for(_paths("a.pdf", "b.pdf", "photo.jpg")))
    assert ids == ["img.compress", "img.pdf", "pdf.merge", "qr.read"]

    ids = _ids(catalog.tools_for(_paths("one.mp4", "two.mp4")))
    assert ids == ["vid.compress", "vid.join"]


def test_tool_paths_filters_a_mixed_selection(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: ENGINES)
    paths = _paths("photo.jpg", "paper.pdf", "clip.mp4")
    assert catalog.tool_paths("img.pdf", paths) == [Path("photo.jpg")]
    assert catalog.tool_paths("pdf.merge", paths) == [Path("paper.pdf")]
    assert catalog.tool_paths("vid.compress", paths) == [Path("clip.mp4")]
    assert catalog.tool_paths("qr.read", paths) == [
        Path("photo.jpg"),
        Path("paper.pdf"),
    ]
    assert catalog.tool_paths("unknown.tool", paths) == paths
