from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import engines, i18n, settings, tools
from .jobs import Job, batch_ctx
from .progress import ProgressWindow, run_job

_COMPRESS_KEYS = {
    "img.compress": "image",
    "vid.compress": "video",
    "aud.compress": "audio",
}


def run_conversions(file_paths, target, parent=None, label=None):
    paths = [Path(p) for p in file_paths]
    if not paths:
        return None
    if label:
        title = label
    elif len(paths) == 1:
        title = i18n.tr("action.file_to", name=paths[0].name, target=target.upper())
    else:
        title = i18n.tr("action.converting_many", n=len(paths), target=target.upper())
    reserved: set[str] = set()

    def work(ctx):
        outputs = []
        total = len(paths)
        for index, path in enumerate(paths):
            fctx = batch_ctx(ctx, total, index) if total > 1 else ctx
            if total > 1:
                ctx.status(i18n.tr(
                    "action.converting_progress",
                    name=path.name, index=index + 1, total=total,
                ))
            else:
                ctx.status(i18n.tr("action.converting_file", name=path.name))
            outputs.extend(engines.convert_single(path, target, fctx, reserved))
        return outputs

    return run_job(title, work, parent)


def _clean_text(path, ctx, reserved):
    import subprocess

    source = Path(path)
    data = source.read_bytes()
    text = data.decode("utf-8", errors="replace")
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    cleaned = "\n".join(lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    out = tools._unique(source.parent, source.stem, " Clean.txt", reserved)
    ctx.status(i18n.tr("action.cleaning", name=source.name))
    out.write_text(cleaned, encoding="utf-8")
    return [out]


_DIRECT = {
    "arc.extract": ("action.extracting_archive", lambda paths, ctx, reserved: [engines.extract_archive(paths[0], ctx, reserved)]),
    "pdf.merge": ("action.merging_pdfs", lambda paths, ctx, reserved: [tools.merge_pdfs(paths, ctx, reserved)]),
    "pdf.split": ("action.splitting_pdf", lambda paths, ctx, reserved: [tools.split_pdf(paths[0], ctx, reserved)]),
    "img.pdf": ("action.creating_pdf", lambda paths, ctx, reserved: [engines.images_to_pdf(paths, ctx, reserved)]),
    "vid.removeaudio": ("action.removing_audio", lambda paths, ctx, reserved: [tools.remove_audio(paths[0], ctx, reserved)]),
    "aud.normalize": ("action.normalizing_volume", lambda paths, ctx, reserved: [tools.normalize_audio(paths[0], ctx, reserved)]),
    "txt.compress": ("action.tidying_text", lambda paths, ctx, reserved: _clean_text(paths[0], ctx, reserved)),
    "pdf.compress": ("action.compressing_pdf", lambda paths, ctx, reserved: [tools.compress_pdf(paths[0], ctx, reserved)]),
    "doc.compress": ("action.compressing_document", lambda paths, ctx, reserved: [tools.compress_document(paths[0], ctx, reserved)]),
}


def run_tool(file_paths, key, parent=None, label=None):
    paths = [Path(p) for p in file_paths]
    if not paths:
        return None

    if key == "qr.read" or key.endswith(".qr"):
        return _run_qr(paths, parent)

    entry = _DIRECT.get(key)
    if entry is not None:
        title_key, fn = entry
        reserved: set[str] = set()
        return run_job(label or i18n.tr(title_key), lambda ctx: fn(paths, ctx, reserved), parent)

    family = _COMPRESS_KEYS.get(key)
    if family is not None:
        return _lazy(parent, lambda: __import__("tangerine.editors", fromlist=["editors"]).run_compress(paths, family, parent))

    return _lazy(parent, lambda: __import__("tangerine.editors", fromlist=["editors"]).open_editor(paths, key, parent, label))


def _lazy(parent, call):
    try:
        return call()
    except ImportError:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            parent,
            i18n.tr("app.name"),
            i18n.tr("action.optional_editor_missing"),
        )
        return None


class ResultsWindow(QDialog):
    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.tr("action.qr_title"))
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        heading = QLabel(i18n.tr(
            "action.qr_results" if results else "action.qr_empty"))
        heading.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(10)

        all_text = []
        for source, where, text in results:
            card = QWidget(objectName="Card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(6)
            tag = QLabel(f"{source}" + (f" — {where}" if where else ""))
            tag.setStyleSheet("font-size: 11px; color: palette(mid);")
            body = QPlainTextEdit(text)
            body.setReadOnly(True)
            body.setFixedHeight(72)
            row = QHBoxLayout()
            row.addStretch(1)
            copy = QPushButton(i18n.tr("action.copy"))
            copy.setProperty("flat", True)
            copy.clicked.connect(lambda _=False, t=text: _copy(t))
            row.addWidget(copy)
            card_layout.addWidget(tag)
            card_layout.addWidget(body)
            card_layout.addLayout(row)
            inner_layout.addWidget(card)
            all_text.append(text)

        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        copy_all = QPushButton(i18n.tr("action.copy_all"))
        copy_all.setProperty("accent", True)
        copy_all.clicked.connect(lambda: _copy("\n".join(all_text)))
        copy_all.setEnabled(bool(all_text))
        close = QPushButton(i18n.tr("action.done"))
        close.setProperty("flat", True)
        close.clicked.connect(self.accept)
        footer.addWidget(copy_all)
        footer.addWidget(close)
        layout.addLayout(footer)


def _copy(text):
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText(text)


def _run_qr(paths, parent):
    holder = {}

    def work(ctx):
        ctx.status(i18n.tr("action.scanning_qr"))
        holder["results"] = tools.read_qr_codes(paths, ctx)
        return list(paths)

    job = Job(work, parent)
    window = ProgressWindow(i18n.tr("action.read_qr"), job, parent)
    window.show()
    job.finished.connect(lambda _results: ResultsWindow(holder.get("results", []), None).exec())
    job.start()
    return window
