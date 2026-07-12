import datetime
import math
from simulation.occupancy_scheduler import OccupancyScheduler
from integration.energy_estimator import EnergyEstimator
from integration.energy_optimizer import EnergyOptimizer

def test_bathroom_occupancy():
    print("Testing Bathroom Occupancy (Target Max: 2)...")
    scheduler = OccupancyScheduler()
    # Override schedule just in case it's not defined
    scheduler.zone_schedules["bathroom"] = {"start_hour": 7, "end_hour": 19}
    
    max_found = 0
    start_time = datetime.datetime.now().replace(hour=0, minute=0, second=0)
    
    # Simulate a full day minute by minute
    for m in range(24 * 60):
        current_time = start_time + datetime.timedelta(minutes=m)
        occ = scheduler.get_room_occupancy_count(
            room_id=1, 
            room_type="bathroom", 
            timestamp=current_time, 
            max_occupancy=2
        )
        if occ > max_found:
            max_found = occ
        if occ > 2:
            print(f"FAIL: Bathroom occupancy reached {occ} at {current_time}!")
            return False
            
    print(f"SUCCESS: Max bathroom occupancy over 24h was {max_found}")
    return max_found <= 2

def test_energy_pipeline():
    print("\nTesting Energy Accumulation & Savings Logic...")
    estimator = EnergyEstimator()
    optimizer = EnergyOptimizer()
    
    room_id = "office_1"
    estimator.register_room(room_id, "office")
    optimizer.register_room(room_id, "office")
    
    # Case 1: Room operates on empty for 1 simulation hour (3600 seconds)
    # The actual applied action is OFF (Lights) and ECO (HVAC)
    dt_sim = 3600.0
    actual_light = "OFF"
    actual_hvac = "ECO"
    
    est = estimator.estimate_room_energy(room_id, actual_light, actual_hvac, dt=dt_sim)
    opt = optimizer.update_room(room_id, actual_light, actual_hvac, dt=dt_sim)
    
    saved = opt["energy_saved_wh"]
    pct = opt["percentage_saved"]
    print(f"AI Energy: {opt['ai_energy_wh']:.2f} Wh | Baseline Energy: {opt['baseline_energy_wh']:.2f} Wh")
    print(f"Energy Saved: {saved:.2f} Wh ({pct:.1f}%)")
    
    if saved > 0 and pct > 0:
        print("SUCCESS: Energy savings successfully registered!")
        return True
    else:
        print("FAIL: Energy savings tracking is broken.")
        return False

def main():
    print("====================================")
    print("Demo Readiness Validation Script")
    print("====================================")
    
    occ_pass = test_bathroom_occupancy()
    eng_pass = test_energy_pipeline()
    
    if occ_pass and eng_pass:
        print("\n[OK] All demo blockers successfully fixed.")
        exit(0)
    else:
        print("\n[ERR] Demo readiness validation failed.")
        exit(1)

if __name__ == "__main__":
    main()
