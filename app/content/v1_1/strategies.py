from __future__ import annotations

from typing import Any

from ...models import GameState
from ...rules.common import RuleError, clamp


def strategy_record(
    strategy_id: int,
    name: str,
    prerequisites: list[int] | None = None,
    mutually_exclusive: list[int] | None = None,
    duration_months: int = 1,
    effect_description: str = "",
    prerequisites_any: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "id": int(strategy_id),
        "name": name,
        "prerequisites": [int(item) for item in prerequisites or []],
        "mutually_exclusive": [int(item) for item in mutually_exclusive or []],
        "duration_months": max(0, int(duration_months)),
        "effect_description": effect_description,
        "prerequisites_any": [int(item) for item in prerequisites_any or []],
    }


STRATEGY_TEMPLATES: dict[int, dict[str, Any]] = {
    1: strategy_record(1, "重振晋纲", effect_description="稳定度+10，解锁“天子反正”决议。"),
    2: strategy_record(2, "复兴北府", effect_description="解锁“组织北府军”决议及3号军事修正。"),
    3: strategy_record(3, "拉拢朝堂", [1, 2], duration_months=3, effect_description="稳定度+3，所有在世人物好感+5，解锁“十月封赏”。"),
    4: strategy_record(4, "经营江南", duration_months=5, effect_description="壮丁-10000，稳定度+5；控制的南方地区增加30份土地。"),
    5: strategy_record(5, "收复巴蜀", [1, 2], duration_months=3, effect_description="战争支持度+20，解锁5号军事修正。"),
    6: strategy_record(6, "防御南方", [1, 2], duration_months=2, effect_description="解锁山阳援军、山阴援军及海路进攻番禺决议。"),
    7: strategy_record(7, "北伐", [1, 2], duration_months=3, effect_description="对北态度变为第4级，所有本国军队士气回满。"),
    8: strategy_record(8, "对燕作战", [7], duration_months=2, effect_description="获得一次无视好感向南燕宣战的机会。"),
    9: strategy_record(9, "提拔新秀", [8], duration_months=3, effect_description="刘裕基础权力+15，解锁“羽葆鼓吹”及北府新秀军事修正。"),
    10: strategy_record(10, "寒人主政", [3], [11], 3, "解锁“寒人主政”决议。"),
    11: strategy_record(11, "结交门阀", [3], [10], 3, "解锁“结交门阀”决议。"),
    12: strategy_record(12, "任用文官班子", duration_months=3, effect_description="解锁“任用文官班子”决议。", prerequisites_any=[10, 11]),
    13: strategy_record(13, "清扫反对派", duration_months=3, effect_description="稳定度+5，解锁处决刘毅和处决诸葛长民。", prerequisites_any=[10, 11]),
    14: strategy_record(14, "开发扬州", [4], duration_months=3, effect_description="扬州增加40份土地：中央15、世家15、自耕农10。"),
    15: strategy_record(15, "开发荆州", [4], duration_months=3, effect_description="荆州增加40份土地：中央15、世家15、自耕农10。"),
    16: strategy_record(16, "开发益州", [4], duration_months=3, effect_description="益州增加40份土地：中央15、世家15、自耕农10。"),
    17: strategy_record(17, "加固建康", [14], duration_months=3, effect_description="解锁“加固建康”决议。"),
    18: strategy_record(18, "检籍土断", [14, 15, 16, 10], duration_months=3, effect_description="经济基础切换为检籍土断，稳定度+10，并获得2号国家修正。"),
    19: strategy_record(19, "门阀北府兵", [9, 11], duration_months=3, effect_description="解锁“组织门阀北府兵”决议。"),
    20: strategy_record(20, "对秦作战", [9], duration_months=3, effect_description="战争支持度+10，并获得一次无视好感向后秦宣战的机会。"),
    # 文档中“对秦作战”和“权臣之路”均标作20号；运行配置顺延后者，保证编号唯一。
    21: strategy_record(21, "权臣之路", [12, 13], duration_months=3, effect_description="解锁剑履上殿、入朝不趋、赞拜不名等决议。"),
    22: strategy_record(22, "九锡之礼", [21, 20], duration_months=3, effect_description="权力分配切换为权臣政治，解锁废立、九锡与登基决议。"),
}


