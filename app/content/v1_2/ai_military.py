from __future__ import annotations

import heapq
import math
import random
from copy import deepcopy
from collections import Counter
from typing import Any

from ...models import Army, GameState
from ...rules.common import RuleError, is_regime_eliminated
from ...rules.diplomacy import region_owner
from ...rules.military import (
    attack,
    city_controller,
    effective_road_type,
    estimate_battle_losses,
    legal_attacks,
    legal_moves,
    march,
    neighbors,
    army_support_priority,
    is_army_surrounded,
    reinforce_army,
    reinforcement_need,
    reward,
    route_cost,
)
from ...rules.ai_modifiers import ai_difficulty_resource_multiplier
from .economy import army_supply_months, economy_data, manpower_balance, month_index, region_economy


STRATEGY_CYCLE_MONTHS = 4
LOST_HOMELAND_PIVOT_MARGIN = 25.0
LOST_HOMELAND_PIVOT_COOLDOWN_MONTHS = 2
ARMY_TASK_COMMITMENT_MONTHS = 2
MOBILE_RESERVE_RATIO = 0.20
TASK_FORCE_MIN_ARMIES = 2
TASK_FORCE_MAX_ARMIES = 5
WATER_ROAD_TYPES = {3, 4}
LAND_UNIT_TYPES = {1, 2, 3}
NAVAL_UNIT_TYPES = {4, 5, 6}
HIGH_DEFENSE_THRESHOLD = 60
CONVOY_DANGER_STEPS = 2
MINIMUM_GARRISON_STRENGTH = {
    "national_capital": 5_000,
    "region_capital": 3_000,
    "fortified_pass": 3_000,
    "convoy_route": 2_000,
}


def ai_military_plan(state: GameState, regime_id: int) -> dict[str, Any] | None:
    plans = state.flags.setdefault("v12_military_plans", {})
    plan = plans.get(str(int(regime_id)))
    return plan if isinstance(plan, dict) else None


def _armies(state: GameState, regime_id: int) -> list[Army]:
    return sorted(
        (army for army in state.armies.values() if army.regime_id == regime_id and army.soldiers > 0),
        key=lambda army: army.id,
    )


def _war_enemies(state: GameState, regime_id: int) -> set[int]:
    enemies = {
        int(side)
        for pair in state.wars
        if regime_id in {int(item) for item in pair}
        for side in pair
        if int(side) != regime_id and not is_regime_eliminated(state, int(side))
    }
    if regime_id == 2 and not state.flags.get("v12_wei_song_peace_concluded"):
        enemies = {state.player_regime_id} if state.player_regime_id in enemies else set()
    elif regime_id == 2 and state.year < 427:
        enemies = {enemy for enemy in enemies if state.regimes.get(enemy, {}).get("name") != "胡夏"}
    return enemies


def _composition(armies: list[Army]) -> dict[str, float | int]:
    counts: Counter[str] = Counter()
    for army in armies:
        for unit in army.units:
            soldiers = max(0, int(unit.get("count", 0)))
            unit_type = int(unit.get("type", 0))
            if unit_type in NAVAL_UNIT_TYPES or army.army_type == 1:
                counts["naval"] += soldiers
            elif unit_type == 2:
                counts["cavalry"] += soldiers
            else:
                counts["infantry"] += soldiers
    total = sum(counts.values())
    return {
        "infantry": counts["infantry"],
        "cavalry": counts["cavalry"],
        "naval": counts["naval"],
        "total": total,
        "land_ratio": round((counts["infantry"] + counts["cavalry"]) / total, 4) if total else 0.0,
        "naval_ratio": round(counts["naval"] / total, 4) if total else 0.0,
    }


def army_readiness_strength(state: GameState, army: Army) -> float:
    """Combat power currently available to an AI planner, not paper headcount."""
    if army.soldiers <= 0 or army.morale <= 0:
        return 0.0
    morale = max(0.0, min(1.0, float(army.morale) / 100))
    months = army_supply_months(army, state)
    if months < 0.5:
        supply = 0.15
    elif months < 1:
        supply = 0.35
    elif months < 2:
        supply = 0.65
    else:
        supply = 1.0
    from ...rules.ai_modifiers import commander_combat_bonus

    command = 1.0 + max(0.0, float(commander_combat_bonus(state, army)))
    return round(float(army.soldiers) * morale * supply * command, 2)


def _effective_force(state: GameState, armies: list[Army]) -> int:
    return int(round(sum(army_readiness_strength(state, army) for army in armies)))


def _strategic_site_minimum(state: GameState, regime_id: int, city_id: int) -> int:
    city = state.cities.get(int(city_id), {})
    if int(city_id) == int(state.regimes[regime_id].get("capital") or 0):
        return MINIMUM_GARRISON_STRENGTH["national_capital"]
    if city.get("capital"):
        return MINIMUM_GARRISON_STRENGTH["region_capital"]
    return MINIMUM_GARRISON_STRENGTH["fortified_pass"]


def _has_cavalry(army: Army) -> bool:
    return any(int(unit.get("type", 0)) == 2 and int(unit.get("count", 0)) > 0 for unit in army.units)


def enemy_naval_threatened_cities(
    state: GameState,
    regime_id: int,
    max_steps: int = 3,
) -> set[int]:
    """Cities an enemy navy can contact this turn, capped at the game's three-step march."""
    enemies = _war_enemies(state, regime_id)
    threatened: set[int] = set()
    for navy in state.armies.values():
        if navy.regime_id not in enemies or navy.soldiers <= 0:
            continue
        if navy.army_type != 1 and not any(
            int(unit.get("type", 0)) in NAVAL_UNIT_TYPES and int(unit.get("count", 0)) > 0
            for unit in navy.units
        ):
            continue
        budget = max(0.0, float(navy.max_action_points))
        queue: list[tuple[float, int, int]] = [(0.0, 0, int(navy.location_id))]
        best: dict[tuple[int, int], float] = {(int(navy.location_id), 0): 0.0}
        while queue:
            spent, steps, city_id = heapq.heappop(queue)
            if spent > budget + 1e-9 or steps > max_steps:
                continue
            threatened.add(city_id)
            if steps == max_steps:
                continue
            for target, road in neighbors(state, city_id):
                road_type = effective_road_type(state, road)
                edge = route_cost(navy, road_type)
                if edge is None:
                    continue
                new_spent = round(spent + edge, 2)
                key = (int(target), steps + 1)
                if new_spent <= budget + 1e-9 and new_spent + 1e-9 < best.get(key, math.inf):
                    best[key] = new_spent
                    heapq.heappush(queue, (new_spent, steps + 1, int(target)))
    return threatened


def city_water_complexity(state: GameState, city_id: int) -> float:
    roads = [road for _target, road in neighbors(state, int(city_id))]
    if not roads:
        return 0.0
    water = sum(1 for road in roads if effective_road_type(state, road) in WATER_ROAD_TYPES)
    # 水路比例为主体；陆路出口越少，越不适合纯陆军展开。
    land_exits = len(roads) - water
    isolation = 0.2 if land_exits <= 1 and water else 0.0
    return round(min(1.0, water / len(roads) + isolation), 4)


def _all_paths_to_friendly_depots(
    state: GameState,
    army: Army,
) -> list[tuple[float, list[int], int, float]]:
    depots: list[tuple[int, float]] = []
    seen_regions: set[int] = set()
    for city_id, city in state.cities.items():
        region_id = int(city.get("region_id", 0))
        if (
            region_id in state.regions
            and region_id not in seen_regions
            and city.get("capital")
            and int(state.regions[region_id].get("controller", 0)) == army.regime_id
        ):
            seen_regions.add(region_id)
            depots.append((int(city_id), float(region_economy(state, region_id)["warehouse"].get("food", 0.0))))
    results: list[tuple[float, list[int], int, float]] = []
    for depot_city, stock in depots:
        path = _strategic_path(state, army.location_id, depot_city, army.regime_id, avoid_water=False, army=army)
        if path:
            results.append((float(len(path) - 1), path, depot_city, stock))
    return sorted(results, key=lambda item: (item[0], -item[3], item[2]))


def supply_line_health(state: GameState, army: Army) -> dict[str, Any]:
    """Rate carried food plus the safest reachable friendly depot on a 0-100 scale."""
    months = army_supply_months(army, state)
    paths = _all_paths_to_friendly_depots(state, army)
    if not paths:
        return {
            "army_id": army.id,
            "health": int(min(40, months / 6 * 40)),
            "supply_months": months,
            "depot_city_id": None,
            "path": [],
            "route_length": 999,
            "route_risk": 100,
        }
    _distance, path, depot_city, stock = paths[0]
    route_risk = 0
    enemy_positions = {
        other.location_id for other in state.armies.values()
        if state.at_war(army.regime_id, other.regime_id)
    }
    for city_id in path[1:-1]:
        controller = city_controller(state, city_id)
        if controller not in {0, army.regime_id}:
            route_risk += 12
        if city_id in enemy_positions:
            route_risk += 30
    route_risk += max(0, len(path) - 4) * 4
    from ...rules.ai_modifiers import ai_difficulty_supply_multiplier

    monthly_need = max(
        0.01,
        army.soldiers / 1000 * 0.2 * ai_difficulty_supply_multiplier(state, army.regime_id),
    )
    depot_score = min(20.0, stock / (monthly_need * 4) * 20)
    carried_score = min(40.0, months / 6 * 40)
    route_score = max(0.0, 30 - route_risk)
    redundancy = 10 if len(paths) >= 2 and paths[1][0] <= paths[0][0] + 2 else 0
    health = int(max(0, min(100, round(carried_score + depot_score + route_score + redundancy))))
    return {
        "army_id": army.id,
        "health": health,
        "supply_months": months,
        "depot_city_id": depot_city,
        "path": path,
        "route_length": len(path) - 1,
        "route_risk": route_risk,
    }


