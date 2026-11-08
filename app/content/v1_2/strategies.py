from __future__ import annotations

from typing import Any

from ...models import GameState
from ...rules.common import RuleError, clamp
from .economy import population_units, region_economy, warehouse_capacity


def _record(strategy_id: int, name: str, prerequisites=(), duration=1, effect="", prerequisites_any=()) -> dict[str, Any]:
    return {
        "id": strategy_id,
        "name": name,
        "prerequisites": list(prerequisites),
        "prerequisites_any": list(prerequisites_any),
        "mutually_exclusive": [],
        "duration_months": duration,
        "effect_description": effect,
    }


STRATEGY_TEMPLATES = {
    1: _record(1, "奉承遗命", duration=2, effect="稳定度+5，刘义符基础权力+5。"),
    2: _record(2, "宫禁自持", (1,), 2, "建康所在州控制度+10，刘义符基础权力+10。"),
    3: _record(3, "倚重顾命", (1,), 2, "顾命大臣好感度+10，稳定度+8。"),
    4: _record(4, "抚军安民", (1,), 3, "各州稳定度+2，严重缺粮州补入10粮。"),
    5: _record(5, "景平亲政", (2,), 3, "刘义符基础权力+15，并激化顾命集团矛盾。"),
    6: _record(6, "劝课农桑", (4,), 4, "高稳定州流民转农效率+20%，下一次丰年产量+5%。"),
    7: _record(7, "整顿州库", (4,), 3, "所有主控州州库容量+20%，降低官漕劫掠风险。"),
    8: _record(8, "元嘉更始", duration=3, effect="稳定度+5，刘义隆基础权力+15，解除主少国疑。"),
    9: _record(9, "亲政班底", (8,), 3, "任用王昙首、殷景仁和王华，获得元嘉近臣修正。"),
    10: _record(10, "清算顾命", (8,), 3, "解锁处置徐羡之、傅亮及谢晦叛乱线。"),
    11: _record(11, "安置流民", (6,), 3, "高稳定州10%流民转为农民，稳定度+2。"),
    12: _record(12, "清查隐户", (6, 8), 3, "各州控制度+5，三个门阀土地最多州转移5%土地。"),
    13: _record(13, "疏浚漕路", (7,), 3, "官漕移动力+1并优先水路，冬季自动改走陆路。"),
    14: _record(14, "平粜常平", (7,), 3, "粮价上限降低20%，允许州库自动平粜。"),
    15: _record(15, "州郡更张", (8,), 3, "解锁重置荆州刺史及地方治理经略。"),
    16: _record(16, "察举能吏", (9,), 4, "寒门刺史控制效果提升，地方命令效率+5%。"),
    17: _record(17, "更定赋役", (12,), 4, "粮税-2个百分点、布税+2个百分点，稳定州稳定度+2。"),
    18: _record(18, "约束刺史", (15,), 3, "限制非宗室刺史权力增长并减缓无刺史兼并。"),
    19: _record(19, "宗室出镇", (15,), 3, "强化宗室刺史控制效果，但提高其个人权力。"),
    20: _record(20, "元嘉文治", duration=5, effect="获得元嘉新政国家修正。", prerequisites_any=(17, 18)),
    21: _record(21, "江淮备边", (20,), 3, "徐州、淮北、中原稳定度+3，彭城、滑台、洛阳城防+10。"),
    22: _record(22, "整顿江淮", (18,), 3, "徐州、淮北控制度+10并安置5%流民。"),
    23: _record(23, "南北商路", (20, 13), 3, "商人上限提高至7，降低商路生成价差门槛。"),
    24: _record(24, "北伐之议", (21,), 3, "解锁第一次元嘉北伐。"),
    25: _record(25, "河南经营", (24,), 3, "中原控制度+20，洛阳城防+10。"),
    26: _record(26, "固守滑台", (25,), 2, "滑台城防+20，中原州库粮食+20，驻军耗粮-10%。"),
    27: _record(27, "乘虚北进", (25,), 2, "宋军在中原进攻+15%，持续12个月。"),
    28: _record(28, "收兵息民", duration=3, effect="战争支持度-10，北方三州稳定度+5。"),
    29: _record(29, "江淮重建", (28,), 4, "徐州、淮北稳定度与控制度+10，15%流民转农。"),
    30: _record(30, "军粮整饬", (28, 13), 4, "战争军粮消耗-15%，官漕运粮速度+20%。"),
    31: _record(31, "元嘉十年", (20,), 1, "触发元嘉十年评议。", prerequisites_any=(29, 30)),
}


def _person(state: GameState, name: str) -> dict | None:
    return next((p for p in state.persons.values() if state.person_name(int(p["id"])) == name), None)


