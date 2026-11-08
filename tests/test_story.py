from __future__ import annotations

import unittest
from unittest.mock import patch

from app.models import GameState
from app.rules.military_modifiers import (
    MILITARY_MODIFIER_RULES,
    MilitaryModifierRule,
    active_military_modifiers,
    modifier_effect_total,
)
from app.content.v1_1.events import add_national_modifier, national_modifier_total, person_id_by_name, queue_start_of_turn_events
from app.content.v1_1.strategies import strategy_record
from app.rules.turn import calendar_text
from app.v11 import load_v11_state


class StoryInitializationTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_scenario_opening_and_first_event_are_applied(self):
        state = self.state
        regime = state.player_regime
        self.assertEqual((state.year, state.month), (404, 10))
        self.assertEqual(calendar_text(state), "公元404年　元兴三年　十月")
        self.assertEqual(
            (regime["stability"], regime["war_support"], regime["treasury"], regime["reserve_army"]),
            (30, 60, 1000, 5000),
        )
        self.assertIsNone(regime["internal"]["emperor"])
        self.assertEqual(state.person_name(regime["internal"]["shangshu_ling"]), "王嘏")
        self.assertTrue(state.at_war(1, 3))
        self.assertEqual(state.city_name(state.persons[person_id_by_name(state, "司马德宗")]["location_id"]), "江陵")
        self.assertTrue(state.events[1]["triggered"])
        self.assertEqual(state.events[1]["effect_handler"], "event_1_effect")
        self.assertEqual(state.persons[person_id_by_name(state, "王嘏")]["opinion_of_player"], 35)
        self.assertEqual(state.persons[person_id_by_name(state, "王谧")]["opinion_of_player"], 85)
        self.assertEqual(state.person_name(regime["internal"]["lu_shangshu"]), "王谧")
        self.assertIn(person_id_by_name(state, "檀凭之"), state.confidants)
        self.assertIn(person_id_by_name(state, "孟昶"), state.confidants)
        self.assertEqual(len(state.confidants), 2)
        self.assertEqual(state.player["level"], 6)
        self.assertEqual(state.flags["pending_story_events"], [1])

    def test_first_event_is_not_repeated(self):
        wang_gao = person_id_by_name(self.state, "王嘏")
        before = self.state.persons[wang_gao]["opinion_of_player"]
        self.assertEqual(queue_start_of_turn_events(self.state), [])
        self.assertEqual(self.state.persons[wang_gao]["opinion_of_player"], before)

    def test_jiangling_battle_creates_modified_armies(self):
        self.state.flags["pending_story_events"] = []
        self.state.month = 12
        before_ids = set(self.state.armies)
        self.assertEqual(queue_start_of_turn_events(self.state), [2])
        created = [army for army_id, army in self.state.armies.items() if army_id not in before_ids]
        self.assertEqual(len(created), 2)
        by_commander = {self.state.person_name(army.commander): army for army in created}
        self.assertEqual(set(by_commander), {"桓谦", "桓振"})
        self.assertTrue(all(army.soldiers == 5000 and self.state.city_name(army.location_id) == "江陵" for army in created))
        qian_modifiers = active_military_modifiers(self.state, by_commander["桓谦"])
        zhen_modifiers = active_military_modifiers(self.state, by_commander["桓振"])
        self.assertAlmostEqual(modifier_effect_total(qian_modifiers, "attack"), 0.20)
        self.assertAlmostEqual(modifier_effect_total(zhen_modifiers, "defense"), 0.30)

        by_commander["桓谦"].commander = person_id_by_name(self.state, "桓振")
        changed = active_military_modifiers(self.state, by_commander["桓谦"])
        self.assertEqual([modifier["id"] for modifier in changed], [2])

    def test_military_modifier_rules_are_checked_in_numeric_order(self):
        checked = []

        def rule(rule_id):
            return MilitaryModifierRule(
                rule_id,
                f"修正{rule_id}",
                "测试",
                {"attack": rule_id / 100},
                lambda _state, _army, _context, rid=rule_id: checked.append(rid) or True,
            )

        army = next(iter(self.state.armies.values()))
        with patch.dict(MILITARY_MODIFIER_RULES, {3: rule(3), 1: rule(1), 2: rule(2)}, clear=True):
            active = active_military_modifiers(self.state, army)
        self.assertEqual(checked, [1, 2, 3])
        self.assertEqual([modifier["id"] for modifier in active], [1, 2, 3])

    def test_huan_qian_modifier_requires_both_event_and_commander(self):
        army = next(iter(self.state.armies.values()))
        army.commander = person_id_by_name(self.state, "桓谦")
        self.assertEqual(active_military_modifiers(self.state, army), [])
        self.state.events[2]["triggered"] = True
        self.assertEqual([item["id"] for item in active_military_modifiers(self.state, army)], [1])
        army.commander = None
        self.assertEqual(active_military_modifiers(self.state, army), [])

    def test_story_data_survives_save_round_trip(self):
        self.state.month = 12
        queue_start_of_turn_events(self.state)
        restored = GameState.from_dict(self.state.to_dict())
        self.assertTrue(restored.events[1]["triggered"])
        self.assertTrue(restored.events[2]["triggered"])
        self.assertEqual(restored.flags["pending_story_events"], [1, 2])
        qian = next(army for army in restored.armies.values() if restored.person_name(army.commander) == "桓谦")
        self.assertAlmostEqual(modifier_effect_total(active_military_modifiers(restored, qian), "attack"), 0.20)
        self.assertEqual(restored.player["level"], 6)

    def test_chinese_month_names_and_yixi_era(self):
        self.state.year = 405
        self.state.month = 1
        self.assertEqual(calendar_text(self.state), "公元405年　元兴四年　正月")
        self.state.flags["era_name"] = "义熙"
        self.state.flags["era_start_year"] = 405
        self.assertEqual(calendar_text(self.state), "公元405年　义熙元年　正月")
        self.state.month = 11
        self.assertTrue(calendar_text(self.state).endswith("冬月"))
        self.state.month = 12
        self.assertTrue(calendar_text(self.state).endswith("腊月"))

    def test_strategy_schema_contains_prerequisites_exclusions_and_effects(self):
        strategy = strategy_record(7, "示例经略", [1, 2], [8], 2, "稳定度+5")
        self.assertEqual(strategy["prerequisites"], [1, 2])
        self.assertEqual(strategy["mutually_exclusive"], [8])
        self.assertEqual(strategy["duration_months"], 2)
        self.assertEqual(strategy["effect_description"], "稳定度+5")

    def test_national_modifiers_are_serializable_and_composable(self):
        add_national_modifier(self.state, 1, "整军经武", "军饷-10%", {"military_pay": -0.10})
        add_national_modifier(self.state, 2, "裁撤冗兵", "军饷-5%", {"military_pay": -0.05})
        self.assertAlmostEqual(national_modifier_total(self.state, "military_pay"), -0.15)
        restored = GameState.from_dict(self.state.to_dict())
        self.assertAlmostEqual(national_modifier_total(restored, "military_pay"), -0.15)


if __name__ == "__main__":
    unittest.main()
