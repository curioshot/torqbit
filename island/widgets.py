"""Opaque painted widgets for the control centre.

Everything here is drawn with QPainter with fully solid fills — no alpha
translucency, no glass. Tracks, knobs, rings and dots all have visible
borders and high-contrast fills so they read on any wallpaper.

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

# Default opaque palette; themes.apply_theme() overwrites these per theme.
PALETTE = {
    "ink": "#f2efe8",
    "sub": "#a8a49d",
    "muted": "#6f6c68",
    "track": "#2a2a31",
    "accent": "#59d98c",
    "warn": "#c9a227",
    "off": "#55555c",
    "bg": "#151519",
    "pane": "#151519",
    "btn": "#1f1f24",
    "btn_border": "#34343c",
}


def _c(value, alpha=None) -> QColor:
    col = QColor(value)
    if not col.isValid():
        col = QColor(PALETTE["ink"])
    # Opaque UI: ignore any requested translucency.
    col.setAlpha(255)
    return col


# Opaque slider geometry, in logical pixels.
SLIDER_TRACK_W = 8.0      # solid visible bar
SLIDER_GRAB_W = 32.0      # invisible but easy to hit
SLIDER_KNOB_R = 10.0      # solid knob
SLIDER_ICON_ALPHA = 255
SLIDER_ICON_PX = 16


class TintableMixin:
    """Mixin: remembers theme colours so a theme change repaints."""

    def apply_palette(self, palette: dict) -> None:
        self._pal = dict(PALETTE)
        self._pal.update({k: v for k, v in palette.items() if isinstance(v, str)})
        self._pal.setdefault("ink", "#f2efe8")
        self._pal.setdefault("track", "#2a2a31")
        self._pal.setdefault("accent", "#59d98c")
        self._pal.setdefault("off", "#55555c")
        self._pal.setdefault("bg", "#151519")
        try:
            self.update()
        except Exception:
            pass


# Backwards-compat: old imports expect `Tintable`.
Tintable = TintableMixin


class VerticalSlider(TintableMixin, QWidget):
    """Drag-to-set vertical bar: solid track, solid fill, solid knob."""

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
        self.setFixedWidth(48)
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(label or icon_name)
        self.setAccessibleDescription(
            "Drag vertically, or use the arrow keys, to change this value")
        self.setAutoFillBackground(False)
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
        cap = 18 if self._caption else 8
        top = SLIDER_ICON_PX + 10
        bot = h - cap - 8
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

        track_col = _c(self._pal["track"])
        accent = _c(self._pal["accent"] if self._enabled_ctrl
                    else self._pal["off"])
        bg = _c(self._pal.get("bg", "#151519"))

        # card behind the slider so it reads as one solid control
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 10, 10)

        # the track: solid rounded bar with an accent fill below the value
        p.setBrush(track_col)
        p.drawRoundedRect(QRectF(cx, top, SLIDER_TRACK_W, height),
                          SLIDER_TRACK_W / 2, SLIDER_TRACK_W / 2)

        # filled portion: solid accent from the bottom up to the value
        fill_h = height * max(0.0, min(1.0, self._shown))
        if fill_h > 1:
            p.setBrush(accent if self._enabled_ctrl else _c(self._pal["off"]))
            p.drawRoundedRect(
                QRectF(cx, top + height - fill_h, SLIDER_TRACK_W, fill_h),
                SLIDER_TRACK_W / 2, SLIDER_TRACK_W / 2)

        # hover: solid outline around the grab area
        if self._hover and self._enabled_ctrl:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(accent, 1.5))
            p.drawRoundedRect(
                QRectF(cx - SLIDER_GRAB_W / 2, top - 2, SLIDER_GRAB_W, height + 4),
                8, 8)

        # the knob — solid white disc with accent ring
        ky = top + height - height * self._shown
        kr = SLIDER_KNOB_R + (1.5 if (self._hover and self._enabled_ctrl) else 0)
        p.setBrush(QColor("#ffffff") if self._enabled_ctrl else _c(self._pal["off"]))
        p.setPen(QPen(accent, 2.5))
        p.drawEllipse(QPointF(cx + SLIDER_TRACK_W / 2, ky), kr, kr)
        # centre dot so the value point is unambiguous
        p.setBrush(accent)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx + SLIDER_TRACK_W / 2, ky), 3.2, 3.2)

        # icon above, dimmed when the hardware is missing
        from . import icons as iconsmod
        pm = iconsmod.pixmap(self.icon_name, SLIDER_ICON_PX, self._pal["ink"])
        if pm is not None:
            if not self._enabled_ctrl:
                p.setOpacity(0.35)
            p.drawPixmap(int((w - pm.width()) / 2), 4, pm)
            p.setOpacity(1.0)

        # caption
        if self._caption:
            p.setPen(_c(self._pal["ink"] if self._enabled_ctrl
                        else self._pal["off"]))
            f = p.font()
            f.setPointSizeF(7.5)
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            p.drawText(QRectF(0, h - 17, w, 15), Qt.AlignCenter,
                       fm.elidedText(self._caption, Qt.ElideRight, w - 2))
        # keyboard focus: visible solid outline
        if self.hasFocus() and self._enabled_ctrl:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(accent, 1.5))
            p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 10, 10)
        p.end()


class RingGauge(TintableMixin, QWidget):
    """Concentric arcs for several metrics, with a numeric readout in the middle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pal = dict(PALETTE)
        self._rings: list[dict] = []
        self._enabled_ctrl = True
        self._hover = False
        self._subtitle = ""
        self._center = ""
        self.setMinimumSize(190, 190)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)

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
        cx, cy = w / 2, (h - 14) / 2

        legend_h = 14 if self._rings else 0
        usable_h = max(40.0, h - legend_h - 12)
        base = min(w / 2 - 12, usable_h / 2 - 12)
        thickness = max(8.0, base * 0.11)

        # solid card behind the gauge
        p.setPen(Qt.NoPen)
        p.setBrush(_c(self._pal.get("bg", "#151519")))
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 12, 12)

        # solid disc the rings sit on, so thin arcs read on any wallpaper
        p.setBrush(_c(self._pal.get("pane", "#151519")))
        p.drawEllipse(QPointF(cx, cy), base + thickness * 0.5,
                      base + thickness * 0.5)

        start = 145  # degrees: leave a gap at the bottom for the readout
        span = 250
        ring_colors = [_c(self._pal["accent"]),
                       _c(self._pal.get("warn", "#c9a227")),
                       _c("#38bdf8")]

        for i, ring in enumerate(self._rings):
            radius = base - i * (thickness + 5)
            if radius < thickness:
                break
            rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_c(self._pal["track"]), thickness,
                          Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, int(-start * 16), -int(span * 16))
            frac = ring["frac"]
            if frac > 0.002:
                rc = ring_colors[i % len(ring_colors)]
                pen_w = thickness * (1.1 if self._hover else 1.0)
                p.setPen(QPen(rc, pen_w, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, int(-start * 16), -int(span * frac * 16))

        # centre readout
        p.setPen(_c(self._pal["ink"]))
        f = p.font()
        f.setPointSizeF(max(12.0, base * 0.28))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(cx - base, cy - base * 0.32, base * 2, base * 0.50),
                   Qt.AlignCenter, getattr(self, "_center", ""))

        if self._subtitle:
            f.setPointSizeF(max(7.5, base * 0.115))
            f.setBold(False)
            p.setFont(f)
            p.setPen(_c(self._pal["sub"]))
            p.drawText(QRectF(cx - base, cy + base * 0.18, base * 2, base * 0.22),
                       Qt.AlignCenter, self._subtitle)

        # metric legend, in a reserved strip below the rings
        f.setPointSizeF(max(7.0, base * 0.10))
        f.setBold(True)
        p.setFont(f)
        for i, ring in enumerate(self._rings):
            row_y = h - legend_h * len(self._rings) + i * legend_h - 2
            rc = ring_colors[i % len(ring_colors)]
            p.setPen(rc)
            p.drawText(QRectF(10, row_y, w - 20, legend_h),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       f"{ring['label']} {ring['fmt'] % ring['value']}")
        p.end()


