"""File tool implementations: compress, metadata, crop, redact, collage,
audio/video editors, PDF split/merge, QR reading."""

from __future__ import annotations

import io
import math
import os
import shutil
import zipfile
from pathlib import Path

from PIL import (
    Image,
    ImageChops,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageOps,
    ImageColor,
    TiffImagePlugin,
)

from . import i18n, naming
from .engines import CODEC_ARGS, Ctx, EngineError, _finish_ffmpeg, load_image, verify_writable, _flatten
from .media import probe, probe_duration_seconds, run_ffmpeg

#: Extensions handled by Pillow for the metadata tools.
IMAGE_META_EXTS = (
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif",
    ".avif", ".bmp",
)

#: GPS location is stored in its own EXIF sub-IFD.
GPS_IFD = 0x8825

#: Mosaic block size for pixelated redaction.
PIXELATE_BLOCK = 12


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
    ctx.status(i18n.tr("action.compressing", name=path.name))
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
    ctx.status(i18n.tr("action.compressing", name=path.name))
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
        raise EngineError(i18n.tr("err.video_compress"))
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
        raise EngineError(i18n.tr("err.doc_compress_type"))
    ctx.status(i18n.tr("action.compressing", name=path.name))
    original_size = path.stat().st_size
    buffer = io.BytesIO()
    with zipfile.ZipFile(path) as source:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            for info in source.infolist():
                if ctx.cancelled():
                    raise EngineError(i18n.tr("err.cancelled"))
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
    ctx.status(i18n.tr("action.compressing", name=path.name))
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
        raise EngineError(i18n.tr("err.audio_compress"))
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
    if ext in IMAGE_META_EXTS:
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
        location = read_location(path)
        if location:
            rows.append((i18n.tr("meta.latitude"), f"{location['latitude']:.6f}"))
            rows.append((i18n.tr("meta.longitude"), f"{location['longitude']:.6f}"))
            if location.get("altitude") is not None:
                rows.append((i18n.tr("meta.altitude"), f"{location['altitude']:.2f} m"))
    else:
        info = probe(path)
        if info.duration:
            rows.append((i18n.tr("meta.duration"), f"{info.duration:.2f} s"))
        if info.bit_rate:
            rows.append((i18n.tr("meta.overall_bitrate"), f"{info.bit_rate / 1000:.0f} kbps"))
        video = info.video()
        if video:
            rows.append((i18n.tr("meta.video_codec"), video.codec))
            if video.width:
                rows.append((i18n.tr("meta.dimensions"), f"{video.width} x {video.height}"))
            if video.fps:
                rows.append((i18n.tr("meta.frame_rate"), f"{video.fps:.3f} fps"))
        audio = info.audio()
        if audio:
            rows.append((i18n.tr("meta.audio_codec"), audio.codec))
            if audio.channels:
                rows.append((i18n.tr("meta.channels"), str(audio.channels)))
            if audio.sample_rate:
                rows.append((i18n.tr("meta.sample_rate"), f"{audio.sample_rate} Hz"))
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


def _gps_decimal(values, reference) -> float | None:
    try:
        parts = [float(part) for part in tuple(values)]
    except Exception:
        return None
    if len(parts) < 2:
        return None
    decimal = parts[0] + parts[1] / 60.0
    if len(parts) > 2:
        decimal += parts[2] / 3600.0
    if isinstance(reference, bytes):
        reference = reference.decode("ascii", errors="replace")
    reference = str(reference or "").strip().upper()
    if reference.startswith("S") or reference.startswith("W"):
        decimal = -decimal
    return decimal


def _gps_altitude_ref(value) -> int:
    if isinstance(value, bytes):
        return value[0] if value else 0
    try:
        return int(value)
    except Exception:
        return 0


def read_location(path: Path) -> dict | None:
    """Decimal latitude/longitude/altitude from the EXIF GPS IFD, if present."""
    try:
        gps = Image.open(path).getexif().get_ifd(GPS_IFD)
    except Exception:
        return None
    if not gps:
        return None
    latitude = _gps_decimal(gps.get(2), gps.get(1))
    longitude = _gps_decimal(gps.get(4), gps.get(3))
    if latitude is None or longitude is None:
        return None
    altitude = None
    if gps.get(6) is not None:
        try:
            altitude = float(gps[6])
            if _gps_altitude_ref(gps.get(5)) == 1:
                altitude = -altitude
        except Exception:
            altitude = None
    return {"latitude": latitude, "longitude": longitude, "altitude": altitude}


