from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any

from ...models import Army, GameState
from ...rules.common import RuleError, clamp, remove_emperor_civil_offices
from .strategies import strategy_completed


RETURN_OF_EMPEROR_TEXT = """江陵克复后第三日，晋安帝司马德宗的御驾北返建康。

车驾过芜湖时，岸边已有迎驾的彩棚，只是年久失修，半边塌在泥里。侍从们手忙脚乱地去扶，帝座上的年轻人却毫无反应——安帝自幼口不能言，不辨寒暑，唯痴痴望着窗外江涛，嘴角挂着涎水。

到达建康那日，朱雀门外百官跪迎。刘裕位于班首，冠冕齐整。銮驾停稳，宦官掀帘搀扶，安帝摇摇晃晃走下，脚下踩到一枚碎瓦片，身子一歪，险些摔倒。刘裕眼疾手快，上前一步伸手托住皇帝肘弯。安帝稳住身子，抬头看了看他，忽然笑了，喉咙里发出含糊的一声“裕”。

刘裕松开手，退后三步，大礼参拜：“臣刘裕，迎陛下还都。”

他身后，百官伏地山呼万岁。王谧俯在人群中，悄悄抬眼——他看到刘裕额头抵着地面，颈后青筋微凸。那是用力克制某种情绪的样子。而安帝依旧站在那里傻笑，一只手还伸着，仿佛在等谁来牵他。"""


BEIFU_INTRO_TEXT = """建康初定，江陵未下。桓玄虽死，其从子桓振与宗室桓谦仍据荆州，收拢残兵，再立声势。江陵城头桓字旗又升了起来，各路溃卒闻风汇聚，旬日之间已得数千人。刘裕坐镇石头城，舆图上江陵一线朱砂未干。他清楚，此城不拔，建康便永无宁日。

可荆州水网密布，江陵城高壕深，这一仗谁来打？刘毅性刚，每战必身先士卒，但好大喜功；刘道规持重，用兵如弈棋，步步为营；何无忌长于水战，却资历尚浅，恐难服众。三人立于堂下，各怀心思。刘裕的手指在舆图上缓缓敲了两下，终于开口——

“北府旧部，该动了。”

殿外春风料峭，战旗猎猎作响。"""


BEIFU_CHOICE_TEXTS = {
    "刘毅": """“公且安坐建康，看某提桓振首级归来！”

刘毅起身出列，声震屋瓦。他本就高大，此时昂首挺胸，甲叶铿然作响，满殿目光顿时被他一人吸去。他向刘裕一拱手，又侧头瞥了何无忌一眼，嘴角微微一挑——那一眼带着笑，却把“你不行”三个字写得清清楚楚。何无忌垂下眼，没有接话。刘道规端着茶盏，吹了吹浮沫，不紧不慢地啜了一口。

当天下午，刘毅便传令各营，点兵五千自领中军，命刘道规率两千步卒为左翼，何无忌率战船二百沿江而下，截断江陵水运。三道军令写得干净利落，连刘裕看了也暗自点头。临行前夜，刘毅独坐帐中擦拭佩刀，对亲信道：“等回来时，这刀上蘸的，得是桓振的血。”

帐外月色如霜，大军整装待发。""",
    "刘道规": """刘裕的目光最终落在这个一直沉默的弟弟身上。刘道规放下茶盏，站起身，整了整衣领，向众人团团作了一揖。他的声音不疾不徐：“请兄信得过我，我便当仁不让。但有一言在先——此战，不是我一个人的战功，是在座每一位的。”

他走到舆图前，手指在江陵城四周画了一个圈：“江陵城坚，急攻恐折兵损将。我的意思，以步军五千围城困敌，逼其出战；毅兄率精兵两千埋伏于汉水北岸，伺机截其援军；何兄水师溯江而上，断其粮道。三路并进，彼首尾不能相顾。”他讲得极细，连每一路何时埋锅造饭、何处设置哨探都一一说明。刘毅起初板着脸，听到后来，眉眼渐渐松下来，最后哼了一声：“还算周到。”何无忌则频频点头，已经开始盘算水师的航程。

刘裕从袖中取出一枚虎符，交到刘道规手中时，用力握了握弟弟的手。""",
    "何无忌": """“无忌不才，但有一事要向公请命。”何无忌出列时，步伐不紧不慢，与刘毅的昂首阔步截然不同。他走到刘裕面前，拱手深揖，“江陵之敌，强在水陆相依。桓振若闭城不出，我军顿兵坚城之下，日久必生变。我请率水师先入长江，扼住江津渡口，断其外援，再以步骑从陆路压上。水陆夹击，江陵便是一座孤城。”

他说得平实，却字字落到实处。刘毅在旁边哂道：“何兄是怕陆上打不赢，想躲到船上去？”何无忌这才抬眼看他，语气温和：“毅兄若愿同行，我水师舱位还空着。”一句话把刘毅噎住。刘道规站出来打圆场：“何兄所言极是，水师若断其粮道，江陵不攻自破。我愿领步军听何兄调遣。”何无忌对他感激地一揖。刘毅僵着脸站了片刻，最终也只是冷冷道：“那就看看你水里能翻出什么浪来。”

当夜，何无忌的帅船上，灯火亮到三更。案上铺满水道图，密密的朱批小字如蚁群般爬满了每一道河湾。""",
}


