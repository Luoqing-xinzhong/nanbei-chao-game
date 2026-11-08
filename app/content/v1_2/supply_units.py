from __future__ import annotations

from typing import Any

from ...models import GameState
from ...rules.common import RuleError, is_regime_eliminated
from ...rules.military import city_controller, effective_road_type, neighbors
from .economy import army_supply_capacity, economy_data, format_resource, region_economy, warehouse_room


SUPPLY_UNIT_MONTHLY_CONSUMPTION = 0.10
SUPPLY_UNIT_MAX_AGE = 12
SUPPLY_UNIT_MAX_ACTION_POINTS = 1.0


def supply_units(state: GameState, regime_id: int | None = None) -> list[dict[str, Any]]:
    data = economy_data(state)
    units = data.setdefault("supply_units", [])
    data.setdefault("next_supply_unit_id", max((int(unit.get("id", 0)) for unit in units), default=0) + 1)
    for unit in units:
        unit.setdefault("age", 0)
        unit.setdefault("action_points", SUPPLY_UNIT_MAX_ACTION_POINTS)
        unit.setdefault("max_action_points", SUPPLY_UNIT_MAX_ACTION_POINTS)
    if regime_id is None:
        return units
    return [unit for unit in units if int(unit.get("regime_id", 0)) == int(regime_id)]


def get_supply_unit(state: GameState, unit_id: int) -> dict[str, Any]:
    unit = next((unit for unit in supply_units(state) if int(unit.get("id", 0)) == int(unit_id)), None)
    if unit is None:
        raise RuleError("补给队不存在或已经被摧毁")
    return unit


def create_supply_unit(state: GameState, regime_id: int, city_id: int, amount: float) -> dict[str, Any]:
    if str(state.flags.get("content_version", "1.1")) != "1.2":
        raise RuleError("补给队仅在1.2版本中可用")
    city = state.cities.get(int(city_id))
    if not city or not city.get("capital"):
        raise RuleError("补给队只能在地区首府创建")
    region_id = int(city.get("region_id", 0))
    region = state.regions.get(region_id)
    if not region or int(region.get("controller", 0)) != int(regime_id) or city_controller(state, city_id) != int(regime_id):
        raise RuleError("只能在本国实际控制的地区首府创建补给队")
    planned = round(float(amount), 2)
    if planned <= 0:
        raise RuleError("装载粮食必须大于0")
    record = region_economy(state, region_id)
    available = float(record["warehouse"].get("food", 0.0))
    if planned > available + 1e-9:
        raise RuleError("计划装载量不能超过当地府库粮食")
    actual = round(planned * max(0.0, min(1.0, float(record.get("control", 0)) / 100)), 2)
    if actual <= 0:
        raise RuleError("地区控制度过低，无法组织补给队")
    record["warehouse"]["food"] = round(available - actual, 2)
    data = economy_data(state)
    units = supply_units(state)
    unit_id = int(data["next_supply_unit_id"])
    data["next_supply_unit_id"] = unit_id + 1
    unit = {
        "id": unit_id,
        "regime_id": int(regime_id),
        "location_id": int(city_id),
        "food": actual,
        "age": 0,
        "action_points": SUPPLY_UNIT_MAX_ACTION_POINTS,
        "max_action_points": SUPPLY_UNIT_MAX_ACTION_POINTS,
    }
    units.append(unit)
    state.add_log(
        f"在{state.city_name(city_id)}创建补给队#{unit_id}：计划装粮{format_resource(planned)}，"
        f"受地区控制度影响实际装粮{format_resource(actual)}。"
    )
    return unit


def _land_movement_cost(road_type: int) -> float | None:
    return {1: 1.0, 2: 1.0, 3: 0.3, 4: 0.5}.get(int(road_type))


def legal_supply_moves(state: GameState, unit_id: int) -> list[tuple[int, int, float]]:
    unit = get_supply_unit(state, unit_id)
    owner = int(unit["regime_id"])
    action_points = float(unit.get("action_points", 0.0))
    best_by_target: dict[int, tuple[int, int, float]] = {}
    for target, road in neighbors(state, int(unit["location_id"])):
        road_type = effective_road_type(state, road)
        cost = _land_movement_cost(road_type)
        if cost is None or cost > action_points + 1e-9:
            continue
        enemy_armies = [
            army for army in state.armies.values()
            if army.soldiers > 0 and army.location_id == target and army.regime_id != owner
        ]
        controller = city_controller(state, target)
        if enemy_armies or not (controller in {0, owner} or state.at_war(owner, controller)):
            continue
        candidate = (int(target), int(road_type), float(cost))
        current = best_by_target.get(int(target))
        if current is None or (candidate[2], candidate[1]) < (current[2], current[1]):
            best_by_target[int(target)] = candidate
    return list(best_by_target.values())


def march_supply_unit(state: GameState, unit_id: int, target_city_id: int) -> str:
    unit = get_supply_unit(state, unit_id)
    option = next((item for item in legal_supply_moves(state, unit_id) if item[0] == int(target_city_id)), None)
    if option is None:
        raise RuleError("目标不是补给队可到达的相邻城市，或行动力不足")
    unit["location_id"] = int(target_city_id)
    unit["action_points"] = round(float(unit.get("action_points", 0.0)) - option[2], 2)
    message = f"补给队#{unit_id}行进至{state.city_name(target_city_id)}，剩余行动力{unit['action_points']:g}。"
    state.add_log(message)
    return message


