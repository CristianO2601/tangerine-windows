"""The photo canvases must never keep a full-resolution bitmap alive.

Regression coverage for the RAM blow-up where a 50-100 MP photo kept a
full-resolution PIL buffer plus several full-size conversion copies for the
whole lifetime of the crop/redact/annotate dialogs. The canvases now display a
downscaled copy (longest edge ``DISPLAY_MAX``) while every coordinate mapping
and every export stays in full-resolution image pixels.
"""

import ctypes
import gc
import sys
import time
from ctypes import wintypes

import pytest
from PIL import Image, ImageDraw

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from tangerine import progress
from tangerine.editors.images import (
    AnnotateDialog,
    CropImageDialog,
    EditPhotoDialog,
    RedactPhotoDialog,
)
from tangerine.editors.ui.canvas import DISPLAY_MAX
from tangerine.engines import Ctx

BIG_SIZE = (8000, 6000)
ORANGE_BOX = (400, 300, 200, 100)


@pytest.fixture(scope="session")
def big_photo(tmp_path_factory):
    """An 8000x6000 JPEG with an orange rectangle at a known pixel box."""
    path = tmp_path_factory.mktemp("big") / "big.jpg"
    image = Image.new("RGB", BIG_SIZE, (12, 24, 36))
    draw = ImageDraw.Draw(image)
    x, y, w, h = ORANGE_BOX
    draw.rectangle((x, y, x + w - 1, y + h - 1), fill=(255, 140, 0))
    image.save(path, "JPEG", quality=40)
    image.close()
    return path


def pump(qapp, seconds: float = 0.05) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


def close_dialog(qapp, dialog) -> None:
    dialog.close()
    dialog.deleteLater()
    pump(qapp)
    gc.collect()
    pump(qapp)


def _mouse_event(kind, pos: QPointF) -> QMouseEvent:
    return QMouseEvent(
        kind, pos, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def working_set_bytes() -> int:
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    ok = psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    assert ok
    return int(counters.WorkingSetSize)


def test_display_pixmap_is_downscaled(qapp, big_photo):
    dialog = CropImageDialog(big_photo)
    try:
        canvas = dialog.canvas
        assert canvas.image_size == BIG_SIZE
        assert not canvas.pixmap.isNull()
        assert max(canvas.pixmap.width(), canvas.pixmap.height()) <= DISPLAY_MAX
        assert canvas.pixmap.width() == DISPLAY_MAX
        assert canvas.display_scale == pytest.approx(BIG_SIZE[0] / DISPLAY_MAX)
    finally:
        close_dialog(qapp, dialog)


def test_full_resolution_mapping(qapp, big_photo):
    dialog = CropImageDialog(big_photo)
    try:
        canvas = dialog.canvas
        canvas.resize(620, 420)
        canvas._layout()

        x, y, w, h = ORANGE_BOX
        top_left = canvas.to_image(canvas.to_widget(float(x), float(y)))
        bottom_right = canvas.to_image(canvas.to_widget(float(x + w), float(y + h)))
        assert top_left == pytest.approx((float(x), float(y)), abs=2.0)
        assert bottom_right == pytest.approx((float(x + w), float(y + h)), abs=2.0)

        center = canvas.to_widget(BIG_SIZE[0] / 2, BIG_SIZE[1] / 2)
        assert center.x() == pytest.approx(canvas.offset.x() + 280.0, abs=1.0)
        assert center.y() == pytest.approx(canvas.offset.y() + 210.0, abs=1.0)

        assert canvas.clamp_box(7900.0, 5900.0, 1000.0, 1000.0) == (
            7900.0, 5900.0, 100.0, 100.0)
    finally:
        close_dialog(qapp, dialog)


def test_crop_drag_moves_in_full_resolution_pixels(qapp, big_photo):
    dialog = CropImageDialog(big_photo)
    try:
        canvas = dialog.canvas
        canvas.resize(620, 420)
        canvas._layout()
        canvas.rect = [3000.0, 2000.0, 2000.0, 1000.0]

        start = canvas.to_widget(4000.0, 2500.0)
        canvas.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, start))
        assert canvas._mode == "move"
        canvas.mouseMoveEvent(_mouse_event(
            QEvent.Type.MouseMove, start + QPointF(14.0, 7.0)))
        assert canvas.rect == pytest.approx([3200.0, 2100.0, 2000.0, 1000.0], abs=2.0)
    finally:
        close_dialog(qapp, dialog)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows working-set measurement")
