"""Seven fully opaque themes for the island.

No transparency anywhere: every colour is a solid #rrggbb hex, every panel
paints a solid fill, buttons/tabs/inputs all have solid fills with visible
1px borders. The old liquid-glass translucency is gone.

Single entry point: apply_theme(window, name). All widget styling lives here
so the Appearance tab can switch looks live.
"""
from __future__ import annotations

THEME_ORDER = ("liquid", "clean_white", "white", "modern_dark", "black", "system", "minimal")

_LABELS = {
    "liquid": "Deep Slate",
    "clean_white": "Clean White",
    "white": "White",
    "modern_dark": "Modern Dark",
    "black": "Black",
    "system": "System default",
    "minimal": "Minimal",
}

_DESCS = {
    "liquid": "Solid slate-blue panels, cyan accents. Fully opaque.",
    "clean_white": "Pristine light theme with warm neutral surfaces and high contrast. Fully opaque.",
    "white": "Pure-white surfaces, dark text, blue accents. Fully opaque.",
    "modern_dark": "Deep obsidian slate with electric cyan highlights and OLED contrast. Fully opaque.",
    "black": "Near-black capsule, the classic look. Fully opaque.",
    "system": "Follows your KDE palette automatically. Fully opaque.",
    "minimal": "Flat monochrome, small radius, no decoration. Fully opaque.",
}