OCTOBER_REWARDS_TEXT = """十月初一，建康城头遍插旌旗，朱雀大街上洒水净尘。安帝虽不晓世事，也被宫人搀扶着坐上了太极殿的御座，呆呆望着殿中济济一堂的文武。

这是桓玄之乱后第一次大朝会。南征荆州的功勋们甲胄未卸便入宫候旨，刘毅站在武将班首，频频整理衣领；刘道规低头摩挲着掌心的茧；何无忌则安静立在柱旁，眼角余光却一直落在刘裕身上。

丹墀之上，诏书已拟好——谁升何职，谁封何爵，满朝都等着一锤定音。刘裕站在百官之前，背对御座，面向众人。殿内静得能听到窗外桂花的落瓣声。他掌心有汗，但脸上不露分毫。

风从殿门灌进来，吹得诏书沙沙作响。"""

OCTOBER_CHOICE_TEXTS = {
    "要的多一些": """“录尚书事……”刘裕看着诏书上这几个字，沉默了片刻。

殿中鸦雀无声。录尚书事，总揽台省政务，自魏晋以来便是实权之首。桓玄当年第一个自封的，就是此职。刘毅在班列中捏紧了拳头，刘道规低头不语，何无忌的目光从刘裕脸上迅速移开。

刘裕没有推辞。他只是慢慢走到殿中央，面朝御座，大礼参拜：“臣，领旨。”声音不高，却像一块石头砸进静水里，涟漪一圈一圈荡开。

当夜，王谧府中灯烛未熄。有人看见王家老仆急匆匆从后门出去，往城东的几家高门递了帖子。刘裕回到府中，孟昶迎上来低声道：“王谧那边连夜走动了。”刘裕解下披风，神色平静：“早料到了。让他们动吧，动总比不动好。”

接下来的几天，台省里递上来的奏章明显少了——高门们在用沉默表达态度。录尚书事的印是铜铸的，可握在手里，比铁还沉。""",
    "收敛一些": """“侍中……”刘裕看着诏书上的任命，将那道黄绢又读了一遍。

殿中有人交换眼色。侍中虽是近臣、出入宫禁，位份尊贵，但比录尚书事终究低了一截。刘裕最亲信的功勋们都在等他抬头说一句“不妥”，可他只是平静地将诏书收好，转身朝御座一揖：“臣，领旨。”

站在一旁的王谧肉眼可见地松了一口气。他向前迈了半步，正要开口说几句场面话，刘裕却先转过身来，朝他拱了拱手：“王公，日后台省诸事，还要倚仗您多费心。”王谧连忙还礼，连说“不敢”。

散朝后，刘道规追上刘裕：“兄，录尚书事……”刘裕打断他，轻声道：“不急在一时。”他看着远处宫墙上初升的日光，掸了掸衣袍，“荆州刚定，朝堂未稳，若此时将王谧等人逼得太紧，反生变乱。退一步，海阔天空。”

身后，高门官员们三三两两走出宫门，眉宇间分明松弛了许多。宫墙根下，几个小宦官在偷偷议论：“刘将军竟是这样的性子？”远处，十月的建康天高云淡，宫阙在阳光下泛着柔和的光。""",
}