def _strategic_path(
    state: GameState,
    start: int,
    goal: int,
    regime_id: int,
    *,
    avoid_water: bool,
    army: Army | None = None,
    forbidden_cities: set[int] | None = None,
) -> list[int] | None:
    forbidden_cities = forbidden_cities or set()
    if goal in forbidden_cities and goal != start:
        return None
    if start == goal:
        return [start]
    enemy_positions = {
        other.location_id for other in state.armies.values()
        if other.regime_id != regime_id and state.at_war(regime_id, other.regime_id)
    }
    queue: list[tuple[float, int, tuple[int, ...]]] = [(0.0, start, (start,))]
    best = {start: 0.0}
    while queue:
        cost, city_id, path = heapq.heappop(queue)
        if city_id == goal:
            return list(path)
        if cost > best.get(city_id, math.inf):
            continue
        for target, road in neighbors(state, city_id):
            if target in forbidden_cities and target != start:
                continue
            road_type = effective_road_type(state, road)
            if army is not None and route_cost(army, road_type) is None:
                continue
            controller = city_controller(state, target)
            if controller not in {0, regime_id} and not state.at_war(regime_id, controller):
                continue
            edge = 1.0
            if avoid_water and road_type in WATER_ROAD_TYPES:
                edge += 4.0
            if controller not in {0, regime_id}:
                edge += 0.75
            if target in enemy_positions and target != goal:
                edge += 8.0
            new_cost = cost + edge
            if new_cost + 1e-9 < best.get(target, math.inf):
                best[target] = new_cost
                heapq.heappush(queue, (new_cost, target, path + (target,)))
    return None


def _strategic_path_cost(state: GameState, path: list[int], avoid_water: bool) -> float:
    total = 0.0
    for left, right in zip(path, path[1:]):
        roads = [
            road for road in state.roads
            if {int(road.get("from", 0)), int(road.get("to", 0))} == {int(left), int(right)}
        ]
        if not roads:
            return math.inf
        road_type = min(effective_road_type(state, road) for road in roads)
        total += 1.0 + (4.0 if avoid_water and road_type in WATER_ROAD_TYPES else 0.0)
    return total


def _recent_conquest(state: GameState, regime_id: int) -> dict[str, Any] | None:
    captures = state.flags.get("v12_region_captures", {})
    candidates = [
        record for record in captures.values()
        if int(record.get("regime_id", 0)) == regime_id
        and month_index(state) - int(record.get("month", -10_000)) <= STRATEGY_CYCLE_MONTHS
        and int(state.regions.get(int(record.get("region_id", 0)), {}).get("controller", 0)) == regime_id
    ]
    return max(candidates, key=lambda record: int(record.get("month", 0))) if candidates else None


def _region_capital(state: GameState, region_id: int) -> int | None:
    return next(
        (
            int(city_id) for city_id in state.regions.get(int(region_id), {}).get("cities", [])
            if state.cities.get(int(city_id), {}).get("capital")
        ),
        None,
    )


def _update_enemy_movement_tracks(state: GameState, regime_id: int) -> dict[str, dict[str, int]]:
    """Remember one prior monthly position so the AI can recognise an approaching spearhead."""
    now = month_index(state)
    all_tracks = state.flags.setdefault("v12_ai_enemy_movement_tracks", {})
    tracks = all_tracks.setdefault(str(int(regime_id)), {})
    living_ids: set[str] = set()
    for enemy in state.armies.values():
        if enemy.regime_id not in _war_enemies(state, regime_id) or enemy.soldiers <= 0:
            continue
        key = str(int(enemy.id))
        living_ids.add(key)
        current = tracks.get(key, {})
        if int(current.get("month", -1)) != now:
            previous = int(current.get("location_id", enemy.location_id))
            tracks[key] = {
                "army_id": int(enemy.id),
                "previous_location_id": previous,
                "location_id": int(enemy.location_id),
                "month": now,
            }
        else:
            current["location_id"] = int(enemy.location_id)
    for key in list(tracks):
        if key not in living_ids:
            tracks.pop(key, None)
    return tracks


def _approaching_enemy_pressure(state: GameState, regime_id: int, city_id: int) -> tuple[float, bool]:
    tracks = state.flags.get("v12_ai_enemy_movement_tracks", {}).get(str(int(regime_id)), {})
    pressure = 0.0
    approaching = False
    enemies = _war_enemies(state, regime_id)
    for enemy in state.armies.values():
        if enemy.regime_id not in enemies or enemy.soldiers <= 0:
            continue
        path = _strategic_path(
            state, enemy.location_id, city_id, enemy.regime_id, avoid_water=False, army=enemy
        )
        if not path or len(path) - 1 > 4:
            continue
        distance = len(path) - 1
        contribution = army_readiness_strength(state, enemy) / max(1, distance + 1)
        track = tracks.get(str(int(enemy.id)), {})
        previous_location = int(track.get("previous_location_id", enemy.location_id))
        previous_path = _strategic_path(
            state, previous_location, city_id, enemy.regime_id, avoid_water=False, army=enemy
        )
        previous_distance = len(previous_path) - 1 if previous_path else 999
        if distance < previous_distance:
            approaching = True
            contribution *= 1.15
        pressure += contribution
    return round(pressure, 2), approaching


def _split_units_for_garrison(army: Army, garrison_size: int) -> tuple[list[dict[str, int]], list[dict[str, int]]]:
    remaining = max(0, int(garrison_size))
    garrison: list[dict[str, int]] = []
    mobile: list[dict[str, int]] = []
    for unit in army.units:
        unit_type = int(unit.get("type", 0))
        count = max(0, int(unit.get("count", 0)))
        kept = min(count, remaining)
        if kept:
            garrison.append({"type": unit_type, "count": kept})
            remaining -= kept
        if count > kept:
            mobile.append({"type": unit_type, "count": count - kept})
    return garrison, mobile


def _create_mobile_reserves(state: GameState, regime_id: int) -> list[int]:
    """Detach surplus battalions from oversized static garrisons without creating soldiers."""
    armies = _armies(state, regime_id)
    if len(armies) < 3 or not _war_enemies(state, regime_id):
        return []
    strategic = [
        army for army in armies
        if state.cities.get(int(army.location_id), {}).get("capital")
        or int(state.cities.get(int(army.location_id), {}).get("defense", 0)) >= HIGH_DEFENSE_THRESHOLD
    ]
    static_ids = {army.id for army in strategic}
    mobile_strength = sum(army.soldiers for army in armies if army.id not in static_ids)
    desired = int(sum(army.soldiers for army in armies) * MOBILE_RESERVE_RATIO)
    if mobile_strength >= desired:
        return []

    created: list[int] = []
    sites = sorted(
        {int(army.location_id) for army in strategic},
        key=lambda city_id: (_enemy_distance_to_city(state, regime_id, city_id), city_id),
        reverse=True,
    )
    for city_id in sites:
        present = [army for army in _armies(state, regime_id) if army.location_id == city_id]
        if len(present) != 1:
            continue
        army = present[0]
        minimum = _strategic_site_minimum(state, regime_id, city_id)
        if army.morale < 30 or army.soldiers < minimum + 2_000 or army.active_battalions < 3:
            continue
        guard_units, mobile_units = _split_units_for_garrison(army, minimum)
        mobile_soldiers = sum(int(unit["count"]) for unit in mobile_units)
        if mobile_soldiers < 2_000:
            continue
        before = max(1, army.soldiers)
        mobile_supply = round(float(army.supply_food) * mobile_soldiers / before, 2)
        army.supply_food = round(max(0.0, float(army.supply_food) - mobile_supply), 2)
        mobile_id = max(state.armies, default=0) + 1
        mobile = Army(
            id=mobile_id,
            regime_id=regime_id,
            army_type=army.army_type,
            units=mobile_units,
            morale=army.morale,
            experience=army.experience,
            commander=army.commander,
            location_id=army.location_id,
            action_points=army.action_points,
            max_action_points=army.max_action_points,
            commander_locked=False,
            supply_food=mobile_supply,
            modifiers=deepcopy(army.modifiers),
            establishment=[int(unit["type"]) for unit in mobile_units],
        )
        army.units = guard_units
        army.establishment = [int(unit["type"]) for unit in guard_units]
        army.commander = None
        army.commander_locked = False
        state.armies[mobile_id] = mobile
        if mobile.commander in state.persons:
            state.persons[int(mobile.commander)]["location_id"] = mobile.location_id
        created.append(mobile_id)
        mobile_strength += mobile_soldiers
        state.add_log(
            f"{state.regimes[regime_id].get('name')}整编{state.city_name(city_id)}守军："
            f"保留{minimum}人，抽调{mobile_soldiers}人组成机动军#{mobile_id}。"
        )
        if mobile_strength >= desired:
            break
    return created


def _front_strength(state: GameState, regime_id: int, target_city: int, radius: int = 4) -> tuple[int, int]:
    enemies = _war_enemies(state, regime_id)
    own = 0
    hostile = 0
    for army in state.armies.values():
        path = _strategic_path(state, army.location_id, target_city, regime_id, avoid_water=False, army=army)
        distance = len(path) - 1 if path else 999
        if distance > radius:
            continue
        if army.regime_id == regime_id:
            own += int(army_readiness_strength(state, army))
        elif army.regime_id in enemies:
            hostile += int(army_readiness_strength(state, army))
    return own, hostile


