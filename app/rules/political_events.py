from __future__ import annotations

import random
from typing import Any

from ..models import Army, GameState
from .common import clamp, person_power
from .laws import is_at_war, is_emperor, level


TENDENCY_COUP_MODIFIER = {
    1: 0.25,
    2: -0.50,
    3: 0.00,
    4: 0.00,
    5: 0.20,
    6: 0.15,
    7: 0.40,
    8: 0.05,
    9: 0.10,
    10: 0.00,
}


def stability_factor(stability: int) -> float:
    if stability >= 70:
        return 0.01
    if stability >= 30:
        return 0.05
    return 0.10


def coup_base_probability(state: GameState, person: dict[str, Any]) -> float:
    values_law = level(state, "values")
    base = {1: 0.30, 2: 0.20, 3: 0.10, 4: 0.05, 5: 0.01}[values_law]
    if values_law == 5 and is_at_war(state, state.player_regime_id):
        base = 0.0
    if level(state, "power") == 5:
        base += 0.10
    base += TENDENCY_COUP_MODIFIER.get(int(person.get("political_tendency", 10)), 0.0)
    return max(0.0, base)


def rebellion_base_probability(state: GameState, person: dict[str, Any]) -> float:
    values_law = level(state, "values")
    base = {1: 0.30, 2: 0.20, 3: 0.10, 4: 0.05, 5: 0.01}[values_law]
    if values_law == 5 and is_at_war(state, state.player_regime_id):
        base = 0.0
    if level(state, "power") == 5:
        base += 0.15
    base += TENDENCY_COUP_MODIFIER.get(int(person.get("political_tendency", 10)), 0.0)
    return max(0.0, base)


def event_probability(state: GameState, person: dict[str, Any], base: float, capital_region: bool = False) -> float:
    loyalty = clamp(float(person.get("attributes", {}).get("loyalty", 0)), 0, 100)
    opinion = clamp(float(person.get("opinion_of_player", 0)), -100, 100)
    chance = base * (100 - loyalty) * 0.01 * (100 - opinion) * 0.01
    chance *= stability_factor(int(state.player_regime.get("stability", 0)))
    if capital_region:
        chance *= 0.5
    return clamp(chance, 0.0, 1.0)


def _ideology_similarity(left: dict[str, Any], right: dict[str, Any]) -> int:
    return 2 if int(left.get("ideology", 8)) == int(right.get("ideology", 8)) else 0


def party_power(state: GameState, party: dict[str, Any]) -> float:
    from .laws import family_land_power

    member_power = sum(
        person_power(state, state.persons[int(person_id)])
        for person_id in party.get("members", []) if int(person_id) in state.persons
    )
    family_power = 0.0
    for family_id in party.get("supported_families", []):
        family = state.families.get(int(family_id))
        if not family:
            continue
        family_power += family_land_power(state, int(family_id))
        family_power += sum(
            person_power(state, state.persons[int(person_id)])
            for person_id in family.get("members", []) if int(person_id) in state.persons
        )
    return member_power + family_power


def _refresh_family_alignment(state: GameState, party: dict[str, Any]) -> None:
    leader = state.persons.get(int(party.get("leader") or 0))
    if not leader:
        party["supported_families"] = []
        return
    party["supported_families"] = [
        int(family_id) for family_id, family in state.families.items()
        if (family_leader := state.persons.get(int(family.get("leader") or 0)))
        and int(family_leader.get("country_id", 0)) == state.player_regime_id
        and _ideology_similarity(leader, family_leader) >= 2
    ]


def _party_membership_actions(state: GameState, party: dict[str, Any]) -> None:
    leader = state.persons.get(int(party.get("leader") or 0))
    if not leader or int(leader.get("status", 0)) not in {1, 2, 3}:
        return
    members = [int(x) for x in party.setdefault("members", []) if int(x) in state.persons]
    if int(leader["id"]) not in members:
        members.insert(0, int(leader["id"]))
    occupied = {
        int(member)
        for other in state.parties.values()
        for member in other.get("members", [])
    }
    candidates = [
        person for person in state.persons.values()
        if int(person.get("country_id", 0)) == state.player_regime_id
        and int(person.get("status", 0)) in {1, 2, 3}
        and int(person["id"]) not in occupied
        and _ideology_similarity(leader, person) >= 2
    ]
    if candidates:
        recruit = max(candidates, key=lambda person: (int(person.get("opinion_of_player", 0)), person_power(state, person)))
        members.append(int(recruit["id"]))
    party["members"] = list(dict.fromkeys(members))


