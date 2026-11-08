from __future__ import annotations

from collections import Counter
import unittest

from app.models import GameState
from app.content.v1_1 import decisions, strategies
from app.rules.common import RuleError
from app.rules.military_modifiers import BattleContext, active_military_modifiers, modifier_effect_total
from app.content.v1_1.events import FOUR_JINGCHU_REGIONS, person_id_by_name, queue_start_of_turn_events
from app.rules.turn import calendar_text
from app.v11 import load_v11_state


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_one_month_strategy_completes_and_unlocks_decision(self):
        before = self.state.player_regime["stability"]
        strategies.start_strategy(self.state, 1)
        with self.assertRaisesRegex(RuleError, "同时只能"):
            strategies.start_strategy(self.state, 2)
        self.assertEqual(strategies.settle_strategies(self.state), [1])
        self.assertTrue(strategies.strategy_completed(self.state, 1))
        self.assertEqual(self.state.player_regime["stability"], before + 10)
        self.assertTrue(decisions.decision_visible(self.state, 1))

    def test_strategy_state_survives_save_round_trip(self):
        strategies.start_strategy(self.state, 2)
        restored = GameState.from_dict(self.state.to_dict())
        self.assertEqual(strategies.active_strategy(restored)["id"], 2)
        strategies.settle_strategies(restored)
        self.assertTrue(strategies.strategy_completed(restored, 2))

    def test_strategy_pauses_when_requirement_fails_and_resumes_with_progress(self):
        self.state.player_regime["militia"] = 10000
        strategies.start_strategy(self.state, 4)
        strategies.settle_strategies(self.state)
        self.assertEqual(self.state.strategies[4]["progress_months"], 1)

        self.state.player_regime["militia"] = 9000
        strategies.settle_strategies(self.state)
        self.assertEqual(self.state.strategies[4]["status"], "paused")
        self.assertEqual(self.state.strategies[4]["progress_months"], 1)
        self.assertEqual(strategies.active_strategy(self.state)["id"], 4)
        self.assertFalse(strategies.strategy_available(self.state, 2)[0])

        self.state.player_regime["militia"] = 10000
        strategies.settle_strategies(self.state)
        self.assertEqual(self.state.strategies[4]["status"], "in_progress")
        self.assertEqual(self.state.strategies[4]["progress_months"], 2)

    def test_cancelled_strategy_loses_progress_and_graph_exposes_four_states(self):
        nodes, _edges = strategies.strategy_genealogy(self.state)
        opening = {node["id"]: node for node in nodes}
        self.assertTrue(opening[1]["executable"])
        self.assertFalse(opening[3]["executable"])

        self.state.player_regime["militia"] = 10000
        strategies.start_strategy(self.state, 4)
        strategies.settle_strategies(self.state)
        running = {node["id"]: node for node in strategies.strategy_genealogy(self.state)[0]}
        self.assertEqual(running[4]["status"], "in_progress")
        self.assertFalse(running[1]["executable"])

        strategies.cancel_strategy(self.state, 4)
        self.assertEqual(self.state.strategies[4]["status"], "available")
        self.assertEqual(self.state.strategies[4]["progress_months"], 0)
        strategies.start_strategy(self.state, 4)
        self.assertEqual(self.state.strategies[4]["progress_months"], 0)

        self.state.player_regime["militia"] = 9000
        paused = {node["id"]: node for node in strategies.strategy_genealogy(self.state)[0]}
        self.assertEqual(paused[4]["status"], "paused")
        strategies.cancel_strategy(self.state, 4)
        unavailable = {node["id"]: node for node in strategies.strategy_genealogy(self.state)[0]}
        self.assertFalse(unavailable[4]["executable"])

        self.state.strategies[1]["status"] = "completed"
        completed = {node["id"]: node for node in strategies.strategy_genealogy(self.state)[0]}
        self.assertEqual(completed[1]["status"], "completed")


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def _complete(self, strategy_id: int):
        self.state.strategies[strategy_id]["status"] = "completed"
        self.state.strategies[strategy_id]["progress_months"] = 1

    def test_return_of_emperor_requires_control_and_changes_era(self):
        self._complete(1)
        self.state.year, self.state.month = 405, 1
        available, reason = decisions.decision_available(self.state, 1)
        self.assertFalse(available)
        self.assertIn("控制荆州", reason)
        jingzhou = next(region for region in self.state.regions.values() if region["name"] == "荆州")
        jingzhou["controller"] = 1
        before = self.state.player_regime["stability"]
        result = decisions.execute_decision(self.state, 1)
        emperor = person_id_by_name(self.state, "司马德宗")
        self.assertEqual(self.state.player_regime["internal"]["emperor"], emperor)
        self.assertEqual(self.state.city_name(self.state.persons[emperor]["location_id"]), "建康")
        self.assertEqual(self.state.persons[emperor]["level"], 10)
        self.assertEqual(self.state.player_regime["stability"], before + 10)
        self.assertEqual(calendar_text(self.state), "公元405年　义熙元年　正月")
        self.assertIn("刘裕", result.text)
        with self.assertRaisesRegex(RuleError, "已经完成"):
            decisions.execute_decision(self.state, 1)

    def test_organize_beifu_all_three_choices(self):
        cases = {
            "刘毅": {"main": "刘毅", "naval": "何无忌", "opinions": {"刘毅": 20}},
            "刘道规": {"main": "刘道规", "naval": "何无忌", "opinions": {"刘毅": -30}},
            "何无忌": {"main": "何无忌", "naval": "刘道规", "opinions": {"刘毅": -50, "刘道规": -5, "何无忌": 20}},
        }
        for choice, expected in cases.items():
            with self.subTest(choice=choice):
                state = load_v11_state()
                state.strategies[2]["status"] = "completed"
                before_armies = set(state.armies)
                before_treasury = state.player_regime["treasury"]
                before_opinions = {
                    name: state.persons[person_id_by_name(state, name)]["opinion_of_player"]
                    for name in ("刘毅", "刘道规", "何无忌")
                }
                before_power = state.persons[person_id_by_name(state, "刘毅")]["attributes"]["base_power"]
                result = decisions.execute_decision(state, 2, choice)
                created = [army for army_id, army in state.armies.items() if army_id not in before_armies]
                self.assertEqual(len(created), 3)
                by_name = {state.person_name(army.commander): army for army in created}
                self.assertEqual(by_name[expected["main"]].soldiers, 5000)
                self.assertEqual(by_name[expected["naval"]].army_type, 1)
                self.assertEqual(by_name[expected["naval"]].soldiers, 2000)
                self.assertTrue(all(state.city_name(army.location_id) == "建康" for army in created))
                self.assertEqual(state.player_regime["treasury"], before_treasury - 200)
                for name, delta in expected["opinions"].items():
                    after = state.persons[person_id_by_name(state, name)]["opinion_of_player"]
                    self.assertEqual(after, max(-100, min(100, before_opinions[name] + delta)))
                if choice == "刘毅":
                    after_power = state.persons[person_id_by_name(state, "刘毅")]["attributes"]["base_power"]
                    self.assertEqual(after_power, min(100, before_power + 20))
                self.assertIn(choice, result.text)
                self.assertNotIn(decisions.BEIFU_INTRO_TEXT, result.text)
                self.assertEqual(decisions.DECISION_TEMPLATES[2]["text"], decisions.BEIFU_INTRO_TEXT)

    def test_decision_still_creates_formation_when_assigned_commander_is_dead(self):
        self._complete(2)
        liu_yi = person_id_by_name(self.state, "刘毅")
        self.state.persons[liu_yi]["status"] = 4
        before_armies = set(self.state.armies)

        decisions.execute_decision(self.state, 2, "刘毅")

        created = [army for army_id, army in self.state.armies.items() if army_id not in before_armies]
        main_formation = next(army for army in created if army.soldiers == 5000)
        self.assertIsNone(main_formation.commander)
        self.assertEqual(main_formation.active_battalions, 5)

    def test_decision_is_not_intercepted_by_command_rejection(self):
        self._complete(2)
        self.state.laws["power"] = 1
        decisions.execute_decision(self.state, 2, "刘毅")
        self.assertIn(2, decisions.completed_decisions(self.state))


class FollowupModifierAndEventTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_modifier_three_only_applies_when_jin_attacks_huan_chu(self):
        self.state.strategies[2]["status"] = "completed"
        jin_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        huan_army = next(army for army in self.state.armies.values() if army.regime_id == 3)
        attacking = BattleContext("attacker", huan_army.location_id, huan_army.id)
        active = active_military_modifiers(self.state, jin_army, attacking)
        self.assertIn(3, [item["id"] for item in active])
        self.assertAlmostEqual(modifier_effect_total(active, "attack"), 0.20)
        defending = BattleContext("defender", jin_army.location_id, huan_army.id)
        self.assertNotIn(3, [item["id"] for item in active_military_modifiers(self.state, jin_army, defending)])

    def test_partition_jingchu_event_assigns_governor_and_half_the_land(self):
        self.state.regimes[3]["regions"] = []
        owned = list(self.state.player_regime["regions"])
        self.state.player_regime["regions"] = list(dict.fromkeys(owned + sorted(FOUR_JINGCHU_REGIONS)))
        tracked = {
            region["name"]: list(region["land_ownership"])
            for region in self.state.regions.values()
            if region["name"] in FOUR_JINGCHU_REGIONS
        }
        self.assertEqual(queue_start_of_turn_events(self.state), [3])
        jingzhou = next(region for region in self.state.regions.values() if region["name"] == "荆州")
        self.assertEqual(self.state.person_name(jingzhou["governor"]), "刘毅")
        high_family_ids = {
            int(family["id"]) for family in self.state.families.values()
            if int(family.get("family_type") or -1) == 1
        }
        for region in self.state.regions.values():
            if region["name"] not in FOUR_JINGCHU_REGIONS:
                continue
            half = len(region["land_ownership"]) // 2
            distributed = region["land_ownership"][:half]
            self.assertTrue(all(owner in high_family_ids for owner in distributed))
            self.assertEqual(region["land_ownership"][half:], tracked[region["name"]][half:])
            counts = Counter(distributed)
            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)


if __name__ == "__main__":
    unittest.main()