def _enemy_distance_to_city(state: GameState, regime_id: int, city_id: int) -> int:
    distances = []
    enemies = _war_enemies(state, regime_id)
    for enemy in state.armies.values():
        if enemy.regime_id not in enemies or enemy.soldiers <= 0:
            continue
        path = _strategic_path(
            state,
            enemy.location_id,
            city_id,
            enemy.regime_id,
            avoid_water=False,
            army=enemy,
        )
        if path:
            distances.append(len(path) - 1)
    return min(distances, default=999)


def ai_defense_priorities(state: GameState, regime_id: int) -> list[dict[str, Any]]:
    """Rank threatened capitals, fortified passes and official convoy-route nodes."""
    if not _war_enemies(state, regime_id):
        return []
    priorities: dict[int, dict[str, Any]] = {}

    def record(city_id: int, kind: str, score: float, reason: str, enemy_distance: int) -> None:
        current = priorities.get(city_id)
        candidate = {
            "city_id": int(city_id),
            "kind": kind,
            "score": round(float(score), 2),
            "reason": reason,
            "enemy_distance": int(enemy_distance),
        }
        if current is None or float(candidate["score"]) > float(current["score"]):
            priorities[city_id] = candidate

    national_capital = int(state.regimes[regime_id].get("capital") or 0)
    for city_id, city in state.cities.items():
        region_id = int(city.get("region_id", 0))
        if int(state.regions.get(region_id, {}).get("controller", 0)) != regime_id:
            continue
        is_region_capital = bool(city.get("capital"))
        defense = int(city.get("defense", 0))
        is_fort = defense >= HIGH_DEFENSE_THRESHOLD
        if not is_region_capital and not is_fort:
            continue
        distance = _enemy_distance_to_city(state, regime_id, int(city_id))
        if int(city_id) == national_capital:
            kind, base, reason = "national_capital", 220, "保卫首都"
        elif distance > (4 if is_region_capital else 3):
            continue
        elif is_region_capital:
            kind, base, reason = "region_capital", 140, "保卫受威胁的地区首府"
        else:
            kind, base, reason = "fortified_pass", 120, "扼守受威胁的高城防关隘"
        threat_bonus = max(0, 5 - distance) * 25 if distance < 999 else 0
        approach_pressure, approaching = _approaching_enemy_pressure(state, regime_id, int(city_id))
        approach_bonus = min(180.0, approach_pressure / 100)
        if approaching:
            approach_bonus += 50
            reason += "，敌军正在接近"
        record(int(city_id), kind, base + defense + threat_bonus + approach_bonus, reason, distance)

    # 官漕本身不受自然损耗，但仍可能被敌军劫掠；敌军两步内可接触路线即视为危险。
    for unit in economy_data(state).get("logistics_units", []):
        if unit.get("kind") != "official" or int(unit.get("regime_id", 0)) != regime_id:
            continue
        path = [int(city_id) for city_id in unit.get("path", [])]
        index = max(0, int(unit.get("path_index", 0)))
        remaining = path[index:]
        threatened = [
            (_enemy_distance_to_city(state, regime_id, city_id), city_id)
            for city_id in remaining
        ]
        threatened = [item for item in threatened if item[0] <= CONVOY_DANGER_STEPS]
        if not threatened:
            continue
        distance, city_id = min(threatened, key=lambda item: (item[0], remaining.index(item[1])))
        record(
            city_id,
            "convoy_route",
            320 + max(0, CONVOY_DANGER_STEPS - distance) * 40,
            f"保护官漕#{unit.get('id')}的运输路线",
            distance,
        )
    return sorted(priorities.values(), key=lambda item: (-float(item["score"]), int(item["city_id"])))


def _enemy_target_candidates(
    state: GameState,
    regime_id: int,
    avoid_water: bool,
    maximum_cavalry_water_avoidance: bool,
) -> list[dict[str, Any]]:
    enemies = _war_enemies(state, regime_id)
    if not enemies:
        return []
    own_armies = _armies(state, regime_id)
    naval_threat = enemy_naval_threatened_cities(state, regime_id) if maximum_cavalry_water_avoidance else set()
    candidates: list[dict[str, Any]] = []
    for region_id, region in state.regions.items():
        controller = int(region.get("controller", 0))
        if controller not in enemies:
            continue
        capital_city_id = _region_capital(state, int(region_id))
        if capital_city_id is None:
            continue
        hostile_by_city: dict[int, int] = {}
        for enemy in state.armies.values():
            if enemy.regime_id not in enemies or enemy.soldiers <= 0:
                continue
            if int(state.cities.get(enemy.location_id, {}).get("region_id", 0)) == int(region_id):
                hostile_by_city[enemy.location_id] = hostile_by_city.get(enemy.location_id, 0) + enemy.soldiers
        lost_homeland = region_owner(state, int(region_id)) == regime_id
        # 收复失地始终以首府为最终目标；普通敌境则先打击该地区兵力最集中的前线城市。
        city_id = int(capital_city_id)
        if hostile_by_city and not lost_homeland:
            city_id = max(hostile_by_city, key=lambda item: (hostile_by_city[item], item))
        reachable = [
            _strategic_path(
                state,
                army.location_id,
                city_id,
                regime_id,
                avoid_water=avoid_water,
                army=army,
                forbidden_cities=naval_threat if maximum_cavalry_water_avoidance and _has_cavalry(army) else None,
            )
            for army in own_armies
        ]
        reachable = [path for path in reachable if path]
        if not reachable:
            continue
        distance = min(len(path) - 1 for path in reachable)
        # 战术前线只统计两步内兵力，避免相邻战区的同一批敌军在多个首府方向重复计入。
        own, hostile = _front_strength(state, regime_id, city_id, radius=2)
        defense = int(state.cities[city_id].get("defense", 0))
        water = city_water_complexity(state, city_id)
        strategic_value = 40 if int(state.regimes[controller].get("capital") or 0) == city_id else 20
        deployed_here = hostile_by_city.get(city_id, 0)
        recovery_bonus = 120 if lost_homeland else 0
        # An undefended homeland is a fleeting operational opportunity.  The
        # ordinary score used to favour a heavily contested front because the
        # friendly troops already massed there increased ``own_strength`` and
        # deployed enemies granted a frontline bonus.  That made an empty lost
        # province (for example Jizhou) look less attractive than a stalemated
        # Luoyang front.  Reward low resistance separately, but only for the
        # recovery of territory the regime actually owns.
        recovery_opportunity_bonus = 0.0
        if lost_homeland:
            if hostile <= 1_000:
                recovery_opportunity_bonus = 100.0
            else:
                recovery_opportunity_bonus = max(0.0, 60.0 - hostile / 500.0)
        frontline_bonus = min(60.0, deployed_here / 1000 * 4)
        score = (
            strategic_value
            + recovery_bonus
            + recovery_opportunity_bonus
            + frontline_bonus
            + own / 1000 * 2
            - hostile / 1000 * 2.5
            - defense / 5
            - distance * 3
        )
        if avoid_water:
            score -= water * 45
        candidates.append({
            "region_id": int(region_id),
            "city_id": city_id,
            "score": round(score, 2),
            "distance": distance,
            "own_strength": own,
            "enemy_strength": hostile,
            "water_complexity": water,
            "lost_homeland": lost_homeland,
            "deployed_enemy_strength": deployed_here,
            "recovery_opportunity_bonus": round(recovery_opportunity_bonus, 2),
        })
    return sorted(candidates, key=lambda item: (-float(item["score"]), int(item["city_id"])))


def national_military_snapshot(state: GameState, regime_id: int) -> dict[str, Any]:
    from .climate import is_winter_month, months_until_winter, winter_months

    own_armies = _armies(state, regime_id)
    enemies = _war_enemies(state, regime_id)
    enemy_armies = [army for army in state.armies.values() if army.regime_id in enemies and army.soldiers > 0]
    own_composition = _composition(own_armies)
    enemy_composition = _composition(enemy_armies)
    supply = [supply_line_health(state, army) for army in own_armies]
    naval_mismatch = int(enemy_composition["naval"]) > int(own_composition["naval"])
    maximum_cavalry_water_avoidance = bool(int(own_composition["cavalry"]) > 0 and naval_mismatch)
    avoid_water = bool(
        maximum_cavalry_water_avoidance
        or (
            float(own_composition["land_ratio"]) >= 0.65
            and float(enemy_composition["naval_ratio"]) >= 0.20
        )
    )
    return {
        "own_armies": len(own_armies),
        "own_soldiers": int(own_composition["total"]),
        "enemy_soldiers": int(enemy_composition["total"]),
        "own_effective_strength": _effective_force(state, own_armies),
        "enemy_effective_strength": _effective_force(state, enemy_armies),
        "own_composition": own_composition,
        "enemy_composition": enemy_composition,
        "supply": supply,
        "average_supply_health": round(sum(item["health"] for item in supply) / len(supply), 2) if supply else 0.0,
        "minimum_supply_months": min((float(item["supply_months"]) for item in supply), default=0.0),
        "avoid_water": avoid_water,
        "naval_mismatch": naval_mismatch,
        "maximum_cavalry_water_avoidance": maximum_cavalry_water_avoidance,
        "enemy_naval_threatened_cities": sorted(enemy_naval_threatened_cities(state, regime_id)) if naval_mismatch else [],
        "war_enemies": sorted(enemies),
        "winter_active": is_winter_month(state),
        "months_until_winter": months_until_winter(state),
        "winter_length": len(winter_months(state, state.year)),
        "winter_naval_caution": is_winter_month(state) or months_until_winter(state) <= 2,
    }


