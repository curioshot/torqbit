"""Persistent config for the island widget."""
from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from . import feeds as feedsmod

APP_NAME = "bot-island"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
EVENTS_FILE = CONFIG_DIR / "events.json"
NOTES_FILE = CONFIG_DIR / "notes.txt"

# These files live alongside the browser profile that holds live Instagram
# session cookies, so the directory must not be group/world readable.
DIR_MODE = 0o700
FILE_MODE = 0o600

DEFAULTS = {
    "mode": "island",          # "island" | "corner"
    "corner": "top-right",     # "top-left" | "top-right" | "bottom-left" | "bottom-right"
    "island_x": None,          # saved top-left of collapsed island (None = auto top-center)
    "island_y": None,
    "corner_margin": 0,        # px inset from screen corner edges
    "emotion": "02",           # aora-bot emotionId (island mood currency)
    "shape": "blob",           # aora-ball body: blob | wedge | gem
    "face": "blobatar",        # face engine: blobatar | aora | simple
    "face_name": "island-bot", # blobatar creature seed (any string)
    "face_bg": "none",         # blobatar backdrop: none | squircle | circle | square
    "theme": "black",          # liquid | clean_white | white | modern_dark | black | system | minimal
    "instagram": {              # native Reels control (bot-driven browser)
        "service": False,       # master service switch
        "enabled": True,
        "browserFamily": "chromium",  # chromium | firefox
        "appMode": True,        # chrome-less window vs a normal tab
        "wheelEnabled": True,   # one wheel notch == one reel (in-page)
        "invertWheel": False,
        "smooth": True,
        "cooldownMs": 800,
        "wheelThreshold": 30,
        "next_keysym": 83, "next_label": "S",
        "prev_keysym": 87, "prev_label": "W",
        "allowArrows": False,
        "controllerEnabled": True,
        "autoAdvance": True,
        "playbackRate": 1,
        "controllerMini": False,
        "controllerPos": None,
    },
    "spotify": {"service": False, "overlay": False},
    # Control centre (the second panel, opened by double-clicking the island).
    # `feeds` is a plain [{name, url}] list so it stays hand-editable; the
    # seed list only applies until the user edits it.
    "centre": {"enabled": True,
               "feeds": [dict(f) for f in feedsmod.DEFAULT_FEEDS]},
}

# Keys the injected page is allowed to write back through the CDP binding.
# Everything else is bot-owned: a page script must not be able to flip the
# master service switch, retarget the browser, or write arbitrary keys.
PAGE_WRITABLE = frozenset({"playbackRate", "controllerMini", "controllerPos"})

VALID_MODE = ("island", "corner")
VALID_CORNER = ("top-left", "top-right", "bottom-left", "bottom-right")
VALID_SHAPE = ("blob", "wedge", "gem")
VALID_FACE = ("blobatar", "aora", "simple")
VALID_FACE_BG = ("none", "squircle", "circle", "square")
VALID_THEME = ("liquid", "clean_white", "white", "modern_dark", "black", "system", "minimal")


def ensure_dir() -> None:
    """Create the config dir 0700 — it holds the browser session profile."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    try:
        if (CONFIG_DIR.stat().st_mode & 0o077) != 0:
            CONFIG_DIR.chmod(DIR_MODE)
    except OSError:
        pass


def _atomic_write(path: Path, text: str) -> None:
    """Write via temp file + fsync + rename so a crash can't truncate the file.

    Keeps the previous contents as ``path.with_suffix(path.suffix + '.bak')``
    so a bad hand-edit is recoverable.
    """
    ensure_dir()
    try:
        if path.exists():
            try:
                bak = path.with_name(path.name + ".bak")
                bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                try:
                    bak.chmod(FILE_MODE)
                except OSError:
                    pass
            except OSError:
                pass
    except OSError:
        pass

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, FILE_MODE)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _int(value, lo: int, hi: int, fallback: int) -> int:
    """Coerce to a clamped int. Hand-edited JSON can hold anything at all."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(lo, min(hi, n))


