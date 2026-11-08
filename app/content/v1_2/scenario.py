from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

from ...constants import JSON_DIR, V11_CONFIG_DIR, V12_CONFIG_DIR
from ...data_loader import DataError, load_initial_state
from ...models import Army, GameState
from ...rules.common import remove_emperor_civil_offices
from ...v11 import DEFAULT_LAWS, load_v11_families
from .economy import army_supply_capacity, enforce_warehouse_capacity, initialize_economy, region_economy


SONG_REGIONS = tuple(range(1, 17))
TERRITORY: dict[int, tuple[int, ...]] = {
    1: SONG_REGIONS,
    2: (17, 18, 19),
    7: (23,),
    10: (22,),
    11: (24,),
    12: (20, 21),
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"无法读取1.2配置 {path.name}: {exc}") from exc


def _index(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(item["id"]): copy.deepcopy(item) for item in items}


def load_expanded_people_and_families(version_dir: Path = V12_CONFIG_DIR) -> tuple[dict[int, dict], dict[int, dict]]:
    """Load the expanded Yuanjia roster and merge its new family definitions."""
    expanded_path = version_dir / "persons_all_factions_initial_1.2_yuanjia_expanded.json"
    fallback_path = version_dir / "persons_all_factions_initial_1.2.json"
    people = _index(_read_json(expanded_path if expanded_path.exists() else fallback_path))
    families = load_v11_families(V11_CONFIG_DIR)
    additions_path = version_dir / "families_1_2_yuanjia_additions.json"
    if additions_path.exists():
        families.update(_index(_read_json(additions_path)))
    # 配置中的人物归属是唯一真源；既补齐旧家族的新成员，也清除过期成员编号。
    members_by_family: dict[int, list[int]] = {}
    for person_id, person in people.items():
        family_id = int(person.get("family_id") or 0)
        if family_id:
            members_by_family.setdefault(family_id, []).append(int(person_id))
    for family_id, family in families.items():
        family["members"] = sorted(members_by_family.get(int(family_id), []))
        leader = int(family.get("leader") or 0)
        if leader not in family["members"]:
            family["leader"] = family["members"][0] if family["members"] else None
    return people, families


def merge_expanded_roster_into_state(state: GameState, version_dir: Path = V12_CONFIG_DIR) -> None:
    """Add expanded-roster entries to an existing 1.2 save without resetting living state."""
    configured_people, configured_families = load_expanded_people_and_families(version_dir)
    for person_id, person in configured_people.items():
        state.persons.setdefault(int(person_id), copy.deepcopy(person))
    for family_id, configured in configured_families.items():
        family = state.families.setdefault(int(family_id), copy.deepcopy(configured))
        family.setdefault("family_type", configured.get("family_type"))
        family.setdefault("government_opinion", configured.get("government_opinion", 0))
    family_names = {
        5: ("刘义恭", "刘义宣", "刘义季", "刘劭", "刘浚", "刘骏", "刘诞", "刘宏", "刘祎", "刘昶", "刘彧", "刘休仁", "刘休佑", "刘休茂", "刘休范", "刘休若"),
        15: ("庾俊之", "庾登之"),
        24: ("萧惠开",),
        29: ("拓跋焘", "拓跋晃", "拓跋丕", "拓跋范", "拓跋健"),
        30: ("赫连昌", "赫连定"),
        0: ("刘道产", "刘尼", "刘休宾", "刘昞"),
    }
    for family_id, names in family_names.items():
        for name in names:
            person_id = _person_id(state, name)
            if person_id:
                state.persons[person_id]["family_id"] = family_id
    for obsolete_family_id in (36, 42, 49, 52, 60):
        state.families.pop(obsolete_family_id, None)
    if 23 in state.families:
        state.families[23]["family_type"] = 2

    def set_parent(child_name: str, parent_name: str) -> None:
        child_id, parent_id = _person_id(state, child_name), _person_id(state, parent_name)
        if not child_id or not parent_id:
            return
        state.persons[child_id]["father"] = parent_id
        children = [int(item) for item in state.persons[parent_id].setdefault("children", [])]
        if child_id not in children:
            children.append(child_id)
        state.persons[parent_id]["children"] = sorted(children)

    for child_name in ("刘义恭", "刘义宣", "刘义季"):
        set_parent(child_name, "刘裕")
    for child_name in ("刘劭", "刘浚", "刘骏", "刘诞", "刘宏", "刘祎", "刘昶", "刘彧", "刘休仁", "刘休佑", "刘休茂", "刘休范", "刘休若"):
        set_parent(child_name, "刘义隆")
    for child_name, parent_name in (("王琇", "王谧"), ("谢瑍", "谢玄"), ("萧惠开", "萧思话"), ("拓跋焘", "拓跋嗣"), ("赫连昌", "赫连勃勃"), ("赫连定", "赫连勃勃")):
        set_parent(child_name, parent_name)
    xie_ju, xie_huan = _person_id(state, "谢据"), _person_id(state, "谢瑍")
    if xie_ju and xie_huan:
        state.persons[xie_ju]["children"] = [int(item) for item in state.persons[xie_ju].get("children", []) if int(item) != xie_huan]

    members_by_family: dict[int, list[int]] = {}
    for person_id, person in state.persons.items():
        family_id = int(person.get("family_id") or 0)
        if family_id:
            members_by_family.setdefault(family_id, []).append(int(person_id))
    for family_id, family in state.families.items():
        family["members"] = sorted(members_by_family.get(int(family_id), []))
        if int(family.get("leader") or 0) not in family["members"]:
            configured_leader = int(configured_families.get(int(family_id), {}).get("leader") or 0)
            family["leader"] = configured_leader if configured_leader in family["members"] else (family["members"][0] if family["members"] else None)


