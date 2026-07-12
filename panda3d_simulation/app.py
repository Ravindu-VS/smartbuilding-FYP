"""
Main Panda3D Application Class

Handles window setup, event loop, frame updates, and main simulation loop.
Integrates sky system, graphics effects, and dynamic room rendering.

IPC Integration:
    This app is the OWNER of the real simulation engine.
    It writes raw simulation state to output/.sim_state.json every frame.
    It reads ML control actions from output/.control_actions.json and
    applies them back into the simulation engine for closed-loop control.
"""

from direct.showbase.ShowBase import ShowBase
from panda3d.core import WindowProperties, load_prc_file_data, AntialiasAttrib, Vec4
import sys
import os
import time

from panda3d_simulation.scene import Scene
from panda3d_simulation.camera import CameraControl
from panda3d_simulation.ui import HUD
from panda3d_simulation.sky_system import SkySystem
from panda3d_simulation.graphics_effects import GraphicsEffects
from panda3d_simulation.actuator_effects import ActuatorEffectsManager
from panda3d_simulation.actuator_visualizer import ActuatorVisualizerManager
from panda3d_simulation.decision_display import DecisionDisplay
from panda3d_simulation.lighting_manager import LightingManager
from panda3d_simulation.post_processing import PostProcessingPipeline, AdvancedRenderingConfig
from simulation.engine import SimulationEngine

# Two-way IPC for backend integration
try:
    from integration.simulation_ipc import (
        SimulationStateWriter, ControlActionReader, cleanup_ipc_files
    )
    from integration.config import (
        ROOM_ID_MAP, SIM_STATE_WRITE_INTERVAL,
        LIGHT_ACTION_TO_SIM, HVAC_ACTION_TO_SIM,
    )
    _IPC_AVAILABLE = True
except ImportError:
    _IPC_AVAILABLE = False


