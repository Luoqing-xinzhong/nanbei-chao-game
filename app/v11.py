from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import JSON_DIR, V11_CONFIG_DIR
from .data_loader import load_initial_state
from .models import GameState


IDEOLOGY_NAMES = {
    1: "门阀保守派",
    2: "改良派",
    3: "寒门革新派",
    4: "皇权至上派",
    5: "军功集团",
    6: "和平文治派",
    7: "地方豪强派",
    8: "务实主义",
    9: "宗室派",
    10: "北府忠臣",
}

TENDENCY_NAMES = {
    1: "激进型",
    2: "忠犬型",
    3: "隐忍型",
    4: "摇摆型",
    5: "阴谋型",
    6: "骑士型",
    7: "投机型",
    8: "理想型",
    9: "务实型",
    10: "骑墙派",
}

LAW_CATEGORIES = {
    "economy": "经济基础",
    "values": "价值观",
    "power": "权力分配",
    "gentry": "门阀地位",
    "north": "对北态度",
    "tax": "税率",
}

LAW_LEVELS: dict[str, list[str]] = {
    "economy": ["庄园农奴制", "检籍土断", "自耕农", "屯田", "均田"],
    "values": ["废弛", "礼法", "仁义", "忠信", "南国魂"],
    "power": ["门阀政治", "寒人主政", "权臣政治", "无上皇权", "武人政治"],
    "gentry": ["王与马", "特权", "高贵", "平权", "堂前燕"],
    "north": ["和平至上", "以和为贵", "积极防御", "北伐至上", "一统天下"],
    "tax": ["免税", "轻税", "常税", "重税", "苛税"],
}

LAW_EFFECTS: dict[str, list[str]] = {
    "economy": [
        "世家土地占有上限80%，世家征税系数0.2，世家土地提供权力×1.2。",
        "世家占有上限60%，征税系数0.4，土地权力系数1.0；新增检籍、土断政令。",
        "世家占有上限30%，征税系数0.5，土地权力系数0.8。",
        "系数同自耕农；新增屯田政令，获得地区5%土地归中央并提高征兵率。",
        "世家土地分给小地主和自耕农，稳定度每回合额外+2。",
    ],
    "values": [
        "政变率30%、造反率30%，政治斗争无底线，污点>0即可处决，稳定上限50，谋划成功率+20%。",
        "政变率20%、造反率20%，处决需50污点；解锁教化政令，稳定上限70。",
        "政变率10%、造反率10%，处决需80污点，禁止刺杀，政令权威消耗-20%。",
        "政变率5%、造反率5%，不使用激进斗争，处决需100污点，每回合稳定+1，政令权威消耗-30%。",
        "政变率/造反率1%（战争时为0），处决需80污点；稳定下限80，战争时稳定锁定100，权威消耗-50%，战争状态-70%，敌军在本国作战士气-50%，战争税收+20%。",
    ],
    "power": [
        "高门人物权力+50%，立法时门阀权重×2，门阀每月吞并1%土地，政令驳斥率+20%。",
        "寒门人物权力+50%，小地主每月吞并1%土地，门阀领袖好感提升×0.5。",
        "需5级非皇帝人物才能立法，权臣权力+100%，立法4倍权重，政令消耗+20%，稳定每回合-1。",
        "除皇帝外人物权力-20%，皇帝+150%；可耗权威强行立法但稳定-30，政令消耗-20%，中央每月吞并1%土地。",
        "皇权-30%，军团武将可造反，军队+20%战力，稳定每回合-2，政变率+10%、造反率+15%。",
    ],
    "gentry": [
        "高门家族额外+50%权力，创建军队时高门自动任武将且不可卸任，高门举荐子弟。每回合消耗30%壮丁",
        "高门+30%权力，会举荐子弟，高门武将不可卸任。每回合消耗20%壮丁",
        "高门+10%权力，卸任消耗+100%。每回合消耗10%壮丁",
        "门阀无额外修正。",
        "高门解体，所有高门失去家族标签变为庶人。",
    ],
    "north": [
        "无法主动宣战，战争支持上限50，军队上限75营，战斗力-10%。",
        "无法使用借口宣战，宣战需好感低于-80，军队上限150营。",
        "解锁动员政令；可用借口宣战，侵略战-20%、防御战+20%，宣战需好感低于-20，军队上限300营，壮丁获取+20%。",
        "解锁动员政令；任何条件下可向魏宣战，战争支持每回合+1，战斗与壮丁获取+20%，军队+20%战力，无军队上限。",
        "解锁动员政令；与魏死战不和解，战争支持下限80且每回合+2，壮丁获取+30%，军队+30%战力，无军队上限，军饷+10%。",
    ],
    "tax": [
        "粮食与布匹税率0%；每月所有本国控制地区稳定度+10。",
        "粮食与布匹税率10%；每月所有本国控制地区稳定度+5。",
        "粮食与布匹税率15%；地区稳定度不变。",
        "粮食与布匹税率20%；每月所有本国控制地区稳定度-5。",
        "粮食与布匹税率25%；每月所有本国控制地区稳定度-10。",
    ],
}

