"""Frosted HUD backdrops: screen capture + blur for the translucent surfaces.

Every HUD surface (the wheel, the progress card, the editors) is made of a
translucent material that lets the desktop behind it shine through.  A
:class:`HudBackdrop` grabs that desktop region, downsamples it, blurs it with
Pillow and paints it clipped to a rounded rectangle with a warm ``wash`` on
top.

Typical use from a widget::

    self._backdrop = HudBackdrop()

    def showEvent(self, event):
        super().showEvent(event)
        self._backdrop.capture(self.frameGeometry())

    def moveEvent(self, event):
        super().moveEvent(event)
        self._backdrop.capture(self.frameGeometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        wash = theme.qcolor(theme.hud(theme.is_dark())["wash"])
        self._backdrop.paint(painter, QRectF(self.rect()), wash, 22.0)

Only QtCore/QtGui are imported, so the module stays import-safe in headless
contexts (tests, packaging scripts).
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath

log = logging.getLogger("tangerine")

try:  # Pillow is a hard requirement; never break importing the app without it.
    from PIL import Image, ImageFilter
except Exception:  # pragma: no cover - defensive, Pillow ships in requirements
    Image = None
    ImageFilter = None

DOWNSAMPLE = 6
BLUR_RADIUS = 10.0
THROTTLE_MS = 250


class HudBackdrop:
    """Blurred desktop-backdrop cache for one translucent surface.

    ``capture`` is cheap enough to call on every move: a repeated capture of
    the same rectangle within the throttle window is ignored, so the repeated
    grabs never run on every paint.  *throttle_ms* may be ``None`` to accept
    the default (a tolerant constructor convenience).
    """

    def __init__(self, throttle_ms: int | None = THROTTLE_MS):
        self._image: QImage | None = None
        self._rect = QRect()
        self._stamp = 0.0
        self._throttle = (THROTTLE_MS if throttle_ms is None
                          else max(0, int(throttle_ms))) / 1000.0

    # -- public API ---------------------------------------------------------

    def has_capture(self) -> bool:
        """Whether a usable capture is cached."""
        return self._image is not None and not self._image.isNull()

    def clear(self) -> None:
        """Drop the cached capture; the next paint falls back to the wash."""
        self._image = None
        self._rect = QRect()

    def capture(self, global_rect: QRect) -> None:
        """Capture *global_rect* (virtual-desktop pixels) and cache the blur.

        Failures (no screen, ``grabWindow`` refused, DPI oddities) clear the
        cache silently: :meth:`paint` then only draws the wash.
        """
        if global_rect.isEmpty() or global_rect.width() < 2 or global_rect.height() < 2:
            self.clear()
            return
        rect = QRect(global_rect)
        now = time.monotonic()
        if rect == self._rect and (now - self._stamp) < self._throttle:
            return
        self._rect = rect
        self._stamp = now
        try:
            image, ratio = self._grab(rect)
            if image is None or image.isNull():
                raise ValueError("empty screen grab")
            blurred = self._blur(self._shrink(image))
            blurred.setDevicePixelRatio(ratio)
            self._image = blurred
        except Exception:
            log.debug("Screen backdrop capture failed; using the wash only",
                      exc_info=True)
            self._image = None

    def paint(self, p: QPainter, rect: QRectF, wash: QColor, radius: float = 0.0) -> bool:
        """Paint the blurred capture plus *wash* clipped to *rect*.

        Returns ``True`` when a capture was drawn, ``False`` when the surface
        fell back to the wash alone.  *radius* rounds the clipped rectangle.
        """
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.save()
        p.setClipPath(path)
        painted = False
        image = self._image
        if image is not None and not image.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.drawImage(rect, image, QRectF(0, 0, image.width(), image.height()))
            painted = True
        p.fillPath(path, wash)
        p.restore()
        return painted

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _grab(rect: QRect) -> tuple[QImage | None, float]:
        """Grab *rect* from the screen that owns its centre."""
        screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return None, 1.0
        x, y, width, height = rect.x(), rect.y(), rect.width(), rect.height()
        image = screen.grabWindow(0, x, y, width, height).toImage()
        if image.isNull() or image.width() < 2 or image.height() < 2:
            # Some platforms interpret the coordinates relative to the screen.
            origin = screen.geometry().topLeft()
            image = screen.grabWindow(
                0, x - origin.x(), y - origin.y(), width, height).toImage()
        ratio = float(screen.devicePixelRatio() or 1.0)
        return image, ratio

    @staticmethod
    def _shrink(image: QImage) -> QImage:
        """Downsample the grab so the blur stays cheap on large regions."""
        width = max(2, image.width() // DOWNSAMPLE)
        height = max(2, image.height() // DOWNSAMPLE)
        return image.scaled(
            width,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    @staticmethod
    def _blur(image: QImage) -> QImage:
        """Gaussian-blur a QImage through Pillow (identity without Pillow)."""
        if Image is None or ImageFilter is None:
            return image
        converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(converted.constBits())
        pillow = Image.frombuffer(
            "RGBA",
            (converted.width(), converted.height()),
            raw,
            "raw",
            "RGBA",
            converted.bytesPerLine(),
            1,
        )
        pillow = pillow.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
        data = pillow.tobytes("raw", "RGBA")
        blurred = QImage(
            data,
            pillow.width,
            pillow.height,
            pillow.width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        return image if blurred.isNull() else blurred
