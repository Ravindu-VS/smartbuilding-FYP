"""
Experiment D: Hardware-in-the-Loop Validation
Tests the latency and integration of the physical hardware room (f2_office_a).
"""
import time
import json
import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integration.state_manager import StateManager
from integration.simulation_bridge import SimulationBridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ExperimentD")

def run_experiment():
    logger.info("Starting Experiment D: HITL Validation")
    
    bridge = SimulationBridge()
    
    # 1. Inject a fake hardware payload
    from hardware.sensor_gateway import process_incoming_sensor_data
    
    payload = {
        "room_id": "f2_office_a",
        "temperature": 28.5,
        "humidity": 65.0,
        "co2": 800,
        "lux": 600,
        "occupancy_probability": 0.95
    }
    
    start_time = time.time()
    process_incoming_sensor_data(payload)
    logger.info(f"Injected hardware payload in {time.time() - start_time:.4f}s")
    
    # 2. Step the state manager
    rooms = bridge.get_all_room_states()
    
    hw_room = next((r for r in rooms if r["room_id"] == "f2_office_a"), None)
    if hw_room:
        logger.info(f"Bridge mapped hardware source: {hw_room['source']}")
        logger.info(f"Hardware sensors: {hw_room['sensors']}")
    else:
        logger.error("Hardware room not found in bridge output")
        
    logger.info("Experiment D complete.")

if __name__ == "__main__":
    run_experiment()
