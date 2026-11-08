from __future__ import annotations

from typing import Any

from ...models import GameState
from ...rules.common import RuleError
from ...rules.treasury import treasury_balance
from .economy import (
    GOOD_NAMES,
    _region_capital,
    _route,
    army_supply_capacity,
    create_convoy,
    format_resource,
    market_food_trade_remaining,
    market_order,
    market_price,
    population_counts,
    population_units,
    region_economy,
    release_grain,
)


ADVICE_LIMIT = 12


def _owned_regions(state: GameState, regime_id: int) -> list[int]:
    return sorted(
        int(region_id)
        for region_id, region in state.regions.items()
        if int(region.get("controller", 0)) == regime_id
    )


def _army_supply_pressure(state: GameState, regime_id: int, region_id: int) -> float:
    return round(sum(
        max(0.0, army_supply_capacity(army) - float(army.supply_food))
        for army in state.armies.values()
        if army.regime_id == regime_id
        and int(state.cities.get(army.location_id, {}).get("region_id", 0)) == region_id
    ), 2)


def _planned_amount(actual_amount: float, control: float) -> float:
    if control <= 0:
        return 0.0
    return round(max(0.0, actual_amount) * 100 / control, 2)


def _has_convoy_route(state: GameState, source: int, target: int) -> bool:
    return bool(_route(state, _region_capital(state, source), _region_capital(state, target)))


def _recommendation(
    kind: str,
    title: str,
    reason: str,
    params: dict[str, Any],
    priority: float,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "reason": reason,
        "params": params,
        "priority": round(float(priority), 2),
        "authority_cost": 10,
    }


