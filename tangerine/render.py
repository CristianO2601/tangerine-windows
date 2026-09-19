"""Faithful HTML rendering through QtWebEngine (v1.8).

Conversions run on worker threads (``jobs.Job``), but Chromium only renders
on the GUI thread: :func:`html_to_pdf` hands the markup to a renderer object
that lives there, waits for ``pdfPrintingFinished`` and reports back, so the
old reportlab text dumps stay only as a fallback.

The builders (markdown, docx, xlsx, csv) are pure Python and can be tested
without WebEngine; ``ensure_ready`` must run once from the GUI thread.
"""

from __future__ import annotations

import csv as _csv
import html as _html
import importlib.util
import threading
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, QUrl, Signal

RENDER_TIMEOUT_S = 60.0

_PAGE_CSS = """
@page { size: A4; margin: 18mm 16mm; }
html, body { margin: 0; padding: 0; }
body { font-family: Georgia, 'Times New Roman', serif; font-size: 11pt;
       line-height: 1.5; color: #1f2328; }
h1, h2, h3, h4 { font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.25;
                 margin: 1.2em 0 0.5em; }
h1 { font-size: 20pt; border-bottom: 1px solid #d0d7de; padding-bottom: 0.2em; }
h2 { font-size: 15pt; }
h3 { font-size: 13pt; }
p { margin: 0.5em 0; }
a { color: #0969da; text-decoration: none; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 9.5pt;
       background: #f6f8fa; padding: 0 0.2em; border-radius: 3px; }
pre { font-family: Consolas, 'Courier New', monospace; font-size: 9.5pt;
      background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
      padding: 0.7em; white-space: pre-wrap; word-wrap: break-word; }
pre code { background: none; padding: 0; }
blockquote { margin: 0.6em 0; padding: 0 0.9em; border-left: 3px solid #d0d7de;
             color: #57606a; }
table { border-collapse: collapse; width: 100%; margin: 0.7em 0; font-size: 10pt; }
th, td { border: 1px solid #d0d7de; padding: 0.35em 0.55em; text-align: left;
         vertical-align: top; }
th { background: #f6f8fa; }
img { max-width: 100%; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 1.2em 0; }
li { margin: 0.15em 0; }
h1, h2, h3 { page-break-after: avoid; }
table, pre, blockquote, img { page-break-inside: avoid; }
"""


@lru_cache(maxsize=1)
def _pygments_css() -> str:
    try:
        from pygments.formatters import HtmlFormatter
    except Exception:
        return ""
    return HtmlFormatter().get_style_defs(".codehilite")


def _document(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_html.escape(title)}</title>"
        f"<style>{_PAGE_CSS}{_pygments_css()}</style></head>"
        f"<body>{body}</body></html>"
    )


def _title_from_markdown(source: str, fallback: str) -> str:
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def markdown_to_html(source: str, title: str = "") -> str:
    """Render CommonMark/GFM (tables, footnotes, codehilite) to full HTML."""
    import markdown

    body = markdown.markdown(
        source,
        extensions=["extra", "sane_lists", "codehilite"],
        extension_configs={"codehilite": {"guess_lang": False}},
    )
    return _document(title or _title_from_markdown(source, "Document"), body)


def docx_to_html(path: Path, title: str = "") -> str:
    """Semantic DOCX rendering through mammoth (images embed as data URIs)."""
    import mammoth

    with open(path, "rb") as handle:
        body = mammoth.convert_to_html(handle).value
    return _document(title or Path(path).stem, body)


def xlsx_to_html(path: Path, title: str = "") -> str:
    """Spreadsheet rendering through xlsx2html (styles, merged cells)."""
    from xlsx2html import xlsx2html

    stream = xlsx2html(str(path))
    body = stream.getvalue() if hasattr(stream, "getvalue") else str(stream)
    return _document(title or Path(path).stem, body)


def table_to_html(rows: list[list[str]]) -> str:
    if not rows:
        return "<p></p>"
    head, *rest = rows
    head_cells = "".join(f"<th>{_html.escape(cell)}</th>" for cell in head)
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{_html.escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rest
    )
    return f"<table><thead><tr>{head_cells}</tr></thead><tbody>{body_rows}</tbody></table>"


def csv_to_html(path: Path, title: str = "") -> str:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        rows = [row for row in _csv.reader(handle)]
    return _document(title or Path(path).stem, table_to_html(rows))


class _RenderJob:
    __slots__ = ("html", "out", "done", "success")

    def __init__(self, html: str, out: Path) -> None:
        self.html = html
        self.out = out
        self.done = threading.Event()
        self.success = False


class _WebEngineRenderer(QObject):
    """Lives on the GUI thread; workers submit jobs through the signal."""

    _request = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._page = None
        self._request.connect(self._render, Qt.ConnectionType.QueuedConnection)

    def render(self, html: str, out: Path) -> bool:
        job = _RenderJob(html, out)
        with self._lock:
            self._request.emit(job)
            if not job.done.wait(RENDER_TIMEOUT_S):
                return False
            return job.success

    def _render(self, job: _RenderJob) -> None:
        try:
            from PySide6.QtWebEngineCore import QWebEnginePage
        except Exception:
            job.done.set()
            return
        page = QWebEnginePage()
        self._page = page
        loop = QEventLoop()
        state = {"done": False, "success": False}

        def finish() -> None:
            if not state["done"]:
                state["done"] = True
                loop.quit()

        def on_pdf(path: str, success: bool) -> None:
            state["success"] = bool(success) and Path(path) == Path(job.out)
            finish()

        def on_load(ok: bool) -> None:
            if not ok:
                finish()
                return
            page.pdfPrintingFinished.connect(on_pdf)
            page.printToPdf(str(job.out))
            QTimer.singleShot(45000, finish)

        page.loadFinished.connect(on_load)
        page.setHtml(job.html, QUrl("about:blank"))
        QTimer.singleShot(30000, finish)
        loop.exec()
        self._page = None
        job.success = state["success"]
        job.done.set()


_renderer: _WebEngineRenderer | None = None
_ready_lock = threading.Lock()


def ensure_ready() -> bool:
    """Create the renderer; must be called once from the GUI thread."""
    global _renderer
    with _ready_lock:
        if _renderer is not None:
            return True
        if importlib.util.find_spec("PySide6.QtWebEngineCore") is None:
            return False
        try:
            _renderer = _WebEngineRenderer()
        except Exception:
            _renderer = None
            return False
        return True


def available() -> bool:
    if _renderer is not None:
        return True
    return importlib.util.find_spec("PySide6.QtWebEngineCore") is not None


def html_to_pdf(html: str, out: Path) -> bool:
    """Render markup to PDF on the GUI thread; False means "use fallback"."""
    renderer = _renderer
    if renderer is None:
        return False
    return renderer.render(html, Path(out))
