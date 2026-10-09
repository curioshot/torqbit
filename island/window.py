"""Always-on-top island / corner widget."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QRegion, QAction, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QMenu, QApplication,
)

from . import config as cfgmod
from . import icons as iconsmod
from . import sensors as sensorsmod
from . import themes as themesmod
from .center import ControlCenter
from .face import FaceView
from .glass import GlassPanel
from .service_tab import ServiceTab
from .tabs import BotTab, CalendarTab, SystemNotesTab, AppearanceTab


COLLAPSED_ISLAND_W, COLLAPSED_ISLAND_H = 252, 42
COLLAPSED_CORNER = 112
EXPANDED_W, EXPANDED_H = 368, 540
CENTRE_GAP = 8          # the visible break between the two containers
CENTRE_MIN_W = 900
CENTRE_W = 1120         # preferred width of the control-centre panel
CENTRE_H = 300          # fixed height; the feed list scrolls inside
CENTRE_MIN_H = 190


def _qt_color(value) -> str:
    """Theme colours are CSS strings like 'rgba(13, 13, 16, 246)'.

    QColor cannot parse that spelling — it rejects it and every painted
    widget then falls back to its (near-white) ink colour. Normalise to hex
    here so the painted widgets always get a colour Qt understands.
    """
    import re
    if not isinstance(value, str):
        return "#000000"
    s = value.strip()
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)"
                 r"(?:\s*,\s*([\d.]+))?\s*\)", s, re.I)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        r, g, b = (max(0, min(255, v)) for v in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"
    return s if s.startswith("#") else "#000000"


class IslandWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = cfgmod.load()
        self.expanded = False
        self.centre_open = False
        self._dragging = False
        self._press_pos = QPoint()
        self._press_global = QPoint()
        self._moved = False
        self._target_geom = None  # enforced end-state for expand/collapse flights
        self._last_click = 0.0    # for click -> card vs double-click -> centre

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # NOTE: intentionally NOT using WA_ShowWithoutActivating so expanded
        # inputs (calendar add, notes) can receive focus.
        self.setAttribute(Qt.WA_X11NetWmWindowTypeDock, False)

        self._build_ui()
        self._place_initial()
        self._raise_timer = QTimer(self)
        self._raise_timer.timeout.connect(self._keep_above)
        # 4s is plenty to beat a fullscreen app; 2s was pure X traffic.
        self._raise_timer.start(4000)

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_count = 0
        self._tick_clock()
        self._apply_mode_visual()
        self.set_theme(self.cfg.get("theme", "black"), save=False)

    # ---------- UI ----------
    def _build_ui(self):
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)

        # collapsed island capsule (glass shell, painted by GlassPanel)
        self.collapsed = GlassPanel(self)
        self.collapsed.setObjectName("collapsed")
        ch = QHBoxLayout(self.collapsed)
        ch.setContentsMargins(6, 3, 12, 3)
        ch.setSpacing(8)
        self.mini_face = FaceView(
            engine=self.cfg.get("face", "blobatar"),
            seed=self.cfg.get("face_name", "island-bot"),
            background=self.cfg.get("face_bg", "none"),
            eye_scale=1.7, lite=True,
            emotion=self.cfg.get("emotion", "02"),
            shape=self.cfg.get("shape", "blob"),
            parent=self.collapsed,
        )
        self.mini_face.setFixedSize(34, 34)
        ch.addWidget(self.mini_face)
        self.mini_time = QLabel("--:--")
        ch.addWidget(self.mini_time)
        self.mini_dot = QLabel()
        self.mini_dot.setFixedSize(10, 10)
        ch.addWidget(self.mini_dot)
        self.mini_temp = QLabel("—")
        self.mini_temp.setToolTip("CPU temperature")
        ch.addWidget(self.mini_temp)
        ch.addStretch(1)
        self.root.addWidget(self.collapsed)

        # expanded card (glass shell, painted by GlassPanel).
        # Top: avatar + time/date/day/temp. Bottom: tab container panel.
        self.card = GlassPanel(self)
        self.card.setObjectName("card")
        cv = QVBoxLayout(self.card)
        cv.setContentsMargins(14, 12, 14, 12)
        cv.setSpacing(8)

        head = QHBoxLayout()
        self.big_face = FaceView(
            engine=self.cfg.get("face", "blobatar"),
            seed=self.cfg.get("face_name", "island-bot"),
            background=self.cfg.get("face_bg", "none"),
            eye_scale=1.15, lite=False,
            emotion=self.cfg.get("emotion", "02"),
            shape=self.cfg.get("shape", "blob"),
            parent=self.card,
        )
        self.big_face.setFixedSize(132, 132)
        head.addWidget(self.big_face)
        txt = QVBoxLayout()
        self.big_time = QLabel("--:--")
        self.big_date = QLabel("")
        self.big_temp = QLabel("")
        self.big_temp.setToolTip("CPU temperature")
        txt.addWidget(self.big_time)
        txt.addWidget(self.big_date)
        txt.addWidget(self.big_temp)
        txt.addStretch(1)
        head.addLayout(txt, 1)
        self.collapse_btn = QPushButton("–")
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.setToolTip("Collapse (click island to expand)")
        self.collapse_btn.clicked.connect(self.collapse)
        head.addWidget(self.collapse_btn, 0, Qt.AlignTop)
        cv.addLayout(head)

        self.tabs = QTabWidget()
        self.bot_tab = BotTab(self.set_emotion, self.set_shape,
                              self.set_face, self.set_seed)
        self.bot_tab.set_shape(self.cfg.get("shape", "blob"))
        self.bot_tab.set_face(self.cfg.get("face", "blobatar"))
        self.bot_tab.set_seed(self.cfg.get("face_name", "island-bot"))
        self.cal_tab = CalendarTab()
        self.sys_tab = SystemNotesTab()
        self.appear_tab = AppearanceTab(self.set_theme, self.set_face_bg)
        self.appear_tab.set_theme(self.cfg.get("theme", "black"))
        self.appear_tab.set_bg(self.cfg.get("face_bg", "none"))
        self.tabs.addTab(self.bot_tab, "Bot / Time")
        self.tabs.addTab(self.cal_tab, "Calendar")
        self.tabs.addTab(self.sys_tab, "System / Notes")
        self.tabs.addTab(self.appear_tab, "Appearance")
        self.svc_tab = ServiceTab()
        self.tabs.addTab(self.svc_tab, "Service")
        # bottom container: the menus live in their own glass panel
        self.content = GlassPanel(self.card)
        self.content.setObjectName("content")
        cv_content = QVBoxLayout(self.content)
        cv_content.setContentsMargins(10, 10, 10, 10)
        cv_content.addWidget(self.tabs)
        cv.addWidget(self.content, 1)

        self.hint = QLabel("Click: island · Double-click: control centre · "
                   "Right-click: more · Drag to move")
        self.hint.setWordWrap(True)
        cv.addWidget(self.hint)

        self.root.addWidget(self.card)
        # Card sits centred over the (wider) control-centre panel below it.
        self.root.setAlignment(self.card, Qt.AlignHCenter)

        # Control centre — a SECOND, deliberately separate glass panel below
        # the card, split from it by CENTRE_GAP. Opened by double-click.
        self.center = ControlCenter(
            on_config_changed=self._centre_config_changed)
        self.center.themeToggleRequested.connect(self.set_theme)
        self.center.setObjectName("center")
        self.root.addSpacing(CENTRE_GAP)
        self.root.addWidget(self.center)
        self.center.setVisible(False)
        self._centre_size = None

        self.card.setVisible(False)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    # ---------- geometry ----------
    def _screen_geo(self) -> QRect:
        s = QApplication.primaryScreen()
        if s:
            return s.availableGeometry()
        return QRect(0, 0, 1920, 1080)

    def _island_home_rect(self, w: int, h: int) -> QRect:
        """Saved island position, clamped on-screen (top-center fallback)."""
        g = self._screen_geo()
        ix, iy = self.cfg.get("island_x"), self.cfg.get("island_y")
        if isinstance(ix, int) and isinstance(iy, int):
            x = min(max(ix, g.x()), g.x() + g.width() - w)
            y = min(max(iy, g.y()), g.y() + g.height() - h)
        else:
            x = g.x() + (g.width() - w) // 2
            y = g.y() + 8
        return QRect(x, y, w, h)

    def _place_initial(self):
        self.adjustSize()
        if self.cfg.get("mode") == "corner":
            self._move_to_corner()
        else:
            self.setGeometry(self._island_home_rect(
                COLLAPSED_ISLAND_W, COLLAPSED_ISLAND_H))

    def _move_to_corner(self):
        g = self._screen_geo()
        m = int(self.cfg.get("corner_margin", 0) or 0)
        c = self.cfg.get("corner", "top-right")
        w = COLLAPSED_CORNER if not self.expanded else EXPANDED_W
        h = COLLAPSED_CORNER if not self.expanded else EXPANDED_H
        if c == "top-left":
            x, y = g.x() + m, g.y() + m
        elif c == "top-right":
            x, y = g.x() + g.width() - w - m, g.y() + m
        elif c == "bottom-left":
            x, y = g.x() + m, g.y() + g.height() - h - m
        else:
            x, y = g.x() + g.width() - w - m, g.y() + g.height() - h - m
        self.setGeometry(x, y, w, h)

    def _apply_mode_visual(self):
        is_corner = self.cfg.get("mode") == "corner"
        if not self.expanded and is_corner:
            self.collapsed.setVisible(False)
            self.setFixedSize(COLLAPSED_CORNER, COLLAPSED_CORNER)
            self._move_to_corner()
            self._update_mask()
        else:
            self.clearMask()
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.collapsed.setVisible(not self.expanded)
            self.card.setVisible(self.expanded)
            if self.expanded:
                self.card.setFixedSize(EXPANDED_W, self.card.sizeHint().height()
                                       or EXPANDED_H)
                if is_corner:
                    self._move_to_corner()
            else:
                self.card.setFixedWidth(EXPANDED_W)
                self.setFixedSize(COLLAPSED_ISLAND_W, COLLAPSED_ISLAND_H)
        # The control centre only exists in card mode.
        self.center.setVisible(bool(self.expanded and self.centre_open))
        if not self.centre_open:
            self.center.hide()
        else:
            w, h = self._centre_geometry()
            self.setFixedSize(w, h)
        # Enforce animation end-state: layout fights during the flight can
        # leave a wrong size; the recorded target always wins.
        if self._target_geom is not None:
            try:
                self.setGeometry(self._target_geom)
            except Exception:
                pass
            self._target_geom = None
        self.update()

    def _update_mask(self):
        # quarter-circle input mask for corner collapsed mode
        w, h = COLLAPSED_CORNER, COLLAPSED_CORNER
        r = min(w, h)
        c = self.cfg.get("corner", "top-right")
        if c == "top-left":
            cx, cy = 0, 0
        elif c == "top-right":
            cx, cy = w, 0
        elif c == "bottom-left":
            cx, cy = 0, h
        else:
            cx, cy = w, h
        big = QRegion(cx - r, cy - r, 2 * r, 2 * r, QRegion.Ellipse)
        full = QRegion(0, 0, w, h)
        self.setMask(big.intersected(full))

    # ---------- paint (corner quarter) ----------
    def paintEvent(self, event):  # noqa: N802
        if self.expanded or self.cfg.get("mode") != "corner":
            return super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.cfg.get("corner", "top-right")
        w, h = self.width(), self.height()
        # quarter pie centered on the screen corner
        p.setBrush(QColor(12, 12, 15, 235))
        p.setPen(QPen(QColor("#2b2b31"), 1.5))
        if c == "top-left":
            p.drawPie(-w, -h, 2 * w, 2 * h, 270 * 16, 90 * 16)
        elif c == "top-right":
            p.drawPie(0, -h, 2 * w, 2 * h, 180 * 16, 90 * 16)
        elif c == "bottom-left":
            p.drawPie(-w, 0, 2 * w, 2 * h, 0 * 16, 90 * 16)
        else:
            p.drawPie(0, 0, 2 * w, 2 * h, 90 * 16, 90 * 16)
        p.setPen(QColor("#f2efe8"))
        p.drawText(QRect(0, 0, w, h), Qt.AlignCenter, datetime.now().strftime("%H:%M"))

    # ---------- expand / collapse (click) ----------
    def expand(self):
        if self.expanded:
            return
        self.expanded = True
        self.set_emotion("01")  # waking blip, engine auto-advances to idle
        QTimer.singleShot(900, lambda: self.set_emotion("10") if self.expanded else None)
        self._animate_to(EXPANDED_W, EXPANDED_H, anchor_corner=(self.cfg.get("mode") == "corner"))

    def collapse(self):
        was_centre = self.centre_open
        if was_centre:
            self.close_centre()
            return
        if not self.expanded:
            return
        self.expanded = False
        self.set_emotion("41")
        if self.cfg.get("mode") == "corner":
            self._animate_to(COLLAPSED_CORNER, COLLAPSED_CORNER, anchor_corner=True)
        else:
            # fly back to the saved island home, not wherever we are
            home = self._island_home_rect(COLLAPSED_ISLAND_W, COLLAPSED_ISLAND_H)
            self._animate_to_rect(home)

    def toggle(self):
        self.collapse() if self.expanded else self.expand()

    # ---------- control centre (double click) ----------
    def _centre_geometry(self) -> tuple[int, int]:
        """Window size for card + gap + centre panel.

        The centre panel has a FIXED height so the layout can never squeeze
        the card and pull the two containers into each other; the feed list
        scrolls instead. On a short screen the panel shrinks to its minimum
        before anything is allowed to overlap.
        """
        g = self._screen_geo()
        avail_h = max(240, g.height() - 24)
        card_h = self.card.sizeHint().height() or EXPANDED_H
        panel_h = CENTRE_H
        if card_h + CENTRE_GAP + panel_h > avail_h:
            panel_h = max(CENTRE_MIN_H, avail_h - card_h - CENTRE_GAP)
        h = card_h + CENTRE_GAP + panel_h
        w = min(CENTRE_W, max(CENTRE_MIN_W, g.width() - 24))
        if self._centre_size != (w, panel_h):
            self._centre_size = (w, panel_h)
            self.center.setFixedSize(w, panel_h)
        return w, h

    def open_centre(self):
        """Second panel, below the card with a visible gap."""
        if not self.cfg.get("centre", {}).get("enabled", True):
            self.hint.setText(
                "Control centre is switched off in config.json "
                "(centre.enabled)")
            return
        if not self.expanded:
            self.expand()
        if self.centre_open:
            return
        self.centre_open = True
        w, h = self._centre_geometry()
        self.center.show()
        self.center.sync_config(self.cfg)
        x, y = self._centre_origin(w, h)
        self._animate_to_rect(QRect(x, y, w, h))
        self.set_emotion("35")

    def close_centre(self):
        if not self.centre_open:
            return
        self.centre_open = False
        self.center.hide()
        self.card.setFixedWidth(EXPANDED_W)
        self._animate_to(EXPANDED_W, EXPANDED_H,
                         anchor_corner=(self.cfg.get("mode") == "corner"))

    def _centre_origin(self, w: int, h: int) -> tuple[int, int]:
        """Keep the wider panel on screen, biased to the current position."""
        g = self._screen_geo()
        cur = self.geometry()
        x = min(max(cur.x(), g.x()), g.x() + max(0, g.width() - w))
        y = min(max(cur.y(), g.y()), g.y() + max(0, g.height() - h))
        return x, y

    def _centre_config_changed(self):
        self.cfg = cfgmod.load()

    def _animate_to_rect(self, rect: QRect):
        cur = self.geometry()
        # Stop any in-flight animation so two flights never fight.
        try:
            if getattr(self, "_anim", None) is not None and self._anim.state():
                self._anim.stop()
        except Exception:
            pass
        # Release fixed-size clamps so the flight can interpolate freely.
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self._target_geom = QRect(rect)
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setStartValue(cur)
        self._anim.setEndValue(QRect(rect))
        self._anim.finished.connect(self._apply_mode_visual)
        QTimer.singleShot(400, self._apply_mode_visual)
        # Collapse: hide the card upfront so its layout can't re-grow
        # the window mid-flight; the capsule stretches then shrinks.
        self.card.setVisible(False)
        self.collapsed.setVisible(True)
        self._anim.start()

    def _animate_to(self, w: int, h: int, anchor_corner: bool):
        cur = self.geometry()
        x, y = cur.x(), cur.y()
        if not anchor_corner:
            # keep top-center-ish: grow downward, keep horizontal center
            x = cur.x() + (cur.width() - w) // 2
            if self.cfg.get("mode") == "island" and not self.expanded:
                pass
        else:
            g = self._screen_geo()
            m = int(self.cfg.get("corner_margin", 0) or 0)
            c = self.cfg.get("corner", "top-right")
            if c == "top-left":
                x, y = g.x() + m, g.y() + m
            elif c == "top-right":
                x, y = g.x() + g.width() - w - m, g.y() + m
            elif c == "bottom-left":
                x, y = g.x() + m, g.y() + g.height() - h - m
            else:
                x, y = g.x() + g.width() - w - m, g.y() + g.height() - h - m
        # Stop any in-flight animation so two flights never fight.
        try:
            if getattr(self, "_anim", None) is not None and self._anim.state():
                self._anim.stop()
        except Exception:
            pass
        # Release fixed-size clamps so the flight can interpolate freely.
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self._target_geom = QRect(x, y, w, h)
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setStartValue(cur)
        self._anim.setEndValue(QRect(x, y, w, h))
        self._anim.finished.connect(self._apply_mode_visual)
        # Safety: if the animation never finishes (e.g. offscreen/platform
        # quirk), still settle on the target visuals.
        QTimer.singleShot(400, self._apply_mode_visual)
        # show target widgets upfront for smooth growth
        if self.expanded:
            self.collapsed.setVisible(False)
            self.card.setVisible(True)
            self.clearMask()
        else:
            # Collapse: hide the card upfront so its layout can't re-grow
            # the window mid-flight; the capsule stretches then shrinks.
            self.card.setVisible(False)
            self.collapsed.setVisible(True)
        self._anim.start()

    # ---------- mouse: drag to move, click to expand ----------
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._press_global = event.globalPos()
            self._moved = False
            self._dragging = True

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging and (event.buttons() & Qt.LeftButton):
            if (event.globalPos() - self._press_global).manhattanLength() > 6:
                self._moved = True
            if self._moved:
                if self.cfg.get("mode") == "corner" and not self.expanded:
                    return  # corner collapsed stays pinned; move via corner picker
                self.move(event.globalPos() - self._press_pos)
                # gaze follows cursor while dragging over island
                try:
                    local = self.mapFromGlobal(QCursor.pos())
                    nx = (local.x() / max(self.width(), 1)) * 2 - 1
                    ny = (local.y() / max(self.height(), 1)) * 2 - 1
                    self.mini_face.setGaze(nx, ny)
                    self.big_face.setGaze(nx, ny)
                except Exception:
                    pass

    def mouseReleaseEvent(self, event):  # noqa: N802
        was_drag = self._moved
        self._dragging = False
        if event.button() == Qt.LeftButton and not was_drag:
            # Click -> card, and a second click inside the double-click
            # interval escalates to the control centre. Both clicks are
            # consumed by this branch, so there is no toggle-fighting and
            # no artificial delay before the island opens.
            now = time.monotonic()
            interval = QApplication.doubleClickInterval() / 1000.0
            if now - self._last_click < interval:
                self._last_click = 0.0
                self.open_centre()
            else:
                self._last_click = now
                self.toggle()
        elif was_drag and self.cfg.get("mode") == "island" and not self.expanded:
            g = self.geometry()
            self.cfg["island_x"], self.cfg["island_y"] = g.x(), g.y()
            cfgmod.save(self.cfg)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.collapse()
            return
        super().keyPressEvent(event)

    # ---------- timers ----------
    def _tick_clock(self):
        now = datetime.now()
        s = now.strftime("%H:%M")
        self.mini_time.setText(s)
        self.big_time.setText(s)
        self.big_date.setText(now.strftime("%A  %Y-%m-%d"))
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        if self._tick_count == 1 or self._tick_count % 3 == 0:
            t = sensorsmod.get_cpu_temp()
            self.mini_temp.setText(sensorsmod.format_temp(t, short=True))
            self.big_temp.setText(f"CPU {sensorsmod.format_temp(t)}")
        if self.cfg.get("mode") == "corner" and not self.expanded:
            self.update()  # repaint quarter time

    def _keep_above(self):
        try:
            if not self.isVisible():
                self.show()
            # raise_() restacks without activating another app
            self.raise_()
        except Exception:
            pass

    # ---------- bot bridge ----------
    def set_emotion(self, eid: str):
        self.cfg["emotion"] = eid
        cfgmod.save(self.cfg)
        try:
            self.mini_face.setEmotion(eid)
        except Exception:
            pass
        try:
            self.big_face.setEmotion(eid)
        except Exception:
            pass
        if eid == "33":
            try:
                self.big_face.burst(24)
            except Exception:
                pass

    def set_shape(self, shape: str):
        if shape not in ("blob", "wedge", "gem"):
            return
        self.cfg["shape"] = shape
        cfgmod.save(self.cfg)
        try:
            self.mini_face.setShape(shape)
            self.big_face.setShape(shape)
        except Exception:
            pass
        self.bot_tab.set_shape(shape)

    # ---------- face picker ----------
    def set_face(self, engine: str):
        from .face import ENGINES
        if engine not in ENGINES:
            return
        self.cfg["face"] = engine
        cfgmod.save(self.cfg)
        try:
            self.mini_face.setEngine(engine)
            self.big_face.setEngine(engine)
        except Exception:
            pass
        # re-assert seed/expression on the fresh engine
        try:
            self.mini_face.setSeed(self.cfg.get("face_name", "island-bot"))
            self.big_face.setSeed(self.cfg.get("face_name", "island-bot"))
            self.mini_face.setEmotion(self.cfg.get("emotion", "02"))
            self.big_face.setEmotion(self.cfg.get("emotion", "02"))
        except Exception:
            pass
        self.bot_tab.set_face(engine)

    def set_seed(self, seed: str):
        if seed == iconsmod.SHUFFLE_SENTINEL:
            try:
                s1 = self.mini_face.shuffleSeed()
                self.big_face.setSeed(s1)
                seed = s1
            except Exception:
                return
        seed = (seed or "").strip() or "island-bot"
        self.cfg["face_name"] = seed
        cfgmod.save(self.cfg)
        try:
            self.mini_face.setSeed(seed)
            self.big_face.setSeed(seed)
        except Exception:
            pass
        self.bot_tab.set_seed(seed)

    def set_face_bg(self, bg: str):
        if bg not in ("none", "squircle", "circle", "square"):
            return
        self.cfg["face_bg"] = bg
        cfgmod.save(self.cfg)
        try:
            self.mini_face.setBackground(bg)
            self.big_face.setBackground(bg)
        except Exception:
            pass
        try:
            self.appear_tab.set_bg(bg)
        except Exception:
            pass

    def set_theme(self, name: str, save: bool = True):
        name = themesmod.apply_theme(self, name)
        self.cfg["theme"] = name
        if save:
            cfgmod.save(self.cfg)
        try:
            self.appear_tab.set_theme(name)
        except Exception:
            pass
        try:
            self.center._theme = name
            self.center.apply_palette(self._centre_palette())
        except Exception:
            pass

    def _centre_palette(self) -> dict:
        """Map the active theme onto the palette the painted widgets want."""
        t = themesmod._resolve(self.cfg.get("theme", "black"))
        return {
            "ink": _qt_color(t.get("text", "#f2efe8")),
            "sub": _qt_color(t.get("subtext", "#a8a49d")),
            "muted": _qt_color(t.get("muted", "#6f6c68")),
            "text": _qt_color(t.get("text", "#f2efe8")),
            "accent": _qt_color(t.get("accent", "#59d98c")),
            "track": _qt_color(t.get("tab", "#17171b")),
            "bg": _qt_color(t.get("card_bg", "#0d0d10")),
            "pane": _qt_color(t.get("pane", "#101013")),
            "btn": _qt_color(t.get("btn", "#1d1d22")),
            "btn_border": _qt_color(t.get("btn_border", "#2c2c33")),
            "off": "#55555c",
        }

    # ---------- menu ----------
    def _menu(self, pos):
        m = QMenu(self)
        m.setStyleSheet("QMenu { background:#151518; color:#eee; border:1px solid #2c2c33; }"
                        "QMenu::item:selected { background:#2a2a32; }")

        mode_m = m.addMenu("Design")
        for label, val in (("Island capsule", "island"), ("Corner ¼ circle", "corner")):
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(self.cfg.get("mode") == val)
            a.triggered.connect(lambda _=False, v=val: self._set_mode(v))
            mode_m.addAction(a)

        corner_m = m.addMenu("Corner")
        for val in ("top-left", "top-right", "bottom-left", "bottom-right"):
            a = QAction(val, self)
            a.setCheckable(True)
            a.setChecked(self.cfg.get("corner") == val)
            a.triggered.connect(lambda _=False, v=val: self._set_corner(v))
            corner_m.addAction(a)

        shape_m = m.addMenu("Bot shape (aora)")
        for val in ("blob", "wedge", "gem"):
            a = QAction(val, self)
            a.setCheckable(True)
            a.setChecked(self.cfg.get("shape") == val)
            a.triggered.connect(lambda _=False, v=val: self.set_shape(v))
            shape_m.addAction(a)

        face_m = m.addMenu("Face")
        for label, val in (("Blobatar creature", "blobatar"),
                           ("EmotionBall (aora)", "aora"),
                           ("Simple eyes", "simple")):
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(self.cfg.get("face") == val)
            a.triggered.connect(lambda _=False, v=val: self.set_face(v))
            face_m.addAction(a)
        face_m.addSeparator()
        rnd = QAction("Surprise me (random creature)", self)
        rnd.setIcon(iconsmod.icon("dice", 16))
        rnd.triggered.connect(lambda: self.set_seed(iconsmod.SHUFFLE_SENTINEL))
        face_m.addAction(rnd)
        bg_m = face_m.addMenu("Backdrop (blobatar)")
        for val in ("none", "squircle", "circle", "square"):
            a = QAction(val, self)
            a.setCheckable(True)
            a.setChecked(self.cfg.get("face_bg") == val)
            a.triggered.connect(lambda _=False, v=val: self.set_face_bg(v))
            bg_m.addAction(a)

        theme_m = m.addMenu("Theme")
        for key, label, _desc in themesmod.available():
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(self.cfg.get("theme") == key)
            a.triggered.connect(lambda _=False, v=key: self.set_theme(v))
            theme_m.addAction(a)

        emo_m = m.addMenu("Emotion")
        for eid, name in (("02", "Idle"), ("10", "Happy"), ("30", "Thinking"),
                          ("32", "Busy"), ("33", "Done"), ("00", "Sleep")):
            a = QAction(f"{name} ({eid})", self)
            a.triggered.connect(lambda _=False, e=eid: self.set_emotion(e))
            emo_m.addAction(a)

        m.addSeparator()
        centre_a = QAction("Control centre", self)
        centre_a.setCheckable(True)
        centre_a.setChecked(self.centre_open)
        centre_a.setShortcut("Ctrl+Space")
        centre_a.triggered.connect(
            lambda: self.close_centre() if self.centre_open else self.open_centre())
        m.addAction(centre_a)
        top = QAction("Snap to top-center", self)
        top.triggered.connect(self._snap_top)
        m.addAction(top)
        quit_a = QAction("Quit", self)
        quit_a.triggered.connect(QApplication.instance().quit)
        m.addAction(quit_a)
        m.exec(self.mapToGlobal(pos))

    def _set_mode(self, mode: str):
        self.cfg["mode"] = mode
        cfgmod.save(self.cfg)
        if self.expanded:
            self.collapse()
            QTimer.singleShot(250, self._apply_mode_visual)
        else:
            self._place_initial() if mode == "island" else self._move_to_corner()
            self._apply_mode_visual()

    def _set_corner(self, corner: str):
        self.cfg["corner"] = corner
        cfgmod.save(self.cfg)
        if self.cfg.get("mode") == "corner":
            self._move_to_corner()
            self._apply_mode_visual()

    def _snap_top(self):
        g = self._screen_geo()
        x = g.x() + (g.width() - COLLAPSED_ISLAND_W) // 2
        self.cfg["mode"] = "island"
        self.cfg["island_x"], self.cfg["island_y"] = x, g.y() + 8
        cfgmod.save(self.cfg)
        if self.expanded:
            self.collapse()
        self.setGeometry(x, g.y() + 8, COLLAPSED_ISLAND_W, COLLAPSED_ISLAND_H)
        self._apply_mode_visual()

    def closeEvent(self, event):  # noqa: N802
        if self.cfg.get("mode") == "island" and not self.expanded:
            g = self.geometry()
            self.cfg["island_x"], self.cfg["island_y"] = g.x(), g.y()
        cfgmod.save(self.cfg)
        super().closeEvent(event)
