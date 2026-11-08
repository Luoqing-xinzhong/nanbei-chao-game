from __future__ import annotations

from ...models import Army, GameState
from ...rules.common import clamp, remove_emperor_civil_offices
from ...rules.military import city_controller
from .economy import army_supply_capacity, population_units, region_economy, warehouse_capacity
from .story_texts import story_metadata, story_name, story_text, story_variant


EVENT_BASE = 12200


def event_key(event_id: int) -> int:
    return EVENT_BASE + int(event_id)


def occurred(state: GameState, event_id: int) -> bool:
    return int(event_id) in {int(x) for x in state.flags.get("v12_story_events", [])}


def _person(state: GameState, name: str) -> dict | None:
    return next((p for p in state.persons.values() if state.person_name(int(p["id"])) == name), None)


def is_person_available(state: GameState, person_or_name: int | str, year: int | None = None, month: int | None = None) -> bool:
    person = state.persons.get(int(person_or_name)) if isinstance(person_or_name, int) else _person(state, person_or_name)
    check_year = int(year if year is not None else state.year)
    if not person or int(person.get("birth_year", 0) or 0) > check_year:
        return False
    if int(person.get("status", 0)) == 4 or person.get("exiled") or person.get("story_disabled"):
        return False
    return True


def _region(state: GameState, name: str) -> dict | None:
    return next((r for r in state.regions.values() if r.get("name") == name), None)


def _city(state: GameState, name: str) -> dict | None:
    return next((c for c in state.cities.values() if c.get("name") == name), None)


def _change_stability(state: GameState, amount: int) -> None:
    state.player_regime["stability"] = int(clamp(int(state.player_regime.get("stability", 0)) + amount, 0, 100))


def _change_local(state: GameState, region_name: str, *, stability=0, control=0) -> None:
    region = _region(state, region_name)
    if not region:
        return
    record = region_economy(state, int(region["id"]))
    record["stability"] = int(clamp(int(record["stability"]) + stability, 0, 100))
    record["control"] = int(clamp(int(record["control"]) + control, 0, 100))
    region["local_stability"] = record["stability"]
    region["control"] = record["control"]


def _assign_region_to_regime(state: GameState, region: dict, regime_id: int) -> None:
    """Keep legal ownership and actual control in sync for scripted regime changes."""
    region_name = str(region["name"])
    for regime in state.regimes.values():
        if region_name in regime.get("regions", []):
            regime["regions"] = [name for name in regime.get("regions", []) if name != region_name]
    target = state.regimes[regime_id]
    target.setdefault("regions", []).append(region_name)
    region["controller"] = regime_id


def _change_person(state: GameState, name: str, *, power=0, opinion=0, fame=0) -> None:
    person = _person(state, name)
    if not person or not is_person_available(state, int(person["id"])):
        return
    attrs = person.setdefault("attributes", {})
    attrs["base_power"] = max(0, int(attrs.get("base_power", 0)) + power)
    attrs["fame"] = max(0, int(attrs.get("fame", 0)) + fame)
    person["opinion_of_player"] = int(clamp(int(person.get("opinion_of_player", 30)) + opinion, -100, 100))


def _army(state: GameState, regime_id: int, city_id: int, units: list[tuple[int, int]], commander: str | None = None) -> Army:
    commander_person = _person(state, commander) if commander else None
    commander_id = int(commander_person["id"]) if commander_person and is_person_available(state, int(commander_person["id"])) else None
    if commander_id:
        for existing in state.armies.values():
            if existing.commander == commander_id:
                existing.commander = None
    army = Army(
        id=max(state.armies, default=0) + 1,
        regime_id=regime_id,
        army_type=0,
        units=[{"type": unit_type, "count": 1000} for unit_type, battalions in units for _ in range(battalions)],
        commander=commander_id,
        location_id=city_id,
        morale=80,
        experience=10,
    )
    army.supply_food = army_supply_capacity(army)
    state.armies[army.id] = army
    return army


