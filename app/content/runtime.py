from __future__ import annotations

from ..models import GameState


def is_v12(state: GameState) -> bool:
    return str(state.flags.get("content_version", "1.1")) == "1.2"


def queue_start_of_turn_events(state: GameState) -> list[int]:
    if str(state.flags.get("rules_version", "")) == "1.3":
        return []
    if is_v12(state):
        from .v1_2.scenario import queue_start_of_turn_events as queue
    else:
        from .v1_1.events import queue_start_of_turn_events as queue
    return queue(state)


def apply_event_choice(state: GameState, event_id: int, choice: str) -> str:
    if is_v12(state):
        from .v1_2.scenario import apply_event_choice as apply
    else:
        from .v1_1.events_4 import apply_event_choice as apply
    return apply(state, event_id, choice)


def render_dynamic_text(state: GameState, value: str) -> str:
    # The placeholder syntax is content-version neutral.
    from .v1_1.story_texts import render_dynamic_text as render

    return render(state, value)
