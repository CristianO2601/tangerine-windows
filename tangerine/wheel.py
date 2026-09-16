"""The radial conversion and tools fan overlay."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QWidget

from . import paths as app_paths
from . import settings, theme
from .icons import icon_for

log = logging.getLogger("tangerine")

EXTENT = theme.FAN_PETAL_RADIUS + 78.0
PETAL_W = 70.0
PETAL_H = 94.0


@dataclass
class FanItem:
    key: str
    label: str
    icon: str = ""
    kind: str = "conversion"


class TangerineWheel(QWidget):
    activated = Signal(list, str)

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.resize(int(EXTENT * 2), int(EXTENT * 2))

        self._items: list[FanItem] = []
        self._file_paths: list[str] = []
        self._hover = -1
        self._prompt = ("Tangerine", "")
        self._mode = "conversion"
        self._factory: Callable[[list[str]], Sequence[FanItem]] | None = None
        self._sound = None
        self._sound_disabled = False
        self._dark = theme.is_dark()

    # -- public API ----------------------------------------------------

    def set_factory(self, factory: Callable[[list[str]], Sequence[FanItem]]) -> None:
        self._factory = factory

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def set_items(self, items: Sequence[FanItem]) -> None:
        self._items = list(items)
        self._hover = -1
        self.update()

    def set_prompt(self, main: str, sub: str = "") -> None:
        self._prompt = (main, sub)
        self.update()

    def center_at(self, global_pos: QPoint) -> None:
        center = QPoint(global_pos)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            margin = int(EXTENT) - 60
            center.setX(min(max(center.x(), area.left() + margin), area.right() - margin))
            center.setY(min(max(center.y(), area.top() + margin), area.bottom() - margin))
        self.move(center.x() - int(EXTENT), center.y() - int(EXTENT))

    def update_cursor(self, global_pos: QPoint) -> None:
        self._update_hover(QPointF(self.mapFromGlobal(global_pos)))

    def file_paths(self) -> list[str]:
        return list(self._file_paths)

    def reset(self) -> None:
        self._items = []
        self._file_paths = []
        self._hover = -1
        self.update()

    # -- interaction ---------------------------------------------------

    def hit_test(self, local: QPointF) -> int:
        count = len(self._items)
        if count == 0:
            return -1
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        dx = local.x() - cx
        dy = local.y() - cy
        radius = math.hypot(dx, dy)
        if radius < theme.FAN_CENTER_RADIUS:
            return -1
        low = theme.FAN_PETAL_RADIUS - PETAL_H / 2.0 - 8
        high = theme.FAN_PETAL_RADIUS + PETAL_H / 2.0 + theme.FAN_HOVER_LIFT + 10
        if radius < low or radius > high:
            return -1
        angle = math.degrees(math.atan2(dy, dx))
        step = 360.0 / count
        half = min(step * 0.48, 62.0)
        for index in range(count):
            target = -90.0 + (index + 0.5) * step
            diff = (angle - target + 540.0) % 360.0 - 180.0
            if abs(diff) <= half:
                return index
        return -1

    def _update_hover(self, local: QPointF) -> None:
        index = self.hit_test(local)
        if index != self._hover:
            self._hover = index
            self.update()
            if index >= 0:
                self._play_highlight()

    def _play_highlight(self) -> None:
        if self._sound_disabled or not settings.get("soundsAndHapticsEnabled"):
            return
        try:
            if self._sound is None:
                from PySide6.QtMultimedia import QSoundEffect

                self._sound = QSoundEffect(self)
                self._sound.setSource(QUrl.fromLocalFile(str(app_paths.highlight_sound())))
                self._sound.setVolume(0.55)
            self._sound.play()
        except Exception:
            self._sound_disabled = True
            log.warning("Highlight sound disabled", exc_info=True)

    def _accept_copy(self, event) -> bool:
        if event.possibleActions() & Qt.CopyAction:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            return True
        event.ignore()
        return False

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        files: list[str] = []
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    files.append(url.toLocalFile())
        if not files:
            event.ignore()
            return
        self._file_paths = files
        if self._factory is not None:
            self.set_items(self._factory(files))
        if not self._items:
            event.ignore()
            return
        subtitle = Path(files[0]).name if len(files) == 1 else f"{len(files)} files"
        self._prompt = (self._prompt[0], subtitle)
        self.update()
        self._accept_copy(event)

    def dragMoveEvent(self, event) -> None:
        self._update_hover(event.position())
        self._accept_copy(event)

    def dragLeaveEvent(self, event) -> None:
        self._hover = -1
        self.update()

    def dropEvent(self, event) -> None:
        if not self._accept_copy(event):
            return
        index = self.hit_test(event.position())
        files = list(self._file_paths)
        if 0 <= index < len(self._items):
            key = self._items[index].key
            self.reset()
            self.hide()
            self.activated.emit(files, key)
        else:
            self.reset()
            self.hide()

    def mouseMoveEvent(self, event) -> None:
        self._update_hover(event.position())

    def leaveEvent(self, event) -> None:
        self._hover = -1
        self.update()

    # -- painting ------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette(self._dark)
        solid = str(settings.get("conversionFanTheme", "glass")).lower() == "solid"
        cx = self.width() / 2.0
        cy = self.height() / 2.0

        if solid:
            painter.setPen(QPen(QColor(palette["border"]), 1.5))
            painter.setBrush(QColor(palette["card"]))
            painter.drawEllipse(QPointF(cx, cy), EXTENT, EXTENT)
        else:
            gradient = QRadialGradient(cx, cy, EXTENT)
            glass = palette["glass"]
            gradient.setColorAt(0.0, QColor(*glass))
            gradient.setColorAt(0.78, QColor(*glass))
            gradient.setColorAt(1.0, QColor(glass[0], glass[1], glass[2], 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(QPointF(cx, cy), EXTENT, EXTENT)

            edge = palette["glass_edge"]
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(*edge), 1.2))
            rim = theme.FAN_PETAL_RADIUS + PETAL_H / 2.0 + 18
            painter.drawEllipse(QPointF(cx, cy), rim, rim)

        count = len(self._items)
        step = 360.0 / count if count else 360.0
        for index, item in enumerate(self._items):
            angle = -90.0 + (index + 0.5) * step
            radians = math.radians(angle)
            lift = theme.FAN_HOVER_LIFT if index == self._hover else 0.0
            px = cx + math.cos(radians) * (theme.FAN_PETAL_RADIUS + lift)
            py = cy + math.sin(radians) * (theme.FAN_PETAL_RADIUS + lift)
            hovered = index == self._hover

            shape = QPainterPath()
            shape.addRoundedRect(
                QRectF(-PETAL_W / 2.0, -PETAL_H / 2.0, PETAL_W, PETAL_H),
                PETAL_W * 0.42,
                PETAL_W * 0.42,
            )
            transform = QTransform()
            transform.translate(px, py)
            transform.rotate(angle + 90.0)
            mapped = transform.map(shape)

            shadow = QTransform()
            shadow.translate(px + 2.0, py + 3.5)
            shadow.rotate(angle + 90.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 56 if self._dark else 30))
            painter.drawPath(shadow.map(shape))

            if solid:
                painter.setPen(QPen(QColor(theme.ACCENT_DARK), 1.2))
                painter.setBrush(
                    QColor(theme.ACCENT_BRIGHT if hovered else theme.ACCENT)
                )
            else:
                painter.setPen(
                    QPen(
                        QColor(theme.ACCENT_DARK) if hovered else QColor(*palette["petal_edge"]),
                        1.2,
                    )
                )
                painter.setBrush(
                    QColor(theme.ACCENT) if hovered else QColor(*palette["petal"])
                )
            painter.drawPath(mapped)

            icon_font = QFont(self.font())
            icon_font.setFamilies(["Segoe UI Emoji", self.font().family()])
            icon_font.setPixelSize(22)
            painter.setFont(icon_font)
            painter.setPen(
                QColor("#FFFFFF") if (solid or hovered) else QColor(theme.ACCENT)
            )
            painter.drawText(
                QRectF(px - PETAL_W / 2.0, py - 36, PETAL_W, 28),
                int(
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                ),
                item.icon or icon_for(item.key),
            )

            label_font = QFont(self.font())
            label_font.setPixelSize(10)
            label_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(label_font)
            painter.setPen(
                QColor("#FFFFFF") if (solid or hovered) else QColor(palette["petal_text"])
            )
            lines = self._wrap(item.label, PETAL_W - 10, label_font)
            line_height = 12.5
            start_y = py + 0.5
            for line_index, line in enumerate(lines):
                painter.drawText(
                    QRectF(px - PETAL_W / 2.0, start_y + line_index * line_height, PETAL_W, line_height),
                    int(
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                    ),
                    line,
                )

        hovered_item = self._items[self._hover] if 0 <= self._hover < count else None
        main_text = hovered_item.label if hovered_item else self._prompt[0]
        sub_text = self._prompt[1]

        if solid:
            painter.setPen(QPen(QColor(palette["border"]), 1.2))
            painter.setBrush(QColor(palette["card_alt"]))
        else:
            painter.setPen(QPen(QColor(*palette["petal_edge"]), 1.0))
            painter.setBrush(QColor(*palette["glass"]))
        painter.drawEllipse(
            QPointF(cx, cy), theme.FAN_CENTER_RADIUS, theme.FAN_CENTER_RADIUS
        )

        main_font = QFont(self.font())
        main_font.setPixelSize(13)
        main_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(main_font)
        painter.setPen(
            QColor(theme.ACCENT) if hovered_item else QColor(palette["text"])
        )
        main_lines = self._wrap(main_text, theme.FAN_CENTER_RADIUS * 2 - 12, main_font)
        offset = -7 if sub_text else 0
        for line_index, line in enumerate(main_lines[:2]):
            painter.drawText(
                QRectF(cx - theme.FAN_CENTER_RADIUS, cy + offset - 16 + line_index * 14, theme.FAN_CENTER_RADIUS * 2, 14),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                line,
            )
        if sub_text:
            sub_font = QFont(self.font())
            sub_font.setPixelSize(10)
            painter.setFont(sub_font)
            painter.setPen(QColor(palette["text_dim"]))
            sub_lines = self._wrap(sub_text, theme.FAN_CENTER_RADIUS * 2 - 14, sub_font)
            painter.drawText(
                QRectF(cx - theme.FAN_CENTER_RADIUS, cy + 8, theme.FAN_CENTER_RADIUS * 2, 13),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                sub_lines[0] if sub_lines else "",
            )
        painter.end()

    def _wrap(self, text: str, width: float, font: QFont) -> list[str]:
        metrics = QFontMetricsF(font)
        words = str(text).split()
        if not words:
            return []
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if metrics.horizontalAdvance(candidate) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) > 2:
            lines = lines[:2]
            last = lines[1]
            while last and metrics.horizontalAdvance(last + "\u2026") > width:
                last = last[:-1]
            lines[1] = last + "\u2026"
        return lines