def _recruit_coup_member(state: GameState, party: dict[str, Any]) -> None:
    coup = party.get("coup")
    leader = state.persons.get(int(party.get("leader") or 0))
    if not coup or not leader:
        return
    participants = {int(x) for x in coup.setdefault("participants", [])}
    candidates = [
        state.persons[pid] for pid in party.get("members", [])
        if pid in state.persons and int(pid) not in participants
        and int(state.persons[pid].get("status", 0)) in {1, 2, 3}
    ]
    if not candidates:
        return
    candidate = min(
        candidates,
        key=lambda person: (
            int(person.get("attributes", {}).get("loyalty", 100)) + int(person.get("opinion_of_player", 0)),
            -_ideology_similarity(leader, person),
        ),
    )
    willingness = (
        (100 - int(candidate.get("attributes", {}).get("loyalty", 100)))
        + (100 - int(candidate.get("opinion_of_player", 0)))
        + _ideology_similarity(leader, candidate) * 25
    ) / 250
    if willingness >= 0.5:
        coup["participants"].append(int(candidate["id"]))


def run_party_phase(state: GameState, rng: random.Random | None = None) -> None:
    """Runs immediately after the player's intrigue phase."""
    rng = rng or random
    for party in state.parties.values():
        _refresh_family_alignment(state, party)
        _party_membership_actions(state, party)
        if party.get("coup", {}).get("special_jiankang"):
            continue
        if party.get("name") == "文官党":
            from .national_modifiers import national_modifier_total

            if national_modifier_total(state, "civil_party_coup_immunity") >= 1:
                party.pop("coup", None)
                continue
        leader = state.persons.get(int(party.get("leader") or 0))
        if not leader or int(leader.get("status", 0)) not in {1, 2, 3}:
            party.pop("coup", None)
            continue
        if party.get("coup"):
            _recruit_coup_member(state, party)
            continue
        chance = event_probability(state, leader, coup_base_probability(state, leader))
        if rng.random() < chance:
            party["coup"] = {
                "leader": int(leader["id"]),
                "participants": [int(leader["id"])],
                "progress": 0.0,
                "exposed": int(leader.get("attributes", {}).get("stain", 0)) >= 80,
            }
            state.add_log(f"{party.get('name', '政党')}党魁开始秘密组织政变。")


def settle_coups(state: GameState) -> None:
    player_power = max(1.0, person_power(state, state.player))
    for party in state.parties.values():
        coup = party.get("coup")
        if not coup:
            continue
        if coup.get("special_jiankang"):
            from ..content.v1_1.events_4 import resolve_special_coup_if_player_returns

            if resolve_special_coup_if_player_returns(state):
                continue
            coup["progress"] = min(100.0, float(coup.get("progress", 0.0)) + 10.0)
            coup["exposed"] = True
            state.add_log(f"建康特殊政变正在推进，当前进度{coup['progress']:.1f}%；刘裕回到建康即可终止。")
            continue
        if party.get("name") == "文官党":
            from .national_modifiers import national_modifier_total

            if national_modifier_total(state, "civil_party_coup_immunity") >= 1:
                party.pop("coup", None)
                state.add_log("刘穆之主持台省，文官党的政变企图立即瓦解。")
                continue
        leader_id = int(coup.get("leader", 0))
        if leader_id not in state.persons or int(state.persons[leader_id].get("status", 0)) == 4:
            party.pop("coup", None)
            state.add_log(f"{party.get('name', '政党')}的政变因党魁死亡而瓦解。")
            continue
        participants = [
            state.persons[int(pid)] for pid in coup.get("participants", [])
            if int(pid) in state.persons and int(state.persons[int(pid)].get("status", 0)) in {1, 2, 3}
        ]
        coup_power = sum(person_power(state, person) for person in participants)
        coup["progress"] = min(100.0, float(coup.get("progress", 0.0)) + 25.0 * coup_power / player_power)
        if any(int(person.get("attributes", {}).get("stain", 0)) >= 80 for person in participants):
            coup["exposed"] = True
            for person in participants:
                attrs = person.setdefault("attributes", {})
                attrs["stain"] = int(clamp(int(attrs.get("stain", 0)) + 20, 0, 100))
        if coup.get("exposed"):
            state.add_log(f"{party.get('name', '政党')}政变已经暴露，当前进度{coup['progress']:.1f}%。")


