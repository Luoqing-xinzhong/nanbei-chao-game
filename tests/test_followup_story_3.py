from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from app.models import Army, GameState
from app.content.v1_1 import decisions, strategies
from app.rules.common import person_power
from app.rules.military_modifiers import BattleContext, active_military_modifiers, modifier_effect_total
from app.rules.national_modifiers import active_national_modifiers, apply_national_modifier_settlement
from app.rules.political_events import check_coup_defeat, settle_coups
from app.content.v1_1.events import person_id_by_name, queue_start_of_turn_events
from app.save_service import load_game, save_game
from app.v11 import load_v11_state


class FixedRandom:
    def __init__(self, value: float):
        self.value = value

    def random(self) -> float:
        return self.value


class FollowupStoryThreeTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def _complete(self, state, *strategy_ids: int) -> None:
        for strategy_id in strategy_ids:
            state.strategies[strategy_id]["status"] = "completed"

    def test_new_strategies_are_in_genealogy_and_support_any_prerequisite(self):
        _nodes, edges = strategies.strategy_genealogy(self.state)
        self.assertIn((8, 9), edges)
        self.assertIn((3, 10), edges)
        self.assertIn((3, 11), edges)
        self.assertIn((10, 12), edges)
        self.assertIn((11, 12), edges)
        self.assertEqual(strategies.strategy_mutual_exclusions(self.state), [(10, 11)])
        self._complete(self.state, 3, 10)
        self.state.year = 412
        self.assertTrue(strategies.strategy_available(self.state, 12)[0])
        self.assertTrue(strategies.strategy_available(self.state, 13)[0])

    def test_promote_talents_requires_legal_xu_qing_and_adds_modifiers(self):
        self._complete(self.state, 8)
        self.assertFalse(strategies.strategy_available(self.state, 9)[0])
        self.state.player_regime["regions"].extend(["徐州", "青州"])
        before = int(self.state.player["attributes"]["base_power"])
        strategies.start_strategy(self.state, 9)
        for _ in range(3):
            strategies.settle_strategies(self.state)
        self.assertEqual(self.state.player["attributes"]["base_power"], before + 15)

        commander = person_id_by_name(self.state, "王镇恶")
        north_yong_city = next(
            int(city["id"])
            for city in self.state.cities.values()
            if self.state.regions[int(city["region_id"])]["name"] == "北雍州"
        )
        army = Army(950, 1, 0, [{"type": 1, "count": 1000}], commander=commander, location_id=1)
        opponent = next(item for item in self.state.armies.values() if item.regime_id != 1)
        active = active_military_modifiers(self.state, army, BattleContext("attacker", north_yong_city, opponent.id))
        self.assertEqual([item["id"] for item in active if item["id"] >= 8], [8, 9])
        self.assertAlmostEqual(modifier_effect_total(active, "attack"), 0.50)

    def test_strategy_ten_and_eleven_are_mutually_exclusive(self):
        self._complete(self.state, 3)
        self.state.year = 412
        self.state.player["attributes"]["base_power"] = 200
        self.assertGreaterEqual(person_power(self.state, self.state.player), 1000)
        self.assertTrue(strategies.strategy_available(self.state, 10)[0])
        self._complete(self.state, 10)
        self.assertFalse(strategies.strategy_available(self.state, 11)[0])

    def test_honor_and_grand_general_decisions(self):
        self._complete(self.state, 9)
        self.state.player_regime["stability"] = 50
        old_level = int(self.state.player["level"])
        old_power = int(self.state.player["attributes"]["base_power"])
        decisions.execute_decision(self.state, 7)
        self.assertEqual(self.state.player["level"], old_level + 1)
        self.assertEqual(self.state.player["attributes"]["base_power"], old_power + 5)

        self.state.regimes[5]["regions"] = []
        self.state.player_regime["regions"].append("广州")
        self.assertTrue(decisions.decision_visible(self.state, 8))
        decisions.execute_decision(self.state, 8)
        self.assertEqual(self.state.player_regime["internal"]["grand_general"], self.state.player["id"])

    def test_humble_and_gentry_routes_apply_law_and_confidants(self):
        humble = load_v11_state()
        self._complete(humble, 10)
        decisions.execute_decision(humble, 9)
        self.assertEqual(humble.laws["power"], 2)
        self.assertIn(person_id_by_name(humble, "刘穆之"), humble.confidants)
        self.assertEqual(humble.persons[person_id_by_name(humble, "刘穆之")]["opinion_of_player"], 100)

        gentry = load_v11_state()
        self._complete(gentry, 11)
        decisions.execute_decision(gentry, 10)
        self.assertEqual(gentry.laws["power"], 1)
        self.assertIn(person_id_by_name(gentry, "王弘"), gentry.confidants)
        self.assertEqual(gentry.persons[person_id_by_name(gentry, "王弘")]["opinion_of_player"], 100)

    def test_civil_service_decision_appoints_everyone_and_activates_modifier(self):
        self._complete(self.state, 12)
        decisions.execute_decision(self.state, 11)
        internal = self.state.player_regime["internal"]
        expected = {
            "shangshu_ling": "刘穆之",
            "left_shangshu": "王弘",
            "right_shangshu": "徐羡之",
            "zhongshu_shilang": "郑鲜之",
            "sanqi_changshi": "褚叔度",
        }
        for office, name in expected.items():
            self.assertEqual(self.state.person_name(internal[office]), name)
        self.assertIn(person_id_by_name(self.state, "傅亮"), self.state.confidants)
        self.assertEqual(self.state.person_name(self.state.parties[1]["leader"]), "刘穆之")
        self.assertEqual([item["id"] for item in active_national_modifiers(self.state)], [1, 3])

        self.state.parties[1]["coup"] = {"leader": internal["shangshu_ling"], "participants": [internal["shangshu_ling"]], "progress": 50}
        settle_coups(self.state)
        self.assertNotIn("coup", self.state.parties[1])
        stability = self.state.player_regime["stability"]
        apply_national_modifier_settlement(self.state)
        self.assertEqual(self.state.player_regime["stability"], stability + 1)

    def test_execute_liu_yi_success_and_failure(self):
        success = load_v11_state()
        self._complete(success, 13)
        old_power = success.player["attributes"]["base_power"]
        decisions.execute_decision(success, 12, rng=FixedRandom(0.1))
        self.assertEqual(success.persons[person_id_by_name(success, "刘毅")]["status"], 4)
        self.assertEqual(success.player["attributes"]["base_power"], old_power + 10)

        failure = load_v11_state()
        self._complete(failure, 13)
        decisions.execute_decision(failure, 12, rng=FixedRandom(0.9))
        rebel_id = int(failure.flags["liu_yi_regime_id"])
        self.assertTrue(failure.events[12]["triggered"])
        self.assertEqual(failure.regimes[rebel_id]["regions"], ["荆州"])
        armies = [army for army in failure.armies.values() if army.regime_id == rebel_id]
        self.assertEqual(sorted((army.army_type, army.soldiers) for army in armies), [(0, 5000), (1, 5000)])
        self.assertEqual({failure.person_name(army.commander) for army in armies}, {"刘毅", "谢混"})

    def test_timed_rebellion_can_be_suppressed_or_capture_jiankang(self):
        self.state.year, self.state.month = 412, 9
        triggered = queue_start_of_turn_events(self.state)
        self.assertIn(12, triggered)
        rebel_id = int(self.state.flags["liu_yi_regime_id"])
        jiangling_region = self.state.regions[int(next(city for city in self.state.cities.values() if city["name"] == "江陵")["region_id"])]
        jiangling_region["controller"] = 1
        self.assertIn(13, queue_start_of_turn_events(self.state))
        for name in ("刘毅", "刘籓", "谢晦"):
            self.assertEqual(self.state.persons[person_id_by_name(self.state, name)]["status"], 4)

        defeat = load_v11_state()
        defeat.year, defeat.month = 412, 9
        queue_start_of_turn_events(defeat)
        rebel_id = int(defeat.flags["liu_yi_regime_id"])
        jiankang = next(city for city in defeat.cities.values() if city["name"] == "建康")
        defeat.regions[int(jiankang["region_id"])]["controller"] = rebel_id
        self.assertIn(14, queue_start_of_turn_events(defeat))
        self.assertTrue(defeat.flags["game_over"])

    def test_completed_coups_trigger_specific_events_instead_of_direct_defeat(self):
        cases = (("刘毅", 8), ("王谧", 9), ("司马休之", 10))
        for name, event_id in cases:
            with self.subTest(name=name):
                state = load_v11_state()
                leader = person_id_by_name(state, name)
                state.parties[1]["coup"] = {"leader": leader, "participants": [leader], "progress": 100}
                check_coup_defeat(state)
                self.assertFalse(state.flags.get("game_over", False))
                self.assertIn(event_id, queue_start_of_turn_events(state))
                self.assertTrue(state.flags["game_over"])

    def test_over_hundred_power_survives_save_only_for_level_six(self):
        self.state.player["attributes"]["base_power"] = 120
        low = self.state.persons[person_id_by_name(self.state, "刘毅")]
        low["attributes"]["base_power"] = 120
        restored = GameState.from_dict(self.state.to_dict())
        self.assertEqual(restored.player["attributes"]["base_power"], 120)
        self.assertEqual(restored.persons[int(low["id"])]["attributes"]["base_power"], 100)

    def test_old_v11_save_is_migrated_with_xu_xianzhi(self):
        self.state.persons.pop(94)
        self.state.families.pop(28)
        with tempfile.TemporaryDirectory() as folder:
            path = save_game(self.state, "旧存档", Path(folder))
            restored = load_game(path)
        self.assertEqual(restored.person_name(94), "徐羡之")
        self.assertEqual(restored.families[28]["name"], "彭城徐氏")


if __name__ == "__main__":
    unittest.main()
