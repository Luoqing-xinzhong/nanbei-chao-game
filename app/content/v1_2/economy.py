from __future__ import annotations

import heapq
import math
import random
from collections import Counter
from typing import Any

from ...models import Army, GameState
from ...rules.common import RuleError, clamp, person_power
from ...rules.military import city_controller


OCCUPATIONS = ("farmer", "artisan", "landlord", "refugee")
OCCUPATION_NAMES = {"farmer": "农民", "artisan": "手工业者", "landlord": "地主", "refugee": "流民"}
CULTURES = ("southern_han", "northern_han", "xianbei", "xiongnu", "southern_tribal")
CULTURE_NAMES = {
    "southern_han": "南方汉",
    "northern_han": "北方汉",
    "xianbei": "鲜卑",
    "xiongnu": "匈奴",
    "southern_tribal": "南蛮",
}
GOODS = ("food", "cloth")
TRANSFERABLE_RESOURCES = ("food", "cloth")
GOOD_NAMES = {"food": "粮食", "cloth": "布匹"}
BASE_PRICES = {"food": 1.0, "cloth": 1.0}
DEFAULT_TAX_RATES = {"food": 0.15, "cloth": 0.15}
TAX_LAW_RATES = {1: 0.0, 2: 0.10, 3: 0.15, 4: 0.20, 5: 0.25}
WAREHOUSE_BASE_CAPACITY = 200.0
WAREHOUSE_EXPANSION_AMOUNT = 20.0
WAREHOUSE_EXPANSION_COPPER_COST = 20.0
WAREHOUSE_EXPANSION_FOOD_COST = 20.0
POPULATION_UNIT_SIZE = 10_000
ORDER_AUTHORITY_COST = 10
MERCHANT_LIMIT = 5
MERCHANT_MAX_TURNS = 2
MARKET_FOOD_TURN_LIMIT = 0.20
LOCAL_POLICY_NAMES = {"stockpile": "屯粮", "tax": "收税", "transfer": "转运", "stop": "停止"}
LOCAL_POLICY_SETTLEMENT_MONTHS = frozenset({8, 9, 10, 11})
MARKET_CAP_MULTIPLIER = 3.0
JANUARY_RETAIN_RATE = 0.10
WEI_STANDING_FORCE_TARGET = 180_000
WEI_MONTHLY_REINFORCEMENT = 50_000
V12_FLAG = "1.2"
V12_ECONOMY_LAW_EFFECTS = [
    "门阀土地上限80%；门阀土地的粮食、布匹实物税按基础税率×0.2征收，土地权力×1.2。",
    "门阀土地上限60%；门阀土地的粮食、布匹实物税按基础税率×0.4征收，土地权力×1.0；解锁检籍、土断。",
    "门阀土地上限30%；门阀土地的粮食、布匹实物税按基础税率×0.5征收，土地权力×0.8。",
    "税率同自耕农；解锁屯田，将地区门阀/小地主土地的5%改为自耕农土地并提高征兵率。",
    "门阀土地分给小地主与自耕农，稳定度每回合额外+2。",
]


def local_economic_actions_allowed(state: GameState) -> bool:
    """Hard calendar gate for every autonomous regional economic action."""
    return int(state.month) in LOCAL_POLICY_SETTLEMENT_MONTHS


# occupation order: farmers, artisans, landlords, refugees
# culture order: southern Han, northern Han, Xianbei, Xiongnu, southern tribal
REGION_RATIOS: dict[str, tuple[tuple[int, int, int, int], tuple[int, int, int, int, int]]] = {
    "扬州": ((60, 18, 12, 10), (95, 3, 0, 0, 2)),
    "淮南地区": ((62, 10, 10, 18), (85, 12, 0, 0, 3)),
    "江州": ((68, 10, 10, 12), (92, 4, 0, 0, 4)),
    "南雍州": ((64, 8, 10, 18), (72, 22, 1, 0, 5)),
    "郢州": ((63, 12, 10, 15), (88, 8, 0, 0, 4)),
    "荆州": ((64, 12, 11, 13), (88, 7, 0, 0, 5)),
    "梁州": ((68, 7, 9, 16), (55, 30, 4, 3, 8)),
    "益州": ((70, 11, 10, 9), (88, 4, 0, 0, 8)),
    "湘州": ((70, 9, 9, 12), (86, 4, 0, 0, 10)),
    "广州": ((68, 10, 8, 14), (68, 5, 0, 0, 27)),
    "交州": ((70, 8, 7, 15), (52, 3, 0, 0, 45)),
    "西南地区": ((72, 5, 5, 18), (25, 3, 0, 0, 72)),
    "中原地区": ((60, 12, 10, 18), (8, 82, 5, 4, 1)),
    "淮北地区": ((58, 9, 9, 24), (15, 78, 3, 3, 1)),
    "徐州": ((60, 10, 9, 21), (20, 74, 3, 2, 1)),
    "青州": ((62, 11, 10, 17), (10, 82, 5, 2, 1)),
    "冀州": ((64, 12, 11, 13), (3, 78, 14, 4, 1)),
    "幽州": ((60, 9, 9, 22), (2, 60, 30, 7, 1)),
    "并州": ((66, 8, 9, 17), (2, 72, 16, 9, 1)),
    "北雍州": ((62, 10, 10, 18), (8, 72, 6, 13, 1)),
    "夏地区": ((58, 5, 7, 30), (2, 35, 8, 54, 1)),
    "陇西地区": ((64, 7, 8, 21), (4, 62, 5, 27, 2)),
    "东北地区": ((56, 7, 8, 29), (1, 45, 48, 5, 1)),
    "仇池": ((68, 5, 7, 20), (8, 52, 3, 20, 17)),
}


def is_v12(state: GameState) -> bool:
    return str(state.flags.get("content_version", "")) == V12_FLAG


def economy_data(state: GameState) -> dict[str, Any]:
    return state.flags.setdefault("v12_economy", {})


def _add_visible_economic_log(state: GameState, regime_id: int, message: str) -> None:
    """AI economic bookkeeping stays hidden; player and neutral-market activity remains visible."""
    if int(regime_id) in {0, state.player_regime_id}:
        state.add_log(message)


def region_economy(state: GameState, region_id: int) -> dict[str, Any]:
    regions = economy_data(state).setdefault("regions", {})
    key = str(int(region_id))
    if key not in regions:
        raise RuleError(f"地区#{region_id}尚未初始化1.2经济数据")
    record = regions[key]
    record.setdefault("warehouse_capacity", WAREHOUSE_BASE_CAPACITY)
    record.setdefault("local_policy", "stockpile")
    return record


def format_resource(value: float | int) -> str:
    """Display a resource with no more than two decimal places."""
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def warehouse_capacity(state: GameState, region_id: int) -> float:
    return round(float(region_economy(state, region_id).setdefault("warehouse_capacity", WAREHOUSE_BASE_CAPACITY)), 2)


def warehouse_resource_capacity(state: GameState, region_id: int, good: str) -> float:
    """AI opening cash may exceed the normal per-resource cap until it is spent."""
    if good == "food" and str(state.flags.get("rules_version", "")) == "1.3":
        capacity = len(population_units(state, int(region_id))) * 0.8
        floor_regions = {
            int(item) for item in state.flags.get("v13_initial_food_capacity_floor_regions", [])
        }
        if int(region_id) in floor_regions:
            capacity = max(30.0, capacity)
        return round(capacity, 2)
    return round(warehouse_capacity(state, region_id), 2)


def warehouse_room(state: GameState, region_id: int, good: str) -> float:
    stock = float(region_economy(state, region_id)["warehouse"].get(good, 0.0))
    return round(max(0.0, warehouse_resource_capacity(state, region_id, good) - stock), 2)


def enforce_warehouse_capacity(state: GameState, region_id: int) -> dict[str, float]:
    record = region_economy(state, region_id)
    removed: dict[str, float] = {}
    for good in TRANSFERABLE_RESOURCES:
        old = max(0.0, float(record["warehouse"].get(good, 0.0)))
        capacity = warehouse_resource_capacity(state, region_id, good)
        capped = round(min(old, capacity), 2)
        record["warehouse"][good] = capped
        removed[good] = round(max(0.0, old - capped), 2)
    return removed


def settle_december_warehouse_food(state: GameState) -> list[dict[str, float | int]]:
    """In 1.3, remove food equal to 20% of each region's population cap in December."""
    if str(state.flags.get("rules_version", "")) != "1.3" or int(state.month) != 12:
        return []
    reports: list[dict[str, float | int]] = []
    for region_id, region in sorted(state.regions.items()):
        record = region_economy(state, int(region_id))
        capacity = warehouse_resource_capacity(state, int(region_id), "food")
        stock = min(max(0.0, float(record["warehouse"].get("food", 0.0))), capacity)
        planned_loss = round(capacity * 0.20, 2)
        actual_loss = round(min(stock, planned_loss), 2)
        record["warehouse"]["food"] = round(max(0.0, stock - actual_loss), 2)
        reports.append({"region_id": int(region_id), "capacity": capacity, "loss": actual_loss})
        if actual_loss > 0:
            _add_visible_economic_log(
                state,
                int(region.get("controller", 0)),
                f"腊月府库结算：{region['name']}粮食容量{format_resource(capacity)}，"
                f"按容量20%减少{format_resource(actual_loss)}，余粮"
                f"{format_resource(record['warehouse']['food'])}。",
            )
    return reports


def lock_ai_region_control(state: GameState, region_id: int, controller_id: int) -> bool:
    """Immediately force an AI-controlled 1.2 region to 100 control."""
    if not is_v12(state) or not controller_id or int(controller_id) == state.player_regime_id:
        return False
    regions = economy_data(state).get("regions", {})
    record = regions.get(str(int(region_id)))
    region = state.regions.get(int(region_id))
    if record is None or region is None:
        return False
    record["control"] = 100
    region["control"] = 100
    return True


def lock_all_ai_region_control(state: GameState) -> None:
    for region_id, region in state.regions.items():
        lock_ai_region_control(state, int(region_id), int(region.get("controller", 0)))


def migrate_market_currency(state: GameState) -> None:
    """Remove obsolete market copper pools; copper is a regime-wide currency."""
    if not is_v12(state):
        return
    for record in economy_data(state).get("regions", {}).values():
        record.setdefault("market", {}).pop("copper", None)


def population_units(state: GameState, region_id: int | None = None) -> list[dict[str, Any]]:
    units = economy_data(state).setdefault("population_units", [])
    if region_id is None:
        return units
    return [unit for unit in units if int(unit.get("region_id", 0)) == int(region_id)]


def population_counts(state: GameState, region_id: int) -> tuple[Counter, Counter]:
    units = population_units(state, region_id)
    return Counter(str(unit["occupation"]) for unit in units), Counter(str(unit["culture"]) for unit in units)


def _allocate(total: int, ratios: tuple[int, ...]) -> list[int]:
    raw = [total * value / sum(ratios) for value in ratios]
    result = [int(value) for value in raw]
    for index in sorted(range(len(ratios)), key=lambda i: (raw[i] - result[i], ratios[i], -i), reverse=True)[: total - sum(result)]:
        result[index] += 1
    return result


def _initial_land(region: dict[str, Any]) -> dict[str, int]:
    total = max(0, int(region.get("land", 0)))
    old = list(region.get("land_ownership", []))
    counts = Counter("self_farm" if int(owner) in {0, 2} else "smallholder" if int(owner) == 1 else "gentry" for owner in old)
    if not old:
        allocated = _allocate(total, (35, 30, 35))
        return dict(zip(("gentry", "smallholder", "self_farm"), allocated))
    raw = [counts["gentry"] * total / len(old), counts["smallholder"] * total / len(old), counts["self_farm"] * total / len(old)]
    values = [int(value) for value in raw]
    for index in sorted(range(3), key=lambda i: raw[i] - values[i], reverse=True)[: total - sum(values)]:
        values[index] += 1
    return dict(zip(("gentry", "smallholder", "self_farm"), values))


