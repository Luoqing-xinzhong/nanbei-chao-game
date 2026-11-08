from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...models import Army, GameState
from ...rules.common import clamp, is_regime_eliminated, living_commander_id
from .story_texts import render_dynamic_text, story_section, story_text, story_variant


def _event(
    event_id: int,
    name: str,
    summary: str,
    effect: str,
    choices: list[str] | None = None,
    choice_required: bool = False,
) -> dict[str, Any]:
    section = story_section("事件", event_id, summary)
    return {
        "id": event_id,
        "name": name,
        "summary": summary,
        "effect_handler": f"event_{event_id}_effect",
        "effect_description": effect,
        "repeatable": False,
        "text": section["intro"],
        "choices": list(choices or []),
        "choice_required": bool(choice_required),
    }


EVENT_TEMPLATES: dict[int, dict[str, Any]] = {
    15: _event(15, "魏援助后秦", "魏决定出兵援助后秦。", "魏在平城组建四支五千骑兵并向主控政权宣战。"),
    16: _event(16, "光复洛阳", "主控政权光复洛阳。", "战争支持度+10，稳定度+10，刘裕基础权力+10。"),
    17: _event(17, "攻克长安", "主控政权光复长安。", "战争支持度+5，稳定度+5；魏将尽快议和。"),
    18: _event(18, "刘穆之之死", "刘穆之病逝，必须为文官党选出新领袖。", "稳定度-10。", ["徐羡之", "王弘"], True),
    19: _event(19, "人心思危", "刘裕不在建康，文官党开始组织特殊政变。", "政变每月固定推进10%，只有刘裕回到建康才能终止。"),
    20: _event(20, "沈田子杀王镇恶", "沈田子杀王镇恶，随后被处决。", "沈田子、王镇恶死亡，战争支持度-20，稳定度-15。"),
    21: _event(21, "赫连勃勃染指关中", "胡夏趁关中空虚进攻长安。", "胡夏向主控政权宣战，并在统万城组建一万步兵。"),
    22: _event(22, "关中沦陷", "赫连勃勃攻占长安。", "战争支持度-7，对北态度下降一级，稳定度-5；胡夏提出割让北雍州的和平要求。"),
    23: _event(23, "攻克统万城", "主控政权攻克统万城。", "战争支持度+20，稳定度+10。"),
    24: _event(24, "攻克平城", "主控政权攻克平城。", "战争支持度+20，稳定度+10。"),
    25: _event(25, "刘裕去世", "刘裕去世，1.1版本流程结束。", "游戏结束。"),
}


def _person_id(state: GameState, name: str) -> int | None:
    return next((int(item["id"]) for item in state.persons.values() if state.person_name(int(item["id"])) == name), None)


def _alive(state: GameState, name: str) -> bool:
    person_id = _person_id(state, name)
    return bool(person_id and int(state.persons[person_id].get("status", 0)) in {1, 2, 3})


def _city_id(state: GameState, name: str) -> int:
    return next(int(item["id"]) for item in state.cities.values() if item.get("name") == name)


def _city_controller(state: GameState, name: str) -> int:
    from ...rules.military import city_controller

    return city_controller(state, _city_id(state, name))


def _owns_and_controls_region(state: GameState, name: str) -> bool:
    region = next((item for item in state.regions.values() if item.get("name") == name), None)
    return bool(region and name in state.player_regime.get("regions", []) and int(region.get("controller", 0)) == state.player_regime_id)


def _stability_cap(state: GameState) -> int:
    return {1: 50, 2: 70}.get(int(state.laws.get("values", 1)), 100)


def _war_support_cap(state: GameState) -> int:
    return 50 if int(state.laws.get("north", 1)) == 1 else 100


def _add_stability(state: GameState, amount: int, respect_law: bool = True) -> None:
    high = _stability_cap(state) if respect_law and amount > 0 else 100
    state.player_regime["stability"] = int(clamp(int(state.player_regime.get("stability", 0)) + amount, 0, high))


