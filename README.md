# Bot Island — always-on-top desktop island

A frameless overlay that lives in front of every window. Three states, one
row, no boxes: the containers, buttons and controls sit directly on the
screen with **no background and no border** — only the components themselves
draw anything.

    collapsed pill        expanded card              full island
    ┌──────────┐         ┌──────────┐               ┌────┬────────┬──────┬──────────┐
    │ ◍ 12:00 ●│  ─1─▶   │ ◍ 12:00 ●│  ─2─▶        │ ▓▓ │  RSS   │ ring │ Calendar │
    └──────────┘         ├──────────┤               │ ▓▓ │  feed  │ gauge│  to-dos  │
                         │ tabs…    │               └────┴────────┴──────┴──────────┘
                         │ content  │
                         └──────────┘

Everything in the sketch's first two states is one pill; the full island is
a single row: the control rail, the news feed, the ring gauge and the
calendar, side by side.

## Run

```bash
./run.sh            # creates .venv, installs deps, launches
./run.sh --no-webengine   # built-in eyes only (no Chromium)
```

Requirements: Linux + X11 (tested KDE Plasma), Python 3.10+.

## Interact

- **1 click** the pill: expand to the card
- **Double-click** the pill *or* the card: open the **full island** directly —
  the in-flight expand flight is cancelled, so the card never flashes past
- **Esc** / the `–` button: step back one level (full → card → pill)
- **⤢** button: open the full island from the card
- **Drag** the pill: move (saved to `~/.config/bot-island/config.json`)
- **Right-click**: Design (island ⇄ corner), Corner, Face, Bot shape,
  Emotion, Control centre (`Ctrl+Space`), Snap to top-center, Quit
- Card tabs: **Bot/Time** (clock, full-size face, emotions, shape, face
  picker, creature name, shuffle), **Calendar** (add/edit/delete events),
  **System/Notes** (CPU/RAM/temp, autosaved notes), **Appearance** (5 themes
  + creature backdrop), **Service** (Instagram + Spotify)
- Live **CPU temperature** next to the clock (pill, header, System tab)
- Emoji-free UI: every icon is inline SVG and tints with the active theme
- Keyboard: sliders take arrows/Home/End/PageUp/Down, `Esc` backs out of a
  service page, everything carries an accessible name

## The full island (double-click)

One row, four columns. Nothing here is a box.

**The rail** — three sliders (mic, output, brightness) over a **4×4 grid of
13 toggles**, 172px wide. It has no panel and never did: the controls sit
straight on the wallpaper.

| Toggle | Driven by | On this machine |
|---|---|---|
| Airplane | NetworkManager (`nmcli radio`) | working |
| Net | `nmcli device` link state | working |
| Wi-Fi | NM radio + adapter presence | no adapter, so disabled |
| Bluetooth | `bluetoothctl` | no adapter, so disabled |
| DND | Plasma 6 desktop-appletsrc | working |
| Mic mute | `pactl` | working |
| Speaker mute | `pactl` sink | working |
| Theme | in-process, no backend | always |
| Lock | `loginctl lock-session` | working |
| Blank | `systemctl suspend`, else `xset dpms` | working |
| Night light | Plasma D-Bus, else `gammastep` | gamma ramp only |
| Play / pause | `playerctl` | no player, so disabled |
| Screenshot | `spectacle` → `grim` → `gnome-screenshot` → `scrot` | spectacle |

**The feed** is a carousel, not a list — no frame, no border, no tab bar, one
feed at a time, scrolling continuously into the next. **The gauge** shows
temp / RAM / load. **The calendar** is a compact month grid plus the selected
day's items.

Sliders are deliberately quiet: a 2px hairline track at ~18% opacity with no
fill, so the accent-coloured knob is the only bright thing. The knob is ~9px
across, and the widget grabs the mouse on press so a drag that drifts off the
48px column keeps tracking instead of dropping.

Each feed shows its own logo above its name, falling back to a coloured
monogram, with its headlines beneath. Right-click anywhere in the strip to
add or remove feeds.

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

White · Black · System default (follows your KDE palette) · Minimal ·
Liquid Glass. Right-click → Theme switches too; the choice persists.

Since the containers no longer paint, a theme now only sets **ink**: text,
subtext, muted and accent. The five remain genuinely different, but they
change colour rather than surface — there are no surfaces left to change.

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
main.py
island/window.py      the three states, transitions, geometry
island/geom.py        shared geometry constants (island + overlay both use these)
island/probe.py       the off-thread worker every system probe runs on
island/sysctl.py      capability probes; every one is gated with a reason
island/center.py      the full island: rail, feed, gauge, calendar
island/todo.py        the calendar column
island/{tabs,service_tab,face,reels,browsers,services}.py
island/{config,colors,themes,icons,glass,widgets,feedcar,feeds,sensors}.py
assets/{blobatar,emotion-ball,reels}/
tools/blobatar-entry.ts   # bundle source for assets/blobatar/blobatar-face.js
tests/                184 tests: unit + an offscreen smoke run
```

`island/reels.py` holds the browser bridge (CDP + BiDi, over `QWebSocket`, so
no extra dependency) and `island/browsers.py` does browser discovery, launch
and the optional PATH wrapper. `assets/reels/` is the page-side engine,
injected at runtime; it is storage-agnostic and can also be loaded by an
extension if you ever want one back.

Nothing in the UI layer touches a subprocess directly. `island/sysctl.py`
knows how to ask; `island/probe.py` knows it must not be asked on the GUI
thread; the widgets only ever see plain numbers.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q
```

Runs headless (`QT_QPA_PLATFORM=offscreen`) and includes a smoke test that
constructs every screen and drives every state transition.

## Rebuild the blobatar bundle

```
npx esbuild tools/blobatar-entry.ts --bundle --format=iife --minify \
  --outfile=assets/blobatar/blobatar-face.js
```
