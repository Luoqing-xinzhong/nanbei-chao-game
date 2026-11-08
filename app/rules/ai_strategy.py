from __future__ import annotations

import random
from collections import deque

from ..constants import AUTHORITY_CAP
from ..models import Army, GameState
from .common import clamp, is_regime_eliminated
from .economy import (
    MILITARY_PAY_PER_BATTALION,
    average_monthly_expenses,
    calculate_region_income,
    regime_income,
)
from .military import city_controller, create_army
from .diplomacy import declare_war
from .politics import command_copper_cost


AI_AUTHORITY_PER_TURN = 200
AI_POLICY_AUTHORITY_COST = 100
AI_DEVELOPMENT_COST = command_copper_cost(300)
AI_DEVELOPMENT_GAIN = 3
AI_RELIEF_COST = command_copper_cost(300)
AI_RELIEF_PROSPERITY_GAIN = 2
AI_RELIEF_STABILITY_GAIN = 3
AI_RELIEF_PROSPERITY_THRESHOLD = 6
AI_RELIEF_STABILITY_THRESHOLD = 50
AI_RECLAIM_AUTHORITY_COST = 50
AI_RECLAIM_MILITIA_COST = 500
AI_CONSCRIPT_COST_PER_SOLDIER = 0.02
AI_DEVELOPMENT_WEIGHT = 0.5
AI_EXPANSION_WEIGHT = 0.5
WEI_REGIME_ID = 2
LATER_QIN_REGIME_ID = 9
LATER_QIN_REINFORCEMENT_FLAG = "later_qin_408_reinforcements"
LATER_QIN_REINFORCEMENT_ARMIES_FLAG = "later_qin_408_army_ids"
LATER_QIN_PAY_MODIFIER_ID = 14


def grant_ai_authority(state: GameState) -> None:
    """每个仍拥有土地的AI政权每回合获得100权威。"""
    for regime_id, regime in state.regimes.items():
        if regime_id == state.player_regime_id or is_regime_eliminated(state, regime_id):
            continue
        regime["authority"] = min(
            AUTHORITY_CAP,
            int(regime.get("authority", 0)) + AI_AUTHORITY_PER_TURN,
        )


def controlled_owned_regions(state: GameState, regime_id: int) -> list[dict]:
    names = set(state.regimes[regime_id].get("regions", []))
    return [
        region
        for region in state.regions.values()
        if region.get("name") in names and int(region.get("controller", 0)) == regime_id
    ]


def issue_development_policy(state: GameState, regime_id: int, region_id: int | None = None) -> int | None:
    """AI在政治阶段颁布一次经济发展政策，不调用玩家的法律或经略。"""
    regime = state.regimes[regime_id]
    regime.setdefault("authority", AI_AUTHORITY_PER_TURN)
    candidates = [
        region for region in controlled_owned_regions(state, regime_id)
        if int(region.get("development", 0)) < 100
    ]
    if (
        int(regime.get("authority", 0)) < AI_POLICY_AUTHORITY_COST
        or int(regime.get("treasury", 0)) < AI_DEVELOPMENT_COST
        or not candidates
    ):
        return None
    if region_id is None:
        region = min(candidates, key=lambda item: (int(item.get("development", 0)), int(item["id"])))
    else:
        region = next((item for item in candidates if int(item["id"]) == int(region_id)), None)
        if region is None:
            return None
    regime["authority"] -= AI_POLICY_AUTHORITY_COST
    regime["treasury"] -= AI_DEVELOPMENT_COST
    region["development"] = int(clamp(int(region.get("development", 0)) + AI_DEVELOPMENT_GAIN, 0, 100))
    state.add_log(
        f"{regime['name']}颁布发展政策：{region['name']}发展度提升至{region['development']}，"
        f"国库-{AI_DEVELOPMENT_COST}、权威-{AI_POLICY_AUTHORITY_COST}。"
    )
    return int(region["id"])


def _relief_target(state: GameState, regime_id: int, region_id: int | None = None) -> dict | None:
    regime = state.regimes[regime_id]
    candidates = controlled_owned_regions(state, regime_id)
    if not candidates:
        return None
    if region_id is None:
        region = min(candidates, key=lambda item: (int(item.get("prosperity", 0)), int(item["id"])))
    else:
        region = next((item for item in candidates if int(item["id"]) == int(region_id)), None)
        if region is None:
            return None
    if (
        int(region.get("prosperity", 0)) >= AI_RELIEF_PROSPERITY_THRESHOLD
        and int(regime.get("stability", 0)) >= AI_RELIEF_STABILITY_THRESHOLD
    ):
        return None
    return region


