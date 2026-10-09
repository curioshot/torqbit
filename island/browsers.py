"""Browser discovery and instrumented launch.

The Reels service needs a browser it can inject JavaScript into. Two
transports are supported, both proven against this machine:

  chromium-family  Chrome DevTools Protocol over WebSocket
                   (Chromium, Chrome, Brave, Edge, Opera, Vivaldi, Arc)
  firefox         WebDriver BiDi over WebSocket (Remote Agent)

Both need the browser launched with a debug port on 127.0.0.1. Chromium 136+
*ignores* --remote-debugging-port when the default profile is used, so a
dedicated bot profile is mandatory. That profile is created here and is
never derived from the user's real browser profile: no cookies, passwords or
history are read or copied. The user signs into Instagram themselves, once,
inside the bot's window.

Two ways in:
  launch()          the bot starts the browser ("Open Instagram" in the UI)
  install_shim()    opt-in PATH wrapper so *any* launch of the browser is
                    instrumented, not just the bot's
"""
from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
from pathlib import Path

from . import config as cfgmod

REELS_URL = "https://www.instagram.com/reels/"

# family -> (candidate binary names, transport)
#
# Ordering matters. Put the concrete package binary BEFORE any generic name:
# on Debian /usr/bin/firefox is a wrapper shell script that runs
# `command -v firefox-esr`, so invoking it can resolve through PATH straight
# back into a bot-island shim and silently inherit that shim's baked-in
# --profile and --remote-debugging-port, overriding our own flags.
FAMILIES = {
    "chromium": (
        ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
         "brave-browser", "microsoft-edge", "microsoft-edge-stable",
         "opera", "vivaldi", "vivaldi-stable", "arc"),
        "cdp",
    ),
    "firefox": (("firefox-esr", "firefox", "firefox-beta"), "bidi"),
}

# Absolute fallbacks for the common Debian/Fedora/Arch layouts, tried when the
# binary is not on PATH (e.g. launched from a desktop session with a minimal PATH).
EXTRA_PATHS = {
    "chromium": (
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/usr/bin/brave-browser", "/usr/bin/microsoft-edge",
        "/usr/lib/chromium/chromium", "/usr/lib/chromium-browser/chromium-browser",
        "/opt/google/chrome/chrome", "/snap/bin/chromium",
        "/var/lib/flatpak/exports/bin/com.brave.Browser",
    ),
    "firefox": ("/usr/bin/firefox-esr", "/usr/lib/firefox-esr/firefox-bin",
                "/usr/bin/firefox", "/opt/firefox/firefox", "/snap/bin/firefox",
                "/var/lib/flatpak/exports/bin/org.mozilla.firefox"),
}

DEFAULT_PORTS = {"chromium": 9222, "firefox": 9223}


def free_port(preferred: int = 0) -> int:
    """A free loopback port, preferring `preferred` when it is available."""
    if preferred:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
        finally:
            s.close()
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _is_shim(path: str) -> bool:
    """True if `path` is a wrapper Bot Island wrote (must never be re-wrapped)."""
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > 4096:
            return False
        return "bot-island-instrumented" in p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def find(family: str) -> str | None:
    """Absolute path to a usable binary for `family`, or None.

    Deliberately skips Bot Island's own PATH shim: wrapping a wrapper would
    pin a stale port/profile into the shim body, and `shutil.which` will
    happily hand us the shim once it sits earlier on PATH than the real binary.
    """
    names, _ = FAMILIES.get(family, ((), None))
    for name in names:
        p = shutil.which(name)
        if p and not _is_shim(p):
            return p
    for p in EXTRA_PATHS.get(family, ()):
        if os.path.isfile(p) and os.access(p, os.X_OK) and not _is_shim(p):
            return p
    return None


def discover() -> list[dict]:
    """Every installed browser the bot can drive, best candidate first."""
    out = []
    for family, (names, transport) in FAMILIES.items():
        binary = find(family)
        if not binary:
            continue
        out.append({
            "family": family,
            "transport": transport,
            "binary": binary,
            "name": os.path.basename(binary),
            "label": _pretty(names, binary),
        })
    return out


def _pretty(names, binary: str) -> str:
    base = os.path.basename(binary).lower()
    for n in names:
        if base.startswith(n):
            return n.replace("-browser", "").replace("-stable", "").replace("-esr", "").title()
    return base


def profile_dir(family: str) -> Path:
    return cfgmod.CONFIG_DIR / f"{family}-profile"


