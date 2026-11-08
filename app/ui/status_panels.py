from __future__ import annotations

import tkinter as tk
from collections import Counter
from tkinter import ttk

from ..constants import OFFICE_NAMES
from ..models import GameState
from ..rules.common import person_power
from ..rules.common import is_regime_eliminated
from ..rules.economy import calculate_region_income, expenses_due_this_month, projected_expenses, regime_income, regime_militia_growth
from ..rules.laws import family_land_power
from ..rules.political_events import party_power
from ..rules.military_modifiers import active_military_modifiers
from ..rules.national_modifiers import active_national_modifiers
from ..rules.ai_modifiers import ai_national_modifier_records
from ..rules.treasury import treasury_balance
from . import theme


def visible_family_members(state: GameState, family: dict) -> list[dict]:
    """Return born family members; deceased ancestors remain visible in the genealogy."""
    return [
        state.persons[person_id]
        for person_id in family.get("members", [])
        if person_id in state.persons
        and int(state.persons[person_id].get("birth_year", 0) or 0) <= int(state.year)
    ]


class StatusWindow(tk.Toplevel):
    def __init__(self, master, title: str, state: GameState, on_close=None):
        super().__init__(master)
        self.state = state
        self._on_close = on_close
        self.title(title)
        self.geometry("980x700")
        self.minsize(720, 520)
        self.configure(background=theme.BG)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        if self._on_close:
            self._on_close()
        self.destroy()


class CourtWindow(StatusWindow):
    def __init__(self, master, state: GameState, on_close=None):
        super().__init__(master, "朝堂", state, on_close)
        header = ttk.Frame(self, style="Panel.TFrame", padding=18)
        header.pack(fill="x", padx=18, pady=(18, 10))
        ttk.Label(header, text="晋廷百官", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text=f"主政：{state.person_name(state.player['id'])}　权威：{state.authority}", style="Panel.TLabel").pack(side="right")

        panes = ttk.Panedwindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        offices = ttk.Frame(panes, style="Panel.TFrame", padding=14)
        people = ttk.Frame(panes, style="Panel.TFrame", padding=14)
        panes.add(offices, weight=1)
        panes.add(people, weight=2)
        ttk.Label(offices, text="官职", style="Subheading.TLabel").pack(anchor="w", pady=(0, 8))
        tree = ttk.Treeview(offices, columns=("office", "person"), show="headings")
        tree.heading("office", text="官职")
        tree.heading("person", text="任职者")
        tree.column("office", width=130)
        tree.column("person", width=100)
        for key, label in OFFICE_NAMES.items():
            tree.insert("", "end", values=(label, state.person_name(state.player_regime.get("internal", {}).get(key))))
        tree.pack(fill="x")

        ttk.Label(offices, text="各州刺史", style="Subheading.TLabel").pack(anchor="w", pady=(14, 8))
        governor_tree = ttk.Treeview(offices, columns=("region", "governor"), show="headings", height=9)
        governor_tree.heading("region", text="州/地区")
        governor_tree.heading("governor", text="刺史")
        governor_tree.column("region", width=130, anchor="center")
        governor_tree.column("governor", width=100, anchor="center")
        owned_regions = set(state.player_regime.get("regions", []))
        for region in sorted(state.regions.values(), key=lambda item: int(item["id"])):
            if region.get("name") not in owned_regions:
                continue
            governor_tree.insert(
                "", "end",
                values=(region["name"], state.person_name(region.get("governor")) or "空缺"),
            )
        governor_tree.pack(fill="both", expand=True)

        ttk.Label(people, text="本国人物", style="Subheading.TLabel").pack(anchor="w", pady=(0, 8))
        p_tree = ttk.Treeview(people, columns=("name", "level", "int", "mil", "opinion", "power"), show="headings")
        for column, text, width in (("name", "姓名", 90), ("level", "级别", 55), ("int", "智力", 55), ("mil", "武力", 55), ("opinion", "好感", 55), ("power", "权力", 85)):
            p_tree.heading(column, text=text)
            p_tree.column(column, width=width, anchor="center")
        for person in state.persons.values():
            if person.get("country_id") != state.player_regime_id or person.get("status") not in {1, 2, 3}:
                continue
            attrs = person.get("attributes", {})
            p_tree.insert("", "end", values=(state.person_name(person["id"]), person.get("level", 0), attrs.get("intelligence", 0), attrs.get("military", 0), person.get("opinion_of_player", 0), int(person_power(state, person))))
        p_tree.pack(fill="both", expand=True)


