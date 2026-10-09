"""Per-character inverse color + readability guard.

Literal inverse (255-c) is unreadable on mid-gray (127 -> 128, gray on gray),
so: compute per-character average background, invert it, then check WCAG-ish
contrast; if it fails, fall back to black/white by luminance. A 1px outline
in the guard color is drawn around light text.
"""
from __future__ import annotations


def _lin(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def inverse_fg(bg_avg: tuple[int, int, int]) -> tuple[tuple[int, int, int], tuple[int, int, int] | None]:
    """Background average -> (fill, outline_or_None)."""
    r, g, b = (max(0, min(255, int(v))) for v in bg_avg)
    inv = (255 - r, 255 - g, 255 - b)
    if contrast(inv, (r, g, b)) >= 4.5:
        outline = (0, 0, 0) if luminance(inv) > 0.3 else None
        return inv, outline
    # guard: pick black or white by background luminance
    if luminance((r, g, b)) < 0.5:
        return (255, 255, 255), (0, 0, 0)
    return (0, 0, 0), None


def avg_color(img, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """Average RGB of img region (box in img coords). Downsamples for speed."""
    region = img.crop(box)
    small = region.resize((8, 8))
    px = list(small.getdata())
    n = len(px)
    r = sum(p[0] for p in px) // n
    g = sum(p[1] for p in px) // n
    b = sum(p[2] for p in px) // n
    return (r, g, b)
