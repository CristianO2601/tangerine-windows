"""Programmatic crop updates refresh custom spin buttons with signals blocked."""
from pathlib import Path

from PIL import Image
import pytest
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtTest import QTest
from tangerine.editors.images import CropImageDialog
from tangerine.editors.ui.controls import NumericSpinBox, NumericDoubleSpinBox


@pytest.mark.parametrize("factory", [NumericSpinBox, NumericDoubleSpinBox])
def test_blocked_value_updates_refresh_step_buttons(qapp, factory):
    spin = factory()
    spin.setRange(0, 10)
    spin.setValue(10)
    emitted = []
    spin.valueChanged.connect(emitted.append)
    assert not spin._up_button.isEnabled()
    with QSignalBlocker(spin):
        spin.setValue(5)
    assert emitted == []
    assert spin._up_button.isEnabled()
    spin.show()
    qapp.processEvents()
    QTest.mouseClick(spin._up_button, Qt.MouseButton.LeftButton)
    assert spin.value() == 6
    assert emitted == [6]
    with QSignalBlocker(spin):
        spin.setValue(0)
    assert not spin._down_button.isEnabled()
    spin.close()


def test_wrapping_and_blocked_step_refresh_buttons_without_emitting(qapp):
    spin = NumericSpinBox()
    spin.setRange(0, 10)
    spin.setValue(9)
    emitted = []
    spin.valueChanged.connect(emitted.append)
    with QSignalBlocker(spin):
        spin.stepBy(1)
    assert spin.value() == 10
    assert not spin._up_button.isEnabled()
    assert emitted == []

    spin.setWrapping(True)
    assert spin._up_button.isEnabled()
    assert spin._down_button.isEnabled()


def test_crop_rect_changed_blocked_values_leave_both_arrows_accurate(
    qapp, tmp_path
):
    source = tmp_path / "source.png"
    Image.new("RGB", (120, 90), (118, 78, 48)).save(source)
    dialog = CropImageDialog(source)
    try:
        dialog.show()
        qapp.processEvents()
        dialog._rect_changed([0.0, 0.0, 1.0, 1.0])
        assert dialog.w_spin.value() == 1
        assert dialog.h_spin.value() == 1
        assert dialog.w_spin._up_button.isEnabled()
        assert dialog.h_spin._up_button.isEnabled()
        assert not dialog.w_spin._down_button.isEnabled()
        assert not dialog.h_spin._down_button.isEnabled()

        QTest.mouseClick(dialog.w_spin._up_button, Qt.MouseButton.LeftButton)
        assert dialog.w_spin.value() == 2
        assert dialog.w_spin._down_button.isEnabled()
        QTest.mouseClick(dialog.w_spin._down_button, Qt.MouseButton.LeftButton)
        assert dialog.w_spin.value() == 1
        assert not dialog.w_spin._down_button.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