def _available_person(state: GameState, name: str) -> dict | None:
    person = _person(state, name)
    if not person or int(person.get("status", 0)) == 4 or int(person.get("birth_year", 0) or 0) > state.year:
        return None
    return person


def _region(state: GameState, name: str) -> dict | None:
    return next((r for r in state.regions.values() if r.get("name") == name), None)


def _city(state: GameState, name: str) -> dict | None:
    return next((c for c in state.cities.values() if c.get("name") == name), None)


def _change_person(state: GameState, name: str, *, power=0, opinion=0) -> None:
    person = _available_person(state, name)
    if not person:
        return
    attrs = person.setdefault("attributes", {})
    attrs["base_power"] = max(0, int(attrs.get("base_power", 0)) + power)
    person["opinion_of_player"] = int(clamp(int(person.get("opinion_of_player", 30)) + opinion, -100, 100))


def _controlled_regions(state: GameState) -> list[dict]:
    return [r for r in state.regions.values() if int(r.get("controller", 0)) == state.player_regime_id]


def ensure_strategy_records(state: GameState) -> None:
    for strategy_id, template in STRATEGY_TEMPLATES.items():
        old = state.strategies.get(strategy_id, {})
        state.strategies[strategy_id] = {
            **template,
            "status": old.get("status", "available"),
            "progress_months": int(old.get("progress_months", 0)),
            "started_turn": old.get("started_turn"),
            **({"pause_reason": old["pause_reason"]} if old.get("pause_reason") else {}),
        }


def strategy_completed(state: GameState, strategy_id: int) -> bool:
    ensure_strategy_records(state)
    return state.strategies[strategy_id].get("status") == "completed"


def active_strategy(state: GameState) -> dict | None:
    ensure_strategy_records(state)
    sync_strategy_statuses(state)
    return next((s for s in state.strategies.values() if s.get("status") in {"in_progress", "paused"}), None)


def strategy_requirements_met(state: GameState, strategy_id: int) -> tuple[bool, str]:
    ensure_strategy_records(state)
    item = state.strategies[strategy_id]
    if any(not strategy_completed(state, req) for req in item["prerequisites"]):
        return False, "前置经略尚未完成"
    alternatives = item.get("prerequisites_any", [])
    if alternatives and not any(strategy_completed(state, req) for req in alternatives):
        return False, "需要完成任一前置经略"
    if strategy_id == 1 and 1 not in {int(item) for item in state.flags.get("v12_story_events", [])}:
        return False, "需要事件“武帝崩”已经发生"
    if strategy_id == 5 and not _available_person(state, "刘义符"):
        return False, "刘义符必须存活"
    if strategy_id == 8:
        if not state.flags.get("v12_yidu_enthroned") or not _available_person(state, "刘义隆"):
            return False, "需要事件“宜都王入京”发生且刘义隆为帝"
    if strategy_id == 20:
        values = [int(region_economy(state, int(r["id"]))["stability"]) for r in _controlled_regions(state)]
        if not values or sum(values) / len(values) < 60:
            return False, "平均地区稳定度需要达到60"
    if strategy_id == 24:
        if int(state.player_regime.get("stability", 0)) < 60 or int(state.player_regime.get("war_support", 0)) < 50:
            return False, "需要稳定度60、战争支持度50"
        if state.at_war(1, 2):
            return False, "宋与魏必须处于和平"
    if strategy_id == 25 and int(_region(state, "中原地区").get("controller", 0) if _region(state, "中原地区") else 0) != 1:
        return False, "需要控制洛阳和中原"
    if strategy_id == 27 and int(state.player_regime.get("war_support", 0)) < 65:
        return False, "战争支持度需要达到65"
    if strategy_id == 28 and not ({18, 19} & set(state.flags.get("v12_story_events", []))):
        return False, "需要北伐受挫或河南守成事件发生"
    if strategy_id == 31 and state.year < 433:
        return False, "需要到公元433年"
    return True, "前置条件满足"


def sync_strategy_statuses(state: GameState) -> None:
    ensure_strategy_records(state)
    for strategy_id, item in state.strategies.items():
        if item.get("status") not in {"in_progress", "paused"}:
            continue
        met, reason = strategy_requirements_met(state, strategy_id)
        if not met:
            item["status"] = "paused"
            item["pause_reason"] = reason
        elif item.get("status") == "paused":
            item["status"] = "in_progress"
            item.pop("pause_reason", None)


def strategy_available(state: GameState, strategy_id: int) -> tuple[bool, str]:
    ensure_strategy_records(state)
    sync_strategy_statuses(state)
    item = state.strategies[strategy_id]
    if item.get("status") == "completed":
        return False, "已经完成"
    if item.get("status") in {"in_progress", "paused"}:
        return False, "正在推进" if item["status"] == "in_progress" else f"已暂停：{item.get('pause_reason', '')}"
    if active_strategy(state):
        return False, "同时只能推进一项经略"
    ok, reason = strategy_requirements_met(state, strategy_id)
    return ok, "可以开始" if ok else reason


