from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import Army, GameState
from ...rules.common import RuleError, clamp, is_regime_eliminated, living_commander_id, person_power, remove_emperor_civil_offices, spend_authority
from .strategies import strategy_completed
from .story_texts import render_dynamic_text, story_section, story_text, story_variant


def _template(
    decision_id: int,
    name: str,
    summary: str,
    effect: str,
    unlock_strategy: int | None = None,
    choices: list[str] | None = None,
) -> dict[str, Any]:
    section = story_section("决议", decision_id, summary)
    return {
        "id": decision_id,
        "name": name,
        "summary": summary,
        "effect_description": effect,
        "unlock_strategy": unlock_strategy,
        "choices": list(choices or []),
        "choice_prompt": "请选择储君" if decision_id == 29 else "请选择",
        "text": section["intro"],
    }


DECISION_TEMPLATES: dict[int, dict[str, Any]] = {
    14: _template(14, "加固建康", "加固建康的城防。", "国库-100，建康城防+30。", 17),
    15: _template(15, "组织门阀北府兵", "组织一支门阀北府兵。", "建康获得谢晦统领的三千步兵、两千弓兵；解锁淝水遗风；高门族长好感+15。", 19),
    16: _template(16, "斩慕容超", "斩杀南燕末帝慕容超。", "慕容超死亡，战争支持度+10，稳定度+10。"),
    17: _template(17, "祭拜晋皇陵", "前往北邙山祭拜晋皇陵。", "稳定度+10，河内司马氏成员好感+25。"),
    18: _template(18, "斩杀姚泓", "在建康斩杀后秦末帝姚泓。", "稳定度+10，刘裕基础权力+5，姚泓死亡。"),
    19: _template(19, "剑履上殿", "获得剑履上殿特权。", "国库-3000，稳定度-50，刘裕基础权力+10。", 21),
    20: _template(20, "入朝不趋", "获得入朝不趋特权。", "国库-3000，稳定度-50，刘裕基础权力+10。", 21),
    21: _template(21, "赞拜不名", "获得赞拜不名特权。", "国库-3000，稳定度-50，刘裕基础权力+10。", 21),
    22: _template(22, "进爵宋王", "进爵宋王。", "国库-3000，刘裕等级+1、基础权力+15，稳定度-50。"),
    23: _template(23, "废立", "废司马德宗，立司马德文。", "稳定度-25，刘裕基础权力+15；司马德文即位，改元元熙。", 22),
    24: _template(24, "杀司马德宗", "杀死已经退位的司马德宗。", "稳定度-25，刘裕基础权力+15，司马德宗死亡。"),
    25: _template(25, "建天子旌旗，享十二旒冠冕", "使用天子仪仗与十二旒冠冕。", "稳定度+5，刘裕等级+1。", 22),
    26: _template(26, "九锡之礼", "接受九锡。", "国库-3000，稳定度+5，刘裕等级+1。"),
    27: _template(27, "登基", "代晋建宋。", "国库-3000；晋帝退位；刘裕登基；国号宋，改元永初；权力分配变为无上皇权。"),
    28: _template(28, "杀司马德文", "处死退位的司马德文。", "稳定度+10，司马德文死亡，价值观法律下降一级。"),
    29: _template(29, "立储", "定立储君。", "所选皇子成为太子，并按长幼消耗权威、改变稳定度。", choices=["刘义符", "刘义真", "刘义隆", "刘义康"]),
}

TREASURY_COST_DECISIONS = {19, 20, 21, 22, 26, 27}
TREASURY_COST = 3000


@dataclass(frozen=True)
class Story4DecisionResult:
    text: str
    effect_description: str


def _person_id(state: GameState, name: str) -> int:
    person = next((item for item in state.persons.values() if state.person_name(int(item["id"])) == name), None)
    if not person:
        raise RuleError(f"人物配置中缺少{name}")
    return int(person["id"])


def _person_alive(state: GameState, name: str) -> bool:
    try:
        return int(state.persons[_person_id(state, name)].get("status", 0)) in {1, 2, 3}
    except RuleError:
        return False


def _city_id(state: GameState, name: str) -> int:
    city = next((item for item in state.cities.values() if item.get("name") == name), None)
    if not city:
        raise RuleError(f"城市配置中缺少{name}")
    return int(city["id"])


def _region(state: GameState, name: str) -> dict[str, Any] | None:
    return next((item for item in state.regions.values() if item.get("name") == name), None)


def _owns_and_controls(state: GameState, name: str) -> bool:
    region = _region(state, name)
    return bool(
        region
        and name in state.player_regime.get("regions", [])
        and int(region.get("controller", 0)) == state.player_regime_id
    )


