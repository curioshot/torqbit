"""Painted widgets for the control centre.

Same approach as glass.py: everything here is drawn with QPainter rather than
styled with QSS, so rounded caps, arcs and rings survive Qt's stylesheet
quirks and every part picks up the active theme's colours.

Every widget follows the same rule: when a capability is unavailable the
widget renders itself *disabled* — visibly inert rather than silently
doing nothing — and carries the reason in its tooltip.
"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QRectF, QPoint, QPointF, Signal, QTimer
from PySide6.QtGui import (QColor, QPainter, QPen)
from PySide6.QtWidgets import QWidget, QSizePolicy

from . import colors as colorsmod

# Default palette; themes.apply_theme() overwrites these per theme.
PALETTE = {
    "ink": "#f2efe8",
    "sub": "#a8a49d",
    "muted": "#6f6c68",
    "track": "#26262c",
    "accent": "#59d98c",
    "warn": "#c9a227",
    "off": "#55555c",
}


def _c(value, alpha=None) -> QColor:
    col = QColor(value)
    if not col.isValid():
        col = QColor(PALETTE["ink"])
    if alpha is not None:
        col.setAlpha(alpha)
    return col


class Tintable:
    """Mixin: remembers theme colours so a theme change repaints."""

    def apply_palette(self, palette: dict) -> None:
        self._pal = dict(PALETTE)
        self._pal.update({k: v for k, v in palette.items() if isinstance(v, str)})
        self._pal.setdefault("ink", "#f2efe8")
        self._pal.setdefault("track", "#26262c")
        self._pal.setdefault("accent", "#59d98c")
        self._pal.setdefault("off", "#55555c")
        self.update()


# Quiet-slider geometry, in logical pixels.
SLIDER_TRACK_W = 2.0     # the visible line
SLIDER_GRAB_W = 28.0     # invisible but easy to hit
SLIDER_KNOB_R = 9.0      # the only bright part
SLIDER_TRACK_ALPHA = 46  # ~18% opacity: present, not loud
SLIDER_ICON_ALPHA = 140
SLIDER_ICON_PX = 15


class VerticalSlider(Tintable, QWidget):
    """Drag-to-set vertical bar: a faint line, no fill, one clear knob."""

    valueChanged = Signal(float)      # emitted while dragging
    released = Signal(float)          # emitted once on release

    def __init__(self, icon_name: str = "sun", label: str = "", parent=None):
        super().__init__(parent)
        self._pal = dict(PALETTE)
        self.icon_name = icon_name
        self._value = 1.0
        self._shown = 1.0
        self._enabled_ctrl = True
        self._hover = False
        self._press = False
        self._moved = False
        self._caption = label
        self._reason = ""
        self._grab_offset: QPoint | None = None
        # three of these share a 96px rail: 32 each, no overflow
        self.setFixedWidth(32)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        # Keyboard-operable: the control centre used to have no focus policy
        # at all, so none of it could be reached without a mouse.
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(label or icon_name)
        self.setAccessibleDescription(
            "Drag vertically, or use the arrow keys, to change this value")
        # The animation timer only runs while a value is actually moving:
        # three sliders at 25Hz each is 75 needless wakeups a second.
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate)

    # -- state ----------------------------------------------------------
    def set_value(self, v: float, emit: bool = False) -> None:
        v = max(0.0, min(1.0, float(v)))
        self._value = v
        if abs(self._shown - v) > 0.004:
            if not self._tick.isActive():
                self._tick.start(40)
        if emit:
            self.valueChanged.emit(v)
        self.update()

    def value(self) -> float:
        return self._value

    def set_control_enabled(self, ok: bool, reason: str = "") -> None:
        """Disable the control itself (hardware absent) — drawn greyed."""
        if ok == self._enabled_ctrl and reason == self._reason:
            return
        self._enabled_ctrl = ok
        self._reason = reason
        self.setCursor(Qt.PointingHandCursor if ok else Qt.ArrowCursor)
        self.setToolTip(reason if not ok else "")
        self.update()

    def set_caption(self, text: str) -> None:
        if text != self._caption:
            self._caption = text
            self.update()

    # -- interaction ----------------------------------------------------
    def _geometry(self):
        w, h = self.width(), self.height()
        cap = 14 if self._caption else 8
        top = SLIDER_ICON_PX + 6
        bot = h - cap - 6
        return (w - SLIDER_TRACK_W) / 2.0, top, max(10.0, bot - top)

    def _value_from_pos(self, pos) -> float:
        _, top, height = self._geometry()
        if height <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - (pos.y() - top) / height))

    def is_dragging(self) -> bool:
        """True while the user is actively moving this slider."""
        return bool(self._press)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._enabled_ctrl:
            self._press = True
            self._moved = False
            self.set_value(self._value_from_pos(event.position().toPoint()), emit=True)
            self.set_cursor_grab(True)
            # Qt only delivers move/release to this widget while the pointer
            # is inside its rect. The column is 32 logical px wide — far
            # narrower than a finger or a mouse's own width — so without an
            # explicit grab the drag dies the moment the pointer drifts
            # sideways, and the user has to release and re-press.
            self.grabMouse()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press and self._enabled_ctrl:
            self._moved = True
            self.set_value(self._value_from_pos(self._drag_pos(event)), emit=True)

    def _drag_pos(self, event):
        """Event position, corrected for the implicit grab offset."""
        pos = event.position().toPoint()
        off = getattr(self, "_grab_offset", None)
        if off is not None:
            pos += off
        return pos

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._press:
            if event.button() == Qt.LeftButton:
                self._press = False
                self._grab_offset = None
                try:
                    self.releaseMouse()
                except Exception:
                    pass
                self.set_cursor_grab(False)
                self.set_value(self._value_from_pos(event.position().toPoint()),
                               emit=True)
                self.released.emit(self._value)
            else:
                # A non-left release (extra button, right-click mid-drag)
                # must not leave _press latched on forever.
                self._press = False
                self._grab_offset = None
                try:
                    self.releaseMouse()
                except Exception:
                    pass
                self.set_cursor_grab(False)

    def set_cursor_grab(self, on: bool) -> None:
        if on:
            self.setCursor(Qt.ClosedHandCursor)
        else:
            self.setCursor(Qt.PointingHandCursor if self._enabled_ctrl
                           else Qt.ArrowCursor)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    # -- keyboard --------------------------------------------------------
    def keyPressEvent(self, event):  # noqa: N802
        if not self._enabled_ctrl:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_Right):
            self._nudge(0.05)
        elif key in (Qt.Key_Down, Qt.Key_Left):
            self._nudge(-0.05)
        elif key == Qt.Key_PageUp:
            self._nudge(0.2)
        elif key == Qt.Key_PageDown:
            self._nudge(-0.2)
        elif key == Qt.Key_Home:
            self._nudge(-2.0)
        elif key == Qt.Key_End:
            self._nudge(2.0)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _nudge(self, delta: float) -> None:
        self.set_value(max(0.0, min(1.0, self._value + delta)))
        self.released.emit(self._value)

    # -- animation ------------------------------------------------------
    def _animate(self) -> None:
        if not self.isVisible():
            self._tick.stop()
            return
        if abs(self._shown - self._value) > 0.004:
            self._shown += (self._value - self._shown) * 0.35
            self.update()
        else:
            self._shown = self._value
            self._tick.stop()   # settled: stop waking up

    # -- paint ----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, top, height = self._geometry()

        track_col = _c(self._pal["ink"],
                       SLIDER_TRACK_ALPHA if self._enabled_ctrl
                       else SLIDER_TRACK_ALPHA // 3)

        # the track: a single faint hairline, no fill anywhere
        p.setPen(Qt.NoPen)
        p.setBrush(track_col)
        p.drawRoundedRect(QRectF(cx, top, SLIDER_TRACK_W, height),
                          SLIDER_TRACK_W / 2, SLIDER_TRACK_W / 2)

        # hover: a barely-there halo so the grab area is discoverable
        if self._hover and self._enabled_ctrl:
            p.setBrush(_c(self._pal["ink"], 16))
            p.drawRoundedRect(
                QRectF(cx - SLIDER_GRAB_W / 2, top, SLIDER_GRAB_W, height),
                SLIDER_GRAB_W / 2, SLIDER_GRAB_W / 2)

        # the knob — the only bright element
        ky = top + height - height * self._shown
        kr = SLIDER_KNOB_R + (1.5 if (self._hover and self._enabled_ctrl) else 0)
        accent = _c(self._pal["accent"] if self._enabled_ctrl
                    else self._pal["off"])
        p.setBrush(_c(self._pal.get("bg", "#101013"), 240))
        p.setPen(QPen(accent, 2.0))
        p.drawEllipse(QPointF(cx + SLIDER_TRACK_W / 2, ky), kr, kr)

        # icon above
        from . import icons as iconsmod
        pm = iconsmod.pixmap(self.icon_name, SLIDER_ICON_PX, self._pal["ink"])
        if pm is not None:
            p.setOpacity((SLIDER_ICON_ALPHA if self._enabled_ctrl else 60) / 255.0)
            p.drawPixmap(int((w - pm.width()) / 2), 4, pm)
            p.setOpacity(1.0)

        # caption
        if self._caption:
            p.setPen(_c(self._pal["ink"] if self._enabled_ctrl
                        else self._pal["off"]))
            f = p.font()
            f.setPointSizeF(7.0)
            p.setFont(f)
            fm = p.fontMetrics()
            p.drawText(QRectF(0, h - 15, w, 13), Qt.AlignCenter,
                       fm.elidedText(self._caption, Qt.ElideRight, w - 2))
        p.end()


class RingGauge(Tintable, QWidget):
    """Concentric arcs for several metrics, with a numeric readout in the middle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pal = dict(PALETTE)
        self._rings: list[dict] = []
        self._enabled_ctrl = True
        self._hover = False
        self._subtitle = ""
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def set_metric(self, label: str, value: float, cap: float = 100.0,
                   fmt: str = "%.0f%%") -> None:
        for r in self._rings:
            if r["label"] == label:
                r.update(value=value, frac=max(0.0, min(1.0, value / cap)))
                self.update()
                return
        self._rings.append({"label": label, "value": value, "cap": cap,
                            "frac": max(0.0, min(1.0, value / cap)), "fmt": fmt})
        self.update()

    def clear_metrics(self) -> None:
        if self._rings:
            self._rings = []
            self.update()

    def set_center(self, top: str, sub: str = "") -> None:
        self._center = top
        self._subtitle = sub
        self.update()

    def set_control_enabled(self, ok: bool, reason: str = "") -> None:
        if ok != self._enabled_ctrl:
            self._enabled_ctrl = ok
            self.setToolTip(reason if not ok else "")
            self.update()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        # Reserve room at the bottom for the legend so rings never collide.
        legend_h = 13 if self._rings else 0
        usable_h = max(40.0, h - legend_h - 10)
        base = min(w / 2 - 10, usable_h / 2 - 10)
        thickness = max(6.0, base * 0.085)

        p.setPen(Qt.NoPen)
        p.setBrush(_c(self._pal.get("bg", "#0d0d10"), 235))
        p.drawEllipse(QPointF(cx, cy), base + thickness * 0.5,
                     base + thickness * 0.5)

        start = 145  # degrees: leave a gap at the bottom for the readout
        span = 250

        for i, ring in enumerate(self._rings):
            radius = base - i * (thickness + 4)
            if radius < thickness:
                break
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_c(self._pal["track"], 220), thickness,
                          Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, int(-start * 16), -int(span * 16))
            frac = ring["frac"]
            if frac > 0.002:
                pen_w = thickness * (1.12 if self._hover else 1.0)
                p.setPen(QPen(_c(self._pal["accent"], 235), pen_w,
                              Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, int(-start * 16), -int(span * frac * 16))

        # centre readout
        p.setPen(_c(self._pal["ink"]))
        f = p.font()
        f.setPointSizeF(max(11.0, base * 0.28))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(cx - base, cy - base * 0.32, base * 2, base * 0.50),
                   Qt.AlignCenter, getattr(self, "_center", ""))

        if self._subtitle:
            f.setPointSizeF(max(7.0, base * 0.115))
            f.setBold(False)
            p.setFont(f)
            p.setPen(_c(self._pal["sub"]))
            p.drawText(QRectF(cx - base, cy + base * 0.18, base * 2, base * 0.22),
                       Qt.AlignCenter, self._subtitle)

        # metric legend, in a reserved strip below the rings
        f.setPointSizeF(max(6.5, base * 0.10))
        p.setFont(f)
        for i, ring in enumerate(self._rings):
            row_y = h - legend_h * len(self._rings) + i * legend_h
            p.setPen(_c(self._pal["accent"], 210))
            p.drawText(QRectF(6, row_y, w - 12, legend_h),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       f"{ring['label']} {ring['fmt'] % ring['value']}")
        p.end()


