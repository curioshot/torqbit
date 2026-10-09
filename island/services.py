"""Service backends: Instagram Reels detection + key control, Spotify bridge.

Instagram: watches the active X11 window. When a browser shows Instagram
Reels and the service is on, the bot takes over reel control (next/prev via
XTest key synthesis) — no browser extension needed for keys and buttons.
Wheel interception still needs page JS (marked extension-only in the UI).

Spotify: reuses the vendored spotify/ project (providers/lrc/timing) for
MPRIS now-playing + synced lyrics, and drives its overlay CLI.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parent.parent
SPOTIFY_DIR = BOT_ROOT / "spotify"
SPOTIFY_VENV_PY = SPOTIFY_DIR / ".venv" / "bin" / "python"

if str(SPOTIFY_DIR) not in sys.path:
    sys.path.insert(0, str(SPOTIFY_DIR))


# ---------------- active window (X11) ----------------

def get_active_window() -> tuple[str, str]:
    """(wm_class, title) of the active window, or ('','') on failure."""
    try:
        from Xlib import X
        from Xlib.display import Display
        d = Display()
        root = d.screen().root
        net_active = d.intern_atom("_NET_ACTIVE_WINDOW")
        prop = root.get_full_property(net_active, X.AnyPropertyType)
        if not prop or not prop.value:
            return "", ""
        wid = int(prop.value[0])
        if not wid:
            return "", ""
        w = d.create_resource_object("window", wid)
        title = ""
        try:
            t = w.get_full_property(d.intern_atom("_NET_WM_NAME"), 0)
            if t and t.value:
                title = t.value.decode("utf-8", "replace") if isinstance(t.value, bytes) else str(t.value)
            if not title:
                title = w.get_wm_name() or ""
        except Exception:
            try:
                title = w.get_wm_name() or ""
            except Exception:
                title = ""
        cls = ""
        try:
            c = w.get_wm_class()
            if c:
                cls = " ".join(c)
        except Exception:
            pass
        return cls, title
    except Exception:
        return "", ""


BROWSER_CLASSES = ("chrome", "chromium", "firefox", "brave", "edge", "opera", "vivaldi")


def detect_instagram() -> tuple[bool, str]:
    """(reels_focused, detail). Heuristic: browser window, title mentions instagram/reel."""
    cls, title = get_active_window()
    if not cls:
        return False, "no active window"
    low = (cls + " " + title).lower()
    if "instagram" in low:
        # any surface: Chrome tab, installed web app, or native app window
        return True, (title[:60] or cls)
    browsers = ("chrome", "chromium", "firefox", "brave", "edge",
                "opera", "vivaldi")
    apps = ("crx_", "electron", "instagram")  # PWA windows, wrappers
    if "reel" in low and any(b in low for b in browsers + apps):
        return True, (title[:60] or cls)
    return False, f"{cls.split()[0] if cls else 'unknown window'}"


def focus_and_send_key(window_id: int, keysym: int) -> bool:
    """Focus an X11 window and synthesize one key press+release via XTest."""
    try:
        from Xlib import X
        from Xlib.display import Display
        from Xlib.ext import xtest
        d = Display()
        w = d.create_resource_object("window", int(window_id))
        try:
            w.raise_window()
        except Exception:
            pass
        try:
            w.set_input_focus(X.RevertToParent, X.CurrentTime)
        except Exception:
            pass
        d.sync()
        keycode = d.keysym_to_keycode(keysym)
        if not keycode:
            return False
        xtest.fake_input(d, X.KeyPress, keycode)
        d.sync()
        xtest.fake_input(d, X.KeyRelease, keycode)
        d.sync()
        return True
    except Exception:
        return False


def find_window_by_class(*needles: str) -> int | None:
    """First mapped top-level window whose WM_CLASS matches. None if none."""
    try:
        from Xlib import X
        from Xlib.display import Display
        d = Display()
        root = d.screen().root
        for wid in root.get_full_property(
                d.intern_atom("_NET_CLIENT_LIST"), X.AnyPropertyType).value or []:
            try:
                w = d.create_resource_object("window", int(wid))
                c = w.get_wm_class()
                if c and any(n in " ".join(c).lower() for n in needles):
                    return int(wid)
            except Exception:
                continue
    except Exception:
        pass
    return None


def find_instagram_window() -> int | None:
    """Window id of an Instagram surface (tab, PWA, or native app)."""
    try:
        from Xlib import X
        from Xlib.display import Display
        d = Display()
        root = d.screen().root
        prop = root.get_full_property(d.intern_atom("_NET_CLIENT_LIST"),
                                      X.AnyPropertyType)
        ids = prop.value if prop else []
        browsers = ("chrome", "chromium", "firefox", "brave", "edge",
                    "opera", "vivaldi")
        apps = ("crx_", "electron", "instagram")
        fallback = None
        for wid in ids or []:
            try:
                w = d.create_resource_object("window", int(wid))
                try:
                    c = " ".join(w.get_wm_class() or [])
                except Exception:
                    c = ""
                try:
                    t = w.get_full_property(d.intern_atom("_NET_WM_NAME"), 0)
                    title = (t.value.decode("utf-8", "replace")
                             if t and t.value else "")
                    if not title:
                        title = w.get_wm_name() or ""
                except Exception:
                    title = ""
                low = (c + " " + title).lower()
                if "instagram" in low:
                    return int(wid)
                if ("reel" in low
                        and any(b in low for b in browsers + apps)
                        and fallback is None):
                    fallback = int(wid)
            except Exception:
                continue
        return fallback
    except Exception:
        return None


def send_reel_key(keysym: int) -> tuple[bool, str]:
    """Send next/prev key to the Instagram surface (focus it first so the
    app receives a real key event). Works for Chrome tabs, installed web
    apps, and native app windows alike."""
    wid = find_instagram_window()
    if wid is None:
        wid = find_window_by_class("chrome", "chromium")
    if wid is None:
        return False, "no Instagram window"
    ok = focus_and_send_key(wid, keysym)
    return ok, "sent" if ok else "synthesis failed"


# ---------------- spotify bridge (vendored spotify/ project) ----------------

_providers = None
_lrc = None
_timing = None


def _load_spotify_modules():
    global _providers, _lrc, _timing
    if _providers is not None:
        return _providers, _lrc, _timing
    try:
        import providers as _p  # noqa
        import lrc as _l  # noqa
        import timing as _t  # noqa
        _providers, _lrc, _timing = _p, _l, _t
    except Exception:
        _providers, _lrc, _timing = None, None, None
    return _providers, _lrc, _timing


def spotify_process_running() -> bool:
    try:
        out = subprocess.run(["pgrep", "-x", "spotify"],
                             capture_output=True, timeout=5)
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def spotify_snapshot(strict_spotify: bool = True):
    """TrackSnapshot dict or None. strict: only the Spotify desktop player,
    never a browser's media session. Never raises."""
    p, _l, _t = _load_spotify_modules()
    if p is None:
        return None
    try:
        if strict_spotify:
            for bus in p._mpris_names():
                if bus.rstrip().endswith(".spotify") or bus == "org.mpris.MediaPlayer2.spotify":
                    snap = p._snapshot_from_mpris(bus)
                    if snap:
                        return snap.to_dict()
            return None
        snap = p.get_mpris(prefer_spotify=True)
        return snap.to_dict() if snap else None
    except Exception:
        return None


