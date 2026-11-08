from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import Army, GameState
from ..content.v1_1.strategies import strategy_completed


@dataclass(frozen=True)
class BattleContext:
    """Information available while modifiers are checked immediately before battle."""

    role: str
    target_city_id: int
    opponent_army_id: int


ModifierCondition = Callable[[GameState, Army, BattleContext | None], bool]
ModifierEffects = Callable[[GameState, Army, BattleContext | None], dict[str, float]]


@dataclass(frozen=True)
class MilitaryModifierRule:
    id: int
    name: str
    description: str
    effects: dict[str, float]
    condition: ModifierCondition
    dynamic_effects: ModifierEffects | None = None

    def as_record(self, state: GameState, army: Army, context: BattleContext | None) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "effects": dict(self.dynamic_effects(state, army, context) if self.dynamic_effects else self.effects),
        }


def _event_happened(state: GameState, event_id: int) -> bool:
    return bool(state.events.get(event_id, {}).get("triggered"))


def _commander_is(state: GameState, army: Army, name: str) -> bool:
    return state.person_name(army.commander) == name


def _v12_region_name(state: GameState, city_id: int) -> str:
    city = state.cities.get(int(city_id), {})
    return str(state.regions.get(int(city.get("region_id", 0)), {}).get("name", ""))


def _v12_yuanjia_rebellion(state: GameState, army: Army, context: BattleContext | None) -> bool:
    return bool(
        str(state.flags.get("content_version", "")) == "1.2"
        and state.flags.get("v12_xie_hui_rebellion")
        and army.regime_id == state.player_regime_id
        and state.person_name(army.commander) in {"檀道济", "到彦之", "刘义恭"}
        and context is not None
        and context.role == "attacker"
        and _v12_region_name(state, context.target_city_id) in {"荆州", "郢州", "南雍州"}
    )


def _v12_henan_vanguard(state: GameState, army: Army, context: BattleContext | None) -> bool:
    return bool(
        army.regime_id == state.player_regime_id
        and int(state.flags.get("v12_henan_vanguard_until", -1)) >= state.turn_number
        and int(army.id) in {int(x) for x in state.flags.get("v12_northern_armies", [])}
        and context is not None and context.role == "attacker"
        and _v12_region_name(state, context.target_city_id) == "中原地区"
    )


def _v12_taiwu_counterattack(state: GameState, army: Army, context: BattleContext | None) -> bool:
    if not state.flags.get("v12_wei_counterattack") or army.regime_id != 2 or context is None or context.role != "attacker":
        return False
    opponent = state.armies.get(context.opponent_army_id)
    return bool(opponent and opponent.regime_id == state.player_regime_id and _v12_region_name(state, context.target_city_id) in {"中原地区", "淮北地区"})


def _v12_taiwu_effect(state: GameState, _army: Army, _context: BattleContext | None) -> dict[str, float]:
    alive = any(state.person_name(int(p["id"])) == "拓跋焘" and int(p.get("status", 0)) != 4 for p in state.persons.values())
    return {"attack": 0.25 if alive else 0.10}


def _v12_tuoba_tao(state: GameState, army: Army, context: BattleContext | None) -> bool:
    if state.person_name(army.commander) != "拓跋焘" or context is None or context.role != "attacker":
        return False
    opponent = state.armies.get(context.opponent_army_id)
    return bool(opponent and opponent.regime_id == state.player_regime_id)


def _huan_qian_offense(state: GameState, army: Army, _context: BattleContext | None) -> bool:
    return _event_happened(state, 2) and _commander_is(state, army, "桓谦")


def _huan_zhen_defense(state: GameState, army: Army, _context: BattleContext | None) -> bool:
    return _event_happened(state, 2) and _commander_is(state, army, "桓振")


def _restored_beifu_attack(state: GameState, army: Army, context: BattleContext | None) -> bool:
    if army.regime_id != state.player_regime_id or not strategy_completed(state, 2):
        return False
    if context is None:
        return state.at_war(state.player_regime_id, 3)
    opponent = state.armies.get(context.opponent_army_id)
    return context.role == "attacker" and bool(opponent and opponent.regime_id == 3)


def _qiao_shu_reinforcement(state: GameState, army: Army, context: BattleContext | None) -> bool:
    return (
        _event_happened(state, 4)
        and army.regime_id == 4
        and (context is None or context.role == "attacker")
    )


