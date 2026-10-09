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


class FeedListItem(QListWidgetItem):
    def __init__(self, title, feed, ts, link, role="headline"):
        super().__init__()
        self._title, self._feed, self._ts = title, feed, ts
        self._link, self.role = link, role
        self.setToolTip(link or feed)
        self.setData(Qt.UserRole, self)


class FeedPanel(QWidget):
    """Headline list with an Add button and a manual refresh."""

    feedsEdited = Signal()

    def __init__(self, on_config_changed=None, parent=None):
        super().__init__(parent)
        self._pal = {}
        self._on_cfg = on_config_changed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        head = QHBoxLayout()
        icon = QLabel()
        pm = iconsmod.pixmap("rss", 15, "#a8a49d")
        if pm is not None:
            icon.setPixmap(pm)
        head.addWidget(icon)
        title = QLabel("Feeds")
        title.setStyleSheet("font-size: 11px; font-weight: 700;")
        head.addWidget(title)
        head.addStretch(1)
        self.count = QLabel("")
        self.count.setStyleSheet("font-size: 9px;")
        head.addWidget(self.count)
        self.refresh_btn = QPushButton()
        self.refresh_btn.setFixedSize(26, 22)
        self.refresh_btn.setToolTip("Refresh now")
        self.refresh_btn.clicked.connect(self._refresh)
        head.addWidget(self.refresh_btn)
        self.add_btn = QPushButton()
        self.add_btn.setFixedSize(26, 22)
        self.add_btn.setToolTip("Add a feed")
        self.add_btn.clicked.connect(self._add)
        head.addWidget(self.add_btn)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.NoSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setMouseTracking(True)
        self.delegate = FeedDelegate({}, self)
        self.list.setItemDelegate(self.delegate)
        self.list.itemActivated.connect(self._open)
        self.list.itemClicked.connect(self._open)
        lay.addWidget(self.list, 1)

        self.reader = feedsmod.FeedReader(self)
        self.reader.feedsChanged.connect(self._reload)
        self.reader.error.connect(lambda _m: None)

    # -- config ---------------------------------------------------------
    def sync_config(self, cfg: dict) -> None:
        feeds = feedsmod.normalize(cfg.get("feeds", []))
        self.reader.set_feeds(feeds)

    def apply_palette(self, pal: dict) -> None:
        self._pal = dict(pal)
        self.delegate.set_palette(pal)
        self.count.setStyleSheet(
            f"font-size: 9px; color: {pal.get('sub', '#a8a49d')};")
        for w in self.findChildren(QLabel):
            if w.text() == "Feeds":
                w.setStyleSheet(
                    f"font-size: 11px; font-weight: 700;"
                    f" color: {pal.get('ink', '#f2efe8')};")
        self.list.setStyleSheet(
            f"QListWidget {{ background: {pal.get('pane', '#101013')};"
            f" border: 1px solid {pal.get('btn_border', '#2c2c33')};"
            f" border-radius: 8px; padding: 2px; color: {pal.get('text', '#f2efe8')}; }}"
            f"QListWidget::item {{ padding: 5px 6px; border-radius: 5px; }}"
            f"QListWidget::item:hover {{ background: {pal.get('btn', '#1d1d22')}; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {pal.get('btn_border', '#2c2c33')};"
            f" border-radius: 3px; min-height: 20px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}")

    # -- actions --------------------------------------------------------
    def start(self) -> None:
        self.reader.start()
        self.reader.refresh()

    def stop(self) -> None:
        self.reader.stop()

    def _refresh(self) -> None:
        self.reader._cache.clear()
        self.reader.refresh()

    def _add(self) -> None:
        current = self.reader.feeds()
        dlg = FeedPickerDialog(current, self._pal, self)
        if dlg.exec() != QDialog.Accepted:
            return
        chosen = dlg.result_feeds()
        if not chosen:
            return
        cfg = cfgmod.load()
        cfg["centre"]["feeds"] = chosen
        cfgmod.save(cfg)
        self.reader.set_feeds(chosen)
        self._reload()
        self.feedsEdited.emit()

    def _open(self, item) -> None:
        link = getattr(item, "_link", "")
        if link:
            QDesktopServices.openUrl(QUrl(link))

    # -- render ---------------------------------------------------------
    def _reload(self) -> None:
        self.list.clear()
        shown = 0
        for it in self.reader.items():
            if it.get("error"):
                self.list.addItem(FeedListItem(
                    it["title"], it["feed"], 0.0, "", "error"))
                continue
            if it.get("pending"):
                self.list.addItem(FeedListItem(
                    it["title"], it["feed"], 0.0, "", "pending"))
                continue
            shown += 1
            self.list.addItem(FeedListItem(
                it["title"], it["feed"], float(it.get("ts") or 0.0),
                it.get("link", "")))
        self.count.setText(f"{shown} items" if shown else "")

    def _refresh_buttons(self) -> None:
        ink = self._pal.get("ink", "#f2efe8")
        for key, name in (("add_btn", "plus"), ("refresh_btn", "refresh")):
            btn = getattr(self, key)
            icon = iconsmod.icon(name, 14, ink)
            if not icon.isNull():
                btn.setIcon(icon)

    def paint_subtitle(self) -> None:
        """Second line per row (feed name + age) via a custom item delegate."""
        self.list.setItemDelegate(FeedDelegate(self._pal))


