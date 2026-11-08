from __future__ import annotations

import random
from typing import Any

from ...models import GameState
from ...rules.common import RuleError, spend_authority


CLIMATE_TYPES: dict[str, dict[str, str]] = {
    "bumper": {"name": "丰收年", "description": "全国灾害率降低，风调雨顺的概率提高。"},
    "normal": {"name": "正常年", "description": "无额外气候修正。"},
    "el_nino": {"name": "南涝北旱年（厄尔尼诺）", "description": "南方洪涝、北方干旱概率提高。"},
    "la_nina": {"name": "南旱北涝年（拉尼娜）", "description": "南方干旱、北方洪涝概率提高。"},
    "disaster": {"name": "大灾年", "description": "玩家控制地区的全部灾害概率提高。"},
    "warm_winter": {"name": "暖冬年", "description": "冬季只剩腊月，并提高下一年全国干旱概率。"},
    "cold_winter": {"name": "寒冬年", "description": "冬季延长为十月至次年二月，并提高下一年全国洪涝概率。"},
}

CLIMATE_WEIGHTS: dict[str, dict[str, int]] = {
    "easy": {
        "bumper": 32, "normal": 36, "el_nino": 7, "la_nina": 7,
        "disaster": 4, "warm_winter": 8, "cold_winter": 6,
    },
    "normal": {
        "bumper": 14, "normal": 30, "el_nino": 12, "la_nina": 12,
        "disaster": 13, "warm_winter": 10, "cold_winter": 9,
    },
    "hard": {
        "bumper": 5, "normal": 18, "el_nino": 16, "la_nina": 16,
        "disaster": 26, "warm_winter": 9, "cold_winter": 10,
    },
}

NORTH_REGION_NAMES = {
    "中原地区", "淮北地区", "徐州", "青州", "冀州", "幽州", "并州",
    "北雍州", "夏地区", "陇西地区", "东北地区", "仇池",
}
EARTHQUAKE_REGIONS = {"梁州", "益州", "西南地区"}
TYPHOON_REGIONS = {"扬州", "广州", "交州", "徐州"}
SEVERE_WINTER_WATER_LINKS = {
    frozenset(pair)
    for pair in (
        ("山阳", "淮陵"),
        ("淮陵", "涡口"),
        ("涡口", "寿春"),
        ("寿春", "颍口"),
        ("颍口", "义阳"),
    )
}


def _climate_data(state: GameState) -> dict[str, Any]:
    return state.flags.setdefault("v12_climate", {"years": {}, "report_offers": [], "reports_viewed": []})


def _weighted_choice(weights: dict[str, int], rng: random.Random) -> str:
    total = sum(max(0, int(value)) for value in weights.values())
    roll = rng.random() * total
    running = 0
    for key, weight in weights.items():
        running += max(0, int(weight))
        if roll < running:
            return key
    return next(reversed(weights))