class SmartBuildingSimApp(ShowBase):
    """
    Main Panda3D application for smart building 3D visualization.
    """

    def __init__(self, config: dict = None):
        try:
            self._configure_panda3d()
            ShowBase.__init__(self)
        except Exception as e:
            print(f"\n[X] ERROR during ShowBase init: {e}")
            import traceback
            traceback.print_exc()
            raise

        self.app_config = config or {}
        self.running = True
        self.paused = False

        # IPC: Two-way communication with backend
        self._ipc_writer = None
        self._ipc_reader = None
        self._ipc_last_write_time = 0.0
        self._ipc_write_interval = SIM_STATE_WRITE_INTERVAL if _IPC_AVAILABLE else 0.1
        self.test_mode = 0  # 0=Normal, 1=Occupancy Demo, 2=Lights Test

        try:
            self._init_window()
            self._init_graphics()

            self.simulation_engine = SimulationEngine(config=self.app_config)

            # Sky system
            self.sky_system = SkySystem(parent_node=self.render)

            # Weather effects
            self.graphics_effects = GraphicsEffects(parent_node=self.render)

            # 3D Scene (pass room configs for dynamic loading)
            self.scene = Scene(self.render, room_configs=self.simulation_engine.room_configs)

            # Camera (auto-centers on building)
            self.camera_control = CameraControl(self)

            # Set up display regions to split UI and 3D scene
            self._setup_display_regions()

            # HUD dashboard (left side UI)
            self.hud = HUD(self)

            # Actuator visual effects
            self.actuator_effects = ActuatorEffectsManager(self.scene, self.render)

            # Actuator → geometry bridge
            self.actuator_visualizer = ActuatorVisualizerManager(self.scene, self.actuator_effects)

            # Decision display (integrated into HUD)
            self.decision_display = DecisionDisplay(self)

            # Initialize IPC for backend integration
            if _IPC_AVAILABLE:
                try:
                    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    self._ipc_writer = SimulationStateWriter(project_root=project_root)
                    self._ipc_reader = ControlActionReader(project_root=project_root)
                    print(f"  IPC: State writer → {self._ipc_writer.filepath}")
                    print(f"  IPC: Control reader ← {self._ipc_reader.filepath}")
                except Exception as e:
                    print(f"  IPC: Initialization failed ({e}), 3D-only mode")
                    self._ipc_writer = None
                    self._ipc_reader = None

            # Post-processing (color grading only)
            self.post_processing = PostProcessingPipeline(self, self.actuator_effects)
            AdvancedRenderingConfig.apply_preset(self.post_processing, "balanced")

            # Register update task
            self.taskMgr.add(self._update_frame, "update_frame")

            # Enable antialiasing
            self.render.setAntialias(AntialiasAttrib.MAuto)
            
            # Hotkeys for test scenarios
            self.accept("1", self.set_test_mode, [0])
            self.accept("2", self.set_test_mode, [1])
            self.accept("3", self.set_test_mode, [2])

            print("\n" + "=" * 60)
            print("  Smart Building Digital Twin — Ready")
            print(f"  Window: {self.win.getXSize()}x{self.win.getYSize()}")
            print(f"  Rooms: {len(self.scene.rooms)}")
            print(f"  Strategy: {self.simulation_engine.decision_engine.get_strategy_name()}")
            print("=" * 60)

        except Exception as e:
            print(f"\n[X] ERROR during initialization: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _configure_panda3d(self):
        """Configure Panda3D settings before initialization."""
        load_prc_file_data(
            "",
            """
            window-title Smart Building Digital Twin
            win-size 1600 900
            fullscreen false
            framebuffer-multisample 1
            multisamples 4
            """
        )

    def _init_window(self):
        """Initialize window properties."""
        props = WindowProperties()
        props.setTitle("Smart Building Digital Twin — 3D Simulation")
        self.win.requestProperties(props)
        self.setBackgroundColor(0.06, 0.06, 0.09, 1.0) # Dark base color for sidebar background

    def _init_graphics(self):
        """Initialize graphics and lighting."""
        self.render.setShaderAuto()
        self.lighting_manager = LightingManager(self.render)
        self.ambient_light = self.lighting_manager.ambient_light
        self.ambient_light_np = self.lighting_manager.ambient_node

    def _setup_display_regions(self):
        """Split the screen so 3D renders on the right 75%, leaving left 25% for UI."""
        # Main UI uses aspect2d which spans the entire window by default
        
        # Shrink the 3D camera display region
        dr = self.cam.node().getDisplayRegion(0)
        dr.setDimensions(0.25, 1.0, 0.0, 1.0)
        
        # Create a background color specifically for the 3D region (sky color)
        # Showbase background color will show in the 25% gap
        dr.setClearColorActive(True)
        dr.setClearColor((0.5, 0.7, 0.95, 1.0))
        self.scene_dr = dr
        
        # Override Showbase's automatic aspect ratio adjustment
        # to account for the shrunk display region
        self.accept("window-event", self._on_window_resize)
        # Initial call
        self._on_window_resize(self.win)

    def _on_window_resize(self, window):
        """Handle window resize to fix 3D aspect ratio."""
        if window is not None:
            wp = window.getProperties()
            if wp.hasSize():
                width = wp.getXSize()
                height = wp.getYSize()
                if height > 0:
                    # Aspect ratio of the 3D portion (75% of width)
                    aspect_ratio = (width * 0.75) / height
                    self.camLens.setAspectRatio(aspect_ratio)

    def _update_frame(self, task):
        """Main frame update loop."""
        dt = globalClock.getDt()

        if not self.paused:
            # Read and apply backend ML control actions BEFORE engine update
            # This closes the loop: Backend ML → control file → sim engine
            self._apply_backend_control_actions()

            # Update simulation (Panda3D OWNS the simulation engine)
            self.simulation_engine.update(dt)
            sim_state = self.simulation_engine.state

            # Override state for visual demo/testing triggers
            if self.test_mode > 0:
                self._apply_test_mode_overrides(sim_state)

            # Publish room config data alongside room state
            self._enrich_room_state(sim_state)

            # Write simulation state to IPC file for backend (throttled)
            self._write_ipc_state(sim_state)

            # Sky color applied only to the 3D display region
            sky_color = self.sky_system.update(
                sun_altitude=sim_state.get("sun_altitude", 0),
                cloud_cover=sim_state.get("weather", {}).get("cloud_cover", 0)
            )
            self.scene_dr.setClearColor(sky_color)

            # Dynamic lighting
            self.lighting_manager.update(
                sun_altitude=sim_state.get("sun_altitude", 0),
                cloud_cover=sim_state.get("weather", {}).get("cloud_cover", 0)
            )

            # Weather effects
            self.graphics_effects.update(
                precipitation=sim_state.get("weather", {}).get("precipitation", 0),
                wind_speed=sim_state.get("weather", {}).get("wind_speed", 0),
                cloud_cover=sim_state.get("weather", {}).get("cloud_cover", 0)
            )

            # 3D scene update
            self.scene.update(sim_state, dt)

            # Actuator effects
            self.actuator_effects.update(sim_state, dt)
            self.actuator_visualizer.update(dt)

            # HUD
            self.hud.update(sim_state, self.graphics_effects)

            # Decision display
            self.decision_display.update(sim_state, self.hud.selected_room_id)

            # Post-processing (color grading)
            self.post_processing.update(sim_state, dt)

            # Camera
            self.camera_control.update()

        return task.cont

    def _write_ipc_state(self, sim_state: dict):
        """
        Write simulation state to IPC file for backend consumption.
        Throttled to avoid saturating disk I/O.
        """
        if self._ipc_writer is None:
            return

        now = time.time()
        if (now - self._ipc_last_write_time) < self._ipc_write_interval:
            return  # Throttle writes

        try:
            self._ipc_writer.write_state(sim_state)
            self._ipc_last_write_time = now
        except Exception as e:
            # Never crash the 3D app due to IPC errors
            pass

    def _apply_backend_control_actions(self):
        """
        Read ML control actions from the backend IPC file and apply them
        to the simulation engine. This closes the control loop:

            Sim state → Backend ML → Predictions → Control → Back to Sim

        Maps string room IDs (e.g., 'office_1') back to integer engine IDs
        and converts controller actions (light_action, hvac_action) to
        simulation engine state variables (light_on, hvac_mode, hvac_speed).
        """
        if self._ipc_reader is None or not _IPC_AVAILABLE:
            return

        if not self._ipc_reader.has_new_actions():
            return

        actions = self._ipc_reader.read_actions()
        if not actions:
            return

        # Build reverse map: string room ID → integer engine room ID
        reverse_map = {v: k for k, v in ROOM_ID_MAP.items()}

        for room_str_id, control in actions.items():
            int_id = reverse_map.get(room_str_id)
            if int_id is None:
                continue

            room = self.simulation_engine.state.get("rooms", {}).get(int_id)
            if room is None:
                continue

            try:
                # Apply light action → simulation light_on state
                light_action = control.get("light_action", "OFF")
                room["light_on"] = LIGHT_ACTION_TO_SIM.get(light_action, False)

                # Apply HVAC action → simulation hvac_mode + hvac_speed
                hvac_action = control.get("hvac_action", "ECO")
                hvac_sim = HVAC_ACTION_TO_SIM.get(
                    hvac_action, {"hvac_mode": "off", "hvac_speed": 0.0}
                )
                room["hvac_mode"] = hvac_sim["hvac_mode"]
                room["hvac_speed"] = hvac_sim["hvac_speed"]
            except Exception:
                pass  # Never crash 3D app due to control action errors

    def _enrich_room_state(self, sim_state):
        """Add room config metadata to state so UI can display it."""
        if "rooms" not in sim_state:
            return

        for room_config in self.simulation_engine.room_configs:
            rid = room_config.room_id
            if rid in sim_state["rooms"]:
                rs = sim_state["rooms"][rid]
                rs["width"] = room_config.dimensions.get("width", 6)
                rs["depth"] = room_config.dimensions.get("depth", 6)
                rs["height"] = room_config.dimensions.get("height", 3)
                rs["type"] = room_config.zone_type

        # Calculate day number
        elapsed_hours = self.simulation_engine.elapsed_time / 3600.0
        sim_state["day"] = int(elapsed_hours / 24)

    def _apply_test_mode_overrides(self, sim_state):
        """Inject forced constraints into the simulation representation without corrupting the engine."""
        if "rooms" not in sim_state:
            return
            
        import math
        time = globalClock.getFrameTime()
        
        for rid, room in sim_state["rooms"].items():
            if self.test_mode == 2:
                room["light_on"] = True
                room["occupancy"] = 0.0 # Clear humans to verify pure light behavior
                
            elif self.test_mode == 1:
                # Forced occupancy demo mode
                cfg = next((rc for rc in self.simulation_engine.room_configs if rc.room_id == rid), None)
                max_o = float(getattr(cfg, 'max_occupancy', 4.0)) if cfg else 4.0
                
                if rid == 0:
                    room["occupancy"] = 2.0
                elif rid == 1:
                    room["occupancy"] = 1.0 if math.sin(time / 2.0) > 0 else 0.0
                elif rid == 2:
                    room["occupancy"] = 1.0
                elif rid == 3:
                    room["occupancy"] = 1.0 if math.sin(time / 5.0) > 0.8 else 0.0

    def toggle_pause(self):
        """Toggle simulation pause state."""
        self.paused = not self.paused
        state_str = "PAUSED" if self.paused else "RUNNING"
        print(f"Simulation: {state_str}")

    def set_test_mode(self, mode: int):
        """Switch visual testing mode."""
        self.test_mode = mode
        modes = ["NORMAL ENGINE", "FORCED OCCUPANCY DEMO", "LIGHTS TEST"]
        print(f"\n[!] HOTKEY TRIGGERED: Switching to {modes[mode]} mode.")

    def _app_shutdown(self):
        """Clean shutdown."""
        print("\nShutting down...")
        self.running = False
        # Clean up IPC files so backend detects disconnection
        if _IPC_AVAILABLE:
            try:
                cleanup_ipc_files()
            except Exception:
                pass
        self.userExit()


def create_app(config: dict = None) -> SmartBuildingSimApp:
    """Factory function to create the application."""
    return SmartBuildingSimApp(config=config)
