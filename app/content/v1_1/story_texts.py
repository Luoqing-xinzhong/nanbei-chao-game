from __future__ import annotations

import re
from functools import lru_cache
from xml.etree import ElementTree
from zipfile import ZipFile

from ...constants import V11_DOCS_DIR


DOCUMENT_PATH = V11_DOCS_DIR / "后续剧情4.docx"
HEADER_RE = re.compile(r"^(事件|决议|经略)(\d+)[：:]\s*(.+)$")
CHOICE_RE = re.compile(r"^选择(.+?)的文本[：:]\s*(.*)$")
NUMBERED_CHOICE_RE = re.compile(r"^选([1-4])的文本[：:]\s*(.*)$")
DEATH_VARIANT_RE = re.compile(r"^(如果死亡时.+?)[，,]文本[：:]\s*(.*)$")


def _paragraphs() -> list[str]:
    if not DOCUMENT_PATH.exists():
        return []
    with ZipFile(DOCUMENT_PATH) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body = root.find(f"{namespace}body")
    if body is None:
        return []
    result: list[str] = []
    for node in body:
        if node.tag not in {f"{namespace}p", f"{namespace}tbl"}:
            continue
        text = "".join(part.text or "" for part in node.iter(f"{namespace}t")).strip()
        if text:
            result.append(text)
    return result


@lru_cache(maxsize=1)
def _sections() -> dict[tuple[str, int], list[str]]:
    sections: dict[tuple[str, int], list[str]] = {}
    current: tuple[str, int] | None = None
    for paragraph in _paragraphs():
        match = HEADER_RE.match(paragraph)
        if match:
            current = (match.group(1), int(match.group(2)))
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(paragraph)
    return sections


def story_section(kind: str, section_id: int, fallback: str = "") -> dict[str, object]:
    """Return narrative intro and choice/ending variants from the design document."""
    paragraphs = _sections().get((kind, int(section_id)), [])
    intro: list[str] = []
    variants: dict[str, list[str]] = {}
    active_variant: str | None = None
    narrative_started = False
    for paragraph in paragraphs:
        numbered = NUMBERED_CHOICE_RE.match(paragraph)
        choice = CHOICE_RE.match(paragraph)
        death = DEATH_VARIANT_RE.match(paragraph)
        variant_match = numbered or choice or death
        if variant_match:
            active_variant = variant_match.group(1).strip()
            variants[active_variant] = []
            remainder = variant_match.group(2).strip()
            if remainder:
                variants[active_variant].append(remainder)
            narrative_started = True
            continue
        if paragraph.startswith("文本：") or paragraph.startswith("提示文本："):
            narrative_started = True
            active_variant = None
            intro.append(paragraph.split("：", 1)[1].strip())
            continue
        if not narrative_started:
            continue
        if paragraph.startswith(("注：", "军事修正", "国家修正")):
            break
        if active_variant is None:
            intro.append(paragraph)
        else:
            variants[active_variant].append(paragraph)
    intro_text = "\n\n".join(item for item in intro if item).strip() or fallback
    return {
        "intro": intro_text,
        "variants": {key: "\n\n".join(values).strip() for key, values in variants.items()},
    }


def story_text(kind: str, section_id: int, fallback: str = "") -> str:
    return str(story_section(kind, section_id, fallback)["intro"])


def story_variant(kind: str, section_id: int, key: str, fallback: str = "") -> str:
    variants = story_section(kind, section_id).get("variants", {})
    return str(variants.get(str(key), fallback))


def render_dynamic_text(state, value: str) -> str:
    """将剧情设计稿中的动态年号占位符按当前游戏日期实时渲染。"""
    from ...rules.turn import reign_year_text

    era_name = str(state.flags.get("era_name", "元兴"))
    era_start_year = int(state.flags.get("era_start_year", 402))
    reign_year = reign_year_text(int(state.year), era_name, era_start_year)
    return re.sub(r"\{?年号\s*\+\s*年号计数\}?", reign_year, str(value))
