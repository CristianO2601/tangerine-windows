"""Settings save/load round-trip with the data directory redirected to tmp.

``tangerine.settings`` caches its dictionary and resolves the JSON path
through ``tangerine.paths.settings_file()`` on every read/write, so the test
monkeypatches that function and resets the private cache. The real user
settings file is never touched.
"""

import json

import pytest

from tangerine import paths, settings


@pytest.fixture
def redirected_settings(tmp_path, monkeypatch):
    target = tmp_path / "settings.json"
    monkeypatch.setattr(paths, "settings_file", lambda: target)
    original_cache = settings._cache
    settings._cache = dict(settings.DEFAULTS)
    yield target
    settings._cache = original_cache


def test_round_trip(redirected_settings):
    target = redirected_settings

    settings.set("collageSpacing", 7)
    settings.set("defaultImageCompressionStrength", "strong")
    settings.set("soundsAndHapticsEnabled", False)
    settings.save()

    assert target.exists()
    payload = json.loads(target.read_text("utf-8"))
    assert payload["collageSpacing"] == 7
    assert payload["defaultImageCompressionStrength"] == "strong"
    assert payload["soundsAndHapticsEnabled"] is False

    # Simulate a fresh launch: drop the cache and read back from disk.
    settings._cache = None
    loaded = settings.load()
    assert loaded["collageSpacing"] == 7
    assert loaded["defaultImageCompressionStrength"] == "strong"
    assert loaded["soundsAndHapticsEnabled"] is False
    assert loaded["welcomeShown"] is False  # defaults survive the merge


def test_corrupt_file_falls_back_to_defaults(redirected_settings):
    target = redirected_settings
    target.write_text("{this is not json", encoding="utf-8")

    settings._cache = None
    loaded = settings.load()

    assert loaded["collageSpacing"] == settings.DEFAULTS["collageSpacing"]
    assert loaded["conversionWheelDragModifierMask"] == "shift"
    assert target.with_suffix(".json.bak").exists()


def test_set_is_noop_when_value_is_unchanged(redirected_settings):
    target = redirected_settings
    settings.save()
    first = target.stat().st_mtime_ns

    settings.set("collageSpacing", settings.DEFAULTS["collageSpacing"])
    assert target.stat().st_mtime_ns == first