def _march_into_shu(state: GameState, army: Army, context: BattleContext | None) -> bool:
    if (
        not strategy_completed(state, 5)
        or army.regime_id != state.player_regime_id
        or state.person_name(army.commander) not in {"刘敬宣", "朱龄石"}
    ):
        return False
    if context is None:
        return False
    if context.role != "attacker":
        return False
    city = state.cities.get(context.target_city_id, {})
    region = state.regions.get(int(city.get("region_id", 0)), {})
    return region.get("name") in {"益州", "梁州"}


BEIFU_COMMANDERS = {"刘裕", "刘毅", "刘道规", "何无忌", "索邈", "刘敬宣", "朱龄石"}


def _beifu_army(state: GameState, army: Army, context: BattleContext | None) -> bool:
    return (
        strategy_completed(state, 7)
        and army.regime_id == state.player_regime_id
        and state.person_name(army.commander) in BEIFU_COMMANDERS
        and (context is None or context.role == "attacker")
    )


def _que_yue_formation(state: GameState, army: Army, context: BattleContext | None) -> bool:
    if (
        not strategy_completed(state, 7)
        or army.regime_id != state.player_regime_id
        or army.army_type != 0
        or not _commander_is(state, army, "刘裕")
        or (context is not None and context.role != "attacker")
    ):
        return False
    # 判定发生于战斗开始前，因此 army.location_id 就是发起进攻的节点。
    return any(
        other.id != army.id
        and other.regime_id == army.regime_id
        and other.army_type == 1
        and other.location_id == army.location_id
        for other in state.armies.values()
    )


NEW_BEIFU_COMMANDERS = {"檀道济", "王镇恶", "王懿", "沈田子", "朱超石", "傅弘之"}


def _new_beifu_generals(state: GameState, army: Army, _context: BattleContext | None) -> bool:
    return (
        strategy_completed(state, 9)
        and army.regime_id == state.player_regime_id
        and state.person_name(army.commander) in NEW_BEIFU_COMMANDERS
    )


def _wang_zhene_in_north_yong(state: GameState, army: Army, context: BattleContext | None) -> bool:
    if not _new_beifu_generals(state, army, context) or not _commander_is(state, army, "王镇恶") or context is None:
        return False
    city = state.cities.get(int(context.target_city_id), {})
    region = state.regions.get(int(city.get("region_id", 0)), {})
    return region.get("name") == "北雍州"


def _xie_hui_beifu(state: GameState, army: Army, _context: BattleContext | None) -> bool:
    return 15 in {int(item) for item in state.flags.get("completed_decisions", [])} and _commander_is(state, army, "谢晦")


def _xie_family_attack(state: GameState, _army: Army, _context: BattleContext | None) -> dict[str, float]:
    from .common import person_power
    from .laws import family_land_power

    family = next((item for item in state.families.values() if item.get("name") == "陈郡谢氏"), None)
    if not family:
        return {"attack": 0.0}
    members = [state.persons[int(item)] for item in family.get("members", []) if int(item) in state.persons]
    family_power = sum(person_power(state, person) for person in members) + family_land_power(state, int(family["id"]))
    return {"attack": family_power / 500.0 * 0.10}


def _helian_plot(state: GameState, army: Army, context: BattleContext | None) -> bool:
    if not _event_happened(state, 21) or army.regime_id != 12 or context is None:
        return False
    opponent = state.armies.get(context.opponent_army_id)
    if not opponent or opponent.regime_id != state.player_regime_id:
        return False
    allowed = {"夏地区", "北雍州"}
    target_city = state.cities.get(int(context.target_city_id), {})
    target_region = state.regions.get(int(target_city.get("region_id", 0)), {}).get("name")
    if target_region not in allowed:
        return False
    if context.role == "attacker":
        origin_city = state.cities.get(int(army.location_id), {})
        origin_region = state.regions.get(int(origin_city.get("region_id", 0)), {}).get("name")
        return origin_region in allowed
    return True


def _wei_permanent_bonus(_state: GameState, army: Army, _context: BattleContext | None) -> bool:
    return army.regime_id == 2


def _wei_cavalry_bonus(_state: GameState, army: Army, _context: BattleContext | None) -> bool:
    used = [unit for unit in army.units if int(unit.get("count", 0)) > 0]
    return army.regime_id == 2 and bool(used) and all(int(unit.get("type", 0)) == 2 for unit in used)


def _later_qin_408_bonus(state: GameState, army: Army, _context: BattleContext | None) -> bool:
    return army.regime_id == 9 and bool(state.flags.get("later_qin_408_reinforcements"))


