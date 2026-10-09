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
  autosaved notes), **Appearance** (5 themes + creature backdrop)
- Live **CPU temperature** next to the clock (capsule, header, System tab)
- Emoji-free UI: every icon is inline SVG and tints with the active theme

## Themes (Appearance tab)

Liquid Glass (frosted translucency) · White · Black · System default
(follows your KDE palette) · Minimal (flat monochrome). Right-click → Theme
switches too; the choice persists.

## Service tab (Instagram + Spotify)

Two 20px-radius tiles next to Appearance. Each opens its settings page with
a service toggle — when on, the bot auto-detects the app and runs itself.

- **Instagram** (ReelScroll replacement, pure Python via X11): toggle +
  live Reels detection across Chrome tabs, installed web apps (PWA), and
  native app windows; Prev/Next reel buttons (focused-window key synthesis,
  verified live — no extension needed for keys), full extension settings
  mirror (keys capturable, cooldown, threshold, arrows, controller,
  auto-advance). Wheel flip stays in the browser extension (needs page JS)
  and is marked as such.
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
main.py  island/{window,face,tabs,config}.py  assets/{blobatar,emotion-ball}/
tools/blobatar-entry.ts   # bundle source for assets/blobatar/blobatar-face.js
```

Rebuild the blobatar bundle: `npx esbuild tools/blobatar-entry.ts --bundle
--format=iife --minify --outfile=assets/blobatar/blobatar-face.js`