def ensure_strategy_records(state: GameState) -> None:
    for strategy_id, template in STRATEGY_TEMPLATES.items():
        existing = state.strategies.get(strategy_id, {})
        state.strategies[strategy_id] = {
            **template,
            "status": existing.get("status", "available")
            if existing.get("status", "available") in {"available", "in_progress", "paused", "completed"}
            else "available",
            "progress_months": int(existing.get("progress_months", 0)),
            "started_turn": existing.get("started_turn"),
            **({"pause_reason": existing["pause_reason"]} if existing.get("pause_reason") else {}),
        }


def strategy_completed(state: GameState, strategy_id: int) -> bool:
    ensure_strategy_records(state)
    return state.strategies.get(strategy_id, {}).get("status") == "completed"


def strategy_genealogy(state: GameState) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    """Return graph nodes, current availability, and prerequisite edges."""
    ensure_strategy_records(state)
    sync_strategy_statuses(state)
    nodes = [
        {
            "id": int(strategy_id),
            "name": str(strategy["name"]),
            "completed": strategy.get("status") == "completed",
            "status": str(strategy.get("status", "available")),
            "executable": _strategy_available_impl(state, int(strategy_id))[0],
            "reason": _strategy_available_impl(state, int(strategy_id))[1],
        }
        for strategy_id, strategy in sorted(state.strategies.items())
    ]
    edges = [
        (int(prerequisite), int(strategy_id))
        for strategy_id, strategy in sorted(state.strategies.items())
        for prerequisite in strategy.get("prerequisites", []) + strategy.get("prerequisites_any", [])
        if int(prerequisite) in state.strategies
    ]
    return nodes, edges


def strategy_mutual_exclusions(state: GameState) -> list[tuple[int, int]]:
    """Return each mutual-exclusion relationship once for graph rendering."""
    ensure_strategy_records(state)
    pairs = {
        tuple(sorted((int(strategy_id), int(other))))
        for strategy_id, strategy in state.strategies.items()
        for other in strategy.get("mutually_exclusive", [])
        if int(other) in state.strategies and int(other) != int(strategy_id)
    }
    return sorted(pairs)


def active_strategy(state: GameState) -> dict[str, Any] | None:
    ensure_strategy_records(state)
    sync_strategy_statuses(state)
    return next(
        (item for item in state.strategies.values() if item.get("status") in {"in_progress", "paused"}),
        None,
    )


def strategy_requirements_met(state: GameState, strategy_id: int) -> tuple[bool, str]:
    """Check prerequisites that must remain true throughout a strategy."""
    ensure_strategy_records(state)
    strategy = state.strategies.get(strategy_id)
    if not strategy:
        return False, "经略不存在"
    missing = [item for item in strategy["prerequisites"] if not strategy_completed(state, int(item))]
    if missing:
        return False, "前置经略尚未完成"
    alternatives = [int(item) for item in strategy.get("prerequisites_any", [])]
    if alternatives and not any(strategy_completed(state, item) for item in alternatives):
        return False, "需要完成任一前置经略"
    excluded = [item for item in strategy["mutually_exclusive"] if strategy_completed(state, int(item))]
    if excluded:
        return False, "互斥经略已经完成"
    if strategy_id == 3 and not bool(state.events.get(3, {}).get("triggered")):
        return False, "需要事件“瓜分荆楚”已经发生"
    if strategy_id == 4 and int(state.player_regime.get("militia", 0)) < 10000:
        return False, "需要至少10000壮丁"
    if strategy_id == 5 and not bool(state.events.get(4, {}).get("triggered")):
        return False, "需要事件“谯蜀增防”已经发生"
    if strategy_id == 6 and not state.at_war(state.player_regime_id, 5):
        return False, "需要正在与卢循交战"
    if strategy_id == 7:
        if int(state.player_regime.get("war_support", 0)) <= 50:
            return False, "战争支持度必须大于50"
        if int(state.player_regime.get("stability", 0)) <= 50:
            return False, "稳定度必须大于50"
    if strategy_id == 9:
        owned = set(state.player_regime.get("regions", []))
        if not {"徐州", "青州"} <= owned:
            return False, "需要法理拥有徐州和青州"
    if strategy_id in {10, 11}:
        if state.year < 412:
            return False, "需要到公元412年"
        from ...rules.common import person_power

        if person_power(state, state.player) < 1000:
            return False, "刘裕权力需要达到1000"
    if strategy_id in {14, 15, 17}:
        region_name = {14: "扬州", 15: "荆州", 17: "益州"}[strategy_id]
        region = next((item for item in state.regions.values() if item.get("name") == region_name), None)
        if not region or region_name not in state.player_regime.get("regions", []):
            return False, f"需要法理拥有{region_name}"
        if int(region.get("controller", 0)) != state.player_regime_id:
            return False, f"需要实际控制{region_name}"
    if strategy_id == 20:
        qin = next((item for item in state.regimes.values() if item.get("name") == "后秦"), None)
        if qin and not state.at_war(state.player_regime_id, int(qin["id"])):
            from ...rules.common import is_regime_eliminated

            if not is_regime_eliminated(state, int(qin["id"])):
                return True, "前置条件满足"
    if strategy_id in {21, 22}:
        from ...rules.common import person_power

        required = 1200 if strategy_id == 21 else 1800
        if person_power(state, state.player) < required:
            return False, f"刘裕权力需要达到{required}"
    return True, "前置条件满足"


