"""reels.py — the key-binding path and the config-key parity contract.

The parity test is the important one: the Prev/Next capture UI wrote
`next_keysym` to config while the bridge asked the page for `nextKey`, so
every captured key was silently dropped and the page kept its own
hardcoded defaults. Nothing in the codebase noticed for months.
"""
from __future__ import annotations

import pytest

from island import config as cfgmod
from island import reels


# ------------------------------------------------------------ keysym -> code
@pytest.mark.parametrize("keysym,label,expected", [
    (83, "S", "KeyS"),
    (87, "W", "KeyW"),
    (ord("A"), "A", "KeyA"),
    (ord("1"), "1", "Digit1"),
    (0xFF51, "", "ArrowLeft"),
    (0xFF52, "", "ArrowUp"),
    (0xFF53, "", "ArrowRight"),
    (0xFF54, "", "ArrowDown"),
    (0xFFBE, "", "F1"),
    (0xFFC9, "", "F12"),
    (0xFF1B, "", "Escape"),
    (ord(" "), " ", "Space"),
])
def test_keysym_maps_to_dom_code(keysym, label, expected):
    assert reels.keysym_to_code(keysym, label) == expected


def test_unmappable_keysym_still_yields_something_usable():
    """An empty result would silently disable the page shortcut."""
    assert reels.keysym_to_code("not a number", "") != ""


# ------------------------------------------------------- config key parity
def test_page_config_contains_every_key_the_page_expects():
    """PAGE_SETTINGS is the contract with assets/reels/reels.js."""
    cfg = dict(cfgmod.DEFAULTS["instagram"])
    bridge = reels.ReelsBridge.__new__(reels.ReelsBridge)
    bridge._config = cfg
    out = bridge._page_config()
    missing = [k for k in reels.PAGE_SETTINGS if k not in out]
    assert not missing, f"page would fall back to hardcoded defaults: {missing}"


def test_page_config_maps_the_captured_keys():
    bridge = reels.ReelsBridge.__new__(reels.ReelsBridge)
    bridge._config = {**cfgmod.DEFAULTS["instagram"],
                      "next_keysym": ord("D"), "next_label": "D",
                      "prev_keysym": ord("A"), "prev_label": "A"}
    out = bridge._page_config()
    assert out["nextKey"] == "KeyD"
    assert out["prevKey"] == "KeyA"
    assert out["nextLabel"] == "D"
    assert out["prevLabel"] == "A"


def test_page_config_passes_through_the_working_settings():
    bridge = reels.ReelsBridge.__new__(reels.ReelsBridge)
    bridge._config = {**cfgmod.DEFAULTS["instagram"],
                      "cooldownMs": 400, "invertWheel": True}
    out = bridge._page_config()
    assert out["cooldownMs"] == 400
    assert out["invertWheel"] is True


# --------------------------------------------------------------- reconnect
def test_reconnect_constants_are_sane():
    assert reels.RECONNECT_MIN_MS > 0
    assert reels.RECONNECT_MAX_MS > reels.RECONNECT_MIN_MS


def test_bridge_is_not_live_without_a_transport():
    bridge = reels.ReelsBridge.__new__(reels.ReelsBridge)
    bridge.transport = None
    assert bridge.is_live() is False
