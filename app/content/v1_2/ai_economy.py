from __future__ import annotations

import math
from typing import Any

from ...models import GameState
from ...rules.common import RuleError, clamp, is_regime_eliminated
from ...rules.military import army_support_priority, create_army, is_army_surrounded, reinforce_army, reinforcement_need
from ...rules.ai_modifiers import ai_difficulty_resource_multiplier, ai_difficulty_supply_multiplier
from ...rules.military import effective_road_type
from ...rules.treasury import capital_region_id, spend_treasury, treasury_balance
from .economy import (
    ORDER_AUTHORITY_COST,
    WEI_STANDING_FORCE_TARGET,
    ai_standing_force_target,
    army_supply_capacity,
    create_convoy,
    economy_data,
    market_food_trade_remaining,
    market_order,
    market_price,
    month_index,
    population_units,
    recruitment_available,
    region_economy,
    release_grain,
)


PLAN_CYCLE_MONTHS = 4
CAPITAL_COPPER_TARGET = 100.0
DEVELOPMENT_COST = 300.0
DEVELOPMENT_STABILITY_GAIN = 3
WEI_REGIME_ID = 2
WEI_STANDING_FORCE_FLOOR = 150_000
DEPOT_RESERVE_MONTHS = 2


def ai_economic_plan(state: GameState, regime_id: int) -> dict[str, Any] | None:
    """Return the saved four-month plan for an AI regime, if one exists."""
    plans = economy_data(state).setdefault("ai_economic_plans", {})
    plan = plans.get(str(int(regime_id)))
    return plan if isinstance(plan, dict) else None


def _controlled_regions(state: GameState, regime_id: int) -> list[int]:
    return sorted(
        int(region_id)
        for region_id, region in state.regions.items()
        if int(region.get("controller", 0)) == regime_id
    )


def _convoy_eta_months(state: GameState, unit: dict[str, Any]) -> int:
    """Estimate settlement ticks until a convoy arrives from its actual route position."""
    path = [int(city_id) for city_id in unit.get("path", [])]
    index = max(0, int(unit.get("path_index", 0)))
    if not path or index >= len(path) - 1:
        return 0
    road_costs: dict[tuple[int, int], float] = {}
    for road in state.roads:
        edge = (min(int(road["from"]), int(road["to"])), max(int(road["from"]), int(road["to"])))
        cost = {1: 1.0, 2: 1.0, 3: 0.3, 4: 0.5}.get(effective_road_type(state, road), 1.0)
        road_costs[edge] = min(cost, road_costs.get(edge, cost))
    remaining = -max(0.0, float(unit.get("movement_progress", 0.0)))
    for left, right in zip(path[index:], path[index + 1:]):
        edge = (min(left, right), max(left, right))
        remaining += road_costs.get(edge, 1.0)
    return max(0, int(math.ceil(max(0.0, remaining) - 1e-9)))


def _incoming_amount(
    state: GameState,
    regime_id: int,
    region_id: int,
    good: str,
    *,
    max_eta_months: int | None = None,
) -> float:
    return round(sum(
        float(unit.get("amount", 0.0)) * 0.9
        for unit in economy_data(state).get("logistics_units", [])
        if unit.get("kind") == "official"
        and int(unit.get("regime_id", 0)) == regime_id
        and int(unit.get("target_region_id", 0)) == region_id
        and str(unit.get("good")) == good
        and (max_eta_months is None or _convoy_eta_months(state, unit) <= max_eta_months)
    ), 2)


def _military_threat(state: GameState, regime_id: int) -> int:
    enemies = {
        int(side)
        for pair in state.wars
        if regime_id in {int(item) for item in pair}
        for side in pair
        if int(side) != regime_id and not is_regime_eliminated(state, int(side))
    }
    return sum(
        army.soldiers for army in state.armies.values()
        if army.regime_id in enemies
    )


