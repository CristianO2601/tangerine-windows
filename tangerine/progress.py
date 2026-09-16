"""Closable mini progress windows with the custom Tangerine orange bar."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from . import i18n, theme
from .jobs import Job

log = logging.getLogger("tangerine")

_ACTIVE: set["ProgressWindow"] = set()


class OrangeProgressBar(QWidget):
    """Custom-drawn orange progress bar (determinate and marquee)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self._value = 0.0
        self._indeterminate = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_value(self, value: float) -> None:
        if value < 0:
            self._indeterminate = True
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._indeterminate = False
            self._timer.stop()
        self._value = max(0.0, min(value, 1.0))
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.035) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 28))
        painter.drawRoundedRect(rect, 7, 7)
        if self._indeterminate:
            span = self.width() * 0.32
            offset = (self.width() + span) * self._phase - span
            chunk = QRectF(offset, 0, span, self.height())
            painter.setClipRect(rect)
            gradient_pen = QColor(theme.ACCENT)
            painter.setBrush(gradient_pen)
            painter.drawRoundedRect(chunk, 7, 7)
        elif self._value > 0:
            chunk = QRectF(0, 0, self.width() * self._value, self.height())
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(chunk, 7, 7)
        painter.end()


class ProgressWindow(QWidget):
    """Rounded mini window; closing it lets the job continue."""

    finished_closed = Signal(object)
    _cascade = [0]

    def __init__(self, title: str, job: Job, parent: QWidget | None = None):
        super().__init__(parent)
        self.job = job
        self.outputs: list[Path] = []
        self.failed = False
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(380)
        self.setWindowTitle(title)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QWidget(self)
        card.setObjectName("ProgressCard")
        p = theme.palette(theme.is_dark())
        card.setStyleSheet(
            f"#ProgressCard {{ background: {p['window']}; border: 1px solid {p['border']};"
            f" border-radius: 14px; }}"
        )
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        header.addWidget(self.title_label)
        header.addStretch(1)
        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 12px; background: transparent; }"
            f"QPushButton:hover {{ background: {p['hover']}; }}"
        )
        close_btn.clicked.connect(self.close)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.status_label = QLabel(i18n.tr("progress.starting"))
        self.status_label.setProperty("muted", True)
        self.status_label.setStyleSheet(f"color: {p['text_dim']};")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.bar = OrangeProgressBar()
        layout.addWidget(self.bar)

        self.error_view = QPlainTextEdit()
        self.error_view.setReadOnly(True)
        self.error_view.setVisible(False)
        self.error_view.setFixedHeight(120)
        layout.addWidget(self.error_view)

        self.cancel_btn = QPushButton(i18n.tr("progress.cancel"))
        self.cancel_btn.clicked.connect(self._cancel_clicked)
        layout.addWidget(self.cancel_btn)

        self.dismiss_btn = QPushButton(i18n.tr("progress.dismiss"))
        self.dismiss_btn.setVisible(False)
        self.dismiss_btn.clicked.connect(self.close)
        layout.addWidget(self.dismiss_btn)

        self._shown_once = False
        self._dismissed = False
        self._job_done = False
        self._position()

        job.progress.connect(self._on_progress)
        job.status.connect(self._on_status)
        job.finished.connect(self._on_finished)
        job.failed.connect(self._on_failed)

    # -- placement ---------------------------------------------------------
    def _position(self) -> None:
        screen = QGuiApplication.screenAt(self.cursor().pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        offset = ProgressWindow._cascade[0] % 6
        ProgressWindow._cascade[0] += 1
        x = area.center().x() - self.width() // 2 + offset * 26
        y = area.center().y() - 80 + offset * 26
        self.move(x, y)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._shown_once:
            self._shown_once = True
            self._position()

    # -- job wiring ----------------------------------------------------------
    def _on_progress(self, value: float) -> None:
        self.bar.set_value(value)

    def _on_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _cancel_clicked(self) -> None:
        self.job.cancel()
        self.status_label.setText(i18n.tr("progress.cancelling"))

    def _on_finished(self, outputs: list) -> None:
        self._job_done = True
        self.cancel_btn.setVisible(False)
        self.outputs = list(outputs)
        check_timer = QTimer(self)
        check_timer.setInterval(300)
        attempts = [0]

        def verify() -> None:
            attempts[0] += 1
            if not self.outputs or all(Path(p).exists() for p in self.outputs):
                check_timer.stop()
                self.bar.set_value(1.0)
                self.close()
            elif attempts[0] >= 50:
                check_timer.stop()
                self.bar.set_value(1.0)
                self.status_label.setText(i18n.tr("progress.output_unconfirmed"))
                self.close()

        check_timer.timeout.connect(verify)
        check_timer.start()

    def _on_failed(self, message: str) -> None:
        self._fail(message)

    def _fail(self, message: str) -> None:
        self.failed = True
        self._job_done = True
        self.cancel_btn.setVisible(False)
        if self._dismissed:
            log.warning("Job failed after the progress window was dismissed: %s", message)
            return
        self.bar.set_value(0.0)
        if self.job.cancel_event.is_set():
            self.status_label.setText(i18n.tr("progress.cancelled"))
        else:
            self.status_label.setText(i18n.tr("progress.operation_failed"))
        self.error_view.setPlainText(message)
        self.error_view.setVisible(True)
        self.dismiss_btn.setVisible(True)
        self.show()
        self.raise_()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._job_done:
            self._dismissed = True
        _ACTIVE.discard(self)
        super().closeEvent(event)
        self.finished_closed.emit(self)


def run_job(title: str, work, parent: QWidget | None = None) -> ProgressWindow:
    job = Job(work, parent)
    window = ProgressWindow(title, job, parent)
    _ACTIVE.add(window)
    window.show()
    job.start()
    return window