class FamiliesWindow(StatusWindow):
    TYPE_NAMES = {0: "皇族", 1: "高门", 2: "寒门", 100: "特殊"}

    def __init__(self, master, state: GameState, on_close=None):
        super().__init__(master, "家族", state, on_close)
        ttk.Label(self, text="天下门第", style="Heading.TLabel").pack(anchor="w", padx=20, pady=(18, 10))
        frame = ttk.Frame(self, style="Panel.TFrame", padding=14)
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        tree = ttk.Treeview(frame, columns=("name", "type", "leader", "members", "opinion", "power"), show="headings")
        for column, text, width in (("name", "家族", 150), ("type", "门第", 80), ("leader", "家主", 90), ("members", "成员", 70), ("opinion", "对政府好感", 100), ("power", "总权力", 100)):
            tree.heading(column, text=text)
            tree.column(column, width=width, anchor="center")
        for family in state.families.values():
            members = visible_family_members(state, family)
            visible_ids = {int(person["id"]) for person in members}
            leader_id = int(family.get("leader") or 0)
            personal_power = sum(person_power(state, p) for p in members)
            power = int(personal_power if state.flags.get("content_version") == "1.2" else personal_power + family_land_power(state, int(family["id"])))
            leader_name = state.person_name(leader_id) if leader_id in visible_ids else "暂未出现"
            tree.insert("", "end", iid=str(family["id"]), values=(family.get("name", family["id"]), self.TYPE_NAMES.get(family.get("family_type"), "未知"), leader_name, len(members), family.get("government_opinion", 0), power))
        tree.pack(fill="both", expand=True)
        tree.bind("<Double-Button-1>", lambda _e: self._details(tree))
        note = "1.2不再记录家族专属地块；门阀土地按地区统一计算。双击可查看族谱。" if state.flags.get("content_version") == "1.2" else "双击家族查看成员与族谱关系"
        ttk.Label(frame, text=note, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

    def _details(self, tree):
        selected = tree.selection()
        if not selected:
            return
        family = self.state.families[int(selected[0])]
        win = tk.Toplevel(self)
        win.title(f"{family.get('name', '家族')} · 族谱")
        win.geometry("920x680")
        win.minsize(680, 520)
        win.configure(background=theme.BG)

        header = ttk.Frame(win, style="Panel.TFrame", padding=14)
        header.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(header, text=family.get("name", ""), style="Heading.TLabel").pack(side="left")
        info_var = tk.StringVar(value="点击节点查看人物详情")
        ttk.Label(header, textvariable=info_var, style="Panel.TLabel", wraplength=560, justify="right").pack(side="right")

        canvas_frame = ttk.Frame(win, style="Panel.TFrame")
        canvas_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        canvas = tk.Canvas(canvas_frame, background=theme.PANEL, highlightthickness=0)
        hbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=canvas.xview)
        vbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        members = visible_family_members(self.state, family)
        by_id = {person["id"]: person for person in members}
        children: dict[int, list[int]] = {pid: [] for pid in by_id}
        roots: list[int] = []
        for pid, person in by_id.items():
            father = person.get("father")
            if father in by_id:
                children[father].append(pid)
            else:
                roots.append(pid)
        if not roots:
            roots = list(by_id)

        positions: dict[int, tuple[float, int]] = {}
        next_x = [0]

        def assign(pid: int, depth: int) -> float:
            if pid in positions:
                return positions[pid][0]
            child_ids = children.get(pid, [])
            if not child_ids:
                x = float(next_x[0])
                next_x[0] += 1
            else:
                x = sum(assign(cid, depth + 1) for cid in child_ids) / len(child_ids)
            positions[pid] = (x, depth)
            return x

        for root in roots:
            assign(root, 0)

        x_spacing, y_spacing, margin = 118, 78, 60
        max_x = max((x for x, _ in positions.values()), default=0)
        max_depth = max((depth for _, depth in positions.values()), default=0)
        tree_width = max(700, int((max_x + 1) * x_spacing) + margin * 2)
        tree_height = max(500, (max_depth + 1) * y_spacing + margin * 2)

        for pid, child_ids in children.items():
            parent_x, parent_depth = positions[pid]
            x1 = margin + parent_x * x_spacing
            y1 = margin + parent_depth * y_spacing + 18
            for child_id in child_ids:
                child_x, child_depth = positions[child_id]
                x2 = margin + child_x * x_spacing
                y2 = margin + child_depth * y_spacing - 18
                canvas.create_line(x1, y1, x2, y2, fill=theme.MUTED, width=1)

        def select_person(pid: int):
            person = self.state.persons.get(pid)
            if not person:
                return
            father = self.state.person_name(person.get("father")) if person.get("father") in self.state.persons else "不详"
            mother = self.state.person_name(person.get("mother")) if person.get("mother") in self.state.persons else "不详"
            spouse = self.state.person_name(person.get("spouse")) if person.get("spouse") in self.state.persons else "无"
            status = {0: "未出生", 1: "正常", 2: "生病", 3: "脑疾", 4: "已故", 5: "隐退"}.get(person.get("status"), "未知")
            info_var.set(
                f"{self.state.person_name(pid)}　级别 {person.get('level', 0)}　"
                f"父：{father}　母：{mother}　配偶：{spouse}　状态：{status}"
            )

        for pid, (node_x, depth) in positions.items():
            x = margin + node_x * x_spacing
            y = margin + depth * y_spacing
            tags = (f"node_{pid}",)
            canvas.create_rectangle(x - 48, y - 18, x + 48, y + 18, fill=theme.PANEL, outline=theme.ACCENT, width=1, tags=tags)
            canvas.create_text(x, y, text=self.state.person_name(pid), fill=theme.INK, font=("Microsoft YaHei UI", 10), tags=tags)
            if by_id[pid].get("status") == 4:
                canvas.create_text(x + 36, y - 12, text="✕", fill="#c0392b", font=("Microsoft YaHei UI", 9, "bold"), tags=tags)
            canvas.tag_bind(f"node_{pid}", "<Button-1>", lambda _event, pid=pid: select_person(pid))

        canvas.configure(scrollregion=(0, 0, tree_width, tree_height))
        if roots:
            select_person(roots[0])


