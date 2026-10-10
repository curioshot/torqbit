"""The UI is deliberately frameless: containers and controls sit directly on
the screen with no background and no border.

These tests exist so a future change cannot quietly put a box back.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("BOT_ISLAND_NO_WEBENGINE", "1")


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
def test_frameless_panel_never_paints(qapp, monkeypatch):
    """Asserted on behaviour, not on pixels: `render()` fills the background
    itself, so a pixel test would pass or fail for the wrong reason."""
    from island import glass

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("a frameless panel started painting")

    monkeypatch.setattr(glass, "QPainter", Boom)
    p = glass.GlassPanel()
    p.resize(200, 120)
    p.paintEvent(None)          # must be a no-op
    p.set_glass(p._top, p._bottom, p._border)
    p.paintEvent(None)          # still a no-op: frameless wins


def test_chrome_can_be_switched_back_on(qapp):
    from island.glass import GlassPanel
    p = GlassPanel(frameless=False)
    assert p.is_frameless() is False
    p.set_frameless(True)
    assert p.is_frameless() is True


def test_default_panels_are_frameless(qapp):
    from island.glass import GlassPanel
    assert GlassPanel().is_frameless() is True


# ------------------------------------------------------------ stylesheet
@pytest.mark.parametrize("theme_key", ["black", "white", "liquid", "minimal"])
def test_tab_sheet_has_no_container_fills(theme_key):
    """`background:` on a container rule is what puts a box back on screen."""
    sheet = _sheet_for(theme_key)
    for selector in ("QTabWidget::pane", "QListWidget", "QTextEdit",
                     "QScrollArea", "QPushButton", "QToolButton", "QLabel",
                     "QSpinBox", "QComboBox", "QProgressBar"):
        rule = _rule_for(sheet, selector)
        assert "background: transparent" in rule, (
            f"theme {theme_key}: {selector} paints a background again -> {rule}")
        assert "border: none" in rule or selector in (
            # These keep a deliberate underline / focus affordance, which is
            # an indicator, not a container border.
            "QLineEdit"), (
            f"theme {theme_key}: {selector} has a border again -> {rule}")


@pytest.mark.parametrize("theme_key", ["black", "white", "liquid", "minimal"])
def test_buttons_have_no_border(theme_key):
    """Buttons in particular: a border on a button is the exact thing the
    sketch's 'no border (0px)' note rules out."""
    sheet = _sheet_for(theme_key)
    assert "QPushButton { background: transparent; border: none;" in sheet
    assert "QToolButton { background: transparent; border: none;" in sheet


@pytest.mark.parametrize("theme_key", ["black", "white", "liquid", "minimal"])
def test_spinbox_steppers_are_styled(theme_key):
    """Unstyled ::up-button/::down-button draw the native arrows in a colour
    that comes from the Qt style, not from the theme."""
    sheet = _sheet_for(theme_key)
    assert "QSpinBox::up-button" in sheet
    assert "QSpinBox::down-button" in sheet


@pytest.mark.parametrize("theme_key", ["black", "white", "liquid", "minimal"])
def test_checkbox_has_a_visible_checked_state(theme_key):
    """A filled square with no tick is indistinguishable from hover."""
    sheet = _sheet_for(theme_key)
    assert "QCheckBox::indicator:checked" in sheet


# ------------------------------------------------------------- window
def test_every_container_in_the_window_is_frameless(qapp, cfg_home,
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
            assert panel.is_frameless(), f"{name} is not frameless"
    finally:
        w.close()


def test_the_rail_has_no_paint_of_its_own(qapp):
    """The rail was never given a panel; it must stay that way."""
    import inspect
    from island.center import Rail
    # Not `dir()`, which would list QWidget's own inherited paintEvent.
    assert "paintEvent" not in Rail.__dict__
    assert "paintEvent" not in inspect.getsource(Rail)
