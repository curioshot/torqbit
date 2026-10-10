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
from . import sensors as sensorsmod
from . import sysctl
from .feedcar import FeedCarousel
from .glass import GlassPanel
from .widgets import VerticalSlider, RingGauge, ToggleDot

GAP = 8

# icon, short label, tooltip name, capability key, control kind
TOGGLES = [
    ("plane", "Airplane", "Airplane mode", "network", "airplane"),
    ("globe", "Net", "Network link", "network", "link"),
    ("wifi", "Wi-Fi", "Wi-Fi radio", "wifi", "wifi"),
    ("bt", "BT", "Bluetooth", "bluetooth", "bluetooth"),
    ("dnd", "DND", "Do not disturb", "dnd", "dnd"),
    ("mic", "Mic", "Mute microphone", "volume", "micmute"),
    ("moon", "Theme", "Light / dark theme", None, "theme"),
    ("lock", "Lock", "Lock screen", "lock", "lock"),
]

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
    """The 1-inch column on the left of the card.

    Sliders on top, toggle buttons underneath, and — deliberately — **no
    panel of its own**, so the controls sit straight on the wallpaper rather
    than inside a second box.
    """

    WIDTH = 96

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(self.WIDTH)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.s_mic = VerticalSlider("mic", "Mic")
        self.s_out = VerticalSlider("speaker", "Output")
        self.s_bright = VerticalSlider("sun", "Light")
        bars = QHBoxLayout()
        bars.setContentsMargins(0, 0, 0, 0)
        bars.setSpacing(0)
        for s in (self.s_mic, self.s_out, self.s_bright):
            bars.addWidget(s)
        lay.addLayout(bars, 1)

        self.toggles: dict[str, ToggleDot] = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        # two per row: three would be 3x58 in a 96px column, one per row
        # would make eight rows and a very long strip.
        for i, (icon_name, label, full, cap, kind) in enumerate(TOGGLES):
            d = ToggleDot(icon_name, label)
            d.tip = full
            self.toggles[kind] = d
            grid.addWidget(d, i // 2, i % 2)
        lay.addLayout(grid, 0)
        self.resize(self.WIDTH, 420)

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

    def __init__(self, on_config_changed=None, parent=None):
        super().__init__(parent)
        self._on_cfg = on_config_changed
        self._pal = {}
        self._theme = "black"
        self._last_action = 0.0

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(16)

        # ---- the rail: outside this panel, beside the card ----
        self.rail = Rail(self)

        # ---- feeds: continuous scroll, one feed at a time ----
        self.feeds = FeedCarousel(on_config_changed, self)
        root.addWidget(self.feeds, 1)

        # ---- right: gauge ----
        self.gauge = RingGauge()
        self.gauge.setFixedWidth(196)
        root.addWidget(self.gauge)

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
        self._poll.setInterval(1500)

        self.backend = sysctl.Backend.get()
        self.caps = self.backend.caps()
        self._apply_caps()

    # ------------------------------------------------------------ setup
    def sync_config(self, cfg: dict) -> None:
        self._theme = cfg.get("theme", "black")
        self.feeds.sync_config(cfg.get("centre", {}))
        want = cfg.get("centre", {}).get("enabled", True)
        if want and self.isVisible():
            self.start()
        self._refresh_metrics(force=True)

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
        # Repaint ourselves as a glass shell so the panel is visibly its own
        # container rather than floating on the wallpaper.
        from PySide6.QtGui import QColor
        bg = QColor(pal.get("bg", "#0d0d10"))
        border = QColor(pal.get("btn_border", "#2c2c33"))
        try:
            self.set_glass(bg, bg, border, 1.0, 20, False, False)
        except Exception:
            pass

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
        self._toggle_tick = getattr(self, "_toggle_tick", 0) + 1
        if self._toggle_tick % 2 == 0:
            self._refresh_toggles()

    def _refresh_metrics(self, force: bool = False) -> None:
        b = self.backend
        if force:
            b.audio._cache.clear()
            b.network._cache.clear()
        if self.caps["volume"]["available"] and self.s_mic.isVisible():
            v = b.audio.volume("source", fresh=force)
            if v is not None and not self.s_mic._press:
                self.s_mic.set_value(v)
            o = b.audio.volume("sink", fresh=force)
            if o is not None and not self.s_out._press:
                self.s_out.set_value(o)
        if self.caps["brightness"]["available"] and not self.s_bright._press:
            self.s_bright.set_value(b.brightness.get())

        down, up = b.speed.sample()
        temp = sensorsmod.get_cpu_temp()
        try:
            import psutil
            ram = psutil.virtual_memory().percent
            load = psutil.cpu_percent(interval=None)
        except Exception:
            ram = load = 0.0

        self.gauge.set_metric("TEMP", temp or 0.0, 100.0, "%.0f°C")
        self.gauge.set_metric("RAM", ram, 100.0, "%.0f%%")
        self.gauge.set_metric("LOAD", load, 100.0, "%.0f%%")
        head = f"{temp:.0f}°C" if temp else "—"
        self.gauge.set_center(head, f"↓ {sysctl.format_bps(down)}")

    def _refresh_toggles(self) -> None:
        b = self.backend
        try:
            self.toggles["airplane"].set_on(not (b.network.radios_enabled() or False))
            self.toggles["link"].set_on(bool(b.network.link_up()))
            if self.caps["wifi"]["available"]:
                self.toggles["wifi"].set_on(bool(b.network.wifi_enabled()))
            if self.caps["bluetooth"]["available"]:
                self.toggles["bluetooth"].set_on(bool(b.bluetooth.powered()))
            if self.caps["dnd"]["available"]:
                self.toggles["dnd"].set_on(bool(b.session.dnd()))
            if self.caps["volume"]["available"]:
                self.toggles["micmute"].set_on(bool(b.audio.muted("source")))
            self.toggles["theme"].set_on(self._theme in DARK_THEMES)
        except Exception:
            pass

    # ------------------------------------------------------------ actions
    def _set_audio(self, which: str, value: float) -> None:
        kind = "source" if which == "mic" else "sink"
        slider = self.s_mic if which == "mic" else self.s_out
        if self.backend.audio.set_volume(kind, value):
            self._last_action = time.monotonic()
            return
        # The device took the command but did not apply it — PipeWire does
        # exactly this on a suspended source. Say so rather than pretend.
        slider.set_control_enabled(
            False,
            "this device accepted the command but did not change volume; "
            "it may have no live capture or playback stream")

    def _set_brightness(self, value: float) -> None:
        if self.backend.brightness.set(value):
            self._last_action = time.monotonic()
            return
        self.s_bright.set_control_enabled(
            False, "this display rejected a brightness change")

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
            elif kind == "theme":
                self.themeToggleRequested.emit(
                    "white" if self._theme in DARK_THEMES else "black")
                dot.set_on(self._theme not in DARK_THEMES)
                return
            elif kind == "lock":
                ok = b.session.lock()
                dot.set_busy(True)
                QTimer.singleShot(1400, lambda: dot.set_busy(False))
                if ok:
                    return
            else:
                ok = False
        except Exception:
            ok = False
        if not ok:
            dot.flash_error()