"""Shared pytest setup for the Tangerine test suite.

Runs Qt in offscreen mode so widget construction works without a desktop,
adds the repository root to ``sys.path`` (so ``import tangerine`` works when
pytest is invoked from anywhere) and exposes a session-scoped QApplication.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

import tempfile
from PySide6.QtCore import qInstallMessageHandler


def _qt_message_handler(mode, context, message):
    """Keep native Qt diagnostics visible when a Windows test aborts."""
    try:
        kind = getattr(mode, "name", str(mode))
        category = getattr(context, "category", "") or "default"
        source = getattr(context, "file", None)
        line = getattr(context, "line", 0)
        location = f" {source}:{line}" if source else ""
        print(f"[Qt {kind} {category}{location}] {message}", file=sys.stderr, flush=True)
    except Exception:
        # The handler must never turn a Qt diagnostic into a second failure.
        pass


qInstallMessageHandler(_qt_message_handler)

from tangerine import paths as _paths

_SETTINGS_TMP = Path(tempfile.mkdtemp(prefix="tangerine_test_settings_"))
_paths.settings_file = lambda: _SETTINGS_TMP / "settings.json"


@pytest.fixture(scope="session")
def qapp():
    """Return the process-wide QApplication, creating it on first use."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    # Qt's Windows offscreen plugin has no system font database. Load installed
    # fonts explicitly so widget rendering checks cover legible text as well.
    if sys.platform == "win32":
        from PySide6.QtGui import QFont, QFontDatabase
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
            font = fonts / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont("Segoe UI", 10))
    return app
