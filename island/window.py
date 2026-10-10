"""Always-on-top island / corner widget."""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import (Qt, QTimer, QPoint, QRect, QPropertyAnimation,
                            QEasingCurve, QEvent)
from PySide6.QtGui import QPainter, QColor, QPen, QRegion, QAction, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QMenu, QApplication,
)

from . import config as cfgmod
from . import colors as colorsmod
from . import icons as iconsmod
from . import sensors as sensorsmod
from . import themes as themesmod
from .center import ControlCenter, Rail
from .face import FaceView
from .geom import (COLLAPSED_CORNER, COLLAPSED_ISLAND_H, COLLAPSED_ISLAND_W,
                   CENTRE_GAP, CENTRE_H, CENTRE_MIN_H, CENTRE_MIN_W, CENTRE_W,
                   EXPANDED_H, EXPANDED_MAX_H, EXPANDED_W, ISLAND_TOP_INSET)
from .glass import GlassPanel
from .service_tab import ServiceTab
from .tabs import BotTab, CalendarTab, SystemNotesTab, AppearanceTab

__all__ = ["IslandWindow", "COLLAPSED_ISLAND_W", "COLLAPSED_ISLAND_H",
           "COLLAPSED_CORNER", "EXPANDED_W", "EXPANDED_H", "CENTRE_GAP",
           "CENTRE_MIN_W", "CENTRE_W", "CENTRE_H", "CENTRE_MIN_H"]

