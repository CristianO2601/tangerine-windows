"""Audio waveform widgets and the shared media-player mixin."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QWidget


class PlayerMixin:
    def _setup_player(self) -> None:
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.9)
        self._playhead_timer = QTimer(self)
        self._playhead_timer.setInterval(60)
        self._playhead_timer.timeout.connect(self._playhead_tick)

    def _load_source(self, path: Path) -> None:
        self._player.setSource(QUrl.fromLocalFile(str(path)))

    def _stop_playback(self) -> None:
        self._player.stop()
        self._playhead_timer.stop()
        self._playhead_tick()

    def _playhead_tick(self) -> None:
        pass


class WaveformView(QWidget):
    """Orange waveform bars on a dark rounded background."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.peaks: list[float] = []
        self.duration = 0.0
        self.playhead = -1.0
        self.setMinimumHeight(120)
        self.setMouseTracking(True)

    def set_peaks(self, peaks: list[float], duration: float) -> None:
        self.peaks = peaks
        self.duration = duration
        self.update()

    def set_playhead(self, seconds: float) -> None:
        self.playhead = seconds
        self.update()

    def x_for(self, seconds: float) -> float:
        if self.duration <= 0:
            return 0.0
        return self.width() * seconds / self.duration

    def seconds_for(self, x: float) -> float:
        if self.width() <= 0:
            return 0.0
        return max(0.0, min(self.duration, x / self.width() * self.duration))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(127, 127, 127, 26))
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)

        mid = self.height() / 2.0
        if self.peaks:
            painter.setBrush(QColor("#F87800"))
            bar_w = max(1.0, self.width() / len(self.peaks) - 1.0)
            for index, peak in enumerate(self.peaks):
                x = index * self.width() / len(self.peaks)
                half = max(1.5, peak * (mid - 8))
                painter.drawRoundedRect(QRectF(x, mid - half, bar_w, half * 2), 1.5, 1.5)

        if self.playhead >= 0:
            painter.setPen(QPen(QColor("#FFFFFF"), 1.4))
            x = self.x_for(self.playhead)
            painter.drawLine(QPointF(x, 4), QPointF(x, self.height() - 4))

        painter.setPen(QPen(QColor(127, 127, 127, 90), 1.0))
        painter.drawLine(QPointF(0, mid), QPointF(self.width(), mid))
        painter.end()


class TrimWaveform(WaveformView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.start = 0.0
        self.end = 0.0
        self._drag = None
        self.changed = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self.duration <= 0:
            return
        x = event.position().x()
        if abs(x - self.x_for(self.start)) <= abs(x - self.x_for(self.end)):
            self._drag = "start"
        else:
            self._drag = "end"

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return
        seconds = self.seconds_for(event.position().x())
        if self._drag == "start":
            self.start = min(seconds, self.end - 0.05)
        else:
            self.end = max(seconds, self.start + 0.05)
        if self.changed:
            self.changed(self.start, self.end)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        shade = QColor(0, 0, 0, 90)
        painter.fillRect(QRectF(0, 0, self.x_for(self.start), self.height()), shade)
        painter.fillRect(QRectF(self.x_for(self.end), 0,
                                self.width() - self.x_for(self.end), self.height()), shade)
        painter.setPen(QPen(QColor("#F87800"), 2.0))
        for position in (self.start, self.end):
            x = self.x_for(position)
            painter.drawLine(QPointF(x, 2), QPointF(x, self.height() - 2))
        painter.end()


class BleepWaveform(WaveformView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ranges: list[list[float]] = []
        self.selected = -1
        self._drag = None
        self._start = 0.0
        self.changed = None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self.duration <= 0:
            return
        x = event.position().x()
        for index, (start, end) in enumerate(self.ranges):
            if abs(x - self.x_for(start)) <= 8:
                self.selected = index
                self._drag = "edge-start"
                return
            if abs(x - self.x_for(end)) <= 8:
                self.selected = index
                self._drag = "edge-end"
                return
            if self.x_for(start) < x < self.x_for(end):
                self.selected = index
                self._drag = "move"
                self._start = self.seconds_for(x)
                if self.changed:
                    self.changed()
                self.update()
                return
        self.selected = -1
        self._drag = "new"
        self._start = self.seconds_for(x)
        if self.changed:
            self.changed()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return
        seconds = self.seconds_for(event.position().x())
        if self._drag == "new":
            start, end = sorted((self._start, seconds))
            self.ranges.append([start, end])
            self.selected = len(self.ranges) - 1
            self._drag = "edge-end"
        elif self._drag == "edge-start":
            self.ranges[self.selected][0] = min(seconds, self.ranges[self.selected][1] - 0.02)
        elif self._drag == "edge-end":
            self.ranges[self.selected][1] = max(seconds, self.ranges[self.selected][0] + 0.02)
        elif self._drag == "move":
            start, end = self.ranges[self.selected]
            width = end - start
            shift = seconds - self._start
            new_start = max(0.0, min(start + shift, self.duration - width))
            self.ranges[self.selected] = [new_start, new_start + width]
            self._start = seconds
        if self.changed:
            self.changed()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None
        self.ranges = [r for r in self.ranges if r[1] - r[0] >= 0.02]

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected >= 0:
            self.ranges.pop(self.selected)
            self.selected = -1
            if self.changed:
                self.changed()
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for index, (start, end) in enumerate(self.ranges):
            rect = QRectF(self.x_for(start), 4, self.x_for(end) - self.x_for(start), self.height() - 8)
            fill = QColor("#F87800")
            fill.setAlpha(70 if index != self.selected else 110)
            painter.fillRect(rect, fill)
            painter.setPen(QPen(QColor("#F87800") if index == self.selected else QColor(248, 120, 0, 150), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
        painter.end()
