from __future__ import annotations

import ctypes
import logging
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import actions, catalog, i18n, paths, settings, theme
from .monitor import DragMonitor
from .wheel import FanItem, TangerineWheel

log = logging.getLogger("tangerine")


def _write_crash_log(message: str) -> None:
    try:
        with (paths.data_dir() / "crash.log").open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


def _show_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "Tangerine", 0x10)
    except Exception:
        pass


def _install_excepthooks() -> None:
    def handle_exception(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Unhandled exception: %s", exc, exc_info=(exc_type, exc, tb))
        _write_crash_log(text)

    def handle_thread_exception(args):
        if issubclass(args.exc_type, SystemExit):
            return
        text = "".join(
            traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback
            )
        )
        log.error(
            "Unhandled exception in thread %s: %s",
            args.thread.name if args.thread else "?",
            args.exc_value,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _write_crash_log(text)

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception


def _warm_catalog() -> None:
    try:
        catalog.available_engines()
    except Exception:
        pass


class Controller(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self._mode = "conversion"
        self._jobs = []
        self._labels = {}
        self._settings_window = None

        self.wheel = TangerineWheel()
        self.wheel.set_factory(self._factory)
        self.wheel.activated.connect(self._activated)

        self.monitor = DragMonitor(self)
        self.monitor.wheelShown.connect(self._show_wheel)
        self.monitor.wheelMoved.connect(self._move_wheel)
        self.monitor.wheelHidden.connect(self._hide_wheel)
        self.monitor.wheelRefreshed.connect(self._refresh_wheel)
        self.monitor.keyboardTriggered.connect(self._keyboard_wheel)

        self.tray = QSystemTrayIcon(QIcon(str(paths.icon_path())), self)
        self.tray.setToolTip(i18n.tr("tray.tooltip"))
        self._menu = None
        self._active_menu = None
        self._build_tray_menu()
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        i18n.add_listener(self._language_changed)

    # -- localization ----------------------------------------------------------
    def _build_tray_menu(self):
        menu = QMenu()
        self._active_menu = menu.addMenu(i18n.tr("tray.active"))
        self._active_menu.aboutToShow.connect(self._rebuild_active)
        menu.addSeparator()
        settings_action = menu.addAction(i18n.tr("tray.settings"))
        settings_action.triggered.connect(self.open_settings)
        update_action = menu.addAction(i18n.tr("tray.check_updates"))
        update_action.triggered.connect(self._check_updates)
        menu.addSeparator()
        quit_action = menu.addAction(i18n.tr("tray.quit"))
        quit_action.triggered.connect(self._quit)
        self._menu = menu
        self.tray.setContextMenu(menu)

    def _language_changed(self, code=None):
        try:
            self.tray.setToolTip(i18n.tr("tray.tooltip"))
            self._build_tray_menu()
            files = self.wheel.file_paths()
            if files:
                self._refresh_wheel(self._mode)
            self.wheel.update()
        except Exception:
            log.exception("Could not refresh the UI after a language change")

    # -- wheel -----------------------------------------------------------------
    def _items_for(self, files, mode):
        file_list = list(files) if files else []
        sources = [Path(f) for f in file_list]
        if mode == "tools":
            items = []
            for tool in catalog.tools_for(sources):
                label = i18n.tr("tool." + tool.id)
                items.append(FanItem(tool.id, label, kind="tool"))
                self._labels[tool.id] = label
            return items
        items = []
        for conversion in catalog.conversions_for(sources):
            label = i18n.tr("conv." + conversion.target_ext)
            items.append(FanItem(conversion.target_ext, label, kind="conversion"))
            self._labels[conversion.target_ext] = label
        return items

    def _factory(self, files):
        return self._items_for(files, self._mode)

    def _show_wheel(self, pos, files, mode):
        self._mode = mode
        self.wheel.set_keyboard_mode(False)
        self.wheel.set_mode(mode)
        if files:
            self.wheel.set_files(files)
            self.wheel.set_items(self._items_for(files, mode))
        elif self.wheel.isVisible():
            # Re-show during the same gesture without a readable payload
            # (Windows does not always publish the drag clipboard): keep the
            # petals dragEnter already filled and abort the farewell in
            # flight instead of wiping them.
            self.wheel.cancel_dismiss()
        else:
            self.wheel.set_items(self._items_for(files, mode))
        self.wheel.center_at(pos)
        self.wheel.show()

    def _keyboard_wheel(self, pos, files, mode):
        """Shift+Enter on an Explorer selection (plan 1.5): keyboard wheel."""
        self._show_wheel(pos, files, mode)
        self.wheel.set_keyboard_mode(True)

    def _refresh_wheel(self, mode):
        self._mode = mode
        self.wheel.set_mode(mode)
        files = self.wheel.file_paths()
        if not files:
            return
        self.wheel.set_items(self._items_for(files, mode), animate=True)

    def _move_wheel(self, pos):
        self.wheel.update_cursor(pos)

    def _hide_wheel(self):
        self.wheel.set_keyboard_mode(False)
        self.wheel.dismiss()

    def _activated(self, files, key):
        self.monitor.notify_dropped()
        if not files:
            return
        label = self._labels.get(key)
        if self._mode == "tools":
            window = actions.run_tool(files, key, None, label)
        else:
            window = actions.run_conversions(files, key, None, None)
        self._track(window)

    def _track(self, window):
        if window is None:
            return
        self._jobs.append(window)
        window.job.finished.connect(lambda *_a, w=window: self._forget(w))
        window.job.failed.connect(lambda *_a, w=window: self._forget(w))

    def _forget(self, window):
        if window in self._jobs:
            self._jobs.remove(window)

    def _rebuild_active(self):
        self._active_menu.clear()
        if not self._jobs:
            self._active_menu.addAction(i18n.tr("tray.nothing_active")).setEnabled(False)
            return
        for window in list(self._jobs):
            action = self._active_menu.addAction(
                window.windowTitle() or i18n.tr("tray.working"))
            action.triggered.connect(lambda _=False, w=window: self._raise(w))

    @staticmethod
    def _raise(window):
        window.show()
        window.raise_()

    # -- tray ------------------------------------------------------------------
    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_settings()

    def open_settings(self):
        if self._settings_window is not None and self._settings_window.isVisible():
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return self._settings_window
        try:
            from . import settings_window

            self._settings_window = settings_window.open_settings()
        except ImportError:
            self.tray.showMessage(
                i18n.tr("app.name"),
                i18n.tr("tray.settings_unavailable"),
                QSystemTrayIcon.MessageIcon.Warning,
                4000,
            )
            self._settings_window = None
        return self._settings_window

    def _check_updates(self):
        QMessageBox.information(
            None,
            i18n.tr("app.name"),
            i18n.tr("tray.update_message", version=paths.APP_VERSION),
        )

    def _quit(self):
        if self._jobs:
            choice = QMessageBox.question(
                None,
                i18n.tr("app.name"),
                i18n.tr("tray.quit_running"),
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
        for window in list(self._jobs):
            job = getattr(window, "job", None)
            if job is not None:
                job.cancel()
        self.monitor.stop()
        self.app.quit()

    def notify_welcome(self):
        self.tray.showMessage(
            i18n.tr("app.name"),
            i18n.tr("tray.welcome"),
            QSystemTrayIcon.MessageIcon.Information,
            9000,
        )
        settings.set("welcomeShown", True)
        settings.save()


def _already_running(app):
    tray = QSystemTrayIcon(QIcon(str(paths.icon_path())))
    tray.show()
    tray.showMessage(
        i18n.tr("app.name"), i18n.tr("tray.already_running"), 5000)
    QTimer.singleShot(5200, app.quit)
    app.exec()
    return 1


def _run():
    app = QApplication(sys.argv)
    app.setApplicationName("Tangerine")
    app.setApplicationVersion(paths.APP_VERSION)
    app.setOrganizationName("Tangerine")
    app.setWindowIcon(QIcon(str(paths.icon_path())))
    app.setQuitOnLastWindowClosed(False)
    theme.apply_app_theme()

    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("No system tray available")
        return 1

    lock = QLockFile(str(paths.data_dir() / "tangerine.lock"))
    if not lock.tryLock(0):
        return _already_running(app)

    controller = Controller(app)
    QTimer.singleShot(700, _warm_catalog)
    if not settings.get("welcomeShown"):
        controller.notify_welcome()
    return app.exec()


def main():
    logging.basicConfig(
        filename=str(paths.log_file()),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    _install_excepthooks()
    try:
        return _run()
    except Exception as exc:
        text = (
            f"Tangerine failed to start: {exc}\n\n"
            + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        )
        log.error("Tangerine failed to start: %s", exc, exc_info=True)
        _write_crash_log(text)
        _show_error(text)
        return 1
