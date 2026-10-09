"""Bot face widget with selectable engines: Blobatar / Aora-ball / Simple.

- blobatar: vendored Alain00/blobatar core (MIT) in assets/blobatar/face.html
- aora: vendored sam70361/aora-bot EmotionBall in assets/emotion-ball/mini.html
- simple: built-in QPainter fallback (no WebEngine needed)
"""
from __future__ import annotations

import os
import random
import urllib.parse
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE_OK = True
except Exception:  # pragma: no cover
    QWebEngineView = None  # type: ignore
    _WEBENGINE_OK = False

ENGINES = ("blobatar", "aora", "simple")

AORA_HTML = Path(__file__).resolve().parent.parent / "assets" / "emotion-ball" / "mini.html"
BLOB_HTML = Path(__file__).resolve().parent.parent / "assets" / "blobatar" / "face.html"

# Island mood IDs (aora emotionIds) -> blobatar expressions.
AORA_TO_BLOB = {
    "01": "surprised",  # waking blip
    "02": "idle",
    "10": "happy",
    "30": "thinking",
    "32": "unsure",
    "35": "surprised",
    "33": "love",
    "00": "sleepy",
    "21": "mad",
    "41": "sleepy",     # powering off
}

# Verified-good creature seeds (see assets/blobatar/preview.html).
SEED_POOL = ["island-bot", "grok", "taro", "miso", "pixel", "bot", "nebula", "aora"]


def _webengine_available() -> bool:
    if os.environ.get("BOT_ISLAND_NO_WEBENGINE") == "1":
        return False
    return bool(_WEBENGINE_OK)


