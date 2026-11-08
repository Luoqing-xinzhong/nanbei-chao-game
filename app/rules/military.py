from __future__ import annotations

import math
import random

from ..models import Army, GameState
from .common import RuleError, clamp
from .military_modifiers import evaluate_battle_modifiers, modifier_effect_total
from .laws import army_battalion_cap, combat_modifier, high_family_commander, is_high_family, level
from .ai_modifiers import commander_combat_bonus

ATTACK_COEFFICIENT = {1: 2.0, 2: 3.0, 3: 4.0, 4: 4.0, 5: 3.0, 6: 2.0}
DEFENSE_COEFFICIENT = {1: 1.0, 2: 0.8, 3: 0.5, 4: 0.5, 5: 0.8, 6: 1.0}


def sync_commander_location(state: GameState, army: Army) -> None:
    if army.commander in state.persons:
        state.persons[army.commander]["location_id"] = army.location_id
        if int(army.commander) == int(state.player["id"]):
            from ..content.v1_1.events_4 import resolve_special_coup_if_player_returns

            resolve_special_coup_if_player_returns(state)


def sync_all_commander_locations(state: GameState) -> None:
    for army in state.armies.values():
        sync_commander_location(state, army)


def city_controller(state: GameState, city_id: int) -> int:
    city = state.cities.get(city_id)
    if not city:
        return 0
    region = state.regions.get(int(city.get("region_id", 0)))
    return int(region.get("controller", 0)) if region else 0


def occupy_capital_if_applicable(state: GameState, army: Army) -> str | None:
    """交战军队进入地区首府时，立即转移该地区的实际控制权。"""
    city = state.cities.get(army.location_id)
    if not city or not city.get("capital"):
        return None
    region = state.regions.get(int(city.get("region_id", 0)))
    if not region:
        return None
    previous = int(region.get("controller", 0))
    if previous in {0, army.regime_id} or not state.at_war(army.regime_id, previous):
        return None
    region["controller"] = army.regime_id
    if str(state.flags.get("rules_version", "")) == "1.3":
        from ..content.v1_3.culture import on_region_control_changed

        on_region_control_changed(state, int(region["id"]), previous, army.regime_id)
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import lock_ai_region_control

        lock_ai_region_control(state, int(region["id"]), army.regime_id)
        state.flags.setdefault("v12_region_captures", {})[str(int(region["id"]))] = {
            "region_id": int(region["id"]),
            "regime_id": int(army.regime_id),
            "previous_controller": previous,
            "month": int(state.year) * 12 + int(state.month),
        }
        from .diplomacy import mark_ai_total_occupation

        mark_ai_total_occupation(state, army.regime_id, previous)
        for war in state.wars:
            if army.regime_id not in war:
                continue
            opponent = int(war[0]) if int(war[1]) == army.regime_id else int(war[1])
            if opponent != previous:
                mark_ai_total_occupation(state, army.regime_id, opponent)
    message = f"军队#{army.id}控制{city['name']}，{region['name']}全境转由{state.regimes[army.regime_id]['name']}控制。"
    state.add_log(message)
    return message


def routes_between(state: GameState, left: int, right: int) -> list[dict]:
    return [
        road for road in state.roads
        if {int(road["from"]), int(road["to"])} == {int(left), int(right)}
    ]


def neighbors(state: GameState, city_id: int) -> list[tuple[int, dict]]:
    result = []
    for road in state.roads:
        if int(road["from"]) == city_id:
            result.append((int(road["to"]), road))
        elif int(road["to"]) == city_id:
            result.append((int(road["from"]), road))
    return result


def effective_road_type(state: GameState, road: dict) -> int:
    """Frozen 1.2 waterways temporarily behave exactly like ordinary land roads."""
    road_type = int(road.get("type", 1))
    if road_type == 3 and str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.climate import is_frozen_water_road

        if is_frozen_water_road(state, road):
            return 1
    return road_type


def route_cost(army: Army, road_type: int) -> float | None:
    if army.army_type == 1:
        return {3: 0.3, 4: 0.5}.get(road_type)
    if army.pure_cavalry:
        return {1: 1.0, 2: 2.0, 3: 0.6, 4: 1.0}.get(road_type)
    return {1: 1.0, 2: 1.0, 3: 0.3, 4: 0.5}.get(road_type)


