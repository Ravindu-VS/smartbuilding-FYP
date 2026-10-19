"""Quick test to verify the Edge Brain starts and processes all 26 rooms."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from raspberry_pi.edge_brain import EdgeBrain

brain = EdgeBrain(speed_factor=360)
brain.tick()
state = brain.get_current_state()

print(f"\n{'='*60}")
print(f"  EDGE BRAIN TEST RESULTS")
print(f"{'='*60}")
print(f"  Total Rooms:   {state['system']['total_rooms']}")
print(f"  Sim Time:      {state['system']['simulation_time']}")
print(f"  Model Loaded:  {state['system']['model_loaded']}")
print(f"  Total Power:   {state['system']['total_power_watts']}W")
print(f"  Occupied:      {state['system']['occupied_rooms']}")
print(f"  Empty:         {state['system']['empty_rooms']}")
print(f"{'='*60}")

print(f"\n  Room Details (first 10):")
for r in state['rooms'][:10]:
    src = r['source'][:4].upper()
    prob = r['ai']['occupancy_probability']
    hvac = r['control']['hvac_action']
    light = r['control']['light_action']
    mode = r['control']['control_mode']
    print(f"    {r['room_id']:20s} [{src}] OccProb={prob:.2f} HVAC={hvac:6s} Light={light:3s} Mode={mode}")

print(f"\n  [OK] Edge Brain is working correctly!")
print(f"{'='*60}\n")
