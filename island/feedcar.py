"""The feed carousel: one feed visible at a time, scrolling on into the next.

Layout per feed is a vertical block — the feed's own picture, then its name,
then its headlines — so scrolling down the container flows from the end of
one feed into the header of the next. No frames, no borders, no tabs, no
arrows: the scroll itself is the only navigation.

Where a feed advertises no logo we draw a coloured monogram instead. The
picture always comes from the feed's own XML; nothing is ever requested from
a third-party icon service.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QSizePolicy, QMenu,
)

from . import feeds as feedsmod
from . import icons as iconsmod

IMAGE_PX = 30          # the feed's picture
MONO_PX = 30           # the monogram fallback
HEAD_GAP = 10
ITEM_GAP = 3


class Monogram(QLabel):
    """First letter of the feed name on a stable per-feed colour."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(MONO_PX, MONO_PX)
        self._name = name or "?"
        self.setPixmap(self._render())

    def _render(self) -> QPixmap:
        pm = QPixmap(MONO_PX, MONO_PX)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(feedsmod.mono_colour(self._name)))
        p.drawRoundedRect(0, 0, MONO_PX, MONO_PX, 7, 7)
        p.setPen(QColor("#101014"))
        f = p.font()
        f.setPixelSize(16)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, self._name[:1].upper())
        p.end()
        return pm