def _create_xie_hui_rebel_regime(state: GameState, xie: dict, jing: dict, city: dict) -> int:
    """Create a dedicated rebel regime instead of reusing the shared royal-revolt slot."""
    rebel_id = max(state.regimes, default=0) + 1
    state.regimes[rebel_id] = {
        "id": rebel_id,
        "name": "谢晦叛军",
        "color": "black",
        "is_main": False,
        "regions": [],
        "capital": int(city["id"]),
        "stability": 40,
        "war_support": 80,
        "militia": 0,
        "reserve_army": 0,
        "opinion_of_main": -100,
        "relation_with_main": "敌对",
        "authority": 500,
        "internal": {"emperor": None, "grand_general": int(xie["id"])},
    }
    _assign_region_to_regime(state, jing, rebel_id)
    state.flags["v12_xie_hui_rebel_regime_id"] = rebel_id
    return rebel_id


def _xie_hui_rebel_regime_id(state: GameState, xie: dict | None = None) -> int:
    stored = int(state.flags.get("v12_xie_hui_rebel_regime_id", 0) or 0)
    if stored in state.regimes:
        return stored
    if xie:
        country_id = int(xie.get("country_id", 0) or 0)
        if country_id in state.regimes and "谢晦" in str(state.regimes[country_id].get("name", "")):
            return country_id
    return 13 if 13 in state.regimes and "谢晦" in str(state.regimes[13].get("name", "")) else 0


def _enthrone_yi_long(state: GameState) -> None:
    yi_fu = _person(state, "刘义符")
    yi_long = _person(state, "刘义隆")
    if not yi_long or not is_person_available(state, int(yi_long["id"])):
        return
    if yi_fu:
        yi_fu["is_player"] = False
        yi_fu["status"] = 4
    yi_long.update(is_player=True, status=1, level=10, location_id=int(state.player_regime.get("capital", 1)))
    state.player_regime.setdefault("internal", {})["emperor"] = int(yi_long["id"])
    yuan_qigui = _person(state, "袁齐妫")
    if yuan_qigui and is_person_available(state, int(yuan_qigui["id"])):
        yi_long["spouse"] = int(yuan_qigui["id"])
        yuan_qigui["spouse"] = int(yi_long["id"])
        state.player_regime["internal"]["empress"] = int(yuan_qigui["id"])
    remove_emperor_civil_offices(state, state.player_regime_id)
    state.flags.update(era_name="元嘉", era_start_year=state.year, v12_yidu_enthroned=True)
    _change_stability(state, 5)


