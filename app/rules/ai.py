from __future__ import annotations

import random
from collections import deque
from ..constants import OFFICE_NAMES
from ..models import GameState
from .common import is_regime_eliminated, living_regime_people
from .military import attack, city_controller, legal_attacks, legal_moves, march
from .ai_strategy import (
    defense_assignments,
    ensure_later_qin_408_reinforcements,
    invasion_target_city,
    plan_wei_invasion,
    run_administrative_actions,
)


def _road_distance(state: GameState, start: int, goal: int) -> int:
    if start == goal:
        return 0
    adjacent: dict[int, set[int]] = {}
    for road in state.roads:
        left, right = int(road["from"]), int(road["to"])
        adjacent.setdefault(left, set()).add(right)
        adjacent.setdefault(right, set()).add(left)
    queue = deque([(start, 0)])
    visited = {start}
    while queue:
        city_id, distance = queue.popleft()
        for neighbor in adjacent.get(city_id, set()):
            if neighbor == goal:
                return distance + 1
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, distance + 1))
    return 10**6


def _lu_xun_offensive_actions(state: GameState, rng: random.Random) -> None:
    targets = [int(item) for item in state.flags.get("lu_xun_offensive_targets", [26, 1])]
    if not targets:
        return
    first_reached = city_controller(state, targets[0]) == 5 or any(
        army.regime_id == 5 and army.location_id == targets[0] for army in state.armies.values()
    )
    target = targets[1] if first_reached and len(targets) > 1 else targets[0]
    armies = [army for army in list(state.armies.values()) if army.regime_id == 5]
    for army in armies:
        if army.id not in state.armies or army.location_id == target:
            continue
        attacks = legal_attacks(state, army.id)
        if attacks:
            destination = min(attacks, key=lambda item: (_road_distance(state, item[0], target), item[0]))[0]
            try:
                attack(state, army.id, destination, rng)
            except ValueError:
                pass
            continue
        moves = legal_moves(state, army.id)
        if moves:
            destination = min(moves, key=lambda item: (_road_distance(state, item[0], target), item[2], item[0]))[0]
            try:
                march(state, army.id, destination)
            except ValueError:
                pass


def _directed_actions(
    state: GameState,
    regime_id: int,
    target: int,
    rng: random.Random,
    forbidden_regions: set[str] | None = None,
) -> None:
    forbidden_regions = forbidden_regions or set()

    def allowed(city_id: int) -> bool:
        city = state.cities.get(int(city_id), {})
        region = state.regions.get(int(city.get("region_id", 0)), {})
        return region.get("name") not in forbidden_regions

    for army in [item for item in list(state.armies.values()) if item.regime_id == regime_id]:
        if army.id not in state.armies or army.location_id == target:
            continue
        attacks = [item for item in legal_attacks(state, army.id) if allowed(item[0])]
        if attacks:
            destination = min(attacks, key=lambda item: (_road_distance(state, item[0], target), item[0]))[0]
            try:
                attack(state, army.id, destination, rng)
            except ValueError:
                pass
            continue
        moves = [item for item in legal_moves(state, army.id) if allowed(item[0])]
        if moves:
            destination = min(moves, key=lambda item: (_road_distance(state, item[0], target), item[2], item[0]))[0]
            try:
                march(state, army.id, destination)
            except ValueError:
                pass


def prepare_political_actions(state: GameState, regime_id: int) -> None:
    regime = state.regimes[regime_id]
    internal = regime.get("internal", {})
    appointed = {v for v in internal.values() if isinstance(v, int)}
    candidates = [p for p in living_regime_people(state, regime_id) if p["id"] not in appointed]
    candidates.sort(key=lambda p: p.get("attributes", {}).get("intelligence", 0), reverse=True)
    for office in OFFICE_NAMES:
        if office != "emperor" and office in internal and not internal[office] and candidates:
            internal[office] = candidates.pop(0)["id"]
            break
    ensure_later_qin_408_reinforcements(state)


def political_actions(state: GameState, regime_id: int) -> None:
    prepare_political_actions(state, regime_id)
    run_administrative_actions(state, regime_id)
    if regime_id == 2:
        plan_wei_invasion(state)


