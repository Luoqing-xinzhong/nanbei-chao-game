from __future__ import annotations

from ..constants import AUTHORITY_CAP, OFFICE_NAMES, PHASES
from ..models import GameState
from . import ai
from .common import clamp, is_regime_eliminated, person_power, remove_emperor_civil_offices
from .economy import projected_expenses, regime_income, regime_militia_growth
from .laws import (
    apply_monthly_effects,
    enact_ready_legislation,
    gentry_militia_loss_rate,
    settle_legislation,
    war_support_loss,
)
from .political_events import check_coup_defeat, check_rebellions, run_party_phase, settle_coups


CHINESE_NUMBERS = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}
MONTH_NAMES = {1: "正月", 2: "二月", 3: "三月", 4: "四月", 5: "五月", 6: "六月", 7: "七月", 8: "八月", 9: "九月", 10: "十月", 11: "冬月", 12: "腊月"}


def reign_year_text(year: int, era_name: str = "元兴", era_start_year: int = 402) -> str:
    n = max(1, year - era_start_year + 1)
    chinese = "元" if n == 1 else CHINESE_NUMBERS.get(n, str(n))
    return f"{era_name}{chinese}年"


def calendar_text(state: GameState) -> str:
    era_name = str(state.flags.get("era_name", "元兴"))
    era_start_year = int(state.flags.get("era_start_year", 402))
    return f"公元{state.year}年　{reign_year_text(state.year, era_name, era_start_year)}　{MONTH_NAMES.get(state.month, f'{state.month}月')}"


def _settle_regime(state: GameState, regime_id: int) -> None:
    if is_regime_eliminated(state, regime_id):
        return
    regime = state.regimes[regime_id]
    income = regime_income(state, regime_id)
    official_salary, military_pay = projected_expenses(state, regime_id)
    regime["treasury"] += income - official_salary - military_pay
    if regime["treasury"] < 0:
        regime["treasury"] = 0
        loss = war_support_loss(state, regime_id, 5)
        regime["war_support"] = int(clamp(regime.get("war_support", 0) - loss, 0, 100))
    if regime["treasury"] == 0:
        dissolved = []
        for army in list(state.armies.values()):
            if army.regime_id != regime_id:
                continue
            army.morale = max(0, int(army.morale) - 5)
            if army.morale == 0:
                dissolved.append(army.id)
                del state.armies[army.id]
        regime["stability"] = int(clamp(regime.get("stability", 0) - 3, 0, 100))
        if regime_id == state.player_regime_id:
            state.add_log(
                "国库枯竭，军饷停发：全军士气-5，稳定度-3。"
                + (f"军队{'、'.join('#' + str(item) for item in dissolved)}原地解散。" if dissolved else "")
            )
            if regime["stability"] == 0:
                state.flags["game_over"] = True
                state.flags["game_over_reason"] = "国库枯竭引发政权崩溃，稳定度降至0。"
    militia_before = max(0, int(regime.get("militia", 0)))
    militia_loss = int(militia_before * gentry_militia_loss_rate(state, regime_id))
    militia_gain = regime_militia_growth(state, regime_id)
    regime["militia"] = max(0, militia_before - militia_loss + militia_gain)
    if regime_id == state.player_regime_id:
        militia_text = f"壮丁 +{militia_gain}"
        if militia_loss:
            militia_text += f"，门阀地位额外流失 -{militia_loss}"
        state.add_log(f"月度结算：收入 {income}，官俸 {official_salary}，军饷 {military_pay}，{militia_text}。")


def remove_eliminated_regime_armies(state: GameState) -> dict[int, list[int]]:
    """结算时清除已经失去全部法理土地的政权所遗留的军队。"""
    removed: dict[int, list[int]] = {}
    for army_id, army in list(state.armies.items()):
        regime_id = int(army.regime_id)
        if not is_regime_eliminated(state, regime_id):
            continue
        removed.setdefault(regime_id, []).append(int(army_id))
        del state.armies[army_id]
    for regime_id, army_ids in removed.items():
        regime = state.regimes.get(regime_id, {})
        regime_name = str(regime.get("name", f"政权{regime_id}"))
        state.add_log(f"灭亡政权残军清理：{regime_name}失去全部土地，清除{len(army_ids)}支军队。")
    return removed