def initialize_economy(state: GameState, seed: int = 422) -> None:
    rng = random.Random(seed)
    data: dict[str, Any] = {
        "next_population_id": 1,
        "next_logistics_id": 1,
        "population_units": [],
        "logistics_units": [],
        "regions": {},
        "recruitment": {},
        "manpower": {},
        "seed": seed,
    }
    state.flags["v12_economy"] = data
    for region in sorted(state.regions.values(), key=lambda item: int(item["id"])):
        region_id = int(region["id"])
        occupation_ratios, culture_ratios = REGION_RATIOS.get(
            str(region.get("name")),
            ((65, 10, 10, 15), (50, 40, 4, 4, 2)),
        )
        # 原配置的households以千户量级记录；每10点生成一个万人单位。
        total_units = max(5, int(round(max(0, int(region.get("households", 0))) / 10)))
        occupation_values: list[str] = []
        for name, amount in zip(OCCUPATIONS, _allocate(total_units, occupation_ratios)):
            occupation_values.extend([name] * amount)
        culture_values: list[str] = []
        for name, amount in zip(CULTURES, _allocate(total_units, culture_ratios)):
            culture_values.extend([name] * amount)
        rng.shuffle(occupation_values)
        rng.shuffle(culture_values)
        for occupation, culture in zip(occupation_values, culture_values):
            data["population_units"].append({
                "id": data["next_population_id"],
                "region_id": region_id,
                "size": POPULATION_UNIT_SIZE,
                "occupation": occupation,
                "culture": culture,
            })
            data["next_population_id"] += 1
        local_stability = int(clamp(int(region.get("prosperity", 5)) * 10, 0, 100))
        controller = int(region.get("controller", 0))
        initial_control = 100 if controller and controller != state.player_regime_id else 70 if controller else 30
        data["regions"][str(region_id)] = {
            "stability": local_stability,
            "control": initial_control,
            "land": _initial_land(region),
            "warehouse": {"food": 20.0, "cloth": 20.0},
            "warehouse_capacity": WAREHOUSE_BASE_CAPACITY,
            "market": {"food": 20.0, "cloth": 20.0},
            "statutory_tax_rates": dict(DEFAULT_TAX_RATES),
            "tax_rates": dict(DEFAULT_TAX_RATES),
            "surplus_years": 0,
            "growth_progress": 0.0,
            "annexation_progress": 0.0,
            "last_weather": "未结算",
        }
        region["local_stability"] = local_stability
        region["control"] = initial_control
    for region_id in state.regions:
        enforce_market_capacity(state, int(region_id))
        enforce_warehouse_capacity(state, int(region_id))
    start_market_turn(state)


def start_market_turn(state: GameState) -> None:
    """Snapshot each market's opening food stock for the cumulative 20% trade cap."""
    data = economy_data(state)
    data["market_turn"] = {
        "turn": int(state.turn_number),
        "regions": {
            str(region_id): {
                "opening_food": round(float(region_economy(state, region_id)["market"].get("food", 0.0)), 2),
                "traded_food": 0.0,
            }
            for region_id in state.regions
        },
    }


def _market_turn_record(state: GameState, region_id: int) -> dict[str, float]:
    data = economy_data(state)
    ledger = data.get("market_turn", {})
    if int(ledger.get("turn", -1)) != int(state.turn_number):
        start_market_turn(state)
        ledger = data["market_turn"]
    regions = ledger.setdefault("regions", {})
    key = str(int(region_id))
    if key not in regions:
        regions[key] = {
            "opening_food": round(float(region_economy(state, region_id)["market"].get("food", 0.0)), 2),
            "traded_food": 0.0,
        }
    return regions[key]


def market_food_trade_remaining(state: GameState, region_id: int, action: str = "buy") -> float:
    record = _market_turn_record(state, region_id)
    limit = float(record["opening_food"]) * MARKET_FOOD_TURN_LIMIT
    if action == "sell":
        limit = max(20.0, limit)
    return round(max(0.0, limit - float(record.get("traded_food", 0.0))), 2)


def tax_collection_coefficient(state: GameState, region_id: int) -> float:
    """Return the land-share-weighted collection coefficient, never the production multiplier."""
    from ...rules.laws import family_tax_rate

    land = region_economy(state, region_id)["land"]
    total = sum(max(0, int(value)) for value in land.values())
    if total <= 0:
        return 0.0
    regime_id = int(state.regions[region_id].get("controller", 0))
    gentry_rate = family_tax_rate(state, regime_id)
    weighted = (
        int(land.get("gentry", 0)) * gentry_rate
        + int(land.get("smallholder", 0)) * 0.5
        + int(land.get("self_farm", 0)) * 0.8
    )
    return round(weighted / total, 4)


def production_tax_rate(state: GameState, region_id: int, good: str = "food") -> float:
    """Actual in-kind rate = statutory tax rate × land collection coefficient."""
    base_rate = TAX_LAW_RATES.get(int(state.laws.get("tax", 3)), 0.15)
    base_rate += float(state.flags.get(f"v12_tax_{good}_offset", 0.0))
    base_rate = float(clamp(base_rate, 0.0, 1.0))
    return round(base_rate * tax_collection_coefficient(state, region_id), 4)


def market_price(state: GameState, region_id: int, good: str) -> float:
    if good not in BASE_PRICES:
        raise RuleError("该商品没有市场价格")
    record = region_economy(state, region_id)
    market = record["market"]
    target = market_demand(state, region_id, good)
    stock = max(0.0, float(market.get(good, 0.0)))
    pressure = (target - stock) / target
    if int(state.flags.get("v12_jianghuai_trade_until", -1)) >= state.turn_number and state.regions[region_id].get("name") in {"徐州", "淮北地区", "中原地区"}:
        pressure *= 0.8
    price_cap = 3.2 if state.flags.get("v12_strategy_effect:14") and good == "food" else 4.0
    price = BASE_PRICES[good] * (1 + pressure * 0.75)
    drought = state.flags.get("v12_drought_relief", {})
    if good == "food" and not drought.get("resolved") and int(drought.get("region_id", 0)) == int(region_id):
        price *= 1.3
    if good == "food" and int(state.flags.get("v12_good_harvest_prices_until", -1)) >= state.turn_number and state.regions[region_id].get("name") in {"扬州", "江州", "荆州"}:
        price *= 0.85
    return round(float(clamp(price, 0.25, price_cap)), 2)


def market_purchase_room_at_price(
    state: GameState,
    region_id: int,
    good: str,
    price_ceiling: float,
) -> float:
    """Maximum whole-cent quantity purchasable without exceeding a price ceiling."""
    record = region_economy(state, region_id)
    market = record["market"]
    current = round(max(0.0, float(market.get(good, 0.0))), 2)
    if current <= 0 or market_price(state, region_id, good) > price_ceiling:
        return 0.0

    original = float(market.get(good, 0.0))
    low, high = 0, int(math.floor(current * 100 + 1e-9))
    try:
        while low < high:
            candidate = (low + high + 1) // 2
            market[good] = round(current - candidate / 100, 2)
            if market_price(state, region_id, good) <= price_ceiling:
                low = candidate
            else:
                high = candidate - 1
    finally:
        market[good] = original
    return round(low / 100, 2)


def market_demand(state: GameState, region_id: int, good: str) -> float:
    occupations, _cultures = population_counts(state, region_id)
    if good == "food":
        demand = float(len(population_units(state, region_id)))
        if str(state.flags.get("rules_version", "")) == "1.3":
            from ..v1_3.culture import food_consumption_multiplier

            demand *= food_consumption_multiplier(state, int(region_id))
        return max(1.0, round(demand, 2))
    return max(1.0, float(occupations["artisan"]) * 2)


def market_capacity(state: GameState, region_id: int, good: str) -> float:
    return round(market_demand(state, region_id, good) * MARKET_CAP_MULTIPLIER, 2)


def _market_room(state: GameState, region_id: int, good: str) -> float:
    stock = float(region_economy(state, region_id)["market"].get(good, 0.0))
    return round(max(0.0, market_capacity(state, region_id, good) - stock), 2)


def enforce_market_capacity(state: GameState, region_id: int) -> dict[str, float]:
    record = region_economy(state, region_id)
    removed = {}
    for good in GOODS:
        old = float(record["market"].get(good, 0.0))
        capped = min(old, market_capacity(state, region_id, good))
        record["market"][good] = round(capped, 2)
        removed[good] = round(max(0.0, old - capped), 2)
    return removed


def _spend_order_authority(state: GameState, regime_id: int) -> None:
    if regime_id == state.player_regime_id:
        if state.authority < ORDER_AUTHORITY_COST:
            raise RuleError(f"权威不足{ORDER_AUTHORITY_COST}")
        state.authority -= ORDER_AUTHORITY_COST
    else:
        regime = state.regimes[regime_id]
        if int(regime.get("authority", 0)) < ORDER_AUTHORITY_COST:
            raise RuleError(f"权威不足{ORDER_AUTHORITY_COST}")
        regime["authority"] -= ORDER_AUTHORITY_COST


def _validate_order_region(state: GameState, regime_id: int, region_id: int) -> dict[str, Any]:
    region = state.regions.get(int(region_id))
    if not region or int(region.get("controller", 0)) != regime_id:
        raise RuleError("经济命令只能向本国实际控制的地区发布")
    return region


def _local_order_efficiency(state: GameState, record: dict[str, Any], regime_id: int) -> float:
    efficiency = float(record["control"]) / 100
    if regime_id == state.player_regime_id and int(state.flags.get("v12_capable_governors_until", -1)) >= state.turn_number:
        efficiency += 0.05
    return min(1.0, efficiency)


def local_income_multiplier(state: GameState, region_id: int, regime_id: int) -> float:
    """Local sale/tax income scales linearly from 0% to 100% with control."""
    record = region_economy(state, int(region_id))
    return round(float(clamp(float(record.get("control", 0)) / 100.0, 0.0, 1.0)), 4)


def local_purchase_cost_multiplier(state: GameState, region_id: int, regime_id: int) -> float:
    """Local spending costs 2x at zero control and normal price at full control."""
    return round(2.0 - local_income_multiplier(state, int(region_id), int(regime_id)), 4)


def _available_order_authority(state: GameState, regime_id: int) -> int:
    if regime_id == state.player_regime_id:
        return int(state.authority)
    return int(state.regimes.get(regime_id, {}).get("authority", 0))


def _floor_resource(value: float) -> float:
    """Round a selectable limit down so the slider can never cross a hard limit."""
    return math.floor(max(0.0, float(value)) * 100 + 1e-9) / 100


def executable_market_order_limit(
    state: GameState,
    regime_id: int,
    region_id: int,
    good: str,
    action: str,
) -> float:
    """Largest planned market order that is valid with the current live balances."""
    if good not in BASE_PRICES or action not in {"buy", "sell"}:
        return 0.0
    try:
        _validate_order_region(state, regime_id, region_id)
    except RuleError:
        return 0.0
    if _available_order_authority(state, regime_id) < ORDER_AUTHORITY_COST:
        return 0.0
    record = region_economy(state, region_id)
    warehouse, market = record["warehouse"], record["market"]
    efficiency = _local_order_efficiency(state, record, regime_id)
    if efficiency <= 0:
        return 0.0
    price = market_price(state, region_id, good)
    if action == "buy":
        from ...rules.treasury import treasury_balance

        cost_multiplier = local_purchase_cost_multiplier(state, region_id, regime_id)
        # These three limits are also checked against the planned amount itself.
        limit = min(
            float(market.get(good, 0.0)),
            treasury_balance(state, regime_id) / (price * cost_multiplier * efficiency),
            warehouse_room(state, region_id, good) / efficiency,
        )
    else:
        # Stock and market capacity constrain the goods sold; revenue is control-adjusted.
        limit = min(
            float(warehouse.get(good, 0.0)),
            _market_room(state, region_id, good) / efficiency,
        )
    if good == "food":
        limit = min(limit, market_food_trade_remaining(state, region_id, action) / efficiency)
    return _floor_resource(limit)


def market_order_efficiency(state: GameState, regime_id: int, region_id: int) -> float:
    """Public control efficiency used by trade previews and threshold markers."""
    return _local_order_efficiency(state, region_economy(state, region_id), regime_id)


def food_market_balance_order_threshold(
    state: GameState,
    regime_id: int,
    region_id: int,
    action: str,
) -> float | None:
    """Planned amount at which buying exhausts surplus or selling fills shortage."""
    if action not in {"buy", "sell"}:
        return None
    efficiency = market_order_efficiency(state, regime_id, region_id)
    if efficiency <= 0:
        return None
    stock = float(region_economy(state, region_id)["market"].get("food", 0.0))
    demand = market_demand(state, region_id, "food")
    affected = max(0.0, stock - demand) if action == "buy" else max(0.0, demand - stock)
    # The green marker must be the first selectable tenth that actually fills
    # the shortage after control loss; the red line marks the safe boundary.
    if action == "sell":
        return math.ceil(affected / efficiency * 10 - 1e-9) / 10
    return math.floor(affected / efficiency * 10 + 1e-9) / 10


