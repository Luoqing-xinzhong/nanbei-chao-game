from __future__ import annotations

import random

from ..models import GameState
from .common import RuleError, clamp, is_regime_eliminated
from .laws import level
from .treasury import change_treasury, spend_treasury, treasury_balance


def month_index(state: GameState) -> int:
    return state.year * 12 + state.month - 1


def truce_key(state: GameState, left: int, right: int) -> str:
    pair = state.relation_pair(left, right)
    return f"truce_until:{pair[0]}:{pair[1]}"


def truce_active(state: GameState, left: int, right: int) -> bool:
    return month_index(state) < int(state.flags.get(truce_key(state, left, right), 0))


def declare_war(state: GameState, aggressor_id: int, defender_id: int) -> list[int]:
    """Start a war through the common 1.2 support rules and return the normalized pair."""
    aggressor_id, defender_id = int(aggressor_id), int(defender_id)
    v12 = str(state.flags.get("content_version", "1.1")) == "1.2"
    if v12:
        support = int(state.regimes.get(aggressor_id, {}).get("war_support", 0))
        if support < 50:
            raise RuleError(f"战争支持度仅{support}，低于50，不能主动发起战争")
    pair = state.relation_pair(aggressor_id, defender_id)
    if pair not in state.wars:
        state.wars.append(pair)
        if v12:
            defender = state.regimes.get(defender_id, {})
            defender["war_support"] = int(clamp(int(defender.get("war_support", 0)) + 20, 0, 100))
            state.add_log(f"{defender.get('name', defender_id)}受到侵略，战争支持度+20。")
    state.flags[f"war_started:{pair[0]}:{pair[1]}"] = state.turn_number
    state.flags[f"war_aggressor:{pair[0]}:{pair[1]}"] = aggressor_id
    return pair


def apply_casualty_war_support_loss(state: GameState, regime_id: int, casualties: int) -> int:
    """Accumulate battle casualties; each adjusted 500 casualties costs one support point."""
    if str(state.flags.get("content_version", "1.1")) != "1.2" or casualties <= 0:
        return 0
    from .ai_modifiers import ai_difficulty_war_support_loss_multiplier
    from .laws import war_support_loss

    key = str(int(regime_id))
    progress = state.flags.setdefault("v12_war_support_casualty_progress", {})
    adjusted_points = casualties / 500 * ai_difficulty_war_support_loss_multiplier(state, regime_id)
    accumulated = float(progress.get(key, 0.0)) + adjusted_points
    points = int(accumulated + 1e-9)
    progress[key] = round(accumulated - points, 6)
    if points <= 0:
        return 0
    actual = war_support_loss(state, regime_id, points)
    regime = state.regimes[int(regime_id)]
    regime["war_support"] = int(clamp(int(regime.get("war_support", 0)) - actual, 0, 100))
    state.add_log(
        f"{regime.get('name', regime_id)}战斗伤亡累计触发战争支持度-{actual}，"
        f"当前{regime['war_support']}。"
    )
    return actual


def region_owner(state: GameState, region_id: int) -> int:
    name = state.regions[region_id]["name"]
    return next((rid for rid, regime in state.regimes.items() if name in regime.get("regions", [])), 0)


def occupied_regions(state: GameState, occupier_id: int, owner_id: int) -> list[int]:
    return [
        region_id for region_id, region in state.regions.items()
        if region_owner(state, region_id) == owner_id and int(region.get("controller", 0)) == occupier_id
    ]


def mark_ai_total_occupation(state: GameState, occupier_id: int, owner_id: int) -> bool:
    """Remember when one AI first controls every legally owned region of another AI."""
    if occupier_id == state.player_regime_id or owner_id == state.player_regime_id:
        return False
    if not state.at_war(occupier_id, owner_id):
        return False
    owned = [region_id for region_id in state.regions if region_owner(state, region_id) == owner_id]
    if not owned or any(int(state.regions[region_id].get("controller", 0)) != occupier_id for region_id in owned):
        return False
    records = state.flags.setdefault("ai_total_occupation", {})
    records.setdefault(f"{occupier_id}:{owner_id}", month_index(state))
    return True