def _regional_army_supply(state: GameState, regime_id: int, region_id: int) -> dict[str, float]:
    """Return the carried-food deficit of armies currently stationed in a region."""
    armies = [
        army for army in state.armies.values()
        if army.regime_id == regime_id
        and army.soldiers > 0
        and int(state.cities.get(army.location_id, {}).get("region_id", 0)) == region_id
    ]
    capacity = round(sum(army_supply_capacity(army) for army in armies), 2)
    carried = round(sum(min(float(army.supply_food), army_supply_capacity(army)) for army in armies), 2)
    refill_need = round(max(0.0, capacity - carried), 2)
    supply_multiplier = ai_difficulty_supply_multiplier(state, regime_id)
    return {
        "army_count": float(len(armies)),
        "capacity": capacity,
        "carried": carried,
        "refill_need": refill_need,
        # 军队自身已经携带六个月粮，州库只需另存两个月周转粮。
        # 旧规则再囤六个月，会令经济AI永久忙于补粮而无法扩军。
        "required_local": round(refill_need + capacity * DEPOT_RESERVE_MONTHS / 6 * supply_multiplier, 2),
    }


def _military_supply_emergency(
    state: GameState,
    regime_id: int,
    *,
    critical_only: bool = False,
) -> dict[str, Any] | None:
    """Find the worst friendly-controlled garrison shortage, including occupied land."""
    targets: list[tuple[float, int, int]] = []
    for region_id, region in state.regions.items():
        if int(region.get("controller", 0)) != regime_id:
            continue
        supply = _regional_army_supply(state, regime_id, int(region_id))
        if supply["army_count"] <= 0:
            continue
        local_food = float(region_economy(state, int(region_id))["warehouse"].get("food", 0.0))
        armies = [
            army for army in state.armies.values()
            if army.regime_id == regime_id
            and army.soldiers > 0
            and int(state.cities.get(army.location_id, {}).get("region_id", 0)) == int(region_id)
        ]
        from .economy import army_supply_months

        minimum_months = min((army_supply_months(army, state) for army in armies), default=0.0)
        urgent_window = max(0, int(math.floor(minimum_months)))
        timely_incoming = _incoming_amount(
            state, regime_id, int(region_id), "food", max_eta_months=urgent_window
        )
        incoming = _incoming_amount(state, regime_id, int(region_id), "food")
        if critical_only and supply["carried"] + local_food + timely_incoming >= supply["capacity"] / 3:
            continue
        effective_incoming = timely_incoming if critical_only else incoming
        gap = round(max(0.0, supply["required_local"] - local_food - effective_incoming), 2)
        if gap > 0.01:
            targets.append((gap, int(supply["army_count"]), int(region_id)))
    if not targets:
        return None
    gap, army_count, region_id = max(targets, key=lambda item: (item[0], item[1], -item[2]))
    return {
        "kind": "military_supply",
        "target_region_id": region_id,
        "target_amount": gap,
        "reason": f"当地{army_count}支驻军补满六个月随军粮尚缺{gap:g}",
        "emergency": True,
    }


