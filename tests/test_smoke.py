"""End-to-end smoke test: build every screen and drive the main transitions.

Runs headless under QT_QPA_PLATFORM=offscreen. It cannot judge whether the
UI looks right, but it does catch the class of failure where a refactor
leaves a tab unconstructable or a transition raising halfway.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BOT_ISLAND_NO_WEBENGINE", "1")


@pytest.fixture
def window(qapp, cfg_home, monkeypatch):
    """An IslandWindow whose config writes land in tmp_path."""
    from island import config as cfgmod
    from island.window import IslandWindow

    monkeypatch.setattr(cfgmod, "CONFIG_DIR", cfg_home.CONFIG_DIR)
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", cfg_home.CONFIG_FILE)
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", cfg_home.EVENTS_FILE)
    monkeypatch.setattr(cfgmod, "NOTES_FILE", cfg_home.NOTES_FILE)

    w = IslandWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    qapp.processEvents()


def pump(qapp, times=4):
    for _ in range(times):
        qapp.processEvents()


def test_window_constructs(window, qapp):
    assert window.isVisible()
    assert window.width() > 0 and window.height() > 0


def test_expand_and_collapse(window, qapp):
    window.expand()
    pump(qapp)
    assert window.expanded is True
    window.collapse()
    pump(qapp)
    assert window.expanded is False


def test_control_centre_opens_and_closes(window, qapp):
    """The card and the full panel are mutually exclusive: they share one
    stacked area beside the rail, so exactly one of them is ever visible."""
    window.expand()
    pump(qapp)
    assert not window.card.isHidden(), "expanded card should be showing"
    assert window.center.isHidden(), "full panel should be hidden"

    window.open_centre()
    pump(qapp)
    assert window.centre_open is True
    assert not window.center.isHidden(), "full panel should be showing"
    assert window.card.isHidden(), "card and panel must not both be showing"
    assert not window.rail.isHidden(), "rail belongs in both wide states"

    window.close_centre()
    pump(qapp)
    assert window.centre_open is False
    assert not window.card.isHidden(), "card must come back"
    assert window.center.isHidden()


def test_rail_hidden_in_the_collapsed_state(window, qapp):
    """There is nothing beside the rail to control when collapsed."""
    window.collapse()
    pump(qapp)
    assert window.rail.isHidden()


def test_full_panel_is_one_row(window, qapp):
    """The old layout stacked the card above the panel, which is what made
    it two separate containers."""
    window.open_centre()
    pump(qapp)
    w, h = window._centre_geometry()
    rail_w = window.rail.width()
    # Panel height is the window height now, not window minus card.
    assert h == pytest.approx(window.center.height(), abs=2)
    assert w > rail_w, "the panel should sit beside the rail"


def test_every_tab_constructs_and_paints(window, qapp):
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        pump(qapp)


def test_toggle_of_each_theme(window, qapp):
    from island import themes
    for key, _label, _desc in themes.available():
        window.set_theme(key)
        pump(qapp)
        assert window.cfg["theme"] == key


def test_face_engines_all_load(window, qapp):
    for engine in ("blobatar", "aora", "simple"):
        window.set_face(engine)
        pump(qapp)
        assert window.cfg["face"] == engine


def test_emotions_and_shapes(window, qapp):
    for eid in ("01", "02", "10", "35", "41"):
        window.set_emotion(eid)
        pump(qapp)
    for shape in ("blob", "wedge", "gem"):
        window.set_shape(shape)
        pump(qapp)


def test_mode_switches(window, qapp):
    window._set_mode("corner")
    pump(qapp)
    assert window.cfg["mode"] == "corner"
    window._set_mode("island")
    pump(qapp)
    assert window.cfg["mode"] == "island"


def test_geometry_clamp_never_inverts(window):
    """`min(max(ix, g.x()), g.x() + g.width() - w)` pushed the window off
    the left edge whenever the window was wider than the screen."""
    lo = 0
    assert window._clamp(-999, lo, 500, 300) == 0
    assert window._clamp(9999, lo, 500, 300) == 0     # size > span -> lo
    assert window._clamp(100, lo, 100, 1000) == 100


def test_service_tab_pages_open(window, qapp):
    from island.service_tab import ServiceTab
    st = window.svc_tab
    st.open("instagram")
    pump(qapp)
    st.open("spotify")
    pump(qapp)


def test_notice_shows_and_hides(qapp, cfg_home, monkeypatch):
    from island import config as cfgmod
    from island.service_tab import ServiceTab
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", cfg_home.CONFIG_FILE)
    st = ServiceTab()
    st.show()
    pump(qapp)
    notice = st.insta.notice
    assert notice.isHidden()
    notice.show_message("something failed", "error")
    pump(qapp)
    assert not notice.isHidden()
    assert notice._text.text() == "something failed"


def test_config_roundtrips_through_the_window(window, qapp):
    window.set_theme("liquid")
    pump(qapp)
    from island import config as cfgmod
    assert cfgmod.load()["theme"] == "liquid"


def test_every_icon_renders_at_every_size_and_colour(qapp):
    """rgba() colours used to make QSvgRenderer draw nothing at all, so the
    whole `system` theme's icons were invisible. Iterate the real set so a
    newly added icon is covered automatically."""
    from island import icons
    assert icons._SVGS, "no icons defined"
    for name in icons._SVGS:
        for size in (14, 22, 44):
            for colour in ("#f2efe8", "rgba(216, 224, 238, 200)", "white",
                           "transparent"):
                pm = icons.pixmap(name, size, colour)
                assert pm is not None, (name, size, colour)
                assert not pm.isNull(), (name, size, colour)


def test_icon_rasterisation_is_cached(qapp):
    """paintEvent called icons.pixmap() at 25Hz; uncached that meant a full
    SVG parse and texture upload per frame per widget."""
    import time
    from island import icons
    icons.pixmap("dice", 22, "#ffffff")          # warm
    t = time.perf_counter()
    for _ in range(500):
        icons.pixmap("dice", 22, "#ffffff")
    cached = time.perf_counter() - t
    assert cached < 0.5, f"500 cached draws took {cached:.2f}s — cache broken"


def test_slider_is_keyboard_operable(qapp):
    from island.widgets import VerticalSlider
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    s = VerticalSlider("sun", "Brightness")
    s.set_value(0.5)
    s._nudge(0.05)
    assert s.value() > 0.5
    assert s.focusPolicy() == Qt.StrongFocus
    assert s.accessibleName()
