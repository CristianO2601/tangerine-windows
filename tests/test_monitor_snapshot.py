"""Multi-file drags and the sticky wheel (v1.8).

Two field problems on Windows 11:

* Shift+click semantics collapse the Explorer selection while the drag
  starts, so the OLE payload carries a single file; the monitor keeps a
  rolling snapshot of the selection and hydrates the payload from it.
* The wheel only stayed while Shift was held, which made screenshots
  impossible mid-gesture; a configurable hotkey now opens a sticky wheel
  that survives the key release.
"""

import time

import pytest
from PySide6.QtCore import QPoint

from tangerine import monitor as monitor_module
from tangerine import settings
from tangerine.monitor import BUTTON_RELEASE_SAMPLES, DragMonitor


class _ScriptedKeys:
    """Left button, the toggle combo (Ctrl+Shift+W) and everything else."""

    def __init__(self):
        self.left = False
        self.combo = False

    def __call__(self, vk: int) -> bool:
        if vk == monitor_module.VK_LBUTTON:
            return self.left
        if self.combo and vk in (
            monitor_module.VK_CONTROL,
            monitor_module.VK_SHIFT,
            0x57,
        ):
            return True
        return False


def _wait_until(qapp, predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def rig(qapp, monkeypatch):
    keys = _ScriptedKeys()
    state = {"pos": QPoint(100, 100), "files": None, "selection": []}
    monkeypatch.setattr(monitor_module, "_is_down", keys)
    monkeypatch.setattr(
        DragMonitor, "_mode_for_current_modifiers", lambda self: "conversion"
    )
    monkeypatch.setattr(DragMonitor, "_drag_files", lambda self: state["files"])
    monkeypatch.setattr(DragMonitor, "_cursor", lambda self: QPoint(state["pos"]))
    monkeypatch.setattr(
        monitor_module.selection, "foreground_explorer_hwnd", lambda: 4242
    )
    monkeypatch.setattr(
        monitor_module.selection,
        "explorer_selection",
        lambda hwnd: list(state["selection"]),
    )
    original_get = settings.get
    monkeypatch.setattr(
        monitor_module.settings,
        "get",
        lambda key, default=None: (
            "ctrl+shift+w" if key == "wheelToggleHotkey" else original_get(key, default)
        ),
    )
    monitor = DragMonitor()
    monitor.stop()
    events: list[tuple] = []
    monitor.wheelShown.connect(
        lambda pos, files, mode: events.append(("shown", files, mode))
    )
    monitor.stickyTriggered.connect(
        lambda pos, files, mode: events.append(("sticky", files, mode))
    )
    monitor.wheelHidden.connect(lambda: events.append(("hidden",)))
    return {"monitor": monitor, "keys": keys, "state": state, "events": events}


def _release(monitor) -> None:
    for _ in range(BUTTON_RELEASE_SAMPLES):
        monitor._tick()


def test_hydration_rules(rig):
    monitor = rig["monitor"]
    now = time.monotonic()

    monitor._snapshot = (4242, ["a.jpg", "b.jpg"], now - 10.0)
    assert monitor._hydrate_from_snapshot(["a.jpg"]) == ["a.jpg"]

    monitor._snapshot = (9999, ["a.jpg", "b.jpg"], now)
    assert monitor._hydrate_from_snapshot(["a.jpg"]) == ["a.jpg"]

    monitor._snapshot = (4242, ["a.jpg", "b.jpg"], now)
    assert monitor._hydrate_from_snapshot(["a.jpg"]) == ["a.jpg", "b.jpg"]
    assert monitor._hydrate_from_snapshot(["x.png"]) == ["x.png"]
    assert monitor._hydrate_from_snapshot(["a.jpg", "z.pdf"]) == ["a.jpg", "z.pdf"]
    assert monitor._hydrate_from_snapshot(None) == ["a.jpg", "b.jpg"]

    monitor._snapshot = None
    assert monitor._hydrate_from_snapshot(None) is None


def test_tick_hydrates_a_collapsed_payload(rig):
    monitor = rig["monitor"]
    state = rig["state"]
    monitor._snapshot = (4242, ["a.jpg", "b.jpg", "c.jpg"], time.monotonic())
    state["files"] = ["a.jpg"]  # collapsed OLE payload

    rig["keys"].left = True
    monitor._tick()  # press at (100, 100)
    state["pos"] = QPoint(100, 180)
    monitor._tick()  # movement past the threshold

    assert rig["events"] == [
        ("shown", ["a.jpg", "b.jpg", "c.jpg"], "conversion"),
    ]


def test_release_edge_snapshots_the_explorer_selection(rig, qapp):
    monitor = rig["monitor"]
    rig["state"]["selection"] = ["a.jpg", "b.jpg"]

    rig["keys"].left = True
    monitor._tick()
    rig["keys"].left = False
    _release(monitor)

    assert _wait_until(qapp, lambda: monitor._snapshot is not None)
    hwnd, files, _stamp = monitor._snapshot
    assert hwnd == 4242
    assert files == ["a.jpg", "b.jpg"]


def test_sticky_hotkey_keeps_the_wheel_after_release(rig, qapp):
    monitor = rig["monitor"]
    rig["state"]["selection"] = ["a.jpg", "b.jpg"]

    rig["keys"].combo = True
    monitor._tick()
    assert _wait_until(
        qapp,
        lambda: ("sticky", ["a.jpg", "b.jpg"], "conversion") in rig["events"],
    )
    assert monitor._sticky is True

    rig["keys"].combo = False
    monitor._tick()
    assert monitor._sticky is True
    assert not any(event[0] == "hidden" for event in rig["events"])

    monitor.sticky_release()
    assert monitor._sticky is False


def test_sticky_hotkey_pressed_again_closes_the_wheel(rig, qapp):
    monitor = rig["monitor"]
    rig["state"]["selection"] = ["a.jpg"]

    rig["keys"].combo = True
    monitor._tick()
    assert _wait_until(qapp, lambda: ("sticky", ["a.jpg"], "conversion") in rig["events"])
    assert monitor._sticky is True

    rig["keys"].combo = False
    monitor._tick()
    rig["keys"].combo = True
    monitor._tick()

    assert monitor._sticky is False
    assert ("hidden",) in rig["events"]