def legal_moves(state: GameState, army_id: int) -> list[tuple[int, int, float]]:
    army = state.armies[army_id]
    # 同一对城市可能同时存在陆路和水路；每个目标只保留当前军队消耗最低的路线。
    best_by_target: dict[int, tuple[int, int, float]] = {}
    for target, road in neighbors(state, army.location_id):
        road_type = effective_road_type(state, road)
        cost = route_cost(army, road_type)
        if cost is None or cost > army.action_points:
            continue
        controller = city_controller(state, target)
        enemies = [a for a in state.armies.values() if a.location_id == target and a.regime_id != army.regime_id]
        if enemies:
            continue
        if controller in {0, army.regime_id} or state.at_war(army.regime_id, controller):
            candidate = (target, road_type, cost)
            current = best_by_target.get(target)
            if current is None or (candidate[2], candidate[1]) < (current[2], current[1]):
                best_by_target[target] = candidate
    return list(best_by_target.values())


def legal_march_routes(state: GameState, army_id: int, max_steps: int = 3) -> list[tuple[tuple[int, ...], float]]:
    """Find useful destinations whose shortest currently legal route is two or three steps."""
    army = state.armies[army_id]
    max_steps = max(2, min(3, int(max_steps)))
    found: dict[int, list[tuple[tuple[int, ...], float]]] = {}

    def visit(city_id: int, path: tuple[int, ...], spent: float) -> None:
        if len(path) >= max_steps:
            return
        for target, road in neighbors(state, city_id):
            if target == army.location_id or target in path:
                continue
            cost = route_cost(army, effective_road_type(state, road))
            total = round(spent + (cost or 0), 2)
            if cost is None or total > army.action_points + 1e-9:
                continue
            controller = city_controller(state, target)
            enemies = [a for a in state.armies.values() if a.location_id == target and a.regime_id != army.regime_id]
            if enemies or not (controller in {0, army.regime_id} or state.at_war(army.regime_id, controller)):
                continue
            new_path = path + (target,)
            found.setdefault(target, []).append((new_path, total))
            visit(target, new_path, total)

    visit(army.location_id, (), 0.0)
    routes: list[tuple[tuple[int, ...], float]] = []
    for candidates in found.values():
        shortest_steps = min(len(path) for path, _cost in candidates)
        if shortest_steps < 2:
            continue
        best = min(
            (candidate for candidate in candidates if len(candidate[0]) == shortest_steps),
            key=lambda candidate: (candidate[1], candidate[0]),
        )
        routes.append(best)
    return sorted(routes, key=lambda item: (-len(item[0]), item[1], item[0][-1]))


def legal_attacks(state: GameState, army_id: int) -> list[tuple[int, int]]:
    army = state.armies[army_id]
    if army.action_points <= 0:
        return []
    result: list[tuple[int, int]] = []
    for target, road in neighbors(state, army.location_id):
        road_type = effective_road_type(state, road)
        allowed = road_type in ({3, 4} if army.army_type == 1 else {1, 2, 3})
        if not allowed:
            continue
        enemy_armies = [a for a in state.armies.values() if a.location_id == target and a.regime_id != army.regime_id]
        if enemy_armies and any(state.at_war(army.regime_id, a.regime_id) for a in enemy_armies):
            result.append((target, road_type))
    return list(dict.fromkeys(result))


