"""Transparent always-on-top overlay for X11 (python-xlib, ARGB).

True per-pixel transparency: 32-bit override-redirect window, only text
pixels have alpha > 0. Draggable, never in taskbar, kept above.
Click-through lock via SHAPE input mask (degrades gracefully).
"""
from __future__ import annotations

import os
import sys
import time

from Xlib import X, display
from Xlib.ext import shape

from inverse import avg_color, inverse_fg

CONFIG_DIR = os.path.expanduser("~/.config/spotify-lyrics")
POS_FILE = os.path.join(CONFIG_DIR, "pos.json")

PADX, PADY, GAP = 28, 22, 10
FONT_CUR = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
FONT_CTX = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)


def load_pos(screen_w: int, screen_h: int, win_w: int, win_h: int) -> tuple[int, int]:
    try:
        import json
        with open(POS_FILE) as f:
            d = json.load(f)
        return max(0, int(d.get("x", 0))), max(0, int(d.get("y", 0)))
    except (OSError, ValueError, KeyError):
        return max(0, (screen_w - win_w) // 2), max(0, screen_h - win_h - 90)


def save_pos(x: int, y: int) -> None:
    try:
        import json
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(POS_FILE, "w") as f:
            json.dump({"x": int(x), "y": int(y)}, f)
    except OSError:
        pass


class X11Overlay:
    def __init__(self):
        from PIL import ImageFont

        self.d = display.Display()
        self.screen = self.d.screen()
        self.root = self.screen.root
        visual = None
        for dep in self.screen.allowed_depths:
            if dep.depth == 32:
                for v in dep.visuals:
                    if v.visual_class == 4:  # TrueColor
                        visual = v.visual_id
                        break
            if visual:
                break
        if visual is None:
            raise RuntimeError("No 32-bit TrueColor visual (need compositor/X11 ARGB).")
        self.cmap = self.root.create_colormap(visual, X.AllocNone)
        sw, sh = self.screen.width_in_pixels, self.screen.height_in_pixels
        x, y = load_pos(sw, sh, 600, 140)
        x, y = self._clamp(x, y, 600, 140)
        self.win = self.root.create_window(
            x, y, 600, 140, 0, 32, X.InputOutput, visual,
            background_pixel=0, border_pixel=0, colormap=self.cmap,
            override_redirect=True,
            event_mask=(X.ExposureMask | X.ButtonPressMask | X.ButtonReleaseMask
                        | X.Button1MotionMask | X.StructureNotifyMask),
        )
        self.gc = self.win.create_gc(graphics_exposures=False)
        above = self.d.get_atom("_NET_WM_STATE_ABOVE")
        skip = self.d.get_atom("_NET_WM_STATE_SKIP_TASKBAR")
        self.win.change_property(self.d.get_atom("_NET_WM_STATE"),
                                 self.d.get_atom("ATOM"), 32, [above, skip])
        self.win.change_property(self.d.get_atom("_NET_WM_WINDOW_TYPE"),
                                 self.d.get_atom("ATOM"), 32,
                                 [self.d.get_atom("_NET_WM_WINDOW_TYPE_DOCK")])
        self.win.set_wm_name("spotify-lyrics")
        self.win.set_wm_class("spotify-lyrics", "SpotifyLyrics")
        self.W, self.H = 600, 140
        self._img_bytes: bytes | None = None
        self.visible = False
        self.locked = False
        self.dragging = False
        self._dx = self._dy = 0
        self._shape_ok: bool | None = None

        def _font(path_size):
            path, size = path_size
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                return ImageFont.load_default()

        self.f_cur = _font(FONT_CUR)
        self.f_ctx = _font(FONT_CTX)

    def _clamp(self, x: int, y: int, w: int, h: int) -> tuple[int, int]:
        """Keep at least a grab-handle visible: never fully off-screen."""
        sw, sh = self.screen.width_in_pixels, self.screen.height_in_pixels
        x = max(-(max(1, w) - 120), min(int(x), sw - 120))
        y = max(-(max(1, h) - 60), min(int(y), sh - 60))
        return x, y

    # ---------------------------------------------------------- window ops
    def show(self):
        self.win.map()
        self.d.sync()
        self.visible = True

    def hide(self):
        self.win.unmap()
        self.d.sync()
        self.visible = False

    def toggle(self):
        self.hide() if self.visible else self.show()

    def set_locked(self, locked: bool):
        """Locked = clicks pass through to windows behind (drag disabled)."""
        self.locked = locked
        try:
            if locked:
                pix = self.win.create_pixmap(1, 1, 1)
                g = pix.create_gc(foreground=0, background=0)
                pix.fill_rectangle(g, 0, 0, 1, 1)
                self.win.shape_mask(shape.SO.Set, shape.SK.Input, 0, 0, pix)
            else:
                # restore input = full window via an all-ones mask
                pix = self.win.create_pixmap(self.W, self.H, 1)
                g = pix.create_gc(foreground=1, background=1)
                pix.fill_rectangle(g, 0, 0, self.W, self.H)
                self.win.shape_mask(shape.SO.Set, shape.SK.Input, 0, 0, pix)
            self._shape_ok = True
        except Exception as e:
            self._shape_ok = False
            print(f"[overlay] click-through unavailable ({e}); "
                  "window stays draggable instead.", file=sys.stderr)

    def geom(self) -> tuple[int, int]:
        g = self.win.get_geometry()
        return g.x, g.y  # parent is root -> screen coords

    # ---------------------------------------------------------- rendering
    def _layout(self, lines):
        """lines: [(text, font, alpha)]. Returns (W,H,items)."""
        from PIL import ImageDraw, Image

        tmp = Image.new("RGBA", (8, 8))
        dr = ImageDraw.Draw(tmp)
        widths, heights, char_xs = [], [], []
        for text, font, _ in lines:
            xs, x = [], 0.0
            for ch in text:
                xs.append(x)
                try:
                    x += font.getlength(ch)
                except Exception:
                    x += dr.textlength(ch, font=font)
            char_xs.append(xs)
            try:
                w = dr.textlength(text, font=font)
            except Exception:
                w = x
            widths.append(w)
            bbox = font.getbbox("Ag")
            heights.append((bbox[3] - bbox[1]) + 8)
        W = int(max(widths or [200])) + 2 * PADX
        H = int(sum(heights)) + GAP * (len(lines) - 1) + 2 * PADY
        return W, H, widths, heights, char_xs

    def render(self, lines, bg_img):
        """Draw 3 lines with per-character inverse colors. Returns bytes."""
        from PIL import Image, ImageDraw

        W, H, widths, heights, char_xs = self._layout(lines)
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        y = PADY
        for li, (text, font, alpha) in enumerate(lines):
            h = heights[li]
            for ci, ch in enumerate(text):
                cx = PADX + char_xs[li][ci]
                # char box in overlay coords -> bg coords (bg covers whole overlay)
                try:
                    adv = font.getlength(ch)
                except Exception:
                    adv = dr.textlength(ch, font=font)
                box = (int(cx), int(y), int(cx + max(1, adv)), int(y + h))
                try:
                    avg = avg_color(bg_img, box)
                except Exception:
                    avg = (0, 0, 0)
                fill, outline = inverse_fg(avg)
                kw = {"fill": fill + (alpha,)}
                if outline:
                    kw.update(stroke_width=1, stroke_fill=outline + (alpha,))
                dr.text((cx, y), ch, font=font, **kw)
            y += h + GAP
        self.W, self.H = W, H
        data = img.tobytes("raw", "BGRA") if sys.byteorder == "little" \
            else img.tobytes("raw", "ARGB")
        self._img_bytes = data
        return data

    def present(self, data: bytes):
        g = self.win.get_geometry()
        if g.width != self.W or g.height != self.H:
            self.win.configure(width=self.W, height=self.H)
        # X requests are capped at 65535*4 bytes -> upload in horizontal bands
        bpp = 4
        band = max(1, 60000 // max(1, self.W))
        row = self.W * bpp
        for y0 in range(0, self.H, band):
            h = min(band, self.H - y0)
            chunk = data[y0 * row:(y0 + h) * row]
            self.win.put_image(self.gc, 0, y0, self.W, h,
                               X.ZPixmap, 32, 0, chunk)
        self.d.sync()

    def refresh_transient_hide(self):
        """Unmap for clean screen sampling. Caller re-shows + re-presents."""
        was = self.visible
        if was:
            self.hide()
        return was

    # ---------------------------------------------------------- events
    def pump(self):
        """Handle pending X events. Returns 'moved' when drag ends."""
        moved = False
        while self.d.pending_events():
            ev = self.d.next_event()
            et = ev.type
            if et == X.Expose and self._img_bytes:
                self.present(self._img_bytes)
            elif et == X.ButtonPress and ev.detail == 1 and not self.locked:
                self.dragging = True
                g = self.win.get_geometry()
                self._dx = ev.root_x - g.x
                self._dy = ev.root_y - g.y
            elif et == X.MotionNotify and self.dragging:
                nx, ny = self._clamp(ev.root_x - self._dx, ev.root_y - self._dy,
                                     self.W, self.H)
                self.win.configure(x=nx, y=ny)
            elif et == X.ButtonRelease and ev.detail == 1 and self.dragging:
                self.dragging = False
                g = self.win.get_geometry()
                save_pos(g.x, g.y)
                moved = True
        return moved

    def fileno(self):
        return self.d.fileno()

    def close(self):
        try:
            self.win.unmap()
            self.d.sync()
        except Exception:
            pass
        self.d.close()
