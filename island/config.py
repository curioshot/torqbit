"""Persistent config for the island widget."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import feeds as feedsmod

APP_NAME = "bot-island"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
EVENTS_FILE = CONFIG_DIR / "events.json"
NOTES_FILE = CONFIG_DIR / "notes.txt"

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
    "theme": "black",          # liquid | white | black | system | minimal
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


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in DEFAULTS:
                    if k in data:
                        cfg[k] = data[k]
    except Exception:
        pass
    # sanitize
    if cfg.get("mode") not in ("island", "corner"):
        cfg["mode"] = "island"
    if cfg.get("corner") not in ("top-left", "top-right", "bottom-left", "bottom-right"):
        cfg["corner"] = "top-right"
    if cfg.get("shape") not in ("blob", "wedge", "gem"):
        cfg["shape"] = "blob"
    if cfg.get("face") not in ("blobatar", "aora", "simple"):
        cfg["face"] = "blobatar"
    if not isinstance(cfg.get("face_name"), str) or not cfg["face_name"].strip():
        cfg["face_name"] = "island-bot"
    if cfg.get("face_bg") not in ("none", "squircle", "circle", "square"):
        cfg["face_bg"] = "none"
    if cfg.get("theme") not in ("liquid", "white", "black", "system", "minimal"):
        cfg["theme"] = "black"  # legacy "dark" maps here too
    # service settings: merge over defaults so new keys appear on old configs
    for key in ("instagram", "spotify"):
        merged = dict(DEFAULTS[key])
        try:
            if isinstance(cfg.get(key), dict):
                merged.update(cfg[key])
        except Exception:
            pass
        cfg[key] = merged
    return cfg


def save(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
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
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_events() -> dict:
    try:
        if EVENTS_FILE.exists():
            data = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): list(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_events(events: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        EVENTS_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_notes() -> str:
    try:
        if NOTES_FILE.exists():
            return NOTES_FILE.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def save_notes(text: str) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        NOTES_FILE.write_text(text, encoding="utf-8")
    except Exception:
        pass