def _apply_event(state: GameState, event_id: int) -> None:
    if event_id == 1:
        wu = _person(state, "刘裕")
        yi_fu = _person(state, "刘义符")
        yi_long = _person(state, "刘义隆")
        if wu:
            wu["status"] = 4
            wu["is_player"] = False
        successor = yi_fu if yi_fu and is_person_available(state, int(yi_fu["id"])) else yi_long
        if successor is None or not is_person_available(state, int(successor["id"])):
            royals = [
                person for person in state.persons.values()
                if int(person.get("country_id", 0)) == state.player_regime_id
                and int(state.families.get(int(person.get("family_id") or 0), {}).get("family_type", -1)) == 0
                and is_person_available(state, int(person["id"]))
            ]
            successor = max(royals, key=lambda person: (int(person.get("level", 0)), -int(person["id"])), default=None)
        if successor:
            for person in state.persons.values():
                person["is_player"] = int(person["id"]) == int(successor["id"])
            successor.update(status=1, level=10, location_id=int(state.player_regime.get("capital", 1)))
            state.player_regime.setdefault("internal", {})["emperor"] = int(successor["id"])
            remove_emperor_civil_offices(state, state.player_regime_id)
        state.flags.update(era_name="永初", era_start_year=420)
        if not any(int(item.get("id", 0)) == 1201 for item in state.national_modifiers):
            state.national_modifiers.append({
                "id": 1201,
                "name": "主少国疑",
                "description": "国家稳定度上限60，玩家每回合权威获取-50%。徐羡之死后移除。",
                "effects": {"stability_cap": 60, "authority_gain": -0.50},
            })
        state.player_regime["stability"] = min(60, int(state.player_regime.get("stability", 60)))
    elif event_id == 2:
        if not state.flags.get("v12_event2_wei_armies"):
            capital = int(state.regimes[2].get("capital") or 0)
            prepared = [
                army.id for army in sorted(state.armies.values(), key=lambda item: item.id)
                if army.regime_id == 2
                and army.location_id == capital
                and army.soldiers == 5_000
                and all(int(unit.get("type", 0)) == 2 for unit in army.units)
            ][:5]
            created = prepared if len(prepared) == 5 else [_army(state, 2, capital, [(2, 5)]).id for _ in range(5)]
            state.flags["v12_event2_wei_armies"] = created
        pair = state.relation_pair(1, 2)
        if pair not in state.wars:
            from ...rules.diplomacy import declare_war

            declare_war(state, 2, 1)
        tuoba_si = _person(state, "拓跋嗣")
        if tuoba_si and is_person_available(state, int(tuoba_si["id"])):
            _change_person(state, "拓跋嗣", fame=5)
        state.flags["v12_wei_henan_opening"] = True
    elif event_id == 3:
        source = _region(state, "中原地区")
        targets = [r for r in (_region(state, "淮北地区"), _region(state, "徐州")) if r]
        if source and targets:
            target = max(targets, key=lambda r: int(region_economy(state, int(r["id"]))["stability"]))
            units = population_units(state, int(source["id"])); moving = units[: max(1, int(len(units) * .05))]
            for unit in moving:
                unit["region_id"] = int(target["id"])
                unit["occupation"] = "farmer" if int(region_economy(state, int(target["id"]))["stability"]) >= 50 else "refugee"
            _change_local(state, "中原地区", stability=-3); _change_local(state, str(target["name"]), stability=2)
    elif event_id == 4:
        state.flags.update(era_name="景平", era_start_year=423); _change_stability(state, 2)
    elif event_id == 5:
        state.flags["v12_coup_active"] = True; state.flags.setdefault("v12_coup_progress", 0)
    elif event_id == 7:
        _enthrone_yi_long(state)
    elif event_id == 10:
        xie = _person(state, "谢晦")
        if not xie or not is_person_available(state, int(xie["id"])):
            _change_stability(state, 5); return
        jing = _region(state, "荆州")
        city = _city(state, "江陵") or _city(state, "江陵城")
        if not jing or not city:
            return
        rebel_id = _create_xie_hui_rebel_regime(state, xie, jing, city)
        xie["country_id"] = rebel_id
        xie["location_id"] = int(city["id"])
        _change_local(state, "荆州", stability=-20, control=-30)
        pair = state.relation_pair(state.player_regime_id, rebel_id)
        if pair not in state.wars:
            from ...rules.diplomacy import declare_war

            declare_war(state, rebel_id, state.player_regime_id)
        army = _army(state, rebel_id, int(city["id"]), [(1, 5), (3, 3)], "谢晦")
        state.flags["v12_xie_hui_rebellion"] = True
        state.flags["v12_xie_hui_rebellion_turn"] = int(state.turn_number)
        state.add_log(f"谢晦在江陵举兵，建立独立叛军政权并集结军队#{army.id}（5000步兵、3000弓兵）。")
    elif event_id == 11:
        xie = _person(state, "谢晦")
        rebel_id = _xie_hui_rebel_regime_id(state, xie)
        if xie: xie["status"] = 4
        jing = _region(state, "荆州")
        if jing:
            _assign_region_to_regime(state, jing, state.player_regime_id)
            if xie and int(jing.get("governor") or 0) == int(xie["id"]):
                jing["governor"] = None
        for army_id, army in list(state.armies.items()):
            if rebel_id and int(army.regime_id) == rebel_id:
                del state.armies[army_id]
        rebel = state.regimes.get(rebel_id)
        if rebel:
            rebel["regions"] = []
            rebel["relation_with_main"] = "灭亡"
            rebel.setdefault("internal", {})["emperor"] = None
            rebel["internal"]["grand_general"] = None
        pair = state.relation_pair(state.player_regime_id, rebel_id) if rebel_id else []
        if pair in state.wars:
            state.wars.remove(pair)
        state.flags["v12_xie_hui_rebellion"] = False
        _change_stability(state, 15); _change_local(state, "荆州", stability=20, control=10); _change_person(state, "刘义隆", power=15)
    elif event_id == 12:
        state.flags["v12_jingzhou_tax_penalty_until"] = state.turn_number + 12
        region = _region(state, "荆州")
        if region and not region.get("governor"): _change_local(state, "荆州", control=-10)
    elif event_id == 13:
        for name in ("扬州", "江州", "荆州"): _change_local(state, name, stability=2)
        state.flags["v12_merchant_bonus_until"] = state.turn_number + (13 - state.month)
        state.flags["v12_good_harvest_prices_until"] = state.turn_number + (13 - state.month)
    elif event_id == 15:
        state.flags["v12_northern_expedition_council"] = True
    elif event_id == 16:
        state.flags["v12_hasty_expedition_until"] = state.turn_number + 1
    elif event_id == 17:
        city = int(state.regimes[2].get("capital") or 0)
        _army(state, 2, city, [(2, 5)]); _army(state, 2, city, [(2, 5)]); _army(state, 2, city, [(2, 3)])
        state.flags["v12_wei_counterattack"] = True
    elif event_id == 18:
        state.player_regime["war_support"] = max(0, int(state.player_regime.get("war_support", 0)) - 15)
        _change_stability(state, -5); _change_local(state, "徐州", stability=-5); _change_local(state, "淮北地区", stability=-5)
    elif event_id == 19:
        state.player_regime["war_support"] = min(100, int(state.player_regime.get("war_support", 0)) + 10)
        _change_person(state, "刘义隆", fame=10); _change_local(state, "中原地区", stability=10)
        state.flags["v12_wei_seek_peace"] = True
    elif event_id == 21:
        controlled = [r for r in state.regions.values() if int(r.get("controller", 0)) == 1]
        stabilities = [int(region_economy(state, int(r["id"]))["stability"]) for r in controlled]
        controls = [int(region_economy(state, int(r["id"]))["control"]) for r in controlled]
        if stabilities and sum(stabilities) / len(stabilities) >= 75 and sum(controls) / len(controls) >= 60 and not any(1 in war for war in state.wars):
            state.flags["v12_yuanjia_assessment"] = "盛世初成"
            state.national_modifiers.append({"id": 1204, "name": "元嘉之治", "description": "权威恢复+10%，一般商品产量+10%，高稳定地区流民转农+25%。", "effects": {}})
        elif stabilities and sum(stabilities) / len(stabilities) >= 55:
            state.flags["v12_yuanjia_assessment"] = "守成可期"; _change_stability(state, 5); _change_person(state, "刘义隆", fame=10)
        else:
            state.flags["v12_yuanjia_assessment"] = "内忧未靖"
            for region in controlled:
                if int(region_economy(state, int(region["id"]))["stability"]) < 40: _change_local(state, str(region["name"]), control=-5)


