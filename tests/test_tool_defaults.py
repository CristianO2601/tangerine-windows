"""Adversarial checks for explicit reuse of editor options."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from PIL import Image
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPushButton, QTabWidget

from tangerine import paths, settings, tool_defaults
from tangerine.editors.images import BackgroundDialog, CompressDialog


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Keep every persistence test in a disposable per-test settings file."""
    target = tmp_path / "settings.json"
    monkeypatch.setattr(paths, "settings_file", lambda: target)
    monkeypatch.setattr(settings, "_cache", deepcopy(settings.DEFAULTS))
    yield target
    assert target.parent == tmp_path


def _make_image(path: Path):
    Image.new("RGB", (120, 90), (124, 75, 38)).save(path)
    return path


def _safe_run_batch(calls):
    def run_batch(paths, run_one, title=None):
        calls.append({"paths": list(paths), "title": title})
        # Exercise the editor's callback without starting an engine, worker,
        # subprocess, or progress window.
        return run_one(Path(paths[0]), object(), set())

    return run_batch


def _no_dialog_exec():
    pytest.fail("QDialog.exec() must be bypassed for valid opted-in defaults")


def test_tool_option_reuse_is_disabled_by_default(isolated_settings):
    assert settings.get("toolSkipOptions") == {}
    assert settings.get("toolDefaultOptions") == {}
    for key in tool_defaults.SUPPORTED:
        assert not tool_defaults.is_enabled(key)
        assert not tool_defaults.can_reuse(key)


def test_cancelling_compression_dialog_does_not_enable_reuse(
    qapp, isolated_settings, tmp_path
):
    source = _make_image(tmp_path / "source.png")
    dialog = CompressDialog([source], "image")
    try:
        assert not dialog.reuse_options.isChecked()
        dialog.reuse_options.setChecked(True)
        cancel = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Cancel"
        )
        QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)
        assert dialog.result() == int(QDialog.DialogCode.Rejected)
        assert not tool_defaults.is_enabled("img.compress")
        assert tool_defaults.load_options("img.compress") is None
    finally:
        dialog.close()


def test_cancelling_background_dialog_does_not_enable_reuse(
    qapp, isolated_settings, tmp_path
):
    source = _make_image(tmp_path / "source.png")
    dialog = BackgroundDialog(source)
    try:
        assert not dialog.reuse_options.isChecked()
        dialog.reuse_options.setChecked(True)
        cancel = next(
            button for button in dialog.findChildren(QPushButton)
            if button.text() == "Cancel"
        )
        QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)
        assert dialog.result() == int(QDialog.DialogCode.Rejected)
        assert not tool_defaults.is_enabled("img.background")
        assert tool_defaults.load_options("img.background") is None
    finally:
        dialog.close()


def test_opted_in_compression_replays_without_modal_exec_or_engine(
    qapp, isolated_settings, tmp_path, monkeypatch
):
    from tangerine.editors import images as image_editors

    source = _make_image(tmp_path / "photo.png")
    options = {
        "strength": "strong",
        "size": "1920",
        "target_enabled": True,
        "target_kb": 8,
    }
    tool_defaults.remember("img.compress", options, True)
    run_calls = []
    engine_calls = []
    monkeypatch.setattr(image_editors, "run_batch", _safe_run_batch(run_calls))
    monkeypatch.setattr(
        image_editors.tools,
        "compress_image",
        lambda path, strength, max_edge, target, ctx, reserved: engine_calls.append(
            (path, strength, max_edge, target)
        ) or "captured",
    )

    dialog = CompressDialog([source], "image")
    monkeypatch.setattr(dialog, "exec", _no_dialog_exec)
    try:
        assert dialog.reuse_options.isChecked()
        assert dialog.strength.currentIndex() == 1
        assert dialog.size.currentIndex() == 2
        assert dialog.target_check.isChecked()
        assert dialog.target_kb.value() == 8
        result = dialog.exec_with_defaults()
        assert result == int(QDialog.DialogCode.Accepted)
        assert len(run_calls) == 1
        assert engine_calls == [(source, "strong", 1920, 8192)]
        assert tool_defaults.can_reuse("img.compress")
    finally:
        dialog.close()