def executable_release_grain_limit(state: GameState, regime_id: int, region_id: int) -> float:
    """Largest valid planned release, including market room and local control."""
    try:
        _validate_order_region(state, regime_id, region_id)
    except RuleError:
        return 0.0
    if _available_order_authority(state, regime_id) < ORDER_AUTHORITY_COST:
        return 0.0
    record = region_economy(state, region_id)
    efficiency = _local_order_efficiency(state, record, regime_id)
    if efficiency <= 0:
        return 0.0
    return _floor_resource(min(
        float(record["warehouse"].get("food", 0.0)),
        _market_room(state, region_id, "food") / efficiency,
    ))


def executable_convoy_limit(
    state: GameState,
    regime_id: int,
    source_region_id: int,
    target_region_id: int,
    good: str,
) -> float:
    """Largest valid planned convoy load for the selected route and resource."""
    if good not in TRANSFERABLE_RESOURCES or source_region_id == target_region_id:
        return 0.0
    try:
        _validate_order_region(state, regime_id, source_region_id)
        _validate_order_region(state, regime_id, target_region_id)
    except RuleError:
        return 0.0
    if _available_order_authority(state, regime_id) < ORDER_AUTHORITY_COST:
        return 0.0
    source_record = region_economy(state, source_region_id)
    if _local_order_efficiency(state, source_record, regime_id) <= 0:
        return 0.0
    route = _route(state, _region_capital(state, source_region_id), _region_capital(state, target_region_id))
    if not route:
        return 0.0
    return _floor_resource(float(source_record["warehouse"].get(good, 0.0)))


def expand_warehouse(state: GameState, regime_id: int, region_id: int) -> str:
    region = _validate_order_region(state, regime_id, region_id)
    record = region_economy(state, region_id)
    warehouse = record["warehouse"]
    from ...rules.treasury import spend_treasury, treasury_balance

    copper_cost = round(WAREHOUSE_EXPANSION_COPPER_COST * local_purchase_cost_multiplier(state, region_id, regime_id), 2)
    if treasury_balance(state, regime_id) < copper_cost:
        raise RuleError(f"国库铜钱不足，需要{format_resource(copper_cost)}")
    if float(warehouse.get("food", 0.0)) < WAREHOUSE_EXPANSION_FOOD_COST:
        raise RuleError(f"当地州库粮食不足{format_resource(WAREHOUSE_EXPANSION_FOOD_COST)}")
    _spend_order_authority(state, regime_id)
    spend_treasury(state, regime_id, copper_cost)
    warehouse["food"] = round(float(warehouse["food"]) - WAREHOUSE_EXPANSION_FOOD_COST, 2)
    old_capacity = warehouse_capacity(state, region_id)
    record["warehouse_capacity"] = round(old_capacity + WAREHOUSE_EXPANSION_AMOUNT, 2)
    capacity_scope = "粮食与布匹"
    message = (
        f"扩建{region['name']}州库：消耗粮食{format_resource(WAREHOUSE_EXPANSION_FOOD_COST)}、"
        f"国库铜钱{format_resource(copper_cost)}（已按控制度折算），{capacity_scope}容量由"
        f"{format_resource(old_capacity)}提高至{format_resource(record['warehouse_capacity'])}。"
    )
    _add_visible_economic_log(state, regime_id, message)
    return message


def market_order(
    state: GameState,
    regime_id: int,
    region_id: int,
    good: str,
    action: str,
    amount: float,
    *,
    charge_authority: bool = True,
    add_log: bool = True,
) -> str:
    region = _validate_order_region(state, regime_id, region_id)
    if good not in BASE_PRICES or action not in {"buy", "sell"} or amount <= 0:
        raise RuleError("市场命令参数无效")
    record = region_economy(state, region_id)
    planned = round(float(amount), 2)
    warehouse, market = record["warehouse"], record["market"]
    price = market_price(state, region_id, good)
    efficiency = _local_order_efficiency(state, record, regime_id)
    if efficiency <= 0:
        raise RuleError("地区控制度为0，无法执行市场命令")
    if action == "sell" and planned > float(warehouse.get(good, 0.0)) + 1e-9:
        raise RuleError("计划出售量不能超过府库实际库存")
    if action == "buy":
        from ...rules.treasury import treasury_balance

        purchase_multiplier = local_purchase_cost_multiplier(state, region_id, regime_id)
        selectable = min(
            float(market.get(good, 0.0)),
            treasury_balance(state, regime_id) / (price * purchase_multiplier * efficiency),
            warehouse_room(state, region_id, good) / efficiency,
        )
        if planned > selectable + 1e-9:
            raise RuleError("计划购买量不能超过市场存货、国库资金或府库剩余容量")
    control_multiplier = local_income_multiplier(state, region_id, regime_id)
    purchase_multiplier = local_purchase_cost_multiplier(state, region_id, regime_id)
    controlled_amount = round(planned * efficiency, 2)
    actual = controlled_amount
    food_trade = None
    if good == "food":
        food_trade = _market_turn_record(state, region_id)
        remaining = market_food_trade_remaining(state, region_id, action)
        if remaining <= 0:
            raise RuleError("本回合粮食市场成交量已达到回合开始库存的20%上限")
        actual = min(actual, remaining)
    if action == "sell":
        actual = min(actual, float(warehouse.get(good, 0.0)), _market_room(state, region_id, good))
        actual = round(actual, 2)
        if actual <= 0:
            raise RuleError("府库无货")
        if charge_authority:
            _spend_order_authority(state, regime_id)
        warehouse[good] = round(float(warehouse[good]) - actual, 2)
        market[good] = round(float(market[good]) + actual, 2)
        revenue = round(actual * price * control_multiplier, 2)
        from ...rules.treasury import change_treasury

        change_treasury(state, regime_id, revenue)
    else:
        from ...rules.treasury import spend_treasury, treasury_balance

        actual = min(
            actual,
            float(market.get(good, 0.0)),
            treasury_balance(state, regime_id) / (price * purchase_multiplier),
            warehouse_room(state, region_id, good),
        )
        actual = round(actual, 2)
        if actual <= 0:
            raise RuleError("市场无货或府库铜钱不足")
        if charge_authority:
            _spend_order_authority(state, regime_id)
        market[good] = round(float(market[good]) - actual, 2)
        warehouse[good] = round(float(warehouse[good]) + actual, 2)
        revenue = round(actual * price * purchase_multiplier, 2)
        spend_treasury(state, regime_id, revenue)
    enforce_market_capacity(state, region_id)
    enforce_warehouse_capacity(state, region_id)
    if food_trade is not None:
        food_trade["traded_food"] = round(float(food_trade.get("traded_food", 0.0)) + actual, 2)
    verb = "购入" if action == "buy" else "出售"
    control_unfinished = round(max(0.0, planned - controlled_amount), 2)
    constrained_unfinished = round(max(0.0, controlled_amount - actual), 2)
    total_unfinished = round(max(0.0, planned - actual), 2)
    cash_label = "获得铜钱" if action == "sell" else "支出铜钱"
    message = (
        f"【经济行动报告·{verb}】\n"
        f"地区：{region['name']}　商品：{GOOD_NAMES[good]}　成交价：{price:g}\n"
        f"计划数量：{planned:g}　实际成交：{actual:g}　未成交：{total_unfinished:g}\n"
        f"控制度导致未执行：{control_unfinished:g}　库存/资金/额度限制导致未执行：{constrained_unfinished:g}\n"
        f"物资损耗：0（未成交物资不会被扣除）　{cash_label}：{revenue:g}　"
        f"控制度折算：{'收入×' + format_resource(control_multiplier) if action == 'sell' else '花费×' + format_resource(purchase_multiplier)}　"
        f"权威：{'-' + str(ORDER_AUTHORITY_COST) if charge_authority else '0（地方自行执行）'}"
    )
    if add_log:
        _add_visible_economic_log(state, regime_id, message)
    return message


def release_grain(state: GameState, regime_id: int, region_id: int, amount: float) -> str:
    """Move government grain into the local market for free."""
    region = _validate_order_region(state, regime_id, region_id)
    if amount <= 0:
        raise RuleError("开仓数量必须大于0")
    record = region_economy(state, region_id)
    planned = round(float(amount), 2)
    if planned > float(record["warehouse"].get("food", 0.0)) + 1e-9:
        raise RuleError("计划放粮量不能超过府库实际库存")
    controlled_amount = round(planned * _local_order_efficiency(state, record, regime_id), 2)
    actual = controlled_amount
    actual = min(actual, float(record["warehouse"].get("food", 0.0)), _market_room(state, region_id, "food"))
    if actual <= 0:
        raise RuleError("州库没有可供投放的粮食")
    _spend_order_authority(state, regime_id)
    record["warehouse"]["food"] -= actual
    record["market"]["food"] += actual
    control_unfinished = round(max(0.0, planned - controlled_amount), 2)
    stock_unfinished = round(max(0.0, controlled_amount - actual), 2)
    total_unfinished = round(max(0.0, planned - actual), 2)
    message = (
        "【经济行动报告·开仓放粮】\n"
        f"地区：{region['name']}　计划投放：{planned:g}　实际投放：{actual:g}　未投放：{total_unfinished:g}\n"
        f"其中控制度导致未执行：{control_unfinished:g}　州库库存限制：{stock_unfinished:g}\n"
        f"粮食损耗：0（未投放粮食仍留在州库）　收入：0　权威：-{ORDER_AUTHORITY_COST}"
    )
    _add_visible_economic_log(state, regime_id, message)
    return message


def _region_capital(state: GameState, region_id: int) -> int:
    region = state.regions[int(region_id)]
    return next(
        (int(city_id) for city_id in region.get("cities", []) if state.cities.get(int(city_id), {}).get("capital")),
        int(region.get("cities", [0])[0]) if region.get("cities") else 0,
    )


def _route(state: GameState, start: int, goal: int) -> tuple[list[int], float] | None:
    from ...rules.military import effective_road_type

    costs = {1: 1.0, 2: 1.0, 3: 0.3, 4: 0.5}
    adjacent: dict[int, list[tuple[int, float]]] = {}
    for road in state.roads:
        left, right = int(road["from"]), int(road["to"])
        cost = costs.get(effective_road_type(state, road), 1.0)
        adjacent.setdefault(left, []).append((right, cost))
        adjacent.setdefault(right, []).append((left, cost))
    queue: list[tuple[float, int, tuple[int, ...]]] = [(0.0, start, (start,))]
    best = {start: 0.0}
    while queue:
        cost, city_id, path = heapq.heappop(queue)
        if city_id == goal:
            return list(path), round(cost, 2)
        if cost > best.get(city_id, math.inf):
            continue
        for neighbor, edge in adjacent.get(city_id, []):
            new_cost = round(cost + edge, 2)
            if new_cost < best.get(neighbor, math.inf):
                best[neighbor] = new_cost
                heapq.heappush(queue, (new_cost, neighbor, path + (neighbor,)))
    return None


def create_convoy(
    state: GameState,
    regime_id: int,
    source_region_id: int,
    target_region_id: int,
    good: str,
    amount: float,
    *,
    charge_authority: bool = True,
    add_log: bool = True,
) -> str:
    source = _validate_order_region(state, regime_id, source_region_id)
    target = state.regions.get(int(target_region_id))
    if not target or int(target.get("controller", 0)) != regime_id:
        raise RuleError("官漕只能运往本国实际控制的地区")
    if source_region_id == target_region_id or good not in TRANSFERABLE_RESOURCES or amount <= 0:
        raise RuleError("官漕命令参数无效")
    source_record = region_economy(state, source_region_id)
    planned = round(float(amount), 2)
    if planned > float(source_record["warehouse"].get(good, 0.0)) + 1e-9:
        raise RuleError("计划调运量不能超过来源府库实际库存")
    controlled_amount = round(planned * _local_order_efficiency(state, source_record, regime_id), 2)
    actual = controlled_amount
    actual = min(actual, float(source_record["warehouse"].get(good, 0.0)))
    if actual <= 0:
        raise RuleError("来源府库物资不足")
    route = _route(state, _region_capital(state, source_region_id), _region_capital(state, target_region_id))
    if not route:
        raise RuleError("两个地区之间没有可用运输路线")
    if charge_authority:
        _spend_order_authority(state, regime_id)
    source_record["warehouse"][good] -= actual
    data = economy_data(state)
    logistics_id = int(data["next_logistics_id"])
    data["next_logistics_id"] = logistics_id + 1
    data["logistics_units"].append({
        "id": logistics_id,
        "kind": "official",
        "regime_id": regime_id,
        "source_region_id": int(source_region_id),
        "target_region_id": int(target_region_id),
        "good": good,
        "amount": actual,
        "initial_amount": actual,
        "total_attrition": 0.0,
        "path": route[0],
        "path_index": 0,
        "movement_progress": 0.0,
        "age": 0,
        "modifiers": ["ai_official_convoy_no_attrition"] if regime_id != state.player_regime_id else [],
    })
    control_unfinished = round(max(0.0, planned - controlled_amount), 2)
    stock_unfinished = round(max(0.0, controlled_amount - actual), 2)
    total_unfinished = round(max(0.0, planned - actual), 2)
    message = (
        f"【经济行动报告·建立官漕#{logistics_id}】\n"
        f"路线：{source['name']} → {state.regions[target_region_id]['name']}　物资：{GOOD_NAMES[good]}\n"
        f"计划装运：{planned:g}　实际装运：{actual:g}　未装运：{total_unfinished:g}\n"
        f"其中控制度导致未执行：{control_unfinished:g}　州库库存限制：{stock_unfinished:g}\n"
        f"启运损耗：0；在途每次结算另损耗当前货物10%　收入：0　"
        f"权威：{'-' + str(ORDER_AUTHORITY_COST) if charge_authority else '0（地方自行执行）'}"
    )
    if add_log:
        _add_visible_economic_log(state, regime_id, message)
    return message


