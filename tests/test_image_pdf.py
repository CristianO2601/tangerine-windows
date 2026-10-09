from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader

from tangerine import engines, image_pdf
from tangerine.image_pdf import PdfOptions


def _ctx(cancel: threading.Event | None = None, progress=None, status=None) -> engines.Ctx:
    return engines.Ctx(progress or (lambda _value: None), status or (lambda _text: None), cancel)


def _write_rgb(path: Path, color: tuple[int, int, int] = (200, 40, 20), size=(24, 16)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def test_is_pdf_image_includes_requested_legacy_extensions():
    for suffix in (".jpg", ".svg", ".gif", ".jpe", ".jfif", ".dib", ".ico"):
        assert image_pdf.is_pdf_image(Path(f"photo{suffix}"))
    assert not image_pdf.is_pdf_image(Path("notes.txt"))


def test_ordered_paths_received_natural_and_manual():
    paths = [Path("photo10.jpg"), Path("photo2.jpg"), Path("photo1.jpg")]
    assert image_pdf.ordered_paths(paths, "received") == paths
    assert image_pdf.ordered_paths(paths, "manual") == paths
    assert image_pdf.ordered_paths(paths, "name") == [paths[2], paths[1], paths[0]]
    with pytest.raises(ValueError):
        image_pdf.ordered_paths(paths, "random")


def test_create_pdf_deduplicates_canonical_inputs_and_keeps_order(tmp_path):
    first = _write_rgb(tmp_path / "photo10.jpg", (240, 20, 10))
    second = _write_rgb(tmp_path / "photo2.jpg", (10, 240, 20))
    output = image_pdf.create_image_pdf(
        [first, second, tmp_path / "." / first.name], _ctx(),
        options=PdfOptions(order="received"),
    )
    assert output == tmp_path / "photo10 PDF.pdf"
    assert len(PdfReader(output).pages) == 2


def test_name_order_and_manual_order_drive_page_order(tmp_path, monkeypatch):
    paths = [
        _write_rgb(tmp_path / "page10.png"),
        _write_rgb(tmp_path / "page2.png"),
        _write_rgb(tmp_path / "page1.png"),
    ]
    observed: list[str] = []
    prepare = image_pdf._prepare_image

    def record(path, with_filename, font_scale):
        observed.append(path.name)
        return prepare(path, with_filename, font_scale)

    monkeypatch.setattr(image_pdf, "_prepare_image", record)
    image_pdf.create_image_pdf(paths, _ctx(), options=PdfOptions(order="name"))
    assert observed == ["page1.png", "page2.png", "page10.png"]

    observed.clear()
    image_pdf.create_image_pdf(paths, _ctx(), options=PdfOptions(order="manual"))
    assert observed == [path.name for path in paths]


def test_prepare_image_flattens_transparency_and_applies_exif_orientation(tmp_path):
    transparent = tmp_path / "transparent.png"
    rgba = Image.new("RGBA", (12, 8), (255, 0, 0, 0))
    rgba.putpixel((4, 3), (0, 120, 10, 255))
    rgba.save(transparent)
    prepared = image_pdf._prepare_image(transparent, False, 1.0)
    try:
        assert prepared.mode == "RGB"
        assert prepared.getpixel((0, 0)) == (255, 255, 255)
        assert prepared.getpixel((4, 3)) == (0, 120, 10)
    finally:
        prepared.close()

    oriented = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (12, 8), (20, 40, 200)).save(oriented, exif=exif)
    prepared = image_pdf._prepare_image(oriented, False, 1.0)
    try:
        assert prepared.size == (8, 12)
    finally:
        prepared.close()


def test_filename_label_and_grid_layout(tmp_path):
    paths = [_write_rgb(tmp_path / f"scan-{index}.png") for index in range(5)]
    plain = image_pdf._prepare_image(paths[0], False, 1.0)
    labeled = image_pdf._prepare_image(paths[0], True, 1.0)
    try:
        assert labeled.height > plain.height
    finally:
        plain.close()
        labeled.close()

    output = image_pdf.create_image_pdf(
        paths, _ctx(), options=PdfOptions(rows=2, columns=2, with_filenames=True),
    )
    assert len(PdfReader(output).pages) == 2


def test_explicit_existing_output_is_not_overwritten(tmp_path):
    source = _write_rgb(tmp_path / "source.png")
    output = tmp_path / "chosen.pdf"
    output.write_bytes(b"keep existing bytes")
    with pytest.raises(engines.EngineError):
        image_pdf.create_image_pdf([source], _ctx(), options=PdfOptions(output=output))
    assert output.read_bytes() == b"keep existing bytes"