def start_strategy(state: GameState, strategy_id: int) -> str:
    if state.phase_index != 0:
        raise RuleError("只能在政治阶段开始经略")
    ok, reason = strategy_available(state, strategy_id)
    if not ok:
        raise RuleError(reason)
    item = state.strategies[strategy_id]
    item.update(status="in_progress", progress_months=0, started_turn=state.turn_number)
    message = f"开始经略“{item['name']}”，预计{item['duration_months']}个月完成。"
    state.add_log(message)
    return message


def cancel_strategy(state: GameState, strategy_id: int) -> str:
    item = state.strategies.get(strategy_id, {})
    if item.get("status") not in {"in_progress", "paused"}:
        raise RuleError("该经略当前没有执行")
    item.update(status="available", progress_months=0, started_turn=None)
    item.pop("pause_reason", None)
    return f"已取消经略“{item['name']}”，进度归零。"


def strategy_genealogy(state: GameState):
    ensure_strategy_records(state)
    nodes = []
    edges = []
    for strategy_id, item in sorted(state.strategies.items()):
        ok, reason = strategy_available(state, strategy_id)
        nodes.append({"id": strategy_id, "name": item["name"], "status": item["status"], "executable": ok, "reason": reason})
        edges.extend((req, strategy_id) for req in item["prerequisites"] + item.get("prerequisites_any", []))
    return nodes, edges


def strategy_mutual_exclusions(state: GameState):
    return []


def _convert_refugees(state: GameState, region_id: int, ratio: float) -> int:
    refugees = [u for u in population_units(state, region_id) if u.get("occupation") == "refugee"]
    count = min(len(refugees), int(len(refugees) * ratio + 0.5))
    for unit in refugees[:count]:
        unit["occupation"] = "farmer"
    return count


