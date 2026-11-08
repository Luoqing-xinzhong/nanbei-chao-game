from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...models import Army, GameState
from ...rules.common import clamp, is_regime_eliminated, living_commander_id


EVENT_TEMPLATES: dict[int, dict[str, Any]] = {
    1: {
        "id": 1,
        "name": "入主建康",
        "summary": "刘裕进入建康，百废待兴，朝中商议平定桓楚事宜。",
        "effect_handler": "event_1_effect",
        "effect_description": "王嘏好感+20，王谧好感+30并任录尚书事；檀凭之、孟昶成为亲信；刘裕等级提升至6。",
        "repeatable": False,
        "text": (
            "十月的建康，宫墙上的焦痕犹新。尚书王嘏率百官出宣阳门，奉迎乘舆。\n\n"
            "司徒王谧却躲在府中，坐立不安。他曾亲手为桓玄解下安帝玺绂，如今义旗已立，"
            "刘毅在朝会上当众喝问：“玺绂何在？”王谧面如土色。从弟王谌又来劝：“兄既桓氏党附，欲求免得乎？”"
            "当夜，王谧携家小逃往曲阿。\n\n"
            "消息报入石头城留台。刘毅按剑：“此人桓玄佐命，当诛！”\n\n"
            "刘裕却摆了摆手。他想起多年前自己赌债缠身、被刁逵囚禁时，是王谧悄悄替他还了钱。"
            "那时满朝显贵无人正眼看他，唯有王谧说：“卿当为一代英雄。”\n\n"
            "“派人去迎。”刘裕对孟昶道。\n\n"
            "孟昶领命，策马出城。檀凭之立于刘裕身侧，低声道：“主公宽宏，但此人终是桓玄旧臣。”"
            "刘裕望向江陵方向：“正因如此，才要用他。江南士族观望者多，杀一个王谧，失的是天下人心。”\n\n"
            "次日，孟昶迎王谧还建康。刘裕亲至府门，扶起伏地请罪的王谧，以他为侍中、领司徒、扬州刺史、录尚书事。"
            "王谧颤声推辞，刘裕只说了四个字：“唯才是举。”\n\n满朝肃然。"
        ),
    },
    2: {
        "id": 2,
        "name": "江陵决战",
        "summary": "桓谦、桓振组织军队，准备与晋军决战。",
        "effect_handler": "event_2_effect",
        "effect_description": "桓楚获得两支五千步兵；桓谦军攻击力+20%，桓振军防御作战力+30%。",
        "repeatable": False,
        "text": (
            "腊月的江陵，北风割面如刀。\n\n"
            "城头旗帜残破，街上行人绝迹。桓玄已死，首级悬于建康城门之下，消息传来那天，城中哭声彻夜不息。\n\n"
            "议事厅内，炭火将熄未熄。桓谦披着旧袍，手指无意识地敲着案几，面前摊着半卷舆图。"
            "桓振推门进来，甲胄上还挂着霜，大嗓门震得窗纸发颤：“叔父，不能再等了！晋军已至巴陵，不日便到城下，"
            "咱们困守孤城，难道要等刘裕来取咱俩的人头？”\n\n"
            "桓谦抬眼看他：“急什么？城外尚有咱们的水师，若能引入长江……”话没说完，桓振一掌拍在案上："
            "“叔父，人家打到家门口了，还读兵书！”他抓起那卷舆图，哗啦扯开，“要么杀出去，要么死在这。我选前者。”\n\n"
            "桓谦沉默良久，终于站起身。他走到窗前推开窗，一股冷风夹着雪沫子扑进来。\n\n"
            "“那就打。”他转过身，声音不大，却很沉，“江陵的兵还有多少？”\n\n“八千。”\n\n"
            "“整军。你率一部西出，我领一部东迎。刘裕的兵也是人，刀砍上去也出血。桓家的男人，死也要站着死。”\n\n"
            "桓振咧嘴一笑，转身出门。雪落下来，盖住了庭院里的马蹄印。"
        ),
    },
    3: {
        "id": 3,
        "name": "瓜分荆楚",
        "summary": "刘毅出任荆州刺史，高门世家瓜分荆楚田产。",
        "effect_handler": "event_3_effect",
        "effect_description": "刘毅成为荆州刺史；荆州、湘州、南雍州、郢州各有50%土地平均分给高门家族。",
        "repeatable": False,
        "text": (
            "江陵城头桓字旗轰然坠地，换上晋旗那日，四州文武齐聚荆州治所。战事方歇，满城硝烟未散，"
            "可官署门前已是车马如云——来的不是将领，是各郡的高门使者。\n\n"
            "议事厅内，刘裕的手还没有捂热荆州刺史的印绶，便当着众人面递了出去：“毅兄，荆州交给你了。”"
            "刘毅接过印时没有推辞，只将那方铜印在掌心掂了掂，咧嘴一笑：“公放心，荆州乱不了。”\n\n"
            "他话音未落，门外已有人递上名帖——琅琊王氏、陈郡谢氏、太原王氏、清河崔氏……一长串名字念下来，"
            "满室静默。谁都知道，这些人不是来贺喜的。四州之地，沃野千里，从江陵到湘阴，从襄阳到夏口，"
            "有多少良田，就有多少双士族的眼睛盯着。\n\n"
            "刘裕站起身，拍了拍刘毅的肩膀，只说了句：“你看着办。”转身出了门。他走出官署时，听见身后厅中"
            "已是人声鼎沸——各家的使者正围着刘毅，争着说起自家田地与江陵交界之处。刘裕没有回头，靴子踩过"
            "石阶上的残雪，咯吱作响。\n\n"
            "他清楚，仗打完了，分账的时候到了。\n\n"
            "高门们很快瓜分四州田产，每郡半数良田换了新契。荆楚百姓望着自家田埂上插满的各色旗幡，默默收起了锄头。"
        ),
    },
}