def _forced_story_target(
    state: GameState,
    regime_id: int,
    snapshot: dict[str, Any],
) -> tuple[str, int | None, str] | None:
    invasion_target = int(state.flags.get("ai_invasion_target:2", 0))
    if (
        regime_id == 2
        and invasion_target not in {0, 1}
        and invasion_target in state.regimes
        and not is_regime_eliminated(state, invasion_target)
        and state.at_war(2, invasion_target)
    ):
        remaining_regions = [
            int(region_id)
            for region_id, region in state.regions.items()
            if int(region.get("controller", 0)) == invasion_target
        ]
        if not remaining_regions:
            return None
        target_capital = int(state.regimes[invasion_target].get("capital") or 0)
        if city_controller(state, target_capital) != invasion_target:
            remaining_capitals = [
                _region_capital(state, int(region_id))
                for region_id in remaining_regions
            ]
            target_capital = next(
                (int(city_id) for city_id in remaining_capitals if city_id is not None),
                target_capital,
            )
        return "attack_region", target_capital, "魏国战略：优先吞并兵力悬殊的相邻小国"
    # 元嘉剧本中的北魏战争主线仍然有效，但是否立即推进由补给评估决定。
    if regime_id != 2 or not state.at_war(1, 2):
        return None
    if int(state.regions.get(13, {}).get("controller", 0)) != 2:
        return "attack_region", 77, "剧情战略：先夺取洛阳与中原"
    if state.flags.get("v12_wei_war_expanded"):
        strong_advantage = int(snapshot["own_effective_strength"]) >= max(
            1, int(snapshot["enemy_effective_strength"]) * 1.5
        )
        supply_ready = (
            float(snapshot["average_supply_health"]) >= 75
            and float(snapshot["minimum_supply_months"]) >= 4
        )
        cavalry_screened = not (
            bool(snapshot["maximum_cavalry_water_avoidance"])
            and 1 in set(snapshot["enemy_naval_threatened_cities"])
        )
        if strong_advantage and supply_ready and cavalry_screened:
            return "attack_region", 1, "和议破裂，兵力、补给与水军掩护均足以南征"
        return "consolidate", 77, "和议虽已破裂，但南征条件不足，继续巩固洛阳"
    return "consolidate", 77, "洛阳已下，巩固中原并等待外交结果"


def _goal_from_snapshot(state: GameState, regime_id: int, snapshot: dict[str, Any]) -> dict[str, Any]:
    armies = _armies(state, regime_id)
    capital = int(state.regimes[regime_id].get("capital") or 0)
    if not armies:
        return {"kind": "rest", "reason": "没有可执行战略的军队"}

    capital_enemy = any(
        army.location_id == capital and army.regime_id in _war_enemies(state, regime_id)
        for army in state.armies.values()
    )
    if capital_enemy or city_controller(state, capital) != regime_id:
        return {"kind": "defend_capital", "target_city_id": capital, "reason": "首都受到直接威胁"}

    candidates = _enemy_target_candidates(
        state,
        regime_id,
        bool(snapshot["avoid_water"]),
        bool(snapshot["maximum_cavalry_water_avoidance"]),
    )
    lost_candidates = [item for item in candidates if item.get("lost_homeland")]
    if lost_candidates:
        target = lost_candidates[0]
        secondary_targets: list[int] = []
        if (
            len(lost_candidates) > 1
            and int(snapshot["own_effective_strength"]) >= int(snapshot["enemy_effective_strength"]) * 1.25
        ):
            secondary_targets = [
                int(item["city_id"])
                for item in lost_candidates[1:2]
                if int(item.get("deployed_enemy_strength", 0)) > 0
            ]
        return {
            "kind": "attack_region",
            "target_region_id": int(target["region_id"]),
            "target_city_id": int(target["city_id"]),
            "secondary_target_city_ids": secondary_targets,
            "reason": (
                f"优先收复失地；目标评分{target['score']:g}，"
                f"敌军部署{int(target['deployed_enemy_strength'])}人"
            ),
        }

    story = _forced_story_target(state, regime_id, snapshot)
    if story:
        return {"kind": story[0], "target_city_id": story[1], "reason": story[2]}

    if candidates:
        target = candidates[0]
        enough_force = int(snapshot["own_effective_strength"]) >= max(
            1,
            int(target["enemy_strength"]) * 1.1,
            int(snapshot["enemy_effective_strength"]) * 0.75,
        )
        if enough_force and float(snapshot["average_supply_health"]) >= 60:
            return {
                "kind": "attack_region",
                "target_region_id": int(target["region_id"]),
                "target_city_id": int(target["city_id"]),
                "reason": f"目标评分{target['score']:g}，战线兵力与补给允许进攻",
            }
        threatened = min(
            (
                city for city in state.cities.values()
                if city.get("capital") and city_controller(state, int(city["id"])) == regime_id
            ),
            key=lambda city: min(
                (len(_strategic_path(state, enemy.location_id, int(city["id"]), enemy.regime_id, avoid_water=False, army=enemy) or [0] * 999) for enemy in state.armies.values() if enemy.regime_id in _war_enemies(state, regime_id)),
                default=999,
            ),
            default=state.cities.get(capital, {"id": capital}),
        )
        return {
            "kind": "defend_frontier",
            "target_city_id": int(threatened["id"]),
            "reason": "进攻优势不足，先巩固受威胁的地区首府",
        }
    recent = _recent_conquest(state, regime_id)
    if recent:
        region_id = int(recent["region_id"])
        return {
            "kind": "consolidate",
            "target_region_id": region_id,
            "target_city_id": _region_capital(state, region_id),
            "reason": "当前没有新的进攻目标，巩固新占领地区与补给线",
        }
    return {"kind": "rest", "target_city_id": capital, "reason": "当前没有交战目标"}


def choose_ai_military_strategy(state: GameState, regime_id: int) -> dict[str, Any]:
    snapshot = national_military_snapshot(state, regime_id)
    plan = _goal_from_snapshot(state, regime_id, snapshot)
    now = month_index(state)
    plan.update({
        "regime_id": int(regime_id),
        "created_month": now,
        "review_month": now + STRATEGY_CYCLE_MONTHS,
        "status": "active" if plan["kind"] != "rest" else "idle",
        "avoid_water": bool(snapshot["avoid_water"]),
        "naval_mismatch": bool(snapshot["naval_mismatch"]),
        "maximum_cavalry_water_avoidance": bool(snapshot["maximum_cavalry_water_avoidance"]),
        "enemy_naval_threatened_cities": list(snapshot["enemy_naval_threatened_cities"]),
        "initial_supply_health": snapshot["average_supply_health"],
        "winter_active": bool(snapshot["winter_active"]),
        "months_until_winter": int(snapshot["months_until_winter"]),
        "winter_length": int(snapshot["winter_length"]),
        "winter_naval_caution": bool(snapshot["winter_naval_caution"]),
        "snapshot": {
            key: snapshot[key]
            for key in (
                "own_soldiers", "enemy_soldiers", "own_effective_strength",
                "enemy_effective_strength", "own_composition", "enemy_composition",
                "average_supply_health",
            )
        },
    })
    state.flags.setdefault("v12_military_plans", {})[str(int(regime_id))] = plan
    return plan


