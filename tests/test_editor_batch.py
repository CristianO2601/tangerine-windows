"""Multi-file editor routing and selection semantics for image tools."""
from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog

from tangerine import actions, catalog, editors


def _names(paths):
    return [path.name for path in paths]


def test_multi_image_selection_offers_per_image_tools(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: {"pillow"})
    paths = [Path("first.jpg"), Path("second.png")]

    ids = {tool.id for tool in catalog.tools_for(paths)}

    assert {"img.crop", "img.annotate", "img.redact", "img.background"} <= ids
    assert catalog.tool_paths("img.crop", paths) == paths


def test_mixed_selection_scopes_per_image_tools_to_images(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: {"pillow"})
    paths = [Path("first.jpg"), Path("paper.pdf"), Path("second.png")]

    ids = {tool.id for tool in catalog.tools_for(paths)}

    assert {"img.crop", "img.annotate", "img.redact", "img.background"} <= ids
    assert catalog.tool_paths("img.crop", paths) == [paths[0], paths[2]]


def test_mixed_svg_selection_only_routes_raster_canvas_tools_to_raster(
    monkeypatch,
):
    monkeypatch.setattr(catalog, "available_engines", lambda: {"pillow"})
    paths = [Path("logo.svg"), Path("photo.jpg"), Path("paper.pdf")]

    ids = {tool.id for tool in catalog.tools_for(paths)}

    assert "img.crop" in ids
    assert "img.background" in ids
    assert {"img.annotate", "img.redact"} <= ids
    assert catalog.tool_paths("img.annotate", paths) == [Path("photo.jpg")]
    assert catalog.tool_paths("img.redact", paths) == [Path("photo.jpg")]


def test_svg_only_batch_does_not_offer_raster_canvas_tools(monkeypatch):
    monkeypatch.setattr(catalog, "available_engines", lambda: {"pillow"})

    ids = {tool.id for tool in catalog.tools_for([Path("one.svg"), Path("two.svg")])}

    assert "img.crop" in ids
    assert "img.background" in ids
    assert "img.annotate" not in ids
    assert "img.redact" not in ids


@pytest.mark.parametrize("key", ["img.crop", "img.annotate", "img.redact"])
def test_actions_run_editor_for_each_image_in_order(monkeypatch, qapp, key):
    opened = []

    class Dialog(QDialog):
        def __init__(self, path, parent=None):
            super().__init__(parent)
            opened.append(Path(path).name)
            self.job_window = object()

        def exec(self):
            return QDialog.DialogCode.Accepted

    class StopOnSecond(Dialog):
        def exec(self):
            return (
                QDialog.DialogCode.Accepted
                if len(opened) == 1
                else QDialog.DialogCode.Rejected
            )

    factory = StopOnSecond if key == "img.redact" else Dialog
    attr = {
        "img.crop": "CropImageDialog",
        "img.annotate": "AnnotateDialog",
        "img.redact": "RedactPhotoDialog",
    }[key]
    monkeypatch.setattr(editors, attr, factory)
    paths = ["first.jpg", "second.png", "third.webp"]

    handle = actions.run_tool(paths, key)

    expected = _names([Path(path) for path in paths])
    completed = expected[:2] if key == "img.redact" else expected
    assert opened == completed
    assert len(handle.dialogs) == len(opened)
    assert len(handle.job_windows) == (1 if key == "img.redact" else len(opened))


def test_background_dispatch_passes_full_selection_as_shared_options_batch(
    monkeypatch, qapp
):
    seen = []

    class Dialog(QDialog):
        def __init__(self, paths, parent=None):
            super().__init__(parent)
            seen.extend(Path(path).name for path in paths)

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(editors, "BackgroundDialog", Dialog)

    dialog = actions.run_tool(["first.jpg", "second.png"], "img.background")

    assert seen == ["first.jpg", "second.png"]
    assert dialog is not None


def test_background_editor_applies_one_options_object_to_every_image(
    monkeypatch, qapp, tmp_path
):
    from PIL import Image

    from tangerine.editors import images

    paths = [tmp_path / "first.png", tmp_path / "second.png"]
    for path in paths:
        Image.new("RGBA", (8, 8), "white").save(path)

    calls = []

    class Context:
        def status(self, _message):
            pass

    def fake_add_background(path, options, _ctx, _reserved):
        calls.append((Path(path), options))
        return Path(path)

    def fake_run_batch(batch_paths, run_one):
        reserved = set()
        for path in batch_paths:
            run_one(path, Context(), reserved)
        return object()

    monkeypatch.setattr(images.tools, "add_background", fake_add_background)
    monkeypatch.setattr(images, "run_batch", fake_run_batch)
    dialog = images.BackgroundDialog(paths)

    dialog._accept_clicked()

    assert [path for path, _options in calls] == paths
    assert calls[0][1] == calls[1][1]
    dialog.close()
