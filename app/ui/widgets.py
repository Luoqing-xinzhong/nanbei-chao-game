from __future__ import annotations

import tkinter as tk
import math
from pathlib import Path
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageTk

from ..constants import MAP_CANDIDATES, MAP_HEIGHT, MAP_WIDTH, REGIME_COLORS
from ..models import GameState
from ..rules.military import city_controller
from . import theme


class ScrollableFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, background=theme.PANEL)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, style="Panel.TFrame")
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self:
                self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return
            widget = getattr(widget, "master", None)


class MapView(ttk.Frame):
    """支持滚轮缩放、鼠标拖动并叠加动态城市/军队标记的地图。"""

    CITY_RADIUS_MAP_UNITS = 10.0

    def __init__(
        self,
        master,
        state: GameState,
        on_city: Callable[[int], None] | None = None,
        on_logistics: Callable[[int], None] | None = None,
        on_supply: Callable[[int], None] | None = None,
        on_city_double: Callable[[int], None] | None = None,
    ):
        super().__init__(master, style="Panel.TFrame")
        self.state = state
        self.on_city = on_city
        self.on_logistics = on_logistics
        self.on_supply = on_supply
        self.on_city_double = on_city_double
        self.canvas = tk.Canvas(self, background="#ddd8ca", highlightthickness=0, cursor="fleur")
        self.canvas.pack(fill="both", expand=True)
        map_path = next((path for path in MAP_CANDIDATES if Path(path).exists()), None)
        if not map_path:
            raise FileNotFoundError("未找到地图.png")
        self.source = Image.open(map_path).convert("RGB")
        self.scale = 0.45
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._photo: ImageTk.PhotoImage | None = None
        self._initialized = False
        self._resize_job: str | None = None
        self._drag_from = (0, 0)
        self._press_at = (0, 0)
        self._city_radius = 6.0
        self._single_click_job: str | None = None
        self._suppress_click_release = False
        self.economic_mode = False
        self.selected_economic_region_id: int | None = None
        self._logistics_hits: list[tuple[float, float, float, float, int]] = []
        self._supply_hits: list[tuple[float, float, float, float, int]] = []
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<MouseWheel>", self._zoom)
        self.canvas.bind("<ButtonPress-1>", self._start_pan)
        self.canvas.bind("<B1-Motion>", self._pan)
        self.canvas.bind("<ButtonRelease-1>", self._end_pan)
        self.canvas.bind("<Double-Button-1>", self._city_double_click)
        self.bind("<Destroy>", self._cancel_pending_map_events, add="+")

    def _cancel_pending_map_events(self, event):
        if event.widget is self:
            for key in ("_resize_job", "_single_click_job"):
                job = getattr(self, key, None)
                if job is not None:
                    self.after_cancel(job)
                    setattr(self, key, None)

    def _on_resize(self, event):
        if event.width > 10 and event.height > 10:
            minimum = self.minimum_scale_for(event.width, event.height)
            if not self._initialized or self.scale < minimum:
                self.scale = minimum
                self.offset_x = (event.width - MAP_WIDTH * self.scale) / 2
                self.offset_y = (event.height - MAP_HEIGHT * self.scale) / 2
                self._initialized = True
            self._clamp_offsets(event.width, event.height)
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(90, self.redraw)

    @staticmethod
    def minimum_scale_for(view_width: float, view_height: float) -> float:
        """最小比例保证地图覆盖整个视口，不露出地图外背景。"""
        return max(max(1.0, view_width) / MAP_WIDTH, max(1.0, view_height) / MAP_HEIGHT)

    @staticmethod
    def bounded_offset(offset: float, viewport_size: float, content_size: float) -> float:
        """把内容偏移限制在两侧边缘之间。"""
        lower = min(0.0, viewport_size - content_size)
        return min(0.0, max(lower, offset))

    @classmethod
    def city_radius_for(cls, scale: float) -> float:
        return cls.CITY_RADIUS_MAP_UNITS * scale

    @staticmethod
    def army_marker_battalions(armies: list) -> int:
        """地图叠军标记显示合计兵力折算的千人营数，而不是军队支数。"""
        if not armies:
            return 0
        return max(1, sum(army.soldiers for army in armies) // 1000)

    def _clamp_offsets(self, view_width: float | None = None, view_height: float | None = None) -> None:
        view_width = float(view_width if view_width is not None else max(1, self.canvas.winfo_width()))
        view_height = float(view_height if view_height is not None else max(1, self.canvas.winfo_height()))
        self.offset_x = self.bounded_offset(self.offset_x, view_width, MAP_WIDTH * self.scale)
        self.offset_y = self.bounded_offset(self.offset_y, view_height, MAP_HEIGHT * self.scale)

    def _zoom(self, event):
        old = self.scale
        factor = 1.18 if event.delta > 0 else 1 / 1.18
        minimum = self.minimum_scale_for(self.canvas.winfo_width(), self.canvas.winfo_height())
        self.scale = max(minimum, min(minimum * 4.5, old * factor))
        world_x = (event.x - self.offset_x) / old
        world_y = (event.y - self.offset_y) / old
        self.offset_x = event.x - world_x * self.scale
        self.offset_y = event.y - world_y * self.scale
        self._clamp_offsets()
        self.redraw()

    def _start_pan(self, event):
        self._drag_from = (event.x, event.y)
        self._press_at = (event.x, event.y)

    def _pan(self, event):
        dx, dy = event.x - self._drag_from[0], event.y - self._drag_from[1]
        old_x, old_y = self.offset_x, self.offset_y
        self.offset_x = old_x + dx
        self.offset_y = old_y + dy
        self._clamp_offsets()
        self._drag_from = (event.x, event.y)
        shift_x, shift_y = self.offset_x - old_x, self.offset_y - old_y
        self.canvas.move("world", shift_x, shift_y)
        self._logistics_hits = [
            (left + shift_x, top + shift_y, right + shift_x, bottom + shift_y, unit_id)
            for left, top, right, bottom, unit_id in self._logistics_hits
        ]
        self._supply_hits = [
            (left + shift_x, top + shift_y, right + shift_x, bottom + shift_y, unit_id)
            for left, top, right, bottom, unit_id in self._supply_hits
        ]

    def _end_pan(self, event):
        if self._suppress_click_release:
            self._suppress_click_release = False
            return
        if abs(event.x - self._press_at[0]) <= 5 and abs(event.y - self._press_at[1]) <= 5:
            if self._single_click_job:
                self.after_cancel(self._single_click_job)
            x, y = event.x, event.y
            self._single_click_job = self.after(230, lambda: self._run_single_click(x, y))

    def _run_single_click(self, x: float, y: float) -> None:
        self._single_click_job = None
        self._city_click_at(x, y)

    def _city_click(self, event):
        self._city_click_at(event.x, event.y)

    def _city_click_at(self, event_x: float, event_y: float):
        for left, top, right, bottom, supply_id in reversed(self._supply_hits):
            if left <= event_x <= right and top <= event_y <= bottom:
                if self.on_supply:
                    self.on_supply(supply_id)
                return
        for left, top, right, bottom, logistics_id in reversed(self._logistics_hits):
            if left <= event_x <= right and top <= event_y <= bottom:
                if self.on_logistics:
                    self.on_logistics(logistics_id)
                return
        hits = []
        occupied = set() if self.economic_mode else {army.location_id for army in self.state.armies.values()}
        army_offset = max(10, 15 * self.scale)
        army_hit_radius = max(14, min(24, 14 * self.scale + 8))
        for city in self.state.cities.values():
            x, y = self._point(city)
            city_distance = (x - event_x) ** 2 + (y - event_y) ** 2
            if city_distance <= (self._city_radius + 5) ** 2:
                hits.append((city_distance, city))
            if city["id"] in occupied:
                army_distance = (x - event_x) ** 2 + (y - army_offset - event_y) ** 2
                if army_distance <= army_hit_radius ** 2:
                    hits.append((army_distance, city))
        if hits and self.on_city:
            self.on_city(int(min(hits, key=lambda item: item[0])[1]["id"]))

    def _city_double_click(self, event):
        if self._single_click_job:
            self.after_cancel(self._single_click_job)
            self._single_click_job = None
        self._suppress_click_release = True
        if not self.on_city_double:
            return
        hits = []
        for city in self.state.cities.values():
            x, y = self._point(city)
            distance = (x - event.x) ** 2 + (y - event.y) ** 2
            if distance <= (self._city_radius + 5) ** 2:
                hits.append((distance, city))
        if hits:
            self.on_city_double(int(min(hits, key=lambda item: item[0])[1]["id"]))

    def redraw(self):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = None
        if self._initialized:
            self._clamp_offsets()
        width = max(1, math.ceil(MAP_WIDTH * self.scale))
        height = max(1, math.ceil(MAP_HEIGHT * self.scale))
        resized = self.source.resize((width, height), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(self.offset_x, self.offset_y, image=self._photo, anchor="nw", tags="world")
        self._draw_cities()
        if self.economic_mode:
            self._draw_economic_labels()
        self._draw_logistics()
        if not self.economic_mode:
            self._draw_supply_units()
            self._draw_armies()

    def _point(self, city: dict) -> tuple[float, float]:
        return self.offset_x + city["x"] * self.scale, self.offset_y + city["y"] * self.scale

    def _draw_cities(self):
        # 圆点使用地图坐标半径，随地图严格等比例缩放。
        radius = self.city_radius_for(self.scale)
        self._city_radius = radius
        for city in self.state.cities.values():
            x, y = self._point(city)
            region_id = int(city.get("region_id", 0))
            if self.economic_mode:
                from ..content.v1_2.economy import market_demand, region_economy

                record = region_economy(self.state, region_id)
                shortage = float(record["market"].get("food", 0.0)) + 1e-9 < market_demand(
                    self.state, region_id, "food"
                )
                fill = "#c83d3d" if shortage else "#29985f"
            else:
                regime = self.state.regimes.get(city_controller(self.state, city["id"]), {})
                fill = REGIME_COLORS.get(str(regime.get("color", "gray")).lower(), regime.get("color", "#777777"))
            selected = self.economic_mode and city.get("capital") and region_id == self.selected_economic_region_id
            outline = "#ffd34d" if selected else "#f7e9c3" if city.get("capital") else "#1d1b18"
            width = 4 if selected else 2 if city.get("capital") else 1
            self.canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=fill,
                outline=outline,
                width=width,
                tags="world",
            )
            if str(self.state.flags.get("rules_version", "")) == "1.3":
                buildings = self.state.flags.get("v13_culture", {}).get("buildings", {}).get(str(region_id), [])
                if any(int(item.get("city_id", 0)) == int(city["id"]) and item.get("type") == "school" for item in buildings):
                    self.canvas.create_text(
                        x + radius * 1.8, y - radius * 1.8, text="📜",
                        fill="#244f87", font=("Microsoft YaHei UI", max(8, int(radius * 1.6)), "bold"), tags="world",
                    )

    def _draw_economic_labels(self) -> None:
        from ..content.v1_2.economy import format_resource, market_demand, market_price, region_economy
        from ..rules.treasury import treasury_balance

        for region_id, region in sorted(self.state.regions.items()):
            capital_id = next(
                (
                    int(city_id)
                    for city_id in region.get("cities", [])
                    if self.state.cities.get(int(city_id), {}).get("capital")
                ),
                None,
            )
            if capital_id not in self.state.cities:
                continue
            record = region_economy(self.state, int(region_id))
            warehouse = record["warehouse"]
            market = record["market"]
            food_demand = market_demand(self.state, int(region_id), "food")
            market_food = float(market.get("food", 0.0))
            food_shortage = max(0.0, food_demand - market_food)
            shortage = food_shortage > 1e-9
            lines = (
                (f"{region.get('name', '')} {'缺粮' if shortage else '充足'}", "#241d15"),
                (f"市场粮食缺口 {format_resource(food_shortage)}", "#c62828"),
                (f"府库粮食 {format_resource(warehouse.get('food', 0))}", "#168447"),
                (
                    f"州库 布{format_resource(warehouse.get('cloth', 0))} "
                    f"国库钱{format_resource(treasury_balance(self.state, int(region.get('controller', 0))))}",
                    "#241d15",
                ),
                (
                    f"市场 粮{format_resource(market_food)} 布{format_resource(market.get('cloth', 0))}",
                    "#241d15",
                ),
                (
                    f"价格 粮{market_price(self.state, int(region_id), 'food'):g} "
                    f"布{market_price(self.state, int(region_id), 'cloth'):g}",
                    "#241d15",
                ),
            )
            x, y = self._point(self.state.cities[capital_id])
            label_x = x + self._city_radius + 5
            label_y = y - self._city_radius
            font = ("Microsoft YaHei UI", max(7, min(10, int(7 + self.scale * 2))), "bold")
            text_ids = []
            boxes = []
            for line, color in lines:
                text_id = self.canvas.create_text(
                    label_x,
                    label_y,
                    text=line,
                    anchor="nw",
                    justify="left",
                    fill=color,
                    font=font,
                    tags="world",
                )
                text_ids.append(text_id)
                bbox = self.canvas.bbox(text_id)
                if bbox:
                    boxes.append(bbox)
                    label_y = bbox[3]
            if boxes:
                background = self.canvas.create_rectangle(
                    min(box[0] for box in boxes) - 3,
                    min(box[1] for box in boxes) - 2,
                    max(box[2] for box in boxes) + 3,
                    max(box[3] for box in boxes) + 2,
                    fill="#f4edda",
                    outline="#7f7462",
                    width=1,
                    tags="world",
                )
                self.canvas.tag_lower(background, text_ids[0])

    @staticmethod
    def logistics_city_id(unit: dict) -> int | None:
        path = unit.get("path", [])
        if not path:
            return None
        index = max(0, min(int(unit.get("path_index", 0)), len(path) - 1))
        return int(path[index])

    def _draw_logistics(self):
        self._logistics_hits = []
        units = self.state.flags.get("v12_economy", {}).get("logistics_units", [])
        grouped: dict[int, list[dict]] = {}
        for unit in units:
            city_id = self.logistics_city_id(unit)
            if city_id in self.state.cities:
                grouped.setdefault(city_id, []).append(unit)
        size = max(5.0, min(11.0, 7.0 * self.scale + 3.0))
        spacing = size * 2 + 3
        for city_id, city_units in grouped.items():
            city = self.state.cities[city_id]
            base_x, base_y = self._point(city)
            for position, unit in enumerate(city_units):
                column = position % 3
                row = position // 3
                x = base_x + (column - 1) * spacing
                y = base_y + max(12, 18 * self.scale) + row * spacing
                regime = self.state.regimes.get(int(unit.get("regime_id", 0)), {})
                if self.economic_mode:
                    fill = "#9a6a2f"
                elif regime:
                    fill = REGIME_COLORS.get(
                        str(regime.get("color", "gray")).lower(),
                        regime.get("color", "#777777"),
                    )
                else:
                    fill = "#9a6a2f"
                left, top, right, bottom = x - size, y - size, x + size, y + size
                self.canvas.create_rectangle(
                    left,
                    top,
                    right,
                    bottom,
                    fill=fill,
                    outline="#fff1c9",
                    width=2,
                    tags="world",
                )
                self._logistics_hits.append((left - 3, top - 3, right + 3, bottom + 3, int(unit["id"])))

    def _draw_supply_units(self):
        """Supply columns use amber hexagons, distinct from army and convoy markers."""
        self._supply_hits = []
        units = self.state.flags.get("v12_economy", {}).get("supply_units", [])
        grouped: dict[int, list[dict]] = {}
        for unit in units:
            city_id = int(unit.get("location_id", 0))
            if city_id in self.state.cities:
                grouped.setdefault(city_id, []).append(unit)
        size = max(7.0, min(13.0, 8.0 * self.scale + 4.0))
        spacing = size * 1.8
        for city_id, city_units in grouped.items():
            base_x, base_y = self._point(self.state.cities[city_id])
            for position, unit in enumerate(city_units):
                x = base_x + max(18, 25 * self.scale) + (position % 3) * spacing
                y = base_y + max(15, 21 * self.scale) + (position // 3) * spacing
                points = []
                for index in range(6):
                    angle = math.pi / 3 * index
                    points.extend((x + size * math.cos(angle), y + size * math.sin(angle)))
                self.canvas.create_polygon(
                    points,
                    fill="#d89019",
                    outline="#fff4cf",
                    width=2,
                    tags="world",
                )
                self.canvas.create_text(
                    x,
                    y,
                    text="粮",
                    fill="#2b2114",
                    font=("Microsoft YaHei UI", 7, "bold"),
                    tags="world",
                )
                self._supply_hits.append((x - size - 3, y - size - 3, x + size + 3, y + size + 3, int(unit["id"])))

    def _draw_armies(self):
        grouped: dict[int, list] = {}
        for army in self.state.armies.values():
            grouped.setdefault(army.location_id, []).append(army)
        for city_id, armies in grouped.items():
            city = self.state.cities.get(city_id)
            if not city:
                continue
            x, y = self._point(city)
            y -= max(10, 15 * self.scale)
            regime = self.state.regimes.get(armies[0].regime_id, {})
            fill = REGIME_COLORS.get(
                str(regime.get("color", "gray")).lower(),
                regime.get("color", "#555"),
            )
            size = max(10, min(17, 12 * self.scale + 5))
            points = (x, y - size, x - size, y - size / 3, x - size * .7, y + size, x + size * .7, y + size, x + size, y - size / 3)
            self.canvas.create_polygon(points, fill=fill, outline="#f8f0d8", width=2, tags="world")
            label = str(self.army_marker_battalions(armies))
            self.canvas.create_text(x, y, text=label, fill="white", font=("Microsoft YaHei UI", 8, "bold"), tags="world")


def labeled_value(master, label: str, value: str, row: int, column: int = 0) -> ttk.Label:
    ttk.Label(master, text=label, style="Muted.TLabel").grid(row=row, column=column, sticky="w", padx=(0, 8), pady=2)
    result = ttk.Label(master, text=value)
    result.grid(row=row, column=column + 1, sticky="w", pady=2)
    return result
