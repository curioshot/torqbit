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
    """First letter of the feed name on a stable per-feed colour.

    Rendered on a solid base in the section's pane colour — fully opaque,
    like everything else in the UI.
    """

    def __init__(self, name: str, bg: str = "#151519", parent=None):
        super().__init__(parent)
        self.setFixedSize(MONO_PX, MONO_PX)
        self._name = name or "?"
        self._bg = bg
        self.setPixmap(self._render())

    def set_background(self, bg: str) -> None:
        if bg != self._bg:
            self._bg = bg
            self.setPixmap(self._render())

    def _render(self) -> QPixmap:
        pm = QPixmap(MONO_PX, MONO_PX)
        pm.fill(QColor(self._bg))
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
        self._dots: list[QLabel] = []
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
        self._mono: Monogram | None = None
        self._pic_is_mono = False
        if pm.isNull() or pm.width() <= 1:
            self._mono = Monogram(name, self._pal.get("pane", "#151519"))
            self.pic.setPixmap(self._mono.pixmap())
            self._pic_is_mono = True
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
            # A container widget per row (not a bare layout): word-wrapped
            # labels inside bare nested layouts miscompute their height and
            # paint on top of each other. The container gives Qt a real
            # widget height to work with.
            cell = QWidget()
            row = QHBoxLayout(cell)
            row.setContentsMargins(0, 1, 0, 1)
            row.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(6, 6)
            dot.setPixmap(self._dot_pixmap(name))
            self._dots.append(dot)
            row.addWidget(dot, 0, Qt.AlignTop)
            txt = QLabel(it.get("title", ""))
            txt.setWordWrap(True)
            txt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            txt.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            txt.setToolTip(it.get("link", "") or name)
            self._texts.append(txt)
            row.addWidget(txt, 1)
            age = QLabel(feedsmod.ago(it.get("ts") or 0.0))
            age.setFixedWidth(34)
            age.setAlignment(Qt.AlignRight | Qt.AlignTop)
            self._ages.append(age)
            row.addWidget(age, 0, Qt.AlignTop)
            lay.addWidget(cell)
        lay.addSpacing(HEAD_GAP)

    def set_image(self, image_bytes) -> None:
        """Swap a placeholder monogram for the real picture once it lands."""
        if not image_bytes:
            return
        pm = QPixmap()
        pm.loadFromData(image_bytes)
        if pm.isNull() or pm.width() <= 1:
            return
        self._pic_is_mono = False
        self.pic.setPixmap(pm.scaled(
            IMAGE_PX, IMAGE_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _dot_pixmap(self, name: str) -> QPixmap:
        pm = QPixmap(6, 6)
        pm.fill(QColor(self._pal.get("pane", "#151519") if self._pal else "#151519"))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(feedsmod.mono_colour(name)))
        p.drawEllipse(0, 0, 6, 6)
        p.end()
        return pm

    def apply_palette(self, pal: dict) -> None:
        self._pal = dict(pal)
        ink = pal.get("text", pal.get("ink", "#f2efe8"))
        sub = pal.get("sub", "#a8a49d")
        muted = pal.get("muted", "#6f6c68")
        pane = pal.get("pane", "#151519")
        self.title.setStyleSheet(
            f"color:{ink}; font-size:12px; font-weight:700; background:{pane};")
        self.rule.setStyleSheet(f"background:{muted}; border:none;")
        for t in self._texts:
            t.setStyleSheet(
                f"color:{sub}; font-size:10px; background:{pane};")
        for a in self._ages:
            a.setStyleSheet(
                f"color:{muted}; font-size:8px; background:{pane};")
        # Re-render the solid icon bases in the new pane colour so no
        # per-pixel alpha is left anywhere in the feed column.
        for d in self._dots:
            d.setPixmap(self._dot_pixmap(self._name))
        if self._pic_is_mono and self._mono is not None:
            self._mono.set_background(pane)
            self.pic.setPixmap(self._mono.pixmap())


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
        self.scroll.viewport().setAutoFillBackground(True)

        self.body = QWidget()
        # Opaque strip: solid canvas so text never floats over wallpaper.
        self.body.setAutoFillBackground(True)
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(8, 8, 8, 0)
        self.body_lay.setSpacing(0)
        self.body_lay.addStretch(1)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll, 1)

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
        pane = pal.get("pane", "#151519")
        card = pal.get("bg", "#101013")
        border = pal.get("btn_border", "#34343c")
        # Viewports ignore stylesheets on some styles — pin the palette too
        # so the scroll area never flashes default light-grey/white.
        try:
            from PySide6.QtGui import QPalette, QColor
            vp_pal = self.scroll.viewport().palette()
            vp_pal.setColor(QPalette.Base, QColor(pane))
            vp_pal.setColor(QPalette.Window, QColor(pane))
            self.scroll.viewport().setPalette(vp_pal)
            bp = self.body.palette()
            bp.setColor(QPalette.Base, QColor(pane))
            bp.setColor(QPalette.Window, QColor(pane))
            self.body.setPalette(bp)
        except Exception:
            pass
        self.body.setStyleSheet(f"background: {pane};")
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background: {pane}; border: 1px solid {border};"
            f" border-radius: 8px; }}"
            f"QScrollBar:vertical {{ background: {pane}; width: 10px; margin: 2px; }}"
            f"QScrollBar::handle:vertical {{ background: {border};"
            f" border-radius: 5px; min-height: 28px; }}"
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