def national_resource_snapshot(state: GameState, regime_id: int) -> dict[str, Any]:
    """Build the compact national snapshot used only when a new plan is chosen."""
    region_ids = _controlled_regions(state, regime_id)
    regions: list[dict[str, Any]] = []
    for region_id in region_ids:
        record = region_economy(state, region_id)
        population = len(population_units(state, region_id))
        army_supply = _regional_army_supply(state, regime_id, region_id)
        incoming_food = _incoming_amount(state, regime_id, region_id, "food")
        warehouse_food = round(float(record["warehouse"].get("food", 0.0)), 2)
        regions.append({
            "region_id": region_id,
            "population": population,
            "stability": int(record.get("stability", 0)),
            "market_food": round(float(record["market"].get("food", 0.0)), 2),
            "warehouse_food": warehouse_food,
            "warehouse_cloth": round(float(record["warehouse"].get("cloth", 0.0)), 2),
            "warehouse_copper": 0.0,
            "incoming_food": incoming_food,
            "army_count": int(army_supply["army_count"]),
            "army_supply_capacity": army_supply["capacity"],
            "army_supply_carried": army_supply["carried"],
            "army_refill_need": army_supply["refill_need"],
            "army_required_local": army_supply["required_local"],
            "army_supply_gap": round(max(0.0, army_supply["required_local"] - warehouse_food - incoming_food), 2),
        })
    own_soldiers = sum(army.soldiers for army in state.armies.values() if army.regime_id == regime_id)
    threat_soldiers = _military_threat(state, regime_id)
    return {
        "region_ids": region_ids,
        "regions": regions,
        "population": sum(int(item["population"]) for item in regions),
        "food": round(sum(float(item["market_food"]) + float(item["warehouse_food"]) for item in regions), 2),
        "cloth": round(sum(float(item["warehouse_cloth"]) for item in regions), 2),
        "copper": treasury_balance(state, regime_id),
        "capital_copper": treasury_balance(state, regime_id),
        "own_soldiers": own_soldiers,
        "threat_soldiers": threat_soldiers,
    }