def _later_qin_reinforcement_pay(_state: GameState, army: Army, _context: BattleContext | None) -> bool:
    return army.regime_id == 9 and any(int(item.get("id", 0)) == 14 for item in army.modifiers)


def _ai_difficulty_bonus(state: GameState, army: Army, _context: BattleContext | None) -> bool:
    from .ai_modifiers import ai_difficulty_combat_bonus

    return army.regime_id != state.player_regime_id and ai_difficulty_combat_bonus(state) > 0


def _ai_difficulty_effects(state: GameState, _army: Army, _context: BattleContext | None) -> dict[str, float]:
    from .ai_modifiers import ai_difficulty_combat_bonus

    bonus = ai_difficulty_combat_bonus(state)
    return {"attack": bonus, "defense": bonus}


# All conditional military modifiers live here. IDs are evaluated from 1 through
# the current maximum before every battle; gaps are allowed for retired content.
MILITARY_MODIFIER_RULES: dict[int, MilitaryModifierRule] = {
    1: MilitaryModifierRule(
        id=1,
        name="桓谦的攻势",
        description="事件“江陵决战”发生且军队领袖为桓谦时，攻击力+20%",
        effects={"attack": 0.20},
        condition=_huan_qian_offense,
    ),
    2: MilitaryModifierRule(
        id=2,
        name="桓振的死守",
        description="事件“江陵决战”发生且军队领袖为桓振时，防御作战力+30%",
        effects={"defense": 0.30},
        condition=_huan_zhen_defense,
    ),
    3: MilitaryModifierRule(
        id=3,
        name="复兴北府",
        description="完成“复兴北府”经略后，晋军进攻桓楚时攻击力+20%",
        effects={"attack": 0.20},
        condition=_restored_beifu_attack,
    ),
    4: MilitaryModifierRule(
        id=4,
        name="谯蜀增防",
        description="事件“谯蜀增防”发生后，谯蜀军队进攻作战力+30%",
        effects={"attack": 0.30},
        condition=_qiao_shu_reinforcement,
    ),
    5: MilitaryModifierRule(
        id=5,
        name="开拔入蜀",
        description="完成“收复巴蜀”后，刘敬宣或朱龄石率军攻入益州、梁州时攻击力+20%",
        effects={"attack": 0.20},
        condition=_march_into_shu,
    ),
    6: MilitaryModifierRule(
        id=6,
        name="北府军",
        description="完成“北伐”后，指定北府将领率军进攻时攻击力+20%",
        effects={"attack": 0.20},
        condition=_beifu_army,
    ),
    7: MilitaryModifierRule(
        id=7,
        name="却月阵",
        description="刘裕率陆军从有己方水军的节点发起进攻时，攻击力额外+50%",
        effects={"attack": 0.50},
        condition=_que_yue_formation,
    ),
    8: MilitaryModifierRule(
        id=8,
        name="北府新秀",
        description="完成“提拔新秀”后，檀道济、王镇恶、王懿、沈田子、朱超石、傅弘之率军时攻击力+30%",
        effects={"attack": 0.30},
        condition=_new_beifu_generals,
    ),
    9: MilitaryModifierRule(
        id=9,
        name="北雍奇兵",
        description="王镇恶率军在北雍州作战时，攻击力额外+20%；从北雍州攻往外地不生效",
        effects={"attack": 0.20},
        condition=_wang_zhene_in_north_yong,
    ),
    # 8、9号已由前一批剧情占用，后续剧情4中的同号修正顺延为10、11。
    10: MilitaryModifierRule(
        id=10,
        name="淝水遗风",
        description="决议“组织门阀北府兵”完成后，谢晦所率军队按陈郡谢氏总权力获得动态进攻修正",
        effects={},
        condition=_xie_hui_beifu,
        dynamic_effects=_xie_family_attack,
    ),
    11: MilitaryModifierRule(
        id=11,
        name="赫连勃勃的阴谋",
        description="事件发生后，胡夏军在夏地区或北雍州与主控政权作战时攻击力+50%",
        effects={"attack": 0.50},
        condition=_helian_plot,
    ),
    12: MilitaryModifierRule(
        id=12,
        name="魏国尚武",
        description="魏政权常驻军事修正：攻击力与防御作战力+20%",
        effects={"attack": 0.20, "defense": 0.20},
        condition=_wei_permanent_bonus,
    ),
    13: MilitaryModifierRule(
        id=13,
        name="后秦整军",
        description="408年后秦大举整军后：攻击力与防御作战力+15%",
        effects={"attack": 0.15, "defense": 0.15},
        condition=_later_qin_408_bonus,
    ),
    14: MilitaryModifierRule(
        id=14,
        name="后秦剧情军军饷优待",
        description="408年直接创建的十支后秦军队军饷降低80%",
        effects={"military_pay": -0.80},
        condition=_later_qin_reinforcement_pay,
    ),
    15: MilitaryModifierRule(
        id=15,
        name="AI难度修正",
        description="普通难度下AI常态攻防+20%，困难难度下AI常态攻防+40%",
        effects={},
        condition=_ai_difficulty_bonus,
        dynamic_effects=_ai_difficulty_effects,
    ),
    16: MilitaryModifierRule(
        id=16,
        name="魏国精骑",
        description="魏国纯骑兵军队额外获得攻击力与防御作战力+20%",
        effects={"attack": 0.20, "defense": 0.20},
        condition=_wei_cavalry_bonus,
    ),
    17: MilitaryModifierRule(
        id=17,
        name="元嘉平乱",
        description="谢晦叛乱期间，平叛主将在荆楚地区进攻+30%",
        effects={"attack": 0.30},
        condition=_v12_yuanjia_rebellion,
    ),
    18: MilitaryModifierRule(
        id=18,
        name="河南先声",
        description="第一次元嘉北伐主将在中原进攻+15%，持续6个月",
        effects={"attack": 0.15},
        condition=_v12_henan_vanguard,
    ),
    19: MilitaryModifierRule(
        id=19,
        name="太武反攻",
        description="魏军反击事件后，魏军在中原、淮北进攻获得加成",
        effects={},
        condition=_v12_taiwu_counterattack,
        dynamic_effects=_v12_taiwu_effect,
    ),
    20: MilitaryModifierRule(
        id=20,
        name="唱筹量沙",
        description="檀道济北援军补给消耗降低50%",
        effects={},
        condition=lambda state, army, _context: any(str(item.get("id", "")) in {"1020", "v12_changchouliangsha"} for item in army.modifiers),
    ),
    21: MilitaryModifierRule(
        id=21,
        name="佛狸佛狸~干杯",
        description="拓跋焘进攻宋军时迫使同地区两支宋军后撤并降低20士气",
        effects={},
        condition=_v12_tuoba_tao,
    ),
}


