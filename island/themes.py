"""Five themes for the island: liquid glass, white, black, system, minimal.

Single entry point: apply_theme(window, name). All widget styling lives here
so the Appearance tab can switch looks live.
"""
from __future__ import annotations

THEME_ORDER = ("liquid", "white", "black", "system", "minimal")

_LABELS = {
    "liquid": "Liquid Glass",
    "white": "White",
    "black": "Black",
    "system": "System default",
    "minimal": "Minimal",
}

_DESCS = {
    "liquid": "Frosted translucency, glow border (KWin blur does the frosting).",
    "white": "Bright light theme, dark text.",
    "black": "Near-black capsule, the classic look.",
    "system": "Follows your KDE palette automatically.",
    "minimal": "Flat monochrome, small radius, no decoration.",
}

_THEMES = {
    "liquid": {
        "capsule_bg": "rgba(32, 38, 52, 150)",
        "capsule_border": "rgba(255, 255, 255, 95)",
        "card_bg": "rgba(26, 31, 44, 168)",
        "card_bg2": "rgba(40, 48, 66, 168)",
        "card_border": "rgba(255, 255, 255, 85)",
        "text": "#f4f6fb",
        "subtext": "rgba(216, 224, 238, 200)",
        "muted": "rgba(170, 180, 198, 160)",
        "accent": "#6ee7ff",
        "pane": "rgba(255, 255, 255, 16)",
        "btn": "rgba(255, 255, 255, 28)",
        "btn_border": "rgba(255, 255, 255, 65)",
        "tab": "rgba(255, 255, 255, 14)",
        "tab_sel": "rgba(255, 255, 255, 55)",
        "radius": 24,
        # Apple liquid-glass shell: brighter veil up top, edge light,
        # specular gloss + inner rim. Alpha stays low so KWin blur frosts it.
        "glass": {"top": (66, 75, 98, 172), "bottom": (16, 20, 31, 172),
                  "border": (255, 255, 255, 120), "bw": 1.5,
                  "gloss": True, "rim": True, "radius": 24},
    },
    "white": {
        "capsule_bg": "rgba(255, 255, 255, 244)",
        "capsule_border": "#d5d5dc",
        "card_bg": "#ffffff",
        "card_bg2": "#f2f2f5",
        "card_border": "#d5d5dc",
        "text": "#191920",
        "subtext": "#5c5c66",
        "muted": "#8a8a94",
        "accent": "#0a8a4d",
        "pane": "#f0f0f3",
        "btn": "#ececf0",
        "btn_border": "#d2d2d9",
        "tab": "#e4e4e9",
        "tab_sel": "#ffffff",
        "radius": 20,
        "glass": {"top": (255, 255, 255, 245), "bottom": (231, 234, 240, 245),
                  "border": (203, 206, 214, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 20},
    },
    "black": {
        "capsule_bg": "rgba(12, 12, 15, 235)",
        "capsule_border": "#2b2b31",
        "card_bg": "rgba(13, 13, 16, 246)",
        "card_bg2": "rgba(13, 13, 16, 246)",
        "card_border": "#2e2e35",
        "text": "#f2efe8",
        "subtext": "#a8a49d",
        "muted": "#6f6c68",
        "accent": "#59d98c",
        "pane": "#101013",
        "btn": "#1d1d22",
        "btn_border": "#2c2c33",
        "tab": "#17171b",
        "tab_sel": "#26262c",
        "radius": 20,
        "glass": {"top": (13, 13, 16, 246), "bottom": (13, 13, 16, 246),
                  "border": (46, 46, 53, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 20},
    },
    "minimal": {
        "capsule_bg": "#101012",
        "capsule_border": "#101012",
        "card_bg": "#101012",
        "card_bg2": "#101012",
        "card_border": "#2a2a2e",
        "text": "#e8e8e8",
        "subtext": "#909090",
        "muted": "#666666",
        "accent": "#e8e8e8",
        "pane": "#101012",
        "btn": "transparent",
        "btn_border": "#333336",
        "tab": "transparent",
        "tab_sel": "#1d1d20",
        "radius": 8,
        "glass": {"top": (16, 16, 18, 255), "bottom": (16, 16, 18, 255),
                  "border": (44, 44, 48, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 8},
    },
}


def available() -> list[tuple[str, str, str]]:
    """(key, label, description) for the Appearance tab, in order."""
    return [(k, _LABELS[k], _DESCS[k]) for k in THEME_ORDER]


def _resolve(name: str) -> dict:
    if name == "system":
        return _system_theme()
    return dict(_THEMES.get(name, _THEMES["black"]))


def _system_theme() -> dict:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QColor

    pal = QApplication.palette()

    def role(*names):
        for n in names:
            if hasattr(pal, n):
                return getattr(pal, n)
        return None

    def col(role_obj, fallback="#888888"):
        try:
            c = pal.color(role_obj)
            if c.isValid():
                return c
        except Exception:
            pass
        return QColor(fallback)

    win = col(role("window", "Window"))
    txt = col(role("windowText", "WindowText"), "#111111")
    sub = col(role("placeholderText", "PlaceholderText"), "")
    if not sub.isValid():
        sub = QColor(txt)
        sub.setAlpha(160)
    base = col(role("base", "Base"))
    mid = col(role("mid", "Mid"))
    hl = col(role("highlight", "Highlight"), "#3a7bd5")

    def css(c: QColor, alpha: int | None = None) -> str:
        if alpha is not None:
            c = QColor(c)
            c.setAlpha(alpha)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"

    darker = QColor(win)
    darker.setRed(max(0, darker.red() - 26))
    darker.setGreen(max(0, darker.green() - 26))
    darker.setBlue(max(0, darker.blue() - 26))

    return {
        "capsule_bg": css(win, 238),
        "capsule_border": css(mid),
        "card_bg": css(win, 246),
        "card_bg2": css(win, 246),
        "card_border": css(mid),
        "text": css(txt),
        "subtext": css(sub),
        "muted": css(sub),
        "accent": css(hl),
        "pane": css(base),
        "btn": css(base),
        "btn_border": css(mid),
        "tab": css(base),
        "tab_sel": css(hl, 70),
        "radius": 14,
        "glass": {"top": (win.red(), win.green(), win.blue(), 242),
                  "bottom": (darker.red(), darker.green(), darker.blue(), 242),
                  "border": (mid.red(), mid.green(), mid.blue(), 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 14},
    }


def apply_theme(window, name: str) -> str:
    """Style the whole island. Returns the effective theme key."""
    from PySide6.QtGui import QColor

    if name not in THEME_ORDER:
        name = "black"
    t = _resolve(name)
    g = t.get("glass", {})

    def qc(key, fallback=(13, 13, 16, 246)):
        v = g.get(key, fallback)
        try:
            return QColor(*v)
        except Exception:
            return QColor(*fallback)

    # Outer shells paint themselves (guaranteed rounded corners).
    top, bottom = qc("top"), qc("bottom")
    border = qc("border", (46, 46, 53, 255))
    bw = float(g.get("bw", 1.0))
    radius = int(g.get("radius", 20))
    gloss, rim = bool(g.get("gloss")), bool(g.get("rim"))
    try:
        window.collapsed.set_glass(top, bottom, border, bw, radius, gloss, rim)
        window.card.set_glass(top, bottom, border, bw, radius, gloss, rim)
        window.content.set_glass(top, bottom, border, bw, max(8, radius - 6),
                                 gloss, rim)
    except Exception:
        pass
    window.mini_time.setStyleSheet(
        f"font-size: 15px; font-weight: 600; background: transparent; color: {t['text']};"
    )
    window.mini_temp.setStyleSheet(
        f"font-size: 11px; background: transparent; color: {t['subtext']};"
    )
    window.mini_dot.setStyleSheet(
        f"background: {t['accent']}; border-radius: 5px; min-width: 10px;"
        f" min-height: 10px; max-width: 10px; max-height: 10px;"
    )

    window.big_time.setStyleSheet(
        f"font-size: 38px; font-weight: 700; background: transparent; color: {t['text']};"
    )
    window.big_date.setStyleSheet(
        f"background: transparent; color: {t['subtext']}; font-size: 12px;"
    )
    window.big_temp.setStyleSheet(
        f"background: transparent; color: {t['subtext']}; font-size: 12px;"
    )
    window.hint.setStyleSheet(
        f"background: transparent; color: {t['muted']}; font-size: 10px;"
    )

    window.tabs.setStyleSheet(
        f"QTabWidget::pane {{ border: 1px solid {t['card_border']};"
        f" border-radius: 10px; background: {t['pane']}; }}"
        f"QTabBar::tab {{ background: {t['tab']}; color: {t['subtext']};"
        f" padding: 4px 4px; font-size: 10px; border-top-left-radius: 8px;"
        f" border-top-right-radius: 8px; margin: 2px; }}"
        f"QTabBar::tab:selected {{ background: {t['tab_sel']}; color: {t['text']}; }}"
        f"QLabel {{ background: transparent; color: {t['text']}; border: none; }}"
        f"QPushButton {{ background: {t['btn']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 8px; padding: 6px 2px; color: {t['text']}; font-size: 11px; }}"
        f"QPushButton:hover {{ border-color: {t['accent']}; }}"
        f"QToolButton {{ background: {t['btn']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 20px; color: {t['text']}; font-size: 13px; font-weight: 600; }}"
        f"QToolButton:hover {{ border-color: {t['accent']}; }}"
        f"QCheckBox {{ color: {t['text']}; background: transparent; spacing: 8px; }}"
        f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;"
        f" border: 1px solid {t['btn_border']}; background: {t['pane']}; }}"
        f"QCheckBox::indicator:checked {{ background: {t['accent']}; }}"
        f"QSpinBox {{ background: {t['pane']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 8px; padding: 4px; color: {t['text']}; }}"
        f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}"
        f"QScrollBar::handle:vertical {{ background: {t['btn_border']};"
        f" border-radius: 3px; min-height: 24px; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"QLineEdit {{ background: {t['pane']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 8px; padding: 6px; color: {t['text']}; }}"
        f"QComboBox {{ background: {t['btn']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 6px; padding: 4px; color: {t['text']}; }}"
        f"QComboBox QAbstractItemView {{ background: {t['pane']}; color: {t['text']};"
        f" selection-background-color: {t['tab_sel']}; }}"
        f"QListWidget {{ background: {t['pane']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 8px; color: {t['text']}; }}"
        f"QTextEdit {{ background: {t['pane']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 8px; color: {t['text']}; }}"
        f"QProgressBar {{ background: {t['pane']}; border: 1px solid {t['btn_border']};"
        f" border-radius: 6px; color: {t['text']}; text-align: center; }}"
        f"QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}"
        f"QRadioButton {{ color: {t['text']}; background: transparent; }}"
        f"QCalendarWidget QWidget {{ background: {t['pane']}; color: {t['text']}; }}"
    )
    # clock + bot-tab labels (inherit tabs sheet, but pin subtext tones)
    try:
        window.bot_tab.clock.setStyleSheet(
            f"font-size: 40px; font-weight: 700; background: transparent; color: {t['text']};"
        )
        window.bot_tab.date.setStyleSheet(
            f"background: transparent; color: {t['subtext']}; font-size: 13px;"
        )
        window.bot_tab.utc_lbl.setStyleSheet(
            f"background: transparent; color: {t['muted']}; font-size: 11px;"
        )
    except Exception:
        pass
    # theme-tinted SVG icons (emoji-free UI)
    try:
        from . import icons as iconsmod
        ink = t["text"]
        window.bot_tab.shuffle_btn.setIcon(iconsmod.icon("dice", 18, ink))
        for eid, btn in window.bot_tab.emo_buttons.items():
            ic = window.bot_tab.EMOTION_ICONS.get(eid)
            if ic:
                btn.setIcon(iconsmod.icon(ic, 14, ink))
        pm = iconsmod.pixmap("thermo", 14, ink)
        if pm is not None:
            window.sys_tab.temp_icon.setPixmap(pm)
        try:
            window.svc_tab.set_icon_tint(ink)
        except Exception:
            pass
        # service scroll canvas: explicit pane color (translucent canvas
        # inside a scroll viewport renders unpredictably dark)
        try:
            window.svc_tab.insta._body.setStyleSheet(f"background: {t['pane']};")
        except Exception:
            pass
    except Exception:
        pass
    return name
