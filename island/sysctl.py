"""System control backends for the control centre.

Every control here answers the same question first: *can this machine do
that, and how?* Nothing silently no-ops. A control that cannot work reports
`kind: "none"` with a `reason`, and the UI disables it and shows that reason
in the tooltip.

    Brightness   hardware  /sys/class/backlight/*/brightness  (real laptops)
                 software  xrandr --output X --brightness      (VMs, desktops)
    Mic / output volume   pactl, falling back to pw-cli
    Network, airplane     NetworkManager via nmcli, QtDBus fallback
    Bluetooth             bluetoothctl
    Lock                  loginctl lock-session
    Do not disturb        Plasma 6 desktop-appletsrc (kded module)
    Net speed             /proc/net/dev deltas

Nothing in this module raises: every backend is wrapped so a failure becomes
a capability report, because all of it is called from a Qt timer.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# --------------------------------------------------------------- helpers


def _run(cmd, timeout=2.5) -> tuple[int, str]:
    """Run a command, never raise. Returns (returncode, combined output)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    except Exception:
        return 1, ""


def _have(cmd: str) -> bool:
    return bool(shutil.which(cmd))


def _f(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


class TTLCache:
    """Memoise an expensive read for a few seconds.

    NetworkManager answers cost 30-90ms per `nmcli` spawn, and the control
    centre polls several times a second. A toggle indicator does not need
    to be current to the millisecond; three seconds is imperceptible.
    """

    def __init__(self, ttl: float = 3.0):
        self.ttl = ttl
        self._v: dict[str, object] = {}
        self._t: dict[str, float] = {}

    def get(self, key: str):
        if key not in self._v:
            return None
        if time.monotonic() - self._t.get(key, 0.0) > self.ttl:
            self._v.pop(key, None)
            return None
        return self._v[key]

    def put(self, key: str, value) -> None:
        self._v[key] = value
        self._t[key] = time.monotonic()

    def clear(self) -> None:
        self._v.clear()
        self._t.clear()


# --------------------------------------------------------------- brightness


class Brightness:
    """Screen brightness: real hardware when present, xrandr dimming otherwise.

    The software path uses the X server's per-output `Brightness` property.
    It is not a gamma curve — it scales the output before compositing — so it
    genuinely reaches black and does not wash out the way --gamma does.
    """

    HARDWARE = "hardware"
    SOFTWARE = "software"
    NONE = "none"

    def __init__(self):
        self.kind = self.NONE
        self.reason = "no brightness control found"
        self.max = 1
        self._outputs: list[str] = []
        self._cached: float | None = None
        self.probe()

    # -- discovery ------------------------------------------------------
    def probe(self) -> str:
        hw = self._probe_sysfs()
        if hw:
            return hw
        sw = self._probe_xrandr()
        if sw:
            return sw
        self.kind = self.NONE
        self.reason = "no backlight device and no X brightness property"
        return self.NONE

    def _probe_sysfs(self) -> str | None:
        try:
            zones = sorted(Path("/sys/class/backlight").glob("*"))
        except Exception:
            return None
        for z in zones:
            bright, mx = z / "brightness", z / "max_brightness"
            try:
                if bright.exists() and os.access(bright, os.W_OK):
                    self.kind = self.HARDWARE
                    self.reason = f"hardware backlight ({z.name})"
                    self.max = max(1, int(mx.read_text().strip()))
                    self._outputs = [str(z)]
                    return self.kind
            except Exception:
                continue
        return None

    def _probe_xrandr(self) -> str | None:
        if not _have("xrandr"):
            return None
        # The Brightness property is only reported by --verbose; plain
        # --query omits it entirely.
        rc, out = _run(["xrandr", "--verbose"], timeout=4.0)
        if rc != 0:
            return None
        outputs, found = [], False
        for line in out.splitlines():
            m = re.match(r"^(\S+)\s+connected", line)
            if m:
                outputs.append(m.group(1))
                continue
            if re.match(r"\s+Brightness:\s+[0-9.]+\s*$", line):
                found = True
        if not found:
            return None
        self.kind = self.SOFTWARE
        self.reason = ("no backlight device — dimming via the X display "
                       "(software brightness)")
        self.max = 1
        self._outputs = outputs or []
        return self.kind

    # -- access ---------------------------------------------------------
    @property
    def available(self) -> bool:
        return self.kind != self.NONE

    def label(self) -> str:
        return "hardware" if self.kind == self.HARDWARE else "software"

    def get(self) -> float:
        """Current brightness, 0.0 - 1.0.

        The software path shells out to `xrandr --verbose`, which costs about
        190ms because it enumerates every display mode. That is far too slow
        for a UI poll, so the value is cached and only refreshed on demand —
        callers that just changed the brightness already know the answer.
        """
        if self.kind == self.HARDWARE:
            try:
                for z in self._outputs:
                    v = _clamp01(int(
                        (Path(z) / "brightness").read_text().strip()) / self.max)
                    self._cached = v
                    return v
            except Exception:
                pass
        elif self.kind == self.SOFTWARE and self._outputs:
            if self._cached is not None:
                return self._cached
            return self.refresh()
        return self._cached or 0.0

    def refresh(self, timeout: float = 4.0) -> float:
        """Re-read the real value from the system, bypassing the cache."""
        if self.kind == self.SOFTWARE and self._outputs:
            rc, out = _run(["xrandr", "--verbose"], timeout=timeout)
            if rc == 0:
                want = self._outputs[0]
                block, on = [], False
                for line in out.splitlines():
                    if re.match(rf"^{re.escape(want)}\s+connected", line):
                        on = True
                        continue
                    if on:
                        if line and not line.startswith((" ", "\t")):
                            break
                        block.append(line)
                m = re.search(r"Brightness:\s+([0-9.]+)", "\n".join(block))
                if m:
                    self._cached = _clamp01(_f(m.group(1), 1.0))
        return self._cached or 0.0

    def set(self, value: float) -> bool:
        v = _clamp01(_f(value, 0.0))
        if self.kind == self.HARDWARE:
            for z in self._outputs:
                try:
                    (Path(z) / "brightness").write_text(
                        str(int(round(v * self.max))))
                    self._cached = v
                    return True
                except Exception:
                    continue
            return False
        if self.kind == self.SOFTWARE:
            ok = True
            for out_name in self._outputs:
                rc, _ = _run(["xrandr", "--output", out_name,
                              "--brightness", f"{v:.3f}"])
                ok = ok and rc == 0
            if ok:
                self._cached = v   # the server accepted it; trust the write
            return ok
        return False


# --------------------------------------------------------------- audio


class Audio:
    """Master output + default-source (mic) volume and mute.

    Backend 1: pactl (from pulseaudio-utils) — talks the Pulse protocol to
               pipewire-pulse over the socket that is already running.
    Backend 2: pw-cli — PipeWire's own CLI, already present, but per-node
               rather than per-default-device, so it is a weaker fallback.
    """

    PACLT = "pactl"
    PWCLI = "pw-cli"
    NONE = "none"

    _VOL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
    _MUTE_RE = re.compile(r"(yes|no)", re.I)

    def __init__(self):
        self.kind = self.NONE
        self.reason = "no audio control backend found"
        self._pw_nodes: dict[str, int] = {}
        self._pw_ts = 0.0
        self._cache = TTLCache(3.0)
        self.probe()

    def probe(self) -> str:
        if _have(self.PACLT):
            rc, _ = _run([self.PACLT, "info"])
            if rc == 0:
                self.kind = self.PACLT
                self.reason = ""
                return self.kind
        if _have(self.PWCLI):
            self.kind = self.PWCLI
            self.reason = ("pactl not installed — volume via pw-cli "
                           "(per-node, may not follow the default device)")
            return self.kind
        self.kind = self.NONE
        self.reason = "install pulseaudio-utils (pactl) to control volume"
        return self.NONE

    @property
    def available(self) -> bool:
        return self.kind != self.NONE

    # -- pactl ----------------------------------------------------------
    def _pactl_vol(self, kind: str) -> float | None:
        what = "get-sink-volume" if kind == "sink" else "get-source-volume"
        rc, out = _run([self.PACLT, what, "@DEFAULT_%s@" % kind.upper()])
        if rc != 0:
            return None
        m = self._VOL_RE.search(out)
        return _clamp01(_f(m.group(1), 0.0) / 100.0) if m else None

    def _pactl_set(self, kind: str, value: float) -> bool:
        what = "set-sink-volume" if kind == "sink" else "set-source-volume"
        rc, _ = _run([self.PACLT, what, "@DEFAULT_%s@" % kind.upper(),
                      f"{int(round(_clamp01(value) * 100))}%"])
        return rc == 0

    def _pactl_mute(self, kind: str, value: bool) -> bool:
        what = "set-sink-mute" if kind == "sink" else "set-source-mute"
        rc, _ = _run([self.PACLT, what, "@DEFAULT_%s@" % kind.upper(),
                      "1" if value else "0"])
        return rc == 0

    # -- pw-cli fallback -------------------------------------------------
    def _pw_nodes_now(self) -> dict[str, int]:
        if time.monotonic() - self._pw_ts < 5.0 and self._pw_nodes:
            return self._pw_nodes
        rc, out = _run(["pw-cli", "ls", "Node"], timeout=4.0)
        nodes: dict[str, int] = {}
        if rc == 0:
            nid = None
            for line in out.splitlines():
                m = re.match(r"\s*id\s+(\d+),", line)
                if m:
                    nid = int(m.group(1))
                    continue
                m = re.search(r'node\.name\s*=\s*"([^"]+)"', line)
                if m and nid is not None:
                    nodes[m.group(1)] = nid
                m = re.search(r'media\.class\s*=\s*"Audio/(Sink|Source)"', line)
                if m and nid is not None:
                    nodes.setdefault(m.group(1), nid)
        self._pw_nodes = nodes
        self._pw_ts = time.monotonic()
        return nodes

    def _pw_first(self, cls: str) -> int | None:
        nodes = self._pw_nodes_now()
        for name, nid in nodes.items():
            if name.startswith("alsa_output") or cls == "Sink":
                if cls == "Sink":
                    return nid
        return nodes.get(cls)

    def _pw_vol(self, nid: int) -> float | None:
        rc, out = _run(["pw-cli", "get-node-volume", str(nid)])
        if rc != 0:
            return None
        nums = re.findall(r"([0-9]+\.[0-9]+)", out)
        if not nums:
            return None
        return _clamp01(max(_f(n) for n in nums))

    # -- public ----------------------------------------------------------
    def volume(self, kind: str = "sink", fresh: bool = False) -> float | None:
        """0.0 - 1.0, or None when unknown."""
        if not fresh:
            hit = self._cache.get(f"vol:{kind}")
            if hit is not None:
                return hit
        out = self._volume_uncached(kind)
        if out is not None:
            self._cache.put(f"vol:{kind}", out)
        return out

    def _volume_uncached(self, kind: str):
        if self.kind == self.PACLT:
            return self._pactl_vol(kind)
        if self.kind == self.PWCLI:
            nid = self._pw_first("Sink" if kind == "sink" else "Source")
            return self._pw_vol(nid) if nid else None
        return None

    def set_volume(self, kind: str, value: float) -> bool:
        """Set and VERIFY.

        PipeWire accepts `pactl set-source-volume` with exit status 0 and then
        ignores it on a suspended device, so a successful exit code proves
        nothing. Every write is read back before it is reported as done.
        """
        want = _clamp01(value)
        if self.kind == self.PACLT:
            self._pactl_set(kind, want)
        elif self.kind == self.PWCLI:
            nid = self._pw_first("Sink" if kind == "sink" else "Source")
            if not nid:
                return False
            _run(["pw-cli", "set-node-volume", str(nid),
                  f"{int(round(want * 100))}"])
        else:
            return False
        self._cache.clear()
        got = self.volume(kind, fresh=True)
        return got is not None and abs(got - want) <= 0.06

    def muted(self, kind: str = "sink", fresh: bool = False) -> bool | None:
        if not fresh:
            hit = self._cache.get(f"mute:{kind}")
            if hit is not None:
                return hit
        val = self._muted_uncached(kind)
        if val is not None:
            self._cache.put(f"mute:{kind}", val)
        return val

    def _muted_uncached(self, kind: str):
        if self.kind == self.PACLT:
            what = "get-sink-mute" if kind == "sink" else "get-source-mute"
            rc, out = _run([self.PACLT, what, "@DEFAULT_%s@" % kind.upper()])
            if rc == 0:
                m = self._MUTE_RE.search(out)
                if m:
                    return m.group(1).lower() == "yes"
        return None

    def set_muted(self, kind: str, value: bool) -> bool:
        """Set and VERIFY, for the same reason as set_volume."""
        if self.kind == self.PACLT:
            self._pactl_mute(kind, value)
        elif self.kind == self.PWCLI:
            nid = self._pw_first("Sink" if kind == "sink" else "Source")
            if not nid:
                return False
            _run(["pw-cli", "set-node-mute", str(nid),
                  "true" if value else "false"])
        else:
            return False
        self._cache.clear()
        got = self.muted(kind, fresh=True)
        return got is not None and got == bool(value)

    def toggle_mic(self) -> bool | None:
        cur = self.muted("source")
        if cur is None:
            return None
        if not self.set_muted("source", not cur):
            return None
        return (not cur)


# --------------------------------------------------------------- network


class Network:
    """NetworkManager: wifi radio, airplane mode, and the primary link."""

    def __init__(self):
        self.kind = "none"
        self.reason = "NetworkManager (nmcli) not available"
        self.has_wifi = False
        self.has_adapter = False
        self._cache = TTLCache(4.0)
        self.probe()

    def probe(self) -> str:
        if not _have("nmcli"):
            self.kind = "none"
            self.reason = "NetworkManager not available"
            return self.kind
        rc, out = _run(["nmcli", "radio"])
        if rc != 0:
            self.kind = "none"
            self.reason = "NetworkManager did not respond"
            return self.kind
        self.kind = "nmcli"
        self.reason = ""
        rc2, dev = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
        self.has_wifi = "wireless" in dev.lower()
        self.has_adapter = any(
            t in dev for t in (":connected", ":connected:externally"))
        return self.kind

    @property
    def available(self) -> bool:
        return self.kind != "none"

    @property
    def wifi_hardware(self) -> bool:
        rc, _ = _run(["nmcli", "radio", "wifi"])
        return rc == 0

    def wifi_enabled(self) -> bool | None:
        rc, out = _run(["nmcli", "radio", "wifi"])
        if rc != 0:
            return None
        return "enabled" in out.lower()

    def set_wifi(self, on: bool) -> bool:
        self._cache.clear()
        rc, _ = _run(["nmcli", "radio", "wifi", "on" if on else "off"])
        return rc == 0

    def radios_enabled(self, fresh: bool = False) -> bool | None:
        """False when at least one radio is off — i.e. airplane mode is on."""
        if not fresh:
            hit = self._cache.get("radios")
            if hit is not None:
                return hit
        rc, out = _run(["nmcli", "radio"])
        if rc != 0:
            return None
        states = [ln.split()[-1].lower() for ln in out.splitlines() if ln.strip()]
        states = [s for s in states if s in ("enabled", "disabled", "missing")]
        val = bool(states) and all(s != "disabled" for s in states)
        self._cache.put("radios", val)
        return val

    def set_airplane(self, off: bool) -> bool:
        """off=True -> turn every radio off (airplane on)."""
        self._cache.clear()
        rc, _ = _run(["nmcli", "radio", "all", "off" if off else "on"])
        return rc == 0

    def primary_device(self, fresh: bool = False) -> str | None:
        if not fresh:
            hit = self._cache.get("primary")
            if hit is not None:
                return hit
        rc, out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"])
        if rc != 0:
            return None
        found = None
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[2].startswith("connected") \
                    and parts[1] != "loopback":
                found = parts[0]
                break
        self._cache.put("primary", found)
        return found

    def link_up(self, fresh: bool = False) -> bool | None:
        if not fresh:
            hit = self._cache.get("link")
            if hit is not None:
                return hit
        dev = self.primary_device(fresh)
        if not dev:
            return None
        rc, out = _run(["nmcli", "-t", "-f", "DEVICE,STATE", "device"])
        if rc != 0:
            return None
        val = None
        for line in out.splitlines():
            p = line.split(":")
            if p and p[0] == dev:
                val = p[-1].startswith("connected")
                break
        self._cache.put("link", val)
        return val

    def set_link(self, up: bool) -> bool:
        """Bring the primary link up or down by cycling its connection."""
        self._cache.clear()
        rc, out = _run(["nmcli", "-t", "-f", "NAME,DEVICE,STATE", "connection",
                        "--active"])
        if rc != 0:
            return False
        active = [ln.split(":") for ln in out.splitlines() if ln.strip()]
        if not active:
            return False
        name = active[0][0]
        action = "up" if up else "down"
        rc2, _ = _run(["nmcli", "connection", action, name])
        return rc2 == 0


class Bluetooth:
    def __init__(self):
        self.kind = "none"
        self.reason = "bluetoothctl not available"
        self.has_adapter = False
        self.probe()

    def probe(self) -> str:
        if not _have("bluetoothctl"):
            self.kind = "none"
            self.reason = "bluetoothctl not installed"
            return self.kind
        rc, out = _run(["bluetoothctl", "show"], timeout=3.0)
        if rc != 0:
            self.kind = "none"
            self.reason = "no bluetooth adapter"
            return self.kind
        self.kind = "bluetoothctl"
        self.reason = ""
        self.has_adapter = "powered" in out.lower() or "controller" in out.lower()
        return self.kind

    @property
    def available(self) -> bool:
        return self.kind != "none"

    def powered(self) -> bool | None:
        rc, out = _run(["bluetoothctl", "show"], timeout=3.0)
        if rc != 0:
            return None
        m = re.search(r"Powered:\s*(yes|no)", out, re.I)
        return bool(m and m.group(1).lower() == "yes")

    def set_powered(self, on: bool) -> bool:
        rc, _ = _run(["bluetoothctl", "power", "on" if on else "off"],
                     timeout=3.0)
        return rc == 0


class Session:
    """Lock screen (loginctl) and Do Not Disturb (Plasma 6 kded module)."""

    DND_FILE = Path.home() / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"

    def __init__(self):
        self.can_lock = _have("loginctl")
        self.lock_reason = "" if self.can_lock else "loginctl not available"
        self.can_dnd = self.DND_FILE.exists()
        self.dnd_reason = ("" if self.can_dnd else
                           "Plasma desktop settings not found")

    def lock(self) -> bool:
        if not self.can_lock:
            return False
        rc, _ = _run(["loginctl", "lock-session"])
        return rc == 0

    def dnd(self) -> bool | None:
        if not self.can_dnd:
            return None
        try:
            ini = self.DND_FILE.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
        m = re.search(r"^\s*org\.kde\.plasma\.donotdisturb\s*=\s*(true|false)",
                      ini, re.M | re.I)
        return bool(m and m.group(1).lower() == "true")

    def set_dnd(self, on: bool) -> bool:
        """Write the Plasma key in place, preserving every other line."""
        if not self.can_dnd:
            return False
        try:
            text = self.DND_FILE.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False
        entry = f"org.kde.plasma.donotdisturb={'true' if on else 'false'}"
        pat = re.compile(r"^(\s*)org\.kde\.plasma\.donotdisturb\s*=\s*(true|false)\s*$",
                         re.M | re.I)
        if pat.search(text):
            new = pat.sub(lambda m: f"{m.group(1)}{entry}", text)
        elif "[DoNotDisturb]" in text:
            new = re.sub(r"(\[DoNotDisturb\]\s*\n)",
                         lambda m: m.group(1) + entry + "\n", text, count=1)
        else:
            new = text.rstrip("\n") + "\n\n[DoNotDisturb]\n" + entry + "\n"
        if new == text:
            return False
        try:
            self.DND_FILE.write_text(new, encoding="utf-8")
        except Exception:
            return False
        # Ask plasmashell to re-read its settings.
        _run(["qdbus6", "org.kde.plasmashell", "/MainApplication",
              "org.kde.PlasmaShell.reparseConfiguration"], timeout=2.0)
        return True


# --------------------------------------------------------------- net speed


class NetSpeed:
    """Throughput from /proc/net/dev deltas on the primary interface."""

    def __init__(self):
        self._last: tuple[float, tuple[int, int]] | None = None
        self.down_bps = 0.0
        self.up_bps = 0.0

    def _iface(self) -> str | None:
        for dev in _read_net_dev():
            if dev not in ("lo",):
                return dev
        return None

    def sample(self) -> tuple[float, float]:
        now = time.monotonic()
        rows = _read_net_dev()
        total_down = total_up = 0
        for dev, rx, tx in rows:
            if dev == "lo":
                continue
            total_down += rx
            total_up += tx
        cur = (total_down, total_up)
        if self._last is None:
            self._last = (now, cur)
            return 0.0, 0.0
        last_t, last_b = self._last
        dt = now - last_t
        if dt <= 0 or dt > 5.0:
            self._last = (now, cur)
            return 0.0, 0.0
        self._last = (now, cur)
        down = max(0.0, (cur[0] - last_b[0]) * 8.0 / dt)
        up = max(0.0, (cur[1] - last_b[1]) * 8.0 / dt)
        # Exponential smoothing: raw per-second deltas are far too jumpy to
        # drive a needle.
        self.down_bps = self.down_bps * 0.7 + down * 0.3
        self.up_bps = self.up_bps * 0.7 + up * 0.3
        return self.down_bps, self.up_bps


def _read_net_dev() -> list[tuple[str, int, int]]:
    out = []
    try:
        with open("/proc/net/dev", encoding="utf-8") as fh:
            for line in fh.readlines()[2:]:
                if ":" not in line:
                    continue
                name, rest = line.split(":", 1)
                parts = rest.split()
                if len(parts) >= 9:
                    out.append((name.strip(), int(parts[0]), int(parts[8])))
    except Exception:
        return out
    return out


# --------------------------------------------------------------- facade


class Backend:
    """One lazily-probed instance of everything, shared by the whole UI."""

    _instance: "Backend | None" = None

    def __init__(self):
        self.brightness = Brightness()
        self.audio = Audio()
        self.network = Network()
        self.bluetooth = Bluetooth()
        self.session = Session()
        self.speed = NetSpeed()

    @classmethod
    def get(cls) -> "Backend":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reprobe(cls) -> "Backend":
        cls._instance = cls()
        return cls._instance

    def caps(self) -> dict:
        """Capability report consumed by the control centre."""
        wifi_dev = self.network.has_wifi and self.network.wifi_hardware
        return {
            "brightness": {
                "available": self.brightness.available,
                "kind": self.brightness.kind,
                "label": self.brightness.label(),
                "reason": self.brightness.reason,
            },
            "volume": {
                "available": self.audio.available,
                "kind": self.audio.kind,
                "reason": self.audio.reason,
            },
            "network": {
                "available": self.network.available,
                "kind": self.network.kind,
                "reason": self.network.reason,
            },
            "wifi": {
                "available": self.network.available and bool(wifi_dev),
                "kind": self.network.kind if wifi_dev else "none",
                "reason": "" if wifi_dev else "no wireless adapter on this machine",
            },
            "bluetooth": {
                "available": self.bluetooth.available,
                "kind": self.bluetooth.kind,
                "reason": self.bluetooth.reason,
            },
            "lock": {
                "available": self.session.can_lock,
                "kind": "loginctl" if self.session.can_lock else "none",
                "reason": self.session.lock_reason,
            },
            "dnd": {
                "available": self.session.can_dnd,
                "kind": "plasma" if self.session.can_dnd else "none",
                "reason": self.session.dnd_reason,
            },
        }


def format_bps(bps: float) -> str:
    b = max(0.0, bps)
    for unit, div in (("Gb/s", 1e9), ("Mb/s", 1e6), ("kb/s", 1e3)):
        if b >= div:
            return f"{b / div:.1f} {unit}"
    return f"{b / 1000:.0f} kb/s"
