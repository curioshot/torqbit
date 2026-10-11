# Agent brief: torque-bot ("Bot Island")

> Last verified against `d8ca62e` (185 tests green). If the tree has moved
> on, re-check the file paths and counts below before trusting them.

## What this is

A frameless, always-on-top desktop overlay for **Linux + X11** (developed on
KDE Plasma). It sits in front of every window and has three states:
collapsed pill → expanded card → full island. The full island is a single
row — control rail, RSS feed carousel, ring gauge, calendar — with no
backgrounds and no borders; only the components themselves paint anything.

Name mapping, because both appear everywhere: the repo is **torque-bot**,
the product calls itself **Bot Island** (`APP_NAME = "bot-island"` in
`island/config.py`). Don't rename one into the other.

## Run and test

```bash
./run.sh                 # creates .venv, installs deps, launches
./run.sh --no-webengine  # built-in eyes only (no Chromium)
.venv/bin/python -m pytest tests/ -q
```

Stack: Python 3.10+, `PySide6==6.9.2`, `psutil`, `python-xlib`
(`requirements.txt`). pytest is tests-only — the app never imports it.
`main.py` enforces a single instance with a `QLockFile` and shuts the probe
worker down on quit; a second copy exits instead of clobbering settings.

## Module map (`island/`)

| File | Owns |
|---|---|
| `window.py` | the three states, transitions, geometry |
| `geom.py` | geometry constants shared by window and overlay |
| `probe.py` | the one off-thread worker every system read runs on |
| `sysctl.py` | capability probes + control backends (`nmcli`, `pactl`, …) |
| `center.py` | the full island: rail, feed, gauge, calendar |
| `feedcar.py` / `feeds.py` | feed carousel widget / RSS-Atom reader + seed list |
| `todo.py` | calendar column (events live in `events.json`) |
| `tabs.py` / `service_tab.py` | card tabs / Instagram + Spotify settings pages |
| `reels.py` | Reels bridge: CDP for Chromium, BiDi for Firefox, over `QWebSocket` |
| `browsers.py` | browser discovery, instrumented launch, optional PATH wrapper |
| `services.py` | X11 key-fallback for Reels + the Spotify bridge |
| `face.py` | face widget (Blobatar / Aora-ball / Simple engines) |
| `config.py` | persistence: atomic writes, `.bak` copies, `VALID_*` sanitize |
| `themes.py` / `colors.py` / `icons.py` / `glass.py` / `widgets.py` | 7 themes, colour parsing, inline-SVG icons, painted containers |
| `sensors.py` | CPU temp readout (best-effort, never raises) |

Data only flows one way: `sysctl.py` knows how to ask, `probe.py` runs it
off the GUI thread, widgets see plain numbers. The UI layer never spawns a
subprocess directly.

## Five rules that break the app if you ignore them

1. **Probes stay off the GUI thread.** Everything in `sysctl.py` is a
   `subprocess.run` or a blocking read; called from a Qt timer slot it once
   froze the UI for ~19s. Route it through `probe.run(...)`. Only plain
   dicts and floats cross the thread boundary — never Qt objects.
2. **A control that can't act must say so.** Every backend reports a
   capability first; a dead control renders disabled with the reason in its
   tooltip. If you add a control, add its probe — never a silent no-op.
3. **Read writes back.** Exit status 0 proves nothing (PipeWire accepts a
   mic-volume write and then ignores it). Confirm the new state before
   reporting success.
4. **Nothing in `sysctl.py` or `sensors.py` raises.** Failures become
   capability reports, because all of it runs on a timer.
5. **Polling runs only while the panel is visible.** A collapsed island must
   cost nothing; don't add background timers.

## Config and state

Lives in `$XDG_CONFIG_HOME/bot-island/` (usually `~/.config/bot-island/`):
`config.json`, `events.json`, `notes.txt`. Dir is `0700`, files `0600` —
the directory also holds the browser profile with live Instagram cookies,
so keep it that way.

- `DEFAULTS` in `config.py` is the schema. Notable keys: `mode`
  (`island`|`corner`), `face` (`blobatar`|`aora`|`simple`), `theme` (7
  values — see `VALID_THEME`), `instagram.*` (Reels settings),
  `centre.feeds` (a plain `[{name, url}]` list, hand-editable).
- Unknown values are sanitized back to defaults on load (e.g. a typo'd
  theme becomes `black`). New enum values must be added to `VALID_*`
  *and* covered by a test like `test_new_themes_survive_sanitize`, or
  they won't survive a reload.
- Writes are atomic (temp file + fsync + rename) and keep a `.bak`, so a
  bad hand-edit is recoverable. Keep both properties.
- `PAGE_WRITABLE` is the only set of keys injected page scripts may write
  back through the CDP binding. Don't widen it without a reason written
  down — a page script must never flip the service switch or retarget the
  browser.

Reels specifics (`reels.py`): injection is probe-and-re-inject, not
preload — every poll checks for `window.__reelscroll` and re-injects after
navigations. Transport failures degrade to "not connected" and the caller
falls back to X11 keys. No new dependency: `QWebSocket` ships with
PySide6.

## Spotify boundary

`spotify/` is a semi-independent subproject (own README, own
requirements): MPRIS now-playing, synced lyrics via lrclib, floating
overlay CLI. The island only touches it through `services.py`, which
reuses its `providers`/`lrc`/`timing` modules and drives the overlay CLI.
Don't merge the two configs; don't import island code from `spotify/`.

## Faces, themes, vendored JS

- 7 themes in `themes.py`; since containers don't paint, a theme sets ink
  (text/subtext/muted/accent) plus translucency.
- 3 face engines: Blobatar (default, name-seeded creature), EmotionBall,
  Simple (built-in QPainter, zero deps).
- `assets/blobatar/` and `assets/reels/` are MIT; **`assets/emotion-ball/`
  is personal/research use only** (see its `THIRD_PARTY_NOTICE.md`). The
  root MIT license does not cover it. `tools/blobatar-entry.ts` is the
  esbuild source for the bundled `blobatar-face.js`.

## Tests

185 tests across 11 files (`test_browsers 8, test_colors 12, test_config
23, test_feeds 23, test_frameless 21, test_layout 23, test_probe 11,
test_reels 18, test_sensors 9, test_smoke 17, test_sysctl 20`). They run
headless (`QT_QPA_PLATFORM=offscreen` is set in `conftest.py`, which also
redirects all filesystem access into `tmp_path` — a test must never touch
the real `~/.config/bot-island`). One `QApplication` per session; the
`qapp` fixture shuts the probe worker down afterwards or Qt aborts at
exit. `test_smoke.py` builds every screen and drives every state
transition — if you change `window.py`, it should catch regressions.

## Non-goals (don't add these)

- Windows/macOS support beyond code-review smoke checks; GNOME-Wayland
  gets a keep-above fallback, not a true overlay.
- A browser extension for Reels — the CDP/BiDi bridge replaced it
  deliberately. Don't bring one back.
- New global hotkeys or background polling without asking first; both cost
  idle CPU, which this project measures (87% → 1% collapsed is in the
  history — keep it that way).
