"""Tabbed settings window (persisted through tangerine.settings)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import settings
from .media import ffmpeg_path, ffprobe_path, rar_path, unrar_path
from . import paths

_WINDOW = None


class ModifierChecks(QGroupBox):
    def __init__(self, title, key, parent=None):
        super().__init__(title, parent)
        self._key = key
        self._boxes: dict[str, QCheckBox] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(14)
        for mod in settings.MODIFIER_ORDER:
            box = QCheckBox(settings.MODIFIER_LABELS.get(mod, mod.title()))
            box.toggled.connect(self._changed)
            self._boxes[mod] = box
            layout.addWidget(box)
        layout.addStretch(1)
        self._load()

    def _load(self):
        mask = settings.parse_mask(str(settings.get(self._key, "")))
        if not mask:
            mask = {"shift"}
        for mod, box in self._boxes.items():
            box.blockSignals(True)
            box.setChecked(mod in mask)
            box.blockSignals(False)

    def _changed(self):
        mask = {mod for mod, box in self._boxes.items() if box.isChecked()}
        if not mask:
            sender = self.sender()
            if isinstance(sender, QCheckBox):
                sender.blockSignals(True)
                sender.setChecked(True)
                sender.blockSignals(False)
            mask = {mod for mod, box in self._boxes.items() if box.isChecked()}
        settings.set(self._key, settings.format_mask(mask))
        settings.save()


class _Row(QWidget):
    """A labelled combo row that can be filtered by the search box."""

    def __init__(self, label, combo, keywords="", parent=None):
        super().__init__(parent)
        self.keywords = (label + " " + keywords).lower()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QLabel(label)
        text.setMinimumWidth(170)
        layout.addWidget(text)
        layout.addWidget(combo, 1)
        self.combo = combo


def _combo(entry: _Row, key: str, choices: list[tuple[str, str]]):
    combo = entry.combo
    for value, label in choices:
        combo.addItem(label, value)
    current = str(settings.get(key, ""))
    index = combo.findData(current)
    if index >= 0:
        combo.setCurrentIndex(index)

    def _changed():
        settings.set(key, combo.currentData())
        settings.save()

    combo.currentIndexChanged.connect(_changed)


def _make_row(label, key, choices, keywords=""):
    combo = QComboBox()
    row = _Row(label, combo, keywords)
    _combo(row, key, choices)
    return row


_STRENGTH = [("balanced", "Balanced"), ("strong", "Strong")]
_SIZES = [
    ("original", "Original dimensions"),
    ("2560", "Longest edge 2560 px"),
    ("1920", "Longest edge 1920 px"),
    ("1280", "Longest edge 1280 px"),
]


class SettingsWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tangerine Settings")
        self.resize(560, 620)
        self.setMinimumSize(500, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        tabs.addTab(self._wheels_tab(), "Wheels")
        tabs.addTab(self._formats_tab(), "Formats")
        tabs.addTab(self._about_tab(), "About")
        tabs.addTab(self._empty_tab("Fan preview and onboarding live in the wheel itself."), "General")

    # ------------------------------------------------------------------

    def _empty_tab(self, text):
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(text)
        note.setWordWrap(True)
        note.setObjectName("dim")
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _wheels_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        intro = QLabel(
            "Hold one of these combinations while dragging files in File Explorer "
            "to open a wheel at the pointer."
        )
        intro.setWordWrap(True)
        intro.setObjectName("dim")
        layout.addWidget(intro)

        self._conversion_checks = ModifierChecks("Conversions wheel", "conversionWheelDragModifierMask")
        self._tools_checks = ModifierChecks("Tools wheel", "toolsWheelDragModifierMask")
        layout.addWidget(self._conversion_checks)
        layout.addWidget(self._tools_checks)

        sounds = QCheckBox("Sound and haptic feedback")
        sounds.setChecked(bool(settings.get("soundsAndHapticsEnabled", True)))

        def _toggle_sound(state):
            settings.set("soundsAndHapticsEnabled", bool(state))
            settings.save()

        sounds.toggled.connect(_toggle_sound)
        layout.addWidget(sounds)

        theme_row = _make_row("Fan theme", "conversionFanTheme", [("glass", "Glass"), ("solid", "Solid")])
        layout.addWidget(theme_row)

        hint = QLabel("The defaults are Shift for conversions and Alt+Shift for tools.")
        hint.setObjectName("dim")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _formats_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        search = QLineEdit()
        search.setPlaceholderText("Search conversion defaults…")
        layout.addWidget(search)

        self._rows: list[_Row] = []

        image_group = QGroupBox("Images")
        image_layout = QVBoxLayout(image_group)
        self._add_row(image_layout, "Compression preset", "defaultImageCompressionStrength", _STRENGTH, "compress jpg png quality")
        self._add_row(image_layout, "Compression size", "defaultImageCompressionSize", _SIZES, "resize dimensions pixels")
        layout.addWidget(image_group)

        video_group = QGroupBox("Videos")
        video_layout = QVBoxLayout(video_group)
        self._add_row(video_layout, "Compression preset", "defaultVideoCompressionStrength", _STRENGTH, "compress mp4 hevc bitrate")
        self._add_row(video_layout, "Compression size", "defaultVideoCompressionSize", _SIZES, "resize dimensions pixels")
        layout.addWidget(video_group)

        audio_group = QGroupBox("Audio")
        audio_layout = QVBoxLayout(audio_group)
        self._add_row(audio_layout, "Compression preset", "defaultAudioCompressionStrength", _STRENGTH, "compress mp3 m4a bitrate")
        layout.addWidget(audio_group)

        def _filter(text):
            needle = text.strip().lower()
            for row in self._rows:
                row.setVisible(not needle or needle in row.keywords)

        search.textChanged.connect(_filter)
        layout.addStretch(1)
        return page

    def _add_row(self, parent_layout, label, key, choices, keywords=""):
        row = _make_row(label, key, choices, keywords)
        parent_layout.addWidget(row)
        self._rows.append(row)

    def _about_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        title = QLabel(f"Tangerine {paths.APP_VERSION} for Windows (build {paths.APP_BUILD})")
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        blurb = QLabel(
            "A drag-to-convert companion for File Explorer, rebuilt from the macOS "
            "Tangerine interaction: hold a modifier while dragging, drop on a petal."
        )
        blurb.setWordWrap(True)
        blurb.setObjectName("dim")
        layout.addWidget(blurb)

        for name, value in (
            ("FFmpeg", ffmpeg_path() or "not found"),
            ("FFprobe", ffprobe_path() or "not found"),
            ("RAR writer", rar_path() or "not found"),
            ("RAR reader", unrar_path() or "not found"),
            ("Settings", str(paths.settings_file())),
            ("Log", str(paths.log_file())),
        ):
            row = QLabel(f"{name}: {value}")
            row.setWordWrap(True)
            row.setObjectName("dim")
            layout.addWidget(row)

        buttons = QHBoxLayout()
        folder = QPushButton("Open Settings Folder")
        folder.setProperty("flat", "true")
        folder.clicked.connect(self._open_folder)
        reset = QPushButton("Restore Defaults")
        reset.setProperty("flat", "true")
        reset.clicked.connect(self._reset)
        buttons.addWidget(folder)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _open_folder(self):
        import subprocess

        data = paths.data_dir()
        subprocess.Popen(["explorer", str(data)])

    def _reset(self):
        confirm = QMessageBox.question(
            self,
            "Restore Defaults",
            "Restore every Tangerine setting to its default value?",
        )
        if confirm != QMessageBox.Yes:
            return
        settings.update(dict(settings.DEFAULTS))
        settings.save()
        for checks in (getattr(self, "_conversion_checks", None), getattr(self, "_tools_checks", None)):
            if checks is not None:
                checks._load()
        QMessageBox.information(self, "Tangerine", "Settings restored to defaults.")


def open_settings(parent=None):
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = SettingsWindow(parent)
    _WINDOW.show()
    _WINDOW.raise_()
    _WINDOW.activateWindow()
    return _WINDOW