def _goal_from_snapshot(state: GameState, regime_id: int, snapshot: dict[str, Any]) -> dict[str, Any]:
    regions = list(snapshot["regions"])
    if not regions:
        return {"kind": "idle", "reason": "没有实际控制的地区"}

    # 军队随军粮无法从市场直接补充。只要本地州库与在途粮不足以补满驻军，
    # 立即建立军粮调运目标，并允许它打断普通的四个月经济规划。
    standing_target = ai_standing_force_target(state, regime_id)
    standing_floor = (
        WEI_STANDING_FORCE_FLOOR
        if regime_id == WEI_REGIME_ID
        else int(math.ceil(standing_target * 0.75 / 1000)) * 1000
    )
    supply_targets = [item for item in regions if float(item["army_supply_gap"]) > 0.01]
    if supply_targets:
        target = max(
            supply_targets,
            key=lambda item: (float(item["army_supply_gap"]), int(item["army_count"]), -int(item["region_id"])),
        )
        return {
            "kind": "military_supply",
            "target_region_id": int(target["region_id"]),
            "target_amount": float(target["army_supply_gap"]),
            "reason": (
                f"当地{int(target['army_count'])}支驻军补满六个月随军粮尚缺"
                f"{float(target['army_supply_gap']):g}"
            ),
            "emergency": True,
        }

    reserve_request = state.flags.get("v12_ai_mobile_reserve_shortage", {}).get(str(int(regime_id)), {})
    reserve_shortage = (
        max(0, int(reserve_request.get("soldiers", 0)))
        if month_index(state) - int(reserve_request.get("month", -10_000)) <= 1
        else 0
    )
    if reserve_shortage >= 2_000:
        return {
            "kind": "military_expansion",
            "target_amount": reserve_shortage,
            "reason": f"当前战区任务编组尚缺可机动有效兵力{reserve_shortage}人",
            "strategic_reserve": True,
            "reserve_emergency": True,
        }

    if standing_target and int(snapshot["own_soldiers"]) < standing_floor:
        return {
            "kind": "military_expansion",
            "target_amount": standing_target - int(snapshot["own_soldiers"]),
            "reason": (
                f"常备军仅{snapshot['own_soldiers']}，"
                f"低于国家规模所需下限，向{standing_target}人整补"
            ),
            "strategic_reserve": True,
        }

    # 民食是硬优先级。州库粮也必须先投到市场，十二月才能被居民消费。
    food_targets = [
        (
            max(0.0, float(item["population"]) - float(item["market_food"])),
            max(
                0.0,
                float(item["population"])
                - float(item["market_food"])
                - max(0.0, float(item["warehouse_food"]) - float(item["army_required_local"]))
                - float(item["incoming_food"]),
            ),
            item,
        )
        for item in regions
        if float(item["market_food"]) + 1e-9 < float(item["population"])
    ]
    if food_targets:
        market_gap, uncovered_gap, target = max(
            food_targets,
            key=lambda item: (item[1] > 0, item[1], item[0], -int(item[2]["region_id"])),
        )
        return {
            "kind": "food_security",
            "target_region_id": int(target["region_id"]),
            "target_amount": round(market_gap, 2),
            "reason": f"目标州市场缺粮{market_gap:g}，全国调配后仍可能缺粮{uncovered_gap:g}",
        }

    if float(snapshot["capital_copper"]) + 1e-9 < CAPITAL_COPPER_TARGET:
        return {
            "kind": "capital_reserve",
            "target_region_id": capital_region_id(state, regime_id),
            "target_amount": CAPITAL_COPPER_TARGET,
            "reason": f"首都州库铜钱不足{CAPITAL_COPPER_TARGET:g}",
        }

    lowest = min(regions, key=lambda item: (int(item["stability"]), int(item["region_id"])))
    development_score = max(0.0, (90 - int(lowest["stability"])) / 90)
    desired_soldiers = max(
        3_000,
        len(regions) * 1_000,
        int(math.ceil(int(snapshot["threat_soldiers"]) * 1.10 / 1000)) * 1000,
        standing_target,
    )
    force_gap = max(0, desired_soldiers - int(snapshot["own_soldiers"]))
    expansion_score = force_gap / max(1, desired_soldiers)
    if regime_id == WEI_REGIME_ID and int(snapshot["own_soldiers"]) < WEI_STANDING_FORCE_FLOOR:
        return {
            "kind": "military_expansion",
            "target_amount": force_gap,
            "reason": (
                f"魏国常备军仅{snapshot['own_soldiers']}，"
                f"低于六位数下限，向{WEI_STANDING_FORCE_TARGET}人整补"
            ),
            "strategic_reserve": True,
        }
    if force_gap > 0 and expansion_score > development_score:
        return {
            "kind": "military_expansion",
            "target_amount": force_gap,
            "reason": f"现有兵力{snapshot['own_soldiers']}，按疆域与敌情需要{desired_soldiers}",
        }
    if int(lowest["stability"]) < 90:
        return {
            "kind": "regional_development",
            "target_region_id": int(lowest["region_id"]),
            "target_amount": 90,
            "reason": f"{state.regions[int(lowest['region_id'])]['name']}地方稳定度仅{lowest['stability']}",
        }

    # 没有迫切问题时，只对储备最薄弱的一州做均衡调配；无明显差距则休整。
    richest = max(regions, key=lambda item: (float(item["warehouse_food"]), -int(item["region_id"])))
    poorest = min(regions, key=lambda item: (float(item["warehouse_food"]), int(item["region_id"])))
    difference = float(richest["warehouse_food"]) - float(poorest["warehouse_food"])
    if difference >= 5:
        return {
            "kind": "balance_food",
            "source_region_id": int(richest["region_id"]),
            "target_region_id": int(poorest["region_id"]),
            "target_amount": round(difference / 2, 2),
            "reason": "各州粮食储备差距过大",
        }
    return {"kind": "idle", "reason": "全国没有迫切的经济缺口"}


def choose_ai_economic_goal(state: GameState, regime_id: int) -> dict[str, Any]:
    """Choose exactly one goal and keep it unchanged for the next four months."""
    now = month_index(state)
    snapshot = national_resource_snapshot(state, regime_id)
    plan = _military_supply_emergency(state, regime_id, critical_only=True) or _goal_from_snapshot(
        state, regime_id, snapshot
    )
    plan.update({
        "regime_id": int(regime_id),
        "created_month": now,
        "review_month": now + (1 if plan.get("emergency") else PLAN_CYCLE_MONTHS),
        "last_action_month": None,
        "actions_taken": 0,
        "status": "active" if plan["kind"] != "idle" else "idle",
        "snapshot": {
            key: snapshot[key]
            for key in ("population", "food", "cloth", "copper", "capital_copper", "own_soldiers", "threat_soldiers")
        },
    })
    economy_data(state).setdefault("ai_economic_plans", {})[str(int(regime_id))] = plan
    return plan


