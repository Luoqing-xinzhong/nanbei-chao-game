from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.content.v1_2.ai_military import national_military_snapshot
from app.content.v1_2.economy import (
    ai_standing_force_target,
    economy_data,
    market_capacity,
    population_units,
    region_economy,
)
from app.content.v1_2.scenario import apply_event_choice, load_v12_state
from app.rules.common import is_regime_eliminated
from app.rules.turn import advance_phase


def run(seed: int, years: int) -> dict:
    random.seed(seed)
    state = load_v12_state()
    start_population = len(population_units(state))
    start_year = state.year
    cleanup_removed = 0.0
    cleanup_annexed = 0
    cleanup_seen: set[int] = set()
    max_market_ratio = 0.0
    market_cap_violations = 0
    winter_caution_months = 0
    errors: list[str] = []

    for _month in range(years * 12):
        try:
            if state.events.get(1203, {}).get("triggered") and not state.flags.get("v12_wei_peace_rejected"):
                apply_event_choice(state, 1203, "拒绝议和")
            snapshot = national_military_snapshot(state, 2) if not is_regime_eliminated(state, 2) else None
            if snapshot and snapshot.get("winter_naval_caution"):
                winter_caution_months += 1
            for _phase in range(4):
                advance_phase(state)
            cleanup = economy_data(state).get("last_january_market_cleanup", [])
            cleanup_year = int(state.year) - 1 if int(state.month) == 2 else int(state.year)
            if cleanup and cleanup_year not in cleanup_seen:
                cleanup_seen.add(cleanup_year)
                cleanup_removed += sum(float(item.get("removed_total", 0.0)) for item in cleanup)
                cleanup_annexed += sum(int(item.get("annexed_land", 0)) for item in cleanup)
            for region_id in state.regions:
                record = region_economy(state, int(region_id))
                for good in ("food", "cloth"):
                    capacity = market_capacity(state, int(region_id), good)
                    stock = float(record["market"].get(good, 0.0))
                    max_market_ratio = max(max_market_ratio, stock / max(0.01, capacity))
                    if stock > capacity + 0.011:
                        market_cap_violations += 1
        except Exception as exc:  # long-run diagnostic should report the exact stopping point
            errors.append(f"{state.year}-{state.month} phase={state.phase_index}: {type(exc).__name__}: {exc}")
            break

    controlled = {
        str(regime_id): sum(1 for region in state.regions.values() if int(region.get("controller", 0)) == regime_id)
        for regime_id in state.regimes
    }
    living_regimes = [
        int(regime_id) for regime_id in state.regimes
        if not is_regime_eliminated(state, int(regime_id))
        and int(controlled[str(regime_id)]) > 0
    ]
    wei_armies = [army for army in state.armies.values() if army.regime_id == 2 and army.soldiers > 0]
    return {
        "seed": seed,
        "requested_years": years,
        "start_year": start_year,
        "end_year": state.year,
        "end_month": state.month,
        "completed": not errors and state.year >= start_year + years,
        "errors": errors,
        "population": {"start": start_population, "end": len(population_units(state))},
        "market": {
            "cap_violations": market_cap_violations,
            "max_capacity_ratio": round(max_market_ratio, 4),
            "january_removed": round(cleanup_removed, 2),
            "january_gentry_annexed": cleanup_annexed,
        },
        "winter_caution_months": winter_caution_months,
        "living_regimes": living_regimes,
        "controlled_regions": controlled,
        "military_by_regime": {
            str(regime_id): {
                "target": ai_standing_force_target(state, int(regime_id)),
                "armies": sum(1 for army in state.armies.values() if army.regime_id == int(regime_id)),
                "soldiers": sum(army.soldiers for army in state.armies.values() if army.regime_id == int(regime_id)),
            }
            for regime_id in state.regimes
            if not is_regime_eliminated(state, int(regime_id))
        },
        "wei": {
            "regions_controlled": int(controlled.get("2", 0)),
            "armies": len(wei_armies),
            "soldiers": sum(army.soldiers for army in wei_armies),
            "wars": [pair for pair in state.wars if 2 in pair],
            "peace_rejected": bool(state.flags.get("v12_wei_peace_rejected")),
            "rejection_reinforcements": len(state.flags.get("v12_wei_rejection_reinforcements", [])),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=50)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--seed", type=int, default=1001)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    seeds = [args.seed + index for index in range(args.runs)]
    if args.workers <= 1:
        results = []
        for seed in seeds:
            result = run(seed, args.years)
            results.append(result)
            print(f"completed seed {seed}: {result['end_year']}-{result['end_month']}", file=sys.stderr, flush=True)
    else:
        results = []
        with ProcessPoolExecutor(max_workers=min(args.workers, args.runs)) as executor:
            pending = {executor.submit(run, seed, args.years): seed for seed in seeds}
            for future in as_completed(pending):
                result = future.result()
                results.append(result)
                print(
                    f"completed seed {result['seed']}: {result['end_year']}-{result['end_month']}",
                    file=sys.stderr,
                    flush=True,
                )
        results.sort(key=lambda item: item["seed"])
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
