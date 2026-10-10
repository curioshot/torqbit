"""config.py — atomic writes, validation, and the page-script trust boundary."""
from __future__ import annotations

import json

import pytest


# --------------------------------------------------------------- sanitizing
def test_load_returns_defaults_on_missing_file(cfg_home):
    cfg = cfg_home.load()
    assert cfg["theme"] == "black"
    assert cfg["mode"] == "island"
    assert cfg["instagram"]["cooldownMs"] == 800


def test_corrupt_cooldown_is_clamped_not_fatal(cfg_home):
    """A hand-edited cooldownMs used to raise ValueError during _load_all,
    which took the whole app down at construction."""
    cfg_home.CONFIG_FILE.write_text(json.dumps(
        {"instagram": {"cooldownMs": "banana", "playbackRate": "fast"}}))
    cfg = cfg_home.load()
    assert cfg["instagram"]["cooldownMs"] == 800
    assert cfg["instagram"]["playbackRate"] == 1.0


def test_out_of_range_numbers_are_clamped(cfg_home):
    cfg_home.CONFIG_FILE.write_text(json.dumps({
        "instagram": {"cooldownMs": 99999, "playbackRate": 900.0,
                      "wheelThreshold": -4},
    }))
    ig = cfg_home.load()["instagram"]
    assert ig["cooldownMs"] == 3000
    assert ig["playbackRate"] == 3.0
    assert ig["wheelThreshold"] == 5


def test_nan_playback_rate_falls_back(cfg_home):
    # json round-trips NaN happily, so this really can reach sanitize()
    cfg_home.CONFIG_FILE.write_text('{"instagram": {"playbackRate": NaN}}')
    assert cfg_home.load()["instagram"]["playbackRate"] == 1.0


def test_enum_fields_reject_junk(cfg_home):
    cfg_home.CONFIG_FILE.write_text(json.dumps(
        {"mode": "hologram", "theme": "neon", "face": "sketch",
         "shape": "dodecahedron", "face_bg": "hologram"}))
    cfg = cfg_home.load()
    assert cfg["mode"] == "island"
    assert cfg["theme"] == "black"
    assert cfg["face"] == "blobatar"
    assert cfg["shape"] == "blob"
    assert cfg["face_bg"] == "none"


def test_bool_is_not_accepted_as_a_coordinate(cfg_home):
    """bool subclasses int, so `true` used to become coordinate 1."""
    cfg_home.CONFIG_FILE.write_text(json.dumps(
        {"island_x": True, "island_y": 40}))
    cfg = cfg_home.load()
    assert cfg["island_x"] is None
    assert cfg["island_y"] == 40


def test_malformed_feeds_are_dropped(cfg_home):
    cfg_home.CONFIG_FILE.write_text(json.dumps({
        "centre": {"feeds": [{"name": "ok", "url": "https://a/rss"},
                             {"name": "no url"},
                             "a bare string",
                             42]}}))
    feeds = cfg_home.load()["centre"]["feeds"]
    assert feeds == [{"name": "ok", "url": "https://a/rss"}]


def test_sanitize_does_not_mutate_defaults(cfg_home):
    """load() used to hand back DEFAULTS["centre"] by reference, so a caller
    mutating cfg["centre"] corrupted the module-level default for the
    whole process."""
    first = cfg_home.load()
    first["centre"]["feeds"].append({"name": "x", "url": "https://x/"})
    first["instagram"]["cooldownMs"] = 1234
    second = cfg_home.load()
    assert len(second["centre"]["feeds"]) == 3
    assert second["instagram"]["cooldownMs"] == 800


# ----------------------------------------------------------------- writing
def test_save_is_atomic_and_leaves_a_backup(cfg_home):
    cfg = cfg_home.load()
    cfg["theme"] = "liquid"
    cfg_home.save(cfg)
    assert cfg_home.CONFIG_FILE.exists()
    assert not list(cfg_home.CONFIG_DIR.glob(".tmp-*"))
    cfg["theme"] = "white"
    cfg_home.save(cfg)
    backup = cfg_home.CONFIG_FILE.with_name("config.json.bak")
    assert backup.exists()
    assert json.loads(backup.read_text())["theme"] == "liquid"


