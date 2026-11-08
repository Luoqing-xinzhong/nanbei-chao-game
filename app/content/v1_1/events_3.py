from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...models import Army, GameState
from ...rules.common import clamp, living_commander_id


EVENT_TEMPLATES: dict[int, dict[str, Any]] = {
    8: {
        "id": 8,
        "name": "刘毅私通禁军宫变挟持天子",
        "summary": "刘毅发动宫变。",
        "effect_handler": "event_8_effect",
        "effect_description": "游戏失败。",
        "repeatable": False,
        "text": """当夜，建康月隐星沉，宫墙下的暗影吞没了一切。刘毅率黑甲禁军自宣阳门入宫，在安帝榻前三步停下，展开黄绢：“陛下受奸佞蛊惑，臣请清君侧。”\n\n天亮时，朱雀门换了告示，落款盖着“豫州牧刘”的印。千里之外，刘裕尚在征途，还不知道建康已经变天。\n\n游戏结束。最后的敌人不是胡骑，不是草寇，是并肩杀出来的同袍。""",
    },
    9: {
        "id": 9,
        "name": "王谧联合高门发动政变",
        "summary": "王谧联合高门发动政变。",
        "effect_handler": "event_9_effect",
        "effect_description": "游戏失败。",
        "repeatable": False,
        "text": """深秋的建康，王谧府中灯火通明。王氏、谢氏、袁氏、荀氏的联名状摆满一案。三更时分，王谧带着高门护卫登上台省，安帝在呈上的诏书上盖下玺印。\n\n天亮时，南渡百年的门阀重新掌权，刘裕的名字被一笔勾去，只剩一道刀口般的墨痕。\n\n游戏结束。刀枪夺不走的江山，文书和姓氏可以。""",
    },
    10: {
        "id": 10,
        "name": "司马休之清君侧",
        "summary": "司马休之联合晋宗室发动政变，弑杀安帝自立。",
        "effect_handler": "event_10_effect",
        "effect_description": "游戏失败。",
        "repeatable": False,
        "text": """大雪落在建康城头。司马休之素服佩剑，率宗室子弟叩开宫门。他跪在安帝榻前：“臣为晋室江山计，请陛下禅位。”随后从袖中取出一方白绫。\n\n天明时，告示称安帝暴疾崩殂，遗诏传位宗室休之。刘裕成了新朝口中的“逆贼”。\n\n游戏结束。宗室不需要英雄，只需要一个姓司马的坐在那里。""",
    },
    11: {
        "id": 11,
        "name": "桓楚破建康",
        "summary": "桓楚反攻并攻破建康。",
        "effect_handler": "event_11_effect",
        "effect_description": "游戏失败。",
        "repeatable": False,
        "text": """建康城头的晋旗坠下时，桓振策马从宣阳门入城。桓楚黑旗从朱雀门一直升到太极殿，像潮水漫过堤岸。\n\n桓振走上丹墀，拍了拍曾属于桓玄的龙椅：“叔父，当年丢的，侄儿替您拿回来了。”\n\n游戏结束。打不死的桓楚，终究还是回来了。""",
    },
    12: {
        "id": 12,
        "name": "刘毅造反",
        "summary": "刘毅在荆州起兵，谢混率水师响应。",
        "effect_handler": "event_12_effect",
        "effect_description": "成立刘毅政权；刘毅获得五千步兵，谢混获得五千战船水军。",
        "repeatable": False,
        "text": """九月江陵，刘毅面前三封密报都指向同一个结局：建康已经容不下他。谢混看完后缓缓点头：“荆州尚有兵马，襄阳城坚粮足。谢某愿率水师为前驱。”\n\n三日后，江陵城头竖起“刘”字大旗。刘毅自领五千步卒，谢混率五千战船顺江而下。昔日同袍，终于拔刀相向。""",
    },
    13: {
        "id": 13,
        "name": "平定刘毅",
        "summary": "刘毅叛乱在江陵被平定。",
        "effect_handler": "event_13_effect",
        "effect_description": "刘毅、刘籓和谢晦死亡，稳定度+10。",
        "repeatable": False,
        "text": """十月江陵，刘字旗坠地。刘籓率残部巷战至死，谢晦自尽，刘毅独坐刺史府正堂，案上只留一行字：“起于京口，终于江陵。”\n\n捷报送抵建康，刘裕看了一遍便继续翻阅公文。只是那页纸被他捏出了几道深深的褶皱。傍晚，有人看见他独登石头城楼，望西而立，直到天黑。""",
    },
    14: {
        "id": 14,
        "name": "刘毅攻破建康",
        "summary": "刘毅叛军攻破建康。",
        "effect_handler": "event_14_effect",
        "effect_description": "游戏失败。",
        "repeatable": False,
        "text": """建康城破的那天，下着小雨。刘毅从宣阳门进入，烧去一半的晋旗湿漉漉地垂着。他曾作为功臣跟在刘裕身后走过这条御道，如今却独自走在最前。\n\n“封存府库，严查宫禁。”他的声音传过空荡荡的广场。雨幕吞没了余下的一切。\n\n游戏结束。从京口到建康，你走了十年；从建康到江陵，你只走了一个月。同袍拔刀，比敌人更准、更快，也更疼。""",
    },
}


