from __future__ import annotations

import math
import random
from typing import Any

from ...models import GameState
from ...rules.common import RuleError, clamp
from ...rules.military import neighbors
from ..v1_2.economy import population_units, region_economy

V13_RULESET = "1.3"
CULTURE_SUPPLY_LEVELS = (0.0, 1.0, 1.25, 1.5, 1.75, 2.0)
CULTURE_MAINTENANCE = {
    "southern_han": 1.0,
    "northern_han": 1.5,
    "southern_tribal": 2.0,
    "xiongnu": 2.5,
    "xianbei": 3.0,
}
SOUTHERN_REGIONS = {
    "扬州", "淮南地区", "江州", "南雍州", "郢州", "荆州", "梁州", "益州",
    "湘州", "广州", "交州", "西南地区",
}

POETRY_TREE: dict[int, dict[str, Any]] = {
    1: {"name": "国风", "cost": 50, "requires": ()},
    2: {"name": "小雅", "cost": 75, "requires": (1,)},
    3: {"name": "大雅", "cost": 75, "requires": (1,)},
    4: {"name": "周颂", "cost": 100, "requires": (2, 3)},
    5: {"name": "商颂", "cost": 125, "requires": (4,)},
    6: {"name": "鲁颂", "cost": 125, "requires": (4,)},
    7: {"name": "诗之国", "cost": 150, "requires": (5, 6)},
}
CLASSIC_NAMES = {"poetry": "诗经", "documents": "尚书", "rites": "礼记", "changes": "易经", "spring_autumn": "春秋"}


def is_v13(state: GameState) -> bool:
    return str(state.flags.get("rules_version", "")) == V13_RULESET


def culture_data(state: GameState) -> dict[str, Any]:
    return state.flags.setdefault("v13_culture", {})


def culture_balance(state: GameState) -> float:
    return round(float(culture_data(state).setdefault("balance", 0.0)), 2)


def change_culture(state: GameState, amount: float) -> float:
    data = culture_data(state)
    data["balance"] = round(max(0.0, float(data.get("balance", 0.0)) + float(amount)), 2)
    return float(data["balance"])


def spend_culture(state: GameState, amount: float, purpose: str = "") -> None:
    discount = 0.5 if 7 in completed_poetry_nodes(state) else 0.0
    actual = round(float(amount) * (1.0 - discount), 2)
    if culture_balance(state) + 1e-9 < actual:
        raise RuleError(f"文化值不足：需要{actual:g}，现有{culture_balance(state):g}")
    change_culture(state, -actual)
    if purpose:
        state.add_log(f"{purpose}消耗文化值{actual:g}。")


def region_approval(state: GameState, region_id: int) -> int:
    if not is_v13(state):
        return 100
    return int(culture_data(state).setdefault("approval", {}).get(str(int(region_id)), 0))


def set_region_approval(state: GameState, region_id: int, value: int) -> int:
    value = int(clamp(int(value), 0, 100))
    culture_data(state).setdefault("approval", {})[str(int(region_id))] = value
    return value


def set_culture_supply(state: GameState, region_id: int, multiplier: float) -> float:
    value = float(multiplier)
    if value not in CULTURE_SUPPLY_LEVELS:
        raise RuleError("文化供给只能设为0、1、1.25、1.5、1.75或2倍")
    if int(state.regions[int(region_id)].get("controller", 0)) != state.player_regime_id:
        raise RuleError("只能调整本国实际控制地区的文化供给")
    region_economy(state, int(region_id))["culture_supply"] = value
    return value


def _building_slots(state: GameState, region_id: int) -> int:
    record = region_economy(state, region_id)
    calculated = 2 + len(population_units(state, region_id)) // 50
    record["building_slots"] = max(int(record.get("building_slots", 0)), calculated)
    return int(record["building_slots"])