PANYU_SUCCESS_TEXT = """建康的议事厅里，舆图从案头一直铺到门槛。刘裕蹲在地上，手指沿着长江一路向南划过，最终停在岭南那一片曲折的海岸线上。卢循据广州已有两年，番禺城高粮足，若从陆路进兵，千里山险，粮道难继，未到城下先已疲敝。

孙处站在一旁看了许久，忽然开口：“主公，陆路走不通，为何不走海路？”

满堂皆惊。自晋室南渡以来，海路用兵前所未有。孙处却走到舆图前，手掌按在番禺正南那片空白处：“给我一支船队，趁东南风起，沿海南下，绕过卢循的耳目，番禺必定不备。一旦拿下番禺，卢循便失了根本，不攻自破。”

刘裕抬起头，看着这个平日里沉默寡言的部将，片刻后点了点头：“多少人够？”

“三千足矣。兵贵精不贵多，船贵快不贵大。”孙处的声音不高，却笃定得让人无法质疑。

刘裕站起身，拍了拍膝盖上的灰：“那就给你三千人，战船四十艘。成与不成，都在这一趟了。”

孙处抱拳一揖，转身出门。风从门外灌进来，吹得舆图哗哗翻卷，番禺那一角被掀起又落下，像是海面上起伏的浪。

船队出海那日，石头城外水雾弥漫。四十艘战船扯满风帆，借着东南季风，一昼夜便驶过了姑孰。孙处立在旗舰船头，手中捏着几卷抄录的海道图，图上密密麻麻标注着暗礁与潮汐时辰——那是他从渔民口中一个字一个字问来的。

卢循没有料到这一路。从沿海哨探到番禺城头守卒，所有人都以为晋军会从赣水南下，谁会想到有人把船开进了茫茫大海？当孙处的旗帜出现在番禺水门外时，城上守军还在换防，炊烟正从街巷间袅袅升起。

“登陆！”孙处拔出佩刀，第一个跳下船舷，海水没到腰际，他踉跄一步便稳住身形，率士卒冲上沙滩。

番禺城门大敞，守将率众仓促迎战，不到两个时辰便溃散。孙处踏进城池时，城中百姓关门闭户，只有几只狗在空巷里吠叫不止。他在城头插上晋旗，草拟捷报时笔蘸墨汁的手还在微微发抖——是海风冻的，还是别的什么，只有他自己知道。

一个月后，捷报送达建康。刘裕看了三遍，轻声道：“南边稳了。”"""

PANYU_FAILURE_TEXT = """船队南下第七日，东南风忽然转向。

孙处站在船头，望着天色从铅灰变成墨黑，海浪翻涌如沸。老舵手扯着嗓子喊：“将军，风暴要来了！须寻港湾躲避！”孙处攥紧栏杆，望着前方若隐若现的海岸线——按海道图推算，距番禺已不足两日航程。他咬了咬牙：“继续南下，抢在风暴前靠岸！”

可他低估了南海的风。

当夜，飓风骤起，四十艘战船被巨浪冲散。孙处的旗舰断了桅杆，随浪漂流三日，好不容易在珠江口靠岸时，只剩七艘船勉强跟了上来。更糟的是，卢循早已获悉晋军出海的消息，在登陆滩涂两侧设下伏兵。孙处踩上沙滩时，两翼箭如雨下。

“结阵！结阵！”他举盾挡箭，率残部拼死突围。箭矢削去了他半片头盔，鲜血顺着额头淌进眼里，他抹了一把，继续向前冲。可他身边士卒越来越少，到后来只剩二十余人被围在一处礁石旁。

孙处靠在石壁上喘息，低头看了看手中断成两截的佩刀，抬头望了望不远处的番禺城郭——近在咫尺，终究是够不到了。

“给主公送信……”他对身边的亲兵说，“就说……孙处无能。”

亲兵摇头不肯走，孙处一把推开他：“走！”他持着半截刀身站起来，迎着围上来的敌军冲了过去。海水漫上沙滩，将血迹一寸一寸冲淡。远处海面上，几艘残船正仓皇北返，风帆在晨雾中越来越小。

一个月后，建康收到消息。刘裕将那张残破的海道图收进袖中，久久没有说话。"""


