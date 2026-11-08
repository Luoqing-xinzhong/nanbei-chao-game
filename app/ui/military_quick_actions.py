from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from ..constants import ROAD_NAMES
from ..models import GameState
from ..rules import military
from ..rules.common import RuleError
from . import theme
from .dialogs import choose_item


def player_armies_at_city(state: GameState, city_id: int):
    return [
        army for army in state.armies.values()
        if army.regime_id == state.player_regime_id and army.location_id == city_id
    ]


class MilitaryQuickActions(tk.Toplevel):
    """Small map-launched command window for armies in one city."""

    def __init__(
        self,
        master,
        state: GameState,
        city_id: int,
        on_changed: Callable[[], None],
        on_close: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        self.state = state
        self.city_id = city_id
        self.on_changed = on_changed
        self.on_close = on_close
        self.title(f"军事快捷操作 · {state.city_name(city_id)}")
        self.geometry("720x340")
        self.minsize(620, 300)
        self.transient(master.winfo_toplevel())
        self.configure(background=theme.PANEL)
        self.protocol("WM_DELETE_WINDOW", self.close)

        header = ttk.Frame(self, style="Panel.TFrame", padding=14)
        header.pack(fill="x")
        ttk.Label(header, text=f"{state.city_name(city_id)}驻军", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text="军事阶段地图快捷操作", style="Muted.TLabel").pack(side="right")

        body = ttk.Frame(self, style="Panel.TFrame", padding=(14, 4, 14, 14))
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            body,
            columns=("id", "commander", "soldiers", "morale", "ap"),
            show="headings",
            height=6,
            selectmode="browse",
        )
        for column, label, width in (
            ("id", "军队", 70),
            ("commander", "将领", 120),
            ("soldiers", "兵力", 100),
            ("morale", "士气", 80),
            ("ap", "行动力", 100),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, anchor="center")
        self.tree.pack(fill="both", expand=True)

        controls = ttk.Frame(body, style="Panel.TFrame")
        controls.pack(fill="x", pady=(12, 0))
        self.action_buttons = []
        for label, command in (
            ("行军", self._march),
            ("一键行军", self._quick_march),
            ("进攻", self._attack),
            ("犒劳", self._reward),
            ("更换将领", self._commander),
        ):
            button = ttk.Button(controls, text=label, command=command)
            button.pack(side="left", padx=4)
            self.action_buttons.append(button)
        ttk.Button(controls, text="关闭", command=self.close).pack(side="right", padx=4)
        self.refresh()

    def close(self):
        if self.on_close:
            self.on_close()
        self.destroy()

    def refresh(self):
        selected = self.tree.selection()
        for item in self.tree.get_children():
            self.tree.delete(item)
        armies = player_armies_at_city(self.state, self.city_id)
        for army in armies:
            self.tree.insert(
                "",
                "end",
                iid=str(army.id),
                values=(
                    f"#{army.id}",
                    self.state.person_name(army.commander),
                    army.soldiers,
                    army.morale,
                    f"{army.action_points:g}/{army.max_action_points:g}",
                ),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        elif armies:
            self.tree.selection_set(str(armies[0].id))
        state = "normal" if armies else "disabled"
        for button in self.action_buttons:
            button.configure(state=state)

    def _selected(self) -> int | None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("请选择", "先选择一支军队。", parent=self)
            return None
        return int(selected[0])

    def _run(self, callback, show_result: bool = False):
        try:
            result = callback()
        except (RuleError, ValueError, KeyError) as exc:
            messagebox.showwarning("无法执行", str(exc), parent=self)
            return
        if result and show_result:
            messagebox.showinfo("作战结果", str(result), parent=self)
        self.on_changed()
        if not player_armies_at_city(self.state, self.city_id):
            self.close()
            return
        self.refresh()

    def _march(self):
        army_id = self._selected()
        if army_id is None:
            return
        options = [
            (f"{self.state.city_name(city)}　经{ROAD_NAMES.get(road_type)}　消耗{cost:g}", city)
            for city, road_type, cost in military.legal_moves(self.state, army_id)
        ]
        if not options:
            messagebox.showwarning("无法行军", "这支军队当前没有可行军的相邻城市。", parent=self)
            return
        target = choose_item(self, "行军", "选择合法目标", options)
        if target is not None:
            self._run(lambda: military.march(self.state, army_id, target))

    def _quick_march(self):
        army_id = self._selected()
        if army_id is None:
            return
        routes = military.legal_march_routes(self.state, army_id)
        if not routes:
            messagebox.showwarning("无法连续行军", "当前行动力内没有可直达的两步或三步目的地。", parent=self)
            return
        options = [
            (
                f"{len(path)}步　{' → '.join(self.state.city_name(city_id) for city_id in path)}　总消耗{cost:g}",
                path,
            )
            for path, cost in routes
        ]
        route = choose_item(self, "一键行军", "选择两步或三步可直达的最远目的地", options)
        if route is not None:
            self._run(lambda: military.march_route(self.state, army_id, route))

    def _attack(self):
        army_id = self._selected()
        if army_id is None:
            return
        options = [
            (f"{self.state.city_name(city)}　经{ROAD_NAMES.get(road_type)}", city)
            for city, road_type in military.legal_attacks(self.state, army_id)
        ]
        if not options:
            messagebox.showwarning("无法进攻", "这支军队附近没有可以进攻的敌军。", parent=self)
            return
        target = choose_item(self, "进攻", "选择敌军驻守的相邻城市", options)
        if target is None:
            return
        if messagebox.askyesno("确认进攻", f"向{self.state.city_name(target)}发起进攻？这会耗尽行动力。", parent=self):
            self._run(lambda: military.attack(self.state, army_id, target), show_result=True)

    def _reward(self):
        army_id = self._selected()
        if army_id is not None:
            self._run(lambda: military.reward(self.state, army_id))

    def _commander(self):
        army_id = self._selected()
        if army_id is None:
            return
        assigned = {army.commander for army in self.state.armies.values() if army.commander}
        options = [("卸任当前将领", (True, None))]
        options.extend(
            (
                f"{self.state.person_name(person['id'])}　武力{person['attributes']['military']}",
                (True, person["id"]),
            )
            for person in self.state.persons.values()
            if person.get("country_id") == self.state.player_regime_id
            and person.get("status") == 1
            and person["id"] not in assigned
        )
        selection = choose_item(self, "任命将领", "选择新将领", options)
        if selection is not None:
            self._run(lambda: military.assign_commander(self.state, army_id, selection[1]))
