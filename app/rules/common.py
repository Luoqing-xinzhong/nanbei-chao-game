from __future__ import annotations

from typing import Any

from ..constants import OFFICE_BASE_POWER, OFFICE_NAMES
from ..models import GameState


class RuleError(ValueError):
    """行动不满足规则约束。"""


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def person_power(state: GameState, person: dict[str, Any]) -> float:
    status_factor = {1: 1.0, 2: 0.7, 3: 0.2}.get(int(person.get("status", 0)), 0.0)
    office_power = 0
    for regime in state.regimes.values():
        internal = regime.get("internal", {})
        for office, occupant in internal.items():
            if occupant == person.get("id"):
                office_power = max(office_power, OFFICE_BASE_POWER.get(office, 0))
    if str(state.flags.get("rules_version", "")) == "1.3":
        buildings = state.flags.get("v13_culture", {}).get("buildings", {})
        for region_id, records in buildings.items():
            for building in records:
                if int(building.get("official") or 0) != int(person.get("id", 0)):
                    continue
                school_power = 70 if str(state.regions.get(int(region_id), {}).get("name")) == "扬州" else 50
                office_power = max(office_power, school_power)
    personal_power = max(0, int(person.get("attributes", {}).get("base_power", 0) or 0))
    if int(person.get("level", 0)) < 6:
        personal_power = min(100, personal_power)
    base = personal_power + office_power
    core_power = base * max(0, int(person.get("level", 0))) * status_factor
    from .laws import power_modifier

    return core_power * max(0.0, 1.0 + power_modifier(state, person))


def player_current_office(state: GameState) -> str | None:
    player_id = int(state.player.get("id", 0))
    return next(
        (office for office, occupant in state.player_regime.get("internal", {}).items() if occupant == player_id),
        None,
    )


def check_player_office_authority(state: GameState, target_office: str) -> None:
    """刘裕不能任免基础权力不低于其当前官职的职位。"""
    current = player_current_office(state)
    if current is None:
        return
    current_power = OFFICE_BASE_POWER.get(current, 0)
    target_power = OFFICE_BASE_POWER.get(target_office, 0)
    if target_power >= current_power:
        raise RuleError(
            f"刘裕当前担任{OFFICE_NAMES.get(current, current)}（基础权力{current_power}），"
            f"无权任免基础权力为{target_power}的{OFFICE_NAMES.get(target_office, target_office)}"
        )


def spend_authority(state: GameState, amount: int, apply_law_modifier: bool = True) -> None:
    if apply_law_modifier:
        from .laws import authority_cost_multiplier

        amount *= authority_cost_multiplier(state)
    amount = max(0, int(round(amount)))
    if state.authority < amount:
        raise RuleError(f"权威不足：需要 {amount}，当前 {state.authority}")
    state.authority -= amount


def once_per_turn(state: GameState, key: str) -> None:
    full_key = f"turn:{state.turn_number}:{key}"
    if state.flags.get(full_key):
        raise RuleError("本回合已经执行过该行动")
    state.flags[full_key] = True


def living_regime_people(state: GameState, regime_id: int) -> list[dict[str, Any]]:
    return [
        p for p in state.persons.values()
        if int(p.get("country_id", 0)) == regime_id and int(p.get("status", 0)) in {1, 2, 3}
    ]


def living_commander_id(state: GameState, person_id: int | None) -> int | None:
    """剧情建军只能任命仍然存活的人；编制本身不因将领死亡而取消。"""
    if not person_id:
        return None
    person = state.persons.get(int(person_id))
    if not person or int(person.get("status", 0)) not in {1, 2, 3}:
        return None
    return int(person_id)


def is_regime_eliminated(state: GameState, regime_id: int) -> bool:
    """法理土地清零即视为灭亡。"""
    regime = state.regimes.get(regime_id)
    return regime is None or len(regime.get("regions", [])) == 0


def remove_emperor_civil_offices(state: GameState, regime_id: int) -> list[str]:
    """An emperor cannot simultaneously retain a central civil office or governorship."""
    regime = state.regimes.get(int(regime_id), {})
    internal = regime.get("internal", {})
    emperor = int(internal.get("emperor") or 0)
    if not emperor:
        return []
    removed = []
    for office, holder in list(internal.items()):
        if office != "emperor" and isinstance(holder, (int, str)) and str(holder).isdigit() and int(holder) == emperor:
            internal[office] = None
            removed.append(str(office))
    for region in state.regions.values():
        if int(region.get("governor") or 0) == emperor:
            region["governor"] = None
            removed.append(f"governor:{region.get('id')}")
    return removed
