# spotify-lyrics (personal, not for publishing)

CLI + floating 3-line lyrics overlay. Shows **previous / current / next** lyric line,
advancing with Spotify time. Overlay is draggable, always-on-top, transparent
(text pixels only). Each character is drawn in the **inverse of the pixels behind it**
(with a contrast guard + outline so mid-gray backgrounds stay readable).

## Setup (once)

```bash
cd ~Desktop/instagram/spotify
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

No Spotify login needed on this machine: the desktop app is read via MPRIS
(D-Bus, offline, instant). Login is only needed for the web player / remote
devices.

Optional login (covers `open.spotify.com`, phone, speakers):

```bash
# create an app at https://developer.spotify.com/dashboard (redirect:
# http://127.0.0.1:8888/callback), then:
export SPOTIFY_CLIENT_ID='<your id>'
.venv/bin/python cli.py auth login
```

## Use

```bash
.venv/bin/python cli.py now                  # current track (JSON)
.venv/bin/python cli.py lyrics get --track "lovely" --artist "Billie Eilish"
.venv/bin/python cli.py overlay start         # show floating lyrics (foreground)
.venv/bin/python cli.py overlay start --hidden  # start hidden, show on toggle
.venv/bin/python cli.py overlay toggle        # show/hide running overlay
.venv/bin/python cli.py overlay stop          # stop running overlay
.venv/bin/python cli.py overlay lock          # toggle click-through (locked/unlocked)
```

* Drag the lyrics with the mouse to move. Position is remembered.
  The window can never be dragged fully off-screen; if you ever lose it
  (e.g. after unplugging a monitor), restart with `--center`:
  `.venv/bin/python cli.py overlay start --center`
* `Ctrl+C` in the `overlay start` terminal also stops it.
* Lyrics source: `lrclib.net` (free, synced LRC), cached 7 days in
  `~/.cache/spotify-lyrics/`. Uploader edits like `- Slowed & Reverbed`
  or `(Sped Up)` fall back to the base song; if durations differ the
  overlay shows static text instead of fake-synced scrolling.
* State: `~/.config/spotify-lyrics/{tokens.json,pos.json}`,
  pidfile `~/.cache/spotify-lyrics/overlay.pid`.

## Notes / limits

* Linux X11: true transparent ARGB overlay (this machine: X11 + KDE).
  GNOME-Wayland falls back to a keep-above window (documented Wayland limit:
  no true pin over fullscreen, sampling needs portal consent).
* Windows/macOS paths are implemented (`SMTC` / `AppleScript`) but only
  smoke-tested here via code review, not live.
* Personal-use tool. Lyrics via LRCLIB; Spotify Web API needs your own
  dev app id. Nothing here is packaged for distribution.