def port_file(family: str) -> Path:
    return cfgmod.CONFIG_DIR / f"{family}-port"


def current_port(family: str) -> int | None:
    """Port of an already-running instrumented browser, if we launched one."""
    try:
        p = port_file(family)
        if p.exists():
            port = int(p.read_text().strip())
            return port if port_listening(port) else None
    except Exception:
        pass
    return None


def port_listening(port: int, timeout: float = 0.35) -> bool:
    try:
        socket.create_connection(("127.0.0.1", int(port)), timeout=timeout).close()
        return True
    except Exception:
        return False


def running(family: str) -> bool:
    return current_port(family) is not None


def _write_firefox_prefs(directory: Path, port: int) -> None:
    """Firefox needs its Remote Agent port set through the profile."""
    directory.mkdir(parents=True, exist_ok=True)
    prefs = {
        # BiDi only; Firefox removed CDP support in 129.
        "marionette.enabled": False,
        "remote.active-protocols": 1,
        "browser.shell.checkDefaultBrowser": False,
        "browser.startup.homepage": REELS_URL,
        "browser.startup.page": 0,
        "datareporting.policy.dataSubmissionEnabled": False,
        "toolkit.telemetry.enabled": False,
        # Keep the bot window quiet and predictable.
        "browser.tabs.warnOnClose": False,
        "dom.webnotifications.enabled": False,
        "media.volume_scale": "0.0",
    }
    lines = [f'user_pref("{k}", {"true" if v is True else "false" if v is False else json_str(v)});'
             for k, v in prefs.items()]
    (directory / "user.js").write_text("\n".join(lines) + "\n", encoding="utf-8")


def json_str(v) -> str:
    import json
    return json.dumps(v)


def build_args(family: str, binary: str, port: int, url: str = REELS_URL,
               app_mode: bool = True, profile: Path | None = None,
               extra_args: list[str] | None = None) -> list[str]:
    """Instrumentation flags. Every debug port binds to loopback only."""
    prof = str(profile or profile_dir(family))
    extra = list(extra_args or [])
    if family == "firefox":
        args = [binary, "--remote-debugging-port", str(port), "--profile", prof]
        args += extra
        args += ["-new-instance", url] if url else ["-new-instance", "about:blank"]
        return args
    args = [binary]
    args += [f"--remote-debugging-port={port}",
             "--remote-debugging-address=127.0.0.1",
             f"--user-data-dir={prof}"]
    if app_mode:
        # Chrome-less window: one purpose, no tab strip or toolbar.
        args += [f"--app={url}"] if url else []
    else:
        args += ["--new-window", url] if url else []
    args += common_flags()
    args += extra
    return args


def common_flags() -> list[str]:
    """Quiet-start flags shared by both families."""
    return ["--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--disable-infobars",
            "--no-service-autorun",
            "--password-store=basic",
            "--disable-print-preview"]


def launch(family: str, url: str = REELS_URL, app_mode: bool = True,
           extra_args: list[str] | None = None) -> dict:
    """Start an instrumented browser for the bot. Returns a status dict.

    Never raises: a failure is reported, not thrown, because this is called
    from a Qt timer.
    """
    binary = find(family)
    if not binary:
        return {"ok": False, "error": f"no {family} browser installed"}

    already = current_port(family)
    if already:
        return {"ok": True, "already": True, "port": already, "family": family}

    port = free_port(DEFAULT_PORTS.get(family, 0))
    prof = profile_dir(family)
    prof.mkdir(parents=True, exist_ok=True)
    if family == "firefox":
        # The Remote Agent is off by default; prefs are the only way to turn it on.
        _write_firefox_prefs(prof, port)

    args = build_args(family, binary, port, url=url, app_mode=app_mode,
                      profile=prof, extra_args=extra_args)
    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return {"ok": False, "error": f"could not start {binary}: {e}"}

    try:
        cfgmod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        port_file(family).write_text(str(port), encoding="utf-8")
    except Exception:
        pass

    return {"ok": True, "already": False, "port": port, "family": family,
            "pid": proc.pid, "binary": binary, "args": args}