def issue_relief_policy(state: GameState, regime_id: int, region_id: int | None = None) -> int | None:
    """AI在繁荣度或稳定度偏低时优先赈灾。"""
    regime = state.regimes[regime_id]
    region = _relief_target(state, regime_id, region_id)
    if (
        region is None
        or int(regime.get("authority", 0)) < AI_POLICY_AUTHORITY_COST
        or int(regime.get("treasury", 0)) < AI_RELIEF_COST
    ):
        return None
    regime["authority"] -= AI_POLICY_AUTHORITY_COST
    regime["treasury"] -= AI_RELIEF_COST
    regime["stability"] = int(clamp(int(regime.get("stability", 0)) + AI_RELIEF_STABILITY_GAIN, 0, 100))
    region["prosperity"] = int(clamp(int(region.get("prosperity", 0)) + AI_RELIEF_PROSPERITY_GAIN, 0, 10))
    state.add_log(
        f"{regime['name']}赈济{region['name']}：稳定度+{AI_RELIEF_STABILITY_GAIN}，"
        f"繁荣度+{AI_RELIEF_PROSPERITY_GAIN}，国库-{AI_RELIEF_COST}、权威-{AI_POLICY_AUTHORITY_COST}。"
    )
    return int(region["id"])


def _eligible_family_ids(state: GameState, regime_id: int) -> list[int]:
    return sorted(
        int(family_id)
        for family_id, family in state.families.items()
        if int(state.persons.get(int(family.get("leader") or 0), {}).get("country_id", 0)) == regime_id
    )


def _reclaim_owners(state: GameState, regime_id: int) -> list[int]:
    families = _eligible_family_ids(state, regime_id)
    # 部分AI政权的精简配置没有具名家族，用“普通地主”(1)承接家族份额。
    family_land = [families[index % len(families)] for index in range(5)] if families else [1] * 5
    return [2] * 5 + family_land + [0] * 5


def _income_after_changes(
    state: GameState,
    regime_id: int,
    region: dict,
    *,
    development_gain: int = 0,
    new_owners: list[int] | None = None,
) -> int:
    candidate = dict(region)
    candidate["land_ownership"] = list(region.get("land_ownership", [])) + list(new_owners or [])
    candidate["development"] = int(clamp(int(region.get("development", 0)) + development_gain, 0, 100))
    return calculate_region_income(candidate, state, regime_id)


def _best_economic_project(state: GameState, regime_id: int) -> tuple[str, int] | None:
    """Compare the actual monthly-income gain from waterworks and reclamation."""
    regime = state.regimes[regime_id]
    regions = controlled_owned_regions(state, regime_id)
    options: list[tuple[int, str, int]] = []
    if int(regime.get("authority", 0)) >= AI_POLICY_AUTHORITY_COST and int(regime.get("treasury", 0)) >= AI_DEVELOPMENT_COST:
        for region in regions:
            if int(region.get("development", 0)) >= 100:
                continue
            before = calculate_region_income(region, state, regime_id)
            gain = _income_after_changes(state, regime_id, region, development_gain=AI_DEVELOPMENT_GAIN) - before
            options.append((gain, "develop", int(region["id"])))
    if (
        int(regime.get("authority", 0)) >= AI_RECLAIM_AUTHORITY_COST
        and int(regime.get("militia", 0)) >= AI_RECLAIM_MILITIA_COST
    ):
        added = _reclaim_owners(state, regime_id)
        for region in regions:
            before = calculate_region_income(region, state, regime_id)
            gain = _income_after_changes(state, regime_id, region, new_owners=added) - before
            options.append((gain, "reclaim", int(region["id"])))
    if not options:
        return None
    _gain, kind, region_id = max(options, key=lambda item: (item[0], item[1] == "reclaim", -item[2]))
    return kind, region_id


def issue_reclaim_policy(state: GameState, regime_id: int, region_id: int) -> int | None:
    regime = state.regimes[regime_id]
    region = state.regions.get(int(region_id))
    if (
        region not in controlled_owned_regions(state, regime_id)
        or int(regime.get("authority", 0)) < AI_RECLAIM_AUTHORITY_COST
        or int(regime.get("militia", 0)) < AI_RECLAIM_MILITIA_COST
    ):
        return None
    region.setdefault("land_ownership", []).extend(_reclaim_owners(state, regime_id))
    region["land"] = int(region.get("land", len(region["land_ownership"]) - 15)) + 15
    regime["militia"] -= AI_RECLAIM_MILITIA_COST
    regime["authority"] -= AI_RECLAIM_AUTHORITY_COST
    state.add_log(
        f"{regime['name']}在{region['name']}垦荒：土地上限+15，壮丁-{AI_RECLAIM_MILITIA_COST}、"
        f"权威-{AI_RECLAIM_AUTHORITY_COST}。"
    )
    return int(region["id"])


