from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .constants import AUTHORITY_CAP, PHASES, START_MONTH, START_YEAR


@dataclass
class Army:
    id: int
    regime_id: int
    army_type: int
    units: list[dict[str, int]]
    morale: int = 80
    experience: int = 0
    commander: int | None = None
    location_id: int = 0
    action_points: float = 1.0
    max_action_points: float = 1.0
    rewarded_this_turn: bool = False
    commander_changed_this_turn: bool = False
    commander_locked: bool = False
    supply_food: float = 0.0
    modifiers: list[dict[str, Any]] = field(default_factory=list)
    establishment: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.establishment:
            self.establishment = [
                int(unit.get("type", 0)) for unit in self.units
                if int(unit.get("type", 0)) > 0
            ]

    @property
    def soldiers(self) -> int:
        return sum(max(0, unit.get("count", 0)) for unit in self.units)

    @property
    def active_battalions(self) -> int:
        return sum(1 for unit in self.units if unit.get("type", 0) and unit.get("count", 0) > 0)

    @property
    def pure_cavalry(self) -> bool:
        used = [unit for unit in self.units if unit.get("count", 0) > 0]
        return bool(used) and all(unit.get("type") == 2 for unit in used)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Army":
        return cls(**value)


@dataclass
class GameState:
    cities: dict[int, dict[str, Any]]
    regions: dict[int, dict[str, Any]]
    regimes: dict[int, dict[str, Any]]
    persons: dict[int, dict[str, Any]]
    families: dict[int, dict[str, Any]]
    roads: list[dict[str, Any]]
    armies: dict[int, Army]
    year: int = START_YEAR
    month: int = START_MONTH
    phase_index: int = 0
    authority: int = 1000
    turn_number: int = 1
    confidants: list[int] = field(default_factory=list)
    wars: list[list[int]] = field(default_factory=list)
    vassals: dict[int, int] = field(default_factory=dict)
    diplomatic_actions: list[int] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    event_log: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    laws: dict[str, int] = field(default_factory=dict)
    parties: dict[int, dict[str, Any]] = field(default_factory=dict)
    legislation: dict[str, Any] = field(default_factory=dict)
    national_modifiers: list[dict[str, Any]] = field(default_factory=list)
    events: dict[int, dict[str, Any]] = field(default_factory=dict)
    strategies: dict[int, dict[str, Any]] = field(default_factory=dict)

    @property
    def phase_names(self) -> tuple[str, ...]:
        if str(self.flags.get("rules_version", "")) == "1.3":
            return ("政治阶段", "发展阶段", "谋划阶段", "外交阶段", "军事阶段")
        return PHASES

    @property
    def phase(self) -> str:
        return self.phase_names[self.phase_index]

    @property
    def player_regime(self) -> dict[str, Any]:
        return next((r for r in self.regimes.values() if r.get("is_main")), self.regimes[min(self.regimes)])

    @property
    def player_regime_id(self) -> int:
        return int(self.player_regime["id"])

    @property
    def player(self) -> dict[str, Any]:
        return next((p for p in self.persons.values() if p.get("is_player")), self.persons[min(self.persons)])

    def person_name(self, person_id: int | None) -> str:
        if not person_id or person_id not in self.persons:
            return "空缺"
        person = self.persons[person_id]
        return f"{person.get('surname', '')}{person.get('given_name', '')}"

    def city_name(self, city_id: int) -> str:
        return self.cities.get(city_id, {}).get("name", f"城市#{city_id}")

    def relation_pair(self, left: int, right: int) -> list[int]:
        return sorted((int(left), int(right)))

    def at_war(self, left: int, right: int) -> bool:
        return self.relation_pair(left, right) in self.wars

    def add_log(self, message: str) -> None:
        self.event_log.append(message)

    def normalize_person_power_data(self, initial: bool = False) -> None:
        """Normalize configured people; runtime saves may retain event-earned levels above 5."""
        emperors = {
            int(regime.get("internal", {}).get("emperor") or 0)
            for regime in self.regimes.values()
        }
        for person in self.persons.values():
            person_id = int(person.get("id", 0))
            old_level = int(person.get("level", 0) or 0)
            if person_id in emperors:
                person["level"] = 10
            elif initial:
                person["level"] = max(0, min(5, old_level))
            else:
                person["level"] = max(0, old_level)
            attributes = person.setdefault("attributes", {})
            base_power = max(0, int(attributes.get("base_power", 0) or 0))
            # 配置初值一律不超过100；游戏中只有达到6级的人能保留事件获得的超额权力。
            if initial or int(person.get("level", 0)) < 6:
                base_power = min(100, base_power)
            attributes["base_power"] = base_power

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "calendar": {"year": self.year, "month": self.month, "turn": self.turn_number},
            "phase_index": self.phase_index,
            "authority": self.authority,
            "cities": list(self.cities.values()),
            "regions": list(self.regions.values()),
            "regimes": list(self.regimes.values()),
            "persons": list(self.persons.values()),
            "families": list(self.families.values()),
            "roads": self.roads,
            "armies": [army.to_dict() for army in self.armies.values()],
            "confidants": self.confidants,
            "wars": self.wars,
            "vassals": self.vassals,
            "diplomatic_actions": self.diplomatic_actions,
            "flags": self.flags,
            "event_log": self.event_log,
            "diagnostics": self.diagnostics,
            "laws": self.laws,
            "parties": self.parties,
            "legislation": self.legislation,
            "national_modifiers": self.national_modifiers,
            "events": self.events,
            "strategies": self.strategies,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GameState":
        calendar = value.get("calendar", {})
        state = cls(
            cities={int(x["id"]): x for x in value["cities"]},
            regions={int(x["id"]): x for x in value["regions"]},
            regimes={int(x["id"]): x for x in value["regimes"]},
            persons={int(x["id"]): x for x in value["persons"]},
            families={int(x["id"]): x for x in value["families"]},
            roads=value["roads"],
            armies={int(x["id"]): Army.from_dict(x) for x in value.get("armies", [])},
            year=int(calendar.get("year", START_YEAR)),
            month=int(calendar.get("month", START_MONTH)),
            turn_number=int(calendar.get("turn", 1)),
            phase_index=int(value.get("phase_index", 0)),
            authority=int(value.get("authority", 1000)),
            confidants=[int(x) for x in value.get("confidants", [])],
            wars=[[int(n) for n in x] for x in value.get("wars", [])],
            vassals={int(k): int(v) for k, v in value.get("vassals", {}).items()},
            diplomatic_actions=[int(x) for x in value.get("diplomatic_actions", [])],
            flags=value.get("flags", {}),
            event_log=value.get("event_log", []),
            diagnostics=value.get("diagnostics", []),
            laws={str(k): int(v) for k, v in value.get("laws", {}).items()},
            parties={int(k): v for k, v in value.get("parties", {}).items()},
            legislation=dict(value.get("legislation", {})),
            national_modifiers=list(value.get("national_modifiers", [])),
            events={int(k): dict(v) for k, v in value.get("events", {}).items()},
            strategies={int(k): dict(v) for k, v in value.get("strategies", {}).items()},
        )
        state.authority = min(AUTHORITY_CAP, max(0, int(state.authority)))
        state.normalize_person_power_data()
        for regime_id, regime in state.regimes.items():
            if regime_id != state.player_regime_id:
                regime.setdefault("authority", 200)
            regime["authority"] = min(AUTHORITY_CAP, max(0, int(regime.get("authority", 0))))
            capital = state.cities.get(int(regime.get("capital") or 0), {})
            legal_regions = set(regime.get("regions", []))
            if capital.get("region") not in legal_regions:
                replacement = next(
                    (
                        int(city["id"]) for city in state.cities.values()
                        if city.get("capital") and city.get("region") in legal_regions
                    ),
                    None,
                )
                if replacement is not None:
                    regime["capital"] = replacement
        return state
