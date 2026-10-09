"""LRCLIB lyrics fetch + LRC parse + disk cache.

Cache: ~/.cache/spotify-lyrics/<slug>.json, TTL 7 days.
 Polite: sequential calls, ~300ms gap, custom User-Agent, honor Retry-After.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

CACHE_DIR = os.path.expanduser("~/.cache/spotify-lyrics")
TTL_S = 7 * 24 * 3600
UA = {"User-Agent": "spotify-lyrics-cli/0.1 (personal use)"}
_LAST_CALL = [0.0]

TAG_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{2,3}))?\]")
WORD_RE = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{2,3})?>")
META_RE = re.compile(r"\[(ti|ar|al|au|by|re|ve|length):", re.IGNORECASE)
OFFSET_RE = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)
# " - Slowed & Reverbed", "(Sped Up)", "Nightcore", "Remix)", ... uploader edits
_VERSION_SUFFIX_RE = re.compile(
    r"\s*(?:[-–—|/(\[]|\s+)\s*"
    r"(slowed(\s*([+&]|and)\s*reverb(ed)?)?|reverb(ed)?|sped\s*up|nightcore|daycore|"
    r"8d(\s*audio)?|tiktok(\s*version)?|remix|cover|live|acoustic|karaoke|"
    r"instrumental|sped|slowed)\s*[)\]]?\s*$",
    re.IGNORECASE,
)


def base_title(title: str) -> str:
    """Strip uploader-edit suffixes ('- Slowed & Reverbed', '(Sped Up)', ...)."""
    t = (title or "").strip()
    for _ in range(3):
        nt = _VERSION_SUFFIX_RE.sub("", t).strip()
        if nt == t or not nt:
            break
        t = nt
    return t


def _throttle():
    dt = time.monotonic() - _LAST_CALL[0]
    if dt < 0.3:
        time.sleep(0.3 - dt)
    _LAST_CALL[0] = time.monotonic()


def _get_json(url: str) -> tuple[int, object | None, str | None]:
    """Returns (status, payload, retry_after)."""
    _throttle()
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.load(r), None
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        ra = e.headers.get("Retry-After")
        if e.code == 404:
            return 404, None, None
        if e.code in (429, 503) and ra:
            try:
                time.sleep(float(ra))
            except ValueError:
                time.sleep(2)
            return e.code, None, ra
        return e.code, None, ra
    except Exception:
        return -1, None, None


def parse_lrc(raw: str) -> tuple[list[int], list[str]]:
    """Parse LRC text -> (times_ms sorted, texts). Multi-tags expanded."""
    offset = 0
    m = OFFSET_RE.search(raw or "")
    if m:
        try:
            offset = int(m.group(1))
        except ValueError:
            offset = 0
    items: list[tuple[int, str]] = []
    for line in (raw or "").splitlines():
        if META_RE.match(line.strip()):
            continue
        tags = list(TAG_RE.finditer(line))
        if not tags:
            continue
        text = WORD_RE.sub("", TAG_RE.sub("", line)).strip()
        for t in tags:
            mins = int(t.group(1))
            secs = int(t.group(2))
            frac = t.group(3) or "0"
            if len(frac) == 2:  # centiseconds
                ms = int(frac) * 10
            else:  # milliseconds (or single digit -> treat as 100ms steps)
                ms = int((frac + "000")[:3])
            items.append(((mins * 60 + secs) * 1000 + ms + offset, text))
    items.sort(key=lambda p: p[0])
    # stable dedupe of identical timestamps (keep first, e.g. translations)
    seen: set[int] = set()
    times, texts = [], []
    for ms, tx in items:
        if ms in seen:
            continue
        seen.add(ms)
        times.append(ms)
        texts.append(tx)
    return times, texts


def _slug(title: str, artist: str, duration_ms: int) -> str:
    h = hashlib.sha1(f"{title.lower()}|{artist.lower()}|{duration_ms}".encode()).hexdigest()[:16]
    return h


def _cache_get(slug: str) -> dict | None:
    try:
        with open(os.path.join(CACHE_DIR, f"{slug}.json")) as f:
            d = json.load(f)
        if time.time() - d.get("fetched_at", 0) > TTL_S:
            return None
        return d
    except (OSError, ValueError):
        return None


def _cache_put(slug: str, d: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    d["fetched_at"] = time.time()
    with open(os.path.join(CACHE_DIR, f"{slug}.json"), "w") as f:
        json.dump(d, f)


def _pick(arr: list, dur_s: int) -> dict | None:
    def score(r: dict) -> tuple:
        synced = 0 if r.get("syncedLyrics") else 1
        try:
            dd = abs(float(r.get("duration") or 0) - (dur_s or 0))
        except (ValueError, TypeError):
            dd = 999
        return (synced, dd)
    arr = [r for r in arr if isinstance(r, dict)]
    if not arr:
        return None
    arr.sort(key=score)
    return arr[0]


def _full_record(rec: dict) -> dict:
    if rec.get("id"):
        _, full, _ = _get_json(f"https://lrclib.net/api/get/{rec['id']}")
        if isinstance(full, dict):
            return full
    return rec


def fetch_lyrics(title: str, artist: str, album: str = "",
                 duration_ms: int = 0) -> dict:
    """Returns {mode, times, texts, trackName, ...}.

    mode: synced | plain | instrumental | none
    Slowed/sped uploader edits fall back to the base title; synced timing is
    only trusted when durations match (else plain static + approx note).
    """
    slug = _slug(title, artist, duration_ms)
    hit = _cache_get(slug)
    if hit:
        hit["cached"] = True
        return hit

    dur_s = int(round(duration_ms / 1000)) if duration_ms else 0
    q = {"track_name": title, "artist_name": artist}
    if album:
        q["album_name"] = album
    if dur_s:
        q["duration"] = str(dur_s)
    url = "https://lrclib.net/api/get?" + urllib.parse.urlencode(q)
    status, rec, _ = _get_json(url)
    if status == 404 or not isinstance(rec, dict):
        # fallback: search, prefer duration match + synced
        sq = {"track_name": title, "artist_name": artist}
        url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(sq)
        _, arr, _ = _get_json(url)
        rec = _pick(arr, dur_s) if isinstance(arr, list) else None
        if rec is not None:
            rec = _full_record(rec)
        if rec is None:
            # last resort: base title without edit suffixes (slowed/sped/...)
            base = base_title(title)
            if base and base.lower() != title.lower():
                for sq in ({"track_name": base, "artist_name": artist},
                           {"track_name": base}):
                    url = "https://lrclib.net/api/search?" + urllib.parse.urlencode(sq)
                    _, arr, _ = _get_json(url)
                    rec = _pick(arr, dur_s) if isinstance(arr, list) else None
                    if rec is not None:
                        break
                if rec is not None:
                    rec = _full_record(rec)
                    try:
                        rec_dur = float(rec.get("duration") or 0)
                    except (ValueError, TypeError):
                        rec_dur = 0
                    if dur_s and abs(rec_dur - dur_s) > 3:
                        # same words, stretched timing: don't fake-sync
                        rec["syncedLyrics"] = None
                        rec["_approx"] = True

    if not isinstance(rec, dict):
        out = {"mode": "none", "times": [], "texts": []}
        _cache_put(slug, out)
        return out
    if rec.get("instrumental"):
        out = {"mode": "instrumental", "times": [], "texts": []}
        _cache_put(slug, out)
        return out
    synced = rec.get("syncedLyrics")
    if synced:
        times, texts = parse_lrc(synced)
        if times:
            out = {"mode": "synced", "times": times, "texts": texts,
                   "trackName": rec.get("trackName"), "artistName": rec.get("artistName")}
            if rec.get("_approx"):
                out["note"] = "approx"
            _cache_put(slug, out)
            return out
    plain = rec.get("plainLyrics")
    if plain:
        texts = [ln.strip() for ln in plain.splitlines()]
        out = {"mode": "plain", "times": [], "texts": texts}
        if rec.get("_approx"):
            out["note"] = "approx (edit version: static text, timing not trusted)"
        _cache_put(slug, out)
        return out
    out = {"mode": "none", "times": [], "texts": []}
    _cache_put(slug, out)
    return out
