from __future__ import annotations

import math
import random
from typing import Any

from ..models import GameState
from ..v11 import LAW_CATEGORIES, LAW_LEVELS


# (preferred level, preference strength, explicitly opposed level, opposition strength)
# Strength 2 is 坚决, strength 1 is 大力, and 0 is neutral.
IDEOLOGY_POSITIONS: dict[int, dict[str, tuple[int | None, int, int | None, int]]] = {
    1: {"economy": (1, 2, None, 0), "values": (None, 0, 5, 2), "power": (1, 2, None, 0), "gentry": (1, 2, None, 0), "north": (None, 0, None, 0)},
    2: {"economy": (2, 1, None, 0), "values": (3, 1, None, 0), "power": (1, 1, None, 0), "gentry": (3, 1, None, 0), "north": (None, 0, 5, 1)},
    3: {"economy": (3, 1, None, 0), "values": (3, 1, None, 0), "power": (2, 1, None, 0), "gentry": (None, 0, 1, 1), "north": (None, 0, None, 0)},
    4: {"economy": (None, 0, None, 0), "values": (4, 2, None, 0), "power": (4, 2, None, 0), "gentry": (None, 0, 4, 1), "north": (5, 1, None, 0)},
    5: {"economy": (4, 1, None, 0), "values": (None, 0, None, 0), "power": (5, 2, None, 0), "gentry": (None, 0, 1, 1), "north": (5, 2, None, 0)},
    6: {"economy": (3, 1, None, 0), "values": (3, 2, None, 0), "power": (None, 0, None, 0), "gentry": (2, 1, None, 0), "north": (None, 0, 5, 2)},
    7: {"economy": (1, 2, None, 0), "values": (None, 0, None, 0), "power": (None, 0, 4, 2), "gentry": (2, 1, None, 0), "north": (None, 0, 5, 1)},
    8: {key: (None, 0, None, 0) for key in LAW_CATEGORIES},
    9: {"economy": (None, 0, None, 0), "values": (2, 2, None, 0), "power": (None, 0, 2, 2), "gentry": (2, 1, None, 0), "north": (2, 2, None, 0)},
    10: {"economy": (4, 1, None, 0), "values": (None, 0, None, 0), "power": (2, 2, None, 0), "gentry": (None, 0, 1, 2), "north": (5, 1, None, 0)},
}


def level(state: GameState, category: str) -> int:
    return int(state.laws.get(category, 1))


def available_law_categories(state: GameState) -> dict[str, str]:
    return LAW_CATEGORIES


def law_levels_for(state: GameState, category: str) -> list[str]:
    return LAW_LEVELS[category]


def gentry_militia_loss_rate(state: GameState, regime_id: int) -> float:
    """门阀地位前三档给玩家政权施加每月壮丁流失。"""
    if not is_player_regime(state, regime_id):
        return 0.0
    return {1: 0.30, 2: 0.20, 3: 0.10}.get(level(state, "gentry"), 0.0)


def unlocked_political_commands(state: GameState) -> tuple[str, ...]:
    """Return only the law-gated decrees that are currently available."""
    commands: list[str] = []
    if level(state, "economy") == 2:
        commands.extend(("检籍", "土断"))
    elif level(state, "economy") == 4:
        commands.append("屯田")
    if level(state, "values") == 2:
        commands.append("教化")
    if level(state, "north") in {3, 4, 5}:
        commands.append("动员")
    return tuple(commands)


def is_player_regime(state: GameState, regime_id: int) -> bool:
    return int(regime_id) == state.player_regime_id


def is_at_war(state: GameState, regime_id: int) -> bool:
    return any(int(regime_id) in pair for pair in state.wars)


def family_type(state: GameState, person: dict[str, Any]) -> int | None:
    family = state.families.get(int(person.get("family_id") or 0))
    return int(family.get("family_type")) if family and family.get("family_type") is not None else None


def is_high_family(state: GameState, person: dict[str, Any]) -> bool:
    return family_type(state, person) == 1


def is_humble_family(state: GameState, person: dict[str, Any]) -> bool:
    return family_type(state, person) == 2


def is_emperor(state: GameState, person_id: int) -> bool:
    return any(regime.get("internal", {}).get("emperor") == person_id for regime in state.regimes.values())


