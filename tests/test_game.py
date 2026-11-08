from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from app.data_loader import load_initial_state
from app.constants import REGIME_COLORS
from app.models import Army
from app.rules import diplomacy, economy, intrigue, military, politics
from app.rules.common import RuleError, is_regime_eliminated
from app.rules.turn import advance_phase, remove_dead_appointments, remove_dead_confidants, remove_eliminated_regime_armies
from app.save_service import list_save_slots, load_game, save_game
from app.ui.widgets import MapView
from app.ui.military_quick_actions import player_armies_at_city
from app.ui.main_screen import chronicle_history, military_history


class DataAndSaveTests(unittest.TestCase):
    def test_log_histories_keep_all_records_and_separate_battles(self):
        state = load_initial_state()
        state.event_log.clear()
        state.flags["battle_reports"] = []
        for index in range(130):
            state.add_log(f"纪事{index}")
        battle = "【战报】测试战斗"
        state.add_log(battle)
        state.flags["battle_reports"].append(battle)

        self.assertEqual(len(chronicle_history(state)), 130)
        self.assertEqual(chronicle_history(state)[-1], "纪事129")
        self.assertEqual(military_history(state), [battle])

    def test_initial_data_is_normalized(self):
        state = load_initial_state()
        self.assertEqual(state.player_regime["name"], "晋")
        self.assertEqual(state.person_name(state.player["id"]), "刘裕")
        self.assertGreater(len(state.cities), 100)
        self.assertGreater(len(state.regions[2]["cities"]), 0)
        self.assertTrue(all(r["from"] in state.cities and r["to"] in state.cities for r in state.roads))
        self.assertEqual(set(state.cities), set(range(1, 145)))
        self.assertEqual(len(state.armies), len(state.regimes))
        self.assertEqual(state.confidants, [])
        jiangzhou = next(city["id"] for city in state.cities.values() if city["name"] == "江州")
        jiangyou = next(city["id"] for city in state.cities.values() if city["name"] == "江油关")
        links = [
            road for road in state.roads
            if {int(road["from"]), int(road["to"])} == {int(jiangzhou), int(jiangyou)}
        ]
        self.assertEqual({int(road["type"]) for road in links}, {1, 3})
        hengyang = next(city["id"] for city in state.cities.values() if city["name"] == "衡阳")
        guiyang = next(city["id"] for city in state.cities.values() if city["name"] == "桂阳")
        hengyang_guiyang = [
            road for road in state.roads
            if {int(road["from"]), int(road["to"])} == {int(hengyang), int(guiyang)}
        ]
        self.assertEqual([int(road["type"]) for road in hengyang_guiyang], [1])
        tongguan = next(city["id"] for city in state.cities.values() if city["name"] == "潼关")
        puban = next(city["id"] for city in state.cities.values() if city["name"] == "蒲坂")
        tongguan_puban = [
            road for road in state.roads
            if {int(road["from"]), int(road["to"])} == {int(tongguan), int(puban)}
        ]
        self.assertEqual(len(tongguan_puban), 1)
        self.assertEqual(state.cities[133]["name"], "涝谷")
        for region in state.regions.values():
            capitals = [city_id for city_id in region["cities"] if state.cities[city_id]["capital"]]
            self.assertEqual(len(capitals), 1, region["name"])

    def test_save_round_trip(self):
        state = load_initial_state()
        state.authority = 777
        with tempfile.TemporaryDirectory() as folder:
            path = save_game(state, "测试", Path(folder))
            restored = load_game(path)
        self.assertEqual(restored.authority, 777)
        self.assertEqual(len(restored.cities), len(state.cities))
        self.assertEqual(restored.armies[1].soldiers, state.armies[1].soldiers)

    def test_ten_fixed_save_slots_can_overwrite_existing_slot(self):
        state = load_initial_state()
        with tempfile.TemporaryDirectory() as folder:
            save_dir = Path(folder)
            slots = list_save_slots(save_dir)
            self.assertEqual(len(slots), 10)
            self.assertTrue(all(not path.exists() for _slot, path in slots))

            first_path = save_game(state, "第一次保存", save_dir, slot=3)
            state.authority = 4321
            second_path = save_game(state, "覆盖保存", save_dir, slot=3)

            self.assertEqual(first_path, second_path)
            self.assertEqual(first_path.name, "slot_03.json")
            self.assertEqual(load_game(second_path).authority, 2000)
            self.assertEqual(sum(path.exists() for _slot, path in list_save_slots(save_dir)), 1)

    def test_later_qin_configuration(self):
        state = load_initial_state()
        regime = state.regimes[9]
        self.assertEqual(REGIME_COLORS[regime["color"]], "#b8860b")
        self.assertEqual(state.person_name(regime["internal"]["emperor"]), "姚兴")
        controllers = {region["controller"] for region in state.regions.values() if region["name"] in regime["regions"]}
        self.assertEqual(controllers, {9})

    def test_requested_qingzhou_road_cleanup_and_water_link(self):
        state = load_initial_state()
        muleng_guanggu = [
            road for road in state.roads
            if {int(road["from"]), int(road["to"])} == {101, 102}
        ]
        siyi_juye = [
            road for road in state.roads
            if {int(road["from"]), int(road["to"])} == {144, 106}
        ]
        self.assertEqual(len(muleng_guanggu), 1)
        self.assertEqual(len(siyi_juye), 1)
        self.assertEqual(int(siyi_juye[0]["type"]), 3)

    def test_northern_land_ownership(self):
        state = load_initial_state()
        self.assertIn("幽州", state.regimes[2]["regions"])
        self.assertEqual(state.regions[18]["controller"], 2)
        self.assertIn("东北地区", state.regimes[7]["regions"])
        self.assertEqual(state.regions[23]["controller"], 7)
        self.assertIn("徐州", state.regimes[8]["regions"])
        self.assertEqual(state.regions[15]["controller"], 8)