def person_id_by_name(state: GameState, name: str) -> int | None:
    return next((int(person["id"]) for person in state.persons.values() if state.person_name(int(person["id"])) == name), None)


def city_id_by_name(state: GameState, name: str) -> int:
    return next(int(city["id"]) for city in state.cities.values() if city.get("name") == name)


def add_national_modifier(state: GameState, modifier_id: int, name: str, description: str, effects: dict[str, float]) -> None:
    state.national_modifiers[:] = [item for item in state.national_modifiers if int(item.get("id", 0)) != modifier_id]
    state.national_modifiers.append({"id": int(modifier_id), "name": name, "description": description, "effects": effects})


def national_modifier_total(state: GameState, effect: str) -> float:
    """Return the combined value of a named effect when a rule consumes it."""
    from ...rules.national_modifiers import national_modifier_total as active_total

    return active_total(state, effect)


def initialize_story_state(state: GameState) -> None:
    """Apply the scenario opening and install serializable event records."""
    state.year = 404
    state.month = 10
    state.turn_number = 1
    # 新剧本没有默认亲信；紧接着触发的剧情奖励仍会正常加入亲信。
    state.confidants.clear()
    regime = state.player_regime
    regime["stability"] = 30
    regime["war_support"] = 60
    regime["treasury"] = 1000
    regime["reserve_army"] = 5000
    regime["militia"] = 10000
    regime["internal"]["emperor"] = None
    wang_gao = person_id_by_name(state, "王嘏")
    regime["internal"]["shangshu_ling"] = wang_gao
    sima_dezong = person_id_by_name(state, "司马德宗")
    jiangling = next((int(city["id"]) for city in state.cities.values() if city.get("name") == "江陵"), 0)
    if sima_dezong and jiangling:
        state.persons[sima_dezong]["location_id"] = jiangling
    war = state.relation_pair(state.player_regime_id, 3)
    if war not in state.wars:
        state.wars.append(war)
    state.regimes[3]["relation_with_main"] = "交战"
    state.events = {
        event_id: {**template, "triggered": False}
        for event_id, template in EVENT_TEMPLATES.items()
    }
    state.strategies = {}
    from .strategies import ensure_strategy_records

    ensure_strategy_records(state)
    state.national_modifiers = []
    state.flags.pop("pending_story_events", None)
    state.event_log.clear()
    state.add_log("公元404年元兴三年十月，新局开始。")
    state.normalize_person_power_data(initial=True)
    # 新建剧本本身就是一个回合开始点，开场事件应在状态交给界面前完成结算。
    queue_start_of_turn_events(state)


