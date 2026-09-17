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
from . import i18n, paths, theme

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


def _strength_choices():
    return [
        ("balanced", i18n.tr("settings.strength.balanced")),
        ("strong", i18n.tr("settings.strength.strong")),
    ]


def _size_choices():
    return [
        ("original", i18n.tr("settings.size.original")),
        ("2560", i18n.tr("settings.size.2560")),
        ("1920", i18n.tr("settings.size.1920")),
        ("1280", i18n.tr("settings.size.1280")),
    ]


class SettingsWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("settings.title"))
        self.resize(560, 620)
        self.setMinimumSize(500, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        tabs.addTab(self._wheels_tab(), i18n.tr("settings.tab.wheels"))
        tabs.addTab(self._formats_tab(), i18n.tr("settings.tab.formats"))
        tabs.addTab(self._about_tab(), i18n.tr("settings.tab.about"))
        tabs.addTab(self._general_tab(), i18n.tr("settings.tab.general"))

    # ------------------------------------------------------------------

    def _general_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        form = QFormLayout()
        self.language_combo = QComboBox()
        self.language_combo.addItem(i18n.tr("settings.language.system"), "system")
        for code, label in i18n.LANGUAGES:
            self.language_combo.addItem(label, code)
        current = str(settings.get("language", i18n.DEFAULT_LANGUAGE) or i18n.DEFAULT_LANGUAGE)
        index = self.language_combo.findData(current)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        form.addRow(i18n.tr("settings.language.label"), self.language_combo)

        self.appearance_combo = QComboBox()
        self.appearance_combo.addItem(i18n.tr("settings.appearance.system"), "system")
        self.appearance_combo.addItem(i18n.tr("settings.appearance.light"), "light")
        self.appearance_combo.addItem(i18n.tr("settings.appearance.dark"), "dark")
        index = self.appearance_combo.findData(settings.appearance_theme())
        if index >= 0:
            self.appearance_combo.setCurrentIndex(index)
        self.appearance_combo.currentIndexChanged.connect(
            lambda _index: self._appearance_changed())
        form.addRow(i18n.tr("settings.appearance.label"), self.appearance_combo)
        layout.addLayout(form)

        hint = QLabel(i18n.tr("settings.language.hint"))
        hint.setWordWrap(True)
        hint.setObjectName("dim")
        layout.addWidget(hint)

        appearance_hint = QLabel(i18n.tr("settings.appearance.hint"))
        appearance_hint.setWordWrap(True)
        appearance_hint.setObjectName("dim")
        layout.addWidget(appearance_hint)
        layout.addStretch(1)
        return page

    def _language_changed(self):
        code = self.language_combo.currentData()
        if code:
            i18n.set_language(str(code))

    def _appearance_changed(self):
        settings.set("appearanceTheme", str(self.appearance_combo.currentData()))
        settings.save()
        theme.apply_app_theme()

    def _wheels_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        intro = QLabel(i18n.tr("settings.wheels.intro"))
        intro.setWordWrap(True)
        intro.setObjectName("dim")
        layout.addWidget(intro)

        self._conversion_checks = ModifierChecks(
            i18n.tr("settings.wheels.conversions"), "conversionWheelDragModifierMask")
        self._tools_checks = ModifierChecks(
            i18n.tr("settings.wheels.tools"), "toolsWheelDragModifierMask")
        layout.addWidget(self._conversion_checks)
        layout.addWidget(self._tools_checks)

        sounds = QCheckBox(i18n.tr("settings.wheels.sound"))
        sounds.setChecked(bool(settings.get("soundsAndHapticsEnabled", True)))

        def _toggle_sound(state):
            settings.set("soundsAndHapticsEnabled", bool(state))
            settings.save()

        sounds.toggled.connect(_toggle_sound)
        layout.addWidget(sounds)

        hint = QLabel(i18n.tr("settings.wheels.hint"))
        hint.setObjectName("dim")
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _formats_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        search = QLineEdit()
        search.setPlaceholderText(i18n.tr("settings.formats.search"))
        layout.addWidget(search)

        self._rows: list[_Row] = []

        image_group = QGroupBox(i18n.tr("settings.formats.images"))
        image_layout = QVBoxLayout(image_group)
        self._add_row(image_layout, i18n.tr("settings.formats.preset"),
                      "defaultImageCompressionStrength", _strength_choices(),
                      "compress jpg png quality")
        self._add_row(image_layout, i18n.tr("settings.formats.size"),
                      "defaultImageCompressionSize", _size_choices(),
                      "resize dimensions pixels")
        layout.addWidget(image_group)

        video_group = QGroupBox(i18n.tr("settings.formats.videos"))
        video_layout = QVBoxLayout(video_group)
        self._add_row(video_layout, i18n.tr("settings.formats.preset"),
                      "defaultVideoCompressionStrength", _strength_choices(),
                      "compress mp4 hevc bitrate")
        self._add_row(video_layout, i18n.tr("settings.formats.size"),
                      "defaultVideoCompressionSize", _size_choices(),
                      "resize dimensions pixels")
        layout.addWidget(video_group)

        audio_group = QGroupBox(i18n.tr("settings.formats.audio"))
        audio_layout = QVBoxLayout(audio_group)
        self._add_row(audio_layout, i18n.tr("settings.formats.preset"),
                      "defaultAudioCompressionStrength", _strength_choices(),
                      "compress mp3 m4a bitrate")
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

        title = QLabel(i18n.tr(
            "settings.about.title",
            version=paths.APP_VERSION, build=paths.APP_BUILD,
        ))
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        blurb = QLabel(i18n.tr("settings.about.blurb"))
        blurb.setWordWrap(True)
        blurb.setObjectName("dim")
        layout.addWidget(blurb)

        not_found = i18n.tr("settings.about.not_found")
        for name, value in (
            (i18n.tr("settings.about.ffmpeg"), ffmpeg_path() or not_found),
            (i18n.tr("settings.about.ffprobe"), ffprobe_path() or not_found),
            (i18n.tr("settings.about.rar_writer"), rar_path() or not_found),
            (i18n.tr("settings.about.rar_reader"), unrar_path() or not_found),
            (i18n.tr("settings.about.settings_file"), str(paths.settings_file())),
            (i18n.tr("settings.about.log"), str(paths.log_file())),
        ):
            row = QLabel(f"{name}: {value}")
            row.setWordWrap(True)
            row.setObjectName("dim")
            layout.addWidget(row)

        buttons = QHBoxLayout()
        folder = QPushButton(i18n.tr("settings.about.open_folder"))
        folder.setProperty("flat", "true")
        folder.clicked.connect(self._open_folder)
        reset = QPushButton(i18n.tr("settings.about.restore"))
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
            i18n.tr("settings.restore.title"),
            i18n.tr("settings.restore.confirm"),
        )
        if confirm != QMessageBox.Yes:
            return
        settings.update(dict(settings.DEFAULTS))
        settings.save()
        for checks in (getattr(self, "_conversion_checks", None), getattr(self, "_tools_checks", None)):
            if checks is not None:
                checks._load()
        self._sync_language_combo()
        self._sync_appearance_combo()
        theme.apply_app_theme()
        QMessageBox.information(
            self, i18n.tr("app.name"), i18n.tr("settings.restore.done"))

    def _sync_language_combo(self):
        combo = getattr(self, "language_combo", None)
        if combo is None:
            return
        current = str(settings.get("language", i18n.DEFAULT_LANGUAGE) or i18n.DEFAULT_LANGUAGE)
        index = combo.findData(current)
        if index >= 0 and index != combo.currentIndex():
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)
        i18n.set_language(current)

    def _sync_appearance_combo(self):
        combo = getattr(self, "appearance_combo", None)
        if combo is None:
            return
        index = combo.findData(settings.appearance_theme())
        if index >= 0 and index != combo.currentIndex():
            combo.blockSignals(True)
            combo.setCurrentIndex(index)
            combo.blockSignals(False)


def open_settings(parent=None):
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = SettingsWindow(parent)
    _WINDOW.show()
    _WINDOW.raise_()
    _WINDOW.activateWindow()
    return _WINDOW
