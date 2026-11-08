from __future__ import annotations

import random
from dataclasses import dataclass

from ...models import GameState
from ...rules.common import RuleError, clamp
from ...rules.treasury import spend_treasury, treasury_balance
from .economy import local_economic_actions_allowed, population_units, region_economy, warehouse_capacity
from .events import _army, _change_local, _change_person, _city, _person, _region, is_person_available, occurred, queue_story_event
from .story_texts import story_name, story_text, story_variant
from .strategies import strategy_completed


def _template(decision_id: int, name: str, unlock: int | None, effect: str, choices=()) -> dict:
    return {"id": decision_id, "name": name, "unlock_strategy": unlock, "summary": effect, "effect_description": effect, "text": story_text("决议", decision_id, effect), "choices": list(choices), "choice_prompt": "请选择"}


DECISION_TEMPLATES = {
    1: _template(1, "厚赏顾命", None, "权威-100；顾命大臣好感度+15，稳定度+5，刘义符基础权力-5。"),
    2: _template(2, "整顿宫禁", 2, "权威-100；整顿建康宫禁，低控制度时可能失败。"),
    3: _template(3, "申明顾命", 3, "顾命集团好感提高，稳定度+5，刘义符基础权力-5。"),
    4: _template(4, "亲阅台省", 5, "70%成功强化刘义符，失败则激化政变。"),
    5: _template(5, "大赦天下", None, "权威-100；稳定度与宋臣好感提高。"),
    6: _template(6, "重定台省班次", 9, "提高元嘉近臣基础权力。"),
    7: _template(7, "收徐羡之权柄", 10, "80%成功解除徐羡之官职，失败则触发特殊政变。"),
    8: _template(8, "处置傅亮", 10, "解除傅亮官职并令其退隐，失败可能逃往荆州。"),
    9: _template(9, "重置荆州刺史", 15, "选择新的荆州刺史。", ("刘义恭", "王弘", "到彦之", "暂不任命")),
    10: _template(10, "赈济北归流民", 11, "消耗20粮、50铜钱，目标州20%流民转农，稳定度+8。", ("选择地区",)),
    11: _template(11, "建康转运仓", 13, "消耗100铜钱，扩建扬州州库；地区方针发往首都的粮运损耗减半。"),
    12: _template(12, "官府平粜", 14, "向高粮价市场投放最多20粮，稳定度+3。"),
    13: _template(13, "分遣宗室刺史", 19, "选择宗室担任目标州刺史。", ("刘义恭", "刘义宣", "刘义季", "刘义庆")),
    14: _template(14, "开放江淮互市", 23, "持续24个月降低价格波动、增加商人并提高稳定度。"),
    15: _template(15, "第一次元嘉北伐", 24, "向魏宣战，在徐州、淮北组建北伐军。"),
    16: _template(16, "修复河南仓廪", 25, "消耗100铜钱、20粮，修复中原仓廪。"),
    17: _template(17, "檀道济北援", 26, "组建援军并获得唱筹量沙军事修正。"),
    18: _template(18, "主动收兵", None, "结束北伐或选择再战一年。", ("收兵议和", "再战一年")),
}


@dataclass(frozen=True)
class DecisionResult:
    name: str
    summary: str
    text: str
    effect_description: str


def completed_decisions(state: GameState) -> list[int]:
    return [int(x) for x in state.flags.setdefault("completed_decisions", [])]


def decision_choices(state: GameState, decision_id: int) -> list[str]:
    choices = list(DECISION_TEMPLATES[decision_id].get("choices", []))
    if decision_id == 9:
        return [choice for choice in choices if choice == "暂不任命" or is_person_available(state, choice)]
    if decision_id == 10:
        return [
            str(region["name"])
            for region in state.regions.values()
            if int(region.get("controller", 0)) == 1
            and (
                sum(1 for unit in population_units(state, int(region["id"])) if unit.get("occupation") == "refugee")
                / max(1, len(population_units(state, int(region["id"]))))
            ) >= 0.15
            and float(region_economy(state, int(region["id"]))["warehouse"].get("food", 0)) >= 20
            and treasury_balance(state, state.player_regime_id) >= 50
        ]
    if decision_id == 13:
        appointed = {int(region.get("governor") or 0) for region in state.regions.values()}
        people = [name for name in choices if is_person_available(state, name) and int(_person(state, name)["id"]) not in appointed]
        regions = [str(region["name"]) for region in state.regions.values() if int(region.get("controller", 0)) == 1]
        return [f"{name} → {region}" for name in people for region in regions]
    if decision_id == 18:
        if int(state.player_regime.get("war_support", 0)) < 80:
            return ["收兵议和"]
    return choices