class FeedSection(QWidget):
    """One feed: picture, name, then its headlines."""

    def __init__(self, name: str, items: list[dict], image_bytes, parent=None):
        super().__init__(parent)
        self._pal = {}
        self._name = name
        self._ages: list[QLabel] = []
        self._texts: list[QLabel] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 6)
        lay.setSpacing(ITEM_GAP)

        head = QVBoxLayout()
        head.setSpacing(4)
        self.pic = QLabel()
        self.pic.setFixedSize(IMAGE_PX, IMAGE_PX)
        self.pic.setAlignment(Qt.AlignCenter)
        pm = QPixmap()
        if image_bytes:
            pm.loadFromData(image_bytes)
        if pm.isNull() or pm.width() <= 1:
            self.pic.setPixmap(Monogram(name).pixmap())
        else:
            self.pic.setPixmap(pm.scaled(
                IMAGE_PX, IMAGE_PX, Qt.KeepAspectRatio,
                Qt.SmoothTransformation))
        head.addWidget(self.pic, 0, Qt.AlignHCenter)

        self.title = QLabel(name)
        self.title.setWordWrap(False)
        self.title.setAlignment(Qt.AlignHCenter)
        head.addWidget(self.title, 0, Qt.AlignHCenter)
        lay.addLayout(head)

        # a hairline rule, not a border: it separates without boxing anything
        self.rule = QFrame()
        self.rule.setFixedHeight(1)
        self.rule.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.rule)
        lay.addSpacing(3)

        for it in items:
            row = QHBoxLayout()
            row.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(4, 4)
            dot.setPixmap(self._dot_pixmap(name))
            dot.setStyleSheet("background: transparent;")
            row.addWidget(dot, 0, Qt.AlignTop)
            txt = QLabel(it.get("title", ""))
            txt.setWordWrap(True)
            txt.setToolTip(it.get("link", "") or name)
            self._texts.append(txt)
            row.addWidget(txt, 1)
            age = QLabel(feedsmod.ago(it.get("ts") or 0.0))
            age.setFixedWidth(34)
            age.setAlignment(Qt.AlignRight | Qt.AlignTop)
            self._ages.append(age)
            row.addWidget(age, 0, Qt.AlignTop)
            lay.addLayout(row)
        lay.addSpacing(HEAD_GAP)

    def set_image(self, image_bytes) -> None:
        """Swap a placeholder monogram for the real picture once it lands."""
        if not image_bytes:
            return
        pm = QPixmap()
        pm.loadFromData(image_bytes)
        if pm.isNull() or pm.width() <= 1:
            return
        self.pic.setPixmap(pm.scaled(
            IMAGE_PX, IMAGE_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _dot_pixmap(self, name: str) -> QPixmap:
        pm = QPixmap(4, 4)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(feedsmod.mono_colour(name)))
        p.drawEllipse(0, 0, 4, 4)
        p.end()
        return pm

    def apply_palette(self, pal: dict) -> None:
        self._pal = dict(pal)
        ink = pal.get("ink", "#f2efe8")
        sub = pal.get("sub", "#a8a49d")
        muted = pal.get("muted", "#6f6c68")
        self.title.setStyleSheet(
            f"color:{ink}; font-size:11px; font-weight:700; background:transparent;")
        self.rule.setStyleSheet(f"background:{muted}; border:none;")
        for t in self._texts:
            t.setStyleSheet(
                f"color:{sub}; font-size:9.5px; background:transparent;")
        for a in self._ages:
            a.setStyleSheet(
                f"color:{muted}; font-size:8px; background:transparent;")


class FeedCarousel(QWidget):
    """All feeds, one after another, in one continuous scroll."""

    addRequested = Signal()

    def __init__(self, on_config_changed=None, parent=None):
        super().__init__(parent)
        self._pal = {}
        self._on_cfg = on_config_changed

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)      # no frame, no border
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.body = QWidget()
        # The strip has no panel of its own: without this it inherits the
        # default opaque palette grey and paints a light slab over the glass.
        self.body.setAttribute(Qt.WA_TranslucentBackground, True)
        self.body.setAutoFillBackground(False)
        self.body.setStyleSheet("background: transparent;")
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 4, 0)
        self.body_lay.setSpacing(0)
        self.body_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        self.reader = feedsmod.FeedReader(self)
        self.reader.feedsChanged.connect(self._rebuild)
        self.reader.imageReady.connect(self._rebuild_images)
        self.reader.error.connect(lambda _m: None)
        self._sections: list[FeedSection] = []

    # ------------------------------------------------------------- config
    def sync_config(self, cfg: dict) -> None:
        self.reader.set_feeds(feedsmod.normalize(cfg.get("feeds", [])))

    def start(self) -> None:
        self.reader.start()
        self.reader.refresh()

    def stop(self) -> None:
        self.reader.stop()

    # ------------------------------------------------------------- render
    def _clear(self) -> None:
        while self.body_lay.count():
            item = self.body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._sections = []

    def _grouped(self):
        """[{name, items, url}] in feed order, one block per feed."""
        out = []
        for feed in self.reader.feeds():
            items = self.reader.feed_items(feed["url"])
            out.append({"name": feed["name"], "url": feed["url"],
                        "items": items[:feedsmod.MAX_ITEMS_PER_FEED]})
        return out

    def _rebuild(self) -> None:
        self._clear()
        for blk in self._grouped():
            sec = FeedSection(blk["name"], blk["items"],
                              self.reader.image_bytes(blk["url"]))
            sec._feed_url = blk["url"]
            if self._pal:
                sec.apply_palette(self._pal)
            self.body_lay.addWidget(sec)
            self._sections.append(sec)
        self.body_lay.addStretch(1)

    def _rebuild_images(self, feed_url: str) -> None:
        """A logo finished downloading: swap that one section's picture."""
        data = self.reader.image_bytes(feed_url)
        if not data:
            return
        for sec in self._sections:
            if getattr(sec, "_feed_url", None) == feed_url:
                sec.set_image(data)

    def apply_palette(self, pal: dict) -> None:
        self._pal = dict(pal)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: {pal.get('btn_border', '#2c2c33')};"
            f" border-radius: 3px; min-height: 24px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}")
        for sec in self._sections:
            sec.apply_palette(pal)

    # ------------------------------------------------------------- add feeds
    def _menu(self, pos) -> None:
        m = QMenu(self)
        a = m.addAction("Add or remove feeds…")
        a.triggered.connect(self._open_picker)
        m.exec(self.mapToGlobal(pos))

    def _open_picker(self) -> None:
        from .center import FeedPickerDialog
        from . import config as cfgmod
        dlg = FeedPickerDialog(self.reader.feeds(), self._pal, self)
        if dlg.exec() != dlg.Accepted:
            return
        chosen = dlg.result_feeds()
        if not chosen:
            return
        cfg = cfgmod.load()
        cfg["centre"]["feeds"] = chosen
        cfgmod.save(cfg)
        self.reader.set_feeds(chosen)
        self._rebuild()