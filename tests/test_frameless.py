"""Opaque-theme guarantees: every theme paints solid panels, solid buttons,
solid tabs and solid inputs. No transparency anywhere in the UI.

These tests exist so a future change cannot quietly bring back a
translucent shell, a transparent button, or a borderless control.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BOT_ISLAND_NO_WEBENGINE", "1")

# "system" is left out: resolving it needs a live QApplication palette,
# which these stylesheet-level tests do not construct.
ALL_THEMES = ["liquid", "clean_white", "white", "modern_dark", "black",
              "minimal"]


class _Stub:
    """Captures whatever apply_theme() pushes at it.

    Every attribute is itself a stub, so however deep apply_theme() reaches
    into the window, the sheets all land in one recorder.
    """

    def __init__(self, sheets: list[str] | None = None):
        object.__setattr__(self, "_sheets",
                           sheets if sheets is not None else [])

    def setStyleSheet(self, sheet):        # noqa: N802 - Qt naming
        self._sheets.append(sheet)

    def set_frameless(self, on=True):
        pass

    def set_glass(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _Stub(self._sheets)


def _sheets_for(theme_key: str) -> list[str]:
    from island import themes
    window = _Stub()
    themes.apply_theme(window, theme_key)
    return window._sheets


def _sheet_for(theme_key: str) -> str:
    """The real stylesheet apply_theme() emits, captured from a stub window."""
    for sheet in _sheets_for(theme_key):
        if "QTabWidget::pane" in sheet:
            return sheet
    raise AssertionError(f"no tab sheet emitted for theme {theme_key!r}")


def _rule_for(sheet: str, selector: str) -> str:
    """The declaration block for one selector, e.g. 'QPushButton'."""
    marker = selector + " {"
    i = sheet.find(marker)
    if i < 0:
        raise AssertionError(f"selector {selector!r} missing from the sheet")
    j = sheet.index("}", i)
    return sheet[i:j]


# ------------------------------------------------------------- painting
def test_opaque_panel_always_paints(qapp, monkeypatch):
    """Panels must paint even when asked to go frameless (no-op now)."""
    from island import glass

    calls = []

    class Spy:
        Antialiasing = True

        def __init__(self, *a, **k):
            calls.append(True)

        def setRenderHint(self, *a, **k):
            pass

        def fillPath(self, *a, **k):
            pass

        def setPen(self, *a, **k):
            pass

        def drawPath(self, *a, **k):
            pass

        def end(self):
            pass

    monkeypatch.setattr(glass, "QPainter", Spy)
    p = glass.GlassPanel()
    p.resize(200, 120)
    p.paintEvent(None)
    assert calls, "opaque panel did not paint"
    p.set_frameless(True)   # must be a no-op: still opaque
    assert p.is_frameless() is False
    calls.clear()
    p.paintEvent(None)
    assert calls, "panel stopped painting after set_frameless(True)"


def test_frameless_api_is_opaque_noop(qapp):
    from island.glass import GlassPanel
    p = GlassPanel(frameless=False)
    assert p.is_frameless() is False
    p.set_frameless(True)
    assert p.is_frameless() is False


def test_default_panels_are_opaque(qapp):
    from island.glass import GlassPanel
    assert GlassPanel().is_frameless() is False


def test_white_theme_uses_pure_white():
    """The white theme must be pure-white surfaces, not warm gray."""
    from island import themes
    t = themes.resolve("white")
    for ck in ("capsule_bg", "card_bg", "card_bg2", "pane", "btn",
               "tab", "chrome"):
        assert t[ck].lower() == "#ffffff", (
            f"white theme {ck} is {t[ck]}, not pure white")


def test_glass_values_are_fully_opaque():
    from island import themes
    for key in ALL_THEMES:
        t = themes.resolve(key)
        for channel in ("top", "bottom", "border"):
            v = t["glass"][channel]
            assert v[3] == 255, f"theme {key}: glass {channel} is translucent: {v}"
        for ck in ("capsule_bg", "card_bg", "card_bg2", "pane", "btn",
                   "tab", "tab_sel", "chrome"):
            val = t.get(ck, "")
            assert "rgba" not in str(val).lower(), (
                f"theme {key}: {ck} still uses rgba: {val}")
            assert "transparent" not in str(val).lower(), (
                f"theme {key}: {ck} is transparent: {val}")


# ------------------------------------------------------------ stylesheet
@pytest.mark.parametrize("theme_key", ALL_THEMES)
def test_tab_sheet_has_opaque_container_fills(theme_key):
    """Content containers must have solid fills — never transparent."""
    sheet = _sheet_for(theme_key)
    for selector in ("QTabWidget::pane", "QListWidget", "QTextEdit",
                     "QScrollArea", "QSpinBox", "QComboBox", "QProgressBar",
                     "QLineEdit"):
        rule = _rule_for(sheet, selector)
        assert "background: transparent" not in rule, (
            f"theme {theme_key}: {selector} is transparent again -> {rule}")


@pytest.mark.parametrize("theme_key", ALL_THEMES)
def test_buttons_have_visible_borders_and_fills(theme_key):
    """Opaque buttons: solid fill plus a real 1px border."""
    sheet = _sheet_for(theme_key)
    for selector in ("QPushButton", "QToolButton"):
        rule = _rule_for(sheet, selector)
        assert "background: transparent" not in rule, (
            f"theme {theme_key}: {selector} is transparent again -> {rule}")
        assert "border: 1px solid" in rule, (
            f"theme {theme_key}: {selector} lost its border -> {rule}")


@pytest.mark.parametrize("theme_key", ALL_THEMES)
def test_tabs_have_opaque_chrome(theme_key):
    """Tabs must be solid fills on every theme — no transparent chrome."""
    sheet = _sheet_for(theme_key)
    assert "QTabBar::tab { background: transparent;" not in sheet
    for selector in ("QPushButton", "QToolButton", "QTabBar::tab"):
        rule = _rule_for(sheet, selector)
        assert "transparent" not in rule.split("background:")[-1].split(";")[0], (
            f"theme {theme_key}: {selector} is transparent -> {rule}")


@pytest.mark.parametrize("theme_key", ALL_THEMES)
def test_no_transparent_background_anywhere_in_main_sheet(theme_key):
    sheet = _sheet_for(theme_key)
    assert "background: transparent" not in sheet, (
        f"theme {theme_key}: main sheet still contains transparency")


@pytest.mark.parametrize("theme_key", ALL_THEMES)
def test_spinbox_steppers_are_styled(theme_key):
    """Unstyled ::up-button/::down-button draw the native arrows in a colour
    that comes from the Qt style, not from the theme."""
    sheet = _sheet_for(theme_key)
    assert "QSpinBox::up-button" in sheet
    assert "QSpinBox::down-button" in sheet


@pytest.mark.parametrize("theme_key", ALL_THEMES)
def test_checkbox_has_a_visible_checked_state(theme_key):
    """A filled square with no tick is indistinguishable from hover."""
    sheet = _sheet_for(theme_key)
    assert "QCheckBox::indicator:checked" in sheet


# ------------------------------------------------------------- window
def test_every_container_in_the_window_is_opaque(qapp, cfg_home,
                                                monkeypatch):
    from island import config as cfgmod
    from island.window import IslandWindow
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", cfg_home.CONFIG_DIR)
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", cfg_home.CONFIG_FILE)
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", cfg_home.EVENTS_FILE)
    monkeypatch.setattr(cfgmod, "NOTES_FILE", cfg_home.NOTES_FILE)
    w = IslandWindow()
    try:
        for name in ("collapsed", "card", "content", "center"):
            panel = getattr(w, name)
            assert not panel.is_frameless(), f"{name} is not opaque"
    finally:
        w.close()


def test_all_themes_keep_window_panels_opaque(qapp, cfg_home, monkeypatch):
    """Switching themes must never reintroduce transparency."""
    from island import config as cfgmod
    from island.window import IslandWindow
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", cfg_home.CONFIG_DIR)
    monkeypatch.setattr(cfgmod, "CONFIG_FILE", cfg_home.CONFIG_FILE)
    monkeypatch.setattr(cfgmod, "EVENTS_FILE", cfg_home.EVENTS_FILE)
    monkeypatch.setattr(cfgmod, "NOTES_FILE", cfg_home.NOTES_FILE)
    w = IslandWindow()
    try:
        for key in ALL_THEMES:
            w.set_theme(key)
            for name in ("collapsed", "card", "content", "center"):
                assert not getattr(w, name).is_frameless(), (
                    f"{name} went transparent on theme {key}")
    finally:
        w.close()


def test_the_rail_has_its_own_opaque_card(qapp):
    """The rail must carry a solid card style (opaque, bordered)."""
    import inspect
    from island.center import Rail
    src = inspect.getsource(Rail.apply_palette)
    assert "border: 1px solid" in src
    assert "background:" in src
