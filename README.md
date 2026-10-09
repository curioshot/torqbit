# Bot Island — always-on-top desktop island

A sleek top-screen capsule (Grok-like) that stays in front of every window.
Click to expand: avatar + time/date/day/temp on top, menus (calendar,
system/notes, appearance) in a glass container below. Closing flies back to
the saved island spot. Or switch to a corner ¼-circle design. Drag to move;
position persists.

## Run

```bash
./run.sh            # creates .venv, installs deps, launches
./run.sh --no-webengine   # built-in eyes only (no Chromium)
```

Requirements: Linux + X11 (tested KDE Plasma), Python 3.10+.

## Interact

- **Click** island/quarter: expand / collapse
- **Drag** island: move (saved to `~/.config/bot-island/config.json`)
- **Right-click**: Design (island ⇄ corner), Corner, Face, Bot shape,
  Emotion, Snap to top-center, Quit
- Expanded panel tabs: **Bot/Time** (emotions, face picker, creature name,
  shuffle), **Calendar** (add events), **System/Notes** (CPU/RAM/temp,
  autosaved notes), **Appearance** (5 themes + creature backdrop),
  **Service** (Instagram + Spotify)
- Live **CPU temperature** next to the clock (capsule, header, System tab)
- Emoji-free UI: every icon is inline SVG and tints with the active theme

## Themes (Appearance tab)

Liquid Glass (frosted translucency) · White · Black · System default
(follows your KDE palette) · Minimal (flat monochrome). Right-click → Theme
switches too; the choice persists.

## Service tab (Instagram + Spotify)

Two 20px-radius tiles next to Appearance. Each opens its settings page with
a service toggle — when on, the bot detects what you're using and drives it
itself.

- **Instagram** — Reels control runs **natively inside the bot**. There is no
  browser extension: the bot connects to your browser over a debug protocol
  and injects the same page-side engine (now in `assets/reels/`), so *wheel
  flip works too*, along with the floating video controller (play/pause,
  scrub, ±5s, 0.5–3×, simulated reverse, picture-in-picture) and
  auto-advance.

  Supported browsers:

  | Browser | Transport |
  |---|---|
  | Chromium, Chrome, Brave, Edge, Opera, Vivaldi, Arc | Chrome DevTools Protocol |
  | Firefox | WebDriver BiDi (Remote Agent) |
  | anything else | X11 key synthesis — next/prev only |

  **First run:** click **Open Instagram** in the Service tab. The bot starts a
  window of its own, on a profile of its own, and you log into Instagram there
  once. Chromium 136+ ignores the debug port on a default profile, so a
  separate profile is mandatory — which is also the safer choice: the bot never
  reads your everyday profile, cookies or passwords.

  **To use the browser you start yourself,** tick *Also control Reels when I
  start the browser myself*. That installs a small wrapper in `~/.local/bin`
  so every launch of that browser comes up instrumented and the bot just
  attaches. Off by default, with an uninstall button beside it — the debug
  port is then open for *all* your browsing in that browser, not just Reels.

  If no instrumented browser is found, the bot falls back to sending next/prev
  keys straight to the Instagram window, so the buttons keep working.
- **Spotify**: toggle + MPRIS detection, auto-launches the app if missing,
  now-playing with synced lrclib lyrics highlighting live, floating-overlay
  start/stop, web-player login hint.

## Faces (you can choose any one)

| Engine | Source | Notes |
|---|---|---|
| **Blobatar** (default) | `assets/blobatar/` (bundled MIT core) | Type any creature name — same name = same creature. 8 moods morph live, eyes follow cursor |
| **EmotionBall** | `assets/emotion-ball/` (vendored JS) | 32 moods, blob/wedge/gem bodies. Visual design: personal/research use only (see its `THIRD_PARTY_NOTICE.md`) |
| **Simple** | built-in QPainter | zero-dependency blinking eyes |

Switch via right-click → Face, or the Bot/Time tab. The shuffle button cycles
through verified-good creatures.

## Files

```
main.py  island/{window,face,tabs,config,service_tab,reels,browsers}.py
assets/{blobatar,emotion-ball,reels}/
tools/blobatar-entry.ts   # bundle source for assets/blobatar/blobatar-face.js
```

`island/reels.py` holds the browser bridge (CDP + BiDi, over `QWebSocket`, so
no extra dependency) and `island/browsers.py` does browser discovery, launch
and the optional PATH wrapper. `assets/reels/` is the page-side engine,
injected at runtime; it is storage-agnostic and can also be loaded by an
extension if you ever want one back.

Settings live in one place — `~/.config/bot-island/config.json`. The page reads
them when it is injected and, over CDP, writes changes from the video pill
straight back through the bot.

Rebuild the blobatar bundle: `npx esbuild tools/blobatar-entry.ts --bundle
--format=iife --minify --outfile=assets/blobatar/blobatar-face.js`