def remove_dead_court_officials(state: GameState) -> dict[int, dict[str, list[int]]]:
    """新回合开始时解除所有已故人物在各政权朝堂中的职务。"""
    removed: dict[int, dict[str, list[int]]] = {}
    for regime_id, regime in state.regimes.items():
        internal = regime.get("internal", {})
        for office, occupant in list(internal.items()):
            if isinstance(occupant, list):
                dead_ids = [
                    int(person_id) for person_id in occupant
                    if int(state.persons.get(int(person_id), {}).get("status", 0)) == 4
                ]
                if dead_ids:
                    internal[office] = [person_id for person_id in occupant if int(person_id) not in dead_ids]
                    removed.setdefault(int(regime_id), {})[office] = dead_ids
            elif isinstance(occupant, int) and int(state.persons.get(occupant, {}).get("status", 0)) == 4:
                internal[office] = None
                removed.setdefault(int(regime_id), {})[office] = [int(occupant)]
    extra_names = {
        "inner_court": "内廷",
        "empress_dowager": "皇太后",
        "empress": "皇后",
        "noble_consort": "贵妃",
        "shuyi": "淑仪",
        "crown_prince": "太子",
        "princes": "皇子",
    }
    for regime_id, offices in removed.items():
        details = []
        for office, person_ids in offices.items():
            office_name = OFFICE_NAMES.get(office, extra_names.get(office, office))
            details.extend(f"{state.person_name(person_id)}（{office_name}）" for person_id in person_ids)
        regime_name = state.regimes.get(regime_id, {}).get("name", f"政权{regime_id}")
        state.add_log(f"回合开始：{regime_name}解除已故任职者：{'、'.join(details)}。")
    return removed


def remove_dead_confidants(state: GameState) -> list[int]:
    """及时从亲信名单中移除已经死亡的人物。"""
    dead = [
        int(person_id) for person_id in state.confidants
        if int(state.persons.get(int(person_id), {}).get("status", 0)) == 4
    ]
    if not dead:
        return []
    dead_set = set(dead)
    state.confidants[:] = [person_id for person_id in state.confidants if int(person_id) not in dead_set]
    state.add_log("清除已故亲信：" + "、".join(state.person_name(person_id) for person_id in dead) + "。")
    return dead


def remove_dead_appointments(state: GameState) -> dict[str, object]:
    """新回合开始时统一解除亡者的官职、刺史、军队将领和政党领袖身份。"""
    for regime_id in state.regimes:
        remove_emperor_civil_offices(state, int(regime_id))
    court = remove_dead_court_officials(state)
    confidants = remove_dead_confidants(state)
    governors: dict[int, int] = {}
    commanders: dict[int, int] = {}
    party_leaders: dict[int, int] = {}
    school_officials: dict[int, int] = {}

    for region_id, region in state.regions.items():
        person_id = int(region.get("governor") or 0)
        if person_id and int(state.persons.get(person_id, {}).get("status", 0)) == 4:
            governors[int(region_id)] = person_id
            region["governor"] = None

    for army_id, army in state.armies.items():
        person_id = int(army.commander or 0)
        # 部分死亡事件会先移除将领；此时仍需清掉特权法律遗留的不可卸任锁。
        if not person_id:
            army.commander_locked = False
            continue
        if person_id and int(state.persons.get(person_id, {}).get("status", 0)) == 4:
            commanders[int(army_id)] = person_id
            army.commander = None
            army.commander_locked = False

    for party_id, party in state.parties.items():
        person_id = int(party.get("leader") or 0)
        if not person_id or int(state.persons.get(person_id, {}).get("status", 0)) != 4:
            continue
        party_leaders[int(party_id)] = person_id
        party["leader"] = None
        party["members"] = [
            member_id for member_id in party.get("members", [])
            if int(member_id) != person_id
        ]
        party["supported_families"] = []
        coup = party.get("coup")
        if coup and not coup.get("special_jiankang") and int(coup.get("leader") or 0) == person_id:
            party.pop("coup", None)

    if str(state.flags.get("rules_version", "")) == "1.3":
        for records in state.flags.get("v13_culture", {}).get("buildings", {}).values():
            for building in records:
                person_id = int(building.get("official") or 0)
                if person_id and int(state.persons.get(person_id, {}).get("status", 0)) == 4:
                    school_officials[int(building.get("id", 0))] = person_id
                    building["official"] = None

    if governors:
        details = "、".join(
            f"{state.person_name(person_id)}（{state.regions[region_id].get('name', f'地区{region_id}')}刺史）"
            for region_id, person_id in governors.items()
        )
        state.add_log(f"回合开始：解除已故刺史：{details}。")
    if commanders:
        details = "、".join(
            f"{state.person_name(person_id)}（军队#{army_id}）"
            for army_id, person_id in commanders.items()
        )
        state.add_log(f"回合开始：解除已故将领：{details}。")
    if party_leaders:
        details = "、".join(
            f"{state.person_name(person_id)}（{state.parties[party_id].get('name', f'政党{party_id}')}）"
            for party_id, person_id in party_leaders.items()
        )
        state.add_log(f"回合开始：清除已故政党领袖：{details}。")

    return {
        "court": court,
        "governors": governors,
        "commanders": commanders,
        "party_leaders": party_leaders,
        "school_officials": school_officials,
        "confidants": confidants,
    }


