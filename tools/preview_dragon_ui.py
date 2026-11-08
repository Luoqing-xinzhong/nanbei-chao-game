"""Read-only UI preview. Never reads or writes player save slots.

Run from game/: python tools/preview_dragon_ui.py --capture
"""
from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.content.v1_2.scenario import load_v12_state
from app.content.v1_3.scenario import load_default_wenjiao_state
from app.ui import theme
from app.ui.main_screen import MainGameScreen
from app.ui.sidebar_stages import sidebar_for
from app.v11 import load_v11_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("1.1", "1.2", "wenjiao_south", "blood_tears"), default="wenjiao_south")
    parser.add_argument("--phase", type=int, default=0)
    parser.add_argument("--size", default="1440x900")
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    state = load_v11_state() if args.scenario == "1.1" else load_v12_state() if args.scenario == "1.2" else load_default_wenjiao_state()
    if args.scenario == "blood_tears":
        # Layout fixture only, not an alternate game-start route.
        state.flags["scenario_id"] = "blood_tears"
        state.year, state.month = 447, 1
    state.phase_index = args.phase
    root = tk.Tk()
    root.title("金戈铁马 · 界面预览（不保存游戏）")
    root.geometry(args.size + "+0+0")
    theme.use_palette("blue")
    theme.configure_theme(ttk.Style(root))
    errors = []

    def error(kind, value, traceback):
        errors.append(str(value))
        sys.__excepthook__(kind, value, traceback)

    root.report_callback_exception = error
    callbacks = {key: lambda *unused: None for key in ("status", "menu", "save", "stage", "changed")}
    screen = MainGameScreen(root, state, callbacks)
    panel = sidebar_for(state)(screen.stage_host, state, lambda: None, screen.refresh)
    screen.set_stage_panel(panel)

    def capture():
        from PIL import ImageGrab

        root.update_idletasks()
        folder = Path(__file__).resolve().parents[1] / "artifacts" / "ui"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"dragon_{args.scenario}_{args.phase}_{args.size}.png"
        if os.name == "nt":
            import ctypes

            # Capture the HWND, not a Tk logical-pixel bbox (Windows may be at 150% DPI).
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            ImageGrab.grab(window=hwnd).save(folder / name)
        else:
            rect = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx()+root.winfo_width(), root.winfo_rooty()+root.winfo_height())
            ImageGrab.grab(bbox=rect).save(folder / name)
        print(folder / name)
        print("sidebar", panel.winfo_width(), panel.winfo_height(), "map", screen.map_frame.winfo_width(), screen.map_frame.winfo_height())
        print("next_button", panel.next_button.winfo_ismapped(), "callback_errors", errors)
        root.destroy()

    if args.capture:
        root.after(1200, capture)
    root.mainloop()
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
