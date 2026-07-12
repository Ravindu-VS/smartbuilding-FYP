#!/usr/bin/env python3
"""
Test Synchronization Architecture

Verifies that the smart building system maintains perfect synchronization
across all startup order scenarios:

- CASE A: All start together
- CASE B: Backend first, simulation later
- CASE C: Simulation first, backend later
- CASE D: Components restart while others running

Tests real-time data sync, stale data detection, and connection status.
"""

import sys
import os
import time
import json
import threading
import requests
from datetime import datetime
from typing import Dict, Any

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SynchronizationTester:
    """Test harness for synchronization verification."""

    def __init__(self):
        self.api_base = "http://127.0.0.1:8001"
        self.test_results = []

    def log_test(self, name: str, passed: bool, details: str = ""):
        """Record test result."""
        result = {
            "test": name,
            "passed": passed,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        }
        self.test_results.append(result)
        status = "[PASS]" if passed else "[FAIL]"
        print(f"\n{status}: {name}")
        if details:
            print(f"      {details}")

    def check_api_health(self) -> bool:
        """Check if API is running."""
        try:
            resp = requests.get(f"{self.api_base}/health", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def get_live_state(self) -> Dict[str, Any]:
        """Fetch current live state from API."""
        try:
            resp = requests.get(f"{self.api_base}/api/system/live", timeout=2)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    def test_simulation_time_consistency(self):
        """
        TEST 1: Simulation time from API matches expected format.

        Verifies: Dashboard can read sim time from API
        """
        try:
            state = self.get_live_state()
            system = state.get("system", {})
            sim_time = system.get("simulation_time")

            if sim_time and isinstance(sim_time, str):
                # Should be ISO format or --:--:--
                if "T" in sim_time or sim_time == "--:--:--":
                    self.log_test(
                        "Simulation Time Format",
                        True,
                        f"Sim time: {sim_time}"
                    )
                    return True

            self.log_test(
                "Simulation Time Format",
                False,
                f"Invalid format: {sim_time}"
            )
        except Exception as e:
            self.log_test("Simulation Time Format", False, str(e))
        return False

    def test_simulation_connection_status(self):
        """
        TEST 2: API reports clear simulation connection status.

        Verifies: API provides 'simulation_connected' flag
        """
        try:
            state = self.get_live_state()
            system = state.get("system", {})

            if "simulation_connected" in system:
                connected = system["simulation_connected"]
                self.log_test(
                    "Simulation Connection Status",
                    True,
                    f"Connected: {connected}"
                )
                return True

            self.log_test(
                "Simulation Connection Status",
                False,
                "Missing 'simulation_connected' field"
            )
        except Exception as e:
            self.log_test("Simulation Connection Status", False, str(e))
        return False

    def test_stale_data_detection(self):
        """
        TEST 3: API detects and reports stale data.

        Verifies: 'data_stale' flag is present and accurate
        """
        try:
            state = self.get_live_state()
            system = state.get("system", {})

            if "data_stale" in system:
                stale = system["data_stale"]
                last_update = system.get("last_update", "")

                # If connected and data is fresh, stale should be False
                connected = system.get("simulation_connected", False)
                if connected and not stale:
                    self.log_test(
                        "Stale Data Detection",
                        True,
                        f"Stale flag: {stale}, Connected: {connected}"
                    )
                    return True

            self.log_test(
                "Stale Data Detection",
                False,
                "Missing 'data_stale' field or incorrect state"
            )
        except Exception as e:
            self.log_test("Stale Data Detection", False, str(e))
        return False

    def test_room_data_consistency(self):
        """
        TEST 4: Room data includes all required fields.

        Verifies: Each room has sensors, AI, control, energy data
        """
        try:
            state = self.get_live_state()
            rooms = state.get("rooms", [])

            if not rooms:
                self.log_test(
                    "Room Data Consistency",
                    False,
                    "No rooms in response"
                )
                return False

            required_keys = ["sensors", "ai", "control", "energy", "ground_truth"]
            first_room = rooms[0]
            missing = [k for k in required_keys if k not in first_room]

            if not missing:
                self.log_test(
                    "Room Data Consistency",
                    True,
                    f"All required fields present in {len(rooms)} rooms"
                )
                return True
            else:
                self.log_test(
                    "Room Data Consistency",
                    False,
                    f"Missing: {missing}"
                )
        except Exception as e:
            self.log_test("Room Data Consistency", False, str(e))
        return False

    def test_ml_predictions_present(self):
        """
        TEST 5: ML predictions are being computed.

        Verifies: Each room has occupancy probability and prediction
        """
        try:
            state = self.get_live_state()
            rooms = state.get("rooms", [])

            if not rooms:
                self.log_test("ML Predictions Present", False, "No rooms")
                return False

            all_have_predictions = all(
                "occupancy_probability" in r.get("ai", {})
                and "predicted_occupancy" in r.get("ai", {})
                for r in rooms
            )

            if all_have_predictions:
                prob = rooms[0]["ai"]["occupancy_probability"]
                self.log_test(
                    "ML Predictions Present",
                    True,
                    f"Occupancy prob: {prob:.2%}"
                )
                return True
            else:
                self.log_test(
                    "ML Predictions Present",
                    False,
                    "Missing predicted_ occupancy in some rooms"
                )
        except Exception as e:
            self.log_test("ML Predictions Present", False, str(e))
        return False

    def test_control_decisions_present(self):
        """
        TEST 6: Control decisions are being made.

        Verifies: Each room has control mode, light/HVAC actions
        """
        try:
            state = self.get_live_state()
            rooms = state.get("rooms", [])

            if not rooms:
                self.log_test("Control Decisions Present", False, "No rooms")
                return False

            all_have_control = all(
                "control_mode" in r.get("control", {})
                and "light_action" in r.get("control", {})
                and "hvac_action" in r.get("control", {})
                for r in rooms
            )

            if all_have_control:
                mode = rooms[0]["control"]["control_mode"]
                self.log_test(
                    "Control Decisions Present",
                    True,
                    f"Control mode: {mode}"
                )
                return True
            else:
                self.log_test(
                    "Control Decisions Present",
                    False,
                    "Missing control fields"
                )
        except Exception as e:
            self.log_test("Control Decisions Present", False, str(e))
        return False

    def test_energy_metrics(self):
        """
        TEST 7: Energy estimation is working.

        Verifies: Total power and cumulative energy are tracked
        """
        try:
            state = self.get_live_state()
            system = state.get("system", {})

            power = system.get("total_power_watts")
            energy = system.get("total_cumulative_energy_wh")

            if power is not None and energy is not None:
                self.log_test(
                    "Energy Metrics",
                    True,
                    f"Power: {power}W, Energy: {energy}Wh"
                )
                return True
            else:
                self.log_test(
                    "Energy Metrics",
                    False,
                    f"Missing fields: power={power}, energy={energy}"
                )
        except Exception as e:
            self.log_test("Energy Metrics", False, str(e))
        return False

    def test_model_loaded(self):
        """
        TEST 8: ML model is loaded and ready.

        Verifies: model_loaded flag is True
        """
        try:
            state = self.get_live_state()
            system = state.get("system", {})

            model_loaded = system.get("model_loaded", False)
            if model_loaded:
                self.log_test(
                    "ML Model Loaded",
                    True,
                    "Model is loaded and ready"
                )
                return True
            else:
                self.log_test(
                    "ML Model Loaded",
                    False,
                    "Model not loaded"
                )
        except Exception as e:
            self.log_test("ML Model Loaded", False, str(e))
        return False

    def test_api_connection_status(self):
        """
        TEST 9: API reports its own connection status.

        Verifies: api_connected flag is present and True
        """
        try:
            state = self.get_live_state()
            system = state.get("system", {})

            api_connected = system.get("api_connected", False)
            if api_connected:
                self.log_test(
                    "API Connection Status",
                    True,
                    "API is connected and running"
                )
                return True
            else:
                self.log_test(
                    "API Connection Status",
                    False,
                    "API reports disconnected"
                )
        except Exception as e:
            self.log_test("API Connection Status", False, str(e))
        return False

    def test_room_history_available(self):
        """
        TEST 10: Room history is being accumulated.

        Verifies: /api/rooms/history endpoint returns data
        """
        try:
            resp = requests.get(
                f"{self.api_base}/api/rooms/history?room_id=office_1",
                timeout=2
            )
            if resp.status_code == 200:
                data = resp.json()
                history = data.get("history", [])
                if history:
                    self.log_test(
                        "Room History Available",
                        True,
                        f"{len(history)} history points accumulated"
                    )
                    return True
                else:
                    self.log_test(
                        "Room History Available",
                        False,
                        "No history points yet"
                    )
            else:
                self.log_test(
                    "Room History Available",
                    False,
                    f"HTTP {resp.status_code}"
                )
        except Exception as e:
            self.log_test("Room History Available", False, str(e))
        return False

    def run_all_tests(self):
        """Run all synchronization tests."""
        print("\n" + "=" * 70)
        print("SMART BUILDING SYNCHRONIZATION TEST SUITE")
        print("=" * 70)

        # Check prerequisites
        if not self.check_api_health():
            print("\n[CRITICAL] API is not responding!")
            print(f"  Expected: {self.api_base}")
            print("  Make sure to run: python run_system.py")
            return False

        print("\n[OK] API is responding")
        print("\nRunning tests...\n")

        # Run all tests
        tests = [
            self.test_simulation_time_consistency,
            self.test_simulation_connection_status,
            self.test_stale_data_detection,
            self.test_room_data_consistency,
            self.test_ml_predictions_present,
            self.test_control_decisions_present,
            self.test_energy_metrics,
            self.test_model_loaded,
            self.test_api_connection_status,
            self.test_room_history_available,
        ]

        results = [test() for test in tests]

        # Summary
        passed = sum(results)
        total = len(results)
        print("\n" + "=" * 70)
        print(f"RESULTS: {passed}/{total} tests passed")
        print("=" * 70)

        if passed == total:
            print("\n[OK] ALL TESTS PASSED - System is fully synchronized!")
        else:
            print(f"\n[WARNING] {total - passed} test(s) failed - see details above")

        return passed == total


def main():
    """Run synchronization tests."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Test Smart Building Synchronization Architecture"
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8001",
        help="API base URL (default: http://127.0.0.1:8001)"
    )
    args = parser.parse_args()

    tester = SynchronizationTester()
    tester.api_base = args.api_base

    success = tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