def fetch_lyrics_async(title: str, artist: str, album: str, duration_ms: int, cb):
    """Fetch lyrics in a thread; cb(record_dict_or_None)."""
    def _run():
        try:
            _p, l, _t = _load_spotify_modules()
            if l is None:
                cb(None)
                return
            rec = l.fetch_lyrics(title, artist, album or "", duration_ms)
            cb(rec)
        except Exception:
            cb(None)
    threading.Thread(target=_run, daemon=True).start()


def parse_lrc_lines(raw: str):
    _p, l, _t = _load_spotify_modules()
    if l is None or not raw:
        return [], []
    try:
        return l.parse_lrc(raw)
    except Exception:
        return [], []


def line_index_at(times, progress_ms: int) -> int:
    _p, _l, t = _load_spotify_modules()
    if t is None:
        return -1
    try:
        return t.index_at(list(times), int(progress_ms))
    except Exception:
        return -1


def overlay_running() -> bool:
    try:
        pidfile = Path.home() / ".cache" / "spotify-lyrics" / "overlay.pid"
        if not pidfile.exists():
            return False
        pid = int(pidfile.read_text().strip().split()[0])
        Path(f"/proc/{pid}").exists()
        return True
    except Exception:
        return False


def overlay_cmd(*args: str) -> tuple[bool, str]:
    py = str(SPOTIFY_VENV_PY) if SPOTIFY_VENV_PY.exists() else sys.executable
    try:
        r = subprocess.run([py, "cli.py", "overlay", *args],
                           cwd=str(SPOTIFY_DIR), capture_output=True,
                           text=True, timeout=20)
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()[:200]
    except Exception as e:
        return False, str(e)[:200]


def overlay_start_detached() -> bool:
    """Launch the (foreground) overlay without blocking. Never raises."""
    py = str(SPOTIFY_VENV_PY) if SPOTIFY_VENV_PY.exists() else sys.executable
    try:
        subprocess.Popen(
            [py, "cli.py", "overlay", "start"],
            cwd=str(SPOTIFY_DIR),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False


def place_overlay_default() -> tuple[int, int] | None:
    """Write the overlay's remembered spot below the island home — but only
    when the user has never placed it (no pos.json). Returns (x, y) or None."""
    try:
        pos_file = Path.home() / ".config" / "spotify-lyrics" / "pos.json"
        if pos_file.exists():
            return None
        sw, sh = 1920, 1080
        try:
            from Xlib.display import Display
            s = Display().screen()
            sw, sh = int(s.width_in_pixels), int(s.height_in_pixels)
        except Exception:
            pass
        try:
            import json as _json
            cfg = _json.loads((Path.home() / ".config" / "bot-island"
                               / "config.json").read_text())
            ix, iy = cfg.get("island_x"), cfg.get("island_y")
        except Exception:
            ix, iy = None, None
        if not isinstance(ix, int) or not isinstance(iy, int):
            ix = (sw - 252) // 2
            iy = 8
        ow, oh = 600, 140
        x = min(max(ix + 252 // 2 - ow // 2, 0), max(sw - ow, 0))
        y = min(iy + 42 + 12, max(sh - oh, 0))
        pos_file.parent.mkdir(parents=True, exist_ok=True)
        import json as _json2
        pos_file.write_text(_json2.dumps({"x": int(x), "y": int(y)}))
        return int(x), int(y)
    except Exception:
        return None


def launch_spotify() -> bool:
    if spotify_process_running():
        return True
    exe = shutil.which("spotify")
    if not exe:
        return False
    try:
        subprocess.Popen([exe], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False