def _completed(state: GameState) -> set[int]:
    return {int(item) for item in state.flags.get("completed_decisions", [])}


def _add_stability(state: GameState, amount: int) -> None:
    state.player_regime["stability"] = int(clamp(int(state.player_regime.get("stability", 0)) + amount, 0, 100))


def _add_war_support(state: GameState, amount: int) -> None:
    state.player_regime["war_support"] = int(clamp(int(state.player_regime.get("war_support", 0)) + amount, 0, 100))


def _add_base_power(state: GameState, name: str, amount: int, cap: int | None = None) -> None:
    person = state.persons[_person_id(state, name)]
    attrs = person.setdefault("attributes", {})
    value = int(attrs.get("base_power", 0)) + amount
    attrs["base_power"] = max(0, min(cap, value) if cap is not None else value)


def _kill(state: GameState, name: str) -> None:
    person_id = _person_id(state, name)
    state.persons[person_id]["status"] = 4
    state.persons[person_id]["death_year"] = state.year
    for army in state.armies.values():
        if army.commander == person_id:
            army.commander = None


def _render(state: GameState, text: str) -> str:
    return render_dynamic_text(state, text)


def decision_visible(state: GameState, decision_id: int, completed: set[int]) -> bool:
    if decision_id in completed:
        return False
    if decision_id in {14, 15, 19, 20, 21, 23, 25}:
        unlock = DECISION_TEMPLATES[decision_id].get("unlock_strategy")
        return bool(unlock and strategy_completed(state, int(unlock)))
    if decision_id == 16:
        return is_regime_eliminated(state, 8) and _person_alive(state, "慕容超")
    if decision_id == 17:
        return state.player_regime.get("name") == "晋" and _person_alive(state, "刘裕")
    if decision_id == 18:
        return bool(state.events.get(17, {}).get("triggered")) and _person_alive(state, "姚泓")
    if decision_id == 22:
        return {19, 20, 21} <= completed
    if decision_id == 24:
        return 23 in completed and _person_alive(state, "司马德宗")
    if decision_id == 26:
        return 25 in completed
    if decision_id == 27:
        return 26 in completed
    if decision_id in {28, 29}:
        return 27 in completed
    return False


def decision_available(state: GameState, decision_id: int, completed: set[int]) -> tuple[bool, str]:
    if not decision_visible(state, decision_id, completed):
        return False, "尚未解锁或已经完成"
    stability = int(state.player_regime.get("stability", 0))
    if decision_id in TREASURY_COST_DECISIONS and int(state.player_regime.get("treasury", 0)) < TREASURY_COST:
        return False, f"国库需要达到{TREASURY_COST}"
    if decision_id == 14 and int(state.player_regime.get("treasury", 0)) < 100:
        return False, "国库需要达到100"
    if decision_id == 16:
        if not (_owns_and_controls(state, "青州") and _owns_and_controls(state, "徐州")):
            return False, "需要拥有并控制青州、徐州"
    if decision_id == 17 and int(state.player["location_id"]) != _city_id(state, "洛阳"):
        return False, "刘裕需要位于洛阳"
    if decision_id in {19, 20, 21} and stability <= 50:
        return False, "稳定度必须大于50"
    if decision_id == 22 and stability <= 60:
        return False, "稳定度必须大于60"
    if decision_id == 25:
        if person_power(state, state.player) < 2000:
            return False, "刘裕权力需要达到2000"
        if stability < 60:
            return False, "稳定度需要达到60"
    if decision_id in {26, 27}:
        if person_power(state, state.player) < 2500:
            return False, "刘裕权力需要达到2500"
        if stability < 65:
            return False, "稳定度需要达到65"
    if decision_id == 27 and int(state.player.get("level", 0)) != 10:
        return False, "刘裕等级必须为10"
    if decision_id == 28 and not _person_alive(state, "司马德文"):
        return False, "司马德文已经死亡"
    if decision_id == 29 and state.player_regime.get("internal", {}).get("crown_prince"):
        return False, "已经册立太子"
    return True, "可以执行"


def _create_beifu_army(state: GameState) -> None:
    commander = living_commander_id(state, _person_id(state, "谢晦"))
    for army in state.armies.values():
        if army.commander == commander:
            army.commander = None
    army_id = max(state.armies, default=0) + 1
    state.armies[army_id] = Army(
        army_id,
        state.player_regime_id,
        0,
        [{"type": 1, "count": 1000} for _ in range(3)] + [{"type": 3, "count": 1000} for _ in range(2)],
        commander=commander,
        location_id=_city_id(state, "建康"),
    )
    if commander:
        state.persons[commander]["location_id"] = _city_id(state, "建康")