def _run_jiankang_auto_convoys(state: GameState) -> list[int]:
    """Compatibility no-op: regional policies now exclusively decide when grain is shipped."""
    return []


def _merchant_opportunities(state: GameState) -> list[tuple[float, int, int, str, list[int], float]]:
    opportunities = []
    for source_id in state.regions:
        for target_id in state.regions:
            if source_id == target_id:
                continue
            route = _route(state, _region_capital(state, source_id), _region_capital(state, target_id))
            if not route or route[1] > MERCHANT_MAX_TURNS:
                continue
            for good in BASE_PRICES:
                margin = market_price(state, target_id, good) - market_price(state, source_id, good)
                stock = float(region_economy(state, source_id)["market"].get(good, 0.0))
                required_margin = BASE_PRICES[good] * (0.25 if state.flags.get("v12_strategy_effect:23") else 0.0)
                if margin > required_margin and stock >= 1:
                    opportunities.append((margin, source_id, target_id, good, route[0], route[1]))
    return sorted(opportunities, reverse=True)


def generate_merchants(state: GameState, rng: random.Random | None = None) -> list[int]:
    rng = rng or random.Random(state.year * 100 + state.month)
    data = economy_data(state)
    active = [unit for unit in data["logistics_units"] if unit.get("kind") == "merchant"]
    merchant_limit = 7 if state.flags.get("v12_strategy_effect:23") else MERCHANT_LIMIT
    if int(state.flags.get("v12_merchant_bonus_until", -1)) >= state.turn_number:
        merchant_limit += 2
    limit = max(0, merchant_limit - len(active))
    opportunities = _merchant_opportunities(state)
    if limit <= 0 or not opportunities:
        return []
    # 从利润最高的候选中随机取样，避免每年完全相同。
    pool = opportunities[: max(limit * 4, limit)]
    rng.shuffle(pool)
    selected = sorted(pool[:limit], reverse=True)
    created = []
    for _margin, source_id, target_id, good, path, _cost in selected:
        source_market = region_economy(state, source_id)["market"]
        amount = round(min(float(source_market.get(good, 0.0)) * 0.15, 20.0), 2)
        if amount < 1:
            continue
        source_market[good] -= amount
        logistics_id = int(data["next_logistics_id"])
        data["next_logistics_id"] = logistics_id + 1
        data["logistics_units"].append({
            "id": logistics_id,
            "kind": "merchant",
            "regime_id": 0,
            "source_region_id": source_id,
            "target_region_id": target_id,
            "good": good,
            "amount": amount,
            "path": path,
            "path_index": 0,
            "movement_progress": 0.0,
            "age": 0,
        })
        created.append(logistics_id)
    if created:
        state.add_log(f"八月商路形成：地图生成{len(created)}支商人漕运单位。")
    return created


def _city_region_id(state: GameState, city_id: int) -> int:
    return int(state.cities.get(int(city_id), {}).get("region_id", 0))


def _deliver_loot(state: GameState, regime_id: int, good: str, amount: float) -> None:
    capital = int(state.regimes.get(regime_id, {}).get("capital") or 0)
    region_id = _city_region_id(state, capital)
    if region_id in state.regions:
        record = region_economy(state, region_id)
        accepted = min(float(amount), warehouse_room(state, region_id, good))
        record["warehouse"][good] = round(float(record["warehouse"].get(good, 0.0)) + accepted, 2)


def _hostile_army_at(state: GameState, unit: dict, city_id: int):
    """Return the first army able to seize a convoy at ``city_id``."""
    owner = int(unit.get("regime_id", 0))
    return next(
        (
            army
            for army in state.armies.values()
            if army.soldiers > 0
            and army.location_id == city_id
            and army.regime_id != owner
            and (owner == 0 or state.at_war(owner, army.regime_id))
        ),
        None,
    )


def _loot_convoy(state: GameState, unit: dict, hostile, city_id: int) -> None:
    amount = float(unit.get("amount", 0.0))
    _deliver_loot(state, hostile.regime_id, str(unit["good"]), amount)
    owner = int(unit.get("regime_id", 0))
    if owner in {0, state.player_regime_id} or hostile.regime_id == state.player_regime_id:
        label = "官漕" if unit.get("kind") == "official" else "商人漕运"
        state.add_log(
            f"{label}#{unit['id']}在{state.city_name(city_id)}中途被军队#{hostile.id}摧毁并劫掠，"
            f"损失剩余{amount:g}单位{GOOD_NAMES.get(str(unit['good']), unit['good'])}，物资运往敌军首都。"
        )


def _log_official_convoy_progress(
    state: GameState,
    unit: dict,
    path: list[int],
    road_costs: dict[tuple[int, int], float],
    attrition: float,
) -> None:
    """Write one compact monthly progress line for the player's official convoy."""
    if unit.get("kind") != "official" or int(unit.get("regime_id", 0)) != state.player_regime_id:
        return
    index = min(max(0, int(unit.get("path_index", 0))), max(0, len(path) - 1))
    segments = max(1, len(path) - 1)
    partial = 0.0
    if index < len(path) - 1:
        edge = (min(path[index], path[index + 1]), max(path[index], path[index + 1]))
        edge_cost = max(0.01, float(road_costs.get(edge, 1.0)))
        partial = min(1.0, max(0.0, float(unit.get("movement_progress", 0.0)) / edge_cost))
    percent = min(100, int(math.floor((index + partial) / segments * 100 + 0.5)))
    source = state.regions.get(int(unit.get("source_region_id", 0)), {}).get("name", "未知")
    target = state.regions.get(int(unit.get("target_region_id", 0)), {}).get("name", "未知")
    good_name = GOOD_NAMES.get(str(unit.get("good", "")), str(unit.get("good", "")))
    state.add_log(
        f"官漕#{unit['id']}月度进度：{source}→{target}，已完成{percent}%（路线{index}/{segments}），"
        f"现位于{state.city_name(path[index])}，剩余{format_resource(unit.get('amount', 0))}单位{good_name}；"
        f"本月损耗{format_resource(attrition)}，累计损耗{format_resource(unit.get('total_attrition', 0))}。"
    )


def settle_logistics(state: GameState, rng: random.Random | None = None) -> None:
    from ...rules.military import effective_road_type

    rng = rng or random.Random(state.turn_number * 7919)
    data = economy_data(state)
    survivors = []
    road_costs: dict[tuple[int, int], float] = {}
    for road in state.roads:
        edge = (min(int(road["from"]), int(road["to"])), max(int(road["from"]), int(road["to"])))
        cost = {1: 1.0, 2: 1.0, 3: 0.3, 4: 0.5}.get(effective_road_type(state, road), 1.0)
        road_costs[edge] = min(cost, road_costs.get(edge, cost))
    for unit in data["logistics_units"]:
        owner = int(unit.get("regime_id", 0))
        unit["age"] = int(unit.get("age", 0)) + 1
        previous_amount = float(unit.get("amount", 0.0))
        unit.setdefault("initial_amount", previous_amount)
        unit.setdefault("total_attrition", 0.0)
        ai_official_convoy = (
            unit.get("kind") == "official"
            and (
                "ai_official_convoy_no_attrition" in unit.get("modifiers", [])
                or owner not in {0, state.player_regime_id}
            )
        )
        attrition_rate = 0.0 if ai_official_convoy else 0.05 if "jiankang_transfer_warehouse" in unit.get("modifiers", []) else 0.1
        attrition = round(previous_amount * attrition_rate, 2)
        unit["amount"] = round(max(0.0, previous_amount - attrition), 2)
        unit["total_attrition"] = round(float(unit.get("total_attrition", 0.0)) + attrition, 2)
        player_official = unit.get("kind") == "official" and owner == state.player_regime_id
        if attrition > 0 and not player_official:
            _add_visible_economic_log(
                state,
                owner,
                f"漕运#{unit['id']}结算途中损耗{attrition:g}单位"
                f"{GOOD_NAMES.get(str(unit['good']), unit['good'])}。",
            )
        if float(unit["amount"]) <= 0:
            label = "官漕" if unit.get("kind") == "official" else "商人漕运"
            _add_visible_economic_log(
                state,
                owner,
                f"{label}#{unit['id']}中途因沿途损耗耗尽并被摧毁，累计损耗"
                f"{format_resource(unit.get('total_attrition', 0))}单位{GOOD_NAMES.get(str(unit['good']), unit['good'])}。",
            )
            continue
        movement = 2.0 if owner == state.player_regime_id and state.flags.get("v12_strategy_effect:13") and unit.get("kind") == "official" else 1.0
        if owner == state.player_regime_id and state.flags.get("v12_strategy_effect:30") and unit.get("kind") == "official":
            movement *= 1.2
        path = [int(city) for city in unit.get("path", [])]
        index = int(unit.get("path_index", 0))
        progress = float(unit.get("movement_progress", 0.0))
        destroyed = False
        if not path or index >= len(path):
            label = "官漕" if unit.get("kind") == "official" else "商人漕运"
            _add_visible_economic_log(
                state,
                owner,
                f"{label}#{unit['id']}因运输路线失效而中途撤销，损失剩余"
                f"{format_resource(unit.get('amount', 0))}单位{GOOD_NAMES.get(str(unit.get('good', '')), unit.get('good', ''))}。",
            )
            continue

        hostile = _hostile_army_at(state, unit, path[index])
        if hostile:
            _loot_convoy(state, unit, hostile, path[index])
            continue

        while index < len(path) - 1:
            edge = (min(path[index], path[index + 1]), max(path[index], path[index + 1]))
            cost = float(road_costs.get(edge, 1.0)) - progress
            if cost > movement + 1e-9:
                unit["movement_progress"] = round(progress + movement, 2)
                movement = 0
                break
            movement -= cost
            progress = 0.0
            index += 1
            unit["path_index"] = index
            unit["movement_progress"] = 0.0
            city_id = path[index]
            hostile = _hostile_army_at(state, unit, city_id)
            if hostile:
                _loot_convoy(state, unit, hostile, city_id)
                destroyed = True
                break
            region_id = _city_region_id(state, city_id)
            stability = int(region_economy(state, region_id)["stability"]) if region_id in state.regions else 100
            risk = max(0.0, (50 - stability) / 100)
            if unit.get("kind") == "merchant" and state.flags.get("v12_strategy_effect:23") and stability >= 70:
                risk = 0.0
            if owner == state.player_regime_id and state.flags.get("v12_strategy_effect:7") and unit.get("kind") == "official":
                risk = max(0.0, risk - 0.05)
            if risk and rng.random() < risk:
                label = "官漕" if unit.get("kind") == "official" else "商人漕运"
                _add_visible_economic_log(
                    state,
                    owner,
                    f"{label}#{unit['id']}经过{state.city_name(city_id)}时中途遭劫毁，损失剩余"
                    f"{format_resource(unit.get('amount', 0))}单位{GOOD_NAMES.get(str(unit['good']), unit['good'])}。",
                )
                destroyed = True
                break
        if destroyed:
            continue
        if index >= len(path) - 1:
            target = region_economy(state, int(unit["target_region_id"]))
            destination = "warehouse" if unit.get("kind") == "official" else "market"
            delivered = float(unit["amount"])
            if destination == "warehouse":
                delivered = min(delivered, warehouse_room(state, int(unit["target_region_id"]), str(unit["good"])))
            target[destination][str(unit["good"])] = round(
                float(target[destination].get(str(unit["good"]), 0.0)) + delivered,
                2,
            )
            if destination == "market":
                enforce_market_capacity(state, int(unit["target_region_id"]))
            else:
                enforce_warehouse_capacity(state, int(unit["target_region_id"]))
            if unit.get("kind") == "official":
                arrival_message = (
                    f"官漕#{unit['id']}抵达{state.regions[int(unit['target_region_id'])]['name']}："
                    f"启运{format_resource(unit.get('initial_amount', delivered))}单位"
                    f"{GOOD_NAMES.get(str(unit['good']), unit['good'])}，实际入库{format_resource(delivered)}，"
                    f"累计损耗{format_resource(max(0.0, float(unit.get('initial_amount', delivered)) - delivered))}"
                    f"（沿途损耗{format_resource(unit.get('total_attrition', 0))}）。"
                )
            else:
                arrival_message = (
                    f"商人漕运#{unit['id']}抵达目的地，向市场交付{format_resource(delivered)}单位"
                    f"{GOOD_NAMES.get(str(unit['good']), unit['good'])}。"
                )
            _add_visible_economic_log(state, owner, arrival_message)
            continue
        if unit.get("kind") == "merchant" and int(unit["age"]) >= MERCHANT_MAX_TURNS:
            state.add_log(f"商人漕运#{unit['id']}超过两回合未抵达，已退出市场。")
            continue
        _log_official_convoy_progress(state, unit, path, road_costs, attrition)
        survivors.append(unit)
    data["logistics_units"] = survivors