def decision_visible(state: GameState, decision_id: int) -> bool:
    if decision_id in completed_decisions(state):
        return False
    template = DECISION_TEMPLATES[decision_id]
    unlock = template.get("unlock_strategy")
    if unlock and not strategy_completed(state, int(unlock)):
        return False
    if decision_id == 1:
        return occurred(state, 1) and is_person_available(state, "刘义符") and any(is_person_available(state, name) for name in ("徐羡之", "傅亮", "谢晦", "檀道济"))
    if decision_id == 5:
        return occurred(state, 7) and is_person_available(state, "刘义隆")
    if decision_id == 18:
        return bool(state.flags.get("v12_northern_expedition_started")) and state.turn_number - int(state.flags.get("v12_northern_started_turn", state.turn_number)) >= 8
    return True


def _target_region(state: GameState) -> dict:
    candidates = [r for r in state.regions.values() if int(r.get("controller", 0)) == 1]
    return max(candidates, key=lambda r: sum(1 for u in population_units(state, int(r["id"])) if u.get("occupation") == "refugee"))


def decision_available(state: GameState, decision_id: int) -> tuple[bool, str]:
    if not decision_visible(state, decision_id):
        return False, "尚未解锁或已经完成"
    if decision_id in {1, 2, 5} and state.authority < 100:
        return False, "需要100权威"
    if decision_id == 7 and not is_person_available(state, "徐羡之"):
        return False, "徐羡之已经不在世"
    if decision_id == 8 and not is_person_available(state, "傅亮"):
        return False, "傅亮已经不在世"
    if decision_id == 9:
        region = _region(state, "荆州")
        if not region or int(region.get("controller", 0)) != 1:
            return False, "需要实际控制荆州"
    if decision_id == 10:
        if not decision_choices(state, decision_id):
            return False, "需要有流民比例达到15%且州库至少有20粮、50铜钱的地区"
    if decision_id == 11 and treasury_balance(state) < 100:
        return False, "首都州库需要100铜钱"
    if decision_id == 12 and not local_economic_actions_allowed(state):
        return False, "地区自主经济行动只能在八月至十一月执行"
    if decision_id == 14 and state.at_war(1, 2):
        return False, "宋与魏必须处于和平"
    if decision_id == 15:
        if state.at_war(1, 2): return False, "宋魏必须处于和平"
        if not any(is_person_available(state, name) for name in ("到彦之", "王玄谟", "檀道济")): return False, "没有可用主将"
    if decision_id == 16:
        region = _region(state, "中原地区")
        if not region or int(region.get("controller", 0)) != 1: return False, "需要控制中原"
        record = region_economy(state, int(region["id"]))
        if treasury_balance(state) < 100 or float(record["warehouse"].get("food", 0)) < 20: return False, "需要100铜钱和中原20粮"
    if decision_id == 17 and not state.at_war(1, 2):
        return False, "宋魏必须仍在交战"
    return True, "可以执行"


def _spend_authority(state: GameState, amount: int) -> None:
    if state.authority < amount: raise RuleError(f"权威不足{amount}")
    state.authority -= amount


def _remove_person_from_offices(state: GameState, person_id: int) -> None:
    for regime in state.regimes.values():
        internal = regime.get("internal", {})
        for office, occupant in list(internal.items()):
            if occupant == person_id and office != "emperor":
                internal[office] = None
    for region in state.regions.values():
        if int(region.get("governor") or 0) == person_id:
            region["governor"] = None


def _custom_army(state: GameState, city_name: str, commander: str | None, units: list[tuple[int, int]]) -> int:
    city = _city(state, city_name)
    if not city: raise RuleError(f"缺少城市{city_name}")
    return _army(state, 1, int(city["id"]), units, commander).id