class FeedDelegate(QStyledItemDelegate):
    """Two-line rows: headline, then "feed · age" in muted text.

    QListWidget cannot do a second line, and a QWidget per row is far too
    heavy for a list that repaints on a timer.
    """

    def __init__(self, pal: dict, parent=None):
        super().__init__(parent)
        self.pal = dict(pal)

    def set_palette(self, pal: dict) -> None:
        self.pal = dict(pal)

    def sizeHint(self, option, index):  # noqa: N802
        s = super().sizeHint(option, index)
        s.setHeight(max(34, s.height() + 12))
        return s

    def paint(self, p: QPainter, option, index) -> None:
        item = index.data(Qt.UserRole)
        if not isinstance(item, FeedListItem):
            super().paint(p, option, index)
            return
        p.save()
        try:
            rect = option.rect
            pal = self.pal
            if option.state & QStyle.StateFlag.State_MouseOver:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(pal.get("btn", "#1d1d22")))
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
            p.setPen(QColor(pal.get("ink", "#f2efe8")
                            if item.role == "headline"
                            else pal.get("muted", "#6f6c68")))
            f = p.font()
            f.setPointSizeF(9.5)
            p.setFont(f)
            metrics = p.fontMetrics()
            title = metrics.elidedText(item._title, Qt.ElideRight,
                                       rect.width() - 82)
            p.drawText(rect.adjusted(9, 3, -74, 0),
                       Qt.AlignLeft | Qt.AlignVCenter, title)
            age = feedsmod.ago(item._ts)
            label = f"{item._feed} · {age}" if age else item._feed
            f.setPointSizeF(8.0)
            p.setFont(f)
            p.setPen(QColor(pal.get("muted", "#6f6c68")))
            lw = p.fontMetrics().horizontalAdvance(label)
            p.drawText(rect.adjusted(max(10, rect.width() - lw - 10), 3, -8, 0),
                       Qt.AlignLeft | Qt.AlignVCenter, label)
        finally:
            # Must restore even if painting raised: an unbalanced save() is
            # what turns a paint error into a segfault.
            p.restore()


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


class ControlCenter(GlassPanel):
    """The second container — a glass shell, deliberately detached from the
    card above it. Owns polling; idle when not visible."""

    themeToggleRequested = Signal(str)

    def __init__(self, on_config_changed=None, parent=None):
        super().__init__(parent)
        self._on_cfg = on_config_changed
        self._pal = {}
        self._theme = "black"
        self._last_action = 0.0

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(14)

        # ---- left column: sliders + toggles ----
        left = QVBoxLayout()
        left.setSpacing(10)
        bars = QHBoxLayout()
        bars.setSpacing(6)
        self.s_mic = VerticalSlider("mic", "Mic")
        self.s_out = VerticalSlider("speaker", "Output")
        self.s_bright = VerticalSlider("sun", "Light")
        for s in (self.s_mic, self.s_out, self.s_bright):
            s.setFixedHeight(108)
            bars.addWidget(s)
        # Each slider gets its own handler: they do different things, so a
        # shared default would silently drive mic from all three.
        self.s_mic.released.connect(lambda v: self._set_audio("mic", v))
        self.s_out.released.connect(lambda v: self._set_audio("out", v))
        self.s_bright.released.connect(
            lambda v: self._set_brightness(v))
        left.addLayout(bars)

        grid = QGridLayout()
        grid.setSpacing(4)
        self.toggles: dict[str, ToggleDot] = {}
        # 4 columns x 2 rows: three rows would not fit the panel height and Qt
        # would silently compress the rows until the captions overlapped.
        for i, (icon_name, label, full, cap, kind) in enumerate(TOGGLES):
            d = ToggleDot(icon_name, label)
            d.tip = full
            d.clicked.connect(lambda k=kind, t=d: self._toggle(k, t))
            self.toggles[kind] = d
            grid.addWidget(d, i // 4, i % 4)
        left.addLayout(grid)
        left.addStretch(1)
        leftw = QWidget()
        leftw.setLayout(left)
        leftw.setFixedWidth(256)
        root.addWidget(leftw)

        # ---- centre: feeds ----
        self.feeds = FeedPanel(on_config_changed, self)
        root.addWidget(self.feeds, 1)

        # ---- right: gauge ----
        self.gauge = RingGauge()
        self.gauge.setFixedWidth(212)
        root.addWidget(self.gauge)

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
        for w in (self.s_mic, self.s_out, self.s_bright, self.gauge):
            w.apply_palette(pal)
        for d in self.toggles.values():
            d.apply_palette(pal)
        self.feeds.apply_palette(pal)
        self.feeds._refresh_buttons()
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