DECISION_TEMPLATES: dict[int, dict[str, Any]] = {
    1: {
        "id": 1,
        "name": "天子反正",
        "unlock_strategy": 1,
        "summary": "晋安帝返回建康。",
        "effect_description": "司马德宗返回建康并成为晋帝；稳定度+10；改元义熙。",
        "text": RETURN_OF_EMPEROR_TEXT,
        "choices": [],
    },
    2: {
        "id": 2,
        "name": "组织北府军",
        "unlock_strategy": 2,
        "summary": "北府军出征荆州，从刘毅、刘道规、何无忌中选出主将。",
        "effect_description": "消耗200国库，在建康组建五千主力、两千步兵和两千水军。",
        "text": BEIFU_INTRO_TEXT,
        "choices": ["刘毅", "刘道规", "何无忌"],
        "choice_prompt": "选择北府军主将",
    },
    3: {
        "id": 3,
        "name": "十月封赏",
        "unlock_strategy": 3,
        "summary": "为平定荆州论功行赏。",
        "effect_description": "根据刘裕索取的官职高低，调整朝臣官职、权力、等级、好感与稳定度。",
        "text": OCTOBER_REWARDS_TEXT,
        "choices": ["要的多一些", "收敛一些"],
        "choice_prompt": "刘裕应当如何接受封赏",
    },
    4: {
        "id": 4,
        "name": "山阳援军",
        "unlock_strategy": 6,
        "summary": "派索邈在山阳组织一支援军。",
        "effect_description": "国库-150，在山阳组建三千步兵，由索邈统领。",
        "text": "索邈奉命赶赴山阳，招募三千步卒，整军待援。",
        "choices": [],
    },
    5: {
        "id": 5,
        "name": "山阴援军",
        "unlock_strategy": 6,
        "summary": "派庾悦在山阴组织一支援军。",
        "effect_description": "国库-200，在山阴组建三千步兵、两千弓兵，由庾悦统领。",
        "text": "庾悦奉命在山阴整编步弓五千，准备驰援南方战线。",
        "choices": [],
    },
    6: {
        "id": 6,
        "name": "海路进攻番禺",
        "unlock_strategy": 6,
        "summary": "派孙处走海路奇袭番禺。",
        "effect_description": "国库-200；空城必胜，否则有70%成功率。失败将损失五千预备役且孙处死亡。",
        "text": "孙处请求率船队沿海南下，绕过卢循耳目，直取番禺。",
        "choices": [],
    },
}

from .decisions_3 import (
    DECISION_TEMPLATES as FOLLOWUP_3_DECISION_TEMPLATES,
    decision_available as followup_3_decision_available,
    decision_visible as followup_3_decision_visible,
    execute as execute_followup_3_decision,
)
from .decisions_4 import (
    DECISION_TEMPLATES as FOLLOWUP_4_DECISION_TEMPLATES,
    decision_available as followup_4_decision_available,
    decision_visible as followup_4_decision_visible,
    execute as execute_followup_4_decision,
)

DECISION_TEMPLATES.update(FOLLOWUP_3_DECISION_TEMPLATES)
DECISION_TEMPLATES.update(FOLLOWUP_4_DECISION_TEMPLATES)


@dataclass(frozen=True)
class DecisionResult:
    name: str
    summary: str
    text: str
    effect_description: str


def completed_decisions(state: GameState) -> list[int]:
    values = state.flags.setdefault("completed_decisions", [])
    return [int(item) for item in values]


def decision_visible(state: GameState, decision_id: int) -> bool:
    if decision_id in FOLLOWUP_4_DECISION_TEMPLATES:
        return followup_4_decision_visible(state, decision_id, set(completed_decisions(state)))
    if decision_id in FOLLOWUP_3_DECISION_TEMPLATES:
        return followup_3_decision_visible(state, decision_id, set(completed_decisions(state)))
    template = DECISION_TEMPLATES[decision_id]
    return decision_id not in completed_decisions(state) and strategy_completed(state, int(template["unlock_strategy"]))


def _region_by_name(state: GameState, name: str) -> dict | None:
    return next((region for region in state.regions.values() if region.get("name") == name), None)