class EconomyWindow(StatusWindow):
    def __init__(self, master, state: GameState, on_close=None):
        super().__init__(master, "经济", state, on_close)
        regime = state.player_regime
        income = regime_income(state, state.player_regime_id)
        militia_growth = regime_militia_growth(state, state.player_regime_id)
        official, military = projected_expenses(state, state.player_regime_id)
        official_due, military_due = expenses_due_this_month(state, state.player_regime_id)
        header = ttk.Frame(self, style="Panel.TFrame", padding=18)
        header.pack(fill="x", padx=18, pady=18)
        ttk.Label(header, text="国计簿", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text=f"国库 {treasury_balance(state):g}　预计本月结算 {income - official_due - military_due:+g}", style="Panel.TLabel").pack(side="right")
        summary = ttk.Frame(self, style="Panel.TFrame", padding=18)
        summary.pack(fill="x", padx=18, pady=(0, 12))
        for i, (label, value) in enumerate((("土地收入", income), ("正月/七月官俸", -official), ("军队军饷", -military), ("壮丁", regime["militia"]), ("预计壮丁增长", f"+{militia_growth}"), ("预备役", regime["reserve_army"]))):
            card = ttk.Frame(summary, style="Panel.TFrame", padding=10)
            card.grid(row=0, column=i, sticky="nsew", padx=5)
            summary.columnconfigure(i, weight=1)
            ttk.Label(card, text=label, style="Muted.TLabel").pack()
            ttk.Label(card, text=str(value), style="Subheading.TLabel").pack(pady=(4, 0))
        table = ttk.Treeview(self, columns=("region", "land", "development", "prosperity", "income", "owners"), show="headings")
        for col, text, width in (("region", "地区", 120), ("land", "土地", 75), ("development", "发展度", 75), ("prosperity", "繁荣度", 75), ("income", "收入", 75), ("owners", "土地构成", 300)):
            table.heading(col, text=text)
            table.column(col, width=width, anchor="center")
        owned = set(regime.get("regions", []))
        for region in state.regions.values():
            if region.get("name") not in owned:
                continue
            counts = Counter(region.get("land_ownership", []))
            owners = f"自耕农 {counts[0]} / 小地主 {counts[1]} / 中央 {counts[2]} / 家族 {sum(v for k, v in counts.items() if k >= 3)}"
            table.insert("", "end", values=(region["name"], region["land"], region["development"], region["prosperity"], calculate_region_income(region, state, state.player_regime_id), owners))
        table.pack(fill="both", expand=True, padx=18, pady=(0, 18))