def _clampf(value, lo: float, hi: float, fallback: float) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return fallback
    if f != f:  # NaN
        return fallback
    return max(lo, min(hi, f))


def _bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    return fallback


def sanitize(cfg: dict) -> dict:
    """Clamp every field to a type/shape the rest of the app can rely on.

    ``config.json`` is documented as hand-editable, so this has to survive
    hostile input: wrong types, out-of-range numbers, NaN, arbitrary nesting.
    """
    out = dict(DEFAULTS)
    out["centre"] = deepcopy(DEFAULTS["centre"])

    for key in DEFAULTS:
        if key in cfg:
            out[key] = cfg[key]

    if out.get("mode") not in VALID_MODE:
        out["mode"] = "island"
    if out.get("corner") not in VALID_CORNER:
        out["corner"] = "top-right"
    if out.get("shape") not in VALID_SHAPE:
        out["shape"] = "blob"
    if out.get("face") not in VALID_FACE:
        out["face"] = "blobatar"
    if not isinstance(out.get("face_name"), str) or not out["face_name"].strip():
        out["face_name"] = "island-bot"
    if out.get("face_bg") not in VALID_FACE_BG:
        out["face_bg"] = "none"
    if out.get("theme") not in VALID_THEME:
        out["theme"] = "black"  # legacy "dark" maps here too

    for name in ("island_x", "island_y"):
        v = out.get(name)
        # bool is an int subclass — `true` must not become coordinate 1.
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            out[name] = None
        else:
            out[name] = int(v)
    if not isinstance(out.get("emotion"), str):
        out["emotion"] = DEFAULTS["emotion"]
    out["corner_margin"] = _int(out.get("corner_margin"), 0, 400, 0)

    # service settings: merge over defaults so new keys appear on old configs
    for key in ("instagram", "spotify"):
        merged = dict(DEFAULTS[key])
        raw = out.get(key)
        if isinstance(raw, dict):
            merged.update(raw)
        out[key] = merged

    ig = out["instagram"]
    for flag in ("service", "enabled", "appMode", "wheelEnabled", "invertWheel",
                 "smooth", "allowArrows", "controllerEnabled", "autoAdvance",
                 "controllerMini"):
        ig[flag] = _bool(ig.get(flag), DEFAULTS["instagram"][flag])
    ig["browserFamily"] = ig.get("browserFamily")
    if ig["browserFamily"] not in ("chromium", "firefox"):
        ig["browserFamily"] = DEFAULTS["instagram"]["browserFamily"]
    ig["cooldownMs"] = _int(ig.get("cooldownMs"), 100, 3000, 800)
    ig["wheelThreshold"] = _int(ig.get("wheelThreshold"), 5, 200, 30)
    ig["playbackRate"] = _clampf(ig.get("playbackRate"), 0.5, 3.0, 1.0)
    for k in ("next_keysym", "prev_keysym"):
        ig[k] = _int(ig.get(k), 0, 0xFFFFFF, DEFAULTS["instagram"][k])
    for k in ("next_label", "prev_label"):
        if not isinstance(ig.get(k), str) or not ig[k]:
            ig[k] = DEFAULTS["instagram"][k]
    if not isinstance(ig.get("controllerPos"), (str, dict, type(None))):
        ig["controllerPos"] = None

    sp = out["spotify"]
    for flag in ("service", "overlay"):
        sp[flag] = _bool(sp.get(flag), DEFAULTS["spotify"][flag])

    c = out["centre"]
    c["enabled"] = _bool(c.get("enabled"), True)
    feeds = c.get("feeds")
    if not isinstance(feeds, list):
        feeds = []
    clean = []
    for f in feeds:
        if isinstance(f, dict) and isinstance(f.get("url"), str) and f["url"].strip():
            name = f.get("name")
            clean.append({"name": str(name) if name else f["url"].strip(),
                          "url": f["url"].strip()})
    c["feeds"] = clean

    return out


