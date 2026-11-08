from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ..constants import OFFICE_NAMES, PHASES, ROAD_NAMES
from ..models import GameState
from ..rules import diplomacy, intrigue, laws, military, politics
from ..rules.common import RuleError, is_regime_eliminated, person_power
from ..rules.treasury import treasury_balance
from ..v11 import LAW_CATEGORIES, LAW_EFFECTS, LAW_LEVELS, law_name
from .dialogs import amount_slider_dialog, army_creation_dialog, center_window, choose_item, peace_treaty
from .strategy_decisions import DecisionPanel, StrategyWindow
from . import theme


class StageWindow(ttk.Frame):
    """嵌入主地图上方的阶段操作面板。"""

    def __init__(self, master, state: GameState, on_advance, on_changed, on_close=None):
        super().__init__(master, style="Stage.TFrame")
        self.state = state
        self.on_advance = on_advance
        self.on_changed = on_changed
        self._on_close = on_close
        self._layout_finished = False

        self._scroll_shell = ttk.Frame(self, style="Stage.TFrame")
        self._canvas = tk.Canvas(self._scroll_shell, background=theme.PANEL, borderwidth=0, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self._scroll_shell, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self._canvas, style="Stage.TFrame")
        self._content_window = self._canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._update_scroll_region)
        self._canvas.bind("<Configure>", self._resize_scroll_content)
        self._canvas.bind("<MouseWheel>", self._scroll_wheel)
        self.content.bind("<MouseWheel>", self._scroll_wheel)

    def _update_scroll_region(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _resize_scroll_content(self, event):
        self._canvas.itemconfigure(self._content_window, width=event.width)

    def _scroll_wheel(self, event):
        self._canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def close(self):
        if self._on_close:
            self._on_close()
        self.destroy()

    def run_action(self, callback, show_result: bool = True, result_title: str = "行动结果"):
        try:
            result = callback()
        except (RuleError, ValueError, KeyError) as exc:
            messagebox.showwarning("无法执行", str(exc), parent=self)
            return
        if result and show_result:
            messagebox.showinfo(result_title, str(result), parent=self)
        self.refresh()
        self.on_changed()

    def next_phase(self):
        self.on_advance()
        self.close()

    def refresh(self):
        pass

    def footer(self):
        if self._layout_finished:
            return
        self._layout_finished = True
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="x", side="bottom")
        ttk.Button(frame, text="下一阶段" if self.state.phase_index < len(self.state.phase_names) - 1 else "结束回合", style="Accent.TButton", command=self.next_phase).pack(side="right")
        ttk.Label(frame, text="完成当前安排后进入下一阶段；未使用的行动将不会保留。", style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        self._scroll_shell.pack(fill="both", expand=True)


class PoliticalWindow(StageWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.authority_var = tk.StringVar()
        self.legislation_var = tk.StringVar()
        self.strategy_var = tk.StringVar()
        header = ttk.Frame(self.content, style="Panel.TFrame", padding=16)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text="政治阶段 · 中枢政令", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.authority_var, style="Panel.TLabel").pack(side="right")
        body = ttk.Panedwindow(self.content, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=8)
        commands = ttk.Frame(body, style="Panel.TFrame", padding=18)
        policies = ttk.Frame(body, style="Panel.TFrame", padding=18)
        body.add(commands, weight=3)
        body.add(policies, weight=2)
        ttk.Label(commands, text="政令", style="Subheading.TLabel").grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 5))
        actions = [
            ("任命官员", self._appoint), ("卸任官员", self._dismiss),
            ("临时征税", lambda: self.run_action(lambda: politics.temporary_tax(self.state))),
            ("赈灾救济", self._relief), ("征兵", self._conscript),
            ("大赦", lambda: self.run_action(lambda: politics.amnesty(self.state))),
            ("审判", self._judge), ("兴修水利", self._develop), ("修筑城防", self._fortify),
            ("垦荒", self._reclaim),
        ]
        law_actions = {
            "检籍": lambda: self.run_action(lambda: laws.household_registration(self.state)),
            "土断": self._land_investigation,
            "屯田": self._tuntian,
            "教化": self._education,
            "动员": self._mobilization,
        }
        actions.extend((name, law_actions[name]) for name in laws.unlocked_political_commands(self.state))
        for i, (text, command) in enumerate(actions):
            ttk.Button(commands, text=text, command=command).grid(row=1 + i // 5, column=i % 5, sticky="nsew", padx=3, pady=3, ipady=3)
        for column in range(5):
            commands.columnconfigure(column, weight=1)
        separator_row = 2 + (len(actions) - 1) // 5
        ttk.Separator(commands).grid(row=separator_row, column=0, columnspan=5, sticky="ew", pady=6)
        ttk.Label(commands, text="政令会直接修改当前政权、地区、城市和人物数据。", wraplength=700, style="Panel.TLabel").grid(row=separator_row + 1, column=0, columnspan=5, sticky="w", pady=2)

        ttk.Label(policies, text="经略", style="Subheading.TLabel").pack(anchor="w")
        ttk.Label(policies, textvariable=self.strategy_var, style="Panel.TLabel").pack(anchor="w", pady=3)
        self.strategy_progress = ttk.Progressbar(policies, value=0, maximum=1)
        self.strategy_progress.pack(fill="x", pady=(0, 3))
        ttk.Button(policies, text="查看经略图", command=self._open_strategies).pack(fill="x")
        ttk.Separator(policies).pack(fill="x", pady=5)
        ttk.Label(policies, text="决议", style="Subheading.TLabel").pack(anchor="w")
        self.decision_panel = DecisionPanel(policies, self.state, self.on_changed)
        self.decision_panel.pack(fill="x")
        ttk.Separator(policies).pack(fill="x", pady=5)
        law_header = ttk.Frame(policies, style="Panel.TFrame")
        law_header.pack(fill="x")
        ttk.Label(law_header, text="法律", style="Subheading.TLabel").pack(side="left")
        ttk.Label(law_header, textvariable=self.legislation_var, style="Panel.TLabel").pack(side="right")
        self.legislation_progress = ttk.Progressbar(policies, value=0, maximum=100)
        self.legislation_progress.pack(fill="x", pady=(3, 2))
        self.cancel_legislation_button = ttk.Button(
            policies,
            text="取消立法（稳定度-5）",
            command=self._cancel_legislation,
        )
        self.cancel_legislation_button.pack(fill="x", pady=(2, 3))
        law_grid = ttk.Frame(policies, style="Panel.TFrame")
        law_grid.pack(fill="both", expand=True, pady=(3, 0))
        for index, (key, category_name) in enumerate(LAW_CATEGORIES.items()):
            level_name = law_name(self.state, key)
            ttk.Button(
                law_grid,
                text=f"{category_name}：{level_name}",
                command=lambda k=key: self._show_law(k),
            ).grid(row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)
            law_grid.columnconfigure(index % 2, weight=1)
        self.footer()
        self.refresh()

    def refresh(self):
        from ..content.v1_1.strategies import active_strategy, ensure_strategy_records

        ensure_strategy_records(self.state)
        self.authority_var.set(f"权威值：{self.state.authority}　国库：{treasury_balance(self.state):g}")
        current_strategy = active_strategy(self.state)
        if current_strategy:
            progress = int(current_strategy.get("progress_months", 0))
            duration = int(current_strategy["duration_months"])
            if current_strategy.get("status") == "paused":
                reason = current_strategy.get("pause_reason", "前置条件不满足")
                self.strategy_var.set(f"暂停：{current_strategy['name']}　{progress}/{duration}个月　{reason}")
            else:
                self.strategy_var.set(f"当前：{current_strategy['name']}　进度：{progress}/{duration}个月")
            self.strategy_progress.configure(maximum=duration, value=progress)
        else:
            completed = sum(item.get("status") == "completed" for item in self.state.strategies.values())
            self.strategy_var.set(f"当前：无　已完成：{completed}/{len(self.state.strategies)}")
            self.strategy_progress.configure(maximum=1, value=0)
        self.decision_panel.refresh()
        if self.state.legislation:
            category = self.state.legislation["category"]
            target = int(self.state.legislation["target_level"])
            progress = int(self.state.legislation.get("progress", 0))
            self.legislation_var.set(f"立法中：{LAW_LEVELS[category][target - 1]}　{progress}%")
            self.legislation_progress.configure(value=progress)
            self.cancel_legislation_button.configure(state="normal")
        else:
            self.legislation_var.set("立法中：无")
            self.legislation_progress.configure(value=0)
            self.cancel_legislation_button.configure(state="disabled")

    def _open_strategies(self):
        StrategyWindow(self, self.state, self.on_changed)

    def _show_law(self, category_key: str):
        window = tk.Toplevel(self)
        window.title(f"{LAW_CATEGORIES[category_key]} · 法律详情")
        window.geometry("720x540")
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PANEL)
        ttk.Label(window, text=LAW_CATEGORIES[category_key], style="Heading.TLabel").pack(anchor="w", padx=20, pady=(18, 4))
        ttk.Label(window, text=f"当前等级：{law_name(self.state, category_key)}", style="Muted.TLabel").pack(anchor="w", padx=20, pady=(0, 12))
        body = tk.Canvas(window, background=theme.PANEL, highlightthickness=0)
        bar = ttk.Scrollbar(window, orient="vertical", command=body.yview)
        body.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        body.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=(0, 12))
        content = ttk.Frame(body, style="Panel.TFrame")
        content_window = body.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _e: body.configure(scrollregion=body.bbox("all")))
        body.bind("<Configure>", lambda e: body.itemconfigure(content_window, width=e.width))
        levels = LAW_LEVELS[category_key]
        effects = LAW_EFFECTS[category_key]
        if category_key == "economy" and str(self.state.flags.get("content_version", "1.1")) == "1.2":
            from ..content.v1_2.economy import V12_ECONOMY_LAW_EFFECTS

            effects = V12_ECONOMY_LAW_EFFECTS
        for index, level_name in enumerate(levels, start=1):
            current = "（当前）" if index == self.state.laws.get(category_key, 1) else ""
            effect = effects[index - 1]
            frame = ttk.Frame(content, style="Panel.TFrame", padding=10)
            frame.pack(fill="x", padx=4, pady=4)
            ttk.Label(frame, text=f"等级 {index}：{level_name}{current}", style="Subheading.TLabel").pack(anchor="w")
            ttk.Label(frame, text=effect, style="Panel.TLabel", wraplength=620, justify="left").pack(anchor="w", pady=(4, 0))
            if not current:
                action_row = ttk.Frame(frame, style="Panel.TFrame")
                action_row.pack(anchor="e", pady=(6, 0))
                if laws.level(self.state, "power") == 4:
                    ttk.Button(
                        action_row,
                        text="皇权强行立法",
                        command=lambda c=category_key, target=index, w=window: self._force_law(c, target, w),
                    ).pack(side="left", padx=(0, 6))
                ttk.Button(
                    action_row,
                    text="提请立法",
                    command=lambda c=category_key, target=index, w=window: self._propose_law(c, target, w),
                ).pack(side="left")
        controls = ttk.Frame(window, style="Panel.TFrame")
        controls.pack(fill="x", padx=20, pady=(0, 16))
        ttk.Button(controls, text="关闭", command=window.destroy).pack(side="right")
        window.grab_set()
        self.wait_window(window)

    def _propose_law(self, category: str, target: int, window):
        try:
            result = laws.propose_legislation(self.state, category, target)
        except (RuleError, ValueError) as exc:
            messagebox.showwarning("立法未能发起", str(exc), parent=window)
            return
        messagebox.showinfo("五人投票", result, parent=window)
        self.refresh()
        self.on_changed()
        if self.state.legislation:
            window.destroy()

    def _force_law(self, category: str, target: int, window):
        if not messagebox.askyesno("强行立法", "皇权将按反对权力消耗权威，并损失30稳定度。继续吗？", parent=window):
            return
        try:
            result = laws.force_legislation(self.state, category, target)
        except (RuleError, ValueError) as exc:
            messagebox.showwarning("无法强行立法", str(exc), parent=window)
            return
        messagebox.showinfo("皇权立法", result, parent=window)
        self.refresh()
        self.on_changed()
        window.destroy()

    def _cancel_legislation(self):
        if not self.state.legislation:
            return
        if not messagebox.askyesno(
            "取消立法",
            "取消后当前进度和投票结果将全部清零，并损失5点稳定度。确定取消吗？",
            parent=self,
        ):
            return
        self.run_action(lambda: laws.cancel_legislation(self.state))

    def _appoint(self):
        internal = self.state.player_regime["internal"]
        choices = [(label, ("office", key)) for key, label in OFFICE_NAMES.items() if key != "emperor" and not internal.get(key)]
        choices.append(("刺史（地区长官）", ("governor", None)))
        selection = choose_item(self, "任命官员", "选择要任命的官职", choices)
        if not selection:
            return
        kind, value = selection
        if kind == "governor":
            region_id = choose_item(self, "任命刺史", "选择地区", self._owned_regions())
            if not region_id:
                return
            occupied = {v for v in internal.values() if isinstance(v, int)}
            occupied |= {r.get("governor") for r in self.state.regions.values() if r.get("governor")}
            people = [
                (f"{self.state.person_name(p['id'])}　智{p['attributes']['intelligence']} 武{p['attributes']['military']}", p["id"])
                for p in self.state.persons.values()
                if p.get("country_id") == self.state.player_regime_id and p.get("status") == 1 and p["id"] not in occupied
            ]
            person_id = choose_item(self, "任命刺史", f"选择{self.state.regions[region_id]['name']}刺史人选", people)
            if person_id:
                self.run_action(lambda: politics.appoint_governor(self.state, region_id, person_id))
            return
        appointed = {v for v in internal.values() if isinstance(v, int)}
        people = [(f"{self.state.person_name(p['id'])}　智{p['attributes']['intelligence']} 武{p['attributes']['military']} 好感{p.get('opinion_of_player', 0)}", p["id"]) for p in self.state.persons.values() if p.get("country_id") == self.state.player_regime_id and p.get("status") == 1 and p["id"] not in appointed]
        person_id = choose_item(self, "任命官员", f"选择{OFFICE_NAMES[value]}人选", people)
        if person_id:
            self.run_action(lambda: politics.appoint(self.state, value, person_id).replace(value, OFFICE_NAMES[value]))

    def _dismiss(self):
        internal = self.state.player_regime["internal"]
        office = choose_item(self, "卸任官员", "选择要解除的官职", [(f"{label}　{self.state.person_name(internal.get(key))}", key) for key, label in OFFICE_NAMES.items() if key != "emperor" and internal.get(key)])
        if office:
            self.run_action(lambda: politics.dismiss(self.state, office))

    def _owned_regions(self):
        names = set(self.state.player_regime.get("regions", []))
        return [(f"{r['name']}　发展{r['development']} 繁荣{r['prosperity']}", r["id"]) for r in self.state.regions.values() if r.get("name") in names]

    def _relief(self):
        rid = choose_item(self, "赈灾救济", f"选择地区（花费{politics.RELIEF_COPPER_COST:g}国库、100权威）", self._owned_regions())
        if rid:
            self.run_action(lambda: politics.relief(self.state, rid))

    def _develop(self):
        rid = choose_item(self, "兴修水利", f"选择地区（花费{politics.DEVELOP_COPPER_COST:g}国库）", self._owned_regions())
        if rid:
            self.run_action(lambda: politics.develop(self.state, rid))

    def _fortify(self):
        names = set(self.state.player_regime.get("regions", []))
        cid = choose_item(self, "修筑城防", f"选择城市（花费{politics.FORTIFY_COPPER_COST:g}国库）", [(f"{c['name']}　城防{c['defense']}", c["id"]) for c in self.state.cities.values() if c.get("region") in names])
        if cid:
            self.run_action(lambda: politics.fortify(self.state, cid))

    def _conscript(self):
        maximum = int(self.state.player_regime.get("militia", 0)) // 1000
        if maximum <= 0:
            messagebox.showwarning("无法征兵", "现有壮丁不足1000人。", parent=self)
            return
        window = tk.Toplevel(self)
        window.title("征召预备役")
        window.geometry("520x260")
        window.resizable(False, False)
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PANEL)
        ttk.Label(window, text="征召预备役", style="Heading.TLabel").pack(anchor="w", padx=24, pady=(20, 4))
        ttk.Label(window, text=f"现有壮丁：{self.state.player_regime['militia']}　每格为1000人", style="Muted.TLabel").pack(anchor="w", padx=24)
        battalions = tk.IntVar(value=1)
        detail = tk.StringVar()

        def update_detail(_value=None):
            amount = battalions.get() * 1000
            cost = int(round(amount * politics.CONSCRIPT_COST_PER_SOLDIER))
            detail.set(f"征召 {battalions.get()} 个千人单位，共 {amount} 人；花费 {cost} 国库、100权威")

        scale = tk.Scale(
            window, from_=1, to=maximum, resolution=1, orient="horizontal",
            variable=battalions, command=update_detail, showvalue=True,
            background=theme.PANEL, highlightthickness=0, length=450,
        )
        scale.pack(fill="x", padx=24, pady=(15, 4))
        ttk.Label(window, textvariable=detail, style="Panel.TLabel").pack(anchor="w", padx=24)
        update_detail()
        controls = ttk.Frame(window, style="Panel.TFrame")
        controls.pack(fill="x", padx=24, pady=(18, 16))

        def confirm():
            amount = battalions.get() * 1000
            window.grab_release()
            window.destroy()
            self.run_action(lambda: politics.conscript(self.state, amount))

        ttk.Button(controls, text="取消", command=window.destroy).pack(side="right")
        ttk.Button(controls, text="确认征召", style="Accent.TButton", command=confirm).pack(side="right", padx=(0, 8))
        window.grab_set()

    def _reclaim(self):
        region_id = choose_item(self, "垦荒", "选择地区（消耗500壮丁、50权威，增加15份土地）", self._owned_regions())
        if region_id:
            self.run_action(lambda: politics.reclaim_land(self.state, region_id))

    def _heir(self):
        emperor = self.state.player_regime["internal"].get("emperor")
        imperial_family = self.state.persons.get(emperor, {}).get("family_id")
        candidates = [(self.state.person_name(p["id"]), p["id"]) for p in self.state.persons.values() if p.get("gender") == 0 and p.get("status") == 1 and (p.get("father") == emperor or p.get("family_id") == imperial_family)]
        pid = choose_item(self, "册立太子", "选择储君", candidates)
        if pid:
            self.run_action(lambda: politics.establish_heir(self.state, pid))

    def _judge(self):
        threshold = laws.execute_stain_threshold(self.state)
        candidates = [(f"{self.state.person_name(p['id'])}　污点{p['attributes'].get('stain', 0)}", p["id"]) for p in self.state.persons.values() if p.get("country_id") == self.state.player_regime_id and p.get("status") in {1, 2, 3} and p.get("attributes", {}).get("stain", 0) >= threshold]
        pid = choose_item(self, "审判", f"选择污点不低于{threshold}的人物", candidates)
        if pid:
            self.run_action(lambda: politics.judge(self.state, pid))

    def _land_investigation(self):
        families = []
        is_v12 = str(self.state.flags.get("content_version", "1.1")) == "1.2"
        for family in self.state.families.values():
            if is_v12:
                leader = self.state.persons.get(int(family.get("leader") or 0))
                if leader and int(leader.get("country_id", 0)) == self.state.player_regime_id and int(leader.get("status", 0)) in {1, 2, 3}:
                    families.append((f"{family.get('name', family['id'])}　家主{self.state.person_name(int(leader['id']))}", int(family["id"])))
                continue
            owned = sum(
                1 for region in laws.owned_player_regions(self.state)
                for owner in region.get("land_ownership", []) if int(owner) == int(family["id"])
            )
            if owned:
                families.append((f"{family.get('name', family['id'])}　土地{owned}", int(family["id"])))
        family_id = choose_item(self, "土断", "选择本年接受土断的家族", families)
        if family_id:
            self.run_action(lambda: laws.land_investigation(self.state, family_id))

    def _tuntian(self):
        region_id = choose_item(self, "屯田", "选择实行屯田的地区", self._owned_regions())
        if region_id:
            self.run_action(lambda: laws.tuntian(self.state, region_id))

    def _education(self):
        officials = {value for value in self.state.player_regime.get("internal", {}).values() if isinstance(value, int)}
        candidates = [
            (f"{self.state.person_name(pid)}　智力{self.state.persons[pid].get('attributes', {}).get('intelligence', 0)}", pid)
            for pid in officials if pid in self.state.persons and self.state.persons[pid].get("status") == 1
        ]
        person_id = choose_item(self, "教化", "选择主持礼乐教育的在职官员", candidates)
        if person_id:
            self.run_action(lambda: laws.education(self.state, person_id))

    def _mobilization(self):
        officials = {value for value in self.state.player_regime.get("internal", {}).values() if isinstance(value, int)}
        candidates = [
            (f"{self.state.person_name(pid)}　智力{self.state.persons[pid].get('attributes', {}).get('intelligence', 0)}", pid)
            for pid in officials if pid in self.state.persons and self.state.persons[pid].get("status") == 1
        ]
        person_id = choose_item(self, "动员", "选择主持战争动员的在职官员", candidates)
        if person_id:
            self.run_action(lambda: laws.mobilization(self.state, person_id))


