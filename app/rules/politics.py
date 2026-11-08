from __future__ import annotations

import random

from ..models import GameState
from .common import RuleError, check_player_office_authority, clamp, once_per_turn, spend_authority
from .economy import calculate_region_income, regime_income
from .laws import can_dismiss_high_family, check_command_rejection, dismissal_cost, execute_stain_threshold
from .treasury import change_treasury, spend_treasury, treasury_balance


COMMAND_COPPER_COST_RATE = 0.05


def command_copper_cost(current_cost: float) -> float:
    """All decree cash costs are five percent of their previous value."""
    # Keep enough precision for per-soldier rates; the final treasury charge is
    # still rounded by each decree and by the treasury service.
    return round(float(current_cost) * COMMAND_COPPER_COST_RATE, 4)


RELIEF_COPPER_COST = command_copper_cost(300)
DEVELOP_COPPER_COST = command_copper_cost(300)
FORTIFY_COPPER_COST = command_copper_cost(300)
# 征召费用本来就是低额费用，不属于“1.1旧政令的数百铜钱固定开支”。
CONSCRIPT_COST_PER_SOLDIER = 0.02


def appoint(state: GameState, office: str, person_id: int) -> str:
    check_command_rejection(state, "appoint")
    check_player_office_authority(state, office)
    regime = state.player_regime
    internal = regime["internal"]
    if office not in internal or isinstance(internal[office], list):
        raise RuleError("该官职不可用")
    if internal[office]:
        raise RuleError("该官职已有任职者")
    if person_id not in state.persons or state.persons[person_id].get("country_id") != state.player_regime_id:
        raise RuleError("只能任命本政权人物")
    if any(value == person_id for value in internal.values() if not isinstance(value, list)):
        raise RuleError("此人已经担任官职")
    spend_authority(state, 100)
    internal[office] = person_id
    message = f"任命{state.person_name(person_id)}担任{office}。"
    state.add_log(message)
    return message


def dismiss(state: GameState, office: str) -> str:
    check_command_rejection(state, "dismiss")
    check_player_office_authority(state, office)
    internal = state.player_regime["internal"]
    if office not in internal or isinstance(internal[office], list) or not internal[office]:
        raise RuleError("该官职目前空缺")
    if office == "emperor":
        raise RuleError("皇帝不能通过普通政令卸任")
    person_id = internal[office]
    person = state.persons.get(person_id, {})
    if not can_dismiss_high_family(state, person):
        raise RuleError("当前门阀法律保护这名高门官员，不能将其卸任")
    spend_authority(state, dismissal_cost(state, person))
    internal[office] = None
    message = f"免去{state.person_name(person_id)}的职务。"
    state.add_log(message)
    return message


def appoint_governor(state: GameState, region_id: int, person_id: int) -> str:
    check_command_rejection(state, "appoint_governor")
    check_player_office_authority(state, "governor")
    region = state.regions.get(region_id)
    if not region or region.get("name") not in state.player_regime.get("regions", []):
        raise RuleError("只能任命本国地区的刺史")
    if region.get("governor"):
        raise RuleError("该地区已经有刺史")
    person = state.persons.get(person_id)
    if not person or person.get("country_id") != state.player_regime_id or person.get("status") != 1:
        raise RuleError("只能任命本政权在世人物为刺史")
    internal = state.player_regime["internal"]
    if any(value == person_id for value in internal.values() if not isinstance(value, list)):
        raise RuleError("此人已经担任中枢官职")
    if any(value == person_id for value in state.regions.values() if value.get("governor")):
        raise RuleError("此人已经担任其他地区刺史")
    capital_id = next(
        (city_id for city_id in region.get("cities", []) if state.cities.get(city_id, {}).get("capital")),
        None,
    )
    if capital_id is None:
        raise RuleError("该地区没有可用的首府")
    spend_authority(state, 100)
    region["governor"] = person_id
    person["location_id"] = capital_id
    # 文官兼任将领时，以其所率军队的位置为准。
    from .military import sync_all_commander_locations

    sync_all_commander_locations(state)
    commanded_army = next((army for army in state.armies.values() if army.commander == person_id), None)
    station = state.city_name(commanded_army.location_id) if commanded_army else state.city_name(capital_id)
    suffix = "（兼任将领，位置随军）" if commanded_army else ""
    message = f"任命{state.person_name(person_id)}为{region['name']}刺史，驻于{station}{suffix}。"
    state.add_log(message)
    return message


def temporary_tax(state: GameState) -> str:
    check_command_rejection(state, "temporary_tax")
    once_per_turn(state, "temporary_tax")
    spend_authority(state, 100)
    amount = regime_income(state, state.player_regime_id)
    change_treasury(state, state.player_regime_id, amount)
    state.player_regime["stability"] = max(0, state.player_regime["stability"] - 5)
    message = f"临时征税获得 {amount} 国库，稳定度下降 5。"
    state.add_log(message)
    return message


def relief(state: GameState, region_id: int) -> str:
    check_command_rejection(state, "relief")
    region = state.regions[region_id]
    if region.get("name") not in state.player_regime.get("regions", []):
        raise RuleError("只能赈济本国地区")
    if treasury_balance(state) < RELIEF_COPPER_COST:
        raise RuleError(f"国库不足 {RELIEF_COPPER_COST:g}")
    spend_authority(state, 100)
    spend_treasury(state, state.player_regime_id, RELIEF_COPPER_COST)
    state.player_regime["stability"] = int(clamp(state.player_regime["stability"] + 3, 0, 100))
    region["prosperity"] = int(clamp(region["prosperity"] + 2, 0, 10))
    message = f"赈济{region['name']}：稳定度 +3，繁荣度 +2。"
    state.add_log(message)
    return message


