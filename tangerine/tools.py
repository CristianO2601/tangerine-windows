"""File tool implementations: compress, metadata, crop, redact, collage,
audio/video editors, PDF split/merge, QR reading."""

from __future__ import annotations

import io
import math
import os
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import naming
from .engines import CODEC_ARGS, Ctx, EngineError, _finish_ffmpeg, load_image, verify_writable, _flatten
from .media import probe, probe_duration_seconds, run_ffmpeg


def _unique(folder: Path, stem: str, suffix: str, reserved: set[Path]) -> Path:
    return naming.unique_path(folder, stem, suffix, reserved)


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------

def compress_image(
    path: Path, strength: str, max_edge: int | None, target_bytes: int | None,
    ctx: Ctx, reserved: set[Path],
) -> Path:
    verify_writable(path)
    ctx.status(f"Compressing {path.name}")
    original_size = path.stat().st_size
    img = load_image(path)
    if img.getexif().get(274, 1) != 1:
        img = ImageOps.exif_transpose(img)
    ext = path.suffix.lower()
    if max_edge and max(img.size) > max_edge:
        ratio = max_edge / max(img.size)
        img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))), Image.LANCZOS)

    if target_bytes:
        saving_target = target_bytes
    else:
        fraction = 0.5 if strength == "strong" else 0.2
        saving_target = int(original_size * (1 - fraction))
    min_ratio = 0.8

    out_path = _unique(path.parent, path.stem, ext, reserved)
    best: bytes | None = None

    if ext in (".jpg", ".jpeg"):
        rgb = _flatten(img) if img.mode != "RGB" else img
        floor = 30 if strength == "strong" else 40
        quality = 92
        buffer = io.BytesIO()
        while quality >= floor:
            buffer.seek(0)
            buffer.truncate(0)
            rgb.save(buffer, "JPEG", quality=quality, optimize=True, progressive=True)
            data = buffer.getvalue()
            if best is None or len(data) < len(best):
                if target_bytes and len(data) <= target_bytes or (
                    not target_bytes and len(data) <= saving_target
                ):
                    best = data
                    break
                best = data
            quality -= 6
        candidate = best or b""
        if candidate and len(candidate) >= original_size * min_ratio and not target_bytes:
            candidate = b""
        if not candidate or len(candidate) >= original_size:
            shutil.copy2(path, out_path)
            ctx.progress(1.0)
            return out_path
        out_path.write_bytes(candidate)
        ctx.progress(1.0)
        return out_path

    if ext == ".png":
        rgb = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, "PNG", optimize=True, compress_level=9)
        lossless = buffer.getvalue()
        best = lossless if len(lossless) < original_size else None
        needs_target = target_bytes or (best is None) or (
            not target_bytes and len(lossless) > saving_target
        )
        if needs_target:
            delta = 4 if strength == "strong" else 2
            step = delta * 2 + 1
            table = [min(255, max(0, (value // step) * step)) for value in range(256)]
            bands = list(rgb.split())
            for index in range(len(bands)):
                if rgb.mode == "RGBA" and index == len(bands) - 1:
                    continue
                bands[index] = bands[index].point(table)
            reduced = Image.merge(rgb.mode, bands)
            buffer.seek(0)
            buffer.truncate(0)
            reduced.save(buffer, "PNG", optimize=True, compress_level=9)
            data = buffer.getvalue()
            if best is None or len(data) < len(best):
                best = data
        if not best or len(best) >= original_size:
            shutil.copy2(path, out_path)
            ctx.progress(1.0)
            return out_path
        out_path.write_bytes(best)
        ctx.progress(1.0)
        return out_path

    if ext in (".tiff", ".tif"):
        buffer = io.BytesIO()
        img.save(buffer, "TIFF", compression="tiff_lzw")
        data = buffer.getvalue()
        if len(data) < original_size:
            out_path.write_bytes(data)
        else:
            shutil.copy2(path, out_path)
        ctx.progress(1.0)
        return out_path

    if ext == ".webp":
        rgb = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
        quality = 85 if strength == "strong" else 92
        buffer = io.BytesIO()
        rgb.save(buffer, "WEBP", quality=quality, method=6)
        data = buffer.getvalue()
        if len(data) < original_size:
            out_path.write_bytes(data)
        else:
            shutil.copy2(path, out_path)
        ctx.progress(1.0)
        return out_path

    if ext in (".heic", ".heif"):
        rgb = img.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, "HEIF", quality=60 if strength == "strong" else 80)
        data = buffer.getvalue()
        if len(data) < original_size:
            out_path.write_bytes(data)
        else:
            shutil.copy2(path, out_path)
        ctx.progress(1.0)
        return out_path

    shutil.copy2(path, out_path)
    ctx.progress(1.0)
    return out_path


def compress_video(path: Path, strength: str, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    info = probe(path)
    ctx.status(f"Compressing {path.name}")
    original_size = path.stat().st_size
    source_bitrate = info.video_bit_rate() or 2_000_000
    factor = 0.5 if strength == "strong" else 0.8
    target = max(int(source_bitrate * factor), 150_000)
    video = info.video()
    height_cap = 1080 if strength == "strong" else None
    args = ["-i", str(path)]
    filters = []
    if height_cap and video and video.height > height_cap:
        filters.append(f"scale=-2:{height_cap}")
    filters.append("format=yuv420p")
    args += ["-vf", ",".join(filters)]
    if info.video() and info.video().codec == "hevc":
        args += ["-c:v", "libx265", "-b:v", str(target), "-preset", "veryfast"]
    else:
        args += [
            "-c:v", "libx264", "-b:v", str(target),
            "-maxrate", str(int(target * 1.5)), "-bufsize", str(int(target * 3)),
            "-preset", "veryfast",
        ]
    audio = info.audio()
    if audio and audio.codec == "aac":
        args += ["-c:a", "copy"]
    elif audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    else:
        args += ["-an"]
    out_path = _unique(path.parent, path.stem, path.suffix, reserved)
    args += [str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    if code == -9:
        _finish_ffmpeg(code, out_path)
    if code != 0 or not out_path.exists():
        raise EngineError("FFmpeg could not compress this video.")
    if out_path.stat().st_size >= original_size:
        shutil.copy2(path, out_path)
    return out_path


def compress_document(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    """Rebuild an Office (ZIP) container at maximum deflate.

    Word, Excel and PowerPoint files are ZIP archives, so recompressing every
    member with level-9 deflate usually shaves a little size. When the rebuilt
    container is not smaller, the original bytes are copied instead.
    """
    verify_writable(path)
    if path.suffix.lower() not in (".docx", ".xlsx", ".pptx"):
        raise EngineError("Only Word, Excel, and PowerPoint files can be compressed.")
    ctx.status(f"Compressing {path.name}")
    original_size = path.stat().st_size
    buffer = io.BytesIO()
    with zipfile.ZipFile(path) as source:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for info in source.infolist():
                if ctx.cancelled():
                    raise EngineError("Cancelled.")
                target.writestr(
                    info, source.read(info.filename),
                    compress_type=zipfile.ZIP_DEFLATED, compresslevel=9,
                )
    data = buffer.getvalue()
    out_path = _unique(
        path.parent,
        naming.tailored_name(path, "Compressed", ""),
        path.suffix.lower(),
        reserved,
    )
    if len(data) < original_size:
        out_path.write_bytes(data)
    else:
        shutil.copy2(path, out_path)
    ctx.progress(1.0)
    return out_path


def compress_audio(path: Path, strength: str, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    info = probe(path)
    ctx.status(f"Compressing {path.name}")
    original_size = path.stat().st_size
    source_bitrate = (info.audio().bit_rate if info.audio() and info.audio().bit_rate else 192_000)
    factor = 0.5 if strength == "strong" else 0.8
    target = max(int(source_bitrate * factor), 64_000)
    ext = path.suffix.lower()
    codec = audio_codec_args(ext)
    if ext in (".mp3", ".m4a"):
        codec = [*codec[:2], "-b:a", str(target)]
    args = ["-i", str(path), "-vn", *codec]
    out_path = _unique(path.parent, path.stem, ext, reserved)
    args += [str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    if code == -9:
        _finish_ffmpeg(code, out_path)
    if code != 0 or not out_path.exists():
        raise EngineError("FFmpeg could not compress this audio file.")
    if out_path.stat().st_size >= original_size:
        shutil.copy2(path, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

EXIF_TAGS = {
    270: "ImageDescription",
    271: "Make",
    272: "Model",
    305: "Software",
    306: "DateTime",
    315: "Artist",
    33432: "Copyright",
    36867: "DateTimeOriginal",
    36868: "DateTimeDigitized",
    40094: "LensSpecification",
    42036: "LensModel",
}

EXIF_SUB_TAGS = {36867, 36868, 40094, 42036}


def read_metadata(path: Path) -> list[tuple[str, str]]:
    ext = path.suffix.lower()
    rows: list[tuple[str, str]] = []
    if ext in (".jpg", ".jpeg", ".tiff", ".tif", ".png", ".webp", ".heic", ".heif"):
        try:
            img = Image.open(path)
            exif = img.getexif()
            values = dict(exif)
            try:
                values.update(exif.get_ifd(0x8769))
            except Exception:
                pass
            for tag in sorted(values):
                name = EXIF_TAGS.get(tag)
                value = values[tag]
                if name is None:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace").strip("\x00")
                rows.append((name, str(value)))
        except Exception:
            pass
    else:
        info = probe(path)
        if info.duration:
            rows.append(("Duration", f"{info.duration:.2f} s"))
        if info.bit_rate:
            rows.append(("Overall bitrate", f"{info.bit_rate / 1000:.0f} kbps"))
        video = info.video()
        if video:
            rows.append(("Video codec", video.codec))
            if video.width:
                rows.append(("Dimensions", f"{video.width} x {video.height}"))
            if video.fps:
                rows.append(("Frame rate", f"{video.fps:.3f} fps"))
        audio = info.audio()
        if audio:
            rows.append(("Audio codec", audio.codec))
            if audio.channels:
                rows.append(("Channels", str(audio.channels)))
            if audio.sample_rate:
                rows.append(("Sample rate", f"{audio.sample_rate} Hz"))
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            meta = PdfReader(str(path)).metadata
            if meta:
                for key, value in meta.items():
                    rows.append((str(key).lstrip("/"), str(value)))
        except Exception:
            pass
    return rows


def write_metadata_image(path: Path, fields: dict[int, str], strip_all: bool, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Writing metadata for {path.name}")
    img = Image.open(path)
    exif = Image.Exif()
    if not strip_all:
        try:
            source = img.getexif()
            for tag in source:
                if tag in (34665, 34853) or tag in fields:
                    continue
                if tag not in EXIF_TAGS and not isinstance(source[tag], (bytes, str, int)):
                    continue
                try:
                    if tag in EXIF_SUB_TAGS:
                        exif.get_ifd(0x8769)[tag] = source[tag]
                    else:
                        exif[tag] = source[tag]
                except Exception:
                    pass
            try:
                for tag, value in source.get_ifd(0x8769).items():
                    if tag in fields:
                        continue
                    try:
                        exif.get_ifd(0x8769)[tag] = value
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass
    for tag, value in fields.items():
        if value:
            if tag in EXIF_SUB_TAGS:
                exif.get_ifd(0x8769)[tag] = value
            else:
                exif[tag] = value
    out_path = _unique(path.parent, f"{path.stem} Metadata", path.suffix, reserved)
    fmt = img.format or None
    save_kwargs: dict = {}
    if path.suffix.lower() in (".jpg", ".jpeg"):
        fmt = "JPEG"
        save_kwargs = {"quality": 95, "optimize": True}
        img = _flatten(img) if img.mode not in ("RGB", "L") else img
    elif path.suffix.lower() == ".png":
        fmt = "PNG"
    elif path.suffix.lower() in (".tiff", ".tif"):
        fmt = "TIFF"
    elif path.suffix.lower() == ".webp":
        fmt = "WEBP"
        save_kwargs = {"quality": 95}
    elif path.suffix.lower() in (".heic", ".heif"):
        fmt = "HEIF"
        save_kwargs = {"quality": 95}
    payload = exif.tobytes() if len(exif) or exif.get_ifd(0x8769) else None
    if payload and fmt in ("JPEG", "PNG", "TIFF", "WEBP", "HEIF"):
        save_kwargs["exif"] = payload
    img.save(out_path, fmt, **save_kwargs)
    ctx.progress(1.0)
    return out_path


def strip_metadata(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Removing metadata from {path.name}")
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif"):
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        out_path = _unique(path.parent, f"{path.stem} Clean", ext, reserved)
        kwargs: dict = {}
        if ext in (".jpg", ".jpeg"):
            fmt = "JPEG"
            img = _flatten(img) if img.mode not in ("RGB", "L") else img
            kwargs = {"quality": 95, "optimize": True}
        elif ext == ".png":
            fmt = "PNG"
        elif ext in (".tiff", ".tif"):
            fmt = "TIFF"
        elif ext == ".webp":
            fmt = "WEBP"
            kwargs = {"quality": 95}
        elif ext in (".heic", ".heif"):
            fmt = "HEIF"
            kwargs = {"quality": 95}
        img.save(out_path, fmt, **kwargs)
        ctx.progress(1.0)
        return out_path
    info = probe(path)
    out_path = _unique(path.parent, f"{path.stem} Clean", path.suffix, reserved)
    args = ["-i", str(path), "-map_metadata", "-1", "-c", "copy", str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Image editing
# ---------------------------------------------------------------------------

def crop_image(path: Path, box: tuple[int, int, int, int], ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Cropping {path.name}")
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    left, top, right, bottom = box
    left = max(0, min(left, img.width - 1))
    top = max(0, min(top, img.height - 1))
    right = max(left + 1, min(right, img.width))
    bottom = max(top + 1, min(bottom, img.height))
    cropped = img.crop((left, top, right, bottom))
    out_path = _unique(path.parent, f"{path.stem} Cropped", path.suffix, reserved)
    cropped.save(out_path, _pillow_format(path.suffix), **_pillow_kwargs(path.suffix))
    ctx.progress(1.0)
    return out_path


def _pillow_format(suffix: str) -> str:
    mapping = {
        ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP",
        ".tiff": "TIFF", ".tif": "TIFF", ".heic": "HEIF", ".heif": "HEIF",
    }
    return mapping.get(suffix.lower(), "PNG")


def _pillow_kwargs(suffix: str) -> dict:
    if suffix.lower() in (".jpg", ".jpeg"):
        return {"quality": 95, "optimize": True}
    if suffix.lower() == ".webp":
        return {"quality": 95}
    if suffix.lower() in (".heic", ".heif"):
        return {"quality": 95}
    return {}


def redact_photo(
    path: Path, boxes: list[tuple[int, int, int, int, str, str]],
    ctx: Ctx, reserved: set[Path],
) -> Path:
    """boxes: (x, y, w, h, mode('solid'|'blur'), color) in pixel coordinates."""
    verify_writable(path)
    ctx.status(f"Redacting {path.name}")
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")
    for x, y, w, h, mode, color in boxes:
        region = (max(0, x), max(0, y), max(0, x + w), max(0, y + h))
        if region[2] <= region[0] or region[3] <= region[1]:
            continue
        if mode == "blur":
            patch = img.crop(region).filter(ImageFilter.GaussianBlur(18))
            img.paste(patch, region)
        else:
            draw = ImageDraw.Draw(img)
            draw.rectangle(region, fill=color)
    flattened = img.convert("RGB")
    out_path = _unique(path.parent, f"{path.stem} Redacted", ".png", reserved)
    flattened.save(out_path, "PNG")
    ctx.progress(1.0)
    return out_path


def add_background(
    path: Path, color: str, width: int | None, height: int | None,
    ctx: Ctx, reserved: set[Path],
) -> Path:
    verify_writable(path)
    ctx.status(f"Adding background to {path.name}")
    img = Image.open(path).convert("RGBA")
    target_w = width or img.width
    target_h = height or img.height
    scale = min(1.0, target_w / img.width, target_h / img.height)
    resized = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), color)
    canvas.paste(resized, ((target_w - resized.width) // 2, (target_h - resized.height) // 2), resized)
    out_path = _unique(path.parent, f"{path.stem} Background", ".png", reserved)
    canvas.save(out_path, "PNG")
    ctx.progress(1.0)
    return out_path


def make_collage(
    paths: list[Path], options: dict, ctx: Ctx, reserved: set[Path],
) -> Path:
    if not paths:
        raise EngineError("No images selected.")
    ctx.status("Building collage")
    images = []
    for path in paths:
        verify_writable(path)
        img = load_image(path).convert("RGBA")
        images.append(img)
    layout = options.get("layout", "grid")
    spacing = int(options.get("spacing", 12))
    padding = int(options.get("padding", 24))
    radius = int(options.get("corner_radius", 12))
    background = options.get("background", "white")
    resolution = options.get("resolution", "source")
    fit = options.get("fit", "fill")

    cell_w = max(img.width for img in images)
    cell_h = max(img.height for img in images)
    if resolution != "source":
        cell_w = cell_h = int(resolution)

    count = len(images)
    if layout == "grid":
        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)
    elif layout == "horizontal":
        cols, rows = count, 1
    elif layout == "vertical":
        cols, rows = 1, count
    else:  # featured
        cols, rows = 2, math.ceil((count + 1) / 2)

    canvas_w = padding * 2 + cols * cell_w + (cols - 1) * spacing
    canvas_h = padding * 2 + rows * cell_h + (rows - 1) * spacing
    bg = (255, 255, 255, 0) if background == "transparent" else background
    canvas = Image.new("RGBA", (canvas_w, canvas_h), bg if isinstance(bg, str) else bg)

    def fit_cell(img: Image.Image, size: tuple[int, int]) -> Image.Image:
        w, h = size
        if fit == "fill":
            scale = max(w / img.width, h / img.height)
        else:
            scale = min(w / img.width, h / img.height)
        resized = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        layer.paste(resized, ((w - resized.width) // 2, (h - resized.height) // 2), resized)
        if radius > 0:
            mask = Image.new("L", size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
            layer.putalpha(mask)
        return layer

    def paste(img: Image.Image, col: int, row: int, span: int = 1) -> None:
        pos = (padding + col * (cell_w + spacing), padding + row * (cell_h + spacing))
        if span > 1:
            size = (cell_w * span + spacing * (span - 1), cell_h)
        else:
            size = (cell_w, cell_h)
        canvas.paste(fit_cell(img, size), pos)

    if layout == "featured" and count > 1:
        paste(images[0], 0, 0, 2)
        for index, img in enumerate(images[1:]):
            row = 1 + index // 2
            col = index % 2
            paste(img, col, row)
    else:
        for index, img in enumerate(images):
            row, col = divmod(index, cols)
            paste(img, col, row)

    first = paths[0]
    out_path = _unique(first.parent, "Photo Collage", ".png", reserved)
    canvas.save(out_path, "PNG")
    ctx.progress(1.0)
    return out_path


# ---------------------------------------------------------------------------
# Audio tools
# ---------------------------------------------------------------------------

AUDIO_CODEC_ARGS = {
    "ogg": ["-c:a", "libvorbis", "-q:a", "4"],
    "opus": ["-c:a", "libopus", "-b:a", "128k"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "wma": ["-c:a", "wmav2", "-b:a", "192k"],
    "m4b": ["-c:a", "aac", "-b:a", "192k"],
}


def audio_codec_args(path_or_ext: Path | str) -> list[str]:
    name = str(path_or_ext).lower().replace("\\", "/").rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1] if "." in name else name
    codec = CODEC_ARGS.get(ext) or AUDIO_CODEC_ARGS.get(ext)
    if codec is None:
        raise EngineError(f"Unsupported audio container: {ext}")
    return list(codec)


def _atempo_chain(factor: float) -> str:
    if factor <= 0:
        raise EngineError("Speed must be greater than zero.")
    parts = []
    remaining = factor
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def normalize_audio(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Normalizing {path.name}")
    info = probe(path)
    ext = path.suffix.lower()
    out_path = _unique(path.parent, f"{path.stem} Normalized", ext, reserved)
    args = ["-i", str(path), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            *audio_codec_args(ext), str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def convert_channels(path: Path, mode: str, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Converting channels of {path.name}")
    info = probe(path)
    ext = path.suffix.lower()
    out_path = _unique(path.parent, f"{path.stem} {'Mono' if mode == 'mono' else 'Stereo'}", ext, reserved)
    args = ["-i", str(path), "-ac", "1" if mode == "mono" else "2",
            *audio_codec_args(ext), str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def trim_audio(path: Path, start: float, end: float, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Trimming {path.name}")
    info = probe(path)
    duration = max(end - start, 0.05)
    ext = path.suffix.lower()
    out_path = _unique(path.parent, f"{path.stem} Trimmed", ext, reserved)
    args = ["-ss", f"{start:.3f}", "-i", str(path), "-t", f"{duration:.3f}",
            *audio_codec_args(ext), "-map_metadata", "0", str(out_path)]
    code = run_ffmpeg(args, duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def bleep_audio(
    path: Path, ranges: list[tuple[float, float]], ctx: Ctx, reserved: set[Path],
) -> Path:
    verify_writable(path)
    if not ranges:
        raise EngineError("Add at least one bleep range first.")
    info = probe(path)
    channels = info.audio().channels if info.audio() and info.audio().channels else 2
    sample_rate = info.audio().sample_rate if info.audio() and info.audio().sample_rate else 44100
    duration = info.duration or _max_end(ranges)
    ctx.status(f"Bleeping {path.name}")
    express = "+".join(f"between(t,{s:.4f},{e:.4f})" for s, e in ranges)
    layout = {1: "mono", 2: "stereo", 3: "2.1", 4: "quad", 5: "5.0",
              6: "5.1", 7: "6.1", 8: "7.1"}.get(channels, "stereo")
    tone_pan = "|".join(f"c{i}=c0" for i in range(channels))
    base_pan = "|".join(f"c{i}=c{i}" for i in range(channels))
    filter_complex = (
        f"sine=frequency=1000:sample_rate={sample_rate}:duration={duration:.4f}[tone];"
        f"[tone]pan={layout}|{tone_pan}[tonec];"
        f"[0:a]pan={layout}|{base_pan},volume=enable='{express}':volume=0[base];"
        f"[base][tonec]amix=inputs=2:duration=first:normalize=0[out]"
    )
    ext = path.suffix.lower()
    out_path = _unique(path.parent, f"{path.stem} Bleeped", ext, reserved)
    args = ["-i", str(path), "-filter_complex", filter_complex, "-map", "[out]",
            *audio_codec_args(ext), str(out_path)]
    code = run_ffmpeg(args, duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def _max_end(ranges: list[tuple[float, float]]) -> float:
    return max(max((e for _, e in ranges), default=1.0), 1e-3)


def make_visualizer(
    path: Path, orientation: str, background_image: Path | None, ctx: Ctx, reserved: set[Path],
) -> Path:
    verify_writable(path)
    ctx.status(f"Building visualizer for {path.name}")
    info = probe(path)
    duration = info.duration or 1.0
    size = {"landscape": (1280, 720), "portrait": (720, 1280), "square": (1080, 1080)}.get(orientation, (1280, 720))
    out_path = _unique(path.parent, f"{path.stem} Visualizer", ".mp4", reserved)
    if background_image and background_image.exists():
        filter_complex = (
            f"[1:v]scale={size[0]}:{size[1]}:force_original_aspect_ratio=increase,"
            f"crop={size[0]}:{size[1]}[bg];"
            f"[0:a]showwaves=s={size[0]}x{max(size[1] // 3, 64)}:mode=cline:colors=0xF87800[wave];"
            f"[bg][wave]overlay=(W-w)/2:(H-h)/2[out]"
        )
        args = ["-i", str(path), "-i", str(background_image), "-filter_complex", filter_complex,
                "-map", "[out]", "-map", "0:a?", "-c:a", "aac", "-b:a", "192k",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-t", f"{duration:.3f}", str(out_path)]
    else:
        filter_complex = (
            f"[0:a]showwaves=s={size[0]}x{max(size[1] // 3, 64)}:mode=cline:colors=0xF87800[wave];"
            f"color=c=black:s={size[0]}x{size[1]}:d={duration:.3f}[bg];"
            f"[bg][wave]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
        )
        args = ["-i", str(path), "-filter_complex", filter_complex, "-map", "[out]",
                "-map", "0:a?", "-c:a", "aac", "-b:a", "192k",
                "-c:v", "libx264", "-preset", "veryfast", "-t", f"{duration:.3f}", str(out_path)]
    code = run_ffmpeg(args, duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


# ---------------------------------------------------------------------------
# Video tools
# ---------------------------------------------------------------------------

def remove_audio(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Removing audio from {path.name}")
    info = probe(path)
    out_path = _unique(path.parent, f"{path.stem} Muted", path.suffix, reserved)
    args = ["-i", str(path), "-an", "-c:v", "copy", str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def trim_video(path: Path, start: float, end: float, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Trimming {path.name}")
    info = probe(path)
    duration = max(end - start, 0.05)
    out_path = _unique(path.parent, f"{path.stem} Trimmed", path.suffix, reserved)
    args = ["-ss", f"{start:.3f}", "-i", str(path), "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    audio = info.audio()
    if audio:
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-an"]
    args += [str(out_path)]
    code = run_ffmpeg(args, duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def crop_video(path: Path, box: tuple[int, int, int, int], ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    info = probe(path)
    video = info.video()
    if not video:
        raise EngineError("No video stream found.")
    x, y, w, h = box
    if x == 0 and y == 0 and w >= video.width and h >= video.height:
        out_path = _unique(path.parent, f"{path.stem} Cropped", path.suffix, reserved)
        shutil.copy2(path, out_path)
        ctx.progress(1.0)
        return out_path
    w -= w % 2
    h -= h % 2
    x = max(0, min(x, video.width - w))
    y = max(0, min(y, video.height - h))
    out_path = _unique(path.parent, f"{path.stem} Cropped", path.suffix, reserved)
    codec = ["-c:v", "libx265", "-crf", "22", "-preset", "veryfast", "-tag:v", "hvc1"] \
        if video.codec == "hevc" else ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    args = ["-i", str(path), "-vf", f"crop={w}:{h}:{x}:{y}", *codec]
    audio = info.audio()
    if audio:
        args += ["-c:a", "copy"]
    else:
        args += ["-an"]
    args += [str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def change_speed(path: Path, factor: float, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(f"Changing speed of {path.name}")
    info = probe(path)
    out_path = _unique(path.parent, f"{path.stem} {factor:g}x", path.suffix, reserved)
    filters = [f"setpts=PTS/{factor:.4f}"]
    args = ["-i", str(path), "-vf", ",".join(filters)]
    if info.audio():
        args += ["-af", _atempo_chain(factor)]
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-an"]
    args += ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", str(out_path)]
    duration = info.duration / factor if factor else info.duration
    code = run_ffmpeg(args, duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def take_snapshots(path: Path, timestamps: list[float], ctx: Ctx, reserved: set[Path]) -> list[Path]:
    verify_writable(path)
    info = probe(path)
    outputs = []
    total = len(timestamps)
    for index, timestamp in enumerate(timestamps):
        ctx.status(f"Capturing frame at {timestamp:.2f}s")
        suffix = f" Frame {int(round(timestamp * 1000))}.png"
        out_path = _unique(path.parent, f"{path.stem}{suffix}", "", reserved)
        args = ["-ss", f"{timestamp:.3f}", "-i", str(path), "-frames:v", "1", "-y", str(out_path)]
        code = run_ffmpeg(args, 0, None, ctx.cancel)
        if code != 0 or not out_path.exists():
            raise EngineError(f"Could not capture a frame at {timestamp:.2f}s.")
        outputs.append(out_path)
        ctx.progress((index + 1) / total)
    return outputs


def split_video(path: Path, parts: int, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    info = probe(path)
    if parts < 2:
        raise EngineError("Choose at least two sections.")
    duration = info.duration
    segment_time = duration / parts
    folder_name = naming.folder_name(path, "Split")
    folder = path.parent / folder_name
    index = 2
    while folder.exists():
        folder = path.parent / f"{folder_name} {index}"
        index += 1
    tmp = Path(str(folder) + ".tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    ctx.status(f"Splitting {path.name} into {parts} sections")
    args = ["-i", str(path), "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-force_key_frames", f"expr:gte(t,n_forced*{segment_time:.4f})",
            "-f", "segment", "-segment_time", f"{segment_time:.4f}",
            "-reset_timestamps", "1"]
    if info.audio():
        args += ["-c:a", "aac", "-b:a", "192k"]
    args += [str(tmp / f"Section %03d{path.suffix}")]
    code = run_ffmpeg(args, duration, ctx.progress, ctx.cancel)
    if code != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise EngineError("Could not split this video.")
    os.replace(tmp, folder)
    return folder


def join_videos(paths: list[Path], ctx: Ctx, reserved: set[Path]) -> Path:
    if len(paths) < 2:
        raise EngineError("Select at least two videos to join.")
    for path in paths:
        verify_writable(path)
    infos = [probe(path) for path in paths]
    first_video = infos[0].video()
    if not first_video:
        raise EngineError("The first video has no video stream.")
    width, height = first_video.width, first_video.height
    if max(width, height) > 1920:
        scale = 1920 / max(width, height)
        width, height = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2
    width = width // 2 * 2
    height = height // 2 * 2
    total = sum(info.duration for info in infos) or 1.0
    args: list[str] = []
    for index, path in enumerate(paths):
        args += ["-i", str(path)]
    filters = []
    for index in range(len(paths)):
        filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{index}]"
        )
    has_audio = [info.audio() is not None for info in infos]
    for index, present in enumerate(has_audio):
        if present:
            filters.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo[a{index}]")
        else:
            args += ["-f", "lavfi", "-t", f"{max(infos[index].duration, 0.1):.3f}",
                     "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            silent_index = len(paths) + sum(1 for p in has_audio[:index] if not p)
            filters.append(f"[{silent_index}:a]aformat=channel_layouts=stereo[a{index}]")
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
    filters.append(f"{concat_inputs}concat=n={len(paths)}:v=1:a=1[outv][outa]")
    out_path = _unique(paths[0].parent, "Joined Video", ".mp4", reserved)
    args += ["-filter_complex", ";".join(filters), "-map", "[outv]", "-map", "[outa]",
             "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path)]
    code = run_ffmpeg(args, total, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def redact_video(
    path: Path, boxes: list[dict], mode: str, color: str, ctx: Ctx, reserved: set[Path],
) -> Path:
    """boxes: dicts with x, y, w, h (pixels) and start, end (seconds)."""
    verify_writable(path)
    if not boxes:
        raise EngineError("Add at least one redaction box first.")
    info = probe(path)
    duration = info.duration
    valid: list[tuple[int, int, int, int, float, float]] = []
    for box in boxes:
        x, y, w, h = int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])
        start = max(0.0, float(box.get("start", 0.0)))
        end = float(box.get("end", duration))
        if duration:
            end = min(end, duration)
        if w <= 0 or h <= 0 or end - start < 0.01:
            continue
        valid.append((x, y, w, h, start, end))
    if not valid:
        raise EngineError("No valid redaction boxes.")
    ctx.status(f"Redacting {path.name}")
    ff_color = "black" if color.startswith("#000000") else f"0x{color.lstrip('#')}"
    chains = []
    current = "[0:v]"
    for index, (x, y, w, h, start, end) in enumerate(valid):
        enable = f"between(t,{start:.4f},{end:.4f})"
        label = f"[v{index}]"
        if mode == "blur":
            chains.append(
                f"{current}split=2[base{index}][toblur{index}];"
                f"[toblur{index}]crop={w}:{h}:{x}:{y},boxblur=25:1[blurred{index}];"
                f"[base{index}][blurred{index}]overlay={x}:{y}:enable='{enable}'{label}"
            )
        else:
            chains.append(
                f"{current}drawbox=x={x}:y={y}:w={w}:h={h}:color={ff_color}:t=fill:enable='{enable}'{label}"
            )
        current = label
    chains.append(f"{current}format=yuv420p[out]")
    filter_complex = ";".join(chains)
    out_path = _unique(path.parent, f"{path.stem} Redacted", path.suffix, reserved)
    args = ["-i", str(path), "-filter_complex", filter_complex, "-map", "[out]"]
    if info.audio():
        args += ["-map", "0:a", "-c:a", "aac", "-b:a", "192k"]
    args += ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast", str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


# ---------------------------------------------------------------------------
# PDF tools
# ---------------------------------------------------------------------------

def split_pdf(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    from pypdf import PdfReader, PdfWriter

    verify_writable(path)
    reader = PdfReader(str(path))
    total = len(reader.pages)
    folder = path.parent / naming.folder_name(path, "Pages")
    index = 2
    while folder.exists():
        folder = path.parent / f"{naming.folder_name(path, 'Pages')} {index}"
        index += 1
    folder.mkdir()
    ctx.status(f"Splitting {path.name} into {total} pages")
    for number, page in enumerate(reader.pages):
        writer = PdfWriter()
        writer.add_page(page)
        out_path = folder / f"Page {number + 1:03d}.pdf"
        with open(out_path, "wb") as handle:
            writer.write(handle)
        ctx.progress((number + 1) / total)
    return folder


def merge_pdfs(paths: list[Path], ctx: Ctx, reserved: set[Path]) -> Path:
    from pypdf import PdfReader, PdfWriter

    if not paths:
        raise EngineError("Select at least one PDF.")
    writer = PdfWriter()
    total = sum(len(PdfReader(str(p)).pages) for p in paths) or 1
    done = 0
    for path in paths:
        verify_writable(path)
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
            done += 1
            ctx.progress(done / total)
    out_path = _unique(paths[0].parent, naming.tailored_name(paths[0], "Merged", "") if len(paths) == 1 else "Merged PDF", ".pdf", reserved)
    with open(out_path, "wb") as handle:
        writer.write(handle)
    return out_path


def compress_pdf(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    from pypdf import PdfReader, PdfWriter

    verify_writable(path)
    ctx.status(f"Compressing {path.name}")
    original_size = path.stat().st_size
    reader = PdfReader(str(path))
    total = max(1, len(reader.pages))
    writer = PdfWriter()
    for number, page in enumerate(reader.pages):
        if ctx.cancelled():
            raise EngineError("Cancelled.")
        try:
            page.compress_content_streams()
        except Exception:
            pass
        writer.add_page(page)
        ctx.progress((number + 1) / total * 0.8)
    try:
        writer.compress_identical_objects()
    except Exception:
        pass
    buffer = io.BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    out_path = _unique(path.parent, naming.tailored_name(path, "Compressed", ""), ".pdf", reserved)
    if len(data) < original_size:
        out_path.write_bytes(data)
    else:
        shutil.copy2(path, out_path)
    ctx.progress(1.0)
    return out_path


# ---------------------------------------------------------------------------
# QR codes
# ---------------------------------------------------------------------------

def read_qr_codes(paths: list[Path], ctx: Ctx) -> list[tuple[str, str | None, str]]:
    """Returns (source name, page label or None, decoded text)."""
    import cv2
    import numpy as np

    detector = cv2.QRCodeDetector()
    results: list[tuple[str, str | None, str]] = []

    def scan_image(image: "Image.Image") -> list[str]:
        array = np.array(image.convert("RGB"))
        bgr = array[:, :, ::-1].copy()
        found: list[str] = []
        try:
            ok, decoded, _, _ = detector.detectAndDecodeMulti(bgr)
        except Exception:
            ok, decoded = False, ()
        if ok and decoded:
            found.extend([d for d in decoded if d])
        else:
            text, points, _ = detector.detectAndDecode(bgr)
            if text:
                found.append(text)
        return found

    for path in paths:
        if ctx.cancelled():
            break
        ctx.status(f"Scanning {path.name}")
        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                import pypdfium2 as pdfium

                pdf = pdfium.PdfDocument(str(path))
                for number in range(len(pdf)):
                    page = pdf[number]
                    image = page.render(scale=200 / 72.0).to_pil()
                    for text in scan_image(image):
                        results.append((path.name, f"Page {number + 1}", text))
            elif suffix == ".gif":
                gif = Image.open(path)
                for frame_index in range(min(getattr(gif, "n_frames", 1), 20)):
                    gif.seek(frame_index)
                    for text in scan_image(gif):
                        label = None if frame_index == 0 else f"Frame {frame_index + 1}"
                        results.append((path.name, label, text))
            else:
                image = Image.open(path)
                for text in scan_image(image):
                    results.append((path.name, None, text))
        except Exception:
            continue
    ctx.progress(1.0)
    return results


def detect_faces(path: Path) -> list[tuple[int, int, int, int]]:
    """Face detection for the redaction editor (Cascade classifier)."""
    import cv2

    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    array = __import__("numpy").array(image)[:, :, ::-1].copy()
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    gray = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, 1.15, 5, minSize=(40, 40))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in faces]
