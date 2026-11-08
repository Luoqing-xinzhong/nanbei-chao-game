from __future__ import annotations

import random
import unittest
from unittest.mock import patch

from app.content.v1_2.climate import (
    CLIMATE_WEIGHTS,
    WEATHER_YIELD_FACTORS,
    is_frozen_water_road,
)
from app.content.v1_2.climate import (
    ensure_annual_climate,
    is_northern_region,
    is_winter_month,
    months_until_winter,
    queue_march_climate_report,
    region_weather_probabilities,
    reveal_climate_report,
    set_annual_climate,
)
from app.content.v1_2.economy import annual_production, population_units, region_economy
from app.content.v1_2.scenario import load_v12_state
from app.content.v1_2.ai_military import national_military_snapshot
from app.rules.common import RuleError
from app.rules.military import effective_road_type, legal_moves
from app.rules.turn import advance_phase


class V12ClimateTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v12_state()

    def test_ai_snapshot_knows_winter_length_and_warns_two_months_early(self):
        self.state.month = 8
        set_annual_climate(self.state, self.state.year, "cold_winter")
        self.assertEqual(months_until_winter(self.state), 2)
        snapshot = national_military_snapshot(self.state, 2)
        self.assertEqual(snapshot["winter_length"], 5)
        self.assertTrue(snapshot["winter_naval_caution"])
        self.state.flags["difficulty"] = "normal"

    def region_id(self, name: str) -> int:
        return next(int(region_id) for region_id, region in self.state.regions.items() if region["name"] == name)

    def city_id(self, name: str) -> int:
        return next(int(city_id) for city_id, city in self.state.cities.items() if city["name"] == name)

    def road(self, left_name: str, right_name: str) -> dict:
        endpoints = {self.city_id(left_name), self.city_id(right_name)}
        return next(road for road in self.state.roads if {int(road["from"]), int(road["to"])} == endpoints)

    def test_all_six_region_weather_states_exist(self):
        self.assertEqual(
            set(WEATHER_YIELD_FACTORS),
            {"地震", "台风", "洪涝", "干旱", "正常", "风调雨顺"},
        )
        self.assertEqual(WEATHER_YIELD_FACTORS["地震"], 0.9)
        self.assertEqual(WEATHER_YIELD_FACTORS["台风"], 0.9)

    def test_difficulty_changes_annual_climate_weights(self):
        self.assertGreater(CLIMATE_WEIGHTS["easy"]["bumper"], CLIMATE_WEIGHTS["normal"]["bumper"])
        self.assertGreater(CLIMATE_WEIGHTS["normal"]["bumper"], CLIMATE_WEIGHTS["hard"]["bumper"])
        self.assertLess(CLIMATE_WEIGHTS["easy"]["disaster"], CLIMATE_WEIGHTS["normal"]["disaster"])
        self.assertLess(CLIMATE_WEIGHTS["normal"]["disaster"], CLIMATE_WEIGHTS["hard"]["disaster"])

    def test_march_climate_report_costs_exactly_one_hundred_authority(self):
        self.state.month = 3
        set_annual_climate(self.state, self.state.year, "el_nino")
        self.assertTrue(queue_march_climate_report(self.state))
        self.assertEqual(self.state.flags["pending_v12_climate_report"], self.state.year)
        before = self.state.authority
        report = reveal_climate_report(self.state)
        self.assertEqual(self.state.authority, before - 100)
        self.assertIn("南涝北旱年", report)
        self.assertFalse(queue_march_climate_report(self.state))

    def test_entering_march_automatically_queues_climate_report(self):
        self.state.month = 2
        self.state.phase_index = 3
        advance_phase(self.state)
        self.assertEqual(self.state.month, 3)
        self.assertEqual(self.state.flags["pending_v12_climate_report"], self.state.year)

    def test_climate_report_cannot_be_viewed_without_authority(self):
        self.state.authority = 99
        with self.assertRaises(RuleError):
            reveal_climate_report(self.state)

    def test_base_hazards_follow_region_rules(self):
        set_annual_climate(self.state, self.state.year, "normal")
        set_annual_climate(self.state, self.state.year - 1, "normal")
        liang = region_weather_probabilities(self.state, self.region_id("梁州"))
        yangzhou = region_weather_probabilities(self.state, self.region_id("扬州"))
        jizhou = region_weather_probabilities(self.state, self.region_id("冀州"))
        self.assertEqual(liang["地震"], 0.30)
        self.assertEqual(yangzhou["台风"], 0.20)
        self.assertGreater(yangzhou["洪涝"], jizhou["洪涝"])
        self.assertGreater(jizhou["干旱"], yangzhou["干旱"])
        self.assertTrue(is_northern_region("冀州"))
        self.assertFalse(is_northern_region("扬州"))

    def test_el_nino_la_nina_and_disaster_year_modify_expected_regions(self):
        south = self.region_id("扬州")
        north = self.region_id("冀州")
        set_annual_climate(self.state, self.state.year - 1, "normal")
        set_annual_climate(self.state, self.state.year, "normal")
        baseline_south = region_weather_probabilities(self.state, south)
        baseline_north = region_weather_probabilities(self.state, north)

        set_annual_climate(self.state, self.state.year, "el_nino")
        el_nino_south = region_weather_probabilities(self.state, south)
        el_nino_north = region_weather_probabilities(self.state, north)
        self.assertGreater(el_nino_south["洪涝"], baseline_south["洪涝"])
        self.assertGreater(el_nino_north["干旱"], baseline_north["干旱"])

        set_annual_climate(self.state, self.state.year, "la_nina")
        la_nina_south = region_weather_probabilities(self.state, south)
        la_nina_north = region_weather_probabilities(self.state, north)
        self.assertGreater(la_nina_south["干旱"], baseline_south["干旱"])
        self.assertGreater(la_nina_north["洪涝"], baseline_north["洪涝"])

        set_annual_climate(self.state, self.state.year, "disaster")
        player_disaster = region_weather_probabilities(self.state, south)
        ai_disaster = region_weather_probabilities(self.state, north)
        self.assertGreater(player_disaster["台风"], baseline_south["台风"])
        self.assertEqual(ai_disaster["洪涝"], baseline_north["洪涝"])

    def test_warm_and_cold_winter_affect_next_year_hazards(self):
        region_id = self.region_id("扬州")
        set_annual_climate(self.state, self.state.year, "normal")
        set_annual_climate(self.state, self.state.year - 1, "normal")
        baseline = region_weather_probabilities(self.state, region_id)
        set_annual_climate(self.state, self.state.year - 1, "warm_winter")
        after_warm = region_weather_probabilities(self.state, region_id)
        self.assertGreater(after_warm["干旱"], baseline["干旱"])
        set_annual_climate(self.state, self.state.year - 1, "cold_winter")
        after_cold = region_weather_probabilities(self.state, region_id)
        self.assertGreater(after_cold["洪涝"], baseline["洪涝"])

    def test_earthquake_removes_population_stability_and_ten_percent_harvest(self):
        region_id = self.region_id("梁州")
        before_population = len(population_units(self.state, region_id))
        before_stability = int(region_economy(self.state, region_id)["stability"])

        def fixed_weather(_state, target_region_id, _rng):
            return ("地震", 0.9) if int(target_region_id) == region_id else ("正常", 1.0)

        with patch("app.content.v1_2.climate.roll_region_weather", side_effect=fixed_weather):
            report = annual_production(self.state, random.Random(11))
        row = next(item for item in report if int(item["region_id"]) == region_id)
        self.assertEqual(row["weather"], "地震")
        self.assertEqual(row["weather_factor"], 0.9)
        self.assertGreaterEqual(row["disaster_deaths"], 1)
        self.assertLessEqual(row["disaster_deaths"], 5)
        self.assertEqual(len(population_units(self.state, region_id)), before_population - row["disaster_deaths"])
        self.assertEqual(region_economy(self.state, region_id)["stability"], max(0, before_stability - 10))

    def test_standard_warm_and_cold_winter_lengths(self):
        year = self.state.year
        set_annual_climate(self.state, year, "normal")
        self.state.month = 11
        self.assertTrue(is_winter_month(self.state))
        self.state.month = 10
        self.assertFalse(is_winter_month(self.state))

        set_annual_climate(self.state, year, "warm_winter")
        self.state.month = 11
        self.assertFalse(is_winter_month(self.state))
        self.state.month = 12
        self.assertTrue(is_winter_month(self.state))

        set_annual_climate(self.state, year, "cold_winter")
        self.state.month = 10
        self.assertTrue(is_winter_month(self.state))

        self.state.year = year + 1
        self.state.month = 1
        self.assertTrue(is_winter_month(self.state))
        set_annual_climate(self.state, year, "warm_winter")
        self.assertFalse(is_winter_month(self.state))

    def test_northern_waterway_freezes_and_behaves_as_land(self):
        set_annual_climate(self.state, self.state.year, "normal")
        self.state.month = 11
        road = self.road("博平", "平原")
        self.assertEqual(int(road["type"]), 3)
        self.assertTrue(is_frozen_water_road(self.state, road))
        self.assertEqual(effective_road_type(self.state, road), 1)

        army = self.state.armies[6]
        army.location_id = self.city_id("博平")
        army.action_points = army.max_action_points
        target = self.city_id("平原")
        self.assertTrue(any(city_id == target and road_type == 1 for city_id, road_type, _cost in legal_moves(self.state, army.id)))
        army.army_type = 1
        army.units = [{"type": 4, "count": 1000}]
        self.assertFalse(any(city_id == target for city_id, _road_type, _cost in legal_moves(self.state, army.id)))

    def test_severe_winter_freezes_the_five_additional_southern_links(self):
        links = (("山阳", "淮陵"), ("淮陵", "涡口"), ("涡口", "寿春"), ("寿春", "颍口"), ("颍口", "义阳"))
        self.state.month = 10
        set_annual_climate(self.state, self.state.year, "normal")
        self.assertTrue(all(not is_frozen_water_road(self.state, self.road(left, right)) for left, right in links))
        set_annual_climate(self.state, self.state.year, "cold_winter")
        self.assertTrue(all(is_frozen_water_road(self.state, self.road(left, right)) for left, right in links))

    def test_climate_record_is_stable_for_the_whole_year(self):
        first = ensure_annual_climate(self.state, rng=random.Random(1))
        second = ensure_annual_climate(self.state, rng=random.Random(999))
        self.assertIs(first, second)
        self.assertEqual(first["kind"], second["kind"])


if __name__ == "__main__":
    unittest.main()
