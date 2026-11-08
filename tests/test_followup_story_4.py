from __future__ import annotations

import random
import unittest

from app.constants import REGIME_COLORS
from app.models import Army
from app.content.v1_1 import decisions, strategies
from app.rules import diplomacy
from app.rules.common import RuleError, person_power
from app.content.v1_1.events_4 import apply_event_choice, resolve_special_coup_if_player_returns
from app.content.v1_1.events_4 import settle_natural_deaths
from app.rules.military_modifiers import BattleContext, active_military_modifiers, modifier_effect_total
from app.rules.national_modifiers import active_national_modifiers
from app.rules.political_events import settle_coups
from app.content.v1_1.events import person_id_by_name, queue_start_of_turn_events
from app.content.v1_1.story_texts import render_dynamic_text
from app.v11 import load_v11_state


class FollowupStoryFourTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def _complete(self, *ids: int) -> None:
        for strategy_id in ids:
            self.state.strategies[strategy_id]["status"] = "completed"

    def _control(self, city_name: str, regime_id: int) -> None:
        city = next(item for item in self.state.cities.values() if item["name"] == city_name)
        self.state.regions[int(city["region_id"])]["controller"] = regime_id

    def test_story_era_placeholder_uses_live_reign_year(self):
        self.state.year = 407
        self.state.flags["era_name"] = "义熙"
        self.state.flags["era_start_year"] = 405
        self.assertEqual(render_dynamic_text(self.state, "{年号+年号计数}夏"), "义熙三年夏")
        self.assertEqual(render_dynamic_text(self.state, "年号 + 年号计数冬"), "义熙三年冬")

    def test_strategy_chain_and_development_land_distribution(self):
        _nodes, edges = strategies.strategy_genealogy(self.state)
        self.assertIn((4, 14), edges)
        self.assertIn((14, 18), edges)
        self.assertIn((20, 22), edges)
        self._complete(4)
        region = next(item for item in self.state.regions.values() if item["name"] == "扬州")
        old_land, old_slots = region["land"], len(region["land_ownership"])
        strategies.start_strategy(self.state, 14)
        for _ in range(3):
            strategies.settle_strategies(self.state)
        added = region["land_ownership"][old_slots:]
        self.assertEqual(region["land"], old_land + 40)
        self.assertEqual(added.count(0), 15)
        self.assertEqual(added.count(2), 10)
        self.assertEqual(sum(self.state.families.get(owner, {}).get("family_type") == 1 for owner in added), 15)

    def test_household_reform_enacts_law_and_modifier(self):
        before = self.state.persons[person_id_by_name(self.state, "刘穆之")]["attributes"]["base_power"]
        self.state.strategies[18]["status"] = "in_progress"
        self.state.strategies[18]["progress_months"] = 2
        for prerequisite in (10, 14, 15, 16):
            self.state.strategies[prerequisite]["status"] = "completed"
        strategies.settle_strategies(self.state)
        self.assertEqual(self.state.laws["economy"], 2)
        self.assertEqual(self.state.persons[person_id_by_name(self.state, "刘穆之")]["attributes"]["base_power"], min(100, before + 10))
        self.assertIn(2, [item["id"] for item in active_national_modifiers(self.state)])

    def test_fortify_and_gentry_beifu_decisions(self):
        self._complete(17, 19)
        old_defense = self.state.cities[1]["defense"]
        decisions.execute_decision(self.state, 14)
        self.assertEqual(self.state.cities[1]["defense"], min(100, old_defense + 30))
        decisions.execute_decision(self.state, 15)
        army = next(item for item in self.state.armies.values() if self.state.person_name(item.commander) == "谢晦")
        self.assertEqual(sorted(unit["type"] for unit in army.units), [1, 1, 1, 3, 3])
        opponent = next(item for item in self.state.armies.values() if item.regime_id != 1)
        context = BattleContext("attacker", opponent.location_id, opponent.id)
        modifiers = active_military_modifiers(self.state, army, context)
        self.assertIn(10, [item["id"] for item in modifiers])
        self.assertGreater(modifier_effect_total(modifiers, "attack"), 0)

    def test_story4_decision_keeps_formation_if_xie_hui_died_early(self):
        self._complete(19)
        xie_hui = person_id_by_name(self.state, "谢晦")
        self.state.persons[xie_hui]["status"] = 4
        before_armies = set(self.state.armies)

        decisions.execute_decision(self.state, 15)

        army = next(item for army_id, item in self.state.armies.items() if army_id not in before_armies)
        self.assertIsNone(army.commander)
        self.assertEqual(sorted(unit["type"] for unit in army.units), [1, 1, 1, 3, 3])

    def test_luoyang_and_changan_events_create_then_end_wei_intervention(self):
        self.state.wars.append(self.state.relation_pair(1, 9))
        self._control("洛阳", 1)
        before_armies = set(self.state.armies)
        triggered = queue_start_of_turn_events(self.state)
        self.assertIn(15, triggered)
        self.assertIn(16, triggered)
        wei_army = next(item for item in self.state.armies.values() if self.state.person_name(item.commander) == "拓跋嗣")
        self.assertEqual(wei_army.soldiers, 5000)
        self.assertTrue(wei_army.pure_cavalry)
        reinforcements = [
            item for army_id, item in self.state.armies.items()
            if army_id not in before_armies and item.regime_id == 2
        ]
        self.assertEqual(len(reinforcements), 4)
        self.assertTrue(all(item.soldiers == 5000 and item.pure_cavalry for item in reinforcements))
        self.assertTrue(self.state.at_war(1, 2))
        self._control("长安", 1)
        self.assertIn(17, queue_start_of_turn_events(self.state))
        self.assertFalse(self.state.at_war(1, 2))

    def test_story4_event_keeps_formation_if_tuoba_si_died_early(self):
        tuoba_si = person_id_by_name(self.state, "拓跋嗣")
        self.state.persons[tuoba_si]["status"] = 4
        self.state.wars.append(self.state.relation_pair(1, 9))
        self._control("洛阳", 1)
        before_armies = set(self.state.armies)

        self.assertIn(15, queue_start_of_turn_events(self.state))

        armies = [
            item for army_id, item in self.state.armies.items()
            if army_id not in before_armies and item.regime_id == 2
        ]
        self.assertEqual(len(armies), 4)
        self.assertTrue(all(army.commander is None for army in armies))
        self.assertTrue(all(army.soldiers == 5000 and army.pure_cavalry for army in armies))

    def test_muzhi_successor_and_special_coup_only_stops_on_return(self):
        muzhi = person_id_by_name(self.state, "刘穆之")
        self.state.persons[muzhi]["status"] = 4
        self.state.player["location_id"] = 77
        self.assertIn(18, queue_start_of_turn_events(self.state))
        apply_event_choice(self.state, 18, "徐羡之")
        self.assertIn(19, queue_start_of_turn_events(self.state))
        party = self.state.parties[1]
        self.assertTrue(party["coup"]["special_jiankang"])
        settle_coups(self.state)
        self.assertEqual(party["coup"]["progress"], 10)
        party["coup"]["leader"] = 0
        settle_coups(self.state)
        self.assertEqual(party["coup"]["progress"], 20)
        self.state.player["location_id"] = 1
        self.assertTrue(resolve_special_coup_if_player_returns(self.state))
        self.assertNotIn("coup", party)

    def test_huxia_targets_changan_and_requires_north_yong_for_peace(self):
        region = next(item for item in self.state.regions.values() if item["name"] == "北雍州")
        region["controller"] = 1
        if "北雍州" not in self.state.player_regime["regions"]:
            self.state.player_regime["regions"].append("北雍州")
        if "北雍州" in self.state.regimes[9]["regions"]:
            self.state.regimes[9]["regions"].remove("北雍州")
        self.assertIn(21, queue_start_of_turn_events(self.state))
        army = next(item for item in self.state.armies.values() if self.state.person_name(item.commander) == "赫连勃勃")
        opponent = Army(999, 1, 0, [{"type": 1, "count": 1000}], location_id=127)
        self.state.armies[999] = opponent
        modifiers = active_military_modifiers(self.state, army, BattleContext("attacker", 127, 999))
        self.assertAlmostEqual(modifier_effect_total(modifiers, "attack"), 0.50)
        self._control("长安", 12)
        self.assertIn(22, queue_start_of_turn_events(self.state))
        with self.assertRaisesRegex(RuleError, "北雍州"):
            diplomacy.make_peace(self.state, 12, {})
        diplomacy.make_peace(self.state, 12, {"player_cedes": [int(region["id"])]})
        self.assertFalse(self.state.at_war(1, 12))

    def test_accession_and_heir_decisions(self):
        completed = self.state.flags.setdefault("completed_decisions", [])
        completed.extend([19, 20, 21, 25, 26])
        self.state.player["level"] = 10
        self.state.player["attributes"]["base_power"] = 300
        self.state.player_regime["stability"] = 80
        self.state.player_regime["treasury"] = 5000
        self.assertGreaterEqual(person_power(self.state, self.state.player), 2500)
        accession = decisions.execute_decision(self.state, 27)
        self.assertEqual(self.state.player_regime["treasury"], 2000)
        self.assertEqual(self.state.player_regime["name"], "宋")
        self.assertEqual(self.state.flags["era_name"], "永初")
        self.assertEqual(self.state.laws["power"], 4)
        self.assertEqual(self.state.player_regime["color"], "blue")
        self.assertEqual(REGIME_COLORS[self.state.player_regime["color"]], REGIME_COLORS["blue"])
        self.assertIn("永初元年", accession.text)
        self.assertNotIn("年号+年号计数", accession.text)
        self.state.authority = 100
        heir = decisions.execute_decision(self.state, 29, "刘义符")
        self.assertEqual(self.state.person_name(self.state.player_regime["internal"]["crown_prince"]), "刘义符")
        self.assertEqual(self.state.authority, 0)
        self.assertNotIn("年号+年号计数", heir.text)

    def test_liu_yu_natural_death_selects_ending_and_ends_game(self):
        self.state.year = int(self.state.player["death_year"])
        self.assertIn(int(self.state.player["id"]), settle_natural_deaths(self.state))
        self.assertIn(25, queue_start_of_turn_events(self.state))
        self.assertTrue(self.state.flags["game_over"])
        self.assertIn("感谢大家游玩1.1版本", self.state.events[25]["text"])
        self.assertGreater(len(self.state.events[25]["text"]), 100)


if __name__ == "__main__":
    unittest.main()