def load() -> dict:
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return sanitize(raw)
        return sanitize({})
    except FileNotFoundError:
        return sanitize({})
    except Exception:
        # Corrupt file: keep it for recovery rather than letting the next
        # save() silently overwrite the user's settings with defaults.
        try:
            raw = CONFIG_FILE.read_text(encoding="utf-8")
            broken = CONFIG_FILE.with_name(CONFIG_FILE.name + ".corrupt")
            broken.write_text(raw, encoding="utf-8")
        except OSError:
            pass
        return sanitize({})


def save(cfg: dict) -> None:
    try:
        ensure_dir()
        # read-modify-write: never drop keys a concurrent (older) writer
        # doesn't know about — e.g. service toggles must survive an
        # unrelated emotion save from another copy.
        try:
            disk = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not isinstance(disk, dict):
                disk = {}
        except Exception:
            disk = {}
        data = dict(disk)
        for k, v in cfg.items():
            if k not in DEFAULTS:
                continue
            old = data.get(k)
            if isinstance(v, dict) and isinstance(old, dict):
                merged = dict(old)
                merged.update(v)
                data[k] = merged
            else:
                data[k] = v
        _atomic_write(CONFIG_FILE, json.dumps(sanitize(data), indent=2))
    except Exception:
        pass


def apply_page_patch(patch: dict) -> dict | None:
    """Apply a settings patch sent by the injected page.

    The CDP binding is reachable by *any* script in the controlled page, so
    this is the trust boundary: only an explicit allow-list of low-risk,
    display-only keys is accepted, each clamped. Returns the accepted subset,
    or None if nothing was allowed.
    """
    if not isinstance(patch, dict):
        return None
    accepted = {}
    for key, value in patch.items():
        if key not in PAGE_WRITABLE:
            continue
        if key == "playbackRate":
            accepted[key] = _clampf(value, 0.5, 3.0, 1.0)
        elif key == "controllerMini":
            accepted[key] = _bool(value, False)
        elif key == "controllerPos":
            if value is None or isinstance(value, (str, dict)):
                accepted[key] = value
    if not accepted:
        return None
    try:
        cfg = load()
        cfg.setdefault("instagram", {}).update(accepted)
        save(cfg)
    except Exception:
        return None
    return accepted


def _clean_events(data) -> dict:
    """Keep only {iso_date: [str, ...]} — a malformed entry must not nuke all."""
    out: dict[str, list[str]] = {}
    if not isinstance(data, dict):
        return out
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        key = _migrate_date_key(key)
        if isinstance(value, str):
            # was list(str) -> per-character garbage
            out.setdefault(key, []).append(value)
            continue
        if not isinstance(value, (list, tuple)):
            continue
        for v in value:
            if isinstance(v, str) and v.strip():
                out.setdefault(key, []).append(v)
    return out


def _migrate_date_key(key: str) -> str:
    """`dd-mm-yyyy` -> `yyyy-mm-dd` so existing events.json keeps working.

    The old format is ambiguous (mm-dd in some locales) and does not sort
    chronologically as a string. Anything unrecognised is passed through.
    """
    parts = key.split("-")
    if len(parts) == 3 and len(parts[0]) == 2 and len(parts[1]) == 2:
        dd, mm, yyyy = parts
        if yyyy.isdigit() and mm.isdigit() and dd.isdigit() and 1 <= int(mm) <= 12:
            return f"{yyyy}-{mm}-{dd}"
    return key


def load_events() -> dict:
    try:
        return _clean_events(json.loads(EVENTS_FILE.read_text(encoding="utf-8")))
    except Exception:
        return {}


def save_events(events: dict) -> None:
    try:
        _atomic_write(EVENTS_FILE, json.dumps(_clean_events(events), indent=2,
                                               ensure_ascii=False))
    except Exception:
        pass


def load_notes() -> str:
    try:
        return NOTES_FILE.read_text(encoding="utf-8")
    except Exception:
        return ""


def save_notes(text: str) -> None:
    try:
        _atomic_write(NOTES_FILE, text if isinstance(text, str) else "")
    except Exception:
        pass