def execute_decision(state: GameState, decision_id: int, choice: str | None = None) -> DecisionResult:
    ok, reason = decision_available(state, decision_id)
    if not ok: raise RuleError(reason)
    if choice is not None and choice not in decision_choices(state, decision_id): raise RuleError("该选项当前不可执行")
    effect = DECISION_TEMPLATES[decision_id]["effect_description"]
    variant_key = choice
    rng = random.Random(state.turn_number * 1009 + decision_id)
    if decision_id == 1:
        _spend_authority(state, 100)
        for name in ("徐羡之", "傅亮", "谢晦", "檀道济"): _change_person(state, name, opinion=15)
        state.player_regime["stability"] = min(100, int(state.player_regime.get("stability", 0)) + 5); _change_person(state, "刘义符", power=-5); state.flags["v12_coup_progress"] = max(0, int(state.flags.get("v12_coup_progress", 0)) - 10)
    elif decision_id == 2:
        _spend_authority(state, 100); region = _region(state, "扬州"); record = region_economy(state, int(region["id"])); failed = int(record["control"]) < 40 and rng.random() < .3
        variant_key = "失败" if failed else "成功"
        record["control"] = min(100, int(record["control"]) + (5 if failed else 15)); _change_person(state, "刘义符", power=0 if failed else 10); _change_person(state, "徐羡之", opinion=-20 if failed else -10)
        if failed: state.flags["v12_coup_progress"] = int(state.flags.get("v12_coup_progress", 0)) + 10
    elif decision_id == 3:
        for name, gain in (("徐羡之",15),("傅亮",10),("谢晦",10)): _change_person(state, name, opinion=gain)
        state.player_regime["stability"] = min(100, int(state.player_regime.get("stability",0))+5); _change_person(state,"刘义符",power=-5)
    elif decision_id == 4:
        if rng.random() < .7: variant_key="成功"; _change_person(state,"刘义符",power=10); _change_person(state,"徐羡之",power=-5)
        else: variant_key="失败"; state.player_regime["stability"] = max(0,int(state.player_regime.get("stability",0))-5); _change_person(state,"徐羡之",opinion=-15); state.flags["v12_coup_progress"] = int(state.flags.get("v12_coup_progress",0))+15
    elif decision_id == 5:
        _spend_authority(state,100); gain=3 if int(state.player_regime.get("stability",0))>=80 else 8; state.player_regime["stability"]=min(100,int(state.player_regime.get("stability",0))+gain)
        for person in state.persons.values():
            if int(person.get("country_id",0))==1 and is_person_available(state,int(person["id"])): person["opinion_of_player"]=min(100,int(person.get("opinion_of_player",30))+5)
    elif decision_id == 6:
        alive=0
        for name,gain in (("殷景仁",10),("王昙首",10),("王华",5)):
            if is_person_available(state,name): alive+=1; _change_person(state,name,power=gain)
        if not alive: state.player_regime["stability"]=min(100,int(state.player_regime.get("stability",0))+3)
        _change_person(state,"徐羡之",opinion=-10)
    elif decision_id == 7:
        xu=_person(state,"徐羡之")
        if rng.random()<.8: variant_key="成功"; _remove_person_from_offices(state,int(xu["id"])); _change_person(state,"徐羡之",power=-30); _change_person(state,"刘义隆",power=10)
        else: variant_key="失败"; state.flags["v12_coup_active"]=True; state.flags["v12_coup_progress"]=max(50,int(state.flags.get("v12_coup_progress",0)))
    elif decision_id == 8:
        fu=_person(state,"傅亮"); success=.9 if not is_person_available(state,"徐羡之") else .6
        if rng.random()<success: variant_key="成功"; _remove_person_from_offices(state,int(fu["id"])); fu["status"]=3
        else: variant_key="失败"; fu["location_id"]=int((_city(state,"江陵") or {"id":fu.get("location_id",1)})["id"]); _change_person(state,"谢晦",opinion=20); state.flags["v12_xie_rebellion_early"]=True
    elif decision_id == 9:
        region=_region(state,"荆州"); person=None if choice=="暂不任命" else _person(state,str(choice)); region["governor"]=int(person["id"]) if person else None
        if choice=="刘义恭": _change_local(state,"荆州",stability=5)
        elif choice=="到彦之": _change_local(state,"荆州",control=5)
    elif decision_id == 10:
        region=_region(state,str(choice)) or _target_region(state); record=region_economy(state,int(region["id"])); record["warehouse"]["food"]-=20; spend_treasury(state,state.player_regime_id,50)
        refugees=[u for u in population_units(state,int(region["id"])) if u.get("occupation")=="refugee"]; count=int(len(refugees)*.2+0.5)
        for unit in refugees[:count]: unit["occupation"]="farmer"
        record["stability"]=min(100,int(record["stability"])+8)
    elif decision_id == 11:
        spend_treasury(state,1,100); region=_region(state,"扬州"); record=region_economy(state,int(region["id"])); failed=int(record["stability"])<40
        record["warehouse_capacity"]=warehouse_capacity(state,int(region["id"]))+(15 if failed else 50); state.flags["v12_jiankang_auto_convoy"]=not failed
    elif decision_id == 12:
        regions=[r for r in state.regions.values() if int(r.get("controller",0))==1]; region=max(regions,key=lambda r: float(region_economy(state,int(r["id"]))["market"].get("food",0))*-1); record=region_economy(state,int(region["id"])); amount=min(20,float(record["warehouse"].get("food",0)))
        if amount<10: record["stability"]=max(0,int(record["stability"])-2)
        else: record["warehouse"]["food"]-=amount; record["market"]["food"]+=amount; record["stability"]=min(100,int(record["stability"])+3)
    elif decision_id == 13:
        person_name, region_name = (part.strip() for part in str(choice).split("→", 1)); person=_person(state,person_name); region=_region(state,region_name); region["governor"]=int(person["id"])
        if int(person.get("level",0))>=7: _change_local(state,str(region["name"]),control=15); _change_person(state,person_name,power=10)
    elif decision_id == 14:
        state.flags["v12_jianghuai_trade_until"]=state.turn_number+24
        for name in ("徐州","淮北地区","中原地区"): _change_local(state,name,stability=2)
    elif decision_id == 15:
        pair=state.relation_pair(1,2)
        if pair not in state.wars:
            from ...rules.diplomacy import declare_war
            declare_war(state, 1, 2)
        state.player_regime["war_support"]=min(100,int(state.player_regime.get("war_support",0))+15)
        commander=next(name for name in ("到彦之","王玄谟","檀道济") if is_person_available(state,name)); variant_key=f"{commander}为主将"; ids=[_custom_army(state,"彭城",commander,[(1,5),(3,3)]),_custom_army(state,"淮阳",None,[(1,4)])]
        state.flags.update(v12_northern_expedition_started=True,v12_northern_started_turn=state.turn_number,v12_northern_armies=ids,v12_northern_initial_strength=sum(state.armies[x].soldiers for x in ids),v12_henan_vanguard_until=state.turn_number+6)
        food=sum(float(region_economy(state,int(_region(state,name)["id"]))["warehouse"].get("food",0)) for name in ("徐州","淮北地区") if _region(state,name))
        if food<80:
            for army_id in ids: state.armies[army_id].morale=max(0,state.armies[army_id].morale-20)
            queue_story_event(state,16)
    elif decision_id == 16:
        spend_treasury(state,1,100); region=_region(state,"中原地区"); record=region_economy(state,int(region["id"])); record["warehouse"]["food"]-=20; gain=10 if int(record["control"])<40 and rng.random()<.3 else 20; variant_key="失败" if gain==10 else "成功"; record["warehouse"]["food"]=min(warehouse_capacity(state,int(region["id"])),float(record["warehouse"]["food"])+gain); record["stability"]=min(100,int(record["stability"])+5); record["control"]=min(100,int(record["control"])+5)
    elif decision_id == 17:
        commander="檀道济" if is_person_available(state,"檀道济") else "王玄谟"; variant_key=f"{commander}为主将"; army_id=_custom_army(state,"滑台",commander,[(1,5),(3,3)])
        if commander=="檀道济": state.armies[army_id].modifiers.append({"id": 1020, "name": "唱筹量沙", "supply_multiplier": 0.5})
    elif decision_id == 18:
        if choice=="再战一年":
            for army_id in state.flags.get("v12_northern_armies",[]):
                if int(army_id) in state.armies: state.armies[int(army_id)].morale=min(100,state.armies[int(army_id)].morale+10)
            state.flags["v12_continue_war_until"]=state.turn_number+12
        else:
            state.player_regime["war_support"]=max(0,int(state.player_regime.get("war_support",0))-5)
            pair=state.relation_pair(1,2)
            if pair in state.wars: state.wars.remove(pair)
            for name in ("徐州","淮北地区","中原地区"): _change_local(state,name,stability=5)
    completed_decisions(state).append(decision_id)
    # setdefault returns the underlying list; ensure completion is persisted when compatibility values were not ints
    state.flags["completed_decisions"] = sorted(set(completed_decisions(state) + [decision_id]))
    state.add_log(f"决议完成：{DECISION_TEMPLATES[decision_id]['name']}。{effect}")
    intro = story_text("决议", decision_id, effect)
    result_text = story_variant("决议", decision_id, str(variant_key), "") if variant_key else ""
    if result_text:
        intro = (intro + "\n\n" + result_text).strip()
    from ..v1_1.story_texts import render_dynamic_text

    intro = render_dynamic_text(state, intro)
    return DecisionResult(DECISION_TEMPLATES[decision_id]["name"], DECISION_TEMPLATES[decision_id]["summary"], intro, effect)
