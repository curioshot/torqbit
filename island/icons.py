"""Inline SVG icons — no emoji anywhere in the UI.

All icons use `currentColor` so the active theme tints them.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap

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
}

SHUFFLE_SENTINEL = "__shuffle__"


def pixmap(name: str, size: int = 16, color: str = "#f2efe8") -> QPixmap | None:
    """Render an icon to a pixmap, or None if SVG rendering is unavailable."""
    if not _SVG_OK or name not in _SVGS:
        return None
    try:
        data = _SVGS[name].replace("currentColor", color).encode("utf-8")
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        QSvgRenderer(data).render(p)
        p.end()
        return QPixmap.fromImage(img)
    except Exception:
        return None


def icon(name: str, size: int = 16, color: str = "#f2efe8") -> QIcon:
    pm = pixmap(name, size, color)
    return QIcon(pm) if pm is not None else QIcon()