def _slot_city_ids(state: GameState, region_id: int) -> list[int]:
    cities = sorted(
        (int(city_id) for city_id, city in state.cities.items() if int(city.get("region_id", 0)) == int(region_id)),
    )
    if not cities:
        return []
    capital = next((city_id for city_id in cities if state.cities[city_id].get("capital")), cities[0])
    ordered = [capital] + [city_id for city_id in cities if city_id != capital]
    return [ordered[index % len(ordered)] for index in range(_building_slots(state, region_id))]


def region_buildings(state: GameState, region_id: int) -> list[dict[str, Any]]:
    return culture_data(state).setdefault("buildings", {}).setdefault(str(int(region_id)), [])


def building_slot_status(state: GameState, region_id: int) -> list[dict[str, Any]]:
    """Return every building slot, including empty slots, in its display order."""
    region_id = int(region_id)
    slot_cities = _slot_city_ids(state, region_id)
    buildings = region_buildings(state, region_id)
    result: list[dict[str, Any]] = []
    for index, city_id in enumerate(slot_cities):
        building = buildings[index] if index < len(buildings) else None
        result.append(
            {
                "index": index + 1,
                "city_id": int(city_id),
                "building": building,
            }
        )
    return result


def school_level_cap(state: GameState, region_id: int) -> int:
    base = 10 if str(state.regions[region_id].get("name")) == "扬州" else 5
    nodes = completed_poetry_nodes(state)
    return base + (2 if 2 in nodes else 0) + (2 if 5 in nodes else 0)


def build_school(state: GameState, region_id: int, name: str | None = None) -> dict[str, Any]:
    region_id = int(region_id)
    region = state.regions.get(region_id)
    if not region or int(region.get("controller", 0)) != state.player_regime_id:
        raise RuleError("只能在本国实际控制地区修建学校")
    buildings = region_buildings(state, region_id)
    if any(item.get("type") == "school" for item in buildings):
        raise RuleError("一个地区只能修建一所学校")
    slots = _slot_city_ids(state, region_id)
    if len(buildings) >= len(slots):
        raise RuleError("该地区没有空余建筑槽")
    special = str(region.get("name")) == "扬州"
    base_cost = 20.0 if special else 10.0
    from ...rules.treasury import spend_treasury, treasury_balance
    from ..v1_2.economy import local_purchase_cost_multiplier

    cost = round(base_cost * local_purchase_cost_multiplier(state, region_id, state.player_regime_id), 2)
    if treasury_balance(state) < cost:
        raise RuleError(f"国库铜钱不足，需要{cost:g}")
    spend_treasury(state, state.player_regime_id, cost)
    building = {
        "id": int(culture_data(state).setdefault("next_building_id", 1)),
        "type": "school", "level": 1, "city_id": slots[len(buildings)],
        "name": name or ("国子学" if special else f"{region['name']}州学"),
        "official": None, "last_upgrade_turn": int(state.turn_number), "supplied": True,
        "construction_cost": cost,
    }
    culture_data(state)["next_building_id"] = int(building["id"]) + 1
    buildings.append(building)
    state.add_log(f"{region['name']}修建{building['name']}，按控制度折算后消耗国库铜钱{cost:g}。")
    return building