def ensure_annual_climate(
    state: GameState,
    year: int | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    year = int(state.year if year is None else year)
    data = _climate_data(state)
    years = data.setdefault("years", {})
    key = str(year)
    if key in years:
        return years[key]
    difficulty = str(state.flags.get("difficulty", "easy"))
    weights = CLIMATE_WEIGHTS.get(difficulty, CLIMATE_WEIGHTS["easy"])
    chooser = rng or random.Random(year * 79_219 + {"easy": 1, "normal": 2, "hard": 3}.get(difficulty, 1))
    climate_key = _weighted_choice(weights, chooser)
    definition = CLIMATE_TYPES[climate_key]
    record = {
        "year": year,
        "kind": climate_key,
        "name": definition["name"],
        "description": definition["description"],
    }
    years[key] = record
    return record


def set_annual_climate(state: GameState, year: int, kind: str) -> dict[str, Any]:
    """Set a climate explicitly for scenarios, migration and deterministic tests."""
    if kind not in CLIMATE_TYPES:
        raise ValueError("未知年度气候")
    definition = CLIMATE_TYPES[kind]
    record = {
        "year": int(year),
        "kind": kind,
        "name": definition["name"],
        "description": definition["description"],
    }
    _climate_data(state).setdefault("years", {})[str(int(year))] = record
    return record


def queue_march_climate_report(state: GameState) -> bool:
    if str(state.flags.get("content_version", "")) != "1.2" or int(state.month) != 3:
        return False
    data = _climate_data(state)
    year = int(state.year)
    offers = data.setdefault("report_offers", [])
    if year in offers or year in data.setdefault("reports_viewed", []):
        return False
    ensure_annual_climate(state, year)
    offers.append(year)
    state.flags["pending_v12_climate_report"] = year
    return True


def reveal_climate_report(state: GameState, year: int | None = None) -> str:
    year = int(state.year if year is None else year)
    if state.authority < 100:
        raise RuleError(f"权威不足：查看太史局报告需要100，当前{state.authority}")
    spend_authority(state, 100, apply_law_modifier=False)
    record = ensure_annual_climate(state, year)
    viewed = _climate_data(state).setdefault("reports_viewed", [])
    if year not in viewed:
        viewed.append(year)
    message = f"太史局奏报：{year}年为{record['name']}。{record['description']}"
    state.add_log(message)
    return message


def is_northern_region(region_name: str) -> bool:
    return str(region_name) in NORTH_REGION_NAMES


def region_weather_probabilities(state: GameState, region_id: int) -> dict[str, float]:
    region = state.regions[int(region_id)]
    name = str(region.get("name", ""))
    northern = is_northern_region(name)
    probabilities = {
        "地震": 0.30 if name in EARTHQUAKE_REGIONS else 0.0,
        "台风": 0.20 if name in TYPHOON_REGIONS else 0.0,
        "洪涝": 0.08 if northern else 0.18,
        "干旱": 0.18 if northern else 0.08,
        "风调雨顺": 0.18,
    }
    climate = ensure_annual_climate(state)
    kind = str(climate["kind"])
    if kind == "bumper":
        for hazard in ("地震", "台风", "洪涝", "干旱"):
            probabilities[hazard] *= 0.5
        probabilities["风调雨顺"] += 0.25
    elif kind == "el_nino":
        probabilities["干旱" if northern else "洪涝"] += 0.18
    elif kind == "la_nina":
        probabilities["洪涝" if northern else "干旱"] += 0.18
    elif kind == "disaster" and int(region.get("controller", 0)) == state.player_regime_id:
        for hazard in ("地震", "台风", "洪涝", "干旱"):
            probabilities[hazard] *= 1.75

    previous = ensure_annual_climate(state, int(state.year) - 1)
    if previous["kind"] == "warm_winter":
        probabilities["干旱"] += 0.12
    elif previous["kind"] == "cold_winter":
        probabilities["洪涝"] += 0.12

    non_normal = sum(probabilities.values())
    if non_normal > 0.98:
        scale = 0.98 / non_normal
        probabilities = {key: value * scale for key, value in probabilities.items()}
        non_normal = 0.98
    probabilities["正常"] = max(0.02, 1.0 - non_normal)
    return {key: round(value, 5) for key, value in probabilities.items()}


WEATHER_YIELD_FACTORS = {
    "地震": 0.90,
    "台风": 0.90,
    "洪涝": 0.50,
    "干旱": 0.70,
    "正常": 1.00,
    "风调雨顺": 1.30,
}


def roll_region_weather(
    state: GameState,
    region_id: int,
    rng: random.Random | None = None,
) -> tuple[str, float]:
    chooser = rng or random.Random(int(state.year) * 104_729 + int(region_id) * 97)
    probabilities = region_weather_probabilities(state, region_id)
    roll = chooser.random()
    running = 0.0
    for weather, chance in probabilities.items():
        running += chance
        if roll < running:
            return weather, WEATHER_YIELD_FACTORS[weather]
    return "正常", WEATHER_YIELD_FACTORS["正常"]


def _winter_reference_year(state: GameState) -> int:
    return int(state.year) - 1 if int(state.month) in {1, 2} else int(state.year)


def is_winter_month(state: GameState) -> bool:
    month = int(state.month)
    if month not in {1, 2, 10, 11, 12}:
        return False
    kind = str(ensure_annual_climate(state, _winter_reference_year(state))["kind"])
    months = {12} if kind == "warm_winter" else {10, 11, 12, 1, 2} if kind == "cold_winter" else {11, 12, 1}
    return month in months


def winter_months(state: GameState, year: int | None = None) -> set[int]:
    reference_year = int(state.year if year is None else year)
    kind = str(ensure_annual_climate(state, reference_year)["kind"])
    return {12} if kind == "warm_winter" else {10, 11, 12, 1, 2} if kind == "cold_winter" else {11, 12, 1}


def months_until_winter(state: GameState) -> int:
    """Months until the next winter blockage; zero means winter is active now."""
    if is_winter_month(state):
        return 0
    month = int(state.month)
    current = sorted(m for m in winter_months(state, state.year) if m >= month and m >= 10)
    if current:
        return current[0] - month
    next_months = sorted(winter_months(state, state.year + 1))
    return (12 - month) + (next_months[0] if next_months else 11)


def is_frozen_water_road(state: GameState, road: dict[str, Any]) -> bool:
    if (
        str(state.flags.get("content_version", "")) != "1.2"
        or int(road.get("type", 1)) != 3
        or not is_winter_month(state)
    ):
        return False
    left = state.cities.get(int(road.get("from", 0)), {})
    right = state.cities.get(int(road.get("to", 0)), {})
    endpoint_regions = {
        str(state.regions.get(int(city.get("region_id", 0)), {}).get("name", ""))
        for city in (left, right)
    }
    if any(is_northern_region(name) for name in endpoint_regions):
        return True
    kind = str(ensure_annual_climate(state, _winter_reference_year(state))["kind"])
    return kind == "cold_winter" and frozenset((str(left.get("name", "")), str(right.get("name", "")))) in SEVERE_WINTER_WATER_LINKS
