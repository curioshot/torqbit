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
- **Double-click**: open the **control centre** — a second panel below the
  card, separated by an 8px gap, with a 96px control rail to the card's left
- **Drag** island: move (saved to `~/.config/bot-island/config.json`)
- **Esc** / the `–` button: step back one level (centre → card → island)
- **Right-click**: Design (island ⇄ corner), Corner, Face, Bot shape,
  Emotion, Control centre (`Ctrl+Space`), Snap to top-center, Quit
- Expanded panel tabs: **Bot/Time** (emotions, face picker, creature name,
  shuffle), **Calendar** (add events), **System/Notes** (CPU/RAM/temp,
  autosaved notes), **Appearance** (5 themes + creature backdrop),
  **Service** (Instagram + Spotify)
- Live **CPU temperature** next to the clock (capsule, header, System tab)
- Emoji-free UI: every icon is inline SVG and tints with the active theme

## Control centre (double-click)

A second glass panel under the card holding the news carousel and a ring gauge
(temp, RAM, load, network throughput). The mic / output / brightness sliders
and the toggle buttons live in a **96px rail immediately left of the card** —
and that rail has no panel of its own, so the controls sit straight on the
wallpaper rather than inside a third box. The rail appears and disappears with
the centre.

Sliders are deliberately quiet: a 2px hairline track at ~18% opacity with no
fill, so the accent-coloured knob is the only bright thing. The knob is ~9px
across inside a 28px invisible grab area. The eight toggles are a 2x4 grid of
44x56 dots directly below them.

**News is a carousel, not a list.** There is no frame, no border, no tab bar
and no visible add/refresh button — one feed fills the strip at a time and
scrolling flows continuously from one feed into the next. Each feed shows its
own logo above its name, falling back to a coloured monogram, and its
headlines beneath. Right-click anywhere in the strip to add or remove feeds.

**Every control is capability-gated.** Before it does anything the bot asks
what this machine can actually do, and a control that cannot act renders
disabled with the reason in its tooltip — it never silently does nothing.

| Control | How it is driven | On this machine |
|---|---|---|
| Brightness | `/sys/class/backlight` when writable, else `xrandr --output … --brightness` | software (no backlight device in a VM) |
| Mic / output volume | `pactl` (install with `sudo apt install pulseaudio-utils`), falling back to `pw-cli` | output works; the mic source ignores writes, so it self-disables |
| Network, airplane | NetworkManager via `nmcli` | working |
| Wi-Fi / Bluetooth | NM radio + adapter presence | no adapter here, so both are disabled |
| Do not disturb | Plasma 6 desktop-appletsrc | working |
| Lock screen | `loginctl lock-session` | working |

Writes are always **read back** before being reported as done: PipeWire
accepts `pactl set-source-volume` with exit status 0 and then ignores it on a
suspended device, so a success code alone proves nothing.

**Feeds.** Right-clicking the strip opens a picker with a built-in catalog grouped by category
(News, Tech, Games, Science, Sport — every URL verified live) plus a box for
any custom RSS/Atom URL. Everything is stored as a plain
`[{name, url}]` list under `centre.feeds` in `config.json`, so feeds can be
added, removed or reordered by hand. A feed that rots degrades to one quiet
"unavailable" row.

```json
"centre": { "enabled": true, "feeds": [ {"name": "BBC World", "url": "https://…"} ] }
```

Polling only runs while the panel is visible, so a collapsed island costs
nothing.

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
        island/{center,feedcar,widgets,sysctl,feeds}.py  ← control centre
assets/{blobatar,emotion-ball,reels}/
tools/blobatar-entry.ts   # bundle source for assets/blobatar/blobatar-face.js
```

`island/reels.py` holds the browser bridge (CDP + BiDi, over `QWebSocket`, so
no extra dependency) and `island/browsers.py` does browser discovery, launch
and the optional PATH wrapper. `assets/reels/` is the page-side engine,
injected at runtime; it is storage-agnostic and can also be loaded by an
extension if you ever want one back.

The control centre splits cleanly by concern: `island/sysctl.py` is the
capability-probing backend layer, `island/widgets.py` the painted widgets,
`island/feeds.py` the RSS reader (including the async logo cache),
`island/feedcar.py` the frameless carousel that renders it, and
`island/center.py` the container that composes them.

Settings live in one place — `~/.config/bot-island/config.json`. The page reads
them when it is injected and, over CDP, writes changes from the video pill
straight back through the bot.

Rebuild the blobatar bundle: `npx esbuild tools/blobatar-entry.ts --bundle
--format=iife --minify --outfile=assets/blobatar/blobatar-face.js`
