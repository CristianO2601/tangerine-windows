"""Drag-modifier monitoring, mirroring the macOS DragGestureMonitor.

The monitor samples public state only: pointer button, modifier keys, the
foreground window and the OLE drag clipboard. No input hooks are installed.
"""

from __future__ import annotations

import ctypes
import math
import os
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, QPoint, QTimer, Signal

from . import dragfiles, selection, settings

user32 = ctypes.windll.user32

VK_LBUTTON = 0x01
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C

MODIFIER_KEYS = {
    "ctrl": (VK_CONTROL,),
    "alt": (VK_MENU,),
    "shift": (VK_SHIFT,),
    "win": (VK_LWIN, VK_RWIN),
}

FOREGROUND_ALLOWLIST = {
    "CabinetWClass",
    "ExploreWClass",
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "XamlExplorerHostIslandWindow",
}

IDLE_INTERVAL_MS = 100
ACTIVE_INTERVAL_MS = 16
MOVEMENT_THRESHOLD = 8.0
DROP_COOLDOWN_S = 0.6
LONG_PRESS_S = 0.7


def _is_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class DragMonitor(QObject):
    wheelShown = Signal(object, object, str)
    wheelMoved = Signal(object)
    wheelHidden = Signal()
    wheelRefreshed = Signal(str)
    keyboardTriggered = Signal(object, object, str)

    _selectionReady = Signal(object, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(IDLE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._button_down = False
        self._anchor: QPoint | None = None
        self._visible = False
        self._cooldown_until = 0.0
        self._last_clip_check = 0.0
        self._last_files: list[str] | None = None
        self._mode: str | None = None
        self._enter_down = False
        self._selection_busy = False
        self._press_started = 0.0
        self._long_press_fired = False
        self._touch_mode = False
        self._selectionReady.connect(self.keyboardTriggered)

    def stop(self) -> None:
        self._timer.stop()

    def notify_dropped(self) -> None:
        self._visible = False
        self._mode = None
        self._last_files = None
        self._cooldown_until = time.monotonic() + DROP_COOLDOWN_S

    # -- polling -------------------------------------------------------

    def _cursor(self) -> QPoint:
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return QPoint(point.x, point.y)

    def _set_active(self, active: bool) -> None:
        interval = ACTIVE_INTERVAL_MS if active else IDLE_INTERVAL_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _held_modifiers(self) -> set[str]:
        return {
            name
            for name, vks in MODIFIER_KEYS.items()
            if any(_is_down(vk) for vk in vks)
        }

    def _mode_for_current_modifiers(self) -> str | None:
        held = self._held_modifiers()
        if not held:
            return None
        tools_mask = settings.parse_mask(settings.get("toolsWheelDragModifierMask"))
        conversion_mask = settings.parse_mask(
            settings.get("conversionWheelDragModifierMask")
        )
        if tools_mask and tools_mask <= held:
            return "tools"
        if conversion_mask and conversion_mask <= held:
            return "conversion"
        return None

    def _drag_files(self) -> list[str] | None:
        now = time.monotonic()
        if now - self._last_clip_check < 0.2:
            return self._last_files
        self._last_clip_check = now
        self._last_files = dragfiles.current_drag_files()
        return self._last_files

    def _foreground_allows(self) -> bool:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value in FOREGROUND_ALLOWLIST

    def _tick(self) -> None:
        button = _is_down(VK_LBUTTON)
        self._poll_keyboard(button)
        if button and not self._button_down:
            self._button_down = True
            self._anchor = self._cursor()
            self._last_files = None
            self._last_clip_check = 0.0
            self._mode = None
            self._press_started = time.monotonic()
            self._long_press_fired = False
            self._touch_mode = False
            self._set_active(True)
        if not button:
            if self._button_down:
                self._button_down = False
                self._anchor = None
                self._mode = None
                self._long_press_fired = False
                self._touch_mode = False
                self._set_active(False)
            if self._visible:
                self._visible = False
                self.wheelHidden.emit()
            return

        cursor = self._cursor()
        if self._anchor is None:
            self._anchor = cursor
            return

        if self._visible:
            self.wheelMoved.emit(cursor)
            mode = self._mode_for_current_modifiers()
            if mode is None and self._touch_mode:
                mode = "conversion"
            if mode is None:
                self._visible = False
                self._mode = None
                self.wheelHidden.emit()
            elif mode != self._mode:
                self._mode = mode
                self.wheelRefreshed.emit(mode)
            return

        if self._maybe_touch_long_press(cursor):
            return

        if time.monotonic() < self._cooldown_until:
            return
        distance = math.hypot(
            cursor.x() - self._anchor.x(), cursor.y() - self._anchor.y()
        )
        if distance < MOVEMENT_THRESHOLD:
            return
        mode = self._mode_for_current_modifiers()
        if mode is None:
            return
        files = self._drag_files()
        if files is None and not self._foreground_allows():
            return
        self._mode = mode
        self._visible = True
        self.wheelShown.emit(cursor, files, mode)

    # -- keyboard / touch triggers --------------------------------------

    def _poll_keyboard(self, button: bool) -> None:
        """Shift+Enter with an Explorer selection opens the wheel (plan 1.5)."""
        enter = _is_down(VK_RETURN)
        pressed = enter and not self._enter_down
        self._enter_down = enter
        if not pressed or button or self._button_down or self._selection_busy:
            return
        hwnd = selection.foreground_explorer_hwnd()
        if hwnd is None:
            return
        mode = self._mode_for_current_modifiers()
        if mode is None:
            return
        cursor = self._cursor()
        self._selection_busy = True

        def worker() -> None:
            try:
                files = selection.explorer_selection(hwnd)
            except Exception:
                files = []
            finally:
                self._selection_busy = False
            if files:
                self._selectionReady.emit(cursor, files, mode)

        threading.Thread(
            target=worker, name="tangerine-enter-selection", daemon=True
        ).start()

    def _maybe_touch_long_press(self, cursor: QPoint) -> bool:
        """Touch mode: hold a drag for >=700 ms without modifiers → wheel."""
        if self._long_press_fired or self._visible:
            return False
        if not bool(settings.get("touchLongPressEnabled")):
            return False
        if self._held_modifiers():
            return False
        if time.monotonic() < self._cooldown_until:
            return False
        if time.monotonic() - self._press_started < LONG_PRESS_S:
            return False
        files = self._drag_files()
        if not files:
            return False
        self._long_press_fired = True
        self._touch_mode = True
        self._mode = "conversion"
        self._visible = True
        self.wheelShown.emit(cursor, files, "conversion")
        return True