class V12PoliticalWindow(StageWindow):
    """1.2 administrative panel with Yuanjia strategies, decisions, and laws."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.legislation_var = tk.StringVar()
        header = ttk.Frame(self.content, style="Panel.TFrame", padding=16)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text="政治阶段 · 中枢政令", style="Heading.TLabel").pack(side="left")
        self.summary = tk.StringVar()
        ttk.Label(header, textvariable=self.summary, style="Panel.TLabel").pack(side="right")

        body = ttk.Panedwindow(self.content, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=8)
        commands = ttk.Frame(body, style="Panel.TFrame", padding=18)
        policies = ttk.Frame(body, style="Panel.TFrame", padding=18)
        body.add(commands, weight=3)
        body.add(policies, weight=2)
        ttk.Label(commands, text="中央政令", style="Subheading.TLabel").grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        actions = [
            ("任命官员", self._appoint),
            ("卸任官员", self._dismiss_office),
            ("临时征税", self._temporary_tax),
            ("赈灾救济", self._relief),
            ("征兵", self._conscript),
            ("大赦", self._amnesty),
            ("审判", self._judge),
            ("兴修水利", self._develop),
            ("修筑城防", self._fortify),
            ("垦荒", self._reclaim),
            ("顾问大臣", self._economic_adviser),
        ]
        if str(self.state.flags.get("rules_version", "")) != "1.3":
            actions.append(("地区经济政令", self._regional_economy))
        law_actions = {
            "检籍": lambda: self.run_action(lambda: laws.household_registration(self.state)),
            "土断": lambda: PoliticalWindow._land_investigation(self),
            "屯田": lambda: PoliticalWindow._tuntian(self),
            "教化": lambda: PoliticalWindow._education(self),
            "动员": lambda: PoliticalWindow._mobilization(self),
        }
        for name in laws.unlocked_political_commands(self.state):
            actions.insert(-1, (name, law_actions[name]))
        for index, (text, command) in enumerate(actions):
            ttk.Button(commands, text=text, command=command).grid(row=1 + index // 5, column=index % 5, sticky="ew", padx=4, pady=4, ipady=4)
            commands.columnconfigure(index % 5, weight=1)
        ttk.Label(
            commands,
            text="顾问大臣可根据全国库存、缺口和军队补给压力提出可一键执行的政令；每道经济命令消耗10权威。",
            style="Muted.TLabel",
        ).grid(row=2 + (len(actions) - 1) // 5, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Label(policies, text="经略", style="Subheading.TLabel").pack(anchor="w")
        if str(self.state.flags.get("rules_version", "")) == "1.3":
            ttk.Label(
                policies,
                text="文教南国使用独立的事件、决议与经略内容；当前经略树为空。",
                style="Muted.TLabel",
                wraplength=360,
            ).pack(fill="x", pady=(6, 10))
        else:
            ttk.Button(policies, text="查看元嘉经略图", command=self._open_strategies).pack(fill="x", pady=(6, 8))
            self.decision_panel = DecisionPanel(policies, self.state, self.on_changed)
            self.decision_panel.pack(fill="x", pady=(0, 10))
        ttk.Separator(policies).pack(fill="x", pady=8)
        law_header = ttk.Frame(policies, style="Panel.TFrame")
        law_header.pack(fill="x", pady=(8, 0))
        ttk.Label(law_header, text="法律", style="Subheading.TLabel").pack(side="left")
        ttk.Label(law_header, textvariable=self.legislation_var, style="Panel.TLabel").pack(side="right")
        self.legislation_progress = ttk.Progressbar(policies, maximum=100, value=0)
        self.legislation_progress.pack(fill="x", pady=(5, 6))
        self.cancel_legislation_button = ttk.Button(
            policies,
            text="取消立法（稳定度-5）",
            command=lambda: PoliticalWindow._cancel_legislation(self),
        )
        self.cancel_legislation_button.pack(fill="x", pady=(0, 6))
        law_grid = ttk.Frame(policies, style="Panel.TFrame")
        law_grid.pack(fill="both", expand=True)
        for index, (key, category_name) in enumerate(LAW_CATEGORIES.items()):
            ttk.Button(
                law_grid,
                text=f"{category_name}：{law_name(self.state, key)}",
                command=lambda category=key: self._show_law(category),
            ).grid(row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)
            law_grid.columnconfigure(index % 2, weight=1)
        self.footer()
        self.refresh()

    def _owned_regions(self):
        from ..content.v1_2.economy import region_economy

        names = set(self.state.player_regime.get("regions", []))
        return [
            (
                f"{region['name']}　稳定{region_economy(self.state, int(region['id']))['stability']} "
                f"控制{region_economy(self.state, int(region['id']))['control']}",
                int(region["id"]),
            )
            for region in self.state.regions.values()
            if region.get("name") in names and int(region.get("controller", 0)) == self.state.player_regime_id
        ]

    def _economic_regions(self):
        from ..content.v1_2.economy import region_economy

        return [
            (
                f"{region['name']}　稳定{region_economy(self.state, int(region['id']))['stability']} "
                f"控制{region_economy(self.state, int(region['id']))['control']}",
                int(region["id"]),
            )
            for region in self.state.regions.values()
            if int(region.get("controller", 0)) == self.state.player_regime_id
        ]

    def refresh(self):
        self.summary.set(f"权威值：{self.state.authority}　国库：{treasury_balance(self.state):g}")
        if self.state.legislation:
            category = str(self.state.legislation["category"])
            target = int(self.state.legislation["target_level"])
            progress = int(self.state.legislation.get("progress", 0))
            self.legislation_var.set(f"立法中：{LAW_LEVELS[category][target - 1]}　{progress}%")
            self.legislation_progress.configure(value=progress)
            self.cancel_legislation_button.configure(state="normal")
        else:
            self.legislation_var.set("立法中：无")
            self.legislation_progress.configure(value=0)
            self.cancel_legislation_button.configure(state="disabled")
        if hasattr(self, "decision_panel"):
            self.decision_panel.refresh()

    def _open_strategies(self):
        StrategyWindow(self, self.state, self.on_changed)

    def _show_law(self, category: str):
        PoliticalWindow._show_law(self, category)

    def _propose_law(self, category: str, target: int, window):
        PoliticalWindow._propose_law(self, category, target, window)

    def _force_law(self, category: str, target: int, window):
        PoliticalWindow._force_law(self, category, target, window)

    def _appoint(self):
        PoliticalWindow._appoint(self)

    def _dismiss_office(self):
        internal = self.state.player_regime["internal"]
        choices = [
            (f"{label}　{self.state.person_name(internal.get(key))}", ("office", key))
            for key, label in OFFICE_NAMES.items()
            if key != "emperor" and internal.get(key)
        ]
        choices.extend(
            (f"{region['name']}刺史　{self.state.person_name(region.get('governor'))}", ("governor", int(region["id"])))
            for region in self.state.regions.values()
            if region.get("name") in set(self.state.player_regime.get("regions", [])) and region.get("governor")
        )
        selected = choose_item(self, "卸任官员", "选择要解除的官职", choices)
        if not selected:
            return
        kind, value = selected
        if kind == "office":
            self.run_action(lambda: politics.dismiss(self.state, value))
        else:
            from ..content.v1_2.economy import dismiss_governor

            self.run_action(lambda: dismiss_governor(self.state, value))

    def _temporary_tax(self):
        from ..content.v1_2 import politics as v12_politics

        self.run_action(lambda: v12_politics.temporary_tax(self.state))

    def _relief(self):
        from ..content.v1_2 import politics as v12_politics

        region_id = choose_item(self, "赈灾救济", f"选择地区（国库{v12_politics.RELIEF_COPPER_COST:g}、权威100；地方稳定度+2）", self._owned_regions())
        if region_id:
            self.run_action(lambda: v12_politics.relief(self.state, region_id))

    def _conscript(self):
        capital_id = int(self.state.player_regime.get("capital") or 0)
        if military.city_controller(self.state, capital_id) != self.state.player_regime_id:
            messagebox.showwarning("无法征兵", "首都正被敌军控制，不能组建军队。", parent=self)
            return
        selection = army_creation_dialog(self, self.state)
        if selection is None:
            return
        army_type, battalions = selection
        self.run_action(lambda: f"军队#{military.create_army(self.state, self.state.player_regime_id, capital_id, army_type, battalions).id}组建完成。")

    def _amnesty(self):
        from ..content.v1_2 import politics as v12_politics

        self.run_action(lambda: v12_politics.amnesty(self.state))

    def _judge(self):
        PoliticalWindow._judge(self)

    def _develop(self):
        from ..content.v1_2 import politics as v12_politics

        region_id = choose_item(self, "兴修水利", f"选择地区（国库{v12_politics.DEVELOP_COPPER_COST:g}；地方稳定度+3）", self._owned_regions())
        if region_id:
            self.run_action(lambda: v12_politics.develop(self.state, region_id))

    def _fortify(self):
        PoliticalWindow._fortify(self)

    def _reclaim(self):
        from ..content.v1_2 import politics as v12_politics

        region_id = choose_item(self, "垦荒", f"选择地区（国库{v12_politics.RECLAIM_COPPER_COST:g}、权威50；三类土地各+5）", self._owned_regions())
        if region_id:
            self.run_action(lambda: v12_politics.reclaim_land(self.state, region_id))

    def _dismiss_governor(self):
        from ..content.v1_2.economy import dismiss_governor

        options = [
            (f"{region['name']}　{self.state.person_name(region.get('governor'))}", int(region["id"]))
            for region in self.state.regions.values()
            if region.get("name") in set(self.state.player_regime.get("regions", [])) and region.get("governor")
        ]
        region_id = choose_item(self, "卸任刺史", "宗室刺史不能主动卸任", options)
        if region_id:
            self.run_action(lambda: dismiss_governor(self.state, region_id))

    def _regional_economy(self):
        action = choose_item(
            self,
            "地区经济政令",
            "选择政令",
            [
                ("地区政策指导", "policy"),
                ("漕运", "convoy"),
                ("出售", "sell"),
                ("购买", "buy"),
                ("开仓放粮", "release"),
                ("扩仓", "expand"),
            ],
        )
        if action == "policy":
            self._local_policy_guidance()
        elif action == "convoy":
            self._convoy()
        elif action in {"sell", "buy"}:
            self._market_order(action)
        elif action == "release":
            self._release_grain()
        elif action == "expand":
            self._expand_warehouse()


class DevelopmentWindow(V12PoliticalWindow):
    """1.3 culture, buildings and local-economy phase."""

    def __init__(self, *args, **kwargs):
        StageWindow.__init__(self, *args, **kwargs)
        from ..content.v1_2.economy import LOCAL_POLICY_NAMES, format_resource, region_economy
        from ..content.v1_3.culture import culture_balance, region_approval

        self.culture_var = tk.StringVar()
        self.policy_vars: dict[int, tk.StringVar] = {}
        self.supply_vars: dict[int, tk.StringVar] = {}
        self.approval_vars: dict[int, tk.StringVar] = {}
        self.food_status_vars: dict[int, tk.StringVar] = {}
        self._policy_values = ("stockpile", "tax", "transfer", "stop")
        self._supply_values = (0.0, 1.0, 1.25, 1.5, 1.75, 2.0)
        header = ttk.Frame(self.content, style="Panel.TFrame", padding=16)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text="发展阶段 · 地方经济与文教", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.culture_var, style="Panel.TLabel").pack(side="right")
        toolbar = ttk.Frame(self.content, style="Panel.TFrame", padding=10)
        toolbar.pack(fill="x", padx=16, pady=4)
        ttk.Button(toolbar, text="地区经济政令", command=self._regional_economy).pack(side="left", padx=4)
        ttk.Button(toolbar, text="修建建筑", command=self._build_building).pack(side="left", padx=4)
        ttk.Button(toolbar, text="升级建筑", command=self._upgrade_building).pack(side="left", padx=4)
        ttk.Button(toolbar, text="主修经典", command=self._classics).pack(side="left", padx=4)
        grid = ttk.Frame(self.content, style="Panel.TFrame", padding=12)
        grid.pack(fill="both", expand=True, padx=16, pady=8)
        for column, (label, width) in enumerate((("地区", 14), ("经济方针", 10), ("文化供给", 10), ("认可度", 8), ("粮食状态", 16))):
            ttk.Label(grid, text=label, style="Subheading.TLabel", width=width).grid(row=0, column=column, sticky="ew", padx=3, pady=3)
        row = 1
        for region_id, region in sorted(self.state.regions.items()):
            if int(region.get("controller", 0)) != self.state.player_regime_id:
                continue
            record = region_economy(self.state, int(region_id))
            demand = len(__import__("app.content.v1_2.economy", fromlist=["population_units"]).population_units(self.state, int(region_id)))
            market_food = float(record["market"].get("food", 0.0))
            ttk.Button(
                grid,
                text=str(region["name"]),
                command=lambda rid=int(region_id): self._show_region_details(rid),
            ).grid(row=row, column=0, sticky="ew", padx=3, pady=2)
            policy = str(record.get("local_policy", "stockpile"))
            self.policy_vars[int(region_id)] = tk.StringVar(value=LOCAL_POLICY_NAMES.get(policy, policy))
            ttk.Button(
                grid,
                textvariable=self.policy_vars[int(region_id)],
                command=lambda rid=int(region_id): self._cycle_policy(rid),
            ).grid(row=row, column=1, sticky="ew", padx=3)
            supply = float(record.get("culture_supply", 1.0))
            self.supply_vars[int(region_id)] = tk.StringVar(value=f"{supply:g}倍")
            ttk.Button(
                grid,
                textvariable=self.supply_vars[int(region_id)],
                command=lambda rid=int(region_id): self._cycle_supply(rid),
            ).grid(row=row, column=2, sticky="ew", padx=3)
            self.approval_vars[int(region_id)] = tk.StringVar(value=str(region_approval(self.state, int(region_id))))
            ttk.Label(grid, textvariable=self.approval_vars[int(region_id)], style="Panel.TLabel").grid(row=row, column=3)
            food_text = f"缺口 {format_resource(demand-market_food)}" if market_food < demand else f"余量 {format_resource(market_food-demand)}"
            self.food_status_vars[int(region_id)] = tk.StringVar(value=food_text)
            ttk.Label(grid, textvariable=self.food_status_vars[int(region_id)], style="Panel.TLabel").grid(row=row, column=4)
            row += 1
        for column in range(5):
            grid.columnconfigure(column, weight=1)
        self.refresh()
        self.footer()

    def refresh(self):
        from ..content.v1_2.economy import LOCAL_POLICY_NAMES, format_resource, population_units, region_economy
        from ..content.v1_3.culture import culture_balance, monthly_culture_projection, region_approval

        projection = monthly_culture_projection(self.state)
        net = float(projection["net"])
        self.culture_var.set(
            f"文化值：{culture_balance(self.state):g}　"
            f"预计月产出：{format_resource(projection['produced'])}　"
            f"预计月消耗：{format_resource(projection['spent'])}　"
            f"净变化：{'+' if net >= 0 else ''}{format_resource(net)}"
        )
        for region_id, variable in self.policy_vars.items():
            record = region_economy(self.state, region_id)
            policy = str(record.get("local_policy", "stockpile"))
            variable.set(LOCAL_POLICY_NAMES.get(policy, policy))
            supply = float(record.get("culture_supply", 1.0))
            self.supply_vars[region_id].set(f"{supply:g}倍")
            self.approval_vars[region_id].set(str(region_approval(self.state, region_id)))
            demand = len(population_units(self.state, region_id))
            market_food = float(record["market"].get("food", 0.0))
            self.food_status_vars[region_id].set(
                f"缺口 {format_resource(demand-market_food)}"
                if market_food < demand
                else f"余量 {format_resource(market_food-demand)}"
            )

    def _cycle_policy(self, region_id):
        from ..content.v1_2.economy import region_economy, set_local_policy

        current = str(region_economy(self.state, region_id).get("local_policy", "stockpile"))
        index = self._policy_values.index(current) if current in self._policy_values else 0
        next_value = self._policy_values[(index + 1) % len(self._policy_values)]
        self.run_action(lambda: set_local_policy(self.state, self.state.player_regime_id, region_id, next_value), show_result=False)

    def _cycle_supply(self, region_id):
        from ..content.v1_2.economy import region_economy
        from ..content.v1_3.culture import set_culture_supply

        current = float(region_economy(self.state, region_id).get("culture_supply", 1.0))
        index = self._supply_values.index(current) if current in self._supply_values else 0
        next_value = self._supply_values[(index + 1) % len(self._supply_values)]
        self.run_action(lambda: set_culture_supply(self.state, region_id, next_value), show_result=False)

    def _show_region_details(self, region_id: int):
        from ..content.v1_2.economy import (
            format_resource,
            market_price,
            projected_region_production,
            region_economy,
            warehouse_resource_capacity,
        )
        from ..content.v1_3.culture import building_slot_status, region_culture_projection

        region = self.state.regions[int(region_id)]
        record = region_economy(self.state, int(region_id))
        warehouse = record["warehouse"]
        market = record["market"]
        production = projected_region_production(self.state, int(region_id))
        culture = region_culture_projection(self.state, int(region_id))
        governor_id = int(region.get("governor") or 0)
        governor = self.state.person_name(governor_id) if governor_id else "空缺"
        official_id = int(culture.get("school_official") or 0)
        official = self.state.person_name(official_id) if official_id else "空缺"
        school_supply = "供粮充足" if culture["school_supplied"] else "供粮不足或尚未建校"
        slots = building_slot_status(self.state, int(region_id))
        slot_lines = []
        for slot in slots:
            city_name = self.state.city_name(int(slot["city_id"]))
            building = slot["building"]
            if building:
                icon = "📜" if building.get("type") == "school" else "◆"
                building_text = f"{icon} {building.get('name', '建筑')}（等级{int(building.get('level', 1))}）"
            else:
                building_text = "空闲"
            slot_lines.append(f"槽位{slot['index']} · {city_name}：{building_text}")
        slot_text = "\n".join(slot_lines) if slot_lines else "该地区暂无可用建筑槽"
        used_slots = sum(1 for slot in slots if slot["building"])
        details = (
            f"【治理】\n"
            f"控制度：{format_resource(record.get('control', region.get('control', 0)))}　"
            f"稳定度：{format_resource(record.get('stability', region.get('local_stability', 0)))}　"
            f"同化度（中央认可度）：{culture['approval']}\n\n"
            f"【府库】\n"
            f"粮食：{format_resource(warehouse.get('food', 0))}/{format_resource(warehouse_resource_capacity(self.state, region_id, 'food'))}\n"
            f"布匹：{format_resource(warehouse.get('cloth', 0))}/{format_resource(warehouse_resource_capacity(self.state, region_id, 'cloth'))}\n"
            f"国家铜钱统一计入国库：{format_resource(treasury_balance(self.state))}\n\n"
            f"【市场】\n"
            f"粮食存量：{format_resource(market.get('food', 0))}　当前粮价：{format_resource(market_price(self.state, region_id, 'food'))}\n"
            f"布匹存量：{format_resource(market.get('cloth', 0))}　当前布价：{format_resource(market_price(self.state, region_id, 'cloth'))}\n\n"
            f"【预计产出】\n"
            f"正常年景粮食年产：{format_resource(production['food'])}　布匹年产：{format_resource(production['cloth'])}\n"
            f"地区每月文化产出：{format_resource(culture['total_output'])}"
            f"（人口{format_resource(culture['population_output'])}，学校{format_resource(culture['school_output'])}；不含中央固定20）\n"
            f"文化值基础消耗：{format_resource(culture['base_maintenance'])}/月　"
            f"当前{format_resource(culture['supply_multiplier'])}倍供给需求：{format_resource(culture['requested_maintenance'])}/月\n\n"
            f"【建筑槽】\n"
            f"已使用：{used_slots}/{len(slots)}\n"
            f"{slot_text}\n\n"
            f"【地方官员】\n"
            f"刺史：{governor}\n"
            f"学校：{culture['school_name']}（{school_supply}，月耗粮{format_resource(culture['school_food'])}）\n"
            f"祭酒：{official}"
        )
        window = tk.Toplevel(self)
        window.title(f"{region['name']} · 地区详情")
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PANEL)
        center_window(window, 720, 620)
        ttk.Label(window, text=f"{region['name']} · 地区详情", style="Heading.TLabel").pack(anchor="w", padx=22, pady=(18, 8))
        text_frame = ttk.Frame(window, style="Panel.TFrame")
        text_frame.pack(fill="both", expand=True, padx=20, pady=(0, 12))
        body = tk.Text(text_frame, wrap="word", font=("Microsoft YaHei UI", 11), background=theme.PANEL, relief="flat", padx=14, pady=12)
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=body.yview)
        body.configure(yscrollcommand=scrollbar.set)
        body.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body.insert("1.0", details)
        body.configure(state="disabled")
        ttk.Button(window, text="关闭", command=window.destroy).pack(anchor="e", padx=20, pady=(0, 16))

    def _build_building(self):
        from ..content.v1_2.economy import format_resource, region_economy
        from ..content.v1_3.culture import build_school, building_slot_status

        building_type = choose_item(
            self,
            "修建建筑",
            "选择建筑类型（其他建筑将在后续版本开放）",
            [("📜 学校", "school")],
        )
        if building_type != "school":
            return
        regions = []
        for region_id, region in self.state.regions.items():
            if int(region.get("controller", 0)) != self.state.player_regime_id:
                continue
            slots = building_slot_status(self.state, int(region_id))
            used = sum(1 for slot in slots if slot["building"])
            regions.append(
                (
                    f"{region['name']}　建筑槽{used}/{len(slots)}　控制度{format_resource(region_economy(self.state, int(region_id)).get('control', 0))}",
                    int(region_id),
                )
            )
        region_id = choose_item(self, "修建学校", "选择修建地区", regions)
        if region_id is not None:
            def build_result():
                building = build_school(self.state, int(region_id))
                region_name = self.state.regions[int(region_id)]["name"]
                return (
                    f"{region_name}成功修建{building['name']}，当前等级为{int(building['level'])}级；"
                    f"按控制度折算后实际花费国库铜钱{building['construction_cost']:g}。"
                )

            self.run_action(build_result, result_title="修建完成")

    def _upgrade_building(self):
        from ..content.v1_3.culture import region_buildings, upgrade_school

        choices = []
        for region_id, region in self.state.regions.items():
            if int(region.get("controller", 0)) != self.state.player_regime_id:
                continue
            for building in region_buildings(self.state, int(region_id)):
                if building.get("type") == "school":
                    choices.append(
                        (
                            f"📜 {region['name']} · {building.get('name', '学校')}　等级{int(building.get('level', 1))}",
                            (int(region_id), int(building.get("id", 0))),
                        )
                    )
        if not choices:
            messagebox.showinfo("升级建筑", "当前没有可以升级的建筑。", parent=self)
            return
        selected = choose_item(self, "升级建筑", "选择要升级的建筑（目前仅开放学校）", choices)
        if selected is None:
            return
        region_id, building_id = selected

        def upgrade_result():
            building = upgrade_school(self.state, int(region_id), int(building_id))
            region_name = self.state.regions[int(region_id)]["name"]
            return (
                f"{region_name}的{building['name']}升级完成，当前为{int(building['level'])}级；"
                f"按控制度折算后实际花费国库铜钱{building['last_upgrade_cost']:g}。"
            )

        self.run_action(upgrade_result, result_title="升级完成")

    def _school_management(self):
        from ..content.v1_3.culture import appoint_school_official, build_school, region_buildings, rename_school, upgrade_school
        regions = [(str(r["name"]), int(rid)) for rid, r in self.state.regions.items() if int(r.get("controller", 0)) == self.state.player_regime_id]
        region_id = choose_item(self, "学校管理", "选择地区", regions)
        if region_id is None:
            return
        school = next((x for x in region_buildings(self.state, region_id) if x.get("type") == "school"), None)
        if not school:
            self.run_action(
                lambda: f"成功修建{build_school(self.state, region_id)['name']}。",
                result_title="修建完成",
            )
            return
        action = choose_item(self, school["name"], f"等级{school['level']}，祭酒：{self.state.person_name(school.get('official'))}", [("升级", "upgrade"), ("改名", "rename"), ("任命祭酒", "official")])
        if action == "upgrade":
            self.run_action(
                lambda: f"{upgrade_school(self.state, region_id, int(school['id']))['name']}升级完成。",
                result_title="升级完成",
            )
        elif action == "rename":
            name = simpledialog.askstring("学校改名", "输入新名称", initialvalue=school["name"], parent=self)
            if name:
                self.run_action(lambda: rename_school(self.state, region_id, name))
        elif action == "official":
            candidates = [(self.state.person_name(pid), pid) for pid, p in self.state.persons.items() if int(p.get("country_id", 0)) == self.state.player_regime_id and int(p.get("status", 0)) == 1]
            person_id = choose_item(self, "任命祭酒", "选择官员", candidates)
            if person_id:
                self.run_action(lambda: appoint_school_official(self.state, region_id, person_id), show_result=False)

    def _classics(self):
        from ..content.v1_3.culture import POETRY_TREE, completed_poetry_nodes, study_classic_node
        completed = completed_poetry_nodes(self.state)
        choices = [(f"{'✓' if node_id in completed else '○'} {node['name']}　文化{node['cost']}", node_id) for node_id, node in POETRY_TREE.items() if node_id not in completed]
        node_id = choose_item(self, "主修经典 · 诗经", "尚书、礼记、易经、春秋将在后续更新", choices)
        if node_id:
            self.run_action(lambda: study_classic_node(self.state, "poetry", node_id))

    def _local_policy_guidance(self):
        from ..content.v1_2.economy import LOCAL_POLICY_NAMES, format_resource, region_economy, set_local_policy

        window = tk.Toplevel(self)
        window.title("地区政策指导")
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PANEL)
        window.minsize(720, 460)
        center_window(window, 900, 620)
        ttk.Label(window, text="地区政策指导", style="Heading.TLabel").pack(anchor="w", padx=20, pady=(18, 4))
        ttk.Label(
            window,
            text="地方会在每月结算阶段自行执行。新地区默认采用屯粮模式，自动行动不消耗中央权威。",
            style="Muted.TLabel",
            wraplength=840,
        ).pack(anchor="w", padx=20, pady=(0, 10))
        frame = ttk.Frame(window, style="Panel.TFrame", padding=10)
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        tree = ttk.Treeview(frame, columns=("region", "policy", "food", "cloth"), show="headings", selectmode="browse")
        for key, label, width in (
            ("region", "地区", 150), ("policy", "当前方针", 110), ("food", "府库粮食", 100),
            ("cloth", "府库布匹", 100),
        ):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="center")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        def render(selected_region=None):
            for item in tree.get_children():
                tree.delete(item)
            for _label, region_id in self._economic_regions():
                record = region_economy(self.state, region_id)
                warehouse = record["warehouse"]
                item = tree.insert("", "end", iid=str(region_id), values=(
                    self.state.regions[region_id]["name"],
                    LOCAL_POLICY_NAMES.get(str(record.get("local_policy", "stockpile")), "屯粮"),
                    format_resource(warehouse.get("food", 0)),
                    format_resource(warehouse.get("cloth", 0)),
                ))
                if selected_region == region_id:
                    tree.selection_set(item)
                    tree.see(item)

        def change(mode):
            selection = tree.selection()
            if not selection:
                messagebox.showwarning("请选择地区", "请先在列表中选择一个地区。", parent=window)
                return
            region_id = int(selection[0])
            try:
                set_local_policy(self.state, self.state.player_regime_id, region_id, mode)
            except RuleError as exc:
                messagebox.showwarning("无法调整", str(exc), parent=window)
                return
            render(region_id)
            self.on_changed()

        controls = ttk.Frame(window, style="Panel.TFrame", padding=(18, 0, 18, 16))
        controls.pack(fill="x")
        for mode in ("stockpile", "tax", "transfer", "stop"):
            ttk.Button(controls, text=LOCAL_POLICY_NAMES[mode], command=lambda selected=mode: change(selected)).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="关闭", command=window.destroy).pack(side="right")
        render()

    def _expand_warehouse(self):
        from ..content.v1_2.economy import (
            WAREHOUSE_EXPANSION_COPPER_COST,
            WAREHOUSE_EXPANSION_FOOD_COST,
            expand_warehouse,
            format_resource,
            warehouse_capacity,
        )

        options = [
            (
                f"{label.split('　')[0]}　当前容量{format_resource(warehouse_capacity(self.state, region_id))}",
                region_id,
            )
            for label, region_id in self._economic_regions()
        ]
        region_id = choose_item(
            self,
            "扩建州库",
            (
                f"选择地区：消耗当地粮食{format_resource(WAREHOUSE_EXPANSION_FOOD_COST)}、"
                f"铜钱{format_resource(WAREHOUSE_EXPANSION_COPPER_COST)}，所有资源容量+20"
            ),
            options,
        )
        if region_id:
            self.run_action(
                lambda: expand_warehouse(self.state, self.state.player_regime_id, region_id),
                result_title="经济行动报告",
            )

    def _economic_adviser(self):
        from ..content.v1_2.advisor import economic_advice, execute_economic_advice

        window = tk.Toplevel(self)
        window.title("顾问大臣 · 全国经济建议")
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PANEL)
        window.minsize(760, 480)
        center_window(window, 920, 650)

        header = ttk.Frame(window, style="Panel.TFrame", padding=18)
        header.pack(fill="x")
        ttk.Label(header, text="顾问大臣", style="Heading.TLabel").pack(side="left")
        authority_var = tk.StringVar()
        ttk.Label(header, textvariable=authority_var, style="Panel.TLabel").pack(side="right")
        ttk.Label(
            window,
            text="综合十二月民食缺口、布匹供需、各州库存与驻军六个月补给压力拟定。建议会随执行结果即时重算。",
            style="Muted.TLabel",
            wraplength=860,
        ).pack(anchor="w", padx=20, pady=(0, 10))

        shell = ttk.Frame(window, style="Panel.TFrame")
        shell.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        canvas = tk.Canvas(shell, background=theme.PANEL, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        rows = ttk.Frame(canvas, style="Panel.TFrame")
        row_window = canvas.create_window((0, 0), window=rows, anchor="nw")
        rows.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(row_window, width=event.width))
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"))

        def render():
            for child in rows.winfo_children():
                child.destroy()
            authority_var.set(f"当前权威：{self.state.authority}　每道政令消耗10")
            advice_list = economic_advice(self.state)
            if not advice_list:
                ttk.Label(
                    rows,
                    text="目前没有同时满足库存、路线、资金和供需条件的经济建议。",
                    style="Panel.TLabel",
                ).pack(anchor="w", padx=14, pady=18)
                return

            for index, advice in enumerate(advice_list, 1):
                card = ttk.Frame(rows, style="Panel.TFrame", padding=(12, 9))
                card.pack(fill="x", padx=4, pady=3)
                text_frame = ttk.Frame(card, style="Panel.TFrame")
                text_frame.pack(side="left", fill="x", expand=True)
                ttk.Label(
                    text_frame,
                    text=f"{index}. {advice['title']}",
                    style="Subheading.TLabel",
                ).pack(anchor="w")
                ttk.Label(
                    text_frame,
                    text=str(advice["reason"]),
                    style="Muted.TLabel",
                    wraplength=700,
                ).pack(anchor="w", pady=(3, 0))

                def execute(selected=advice):
                    try:
                        result = execute_economic_advice(self.state, selected)
                    except (RuleError, ValueError, KeyError) as exc:
                        messagebox.showwarning("无法执行", str(exc), parent=window)
                        render()
                        return
                    messagebox.showinfo("经济行动报告", str(result), parent=window)
                    self.refresh()
                    self.on_changed()
                    render()

                ttk.Button(
                    card,
                    text="执行",
                    style="Accent.TButton",
                    command=execute,
                    state="normal" if self.state.authority >= int(advice.get("authority_cost", 10)) else "disabled",
                ).pack(side="right", padx=(12, 0))

        controls = ttk.Frame(window, style="Panel.TFrame", padding=(18, 0, 18, 14))
        controls.pack(fill="x")
        ttk.Button(controls, text="关闭", command=window.destroy).pack(side="right")
        ttk.Button(controls, text="重新评估", command=render).pack(side="right", padx=(0, 8))
        render()

    def _market_order(self, action: str):
        from ..content.v1_2.economy import (
            GOOD_NAMES,
            executable_market_order_limit,
            food_market_balance_order_threshold,
            market_order,
            market_order_efficiency,
            market_price,
            region_economy,
        )

        region_id = choose_item(self, "地区市场", "选择实际控制的地区", self._economic_regions())
        if not region_id:
            return
        good = choose_item(
            self,
            "地区市场",
            "选择商品",
            [(GOOD_NAMES[key], key) for key in ("food", "cloth")],
        )
        if not good:
            return
        record = region_economy(self.state, region_id)
        control = float(record.get("control", 0))
        if control <= 0:
            messagebox.showwarning("无法交易", "地区控制度为0，无法执行市场命令。", parent=self)
            return
        price = market_price(self.state, region_id, good)
        maximum = executable_market_order_limit(
            self.state, self.state.player_regime_id, region_id, good, action
        )
        if maximum <= 0:
            reason = "州库无货或本回合粮食成交额度不足。" if action == "sell" else "市场无货、州库铜钱或本回合粮食成交额度不足。"
            messagebox.showwarning("无法交易", reason, parent=self)
            return
        verb = "出售" if action == "sell" else "购买"
        efficiency = market_order_efficiency(self.state, self.state.player_regime_id, region_id)
        markers = []
        if good == "food":
            threshold = food_market_balance_order_threshold(
                self.state, self.state.player_regime_id, region_id, action
            )
            if threshold is not None:
                markers.append((
                    threshold,
                    theme.GREEN if action == "sell" else theme.ACCENT,
                    "不缺粮线" if action == "sell" else "缺粮线",
                ))
        amount = amount_slider_dialog(
            self,
            f"{verb}{GOOD_NAMES[good]}",
            f"成交价：{price:g}　地区控制度：{control:g}%\n拖动滑条选择计划交易量。",
            maximum,
            initial=min(maximum, max(0.1, maximum / 2)),
            resolution=0.1,
            formatter=lambda selected: (
                f"计划{verb}：{selected:g}单位　"
                f"预计实际成交：{selected * efficiency:.2f}单位"
            ),
            markers=markers,
        )
        if amount:
            self.run_action(
                lambda: market_order(self.state, self.state.player_regime_id, region_id, good, action, amount),
                result_title="经济行动报告",
            )

    def _release_grain(self):
        from ..content.v1_2.economy import executable_release_grain_limit, region_economy, release_grain

        region_id = choose_item(self, "开仓放粮", "选择实际控制的地区", self._economic_regions())
        if not region_id:
            return
        record = region_economy(self.state, region_id)
        available = float(record["warehouse"].get("food", 0.0))
        control = float(record.get("control", 0))
        if available <= 0:
            messagebox.showwarning("无法放粮", "当地州库没有粮食。", parent=self)
            return
        if control <= 0:
            messagebox.showwarning("无法放粮", "地区控制度为0，无法组织放粮。", parent=self)
            return
        maximum = executable_release_grain_limit(self.state, self.state.player_regime_id, region_id)
        if maximum <= 0:
            messagebox.showwarning("无法放粮", "市场容量、州库粮食或权威不足。", parent=self)
            return
        amount = amount_slider_dialog(
            self,
            "开仓放粮",
            f"州库粮食：{available:g}　地区控制度：{control:g}%\n拖动滑条选择计划投放量。",
            maximum,
            initial=min(maximum, max(1.0, maximum / 2)),
            resolution=0.1,
            formatter=lambda selected: (
                f"计划投放：{selected:g}单位　"
                f"预计实际投放：{min(available, selected * control / 100):.2f}单位"
            ),
        )
        if amount:
            self.run_action(
                lambda: release_grain(self.state, self.state.player_regime_id, region_id, amount),
                result_title="经济行动报告",
            )

    def _convoy(self):
        from ..content.v1_2.economy import GOOD_NAMES, create_convoy, executable_convoy_limit, region_economy

        regions = self._economic_regions()
        source = choose_item(self, "建立官漕", "选择起运地区", regions)
        if not source:
            return
        target = choose_item(self, "建立官漕", "选择目的地区", [(label, value) for label, value in regions if value != source])
        if not target:
            return
        good = choose_item(
            self,
            "建立官漕",
            "选择调运内容（粮食、布匹是物资；铜钱作为款项调拨）",
            [(GOOD_NAMES[key], key) for key in ("food", "cloth")],
        )
        if not good:
            return
        source_record = region_economy(self.state, source)
        available = float(source_record["warehouse"].get(good, 0.0))
        control = float(source_record.get("control", 0))
        if available <= 0:
            messagebox.showwarning("无法建立官漕", f"来源州库没有{GOOD_NAMES[good]}。", parent=self)
            return
        if control <= 0:
            messagebox.showwarning("无法建立官漕", "来源地区控制度为0，无法组织调运。", parent=self)
            return
        maximum = executable_convoy_limit(
            self.state, self.state.player_regime_id, source, target, good
        )
        if maximum <= 0:
            messagebox.showwarning("无法建立官漕", "库存、权威或运输路线不足。", parent=self)
            return
        amount = amount_slider_dialog(
            self,
            "建立官漕",
            f"来源州库：{available:g}单位{GOOD_NAMES[good]}　地区控制度：{control:g}%\n拖动滑条选择计划运量。",
            maximum,
            initial=min(maximum, max(1.0, maximum / 2)),
            resolution=0.1,
            formatter=lambda selected: (
                f"计划调运：{selected:g}单位　"
                f"预计实际装运：{min(available, selected * control / 100):.2f}单位"
            ),
        )
        if amount:
            self.run_action(
                lambda: create_convoy(self.state, self.state.player_regime_id, source, target, good, amount),
                result_title="经济行动报告",
            )


# DevelopmentWindow reuses the mature 1.2 local-economy dialogs.  Keep them
# available on the political panel for 1.2 games, where that phase remains the
# documented entry point.
for _method_name in ("_local_policy_guidance", "_expand_warehouse", "_economic_adviser", "_market_order", "_release_grain", "_convoy"):
    setattr(V12PoliticalWindow, _method_name, getattr(DevelopmentWindow, _method_name))


class IntrigueWindow(StageWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        header = ttk.Frame(self.content, style="Panel.TFrame", padding=16)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text="谋划阶段 · 帷幄密议", style="Heading.TLabel").pack(side="left")
        ttk.Button(header, text="邀请大臣", command=self._invite).pack(side="right", padx=(8, 0))
        ttk.Button(header, text="除名亲信", command=self._remove).pack(side="right")
        body = ttk.Panedwindow(self.content, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=8)
        left = ttk.Frame(body, style="Panel.TFrame", padding=14)
        right = ttk.Frame(body, style="Panel.TFrame", padding=14)
        body.add(left, weight=1)
        body.add(right, weight=2)
        ttk.Label(left, text="亲信（每人每回合一次）", style="Subheading.TLabel").pack(anchor="w")
        self.confidants = tk.Listbox(left, font=("Microsoft YaHei UI", 11), background=theme.PANEL, borderwidth=0, exportselection=False)
        self.confidants.pack(fill="both", expand=True, pady=10)
        ttk.Label(right, text="行动目标", style="Subheading.TLabel").pack(anchor="w")
        self.targets = ttk.Treeview(right, columns=("name", "country", "family", "opinion", "alert"), show="headings")
        for col, text, width in (("name", "姓名", 100), ("country", "国籍", 70), ("family", "家族", 120), ("opinion", "好感", 60), ("alert", "警惕", 60)):
            self.targets.heading(col, text=text)
            self.targets.column(col, width=width, anchor="center")
        self.targets.pack(fill="both", expand=True, pady=10)
        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.pack(fill="x")
        for i, action in enumerate(intrigue.ACTIONS):
            ttk.Button(buttons, text=action, command=lambda a=action: self._perform(a)).grid(row=i // 5, column=i % 5, sticky="ew", padx=3, pady=3)
            buttons.columnconfigure(i % 5, weight=1)
        self.footer()
        self.refresh()

    def refresh(self):
        self.confidants.delete(0, "end")
        for pid in self.state.confidants:
            used = "（已行动）" if self.state.flags.get(f"turn:{self.state.turn_number}:intrigue:{pid}") else ""
            self.confidants.insert("end", f"{self.state.person_name(pid)}{used}")
        for item in self.targets.get_children():
            self.targets.delete(item)
        for person in intrigue.available_targets(self.state):
            regime = self.state.regimes.get(person.get("country_id"), {})
            family = self.state.families.get(person.get("family_id"), {})
            self.targets.insert("", "end", iid=str(person["id"]), values=(self.state.person_name(person["id"]), regime.get("name", "?"), family.get("name", "无"), person.get("opinion_of_player", 0), person.get("attributes", {}).get("alertness", 0)))

    def _selected_confidant(self):
        selected = self.confidants.curselection()
        return self.state.confidants[selected[0]] if selected else None

    def _perform(self, action):
        cid = self._selected_confidant()
        targets = self.targets.selection()
        if not cid or not targets:
            messagebox.showwarning("请选择", "先选择一名亲信和一名目标。", parent=self)
            return
        target = int(targets[0])
        chance = intrigue.ACTIONS[action][0]
        if not messagebox.askyesno("确认谋划", f"对{self.state.person_name(target)}执行“{action}”？\n基础成功率 {chance:.0%}", parent=self):
            return
        self.run_action(lambda: intrigue.perform(self.state, cid, target, action))

    def _invite(self):
        candidates = [(f"{self.state.person_name(p['id'])}　好感{p.get('opinion_of_player', 0)} 权力{int(person_power(self.state, p))}", p["id"]) for p in self.state.persons.values() if p.get("country_id") == self.state.player_regime_id and p.get("status") == 1 and p["id"] not in self.state.confidants and not p.get("is_player")]
        pid = choose_item(self, "邀请大臣", "邀请成为亲信（成功率取决于好感）", candidates)
        if pid:
            self.run_action(lambda: intrigue.invite_confidant(self.state, pid))

    def _remove(self):
        pid = choose_item(self, "除名亲信", "除名后其好感将变为 -100", [(self.state.person_name(x), x) for x in self.state.confidants])
        if pid and messagebox.askyesno("确认除名", f"确定除名{self.state.person_name(pid)}？", parent=self):
            self.run_action(lambda: intrigue.remove_confidant(self.state, pid))


class DiplomacyWindow(StageWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ttk.Label(self.content, text="外交阶段 · 纵横捭阖", style="Heading.TLabel").pack(anchor="w", padx=18, pady=(18, 8))
        body = ttk.Panedwindow(self.content, orient="horizontal")
        body.pack(fill="both", expand=True, padx=16, pady=8)
        left = ttk.Frame(body, style="Panel.TFrame", padding=14)
        right = ttk.Frame(body, style="Panel.TFrame", padding=18)
        body.add(left, weight=1)
        body.add(right, weight=2)
        self.regime_list = tk.Listbox(left, font=("Microsoft YaHei UI", 12), background=theme.PANEL, borderwidth=0, exportselection=False)
        self.regime_ids: list[int] = []
        self._rebuild_regime_list()
        self.regime_list.pack(fill="both", expand=True)
        self.regime_list.bind("<<ListboxSelect>>", lambda _e: self.refresh())
        self.detail = tk.StringVar(value="请选择政权")
        ttk.Label(right, textvariable=self.detail, style="Subheading.TLabel", justify="left", wraplength=620).pack(anchor="w", fill="x")
        ttk.Separator(right).pack(fill="x", pady=18)
        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.pack(fill="x")
        for i, action in enumerate(("遣使", "送礼", "羞辱", "联姻", "宣战", "和解", "要求臣服")):
            ttk.Button(buttons, text=action, command=lambda a=action: self._act(a)).grid(row=i // 4, column=i % 4, padx=5, pady=5, sticky="ew")
            buttons.columnconfigure(i % 4, weight=1)
        ttk.Label(right, text="每回合对每个政权只能采取一次外交行动。联姻将在后续剧本补充皇族婚配数据后开放。", style="Muted.TLabel", wraplength=620).pack(anchor="w", pady=20)
        self.footer()

    def _selected(self):
        selection = self.regime_list.curselection()
        return self.regime_ids[selection[0]] if selection else None

    def _rebuild_regime_list(self):
        selected_id = self._selected() if self.regime_ids else None
        active_ids = [
            regime_id for regime_id in self.state.regimes
            if regime_id != self.state.player_regime_id and not is_regime_eliminated(self.state, regime_id)
        ]
        if active_ids == self.regime_ids:
            return
        self.regime_ids = active_ids
        self.regime_list.delete(0, "end")
        for regime_id in self.regime_ids:
            self.regime_list.insert("end", self.state.regimes[regime_id]["name"])
        if selected_id in self.regime_ids:
            self.regime_list.selection_set(self.regime_ids.index(selected_id))

    def refresh(self):
        self._rebuild_regime_list()
        rid = self._selected()
        if not rid:
            self.detail.set("请选择左侧政权查看外交状态。")
            return
        r = self.state.regimes[rid]
        status = "本回合已行动" if rid in self.state.diplomatic_actions else "本回合可行动"
        war = "交战中" if self.state.at_war(self.state.player_regime_id, rid) else r.get("relation_with_main", "正常")
        self.detail.set(f"{r['name']}\n首都：{self.state.city_name(r.get('capital', 0))}\n关系：{war}　好感：{r.get('opinion_of_main', 0)}\n国库：{treasury_balance(self.state, rid):g}　稳定：{r.get('stability', 0)}　战争支持：{r.get('war_support', 0)}\n{status}")

    def _act(self, action):
        rid = self._selected()
        if not rid:
            messagebox.showwarning("请选择", "先选择一个政权。", parent=self)
            return
        if action == "联姻":
            messagebox.showinfo("联姻", "测试人物数据暂不具备完整皇室亲属婚配条件。", parent=self)
            return
        if action == "和解":
            terms = peace_treaty(self, self.state, rid)
            if terms is None:
                return
            self.run_action(lambda: diplomacy.make_peace(self.state, rid, terms))
            return
        envoy = None
        if action == "遣使":
            people = [(f"{self.state.person_name(p['id'])}　智力{p['attributes']['intelligence']}", p["id"]) for p in self.state.persons.values() if p.get("country_id") == self.state.player_regime_id and p.get("status") == 1]
            envoy = choose_item(self, "选择使节", "使节智力会影响出使结果", people)
            if not envoy:
                return
        self.run_action(lambda: diplomacy.act(self.state, rid, action, envoy))


class MilitaryWindow(StageWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        header = ttk.Frame(self.content, style="Panel.TFrame", padding=16)
        header.pack(fill="x", padx=16, pady=(16, 8))
        ttk.Label(header, text="军事阶段 · 调兵遣将", style="Heading.TLabel").pack(side="left")
        self.summary = tk.StringVar()
        ttk.Label(header, textvariable=self.summary, style="Panel.TLabel").pack(side="right")
        frame = ttk.Frame(self.content, style="Panel.TFrame", padding=14)
        frame.pack(fill="both", expand=True, padx=16, pady=8)
        self.tree = ttk.Treeview(frame, columns=("id", "type", "commander", "units", "supply", "morale", "exp", "location", "ap"), show="headings", selectmode="browse")
        for col, text, width in (("id", "军队", 60), ("type", "类型", 60), ("commander", "将领", 90), ("units", "兵力/营", 100), ("supply", "随军粮", 105), ("morale", "士气", 60), ("exp", "经验", 60), ("location", "所在地", 100), ("ap", "行动力", 70)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True)
        controls = ttk.Frame(frame, style="Panel.TFrame")
        controls.pack(fill="x", pady=(12, 0))
        for text, command in (("行军", self._march), ("一键行军", self._quick_march), ("进攻", self._attack), ("犒劳", self._reward), ("补充至满编", self._reinforce), ("任命/更换将领", self._commander), ("解散军队", self._disband), ("创建军队", self._create)):
            ttk.Button(controls, text=text, command=command).pack(side="left", padx=4)
        ttk.Separator(frame).pack(fill="x", pady=(12, 8))
        ttk.Label(frame, text="补给队", style="Subheading.TLabel").pack(anchor="w")
        self.supply_tree = ttk.Treeview(
            frame,
            columns=("id", "food", "location", "age", "ap"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for col, text, width in (
            ("id", "补给队", 80), ("food", "携粮", 100), ("location", "所在地", 130),
            ("age", "服役时间", 100), ("ap", "行动力", 90),
        ):
            self.supply_tree.heading(col, text=text)
            self.supply_tree.column(col, width=width, anchor="center")
        self.supply_tree.pack(fill="x", pady=(5, 0))
        supply_controls = ttk.Frame(frame, style="Panel.TFrame")
        supply_controls.pack(fill="x", pady=(8, 0))
        for text, command in (
            ("创建补给队", self._create_supply),
            ("移动补给队", self._march_supply),
            ("补给相邻军队", self._supply_army),
            ("撤销补给队", self._disband_supply),
        ):
            ttk.Button(supply_controls, text=text, command=command).pack(side="left", padx=4)
        self.footer()
        self.refresh()

    def refresh(self):
        selected = self.tree.selection()
        for item in self.tree.get_children():
            self.tree.delete(item)
        armies = [a for a in self.state.armies.values() if a.regime_id == self.state.player_regime_id]
        for army in armies:
            if str(self.state.flags.get("content_version", "1.1")) == "1.2":
                from ..content.v1_2.economy import army_supply_months

                supply = f"{army.supply_food:g}粮 / {army_supply_months(army):g}月"
            else:
                supply = "—"
            self.tree.insert("", "end", iid=str(army.id), values=(f"#{army.id}", "水军" if army.army_type else "陆军", self.state.person_name(army.commander), f"{army.soldiers}/{army.active_battalions}营", supply, army.morale, army.experience, self.state.city_name(army.location_id), f"{army.action_points:g}/{army.max_action_points:g}"))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        supply_selected = self.supply_tree.selection()
        for item in self.supply_tree.get_children():
            self.supply_tree.delete(item)
        if str(self.state.flags.get("content_version", "1.1")) == "1.2":
            from ..content.v1_2.supply_units import SUPPLY_UNIT_MAX_AGE, supply_units

            for unit in supply_units(self.state, self.state.player_regime_id):
                self.supply_tree.insert("", "end", iid=str(unit["id"]), values=(
                    f"#{unit['id']}",
                    f"{float(unit.get('food', 0)):g}",
                    self.state.city_name(int(unit.get("location_id", 0))),
                    f"{int(unit.get('age', 0))}/{SUPPLY_UNIT_MAX_AGE}月",
                    f"{float(unit.get('action_points', 0)):g}/{float(unit.get('max_action_points', 1)):g}",
                ))
        if supply_selected and self.supply_tree.exists(supply_selected[0]):
            self.supply_tree.selection_set(supply_selected[0])
        if str(self.state.flags.get("content_version", "1.1")) == "1.2":
            from ..content.v1_2.economy import manpower_balance, manpower_capacity

            self.summary.set(
                f"人力：{manpower_balance(self.state, self.state.player_regime_id)}"
                f"/{manpower_capacity(self.state, self.state.player_regime_id)}　"
                f"国库：{treasury_balance(self.state):g}"
            )
        else:
            self.summary.set(f"预备役：{self.state.player_regime['reserve_army']}　国库：{self.state.player_regime['treasury']}")

    def _selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("请选择", "先选择一支军队。", parent=self)
            return None
        return int(selected[0])

    def _selected_supply(self):
        selected = self.supply_tree.selection()
        if not selected:
            messagebox.showwarning("请选择", "先选择一支补给队。", parent=self)
            return None
        return int(selected[0])

    def _march(self):
        aid = self._selected()
        if not aid:
            return
        options = [(f"{self.state.city_name(city)}　经{ROAD_NAMES.get(road_type)}　消耗{cost:g}", city) for city, road_type, cost in military.legal_moves(self.state, aid)]
        target = choose_item(self, "行军", "选择合法目标", options)
        if target:
            self.run_action(lambda: military.march(self.state, aid, target), show_result=False)

    def _quick_march(self):
        aid = self._selected()
        if not aid:
            return
        routes = military.legal_march_routes(self.state, aid)
        if not routes:
            messagebox.showwarning("无法连续行军", "当前行动力内没有可直达的两步或三步目的地。", parent=self)
            return
        options = []
        for path, cost in routes:
            route_text = " → ".join(self.state.city_name(city_id) for city_id in path)
            options.append((f"{len(path)}步　{route_text}　总消耗{cost:g}", path))
        route = choose_item(self, "一键行军", "选择两步或三步可直达的最远目的地", options)
        if route:
            self.run_action(lambda: military.march_route(self.state, aid, route), show_result=False)

    def _attack(self):
        aid = self._selected()
        if not aid:
            return
        options = [(f"{self.state.city_name(city)}　经{ROAD_NAMES.get(road_type)}", city) for city, road_type in military.legal_attacks(self.state, aid)]
        target = choose_item(self, "进攻", "选择敌军驻守的相邻城市", options)
        if target and messagebox.askyesno("确认进攻", f"向{self.state.city_name(target)}发起进攻？这会耗尽行动力。", parent=self):
            self.run_action(lambda: military.attack(self.state, aid, target))

    def _reward(self):
        aid = self._selected()
        if aid:
            self.run_action(lambda: military.reward(self.state, aid))

    def _reinforce(self):
        aid = self._selected()
        if not aid:
            return
        need = military.reinforcement_need(self.state.armies[aid])
        if need <= 0:
            messagebox.showinfo("无需补充", "该军队已经满编。", parent=self)
            return
        if messagebox.askyesno("补充至满编", f"补充缺额{need}人并消耗等量人力？", parent=self):
            self.run_action(lambda: military.reinforce_army(self.state, aid))

    def _commander(self):
        aid = self._selected()
        if not aid:
            return
        assigned = {a.commander for a in self.state.armies.values() if a.commander}
        options = [("卸任当前将领", None)] + [(f"{self.state.person_name(p['id'])}　武力{p['attributes']['military']}", p["id"]) for p in self.state.persons.values() if p.get("country_id") == self.state.player_regime_id and p.get("status") == 1 and p["id"] not in assigned]
        marker = choose_item(self, "任命将领", "选择将领（选择第一项可卸任）", [(label, (True, value)) for label, value in options])
        if marker is not None:
            self.run_action(lambda: military.assign_commander(self.state, aid, marker[1]))

    def _disband(self):
        aid = self._selected()
        prompt = "士兵将解除军籍。确定解散？" if str(self.state.flags.get("content_version", "1.1")) == "1.2" else "士兵将回到预备役。确定解散？"
        if aid and messagebox.askyesno("解散军队", prompt, parent=self):
            self.run_action(lambda: military.disband(self.state, aid))

    def _create(self):
        capital_id = int(self.state.player_regime.get("capital") or 0)
        if military.city_controller(self.state, capital_id) != self.state.player_regime_id:
            messagebox.showwarning("无法创建", "首都正被敌军控制，不能创建军队。", parent=self)
            return
        selection = army_creation_dialog(self, self.state)
        if selection is None:
            return
        army_type, battalions = selection
        self.run_action(lambda: f"军队#{military.create_army(self.state, self.state.player_regime_id, capital_id, army_type, battalions).id}组建完成。")

    def _create_supply(self):
        if str(self.state.flags.get("content_version", "1.1")) != "1.2":
            messagebox.showwarning("无法创建", "补给队仅在1.2版本中可用。", parent=self)
            return
        from ..content.v1_2.economy import format_resource, region_economy
        from ..content.v1_2.supply_units import create_supply_unit

        options = []
        for city in self.state.cities.values():
            region_id = int(city.get("region_id", 0))
            region = self.state.regions.get(region_id, {})
            if not city.get("capital") or int(region.get("controller", 0)) != self.state.player_regime_id:
                continue
            record = region_economy(self.state, region_id)
            options.append((
                f"{region.get('name', '未知')}·{city['name']}　府库粮食{format_resource(record['warehouse'].get('food', 0))}　控制{record.get('control', 0)}",
                int(city["id"]),
            ))
        city_id = choose_item(self, "创建补给队", "选择本国实际控制的地区首府", options)
        if city_id is None:
            return
        region_id = int(self.state.cities[city_id]["region_id"])
        record = region_economy(self.state, region_id)
        available = float(record["warehouse"].get("food", 0.0))
        control = float(record.get("control", 0.0))
        if available <= 0 or control <= 0:
            messagebox.showwarning("无法创建", "当地府库没有粮食，或地区控制度为0。", parent=self)
            return
        amount = amount_slider_dialog(
            self,
            "装载补给队粮食",
            f"府库粮食：{available:g}　地区控制度：{control:g}%\n计划量不能超过府库库存，控制度只影响实际装载量。",
            available,
            initial=min(available, max(1.0, available / 2)),
            resolution=0.1,
            formatter=lambda selected: f"计划装载：{selected:g}　预计实际装载：{selected * control / 100:.2f}",
        )
        if amount:
            self.run_action(
                lambda: f"补给队#{create_supply_unit(self.state, self.state.player_regime_id, city_id, amount)['id']}创建完成。"
            )

    def _march_supply(self):
        unit_id = self._selected_supply()
        if unit_id is None:
            return
        from ..content.v1_2.supply_units import legal_supply_moves, march_supply_unit

        options = [
            (f"{self.state.city_name(city_id)}　经{ROAD_NAMES.get(road_type)}　消耗{cost:g}", city_id)
            for city_id, road_type, cost in legal_supply_moves(self.state, unit_id)
        ]
        if not options:
            messagebox.showwarning("无法移动", "该补给队当前没有可到达的相邻城市。", parent=self)
            return
        target = choose_item(self, "移动补给队", "按普通陆军道路规则移动一格", options)
        if target is not None:
            self.run_action(lambda: march_supply_unit(self.state, unit_id, target), show_result=False)

    def _supply_army(self):
        unit_id = self._selected_supply()
        if unit_id is None:
            return
        from ..content.v1_2.economy import army_supply_capacity
        from ..content.v1_2.supply_units import get_supply_unit, supply_army, supply_targets

        targets = supply_targets(self.state, unit_id)
        options = [
            (
                f"军队#{army_id}　{self.state.city_name(self.state.armies[army_id].location_id)}　"
                f"现有{self.state.armies[army_id].supply_food:g}/{army_supply_capacity(self.state.armies[army_id]):g}粮",
                army_id,
            )
            for army_id, _room in targets
        ]
        if not options:
            messagebox.showwarning("无法补给", "道路相连的一格内没有需要粮食的己方军队。", parent=self)
            return
        army_id = choose_item(self, "补给相邻军队", "选择道路相连一格内的己方军队", options)
        if army_id is None:
            return
        room = dict(targets)[army_id]
        unit = get_supply_unit(self.state, unit_id)
        maximum = min(float(unit.get("food", 0.0)), float(room))
        amount = amount_slider_dialog(
            self,
            "交付军粮",
            f"补给队携粮：{float(unit.get('food', 0)):g}　目标军队剩余容量：{room:g}",
            maximum,
            initial=maximum,
            resolution=0.1,
        )
        if amount:
            self.run_action(lambda: supply_army(self.state, unit_id, army_id, amount))

    def _disband_supply(self):
        unit_id = self._selected_supply()
        if unit_id is None:
            return
        if messagebox.askyesno("撤销补给队", "剩余粮食不会返还府库，确定撤销？", parent=self):
            from ..content.v1_2.supply_units import disband_supply_unit

            self.run_action(lambda: disband_supply_unit(self.state, unit_id))


WINDOW_BY_PHASE = {
    0: PoliticalWindow,
    1: IntrigueWindow,
    2: DiplomacyWindow,
    3: MilitaryWindow,
}

WINDOW_BY_PHASE_NAME = {
    "政治阶段": V12PoliticalWindow,
    "发展阶段": DevelopmentWindow,
    "谋划阶段": IntrigueWindow,
    "外交阶段": DiplomacyWindow,
    "军事阶段": MilitaryWindow,
}
