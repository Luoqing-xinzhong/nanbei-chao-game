from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .constants import JSON_DIR
from .models import Army, GameState


class DataError(RuntimeError):
    """配置无法启动游戏时抛出。"""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(f"无法读取配置 {path.name}: {exc}") from exc


def _index(items: list[dict[str, Any]], label: str, diagnostics: list[str] | None = None) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in items:
        if "id" not in item:
            raise DataError(f"{label}中存在缺少 id 的记录")
        item_id = int(item["id"])
        if item_id in result:
            if diagnostics is not None:
                diagnostics.append(f"{label} id={item_id} 重复，保留第一条记录")
            continue
        result[item_id] = copy.deepcopy(item)
    return result


def _initial_armies(regimes: dict[int, dict[str, Any]], cities: dict[int, dict[str, Any]]) -> dict[int, Army]:
    armies: dict[int, Army] = {}
    next_id = 1
    for regime in regimes.values():
        capital = int(regime.get("capital") or 0)
        if capital not in cities:
            # 部分测试政权首都引用了缺失的城市；优先选择其控制地区内首座现有城市。
            owned_region_ids = {
                city["region_id"] for city in cities.values()
                if city.get("region") in regime.get("regions", [])
            }
            capital = next((c["id"] for c in cities.values() if c.get("region_id") in owned_region_ids), 0)
        if not capital:
            continue
        count = min(3000 if regime.get("is_main") else 1000, int(regime.get("reserve_army", 0)))
        if count <= 0:
            continue
        regime["reserve_army"] -= count
        armies[next_id] = Army(
            id=next_id,
            regime_id=int(regime["id"]),
            army_type=0,
            units=[{"type": 1, "count": min(1000, count - i * 1000)} for i in range((count + 999) // 1000)],
            morale=80,
            experience=10,
            commander=int(regime.get("initial_army_commander") or 0) or None,
            location_id=capital,
        )
        next_id += 1
    return armies


def load_initial_state(json_dir: Path = JSON_DIR) -> GameState:
    diagnostics: list[str] = []
    cities_doc = _read_json(json_dir / "cities.json")
    roads_doc = _read_json(json_dir / "roads_all.json")
    cities = _index(cities_doc.get("cities", []), "城市", diagnostics)
    regions = _index(_read_json(json_dir / "regions_initial.json"), "地区", diagnostics)
    regimes = _index(_read_json(json_dir / "regimes_initial.json"), "政权", diagnostics)
    persons = _index(_read_json(json_dir / "persons_all_factions_initial.json"), "人物", diagnostics)
    families = _index(_read_json(json_dir / "families_all_factions_initial.json"), "家族", diagnostics)

    if not cities or not regions or not regimes or not persons:
        raise DataError("城市、地区、政权和人物配置不能为空")

    # 以城市的 region_id 为权威来源，补齐测试配置里大量为空的 regions[].cities。
    for region in regions.values():
        derived = [c["id"] for c in cities.values() if int(c.get("region_id", -1)) == region["id"]]
        configured = [int(x) for x in region.get("cities", []) if int(x) in cities]
        merged = list(dict.fromkeys(configured + derived))
        if merged != region.get("cities", []):
            diagnostics.append(f"已补全地区“{region['name']}”的城市列表（{len(merged)}座）")
        region["cities"] = merged
        capitals = [city_id for city_id in merged if cities[city_id].get("capital") is True]
        if len(capitals) != 1:
            diagnostics.append(f"地区“{region['name']}”应有且仅有一个首府，当前为 {len(capitals)} 个")

    valid_roads: list[dict[str, Any]] = []
    for road in roads_doc.get("roads", []):
        if int(road.get("from", 0)) not in cities or int(road.get("to", 0)) not in cities:
            diagnostics.append(f"跳过道路#{road.get('id')}：引用了缺失城市")
            continue
        valid_roads.append(copy.deepcopy(road))

    for regime in regimes.values():
        if int(regime.get("capital") or 0) not in cities:
            diagnostics.append(f"政权“{regime['name']}”的首都#{regime.get('capital')}不存在，地图显示将使用替代驻地")
        regime.setdefault("opinion_of_main", 0)
        if not regime.get("is_main"):
            regime.setdefault("authority", 200)

    # 未填写所在地的人物默认在本国首都；缺失首都则选本国控制的第一座城市。
    for person in persons.values():
        if int(person.get("location_id") or 0) in cities:
            continue
        regime = regimes.get(int(person.get("country_id", 0)))
        if not regime:
            continue
        candidate = int(regime.get("capital") or 0)
        if candidate not in cities:
            region_names = set(regime.get("regions", []))
            candidate = next((c["id"] for c in cities.values() if c.get("region") in region_names), 0)
        person["location_id"] = candidate

    armies = _initial_armies(regimes, cities)
    state = GameState(
        cities=cities,
        regions=regions,
        regimes=regimes,
        persons=persons,
        families=families,
        roads=valid_roads,
        armies=armies,
        confidants=[],
        diagnostics=diagnostics,
    )
    state.add_log("义熙元年正月，晋室还都建康，新局已开。")
    return state