# Geometry flight duration. Two animation helpers used to each hardcode 200,
# with a 400ms "safety" timer at double that.
ANIM_MS = 200
ANIM_SETTLE_MS = ANIM_MS * 2
# Waking -> idle mood change after the expand flight.
WAKE_SETTLE_MS = 900
# The face inside a pill, in both the collapsed capsule and the card header.
PILL_FACE = 40


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
        # One face widget, re-parented between the collapsed pill and the
        # expanded card's header. They are never on screen at the same
        # time, and a second QWebEngineView costs a browser process.
        self.pill_face = FaceView(
            engine=self.cfg.get("face", "blobatar"),
            seed=self.cfg.get("face_name", "island-bot"),
            background=self.cfg.get("face_bg", "none"),
            eye_scale=1.7, lite=True,
            emotion=self.cfg.get("emotion", "02"),
            shape=self.cfg.get("shape", "blob"),
            parent=self.collapsed,
        )
        self.pill_face.setFixedSize(PILL_FACE, PILL_FACE)
        ch.addWidget(self.pill_face)
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

        # expanded card (frameless shell). Top: a pill row of face, time and
        # status dot. Then the tab strip. Then the tab content.
        self.card = GlassPanel(self)
        self.card.setObjectName("card")
        cv = QVBoxLayout(self.card)
        cv.setContentsMargins(4, 4, 4, 4)
        cv.setSpacing(2)

        # The pill: same three elements as the collapsed capsule, at the
        # card's scale. It used to be a 132px avatar beside a stack of
        # time/date/temperature, which is not what the pill reads as.
        head = QHBoxLayout()
        head.setContentsMargins(8, 6, 8, 6)
        head.setSpacing(10)
        self._pill_slot = QVBoxLayout()
        self._pill_slot.setContentsMargins(0, 0, 0, 0)
        head.addLayout(self._pill_slot)
        self.big_time = QLabel("--:--")
        self.big_time.setAccessibleName("Time")
        head.addWidget(self.big_time)
        self.big_dot = QLabel()
        self.big_dot.setFixedSize(10, 10)
        self.big_dot.setToolTip("Status")
        head.addWidget(self.big_dot)
        self.big_temp = QLabel("—")
        self.big_temp.setToolTip("CPU temperature")
        head.addWidget(self.big_temp)
        head.addStretch(1)
        self.collapse_btn = QPushButton("–")
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.setToolTip("Collapse (click the island to expand)")
        self.collapse_btn.setAccessibleName("Collapse back to the island")
        self.collapse_btn.clicked.connect(self.collapse)
        head.addWidget(self.collapse_btn, 0, Qt.AlignVCenter)
        cv.addLayout(head)

        self.full_btn = QPushButton("⤢")
        self.full_btn.setFixedSize(28, 28)
        self.full_btn.setToolTip("Open the full island (double-click anywhere)")
        self.full_btn.setAccessibleName("Open the full island")
        self.full_btn.clicked.connect(self.open_centre)
        head.addWidget(self.full_btn, 0, Qt.AlignVCenter)

        self.tabs = QTabWidget()
        # A second, larger face for the Bot tab. The card header and the
        # collapsed pill share one (see _move_pill_face); this one is always
        # parented to the Bot tab.
        self.tab_face = FaceView(
            engine=self.cfg.get("face", "blobatar"),
            seed=self.cfg.get("face_name", "island-bot"),
            background=self.cfg.get("face_bg", "none"),
            eye_scale=1.15, lite=False,
            emotion=self.cfg.get("emotion", "02"),
            shape=self.cfg.get("shape", "blob"),
        )
        self.bot_tab = BotTab(self.set_emotion, self.set_shape,
                              self.set_face, self.set_seed,
                              face_view=self.tab_face)
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

        # Double-click anywhere in the card opens the full island. The tab
        # bar and the header consume presses, so the filter has to reach
        # them explicitly.
        self.card.installEventFilter(self)
        self.tabs.tabBar().installEventFilter(self)
        self.tabs.installEventFilter(self)
        self.collapse_btn.installEventFilter(self)
        self.full_btn.installEventFilter(self)
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

        # Control centre — a SECOND, deliberately separate glass panel below
        # the card, split from it by CENTRE_GAP. Opened by double-click.
        self.center = ControlCenter(
            on_config_changed=self._centre_config_changed)
        self.center.themeToggleRequested.connect(self.set_theme)
        self.center.setObjectName("center")

        # One row: the rail on the left, and a stacked area beside it that
        # holds either the expanded card or the full island panel. The rail
        # used to be re-parented between two layouts depending on state,
        # which is why only one of the two could ever be on screen.
        self.main_row = QHBoxLayout()
        self.main_row.setContentsMargins(0, 0, 0, 0)
        self.main_row.setSpacing(CENTRE_GAP)
        self.rail = self.center.rail
        self.rail.setVisible(False)
        self.main_row.addWidget(self.rail)

        self.stack_area = QVBoxLayout()
        self.stack_area.setContentsMargins(0, 0, 0, 0)
        self.stack_area.setSpacing(CENTRE_GAP)
        self.stack_area.addWidget(self.card)
        self.stack_area.addWidget(self.center)
        self.main_row.addLayout(self.stack_area, 1)
        self.root.addLayout(self.main_row)

        self.center.setVisible(False)
        self._centre_size = None

        self.card.setVisible(False)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    # ---------- geometry ----------
    def _move_pill_face(self, expanded: bool) -> None:
        """Put the shared face widget in whichever pill is currently on screen.

        The collapsed pill and the expanded card's header are never visible
        at the same time, so they share one QWebEngineView rather than
        paying for a second browser process. Reparenting preserves the
        loaded page, so this is not a reload.
        """
        if not hasattr(self, "pill_face"):
            return
        slot = getattr(self, "_pill_slot", None)
        if slot is None:
            return
        try:
            if expanded and slot.indexOf(self.pill_face) < 0:
                slot.addWidget(self.pill_face)
            elif not expanded and slot.indexOf(self.pill_face) >= 0:
                slot.removeWidget(self.pill_face)
                self.collapsed.layout().addWidget(self.pill_face)
                self.collapsed.layout().setAlignment(
                    self.pill_face, Qt.AlignLeft | Qt.AlignVCenter)
        except Exception:
            pass

    def _screen_geo(self) -> QRect:
        """The screen the island actually lives on, not always the primary.

        A position saved on a second monitor used to be clamped straight
        back onto the primary at the next start, so the widget jumped
        displays every time the dock changed.
        """
        s = self.screen() if self.isVisible() else None
        if s is None:
            screens = QApplication.screens()
            ix, iy = self.cfg.get("island_x"), self.cfg.get("island_y")
            # Prefer whichever screen still contains the saved position.
            if isinstance(ix, int) and isinstance(iy, int) and screens:
                for cand in screens:
                    g = cand.availableGeometry()
                    if g.contains(QPoint(ix, iy)):
                        return g
            s = QApplication.primaryScreen() or (screens[0] if screens else None)
        if s:
            return s.availableGeometry()
        return QRect(0, 0, 1920, 1080)

    @staticmethod
    def _clamp(pos: int, lo: int, size: int, span: int) -> int:
        """Keep `pos`..`pos`+`size` inside lo..lo+span.

        The old form was `min(max(ix, g.x()), g.x() + g.width() - w)`, which
        inverts when the window is wider than the screen: the upper bound
        becomes *smaller* than the lower bound and the window is pushed off
        the left edge.
        """
        hi = lo + max(0, span - size)
        return min(max(pos, lo), hi)

    def _island_home_rect(self, w: int, h: int) -> QRect:
        """Saved island position, clamped on-screen (top-center fallback)."""
        g = self._screen_geo()
        ix, iy = self.cfg.get("island_x"), self.cfg.get("island_y")
        if isinstance(ix, int) and isinstance(iy, int) \
                and not isinstance(ix, bool) and not isinstance(iy, bool):
            x = self._clamp(ix, g.x(), w, g.width())
            y = self._clamp(iy, g.y(), h, g.height())
        else:
            x = g.x() + (g.width() - w) // 2
            y = g.y() + ISLAND_TOP_INSET
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

    def _rail_visible_now(self) -> bool:
        """The rail is shown in both wide states — but not in corner mode,
        where it has nothing to sit beside."""
        if not self.expanded:
            return False
        return bool(self.centre_open) or self.cfg.get("mode") != "corner"

    def _expanded_size(self) -> tuple[int, int]:
        """Window size for the expanded card, including the rail.

        The window contains rail + gap + card, so sizing the *window* to
        EXPANDED_W (as the old two-row layout allowed) squeezed the rail out
        and left a 368px window with a 172px rail inside it.

        Height comes from the tallest tab rather than the card's own
        sizeHint, which QTabWidget inflates to a value that does not match
        anything actually on screen.
        """
        tallest = EXPANDED_H
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if page is not None:
                tallest = max(tallest, page.sizeHint().height())
        # Header, tab strip and hint label live above/below the pages.
        card_h = min(tallest + 96, EXPANDED_MAX_H)
        w = EXPANDED_W
        if self._rail_visible_now():
            w += self.rail.width() + CENTRE_GAP
        return w, card_h

    def _apply_mode_visual(self):
        is_corner = self.cfg.get("mode") == "corner"
        # `full` means the wide panel is showing; `card` means the expanded
        # card is. They are mutually exclusive: both live in the same
        # stacked area beside the rail.
        full = bool(self.expanded and self.centre_open)
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
            self.card.setVisible(self.expanded and not full)
            self.center.setVisible(full)
            if full:
                w, h = self._centre_geometry()
                self.setFixedSize(w, h)
            elif self.expanded:
                ew, eh = self._expanded_size()
                self.card.setFixedWidth(EXPANDED_W)
                self.setFixedSize(ew, eh)
                if is_corner:
                    self._move_to_corner()
            else:
                self.card.setFixedWidth(EXPANDED_W)
                self.setFixedSize(COLLAPSED_ISLAND_W, COLLAPSED_ISLAND_H)
        self._update_rail(full, is_corner)

    def _update_rail(self, full: bool = None, is_corner: bool = None) -> None:
        """The rail exists in both wide states, never in the collapsed one.

        Called directly from every transition as well as from the settle
        callback: relying on the callback alone meant the rail stayed hidden
        through the whole expand flight and only appeared at the end.
        """
        if full is None:
            full = bool(self.expanded and self.centre_open)
        if is_corner is None:
            is_corner = self.cfg.get("mode") == "corner"
        visible = bool(self.expanded and (full or not is_corner))
        if self.rail.isVisible() != visible or self.rail.isHidden() == visible:
            self.rail.setVisible(visible)
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
        # Read from the active theme. These were hardcoded to the `black`
        # theme's values, so switching to white/minimal/liquid and then
        # choosing corner mode gave you a black wedge.
        t = themesmod.resolve(self.cfg.get("theme", "black"))
        glass = t.get("glass", {})
        fill = colorsmod.to_qcolor(glass.get("bottom") or t.get("card_bg", "#0d0d10"),
                                   "#0d0d10")
        edge = colorsmod.to_qcolor(glass.get("border") or t.get("card_border", "#2c2c33"),
                                   "#2c2c33")
        ink = colorsmod.to_qcolor(t.get("text", "#f2efe8"), "#f2efe8")
        # quarter pie centered on the screen corner
        p.setBrush(fill)
        p.setPen(QPen(edge, 1.5))
        if c == "top-left":
            p.drawPie(-w, -h, 2 * w, 2 * h, 270 * 16, 90 * 16)
        elif c == "top-right":
            p.drawPie(0, -h, 2 * w, 2 * h, 180 * 16, 90 * 16)
        elif c == "bottom-left":
            p.drawPie(-w, 0, 2 * w, 2 * h, 0 * 16, 90 * 16)
        else:
            p.drawPie(0, 0, 2 * w, 2 * h, 90 * 16, 90 * 16)
        p.setPen(ink)
        # Only a quarter of this square is visible, so centring the clock in
        # the full rect puts it in the clipped-away part of the pie.
        p.drawText(QRect(0, 0, w, h),
                   Qt.AlignCenter, self.clock_text())

    # ---------- expand / collapse (click) ----------
    def expand(self, instant: bool = False):
        if self.expanded:
            return
        self.expanded = True
        self._move_pill_face(True)
        self._update_rail()
        self.set_emotion("01")  # waking blip, engine auto-advances to idle
        QTimer.singleShot(WAKE_SETTLE_MS, lambda: self.set_emotion("10") if self.expanded else None)
        w, h = self._expanded_size()
        if instant:
            # Land on the target state with no flight, so a double-click
            # never shows the card on its way to the full island.
            self._cancel_animation()
            self.setGeometry(self._expanded_geometry(w, h))
            self._apply_mode_visual()
            return
        self._animate_to(w, h, anchor_corner=(self.cfg.get("mode") == "corner"))

    def _expanded_geometry(self, w: int, h: int) -> QRect:
        g = self._screen_geo()
        cur = self.geometry()
        if self.cfg.get("mode") == "corner":
            m = int(self.cfg.get("corner_margin", 0) or 0)
            x, y = g.x() + g.width() - w - m, g.y() + m
        else:
            x = cur.x() + (cur.width() - w) // 2
            y = cur.y()
        return QRect(self._clamp(x, g.x(), w, g.width()),
                     self._clamp(y, g.y(), h, g.height()), w, h)

    def _cancel_animation(self) -> None:
        anim = getattr(self, "_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass

    def collapse(self):
        was_centre = self.centre_open
        if was_centre:
            self.close_centre()
            return
        if not self.expanded:
            return
        self.expanded = False
        self._move_pill_face(False)
        self._update_rail()
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
        """Window size for the full island: rail + the wide panel, one row.

        The panel has a FIXED height so the layout can never squeeze its
        contents; the feed list scrolls instead. On a short screen the
        panel shrinks to its minimum before anything is allowed to overlap.
        """
        g = self._screen_geo()
        avail_h = max(200, g.height() - 24)
        panel_h = min(CENTRE_H, max(CENTRE_MIN_H, avail_h))
        w = min(CENTRE_W, max(CENTRE_MIN_W, g.width() - 24))
        # The row also has to fit the rail beside the panel.
        need = Rail.WIDTH + CENTRE_GAP + EXPANDED_W + 24
        w = max(w, min(need, g.width() - 16))
        if self._centre_size != (w, panel_h):
            self._centre_size = (w, panel_h)
            self.center.setFixedSize(w, panel_h)
        return w, panel_h

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
        self._update_rail()
        self.center.sync_config(self.cfg)
        x, y = self._centre_origin(w, h)
        self._animate_to_rect(QRect(x, y, w, h), hide_card=False)
        self.set_emotion("35")

    def close_centre(self):
        if not self.centre_open:
            return
        self.centre_open = False
        self.center.hide()
        self._update_rail()
        w, h = self._expanded_size()
        self.card.setFixedWidth(EXPANDED_W)
        self._animate_to(w, h,
                         anchor_corner=(self.cfg.get("mode") == "corner"))

    def _centre_origin(self, w: int, h: int) -> tuple[int, int]:
        """Keep the wider panel on screen, biased to the current position."""
        g = self._screen_geo()
        cur = self.geometry()
        x = self._clamp(cur.x(), g.x(), w, g.width())
        y = self._clamp(cur.y(), g.y(), h, g.height())
        return x, y

    def _centre_config_changed(self):
        self.cfg = cfgmod.load()

    def _animate_to_rect(self, rect: QRect, hide_card: bool = True):
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
        self._anim.setDuration(ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setStartValue(cur)
        self._anim.setEndValue(QRect(rect))
        self._anim.finished.connect(self._apply_mode_visual)
        QTimer.singleShot(ANIM_SETTLE_MS, self._apply_mode_visual)
        # Show the pair that belongs to the target state, upfront, so the
        # flight grows out of the right widget.
        #
        # Collapsing hides the card early on purpose: its layout would
        # otherwise re-grow the window mid-flight and the capsule would
        # stretch. This branch used to run unconditionally, so opening the
        # control centre hid the card for the whole flight and flashed an
        # empty capsule back at the end.
        if hide_card:
            self.card.setVisible(False)
            self.collapsed.setVisible(True)
        elif self.expanded:
            self.collapsed.setVisible(False)
            self.card.setVisible(True)
            self.clearMask()
        self._anim.start()

    def _animate_to(self, w: int, h: int, anchor_corner: bool):
        cur = self.geometry()
        x, y = cur.x(), cur.y()
        if not anchor_corner:
            # keep top-center-ish: grow downward, keep horizontal center
            x = cur.x() + (cur.width() - w) // 2
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
        # One animation path for both helpers — they were near-identical
        # copies, and the divergence is what produced the centre flash.
        self._animate_to_rect(QRect(x, y, w, h),
                              hide_card=not self.expanded)

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
                    self.pill_face.setGaze(nx, ny)
                    self.tab_face.setGaze(nx, ny)
                except Exception:
                    pass

    def mouseReleaseEvent(self, event):  # noqa: N802
        was_drag = self._moved
        self._dragging = False
        if event.button() == Qt.LeftButton and not was_drag:
            # A single click acts immediately — no delay before the island
            # opens, because this is a click target you hit constantly. A
            # second click inside the double-click interval escalates to the
            # full island, and the in-flight expand flight is cancelled so
            # the card never flashes past on the way.
            now = time.monotonic()
            interval = QApplication.doubleClickInterval() / 1000.0
            if now - self._last_click < interval:
                self._last_click = 0.0
                self._double_click_action()
            else:
                self._last_click = now
                self.toggle()
        elif was_drag and self.cfg.get("mode") == "island" and not self.expanded:
            g = self.geometry()
            self.cfg["island_x"], self.cfg["island_y"] = g.x(), g.y()
            cfgmod.save(self.cfg)

    def _double_click_action(self) -> None:
        """Double-click always means "the full island", from either pill."""
        if not self.cfg.get("centre", {}).get("enabled", True):
            self.hint.setText("Control centre is switched off in config.json "
                              "(centre.enabled)")
            return
        if not self.expanded:
            # The first click already started an expand flight. Land it
            # instantly so the card is not drawn for even one frame on its
            # way to being replaced by the panel.
            self.expand(instant=True)
        self.open_centre()

    def eventFilter(self, obj, event):  # noqa: N802
        """Catch double-clicks on the expanded card.

        The card is made of ordinary widgets — QTabWidget, QLabel,
        QPushButton — and several of them consume the press, so a
        window-level handler alone never sees a double-click inside it.
        """
        if event.type() == QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton and obj is not self:
                self._last_click = 0.0
                self._double_click_action()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.collapse()
            return
        super().keyPressEvent(event)

    # ---------- timers ----------
    def clock_text(self) -> str:
        """The one clock. Three surfaces used to format independently, so the
        corner wedge and the capsule could disagree for up to a second."""
        return datetime.now().strftime("%H:%M")

    def _tick_clock(self):
        now = datetime.now()
        s = now.strftime("%H:%M")
        self.mini_time.setText(s)
        self.big_time.setText(s)
        if hasattr(self, "bot_tab") and self.bot_tab is not None:
            self.bot_tab.date.setText(now.strftime("%A  %Y-%m-%d"))
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
            self.pill_face.setEmotion(eid)
        except Exception:
            pass
        try:
            self.tab_face.setEmotion(eid)
        except Exception:
            pass
        if eid == "33":
            try:
                self.tab_face.burst(24)
            except Exception:
                pass

    def set_shape(self, shape: str):
        if shape not in ("blob", "wedge", "gem"):
            return
        self.cfg["shape"] = shape
        cfgmod.save(self.cfg)
        try:
            self.pill_face.setShape(shape)
            self.tab_face.setShape(shape)
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
            self.pill_face.setEngine(engine)
            self.tab_face.setEngine(engine)
        except Exception:
            pass
        # re-assert seed/expression on the fresh engine
        try:
            self.pill_face.setSeed(self.cfg.get("face_name", "island-bot"))
            self.tab_face.setSeed(self.cfg.get("face_name", "island-bot"))
            self.pill_face.setEmotion(self.cfg.get("emotion", "02"))
            self.tab_face.setEmotion(self.cfg.get("emotion", "02"))
        except Exception:
            pass
        self.bot_tab.set_face(engine)

    def set_seed(self, seed: str):
        if seed == iconsmod.SHUFFLE_SENTINEL:
            try:
                s1 = self.pill_face.shuffleSeed()
                self.tab_face.setSeed(s1)
                seed = s1
            except Exception:
                return
        seed = (seed or "").strip() or "island-bot"
        self.cfg["face_name"] = seed
        cfgmod.save(self.cfg)
        try:
            self.pill_face.setSeed(seed)
            self.tab_face.setSeed(seed)
        except Exception:
            pass
        self.bot_tab.set_seed(seed)

    def set_face_bg(self, bg: str):
        if bg not in ("none", "squircle", "circle", "square"):
            return
        self.cfg["face_bg"] = bg
        cfgmod.save(self.cfg)
        try:
            self.pill_face.setBackground(bg)
            self.tab_face.setBackground(bg)
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
        t = themesmod.resolve(self.cfg.get("theme", "black"))
        hexc = colorsmod.to_hex
        return {
            "ink": hexc(t.get("text", "#f2efe8")),
            "sub": hexc(t.get("subtext", "#a8a49d")),
            "muted": hexc(t.get("muted", "#6f6c68")),
            "text": hexc(t.get("text", "#f2efe8")),
            "accent": hexc(t.get("accent", "#59d98c")),
            "track": hexc(t.get("tab", "#17171b")),
            "bg": hexc(t.get("card_bg", "#0d0d10")),
            "pane": hexc(t.get("pane", "#101013")),
            "btn": hexc(t.get("btn", "#1d1d22")),
            "btn_border": hexc(t.get("btn_border", "#2c2c33")),
            # Disabled ink was a hardcoded grey living outside the theme
            # system, so it never matched any theme.
            "off": hexc(t.get("muted", "#6f6c68")),
            "warn": hexc(t.get("accent", "#59d98c")),
            "error": colorsmod.ERROR.hex(),
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
        self.cfg["island_x"], self.cfg["island_y"] = x, g.y() + ISLAND_TOP_INSET
        cfgmod.save(self.cfg)
        if self.expanded:
            self.collapse()
        self.setGeometry(x, g.y() + ISLAND_TOP_INSET, COLLAPSED_ISLAND_W, COLLAPSED_ISLAND_H)
        self._apply_mode_visual()

    def closeEvent(self, event):  # noqa: N802
        if self.cfg.get("mode") == "island" and not self.expanded:
            g = self.geometry()
            self.cfg["island_x"], self.cfg["island_y"] = g.x(), g.y()
        cfgmod.save(self.cfg)
        super().closeEvent(event)
