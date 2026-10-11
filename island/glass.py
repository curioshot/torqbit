"""OpaquePanel: QPainter-painted rounded container (no glass, no transparency).

The old liquid-glass look (translucent fill + compositor blur + specular
gloss) is gone on purpose: it only ever looked right under KWin blur, it
degraded to a muddy translucent box everywhere else, and floating controls
with no container behind them read as visual garbage — especially the
full-island panel after a double-click.

Every panel now paints a fully opaque rounded rect: solid fill, 1px solid
border, optional subtle top-light gradient (both stops fully opaque).
`set_glass()` / `set_frameless()` / `is_frameless()` are kept as
compatibility shims so old callers keep working, but they no longer make
anything transparent — `is_frameless()` always reports False and
`paintEvent` always paints.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


def _opaque(color) -> QColor:
    """Force full opacity — any translucent theme value becomes solid."""
    c = QColor(color) if not isinstance(color, QColor) else QColor(color)
    if not c.isValid():
        c = QColor(19, 19, 23)
    c.setAlpha(255)
    return c


class GlassPanel(QWidget):
    """A structural panel that always paints an opaque rounded background."""

    def __init__(self, parent=None, frameless: bool = False):
        super().__init__(parent)
        self._top = QColor(22, 22, 27)
        self._bottom = QColor(16, 16, 20)
        self._border = QColor(48, 48, 58)
        self._border_w = 1.0
        self._radius = 16
        self._gloss = False
        self._rim = False
        # Kept only so old calls don't crash; panels are always opaque now.
        self._frameless = False
        # Do NOT set WA_TranslucentBackground / WA_NoSystemBackground here:
        # child panels must be fully opaque. Only the top-level window keeps
        # WA_TranslucentBackground (for rounded outer corners) — see window.py.
        self.setAutoFillBackground(False)

    def set_frameless(self, on: bool = True) -> None:
        # No-op by design: transparency was removed project-wide. Kept for
        # backwards compatibility with themes.apply_theme() and tests.
        self._frameless = False
        self.update()

    def is_frameless(self) -> bool:
        return False

    def set_glass(self, top: QColor, bottom: QColor, border: QColor,
                  border_w: float = 1.0, radius: int = 16,
                  gloss: bool = False, rim: bool = False) -> None:
        self._top = _opaque(top)
        self._bottom = _opaque(bottom)
        self._border = _opaque(border)
        self._border_w = float(border_w) if border_w else 1.0
        self._radius = int(radius)
        # Gloss/rim highlights are subtle opaque lightening only; never alpha.
        self._gloss = False
        self._rim = False
        self.update()

    def paintEvent(self, event):  # noqa: N802
        w, h = self.width(), self.height()
        if w < 4 or h < 4:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pad = self._border_w / 2.0 + 0.5
        r = max(0, min(self._radius, int(min(w, h) / 2)))

        path = QPainterPath()
        path.addRoundedRect(pad, pad, w - 2 * pad, h - 2 * pad, r, r)

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, self._top)
        grad.setColorAt(1, self._bottom)
        p.fillPath(path, grad)

        p.setPen(QPen(self._border, self._border_w))
        p.drawPath(path)
        p.end()


# Backwards-compat alias: some imports may still say GlassPanel.
OpaquePanel = GlassPanel