class MapGeometryTests(unittest.TestCase):
    def test_minimum_scale_covers_viewport(self):
        scale = MapView.minimum_scale_for(1000, 1000)
        self.assertGreaterEqual(2416 * scale, 1000)
        self.assertGreaterEqual(1762 * scale, 1000)
        self.assertAlmostEqual(scale, 1000 / 1762)

    def test_offset_is_clamped_to_map_edges(self):
        self.assertEqual(MapView.bounded_offset(30, 1000, 1200), 0)
        self.assertEqual(MapView.bounded_offset(-300, 1000, 1200), -200)
        self.assertEqual(MapView.bounded_offset(-80, 1000, 1200), -80)

    def test_city_radius_scales_with_map(self):
        self.assertEqual(MapView.city_radius_for(0.5), 5)
        self.assertEqual(MapView.city_radius_for(1.0), 10)
        self.assertEqual(MapView.city_radius_for(2.0), 20)

    def test_overlapping_army_marker_shows_total_battalions(self):
        armies = [
            Army(9001, 1, 0, [{"type": 1, "count": 9000}]),
            Army(9002, 1, 0, [{"type": 1, "count": 12000}]),
        ]
        self.assertEqual(MapView.army_marker_battalions(armies), 21)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.state = load_initial_state()

    def test_economy_and_political_orders(self):
        income = economy.regime_income(self.state, self.state.player_regime_id)
        self.assertGreater(income, 0)
        old_treasury = self.state.player_regime["treasury"]
        message = politics.temporary_tax(self.state)
        self.assertIn("临时征税", message)
        self.assertEqual(self.state.player_regime["treasury"], old_treasury + income)
        politics.develop(self.state, 1)
        self.assertEqual(self.state.regions[1]["development"], 78)

    def test_family_land_uses_higher_tax_rate(self):
        region = {"land_ownership": [3] * 100, "development": 100, "prosperity": 10}
        self.assertEqual(economy.calculate_region_income(region), 25)
        region["governor"] = 8
        self.assertEqual(economy.calculate_region_income(region), 50)

    def test_region_without_governor_has_half_income(self):
        region = {"land_ownership": [2] * 100, "development": 100, "prosperity": 10, "governor": None}
        self.assertEqual(economy.calculate_region_income(region), 50)
        region["governor"] = 1
        self.assertEqual(economy.calculate_region_income(region), 100)

    def test_treasury_and_militia_growth_soft_and_hard_caps(self):
        regime = self.state.player_regime
        regime["treasury"] = 15_000
        full_income = economy.regime_income(self.state, self.state.player_regime_id)
        regime["treasury"] = 15_001
        self.assertEqual(economy.regime_income(self.state, self.state.player_regime_id), int(full_income * 0.2))
        regime["treasury"] = 20_000
        self.assertEqual(economy.regime_income(self.state, self.state.player_regime_id), int(full_income * 0.2))
        regime["treasury"] = 20_001
        self.assertEqual(economy.regime_income(self.state, self.state.player_regime_id), 0)

        regime["militia"] = 150_000
        full_growth = economy.regime_militia_growth(self.state, self.state.player_regime_id)
        regime["militia"] = 150_001
        self.assertEqual(economy.regime_militia_growth(self.state, self.state.player_regime_id), int(round(full_growth * 0.2)))
        regime["militia"] = 200_001
        self.assertEqual(economy.regime_militia_growth(self.state, self.state.player_regime_id), 0)

    def test_prosperity_no_longer_recovers_naturally(self):
        region = next(
            item for item in self.state.regions.values()
            if item["name"] in self.state.player_regime["regions"]
            and int(item.get("controller", 0)) == self.state.player_regime_id
        )
        region["prosperity"] = 5
        # 完成一个完整回合；繁荣度只会因政令、剧情或战斗改变。
        for _ in range(4):
            advance_phase(self.state)
        self.assertEqual(region["prosperity"], 5)

    def test_intrigue_changes_target(self):
        confidant = next(
            person["id"] for person in self.state.persons.values()
            if person.get("country_id") == self.state.player_regime_id
            and person.get("status") == 1
            and not person.get("is_player")
        )
        self.state.confidants.append(confidant)
        family = self.state.persons[confidant].get("family_id")
        target = next(p["id"] for p in intrigue.available_targets(self.state) if p.get("family_id") != family)
        before = self.state.persons[target]["opinion_of_player"]
        intrigue.perform(self.state, confidant, target, "拉拢", random.Random(1))
        self.assertGreater(self.state.persons[target]["opinion_of_player"], before)

    def test_march_and_battle(self):
        army = self.state.armies[1]
        move = military.legal_moves(self.state, army.id)[0]
        military.march(self.state, army.id, move[0])
        self.assertEqual(army.location_id, move[0])
        army.location_id = 1
        army.action_points = 1
        enemy = next(a for a in self.state.armies.values() if a.regime_id != army.regime_id)
        enemy.location_id = 2
        self.state.wars.append(self.state.relation_pair(army.regime_id, enemy.regime_id))
        result = military.attack(self.state, army.id, 2, random.Random(4))
        self.assertIn("进攻", result)
        self.assertEqual(army.action_points, 0)

    def test_empty_armies_are_removed_and_cannot_attack_again(self):
        own = next(army for army in self.state.armies.values() if army.regime_id == 1)
        empty_id = max(self.state.armies) + 1
        self.state.armies[empty_id] = Army(
            empty_id,
            1,
            0,
            [],
            location_id=own.location_id,
        )
        self.assertEqual(military.remove_empty_armies(self.state), [empty_id])
        self.assertNotIn(empty_id, self.state.armies)
        self.assertIn(f"军队#{empty_id}", self.state.event_log[-1])

    def test_empty_attacker_is_cleaned_before_combat(self):
        enemy = next(army for army in self.state.armies.values() if army.regime_id != 1)
        enemy.location_id = 2
        empty_id = max(self.state.armies) + 1
        self.state.armies[empty_id] = Army(empty_id, 1, 0, [], location_id=1)
        self.state.wars.append(self.state.relation_pair(1, enemy.regime_id))
        with self.assertRaisesRegex(RuleError, "空编制已被清理"):
            military.attack(self.state, empty_id, 2, random.Random(1))
        self.assertNotIn(empty_id, self.state.armies)

    def test_one_click_march_reaches_two_or_three_step_destination(self):
        army = self.state.armies[1]
        routes = military.legal_march_routes(self.state, army.id)
        self.assertTrue(routes)
        path, cost = routes[0]
        self.assertIn(len(path), {2, 3})
        old_action_points = army.action_points
        result = military.march_route(self.state, army.id, path)
        self.assertEqual(army.location_id, path[-1])
        self.assertAlmostEqual(army.action_points, old_action_points - cost)
        self.assertIn(f"连续行军{len(path)}步", result)

    def test_one_click_march_uses_cheapest_parallel_road_during_execution(self):
        army = self.state.armies[1]
        army.location_id = 1
        army.action_points = 1.0
        army.max_action_points = 1.0
        army.units = [{"type": 1, "count": 1000}]
        self.state.roads = [
            {"id": 1, "from": 1, "to": 2, "type": 1},
            {"id": 2, "from": 1, "to": 2, "type": 3},
            {"id": 3, "from": 2, "to": 3, "type": 3},
        ]

        moves_to_two = [move for move in military.legal_moves(self.state, army.id) if move[0] == 2]
        self.assertEqual(moves_to_two, [(2, 3, 0.3)])
        routes = dict(military.legal_march_routes(self.state, army.id))
        self.assertAlmostEqual(routes[(2, 3)], 0.6)

        military.march_route(self.state, army.id, (2, 3))

        self.assertEqual(army.location_id, 3)
        self.assertAlmostEqual(army.action_points, 0.4)

    def test_reduced_water_route_costs(self):
        army = self.state.armies[1]
        self.assertFalse(army.pure_cavalry)
        self.assertEqual(military.route_cost(army, 3), 0.3)
        self.assertEqual(military.route_cost(army, 4), 0.5)
        army.units = [{"type": 2, "count": 1000}]
        self.assertTrue(army.pure_cavalry)
        self.assertEqual(military.route_cost(army, 3), 0.6)
        self.assertEqual(military.route_cost(army, 4), 1.0)
        army.army_type = 1
        army.units = [{"type": 4, "count": 1000}]
        self.assertEqual(military.route_cost(army, 3), 0.3)
        self.assertEqual(military.route_cost(army, 4), 0.5)

    def test_recruitment_and_military_pay_use_reduced_costs(self):
        self.state.laws["power"] = 2  # 避免门阀政治的政令驳回判定。
        old_treasury = self.state.player_regime["treasury"]
        politics.conscript(self.state, 1000)
        self.assertEqual(self.state.player_regime["treasury"], old_treasury - 20)
        _official_salary, military_pay = economy.projected_expenses(self.state, self.state.player_regime_id)
        battalions = sum(
            army.active_battalions for army in self.state.armies.values()
            if army.regime_id == self.state.player_regime_id
        )
        self.assertEqual(military_pay, battalions * 10)

    def test_official_salary_is_two_per_filled_office(self):
        official_salary, _military_pay = economy.projected_expenses(self.state, self.state.player_regime_id)
        filled = sum(
            len(value) if isinstance(value, list) else int(bool(value))
            for value in self.state.player_regime["internal"].values()
        )
        self.assertEqual(official_salary, filled * 2)

    def test_marching_into_enemy_capital_transfers_region_control(self):
        army = self.state.armies[1]
        # 1—2 有道路；把 2 暂作被敌国控制地区的首府，验证行军占领分支。
        self.state.cities[2]["capital"] = True
        self.state.regions[1]["controller"] = 2
        self.state.wars.append([1, 2])
        result = military.march(self.state, army.id, 2)
        self.assertEqual(self.state.regions[1]["controller"], 1)
        self.assertIn("全境转由晋控制", result)

    def test_capturing_enemy_capital_transfers_region_control(self):
        attacker = self.state.armies[1]
        enemy = self.state.armies[2]
        self.state.cities[2]["capital"] = True
        self.state.regions[1]["controller"] = 2
        self.state.wars.append([1, 2])
        enemy.location_id = 2
        enemy.units = [{"type": 1, "count": 1}]
        result = military.attack(self.state, attacker.id, 2, random.Random(2))
        self.assertEqual(attacker.location_id, 2)
        self.assertEqual(self.state.regions[1]["controller"], 1)
        self.assertIn("全境转由晋控制", result)

    def test_peace_can_return_or_cede_ai_land_controlled_by_player(self):
        region_id = 17  # 冀州，法理属于魏
        self.state.regions[region_id]["controller"] = 1
        self.state.regions[region_id]["governor"] = 8
        self.state.wars.append([1, 2])
        result = diplomacy.make_peace(self.state, 2, {})
        self.assertNotIn("冀州", self.state.player_regime["regions"])
        self.assertIn("冀州", self.state.regimes[2]["regions"])
        self.assertEqual(self.state.regions[region_id]["controller"], 2)
        self.assertIn("我方归还冀州", result)

        self.state.diplomatic_actions.clear()
        self.state.regions[region_id]["controller"] = 1
        self.state.wars.append([1, 2])
        result = diplomacy.make_peace(self.state, 2, {"target_cedes": [region_id], "player_pays": 200})
        self.assertIn("冀州", self.state.player_regime["regions"])
        self.assertNotIn("冀州", self.state.regimes[2]["regions"])
        self.assertEqual(self.state.regions[region_id]["controller"], 1)
        self.assertIsNone(self.state.regions[region_id]["governor"])
        self.assertNotIn([1, 2], self.state.wars)
        self.assertIn("割让冀州", result)

    def test_peace_removes_governor_when_player_cedes_region(self):
        region_id = 1  # 扬州，法理属于玩家
        governor_id = 8
        self.state.regions[region_id]["governor"] = governor_id
        self.state.wars.append([1, 2])

        diplomacy.make_peace(self.state, 2, {"player_cedes": [region_id]})

        self.assertEqual(diplomacy.region_owner(self.state, region_id), 2)
        self.assertEqual(self.state.regions[region_id]["controller"], 2)
        self.assertIsNone(self.state.regions[region_id]["governor"])
        self.assertTrue(any("原刺史" in item and "卸任" in item for item in self.state.event_log))

    def test_eliminated_regime_is_not_a_diplomatic_target_or_reparation_payer(self):
        target_id = 7
        target_army_ids = [army.id for army in self.state.armies.values() if army.regime_id == target_id]
        self.state.regions[23]["controller"] = 1
        self.state.wars.append([1, target_id])
        with self.assertRaisesRegex(RuleError, "不能再支付赔款"):
            diplomacy.make_peace(self.state, target_id, {"target_cedes": [23], "target_pays": 100})
        diplomacy.make_peace(self.state, target_id, {"target_cedes": [23]})
        self.assertTrue(is_regime_eliminated(self.state, target_id))
        self.assertTrue(all(army_id not in self.state.armies for army_id in target_army_ids))
        with self.assertRaisesRegex(RuleError, "失去全部土地"):
            diplomacy.act(self.state, target_id, "送礼")

    def test_peace_repatriates_armies_staying_in_former_enemy_territory(self):
        target_id = 2
        player_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        target_army = next(army for army in self.state.armies.values() if army.regime_id == target_id)
        target_city = next(
            city for city in self.state.cities.values()
            if city.get("region") in self.state.regimes[target_id]["regions"]
        )
        player_city = next(
            city for city in self.state.cities.values()
            if city.get("region") in self.state.player_regime["regions"]
        )
        player_army.location_id = int(target_city["id"])
        target_army.location_id = int(player_city["id"])
        self.state.wars.append(self.state.relation_pair(1, target_id))

        result = diplomacy.make_peace(self.state, target_id, {})

        self.assertEqual(player_army.location_id, int(self.state.player_regime["capital"]))
        self.assertEqual(target_army.location_id, int(self.state.regimes[target_id]["capital"]))
        self.assertIn("遣返境外军队2支", result)

    def test_settlement_removes_armies_of_eliminated_regimes(self):
        target_id = 7
        removed_army_ids = [army.id for army in self.state.armies.values() if army.regime_id == target_id]
        surviving_army_id = next(army.id for army in self.state.armies.values() if army.regime_id != target_id)
        self.assertTrue(removed_army_ids)
        self.state.regimes[target_id]["regions"] = []

        removed = remove_eliminated_regime_armies(self.state)

        self.assertEqual(removed[target_id], removed_army_ids)
        self.assertTrue(all(army_id not in self.state.armies for army_id in removed_army_ids))
        self.assertIn(surviving_army_id, self.state.armies)
        self.assertTrue(any("灭亡政权残军清理" in item for item in self.state.event_log))

    def test_new_turn_removes_all_offices_governors_and_commanders_of_dead_people(self):
        internal = self.state.player_regime["internal"]
        dead_id = next(
            int(person["id"])
            for person in self.state.persons.values()
            if int(person.get("country_id", 0)) == self.state.player_regime_id and not person.get("is_player")
        )
        living_id = int(self.state.player["id"])
        self.state.persons[dead_id]["status"] = 4
        internal["zhongshu_ling"] = dead_id
        internal["inner_court"] = [dead_id, living_id]
        region = next(iter(self.state.regions.values()))
        region["governor"] = dead_id
        army = next(iter(self.state.armies.values()))
        army.commander = dead_id
        army.commander_locked = True
        self.state.parties[1] = {
            "id": 1,
            "name": "测试党",
            "leader": dead_id,
            "members": [dead_id, living_id],
            "supported_families": [1],
            "coup": {"leader": dead_id, "participants": [dead_id], "progress": 25},
        }

        removed = remove_dead_appointments(self.state)

        self.assertEqual(internal["zhongshu_ling"], None)
        self.assertEqual(internal["inner_court"], [living_id])
        self.assertEqual(removed["court"][self.state.player_regime_id]["zhongshu_ling"], [dead_id])
        self.assertEqual(removed["court"][self.state.player_regime_id]["inner_court"], [dead_id])
        self.assertEqual(removed["governors"][int(region["id"])], dead_id)
        self.assertEqual(removed["commanders"][int(army.id)], dead_id)
        self.assertIsNone(region["governor"])
        self.assertIsNone(army.commander)
        self.assertFalse(army.commander_locked)
        self.assertEqual(removed["party_leaders"][1], dead_id)
        self.assertIsNone(self.state.parties[1]["leader"])
        self.assertEqual(self.state.parties[1]["members"], [living_id])
        self.assertEqual(self.state.parties[1]["supported_families"], [])
        self.assertNotIn("coup", self.state.parties[1])
        self.assertTrue(any("解除已故任职者" in item for item in self.state.event_log))
        self.assertTrue(any("解除已故刺史" in item for item in self.state.event_log))
        self.assertTrue(any("解除已故将领" in item for item in self.state.event_log))
        self.assertTrue(any("清除已故政党领袖" in item for item in self.state.event_log))

    def test_dead_privileged_commander_does_not_leave_army_locked(self):
        army = next(item for item in self.state.armies.values() if item.regime_id == self.state.player_regime_id)
        dead_id = next(
            int(person["id"])
            for person in self.state.persons.values()
            if int(person.get("country_id", 0)) == self.state.player_regime_id
            and int(person.get("status", 0)) == 1
            and not person.get("is_player")
        )
        self.state.persons[dead_id]["status"] = 4
        # 模拟死亡事件先清空将领、却遗留特权法律锁定字段的旧状态。
        army.commander = None
        army.commander_locked = True

        remove_dead_appointments(self.state)

        self.assertFalse(army.commander_locked)
        assigned = {item.commander for item in self.state.armies.values() if item.commander}
        replacement = next(
            int(person["id"])
            for person in self.state.persons.values()
            if int(person.get("country_id", 0)) == self.state.player_regime_id
            and int(person.get("status", 0)) == 1
            and int(person["id"]) not in assigned
        )
        military.assign_commander(self.state, army.id, replacement)
        self.assertEqual(army.commander, replacement)

    def test_dead_confidants_are_removed_immediately(self):
        living_ids = [
            int(person["id"])
            for person in self.state.persons.values()
            if int(person.get("country_id", 0)) == self.state.player_regime_id
            and int(person.get("status", 0)) == 1
            and not person.get("is_player")
        ]
        dead_id, living_id = living_ids[:2]
        self.state.confidants[:] = [dead_id, living_id]
        self.state.persons[dead_id]["status"] = 4

        self.assertEqual(remove_dead_confidants(self.state), [dead_id])
        self.assertEqual(self.state.confidants, [living_id])
        self.assertTrue(any("清除已故亲信" in item for item in self.state.event_log))

    def test_army_creation_is_capital_only_and_uses_fixed_battalions(self):
        self.state.player_regime["reserve_army"] = max(3000, self.state.player_regime["reserve_army"])
        reserve = self.state.player_regime["reserve_army"]
        with self.assertRaisesRegex(RuleError, "只能在首都"):
            military.create_army(self.state, 1, 2, 0, {1: 1})
        army = military.create_army(self.state, 1, 1, 0, {1: 1, 3: 2})
        self.assertEqual(len(army.units), 3)
        self.assertTrue(all(unit["count"] == 1000 for unit in army.units))
        self.assertEqual(army.soldiers, 3000)
        self.assertEqual(self.state.player_regime["reserve_army"], reserve - 3000)
        with self.assertRaisesRegex(RuleError, "1 至 9 个营"):
            military.create_army(self.state, 1, 1, 0, {1: 10})

    def test_map_quick_actions_find_only_player_armies_in_city(self):
        own_army = next(army for army in self.state.armies.values() if army.regime_id == self.state.player_regime_id)
        enemy_army = next(army for army in self.state.armies.values() if army.regime_id != self.state.player_regime_id)
        enemy_army.location_id = own_army.location_id
        found = player_armies_at_city(self.state, own_army.location_id)
        self.assertIn(own_army, found)
        self.assertNotIn(enemy_army, found)

    def test_four_phases_advance_to_next_month(self):
        for _ in range(4):
            advance_phase(self.state)
        self.assertEqual(self.state.month, 11)
        self.assertEqual(self.state.phase_index, 0)
        self.assertEqual(self.state.turn_number, 2)


if __name__ == "__main__":
    unittest.main()