def _person_id(state: GameState, name: str) -> int | None:
    return next(
        (int(person["id"]) for person in state.persons.values() if state.person_name(int(person["id"])) == name),
        None,
    )


def _city_id(state: GameState, name: str) -> int:
    return next(int(city["id"]) for city in state.cities.values() if city.get("name") == name)


def _alive(state: GameState, name: str) -> bool:
    person_id = _person_id(state, name)
    return bool(person_id and int(state.persons[person_id].get("status", 0)) in {1, 2, 3})


def _completed_coup_by(state: GameState, name: str) -> bool:
    return any(
        float(coup.get("progress", 0)) >= 100
        and not coup.get("special_jiankang")
        and state.person_name(int(coup.get("leader", 0))) == name
        for party in state.parties.values()
        if (coup := party.get("coup"))
    )


def _lose_game(state: GameState, reason: str) -> None:
    state.flags["game_over"] = True
    state.flags["game_over_reason"] = reason


def _kill(state: GameState, name: str) -> None:
    person_id = _person_id(state, name)
    if not person_id:
        return
    person = state.persons[person_id]
    person["status"] = 4
    person["death_year"] = state.year
    for army in state.armies.values():
        if army.commander == person_id:
            army.commander = None


def _create_army(
    state: GameState,
    regime_id: int,
    commander_name: str,
    naval: bool = False,
) -> Army:
    commander = living_commander_id(state, _person_id(state, commander_name))
    for army in state.armies.values():
        if army.commander == commander:
            army.commander = None
    army_id = max(state.armies, default=0) + 1
    army = Army(
        army_id,
        regime_id,
        1 if naval else 0,
        [{"type": 4 if naval else 1, "count": 1000} for _ in range(5)],
        commander=commander,
        location_id=_city_id(state, "江陵"),
    )
    state.armies[army_id] = army
    if commander:
        state.persons[commander]["location_id"] = army.location_id
    return army