def _gps_rational(value: float) -> tuple:
    degrees = int(value)
    minutes_full = (value - degrees) * 60.0
    minutes = int(minutes_full)
    seconds = (minutes_full - minutes) * 60.0
    return (
        TiffImagePlugin.IFDRational(degrees, 1),
        TiffImagePlugin.IFDRational(minutes, 1),
        TiffImagePlugin.IFDRational(round(seconds * 10000), 10000),
    )


def _write_gps(exif: Image.Exif, location: dict) -> None:
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if latitude is None or longitude is None:
        return
    latitude = float(latitude)
    longitude = float(longitude)
    gps = exif.get_ifd(GPS_IFD)
    gps[1] = "N" if latitude >= 0 else "S"
    gps[2] = _gps_rational(abs(latitude))
    gps[3] = "E" if longitude >= 0 else "W"
    gps[4] = _gps_rational(abs(longitude))
    altitude = location.get("altitude")
    if altitude is not None and str(altitude).strip() != "":
        altitude = float(altitude)
        gps[5] = 0 if altitude >= 0 else 1
        gps[6] = TiffImagePlugin.IFDRational(round(abs(altitude) * 1000), 1000)


def _exif_payload(exif: Image.Exif) -> bytes | None:
    try:
        populated = bool(
            len(exif) or len(exif.get_ifd(0x8769)) or len(exif.get_ifd(GPS_IFD)))
    except Exception:
        populated = True
    if not populated:
        return None
    try:
        return exif.tobytes()
    except Exception:
        return None


def _save_image_with_exif(img: Image.Image, path: Path, out_path: Path, exif) -> None:
    ext = path.suffix.lower()
    fmt = img.format or None
    save_kwargs: dict = {}
    if ext in (".jpg", ".jpeg"):
        fmt = "JPEG"
        save_kwargs = {"quality": 95, "optimize": True}
        img = _flatten(img) if img.mode not in ("RGB", "L") else img
    elif ext == ".png":
        fmt = "PNG"
    elif ext in (".tiff", ".tif"):
        fmt = "TIFF"
    elif ext == ".webp":
        fmt = "WEBP"
        save_kwargs = {"quality": 95}
    elif ext in (".heic", ".heif"):
        fmt = "HEIF"
        save_kwargs = {"quality": 95}
    elif ext == ".avif":
        fmt = "AVIF"
        save_kwargs = {"quality": 95}
    elif ext == ".bmp":
        fmt = "BMP"
    payload = _exif_payload(exif) if exif is not None else None
    if payload and fmt in ("JPEG", "PNG", "TIFF", "WEBP", "HEIF", "AVIF"):
        save_kwargs["exif"] = payload
    img.save(out_path, fmt, **save_kwargs)


def write_metadata_image(
    path: Path, fields: dict[int, str], strip_all: bool, ctx: Ctx, reserved: set[Path],
    location: dict | None = None,
) -> Path:
    verify_writable(path)
    ctx.status(i18n.tr("action.writing_metadata", name=path.name))
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
            try:
                for tag, value in source.get_ifd(GPS_IFD).items():
                    try:
                        exif.get_ifd(GPS_IFD)[tag] = value
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
    if location:
        try:
            _write_gps(exif, location)
        except Exception:
            pass
    out_path = _unique(path.parent, f"{path.stem} Metadata", path.suffix, reserved)
    _save_image_with_exif(img, path, out_path, exif)
    ctx.progress(1.0)
    return out_path