def upgrade_school(state: GameState, region_id: int, building_id: int | None = None) -> dict[str, Any]:
    school = next(
        (
            item
            for item in region_buildings(state, region_id)
            if item.get("type") == "school"
            and (building_id is None or int(item.get("id", 0)) == int(building_id))
        ),
        None,
    )
    if not school:
        raise RuleError("该地区尚未修建学校")
    if int(school["level"]) >= school_level_cap(state, int(region_id)):
        raise RuleError("学校已经达到当前等级上限")
    elapsed = state.turn_number - int(school.get("last_upgrade_turn", -999))
    if elapsed < 2:
        raise RuleError(f"{school.get('name', '该建筑')}的升级冷却还剩{2 - elapsed}回合")
    special = str(state.regions[int(region_id)].get("name")) == "扬州"
    base_cost = 4.0 if special else 2.0
    from ...rules.treasury import spend_treasury, treasury_balance
    from ..v1_2.economy import local_purchase_cost_multiplier

    cost = round(base_cost * local_purchase_cost_multiplier(state, int(region_id), state.player_regime_id), 2)
    if treasury_balance(state) < cost:
        raise RuleError(f"国库铜钱不足，需要{cost:g}")
    spend_treasury(state, state.player_regime_id, cost)
    school["level"] = int(school["level"]) + 1
    school["last_upgrade_turn"] = int(state.turn_number)
    school["last_upgrade_cost"] = cost
    state.add_log(f"{school.get('name', '学校')}升级，按控制度折算后消耗国库铜钱{cost:g}。")
    return school


def rename_school(state: GameState, region_id: int, name: str) -> str:
    school = next((item for item in region_buildings(state, region_id) if item.get("type") == "school"), None)
    if not school or not str(name).strip():
        raise RuleError("学校不存在或名称为空")
    school["name"] = str(name).strip()[:24]
    return str(school["name"])


def appoint_school_official(state: GameState, region_id: int, person_id: int | None) -> None:
    school = next((item for item in region_buildings(state, region_id) if item.get("type") == "school"), None)
    if not school:
        raise RuleError("该地区尚未修建学校")
    if person_id is not None:
        person = state.persons.get(int(person_id))
        if not person or int(person.get("country_id", 0)) != state.player_regime_id or int(person.get("status", 0)) != 1:
            raise RuleError("祭酒人选无效")
        for buildings in culture_data(state).setdefault("buildings", {}).values():
            for other in buildings:
                if int(other.get("official") or 0) == int(person_id):
                    raise RuleError("此人已经担任其他学校祭酒")
    school["official"] = int(person_id) if person_id else None


def completed_poetry_nodes(state: GameState) -> set[int]:
    return {int(item) for item in culture_data(state).setdefault("classic_progress", {}).setdefault("poetry", [])}


def study_classic_node(state: GameState, classic: str, node_id: int) -> str:
    if classic != "poetry":
        raise RuleError("该经典的文化树尚待后续更新")
    active = culture_data(state).setdefault("active_classics", [])
    if classic not in active:
        if len(active) >= 2:
            raise RuleError("最多同时发展两部经典；请先放弃其中一部")
        active.append(classic)
    node = POETRY_TREE.get(int(node_id))
    completed = completed_poetry_nodes(state)
    if not node or int(node_id) in completed:
        raise RuleError("该文化节点无效或已经完成")
    if not set(node["requires"]).issubset(completed):
        raise RuleError("前置文化节点尚未完成")
    spend_culture(state, float(node["cost"]), f"研习《诗经》·{node['name']}")
    culture_data(state)["classic_progress"]["poetry"] = sorted(completed | {int(node_id)})
    return f"完成《诗经》节点：{node['name']}。"


def abandon_classic(state: GameState, classic: str) -> None:
    active = culture_data(state).setdefault("active_classics", [])
    if classic in active:
        active.remove(classic)
    culture_data(state).setdefault("classic_progress", {})[classic] = []


def initialize_v13(state: GameState, *, inherited_from: str = "yuanjia_governance") -> GameState:
    state.flags["rules_version"] = V13_RULESET
    state.flags["scenario_id"] = "wenjiao_south"
    state.flags["inherited_from"] = inherited_from
    data = culture_data(state)
    data.setdefault("balance", 0.0)
    data.setdefault("approval", {})
    data.setdefault("buildings", {})
    data.setdefault("active_classics", [])
    data.setdefault("classic_progress", {"poetry": []})
    data.setdefault("next_building_id", 1)
    for region_id, region in state.regions.items():
        record = region_economy(state, int(region_id))
        record.setdefault("culture_supply", 1.0)
        _building_slots(state, int(region_id))
        if str(region_id) not in data["approval"]:
            if int(region.get("controller", 0)) == state.player_regime_id:
                data["approval"][str(region_id)] = 80 if str(region.get("name")) in SOUTHERN_REGIONS else 50
            else:
                data["approval"][str(region_id)] = 0
    from ..v1_2.economy import enforce_warehouse_capacity

    for region_id in state.regions:
        enforce_warehouse_capacity(state, int(region_id))
    return state