class FallbackFace(QWidget):
    """Minimal blinking eyes so the island still looks alive without WebEngine."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open = 1.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(90)
        self._phase = 0
        self.setAttribute(Qt.WA_TranslucentBackground)

    def _tick(self):
        self._phase += 1
        # blink every ~40 ticks
        if self._phase % 43 in (0, 1, 2):
            self._open = 0.12
        else:
            self._open = 1.0
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setBrush(QColor("#111114"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        # eyes
        ew, eh = w * 0.16, h * 0.42 * self._open
        for cx in (w * 0.36, w * 0.64):
            p.setBrush(QColor("#f5f2ea"))
            p.drawEllipse(int(cx - ew / 2), int(h / 2 - eh / 2), int(ew), int(max(eh, 2)))


# (Backwards-compat alias defined after FaceView, at end of module.)


class FaceView(QWidget):
    """Engine-aware face: hosts blobatar / aora-ball web UIs or the fallback."""

    def __init__(self, engine: str = "blobatar", seed: str = "island-bot",
                 emotion: str = "02", shape: str = "blob",
                 background: str = "none", eye_scale: float = 1.6,
                 lite: bool = True, parent=None):
        super().__init__(parent)
        self._engine = engine if engine in ENGINES else "blobatar"
        self._seed = seed or "island-bot"
        self._emotion = emotion          # island mood id (aora space)
        self._shape = shape              # aora only
        self._background = background    # blobatar only
        self._eye_scale = eye_scale      # aora only
        self._lite = lite                # aora only
        self._inner = None

        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._build_inner(lay)

    # ---------- construction ----------
    def _build_inner(self, lay):
        if self._engine == "simple" or not _webengine_available():
            if self._engine != "simple":
                self._engine_effective = "simple-fallback"
            else:
                self._engine_effective = "simple"
            self._inner = FallbackFace(self)
        else:
            self._engine_effective = self._engine
            try:
                view = QWebEngineView(self)
                view.setAttribute(Qt.WA_TranslucentBackground)
                view.page().setBackgroundColor(Qt.transparent)
                view.setContextMenuPolicy(Qt.NoContextMenu)
                view.page().settings().setAttribute(
                    view.page().settings().WebAttribute.ShowScrollBars, False)
                self._inner = view
                try:
                    view.loadFinished.connect(lambda _ok: self._reapply())
                except Exception:
                    pass
            except Exception:
                self._engine_effective = "simple-fallback"
                self._inner = FallbackFace(self)
        # replace layout content
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._inner:
                w.deleteLater()
        lay.addWidget(self._inner)
        if not isinstance(self._inner, FallbackFace):
            self.reload()

    def _url(self) -> QUrl:
        if self._engine == "aora":
            base = QUrl.fromLocalFile(str(AORA_HTML))
            base.setQuery(urllib.parse.urlencode({
                "emotion": self._emotion,
                "shape": self._shape,
                "eyeScale": str(self._eye_scale),
                "lite": "1" if self._lite else "0",
            }))
            return base
        # blobatar
        base = QUrl.fromLocalFile(str(BLOB_HTML))
        base.setQuery(urllib.parse.urlencode({
            "name": self._seed,
            "expression": AORA_TO_BLOB.get(self._emotion, "idle"),
            "background": self._background,
            "travel": "4",
        }))
        return base

    def reload(self):
        if self._inner is None or isinstance(self._inner, FallbackFace):
            return
        try:
            self._inner.setUrl(self._url())
        except Exception:
            pass

    def _js(self, code: str):
        try:
            if self._inner is not None and not isinstance(self._inner, FallbackFace):
                self._inner.page().runJavaScript(code)
        except Exception:
            pass

    def _reapply(self):
        if self._engine == "aora":
            self._js(f"window.__botSetEmotion && window.__botSetEmotion('{self._emotion}')")
        elif self._engine == "blobatar":
            expr = AORA_TO_BLOB.get(self._emotion, "idle")
            self._js(f"window.__faceSetExpression && window.__faceSetExpression('{expr}')")

    # ---------- lifecycle ----------
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._set_lifecycle(True)

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._set_lifecycle(False)

    def _set_lifecycle(self, active: bool):
        """Freeze the page when the widget is hidden.

        The card's face view sits inside a hidden panel whenever the island
        is collapsed, yet the page keeps running its animation loop and
        driving the compositor. Measured cost of one hidden animated view:
        ~22% of a core plus ~60MB. Freezing stops all of it.
        """
        if isinstance(self._inner, FallbackFace) or self._inner is None:
            return
        try:
            self._inner.setVisible(active)
            page = self._inner.page()
            if hasattr(page, "setLifecycleState"):
                from PySide6.QtWebEngineCore import QWebEnginePage
                page.setLifecycleState(
                    QWebEnginePage.LifecycleState.Active if active
                    else QWebEnginePage.LifecycleState.Frozen)
        except Exception:
            pass

    def setEngine(self, engine: str):
        if engine not in ENGINES or engine == self._engine:
            return
        self._engine = engine
        lay = self.layout()
        old = self._inner
        self._build_inner(lay)
        if old is not None and old is not self._inner:
            old.deleteLater()
        self._set_lifecycle(self.isVisible())

    @property
    def engine(self) -> str:
        return self._engine

    def setSeed(self, seed: str):
        seed = (seed or "").strip() or "island-bot"
        self._seed = seed
        if self._engine == "blobatar":
            self._js(f"window.__faceSetName && window.__faceSetName({js_str(seed)})")

    def shuffleSeed(self) -> str:
        pool = [s for s in SEED_POOL if s != self._seed] or SEED_POOL
        seed = random.choice(pool)
        self.setSeed(seed)
        return seed

    def setBackground(self, bg: str):
        if bg not in ("none", "squircle", "circle", "square"):
            return
        self._background = bg
        if self._engine == "blobatar":
            self._js(f"window.__faceSetBackground && window.__faceSetBackground('{bg}')")

    def setEmotion(self, eid: str):
        """Island mood id; mapped per engine."""
        self._emotion = eid
        if self._engine == "aora":
            self._js(f"window.__botSetEmotion && window.__botSetEmotion('{eid}')")
        elif self._engine == "blobatar":
            expr = AORA_TO_BLOB.get(eid, "idle")
            self._js(f"window.__faceSetExpression && window.__faceSetExpression('{expr}')")
        if eid == "33":
            self.burst(24)

    def setShape(self, shape: str):
        """Aora-ball body shape; ignored by other engines."""
        if shape not in ("blob", "wedge", "gem"):
            return
        self._shape = shape
        if self._engine == "aora":
            self._js(f"window.__botRecreate && window.__botRecreate('{shape}','{self._emotion}')")

    def setGaze(self, nx: float, ny: float):
        nx = max(-1.0, min(1.0, nx))
        ny = max(-1.0, min(1.0, ny))
        if self._engine == "aora":
            self._js(f"window.__botGaze && window.__botGaze({nx:.3f},{ny:.3f})")
        elif self._engine == "blobatar":
            self._js(f"window.__faceLook && window.__faceLook({nx:.3f},{ny:.3f})")

    def spin(self):
        if self._engine == "aora":
            self._js("window.__botSpin && window.__botSpin()")

    def burst(self, n: int = 20):
        if self._engine == "aora":
            self._js(f"window.__botBurst && window.__botBurst({int(n)})")


def js_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


# Keep module import order safe: js_str used above at runtime only.

# Backwards-compat alias (same kwargs, engine defaults to blobatar).
BotFaceView = FaceView