# 1.1剧本的初始法律。
DEFAULT_LAWS = {
    "economy": 1,
    "values": 1,
    "power": 1,
    "gentry": 1,
    "north": 4,
    "tax": 3,
}

# 1.1 开局指定的四党领袖；外戚党暂时没有明确领袖。
PARTY_TEMPLATES = {
    1: {"id": 1, "name": "文官党", "leader": 8, "members": [8], "supported_families": []},
    2: {"id": 2, "name": "武将党", "leader": 33, "members": [33], "supported_families": []},
    3: {"id": 3, "name": "外戚党", "leader": None, "members": [], "supported_families": []},
    4: {"id": 4, "name": "宗室党", "leader": 85, "members": [85], "supported_families": []},
}

# 新人物数据只覆盖了这些政权，其余政权暂不强行指定皇帝。
REGIME_LEADERS = {
    1: 83,   # 晋：司马德宗
    2: 95,   # 魏：拓跋嗣
    5: 38,   # 卢循
    8: 45,   # 南燕：慕容超
    9: 74,   # 后秦：姚泓
    12: 96,  # 胡夏：赫连勃勃
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _index(items: list[dict[str, Any]], label: str) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for item in items:
        item_id = int(item["id"])
        if item_id in result:
            continue
        result[item_id] = item
    return result


def load_v11_persons(json_dir: Path = V11_CONFIG_DIR) -> dict[int, dict[str, Any]]:
    return _index(_read_json(json_dir / "persons_v1_1_historical.json"), "人物")


def load_v11_families(json_dir: Path = V11_CONFIG_DIR) -> dict[int, dict[str, Any]]:
    return _index(_read_json(json_dir / "families_v1_1_historical.json"), "家族")


def apply_v11_initial_state(state: GameState, json_dir: Path = V11_CONFIG_DIR) -> GameState:
    """在已有 v1 状态上叠加 1.1 的历史人物、家族、法律与政党数据。"""
    persons = load_v11_persons(json_dir)
    families = load_v11_families(json_dir)
    if not persons or not families:
        raise RuntimeError("1.1 历史人物或家族数据为空")

    state.persons = persons
    state.families = families
    for region in state.regions.values():
        region.setdefault("governor", None)

    # 人物所在地缺失时，沿用原有逻辑：优先本国首都，其次本国第一座城市。
    for person in state.persons.values():
        if int(person.get("location_id") or 0) in state.cities:
            continue
        regime = state.regimes.get(int(person.get("country_id", 0)))
        if not regime:
            continue
        candidate = int(regime.get("capital") or 0)
        if candidate not in state.cities:
            region_names = set(regime.get("regions", []))
            candidate = next((c["id"] for c in state.cities.values() if c.get("region") in region_names), 0)
        person["location_id"] = candidate

    # 替换 1.1 已明确的开局领袖；未提供人物数据的政权不强行指定皇帝。
    for regime_id, leader_id in REGIME_LEADERS.items():
        regime = state.regimes.get(regime_id)
        if not regime:
            continue
        if leader_id in state.persons:
            regime["internal"]["emperor"] = leader_id

    # 1.1 人物名单未覆盖的政权，不再保留旧人物 ID 的悬空引用。
    for regime in state.regimes.values():
        emperor = regime["internal"].get("emperor")
        if emperor not in state.persons:
            regime["internal"]["emperor"] = None

    state.confidants = []

    state.laws = dict(DEFAULT_LAWS)
    state.parties = {pid: dict(template) for pid, template in PARTY_TEMPLATES.items()}
    state.legislation = {}
    state.normalize_person_power_data(initial=True)
    from .content.v1_1.events import initialize_story_state

    initialize_story_state(state)
    state.diagnostics.append(
        f"已加载 1.1 历史数据：人物 {len(state.persons)} 人，家族 {len(state.families)} 个，"
        f"政党 {len(state.parties)} 个，法律方向 {len(state.laws)} 项。"
    )
    return state


def load_v11_state(json_dir: Path = JSON_DIR, version_dir: Path | None = None) -> GameState:
    """加载 1.1 版本初始状态。"""
    state = load_initial_state(json_dir)
    if version_dir is None:
        # 兼容过去把通用模板与1.1覆盖配置放在同一目录的外部调用。
        legacy_persons = json_dir / "persons_v1_1_historical.json"
        version_dir = json_dir if legacy_persons.exists() else V11_CONFIG_DIR
    return apply_v11_initial_state(state, version_dir)


def law_name(state: GameState, category: str) -> str:
    level = state.laws.get(category, 1)
    return LAW_LEVELS[category][level - 1]


def law_effect(category: str, level: int) -> str:
    return LAW_EFFECTS[category][level - 1]
