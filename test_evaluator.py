"""
Quick test of ControlEvaluator with 1-hour simulation
"""

import sys
from datetime import datetime, timedelta
import numpy as np
from simulation_control_evaluator import ControlEvaluator

print("[OK] Imports successful")

# Create evaluator
evaluator = ControlEvaluator()
print("[OK] ControlEvaluator initialized")

# Simulate 1 hour (60 minutes)
start_time = datetime(2026, 4, 4, 12, 0, 0)
print("[..] Running 1-hour evaluation...")

for i in range(60):
    current_time = start_time + timedelta(minutes=i)

    # Occupied for first 30 mins, empty for next 30
    true_occupancy = 1 if i < 30 else 0

    sensor_data = {
        "Temperature": 21.0 + np.random.normal(0, 0.5),
        "Humidity": 40 + (true_occupancy * 10) + np.random.normal(0, 2),
        "Light": (true_occupancy * 300) + np.random.normal(0, 50),
        "CO2": 400 + (true_occupancy * 200) + np.random.normal(0, 20),
        "HumidityRatio": 0.004 + (true_occupancy * 0.001),
    }

    evaluator.add_timestep(current_time, sensor_data, true_occupancy)

print("[OK] 60 timesteps added")

# Compute metrics
metrics = evaluator.compute_metrics()
print(f"[OK] Metrics computed")
print(f"     Baseline Energy: {metrics.baseline_total_energy_kwh:.3f} kWh")
print(f"     AI Energy: {metrics.ai_total_energy_kwh:.3f} kWh")
print(f"     Saved: {metrics.energy_saved_percent:.1f}%")
print(f"     Occupancy Accuracy: {metrics.occupancy_accuracy:.1%}")

# Save results
evaluator.save_all_results()
print("[OK] Results saved")
print("[OK] All tests passed!")
