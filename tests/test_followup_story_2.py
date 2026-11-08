from __future__ import annotations

import random
import unittest
from unittest.mock import patch

from app.models import Army
from app.content.v1_1 import decisions, strategies
from app.rules import ai, diplomacy, economy, intrigue, military, politics
from app.rules.common import RuleError
from app.rules.diplomacy import month_index, truce_key
from app.rules.military_modifiers import BattleContext, active_military_modifiers, modifier_effect_total
from app.content.v1_1.events import queue_start_of_turn_events
from app.rules.turn import _settle_regime
from app.v11 import load_v11_state


class FixedRandom:
    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


class GeneralRuleTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_liu_yu_cannot_appoint_an_equal_or_stronger_office(self):
        player_id = int(self.state.player["id"])
        self.state.player_regime["internal"]["shizhong"] = player_id
        with patch("app.rules.laws.random.random", return_value=1.0):
            with self.assertRaisesRegex(RuleError, "无权任免"):
                politics.appoint(self.state, "shangshu_ling", player_id)

    def test_army_commander_location_follows_march(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == self.state.player_regime_id)
        army.commander = int(self.state.player["id"])
        destination = military.legal_moves(self.state, army.id)[0][0]
        military.march(self.state, army.id, destination)
        self.assertEqual(self.state.player["location_id"], destination)

    def test_governor_appointment_does_not_pull_a_commander_off_the_army(self):
        self.state.laws["power"] = 2
        army = next(army for army in self.state.armies.values() if army.regime_id == self.state.player_regime_id)
        player_id = int(self.state.player["id"])
        army.commander = player_id
        self.state.player["location_id"] = army.location_id
        region = next(
            region for region in self.state.regions.values()
            if region["name"] in self.state.player_regime["regions"] and not region.get("governor")
        )
        politics.appoint_governor(self.state, int(region["id"]), player_id)
        self.assertEqual(self.state.player["location_id"], army.location_id)

    def test_empty_treasury_dissolves_zero_morale_army_and_can_end_game(self):
        regime = self.state.player_regime
        regime["treasury"] = 0
        regime["stability"] = 3
        for region in self.state.regions.values():
            if region["name"] in regime["regions"]:
                region["land_ownership"] = []
                region["households"] = 0
        army = next(army for army in self.state.armies.values() if army.regime_id == self.state.player_regime_id)
        army.morale = 5
        army_id = army.id
        _settle_regime(self.state, self.state.player_regime_id)
        self.assertNotIn(army_id, self.state.armies)
        self.assertEqual(regime["stability"], 0)
        self.assertTrue(self.state.flags["game_over"])

    def test_one_year_truce_blocks_declaration(self):
        target = 8
        self.state.laws["north"] = 4
        self.state.regimes[target]["opinion_of_main"] = -100
        self.state.flags[truce_key(self.state, 1, target)] = month_index(self.state) + 12
        with self.assertRaisesRegex(RuleError, "停战协定"):
            diplomacy.act(self.state, target, "宣战")

    def test_rejected_command_cannot_be_retried_in_the_same_turn(self):
        self.state.laws["power"] = 1
        before = self.state.player_regime["treasury"]
        with patch("app.rules.laws.random.random", return_value=0.0):
            with self.assertRaisesRegex(RuleError, "驳回"):
                politics.temporary_tax(self.state)
        with patch("app.rules.laws.random.random", return_value=1.0):
            with self.assertRaisesRegex(RuleError, "已经被驳斥"):
                politics.temporary_tax(self.state)
        self.assertEqual(self.state.player_regime["treasury"], before)

        self.state.turn_number += 1
        with patch("app.rules.laws.random.random", return_value=1.0):
            politics.temporary_tax(self.state)
        self.assertGreater(self.state.player_regime["treasury"], before)

    def test_opening_militia_and_population_based_growth(self):
        self.assertEqual(self.state.player_regime["militia"], 10000)
        self.assertEqual(economy.regime_militia_growth(self.state, self.state.player_regime_id), 300)
        self.state.regions[1]["governor"] = int(self.state.player["id"])
        self.assertGreater(economy.regime_militia_growth(self.state, 1), 300)

    def test_early_gentry_law_causes_monthly_militia_loss(self):
        regime = self.state.player_regime
        self.state.laws["gentry"] = 1
        regime["militia"] = 10_000
        gain = economy.regime_militia_growth(self.state, self.state.player_regime_id)
        _settle_regime(self.state, self.state.player_regime_id)
        self.assertEqual(regime["militia"], 10_000 - 3_000 + gain)

    def test_reclaim_land_adds_fifteen_owned_slots(self):
        self.state.laws["power"] = 2
        region = self.state.regions[1]
        old_land = int(region["land"])
        old_slots = len(region["land_ownership"])
        old_militia = self.state.player_regime["militia"]
        old_authority = self.state.authority
        politics.reclaim_land(self.state, 1, random.Random(7))
        added = region["land_ownership"][old_slots:]
        self.assertEqual(region["land"], old_land + 15)
        self.assertEqual(len(added), 15)
        self.assertEqual(added.count(2), 5)
        self.assertEqual(added.count(0), 5)
        self.assertEqual(sum(owner in self.state.families for owner in added), 5)
        self.assertEqual(self.state.player_regime["militia"], old_militia - 500)
        self.assertEqual(self.state.authority, old_authority - 50)

    def test_conscription_requires_thousand_person_units(self):
        self.state.laws["power"] = 2
        with self.assertRaisesRegex(RuleError, "1000"):
            politics.conscript(self.state, 1500)

    def test_intrigue_targets_exclude_player_and_confidants(self):
        targets = {int(person["id"]) for person in intrigue.available_targets(self.state)}
        self.assertNotIn(int(self.state.player["id"]), targets)
        self.assertTrue(set(self.state.confidants).isdisjoint(targets))
        self.assertTrue(all(int(self.state.persons[person_id].get("country_id", 0)) == self.state.player_regime_id for person_id in targets))

        confidant = next(
            int(person["id"])
            for person in self.state.persons.values()
            if int(person.get("country_id", 0)) == self.state.player_regime_id
            and int(person.get("status", 0)) == 1
            and not person.get("is_player")
        )
        self.state.confidants.append(confidant)
        foreigner = next(
            int(person["id"])
            for person in self.state.persons.values()
            if int(person.get("country_id", 0)) != self.state.player_regime_id
            and int(person.get("status", 0)) in {1, 2, 3}
        )
        with self.assertRaisesRegex(RuleError, "外国人"):
            intrigue.perform(self.state, confidant, foreigner, "拉拢", random.Random(1))


class StrategyAndDecisionTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def _complete(self, *strategy_ids: int) -> None:
        for strategy_id in strategy_ids:
            self.state.strategies[strategy_id]["status"] = "completed"

    def test_court_strategy_requires_event_three_and_applies_its_effect(self):
        self._complete(1, 2)
        self.assertFalse(strategies.strategy_available(self.state, 3)[0])
        self.state.events[3]["triggered"] = True
        before_stability = self.state.player_regime["stability"]
        tracked_person = next(person for person in self.state.persons.values() if int(person.get("status", 0)) in {1, 2, 3})
        before_opinion = tracked_person["opinion_of_player"]
        strategies.start_strategy(self.state, 3)
        for _ in range(3):
            strategies.settle_strategies(self.state)
        self.assertTrue(strategies.strategy_completed(self.state, 3))
        self.assertEqual(self.state.player_regime["stability"], before_stability + 3)
        self.assertEqual(tracked_person["opinion_of_player"], min(100, before_opinion + 5))
        self.assertTrue(decisions.decision_visible(self.state, 3))

    def test_strategy_genealogy_comes_from_prerequisites_and_completion_state(self):
        self._complete(1, 7)
        nodes, edges = strategies.strategy_genealogy(self.state)
        completed = {node["id"] for node in nodes if node["completed"]}
        self.assertEqual(completed, {1, 7})
        self.assertIn((1, 3), edges)
        self.assertIn((2, 3), edges)
        self.assertIn((7, 8), edges)
        self.assertNotIn((4, 8), edges)

    def test_develop_south_adds_central_and_self_farming_land(self):
        self.state.player_regime["militia"] = 10000
        tracked = {
            region_id: len(region["land_ownership"])
            for region_id, region in self.state.regions.items()
            if 1 <= region_id <= 12 and region["controller"] == 1
        }
        strategies.start_strategy(self.state, 4)
        for _ in range(5):
            strategies.settle_strategies(self.state)
        self.assertEqual(self.state.player_regime["militia"], 0)
        for region_id, old_length in tracked.items():
            added = self.state.regions[region_id]["land_ownership"][old_length:]
            self.assertEqual(added, [2] * 15 + [0] * 15)

    def test_october_rewards_changes_offices_levels_and_power(self):
        self._complete(3)
        player_power = self.state.player["attributes"]["base_power"]
        liu_yi = next(person for person in self.state.persons.values() if self.state.person_name(person["id"]) == "刘毅")
        liu_yi_level = liu_yi["level"]
        decisions.execute_decision(self.state, 3, "要的多一些")
        self.assertEqual(self.state.player_regime["internal"]["lu_shangshu"], self.state.player["id"])
        self.assertEqual(self.state.player["attributes"]["base_power"], player_power + 15)
        self.assertEqual(liu_yi["level"], liu_yi_level + 1)

    def test_panyu_raid_success_and_failure(self):
        success = load_v11_state()
        success.strategies[6]["status"] = "completed"
        pair = success.relation_pair(1, 5)
        success.wars.append(pair)
        guangzhou = success.regions[10]
        guangzhou["controller"] = 5
        panyu_armies = [army for army in success.armies.values() if army.location_id == 69 and army.regime_id == 5]
        for army in panyu_armies:
            success.armies.pop(army.id)
        decisions.execute_decision(success, 6, rng=FixedRandom(0.99))
        self.assertEqual(guangzhou["controller"], 1)
        self.assertTrue(any(army.location_id == 69 and success.person_name(army.commander) == "孙处" for army in success.armies.values()))

        failure = load_v11_state()
        failure.strategies[6]["status"] = "completed"
        failure.wars.append(failure.relation_pair(1, 5))
        failure.regions[10]["controller"] = 5
        defender = next(army for army in failure.armies.values() if army.regime_id == 5)
        defender.location_id = 69
        defender.units = [{"type": 1, "count": 1000}]
        before_reserve = failure.player_regime["reserve_army"]
        decisions.execute_decision(failure, 6, rng=FixedRandom(0.99))
        sun_chu = next(person for person in failure.persons.values() if failure.person_name(person["id"]) == "孙处")
        self.assertEqual(sun_chu["status"], 4)
        self.assertEqual(failure.player_regime["reserve_army"], max(0, before_reserve - 5000))

    def test_yan_strategy_is_instant_during_an_existing_war(self):
        self._complete(7)
        self.state.wars.append(self.state.relation_pair(1, 8))
        strategies.start_strategy(self.state, 8)
        self.assertTrue(strategies.strategy_completed(self.state, 8))
        self.assertFalse(self.state.flags.get("yan_free_declaration_available", False))


