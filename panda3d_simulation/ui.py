"""
Professional Dashboard UI System

Clean left-side panel with semi-transparent dark background.
Organized sections: Time, Room, Sensors, Controls, Performance.
Light text on dark panel for readability in all lighting conditions.
"""

from panda3d.core import TextNode, CardMaker, TransparencyAttrib, Vec4


class DashboardUI:
    """
    Professional dashboard UI with dark background panel.
    Always readable regardless of sky/scene brightness.
    """

    # Panel geometry dynamically sized to 25% of screen width
    PANEL_WIDTH = 0.88  # Approx 25% at 16:9. Will be resized on init.

    # Text positioning relative to a2dTopLeft
    TEXT_X = 0.05         # Elegant left margin
    HEADER_Y = -0.08      # Initial Y from top
    LINE_HEIGHT = 0.048
    SECTION_GAP = 0.03

    # Font sizes
    TITLE_SCALE = 0.05
    VALUE_SCALE = 0.04
    SMALL_SCALE = 0.032
    HIGHLIGHT_SCALE = 0.043

    # Colors (light on dark background)
    COLOR_TITLE = (0.3, 0.85, 1.0, 1.0)       # Electric Cyan headers
    COLOR_LABEL = (0.75, 0.75, 0.8, 1.0)        # Crisp gray labels
    COLOR_VALUE = (0.92, 0.92, 0.92, 1.0)       # Near-white values
    COLOR_HIGHLIGHT = (0.3, 0.95, 0.5, 1.0)     # Green highlights
    COLOR_WARNING = (1.0, 0.75, 0.2, 1.0)       # Amber warning
    COLOR_CRITICAL = (1.0, 0.35, 0.3, 1.0)      # Red critical
    COLOR_NEUTRAL = (0.6, 0.6, 0.65, 1.0)       # Muted neutral
    COLOR_INFO = (0.4, 0.75, 1.0, 1.0)          # Light blue info
    COLOR_DIM = (0.45, 0.45, 0.5, 1.0)          # Dim text

    def __init__(self, app):
        """Initialize the dashboard UI."""
        self.app = app
        self.text_elements = {}

        # Room selector state
        self.selected_room_id = 0
        self.selected_room_max_id = 4

        # First compute actual panel width based on window aspect ratio
        aspect_ratio = self.app.getAspectRatio()
        full_width = aspect_ratio * 2.0
        self.PANEL_WIDTH = full_width * 0.25

        # Create background panel first
        self._create_background_panel()
        # Then text elements
        self._create_dashboard_panels()
        self._setup_room_selector()
        
        # Add resize hook
        self.app.accept("window-event", self._on_resize)

    def _on_resize(self, window):
        """Update background panel width if window size changes."""
        if hasattr(self, 'panel_np'):
            aspect_ratio = self.app.getAspectRatio()
            new_width = aspect_ratio * 2.0 * 0.25
            if abs(new_width - self.PANEL_WIDTH) > 0.01:
                self.PANEL_WIDTH = new_width
                # Re-generate cards
                self.panel_np.removeNode()
                self.accent_np.removeNode()
                self._create_background_panel()

    def _create_background_panel(self):
        """Create semi-transparent dark background card behind the panel."""
        cm = CardMaker("panel_bg")
        # Relative to a2dTopLeft, Y/Z goes down to -2.0
        cm.setFrame(0, self.PANEL_WIDTH, -2.0, 0.0)
        cm.setColor(0.06, 0.06, 0.09, 0.82)

        self.panel_np = self.app.a2dTopLeft.attachNewNode(cm.generate())
        self.panel_np.setTransparency(TransparencyAttrib.MAlpha)
        self.panel_np.setBin("background", 0)

        # Thin accent line on right edge
        cm2 = CardMaker("panel_accent")
        cm2.setFrame(self.PANEL_WIDTH - 0.005, self.PANEL_WIDTH, -2.0, 0.0)
        cm2.setColor(0.1, 0.8, 1.0, 0.75) 
        self.accent_np = self.app.a2dTopLeft.attachNewNode(cm2.generate())
        self.accent_np.setTransparency(TransparencyAttrib.MAlpha)
        self.accent_np.setBin("background", 1)

    def _create_dashboard_panels(self):
        """Create all dashboard panel sections."""
        y = self.HEADER_Y

        # ═══════════════════════ SIMULATION STATUS ═══════════════════════
        self._create_element("sim_title", "⏱ SIMULATION", self.TEXT_X, y,
                             scale=self.TITLE_SCALE, color=self.COLOR_TITLE)
        y -= self.LINE_HEIGHT

        self._create_element("sim_date_time", "Time: --:-- (Day 0)", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT

        self._create_element("sim_speed", "Speed: 60.0x", self.TEXT_X, y,
                             scale=self.SMALL_SCALE, color=self.COLOR_LABEL)
        y -= self.LINE_HEIGHT

        self._create_element("sim_status", "[ RUNNING ]", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_HIGHLIGHT)
        y -= self.LINE_HEIGHT

        self._create_element("sim_weather", "Weather: Clear | 22°C", self.TEXT_X, y,
                             scale=self.SMALL_SCALE, color=self.COLOR_DIM)
        y -= self.LINE_HEIGHT + self.SECTION_GAP

        # ═══════════════════════ SELECTED ROOM ═══════════════════════
        self._create_element("room_title", "🏢 SELECTED ROOM", self.TEXT_X, y,
                             scale=self.TITLE_SCALE, color=self.COLOR_TITLE)
        y -= self.LINE_HEIGHT

        self._create_element("room_name", "Room 0 — Office A", self.TEXT_X, y,
                             scale=self.HIGHLIGHT_SCALE, color=self.COLOR_INFO)
        y -= self.LINE_HEIGHT

        self._create_element("room_type", "Type: Office | 6×6×3m", self.TEXT_X, y,
                             scale=self.SMALL_SCALE, color=self.COLOR_LABEL)
        y -= self.LINE_HEIGHT + self.SECTION_GAP

        # ═══════════════════════ SENSOR DATA ═══════════════════════
        self._create_element("sensor_title", "📊 SENSORS", self.TEXT_X, y,
                             scale=self.TITLE_SCALE, color=self.COLOR_TITLE)
        y -= self.LINE_HEIGHT

        self._create_element("sensor_temp", "Temp: 21.5°C", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT

        self._create_element("sensor_humidity", "Humidity: 45%", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT

        self._create_element("sensor_co2", "CO2: 420 ppm", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT

        self._create_element("sensor_occupancy", "Occupancy: 0/4", self.TEXT_X, y,
                             scale=self.HIGHLIGHT_SCALE, color=self.COLOR_HIGHLIGHT)
        y -= self.LINE_HEIGHT + self.SECTION_GAP

        # ═══════════════════════ ACTUATOR CONTROL ═══════════════════════
        self._create_element("control_title", "⚡ CONTROLS", self.TEXT_X, y,
                             scale=self.TITLE_SCALE, color=self.COLOR_TITLE)
        y -= self.LINE_HEIGHT

        self._create_element("decision_light", "Light: OFF", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT

        self._create_element("decision_hvac", "HVAC: Off", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT

        self._create_element("decision_shading", "Shading: 0%", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT

        self._create_element("decision_comfort", "Comfort: --/100", self.TEXT_X, y,
                             scale=self.HIGHLIGHT_SCALE, color=self.COLOR_HIGHLIGHT)
        y -= self.LINE_HEIGHT
        
        self._create_element("decision_energy", "Load: 0 W", self.TEXT_X, y,
                             scale=self.VALUE_SCALE, color=self.COLOR_VALUE)
        y -= self.LINE_HEIGHT + self.SECTION_GAP

        # ═══════════════════════ DECISION REASONING ═══════════════════════
        self._create_element("reason_title", "🧠 DECISION", self.TEXT_X, y,
                             scale=self.TITLE_SCALE, color=self.COLOR_TITLE)
        y -= self.LINE_HEIGHT

        self._create_element("decision_strategy", "Strategy: comfort", self.TEXT_X, y,
                             scale=self.SMALL_SCALE, color=self.COLOR_LABEL)
        y -= self.LINE_HEIGHT

        self._create_element("decision_reason", "Reason: initializing...", self.TEXT_X, y,
                             scale=self.SMALL_SCALE, color=self.COLOR_DIM)
        y -= self.LINE_HEIGHT

        self._create_element("decision_effectiveness", "Status: —", self.TEXT_X, y,
                             scale=self.SMALL_SCALE, color=self.COLOR_HIGHLIGHT)
        y -= self.LINE_HEIGHT

        self._create_element("decision_trend", "Trend: —", self.TEXT_X, y,
                             scale=self.SMALL_SCALE, color=self.COLOR_DIM)

        # ═══════════════════════ BOTTOM BAR ═══════════════════════
        self._create_element("fps", "FPS: 60", self.TEXT_X, -1.90,
                             scale=self.SMALL_SCALE, color=self.COLOR_DIM)

        self._create_element("controls",
                             "WASD/QE Move  Space Pause  R Reset\nModes: [1] Normal  [2] Occ Demo  [3] Lights",
                             self.TEXT_X, -1.95,
                             scale=max(0.018, min(0.024, self.PANEL_WIDTH * 0.025)), color=self.COLOR_DIM)

    def _create_element(self, name, text, x, y, scale=0.04, color=(1, 1, 1, 1)):
        """Create a text element."""
        text_node = TextNode(name)
        text_node.setText(text)
        text_node.setTextColor(*color)
        text_node.setAlign(TextNode.ALeft)
        text_node.setTextScale(scale)

        # Attach to a2dTopLeft instead of aspect2d center
        text_np = self.app.a2dTopLeft.attachNewNode(text_node)
        text_np.setPos(x, 0, y)
        text_np.setBin("gui-popup", 10)  # Render above background

        self.text_elements[name] = {
            "node": text_node,
            "nodepath": text_np,
            "last_text": text,
            "last_color": color
        }

    def _set_text(self, element_name, text, color=None):
        """Update text content and optionally color."""
        if element_name not in self.text_elements:
            return

        element = self.text_elements[element_name]

        if element["last_text"] != text:
            element["node"].setText(text)
            element["last_text"] = text

        if color is not None and element["last_color"] != color:
            element["node"].setTextColor(*color)
            element["last_color"] = color

    def _setup_room_selector(self):
        """Set up keyboard handlers for room selection."""
        for i in range(10):
            self.app.accept(str(i), self.select_room, [i])

    def select_room(self, room_id: int):
        """Select a room to display information for."""
        if 0 <= room_id <= self.selected_room_max_id:
            self.selected_room_id = room_id
            # Notify scene to highlight room
            if hasattr(self.app, 'scene'):
                self.app.scene.select_room(room_id)

    def update(self, simulation_state: dict, graphics_effects=None):
        """Update dashboard with current simulation state."""
        if "rooms" in simulation_state:
            room_ids = list(simulation_state["rooms"].keys())
            self.selected_room_max_id = max(room_ids) if room_ids else 4

        # ─────── TIME SECTION ───────
        if "time" in simulation_state and "speed_factor" in simulation_state:
            time_str = simulation_state["time"]
            speed = simulation_state["speed_factor"]
            day = simulation_state.get("day", 0)
            self._set_text("sim_date_time", f"Time: {time_str} (Day {day})")
            self._set_text("sim_speed", f"Speed: {speed:.1f}x")

        is_paused = simulation_state.get("paused", False)
        if is_paused:
            self._set_text("sim_status", "[ PAUSED ]", self.COLOR_WARNING)
        else:
            self._set_text("sim_status", "[ RUNNING ]", self.COLOR_HIGHLIGHT)

        # Weather
        weather_status = "Clear"
        outdoor_temp = simulation_state.get("outdoor_temperature", 20.0)
        if graphics_effects and graphics_effects.is_raining():
            weather_status = f"Rain ({graphics_effects.get_rain_intensity():.0%})"
        elif graphics_effects and graphics_effects.is_windy():
            weather_status = f"Wind ({graphics_effects.get_wind_strength():.0%})"
        self._set_text("sim_weather", f"Weather: {weather_status} | {outdoor_temp:.1f}°C")

        # ─────── ROOM & SENSOR SECTIONS ───────
        if "rooms" in simulation_state:
            rooms = simulation_state["rooms"]

            if self.selected_room_id in rooms:
                room_state = rooms[self.selected_room_id]
                zone_type = room_state.get("zone_type", room_state.get("type", "Unknown"))
                room_name = room_state.get("name", f"Room {self.selected_room_id}")

                self._set_text("room_name",
                               f"Room {self.selected_room_id} — {room_name}",
                               self.COLOR_INFO)

                self._set_text("room_type",
                               f"Type: {zone_type.capitalize()}",
                               self.COLOR_LABEL)

                # Sensor data with color coding
                temp = room_state.get("temperature", 20.0)
                humidity = room_state.get("humidity", 50.0)
                co2 = room_state.get("co2", 400)
                occupancy = room_state.get("occupancy", 0)
                max_occ = room_state.get("max_occupancy", room_state.get("occupancy_max", 4))

                self._set_text("sensor_temp", f"Temp: {temp:.1f}°C",
                               self._temp_color(temp))
                self._set_text("sensor_humidity", f"Humidity: {humidity:.0f}%",
                               self._humidity_color(humidity))
                self._set_text("sensor_co2", f"CO2: {int(co2)} ppm",
                               self._co2_color(co2))
                self._set_text("sensor_occupancy",
                               f"Occupancy: {int(occupancy)}/{int(max_occ)}",
                               self.COLOR_HIGHLIGHT if occupancy > 0.5 else self.COLOR_NEUTRAL)
                               
                # TEMPORARY LOG FOR OCCUPANCY SYNCHRONIZATION 
                import time
                current_time = time.time()
                if not hasattr(self, "_last_debug_log") or current_time - getattr(self, "_last_debug_log") > 2.0:
                    if self.selected_room_id == 0:
                        setattr(self, "_last_debug_log", current_time)
                        print(f"\n[SYNC CHECK] Room 0 | Engine: {occupancy} | Visual Markers: {int(round(occupancy))} | UI: {int(occupancy)}")

                # Control decisions
                light_on = room_state.get("light_on", False)
                occupancy = room_state.get("occupancy", 0)
                lux = room_state.get("light_level", 0.0)
                lux_threshold = room_state.get("light_threshold", 400.0)
                
                light_status_str = "ON" if light_on else "OFF"
                debug_info = f" (Occ:{int(occupancy)}|Lux:{lux:.0f}/{lux_threshold:.0f})"
                
                # Active optimization highlight for lighting
                if not light_on and occupancy <= 0:
                    self._set_text("decision_light", f"Light: {light_status_str} [ECO]{debug_info}", (0.3, 0.9, 0.5, 1.0))
                else:
                    self._set_text("decision_light", f"Light: {light_status_str}{debug_info}",
                                  (1.0, 0.9, 0.3, 1.0) if light_on else self.COLOR_NEUTRAL)

                hvac_mode = room_state.get("hvac_mode", "off").upper()
                hvac_speed = room_state.get("hvac_speed", 0.0) * 100
                hvac_color = self._hvac_color(hvac_mode)
                self._set_text("decision_hvac",
                               f"HVAC: {hvac_mode} {hvac_speed:.0f}%",
                               hvac_color)

                shading = room_state.get("shading_factor", 0.0) * 100
                self._set_text("decision_shading", f"Shading: {shading:.0f}%")

                comfort = room_state.get("comfort_index", 50)
                self._set_text("decision_comfort",
                               f"Comfort: {int(comfort)}/100",
                               self._comfort_color(comfort))
                               
                # Energy usage bar (visual representation stripped of unicode boxes)
                energy = room_state.get("energy_use", 0.0)
                energy_color = self.COLOR_VALUE
                if energy >= 80:
                    energy_color = self.COLOR_CRITICAL
                elif energy <= 20:
                    energy_color = (0.3, 0.9, 0.5, 1.0) # Green for low energy
                    
                self._set_text("decision_energy", 
                               f"Load: {energy:.0f} W", 
                               energy_color)

                # Decision reasoning (integrated from decision_display)
                reason = room_state.get("decision_reason", "—")
                # Highlight active reasons showing cause-effect
                reason_color = self.COLOR_HIGHLIGHT if "empty" in reason.lower() or "saving" in reason.lower() else self.COLOR_DIM
                
                # Truncate long reasons
                if len(reason) > 60:
                    reason = reason[:57] + "..."
                self._set_text("decision_reason", f"Decision: {reason}", reason_color)

        # Strategy info (from engine)
        if hasattr(self.app, 'simulation_engine'):
            strategy = self.app.simulation_engine.decision_engine.get_strategy_name()
            self._set_text("decision_strategy", f"Strategy: {strategy}")

        # ─────── FPS ───────
        from panda3d.core import ClockObject
        clock = ClockObject.getGlobalClock()
        fps = clock.getAverageFrameRate()
        self._set_text("fps", f"FPS: {fps:.0f}")

    # ═══════════ Color helpers ═══════════

    def _temp_color(self, temp):
        if 18 <= temp <= 24:
            return self.COLOR_HIGHLIGHT
        elif 16 <= temp < 18 or 24 < temp <= 26:
            return self.COLOR_WARNING
        else:
            return self.COLOR_CRITICAL

    def _humidity_color(self, h):
        if 30 <= h <= 60:
            return self.COLOR_HIGHLIGHT
        elif 20 <= h < 30 or 60 < h <= 70:
            return self.COLOR_WARNING
        else:
            return self.COLOR_CRITICAL

    def _co2_color(self, co2):
        if co2 < 600:
            return self.COLOR_HIGHLIGHT
        elif co2 < 1000:
            return self.COLOR_WARNING
        else:
            return self.COLOR_CRITICAL

    def _hvac_color(self, mode):
        m = mode.lower()
        if m == "heating":
            return (1.0, 0.55, 0.2, 1.0)
        elif m == "cooling":
            return (0.3, 0.75, 1.0, 1.0)
        elif m == "fan":
            return self.COLOR_NEUTRAL
        else:
            return self.COLOR_VALUE

    def _comfort_color(self, c):
        if c >= 75:
            return self.COLOR_HIGHLIGHT
        elif c >= 50:
            return self.COLOR_WARNING
        else:
            return self.COLOR_CRITICAL

    def pause(self):
        self._set_text("sim_status", "⏸ PAUSED", self.COLOR_WARNING)

    def resume(self):
        self._set_text("sim_status", "● RUNNING", self.COLOR_HIGHLIGHT)


# Backward compatibility
class HUD(DashboardUI):
    """Alias for backward compatibility."""
    pass
