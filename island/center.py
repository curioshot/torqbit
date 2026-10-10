"""The control centre — the second glass panel.

Laid out as:

    ┌─ centre panel ────────────────────────────────────────────────┐
    │  ┌──┐┌──┐┌──┐   ┌── feeds ─────────[+]─┐   ╭───────────────╮  │
    │  │🎤││🔊││☀ │   │ • headline      2h  │   │   ring gauge  │  │
    │  └──┘└──┘└──┘   │ • headline      4h  │   │  temp/ram/net │  │
    │   ○ ○ ○         │ • headline      6h  │   ╰───────────────╯  │
    │   ○ ○ ○           └────────────────────┘                       │
    │   ○ ○ ○                                                          │
    └─────────────────────────────────────────────────────────────────┘

Everything is capability-gated: a control the machine cannot perform renders
disabled and carries the reason in its tooltip, rather than pretending to
work. Polling only runs while the panel is visible.
"""
from __future__ import annotations

import time
import webbrowser

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QColor, QBrush, QPen, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QDialog, QComboBox, QLineEdit, QCheckBox, QGridLayout,
    QAbstractItemView, QFrame, QSizePolicy, QMessageBox, QStyledItemDelegate, QStyle,
)

from . import config as cfgmod
from . import feeds as feedsmod
from . import icons as iconsmod
from . import probe as probes
from . import sensors as sensorsmod
from . import sysctl
from .feedcar import FeedCarousel
from .glass import GlassPanel
from .todo import TodoColumn, CALENDAR_W
from .widgets import VerticalSlider, RingGauge, ToggleDot

GAP = 8
POLL_MS = 1500
# Toggle indicators change at human speed; re-reading NetworkManager
# and pactl on every tick is what made this panel feel heavy.
TOGGLE_EVERY_N_TICKS = 2
# How long to wait before re-probing capabilities after a failed write.
RECAP_DELAY_MS = 4000
# Reading back a write lands within this tolerance of what we asked for.
VERIFY_TOLERANCE = 0.06
GAUGE_W = 196

# icon, short label, tooltip name, capability key, control kind
TOGGLES = [
    ("plane", "Airplane", "Airplane mode", "network", "airplane"),
    ("globe", "Net", "Network link", "network", "link"),
    ("wifi", "Wi-Fi", "Wi-Fi radio", "wifi", "wifi"),
    ("bt", "BT", "Bluetooth", "bluetooth", "bluetooth"),
    ("dnd", "DND", "Do not disturb", "dnd", "dnd"),
    ("mic", "Mic", "Mute microphone", "volume", "micmute"),
    ("speaker", "Speaker", "Mute audio output", "volume", "spkmute"),
    ("moon", "Theme", "Light / dark theme", None, "theme"),
    ("lock", "Lock", "Lock screen", "lock", "lock"),
    ("power", "Blank", "Blank the screen", "blank", "blank"),
    ("thermo", "Night", "Night light / blue-light filter", "nightlight",
     "nightlight"),
    ("party", "Play", "Play or pause the current track", "playback",
     "playback"),
    ("speed", "Shot", "Save a screenshot", "screenshot", "screenshot"),
]

# The rail is a 4-column grid. Grid spacing and dot size are chosen so a
# dot never wraps to the next row: RAIL_W must be >= 4*DOT_W + 3*DOT_GAP.
RAIL_COLUMNS = 4
DOT_W, DOT_H = 40, 52
DOT_GAP = 4
SLIDER_W = 48
RAIL_W = max(96, RAIL_COLUMNS * DOT_W + (RAIL_COLUMNS - 1) * DOT_GAP)


def _rows_for(count: int, columns: int = RAIL_COLUMNS) -> int:
    return (count + columns - 1) // columns

DARK_THEMES = {"black", "liquid", "minimal"}
LIGHT_THEMES = {"white"}