def _heir_choice(state: GameState, choice: str | None) -> tuple[str, str]:
    costs = {"刘义符": (100, 10, "1"), "刘义真": (1000, -30, "2"), "刘义隆": (1500, -50, "3"), "刘义康": (2000, -70, "4")}
    if choice not in costs:
        raise RuleError("必须从四位皇子中选择储君")
    cost, stability, variant = costs[choice]
    spend_authority(state, cost, apply_law_modifier=False)
    state.player_regime.setdefault("internal", {})["crown_prince"] = _person_id(state, choice)
    _add_stability(state, stability)
    text = story_variant("决议", 29, variant, f"{choice}被册立为太子。")
    return text, f"{choice}成为太子，权威-{cost}，稳定度{stability:+d}。"


def execute(state: GameState, decision_id: int, choice: str | None = None) -> Story4DecisionResult:
    text = story_text("决议", decision_id, DECISION_TEMPLATES[decision_id]["summary"])
    effect = str(DECISION_TEMPLATES[decision_id]["effect_description"])
    if decision_id in TREASURY_COST_DECISIONS:
        state.player_regime["treasury"] -= TREASURY_COST
    if decision_id == 14:
        state.player_regime["treasury"] -= 100
        city = state.cities[_city_id(state, "建康")]
        city["defense"] = int(clamp(int(city.get("defense", 0)) + 30, 0, 100))
    elif decision_id == 15:
        _create_beifu_army(state)
        for family in state.families.values():
            if int(family.get("family_type", -1)) != 1:
                continue
            leader = state.persons.get(int(family.get("leader") or 0))
            if leader:
                leader["opinion_of_player"] = int(clamp(int(leader.get("opinion_of_player", 0)) + 15, -100, 100))
    elif decision_id == 16:
        _kill(state, "慕容超")
        _add_war_support(state, 10)
        _add_stability(state, 10)
    elif decision_id == 17:
        _add_stability(state, 10)
        family = next((item for item in state.families.values() if item.get("name") == "河内司马氏"), None)
        if family:
            for person_id in family.get("members", []):
                person = state.persons.get(int(person_id))
                if person:
                    person["opinion_of_player"] = int(clamp(int(person.get("opinion_of_player", 0)) + 25, -100, 100))
    elif decision_id == 18:
        _kill(state, "姚泓")
        _add_stability(state, 10)
        _add_base_power(state, "刘裕", 5)
    elif decision_id in {19, 20, 21}:
        _add_stability(state, -50)
        _add_base_power(state, "刘裕", 10)
    elif decision_id == 22:
        state.player["level"] = int(state.player.get("level", 0)) + 1
        _add_stability(state, -50)
        _add_base_power(state, "刘裕", 15)
    elif decision_id == 23:
        old_id, new_id = _person_id(state, "司马德宗"), _person_id(state, "司马德文")
        state.persons[old_id]["level"] = 5
        state.persons[new_id]["level"] = 10
        state.player_regime.setdefault("internal", {})["emperor"] = new_id
        remove_emperor_civil_offices(state, state.player_regime_id)
        state.flags["era_name"] = "元熙"
        state.flags["era_start_year"] = state.year
        _add_stability(state, -25)
        _add_base_power(state, "刘裕", 15)
    elif decision_id == 24:
        _kill(state, "司马德宗")
        _add_stability(state, -25)
        _add_base_power(state, "刘裕", 15)
    elif decision_id in {25, 26}:
        _add_stability(state, -50)
        state.player["level"] = int(state.player.get("level", 0)) + 1
    elif decision_id == 27:
        internal = state.player_regime.setdefault("internal", {})
        former = int(internal.get("emperor") or 0)
        if former in state.persons and former != int(state.player["id"]):
            state.persons[former]["level"] = 5
        internal["emperor"] = int(state.player["id"])
        remove_emperor_civil_offices(state, state.player_regime_id)
        state.player["level"] = 10
        state.player_regime["name"] = "宋"
        state.player_regime["color"] = "blue"
        state.flags["era_name"] = "永初"
        state.flags["era_start_year"] = state.year
        state.laws["power"] = 4
        liu_family = next((item for item in state.families.values() if item.get("name") == "彭城刘氏-1"), None)
        sima_family = next((item for item in state.families.values() if item.get("name") == "河内司马氏"), None)
        if liu_family:
            liu_family["family_type"] = 0
        if sima_family:
            sima_family["family_type"] = 2
        _add_stability(state, 10)
    elif decision_id == 28:
        _kill(state, "司马德文")
        state.laws["values"] = max(1, int(state.laws.get("values", 1)) - 1)
        _add_stability(state, 10)
    elif decision_id == 29:
        text, effect = _heir_choice(state, choice)
    return Story4DecisionResult(_render(state, text), effect)
