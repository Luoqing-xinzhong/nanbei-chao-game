from __future__ import annotations

from ..models import GameState


AI_INCOME_BONUS = 1.0
AI_MILITIA_BONUS = 1.0
DIFFICULTY_COMBAT_BONUSES = {"easy": 0.0, "normal": 0.20, "hard": 0.40}
DIFFICULTY_RESOURCE_DISCOUNTS = {"easy": 0.0, "normal": 0.20, "hard": 0.40}
DIFFICULTY_RESOURCE_INCOME_BONUSES = {"easy": 1.0, "normal": 2.0, "hard": 3.0}
DIFFICULTY_SUPPLY_DISCOUNTS = {"easy": 0.50, "normal": 0.70, "hard": 0.85}
DIFFICULTY_WAR_SUPPORT_LOSS_REDUCTIONS = {"easy": 0.70, "normal": 0.80, "hard": 0.90}
DIFFICULTY_WAR_SUPPORT_RECOVERY = {"easy": 5, "normal": 7, "hard": 10}
DIFFICULTY_SIMULATED_COMMANDER_MARTIAL = {"easy": 50, "normal": 60, "hard": 70}
DIFFICULTY_NAMES = {"easy": "简单", "normal": "普通", "hard": "困难"}


def ai_income_multiplier(state: GameState, regime_id: int) -> float:
    """AI政权在基础收入上额外获得100%，即总收入为200%。"""
    regime = state.regimes.get(int(regime_id), {})
    return 1.0 if regime.get("is_main") else 1.0 + AI_INCOME_BONUS


def ai_militia_multiplier(state: GameState, regime_id: int) -> float:
    """所有AI政权壮丁增长增加100%。"""
    regime = state.regimes.get(int(regime_id), {})
    return 1.0 if regime.get("is_main") else 1.0 + AI_MILITIA_BONUS


def set_difficulty(state: GameState, difficulty: str) -> None:
    if difficulty not in DIFFICULTY_COMBAT_BONUSES:
        raise ValueError("未知难度")
    state.flags["difficulty"] = difficulty


def ai_difficulty_combat_bonus(state: GameState) -> float:
    return DIFFICULTY_COMBAT_BONUSES.get(str(state.flags.get("difficulty", "easy")), 0.0)


def ai_difficulty_resource_multiplier(state: GameState) -> float:
    """Return the share of real recruitment resources paid by AI regimes."""
    discount = DIFFICULTY_RESOURCE_DISCOUNTS.get(str(state.flags.get("difficulty", "easy")), 0.0)
    return max(0.0, 1.0 - discount)


def ai_difficulty_resource_income_bonus(state: GameState, regime_id: int) -> float:
    """Extra food/cloth income created for AI, separate from regional output."""
    if int(regime_id) == state.player_regime_id:
        return 0.0
    return DIFFICULTY_RESOURCE_INCOME_BONUSES.get(str(state.flags.get("difficulty", "easy")), 1.0)


def ai_difficulty_supply_multiplier(state: GameState, regime_id: int) -> float:
    """Return the share of normal army food consumption paid by an AI regime."""
    if int(regime_id) == state.player_regime_id:
        return 1.0
    discount = DIFFICULTY_SUPPLY_DISCOUNTS.get(str(state.flags.get("difficulty", "easy")), 0.50)
    return max(0.0, 1.0 - discount)


def ai_difficulty_war_support_loss_multiplier(state: GameState, regime_id: int) -> float:
    """AI only pays 30%/20%/10% of casualty-driven war-support loss."""
    if int(regime_id) == state.player_regime_id:
        return 1.0
    reduction = DIFFICULTY_WAR_SUPPORT_LOSS_REDUCTIONS.get(
        str(state.flags.get("difficulty", "easy")), 0.70
    )
    return max(0.0, 1.0 - reduction)


def recover_ai_war_support(state: GameState) -> dict[int, int]:
    """Apply the difficulty-scaled monthly AI recovery before surrender checks."""
    difficulty = str(state.flags.get("difficulty", "easy"))
    amount = int(DIFFICULTY_WAR_SUPPORT_RECOVERY.get(difficulty, 5))
    recovered: dict[int, int] = {}
    for regime_id, regime in state.regimes.items():
        if int(regime_id) == state.player_regime_id or not regime.get("regions"):
            continue
        before = max(0, min(100, int(regime.get("war_support", 0))))
        after = min(100, before + amount)
        regime["war_support"] = after
        if after > before:
            recovered[int(regime_id)] = after - before
            if any(int(regime_id) in {int(side) for side in pair} for pair in state.wars):
                state.add_log(
                    f"{regime.get('name', regime_id)}AI战争支持度恢复+{after - before}，当前{after}。"
                )
    return recovered