class V12EconomyWindow(StatusWindow):
    def __init__(self, master, state: GameState, on_close=None):
        from ..content.v1_2.economy import format_resource, governor_kind, manpower_balance, manpower_capacity, market_price, population_counts, population_units, region_economy, warehouse_capacity, warehouse_resource_capacity

        super().__init__(master, "经济 · 1.2", state, on_close)
        owned_regions = [
            region for region in state.regions.values()
            if int(region.get("controller", 0)) == state.player_regime_id
        ]
        total_population = sum(len(population_units(state, int(region["id"]))) for region in owned_regions)
        header = ttk.Frame(self, style="Panel.TFrame", padding=18)
        header.pack(fill="x", padx=18, pady=18)
        ttk.Label(header, text="元嘉国计簿", style="Heading.TLabel").pack(side="left")
        ttk.Label(
            header,
            text=(
                f"国库（首都州库铜钱）{format_resource(treasury_balance(state))}　"
                f"人力 {manpower_balance(state, state.player_regime_id)}/{manpower_capacity(state, state.player_regime_id)}　"
                f"人口 {total_population} 万人单位　地区 {len(owned_regions)}"
            ),
            style="Panel.TLabel",
        ).pack(side="right")
        ttk.Label(
            self,
            text="七月生产、十二月人口消费；州库只存粮食和布匹，铜钱统一计入国家国库。地方收入与支出受控制度折算。",
            style="Muted.TLabel",
        ).pack(anchor="w", padx=20, pady=(0, 10))
        frame = ttk.Frame(self, style="Panel.TFrame", padding=12)
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        tree = ttk.Treeview(
            frame,
            columns=("region", "governor", "kind", "stability", "control", "population", "occupations", "land", "food", "food_price", "cloth", "cloth_price", "garrison", "weather"),
            show="headings",
        )
        for column, label, width in (
            ("region", "地区", 90), ("governor", "刺史", 90), ("kind", "出身", 55),
            ("stability", "稳定", 55), ("control", "控制", 55), ("population", "人口单位", 70),
            ("occupations", "农/工/地/流", 115), ("land", "门阀/小地主/自耕", 125),
            ("food", "府库/上限/市场粮", 120), ("food_price", "粮价", 50),
            ("cloth", "府库/市场布", 95), ("cloth_price", "布价", 50),
            ("garrison", "驻军支数", 65), ("weather", "年景", 60),
        ):
            tree.heading(column, text=label)
            tree.column(column, width=width, anchor="center")
        for region in owned_regions:
            region_id = int(region["id"])
            record = region_economy(state, region_id)
            occupations, _cultures = population_counts(state, region_id)
            land = record["land"]
            kinds = {"none": "空缺", "humble": "寒门", "high": "高门", "royal": "宗室"}
            garrison = sum(
                1 for army in state.armies.values()
                if army.soldiers > 0 and army.regime_id == int(region.get("controller", 0))
                and int(state.cities.get(army.location_id, {}).get("region_id", 0)) == region_id
            )
            tree.insert("", "end", values=(
                region["name"], state.person_name(region.get("governor")), kinds[governor_kind(state, region_id)],
                record["stability"], record["control"], len(population_units(state, region_id)),
                f"{occupations['farmer']}/{occupations['artisan']}/{occupations['landlord']}/{occupations['refugee']}",
                f"{land['gentry']}/{land['smallholder']}/{land['self_farm']}",
                f"{format_resource(record['warehouse']['food'])}/{format_resource(warehouse_resource_capacity(state, region_id, 'food'))}/{format_resource(record['market']['food'])}", format_resource(market_price(state, region_id, "food")),
                f"{format_resource(record['warehouse']['cloth'])}/{format_resource(record['market']['cloth'])}", format_resource(market_price(state, region_id, "cloth")),
                garrison, record.get("last_weather", "未结算"),
            ))
        vbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        logistics = state.flags.get("v12_economy", {}).get("logistics_units", [])
        ttk.Label(frame, text=f"在途漕运与商队：{len(logistics)} 支。驻军每支在月结时提供5点控制度。", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))