def start_liu_yi_rebellion(state: GameState) -> int:
    existing = int(state.flags.get("liu_yi_regime_id", 0))
    if existing in state.regimes:
        return existing
    liu_yi = _person_id(state, "刘毅")
    xie_hun = _person_id(state, "谢混")
    jingzhou = next(region for region in state.regions.values() if region.get("name") == "荆州")
    regime_id = max(state.regimes, default=0) + 1
    for regime in state.regimes.values():
        if "荆州" in regime.get("regions", []):
            regime["regions"].remove("荆州")
    state.player_regime.setdefault("regions", [])
    jingzhou["controller"] = regime_id
    jingzhou["governor"] = None
    state.regimes[regime_id] = {
        "id": regime_id,
        "name": "刘毅",
        "color": "darkred",
        "is_main": False,
        "regions": ["荆州"],
        "capital": _city_id(state, "江陵"),
        "stability": 50,
        "war_support": 80,
        "treasury": 500,
        "militia": 0,
        "reserve_army": 0,
        "opinion_of_main": -100,
        "relation_with_main": "交战",
        "internal": {"emperor": None, "grand_general": liu_yi},
    }
    for person_id in (liu_yi, xie_hun):
        if person_id:
            state.persons[person_id]["country_id"] = regime_id
    pair = state.relation_pair(state.player_regime_id, regime_id)
    if pair not in state.wars:
        state.wars.append(pair)
    state.flags[f"war_aggressor:{pair[0]}:{pair[1]}"] = regime_id
    state.flags["liu_yi_regime_id"] = regime_id
    _create_army(state, regime_id, "刘毅")
    _create_army(state, regime_id, "谢混", naval=True)
    return regime_id


def mark_event_12_triggered(state: GameState) -> None:
    event = state.events.get(12)
    if event:
        event["triggered"] = True


def _event_8_condition(state: GameState) -> bool:
    return _completed_coup_by(state, "刘毅")


def _event_9_condition(state: GameState) -> bool:
    return _completed_coup_by(state, "王谧")


def _event_10_condition(state: GameState) -> bool:
    return _completed_coup_by(state, "司马休之")


def _event_11_condition(state: GameState) -> bool:
    from ...rules.military import city_controller

    return city_controller(state, _city_id(state, "建康")) == 3


def _event_12_condition(state: GameState) -> bool:
    return (state.year, state.month) >= (412, 9) and _alive(state, "刘毅") and not state.flags.get("liu_yi_regime_id")


def _event_13_condition(state: GameState) -> bool:
    from ...rules.military import city_controller

    return bool(state.events.get(12, {}).get("triggered")) and city_controller(state, _city_id(state, "江陵")) == state.player_regime_id


def _event_14_condition(state: GameState) -> bool:
    from ...rules.military import city_controller

    rebel_id = int(state.flags.get("liu_yi_regime_id", 0))
    return bool(rebel_id and state.events.get(12, {}).get("triggered")) and city_controller(state, _city_id(state, "建康")) == rebel_id


def _event_8_effect(state: GameState) -> None:
    _lose_game(state, "刘毅私通禁军发动宫变，晋廷覆亡。")


def _event_9_effect(state: GameState) -> None:
    _lose_game(state, "王谧联合高门发动政变，晋廷覆亡。")


def _event_10_effect(state: GameState) -> None:
    _lose_game(state, "司马休之清君侧并弑帝自立，晋廷覆亡。")


def _event_11_effect(state: GameState) -> None:
    _lose_game(state, "桓楚攻破建康，晋廷覆亡。")


def _event_12_effect(state: GameState) -> None:
    start_liu_yi_rebellion(state)


def _event_13_effect(state: GameState) -> None:
    for name in ("刘毅", "刘籓", "谢晦"):
        _kill(state, name)
    values_law = int(state.laws.get("values", 1))
    stability_cap = {1: 50, 2: 70}.get(values_law, 100)
    state.player_regime["stability"] = int(
        clamp(state.player_regime.get("stability", 0) + 10, 0, stability_cap)
    )


def _event_14_effect(state: GameState) -> None:
    _lose_game(state, "刘毅叛军攻破建康，晋廷覆亡。")


EVENT_CONDITIONS: dict[int, Callable[[GameState], bool]] = {
    8: _event_8_condition,
    9: _event_9_condition,
    10: _event_10_condition,
    11: _event_11_condition,
    12: _event_12_condition,
    13: _event_13_condition,
    14: _event_14_condition,
}

EVENT_EFFECTS: dict[int, Callable[[GameState], None]] = {
    8: _event_8_effect,
    9: _event_9_effect,
    10: _event_10_effect,
    11: _event_11_effect,
    12: _event_12_effect,
    13: _event_13_effect,
    14: _event_14_effect,
}