def _person_id(state: GameState, name: str) -> int:
    return next(
        (int(person_id) for person_id, person in state.persons.items() if f"{person.get('surname', '')}{person.get('given_name', '')}" == name),
        0,
    )


def _set_territory(state: GameState) -> None:
    for regime in state.regimes.values():
        regime["regions"] = []
    for region in state.regions.values():
        region["controller"] = 0
        region["governor"] = None
    for regime_id, region_ids in TERRITORY.items():
        regime = state.regimes[regime_id]
        regime["regions"] = [state.regions[region_id]["name"] for region_id in region_ids]
        for region_id in region_ids:
            state.regions[region_id]["controller"] = regime_id


def _assign_opening_governors(state: GameState, rng: random.Random | None = None) -> None:
    """Staff Song regions, fixing Xie Hui in Jingzhou before random assignment."""
    rng = rng or random.SystemRandom()
    regime_id = state.player_regime_id
    emperor = int(state.regimes[regime_id].get("internal", {}).get("emperor") or 0)
    candidates = []
    for person_id, person in state.persons.items():
        family = state.families.get(int(person.get("family_id") or 0), {})
        if (
            int(person.get("country_id") or 0) == regime_id
            and int(person.get("status", 0)) == 1
            and int(person.get("birth_year", 0) or 0) <= state.year
            and (not int(person.get("death_year", 0) or 0) or int(person.get("death_year", 0)) >= state.year)
            and int(person_id) != emperor
            and family.get("family_type") in {0, 1}
        ):
            candidates.append(int(person_id))
    region_ids = [
        int(region_id)
        for region_id, region in sorted(state.regions.items())
        if region.get("name") in set(state.regimes[regime_id].get("regions", []))
    ]
    if len(candidates) < len(region_ids):
        raise DataError("1.2开局的高门、宗室人物不足，无法为宋国各州分配刺史")
    fixed: dict[int, int] = {}
    jingzhou_id = next(
        (region_id for region_id in region_ids if state.regions[region_id].get("name") == "荆州"),
        None,
    )
    xie_hui = _person_id(state, "谢晦")
    if jingzhou_id is not None and xie_hui in candidates:
        fixed[jingzhou_id] = xie_hui
        candidates.remove(xie_hui)
    random_region_ids = [region_id for region_id in region_ids if region_id not in fixed]
    rng.shuffle(candidates)
    for region_id, person_id in fixed.items():
        state.regions[region_id]["governor"] = person_id
    for region_id, person_id in zip(random_region_ids, candidates):
        state.regions[region_id]["governor"] = person_id


def _army(state: GameState, regime_id: int, army_type: int, unit_type: int, city_id: int, battalions: int = 5) -> Army:
    army_id = max(state.armies, default=0) + 1
    army = Army(
        id=army_id,
        regime_id=regime_id,
        army_type=army_type,
        units=[{"type": unit_type, "count": 1000} for _ in range(battalions)],
        morale=80,
        experience=10,
        location_id=city_id,
        action_points=2.0 if unit_type == 2 else 1.0,
        max_action_points=2.0 if unit_type == 2 else 1.0,
    )
    army.supply_food = army_supply_capacity(army)
    state.armies[army_id] = army
    return army


