"""Filesystem locations used across Tangerine for Windows."""

import os
import sys
from pathlib import Path

APP_NAME = "Tangerine"
APP_VERSION = "1.5.0"
APP_BUILD = 5


def app_root() -> Path:
    """Directory containing the application (frozen exe or source tree)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    return app_root() / "assets"


def tools_dir() -> Path:
    return app_root() / "tools"


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return data_dir() / "settings.json"


def log_file() -> Path:
    return data_dir() / "tangerine.log"


def icon_path() -> Path:
    return assets_dir() / "tray.ico"


def icon_png() -> Path:
    return assets_dir() / "tray.png"


def highlight_sound() -> Path:
    return assets_dir() / "highlight.wav"
