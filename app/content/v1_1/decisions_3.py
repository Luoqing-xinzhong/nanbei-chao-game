from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from ...models import GameState
from ...rules.common import RuleError, clamp, is_regime_eliminated
from .events_3 import mark_event_12_triggered, start_liu_yi_rebellion
from .strategies import strategy_completed


DECISION_TEMPLATES: dict[int, dict[str, Any]] = {
    7: {
        "id": 7,
        "name": "羽葆鼓吹",
        "unlock_strategy": 9,
        "summary": "刘裕获得羽葆鼓吹、班剑二十人的殊礼。",
        "effect_description": "刘裕等级+1、基础权力+5，稳定度-5。",
        "choices": [],
        "text": """深秋的建康，一封诏书送到刘裕府邸：特赐羽葆鼓吹、班剑二十人，以彰殊勋。那是天子仪仗才能使用的礼制，前一个得到它的人姓桓。\n\n赐仪之日，二十名班剑甲士分列两行，羽葆鼓吹响彻满城。刘裕骑马走在仪仗中央，回望宫墙上的晋旗，日光落在脸上，明暗各半。这一步迈出去，就再也回不了头了。""",
    },
    8: {
        "id": 8,
        "name": "改授大将军",
        "unlock_strategy": None,
        "summary": "岭南平定后，刘裕受授大将军、都督中外诸军事。",
        "effect_description": "刘裕职务改为大将军，稳定度-5。",
        "choices": [],
        "text": """广州平定的奏报传入朱雀门。岭南既平，天下似乎再无人能与刘裕抗衡。\n\n授职典礼上，王谧展开诏书：“授刘裕大将军，都督中外诸军事。”刘裕跪下接诏，转身面对满朝文武。百官贺声中，有人真心欢喜，有人勉强挤笑。建康已在脚下，可前路忽然更加模糊。""",
    },
    9: {
        "id": 9,
        "name": "寒人主政",
        "unlock_strategy": 10,
        "summary": "刘裕不问门第，任用寒人主持台省与地方政务。",
        "effect_description": "权力分配改为寒人主政；稳定度-5；刘穆之成为亲信；寒门好感+5，高门好感-10。",
        "choices": [],
        "text": """石头城议事厅里，刘裕面前摆着一册密密麻麻的名字。册中没有一个能在《百家谱》中找到的高门姓氏，只有两个字写在页眉：可用。\n\n“台省诸曹、地方郡县，有缺即补，不问门第，唯才是用。”刘穆之摊开空白文书，提笔问道：“主公说，从哪一曹开始？”\n\n诏令发出，建康高门府邸彻夜不熄；台省衙门的灯，也从此不再熄灭。""",
    },
    10: {
        "id": 10,
        "name": "结交门阀",
        "unlock_strategy": 11,
        "summary": "刘裕借王弘之手与江南高门合作。",
        "effect_description": "权力分配改为门阀政治；稳定度+5；王弘成为亲信；高门好感+5，寒门好感-5。",
        "choices": [],
        "text": """刘裕将翻旧的《百家谱》合上：“若不用这些人，这江山坐得稳坐不稳？”刘穆之沉默片刻，答道：“坐不稳。”\n\n三日后，王弘踏雪来到石头城。刘裕将一卷空白任命文书推到他面前：“台省十三曹，王公荐人。”王弘若点头，半座建康也会跟着点头。\n\n任命文书发出那天，乌衣巷里的炭火比往年更旺。江山还是那个江山，只是刀剑之外，又多了一张必须握住的网。""",
    },
    11: {
        "id": 11,
        "name": "任用文官班子",
        "unlock_strategy": 12,
        "summary": "刘裕正式组建自己的台省文官班子。",
        "effect_description": "任命刘穆之、王弘、徐羡之、郑鲜之、褚叔度；傅亮成为亲信；刘穆之领导文官党；获得1号国家修正。",
        "choices": [],
        "text": """战事渐歇，粮赋、考课、刑狱的文书却堆满台省。刘裕召刘穆之、王弘同至议事厅，摊开新班子名单。\n\n尚书令刘穆之、尚书左仆射王弘、尚书右仆射徐羡之、中书侍郎郑鲜之、散骑常侍褚叔度，五人同日出任。诸曹文书自此分作轻重缓急，流转如轮。\n\n朝廷终于有了朝廷的样子。只要刘穆之仍主持台省，文官党便不会再生异动。""",
    },
    12: {
        "id": 12,
        "name": "处决刘毅",
        "unlock_strategy": 13,
        "summary": "刘裕密谋除掉坐镇荆州的刘毅。",
        "effect_description": "70%成功处决刘毅；失败时刘毅与谢混在荆州起兵。",
        "choices": [],
        "text": "刘裕以宴请为名召刘毅入建康。一封密令向西送出，同袍的道路也走到了尽头。",
    },
    13: {
        "id": 13,
        "name": "处决诸葛长民",
        "unlock_strategy": 13,
        "summary": "刘裕设宴处决诸葛长民。",
        "effect_description": "诸葛长民死亡；刘裕基础权力+5；稳定度+5。",
        "choices": [],
        "text": """建康秋夜，刘裕设宴石头城，只邀诸葛长民一人。酒过三巡，诸葛长民拍案道：“公若早两年称帝，兄弟我头一个拥戴！”\n\n夜深告辞时，两侧帷幕后闪出甲士。倒地之前，诸葛长民忽然笑了：“韩信……彭越……今日轮到我了……”\n\n翌日告示只写：豫州刺史诸葛长民暴疾身亡。城中无人追问，像水渗入沙中一般无声。""",
    },
}


