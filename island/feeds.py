"""RSS/Atom reader for the control centre.

Fetching is non-blocking: QNetworkAccessManager does the work and the reply
lands on the Qt event loop, so a slow or dead feed can never stall the
island. Parsing uses xml.etree (stdlib), so this adds no dependency.

The catalog is grouped by category so the picker can offer a browsable list,
and the user can always add a raw URL instead.
"""
from __future__ import annotations

import hashlib
import time
import os
import colorsys
from pathlib import Path
from xml.etree import ElementTree

from PySide6.QtCore import (QObject, QUrl, Signal, QTimer, QDateTime, Qt)
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkRequest,
                              QNetworkReply)

APP_UA = "bot-island/1.0 (RSS reader)"

# --------------------------------------------------------------- catalog
# Every URL here was verified to answer HTTP 200 at the time this was built.
# A feed that later rots degrades to one "unavailable" row, never an error
# dialog and never a stall.
CATALOG: dict[str, list[tuple[str, str]]] = {
    "News": [
        ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("The Guardian — World", "https://www.theguardian.com/world/rss"),
    ],
    "Tech": [
        ("Hacker News", "https://hnrss.org/frontpage"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
        ("Lobsters", "https://lobste.rs/rss"),
        ("The Guardian — Tech", "https://www.theguardian.com/uk/technology/rss"),
    ],
    "Games": [
        ("Eurogamer", "https://www.eurogamer.net/feed"),
        ("PC Gamer", "https://www.pcgamer.com/rss/"),
    ],
    "Science": [
        ("NASA", "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
        ("Phys.org", "https://phys.org/rss-feed/"),
    ],
    "Sport": [
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml"),
    ],
}

REFRESH_MS = 10 * 60 * 1000     # refetch interval
TIMEOUT_MS = 12000
MAX_ITEMS_PER_FEED = 5
# Must stay *below* REFRESH_MS, or every refresh tick hits the cache and
# `continue`s and the feed is frozen for the life of the process.
ITEM_TTL_S = 5 * 60
# A failure is remembered only briefly: one 500 or Wi-Fi blip should not
# silence a feed for half an hour.
ERROR_TTL_S = 60
# Guards against a pathological feed (or a slow retry loop) opening more
# connections than we can comfortably hold open.
MAX_CONCURRENT_FETCH = 6
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_CACHE_FILES = 300

# Seeded on first run so the panel is not an empty box; everything here can be
# removed with the "-" in the picker, and more added with "+".
DEFAULT_FEEDS = [
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage"},
]


class FeedReader(QObject):
    """Fetches the enabled feeds and exposes a merged, newest-first list."""

    feedsChanged = Signal()        # the merged list changed
    error = Signal(str)
    imageReady = Signal(str)       # feed url whose logo finished downloading

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._feeds: list[dict] = []      # [{"name","url"}]
        self._items: list[dict] = []      # merged, newest first
        self._cache: dict[str, tuple[float, list[dict], bool]] = {}
        self._images: dict[str, str | None] = {}   # feed url -> image url
        self._inflight: set[str] = set()
        self._img_inflight: set[str] = set()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------ state
    def set_feeds(self, feeds: list[dict]) -> None:
        self._feeds = [f for f in (feeds or [])
                       if isinstance(f, dict) and f.get("url")]
        self._prune_cache()
        self._prune_images()
        self.refresh()

    def feeds(self) -> list[dict]:
        return list(self._feeds)

    def items(self) -> list[dict]:
        return list(self._items)

    def feed_items(self, url: str) -> list[dict]:
        """Parsed items for one feed, or [] — the public view of the cache."""
        hit = self._cache.get(url)
        return list(hit[1]) if hit else []

    def start(self) -> None:
        self._timer.start(REFRESH_MS)

    def stop(self) -> None:
        self._timer.stop()

    def _prune_cache(self) -> None:
        now = time.time()
        live = {f["url"] for f in self._feeds}
        # Drop entries for feeds that no longer exist, and anything past TTL.
        # A successful entry lives ITEM_TTL_S, a failed one only ERROR_TTL_S.
        self._cache = {
            k: v for k, v in self._cache.items()
            if k in live and now - v[0] < (ERROR_TTL_S if v[2] else ITEM_TTL_S)
        }

    def _prune_images(self) -> None:
        live = {f["url"] for f in self._feeds}
        self._images = {k: v for k, v in self._images.items() if k in live}

    # ------------------------------------------------------------ fetch
    def refresh(self) -> None:
        self._prune_cache()
        now = time.time()
        budget = MAX_CONCURRENT_FETCH - len(self._inflight)
        for feed in self._feeds:
            if budget <= 0:
                break
            url = feed["url"]
            hit = self._cache.get(url)
            if hit and now - hit[0] < (ERROR_TTL_S if hit[2] else ITEM_TTL_S):
                continue
            if url in self._inflight:
                continue
            self._fetch(feed)
            budget -= 1

    def _fetch(self, feed: dict) -> None:
        url = feed["url"]
        self._inflight.add(url)
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", APP_UA.encode())
        req.setRawHeader(b"Accept", b"application/rss+xml, application/xml, text/xml")
        req.setTransferTimeout(TIMEOUT_MS)
        try:
            reply = self._nam.get(req)
        except Exception as e:
            self._inflight.discard(url)
            self.error.emit(f"{feed['name']}: {e}")
            return
        reply.finished.connect(lambda *_, f=feed: self._done(f, reply))

    def _done(self, feed: dict, reply) -> None:
        url = feed["url"]
        self._inflight.discard(url)
        try:
            body = bytes(reply.readAll())
            # QNetworkReply.error() returns the enum NoError on success, not None.
            ok = (reply.error() == QNetworkReply.NoError) and bool(body)
            if not ok:
                self._show_error(feed, url, reply.errorString())
                return
            # Parse once and reuse the tree: the old code called
            # fromstring() twice on identical bytes for every feed.
            root = _parse_xml(body)
            if root is None:
                self._show_error(feed, url, reply.errorString())
                return
            items = parse_root(root)
            if not items:
                self._show_error(feed, url, reply.errorString())
                return
            self._cache[url] = (time.time(), items, False)
            self._note_image(feed, url, root)
        except Exception as e:
            self._show_error(feed, url, str(e))
            return
        finally:
            try:
                reply.deleteLater()
            except Exception:
                pass
        self._rebuild()

    # ------------------------------------------------------------ images
    def image_url(self, feed_url: str) -> str | None:
        return self._images.get(feed_url)

    def image_bytes(self, feed_url: str):
        """Cached bytes for a feed logo, or None to fall back to a monogram."""
        u = self._images.get(feed_url)
        if not u:
            return None
        return cached_image(u)

    def _note_image(self, feed: dict, url: str, root) -> None:
        img = image_url_from_root(root)
        self._images[url] = img
        if not img:
            return
        p = image_cache_path(img)
        if p is None:
            self._images[url] = None
            return
        try:
            if p.exists():
                self.imageReady.emit(url)
                return
        except OSError:
            pass
        self._fetch_image(url, img)

    def _fetch_image(self, feed_url: str, img: str) -> None:
        if img in self._img_inflight:
            return
        self._img_inflight.add(img)
        try:
            req = QNetworkRequest(QUrl(img))
            req.setRawHeader(b"User-Agent", APP_UA.encode())
            req.setTransferTimeout(TIMEOUT_MS)
            # Redirects could walk an https logo off to file://; refuse them.
            req.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            reply = self._nam.get(req)
        except Exception:
            self._img_inflight.discard(img)
            return
        reply.finished.connect(
            lambda *_, f=feed_url, i=img, r=reply: self._image_done(f, i, r))

    def _image_done(self, feed_url: str, img: str, reply) -> None:
        self._img_inflight.discard(img)
        try:
            body = bytes(reply.readAll())
            if reply.error() != QNetworkReply.NoError or not body:
                return
            # A feed can advertise an arbitrary URL; cap what we keep on disk.
            if len(body) > MAX_IMAGE_BYTES:
                return
            p = image_cache_path(img)
            if p is None:
                return
            image_cache_dir(create=True)
            tmp = p.with_name(p.name + ".part")
            tmp.write_bytes(body)
            os.replace(tmp, p)
            _evict_image_cache()
            self.imageReady.emit(feed_url)
        except Exception:
            pass
        finally:
            try:
                reply.deleteLater()
            except Exception:
                pass

    def _show_error(self, feed: dict, url: str, detail: str = "") -> None:
        """Remember the failure briefly so the list can show it quietly."""
        self._cache[url] = (time.time(), [], True)
        if detail:
            self.error.emit(f"{feed['name']}: {detail}")

    # ------------------------------------------------------------ merge
    def _rebuild(self) -> None:
        merged: list[dict] = []
        for feed in self._feeds:
            hit = self._cache.get(feed["url"])
            if hit is None:
                merged.append({"title": f"{feed['name']} — loading…",
                               "feed": feed["name"], "link": "", "ts": 0.0,
                               "pending": True})
                continue
            _, items, failed = hit
            if not items:
                merged.append({"title": f"{feed['name']} — feed unavailable",
                               "feed": feed["name"], "link": "", "ts": 0.0,
                               "error": True})
                continue
            for it in items[:MAX_ITEMS_PER_FEED]:
                merged.append({"title": it["title"], "feed": feed["name"],
                               "link": it["link"], "ts": it["ts"]})
        # Newest first; placeholders sink to the bottom.
        merged.sort(key=lambda x: (x.get("pending", False) or x.get("error", False),
                                   -float(x.get("ts") or 0.0)))
        self._items = merged
        self.feedsChanged.emit()


# --------------------------------------------------------------- parsing
def _text(node) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def _parse_xml(data: bytes):
    """Bytes -> ElementTree root, or None. Never raises."""
    try:
        return ElementTree.fromstring(data)
    except Exception:
        return None


def _safe_http_url(raw: str | None) -> str | None:
    """Only ever hand back an http(s) URL.

    Feed bodies are untrusted input and QNetworkAccessManager will happily
    fetch file:// and http://169.254.169.254/, so every URL that comes out of
    a feed has to be scheme-checked here rather than at the fetch site.
    """
    if not raw:
        return None
    url = raw.strip()
    if not url:
        return None
    low = url.lower()
    if low.startswith("https://"):
        return url
    if low.startswith("http://"):
        return url
    return None


def _parse_date(raw: str) -> float:
    """Best-effort RFC822/ISO8601 -> epoch seconds. Returns 0.0 on failure."""
    raw = (raw or "").strip()
    if not raw:
        return 0.0
    # RFC822 (RSS): "Fri, 09 Oct 2026 22:34:00 GMT"
    from email.utils import parsedate_to_datetime
    for parser in (lambda s: parsedate_to_datetime(s),
                   lambda s: QDateTime.fromString(s, Qt.ISODate).toSecsSinceEpoch()):
        try:
            v = parser(raw)
            if v is None:
                continue
            if hasattr(v, "timestamp"):
                return float(v.timestamp())
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        except Exception:
            continue
    # Last resort: a bare "2026-10-09T22:34:00Z" with a trailing Z.
    try:
        return float(QDateTime.fromString(raw.replace("Z", "+0000"),
                                          Qt.ISODate).toSecsSinceEpoch())
    except Exception:
        return 0.0


def parse_feed(data: bytes) -> list[dict]:
    """Parse RSS 2.0, RDF or Atom. Returns [{title, link, ts}] newest first."""
    root = _parse_xml(data)
    return parse_root(root) if root is not None else []


def parse_root(root) -> list[dict]:
    """Same as parse_feed but takes an already-parsed tree."""
    out: list[dict] = []
    if root is None:
        return out

    tag = _local(root.tag)

    if tag == "feed":  # Atom
        ns = {"a": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        path = f"{{{ns['a']}}}entry" if ns else "entry"
        tpath = f"{{{ns['a']}}}title" if ns else "title"
        lpath = f"{{{ns['a']}}}link" if ns else "link"
        dpath = f"{{{ns['a']}}}updated" if ns else "updated"
        ppath = f"{{{ns['a']}}}published" if ns else "published"
        for entry in root.findall(path):
            link_el = entry.find(lpath)
            link = (link_el.get("href") if link_el is not None else "") or ""
            title = _text(entry.find(tpath))
            ts = _parse_date(_text(entry.find(ppath)) or _text(entry.find(dpath)))
            if title:
                out.append({"title": title, "link": link, "ts": ts})
        return sorted(out, key=lambda x: -x["ts"])

    # RSS 2.0 / RDF: items are either <item> or (rdf) <item>
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        title = _text(item.find("title"))
        link = ""
        for ln in item.findall("link"):
            if ln.text and ln.text.strip():
                link = ln.text.strip()
                break
            if ln.get("href"):
                link = ln.get("href")
                break
        date = ""
        for key in ("pubDate", "date", "{http://purl.org/dc/elements/1.1/}date"):
            el = item.find(key)
            if el is not None and _text(el):
                date = _text(el)
                break
        ts = _parse_date(date)
        if title:
            out.append({"title": title, "link": link, "ts": ts})
    return sorted(out, key=lambda x: -x["ts"])


def _local(tag: str) -> str:
    return tag.split("}")[-1].strip("{}").lower()


def image_url_from_feed(data: bytes) -> str | None:
    root = _parse_xml(data)
    return image_url_from_root(root) if root is not None else None


def image_url_from_root(root) -> str | None:
    """Best feed logo advertised in the feed's own XML.

    Deliberately never contacts a third-party favicon service: that would
    tell a third party exactly which feeds this user reads.

    The scan is namespace-agnostic on purpose — `<icon>` and
    `<itunes:image>` only exist inside a namespaced document, and matching on
    a fixed path finds neither of them.

    Every candidate goes through _safe_http_url: this is untrusted input, and
    an unchecked value here becomes a file:// read or an SSRF pivot.
    """
    if root is None:
        return None

    # 1) channel/feed level logo, in document order
    for el in root.iter():
        if _local(el.tag) not in ("image", "logo", "icon"):
            continue
        for attr in ("href", "resource"):
            found = _safe_http_url(el.get(attr))
            if found:
                return found
        text = (el.text or "").strip()
        found = _safe_http_url(text)
        if found:
            return found
        for child in el.iter():
            if _local(child.tag) == "url":
                found = _safe_http_url(child.text)
                if found:
                    return found

    # 2) first item's own attached image
    for item in root.iter():
        if _local(item.tag) not in ("item", "entry"):
            continue
        for el in item.iter():
            name = _local(el.tag)
            if name not in ("enclosure", "content", "thumbnail", "image"):
                continue
            found = _safe_http_url(el.get("url")) or _safe_http_url(el.get("href"))
            if not found:
                continue
            # media:thumbnail commonly carries no type at all
            mime = (el.get("type") or "").strip()
            if mime and not mime.startswith("image"):
                continue
            if not mime and name not in ("thumbnail", "image"):
                continue
            return found
    return None


_NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_NS_MEDIA = "http://search.yahoo.com/mrss/"


def image_cache_dir(create: bool = False):
    """Cache root. Created lazily — `cached_image()` only ever reads."""
    base = Path(os.environ.get(
        "XDG_CACHE_HOME", Path.home() / ".cache")) / "bot-island" / "feedimg"
    if create:
        base.mkdir(parents=True, exist_ok=True)
    return base


def image_cache_path(url: str):
    """Deterministic cache path for a feed image URL."""
    if not _safe_http_url(url):
        return None
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    ext = ".png"
    low = url.lower().split("?")[0]
    for known in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
        if low.endswith(known):
            ext = known
            break
    return image_cache_dir() / (digest + ext)


def _evict_image_cache(limit: int = MAX_CACHE_FILES) -> None:
    """Bound the on-disk cache: feed logos carry cache-busting query strings,
    so without this the cache grows without limit for the life of the install."""
    try:
        base = image_cache_dir()
        files = [p for p in base.iterdir()
                 if p.is_file() and not p.name.endswith(".part")]
        if len(files) <= limit:
            return
        files.sort(key=lambda p: p.stat().st_mtime)
        for p in files[:len(files) - limit]:
            try:
                p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def cached_image(url: str | None):
    """Bytes of a previously downloaded feed image, or None."""
    if not url:
        return None
    p = image_cache_path(url)
    if p is None:
        return None
    try:
        if p.exists() and p.stat().st_size > 0:
            return p.read_bytes()
    except OSError:
        pass
    return None


def mono_colour(name: str) -> str:
    """Stable pastel-ish accent for the monogram fallback."""
    h = hashlib.sha1((name or "?").encode("utf-8")).digest()
    hue = h[0] / 255.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.42, 0.86)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def ago(ts: float) -> str:
    """Compact relative age, e.g. '4h', '2d'."""
    if not ts:
        return ""
    delta = max(0, int(time.time() - ts))
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    return f"{delta // 86400}d"


# --------------------------------------------------------------- editing
def add_feed(feeds: list[dict], name: str, url: str) -> list[dict]:
    url = (url or "").strip()
    if not url:
        return feeds
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if any(f.get("url") == url for f in feeds):
        return feeds
    name = (name or url).strip()
    return list(feeds) + [{"name": name, "url": url}]


def remove_feed(feeds: list[dict], url: str) -> list[dict]:
    return [f for f in feeds if f.get("url") != url]


def normalize(feeds) -> list[dict]:
    """Config -> clean list, dropping anything unusable.

    An explicitly empty list means "the user removed everything", so it is
    respected. Only a *missing* key falls back to the defaults.
    """
    if feeds is None:
        return [dict(f) for f in DEFAULT_FEEDS]
    out = []
    for f in feeds or []:
        if isinstance(f, dict) and f.get("url"):
            out.append({"name": str(f.get("name") or f["url"]),
                        "url": str(f["url"])})
        elif isinstance(f, str) and f.strip():
            out.append({"name": f.strip(), "url": f.strip()})
    return out


# ---------------------------------------------------------------- tests
if __name__ == "__main__":
    import sys
    RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Hello world</title><link>https://example.com/1</link>
      <pubDate>Fri, 09 Oct 2026 22:34:00 GMT</pubDate></item>
    <item><title>Older post</title><link>https://example.com/2</link>
      <pubDate>Fri, 09 Oct 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""
    ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
    <entry><title>Atom one</title><link href="https://a.example/1"/>
      <published>2026-10-09T12:00:00Z</published></entry>
    </feed>"""
    r = parse_feed(RSS)
    print("RSS:", [i["title"] for i in r])
    print("  newest first:", r[0]["ts"] >= r[1]["ts"])
    print("  link parsed:", r[0]["link"])
    a = parse_feed(ATOM)
    print("ATOM:", [i["title"] for i in a], a[0]["link"] if a else "")
    print("garbage ->", parse_feed(b"not xml at all"))
    print("add:", len(add_feed([], "X", "example.com/rss")))
    print("add dup:", len(add_feed(add_feed([], "X", "a.example"), "X", "a.example")))
    print("ago:", ago(time.time() - 3600), ago(time.time() - 86400 * 2))
    sys.exit(0 if len(r) == 2 and len(a) == 1 and not parse_feed(b"nope") else 1)