def ensure_story_event_record(state: GameState, event_id: int, *, choices: list[str] | None = None) -> dict:
    """Install the document-backed event record without replaying its game effects."""
    key = event_key(event_id)
    text = story_text("事件", event_id, "")
    if event_id == 15 and not any(
        is_person_available(state, name) for name in ("到彦之", "王玄谟", "檀道济")
    ):
        text = story_variant("事件", 15, "三将均已不在人世", text)
    record = {
        "id": key,
        "name": story_name("事件", event_id, f"事件{event_id}"),
        "summary": story_name("事件", event_id, f"事件{event_id}"),
        "text": text,
        "effect_description": story_metadata("事件", event_id, "事件效果已经按1.2剧本规则结算。"),
        "choices": list(choices or []),
        "choice_required": bool(choices),
        "triggered": True,
        "story_event_id": event_id,
    }
    state.events[key] = record
    return record


def queue_story_event(state: GameState, event_id: int, *, choices: list[str] | None = None) -> bool:
    if int(event_id) == 14:
        _remove_retired_royal_power_event(state)
        return False
    if occurred(state, event_id) and event_id != 13:
        return False
    state.flags.setdefault("v12_story_events", []).append(int(event_id))
    state.flags.setdefault("v12_story_event_turns", {})[str(int(event_id))] = int(state.turn_number)
    key = event_key(event_id)
    record = ensure_story_event_record(state, event_id, choices=choices)
    _apply_event(state, event_id)
    if event_id == 21:
        assessment = str(state.flags.get("v12_yuanjia_assessment", ""))
        branch = story_variant("事件", 21, assessment, "")
        if branch:
            record["text"] = (str(record["text"]) + "\n\n" + branch).strip()
    pending = state.flags.setdefault("pending_story_events", [])
    if key not in pending: pending.append(key)
    state.add_log(f"事件触发：{record['name']}。")
    return True


