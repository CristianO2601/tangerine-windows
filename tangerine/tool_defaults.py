"""Validated, explicitly enabled reuse of options for non-positional tools."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import re
from pathlib import Path

from . import settings

SUPPORTED = ("img.compress", "vid.compress", "aud.compress", "img.collage", "img.background")


@lru_cache(maxsize=16)
def _readable_image(path: str, size: int, modified_ns: int) -> bool:
    # Use the same decoder as the tool; cache only a specific file revision.
    from .engines import EngineError, load_image
    try:
        image = load_image(Path(path))
        image.close()
        return True
    except (EngineError, OSError, ValueError):
        return False


def validate(key: str, value) -> dict | None:
    """Reject stale/corrupt settings instead of starting an unexpected job."""
    if key not in SUPPORTED or not isinstance(value, dict):
        return None

    def integer(name, low, high):
        item = value.get(name)
        if type(item) is not int or not low <= item <= high:
            raise ValueError(name)
        return item

    def choice(name, choices):
        item = value.get(name)
        if item not in choices:
            raise ValueError(name)
        return item

    def color(item):
        if not isinstance(item, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", item):
            raise ValueError("color")
        return item

    try:
        if key.endswith(".compress"):
            result = {"strength": choice("strength", ("balanced", "strong"))}
            if key == "img.compress":
                result["size"] = choice("size", ("original", "2560", "1920", "1280"))
                if type(value.get("target_enabled")) is not bool:
                    return None
                result.update(target_enabled=value["target_enabled"], target_kb=integer("target_kb", 1, 1024 * 1024))
            return result
        if key == "img.collage":
            return {"layout": choice("layout", ("grid", "horizontal", "vertical", "featured")),
                    "spacing": integer("spacing", 0, 96), "padding": integer("padding", 0, 160),
                    "corner_radius": integer("corner_radius", 0, 64),
                    "background": choice("background", ("white", "black", "transparent")),
                    "resolution": choice("resolution", ("source", 2000, 1500, 1080)),
                    "fit": choice("fit", ("fill", "contain"))}
        fill = value.get("fill")
        if not isinstance(fill, dict):
            return None
        kind = fill.get("type")
        if kind == "color":
            clean_fill = {"type": kind, "color": color(fill.get("color"))}
        elif kind == "gradient":
            angle = fill.get("angle")
            if type(angle) is not int or not 0 <= angle <= 360:
                return None
            clean_fill = {"type": kind, "from": color(fill.get("from")), "to": color(fill.get("to")), "angle": angle}
        elif kind == "image":
            path = fill.get("path")
            if not isinstance(path, str) or not Path(path).is_file():
                return None
            stat = Path(path).stat()
            if not _readable_image(str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns):
                return None
            clean_fill = {"type": kind, "path": path}
        else:
            return None
        return {"fill": clean_fill, "aspect": choice("aspect", ("original", "1:1", "4:3", "3:2", "16:9", "9:16")),
                "margin": integer("margin", 0, 512), "radius": integer("radius", 0, 256), "fit": "contain"}
    except (ValueError, TypeError, OSError):
        return None


def load_options(key: str) -> dict | None:
    stored = settings.get("toolDefaultOptions", {})
    return validate(key, stored.get(key)) if isinstance(stored, dict) else None


def is_enabled(key: str) -> bool:
    enabled = settings.get("toolSkipOptions", {})
    return key in SUPPORTED and isinstance(enabled, dict) and enabled.get(key) is True


def can_reuse(key: str) -> bool:
    return is_enabled(key) and load_options(key) is not None


def remember(key: str, options: dict, enabled: bool) -> None:
    clean = validate(key, options)
    if clean is None:
        raise ValueError(f"Invalid defaults for {key}")
    stored = settings.get("toolDefaultOptions", {})
    stored = deepcopy(stored) if isinstance(stored, dict) else {}
    toggles = settings.get("toolSkipOptions", {})
    toggles = dict(toggles) if isinstance(toggles, dict) else {}
    stored[key] = clean
    toggles[key] = enabled is True
    settings.update({"toolDefaultOptions": stored, "toolSkipOptions": toggles})


def set_enabled(key: str, enabled: bool) -> None:
    if key not in SUPPORTED:
        raise ValueError(key)
    toggles = settings.get("toolSkipOptions", {})
    toggles = dict(toggles) if isinstance(toggles, dict) else {}
    toggles[key] = enabled is True
    settings.set("toolSkipOptions", toggles)