def conscript(state: GameState, amount: int) -> str:
    if amount <= 0 or amount % 1000 != 0 or amount > state.player_regime["militia"]:
        raise RuleError("征兵人数必须以1000人为单位，且不能超过现有壮丁数")
    cost = int(round(amount * CONSCRIPT_COST_PER_SOLDIER))
    if treasury_balance(state) < cost:
        raise RuleError(f"国库不足，需要 {cost}")
    check_command_rejection(state, "conscript")
    once_per_turn(state, "conscript")
    spend_authority(state, 100)
    state.player_regime["militia"] -= amount
    state.player_regime["reserve_army"] += amount
    spend_treasury(state, state.player_regime_id, cost)
    message = f"征募 {amount} 人，花费 {cost} 国库。"
    state.add_log(message)
    return message


def reclaim_land(state: GameState, region_id: int, rng: random.Random | None = None) -> str:
    """基础政令：消耗壮丁开垦十五份新土地。"""
    region = state.regions.get(region_id)
    if not region or region.get("name") not in state.player_regime.get("regions", []):
        raise RuleError("只能在本国地区垦荒")
    if int(state.player_regime.get("militia", 0)) < 500:
        raise RuleError("壮丁不足500人")
    eligible_families = [
        int(family_id)
        for family_id, family in state.families.items()
        if int(state.persons.get(int(family.get("leader") or 0), {}).get("country_id", 0)) == state.player_regime_id
    ]
    if not eligible_families:
        raise RuleError("本国没有可以分配土地的家族")
    check_command_rejection(state, "reclaim_land", rng)
    spend_authority(state, 50)
    chooser = rng or random
    family_land = [chooser.choice(eligible_families) for _ in range(5)]
    region.setdefault("land_ownership", []).extend([2] * 5 + family_land + [0] * 5)
    region["land"] = int(region.get("land", len(region["land_ownership"]) - 15)) + 15
    state.player_regime["militia"] -= 500
    message = f"在{region['name']}垦荒：土地上限+15，中央、家族、自耕农各获得5份土地。"
    state.add_log(message)
    return message


def amnesty(state: GameState) -> str:
    check_command_rejection(state, "amnesty")
    once_per_turn(state, "amnesty")
    spend_authority(state, 100)
    state.player_regime["militia"] += 2000
    state.player_regime["stability"] = max(0, state.player_regime["stability"] - 3)
    message = "颁布大赦：壮丁 +2000，稳定度 -3。"
    state.add_log(message)
    return message


def develop(state: GameState, region_id: int) -> str:
    check_command_rejection(state, "develop")
    region = state.regions[region_id]
    if region.get("name") not in state.player_regime.get("regions", []):
        raise RuleError("只能建设本国地区")
    if treasury_balance(state) < DEVELOP_COPPER_COST:
        raise RuleError(f"国库不足 {DEVELOP_COPPER_COST:g}")
    spend_treasury(state, state.player_regime_id, DEVELOP_COPPER_COST)
    region["development"] = int(clamp(region["development"] + 3, 0, 100))
    message = f"兴修{region['name']}水利：发展度 +3。"
    state.add_log(message)
    return message


def fortify(state: GameState, city_id: int) -> str:
    check_command_rejection(state, "fortify")
    once_per_turn(state, "fortify")
    city = state.cities[city_id]
    if city.get("region") not in state.player_regime.get("regions", []):
        raise RuleError("只能修筑本国城市")
    if treasury_balance(state) < FORTIFY_COPPER_COST:
        raise RuleError(f"国库不足 {FORTIFY_COPPER_COST:g}")
    spend_treasury(state, state.player_regime_id, FORTIFY_COPPER_COST)
    city["defense"] = int(clamp(city.get("defense", 0) + 5, 0, 100))
    message = f"修筑{city['name']}城防：城防提升至 {city['defense']}。"
    state.add_log(message)
    return message


def establish_heir(state: GameState, person_id: int) -> str:
    check_command_rejection(state, "establish_heir")
    internal = state.player_regime["internal"]
    if internal.get("crown_prince"):
        raise RuleError("已经册立太子")
    emperor = internal.get("emperor")
    person = state.persons.get(person_id)
    if not person or person.get("gender") != 0 or person.get("status") != 1:
        raise RuleError("储君必须是在世男性")
    is_son = person.get("father") == emperor
    imperial_family = state.persons.get(emperor, {}).get("family_id")
    if not is_son and person.get("family_id") != imperial_family:
        raise RuleError("应从皇帝之子或同族皇室男性中选择")
    spend_authority(state, 100)
    internal["crown_prince"] = person_id
    message = f"册立{state.person_name(person_id)}为太子。"
    state.add_log(message)
    return message


def judge(state: GameState, person_id: int) -> str:
    check_command_rejection(state, "judge")
    person = state.persons.get(person_id)
    if not person or person.get("status") not in {1, 2, 3}:
        raise RuleError("审判目标无效")
    threshold = execute_stain_threshold(state)
    if person.get("attributes", {}).get("stain", 0) < threshold:
        raise RuleError(f"目标污点不足 {threshold}")
    spend_authority(state, 300)
    person["status"] = 4
    person["death_year"] = state.year
    message = f"{state.person_name(person_id)}被审判处死。"
    state.add_log(message)
    return message