def _retarget_weak_lost_homeland(
    state: GameState,
    regime_id: int,
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Pivot an active offensive when another owned lost region becomes much softer.

    The four-month grand-strategy cycle remains the default.  This is a narrow
    exception for reclaiming homeland: it checks once per month, requires a
    material score advantage, and applies a two-month switch cooldown unless
    the alternative is virtually undefended while the current front is not.
    """
    if str(plan.get("kind")) != "attack_region" or not _war_enemies(state, regime_id):
        return plan
    target_city = int(plan.get("target_city_id") or 0)
    current_region_id = int(
        plan.get("target_region_id")
        or state.cities.get(target_city, {}).get("region_id", 0)
        or 0
    )
    if not current_region_id or region_owner(state, current_region_id) != regime_id:
        return plan

    snapshot = national_military_snapshot(state, regime_id)
    lost = [
        item
        for item in _enemy_target_candidates(
            state,
            regime_id,
            bool(snapshot["avoid_water"]),
            bool(snapshot["maximum_cavalry_water_avoidance"]),
        )
        if item.get("lost_homeland")
    ]
    current = next((item for item in lost if int(item["region_id"]) == current_region_id), None)
    alternative = next((item for item in lost if int(item["region_id"]) != current_region_id), None)
    if current is None or alternative is None:
        return plan

    advantage = float(alternative["score"]) - float(current["score"])
    if advantage < LOST_HOMELAND_PIVOT_MARGIN:
        return plan
    now = month_index(state)
    last_switch = int(plan.get("last_target_switch_month", plan.get("created_month", now)))
    decisive_opening = (
        int(alternative.get("enemy_strength", 0)) <= 1_000
        and int(current.get("enemy_strength", 0)) >= 5_000
        and advantage >= LOST_HOMELAND_PIVOT_MARGIN * 2
    )
    if not decisive_opening and now - last_switch < LOST_HOMELAND_PIVOT_COOLDOWN_MONTHS:
        return plan

    previous_city = target_city
    plan.update({
        "target_region_id": int(alternative["region_id"]),
        "target_city_id": int(alternative["city_id"]),
        # Forces already on the old front are retained by local hold/defence
        # logic.  Do not keep it as a secondary offensive target, otherwise the
        # first newly freed formation is immediately sent back there and the
        # strategic pivot exists only on paper.
        "secondary_target_city_ids": [],
        "previous_target_city_id": previous_city,
        "last_target_switch_month": now,
        "review_month": now + STRATEGY_CYCLE_MONTHS,
        "status": "active",
        "reason": (
            f"发现更薄弱的失地，转移战略重心；新目标评分{alternative['score']:g}，"
            f"原目标评分{current['score']:g}，敌军压力"
            f"{int(alternative.get('enemy_strength', 0))}人"
        ),
    })
    return plan


def ensure_ai_military_strategy(state: GameState, regime_id: int) -> dict[str, Any]:
    plan = ai_military_plan(state, regime_id)
    if plan is not None and plan.get("status") == "completed" and _war_enemies(state, regime_id):
        return choose_ai_military_strategy(state, regime_id)
    # 兼容旧存档中的全国补给计划：单支军队抵达补给点或恢复两个月粮食后，
    # 不再等待四个月复核，立即恢复原战略。新计划已不再生成全局 resupply。
    if plan is not None and plan.get("kind") == "resupply":
        target_army = state.armies.get(int(plan.get("target_army_id") or 0))
        health = supply_line_health(state, target_army) if target_army is not None else None
        reached_depot = bool(
            target_army is not None
            and health is not None
            and health.get("depot_city_id") is not None
            and int(health["depot_city_id"]) == int(target_army.location_id)
        )
        recovered = bool(health is not None and float(health["supply_months"]) >= 2)
        if target_army is None or reached_depot or recovered:
            resume_kind = plan.get("resume_kind")
            resume_target = int(plan.get("resume_target_city_id") or 0)
            if resume_kind and resume_target:
                plan.update({
                    "kind": str(resume_kind),
                    "target_city_id": resume_target,
                    "status": "active",
                    "reason": "补给军队已抵达补给点，立即恢复原战略",
                })
                plan.pop("target_army_id", None)
                plan.pop("resume_kind", None)
                plan.pop("resume_target_city_id", None)
                return plan
            return choose_ai_military_strategy(state, regime_id)
    if plan is None or month_index(state) >= int(plan.get("review_month", -1)):
        return choose_ai_military_strategy(state, regime_id)
    return _retarget_weak_lost_homeland(state, regime_id, plan)


def _can_attack(state: GameState, army: Army, target_city: int, avoid_water: bool) -> bool:
    defenders = [
        other for other in state.armies.values()
        if other.location_id == target_city and other.regime_id != army.regime_id and state.at_war(army.regime_id, other.regime_id)
    ]
    if not defenders:
        return False
    local_attackers = sum(
        army_readiness_strength(state, other)
        for other in state.armies.values()
        if other.location_id == army.location_id and other.regime_id == army.regime_id
    )
    defense = sum(army_readiness_strength(state, other) for other in defenders)
    defense *= 1 + int(state.cities[target_city].get("defense", 0)) / 100
    required_ratio = 1.25 if avoid_water and city_water_complexity(state, target_city) >= 0.5 else 0.9
    if local_attackers < defense * required_ratio:
        return False
    assessment = ai_attack_assessment(state, army, target_city)
    state.flags.setdefault("v12_ai_attack_assessments", {})[str(int(army.id))] = {
        **assessment,
        "month": month_index(state),
        "target_city_id": int(target_city),
    }
    return bool(assessment["allowed"])


def ai_attack_assessment(state: GameState, army: Army, target_city: int) -> dict[str, Any]:
    """Forecast casualty support loss and decide whether an AI attack is sustainable."""
    support = int(state.regimes[army.regime_id].get("war_support", 0))
    try:
        estimate = estimate_battle_losses(state, army.id, int(target_city))
    except RuleError:
        return {"allowed": False, "reason": "无法形成合法进攻", "support_after": support}
    from ...rules.ai_modifiers import ai_difficulty_war_support_loss_multiplier

    multiplier = ai_difficulty_war_support_loss_multiplier(state, army.regime_id)
    progress = float(
        state.flags.get("v12_war_support_casualty_progress", {}).get(str(int(army.regime_id)), 0.0)
    )
    expected_losses = int(estimate["attacker_losses"])
    support_loss = int(progress + expected_losses / 500 * multiplier + 1e-9)
    support_after = max(0, support - support_loss)
    favorable_exchange = int(estimate["defender_losses"]) >= max(1, expected_losses) * 1.25
    if support < 30:
        allowed = False
        reason = "战争支持度低于30，停止主动攻击并优先保存军队"
    elif support < 50:
        allowed = support_loss <= 1 and support_after >= 30 and favorable_exchange
        reason = (
            "低战争支持度下仅允许预计损失不超过1点且交换比有利的攻击"
            if not allowed else "预计战损很低且交换比有利"
        )
    else:
        allowed = support_after >= 25
        reason = "预计攻击后仍保有战争支持度安全余量" if allowed else "预计战损可能使战争支持度接近投降线"
    return {
        "allowed": bool(allowed),
        "reason": reason,
        "war_support": support,
        "support_loss": support_loss,
        "support_after": support_after,
        "attacker_losses": expected_losses,
        "defender_losses": int(estimate["defender_losses"]),
    }


def _movement_commitment_allows(
    state: GameState,
    army: Army,
    next_city: int,
    target_city: int,
    *,
    urgent: bool,
) -> bool:
    if urgent:
        return True
    history = state.flags.setdefault("v12_ai_army_movement_commitments", {}).get(str(int(army.id)), {})
    if not history:
        return True
    now = month_index(state)
    reversing = (
        int(history.get("to_city_id", -1)) == int(army.location_id)
        and int(history.get("from_city_id", -1)) == int(next_city)
    )
    same_mission = int(history.get("target_city_id", 0)) == int(target_city)
    return not (
        reversing
        and not same_mission
        and now < int(history.get("locked_until_month", -1))
    )


def _record_movement_commitment(
    state: GameState,
    army: Army,
    origin: int,
    target_city: int,
    mission_kind: str,
) -> None:
    state.flags.setdefault("v12_ai_army_movement_commitments", {})[str(int(army.id))] = {
        "army_id": int(army.id),
        "from_city_id": int(origin),
        "to_city_id": int(army.location_id),
        "target_city_id": int(target_city),
        "mission_kind": str(mission_kind),
        "month": month_index(state),
        "locked_until_month": month_index(state) + ARMY_TASK_COMMITMENT_MONTHS,
    }


def _step_toward(
    state: GameState,
    army: Army,
    target_city: int,
    *,
    avoid_water: bool,
    maximum_cavalry_water_avoidance: bool,
    allow_attack: bool,
    rng: random.Random,
    urgent: bool = False,
    mission_kind: str = "strategic",
) -> bool:
    if army.location_id == target_city or army.action_points <= 0:
        return False
    forbidden_cities = (
        enemy_naval_threatened_cities(state, army.regime_id)
        if maximum_cavalry_water_avoidance and _has_cavalry(army)
        else set()
    )
    path = _strategic_path(
        state,
        army.location_id,
        target_city,
        army.regime_id,
        avoid_water=avoid_water,
        army=army,
        forbidden_cities=forbidden_cities,
    )
    if not path or len(path) < 2:
        return False
    next_city = int(path[1])
    if not _movement_commitment_allows(
        state, army, next_city, target_city, urgent=urgent
    ):
        return False
    next_controller = city_controller(state, next_city)
    if army.regime_id == 2 and state.year < 427 and state.regimes.get(next_controller, {}).get("name") == "胡夏":
        return False
    if any(option[0] == next_city for option in legal_attacks(state, army.id)):
        if allow_attack and _can_attack(state, army, next_city, avoid_water):
            try:
                origin = int(army.location_id)
                attack(state, army.id, next_city, rng)
                if army.id in state.armies:
                    _record_movement_commitment(state, army, origin, target_city, mission_kind)
                return True
            except (RuleError, ValueError):
                return False
        return False
    if any(option[0] == next_city for option in legal_moves(state, army.id)):
        try:
            origin = int(army.location_id)
            march(state, army.id, next_city)
            _record_movement_commitment(state, army, origin, target_city, mission_kind)
            return True
        except (RuleError, ValueError):
            return False
    return False


def _emergency_supply_action(
    state: GameState,
    army: Army,
    rng: random.Random,
    maximum_cavalry_water_avoidance: bool,
) -> bool:
    health = supply_line_health(state, army)
    if float(health["supply_months"]) > 1 and int(health["health"]) >= 20:
        return False
    depot = health.get("depot_city_id")
    if depot is None or int(depot) == army.location_id:
        return False
    return _step_toward(
        state,
        army,
        int(depot),
        avoid_water=maximum_cavalry_water_avoidance and _has_cavalry(army),
        maximum_cavalry_water_avoidance=maximum_cavalry_water_avoidance,
        allow_attack=False,
        rng=rng,
        urgent=True,
        mission_kind="emergency_resupply",
    )


def _capital_guard_id(state: GameState, regime_id: int) -> int | None:
    capital = int(state.regimes[regime_id].get("capital") or 0)
    candidates = [army for army in _armies(state, regime_id) if army.location_id == capital]
    return max(
        candidates,
        key=lambda army: (army_readiness_strength(state, army), army.soldiers, -army.id),
    ).id if candidates else None


def _local_fallback_city(state: GameState, regime_id: int, from_city: int) -> int | None:
    """Find the nearest controlled capital or fortified node behind the local front."""
    source_region = int(state.cities.get(int(from_city), {}).get("region_id", 0))
    national_capital = int(state.regimes[regime_id].get("capital") or 0)
    candidates: list[tuple[int, int, int, int]] = []
    probe = next((army for army in _armies(state, regime_id) if army.location_id == from_city), None)
    for city_id, city in state.cities.items():
        city_id = int(city_id)
        if city_id == from_city or city_controller(state, city_id) != regime_id:
            continue
        if not (city.get("capital") or int(city.get("defense", 0)) >= HIGH_DEFENSE_THRESHOLD or city_id == national_capital):
            continue
        path = _strategic_path(
            state,
            from_city,
            city_id,
            regime_id,
            avoid_water=False,
            army=probe,
        )
        if not path:
            continue
        same_region = int(city.get("region_id", 0)) == source_region
        candidates.append((0 if same_region else 1, len(path) - 1, -int(city.get("defense", 0)), city_id))
    if candidates:
        return min(candidates)[3]
    return national_capital if national_capital and national_capital != from_city else None


def evaluate_local_military_strategies(
    state: GameState,
    regime_id: int,
    grand_plan: dict[str, Any] | None = None,
) -> dict[int, dict[str, Any]]:
    """Re-evaluate every controlled region each month without replacing the grand strategy."""
    grand_plan = grand_plan or ai_military_plan(state, regime_id) or {}
    grand_target = int(grand_plan.get("target_city_id") or 0)
    enemies = _war_enemies(state, regime_id)
    records: dict[int, dict[str, Any]] = {}
    controlled_regions = {
        int(region_id) for region_id, region in state.regions.items()
        if int(region.get("controller", 0)) == regime_id
    }
    controlled_regions.update(
        int(state.cities.get(int(army.location_id), {}).get("region_id", 0))
        for army in _armies(state, regime_id)
    )
    controlled_regions.discard(0)
    for region_id in sorted(controlled_regions):
        local_armies = [
            army for army in _armies(state, regime_id)
            if int(state.cities.get(int(army.location_id), {}).get("region_id", 0)) == region_id
        ]
        record: dict[str, Any] = {
            "region_id": region_id,
            "month": month_index(state),
            "grand_strategy_kind": str(grand_plan.get("kind", "rest")),
            "grand_target_city_id": grand_target,
            "action": "observe",
            "reason": "本地区没有驻军，继续观察",
        }
        if not local_armies or not enemies:
            records[region_id] = record
            continue

        local_city_ids = {int(army.location_id) for army in local_armies}
        front_candidates: set[int] = set()
        enemy_pressure_cities: set[int] = set()
        for city_id in local_city_ids:
            for next_city, _road in neighbors(state, city_id):
                controller = city_controller(state, int(next_city))
                hostile_present = any(
                    other.location_id == int(next_city) and other.regime_id in enemies and other.soldiers > 0
                    for other in state.armies.values()
                )
                if controller in enemies or hostile_present:
                    front_candidates.add(int(next_city))
                if hostile_present:
                    enemy_pressure_cities.add(int(next_city))
        if not front_candidates:
            record.update({"action": "follow_strategy", "reason": "本地区不与敌军直接接触，服从大战略调动"})
            records[region_id] = record
            continue

        own_strength = sum(army_readiness_strength(state, army) for army in local_armies)
        health_rows = [supply_line_health(state, army) for army in local_armies]
        minimum_supply = min((float(row["supply_months"]) for row in health_rows), default=0.0)
        average_health = sum(int(row["health"]) for row in health_rows) / max(1, len(health_rows))
        current_defense = max(int(state.cities.get(city_id, {}).get("defense", 0)) for city_id in local_city_ids)
        defensive_strength = own_strength * (1 + current_defense / 100)
        enemy_pressure = sum(
            army_readiness_strength(state, army)
            for army in state.armies.values()
            if army.regime_id in enemies and army.location_id in enemy_pressure_cities
        )

        opportunities: list[tuple[float, int, int, int]] = []
        for target_city in front_candidates:
            reachable = False
            for army in local_armies:
                path = _strategic_path(
                    state,
                    army.location_id,
                    target_city,
                    regime_id,
                    avoid_water=bool(grand_plan.get("avoid_water")),
                    army=army,
                )
                if path and len(path) == 2:
                    reachable = True
                    break
            if not reachable:
                continue
            if grand_target:
                distances = []
                for army in local_armies:
                    path = _strategic_path(
                        state,
                        target_city,
                        grand_target,
                        regime_id,
                        avoid_water=bool(grand_plan.get("avoid_water")),
                        army=army,
                    )
                    if path:
                        distances.append(len(path) - 1)
                strategic_distance = min(distances, default=999)
            else:
                strategic_distance = 0
            defenders = [
                army for army in state.armies.values()
                if army.regime_id in enemies and army.location_id == target_city and army.soldiers > 0
            ]
            target_threat = sum(
                army_readiness_strength(state, army) for army in defenders
            ) * (1 + int(state.cities.get(target_city, {}).get("defense", 0)) / 100)
            # Nearby enemy reserves count at half strength: a 'safe' advance
            # must survive the obvious counterattack, not merely win the tile.
            reserve_cities = {int(city) for city, _road in neighbors(state, target_city)}
            target_threat += 0.5 * sum(
                army_readiness_strength(state, army)
                for army in state.armies.values()
                if army.regime_id in enemies and army.location_id in reserve_cities
            )
            strategic_value = (
                100 if state.cities.get(target_city, {}).get("capital") else 0
            ) + int(state.cities.get(target_city, {}).get("defense", 0))
            opportunities.append((target_threat, -strategic_value, strategic_distance, target_city))

        fallback = _local_fallback_city(state, regime_id, min(local_city_ids))
        war_support = int(state.regimes[regime_id].get("war_support", 0))
        if (
            fallback
            and (
                war_support < 30
                or enemy_pressure > max(1.0, defensive_strength * 1.3)
            )
        ):
            record.update({
                "action": "retreat",
                "fallback_city_id": int(fallback),
                "own_strength": round(own_strength, 1),
                "enemy_pressure": round(enemy_pressure, 1),
                "reason": (
                    "战争支持度低于30，主动缩短战线并保存军队"
                    if war_support < 30
                    else "局部敌军压力超过守军承受能力，向后方首府或关隘撤退"
                ),
            })
        elif opportunities:
            target_threat, _negative_value, _distance, advance_city = min(opportunities)
            safe = (
                minimum_supply >= 2
                and average_health >= 40
                and own_strength >= max(1.0, target_threat * 1.5)
                and (
                    war_support >= 50
                    or (war_support >= 30 and target_threat <= own_strength * 0.35)
                )
            )
            if safe:
                record.update({
                    "action": "advance",
                    "advance_city_id": int(advance_city),
                    "own_strength": round(own_strength, 1),
                    "enemy_pressure": round(target_threat, 1),
                    "reason": "局部兵力、补给和反击风险允许机会性推进，优先于大战略调动",
                })
            else:
                record.update({
                    "action": "hold",
                    "own_strength": round(own_strength, 1),
                    "enemy_pressure": round(target_threat, 1),
                    "reason": (
                        "战争支持度偏低，仅维持低损耗战线"
                        if war_support < 50
                        else "局部推进风险偏高，维持战线等待兵力或补给改善"
                    ),
                })
        else:
            record.update({"action": "follow_strategy", "reason": "局部没有可执行的行进目标，服从大战略调动"})
        records[region_id] = record

    state.flags.setdefault("v12_local_military_plans", {})[str(int(regime_id))] = {
        "month": month_index(state),
        "regions": {str(region_id): value for region_id, value in records.items()},
    }
    return records


def _deploy_defensive_guards(
    state: GameState,
    regime_id: int,
    armies: list[Army],
    unavailable: set[int],
    maximum_cavalry_water_avoidance: bool,
    rng: random.Random,
) -> tuple[set[int], list[str]]:
    priorities = ai_defense_priorities(state, regime_id)
    if len(armies) <= 1:
        return set(), []
    # 至多抽出约四分之一部队守备，防止防御逻辑吞掉全部战略机动力量。
    site_limit = min(len(priorities), max(1, len(armies) // 4))
    protected: set[int] = set()
    actions: list[str] = []
    capital_guard = _capital_guard_id(state, regime_id)

    # 已驻扎在首府或高城防关隘的部队只保留一支最小编制，其余兵力投入前线。
    # 这样不会为远离战场的每一座城另行抽调军队，也不会把已有要塞完全撤空。
    strategic_sites = {
        int(army.location_id)
        for army in armies
        if state.cities.get(int(army.location_id), {}).get("capital")
        or int(state.cities.get(int(army.location_id), {}).get("defense", 0)) >= HIGH_DEFENSE_THRESHOLD
    }
    for city_id in sorted(strategic_sites):
        present = [
            army for army in armies
            if army.id not in unavailable | protected and army.location_id == city_id
        ]
        if present:
            city = state.cities.get(city_id, {})
            if city_id == int(state.regimes[regime_id].get("capital") or 0):
                minimum = MINIMUM_GARRISON_STRENGTH["national_capital"]
            elif city.get("capital"):
                minimum = MINIMUM_GARRISON_STRENGTH["region_capital"]
            else:
                minimum = MINIMUM_GARRISON_STRENGTH["fortified_pass"]
            adequate = [army for army in present if army.soldiers >= minimum]
            guard = (
                min(
                    adequate,
                    key=lambda army: (army.soldiers, -army_readiness_strength(state, army), army.id),
                )
                if adequate
                else max(present, key=lambda army: (army_readiness_strength(state, army), army.soldiers, -army.id))
            )
            protected.add(guard.id)

    for priority in priorities[:site_limit]:
        target = int(priority["city_id"])
        minimum = MINIMUM_GARRISON_STRENGTH.get(str(priority["kind"]), 3_000)
        present = [
            army for army in armies
            if army.id not in unavailable and army.location_id == target
        ]
        protected_here = sum(army.soldiers for army in present if army.id in protected)
        for guard in sorted(
            (army for army in present if army.id not in protected),
            key=lambda army: (army.soldiers, army.id),
        ):
            if protected_here >= minimum:
                break
            protected.add(guard.id)
            protected_here += guard.soldiers
        if protected_here >= minimum:
            continue
        candidates: list[tuple[int, float, Army]] = []
        for army in armies:
            if army.id in unavailable | protected:
                continue
            if army.id == capital_guard and army.location_id != target:
                continue
            forbidden = (
                enemy_naval_threatened_cities(state, regime_id)
                if maximum_cavalry_water_avoidance and _has_cavalry(army)
                else set()
            )
            path = _strategic_path(
                state,
                army.location_id,
                target,
                regime_id,
                avoid_water=maximum_cavalry_water_avoidance and _has_cavalry(army),
                army=army,
                forbidden_cities=forbidden,
            )
            if path:
                candidates.append((len(path) - 1, -army_readiness_strength(state, army), army))
        if not candidates:
            continue
        guard = min(candidates, key=lambda item: (item[0], item[1], item[2].id))[2]
        protected.add(guard.id)
        old_location = guard.location_id
        if _step_toward(
            state,
            guard,
            target,
            avoid_water=maximum_cavalry_water_avoidance and _has_cavalry(guard),
            maximum_cavalry_water_avoidance=maximum_cavalry_water_avoidance,
            allow_attack=True,
            rng=rng,
            urgent=True,
            mission_kind="intercept_defense",
        ):
            actions.append(
                f"protect_{priority['kind']}:{guard.id}:{old_location}->{guard.location_id}:target={target}"
            )
    return protected, actions


def _select_task_force(
    state: GameState,
    regime_id: int,
    requested_target: int,
    eligible: list[Army],
    *,
    avoid_water: bool,
) -> tuple[int, int, set[int]]:
    """Create or retain a two-month, two-to-five-army operational group."""
    now = month_index(state)
    records = state.flags.setdefault("v12_ai_task_forces", {})
    current = records.get(str(int(regime_id)), {})
    eligible_ids = {army.id for army in eligible}
    surviving = {
        int(army_id) for army_id in current.get("member_army_ids", [])
        if int(army_id) in state.armies
        and state.armies[int(army_id)].regime_id == regime_id
        and state.armies[int(army_id)].soldiers > 0
        and int(army_id) in eligible_ids
    }
    current_target = int(current.get("target_city_id", 0))
    if (
        current_target in state.cities
        and now < int(current.get("commit_until_month", -1))
        and surviving
        and city_controller(state, current_target) != regime_id
    ):
        return current_target, int(current.get("rally_city_id", current_target)), surviving

    ranked: list[tuple[int, float, int, Army]] = []
    for army in eligible:
        path = _strategic_path(
            state, army.location_id, requested_target, regime_id,
            avoid_water=avoid_water, army=army,
        )
        if path:
            ranked.append((len(path) - 1, -army_readiness_strength(state, army), army.id, army))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    defenders = [
        army for army in state.armies.values()
        if army.location_id == requested_target and army.regime_id in _war_enemies(state, regime_id)
    ]
    target_strength = sum(army_readiness_strength(state, army) for army in defenders)
    target_strength *= 1 + int(state.cities.get(requested_target, {}).get("defense", 0)) / 100
    required = max(4_000.0, target_strength * 1.35)
    members: list[Army] = []
    accumulated = 0.0
    for _distance, _negative_strength, _army_id, army in ranked:
        members.append(army)
        accumulated += army_readiness_strength(state, army)
        if (
            len(members) >= TASK_FORCE_MIN_ARMIES
            and accumulated >= required
        ) or len(members) >= TASK_FORCE_MAX_ARMIES:
            break
    if not members and ranked:
        members = [ranked[0][3]]

    rally = requested_target
    if defenders and members:
        approaches: list[tuple[float, int]] = []
        for city_id, _road in neighbors(state, requested_target):
            if any(
                other.location_id == city_id and other.regime_id in _war_enemies(state, regime_id)
                for other in state.armies.values()
            ):
                continue
            total_distance = 0
            reachable = True
            for army in members:
                path = _strategic_path(
                    state, army.location_id, int(city_id), regime_id,
                    avoid_water=avoid_water, army=army,
                )
                if not path:
                    reachable = False
                    break
                total_distance += _strategic_path_cost(state, path, avoid_water)
            if reachable:
                approaches.append((total_distance, int(city_id)))
        if approaches:
            rally = min(approaches)[1]

    roles = ("先锋", "主力", "主力", "预备队", "补给线护卫")
    record = {
        "regime_id": int(regime_id),
        "target_city_id": int(requested_target),
        "rally_city_id": int(rally),
        "member_army_ids": [army.id for army in members],
        "roles": {str(army.id): roles[index] for index, army in enumerate(members)},
        "created_month": now,
        "commit_until_month": now + ARMY_TASK_COMMITMENT_MONTHS,
        "required_effective_strength": round(required, 2),
        "assigned_effective_strength": round(accumulated, 2),
        "status": "assembling" if members else "awaiting_reserve",
    }
    records[str(int(regime_id))] = record
    shortage = max(0, int(math.ceil(required - accumulated)))
    state.flags.setdefault("v12_ai_mobile_reserve_shortage", {})[str(int(regime_id))] = {
        "month": now,
        "target_city_id": int(requested_target),
        "soldiers": shortage,
    }
    return int(requested_target), int(rally), {army.id for army in members}


def run_ai_military_strategy(
    state: GameState,
    regime_id: int,
    rng: random.Random | None = None,
) -> list[str]:
    """Execute monthly tactics without changing the saved four-month strategic goal."""
    if regime_id == state.player_regime_id or is_regime_eliminated(state, regime_id):
        return []
    chooser = rng or random.Random(state.turn_number * 10_007 + regime_id)
    actions: list[str] = []
    _update_enemy_movement_tracks(state, regime_id)
    created_reserves = _create_mobile_reserves(state, regime_id)
    actions.extend(f"create_mobile_reserve:{army_id}" for army_id in created_reserves)
    armies = _armies(state, regime_id)
    if not armies:
        plan = ensure_ai_military_strategy(state, regime_id)
        plan["status"] = "blocked"
        return actions
    # 有人力时先补充首都、州府、关隘与前线，再照顾其中士气更低的部队。
    # 包围中的部队不能凭空接收补员，必须先突围或解围。
    manpower_multiplier = ai_difficulty_resource_multiplier(state)
    for army in sorted(armies, key=lambda item: army_support_priority(state, item)):
        need = reinforcement_need(army)
        if need <= 0 or is_army_surrounded(state, army.id):
            continue
        cost = max(1, int(math.ceil(need * manpower_multiplier)))
        if manpower_balance(state, regime_id) < cost:
            continue
        try:
            reinforce_army(state, army.id, manpower_cost_multiplier=manpower_multiplier)
            actions.append(f"reinforce:{army.id}:{need}:manpower={cost}")
        except RuleError:
            continue

    # AI must actively restore shattered formations. Otherwise zero-morale
    # armies occupy forts and inflate national strength forever despite being
    # unable to survive one battle. Strategic positions receive food first.
    for army in sorted(armies, key=lambda item: army_support_priority(state, item)):
        if army.morale >= 60 or army.rewarded_this_turn:
            continue
        if city_controller(state, army.location_id) != regime_id:
            continue
        try:
            before = int(army.morale)
            reward(state, army.id)
            actions.append(f"restore_morale:{army.id}:{before}->{army.morale}")
        except RuleError:
            continue
    plan = ensure_ai_military_strategy(state, regime_id)
    if regime_id == 2:
        taiwu = next(
            (
                person for person in state.persons.values()
                if state.person_name(int(person["id"])) == "拓跋焘"
                and int(person.get("status", 0)) != 4
                and int(person.get("birth_year", 0) or 0) <= state.year
            ),
            None,
        )
        if taiwu:
            taiwu_id = int(taiwu["id"])
            current = next((army for army in armies if army.commander == taiwu_id), None)
            preferred = max(armies, key=lambda army: (army.soldiers, army.id))
            if current is not preferred:
                if current:
                    current.commander = None
                preferred.commander = taiwu_id
                taiwu["location_id"] = preferred.location_id

    # 极端缺粮只改变当月战术，不会改写四个月战略提纲。
    emergency_armies: set[int] = set()
    current_own = _composition(armies)
    current_enemy = _composition([
        army for army in state.armies.values()
        if army.regime_id in _war_enemies(state, regime_id) and army.soldiers > 0
    ])
    # 战略目标四个月不变，但水军掩护若在周期中损失，骑兵禁区必须立即生效。
    current_naval_mismatch = int(current_enemy["naval"]) > int(current_own["naval"])
    maximum_cavalry_water_avoidance = bool(
        plan.get("maximum_cavalry_water_avoidance")
        or (int(current_own["cavalry"]) > 0 and current_naval_mismatch)
    )
    for army in armies:
        health = supply_line_health(state, army)
        supply_emergency = float(health["supply_months"]) <= 1 or int(health["health"]) < 20
        if not supply_emergency:
            continue
        emergency_armies.add(army.id)
        old_location = army.location_id
        if _emergency_supply_action(state, army, chooser, maximum_cavalry_water_avoidance):
            actions.append(f"emergency_resupply:{army.id}:{old_location}->{army.location_id}")

    local_plans = evaluate_local_military_strategies(state, regime_id, plan)
    defensive_armies, defensive_actions = _deploy_defensive_guards(
        state,
        regime_id,
        armies,
        emergency_armies,
        maximum_cavalry_water_avoidance,
        chooser,
    )
    actions.extend(defensive_actions)

    capital_guard = _capital_guard_id(state, regime_id)
    local_unavailable: set[int] = set()
    for army in armies:
        region_id = int(state.cities.get(int(army.location_id), {}).get("region_id", 0))
        local = local_plans.get(region_id, {})
        local_action = str(local.get("action", "follow_strategy"))
        if local_action == "hold":
            local_unavailable.add(army.id)
            continue
        if local_action != "retreat":
            continue
        local_unavailable.add(army.id)
        if army.id in emergency_armies | defensive_armies or army.id == capital_guard:
            continue
        fallback = int(local.get("fallback_city_id") or 0)
        if not fallback or fallback == army.location_id:
            continue
        old_location = army.location_id
        if _step_toward(
            state,
            army,
            fallback,
            avoid_water=maximum_cavalry_water_avoidance and _has_cavalry(army),
            maximum_cavalry_water_avoidance=maximum_cavalry_water_avoidance,
            allow_attack=False,
            rng=chooser,
            urgent=True,
            mission_kind="local_retreat",
        ):
            actions.append(f"local_retreat:{army.id}:{old_location}->{army.location_id}:target={fallback}")

    # A safe one-step local opportunity outranks the four-month grand target.
    # Only this month's movement is overridden; the saved strategy itself is
    # deliberately left untouched.  If every nearby formation is a protected
    # pass guard, one may sortie only when at least one other local army remains.
    for region_id, local in local_plans.items():
        if str(local.get("action")) != "advance":
            continue
        advance_city = int(local.get("advance_city_id") or 0)
        if not advance_city:
            continue
        region_armies = [
            army for army in armies
            if int(state.cities.get(int(army.location_id), {}).get("region_id", 0)) == int(region_id)
        ]
        local_unavailable.update(army.id for army in region_armies)
        candidates = [
            army for army in region_armies
            if army.id not in emergency_armies and army.id != capital_guard and army.action_points > 0
        ]
        mobile = [army for army in candidates if army.id not in defensive_armies]
        sortie_from_guard = False
        if not mobile and len(region_armies) >= 2:
            mobile = [army for army in candidates if army.id in defensive_armies]
            sortie_from_guard = True
        ranked: list[tuple[int, float, Army]] = []
        for army in mobile:
            path = _strategic_path(
                state,
                army.location_id,
                advance_city,
                regime_id,
                avoid_water=maximum_cavalry_water_avoidance and _has_cavalry(army),
                army=army,
                forbidden_cities=(
                    enemy_naval_threatened_cities(state, regime_id)
                    if maximum_cavalry_water_avoidance and _has_cavalry(army)
                    else None
                ),
            )
            if path:
                ranked.append((len(path) - 1, -army_readiness_strength(state, army), army))
        limit = 1 if sortie_from_guard else 2
        successful = 0
        for _distance, _negative_strength, army in sorted(ranked, key=lambda item: (item[0], item[1], item[2].id)):
            if successful >= limit:
                break
            old_location = army.location_id
            if _step_toward(
                state,
                army,
                advance_city,
                avoid_water=maximum_cavalry_water_avoidance and _has_cavalry(army),
                maximum_cavalry_water_avoidance=maximum_cavalry_water_avoidance,
                allow_attack=True,
                rng=chooser,
                mission_kind="local_advance",
            ):
                successful += 1
                actions.append(
                    f"local_advance:{army.id}:{old_location}->{army.location_id}:target={advance_city}"
                )

    if plan.get("status") in {"idle", "blocked", "completed"}:
        return actions
    kind = str(plan.get("kind"))
    target = int(plan.get("target_city_id") or 0)
    if kind == "rest" or not target:
        return actions

    if kind == "resupply":
        # 仅为无法恢复目标的旧存档兜底；健康军队不再被全国补给计划冻结。
        resume_kind = plan.get("resume_kind")
        resume_target = int(plan.get("resume_target_city_id") or 0)
        if resume_kind and resume_target:
            plan.update({"kind": str(resume_kind), "target_city_id": resume_target, "status": "active"})
            kind = str(resume_kind)
            target = resume_target
        else:
            return actions

    avoid_water = bool(plan.get("avoid_water"))
    if kind in {"consolidate", "defend_capital", "defend_frontier"}:
        desired_guards = 2 if len(armies) >= 3 else 1
        present = sum(1 for army in armies if army.location_id == target)
        for army in sorted(armies, key=lambda item: (-item.soldiers, item.id)):
            if army.id in emergency_armies | defensive_armies | local_unavailable or army.location_id == target or present >= desired_guards:
                continue
            old_location = army.location_id
            if _step_toward(
                state,
                army,
                target,
                avoid_water=avoid_water,
                maximum_cavalry_water_avoidance=maximum_cavalry_water_avoidance,
                allow_attack=True,
                rng=chooser,
                urgent=kind in {"defend_capital", "defend_frontier"},
                mission_kind=kind,
            ):
                actions.append(f"{kind}:{army.id}:{old_location}->{army.location_id}")
                if army.location_id == target:
                    present += 1
        if present >= desired_guards:
            plan["status"] = "holding"
        return actions

    if kind == "attack_region":
        from .climate import is_winter_month, months_until_winter

        winter_naval_caution = is_winter_month(state) or months_until_winter(state) <= 2
        task_eligible = [
            army for army in armies
            if army.id not in emergency_armies | defensive_armies | local_unavailable
            and army.id != capital_guard
            and army.action_points > 0
            and army.morale >= 30
            and float(supply_line_health(state, army)["supply_months"]) >= 2
            and int(supply_line_health(state, army)["health"]) >= 40
        ]
        operation_target, rally_city, primary_armies = _select_task_force(
            state,
            regime_id,
            target,
            task_eligible,
            avoid_water=avoid_water,
        )
        task_record = state.flags.get("v12_ai_task_forces", {}).get(str(int(regime_id)), {})
        defenders_at_operation = [
            army for army in state.armies.values()
            if army.location_id == operation_target and army.regime_id in _war_enemies(state, regime_id)
        ]
        assembled = [
            state.armies[army_id] for army_id in primary_armies
            if army_id in state.armies and state.armies[army_id].location_id == rally_city
        ]
        assembled_strength = sum(army_readiness_strength(state, army) for army in assembled)
        ready_to_assault = (
            not defenders_at_operation
            or rally_city == operation_target
            or (
                len(assembled) >= min(TASK_FORCE_MIN_ARMIES, len(primary_armies))
                and assembled_strength >= float(task_record.get("required_effective_strength", 0)) * 0.9
            )
        )
        secondary_armies: set[int] = set()
        secondary_targets = [
            int(city_id) for city_id in plan.get("secondary_target_city_ids", [])
            if int(city_id) in state.cities and int(city_id) != target
        ]
        # 兵力优势足以开辟第二方向时，每个次要失地首府派两支最近的机动军包围；
        # 首府、关隘最低守军以及断粮军队均不会被抽走。
        for secondary_target in secondary_targets:
            candidates: list[tuple[int, int, Army]] = []
            for army in armies:
                if army.id in emergency_armies | defensive_armies | secondary_armies | local_unavailable | primary_armies or army.id == capital_guard:
                    continue
                health = supply_line_health(state, army)
                if float(health["supply_months"]) < 2 or int(health["health"]) < 40:
                    continue
                path = _strategic_path(
                    state,
                    army.location_id,
                    secondary_target,
                    regime_id,
                    avoid_water=avoid_water,
                    army=army,
                    forbidden_cities=(
                        enemy_naval_threatened_cities(state, regime_id)
                        if maximum_cavalry_water_avoidance and _has_cavalry(army)
                        else None
                    ),
                )
                if path:
                    candidates.append((len(path) - 1, -army.soldiers, army))
            for _distance, _negative_strength, army in sorted(
                candidates,
                key=lambda item: (item[0], item[1], item[2].id),
            )[:2]:
                old_location = army.location_id
                secondary_armies.add(army.id)
                if _step_toward(
                    state,
                    army,
                    secondary_target,
                    avoid_water=avoid_water,
                    maximum_cavalry_water_avoidance=maximum_cavalry_water_avoidance,
                    allow_attack=True,
                    rng=chooser,
                    mission_kind="secondary_task_force",
                ):
                    actions.append(f"secondary_attack:{army.id}:{old_location}->{army.location_id}:target={secondary_target}")
        for army in sorted(armies, key=lambda item: (-army_readiness_strength(state, item), item.id)):
            if army.id not in primary_armies:
                continue
            if winter_naval_caution and army.army_type == 1:
                continue
            health = supply_line_health(state, army)
            if float(health["supply_months"]) < 2 or int(health["health"]) < 40:
                continue
            old_location = army.location_id
            army_target = operation_target if ready_to_assault and army.location_id == rally_city else rally_city
            if army.location_id == rally_city and not ready_to_assault:
                continue
            if _step_toward(
                state,
                army,
                army_target,
                avoid_water=avoid_water,
                maximum_cavalry_water_avoidance=maximum_cavalry_water_avoidance,
                allow_attack=True,
                rng=chooser,
                mission_kind="primary_task_force",
            ):
                actions.append(
                    f"attack:{army.id}:{old_location}->{army.location_id}:"
                    f"target={operation_target}:rally={rally_city}"
                )
        hostile_at_target = any(
            army.location_id == target and army.regime_id in _war_enemies(state, regime_id)
            for army in state.armies.values()
        )
        own_at_target = any(
            army.location_id == target and army.regime_id == regime_id
            for army in state.armies.values()
        )
        if city_controller(state, target) == regime_id or (own_at_target and not hostile_at_target):
            plan["status"] = "completed"
        return actions
    return actions