def create_army(
    state: GameState,
    regime_id: int,
    city_id: int,
    army_type: int,
    battalions: dict[int, int],
    *,
    recruitment_cost_multiplier: float = 1.0,
) -> Army:
    regime = state.regimes[regime_id]
    if regime_id == state.player_regime_id and int(battalions.get(2, 0)) > 0:
        from .national_modifiers import national_modifier_total

        if national_modifier_total(state, "cavalry_recruitment_disabled") >= 1:
            raise RuleError("国家修正“马政不振”生效：主控政权不能招募骑兵")
    capital = int(regime.get("capital") or 0)
    if city_id != capital:
        raise RuleError(f"军队只能在首都{state.city_name(capital)}组建")
    if city_controller(state, city_id) != regime_id:
        raise RuleError("首都正被敌军控制，不能组建军队")
    if army_type not in {0, 1}:
        raise RuleError("军队类型无效")
    units: list[dict[str, int]] = []
    for unit_type, battalion_count in battalions.items():
        if int(battalion_count) != battalion_count or battalion_count < 0:
            raise RuleError("营数必须是非负整数")
        units.extend({"type": int(unit_type), "count": 1000} for _ in range(int(battalion_count)))
    if not units or len(units) > 9:
        raise RuleError("军队需要 1 至 9 个营，每营固定 1000 人")
    v12 = str(state.flags.get("content_version", "1.1")) == "1.2"
    cap = None if v12 else army_battalion_cap(state, regime_id)
    current_battalions = sum(army.active_battalions for army in state.armies.values() if army.regime_id == regime_id)
    if cap is not None and current_battalions + len(units) > cap:
        raise RuleError(f"当前对北态度将全国军队上限锁定为{cap}营")
    if army_type == 0 and any(x["type"] not in {1, 2, 3} for x in units):
        raise RuleError("陆军只能编制步兵、骑兵和弓兵")
    if army_type == 1 and any(x["type"] not in {4, 5, 6} for x in units):
        raise RuleError("水军只能编制战船、快船和楼船")
    total = len(units) * 1000
    copper_cost = 0.0
    if v12:
        from ..content.v1_2.economy import recruitment_available, record_recruitment
        from .treasury import spend_treasury, treasury_balance

        recruitment_cost = max(1, int(math.ceil(total * max(0.0, recruitment_cost_multiplier))))
        copper_cost = round(len(units) * 3.0 * max(0.0, recruitment_cost_multiplier), 2)
        if recruitment_cost > recruitment_available(state, regime_id):
            raise RuleError(
                f"人力不足：需要{recruitment_cost}，现有人力{recruitment_available(state, regime_id)}"
            )
        if treasury_balance(state, regime_id) + 1e-9 < copper_cost:
            raise RuleError(f"组建{len(units)}营需要铜钱{copper_cost:g}")
        record_recruitment(state, regime_id, recruitment_cost)
        spend_treasury(state, regime_id, copper_cost)
    else:
        if total > int(regime.get("reserve_army", 0)):
            raise RuleError("预备役不足")
        regime["reserve_army"] -= total
    army_id = max(state.armies, default=0) + 1
    max_ap = 2.0 if units and all(x["type"] == 2 for x in units) else 1.0
    commander = high_family_commander(state, regime_id)
    army = Army(
        army_id, regime_id, army_type, units,
        commander=commander,
        location_id=city_id,
        action_points=max_ap,
        max_action_points=max_ap,
        commander_locked=commander is not None,
    )
    if v12:
        from ..content.v1_2.economy import army_supply_capacity

        army.supply_food = army_supply_capacity(army)
    state.armies[army_id] = army
    commander_text = f"，由高门武将{state.person_name(commander)}统领且不可卸任" if commander else ""
    cost_text = f"，消耗人力{recruitment_cost}、铜钱{copper_cost:g}" if v12 else ""
    state.add_log(
        f"在首都{state.city_name(city_id)}组建军队#{army_id}，"
        f"共 {len(units)} 营、{total} 人{cost_text}{commander_text}。"
    )
    return army


def army_full_strength(army: Army) -> int:
    establishment = army.establishment or [int(unit.get("type", 0)) for unit in army.units]
    return len(establishment) * 1000


def reinforcement_need(army: Army) -> int:
    return max(0, army_full_strength(army) - army.soldiers)


def is_army_surrounded(state: GameState, army_id: int) -> bool:
    """Whether every usable exit is blocked by an army currently at war.

    Action points are deliberately ignored: a tired formation is not encircled.
    Neutral borders and terrain the formation cannot use are not counted as
    enemy blockade lines.
    """
    army = state.armies.get(int(army_id))
    if army is None or army.soldiers <= 0:
        return False
    has_blockading_enemy = False
    has_open_exit = False
    for target, road in neighbors(state, int(army.location_id)):
        if route_cost(army, effective_road_type(state, road)) is None:
            continue
        controller = city_controller(state, target)
        if controller not in {0, army.regime_id} and not state.at_war(army.regime_id, controller):
            continue
        blockaders = [
            other for other in state.armies.values()
            if other.soldiers > 0
            and int(other.location_id) == int(target)
            and state.at_war(army.regime_id, other.regime_id)
        ]
        if blockaders:
            has_blockading_enemy = True
        else:
            has_open_exit = True
    return has_blockading_enemy and not has_open_exit


