from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from app.content.v1_2.economy import (
    annual_consumption,
    annual_manpower_potential,
    annual_production,
    auto_fill_vacant_offices,
    ai_standing_force_target,
    apply_battle_stability_loss,
    army_supply_capacity,
    army_supply_months,
    create_convoy,
    dismiss_governor,
    economy_data,
    executable_convoy_limit,
    executable_market_order_limit,
    executable_release_grain_limit,
    expand_warehouse,
    food_market_balance_order_threshold,
    format_resource,
    governor_kind,
    market_order,
    market_capacity,
    market_price,
    month_index,
    manpower_balance,
    manpower_capacity,
    change_manpower,
    collect_annual_manpower,
    january_market_cleanup,
    market_demand,
    population_units,
    production_tax_rate,
    recruitment_available,
    release_grain,
    region_economy,
    settle_army_supply,
    settle_ai_standing_armies,
    settle_capital_expenses,
    settle_local_governance,
    settle_local_policies,
    settle_peacetime_stability,
    settle_logistics,
    settle_migration,
    settle_month,
    settle_wei_standing_army,
    starvation_effects,
    start_market_turn,
    set_local_policy,
    tax_collection_coefficient,
    warehouse_capacity,
)
from app.content.v1_2.advisor import economic_advice, execute_economic_advice
from app.content.v1_2.scenario import load_v12_state, queue_start_of_turn_events
from app.content.v1_2.supply_units import (
    create_supply_unit,
    get_supply_unit,
    legal_supply_moves,
    march_supply_unit,
    settle_supply_units,
    supply_army,
    supply_targets,
    supply_units,
)
from app.content.v1_2 import decisions as v12_decisions, strategies as v12_strategies
from app.content.v1_2.events import apply_event_choice as apply_v12_event_choice
from app.content.v1_2.events import check_story_events, ensure_story_event_record, event_key, occurred, queue_story_event
from app.content.v1_2 import politics as v12_politics
from app.content.v1_2.ai_economy import (
    PLAN_CYCLE_MONTHS,
    WEI_STANDING_FORCE_TARGET,
    ai_economic_plan,
    choose_ai_economic_goal,
    ensure_ai_economic_goal,
    run_ai_economic_plan,
)
from app.content.v1_2.ai_military import (
    STRATEGY_CYCLE_MONTHS,
    army_readiness_strength,
    ai_attack_assessment,
    ai_military_plan,
    ai_defense_priorities,
    choose_ai_military_strategy,
    enemy_naval_threatened_cities,
    evaluate_local_military_strategies,
    ensure_ai_military_strategy,
    national_military_snapshot,
    run_ai_military_strategy,
    supply_line_health,
)
from app.rules.common import RuleError
from app.rules import ai, laws
from app.rules.ai_strategy import plan_wei_invasion
from app.rules.ai_modifiers import ai_simulated_commander_martial, recover_ai_war_support
from app.rules.economy import projected_expenses
from app.rules.military import attack, city_controller, create_army, estimate_battle_losses, is_army_surrounded, neighbors, occupy_capital_if_applicable, reinforce_army, reinforcement_need
from app.rules.military_modifiers import active_military_modifiers
from app.rules.national_modifiers import active_national_modifiers
from app.rules.turn import advance_phase, settle_turn
from app.rules.treasury import set_treasury, treasury_balance
from app.rules.diplomacy import apply_casualty_war_support_loss, declare_war, force_surrender, mark_ai_total_occupation, peace_evaluation, peace_score, queue_ai_peace_offer, reject_ai_peace_offer, region_owner
from app.save_service import load_game, save_game
from app.ui.widgets import MapView
from app.ui.dialogs import truncate_slider_value
from app.ui.status_panels import visible_family_members
from app.v11 import DEFAULT_LAWS


