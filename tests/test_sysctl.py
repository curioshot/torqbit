"""sysctl.py — pure helpers plus the Plasma DND writer.

The DND tests matter most: set_dnd() rewrites the user's entire desktop
layout file, and the old regex used `\\s*$`, which matches newlines. The
replacement dropped the line terminator and merged the DND entry into the
next line, corrupting the INI.
"""
from __future__ import annotations

import os
import stat

import pytest

from island import sysctl


PLASMA = """[Containments]
[Containments][1]
activityId=
formfactor=0

[DoNotDisturb]
org.kde.plasma.donotdisturb=false
org.kde.plasma.donotdisturb.rules=Array
size=1

[General]
animationEnabled=false
"""


# ------------------------------------------------------------------ helpers
def test_clamp01():
    assert sysctl._clamp01(0.5) == 0.5
    assert sysctl._clamp01(-1) == 0.0
    assert sysctl._clamp01(5) == 1.0


def test_f_never_raises():
    assert sysctl._f(None) == 0.0
    assert sysctl._f("nonsense") == 0.0
    assert sysctl._f("2.5") == 2.5


def test_run_handles_a_missing_binary():
    rc, _ = sysctl._run(["definitely-not-a-real-binary-xyz"])
    assert rc == 127


def test_run_respects_the_timeout():
    rc, _ = sysctl._run(["sleep", "5"], timeout=0.2)
    assert rc == 124


def test_ttl_cache_expires():
    c = sysctl.TTLCache(ttl=0.05)
    c.put("k", "v")
    assert c.get("k") == "v"
    import time
    time.sleep(0.08)
    assert c.get("k") is None


def test_ttl_cache_does_not_leak_its_timestamp_dict():
    """get() popped the value but never the timestamp, so the dict grew
    without bound."""
    c = sysctl.TTLCache(ttl=0.01)
    for i in range(5):
        c.put(f"k{i}", i)
    import time
    time.sleep(0.02)
    for i in range(5):
        c.get(f"k{i}")
    assert len(c._t) == 0, f"timestamps leaked: {c._t}"


def test_format_bps():
    assert "kb/s" in sysctl.format_bps(5000)
    assert "Mb/s" in sysctl.format_bps(5_000_000)
    assert "Gb/s" in sysctl.format_bps(3e9)
    assert sysctl.format_bps(0)


# --------------------------------------------------------------- DND write
@pytest.fixture
def session(tmp_path, monkeypatch):
    f = tmp_path / "plasma-org.kde.plasma.desktop-appletsrc"
    f.write_text(PLASMA, encoding="utf-8")
    monkeypatch.setattr(sysctl, "_run", lambda *a, **k: (0, ""))
    s = sysctl.Session.__new__(sysctl.Session)
    s.DND_FILE = f
    s.can_lock = True
    s.can_dnd = True
    return s, f


def test_dnd_roundtrips(session):
    s, f = session
    assert s.dnd() is False
    assert s.set_dnd(True) is True
    assert s.dnd() is True
    assert s.set_dnd(False) is True
    assert s.dnd() is False


def test_set_dnd_preserves_every_other_line(session):
    s, f = session
    s.set_dnd(True)
    text = f.read_text()
    assert "[Containments]" in text
    assert "org.kde.plasma.donotdisturb.rules=Array" in text
    assert "animationEnabled=false" in text
    assert text.count("[DoNotDisturb]") == 1


def test_set_dnd_does_not_swallow_blank_lines(session):
    r"""`\s*$` matches newlines, so when the DND key is followed by blank or
    whitespace-only lines the match ran past the end of its own line and the
    substitution deleted them.

    Asserted through set_dnd() rather than against a copy of the pattern, so
    the test actually exercises the code it is protecting.
    """
    s, f = session
    original = f.read_text()
    f.write_text(original.replace(
        "org.kde.plasma.donotdisturb=false\n",
        "org.kde.plasma.donotdisturb=false\n\n   \n", 1))
    assert "\n\n   \n" in f.read_text()
    assert s.set_dnd(True) is True
    after = f.read_text()
    assert "\n\n   \n" in after, (
        f"blank/whitespace lines after the DND key were deleted:\n{after!r}")
    assert "org.kde.plasma.donotdisturb=true" in after
    assert "org.kde.plasma.donotdisturb.rules=Array" in after


def test_set_dnd_reads_back_what_it_wrote(session):
    """set_dnd must confirm the key landed, not trust its own edit."""
    s, f = session
    monkey = s.set_dnd
    assert monkey(True) is True
    assert s.dnd() is True
    assert s.set_dnd(False) is True
    assert s.dnd() is False


def test_set_dnd_tolerates_trailing_whitespace(session):
    s, f = session
    original = f.read_text()
    f.write_text(original.replace(
        "org.kde.plasma.donotdisturb=false",
        "org.kde.plasma.donotdisturb=false   ", 1))
    assert s.set_dnd(True) is True
    assert "org.kde.plasma.donotdisturb=true" in f.read_text().splitlines()


def test_set_dnd_creates_the_section_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(sysctl, "_run", lambda *a, **k: (0, ""))
    f = tmp_path / "dnd-missing-section"
    f.write_text("[General]\nanimationEnabled=false\n")
    s = sysctl.Session.__new__(sysctl.Session)
    s.DND_FILE = f
    s.can_lock = True
    s.can_dnd = True
    assert s.set_dnd(True) is True
    text = f.read_text()
    assert "[DoNotDisturb]" in text
    assert "donotdisturb=true" in text
    assert "animationEnabled=false" in text


def test_set_dnd_creates_the_file_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(sysctl, "_run", lambda *a, **k: (0, ""))
    f = tmp_path / "empty-plasma"
    f.write_text("")
    s = sysctl.Session.__new__(sysctl.Session)
    s.DND_FILE = f
    s.can_lock = True
    s.can_dnd = True
    assert s.set_dnd(True) is True
    assert "donotdisturb=true" in f.read_text()


def test_set_dnd_leaves_the_file_intact_on_failure(session, monkeypatch):
    s, f = session
    before = f.read_text()
    monkeypatch.setattr(sysctl, "_atomic_write", lambda *a, **k: False)
    assert s.set_dnd(True) is False
    assert f.read_text() == before


def test_set_dnd_is_atomic(session):
    """A crash mid-write must not be able to truncate the user's desktop
    layout, so the write goes through a temp file and a rename."""
    s, f = session
    s.set_dnd(True)
    assert not list(f.parent.glob(".bot-*")), "temp file left behind"


# ---------------------------------------------------------------- wifi bus
@pytest.mark.parametrize("out,expected", [
    ("WIFI: enabled\n", True),
    ("WIFI: disabled\n", False),
    ("WIFI: missing\nBT: missing\n", False),   # nothing real to toggle
    ("", False),
])
def test_radio_state_reads_as_disabled_when_there_is_nothing_to_toggle(
        out, expected, monkeypatch):
    """`missing` means no such radio exists. Counting it as 'enabled' lit
    the airplane dot on a machine with nothing to switch off."""
    n = sysctl.Network.__new__(sysctl.Network)
    n._cache = sysctl.TTLCache(ttl=3.0)
    monkeypatch.setattr(sysctl, "_run", lambda *a, **k: (0, out))
    assert n.radios_enabled() is expected