def _check_coup(state: GameState) -> None:
    if not state.flags.get("v12_coup_active") or occurred(state, 7):
        return
    xu = _person(state, "徐羡之"); fu = _person(state, "傅亮")
    if not xu or not is_person_available(state, int(xu["id"])):
        if fu and is_person_available(state, int(fu["id"])):
            if not occurred(state, 6):
                queue_story_event(state, 6)
            progress = 10 if int(fu.get("opinion_of_player", 0)) >= 50 else 20
        else:
            state.flags["v12_coup_active"] = False; return
    else:
        progress = 25
        if 3 in {int(x) for x in state.flags.get("completed_decisions", [])}: progress -= 5
        if state.strategies.get(5, {}).get("status") == "completed": progress += 5
    state.flags["v12_coup_progress"] = int(state.flags.get("v12_coup_progress", 0)) + progress
    if int(state.flags["v12_coup_progress"]) >= 100 and is_person_available(state, "刘义隆"):
        queue_story_event(state, 7)


def _remove_retired_royal_power_event(state: GameState) -> None:
    """Remove the retired event from new games and from pending legacy saves."""
    state.flags["v12_story_events"] = [
        int(item) for item in state.flags.get("v12_story_events", []) if int(item) != 14
    ]
    state.flags.setdefault("v12_story_event_turns", {}).pop("14", None)
    state.flags["pending_story_events"] = [
        int(item) for item in state.flags.get("pending_story_events", [])
        if int(item) != event_key(14)
    ]
    state.events.pop(event_key(14), None)
    state.flags.pop("v12_royal_power_checked", None)
    state.flags.pop("v12_unhandled_royals", None)


