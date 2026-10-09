"""CPU temperature readout (best-effort, never raises)."""
from __future__ import annotations

from pathlib import Path


def _from_psutil() -> float | None:
    try:
        import psutil
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    if not temps:
        return None
    # preferred package sensors first
    for key in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz", "soc_thermal"):
        entries = temps.get(key)
        if entries:
            if key == "coretemp":
                pkg = [e.current for e in entries
                       if "package" in (e.label or "").lower() and e.current]
                if pkg:
                    return float(pkg[0])
            vals = [e.current for e in entries if e.current]
            if vals:
                return float(max(vals))
    # anything with a reading
    vals = [e.current for v in temps.values() for e in v if e.current]
    return float(max(vals)) if vals else None


def _from_sysfs() -> float | None:
    base = Path("/sys/class/thermal")
    best: float | None = None
    try:
        zones = sorted(base.glob("thermal_zone*"))
    except Exception:
        return None
    preferred = ("x86_pkg_temp", "cpu-thermal", "cpu_thermal", "k10temp")
    ordered = sorted(zones, key=lambda z: (
        0 if _zone_type(z) in preferred else 1, z.name))
    for z in ordered:
        try:
            kind = _zone_type(z)
            raw = (z / "temp").read_text().strip()
            c = int(raw) / 1000.0
        except Exception:
            continue
        if -40.0 < c < 125.0:
            best = c
            if kind in preferred:
                break
    return best


def _zone_type(z: Path) -> str:
    try:
        return (z / "type").read_text().strip()
    except Exception:
        return ""


def get_cpu_temp() -> float | None:
    """Return CPU temperature in °C, or None when no sensor is readable."""
    return _from_psutil() or _from_sysfs()


def format_temp(t: float | None, short: bool = False) -> str:
    if t is None:
        return "—"
    return f"{t:.0f}°" if short else f"{t:.1f}°C"
