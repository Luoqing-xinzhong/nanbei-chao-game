from __future__ import annotations

import tkinter as tk
import unittest
from tkinter import ttk

from PIL import Image

from app.content.v1_2.scenario import load_v12_state
from app.content.v1_3.scenario import load_default_wenjiao_state
from app.ui import theme
from app.ui.dragon_layout import ART_PATH, ART_SIZE, REGIONS, scaled_rect
from app.ui.main_screen import MainGameScreen
from app.ui.sidebar_stages import sidebar_for
from app.v11 import load_v11_state


class DragonGeometryTests(unittest.TestCase):
    def test_packaged_background_matches_layout_coordinates(self):
        with Image.open(ART_PATH) as source:
            self.assertEqual(source.size, ART_SIZE)

    def test_regions_remain_inside_full_window_without_overlapping_map(self):
        for width, height in ((1024, 680), (1366, 768), (1440, 900), (1920, 1080), (2560, 1080)):
            with self.subTest(size=(width, height)):
                boxes = {name: scaled_rect(name, width, height) for name in REGIONS}
                for x, y, w, h in boxes.values():
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x+w, width)
                    self.assertLessEqual(y+h, height)
                self.assertLess(boxes["stage"][0]+boxes["stage"][2], boxes["map"][0])
                self.assertLess(boxes["map"][0]+boxes["map"][2], boxes["logs"][0])


class DragonWidgetTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda _kind, value, _trace: self.errors.append(str(value))
        theme.configure_theme(ttk.Style(self.root))
        self.callbacks = {key: lambda *args: None for key in ("status", "stage", "save", "menu", "changed")}

    def tearDown(self):
        if hasattr(self, "root"):
            self.root.destroy()
        self.assertEqual(self.errors, [])

    def test_all_four_subscenarios_can_build_refresh_and_close_every_stage(self):
        scenarios = (("songwu", load_v11_state()), ("yuanjia", load_v12_state()),
                     ("wenjiao_south", load_default_wenjiao_state()),
                     ("blood_tears", load_default_wenjiao_state()))
        for name, state in scenarios:
            if name == "blood_tears":
                state.flags["scenario_id"] = name
            screen = MainGameScreen(self.root, state, self.callbacks)
            for index, phase in enumerate(state.phase_names):
                with self.subTest(scenario=name, phase=phase):
                    state.phase_index = index
                    panel = sidebar_for(state)(screen.stage_host, state, lambda: None, lambda: None)
                    screen.set_stage_panel(panel)
                    self.root.update_idletasks()
                    panel.refresh()
                    screen.refresh()
                    self.assertIs(panel.master, screen.stage_host)
                    self.assertIsNot(panel.master, screen.map_frame)
                    expected = "结束回合" if index == len(state.phase_names)-1 else "下一阶段"
                    self.assertEqual(panel.next_button.cget("text"), expected)
                    binding = panel._wheel_binding
                    panel.close()
                    self.assertNotIn(binding, self.root.bind("<MouseWheel>"))
            screen.destroy()

    def test_logs_have_switchable_tabs_latest_five_and_full_history(self):
        state = load_default_wenjiao_state()
        for index in range(8):
            state.add_log(f"纪事{index}")
            state.add_log(f"【战报】军情{index}")
        screen = MainGameScreen(self.root, state, self.callbacks)
        self.assertEqual(len(screen.log_tabs.tabs()), 2)
        self.assertNotIn("纪事2", screen.chronicle_log.get("1.0", "end"))
        self.assertIn("纪事3", screen.chronicle_log.get("1.0", "end"))
        self.assertIn("军情7", screen.military_log.get("1.0", "end"))
        self.assertNotIn("军情2", screen.military_log.get("1.0", "end"))
        screen.log_tabs.select(1)
        self.assertEqual(screen.log_tabs.index("current"), 1)
        self.assertEqual(len(state.event_log), 16)

    def test_repainting_does_not_accumulate_navigation_event_handlers(self):
        screen = MainGameScreen(self.root, load_default_wenjiao_state(), self.callbacks)
        before = len(screen.backdrop._tclCommands)
        for _ in range(10):
            screen.backdrop.redraw()
        self.assertEqual(len(screen.backdrop._tclCommands), before)
        self.assertEqual(screen.backdrop.tag_bind("overlay", "<ButtonRelease-1>"), "")

    def test_development_buttons_change_both_values_and_labels(self):
        state = load_default_wenjiao_state()
        state.phase_index = state.phase_names.index("发展阶段")
        screen = MainGameScreen(self.root, state, self.callbacks)
        panel = sidebar_for(state)(screen.stage_host, state, lambda: None, lambda: None)
        screen.set_stage_panel(panel)
        region_id = next(iter(panel.policy_vars))
        before_policy = panel.policy_vars[region_id].get()
        panel._cycle_policy(region_id)
        self.assertNotEqual(panel.policy_vars[region_id].get(), before_policy)
        before_supply = panel.supply_vars[region_id].get()
        panel._cycle_supply(region_id)
        self.assertNotEqual(panel.supply_vars[region_id].get(), before_supply)
        panel.close()

    def test_phase_footer_advances_once_and_releases_scroll_binding(self):
        state = load_default_wenjiao_state()
        screen = MainGameScreen(self.root, state, self.callbacks)
        advances = []
        panel = sidebar_for(state)(screen.stage_host, state, lambda: advances.append(1), lambda: None)
        screen.set_stage_panel(panel)
        panel.next_button.invoke()
        self.assertEqual(advances, [1])
        self.assertFalse(panel.winfo_exists())


if __name__ == "__main__":
    unittest.main()