LIU_YI_SUCCESS_TEXT = """建康入秋后的第一场雨下了一整夜。刘穆之将密报放在案角：“刘毅在荆州私蓄甲士，再拖下去，荆襄便不再是朝廷的荆襄。”\n\n刘裕沉默许久，传令以宴请为名召刘毅入京。半月后，刘毅在建康被收押，三日后以谋反罪伏诛。消息传回荆州，各郡守将纷纷上表效忠。\n\n那封“刘毅已伏法”的密报被刘裕凑到烛火上，纸页卷曲、发黑，化为灰烬。风一吹，什么也没有剩下。"""

LIU_YI_FAILURE_TEXT = """建康密使还在路上，荆州刺史府的灯便先亮了。密报已经泄露：酒宴是假，鸿门宴是真。\n\n刘毅将纸揉成一团：“我跟他从京口一起杀出来，如今他坐稳建康，便嫌我碍眼了？”谢混低声道：“荆州尚有兵马，北面还可联络后秦。”\n\n“那就反。”三日后，刘毅在江陵誓师，谢混率五千战船顺江而下，刘毅自领五千步卒。昔日同袍的路，终究没有走完同一条。"""


@dataclass(frozen=True)
class Story3DecisionResult:
    text: str
    effect_description: str


def _person_id(state: GameState, name: str) -> int:
    person_id = next(
        (int(person["id"]) for person in state.persons.values() if state.person_name(int(person["id"])) == name),
        None,
    )
    if person_id is None:
        raise RuleError(f"人物配置中缺少{name}")
    return person_id


def _alive(state: GameState, name: str) -> bool:
    try:
        return int(state.persons[_person_id(state, name)].get("status", 0)) in {1, 2, 3}
    except RuleError:
        return False


def _set_office(state: GameState, name: str, office: str) -> None:
    person_id = _person_id(state, name)
    internal = state.player_regime.setdefault("internal", {})
    for key, occupant in list(internal.items()):
        if not isinstance(occupant, list) and (occupant == person_id or key == office):
            internal[key] = None
    internal[office] = person_id


def _opinion(state: GameState, name: str, delta: int | None = None, value: int | None = None) -> None:
    person = state.persons[_person_id(state, name)]
    person["opinion_of_player"] = int(
        clamp(value if value is not None else int(person.get("opinion_of_player", 0)) + int(delta or 0), -100, 100)
    )


def _base_power(state: GameState, name: str, amount: int) -> None:
    person = state.persons[_person_id(state, name)]
    attributes = person.setdefault("attributes", {})
    value = max(0, int(attributes.get("base_power", 0)) + int(amount))
    if int(person.get("level", 0)) < 6:
        value = min(100, value)
    attributes["base_power"] = value


def _confidant(state: GameState, name: str) -> None:
    person_id = _person_id(state, name)
    if person_id not in state.confidants:
        state.confidants.append(person_id)


def _kill(state: GameState, name: str) -> None:
    person_id = _person_id(state, name)
    state.persons[person_id]["status"] = 4
    state.persons[person_id]["death_year"] = state.year
    for army in state.armies.values():
        if army.commander == person_id:
            army.commander = None