def _add_war_support(state: GameState, amount: int, respect_law: bool = True) -> None:
    high = _war_support_cap(state) if respect_law and amount > 0 else 100
    state.player_regime["war_support"] = int(clamp(int(state.player_regime.get("war_support", 0)) + amount, 0, high))


def _base_power(state: GameState, name: str, amount: int) -> None:
    person_id = _person_id(state, name)
    if person_id:
        attrs = state.persons[person_id].setdefault("attributes", {})
        attrs["base_power"] = max(0, int(attrs.get("base_power", 0)) + amount)


def _kill(state: GameState, name: str) -> None:
    person_id = _person_id(state, name)
    if not person_id:
        return
    state.persons[person_id]["status"] = 4
    state.persons[person_id]["death_year"] = state.year
    for army in state.armies.values():
        if army.commander == person_id:
            army.commander = None


def _create_army(state: GameState, regime_id: int, city_name: str, commander_name: str, unit_type: int, battalions: int) -> Army:
    commander = living_commander_id(state, _person_id(state, commander_name))
    if commander:
        for army in state.armies.values():
            if army.commander == commander:
                army.commander = None
    army_id = max(state.armies, default=0) + 1
    city_id = _city_id(state, city_name)
    army = Army(
        army_id,
        regime_id,
        0,
        [{"type": unit_type, "count": 1000} for _ in range(battalions)],
        commander=commander,
        location_id=city_id,
        max_action_points=2.0 if unit_type == 2 else 1.0,
        action_points=2.0 if unit_type == 2 else 1.0,
    )
    state.armies[army_id] = army
    if commander:
        state.persons[commander]["location_id"] = city_id
    return army


def _declare_war(state: GameState, regime_id: int) -> None:
    pair = state.relation_pair(state.player_regime_id, regime_id)
    if pair not in state.wars:
        state.wars.append(pair)
    state.flags[f"war_started:{pair[0]}:{pair[1]}"] = state.turn_number
    state.flags[f"war_aggressor:{pair[0]}:{pair[1]}"] = regime_id
    state.regimes[regime_id]["relation_with_main"] = "交战"


def _end_war(state: GameState, regime_id: int) -> None:
    from ...rules.diplomacy import month_index, repatriate_armies_after_peace, truce_key

    pair = state.relation_pair(state.player_regime_id, regime_id)
    if pair in state.wars:
        state.wars.remove(pair)
    state.regimes[regime_id]["relation_with_main"] = "正常"
    state.flags[truce_key(state, state.player_regime_id, regime_id)] = month_index(state) + 12
    repatriate_armies_after_peace(state, state.player_regime_id, regime_id)


def _event_15_condition(state: GameState) -> bool:
    return state.at_war(state.player_regime_id, 9) and _city_controller(state, "洛阳") == state.player_regime_id and not is_regime_eliminated(state, 2)


def _event_16_condition(state: GameState) -> bool:
    return _city_controller(state, "洛阳") == state.player_regime_id


def _event_17_condition(state: GameState) -> bool:
    return _city_controller(state, "长安") == state.player_regime_id


def _event_18_condition(state: GameState) -> bool:
    person_id = _person_id(state, "刘穆之")
    return bool(person_id and int(state.persons[person_id].get("status", 0)) == 4)


def _event_19_condition(state: GameState) -> bool:
    return bool(
        state.events.get(18, {}).get("triggered")
        and state.flags.get("civil_party_successor")
        and int(state.player.get("location_id", 0)) != _city_id(state, "建康")
    )


def _event_20_condition(state: GameState) -> bool:
    tianzi, zhene = _person_id(state, "沈田子"), _person_id(state, "王镇恶")
    return bool(
        state.events.get(17, {}).get("triggered")
        and tianzi and zhene and _alive(state, "沈田子") and _alive(state, "王镇恶")
        and int(state.persons[tianzi].get("location_id", 0)) == int(state.persons[zhene].get("location_id", 0))
        and int(state.player.get("location_id", 0)) != int(state.persons[tianzi].get("location_id", 0))
    )