def settle_turn(state: GameState) -> None:
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        _settle_turn_v12(state)
        return
    from .national_modifiers import apply_national_modifier_settlement

    apply_national_modifier_settlement(state)
    remove_eliminated_regime_armies(state)
    for regime_id in state.regimes:
        _settle_regime(state, regime_id)
    apply_monthly_effects(state)
    settle_legislation(state)
    from ..content.v1_1.strategies import settle_strategies

    settle_strategies(state)
    _mark_scenario_transition_if_due(state)
    settle_coups(state)
    check_rebellions(state)
    for army in state.armies.values():
        army.action_points = army.max_action_points
        army.rewarded_this_turn = False
        army.commander_changed_this_turn = False
    from .military import sync_all_commander_locations

    sync_all_commander_locations(state)
    # 主控权力以及中书官员是权威主要来源；无任职者时也保留最低恢复。
    player_power = person_power(state, state.player)
    internal = state.player_regime.get("internal", {})
    bonus = 0
    for office in ("zhongshu_ling", "zhongshu_shilang"):
        person = state.persons.get(internal.get(office))
        if person:
            bonus += person.get("attributes", {}).get("intelligence", 0)
    state.authority = min(AUTHORITY_CAP, state.authority + int(max(100, player_power * 0.05 + bonus)))
    from .ai_strategy import grant_ai_authority

    grant_ai_authority(state)
    for person in state.persons.values():
        if person.get("status") == 0 and person.get("birth_year") == state.year:
            person["status"] = 1
            state.add_log(f"{state.person_name(person['id'])}出生。")
    state.month += 1
    if state.month > 12:
        state.month = 1
        state.year += 1
    from ..content.v1_1.events_4 import settle_natural_deaths

    settle_natural_deaths(state)
    state.turn_number += 1
    state.phase_index = 0
    state.diplomatic_actions.clear()
    enact_ready_legislation(state)
    check_coup_defeat(state)
    state.add_log(f"第 {state.turn_number} 回合开始：{calendar_text(state)}。")
    from ..content.v1_1.events import queue_start_of_turn_events

    queue_start_of_turn_events(state)
    # 先让死亡剧情读取人物生前职务，再在玩家取得新回合操作权之前腾空职位。
    remove_dead_appointments(state)


