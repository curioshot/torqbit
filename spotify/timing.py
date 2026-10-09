"""Timing core: anchor poll + local interpolation + line index via bisect."""
from __future__ import annotations

import bisect
import time
from dataclasses import dataclass


@dataclass
class Anchor:
    reported_ms: int = 0
    mono: float = 0.0
    playing: bool = False
    track_key: str = ""


def estimate_ms(a: Anchor, now: float | None = None) -> int:
    now = time.monotonic() if now is None else now
    if a.playing:
        return int(a.reported_ms + (now - a.mono) * 1000)
    return a.reported_ms


def index_at(times: list[int], progress_ms: int) -> int:
    """Current line index for progress. -1 if before first line."""
    if not times:
        return -1
    return bisect.bisect_right(times, progress_ms) - 1


def needs_reanchor(a: Anchor, reported_ms: int, playing: bool,
                   track_key: str, drift_ms: int = 1500) -> bool:
    if track_key != a.track_key:
        return True
    if playing != a.playing:
        return True
    return abs(reported_ms - estimate_ms(a)) > drift_ms
