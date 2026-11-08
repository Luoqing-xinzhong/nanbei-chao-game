from __future__ import annotations

from collections import Counter

from ..models import GameState
from .common import clamp

# 家族土地的默认税收率由 0.2 提高到 0.5，避免门阀土地占比较高时财政近乎停摆。
LAND_RATES = {0: 0.8, 1: 0.5, 2: 1.0}
FAMILY_LAND_RATE = 0.5
MILITARY_PAY_PER_BATTALION = 10  # 原每营50，现调整为20%。
OFFICIAL_SALARY_PER_OFFICE = 2  # 原每个官职20，缩减为当前的十分之一。
TREASURY_SOFT_CAP = 15_000
TREASURY_HARD_CAP = 20_000
MILITIA_SOFT_CAP = 150_000
MILITIA_HARD_CAP = 200_000


def treasury_income_multiplier(treasury: int) -> float:
    """Return the monthly-income multiplier at the current treasury stock."""
    if int(treasury) > TREASURY_HARD_CAP:
        return 0.0
    if int(treasury) > TREASURY_SOFT_CAP:
        return 0.2
    return 1.0


def militia_growth_multiplier(militia: int) -> float:
    """Return the natural militia-growth multiplier at the current stock."""
    if int(militia) > MILITIA_HARD_CAP:
        return 0.0
    if int(militia) > MILITIA_SOFT_CAP:
        return 0.2
    return 1.0


def calculate_region_income(region: dict, state: GameState | None = None, regime_id: int | None = None) -> int:
    ownership = region.get("land_ownership", [])
    if not ownership:
        return 0
    counts = Counter(int(owner) for owner in ownership)
    weighted = 0.0
    family_rate = FAMILY_LAND_RATE
    if state is not None and regime_id is not None:
        from .laws import family_tax_rate

        family_rate = family_tax_rate(state, regime_id)
    for owner, count in counts.items():
        rate = LAND_RATES.get(owner, family_rate if owner >= 3 else 0.0)
        weighted += count * rate
    development = clamp(float(region.get("development", 0)), 0, 100) / 100
    prosperity = clamp(float(region.get("prosperity", 0)), 0, 10) / 10
    income = int(weighted * development * prosperity)
    # A region without an appointed governor can only remit half of its income.
    if not region.get("governor"):
        income //= 2
    return income


def regime_income(state: GameState, regime_id: int) -> int:
    regime = state.regimes[regime_id]
    names = set(regime.get("regions", []))
    total = sum(calculate_region_income(region, state, regime_id) for region in state.regions.values() if region.get("name") in names)
    stability = int(regime.get("stability", 0))
    if stability < 10:
        return 0
    if stability < 50:
        total //= 2
    from .laws import income_multiplier

    from .ai_modifiers import ai_income_multiplier

    return int(
        total
        * income_multiplier(state, regime_id)
        * ai_income_multiplier(state, regime_id)
        * treasury_income_multiplier(int(regime.get("treasury", 0)))
    )


def calculate_region_militia_growth(region: dict) -> float:
    """壮丁增长取决于人口和繁荣度；没有刺史时只能获得一半。"""
    households = max(0, int(region.get("households", 0)))
    prosperity = clamp(float(region.get("prosperity", 0)), 0, 10)
    growth = households * prosperity / 90
    if not region.get("governor"):
        growth *= 0.5
    return growth


def regime_militia_growth(state: GameState, regime_id: int) -> int:
    regime = state.regimes[regime_id]
    names = set(regime.get("regions", []))
    base = sum(
        calculate_region_militia_growth(region)
        for region in state.regions.values()
        if region.get("name") in names
    )
    from .laws import militia_multiplier
    from .ai_modifiers import ai_militia_multiplier

    return max(0, int(round(
        base
        * militia_multiplier(state, regime_id)
        * ai_militia_multiplier(state, regime_id)
        * militia_growth_multiplier(int(regime.get("militia", 0)))
    )))


def projected_expenses(state: GameState, regime_id: int) -> tuple[int, int]:
    official_count = 0
    for value in state.regimes[regime_id].get("internal", {}).values():
        if isinstance(value, list):
            official_count += len(value)
        elif value:
            official_count += 1
    official_salary = official_count * OFFICIAL_SALARY_PER_OFFICE
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        return official_salary, 0
    from .military_modifiers import active_military_modifiers, modifier_effect_total

    military_pay_base = 0.0
    for army in state.armies.values():
        if army.regime_id != regime_id:
            continue
        pay_modifier = modifier_effect_total(active_military_modifiers(state, army), "military_pay")
        military_pay_base += army.active_battalions * MILITARY_PAY_PER_BATTALION * max(0.0, 1.0 + pay_modifier)
    from .laws import military_pay_multiplier

    military_pay = int(round(military_pay_base * military_pay_multiplier(state, regime_id)))
    return official_salary, military_pay


def uses_semiannual_official_salary(state: GameState) -> bool:
    """Yuanjia (1.2), Wenjiao (1.3), and later content pay twice yearly."""
    raw = str(state.flags.get("rules_version") or state.flags.get("content_version") or "1.0")
    try:
        parts = tuple(int(item) for item in raw.split(".")[:2])
    except ValueError:
        return False
    return parts >= (1, 2)


def expenses_due_this_month(state: GameState, regime_id: int) -> tuple[int, int]:
    """Return cash actually due at this month-end without changing unit costs."""
    official_salary, military_pay = projected_expenses(state, regime_id)
    if uses_semiannual_official_salary(state) and int(state.month) not in {1, 7}:
        official_salary = 0
    return official_salary, military_pay


def average_monthly_expenses(state: GameState, regime_id: int) -> tuple[float, float]:
    """Budgeting view: two unchanged salary payments spread over twelve months."""
    official_salary, military_pay = projected_expenses(state, regime_id)
    if uses_semiannual_official_salary(state):
        return official_salary / 6.0, float(military_pay)
    return float(official_salary), float(military_pay)