_THEMES = {
    "liquid": {
        "capsule_bg": "#232b3d",
        "capsule_border": "#3d4a63",
        "card_bg": "#1b2231",
        "card_bg2": "#273043",
        "card_border": "#3d4a63",
        "text": "#f4f6fb",
        "subtext": "#c2cad8",
        "muted": "#8a94a8",
        "accent": "#6ee7ff",
        "pane": "#202839",
        "btn": "#2c3650",
        "btn_border": "#46536e",
        "tab": "#1e2635",
        "tab_sel": "#31405c",
        "radius": 16,
        "shell": True,
        "chrome": "#2c3650",
        "glass": {"top": (35, 43, 61, 255), "bottom": (27, 34, 49, 255),
                  "border": (61, 74, 99, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 16},
    },
    "clean_white": {
        "capsule_bg": "#ffffff",
        "capsule_border": "#cfd2d8",
        "card_bg": "#f6f6f4",
        "card_bg2": "#ffffff",
        "card_border": "#cfd2d8",
        "text": "#111118",
        "subtext": "#52525e",
        "muted": "#8a8a94",
        "accent": "#0066cc",
        "pane": "#ffffff",
        "btn": "#e9ebef",
        "btn_border": "#c2c6cd",
        "tab": "#e4e6ea",
        "tab_sel": "#ffffff",
        "radius": 16,
        "shell": True,
        "chrome": "#e9ebef",
        "glass": {"top": (255, 255, 255, 255), "bottom": (246, 246, 244, 255),
                  "border": (207, 210, 216, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 16},
    },
    "white": {
        "capsule_bg": "#ffffff",
        "capsule_border": "#c9ccd2",
        "card_bg": "#ffffff",
        "card_bg2": "#ffffff",
        "card_border": "#c9ccd2",
        "text": "#191920",
        "subtext": "#45454e",
        "muted": "#76767e",
        "accent": "#0066cc",
        "pane": "#ffffff",
        "btn": "#ffffff",
        "btn_border": "#b9bdc4",
        "tab": "#ffffff",
        "tab_sel": "#eef1f4",
        "radius": 16,
        "shell": True,
        "chrome": "#ffffff",
        "glass": {"top": (255, 255, 255, 255), "bottom": (255, 255, 255, 255),
                  "border": (201, 204, 210, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 16},
    },
    "modern_dark": {
        "capsule_bg": "#151923",
        "capsule_border": "#2b3346",
        "card_bg": "#10141d",
        "card_bg2": "#1a2030",
        "card_border": "#2b3346",
        "text": "#f3f4f6",
        "subtext": "#9ca3af",
        "muted": "#6b7280",
        "accent": "#38bdf8",
        "pane": "#161c29",
        "btn": "#222a3d",
        "btn_border": "#35405a",
        "tab": "#161c29",
        "tab_sel": "#263049",
        "radius": 16,
        "shell": True,
        "chrome": "#222a3d",
        "glass": {"top": (21, 25, 35, 255), "bottom": (16, 20, 29, 255),
                  "border": (43, 51, 70, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 16},
    },
    "black": {
        "capsule_bg": "#141417",
        "capsule_border": "#2e2e35",
        "card_bg": "#101013",
        "card_bg2": "#1a1a1f",
        "card_border": "#2e2e35",
        "text": "#f2efe8",
        "subtext": "#a8a49d",
        "muted": "#6f6c68",
        "accent": "#59d98c",
        "pane": "#151519",
        "btn": "#1f1f24",
        "btn_border": "#34343c",
        "tab": "#17171b",
        "tab_sel": "#2a2a31",
        "radius": 16,
        "shell": True,
        "chrome": "#1f1f24",
        "glass": {"top": (20, 20, 23, 255), "bottom": (16, 16, 19, 255),
                  "border": (46, 46, 53, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 16},
    },
    "minimal": {
        "capsule_bg": "#141416",
        "capsule_border": "#2a2a2e",
        "card_bg": "#101012",
        "card_bg2": "#18181b",
        "card_border": "#2a2a2e",
        "text": "#e8e8e8",
        "subtext": "#a0a0a0",
        "muted": "#707070",
        "accent": "#e8e8e8",
        "pane": "#141416",
        "btn": "#1d1d20",
        "btn_border": "#333336",
        "tab": "#141416",
        "tab_sel": "#242428",
        "radius": 8,
        "shell": True,
        "chrome": "#1d1d20",
        "glass": {"top": (20, 20, 22, 255), "bottom": (16, 16, 18, 255),
                  "border": (42, 42, 46, 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 8},
    },
}


def available() -> list[tuple[str, str, str]]:
    """(key, label, description) for the Appearance tab, in order."""
    return [(k, _LABELS[k], _DESCS[k]) for k in THEME_ORDER]


def resolve(name: str) -> dict:
    """Public: the control centre needs the same resolved palette."""
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
                c = QColor(c)
                c.setAlpha(255)
                return c
        except Exception:
            pass
        return QColor(fallback)

    win = col(role("window", "Window"))
    txt = col(role("windowText", "WindowText"), "#111111")
    sub = col(role("placeholderText", "PlaceholderText"), "")
    if not sub.isValid():
        sub = QColor(txt)
    base = col(role("base", "Base"))
    mid = col(role("mid", "Mid"))
    hl = col(role("highlight", "Highlight"), "#3a7bd5")

    def css(c: QColor) -> str:
        c = QColor(c)
        c.setAlpha(255)
        return f"#{c.red():02x}{c.green():02x}{c.blue():02x}"

    darker = QColor(win)
    darker.setRed(max(0, darker.red() - 18))
    darker.setGreen(max(0, darker.green() - 18))
    darker.setBlue(max(0, darker.blue() - 18))

    return {
        "capsule_bg": css(win),
        "capsule_border": css(mid),
        "card_bg": css(win),
        "card_bg2": css(darker),
        "card_border": css(mid),
        "text": css(txt),
        "subtext": css(sub),
        "muted": css(sub),
        "accent": css(hl),
        "pane": css(base),
        "btn": css(base),
        "btn_border": css(mid),
        "tab": css(base),
        "tab_sel": css(hl),
        "radius": 14,
        "shell": True,
        "chrome": css(base),
        "glass": {"top": (win.red(), win.green(), win.blue(), 255),
                  "bottom": (darker.red(), darker.green(), darker.blue(), 255),
                  "border": (mid.red(), mid.green(), mid.blue(), 255), "bw": 1.0,
                  "gloss": False, "rim": False, "radius": 14},
    }


def apply_theme(window, name: str) -> str:
    """Style the whole island with fully opaque surfaces. Returns theme key."""
    from PySide6.QtGui import QColor

    if name not in THEME_ORDER:
        name = "black"
    t = resolve(name)
    g = t.get("glass", {})

    def qc(key, fallback=(19, 19, 23, 255)):
        v = g.get(key, fallback)
        try:
            c = QColor(*v)
        except Exception:
            c = QColor(*fallback)
        c.setAlpha(255)
        return c

    radius = int(t.get("radius", 16))
    # Every panel paints an opaque shell on every theme — no exceptions.
    for _panel_name in ("collapsed", "card", "content"):
        try:
            _panel = getattr(window, _panel_name)
            _panel.set_frameless(False)
            _panel.set_glass(qc("top"), qc("bottom"), qc("border"),
                             float(g.get("bw", 1.0)), radius, False, False)
        except Exception:
            pass
    try:
        window.center.set_frameless(False)
        window.center.set_glass(qc("top"), qc("bottom"), qc("border"),
                                float(g.get("bw", 1.0)), radius, False, False)
    except Exception:
        pass

    chrome = t.get("chrome", t["btn"])
    btn = t["btn"]
    btn_border = t["btn_border"]
    pane = t["pane"]
    card = t["card_bg"]

    window.mini_time.setStyleSheet(
        f"font-size: 15px; font-weight: 600; background: {t['capsule_bg']}; color: {t['text']};"
    )
    window.mini_temp.setStyleSheet(
        f"font-size: 11px; background: {t['capsule_bg']}; color: {t['subtext']};"
    )
    window.mini_dot.setStyleSheet(
        f"background: {t['accent']}; border-radius: 5px; min-width: 10px;"
        f" min-height: 10px; max-width: 10px; max-height: 10px;"
    )

    window.big_time.setStyleSheet(
        f"font-size: 17px; font-weight: 600; background: {card}; color: {t['text']};"
    )
    window.big_dot.setStyleSheet(
        f"background: {t['accent']}; border-radius: 5px; min-width: 10px;"
        f" min-height: 10px; max-width: 10px; max-height: 10px;"
    )
    window.big_temp.setStyleSheet(
        f"background: {card}; color: {t['subtext']}; font-size: 12px;"
    )
    window.hint.setStyleSheet(
        f"background: {card}; color: {t['muted']}; font-size: 10px;"
    )

    # Opaque, bordered, clearly pressable controls. No transparent fills,
    # no borderless buttons, no invisible tab chrome.
    window.tabs.setStyleSheet(
        f"QTabWidget::pane {{ background: {card}; border: 1px solid {t['card_border']};"
        f" border-radius: {radius // 2}px; top: -1px; }}"
        f"QTabBar::tab {{ background: {t['tab']}; color: {t['muted']};"
        f" padding: 5px 8px; font-size: 10px; font-weight: 600;"
        f" border: 1px solid {t['card_border']}; border-bottom: none;"
        f" border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 1px; }}"
        f"QTabBar::tab:selected {{ background: {t['tab_sel']}; color: {t['text']};"
        f" border-bottom: 2px solid {t['accent']}; }}"
        f"QTabBar::tab:hover:!selected {{ color: {t['text']}; background: {t['tab_sel']}; }}"
        f"QWidget {{ background: {card}; color: {t['text']}; }}"
        f"QLabel {{ background: {card}; color: {t['text']}; border: none; }}"
        f"QPushButton {{ background: {btn}; border: 1px solid {btn_border};"
        f" border-radius: 8px; padding: 6px 12px; color: {t['text']}; font-size: 11px;"
        f" font-weight: 600; }}"
        f"QPushButton:hover {{ border: 1px solid {t['accent']}; color: {t['accent']}; }}"
        f"QPushButton:pressed {{ background: {t['tab_sel']}; }}"
        f"QPushButton:disabled {{ background: {pane}; color: {t['muted']};"
        f" border: 1px solid {t['card_border']}; }}"
        f"QToolButton {{ background: {btn}; border: 1px solid {btn_border};"
        f" border-radius: 8px; color: {t['text']}; font-size: 13px; font-weight: 600;"
        f" padding: 6px; }}"
        f"QToolButton:hover {{ border: 1px solid {t['accent']}; color: {t['accent']}; }}"
        f"QToolButton:pressed {{ background: {t['tab_sel']}; }}"
        f"QCheckBox {{ color: {t['text']}; background: {card}; spacing: 8px; }}"
        f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;"
        f" border: 1px solid {btn_border}; background: {pane}; }}"
        f"QCheckBox::indicator:checked {{ border: 1px solid {t['accent']};"
        f" background: {t['accent']}; }}"
        f"QSpinBox {{ background: {pane}; border: 1px solid {btn_border};"
        f" border-radius: 6px; padding: 4px 6px; color: {t['text']}; }}"
        f"QSpinBox::up-button, QSpinBox::down-button {{ background: {btn};"
        f" border: 1px solid {btn_border}; width: 16px; border-radius: 4px; }}"
        f"QScrollBar:vertical {{ background: {card}; width: 10px; margin: 2px;"
        f" border: none; border-radius: 5px; }}"
        f"QScrollBar::handle:vertical {{ background: {btn_border};"
        f" border-radius: 5px; min-height: 28px; }}"
        f"QScrollBar::handle:vertical:hover {{ background: {t['accent']}; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        f"QScrollArea {{ background: {card}; border: 1px solid {t['card_border']};"
        f" border-radius: 8px; }}"
        f"QLineEdit {{ background: {pane}; border: 1px solid {btn_border};"
        f" border-radius: 6px; padding: 6px 8px; color: {t['text']};"
        f" selection-background-color: {t['accent']}; }}"
        f"QLineEdit:focus {{ border: 1px solid {t['accent']}; }}"
        f"QComboBox {{ background: {pane}; border: 1px solid {btn_border};"
        f" border-radius: 6px; padding: 5px 8px; color: {t['text']}; }}"
        f"QComboBox::drop-down {{ border: none; width: 20px; background: {pane}; }}"
        f"QComboBox QAbstractItemView {{ background: {pane}; color: {t['text']};"
        f" selection-background-color: {t['tab_sel']};"
        f" selection-color: {t['text']}; border: 1px solid {btn_border}; }}"
        f"QListWidget {{ background: {pane}; border: 1px solid {t['card_border']};"
        f" border-radius: 8px; color: {t['text']}; padding: 4px; }}"
        f"QListWidget::item {{ background: {pane}; border-radius: 4px; padding: 3px; }}"
        f"QListWidget::item:selected {{ background: {t['tab_sel']};"
        f" color: {t['text']}; border: 1px solid {t['accent']}; }}"
        f"QTextEdit {{ background: {pane}; border: 1px solid {t['card_border']};"
        f" border-radius: 8px; color: {t['text']}; padding: 4px; }}"
        f"QProgressBar {{ background: {pane}; border: 1px solid {t['card_border']};"
        f" border-radius: 6px; color: {t['text']}; text-align: center;"
        f" max-height: 14px; }}"
        f"QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}"
        f"QRadioButton {{ color: {t['text']}; background: {card}; }}"
        f"QCalendarWidget QWidget {{ background: {pane}; color: {t['text']};"
        f" selection-background-color: {t['accent']}; }}"
        f"QCalendarWidget QAbstractItemView:enabled {{ background: {pane};"
        f" color: {t['text']}; selection-background-color: {t['accent']};"
        f" selection-color: {t['text']}; outline: none; }}"
        f"QMenu {{ background: {pane}; color: {t['text']};"
        f" border: 1px solid {btn_border}; }}"
        f"QMenu::item:selected {{ background: {t['tab_sel']}; color: {t['text']}; }}"
    )
    # clock + bot-tab labels (inherit tabs sheet, but pin subtext tones)
    try:
        window.bot_tab.clock.setStyleSheet(
            f"font-size: 34px; font-weight: 700; background: {card}; color: {t['text']};"
        )
        window.bot_tab.date.setStyleSheet(
            f"background: {card}; color: {t['subtext']}; font-size: 13px;"
        )
        window.bot_tab.utc_lbl.setStyleSheet(
            f"background: {card}; color: {t['muted']}; font-size: 11px;"
        )
    except Exception:
        pass
    # theme-tinted SVG icons (emoji-free UI)
    try:
        from . import icons as iconsmod
        ink = t["text"]
        window.bot_tab.shuffle_btn.setIcon(iconsmod.icon("dice", 18, ink))
        for eid, btn_w in window.bot_tab.emo_buttons.items():
            ic = window.bot_tab.EMOTION_ICONS.get(eid)
            if ic:
                btn_w.setIcon(iconsmod.icon(ic, 14, ink))
        pm = iconsmod.pixmap("thermo", 14, ink)
        if pm is not None:
            window.sys_tab.temp_icon.setPixmap(pm)
        try:
            window.svc_tab.set_icon_tint(ink)
        except Exception:
            pass
        try:
            window.svc_tab.insta._body.setStyleSheet(f"background: {pane};")
        except Exception:
            pass
    except Exception:
        pass
    return name
