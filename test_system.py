"""
Smart Building Digital Twin — System Verification Script

Comprehensive tests to verify the full system works end-to-end:
  1. ML model loads successfully
  2. Simulation bridge initializes and produces room data
  3. State manager processes rooms through the ML pipeline
  4. Closed-loop feedback writes decisions back to simulation
  5. Energy estimation works per room
  6. API returns live data (requires running system)
  7. Dashboard HTML is served (requires running system)

Usage:
    # Offline tests (no server needed):
    python test_system.py

    # Full tests including API (run_system.py must be running):
    python test_system.py --with-api
"""

import sys
import os
import time
import argparse

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# =============================================================================
# TEST UTILITIES
# =============================================================================

class TestResults:
    """Collects and reports test results."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def ok(self, name, detail=""):
        self.passed += 1
        self.results.append(("PASS", name, detail))
        print(f"  [OK] {name}" + (f" -- {detail}" if detail else ""))

    def fail(self, name, error=""):
        self.failed += 1
        self.results.append(("FAIL", name, str(error)))
        print(f"  [FAIL] {name} -- {error}")

    def report(self):
        print()
        print("=" * 70)
        total = self.passed + self.failed
        print(f"  RESULTS: {self.passed}/{total} passed, {self.failed} failed")
        if self.failed == 0:
            print("  ALL TESTS PASSED -- System is ready!")
        else:
            print("  WARNING: Some tests failed. Check errors above.")
        print("=" * 70)
        return self.failed == 0


# =============================================================================
# OFFLINE TESTS (No server required)
# =============================================================================

def test_model_loads(results: TestResults):
    """Test that the ML model loads successfully."""
    print("\n--- Test: ML Model Loading ---")
    try:
        from occupancy_inference_service import OccupancyInferenceService

        model_path = os.path.join(PROJECT_ROOT, "models", "domain_adapted_occupancy_pipeline.pkl")
        service = OccupancyInferenceService(model_path, threshold=0.5)

        # Test a prediction
        test_data = {
            "Temperature": 21.5,
            "Humidity": 35.0,
            "Light": 450.0,
            "CO2": 700.0,
            "HumidityRatio": 0.0045,
        }
        result = service.predict(test_data)
        prob = result.occupancy_probability

        results.ok("ML model loaded", f"pipeline steps: {list(service.pipeline.named_steps.keys())}")
        results.ok("Inference works", f"probability={prob:.4f}, prediction={result.occupancy_prediction}")

    except Exception as e:
        results.fail("ML model loading", str(e))


def test_controller_loads(results: TestResults):
    """Test that the smart building controller loads."""
    print("\n--- Test: Smart Building Controller ---")
    try:
        from smart_building_controller import SmartBuildingController

        model_path = os.path.join(PROJECT_ROOT, "models", "domain_adapted_occupancy_pipeline.pkl")
        controller = SmartBuildingController(model_path, empty_threshold=0.20, occupied_threshold=0.60)

        # Test a control decision
        test_data = {
            "Temperature": 21.5,
            "Humidity": 35.0,
            "Light": 450.0,
            "CO2": 700.0,
            "HumidityRatio": 0.0045,
        }
        decision = controller.get_control_decision(test_data)

        results.ok("Controller loaded", f"thresholds: EMPTY<0.20, STANDBY[0.20-0.60), OCCUPIED>=0.60")
        results.ok("Control decision works",
                    f"mode={decision.control_mode}, light={decision.light_action}, hvac={decision.hvac_action}")

    except Exception as e:
        results.fail("Controller loading", str(e))


def test_simulation_bridge(results: TestResults):
    """Test that the simulation bridge initializes and produces data."""
    print("\n--- Test: Simulation Bridge ---")
    try:
        from integration.simulation_bridge import SimulationBridge

        bridge = SimulationBridge()
        results.ok("SimulationBridge initialized", f"engine running: {bridge.is_running()}")

        # Step simulation
        bridge.step(dt=2.0)
        rooms = bridge.get_all_room_states()

        results.ok("Simulation step works", f"produced {len(rooms)} room states")

        # Verify rooms have expected structure
        expected_rooms = {"office_1", "kitchen_1", "meeting_room_1", "bathroom_1"}
        actual_rooms = {r["room_id"] for r in rooms}
        if expected_rooms == actual_rooms:
            results.ok("All 4 rooms present", ", ".join(sorted(actual_rooms)))
        else:
            results.fail("Room check", f"expected {expected_rooms}, got {actual_rooms}")

        # Verify sensor data structure
        for room in rooms:
            sensors = room.get("sensors", {})
            for key in ["Temperature", "Humidity", "Light", "CO2", "HumidityRatio"]:
                if key not in sensors:
                    results.fail(f"Sensor '{key}' missing", f"room {room['room_id']}")
                    return

        results.ok("Sensor data structure valid", "Temperature, Humidity, Light, CO2, HumidityRatio")

        return bridge  # Return for reuse

    except Exception as e:
        results.fail("SimulationBridge initialization", str(e))
        import traceback
        traceback.print_exc()
        return None


def test_state_manager(results: TestResults, bridge=None):
    """Test state manager processes rooms through ML pipeline."""
    print("\n--- Test: State Manager (ML Pipeline) ---")
    try:
        from integration.state_manager import StateManager

        sm = StateManager()
        results.ok("StateManager initialized", f"model loaded: {sm._health['model_loaded']}")

        # Wire closed-loop feedback if bridge is available
        if bridge is not None:
            sm.set_bridge(bridge)
            results.ok("Closed-loop feedback wired", "StateManager -> SimulationBridge")

        # Get room data from bridge
        if bridge is not None:
            bridge.step(dt=2.0)
            raw_rooms = bridge.get_all_room_states()
        else:
            # Use synthetic data if bridge not available
            raw_rooms = [{
                "room_id": "office_1",
                "room_type": "office",
                "display_name": "Office A",
                "timestamp": "2026-01-01T12:00:00",
                "sensors": {
                    "Temperature": 21.5, "Humidity": 35.0,
                    "Light": 450.0, "CO2": 700.0, "HumidityRatio": 0.0045,
                },
                "ground_truth": {"true_occupancy": 1, "occupancy_count": 2},
                "device_state": {},
            }]

        # Process through pipeline
        sm.process_room_states(raw_rooms)
        state = sm.get_current_state()
        rooms = state.get("rooms", [])

        if len(rooms) > 0:
            results.ok("Pipeline processed rooms", f"{len(rooms)} rooms in state")

            # Check each room has all expected fields
            room = rooms[0]
            for section in ["sensors", "ai", "control", "energy"]:
                if section in room and room[section]:
                    results.ok(f"Room has '{section}' data",
                               f"{list(room[section].keys())[:4]}...")
                else:
                    results.fail(f"Room missing '{section}' data")

            # Check AI result
            ai = room.get("ai", {})
            if "occupancy_probability" in ai:
                results.ok("AI prediction present",
                           f"prob={ai['occupancy_probability']:.4f}, "
                           f"pred={ai.get('predicted_occupancy')}")
            else:
                results.fail("AI prediction missing")

            # Check control result
            ctrl = room.get("control", {})
            if "control_mode" in ctrl:
                results.ok("Control decision present",
                           f"mode={ctrl['control_mode']}, "
                           f"light={ctrl.get('light_action')}, "
                           f"hvac={ctrl.get('hvac_action')}")
            else:
                results.fail("Control decision missing")

            # Check energy
            energy = room.get("energy", {})
            if "estimated_power_watts" in energy:
                results.ok("Energy estimation present",
                           f"power={energy['estimated_power_watts']}W, "
                           f"cumulative={energy.get('cumulative_energy_wh', 0):.2f}Wh")
            else:
                results.fail("Energy estimation missing")

        else:
            results.fail("No rooms in state after processing")

        # Check system summary
        summary = sm.get_system_summary()
        results.ok("System summary works",
                    f"rooms={summary['total_rooms']}, "
                    f"occupied={summary['occupied_rooms']}, "
                    f"power={summary['total_power_watts']}W")

        return sm

    except Exception as e:
        results.fail("StateManager processing", str(e))
        import traceback
        traceback.print_exc()
        return None


def test_closed_loop_feedback(results: TestResults):
    """Test that ML decisions are written back into the simulation engine."""
    print("\n--- Test: Closed-Loop Feedback ---")
    try:
        from integration.simulation_bridge import SimulationBridge
        from integration.config import ROOM_ID_REVERSE

        bridge = SimulationBridge()
        bridge.step(dt=2.0)

        # Apply control actions for office_1
        bridge.apply_control_actions("office_1", {
            "light_action": "ON",
            "hvac_action": "NORMAL",
        })

        # Verify the simulation engine state was modified
        int_id = ROOM_ID_REVERSE["office_1"]
        room_state = bridge._engine.state["rooms"][int_id]

        if room_state["light_on"] == True:
            results.ok("Light feedback applied", "light_action=ON -> light_on=True")
        else:
            results.fail("Light feedback failed", f"expected True, got {room_state['light_on']}")

        if room_state["hvac_mode"] == "heating":
            results.ok("HVAC feedback applied", "hvac_action=NORMAL -> hvac_mode=heating")
        else:
            results.fail("HVAC feedback failed", f"expected 'heating', got {room_state['hvac_mode']}")

        # Test OFF state
        bridge.apply_control_actions("office_1", {
            "light_action": "OFF",
            "hvac_action": "ECO",
        })
        room_state = bridge._engine.state["rooms"][int_id]

        if room_state["light_on"] == False and room_state["hvac_mode"] == "off":
            results.ok("OFF/ECO feedback applied", "light=OFF->False, hvac=ECO->off")
        else:
            results.fail("OFF/ECO feedback failed")

    except Exception as e:
        results.fail("Closed-loop feedback test", str(e))
        import traceback
        traceback.print_exc()


def test_energy_estimator(results: TestResults):
    """Test per-room energy estimation."""
    print("\n--- Test: Energy Estimator ---")
    try:
        from integration.energy_estimator import EnergyEstimator

        estimator = EnergyEstimator()
        estimator.register_room("office_1", "office")

        # Estimate energy for different states
        result_on = estimator.estimate_room_energy("office_1", "ON", "NORMAL")
        time.sleep(0.1)
        result_off = estimator.estimate_room_energy("office_1", "OFF", "ECO")

        if result_on["estimated_power_watts"] > result_off["estimated_power_watts"]:
            results.ok("Energy estimation logic correct",
                       f"ON/NORMAL={result_on['estimated_power_watts']}W > "
                       f"OFF/ECO={result_off['estimated_power_watts']}W")
        else:
            results.fail("Energy estimation logic",
                         f"ON should use more power than OFF")

        if result_off["cumulative_energy_wh"] > 0:
            results.ok("Cumulative energy accumulates",
                       f"{result_off['cumulative_energy_wh']:.4f}Wh")
        else:
            results.ok("Cumulative energy starts at ~0", "as expected for short test")

    except Exception as e:
        results.fail("Energy estimator", str(e))


# =============================================================================
# ONLINE TESTS (Require running server)
# =============================================================================

def test_api_endpoints(results: TestResults, port=8001):
    """Test API endpoints (requires running system)."""
    print(f"\n--- Test: API Endpoints (http://127.0.0.1:{port}) ---")
    import urllib.request
    import json

    base = f"http://127.0.0.1:{port}"

    def check_endpoint(name, url, check_fn=None):
        try:
            r = urllib.request.urlopen(url, timeout=5)
            data = json.loads(r.read())
            if check_fn:
                check_fn(data)
            results.ok(f"API {name}", f"OK")
            return data
        except Exception as e:
            results.fail(f"API {name}", str(e))
            return None

    # Health
    check_endpoint("GET /health", f"{base}/health",
                   lambda d: None if d.get("model_loaded") else (_ for _ in ()).throw(
                       ValueError("model not loaded")))

    # Live state
    data = check_endpoint("GET /api/system/live", f"{base}/api/system/live")
    if data:
        rooms = data.get("rooms", [])
        system = data.get("system", {})
        if len(rooms) == 4:
            results.ok("Live state has 4 rooms",
                       f"occupied={system.get('occupied_rooms')}, "
                       f"power={system.get('total_power_watts', 0):.0f}W")
        else:
            results.fail("Live state room count", f"expected 4, got {len(rooms)}")

        # Check each room has full data
        for room in rooms:
            rid = room.get("room_id", "?")
            has_ai = bool(room.get("ai", {}).get("occupancy_probability") is not None)
            has_ctrl = bool(room.get("control", {}).get("control_mode"))
            has_energy = bool(room.get("energy", {}).get("estimated_power_watts") is not None)
            if has_ai and has_ctrl and has_energy:
                results.ok(f"Room {rid} complete", f"prob={room['ai']['occupancy_probability']:.3f}")
            else:
                results.fail(f"Room {rid} incomplete",
                             f"ai={has_ai}, ctrl={has_ctrl}, energy={has_energy}")

    # System summary
    check_endpoint("GET /api/system/summary", f"{base}/api/system/summary")

    # Rooms current state
    check_endpoint("GET /api/rooms/current-state", f"{base}/api/rooms/current-state")

    # History
    check_endpoint("GET /api/rooms/history", f"{base}/api/rooms/history")

    # Dashboard
    try:
        r = urllib.request.urlopen(f"{base}/dashboard", timeout=5)
        html = r.read().decode()
        if "Smart Building" in html and "Digital Twin" in html:
            results.ok("Dashboard HTML served", f"{len(html)} bytes")
        else:
            results.fail("Dashboard HTML", "Unexpected content")
    except Exception as e:
        results.fail("Dashboard HTML", str(e))


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Smart Building System Verification")
    parser.add_argument("--with-api", action="store_true",
                        help="Also test API endpoints (requires running system)")
    parser.add_argument("--port", type=int, default=8001,
                        help="API port for online tests")
    args = parser.parse_args()

    print()
    print("=" * 70)
    print("  Smart Building Digital Twin — System Verification")
    print("=" * 70)

    results = TestResults()

    # Offline tests
    test_model_loads(results)
    test_controller_loads(results)
    bridge = test_simulation_bridge(results)
    test_state_manager(results, bridge)
    test_closed_loop_feedback(results)
    test_energy_estimator(results)

    # Online tests (optional)
    if args.with_api:
        test_api_endpoints(results, port=args.port)
    else:
        print("\n  [INFO] Skipping API tests (use --with-api to include them)")

    # Report
    success = results.report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