class FeedPickerDialog(QDialog):
    """Category -> feeds, multi-select, plus a custom URL box."""

    def __init__(self, current: list[dict], pal: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add feeds")
        self.setMinimumWidth(430)
        have = {f["url"] for f in current}
        lay = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Category"))
        self.cat = QComboBox()
        self.cat.addItems(list(feedsmod.CATALOG.keys()))
        self.cat.currentIndexChanged.connect(self._fill)
        row.addWidget(self.cat, 1)
        lay.addLayout(row)

        self.list = QListWidget()
        for name, url in feedsmod.CATALOG[self.cat.currentText()]:
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, url)
            it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            it.setCheckState(Qt.Unchecked if url in have else Qt.Checked)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)

        self.status = QLabel("Ticked feeds are added; already-added ones are shown unticked.")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        custom = QHBoxLayout()
        custom.addWidget(QLabel("Custom URL"))
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://example.com/feed.xml")
        self.url.returnPressed.connect(self._add_custom)
        custom.addWidget(self.url, 1)
        addb = QPushButton("Add")
        addb.clicked.connect(self._add_custom)
        custom.addWidget(addb)
        lay.addLayout(custom)

        self.name = QLineEdit()
        self.name.setPlaceholderText("name for that custom feed (optional)")
        lay.addWidget(self.name)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Save")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _fill(self) -> None:
        self.list.clear()
        for name, url in feedsmod.CATALOG[self.cat.currentText()]:
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, url)
            it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            it.setCheckState(Qt.Unchecked)
            self.list.addItem(it)

    def _add_custom(self) -> None:
        url = self.url.text().strip()
        if not url:
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._extra = getattr(self, "_extra", [])
        self._extra.append({"name": self.name.text().strip() or url, "url": url})
        self.url.clear()
        self.name.clear()
        self.status.setText(f"Added {self._extra[-1]['name']} — press Save.")

    def result_feeds(self) -> list[dict]:
        out: list[dict] = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                url = it.data(Qt.UserRole)
                out.append({"name": it.text(), "url": url})
        out.extend(getattr(self, "_extra", []))
        return out


