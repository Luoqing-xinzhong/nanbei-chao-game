from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..data_loader import DataError
from ..v11 import load_v11_state
from ..content.v1_2.scenario import load_v12_state
from ..content.v1_2.climate import queue_march_climate_report, reveal_climate_report
from ..models import GameState
from ..content.runtime import apply_event_choice, queue_start_of_turn_events, render_dynamic_text
from ..rules.turn import advance_phase
from ..rules.ai_modifiers import set_difficulty
from ..rules.common import RuleError
from ..save_service import list_save_slots, load_game, save_game, save_slot_label
from .dialogs import center_window, choose_item
from .main_screen import MainGameScreen
from .sidebar_stages import sidebar_for
from .status_panels import CourtWindow, DiplomacyStatusWindow, EconomyWindow, FamiliesWindow, MilitaryStatusWindow, ModifiersWindow, PartiesWindow, V12EconomyWindow
from . import theme


class GameApplication:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("南国魂 · 南北朝策略游戏")
        self.root.geometry("1440x900")
        self.root.minsize(1024, 680)
        self.root.configure(background=theme.BG)
        try:
            self.root.state("zoomed")
        except tk.TclError:
            pass
        self.style = ttk.Style(root)
        theme.configure_theme(self.style)
        self.state: GameState | None = None
        self.screen: ttk.Frame | None = None
        self.main_screen: MainGameScreen | None = None
        self.stage_window: ttk.Frame | None = None
        self.status_window: tk.Toplevel | None = None
        self.show_menu()

    def _clear_screen(self):
        if self.stage_window and self.stage_window.winfo_exists():
            self.stage_window.destroy()
        if self.status_window and self.status_window.winfo_exists():
            self.status_window.destroy()
        self.stage_window = None
        self.status_window = None
        if self.screen:
            self.screen.destroy()
        self.main_screen = None

    def show_menu(self):
        if self.state and self.main_screen:
            if not messagebox.askyesno("返回主菜单", "尚未保存的进度会丢失，确定返回？", parent=self.root):
                return
        self._apply_theme("default")
        self.state = None
        self._clear_screen()
        self.screen = ttk.Frame(self.root)
        self.screen.pack(fill="both", expand=True)
        center = ttk.Frame(self.screen, style="Panel.TFrame", padding=55)
        center.place(relx=.5, rely=.5, anchor="center", relwidth=.46, relheight=.68)
        ttk.Label(center, text="南 国 魂", style="Title.TLabel").pack(pady=(35, 4))
        ttk.Label(center, text="南北朝历史策略游戏 · 测试版", style="Muted.TLabel").pack(pady=(0, 45))
        ttk.Button(center, text="开始游戏", style="Accent.TButton", command=self.show_scenarios).pack(fill="x", pady=8, ipady=6)
        ttk.Button(center, text="读取存档", command=self.show_load_dialog).pack(fill="x", pady=8, ipady=6)
        ttk.Button(center, text="退出游戏", command=self.root.destroy).pack(fill="x", pady=8, ipady=6)
        ttk.Label(center, text="滚动地图、管理朝堂、经营国力，在四阶段回合中重塑天下。", style="Panel.TLabel", wraplength=520, justify="center").pack(side="bottom", pady=25)

    def show_scenarios(self):
        self._clear_screen()
        self.screen = ttk.Frame(self.root)
        self.screen.pack(fill="both", expand=True)
        ttk.Label(self.screen, text="选择剧本", style="Title.TLabel").pack(pady=(45, 8))
        ttk.Label(self.screen, text="不同剧本将拥有各自的政权、人物与局势", style="Muted.TLabel").pack()
        cards = ttk.Frame(self.screen)
        cards.pack(fill="both", expand=True, padx=70, pady=45)
        scenarios = [
            ("1. 金戈铁马", "桓玄败亡，晋室还都。刘裕坐镇建康，旧秩序在兵戈间摇摇欲坠。", True),
            ("2. 九锡流转", "刘宋与北魏隔河对峙。", False),
            ("3. 菩萨天子", "北魏朝堂风雨欲来。", False),
            ("4. 后庭玉树", "江南承平将尽。", False),
        ]
        for i, (title, description, enabled) in enumerate(scenarios):
            card = ttk.Frame(cards, style="Panel.TFrame", padding=24)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=12, pady=12)
            cards.columnconfigure(i % 2, weight=1, uniform="scenario_columns")
            cards.rowconfigure(i // 2, weight=1, uniform="scenario_rows")
            ttk.Label(card, text=title, style="Heading.TLabel").pack(anchor="w")
            ttk.Label(card, text=description, wraplength=500, style="Panel.TLabel").pack(anchor="w", pady=14)
            command = self.show_subscenarios if enabled else lambda: messagebox.showinfo("剧本未开放", "该剧本将在后续版本开放。", parent=self.root)
            ttk.Button(card, text="进入剧本" if enabled else "尚未开放", style="Accent.TButton" if enabled else "TButton", command=command).pack(side="bottom", fill="x")
        ttk.Button(self.screen, text="返回", command=self.show_menu).pack(pady=(0, 28))

    def show_subscenarios(self):
        self._clear_screen()
        self.screen = ttk.Frame(self.root)
        self.screen.pack(fill="both", expand=True)
        panel = ttk.Frame(self.screen, style="Panel.TFrame", padding=24)
        panel.place(relx=.5, rely=.5, anchor="center", relwidth=.62, relheight=.68)
        ttk.Label(panel, text="金戈铁马 · 选择子剧本", style="Title.TLabel").pack(pady=(6, 4))
        ttk.Label(panel, text="文教南国点击开始后，可选择默认数据或继承元嘉之治结算存档。", style="Muted.TLabel").pack(pady=(0, 10))
        choices = (
            ("1.1", "宋武北伐", "从义熙元年开始，可直接创建新游戏。"),
            ("1.2", "元嘉之治", "公元422年至433年腊月，可直接创建新游戏。"),
            ("wenjiao_south", "文教南国", "公元434年至446年腊月；开始时选择默认数据或继承元嘉之治结算存档。"),
            ("inherit:blood_tears", "血泪江左", "公元447年开始；只能继承文教南国结算存档。"),
        )
        for version, title, description in choices:
            row = ttk.Frame(panel, style="Panel.TFrame", padding=(10, 6))
            row.pack(fill="x", pady=3)
            row.columnconfigure(0, weight=1)
            ttk.Label(row, text=title, style="Heading.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(row, text=description, style="Panel.TLabel", wraplength=650).grid(row=1, column=0, sticky="w", pady=(1, 0))
            ttk.Button(
                row,
                text="开始" if version == "wenjiao_south" else "选择",
                style="Accent.TButton",
                command=lambda selected=version: (
                    self.show_wenjiao_start_choice()
                    if selected == "wenjiao_south"
                    else self.show_inheritance(selected.split(":", 1)[1])
                    if selected.startswith("inherit:")
                    else self.show_difficulty(selected)
                ),
            ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        ttk.Button(panel, text="返回剧本选择", command=self.show_scenarios).pack(side="bottom", pady=(8, 0))

    def show_wenjiao_start_choice(self):
        selected = choose_item(
            self.root,
            "开始文教南国",
            "请选择文教南国的开局方式：",
            [
                ("默认数据开局（使用二号存档提取的独立默认状态）", "default"),
                ("继承元嘉之治结算存档", "inherit"),
            ],
        )
        if selected == "default":
            self.show_difficulty("1.3:wenjiao_south")
        elif selected == "inherit":
            self.show_inheritance("wenjiao_south")

    def show_inheritance(self, target: str):
        from ..content.v1_3.scenario import inherit_scenario, inheritance_available

        candidates = []
        for slot, path in list_save_slots():
            if not path.exists():
                continue
            try:
                state = load_game(path)
            except (OSError, ValueError, KeyError):
                continue
            if inheritance_available(state, target)[0]:
                candidates.append((save_slot_label(slot, path), path))
        if not candidates:
            required = "元嘉之治433年腊月" if target == "wenjiao_south" else "文教南国446年腊月"
            messagebox.showwarning("没有可继承存档", f"需要{required}结算后生成的继承存档。", parent=self.root)
            return
        selected = choose_item(self.root, "选择继承存档", "将完整继承政权、人物、地区、经济、军队、法律与剧情状态", candidates)
        if selected is None:
            return
        try:
            self.state = inherit_scenario(load_game(Path(selected)), target)
        except (OSError, ValueError, RuleError) as exc:
            messagebox.showerror("无法继承", str(exc), parent=self.root)
            return
        self._apply_theme("blue")
        self.show_main_game()
        self.open_stage()

    def show_difficulty(self, content_version: str = "1.1"):
        self._clear_screen()
        self.screen = ttk.Frame(self.root)
        self.screen.pack(fill="both", expand=True)
        panel = ttk.Frame(self.screen, style="Panel.TFrame", padding=42)
        panel.place(relx=.5, rely=.5, anchor="center", relwidth=.56, relheight=.70)
        ttk.Label(panel, text="选择难度", style="Title.TLabel").pack(pady=(18, 8))
        ttk.Label(
            panel,
            text=(
                "难度会改变年度气候概率、AI军队攻防修正与补给消耗。"
                if content_version == "1.2" or content_version.startswith("1.3:")
                else "难度只改变AI军队的常态攻防修正，经济与剧情规则保持一致。"
            ),
            style="Muted.TLabel",
        ).pack(pady=(0, 28))
        climate_notes = {
            "easy": "；丰收年概率提高",
            "normal": "；各种灾害年概率提高",
            "hard": "；各种灾害年概率大幅提高",
        } if content_version == "1.2" or content_version.startswith("1.3:") else {"easy": "", "normal": "", "hard": ""}
        supply_notes = {
            "easy": "；AI军粮消耗-50%，伤亡战争支持损失-70%",
            "normal": "；AI军粮消耗-70%，伤亡战争支持损失-80%",
            "hard": "；AI军粮消耗-85%，伤亡战争支持损失-90%",
        } if content_version == "1.2" or content_version.startswith("1.3:") else {"easy": "", "normal": "", "hard": ""}
        difficulties = [
            ("easy", "简单", "无额外攻防修正" + supply_notes["easy"] + climate_notes["easy"]),
            ("normal", "普通", "所有AI军队常态攻击力与防御作战力+20%" + supply_notes["normal"] + climate_notes["normal"]),
            ("hard", "困难", "所有AI军队常态攻击力与防御作战力+40%" + supply_notes["hard"] + climate_notes["hard"]),
        ]
        for key, title, description in difficulties:
            row = ttk.Frame(panel, style="Panel.TFrame", padding=12)
            row.pack(fill="x", pady=7)
            ttk.Label(row, text=title, style="Heading.TLabel", width=6).pack(side="left")
            ttk.Button(
                row,
                text="...",
                width=3,
                command=lambda name=title, detail=description: messagebox.showinfo(
                    f"{name}难度",
                    detail,
                    parent=self.root,
                ),
            ).pack(side="left", padx=(4, 12))
            ttk.Button(
                row,
                text="选择",
                style="Accent.TButton",
                command=lambda selected=key: self.start_new_game(selected, content_version),
            ).pack(side="right")
        ttk.Button(panel, text="返回子剧本选择", command=self.show_subscenarios).pack(side="bottom", pady=(20, 0))

    def start_new_game(self, difficulty: str = "easy", content_version: str = "1.1"):
        try:
            if content_version == "1.3:wenjiao_south":
                from ..content.v1_3.scenario import load_default_wenjiao_state

                self.state = load_default_wenjiao_state()
            else:
                self.state = load_v12_state() if content_version == "1.2" else load_v11_state()
        except (DataError, RuleError) as exc:
            messagebox.showerror("配置错误", str(exc), parent=self.root)
            return
        self.state.flags.pop("ai_opponent_mode", None)
        self.state.flags.pop("deepseek_model", None)
        set_difficulty(self.state, difficulty)
        queue_start_of_turn_events(self.state)
        self._apply_theme("blue")
        self.show_main_game()
        self._show_pending_story_events()
        self._show_pending_ai_peace_offer()
        self._show_v12_climate_report()
        self._show_v12_production_report()
        self.open_stage()

    def _apply_theme(self, name: str) -> None:
        theme.use_palette(name)
        theme.configure_theme(self.style)
        self.root.configure(background=theme.BG)

    def show_main_game(self):
        if not self.state:
            return
        self._clear_screen()
        self.screen = ttk.Frame(self.root)
        self.screen.pack(fill="both", expand=True)
        self.main_screen = MainGameScreen(self.screen, self.state, {
            "status": self.open_status,
            "stage": self.open_stage,
            "save": self.save_current,
            "menu": self.show_menu,
            "changed": self.refresh,
        })

    def _show_pending_story_events(self):
        if not self.state:
            return
        pending = [int(x) for x in self.state.flags.pop("pending_story_events", [])]
        for event_id in pending:
            event = self.state.events.get(event_id)
            if not event:
                continue
            window = tk.Toplevel(self.root)
            window.title(f"事件 · {event['name']}")
            window.geometry("820x680")
            window.minsize(620, 480)
            window.transient(self.root)
            window.configure(background=theme.BG)
            ttk.Label(window, text=event["name"], style="Heading.TLabel").pack(anchor="w", padx=28, pady=(24, 5))
            ttk.Label(window, text=event.get("summary", ""), style="Muted.TLabel", wraplength=740).pack(anchor="w", padx=28, pady=(0, 12))
            # Reserve the action row at the bottom before giving the narrative
            # the remaining expandable space.  Long event text/effect notes can
            # no longer push mandatory choices below the window edge.
            controls = ttk.Frame(window, style="Panel.TFrame")
            controls.pack(side="bottom", fill="x", padx=28, pady=(0, 20))
            effect_label = ttk.Label(window, text=f"效果：{event.get('effect_description', '无')}", style="Panel.TLabel", wraplength=750)
            effect_label.pack(side="bottom", anchor="w", padx=28, pady=(0, 12))
            text_frame = ttk.Frame(window, style="Panel.TFrame")
            text_frame.pack(fill="both", expand=True, padx=26, pady=(0, 12))
            text = tk.Text(text_frame, wrap="word", font=("Microsoft YaHei UI", 11), background=theme.PANEL, relief="flat", padx=18, pady=16)
            scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=scrollbar.set)
            text.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            text.insert("1.0", render_dynamic_text(self.state, event.get("text", "")))
            text.configure(state="disabled")
            choices = list(event.get("choices", []))
            if choices:
                if event.get("choice_required"):
                    window.protocol("WM_DELETE_WINDOW", lambda: None)

                def choose_story_option(selected, eid=event_id, event_window=window, body=text, row=controls):
                    try:
                        result_text = apply_event_choice(self.state, eid, selected)
                    except ValueError as exc:
                        messagebox.showwarning("无法选择", str(exc), parent=event_window)
                        return
                    body.configure(state="normal")
                    body.delete("1.0", "end")
                    body.insert("1.0", result_text)
                    body.configure(state="disabled")
                    for child in row.winfo_children():
                        child.destroy()
                    ttk.Button(row, text="继续", style="Accent.TButton", command=event_window.destroy).pack(side="right")
                    event_window.protocol("WM_DELETE_WINDOW", event_window.destroy)
                    queue_start_of_turn_events(self.state)

                ttk.Label(controls, text="必须选择：", style="Subheading.TLabel").pack(side="left")
                for choice in choices:
                    ttk.Button(
                        controls,
                        text=choice,
                        style="Accent.TButton",
                        command=lambda selected=choice: choose_story_option(selected),
                    ).pack(side="left", padx=6)
            else:
                ttk.Button(controls, text="继续", style="Accent.TButton", command=window.destroy).pack(side="right")
            center_window(window, 820, 680)
            window.grab_set()
            self.root.wait_window(window)
        # 强制事件选项可能立即解锁同回合后续事件，继续显示新入队内容。
        if self.state.flags.get("pending_story_events"):
            self._show_pending_story_events()

    def _show_pending_ai_peace_offer(self):
        if not self.state:
            return
        offer = self.state.flags.get("pending_ai_peace_offer")
        if not isinstance(offer, dict):
            return
        from ..rules.diplomacy import accept_ai_peace_offer, reject_ai_peace_offer

        regime_id = int(offer.get("regime_id", 0))
        regime = self.state.regimes.get(regime_id)
        if not regime or not self.state.at_war(self.state.player_regime_id, regime_id):
            self.state.flags.pop("pending_ai_peace_offer", None)
            return
        terms = dict(offer.get("terms", {}))

        def region_names(key: str) -> str:
            return "、".join(
                self.state.regions[int(region_id)]["name"]
                for region_id in terms.get(key, [])
                if int(region_id) in self.state.regions
            ) or "无"

        from ..rules.diplomacy import occupied_regions

        returned_regions = set(occupied_regions(self.state, regime_id, self.state.player_regime_id)) - {
            int(region_id) for region_id in terms.get("player_cedes", [])
        }
        returned_names = "、".join(
            self.state.regions[region_id]["name"] for region_id in sorted(returned_regions)
        ) or "无"
        returned_to_ai = set(occupied_regions(self.state, self.state.player_regime_id, regime_id)) - {
            int(region_id) for region_id in terms.get("target_cedes", [])
        }
        returned_to_ai_names = "、".join(
            self.state.regions[region_id]["name"] for region_id in sorted(returned_to_ai)
        ) or "无"

        lines = [
            f"{regime['name']}提出以下和平条件：",
            "",
            f"对方割让给我方：{region_names('target_cedes')}",
            f"我方归还给对方：{returned_to_ai_names}",
            f"我方割让给对方：{region_names('player_cedes')}",
            f"对方归还我方占领地：{returned_names}",
            f"对方支付赔款：{int(terms.get('target_pays', 0))}",
            f"我方支付赔款：{int(terms.get('player_pays', 0))}",
            "",
            str(offer.get("evaluation", "")),
            "",
            "拒绝后，该政权四个月内不会再次提出和平协议。",
        ]
        window = tk.Toplevel(self.root)
        window.title(f"外交 · {regime['name']}和平提议")
        window.transient(self.root)
        window.resizable(False, False)
        window.configure(background=theme.PANEL)
        ttk.Label(window, text="和平协议", style="Heading.TLabel").pack(anchor="w", padx=28, pady=(24, 8))
        ttk.Label(
            window,
            text="\n".join(lines),
            style="Panel.TLabel",
            wraplength=690,
            justify="left",
        ).pack(fill="both", expand=True, anchor="w", padx=28, pady=(0, 16))
        controls = ttk.Frame(window, style="Panel.TFrame")
        controls.pack(fill="x", padx=28, pady=(0, 22))
        resolved = {"value": False}

        def accept():
            try:
                message = accept_ai_peace_offer(self.state)
            except RuleError as exc:
                messagebox.showwarning("协议失效", str(exc), parent=window)
                self.state.flags.pop("pending_ai_peace_offer", None)
            else:
                messagebox.showinfo("缔结和平", message, parent=window)
            resolved["value"] = True
            window.destroy()
            self.refresh()

        def reject():
            if not resolved["value"] and self.state.flags.get("pending_ai_peace_offer"):
                reject_ai_peace_offer(self.state)
            resolved["value"] = True
            window.destroy()
            self.refresh()

        ttk.Button(controls, text="接受协议", style="Accent.TButton", command=accept).pack(side="right", padx=(8, 0))
        ttk.Button(controls, text="拒绝协议", command=reject).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", reject)
        center_window(window, 760, 480)
        window.grab_set()
        self.root.wait_window(window)

    def _show_v12_production_report(self):
        if not self.state or self.state.flags.get("content_version") != "1.2":
            return
        report = list(self.state.flags.pop("pending_v12_production_report", []))
        if not report:
            return
        owned = set(self.state.player_regime.get("regions", []))
        rows = [row for row in report if row.get("region") in owned]
        if not rows:
            return
        window = tk.Toplevel(self.root)
        window.title("七月生产报告")
        window.geometry("1260x650")
        window.minsize(820, 500)
        window.transient(self.root)
        window.configure(background=theme.BG)
        climate_name = str(report[0].get("climate", "未知气候"))
        ttk.Label(window, text=f"七月各州生产报告 · {climate_name}", style="Heading.TLabel").pack(anchor="w", padx=24, pady=(20, 4))
        ttk.Label(
            window,
            text="粮食产量不受土地征收系数影响；实物税率=税率法律×征收系数。七月另按实际粮税的50%收入铜钱，并按人口、控制度和战争支持度征集人力。",
            style="Muted.TLabel",
            wraplength=960,
        ).pack(anchor="w", padx=24, pady=(0, 12))
        frame = ttk.Frame(window, style="Panel.TFrame", padding=12)
        frame.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        tree = ttk.Treeview(
            frame,
            columns=("region", "weather", "disaster", "population", "farmers", "land", "food", "coefficient", "tax_rate", "tax_copper", "cloth", "warehouse", "market", "balance", "warning"),
            show="headings",
        )
        for column, label, width in (
            ("region", "地区", 85), ("weather", "灾害/年景", 70), ("disaster", "即时灾损", 105), ("population", "人口需求", 75),
            ("farmers", "农民", 55), ("land", "土地", 55), ("food", "粮食产量", 75),
            ("coefficient", "征收系数", 70), ("tax_rate", "实物税率", 70),
            ("tax_copper", "粮税铜钱", 70), ("cloth", "布匹产量", 75), ("warehouse", "州库粮", 70), ("market", "市场粮", 70),
            ("balance", "预计余缺", 70), ("warning", "提示", 100),
        ):
            tree.heading(column, text=label)
            tree.column(column, width=width, anchor="center")
        shortage_count = 0
        from ..content.v1_2.economy import format_resource

        for row in rows:
            shortage = bool(row.get("shortage"))
            shortage_count += int(shortage)
            tree.insert("", "end", values=(
                row["region"], row["weather"],
                (
                    f"人口-{int(row.get('disaster_deaths', 0))}，稳定-{int(row.get('stability_loss', 0))}"
                    if int(row.get("disaster_deaths", 0)) or int(row.get("stability_loss", 0))
                    else "—"
                ),
                row["population"], row["farmers"], row["land"],
                format_resource(row['food']), f"{float(row.get('tax_collection_coefficient', 0)):.1%}",
                f"{float(row.get('food_tax_rate', 0)):.1%}", format_resource(row.get('copper_from_food_tax', 0)),
                format_resource(row['cloth']), format_resource(row['warehouse_food']),
                format_resource(row['market_food']), format_resource(row['projected_balance']),
                "可能缺粮" if shortage else "供应可维持",
            ), tags=("shortage",) if shortage else ())
        tree.tag_configure("shortage", foreground="#b52a2a")
        tree.pack(fill="both", expand=True)
        footer = ttk.Frame(window, style="Panel.TFrame", padding=(22, 0, 22, 18))
        footer.pack(fill="x")
        manpower_gain = max((int(row.get("national_manpower_gain", 0)) for row in rows), default=0)
        ttk.Label(
            footer,
            text=f"本年共有 {shortage_count} 个地区可能出现粮食缺口；全国获得人力 {manpower_gain}。",
            style="Panel.TLabel",
        ).pack(side="left")
        ttk.Button(footer, text="确认", style="Accent.TButton", command=window.destroy).pack(side="right")
        center_window(window, 1260, 650)
        window.grab_set()
        self.root.wait_window(window)

    def _show_v12_climate_report(self):
        if not self.state or self.state.flags.get("content_version") != "1.2":
            return
        queue_march_climate_report(self.state)
        year = self.state.flags.pop("pending_v12_climate_report", None)
        if year is None:
            return
        if not messagebox.askyesno(
            "太史局天气报告",
            f"太史局已完成{int(year)}年大气候推演。\n消耗100权威查看报告？",
            parent=self.root,
        ):
            return
        try:
            report = reveal_climate_report(self.state, int(year))
        except RuleError as exc:
            messagebox.showwarning("权威不足", str(exc), parent=self.root)
            return
        messagebox.showinfo("太史局天气报告", report, parent=self.root)
        self.refresh()

    def show_load_dialog(self):
        slots = [(slot, path) for slot, path in list_save_slots() if path.exists()]
        if not slots:
            messagebox.showinfo("读取存档", "还没有存档。开始新游戏后可在主界面保存。", parent=self.root)
            return
        selected = choose_item(
            self.root,
            "读取存档",
            "选择存档位",
            [(save_slot_label(slot, path), path) for slot, path in slots],
        )
        if not selected:
            return
        try:
            loaded_state = load_game(Path(selected))
        except Exception as exc:
            messagebox.showerror("读取失败", f"无法读取存档：{exc}", parent=self.root)
            return
        self.state = loaded_state
        # AI对手测试模式已废除；兼容读取旧存档，但不再恢复外部模型控制。
        self.state.flags.pop("ai_opponent_mode", None)
        self.state.flags.pop("deepseek_model", None)
        # 兼容剧情系统加入前生成的存档；只在回合开始阶段补做事件检查。
        if self.state.phase_index == 0:
            queue_start_of_turn_events(self.state)
        self._apply_theme("blue")
        self.show_main_game()
        self._show_v12_climate_report()
        self._show_pending_story_events()
        self._show_pending_ai_peace_offer()
        self._show_v12_production_report()
        self.open_stage()

    def save_current(self):
        if not self.state:
            return
        slots = list_save_slots()
        selected_slot = choose_item(
            self.root,
            "保存游戏",
            "选择一个存档位；已有存档可以覆盖",
            [(save_slot_label(slot, path), slot) for slot, path in slots],
        )
        if selected_slot is None:
            return
        selected_path = next(path for slot, path in slots if slot == int(selected_slot))
        if selected_path.exists() and not messagebox.askyesno(
            "覆盖存档",
            f"存档位 {int(selected_slot):02d} 已有内容，确定覆盖吗？",
            parent=self.root,
        ):
            return
        try:
            era_name = self.state.flags.get("era_name", "元兴")
            path = save_game(
                self.state,
                f"{era_name}_{self.state.year}_{self.state.month}月",
                slot=int(selected_slot),
            )
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        messagebox.showinfo("保存成功", f"存档已保存：\n{path.name}", parent=self.root)

    def open_stage(self):
        if not self.state or not self.main_screen:
            return
        if self.stage_window and self.stage_window.winfo_exists():
            self.main_screen.expand_stage_panel()
            return
        cls = sidebar_for(self.state)
        self.stage_window = cls(
            self.main_screen.stage_host,
            self.state,
            self._advance_phase,
            self.refresh,
            self._stage_closed,
        )
        self.main_screen.set_stage_panel(self.stage_window)

    def _stage_closed(self):
        if self.main_screen:
            self.main_screen.clear_stage_panel()
        self.stage_window = None

    def _advance_phase(self):
        if not self.state:
            return
        self.root.configure(cursor="wait")
        self.root.update_idletasks()
        try:
            result = advance_phase(self.state)
        finally:
            self.root.configure(cursor="")
        self.state.add_log(result)
        self.refresh()
        self._show_v12_climate_report()
        self._show_v12_production_report()
        self._show_pending_story_events()
        self._show_pending_ai_peace_offer()
        self._handle_v13_transition()
        if self.state.flags.get("game_over"):
            messagebox.showerror("游戏结束", self.state.flags.get("game_over_reason", "政权已经覆灭。"), parent=self.root)
            return
        # 阶段窗口关闭后直接接续下一阶段，不再插入确认弹窗。
        self.root.after(80, self.open_stage)

    def _handle_v13_transition(self):
        if not self.state or not self.state.flags.get("v13_transition_ready"):
            return
        from ..content.v1_3.scenario import inherit_scenario

        transition = dict(self.state.flags["v13_transition_ready"])
        target_name = "文教南国" if transition.get("target") == "wenjiao_south" else "血泪江左"
        choice = messagebox.askyesnocancel(
            "子剧本结算完成",
            f"本子剧本已经完成。\n是：快速继承并进入《{target_name}》\n否：保存结算存档\n取消：稍后处理",
            parent=self.root,
        )
        if choice is True:
            inherit_scenario(self.state, str(transition["target"]))
            self.refresh()
        elif choice is False:
            self.save_current()

    def open_status(self, kind: str):
        if not self.state:
            return
        if self.status_window and self.status_window.winfo_exists():
            self.status_window.destroy()
        classes = {
            "court": CourtWindow,
            "families": FamiliesWindow,
            "economy": EconomyWindow,
            "military": MilitaryStatusWindow,
            "diplomacy": DiplomacyStatusWindow,
            "parties": PartiesWindow,
            "modifiers": ModifiersWindow,
        }
        if kind == "economy" and self.state.flags.get("content_version") == "1.2":
            classes["economy"] = V12EconomyWindow
        self.status_window = classes[kind](self.root, self.state, self._status_closed)

    def _status_closed(self):
        self.status_window = None

    def refresh(self):
        if self.main_screen:
            self.main_screen.refresh()
        if self.stage_window and self.stage_window.winfo_exists():
            self.stage_window.refresh()


def run() -> None:
    root = tk.Tk()
    GameApplication(root)
    root.mainloop()
