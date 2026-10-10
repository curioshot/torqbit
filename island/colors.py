"""CSS colour strings -> QColor.

The themes are authored as CSS because half of them end up in a Qt style
sheet. The other half are handed to QPainter / QSvgRenderer, which cannot
read that spelling:

* ``rgba(216, 224, 238, 200)`` — Qt's SVG renderer draws **nothing at all**
  for a stroke in this form, so an icon tinted with one renders as an empty
  square. Every icon on the ``system`` theme was invisible for this reason.
* ``transparent`` — not a valid QColor name; it silently became black.
* the old local parser also dropped the alpha channel, so a 6%-opacity pane
  came out fully opaque.

Everything here normalises to a real QColor with alpha intact, and never
raises.
"""
from __future__ import annotations

import re

from PySide6.QtGui import QColor

_FUNC = re.compile(
    r"rgba?\(\s*([\d.]+%?)\s*,\s*([\d.]+%?)\s*,\s*([\d.]+%?)"
    r"(?:\s*,\s*([\d.]+%?)\s*)?\)", re.I)

_NAMED = {
    "transparent": QColor(0, 0, 0, 0),
    "none": QColor(0, 0, 0, 0),
    "black": QColor(0, 0, 0),
    "white": QColor(255, 255, 255),
}

# Semantic accents. These are deliberately *not* per-theme: "this failed" has
# to read as failure in every theme, including the monochrome one.
ERROR = QColor("#ff6b6b")
DANGER = QColor("#e5484d")
OK = QColor("#30a46c")


def _channel(raw: str, scale: int) -> int:
    raw = (raw or "").strip()
    if raw.endswith("%"):
        try:
            return max(0, min(scale, int(round(float(raw[:-1]) * scale / 100.0))))
        except ValueError:
            return 0
    try:
        return max(0, min(scale, int(round(float(raw)))))
    except ValueError:
        return 0


def _alpha(raw: str | None) -> int:
    """Alpha to 0..255.

    Two conventions are in play and both reach this function. Qt style
    sheets (and this codebase's own `css()` helper) write alpha as a plain
    0..255 integer, while CSS proper writes a 0..1 fraction. The presence of
    a decimal point is the unambiguous discriminator — `200` is Qt,
    `0.5` is CSS — so there is no guessing.
    """
    if raw is None:
        return 255
    raw = raw.strip()
    if raw.endswith("%"):
        try:
            return max(0, min(255, int(round(float(raw[:-1]) * 255 / 100.0))))
        except ValueError:
            return 255
    try:
        value = float(raw)
    except ValueError:
        return 255
    if "." in raw:
        value = value * 255.0
    return max(0, min(255, int(round(value))))


def to_qcolor(value, fallback: QColor | str = "#f2efe8") -> QColor:
    """Best-effort conversion of any CSS colour spelling Qt might see.

    Falls back to ``fallback`` rather than to black: black is almost never
    the intended ink on a dark card, and silently picking it is what made
    the old parser so hard to diagnose.
    """
    fb = fallback if isinstance(fallback, QColor) else QColor(fallback)
    if isinstance(value, QColor):
        return QColor(value)
    if not isinstance(value, str):
        return QColor(fb)
    s = value.strip()
    if not s:
        return QColor(fb)

    low = s.lower()
    if low in _NAMED:
        return QColor(_NAMED[low])

    m = _FUNC.match(s)
    if m:
        return QColor(_channel(m.group(1), 255),
                      _channel(m.group(2), 255),
                      _channel(m.group(3), 255),
                      _alpha(m.group(4)))

    if s.startswith("#"):
        # Qt understands #rgb, #rgba, #rrggbb and #aarrggbb already.
        col = QColor(s)
        return QColor(col) if col.isValid() else QColor(fb)

    col = QColor(low)          # the rest of the SVG/CSS named colours
    return QColor(col) if col.isValid() else QColor(fb)


def to_hex(value, fallback: str = "#f2efe8", keep_alpha: bool = False) -> str:
    """Normalised hex string — for the places that build a QSS fragment.

    Qt style sheets accept ``#rrggbb`` and ``rgba(r,g,b,a)`` but not the
    8-digit ``#aarrggbb`` form, so alpha is either dropped or spelled out.
    """
    col = to_qcolor(value, fallback)
    if not col.isValid():
        col = QColor(fallback)
    if keep_alpha and col.alpha() < 255:
        return f"rgba({col.red()}, {col.green()}, {col.blue()}, {col.alpha()})"
    return f"#{col.red():02x}{col.green():02x}{col.blue():02x}"


def ink(value, fallback: str = "#f2efe8") -> str:
    """Hex for an SVG stroke: alpha is flattened away, because a semi-
    transparent `currentColor` stroke is what Qt's renderer refuses."""
    col = to_qcolor(value, fallback)
    if not col.isValid():
        col = QColor(fallback)
    return f"#{col.red():02x}{col.green():02x}{col.blue():02x}"