def decision_available(state: GameState, decision_id: int) -> tuple[bool, str]:
    if decision_id in FOLLOWUP_4_DECISION_TEMPLATES:
        return followup_4_decision_available(state, decision_id, set(completed_decisions(state)))
    if decision_id in FOLLOWUP_3_DECISION_TEMPLATES:
        return followup_3_decision_available(state, decision_id, set(completed_decisions(state)))
    if not decision_visible(state, decision_id):
        return False, "尚未解锁或已经完成"
    if decision_id == 1:
        jingzhou = _region_by_name(state, "荆州")
        if not jingzhou or int(jingzhou.get("controller", 0)) != state.player_regime_id:
            return False, "需要晋实际控制荆州"
        if (state.year, state.month) < (405, 1):
            return False, "需要到公元405年正月"
    elif decision_id == 2 and int(state.player_regime.get("treasury", 0)) < 200:
        return False, "需要至少200国库"
    elif decision_id in {4, 5, 6}:
        if not state.at_war(state.player_regime_id, 5):
            return False, "必须正在与卢循交战"
        required = {4: 150, 5: 200, 6: 200}[decision_id]
        if int(state.player_regime.get("treasury", 0)) <= required:
            return False, f"国库必须大于{required}"
        if decision_id == 6:
            guangzhou = _region_by_name(state, "广州")
            if not guangzhou or int(guangzhou.get("controller", 0)) != 5:
                return False, "广州必须由卢循控制"
            panyu = _city_id(state, "番禺")
            garrison = sum(army.soldiers for army in state.armies.values() if army.location_id == panyu and army.regime_id == 5)
            if garrison > 5000:
                return False, "番禺守军超过5000人"
    return True, "可以执行"


def _person_id(state: GameState, name: str) -> int:
    person_id = next((int(person["id"]) for person in state.persons.values() if state.person_name(int(person["id"])) == name), None)
    if person_id is None:
        raise RuleError(f"人物配置中缺少{name}")
    return person_id


def _city_id(state: GameState, name: str) -> int:
    city_id = next((int(city["id"]) for city in state.cities.values() if city.get("name") == name), None)
    if city_id is None:
        raise RuleError(f"城市配置中缺少{name}")
    return city_id


def _adjust_opinion(state: GameState, name: str, amount: int) -> None:
    person = state.persons[_person_id(state, name)]
    person["opinion_of_player"] = int(clamp(person.get("opinion_of_player", 0) + amount, -100, 100))


def _create_army(state: GameState, commander_name: str, battalions: int, naval: bool = False) -> Army:
    from ...rules.common import living_commander_id

    commander = living_commander_id(state, _person_id(state, commander_name))
    for army in state.armies.values():
        if army.commander == commander:
            army.commander = None
    army_id = max(state.armies, default=0) + 1
    army = Army(
        id=army_id,
        regime_id=state.player_regime_id,
        army_type=1 if naval else 0,
        units=[{"type": 4 if naval else 1, "count": 1000} for _ in range(battalions)],
        commander=commander,
        location_id=_city_id(state, "建康"),
    )
    state.armies[army_id] = army
    if commander:
        state.persons[commander]["location_id"] = army.location_id
    return army


def _create_custom_army(state: GameState, commander_name: str, city_name: str, units: list[tuple[int, int]], naval: bool = False) -> Army:
    from ...rules.common import living_commander_id

    commander = living_commander_id(state, _person_id(state, commander_name))
    for army in state.armies.values():
        if army.commander == commander:
            army.commander = None
    army_id = max(state.armies, default=0) + 1
    army = Army(
        id=army_id,
        regime_id=state.player_regime_id,
        army_type=1 if naval else 0,
        units=[{"type": unit_type, "count": 1000} for unit_type, battalions in units for _ in range(battalions)],
        commander=commander,
        location_id=_city_id(state, city_name),
    )
    state.armies[army_id] = army
    if commander:
        state.persons[commander]["location_id"] = army.location_id
    return army


def _execute_return_of_emperor(state: GameState) -> str:
    emperor_id = _person_id(state, "司马德宗")
    state.persons[emperor_id]["location_id"] = _city_id(state, "建康")
    state.persons[emperor_id]["level"] = 10
    state.player_regime["internal"]["emperor"] = emperor_id
    remove_emperor_civil_offices(state, state.player_regime_id)
    state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) + 10, 0, 100))
    state.flags["era_name"] = "义熙"
    state.flags["era_start_year"] = 405
    return RETURN_OF_EMPEROR_TEXT