def supply_targets(state: GameState, unit_id: int) -> list[tuple[int, float]]:
    unit = get_supply_unit(state, unit_id)
    owner = int(unit["regime_id"])
    adjacent = {int(city_id) for city_id, _road in neighbors(state, int(unit["location_id"]))}
    result: list[tuple[int, float]] = []
    for army in state.armies.values():
        if army.regime_id != owner or army.soldiers <= 0 or army.location_id not in adjacent:
            continue
        room = round(max(0.0, army_supply_capacity(army) - float(army.supply_food)), 2)
        if room > 0:
            result.append((int(army.id), room))
    return result


def supply_army(state: GameState, unit_id: int, army_id: int, amount: float) -> str:
    unit = get_supply_unit(state, unit_id)
    targets = dict(supply_targets(state, unit_id))
    if int(army_id) not in targets:
        raise RuleError("只能补给道路相连一格内、仍有补给空间的己方军队")
    planned = round(float(amount), 2)
    if planned <= 0 or planned > float(unit.get("food", 0.0)) + 1e-9:
        raise RuleError("补给量不能超过补给队现有粮食")
    if planned > float(targets[int(army_id)]) + 1e-9:
        raise RuleError("补给量不能超过目标军队的随军粮容量")
    army = state.armies[int(army_id)]
    army.supply_food = round(float(army.supply_food) + planned, 2)
    unit["food"] = round(float(unit["food"]) - planned, 2)
    message = f"补给队#{unit_id}向军队#{army_id}交付粮食{format_resource(planned)}。"
    state.add_log(message)
    if float(unit["food"]) <= 0:
        supply_units(state).remove(unit)
        message += " 补给队粮食耗尽，编制自动撤销。"
        state.add_log(f"补给队#{unit_id}粮食耗尽，自动撤销。")
    return message


def disband_supply_unit(state: GameState, unit_id: int) -> str:
    unit = get_supply_unit(state, unit_id)
    supply_units(state).remove(unit)
    message = f"补给队#{unit_id}已主动撤销，剩余粮食不予返还。"
    state.add_log(message)
    return message


def _deliver_looted_food(state: GameState, regime_id: int, amount: float) -> float:
    capital = int(state.regimes.get(int(regime_id), {}).get("capital") or 0)
    region_id = int(state.cities.get(capital, {}).get("region_id", 0))
    if region_id not in state.regions:
        return 0.0
    record = region_economy(state, region_id)
    accepted = min(float(amount), warehouse_room(state, region_id, "food"))
    record["warehouse"]["food"] = round(float(record["warehouse"].get("food", 0.0)) + accepted, 2)
    return round(accepted, 2)


def settle_supply_units(state: GameState) -> list[int]:
    """Apply monthly consumption, expiry, capture and action-point recovery."""
    survivors: list[dict[str, Any]] = []
    removed: list[int] = []
    for unit in list(supply_units(state)):
        unit_id = int(unit["id"])
        owner = int(unit.get("regime_id", 0))
        if is_regime_eliminated(state, owner):
            removed.append(unit_id)
            continue
        unit["age"] = int(unit.get("age", 0)) + 1
        previous = float(unit.get("food", 0.0))
        consumed = round(previous * SUPPLY_UNIT_MONTHLY_CONSUMPTION, 2)
        unit["food"] = round(max(0.0, previous - consumed), 2)
        if owner == state.player_regime_id:
            state.add_log(f"补给队#{unit_id}月度自耗粮食{format_resource(consumed)}。")
        if int(unit["age"]) >= SUPPLY_UNIT_MAX_AGE:
            removed.append(unit_id)
            if owner == state.player_regime_id:
                state.add_log(f"补给队#{unit_id}服役已满一年，自动撤销。")
            continue
        if float(unit["food"]) <= 0:
            removed.append(unit_id)
            if owner == state.player_regime_id:
                state.add_log(f"补给队#{unit_id}粮食耗尽，自动摧毁。")
            continue
        hostile = next(
            (
                army for army in state.armies.values()
                if army.soldiers > 0
                and army.location_id == int(unit["location_id"])
                and army.regime_id != owner
                and state.at_war(owner, army.regime_id)
            ),
            None,
        )
        if hostile is not None:
            looted = _deliver_looted_food(state, hostile.regime_id, float(unit["food"]))
            removed.append(unit_id)
            if owner == state.player_regime_id or hostile.regime_id == state.player_regime_id:
                state.add_log(
                    f"补给队#{unit_id}在{state.city_name(int(unit['location_id']))}被军队#{hostile.id}劫掠，"
                    f"敌方首都接收粮食{format_resource(looted)}。"
                )
            continue
        unit["action_points"] = float(unit.get("max_action_points", SUPPLY_UNIT_MAX_ACTION_POINTS))
        survivors.append(unit)
    economy_data(state)["supply_units"] = survivors
    return removed