def issue_best_economic_policy(state: GameState, regime_id: int) -> str | None:
    relief_region = issue_relief_policy(state, regime_id)
    if relief_region is not None:
        return f"relief:{relief_region}"
    project = _best_economic_project(state, regime_id)
    if project is None:
        return None
    kind, region_id = project
    if kind == "reclaim":
        result = issue_reclaim_policy(state, regime_id, region_id)
    else:
        result = issue_development_policy(state, regime_id, region_id)
    return f"{kind}:{result}" if result is not None else None


def _usable_capital(state: GameState, regime_id: int) -> int | None:
    capital = int(state.regimes[regime_id].get("capital") or 0)
    if capital in state.cities and city_controller(state, capital) == regime_id:
        return capital
    return None


def military_threat_strength(state: GameState, regime_id: int) -> tuple[int, list[int]]:
    """战争中合计所有敌军；和平时以接壤政权中最强的一国作为潜在威胁。"""
    war_enemies = sorted(
        {
            int(side)
            for war in state.wars
            if regime_id in {int(item) for item in war}
            for side in war
            if int(side) != regime_id and not is_regime_eliminated(state, int(side))
        }
    )

    def soldiers(target_id: int) -> int:
        return sum(
            army.soldiers for army in state.armies.values()
            if army.regime_id == target_id
        )

    if war_enemies:
        return sum(soldiers(enemy_id) for enemy_id in war_enemies), war_enemies
    border_regimes = [
        target_id for target_id in neighboring_regimes(state, regime_id)
        if target_id in state.regimes
        and not is_regime_eliminated(state, target_id)
        and target_id not in state.vassals
        and state.vassals.get(regime_id) != target_id
    ]
    if not border_regimes:
        return 0, []
    strongest = max(border_regimes, key=lambda target_id: (soldiers(target_id), -target_id))
    return soldiers(strongest), [strongest]