def ensure_ai_economic_goal(state: GameState, regime_id: int) -> dict[str, Any]:
    plan = ai_economic_plan(state, regime_id)
    if plan is None or month_index(state) >= int(plan.get("review_month", -1)):
        return choose_ai_economic_goal(state, regime_id)
    if plan.get("kind") != "military_supply":
        if _military_supply_emergency(state, regime_id, critical_only=True) is not None:
            return choose_ai_economic_goal(state, regime_id)
    reserve_request = state.flags.get("v12_ai_mobile_reserve_shortage", {}).get(str(int(regime_id)), {})
    reserve_shortage = max(0, int(reserve_request.get("soldiers", 0)))
    request_is_current = month_index(state) - int(reserve_request.get("month", -10_000)) <= 1
    if (
        request_is_current
        and reserve_shortage >= 2_000
        and plan.get("kind") not in {"military_supply", "military_expansion"}
    ):
        return choose_ai_economic_goal(state, regime_id)
    return plan


def _target_still_controlled(state: GameState, regime_id: int, region_id: int | None) -> bool:
    return bool(
        region_id in state.regions
        and int(state.regions[int(region_id)].get("controller", 0)) == regime_id
        and state.regions[int(region_id)].get("name") in state.regimes[regime_id].get("regions", [])
    )


def _convoy_to_target(
    state: GameState,
    regime_id: int,
    target_region_id: int,
    good: str,
    needed: float,
    *,
    protected_amount: float = 0.0,
    protect_civilian_food: bool = True,
) -> str | None:
    candidates: list[tuple[float, int]] = []
    for region_id in _controlled_regions(state, regime_id):
        if region_id == target_region_id:
            continue
        stock = float(region_economy(state, region_id)["warehouse"].get(good, 0.0))
        reserve = protected_amount
        if good == "food":
            army_need = _regional_army_supply(state, regime_id, region_id)["required_local"]
            record = region_economy(state, region_id)
            civilian_gap = (
                max(
                    0.0,
                    float(len(population_units(state, region_id))) - float(record["market"].get("food", 0.0)),
                )
                if protect_civilian_food
                else 0.0
            )
            reserve = max(reserve, civilian_gap) + army_need
        available = stock - reserve
        if available > 1:
            candidates.append((available, region_id))
    for available, source_region_id in sorted(candidates, reverse=True):
        try:
            # 官漕每次结算损失10%，因此略多装运以接近目标到货量。
            return create_convoy(
                state,
                regime_id,
                source_region_id,
                target_region_id,
                good,
                min(available, max(1.0, needed / 0.9)),
            )
        except RuleError:
            continue
    return None


def _fund_capital(state: GameState, regime_id: int, needed: float) -> str | None:
    # 铜钱是全局国库量；缺钱时直接在任一受控地区出售非民生物资筹款。
    candidates = sorted(
        _controlled_regions(state, regime_id),
        key=lambda region_id: float(region_economy(state, region_id)["warehouse"].get("cloth", 0.0)),
        reverse=True,
    )
    for region_id in candidates:
        cloth = float(region_economy(state, region_id)["warehouse"].get("cloth", 0.0))
        if cloth <= 1:
            continue
        try:
            return market_order(state, regime_id, region_id, "cloth", "sell", min(cloth, max(1.0, needed)))
        except RuleError:
            continue
    return None