def power_modifier(state: GameState, person: dict[str, Any]) -> float:
    """All percentage adjustments stack additively, as required by the design."""
    if int(person.get("country_id", 0)) != state.player_regime_id:
        return 0.0
    modifier = 0.0
    power_law = level(state, "power")
    if power_law == 1 and is_high_family(state, person):
        modifier += 0.50
    elif power_law == 2 and is_humble_family(state, person):
        modifier += 0.50
    elif power_law == 3 and not is_emperor(state, int(person["id"])) and int(person.get("level", 0)) >= 5:
        modifier += 1.00
    elif power_law == 4:
        modifier += 1.50 if is_emperor(state, int(person["id"])) else -0.20
    elif power_law == 5 and is_emperor(state, int(person["id"])):
        modifier -= 0.30

    if is_high_family(state, person):
        modifier += {1: 0.50, 2: 0.30, 3: 0.10}.get(level(state, "gentry"), 0.0)
    return modifier


def family_land_power(state: GameState, family_id: int) -> float:
    coefficient = {1: 1.2, 2: 1.0, 3: 0.8, 4: 0.8, 5: 0.0}[level(state, "economy")]
    land = sum(
        1
        for region in owned_player_regions(state)
        for owner in region.get("land_ownership", [])
        if int(owner) == int(family_id)
    )
    return land * coefficient


def adjust_person_opinion(state: GameState, person: dict[str, Any], delta: int) -> int:
    if delta > 0 and level(state, "power") == 2 and is_high_family(state, person):
        family = state.families.get(int(person.get("family_id") or 0), {})
        if int(family.get("leader") or 0) == int(person.get("id", 0)):
            delta = int(round(delta * 0.5))
    person["opinion_of_player"] = max(-100, min(100, int(person.get("opinion_of_player", 0)) + delta))
    return int(person["opinion_of_player"])


def legislative_stance(state: GameState, person: dict[str, Any], category: str, target_level: int) -> int:
    # 税率法律沿用人物对“经济基础”的意识形态取向。
    position_category = "economy" if category == "tax" else category
    position = IDEOLOGY_POSITIONS.get(int(person.get("ideology", 8)), IDEOLOGY_POSITIONS[8])[position_category]
    preferred, support_strength, opposed, oppose_strength = position
    current = level(state, category)
    if opposed == target_level:
        return -oppose_strength
    if preferred is None:
        return 0
    if target_level == preferred:
        return support_strength
    if current == preferred:
        return -support_strength

    current_side = -1 if current < preferred else 1
    target_side = -1 if target_level < preferred else 1
    if current_side != target_side:
        # A proposal that leaps over the person's ideal point is regarded as
        # an extreme overcorrection, even when its numeric distance is small.
        return -2
    current_distance = abs(current - preferred)
    target_distance = abs(target_level - preferred)
    if target_distance < current_distance:
        return support_strength
    if target_distance > current_distance:
        return -support_strength
    return 0


def _legislative_weight(state: GameState, person: dict[str, Any]) -> float:
    from .common import person_power

    weight = person_power(state, person)
    if level(state, "power") == 1 and is_high_family(state, person):
        weight *= 2
    elif level(state, "power") == 3 and not is_emperor(state, int(person["id"])) and int(person.get("level", 0)) >= 5:
        weight *= 4
    return weight


def top_legislators(state: GameState) -> list[dict[str, Any]]:
    people = [
        person for person in state.persons.values()
        if int(person.get("country_id", 0)) == state.player_regime_id and int(person.get("status", 0)) in {1, 2, 3}
    ]
    return sorted(people, key=lambda person: (-_legislative_weight(state, person), int(person["id"])))[:5]


def _supports_proposal(person: dict[str, Any], stance: int) -> bool:
    opinion = int(person.get("opinion_of_player", 0))
    if stance >= 2:
        return True
    if stance <= -2:
        return False
    if stance == 1:
        return opinion > -50
    if stance == -1:
        return opinion >= 50
    return opinion >= 0


def collect_legislative_votes(state: GameState, category: str, target_level: int) -> tuple[list[dict[str, Any]], float, float]:
    votes: list[dict[str, Any]] = []
    support = 0.0
    oppose = 0.0
    for person in top_legislators(state):
        stance = legislative_stance(state, person, category, target_level)
        agrees = _supports_proposal(person, stance)
        weight = _legislative_weight(state, person)
        if agrees:
            support += weight
        else:
            oppose += weight
        votes.append({"person_id": int(person["id"]), "support": agrees, "power": round(weight, 2), "stance": stance})
    return votes, support, oppose


