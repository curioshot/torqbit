"""GlassPanel: QPainter-painted rounded container.

Stylesheets can't be trusted for the outer shell (child widgets with opaque
fills can square off the corners, and gradient+radius has platform quirks),
so the capsule / card / content shells paint themselves: vertical gradient
veil, bright edge, top specular highlight, inner rim light — the Apple
liquid-glass recipe elements that translate to Qt:

  web recipe                              -> Qt translation
  thin bright border rgba(255,255,255,.3) -> 1.5px light pen
  inset 0 1px 0 white specular            -> gloss gradient overlay, top 45%
  backdrop blur + saturate                -> KWin blurs translucent areas live;
                                             we keep alpha low so it can work
  soft drop shadow                        -> second inner rim + border glow
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class GlassPanel(QWidget):
    """A structural panel that, by default, paints nothing.

    Originally this drew a frosted rounded rect — translucent fill, 1px
    border, specular gloss — and relied on the compositor's "blur behind"
    to do the frosting. The flagship look was therefore only ever really
    present under KCompositor, and degraded to a flat translucent box
    everywhere else.

    The UI is now deliberately frameless: containers, buttons and controls
    sit directly on the screen with no background and no border. The class
    is kept as the single layout shell the window builds from (it owns the
    translucent-background attribute), but it paints nothing.
    `set_glass()` is retained for any caller that wants the old chrome back.
    """

    def __init__(self, parent=None, frameless: bool = True):
        super().__init__(parent)
        self._top = QColor(13, 13, 16, 246)
        self._bottom = QColor(13, 13, 16, 246)
        self._border = QColor(46, 46, 53)
        self._border_w = 1.0
        self._radius = 20
        self._gloss = False
        self._rim = False
        self._frameless = bool(frameless)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if self._frameless:
            # Nothing to draw, so skip the backing store entirely.
            self.setAttribute(Qt.WA_NoSystemBackground, True)

    def set_frameless(self, on: bool = True) -> None:
        self._frameless = bool(on)
        self.setAttribute(Qt.WA_NoSystemBackground, self._frameless)
        self.update()

    def is_frameless(self) -> bool:
        return self._frameless

    def set_glass(self, top: QColor, bottom: QColor, border: QColor,
                  border_w: float = 1.0, radius: int = 20,
                  gloss: bool = False, rim: bool = False) -> None:
        self._top = QColor(top)
        self._bottom = QColor(bottom)
        self._border = QColor(border)
        self._border_w = float(border_w)
        self._radius = int(radius)
        self._gloss = bool(gloss)
        self._rim = bool(rim)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        if self._frameless:
            return
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

        if self._gloss:
            # specular: white veil, strong at the very top, gone by ~45%
            gloss = QLinearGradient(0, 0, 0, h * 0.5)
            gloss.setColorAt(0, QColor(255, 255, 255, 70))
            gloss.setColorAt(0.55, QColor(255, 255, 255, 14))
            gloss.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillPath(path, gloss)

        p.setPen(QPen(self._border, self._border_w))
        p.drawPath(path)

        if self._rim:
            # inner rim light: second hairline just inside the edge
            inset = pad + self._border_w + 0.5
            r2 = max(0, r - 2)
            rim_path = QPainterPath()
            rim_path.addRoundedRect(inset, inset, w - 2 * inset, h - 2 * inset, r2, r2)
            p.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
            p.drawPath(rim_path)