def army_support_priority(state: GameState, army: Army) -> tuple[int, int, int, int]:
    """Sort key for AI reinforcement/reward: strategic site, then low morale."""
    city = state.cities.get(int(army.location_id), {})
    score = 0
    if int(army.location_id) == int(state.regimes.get(army.regime_id, {}).get("capital") or 0):
        score += 500
    elif bool(city.get("capital")):
        score += 350
    defense = int(city.get("defense", 0))
    if defense >= 60:
        score += 250 + defense
    if any(
        other.soldiers > 0
        and state.at_war(army.regime_id, other.regime_id)
        for target, _road in neighbors(state, int(army.location_id))
        for other in state.armies.values()
        if int(other.location_id) == int(target)
    ):
        score += 200
    return (-score, int(army.morale), -reinforcement_need(army), int(army.id))


def reinforce_army(state: GameState, army_id: int, *, manpower_cost_multiplier: float = 1.0) -> str:
    """Restore every battalion in an army to 1,000 soldiers using national manpower."""
    army = state.armies.get(int(army_id))
    if army is None or army.soldiers <= 0:
        raise RuleError("军队不存在或已经溃散")
    if str(state.flags.get("content_version", "1.1")) != "1.2":
        raise RuleError("补充满编功能仅适用于1.2版本")
    need = reinforcement_need(army)
    if need <= 0:
        raise RuleError("该军队已经满编")
    if is_army_surrounded(state, army.id):
        raise RuleError("军队已被包围，无法补充兵力")
    from ..content.v1_2.economy import manpower_balance, spend_manpower

    cost = max(1, int(math.ceil(need * max(0.0, manpower_cost_multiplier))))
    if manpower_balance(state, army.regime_id) < cost:
        raise RuleError(f"补充满编需要人力{cost}，现有人力{manpower_balance(state, army.regime_id)}")
    remaining_by_type: dict[int, list[dict[str, int]]] = {}
    for unit in army.units:
        remaining_by_type.setdefault(int(unit.get("type", 0)), []).append(unit)
    rebuilt: list[dict[str, int]] = []
    for unit_type in army.establishment:
        pool = remaining_by_type.get(int(unit_type), [])
        unit = pool.pop(0) if pool else {"type": int(unit_type), "count": 0}
        unit["count"] = 1000
        rebuilt.append(unit)
    army.units = rebuilt
    spend_manpower(state, army.regime_id, cost)
    message = f"军队#{army.id}补充至满编{army.soldiers}人，消耗人力{cost}。"
    state.add_log(message)
    return message


def march(state: GameState, army_id: int, target_city_id: int) -> str:
    army = state.armies[army_id]
    option = next((x for x in legal_moves(state, army_id) if x[0] == target_city_id), None)
    if not option:
        raise RuleError("目标不是合法行军地点，或行动力不足")
    army.location_id = target_city_id
    sync_commander_location(state, army)
    army.action_points = round(army.action_points - option[2], 2)
    message = f"军队#{army_id}行军至{state.city_name(target_city_id)}，剩余行动力 {army.action_points:g}。"
    state.add_log(message)
    occupation = occupy_capital_if_applicable(state, army)
    if occupation:
        message += f"\n{occupation}"
    return message


def march_route(state: GameState, army_id: int, path: tuple[int, ...] | list[int]) -> str:
    route = tuple(int(city_id) for city_id in path)
    if len(route) not in {2, 3}:
        raise RuleError("一键行军路线必须包含两步或三步")
    legal_paths = {candidate for candidate, _cost in legal_march_routes(state, army_id)}
    if route not in legal_paths:
        raise RuleError("这条连续行军路线已经不可用")
    origin = state.armies[army_id].location_id
    for city_id in route:
        march(state, army_id, city_id)
    message = (
        f"军队#{army_id}从{state.city_name(origin)}连续行军{len(route)}步，"
        f"抵达{state.city_name(route[-1])}。"
    )
    state.add_log(message)
    return message


def _combat_value(army: Army, coefficients: dict[int, float]) -> float:
    return sum(coefficients.get(unit["type"], 0) * unit["count"] for unit in army.units)