def expansion_assessment(state: GameState, regime_id: int) -> dict[str, int | list[int]]:
    """按实际兵力、月度收支和存款计算本次扩军规模，不设置静态军队上限。"""
    regime = state.regimes[regime_id]
    own_soldiers = sum(
        army.soldiers for army in state.armies.values()
        if army.regime_id == regime_id
    )
    threat_soldiers, threat_regimes = military_threat_strength(state, regime_id)
    at_war = bool(threat_regimes and any(state.at_war(regime_id, enemy_id) for enemy_id in threat_regimes))
    official_salary, current_pay = average_monthly_expenses(state, regime_id)
    income = regime_income(state, regime_id)
    monthly_surplus = income - official_salary - current_pay

    # 和平期保留三个月当前开支，战争期只保留一个月；其余存款分期用于支撑新增军饷。
    current_expenses = official_salary + current_pay
    safety_months = 1 if at_war else 3
    drawdown_months = 6 if at_war else 12
    spendable_treasury = max(0, int(regime.get("treasury", 0)) - current_expenses * safety_months)
    treasury_support = spendable_treasury // drawdown_months
    financial_capacity = max(
        0,
        (monthly_surplus + treasury_support) // MILITARY_PAY_PER_BATTALION,
    )

    # 面临兵力缺口时优先补足；没有直接缺口时，也会把约一半可承受预算用于扩大常备军。
    threat_gap = max(0, (threat_soldiers * 115 // 100 - own_soldiers + 999) // 1000)
    financially_driven = max(0, financial_capacity // 2)
    requested = max(threat_gap, financially_driven)
    battalions = min(9, financial_capacity, requested)
    return {
        "own_soldiers": own_soldiers,
        "threat_soldiers": threat_soldiers,
        "threat_regimes": threat_regimes,
        "income": income,
        "monthly_surplus": monthly_surplus,
        "spendable_treasury": spendable_treasury,
        "financial_capacity": financial_capacity,
        "threat_gap_battalions": threat_gap,
        "battalions": battalions,
    }


def expand_military(state: GameState, regime_id: int) -> Army | None:
    """根据动态财政与敌军压力组建一支至多九营的军队。"""
    regime = state.regimes[regime_id]
    if int(regime.get("authority", 0)) < AI_POLICY_AUTHORITY_COST:
        return None
    capital = _usable_capital(state, regime_id)
    if capital is None:
        return None
    assessment = expansion_assessment(state, regime_id)
    battalions = int(assessment["battalions"])
    if battalions <= 0:
        return None

    required = battalions * 1000
    reserve = int(regime.get("reserve_army", 0))
    shortage = max(0, required - reserve)
    shortage = ((shortage + 999) // 1000) * 1000
    conscription_cost = int(round(shortage * AI_CONSCRIPT_COST_PER_SOLDIER))
    _official_salary, current_pay = average_monthly_expenses(state, regime_id)
    next_month_expenses = _official_salary + current_pay + battalions * MILITARY_PAY_PER_BATTALION
    expected_deficit = max(0, next_month_expenses - int(assessment["income"]))
    if (
        shortage > int(regime.get("militia", 0))
        or int(regime.get("treasury", 0)) < conscription_cost + expected_deficit
    ):
        return None
    if shortage:
        regime["militia"] -= shortage
        regime["reserve_army"] = reserve + shortage
        regime["treasury"] -= conscription_cost
        state.add_log(f"{regime['name']}扩充预备役{shortage}人，国库-{conscription_cost}。")
    try:
        army = create_army(state, regime_id, capital, 0, {1: battalions})
    except ValueError:
        return None
    regime["authority"] -= AI_POLICY_AUTHORITY_COST
    state.add_log(f"{regime['name']}发布扩军政令，权威-{AI_POLICY_AUTHORITY_COST}。")
    return army


def run_administrative_actions(
    state: GameState,
    regime_id: int,
    rng: random.Random | None = None,
) -> list[str]:
    """AI反复发布行政政令；发展与扩军同时可用时各有50%权重。"""
    chooser = rng or random
    regime = state.regimes[regime_id]
    regime.setdefault("authority", AI_AUTHORITY_PER_TURN)
    actions: list[str] = []
    # 垦荒消耗50权威，其他行政行动消耗100；额外上限只用于防御异常存档数据。
    for _ in range(100):
        if int(regime.get("authority", 0)) < AI_RECLAIM_AUTHORITY_COST:
            break
        development_first = chooser.random() < AI_DEVELOPMENT_WEIGHT / (
            AI_DEVELOPMENT_WEIGHT + AI_EXPANSION_WEIGHT
        )
        if development_first:
            action = issue_best_economic_policy(state, regime_id)
            if action is not None:
                actions.append(action)
                continue
            army = expand_military(state, regime_id)
            if army is not None:
                actions.append(f"expand:{army.id}")
                continue
        else:
            army = expand_military(state, regime_id)
            if army is not None:
                actions.append(f"expand:{army.id}")
                continue
            action = issue_best_economic_policy(state, regime_id)
            if action is not None:
                actions.append(action)
                continue
        break
    return actions


def _tag_later_qin_reinforcement_pay(state: GameState, army_ids: list[int]) -> None:
    for army_id in army_ids:
        army = state.armies.get(int(army_id))
        if army is None or army.regime_id != LATER_QIN_REGIME_ID:
            continue
        if not any(int(item.get("id", 0)) == LATER_QIN_PAY_MODIFIER_ID for item in army.modifiers):
            army.modifiers.append({"id": LATER_QIN_PAY_MODIFIER_ID})


def _migrate_later_qin_reinforcement_ids(state: GameState) -> list[int]:
    stored = [
        int(army_id) for army_id in state.flags.get(LATER_QIN_REINFORCEMENT_ARMIES_FLAG, [])
        if int(army_id) in state.armies
    ]
    if stored:
        return stored
    # 兼容已经触发过408年整军的旧存档：剧情军是同批生成、无将领的五营步兵，取编号最新的十支。
    candidates = [
        army.id for army in state.armies.values()
        if army.regime_id == LATER_QIN_REGIME_ID
        and army.commander is None
        and len(army.units) == 5
        and all(int(unit.get("type", 0)) == 1 and int(unit.get("count", 0)) == 1000 for unit in army.units)
    ]
    stored = sorted(candidates, reverse=True)[:10]
    if stored:
        state.flags[LATER_QIN_REINFORCEMENT_ARMIES_FLAG] = sorted(stored)
    return stored


def ensure_later_qin_408_reinforcements(state: GameState) -> list[int]:
    """408年后秦一次性获得十支五千人陆军，不消耗预备役。"""
    if state.flags.get(LATER_QIN_REINFORCEMENT_FLAG):
        _tag_later_qin_reinforcement_pay(state, _migrate_later_qin_reinforcement_ids(state))
        return []
    if state.year < 408:
        return []
    if LATER_QIN_REGIME_ID not in state.regimes or is_regime_eliminated(state, LATER_QIN_REGIME_ID):
        return []
    capital = _usable_capital(state, LATER_QIN_REGIME_ID)
    if capital is None:
        return []
    created: list[int] = []
    for _ in range(10):
        army_id = max(state.armies, default=0) + 1
        state.armies[army_id] = Army(
            id=army_id,
            regime_id=LATER_QIN_REGIME_ID,
            army_type=0,
            units=[{"type": 1, "count": 1000} for _ in range(5)],
            commander=None,
            location_id=capital,
        )
        created.append(army_id)
    state.flags[LATER_QIN_REINFORCEMENT_FLAG] = True
    state.flags[LATER_QIN_REINFORCEMENT_ARMIES_FLAG] = list(created)
    _tag_later_qin_reinforcement_pay(state, created)
    state.add_log(
        "后秦于408年大举整军：在首都组建十支五千人军队，获得常驻15%军事修正；"
        "这些剧情军的军饷降低80%。"
    )
    return created


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


def strategic_defense_targets(state: GameState, regime_id: int) -> list[int]:
    """首都 > 各地区首府 > 高城防关隘。"""
    regime = state.regimes[regime_id]
    region_names = set(regime.get("regions", []))
    targets: list[int] = []
    capital = int(regime.get("capital") or 0)
    if capital in state.cities:
        targets.append(capital)
    regional_capitals = sorted(
        (
            city for city in state.cities.values()
            if city.get("capital") and city.get("region") in region_names and int(city["id"]) != capital
        ),
        key=lambda city: (-int(city.get("defense", 0)), int(city["id"])),
    )
    targets.extend(int(city["id"]) for city in regional_capitals)
    passes = sorted(
        (
            city for city in state.cities.values()
            if city.get("region") in region_names
            and "关" in str(city.get("name", ""))
            and int(city.get("defense", 0)) >= 50
            and int(city["id"]) not in targets
        ),
        key=lambda city: (-int(city.get("defense", 0)), int(city["id"])),
    )
    targets.extend(int(city["id"]) for city in passes)
    return targets


def defense_assignments(state: GameState, regime_id: int) -> dict[int, int]:
    """按目标优先级依次分派距离最近的一支军队。返回 army_id -> city_id。"""
    available = [army for army in state.armies.values() if army.regime_id == regime_id]
    assignments: dict[int, int] = {}
    for target in strategic_defense_targets(state, regime_id):
        if not available:
            break
        army = min(
            available,
            key=lambda item: (_road_distance(state, item.location_id, target), -item.soldiers, item.id),
        )
        assignments[army.id] = target
        available.remove(army)
    return assignments


def military_strength(state: GameState, regime_id: int) -> float:
    regime = state.regimes[regime_id]
    fielded = sum(
        army.soldiers * (0.5 + max(0, int(army.morale)) / 200)
        for army in state.armies.values()
        if army.regime_id == regime_id
    )
    return fielded + int(regime.get("reserve_army", 0)) * 0.5 + int(regime.get("militia", 0)) * 0.1


def neighboring_regimes(state: GameState, regime_id: int) -> set[int]:
    result: set[int] = set()
    for road in state.roads:
        left, right = int(road["from"]), int(road["to"])
        left_controller = city_controller(state, left)
        right_controller = city_controller(state, right)
        if left_controller == regime_id and right_controller not in {0, regime_id}:
            result.add(right_controller)
        elif right_controller == regime_id and left_controller not in {0, regime_id}:
            result.add(left_controller)
    return result


def plan_wei_invasion(state: GameState) -> int | None:
    """魏只在明显占优时侵略相邻且领土更少的小政权。"""
    if WEI_REGIME_ID not in state.regimes or is_regime_eliminated(state, WEI_REGIME_ID):
        return None
    flag_key = f"ai_invasion_target:{WEI_REGIME_ID}"
    old_target = int(state.flags.get(flag_key, 0))
    huxia_id = next(
        (int(regime_id) for regime_id, regime in state.regimes.items() if regime.get("name") == "胡夏"),
        12,
    )
    yuanjia = str(state.flags.get("content_version", "1.1")) == "1.2"
    if yuanjia and not state.flags.get("v12_wei_song_peace_concluded"):
        # 元嘉开局阶段北魏把全部战略注意力放在宋国，不建立任何第二战线。
        state.flags[flag_key] = state.player_regime_id
        return state.player_regime_id if state.at_war(WEI_REGIME_ID, state.player_regime_id) else None
    if yuanjia and state.year < 427 and old_target == huxia_id:
        state.flags.pop(flag_key, None)
        old_target = 0
    if old_target and not is_regime_eliminated(state, old_target) and state.at_war(WEI_REGIME_ID, old_target):
        huxia_ready = (
            yuanjia
            and state.year >= 427
            and old_target != huxia_id
            and huxia_id in neighboring_regimes(state, WEI_REGIME_ID)
            and not is_regime_eliminated(state, huxia_id)
            and military_strength(state, WEI_REGIME_ID) >= military_strength(state, huxia_id) * 1.15
        )
        if not huxia_ready:
            return old_target
        state.flags.pop(flag_key, None)
    state.flags.pop(flag_key, None)
    # 剧情援秦期间不另开战线；其他既有战争也优先打完。
    if state.flags.get("wei_aid_qin_active"):
        return None
    wei_regions = len(state.regimes[WEI_REGIME_ID].get("regions", []))
    wei_strength = military_strength(state, WEI_REGIME_ID)
    # 元嘉剧本的历史窗口：427年前北魏绝不主动进攻胡夏；427年起只要
    # 接壤且兵力评估允许，就把彻底吞并胡夏置于其他小国目标之前。
    neighbors = neighboring_regimes(state, WEI_REGIME_ID)
    if (
        yuanjia
        and state.year >= 427
        and huxia_id in neighbors
        and huxia_id in state.regimes
        and not is_regime_eliminated(state, huxia_id)
        and wei_strength >= military_strength(state, huxia_id) * 1.15
    ):
        pair = state.relation_pair(WEI_REGIME_ID, huxia_id)
        if pair not in state.wars:
            if int(state.regimes[WEI_REGIME_ID].get("war_support", 0)) < 50:
                return None
            declare_war(state, WEI_REGIME_ID, huxia_id)
        state.flags[flag_key] = huxia_id
        state.flags["v12_wei_huxia_annexation"] = True
        state.add_log("北魏判断吞并时机已经成熟，向胡夏宣战，并将彻底灭亡胡夏定为持续战略目标。")
        return huxia_id
    candidates = []
    for target in neighbors:
        if target not in state.regimes or is_regime_eliminated(state, target):
            continue
        if yuanjia and state.year < 427 and target == huxia_id:
            continue
        if target in state.vassals or state.vassals.get(WEI_REGIME_ID) == target:
            continue
        target_regions = len(state.regimes[target].get("regions", []))
        target_strength = military_strength(state, target)
        if target_regions >= wei_regions or wei_strength < target_strength * 1.25:
            continue
        candidates.append((target_strength, target_regions, target))
    if candidates:
        target = min(candidates)[2]
    else:
        active_enemies = [
            other
            for war in state.wars
            if WEI_REGIME_ID in war
            for other in war
            if other != WEI_REGIME_ID and not is_regime_eliminated(state, other)
        ]
        if not active_enemies:
            return None
        target = min(active_enemies, key=lambda rid: (military_strength(state, rid), rid))
    pair = state.relation_pair(WEI_REGIME_ID, target)
    if pair not in state.wars:
        if int(state.regimes[WEI_REGIME_ID].get("war_support", 0)) < 50:
            return None
        declare_war(state, WEI_REGIME_ID, target)
    state.flags[flag_key] = target
    if target == state.player_regime_id:
        state.regimes[WEI_REGIME_ID]["relation_with_main"] = "交战"
    state.add_log(f"魏评估边境力量后，决定侵略{state.regimes[target]['name']}。")
    return target


def invasion_target_city(state: GameState, target_regime_id: int) -> int | None:
    capital = int(state.regimes.get(target_regime_id, {}).get("capital") or 0)
    if capital in state.cities and city_controller(state, capital) == target_regime_id:
        return capital
    for region_id, region in state.regions.items():
        if int(region.get("controller", 0)) != target_regime_id:
            continue
        regional_capital = next(
            (
                int(city_id)
                for city_id in region.get("cities", [])
                if state.cities.get(int(city_id), {}).get("capital")
            ),
            None,
        )
        if regional_capital is not None:
            return regional_capital
    return capital if capital in state.cities else None