def ai_simulated_commander_martial(state: GameState, army) -> int:
    """Return a virtual martial value only for commanderless non-player armies."""
    if int(army.regime_id) == state.player_regime_id:
        return 0
    commander = state.persons.get(int(army.commander or 0))
    if commander and int(commander.get("status", 0)) != 4:
        return 0
    difficulty = str(state.flags.get("difficulty", "easy"))
    return int(DIFFICULTY_SIMULATED_COMMANDER_MARTIAL.get(difficulty, 50))


def ai_simulated_commander_combat_bonus(state: GameState, army) -> float:
    """Each two virtual martial points provide one percent combat strength."""
    return ai_simulated_commander_martial(state, army) / 200


def effective_commander_martial(state: GameState, army) -> int:
    """Use a real living commander's martial value, or the AI-only simulation."""
    commander = state.persons.get(int(army.commander or 0))
    if commander and int(commander.get("status", 0)) != 4:
        return max(0, int(commander.get("attributes", {}).get("military", 0)))
    return ai_simulated_commander_martial(state, army)


def commander_combat_bonus(state: GameState, army) -> float:
    return effective_commander_martial(state, army) / 200


def ai_national_modifier_records(state: GameState) -> list[dict]:
    """供修正状态窗口展示的常驻AI国家修正。"""
    records = [] if str(state.flags.get("content_version", "1.1")) == "1.2" else [
        {
            "id": "AI-1",
            "name": "AI财政扶持",
            "description": "所有非玩家政权收入增加100%（最终为基础收入的200%）。",
            "effects": {"income": AI_INCOME_BONUS},
        },
        {
            "id": "AI-2",
            "name": "AI行政补贴",
            "description": "所有非玩家政权每回合获得200权威，可在行政阶段连续发布政令。",
            "effects": {"monthly_authority": 200},
        },
        {
            "id": "AI-3",
            "name": "AI兵源扶持",
            "description": "所有非玩家政权壮丁增长增加100%（最终为基础增长的200%）。",
            "effects": {"militia_growth": AI_MILITIA_BONUS},
        },
    ]
    difficulty = str(state.flags.get("difficulty", "easy"))
    bonus = ai_difficulty_combat_bonus(state)
    if bonus:
        records.append(
            {
                "id": "AI-D",
                "name": f"{DIFFICULTY_NAMES.get(difficulty, difficulty)}难度",
                "description": f"所有AI军队常态攻击力与防御作战力+{int(bonus * 100)}%。",
                "effects": {"attack": bonus, "defense": bonus},
            }
        )
    records.append(
        {
            "id": "AI-C",
            "name": "AI模拟将领",
            "description": (
                "没有真实将领的AI军队按难度获得模拟将领："
                f"当前武力{DIFFICULTY_SIMULATED_COMMANDER_MARTIAL.get(difficulty, 50)}；"
                "玩家空将领军队不受影响。"
            ),
            "effects": {
                "simulated_commander_martial": DIFFICULTY_SIMULATED_COMMANDER_MARTIAL.get(difficulty, 50),
            },
        }
    )
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        resource_bonus = DIFFICULTY_RESOURCE_INCOME_BONUSES.get(difficulty, 1.0)
        supply_discount = DIFFICULTY_SUPPLY_DISCOUNTS.get(difficulty, 0.50)
        support_reduction = DIFFICULTY_WAR_SUPPORT_LOSS_REDUCTIONS.get(difficulty, 0.70)
        records.append(
            {
                "id": "AI-R",
                "name": "AI资源扶持",
                "description": (
                    f"AI年度粮食与布匹收入额外增加{int(resource_bonus * 100)}%，"
                    "额外资源直接生成，不从地区基础产量中扣除。"
                ),
                "effects": {"food_income": resource_bonus, "cloth_income": resource_bonus},
            }
        )
        records.append(
            {
                "id": "AI-W",
                "name": "AI战争承受力",
                "description": (
                    f"AI因战斗伤亡造成的战争支持度损失降低{int(support_reduction * 100)}%，"
                    f"每月恢复{DIFFICULTY_WAR_SUPPORT_RECOVERY.get(difficulty, 5)}点战争支持度。"
                ),
                "effects": {
                    "war_support_loss": -support_reduction,
                    "monthly_war_support": DIFFICULTY_WAR_SUPPORT_RECOVERY.get(difficulty, 5),
                },
            }
        )
        records.append(
            {
                "id": "AI-S",
                "name": "AI补给折扣",
                "description": f"AI军队粮食消耗降低{int(supply_discount * 100)}%。",
                "effects": {"supply_cost": -supply_discount},
            }
        )
    return records
