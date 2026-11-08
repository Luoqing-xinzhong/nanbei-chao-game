from __future__ import annotations

from pathlib import Path

GAME_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = GAME_DIR.parent
CONTENT_DIR = GAME_DIR / "app" / "content"
V11_CONTENT_DIR = CONTENT_DIR / "v1_1"
V12_CONTENT_DIR = CONTENT_DIR / "v1_2"
RESOURCES_DIR = GAME_DIR / "resources"
COMMON_CONFIG_DIR = RESOURCES_DIR / "common" / "config"
VERSIONS_DIR = RESOURCES_DIR / "versions"
V11_CONFIG_DIR = VERSIONS_DIR / "1.1" / "config"
V11_DOCS_DIR = VERSIONS_DIR / "1.1" / "docs"
V12_CONFIG_DIR = VERSIONS_DIR / "1.2" / "config"
V12_DOCS_DIR = VERSIONS_DIR / "1.2" / "docs"
V13_CONFIG_DIR = VERSIONS_DIR / "1.3" / "config"
V13_DOCS_DIR = VERSIONS_DIR / "1.3" / "docs"

# 兼容原有调用方名称；通用初始化模板现在统一位于 common/config。
JSON_DIR = COMMON_CONFIG_DIR
SAVE_DIR = GAME_DIR / "saves"

# 地图目前由用户放在项目根目录；保留 game/assets 的覆盖位置，方便以后打包。
MAP_CANDIDATES = (GAME_DIR / "assets" / "map.png", PROJECT_DIR / "地图.png")

MAP_WIDTH = 2416
MAP_HEIGHT = 1762
START_YEAR = 404
START_MONTH = 10
AUTHORITY_CAP = 2000

PHASES = ("政治阶段", "谋划阶段", "外交阶段", "军事阶段")

REGIME_COLORS = {
    "red": "#d83b3b",
    "purple": "#7757b8",
    "blue": "#3278c8",
    "darkblue": "#1f3a70",
    "green": "#2e9d61",
    "orange": "#e58a34",
    "yellow": "#d1a522",
    "brightyellow": "#f6c800",
    "darkgold": "#b8860b",
    "pink": "#d05c91",
    "brown": "#8b5a38",
    "cyan": "#1f9fae",
    "deepskyblue": "#00bfff",
    "black": "#333333",
    "gray": "#777777",
    "grey": "#777777",
    "white": "#e8e5d8",
}

ROAD_NAMES = {1: "陆路", 2: "山路", 3: "水路", 4: "海路"}

OFFICE_NAMES = {
    "emperor": "皇帝",
    "lu_shangshu": "录尚书事",
    "shangshu_ling": "尚书令",
    "left_shangshu": "尚书左仆射",
    "right_shangshu": "尚书右仆射",
    "zhongshu_ling": "中书令",
    "zhongshu_shilang": "中书侍郎",
    "shizhong": "侍中",
    "sanqi_changshi": "散骑常侍",
    "sanqi_shilang1": "散骑侍郎（一）",
    "sanqi_shilang2": "散骑侍郎（二）",
    "grand_general": "大将军",
    "imperial_guard_commander": "禁军统领",
}

# 官职基础权力用于人物权力和刘裕可控制官职范围的统一判定。
OFFICE_BASE_POWER = {
    "emperor": 100,
    "lu_shangshu": 100,
    "grand_general": 100,
    "imperial_guard_commander": 100,
    "shangshu_ling": 80,
    "zhongshu_ling": 80,
    "shizhong": 80,
    "left_shangshu": 50,
    "right_shangshu": 50,
    "zhongshu_shilang": 50,
    "sanqi_changshi": 50,
    "sanqi_shilang1": 50,
    "sanqi_shilang2": 50,
    "governor": 50,
}