def _family_type(state: GameState, person_id: int | None) -> int | None:
    person = state.persons.get(int(person_id or 0), {})
    family = state.families.get(int(person.get("family_id") or 0), {})
    return int(family["family_type"]) if family.get("family_type") is not None else None


def governor_kind(state: GameState, region_id: int) -> str:
    governor = state.regions[int(region_id)].get("governor")
    if not governor:
        return "none"
    return {0: "royal", 1: "high", 2: "humble"}.get(_family_type(state, int(governor)), "humble")


def auto_fill_vacant_offices(state: GameState) -> dict[str, list[tuple[str, int]]]:
    """Fill vacant player offices: royal governors first, high-family central officials first."""
    regime = state.player_regime
    internal = regime.setdefault("internal", {})
    emperor = int(internal.get("emperor") or 0)
    occupied = {
        int(value) for value in internal.values()
        if isinstance(value, int) and int(value) > 0
    }
    occupied |= {int(region.get("governor") or 0) for region in state.regions.values() if region.get("governor")}
    available = [
        person for person in state.persons.values()
        if int(person.get("country_id", 0)) == state.player_regime_id
        and int(person.get("status", 0)) == 1
        and int(person.get("id", 0)) not in occupied | {emperor}
    ]
    governor_exclusions = {"刘义康", "刘义庆", "刘劭"}

    def rank(person: dict, priority: dict[int | None, int]) -> tuple[int, int, int, int]:
        person_id = int(person["id"])
        family_type = _family_type(state, person_id)
        return (
            priority.get(family_type, 9),
            -int(person.get("level", 0)),
            -person_power(state, person),
            person_id,
        )

    result: dict[str, list[tuple[str, int]]] = {"central": [], "governors": []}
    legal_names = set(regime.get("regions", []))
    for region_id, region in sorted(state.regions.items()):
        if region.get("name") not in legal_names or region.get("governor"):
            continue
        eligible = [
            person for person in available
            if not (_family_type(state, int(person["id"])) == 0 and state.person_name(int(person["id"])) in governor_exclusions)
        ]
        candidates = sorted(eligible, key=lambda person: rank(person, {0: 0, 1: 1, 2: 2, None: 3}))
        if not candidates:
            break
        person = candidates[0]
        person_id = int(person["id"])
        region["governor"] = person_id
        person["location_id"] = _region_capital(state, int(region_id))
        available.remove(person)
        result["governors"].append((str(region["name"]), person_id))

    from ...constants import OFFICE_NAMES

    for office, occupant in internal.items():
        if office not in OFFICE_NAMES or office == "emperor" or isinstance(occupant, list) or occupant:
            continue
        candidates = sorted(available, key=lambda person: rank(person, {1: 0, 0: 1, 2: 2, None: 3}))
        if not candidates:
            break
        person = candidates[0]
        person_id = int(person["id"])
        internal[office] = person_id
        available.remove(person)
        result["central"].append((str(office), person_id))
    if result["central"] or result["governors"]:
        state.add_log(
            f"朝廷自动补官：中枢{len(result['central'])}人，刺史{len(result['governors'])}人。"
        )
    return result


def settle_local_governance(state: GameState, rng: random.Random | None = None) -> None:
    rng = rng or random.Random(state.turn_number * 3571)
    for region_id, region in sorted(state.regions.items()):
        record = region_economy(state, region_id)
        kind = governor_kind(state, region_id)
        controller = int(region.get("controller", 0))
        if controller and controller != state.player_regime_id:
            record["control"] = 100
        else:
            control_delta = {"none": -15, "humble": 1, "high": 2, "royal": 12 if state.flags.get("v12_strategy_effect:19") else 10}[kind]
            stationed_armies = sum(
                1
                for army in state.armies.values()
                if army.soldiers > 0
                and army.regime_id == controller
                and _city_region_id(state, army.location_id) == int(region_id)
            )
            control_delta += stationed_armies * 5
            control_cap = 70 if kind in {"humble", "high"} else 100
            record["control"] = int(clamp(int(record.get("control", 0)) + control_delta, 0, control_cap))
        region["control"] = record["control"]
        no_governor_annexation = 1.75 if state.flags.get("v12_strategy_effect:18") else 2.0
        annex_multiplier = {"none": no_governor_annexation, "humble": 1.5, "high": 2.5, "royal": 0.0}[kind]
        record["annexation_progress"] = float(record.get("annexation_progress", 0.0)) + annex_multiplier
        land = record["land"]
        while record["annexation_progress"] >= 1 and land["self_farm"] + land["smallholder"] > 0:
            source = "self_farm" if land["self_farm"] > 0 else "smallholder"
            land[source] -= 1
            land["gentry"] += 1
            record["annexation_progress"] -= 1
        if kind == "royal":
            governor = state.persons.get(int(region.get("governor") or 0))
            if governor:
                attrs = governor.setdefault("attributes", {})
                attrs["base_power"] = int(attrs.get("base_power", 0)) + 2 + (1 if state.flags.get("v12_strategy_effect:19") else 0)
                if state.month == 1:
                    governor["level"] = min(9, int(governor.get("level", 0)) + 1)
                power = person_power(state, governor)
                chance = max(0.0, min(0.25, (power - 1200) / 8000))
                if int(governor.get("id", 0)) != 26 and chance and rng.random() < chance:
                    state.flags.setdefault("v12_royal_revolt_candidates", []).append(int(governor["id"]))
                    _trigger_royal_revolt(state, region_id, int(governor["id"]))


def settle_peacetime_stability(state: GameState) -> list[int]:
    """Peaceful controllers restore three local-stability points in every region each month."""
    restored: list[int] = []
    warring_regimes = {int(regime_id) for pair in state.wars for regime_id in pair}
    for region_id, region in state.regions.items():
        controller = int(region.get("controller", 0))
        if controller <= 0 or controller in warring_regimes:
            continue
        record = region_economy(state, int(region_id))
        if str(state.flags.get("rules_version", "")) == "1.3" and not bool(record.get("culture_sufficient", False)):
            continue
        before = int(record.get("stability", 0))
        record["stability"] = min(100, before + 3)
        region["local_stability"] = record["stability"]
        if int(record["stability"]) > before:
            restored.append(int(region_id))
    return restored


def _trigger_royal_revolt(
    state: GameState,
    region_id: int,
    governor_id: int,
    army_types: list[int] | None = None,
) -> None:
    """Turn a successful royal-governor revolt check into a real map rebellion."""
    if int(governor_id) == 26:
        return
    rebel_id = 13
    if rebel_id not in state.regimes:
        state.add_log(f"宗室刺史{state.person_name(governor_id)}权势坐大，开始图谋叛乱。")
        return
    region = state.regions[region_id]
    region_name = str(region["name"])
    former_owner = next(
        (int(regime_id) for regime_id, regime in state.regimes.items() if region_name in regime.get("regions", [])),
        int(region.get("controller", 0)),
    )
    if former_owner == rebel_id:
        return
    if former_owner in state.regimes:
        state.regimes[former_owner]["regions"] = [name for name in state.regimes[former_owner].get("regions", []) if name != region_name]
    rebel = state.regimes[rebel_id]
    rebel["name"] = f"{state.person_name(governor_id)}叛军"
    rebel["regions"] = list(dict.fromkeys(list(rebel.get("regions", [])) + [region_name]))
    capital = _region_capital(state, region_id)
    rebel["capital"] = capital
    rebel.setdefault("internal", {})["emperor"] = governor_id
    rebel["authority"] = max(100, int(rebel.get("authority", 0)))
    region["controller"] = rebel_id
    region_economy(state, region_id)["control"] = 100
    region["control"] = 100
    state.persons[governor_id]["country_id"] = rebel_id
    pair = state.relation_pair(former_owner, rebel_id)
    if former_owner and pair not in state.wars:
        from ...rules.diplomacy import declare_war

        declare_war(state, rebel_id, former_owner)
    compositions = army_types or [1]
    created: list[int] = []
    for index, unit_type in enumerate(compositions):
        army_id = max(state.armies, default=0) + 1
        rebel_army = Army(
            id=army_id,
            regime_id=rebel_id,
            army_type=1 if int(unit_type) == 4 else 0,
            units=[{"type": int(unit_type), "count": 1000} for _ in range(5 if army_types else 3)],
            commander=governor_id if index == 0 else None,
            location_id=capital,
        )
        rebel_army.supply_food = army_supply_capacity(rebel_army)
        state.armies[army_id] = rebel_army
        created.append(army_id)
    state.add_log(
        f"宗室刺史{state.person_name(governor_id)}在{region_name}起兵叛乱，"
        f"组建{len(created)}支军队（{'、'.join('#' + str(item) for item in created)}）。"
    )


def dismiss_governor(state: GameState, region_id: int, rng: random.Random | None = None) -> str:
    region = state.regions.get(int(region_id))
    if not region or region.get("name") not in state.player_regime.get("regions", []):
        raise RuleError("只能处理本国地区的刺史")
    governor = int(region.get("governor") or 0)
    if not governor:
        raise RuleError("该地区没有刺史")
    kind = governor_kind(state, region_id)
    cost = 500 if kind == "royal" else 100
    if state.authority < cost:
        raise RuleError(f"权威不足{cost}")
    state.authority -= cost
    if kind == "royal":
        rng = rng or random.Random(state.turn_number * 7919 + int(region_id))
        if rng.random() < 0.5:
            capital = _region_capital(state, int(region_id))
            has_water = any(
                int(road.get("type", 0)) == 3
                and capital in {int(road.get("from", 0)), int(road.get("to", 0))}
                for road in state.roads
            )
            _trigger_royal_revolt(
                state,
                int(region_id),
                governor,
                [1, 1, 4, 4] if has_water else [1, 1, 1, 1],
            )
            return f"卸任{state.person_name(governor)}失败：宗室刺史起兵反叛，权威-{cost}。"
    region["governor"] = None
    message = f"免去{state.person_name(governor)}的{region['name']}刺史职务，权威-{cost}。"
    state.add_log(message)
    return message


def _adjacent_regions(state: GameState) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {int(region_id): set() for region_id in state.regions}
    for road in state.roads:
        left, right = _city_region_id(state, int(road["from"])), _city_region_id(state, int(road["to"]))
        if left and right and left != right:
            result.setdefault(left, set()).add(right)
            result.setdefault(right, set()).add(left)
    return result


