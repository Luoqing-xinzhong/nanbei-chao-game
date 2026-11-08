from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import GameState
from .common import clamp


NationalCondition = Callable[[GameState], bool]


@dataclass(frozen=True)
class NationalModifierRule:
    id: int
    name: str
    description: str
    effects: dict[str, float]
    condition: NationalCondition

    def as_record(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "effects": dict(self.effects),
        }


def _person_id(state: GameState, name: str) -> int | None:
    return next(
        (int(person["id"]) for person in state.persons.values() if state.person_name(int(person["id"])) == name),
        None,
    )


def _liu_muzhi_chancellery(state: GameState) -> bool:
    person_id = _person_id(state, "刘穆之")
    return bool(
        person_id
        and int(state.persons[person_id].get("status", 0)) in {1, 2, 3}
        and int(state.player_regime.get("internal", {}).get("shangshu_ling") or 0) == person_id
        and 11 in {int(item) for item in state.flags.get("completed_decisions", [])}
    )


def _household_reform(state: GameState) -> bool:
    from ..content.v1_1.strategies import strategy_completed

    return strategy_completed(state, 18) and int(state.laws.get("economy", 1)) == 2


def _main_regime_cannot_recruit_cavalry(_state: GameState) -> bool:
    return True


# 与军事修正相同：结算前依次从1号检查到最后一号，编号允许留空。
NATIONAL_MODIFIER_RULES: dict[int, NationalModifierRule] = {
    1: NationalModifierRule(
        1,
        "刘穆之文官班子",
        "刘穆之担任尚书令时，文官党绝不会发动政变，每回合稳定度+1。",
        {"civil_party_coup_immunity": 1.0, "monthly_stability": 1.0},
        _liu_muzhi_chancellery,
    ),
    2: NationalModifierRule(
        2,
        "检籍土断改革",
        "完成“检籍土断”经略且继续执行检籍土断制度时，检籍与土断效果+30%。",
        {"land_policy_effect": 0.30},
        _household_reform,
    ),
    3: NationalModifierRule(
        3,
        "马政不振",
        "主控政权不能在创建军队时招募骑兵营；事件或决议直接授予的骑兵不受影响。",
        {"cavalry_recruitment_disabled": 1.0},
        _main_regime_cannot_recruit_cavalry,
    ),
}


def active_national_modifiers(state: GameState) -> list[dict]:
    active: list[dict] = []
    custom_ids = {int(item.get("id", 0)) for item in state.national_modifiers}
    for modifier_id in range(1, max(NATIONAL_MODIFIER_RULES, default=0) + 1):
        rule = NATIONAL_MODIFIER_RULES.get(modifier_id)
        if rule is not None and modifier_id not in custom_ids and rule.condition(state):
            active.append(rule.as_record())
    # 显式写入存档的修正视为场景自定义规则，可覆盖同编号的内置动态规则。
    active.extend(dict(item) for item in state.national_modifiers)
    return active


def national_modifier_total(state: GameState, effect: str) -> float:
    return sum(float(item.get("effects", {}).get(effect, 0.0)) for item in active_national_modifiers(state))


def apply_national_modifier_settlement(state: GameState) -> None:
    stability = national_modifier_total(state, "monthly_stability")
    if stability:
        state.player_regime["stability"] = int(
            clamp(int(state.player_regime.get("stability", 0)) + stability, 0, 100)
        )
        state.add_log(f"国家修正结算：稳定度 {stability:+g}。")
