"""Routing audit as a test: every tool offered by the catalog must open its
editor or schedule its job - never fall back to a "tool not available"
message box.

The real catalog and ``actions.run_tool`` dispatch are exercised; only job
execution, dialog modal loops and message boxes are intercepted. Fixtures are
synthesized locally, so no external assets are needed and the suite passes
whether or not FFmpeg is installed (video fixtures are added only when OpenCV
can write a clip on this machine).
"""

import struct
import threading
import wave
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from tangerine import actions, catalog, editors

records: list[tuple[str, ...]] = []


def _rec(*items) -> None:
    records.append(tuple(str(item) for item in items))


class _FakeJob(QObject):
    """Signal-compatible stand-in for tangerine.jobs.Job."""

    progress = Signal(float)
    status = Signal(str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, work, parent=None):
        super().__init__(parent)
        self.work = work
        self.cancel_event = threading.Event()

    def start(self):
        _rec("QRJOB")
        return self

    def cancel(self):
        pass


class _DummyWindow:
    def __init__(self, *args, **kwargs):
        self.job = args[1] if len(args) > 1 else None

    def show(self):
        pass

    def close(self):
        pass


class _FakeResults:
    def __init__(self, results, parent=None):
        self.results = results

    def exec(self):
        _rec("RESULTS")


def _write_wav(path: Path, samples: int = 800) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(struct.pack(f"<{samples}h", *([0] * samples)))


def _write_pdf(path: Path) -> None:
    from reportlab.pdfgen import canvas as pdf_canvas

    pdf = pdf_canvas.Canvas(str(path), pagesize=(200, 200))
    pdf.drawString(24, 100, "Tangerine routing fixture")
    pdf.save()


def _write_video(path: Path) -> bool:
    """Best-effort MJPG clip; returns False when OpenCV cannot write one."""
    try:
        import cv2
        import numpy as np

        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        frame[:, :] = (0, 128, 248)
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (32, 32)
        )
        if not writer.isOpened():
            return False
        for _ in range(5):
            writer.write(frame)
        writer.release()
    except Exception:
        return False
    return path.exists() and path.stat().st_size > 0


def _fixture_sets(folder: Path) -> dict[str, list[Path]]:
    from PIL import Image

    photo = folder / "photo.jpg"
    Image.new("RGB", (32, 32), (248, 120, 0)).save(photo, "JPEG")
    logo = folder / "logo.png"
    Image.new("RGBA", (32, 32), (255, 255, 255, 160)).save(logo, "PNG")
    anim = folder / "anim.gif"
    Image.new("RGB", (32, 32), (255, 128, 0)).save(anim, "GIF")

    tone = folder / "tone.wav"
    tone2 = folder / "tone2.wav"
    _write_wav(tone)
    _write_wav(tone2, samples=1600)

    notes = folder / "notes.pdf"
    notes2 = folder / "notes2.pdf"
    _write_pdf(notes)
    _write_pdf(notes2)

    text = folder / "notes.txt"
    text.write_text("First line\n\n\n\nSecond line\n", encoding="utf-8")

    bundle = folder / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("hello.txt", "hello")

    sets = {
        "image": [photo],
        "image-multi": [photo, logo],
        "gif": [anim],
        "audio": [tone],
        "audio-multi": [tone, tone2],
        "pdf": [notes],
        "pdf-multi": [notes, notes2],
        "txt": [text],
        "archive": [bundle],
        "image-pdf-multi": [photo, notes],
    }

    if _write_video(folder / "clip1.avi") and _write_video(folder / "clip2.avi"):
        sets["video"] = [folder / "clip1.avi"]
        sets["video-multi"] = [folder / "clip1.avi", folder / "clip2.avi"]
    return sets


@pytest.fixture
def tool_sets(qapp, tmp_path, monkeypatch):
    records.clear()
    monkeypatch.setattr(
        actions, "run_job", lambda title, work, parent=None: _rec("JOB", title)
    )
    monkeypatch.setattr(actions, "Job", _FakeJob)
    monkeypatch.setattr(actions, "ProgressWindow", _DummyWindow)
    monkeypatch.setattr(actions, "ResultsWindow", _FakeResults)
    monkeypatch.setattr(
        editors.ToolDialog, "exec", lambda self: _rec("EXEC", type(self).__name__)
    )
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *args, **kwargs: _rec("INFO", *args)),
    )
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *args, **kwargs: _rec("WARN", *args)),
    )
    return _fixture_sets(tmp_path)


def test_every_offered_tool_routes(tool_sets):
    problems: list[str] = []
    total = 0

    for set_name, paths in tool_sets.items():
        tools = catalog.tools_for(paths)
        if not tools:
            problems.append(f"{set_name}: the catalog offered no tools")
            continue
        for tool in tools:
            total += 1
            before = len(records)
            try:
                actions.run_tool(
                    [str(path) for path in paths], tool.id, None, tool.label
                )
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{set_name}/{tool.id}: {type(exc).__name__}: {exc}")
                continue

            got = records[before:]
            kinds = [entry[0] for entry in got]
            if "INFO" in kinds or "WARN" in kinds:
                problems.append(f"{set_name}/{tool.id}: fallback message box {got}")
            elif tool.id in actions._COMPRESS_KEYS:
                if kinds[:1] != ["EXEC"]:
                    problems.append(
                        f"{set_name}/{tool.id}: expected a compress editor, got {got}"
                    )
            elif tool.id in actions._DIRECT:
                if kinds[:1] != ["JOB"]:
                    problems.append(
                        f"{set_name}/{tool.id}: expected a direct job, got {got}"
                    )
            elif tool.id == "qr.read" or tool.id.endswith(".qr"):
                if "QRJOB" not in kinds and "RESULTS" not in kinds:
                    problems.append(
                        f"{set_name}/{tool.id}: expected the QR flow, got {got}"
                    )
            elif kinds[:1] != ["EXEC"]:
                problems.append(
                    f"{set_name}/{tool.id}: expected an editor dialog, got {got}"
                )

    assert total >= 20, f"unexpectedly few routes exercised ({total})"
    assert not problems, "routing problems:\n" + "\n".join(problems)