def settle_ai_total_annexations(state: GameState) -> list[tuple[int, int]]:
    """At the next AI diplomacy phase, turn complete occupation into total annexation."""
    records = state.flags.setdefault("ai_total_occupation", {})
    current_month = month_index(state)
    # Also discover complete occupations from older saves, using capture records when possible.
    for pair in list(state.wars):
        left, right = (int(pair[0]), int(pair[1]))
        if state.player_regime_id in {left, right}:
            continue
        for occupier_id, owner_id in ((left, right), (right, left)):
            owned = [region_id for region_id in state.regions if region_owner(state, region_id) == owner_id]
            if not owned or any(int(state.regions[region_id].get("controller", 0)) != occupier_id for region_id in owned):
                continue
            key = f"{occupier_id}:{owner_id}"
            if key not in records:
                captures = state.flags.get("v12_region_captures", {})
                capture_months = [
                    int(captures.get(str(region_id), {}).get("month", current_month))
                    for region_id in owned
                    if int(captures.get(str(region_id), {}).get("regime_id", 0)) == occupier_id
                ]
                records[key] = max(capture_months, default=current_month)

    completed: list[tuple[int, int]] = []
    for key, occupied_month in list(records.items()):
        try:
            occupier_id, owner_id = (int(item) for item in str(key).split(":", 1))
        except (TypeError, ValueError):
            records.pop(key, None)
            continue
        owned = [region_id for region_id in state.regions if region_owner(state, region_id) == owner_id]
        still_complete = (
            owned
            and state.at_war(occupier_id, owner_id)
            and all(int(state.regions[region_id].get("controller", 0)) == occupier_id for region_id in owned)
        )
        if not still_complete:
            records.pop(key, None)
            continue
        if current_month <= int(occupied_month):
            continue
        names = [str(state.regions[region_id]["name"]) for region_id in owned]
        for region_id in owned:
            _transfer_region(state, region_id, occupier_id)
        pair = state.relation_pair(occupier_id, owner_id)
        if pair in state.wars:
            state.wars.remove(pair)
        state.regimes[owner_id]["relation_with_main"] = "灭亡"
        state.vassals.pop(owner_id, None)
        state.wars[:] = [war for war in state.wars if owner_id not in war]
        repatriate_armies_after_peace(state, occupier_id, owner_id)
        records.pop(key, None)
        completed.append((occupier_id, owner_id))
        state.add_log(
            f"AI外交：{state.regimes[owner_id]['name']}全境已被{state.regimes[occupier_id]['name']}占领，"
            f"双方签订割让条约；{'、'.join(names)}全部并入{state.regimes[occupier_id]['name']}。"
        )
    return completed


def _transfer_region(state: GameState, region_id: int, new_owner_id: int) -> None:
    region = state.regions[region_id]
    name = region["name"]
    old_owner_id = region_owner(state, region_id)
    governor_id = int(region.get("governor") or 0)
    if governor_id:
        region["governor"] = None
        state.add_log(
            f"和平割地：{name}所有权由{state.regimes.get(old_owner_id, {}).get('name', '无')}"
            f"转移给{state.regimes.get(new_owner_id, {}).get('name', '无')}，"
            f"原刺史{state.person_name(governor_id)}卸任。"
        )
    if old_owner_id and name in state.regimes[old_owner_id].get("regions", []):
        state.regimes[old_owner_id]["regions"].remove(name)
    if name not in state.regimes[new_owner_id].setdefault("regions", []):
        state.regimes[new_owner_id]["regions"].append(name)
    region["controller"] = new_owner_id
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from ..content.v1_2.economy import lock_ai_region_control

        lock_ai_region_control(state, region_id, new_owner_id)