def _event_21_condition(state: GameState) -> bool:
    return _owns_and_controls_region(state, "北雍州") and not is_regime_eliminated(state, 12)


def _event_22_condition(state: GameState) -> bool:
    return bool(state.events.get(21, {}).get("triggered")) and _city_controller(state, "长安") == 12


def _event_23_condition(state: GameState) -> bool:
    return _city_controller(state, "统万城") == state.player_regime_id


def _event_24_condition(state: GameState) -> bool:
    return _city_controller(state, "平城") == state.player_regime_id


def _event_25_condition(state: GameState) -> bool:
    person_id = _person_id(state, "刘裕")
    return bool(person_id and int(state.persons[person_id].get("status", 0)) == 4)


def _event_15_effect(state: GameState) -> None:
    _create_army(state, 2, "平城", "拓跋嗣", 2, 5)
    for _ in range(3):
        _create_army(state, 2, "平城", "", 2, 5)
    _declare_war(state, 2)
    state.flags["wei_aid_qin_active"] = True
    state.flags["wei_aid_target"] = _city_id(state, "洛阳")


def _event_16_effect(state: GameState) -> None:
    _add_war_support(state, 10)
    _add_stability(state, 10)
    _base_power(state, "刘裕", 10)


def _event_17_effect(state: GameState) -> None:
    _add_war_support(state, 5)
    _add_stability(state, 5)
    if state.events.get(15, {}).get("triggered") and state.at_war(state.player_regime_id, 2):
        _end_war(state, 2)
        state.flags["wei_aid_qin_active"] = False
        state.add_log("长安已被攻克，魏依照援秦方略主动与主控政权议和。")


def _event_18_effect(state: GameState) -> None:
    _add_stability(state, -10, respect_law=False)
    state.flags["pending_event_choice:18"] = True


def _event_19_effect(state: GameState) -> None:
    leader = int(state.flags.get("civil_party_successor", 0))
    party = next((item for item in state.parties.values() if item.get("name") == "文官党"), None)
    if not party or not leader:
        return
    jiankang = _city_id(state, "建康")
    participants = [
        int(person["id"])
        for person in state.persons.values()
        if int(person.get("country_id", 0)) == state.player_regime_id
        and int(person.get("status", 0)) in {1, 2, 3}
        and int(person.get("location_id", 0)) == jiankang
        and int(person["id"]) != int(state.player["id"])
    ]
    party["coup"] = {
        "leader": leader,
        "participants": list(dict.fromkeys([leader] + participants)),
        "progress": 0.0,
        "exposed": True,
        "special_jiankang": True,
    }
    state.flags["special_jiankang_coup_party"] = int(party["id"])


def _event_20_effect(state: GameState) -> None:
    _kill(state, "沈田子")
    _kill(state, "王镇恶")
    _add_war_support(state, -20, respect_law=False)
    _add_stability(state, -15, respect_law=False)


def _event_21_effect(state: GameState) -> None:
    _create_army(state, 12, "统万城", "赫连勃勃", 1, 10)
    _declare_war(state, 12)
    state.flags["huxia_changan_target"] = _city_id(state, "长安")


def _event_22_effect(state: GameState) -> None:
    _add_war_support(state, -7, respect_law=False)
    _add_stability(state, -5, respect_law=False)
    state.laws["north"] = max(1, int(state.laws.get("north", 1)) - 1)
    region = next((item for item in state.regions.values() if item.get("name") == "北雍州"), None)
    if region:
        state.flags["huxia_required_peace_region"] = int(region["id"])
    state.flags["huxia_changan_target"] = 0


def _event_23_effect(state: GameState) -> None:
    _add_war_support(state, 20)
    _add_stability(state, 10)


def _event_24_effect(state: GameState) -> None:
    _add_war_support(state, 20)
    _add_stability(state, 10)