def _date_at_least(state: GameState, year: int, month: int) -> bool:
    return (state.year, state.month) >= (year, month)


def _alive(state: GameState, name: str) -> bool:
    person_id = person_id_by_name(state, name)
    return bool(person_id and int(state.persons[person_id].get("status", 0)) in {1, 2, 3})


def _event_1_condition(state: GameState) -> bool:
    return _date_at_least(state, 404, 10)


def _event_1_effect(state: GameState) -> None:
    wang_gao = person_id_by_name(state, "王嘏")
    wang_mi = person_id_by_name(state, "王谧")
    tan_pingzhi = person_id_by_name(state, "檀凭之")
    meng_chang = person_id_by_name(state, "孟昶")
    if wang_gao:
        state.persons[wang_gao]["opinion_of_player"] = int(clamp(state.persons[wang_gao].get("opinion_of_player", 0) + 20, -100, 100))
    if wang_mi:
        state.persons[wang_mi]["opinion_of_player"] = int(clamp(state.persons[wang_mi].get("opinion_of_player", 0) + 30, -100, 100))
        state.player_regime["internal"]["lu_shangshu"] = wang_mi
    for person_id in (tan_pingzhi, meng_chang):
        if person_id and person_id not in state.confidants:
            state.confidants.append(person_id)
    # Initial configuration is capped at 5, but events may raise a person beyond it.
    state.player["level"] = 6


def _event_2_condition(state: GameState) -> bool:
    return (
        _date_at_least(state, 404, 12)
        and not is_regime_eliminated(state, 3)
        and _alive(state, "桓谦")
        and _alive(state, "桓振")
    )


def _create_story_army(state: GameState, commander_name: str) -> Army:
    commander = living_commander_id(state, person_id_by_name(state, commander_name))
    jiangling = next(int(city["id"]) for city in state.cities.values() if city.get("name") == "江陵")
    army_id = max(state.armies, default=0) + 1
    army = Army(
        army_id,
        3,
        0,
        [{"type": 1, "count": 1000} for _ in range(5)],
        commander=commander,
        location_id=jiangling,
    )
    state.armies[army_id] = army
    return army


def _event_2_effect(state: GameState) -> None:
    _create_story_army(state, "桓谦")
    _create_story_army(state, "桓振")


FOUR_JINGCHU_REGIONS = {"荆州", "湘州", "南雍州", "郢州"}


def _event_3_condition(state: GameState) -> bool:
    owned = set(state.player_regime.get("regions", []))
    return is_regime_eliminated(state, 3) and FOUR_JINGCHU_REGIONS <= owned


