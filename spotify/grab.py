"""Screen sampling behind the overlay.

Primary: mss (XShm on X11, BitBlt on Windows). Caller must hide/unmap the
overlay before grabbing so it doesn't sample itself.
"""
from __future__ import annotations


def grab_region(x: int, y: int, w: int, h: int):
    """Return a PIL RGB image of the screen region. Raises on failure."""
    import mss
    from PIL import Image

    x, y, w, h = int(x), int(y), int(w), int(h)
    if w <= 0 or h <= 0:
        raise ValueError("empty region")
    with mss.MSS() as sct:
        mon = {"left": x, "top": y, "width": w, "height": h}
        shot = sct.grab(mon)
        return Image.frombytes("RGB", (shot.width, shot.height), shot.rgb)