def _install_armies(state: GameState) -> None:
    state.armies.clear()
    for _ in range(3):
        _army(state, 1, 0, 1, 77)
    for _ in range(2):
        _army(state, 1, 1, 4, 1)
    # 预留事件2的五路魏国骑兵编号；事件2触发时接管并登记这些军队。
    for _ in range(5):
        _army(state, 2, 0, 2, int(state.regimes[2]["capital"]))
    # 在原剧情军编号之后，每个开局政权再获得一支五千人步兵军。
    for regime_id, regime in sorted(state.regimes.items()):
        capital = int(regime.get("capital") or 0)
        if regime.get("regions") and capital in state.cities:
            _army(state, int(regime_id), 0, 1, capital)


def load_v12_state(json_dir: Path = JSON_DIR, version_dir: Path = V12_CONFIG_DIR) -> GameState:
    """Load the Yuanjia 1.2 sub-scenario without mutating any 1.1 content."""
    state = load_initial_state(json_dir)
    state.regions = _index(_read_json(version_dir / "regions_initial_1.2.json"))
    state.regimes = _index(_read_json(version_dir / "regimes_initial_1.2.json"))
    state.persons, state.families = load_expanded_people_and_families(version_dir)
    for region in state.regions.values():
        derived = [city["id"] for city in state.cities.values() if int(city.get("region_id", 0)) == int(region["id"])]
        region["cities"] = list(dict.fromkeys([int(city) for city in region.get("cities", []) if int(city) in state.cities] + derived))
    _set_territory(state)

    state.year = 422
    state.month = 1
    state.turn_number = 1
    state.phase_index = 0
    state.authority = 500
    state.confidants.clear()
    state.wars = [state.relation_pair(1, 2)]
    state.vassals.clear()
    state.diplomatic_actions.clear()
    state.flags = {
        "content_version": "1.2",
        "scenario_id": "yuanjia_governance",
        "era_name": "永初",
        "era_start_year": 422,
        "v12_opening_applied": True,
    }
    state.laws = dict(DEFAULT_LAWS)
    state.legislation = {}
    state.strategies = {}
    state.events = {}
    state.national_modifiers = []
    xu_xianzhi = _person_id(state, "徐羡之")
    fu_liang = _person_id(state, "傅亮")
    xie_hui = _person_id(state, "谢晦")
    tan_daoji = _person_id(state, "檀道济")
    liu_yu = _person_id(state, "刘裕")
    liu_yifu = _person_id(state, "刘义符")
    state.parties = {
        1: {"id": 1, "name": "文官党", "leader": xu_xianzhi or None, "members": [item for item in (xu_xianzhi, fu_liang, xie_hui) if item], "supported_families": []},
        2: {"id": 2, "name": "武将党", "leader": tan_daoji or None, "members": [tan_daoji] if tan_daoji else [], "supported_families": []},
        3: {"id": 3, "name": "外戚党", "leader": None, "members": [], "supported_families": []},
        4: {"id": 4, "name": "宗室党", "leader": None, "members": [], "supported_families": []},
    }

    for regime in state.regimes.values():
        regime["is_main"] = int(regime["id"]) == 1
        regime.setdefault("authority", 200)
        regime.setdefault("internal", {})
    state.regimes[1]["internal"]["emperor"] = liu_yifu
    remove_emperor_civil_offices(state, 1)
    state.regimes[1]["stability"] = min(60, int(state.regimes[1].get("stability", 60)))
    state.regimes[2]["relation_with_main"] = "交战"
    for person in state.persons.values():
        person["is_player"] = int(person["id"]) == liu_yifu
        person["opinion_of_player"] = 30
    if liu_yu:
        state.persons[liu_yu]["status"] = 4
    if liu_yifu:
        state.persons[liu_yifu]["level"] = 10
        state.persons[liu_yifu]["location_id"] = 1
        liu_family_id = int(state.persons[liu_yifu].get("family_id") or 0)
        if liu_family_id in state.families:
            state.families[liu_family_id]["family_type"] = 0
    _assign_opening_governors(state)

    _install_armies(state)
    initialize_economy(state)
    state.player_regime["treasury"] = 1_000.0
    for regime_id, regime in state.regimes.items():
        if int(regime_id) == state.player_regime_id:
            continue
        regime["stability"] = 100
        regime["war_support"] = 100
        regime["treasury"] = 1_000.0 if regime.get("regions") else 0.0
    state.flags["v12_global_treasury_migrated"] = True
    state.flags["v12_capital_treasury_migrated"] = True
    state.flags["v12_story_events"] = []
    state.event_log.clear()
    from .events import queue_story_event

    queue_story_event(state, 1)
    queue_story_event(state, 2)
    state.add_log("公元422年永初三年，宋武帝崩，少帝即位；魏军趁丧南侵。")
    state.normalize_person_power_data()
    state.diagnostics.append("已加载1.2‘元嘉之治’：启用独立人口、土地、市场、物流、地方治理与军粮规则。")
    return state


