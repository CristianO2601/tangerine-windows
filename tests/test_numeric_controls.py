"""Interaction and rendering checks for the shared numeric spin controls."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QSpinBox, QVBoxLayout, QWidget

from tangerine.editors.ui.controls import NumericDoubleSpinBox, NumericSpinBox
from tangerine.theme import stylesheet


def _install_theme(qapp, dark: bool):
    old = qapp.styleSheet()
    qapp.setStyleSheet(stylesheet(dark))
    return old


def test_numeric_controls_keep_native_types_and_large_hit_targets(qapp):
    integer = NumericSpinBox()
    decimal = NumericDoubleSpinBox()
    try:
        assert isinstance(integer, QSpinBox)
        assert isinstance(decimal, QDoubleSpinBox)
        assert integer.minimumHeight() >= 50
        assert integer._up_button.width() >= 24
        assert integer._down_button.width() >= 24
        assert integer._up_button.height() >= 24
        assert integer._down_button.height() >= 24
        assert integer.lineEdit().textMargins().right() >= 40
        assert integer.lineEdit().cursor().shape() == Qt.CursorShape.IBeamCursor
        assert integer._up_button.cursor().shape() == Qt.CursorShape.PointingHandCursor
    finally:
        integer.deleteLater()
        decimal.deleteLater()


def test_step_buttons_keyboard_wheel_suffix_and_limits(qapp):
    box = NumericSpinBox()
    box.setRange(0, 3)
    box.setSuffix(" px")
    box.resize(180, 50)
    box.show()
    try:
        assert box.value() == 0
        assert "0" in box.lineEdit().text()
        assert "px" in box.lineEdit().text()
        assert not box._down_button.isEnabled()

        QTest.mouseClick(box._up_button, Qt.MouseButton.LeftButton)
        assert box.value() == 1
        QTest.mouseClick(box._up_button, Qt.MouseButton.LeftButton)
        assert box.value() == 2

        box.lineEdit().selectAll()
        QTest.keyClicks(box.lineEdit(), "3")
        QTest.keyClick(box.lineEdit(), Qt.Key.Key_Enter)
        assert box.value() == 3
        assert not box._up_button.isEnabled()
        assert box._down_button.isEnabled()

        box.setFocus(Qt.FocusReason.OtherFocusReason)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        position = QPointF(12, 20)
        global_position = QPointF(box.mapToGlobal(QPoint(12, 20)))
        wheel = QWheelEvent(
            position,
            global_position,
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(box, wheel)
        assert box.value() == 2
        QTest.mouseClick(box._down_button, Qt.MouseButton.LeftButton)
        assert box.value() == 1
    finally:
        box.close()
        box.deleteLater()


def test_numeric_controls_render_in_both_theme_modes(qapp, tmp_path):
    old = qapp.styleSheet()
    try:
        for dark in (False, True):
            qapp.setStyleSheet(stylesheet(dark))
            panel = QWidget()
            panel.setWindowTitle("Numeric controls")
            layout = QVBoxLayout(panel)
            layout.addWidget(QLabel("Zero value with suffix"))
            zero = NumericSpinBox()
            zero.setRange(0, 100)
            zero.setValue(0)
            zero.setSuffix(" px")
            layout.addWidget(zero)
            layout.addWidget(QLabel("At maximum"))
            maximum = NumericDoubleSpinBox()
            maximum.setRange(0.0, 12.0)
            maximum.setDecimals(1)
            maximum.setValue(12.0)
            maximum.setSuffix(" %")
            layout.addWidget(maximum)
            panel.resize(300, 210)
            panel.show()
            qapp.processEvents()
            baseline = panel.grab().toImage()
            # The offscreen platform does not update the mouse cursor's widget
            # tracking, so set the same Qt hover attribute used by :hover.
            zero._up_button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
            qapp.processEvents()
            hovered = panel.grab().toImage()
            assert baseline != hovered
            sample = zero._up_button.mapTo(
                panel, QPoint(zero._up_button.width() // 2,
                              zero._up_button.height() - 3)
            )
            before = baseline.pixelColor(sample)
            after = hovered.pixelColor(sample)
            assert (abs(before.red() - after.red()) +
                    abs(before.green() - after.green()) +
                    abs(before.blue() - after.blue())) >= 50
            target = tmp_path / ("numeric-controls-dark.png" if dark else
                                 "numeric-controls-light.png")
            assert hovered.save(str(target))
            assert target.stat().st_size > 1000
            assert not maximum._up_button.isEnabled()
            panel.close()
            panel.deleteLater()
            qapp.processEvents()
    finally:
        qapp.setStyleSheet(old)


def test_double_step_button_changes_fractional_value(qapp):
    box = NumericDoubleSpinBox()
    box.setRange(0.0, 1.0)
    box.setDecimals(2)
    box.setSingleStep(0.25)
    box.resize(150, 50)
    try:
        QTest.mouseClick(box._up_button, Qt.MouseButton.LeftButton)
        assert box.value() == 0.25
        QTest.mouseClick(box._down_button, Qt.MouseButton.LeftButton)
        assert box.value() == 0.0
        assert not box._down_button.isEnabled()
    finally:
        box.deleteLater()