def on_region_control_changed(state: GameState, region_id: int, previous: int, current: int) -> None:
    if not is_v13(state):
        return
    approvals = culture_data(state).setdefault("approval", {})
    key = str(int(region_id))
    if current == state.player_regime_id and previous != state.player_regime_id:
        approvals.setdefault(key, 0)


def food_consumption_multiplier(state: GameState, region_id: int) -> float:
    if not is_v13(state) or int(state.regions[region_id].get("controller", 0)) != state.player_regime_id:
        return 1.0
    return round(2.0 - region_approval(state, region_id) / 100.0, 2)


def _school_output_and_maintenance(state: GameState) -> float:
    output = 0.0
    for key, buildings in culture_data(state).setdefault("buildings", {}).items():
        region_id = int(key)
        if int(state.regions.get(region_id, {}).get("controller", 0)) != state.player_regime_id:
            continue
        warehouse = region_economy(state, region_id)["warehouse"]
        for school in buildings:
            if school.get("type") != "school":
                continue
            special = str(state.regions[region_id].get("name")) == "扬州"
            level = int(school.get("level", 1))
            food = (2.4 + (level - 1) * 0.4) if special else (1.2 + (level - 1) * 0.2)
            if float(warehouse.get("food", 0.0)) + 1e-9 < food:
                school["supplied"] = False
                continue
            warehouse["food"] = round(float(warehouse["food"]) - food, 2)
            school["supplied"] = True
            produced = (12 + (level - 1) * 2) if special else (6 + (level - 1))
            official = state.persons.get(int(school.get("official") or 0))
            if official and int(official.get("attributes", {}).get("intelligence", 0)) > 80:
                produced *= 1.1
            output += produced
    return output


def _population_culture_output(state: GameState) -> float:
    total = 0.0
    for region_id, region in state.regions.items():
        if int(region.get("controller", 0)) != state.player_regime_id:
            continue
        approval = region_approval(state, int(region_id))
        for unit in population_units(state, int(region_id)):
            culture = str(unit.get("culture", ""))
            eligible = culture == "southern_han" or (culture == "northern_han" and approval >= 70) or approval >= 90
            if eligible:
                total += max(0, int(unit.get("size", 10_000))) / 10_000 * 0.020
    if 4 in completed_poetry_nodes(state):
        total *= 1.2
    return total


