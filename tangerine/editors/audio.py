"""Audio editors: channels, visualizer, trim and bleep."""
from __future__ import annotations

import array
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QWidget,
)

from .. import progress, tools
from ..media import CREATE_NO_WINDOW, ffmpeg_path
from .base import ToolDialog
from .ui.waveform import BleepWaveform, PlayerMixin, TrimWaveform


def audio_peaks(path: Path, buckets: int = 1400) -> list[float]:
    exe = ffmpeg_path()
    if not exe:
        return []
    args = [
        exe, "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
    ]
    try:
        proc = subprocess.run(
            args, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60)
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    data = proc.stdout
    samples = array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return []
    step = max(1, len(samples) // buckets)
    peaks: list[float] = []
    for start in range(0, len(samples) - step + 1, step):
        chunk = samples[start:start + step]
        magnitude = max(max(chunk), -min(chunk)) / 32768.0
        peaks.append(magnitude)
    return peaks


# ---------------------------------------------------------------------------
# Audio: channels, visualizer, trim, bleep
# ---------------------------------------------------------------------------

class ChannelsDialog(ToolDialog):
    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Convert Audio Channels", parent)
        self._path = Path(path)
        info = tools.probe(self._path)
        audio = info.audio()
        channels = audio.channels if audio else 0

        heading = QLabel(f"{self._path.name} currently has {channels or '?'} channel(s).")
        heading.setWordWrap(True)
        self._body.addWidget(heading)

        self.mono = QRadioButton("Mono mixdown")
        self.stereo = QRadioButton("Two-channel stereo")
        if channels == 1:
            self.stereo.setChecked(True)
        else:
            self.mono.setChecked(True)
        self._body.addWidget(self.mono)
        self._body.addWidget(self.stereo)
        hint = QLabel("Mono to stereo duplicates the signal. "
                      "Mono mixdown combines both channels.")
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        self._body.addWidget(hint)
        self.add_buttons("Save Converted Copy")

    def _accept_clicked(self) -> None:
        mode = "mono" if self.mono.isChecked() else "stereo"
        path = self._path
        progress.run_job(
            f"Converting channels for {path.name}",
            lambda ctx: [tools.convert_channels(path, mode, ctx, set())],
        )
        self.accept()


class VisualizerDialog(ToolDialog):
    def __init__(self, path, parent: QWidget | None = None):
        super().__init__("Audio Visualizer", parent)
        self._path = Path(path)
        self._background: Path | None = None

        form = QFormLayout()
        form.setSpacing(10)
        self.orientation = QComboBox()
        self.orientation.addItems(["Landscape 1280 x 720", "Portrait 720 x 1280",
                                   "Square 1080 x 1080"])
        form.addRow("Shape", self.orientation)
        self._body.addLayout(form)

        row = QHBoxLayout()
        self.bg_label = QLabel("Background image: none")
        self.bg_label.setProperty("dim", True)
        choose = QPushButton("Choose Image...")
        choose.clicked.connect(self._choose_background)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_background)
        row.addWidget(self.bg_label, 1)
        row.addWidget(choose)
        row.addWidget(clear)
        self._body.addLayout(row)

        hint = QLabel("The full recording is rendered as a Tangerine-orange waveform "
                      "on black or your chosen image.")
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        self._body.addWidget(hint)
        self.add_buttons("Create Visualizer")

    def _choose_background(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Background Image", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if chosen:
            self._background = Path(chosen)
            self.bg_label.setText(f"Background image: {Path(chosen).name}")

    def _clear_background(self) -> None:
        self._background = None
        self.bg_label.setText("Background image: none")

    def _accept_clicked(self) -> None:
        orientation = ["landscape", "portrait", "square"][self.orientation.currentIndex()]
        path = self._path
        background = self._background
        progress.run_job(
            f"Building visualizer for {path.name}",
            lambda ctx: [tools.make_visualizer(path, orientation, background, ctx, set())],
        )
        self.accept()


class TrimAudioDialog(ToolDialog, PlayerMixin):
    def __init__(self, path, parent: QWidget | None = None):
        ToolDialog.__init__(self, "Trim Audio", parent)
        self._path = Path(path)
        self._duration = tools.probe_duration_seconds(self._path) or 0.0
        self._setup_player()
        self._load_source(self._path)

        self.waveform = TrimWaveform()
        self._body.addWidget(self.waveform)
        self.waveform.start = 0.0
        self.waveform.end = self._duration
        self.waveform.changed = self._waveform_changed
        self.loading = QLabel("Loading waveform…")
        self.loading.setProperty("dim", True)
        self._body.addWidget(self.loading)

        form = QFormLayout()
        form.setSpacing(10)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0.0, max(self._duration, 0.01))
        self.start_spin.setDecimals(3)
        self.start_spin.setSuffix(" s")
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.0, max(self._duration, 0.01))
        self.end_spin.setDecimals(3)
        self.end_spin.setValue(self._duration)
        self.end_spin.setSuffix(" s")
        form.addRow("Start", self.start_spin)
        form.addRow("End", self.end_spin)
        self._body.addLayout(form)
        self.start_spin.valueChanged.connect(self._spins_changed)
        self.end_spin.valueChanged.connect(self._spins_changed)

        row = QHBoxLayout()
        play = QPushButton("Play Selection")
        play.clicked.connect(self._play_selection)
        stop = QPushButton("Stop")
        stop.clicked.connect(self._stop_playback)
        auto = QPushButton("Auto-trim Silence")
        auto.clicked.connect(self._auto_trim)
        row.addWidget(play)
        row.addWidget(stop)
        row.addWidget(auto)
        row.addStretch(1)
        self._body.addLayout(row)
        self.add_buttons("Save Trimmed Copy")
        QTimer.singleShot(50, self._load_waveform)

    def _load_waveform(self) -> None:
        self.waveform.set_peaks(audio_peaks(self._path), self._duration)
        self.loading.setVisible(False)

    def _waveform_changed(self, start: float, end: float) -> None:
        self.start_spin.blockSignals(True)
        self.end_spin.blockSignals(True)
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)
        self.start_spin.blockSignals(False)
        self.end_spin.blockSignals(False)

    def _spins_changed(self) -> None:
        self.waveform.start = self.start_spin.value()
        self.waveform.end = self.end_spin.value()
        self.waveform.update()

    def _play_selection(self) -> None:
        self._stop_playback()
        self._player.setPosition(int(self.start_spin.value() * 1000))
        self._player.play()
        self._playhead_timer.start()

    def _playhead_tick(self) -> None:
        position = self._player.position() / 1000.0
        self.waveform.set_playhead(position)
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            if position >= self.end_spin.value() - 0.03:
                self._stop_playback()

    def _auto_trim(self) -> None:
        peaks = self.waveform.peaks
        if not peaks:
            QMessageBox.information(self, "Auto-trim", "The waveform is not available yet.")
            return
        top = max(peaks)
        if top <= 0:
            return
        threshold = top * 0.035
        first = next((i for i, p in enumerate(peaks) if p > threshold), None)
        last = next((i for i in range(len(peaks) - 1, -1, -1) if peaks[i] > threshold), None)
        if first is None or last is None or last <= first:
            QMessageBox.information(
                self, "Auto-trim",
                "The selected range is silent at this threshold. "
                "Lower the threshold or turn off automatic trimming.")
            return
        start = (first / len(peaks)) * self._duration
        end = ((last + 1) / len(peaks)) * self._duration
        self.start_spin.setValue(max(0.0, start - 0.05))
        self.end_spin.setValue(min(self._duration, end + 0.05))

    def _accept_clicked(self) -> None:
        start, end = self.start_spin.value(), self.end_spin.value()
        if end - start < 0.05:
            QMessageBox.warning(self, "Trim Audio", "The selected range is too short.")
            return
        self._stop_playback()
        path = self._path
        progress.run_job(
            f"Trimming {path.name}",
            lambda ctx: [tools.trim_audio(path, start, end, ctx, set())],
        )
        self.accept()


