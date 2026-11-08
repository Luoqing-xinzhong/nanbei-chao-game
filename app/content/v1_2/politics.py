from __future__ import annotations

import random

from ...models import GameState
from ...rules.common import RuleError, check_player_office_authority, clamp, once_per_turn, spend_authority
from ...rules.laws import check_command_rejection
from ...rules.politics import command_copper_cost
from ...rules.treasury import spend_treasury, treasury_balance
from .economy import economy_data, region_economy


RELIEF_COPPER_COST = command_copper_cost(300)
DEVELOP_COPPER_COST = command_copper_cost(300)
# 1.2新增的垦荒铜钱成本不继承旧版固定政令折扣。
RECLAIM_COPPER_COST = 500


def _owned_controlled_region(state: GameState, region_id: int) -> dict:
    region = state.regions.get(int(region_id))
    if (
        not region
        or region.get("name") not in state.player_regime.get("regions", [])
        or int(region.get("controller", 0)) != state.player_regime_id
    ):
        raise RuleError("只能对本国实际控制的地区发布政令")
    return region


def temporary_tax(state: GameState) -> str:
    from .economy import warehouse_room

    check_command_rejection(state, "temporary_tax")
    once_per_turn(state, "temporary_tax")
    spend_authority(state, 100)
    totals = {"food": 0.0, "cloth": 0.0}
    for region_id, region in state.regions.items():
        if region.get("name") not in state.player_regime.get("regions", []) or int(region.get("controller", 0)) != state.player_regime_id:
            continue
        record = region_economy(state, int(region_id))
        for good in ("food", "cloth"):
            amount = round(float(record["market"].get(good, 0.0)) * 0.10 * float(record["control"]) / 100, 2)
            amount = min(amount, warehouse_room(state, int(region_id), good))
            record["market"][good] -= amount
            record["warehouse"][good] = round(float(record["warehouse"].get(good, 0.0)) + amount, 2)
            totals[good] += amount
    state.player_regime["stability"] = int(clamp(int(state.player_regime.get("stability", 0)) - 5, 0, 100))
    message = f"临时征税从各州市场征收粮食{totals['food']:g}、布匹{totals['cloth']:g}入州库，国家稳定度-5。"
    state.add_log(message)
    return message


def relief(state: GameState, region_id: int) -> str:
    region = _owned_controlled_region(state, region_id)
    check_command_rejection(state, "relief")
    if treasury_balance(state) < RELIEF_COPPER_COST:
        raise RuleError(f"国库不足{RELIEF_COPPER_COST:g}")
    spend_authority(state, 100)
    spend_treasury(state, state.player_regime_id, RELIEF_COPPER_COST)
    state.player_regime["stability"] = int(clamp(int(state.player_regime.get("stability", 0)) + 3, 0, 100))
    record = region_economy(state, region_id)
    record["stability"] = int(clamp(int(record["stability"]) + 2, 0, 100))
    region["local_stability"] = record["stability"]
    message = f"赈济{region['name']}：国家稳定度+3，地方稳定度+2。"
    state.add_log(message)
    return message


def amnesty(state: GameState) -> str:
    check_command_rejection(state, "amnesty")
    once_per_turn(state, "amnesty")
    spend_authority(state, 100)
    state.player_regime["stability"] = int(clamp(int(state.player_regime.get("stability", 0)) - 3, 0, 100))
    bonuses = economy_data(state).setdefault("recruitment_bonus", {})
    key = str(state.player_regime_id)
    bonuses[key] = int(bonuses.get(key, 0)) + 1000
    message = "颁布大赦：人力征集额外+1000，国家稳定度-3。"
    state.add_log(message)
    return message


def develop(state: GameState, region_id: int) -> str:
    region = _owned_controlled_region(state, region_id)
    check_command_rejection(state, "develop")
    spend_treasury(state, state.player_regime_id, DEVELOP_COPPER_COST)
    record = region_economy(state, region_id)
    record["stability"] = int(clamp(int(record["stability"]) + 3, 0, 100))
    region["local_stability"] = record["stability"]
    message = f"兴修{region['name']}水利：地方稳定度+3。"
    state.add_log(message)
    return message


def reclaim_land(state: GameState, region_id: int, rng: random.Random | None = None) -> str:
    region = _owned_controlled_region(state, region_id)
    check_command_rejection(state, "reclaim_land", rng)
    if treasury_balance(state) < RECLAIM_COPPER_COST:
        raise RuleError(f"国库不足{RECLAIM_COPPER_COST:g}")
    spend_authority(state, 50)
    spend_treasury(state, state.player_regime_id, RECLAIM_COPPER_COST)
    land = region_economy(state, region_id)["land"]
    land["gentry"] += 5
    land["smallholder"] += 5
    land["self_farm"] += 5
    message = f"在{region['name']}垦荒：国库-{RECLAIM_COPPER_COST:g}、权威-50，门阀、小地主、自耕农土地各+5。"
    state.add_log(message)
    return message
