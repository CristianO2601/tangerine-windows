"""Format families, conversion targets and file tools - mirrors the macOS spec."""

from dataclasses import dataclass
from pathlib import Path

from . import media

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tiff", ".tif", ".svg", ".bmp"}
RASTER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tiff", ".tif", ".bmp"}
SVG_EXTS = {".svg"}
GIF_EXTS = {".gif"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
PDF_EXTS = {".pdf"}
TXT_EXTS = {".txt"}
DOC_EXTS = {".docx", ".xlsx", ".pptx", ".csv", ".rtf", ".md", ".odt", ".epub"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".rar"}

DOC_OFFICE_EXTS = {".docx", ".xlsx", ".pptx"}

DOCX_OUT_IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
DOCX_OUT_PDF_EXTS = {".pdf"}
TXT_OUT_PDF_EXTS = {".pdf"}

IMAGE_TARGETS = ["jpg", "png", "webp", "heic", "tiff", "pdf"]
AUDIO_TARGETS = ["mp3", "m4a", "wav", "flac"]
VIDEO_TARGETS = ["mp4", "mov", "mkv", "gif", "mp3", "m4a"]
GIF_TARGETS = ["mp4", "mov", "mkv"]
ARCHIVE_TARGETS = ["zip", "tar", "gz", "rar"]
PDF_TARGETS = ["docx", "jpg", "png", "txt"]
TXT_TARGETS = ["pdf", "jpg", "png"]
IMAGE_DOC_TARGETS = ["pdf", "docx"]

DOC_CONVERSIONS = {
    ".docx": ("txt", "pdf", "jpg", "png"),
    ".xlsx": ("csv", "pdf", "jpg", "png"),
    ".pptx": ("txt", "pdf", "jpg", "png"),
    ".csv": ("xlsx", "pdf", "jpg", "png", "txt"),
    ".rtf": ("txt", "pdf", "jpg", "png"),
    ".md": ("txt", "html", "pdf", "jpg", "png"),
    ".odt": ("txt", "pdf", "jpg", "png"),
    ".epub": ("txt",),
}

DOC_READER_ENGINES = {
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".rtf": "rtf",
    ".md": "markdown",
    ".odt": "odt",
}

DOC_TARGET_ENGINES = {
    "xlsx": ("xlsx",),
    "html": ("markdown",),
    "pdf": ("reportlab",),
    "jpg": ("reportlab", "pdfium"),
    "png": ("reportlab", "pdfium"),
}

DOC_TARGET_LABELS = {
    "txt": "Text File",
    "pdf": "PDF",
    "jpg": "JPG",
    "png": "PNG",
    "csv": "CSV",
    "xlsx": "Excel",
    "html": "HTML",
}

FAMILY_IMAGE = "image"
FAMILY_GIF = "gif"
FAMILY_AUDIO = "audio"
FAMILY_VIDEO = "video"
FAMILY_PDF = "pdf"
FAMILY_TXT = "txt"
FAMILY_DOC = "doc"
FAMILY_ARCHIVE = "archive"


@dataclass(frozen=True)
class Conversion:
    id: str
    label: str
    target_ext: str
    engine: str
    family: str


@dataclass(frozen=True)
class Tool:
    id: str
    label: str
    family: str
    batch: bool = False
    engines: tuple[str, ...] = ()


def family_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in RASTER_EXTS or ext in SVG_EXTS:
        return FAMILY_IMAGE
    if ext in GIF_EXTS:
        return FAMILY_GIF
    if ext in AUDIO_EXTS:
        return FAMILY_AUDIO
    if ext in VIDEO_EXTS:
        return FAMILY_VIDEO
    if ext in PDF_EXTS:
        return FAMILY_PDF
    if ext in TXT_EXTS:
        return FAMILY_TXT
    if ext in DOC_EXTS:
        return FAMILY_DOC
    if ext in ARCHIVE_EXTS:
        return FAMILY_ARCHIVE
    return None


def is_archive(name: str) -> bool:
    return Path(name).suffix.lower() in ARCHIVE_EXTS


_ENGINES: set[str] | None = None


def available_engines() -> set[str]:
    global _ENGINES
    if _ENGINES is not None:
        return _ENGINES
    engines = set()
    try:
        import PIL  # noqa: F401
        engines.add("pillow")
    except Exception:
        pass
    try:
        import pillow_heif  # noqa: F401
        engines.add("heic")
    except Exception:
        pass
    try:
        import pypdfium2  # noqa: F401
        engines.add("pdfium")
    except Exception:
        pass
    try:
        import pypdf  # noqa: F401
        engines.add("pypdf")
    except Exception:
        pass
    try:
        import docx  # noqa: F401
        engines.add("docx")
    except Exception:
        pass
    try:
        import openpyxl  # noqa: F401
        engines.add("xlsx")
    except Exception:
        pass
    try:
        import pptx  # noqa: F401
        engines.add("pptx")
    except Exception:
        pass
    try:
        import striprtf  # noqa: F401
        engines.add("rtf")
    except Exception:
        pass
    try:
        import odf  # noqa: F401
        engines.add("odt")
    except Exception:
        pass
    try:
        import markdown  # noqa: F401
        engines.add("markdown")
    except Exception:
        pass
    try:
        import reportlab  # noqa: F401
        engines.add("reportlab")
    except Exception:
        pass
    try:
        import cv2  # noqa: F401
        engines.add("qr")
    except Exception:
        pass
    if media.ffmpeg_path():
        engines.add("ffmpeg")
    if media.unrar_path():
        engines.add("unrar")
    if media.rar_path():
        engines.add("rar")
    _ENGINES = engines
    return engines


def _conversion(ext: str, target: str, family: str) -> Conversion | None:
    engines = available_engines()
    if target in ("jpg", "png", "tiff", "webp"):
        if "pillow" not in engines:
            return None
    if target == "heic" and "heic" not in engines:
        return None
    if target == "pdf":
        if family in (FAMILY_IMAGE, FAMILY_TXT) and "pdfium" not in engines and "pillow" not in engines:
            return None
    if target == "docx" and "docx" not in engines:
        return None
    if target == "txt" and "pypdf" not in engines:
        return None
    if target in ("mp3", "m4a", "wav", "flac", "mp4", "mov", "mkv", "gif") and "ffmpeg" not in engines:
        return None
    if target == "rar" and "rar" not in engines:
        return None
    return Conversion(
        id=f"conv:{ext}:{target}",
        label=target.upper(),
        target_ext=target,
        engine="engine",
        family=family,
    )


def _doc_conversion(source_ext: str, target: str, family: str) -> Conversion | None:
    """A document conversion, offered only when reader and writer can run."""
    engines = available_engines()
    reader = DOC_READER_ENGINES.get(source_ext)
    if reader and reader not in engines:
        return None
    if not set(DOC_TARGET_ENGINES.get(target, ())) <= engines:
        return None
    return Conversion(
        id=f"conv:{source_ext.lstrip('.')}:{target}",
        label=DOC_TARGET_LABELS.get(target, target.upper()),
        target_ext=target,
        engine="engine",
        family=family,
    )


def conversions_for(paths_: list[Path]) -> list[Conversion]:
    """Output-format targets offered for the given source selection."""
    if not paths_:
        return []
    families = {family_of(p) for p in paths_}
    if len(families) != 1:
        return []
    family = families.pop()
    if family is None:
        return []
    exts = {p.suffix.lower().lstrip(".") for p in paths_}
    results: list[Conversion] = []
    if family == FAMILY_IMAGE:
        has_svg = bool(exts & {e.lstrip(".") for e in SVG_EXTS})
        targets = list(IMAGE_TARGETS)
        if not has_svg:
            targets.append("docx")
        for target in targets:
            if target.lstrip(".") in exts and not has_svg:
                continue
            if target == "heic" and exts == {"heic"}:
                continue
            conv = _conversion("image", target, family)
            if conv:
                results.append(conv)
    elif family == FAMILY_AUDIO:
        for target in AUDIO_TARGETS:
            if target in exts:
                continue
            conv = _conversion("audio", target, family)
            if conv:
                results.append(conv)
    elif family == FAMILY_VIDEO:
        for target in VIDEO_TARGETS:
            if target in exts:
                continue
            conv = _conversion("video", target, family)
            if conv:
                results.append(conv)
    elif family == FAMILY_GIF:
        for target in GIF_TARGETS:
            conv = _conversion("gif", target, family)
            if conv:
                results.append(conv)
    elif family == FAMILY_PDF:
        for target in PDF_TARGETS:
            conv = _conversion("pdf", target, family)
            if conv:
                results.append(conv)
    elif family == FAMILY_TXT:
        for target in TXT_TARGETS:
            conv = _conversion("txt", target, family)
            if conv:
                results.append(conv)
    elif family == FAMILY_DOC:
        source_exts = [p.suffix.lower() for p in paths_]
        for target in DOC_CONVERSIONS.get(source_exts[0], ()):
            if any(target not in DOC_CONVERSIONS.get(ext, ()) for ext in source_exts):
                continue
            conv = None
            for ext in source_exts:
                conv = _doc_conversion(ext, target, family)
                if conv is None:
                    break
            if conv:
                results.append(conv)
    elif family == FAMILY_ARCHIVE:
        for target in ARCHIVE_TARGETS:
            if exts == {target}:
                continue
            conv = _conversion("archive", target, family)
            if conv:
                results.append(conv)
    return results


IMAGE_TOOLS = [
    Tool("img.compress", "Compress", FAMILY_IMAGE, batch=True),
    Tool("img.metadata", "Metadata", FAMILY_IMAGE),
    Tool("img.edit", "Edit Photo", FAMILY_IMAGE),
    Tool("img.annotate", "Annotate Photo", FAMILY_IMAGE),
    Tool("img.background", "Add Background", FAMILY_IMAGE),
    Tool("img.crop", "Crop", FAMILY_IMAGE),
    Tool("img.redact", "Redact Photo", FAMILY_IMAGE),
    Tool("img.pdf", "Create PDF", FAMILY_IMAGE, batch=True),
    Tool("img.collage", "Create Collage", FAMILY_IMAGE, batch=True),
]
AUDIO_TOOLS = [
    Tool("aud.compress", "Compress", FAMILY_AUDIO, batch=True),
    Tool("aud.metadata", "Metadata", FAMILY_AUDIO),
    Tool("aud.normalize", "Normalize Volume", FAMILY_AUDIO),
    Tool("aud.visualizer", "Audio Visualizer", FAMILY_AUDIO),
    Tool("aud.trim", "Trim Audio", FAMILY_AUDIO),
    Tool("aud.channels", "Convert Audio Channels", FAMILY_AUDIO),
    Tool("aud.bleep", "Bleep Audio", FAMILY_AUDIO),
]
VIDEO_TOOLS = [
    Tool("vid.compress", "Compress", FAMILY_VIDEO, batch=True),
    Tool("vid.metadata", "Metadata", FAMILY_VIDEO),
    Tool("vid.removeaudio", "Remove Audio", FAMILY_VIDEO),
    Tool("vid.trim", "Trim", FAMILY_VIDEO),
    Tool("vid.crop", "Crop", FAMILY_VIDEO),
    Tool("vid.speed", "Change Speed", FAMILY_VIDEO),
    Tool("vid.snapshots", "Snapshots", FAMILY_VIDEO),
    Tool("vid.split", "Split Video", FAMILY_VIDEO),
    Tool("vid.redact", "Redact Video", FAMILY_VIDEO),
    Tool("vid.join", "Join Videos", FAMILY_VIDEO, batch=True),
]
GIF_TOOLS = [
    Tool("gif.metadata", "Metadata", FAMILY_GIF),
]
PDF_TOOLS = [
    Tool("pdf.compress", "Compress", FAMILY_PDF),
    Tool("pdf.metadata", "Metadata", FAMILY_PDF),
    Tool("pdf.split", "Split PDF", FAMILY_PDF),
    Tool("pdf.qr", "Read QR Codes", FAMILY_PDF),
    Tool("pdf.merge", "Merge into one PDF", FAMILY_PDF, batch=True),
]
ARCHIVE_TOOLS = [Tool("arc.extract", "Extract", FAMILY_ARCHIVE)]
DOC_TOOLS = [Tool("doc.compress", "Compress", FAMILY_DOC)]
NO_OP = [Tool("qr.read", "Read QR Codes", FAMILY_IMAGE, batch=True)]


def tools_for(paths_: list[Path]) -> list[Tool]:
    """File tools offered for the given source selection (including batches)."""
    if not paths_:
        return []
    families = [family_of(p) for p in paths_]
    if any(f is None for f in families):
        return []
    unique = set(families)
    engines = available_engines()

    def filt(tools: list[Tool]) -> list[Tool]:
        out = []
        for tool in tools:
            if tool.engines and not set(tool.engines) <= engines:
                continue
            out.append(tool)
        return out

    if len(paths_) > 1:
        if unique == {FAMILY_IMAGE}:
            return filt([
                Tool("img.compress", "Compress", FAMILY_IMAGE, batch=True),
                Tool("img.pdf", "Create PDF", FAMILY_IMAGE, batch=True),
                Tool("img.collage", "Create Collage", FAMILY_IMAGE, batch=True),
                Tool("qr.read", "Read QR Codes", FAMILY_IMAGE, batch=True),
            ])
        if unique == {FAMILY_VIDEO}:
            return filt([t for t in VIDEO_TOOLS if t.id == "vid.join"])
        if unique == {FAMILY_PDF}:
            return filt([t for t in PDF_TOOLS if t.id == "pdf.merge"])
        if unique == {FAMILY_AUDIO}:
            return filt([t for t in AUDIO_TOOLS if t.id == "aud.compress"])
        if unique <= {FAMILY_IMAGE, FAMILY_PDF}:
            return filt([Tool("qr.read", "Read QR Codes", FAMILY_PDF, batch=True)])
        return []
    family = families[0]
    if family == FAMILY_IMAGE:
        path = paths_[0]
        tools = list(IMAGE_TOOLS)
        if path.suffix.lower() in SVG_EXTS:
            tools = [t for t in tools if t.id in ("img.pdf", "img.crop", "img.background")]
        if path.suffix.lower() in (".bmp",):
            tools = [t for t in tools if t.id not in ("img.metadata",)]
        tools.append(Tool("qr.read", "Read QR Codes", FAMILY_IMAGE))
        return filt(tools)
    if family == FAMILY_GIF:
        return filt(GIF_TOOLS + [Tool("qr.read", "Read QR Codes", FAMILY_GIF)])
    if family == FAMILY_AUDIO:
        return filt(AUDIO_TOOLS)
    if family == FAMILY_VIDEO:
        return filt(VIDEO_TOOLS)
    if family == FAMILY_PDF:
        return filt(PDF_TOOLS)
    if family == FAMILY_TXT:
        return filt([Tool("txt.compress", "Compress", FAMILY_TXT)])
    if family == FAMILY_DOC:
        if paths_[0].suffix.lower() in DOC_OFFICE_EXTS:
            return filt(DOC_TOOLS)
        return []
    if family == FAMILY_ARCHIVE:
        return filt(ARCHIVE_TOOLS)
    return []


BATCH_TOOL_IDS = {"img.compress", "img.pdf", "img.collage", "aud.compress", "vid.compress", "vid.join", "pdf.merge"}
