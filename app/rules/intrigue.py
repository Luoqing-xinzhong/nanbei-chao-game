from __future__ import annotations

import random

from ..models import GameState
from .common import RuleError, clamp
from .laws import adjust_person_opinion, execute_stain_threshold, intrigue_action_allowed, intrigue_success_modifier
from .treasury import spend_treasury, treasury_balance

ACTIONS = {
    "拉拢": (0.60, 0),
    "讨好": (0.80, 50),
    "宴请": (0.70, 200),
    "联姻": (0.50, 0),
    "打压": (0.50, 0),
    "威胁": (0.40, 0),
    "调查": (0.70, 0),
    "诬陷": (0.40, 0),
    "刺杀": (0.25, 0),
    "处决": (1.00, 0),
}


def available_targets(state: GameState) -> list[dict]:
    """只返回本国存活人物，并排除主控人物和全部亲信。"""
    confidants = {int(person_id) for person_id in state.confidants}
    return [
        person for person in state.persons.values()
        if int(person.get("status", 0)) in {1, 2, 3}
        and int(person.get("country_id", 0)) == state.player_regime_id
        and not person.get("is_player")
        and int(person["id"]) not in confidants
    ]


def invite_confidant(state: GameState, person_id: int, rng: random.Random | None = None) -> str:
    if person_id in state.confidants:
        raise RuleError("此人已经是亲信")
    if len(state.confidants) >= 5:
        raise RuleError("亲信最多五人")
    person = state.persons[person_id]
    opinion = int(person.get("opinion_of_player", 0))
    chance = clamp(opinion / 100, 0.05, 0.95)
    if (rng or random).random() <= chance:
        state.confidants.append(person_id)
        message = f"{state.person_name(person_id)}接受邀请，成为亲信。"
    else:
        message = f"{state.person_name(person_id)}婉拒了邀请。"
    state.add_log(message)
    return message


def remove_confidant(state: GameState, person_id: int) -> str:
    if person_id not in state.confidants:
        raise RuleError("此人不是亲信")
    state.confidants.remove(person_id)
    state.persons[person_id]["opinion_of_player"] = -100
    message = f"{state.person_name(person_id)}被从亲信中除名。"
    state.add_log(message)
    return message


def perform(state: GameState, confidant_id: int, target_id: int, action: str, rng: random.Random | None = None) -> str:
    rng = rng or random
    if confidant_id not in state.confidants:
        raise RuleError("执行者不是亲信")
    if target_id == confidant_id:
        raise RuleError("不能以执行者本人为目标")
    if target_id not in {int(person["id"]) for person in available_targets(state)}:
        raise RuleError("外国人、主控人物和亲信不能成为谋划对象")
    if action not in ACTIONS:
        raise RuleError("未知谋划行动")
    if not intrigue_action_allowed(state, action):
        raise RuleError("当前价值观法律禁止这种激进谋划")
    key = f"turn:{state.turn_number}:intrigue:{confidant_id}"
    if state.flags.get(key):
        raise RuleError("这名亲信本回合已经行动")
    target = state.persons[target_id]
    if target.get("family_id") and target.get("family_id") == state.persons[confidant_id].get("family_id"):
        raise RuleError("不能以亲信的同族成员为目标")
    threshold = execute_stain_threshold(state)
    if action == "处决" and int(target.get("attributes", {}).get("stain", 0)) < threshold:
        raise RuleError(f"目标污点不足 {threshold}，不能公开处决")
    if action == "诬陷" and not state.flags.get(f"investigated:{target_id}"):
        raise RuleError("必须先调查目标并掌握信息")
    base, cost = ACTIONS[action]
    if treasury_balance(state) < cost:
        raise RuleError(f"国库不足 {cost}")
    spend_treasury(state, state.player_regime_id, cost)
    intelligence = state.persons[confidant_id].get("attributes", {}).get("intelligence", 0)
    chance = clamp(base + 0.005 * intelligence + intrigue_success_modifier(state), 0.05, 0.95)
    success = rng.random() <= chance
    attrs = target.setdefault("attributes", {})
    if success:
        if action == "拉拢":
            adjust_person_opinion(state, target, 15)
            attrs["loyalty"] = int(clamp(attrs.get("loyalty", 0) + 5, 0, 100))
        elif action == "讨好":
            adjust_person_opinion(state, target, 10)
        elif action == "宴请":
            adjust_person_opinion(state, target, 20)
            attrs["alertness"] = int(clamp(attrs.get("alertness", 0) - 10, 0, 100))
        elif action == "打压":
            value = max(0, int(attrs.get("base_power", 0)) - 20)
            if int(target.get("level", 0)) < 6:
                value = min(100, value)
            attrs["base_power"] = value
        elif action == "威胁":
            attrs["loyalty"] = int(clamp(attrs.get("loyalty", 0) + 20, 0, 100))
        elif action == "调查":
            state.flags[f"investigated:{target_id}"] = True
            from .political_events import investigate_coup_member

            investigate_coup_member(state, target_id, rng)
        elif action == "诬陷":
            attrs["stain"] = int(clamp(attrs.get("stain", 0) + rng.randint(20, 50), 0, 100))
        elif action in {"刺杀", "处决"}:
            target["status"] = 4
            target["death_year"] = state.year
            from .political_events import destroy_coups_led_by

            destroy_coups_led_by(state, target_id)
        message = f"{state.person_name(confidant_id)}对{state.person_name(target_id)}执行“{action}”成功。"
    else:
        attrs["alertness"] = int(clamp(attrs.get("alertness", 0) + 10, 0, 100))
        adjust_person_opinion(state, target, -5)
        message = f"对{state.person_name(target_id)}的“{action}”失败，目标提高了警惕。"
    state.flags[key] = True
    state.add_log(message)
    return message