def _apply_losses(army: Army, losses: int) -> int:
    losses = min(max(0, int(losses)), army.soldiers)
    remaining = losses
    live_units = [u for u in army.units if u["count"] > 0]
    while remaining and live_units:
        share = max(1, math.ceil(remaining / len(live_units)))
        for unit in list(live_units):
            taken = min(unit["count"], share, remaining)
            unit["count"] -= taken
            remaining -= taken
            if unit["count"] <= 0:
                live_units.remove(unit)
            if remaining <= 0:
                break
    army.units = [u for u in army.units if u["count"] > 0]
    return losses


def remove_empty_armies(state: GameState) -> list[int]:
    """清除实际兵力已经归零的军队，兼容旧存档和非战斗减员留下的空编制。"""
    removed = sorted(
        int(army_id)
        for army_id, army in state.armies.items()
        if army.soldiers <= 0
    )
    for army_id in removed:
        state.armies.pop(army_id, None)
    if removed:
        state.add_log("清理空军队：" + "、".join(f"军队#{army_id}" for army_id in removed) + "已撤销编制。")
    return removed


def estimate_battle_losses(state: GameState, army_id: int, target_city_id: int) -> dict[str, int | float]:
    """Estimate the next attack at midpoint variance without changing game state."""
    attacker = state.armies.get(int(army_id))
    if attacker is None or attacker.soldiers <= 0:
        raise RuleError("进攻军队不存在或已经没有士兵")
    option = next((item for item in legal_attacks(state, army_id) if item[0] == target_city_id), None)
    if not option:
        raise RuleError("目标不是合法进攻地点")
    defenders = [
        army for army in state.armies.values()
        if army.location_id == target_city_id
        and army.regime_id != attacker.regime_id
        and state.at_war(attacker.regime_id, army.regime_id)
        and army.soldiers > 0
    ]
    if not defenders:
        return {
            "attacker_losses": 0,
            "defender_losses": 0,
            "attacker_strength": float(attacker.soldiers),
            "defender_strength": 0.0,
        }
    defender = max(defenders, key=lambda army: army.soldiers)
    road_factor = {1: 1.0, 2: 0.5, 3: 1.0 if attacker.army_type == 1 else 0.3, 4: 0.5}.get(option[1], 1.0)
    atk_modifier = combat_modifier(state, attacker.regime_id, True, target_city_id)
    defense_modifier = combat_modifier(state, defender.regime_id, False, target_city_id)
    attacker_modifiers, defender_modifiers = evaluate_battle_modifiers(state, attacker, defender, target_city_id)
    attack_strength = _combat_value(attacker, ATTACK_COEFFICIENT) * road_factor * (
        1 + attacker.experience / 100 + atk_modifier
        + modifier_effect_total(attacker_modifiers, "attack")
        + commander_combat_bonus(state, attacker)
    )
    defense_strength = _combat_value(defender, DEFENSE_COEFFICIENT) * (
        1 + defender.experience / 100 + defense_modifier
        + modifier_effect_total(defender_modifiers, "defense")
        + commander_combat_bonus(state, defender)
    )
    defense_strength *= 1 + int(state.cities[target_city_id].get("defense", 0)) / 100
    defender_losses = int(max(attacker.soldiers * 0.04, (attack_strength - defense_strength * 0.65) * 0.105))
    attacker_losses = int(max(defender.soldiers * 0.025, (defense_strength - attack_strength * 0.45) * 0.085))
    return {
        "attacker_losses": min(attacker.soldiers, max(0, attacker_losses)),
        "defender_losses": min(defender.soldiers, max(0, defender_losses)),
        "attacker_strength": round(float(attack_strength), 2),
        "defender_strength": round(float(defense_strength), 2),
    }


