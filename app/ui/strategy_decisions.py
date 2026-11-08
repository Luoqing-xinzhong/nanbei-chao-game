from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from ..models import GameState
from ..content.v1_1 import decisions, strategies
from ..rules.common import RuleError
from ..content.v1_1.story_texts import render_dynamic_text
from . import theme
from .dialogs import center_window
from .widgets import ScrollableFrame


def _story_modules(state: GameState):
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2 import decisions as selected_decisions
        from ..content.v1_2 import strategies as selected_strategies
        return selected_decisions, selected_strategies
    return decisions, strategies


class StrategyGenealogyWindow(tk.Toplevel):
    """Prerequisite graph generated from strategy configuration."""

    NODE_WIDTH = 150
    NODE_HEIGHT = 62
    X_GAP = 48
    Y_GAP = 82

    def __init__(self, master, state: GameState):
        super().__init__(master)
        self.state = state
        _decisions, self.strategies = _story_modules(state)
        self.title("经略图谱")
        self.geometry("920x620")
        self.minsize(680, 440)
        self.transient(master.winfo_toplevel())
        self.configure(background=theme.PANEL)

        heading = ttk.Frame(self, style="Panel.TFrame")
        heading.pack(fill="x", padx=20, pady=(18, 10))
        ttk.Label(heading, text="经略图谱", style="Heading.TLabel").pack(side="left")
        ttk.Label(heading, text="黑线红叉：互斥", foreground="#b42318", background=theme.PANEL, padding=(6, 4)).pack(side="right", padx=(8, 0))
        ttk.Label(heading, text="灰色：不可执行", foreground="#272727", background="#aeb3ba", padding=(8, 4)).pack(side="right", padx=(8, 0))
        ttk.Label(heading, text="黄色：推进中", foreground="#272727", background="#e3b341", padding=(8, 4)).pack(side="right", padx=(8, 0))
        ttk.Label(heading, text="蓝色：已完成", foreground="#ffffff", background="#2f6fad", padding=(8, 4)).pack(side="right", padx=(8, 0))
        ttk.Label(heading, text="白色：可执行", foreground="#272727", background="#ffffff", padding=(8, 4)).pack(side="right")

        body = ttk.Frame(self, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.canvas = tk.Canvas(body, background=theme.PANEL, highlightthickness=0)
        vertical = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        ttk.Button(self, text="关闭", command=self.destroy).pack(anchor="e", padx=20, pady=(0, 16))
        self.redraw()

    @staticmethod
    def _depths(nodes: list[dict], edges: list[tuple[int, int]]) -> dict[int, int]:
        parents: dict[int, list[int]] = {int(node["id"]): [] for node in nodes}
        for parent, child in edges:
            parents.setdefault(child, []).append(parent)
        cache: dict[int, int] = {}

        def depth(strategy_id: int, trail: frozenset[int] = frozenset()) -> int:
            if strategy_id in cache:
                return cache[strategy_id]
            if strategy_id in trail:
                return 0
            prerequisites = parents.get(strategy_id, [])
            value = 0 if not prerequisites else 1 + max(depth(item, trail | {strategy_id}) for item in prerequisites)
            cache[strategy_id] = value
            return value

        for strategy_id in parents:
            depth(strategy_id)
        return cache

    def redraw(self) -> None:
        self.canvas.delete("all")
        nodes, edges = self.strategies.strategy_genealogy(self.state)
        depths = self._depths(nodes, edges)
        layers: dict[int, list[dict]] = {}
        for node in nodes:
            layers.setdefault(depths[int(node["id"])], []).append(node)
        for values in layers.values():
            values.sort(key=lambda item: int(item["id"]))

        max_layer_size = max((len(values) for values in layers.values()), default=1)
        width = max(860, 80 + max_layer_size * (self.NODE_WIDTH + self.X_GAP))
        height = max(400, 70 + len(layers) * (self.NODE_HEIGHT + self.Y_GAP))
        positions: dict[int, tuple[float, float]] = {}
        for layer, values in sorted(layers.items()):
            span = len(values) * self.NODE_WIDTH + max(0, len(values) - 1) * self.X_GAP
            left = (width - span) / 2
            top = 40 + layer * (self.NODE_HEIGHT + self.Y_GAP)
            for index, node in enumerate(values):
                positions[int(node["id"])] = (left + index * (self.NODE_WIDTH + self.X_GAP), top)

        for parent, child in edges:
            if parent not in positions or child not in positions:
                continue
            px, py = positions[parent]
            cx, cy = positions[child]
            start = (px + self.NODE_WIDTH / 2, py + self.NODE_HEIGHT)
            end = (cx + self.NODE_WIDTH / 2, cy)
            middle_y = (start[1] + end[1]) / 2
            self.canvas.create_line(
                start[0], start[1], start[0], middle_y, end[0], middle_y, end[0], end[1],
                fill="#6d737b", width=2, arrow="last",
            )

        # 互斥关系不带方向：黑线连接两节点，并在线段中央用红叉标明冲突。
        for left_id, right_id in self.strategies.strategy_mutual_exclusions(self.state):
            if left_id not in positions or right_id not in positions:
                continue
            lx, ly = positions[left_id]
            rx, ry = positions[right_id]
            start_x, start_y = lx + self.NODE_WIDTH / 2, ly + self.NODE_HEIGHT / 2
            end_x, end_y = rx + self.NODE_WIDTH / 2, ry + self.NODE_HEIGHT / 2
            self.canvas.create_line(start_x, start_y, end_x, end_y, fill="#111111", width=3)
            middle_x, middle_y = (start_x + end_x) / 2, (start_y + end_y) / 2
            cross = 8
            self.canvas.create_line(
                middle_x - cross, middle_y - cross, middle_x + cross, middle_y + cross,
                fill="#d92d20", width=4,
            )
            self.canvas.create_line(
                middle_x - cross, middle_y + cross, middle_x + cross, middle_y - cross,
                fill="#d92d20", width=4,
            )

        for node in nodes:
            left, top = positions[int(node["id"])]
            status = str(node.get("status", "available"))
            if status == "completed":
                fill, outline, text_color, status_text = "#2f6fad", "#1f4f82", "#ffffff", "已完成"
            elif status == "in_progress":
                fill, outline, text_color, status_text = "#e3b341", "#9a7420", "#272727", "推进中"
            elif bool(node.get("executable")):
                fill, outline, text_color, status_text = "#ffffff", "#737980", "#272727", "可执行"
            else:
                fill, outline, text_color = "#aeb3ba", "#737980", "#272727"
                status_text = "已暂停" if status == "paused" else "不可执行"
            self.canvas.create_rectangle(
                left, top, left + self.NODE_WIDTH, top + self.NODE_HEIGHT,
                fill=fill, outline=outline, width=2,
            )
            self.canvas.create_text(
                left + self.NODE_WIDTH / 2,
                top + self.NODE_HEIGHT / 2 - 7,
                text=f"{node['id']}. {node['name']}",
                fill=text_color,
                font=("Microsoft YaHei UI", 10, "bold"),
                width=self.NODE_WIDTH - 14,
            )
            self.canvas.create_text(
                left + self.NODE_WIDTH / 2,
                top + self.NODE_HEIGHT - 12,
                text=status_text,
                fill=text_color,
                font=("Microsoft YaHei UI", 8),
            )
        self.canvas.configure(scrollregion=(0, 0, width, height))


def show_decision_result(master, result: decisions.DecisionResult) -> None:
    window = tk.Toplevel(master)
    window.title(f"决议完成 · {result.name}")
    window.geometry("820x680")
    window.minsize(620, 480)
    window.transient(master.winfo_toplevel())
    window.configure(background=theme.PANEL)
    ttk.Label(window, text=result.name, style="Heading.TLabel").pack(anchor="w", padx=24, pady=(20, 4))
    ttk.Label(window, text=result.summary, style="Muted.TLabel", wraplength=750).pack(anchor="w", padx=24, pady=(0, 10))
    body = ttk.Frame(window, style="Panel.TFrame")
    body.pack(fill="both", expand=True, padx=22, pady=(0, 12))
    text = tk.Text(body, wrap="word", background=theme.PANEL, relief="flat", padx=16, pady=14, font=("Microsoft YaHei UI", 11))
    bar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
    text.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    text.insert("1.0", result.text)
    text.configure(state="disabled")
    ttk.Label(window, text=f"效果：{result.effect_description}", style="Panel.TLabel", wraplength=750).pack(anchor="w", padx=24, pady=(0, 10))
    controls = ttk.Frame(window, style="Panel.TFrame")
    controls.pack(fill="x", padx=24, pady=(0, 18))
    ttk.Button(controls, text="关闭", command=window.destroy).pack(side="right")
    center_window(window, 820, 680)
    window.grab_set()


class StrategyWindow(tk.Toplevel):
    def __init__(self, master, state: GameState, on_changed: Callable[[], None]):
        super().__init__(master)
        self.state = state
        self.on_changed = on_changed
        _decisions, self.strategies = _story_modules(state)
        self.title("经略图")
        self.geometry("760x500")
        self.minsize(640, 420)
        self.transient(master.winfo_toplevel())
        self.configure(background=theme.PANEL)
        self.genealogy_window: StrategyGenealogyWindow | None = None
        title_row = ttk.Frame(self, style="Panel.TFrame")
        title_row.pack(fill="x", padx=22, pady=(20, 4))
        ttk.Label(title_row, text="经略图", style="Heading.TLabel").pack(side="left")
        ttk.Button(title_row, text="经略图谱", command=self._show_genealogy).pack(side="right")
        ttk.Label(self, text="前置条件失效时自动暂停并保留进度；主动取消会清空进度。", style="Muted.TLabel").pack(anchor="w", padx=22, pady=(0, 12))
        self.scroll = ScrollableFrame(self, style="Panel.TFrame")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        self.rows = self.scroll.body
        ttk.Button(self, text="关闭", command=self.destroy).pack(anchor="e", padx=20, pady=(0, 16))
        self.refresh()

    def refresh(self):
        self.strategies.ensure_strategy_records(self.state)
        self.strategies.sync_strategy_statuses(self.state)
        for child in self.rows.winfo_children():
            child.destroy()
        status_names = {"available": "未开始", "in_progress": "推进中", "paused": "已暂停", "completed": "已完成"}
        for strategy_id in sorted(self.state.strategies):
            strategy = self.state.strategies[strategy_id]
            row = ttk.Frame(self.rows, style="Panel.TFrame", padding=12)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=f"{strategy_id}. {strategy['name']}", style="Subheading.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(row, text=status_names.get(strategy["status"], strategy["status"]), style="Panel.TLabel").grid(row=0, column=1, sticky="e")
            ttk.Label(row, text=f"耗时：{strategy['duration_months']}个月　效果：{strategy['effect_description']}", style="Panel.TLabel", wraplength=550).grid(row=1, column=0, sticky="w", pady=(5, 0))
            progress = int(strategy.get("progress_months", 0))
            ttk.Progressbar(row, maximum=int(strategy["duration_months"]), value=progress).grid(row=2, column=0, sticky="ew", pady=(7, 0))
            available, reason = self.strategies.strategy_available(self.state, strategy_id)
            if strategy.get("status") in {"in_progress", "paused"}:
                button = ttk.Button(row, text="取消经略", command=lambda sid=strategy_id: self._cancel(sid))
            else:
                button = ttk.Button(row, text="开始经略" if available else reason, command=lambda sid=strategy_id: self._start(sid))
            button.grid(row=1, column=1, rowspan=2, sticky="e", padx=(12, 0))
            if not available and strategy.get("status") not in {"in_progress", "paused"}:
                button.configure(state="disabled")
            row.columnconfigure(0, weight=1)
        if self.genealogy_window and self.genealogy_window.winfo_exists():
            self.genealogy_window.redraw()

    def _show_genealogy(self):
        if self.genealogy_window and self.genealogy_window.winfo_exists():
            self.genealogy_window.redraw()
            self.genealogy_window.lift()
            self.genealogy_window.focus_force()
            return
        self.genealogy_window = StrategyGenealogyWindow(self, self.state)

    def _start(self, strategy_id: int):
        try:
            message = self.strategies.start_strategy(self.state, strategy_id)
        except RuleError as exc:
            messagebox.showwarning("无法开始经略", str(exc), parent=self)
            return
        messagebox.showinfo("经略开始", message, parent=self)
        self.on_changed()
        self.refresh()

    def _cancel(self, strategy_id: int):
        strategy = self.state.strategies[strategy_id]
        if not messagebox.askyesno(
            "取消经略",
            f"取消“{strategy['name']}”后，当前进度将全部清零。确定取消吗？",
            parent=self,
        ):
            return
        try:
            self.strategies.cancel_strategy(self.state, strategy_id)
        except RuleError as exc:
            messagebox.showwarning("无法取消经略", str(exc), parent=self)
            return
        self.on_changed()
        self.refresh()


class DecisionPanel(ttk.Frame):
    """Compact decisions: a small clickable dot on the left and its name on the right."""

    def __init__(self, master, state: GameState, on_changed: Callable[[], None]):
        super().__init__(master, style="Panel.TFrame")
        self.state = state
        self.on_changed = on_changed
        self.decisions, _strategies = _story_modules(state)
        self.refresh()

    def refresh(self):
        for child in self.winfo_children():
            child.destroy()
        visible = [decision_id for decision_id in sorted(self.decisions.DECISION_TEMPLATES) if self.decisions.decision_visible(self.state, decision_id)]
        if not visible:
            ttk.Label(self, text="暂无已解锁决议", style="Muted.TLabel").pack(anchor="w", pady=4)
            return
        for decision_id in visible:
            template = self.decisions.DECISION_TEMPLATES[decision_id]
            available, reason = self.decisions.decision_available(self.state, decision_id)
            row = ttk.Frame(self, style="Panel.TFrame")
            row.pack(fill="x", pady=3)
            canvas = tk.Canvas(row, width=28, height=28, background=theme.PANEL, highlightthickness=0, cursor="hand2" if available else "arrow")
            canvas.pack(side="left", padx=(2, 7))
            fill = theme.ACCENT if available else "#aaa59b"
            canvas.create_oval(6, 6, 22, 22, fill=fill, outline=theme.ACCENT_DARK if available else theme.MUTED, width=1)
            ttk.Label(row, text=template["name"], style="Subheading.TLabel").pack(side="left")
            ttk.Label(row, text=reason, style="Muted.TLabel").pack(side="right", padx=(8, 2))
            if available:
                canvas.bind("<Button-1>", lambda _event, did=decision_id: self._execute(did))

    def _execute(self, decision_id: int):
        template = self.decisions.DECISION_TEMPLATES[decision_id]
        if template["choices"]:
            self._show_choice_decision(decision_id)
            return
        self._finish_decision(decision_id)

    def _finish_decision(self, decision_id: int, choice: str | None = None, intro_window=None):
        try:
            result = self.decisions.execute_decision(self.state, decision_id, choice)
        except RuleError as exc:
            messagebox.showwarning("无法执行决议", str(exc), parent=intro_window or self)
            return
        if intro_window and intro_window.winfo_exists():
            intro_window.grab_release()
            intro_window.destroy()
        self.on_changed()
        self.refresh()
        show_decision_result(self, result)

    def _show_choice_decision(self, decision_id: int):
        template = self.decisions.DECISION_TEMPLATES[decision_id]
        available_choices = (
            self.decisions.decision_choices(self.state, decision_id)
            if hasattr(self.decisions, "decision_choices")
            else list(template["choices"])
        )
        window = tk.Toplevel(self)
        window.title(template["name"])
        window.geometry("820x680")
        window.minsize(620, 480)
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PANEL)
        ttk.Label(window, text=template["name"], style="Heading.TLabel").pack(anchor="w", padx=24, pady=(20, 4))
        ttk.Label(window, text=template["summary"], style="Muted.TLabel", wraplength=750).pack(anchor="w", padx=24, pady=(0, 10))

        body = ttk.Frame(window, style="Panel.TFrame")
        body.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        text = tk.Text(body, wrap="word", background=theme.PANEL, relief="flat", padx=16, pady=14, font=("Microsoft YaHei UI", 11))
        bar = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        text.insert("1.0", render_dynamic_text(self.state, template["text"]))
        text.configure(state="disabled")

        choices = ttk.Frame(window, style="Panel.TFrame")
        choices.pack(fill="x", padx=22, pady=(0, 18))
        ttk.Label(choices, text=template.get("choice_prompt", "请选择：") + "：", style="Subheading.TLabel").pack(side="left", padx=(4, 10))
        for choice in available_choices:
            ttk.Button(
                choices,
                text=choice,
                style="Accent.TButton",
                command=lambda selected=choice: self._finish_decision(decision_id, selected, window),
            ).pack(side="left", padx=5)
        ttk.Button(choices, text="暂不决定", command=window.destroy).pack(side="right", padx=4)
        center_window(window, 820, 680)
        window.grab_set()
