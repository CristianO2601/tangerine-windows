"""Shared, accessible numeric spin boxes used by Tangerine editors.

These remain real ``QSpinBox``/``QDoubleSpinBox`` subclasses, so existing
``findChild`` calls, value signals, validators, keyboard editing and wheel
behavior keep their normal Qt contracts.  The native tiny step arrows are
replaced by two explicit, easy-to-hit child buttons.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QSpinBox,
    QToolButton,
)


class _ChevronButton(QToolButton):
    """Tool button that paints a crisp chevron without a platform glyph."""

    def __init__(self, direction: str, parent: QAbstractSpinBox):
        super().__init__(parent)
        self.setProperty("numericStepButton", True)
        self.setProperty("stepDirection", direction)
        self.setObjectName(f"numericStep{direction.title()}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(75)
        self.setAccessibleName("Increase" if direction == "up" else "Decrease")
        self._direction = direction

    def mousePressEvent(self, event):
        parent = self.parentWidget()
        if parent is not None:
            parent.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        # Let QSS render the button surface and interaction states first.
        super().paintEvent(event)
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() / 2
        cy = self.height() / 2
        path = QPainterPath()
        if self._direction == "up":
            path.moveTo(QPointF(cx - 4.5, cy + 1.5))
            path.lineTo(QPointF(cx, cy - 2.5))
            path.lineTo(QPointF(cx + 4.5, cy + 1.5))
        else:
            path.moveTo(QPointF(cx - 4.5, cy - 1.5))
            path.lineTo(QPointF(cx, cy + 2.5))
            path.lineTo(QPointF(cx + 4.5, cy - 1.5))
        painter.drawPath(path)


class _NumericSpinMixin:
    """Shared behavior for native Qt spin boxes with large step controls."""

    _BUTTON_WIDTH = 32

    def _init_numeric_controls(self):
        self.setProperty("numericControl", True)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setMinimumHeight(50)  # each half keeps a minimum 24 px target
        self.setMinimumWidth(92)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.lineEdit().setCursor(Qt.CursorShape.IBeamCursor)

        self._up_button = _ChevronButton("up", self)
        self._down_button = _ChevronButton("down", self)
        self._up_button.clicked.connect(lambda: self.stepBy(1))
        self._down_button.clicked.connect(lambda: self.stepBy(-1))
        self.valueChanged.connect(self._sync_step_buttons)
        self._sync_step_buttons()
        self._layout_step_buttons()

    def _layout_step_buttons(self):
        if not hasattr(self, "_up_button"):
            return
        inset = 1
        width = self._BUTTON_WIDTH
        usable_height = max(48, self.height() - inset * 2)
        top_height = usable_height // 2
        x = max(inset, self.width() - width - inset)
        self._up_button.setGeometry(x, inset, width, top_height)
        self._down_button.setGeometry(
            x, inset + top_height, width, usable_height - top_height
        )
        # Keep editable text, including suffixes and zero values, outside the
        # overlaid step-button column.
        self.lineEdit().setTextMargins(0, 0, width + 8, 0)

    def _sync_step_buttons(self, *_):
        if not hasattr(self, "_up_button"):
            return
        enabled = self.stepEnabled()
        self._up_button.setEnabled(
            bool(enabled & QAbstractSpinBox.StepEnabledFlag.StepUpEnabled)
        )
        self._down_button.setEnabled(
            bool(enabled & QAbstractSpinBox.StepEnabledFlag.StepDownEnabled)
        )

    def setRange(self, minimum, maximum):
        super().setRange(minimum, maximum)
        self._sync_step_buttons()

    def setMinimum(self, minimum):
        super().setMinimum(minimum)
        self._sync_step_buttons()

    def setMaximum(self, maximum):
        super().setMaximum(maximum)
        self._sync_step_buttons()

    def setReadOnly(self, read_only):
        super().setReadOnly(read_only)
        self._sync_step_buttons()

    def setValue(self, value):
        """Refresh affordances even when callers block Qt value signals."""
        super().setValue(value)
        self._sync_step_buttons()

    def stepBy(self, steps):
        super().stepBy(steps)
        self._sync_step_buttons()

    def setWrapping(self, wrapping):
        super().setWrapping(wrapping)
        self._sync_step_buttons()

    def interpretText(self):
        super().interpretText()
        self._sync_step_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_step_buttons()


class NumericSpinBox(_NumericSpinMixin, QSpinBox):
    """Drop-in ``QSpinBox`` with a clear 32×24 px minimum step hit target."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_numeric_controls()


class NumericDoubleSpinBox(_NumericSpinMixin, QDoubleSpinBox):
    """Drop-in ``QDoubleSpinBox`` with the shared large step controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_numeric_controls()