def decision_visible(state: GameState, decision_id: int, completed: set[int]) -> bool:
    if decision_id in completed:
        return False
    if decision_id == 8:
        return is_regime_eliminated(state, 5) and "广州" in state.player_regime.get("regions", [])
    unlock = DECISION_TEMPLATES[decision_id].get("unlock_strategy")
    return bool(unlock and strategy_completed(state, int(unlock)))


def decision_available(state: GameState, decision_id: int, completed: set[int]) -> tuple[bool, str]:
    if not decision_visible(state, decision_id, completed):
        return False, "尚未解锁或已经完成"
    if decision_id == 7 and int(state.player_regime.get("stability", 0)) < 50:
        return False, "稳定度需要达到50"
    if decision_id == 12:
        if not _alive(state, "刘毅"):
            return False, "刘毅已经死亡"
        if bool(state.events.get(12, {}).get("triggered")):
            return False, "刘毅造反事件已经发生"
    if decision_id == 13 and not _alive(state, "诸葛长民"):
        return False, "诸葛长民已经死亡"
    return True, "可以执行"


def _family_opinions(state: GameState, high_delta: int, humble_delta: int) -> None:
    for person in state.persons.values():
        family = state.families.get(int(person.get("family_id") or 0), {})
        family_type = int(family.get("family_type", -1))
        delta = high_delta if family_type == 1 else humble_delta if family_type == 2 else 0
        if delta:
            person["opinion_of_player"] = int(clamp(person.get("opinion_of_player", 0) + delta, -100, 100))


def execute(state: GameState, decision_id: int, rng: random.Random | None = None) -> Story3DecisionResult:
    template = DECISION_TEMPLATES[decision_id]
    text = str(template["text"])
    effect = str(template["effect_description"])
    regime = state.player_regime
    if decision_id == 7:
        state.player["level"] = int(state.player.get("level", 0)) + 1
        _base_power(state, "刘裕", 5)
        regime["stability"] = int(clamp(regime.get("stability", 0) - 5, 0, 100))
    elif decision_id == 8:
        _set_office(state, "刘裕", "grand_general")
        regime["stability"] = int(clamp(regime.get("stability", 0) - 5, 0, 100))
    elif decision_id == 9:
        state.laws["power"] = 2
        regime["stability"] = int(clamp(regime.get("stability", 0) - 5, 0, 100))
        _opinion(state, "刘穆之", value=100)
        _confidant(state, "刘穆之")
        _family_opinions(state, high_delta=-10, humble_delta=5)
    elif decision_id == 10:
        state.laws["power"] = 1
        regime["stability"] = int(clamp(regime.get("stability", 0) + 5, 0, 100))
        _opinion(state, "王弘", value=100)
        _confidant(state, "王弘")
        _family_opinions(state, high_delta=5, humble_delta=-5)
    elif decision_id == 11:
        for name, office in (
            ("刘穆之", "shangshu_ling"),
            ("王弘", "left_shangshu"),
            ("徐羡之", "right_shangshu"),
            ("郑鲜之", "zhongshu_shilang"),
            ("褚叔度", "sanqi_changshi"),
        ):
            _set_office(state, name, office)
            _opinion(state, name, delta=10)
        _opinion(state, "傅亮", delta=50)
        _confidant(state, "傅亮")
        party = next((item for item in state.parties.values() if item.get("name") == "文官党"), None)
        if party is not None:
            liu_muzhi = _person_id(state, "刘穆之")
            party["leader"] = liu_muzhi
            party["members"] = list(dict.fromkeys([liu_muzhi] + [int(x) for x in party.get("members", [])]))
            party.pop("coup", None)
    elif decision_id == 12:
        if (rng or random).random() < 0.70:
            _kill(state, "刘毅")
            regime["stability"] = int(clamp(regime.get("stability", 0) + 10, 0, 100))
            _base_power(state, "刘裕", 10)
            text = LIU_YI_SUCCESS_TEXT
            effect = "处决成功：刘毅死亡，稳定度+10，刘裕基础权力+10。"
        else:
            mark_event_12_triggered(state)
            start_liu_yi_rebellion(state)
            text = LIU_YI_FAILURE_TEXT
            effect = "处决失败：刘毅在荆州造反，谢混率五千战船水军响应。"
    elif decision_id == 13:
        _kill(state, "诸葛长民")
        _base_power(state, "刘裕", 5)
        regime["stability"] = int(clamp(regime.get("stability", 0) + 5, 0, 100))
    return Story3DecisionResult(text, effect)
