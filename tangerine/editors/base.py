"""Shared dialog scaffolding and small conversion helpers for tool editors."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import jobs, progress


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def pil_to_qimage(img) -> QImage:
    rgba = img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(
        data, rgba.width, rgba.height, rgba.width * 4,
        QImage.Format.Format_RGBA8888,
    )
    return qimage.copy()


def pil_to_pixmap(img, max_w: int, max_h: int) -> QPixmap:
    preview = img.copy()
    preview.thumbnail((max_w, max_h))
    return QPixmap.fromImage(pil_to_qimage(preview))


def run_batch(paths, run_one, title=None) -> None:
    paths = [Path(p) for p in paths]

    def work(ctx):
        reserved: set[Path] = set()
        outputs = []
        total = len(paths)
        for index, path in enumerate(paths):
            sub = jobs.batch_ctx(ctx, total, index) if total > 1 else ctx
            result = run_one(path, sub, reserved)
            if isinstance(result, list):
                outputs.extend(result)
            elif result is not None:
                outputs.append(result)
        return outputs

    if title is None:
        title = (
            f"Working on {paths[0].name}" if len(paths) == 1
            else f"Working on {len(paths)} files"
        )
    progress.run_job(title, work)


class ToolDialog(QDialog):
    """Base dialog with a body layout and a standard button row."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(18, 16, 18, 16)
        self._body.setSpacing(12)

    def add_buttons(self, ok_text: str) -> QPushButton:
        box = QDialogButtonBox()
        ok = box.addButton(ok_text, QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setProperty("accent", True)
        cancel = box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        ok.clicked.connect(self._accept_clicked)
        cancel.clicked.connect(self.reject)
        self._body.addWidget(box)
        self._ok_button = ok
        return ok

    def _accept_clicked(self) -> None:
        self.accept()

    def save_defaults(self) -> None:
        pass