class EventModifierAndAITests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_qiao_shu_reinforcement_event_creates_five_thousand_troops(self):
        self.state.events[2]["triggered"] = True
        self.state.year, self.state.month = 405, 8
        before = set(self.state.armies)
        triggered = queue_start_of_turn_events(self.state)
        self.assertIn(4, triggered)
        created = [army for army_id, army in self.state.armies.items() if army_id not in before and army.regime_id == 4]
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].location_id, 57)
        self.assertEqual(created[0].soldiers, 5000)

    def test_lu_xun_ambush_creates_forces_and_sets_offensive_targets(self):
        self.state.wars.append(self.state.relation_pair(1, 8))
        before = set(self.state.armies)
        self.assertIn(5, queue_start_of_turn_events(self.state))
        created = [army for army_id, army in self.state.armies.items() if army_id not in before and army.regime_id == 5]
        self.assertEqual(len(created), 4)
        self.assertEqual(sorted(army.soldiers for army in created), [5000, 5000, 5000, 5000])
        self.assertIn(self.state.relation_pair(1, 5), self.state.wars)
        self.assertEqual(self.state.flags["lu_xun_offensive_targets"], [26, 1])

    def test_lu_xun_defensive_event_is_mutually_exclusive(self):
        pair = self.state.relation_pair(1, 5)
        self.state.wars.append(pair)
        self.state.flags[f"war_aggressor:{pair[0]}:{pair[1]}"] = 1
        triggered = queue_start_of_turn_events(self.state)
        self.assertIn(6, triggered)
        self.assertNotIn(5, triggered)
        self.assertFalse(self.state.events[5]["triggered"])

    def test_capture_of_jiankang_ends_game(self):
        self.state.regions[self.state.cities[1]["region_id"]]["controller"] = 5
        self.assertIn(7, queue_start_of_turn_events(self.state))
        self.assertTrue(self.state.flags["game_over"])

    def test_new_military_modifiers_stack_in_number_order(self):
        self.state.strategies[7]["status"] = "completed"
        attacker = Army(
            900,
            1,
            0,
            [{"type": 1, "count": 1000}],
            commander=int(self.state.player["id"]),
            location_id=1,
        )
        navy = Army(901, 1, 1, [{"type": 4, "count": 1000}], location_id=1)
        opponent = next(army for army in self.state.armies.values() if army.regime_id == 4)
        self.state.armies[attacker.id] = attacker
        self.state.armies[navy.id] = navy
        context = BattleContext("attacker", opponent.location_id, opponent.id)
        active = active_military_modifiers(self.state, attacker, context)
        self.assertEqual([item["id"] for item in active if item["id"] >= 6], [6, 7])
        self.assertAlmostEqual(modifier_effect_total(active, "attack"), 0.70)

    def test_march_into_shu_modifier_uses_the_target_region(self):
        self.state.strategies[5]["status"] = "completed"
        commander = next(person["id"] for person in self.state.persons.values() if self.state.person_name(person["id"]) == "刘敬宣")
        attacker = Army(910, 1, 0, [{"type": 1, "count": 1000}], commander=commander, location_id=1)
        opponent = next(army for army in self.state.armies.values() if army.regime_id == 4)
        self.state.armies[attacker.id] = attacker
        into_yizhou = BattleContext("attacker", 57, opponent.id)
        out_of_yizhou = BattleContext("attacker", 1, opponent.id)
        self.assertIn(5, [item["id"] for item in active_military_modifiers(self.state, attacker, into_yizhou)])
        self.assertNotIn(5, [item["id"] for item in active_military_modifiers(self.state, attacker, out_of_yizhou)])

    def test_lu_xun_ai_moves_toward_xunyang(self):
        self.state.wars.append(self.state.relation_pair(1, 8))
        queue_start_of_turn_events(self.state)
        armies = [army for army in self.state.armies.values() if army.regime_id == 5]
        before = min(ai._road_distance(self.state, army.location_id, 26) for army in armies)
        ai.military_actions(self.state, 5, random.Random(3))
        after = min(ai._road_distance(self.state, army.location_id, 26) for army in self.state.armies.values() if army.regime_id == 5)
        self.assertLess(after, before)


if __name__ == "__main__":
    unittest.main()
