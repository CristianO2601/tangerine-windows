"""Audio visualizer end-to-end: the generated MP4 must carry the audio track,
and video-only sources fail with a friendly error before FFmpeg runs.

Requires FFmpeg and ffprobe; the module skips when either is missing.
"""

import json
import subprocess
from pathlib import Path

import pytest

from tangerine import engines, media, tools

pytestmark = pytest.mark.skipif(
    not media.ffmpeg_path() or not media.ffprobe_path(),
    reason="FFmpeg and ffprobe are required for the visualizer tests",
)


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(
        [media.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


def _streams(path: Path) -> list[dict]:
    output = subprocess.run(
        [media.ffprobe_path(), "-v", "error", "-show_streams", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return json.loads(output)["streams"]


def _kinds(path: Path) -> set[str]:
    return {stream["codec_type"] for stream in _streams(path)}


def _audio_codec(path: Path) -> str:
    return next(
        stream["codec_name"] for stream in _streams(path) if stream["codec_type"] == "audio"
    )


@pytest.fixture(scope="module")
def tone(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("viz_tone") / "tone.wav"
    _ffmpeg(
        ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "pcm_s16le", str(path)]
    )
    return path


@pytest.fixture(scope="module")
def video_with_audio(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("viz_av") / "clip_av.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ]
    )
    return path


@pytest.fixture(scope="module")
def silent_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("viz_silent") / "clip_silent.mp4"
    _ffmpeg(
        [
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=10:d=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ]
    )
    return path


def test_audio_source_output_has_video_and_audio(tone):
    output = tools.make_visualizer(tone, "landscape", None, engines.Ctx(), set())
    assert output.exists()
    assert output.stat().st_size > 0
    assert _kinds(output) == {"video", "audio"}
    assert _audio_codec(output) == "aac"


def test_video_with_audio_keeps_audio(video_with_audio):
    output = tools.make_visualizer(video_with_audio, "landscape", None, engines.Ctx(), set())
    assert output.exists()
    assert _kinds(output) == {"video", "audio"}
    assert _audio_codec(output) == "aac"


def test_video_without_audio_raises_friendly_error(silent_video):
    with pytest.raises(engines.EngineError) as raised:
        tools.make_visualizer(silent_video, "landscape", None, engines.Ctx(), set())
    assert str(raised.value) == "This video has no audio track to visualize."
    assert not list(silent_video.parent.glob("*Visualizer*.mp4"))