def remove_location(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    """Drop only the EXIF GPS block, keeping every other tag."""
    verify_writable(path)
    if path.suffix.lower() not in IMAGE_META_EXTS:
        raise EngineError(i18n.tr("err.gps_image_only"))
    ctx.status(i18n.tr("action.removing_location", name=path.name))
    img = Image.open(path)
    source = img.getexif()
    exif = Image.Exif()
    for tag in source:
        if tag in (0x8769, GPS_IFD):
            continue
        try:
            exif[tag] = source[tag]
        except Exception:
            pass
    try:
        for tag, value in source.get_ifd(0x8769).items():
            try:
                exif.get_ifd(0x8769)[tag] = value
            except Exception:
                pass
    except Exception:
        pass
    out_path = _unique(path.parent, f"{path.stem} No Location", path.suffix, reserved)
    _save_image_with_exif(img, path, out_path, exif)
    ctx.progress(1.0)
    return out_path


def strip_metadata(path: Path, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(i18n.tr("action.removing_metadata", name=path.name))
    ext = path.suffix.lower()
    if ext in IMAGE_META_EXTS:
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
        elif ext == ".avif":
            fmt = "AVIF"
            kwargs = {"quality": 95}
        else:
            fmt = "BMP"
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
    ctx.status(i18n.tr("action.cropping", name=path.name))
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
        ".avif": "AVIF", ".bmp": "BMP",
    }
    return mapping.get(suffix.lower(), "PNG")


def _pillow_kwargs(suffix: str) -> dict:
    if suffix.lower() in (".jpg", ".jpeg"):
        return {"quality": 95, "optimize": True}
    if suffix.lower() in (".webp", ".heic", ".heif", ".avif"):
        return {"quality": 95}
    return {}


def redact_photo(
    path: Path, boxes: list[tuple[int, int, int, int, str, str]],
    ctx: Ctx, reserved: set[Path],
) -> Path:
    """boxes: (x, y, w, h, mode('solid'|'blur'|'pixelate'), color) in pixels."""
    verify_writable(path)
    ctx.status(i18n.tr("action.redacting", name=path.name))
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")
    for x, y, w, h, mode, color in boxes:
        region = (max(0, x), max(0, y), max(0, x + w), max(0, y + h))
        if region[2] <= region[0] or region[3] <= region[1]:
            continue
        if mode == "blur":
            patch = img.crop(region).filter(ImageFilter.GaussianBlur(18))
            img.paste(patch, region)
        elif mode == "pixelate":
            patch = img.crop(region)
            mosaic = patch.resize(
                (max(1, patch.width // PIXELATE_BLOCK), max(1, patch.height // PIXELATE_BLOCK)),
                Image.NEAREST,
            ).resize(patch.size, Image.NEAREST)
            img.paste(mosaic, region)
        else:
            draw = ImageDraw.Draw(img)
            draw.rectangle(region, fill=color)
    flattened = img.convert("RGB")
    out_path = _unique(path.parent, f"{path.stem} Redacted", ".png", reserved)
    flattened.save(out_path, "PNG")
    ctx.progress(1.0)
    return out_path


#: Canvas ratios offered by the background tool.
ASPECT_RATIOS = {
    "1:1": 1.0, "4:3": 4 / 3, "3:2": 3 / 2, "16:9": 16 / 9, "9:16": 9 / 16,
}


def _hex_rgb(value, fallback: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    try:
        parts = ImageColor.getrgb(str(value))
    except Exception:
        return fallback
    return parts[0], parts[1], parts[2]


def _linear_gradient(size: tuple[int, int], start: str, end: str, angle: float) -> Image.Image:
    """Directional gradient interpolated by projection onto *angle* degrees."""
    width, height = size
    first = _hex_rgb(start, (255, 255, 255))
    last = _hex_rgb(end, (0, 0, 0))
    samples = 192
    theta = math.radians(float(angle) % 360.0)
    dx, dy = math.cos(theta), math.sin(theta)
    span = abs(dx) * (samples - 1) + abs(dy) * (samples - 1)
    small = Image.new("RGB", (samples, samples))
    pixels = small.load()
    center = (samples - 1) / 2.0
    for y in range(samples):
        for x in range(samples):
            projection = (x - center) * dx + (y - center) * dy
            t = projection / span + 0.5 if span else 0.0
            t = max(0.0, min(1.0, t))
            pixels[x, y] = (
                round(first[0] + (last[0] - first[0]) * t),
                round(first[1] + (last[1] - first[1]) * t),
                round(first[2] + (last[2] - first[2]) * t),
            )
    return small.resize(size, Image.BILINEAR)


def _cover_image(path: Path, size: tuple[int, int]) -> Image.Image:
    cover = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    scale = max(size[0] / cover.width, size[1] / cover.height)
    resized = cover.resize(
        (max(1, math.ceil(cover.width * scale)), max(1, math.ceil(cover.height * scale))),
        Image.LANCZOS,
    )
    left = (resized.width - size[0]) // 2
    top = (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def _background_layer(size: tuple[int, int], fill: dict) -> Image.Image:
    kind = str((fill or {}).get("type", "color"))
    if kind == "gradient":
        return _linear_gradient(
            size, fill.get("from", "#FFFFFF"), fill.get("to", "#000000"),
            fill.get("angle", 0.0))
    if kind == "image":
        source = Path(str(fill.get("path", "")))
        if not source.exists():
            raise EngineError(i18n.tr("err.background_image", name=source.name))
        return _cover_image(source, size)
    return Image.new("RGB", size, _hex_rgb(fill.get("color", "#FFFFFF")))


def add_background(
    path: Path, options: dict, ctx: Ctx, reserved: set[Path],
) -> Path:
    """Place the photo on a larger canvas built from the chosen fill.

    ``options`` keys: ``fill`` (color/gradient/image), ``aspect``,
    ``margin`` (px), ``radius`` (px, image corners) and ``fit``.
    """
    verify_writable(path)
    ctx.status(i18n.tr("action.adding_background_to", name=path.name))
    options = options or {}
    fill = options.get("fill") or {"type": "color", "color": "#FFFFFF"}
    margin = max(0, int(options.get("margin", 0)))
    radius = max(0, int(options.get("radius", 0)))
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")

    canvas_w = img.width + margin * 2
    canvas_h = img.height + margin * 2
    ratio = ASPECT_RATIOS.get(str(options.get("aspect", "original")))
    if ratio:
        if canvas_w / canvas_h < ratio:
            canvas_w = int(round(canvas_h * ratio))
        elif canvas_w / canvas_h > ratio:
            canvas_h = int(round(canvas_w / ratio))
    canvas_w = max(canvas_w, img.width)
    canvas_h = max(canvas_h, img.height)

    canvas = _background_layer((canvas_w, canvas_h), fill)
    alpha = img.getchannel("A")
    if radius > 0:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, img.width - 1, img.height - 1),
            radius=min(radius, max(img.size) // 2), fill=255)
        alpha = ImageChops.multiply(alpha, mask)
    canvas.paste(img, ((canvas_w - img.width) // 2, (canvas_h - img.height) // 2), alpha)
    out_path = _unique(path.parent, f"{path.stem} Background", ".png", reserved)
    canvas.save(out_path, "PNG")
    ctx.progress(1.0)
    return out_path


def _shift_temperature(img: Image.Image, value: float) -> Image.Image:
    amount = max(-100.0, min(100.0, float(value))) / 100.0
    if amount == 0:
        return img
    red = img.getchannel("R").point(
        lambda p: max(0, min(255, int(round(p * (1.0 + 0.28 * amount))))))
    blue = img.getchannel("B").point(
        lambda p: max(0, min(255, int(round(p * (1.0 - 0.28 * amount))))))
    return Image.merge("RGB", (red, img.getchannel("G"), blue))


def _apply_vibrance(img: Image.Image, value: float) -> Image.Image:
    amount = max(-100.0, min(100.0, float(value))) / 100.0
    if amount == 0:
        return img
    hue, saturation, brightness = img.convert("HSV").split()
    if amount > 0:
        table = [
            max(0, min(255, int(round(x + amount * (255 - x) * x / 255.0))))
            for x in range(256)
        ]
    else:
        table = [
            max(0, min(255, int(round(x + amount * x * x / 255.0))))
            for x in range(256)
        ]
    saturation = saturation.point(table)
    return Image.merge("HSV", (hue, saturation, brightness)).convert("RGB")


def _apply_preset(img: Image.Image, preset: str) -> Image.Image:
    if preset == "mono":
        return ImageOps.grayscale(img).convert("RGB")
    if preset == "sepia":
        return ImageOps.colorize(
            ImageOps.grayscale(img), black=(38, 22, 10), white=(255, 240, 205))
    if preset == "noir":
        return ImageEnhance.Contrast(
            ImageOps.grayscale(img).convert("RGB")).enhance(1.35)
    if preset == "vivid":
        vivid = ImageEnhance.Color(img).enhance(1.4)
        return ImageEnhance.Contrast(vivid).enhance(1.12)
    if preset == "cool":
        return _shift_temperature(img, -35)
    if preset == "warm":
        return _shift_temperature(img, 35)
    return img


def _vignette_mask(size: tuple[int, int], strength: float) -> Image.Image:
    amount = max(0.0, min(100.0, float(strength))) / 100.0
    samples = 129
    mask = Image.new("L", (samples, samples), 255)
    pixels = mask.load()
    center = (samples - 1) / 2.0
    diagonal = math.sqrt(2.0)
    for y in range(samples):
        for x in range(samples):
            nx = (x - center) / center
            ny = (y - center) / center
            radius = math.hypot(nx, ny) / diagonal
            falloff = max(0.0, min(1.0, (radius - 0.35) / 0.65))
            pixels[x, y] = int(round(255 * (1.0 - amount * falloff * falloff)))
    return mask.resize(size, Image.BILINEAR)


def _add_grain(img: Image.Image, value: float) -> Image.Image:
    amount = max(0.0, min(100.0, float(value))) / 100.0
    if amount == 0:
        return img
    half_w = max(1, img.width // 2)
    half_h = max(1, img.height // 2)
    noise = Image.frombytes(
        "L", (half_w, half_h), os.urandom(half_w * half_h)).resize(
        img.size, Image.NEAREST)
    noise = noise.point(
        lambda p: max(0, min(255, int(round(128 + (p - 128) * amount * 0.5)))))
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    return ImageChops.add(img, noise_rgb, scale=1.0, offset=-128)


def _apply_edits(image: Image.Image, options: dict) -> Image.Image:
    """Preset first, then the manual adjustments, in a fixed order."""
    options = options or {}
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    result = image.convert("RGB")
    result = _apply_preset(result, str(options.get("preset", "none")))

    exposure = float(options.get("exposure", 0))
    if exposure:
        result = ImageEnhance.Brightness(result).enhance(2.0 ** (exposure / 50.0))
    contrast = float(options.get("contrast", 0))
    if contrast:
        result = ImageEnhance.Contrast(result).enhance(1.0 + contrast / 100.0)
    saturation = float(options.get("saturation", 0))
    if saturation:
        result = ImageEnhance.Color(result).enhance(1.0 + saturation / 100.0)
    temperature = float(options.get("temperature", 0))
    if temperature:
        result = _shift_temperature(result, temperature)
    vibrance = float(options.get("vibrance", 0))
    if vibrance:
        result = _apply_vibrance(result, vibrance)
    sharpness = float(options.get("sharpness", 0))
    if sharpness > 0:
        result = result.filter(ImageFilter.UnsharpMask(
            radius=2, percent=int(round(sharpness * 1.5)), threshold=3))
    vignette = float(options.get("vignette", 0))
    if vignette > 0:
        result = Image.merge("RGB", [
            ImageChops.multiply(channel, _vignette_mask(result.size, vignette))
            for channel in result.split()
        ])
    grain = float(options.get("grain", 0))
    if grain > 0:
        result = _add_grain(result, grain)
    if alpha is not None:
        result = result.convert("RGBA")
        result.putalpha(alpha)
    return result


def edit_image(path: Path, options: dict, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(i18n.tr("action.editing", name=path.name))
    image = ImageOps.exif_transpose(Image.open(path))
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.mode or "transparency" in image.info else "RGB")
    result = _apply_edits(image, options)
    out_path = _unique(path.parent, f"{path.stem} Edited", ".png", reserved)
    result.save(out_path, "PNG")
    ctx.progress(1.0)
    return out_path


def make_collage(
    paths: list[Path], options: dict, ctx: Ctx, reserved: set[Path],
) -> Path:
    if not paths:
        raise EngineError(i18n.tr("err.no_images"))
    ctx.status(i18n.tr("action.building_collage"))
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

#: Extra containers that are not conversion targets; the shared encoders live
#: in ``engines.CODEC_ARGS`` (mp3, m4a, wav, flac, ogg, opus, aiff, wma).
AUDIO_CODEC_ARGS = {
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "m4b": ["-c:a", "aac", "-b:a", "192k"],
}

#: Source extensions that reuse another container's encoder arguments.
AUDIO_CODEC_ALIASES = {"aif": "aiff"}


def audio_codec_args(path_or_ext: Path | str) -> list[str]:
    """FFmpeg codec arguments for an audio path or extension.

    ``.aif`` is encoded as ``.aiff``; unknown containers raise ``EngineError``.
    """
    name = str(path_or_ext).lower().replace("\\", "/").rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1] if "." in name else name
    ext = AUDIO_CODEC_ALIASES.get(ext, ext)
    codec = CODEC_ARGS.get(ext) or AUDIO_CODEC_ARGS.get(ext)
    if codec is None:
        raise EngineError(i18n.tr("err.audio_container", ext=ext))
    return list(codec)


def _atempo_chain(factor: float) -> str:
    if factor <= 0:
        raise EngineError(i18n.tr("err.speed_positive"))
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
    ctx.status(i18n.tr("action.normalizing", name=path.name))
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
    ctx.status(i18n.tr("action.converting_channels_of", name=path.name))
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
    ctx.status(i18n.tr("action.trimming", name=path.name))
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
        raise EngineError(i18n.tr("err.bleep_range"))
    info = probe(path)
    channels = info.audio().channels if info.audio() and info.audio().channels else 2
    sample_rate = info.audio().sample_rate if info.audio() and info.audio().sample_rate else 44100
    duration = info.duration or _max_end(ranges)
    ctx.status(i18n.tr("action.bleeping", name=path.name))
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
    ctx.status(i18n.tr("action.building_visualizer", name=path.name))
    info = probe(path)
    if not info.audio():
        raise EngineError(i18n.tr("err.no_audio_track"))
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
    ctx.status(i18n.tr("action.removing_audio_from", name=path.name))
    info = probe(path)
    out_path = _unique(path.parent, f"{path.stem} Muted", path.suffix, reserved)
    args = ["-i", str(path), "-an", "-c:v", "copy", str(out_path)]
    code = run_ffmpeg(args, info.duration, ctx.progress, ctx.cancel)
    _finish_ffmpeg(code, out_path)
    return out_path


def trim_video(path: Path, start: float, end: float, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    ctx.status(i18n.tr("action.trimming", name=path.name))
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
        raise EngineError(i18n.tr("err.no_video_stream"))
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
    ctx.status(i18n.tr("action.changing_speed", name=path.name))
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
        ctx.status(i18n.tr("action.capturing_frame", time=timestamp))
        suffix = f" Frame {int(round(timestamp * 1000))}.png"
        out_path = _unique(path.parent, f"{path.stem}{suffix}", "", reserved)
        args = ["-ss", f"{timestamp:.3f}", "-i", str(path), "-frames:v", "1", "-y", str(out_path)]
        code = run_ffmpeg(args, 0, None, ctx.cancel)
        if code != 0 or not out_path.exists():
            raise EngineError(i18n.tr("err.frame_capture", time=timestamp))
        outputs.append(out_path)
        ctx.progress((index + 1) / total)
    return outputs


def split_video(path: Path, parts: int, ctx: Ctx, reserved: set[Path]) -> Path:
    verify_writable(path)
    info = probe(path)
    if parts < 2:
        raise EngineError(i18n.tr("err.split_sections"))
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
    ctx.status(i18n.tr("action.splitting_into", name=path.name, parts=parts))
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
        raise EngineError(i18n.tr("err.split_failed"))
    os.replace(tmp, folder)
    return folder


def join_videos(paths: list[Path], ctx: Ctx, reserved: set[Path]) -> Path:
    if len(paths) < 2:
        raise EngineError(i18n.tr("err.join_two"))
    for path in paths:
        verify_writable(path)
    infos = [probe(path) for path in paths]
    first_video = infos[0].video()
    if not first_video:
        raise EngineError(i18n.tr("err.first_no_video"))
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
        raise EngineError(i18n.tr("err.redact_box"))
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
        raise EngineError(i18n.tr("err.redact_invalid"))
    ctx.status(i18n.tr("action.redacting", name=path.name))
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
        elif mode == "pixelate":
            block_w = max(1, w // PIXELATE_BLOCK)
            block_h = max(1, h // PIXELATE_BLOCK)
            chains.append(
                f"{current}split=2[base{index}][topix{index}];"
                f"[topix{index}]crop={w}:{h}:{x}:{y},"
                f"scale={block_w}:{block_h}:flags=neighbor,"
                f"scale={w}:{h}:flags=neighbor[mosaic{index}];"
                f"[base{index}][mosaic{index}]overlay={x}:{y}:enable='{enable}'{label}"
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
    ctx.status(i18n.tr("action.splitting_into_pages", name=path.name, total=total))
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
        raise EngineError(i18n.tr("err.pdf_select"))
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
    ctx.status(i18n.tr("action.compressing", name=path.name))
    original_size = path.stat().st_size
    reader = PdfReader(str(path))
    total = max(1, len(reader.pages))
    writer = PdfWriter()
    for number, page in enumerate(reader.pages):
        if ctx.cancelled():
            raise EngineError(i18n.tr("err.cancelled"))
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
        ctx.status(i18n.tr("action.scanning", name=path.name))
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