class MilitaryStatusWindow(StatusWindow):
    UNIT_NAMES = {1: "步兵", 2: "骑兵", 3: "弓兵", 4: "战船", 5: "快船", 6: "楼船"}

    def __init__(self, master, state: GameState, on_close=None):
        super().__init__(master, "军事状态", state, on_close)
        armies = [a for a in state.armies.values() if a.regime_id == state.player_regime_id]
        supply_columns = []
        if str(state.flags.get("content_version", "1.1")) == "1.2":
            from ..content.v1_2.supply_units import supply_units
            from ..content.v1_2.economy import manpower_balance, manpower_capacity

            supply_columns = supply_units(state, state.player_regime_id)
        header = ttk.Frame(self, style="Panel.TFrame", padding=18)
        header.pack(fill="x", padx=18, pady=18)
        ttk.Label(header, text="我军军势", style="Heading.TLabel").pack(side="left")
        reserve_text = (
            f"　人力 {manpower_balance(state, state.player_regime_id)}/{manpower_capacity(state, state.player_regime_id)}"
            if str(state.flags.get("content_version", "1.1")) == "1.2"
            else f"　预备役 {state.player_regime['reserve_army']}"
        )
        ttk.Label(
            header,
            text=f"军队 {len(armies)} 支　总兵力 {sum(a.soldiers for a in armies)}　补给队 {len(supply_columns)} 支{reserve_text}",
            style="Panel.TLabel",
        ).pack(side="right")
        frame = ttk.Frame(self, style="Panel.TFrame", padding=14)
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        tree = ttk.Treeview(frame, columns=("id", "type", "commander", "location", "soldiers", "formation", "supply", "modifier", "morale", "experience", "ap"), show="headings")
        for col, text, width in (
            ("id", "军队", 60), ("type", "兵种", 60), ("commander", "将领", 90),
            ("location", "所在地", 100), ("soldiers", "总兵力", 80), ("formation", "编制", 250),
            ("supply", "随军补给", 110),
            ("modifier", "军队修正", 130),
            ("morale", "士气", 55), ("experience", "经验", 55), ("ap", "行动力", 65),
        ):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="center")
        for army in armies:
            counts = Counter()
            for unit in army.units:
                counts[self.UNIT_NAMES.get(unit.get("type"), "未知")] += unit.get("count", 0)
            formation = " / ".join(f"{name}{count}" for name, count in counts.items())
            modifiers = "、".join(item.get("name", "未命名") for item in active_military_modifiers(state, army)) or "无"
            if str(state.flags.get("content_version", "1.1")) == "1.2":
                from ..content.v1_2.economy import army_supply_months

                supply = f"{army.supply_food:g}粮 / {army_supply_months(army):g}战时月"
            else:
                supply = "—"
            tree.insert("", "end", values=(f"#{army.id}", "水军" if army.army_type else "陆军", state.person_name(army.commander), state.city_name(army.location_id), army.soldiers, formation, supply, modifiers, army.morale, army.experience, f"{army.action_points:g}/{army.max_action_points:g}"))
        tree.pack(fill="both", expand=True)
        if supply_columns:
            ttk.Label(frame, text="补给队", style="Subheading.TLabel").pack(anchor="w", pady=(10, 4))
            supply_tree = ttk.Treeview(frame, columns=("id", "food", "location", "age", "ap"), show="headings", height=4)
            for col, text, width in (
                ("id", "补给队", 80), ("food", "携粮", 100), ("location", "所在地", 120),
                ("age", "服役时间", 100), ("ap", "行动力", 90),
            ):
                supply_tree.heading(col, text=text)
                supply_tree.column(col, width=width, anchor="center")
            for unit in supply_columns:
                supply_tree.insert("", "end", values=(
                    f"#{unit['id']}", f"{float(unit.get('food', 0)):g}",
                    state.city_name(int(unit.get("location_id", 0))), f"{int(unit.get('age', 0))}/12月",
                    f"{float(unit.get('action_points', 0)):g}/{float(unit.get('max_action_points', 1)):g}",
                ))
            supply_tree.pack(fill="x")
        ttk.Label(frame, text="此窗口用于跨阶段查看；调兵、任命和组建仍在军事阶段执行。", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))