def _execute_food_goal(state: GameState, regime_id: int, plan: dict[str, Any]) -> str | None:
    target = int(plan.get("target_region_id", 0))
    if not _target_still_controlled(state, regime_id, target):
        plan["status"] = "blocked"
        return None
    record = region_economy(state, target)
    gap = max(0.0, float(len(population_units(state, target))) - float(record["market"].get("food", 0.0)))
    if gap <= 0:
        plan["status"] = "completed"
        return None
    military_reserve = _regional_army_supply(state, regime_id, target)["required_local"]
    local_food = max(0.0, float(record["warehouse"].get("food", 0.0)) - military_reserve)
    if local_food > 0.01:
        try:
            return release_grain(state, regime_id, target, min(gap, local_food))
        except RuleError:
            pass
    if _incoming_amount(state, regime_id, target, "food") > 0:
        return None
    return _convoy_to_target(state, regime_id, target, "food", gap)


def _execute_military_supply_goal(state: GameState, regime_id: int, plan: dict[str, Any]) -> str | None:
    target = int(plan.get("target_region_id", 0))
    if target not in state.regions or int(state.regions[target].get("controller", 0)) != regime_id:
        plan["status"] = "blocked"
        return None
    required_local = _regional_army_supply(state, regime_id, target)["required_local"]
    local_food = float(region_economy(state, target)["warehouse"].get("food", 0.0))
    armies = [
        army for army in state.armies.values()
        if army.regime_id == regime_id
        and army.soldiers > 0
        and int(state.cities.get(army.location_id, {}).get("region_id", 0)) == target
    ]
    from .economy import army_supply_months

    minimum_months = min((army_supply_months(army, state) for army in armies), default=0.0)
    incoming = _incoming_amount(
        state,
        regime_id,
        target,
        "food",
        max_eta_months=max(0, int(math.floor(minimum_months))),
    )
    gap = max(0.0, required_local - local_food - incoming)
    if gap <= 0.01:
        plan["status"] = "completed"
        return None
    convoy = _convoy_to_target(
        state,
        regime_id,
        target,
        "food",
        gap,
        protect_civilian_food=False,
    )
    if convoy is not None:
        return convoy

    # 全国州库都没有可调余粮时，先在有铜钱的本国州购买市场粮；
    # 下个月继续沿用紧急目标，把新购粮食运往驻军地区。
    candidates = sorted(
        _controlled_regions(state, regime_id),
        key=lambda region_id: (
            float(region_economy(state, region_id)["market"].get("food", 0.0)),
            treasury_balance(state, regime_id),
        ),
        reverse=True,
    )
    for region_id in candidates:
        record = region_economy(state, region_id)
        price = market_price(state, region_id, "food")
        amount = min(
            gap / 0.9,
            float(record["market"].get("food", 0.0)),
            treasury_balance(state, regime_id) / max(0.01, price),
            market_food_trade_remaining(state, region_id),
        )
        if amount <= 0.01:
            continue
        try:
            return market_order(state, regime_id, region_id, "food", "buy", amount)
        except RuleError:
            continue
    return None


def _execute_capital_goal(state: GameState, regime_id: int, plan: dict[str, Any]) -> str | None:
    gap = max(0.0, float(plan.get("target_amount", CAPITAL_COPPER_TARGET)) - treasury_balance(state, regime_id))
    if gap <= 0:
        plan["status"] = "completed"
        return None
    return _fund_capital(state, regime_id, gap)


def _execute_development_goal(state: GameState, regime_id: int, plan: dict[str, Any]) -> str | None:
    target = int(plan.get("target_region_id", 0))
    if not _target_still_controlled(state, regime_id, target):
        plan["status"] = "blocked"
        return None
    record = region_economy(state, target)
    desired = int(plan.get("target_amount", 90))
    if int(record.get("stability", 0)) >= desired:
        plan["status"] = "completed"
        return None
    if treasury_balance(state, regime_id) + 1e-9 < DEVELOPMENT_COST:
        return _fund_capital(state, regime_id, DEVELOPMENT_COST - treasury_balance(state, regime_id))
    spend_treasury(state, regime_id, DEVELOPMENT_COST)
    record["stability"] = int(clamp(int(record.get("stability", 0)) + DEVELOPMENT_STABILITY_GAIN, 0, 100))
    state.regions[target]["local_stability"] = record["stability"]
    return f"develop:{target}:{record['stability']}"


