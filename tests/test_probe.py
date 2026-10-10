"""probe.py — the off-thread worker, and the new capability probes."""
from __future__ import annotations

import threading
import time

import pytest


def test_work_keeps_the_gui_thread_responsive(qapp):
    """The whole reason this module exists: a blocking probe must not stall
    the Qt event loop."""
    from island import probe
    done = {}

    def worker():
        done["v"] = probe.run(lambda: (time.sleep(0.4), "done")[1], timeout=3.0)

    th = threading.Thread(target=worker)
    th.start()
    frames = 0
    while th.is_alive():
        qapp.processEvents()
        frames += 1
        time.sleep(0.005)
    th.join()
    assert done["v"] == "done"
    assert frames > 10, f"event loop only ticked {frames} times — it blocked"


def test_propagates_results_and_defaults(qapp):
    from island import probe
    assert probe.run(lambda: 42) == 42
    # A raising callable must never escape into a paint path.
    assert probe.run(lambda: 1 / 0, default="fallback") == "fallback"


def test_timeout_returns_the_default_without_raising(qapp):
    from island import probe
    assert probe.run(lambda: time.sleep(5), timeout=0.15,
                     default="timed-out") == "timed-out"


def test_shutdown_is_idempotent_and_safe(qapp):
    """Uses a private Prober: shutting down the process-wide one mid-suite
    would leak state into later tests."""
    from island import probe
    p = probe.Prober()
    assert p.run(lambda: 1) == 1
    p.shutdown()
    p.shutdown()
    # After shutdown the prober must degrade rather than hang or raise.
    assert p.run(lambda: 1, default=None, timeout=0.5) is None


# ------------------------------------------------------------ new probes
def test_new_probes_report_availability_without_raising(monkeypatch):
    from island import sysctl
    for cls in (sysctl.Screenshot, sysctl.BlankScreen, sysctl.NightLight,
                sysctl.Playback):
        obj = cls()
        assert isinstance(obj.available, bool)
        assert isinstance(obj.reason, str)


class _StubCap:
    def __init__(self, available=True, kind="stub", reason=""):
        self.available, self.kind, self.reason = available, kind, reason

    def label(self):
        return "stub label"


class _StubBackend:
    """Just the attribute surface Backend.caps() reads.

    A real Backend probes the live system (nmcli, pactl, xrandr), which
    would make these tests slow and machine-dependent.
    """
    def __init__(self):
        self.brightness = _StubCap()
        self.audio = _StubCap()
        self.network = _StubCap()
        self.network.has_wifi = True
        self.network.wifi_hardware = True
        self.bluetooth = _StubCap()
        self.session = _StubCap()
        # Session exposes capability flags by name, not as .available
        self.session.can_lock, self.session.lock_reason = True, ""
        self.session.can_dnd, self.session.dnd_reason = True, ""
        self.screenshot = _StubCap()
        self.blank_screen = _StubCap()
        self.night_light = _StubCap()
        self.playback = _StubCap()


def test_caps_includes_every_new_key():
    from island import sysctl
    caps = sysctl.Backend.caps(_StubBackend())
    for key in ("screenshot", "blank", "nightlight", "playback"):
        assert key in caps, f"{key} missing from the capability report"
        assert "available" in caps[key] and "reason" in caps[key]


def test_caps_maps_the_probe_attribute_names():
    """The report renames two of the probe attributes (blank_screen -> blank),
    so a rename could silently drop a key."""
    from island import sysctl
    caps = sysctl.Backend.caps(_StubBackend())
    assert caps["blank"]["available"] is True
    assert caps["nightlight"]["available"] is True


# ----------------------------------------------------------------- rail
def test_rail_grid_holds_thirteen_toggles(qapp):
    from island.center import Rail, TOGGLES, RAIL_COLUMNS, _rows_for
    rail = Rail()
    assert len(TOGGLES) == 13
    assert len(rail.toggles) == 13
    assert RAIL_COLUMNS == 4
    assert _rows_for(13) == 4


def test_rail_dots_do_not_wrap(qapp):
    """A dot wider than its column silently pushes to the next row, which is
    how the old 3-per-row idea was rejected."""
    from island.center import RAIL_COLUMNS, DOT_W, DOT_GAP, RAIL_W
    needed = RAIL_COLUMNS * DOT_W + (RAIL_COLUMNS - 1) * DOT_GAP
    assert RAIL_W >= needed, f"rail {RAIL_W}px cannot fit a row of {needed}px"


def test_every_toggle_has_a_backend_capability_key():
    """A typo in a toggle's cap_key would mean that control is never gated
    and silently does nothing when it cannot act."""
    from island.center import TOGGLES
    from island import sysctl
    caps = sysctl.Backend.caps(_StubBackend())
    for _icon, _label, _full, cap_key, _kind in TOGGLES:
        if cap_key is None:
            continue
        assert cap_key in caps, (
            f"toggle capability key {cap_key!r} is not in the capability "
            f"report — it would never gate correctly")


def test_every_toggle_kind_has_an_action():
    """Each kind must be handled by ControlCenter._toggle, otherwise
    clicking it flashes an error forever."""
    import inspect
    from island.center import ControlCenter, TOGGLES
    src = inspect.getsource(ControlCenter._toggle)
    for _i, _l, _f, _c, kind in TOGGLES:
        assert f'kind == "{kind}"' in src, (
            f"toggle {kind!r} has no branch in _toggle()")
