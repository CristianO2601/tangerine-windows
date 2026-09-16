"""Persistent settings, mirroring the macOS app's UserDefaults keys."""

import json
import logging
import os
import threading
from typing import Any

from . import paths

log = logging.getLogger("tangerine")

DEFAULTS: dict[str, Any] = {
    "conversionWheelDragModifierMask": "shift",
    "toolsWheelDragModifierMask": "alt+shift",
    "soundsAndHapticsEnabled": True,
    "conversionFanTheme": "glass",
    "defaultImageCompressionStrength": "balanced",
    "defaultImageCompressionSize": "original",
    "defaultVideoCompressionStrength": "balanced",
    "defaultVideoCompressionSize": "original",
    "defaultAudioCompressionStrength": "balanced",
    "imageCompressionTargetEnabled": False,
    "imageCompressionTargetKB": 0,
    "collageLayout": "grid",
    "collageSpacing": 12,
    "collagePadding": 24,
    "collageCornerRadius": 12,
    "collageBackground": "white",
    "collageCellShape": "square",
    "collageResolution": "source",
    "collageFit": "fill",
    "joinVideosFPSCap": 30,
    "videoCompressionAccurate": True,
    "welcomeShown": False,
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def load() -> dict[str, Any]:
    with _lock:
        return _ensure_cache()


def _ensure_cache() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    data = dict(DEFAULTS)
    path = paths.settings_file()
    try:
        if path.exists():
            stored = json.loads(path.read_text("utf-8"))
            if isinstance(stored, dict):
                data.update(stored)
    except json.JSONDecodeError:
        log.exception("Settings file is corrupt; restoring defaults")
        try:
            os.replace(path, path.with_suffix(".json.bak"))
        except OSError:
            log.exception("Could not back up corrupt settings file")
    except Exception:
        pass
    _cache = data
    return _cache


def get(key: str, default: Any = None) -> Any:
    data = load()
    if key in data:
        return data[key]
    if default is not None:
        return default
    return DEFAULTS.get(key)


def set(key: str, value: Any) -> None:
    with _lock:
        data = _ensure_cache()
        if data.get(key) == value:
            return
        data[key] = value
        _save()


def update(values: dict[str, Any]) -> None:
    with _lock:
        data = _ensure_cache()
        changed = False
        for key, value in values.items():
            if data.get(key) != value:
                data[key] = value
                changed = True
        if changed:
            _save()


def save() -> None:
    with _lock:
        _save()


def _save() -> None:
    try:
        payload = json.dumps(_cache or DEFAULTS, indent=2, ensure_ascii=False)
        final = paths.settings_file()
        tmp = final.with_suffix(".json.tmp")
        tmp.write_text(payload, "utf-8")
        os.replace(tmp, final)
    except Exception:
        pass


MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]
MODIFIER_LABELS = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Win",
}
MODIFIER_QT = {
    "ctrl": "Control",
    "alt": "Alt",
    "shift": "Shift",
    "win": "Meta",
}


_ALIASES = {
    "control": "ctrl",
    "option": "alt",
    "cmd": "win",
    "command": "win",
    "meta": "win",
}


def parse_mask(text: str) -> set[str]:
    parts = {p.strip().lower() for p in str(text or "").split("+")}
    return {_ALIASES.get(p, p) for p in parts if _ALIASES.get(p, p) in MODIFIER_ORDER}


def format_mask(mask: set[str]) -> str:
    ordered = [m for m in MODIFIER_ORDER if m in mask]
    return "+".join(ordered)


def mask_label(text: str) -> str:
    mask = parse_mask(text)
    if not mask:
        return "None"
    return " + ".join(MODIFIER_LABELS[m] for m in MODIFIER_ORDER if m in mask)