def _repatriation_destination(state: GameState, regime_id: int) -> int | None:
    if is_regime_eliminated(state, regime_id):
        return None
    regime = state.regimes[regime_id]
    legal_regions = set(regime.get("regions", []))
    capital = int(regime.get("capital") or 0)
    capital_city = state.cities.get(capital, {})
    capital_region = state.regions.get(int(capital_city.get("region_id", 0)), {})
    if capital_city and capital_region.get("name") in legal_regions and int(capital_region.get("controller", 0)) == regime_id:
        return capital
    controlled_capitals = sorted(
        (
            city for city in state.cities.values()
            if city.get("capital")
            and city.get("region") in legal_regions
            and int(state.regions.get(int(city.get("region_id", 0)), {}).get("controller", 0)) == regime_id
        ),
        key=lambda city: (-int(city.get("defense", 0)), int(city["id"])),
    )
    if controlled_capitals:
        return int(controlled_capitals[0]["id"])
    controlled_cities = sorted(
        (
            city for city in state.cities.values()
            if city.get("region") in legal_regions
            and int(state.regions.get(int(city.get("region_id", 0)), {}).get("controller", 0)) == regime_id
        ),
        key=lambda city: int(city["id"]),
    )
    if controlled_cities:
        return int(controlled_cities[0]["id"])
    legal_city = next((city for city in state.cities.values() if city.get("region") in legal_regions), None)
    return int(legal_city["id"]) if legal_city else None


def repatriate_armies_after_peace(state: GameState, left_id: int, right_id: int) -> dict[str, list[int]]:
    """和平后遣返双方滞留在原敌国法理境内的军队；灭亡一方的军队直接清除。"""
    from .military import sync_commander_location

    moved: list[int] = []
    removed: list[int] = []
    for regime_id, former_enemy_id in ((left_id, right_id), (right_id, left_id)):
        armies = [army for army in list(state.armies.values()) if army.regime_id == regime_id]
        if is_regime_eliminated(state, regime_id):
            for army in armies:
                state.armies.pop(army.id, None)
                removed.append(int(army.id))
            continue
        destination = _repatriation_destination(state, regime_id)
        for army in armies:
            city = state.cities.get(int(army.location_id), {})
            region_id = int(city.get("region_id", 0))
            region = state.regions.get(region_id, {})
            in_former_enemy_territory = (
                region_owner(state, region_id) == former_enemy_id
                or int(region.get("controller", 0)) == former_enemy_id
            ) if region_id else False
            if not in_former_enemy_territory:
                continue
            if destination is None:
                state.armies.pop(army.id, None)
                removed.append(int(army.id))
                continue
            army.location_id = destination
            sync_commander_location(state, army)
            moved.append(int(army.id))
    if moved:
        state.add_log("和平撤军：" + "、".join(f"军队#{army_id}" for army_id in moved) + "已返回本国境内。")
    if removed:
        state.add_log("和平清军：" + "、".join(f"军队#{army_id}" for army_id in removed) + "所属政权已经灭亡，编制被清除。")
    return {"moved": sorted(moved), "removed": sorted(removed)}


def force_surrender(state: GameState, regime_id: int) -> bool:
    """At support below 20, restore conquests and cede the surrenderer's occupied land."""
    regime_id = int(regime_id)
    if str(state.flags.get("content_version", "1.1")) != "1.2":
        return False
    regime = state.regimes.get(regime_id, {})
    if int(regime.get("war_support", 0)) >= 20:
        return False
    enemies = {
        int(side)
        for pair in state.wars
        if regime_id in {int(item) for item in pair}
        for side in pair
        if int(side) != regime_id
    }
    if not enemies:
        return False

    returned: list[int] = []
    ceded: list[int] = []
    # First return every enemy-owned region occupied by the surrendering regime.
    for region_id, region in list(state.regions.items()):
        owner = region_owner(state, int(region_id))
        if owner in enemies and int(region.get("controller", 0)) == regime_id:
            region["controller"] = owner
            region["governor"] = None
            try:
                from ..content.v1_2.economy import lock_ai_region_control

                lock_ai_region_control(state, int(region_id), owner)
            except (ImportError, KeyError):
                pass
            returned.append(int(region_id))

    # Then permanently cede the surrenderer's regions already occupied by each enemy.
    occupied = [
        (int(region_id), int(region.get("controller", 0)))
        for region_id, region in state.regions.items()
        if region_owner(state, int(region_id)) == regime_id
        and int(region.get("controller", 0)) in enemies
    ]
    for region_id, occupier in occupied:
        _transfer_region(state, region_id, occupier)
        ceded.append(region_id)

    for enemy_id in sorted(enemies):
        pair = state.relation_pair(regime_id, enemy_id)
        if pair in state.wars:
            state.wars.remove(pair)
        state.flags[truce_key(state, regime_id, enemy_id)] = month_index(state) + 12
        repatriate_armies_after_peace(state, regime_id, enemy_id)
    regime["relation_with_main"] = "灭亡" if is_regime_eliminated(state, regime_id) else "战败"
    state.flags.setdefault("v12_forced_surrenders", []).append({
        "regime_id": regime_id,
        "month": month_index(state),
        "returned_regions": returned,
        "ceded_regions": ceded,
    })
    returned_names = "、".join(state.regions[item]["name"] for item in returned) or "无"
    ceded_names = "、".join(state.regions[item]["name"] for item in ceded) or "无"
    state.add_log(
        f"{regime.get('name', regime_id)}战争支持度低于20，被迫投降："
        f"交还侵占地区{returned_names}；割让被占地区{ceded_names}。"
    )
    return True