def sync_strategy_statuses(state: GameState) -> None:
    """Pause or resume the sole active strategy as its prerequisites change."""
    ensure_strategy_records(state)
    for strategy_id, strategy in sorted(state.strategies.items()):
        status = strategy.get("status")
        if status not in {"in_progress", "paused"}:
            continue
        met, reason = strategy_requirements_met(state, int(strategy_id))
        # 前置检查会兼容性补齐经略记录，因此重新取得当前字典对象。
        strategy = state.strategies[int(strategy_id)]
        status = strategy.get("status")
        if not met and status != "paused":
            strategy["status"] = "paused"
            strategy["pause_reason"] = reason
            state.add_log(f"经略暂停：{strategy['name']}。{reason}。")
        elif met and status == "paused":
            strategy["status"] = "in_progress"
            strategy.pop("pause_reason", None)
            state.add_log(f"经略恢复：{strategy['name']}。")


def _strategy_available_impl(state: GameState, strategy_id: int) -> tuple[bool, str]:
    strategy = state.strategies.get(strategy_id)
    if not strategy:
        return False, "经略不存在"
    if strategy.get("status") == "completed":
        return False, "已经完成"
    if strategy.get("status") == "in_progress":
        return False, "正在推进"
    if strategy.get("status") == "paused":
        return False, f"已暂停：{strategy.get('pause_reason', '前置条件不满足')}"
    if any(
        item.get("status") in {"in_progress", "paused"}
        for item in state.strategies.values()
    ):
        return False, "同时只能推进一项经略"
    return strategy_requirements_met(state, strategy_id)


def strategy_available(state: GameState, strategy_id: int) -> tuple[bool, str]:
    ensure_strategy_records(state)
    sync_strategy_statuses(state)
    available, reason = _strategy_available_impl(state, strategy_id)
    return (available, "可以开始" if available else reason)


def start_strategy(state: GameState, strategy_id: int) -> str:
    if state.phase_index != 0:
        raise RuleError("只能在政治阶段开始经略")
    available, reason = strategy_available(state, strategy_id)
    if not available:
        raise RuleError(reason)
    strategy = state.strategies[strategy_id]
    if strategy_id == 8 and state.at_war(state.player_regime_id, 8):
        strategy["status"] = "completed"
        strategy["progress_months"] = 0
        strategy["started_turn"] = state.turn_number
        message = "当前已与南燕交战，经略“对燕作战”立即完成，不获得额外宣战机会。"
        state.add_log(message)
        return message
    if strategy_id == 20:
        from ...rules.common import is_regime_eliminated

        qin = next((item for item in state.regimes.values() if item.get("name") == "后秦"), None)
        if not qin or is_regime_eliminated(state, int(qin["id"])) or state.at_war(state.player_regime_id, int(qin["id"])):
            strategy["status"] = "completed"
            strategy["progress_months"] = 0
            strategy["started_turn"] = state.turn_number
            message = "后秦已经灭亡或双方正在交战，经略“对秦作战”直接完成，不获得额外宣战机会。"
            state.add_log(message)
            return message
    strategy["status"] = "in_progress"
    strategy["progress_months"] = 0
    strategy["started_turn"] = state.turn_number
    strategy.pop("pause_reason", None)
    message = f"开始经略“{strategy['name']}”，预计{strategy['duration_months']}个月完成。"
    state.add_log(message)
    return message