def economic_advice(
    state: GameState,
    regime_id: int | None = None,
    limit: int = ADVICE_LIMIT,
) -> list[dict[str, Any]]:
    """Recommend executable orders from national stocks, shortages and army supply pressure."""
    regime_id = int(state.player_regime_id if regime_id is None else regime_id)
    region_ids = _owned_regions(state, regime_id)
    if not region_ids:
        return []
    details: dict[int, dict[str, float]] = {}
    for region_id in region_ids:
        record = region_economy(state, region_id)
        occupations, _cultures = population_counts(state, region_id)
        population = len(population_units(state, region_id))
        army_pressure = _army_supply_pressure(state, regime_id, region_id)
        food_market = float(record["market"].get("food", 0.0))
        food_warehouse = float(record["warehouse"].get("food", 0.0))
        cloth_market = float(record["market"].get("cloth", 0.0))
        cloth_warehouse = float(record["warehouse"].get("cloth", 0.0))
        cloth_demand = max(1.0, float(occupations["artisan"]) * 2)
        details[region_id] = {
            "control": float(record.get("control", 0.0)),
            "population": float(population),
            "civilian_food_gap": max(0.0, population - food_market),
            "army_food_gap": army_pressure,
            "warehouse_food": food_warehouse,
            "market_food": food_market,
            "warehouse_cloth": cloth_warehouse,
            "market_cloth": cloth_market,
            "cloth_demand": cloth_demand,
            "warehouse_copper": treasury_balance(state, regime_id),
        }

    recommendations: list[dict[str, Any]] = []

    # 先救济居民；一地至多一条放粮建议，避免列表被同类命令淹没。
    release_targets = sorted(
        region_ids,
        key=lambda rid: (details[rid]["civilian_food_gap"], details[rid]["population"]),
        reverse=True,
    )
    for region_id in release_targets[:3]:
        item = details[region_id]
        actual = min(item["civilian_food_gap"], item["warehouse_food"])
        if actual <= 0 or item["control"] <= 0:
            continue
        region_name = state.regions[region_id]["name"]
        recommendations.append(_recommendation(
            "release",
            f"开仓放粮：{region_name} {format_resource(actual)}",
            f"当地市场距十二月民食需求尚缺{format_resource(item['civilian_food_gap'])}，州库可立即弥补{format_resource(actual)}。",
            {"regime_id": regime_id, "region_id": region_id, "amount": _planned_amount(actual, item["control"])},
            1000 + item["civilian_food_gap"],
        ))

    # 使用虚拟库存分配，避免多条建议重复调运同一批粮食。
    virtual_food = {
        rid: max(
            0.0,
            details[rid]["warehouse_food"]
            - min(details[rid]["civilian_food_gap"], details[rid]["warehouse_food"])
            - details[rid]["army_food_gap"]
            - max(2.0, details[rid]["population"] * 0.10),
        )
        for rid in region_ids
    }
    food_targets = sorted(
        region_ids,
        key=lambda rid: (
            max(0.0, details[rid]["civilian_food_gap"] - details[rid]["warehouse_food"])
            + max(0.0, details[rid]["army_food_gap"] - max(0.0, details[rid]["warehouse_food"] - details[rid]["civilian_food_gap"])),
            details[rid]["army_food_gap"],
        ),
        reverse=True,
    )
    convoy_count = 0
    for target in food_targets:
        item = details[target]
        unmet_civilian = max(0.0, item["civilian_food_gap"] - item["warehouse_food"])
        remaining_warehouse = max(0.0, item["warehouse_food"] - item["civilian_food_gap"])
        unmet_army = max(0.0, item["army_food_gap"] - remaining_warehouse)
        needed = unmet_civilian + unmet_army
        if needed <= 0:
            continue
        donors = sorted(region_ids, key=lambda rid: virtual_food[rid], reverse=True)
        source = next(
            (rid for rid in donors if rid != target and virtual_food[rid] > 1 and _has_convoy_route(state, rid, target)),
            None,
        )
        if source is None:
            continue
        actual = min(needed / 0.9, virtual_food[source])
        if actual <= 1:
            continue
        virtual_food[source] -= actual
        source_name = state.regions[source]["name"]
        target_name = state.regions[target]["name"]
        reasons = []
        if unmet_civilian:
            reasons.append(f"民食净缺口{format_resource(unmet_civilian)}")
        if unmet_army:
            reasons.append(f"驻军补给压力{format_resource(unmet_army)}")
        recommendations.append(_recommendation(
            "convoy",
            f"漕运粮食：{source_name} → {target_name} {format_resource(actual)}",
            "、".join(reasons) + "；已按在途10%损耗略增装运量。",
            {
                "regime_id": regime_id,
                "source_region_id": source,
                "target_region_id": target,
                "good": "food",
                "amount": _planned_amount(actual, details[source]["control"]),
            },
            800 + needed,
        ))
        convoy_count += 1
        if convoy_count >= 3:
            break

    # 布匹调往价格较高、市场供应偏少的地区，随后可在目的地出售。
    cloth_targets = sorted(
        region_ids,
        key=lambda rid: (market_price(state, rid, "cloth"), details[rid]["cloth_demand"] - details[rid]["market_cloth"]),
        reverse=True,
    )
    cloth_sources = sorted(
        region_ids,
        key=lambda rid: details[rid]["warehouse_cloth"] - max(2.0, details[rid]["cloth_demand"] * 0.25),
        reverse=True,
    )
    cloth_convoys = 0
    for target in cloth_targets:
        shortage = max(0.0, details[target]["cloth_demand"] - details[target]["market_cloth"])
        if shortage <= 1:
            continue
        source = next((
            rid for rid in cloth_sources
            if rid != target
            and details[rid]["warehouse_cloth"] > max(3.0, details[rid]["cloth_demand"] * 0.5)
            and _has_convoy_route(state, rid, target)
        ), None)
        if source is None:
            continue
        surplus = details[source]["warehouse_cloth"] - max(3.0, details[source]["cloth_demand"] * 0.5)
        actual = min(surplus, max(2.0, shortage / 0.9))
        recommendations.append(_recommendation(
            "convoy",
            f"漕运布匹：{state.regions[source]['name']} → {state.regions[target]['name']} {format_resource(actual)}",
            f"目的地布价{format_resource(market_price(state, target, 'cloth'))}且市场缺布{format_resource(shortage)}，调入后适合出售。",
            {
                "regime_id": regime_id, "source_region_id": source, "target_region_id": target,
                "good": "cloth", "amount": _planned_amount(actual, details[source]["control"]),
            },
            500 + market_price(state, target, "cloth") * 10,
        ))
        details[source]["warehouse_cloth"] -= actual
        cloth_convoys += 1
        if cloth_convoys >= 2:
            break

    # 市场交易：低价且有余货时买入，高价且州库有余货时出售。
    trade_options: list[dict[str, Any]] = []
    for region_id in region_ids:
        item = details[region_id]
        control = item["control"]
        if control <= 0:
            continue
        for good in ("food", "cloth"):
            price = market_price(state, region_id, good)
            warehouse_stock = item[f"warehouse_{good}"]
            market_stock = item[f"market_{good}"]
            demand = item["population"] if good == "food" else item["cloth_demand"]
            reserve = item["army_food_gap"] + max(2.0, demand * 0.10) if good == "food" else max(3.0, demand * 0.50)
            sellable = max(0.0, warehouse_stock - reserve)
            if good == "food" and item["civilian_food_gap"] > 0:
                sellable = 0.0
            if sellable > 1:
                actual = min(sellable, max(2.0, warehouse_stock * 0.20))
                if good == "food":
                    actual = min(actual, market_food_trade_remaining(state, region_id))
                if actual > 0:
                    trade_options.append(_recommendation(
                        "sell",
                        f"出售{GOOD_NAMES[good]}：{state.regions[region_id]['name']} {format_resource(actual)}",
                        f"州库扣除安全储备后仍有余量，当前价格{format_resource(price)}。",
                        {"regime_id": regime_id, "region_id": region_id, "good": good, "action": "sell", "amount": _planned_amount(actual, control)},
                        300 + price * 20,
                    ))

            market_surplus = max(0.0, market_stock - demand * 1.20)
            affordable = item["warehouse_copper"] / price if price > 0 else 0.0
            buyable = min(market_surplus, affordable)
            if good == "food":
                buyable = min(buyable, market_food_trade_remaining(state, region_id))
            if buyable > 1 and price <= 1.0:
                actual = min(buyable, max(2.0, market_surplus * 0.50))
                trade_options.append(_recommendation(
                    "buy",
                    f"购买{GOOD_NAMES[good]}：{state.regions[region_id]['name']} {format_resource(actual)}",
                    f"当地市场供应超过需求且价格仅{format_resource(price)}，适合转入州库。",
                    {"regime_id": regime_id, "region_id": region_id, "good": good, "action": "buy", "amount": _planned_amount(actual, control)},
                    250 + (1.0 - price) * 20,
                ))
    recommendations.extend(sorted(trade_options, key=lambda item: float(item["priority"]), reverse=True)[:4])

    recommendations.sort(key=lambda item: (-float(item["priority"]), str(item["title"])))
    return recommendations[: max(1, int(limit))]


def execute_economic_advice(state: GameState, advice: dict[str, Any]) -> str:
    """Execute one currently displayed recommendation through normal rule functions."""
    params = dict(advice.get("params", {}))
    regime_id = int(params.pop("regime_id", state.player_regime_id))
    if regime_id != state.player_regime_id:
        raise RuleError("顾问面板只能执行玩家政权的命令")
    kind = str(advice.get("kind", ""))
    if kind == "release":
        return release_grain(state, regime_id, **params)
    if kind == "convoy":
        return create_convoy(state, regime_id, **params)
    if kind in {"buy", "sell"}:
        return market_order(state, regime_id, **params)
    raise RuleError("这条顾问建议已经失效")