def check_coup_defeat(state: GameState) -> None:
    """达到100%的政变交给剧情事件处理，不再直接结束游戏。"""
    for party in state.parties.values():
        coup = party.get("coup")
        if coup and float(coup.get("progress", 0.0)) >= 100:
            if coup.get("special_jiankang"):
                state.flags["game_over"] = True
                state.flags["game_over_reason"] = "刘裕迟迟未归，建康特殊政变成功，主控政权覆亡。"
                return
            leader_id = int(coup.get("leader", 0))
            key = f"coup_ready:{leader_id}"
            if not state.flags.get(key):
                state.flags[key] = True
                state.add_log(f"{state.person_name(leader_id)}主导的政变已经达到100%，等待相关事件结算。")


def investigate_coup_member(state: GameState, person_id: int, rng: random.Random) -> None:
    for party in state.parties.values():
        coup = party.get("coup")
        if not coup or person_id not in {int(x) for x in coup.get("participants", [])}:
            continue
        person = state.persons.get(person_id)
        if not person:
            continue
        attrs = person.setdefault("attributes", {})
        attrs["stain"] = int(clamp(int(attrs.get("stain", 0)) + rng.randint(10, 30), 0, 100))
        if attrs["stain"] >= 80:
            coup["exposed"] = True


def destroy_coups_led_by(state: GameState, person_id: int) -> None:
    for party in state.parties.values():
        coup = party.get("coup")
        if coup and int(coup.get("leader", 0)) == person_id and not coup.get("special_jiankang"):
            party.pop("coup", None)
            state.add_log(f"{party.get('name', '政党')}的政变因党魁被除掉而瓦解。")


def _region_capital(state: GameState, region: dict[str, Any]) -> int:
    return next(
        (int(city_id) for city_id in region.get("cities", []) if state.cities.get(int(city_id), {}).get("capital")),
        int(region.get("cities", [0])[0]) if region.get("cities") else 0,
    )


def _create_rebel_regime(state: GameState, person: dict[str, Any], region: dict[str, Any]) -> None:
    old_regime_id = state.player_regime_id
    new_id = max(state.regimes, default=0) + 1
    capital = _region_capital(state, region)
    region_name = str(region["name"])
    if region_name in state.player_regime.get("regions", []):
        state.player_regime["regions"].remove(region_name)
    region["controller"] = new_id
    region["governor"] = None
    state.regimes[new_id] = {
        "id": new_id,
        "name": f"{state.person_name(int(person['id']))}叛军",
        "color": "black",
        "is_main": False,
        "regions": [region_name],
        "capital": capital,
        "stability": 40,
        "war_support": 80,
        "treasury": 500,
        "militia": 0,
        "reserve_army": 0,
        "opinion_of_main": -100,
        "relation_with_main": "交战",
        "internal": {"emperor": None, "grand_general": int(person["id"])},
    }
    person["country_id"] = new_id
    pair = state.relation_pair(old_regime_id, new_id)
    if pair not in state.wars:
        from .diplomacy import declare_war

        declare_war(state, new_id, old_regime_id)
    for _ in range(2):
        army_id = max(state.armies, default=0) + 1
        state.armies[army_id] = Army(
            army_id,
            new_id,
            0,
            [{"type": 1, "count": 1000} for _ in range(5)],
            commander=int(person["id"]) if not any(a.commander == person["id"] for a in state.armies.values()) else None,
            location_id=capital,
        )
    state.add_log(f"{state.person_name(int(person['id']))}在{region_name}起兵造反，建立叛军政权并集结两支五千人军队！")


def check_rebellions(state: GameState, rng: random.Random | None = None) -> None:
    rng = rng or random
    capital_region_id = int(state.cities.get(int(state.player_regime.get("capital", 0)), {}).get("region_id", 0))
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for region in list(state.regions.values()):
        governor = state.persons.get(int(region.get("governor") or 0))
        if governor and region.get("name") in state.player_regime.get("regions", []):
            candidates.append((governor, region))
    if level(state, "power") == 5:
        for army in list(state.armies.values()):
            commander = state.persons.get(int(army.commander or 0))
            city = state.cities.get(army.location_id, {})
            region = state.regions.get(int(city.get("region_id", 0)))
            if commander and region and region.get("name") in state.player_regime.get("regions", []):
                candidates.append((commander, region))
    seen: set[int] = set()
    for person, region in candidates:
        if int(person["id"]) == 26 or int(person["id"]) in seen or is_emperor(state, int(person["id"])):
            continue
        seen.add(int(person["id"]))
        chance = event_probability(
            state,
            person,
            rebellion_base_probability(state, person),
            capital_region=int(region["id"]) == capital_region_id,
        )
        if rng.random() < chance:
            _create_rebel_regime(state, person, region)
