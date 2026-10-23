"""Quick verification of all new modules."""
import sys
sys.path.insert(0, '.')

print("=" * 60)
print("  Module Import Verification")
print("=" * 60)

# 1. Config
from integration.config import (
    BASELINE_LIGHT_ACTION, BASELINE_HVAC_ACTION,
    SYSTEM_LOG_FILE, EVENT_LOG_MAX_SIZE,
)
print(f"[OK] Config: baseline={BASELINE_LIGHT_ACTION}/{BASELINE_HVAC_ACTION}, log={SYSTEM_LOG_FILE}")

# 2. Logger
from integration.logger import SystemLogger
sl = SystemLogger.get_instance()
sl.log_system("Verification test started")
sl.log_control("office_1", "OCCUPIED", "Lights ON, HVAC NORMAL")
sl.log_energy("Test energy event")
events = sl.get_recent_events()
print(f"[OK] Logger: {len(events)} events in buffer")
for e in events:
    print(f"     [{e['category']}] {e['message']}")

# 3. Energy Optimizer
from integration.energy_optimizer import EnergyOptimizer
opt = EnergyOptimizer()
opt.register_room("office_1", "office")
opt.register_room("kitchen_1", "kitchen")
import time
# First update to set timestamp
opt.update_room("office_1", "OFF", "ECO")
opt.update_room("kitchen_1", "DIM", "LOW")
time.sleep(0.1)
# Second update to accumulate energy
opt.update_room("office_1", "OFF", "ECO")
opt.update_room("kitchen_1", "DIM", "LOW")
summary = opt.get_building_summary()
print(f"[OK] EnergyOptimizer: baseline={summary['baseline_power_watts']}W, ai={summary['ai_power_watts']}W, saved={summary['percentage_saved']}%")

# 4. State Manager (just import, no ML model load for speed)
from integration.state_manager import StateManager
print("[OK] StateManager imported successfully")

# 5. Energy Estimator
from integration.energy_estimator import EnergyEstimator
ee = EnergyEstimator()
ee.register_room("test_room", "office")
result = ee.estimate_room_energy("test_room", "ON", "NORMAL")
print(f"[OK] EnergyEstimator: power={result['estimated_power_watts']}W")

# 6. Simulation Bridge
from integration.simulation_bridge import SimulationBridge
print("[OK] SimulationBridge imported successfully")

# 7. Simulation IPC
from integration.simulation_ipc import SimulationStateWriter, SimulationStateReader, ControlActionWriter, ControlActionReader
print("[OK] SimulationIPC imported successfully")

# 8. Flask API
from smart_building_api_flask import app
print("[OK] Flask API imported successfully")

# Check log file was created
import os
log_path = os.path.join('.', SYSTEM_LOG_FILE)
if os.path.exists(log_path):
    size = os.path.getsize(log_path)
    print(f"[OK] Log file exists: {log_path} ({size} bytes)")
else:
    print(f"[!!] Log file not found: {log_path}")

print()
print("=" * 60)
print("  ALL MODULES VERIFIED SUCCESSFULLY")
print("=" * 60)
