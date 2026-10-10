"""CPU temperature readout (best-effort, never raises).

All sampling is cheap but not free: `_from_sysfs` stats and reads a file per
thermal zone, and this runs from a Qt timer. Results are therefore cached
for a moment — three callers on three different cadences used to each
re-read every zone independently.
"""
from __future__ import annotations

import time
from pathlib import Path

# Overridable so tests can point at a fixture tree.
_SYSFS_THERMAL = "/sys/class/thermal"

# Preferred psutil sensor chips, in order.
PREFERRED_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal",
                     "acpitz", "soc_thermal")
# Preferred sysfs zone types, in order.
PREFERRED_ZONES = ("x86_pkg_temp", "cpu-thermal", "cpu_thermal", "k10temp")
# Anything outside this is a broken read, not a temperature.
PLAUSIBLE_MIN_C, PLAUSIBLE_MAX_C = -40.0, 125.0
# How long a reading stays valid. The UI polls at 1.5-3s.
CACHE_TTL_S = 2.0

_cache: dict = {"ts": 0.0, "value": None}


def _from_psutil() -> float | None:
    try:
        import psutil
        temps = psutil.sensors_temperatures()
    except Exception:
        return None
    if not temps:
        return None
    for key in PREFERRED_SENSORS:
        entries = temps.get(key)
        if not entries:
            continue
        if key == "coretemp":
            # coretemp reports every core; the package sensor is the CPU.
            pkg = [e.current for e in entries
                   if "package" in (e.label or "").lower() and e.current]
            if pkg:
                return float(pkg[0])
        vals = [e.current for e in entries if e.current]
        if vals:
            return float(max(vals))
    vals = [e.current for v in temps.values() for e in v if e.current]
    return float(max(vals)) if vals else None


def _zone_type(z: Path) -> str:
    try:
        return (z / "type").read_text().strip()
    except Exception:
        return ""


def _from_sysfs() -> float | None:
    base = Path(_SYSFS_THERMAL)
    best: float | None = None
    try:
        zones = sorted(base.glob("thermal_zone*"))
    except Exception:
        return None
    if not zones:
        return None
    # Read each zone's type exactly once. It used to be read twice: once in
    # the sort key and once again in the loop body.
    kinds = {z: _zone_type(z) for z in zones}
    ordered = sorted(zones, key=lambda z: (
        0 if kinds[z] in PREFERRED_ZONES else 1, z.name))
    for z in ordered:
        try:
            raw = (z / "temp").read_text().strip()
            c = int(raw) / 1000.0
        except Exception:
            continue
        if PLAUSIBLE_MIN_C < c < PLAUSIBLE_MAX_C:
            best = c
            if kinds[z] in PREFERRED_ZONES:
                break
    return best


def get_cpu_temp(fresh: bool = False) -> float | None:
    """Return CPU temperature in °C, or None when no sensor is readable.

    Note the `is None` check rather than `or`: a legitimate reading of 0.0 °C
    is falsy, and `psutil or sysfs` used to throw it away and report a
    different sensor's value instead.
    """
    if not fresh:
        now = time.monotonic()
        if now - _cache["ts"] < CACHE_TTL_S:
            return _cache["value"]
    value = _from_psutil()
    if value is None:
        value = _from_sysfs()
    _cache["ts"] = time.monotonic()
    _cache["value"] = value
    return value


def format_temp(t: float | None, short: bool = False) -> str:
    if t is None:
        return "—"
    return f"{t:.0f}°" if short else f"{t:.1f}°C"
