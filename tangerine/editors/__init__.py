"""Interactive tool editors for the Windows port of Tangerine.

Each editor collects its options, then hands the work to a Job so the heavy
lifting happens on a worker thread with the familiar progress window.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from .. import jobs, progress, settings, tools
from ..engines import EngineError
from .audio import (
    BleepDialog,
    ChannelsDialog,
    TrimAudioDialog,
    VisualizerDialog,
    audio_peaks,
)
from .base import ToolDialog, pil_to_pixmap, pil_to_qimage, run_batch
from .images import (
    AnnotateDialog,
    BackgroundDialog,
    CollageDialog,
    CompressDialog,
    CropImageDialog,
    EditPhotoDialog,
    MetadataDialog,
    RedactPhotoDialog,
)
from .ui.canvas import AnnotateCanvas, CropCanvas, ImageCanvas, RedactCanvas, _draw_op
from .ui.video import BoxDrawDialog, VideoPane
from .ui.waveform import BleepWaveform, PlayerMixin, TrimWaveform, WaveformView
from .video import (
    CropVideoDialog,
    JoinDialog,
    RedactVideoDialog,
    SnapshotsDialog,
    SpeedDialog,
    SplitVideoDialog,
    TrimVideoDialog,
    _frame_pixmap,
    _grab_frame,
)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def open_editor(paths, key: str, parent: QWidget | None = None, label: str | None = None) -> None:
    sources = [Path(p) for p in paths]
    if not sources:
        return
    if key in ("img.compress", "vid.compress", "aud.compress"):
        family = {"img": "image", "vid": "video", "aud": "audio"}[key.split(".")[0]]
        return run_compress(paths, family, parent, label)
    builders = {
        "img.metadata": lambda: MetadataDialog(sources[0], parent),
        "img.crop": lambda: CropImageDialog(sources[0], parent),
        "img.redact": lambda: RedactPhotoDialog(sources[0], parent),
        "img.annotate": lambda: AnnotateDialog(sources[0], parent),
        "img.background": lambda: BackgroundDialog(sources[0], parent),
        "img.edit": lambda: EditPhotoDialog(sources[0], parent),
        "img.collage": lambda: CollageDialog(sources, parent),
        "aud.metadata": lambda: MetadataDialog(sources[0], parent),
        "aud.trim": lambda: TrimAudioDialog(sources[0], parent),
        "aud.bleep": lambda: BleepDialog(sources[0], parent),
        "aud.channels": lambda: ChannelsDialog(sources[0], parent),
        "aud.visualizer": lambda: VisualizerDialog(sources[0], parent),
        "vid.metadata": lambda: MetadataDialog(sources[0], parent),
        "vid.trim": lambda: TrimVideoDialog(sources[0], parent),
        "vid.crop": lambda: CropVideoDialog(sources[0], parent),
        "vid.speed": lambda: SpeedDialog(sources[0], parent),
        "vid.snapshots": lambda: SnapshotsDialog(sources[0], parent),
        "vid.split": lambda: SplitVideoDialog(sources[0], parent),
        "vid.redact": lambda: RedactVideoDialog(sources[0], parent),
        "vid.join": lambda: JoinDialog(sources, parent),
        "gif.metadata": lambda: MetadataDialog(sources[0], parent),
        "pdf.metadata": lambda: MetadataDialog(sources[0], parent),
    }
    builder = builders.get(key)
    if builder is None:
        QMessageBox.information(
            parent, label or "Tangerine",
            f"The {label or key} editor is not available yet.")
        return
    try:
        dialog = builder()
    except EngineError as error:
        QMessageBox.warning(parent, label or "Tangerine", str(error))
        return
    dialog.exec()


def run_compress(paths, family: str, parent: QWidget | None = None, label: str | None = None) -> None:
    CompressDialog(paths, family, parent).exec()