def region_culture_projection(state: GameState, region_id: int) -> dict[str, float | int | str | bool | None]:
    """Return a non-mutating monthly culture output and maintenance estimate."""
    region_id = int(region_id)
    approval = region_approval(state, region_id)
    population_output = 0.0
    base_maintenance = 0.0
    nodes = completed_poetry_nodes(state)
    maintenance_discount = (0.8 if 6 in nodes else 1.0) * (0.5 if 7 in nodes else 1.0)
    for unit in population_units(state, region_id):
        size = max(0, int(unit.get("size", 10_000))) / 10_000
        unit_culture = str(unit.get("culture", ""))
        eligible = unit_culture == "southern_han" or (unit_culture == "northern_han" and approval >= 70) or approval >= 90
        if eligible:
            population_output += size * 0.020
        base_maintenance += size * 0.025 * CULTURE_MAINTENANCE.get(unit_culture, 1.0)
    if 4 in nodes:
        population_output *= 1.2
    base_maintenance *= maintenance_discount

    school = next((item for item in region_buildings(state, region_id) if item.get("type") == "school"), None)
    school_output = 0.0
    school_food = 0.0
    school_supplied = False
    school_name = "未建学校"
    school_official = None
    if school:
        school_name = str(school.get("name", "学校"))
        level = int(school.get("level", 1))
        school_official = int(school.get("official") or 0) or None
        special = str(state.regions[region_id].get("name")) == "扬州"
        school_food = (2.4 + (level - 1) * 0.4) if special else (1.2 + (level - 1) * 0.2)
        school_supplied = float(region_economy(state, region_id)["warehouse"].get("food", 0.0)) + 1e-9 >= school_food
        if school_supplied:
            school_output = (12 + (level - 1) * 2) if special else (6 + (level - 1))
            official = state.persons.get(int(school_official or 0))
            if official and int(official.get("attributes", {}).get("intelligence", 0)) > 80:
                school_output *= 1.1
    total_output = population_output + school_output
    if 1 in nodes:
        total_output *= 1.1
    supply = float(region_economy(state, region_id).get("culture_supply", 1.0))
    return {
        "approval": approval,
        "population_output": round(population_output, 2),
        "school_output": round(school_output, 2),
        "total_output": round(total_output, 2),
        "base_maintenance": round(base_maintenance, 2),
        "requested_maintenance": round(base_maintenance * supply, 2),
        "supply_multiplier": supply,
        "school_name": school_name,
        "school_food": round(school_food, 2),
        "school_supplied": school_supplied,
        "school_official": school_official,
    }


def monthly_culture_projection(state: GameState) -> dict[str, float]:
    """Estimate this month's culture production, spending and net change without mutation."""
    controlled = [
        int(region_id)
        for region_id, region in state.regions.items()
        if int(region.get("controller", 0)) == state.player_regime_id
    ]
    projections = [region_culture_projection(state, region_id) for region_id in controlled]
    central_output = 20.0 * (1.1 if 1 in completed_poetry_nodes(state) else 1.0)
    produced = central_output + sum(float(item["total_output"]) for item in projections)
    requested = sum(float(item["requested_maintenance"]) for item in projections)
    spent = min(culture_balance(state) + produced, requested)
    return {
        "produced": round(produced, 2),
        "requested": round(requested, 2),
        "spent": round(spent, 2),
        "net": round(produced - spent, 2),
    }