def test_open_close_working_set_delta_is_small(qapp, big_photo):
    gc.collect()
    pump(qapp)
    before = working_set_bytes()

    dialog = CropImageDialog(big_photo)
    pump(qapp)
    loaded = working_set_bytes()

    dialog.close()
    dialog.deleteLater()
    pump(qapp)
    del dialog
    gc.collect()
    pump(qapp)
    closed = working_set_bytes()

    print(
        f"\nworking set: before={before / 2 ** 20:.1f} MB "
        f"loaded={loaded / 2 ** 20:.1f} MB closed={closed / 2 ** 20:.1f} MB "
        f"delta_open={(loaded - before) / 2 ** 20:.1f} MB "
        f"delta_closed={(closed - before) / 2 ** 20:.1f} MB"
    )
    assert loaded - before < 400 * 2 ** 20
    assert closed - before < 400 * 2 ** 20


@pytest.fixture
def sync_jobs(monkeypatch):
    outputs = []

    def fake_run_job(title, work, parent=None):
        outputs.extend(work(Ctx()))
        return None

    monkeypatch.setattr(progress, "run_job", fake_run_job)
    return outputs


def test_crop_export_is_full_resolution(qapp, big_photo, sync_jobs):
    dialog = CropImageDialog(big_photo)
    try:
        x, y, w, h = ORANGE_BOX
        dialog.canvas.rect = [float(x), float(y), float(w), float(h)]
        dialog._accept_clicked()
    finally:
        close_dialog(qapp, dialog)

    assert len(sync_jobs) == 1
    with Image.open(sync_jobs[0]) as out:
        assert out.size == (w, h)
        pixel = out.convert("RGB").getpixel((w // 2, h // 2))
    assert pixel[0] > 200 and pixel[1] > 100 and pixel[2] < 60


def test_redact_export_is_full_resolution(qapp, big_photo, sync_jobs):
    dialog = RedactPhotoDialog(big_photo)
    try:
        dialog.mode.setCurrentIndex(1)
        x, y, w, h = ORANGE_BOX
        dialog.canvas.boxes.append({
            "x": float(x), "y": float(y), "w": float(w), "h": float(h),
            "mode": "blur", "color": "#000000",
        })
        dialog._accept_clicked()
    finally:
        close_dialog(qapp, dialog)

    assert len(sync_jobs) == 1
    with Image.open(sync_jobs[0]) as out:
        assert out.size == BIG_SIZE


def test_annotate_export_is_full_resolution(qapp, big_photo, sync_jobs):
    dialog = AnnotateDialog(big_photo)
    ax, ay, aw, ah = 1000, 1000, 400, 200
    try:
        dialog.canvas.ops.append({
            "type": "rect", "x1": float(ax), "y1": float(ay),
            "x2": float(ax + aw), "y2": float(ay + ah),
            "color": "#F87800", "width": 3,
        })
        dialog._accept_clicked()
    finally:
        close_dialog(qapp, dialog)

    assert len(sync_jobs) == 1
    with Image.open(sync_jobs[0]) as out:
        assert out.size == BIG_SIZE
        rgb = out.convert("RGB")
        on_border = rgb.getpixel((ax, ay + ah // 2))
        inside = rgb.getpixel((ax + aw // 2, ay + ah // 2))
    assert on_border[0] > 180 and on_border[1] < 180 and on_border[2] < 90
    assert sum(inside) < 200


def test_large_jpeg_keeps_no_full_resolution_pixmap(qapp, big_photo):
    dialog = CropImageDialog(big_photo)
    try:
        canvas = dialog.canvas
        assert canvas.pixmap.width() * canvas.pixmap.height() <= DISPLAY_MAX ** 2
        assert canvas.image is not None
        assert max(canvas.image.size) <= DISPLAY_MAX
    finally:
        close_dialog(qapp, dialog)


def test_edit_photo_preview_is_downscaled(qapp, big_photo):
    dialog = EditPhotoDialog(big_photo)
    try:
        assert max(dialog._image.size) <= 520
    finally:
        close_dialog(qapp, dialog)