class ToggleDot(Tintable, QWidget):
    """Circular toggle. Ink when off, filled accent ring when on."""

    clicked = Signal()

    def __init__(self, icon_name: str, label: str = "", parent=None):
        super().__init__(parent)
        self._pal = dict(PALETTE)
        self.icon_name = icon_name
        self.label = label
        self._on = False
        self._busy = False
        self._enabled_ctrl = True
        self._reason = ""
        self._hover = False
        self._press = False
        self._error_until = 0.0
        self.tip = label
        # Circle plus a caption strip underneath. Defaults match the rail's
        # 4-column grid; center.py sizes them for its own layout.
        self.setFixedSize(40, 52)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(label)
        self.setAccessibleDescription("Toggle. Press Space or Enter.")
        # The error ring is time-based, so it needs its own repaint: without
        # this the red ring only cleared on the next *state* change, and a
        # failed toggle changes no state — so it stayed up indefinitely.
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self.update)

    # -- state ----------------------------------------------------------
    def set_on(self, on: bool) -> None:
        on = bool(on)
        if on != self._on:
            self._on = on
            self.update()

    def is_on(self) -> bool:
        return self._on

    def set_busy(self, busy: bool) -> None:
        if busy != self._busy:
            self._busy = busy
            self.update()

    def set_control_enabled(self, ok: bool, reason: str = "") -> None:
        """Unavailable controls stay visible but inert, with the reason."""
        if ok == self._enabled_ctrl and reason == self._reason:
            return
        self._enabled_ctrl = ok
        self._reason = reason
        self.setCursor(Qt.PointingHandCursor if ok else Qt.ArrowCursor)
        name = getattr(self, "tip", "") or self.label
        self.setToolTip(f"{name}\n\n{reason}" if (reason and not ok) else name)
        self.update()

    def flash_error(self) -> None:
        self._error_until = time.monotonic() + 1.2
        self._flash.start(1300)   # repaint once the ring has expired
        self.update()

    # -- interaction ----------------------------------------------------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._enabled_ctrl:
            self._press = True
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._press:
            self._press = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self._press = False
        self.update()

    # -- paint ----------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        d = min(w, self.height() - 16)   # the square part, above the caption
        c = QPointF(d / 2, d / 2)
        r = d / 2 - 3

        bg = _c(self._pal.get("bg", "#151519"),
                235 if self._enabled_ctrl else 130)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawEllipse(c, r, r)

        error = self._error_until > time.monotonic()
        if error:
            ring = colorsmod.ERROR
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ring, 2.4))
            p.drawEllipse(c, r, r)
        elif self._on:
            ring = _c(self._pal["accent"])
            p.setBrush(_c(self._pal["accent"], 55))
            p.setPen(QPen(ring, 2.2))
            p.drawEllipse(c, r - 1, r - 1)
        elif self._hover and self._enabled_ctrl:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_c(self._pal["ink"], 90), 1.4))
            p.drawEllipse(c, r, r)

        ink = _c(self._pal["ink"],
                 (255 if (self._on or self._hover) else 110)
                 if self._enabled_ctrl else 40)
        from . import icons as iconsmod
        pm = iconsmod.pixmap(self.icon_name, 22, ink.name())
        if pm is not None:
            p.drawPixmap(int(c.x() - pm.width() / 2),
                         int(c.y() - pm.height() / 2), pm)

        if self.label:
            f = p.font()
            f.setPointSizeF(6.8)
            p.setFont(f)
            p.setPen(_c(self._pal["sub"] if self._enabled_ctrl
                        else self._pal["off"]))
            # Elide rather than bleed into the neighbouring dot.
            fm = p.fontMetrics()
            text = fm.elidedText(self.label, Qt.ElideRight, w - 3)
            p.drawText(QRectF(0, d + 1, w, 14), Qt.AlignCenter, text)
        p.end()