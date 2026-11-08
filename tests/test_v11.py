from __future__ import annotations

import unittest

from app.constants import (
    COMMON_CONFIG_DIR,
    GAME_DIR,
    V11_CONFIG_DIR,
    V11_CONTENT_DIR,
    V11_DOCS_DIR,
    V12_CONFIG_DIR,
    V12_CONTENT_DIR,
    V12_DOCS_DIR,
)
from app.v11 import LAW_CATEGORIES, load_v11_state


class V11InitializationTests(unittest.TestCase):
    def setUp(self):
        self.state = load_v11_state()

    def test_historical_persons_and_families_are_loaded(self):
        self.assertEqual(len(self.state.persons), 94)
        self.assertEqual(len(self.state.families), 28)
        self.assertEqual(self.state.person_name(self.state.player["id"]), "刘裕")
        self.assertEqual(self.state.person_name(83), "司马德宗")
        self.assertIn("徐羡之", {self.state.person_name(person_id) for person_id in self.state.persons})
        self.assertIn("拓跋嗣", {self.state.person_name(person_id) for person_id in self.state.persons})
        self.assertIn("赫连勃勃", {self.state.person_name(person_id) for person_id in self.state.persons})

    def test_versioned_resource_layout_is_complete(self):
        self.assertTrue((COMMON_CONFIG_DIR / "cities.json").is_file())
        self.assertTrue((COMMON_CONFIG_DIR / "roads_all.json").is_file())
        self.assertTrue((V11_CONFIG_DIR / "persons_v1_1_historical.json").is_file())
        self.assertTrue((V11_DOCS_DIR / "后续剧情4.docx").is_file())
        self.assertTrue((V12_CONFIG_DIR / "persons_all_factions_initial_1.2.json").is_file())
        self.assertTrue(V12_DOCS_DIR.is_dir())

    def test_story_content_is_separated_from_common_rules(self):
        for filename in ("story_texts.py", "events.py", "decisions.py", "strategies.py"):
            self.assertTrue((V11_CONTENT_DIR / filename).is_file())
        self.assertTrue((V12_CONTENT_DIR / "__init__.py").is_file())
        for old_name in ("story.py", "decisions.py", "strategies.py", "story_texts.py"):
            self.assertFalse((GAME_DIR / "app" / "rules" / old_name).exists())

    def test_regime_leaders_are_updated(self):
        self.assertIsNone(self.state.regimes[1]["internal"]["emperor"])
        self.assertEqual(self.state.person_name(self.state.regimes[1]["internal"]["shangshu_ling"]), "王嘏")
        self.assertEqual(self.state.person_name(self.state.regimes[5]["internal"]["emperor"]), "卢循")
        self.assertEqual(self.state.person_name(self.state.regimes[8]["internal"]["emperor"]), "慕容超")
        self.assertEqual(self.state.person_name(self.state.regimes[9]["internal"]["emperor"]), "姚泓")
        self.assertEqual(self.state.person_name(self.state.regimes[2]["internal"]["emperor"]), "拓跋嗣")
        self.assertEqual(self.state.person_name(self.state.regimes[12]["internal"]["emperor"]), "赫连勃勃")

    def test_opening_jiankang_army_is_commanded_by_liu_yu(self):
        army = next(item for item in self.state.armies.values() if item.regime_id == 1 and item.location_id == 1)
        self.assertEqual(self.state.person_name(army.commander), "刘裕")

    def test_only_story_granted_confidants_are_present_at_opening(self):
        names = {self.state.person_name(pid) for pid in self.state.confidants}
        self.assertEqual(names, {"檀凭之", "孟昶"})

    def test_laws_and_parties_are_initialized(self):
        self.assertEqual(set(self.state.laws), set(LAW_CATEGORIES))
        self.assertEqual(len(self.state.parties), 4)
        self.assertEqual(self.state.parties[1]["leader"], 8)
        self.assertEqual(self.state.parties[2]["leader"], 33)
        self.assertIsNone(self.state.parties[3]["leader"])
        self.assertEqual(self.state.parties[4]["leader"], 85)


if __name__ == "__main__":
    unittest.main()