def check_story_events(state: GameState) -> list[int]:
    _remove_retired_royal_power_event(state)
    before = set(state.flags.get("v12_story_events", []))
    luoyang = _city(state, "洛阳")
    if luoyang and not state.flags.get("v12_wei_henan_opening_resolved"):
        if state.turn_number >= 7 and city_controller(state, int(luoyang["id"])) == 1:
            state.player_regime["war_support"] = min(100, int(state.player_regime.get("war_support", 0)) + 10)
            state.flags["v12_wei_henan_opening_resolved"] = "defended"
        elif city_controller(state, int(luoyang["id"])) == 2:
            _change_local(state, "中原地区", stability=-10)
            state.flags["v12_wei_henan_opening_resolved"] = "lost"
    if state.flags.get("v12_wei_henan_opening_resolved") == "lost" and not occurred(state, 3):
        central = _region(state, "中原地区")
        if central and int(region_economy(state, int(central["id"]))["stability"]) < 50:
            queue_story_event(state, 3)
    if state.year >= 423 and not occurred(state, 4) and is_person_available(state, "刘义符"):
        queue_story_event(state, 4)
    if (state.year, state.month) >= (424, 1) and not occurred(state, 5) and is_person_available(state, "徐羡之") and is_person_available(state, "刘义符"):
        queue_story_event(state, 5)
    _check_coup(state)
    if state.year == 426 and state.strategies.get(10, {}).get("status") == "completed" and not occurred(state, 10):
        xie = _person(state, "谢晦"); jing = _region(state, "荆州")
        if xie and jing and int(jing.get("governor") or 0) == int(xie["id"]): queue_story_event(state, 10)
    if occurred(state, 10) and not occurred(state, 11):
        jiangling = _city(state, "江陵") or _city(state, "江陵城")
        rebellion_turn = int(
            state.flags.get("v12_story_event_turns", {}).get(
                "10", state.flags.get("v12_xie_hui_rebellion_turn", -999)
            )
        )
        if (
            state.turn_number - rebellion_turn >= 3
            and jiangling
            and city_controller(state, int(jiangling["id"])) == 1
        ):
            queue_story_event(state, 11)
    if occurred(state, 11) and not occurred(state, 12):
        happened = int(state.flags.get("v12_story_event_turns", {}).get("11", -999))
        jingzhou = _region(state, "荆州")
        if jingzhou and state.turn_number - happened <= 12 and int(region_economy(state, int(jingzhou["id"]))["stability"]) < 50:
            queue_story_event(state, 12)
    if 425 <= state.year <= 429 and state.month == 8 and not occurred(state, 9):
        for name in ("北雍州", "中原地区"):
            region = _region(state, name)
            if region and int(region.get("controller", 0)) == 1 and region_economy(state, int(region["id"])).get("last_weather") == "干旱":
                queue_story_event(state, 9)
                state.flags["v12_drought_relief"] = {"region_id": int(region["id"]), "opening_food": float(region_economy(state, int(region["id"]))["warehouse"].get("food", 0.0))}
                break
    drought = state.flags.get("v12_drought_relief")
    if drought and state.month == 1 and not drought.get("resolved"):
        region_id = int(drought["region_id"]); imported = float(region_economy(state, region_id)["warehouse"].get("food", 0.0)) - float(drought["opening_food"])
        _change_local(state, str(state.regions[region_id]["name"]), stability=5 if imported >= 20 else -5)
        if imported < 20:
            refugees = population_units(state, region_id)
            for unit in refugees[: max(1, int(len(refugees) * .03))]: unit["occupation"] = "refugee"
        drought["resolved"] = True
    if state.month == 8:
        rich = []
        for name in ("扬州", "江州", "荆州"):
            region = _region(state, name)
            if region and region_economy(state, int(region["id"])).get("last_weather") in {"风调雨顺", "丰收"} and int(region_economy(state, int(region["id"]))["stability"]) >= 70:
                rich.append(region)
        if len(rich) >= 2 and int(state.flags.get("v12_last_good_harvest_year", 0)) != state.year:
            queue_story_event(state, 13); state.flags["v12_last_good_harvest_year"] = state.year
    if state.strategies.get(24, {}).get("status") == "completed" and not occurred(state, 15): queue_story_event(state, 15)
    counterattack_date = (430, 6) if state.strategies.get(27, {}).get("status") == "completed" else (430, 9)
    if (state.year, state.month) >= counterattack_date and not occurred(state, 17):
        if any(city_controller(state, int(city["id"])) == 1 for city in (_city(state, "洛阳"), _city(state, "滑台")) if city): queue_story_event(state, 17)
    # 431年腊月只看宋是否仍实际控制中原。成功则触发事件19；
    # 若未成功，432年正月起必定由事件18收束北伐线，二者严格互斥。
    if (state.year, state.month) == (431, 12) and not occurred(state, 18) and not occurred(state, 19):
        central = _region(state, "中原地区")
        if central and int(central.get("controller", 0)) == state.player_regime_id:
            queue_story_event(state, 19)
    if (state.year, state.month) >= (432, 1) and not occurred(state, 18) and not occurred(state, 19):
        queue_story_event(state, 18)
    after = set(state.flags.get("v12_story_events", []))
    return sorted(int(x) for x in after - before)


def apply_event_choice(state: GameState, event_id: int, choice: str) -> str:
    raise ValueError("该事件没有可选分支；宗王坐大事件已经移除")