def _event_25_effect(state: GameState) -> None:
    emperor = int(state.player_regime.get("internal", {}).get("emperor") or 0) == int(state.player["id"])
    has_luoyang = _city_controller(state, "洛阳") == state.player_regime_id
    if not emperor:
        key = "如果死亡时身份不为皇帝且稳定度低于50" if int(state.player_regime.get("stability", 0)) < 50 else "如果死亡时身份不为皇帝且稳定度高于50"
    else:
        key = "如果死亡时身份为皇帝且有洛阳" if has_luoyang else "如果死亡时身份为皇帝但没有洛阳"
    ending = render_dynamic_text(state, story_variant("事件", 25, key, "刘裕去世，属于他的时代结束了。"))
    state.events[25]["text"] = ending + "\n\n感谢大家游玩1.1版本，后续会继续更新。"
    state.flags["game_over"] = True
    state.flags["game_over_reason"] = "刘裕去世，1.1版本剧情结束。"


EVENT_CONDITIONS: dict[int, Callable[[GameState], bool]] = {
    15: _event_15_condition,
    16: _event_16_condition,
    17: _event_17_condition,
    18: _event_18_condition,
    19: _event_19_condition,
    20: _event_20_condition,
    21: _event_21_condition,
    22: _event_22_condition,
    23: _event_23_condition,
    24: _event_24_condition,
    25: _event_25_condition,
}

EVENT_EFFECTS: dict[int, Callable[[GameState], None]] = {
    15: _event_15_effect,
    16: _event_16_effect,
    17: _event_17_effect,
    18: _event_18_effect,
    19: _event_19_effect,
    20: _event_20_effect,
    21: _event_21_effect,
    22: _event_22_effect,
    23: _event_23_effect,
    24: _event_24_effect,
    25: _event_25_effect,
}


def apply_event_choice(state: GameState, event_id: int, choice: str) -> str:
    if event_id != 18 or choice not in {"徐羡之", "王弘"}:
        raise ValueError("事件选项无效")
    leader = _person_id(state, choice)
    if not leader:
        raise ValueError(f"人物配置中缺少{choice}")
    party = next((item for item in state.parties.values() if item.get("name") == "文官党"), None)
    if party:
        party["leader"] = leader
        party["members"] = list(dict.fromkeys([leader] + [int(item) for item in party.get("members", [])]))
        party.pop("coup", None)
    state.flags["civil_party_successor"] = leader
    state.flags.pop("pending_event_choice:18", None)
    state.add_log(f"{choice}接任文官党领袖。")
    return render_dynamic_text(state, story_variant("事件", 18, choice, f"{choice}接掌台省与文官党。"))


def settle_natural_deaths(state: GameState) -> list[int]:
    """Resolve configured death years at the first turn that reaches that year."""
    deceased: list[int] = []
    for person in state.persons.values():
        death_year = int(person.get("death_year", 0) or 0)
        if death_year <= 0 or state.year < death_year or int(person.get("status", 0)) not in {1, 2, 3}:
            continue
        person_id = int(person["id"])
        person["status"] = 4
        deceased.append(person_id)
        for army in state.armies.values():
            if army.commander == person_id:
                army.commander = None
        state.add_log(f"{state.person_name(person_id)}于公元{state.year}年去世。")
    return deceased


def resolve_special_coup_if_player_returns(state: GameState) -> bool:
    if int(state.player.get("location_id", 0)) != _city_id(state, "建康"):
        return False
    party_id = int(state.flags.get("special_jiankang_coup_party", 0))
    party = state.parties.get(party_id)
    if not party or not party.get("coup", {}).get("special_jiankang"):
        return False
    party.pop("coup", None)
    state.flags.pop("special_jiankang_coup_party", None)
    state.flags["special_jiankang_coup_resolved"] = True
    state.add_log("刘裕回到建康，人心思危引发的特殊政变立即停止。")
    return True
