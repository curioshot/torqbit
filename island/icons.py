"""Inline SVG icons — no emoji anywhere in the UI.

All icons use `currentColor` so the active theme tints them.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (QIcon, QImage, QPainter, QPixmap, QGuiApplication)

from . import colors as colorsmod

try:
    from PySide6.QtSvg import QSvgRenderer
    _SVG_OK = True
except Exception:  # pragma: no cover
    _SVG_OK = False

_SVGS = {
    # die face-5 in a rounded square
    "dice": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<rect x="3.5" y="3.5" width="17" height="17" rx="4"/>'
        '<g fill="currentColor" stroke="none">'
        '<circle cx="8.2" cy="8.2" r="1.5"/><circle cx="15.8" cy="8.2" r="1.5"/>'
        '<circle cx="12" cy="12" r="1.5"/>'
        '<circle cx="8.2" cy="15.8" r="1.5"/><circle cx="15.8" cy="15.8" r="1.5"/>'
        "</g></svg>"
    ),
    # party popper: cone + burst + confetti
    "party": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 20 13 11l-4.5-.5L4 20z"/>'
        '<path d="M13 11l1.5-5 2 3.5L20 8l-1 3 3.5 1.5"/>'
        '<circle cx="18.5" cy="4.5" r="1.1"/><circle cx="21" cy="15.5" r="1.1"/>'
        "</svg>"
    ),
    # thermometer
    "thermo": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<path d="M10 4a2 2 0 0 1 4 0v8.5a4.5 4.5 0 1 1-4 0V4z"/>'
        '<circle cx="12" cy="17.5" r="1.6" fill="currentColor" stroke="none"/>'
        "</svg>"
    ),
    # palette (appearance)
    "palette": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8">'
        '<circle cx="12" cy="12" r="8.5"/>'
        '<g fill="currentColor" stroke="none">'
        '<circle cx="9" cy="9.5" r="1.2"/><circle cx="13" cy="8.5" r="1.2"/>'
        '<circle cx="15.5" cy="12" r="1.2"/><circle cx="9.5" cy="14" r="1.2"/>'
        "</g></svg>"
    ),
    # camera glyph (instagram service)
    "instagram": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8">'
        '<rect x="3.5" y="5" width="17" height="14" rx="4.5"/>'
        '<circle cx="12" cy="12" r="3.6"/>'
        '<circle cx="17" cy="9" r="1.2" fill="currentColor" stroke="none"/>'
        "</svg>"
    ),
    # music glyph (spotify service)
    "spotify": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M8.5 10.5c2.5-1.2 5-.8 7 .5"/>'
        '<path d="M8.5 13.2c2-1 4-.6 5.6.4"/>'
        '<path d="M8.7 15.7c1.4-.7 2.8-.4 4 .3"/>'
        "</svg>"
    ),
    # --- control centre ---
    # microphone (capsule + stand + base)
    "mic": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<rect x="9" y="3" width="6" height="10" rx="3"/>'
        '<path d="M5.5 11a6.5 6.5 0 0 0 13 0"/>'
        '<path d="M12 17.5V21M9 21h6"/>'
        "</svg>"
    ),
    # speaker (output volume)
    "speaker": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4 9.5h3L11 6v12L7 14.5H4z"/>'
        '<path d="M14.5 9.5a3.6 3.6 0 0 1 0 5"/>'
        '<path d="M17.2 7a7 7 0 0 1 0 10"/>'
        "</svg>"
    ),
    # sun (brightness)
    "sun": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2'
        'M5.4 5.4l1.4 1.4M17.2 17.2l1.4 1.4M18.6 5.4l-1.4 1.4M6.8 17.2l-1.4 1.4"/>'
        "</svg>"
    ),
    # airplane (flight mode)
    "plane": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10.5 3.2a1.5 1.5 0 0 1 3 0V9l7 4.2v2.1l-7-2.2v4.3l2.3 1.7v1.6'
        'L12 19.6l-3.8 1.1v-1.6l2.3-1.7v-4.3l-7 2.2v-2.1L10.5 9z"/>'
        "</svg>"
    ),
    # globe (network link)
    "globe": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8">'
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M3.5 12h17"/>'
        '<ellipse cx="12" cy="12" rx="4" ry="8.5"/>'
        "</svg>"
    ),
    # wifi arcs
    "wifi": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<path d="M2.8 9.2a13.5 13.5 0 0 1 18.4 0"/>'
        '<path d="M6.3 12.8a8.5 8.5 0 0 1 11.4 0"/>'
        '<path d="M9.8 16.4a3.6 3.6 0 0 1 4.4 0"/>'
        '<circle cx="12" cy="19.4" r="1" fill="currentColor" stroke="none"/>'
        "</svg>"
    ),
    # bluetooth rune
    "bt": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M8 7.2 16 16.4 12 19.6V4.4l4 3.2L8 16.8"/>'
        "</svg>"
    ),
    # bell with a slash (do not disturb)
    "dnd": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6.5 10a5.5 5.5 0 0 1 11 0c0 4 1.5 5.5 1.5 5.5H5S6.5 14 6.5 10z"/>'
        '<path d="M10.2 18.5a2 2 0 0 0 3.6 0"/>'
        '<path d="M4 4l16 16"/>'
        "</svg>"
    ),
    # padlock (lock screen)
    "lock": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="4.8" y="10.5" width="14.4" height="9.5" rx="2.4"/>'
        '<path d="M8.2 10.5V8a3.8 3.8 0 0 1 7.6 0v2.5"/>'
        "</svg>"
    ),
    # rss wave (feed panel)
    "rss": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<circle cx="6.2" cy="17.8" r="1.5" fill="currentColor" stroke="none"/>'
        '<path d="M4.5 11.2a8.3 8.3 0 0 1 8.3 8.3"/>'
        '<path d="M4.5 5.8a13.7 13.7 0 0 1 13.7 13.7"/>'
        "</svg>"
    ),
    # download arrow into a tray (refresh feeds)
    "refresh": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 4v10"/><path d="M8.2 10.4 12 14.2l3.8-3.8"/>'
        '<path d="M4.5 16.5v2a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-2"/>'
        "</svg>"
    ),
    # memory / ram chip
    "ram": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3.5" y="7.5" width="17" height="9" rx="1.8"/>'
        '<rect x="7" y="10.5" width="6" height="3" rx="0.8"/>'
        '<path d="M7 16.5v2M11 16.5v2M15 16.5v2M17 16.5v2"/>'
        "</svg>"
    ),
    # cpu chip (load)
    "cpu": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>'
        '<rect x="10" y="10" width="4" height="4" rx="0.8"/>'
        '<path d="M9.5 6.5V3.5M14.5 6.5V3.5M9.5 20.5v-3M14.5 20.5v-3'
        'M6.5 9.5h-3M6.5 14.5h-3M20.5 9.5h-3M20.5 14.5h-3"/>'
        "</svg>"
    ),
    # up/down arrows (network speed)
    "speed": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 19V9M6 9 3.2 11.8M6 9l2.8 2.8"/>'
        '<path d="M12 5v10M12 15l-2.8-2.8M12 15l2.8-2.8"/>'
        '<path d="M18 19v-6M18 13l-2.8 2.8M18 13l2.8 2.8"/>'
        "</svg>"
    ),
    # plus (add feed)
    "plus": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round">'
        '<path d="M12 5.5v13M5.5 12h13"/>'
        "</svg>"
    ),
    # trash (remove feed)
    "trash": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M4.5 6.5h15M9.5 6.5V4.2h5v2.3"/>'
        '<path d="M6.8 6.5 7.7 20a1 1 0 0 0 1 .9h6.6a1 1 0 0 0 1-.9l.9-13.5"/>'
        '<path d="M10.4 10v7M13.6 10v7"/>'
        "</svg>"
    ),
    # moon (dark theme)
    "moon": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 14.2A8.4 8.4 0 0 1 9.8 4 8.5 8.5 0 1 0 20 14.2z"/>'
        "</svg>"
    ),
    # power symbol (theme toggle uses it too)
    "power": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round">'
        '<path d="M12 3.5v8"/>'
        '<path d="M17.4 6.6a7.5 7.5 0 1 1-10.8 0"/>'
        "</svg>"
    ),
}

SHUFFLE_SENTINEL = "__shuffle__"


@lru_cache(maxsize=512)
def _rasterize(name: str, size: int, dpr: float, rgb: tuple[int, int, int]):
    """SVG bytes -> QPixmap, memoised.

    Rasterising an SVG means parsing its XML, allocating a QImage and
    uploading a texture. That used to happen on every paintEvent — three
    sliders at 25 Hz plus eight toggles is eleven full rasterisations per
    frame. The cache is keyed by device pixel ratio, so a screen change
    still produces a correctly-sized bitmap.
    """
    data = (_SVGS[name]
            .replace("currentColor", "#%02x%02x%02x" % rgb)
            .encode("utf-8"))
    px = max(1, int(round(size * dpr)))
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return None
    p = QPainter(img)
    try:
        renderer.render(p, QRectF(0, 0, px, px))
    finally:
        p.end()
    pm = QPixmap.fromImage(img)
    # Without this the 1x bitmap gets upscaled and every icon is soft on a
    # HiDPI display, while the QPainter-drawn parts stay crisp.
    pm.setDevicePixelRatio(dpr)
    return pm


def _dpr() -> float:
    try:
        screen = QGuiApplication.primaryScreen()
        return float(screen.devicePixelRatio()) if screen else 1.0
    except Exception:
        return 1.0


def pixmap(name: str, size: int = 16, color: str = "#f2efe8") -> QPixmap | None:
    """Render an icon to a pixmap, or None if SVG rendering is unavailable.

    `color` may be any CSS spelling — including ``rgba(...)``, which Qt's SVG
    renderer silently refuses to draw at all.
    """
    if not _SVG_OK or name not in _SVGS:
        return None
    try:
        col = colorsmod.to_qcolor(color, "#f2efe8")
        if not col.isValid():
            return None
        return _rasterize(name, int(size), _dpr(),
                          (col.red(), col.green(), col.blue()))
    except Exception:
        return None


def icon(name: str, size: int = 16, color: str = "#f2efe8") -> QIcon:
    pm = pixmap(name, size, color)
    return QIcon(pm) if pm is not None else QIcon()