def _event_3_effect(state: GameState) -> None:
    liu_yi = person_id_by_name(state, "刘毅")
    jingzhou = next(region for region in state.regions.values() if region.get("name") == "荆州")
    if liu_yi:
        for region in state.regions.values():
            if region.get("governor") == liu_yi:
                region["governor"] = None
        jingzhou["governor"] = liu_yi
        capital = next(
            (city_id for city_id in jingzhou.get("cities", []) if state.cities.get(city_id, {}).get("capital")),
            0,
        )
        if capital:
            state.persons[liu_yi]["location_id"] = capital
        from ...rules.military import sync_all_commander_locations

        sync_all_commander_locations(state)
    high_families = sorted(
        int(family["id"]) for family in state.families.values()
        if int(family.get("family_type") or -1) == 1
    )
    if not high_families:
        return
    for region in state.regions.values():
        if region.get("name") not in FOUR_JINGCHU_REGIONS:
            continue
        ownership = list(region.get("land_ownership", []))
        for index in range(len(ownership) // 2):
            ownership[index] = high_families[index % len(high_families)]
        region["land_ownership"] = ownership


# 后续剧情二：新事件仍由统一的回合开始事件队列负责判定和展示。
EVENT_TEMPLATES.update({
    4: {
        "id": 4,
        "name": "谯蜀增防",
        "summary": "谯蜀得知晋军可能西进，开始在成都扩充守军。",
        "effect_handler": "event_4_effect",
        "effect_description": "谯蜀在成都获得五千步兵，并解锁4号军事修正。",
        "repeatable": False,
        "text": "义熙元年八月，蜀中急报接连送入成都。谯蜀朝廷征发丁壮、整修城垣，五千新军集结于成都，严阵以待。",
    },
    5: {
        "id": 5,
        "name": "卢循窥伺",
        "summary": "晋军北顾之际，卢循、徐道覆自番禺起兵。",
        "effect_handler": "event_5_effect",
        "effect_description": "卢循向晋宣战，在番禺建立四支军队，并依次以寻阳、建康为进攻目标。",
        "repeatable": False,
        "text": (
            "晋军与南燕或后秦交战之际，卢循认为建康空虚，遂与徐道覆在番禺大集舟师。"
            "叛军扬帆北上，先指寻阳，继而直逼建康。"
        ),
    },
    6: {
        "id": 6,
        "name": "卢循死守",
        "summary": "晋廷主动向卢循宣战，卢循在番禺聚兵自保。",
        "effect_handler": "event_6_effect",
        "effect_description": "卢循在番禺建立四支守军；本事件与“卢循窥伺”互斥。",
        "repeatable": False,
        "text": (
            "晋廷檄文传至岭南，卢循知道大战已不可避免。他命徐道覆整顿水师，"
            "又在番禺征集步弓兵，决意凭借海路与城防固守。"
        ),
    },
    7: {
        "id": 7,
        "name": "卢循破建康",
        "summary": "卢循军攻入建康，晋廷的统治土崩瓦解。",
        "effect_handler": "event_7_effect",
        "effect_description": "游戏失败。",
        "repeatable": False,
        "text": "卢循军旗出现在建康城头。宫省失守、百官奔散，晋廷再无力维持局面。",
    },
})

EVENT_TEMPLATES[4]["text"] = """八月成都，暑气未消。城头守卒手搭凉棚向北张望——入秋以来，从白帝城方向传来消息，晋军正在整备，似有溯江西进之意。

刺史府中，谯纵背着手来回踱步。案上摆着三封急报，一封说刘裕已平江陵，一封说巴东守将遣使来降，第三封还未拆开，用火漆封着，落款是“汉中”。

“主公。”参军起身拱手，“晋军若来，必走水路。成都虽险，但城中兵不满三千，且多为新募，未经战阵……”

谯纵停下脚步，望着窗外西岭雪山在暮色中泛着青灰色的轮廓。入蜀一年多，他靠着氐羌之众坐稳了成都，可心里始终清楚——这座城是捡来的。刘裕腾出手来，第一个要收拾的就是他。

“传令下去，”他转过身，声音沙哑却果断，“各郡征丁，不限门第，三日之内齐集成都。府库粮草全部充作军需，成都四面城门加筑瓮城，城墙上多备滚木礌石。”

参军低头应诺，走到门口时，谯纵又叫住他：“把汉中那封急报拆了。”

参军撕开火漆，展开信笺，脸色微变。谯纵接过看了一眼，缓缓放下，什么也没说。窗外暮色渐深，城头传来换防的梆子声，一声接着一声，催命似的。"""

EVENT_TEMPLATES[5]["text"] = """番禺的六月，海风裹着咸腥灌进刺史府。卢循靠着竹榻读信，窗外蝉鸣聒噪。信是徐道覆从始兴加急送来的——“刘裕北伐，建康空虚，此天赐良机，不可失也。”他搁下信，目光移向墙角的沙盘，长江沿线晋军布防一目了然，而建康方向，确实空了大半。

门被推开，徐道覆风尘仆仆跨进来，甲胄未解便快步上前：“主公，还在犹豫？刘裕率主力北讨南燕，建康留守不过老弱数千，此时不出，等他班师回朝，再无机会！”

卢循坐直了身子，眉头紧皱，手指轻轻敲着案几：“万一刘裕回师……他此人用兵如神，你我……”

徐道覆一掌拍在案上：“等他回师，我等死无葬身之地！建康空虚是实情，江州守军不过万人，且分驻各地。只要迅速攻下寻阳，顺流直下建康，晋人连集结的时间都没有！”

案上茶盏跳了一下，卢循盯着杯中漾开的波纹，沉默了许久。

“好。”他终于开口，“点兵。”

八月初，卢循大军北上。番禺码头樯橹如林，五千步卒列阵登船，三千战船劈开珠江水，两千楼船蔽江而下。卢循登船前回望了一眼番禺城——他知道，此去再无退路。徐道覆站在他身侧，目光灼灼望着北方：“先取寻阳，再下建康。刘裕回来时，让他无家可归。”

【战略指示】卢循北进后，AI将优先攻取寻阳。寻阳陷落后，将沿江全力直扑建康，不再分兵他顾。"""

EVENT_TEMPLATES[6]["text"] = """信报传入番禺时，卢循正在后院浇花。铜壶落在地上，水漫了一地。

他弯腰拾起壶，走向议事厅，步子比平时慢了半拍。徐道覆已在厅中等候，手中攥着一卷文书，见卢循进来，直接摊在案上：“刘裕发檄了。荆州、江州两路水陆并进，旬日之内兵锋可抵始兴。”

卢循没有说话，走到沙盘前低头看着番禺城四周的地形。城北群山环绕，城南水网密布，虽是易守难攻之地，但也意味着——一旦被围，便无路可退。

“主公，与其坐等，不如北上迎敌，在赣水一带设伏……”徐道覆的手指在地图上一划。

“来不及了。”卢循打断他，声音低沉，“刘裕用兵，兵贵神速。他既然敢发檄，大军必然已经开拔。现在北上，正好撞进他的口袋。”他抬眼望向窗外，珠江在午后的日光下泛着白花花的光，“守吧。番禺城墙够厚，粮草够吃半年。他远道而来，水土不服，时间拖久了，退的是他。”

徐道覆沉默片刻，微微点头。传令声很快响彻全城——征丁、闭门、加固城防，四面城门落闸。卢循登城巡视时，看到江面上几艘百姓的渔船正急急驶回港内，船头堆着家当，一个老妇搂着孩子，回头望着番禺城墙，泪水淌了满脸。

卢循收回目光，按了按腰间的剑柄。城在人在，城破人亡——这话他从前听别人说过，如今轮到自己了。"""

EVENT_TEMPLATES[7]["text"] = """船队冲破秦淮河栅栏时，建康城头的火把还没有来得及点亮。

卢循立在旗舰船头，望着夜色中逐渐逼近的石头城轮廓，两岸一片死寂。北上的路上他曾想象过无数次破城的情形——却没想到，真正抵达的时候竟如此平静。城中已经没有像样的抵抗，只剩几个老卒在城墙拐角处放了几箭，箭矢软绵绵地落在水里，连水花都没溅起几朵。

他踏上宣阳门台阶时，一个文官模样的人挡在门前。卢循认出了他——王嘏。王嘏站在那儿，身子微微发抖，但还是开口：“尚书令王嘏……见过卢将军。”卢循没有拔刀，只是从他身旁走过去，擦肩而过时，王嘏听到他说了一句：“城中百官，各安其职。”

太极殿的门敞着，御座空荡荡的。安帝不知所踪，宫人跪了满地，一个老太监缩在柱子后面，筛糠似的哆嗦。

卢循走上丹墀，手抚过御座的扶手，沾了一指灰。他转过身，望向殿门外那片黑沉沉的宫阙——刘裕北伐未归，留下这座空城，像一只剥了壳的蚌。他低头看了看自己的手掌，缓缓在龙椅上坐了下来。

窗外，天边泛起一线鱼肚白。建康换了主人。

而在千里之外的某条官道上，一骑快马正昼夜不停地向北飞驰，马背上驮着印着“急”字的文书——只是它来不及了。

游戏结束。刘裕功业，止于建康城头的那面卢字大旗。"""


def _create_regime_army(
    state: GameState,
    regime_id: int,
    city_id: int,
    unit_types: list[int],
    commander_id: int | None = None,
    army_type: int = 0,
) -> Army:
    commander_id = living_commander_id(state, commander_id)
    if commander_id in state.persons:
        for existing in state.armies.values():
            if existing.commander == commander_id:
                existing.commander = None
    army_id = max(state.armies, default=0) + 1
    army = Army(
        army_id,
        regime_id,
        army_type,
        [{"type": int(unit_type), "count": 1000} for unit_type in unit_types],
        commander=commander_id if commander_id in state.persons else None,
        location_id=city_id,
    )
    state.armies[army_id] = army
    if army.commander in state.persons:
        state.persons[army.commander]["location_id"] = city_id
    return army


def _event_4_condition(state: GameState) -> bool:
    return _date_at_least(state, 405, 8) and not is_regime_eliminated(state, 4)


def _event_4_effect(state: GameState) -> None:
    _create_regime_army(state, 4, city_id_by_name(state, "成都"), [1] * 5)


def _create_lu_xun_forces(state: GameState) -> None:
    # 卢循：五千步兵；徐道覆：三千战船、两千楼船；另有两支五千人的步弓军。
    panyu = city_id_by_name(state, "番禺")
    _create_regime_army(state, 5, panyu, [1] * 5, commander_id=person_id_by_name(state, "卢循"))
    _create_regime_army(state, 5, panyu, [4] * 3 + [6] * 2, commander_id=person_id_by_name(state, "徐道覆"), army_type=1)
    _create_regime_army(state, 5, panyu, [1] * 3 + [3] * 2)
    _create_regime_army(state, 5, panyu, [1] * 3 + [3] * 2)


def _event_5_condition(state: GameState) -> bool:
    from ...rules.diplomacy import truce_active

    return (
        not is_regime_eliminated(state, 5)
        and not state.at_war(state.player_regime_id, 5)
        and not truce_active(state, state.player_regime_id, 5)
        and (state.at_war(state.player_regime_id, 8) or state.at_war(state.player_regime_id, 9))
        and not bool(state.events.get(6, {}).get("triggered"))
    )


def _event_5_effect(state: GameState) -> None:
    _create_lu_xun_forces(state)
    pair = state.relation_pair(state.player_regime_id, 5)
    if pair not in state.wars:
        state.wars.append(pair)
    state.flags[f"war_started:{pair[0]}:{pair[1]}"] = state.turn_number
    state.flags[f"war_aggressor:{pair[0]}:{pair[1]}"] = 5
    state.flags["lu_xun_offensive_targets"] = [city_id_by_name(state, "寻阳"), city_id_by_name(state, "建康")]
    state.regimes[5]["relation_with_main"] = "交战"


def _event_6_condition(state: GameState) -> bool:
    pair = state.relation_pair(state.player_regime_id, 5)
    return (
        not is_regime_eliminated(state, 5)
        and state.at_war(state.player_regime_id, 5)
        and int(state.flags.get(f"war_aggressor:{pair[0]}:{pair[1]}", 0)) == state.player_regime_id
        and not bool(state.events.get(5, {}).get("triggered"))
    )


def _event_6_effect(state: GameState) -> None:
    _create_lu_xun_forces(state)


def _event_7_condition(state: GameState) -> bool:
    from ...rules.military import city_controller

    return not is_regime_eliminated(state, 5) and city_controller(state, city_id_by_name(state, "建康")) == 5


def _event_7_effect(state: GameState) -> None:
    state.flags["game_over"] = True
    state.flags["game_over_reason"] = "卢循攻占建康，晋廷覆亡。"


EVENT_CONDITIONS: dict[int, Callable[[GameState], bool]] = {
    1: _event_1_condition,
    2: _event_2_condition,
    3: _event_3_condition,
    4: _event_4_condition,
    5: _event_5_condition,
    6: _event_6_condition,
    7: _event_7_condition,
}
EVENT_EFFECTS: dict[int, Callable[[GameState], None]] = {
    1: _event_1_effect,
    2: _event_2_effect,
    3: _event_3_effect,
    4: _event_4_effect,
    5: _event_5_effect,
    6: _event_6_effect,
    7: _event_7_effect,
}

# 后续剧情三独立存放，安装到统一事件队列中，旧存档会由 ensure_event_records 自动补齐。
from .events_3 import (
    EVENT_CONDITIONS as FOLLOWUP_3_EVENT_CONDITIONS,
    EVENT_EFFECTS as FOLLOWUP_3_EVENT_EFFECTS,
    EVENT_TEMPLATES as FOLLOWUP_3_EVENT_TEMPLATES,
)

EVENT_TEMPLATES.update(FOLLOWUP_3_EVENT_TEMPLATES)
EVENT_CONDITIONS.update(FOLLOWUP_3_EVENT_CONDITIONS)
EVENT_EFFECTS.update(FOLLOWUP_3_EVENT_EFFECTS)

# 后续剧情四继续使用统一的事件队列；长文本由 story_texts 与规则逻辑分离。
from .events_4 import (
    EVENT_CONDITIONS as FOLLOWUP_4_EVENT_CONDITIONS,
    EVENT_EFFECTS as FOLLOWUP_4_EVENT_EFFECTS,
    EVENT_TEMPLATES as FOLLOWUP_4_EVENT_TEMPLATES,
)

EVENT_TEMPLATES.update(FOLLOWUP_4_EVENT_TEMPLATES)
EVENT_CONDITIONS.update(FOLLOWUP_4_EVENT_CONDITIONS)
EVENT_EFFECTS.update(FOLLOWUP_4_EVENT_EFFECTS)


def ensure_event_records(state: GameState) -> None:
    for event_id, template in EVENT_TEMPLATES.items():
        if event_id not in state.events:
            state.events[event_id] = {**template, "triggered": False}


def queue_start_of_turn_events(state: GameState) -> list[int]:
    """Evaluate events at turn start, apply effects, and queue their text for the UI."""
    ensure_event_records(state)
    triggered_ids: list[int] = []
    queued = [int(x) for x in state.flags.get("pending_story_events", [])]
    for event_id in sorted(EVENT_TEMPLATES):
        event = state.events[event_id]
        if event.get("triggered") and not event.get("repeatable"):
            continue
        if not EVENT_CONDITIONS[event_id](state):
            continue
        EVENT_EFFECTS[event_id](state)
        if not event.get("repeatable"):
            event["triggered"] = True
        if event_id not in queued:
            queued.append(event_id)
        triggered_ids.append(event_id)
        state.add_log(f"事件触发：{event['name']}。{event['effect_description']}")
    state.flags["pending_story_events"] = queued
    return triggered_ids
