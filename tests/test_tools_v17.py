"""Ola C tools (v1.7.0): pixelated redaction, the full background builder,
photo edits with presets, GPS location round-trip and the AVIF crop fix.

FFmpeg-dependent checks skip cleanly when it is missing; the AVIF check skips
when pillow-heif is not installed, mirroring ``test_formats_v17``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from tangerine import catalog, engines, media, tools

requires_ffmpeg = pytest.mark.skipif(
    not media.ffmpeg_path() or not media.ffprobe_path(),
    reason="FFmpeg and ffprobe are required for the media tool checks",
)

requires_heif = pytest.mark.skipif(
    "heic" not in catalog.available_engines(),
    reason="pillow-heif is required for AVIF support",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ctx() -> engines.Ctx:
    return engines.Ctx()


def _stripes(size: tuple[int, int] = (96, 96)) -> Image.Image:
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = ((x * 5) % 256, (y * 7) % 256, ((x + y) * 3) % 256)
    return image


def _luma(path: Path) -> float:
    with Image.open(path) as image:
        return ImageStat.Stat(image.convert("L")).mean[0]


# ---------------------------------------------------------------------------
# 1. pixelated redaction
# ---------------------------------------------------------------------------

def test_redact_photo_pixelate_blocks(tmp_path):
    source = tmp_path / "photo.png"
    _stripes().save(source)
    before = source.read_bytes()
    out = tools.redact_photo(
        source, [(24, 24, 48, 48, "pixelate", "#000000")], _ctx(), set())
    assert out.name == "photo Redacted.png"
    assert source.read_bytes() == before

    with Image.open(out).convert("RGB") as result, Image.open(source).convert("RGB") as original:
        blocks = []
        for by in range(24, 72, 12):
            for bx in range(24, 72, 12):
                block = [result.getpixel((x, y))
                         for y in range(by, by + 12) for x in range(bx, bx + 12)]
                assert len(set(block)) == 1
                assert block[0] != original.getpixel((bx, by))
                blocks.append(block[0])
        assert len(set(blocks)) > 1
        assert result.getpixel((5, 5)) == original.getpixel((5, 5))
        assert result.size == original.size


def test_redact_photo_pixelate_ignores_solid_color(tmp_path):
    source = tmp_path / "photo.png"
    _stripes((48, 48)).save(source)
    pixelated = tools.redact_photo(
        source, [(0, 0, 48, 48, "pixelate", "#FF00FF")], _ctx(), set())
    with Image.open(pixelated).convert("RGB") as result:
        raw = result.tobytes()
        assert not any(raw[index:index + 3] == b"\xff\x00\xff"
                       for index in range(0, len(raw), 3))


def _extract_frame(path: Path, target: Path) -> Image.Image:
    subprocess.run(
        [media.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-ss", "0.5", "-i", str(path), "-frames:v", "1", str(target)],
        check=True, capture_output=True)
    return Image.open(target).convert("RGB")


def _block_spread(region: Image.Image) -> float:
    total = 0.0
    count = 0
    for by in range(0, region.height - 11, 12):
        for bx in range(0, region.width - 11, 12):
            stats = ImageStat.Stat(region.crop((bx, by, bx + 12, by + 12)))
            total += sum(stats.stddev)
            count += 1
    return total / count


@requires_ffmpeg
def test_redact_video_pixelate_mosaic(tmp_path):
    source = tmp_path / "clip.mp4"
    subprocess.run(
        [media.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True, capture_output=True)
    out = tools.redact_video(
        source,
        [{"x": 20, "y": 20, "w": 120, "h": 96, "start": 0.0, "end": 1.0}],
        "pixelate", "#000000", _ctx(), set())
    assert out.name == "clip Redacted.mp4"
    assert out.stat().st_size > 0
    video = media.probe(out).video()
    assert video is not None
    assert (video.width, video.height) == (160, 120)

    box = (20, 20, 140, 116)
    before = _extract_frame(source, tmp_path / "before.png").crop(box)
    after = _extract_frame(out, tmp_path / "after.png").crop(box)
    assert _block_spread(after) < _block_spread(before) / 4
    assert ImageChops.difference(before, after).getbbox() is not None


@requires_ffmpeg
def test_redact_video_pixelate_needs_a_valid_box(tmp_path):
    source = tmp_path / "clip.mp4"
    subprocess.run(
        [media.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=orange:s=64x64:r=5:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
        check=True, capture_output=True)
    with pytest.raises(engines.EngineError):
        tools.redact_video(
            source, [{"x": 0, "y": 0, "w": 0, "h": 10, "start": 0.0, "end": 0.5}],
            "pixelate", "#000000", _ctx(), set())


# ---------------------------------------------------------------------------
# 2. full background
# ---------------------------------------------------------------------------

def test_add_background_color_aspect_margin_radius(tmp_path):
    source = tmp_path / "logo.png"
    Image.new("RGB", (40, 30), (200, 40, 40)).save(source)
    out = tools.add_background(source, {
        "fill": {"type": "color", "color": "#3060C0"},
        "aspect": "1:1", "margin": 10, "radius": 8, "fit": "contain",
    }, _ctx(), set())
    assert out.name == "logo Background.png"
    with Image.open(out).convert("RGB") as result:
        assert result.size == (60, 60)
        assert result.getpixel((30, 30)) == (200, 40, 40)
        assert result.getpixel((0, 0)) == (48, 96, 192)
        assert result.getpixel((10, 15)) == (48, 96, 192)
        assert result.getpixel((30, 15)) == (200, 40, 40)


def test_add_background_never_enlarges_the_photo(tmp_path):
    source = tmp_path / "wide.png"
    Image.new("RGB", (400, 30), (200, 40, 40)).save(source)
    out = tools.add_background(source, {
        "fill": {"type": "color", "color": "#3060C0"},
        "aspect": "1:1", "margin": 0, "radius": 0, "fit": "contain",
    }, _ctx(), set())
    with Image.open(out).convert("RGB") as result:
        assert result.size == (400, 400)
        assert result.getpixel((200, 200)) == (200, 40, 40)
        assert result.getpixel((200, 10)) == (48, 96, 192)


def test_add_background_gradient_follows_angle(tmp_path):
    source = tmp_path / "logo.png"
    Image.new("RGB", (20, 10), (255, 255, 255)).save(source)
    horizontal = tools.add_background(source, {
        "fill": {"type": "gradient", "from": "#000000", "to": "#FFFFFF",
                 "angle": 0},
        "aspect": "original", "margin": 30, "radius": 0, "fit": "contain",
    }, _ctx(), set())
    with Image.open(horizontal).convert("RGB") as result:
        left = result.getpixel((2, 35))
        right = result.getpixel((78, 35))
        assert sum(left) < sum(right)
        assert sum(left) < 60 and sum(right) > 700

    vertical = tools.add_background(source, {
        "fill": {"type": "gradient", "from": "#000000", "to": "#FFFFFF",
                 "angle": 90},
        "aspect": "original", "margin": 30, "radius": 0, "fit": "contain",
    }, _ctx(), set())
    with Image.open(vertical).convert("RGB") as result:
        top = result.getpixel((40, 2))
        bottom = result.getpixel((40, 68))
        assert sum(top) < sum(bottom)


def test_add_background_image_is_cover_cropped(tmp_path):
    source = tmp_path / "logo.png"
    Image.new("RGB", (20, 10), (255, 255, 255)).save(source)
    cover = tmp_path / "cover.png"
    quadrants = Image.new("RGB", (100, 100), (0, 0, 255))
    for y in range(50):
        for x in range(50):
            quadrants.putpixel((x, y), (255, 0, 0))
    quadrants.save(cover)
    out = tools.add_background(source, {
        "fill": {"type": "image", "path": str(cover)},
        "aspect": "original", "margin": 30, "radius": 0, "fit": "contain",
    }, _ctx(), set())
    with Image.open(out).convert("RGB") as result:
        assert result.size == (80, 70)
        assert result.getpixel((2, 2)) == (255, 0, 0)
        assert result.getpixel((2, 68)) == (0, 0, 255)
        assert result.getpixel((40, 35)) == (255, 255, 255)


def test_add_background_missing_image_raises(tmp_path):
    source = tmp_path / "logo.png"
    Image.new("RGB", (20, 10), (0, 0, 0)).save(source)
    with pytest.raises(engines.EngineError):
        tools.add_background(source, {
            "fill": {"type": "image", "path": str(tmp_path / "gone.png")},
            "aspect": "original", "margin": 4, "radius": 0, "fit": "contain",
        }, _ctx(), set())


# ---------------------------------------------------------------------------
# 3. photo editing
# ---------------------------------------------------------------------------

def test_edit_image_preset_mono(tmp_path):
    source = tmp_path / "photo.png"
    _stripes().save(source)
    out = tools.edit_image(source, {"preset": "mono"}, _ctx(), set())
    assert out.name == "photo Edited.png"
    with Image.open(out).convert("RGB") as result:
        for y in range(0, result.height, 7):
            for x in range(0, result.width, 7):
                pixel = result.getpixel((x, y))
                assert pixel[0] == pixel[1] == pixel[2]


def test_edit_image_sharpness_and_exposure_change_pixels(tmp_path):
    source = tmp_path / "photo.png"
    _stripes().save(source)
    plain = tools.edit_image(source, {}, _ctx(), set())
    sharpened = tools.edit_image(source, {"sharpness": 80}, _ctx(), set())
    with Image.open(plain).convert("RGB") as a, Image.open(sharpened).convert("RGB") as b:
        assert a.size == b.size
        assert ImageChops.difference(a, b).getbbox() is not None

    darker = tools.edit_image(source, {"exposure": -100}, _ctx(), set())
    brighter = tools.edit_image(source, {"exposure": 100}, _ctx(), set())
    assert _luma(darker) < _luma(plain) < _luma(brighter)


def test_edit_image_temperature_and_vignette(tmp_path):
    source = tmp_path / "photo.png"
    Image.new("RGB", (60, 60), (128, 128, 128)).save(source)
    warm = tools.edit_image(source, {"temperature": 100}, _ctx(), set())
    cool = tools.edit_image(source, {"temperature": -100}, _ctx(), set())
    with Image.open(warm).convert("RGB") as w, Image.open(cool).convert("RGB") as c:
        warm_pixel = w.getpixel((30, 30))
        cool_pixel = c.getpixel((30, 30))
        assert warm_pixel[0] - warm_pixel[2] > 0
        assert cool_pixel[0] - cool_pixel[2] < 0

    vignetted = tools.edit_image(source, {"vignette": 100}, _ctx(), set())
    with Image.open(vignetted).convert("RGB") as v, Image.open(source).convert("RGB") as o:
        assert sum(v.getpixel((2, 2))) < sum(o.getpixel((2, 2)))
        assert v.getpixel((30, 30)) == o.getpixel((30, 30))


def test_edit_image_preset_runs_before_manual_temperature(tmp_path):
    source = tmp_path / "photo.png"
    Image.new("RGB", (40, 40), (128, 128, 128)).save(source)
    preset_only = tools.edit_image(source, {"preset": "cool"}, _ctx(), set())
    combined = tools.edit_image(
        source, {"preset": "cool", "temperature": -60}, _ctx(), set())
    with Image.open(preset_only).convert("RGB") as a, Image.open(combined).convert("RGB") as b:
        assert b.getpixel((20, 20))[2] - b.getpixel((20, 20))[0] > \
            a.getpixel((20, 20))[2] - a.getpixel((20, 20))[0]


# ---------------------------------------------------------------------------
# 4. GPS location
# ---------------------------------------------------------------------------

def test_gps_write_read_and_remove_location(tmp_path):
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (40, 30), (200, 100, 50)).save(source, "JPEG", quality=95)
    written = tools.write_metadata_image(
        source, {315: "Tangerine GPS QA", 36867: "2020:01:02 03:04:05"}, False,
        _ctx(), set(),
        {"latitude": 41.3874, "longitude": 2.1686, "altitude": 12.5})
    assert written.name == "photo Metadata.jpg"

    location = tools.read_location(written)
    assert location is not None
    assert location["latitude"] == pytest.approx(41.3874, abs=1e-4)
    assert location["longitude"] == pytest.approx(2.1686, abs=1e-4)
    assert location["altitude"] == pytest.approx(12.5, abs=0.05)

    rows = dict(tools.read_metadata(written))
    assert rows["Latitude"] == "41.387400"
    assert rows["Longitude"] == "2.168600"
    assert rows["Altitude"] == "12.50 m"
    assert rows["Artist"] == "Tangerine GPS QA"

    cleaned = tools.remove_location(written, _ctx(), set())
    assert cleaned.name == "photo Metadata No Location.jpg"
    assert cleaned.suffix == ".jpg"
    assert tools.read_location(cleaned) is None
    remaining = dict(tools.read_metadata(cleaned))
    assert "Latitude" not in remaining and "Longitude" not in remaining
    assert remaining["Artist"] == "Tangerine GPS QA"
    assert remaining["DateTimeOriginal"] == "2020:01:02 03:04:05"


def test_write_metadata_image_keeps_existing_gps(tmp_path):
    source = tmp_path / "photo.jpg"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(source, "JPEG", quality=95)
    first = tools.write_metadata_image(
        source, {}, False, _ctx(), set(),
        {"latitude": -33.8688, "longitude": 151.2093})
    second = tools.write_metadata_image(
        first, {315: "Second pass"}, False, _ctx(), set())
    location = tools.read_location(second)
    assert location is not None
    assert location["latitude"] == pytest.approx(-33.8688, abs=1e-4)
    assert location["longitude"] == pytest.approx(151.2093, abs=1e-4)


def test_remove_location_rejects_non_images(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("hello", encoding="utf-8")
    with pytest.raises(engines.EngineError):
        tools.remove_location(source, _ctx(), set())


# ---------------------------------------------------------------------------
# 5. AVIF / BMP crop fix
# ---------------------------------------------------------------------------

@requires_heif
def test_crop_image_keeps_avif_format(tmp_path):
    source = tmp_path / "photo.avif"
    Image.new("RGB", (64, 48), (10, 200, 30)).save(source, "AVIF")
    out = tools.crop_image(source, (4, 4, 40, 40), _ctx(), set())
    assert out.suffix == ".avif"
    with Image.open(out) as result:
        result.load()
        assert result.format == "AVIF"
        assert result.size == (36, 36)


def test_crop_image_keeps_bmp_format(tmp_path):
    source = tmp_path / "photo.bmp"
    Image.new("RGB", (32, 24), (1, 2, 3)).save(source, "BMP")
    out = tools.crop_image(source, (0, 0, 16, 16), _ctx(), set())
    assert out.suffix == ".bmp"
    with Image.open(out) as result:
        assert result.format == "BMP"
        assert result.size == (16, 16)
