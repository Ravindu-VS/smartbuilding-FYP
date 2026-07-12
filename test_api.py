"""
Test Smart Building API

Tests all endpoints of the Smart Building ML API
"""

import requests
import json
import sys

# API endpoint
BASE_URL = "http://127.0.0.1:8001"

# Test sensor data
SENSOR_DATA_OCCUPIED = {
    "Temperature": 21.5,
    "Humidity": 35.0,
    "Light": 450.0,
    "CO2": 700.0,
    "HumidityRatio": 0.0045
}

SENSOR_DATA_EMPTY = {
    "Temperature": 19.5,
    "Humidity": 25.0,
    "Light": 50.0,
    "CO2": 420.0,
    "HumidityRatio": 0.0035
}

SENSOR_DATA_MISSING = {
    "Temperature": 21.0,
    "Humidity": None,  # Missing value
    "Light": 350.0,
    "CO2": 650.0,
    "HumidityRatio": 0.0044
}


def test_health():
    """Test health endpoint."""
    print("\n[TEST] GET /health")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"  Error: {e}")
        return False


def test_predict_occupancy():
    """Test occupancy prediction endpoint."""
    print("\n[TEST] POST /predict-occupancy")
    try:
        response = requests.post(
            f"{BASE_URL}/predict-occupancy",
            json=SENSOR_DATA_OCCUPIED,
            timeout=5
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"  Error: {e}")
        return False


def test_control_decision():
    """Test control decision endpoint."""
    print("\n[TEST] POST /control-decision")
    try:
        response = requests.post(
            f"{BASE_URL}/control-decision",
            json=SENSOR_DATA_OCCUPIED,
            timeout=5
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"  Error: {e}")
        return False


def test_batch_occupancy():
    """Test batch occupancy prediction endpoint."""
    print("\n[TEST] POST /batch-occupancy")
    try:
        response = requests.post(
            f"{BASE_URL}/batch-occupancy",
            json=[SENSOR_DATA_OCCUPIED, SENSOR_DATA_EMPTY, SENSOR_DATA_MISSING],
            timeout=5
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"  Error: {e}")
        return False


def test_batch_control():
    """Test batch control decision endpoint."""
    print("\n[TEST] POST /batch-control")
    try:
        response = requests.post(
            f"{BASE_URL}/batch-control",
            json=[SENSOR_DATA_OCCUPIED, SENSOR_DATA_EMPTY, SENSOR_DATA_MISSING],
            timeout=5
        )
        print(f"  Status: {response.status_code}")
        print(f"  Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"  Error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("Smart Building API Test Suite")
    print("=" * 70)
    print(f"\nTesting API at: {BASE_URL}")
    print("\nMake sure the API is running:")
    print("  python run_api_flask.py")

    # Run tests
    results = []
    results.append(("Health Check", test_health()))
    results.append(("Predict Occupancy", test_predict_occupancy()))
    results.append(("Control Decision", test_control_decision()))
    results.append(("Batch Occupancy", test_batch_occupancy()))
    results.append(("Batch Control", test_batch_control()))

    # Summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
    print(f"\nTotal: {passed}/{total} passed")
    print("=" * 70)

    sys.exit(0 if passed == total else 1)