def propose_legislation(state: GameState, category: str, target_level: int) -> str:
    from .common import RuleError

    categories = available_law_categories(state)
    if category not in categories or target_level not in range(1, 6):
        raise RuleError("法律提案无效")
    if target_level == level(state, category):
        raise RuleError("该法律已经生效")
    if state.legislation:
        raise RuleError("同一时间只能推进一项立法")
    if category == "values" and target_level == 5:
        raise RuleError("“南国魂”在1.1版本中锁定，暂时不能立法")
    if category == "power" and target_level == 3:
        eligible = [p for p in top_legislators(state) if not is_emperor(state, int(p["id"])) and int(p.get("level", 0)) >= 5]
        if not eligible:
            raise RuleError("实行权臣政治需要至少一名5级非皇帝权臣")

    votes, support, oppose = collect_legislative_votes(state, category, target_level)

    details = "；".join(
        f"{state.person_name(v['person_id'])}{'赞成' if v['support'] else '反对'}({v['power']:g})" for v in votes
    )
    if support <= oppose:
        message = f"立法投票未通过：赞成权力 {support:g}，反对权力 {oppose:g}。{details}"
        state.add_log(message)
        return message
    if str(state.flags.get("rules_version", "")) == "1.3":
        from ..content.v1_3.culture import spend_culture

        spend_culture(state, abs(int(target_level) - level(state, category)) * 20, "制定法律")
    state.legislation = {
        "category": category,
        "target_level": int(target_level),
        "progress": 0,
        "started_turn": state.turn_number,
        "votes": votes,
    }
    message = (
        f"立法投票通过：拟将{categories[category]}改为“{law_levels_for(state, category)[target_level - 1]}”；"
        f"赞成权力 {support:g}，反对权力 {oppose:g}。{details}"
    )
    state.add_log(message)
    return message


def force_legislation(state: GameState, category: str, target_level: int) -> str:
    from .common import RuleError, spend_authority

    if level(state, "power") != 4:
        raise RuleError("只有无上皇权可以强行通过立法投票")
    if category not in available_law_categories(state) or target_level not in range(1, 6):
        raise RuleError("法律提案无效")
    if target_level == level(state, category):
        raise RuleError("该法律已经生效")
    if state.legislation:
        raise RuleError("同一时间只能推进一项立法")
    if category == "values" and target_level == 5:
        raise RuleError("“南国魂”在1.1版本中锁定，暂时不能立法")
    votes, support, oppose = collect_legislative_votes(state, category, target_level)
    authority_cost = max(100, int(math.ceil(oppose / 10.0)))
    spend_authority(state, authority_cost)
    if str(state.flags.get("rules_version", "")) == "1.3":
        from ..content.v1_3.culture import spend_culture

        spend_culture(state, abs(int(target_level) - level(state, category)) * 20, "制定法律")
    loses_stability = level(state, "values") != 5
    if loses_stability:
        state.player_regime["stability"] = max(0, int(state.player_regime.get("stability", 0)) - 30)
    state.legislation = {
        "category": category,
        "target_level": int(target_level),
        "progress": 0,
        "started_turn": state.turn_number,
        "votes": votes,
        "forced": True,
    }
    message = (
        f"以皇权强行通过“{law_levels_for(state, category)[target_level - 1]}”的立法投票："
        f"反对权力{oppose:g}，基础权威代价{authority_cost}，"
        + ("稳定度下降30。" if loses_stability else "南国魂免除稳定度损失。")
    )
    state.add_log(message)
    return message


def cancel_legislation(state: GameState) -> str:
    """Withdraw the active bill; a later attempt must vote and progress from zero."""
    from .common import RuleError

    if state.phase_index != 0:
        raise RuleError("只能在政治阶段取消立法")
    if not state.legislation:
        raise RuleError("当前没有正在推进的立法")
    category = str(state.legislation.get("category", ""))
    target = int(state.legislation.get("target_level", 1))
    try:
        name = law_levels_for(state, category)[target - 1]
    except KeyError:
        name = "未知法律"
    state.legislation = {}
    state.player_regime["stability"] = max(0, int(state.player_regime.get("stability", 0)) - 5)
    message = f"已取消“{name}”立法，全部进度与投票结果清零，稳定度-5。"
    state.add_log(message)
    return message


