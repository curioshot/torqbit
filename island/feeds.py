"""RSS/Atom reader for the control centre.

Fetching is non-blocking: QNetworkAccessManager does the work and the reply
lands on the Qt event loop, so a slow or dead feed can never stall the
island. Parsing uses QXmlStreamReader (QtCore), so this adds no dependency.

The catalog is grouped by category so the "+" button can offer a browsable
picker, and the user can always add a raw URL instead.
"""
from __future__ import annotations

import time
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
ITEM_TTL_S = 30 * 60            # cache items for half an hour

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._feeds: list[dict] = []      # [{"name","url"}]
        self._items: list[dict] = []      # merged, newest first
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._inflight: set[str] = set()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    # ------------------------------------------------------------ state
    def set_feeds(self, feeds: list[dict]) -> None:
        self._feeds = [f for f in (feeds or [])
                       if isinstance(f, dict) and f.get("url")]
        self._prune_cache()
        self.refresh()

    def feeds(self) -> list[dict]:
        return list(self._feeds)

    def items(self) -> list[dict]:
        return list(self._items)

    def start(self) -> None:
        self._timer.start(REFRESH_MS)

    def stop(self) -> None:
        self._timer.stop()

    def _prune_cache(self) -> None:
        now = time.time()
        self._cache = {k: v for k, v in self._cache.items()
                       if now - v[0] < ITEM_TTL_S}

    # ------------------------------------------------------------ fetch
    def refresh(self) -> None:
        self._prune_cache()
        now = time.time()
        for feed in self._feeds:
            url = feed["url"]
            hit = self._cache.get(url)
            if hit and now - hit[0] < ITEM_TTL_S:
                continue
            if url in self._inflight:
                continue
            self._fetch(feed)

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
            items = parse_feed(body)
            if not items:
                self._show_error(feed, url)
                return
            self._cache[url] = (time.time(), items)
        except Exception as e:
            self._show_error(feed, url, str(e))
            return
        finally:
            try:
                reply.deleteLater()
            except Exception:
                pass
        self._rebuild()

    def _show_error(self, feed: dict, url: str, detail: str = "") -> None:
        """Remember the failure so the list can show it quietly."""
        self._cache[url] = (time.time(), [])
        self._cache.setdefault("__errors__", (time.time(), []))
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
            _, items = hit
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
    """Parse RSS 2.0, RDF or Atom. Returns [{title, link, ts}] newest first.

    Uses ElementTree rather than QXmlStreamReader so this function stays
    unit-testable without a Qt event loop.
    """
    out: list[dict] = []
    try:
        root = ElementTree.fromstring(data)
    except Exception:
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