def attack(state: GameState, army_id: int, target_city_id: int, rng: random.Random | None = None) -> str:
    removed_before_battle = remove_empty_armies(state)
    if army_id in removed_before_battle:
        raise RuleError("这支军队已经没有士兵，空编制已被清理")
    attacker = state.armies[army_id]
    option = next((x for x in legal_attacks(state, army_id) if x[0] == target_city_id), None)
    if not option:
        raise RuleError("目标不是合法进攻地点")
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import apply_battle_stability_loss

        apply_battle_stability_loss(state, target_city_id)
    defenders = [a for a in state.armies.values() if a.location_id == target_city_id and a.regime_id != attacker.regime_id]
    defender = max(defenders, key=lambda a: a.soldiers)
    attacker_regime_id = int(attacker.regime_id)
    defender_regime_id = int(defender.regime_id)
    road_factor = {1: 1.0, 2: 0.5, 3: 1.0 if attacker.army_type == 1 else 0.3, 4: 0.5}.get(option[1], 1.0)
    atk_modifier = combat_modifier(state, attacker.regime_id, True, target_city_id)
    defense_modifier = combat_modifier(state, defender.regime_id, False, target_city_id)
    attacker_modifiers, defender_modifiers = evaluate_battle_modifiers(state, attacker, defender, target_city_id)
    atk = _combat_value(attacker, ATTACK_COEFFICIENT) * road_factor * (
        1 + attacker.experience / 100 + atk_modifier
        + modifier_effect_total(attacker_modifiers, "attack")
        + commander_combat_bonus(state, attacker)
    )
    defense = _combat_value(defender, DEFENSE_COEFFICIENT) * (
        1 + defender.experience / 100 + defense_modifier
        + modifier_effect_total(defender_modifiers, "defense")
        + commander_combat_bonus(state, defender)
    )
    city_defense = state.cities[target_city_id].get("defense", 0)
    defense *= 1 + city_defense / 100
    rng = rng or random
    defender_losses = int(max(attacker.soldiers * 0.04, (atk - defense * 0.65) * rng.uniform(0.08, 0.13)))
    attacker_losses = int(max(defender.soldiers * 0.025, (defense - atk * 0.45) * rng.uniform(0.06, 0.11)))
    defender_losses = _apply_losses(defender, defender_losses)
    attacker_losses = _apply_losses(attacker, attacker_losses)
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from .diplomacy import apply_casualty_war_support_loss

        apply_casualty_war_support_loss(state, attacker_regime_id, attacker_losses)
        apply_casualty_war_support_loss(state, defender_regime_id, defender_losses)
    attacker.action_points = 0
    for army, losses in ((attacker, attacker_losses), (defender, defender_losses)):
        capacity = max(1000, (army.active_battalions or 1) * 1000)
        army.morale = int(clamp(army.morale - losses / capacity * 125, 0, 100))
        army.experience = int(clamp(army.experience + 3, 0, 100))
    defender_defeated = defender.soldiers <= 0 or defender.morale <= 0
    attacker_defeated = attacker.soldiers <= 0 or attacker.morale <= 0
    captured = False
    if defender_defeated:
        state.armies.pop(defender.id, None)
    if attacker_defeated:
        state.armies.pop(attacker.id, None)
    if defender_defeated and attacker_defeated:
        outcome = "双方军队均告溃散，城市未被攻占"
    elif defender_defeated:
        remaining_defenders = [
            army for army in state.armies.values()
            if army.location_id == target_city_id and army.regime_id != attacker.regime_id
        ]
        if remaining_defenders:
            outcome = "一支守军溃败，但城内仍有敌军"
        else:
            attacker.location_id = target_city_id
            sync_commander_location(state, attacker)
            attacker.experience = int(clamp(attacker.experience + 2, 0, 100))
            outcome = "守军溃败，城市被攻占"
            captured = True
    elif attacker_defeated:
        outcome = "进攻方溃败，守军仍控制城市"
    else:
        outcome = "守军仍控制城市"
    region = state.regions.get(int(state.cities[target_city_id].get("region_id", 0)))
    if region and str(state.flags.get("content_version", "1.1")) != "1.2":
        region["prosperity"] = max(0, int(region.get("prosperity", 0)) - 1)
    forced_retreats: list[int] = []
    if any(item.get("name") == "佛狸佛狸~干杯" for item in attacker_modifiers):
        region_id = int(state.cities[target_city_id].get("region_id", 0))
        candidates = [
            army for army in state.armies.values()
            if army.regime_id == state.player_regime_id
            and int(state.cities.get(army.location_id, {}).get("region_id", 0)) == region_id
        ]
        rng.shuffle(candidates)
        for retreating in candidates[:2]:
            retreating.morale = max(0, int(retreating.morale) - 20)
            steps = rng.randint(1, 2)
            for _ in range(steps):
                options = [
                    city_id for city_id, _road in neighbors(state, retreating.location_id)
                    if city_id != target_city_id and city_controller(state, city_id) == state.player_regime_id
                ]
                if not options:
                    break
                retreating.location_id = rng.choice(options)
                sync_commander_location(state, retreating)
            forced_retreats.append(retreating.id)
    message = (
        f"军队#{army_id}进攻{state.city_name(target_city_id)}：进攻方损失 {attacker_losses}，"
        f"防守方损失 {defender_losses}；{outcome}。"
    )
    active_notes = []
    if attacker_modifiers:
        active_notes.append("进攻方：" + "、".join(item["name"] for item in attacker_modifiers))
    if defender_modifiers:
        active_notes.append("防守方：" + "、".join(item["name"] for item in defender_modifiers))
    if active_notes:
        message += "\n生效军事修正：" + "；".join(active_notes)
    if forced_retreats:
        message += "\n拓跋焘迫使宋军后撤：" + "、".join(f"军队#{army_id}" for army_id in forced_retreats) + "，士气各-20。"
    battle_entry = "【战报】" + message
    state.add_log(battle_entry)
    reports = state.flags.setdefault("battle_reports", [])
    reports.append(battle_entry)
    if captured:
        occupation = occupy_capital_if_applicable(state, attacker)
        if occupation:
            message += f"\n{occupation}"
    remove_empty_armies(state)
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from .diplomacy import force_surrender

        for regime_id in (attacker_regime_id, defender_regime_id):
            force_surrender(state, regime_id)
    return message


