"""Fallback overlay for non-X11 (Wayland GNOME, Windows, macOS).

tkinter topmost borderless window with a Text widget; per-character colors
via tags. No true per-pixel transparency here (Tk limits) — small dark pill.
Same 3-line protocol + drag + show/hide as the X11 overlay.
"""
from __future__ import annotations

import os
import tkinter as tk

CONFIG_DIR = os.path.expanduser("~/.config/spotify-lyrics")
POS_FILE = os.path.join(CONFIG_DIR, "pos.json")


def load_pos() -> tuple[int, int]:
    try:
        import json
        with open(POS_FILE) as f:
            d = json.load(f)
        return int(d.get("x", 100)), int(d.get("y", 100))
    except (OSError, ValueError, KeyError):
        return 100, 100


def save_pos(x: int, y: int) -> None:
    try:
        import json
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(POS_FILE, "w") as f:
            json.dump({"x": int(x), "y": int(y)}, f)
    except OSError:
        pass


class TkOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("spotify-lyrics")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        try:
            self.root.wm_attributes("-alpha", 0.93)
        except tk.TclError:
            pass
        try:
            self.root.wm_attributes("-type", "dock")
        except tk.TclError:
            pass
        x, y = load_pos()
        swd, sht = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(-280, min(x, swd - 120))
        y = max(-60, min(y, sht - 60))
        self.root.geometry(f"+{x}+{y}")
        self.text = tk.Text(self.root, borderwidth=0, highlightthickness=0,
                            bg="#101010", relief="flat", wrap="none",
                            cursor="fleur")
        self.text.configure(state="disabled")
        self.text.pack()
        self.visible = False
        self.locked = False
        self._dx = self._dy = 0
        self.root.bind("<ButtonPress-1>", self._press)
        self.root.bind("<B1-Motion>", self._move)
        self.root.bind("<ButtonRelease-1>", self._release)
        self.root.withdraw()

    def _press(self, e):
        if self.locked:
            return
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _move(self, e):
        if self.locked:
            return
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _release(self, e):
        save_pos(self.root.winfo_x(), self.root.winfo_y())

    def _hex(self, rgb, alpha=255):
        r, g, b = (max(0, min(255, int(v))) for v in rgb)
        return f"#{r:02x}{g:02x}{b:02x}"

    def show_lines(self, styled):
        """styled: [(text, [(char, fill_rgb)], size, bold)] — per-char colors."""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        ntag = 0
        for text, chars, size, bold in styled:
            if self.text.index("end-1c") != "1.0":
                self.text.insert("end", "\n")
            for ch, fill in chars:
                idx0 = self.text.index("end-1c")
                self.text.insert("end", ch)
                tag = f"c{ntag}"
                ntag += 1
                self.text.tag_add(tag, idx0, "end-1c")
                self.text.tag_config(tag, foreground=self._hex(fill),
                                     font=("DejaVu Sans", size,
                                           "bold" if bold else "normal"))
        self.text.configure(state="disabled")

    def show(self):
        self.root.deiconify()
        self.visible = True

    def hide(self):
        self.root.withdraw()
        self.visible = False

    def toggle(self):
        self.hide() if self.visible else self.show()

    def set_locked(self, locked: bool):
        self.locked = locked  # Tk has no OS click-through; drag disabled only

    def pump(self):
        self.root.update_idletasks()
        self.root.update()

    def geom_center(self):
        return (self.root.winfo_x(), self.root.winfo_y(),
                self.root.winfo_width(), self.root.winfo_height())

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass
