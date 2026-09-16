"""Background job runner: threading + Qt signals for progress reporting."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Signal

from . import i18n
from .engines import Ctx, EngineError

log = logging.getLogger("tangerine")


class Job(QObject):
    progress = Signal(float)
    status = Signal(str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, work: Callable[[Ctx], object], parent: QObject | None = None):
        super().__init__(parent)
        self.work = work
        self.cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

    def ctx(self) -> Ctx:
        return Ctx(self.progress.emit, self.status.emit, self.cancel_event)

    def start(self) -> "Job":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def cancel(self) -> None:
        self.cancel_event.set()

    def _run(self) -> None:
        try:
            result = self.work(self.ctx())
            paths: list[Path]
            if isinstance(result, (list, tuple)):
                paths = [p for p in result if p is not None]
            elif result is None:
                paths = []
            else:
                paths = [result]
            if self.cancel_event.is_set():
                raise EngineError(i18n.tr("err.cancelled"))
            self.finished.emit(paths)
        except EngineError as exc:
            if self.cancel_event.is_set():
                self.failed.emit(i18n.tr("err.cancelled"))
            else:
                self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            log.exception("Unhandled error in job")
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def batch_ctx(job_ctx: Ctx, total: int, index: int) -> Ctx:
    """A Ctx whose progress maps file N of a batch onto the whole bar."""

    def mapped(fraction: float) -> None:
        if fraction < 0:
            job_ctx.progress(fraction)
        else:
            job_ctx.progress((index + max(0.0, min(fraction, 1.0))) / max(total, 1))

    return Ctx(mapped, job_ctx.status, job_ctx.cancel)