def cancel_strategy(state: GameState, strategy_id: int) -> str:
    if state.phase_index != 0:
        raise RuleError("只能在政治阶段取消经略")
    ensure_strategy_records(state)
    strategy = state.strategies.get(strategy_id)
    if not strategy or strategy.get("status") not in {"in_progress", "paused"}:
        raise RuleError("该经略当前没有执行")
    strategy["status"] = "available"
    strategy["progress_months"] = 0
    strategy["started_turn"] = None
    strategy.pop("pause_reason", None)
    message = f"已取消经略“{strategy['name']}”，此前进度全部清零。"
    state.add_log(message)
    return message


def _apply_strategy_effect(state: GameState, strategy_id: int) -> None:
    if strategy_id == 1:
        state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) + 10, 0, 100))
    elif strategy_id == 3:
        state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) + 3, 0, 100))
        for person in state.persons.values():
            if int(person.get("status", 0)) in {1, 2, 3}:
                person["opinion_of_player"] = int(clamp(person.get("opinion_of_player", 0) + 5, -100, 100))
    elif strategy_id == 4:
        state.player_regime["militia"] = max(0, int(state.player_regime.get("militia", 0)) - 10000)
        state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) + 5, 0, 100))
        for region_id, region in state.regions.items():
            if 1 <= int(region_id) <= 12 and int(region.get("controller", 0)) == state.player_regime_id:
                region.setdefault("land_ownership", []).extend([2] * 15 + [0] * 15)
    elif strategy_id == 5:
        cap = 50 if int(state.laws.get("north", 1)) == 1 else 100
        state.player_regime["war_support"] = min(cap, int(state.player_regime.get("war_support", 0)) + 20)
    elif strategy_id == 7:
        state.laws["north"] = 4
        for army in state.armies.values():
            if army.regime_id == state.player_regime_id:
                army.morale = 100
    elif strategy_id == 8:
        state.flags["yan_free_declaration_available"] = True
    elif strategy_id == 9:
        attributes = state.player.setdefault("attributes", {})
        attributes["base_power"] = max(0, int(attributes.get("base_power", 0)) + 15)
    elif strategy_id == 13:
        state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) + 5, 0, 100))
    elif strategy_id in {14, 15, 16}:
        region_name = {14: "扬州", 15: "荆州", 16: "益州"}[strategy_id]
        region = next(item for item in state.regions.values() if item.get("name") == region_name)
        high_families = [
            int(family_id)
            for family_id, family in sorted(state.families.items())
            if int(family.get("family_type", -1)) == 1
        ]
        family_land = [high_families[index % len(high_families)] for index in range(15)] if high_families else [2] * 15
        region.setdefault("land_ownership", []).extend([0] * 15 + family_land + [2] * 10)
        region["land"] = int(region.get("land", 0)) + 40
    elif strategy_id == 18:
        state.laws["economy"] = 2
        values_cap = {1: 50, 2: 70}.get(int(state.laws.get("values", 1)), 100)
        state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) + 10, 0, values_cap))
        liu_muzhi = next((person for person in state.persons.values() if state.person_name(int(person["id"])) == "刘穆之"), None)
        if liu_muzhi:
            attrs = liu_muzhi.setdefault("attributes", {})
            attrs["base_power"] = min(100, int(attrs.get("base_power", 0)) + 10)
        for person in state.persons.values():
            family = state.families.get(int(person.get("family_id") or 0), {})
            if int(family.get("family_type", -1)) == 1:
                person["opinion_of_player"] = int(clamp(person.get("opinion_of_player", 0) - 5, -100, 100))
    elif strategy_id == 20:
        cap = 50 if int(state.laws.get("north", 1)) == 1 else 100
        state.player_regime["war_support"] = min(cap, int(state.player_regime.get("war_support", 0)) + 10)
        state.flags["qin_free_declaration_available"] = True
    elif strategy_id == 22:
        state.laws["power"] = 3


def settle_strategies(state: GameState) -> list[int]:
    """Advance active strategies once during monthly settlement."""
    ensure_strategy_records(state)
    sync_strategy_statuses(state)
    completed: list[int] = []
    for strategy_id in sorted(state.strategies):
        strategy = state.strategies[strategy_id]
        if strategy.get("status") != "in_progress":
            continue
        strategy["progress_months"] = int(strategy.get("progress_months", 0)) + 1
        if strategy["progress_months"] < int(strategy["duration_months"]):
            continue
        strategy["status"] = "completed"
        _apply_strategy_effect(state, strategy_id)
        completed.append(strategy_id)
        state.add_log(f"经略完成：{strategy['name']}。{strategy['effect_description']}")
    return completed
