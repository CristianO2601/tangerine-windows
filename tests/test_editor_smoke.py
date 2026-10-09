"""Executable headless smoke for the real image editor workflows."""
import json
from pathlib import Path
import tempfile

from tangerine.editor_smoke import editors_smoke


def test_editors_smoke_writes_success_receipt_without_visible_ui(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    result = editors_smoke()

    receipt = Path(tempfile.gettempdir()) / "Tangerine-editors-smoke.json"
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert result == 0, data.get("traceback")
    assert data["version"]
    assert data["ok"] is True
    assert {
        "annotate_canvas_render_and_output",
        "crop_aspect_handles_and_output",
        "numeric_buttons_and_annotation_width",
        "background_batch_defaults_replay_and_autoclose",
    } == {item["name"] for item in data["checks"] if item["ok"]}