class ModifiersWindow(StatusWindow):
    def __init__(self, master, state: GameState, on_close=None):
        super().__init__(master, "修正状态", state, on_close)
        ttk.Label(self, text="国家与军队修正", style="Heading.TLabel").pack(anchor="w", padx=20, pady=(18, 10))
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        national_frame = ttk.Frame(panes, style="Panel.TFrame", padding=12)
        army_frame = ttk.Frame(panes, style="Panel.TFrame", padding=12)
        panes.add(national_frame, weight=1)
        panes.add(army_frame, weight=2)
        ttk.Label(national_frame, text="国家修正", style="Subheading.TLabel").pack(anchor="w", pady=(0, 6))
        national = ttk.Treeview(national_frame, columns=("id", "name", "effect"), show="headings", height=5)
        for col, label, width in (("id", "编号", 60), ("name", "名称", 180), ("effect", "具体效果", 600)):
            national.heading(col, text=label)
            national.column(col, width=width, anchor="center" if col == "id" else "w")
        for modifier in active_national_modifiers(state) + ai_national_modifier_records(state):
            national.insert("", "end", values=(modifier.get("id"), modifier.get("name"), modifier.get("description")))
        national.pack(fill="both", expand=True)

        ttk.Label(army_frame, text="军队修正", style="Subheading.TLabel").pack(anchor="w", pady=(0, 6))
        armies = ttk.Treeview(army_frame, columns=("army", "country", "commander", "name", "effect"), show="headings")
        for col, label, width in (("army", "军队", 70), ("country", "所属", 90), ("commander", "将领", 100), ("name", "修正", 180), ("effect", "具体效果", 430)):
            armies.heading(col, text=label)
            armies.column(col, width=width, anchor="center" if col != "effect" else "w")
        for army in state.armies.values():
            for modifier in active_military_modifiers(state, army):
                armies.insert("", "end", values=(f"#{army.id}", state.regimes.get(army.regime_id, {}).get("name", "未知"), state.person_name(army.commander), modifier.get("name"), modifier.get("description")))
        armies.pack(fill="both", expand=True)