def settle_migration(state: GameState, rng: random.Random | None = None) -> None:
    rng = rng or random.Random(state.turn_number * 1291)
    adjacency = _adjacent_regions(state)
    # A unit may migrate at most once per monthly settlement even if its destination
    # is visited later in region order.
    moved_ids: set[int] = set()
    for region_id in sorted(state.regions):
        record = region_economy(state, region_id)
        stability = int(record["stability"])
        units = [unit for unit in population_units(state, region_id) if int(unit["id"]) not in moved_ids]
        if stability < 50 and units:
            neighbors = [target for target in adjacency.get(region_id, set()) if int(region_economy(state, target)["stability"]) > stability]
            if neighbors:
                target = max(neighbors, key=lambda item: (int(region_economy(state, item)["stability"]), -item))
                rate = (50 - stability) / 1000
                target_record = region_economy(state, target)
                target_land = sum(max(0, int(value)) for value in target_record["land"].values())
                target_population = len(population_units(state, target))
                if target_land <= target_population:
                    rate *= 0.1
                moved = 0
                for unit in units:
                    if rng.random() < rate:
                        unit["region_id"] = target
                        unit["occupation"] = "farmer"
                        moved_ids.add(int(unit["id"]))
                        moved += 1
                if moved:
                    target_record["stability"] = int(clamp(int(target_record["stability"]) - moved, 0, 100))
                    state.regions[target]["local_stability"] = target_record["stability"]
                    state.add_log(
                        f"{state.regions[region_id]['name']}有{moved}个人口单位逃往{state.regions[target]['name']}并转为农民，"
                        f"目标地区稳定度-{moved}。"
                    )
        elif stability >= 70:
            rate = max(0.01, (stability - 70) / 300)
            if int(state.flags.get("v12_farming_conversion_until", -1)) >= state.turn_number:
                rate *= 1.20
            if any(int(item.get("id", 0)) == 1203 for item in state.national_modifiers):
                rate *= 1.20
            if any(int(item.get("id", 0)) == 1204 for item in state.national_modifiers):
                rate *= 1.25
            converted = 0
            for unit in units:
                if unit.get("occupation") == "refugee" and rng.random() < rate:
                    unit["occupation"] = "farmer"
                    converted += 1
            if converted:
                state.add_log(f"{state.regions[region_id]['name']}稳定安定，{converted}个流民单位转为农民。")


def _apply_severe_weather_losses(
    state: GameState,
    region_id: int,
    weather_name: str,
    rng: random.Random,
) -> tuple[int, int]:
    if weather_name not in {"地震", "台风"}:
        return 0, 0
    units = population_units(state, region_id)
    losses = min(len(units), rng.randint(1, 5))
    victim_ids = {
        int(unit["id"]) for unit in rng.sample(units, losses)
    } if losses else set()
    if victim_ids:
        data = economy_data(state)
        data["population_units"] = [
            unit for unit in data["population_units"]
            if int(unit["id"]) not in victim_ids
        ]
    record = region_economy(state, region_id)
    old_stability = int(record.get("stability", 0))
    record["stability"] = int(clamp(old_stability - 10, 0, 100))
    state.regions[region_id]["local_stability"] = record["stability"]
    actual_stability_loss = old_stability - int(record["stability"])
    state.add_log(
        f"七月{state.regions[region_id]['name']}发生{weather_name}："
        f"损失{losses}个人口单位，地方稳定度-{actual_stability_loss}，本年收成-10%。"
    )
    return losses, actual_stability_loss


def _region_production_bonus(
    state: GameState,
    region_id: int,
    weather_factor: float = 1.0,
) -> float:
    bonus = 1.0
    if any(int(item.get("id", 0)) == 1203 for item in state.national_modifiers):
        bonus += 0.05
    if any(int(item.get("id", 0)) == 1204 for item in state.national_modifiers):
        bonus += 0.10
    if (
        state.flags.get("v12_farming_bonus_pending")
        and int(state.regions[region_id].get("controller", 0)) == state.player_regime_id
        and int(region_economy(state, region_id).get("stability", 0)) >= 70
        and weather_factor >= 1.0
    ):
        bonus += 0.05
    return bonus


def projected_region_production(state: GameState, region_id: int) -> dict[str, float | int]:
    """Non-mutating normal-weather estimate for the development-stage detail view."""
    region_id = int(region_id)
    record = region_economy(state, region_id)
    occupations, _cultures = population_counts(state, region_id)
    land_total = sum(int(value) for value in record["land"].values())
    bonus = _region_production_bonus(state, region_id)
    return {
        "farmers": int(occupations["farmer"]),
        "artisans": int(occupations["artisan"]),
        "land": int(land_total),
        "production_bonus": round(bonus, 2),
        "food": round(min(occupations["farmer"], land_total) * 2 * bonus, 2),
        "cloth": round(occupations["artisan"] * 2 * bonus, 2),
    }


def annual_production(state: GameState, rng: random.Random | None = None) -> list[dict[str, Any]]:
    from .climate import ensure_annual_climate, roll_region_weather
    from ...rules.ai_modifiers import ai_difficulty_resource_income_bonus

    rng = rng or random.Random(state.year * 7)
    climate = ensure_annual_climate(state)
    report: list[dict[str, Any]] = []
    for region_id in sorted(state.regions):
        record = region_economy(state, region_id)
        weather_name, weather_factor = roll_region_weather(state, region_id, rng)
        disaster_deaths, stability_loss = _apply_severe_weather_losses(
            state, region_id, weather_name, rng
        )
        occupations, _cultures = population_counts(state, region_id)
        land_total = sum(int(value) for value in record["land"].values())
        production_bonus = _region_production_bonus(state, region_id, weather_factor)
        food = round(min(occupations["farmer"], land_total) * 2 * weather_factor * production_bonus, 2)
        cloth = round(occupations["artisan"] * 2 * production_bonus, 2)
        record["last_weather"] = weather_name
        collection_coefficient = tax_collection_coefficient(state, region_id)
        active_tax_rates = {
            good: production_tax_rate(state, region_id, good)
            for good in ("food", "cloth")
        }
        record["tax_collection_coefficient"] = collection_coefficient
        record["tax_rates"] = dict(active_tax_rates)
        controller = int(state.regions[region_id].get("controller", 0))
        ai_income_bonus_rate = ai_difficulty_resource_income_bonus(state, controller)
        ai_resource_bonus = {"food": 0.0, "cloth": 0.0}
        collected_tax = {"food": 0.0, "cloth": 0.0}
        for good, output in (("food", food), ("cloth", cloth)):
            tax = round(output * active_tax_rates[good], 2)
            accepted_tax = round(min(tax, warehouse_room(state, region_id, good)), 2)
            collected_tax[good] = accepted_tax
            record["warehouse"][good] = round(float(record["warehouse"].get(good, 0.0)) + accepted_tax, 2)
            record["market"][good] = round(float(record["market"].get(good, 0.0)) + output - accepted_tax, 2)
            if ai_income_bonus_rate > 0:
                generated = min(
                    round(tax * ai_income_bonus_rate, 2),
                    warehouse_room(state, region_id, good),
                )
                record["warehouse"][good] = round(float(record["warehouse"].get(good, 0.0)) + generated, 2)
                ai_resource_bonus[good] = round(generated, 2)
        copper_from_food_tax = round(
            collected_tax["food"] * 0.5 * local_income_multiplier(state, region_id, controller),
            2,
        ) if controller else 0.0
        if copper_from_food_tax and controller in state.regimes:
            from ...rules.treasury import change_treasury

            change_treasury(state, controller, copper_from_food_tax)
        enforce_market_capacity(state, region_id)
        enforce_warehouse_capacity(state, region_id)
        population = len(population_units(state, region_id))
        projected_balance = round(float(record["market"]["food"]) - population, 2)
        report.append({
            "region_id": int(region_id),
            "region": state.regions[region_id]["name"],
            "controller": int(state.regions[region_id].get("controller", 0)),
            "climate": climate["name"],
            "weather": weather_name,
            "weather_factor": weather_factor,
            "disaster_deaths": disaster_deaths,
            "stability_loss": stability_loss,
            "population": population,
            "farmers": int(occupations["farmer"]),
            "land": int(land_total),
            "food": float(food),
            "cloth": float(cloth),
            "ai_food_income_bonus": ai_resource_bonus["food"],
            "ai_cloth_income_bonus": ai_resource_bonus["cloth"],
            "tax_collection_coefficient": collection_coefficient,
            "statutory_food_tax_rate": TAX_LAW_RATES.get(int(state.laws.get("tax", 3)), 0.15),
            "food_tax_rate": active_tax_rates["food"],
            "food_tax": collected_tax["food"],
            "copper_from_food_tax": copper_from_food_tax,
            "national_treasury_income": copper_from_food_tax,
            "warehouse_food": round(float(record["warehouse"]["food"]), 2),
            "market_food": round(float(record["market"]["food"]), 2),
            "projected_balance": projected_balance,
            "shortage": projected_balance < 0,
        })
        state.add_log(
            f"七月{state.regions[region_id]['name']}收获（{weather_name}）：粮食{food:g}、布匹{cloth:g}；"
            f"征收粮税{collected_tax['food']:g}，按控制度折收国库铜钱{copper_from_food_tax:g}。"
        )
    if state.flags.get("v12_farming_bonus_pending"):
        state.flags["v12_farming_bonus_pending"] = False
    manpower_gains = collect_annual_manpower(state)
    for row in report:
        row["national_manpower_gain"] = int(manpower_gains.get(int(row.get("controller", 0)), 0))
    state.flags["pending_v12_production_report"] = report
    climate["revealed_by_harvest"] = True
    return report


def _new_population_unit(state: GameState, region_id: int, occupation: str, culture: str) -> None:
    data = economy_data(state)
    unit_id = int(data["next_population_id"])
    data["next_population_id"] = unit_id + 1
    data["population_units"].append({
        "id": unit_id,
        "region_id": int(region_id),
        "size": POPULATION_UNIT_SIZE,
        "occupation": occupation,
        "culture": culture,
    })


def starvation_effects(population: int, shortage: float) -> tuple[float, int, int]:
    """Scale famine linearly: 50% shortage means 20% deaths and -50 stability."""
    if population <= 0 or shortage <= 0:
        return 0.0, 0, 0
    shortage_ratio = float(clamp(float(shortage) / population, 0.0, 1.0))
    death_count = min(population, int(math.floor(population * shortage_ratio * 0.40 + 0.5)))
    stability_loss = min(100, int(math.floor(shortage_ratio * 100 + 0.5)))
    return shortage_ratio, death_count, stability_loss


def annual_consumption(state: GameState, rng: random.Random | None = None) -> list[dict[str, Any]]:
    rng = rng or random.Random(state.year * 9)
    death_order = {"refugee": 0, "farmer": 1, "artisan": 2, "landlord": 3}
    data = economy_data(state)
    report: list[dict[str, Any]] = []
    for region_id in sorted(state.regions):
        record = region_economy(state, region_id)
        units = population_units(state, region_id)
        required = float(len(units))
        if str(state.flags.get("rules_version", "")) == "1.3":
            from ..v1_3.culture import food_consumption_multiplier

            required *= food_consumption_multiplier(state, region_id)
        available = float(record["market"].get("food", 0.0))
        consumed = min(required, available)
        record["market"]["food"] = round(available - consumed, 2)
        shortage = round(max(0.0, required - consumed), 2)
        shortage_ratio, deaths, stability_loss = starvation_effects(len(units), shortage)
        if shortage > 0:
            victims = sorted(units, key=lambda unit: (death_order.get(str(unit.get("occupation")), 9), int(unit["id"])))[:deaths]
            victim_ids = {int(unit["id"]) for unit in victims}
            data["population_units"] = [unit for unit in data["population_units"] if int(unit["id"]) not in victim_ids]
            record["stability"] = int(clamp(int(record["stability"]) - stability_loss, 0, 100))
            state.regions[region_id]["local_stability"] = record["stability"]
            state.add_log(
                f"十二月{state.regions[region_id]['name']}缺粮{shortage:g}单位（{shortage_ratio:.1%}），"
                f"饿死{len(victims)}个人口单位，地方稳定度-{stability_loss}。"
            )
            record["surplus_years"] = 0
        else:
            record["surplus_years"] = int(record.get("surplus_years", 0)) + 1 if record["market"]["food"] > 0 else 0
        consumption = {
            "region_id": int(region_id),
            "required": required,
            "available": available,
            "consumed": consumed,
            "shortage": shortage,
            "shortage_ratio": shortage_ratio,
            "deaths": len(victims) if shortage > 0 else 0,
            "stability_loss": stability_loss,
        }
        record["last_consumption"] = dict(consumption)
        report.append(consumption)
        if int(record["surplus_years"]) >= 3:
            current = population_units(state, region_id)
            record["growth_progress"] = float(record.get("growth_progress", 0.0)) + len(current) * 0.02
            while record["growth_progress"] >= 1 and current:
                occupation = str(rng.choice(current)["occupation"])
                culture = str(rng.choice(current)["culture"])
                _new_population_unit(state, region_id, occupation, culture)
                record["growth_progress"] -= 1
                current = population_units(state, region_id)
    if str(state.flags.get("rules_version", "")) == "1.3":
        from ..v1_3.culture import handle_famine_approval

        handle_famine_approval(state, report, rng)
    return report