def settle_culture(state: GameState) -> dict[str, float]:
    if not is_v13(state):
        return {}
    produced = 20.0 + _population_culture_output(state) + _school_output_and_maintenance(state)
    if 1 in completed_poetry_nodes(state):
        produced *= 1.1
    change_culture(state, produced)
    controlled = [int(rid) for rid, r in state.regions.items() if int(r.get("controller", 0)) == state.player_regime_id]
    demands: dict[int, tuple[float, float]] = {}
    nodes = completed_poetry_nodes(state)
    maintenance_discount = (0.8 if 6 in nodes else 1.0) * (0.5 if 7 in nodes else 1.0)
    for region_id in controlled:
        base = sum(
            max(0, int(unit.get("size", 10_000))) / 10_000 * 0.025 * CULTURE_MAINTENANCE.get(str(unit.get("culture")), 1.0)
            for unit in population_units(state, region_id)
        ) * maintenance_discount
        multiplier = float(region_economy(state, region_id).setdefault("culture_supply", 1.0))
        demands[region_id] = (base, base * multiplier)
    minimum_total = sum(min(base, wanted) for base, wanted in demands.values())
    wanted_total = sum(wanted for _base, wanted in demands.values())
    available = culture_balance(state)
    spent = min(available, wanted_total)
    allocations: dict[int, float] = {}
    if available < minimum_total and minimum_total > 0:
        allocations = {
            rid: spent * min(base, wanted) / minimum_total
            for rid, (base, wanted) in demands.items()
        }
    else:
        extra_available = max(0.0, spent - minimum_total)
        extra_total = max(0.0, wanted_total - minimum_total)
        allocations = {
            rid: min(base, wanted) + (
                extra_available * max(0.0, wanted - min(base, wanted)) / extra_total
                if extra_total > 0 else 0.0
            )
            for rid, (base, wanted) in demands.items()
        }
    change_culture(state, -spent)
    approval_bonus = 1.2 if 3 in completed_poetry_nodes(state) else 1.0
    for region_id, (base, _wanted) in demands.items():
        allocation = allocations.get(region_id, 0.0)
        record = region_economy(state, region_id)
        ratio = allocation / base if base > 0 else 2.0
        sufficient = ratio + 1e-9 >= 1.0
        record["culture_sufficient"] = sufficient
        record["last_culture_required"] = round(base, 2)
        record["last_culture_received"] = round(allocation, 2)
        if not sufficient:
            loss = int(math.floor((1.0 - max(0.0, ratio)) * 10 + 0.5))
            record["stability"] = max(0, int(record.get("stability", 0)) - loss)
            record["culture_stability_cap"] = int(record["stability"])
            set_region_approval(state, region_id, region_approval(state, region_id) - 1)
        else:
            record.pop("culture_stability_cap", None)
            gain = 4 if ratio >= 2 else 3 if ratio >= 1.75 else 2 if ratio >= 1.5 else 1 if ratio >= 1.25 else 0
            if gain:
                set_region_approval(state, region_id, region_approval(state, region_id) + int(math.floor(gain * approval_bonus + 0.5)))
    for region_id, region in state.regions.items():
        if int(region.get("controller", 0)) not in {0, state.player_regime_id} and region_approval(state, int(region_id)) > 0:
            set_region_approval(state, int(region_id), region_approval(state, int(region_id)) - 1)
    state.add_log(f"文化结算：本月产生{produced:.2f}，地区供给{spent:.2f}，结余{culture_balance(state):.2f}。")
    return {"produced": round(produced, 2), "spent": round(spent, 2), "balance": culture_balance(state)}


def handle_famine_approval(state: GameState, reports: list[dict[str, Any]], rng: random.Random) -> None:
    if not is_v13(state):
        return
    for report in reports:
        region_id = int(report["region_id"])
        approval = region_approval(state, region_id)
        shortage = float(report.get("shortage_ratio", 0.0))
        if approval > 50 or shortage <= 0 or int(state.regions[region_id].get("controller", 0)) != state.player_regime_id:
            continue
        set_region_approval(state, region_id, approval - int(math.floor(shortage * 10 + 0.5)))
        revolt_chance = max(0.0, min(1.0, (50 - approval) / 50.0))
        if rng.random() >= revolt_chance:
            continue
        adjacent_enemies: set[int] = set()
        city_ids = [int(cid) for cid, city in state.cities.items() if int(city.get("region_id", 0)) == region_id]
        for city_id in city_ids:
            for target, _road in neighbors(state, city_id):
                target_region = int(state.cities[target].get("region_id", 0))
                controller = int(state.regions.get(target_region, {}).get("controller", 0))
                if controller not in {0, state.player_regime_id}:
                    adjacent_enemies.add(controller)
        if adjacent_enemies and rng.random() < 0.5:
            target = min(adjacent_enemies)
            region = state.regions[region_id]
            name = str(region["name"])
            region["controller"] = target
            for regime in state.regimes.values():
                if name in regime.get("regions", []):
                    regime["regions"].remove(name)
            state.regimes[target].setdefault("regions", []).append(name)
            state.add_log(f"{name}因饥荒与低认可度发生民变，投向{state.regimes[target]['name']}。")
        else:
            region_economy(state, region_id)["control"] = max(0, int(region_economy(state, region_id).get("control", 0)) - 30)
            state.add_log(f"{state.regions[region_id]['name']}因饥荒与低认可度爆发民变，控制度-30。")
