from __future__ import annotations

import unittest

from app.models import Army
from app.rules.ai_modifiers import ai_income_multiplier, ai_militia_multiplier, set_difficulty
from app.rules.ai_strategy import (
    defense_assignments,
    ensure_later_qin_408_reinforcements,
    expansion_assessment,
    expand_military,
    grant_ai_authority,
    issue_best_economic_policy,
    issue_development_policy,
    plan_wei_invasion,
    run_administrative_actions,
    strategic_defense_targets,
)
from app.rules.economy import regime_income, regime_militia_growth
from app.rules.economy import projected_expenses
from app.rules.military_modifiers import active_military_modifiers, modifier_effect_total
from app.v11 import load_v11_state


class AIStrategyTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_ai_income_uses_current_bonus_and_player_is_unchanged(self):
        self.assertEqual(ai_income_multiplier(self.state, 1), 1.0)
        self.assertEqual(ai_income_multiplier(self.state, 2), 2.0)
        income = regime_income(self.state, 2)
        self.state.regimes[2]["is_main"] = True
        base = regime_income(self.state, 2)
        self.assertEqual(income, base * 2)

    def test_ai_development_policy_consumes_its_own_authority(self):
        regime = self.state.regimes[4]
        regime["authority"] = 100
        regime["treasury"] = 1000
        candidate = min(
            (
                region for region in self.state.regions.values()
                if region["name"] in regime["regions"] and int(region.get("controller", 0)) == 4
            ),
            key=lambda region: (int(region.get("development", 0)), int(region["id"])),
        )
        before = int(candidate["development"])
        self.assertEqual(issue_development_policy(self.state, 4), int(candidate["id"]))
        self.assertEqual(candidate["development"], min(100, before + 3))
        self.assertEqual(regime["authority"], 0)
        self.assertEqual(regime["treasury"], 985)

    def test_ai_receives_two_hundred_authority_each_turn(self):
        before = int(self.state.regimes[2]["authority"])
        grant_ai_authority(self.state)
        self.assertEqual(self.state.regimes[2]["authority"], before + 200)

    def test_ai_authority_gain_is_capped_at_two_thousand(self):
        self.state.regimes[2]["authority"] = 1950
        grant_ai_authority(self.state)
        self.assertEqual(self.state.regimes[2]["authority"], 2000)
        grant_ai_authority(self.state)
        self.assertEqual(self.state.regimes[2]["authority"], 2000)

    def test_ai_militia_growth_is_doubled(self):
        self.assertEqual(ai_militia_multiplier(self.state, 1), 1.0)
        self.assertEqual(ai_militia_multiplier(self.state, 2), 2.0)
        boosted = regime_militia_growth(self.state, 2)
        self.state.regimes[2]["is_main"] = True
        base = regime_militia_growth(self.state, 2)
        self.assertEqual(boosted, base * 2)

    def test_difficulty_adds_ai_only_combat_modifier(self):
        ai_army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        player_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        self.assertNotIn(15, [item["id"] for item in active_military_modifiers(self.state, ai_army)])
        set_difficulty(self.state, "normal")
        normal = next(item for item in active_military_modifiers(self.state, ai_army) if item["id"] == 15)
        self.assertEqual(normal["effects"], {"attack": 0.20, "defense": 0.20})
        self.assertNotIn(15, [item["id"] for item in active_military_modifiers(self.state, player_army)])
        set_difficulty(self.state, "hard")
        hard = next(item for item in active_military_modifiers(self.state, ai_army) if item["id"] == 15)
        self.assertEqual(hard["effects"], {"attack": 0.40, "defense": 0.40})

    def test_ai_can_issue_multiple_economic_orders_with_surplus_authority(self):
        class DevelopFirst:
            @staticmethod
            def random() -> float:
                return 0.0

        regime = self.state.regimes[4]
        regime["authority"] = 200
        regime["treasury"] = 10000
        regions = [
            region for region in self.state.regions.values()
            if region["name"] in regime["regions"] and int(region.get("controller", 0)) == 4
        ]
        before = sum(int(region["development"]) for region in regions)
        actions = run_administrative_actions(self.state, 4, DevelopFirst())
        self.assertTrue(all(action.split(":", 1)[0] in {"relief", "develop", "reclaim"} for action in actions))
        self.assertGreaterEqual(len(actions), 2)
        self.assertGreaterEqual(sum(int(region["development"]) for region in regions), before)
        self.assertEqual(regime["authority"], 0)

    def test_ai_relief_takes_priority_when_stability_is_low(self):
        regime = self.state.regimes[4]
        regime["authority"] = 100
        regime["treasury"] = 1000
        regime["stability"] = 30
        regions = [
            region for region in self.state.regions.values()
            if region["name"] in regime["regions"] and int(region.get("controller", 0)) == 4
        ]
        for region in regions:
            region["prosperity"] = 10
        before_stability = regime["stability"]
        action = issue_best_economic_policy(self.state, 4)
        self.assertTrue(action.startswith("relief:"))
        self.assertEqual(regime["stability"], before_stability + 3)

    def test_ai_compares_waterworks_and_reclamation_income_gain(self):
        regime = self.state.regimes[4]
        regime["authority"] = 100
        regime["treasury"] = 1000
        regime["militia"] = 0
        regime["stability"] = 70
        for region in self.state.regions.values():
            if region["name"] in regime["regions"] and int(region.get("controller", 0)) == 4:
                region["prosperity"] = 10
        self.assertTrue(issue_best_economic_policy(self.state, 4).startswith("develop:"))

    def test_ai_uses_expansion_half_of_weighted_choice(self):
        class ExpandFirst:
            @staticmethod
            def random() -> float:
                return 0.99

        regime = self.state.regimes[4]
        regime["authority"] = 100
        regime["treasury"] = 10000
        regime["reserve_army"] = 9000
        actions = run_administrative_actions(self.state, 4, ExpandFirst())
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0].startswith("expand:"))
        self.assertEqual(regime["authority"], 0)

    def test_ai_expands_with_a_large_affordable_formation(self):
        regime = self.state.regimes[4]
        regime["treasury"] = 10000
        regime["reserve_army"] = 9000
        before = set(self.state.armies)
        army = expand_military(self.state, 4)
        self.assertIsNotNone(army)
        self.assertNotIn(army.id, before)
        self.assertEqual(army.soldiers, 9000)
        self.assertEqual(army.location_id, int(regime["capital"]))
        self.assertEqual(regime["authority"], 100)

    def test_later_qin_can_expand_beyond_the_old_fifty_four_battalion_limit(self):
        self.state.year = 408
        ensure_later_qin_408_reinforcements(self.state)
        regime = self.state.regimes[9]
        regime["authority"] = 100
        regime["treasury"] = 100000
        regime["reserve_army"] = 9000
        before = sum(army.active_battalions for army in self.state.armies.values() if army.regime_id == 9)
        self.assertEqual(before, 51)
        army = expand_military(self.state, 9)
        self.assertIsNotNone(army)
        after = sum(item.active_battalions for item in self.state.armies.values() if item.regime_id == 9)
        self.assertEqual(after, 60)
        self.assertGreater(after, 54)

    def test_expansion_assessment_uses_real_enemy_soldiers(self):
        regime_id = 4
        enemy_id = self.state.player_regime_id
        self.state.wars.append(self.state.relation_pair(regime_id, enemy_id))
        enemy_army_id = max(self.state.armies) + 1
        self.state.armies[enemy_army_id] = Army(
            enemy_army_id,
            enemy_id,
            0,
            [{"type": 1, "count": 1000} for _ in range(9)],
            location_id=1,
        )
        assessment = expansion_assessment(self.state, regime_id)
        enemy_soldiers = sum(
            army.soldiers for army in self.state.armies.values()
            if army.regime_id == enemy_id
        )
        self.assertEqual(assessment["threat_soldiers"], enemy_soldiers)
        self.assertGreater(assessment["threat_gap_battalions"], 0)

    def test_wei_declares_war_on_a_weaker_adjacent_small_regime(self):
        # 用一条明确的边境道路隔离测试，不依赖地图其余邻接关系。
        wei_capital = int(self.state.regimes[2]["capital"])
        target_capital = int(self.state.regimes[7]["capital"])
        self.state.roads = [{"id": 9999, "from": wei_capital, "to": target_capital, "type": 1}]
        self.state.regimes[2]["reserve_army"] = 100000
        target = plan_wei_invasion(self.state)
        self.assertEqual(target, 7)
        self.assertTrue(self.state.at_war(2, 7))
        self.assertEqual(self.state.flags["ai_invasion_target:2"], 7)

    def test_defense_priority_assigns_first_army_to_capital(self):
        targets = strategic_defense_targets(self.state, 2)
        self.assertEqual(targets[0], int(self.state.regimes[2]["capital"]))
        assignments = defense_assignments(self.state, 2)
        self.assertIn(int(self.state.regimes[2]["capital"]), assignments.values())

    def test_wei_has_permanent_twenty_percent_military_bonus(self):
        army = next(item for item in self.state.armies.values() if item.regime_id == 2)
        modifiers = active_military_modifiers(self.state, army)
        self.assertIn(12, [item["id"] for item in modifiers])
        self.assertAlmostEqual(modifier_effect_total(modifiers, "attack"), 0.20)
        self.assertAlmostEqual(modifier_effect_total(modifiers, "defense"), 0.20)

    def test_later_qin_408_creates_ten_armies_and_unlocks_bonus_once(self):
        self.state.year = 408
        before = set(self.state.armies)
        created = ensure_later_qin_408_reinforcements(self.state)
        self.assertEqual(len(created), 10)
        armies = [self.state.armies[army_id] for army_id in created]
        self.assertTrue(all(army.regime_id == 9 and army.soldiers == 5000 for army in armies))
        modifiers = active_military_modifiers(self.state, armies[0])
        self.assertIn(13, [item["id"] for item in modifiers])
        self.assertIn(14, [item["id"] for item in modifiers])
        self.assertAlmostEqual(modifier_effect_total(modifiers, "attack"), 0.15)
        # 十支剧情军原需500军饷，折扣后只需100；另含后秦开局军队的正常军饷。
        normal_pay = sum(
            army.active_battalions * 10
            for army in self.state.armies.values()
            if army.regime_id == 9 and army.id not in created
        )
        self.assertEqual(projected_expenses(self.state, 9)[1], normal_pay + 100)
        self.assertEqual(ensure_later_qin_408_reinforcements(self.state), [])
        self.assertEqual(set(self.state.armies) - before, set(created))


if __name__ == "__main__":
    unittest.main()