def settle_legislation(state: GameState) -> str | None:
    if not state.legislation or int(state.legislation.get("progress", 0)) >= 100:
        return None
    if state.authority < 100:
        message = "立法因权威不足100而暂停，本回合没有推进。"
        state.add_log(message)
        return message
    state.authority -= 100
    state.legislation["progress"] = min(100, int(state.legislation.get("progress", 0)) + 25)
    message = f"结算阶段消耗100权威，立法进度推进至{state.legislation['progress']}%。"
    state.add_log(message)
    return message


def enact_ready_legislation(state: GameState) -> str | None:
    if not state.legislation or int(state.legislation.get("progress", 0)) < 100:
        return None
    category = str(state.legislation["category"])
    target = int(state.legislation["target_level"])
    opinion_stances = {
        int(person["id"]): legislative_stance(state, person, category, target)
        for person in state.persons.values()
        if int(person.get("country_id", 0)) == state.player_regime_id and int(person.get("status", 0)) in {1, 2, 3}
    }
    state.laws[category] = target
    changes = {2: 30, 1: 10, -1: -10, -2: -30}
    for person in state.persons.values():
        if int(person.get("country_id", 0)) != state.player_regime_id or int(person.get("status", 0)) not in {1, 2, 3}:
            continue
        stance = opinion_stances.get(int(person["id"]), 0)
        delta = changes.get(stance, 0)
        if delta:
            person["opinion_of_player"] = max(-100, min(100, int(person.get("opinion_of_player", 0)) + delta))
    apply_immediate_effect(state, category, target)
    name = law_levels_for(state, category)[target - 1]
    state.legislation = {}
    message = f"新法“{name}”在回合开始时正式生效。"
    state.add_log(message)
    return message


def owned_player_regions(state: GameState) -> list[dict[str, Any]]:
    names = set(state.player_regime.get("regions", []))
    return [region for region in state.regions.values() if region.get("name") in names]


def _replace_land(region: dict[str, Any], source_predicate, count: int, new_owner) -> int:
    changed = 0
    land = region.get("land_ownership", [])
    for index, owner in enumerate(land):
        if changed >= count:
            break
        if source_predicate(int(owner)):
            land[index] = new_owner(changed) if callable(new_owner) else new_owner
            changed += 1
    return changed


def enforce_family_land_cap(state: GameState) -> None:
    cap = {1: 0.80, 2: 0.60, 3: 0.30, 4: 0.30, 5: 0.0}[level(state, "economy")]
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import region_economy

        for region in owned_player_regions(state):
            land = region_economy(state, int(region["id"]))["land"]
            total = sum(max(0, int(value)) for value in land.values())
            excess = max(0, int(land.get("gentry", 0)) - math.floor(total * cap))
            land["gentry"] -= excess
            land["smallholder"] += (excess + 1) // 2
            land["self_farm"] += excess // 2
        return
    family_ids = set(state.families)
    for region in owned_player_regions(state):
        land = region.get("land_ownership", [])
        maximum = math.floor(len(land) * cap)
        family_count = sum(1 for owner in land if int(owner) in family_ids)
        excess = max(0, family_count - maximum)
        _replace_land(region, lambda owner: owner in family_ids, excess, lambda i: 1 if i % 2 == 0 else 2)


def apply_immediate_effect(state: GameState, category: str, target: int) -> None:
    if category == "economy":
        enforce_family_land_cap(state)
        if target == 5:
            for region in owned_player_regions(state):
                _replace_land(region, lambda owner: owner in state.families, len(region.get("land_ownership", [])), lambda i: 1 if i % 2 == 0 else 2)
    elif category == "gentry" and target == 5:
        dissolved = {fid for fid, family in state.families.items() if int(family.get("family_type", -1)) == 1}
        for person in state.persons.values():
            if int(person.get("family_id") or 0) in dissolved:
                person["family_id"] = 0
        for family_id in dissolved:
            state.families.pop(family_id, None)


def _annex_land(state: GameState, destination: int | list[int]) -> None:
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import region_economy

        if isinstance(destination, list):
            if not destination:
                return
            target_key = "gentry"
        else:
            target_key = "smallholder" if destination == 1 else "self_farm"
        for region in owned_player_regions(state):
            land = region_economy(state, int(region["id"]))["land"]
            total = sum(max(0, int(value)) for value in land.values())
            amount = max(1, math.ceil(total * 0.01)) if total else 0
            moved = 0
            for source in ("self_farm", "smallholder", "gentry"):
                if source == target_key or moved >= amount:
                    continue
                transfer = min(int(land.get(source, 0)), amount - moved)
                land[source] -= transfer
                land[target_key] += transfer
                moved += transfer
        return
    for region in owned_player_regions(state):
        land = region.get("land_ownership", [])
        amount = max(1, math.ceil(len(land) * 0.01)) if land else 0
        destinations = destination if isinstance(destination, list) else [destination]
        if not destinations:
            continue
        _replace_land(
            region,
            lambda owner: owner not in destinations,
            amount,
            lambda i: destinations[i % len(destinations)],
        )


