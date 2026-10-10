"""feeds.py — parsing, cache lifetimes, and the URL trust boundary."""
from __future__ import annotations

import time

import pytest

from island import feeds


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<title>Chan</title>
<item><title>Newest</title><link>https://e.example/1</link>
  <pubDate>Fri, 09 Oct 2026 22:34:00 GMT</pubDate></item>
<item><title>Older</title><link>https://e.example/2</link>
  <pubDate>Fri, 09 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom one</title><link href="https://a.example/1"/>
  <published>2026-10-09T12:00:00Z</published></entry></feed>"""


# ------------------------------------------------------------------ parsing
def test_rss_parses_and_sorts_newest_first():
    out = feeds.parse_feed(RSS)
    assert [i["title"] for i in out] == ["Newest", "Older"]
    assert out[0]["ts"] >= out[1]["ts"]
    assert out[0]["link"] == "https://e.example/1"


def test_atom_parses():
    out = feeds.parse_feed(ATOM)
    assert len(out) == 1
    assert out[0]["title"] == "Atom one"
    assert out[0]["link"] == "https://a.example/1"


def test_garbage_never_raises():
    assert feeds.parse_feed(b"not xml at all") == []
    assert feeds.parse_feed(b"") == []
    assert feeds.parse_root(None) == []


def test_parse_root_and_parse_feed_agree():
    """_done() used to call ElementTree.fromstring twice on the same bytes."""
    root = feeds._parse_xml(RSS)
    assert feeds.parse_root(root) == feeds.parse_feed(RSS)


# -------------------------------------------------------------- URL safety
@pytest.mark.parametrize("bad", [
    "file:///etc/passwd",
    "ftp://example.com/x.png",
    "/etc/passwd",
    "",
    "   ",
    None,
])
def test_non_http_urls_are_rejected(bad):
    assert feeds._safe_http_url(bad) is None


@pytest.mark.parametrize("good", [
    "https://a.example/logo.png",
    "http://a.example/logo.png",
])
def test_http_urls_pass(good):
    assert feeds._safe_http_url(good) == good


def test_feed_supplied_file_url_never_reaches_the_fetcher():
    """A hostile feed must not turn the bot into a local-file reader."""
    hostile = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <image><url>file:///etc/shadow</url></image>
    <item><title>x</title></item></channel></rss>"""
    assert feeds.image_url_from_feed(hostile) is None


def test_feed_supplied_http_url_is_kept():
    body = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <image><url>https://cdn.example/logo.png</url></image>
    <item><title>x</title></item></channel></rss>"""
    assert feeds.image_url_from_feed(body) == "https://cdn.example/logo.png"


def test_image_cache_path_refuses_non_http():
    assert feeds.image_cache_path("file:///etc/passwd") is None


# ---------------------------------------------------------------- lifetimes
def test_refresh_interval_is_shorter_than_the_cache_ttl():
    """These two used to be inverted: 30min cache vs a 10min timer, so
    `refresh()` hit the cache on every tick and never fetched again."""
    refresh_s = feeds.REFRESH_MS / 1000
    assert feeds.ITEM_TTL_S < refresh_s, (
        f"items live {feeds.ITEM_TTL_S}s but refresh runs every "
        f"{refresh_s}s — the feed would never update")


def test_error_ttl_is_shorter_than_the_success_ttl():
    """One transient 500 used to silence a feed for half an hour. A failure
    must be retried sooner than a success would be refetched."""
    assert feeds.ERROR_TTL_S < feeds.ITEM_TTL_S


def test_concurrent_fetch_is_bounded():
    assert feeds.MAX_CONCURRENT_FETCH >= 1
    assert feeds.MAX_CONCURRENT_FETCH <= 16


# ------------------------------------------------------------------- edits
def test_add_feed_normalises_and_dedupes():
    assert feeds.add_feed([], "X", "example.com/rss") == [
        {"name": "X", "url": "https://example.com/rss"}]
    once = feeds.add_feed([], "X", "https://example.com/rss")
    assert feeds.add_feed(once, "X", "https://example.com/rss") == once


def test_remove_feed():
    fs = [{"name": "a", "url": "https://a/"}]
    assert feeds.remove_feed(fs, "https://a/") == []


def test_normalize_respects_an_explicit_empty_list():
    """An empty list means the user removed everything; only a *missing*
    key falls back to the seed feeds."""
    assert feeds.normalize([]) == []
    assert feeds.normalize(None) == [dict(f) for f in feeds.DEFAULT_FEEDS]


def test_ago():
    now = time.time()
    assert feeds.ago(0) == ""
    assert feeds.ago(now - 30) == "now"
    assert feeds.ago(now - 3600) == "1h"
    assert feeds.ago(now - 86400 * 2) == "2d"


def test_mono_colour_is_stable_and_hex():
    c = feeds.mono_colour("BBC World")
    assert c == feeds.mono_colour("BBC World")
    assert c.startswith("#") and len(c) == 7