def _execute_organize_beifu(state: GameState, choice: str | None) -> str:
    if choice not in DECISION_TEMPLATES[2]["choices"]:
        raise RuleError("必须从刘毅、刘道规、何无忌中选择主将")
    state.player_regime["treasury"] -= 200
    if choice == "刘毅":
        _create_army(state, "刘毅", 5, naval=True)
        _create_army(state, "刘道规", 2)
        _create_army(state, "何无忌", 2, naval=True)
        attributes = state.persons[_person_id(state, "刘毅")].setdefault("attributes", {})
        attributes["base_power"] = int(clamp(attributes.get("base_power", 0) + 20, 0, 100))
        _adjust_opinion(state, "刘毅", 20)
    elif choice == "刘道规":
        _create_army(state, "刘道规", 5, naval=True)
        _create_army(state, "刘毅", 2)
        _create_army(state, "何无忌", 2, naval=True)
        _adjust_opinion(state, "刘毅", -30)
    else:
        _create_army(state, "何无忌", 5, naval=True)
        _create_army(state, "刘毅", 2)
        _create_army(state, "刘道规", 2, naval=True)
        _adjust_opinion(state, "刘毅", -50)
        _adjust_opinion(state, "刘道规", -5)
        _adjust_opinion(state, "何无忌", 20)
    return BEIFU_CHOICE_TEXTS[choice]


def _set_player_office(state: GameState, office: str) -> None:
    player_id = int(state.player["id"])
    internal = state.player_regime["internal"]
    for key, occupant in list(internal.items()):
        if occupant == player_id or key == office:
            if not isinstance(occupant, list):
                internal[key] = None
    internal[office] = player_id


def _set_person_office(state: GameState, person_id: int, office: str) -> None:
    internal = state.player_regime["internal"]
    for key, occupant in list(internal.items()):
        if occupant == person_id or key == office:
            if not isinstance(occupant, list):
                internal[key] = None
    internal[office] = person_id


def _adjust_base_power(state: GameState, name: str, amount: int) -> None:
    person = state.persons[_person_id(state, name)]
    attributes = person.setdefault("attributes", {})
    value = max(0, int(attributes.get("base_power", 0)) + int(amount))
    if int(person.get("level", 0)) < 6:
        value = min(100, value)
    attributes["base_power"] = value


def _execute_october_rewards(state: GameState, choice: str | None) -> tuple[str, str]:
    if choice not in DECISION_TEMPLATES[3]["choices"]:
        raise RuleError("必须选择封赏态度")
    if choice == "要的多一些":
        _set_player_office(state, "lu_shangshu")
        _adjust_base_power(state, "刘裕", 15)
        for name in ("王谧", "王嘏"):
            _adjust_opinion(state, name, -50)
        for person in state.persons.values():
            family = state.families.get(int(person.get("family_id") or 0), {})
            if int(family.get("family_type") or -1) == 1:
                person["opinion_of_player"] = int(clamp(person.get("opinion_of_player", 0) - 30, -100, 100))
        state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) - 10, 0, 100))
        liu_yi = state.persons[_person_id(state, "刘毅")]
        liu_yi["level"] = int(liu_yi.get("level", 0)) + 1
        _adjust_base_power(state, "刘毅", 10)
        _adjust_opinion(state, "刘毅", 20)
        liu_daogui = state.persons[_person_id(state, "刘道规")]
        liu_daogui["level"] = int(liu_daogui.get("level", 0)) + 1
        _set_person_office(state, int(liu_daogui["id"]), "sanqi_shilang1")
        _adjust_opinion(state, "刘道规", 30)
        he_wuji = state.persons[_person_id(state, "何无忌")]
        he_wuji["level"] = int(he_wuji.get("level", 0)) + 1
        _adjust_opinion(state, "何无忌", 20)
        effect = "刘裕任录尚书事并强化功勋集团；高门好感下降，稳定度-10。"
    else:
        _set_player_office(state, "shizhong")
        _adjust_base_power(state, "刘裕", 10)
        for name in ("王谧", "王嘏"):
            _adjust_opinion(state, name, 10)
        for person in state.persons.values():
            family = state.families.get(int(person.get("family_id") or 0), {})
            if int(family.get("family_type") or -1) == 1:
                person["opinion_of_player"] = int(clamp(person.get("opinion_of_player", 0) + 5, -100, 100))
        state.player_regime["stability"] = int(clamp(state.player_regime.get("stability", 0) + 5, 0, 100))
        for name in ("刘毅", "刘道规", "何无忌"):
            person = state.persons[_person_id(state, name)]
            person["level"] = int(person.get("level", 0)) + 1
            _adjust_base_power(state, name, 5)
        effect = "刘裕任侍中并安抚高门；稳定度+5，三位功勋等级与基础权力提升。"
    return OCTOBER_CHOICE_TEXTS[choice], effect


