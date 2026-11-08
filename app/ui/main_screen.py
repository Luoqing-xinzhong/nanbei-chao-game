from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..models import GameState
from ..rules.common import RuleError
from ..rules.military import city_controller
from ..rules.turn import calendar_text
from ..rules.treasury import treasury_balance
from . import theme
from .dragon_layout import BLUE, INK, PAPER, DragonBackdrop, scaled_rect
from .military_quick_actions import MilitaryQuickActions, player_armies_at_city
from .widgets import MapView


def chronicle_history(state: GameState) -> list[str]:
    """Return every non-battle chronicle entry in saved order."""
    return [str(item) for item in state.event_log if not str(item).startswith("【战报】")]


def military_history(state: GameState) -> list[str]:
    """Return all available reports while preserving repeated battles."""
    event_reports = [str(item) for item in state.event_log if str(item).startswith("【战报】")]
    if event_reports:
        return event_reports
    return [str(item) for item in state.flags.get("battle_reports", [])]


class MainGameScreen(ttk.Frame):
    def __init__(self, master, state: GameState, callbacks: dict[str, callable]):
        super().__init__(master)
        self.state = state
        self.callbacks = callbacks
        self.stage_panel: ttk.Frame | None = None
        self.military_quick_window: MilitaryQuickActions | None = None
        self.economic_mode = False
        self.economic_convoy_source: int | None = None
        self.stage_expanded = False
        self.pack(fill="both", expand=True)
        self.backdrop = DragonBackdrop(self, callbacks["status"], callbacks["menu"], callbacks["save"])
        self.backdrop.place(x=0, y=0, relwidth=1, relheight=1)
        self.info_var = tk.StringVar()
        self.stage_host = tk.Frame(self, background=PAPER, borderwidth=0)
        self.map_frame = tk.Frame(self, background=BLUE, borderwidth=0)
        self.map = MapView(
            self.map_frame,
            state,
            self._city_details,
            self._show_logistics_details,
            self._show_supply_details,
            self._city_double_click,
        )
        self.map.pack(fill="both", expand=True)
        self.economic_mode_button = ttk.Button(
            self.map_frame,
            text="经济模式",
            command=self._toggle_economic_mode,
        )
        if str(self.state.flags.get("content_version", "1.1")) == "1.2":
            self.economic_mode_button.place(relx=1.0, x=-14, y=14, anchor="ne")
        log_frame = tk.Frame(self, background=PAPER, borderwidth=0)
        self.log_frame = log_frame
        self.log_tabs = ttk.Notebook(log_frame, style="Dragon.TNotebook")
        self.log_tabs.pack(fill="both", expand=True)
        chronicle_frame = tk.Frame(self.log_tabs, background=PAPER)
        self.log_tabs.add(chronicle_frame, text="纪事")
        self.chronicle_log = tk.Text(
            chronicle_frame, width=1, height=1, wrap="word", state="disabled",
            background=PAPER, foreground=INK, relief="flat", font=("Microsoft YaHei UI", 10),
            padx=8, pady=8, highlightthickness=0,
        )
        self.chronicle_log.pack(fill="both", expand=True, pady=(8, 4))
        ttk.Button(
            chronicle_frame, text="历史", command=lambda: self._open_history("纪事历史", chronicle_history(self.state)),
        ).pack(fill="x", pady=(0, 8))

        military_frame = tk.Frame(self.log_tabs, background=PAPER)
        self.log_tabs.add(military_frame, text="军事")
        self.military_log = tk.Text(
            military_frame, width=1, height=1, wrap="word", state="disabled",
            background=PAPER, foreground=INK, relief="flat", font=("Microsoft YaHei UI", 10),
            padx=8, pady=8, highlightthickness=0,
        )
        self.military_log.pack(fill="both", expand=True, pady=(8, 4))
        ttk.Button(
            military_frame, text="历史", command=lambda: self._open_history("军事历史", military_history(self.state)),
        ).pack(fill="x")
        self.bind("<Configure>", self._layout_shell, add="+")
        self.refresh()

    def _layout_shell(self, event=None):
        if event is not None and event.widget is not self:
            return
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        for name, widget in (("stage", self.stage_host), ("map", self.map_frame), ("logs", self.log_frame)):
            x, y, w, h = scaled_rect(name, width, height)
            widget.place(x=x, y=y, width=w, height=h)

    def set_stage_panel(self, panel: ttk.Frame) -> None:
        self.stage_panel = panel
        self.expand_stage_panel()

    def clear_stage_panel(self) -> None:
        self.stage_panel = None
        self.stage_expanded = False

    def expand_stage_panel(self) -> None:
        if not self.stage_panel or not self.stage_panel.winfo_exists():
            self.callbacks["stage"]()
            return
        self.stage_panel.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.stage_panel.lift()
        self.stage_expanded = True

    def collapse_stage_panel(self) -> None:
        # Compatibility entrypoint: the narrow side panel no longer covers the map.
        self.expand_stage_panel()

    def toggle_stage_panel(self) -> None:
        self.expand_stage_panel()

    def refresh(self):
        if self.military_quick_window and self.military_quick_window.winfo_exists() and self.state.phase != "军事阶段":
            self.military_quick_window.close()
        economic_phase = "发展阶段" if str(self.state.flags.get("rules_version", "")) == "1.3" else "政治阶段"
        if self.state.phase != economic_phase and self.economic_convoy_source is not None:
            self.economic_convoy_source = None
            self.map.selected_economic_region_id = None
            self.economic_mode_button.configure(text="返回政权地图" if self.economic_mode else "经济模式")
        regime = self.state.player_regime
        manpower_text = ""
        if str(self.state.flags.get("content_version", "1.1")) == "1.2":
            from ..content.v1_2.economy import manpower_balance, manpower_capacity

            manpower_text = (
                f"　人力：{manpower_balance(self.state, self.state.player_regime_id)}"
                f"/{manpower_capacity(self.state, self.state.player_regime_id)}"
            )
            if str(self.state.flags.get("rules_version", "")) == "1.3":
                from ..content.v1_3.culture import culture_balance

                manpower_text += f"　文化：{culture_balance(self.state):g}"
        self.info_var.set(
            f"{calendar_text(self.state)}　{self.state.phase}\n"
            f"国号：{regime['name']}　稳定度：{regime['stability']}　战争支持：{regime['war_support']}　"
            f"国库：{treasury_balance(self.state):g}{manpower_text}　权威：{self.state.authority}"
        )
        self.backdrop.date_text = calendar_text(self.state).replace("　", " ")
        self.backdrop.phase_names = tuple(self.state.phase_names)
        self.backdrop.phase_index = self.state.phase_index
        self.backdrop.state_lines = [
            f"国号：{regime['name']}    {self.state.phase}",
            f"国库：{treasury_balance(self.state):g} 铜钱",
            f"权威：{self.state.authority} / 2000",
            f"稳定度：{regime['stability']}",
            f"战争支持：{regime['war_support']}",
        ]
        if str(self.state.flags.get("content_version", "1.1")) == "1.2":
            self.backdrop.state_lines.append(
                f"人力：{manpower_balance(self.state, self.state.player_regime_id)}"
                f" / {manpower_capacity(self.state, self.state.player_regime_id)}"
            )
            if str(self.state.flags.get("rules_version", "")) == "1.3":
                self.backdrop.state_lines.append(f"文化值：{culture_balance(self.state):g}")
        else:
            self.backdrop.state_lines.append(f"预备役：{regime.get('reserve_army', 0)}")
        self.backdrop.redraw()
        self._refresh_log_widget(self.chronicle_log, chronicle_history(self.state))
        self._refresh_log_widget(self.military_log, military_history(self.state))
        self.map.redraw()

    @staticmethod
    def _refresh_log_widget(widget: tk.Text, records: list[str]) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        recent = list(reversed(records[-5:]))
        widget.insert("1.0", "\n\n".join(recent) if recent else "暂无记录")
        widget.configure(state="disabled")

    def _open_history(self, title: str, records: list[str]) -> None:
        from .dialogs import center_window

        window = tk.Toplevel(self)
        window.title(title)
        window.transient(self.winfo_toplevel())
        window.configure(background=theme.PANEL)
        ttk.Label(window, text=f"{title} · 共{len(records)}条", style="Heading.TLabel").pack(
            anchor="w", padx=18, pady=(16, 8),
        )
        content = ttk.Frame(window, style="Panel.TFrame")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        text = tk.Text(
            content, wrap="word", state="normal", background=theme.PANEL,
            relief="flat", font=("Microsoft YaHei UI", 10), padx=8, pady=8,
        )
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text.insert("1.0", "\n\n".join(records) if records else "暂无记录")
        text.configure(state="disabled")
        ttk.Button(window, text="关闭", command=window.destroy).pack(pady=(0, 14))
        center_window(window, 760, 620)

    def _city_details(self, city_id: int):
        economic_phase = "发展阶段" if str(self.state.flags.get("rules_version", "")) == "1.3" else "政治阶段"
        if self.economic_mode and self.state.phase == economic_phase and self.state.cities[city_id].get("capital"):
            self._economic_capital_click(city_id)
            return
        if self.state.phase == "军事阶段" and player_armies_at_city(self.state, city_id):
            self._open_military_quick_actions(city_id)
            return
        self._show_city_details(city_id)

    def _city_double_click(self, city_id: int) -> None:
        city = self.state.cities.get(city_id, {})
        economic_phase = "发展阶段" if str(self.state.flags.get("rules_version", "")) == "1.3" else "政治阶段"
        if not (self.economic_mode and self.state.phase == economic_phase and city.get("capital")):
            return
        region_id = int(city.get("region_id", 0))
        if int(self.state.regions.get(region_id, {}).get("controller", 0)) != self.state.player_regime_id:
            messagebox.showwarning("无法发布经济命令", "只能向本国实际控制的地区发布命令。", parent=self)
            return
        self._open_economic_quick_actions(region_id)

    def _open_economic_quick_actions(self, region_id: int) -> None:
        from .dialogs import choose_item

        action = choose_item(
            self,
            f"{self.state.regions[region_id]['name']} · 快捷经济命令",
            "选择要执行的地区经济命令",
            [
                ("出售粮食或布匹", "sell"),
                ("购入粮食或布匹", "buy"),
                ("开仓放粮", "release"),
                ("扩建州库", "expand"),
                ("建立漕运", "convoy"),
            ],
        )
        if action in {"sell", "buy"}:
            self._quick_market_order(region_id, str(action))
        elif action == "release":
            self._quick_release_grain(region_id)
        elif action == "expand":
            self._quick_expand_warehouse(region_id)
        elif action == "convoy":
            self._quick_convoy(region_id)

    def _quick_market_order(self, region_id: int, action: str) -> None:
        from ..content.v1_2.economy import (
            GOOD_NAMES,
            executable_market_order_limit,
            food_market_balance_order_threshold,
            market_order,
            market_order_efficiency,
            market_price,
            region_economy,
        )
        from .dialogs import amount_slider_dialog, choose_item

        good = choose_item(self, "快捷交易", "选择商品", [(GOOD_NAMES[key], key) for key in ("food", "cloth")])
        if not good:
            return
        maximum = executable_market_order_limit(
            self.state, self.state.player_regime_id, region_id, str(good), action
        )
        if maximum <= 0:
            messagebox.showwarning("无法交易", "库存、余额、容量、成交额度或权威不足，当前没有可执行量。", parent=self)
            return
        record = region_economy(self.state, region_id)
        control = float(record.get("control", 0.0))
        verb = "出售" if action == "sell" else "购入"
        efficiency = market_order_efficiency(self.state, self.state.player_regime_id, region_id)
        markers = []
        if str(good) == "food":
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
            f"{verb}{GOOD_NAMES[str(good)]}",
            f"成交价：{market_price(self.state, region_id, str(good)):g}　控制度：{control:g}%\n"
            f"滑条上限{maximum:g}已按当前库存、铜钱、容量与成交额度锁定。",
            maximum,
            initial=min(maximum, max(0.1, maximum / 2)),
            resolution=0.1,
            formatter=lambda selected: (
                f"计划{verb}：{selected:g}单位　预计实际成交：{selected * efficiency:.2f}单位"
            ),
            markers=markers,
        )
        if amount:
            self._run_quick_economic_action(
                lambda: market_order(
                    self.state, self.state.player_regime_id, region_id, str(good), action, amount
                )
            )

    def _quick_release_grain(self, region_id: int) -> None:
        from ..content.v1_2.economy import executable_release_grain_limit, release_grain
        from .dialogs import amount_slider_dialog

        maximum = executable_release_grain_limit(self.state, self.state.player_regime_id, region_id)
        if maximum <= 0:
            messagebox.showwarning("无法放粮", "州库粮食、市场容量或权威不足，当前没有可执行量。", parent=self)
            return
        amount = amount_slider_dialog(
            self,
            "开仓放粮",
            f"滑条上限{maximum:g}已按州库库存、市场容量和地区控制度锁定。",
            maximum,
            initial=min(maximum, max(0.1, maximum / 2)),
            resolution=0.1,
        )
        if amount:
            self._run_quick_economic_action(
                lambda: release_grain(self.state, self.state.player_regime_id, region_id, amount)
            )

    def _quick_expand_warehouse(self, region_id: int) -> None:
        from ..content.v1_2.economy import (
            WAREHOUSE_EXPANSION_COPPER_COST,
            WAREHOUSE_EXPANSION_FOOD_COST,
            expand_warehouse,
        )

        region_name = self.state.regions[region_id]["name"]
        if not messagebox.askyesno(
            "扩建州库",
            f"在{region_name}消耗粮食{WAREHOUSE_EXPANSION_FOOD_COST:g}、铜钱{WAREHOUSE_EXPANSION_COPPER_COST:g}扩建州库？",
            parent=self,
        ):
            return
        self._run_quick_economic_action(
            lambda: expand_warehouse(self.state, self.state.player_regime_id, region_id)
        )

    def _quick_convoy(self, source_region_id: int) -> None:
        from .dialogs import choose_item

        targets = [
            (region["name"], int(region_id))
            for region_id, region in self.state.regions.items()
            if int(region_id) != source_region_id
            and int(region.get("controller", 0)) == self.state.player_regime_id
        ]
        target = choose_item(self, "建立漕运", "选择目的州府", targets)
        if target:
            self._open_map_convoy_dialog(source_region_id, int(target))

    def _run_quick_economic_action(self, action) -> None:
        try:
            report = action()
        except RuleError as exc:
            messagebox.showwarning("无法执行经济命令", str(exc), parent=self)
            return
        messagebox.showinfo("经济行动报告", str(report), parent=self)
        self.callbacks["changed"]()

    def _toggle_economic_mode(self) -> None:
        self.economic_mode = not self.economic_mode
        self.economic_convoy_source = None
        self.map.economic_mode = self.economic_mode
        self.map.selected_economic_region_id = None
        self.economic_mode_button.configure(text="返回政权地图" if self.economic_mode else "经济模式")
        self.map.redraw()

    def _economic_capital_click(self, city_id: int) -> None:
        region_id = int(self.state.cities[city_id].get("region_id", 0))
        region = self.state.regions.get(region_id, {})
        if int(region.get("controller", 0)) != self.state.player_regime_id:
            messagebox.showwarning("无法建立漕运", "只能选择本国实际控制的州府。", parent=self)
            return
        if self.economic_convoy_source is None:
            self.economic_convoy_source = region_id
            self.map.selected_economic_region_id = region_id
            self.economic_mode_button.configure(text=f"漕运起点：{region.get('name', '')}")
            self.map.redraw()
            return
        if self.economic_convoy_source == region_id:
            self.economic_convoy_source = None
            self.map.selected_economic_region_id = None
            self.economic_mode_button.configure(text="返回政权地图")
            self.map.redraw()
            return
        source = int(self.economic_convoy_source)
        self.economic_convoy_source = None
        self.map.selected_economic_region_id = None
        self.economic_mode_button.configure(text="返回政权地图")
        self._open_map_convoy_dialog(source, region_id)
        self.map.redraw()

    def _open_map_convoy_dialog(self, source_region_id: int, target_region_id: int) -> None:
        from ..content.v1_2.economy import GOOD_NAMES, create_convoy, executable_convoy_limit, region_economy
        from .dialogs import amount_slider_dialog, choose_item

        good = choose_item(
            self,
            "建立漕运",
            f"{self.state.regions[source_region_id]['name']} → {self.state.regions[target_region_id]['name']}\n选择漕运货物",
            [(GOOD_NAMES[key], key) for key in ("food", "cloth")],
        )
        if not good:
            return
        source_record = region_economy(self.state, source_region_id)
        available = float(source_record["warehouse"].get(good, 0.0))
        control = float(source_record.get("control", 0.0))
        maximum = executable_convoy_limit(
            self.state, self.state.player_regime_id, source_region_id, target_region_id, str(good)
        )
        if maximum <= 0:
            messagebox.showwarning("无法建立漕运", f"{GOOD_NAMES[good]}库存、权威或运输路线不足。", parent=self)
            return
        amount = amount_slider_dialog(
            self,
            "建立漕运",
            f"可用{GOOD_NAMES[good]}：{available:g}　地区控制度：{control:g}%\n拖动滑条选择计划运量。",
            maximum,
            initial=min(maximum, max(0.1, maximum / 2)),
            resolution=0.1,
            formatter=lambda selected: (
                f"计划调运：{selected:g}　预计实际装运：{min(available, selected * control / 100):.2f}"
            ),
        )
        if not amount:
            return
        try:
            report = create_convoy(
                self.state,
                self.state.player_regime_id,
                source_region_id,
                target_region_id,
                str(good),
                amount,
            )
        except RuleError as exc:
            messagebox.showwarning("无法建立漕运", str(exc), parent=self)
            return
        messagebox.showinfo("经济行动报告", report, parent=self)
        self.callbacks["changed"]()

    def _open_military_quick_actions(self, city_id: int):
        if self.military_quick_window and self.military_quick_window.winfo_exists():
            self.military_quick_window.destroy()
        self.military_quick_window = MilitaryQuickActions(
            self,
            self.state,
            city_id,
            self.callbacks["changed"],
            self._military_quick_closed,
        )

    def _military_quick_closed(self):
        self.military_quick_window = None

    def _show_city_details(self, city_id: int):
        city = self.state.cities[city_id]
        region = self.state.regions.get(city.get("region_id"), {})
        controller = self.state.regimes.get(city_controller(self.state, city_id), {})
        armies = [a for a in self.state.armies.values() if a.location_id == city_id]
        army_text = "、".join(f"#{a.id} {a.soldiers}人" for a in armies) or "无"
        messagebox.showinfo(
            city["name"],
            f"地区：{region.get('name', '未知')}\n控制者：{controller.get('name', '无')}\n"
            f"首府：{'是' if city.get('capital') else '否'}\n城防：{city.get('defense', 0)}\n驻军：{army_text}",
            parent=self,
        )

    def _show_logistics_details(self, logistics_id: int):
        from ..content.v1_2.economy import GOOD_NAMES

        units = self.state.flags.get("v12_economy", {}).get("logistics_units", [])
        unit = next((item for item in units if int(item.get("id", 0)) == int(logistics_id)), None)
        if not unit:
            return
        path = [int(city_id) for city_id in unit.get("path", [])]
        path_index = max(0, min(int(unit.get("path_index", 0)), max(0, len(path) - 1)))
        route_parts = []
        for index, city_id in enumerate(path):
            name = self.state.city_name(city_id)
            route_parts.append(f"【{name}】" if index == path_index else name)
        regime = self.state.regimes.get(int(unit.get("regime_id", 0)), {})
        owner_name = regime.get("name", "民间商队")
        kind_name = "官漕" if unit.get("kind") == "official" else "商队"
        modifier_text = (
            "\n修正：AI官漕保障（免除路途自然损耗）"
            if unit.get("kind") == "official" and int(unit.get("regime_id", 0)) not in {0, self.state.player_regime_id}
            else ""
        )
        source = self.state.regions.get(int(unit.get("source_region_id", 0)), {}).get("name", "未知")
        target = self.state.regions.get(int(unit.get("target_region_id", 0)), {}).get("name", "未知")
        good = GOOD_NAMES.get(str(unit.get("good", "")), str(unit.get("good", "未知")))
        messagebox.showinfo(
            f"漕运#{logistics_id}",
            f"类型：{kind_name}\n所属：{owner_name}\n起点：{source}\n终点：{target}\n"
            f"货物：{good} {float(unit.get('amount', 0)):g} 单位\n"
            f"路线：{' → '.join(route_parts) or '无'}\n"
            f"本段进度：{float(unit.get('movement_progress', 0)):g}\n在途月数：{int(unit.get('age', 0))}{modifier_text}",
            parent=self,
        )

    def _show_supply_details(self, supply_id: int):
        from ..content.v1_2.supply_units import SUPPLY_UNIT_MAX_AGE, get_supply_unit

        try:
            unit = get_supply_unit(self.state, supply_id)
        except Exception:
            return
        regime = self.state.regimes.get(int(unit.get("regime_id", 0)), {})
        messagebox.showinfo(
            f"补给队#{supply_id}",
            f"所属：{regime.get('name', '未知')}\n"
            f"所在地：{self.state.city_name(int(unit.get('location_id', 0)))}\n"
            f"携带粮食：{float(unit.get('food', 0)):g}\n"
            f"服役时间：{int(unit.get('age', 0))}/{SUPPLY_UNIT_MAX_AGE}个月\n"
            f"行动力：{float(unit.get('action_points', 0)):g}/{float(unit.get('max_action_points', 1)):g}\n"
            "每月自耗现有粮食的10%；只能向道路相连一格内的己方军队补给。",
            parent=self,
        )