def apply_monthly_effects(state: GameState) -> None:
    regime = state.player_regime
    stability_delta = 0
    if level(state, "economy") == 5:
        stability_delta += 2
    values_law = level(state, "values")
    stability_delta += {1: -1, 4: 1, 5: 2}.get(values_law, 0)
    stability_delta += {3: -1, 5: -2}.get(level(state, "power"), 0)
    regime["stability"] = int(regime.get("stability", 0)) + stability_delta
    if values_law == 1:
        regime["stability"] = min(regime["stability"], 50)
    elif values_law == 2:
        regime["stability"] = min(regime["stability"], 70)
    elif values_law == 5:
        regime["stability"] = 100 if is_at_war(state, state.player_regime_id) else max(80, regime["stability"])
    regime["stability"] = max(0, min(100, regime["stability"]))

    north_law = level(state, "north")
    support_gain = {4: 1, 5: 2}.get(north_law, 0)
    if values_law == 5 and is_at_war(state, state.player_regime_id):
        support_gain += 2
    regime["war_support"] = int(regime.get("war_support", 0)) + support_gain
    if north_law == 1:
        regime["war_support"] = min(50, regime["war_support"])
    elif north_law == 5:
        regime["war_support"] = max(80, regime["war_support"])
    regime["war_support"] = max(0, min(100, regime["war_support"]))

    power_law = level(state, "power")
    if power_law == 1:
        high_families = [
            fid for fid, family in state.families.items()
            if int(family.get("family_type", -1)) == 1
            and int(state.persons.get(int(family.get("leader") or 0), {}).get("country_id", 0)) == state.player_regime_id
        ]
        _annex_land(state, high_families)
    elif power_law == 2:
        _annex_land(state, 1)
    elif power_law == 4:
        _annex_land(state, 0)
    enforce_family_land_cap(state)

    tax_stability = {1: 10, 2: 5, 3: 0, 4: -5, 5: -10}.get(level(state, "tax"), 0)
    if tax_stability:
        owned_names = set(state.player_regime.get("regions", []))
        for region in state.regions.values():
            if (
                region.get("name") in owned_names
                and int(region.get("controller", 0)) == state.player_regime_id
            ):
                current = int(region.get("local_stability", region.get("prosperity", 5) * 10))
                region["local_stability"] = max(0, min(100, current + tax_stability))
                economy = state.flags.get("v12_economy", {}).get("regions", {}).get(str(region["id"]))
                if economy is not None:
                    economy["stability"] = region["local_stability"]

    if values_law == 5:
        for person in state.persons.values():
            if (
                int(person.get("country_id", 0)) == state.player_regime_id
                and int(person.get("status", 0)) in {1, 2, 3}
                and not person.get("is_player")
                and not is_emperor(state, int(person["id"]))
                and int(person.get("opinion_of_player", 0)) < 0
                and int(person.get("attributes", {}).get("stain", 0)) > 80
            ):
                person["status"] = 5
                state.add_log(f"{state.person_name(int(person['id']))}自知污名深重，退出朝堂。")

    if level(state, "gentry") in {1, 2}:
        appointed = {
            int(value) for value in state.player_regime.get("internal", {}).values()
            if isinstance(value, int)
        }
        candidates = [
            person for person in state.persons.values()
            if int(person.get("country_id", 0)) == state.player_regime_id
            and int(person.get("status", 0)) == 1
            and is_high_family(state, person)
            and int(person["id"]) not in appointed
        ]
        if candidates:
            candidate = max(candidates, key=lambda person: int(person.get("attributes", {}).get("intelligence", 0)))
            recommendations = state.flags.setdefault("gentry_recommendations", [])
            if int(candidate["id"]) not in recommendations:
                recommendations.append(int(candidate["id"]))
                state.add_log(f"高门向朝中举荐{state.person_name(int(candidate['id']))}。")


