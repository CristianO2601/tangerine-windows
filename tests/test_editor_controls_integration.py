"""Offscreen layout and input checks for numeric controls inside full dialogs."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest

from tangerine import theme
from tangerine.editors.images import BackgroundDialog, CropImageDialog
from tangerine.editors.ui.controls import NumericSpinBox


def _assert_within_dialog(dialog, widget):
    top_left = widget.mapTo(dialog, QPoint(0, 0))
    mapped = QRect(top_left, widget.size())
    assert dialog.rect().contains(mapped), (
        f"{widget.objectName() or type(widget).__name__} is clipped: "
        f"{mapped} outside {dialog.rect()}"
    )


def _assert_spin_targets(dialog, spin):
    assert spin.isVisible()
    assert spin.lineEdit().textMargins().right() >= 40
    for button in (spin._up_button, spin._down_button):
        _assert_within_dialog(dialog, button)
        assert button.width() >= 24
        assert button.height() >= 24
        assert spin.rect().contains(button.geometry())


def _enter_text(spin, text):
    spin.lineEdit().setFocus()
    spin.lineEdit().selectAll()
    QTest.keyClicks(spin.lineEdit(), text)
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)


def _dialog_screenshot(dialog, path):
    dialog.show()
    QTest.qWait(350)
    assert dialog.isVisible()
    assert dialog.grab().save(str(path))
    assert path.stat().st_size > 10_000


@pytest.mark.parametrize("dark", [False, True])
def test_crop_and_background_dialog_controls_fit_and_interact(
    qapp, tmp_path, monkeypatch, dark
):
    monkeypatch.setattr(theme, "is_dark", lambda: dark)
    qapp.setStyleSheet(theme.stylesheet(dark))
    source = tmp_path / "landscape.png"
    Image.new("RGB", (1200, 900), (118, 78, 48)).save(source)
    evidence = Path("build/ui-repair-evidence/20261009")
    evidence.mkdir(parents=True, exist_ok=True)
    mode = "dark" if dark else "light"

    crop = CropImageDialog(source)
    try:
        _dialog_screenshot(crop, evidence / f"crop-dialog-{mode}.png")
        _assert_within_dialog(crop, crop.canvas)
        _assert_spin_targets(crop, crop.w_spin)
        _assert_spin_targets(crop, crop.h_spin)
        crop.w_spin.setValue(500)
        before = crop.w_spin.value()
        QTest.mouseClick(crop.w_spin._up_button, Qt.MouseButton.LeftButton)
        assert crop.w_spin.value() == before + 1
        QTest.mouseClick(crop.w_spin._down_button, Qt.MouseButton.LeftButton)
        assert crop.w_spin.value() == before
        assert crop.canvas.rect[2] == before
    finally:
        crop.close()
        crop.deleteLater()
        qapp.processEvents()

    background = BackgroundDialog(source)
    try:
        background.margin.setValue(8)
        background.radius.setValue(4)
        _dialog_screenshot(background, evidence / f"background-dialog-{mode}.png")
        _assert_spin_targets(background, background.margin)
        _assert_spin_targets(background, background.radius)
        QTest.mouseClick(background.margin._up_button, Qt.MouseButton.LeftButton)
        assert background.margin.value() == 9
        QTest.mouseClick(background.margin._down_button, Qt.MouseButton.LeftButton)
        assert background.margin.value() == 8
        _enter_text(background.margin, "25")
        _enter_text(background.radius, "14")
        assert background.margin.value() == 25
        assert background.radius.value() == 14
        assert background.margin.lineEdit().text().endswith("px")
        assert background.radius.lineEdit().text().endswith("px")
    finally:
        background.close()
        background.deleteLater()
        qapp.processEvents()


def test_numeric_readonly_and_disabled_states_keep_native_behavior(qapp):
    spin = NumericSpinBox()
    spin.setRange(0, 10)
    spin.setValue(4)
    spin.resize(140, 50)
    spin.show()
    qapp.processEvents()
    try:
        spin.setReadOnly(True)
        assert spin.lineEdit().isReadOnly()
        assert not spin._up_button.isEnabled()
        assert not spin._down_button.isEnabled()
        QTest.keyClicks(spin.lineEdit(), "9")
        QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
        assert spin.value() == 4
        spin.setReadOnly(False)
        assert spin._up_button.isEnabled()
        QTest.mouseClick(spin._up_button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert spin.value() == 5

        spin.setEnabled(False)
        assert not spin._up_button.isEnabled()
        assert not spin._down_button.isEnabled()
        QTest.mouseClick(spin._down_button, Qt.MouseButton.LeftButton)
        assert spin.value() == 5
    finally:
        spin.deleteLater()
        qapp.processEvents()