def test_opted_in_background_replays_without_modal_exec_or_engine(
    qapp, isolated_settings, tmp_path, monkeypatch
):
    from tangerine.editors import images as image_editors

    source = _make_image(tmp_path / "background-source.png")
    options = {
        "fill": {"type": "gradient", "from": "#112233", "to": "#DDAA77", "angle": 130},
        "aspect": "4:3",
        "margin": 37,
        "radius": 19,
        "fit": "contain",
    }
    tool_defaults.remember("img.background", options, True)
    run_calls = []
    engine_calls = []
    monkeypatch.setattr(image_editors, "run_batch", _safe_run_batch(run_calls))
    monkeypatch.setattr(
        image_editors.tools,
        "add_background",
        lambda path, received, ctx, reserved: engine_calls.append(
            (path, received)
        ) or "captured",
    )

    dialog = BackgroundDialog(source)
    monkeypatch.setattr(dialog, "exec", _no_dialog_exec)
    try:
        assert dialog.reuse_options.isChecked()
        assert dialog.fill_type.currentIndex() == 1
        assert dialog.angle.value() == 130
        assert dialog.aspect.currentIndex() == 2
        assert dialog.margin.value() == 37
        assert dialog.radius.value() == 19
        result = dialog.exec_with_defaults()
        assert result == int(QDialog.DialogCode.Accepted)
        assert len(run_calls) == 1
        expected = deepcopy(options)
        expected["fill"]["to"] = "#ddaa77"
        assert engine_calls == [(source, expected)]
        assert tool_defaults.can_reuse("img.background")
    finally:
        dialog.close()


@pytest.mark.parametrize("case", ["missing-image", "corrupt-options", "corrupt-image"])
def test_bad_background_default_falls_back_to_dialog(
    qapp, isolated_settings, tmp_path, monkeypatch, case
):
    from tangerine.editors import images as image_editors

    source = _make_image(tmp_path / f"source-{case}.png")
    missing = tmp_path / "not-here.png"
    corrupt = tmp_path / "broken.png"
    corrupt.write_bytes(b"not an image")
    good_shape = {
        "fill": {"type": "image", "path": str(missing)},
        "aspect": "original",
        "margin": 0,
        "radius": 0,
        "fit": "contain",
    }
    if case == "corrupt-options":
        stored = {"fill": {"type": "gradient", "from": "not-a-color"}}
    else:
        stored = deepcopy(good_shape)
        if case == "corrupt-image":
            stored["fill"]["path"] = str(corrupt)
    settings.set("toolDefaultOptions", {"img.background": stored})
    settings.set("toolSkipOptions", {"img.background": True})

    dialog = BackgroundDialog(source)
    exec_calls = []
    monkeypatch.setattr(
        dialog, "exec",
        lambda: exec_calls.append(True) or int(QDialog.DialogCode.Rejected),
    )
    monkeypatch.setattr(
        image_editors,
        "run_batch",
        lambda *args, **kwargs: pytest.fail("invalid defaults must not start a batch"),
    )
    try:
        result = dialog.exec_with_defaults()
        assert result == int(QDialog.DialogCode.Rejected)
        assert exec_calls == [True]
        assert dialog._image_path is None
    finally:
        dialog.close()


@pytest.mark.parametrize("key,value", [
    ("img.compress", None),
    ("img.compress", []),
    ("img.compress", {"strength": "balanced", "size": "original",
                       "target_enabled": False, "target_kb": True}),
    ("img.background", {"fill": {"type": "gradient", "from": "#112233",
                                  "to": "#AABBCC", "angle": True},
                        "aspect": "original", "margin": 0,
                        "radius": 0, "fit": "contain"}),
])
def test_malformed_persisted_defaults_never_become_reusable(
    isolated_settings, key, value
):
    settings.set("toolDefaultOptions", {key: value})
    settings.set("toolSkipOptions", {key: True})
    assert tool_defaults.load_options(key) is None
    assert not tool_defaults.can_reuse(key)


def test_settings_default_toggles_refresh_when_window_is_reopened(
    qapp, isolated_settings
):
    from tangerine.settings_window import SettingsWindow

    tool_defaults.remember(
        "img.compress",
        {"strength": "balanced", "size": "original",
         "target_enabled": False, "target_kb": 500},
        False,
    )
    window = SettingsWindow()
    tabs = window.findChild(QTabWidget)
    check = window.default_option_checks["img.compress"]
    try:
        window.show()
        tabs.setCurrentIndex(2)
        qapp.processEvents()
        assert not check.isChecked()
        assert check.isEnabled()
        assert check.isVisible()

        QTest.mouseClick(
            check, Qt.MouseButton.LeftButton,
            pos=QPoint(8, check.height() // 2),
        )
        qapp.processEvents()
        assert check.isChecked()
        assert tool_defaults.is_enabled("img.compress")

        window.hide()
        tool_defaults.set_enabled("img.compress", False)
        window.show()
        qapp.processEvents()
        assert not check.isChecked()

        QTest.mouseClick(
            check, Qt.MouseButton.LeftButton,
            pos=QPoint(8, check.height() // 2),
        )
        qapp.processEvents()
        assert tool_defaults.is_enabled("img.compress")
        window.hide()
        window.show()
        qapp.processEvents()
        assert check.isChecked()
    finally:
        window.close()