def family_tax_rate(state: GameState, regime_id: int) -> float:
    if not is_player_regime(state, regime_id):
        return 0.5
    return {1: 0.2, 2: 0.4, 3: 0.5, 4: 0.5, 5: 0.5}[level(state, "economy")]


def income_multiplier(state: GameState, regime_id: int) -> float:
    if is_player_regime(state, regime_id) and level(state, "values") == 5 and is_at_war(state, regime_id):
        return 1.20
    return 1.0


def authority_cost_multiplier(state: GameState) -> float:
    values_law = level(state, "values")
    if values_law == 5:
        values_modifier = -0.70 if is_at_war(state, state.player_regime_id) else -0.50
    else:
        values_modifier = {3: -0.20, 4: -0.30}.get(values_law, 0.0)
    power_modifier_value = {3: 0.20, 4: -0.20}.get(level(state, "power"), 0.0)
    return max(0.10, 1.0 + values_modifier + power_modifier_value)


def check_command_rejection(
    state: GameState,
    command_key: str,
    rng: random.Random | None = None,
) -> None:
    from .common import RuleError

    rejected_key = f"turn:{state.turn_number}:rejected_command:{command_key}"
    if state.flags.get(rejected_key):
        raise RuleError("这道政令本回合已经被驳斥，不能再次执行")
    if int(state.laws.get("power", 0)) == 1 and (rng or random).random() < 0.20:
        state.flags[rejected_key] = True
        raise RuleError("门阀政治下朝臣驳回了这道政令，本次没有消耗资源；本回合不能再次执行")


def militia_multiplier(state: GameState, regime_id: int) -> float:
    if not is_player_regime(state, regime_id):
        return 1.0
    modifier = {3: 0.20, 4: 0.20, 5: 0.30}.get(level(state, "north"), 0.0)
    region_bonus = sum(float(region.get("conscription_bonus", 0.0)) for region in owned_player_regions(state))
    return 1.0 + modifier + region_bonus


def military_pay_multiplier(state: GameState, regime_id: int) -> float:
    return 1.10 if is_player_regime(state, regime_id) and level(state, "north") == 5 else 1.0


def army_battalion_cap(state: GameState, regime_id: int) -> int | None:
    if not is_player_regime(state, regime_id):
        return None
    return {1: 75, 2: 150, 3: 300}.get(level(state, "north"))


def combat_modifier(state: GameState, regime_id: int, offensive: bool, city_id: int) -> float:
    modifier = 0.0
    if is_player_regime(state, regime_id):
        if str(state.flags.get("rules_version", "")) == "1.3":
            from ..content.v1_3.culture import completed_poetry_nodes

            if 7 in completed_poetry_nodes(state):
                modifier -= 0.20
        if level(state, "power") == 5:
            modifier += 0.20
        north_law = level(state, "north")
        modifier += {1: -0.10, 4: 0.20, 5: 0.30}.get(north_law, 0.0)
        if north_law == 3:
            modifier += -0.20 if offensive else 0.20
    elif level(state, "values") == 5:
        city = state.cities.get(city_id, {})
        region = state.regions.get(int(city.get("region_id", 0)), {})
        if region.get("name") in set(state.player_regime.get("regions", [])):
            modifier -= 0.50
    return max(-0.90, modifier)


def war_support_loss(state: GameState, regime_id: int, amount: int) -> int:
    if is_player_regime(state, regime_id) and level(state, "north") == 1:
        return int(math.ceil(amount * 1.5))
    return int(amount)


def execute_stain_threshold(state: GameState) -> int:
    return {1: 1, 2: 50, 3: 80, 4: 100, 5: 80}[level(state, "values")]


def intrigue_success_modifier(state: GameState) -> float:
    return 0.20 if level(state, "values") == 1 else 0.0


def intrigue_action_allowed(state: GameState, action: str) -> bool:
    values_law = level(state, "values")
    if values_law == 3 and action == "刺杀":
        return False
    if values_law == 4 and action in {"威胁", "诬陷", "刺杀"}:
        return False
    if values_law == 5 and action in {"打压", "威胁", "诬陷", "刺杀"}:
        return False
    return True


def high_family_commander(state: GameState, regime_id: int) -> int | None:
    if not is_player_regime(state, regime_id) or level(state, "gentry") != 1:
        return None
    candidates = [
        person for person in state.persons.values()
        if int(person.get("country_id", 0)) == regime_id and int(person.get("status", 0)) == 1
        and is_high_family(state, person)
        and not any(army.commander == person["id"] for army in state.armies.values())
    ]
    if not candidates:
        return None
    from .common import person_power

    return int(max(candidates, key=lambda person: person_power(state, person))["id"])


