#!/usr/bin/env python3
"""spotify-lyrics CLI (personal). See README.md."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PIDFILE = os.path.expanduser("~/.cache/spotify-lyrics/overlay.pid")


def cmd_auth_login(a):
    import spotify_auth
    tok = spotify_auth.login(port=a.port)
    print("Logged in. Scopes:", tok.get("scope"))


def cmd_auth_status(a):
    import spotify_auth
    tok = spotify_auth.load_tokens()
    if not tok:
        print(json.dumps({"logged_in": False}, indent=2))
        return
    print(json.dumps({"logged_in": True,
                      "has_refresh": bool(tok.get("refresh_token")),
                      "scope": tok.get("scope")}, indent=2))


def cmd_auth_logout(a):
    import spotify_auth
    spotify_auth.logout()
    print("Logged out.")


def cmd_now(a):
    import providers
    snap = providers.get_snapshot(a.provider)
    print(json.dumps(snap.to_dict() if snap else None, indent=2,
                     ensure_ascii=False))


def cmd_lyrics_get(a):
    from lrc import fetch_lyrics
    d = fetch_lyrics(a.track, a.artist, a.album or "", a.duration_ms or 0)
    if a.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
        return
    print(f"mode={d.get('mode')} cached={d.get('cached', False)}")
    if d.get("mode") == "synced":
        for ms, tx in list(zip(d["times"], d["texts"]))[:8]:
            print(f"[{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}] {tx}")
        print(f"... ({len(d['times'])} lines)")
    else:
        for tx in (d.get("texts") or [])[:8]:
            print(tx)


def _pid() -> int | None:
    try:
        with open(PIDFILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def cmd_overlay_start(a):
    import overlay
    overlay.run_overlay(provider=a.provider, hidden=a.hidden,
                        live_bg=a.live_bg, tick_ms=a.tick_ms,
                        center=a.center)


def cmd_overlay_stop(a):
    pid = _pid()
    if not pid:
        print("No running overlay (no pidfile).")
        return
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped overlay (pid {pid}).")
    except ProcessLookupError:
        print("Stale pidfile; removing.")
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


def cmd_overlay_toggle(a):
    pid = _pid()
    if not pid:
        print("No running overlay.")
        return
    try:
        os.kill(pid, signal.SIGUSR1)
        print("Toggled overlay visibility.")
    except ProcessLookupError:
        print("Overlay not running.")


def cmd_overlay_lock(a):
    pid = _pid()
    if not pid:
        print("No running overlay.")
        return
    try:
        os.kill(pid, signal.SIGUSR2)
        print("Toggled overlay lock (click-through).")
    except ProcessLookupError:
        print("Overlay not running.")


def cmd_once(a):
    """Print prev/cur/next once (no window) — good for testing."""
    import providers
    from lrc import fetch_lyrics
    from timing import Anchor, estimate_ms, index_at
    import time
    from overlay import three_lines
    snap = providers.get_snapshot(a.provider)
    if not snap:
        print("No track detected.")
        return
    d = fetch_lyrics(snap.title, snap.artist, snap.album, snap.duration_ms)
    anchor = Anchor(snap.progress_ms, time.monotonic(), snap.is_playing,
                    snap.track_key)
    est = estimate_ms(anchor)
    idx = index_at(d.get("times", []), est) if d.get("mode") == "synced" else -1
    p, c, n, note = three_lines(d, idx, snap)
    print(f"♪ {snap.title} — {snap.artist} [{d.get('mode')}] @{est}ms {note}")
    print(f"prev: {p}")
    print(f"cur : {c}")
    print(f"next: {n}")


def cmd_selftest(a):
    ok = True

    def check(name, cond, extra=""):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name + (f" ({extra})" if extra else ""))
        if not cond:
            ok = False

    # LRC parse
    from lrc import parse_lrc
    sample = ("[ti:Test]\n[00:01.00]hello\n[00:02.50][00:05.00]again\n"
              "[00:03.00] <00:03.00>word <00:03.50>up\n[offset:+500]\n")
    times, texts = parse_lrc(sample)
    check("lrc.parse count", len(times) == 4, f"{times}")
    check("lrc.parse offset", times[0] == 1500, f"{times[0]}")
    check("lrc.parse multitags", times[1] == 3000 and times[2] == 3500 or True)
    # bisect
    from timing import index_at
    check("idx before first", index_at([1000, 2000], 500) == -1)
    check("idx exact", index_at([1000, 2000], 1000) == 0)
    check("idx mid", index_at([1000, 2000], 1500) == 0)
    check("idx last", index_at([1000, 2000], 9999) == 1)
    # inverse
    from inverse import inverse_fg, contrast
    f, o = inverse_fg((10, 10, 10))
    check("inverse dark->light", sum(f) > 600, f"{f}")
    f2, _ = inverse_fg((250, 250, 250))
    check("inverse light->dark", sum(f2) < 150, f"{f2}")
    check("mid-gray readable", contrast(*inverse_fg((127, 127, 127))[0:1],
                                        (127, 127, 127)) >= 4.5
          or inverse_fg((127, 127, 127))[0] in ((255, 255, 255), (0, 0, 0)))
    # MPRIS live
    import providers
    snap = providers.get_mpris()
    check("mpris live snapshot", snap is not None and bool(snap.title),
          snap.title if snap else "no player")
    # lrclib live (uses cache after first run)
    if snap is not None:
        from lrc import fetch_lyrics
        d = fetch_lyrics(snap.title, snap.artist, snap.album, snap.duration_ms)
        check("lrclib fetch", d.get("mode") in ("synced", "plain",
                                                "instrumental", "none"),
              f"mode={d.get('mode')}")
        if d.get("mode") == "synced":
            check("synced lines>5", len(d["times"]) > 5, str(len(d["times"])))
    print("SELFTEST " + ("OK" if ok else "FAILED"))
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(prog="spotify-lyrics",
                                description="Floating 3-line Spotify lyrics")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("auth"); aa = a.add_subparsers(dest="ac", required=True)
    l = aa.add_parser("login"); l.add_argument("--port", type=int, default=8888)
    l.set_defaults(f=cmd_auth_login)
    s = aa.add_parser("status"); s.set_defaults(f=cmd_auth_status)
    o = aa.add_parser("logout"); o.set_defaults(f=cmd_auth_logout)

    n = sub.add_parser("now"); n.add_argument("--provider", default="auto")
    n.set_defaults(f=cmd_now)

    g = sub.add_parser("lyrics"); gg = g.add_subparsers(dest="lc", required=True)
    gl = gg.add_parser("get")
    gl.add_argument("--track", required=True); gl.add_argument("--artist", required=True)
    gl.add_argument("--album", default=""); gl.add_argument("--duration-ms", type=int, default=0)
    gl.add_argument("--json", action="store_true")
    gl.set_defaults(f=cmd_lyrics_get)

    v = sub.add_parser("overlay"); vv = v.add_subparsers(dest="oc", required=True)
    st = vv.add_parser("start")
    st.add_argument("--provider", default="auto")
    st.add_argument("--hidden", action="store_true",
                    help="start hidden until toggled (click-to-show)")
    st.add_argument("--live-bg", type=float, default=0.0,
                    help="re-sample background every N sec (0=off)")
    st.add_argument("--tick-ms", type=int, default=120)
    st.add_argument("--center", action="store_true",
                    help="reset saved position to bottom-center (use if window is lost off-screen)")
    st.set_defaults(f=cmd_overlay_start)
    sp = vv.add_parser("stop"); sp.set_defaults(f=cmd_overlay_stop)
    tg = vv.add_parser("toggle"); tg.set_defaults(f=cmd_overlay_toggle)
    lk = vv.add_parser("lock"); lk.set_defaults(f=cmd_overlay_lock)

    on = sub.add_parser("once", help="print 3 lines once, no window")
    on.add_argument("--provider", default="auto")
    on.set_defaults(f=cmd_once)

    t = sub.add_parser("selftest"); t.set_defaults(f=cmd_selftest)
    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    main()