def _legacy_execute_expansion_goal(state: GameState, regime_id: int, plan: dict[str, Any]) -> str | None:
    gap = max(0, int(plan.get("target_amount", 0)))
    recruited = int(plan.get("recruited", 0))
    remaining = max(0, gap - recruited)
    if remaining <= 0:
        plan["status"] = "completed"
        return None
    available = recruitment_available(state, regime_id)
    battalions = min(9, available // 1000, int(math.ceil(remaining / 1000)))
    if battalions <= 0:
        return None
    # 扩军前保留各地一整年民食，并确认还能装满新军六个月随军粮。
    spare_food = 0.0
    for region_id in _controlled_regions(state, regime_id):
        supply = _regional_army_supply(state, regime_id, region_id)
        protected = supply["refill_need"]
        spare_food += max(
            0.0,
            float(region_economy(state, region_id)["warehouse"].get("food", 0.0)) - protected,
        )
    battalions = min(battalions, int(spare_food // 1.2))
    if battalions <= 0:
        return None
    try:
        army = create_army(
            state,
            regime_id,
            int(state.regimes[regime_id].get("capital") or 0),
            0,
            {1: battalions},
        )
    except (RuleError, ValueError):
        return None
    plan["recruited"] = recruited + battalions * 1000
    return f"expand:{army.id}:{battalions}"


def _execute_expansion_goal(state: GameState, regime_id: int, plan: dict[str, Any]) -> str | None:
    """Build toward the force target through paid, rate-limited recruitment."""
    gap = max(0, int(plan.get("target_amount", 0)))
    recruited = int(plan.get("recruited", 0))
    remaining = max(0, gap - recruited)
    if remaining <= 0:
        plan["status"] = "completed"
        return None

    multiplier = ai_difficulty_resource_multiplier(state)
    available = recruitment_available(state, regime_id)
    depleted = sorted(
        (
            (reinforcement_need(army), army)
            for army in state.armies.values()
            if army.regime_id == regime_id
            and army.soldiers > 0
            and reinforcement_need(army) > 0
            and not is_army_surrounded(state, army.id)
        ),
        key=lambda item: army_support_priority(state, item[1]),
    )
    for need, army in depleted:
        manpower_cost = max(1, int(math.ceil(need * multiplier)))
        if manpower_cost > available:
            continue
        try:
            reinforce_army(state, army.id, manpower_cost_multiplier=multiplier)
        except RuleError:
            continue
        plan["recruited"] = recruited + need
        return f"reinforce:{army.id}:{need}:manpower={manpower_cost}"

    recruitment_per_battalion = max(1, int(math.ceil(1000 * multiplier)))
    desired_battalions = min(9, available // recruitment_per_battalion, int(math.ceil(remaining / 1000)))
    if desired_battalions <= 0:
        plan["stage"] = "await_manpower"
        return None

    capital_region = capital_region_id(state, regime_id)
    if capital_region is None:
        plan["status"] = "blocked"
        return None
    capital_store = region_economy(state, capital_region)["warehouse"]
    food_per_battalion = 1.2 * multiplier
    capital_food = float(capital_store.get("food", 0.0))
    battalions = min(desired_battalions, int((capital_food + 1e-9) // food_per_battalion))
    if battalions <= 0:
        # Food must physically reach the capital before recruitment can proceed.
        incoming_food = _incoming_amount(state, regime_id, capital_region, "food")
        plan["stage"] = "await_capital_food" if incoming_food >= food_per_battalion else "fund_capital_food"
        if incoming_food >= food_per_battalion:
            return None
        action = _convoy_to_target(
            state,
            regime_id,
            capital_region,
            "food",
            max(
                food_per_battalion,
                desired_battalions * food_per_battalion - incoming_food,
            ),
            protect_civilian_food=True,
        )
        if action is None:
            plan.update(
                status="blocked",
                review_month=month_index(state) + 1,
                blocked_reason="首都缺少扩军粮食，且没有可用调运来源",
            )
        return action

    copper_cost = round(battalions * 3.0 * multiplier, 2)
    capital_copper = treasury_balance(state, regime_id)
    if capital_copper + 1e-9 < copper_cost:
        shortfall = max(0.0, copper_cost - capital_copper)
        plan["stage"] = "fund_capital_copper"
        action = _fund_capital(state, regime_id, shortfall)
        if action is None:
            plan.update(
                status="blocked",
                review_month=month_index(state) + 1,
                blocked_reason="首都缺少扩军铜钱，且没有可用调运或出售来源",
            )
        return action

    try:
        army = create_army(
            state,
            regime_id,
            int(state.regimes[regime_id].get("capital") or 0),
            0,
            {1: battalions},
            recruitment_cost_multiplier=multiplier,
        )
    except (RuleError, ValueError):
        return None

    food_cost = round(battalions * food_per_battalion, 2)
    capital_store["food"] = round(max(0.0, float(capital_store.get("food", 0.0)) - food_cost), 2)
    plan["recruited"] = recruited + battalions * 1000
    plan["stage"] = "recruiting"
    plan.pop("blocked_reason", None)
    return f"expand:{army.id}:{battalions}:food={food_cost:g}"


def _execute_balance_goal(state: GameState, regime_id: int, plan: dict[str, Any]) -> str | None:
    source = int(plan.get("source_region_id", 0))
    target = int(plan.get("target_region_id", 0))
    if not _target_still_controlled(state, regime_id, source) or not _target_still_controlled(state, regime_id, target):
        plan["status"] = "blocked"
        return None
    if _incoming_amount(state, regime_id, target, "food") > 0:
        return None
    amount = min(
        float(plan.get("target_amount", 0.0)),
        max(
            0.0,
            float(region_economy(state, source)["warehouse"].get("food", 0.0))
            - len(population_units(state, source))
            - _regional_army_supply(state, regime_id, source)["required_local"],
        ),
    )
    if amount <= 1:
        plan["status"] = "completed"
        return None
    try:
        return create_convoy(state, regime_id, source, target, "food", amount)
    except RuleError:
        return None


def run_ai_economic_plan(state: GameState, regime_id: int) -> list[str]:
    """Execute at most one monthly action in service of the saved four-month goal."""
    if regime_id == state.player_regime_id or is_regime_eliminated(state, regime_id):
        return []
    plan = ensure_ai_economic_goal(state, regime_id)
    if plan.get("kind") == "military_expansion":
        emergency = _military_supply_emergency(state, regime_id, critical_only=True)
        if emergency is not None:
            plan = choose_ai_economic_goal(state, regime_id)
    now = month_index(state)
    if plan.get("last_action_month") == now or plan.get("status") in {"idle", "blocked", "completed"}:
        return []
    if int(state.regimes[regime_id].get("authority", 0)) < ORDER_AUTHORITY_COST and plan.get("kind") not in {
        "regional_development",
        "military_expansion",
    }:
        return []

    handlers = {
        "military_supply": _execute_military_supply_goal,
        "food_security": _execute_food_goal,
        "capital_reserve": _execute_capital_goal,
        "regional_development": _execute_development_goal,
        "military_expansion": _execute_expansion_goal,
        "balance_food": _execute_balance_goal,
    }
    handler = handlers.get(str(plan.get("kind")))
    try:
        result = handler(state, regime_id, plan) if handler else None
    except RuleError:
        result = None
    if result is None:
        return []
    plan["last_action_month"] = now
    plan["actions_taken"] = int(plan.get("actions_taken", 0)) + 1
    return [result]