def can_dismiss_high_family(state: GameState, person: dict[str, Any]) -> bool:
    return not (is_high_family(state, person) and level(state, "gentry") in {1, 2})


def dismissal_cost(state: GameState, person: dict[str, Any], base: int = 100) -> int:
    if is_high_family(state, person) and level(state, "gentry") == 3:
        return base * 2
    return base


def household_registration(state: GameState) -> str:
    from .common import RuleError, once_per_turn, spend_authority

    if level(state, "economy") != 2:
        raise RuleError("只有检籍土断制度可以执行检籍")
    check_command_rejection(state, "household_registration")
    once_per_turn(state, "household_registration")
    spend_authority(state, 100)
    from .national_modifiers import national_modifier_total

    effect_rate = 0.05 * (1.0 + national_modifier_total(state, "land_policy_effect"))
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import region_economy

        released = 0
        for region in owned_player_regions(state):
            land = region_economy(state, int(region["id"]))["land"]
            amount = min(int(land.get("gentry", 0)), math.ceil(int(land.get("gentry", 0)) * effect_rate))
            land["gentry"] -= amount
            land["self_farm"] += amount
            released += amount
        for family in state.families.values():
            if int(family.get("family_type", -1)) != 1:
                continue
            leader = state.persons.get(int(family.get("leader") or 0))
            if leader and int(leader.get("country_id", 0)) == state.player_regime_id:
                leader["opinion_of_player"] = max(-100, int(leader.get("opinion_of_player", 0)) - 2)
        message = f"完成检籍：门阀共释放{released}份土地给自耕农。"
        state.add_log(message)
        return message
    released = 0
    for family_id, family in state.families.items():
        family_released = 0
        for region in owned_player_regions(state):
            owned = sum(1 for owner in region.get("land_ownership", []) if int(owner) == family_id)
            amount = math.ceil(owned * effect_rate)
            family_released += _replace_land(region, lambda owner, fid=family_id: owner == fid, amount, 2)
        if family_released:
            released += family_released
            leader = state.persons.get(int(family.get("leader") or 0))
            if leader:
                leader["opinion_of_player"] = max(-100, int(leader.get("opinion_of_player", 0)) - 2)
    message = f"完成检籍：世家共释放{released}份土地给自耕农。"
    state.add_log(message)
    return message


def land_investigation(state: GameState, family_id: int) -> str:
    from .common import RuleError, once_per_turn, spend_authority

    if level(state, "economy") != 2:
        raise RuleError("只有检籍土断制度可以执行土断")
    family = state.families.get(family_id)
    if not family:
        raise RuleError("目标家族不存在")
    check_command_rejection(state, "land_investigation")
    once_per_turn(state, "land_investigation")
    yearly_key = f"land_investigation:{state.year}:{family_id}"
    if state.flags.get(yearly_key):
        raise RuleError("该家族本年已经接受过土断")
    spend_authority(state, 300)
    from .national_modifiers import national_modifier_total

    effect_rate = 0.15 * (1.0 + national_modifier_total(state, "land_policy_effect"))
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import region_economy

        surrendered = 0
        for region in owned_player_regions(state):
            land = region_economy(state, int(region["id"]))["land"]
            amount = min(int(land.get("gentry", 0)), math.ceil(int(land.get("gentry", 0)) * effect_rate))
            land["gentry"] -= amount
            land["self_farm"] += amount
            surrendered += amount
        state.flags[yearly_key] = True
        leader = state.persons.get(int(family.get("leader") or 0))
        if leader:
            leader["opinion_of_player"] = max(-100, int(leader.get("opinion_of_player", 0)) - 30)
        message = f"对{family.get('name', family_id)}实施土断，其家主好感-30；全体门阀合计释放{surrendered}份土地给自耕农。"
        state.add_log(message)
        return message
    surrendered = 0
    for region in owned_player_regions(state):
        owned = sum(1 for owner in region.get("land_ownership", []) if int(owner) == family_id)
        surrendered += _replace_land(region, lambda owner: owner == family_id, math.ceil(owned * effect_rate), 0)
    state.flags[yearly_key] = True
    leader = state.persons.get(int(family.get("leader") or 0))
    if leader:
        leader["opinion_of_player"] = max(-100, int(leader.get("opinion_of_player", 0)) - 30)
    message = f"对{family.get('name', family_id)}实施土断，收归中央土地{surrendered}份。"
    state.add_log(message)
    return message


