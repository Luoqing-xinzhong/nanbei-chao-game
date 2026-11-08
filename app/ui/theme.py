from __future__ import annotations

from tkinter import ttk


DEFAULT_PALETTE = {
    "BG": "#eee7d4",
    "PANEL": "#f8f3e6",
    "INK": "#2c261f",
    "MUTED": "#746a5b",
    "ACCENT": "#9d302c",
    "ACCENT_DARK": "#70231f",
    "GOLD": "#b89143",
    "GREEN": "#476d50",
}

BLUE_PALETTE = {
    "BG": "#e7eef7",
    "PANEL": "#f3f7fc",
    "INK": "#1f2b3a",
    "MUTED": "#5d6f83",
    "ACCENT": "#2f5f9e",
    "ACCENT_DARK": "#224a7d",
    "GOLD": "#c5a044",
    "GREEN": "#3f6d56",
}

BG = DEFAULT_PALETTE["BG"]
PANEL = DEFAULT_PALETTE["PANEL"]
INK = DEFAULT_PALETTE["INK"]
MUTED = DEFAULT_PALETTE["MUTED"]
ACCENT = DEFAULT_PALETTE["ACCENT"]
ACCENT_DARK = DEFAULT_PALETTE["ACCENT_DARK"]
GOLD = DEFAULT_PALETTE["GOLD"]
GREEN = DEFAULT_PALETTE["GREEN"]


def use_palette(name: str) -> None:
    """切换全局调色板；name 为 blue 时使用蓝色主题，否则恢复默认主题。"""
    global BG, PANEL, INK, MUTED, ACCENT, ACCENT_DARK, GOLD, GREEN
    palette = BLUE_PALETTE if name == "blue" else DEFAULT_PALETTE
    BG = palette["BG"]
    PANEL = palette["PANEL"]
    INK = palette["INK"]
    MUTED = palette["MUTED"]
    ACCENT = palette["ACCENT"]
    ACCENT_DARK = palette["ACCENT_DARK"]
    GOLD = palette["GOLD"]
    GREEN = palette["GREEN"]


def configure_theme(style: ttk.Style) -> None:
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", font=("Microsoft YaHei UI", 10), background=BG, foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL, relief="solid", borderwidth=1)
    style.configure("Stage.TFrame", background=PANEL, relief="solid", borderwidth=2)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Panel.TLabel", background=PANEL, foreground=INK)
    style.configure("Title.TLabel", font=("Microsoft YaHei UI", 28, "bold"), foreground=ACCENT)
    style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 15, "bold"), foreground=ACCENT_DARK)
    style.configure("Subheading.TLabel", font=("Microsoft YaHei UI", 11, "bold"), foreground=INK)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("TButton", padding=(12, 7))
    style.configure("Accent.TButton", foreground="white", background=ACCENT, font=("Microsoft YaHei UI", 11, "bold"))
    style.map("Accent.TButton", background=[("active", ACCENT_DARK), ("pressed", ACCENT_DARK)])
    style.configure("Phase.TButton", padding=(14, 9), font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("Treeview", rowheight=27, background=PANEL, fieldbackground=PANEL)
    style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("TNotebook", background=BG)
    style.configure("TNotebook.Tab", padding=(15, 7))
    # Local shell styles do not change the palettes of existing detail windows.
    paper, ink, gold, blue = "#f4e7d0", "#3f3025", "#d4ae66", "#06354e"
    style.configure("Dragon.TFrame", background=paper, borderwidth=0, relief="flat")
    style.configure("Dragon.TLabel", background=paper, foreground=ink, font=("Microsoft YaHei UI", 10))
    style.configure("Dragon.Heading.TLabel", background=paper, foreground="#9e332b", font=("Microsoft YaHei UI", 12, "bold"))
    style.configure("Dragon.TButton", background="#f8edda", foreground=ink, padding=(5, 7),
                    bordercolor=gold, lightcolor=gold, darkcolor=gold, font=("Microsoft YaHei UI", 10))
    style.map("Dragon.TButton", background=[("active", "#ead5ae"), ("pressed", "#dfc38d")])
    style.configure("Dragon.Next.TButton", background=blue, foreground=gold, padding=(8, 10),
                    font=("Microsoft YaHei UI", 11, "bold"))
    style.map("Dragon.Next.TButton", background=[("active", "#104b67"), ("pressed", "#022b42")])
    style.configure("Dragon.TNotebook", background=paper, borderwidth=0)
    style.configure("Dragon.TNotebook.Tab", background=paper, foreground=ink, padding=(16, 6))
    style.map("Dragon.TNotebook.Tab", background=[("selected", blue)], foreground=[("selected", gold)])
    style.configure("Dragon.Treeview", background=paper, fieldbackground=paper, foreground=ink,
                    rowheight=27, borderwidth=0, font=("Microsoft YaHei UI", 9))
    style.configure("Dragon.Treeview.Heading", background=paper, foreground=ink,
                    font=("Microsoft YaHei UI", 9, "bold"))
