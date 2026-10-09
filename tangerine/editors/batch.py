"""Small helpers for editors that need one user-authored result per file."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtWidgets import QDialog, QWidget


@dataclass
class BatchEditorHandle:
    """References to progress windows started by a sequential editor batch."""

    job_windows: list[object] = field(default_factory=list)
    dialogs: list[QDialog] = field(default_factory=list)


def run_sequential_dialogs(
    paths: Iterable[Path],
    factory: Callable[[Path, QWidget | None], QDialog],
    parent: QWidget | None = None,
) -> BatchEditorHandle:
    """Show one modal editor per path, stopping when the user cancels.

    Editors such as crop, annotate, and redact collect geometry specific to
    one image. Reusing the first image's geometry for the rest would silently
    apply the wrong region, so each file gets its own editor.
    """
    handle = BatchEditorHandle()
    for path in paths:
        dialog = factory(Path(path), parent)
        handle.dialogs.append(dialog)
        exec_with_defaults = getattr(dialog, "exec_with_defaults", dialog.exec)
        if exec_with_defaults() != QDialog.DialogCode.Accepted:
            break
        job_window = getattr(dialog, "job_window", None)
        if job_window is not None:
            handle.job_windows.append(job_window)
    return handle


def exec_editor(dialog: QDialog) -> QDialog:
    """Run an editor through its opt-in settings replay hook and retain it."""
    exec_with_defaults = getattr(dialog, "exec_with_defaults", dialog.exec)
    exec_with_defaults()
    return dialog