def tuntian(state: GameState, region_id: int) -> str:
    from .common import RuleError, spend_authority

    if level(state, "economy") != 4:
        raise RuleError("只有屯田制度可以执行屯田政令")
    region = state.regions.get(region_id)
    if not region or region not in owned_player_regions(state):
        raise RuleError("只能在本国地区屯田")
    check_command_rejection(state, "tuntian")
    spend_authority(state, 100)
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import region_economy

        land = region_economy(state, region_id)["land"]
        amount = math.ceil(sum(max(0, int(value)) for value in land.values()) * 0.05)
        gained = 0
        for source in ("gentry", "smallholder"):
            transfer = min(int(land.get(source, 0)), amount - gained)
            land[source] -= transfer
            land["self_farm"] += transfer
            gained += transfer
            if gained >= amount:
                break
        region["conscription_bonus"] = float(region.get("conscription_bonus", 0.0)) + 0.05
        message = f"在{region['name']}实行屯田，整理{gained}份门阀或小地主土地为自耕屯田，该地区征兵率提高5%。"
        state.add_log(message)
        return message
    amount = math.ceil(len(region.get("land_ownership", [])) * 0.05)
    gained = _replace_land(region, lambda owner: owner != 0, amount, 0)
    region["conscription_bonus"] = float(region.get("conscription_bonus", 0.0)) + 0.05
    message = f"在{region['name']}实行屯田，中央获得{gained}份土地，该地区征兵率提高5%。"
    state.add_log(message)
    return message


def education(state: GameState, person_id: int) -> str:
    from .common import RuleError, once_per_turn, spend_authority

    if level(state, "values") != 2:
        raise RuleError("只有礼法价值观可以执行教化")
    person = state.persons.get(person_id)
    if not person or int(person.get("country_id", 0)) != state.player_regime_id or int(person.get("status", 0)) != 1:
        raise RuleError("教化官员无效")
    if int(state.flags.get(f"education_cooldown:{person_id}", 0)) > state.turn_number:
        raise RuleError("这名官员仍在五回合教化冷却中")
    check_command_rejection(state, "education")
    once_per_turn(state, "education")
    spend_authority(state, 100)
    intelligence = int(person.get("attributes", {}).get("intelligence", 0))
    gain = max(1, min(5, math.ceil(intelligence / 20)))
    state.player_regime["stability"] = min(70, int(state.player_regime.get("stability", 0)) + gain)
    state.flags[f"education_cooldown:{person_id}"] = state.turn_number + 5
    message = f"{state.person_name(person_id)}主持礼乐教化，稳定度提高{gain}。"
    state.add_log(message)
    return message


def mobilization(state: GameState, person_id: int) -> str:
    """由在职官员主持动员；规则与教化相同，但提高战争支持度。"""
    from .common import RuleError, once_per_turn, spend_authority

    if level(state, "north") not in {3, 4, 5}:
        raise RuleError("只有第3、4、5级对北态度法律可以执行动员")
    person = state.persons.get(person_id)
    if not person or int(person.get("country_id", 0)) != state.player_regime_id or int(person.get("status", 0)) != 1:
        raise RuleError("动员官员无效")
    officials = {
        int(value)
        for value in state.player_regime.get("internal", {}).values()
        if isinstance(value, int)
    }
    if person_id not in officials:
        raise RuleError("只能选择在职官员主持动员")
    if int(state.flags.get(f"mobilization_cooldown:{person_id}", 0)) > state.turn_number:
        raise RuleError("这名官员仍在五回合动员冷却中")
    check_command_rejection(state, "mobilization")
    once_per_turn(state, "mobilization")
    spend_authority(state, 100)
    intelligence = int(person.get("attributes", {}).get("intelligence", 0))
    gain = max(1, min(5, math.ceil(intelligence / 20)))
    regime = state.player_regime
    regime["war_support"] = min(100, int(regime.get("war_support", 0)) + gain)
    state.flags[f"mobilization_cooldown:{person_id}"] = state.turn_number + 5
    message = f"{state.person_name(person_id)}主持战争动员，战争支持度提高{gain}。"
    state.add_log(message)
    return message