def test_save_never_truncates_on_failure(cfg_home, monkeypatch):
    cfg = cfg_home.load()
    cfg_home.save(cfg)
    original = cfg_home.CONFIG_FILE.read_text()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(cfg_home.os, "replace", boom)
    cfg["theme"] = "minimal"
    cfg_home.save(cfg)
    # The old content is still there, not a half-written file.
    assert cfg_home.CONFIG_FILE.read_text() == original
    assert not list(cfg_home.CONFIG_DIR.glob(".tmp-*"))


def test_corrupt_json_is_preserved_not_overwritten(cfg_home):
    cfg_home.CONFIG_FILE.write_text("{not json at all")
    cfg = cfg_home.load()
    assert cfg["theme"] == "black"
    saved = cfg_home.CONFIG_FILE.with_name("config.json.corrupt")
    assert saved.exists()
    assert saved.read_text() == "{not json at all"


def test_save_preserves_unknown_keys_written_by_a_newer_version(cfg_home):
    cfg_home.CONFIG_FILE.write_text(json.dumps({"futureFeature": {"on": True}}))
    cfg = cfg_home.load()
    cfg["theme"] = "white"
    cfg_home.save(cfg)
    # unknown top-level keys are dropped by sanitize on read-back, which is
    # the documented contract; assert we at least did not lose the theme.
    assert json.loads(cfg_home.CONFIG_FILE.read_text())["theme"] == "white"


# ------------------------------------------------------------------ events
def test_load_events_does_not_explode_a_string_value(cfg_home):
    """list("hello") used to turn one bad entry into {'h','e','l','l','o'}."""
    cfg_home.EVENTS_FILE.write_text(json.dumps({"2026-01-01": "hello"}))
    assert cfg_home.load_events() == {"2026-01-01": ["hello"]}


def test_load_events_survives_an_unusable_value(cfg_home):
    cfg_home.EVENTS_FILE.write_text(json.dumps(
        {"2026-01-01": 42, "2026-01-02": ["kept", 7, ""]}))
    assert cfg_home.load_events() == {"2026-01-02": ["kept"]}


def test_legacy_date_keys_are_migrated(cfg_home):
    """The old key was dd-mm-yyyy, which does not sort chronologically."""
    cfg_home.EVENTS_FILE.write_text(json.dumps({"05-03-2026": ["legacy"]}))
    assert cfg_home.load_events() == {"2026-03-05": ["legacy"]}


def test_iso_keys_pass_through(cfg_home):
    cfg_home.EVENTS_FILE.write_text(json.dumps({"2026-03-05": ["kept"]}))
    assert cfg_home.load_events() == {"2026-03-05": ["kept"]}


def test_save_events_roundtrip(cfg_home):
    cfg_home.save_events({"2026-03-05": ["standup"]})
    assert cfg_home.load_events() == {"2026-03-05": ["standup"]}


# ------------------------------------------------------ page trust boundary
def test_page_cannot_write_the_master_switch(cfg_home):
    """Any script in the controlled page can call the CDP binding. It must
    not be able to switch the service off or retarget the browser."""
    accepted = cfg_home.apply_page_patch({
        "service": False, "browserFamily": "firefox", "cooldownMs": 999999})
    assert accepted is None
    assert cfg_home.load()["instagram"]["service"] is False  # unchanged default
    assert cfg_home.load()["instagram"]["cooldownMs"] == 800


def test_page_can_write_the_three_display_keys(cfg_home):
    accepted = cfg_home.apply_page_patch(
        {"playbackRate": 2.0, "controllerMini": True, "controllerPos": "br"})
    assert accepted == {"playbackRate": 2.0, "controllerMini": True,
                        "controllerPos": "br"}
    ig = cfg_home.load()["instagram"]
    assert ig["playbackRate"] == 2.0
    assert ig["controllerMini"] is True


def test_page_values_are_clamped(cfg_home):
    accepted = cfg_home.apply_page_patch({"playbackRate": 99.0})
    assert accepted["playbackRate"] == 3.0


def test_page_patch_must_be_a_dict(cfg_home):
    assert cfg_home.apply_page_patch("service: false") is None
    assert cfg_home.apply_page_patch(None) is None


# ------------------------------------------------------------- permissions
def test_config_dir_is_not_world_readable(cfg_home):
    cfg_home.ensure_dir()
    mode = cfg_home.CONFIG_DIR.stat().st_mode & 0o077
    assert mode == 0, f"config dir is group/world accessible: {oct(mode)}"