def _queue(state: GameState, event_id: int) -> None:
    pending = state.flags.setdefault("pending_story_events", [])
    if event_id not in pending:
        pending.append(event_id)


def queue_start_of_turn_events(state: GameState) -> list[int]:
    queued: list[int] = []
    from .events import check_story_events

    queued.extend(check_story_events(state))
    xu_id = _person_id(state, "徐羡之")
    xu_dead = bool(xu_id) and int(state.persons.get(xu_id, {}).get("status", 0)) == 4
    if xu_dead and any(int(item.get("id", 0)) == 1201 for item in state.national_modifiers):
        state.national_modifiers[:] = [item for item in state.national_modifiers if int(item.get("id", 0)) != 1201]
        state.add_log("徐羡之已死，国家修正“主少国疑”移除。")
    ensure_wei_rejection_reinforcements(state)
    return queued


def ensure_wei_rejection_reinforcements(state: GameState) -> list[int]:
    """Create the one-time infantry wave, including compatibility for older rejected saves."""
    if not state.flags.get("v12_wei_peace_rejected"):
        return []
    recorded = state.flags.get("v12_wei_rejection_reinforcements")
    if isinstance(recorded, list):
        return [int(army_id) for army_id in recorded if int(army_id) in state.armies]
    created = [_army(state, 2, 0, 1, 77).id for _ in range(5)]
    state.flags["v12_wei_rejection_reinforcements"] = created
    state.add_log("北魏因和议破裂，在洛阳集结五支五千人步兵军。")
    return created


def queue_wei_peace_offer_during_diplomacy(state: GameState) -> bool:
    """Wei sends its one-time Luoyang peace proposal during the AI diplomacy phase."""
    from .events import event_key
    from .story_texts import story_metadata, story_name, story_text

    peace_key = event_key(2)
    peace = state.events.setdefault(peace_key, {})
    if (
        state.flags.get("v12_wei_peace_offer_date")
        or state.flags.get("v12_wei_peace_resolved")
        or state.flags.get("v12_wei_peace_rejected")
        or int(state.regions[13].get("controller", 0)) != 2
        or not state.at_war(1, 2)
    ):
        return False
    peace.update({
        "id": peace_key,
        "name": story_name("事件", 2, "魏窥河南") + "·和议",
        "summary": "魏国占领中原主要城市后，依照事件2向宋廷提出议和。",
        "text": story_text("事件", 2, "魏使抵达宋营，请求两国议和。"),
        "effect_description": story_metadata("事件", 2, "接受则停战；拒绝则魏增派五支步兵军。"),
        "choices": ["接受议和", "拒绝议和"],
        "choice_required": True,
        "triggered": True,
        "story_event_id": 2,
        "peace_offer": True,
    })
    state.flags["v12_wei_peace_offer_date"] = [int(state.year), int(state.month)]
    _queue(state, peace_key)
    state.add_log("北魏在外交阶段遣使议和，要求宋承认洛阳及中原易手。")
    return True


def apply_event_choice(state: GameState, event_id: int, choice: str) -> str:
    from .events import event_key

    if int(event_id) == event_key(2):
        from .story_texts import story_variant

        if choice == "拒绝议和":
            from ...rules.diplomacy import month_index

            state.flags["v12_wei_peace_rejected"] = True
            state.flags["v12_wei_peace_resolved"] = "rejected"
            state.flags["v12_wei_war_expanded"] = True
            state.flags.setdefault("ai_peace_offer_cooldown", {})["2"] = month_index(state) + 4
            ensure_wei_rejection_reinforcements(state)
            state.add_log("宋廷拒绝魏国议和要求，北魏扩大战局，并在洛阳集结五支五千人步兵军。")
            return story_variant("事件", 2, "拒绝和解", "宋廷拒绝魏国议和要求，北魏随即扩大战局。")
        if choice != "接受议和":
            raise ValueError("无效的议和选项")
        from ...rules.diplomacy import make_peace

        state.flags["v12_wei_peace_resolved"] = "accepted"
        result = make_peace(state, 2, {"player_cedes": [13], "_scripted_offer": True})
        return story_variant("事件", 2, "同意和解", "宋魏达成和议。") + "\n\n" + result
    if int(event_id) >= 12200:
        from .events import apply_event_choice as apply_story_choice

        return apply_story_choice(state, event_id, choice)
    raise ValueError("这个1.2事件没有可选分支")