def test_auto_output_reservation_uses_unique_sibling(tmp_path):
    source = _write_rgb(tmp_path / "source.png")
    original = tmp_path / "source.pdf"
    original.write_bytes(b"already here")
    output = image_pdf.create_image_pdf([source], _ctx())
    assert output == tmp_path / "source 2.pdf"
    assert original.read_bytes() == b"already here"
    assert len(PdfReader(output).pages) == 1


def test_concurrent_jobs_reserve_distinct_outputs(tmp_path):
    source = _write_rgb(tmp_path / "parallel.png")
    reserved: set[Path] = set()

    def run():
        return image_pdf.create_image_pdf([source], _ctx(), reserved)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _index: run(), range(2)))
    assert len(set(outputs)) == 2
    assert {path.name for path in outputs} == {"parallel.pdf", "parallel 2.pdf"}
    assert {path.name for path in reserved} == {"parallel.pdf", "parallel 2.pdf"}
    assert all(len(PdfReader(path).pages) == 1 for path in outputs)


def test_corrupt_input_does_not_leave_output_or_reservation(tmp_path, monkeypatch):
    good = _write_rgb(tmp_path / "good.png")
    corrupt = tmp_path / "broken.jpg"
    corrupt.write_bytes(b"not an image")
    reserved: set[Path] = set()
    prepared: list[Image.Image] = []
    original_prepare = image_pdf._prepare_image

    def track_prepared(path, with_filename, font_scale):
        image = original_prepare(path, with_filename, font_scale)
        prepared.append(image)
        return image

    # The first loaded image must be closed when a later source is corrupt.
    monkeypatch.setattr(image_pdf, "_prepare_image", track_prepared)
    with pytest.raises(engines.EngineError):
        image_pdf.create_image_pdf([good, corrupt], _ctx(), reserved)
    assert reserved == set()
    assert len(prepared) == 1
    with pytest.raises(ValueError):
        prepared[0].getpixel((0, 0))
    assert list(tmp_path.glob("*.pdf")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_empty_selection_raises_without_creating_files(tmp_path):
    reserved: set[Path] = set()
    with pytest.raises(engines.EngineError):
        image_pdf.create_image_pdf([], _ctx(), reserved)
    assert reserved == set()
    assert list(tmp_path.iterdir()) == []


def test_cancel_before_processing_leaves_no_outputs(tmp_path):
    source = _write_rgb(tmp_path / "cancel.png")
    cancel = threading.Event()
    cancel.set()
    reserved: set[Path] = set()
    with pytest.raises(engines.EngineError, match="Cancelled|Cancelado"):
        image_pdf.create_image_pdf([source], _ctx(cancel), reserved)
    assert reserved == set()
    assert list(tmp_path.glob("*.pdf")) == []


def test_cancel_after_temp_save_cleans_temp_and_reservation(tmp_path, monkeypatch):
    source = _write_rgb(tmp_path / "after-save.png")
    cancel = threading.Event()
    original_save = Image.Image.save

    def save_then_cancel(self, *args, **kwargs):
        result = original_save(self, *args, **kwargs)
        cancel.set()
        return result

    monkeypatch.setattr(Image.Image, "save", save_then_cancel)
    reserved: set[Path] = set()
    with pytest.raises(engines.EngineError, match="Cancelled|Cancelado"):
        image_pdf.create_image_pdf([source], _ctx(cancel), reserved)
    assert reserved == set()
    assert list(tmp_path.glob("*.pdf")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_read_only_input_is_accepted_and_wrapper_remains_compatible(tmp_path, monkeypatch):
    source = _write_rgb(tmp_path / "readonly.png")
    source.chmod(0o444)
    monkeypatch.setattr(
        engines, "verify_writable",
        lambda _path: (_ for _ in ()).throw(AssertionError("source must be read-only")),
    )
    try:
        output = engines.images_to_pdf([source], _ctx(), set())
    finally:
        source.chmod(0o666)
    assert output == tmp_path / "readonly.pdf"
    assert len(PdfReader(output).pages) == 1


def test_progress_reaches_one_only_after_pdf_is_published(tmp_path, monkeypatch):
    source = _write_rgb(tmp_path / "progress.png")
    values: list[float] = []
    output = tmp_path / "progress.pdf"
    original_replace = image_pdf.os.replace

    def assert_before_publish(src, dst):
        assert values and values[-1] < 1.0
        assert not Path(dst).read_bytes()
        return original_replace(src, dst)

    monkeypatch.setattr(image_pdf.os, "replace", assert_before_publish)
    result = image_pdf.create_image_pdf(
        [source], _ctx(progress=values.append), options=PdfOptions(output=output),
    )
    assert result == output
    assert values[-1] == 1.0
    assert len(PdfReader(output).pages) == 1
