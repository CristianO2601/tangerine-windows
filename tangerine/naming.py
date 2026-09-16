"""Collision-safe sibling naming: cat.jpg, cat 2.jpg, cat 3.jpg ..."""

from pathlib import Path


def unique_path(folder: Path, stem: str, suffix: str, reserved: set[Path] | None = None) -> Path:
    """Return a path inside *folder* that does not yet exist."""
    if reserved is None:
        reserved = set()
    suffix = suffix or ""
    candidate = folder / f"{stem}{suffix}"
    index = 2
    while candidate.exists() or candidate in reserved:
        candidate = folder / f"{stem} {index}{suffix}"
        index += 1
    reserved.add(candidate)
    return candidate


def tailored_name(source: Path, descriptor: str, suffix: str) -> str:
    """Descriptive sibling name such as 'Clip Cropped.mp4'."""
    base = source.stem
    if descriptor and descriptor.lower() not in base.lower():
        return f"{base} {descriptor}{suffix}"
    return f"{base}{suffix}"


def folder_name(source: Path, descriptor: str) -> str:
    base = source.stem
    if descriptor:
        return f"{base} {descriptor}"
    return base


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