def _execute_reinforcement(state: GameState, decision_id: int) -> str:
    if decision_id == 4:
        state.player_regime["treasury"] -= 150
        _create_custom_army(state, "索邈", "山阳", [(1, 3)])
        return DECISION_TEMPLATES[4]["text"]
    state.player_regime["treasury"] -= 200
    _create_custom_army(state, "庾悦", "山阴", [(1, 3), (3, 2)])
    return DECISION_TEMPLATES[5]["text"]


def _execute_panyu_raid(state: GameState, rng: random.Random | None) -> tuple[str, str]:
    state.player_regime["treasury"] -= 200
    panyu = _city_id(state, "番禺")
    defenders = [army for army in state.armies.values() if army.location_id == panyu and army.regime_id == 5]
    success = not defenders or (rng or random).random() < 0.70
    if success:
        for army in defenders:
            state.armies.pop(army.id, None)
        guangzhou = _region_by_name(state, "广州")
        if guangzhou:
            guangzhou["controller"] = state.player_regime_id
        _create_custom_army(state, "孙处", "番禺", [(1, 5)])
        return PANYU_SUCCESS_TEXT, "奇袭成功：晋控制番禺并获得孙处统领的五千步兵。"
    state.player_regime["reserve_army"] = max(0, int(state.player_regime.get("reserve_army", 0)) - 5000)
    sun_chu = state.persons[_person_id(state, "孙处")]
    sun_chu["status"] = 4
    sun_chu["death_year"] = state.year
    return PANYU_FAILURE_TEXT, "奇袭失败：损失五千预备役，孙处死亡。"


def execute_decision(state: GameState, decision_id: int, choice: str | None = None, rng: random.Random | None = None) -> DecisionResult:
    if state.phase_index != 0:
        raise RuleError("决议只能在政治阶段执行")
    available, reason = decision_available(state, decision_id)
    if not available:
        raise RuleError(reason)
    template = DECISION_TEMPLATES[decision_id]
    effect_description = template["effect_description"]
    if decision_id == 1:
        text = _execute_return_of_emperor(state)
    elif decision_id == 2:
        text = _execute_organize_beifu(state, choice)
    elif decision_id == 3:
        text, effect_description = _execute_october_rewards(state, choice)
    elif decision_id in {4, 5}:
        text = _execute_reinforcement(state, decision_id)
    elif decision_id == 6:
        text, effect_description = _execute_panyu_raid(state, rng)
    elif decision_id in FOLLOWUP_4_DECISION_TEMPLATES:
        outcome = execute_followup_4_decision(state, decision_id, choice)
        text, effect_description = outcome.text, outcome.effect_description
    else:
        outcome = execute_followup_3_decision(state, decision_id, rng)
        text, effect_description = outcome.text, outcome.effect_description
    values = state.flags.setdefault("completed_decisions", [])
    values.append(decision_id)
    state.add_log(f"决议完成：{template['name']}。{effect_description}")
    if decision_id == 2:
        result_name = f"{template['name']} · {choice}为主将"
        result_summary = f"刘裕任命{choice}统领出征荆州的北府军。"
    elif decision_id == 3:
        result_name = f"{template['name']} · {choice}"
        result_summary = "朝廷完成对平定荆州功臣的封赏。"
    else:
        result_name = template["name"]
        result_summary = template["summary"]
    return DecisionResult(result_name, result_summary, text, effect_description)
