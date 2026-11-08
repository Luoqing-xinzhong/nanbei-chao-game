from __future__ import annotations

from ..models import GameState
from .common import RuleError


def uses_capital_warehouse(state: GameState) -> bool:
    """Compatibility name: 1.2+ now uses a regime-wide treasury."""
    return False


def uses_global_treasury(state: GameState) -> bool:
    return str(state.flags.get("content_version", "1.1")) == "1.2" and bool(
        state.flags.get("v12_economy", {}).get("regions")
    )


def capital_region_id(state: GameState, regime_id: int) -> int | None:
    regime = state.regimes.get(int(regime_id), {})
    capital = state.cities.get(int(regime.get("capital") or 0), {})
    region_id = int(capital.get("region_id") or 0)
    return region_id if region_id in state.regions else None


def treasury_balance(state: GameState, regime_id: int | None = None) -> float:
    regime_id = int(regime_id if regime_id is not None else state.player_regime_id)
    return round(float(state.regimes.get(regime_id, {}).get("treasury", 0.0)), 2)


def set_treasury(state: GameState, regime_id: int, amount: float) -> float:
    amount = round(max(0.0, float(amount)), 2)
    state.regimes[int(regime_id)]["treasury"] = amount
    return amount


def change_treasury(state: GameState, regime_id: int, delta: float) -> float:
    return set_treasury(state, regime_id, treasury_balance(state, regime_id) + float(delta))


def spend_treasury(state: GameState, regime_id: int, amount: float) -> float:
    amount = round(max(0.0, float(amount)), 2)
    available = treasury_balance(state, regime_id)
    if available + 1e-9 < amount:
        raise RuleError(f"国库不足：需要{amount:g}，现有铜钱{available:g}")
    return set_treasury(state, regime_id, available - amount)


def migrate_legacy_treasuries(state: GameState) -> None:
    """Collect every legacy regional copper balance into its controller's global treasury."""
    if not uses_global_treasury(state) or state.flags.get("v12_global_treasury_migrated"):
        return
    totals = {int(regime_id): float(regime.get("treasury", 0.0) or 0.0) for regime_id, regime in state.regimes.items()}
    for region_id, region in state.regions.items():
        record = state.flags["v12_economy"]["regions"].get(str(int(region_id)), {})
        warehouse = record.setdefault("warehouse", {})
        copper = float(warehouse.pop("copper", 0.0) or 0.0)
        controller = int(region.get("controller", 0))
        if controller in totals:
            totals[controller] += copper
    for regime_id, amount in totals.items():
        set_treasury(state, regime_id, amount)
    state.flags["v12_global_treasury_migrated"] = True
    state.flags["v12_capital_treasury_migrated"] = True
