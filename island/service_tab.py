"""Service tab: Instagram (Reels) + Spotify (lyrics) services.

Instagram runs natively: island/reels.py injects assets/reels/ into the page
over CDP/BiDi, so wheel flip, the video controller and auto-advance all work
with no browser extension. The X11 key path in island/services.py is kept as
a fallback for browsers the bot cannot attach to.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    QCheckBox, QComboBox, QSpinBox, QStackedWidget, QToolButton, QListWidget,
    QSizePolicy,
)

from . import browsers
from . import config as cfgmod
from . import icons as iconsmod
from . import services as svc
from .reels import ReelsService


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
    """Native Reels control: browser launch, live status, settings mirror."""

    _ARROW_SYMS = {"Left": 0xFF51, "Up": 0xFF52, "Right": 0xFF53, "Down": 0xFF54}

    def __init__(self, on_back, service=None, parent=None):
        super().__init__(parent)
        self.svc = service                      # ReelsService, shared
        self._capturing: str | None = None      # "next" | "prev" | None
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
        self.service.setToolTip("When on, the bot attaches to Instagram in your\n"
                                "browser and controls Reels itself.")
        self.service.checkStateChanged.connect(self._save_service)
        top.addWidget(self.service)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        top.addWidget(self.dot)
        self.status = QLabel("starting…")
        self.status.setWordWrap(True)
        top.addWidget(self.status, 1)
        body.addLayout(top)

        # ---- browser -------------------------------------------------
        br = QGridLayout()
        br.addWidget(QLabel("Browser"), 0, 0)
        self.browser = QComboBox()
        self.browser.setToolTip("Which browser the bot launches and drives.")
        self.browser.currentIndexChanged.connect(self._save_browser)
        br.addWidget(self.browser, 0, 1)
        self.open_btn = QPushButton("Open Instagram")
        self.open_btn.setToolTip("Launches a bot-managed window with its own\n"
                                 "profile. Log into Instagram there once.")
        self.open_btn.clicked.connect(self._open)
        br.addWidget(self.open_btn, 0, 2)
        br.setColumnStretch(1, 1)
        body.addLayout(br)

        self.shim = QCheckBox("Also control Reels when I start the browser myself")
        self.shim.setToolTip(
            "Installs a small wrapper earlier on PATH so every launch of this\n"
            "browser comes up instrumented.\n\n"
            "The debug port is then open for ALL of your browsing in that\n"
            "browser, not just Reels. The bot still never reads your normal\n"
            "profile, cookies or passwords.")
        self.shim.checkStateChanged.connect(self._toggle_shim)
        body.addWidget(self.shim)

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
            ("wheelEnabled", "Wheel flip", "One wheel notch = exactly one reel"),
            ("invertWheel", "Invert wheel", "Reverse the wheel direction"),
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

        note = QLabel("Everything runs natively inside the bot — no browser "
                      "extension is installed. When no instrumented browser is "
                      "available the bot falls back to sending next/prev keys "
                      "to the Instagram window directly.")
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
        if self.svc:
            self.svc.sync_config(cfg["instagram"])

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

        self._fill_browsers(s.get("browserFamily", "chromium"))

    def _fill_browsers(self, current: str):
        found = browsers.discover()
        self.browser.blockSignals(True)
        self.browser.clear()
        for b in found:
            self.browser.addItem(b["label"], b["family"])
        idx = self.browser.findData(current)
        if idx < 0 and found:
            idx = 0
            current = found[0]["family"]
        if idx >= 0:
            self.browser.setCurrentIndex(idx)
        self.browser.setEnabled(bool(found))
        self.browser.blockSignals(False)
        if not found:
            self.open_btn.setEnabled(False)
            self.open_btn.setToolTip("No supported browser found")
        self._sync_shim()

    def _sync_shim(self):
        fam = self.browser.currentData() or "chromium"
        try:
            installed = browsers.shim_installed(fam)
        except Exception:
            installed = False
        self.shim.blockSignals(True)
        self.shim.setChecked(installed)
        self.shim.blockSignals(False)

    # ----- actions -----
    def _save_service(self):
        self._patch({"service": self.service.isChecked()})
        self.refresh()

    def _save_browser(self):
        fam = self.browser.currentData()
        if not fam:
            return
        self._patch({"browserFamily": fam})
        if self.svc:
            self.svc.set_family(fam)
        self._sync_shim()

    def _toggle_shim(self):
        if not self.svc:
            return
        fam = self.browser.currentData() or "chromium"
        msg = (self.svc.uninstall_shim() if self.shim.isChecked()
               else self.svc.install_shim())
        self.status.setText(msg)
        self._sync_shim()

    def _open(self):
        if self.svc:
            self.status.setText(self.svc.open_instagram())

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
        if not self.svc:
            return
        fn = self.svc.next_reel if which == "next" else self.svc.prev_reel

        def done(result, error):
            origin, payload = result if result else ("x11", {})
            ok = bool(payload.get("ok")) if isinstance(payload, dict) else False
            if error:
                self.status.setText(f"Could not send {which}: {error}")
            elif origin == "native":
                self.status.setText(
                    f"{which.capitalize()} reel (in-page)"
                    if ok else f"Bot could not turn: {payload}")
            else:
                self.status.setText(
                    f"Sent {which} key ({payload.get('detail', '')})"
                    if ok else "No Instagram window found")

        fn(done)

    def refresh(self):
        s = self._cfg()
        on = bool(s.get("service"))
        st = self.svc.state() if self.svc else {}
        connected = bool(st.get("connected"))
        reels = bool(st.get("reelsPage"))
        active = connected and reels and on and bool(s.get("enabled", True))
        self.dot.setStyleSheet(_dot("#59d98c" if active else "#55555c"))
        self.status.setText(st.get("detail", "") or "idle")
        self.prev_btn.setEnabled(on)
        self.next_btn.setEnabled(on)


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

        # One shared Reels controller: browser launch, page bridge and the
        # X11 key fallback live behind a single object the page polls.
        self.reels = ReelsService(self)
        self.reels.message.connect(lambda m: None)

        home = QWidget()
        grid = QGridLayout(home)
        grid.setAlignment(Qt.AlignCenter)
        self.tiles: dict[str, QToolButton] = {}
        for i, (key, label, icon, tip) in enumerate([
            ("instagram", "Instagram", "instagram",
             "Reels control: native, no browser extension"),
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

        self.insta = InstagramPage(lambda: self.stack.setCurrentIndex(0),
                                   service=self.reels)
        self.spot = SpotifyPage(lambda: self.stack.setCurrentIndex(0))
        self.stack.addWidget(self.insta)
        self.stack.addWidget(self.spot)

        self.reels.sync_config(cfgmod.load().get("instagram", {}))

        self._t = QTimer(self)
        self._t.timeout.connect(self._poll)
        self._t.start(2000)
        self._poll()

    def open(self, key: str):
        self.stack.setCurrentIndex(1 if key == "instagram" else 2)

    def _poll(self):
        try:
            self.reels.tick()
        except Exception:
            pass
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
