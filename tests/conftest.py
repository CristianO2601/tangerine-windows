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
    return app
