"""Main loop: poll provider -> anchor -> lyrics -> 3 lines -> paint.

Repaints only on: track change, line-index change, move, bg refresh.
"""
from __future__ import annotations

import os
import signal
import sys
import time

PIDFILE = os.path.expanduser("~/.cache/spotify-lyrics/overlay.pid")

_should_show = True
_lock_toggle = False


def _on_usr1(signum, frame):
    global _should_show
    _should_show = not _should_show


def _on_usr2(signum, frame):
    global _lock_toggle
    _lock_toggle = True


def write_pid():
    os.makedirs(os.path.dirname(PIDFILE), exist_ok=True)
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))


def read_pid() -> int | None:
    try:
        with open(PIDFILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def three_lines(lrc: dict, idx: int, snap) -> tuple[str, str, str, str]:
    """Returns (prev, cur, nxt, note)."""
    mode = lrc.get("mode", "none")
    texts = lrc.get("texts", []) or []
    if mode == "synced":
        times = lrc.get("times", [])
        if not times:
            return "", "No synced lines", "", "empty"
        if idx < 0:
            cur = texts[0] if texts else ""
            nxt = texts[1] if len(texts) > 1 else ""
            return "", cur, nxt, "intro"
        prev = texts[idx - 1] if idx > 0 else ""
        cur = texts[idx] if idx < len(texts) else ""
        nxt = texts[idx + 1] if idx + 1 < len(texts) else ""
        return prev, cur, nxt, ""
    if mode == "plain":
        cur = texts[0] if texts else ""
        nxt = texts[1] if len(texts) > 1 else ""
        return "", cur, nxt, "unsynced"
    if mode == "instrumental":
        return "", "♪ Instrumental ♪", "", "instrumental"
    if snap is None:
        return "", "Waiting for Spotify …", "", "waiting"
    return "", "No lyrics found", "", "none"


def is_x11() -> bool:
    import platform
    if platform.system() != "Linux":
        return False
    st = os.environ.get("XDG_SESSION_TYPE", "")
    if st and st != "x11":
        return False
    return bool(os.environ.get("DISPLAY"))


def run_overlay(provider: str = "auto", hidden: bool = False,
                live_bg: float = 0.0, tick_ms: int = 120,
                center: bool = False):
    import providers
    import timing
    from timing import Anchor
    from lrc import fetch_lyrics

    global _should_show, _lock_toggle
    _should_show = not hidden
    signal.signal(signal.SIGUSR1, _on_usr1)
    signal.signal(signal.SIGUSR2, _on_usr2)
    write_pid()
    try:
        from spotify_auth import load_tokens
        has_token = bool(load_tokens() and load_tokens().get("refresh_token"))
    except Exception:
        has_token = False
    use_web = (provider == "web") or (provider == "auto" and has_token)
    local_provider = "auto" if provider == "auto" else provider
    if use_web:
        print("[overlay] source: Spotify Web API (5s poll + interpolation)")
    else:
        print(f"[overlay] source: local ({local_provider}, 1s poll, no login)")

    if is_x11():
        from overlay_x11 import X11Overlay, POS_FILE
        if center:
            try:
                os.remove(POS_FILE)
            except OSError:
                pass
        from grab import grab_region
        from PIL import Image

        ov = X11Overlay()
        if _should_show:
            ov.show()
        print("[overlay] X11 ARGB transparent window. Drag to move. "
              "SIGUSR1 toggles, SIGUSR2 locks.")

        def paint(prev, cur, nxt):
            lines = [(prev, ov.f_ctx, 215), (cur, ov.f_cur, 255),
                     (nxt, ov.f_ctx, 215)]
            W, H, _, _, _ = ov._layout(lines)
            x, y = ov.geom()
            was = ov.refresh_transient_hide()
            try:
                bg = grab_region(x, y, W, H)
            except Exception as e:
                print(f"[overlay] grab failed ({e}); using dark fallback")
                bg = Image.new("RGB", (W, H), (20, 20, 20))
            data = ov.render(lines, bg)
            if _should_show and not ov.visible:
                ov.show()
            elif not _should_show and ov.visible:
                ov.hide()
            if ov.visible:
                ov.present(data)

        def loop_body(ctx):
            global _lock_toggle
            if ov.pump():
                paint(ctx["prev"], ctx["cur"], ctx["nxt"])  # re-sample after move
            if _lock_toggle:
                _lock_toggle = False
                ov.set_locked(not ov.locked)
                print(f"[overlay] {'locked (click-through)' if ov.locked else 'unlocked (draggable)'}")
            if _should_show and not ov.visible:
                ov.show()
                paint(ctx["prev"], ctx["cur"], ctx["nxt"])
            elif not _should_show and ov.visible:
                ov.hide()

        def cleanup():
            ov.close()
    else:
        from overlay_tk import TkOverlay, POS_FILE as TK_POS
        if center:
            try:
                os.remove(TK_POS)
            except OSError:
                pass
        from grab import grab_region
        from inverse import avg_color, inverse_fg

        ov = TkOverlay()
        print("[overlay] fallback window (tkinter). Drag to move.")
        if _should_show:
            ov.show()

        def paint(prev, cur, nxt):
            ov.hide()  # withdraw for clean sample
            ov.root.update()
            try:
                x, y, w, h = ov.geom_center()
                bg = grab_region(x, y, max(w, 300), 300)
                styled = []
                for text, size, bold in ((prev, 13, False), (cur, 19, True),
                                        (nxt, 13, False)):
                    chars = []
                    if text:
                        cw = max(1, bg.width // max(1, len(text)))
                        for i, ch in enumerate(text):
                            try:
                                avg = avg_color(bg, (i * cw, 0, (i + 1) * cw, bg.height))
                            except Exception:
                                avg = (16, 16, 16)
                            fill, _ = inverse_fg(avg)
                            chars.append((ch, fill))
                    styled.append((text, chars, size, bold))
            except Exception as e:
                print(f"[overlay] grab failed ({e})")
                styled = [(t, [(c, (240, 240, 240)) for c in t], s, b)
                          for t, s, b in ((prev, 13, False), (cur, 19, True),
                                          (nxt, 13, False))]
            ov.show_lines(styled)
            if _should_show and not ov.visible:
                ov.show()

        def loop_body(ctx):
            global _lock_toggle
            ov.pump()
            if _lock_toggle:
                _lock_toggle = False
                ov.set_locked(not ov.locked)
            if _should_show and not ov.visible:
                ov.show()
                paint(ctx["prev"], ctx["cur"], ctx["nxt"])
            elif not _should_show and ov.visible:
                ov.hide()

        def cleanup():
            ov.close()

    anchor = Anchor(mono=time.monotonic())
    lrc = {"mode": "none", "times": [], "texts": []}
    idx = -999
    ctx = {"prev": "", "cur": "Waiting for Spotify …", "nxt": ""}
    last_poll = 0.0
    last_bg = time.monotonic()
    poll_iv = 5.0 if use_web else 1.0
    try:
        paint(ctx["prev"], ctx["cur"], ctx["nxt"])
        while True:
            now = time.monotonic()
            if now - last_poll >= poll_iv:
                last_poll = now
                try:
                    snap = providers.get_web() if use_web \
                        else providers.get_snapshot(local_provider)
                except Exception as e:
                    print(f"[overlay] provider error: {e}")
                    snap = None
                if snap is None:
                    if lrc.get("mode") != "waiting":
                        lrc = {"mode": "none", "times": [], "texts": []}
                        idx = -999
                        p, c, n, _ = three_lines(lrc, -1, None)
                        ctx = {"prev": p, "cur": c, "nxt": n}
                        paint(p, c, n)
                else:
                    if snap.track_key != anchor.track_key:
                        try:
                            lrc = fetch_lyrics(snap.title, snap.artist,
                                               snap.album, snap.duration_ms)
                        except Exception as e:
                            print(f"[overlay] lyrics error: {e}")
                            lrc = {"mode": "none", "times": [], "texts": []}
                        idx = -999
                        print(f"[overlay] ♪ {snap.title} — {snap.artist} "
                              f"[{lrc.get('mode')}]"
                              f"{' (' + lrc['note'] + ')' if lrc.get('note') else ''}")
                    if timing.needs_reanchor(anchor, snap.progress_ms,
                                            snap.is_playing, snap.track_key):
                        anchor = Anchor(snap.progress_ms, now,
                                        snap.is_playing, snap.track_key)
            est = timing.estimate_ms(anchor)
            if lrc.get("mode") == "synced":
                i2 = timing.index_at(lrc["times"], est)
                if i2 != idx:
                    idx = i2
                    p, c, n, _ = three_lines(lrc, idx, anchor)
                    ctx = {"prev": p, "cur": c, "nxt": n}
                    paint(p, c, n)
                    last_bg = now
            if live_bg and now - last_bg >= live_bg:
                last_bg = now
                paint(ctx["prev"], ctx["cur"], ctx["nxt"])
            loop_body(ctx)
            time.sleep(max(0.02, tick_ms / 1000.0))
    except KeyboardInterrupt:
        print("\noverlay stopped.")
    finally:
        try:
            cleanup()
        except Exception:
            pass
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