def _act_toward_target(
    state: GameState,
    army_id: int,
    target: int,
    rng: random.Random,
) -> bool:
    army = state.armies.get(army_id)
    if army is None or army.location_id == target:
        return False
    attacks = legal_attacks(state, army.id)
    if attacks:
        destination = min(attacks, key=lambda item: (_road_distance(state, item[0], target), item[0]))[0]
        try:
            attack(state, army.id, destination, rng)
            return True
        except ValueError:
            return False
    moves = legal_moves(state, army.id)
    if moves:
        destination = min(
            moves,
            key=lambda item: (_road_distance(state, item[0], target), item[2], item[0]),
        )[0]
        try:
            march(state, army.id, destination)
            return True
        except ValueError:
            return False
    return False


def military_actions(state: GameState, regime_id: int, rng: random.Random | None = None) -> None:
    rng = rng or random
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.ai_military import run_ai_military_strategy

        run_ai_military_strategy(state, regime_id, rng)
        return
    if regime_id == 5 and state.flags.get("lu_xun_offensive_targets"):
        _lu_xun_offensive_actions(state, rng)
        return
    if regime_id == 2 and state.flags.get("wei_aid_qin_active"):
        _directed_actions(
            state,
            regime_id,
            int(state.flags.get("wei_aid_target") or 77),
            rng,
            forbidden_regions={"淮北地区"},
        )
        return
    if regime_id == 12 and state.flags.get("huxia_required_peace_region"):
        return
    if regime_id == 12 and int(state.flags.get("huxia_changan_target", 0)):
        _directed_actions(state, regime_id, int(state.flags["huxia_changan_target"]), rng)
        return
    regime = state.regimes[regime_id]
    capital = int(regime.get("capital") or 0)
    armies = [a for a in list(state.armies.values()) if a.regime_id == regime_id]
    assignments = defense_assignments(state, regime_id)
    for army_id, target in assignments.items():
        army = state.armies.get(army_id)
        if army is not None and army.location_id != target:
            _act_toward_target(state, army_id, target, rng)

    protected = {
        army_id for army_id, target in assignments.items()
        if army_id in state.armies and state.armies[army_id].location_id == target
    }
    offensive_target = None
    if regime_id == 2:
        target_regime = plan_wei_invasion(state)
        if target_regime:
            offensive_target = invasion_target_city(state, target_regime)
    for army in armies:
        if army.id not in state.armies or army.id in assignments or army.id in protected:
            continue
        if offensive_target and _act_toward_target(state, army.id, offensive_target, rng):
            continue
        attacks = legal_attacks(state, army.id)
        if attacks and rng.random() < 0.75:
            try:
                attack(state, army.id, rng.choice(attacks)[0], rng)
            except ValueError:
                pass
            continue
        # 已由防守分派保证首都、地区首府和高城防关隘依次获得守军。
        capital_guards = [a for a in armies if a.location_id == capital and a.id in state.armies]
        if army.location_id == capital and len(capital_guards) <= 1:
            continue
        moves = legal_moves(state, army.id)
        frontier = [
            move for move in moves
            if state.at_war(regime_id, city_controller(state, move[0]))
        ]
        choice_pool = frontier or moves
        if choice_pool and rng.random() < 0.5:
            try:
                march(state, army.id, rng.choice(choice_pool)[0])
            except ValueError:
                pass


def run_phase(
    state: GameState,
    phase_index: int,
) -> None:
    v12 = str(state.flags.get("content_version", "1.1")) == "1.2"
    if v12 and phase_index == 2:
        from .diplomacy import settle_ai_total_annexations

        settle_ai_total_annexations(state)
    for regime_id in state.regimes:
        if regime_id == state.player_regime_id:
            continue
        if is_regime_eliminated(state, regime_id):
            continue
        if v12:
            if phase_index == 0:
                prepare_political_actions(state, regime_id)
                if regime_id == 2:
                    plan_wei_invasion(state)
                from ..content.v1_2.economy import run_ai_economic_orders

                run_ai_economic_orders(state, regime_id)
            elif phase_index == 2:
                if regime_id == 2:
                    from ..content.v1_2.scenario import queue_wei_peace_offer_during_diplomacy

                    queue_wei_peace_offer_during_diplomacy(state)
                from .diplomacy import queue_ai_peace_offer

                queue_ai_peace_offer(state, regime_id)
            elif phase_index == 3:
                military_actions(state, regime_id)
            continue
        if phase_index == 0:
            political_actions(state, regime_id)
        elif phase_index == 3:
            military_actions(state, regime_id)
