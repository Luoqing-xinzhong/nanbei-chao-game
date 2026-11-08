from __future__ import annotations

import unittest

from app.rules import laws
from app.rules.common import RuleError, person_power, spend_authority
from app.rules.economy import calculate_region_income
from app.rules.political_events import check_rebellions, run_party_phase, settle_coups
from app.v11 import load_v11_state


class PersonPowerTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_levels_and_personal_power_are_normalized(self):
        emperors = {
            regime["internal"].get("emperor")
            for regime in self.state.regimes.values()
            if regime.get("internal", {}).get("emperor")
        }
        for person in self.state.persons.values():
            if person["id"] in emperors:
                self.assertEqual(person["level"], 10)
            elif not person.get("is_player"):
                self.assertLessEqual(person["level"], 5)
            self.assertIsInstance(person["attributes"]["base_power"], int)
            self.assertGreaterEqual(person["attributes"]["base_power"], 0)
            self.assertLessEqual(person["attributes"]["base_power"], 100)
        self.assertTrue(all(self.state.persons[pid]["level"] == 10 for pid in emperors))
        self.assertEqual(self.state.player["level"], 6)

    def test_power_formula_uses_new_status_coefficients(self):
        person = {
            "id": 9999,
            "country_id": 9999,
            "status": 1,
            "level": 4,
            "attributes": {"base_power": 50},
        }
        self.assertEqual(person_power(self.state, person), 200)
        person["status"] = 2
        self.assertEqual(person_power(self.state, person), 140)
        person["status"] = 3
        self.assertEqual(person_power(self.state, person), 40)


class LegislationTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_top_five_vote_progress_pause_and_enactment(self):
        before_supporter = self.state.persons[8]["opinion_of_player"]  # 王谧支持检籍土断
        before_opponent = self.state.persons[69]["opinion_of_player"]  # 谢混捍卫庄园农奴制
        result = laws.propose_legislation(self.state, "economy", 2)
        self.assertIn("投票通过", result)
        self.assertEqual(len(self.state.legislation["votes"]), 5)

        self.state.authority = 350
        for expected in (25, 50, 75):
            laws.settle_legislation(self.state)
            self.assertEqual(self.state.legislation["progress"], expected)
        laws.settle_legislation(self.state)
        self.assertEqual(self.state.legislation["progress"], 75)
        self.assertEqual(self.state.authority, 50)

        self.state.authority = 150
        laws.settle_legislation(self.state)
        laws.enact_ready_legislation(self.state)
        self.assertEqual(self.state.laws["economy"], 2)
        self.assertFalse(self.state.legislation)
        self.assertEqual(self.state.persons[8]["opinion_of_player"], before_supporter + 10)
        self.assertEqual(self.state.persons[69]["opinion_of_player"], before_opponent - 30)

    def test_cancel_legislation_clears_vote_and_progress_with_stability_cost(self):
        result = laws.propose_legislation(self.state, "economy", 2)
        self.assertIn("投票通过", result)
        laws.settle_legislation(self.state)
        laws.settle_legislation(self.state)
        self.assertEqual(self.state.legislation["progress"], 50)
        old_stability = self.state.player_regime["stability"]

        message = laws.cancel_legislation(self.state)
        self.assertIn("投票结果清零", message)
        self.assertFalse(self.state.legislation)
        self.assertEqual(self.state.player_regime["stability"], max(0, old_stability - 5))

        second_vote = laws.propose_legislation(self.state, "economy", 2)
        self.assertIn("投票通过", second_vote)
        self.assertEqual(self.state.legislation["progress"], 0)
        self.assertEqual(len(self.state.legislation["votes"]), 5)

    def test_ideology_supports_approaching_ideal_and_rejects_overshoot(self):
        person = {"ideology": 3}  # 寒门革新派，经济理想为3级自耕农
        self.state.laws["economy"] = 1
        self.assertGreater(laws.legislative_stance(self.state, person, "economy", 2), 0)
        self.assertEqual(laws.legislative_stance(self.state, person, "economy", 4), -2)
        self.assertEqual(laws.legislative_stance(self.state, person, "economy", 5), -2)

    def test_tax_law_reuses_economy_ideology(self):
        person = {"ideology": 3}
        self.state.laws["tax"] = 1
        self.assertEqual(
            laws.legislative_stance(self.state, person, "tax", 2),
            laws.legislative_stance(self.state, person, "economy", 2),
        )

    def test_all_ideologies_follow_directional_law_preferences(self):
        checked = 0
        for ideology, categories in laws.IDEOLOGY_POSITIONS.items():
            person = {"ideology": ideology}
            for category, (preferred, strength, _opposed, _oppose_strength) in categories.items():
                if preferred is None:
                    continue
                checked += 1
                if preferred >= 3:
                    self.state.laws[category] = 1
                    closer = 2
                    self.assertEqual(laws.legislative_stance(self.state, person, category, closer), strength)
                    if preferred < 5:
                        self.assertEqual(laws.legislative_stance(self.state, person, category, preferred + 1), -2)
                else:
                    self.state.laws[category] = 5
                    closer = 4
                    self.assertEqual(laws.legislative_stance(self.state, person, category, closer), strength)
                    if preferred > 1:
                        self.assertEqual(laws.legislative_stance(self.state, person, category, preferred - 1), -2)
        self.assertGreater(checked, 20)

    def test_law_effects_change_tax_and_authority_cost(self):
        region = next(region for region in self.state.regions.values() if any(int(x) >= 3 for x in region["land_ownership"]))
        self.state.laws["economy"] = 1
        low_tax = calculate_region_income(region, self.state, self.state.player_regime_id)
        self.state.laws["economy"] = 3
        high_tax = calculate_region_income(region, self.state, self.state.player_regime_id)
        self.assertGreater(high_tax, low_tax)

        self.state.laws["values"] = 3
        self.state.laws["power"] = 4
        self.state.authority = 1000
        spend_authority(self.state, 100)
        self.assertEqual(self.state.authority, 940)  # -20% and -20%, additively

    def test_absolute_monarchy_can_force_a_rejected_vote(self):
        self.state.laws["power"] = 4
        self.state.authority = 5000
        old_stability = self.state.player_regime["stability"]
        result = laws.force_legislation(self.state, "north", 5)
        self.assertIn("强行通过", result)
        self.assertTrue(self.state.legislation.get("forced"))
        self.assertEqual(self.state.player_regime["stability"], old_stability - 30)

    def test_law_decree_buttons_unlock_only_with_prerequisite_laws(self):
        self.assertEqual(laws.unlocked_political_commands(self.state), ("动员",))
        self.state.laws["economy"] = 2
        self.assertEqual(laws.unlocked_political_commands(self.state), ("检籍", "土断", "动员"))
        self.state.laws["economy"] = 4
        self.state.laws["values"] = 2
        self.assertEqual(laws.unlocked_political_commands(self.state), ("屯田", "教化", "动员"))

    def test_mobilization_matches_education_but_adds_war_support(self):
        self.state.laws["power"] = 2
        official = next(
            int(person_id) for person_id in self.state.player_regime["internal"].values()
            if isinstance(person_id, int) and person_id in self.state.persons
        )
        before_support = self.state.player_regime["war_support"]
        before_stability = self.state.player_regime["stability"]
        result = laws.mobilization(self.state, official)
        self.assertIn("战争支持度提高", result)
        self.assertGreater(self.state.player_regime["war_support"], before_support)
        self.assertEqual(self.state.player_regime["stability"], before_stability)
        with self.assertRaisesRegex(RuleError, "冷却|本回合"):
            laws.mobilization(self.state, official)
        self.state.laws["north"] = 2
        self.state.turn_number += 6
        with self.assertRaisesRegex(RuleError, "第3、4、5级"):
            laws.mobilization(self.state, official)

    def test_immediate_land_and_monthly_stability_effects(self):
        self.state.laws["economy"] = 5
        laws.apply_immediate_effect(self.state, "economy", 5)
        family_ids = set(self.state.families)
        self.assertFalse(any(owner in family_ids for region in laws.owned_player_regions(self.state) for owner in region["land_ownership"]))
        self.state.laws["values"] = 4
        self.state.laws["power"] = 2
        old_stability = self.state.player_regime["stability"]
        laws.apply_monthly_effects(self.state)
        self.assertEqual(self.state.player_regime["stability"], min(100, old_stability + 3))

    def test_tax_law_changes_controlled_region_stability(self):
        region = laws.owned_player_regions(self.state)[0]
        region["local_stability"] = 50
        self.state.laws["tax"] = 1
        laws.apply_monthly_effects(self.state)
        self.assertEqual(region["local_stability"], 60)
        self.state.laws["tax"] = 5
        laws.apply_monthly_effects(self.state)
        self.assertEqual(region["local_stability"], 50)

    def test_parties_and_governors_use_law_driven_political_events(self):
        class AlwaysTrigger:
            @staticmethod
            def random():
                return 0.0

        run_party_phase(self.state, AlwaysTrigger())
        self.assertTrue(any(party.get("coup") for party in self.state.parties.values()))
        settle_coups(self.state)
        self.assertTrue(any(float(party.get("coup", {}).get("progress", 0)) > 0 for party in self.state.parties.values()))

        region = next(region for region in laws.owned_player_regions(self.state) if region["id"] != 1)
        governor = self.state.persons[33]
        region["governor"] = governor["id"]
        old_regime_count = len(self.state.regimes)
        check_rebellions(self.state, AlwaysTrigger())
        self.assertEqual(len(self.state.regimes), old_regime_count + 1)
        rebel_id = max(self.state.regimes)
        self.assertEqual(sum(1 for army in self.state.armies.values() if army.regime_id == rebel_id), 2)


if __name__ == "__main__":
    unittest.main()