def reward(state: GameState, army_id: int) -> str:
    army = state.armies[army_id]
    if army.rewarded_this_turn:
        raise RuleError("本回合已经犒劳过这支军队")
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import region_economy

        region_id = int(state.cities.get(army.location_id, {}).get("region_id", 0))
        warehouse = region_economy(state, region_id)["warehouse"]
        cost = round(max(0, army.soldiers) / 1000 * 0.2, 2)
        if float(warehouse.get("food", 0.0)) < cost:
            raise RuleError(f"当地州库粮食不足，需要 {cost:g}单位")
        warehouse["food"] = round(float(warehouse.get("food", 0.0)) - cost, 2)
        cost_text = f"消耗当地州库粮食 {cost:g} 单位"
    else:
        cost = army.active_battalions * 100
        regime = state.regimes[army.regime_id]
        if regime["treasury"] < cost:
            raise RuleError(f"国库不足，需要 {cost}")
        regime["treasury"] -= cost
        cost_text = f"花费 {cost}"
    army.morale = int(clamp(army.morale + 30, 0, 100))
    army.rewarded_this_turn = True
    message = f"犒劳军队#{army_id}，{cost_text}，士气恢复至 {army.morale}。"
    state.add_log(message)
    return message


def assign_commander(state: GameState, army_id: int, person_id: int | None) -> str:
    army = state.armies[army_id]
    # 兼容死亡事件或旧存档留下的“将领空缺但仍锁定”状态。
    if army.commander is None:
        army.commander_locked = False
    if army.commander_locked and army.commander != person_id:
        raise RuleError("这名高门武将受当前门阀法律保护，不能卸任或替换")
    if army.commander_changed_this_turn:
        raise RuleError("本回合已经变更过将领")
    if person_id:
        if any(a.commander == person_id for a in state.armies.values()):
            raise RuleError("此人已经统领其他军队")
        person = state.persons.get(person_id)
        if not person or person.get("country_id") != army.regime_id or person.get("status") != 1:
            raise RuleError("将领人选无效")
    army.commander = person_id
    sync_commander_location(state, army)
    if person_id and level(state, "gentry") in {1, 2} and is_high_family(state, state.persons[person_id]):
        army.commander_locked = True
    army.commander_changed_this_turn = True
    message = f"军队#{army_id}的将领变更为{state.person_name(person_id)}。"
    state.add_log(message)
    return message


def disband(state: GameState, army_id: int) -> str:
    army = state.armies[army_id]
    if not legal_moves(state, army_id):
        raise RuleError("军队被包围，不能解散")
    soldiers = army.soldiers
    del state.armies[army_id]
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        message = f"军队#{army_id}解散，{soldiers} 人解除军籍。"
    else:
        state.regimes[army.regime_id]["reserve_army"] += soldiers
        message = f"军队#{army_id}解散，{soldiers} 人回到预备役。"
    state.add_log(message)
    return message
