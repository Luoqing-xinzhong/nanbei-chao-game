"""Responsive shell artwork and hit areas for the four Jin-Ge-Tie-Ma scenarios.

Only the frame is stretched to fill the window. The live MapView remains a
separate, aspect-preserving viewport with its own world coordinates.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from PIL import Image, ImageTk

from ..constants import RESOURCES_DIR

ART_PATH = RESOURCES_DIR / "common" / "ui" / "dragon_frame.png"
ART_SIZE = (1671, 941)
PAPER = "#f4e7d0"
INK = "#3f3025"
BLUE = "#06354e"
GOLD = "#d4ae66"
RED = "#9e332b"

# Inner bounds deliberately stop short of the painted gold frame.
REGIONS = {
    "stage": (26, 237, 382, 844),
    "map": (414, 220, 1228, 829),
    "logs": (1264, 417, 1637, 788),
    "state": (1265, 178, 1635, 400),
}


def scaled_rect(name: str, width: int, height: int) -> tuple[int, int, int, int]:
    """Return x/y/width/height in the full-bleed artwork coordinate system."""
    left, top, right, bottom = REGIONS[name]
    sx, sy = max(1, width) / ART_SIZE[0], max(1, height) / ART_SIZE[1]
    x, y = round(left * sx), round(top * sy)
    return x, y, max(1, round(right * sx) - x), max(1, round(bottom * sy) - y)


class DragonBackdrop(tk.Canvas):
    def __init__(self, master, on_status: Callable, on_menu: Callable, on_save: Callable):
        super().__init__(master, background=BLUE, borderwidth=0, highlightthickness=0)
        with Image.open(ART_PATH) as source:
            self._source = source.convert("RGB")
        self._photo = None
        self._image_size = (0, 0)
        self.on_status = on_status
        self.on_menu = on_menu
        self.on_save = on_save
        self.phase_names: tuple[str, ...] = ()
        self.phase_index = 0
        self.date_text = ""
        self.state_lines: list[str] = []
        self._resize_job = None
        self.bind("<Configure>", self._resize)
        self.bind("<Destroy>", self._destroy, add="+")
        for key in ("court", "families", "economy", "parties", "modifiers", "military", "diplomacy"):
            self._bind_action(f"nav_{key}", lambda kind=key: self.on_status(kind))
        self._bind_action("menu", self.on_menu)
        self._bind_action("save", self.on_save)

    def _bind_action(self, tag, callback):
        self.tag_bind(tag, "<ButtonRelease-1>", lambda _e: callback())
        self.tag_bind(tag, "<Enter>", lambda _e: self.configure(cursor="hand2"))
        self.tag_bind(tag, "<Leave>", lambda _e: self.configure(cursor=""))

    def _destroy(self, event):
        if event.widget is self and self._resize_job is not None:
            self.after_cancel(self._resize_job)
            self._resize_job = None

    def _resize(self, _event=None):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, self.redraw)

    def redraw(self):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = None
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        if (width, height) != self._image_size:
            self._photo = ImageTk.PhotoImage(self._source.resize((width, height), Image.Resampling.LANCZOS), master=self)
            self._image_size = (width, height)
            self.delete("art")
            self.create_image(0, 0, image=self._photo, anchor="nw", tags="art")
            self.tag_lower("art")
        self.delete("overlay")
        sx, sy = width / ART_SIZE[0], height / ART_SIZE[1]
        font_size = max(11, min(21, round(16 * min(sx, sy))))

        def text(x, y, value, color=INK, size=None, **kwargs):
            return self.create_text(
                x * sx, y * sy, text=value, fill=color,
                font=("Microsoft YaHei UI", -(size or font_size)), tags="overlay", **kwargs,
            )

        nav = (("朝堂", "court"), ("家族", "families"), ("经济", "economy"),
               ("政党", "parties"), ("修正", "modifiers"),
               ("军事状态", "military"), ("外交状态", "diplomacy"))
        for index, (label, key) in enumerate(nav):
            left, right = 235 + index * 167, 235 + (index + 1) * 167
            tag = f"nav_{key}"
            self.create_rectangle(left * sx, 81 * sy, right * sx, 122 * sy,
                                  fill=BLUE, outline="", tags=("overlay", tag))
            item = text((left + right) / 2, 102, label, GOLD)
            self.addtag_withtag(tag, item)
            if index:
                self.create_line(left * sx, 89 * sy, left * sx, 115 * sy,
                                 fill=GOLD, tags="overlay")

        # Replace the five blank baked-in chips so 1.1/1.2's four stages also fit.
        self.create_rectangle(410 * sx, 145 * sy, 1234 * sx, 204 * sy,
                              fill=PAPER, outline="", tags="overlay")
        count = max(1, len(self.phase_names))
        chip_width = 780 / count
        for index, phase in enumerate(self.phase_names):
            left = 437 + index * chip_width
            right = left + chip_width - 17
            active = index == self.phase_index
            coords = (left+10, 154, right-10, 154, right, 173, right-10, 192,
                      left+10, 192, left, 173)
            self.create_polygon(
                *(point * (sx if i % 2 == 0 else sy) for i, point in enumerate(coords)),
                fill=BLUE if active else "#f7ecd7", outline=GOLD, width=2, tags="overlay",
            )
            text((left + right) / 2, 173, phase, GOLD if active else INK)
            if index < count - 1:
                text(right + 9, 173, "›", GOLD)
        # No bindings on phase chips: they are progress indicators, never jumps.
        text(32, 165, "金 戈 铁 马", GOLD, anchor="w")
        self.create_rectangle(25*sx, 183*sy, 399*sx, 207*sy,
                              fill=PAPER, outline="", tags="overlay")
        text(32, 195, self.date_text, INK, size=max(11, font_size-1), anchor="w")

        text(1273, 177, "国 势", RED, size=font_size+3, anchor="nw")
        for index, line in enumerate(self.state_lines):
            text(1273, 216 + index * 27, line, anchor="nw", width=345 * sx)
        for label, left, right, callback, tag in (
            ("主菜单", 1304, 1447, self.on_menu, "menu"),
            ("存档", 1450, 1590, self.on_save, "save"),
        ):
            item = self.create_rectangle(left*sx, 841*sy, right*sx, 895*sy,
                                         fill=BLUE, outline="", tags=("overlay", tag))
            item = text((left+right)/2, 867, label, GOLD)
            self.addtag_withtag(tag, item)
