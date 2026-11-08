from __future__ import annotations

import json

from ...constants import V13_CONFIG_DIR
from ...models import GameState
from ...rules.common import RuleError
from ..v1_2.economy import economy_data, region_economy
from .culture import SOUTHERN_REGIONS, culture_data, initialize_v13


WENJIAO_DEFAULT_PATH = V13_CONFIG_DIR / "wenjiao_south_default.json"
WENJIAO_DEFAULT_SOURCE = "frozen_default_snapshot"

SCENARIOS = {
    "wenjiao_south": {"name": "文教南国", "source": "yuanjia_governance", "source_name": "元嘉之治", "source_year": 433, "start": (434, 1)},
    "blood_tears": {"name": "血泪江左", "source": "wenjiao_south", "source_name": "文教南国", "source_year": 446, "start": (447, 1)},
}


def _seal_previous_scenario_content(state: GameState) -> None:
    """Remove executable Yuanjia content while retaining its settled world effects."""
    state.events.clear()
    state.strategies.clear()
    state.flags.pop("pending_story_events", None)
    state.flags.pop("v13_transition_ready", None)
    state.flags["previous_scenario_content_sealed"] = True


def _enter_wenjiao_south(state: GameState, *, inherited_from: str) -> GameState:
    state.year, state.month = SCENARIOS["wenjiao_south"]["start"]
    state.phase_index = 0
    _seal_previous_scenario_content(state)
    initialize_v13(state, inherited_from=inherited_from)
    state.flags["scenario_id"] = "wenjiao_south"
    state.flags["inherited_from"] = inherited_from
    return state


def _revive_chouchi_and_return_wei_armies(state: GameState) -> tuple[int, list[int]]:
    chouchi = next((regime for regime in state.regimes.values() if regime.get("name") == "仇池"), None)
    wei = next((regime for regime in state.regimes.values() if regime.get("name") == "魏"), None)
    if not chouchi or not wei:
        raise RuleError("文教南国默认数据缺少仇池或魏政权")
    capital_id = int(chouchi.get("capital") or 0)
    capital = state.cities.get(capital_id, {})
    region_id = int(capital.get("region_id") or 0)
    region = state.regions.get(region_id)
    if not region:
        raise RuleError("文教南国默认数据无法定位仇池首都所在地区")

    region_name = str(region["name"])
    for regime in state.regimes.values():
        regime["regions"] = [name for name in regime.get("regions", []) if name != region_name]
    chouchi.setdefault("regions", []).append(region_name)
    chouchi["relation_with_main"] = "中立"
    region["controller"] = int(chouchi["id"])

    chouchi_id = int(chouchi["id"])
    wei_id = int(wei["id"])
    state.wars = [pair for pair in state.wars if chouchi_id not in {int(x) for x in pair}]
    state.vassals.pop(chouchi_id, None)
    returned: list[int] = []
    wei_capital = int(wei.get("capital") or 0)
    for army in state.armies.values():
        city = state.cities.get(int(army.location_id), {})
        if int(army.regime_id) == wei_id and int(city.get("region_id") or 0) == region_id:
            army.location_id = wei_capital
            from ...rules.military import sync_commander_location

            sync_commander_location(state, army)
            returned.append(int(army.id))
    original_chouchi_army = state.armies.get(19)
    if original_chouchi_army and int(original_chouchi_army.regime_id) == wei_id:
        original_chouchi_army.location_id = wei_capital
        from ...rules.military import sync_commander_location

        sync_commander_location(state, original_chouchi_army)
        if 19 not in returned:
            returned.append(19)
    return region_id, returned


def _set_default_gentry_land_share(state: GameState, share: float = 0.60) -> None:
    """Rebalance every region without changing its total amount of land."""
    for region_id in state.regions:
        land = region_economy(state, int(region_id)).setdefault("land", {})
        gentry = max(0, int(land.get("gentry", 0)))
        smallholder = max(0, int(land.get("smallholder", 0)))
        self_farm = max(0, int(land.get("self_farm", 0)))
        total = gentry + smallholder + self_farm
        if total <= 0:
            continue

        target_gentry = min(total, max(0, int(total * share + 0.5)))
        remaining = total - target_gentry
        non_gentry_total = smallholder + self_farm
        if non_gentry_total > 0:
            target_self_farm = int(remaining * self_farm / non_gentry_total + 0.5)
        else:
            target_self_farm = 0
        target_self_farm = min(remaining, max(0, target_self_farm))
        land.update({
            "gentry": target_gentry,
            "smallholder": remaining - target_self_farm,
            "self_farm": target_self_farm,
        })