def instrument_args(family: str) -> list[str]:
    """Flags a PATH shim should append so any launch is bot-driveable.

    Each entry is a complete, already-quoted shell word — the shim joins
    them with spaces onto one exec line.
    """
    prof = shlex.quote(str(profile_dir(family)))
    if family == "firefox":
        port = current_port("firefox") or DEFAULT_PORTS["firefox"]
        return ["--remote-debugging-port", str(port), "--profile", prof]
    port = current_port("chromium") or DEFAULT_PORTS["chromium"]
    return [f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={prof}"]


# ------------------------------------------------------------------ PATH shim
SHIM_DIR_NAME = ".local/bin"
SHIM_MARKER = "bot-island-instrumented"


def _shim_dir() -> Path:
    return Path.home() / SHIM_DIR_NAME


def _shim_family(body: str) -> str | None:
    """Family a shim wraps, parsed from its header comment.

    Header looks like:  # bot-island-instrumented wrapper for firefox
    """
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("#") or SHIM_MARKER not in line:
            continue
        parts = line.lstrip("#").split()
        # [marker, 'wrapper', 'for', family]
        if (len(parts) >= 4 and parts[0] == SHIM_MARKER
                and parts[1] == "wrapper" and parts[2] == "for"):
            return parts[3]
    return None


def find_shim(family: str) -> Path | None:
    """The installed shim for `family`, whatever it ended up being named.

    Deliberately a directory scan rather than a derived filename: the binary
    name `find()` resolves moves once the shim is itself earlier on PATH
    (firefox vs firefox-esr), which would make install and check disagree.
    """
    d = _shim_dir()
    try:
        for p in sorted(d.iterdir()):
            # Filter by the parsed header, not _is_shim(): _is_shim() matches
            # the very marker we are looking for and would skip every hit.
            if not p.is_file():
                continue
            if _shim_family(_safe_read(p)) == family:
                return p
    except Exception:
        pass
    return None


def shim_installed(family: str) -> bool:
    return find_shim(family) is not None


def _safe_read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def install_shim(family: str) -> dict:
    """Wrap the browser on PATH so EVERY launch comes up instrumented.

    This exposes the debug port for all browsing, not just Reels — which is
    why it is opt-in and clearly labelled in the UI. The port is baked in at
    install time, so uninstall/reinstall after changing ports.
    """
    binary = find(family)
    if not binary:
        return {"ok": False, "error": f"no {family} browser installed"}
    existing = find_shim(family)
    if existing:
        return {"ok": True, "already": True, "path": str(existing)}
    target = _shim_dir() / os.path.basename(binary)
    flags = " ".join(instrument_args(family))
    script = "\n".join([
        "#!/usr/bin/env bash",
        f"# {SHIM_MARKER} wrapper for {family}",
        "# Installed by Bot Island so Instagram Reels control works no matter how",
        "# the browser is started. Remove with the \"Uninstall\" button in the",
        "# Service tab, or just delete this file.",
        f'exec {shlex.quote(binary)} {flags} "$@"',
        "",
    ])
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
        target.chmod(0o755)
    except Exception as e:
        return {"ok": False, "error": f"could not write {target}: {e}"}
    return {"ok": True, "already": False, "path": str(target), "binary": binary}


def uninstall_shim(family: str) -> dict:
    p = find_shim(family)
    if not p:
        return {"ok": True, "already": False}
    if SHIM_MARKER not in _safe_read(p):
        return {"ok": False,
                "error": f"{p} is not a bot-island shim — left alone"}
    try:
        p.unlink()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "already": False, "path": str(p)}


def shim_status() -> dict:
    """Per-family shim state for the UI."""
    out = {}
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for family in FAMILIES:
        if not find(family):
            continue
        p = find_shim(family)
        path = str(p) if p else str(_shim_dir() / FAMILIES[family][0][0])
        out[family] = {
            "installed": p is not None,
            "path": path,
            "dir_on_path": str(_shim_dir()) in path_dirs,
            "shim_dir_index": (path_dirs.index(str(_shim_dir()))
                               if str(_shim_dir()) in path_dirs else -1),
            "real_dir_index": _real_dir_index(family, path_dirs),
        }
    return out


def shim_effective(family: str) -> bool:
    """True when the shim would actually win over the real binary on PATH."""
    st = shim_status().get(family)
    if not st or not st["installed"]:
        return False
    sdi, rdi = st["shim_dir_index"], st["real_dir_index"]
    if sdi < 0:
        return False
    return rdi < 0 or sdi < rdi


def _real_dir_index(family: str, path_dirs: list[str]) -> int:
    """Index of the real binary's directory on PATH (-1 when absent)."""
    for i, d in enumerate(path_dirs):
        if not d:
            continue
        for name in FAMILIES[family][0]:
            cand = Path(d, name)
            if cand.exists() and not _is_shim(str(cand)):
                return i
    return -1