def _apply_effect(state: GameState, strategy_id: int) -> None:
    regime = state.player_regime
    if strategy_id == 1:
        regime["stability"] = int(clamp(int(regime.get("stability", 0)) + 5, 0, 100)); _change_person(state, "刘义符", power=5)
    elif strategy_id == 2:
        region = _region(state, "扬州"); region_economy(state, int(region["id"]))["control"] = min(100, int(region_economy(state, int(region["id"]))["control"]) + 10); _change_person(state, "刘义符", power=10)
    elif strategy_id == 3:
        for name in ("徐羡之", "傅亮", "谢晦", "檀道济"): _change_person(state, name, opinion=10)
        regime["stability"] = int(clamp(int(regime.get("stability", 0)) + 8, 0, 100))
    elif strategy_id == 4:
        for region in _controlled_regions(state):
            record = region_economy(state, int(region["id"])); record["stability"] = min(100, int(record["stability"]) + 2)
            if float(record["warehouse"].get("food", 0)) < len(population_units(state, int(region["id"]))) * 0.5:
                record["warehouse"]["food"] = min(warehouse_capacity(state, int(region["id"])), float(record["warehouse"].get("food", 0)) + 10)
    elif strategy_id == 5:
        _change_person(state, "刘义符", power=15); _change_person(state, "徐羡之", opinion=-15); _change_person(state, "谢晦", opinion=-10); state.flags["v12_coup_progress"] = int(state.flags.get("v12_coup_progress", 0)) + 10
    elif strategy_id in {6, 7, 13, 14, 16, 18, 19, 23, 26, 27, 30}:
        state.flags[f"v12_strategy_effect:{strategy_id}"] = True
        if strategy_id == 6:
            state.flags["v12_farming_bonus_pending"] = True
            state.flags["v12_farming_conversion_until"] = state.turn_number + 36
        elif strategy_id == 7:
            for region in _controlled_regions(state):
                record = region_economy(state, int(region["id"])); record["warehouse_capacity"] = round(warehouse_capacity(state, int(region["id"])) * 1.2, 2)
        elif strategy_id == 14:
            regime["stability"] = min(100, int(regime.get("stability", 0)) + 3)
        elif strategy_id == 16:
            state.flags["v12_capable_governors_until"] = state.turn_number + 60
            if any(_available_person(state, name) for name in ("殷景仁", "何尚之", "王敬弘")):
                regime["stability"] = min(100, int(regime.get("stability", 0)) + 3)
        elif strategy_id == 18:
            for person in state.persons.values():
                family = state.families.get(int(person.get("family_id") or 0), {})
                if int(person.get("country_id", 0)) == state.player_regime_id and int(family.get("family_type", -1)) == 1:
                    person["opinion_of_player"] = max(-100, int(person.get("opinion_of_player", 30)) - 5)
        elif strategy_id == 26:
            city = _city(state, "滑台"); city["defense"] = int(city.get("defense", 0)) + 20
            region = _region(state, "中原地区"); record = region_economy(state, int(region["id"])); record["warehouse"]["food"] = min(warehouse_capacity(state, int(region["id"])), float(record["warehouse"].get("food", 0)) + 20)
        elif strategy_id == 27:
            state.flags["v12_henan_offense_until"] = state.turn_number + 12
    elif strategy_id == 8:
        regime["stability"] = min(100, int(regime.get("stability", 0)) + 5); _change_person(state, "刘义隆", power=15)
        state.national_modifiers[:] = [m for m in state.national_modifiers if int(m.get("id", 0)) != 1201]
    elif strategy_id == 9:
        alive = 0
        for name, opinion in (("王昙首", 20), ("殷景仁", 20), ("王华", 10)):
            person = _available_person(state, name)
            if person:
                alive += 1; _change_person(state, name, opinion=opinion)
                if name in {"王昙首", "殷景仁"} and int(person["id"]) not in state.confidants: state.confidants.append(int(person["id"]))
        if not alive: _change_person(state, "刘义隆", power=10)
        state.national_modifiers.append({"id": 1202, "name": "元嘉近臣", "description": "每回合权威+5，扬州控制度每月+1。", "effects": {}})
    elif strategy_id == 11:
        for region in _controlled_regions(state):
            record = region_economy(state, int(region["id"]))
            if int(record["stability"]) >= 70 and _convert_refugees(state, int(region["id"]), .1): record["stability"] = min(100, int(record["stability"]) + 2)
    elif strategy_id == 12:
        ranked = sorted(_controlled_regions(state), key=lambda r: region_economy(state, int(r["id"]))["land"].get("gentry", 0), reverse=True)
        for region in _controlled_regions(state): region_economy(state, int(region["id"]))["control"] = min(100, int(region_economy(state, int(region["id"]))["control"]) + 5)
        for region in ranked[:3]:
            land = region_economy(state, int(region["id"]))["land"]; moved = max(1, int(land.get("gentry", 0) * .05)); land["gentry"] = max(0, int(land.get("gentry", 0)) - moved); land["smallholder"] += moved
    elif strategy_id == 17:
        state.flags["v12_tax_food_offset"] = -0.02; state.flags["v12_tax_cloth_offset"] = 0.02
        for region in _controlled_regions(state):
            record = region_economy(state, int(region["id"]));
            if int(record["stability"]) >= 60: record["stability"] = min(100, int(record["stability"]) + 2)
    elif strategy_id == 20:
        state.national_modifiers.append({"id": 1203, "name": "元嘉新政", "description": "权威恢复+10%，高稳定州流民转农速度+20%，一般商品产量+5%。", "effects": {}})
    elif strategy_id in {21, 22, 25, 28, 29}:
        names = {21:("徐州","淮北地区","中原地区"),22:("徐州","淮北地区"),25:("中原地区",),28:("徐州","淮北地区","中原地区"),29:("徐州","淮北地区")}[strategy_id]
        for name in names:
            region = _region(state, name)
            if not region: continue
            record = region_economy(state, int(region["id"]))
            if strategy_id in {21,28}: record["stability"] = min(100, int(record["stability"]) + (3 if strategy_id == 21 else 5))
            if strategy_id in {22,29,25}: record["control"] = min(100, int(record["control"]) + ({22:10,29:10,25:20}[strategy_id]))
            if strategy_id == 22: _convert_refugees(state, int(region["id"]), .05)
            if strategy_id == 29: record["stability"] = min(100, int(record["stability"]) + 10); _convert_refugees(state, int(region["id"]), .15)
        if strategy_id == 21:
            for city_name in ("彭城", "滑台", "洛阳"):
                city = _city(state, city_name)
                if city: city["defense"] = int(city.get("defense", 0)) + 10
        elif strategy_id == 25:
            city = _city(state, "洛阳"); city["defense"] = int(city.get("defense", 0)) + 10
        elif strategy_id == 28: regime["war_support"] = max(0, int(regime.get("war_support", 0)) - 10)
    elif strategy_id == 31:
        from .events import queue_story_event
        queue_story_event(state, 21)


def settle_strategies(state: GameState) -> list[int]:
    ensure_strategy_records(state); sync_strategy_statuses(state)
    completed = []
    for strategy_id, item in state.strategies.items():
        if item.get("status") != "in_progress": continue
        item["progress_months"] = int(item.get("progress_months", 0)) + 1
        if item["progress_months"] < int(item["duration_months"]): continue
        item["status"] = "completed"; _apply_effect(state, strategy_id); completed.append(strategy_id)
        state.add_log(f"经略完成：{item['name']}。{item['effect_description']}")
    return completed