def _reset_default_regional_development(state: GameState) -> None:
    """Remove play-session development from the frozen default scenario."""
    culture = culture_data(state)
    culture["buildings"] = {}
    culture["next_building_id"] = 1
    approvals = culture.setdefault("approval", {})
    for region_id in state.regions:
        record = region_economy(state, int(region_id))
        record["local_policy"] = "stockpile"
        record["culture_supply"] = 1.0
        region = state.regions[int(region_id)]
        if int(region.get("controller", 0)) == state.player_regime_id:
            approvals[str(int(region_id))] = 75 if str(region.get("name")) in SOUTHERN_REGIONS else 50


def prepare_default_wenjiao_state(state: GameState) -> GameState:
    """Normalize the immutable default snapshot without consulting any save slot."""
    _enter_wenjiao_south(state, inherited_from=WENJIAO_DEFAULT_SOURCE)
    from ...rules.treasury import migrate_legacy_treasuries, set_treasury

    migrate_legacy_treasuries(state)
    state.event_log.clear()
    state.flags["battle_reports"] = []
    state.player_regime["stability"] = 50
    state.player_regime["war_support"] = 50
    state.player_regime["authority"] = 500
    state.authority = 500
    state.legislation.clear()
    state.laws["economy"] = 2
    _set_default_gentry_land_share(state)
    _reset_default_regional_development(state)
    state.flags["default_snapshot_frozen"] = True
    set_treasury(state, state.player_regime_id, 100.0)
    yi_long = next((person for person in state.persons.values() if f"{person.get('surname', '')}{person.get('given_name', '')}" == "刘义隆"), None)
    yuan_qigui = next((person for person in state.persons.values() if f"{person.get('surname', '')}{person.get('given_name', '')}" == "袁齐妫"), None)
    if yi_long and yuan_qigui:
        yi_long["spouse"] = int(yuan_qigui["id"])
        yuan_qigui["spouse"] = int(yi_long["id"])
        state.player_regime.setdefault("internal", {})["empress"] = int(yuan_qigui["id"])
    culture_data(state)["balance"] = 50.0
    economy = economy_data(state)
    economy.setdefault("manpower", {})[str(state.player_regime_id)] = 10_000
    economy["manpower_initialized"] = True
    for region_id in state.regions:
        region_economy(state, int(region_id)).setdefault("warehouse", {})["food"] = 0.0
    player_region_names = set(state.player_regime.get("regions", []))
    player_region_ids = [
        int(region_id)
        for region_id, region in state.regions.items()
        if str(region.get("name")) in player_region_names
    ]
    state.flags["v13_initial_food_capacity_floor_regions"] = player_region_ids
    for region_id, region in state.regions.items():
        if str(region.get("name")) in player_region_names:
            region_economy(state, int(region_id))["warehouse"]["food"] = 30.0
    _revive_chouchi_and_return_wei_armies(state)
    return state


def load_default_wenjiao_state() -> GameState:
    if not WENJIAO_DEFAULT_PATH.exists():
        raise RuleError(f"缺少文教南国默认配置：{WENJIAO_DEFAULT_PATH}")
    try:
        payload = json.loads(WENJIAO_DEFAULT_PATH.read_text(encoding="utf-8"))
        state = GameState.from_dict(payload)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuleError(f"文教南国默认配置读取失败：{exc}") from exc
    return prepare_default_wenjiao_state(state)


def inheritance_available(state: GameState, target: str) -> tuple[bool, str]:
    config = SCENARIOS.get(str(target))
    if not config:
        return False, "目标子剧本不存在"
    transition = state.flags.get("v13_transition_ready", {})
    if (
        str(transition.get("source", "")) != str(config["source"])
        or int(transition.get("year", 0)) != int(config["source_year"])
        or str(transition.get("target", "")) != str(target)
    ):
        return False, f"只能继承《{config['source_name']}》在公元{config['source_year']}年腊月结算生成的存档"
    return True, "可以继承"


def inherit_scenario(state: GameState, target: str) -> GameState:
    ok, reason = inheritance_available(state, target)
    if not ok:
        raise RuleError(reason)
    config = SCENARIOS[str(target)]
    if target == "wenjiao_south":
        _enter_wenjiao_south(state, inherited_from=str(config["source"]))
    else:
        state.year, state.month = config["start"]
        state.phase_index = 0
        _seal_previous_scenario_content(state)
        state.flags["scenario_id"] = str(target)
        state.flags["inherited_from"] = str(config["source"])
        state.flags["rules_version"] = "1.3"
    state.add_log(f"继承上一子剧本全部世界状态，进入《{config['name']}》。")
    return state