class V12ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v12_state()

    def set_ai_force_to_target(self, regime_id: int) -> None:
        """Test helper: satisfy a force target without invoking the removed free-rebuild rule."""
        armies = [army for army in self.state.armies.values() if army.regime_id == regime_id]
        army = armies[0]
        current = sum(item.soldiers for item in armies)
        target = ai_standing_force_target(self.state, regime_id)
        army.units[0]["count"] += max(0, target - current)
        for item in armies:
            item.supply_food = army_supply_capacity(item)

    def test_opening_uses_independent_yuanjia_state(self):
        state = self.state
        self.assertEqual((state.year, state.month), (422, 1))
        self.assertEqual(state.flags["content_version"], "1.2")
        self.assertEqual(state.person_name(state.player["id"]), "刘义符")
        self.assertEqual(treasury_balance(state), 1000)
        self.assertEqual(state.authority, 500)
        self.assertEqual(state.regimes[1]["regions"], [state.regions[i]["name"] for i in range(1, 17)])
        self.assertEqual(state.regions[14]["controller"], 1)
        self.assertEqual(len([army for army in state.armies.values() if army.regime_id == 1]), 6)
        self.assertEqual(len([army for army in state.armies.values() if army.regime_id == 2]), 6)
        self.assertEqual(state.laws, DEFAULT_LAWS)
        for region_id, record in state.flags["v12_economy"]["regions"].items():
            self.assertEqual(record["warehouse"], {"food": 20.0, "cloth": 20.0})
            self.assertEqual(record["warehouse_capacity"], 200.0)
            self.assertEqual(record["market"]["food"], min(20.0, market_capacity(state, int(region_id), "food")))
            self.assertEqual(record["market"]["cloth"], min(20.0, market_capacity(state, int(region_id), "cloth")))
        for regime_id, regime in state.regimes.items():
            if int(regime_id) != state.player_regime_id:
                self.assertEqual(regime["stability"], 100)
                self.assertEqual(regime["war_support"], 100)
                if regime.get("regions"):
                    self.assertEqual(treasury_balance(state, int(regime_id)), 1000)
        jingzhou = next(region for region in state.regions.values() if region["name"] == "荆州")
        self.assertEqual(state.person_name(int(jingzhou["governor"])), "谢晦")
        self.assertNotIn(1201, state.events)
        self.assertNotIn(1202, state.events)
        self.assertNotIn(1203, state.events)
        self.assertEqual(state.flags["pending_story_events"], [12201, 12202])
        self.assertEqual(state.events[12201]["name"], "武帝崩")
        self.assertEqual(state.events[12202]["name"], "魏窥河南")
        self.assertEqual(len(state.persons), 311)
        self.assertTrue({23, 31, 59, 61}.issubset(state.families))
        self.assertTrue({36, 42, 49, 52, 60}.isdisjoint(state.families))
        self.assertTrue(all(int(person.get("family_id") or 0) in {0, *state.families} for person in state.persons.values()))
        for family_id, family in state.families.items():
            self.assertEqual(
                family["members"],
                sorted(int(person_id) for person_id, person in state.persons.items() if int(person.get("family_id") or 0) == int(family_id)),
            )
        by_name = {state.person_name(person_id): person for person_id, person in state.persons.items()}
        self.assertEqual(int(by_name["萧惠开"]["father"]), int(by_name["萧思话"]["id"]))
        self.assertEqual(int(by_name["萧惠开"]["family_id"]), 24)
        self.assertEqual(int(by_name["刘义恭"]["family_id"]), 5)
        self.assertEqual(int(by_name["拓跋焘"]["family_id"]), 29)
        self.assertEqual(int(by_name["赫连昌"]["family_id"]), 30)
        self.assertEqual(int(state.families[23]["family_type"]), 2)

    def test_xie_hui_rebellion_waits_for_song_to_recapture_jiangling(self):
        state = self.state
        jingzhou = next(region for region in state.regions.values() if region["name"] == "荆州")
        jiangling = next(city for city in state.cities.values() if city["name"] in {"江陵", "江陵城"})
        xie_hui = next(
            person for person in state.persons.values()
            if state.person_name(int(person["id"])) == "谢晦"
        )
        shared_rebel_name = str(state.regimes[13]["name"])
        shared_rebel_regions = list(state.regimes[13].get("regions", []))

        self.assertTrue(queue_story_event(state, 10))
        rebel_id = int(state.flags["v12_xie_hui_rebel_regime_id"])
        self.assertNotEqual(rebel_id, 13)
        self.assertEqual(state.regimes[rebel_id]["name"], "谢晦叛军")
        self.assertEqual(state.regimes[13]["name"], shared_rebel_name)
        self.assertEqual(state.regimes[13].get("regions", []), shared_rebel_regions)
        self.assertEqual(int(jingzhou["controller"]), rebel_id)
        self.assertEqual(region_owner(state, int(jingzhou["id"])), rebel_id)
        self.assertIn(state.relation_pair(1, rebel_id), state.wars)
        self.assertFalse(occurred(state, 11))
        rebel_armies = [army for army in state.armies.values() if army.regime_id == rebel_id]
        self.assertEqual(len(rebel_armies), 1)
        self.assertEqual(rebel_armies[0].soldiers, 8_000)
        self.assertEqual(rebel_armies[0].commander, int(xie_hui["id"]))

        check_story_events(state)
        self.assertFalse(occurred(state, 11))
        self.assertNotEqual(int(xie_hui["status"]), 4)

        jingzhou["controller"] = 1
        check_story_events(state)
        self.assertFalse(occurred(state, 11))
        rebellion_turn = int(state.flags["v12_story_event_turns"]["10"])
        state.turn_number = rebellion_turn + 2
        check_story_events(state)
        self.assertFalse(occurred(state, 11))

        state.turn_number = rebellion_turn + 3
        check_story_events(state)
        self.assertTrue(occurred(state, 11))
        self.assertEqual(city_controller(state, int(jiangling["id"])), 1)
        self.assertEqual(region_owner(state, int(jingzhou["id"])), 1)
        self.assertEqual(int(xie_hui["status"]), 4)
        self.assertIsNone(jingzhou.get("governor"))
        self.assertNotIn(state.relation_pair(1, rebel_id), state.wars)
        self.assertFalse(any(army.regime_id == rebel_id for army in state.armies.values()))

    def test_opening_randomly_assigns_unique_high_or_royal_governors(self):
        governors = [int(self.state.regions[region_id]["governor"]) for region_id in range(1, 17)]
        self.assertEqual(len(governors), len(set(governors)))
        self.assertNotIn(int(self.state.player_regime["internal"]["emperor"]), governors)
        for person_id in governors:
            person = self.state.persons[person_id]
            family = self.state.families[int(person["family_id"])]
            self.assertEqual(int(person["country_id"]), 1)
            self.assertEqual(int(person["status"]), 1)
            self.assertIn(int(family["family_type"]), {0, 1})

    def test_vacant_offices_auto_fill_with_required_family_priorities(self):
        region = self.state.regions[1]
        region["governor"] = None
        internal = self.state.player_regime["internal"]
        internal["zhongshu_ling"] = None

        filled = auto_fill_vacant_offices(self.state)

        governor_id = int(region["governor"])
        governor_family = self.state.families[int(self.state.persons[governor_id]["family_id"])]
        self.assertEqual(int(governor_family["family_type"]), 0)
        self.assertNotIn(self.state.person_name(governor_id), {"刘义康", "刘义庆", "刘劭"})
        central_id = int(internal["zhongshu_ling"])
        central_family = self.state.families[int(self.state.persons[central_id]["family_id"])]
        self.assertEqual(int(central_family["family_type"]), 1)
        self.assertTrue(filled["governors"])
        self.assertTrue(filled["central"])

    def test_non_royal_governor_control_growth_and_cap(self):
        region_id = 1
        region = self.state.regions[region_id]
        self.state.armies.clear()
        candidates = {}
        for person_id, person in self.state.persons.items():
            family_type = int(self.state.families.get(int(person.get("family_id") or 0), {}).get("family_type", -1))
            if family_type in {1, 2} and int(person.get("status", 0)) == 1:
                candidates.setdefault(family_type, int(person_id))
        for family_type, expected_gain in ((1, 2), (2, 1)):
            region["governor"] = candidates[family_type]
            region_economy(self.state, region_id)["control"] = 69
            settle_local_governance(self.state, random.Random(1))
            self.assertEqual(region_economy(self.state, region_id)["control"], 70)
            region_economy(self.state, region_id)["control"] = 50
            settle_local_governance(self.state, random.Random(1))
            self.assertEqual(region_economy(self.state, region_id)["control"], 50 + expected_gain)

    def test_dismissing_royal_governor_costs_500_and_can_spawn_four_armies(self):
        class RevoltRoll:
            @staticmethod
            def random():
                return 0.0

        region_id = 1
        royal = next(
            int(person_id) for person_id, person in self.state.persons.items()
            if int(person.get("status", 0)) == 1
            and int(self.state.families.get(int(person.get("family_id") or 0), {}).get("family_type", -1)) == 0
            and int(person_id) != 26
        )
        self.state.regions[region_id]["governor"] = royal
        self.state.authority = 500
        before = len(self.state.armies)

        result = dismiss_governor(self.state, region_id, RevoltRoll())

        self.assertIn("起兵反叛", result)
        self.assertEqual(self.state.authority, 0)
        self.assertEqual(len(self.state.armies), before + 4)
        self.assertTrue(all(army.soldiers == 5_000 for army in sorted(self.state.armies.values(), key=lambda item: item.id)[-4:]))

    def test_unborn_people_are_hidden_from_family_genealogy_until_birth_year(self):
        liu_family = self.state.families[5]
        visible_422 = {int(person["id"]) for person in visible_family_members(self.state, liu_family)}
        self.assertNotIn(118, visible_422)  # 刘劭生于424年
        self.assertIn(109, visible_422)  # 刘义恭已经出生
        self.state.year = 424
        visible_424 = {int(person["id"]) for person in visible_family_members(self.state, liu_family)}
        self.assertIn(118, visible_424)

    def test_every_opening_regime_with_land_has_a_five_thousand_land_army(self):
        for regime_id, regime in self.state.regimes.items():
            if not regime.get("regions"):
                continue
            self.assertTrue(any(
                army.regime_id == regime_id and army.army_type == 0 and army.soldiers == 5000
                for army in self.state.armies.values()
            ))

    def test_new_emperor_immediately_loses_all_civil_offices(self):
        person_id = 26
        self.state.player_regime["internal"]["zhongshu_ling"] = person_id
        self.state.regions[1]["governor"] = person_id
        self.state.year = 424
        for month in range(1, 5):
            self.state.month = month
            queue_start_of_turn_events(self.state)
        self.assertEqual(self.state.player_regime["internal"]["emperor"], person_id)
        self.assertIsNone(self.state.player_regime["internal"]["zhongshu_ling"])
        self.assertIsNone(self.state.regions[1]["governor"])
        self.assertEqual(self.state.persons[26]["spouse"], 114)
        self.assertEqual(self.state.persons[114]["spouse"], 26)
        self.assertEqual(self.state.player_regime["internal"]["empress"], 114)

    def test_market_capacity_and_january_gentry_annexation(self):
        region_id = 1
        record = region_economy(self.state, region_id)
        record["warehouse"]["food"] = 10_000
        record["market"]["food"] = market_capacity(self.state, region_id, "food") - 1
        self.state.authority = 100
        release_grain(self.state, 1, region_id, 100)
        self.assertEqual(record["market"]["food"], market_capacity(self.state, region_id, "food"))

        for level, threshold in ((1, 5), (2, 8), (3, 10), (4, 15)):
            state = load_v12_state()
            state.laws["economy"] = level
            local = region_economy(state, region_id)
            food_keep = market_demand(state, region_id, "food") * 0.1
            cloth_keep = market_demand(state, region_id, "cloth") * 0.1
            local["market"]["food"] = food_keep + threshold * 2
            local["market"]["cloth"] = cloth_keep
            before = int(local["land"]["gentry"])
            row = january_market_cleanup(state)[region_id - 1]
            self.assertEqual(row["annexed_land"], 2)
            self.assertEqual(local["land"]["gentry"], before + 2)
            self.assertAlmostEqual(local["market"]["food"], food_keep)

    def test_liu_yilong_never_triggers_royal_governor_revolt(self):
        from app.content.v1_2.economy import _trigger_royal_revolt

        self.state.regions[1]["governor"] = 26
        before = (len(self.state.armies), list(self.state.player_regime["regions"]))
        _trigger_royal_revolt(self.state, 1, 26)
        self.assertEqual((len(self.state.armies), self.state.player_regime["regions"]), before)

    def test_wei_cavalry_receives_an_extra_twenty_percent_combat_bonus(self):
        cavalry = next(army for army in self.state.armies.values() if army.regime_id == 2 and army.pure_cavalry)
        names = {item["name"] for item in active_military_modifiers(self.state, cavalry)}
        self.assertIn("魏国尚武", names)
        self.assertIn("魏国精骑", names)

    def test_main_regime_cannot_recruit_cavalry_but_ai_can(self):
        modifiers = {item["name"] for item in active_national_modifiers(self.state)}
        self.assertIn("马政不振", modifiers)
        with self.assertRaises(RuleError):
            create_army(
                self.state,
                self.state.player_regime_id,
                int(self.state.player_regime["capital"]),
                0,
                {2: 1},
            )
        ai_army = create_army(
            self.state,
            2,
            int(self.state.regimes[2]["capital"]),
            0,
            {2: 1},
        )
        self.assertTrue(ai_army.pure_cavalry)

    def test_wei_focuses_only_on_song_until_the_first_peace(self):
        target = plan_wei_invasion(self.state)
        self.assertEqual(target, 1)
        self.assertEqual([war for war in self.state.wars if 2 in war], [self.state.relation_pair(1, 2)])
        self.state.flags.pop("v12_military_plans", None)
        plan = choose_ai_military_strategy(self.state, 2)
        self.assertEqual(plan["target_city_id"], 77)

        self.state.wars.remove(self.state.relation_pair(1, 2))
        self.state.flags["v12_wei_song_peace_concluded"] = True
        self.state.flags.pop("ai_invasion_target:2", None)
        post_peace_target = plan_wei_invasion(self.state)
        self.assertNotIn(post_peace_target, {None, 1, 12})
        self.assertTrue(self.state.at_war(2, int(post_peace_target)))

    def test_wei_waits_until_427_then_prioritizes_huxia_annexation(self):
        self.state.flags["v12_wei_song_peace_concluded"] = True
        self.state.wars.remove(self.state.relation_pair(1, 2))
        self.state.flags.pop("ai_invasion_target:2", None)
        self.state.year = 426
        self.assertNotEqual(plan_wei_invasion(self.state), 12)
        self.state.flags.pop("ai_invasion_target:2", None)
        self.state.wars[:] = [war for war in self.state.wars if 2 not in war or 12 not in war]
        self.state.year = 427
        self.assertEqual(plan_wei_invasion(self.state), 12)
        self.assertTrue(self.state.flags["v12_wei_huxia_annexation"])

    def test_ai_total_occupation_becomes_annexation_next_month(self):
        winner_id, loser_id = 2, 7
        pair = self.state.relation_pair(winner_id, loser_id)
        if pair not in self.state.wars:
            self.state.wars.append(pair)
        loser_regions = [region_id for region_id in self.state.regions if region_owner(self.state, region_id) == loser_id]
        self.assertTrue(loser_regions)
        for region_id in loser_regions:
            self.state.regions[region_id]["controller"] = winner_id
        self.assertTrue(mark_ai_total_occupation(self.state, winner_id, loser_id))
        ai.run_phase(self.state, 2)
        self.assertTrue(self.state.regimes[loser_id]["regions"])
        self.state.month += 1
        ai.run_phase(self.state, 2)
        self.assertFalse(self.state.regimes[loser_id]["regions"])
        self.assertTrue(all(region_owner(self.state, region_id) == winner_id for region_id in loser_regions))
        self.assertNotIn(pair, self.state.wars)

    def test_tax_law_save_is_preserved_and_other_laws_are_filled(self):
        self.state.laws = {"tax": 4}
        self.state.legislation = {"category": "tax", "target_level": 5, "progress": 50}
        with tempfile.TemporaryDirectory() as folder:
            path = save_game(self.state, save_dir=Path(folder))
            loaded = load_game(path)
        self.assertEqual(loaded.laws["tax"], 4)
        self.assertEqual(set(loaded.laws), set(DEFAULT_LAWS))
        self.assertEqual(loaded.legislation["category"], "tax")

    def test_old_v12_regional_copper_is_migrated_into_global_treasury(self):
        self.state.flags.pop("v12_global_treasury_migrated", None)
        self.state.player_regime["treasury"] = 100
        for region_id in self.state.regions:
            region_economy(self.state, region_id)["warehouse"].pop("copper", None)
        region_economy(self.state, 1)["warehouse"]["copper"] = 50
        ai_region_id = next(
            int(region_id)
            for region_id, region in self.state.regions.items()
            if int(region.get("controller", 0)) not in {0, self.state.player_regime_id}
        )
        region_economy(self.state, ai_region_id)["control"] = 10
        self.state.regions[ai_region_id]["control"] = 10
        with tempfile.TemporaryDirectory() as folder:
            path = save_game(self.state, save_dir=Path(folder))
            loaded = load_game(path)
        self.assertEqual(treasury_balance(loaded), 150)
        self.assertNotIn("copper", region_economy(loaded, 1)["warehouse"])
        self.assertEqual(region_economy(loaded, ai_region_id)["control"], 100)

    def test_old_market_copper_is_removed_when_loading_a_save(self):
        region_economy(self.state, 1)["market"]["copper"] = 777
        with tempfile.TemporaryDirectory() as folder:
            path = save_game(self.state, save_dir=Path(folder))
            loaded = load_game(path)
        self.assertNotIn("copper", region_economy(loaded, 1)["market"])

    def test_cash_expenses_are_paid_from_global_treasury(self):
        set_treasury(self.state, 1, 1_000)
        before = treasury_balance(self.state)
        self.state.laws["power"] = 2
        v12_politics.develop(self.state, 1)
        self.assertEqual(treasury_balance(self.state), before - 15)
        expected_salary = projected_expenses(self.state, 1)[0]
        settle_capital_expenses(self.state)
        self.assertEqual(treasury_balance(self.state), before - 15 - expected_salary)

    def test_official_salary_is_paid_only_at_january_and_july_month_end(self):
        salary = projected_expenses(self.state, 1)[0]
        set_treasury(self.state, 1, 10_000)
        before = treasury_balance(self.state)

        for month in range(1, 13):
            self.state.month = month
            settle_capital_expenses(self.state)

        self.assertEqual(treasury_balance(self.state), before - salary * 2)
        salary_logs = [line for line in self.state.event_log if "月官俸" in line]
        self.assertEqual(len(salary_logs), 2)
        self.assertTrue(any("正月官俸" in line for line in salary_logs))
        self.assertTrue(any("七月官俸" in line for line in salary_logs))

    def test_non_salary_month_has_no_official_salary_arrears_penalty(self):
        self.state.month = 2
        set_treasury(self.state, 1, 0)
        self.state.player_regime["stability"] = 80
        self.state.player_regime["war_support"] = 80

        settle_capital_expenses(self.state)

        self.assertEqual(self.state.player_regime["stability"], 80)
        self.assertEqual(self.state.player_regime["war_support"], 80)

    def test_copper_cannot_be_created_as_a_convoy_good(self):
        with self.assertRaises(RuleError):
            create_convoy(self.state, 1, 1, 2, "copper", 100)

    def test_population_ids_are_unique_and_never_derived_from_list_position(self):
        units = population_units(self.state)
        ids = [int(unit["id"]) for unit in units]
        self.assertTrue(units)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.state.flags["v12_economy"]["next_population_id"], max(ids) + 1)

    def test_failed_market_order_does_not_mutate_stock(self):
        self.state.month = 8
        self.state.authority = 0
        record = region_economy(self.state, 1)
        before = dict(record["warehouse"]), dict(record["market"])
        with self.assertRaises(RuleError):
            market_order(self.state, 1, 1, "food", "buy", 5)
        self.assertEqual((record["warehouse"], record["market"]), before)

    def test_market_uses_global_treasury_without_local_or_market_cash_pool(self):
        record = region_economy(self.state, 1)
        record["control"] = 100
        record["warehouse"].update({"cloth": 100.0})
        set_treasury(self.state, 1, 100)
        record["market"]["cloth"] = 100.0
        record["market"].pop("copper", None)
        self.state.authority = 100

        before_sale_cash = treasury_balance(self.state)
        market_order(self.state, 1, 1, "cloth", "sell", 10)
        self.assertGreater(treasury_balance(self.state), before_sale_cash)
        self.assertNotIn("copper", record["warehouse"])
        self.assertNotIn("copper", record["market"])

        before_purchase_cash = treasury_balance(self.state)
        market_order(self.state, 1, 1, "cloth", "buy", 5)
        self.assertLess(treasury_balance(self.state), before_purchase_cash)
        self.assertNotIn("copper", record["market"])

    def test_economic_adviser_recommends_and_executes_live_orders(self):
        for region_id in range(1, 17):
            record = region_economy(self.state, region_id)
            record["control"] = 100
            record["market"].update({"food": 1000.0, "cloth": 1000.0})
            record["warehouse"].update({"food": 1000.0, "cloth": 1000.0, "copper": 1000.0})
        target = region_economy(self.state, 1)
        target["market"]["food"] = 0.0
        target["warehouse"]["food"] = 100.0
        self.state.authority = 100

        advice = economic_advice(self.state)
        release = next(item for item in advice if item["kind"] == "release" and item["params"]["region_id"] == 1)
        before_food = float(target["warehouse"]["food"])
        report = execute_economic_advice(self.state, release)
        self.assertIn("经济行动报告", report)
        self.assertLess(target["warehouse"]["food"], before_food)
        self.assertEqual(self.state.authority, 90)

    def test_economic_adviser_accounts_for_remote_shortage_and_convoy_loss(self):
        for region_id in range(1, 17):
            record = region_economy(self.state, region_id)
            record["control"] = 100
            record["market"].update({"food": 1000.0, "cloth": 1000.0})
            record["warehouse"].update({"food": 1000.0, "cloth": 1000.0, "copper": 1000.0})
        target = region_economy(self.state, 1)
        target["market"]["food"] = 0.0
        target["warehouse"]["food"] = 0.0

        advice = economic_advice(self.state)
        convoy = next(item for item in advice if item["kind"] == "convoy" and item["params"]["good"] == "food")
        self.assertEqual(convoy["params"]["target_region_id"], 1)
        self.assertIn("10%损耗", convoy["reason"])

    def test_food_market_orders_share_twenty_percent_turn_cap_and_granary_is_exempt(self):
        record = region_economy(self.state, 1)
        record["control"] = 100
        record["warehouse"].update({"food": 100.0, "copper": 100.0})
        record["market"].update({"food": 20.0})
        self.state.authority = 100
        start_market_turn(self.state)
        release_grain(self.state, 1, 1, 10)
        self.assertEqual(record["market"]["food"], 30.0)
        market_order(self.state, 1, 1, "food", "sell", 10)
        # Food sales may always reach 20 units per turn even when 20% of the
        # opening market stock would be lower.
        self.assertEqual(record["market"]["food"], 40.0)
        with self.assertRaises(RuleError):
            market_order(self.state, 1, 1, "food", "buy", 1)

        self.state.turn_number += 1
        start_market_turn(self.state)
        market_order(self.state, 1, 1, "food", "buy", 20)
        self.assertAlmostEqual(record["market"]["food"], 32.0)

    def test_economic_order_plan_cannot_exceed_real_warehouse_stock(self):
        record = region_economy(self.state, 1)
        record["control"] = 75
        record["warehouse"].update({"food": 40.0, "copper": 100.0})
        record["market"]["food"] = 150.0
        self.state.authority = 100
        start_market_turn(self.state)

        with self.assertRaises(RuleError):
            market_order(self.state, 1, 1, "food", "sell", 45)
        market_order(self.state, 1, 1, "food", "sell", 40)
        self.assertEqual(record["warehouse"]["food"], 10.0)

        record["warehouse"]["food"] = 40.0
        with self.assertRaises(RuleError):
            release_grain(self.state, 1, 1, 45)
        with self.assertRaises(RuleError):
            create_convoy(self.state, 1, 1, 2, "food", 45)

    def test_market_trade_quantity_and_money_both_follow_control(self):
        region_id = 1
        record = region_economy(self.state, region_id)
        record["control"] = 50
        record["warehouse"]["cloth"] = 20
        record["market"]["cloth"] = 20
        self.state.authority = 100
        set_treasury(self.state, 1, 100)
        price = market_price(self.state, region_id, "cloth")

        purchase = market_order(self.state, 1, region_id, "cloth", "buy", 5)
        self.assertIn("实际成交：2.5", purchase)
        self.assertEqual(treasury_balance(self.state), round(100 - 2.5 * price * 1.5, 2))
        before_sale = treasury_balance(self.state)
        sale_price = market_price(self.state, region_id, "cloth")
        sale = market_order(self.state, 1, region_id, "cloth", "sell", 5)
        self.assertIn("实际成交：2.5", sale)
        self.assertEqual(treasury_balance(self.state), round(before_sale + 2.5 * sale_price * 0.5, 2))

    def test_food_trade_balance_threshold_inverts_control_efficiency(self):
        region_id = 1
        record = region_economy(self.state, region_id)
        record["control"] = 200 / 3
        demand = market_demand(self.state, region_id, "food")

        record["market"]["food"] = demand - 40
        self.assertEqual(food_market_balance_order_threshold(self.state, 1, region_id, "sell"), 60.0)
        record["market"]["food"] = demand + 40
        self.assertEqual(food_market_balance_order_threshold(self.state, 1, region_id, "buy"), 60.0)

    def test_economic_slider_limits_are_immediately_executable(self):
        region_id = 1
        record = region_economy(self.state, region_id)
        record["control"] = 50
        record["warehouse_capacity"] = 200
        record["warehouse"].update({"food": 40.0, "cloth": 80.0})
        set_treasury(self.state, 1, 100)
        record["market"]["cloth"] = market_capacity(self.state, region_id, "cloth") - 10
        self.state.authority = 100

        sell_limit = executable_market_order_limit(self.state, 1, region_id, "cloth", "sell")
        self.assertEqual(sell_limit, 20.0)
        market_order(self.state, 1, region_id, "cloth", "sell", sell_limit)

        record["market"]["food"] = market_capacity(self.state, region_id, "food") - 10
        release_limit = executable_release_grain_limit(self.state, 1, region_id)
        self.assertEqual(release_limit, 20.0)
        release_grain(self.state, 1, region_id, release_limit)

        convoy_limit = executable_convoy_limit(self.state, 1, region_id, 2, "food")
        self.assertEqual(convoy_limit, 30.0)
        create_convoy(self.state, 1, region_id, 2, "food", convoy_limit)

        self.state.authority = 0
        self.assertEqual(executable_market_order_limit(self.state, 1, region_id, "cloth", "buy"), 0.0)
        self.assertEqual(executable_release_grain_limit(self.state, 1, region_id), 0.0)
        self.assertEqual(executable_convoy_limit(self.state, 1, region_id, 2, "food"), 0.0)

    def test_local_policy_defaults_to_stockpile_and_can_transfer_surplus(self):
        self.state.month = 8
        source, capital = 2, 1
        record = region_economy(self.state, source)
        self.assertEqual(record["local_policy"], "stockpile")
        record["control"] = 100
        record["warehouse"].update({"food": 50.0, "cloth": 45.0})
        record["market"]["food"] = market_demand(self.state, source, "food")
        set_local_policy(self.state, 1, source, "transfer")

        before_ids = {int(unit["id"]) for unit in self.state.flags["v12_economy"]["logistics_units"]}
        reports = settle_local_policies(self.state)
        created = [
            unit for unit in self.state.flags["v12_economy"]["logistics_units"]
            if int(unit["id"]) not in before_ids and int(unit["source_region_id"]) == source
        ]
        self.assertEqual(record["warehouse"]["food"], 20.0)
        self.assertEqual(record["warehouse"]["cloth"], 20.0)
        self.assertEqual({unit["good"] for unit in created}, {"food", "cloth"})
        self.assertTrue(all(int(unit["target_region_id"]) == capital for unit in created))
        self.assertTrue(any("转运" in report for report in reports))

    def test_stockpile_policy_buys_cheap_surplus_without_consuming_authority(self):
        self.state.month = 8
        region_id = 2
        record = region_economy(self.state, region_id)
        record["control"] = 100
        demand = market_demand(self.state, region_id, "food")
        record["market"]["food"] = demand * 2
        record["warehouse"].update({"food": 20.0, "copper": 100.0})
        start_market_turn(self.state)
        authority = self.state.authority

        settle_local_policies(self.state)

        self.assertGreater(record["warehouse"]["food"], 20.0)
        self.assertGreaterEqual(record["market"]["food"], demand)
        self.assertEqual(self.state.authority, authority)

    def test_stockpile_policy_sells_surplus_cloth_to_finance_cheap_grain(self):
        self.state.month = 8
        region_id = 2
        record = region_economy(self.state, region_id)
        record["control"] = 100
        demand = market_demand(self.state, region_id, "food")
        record["market"]["food"] = demand * 2
        record["market"]["cloth"] = 0.0
        record["warehouse"].update({"food": 20.0, "cloth": 1.0, "copper": 0.0})
        set_local_policy(self.state, 1, region_id, "stockpile")
        start_market_turn(self.state)
        before_food = float(record["warehouse"]["food"])
        before_cloth = float(record["warehouse"]["cloth"])
        authority = self.state.authority

        reports = settle_local_policies(self.state)

        self.assertLess(record["warehouse"]["cloth"], before_cloth)
        self.assertGreater(record["warehouse"]["food"], before_food)
        self.assertLess(record["warehouse"]["cloth"], 1.0)
        self.assertLess(record["warehouse"]["cloth"], 20.0)
        self.assertGreaterEqual(record["market"]["food"], demand)
        self.assertEqual(self.state.authority, authority)
        self.assertTrue(reports)

    def test_stockpile_policy_never_buys_below_local_food_demand(self):
        self.state.month = 8
        region_id = 2
        record = region_economy(self.state, region_id)
        record["control"] = 100
        demand = market_demand(self.state, region_id, "food")
        record["market"]["food"] = demand + 1.0
        record["warehouse"].update({"food": 0.0, "cloth": 100.0, "copper": 200.0})
        set_local_policy(self.state, 1, region_id, "stockpile")
        start_market_turn(self.state)

        settle_local_policies(self.state)

        self.assertGreaterEqual(record["market"]["food"], demand)
        self.assertLessEqual(record["warehouse"]["food"], 1.0)

    def test_stockpile_purchase_never_pushes_modified_food_price_above_one(self):
        self.state.month = 8
        region_id = 2
        record = region_economy(self.state, region_id)
        record["control"] = 100
        demand = market_demand(self.state, region_id, "food")
        record["market"]["food"] = demand * 1.5
        record["warehouse"].update({"food": 0.0, "cloth": 100.0, "copper": 200.0})
        self.state.flags["v12_drought_relief"] = {"region_id": region_id, "resolved": False}
        set_local_policy(self.state, 1, region_id, "stockpile")
        start_market_turn(self.state)
        price_before = market_price(self.state, region_id, "food")

        settle_local_policies(self.state)

        self.assertLess(price_before, 1.0)
        self.assertGreater(record["warehouse"]["food"], 0.0)
        self.assertLessEqual(market_price(self.state, region_id, "food"), 1.0)

    def test_stockpile_policy_ships_only_after_warehouse_is_full(self):
        self.state.month = 8
        source = 2
        record = region_economy(self.state, source)
        record["control"] = 100
        record["warehouse"]["food"] = warehouse_capacity(self.state, source) - 1
        record["market"]["food"] = market_demand(self.state, source, "food")
        set_local_policy(self.state, 1, source, "stockpile")
        settle_local_policies(self.state)
        self.assertFalse([
            unit for unit in self.state.flags["v12_economy"]["logistics_units"]
            if int(unit.get("source_region_id", 0)) == source and unit.get("good") == "food"
        ])

        record["warehouse"]["food"] = warehouse_capacity(self.state, source)
        self.state.flags["v12_jiankang_auto_convoy"] = True
        settle_local_policies(self.state)
        convoys = [
            unit for unit in self.state.flags["v12_economy"]["logistics_units"]
            if int(unit.get("source_region_id", 0)) == source and unit.get("good") == "food"
        ]
        self.assertEqual(len(convoys), 1)
        self.assertEqual(convoys[0]["amount"], 20.0)
        self.assertIn("jiankang_transfer_warehouse", convoys[0]["modifiers"])
        self.assertEqual(record["warehouse"]["food"], warehouse_capacity(self.state, source) - 20)

    def test_jiankang_transfer_decision_cannot_bypass_stockpile_policy(self):
        source = 2
        record = region_economy(self.state, source)
        record["control"] = 100
        record["warehouse"]["food"] = 40.0
        record["market"]["food"] = market_demand(self.state, source, "food") * 2
        set_local_policy(self.state, 1, source, "stockpile")
        self.state.flags["v12_jiankang_auto_convoy"] = True
        self.state.month = 7

        settle_month(self.state, random.Random(7))

        self.assertFalse([
            unit for unit in self.state.flags["v12_economy"]["logistics_units"]
            if int(unit.get("source_region_id", 0)) == source
            and unit.get("good") == "food"
            and "jiankang_transfer_warehouse" in unit.get("modifiers", [])
        ])

    def test_stop_local_policy_performs_no_automatic_action(self):
        self.state.month = 8
        region_id = 2
        record = region_economy(self.state, region_id)
        record["control"] = 100
        record["warehouse"].update({"food": 200.0, "cloth": 150.0, "copper": 100.0})
        record["market"]["food"] = market_demand(self.state, region_id, "food") * 2
        set_local_policy(self.state, 1, region_id, "stop")
        before_warehouse = dict(record["warehouse"])
        before_market = dict(record["market"])
        before_logistics = list(self.state.flags["v12_economy"]["logistics_units"])

        settle_local_policies(self.state)

        self.assertEqual(record["warehouse"], before_warehouse)
        self.assertEqual(record["market"], before_market)
        self.assertEqual(self.state.flags["v12_economy"]["logistics_units"], before_logistics)

    def test_local_policies_only_execute_from_august_through_november(self):
        region_id = 2
        record = region_economy(self.state, region_id)
        record["control"] = 100
        demand = market_demand(self.state, region_id, "food")
        record["market"]["food"] = max(0.0, demand - 20.0)
        record["warehouse"].update({"food": 100.0, "cloth": 100.0, "copper": 0.0})
        set_local_policy(self.state, 1, region_id, "stockpile")

        for month in (1, 2, 3, 4, 5, 6, 7, 12):
            self.state.month = month
            before_warehouse = dict(record["warehouse"])
            before_market = dict(record["market"])
            self.assertEqual(settle_local_policies(self.state), [])
            self.assertEqual(record["warehouse"], before_warehouse)
            self.assertEqual(record["market"], before_market)

        self.state.month = 8
        start_market_turn(self.state)
        self.assertTrue(settle_local_policies(self.state))
        self.assertGreater(record["market"]["food"], max(0.0, demand - 20.0))

    def test_strategy_auto_price_stabilization_obeys_august_november_hard_gate(self):
        region_id = 2
        record = region_economy(self.state, region_id)
        record["warehouse"]["food"] = 100.0
        record["market"]["food"] = 0.0
        record["local_policy"] = "stop"
        self.state.flags["v12_strategy_effect:14"] = True
        self.state.armies.clear()
        self.state.flags["v12_economy"]["logistics_units"] = []

        self.state.month = 1
        settle_month(self.state, random.Random(1))
        self.assertEqual(record["warehouse"]["food"], 100.0)
        self.assertEqual(record["market"]["food"], 0.0)

        self.state.month = 8
        settle_month(self.state, random.Random(8))
        self.assertLess(record["warehouse"]["food"], 100.0)
        self.assertGreater(record["market"]["food"], 0.0)

    def test_official_price_stabilization_decision_cannot_bypass_month_gate(self):
        v12_strategies.ensure_strategy_records(self.state)
        self.state.strategies[14]["status"] = "completed"
        self.state.month = 7
        allowed, reason = v12_decisions.decision_available(self.state, 12)
        self.assertFalse(allowed)
        self.assertIn("八月至十一月", reason)

        self.state.month = 8
        allowed, _reason = v12_decisions.decision_available(self.state, 12)
        self.assertTrue(allowed)

    def test_first_northern_expedition_creates_auxiliary_army_at_huaiyang(self):
        v12_strategies.ensure_strategy_records(self.state)
        self.state.strategies[24]["status"] = "completed"
        self.state.wars = [war for war in self.state.wars if war != self.state.relation_pair(1, 2)]
        huaiyang = next(city for city in self.state.cities.values() if city["name"] == "淮阳")

        v12_decisions.execute_decision(self.state, 15)

        expedition_armies = [
            self.state.armies[int(army_id)]
            for army_id in self.state.flags["v12_northern_armies"]
        ]
        self.assertEqual(len(expedition_armies), 2)
        self.assertEqual(expedition_armies[1].location_id, int(huaiyang["id"]))
        self.assertEqual(expedition_armies[1].soldiers, 4_000)
        self.assertIn(15, self.state.flags["completed_decisions"])

    def test_active_local_policies_sell_reserves_to_correct_market_shortages(self):
        for mode in ("stockpile", "tax", "transfer"):
            with self.subTest(mode=mode):
                state = load_v12_state()
                state.month = 8
                region_id = 2
                record = region_economy(state, region_id)
                record["control"] = 100
                food_demand = market_demand(state, region_id, "food")
                cloth_demand = market_demand(state, region_id, "cloth")
                record["market"].update({
                    "food": max(0.0, food_demand - 5.0),
                    "cloth": max(0.0, cloth_demand - 3.0),
                })
                record["warehouse"].update({"food": 50.0, "cloth": 50.0, "copper": 0.0})
                set_local_policy(state, 1, region_id, mode)
                start_market_turn(state)

                reports = settle_local_policies(state)

                self.assertGreaterEqual(record["market"]["food"], food_demand)
                self.assertGreaterEqual(record["market"]["cloth"], cloth_demand)
                self.assertTrue(reports)

    def test_supply_column_creation_is_limited_by_stock_and_control(self):
        record = region_economy(self.state, 1)
        record["control"] = 75
        record["warehouse"]["food"] = 40.0
        with self.assertRaises(RuleError):
            create_supply_unit(self.state, 1, 1, 45)

        unit = create_supply_unit(self.state, 1, 1, 40)
        self.assertEqual(unit["food"], 30.0)
        self.assertEqual(record["warehouse"]["food"], 10.0)
        self.assertEqual(unit["location_id"], 1)

    def test_supply_column_moves_like_land_army_and_supplies_adjacent_army(self):
        record = region_economy(self.state, 1)
        record["control"] = 100
        record["warehouse"]["food"] = 100.0
        unit = create_supply_unit(self.state, 1, 1, 50)
        target_army = self.state.armies[4]
        target_army.location_id = 2
        target_army.supply_food = 0.0

        targets = dict(supply_targets(self.state, int(unit["id"])))
        self.assertIn(target_army.id, targets)
        supply_army(self.state, int(unit["id"]), target_army.id, 3.0)
        self.assertEqual(target_army.supply_food, 3.0)
        self.assertEqual(get_supply_unit(self.state, int(unit["id"]))["food"], 47.0)

        moves = legal_supply_moves(self.state, int(unit["id"]))
        self.assertTrue(any(city_id == 2 for city_id, _road_type, _cost in moves))
        march_supply_unit(self.state, int(unit["id"]), 2)
        self.assertEqual(get_supply_unit(self.state, int(unit["id"]))["location_id"], 2)

    def test_supply_column_monthly_consumption_expiry_and_looting(self):
        record = region_economy(self.state, 1)
        record["control"] = 100
        record["warehouse"]["food"] = 200.0
        unit = create_supply_unit(self.state, 1, 1, 100)
        unit["action_points"] = 0.0
        settle_supply_units(self.state)
        unit = get_supply_unit(self.state, int(unit["id"]))
        self.assertEqual(unit["food"], 90.0)
        self.assertEqual(unit["age"], 1)
        self.assertEqual(unit["action_points"], 1.0)

        unit["age"] = 11
        settle_supply_units(self.state)
        self.assertFalse(supply_units(self.state, 1))

        record["warehouse"]["food"] = 100.0
        looted = create_supply_unit(self.state, 1, 1, 50)
        enemy = next(army for army in self.state.armies.values() if army.regime_id == 2)
        looted["location_id"] = enemy.location_id
        enemy_capital = int(self.state.regimes[2]["capital"])
        enemy_region = int(self.state.cities[enemy_capital]["region_id"])
        enemy_store = region_economy(self.state, enemy_region)["warehouse"]
        enemy_store["food"] = 0.0
        settle_supply_units(self.state)
        self.assertFalse(supply_units(self.state, 1))
        self.assertEqual(enemy_store["food"], 45.0)

    def test_recruitment_consumes_persistent_manpower_and_copper(self):
        self.assertGreaterEqual(recruitment_available(self.state, 1), 1000)
        before_reserve = int(self.state.player_regime.get("reserve_army", 0))
        before_manpower = manpower_balance(self.state, 1)
        before_copper = treasury_balance(self.state, 1)
        create_army(self.state, 1, 1, 0, {1: 1})
        self.assertEqual(self.state.player_regime.get("reserve_army", 0), before_reserve)
        self.assertEqual(manpower_balance(self.state, 1), before_manpower - 1000)
        self.assertEqual(treasury_balance(self.state, 1), before_copper - 3)
        create_army(self.state, 1, 1, 0, {1: 1})
        self.assertEqual(manpower_balance(self.state, 1), before_manpower - 2000)

    def test_nine_battalion_army_costs_twenty_seven_copper(self):
        before_manpower = manpower_balance(self.state, 1)
        before_copper = treasury_balance(self.state, 1)

        create_army(self.state, 1, 1, 0, {1: 9})

        self.assertEqual(manpower_balance(self.state, 1), before_manpower - 9_000)
        self.assertEqual(treasury_balance(self.state, 1), before_copper - 27)

    def test_reinforcement_restores_original_establishment_using_manpower(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        army.units[0]["count"] -= 600
        self.assertEqual(reinforcement_need(army), 600)
        before = manpower_balance(self.state, 1)

        reinforce_army(self.state, army.id)

        self.assertEqual(reinforcement_need(army), 0)
        self.assertEqual(manpower_balance(self.state, 1), before - 600)

    def test_surrounded_army_cannot_receive_reinforcements(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == 1 and army.army_type == 0)
        army.units[0]["count"] -= 500
        exits = [city_id for city_id, _road in neighbors(self.state, army.location_id)]
        enemies = [other for other in self.state.armies.values() if other.regime_id == 2]
        self.assertGreaterEqual(len(enemies), len(exits))
        for enemy, city_id in zip(enemies, exits):
            enemy.location_id = city_id

        self.assertTrue(is_army_surrounded(self.state, army.id))
        with self.assertRaisesRegex(RuleError, "被包围"):
            reinforce_army(self.state, army.id)
        self.assertEqual(reinforcement_need(army), 500)

    def test_ai_reinforces_strategic_position_before_less_important_low_morale_army(self):
        state = load_v12_state()
        state.flags["difficulty"] = "normal"
        capital = int(state.regimes[2]["capital"])
        capital_region = int(state.cities[capital]["region_id"])
        secondary = next(
            int(city_id) for city_id, city in state.cities.items()
            if int(city.get("region_id", 0)) == capital_region
            and int(city_id) != capital
            and not city.get("capital")
            and int(city.get("defense", 0)) < 60
        )
        wei_armies = [army for army in state.armies.values() if army.regime_id == 2]
        important, low_morale = wei_armies[:2]
        important.location_id = capital
        important.morale = 50
        important.units[0]["count"] -= 500
        low_morale.location_id = secondary
        low_morale.morale = 10
        low_morale.units[0]["count"] -= 500
        data = economy_data(state)
        data["manpower_initialized"] = True
        data.setdefault("manpower", {})["2"] = 400

        actions = run_ai_military_strategy(state, 2, random.Random(7))

        self.assertEqual(reinforcement_need(important), 0)
        self.assertEqual(reinforcement_need(low_morale), 500)
        self.assertIn(f"reinforce:{important.id}:500:manpower=400", actions)

    def test_ai_rewards_lowest_morale_army_when_positions_are_equally_important(self):
        state = load_v12_state()
        capital = int(state.regimes[2]["capital"])
        armies = [army for army in state.armies.values() if army.regime_id == 2][:2]
        armies[0].location_id = capital
        armies[1].location_id = capital
        armies[0].morale = 40
        armies[1].morale = 20
        capital_region = int(state.cities[capital]["region_id"])
        region_economy(state, capital_region)["warehouse"]["food"] = 1.0

        actions = run_ai_military_strategy(state, 2, random.Random(11))

        self.assertEqual(armies[1].morale, 50)
        self.assertEqual(armies[0].morale, 40)
        self.assertTrue(any(action.startswith(f"restore_morale:{armies[1].id}:") for action in actions))

    def test_july_manpower_uses_population_control_and_war_support(self):
        state = load_v12_state()
        state.player_regime["war_support"] = 50
        expected = annual_manpower_potential(state, 1)
        before = manpower_balance(state, 1)

        gains = collect_annual_manpower(state)
        repeated = collect_annual_manpower(state)

        self.assertEqual(gains[1], expected)
        self.assertEqual(repeated[1], expected)
        self.assertEqual(manpower_balance(state, 1), before + expected)

    def test_manpower_growth_and_pool_are_halved_to_ten_and_twenty_per_population_unit(self):
        for region in self.state.regions.values():
            if int(region.get("controller", 0)) == 1:
                region_economy(self.state, int(region["id"]))["control"] = 100
        self.state.player_regime["war_support"] = 100
        economy_data(self.state).setdefault("recruitment_bonus", {})["1"] = 0
        population = sum(
            len(population_units(self.state, int(region["id"])))
            for region in self.state.regions.values()
            if int(region.get("controller", 0)) == 1
        )
        self.assertEqual(annual_manpower_potential(self.state, 1), population * 10)
        self.assertEqual(manpower_capacity(self.state, 1), population * 20)

        capacity = manpower_capacity(self.state, 1)
        economy_data(self.state).setdefault("manpower", {})["1"] = capacity + 500

        self.assertEqual(manpower_balance(self.state, 1), capacity)
        self.assertEqual(change_manpower(self.state, 1, 500), capacity)

    def test_war_declaration_requires_fifty_support_and_boosts_defender(self):
        target_id = 7
        pair = self.state.relation_pair(1, target_id)
        self.state.wars[:] = [war for war in self.state.wars if war != pair]
        self.state.player_regime["war_support"] = 49
        self.state.regimes[target_id]["war_support"] = 30
        with self.assertRaisesRegex(RuleError, "低于50"):
            declare_war(self.state, 1, target_id)

        self.state.player_regime["war_support"] = 50
        declare_war(self.state, 1, target_id)

        self.assertIn(pair, self.state.wars)
        self.assertEqual(self.state.regimes[target_id]["war_support"], 50)

    def test_ai_casualty_support_discount_depends_on_difficulty(self):
        expected_losses = {"easy": 3, "normal": 2, "hard": 1}
        for difficulty, expected_loss in expected_losses.items():
            state = load_v12_state()
            state.flags["difficulty"] = difficulty
            state.regimes[2]["war_support"] = 100
            actual = apply_casualty_war_support_loss(state, 2, 5_000)
            self.assertEqual(actual, expected_loss)
            self.assertEqual(state.regimes[2]["war_support"], 100 - expected_loss)

    def test_support_below_twenty_forces_land_settlement(self):
        self.state.regions[13]["controller"] = 2  # 魏侵占宋国中原
        self.state.regions[17]["controller"] = 1  # 宋侵占魏国冀州
        self.state.regimes[2]["war_support"] = 19
        pair = self.state.relation_pair(1, 2)
        if pair not in self.state.wars:
            self.state.wars.append(pair)

        self.assertTrue(force_surrender(self.state, 2))

        self.assertEqual(self.state.regions[13]["controller"], 1)
        self.assertEqual(region_owner(self.state, 17), 1)
        self.assertNotIn(pair, self.state.wars)

    def test_monthly_treasury_deficit_reduces_central_stability_and_support(self):
        set_treasury(self.state, 1, 0)
        self.state.player_regime["stability"] = 80
        self.state.player_regime["war_support"] = 80

        settle_capital_expenses(self.state)

        self.assertEqual(self.state.player_regime["stability"], 77)
        self.assertEqual(self.state.player_regime["war_support"], 77)

    def test_battle_reduces_local_stability_by_ten(self):
        before = int(region_economy(self.state, 13)["stability"])
        apply_battle_stability_loss(self.state, 77)
        self.assertEqual(region_economy(self.state, 13)["stability"], max(0, before - 10))

    def test_424_coup_changes_player_and_era(self):
        self.state.year = 424
        queued = []
        for month in range(1, 5):
            self.state.month = month
            queued.extend(queue_start_of_turn_events(self.state))
        self.assertIn(7, queued)
        self.assertTrue(occurred(self.state, 7))
        self.assertEqual(self.state.person_name(self.state.player["id"]), "刘义隆")
        self.assertEqual(self.state.flags["era_name"], "元嘉")
        self.assertEqual(self.state.persons[24]["status"], 4)

    def test_v12_story_pack_has_documented_strategies_and_decisions(self):
        self.assertEqual(len(v12_strategies.STRATEGY_TEMPLATES), 31)
        self.assertEqual(len(v12_decisions.DECISION_TEMPLATES), 18)
        self.assertTrue(all(int(person.get("opinion_of_player", 0)) == 30 for person in self.state.persons.values()))
        v12_strategies.ensure_strategy_records(self.state)
        self.assertTrue(v12_strategies.strategy_available(self.state, 1)[0])

    def test_northern_expedition_council_only_shows_the_applicable_text_branch(self):
        queue_story_event(self.state, 15)
        normal_text = self.state.events[event_key(15)]["text"]
        self.assertIn("北伐的事，今日定下来", normal_text)
        self.assertNotIn("若到彦之", normal_text)
        self.assertNotIn("---", normal_text)
        self.assertNotIn("北伐之事，再议吧", normal_text)

        unavailable = load_v12_state()
        for name in ("到彦之", "王玄谟", "檀道济"):
            person = next(
                person for person in unavailable.persons.values()
                if unavailable.person_name(int(person["id"])) == name
            )
            person["status"] = 4
        queue_story_event(unavailable, 15)
        alternate_text = unavailable.events[event_key(15)]["text"]
        self.assertIn("北伐之事，再议吧", alternate_text)
        self.assertNotIn("若到彦之", alternate_text)
        self.assertNotIn("---", alternate_text)
        self.assertNotIn("北伐的事，今日定下来", alternate_text)

    def test_yuanjia_scenario_settles_at_the_end_of_433_and_blocks_further_turns(self):
        self.state.year = 433
        self.state.month = 12
        self.state.phase_index = len(self.state.phase_names) - 1

        settle_turn(self.state)

        self.assertEqual(
            self.state.flags.get("v13_transition_ready"),
            {"source": "yuanjia_governance", "target": "wenjiao_south", "year": 433},
        )
        self.assertEqual((self.state.year, self.state.month), (434, 1))
        frozen = (self.state.year, self.state.month, self.state.phase_index, self.state.turn_number)
        message = advance_phase(self.state)
        self.assertEqual(
            (self.state.year, self.state.month, self.state.phase_index, self.state.turn_number),
            frozen,
        )
        self.assertIn("必须先保存", message)

    def test_loading_a_legacy_january_434_save_restores_the_missing_transition(self):
        self.state.year = 434
        self.state.month = 1
        self.state.flags.pop("v13_transition_ready", None)
        with tempfile.TemporaryDirectory() as folder:
            path = save_game(self.state, save_dir=Path(folder))
            loaded = load_game(path)
        self.assertEqual(
            loaded.flags.get("v13_transition_ready"),
            {"source": "yuanjia_governance", "target": "wenjiao_south", "year": 433},
        )

    def test_retired_royal_power_event_is_removed_from_legacy_saves(self):
        ensure_story_event_record(self.state, 14, choices=["暂不处理"])
        self.state.flags.setdefault("v12_story_events", []).append(14)
        self.state.flags.setdefault("v12_story_event_turns", {})["14"] = self.state.turn_number
        self.state.flags.setdefault("pending_story_events", []).append(event_key(14))

        check_story_events(self.state)

        self.assertFalse(occurred(self.state, 14))
        self.assertNotIn(event_key(14), self.state.events)
        self.assertNotIn(event_key(14), self.state.flags["pending_story_events"])
        self.assertFalse(queue_story_event(self.state, 14, choices=["暂不处理"]))
        with self.assertRaisesRegex(ValueError, "已经移除"):
            apply_v12_event_choice(self.state, event_key(14), "暂不处理")

    def test_event_19_occurs_only_in_december_431_when_song_controls_central_plains(self):
        central = next(region for region in self.state.regions.values() if region["name"] == "中原地区")
        self.state.year = 431
        self.state.month = 12
        central["controller"] = self.state.player_regime_id

        check_story_events(self.state)

        self.assertTrue(occurred(self.state, 19))
        self.assertFalse(occurred(self.state, 18))

    def test_event_18_occurs_from_january_432_when_event_19_did_not_happen(self):
        central = next(region for region in self.state.regions.values() if region["name"] == "中原地区")
        self.state.year = 431
        self.state.month = 12
        central["controller"] = 2
        check_story_events(self.state)
        self.assertFalse(occurred(self.state, 18))
        self.assertFalse(occurred(self.state, 19))

        self.state.year = 432
        self.state.month = 1
        check_story_events(self.state)

        self.assertTrue(occurred(self.state, 18))
        self.assertFalse(occurred(self.state, 19))

    def test_wei_offers_peace_only_in_diplomacy_and_rejection_expands_war(self):
        self.state.regions[13]["controller"] = 2
        self.state.flags["pending_story_events"] = []
        self.assertNotIn(12202, queue_start_of_turn_events(self.state))
        self.assertFalse(self.state.events[12202].get("peace_offer", False))
        ai.run_phase(self.state, 2)
        self.assertTrue(self.state.events[12202]["peace_offer"])
        self.assertIn(12202, self.state.flags["pending_story_events"])
        from app.content.v1_2.scenario import apply_event_choice

        before_ids = set(self.state.armies)
        result = apply_event_choice(self.state, 12202, "拒绝议和")
        self.assertIn("魏军", result)
        self.assertTrue(self.state.flags["v12_wei_war_expanded"])
        reinforcements = [self.state.armies[army_id] for army_id in set(self.state.armies) - before_ids]
        self.assertEqual(len(reinforcements), 5)
        self.assertTrue(all(army.regime_id == 2 and army.location_id == 77 for army in reinforcements))
        self.assertTrue(all(army.soldiers == 5000 and all(unit["type"] == 1 for unit in army.units) for army in reinforcements))
        self.assertTrue(all(army.supply_food == army_supply_capacity(army) for army in reinforcements))
        army_count = len(self.state.armies)
        apply_event_choice(self.state, 12202, "拒绝议和")
        self.assertEqual(len(self.state.armies), army_count)
        for army in self.state.armies.values():
            if army.regime_id == 1:
                army.location_id = 1
        wei_armies = [army for army in self.state.armies.values() if army.regime_id == 2]
        for army in wei_armies[1:]:
            self.state.armies.pop(army.id)
        wei_armies[0].location_id = 77
        wei_armies[0].action_points = wei_armies[0].max_action_points
        ai.military_actions(self.state, 2)
        self.assertEqual(wei_armies[0].location_id, 77)
        self.assertEqual(ai_military_plan(self.state, 2)["kind"], "consolidate")

    def test_old_rejected_save_receives_wei_infantry_reinforcements_once(self):
        self.state.flags["v12_wei_peace_rejected"] = True
        self.state.flags.pop("v12_wei_rejection_reinforcements", None)
        before = len(self.state.armies)
        queue_start_of_turn_events(self.state)
        self.assertEqual(len(self.state.armies), before + 5)
        queue_start_of_turn_events(self.state)
        self.assertEqual(len(self.state.armies), before + 5)

    def test_four_phases_use_v12_settlement(self):
        for _ in range(4):
            advance_phase(self.state)
        self.assertEqual((self.state.year, self.state.month, self.state.phase_index), (422, 2, 0))
        self.assertIn("v12_economy", self.state.flags)

    def test_open_granary_moves_free_food_to_market_in_any_month(self):
        self.state.month = 1
        self.state.authority = 100
        record = region_economy(self.state, 1)
        record["control"] = 100
        before_warehouse = float(record["warehouse"]["food"])
        before_market = float(record["market"]["food"])
        report = release_grain(self.state, 1, 1, 5)
        self.assertEqual(record["warehouse"]["food"], before_warehouse - 5)
        self.assertEqual(record["market"]["food"], before_market + 5)
        self.assertEqual(self.state.authority, 90)
        self.assertIn("实际投放：5", report)
        self.assertIn("粮食损耗：0", report)

    def test_economic_action_reports_show_actual_unfinished_and_cash_result(self):
        record = region_economy(self.state, 1)
        record["control"] = 50
        record["warehouse"].update({"food": 100.0, "cloth": 100.0})
        set_treasury(self.state, 1, 100)
        before_copper = treasury_balance(self.state)
        self.state.authority = 100
        release_report = release_grain(self.state, 1, 1, 10)
        self.assertIn("计划投放：10", release_report)
        self.assertIn("实际投放：5", release_report)
        self.assertIn("未投放：5", release_report)
        trade_report = market_order(self.state, 1, 1, "cloth", "sell", 10)
        self.assertIn("实际成交：5", trade_report)
        self.assertIn("未成交：5", trade_report)
        self.assertIn("控制度导致未执行：5", trade_report)
        self.assertIn("收入×0.5", trade_report)
        self.assertIn("获得铜钱：", trade_report)
        self.assertGreater(treasury_balance(self.state), before_copper)
        self.assertNotIn("copper", record["market"])
        convoy_report = create_convoy(self.state, 1, 1, 2, "food", 10)
        self.assertIn("实际装运：5", convoy_report)
        self.assertIn("未装运：5", convoy_report)
        self.assertIn("在途每次结算另损耗当前货物10%", convoy_report)

    def test_famine_scales_linearly_in_december_instead_of_killing_the_entire_gap(self):
        self.assertEqual(starvation_effects(100, 50), (0.5, 20, 50))
        self.assertEqual(starvation_effects(100, 25), (0.25, 10, 25))
        region_id = 1
        units = population_units(self.state, region_id)
        population = len(units)
        record = region_economy(self.state, region_id)
        record["market"]["food"] = population / 2
        record["stability"] = 100
        consumption = annual_consumption(self.state)
        row = next(item for item in consumption if item["region_id"] == region_id)
        expected_deaths = int(population * 0.20 + 0.5)
        self.assertEqual(row["deaths"], expected_deaths)
        self.assertEqual(row["stability_loss"], 50)
        self.assertEqual(len(population_units(self.state, region_id)), population - expected_deaths)
        self.assertEqual(record["stability"], 50)

    def test_population_consumption_runs_in_december_not_september(self):
        for region_id in self.state.regions:
            region_economy(self.state, region_id)["market"]["food"] = 10_000
            region_economy(self.state, region_id).pop("last_consumption", None)
        self.state.month = 9
        settle_month(self.state, random.Random(1))
        self.assertNotIn("last_consumption", region_economy(self.state, 1))
        self.state.month = 12
        settle_month(self.state, random.Random(1))
        self.assertIn("last_consumption", region_economy(self.state, 1))

    def test_land_shortage_reduces_migration_chance_by_ninety_percent(self):
        class FixedRandom:
            @staticmethod
            def random():
                return 0.01

        def prepare(land: int):
            state = load_v12_state()
            source, target = 1, 2
            source_capital = next(city["id"] for city in state.cities.values() if city.get("region_id") == source and city.get("capital"))
            target_capital = next(city["id"] for city in state.cities.values() if city.get("region_id") == target and city.get("capital"))
            state.roads = [{"from": source_capital, "to": target_capital, "type": 1}]
            for region_id in state.regions:
                region_economy(state, region_id)["stability"] = 50
            region_economy(state, source)["stability"] = 0
            region_economy(state, target)["stability"] = 100
            region_economy(state, target)["land"] = {"gentry": land, "smallholder": 0, "self_farm": 0}
            return state, source

        crowded, source = prepare(0)
        crowded_before = len(population_units(crowded, source))
        settle_migration(crowded, FixedRandom())
        self.assertEqual(len(population_units(crowded, source)), crowded_before)

        spacious, source = prepare(100_000)
        spacious_before = len(population_units(spacious, source))
        target_stability = int(region_economy(spacious, 2)["stability"])
        settle_migration(spacious, FixedRandom())
        self.assertGreater(spacious_before, 0)
        self.assertEqual(len(population_units(spacious, source)), 0)
        self.assertEqual(region_economy(spacious, 2)["stability"], max(0, target_stability - spacious_before))

    def test_economy_law_uses_original_in_kind_tax_coefficients(self):
        record = region_economy(self.state, 1)
        record["land"] = {"gentry": 10, "smallholder": 0, "self_farm": 0}
        expected = {1: (0.2, 0.03), 2: (0.4, 0.06), 3: (0.5, 0.075), 4: (0.5, 0.075), 5: (0.5, 0.075)}
        for level, (coefficient, rate) in expected.items():
            self.state.laws["economy"] = level
            self.assertEqual(tax_collection_coefficient(self.state, 1), coefficient)
            self.assertEqual(production_tax_rate(self.state, 1), rate)

    def test_tax_coefficient_only_splits_output_and_does_not_reduce_production(self):
        class NormalWeather:
            @staticmethod
            def random():
                return 0.999

            @staticmethod
            def choice(options):
                if options and isinstance(options[0], tuple) and options[0][0] in {"洪涝", "干旱", "正常", "丰收"}:
                    return ("正常", 1.0)
                return options[0]

        before = {
            region_id: (
                float(region_economy(self.state, region_id)["warehouse"]["food"]),
                float(region_economy(self.state, region_id)["market"]["food"]),
            )
            for region_id in self.state.regions
        }
        report = annual_production(self.state, NormalWeather())
        for row in report:
            warehouse_before, market_before = before[int(row["region_id"])]
            record = region_economy(self.state, int(row["region_id"]))
            added = (
                float(record["warehouse"]["food"]) - warehouse_before
                + float(record["market"]["food"]) - market_before
            )
            self.assertAlmostEqual(
                added,
                float(row["food"]) + float(row["ai_food_income_bonus"]),
                places=2,
            )
            self.assertAlmostEqual(
                float(row["food_tax_rate"]),
                0.15 * float(row["tax_collection_coefficient"]),
                places=4,
            )
        self.assertLess(sum(bool(row["shortage"]) for row in report), len(report))

    def test_ai_gets_difficulty_scaled_food_and_cloth_income_outside_production(self):
        class NormalWeather:
            @staticmethod
            def random():
                return 0.999

            @staticmethod
            def choice(options):
                if options and isinstance(options[0], tuple):
                    return ("正常", 1.0)
                return options[0]

        expected_rates = {"easy": 1.0, "normal": 2.0, "hard": 3.0}
        for difficulty, expected_rate in expected_rates.items():
            state = load_v12_state()
            state.flags["difficulty"] = difficulty
            ai_region_id = next(
                region_id for region_id, region in state.regions.items()
                if int(region.get("controller", 0)) == 2
            )
            player_region_id = next(
                region_id for region_id, region in state.regions.items()
                if int(region.get("controller", 0)) == state.player_regime_id
            )
            for region_id in (ai_region_id, player_region_id):
                region_economy(state, region_id)["warehouse"].update({"food": 0.0, "cloth": 0.0})

            report = {row["region_id"]: row for row in annual_production(state, NormalWeather())}
            ai_row = report[ai_region_id]
            player_row = report[player_region_id]
            normal_food_tax = round(float(ai_row["food"]) * float(ai_row["food_tax_rate"]), 2)
            expected_food_bonus = min(
                round(normal_food_tax * expected_rate, 2),
                warehouse_capacity(state, ai_region_id) - normal_food_tax,
            )
            normal_cloth_tax = round(
                float(ai_row["cloth"])
                * production_tax_rate(state, ai_region_id, "cloth"),
                2,
            )
            expected_cloth_bonus = min(
                round(normal_cloth_tax * expected_rate, 2),
                warehouse_capacity(state, ai_region_id) - normal_cloth_tax,
            )
            self.assertAlmostEqual(ai_row["ai_food_income_bonus"], expected_food_bonus, places=2)
            self.assertAlmostEqual(ai_row["ai_cloth_income_bonus"], expected_cloth_bonus, places=2)
            self.assertEqual(player_row["ai_food_income_bonus"], 0.0)
            self.assertEqual(player_row["ai_cloth_income_bonus"], 0.0)

    def test_economy_legislation_uses_shared_vote_and_progress_rules(self):
        for person in laws.top_legislators(self.state):
            person["ideology"] = 2
            person["opinion_of_player"] = 100
        result = laws.propose_legislation(self.state, "economy", 2)
        self.assertIn("投票通过", result)
        self.state.authority = 1000
        for _ in range(4):
            laws.settle_legislation(self.state)
        laws.enact_ready_legislation(self.state)
        self.assertEqual(self.state.laws["economy"], 2)

    def test_land_investigation_targets_one_family_but_reduces_aggregate_gentry_land(self):
        self.state.laws["economy"] = 2
        self.state.laws["power"] = 2
        self.state.authority = 1000
        family = next(
            family
            for family in self.state.families.values()
            if family.get("leader") and int(family["leader"]) in self.state.persons
        )
        leader = self.state.persons[int(family["leader"])]
        before_opinion = int(leader.get("opinion_of_player", 0))
        before_gentry = sum(int(region_economy(self.state, region_id)["land"]["gentry"]) for region_id in range(1, 17))
        laws.land_investigation(self.state, int(family["id"]))
        after_gentry = sum(int(region_economy(self.state, region_id)["land"]["gentry"]) for region_id in range(1, 17))
        self.assertLess(after_gentry, before_gentry)
        self.assertEqual(leader["opinion_of_player"], max(-100, before_opinion - 30))

    def test_logistics_lose_ten_percent_and_can_be_looted_on_current_tile(self):
        data = economy_data(self.state)
        player_capital = int(self.state.player_regime["capital"])
        enemy = next(army for army in self.state.armies.values() if army.regime_id == 2)
        enemy.location_id = player_capital
        enemy_region = int(self.state.cities[int(self.state.regimes[2]["capital"])]["region_id"])
        before = float(region_economy(self.state, enemy_region)["warehouse"]["food"])
        data["logistics_units"] = [{
            "id": 999,
            "kind": "official",
            "regime_id": 1,
            "source_region_id": 1,
            "target_region_id": 2,
            "good": "food",
            "amount": 100.0,
            "path": [player_capital, player_capital],
            "path_index": 0,
            "movement_progress": 0.0,
            "age": 0,
        }]
        settle_logistics(self.state, random.Random(1))
        self.assertEqual(data["logistics_units"], [])
        self.assertEqual(region_economy(self.state, enemy_region)["warehouse"]["food"], before + 90)
        self.assertTrue(any("官漕#999" in line and "中途" in line and "摧毁" in line for line in self.state.event_log))

    def test_surviving_logistics_keep_map_location_and_ten_percent_less_cargo(self):
        self.state.armies.clear()
        for region_id in self.state.regions:
            region_economy(self.state, region_id)["stability"] = 100
        city_ids = list(self.state.cities)[:3]
        unit = {
            "id": 1000,
            "kind": "official",
            "regime_id": 1,
            "source_region_id": 1,
            "target_region_id": 1,
            "good": "cloth",
            "amount": 100.0,
            "path": city_ids,
            "path_index": 0,
            "movement_progress": 0.0,
            "age": 0,
        }
        economy_data(self.state)["logistics_units"] = [unit]
        settle_logistics(self.state, random.Random(1))
        self.assertEqual(unit["amount"], 90.0)
        self.assertEqual(MapView.logistics_city_id(unit), city_ids[1])
        progress = next(line for line in reversed(self.state.event_log) if "官漕#1000月度进度" in line)
        self.assertIn("路线1/2", progress)
        self.assertIn("本月损耗10", progress)
        self.assertIn("累计损耗10", progress)

    def test_official_convoy_arrival_log_reports_loaded_delivered_and_total_loss(self):
        self.state.armies.clear()
        city_ids = list(self.state.cities)[:2]
        source_region = int(self.state.cities[city_ids[0]]["region_id"])
        target_region = int(self.state.cities[city_ids[1]]["region_id"])
        region_economy(self.state, target_region)["warehouse"]["food"] = 0.0
        economy_data(self.state)["logistics_units"] = [{
            "id": 1001,
            "kind": "official",
            "regime_id": 1,
            "source_region_id": source_region,
            "target_region_id": target_region,
            "good": "food",
            "amount": 100.0,
            "initial_amount": 100.0,
            "total_attrition": 0.0,
            "path": city_ids,
            "path_index": 0,
            "movement_progress": 0.0,
            "age": 0,
        }]

        settle_logistics(self.state, random.Random(1))

        report = next(line for line in reversed(self.state.event_log) if "官漕#1001抵达" in line)
        self.assertIn("启运100", report)
        self.assertIn("实际入库90", report)
        self.assertIn("累计损耗10", report)

    def test_ai_official_convoy_has_no_route_attrition(self):
        self.state.armies.clear()
        for region_id in self.state.regions:
            region_economy(self.state, region_id)["stability"] = 100
        city_ids = list(self.state.cities)[:3]
        unit = {
            "id": 1002,
            "kind": "official",
            "regime_id": 2,
            "source_region_id": 17,
            "target_region_id": 18,
            "good": "food",
            "amount": 100.0,
            "path": city_ids,
            "path_index": 0,
            "movement_progress": 0.0,
            "age": 0,
        }
        economy_data(self.state)["logistics_units"] = [unit]
        settle_logistics(self.state, random.Random(1))
        self.assertEqual(unit["amount"], 100.0)

    def test_economic_orders_follow_actual_control_instead_of_legal_ownership(self):
        occupied_region = 17
        lost_region = 1
        self.assertNotIn(self.state.regions[occupied_region]["name"], self.state.player_regime["regions"])
        self.state.regions[occupied_region]["controller"] = 1
        occupied = region_economy(self.state, occupied_region)
        occupied["control"] = 100
        occupied["warehouse"]["cloth"] = 100
        self.state.authority = 100
        report = market_order(self.state, 1, occupied_region, "cloth", "sell", 10)
        self.assertIn("实际成交：10", report)

        self.assertIn(self.state.regions[lost_region]["name"], self.state.player_regime["regions"])
        self.state.regions[lost_region]["controller"] = 2
        with self.assertRaises(RuleError):
            market_order(self.state, 1, lost_region, "cloth", "sell", 1)

    def test_v12_has_no_military_money_pay_and_temporary_tax_collects_goods(self):
        self.assertEqual(projected_expenses(self.state, 1)[1], 0)
        self.state.laws["power"] = 2
        record = region_economy(self.state, 1)
        before_copper = treasury_balance(self.state)
        before_food = float(record["warehouse"]["food"])
        self.state.authority = 1000
        v12_politics.temporary_tax(self.state)
        self.assertEqual(treasury_balance(self.state), before_copper)
        self.assertNotIn("copper", record["warehouse"])
        self.assertNotIn("copper", record["market"])
        self.assertGreater(record["warehouse"]["food"], before_food)

    def test_battle_reports_are_preserved_for_chronicle(self):
        attacker = next(army for army in self.state.armies.values() if army.regime_id == 1 and army.location_id == 77)
        target = next(
            int(road["to"] if int(road["from"]) == 77 else road["from"])
            for road in self.state.roads
            if 77 in {int(road["from"]), int(road["to"])}
        )
        defender = next(army for army in self.state.armies.values() if army.regime_id == 2)
        defender.location_id = target
        attack(self.state, attacker.id, target, random.Random(4))
        self.assertTrue(self.state.flags["battle_reports"])
        self.assertTrue(self.state.flags["battle_reports"][-1].startswith("【战报】"))
        self.assertIn(self.state.city_name(target), self.state.flags["battle_reports"][-1])

    def test_relief_and_waterworks_raise_local_stability_not_prosperity(self):
        self.state.laws["power"] = 2
        capital_region = int(self.state.cities[int(self.state.player_regime["capital"])]["region_id"])
        capital_record = region_economy(self.state, capital_region)
        capital_record["warehouse_capacity"] = 1_000
        capital_record["warehouse"]["copper"] = 1_000
        record = region_economy(self.state, 1)
        record["stability"] = 50
        old_prosperity = self.state.regions[1].get("prosperity")
        v12_politics.relief(self.state, 1)
        v12_politics.develop(self.state, 1)
        self.assertEqual(record["stability"], 55)
        self.assertEqual(self.state.regions[1].get("prosperity"), old_prosperity)

    def test_each_peacetime_region_recovers_three_stability_per_month(self):
        peaceful_region = 1
        wartime_region = next(
            int(region_id) for region_id, region in self.state.regions.items()
            if int(region.get("controller", 0)) == 2
        )
        region_economy(self.state, peaceful_region)["stability"] = 94
        region_economy(self.state, wartime_region)["stability"] = 94
        self.state.wars = [[1, 2]]
        settle_peacetime_stability(self.state)
        self.assertEqual(region_economy(self.state, peaceful_region)["stability"], 94)
        self.assertEqual(region_economy(self.state, wartime_region)["stability"], 94)

        self.state.wars = []
        restored = settle_peacetime_stability(self.state)
        self.assertEqual(region_economy(self.state, peaceful_region)["stability"], 97)
        self.assertEqual(region_economy(self.state, wartime_region)["stability"], 97)
        self.assertIn(peaceful_region, restored)

        region_economy(self.state, peaceful_region)["stability"] = 99
        settle_peacetime_stability(self.state)
        self.assertEqual(region_economy(self.state, peaceful_region)["stability"], 100)

    def test_warehouse_cap_and_expansion_order(self):
        record = region_economy(self.state, 1)
        self.assertEqual(warehouse_capacity(self.state, 1), 200.0)
        record["warehouse"].update({"food": 50.0})
        set_treasury(self.state, 1, 50)
        before_treasury = treasury_balance(self.state)
        self.state.authority = 100
        report = expand_warehouse(self.state, 1, 1)
        self.assertEqual(warehouse_capacity(self.state, 1), 220.0)
        self.assertEqual(record["warehouse"]["food"], 30.0)
        self.assertNotIn("copper", record["warehouse"])
        self.assertLess(treasury_balance(self.state), before_treasury)
        self.assertEqual(self.state.authority, 90)
        self.assertIn("粮食与布匹容量", report)

    def test_resource_formatter_uses_at_most_two_decimals(self):
        self.assertEqual(format_resource(1.236), "1.24")
        self.assertEqual(format_resource(1.2), "1.2")
        self.assertEqual(format_resource(1), "1")

    def test_slider_values_truncate_to_one_decimal_without_exceeding_limit(self):
        self.assertEqual(truncate_slider_value(12.99), 12.9)
        self.assertEqual(truncate_slider_value(12.01), 12.0)
        self.assertEqual(truncate_slider_value(0.09), 0.0)

    def test_july_food_tax_adds_half_as_minted_copper(self):
        class NormalWeather:
            @staticmethod
            def random():
                return 0.999

            @staticmethod
            def choice(options):
                if options and isinstance(options[0], tuple):
                    return ("正常", 1.0)
                return options[0]

        region_id = 1
        record = region_economy(self.state, region_id)
        record["warehouse"].update({"food": 0.0, "cloth": 0.0})
        before_treasury = treasury_balance(self.state)
        report = annual_production(self.state, NormalWeather())
        row = next(item for item in report if int(item["region_id"]) == region_id)
        expected = round(float(row["food_tax"]) * 0.5 * float(record["control"]) / 100, 2)
        self.assertEqual(float(row["copper_from_food_tax"]), expected)
        total_player_copper = round(sum(
            float(item["copper_from_food_tax"])
            for item in report
            if int(item["controller"]) == self.state.player_regime_id
        ), 2)
        self.assertEqual(treasury_balance(self.state), before_treasury + total_player_copper)
        self.assertEqual(float(row["national_treasury_income"]), expected)

    def test_july_production_creates_shortage_report(self):
        report = annual_production(self.state)
        self.assertEqual(len(report), len(self.state.regions))
        self.assertEqual(self.state.flags["pending_v12_production_report"], report)
        self.assertTrue({"food", "cloth", "projected_balance", "shortage"} <= set(report[0]))

    def test_army_carries_six_wartime_months_and_refills_at_friendly_depot(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        self.assertEqual(army.supply_food, army_supply_capacity(army))
        self.assertEqual(army_supply_months(army), 6)
        # In hostile territory no warehouse refill is available.
        army.location_id = 117
        settle_army_supply(self.state)
        self.assertEqual(army_supply_months(army), 5)
        # Back in a controlled home region, the regional warehouse fills it to six months.
        army.location_id = 1
        army.supply_food = 0
        region_economy(self.state, 1)["warehouse"]["food"] = 100
        settle_army_supply(self.state)
        self.assertEqual(army_supply_months(army), 6)

    def test_each_stationed_army_adds_five_control(self):
        record = region_economy(self.state, 13)
        record["control"] = 70
        self.state.regions[13]["governor"] = None
        # Three Song armies are initially stationed at Luoyang: -15 without governor +15 from armies.
        settle_local_governance(self.state)
        self.assertEqual(record["control"], 70)

    def test_ai_economic_reports_are_hidden_and_ai_control_is_locked_to_one_hundred(self):
        ai_regions = [
            int(region_id)
            for region_id, region in self.state.regions.items()
            if int(region.get("controller", 0)) not in {0, self.state.player_regime_id}
        ]
        self.assertTrue(ai_regions)
        self.assertTrue(all(region_economy(self.state, region_id)["control"] == 100 for region_id in ai_regions))

        region_id = ai_regions[0]
        regime_id = int(self.state.regions[region_id]["controller"])
        self.state.regimes[regime_id]["authority"] = 100
        record = region_economy(self.state, region_id)
        record["warehouse"]["cloth"] = 100
        before_log = list(self.state.event_log)
        result = market_order(self.state, regime_id, region_id, "cloth", "sell", 10)
        self.assertIn("经济行动报告", result)
        self.assertEqual(self.state.event_log, before_log)

        record["control"] = 15
        self.state.regions[region_id]["control"] = 15
        settle_local_governance(self.state)
        self.assertEqual(record["control"], 100)
        self.assertEqual(self.state.regions[region_id]["control"], 100)

    def test_ai_keeps_one_economic_goal_for_four_months(self):
        regime_id = 7
        plan = ensure_ai_economic_goal(self.state, regime_id)
        created_month = int(plan["created_month"])
        target = plan.get("target_region_id")
        kind = plan["kind"]

        for month in (2, 3, 4):
            self.state.month = month
            current = ensure_ai_economic_goal(self.state, regime_id)
            self.assertEqual(current["created_month"], created_month)
            self.assertEqual(current["kind"], kind)
            self.assertEqual(current.get("target_region_id"), target)

        self.state.month = 5
        reviewed = ensure_ai_economic_goal(self.state, regime_id)
        self.assertEqual(reviewed["created_month"], created_month + PLAN_CYCLE_MONTHS)
        self.assertEqual(reviewed["review_month"], reviewed["created_month"] + PLAN_CYCLE_MONTHS)

    def test_ai_plan_executes_at_most_one_action_each_month(self):
        regime_id = 7
        self.set_ai_force_to_target(regime_id)
        before_authority = int(self.state.regimes[regime_id]["authority"])
        first = run_ai_economic_plan(self.state, regime_id)
        second = run_ai_economic_plan(self.state, regime_id)
        self.assertTrue(first)
        self.assertEqual(second, [])
        self.assertEqual(self.state.regimes[regime_id]["authority"], before_authority - 10)
        self.assertEqual(ai_economic_plan(self.state, regime_id)["actions_taken"], 1)

    def test_ai_does_not_switch_target_before_review_month(self):
        regime_id = 12
        self.set_ai_force_to_target(regime_id)
        for army in self.state.armies.values():
            if army.regime_id == regime_id:
                region_id = int(self.state.cities[army.location_id]["region_id"])
                region_economy(self.state, region_id)["warehouse"]["food"] = 100
        plan = ensure_ai_economic_goal(self.state, regime_id)
        target = int(plan["target_region_id"])
        other = next(
            region_id for region_id in self.state.regions
            if region_id != target and int(self.state.regions[region_id].get("controller", 0)) == regime_id
        )
        region_economy(self.state, target)["market"]["food"] = 10_000
        region_economy(self.state, other)["market"]["food"] = 0
        self.state.month = 2
        self.assertEqual(run_ai_economic_plan(self.state, regime_id), [])
        current = ai_economic_plan(self.state, regime_id)
        self.assertEqual(current["target_region_id"], target)
        self.assertEqual(current["status"], "completed")

    def test_ai_army_supply_emergency_interrupts_four_month_plan_and_creates_convoy(self):
        regime_id = 2
        target_region = 13
        self.state.regions[target_region]["controller"] = regime_id
        self.assertNotIn(self.state.regions[target_region]["name"], self.state.regimes[regime_id]["regions"])
        source_region = 17
        for army in self.state.armies.values():
            if army.regime_id == regime_id:
                army.location_id = 77
                army.supply_food = 0
        target = region_economy(self.state, target_region)
        target["warehouse"]["food"] = 0
        for region_id, region in self.state.regions.items():
            if int(region.get("controller", 0)) == regime_id:
                region_economy(self.state, region_id)["warehouse"]["food"] = 0
        source = region_economy(self.state, source_region)
        source["warehouse"]["food"] = 100
        source["market"]["food"] = 0
        self.state.regimes[regime_id]["authority"] = 100

        old_plan = ensure_ai_economic_goal(self.state, regime_id)
        old_plan.update({"kind": "regional_development", "status": "active", "review_month": old_plan["created_month"] + 4})
        actions = run_ai_economic_plan(self.state, regime_id)
        plan = ai_economic_plan(self.state, regime_id)

        self.assertEqual(plan["kind"], "military_supply")
        self.assertEqual(plan["target_region_id"], target_region)
        self.assertEqual(plan["review_month"], plan["created_month"] + 1)
        self.assertTrue(actions)
        convoy = economy_data(self.state)["logistics_units"][-1]
        self.assertEqual((convoy["good"], convoy["target_region_id"]), ("food", target_region))

    def test_ai_food_security_keeps_food_needed_to_refill_local_armies(self):
        regime_id = 7
        self.set_ai_force_to_target(regime_id)
        target_region = int(self.state.cities[int(self.state.regimes[regime_id]["capital"])]["region_id"])
        for region_id, region in self.state.regions.items():
            if int(region.get("controller", 0)) == regime_id:
                region_economy(self.state, region_id)["market"]["food"] = 10_000
        record = region_economy(self.state, target_region)
        population = len(population_units(self.state, target_region))
        record["market"]["food"] = max(0, population - 20)
        record["warehouse"]["food"] = 50
        army = next(army for army in self.state.armies.values() if army.regime_id == regime_id)
        army.location_id = int(self.state.regimes[regime_id]["capital"])
        army.supply_food = 0
        total_capacity = sum(
            army_supply_capacity(item) for item in self.state.armies.values() if item.regime_id == regime_id
        )
        military_reserve = total_capacity / 3 + army_supply_capacity(army)
        self.state.regimes[regime_id]["authority"] = 100

        actions = run_ai_economic_plan(self.state, regime_id)
        self.assertEqual(ai_economic_plan(self.state, regime_id)["kind"], "food_security")
        self.assertTrue(actions)
        self.assertGreaterEqual(record["warehouse"]["food"], military_reserve)

    def test_wei_uses_a_six_figure_standing_force_target(self):
        regime_id = 2
        for region_id, region in self.state.regions.items():
            if int(region.get("controller", 0)) != regime_id:
                continue
            record = region_economy(self.state, region_id)
            record["market"]["food"] = len(population_units(self.state, region_id))
            record["warehouse"]["copper"] = 500
            record["warehouse"]["food"] = 500
        plan = choose_ai_economic_goal(self.state, regime_id)
        self.assertEqual(plan["kind"], "military_expansion")
        self.assertEqual(plan["target_amount"], WEI_STANDING_FORCE_TARGET - 30_000)

    def test_wei_standing_force_target_does_not_replace_losses_for_free(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        army.units[0]["count"] = 100
        before = sum(item.soldiers for item in self.state.armies.values() if item.regime_id == 2)
        reinforced = settle_wei_standing_army(self.state)
        after = sum(item.soldiers for item in self.state.armies.values() if item.regime_id == 2)
        self.assertEqual(reinforced, 0)
        self.assertEqual(after, before)
        self.assertEqual(army.units[0]["count"], 100)

    def test_other_ai_standing_targets_do_not_create_free_armies(self):
        regime_id = 7
        before = sum(item.soldiers for item in self.state.armies.values() if item.regime_id == regime_id)
        player_before = sum(
            item.soldiers for item in self.state.armies.values()
            if item.regime_id == self.state.player_regime_id
        )
        reinforced = settle_ai_standing_armies(self.state)
        after = sum(item.soldiers for item in self.state.armies.values() if item.regime_id == regime_id)
        player_after = sum(
            item.soldiers for item in self.state.armies.values()
            if item.regime_id == self.state.player_regime_id
        )
        self.assertEqual(reinforced, {})
        self.assertEqual(after, before)
        self.assertEqual(player_after, player_before)

    def test_lost_capital_does_not_trigger_free_relocation_or_rebuild(self):
        regime_id = 12
        old_capital = int(self.state.regimes[regime_id]["capital"])
        old_capital_region = next(
            region_id
            for region_id, region in self.state.regions.items()
            if old_capital in region.get("cities", [])
        )
        self.state.regions[old_capital_region]["controller"] = 2
        for army_id in [army.id for army in self.state.armies.values() if army.regime_id == regime_id]:
            self.state.armies.pop(army_id)
        reinforced = settle_ai_standing_armies(self.state)
        new_capital = int(self.state.regimes[regime_id]["capital"])
        self.assertEqual(new_capital, old_capital)
        self.assertEqual(reinforced, {})
        self.assertFalse(any(army.regime_id == regime_id for army in self.state.armies.values()))

    def test_ai_expansion_pays_difficulty_adjusted_recruits_and_food(self):
        expected = {
            # The halved manpower pool now limits the first batch to six
            # battalions on easy and eight on normal; hard still reaches nine
            # because its recruitment discount consumes less manpower.
            "easy": (6000, 7.2),
            "normal": (6400, 7.68),
            "hard": (5400, 6.48),
        }
        for difficulty, (recruitment_cost, food_cost) in expected.items():
            state = load_v12_state()
            state.flags["difficulty"] = difficulty
            regime_id = 2
            plan = choose_ai_economic_goal(state, regime_id)
            self.assertEqual(plan["kind"], "military_expansion")
            capital = int(state.regimes[regime_id]["capital"])
            capital_region = int(state.cities[capital]["region_id"])
            warehouse = region_economy(state, capital_region)["warehouse"]
            food_before = float(warehouse["food"])

            actions = run_ai_economic_plan(state, regime_id)

            self.assertTrue(actions and actions[0].startswith("expand:"))
            self.assertAlmostEqual(food_before - float(warehouse["food"]), food_cost, places=2)
            record = economy_data(state)["recruitment"][str(regime_id)]
            self.assertEqual(record["amount"], recruitment_cost)

    def test_ai_expansion_funds_an_empty_capital_treasury_then_resumes_recruiting(self):
        state = load_v12_state()
        state.flags["difficulty"] = "hard"
        regime_id = 2
        capital = int(state.regimes[regime_id]["capital"])
        capital_region = int(state.cities[capital]["region_id"])
        controlled = [
            int(region_id) for region_id, region in state.regions.items()
            if int(region.get("controller", 0)) == regime_id
        ]
        source_region = next(region_id for region_id in controlled if region_id != capital_region)
        for region_id in controlled:
            warehouse = region_economy(state, region_id)["warehouse"]
            warehouse["cloth"] = 0
            warehouse["food"] = 500
        set_treasury(state, regime_id, 0)
        region_economy(state, source_region)["warehouse"]["cloth"] = 100
        plan = choose_ai_economic_goal(state, regime_id)
        soldiers_before = sum(army.soldiers for army in state.armies.values() if army.regime_id == regime_id)

        funding_actions = run_ai_economic_plan(state, regime_id)

        self.assertTrue(funding_actions)
        self.assertEqual(plan["stage"], "fund_capital_copper")
        self.assertEqual(plan["actions_taken"], 1)
        self.assertEqual(
            sum(army.soldiers for army in state.armies.values() if army.regime_id == regime_id),
            soldiers_before,
        )
        self.assertGreater(treasury_balance(state, regime_id), 0)

        # Once the physically transported funds are available, the unchanged
        # expansion plan resumes instead of waiting for a new four-month goal.
        set_treasury(state, regime_id, 100)
        state.month += 1
        recruitment_actions = run_ai_economic_plan(state, regime_id)
        self.assertTrue(recruitment_actions and recruitment_actions[0].startswith("expand:"))
        self.assertEqual(plan["stage"], "recruiting")
        self.assertGreater(
            sum(army.soldiers for army in state.armies.values() if army.regime_id == regime_id),
            soldiers_before,
        )

    def test_failed_ai_expansion_does_not_consume_the_monthly_action(self):
        state = load_v12_state()
        regime_id = 2
        capital = int(state.regimes[regime_id]["capital"])
        capital_region = int(state.cities[capital]["region_id"])
        for region_id, region in state.regions.items():
            if int(region.get("controller", 0)) != regime_id:
                continue
            warehouse = region_economy(state, int(region_id))["warehouse"]
            warehouse["cloth"] = 0
            warehouse["food"] = 500
        set_treasury(state, regime_id, 0)
        plan = choose_ai_economic_goal(state, regime_id)
        self.assertEqual(treasury_balance(state, regime_id), 0)

        self.assertEqual(run_ai_economic_plan(state, regime_id), [])

        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(plan["stage"], "fund_capital_copper")
        self.assertIsNone(plan["last_action_month"])
        self.assertEqual(plan["actions_taken"], 0)
        self.assertIn("缺少扩军铜钱", plan["blocked_reason"])

    def test_ai_economic_goal_is_saved_and_loaded(self):
        regime_id = 2
        expected = dict(ensure_ai_economic_goal(self.state, regime_id))
        with tempfile.TemporaryDirectory() as folder:
            path = save_game(self.state, save_dir=Path(folder))
            loaded = load_game(path)
        self.assertEqual(ai_economic_plan(loaded, regime_id), expected)

    def test_ai_keeps_one_military_strategy_for_four_months(self):
        regime_id = 2
        plan = ensure_ai_military_strategy(self.state, regime_id)
        self.assertEqual(plan["kind"], "attack_region")
        self.assertEqual(plan["target_city_id"], 77)
        created_month = int(plan["created_month"])

        # 战况变化不会让AI在四个月内临时改攻建康。
        self.state.regions[13]["controller"] = 2
        self.state.flags["v12_wei_war_expanded"] = True
        for month in (2, 3, 4):
            self.state.month = month
            current = ensure_ai_military_strategy(self.state, regime_id)
            self.assertEqual(current["created_month"], created_month)
            self.assertEqual(current["target_city_id"], 77)

        self.state.month = 5
        reviewed = ensure_ai_military_strategy(self.state, regime_id)
        self.assertEqual(reviewed["created_month"], created_month + STRATEGY_CYCLE_MONTHS)
        self.assertEqual(reviewed["kind"], "consolidate")
        self.assertEqual(reviewed["target_city_id"], 77)

    def test_ai_recovers_war_support_by_difficulty_each_month(self):
        for difficulty, expected in (("easy", 5), ("normal", 7), ("hard", 10)):
            state = load_v12_state()
            state.flags["difficulty"] = difficulty
            state.regimes[2]["war_support"] = 15

            gains = recover_ai_war_support(state)

            self.assertEqual(gains[2], expected)
            self.assertEqual(state.regimes[2]["war_support"], 15 + expected)

    def test_commanderless_ai_uses_difficulty_martial_but_player_does_not(self):
        ai_strengths = []
        player_strengths = []
        for difficulty, martial in (("easy", 50), ("normal", 60), ("hard", 70)):
            state = load_v12_state()
            state.flags["difficulty"] = difficulty
            wei = next(army for army in state.armies.values() if army.regime_id == 2)
            song = next(army for army in state.armies.values() if army.regime_id == 1)
            wei.commander = None
            song.commander = None
            wei.location_id = 107
            song.location_id = 82
            wei.units = [{"type": 1, "count": 5_000}]
            song.units = [{"type": 1, "count": 5_000}]

            ai_strengths.append(float(estimate_battle_losses(state, wei.id, 82)["attacker_strength"]))
            self.assertEqual(ai_simulated_commander_martial(state, wei), martial)
            self.assertEqual(ai_simulated_commander_martial(state, song), 0)

            song.location_id = 107
            wei.location_id = 82
            player_strengths.append(float(estimate_battle_losses(state, song.id, 82)["attacker_strength"]))

        self.assertLess(ai_strengths[0], ai_strengths[1])
        self.assertLess(ai_strengths[1], ai_strengths[2])
        self.assertEqual(len(set(player_strengths)), 1)

    def test_low_support_ai_rejects_costly_attack_before_battle(self):
        wei = next(army for army in self.state.armies.values() if army.regime_id == 2)
        song = next(army for army in self.state.armies.values() if army.regime_id == 1)
        wei.location_id = 107
        song.location_id = 82
        wei.units = [{"type": 1, "count": 5_000}]
        song.units = [{"type": 1, "count": 9_000}]
        wei.supply_food = army_supply_capacity(wei)
        self.state.regimes[2]["war_support"] = 25

        assessment = ai_attack_assessment(self.state, wei, 82)
        local = evaluate_local_military_strategies(
            self.state,
            2,
            {"kind": "attack_region", "target_city_id": 82, "avoid_water": False},
        )[17]

        self.assertFalse(assessment["allowed"])
        self.assertIn("低于30", assessment["reason"])
        self.assertEqual(local["action"], "retreat")

    def test_monthly_local_strategy_advances_or_retreats_without_replacing_grand_plan(self):
        wei_armies = [army for army in self.state.armies.values() if army.regime_id == 2]
        song_armies = [army for army in self.state.armies.values() if army.regime_id == 1]
        for army in wei_armies:
            army.location_id = 107
            army.supply_food = army_supply_capacity(army)
        for army in song_armies:
            army.location_id = 82
            army.units = [{"type": 1, "count": 500}]
        grand_plan = {
            "regime_id": 2,
            "kind": "attack_region",
            "target_city_id": 77,
            "avoid_water": False,
            "review_month": 9_999,
            "status": "active",
        }
        self.state.flags.setdefault("v12_military_plans", {})["2"] = grand_plan

        advance = evaluate_local_military_strategies(self.state, 2, grand_plan)[17]
        self.assertEqual(advance["action"], "advance")
        self.assertNotEqual(advance["advance_city_id"], grand_plan["target_city_id"])

        for army in song_armies:
            army.units = [{"type": 1, "count": 10_000}]
            army.morale = 100
            army.supply_food = army_supply_capacity(army)
        retreat = evaluate_local_military_strategies(self.state, 2, grand_plan)[17]
        self.assertEqual(retreat["action"], "retreat")
        self.assertTrue(retreat["fallback_city_id"])
        self.assertEqual(grand_plan["target_city_id"], 77)
        self.assertEqual(grand_plan["review_month"], 9_999)
        saved = self.state.flags["v12_local_military_plans"]["2"]
        self.assertEqual(saved["month"], month_index(self.state))

    def test_safe_local_advance_executes_before_different_grand_target(self):
        wei_armies = [army for army in self.state.armies.values() if army.regime_id == 2]
        song_armies = [army for army in self.state.armies.values() if army.regime_id == 1]
        for army in wei_armies:
            army.location_id = 107
            army.supply_food = army_supply_capacity(army)
        for army in song_armies:
            army.location_id = 82
            army.units = [{"type": 1, "count": 500}]
        grand_plan = {
            "regime_id": 2,
            "kind": "attack_region",
            "target_city_id": 77,
            "avoid_water": False,
            "review_month": 9_999,
            "status": "active",
        }
        self.state.flags.setdefault("v12_military_plans", {})["2"] = grand_plan

        actions = run_ai_military_strategy(self.state, 2, random.Random(1))

        self.assertTrue(any(action.startswith("local_advance:") for action in actions))
        self.assertEqual(grand_plan["target_city_id"], 77)
        self.assertEqual(grand_plan["review_month"], 9_999)

    def test_land_heavy_ai_avoids_water_when_enemy_navy_is_strong(self):
        snapshot = national_military_snapshot(self.state, 2)
        self.assertEqual(snapshot["own_composition"]["cavalry"], 25_000)
        self.assertEqual(snapshot["enemy_composition"]["naval"], 10_000)
        self.assertTrue(snapshot["avoid_water"])
        plan = choose_ai_military_strategy(self.state, 2)
        self.assertTrue(plan["avoid_water"])
        self.assertTrue(plan["maximum_cavalry_water_avoidance"])

    def test_enemy_navy_creates_absolute_three_step_cavalry_exclusion_zone(self):
        threatened = enemy_naval_threatened_cities(self.state, 2)
        self.assertIn(1, threatened)
        self.assertIn(2, threatened)
        plan = choose_ai_military_strategy(self.state, 2)
        self.assertEqual(set(plan["enemy_naval_threatened_cities"]), threatened)

        # 即使外部剧情强行指定建康，水军不匹配时骑兵也不会向禁区移动。
        self.state.regions[13]["controller"] = 2
        plan["kind"] = "attack_region"
        plan["target_city_id"] = 1
        plan["status"] = "active"
        for army in self.state.armies.values():
            if army.regime_id == 2:
                army.location_id = 77
        run_ai_military_strategy(self.state, 2, random.Random(1))
        self.assertTrue(all(
            army.location_id not in threatened
            for army in self.state.armies.values()
            if army.regime_id == 2 and army.pure_cavalry
        ))

    def test_wei_southern_campaign_requires_large_advantage_supply_and_naval_cover(self):
        self.state.regions[13]["controller"] = 2
        self.state.flags["v12_wei_war_expanded"] = True
        blocked = choose_ai_military_strategy(self.state, 2)
        self.assertEqual(blocked["kind"], "consolidate")

        # 两支一万人的水军改为魏军掩护后，且总兵力超过宋军1.5倍，才允许南征。
        for army_id in (4, 5):
            self.state.armies[army_id].regime_id = 2
            self.state.armies[army_id].location_id = 117
        allowed = choose_ai_military_strategy(self.state, 2)
        self.assertEqual(allowed["kind"], "attack_region")
        self.assertEqual(allowed["target_city_id"], 1)
        self.assertFalse(allowed["naval_mismatch"])

    def test_cavalry_exclusion_activates_immediately_if_naval_cover_is_lost(self):
        self.state.armies[4].regime_id = 2
        self.state.armies[4].location_id = 117
        plan = choose_ai_military_strategy(self.state, 2)
        self.assertFalse(plan["naval_mismatch"])
        plan.update({"kind": "attack_region", "target_city_id": 1, "status": "active"})
        self.state.armies.pop(4)
        for army in self.state.armies.values():
            if army.regime_id == 2:
                army.location_id = 77
        run_ai_military_strategy(self.state, 2, random.Random(1))
        threatened = enemy_naval_threatened_cities(self.state, 2)
        self.assertTrue(all(army.location_id not in threatened for army in self.state.armies.values() if army.regime_id == 2 and army.pure_cavalry))

    def test_ai_prioritizes_threatened_region_capitals_and_fortified_passes(self):
        regime_id = 2
        controlled_city_ids = [
            int(city_id) for city_id, city in self.state.cities.items()
            if int(self.state.regions[int(city.get("region_id", 0))].get("controller", 0)) == regime_id
        ]
        region_capital = next(city_id for city_id in controlled_city_ids if self.state.cities[city_id].get("capital"))
        fortified = next(
            city_id for city_id in controlled_city_ids
            if not self.state.cities[city_id].get("capital") and int(self.state.cities[city_id].get("defense", 0)) >= 60
        )
        enemies = [army for army in self.state.armies.values() if army.regime_id == 1]
        enemies[0].location_id = next(
            int(road["to"] if int(road["from"]) == region_capital else road["from"])
            for road in self.state.roads if region_capital in {int(road["from"]), int(road["to"])}
        )
        enemies[1].location_id = next(
            int(road["to"] if int(road["from"]) == fortified else road["from"])
            for road in self.state.roads if fortified in {int(road["from"]), int(road["to"])}
        )
        kinds = {item["kind"] for item in ai_defense_priorities(self.state, regime_id)}
        self.assertIn("region_capital", kinds)
        self.assertIn("fortified_pass", kinds)

    def test_ai_marks_endangered_official_convoy_route_as_top_defense(self):
        regime_id = 2
        path = [117, 118, 77]
        economy_data(self.state)["logistics_units"] = [{
            "id": 2001,
            "kind": "official",
            "regime_id": regime_id,
            "source_region_id": 19,
            "target_region_id": 13,
            "good": "food",
            "amount": 30.0,
            "path": path,
            "path_index": 0,
            "movement_progress": 0.0,
            "age": 0,
        }]
        enemy = next(army for army in self.state.armies.values() if army.regime_id == 1)
        enemy.location_id = 118
        priority = ai_defense_priorities(self.state, regime_id)[0]
        self.assertEqual(priority["kind"], "convoy_route")
        self.assertEqual(priority["city_id"], 118)
        actions = run_ai_military_strategy(self.state, regime_id, random.Random(1))
        self.assertTrue(any(action.startswith("protect_convoy_route:") for action in actions))

    def test_land_strategy_chooses_longer_land_route_over_short_water_route(self):
        self.state.month = 6
        plan = choose_ai_military_strategy(self.state, 2)
        self.assertTrue(plan["avoid_water"])
        self.state.roads = [
            {"from": 117, "to": 118, "type": 3},
            {"from": 118, "to": 77, "type": 3},
            {"from": 117, "to": 119, "type": 1},
            {"from": 119, "to": 120, "type": 1},
            {"from": 120, "to": 77, "type": 1},
        ]
        run_ai_military_strategy(self.state, 2, random.Random(1))
        self.assertEqual(self.state.armies[7].location_id, 119)

    def test_low_supply_is_handled_per_army_without_replacing_strategy(self):
        for army in self.state.armies.values():
            if army.regime_id == 2:
                army.supply_food = 0
        plan = choose_ai_military_strategy(self.state, 2)
        self.assertEqual(plan["kind"], "attack_region")
        self.assertLess(plan["snapshot"]["average_supply_health"], 100)

    def test_ai_effective_strength_excludes_zero_morale_paper_force(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        army.units = [{"type": 1, "count": 9_000}]
        army.supply_food = army_supply_capacity(army)
        army.morale = 0

        self.assertEqual(army_readiness_strength(self.state, army), 0)

        army.morale = 80
        ready = army_readiness_strength(self.state, army)
        army.supply_food = 0
        starving = army_readiness_strength(self.state, army)
        self.assertGreater(ready, starving)

    def test_ai_restores_low_morale_army_from_friendly_warehouse(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        capital = int(self.state.regimes[2]["capital"])
        army.location_id = capital
        army.morale = 0
        capital_region = int(self.state.cities[capital]["region_id"])
        region_economy(self.state, capital_region)["warehouse"]["food"] = 200

        actions = run_ai_military_strategy(self.state, 2, random.Random(1))

        self.assertEqual(army.morale, 30)
        self.assertTrue(any(action.startswith(f"restore_morale:{army.id}:") for action in actions))

    def test_ai_detaches_mobile_reserve_without_creating_soldiers(self):
        wei_armies = [army for army in self.state.armies.values() if army.regime_id == 2]
        oversized = wei_armies[0]
        oversized.location_id = 132
        oversized.units = [{"type": 1, "count": 1_000} for _ in range(9)]
        oversized.establishment = [1] * 9
        oversized.morale = 80
        oversized.supply_food = army_supply_capacity(oversized)
        for army in wei_armies[1:]:
            army.location_id = int(self.state.regimes[2]["capital"])
        before = sum(army.soldiers for army in wei_armies)

        actions = run_ai_military_strategy(self.state, 2, random.Random(1))

        after = sum(army.soldiers for army in self.state.armies.values() if army.regime_id == 2)
        self.assertEqual(after, before)
        self.assertGreaterEqual(
            sum(
                army.soldiers for army in self.state.armies.values()
                if army.regime_id == 2 and army.location_id == 132
            ),
            3_000,
        )
        self.assertTrue(any(action.startswith("create_mobile_reserve:") for action in actions))

    def test_ai_creates_persistent_two_to_five_army_task_force(self):
        run_ai_military_strategy(self.state, 2, random.Random(1))
        task = self.state.flags["v12_ai_task_forces"]["2"]

        self.assertGreaterEqual(len(task["member_army_ids"]), 2)
        self.assertLessEqual(len(task["member_army_ids"]), 5)
        self.assertEqual(
            task["commit_until_month"] - task["created_month"],
            2,
        )
        self.assertEqual(set(task["roles"]), {str(item) for item in task["member_army_ids"]})

    def test_starving_army_does_not_freeze_healthy_attackers(self):
        plan = choose_ai_military_strategy(self.state, 2)
        plan.update({"kind": "attack_region", "target_city_id": 77, "status": "active"})
        armies = sorted((army for army in self.state.armies.values() if army.regime_id == 2), key=lambda army: army.id)
        starving = armies[0]
        for item in armies:
            item.supply_food = army_supply_capacity(item)
            item.location_id = 117
        starving.supply_food = 0

        actions = run_ai_military_strategy(self.state, 2, random.Random(1))

        self.assertEqual(starving.location_id, 117)
        attacking_ids = {
            int(action.split(":")[1]) for action in actions if action.startswith("attack:")
        }
        self.assertTrue(attacking_ids)
        self.assertNotIn(starving.id, attacking_ids)
        self.assertTrue(any(army.location_id != 117 for army in armies if army.id in attacking_ids))

    def test_legacy_global_resupply_plan_resumes_immediately_at_depot(self):
        army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        army.location_id = 117
        army.supply_food = 0
        self.state.flags.setdefault("v12_military_plans", {})["2"] = {
            "kind": "resupply",
            "target_army_id": army.id,
            "target_city_id": 117,
            "resume_kind": "attack_region",
            "resume_target_city_id": 77,
            "created_month": self.state.year * 12 + self.state.month,
            "review_month": self.state.year * 12 + self.state.month + 4,
            "status": "active",
        }

        plan = ensure_ai_military_strategy(self.state, 2)

        self.assertEqual((plan["kind"], plan["target_city_id"]), ("attack_region", 77))

    def test_completed_wartime_target_is_replaced_immediately(self):
        plan = choose_ai_military_strategy(self.state, 2)
        plan.update({"status": "completed", "target_city_id": 117, "review_month": plan["review_month"] + 3})

        replacement = ensure_ai_military_strategy(self.state, 2)

        self.assertEqual(replacement["status"], "active")
        self.assertNotEqual(replacement["target_city_id"], 117)

    def test_wartime_offensive_keeps_minimum_garrison_at_existing_fort(self):
        plan = choose_ai_military_strategy(self.state, 2)
        plan.update({"kind": "attack_region", "target_city_id": 77, "status": "active"})
        armies = sorted((army for army in self.state.armies.values() if army.regime_id == 2), key=lambda army: army.id)
        fort_city = 132
        for army in armies:
            army.supply_food = army_supply_capacity(army)
        for army in armies[:2]:
            army.location_id = fort_city

        run_ai_military_strategy(self.state, 2, random.Random(1))

        remaining = [army for army in armies[:2] if army.location_id == fort_city]
        self.assertEqual(len(remaining), 1)
        self.assertTrue(any(army.location_id != fort_city for army in armies[:2]))

    def test_superior_ai_opens_secondary_front_against_another_lost_capital(self):
        self.state.regions[13]["controller"] = 1
        self.state.regions[17]["controller"] = 1
        region_13_name = self.state.regions[13]["name"]
        if region_13_name in self.state.regimes[1]["regions"]:
            self.state.regimes[1]["regions"].remove(region_13_name)
        self.state.regimes[2]["regions"].append(region_13_name)
        song_armies = [army for army in self.state.armies.values() if army.regime_id == 1]
        song_armies[0].location_id = 77
        song_armies[0].units = [{"type": 1, "count": 3_000}]
        song_armies[1].location_id = 107
        song_armies[1].units = [{"type": 1, "count": 3_000}]
        for army in song_armies[2:]:
            army.units = [{"type": 1, "count": 1}]
        for army in self.state.armies.values():
            if army.regime_id == 2:
                for unit in army.units:
                    unit["type"] = 1
                army.units[0]["count"] += 10_000
                army.supply_food = army_supply_capacity(army)

        plan = choose_ai_military_strategy(self.state, 2)

        targets = {int(plan["target_city_id"]), *map(int, plan.get("secondary_target_city_ids", []))}
        self.assertEqual(targets, {77, 107})

    def test_ai_pivots_from_contested_front_to_undefended_lost_region(self):
        self.state.regions[13]["controller"] = 1
        self.state.regions[17]["controller"] = 1
        region_13_name = self.state.regions[13]["name"]
        if region_13_name in self.state.regimes[1]["regions"]:
            self.state.regimes[1]["regions"].remove(region_13_name)
        if region_13_name not in self.state.regimes[2]["regions"]:
            self.state.regimes[2]["regions"].append(region_13_name)
        for army in self.state.armies.values():
            if army.regime_id == 1:
                army.location_id = 77
                army.units = [{"type": 1, "count": 5_000}]
            elif army.regime_id == 2:
                army.units = [{"type": 1, "count": 5_000}]
                army.supply_food = army_supply_capacity(army)

        now = self.state.year * 12 + self.state.month
        self.state.flags.setdefault("v12_military_plans", {})["2"] = {
            "kind": "attack_region",
            "target_region_id": 13,
            "target_city_id": 77,
            "secondary_target_city_ids": [],
            "created_month": now,
            "review_month": now + STRATEGY_CYCLE_MONTHS,
            "status": "active",
        }

        plan = ensure_ai_military_strategy(self.state, 2)

        self.assertEqual(plan["target_region_id"], 17)
        self.assertEqual(plan["target_city_id"], 107)
        self.assertEqual(plan["secondary_target_city_ids"], [])
        self.assertEqual(plan["previous_target_city_id"], 77)
        self.assertIn("更薄弱的失地", plan["reason"])

    def test_ai_refuses_land_cession_when_it_can_fight_exhausted_player(self):
        target_id = 2
        self.state.regions[17]["controller"] = self.state.player_regime_id
        self.state.player_regime["war_support"] = 20
        self.state.regimes[target_id]["war_support"] = 80
        for army in self.state.armies.values():
            if army.regime_id == self.state.player_regime_id:
                army.units = [{"type": 1, "count": 500}]
                army.morale = 20
                army.supply_food = 0
            elif army.regime_id == target_id:
                army.units = [{"type": 1, "count": 5_000}]
                army.morale = 80
                army.supply_food = army_supply_capacity(army)

        accepted, reason = peace_evaluation(self.state, target_id, {"target_cedes": [17]})

        self.assertFalse(accepted)
        self.assertIn("尚有一战之力", reason)

    def test_peace_score_applies_exact_penalty_at_one_point_five_force_ratio(self):
        for army in self.state.armies.values():
            army.units = [{"type": 1, "count": 0}]
        player_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        wei_army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        player_army.units = [{"type": 1, "count": 10_000}]
        wei_army.units = [{"type": 1, "count": 15_000}]
        self.state.player_regime["war_support"] = 80
        self.state.regimes[2]["war_support"] = 80

        accepted, detail = peace_evaluation(self.state, 2, {})

        self.assertFalse(accepted)
        self.assertIn("-150", detail)

    def test_peace_score_scales_force_penalty_and_has_default_resistance(self):
        for army in self.state.armies.values():
            army.units = [{"type": 1, "count": 0}]
        player_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        wei_army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        player_army.units = [{"type": 1, "count": 10_000}]
        self.state.player_regime["war_support"] = 80
        self.state.regimes[2]["war_support"] = 80

        wei_army.units = [{"type": 1, "count": 20_000}]
        score_two, parts_two = peace_score(self.state, 2, {})
        wei_army.units = [{"type": 1, "count": 30_000}]
        score_three, parts_three = peace_score(self.state, 2, {})
        player_army.units = [{"type": 1, "count": 30_000}]
        wei_army.units = [{"type": 1, "count": 10_000}]
        score_one_to_three, parts_one_to_three = peace_score(self.state, 2, {})

        self.assertEqual(score_two, -220)
        self.assertIn("默认和解阻力-20", parts_two)
        self.assertTrue(any(item.endswith("-200") for item in parts_two))
        self.assertEqual(score_three, -320)
        self.assertTrue(any(item.endswith("-300") for item in parts_three))
        self.assertEqual(score_one_to_three, 280)
        self.assertTrue(any(item.endswith("+300") for item in parts_one_to_three))

    def test_force_ratio_from_half_through_one_point_two_is_neutral(self):
        for army in self.state.armies.values():
            army.units = [{"type": 1, "count": 0}]
        player_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        wei_army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        player_army.units = [{"type": 1, "count": 10_000}]
        self.state.player_regime["war_support"] = 80
        self.state.regimes[2]["war_support"] = 80

        wei_army.units = [{"type": 1, "count": 5_000}]
        half_score, half_parts = peace_score(self.state, 2, {})
        wei_army.units = [{"type": 1, "count": 12_000}]
        one_point_two_score, one_point_two_parts = peace_score(self.state, 2, {})

        self.assertEqual(half_score, -20)
        self.assertEqual(half_parts, ["默认和解阻力-20"])
        self.assertEqual(one_point_two_score, -20)
        self.assertEqual(one_point_two_parts, ["默认和解阻力-20"])

    def test_ai_returning_occupied_player_region_adds_fifty(self):
        for army in self.state.armies.values():
            army.units = [{"type": 1, "count": 0}]
        player_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        wei_army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        player_army.units = [{"type": 1, "count": 10_000}]
        wei_army.units = [{"type": 1, "count": 10_000}]
        self.state.player_regime["war_support"] = 80
        self.state.regimes[2]["war_support"] = 80
        player_region = next(
            region_id for region_id in self.state.regions
            if region_owner(self.state, region_id) == 1
        )
        self.state.regions[player_region]["controller"] = 2

        score, parts = peace_score(self.state, 2, {})

        self.assertEqual(score, 30)
        self.assertTrue(any("AI归还所占玩家地区" in item and item.endswith("+50") for item in parts))

    def test_land_demands_only_penalize_regions_not_controlled_by_player(self):
        target_region = next(
            region_id for region_id in self.state.regions
            if region_owner(self.state, region_id) == 2
        )
        self.state.regions[target_region]["controller"] = 1
        occupied_score, occupied_parts = peace_score(
            self.state,
            2,
            {"target_cedes": [target_region]},
        )
        returned_score, returned_parts = peace_score(self.state, 2, {"target_cedes": []})
        self.state.regions[target_region]["controller"] = 2
        unoccupied_score, unoccupied_parts = peace_score(
            self.state,
            2,
            {"target_cedes": [target_region]},
        )

        self.assertTrue(any(item.endswith("+0") for item in occupied_parts))
        self.assertEqual(returned_score, occupied_score + 50)
        self.assertTrue(any(item.endswith("+50") for item in returned_parts))
        self.assertEqual(unoccupied_score, occupied_score - 10_000)
        self.assertTrue(any(item.endswith("-10000") for item in unoccupied_parts))

    def test_force_ratio_from_half_to_one_point_two_is_neutral(self):
        for army in self.state.armies.values():
            army.units = [{"type": 1, "count": 0}]
        player_army = next(army for army in self.state.armies.values() if army.regime_id == 1)
        wei_army = next(army for army in self.state.armies.values() if army.regime_id == 2)
        self.state.player_regime["war_support"] = 80
        self.state.regimes[2]["war_support"] = 80

        for ai_force, player_force in ((5_000, 10_000), (10_000, 10_000), (12_000, 10_000)):
            wei_army.units = [{"type": 1, "count": ai_force}]
            player_army.units = [{"type": 1, "count": player_force}]
            score, parts = peace_score(self.state, 2, {})
            self.assertEqual(score, -20)
            self.assertFalse(any("剩余兵力" in item for item in parts))

    def test_rejected_ai_peace_offer_has_four_month_cooldown(self):
        self.state.flags["pending_story_events"] = []
        self.state.flags["v12_wei_peace_resolved"] = "generic-test"
        self.state.regimes[2]["war_support"] = 20
        for army in self.state.armies.values():
            if army.regime_id == 2:
                army.units = [{"type": 1, "count": 100}]

        self.assertTrue(queue_ai_peace_offer(self.state, 2))
        reject_ai_peace_offer(self.state)
        self.assertFalse(queue_ai_peace_offer(self.state, 2))

        self.state.month += 4
        self.assertTrue(queue_ai_peace_offer(self.state, 2))

    def test_ai_supply_discount_reduces_actual_consumption_by_difficulty(self):
        for difficulty, multiplier in (("easy", 0.50), ("normal", 0.30), ("hard", 0.15)):
            state = load_v12_state()
            state.flags["difficulty"] = difficulty
            army = next(army for army in state.armies.values() if army.regime_id == 2)
            army.location_id = 1
            army.supply_food = 10.0
            before = float(army.supply_food)
            expected_cost = round(army.soldiers / 1000 * 0.2 * multiplier, 2)

            settle_army_supply(state)

            capped_before = min(before, army_supply_capacity(army))
            self.assertAlmostEqual(float(army.supply_food), capped_before - expected_cost, places=2)

    def test_late_convoy_does_not_hide_frontline_supply_emergency(self):
        regime_id = 2
        target_region = 13
        self.state.regions[target_region]["controller"] = regime_id
        army = next(army for army in self.state.armies.values() if army.regime_id == regime_id)
        army.location_id = 77
        army.supply_food = 0
        region_economy(self.state, target_region)["warehouse"]["food"] = 0
        economy_data(self.state)["logistics_units"] = [{
            "id": 9001,
            "kind": "official",
            "regime_id": regime_id,
            "source_region_id": 19,
            "target_region_id": target_region,
            "good": "food",
            "amount": 100.0,
            "path": [117, 118, 119, 120, 77],
            "path_index": 0,
            "movement_progress": 0.0,
            "age": 0,
        }]

        plan = choose_ai_economic_goal(self.state, regime_id)

        self.assertEqual(plan["kind"], "military_supply")
        self.assertEqual(plan["target_region_id"], target_region)

    def test_recent_conquest_is_consolidated_before_new_attack(self):
        self.state.regions[13]["controller"] = 2
        self.state.flags["v12_wei_war_expanded"] = True
        self.state.flags["v12_region_captures"] = {
            "13": {
                "region_id": 13,
                "regime_id": 2,
                "previous_controller": 1,
                "month": self.state.year * 12 + self.state.month,
            }
        }
        plan = choose_ai_military_strategy(self.state, 2)
        self.assertEqual(plan["kind"], "consolidate")
        self.assertEqual(plan["target_city_id"], 77)

    def test_capturing_region_capital_records_conquest_month(self):
        army = self.state.armies[6]
        army.location_id = 77
        occupy_capital_if_applicable(self.state, army)
        record = self.state.flags["v12_region_captures"]["13"]
        self.assertEqual(record["regime_id"], 2)
        self.assertEqual(record["previous_controller"], 1)
        self.assertEqual(record["month"], self.state.year * 12 + self.state.month)

    def test_supply_emergency_does_not_replace_saved_strategy(self):
        plan = choose_ai_military_strategy(self.state, 2)
        army = self.state.armies[7]
        army.location_id = 119
        army.supply_food = 0
        before_target = plan["target_city_id"]
        actions = run_ai_military_strategy(self.state, 2, random.Random(1))
        self.assertTrue(any(action.startswith("emergency_resupply:7:") for action in actions))
        self.assertEqual(ai_military_plan(self.state, 2)["target_city_id"], before_target)

    def test_supply_health_records_route_depot_and_carried_food(self):
        army = self.state.armies[6]
        record = supply_line_health(self.state, army)
        self.assertEqual(record["supply_months"], 6)
        self.assertEqual(record["depot_city_id"], 117)
        self.assertEqual(record["path"], [117])
        self.assertGreaterEqual(record["health"], 80)


if __name__ == "__main__":
    unittest.main()