def register_military_modifier(rule: MilitaryModifierRule) -> None:
    """Register or replace a numbered rule for later scenario modules."""
    if rule.id <= 0:
        raise ValueError("军事修正编号必须大于0")
    MILITARY_MODIFIER_RULES[rule.id] = rule


def active_military_modifiers(
    state: GameState,
    army: Army,
    context: BattleContext | None = None,
) -> list[dict]:
    """Evaluate every numbered rule in ascending order for one army."""
    active: list[dict] = []
    last_id = max(MILITARY_MODIFIER_RULES, default=0)
    for modifier_id in range(1, last_id + 1):
        rule = MILITARY_MODIFIER_RULES.get(modifier_id)
        if rule is not None and rule.condition(state, army, context):
            active.append(rule.as_record(state, army, context))

    # Preserve old/custom save modifiers that do not have a dynamic rule ID.
    registered_ids = set(MILITARY_MODIFIER_RULES)
    def saved_modifier_id(modifier: dict) -> int:
        try:
            return int(modifier.get("id", 0))
        except (TypeError, ValueError):
            # 兼容早期1.2测试存档使用的字符串编号。
            return 1020 if modifier.get("id") == "v12_changchouliangsha" else 0

    active.extend(
        dict(modifier)
        for modifier in army.modifiers
        if saved_modifier_id(modifier) not in registered_ids
    )
    return active


def evaluate_battle_modifiers(
    state: GameState,
    attacker: Army,
    defender: Army,
    target_city_id: int,
) -> tuple[list[dict], list[dict]]:
    """Freeze both armies' active modifiers immediately before combat."""
    attacker_context = BattleContext("attacker", target_city_id, defender.id)
    defender_context = BattleContext("defender", target_city_id, attacker.id)
    return (
        active_military_modifiers(state, attacker, attacker_context),
        active_military_modifiers(state, defender, defender_context),
    )


def modifier_effect_total(modifiers: list[dict], effect: str) -> float:
    return sum(float(modifier.get("effects", {}).get(effect, 0.0)) for modifier in modifiers)