class BleepDialog(ToolDialog, PlayerMixin):
    def __init__(self, path, parent: QWidget | None = None):
        ToolDialog.__init__(self, "Bleep Audio", parent)
        self._path = Path(path)
        self._duration = tools.probe_duration_seconds(self._path) or 0.0
        self._setup_player()
        self._load_source(self._path)

        self.waveform = BleepWaveform()
        self.waveform.duration = self._duration
        self._body.addWidget(self.waveform)
        self.loading = QLabel("Loading waveform…")
        self.loading.setProperty("dim", True)
        self._body.addWidget(self.loading)

        form = QFormLayout()
        form.setSpacing(10)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0.0, max(self._duration, 0.01))
        self.start_spin.setDecimals(3)
        self.start_spin.setSuffix(" s")
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.0, max(self._duration, 0.01))
        self.end_spin.setDecimals(3)
        self.end_spin.setSuffix(" s")
        form.addRow("Range start", self.start_spin)
        form.addRow("Range end", self.end_spin)
        self._body.addLayout(form)

        row = QHBoxLayout()
        add = QPushButton("Add / Update Range")
        add.clicked.connect(self._add_range)
        entire = QPushButton("Bleep Entire Audio")
        entire.clicked.connect(self._bleep_entire)
        remove = QPushButton("Delete Range")
        remove.clicked.connect(self._delete_range)
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(entire)
        row.addStretch(1)
        self._body.addLayout(row)

        playback = QHBoxLayout()
        play = QPushButton("Play Original")
        play.clicked.connect(self._play)
        stop = QPushButton("Stop")
        stop.clicked.connect(self._stop_playback)
        playback.addWidget(play)
        playback.addWidget(stop)
        playback.addStretch(1)
        self._body.addLayout(playback)

        hint = QLabel("Drag across the waveform to add a range, then drag a range or "
                      "either edge to adjust it. A 1 kHz tone replaces the samples "
                      "inside every range on all channels.")
        hint.setProperty("dim", True)
        hint.setWordWrap(True)
        self._body.addWidget(hint)
        self.waveform.changed = self._waveform_changed
        self.add_buttons("Save Bleeped Copy")
        QTimer.singleShot(50, self._load_waveform)

    def _load_waveform(self) -> None:
        self.waveform.set_peaks(audio_peaks(self._path), self._duration)
        self.loading.setVisible(False)

    def _waveform_changed(self) -> None:
        ranges = self.waveform.ranges
        if self.waveform.selected >= 0 and self.waveform.selected < len(ranges):
            start, end = ranges[self.waveform.selected]
            self.start_spin.blockSignals(True)
            self.end_spin.blockSignals(True)
            self.start_spin.setValue(start)
            self.end_spin.setValue(end)
            self.start_spin.blockSignals(False)
            self.end_spin.blockSignals(False)

    def _add_range(self) -> None:
        start, end = sorted((self.start_spin.value(), self.end_spin.value()))
        if end - start < 0.02:
            QMessageBox.warning(self, "Bleep Audio", "The range is too short.")
            return
        self.waveform.ranges.append([start, end])
        self.waveform.selected = len(self.waveform.ranges) - 1
        self.waveform.update()

    def _bleep_entire(self) -> None:
        self.waveform.ranges = [[0.0, self._duration]]
        self.waveform.selected = 0
        self._waveform_changed()
        self.waveform.update()

    def _delete_range(self) -> None:
        if self.waveform.selected >= 0:
            self.waveform.ranges.pop(self.waveform.selected)
            self.waveform.selected = -1
            self.waveform.update()

    def _play(self) -> None:
        self._stop_playback()
        self._player.play()
        self._playhead_timer.start()

    def _playhead_tick(self) -> None:
        position = self._player.position() / 1000.0
        self.waveform.set_playhead(position)
        if self._player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            self._playhead_timer.stop()
            self.waveform.set_playhead(-1)

    def _accept_clicked(self) -> None:
        ranges = [tuple(r) for r in self.waveform.ranges]
        if not ranges:
            QMessageBox.warning(self, "Bleep Audio", "Add at least one bleep range first.")
            return
        self._stop_playback()
        path = self._path
        progress.run_job(
            f"Bleeping {path.name}",
            lambda ctx: [tools.bleep_audio(path, ranges, ctx, set())],
        )
        self.accept()