class Rail(QWidget):
    """The control column on the left: sliders on top, a 4-column grid of
    toggles underneath, and — deliberately — **no panel of its own**, so the
    controls sit straight on the wallpaper rather than inside a second box.
    """

    WIDTH = RAIL_W

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(RAIL_W)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        self.s_mic = VerticalSlider("mic", "Mic")
        self.s_out = VerticalSlider("speaker", "Output")
        self.s_bright = VerticalSlider("sun", "Light")
        bars = QHBoxLayout()
        bars.setContentsMargins(0, 0, 0, 0)
        bars.setSpacing(8)
        for s in (self.s_mic, self.s_out, self.s_bright):
            s.setFixedWidth(SLIDER_W)
            bars.addWidget(s)
        lay.addLayout(bars, 1)

        self.toggles: dict[str, ToggleDot] = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(DOT_GAP)
        for i, (icon_name, label, full, cap, kind) in enumerate(TOGGLES):
            d = ToggleDot(icon_name, label)
            d.tip = full
            self.toggles[kind] = d
            grid.addWidget(d, i // RAIL_COLUMNS, i % RAIL_COLUMNS)
        # Fill any trailing slots so the grid keeps its width even when a
        # future release ships fewer toggles than the row count implies.
        for slot in range(len(TOGGLES),
                          RAIL_COLUMNS * _rows_for(len(TOGGLES))):
            grid.addWidget(QWidget(), slot // RAIL_COLUMNS,
                           slot % RAIL_COLUMNS)
        lay.addLayout(grid, 0)

    def apply_palette(self, pal: dict) -> None:
        for w in (self.s_mic, self.s_out, self.s_bright):
            w.apply_palette(pal)
        for d in self.toggles.values():
            d.apply_palette(pal)


class ControlCenter(GlassPanel):
    """The second container — a glass shell, deliberately detached from the
    card above it. Owns polling; idle when not visible.

    The sliders and toggle buttons live in `self.rail`, which the window
    places beside the card rather than inside this panel.
    """

    themeToggleRequested = Signal(str)
    toastRequested = Signal(str)

    def __init__(self, on_config_changed=None, parent=None):
        super().__init__(parent)
        self._on_cfg = on_config_changed
        self._pal = {}
        self._theme = "black"

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(20)

        # ---- the rail: outside this panel, in the row beside it ----
        self.rail = Rail(self)

        # ---- feeds: continuous scroll, one feed at a time ----
        self.feeds = FeedCarousel(on_config_changed, self)
        root.addWidget(self.feeds, 1)

        # ---- gauge ----
        self.gauge = RingGauge()
        self.gauge.setFixedWidth(GAUGE_W)
        root.addWidget(self.gauge)

        # ---- calendar / to-dos, as the last column ----
        self.calendar = TodoColumn(on_config_changed, self)
        self.calendar.setFixedWidth(CALENDAR_W)
        root.addWidget(self.calendar)

        # convenience aliases: the rail's controls, reachable from here
        self.s_mic = self.rail.s_mic
        self.s_out = self.rail.s_out
        self.s_bright = self.rail.s_bright
        self.toggles = self.rail.toggles
        self.s_mic.released.connect(lambda v: self._set_audio("mic", v))
        self.s_out.released.connect(lambda v: self._set_audio("out", v))
        self.s_bright.released.connect(lambda v: self._set_brightness(v))
        for _i, (_ic, _lb, _full, _cap, kind) in enumerate(TOGGLES):
            self.toggles[kind].clicked.connect(
                lambda k=kind, t=self.toggles[kind]: self._toggle(k, t))

        # ---- polling ----
        self._poll = QTimer(self)
        self._poll.timeout.connect(self.tick)
        self._poll.setInterval(POLL_MS)

        # The backend probes five subsystems, several of them with 3-4s
        # subprocess timeouts. Probing that on the GUI thread froze startup
        # for seconds on an unhappy machine, so it goes through the worker.
        self.backend = probes.run(sysctl.Backend.get, timeout=15.0) \
            or sysctl.Backend.get()
        self.caps = probes.run(self.backend.caps, timeout=8.0) \
            or self.backend.caps()
        self._toggle_tick = 0
        self._apply_caps()

    # ------------------------------------------------------------ setup
    def sync_config(self, cfg: dict) -> None:
        self._theme = cfg.get("theme", "black")
        self.feeds.sync_config(cfg.get("centre", {}))
        # `show()` already fired showEvent -> start(). Calling start() again
        # here, plus an unconditional forced refresh, meant opening the
        # centre cost three full metric refreshes and two toggle refreshes —
        # roughly fourteen synchronous subprocess spawns in one event-loop
        # turn, because `force` cleared the TTL caches each time.
        if cfg.get("centre", {}).get("enabled", True) and not self._poll.isActive():
            self.start()

    def _apply_caps(self) -> None:
        c = self.caps
        vol_ok = c["volume"]["available"]
        self.s_mic.set_control_enabled(
            vol_ok, c["volume"]["reason"] if not vol_ok else "")
        self.s_out.set_control_enabled(
            vol_ok, c["volume"]["reason"] if not vol_ok else "")
        br = c["brightness"]
        self.s_bright.set_control_enabled(
            br["available"], br["reason"] if not br["available"] else "")

        for (_icon, _label, _full, cap_key, kind) in TOGGLES:
            dot = self.toggles[kind]
            if cap_key is None:
                dot.set_control_enabled(True, "")
                continue
            cap = c.get(cap_key, {})
            dot.set_control_enabled(
                bool(cap.get("available")),
                cap.get("reason", "") if not cap.get("available") else "")

    def apply_palette(self, pal: dict) -> None:
        self._pal = dict(pal)
        self.gauge.apply_palette(pal)
        self.feeds.apply_palette(pal)
        self.rail.apply_palette(pal)
        self.calendar.apply_palette(pal)
        # Frameless: the panel paints nothing, so the RSS list, the gauge and
        # the calendar sit directly on the screen with no container behind
        # them. This call used to paint a glass shell here.
        self.set_frameless(True)

    # ------------------------------------------------------------ life
    def start(self) -> None:
        if not self._poll.isActive():
            self._poll.start()
        self.feeds.start()
        self._refresh_metrics(force=True)
        self._refresh_toggles()

    def stop(self) -> None:
        self._poll.stop()
        self.feeds.stop()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.start()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self.stop()

    # ------------------------------------------------------------ poll
    def tick(self) -> None:
        self._refresh_metrics()
        # Toggle indicators change at human speed; re-reading NetworkManager
        # and pactl on every tick is what made this panel feel heavy.
        self._toggle_tick += 1
        if self._toggle_tick % TOGGLE_EVERY_N_TICKS == 0:
            self._refresh_toggles()

    def _refresh_metrics(self, force: bool = False) -> None:
        b = self.backend
        if force:
            probes.run(lambda: (b.audio._cache.clear(),
                                b.network._cache.clear()))
        if self.caps["volume"]["available"] and self.s_mic.isVisible():
            # One worker hop for both volumes: pactl costs ~50ms a spawn and
            # this runs every 1.5s. It blocks the GUI thread, so it must not.
            vols = probes.run(lambda: (b.audio.volume("source", fresh=force),
                                       b.audio.volume("sink", fresh=force)),
                              timeout=4.0, default=(None, None))
            v, o = vols
            if v is not None and not self.s_mic.is_dragging():
                self.s_mic.set_value(v)
            if o is not None and not self.s_out.is_dragging():
                self.s_out.set_value(o)
        if self.caps["brightness"]["available"] and not self.s_bright.is_dragging():
            level = probes.run(b.brightness.get, timeout=4.0)
            if level is not None:
                self.s_bright.set_value(level)

        down, up = b.speed.sample()
        temp = sensorsmod.get_cpu_temp()
        ram, load = probes.run(self._host_load, timeout=3.0, default=(0.0, 0.0))

        self.gauge.set_metric("TEMP", temp or 0.0, 100.0, "%.0f°C")
        self.gauge.set_metric("RAM", ram, 100.0, "%.0f%%")
        self.gauge.set_metric("LOAD", load, 100.0, "%.0f%%")
        head = f"{temp:.0f}°C" if temp else "—"
        self.gauge.set_center(head, f"↓ {sysctl.format_bps(down)}")

    @staticmethod
    def _host_load() -> tuple[float, float]:
        try:
            import psutil
            return psutil.virtual_memory().percent, psutil.cpu_percent(
                interval=None)
        except Exception:
            return 0.0, 0.0

    def _refresh_toggles(self) -> None:
        """Read every toggle's real state in ONE worker hop.

        Read individually this was up to seven `nmcli`/`bluetoothctl`/
        `pactl` spawns per tick, each 50-150ms, all on the GUI thread. One
        hop keeps the stall off the event loop entirely.
        """
        states = probes.run(self._read_toggle_states, timeout=6.0)
        if not states:
            return
        for kind, on in states.items():
            dot = self.toggles.get(kind)
            if dot is not None:
                dot.set_on(bool(on))

    def _read_toggle_states(self) -> dict:
        b = self.backend
        c = self.caps
        out: dict[str, bool] = {}
        try:
            out["airplane"] = not (b.network.radios_enabled() or False)
            out["link"] = bool(b.network.link_up())
            if c["wifi"]["available"]:
                out["wifi"] = bool(b.network.wifi_enabled())
            if c["bluetooth"]["available"]:
                out["bluetooth"] = bool(b.bluetooth.powered())
            if c["dnd"]["available"]:
                out["dnd"] = bool(b.session.dnd())
            if c["volume"]["available"]:
                out["micmute"] = bool(b.audio.muted("source"))
                out["spkmute"] = bool(b.audio.muted("sink"))
            if c["nightlight"]["available"]:
                out["nightlight"] = bool(b.night_light.enabled())
            if c["playback"]["available"]:
                playing = b.playback.playing()
                if playing is not None:
                    out["playback"] = playing
        except Exception:
            return {}
        # Theme is local state, not a system read — always applied.
        out["theme"] = self._theme in DARK_THEMES
        return out

    # ------------------------------------------------------------ actions
    def _set_audio(self, which: str, value: float) -> None:
        kind = "source" if which == "mic" else "sink"
        slider = self.s_mic if which == "mic" else self.s_out
        if self.backend.audio.set_volume(kind, value):
            return
        # The device took the command but did not apply it — PipeWire does
        # exactly this on a suspended source, and it is routine. Say so, and
        # try again shortly; latching the control off here left it dead for
        # the rest of the session after one transient hiccup.
        slider.flash_error()
        slider.setToolTip(
            "This device accepted the command but did not change volume.\n"
            "It may have no live capture or playback stream right now.\n"
            "The bot will try again on the next change.")
        self._schedule_recap()

    def _schedule_recap(self) -> None:
        """Re-apply capabilities shortly after a failed write."""
        t = getattr(self, "_recap", None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._recap_caps)
            self._recap = t
        if not t.isActive():
            t.start(RECAP_DELAY_MS)

    def _recap_caps(self) -> None:
        """Re-probe after a transient failure, rather than staying disabled."""
        try:
            self.backend.reprobe()
            self.caps = self.backend.caps()
            self._apply_caps()
        except Exception:
            pass

    def _set_brightness(self, value: float) -> None:
        if self.backend.brightness.set(value):
            return
        self.s_bright.flash_error()
        self.s_bright.setToolTip(
            "This display rejected a brightness change.")
        self._schedule_recap()

    def _toggle_speaker_mute(self) -> bool | None:
        """Flip output mute. `audio.muted` already handles sinks; this
        exists so a failure surfaces as None (unchanged) rather than a
        silently wrong state."""
        cur = self.backend.audio.muted("sink", fresh=True)
        if cur is None:
            return None
        want = not cur
        return want if self.backend.audio.set_muted("sink", want) else None

    def _toggle(self, kind: str, dot: ToggleDot) -> None:
        b = self.backend
        c = self.caps
        try:
            if kind == "airplane":
                cur = b.network.radios_enabled()
                ok = b.network.set_airplane(off=bool(cur))
                dot.set_on(not (b.network.radios_enabled() or False))
            elif kind == "link":
                cur = b.network.link_up()
                if cur is None:
                    ok = False
                else:
                    ok = b.network.set_link(not cur)
                dot.set_on(bool(b.network.link_up()))
            elif kind == "wifi":
                cur = b.network.wifi_enabled()
                ok = b.network.set_wifi(not bool(cur)) if cur is not None else False
                dot.set_on(bool(b.network.wifi_enabled()))
            elif kind == "bluetooth":
                cur = b.bluetooth.powered()
                ok = b.bluetooth.set_powered(not bool(cur)) if cur is not None else False
                dot.set_on(bool(b.bluetooth.powered()))
            elif kind == "dnd":
                cur = b.session.dnd()
                ok = b.session.set_dnd(not bool(cur)) if cur is not None else False
                dot.set_on(bool(b.session.dnd()))
            elif kind == "micmute":
                r = b.audio.toggle_mic()
                ok = r is not None
                if r is not None:
                    dot.set_on(bool(r))
            elif kind == "spkmute":
                r = self._toggle_speaker_mute()
                ok = r is not None
                if r is not None:
                    dot.set_on(bool(r))
            elif kind == "theme":
                self.themeToggleRequested.emit(
                    "white" if self._theme in DARK_THEMES else "black")
                dot.set_on(self._theme not in DARK_THEMES)
                return
            elif kind == "lock":
                ok = probes.run(b.session.lock, timeout=4.0, default=False)
                if ok:
                    # The screen locks, so the panel goes with it; there is
                    # no point animating a busy state nobody will see.
                    return
            elif kind == "blank":
                ok = probes.run(b.blank_screen.blank, timeout=6.0,
                                default=False)
                # Nothing to show afterwards: the screen is off.
                return
            elif kind == "nightlight":
                r = probes.run(b.night_light.toggle, timeout=5.0)
                ok = r is not None
                if r is not None:
                    dot.set_on(bool(r))
            elif kind == "playback":
                r = probes.run(b.playback.play_pause, timeout=5.0)
                ok = r is not None
                if r is not None:
                    dot.set_on(bool(r))
            elif kind == "screenshot":
                ok = probes.run(b.screenshot.grab, timeout=12.0,
                                default=False)
                if ok:
                    self.toastRequested.emit(
                        f"Screenshot saved to {b.screenshot._dir}")
            else:
                ok = False
        except Exception:
            ok = False
        if not ok:
            dot.flash_error()