class DiplomacyStatusWindow(StatusWindow):
    def __init__(self, master, state: GameState, on_close=None):
        super().__init__(master, "外交状态", state, on_close)
        header = ttk.Frame(self, style="Panel.TFrame", padding=18)
        header.pack(fill="x", padx=18, pady=18)
        ttk.Label(header, text="天下邦交", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text=f"本国：{state.player_regime['name']}　战争支持 {state.player_regime['war_support']}", style="Panel.TLabel").pack(side="right")
        frame = ttk.Frame(self, style="Panel.TFrame", padding=14)
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        tree = ttk.Treeview(frame, columns=("name", "relation", "opinion", "capital", "owned", "controlled", "stability", "support", "treasury"), show="headings")
        for col, text, width in (
            ("name", "政权", 80), ("relation", "与我方关系", 90), ("opinion", "好感", 55),
            ("capital", "首都", 80), ("owned", "所有地区", 70), ("controlled", "控制地区", 70),
            ("stability", "稳定", 55), ("support", "战争支持", 75), ("treasury", "国库", 75),
        ):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="center")
        for regime_id, regime in state.regimes.items():
            if regime_id != state.player_regime_id and is_regime_eliminated(state, regime_id):
                continue
            if regime_id == state.player_regime_id:
                relation = "本国"
                opinion = 100
            elif state.at_war(state.player_regime_id, regime_id):
                relation = "交战"
                opinion = regime.get("opinion_of_main", 0)
            elif regime_id in state.vassals:
                relation = "我方臣属" if state.vassals[regime_id] == state.player_regime_id else "臣属"
                opinion = regime.get("opinion_of_main", 0)
            else:
                relation = regime.get("relation_with_main", "正常")
                opinion = regime.get("opinion_of_main", 0)
            controlled = sum(1 for region in state.regions.values() if int(region.get("controller", 0)) == regime_id)
            tree.insert("", "end", values=(regime["name"], relation, opinion, state.city_name(regime.get("capital", 0)), len(regime.get("regions", [])), controlled, regime.get("stability", 0), regime.get("war_support", 0), f"{treasury_balance(state, regime_id):g}"))
        tree.pack(fill="both", expand=True)
        ttk.Label(frame, text="“所有地区”代表法理归属，“控制地区”代表当前实际占领；和平协议可改变法理归属。", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))


class PartiesWindow(StatusWindow):
    def __init__(self, master, state: GameState, on_close=None):
        super().__init__(master, "政党", state, on_close)
        header = ttk.Frame(self, style="Panel.TFrame", padding=18)
        header.pack(fill="x", padx=18, pady=18)
        ttk.Label(header, text="朝堂四党", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, text="政党会在谋划阶段后拉拢成员、联络家族并判定政变。", style="Muted.TLabel").pack(side="right")
        frame = ttk.Frame(self, style="Panel.TFrame", padding=14)
        frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        tree = ttk.Treeview(frame, columns=("name", "leader", "members", "families", "power", "coup"), show="headings")
        for col, text, width in (("name", "政党", 90), ("leader", "党魁", 110), ("members", "成员数", 70), ("families", "站队家族", 90), ("power", "政党权力", 100), ("coup", "政变状态", 150)):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="center")
        for party in state.parties.values():
            leader = state.person_name(party.get("leader"))
            members = party.get("members", [])
            family_count = len(party.get("supported_families", []))
            coup = party.get("coup")
            if coup and coup.get("exposed"):
                coup_text = f"已暴露 {float(coup.get('progress', 0)):.1f}%"
            elif coup:
                coup_text = "未发现异常"
            else:
                coup_text = "无"
            tree.insert("", "end", values=(party.get("name", party.get("id")), leader, len(members), family_count, int(party_power(state, party)), coup_text))
        tree.pack(fill="both", expand=True)
        ttk.Label(frame, text="家族按族长与党魁意识形态站队；未暴露的政变不会向玩家显示真实进度。", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