def january_market_cleanup(state: GameState) -> list[dict[str, Any]]:
    thresholds = {1: 5, 2: 8, 3: 10, 4: 15}
    threshold = thresholds.get(int(state.laws.get("economy", 1)))
    report = []
    for region_id in sorted(state.regions):
        record = region_economy(state, region_id)
        removed = {}
        for good in GOODS:
            stock = float(record["market"].get(good, 0.0))
            retained = min(stock, market_demand(state, region_id, good) * JANUARY_RETAIN_RATE)
            record["market"][good] = round(retained, 2)
            removed[good] = round(max(0.0, stock - retained), 2)
        removed_total = round(sum(removed.values()), 2)
        annexed = int(removed_total // threshold) if threshold else 0
        land = record["land"]
        moved = 0
        for source in ("self_farm", "smallholder"):
            transfer = min(int(land.get(source, 0)), annexed - moved)
            land[source] -= transfer
            land["gentry"] += transfer
            moved += transfer
            if moved >= annexed:
                break
        report.append({"region_id": region_id, "removed": removed, "removed_total": removed_total, "annexed_land": moved})
    economy_data(state)["last_january_market_cleanup"] = report
    return report


def settle_army_supply(state: GameState) -> None:
    from ...rules.ai_modifiers import ai_difficulty_supply_multiplier

    for army in sorted(list(state.armies.values()), key=lambda item: int(item.id)):
        region_id = _city_region_id(state, army.location_id)
        if region_id not in state.regions:
            continue
        capacity = army_supply_capacity(army)
        army.supply_food = round(float(clamp(float(army.supply_food), 0, capacity)), 2)
        warehouse = region_economy(state, region_id)["warehouse"]
        friendly_depot = int(state.regions[region_id].get("controller", 0)) == army.regime_id
        if friendly_depot:
            refill = min(capacity - army.supply_food, float(warehouse.get("food", 0.0)))
            army.supply_food = round(army.supply_food + refill, 2)
            warehouse["food"] = round(float(warehouse.get("food", 0.0)) - refill, 2)


        wartime = any(army.regime_id in pair for pair in state.wars)
        needed = round(army.soldiers / 1000 * (0.2 if wartime else 0.1), 2)
        needed = round(needed * ai_difficulty_supply_multiplier(state, army.regime_id), 2)
        if any(str(item.get("id", "")) in {"1020", "v12_changchouliangsha"} for item in army.modifiers):
            needed = round(needed * 0.5, 2)
        if wartime and state.flags.get("v12_strategy_effect:30") and army.regime_id == state.player_regime_id:
            needed = round(needed * 0.85, 2)
        if army.supply_food + 1e-9 >= needed:
            army.supply_food = round(army.supply_food - needed, 2)
        else:
            half_penalty = (
                wartime
                and state.flags.get("v12_strategy_effect:30")
                and army.regime_id == state.player_regime_id
                and needed > 0
                and army.supply_food / needed >= 0.5
            )
            army.supply_food = 0.0
            before = army.soldiers
            for unit in army.units:
                unit["count"] = max(0, int(int(unit.get("count", 0)) * (0.9 if half_penalty else 0.8)))
            army.units = [unit for unit in army.units if int(unit.get("count", 0)) > 0]
            morale_loss = 15 if half_penalty else 30
            army.morale = max(0, int(army.morale) - morale_loss)
            state.add_log(f"军队#{army.id}在{state.regions[region_id]['name']}随军粮耗尽，损失{before - army.soldiers}人、士气-{morale_loss}。")
            capacity = army_supply_capacity(army)
        if friendly_depot:
            refill = min(capacity - army.supply_food, float(warehouse.get("food", 0.0)))
            army.supply_food = round(army.supply_food + refill, 2)
            warehouse["food"] = round(float(warehouse.get("food", 0.0)) - refill, 2)


def ai_standing_force_target(state: GameState, regime_id: int) -> int:
    """Return a sustainable AI establishment based on territory and enemies."""
    if regime_id == 2:
        return WEI_STANDING_FORCE_TARGET
    controlled = sum(
        1 for region in state.regions.values()
        if int(region.get("controller", 0)) == regime_id
    )
    if controlled <= 0:
        return 0
    enemies = {
        int(side)
        for pair in state.wars
        if regime_id in {int(item) for item in pair}
        for side in pair
        if int(side) != regime_id
    }
    enemy_soldiers = sum(
        army.soldiers for army in state.armies.values()
        if army.regime_id in enemies and army.soldiers > 0
    )
    territorial = max(12_000, controlled * 12_000)
    wartime = math.ceil(enemy_soldiers * 0.75 / 1000) * 1000
    territorial_cap = max(25_000, controlled * 25_000)
    return int(min(max(territorial, wartime), territorial_cap))


def _legacy_free_ai_standing_army(state: GameState, regime_id: int) -> int:
    if regime_id == state.player_regime_id or regime_id not in state.regimes:
        return 0
    target = ai_standing_force_target(state, regime_id)
    if target <= 0:
        return 0
    armies = sorted(
        (army for army in state.armies.values() if army.regime_id == regime_id and army.soldiers > 0),
        key=lambda army: (army.soldiers, army.id),
    )
    total = sum(army.soldiers for army in armies)
    monthly_limit = WEI_MONTHLY_REINFORCEMENT if regime_id == 2 else min(30_000, max(3_000, target // 5))
    remaining = min(monthly_limit, max(0, target - total))
    reinforced = 0
    for army in armies:
        for unit in army.units:
            missing = max(0, 1000 - int(unit.get("count", 0)))
            added = min(missing, remaining)
            if added <= 0:
                continue
            unit["count"] = int(unit.get("count", 0)) + added
            remaining -= added
            reinforced += added
            if remaining <= 0:
                break
        if remaining <= 0:
            break
    capital = int(state.regimes[regime_id].get("capital") or 0)
    capital_controlled = capital in state.cities and city_controller(state, capital) == regime_id
    if not capital_controlled:
        fallback = next(
            (
                int(city_id)
                for region_id, region in sorted(state.regions.items())
                if int(region.get("controller", 0)) == regime_id
                for city_id in region.get("cities", [])
                if state.cities.get(int(city_id), {}).get("capital")
            ),
            None,
        )
        if fallback is not None:
            capital = fallback
            state.regimes[regime_id]["capital"] = capital
            capital_controlled = True
            state.add_log(f"{state.regimes[regime_id]['name']}失去旧都，迁都至{state.city_name(capital)}。")
    while remaining >= 1000 and total + reinforced < target and capital_controlled:
        battalions = min(
            9,
            remaining // 1000,
            math.ceil((target - total - reinforced) / 1000),
        )
        if battalions <= 0:
            break
        army_id = max(state.armies, default=0) + 1
        replacement = Army(
            army_id,
            regime_id,
            0,
            [{"type": 1, "count": 1000} for _ in range(int(battalions))],
            morale=80,
            experience=0,
            location_id=capital,
            action_points=1.0,
            max_action_points=1.0,
        )
        replacement.supply_food = round(battalions * 1.2, 2)
        state.armies[army_id] = replacement
        added = int(battalions) * 1000
        remaining -= added
        reinforced += added
    if reinforced:
        state.add_log(f"{state.regimes[regime_id]['name']}常备军补充兵员{reinforced}人。")
    return reinforced


def _settle_ai_standing_army(state: GameState, regime_id: int) -> int:
    """Standing-force values are AI planning targets and never create free troops."""
    return 0


def settle_wei_standing_army(state: GameState) -> int:
    """Compatibility entry point used by focused tests and older callers."""
    return _settle_ai_standing_army(state, 2)


def settle_ai_standing_armies(state: GameState) -> dict[int, int]:
    reinforced: dict[int, int] = {}
    for regime_id in sorted(state.regimes):
        amount = _settle_ai_standing_army(state, int(regime_id))
        if amount:
            reinforced[int(regime_id)] = amount
    return reinforced


def army_supply_capacity(army) -> float:
    return round(max(0, int(army.soldiers)) / 1000 * 0.2 * 6, 2)


def army_supply_months(army, state: GameState | None = None) -> float:
    monthly_wartime = max(0, int(army.soldiers)) / 1000 * 0.2
    if state is not None:
        from ...rules.ai_modifiers import ai_difficulty_supply_multiplier

        monthly_wartime *= ai_difficulty_supply_multiplier(state, army.regime_id)
    if monthly_wartime <= 0:
        return 0.0
    return round(min(6.0, float(army.supply_food) / monthly_wartime), 1)


def annual_manpower_potential(state: GameState, regime_id: int) -> int:
    """Every 10,000-person unit yields at most 10 manpower, scaled by control and support."""
    regime = state.regimes.get(int(regime_id), {})
    support = max(0, min(100, int(regime.get("war_support", 0)))) / 100
    total = 0.0
    for region_id, region in state.regions.items():
        if int(region.get("controller", 0)) != int(regime_id):
            continue
        control = max(0, min(100, int(region_economy(state, int(region_id)).get("control", 0)))) / 100
        population = sum(
            max(0, int(unit.get("size", POPULATION_UNIT_SIZE))) / POPULATION_UNIT_SIZE
            for unit in population_units(state, int(region_id))
        )
        total += population * 10 * control * support
    bonus = int(economy_data(state).setdefault("recruitment_bonus", {}).get(str(regime_id), 0))
    return max(0, int(math.floor(total + 1e-9)) + bonus)


def manpower_capacity(state: GameState, regime_id: int) -> int:
    """Dynamic reserve cap: 20 manpower per controlled 10,000-person unit."""
    population = 0.0
    for region_id, region in state.regions.items():
        if int(region.get("controller", 0)) != int(regime_id):
            continue
        population += sum(
            max(0, int(unit.get("size", POPULATION_UNIT_SIZE))) / POPULATION_UNIT_SIZE
            for unit in population_units(state, int(region_id))
        )
    return max(0, int(math.floor(population * 20 + 1e-9)))


def _ensure_manpower_records(state: GameState) -> dict[str, int]:
    data = economy_data(state)
    manpower = data.setdefault("manpower", {})
    if not data.get("manpower_initialized"):
        for regime_id, regime in state.regimes.items():
            if regime.get("regions"):
                manpower.setdefault(str(int(regime_id)), annual_manpower_potential(state, int(regime_id)))
        data["manpower_initialized"] = True
    return manpower


def manpower_balance(state: GameState, regime_id: int) -> int:
    records = _ensure_manpower_records(state)
    key = str(int(regime_id))
    balance = max(0, int(records.get(key, 0)))
    capacity = manpower_capacity(state, regime_id)
    if balance > capacity:
        records[key] = capacity
        balance = capacity
    return balance


def change_manpower(state: GameState, regime_id: int, amount: int) -> int:
    records = _ensure_manpower_records(state)
    key = str(int(regime_id))
    capacity = manpower_capacity(state, regime_id)
    records[key] = min(capacity, max(0, int(records.get(key, 0)) + int(amount)))
    return int(records[key])


def spend_manpower(state: GameState, regime_id: int, amount: int) -> int:
    amount = max(0, int(amount))
    available = manpower_balance(state, regime_id)
    if amount > available:
        raise RuleError(f"人力不足：需要{amount}，现有人力{available}")
    return change_manpower(state, regime_id, -amount)


def collect_annual_manpower(state: GameState) -> dict[int, int]:
    previous = economy_data(state).get("last_manpower_collection", {})
    if int(previous.get("year", -1)) == int(state.year):
        return {int(key): int(value) for key, value in previous.get("gains", {}).items()}
    gains: dict[int, int] = {}
    for regime_id, regime in state.regimes.items():
        if not regime.get("regions"):
            continue
        potential = annual_manpower_potential(state, int(regime_id))
        if potential <= 0:
            continue
        before = manpower_balance(state, int(regime_id))
        after = change_manpower(state, int(regime_id), potential)
        gain = after - before
        gains[int(regime_id)] = gain
        state.add_log(
            f"七月人力征集：{regime.get('name', regime_id)}获得人力{gain}，"
            f"现有人力{after}/{manpower_capacity(state, int(regime_id))}。"
        )
    economy_data(state)["last_manpower_collection"] = {
        "year": int(state.year),
        "gains": {str(key): value for key, value in gains.items()},
    }
    return gains


def recruitment_cap(state: GameState, regime_id: int) -> int:
    """Compatibility name: current recruitable manpower, not a renewable per-click cap."""
    return manpower_balance(state, regime_id)


def month_index(state: GameState) -> int:
    return state.year * 12 + state.month


def recruitment_available(state: GameState, regime_id: int) -> int:
    return manpower_balance(state, regime_id)


def record_recruitment(state: GameState, regime_id: int, amount: int) -> None:
    available = recruitment_available(state, regime_id)
    if amount <= 0 or amount > available:
        raise RuleError(f"本次征兵需要人力{amount}，现有人力{available}")
    spend_manpower(state, regime_id, int(amount))
    economy_data(state).setdefault("recruitment", {})[str(regime_id)] = {
        "last_month": month_index(state),
        "amount": int(amount),
    }


def apply_battle_stability_loss(state: GameState, city_id: int) -> None:
    if not is_v12(state):
        return
    region_id = _city_region_id(state, city_id)
    if region_id not in state.regions:
        return
    record = region_economy(state, region_id)
    record["stability"] = int(clamp(int(record["stability"]) - 10, 0, 100))
    state.regions[region_id]["local_stability"] = record["stability"]
    state.add_log(f"{state.regions[region_id]['name']}发生战役，地方稳定度-10。")


def run_ai_economic_orders(state: GameState, regime_id: int) -> list[str]:
    # 保留旧入口以兼容既有存档和调用方；具体规划独立维护在AI模块中。
    from .ai_economy import run_ai_economic_plan

    return run_ai_economic_plan(state, regime_id)


def run_ai_august_orders(state: GameState, regime_id: int) -> list[str]:
    """Compatibility alias for saves and callers created before monthly orders were enabled."""
    return run_ai_economic_orders(state, regime_id)


def set_local_policy(state: GameState, regime_id: int, region_id: int, mode: str) -> str:
    """Set the monthly policy followed autonomously by a controlled region."""
    region = _validate_order_region(state, regime_id, region_id)
    if mode not in LOCAL_POLICY_NAMES:
        raise RuleError("未知的地区政策模式")
    region_economy(state, region_id)["local_policy"] = mode
    message = f"{region['name']}地区政策调整为“{LOCAL_POLICY_NAMES[mode]}”。"
    _add_visible_economic_log(state, regime_id, message)
    return message


def _capital_region_id(state: GameState, regime_id: int) -> int:
    capital = int(state.regimes.get(int(regime_id), {}).get("capital") or 0)
    return _city_region_id(state, capital)


def _local_policy_convoy(
    state: GameState,
    source_region_id: int,
    target_region_id: int,
    good: str,
    amount: float,
) -> float:
    if not local_economic_actions_allowed(state):
        return 0.0
    if source_region_id == target_region_id or amount <= 0:
        return 0.0
    before = float(region_economy(state, source_region_id)["warehouse"].get(good, 0.0))
    logistics_id = int(economy_data(state).setdefault("next_logistics_id", 1))
    try:
        create_convoy(
            state,
            state.player_regime_id,
            source_region_id,
            target_region_id,
            good,
            min(before, round(amount, 2)),
            charge_authority=False,
            add_log=False,
        )
    except RuleError:
        return 0.0
    if (
        state.flags.get("v12_jiankang_auto_convoy")
        and good == "food"
        and int(target_region_id) == _capital_region_id(state, state.player_regime_id)
    ):
        created = next(
            (unit for unit in economy_data(state).get("logistics_units", []) if int(unit.get("id", 0)) == logistics_id),
            None,
        )
        if created is not None:
            created.setdefault("modifiers", []).append("jiankang_transfer_warehouse")
    after = float(region_economy(state, source_region_id)["warehouse"].get(good, 0.0))
    return round(max(0.0, before - after), 2)


def _local_policy_trade(state: GameState, region_id: int, good: str, action: str, amount: float) -> float:
    if not local_economic_actions_allowed(state):
        return 0.0
    if good == "food" and action == "buy":
        record = region_economy(state, region_id)
        local_surplus = max(
            0.0,
            float(record["market"].get("food", 0.0)) - market_demand(state, region_id, "food"),
        )
        price_safe_amount = market_purchase_room_at_price(state, region_id, "food", 1.0)
        amount = min(float(amount), local_surplus, price_safe_amount)
    if amount <= 0:
        return 0.0
    record = region_economy(state, region_id)
    before = float(record["warehouse"].get(good, 0.0))
    try:
        market_order(
            state,
            state.player_regime_id,
            region_id,
            good,
            action,
            round(amount, 2),
            charge_authority=False,
            add_log=False,
        )
    except RuleError:
        return 0.0
    after = float(record["warehouse"].get(good, 0.0))
    return round(abs(after - before), 2)


def _local_market_feedback(state: GameState, region_id: int) -> list[str]:
    """Sell real local reserves when a non-stopped region's market is undersupplied."""
    if not local_economic_actions_allowed(state):
        return []
    record = region_economy(state, region_id)
    warehouse = record["warehouse"]
    actions: list[str] = []
    for good in GOODS:
        demand = market_demand(state, region_id, good)
        shortage = max(0.0, demand - float(record["market"].get(good, 0.0)))
        if shortage <= 0.01:
            continue
        price = market_price(state, region_id, good)
        sellable = min(
            shortage,
            float(warehouse.get(good, 0.0)),
            _market_room(state, region_id, good),
        )
        if good == "food":
            sellable = min(sellable, market_food_trade_remaining(state, region_id, "sell"))
        sold = _local_policy_trade(state, region_id, good, "sell", sellable)
        if sold:
            actions.append(f"市场短缺，出售{GOOD_NAMES[good]}{format_resource(sold)}")
    return actions


def settle_local_policies(state: GameState) -> list[str]:
    """Execute player-selected local guidance once during monthly settlement."""
    if not local_economic_actions_allowed(state):
        return []
    regime_id = state.player_regime_id
    capital_region_id = _capital_region_id(state, regime_id)
    reports: list[str] = []
    for region_id, region in sorted(state.regions.items()):
        if int(region.get("controller", 0)) != regime_id:
            continue
        record = region_economy(state, int(region_id))
        warehouse = record["warehouse"]
        mode = str(record.get("local_policy", "stockpile"))
        actions: list[str] = []

        if mode == "stop":
            continue
        actions.extend(_local_market_feedback(state, int(region_id)))
        if mode == "stockpile":
            capacity = warehouse_resource_capacity(state, int(region_id), "food")
            if float(warehouse.get("food", 0.0)) >= capacity - 0.01:
                shipped = _local_policy_convoy(state, int(region_id), capital_region_id, "food", 20.0)
                if shipped:
                    actions.append(f"向首都发粮{format_resource(shipped)}")
            price = market_price(state, int(region_id), "food")
            demand = market_demand(state, int(region_id), "food")
            desired_food = min(
                max(0.0, float(record["market"].get("food", 0.0)) - demand),
                warehouse_room(state, int(region_id), "food"),
                market_food_trade_remaining(state, int(region_id), "buy"),
                market_purchase_room_at_price(state, int(region_id), "food", 1.0),
            )
            from ...rules.treasury import treasury_balance

            purchase_factor = local_purchase_cost_multiplier(state, int(region_id), regime_id)
            affordable_food = treasury_balance(state, regime_id) / (price * purchase_factor)
            if price < 1.0 and desired_food > affordable_food + 0.01:
                # Sell only enough cloth to finance grain that can actually be
                # bought and stored; stockpiling regions keep no fixed cloth floor.
                cloth_surplus = max(0.0, float(warehouse.get("cloth", 0.0)))
                cloth_price = market_price(state, int(region_id), "cloth")
                cash_shortfall = max(0.0, (desired_food - affordable_food) * price)
                cloth_to_sell = min(
                    cloth_surplus,
                    cash_shortfall / cloth_price,
                    _market_room(state, int(region_id), "cloth"),
                )
                copper_before = treasury_balance(state, regime_id)
                sold = _local_policy_trade(state, int(region_id), "cloth", "sell", cloth_to_sell)
                copper_earned = round(treasury_balance(state, regime_id) - copper_before, 2)
                if sold:
                    actions.append(
                        f"出售布匹{format_resource(sold)}换得铜钱{format_resource(copper_earned)}"
                    )
            purchasable = min(
                max(0.0, float(record["market"].get("food", 0.0)) - demand),
                treasury_balance(state, regime_id) / (price * purchase_factor),
                warehouse_room(state, int(region_id), "food"),
                market_food_trade_remaining(state, int(region_id), "buy"),
            )
            if price < 1.0 and purchasable > 0:
                bought = _local_policy_trade(state, int(region_id), "food", "buy", purchasable)
                if bought:
                    actions.append(f"低价购粮{format_resource(bought)}")

        elif mode == "tax":
            for good in ("food", "cloth"):
                sellable = min(
                    float(warehouse.get(good, 0.0)),
                    _market_room(state, int(region_id), good),
                )
                if good == "food":
                    sellable = min(sellable, market_food_trade_remaining(state, int(region_id), "sell"))
                sold = _local_policy_trade(state, int(region_id), good, "sell", sellable)
                if sold:
                    actions.append(f"出售{GOOD_NAMES[good]}{format_resource(sold)}")

        elif mode == "transfer":
            if float(record["market"].get("food", 0.0)) >= market_demand(state, int(region_id), "food"):
                for good in ("food", "cloth"):
                    amount = max(0.0, float(warehouse.get(good, 0.0)) - 20.0)
                    shipped = _local_policy_convoy(state, int(region_id), capital_region_id, good, amount)
                    if shipped:
                        actions.append(f"向首都转运{GOOD_NAMES[good]}{format_resource(shipped)}")

        if actions:
            report = f"{region['name']}按“{LOCAL_POLICY_NAMES.get(mode, '屯粮')}”方针：" + "；".join(actions) + "。"
            reports.append(report)
            state.add_log(report)
    return reports


def settle_capital_expenses(state: GameState) -> None:
    """Pay cash expenses; official salaries fall due only in January and July."""
    from ...rules.economy import expenses_due_this_month
    from ...rules.treasury import change_treasury, treasury_balance

    for regime_id, regime in state.regimes.items():
        if not regime.get("regions"):
            continue
        official_salary, military_pay = expenses_due_this_month(state, int(regime_id))
        due = float(official_salary + military_pay)
        if due <= 0:
            continue
        available = treasury_balance(state, int(regime_id))
        paid = min(available, due)
        if paid:
            change_treasury(state, int(regime_id), -paid)
        arrears = round(max(0.0, due - paid), 2)
        if arrears > 0:
            regime["stability"] = int(clamp(int(regime.get("stability", 0)) - 3, 0, 100))
            regime["war_support"] = int(clamp(int(regime.get("war_support", 0)) - 3, 0, 100))
            state.add_log(
                f"{regime.get('name', regime_id)}国库出现{arrears:g}铜钱赤字，"
                "中央稳定度-3、战争支持度-3。"
            )
        if int(regime_id) == state.player_regime_id:
            salary_label = "正月官俸" if int(state.month) == 1 else "七月官俸"
            message = f"月末现金开支：从国库支付{salary_label}{paid:g}铜钱。"
            if arrears > 0:
                message += f"尚欠官俸{arrears:g}铜钱。"
            state.add_log(message)


def settle_month(state: GameState, rng: random.Random | None = None) -> None:
    rng = rng or random.Random(state.turn_number * 104729)
    settle_local_governance(state, rng)
    if str(state.flags.get("rules_version", "")) == "1.3":
        from ..v1_3.culture import settle_culture

        settle_culture(state)
    settle_peacetime_stability(state)
    settle_army_supply(state)
    settle_local_policies(state)
    settle_logistics(state, rng)
    from .supply_units import settle_supply_units

    settle_supply_units(state)
    settle_migration(state, rng)
    if local_economic_actions_allowed(state) and state.flags.get("v12_strategy_effect:14"):
        for region_id, region in state.regions.items():
            if int(region.get("controller", 0)) != state.player_regime_id:
                continue
            record = region_economy(state, int(region_id))
            demand = market_demand(state, int(region_id), "food")
            gap = max(0.0, demand - float(record["market"].get("food", 0.0)))
            amount = min(gap, float(record["warehouse"].get("food", 0.0)), _market_room(state, int(region_id), "food"))
            if amount > 0:
                record["warehouse"]["food"] = round(float(record["warehouse"]["food"]) - amount, 2)
                record["market"]["food"] = round(float(record["market"]["food"]) + amount, 2)
    if state.month == 1:
        january_market_cleanup(state)
    if state.month == 7:
        annual_production(state, rng)
    elif state.month == 8:
        generate_merchants(state, rng)
    elif state.month == 12:
        annual_consumption(state, rng)
        settle_december_warehouse_food(state)
    for region_id in state.regions:
        enforce_market_capacity(state, int(region_id))
        enforce_warehouse_capacity(state, int(region_id))
    settle_capital_expenses(state)
    from ...rules.ai_modifiers import recover_ai_war_support

    recover_ai_war_support(state)
    from ...rules.diplomacy import settle_forced_surrenders

    settle_forced_surrenders(state)
    if str(state.flags.get("rules_version", "")) == "1.3":
        for region_id in state.regions:
            record = region_economy(state, int(region_id))
            if "culture_stability_cap" in record:
                record["stability"] = min(int(record.get("stability", 0)), int(record["culture_stability_cap"]))
                state.regions[int(region_id)]["local_stability"] = int(record["stability"])
