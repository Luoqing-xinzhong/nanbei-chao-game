from __future__ import annotations

import random
import unittest

from app.content.v1_2.economy import (
    market_price,
    population_units,
    projected_region_production,
    region_economy,
    settle_capital_expenses,
    settle_december_warehouse_food,
    warehouse_capacity,
    warehouse_resource_capacity,
)
from app.content.v1_2.scenario import load_v12_state
from app.content.v1_3.culture import (
    SOUTHERN_REGIONS,
    build_school,
    building_slot_status,
    change_culture,
    completed_poetry_nodes,
    culture_balance,
    food_consumption_multiplier,
    initialize_v13,
    region_approval,
    region_buildings,
    region_culture_projection,
    monthly_culture_projection,
    set_culture_supply,
    settle_culture,
    study_classic_node,
    upgrade_school,
)
from app.content.v1_3.scenario import inherit_scenario, inheritance_available, load_default_wenjiao_state
from app.rules.common import RuleError
from app.rules.economy import projected_expenses
from app.rules.treasury import set_treasury, treasury_balance
from app.rules.turn import settle_turn


class V13ContentTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v12_state()
        self.state.year = 434
        self.state.month = 1
        initialize_v13(self.state)

    def _region(self, name: str) -> int:
        return next(int(rid) for rid, region in self.state.regions.items() if region["name"] == name)

    def test_v13_adds_development_phase_without_changing_v12_phase_list(self):
        self.assertEqual(self.state.phase_names, ("政治阶段", "发展阶段", "谋划阶段", "外交阶段", "军事阶段"))
        old = load_v12_state()
        self.assertEqual(old.phase_names, ("政治阶段", "谋划阶段", "外交阶段", "军事阶段"))

    def test_initial_approval_is_eighty_south_and_fifty_north(self):
        self.assertEqual(region_approval(self.state, self._region("扬州")), 80)
        self.assertEqual(region_approval(self.state, self._region("中原地区")), 50)

    def test_development_region_details_use_live_non_mutating_projections(self):
        region_id = self._region("扬州")
        record = region_economy(self.state, region_id)
        before_warehouse = dict(record["warehouse"])

        production = projected_region_production(self.state, region_id)
        culture = region_culture_projection(self.state, region_id)

        self.assertGreaterEqual(float(production["food"]), 0)
        self.assertGreaterEqual(float(culture["total_output"]), 0)
        self.assertGreater(float(culture["base_maintenance"]), 0)
        self.assertEqual(
            float(culture["requested_maintenance"]),
            round(float(culture["base_maintenance"]) * float(culture["supply_multiplier"]), 2),
        )
        self.assertEqual(record["warehouse"], before_warehouse)

        set_culture_supply(self.state, region_id, 1.5)
        updated = region_culture_projection(self.state, region_id)
        self.assertEqual(updated["supply_multiplier"], 1.5)
        self.assertEqual(
            float(updated["requested_maintenance"]),
            round(float(updated["base_maintenance"]) * 1.5, 2),
        )

    def test_v13_food_capacity_scales_with_population_but_v12_keeps_general_capacity(self):
        region_id = self._region("扬州")
        expected = round(len(population_units(self.state, region_id)) * 0.8, 2)
        self.assertEqual(warehouse_resource_capacity(self.state, region_id, "food"), expected)
        old = load_v12_state()
        self.assertEqual(warehouse_resource_capacity(old, region_id, "food"), warehouse_capacity(old, region_id))

    def test_december_warehouse_food_loss_is_twenty_percent_of_maximum_capacity(self):
        region_id = self._region("扬州")
        capacity = warehouse_resource_capacity(self.state, region_id, "food")
        record = region_economy(self.state, region_id)
        record["warehouse"]["food"] = capacity
        self.state.month = 12

        reports = settle_december_warehouse_food(self.state)

        report = next(item for item in reports if int(item["region_id"]) == region_id)
        self.assertEqual(report["loss"], round(capacity * 0.2, 2))
        self.assertEqual(record["warehouse"]["food"], round(capacity * 0.8, 2))
        self.assertTrue(any("腊月府库结算：扬州" in line for line in self.state.event_log))

    def test_culture_shortage_blocks_stability_recovery_and_reduces_stability(self):
        region_id = self._region("扬州")
        record = region_economy(self.state, region_id)
        record["stability"] = 80
        set_culture_supply(self.state, region_id, 2.0)
        for rid, region in self.state.regions.items():
            if int(region.get("controller", 0)) == self.state.player_regime_id:
                set_culture_supply(self.state, int(rid), 2.0)
        self.state.flags["v13_culture"]["balance"] = 0.0

        report = settle_culture(self.state)

        self.assertGreater(report["produced"], 20)
        self.assertIn("culture_sufficient", record)
        if not record["culture_sufficient"]:
            self.assertLess(record["stability"], 80)

    def test_school_uses_local_treasury_has_slot_and_upgrade_cooldown(self):
        region_id = self._region("扬州")
        warehouse = region_economy(self.state, region_id)["warehouse"]
        from app.rules.treasury import set_treasury, treasury_balance

        set_treasury(self.state, self.state.player_regime_id, 100)
        before = treasury_balance(self.state)

        school = build_school(self.state, region_id)

        self.assertEqual(school["name"], "国子学")
        self.assertNotIn("copper", warehouse)
        self.assertEqual(treasury_balance(self.state), before - float(school["construction_cost"]))
        self.assertIn(school, region_buildings(self.state, region_id))
        slots = building_slot_status(self.state, region_id)
        self.assertGreaterEqual(len(slots), 2)
        self.assertIs(slots[0]["building"], school)
        self.assertTrue(any(slot["building"] is None for slot in slots[1:]))
        with self.assertRaisesRegex(RuleError, "升级冷却"):
            upgrade_school(self.state, region_id)
        self.state.turn_number += 2
        upgraded = upgrade_school(self.state, region_id)
        self.assertEqual(upgraded["level"], 2)

    def test_building_upgrade_cooldown_is_per_building_id(self):
        first = self._region("扬州")
        second = self._region("江州")
        from app.rules.treasury import set_treasury

        set_treasury(self.state, self.state.player_regime_id, 100)
        first_school = build_school(self.state, first)
        second_school = build_school(self.state, second)
        first_school["last_upgrade_turn"] = self.state.turn_number - 2

        upgraded = upgrade_school(self.state, first, int(first_school["id"]))

        self.assertEqual(upgraded["level"], 2)
        self.assertEqual(second_school["level"], 1)
        with self.assertRaisesRegex(RuleError, second_school["name"]):
            upgrade_school(self.state, second, int(second_school["id"]))

    def test_poetry_tree_costs_culture_and_enforces_prerequisites(self):
        change_culture(self.state, 200)
        with self.assertRaisesRegex(RuleError, "前置"):
            study_classic_node(self.state, "poetry", 2)
        before = culture_balance(self.state)
        study_classic_node(self.state, "poetry", 1)
        self.assertEqual(culture_balance(self.state), before - 50)
        self.assertEqual(completed_poetry_nodes(self.state), {1})

    def test_zero_approval_doubles_player_food_consumption_only(self):
        region_id = self._region("中原地区")
        self.state.flags["v13_culture"]["approval"][str(region_id)] = 0
        self.assertEqual(food_consumption_multiplier(self.state, region_id), 2.0)
        population = len(population_units(self.state, region_id))
        from app.content.v1_2.economy import market_demand

        self.assertEqual(market_demand(self.state, region_id, "food"), max(1.0, population * 2.0))
        self.state.regions[region_id]["controller"] = 2
        self.assertEqual(food_consumption_multiplier(self.state, region_id), 1.0)
        self.assertEqual(market_demand(self.state, region_id, "food"), max(1.0, float(population)))

    def test_food_price_uses_approval_adjusted_demand(self):
        state = load_default_wenjiao_state()
        region_id = next(
            int(item["id"])
            for item in state.regions.values()
            if item["name"] == "淮南地区"
        )
        population = len(population_units(state, region_id))
        region_economy(state, region_id)["market"]["food"] = float(population)
        state.flags["v13_culture"]["approval"][str(region_id)] = 100
        fully_accepted_price = market_price(state, region_id, "food")
        state.flags["v13_culture"]["approval"][str(region_id)] = 50
        low_approval_price = market_price(state, region_id, "food")

        self.assertGreater(low_approval_price, fully_accepted_price)

    def test_monthly_culture_projection_matches_settlement_totals(self):
        projection = monthly_culture_projection(self.state)
        report = settle_culture(self.state)

        self.assertEqual(report["produced"], projection["produced"])
        self.assertEqual(report["spent"], projection["spent"])
        self.assertEqual(
            report["balance"],
            round(projection["net"], 2),
        )

    def test_inheritance_requires_exact_transition_marker_and_preserves_world(self):
        self.state.flags["scenario_id"] = "yuanjia_governance"
        self.state.flags["v13_transition_ready"] = {"source": "yuanjia_governance", "target": "wenjiao_south", "year": 433}
        self.state.flags.pop("rules_version", None)
        person_id = min(self.state.persons)
        self.state.persons[person_id]["opinion_of_player"] = 77
        self.assertTrue(inheritance_available(self.state, "wenjiao_south")[0])

        inherited = inherit_scenario(self.state, "wenjiao_south")

        self.assertEqual((inherited.year, inherited.month), (434, 1))
        self.assertEqual(inherited.flags["rules_version"], "1.3")
        self.assertEqual(inherited.persons[person_id]["opinion_of_player"], 77)
        self.assertNotIn("v13_transition_ready", inherited.flags)
        self.assertEqual(inherited.events, {})
        self.assertEqual(inherited.strategies, {})
        self.assertNotIn("pending_story_events", inherited.flags)

    def test_default_wenjiao_snapshot_uses_slot_two_world_with_requested_overrides(self):
        state = load_default_wenjiao_state()
        chouchi = state.regimes[11]
        wei = state.regimes[2]
        chouchi_region_id = int(state.cities[int(chouchi["capital"])]["region_id"])

        self.assertEqual((state.year, state.month), (434, 1))
        self.assertEqual(state.flags["scenario_id"], "wenjiao_south")
        self.assertEqual(state.flags["inherited_from"], "frozen_default_snapshot")
        self.assertTrue(state.flags["default_snapshot_frozen"])
        self.assertEqual(state.event_log, [])
        self.assertEqual(state.flags["battle_reports"], [])
        self.assertEqual(state.player_regime["stability"], 50)
        self.assertEqual(state.player_regime["war_support"], 50)
        self.assertEqual(state.authority, 500)
        self.assertEqual(state.legislation, {})
        self.assertEqual(state.laws["economy"], 2)
        from app.rules.treasury import treasury_balance

        self.assertEqual(treasury_balance(state), 100.0)
        self.assertEqual(state.persons[26]["spouse"], 114)
        self.assertEqual(state.persons[114]["spouse"], 26)
        self.assertEqual(state.player_regime["internal"]["empress"], 114)
        self.assertEqual(culture_balance(state), 50.0)
        self.assertEqual(state.flags["v12_economy"]["manpower"][str(state.player_regime_id)], 10_000)
        self.assertEqual(state.flags["v13_culture"]["buildings"], {})
        self.assertEqual(state.flags["v13_culture"]["next_building_id"], 1)
        for region_id in state.regions:
            record = region_economy(state, region_id)
            self.assertEqual(record["local_policy"], "stockpile")
            self.assertEqual(float(record["culture_supply"]), 1.0)
            if int(state.regions[region_id].get("controller", 0)) == state.player_regime_id:
                expected_approval = 75 if state.regions[region_id]["name"] in SOUTHERN_REGIONS else 50
                self.assertEqual(region_approval(state, region_id), expected_approval)
            land = record["land"]
            total_land = sum(int(value) for value in land.values())
            if total_land:
                self.assertAlmostEqual(int(land["gentry"]) / total_land, 0.60, delta=0.5 / total_land + 1e-9)
        player_region_names = set(state.player_regime["regions"])
        for region_id, region in state.regions.items():
            expected = 30.0 if region["name"] in player_region_names else 0.0
            self.assertEqual(float(region_economy(state, region_id)["warehouse"]["food"]), expected)
            if expected:
                self.assertGreaterEqual(warehouse_resource_capacity(state, region_id, "food"), 30.0)
        self.assertEqual(int(state.regions[chouchi_region_id]["controller"]), 11)
        self.assertIn(state.regions[chouchi_region_id]["name"], chouchi["regions"])
        self.assertNotIn(state.regions[chouchi_region_id]["name"], wei["regions"])
        self.assertTrue(
            all(
                int(state.cities[army.location_id].get("region_id", 0)) != chouchi_region_id
                for army in state.armies.values()
                if int(army.regime_id) == 2
            )
        )
        self.assertEqual(state.armies[19].location_id, int(wei["capital"]))
        self.assertEqual(state.events, {})
        self.assertEqual(state.strategies, {})

    def test_wenjiao_official_salary_uses_january_and_july_schedule(self):
        state = load_default_wenjiao_state()
        salary = projected_expenses(state, state.player_regime_id)[0]
        set_treasury(state, state.player_regime_id, 10_000)
        state.month = 2
        settle_capital_expenses(state)
        self.assertEqual(treasury_balance(state), 10_000)
        state.month = 7
        settle_capital_expenses(state)
        self.assertEqual(treasury_balance(state), 10_000 - salary)

    def test_default_wenjiao_loading_does_not_change_v12_content(self):
        load_default_wenjiao_state()
        old = load_v12_state()
        from app.content.v1_2.strategies import ensure_strategy_records

        ensure_strategy_records(old)
        self.assertEqual(old.flags["content_version"], "1.2")
        self.assertNotEqual(old.flags.get("rules_version"), "1.3")
        self.assertTrue(old.events)
        self.assertTrue(old.strategies)

    def test_wenjiao_south_also_marks_its_final_settlement(self):
        self.state.flags["scenario_id"] = "wenjiao_south"
        self.state.year = 446
        self.state.month = 12

        settle_turn(self.state)

        self.assertEqual(
            self.state.flags.get("v13_transition_ready"),
            {"source": "wenjiao_south", "target": "blood_tears", "year": 446},
        )


if __name__ == "__main__":
    unittest.main()
