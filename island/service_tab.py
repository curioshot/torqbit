"""Service tab: Instagram (ReelScroll replacement) + Spotify (lyrics) services.

Home shows two 20px-radius square tiles. Each tile opens its settings page
with a service toggle: when on, the bot auto-detects the app in use and runs
the bot-native behavior itself — no browser extension needed for keys/buttons,
no separate lyrics window needed for Spotify.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    QCheckBox, QSpinBox, QStackedWidget, QToolButton, QListWidget,
    QSizePolicy,
)

from . import config as cfgmod
from . import icons as iconsmod
from . import services as svc


def _dot(color: str) -> str:
    return (f"background: {color}; border-radius: 5px; min-width: 10px;"
            f" min-height: 10px; max-width: 10px; max-height: 10px;")


class _BackHeader(QWidget):
    def __init__(self, title: str, on_back, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        back = QPushButton("Back")
        back.setFixedWidth(64)
        back.clicked.connect(on_back)
        lay.addWidget(back)
        t = QLabel(title)
        t.setStyleSheet("font-size: 15px; font-weight: 700;")
        lay.addWidget(t, 1)


class InstagramPage(QWidget):
    """ReelScroll settings, mirrored from the extension into the bot."""

    _ARROW_SYMS = {"Left": 0xFF51, "Up": 0xFF52, "Right": 0xFF53, "Down": 0xFF54}

    def __init__(self, on_back, parent=None):
        super().__init__(parent)
        self._capturing: str | None = None  # "next" | "prev" | None
        self.setFocusPolicy(Qt.StrongFocus)
        lay = QVBoxLayout(self)
        lay.addWidget(_BackHeader("Instagram — Reels", on_back))

        from PySide6.QtWidgets import QScrollArea, QFrame
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        body_w = QWidget()
        self._body = body_w  # themed opaque canvas (see themes.apply_theme)
        body = QVBoxLayout(body_w)
        body.setContentsMargins(0, 0, 4, 0)
        scroll.setWidget(body_w)
        lay.addWidget(scroll, 1)

        top = QHBoxLayout()
        self.service = QCheckBox("Service on")
        self.service.setToolTip("When on, the bot watches for Instagram Reels\n"
                                "and takes over reel control itself.")
        self.service.checkStateChanged.connect(self._save_service)
        top.addWidget(self.service)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        top.addWidget(self.dot)
        self.status = QLabel("starting…")
        self.status.setWordWrap(True)
        top.addWidget(self.status, 1)
        body.addLayout(top)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("Prev reel")
        self.next_btn = QPushButton("Next reel")
        self.prev_btn.clicked.connect(lambda: self._nudge("prev"))
        self.next_btn.clicked.connect(lambda: self._nudge("next"))
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        body.addLayout(nav)

        grid = QGridLayout()
        self.boxes: dict[str, QCheckBox] = {}
        for i, (key, label, tip) in enumerate([
            ("enabled", "Enabled", "Master switch for reel control"),
            ("wheelEnabled", "Wheel flip", "Wheel remap needs page JS — stays in the browser extension"),
            ("invertWheel", "Invert wheel", "Wheel direction, used by the browser extension"),
            ("smooth", "Smooth jumps", "Animate the jump between reels"),
            ("allowArrows", "Arrow keys", "Let arrow keys flip reels too"),
            ("controllerEnabled", "Video controller", "Floating pill over the playing reel"),
            ("autoAdvance", "Auto-advance", "Load the next reel when one finishes"),
        ]):
            b = QCheckBox(label)
            b.setToolTip(tip)
            b.checkStateChanged.connect(lambda _s, k=key: self._save_box(k))
            grid.addWidget(b, i // 2, i % 2)
            self.boxes[key] = b
        body.addLayout(grid)

        tune = QGridLayout()
        tune.addWidget(QLabel("Cooldown"), 0, 0)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(100, 3000)
        self.cooldown.setSingleStep(50)
        self.cooldown.setSuffix(" ms")
        self.cooldown.valueChanged.connect(lambda _v: self._save_spin())
        tune.addWidget(self.cooldown, 0, 1)
        tune.addWidget(QLabel("Threshold"), 0, 2)
        self.threshold = QSpinBox()
        self.threshold.setRange(5, 200)
        self.threshold.setSuffix(" px")
        self.threshold.valueChanged.connect(lambda _v: self._save_spin())
        tune.addWidget(self.threshold, 0, 3)
        tune.addWidget(QLabel("Prev key"), 1, 0)
        self.prev_key = QPushButton("W")
        self.prev_key.clicked.connect(lambda: self._arm("prev"))
        tune.addWidget(self.prev_key, 1, 1)
        tune.addWidget(QLabel("Next key"), 1, 2)
        self.next_key = QPushButton("S")
        self.next_key.clicked.connect(lambda: self._arm("next"))
        tune.addWidget(self.next_key, 1, 3)
        tune.setColumnStretch(1, 1)
        tune.setColumnStretch(3, 1)
        body.addLayout(tune)

        note = QLabel("Wheel flip runs in the browser extension (needs page JS). "
                      "Keys, buttons and detection run natively in the bot.")
        note.setWordWrap(True)
        body.addWidget(note)
        body.addStretch(1)
        lay.addStretch(1)
        self._load_all()

    # ----- config -----
    def _cfg(self) -> dict:
        return cfgmod.load().get("instagram", {})

    def _patch(self, patch: dict):
        cfg = cfgmod.load()
        cfg["instagram"].update(patch)
        cfgmod.save(cfg)

    def _load_all(self):
        s = self._cfg()
        self.service.blockSignals(True)
        self.service.setChecked(bool(s.get("service")))
        self.service.blockSignals(False)
        for k, b in self.boxes.items():
            b.blockSignals(True)
            b.setChecked(bool(s.get(k, True)))
            b.blockSignals(False)
        self.cooldown.blockSignals(True)
        self.cooldown.setValue(int(s.get("cooldownMs", 800)))
        self.cooldown.blockSignals(False)
        self.threshold.blockSignals(True)
        self.threshold.setValue(int(s.get("wheelThreshold", 30)))
        self.threshold.blockSignals(False)
        self.prev_key.setText(str(s.get("prev_label", "W")))
        self.next_key.setText(str(s.get("next_label", "S")))

    def _save_service(self):
        self._patch({"service": self.service.isChecked()})
        self.refresh()

    def _save_box(self, key: str):
        self._patch({key: self.boxes[key].isChecked()})

    def _save_spin(self):
        self._patch({"cooldownMs": self.cooldown.value(),
                     "wheelThreshold": self.threshold.value()})

    # ----- key capture -----
    def _arm(self, which: str):
        self._capturing = which
        btn = self.prev_key if which == "prev" else self.next_key
        btn.setText("Press a key…")
        self.setFocus()

    def keyPressEvent(self, event):  # noqa: N802
        if self._capturing is None:
            return super().keyPressEvent(event)
        if event.key() in (Qt.Key_Escape, Qt.Key_Enter, Qt.Key_Return):
            self._capturing = None
            self._load_all()
            return
        sym, label = self._qt_to_sym(event)
        if sym is None:
            return
        which = self._capturing
        self._capturing = None
        self._patch({f"{which}_keysym": sym, f"{which}_label": label})
        self._load_all()

    @classmethod
    def _qt_to_sym(cls, event) -> tuple[int | None, str]:
        k = event.key()
        if Qt.Key_A <= k <= Qt.Key_Z or Qt.Key_0 <= k <= Qt.Key_9:
            return k, chr(k)
        if k == Qt.Key_Space:
            return 0x20, "Space"
        names = {Qt.Key_Left: "Left", Qt.Key_Up: "Up",
                 Qt.Key_Right: "Right", Qt.Key_Down: "Down"}
        if k in names:
            return cls._ARROW_SYMS[names[k]], names[k]
        return None, ""

    # ----- live -----
    def _nudge(self, which: str):
        s = self._cfg()
        sym = int(s.get(f"{which}_keysym", 83 if which == "next" else 87))
        ok, msg = svc.send_reel_key(sym)
        self.status.setText(("Sent " if ok else "Could not send ") +
                            f"{which} key ({msg})")

    def refresh(self):
        s = self._cfg()
        on = bool(s.get("service"))
        self.service.blockSignals(True)
        self.service.setChecked(on)
        self.service.blockSignals(False)
        detected, detail = svc.detect_instagram()
        active = on and bool(s.get("enabled", True)) and detected
        self.dot.setStyleSheet(_dot("#59d98c" if active else "#55555c"))
        if not on:
            self.status.setText("Service off — toggle on to watch for Reels.")
        elif not detected:
            self.status.setText(f"Watching… ({detail})")
        else:
            self.status.setText(f"Controlling Reels — {detail}")
        self.prev_btn.setEnabled(active)
        self.next_btn.setEnabled(active)


class SpotifyPage(QWidget):
    def __init__(self, on_back, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_BackHeader("Spotify — Lyrics", on_back))

        top = QHBoxLayout()
        self.service = QCheckBox("Service on")
        self.service.setToolTip("When on, the bot watches Spotify and shows\n"
                                "synced lyrics here automatically.")
        self.service.checkStateChanged.connect(self._save_service)
        top.addWidget(self.service)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        top.addWidget(self.dot)
        self.status = QLabel("starting…")
        self.status.setWordWrap(True)
        top.addWidget(self.status, 1)
        lay.addLayout(top)

        self.track = QLabel("No track")
        self.track.setStyleSheet("font-size: 14px; font-weight: 700;")
        self.track.setWordWrap(True)
        lay.addWidget(self.track)

        self.lyrics = QListWidget()
        lay.addWidget(self.lyrics, 1)

        row = QHBoxLayout()
        self.ov_btn = QPushButton("Floating overlay")
        self.ov_btn.setToolTip("Latch: once on, the overlay stays up —\n"
                               "the bot restarts it if it ever drops.")
        self.ov_btn.setCheckable(True)
        self.ov_btn.toggled.connect(self._save_overlay)
        row.addWidget(self.ov_btn)
        self.app_btn = QPushButton("Open Spotify")
        self.app_btn.clicked.connect(lambda: svc.launch_spotify())
        row.addWidget(self.app_btn)
        lay.addLayout(row)

        hint = QLabel("Desktop app is read offline via MPRIS. Lyrics via lrclib.net. "
                      "Web player / phone need login: spotify at developer.spotify.com, "
                      "then run spotify/.venv/bin/python cli.py auth login")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._track_key: str | None = None
        self._times: list = []
        self._pending: dict | None = None
        self._load_all()

    def _cfg(self) -> dict:
        return cfgmod.load().get("spotify", {})

    def _load_all(self):
        s = self._cfg()
        self.service.blockSignals(True)
        self.service.setChecked(bool(s.get("service")))
        self.service.blockSignals(False)
        self.ov_btn.blockSignals(True)
        self.ov_btn.setChecked(bool(s.get("overlay")))
        self.ov_btn.blockSignals(False)

    def _save_service(self):
        on = self.service.isChecked()
        cfg = cfgmod.load()
        cfg["spotify"]["service"] = on
        cfgmod.save(cfg)
        if on and not svc.spotify_process_running():
            if svc.launch_spotify():
                self.status.setText("Starting Spotify…")
            else:
                self.status.setText("Spotify app not found.")
        if not on and svc.overlay_running():
            svc.overlay_cmd("stop")  # service owns the overlay; leave none behind
        self.refresh()

    def _save_overlay(self):
        cfg = cfgmod.load()
        cfg["spotify"]["overlay"] = self.ov_btn.isChecked()
        cfgmod.save(cfg)
        self.refresh()

    def _drain_pending(self):
        if self._pending is not None:
            rec, key = self._pending, self._track_key
            self._pending = None
            if rec and rec.get("mode") == "synced":
                self._times = rec.get("times", [])
                texts = rec.get("texts", [])
                self.lyrics.clear()
                for line in texts:
                    self.lyrics.addItem(line or "·")
            elif rec and rec.get("mode") == "plain":
                self._times = []
                self.lyrics.clear()
                for line in (rec.get("texts") or ["(static lyrics)"]):
                    self.lyrics.addItem(line or "·")
            else:
                self._times = []
                self.lyrics.clear()
                self.lyrics.addItem("(no lyrics found)")

    def refresh(self):
        self._drain_pending()
        cfg = cfgmod.load()
        s = cfg.get("spotify", {})
        on = bool(s.get("service"))
        # re-sync toggles with disk truth (an external edit can never leave
        # the UI lying about the real state)
        self.service.blockSignals(True)
        self.service.setChecked(on)
        self.service.blockSignals(False)
        self.ov_btn.blockSignals(True)
        self.ov_btn.setChecked(bool(s.get("overlay")))
        self.ov_btn.blockSignals(False)
        # overlay latch watchdog: latched on -> must be running
        if on and s.get("overlay"):
            if not svc.overlay_running():
                svc.place_overlay_default()
                svc.overlay_start_detached()
        elif not s.get("overlay") and svc.overlay_running() and not on:
            svc.overlay_cmd("stop")
        snap = svc.spotify_snapshot() if on else None
        if not on:
            self.dot.setStyleSheet(_dot("#55555c"))
            self.status.setText("Service off — toggle on to follow Spotify.")
            return
        if not snap:
            self.dot.setStyleSheet(_dot("#55555c"))
            if svc.spotify_process_running():
                self.status.setText("Spotify runs but exposes no track yet.")
            else:
                self.status.setText("Spotify not running.")
            return
        self.dot.setStyleSheet(
            _dot("#59d98c" if snap.get("is_playing") else "#c9a227"))
        state = "Playing" if snap.get("is_playing") else "Paused"
        self.status.setText(f"{state} via {snap.get('provider', 'mpris')}")
        self.track.setText(f"{snap.get('title', '?')} — {snap.get('artist', '?')}")
        key = snap.get("track_key")
        if key != self._track_key:
            self._track_key = key
            self._times = []
            self.lyrics.clear()
            self.lyrics.addItem("Fetching lyrics…")
            svc.fetch_lyrics_async(
                snap.get("title", ""), snap.get("artist", ""),
                snap.get("album", ""), snap.get("duration_ms", 0),
                lambda rec: self._store_pending(rec))
        else:
            idx = svc.line_index_at(self._times, snap.get("progress_ms", 0))
            if 0 <= idx < self.lyrics.count():
                self.lyrics.setCurrentRow(idx)

    def _store_pending(self, rec):
        self._pending = rec


class ServiceTab(QWidget):
    """Home tiles -> per-service settings pages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        home = QWidget()
        grid = QGridLayout(home)
        grid.setAlignment(Qt.AlignCenter)
        self.tiles: dict[str, QToolButton] = {}
        for i, (key, label, icon, tip) in enumerate([
            ("instagram", "Instagram", "instagram",
             "ReelScroll replacement: reel control + settings"),
            ("spotify", "Spotify", "spotify",
             "Now playing + synced lyrics + overlay"),
        ]):
            t = QToolButton()
            t.setText(label)
            t.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            t.setIcon(iconsmod.icon(icon, 44))
            t.setIconSize(QSize(44, 44))
            t.setFixedSize(128, 128)
            t.setToolTip(tip)
            t.clicked.connect(lambda _=False, k=key: self.open(k))
            grid.addWidget(t, 0, i, Qt.AlignCenter)
            self.tiles[key] = t
        grid.setSpacing(16)
        self.stack.addWidget(home)

        self.insta = InstagramPage(lambda: self.stack.setCurrentIndex(0))
        self.spot = SpotifyPage(lambda: self.stack.setCurrentIndex(0))
        self.stack.addWidget(self.insta)
        self.stack.addWidget(self.spot)

        self._t = QTimer(self)
        self._t.timeout.connect(self._poll)
        self._t.start(2000)
        self._poll()

    def open(self, key: str):
        self.stack.setCurrentIndex(1 if key == "instagram" else 2)

    def _poll(self):
        try:
            self.insta.refresh()
        except Exception:
            pass
        try:
            self.spot.refresh()
        except Exception:
            pass

    def set_icon_tint(self, color: str):
        try:
            self.tiles["instagram"].setIcon(iconsmod.icon("instagram", 44, color))
            self.tiles["spotify"].setIcon(iconsmod.icon("spotify", 44, color))
        except Exception:
            pass