def settle_forced_surrenders(state: GameState) -> list[int]:
    surrendered = []
    for regime_id in sorted(state.regimes):
        if force_surrender(state, int(regime_id)):
            surrendered.append(int(regime_id))
    return surrendered


def _remaining_force(state: GameState, regime_id: int) -> int:
    return sum(
        max(0, int(army.soldiers))
        for army in state.armies.values()
        if int(army.regime_id) == int(regime_id)
    )


def peace_score(state: GameState, target_id: int, terms: dict) -> tuple[int, list[str]]:
    """Score a treaty from the AI target's point of view.

    Positive values make peace more attractive.  Territory already occupied is
    deliberately treated differently from an extra, unoccupied demand so the
    score follows the battlefield instead of merely counting legal ownership.
    """
    player_id = state.player_regime_id
    mandatory = set(occupied_regions(state, player_id, target_id))
    requested = set(int(x) for x in terms.get("target_cedes", []))
    offered = set(int(x) for x in terms.get("player_cedes", []))
    player_occupied = set(occupied_regions(state, target_id, player_id))
    parts: list[tuple[str, int]] = [("默认和解阻力", -20)]

    ai_soldiers = _remaining_force(state, target_id)
    player_soldiers = _remaining_force(state, player_id)
    force_ratio = ai_soldiers / max(1, player_soldiers)
    if force_ratio > 1.2:
        force_penalty = -int(round(force_ratio * 100))
        parts.append((f"AI剩余兵力为对手{force_ratio:.2f}倍，尚有一战之力", force_penalty))
    elif force_ratio < 0.5:
        disadvantage_ratio = player_soldiers / max(1, ai_soldiers)
        force_bonus = int(round(disadvantage_ratio * 100))
        parts.append((f"对手剩余兵力为AI的{disadvantage_ratio:.2f}倍", force_bonus))

    occupied_concessions = requested & mandatory
    returned_occupations = mandatory - requested
    extra_concessions = requested - mandatory
    if occupied_concessions:
        parts.append((f"确认割让已被玩家占领的地区×{len(occupied_concessions)}", 0))
    if returned_occupations:
        parts.append((f"玩家归还所占AI地区×{len(returned_occupations)}", 50 * len(returned_occupations)))
    if extra_concessions:
        parts.append((f"要求割让未被玩家占领的地区×{len(extra_concessions)}", -10_000 * len(extra_concessions)))

    occupied_awards = offered & player_occupied
    extra_awards = offered - player_occupied
    if occupied_awards:
        parts.append((f"玩家承认AI已占领地区×{len(occupied_awards)}", 50 * len(occupied_awards)))
    if extra_awards:
        parts.append((f"玩家额外割让地区×{len(extra_awards)}", 75 * len(extra_awards)))
    omitted_occupations = player_occupied - offered
    if omitted_occupations:
        parts.append((f"AI归还所占玩家地区×{len(omitted_occupations)}", 50 * len(omitted_occupations)))

    player_pays = max(0, int(terms.get("player_pays", 0)))
    target_pays = max(0, int(terms.get("target_pays", 0)))
    if player_pays:
        parts.append((f"玩家赔款{player_pays}", min(150, player_pays // 10)))
    if target_pays:
        parts.append((f"AI赔款{target_pays}", -min(150, target_pays // 10)))
    if terms.get("target_vassal"):
        parts.append(("要求AI臣服", -100))
    huxia_required = int(state.flags.get("huxia_required_peace_region", 0)) if target_id == 12 else 0
    if huxia_required and huxia_required in offered:
        parts.append(("满足胡夏既定议和条件", 150))

    ai_support = int(state.regimes[target_id].get("war_support", 0))
    player_support = int(state.player_regime.get("war_support", 0))
    support_score = (player_support - ai_support) * 2
    if support_score:
        parts.append((f"战争支持度差（玩家{player_support}/AI{ai_support}）", support_score))
    return sum(value for _, value in parts), [f"{name}{value:+d}" for name, value in parts]


def peace_evaluation(state: GameState, target_id: int, terms: dict) -> tuple[bool, str]:
    """Evaluate a player/AI treaty with a transparent battlefield score."""
    player_id = state.player_regime_id
    offered = set(int(x) for x in terms.get("player_cedes", []))
    huxia_required = int(state.flags.get("huxia_required_peace_region", 0)) if target_id == 12 else 0
    if huxia_required and huxia_required not in offered:
        return False, "胡夏坚持要求割让北雍州"
    if int(terms.get("target_pays", 0)) > treasury_balance(state, target_id):
        return False, "AI无力支付协议中的赔款"
    if int(terms.get("player_pays", 0)) > treasury_balance(state, player_id):
        return False, "玩家无力支付协议中的赔款"
    score, breakdown = peace_score(state, target_id, terms)
    if huxia_required and huxia_required in offered and score < 0:
        # This legacy story war defines North Yong as Hu Xia's sufficient peace
        # condition; preserve that contract while still showing the common score.
        breakdown.append(f"胡夏既定条件保底{(-score):+d}")
        score = 0
    accepted = score >= 0
    detail = f"AI和解倾向 {score:+d}"
    if breakdown:
        detail += "（" + "；".join(breakdown) + "）"
    return accepted, detail


def _peace_offer_cooldowns(state: GameState) -> dict[str, int]:
    return state.flags.setdefault("ai_peace_offer_cooldown", {})


def queue_ai_peace_offer(state: GameState, target_id: int) -> bool:
    """Let one AI opponent propose a treaty during its diplomacy phase."""
    target_id = int(target_id)
    player_id = state.player_regime_id
    if state.flags.get("pending_ai_peace_offer") or not state.at_war(player_id, target_id):
        return False
    if is_regime_eliminated(state, target_id):
        return False
    if month_index(state) < int(_peace_offer_cooldowns(state).get(str(target_id), 0)):
        return False
    # Scripted event peace takes precedence over the generic system.
    if any(state.events.get(int(event_id), {}).get("peace_offer") for event_id in state.flags.get("pending_story_events", [])):
        return False

    target_cedes = occupied_regions(state, player_id, target_id)
    player_cedes = occupied_regions(state, target_id, player_id)
    ai_force = _remaining_force(state, target_id)
    player_force = _remaining_force(state, player_id)
    ai_support = int(state.regimes[target_id].get("war_support", 0))
    has_reason = bool(target_cedes or player_cedes or ai_support <= 50 or player_force >= max(1, ai_force) * 1.2)
    if not has_reason:
        return False

    terms = {
        "target_cedes": list(target_cedes),
        "player_cedes": list(player_cedes),
        "target_pays": 0,
        "player_pays": 0,
        "target_vassal": False,
    }
    base_score, _ = peace_score(state, target_id, terms)
    if ai_force > player_force * 1.15 or len(player_cedes) > len(target_cedes):
        terms["player_pays"] = min(int(treasury_balance(state, player_id)), 200)
    target_region_ids = {
        int(region_id)
        for region_id in state.regions
        if region_owner(state, int(region_id)) == target_id
    }
    target_will_be_eliminated = (
        bool(target_region_ids)
        and target_region_ids <= set(target_cedes)
        and not player_cedes
    )
    if (
        not terms["player_pays"]
        and not target_will_be_eliminated
        and base_score >= 20
        and (target_cedes or ai_support <= 40)
    ):
        # A losing AI may buy peace, but never offers so much that its own score
        # falls below acceptance solely because of the indemnity.
        affordable = min(int(treasury_balance(state, target_id)), 200)
        terms["target_pays"] = min(affordable, max(0, base_score - 10) * 10)

    accepted, detail = peace_evaluation(state, target_id, terms)
    if not accepted:
        return False
    state.flags["pending_ai_peace_offer"] = {
        "regime_id": target_id,
        "terms": terms,
        "evaluation": detail,
        "month": month_index(state),
    }
    state.add_log(f"{state.regimes[target_id]['name']}在外交阶段遣使提出和平协议。")
    return True


def reject_ai_peace_offer(state: GameState) -> str:
    offer = state.flags.pop("pending_ai_peace_offer", None)
    if not isinstance(offer, dict):
        raise RuleError("当前没有待答复的AI和平协议")
    target_id = int(offer.get("regime_id", 0))
    _peace_offer_cooldowns(state)[str(target_id)] = month_index(state) + 4
    name = state.regimes.get(target_id, {}).get("name", f"政权#{target_id}")
    message = f"我方拒绝{name}的和平协议；该国最早四个月后才能再次提议。"
    state.add_log(message)
    return message


def accept_ai_peace_offer(state: GameState) -> str:
    offer = state.flags.get("pending_ai_peace_offer")
    if not isinstance(offer, dict):
        raise RuleError("当前没有待答复的AI和平协议")
    target_id = int(offer.get("regime_id", 0))
    result = make_peace(state, target_id, dict(offer.get("terms", {})))
    state.flags.pop("pending_ai_peace_offer", None)
    _peace_offer_cooldowns(state).pop(str(target_id), None)
    return result


def make_peace(state: GameState, target_id: int, terms: dict | None = None) -> str:
    target = _check(state, target_id)
    if level(state, "north") == 5 and target.get("name") == "魏":
        raise RuleError("一统天下国策要求与魏死战到底，不能议和")
    pair = state.relation_pair(state.player_regime_id, target_id)
    if pair not in state.wars:
        raise RuleError("双方并未交战")
    terms = dict(terms or {})
    scripted_offer = bool(terms.pop("_scripted_offer", False))
    occupied_target_regions = set(occupied_regions(state, state.player_regime_id, target_id))
    target_cedes = set(int(x) for x in terms.get("target_cedes", []))
    returned_to_target = occupied_target_regions - target_cedes
    player_cedes = set(int(x) for x in terms.get("player_cedes", []))
    returned_to_player = set(occupied_regions(state, target_id, state.player_regime_id)) - player_cedes
    huxia_required = int(state.flags.get("huxia_required_peace_region", 0)) if target_id == 12 else 0
    if huxia_required and huxia_required not in player_cedes:
        raise RuleError("胡夏只接受割让北雍州的和平协议")
    if any(region_owner(state, rid) != target_id for rid in target_cedes):
        raise RuleError("对方割让列表包含不属于对方的地区")
    if any(region_owner(state, rid) != state.player_regime_id for rid in player_cedes):
        raise RuleError("我方割让列表包含不属于我方的地区")
    target_pays = max(0, int(terms.get("target_pays", 0)))
    player_pays = max(0, int(terms.get("player_pays", 0)))
    target_region_names = set(target.get("regions", []))
    ceded_target_names = {state.regions[region_id]["name"] for region_id in target_cedes}
    received_names = {state.regions[region_id]["name"] for region_id in player_cedes}
    target_will_be_eliminated = not ((target_region_names - ceded_target_names) | received_names)
    if target_will_be_eliminated and target_pays:
        raise RuleError("该协议将使对方失去全部土地，灭亡政权不能再支付赔款")
    if target_will_be_eliminated and terms.get("target_vassal"):
        raise RuleError("该协议将使对方失去全部土地，灭亡政权不能成为臣属")
    if target_pays > treasury_balance(state, target_id):
        raise RuleError("对方国库不足以支付赔款")
    if player_pays > treasury_balance(state, state.player_regime_id):
        raise RuleError("我方国库不足以支付赔款")
    terms.update({
        "target_cedes": list(target_cedes),
        "target_returns": list(returned_to_target),
        "player_cedes": list(player_cedes),
        "target_pays": target_pays,
        "player_pays": player_pays,
    })
    accepted, evaluation = (True, "剧情和议") if scripted_offer else peace_evaluation(state, target_id, terms)
    if not accepted:
        raise RuleError(f"{target['name']}拒绝了和平协议（{evaluation}）")
    for region_id in target_cedes:
        _transfer_region(state, region_id, state.player_regime_id)
    for region_id in player_cedes:
        _transfer_region(state, region_id, target_id)
    for region_id in returned_to_target:
        region = state.regions[region_id]
        region["controller"] = target_id
        region["governor"] = None
        if str(state.flags.get("content_version", "1.1")) == "1.2":
            from ..content.v1_2.economy import lock_ai_region_control

            lock_ai_region_control(state, region_id, target_id)
    for region_id in returned_to_player:
        region = state.regions[region_id]
        region["controller"] = state.player_regime_id
        region["governor"] = None
        if str(state.flags.get("content_version", "1.1")) == "1.2":
            from ..content.v1_2.economy import lock_ai_region_control

            lock_ai_region_control(state, region_id, state.player_regime_id)
    change_treasury(state, target_id, player_pays - target_pays)
    change_treasury(state, state.player_regime_id, target_pays - player_pays)
    if terms.get("target_vassal"):
        state.vassals[target_id] = state.player_regime_id
        target["relation_with_main"] = "臣服"
    else:
        target["relation_with_main"] = "灭亡" if target_will_be_eliminated else "正常"
    state.wars.remove(pair)
    if str(state.flags.get("content_version", "1.1")) == "1.2" and target_id == 2:
        state.flags["v12_wei_song_peace_concluded"] = True
        if int(state.flags.get("ai_invasion_target:2", 0)) == state.player_regime_id:
            state.flags.pop("ai_invasion_target:2", None)
    state.flags[truce_key(state, state.player_regime_id, target_id)] = month_index(state) + 12
    if target_will_be_eliminated:
        state.vassals.pop(target_id, None)
        state.wars[:] = [war for war in state.wars if target_id not in war]
    withdrawal = repatriate_armies_after_peace(state, state.player_regime_id, target_id)
    if target_id == 12:
        state.flags.pop("huxia_required_peace_region", None)
    state.diplomatic_actions.append(target_id)
    pieces = ["双方停战"]
    if target_cedes:
        pieces.append(f"{target['name']}割让" + "、".join(state.regions[x]["name"] for x in target_cedes))
    if returned_to_target:
        pieces.append("我方归还" + "、".join(state.regions[x]["name"] for x in returned_to_target))
    if player_cedes:
        pieces.append("我方割让" + "、".join(state.regions[x]["name"] for x in player_cedes))
    if returned_to_player:
        pieces.append(f"{target['name']}归还" + "、".join(state.regions[x]["name"] for x in returned_to_player))
    if target_pays:
        pieces.append(f"对方赔款{target_pays}")
    if player_pays:
        pieces.append(f"我方赔款{player_pays}")
    if terms.get("target_vassal"):
        pieces.append("对方臣服")
    if withdrawal["moved"]:
        pieces.append(f"遣返境外军队{len(withdrawal['moved'])}支")
    if withdrawal["removed"]:
        pieces.append(f"清除灭亡政权军队{len(withdrawal['removed'])}支")
    message = f"与{target['name']}缔结和平：" + "；".join(pieces) + f"。（{evaluation}）"
    state.add_log(message)
    return message


def _check(state: GameState, target_id: int) -> dict:
    if target_id == state.player_regime_id or target_id not in state.regimes:
        raise RuleError("外交目标无效")
    if is_regime_eliminated(state, target_id):
        raise RuleError("该政权已经失去全部土地，不能再进行外交或支付赔款")
    if target_id in state.diplomatic_actions:
        raise RuleError("本回合已经对该政权采取过外交行动")
    return state.regimes[target_id]


def act(state: GameState, target_id: int, action: str, envoy_id: int | None = None, rng: random.Random | None = None) -> str:
    target = _check(state, target_id)
    rng = rng or random
    if action == "遣使":
        if not envoy_id or envoy_id not in state.persons:
            raise RuleError("请选择使节")
        intelligence = state.persons[envoy_id].get("attributes", {}).get("intelligence", 0)
        success = rng.random() <= clamp(0.5 * (1 + 0.005 * intelligence), 0, 0.95)
        target["opinion_of_main"] = int(clamp(target.get("opinion_of_main", 0) + (10 if success else -5), -100, 100))
        message = f"{state.person_name(envoy_id)}出使{target['name']}，" + ("宾主尽欢。" if success else "未能取得进展。")
    elif action == "送礼":
        if treasury_balance(state) < 500:
            raise RuleError("国库不足 500")
        spend_treasury(state, state.player_regime_id, 500)
        success = rng.random() <= 0.6
        if success:
            target["opinion_of_main"] = int(clamp(target.get("opinion_of_main", 0) + 20, -100, 100))
        message = f"向{target['name']}赠礼，" + ("对方好感增加 20。" if success else "对方收礼但态度未变。")
    elif action == "羞辱":
        target["opinion_of_main"] = int(clamp(target.get("opinion_of_main", 0) - 20, -100, 100))
        message = f"公开羞辱{target['name']}，其好感下降 20。"
    elif action == "宣战":
        if truce_active(state, state.player_regime_id, target_id):
            remaining = int(state.flags[truce_key(state, state.player_regime_id, target_id)]) - month_index(state)
            raise RuleError(f"停战协定尚有{remaining}个月，不能再次宣战")
        if (
            str(state.flags.get("content_version", "1.1")) == "1.2"
            and int(state.player_regime.get("war_support", 0)) < 50
        ):
            raise RuleError("战争支持度低于50，不能主动宣战")
        north_law = level(state, "north")
        opinion = int(target.get("opinion_of_main", 0))
        yan_chance = target_id == 8 and bool(state.flags.get("yan_free_declaration_available"))
        qin_chance = target_id == 9 and bool(state.flags.get("qin_free_declaration_available"))
        has_claim = bool(state.flags.get(f"war_claim:{target_id}")) or yan_chance or qin_chance
        if north_law == 1:
            raise RuleError("和平至上国策禁止主动宣战")
        if north_law == 2 and opinion >= -80:
            raise RuleError("以和为贵国策要求对方好感低于-80，且不能使用宣战借口")
        if north_law == 3 and opinion >= -20 and not has_claim:
            raise RuleError("积极防御国策要求好感低于-20或拥有宣战借口")
        if north_law in {4, 5} and target.get("name") != "魏" and opinion >= -20 and not has_claim:
            raise RuleError("对非魏政权宣战仍需好感低于-20或拥有宣战借口")
        pair = declare_war(state, state.player_regime_id, target_id)
        if yan_chance:
            state.flags["yan_free_declaration_available"] = False
        if qin_chance:
            state.flags["qin_free_declaration_available"] = False
        target["relation_with_main"] = "交战"
        message = f"向{target['name']}宣战。"
    elif action == "和解":
        # 简单调用保留给规则层兼容；界面会使用可定制的 make_peace。
        return make_peace(state, target_id, {})
    elif action == "要求臣服":
        accept = target.get("war_support", 100) < 25 or treasury_balance(state, target_id) < 300
        if not accept:
            raise RuleError("对方实力尚存，拒绝臣服")
        state.vassals[target_id] = state.player_regime_id
        target["relation_with_main"] = "臣服"
        message = f"{target['name']}接受册封，向我方臣服。"
    else:
        raise RuleError("该外交行动尚未开放")
    state.diplomatic_actions.append(target_id)
    state.add_log(message)
    return message
