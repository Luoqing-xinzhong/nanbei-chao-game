from __future__ import annotations

import json
import re
import copy
import shutil
from datetime import datetime
from pathlib import Path

from .constants import SAVE_DIR
from .models import GameState

SAVE_SLOT_COUNT = 10
SLOT_FILE_RE = re.compile(r"^slot_(\d{2})\.json$")


def save_slot_path(slot: int, save_dir: Path = SAVE_DIR) -> Path:
    if not 1 <= int(slot) <= SAVE_SLOT_COUNT:
        raise ValueError(f"存档位必须在1至{SAVE_SLOT_COUNT}之间")
    return save_dir / f"slot_{int(slot):02d}.json"


def _migrate_legacy_saves(save_dir: Path) -> None:
    """将旧式时间戳存档复制进空槽位；保留原文件，避免迁移造成数据丢失。"""
    if not save_dir.exists():
        return
    # 只在尚未建立任何固定槽位时执行一次，避免保留的旧文件被反复复制到空槽。
    if any(save_slot_path(index, save_dir).exists() for index in range(1, SAVE_SLOT_COUNT + 1)):
        return
    legacy = sorted(
        (path for path in save_dir.glob("*.json") if not SLOT_FILE_RE.match(path.name)),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for slot, source in zip(
        (index for index in range(1, SAVE_SLOT_COUNT + 1) if not save_slot_path(index, save_dir).exists()),
        legacy,
    ):
        shutil.copy2(source, save_slot_path(slot, save_dir))


def list_save_slots(save_dir: Path = SAVE_DIR) -> list[tuple[int, Path]]:
    save_dir.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_saves(save_dir)
    return [(slot, save_slot_path(slot, save_dir)) for slot in range(1, SAVE_SLOT_COUNT + 1)]


def save_slot_label(slot: int, path: Path) -> str:
    if not path.exists():
        return f"存档位 {slot:02d}　【空】"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        name = str(data.get("save_name") or path.stem)
        saved_at = str(data.get("saved_at", "")).replace("T", " ")
        year = int(data.get("year", 0))
        month = int(data.get("month", 0))
        date_text = f"公元{year}年{month}月" if year and month else "日期未知"
        return f"存档位 {slot:02d}　{name}　{date_text}　{saved_at}"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return f"存档位 {slot:02d}　【无法读取】　{path.name}"


def list_saves(save_dir: Path = SAVE_DIR) -> list[Path]:
    return [path for _slot, path in list_save_slots(save_dir) if path.exists()]


def save_game(state: GameState, name: str = "自动存档", save_dir: Path = SAVE_DIR, slot: int | None = None) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_") or "存档"
    if slot is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = save_dir / f"{safe_name}_{stamp}.json"
    else:
        path = save_slot_path(slot, save_dir)
    payload = state.to_dict()
    payload["save_name"] = safe_name
    payload["saved_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_game(path: Path) -> GameState:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    state = GameState.from_dict(data)
    # 兼容结束标记修复前已经误推进到下一年正月的子剧本存档。这些状态
    # 已完成上一年腊月结算，只补继承标记，不重跑任何月度结算。
    if (
        str(state.flags.get("scenario_id", "")) == "yuanjia_governance"
        and (state.year, state.month) == (434, 1)
        and str(state.flags.get("rules_version", "")) != "1.3"
        and not state.flags.get("v13_transition_ready")
    ):
        state.flags["v13_transition_ready"] = {
            "source": "yuanjia_governance",
            "target": "wenjiao_south",
            "year": 433,
        }
    if (
        str(state.flags.get("scenario_id", "")) == "wenjiao_south"
        and (state.year, state.month) == (447, 1)
        and str(state.flags.get("rules_version", "")) == "1.3"
        and not state.flags.get("v13_transition_ready")
    ):
        state.flags["v13_transition_ready"] = {
            "source": "wenjiao_south",
            "target": "blood_tears",
            "year": 446,
        }
    if (
        str(state.flags.get("content_version", "1.1")) == "1.2"
        and state.year >= 434
        and str(state.flags.get("rules_version", "")) != "1.3"
        and not state.flags.get("v13_transition_ready")
    ):
        raise ValueError("1.3改版后，旧版1.2在公元434年及以后的存档无法打开")
    for regime in state.regimes.values():
        if regime.get("name") == "后凉":
            regime["name"] = "北凉"
    # 为旧存档补齐当前版本的全部法律类别。
    if str(state.flags.get("content_version", "1.1")) == "1.2":
        from .v11 import DEFAULT_LAWS
        from .content.v1_2.economy import enforce_warehouse_capacity, lock_all_ai_region_control, migrate_market_currency
        from .rules.treasury import migrate_legacy_treasuries

        for category, default_level in DEFAULT_LAWS.items():
            state.laws.setdefault(category, default_level)
        migrate_legacy_treasuries(state)
        migrate_market_currency(state)
        for region_id in state.regions:
            enforce_warehouse_capacity(state, int(region_id))
        lock_all_ai_region_control(state)
        from .content.v1_2.strategies import ensure_strategy_records
        from .content.v1_2.events import ensure_story_event_record, event_key
        from .content.v1_2.scenario import merge_expanded_roster_into_state

        merge_expanded_roster_into_state(state)
        state.flags.setdefault("v12_story_events", [1, 2])
        legacy_pending = {int(item) for item in state.flags.get("pending_story_events", [])}
        for legacy_event_id in (1201, 1202, 1203, 1204):
            state.events.pop(legacy_event_id, None)
        pending = [int(item) for item in state.flags.get("pending_story_events", []) if int(item) not in {1201, 1202, 1203, 1204}]
        for story_id, legacy_id in ((1, 1201), (2, 1202)):
            ensure_story_event_record(state, story_id)
            if legacy_id in legacy_pending and event_key(story_id) not in pending:
                pending.append(event_key(story_id))
        # 事件15早期把设计稿中的分隔线和条件说明当成了正文。尚未展示的
        # 旧存档事件在读取时按当前三名主将的生存状态重新生成显示文本。
        if event_key(15) in pending:
            ensure_story_event_record(state, 15)
        state.flags["pending_story_events"] = pending
        if 1203 in legacy_pending:
            from .content.v1_2.scenario import queue_wei_peace_offer_during_diplomacy

            state.flags.pop("v12_wei_peace_offer_date", None)
            queue_wei_peace_offer_during_diplomacy(state)
        ensure_strategy_records(state)
        if str(state.flags.get("rules_version", "")) == "1.3":
            from .content.v1_3.culture import initialize_v13

            initialize_v13(state, inherited_from=str(state.flags.get("inherited_from", "yuanjia_governance")))
    # 后续剧情加入了新人物与家族；为已有1.1存档补齐配置，不改动普通v1测试状态。
    if state.events:
        from .v11 import load_v11_families, load_v11_persons

        configured_people = load_v11_persons()
        configured_families = load_v11_families()
        for person_id in (94, 95, 96):
            if person_id not in state.persons:
                state.persons[person_id] = copy.deepcopy(configured_people[person_id])
        for family_id in (28, 29, 30):
            if family_id not in state.families:
                state.families[family_id] = copy.deepcopy(configured_families[family_id])
    return state
