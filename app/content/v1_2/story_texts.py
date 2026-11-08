from __future__ import annotations

import re
from functools import lru_cache

from ...constants import V12_DOCS_DIR


STORY_FILE = V12_DOCS_DIR / "1.2元嘉之治_422-433_剧本设计_v2_事件决议区分版.txt"
HEADER = re.compile(r"^(经略|决议|事件)(\d+)[：:]\s*(.+)$")


@lru_cache(maxsize=1)
def sections() -> dict[tuple[str, int], dict[str, object]]:
    if not STORY_FILE.exists():
        return {}
    result: dict[tuple[str, int], dict[str, object]] = {}
    current: tuple[str, int] | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        if current is None:
            return
        entry = result[current]
        text_at = next((i for i, line in enumerate(lines) if line.startswith("文本：")), None)
        metadata = lines if text_at is None else lines[:text_at]
        narrative = [] if text_at is None else lines[text_at + 1 :]
        entry["metadata"] = "\n".join(line for line in metadata if line.strip()).strip()
        intro: list[str] = []
        variants: dict[str, list[str]] = {}
        current_variant: str | None = None
        for line in narrative:
            variant = re.match(r"^【(.+)】\s*$", line.strip())
            if variant:
                variant_name = variant.group(1).strip()
                # Some event entries use a labelled prompt before their actual
                # choice results.  It is part of the main narrative rather than
                # a selectable variant.
                if variant_name in {"提示文", "正文", "事件文本"}:
                    current_variant = None
                else:
                    current_variant = variant_name
                    variants[current_variant] = []
            elif current_variant is None:
                intro.append(line)
            else:
                variants[current_variant].append(line)
        entry["text"] = "\n".join(intro).strip()
        entry["variants"] = {name: "\n".join(value).strip() for name, value in variants.items()}
        lines = []

    for raw in STORY_FILE.read_text(encoding="utf-8-sig").splitlines():
        if current is not None and re.match(r"^[五六七]、", raw.strip()):
            flush()
            current = None
            continue
        match = HEADER.match(raw.strip())
        if match:
            flush()
            current = (match.group(1), int(match.group(2)))
            result[current] = {"name": match.group(3).strip()}
            continue
        if current is not None:
            lines.append(raw)
    flush()
    return result


def story_name(kind: str, story_id: int, fallback: str = "") -> str:
    return str(sections().get((kind, int(story_id)), {}).get("name", fallback))


def story_text(kind: str, story_id: int, fallback: str = "") -> str:
    section = sections().get((kind, int(story_id)), {})
    return str(section.get("text") or section.get("metadata") or fallback)


def story_metadata(kind: str, story_id: int, fallback: str = "") -> str:
    return str(sections().get((kind, int(story_id)), {}).get("metadata") or fallback)


def story_variant(kind: str, story_id: int, key: str, fallback: str = "") -> str:
    variants = sections().get((kind, int(story_id)), {}).get("variants", {})
    normalized = str(key).replace("选项", "").replace("选择", "").strip()
    for name, text in dict(variants).items():
        if normalized in name or name in normalized:
            return str(text or fallback)
    return fallback
