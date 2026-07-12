"""Quick test script for the integration API endpoints."""
import urllib.request
import json

BASE = "http://127.0.0.1:8001"

def test_endpoint(name, url):
    try:
        r = urllib.request.urlopen(url)
        data = json.loads(r.read())
        print(f"\n[OK] {name} — OK")
        return data
    except Exception as e:
        print(f"\n[FAIL] {name} — FAILED: {e}")
        return None

# 1. Health
data = test_endpoint("GET /health", f"{BASE}/health")
if data:
    print(f"  status={data['status']}, model={data['model_loaded']}, sim={data['simulation_active']}")

# 2. Live state
data = test_endpoint("GET /api/system/live", f"{BASE}/api/system/live")
if data:
    rooms = data.get("rooms", [])
    system = data.get("system", {})
    print(f"  Rooms: {len(rooms)}")
    print(f"  Occupied: {system.get('occupied_rooms', '?')}, Empty: {system.get('empty_rooms', '?')}")
    print(f"  Total power: {system.get('total_power_watts', 0):.1f}W")
    print(f"  Sim time: {system.get('simulation_time', '--')}")
    for rm in rooms:
        ai = rm.get("ai", {})
        ctrl = rm.get("control", {})
        energy = rm.get("energy", {})
        sensors = rm.get("sensors", {})
        gt = rm.get("ground_truth", {})
        print(f"  [{rm['room_id']}] "
              f"prob={ai.get('occupancy_probability', 0):.3f} "
              f"pred={ai.get('predicted_occupancy', '?')} "
              f"truth={gt.get('true_occupancy', '?')} "
              f"mode={ctrl.get('control_mode', '?')} "
              f"light={ctrl.get('light_action', '?')} "
              f"hvac={ctrl.get('hvac_action', '?')} "
              f"power={energy.get('estimated_power_watts', 0):.0f}W "
              f"temp={sensors.get('Temperature', 0):.1f}°C "
              f"co2={sensors.get('CO2', 0):.0f}ppm")

# 3. System summary
data = test_endpoint("GET /api/system/summary", f"{BASE}/api/system/summary")
if data:
    print(f"  Total energy: {data.get('total_cumulative_energy_wh', 0):.2f}Wh")
    print(f"  Update interval: {data.get('update_interval', '?')}s")

# 4. History
data = test_endpoint("GET /api/rooms/history", f"{BASE}/api/rooms/history")
if data:
    for room_id, hist in data.items():
        print(f"  {room_id}: {len(hist)} history points")

# 5. Dashboard reachable
try:
    r = urllib.request.urlopen(f"{BASE}/dashboard")
    html = r.read().decode()
    if "Smart Building" in html:
        print(f"\n[OK] Dashboard HTML — OK ({len(html)} bytes)")
    else:
        print(f"\n[FAIL] Dashboard HTML — Unexpected content")
except Exception as e:
    print(f"\n[FAIL] Dashboard — FAILED: {e}")

print("\n" + "=" * 60)
print("ALL ENDPOINT TESTS COMPLETE")
print("=" * 60)
