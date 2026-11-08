from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable

from ..rules.treasury import treasury_balance
from . import theme


def truncate_slider_value(value: float) -> float:
    """Keep at most one decimal and always truncate toward zero to protect hard limits."""
    return math.floor(max(0.0, float(value)) * 10 + 1e-9) / 10


def center_window(window: tk.Toplevel, width: int, height: int) -> None:
    """按给定尺寸将窗口放在当前屏幕正中央。"""
    window.update_idletasks()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = max(0, (screen_width - width) // 2)
    y = max(0, (screen_height - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def choose_item(parent, title: str, prompt: str, items: Iterable[tuple[str, object]]) -> object | None:
    values = list(items)
    if not values:
        return None
    window = tk.Toplevel(parent)
    window.title(title)
    window.transient(parent.winfo_toplevel())
    window.geometry("460x480")
    window.minsize(360, 320)
    window.configure(background=theme.PANEL)
    ttk.Label(window, text=prompt, style="Heading.TLabel", wraplength=410).pack(anchor="w", padx=20, pady=(18, 10))
    frame = ttk.Frame(window, style="Panel.TFrame")
    frame.pack(fill="both", expand=True, padx=20, pady=8)
    box = tk.Listbox(frame, font=("Microsoft YaHei UI", 11), activestyle="none", background=theme.PANEL, borderwidth=0, highlightthickness=0)
    bar = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
    box.configure(yscrollcommand=bar.set)
    box.pack(side="left", fill="both", expand=True, padx=8, pady=8)
    bar.pack(side="right", fill="y")
    for label, _ in values:
        box.insert("end", label)
    box.selection_set(0)
    result = {"value": None}

    def accept(_event=None):
        selected = box.curselection()
        if selected:
            result["value"] = values[selected[0]][1]
        window.destroy()

    controls = ttk.Frame(window, style="Panel.TFrame")
    controls.pack(fill="x", padx=20, pady=(0, 18))
    ttk.Button(controls, text="确定", style="Accent.TButton", command=accept).pack(side="right", padx=(8, 0))
    ttk.Button(controls, text="取消", command=window.destroy).pack(side="right")
    box.bind("<Double-Button-1>", accept)
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.grab_set()
    parent.wait_window(window)
    return result["value"]


def amount_slider_dialog(
    parent,
    title: str,
    prompt: str,
    maximum: float,
    *,
    initial: float | None = None,
    resolution: float = 0.1,
    formatter: Callable[[float], str] | None = None,
    markers: Iterable[tuple[float, str, str]] | None = None,
) -> float | None:
    """Select a positive numeric amount using a slider without keyboard entry."""
    maximum = truncate_slider_value(maximum)
    if maximum <= 0:
        return None
    resolution = min(maximum, max(0.1, truncate_slider_value(resolution)))
    requested_initial = truncate_slider_value(initial if initial is not None else maximum / 2)
    starting_value = min(maximum, max(resolution, requested_initial))
    result: dict[str, float | None] = {"value": None}
    window = tk.Toplevel(parent)
    window.title(title)
    window.transient(parent.winfo_toplevel())
    window.resizable(False, False)
    window.configure(background=theme.PANEL)
    ttk.Label(window, text=title, style="Heading.TLabel").pack(anchor="w", padx=24, pady=(20, 5))
    ttk.Label(window, text=prompt, style="Muted.TLabel", wraplength=510).pack(anchor="w", padx=24)
    amount = tk.DoubleVar(value=starting_value)
    detail = tk.StringVar()

    def refresh(_value=None):
        selected = truncate_slider_value(amount.get())
        detail.set(formatter(selected) if formatter else f"已选择：{selected:g}单位")

    slider_length = 500
    scale = tk.Scale(
        window,
        from_=resolution,
        to=maximum,
        resolution=resolution,
        orient="horizontal",
        variable=amount,
        command=refresh,
        showvalue=False,
        background=theme.PANEL,
        highlightthickness=0,
        length=slider_length,
    )
    scale.pack(fill="x", padx=24, pady=(18, 5))
    visible_markers = [
        (min(maximum, max(resolution, float(value))), color, label)
        for value, color, label in (markers or [])
        if float(value) <= maximum + 1e-9
    ]
    if visible_markers:
        marker_canvas = tk.Canvas(
            window, width=slider_length, height=28, background=theme.PANEL,
            highlightthickness=0, borderwidth=0,
        )
        marker_canvas.pack(fill="x", padx=24, pady=(0, 2))
        usable = slider_length - 20
        for value, color, label in visible_markers:
            ratio = 0.0 if maximum <= resolution else (value - resolution) / (maximum - resolution)
            x = 10 + usable * min(1.0, max(0.0, ratio))
            marker_canvas.create_line(x, 0, x, 14, fill=color, width=3)
            marker_canvas.create_text(x, 21, text=label, fill=color, font=("Microsoft YaHei UI", 8))
    ttk.Label(window, textvariable=detail, style="Panel.TLabel").pack(anchor="w", padx=24)
    refresh()

    def accept():
        result["value"] = truncate_slider_value(amount.get())
        window.destroy()

    controls = ttk.Frame(window, style="Panel.TFrame")
    controls.pack(fill="x", padx=24, pady=(20, 18))
    ttk.Button(controls, text="确认调运", style="Accent.TButton", command=accept).pack(side="right", padx=(8, 0))
    ttk.Button(controls, text="取消", command=window.destroy).pack(side="right")
    center_window(window, 560, 285 if visible_markers else 250)
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.grab_set()
    parent.wait_window(window)
    return result["value"]


def peace_treaty(parent, state, target_id: int) -> dict | None:
    """编辑双向割地、赔款和臣服条款。"""
    from ..rules.diplomacy import occupied_regions

    target = state.regimes[target_id]
    player_id = state.player_regime_id
    target_regions = [r for r in state.regions.values() if r["name"] in target.get("regions", [])]
    player_regions = [r for r in state.regions.values() if r["name"] in state.player_regime.get("regions", [])]
    mandatory = set(occupied_regions(state, player_id, target_id))
    demanded = set(occupied_regions(state, target_id, player_id))
    required_player_cession = int(state.flags.get("huxia_required_peace_region", 0) or 0) if target_id == 12 else 0

    window = tk.Toplevel(parent)
    window.title(f"与{target['name']}议和")
    window.geometry("820x650")
    window.minsize(680, 520)
    window.transient(parent.winfo_toplevel())
    window.configure(background=theme.PANEL)
    ttk.Label(window, text="定制和平协议", style="Heading.TLabel").pack(anchor="w", padx=20, pady=(18, 4))
    treaty_note = (
        "对方被我方控制的领土已默认选中；保留选中表示要求割让，取消选中表示停战时归还对方。"
        "每归还一块被我方占领的地区，AI和解倾向+50；索取尚未占领的地区会受到极大惩罚。"
        "我方被对方占领但未选择割让的地区，也会在停战时归还我方。"
    )
    if required_player_cession:
        required_region = state.regions.get(required_player_cession, {})
        treaty_note += f"\n胡夏当前的议和条件：我方必须割让{required_region.get('name', '北雍州')}。"
    ttk.Label(window, text=treaty_note, style="Muted.TLabel", wraplength=760).pack(anchor="w", padx=20, pady=(0, 12))
    columns = ttk.Frame(window, style="Panel.TFrame")
    columns.pack(fill="both", expand=True, padx=20)
    columns.columnconfigure(0, weight=1)
    columns.columnconfigure(1, weight=1)
    columns.rowconfigure(1, weight=1)
    ttk.Label(columns, text=f"{target['name']}割让给我方", style="Subheading.TLabel").grid(row=0, column=0, sticky="w", padx=8, pady=6)
    ttk.Label(columns, text=f"我方割让给{target['name']}", style="Subheading.TLabel").grid(row=0, column=1, sticky="w", padx=8, pady=6)
    target_box = tk.Listbox(columns, selectmode="multiple", exportselection=False, font=("Microsoft YaHei UI", 10), background=theme.PANEL)
    player_box = tk.Listbox(columns, selectmode="multiple", exportselection=False, font=("Microsoft YaHei UI", 10), background=theme.PANEL)
    target_box.grid(row=1, column=0, sticky="nsew", padx=8)
    player_box.grid(row=1, column=1, sticky="nsew", padx=8)
    for index, region in enumerate(target_regions):
        controlled = state.regimes.get(region.get("controller"), {}).get("name", "无")
        suffix = "（我方已控制，默认要求割让）" if region["id"] in mandatory else f"（控制：{controlled}）"
        target_box.insert("end", f"{region['name']} {suffix}")
        if region["id"] in mandatory:
            target_box.selection_set(index)
    for index, region in enumerate(player_regions):
        controlled = state.regimes.get(region.get("controller"), {}).get("name", "无")
        if region["id"] == required_player_cession:
            suffix = "（胡夏要求割让）"
        elif region["id"] in demanded:
            suffix = "（对方已控制）"
        else:
            suffix = f"（控制：{controlled}）"
        player_box.insert("end", f"{region['name']} {suffix}")
        if region["id"] in demanded or region["id"] == required_player_cession:
            player_box.selection_set(index)

    money = ttk.Frame(window, style="Panel.TFrame", padding=12)
    money.pack(fill="x", padx=20, pady=12)
    target_pays = tk.IntVar(value=0)
    player_pays = tk.IntVar(value=0)
    vassal = tk.BooleanVar(value=False)
    ttk.Label(money, text="对方赔款").grid(row=0, column=0, sticky="w")
    ttk.Spinbox(money, from_=0, to=max(0, treasury_balance(state, target_id)), increment=100, textvariable=target_pays, width=12).grid(row=0, column=1, padx=(6, 22))
    ttk.Label(money, text="我方赔款").grid(row=0, column=2, sticky="w")
    ttk.Spinbox(money, from_=0, to=max(0, treasury_balance(state)), increment=100, textvariable=player_pays, width=12).grid(row=0, column=3, padx=(6, 22))
    ttk.Checkbutton(money, text="要求对方臣服", variable=vassal).grid(row=0, column=4, sticky="w")
    result = {"value": None}

    def accept():
        result["value"] = {
            "target_cedes": [target_regions[i]["id"] for i in target_box.curselection()],
            "player_cedes": [player_regions[i]["id"] for i in player_box.curselection()],
            "target_pays": max(0, target_pays.get()),
            "player_pays": max(0, player_pays.get()),
            "target_vassal": vassal.get(),
        }
        window.destroy()

    controls = ttk.Frame(window, style="Panel.TFrame")
    controls.pack(fill="x", padx=20, pady=(0, 18))
    ttk.Button(controls, text="提交协议", style="Accent.TButton", command=accept).pack(side="right", padx=(8, 0))
    ttk.Button(controls, text="取消", command=window.destroy).pack(side="right")
    window.grab_set()
    parent.wait_window(window)
    return result["value"]


def army_creation_dialog(parent, state) -> tuple[int, dict[int, int]] | None:
    """用整营滑块配置军队；不接受键盘输入人数。"""
    regime = state.player_regime
    from ..rules.national_modifiers import national_modifier_total

    cavalry_disabled = national_modifier_total(state, "cavalry_recruitment_disabled") >= 1
    capital_id = int(regime.get("capital") or 0)
    v12 = str(state.flags.get("content_version", "1.1")) == "1.2"
    if v12:
        from ..content.v1_2.economy import recruitment_available

        reserve = recruitment_available(state, state.player_regime_id)
    else:
        reserve = int(regime.get("reserve_army", 0))
    max_battalions = min(
        9,
        reserve // 1000,
        int(treasury_balance(state, state.player_regime_id) // 3) if v12 else 9,
    )
    window = tk.Toplevel(parent)
    window.title("在首都创建军队")
    window.geometry("650x590")
    window.minsize(560, 520)
    window.transient(parent.winfo_toplevel())
    window.configure(background=theme.PANEL)
    ttk.Label(window, text="创建军队", style="Heading.TLabel").pack(anchor="w", padx=24, pady=(20, 5))
    ttk.Label(
        window,
        text=(
            f"组建地点：{state.city_name(capital_id)}（首都）　"
            + (f"现有人力：{reserve}" if v12 else f"预备役：{reserve}人")
            + "\n每营固定1000人；一支军队最多9营。"
        ),
        style="Muted.TLabel",
    ).pack(anchor="w", padx=24, pady=(0, 12))

    army_type = tk.IntVar(value=0)
    type_frame = ttk.Frame(window, style="Panel.TFrame")
    type_frame.pack(fill="x", padx=24, pady=4)
    ttk.Label(type_frame, text="军队类型：", style="Subheading.TLabel").pack(side="left")
    ttk.Radiobutton(type_frame, text="陆军", variable=army_type, value=0).pack(side="left", padx=10)
    ttk.Radiobutton(type_frame, text="水军", variable=army_type, value=1).pack(side="left", padx=10)

    sliders = ttk.Frame(window, style="Panel.TFrame", padding=12)
    sliders.pack(fill="x", padx=24, pady=10)
    counts = [tk.IntVar(value=0) for _ in range(3)]
    name_vars = [tk.StringVar() for _ in range(3)]
    count_vars = [tk.StringVar(value="0 营 / 0 人") for _ in range(3)]
    scales: list[tk.Scale] = []
    updating = {"value": False}
    total_var = tk.StringVar()
    remaining_var = tk.StringVar()
    pay_var = tk.StringVar()
    mobility_var = tk.StringVar()
    result = {"value": None}

    def refresh(_value=None, changed_index: int | None = None):
        if updating["value"]:
            return
        updating["value"] = True
        total = sum(value.get() for value in counts)
        if total > max_battalions and changed_index is not None:
            overflow = total - max_battalions
            counts[changed_index].set(max(0, counts[changed_index].get() - overflow))
            total = sum(value.get() for value in counts)
        for index, value in enumerate(counts):
            count_vars[index].set(f"{value.get()} 营 / {value.get() * 1000} 人")
        total_var.set(f"总编制：{total} / 9 营")
        remaining_var.set(
            f"总兵力：{total * 1000} 人　"
            + (f"组建后人力：{reserve - total * 1000}" if v12 else f"组建后预备役：{reserve - total * 1000} 人")
        )
        pay_var.set(
            f"组建费用：{total * 3:g}铜钱　预计每月口粮：{total * 0.2:g}单位"
            if v12 else f"预计每月军饷：{total * 50} 国库"
        )
        pure_cavalry = army_type.get() == 0 and counts[1].get() > 0 and counts[0].get() == 0 and counts[2].get() == 0
        mobility_var.set("行动力上限：2（纯骑兵）" if pure_cavalry else "行动力上限：1")
        create_button.configure(state="normal" if total > 0 else "disabled")
        updating["value"] = False

    for index in range(3):
        ttk.Label(sliders, textvariable=name_vars[index], style="Subheading.TLabel", width=8).grid(row=index, column=0, sticky="w", padx=5)
        scale = tk.Scale(
            sliders, from_=0, to=max_battalions, orient="horizontal", resolution=1,
            showvalue=False, length=350, background=theme.PANEL, highlightthickness=0,
            variable=counts[index], command=lambda value, i=index: refresh(value, i),
        )
        scale.grid(row=index, column=1, sticky="ew", padx=8, pady=7)
        scales.append(scale)
        ttk.Label(sliders, textvariable=count_vars[index], style="Panel.TLabel", width=14).grid(row=index, column=2, sticky="e")
    sliders.columnconfigure(1, weight=1)

    calculator = ttk.LabelFrame(window, text="编制计算器", padding=14)
    calculator.pack(fill="x", padx=24, pady=(4, 12))
    ttk.Label(calculator, textvariable=total_var, style="Subheading.TLabel").pack(anchor="w")
    ttk.Label(calculator, textvariable=remaining_var).pack(anchor="w", pady=3)
    ttk.Label(calculator, textvariable=pay_var).pack(anchor="w", pady=3)
    ttk.Label(calculator, textvariable=mobility_var).pack(anchor="w", pady=3)

    def switch_type(*_args):
        names = ("步兵", "骑兵", "弓兵") if army_type.get() == 0 else ("战船", "快船", "楼船")
        for index, name in enumerate(names):
            name_vars[index].set(name)
            counts[index].set(0)
            scales[index].configure(
                state="disabled" if cavalry_disabled and army_type.get() == 0 and index == 1 else "normal"
            )
        refresh()

    def accept():
        unit_types = (1, 2, 3) if army_type.get() == 0 else (4, 5, 6)
        result["value"] = (army_type.get(), {unit_type: counts[index].get() for index, unit_type in enumerate(unit_types)})
        window.destroy()

    controls = ttk.Frame(window, style="Panel.TFrame")
    controls.pack(fill="x", padx=24, pady=(0, 18))
    create_button = ttk.Button(controls, text="组建军队", style="Accent.TButton", command=accept)
    create_button.pack(side="right", padx=(8, 0))
    ttk.Button(controls, text="取消", command=window.destroy).pack(side="right")
    army_type.trace_add("write", switch_type)
    switch_type()
    window.grab_set()
    parent.wait_window(window)
    return result["value"]