class ToggleDot(TintableMixin, QWidget):
    """Circular toggle. Solid disc, solid ring when on."""

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
        self.setFixedSize(48, 60)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(label)
        self.setAccessibleDescription("Toggle. Press Space or Enter.")
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self.update)
        self.setAutoFillBackground(False)

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

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            if self._enabled_ctrl:
                self.clicked.emit()
                event.accept()
                return
        super().keyPressEvent(event)

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
        d = min(w, self.height() - 18)   # the square part, above the caption
        c = QPointF(w / 2, d / 2 + 1)
        r = d / 2 - 3

        accent = _c(self._pal["accent"])
        btn = _c(self._pal.get("btn", "#1f1f24"))
        border = _c(self._pal.get("btn_border", "#34343c"))

        # solid disc; the icon inverts when the fill goes accent
        if not self._enabled_ctrl:
            p.setBrush(_c(self._pal.get("pane", "#151519")))
            p.setPen(QPen(border, 1.2))
        elif self._on:
            p.setBrush(accent)
            p.setPen(QPen(accent, 1.5))
        elif self._press:
            p.setBrush(_c(self._pal.get("tab_sel", "#2a2a31")))
            p.setPen(QPen(accent, 1.8))
        elif self._hover:
            p.setBrush(btn)
            p.setPen(QPen(accent, 1.5))
        else:
            p.setBrush(btn)
            p.setPen(QPen(border, 1.2))
        p.drawEllipse(c, r, r)

        error = self._error_until > time.monotonic()
        if error:
            ring = colorsmod.ERROR
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ring, 2.5))
            p.drawEllipse(c, r + 1.5, r + 1.5)

        # icon: dark on accent fill, ink otherwise
        if self._on and self._enabled_ctrl:
            ink = QColor("#101014")
        else:
            ink = _c(self._pal["ink"] if (self._on or self._hover)
                     else self._pal["sub"])
            if not self._enabled_ctrl:
                ink = _c(self._pal["off"])
        from . import icons as iconsmod
        pm = iconsmod.pixmap(self.icon_name, 20, ink.name())
        if pm is not None:
            p.drawPixmap(int(c.x() - pm.width() / 2),
                         int(c.y() - pm.height() / 2), pm)

        # keyboard focus ring
        if self.hasFocus() and self._enabled_ctrl:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(accent, 1.5))
            p.drawEllipse(c, r + 3, r + 3)

        if self.label:
            f = p.font()
            f.setPointSizeF(7.0)
            f.setBold(self._on)
            p.setFont(f)
            p.setPen(_c(self._pal["sub"] if self._enabled_ctrl
                        else self._pal["off"]))
            fm = p.fontMetrics()
            text = fm.elidedText(self.label, Qt.ElideRight, w - 3)
            p.drawText(QRectF(0, d + 3, w, 15), Qt.AlignCenter, text)
        p.end()