def _settle_turn_v12(state: GameState) -> None:
    """Independent monthly settlement for the 1.2 economy and local systems."""
    from ..content.runtime import queue_start_of_turn_events
    from ..content.v1_1.events_4 import settle_natural_deaths
    from ..content.v1_2.economy import settle_month, start_market_turn
    from .ai_strategy import grant_ai_authority
    from .military import remove_empty_armies, sync_all_commander_locations

    remove_eliminated_regime_armies(state)
    settle_month(state)
    apply_monthly_effects(state)
    settle_legislation(state)
    if str(state.flags.get("rules_version", "")) != "1.3":
        from ..content.v1_2.strategies import settle_strategies

        settle_strategies(state)
    # 1.2/1.3子剧本都走本结算函数。结束标记必须在这里生成；此前它只
    # 写在普通结算分支中，导致元嘉之治越过433年后仍能照常推进。
    _mark_scenario_transition_if_due(state)
    remove_empty_armies(state)
    for army in state.armies.values():
        army.action_points = army.max_action_points
        army.rewarded_this_turn = False
        army.commander_changed_this_turn = False
    sync_all_commander_locations(state)

    player_power = person_power(state, state.player)
    internal = state.player_regime.get("internal", {})
    office_bonus = sum(
        int(state.persons.get(int(internal.get(office) or 0), {}).get("attributes", {}).get("intelligence", 0))
        for office in ("zhongshu_ling", "zhongshu_shilang")
    )
    authority_gain = int(max(100, player_power * 0.05 + office_bonus))
    if any(int(item.get("id", 0)) == 1201 for item in state.national_modifiers):
        authority_gain = max(1, int(authority_gain * 0.5))
        state.player_regime["stability"] = min(60, int(state.player_regime.get("stability", 0)))
    if any(int(item.get("id", 0)) == 1202 for item in state.national_modifiers):
        authority_gain += 5
        yangzhou = next((r for r in state.regions.values() if r.get("name") == "扬州"), None)
        if yangzhou:
            from ..content.v1_2.economy import region_economy

            record = region_economy(state, int(yangzhou["id"]))
            record["control"] = min(100, int(record.get("control", 0)) + 1)
    if any(int(item.get("id", 0)) in {1203, 1204} for item in state.national_modifiers):
        authority_gain = int(authority_gain * 1.1)
    state.authority = min(AUTHORITY_CAP, state.authority + authority_gain)
    grant_ai_authority(state)

    for person in state.persons.values():
        if int(person.get("status", 0)) == 0 and int(person.get("birth_year", 0) or 0) == state.year:
            person["status"] = 1
            state.add_log(f"{state.person_name(int(person['id']))}出生。")
    state.month += 1
    if state.month > 12:
        state.month = 1
        state.year += 1
    settle_natural_deaths(state)
    state.turn_number += 1
    start_market_turn(state)
    state.phase_index = 0
    state.diplomatic_actions.clear()
    enact_ready_legislation(state)
    state.add_log(f"第 {state.turn_number} 回合开始：{calendar_text(state)}。")
    queue_start_of_turn_events(state)
    from ..content.v1_2.climate import queue_march_climate_report

    queue_march_climate_report(state)
    remove_dead_appointments(state)
    from ..content.v1_2.economy import auto_fill_vacant_offices

    auto_fill_vacant_offices(state)


def _mark_scenario_transition_if_due(state: GameState) -> dict | None:
    """Mark a completed sub-scenario at its final December settlement."""
    scenario_id = str(state.flags.get("scenario_id", ""))
    rules_version = str(state.flags.get("rules_version", ""))
    transition: dict | None = None
    if rules_version == "1.3" and scenario_id == "wenjiao_south" and (state.year, state.month) == (446, 12):
        transition = {"source": "wenjiao_south", "target": "blood_tears", "year": 446}
    elif scenario_id == "yuanjia_governance" and (state.year, state.month) == (433, 12):
        transition = {"source": "yuanjia_governance", "target": "wenjiao_south", "year": 433}
    if transition is not None:
        state.flags["v13_transition_ready"] = transition
        state.add_log("本子剧本最终月份结算完成，等待保存结算存档或继承下一子剧本。")
    return transition


def advance_phase(
    state: GameState,
) -> str:
    from .military import remove_empty_armies

    if state.flags.get("v13_transition_ready"):
        return "本子剧本已经结算，必须先保存结算存档或继承下一子剧本。"
    remove_empty_armies(state)
    remove_dead_confidants(state)
    old = state.phase
    phase_name = state.phase
    ai_phase = {"政治阶段": 0, "谋划阶段": 1, "外交阶段": 2, "军事阶段": 3}.get(phase_name)
    if ai_phase is not None:
        ai.run_phase(state, ai_phase)
    if phase_name == "谋划阶段" and str(state.flags.get("content_version", "1.1")) != "1.2":
        run_party_phase(state)
    if state.phase_index == len(state.phase_names) - 1:
        settle_turn(state)
        return f"{old}结束，完成月度结算，进入{state.phase}。"
    state.phase_index += 1
    return f"{old}结束，进入{state.phase}。"
