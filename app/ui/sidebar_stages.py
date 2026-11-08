"""Narrow phase views; action implementations stay in stage_panels.py.

The subclasses intentionally build only the sidebar widgets. They inherit the
existing action methods, so the layout does not duplicate or change game rules.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..rules import intrigue, laws, politics
from ..rules.treasury import treasury_balance
from ..v11 import LAW_CATEGORIES, LAW_LEVELS, law_name
from .dialogs import center_window
from .dragon_layout import INK, PAPER
from .stage_panels import (
    DevelopmentWindow, DiplomacyWindow, IntrigueWindow, MilitaryWindow,
    PoliticalWindow, StageWindow, V12PoliticalWindow,
)
from .strategy_decisions import DecisionPanel


class SidebarMixin:
    def _start(self, args, kwargs, title):
        StageWindow.__init__(self, *args, **kwargs)
        self.configure(style="Dragon.TFrame")
        self._scroll_shell.configure(style="Dragon.TFrame")
        self._canvas.configure(background=PAPER)
        self.content.configure(style="Dragon.TFrame", padding=(7, 4))
        self._detail_windows = []
        self._label(title, heading=True)

    def _label(self, text=None, *, variable=None, heading=False, parent=None):
        label = ttk.Label(
            parent or self.content, text=text, textvariable=variable,
            style="Dragon.Heading.TLabel" if heading else "Dragon.TLabel",
            wraplength=220, justify="left",
        )
        label.pack(anchor="w", fill="x", pady=(6, 5))
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(80, e.width-4)))
        return label

    def _buttons(self, actions, parent=None):
        frame = ttk.Frame(parent or self.content, style="Dragon.TFrame")
        frame.pack(fill="x", pady=(2, 5))
        for column in range(2):
            frame.columnconfigure(column, weight=1, uniform="actions")
        for index, (label, callback) in enumerate(actions):
            ttk.Button(frame, text=label, command=callback, style="Dragon.TButton").grid(
                row=index//2, column=index % 2, sticky="ew", padx=3, pady=3,
            )
        return frame

    def _tree(self, columns, displayed, *, height=5):
        frame = ttk.Frame(self.content, style="Dragon.TFrame")
        frame.pack(fill="x", pady=5)
        tree = ttk.Treeview(frame, columns=tuple(columns), displaycolumns=tuple(displayed),
                            show="headings", selectmode="browse", height=height, style="Dragon.Treeview")
        for key, title in columns.items():
            tree.heading(key, text=title)
            tree.column(key, width=65, minwidth=35, stretch=True, anchor="center")
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        return tree

    def _list(self, height=4):
        frame = ttk.Frame(self.content, style="Dragon.TFrame")
        frame.pack(fill="x", pady=5)
        box = tk.Listbox(frame, width=1, height=height, font=("Microsoft YaHei UI", 10),
                         background=PAPER, foreground=INK, borderwidth=0, highlightthickness=0,
                         exportselection=False, activestyle="none")
        bar = ttk.Scrollbar(frame, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        return box

    def _finish(self):
        self._layout_finished = True
        footer = ttk.Frame(self, style="Dragon.TFrame", padding=(10, 8))
        footer.pack(side="bottom", fill="x")
        self.next_button = ttk.Button(
            footer, text="结束回合" if self.state.phase_index == len(self.state.phase_names)-1 else "下一阶段",
            command=self.next_phase, style="Dragon.Next.TButton",
        )
        self.next_button.pack(fill="x")
        self._scroll_shell.pack(fill="both", expand=True)
        # Wheel events from buttons/labels must scroll this panel, not the map.
        self._wheel_owner = self.winfo_toplevel()
        self._wheel_binding = self._wheel_owner.bind("<MouseWheel>", self._sidebar_wheel, add="+")
        self.bind("<Destroy>", self._cleanup_sidebar, add="+")
        self.refresh()

    def _cleanup_sidebar(self, event):
        if event.widget is self and self._wheel_binding:
            self._wheel_owner.unbind("<MouseWheel>", self._wheel_binding)
            self._wheel_binding = None

    def _sidebar_wheel(self, event):
        if not self.winfo_exists():
            return
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget in {self._canvas, self.content}:
            return  # StageWindow already scrolls these directly.
        while widget is not None:
            if isinstance(widget, (tk.Listbox, ttk.Treeview)):
                return
            if widget is self.content:
                self._scroll_wheel(event)
                return
            widget = getattr(widget, "master", None)

    def _detail(self, title):
        window = tk.Toplevel(self)
        window.title(title)
        window.transient(self.winfo_toplevel())
        window.configure(background=PAPER)
        center_window(window, 780, 620)
        footer = ttk.Frame(window, style="Dragon.TFrame", padding=12)
        footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="关闭", command=window.destroy, style="Dragon.TButton").pack(side="right")
        self._label(title, heading=True, parent=window)
        self._detail_windows.append(window)
        return window

    def close(self):
        for window in self._detail_windows:
            if window.winfo_exists():
                window.destroy()
        StageWindow.close(self)


class PoliticalSidebarMixin(SidebarMixin):
    def _political_init(self, args, kwargs, *, modern):
        self._modern = modern
        self._start(args, kwargs, "政治阶段 · 中枢政令")
        self.summary = tk.StringVar()
        self._label(variable=self.summary)
        self._action_signature = None
        self.actions_host = ttk.Frame(self.content, style="Dragon.TFrame")
        self.actions_host.pack(fill="x")
        self._label("国政典章", heading=True)
        self._buttons((("法律", self._laws), ("经略", self._strategies), ("决议", self._decisions)))
        self.legislation_var = tk.StringVar()
        self._label(variable=self.legislation_var)
        self._finish()

    def _political_actions(self):
        if self._modern:
            actions = [
                ("任命官员", self._appoint), ("卸任官员", self._dismiss_office),
                ("临时征税", self._temporary_tax), ("赈灾救济", self._relief),
                ("征兵", self._conscript), ("大赦", self._amnesty), ("审判", self._judge),
                ("兴修水利", self._develop), ("修筑城防", self._fortify),
                ("垦荒", self._reclaim), ("顾问大臣", self._economic_adviser),
            ]
            if str(self.state.flags.get("rules_version", "")) != "1.3":
                actions.append(("地区经济政令", self._regional_economy))
        else:
            actions = [
                ("任命官员", self._appoint), ("卸任官员", self._dismiss),
                ("临时征税", lambda: self.run_action(lambda: politics.temporary_tax(self.state))),
                ("赈灾救济", self._relief), ("征兵", self._conscript),
                ("大赦", lambda: self.run_action(lambda: politics.amnesty(self.state))),
                ("审判", self._judge), ("兴修水利", self._develop),
                ("修筑城防", self._fortify), ("垦荒", self._reclaim),
            ]
        gated = {
            "检籍": lambda: self.run_action(lambda: laws.household_registration(self.state)),
            "土断": lambda: PoliticalWindow._land_investigation(self),
            "屯田": lambda: PoliticalWindow._tuntian(self),
            "教化": lambda: PoliticalWindow._education(self),
            "动员": lambda: PoliticalWindow._mobilization(self),
        }
        actions.extend((name, gated[name]) for name in laws.unlocked_political_commands(self.state))
        return actions

    def refresh(self):
        self.summary.set(f"权威 {self.state.authority}   国库 {treasury_balance(self.state):g}")
        signature = tuple(laws.unlocked_political_commands(self.state))
        if signature != self._action_signature:
            for child in self.actions_host.winfo_children():
                child.destroy()
            self._buttons(self._political_actions(), parent=self.actions_host)
            self._action_signature = signature
        legislation = self.state.legislation
        if legislation:
            title = LAW_LEVELS[str(legislation["category"])][int(legislation["target_level"])-1]
            self.legislation_var.set(f"立法中：{title} · {int(legislation.get('progress', 0))}%")
        else:
            self.legislation_var.set("立法中：无")

    def _laws(self):
        window = self._detail("法律 · 国政典章")
        self._label(variable=self.legislation_var, parent=window)
        body = ttk.Frame(window, style="Dragon.TFrame", padding=16)
        body.pack(fill="both", expand=True)
        for key, title in LAW_CATEGORIES.items():
            ttk.Button(body, text=f"{title}：{law_name(self.state, key)}", style="Dragon.TButton",
                       command=lambda category=key: self._show_law(category)).pack(fill="x", pady=5)
        ttk.Button(body, text="取消进行中的立法（稳定度-5）", style="Dragon.TButton",
                   command=lambda: PoliticalWindow._cancel_legislation(self)).pack(fill="x", pady=10)

    def _strategies(self):
        if str(self.state.flags.get("rules_version", "")) == "1.3":
            window = self._detail("经略")
            self._label("本子剧本的独立经略内容暂为空。", parent=window)
        else:
            self._open_strategies()

    def _decisions(self):
        window = self._detail("决议")
        if str(self.state.flags.get("rules_version", "")) == "1.3":
            self._label("本子剧本暂无可执行决议。", parent=window)
            return
        canvas = tk.Canvas(window, background=PAPER, highlightthickness=0)
        bar = ttk.Scrollbar(window, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=12, pady=10)
        panel = DecisionPanel(canvas, self.state, self.on_changed)
        item = canvas.create_window((0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))


class PoliticalSidebar(PoliticalSidebarMixin, PoliticalWindow):
    def __init__(self, *args, **kwargs):
        self._political_init(args, kwargs, modern=False)


class V12PoliticalSidebar(PoliticalSidebarMixin, V12PoliticalWindow):
    def __init__(self, *args, **kwargs):
        self._political_init(args, kwargs, modern=True)


class DevelopmentSidebar(SidebarMixin, DevelopmentWindow):
    def __init__(self, *args, **kwargs):
        self._start(args, kwargs, "发展阶段 · 地方文教")
        self.culture_var = tk.StringVar()
        self._label(variable=self.culture_var)
        self._buttons((("地区经济政令", self._regional_economy), ("主修经典", self._classics),
                       ("修建建筑", self._build_building), ("升级建筑", self._upgrade_building)))
        self._policy_values = ("stockpile", "tax", "transfer", "stop")
        self._supply_values = (0.0, 1.0, 1.25, 1.5, 1.75, 2.0)
        self.policy_vars = {}
        self.supply_vars = {}
        self.approval_vars = {}
        self.food_status_vars = {}
        self._region_signature = ()
        self.regions_host = ttk.Frame(self.content, style="Dragon.TFrame")
        self.regions_host.pack(fill="x")
        self._finish()

    def refresh(self):
        from ..content.v1_2.economy import format_resource, market_demand, region_economy
        from ..content.v1_3.culture import culture_balance, monthly_culture_projection, region_approval

        projection = monthly_culture_projection(self.state)
        self.culture_var.set(
            f"文化 {culture_balance(self.state):g}\n"
            f"月产出 {format_resource(projection['produced'])} / 月消耗 {format_resource(projection['spent'])}"
        )
        region_ids = tuple(rid for rid, region in sorted(self.state.regions.items())
                           if int(region.get("controller", 0)) == self.state.player_regime_id)
        if region_ids != self._region_signature:
            for child in self.regions_host.winfo_children():
                child.destroy()
            for mapping in (self.policy_vars, self.supply_vars, self.approval_vars, self.food_status_vars):
                mapping.clear()
            for region_id in region_ids:
                card = ttk.Frame(self.regions_host, style="Dragon.TFrame", padding=(2, 5))
                card.pack(fill="x")
                ttk.Separator(card).pack(fill="x", pady=3)
                ttk.Button(card, text=self.state.regions[region_id]["name"], style="Dragon.TButton",
                           command=lambda rid=region_id: self._show_region_details(rid)).pack(fill="x")
                self.policy_vars[region_id] = tk.StringVar()
                self.supply_vars[region_id] = tk.StringVar()
                self.approval_vars[region_id] = tk.StringVar()
                self.food_status_vars[region_id] = tk.StringVar()
                row = ttk.Frame(card, style="Dragon.TFrame")
                row.pack(fill="x", pady=3)
                for column, (variable, callback) in enumerate((
                    (self.policy_vars[region_id], lambda rid=region_id: self._cycle_policy(rid)),
                    (self.supply_vars[region_id], lambda rid=region_id: self._cycle_supply(rid)),
                )):
                    row.columnconfigure(column, weight=1, uniform="policy")
                    ttk.Button(row, textvariable=variable, command=callback, style="Dragon.TButton").grid(
                        row=0, column=column, sticky="ew", padx=2,
                    )
                self._label(variable=self.food_status_vars[region_id], parent=card)
            self._region_signature = region_ids
        from ..content.v1_2.economy import LOCAL_POLICY_NAMES
        for region_id in region_ids:
            record = region_economy(self.state, region_id)
            self.policy_vars[region_id].set(LOCAL_POLICY_NAMES.get(str(record.get("local_policy")), "屯粮"))
            self.supply_vars[region_id].set(f"文化 {float(record.get('culture_supply', 1)):g}倍")
            gap = market_demand(self.state, region_id, "food") - float(record["market"].get("food", 0))
            self.food_status_vars[region_id].set(
                f"认可 {region_approval(self.state, region_id)} · "
                + (f"缺粮 {format_resource(gap)}" if gap > 0 else f"余粮 {format_resource(-gap)}")
            )


class IntrigueSidebar(SidebarMixin, IntrigueWindow):
    def __init__(self, *args, **kwargs):
        self._start(args, kwargs, "谋划阶段 · 帷幄密议")
        self._buttons((("邀请大臣", self._invite), ("除名亲信", self._remove)))
        self._label("亲信 · 每人每回合一次", heading=True)
        self.confidants = self._list(3)
        self._label("选择行动目标", heading=True)
        self.targets = self._tree(
            {"name": "姓名", "country": "国籍", "family": "家族", "opinion": "好感", "alert": "警惕"},
            ("name", "opinion", "alert"), height=5,
        )
        self._buttons([(action, lambda key=action: self._perform(key)) for action in intrigue.ACTIONS])
        self._finish()


class DiplomacySidebar(SidebarMixin, DiplomacyWindow):
    def __init__(self, *args, **kwargs):
        self._start(args, kwargs, "外交阶段 · 纵横捭阖")
        self._label("选择交涉政权", heading=True)
        self.regime_list = self._list(5)
        self.regime_ids = []
        self.detail = tk.StringVar(value="请选择政权")
        self._label(variable=self.detail)
        self.regime_list.bind("<<ListboxSelect>>", lambda _e: self.refresh())
        self._buttons([(action, lambda key=action: self._act(key))
                       for action in ("遣使", "送礼", "羞辱", "联姻", "宣战", "和解", "要求臣服")])
        self._finish()


class MilitarySidebar(SidebarMixin, MilitaryWindow):
    def __init__(self, *args, **kwargs):
        self._start(args, kwargs, "军事阶段 · 调兵遣将")
        self.summary = tk.StringVar()
        self._label(variable=self.summary)
        self.tree = self._tree(
            {"id": "军队", "type": "类型", "commander": "将领", "units": "兵力/营",
             "supply": "随军粮", "morale": "士气", "exp": "经验", "location": "所在地", "ap": "行动力"},
            ("id", "units", "location"), height=5,
        )
        self.army_detail = tk.StringVar(value="选择军队查看将领、士气、补给与行动力。")
        self._label(variable=self.army_detail)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._selected_army_detail())
        self._buttons((("行军", self._march), ("一键行军", self._quick_march),
                       ("进攻", self._attack), ("犒劳", self._reward),
                       ("补充至满编", self._reinforce), ("分派将领", self._commander),
                       ("解散军队", self._disband), ("创建军队", self._create)))
        self._label("补给队", heading=True)
        self.supply_tree = self._tree(
            {"id": "编号", "food": "携粮", "location": "位置", "age": "服役", "ap": "行动力"},
            ("id", "food", "location"), height=3,
        )
        self.supply_detail = tk.StringVar(value="选择补给队查看服役时间与行动力。")
        self._label(variable=self.supply_detail)
        self.supply_tree.bind("<<TreeviewSelect>>", lambda _e: self._selected_supply_detail())
        modern = str(self.state.flags.get("content_version", "1.1")) == "1.2"
        if modern:
            self._buttons((("创建补给队", self._create_supply), ("移动补给队", self._march_supply),
                           ("补给相邻军队", self._supply_army), ("撤销补给队", self._disband_supply)))
        self._finish()

    def _selected_army_detail(self):
        selected = self.tree.selection()
        if not selected:
            self.army_detail.set("选择军队查看将领、士气、补给与行动力。")
            return
        army = self.state.armies.get(int(selected[0]))
        if not army:
            return
        self.army_detail.set(
            f"#{army.id} · {army.soldiers}人 · {self.state.person_name(army.commander)}\n"
            f"士气 {army.morale} · 经验 {army.experience}\n"
            f"随军粮 {army.supply_food:g} · 行动力 {army.action_points:g}/{army.max_action_points:g}"
        )

    def _selected_supply_detail(self):
        selected = self.supply_tree.selection()
        if not selected:
            self.supply_detail.set("选择补给队查看服役时间与行动力。")
            return
        values = self.supply_tree.item(selected[0], "values")
        self.supply_detail.set(f"补给队{values[0]} · 已服役 {values[3]}\n行动力 {values[4]}")


def sidebar_for(state):
    if state.phase == "政治阶段":
        return V12PoliticalSidebar if str(state.flags.get("content_version", "1.1")) == "1.2" else PoliticalSidebar
    return {"发展阶段": DevelopmentSidebar, "谋划阶段": IntrigueSidebar,
            "外交阶段": DiplomacySidebar, "军事阶段": MilitarySidebar}[state.phase]
