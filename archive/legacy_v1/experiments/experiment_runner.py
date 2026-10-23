"""
Experimental Evaluation Framework

Runs deterministic 24-hour simulation experiments comparing different
control strategies and ML models for the Smart Building.

Experiments:
    A: Baseline (always-on) vs AI-controlled building
    B: Occupancy model comparison (RF vs threshold vs perfect)
    C: Controller strategy comparison (rule-based vs ML-threshold vs optimizer)

Usage:
    python experiments/experiment_runner.py --experiment A
    python experiments/experiment_runner.py --all
    
Output:
    CSV files in output/experiments/
    Ready for generate_results.py to produce charts.
"""

import os
import sys
import csv
import math
import logging
import argparse
from typing import Dict, List, Any, Tuple
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from integration.building_config import (
    BUILDING_CONFIG, get_all_rooms, get_room_energy_params,
    get_room_control_tuning, ENERGY_PARAMS_BY_TYPE,
)
from integration.multi_floor_simulator import MultiFloorSimulator

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Output directory
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output", "experiments")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# =============================================================================
# CONTROL STRATEGIES
# =============================================================================

class BaselineController:
    """Always-on controller: Lights ON, HVAC NORMAL for all rooms."""
    
    name = "Baseline (Always-On)"
    
    def decide(self, sensors, room_type, true_occupancy=None):
        return {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "ALWAYS_ON"}


class ThresholdCO2Controller:
    """Simple CO2 threshold: occupied if CO2 > 600."""
    
    name = "CO2 Threshold"
    
    def decide(self, sensors, room_type, true_occupancy=None):
        co2 = sensors.get("CO2", 400)
        if co2 > 600:
            return {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "OCCUPIED"}
        else:
            return {"light_action": "OFF", "hvac_action": "ECO", "control_mode": "EMPTY"}


class MLThresholdController:
    """ML-based 3-zone controller using the actual trained model."""
    
    name = "ML Occupancy (Random Forest)"
    
    def __init__(self):
        try:
            from occupancy_inference_service import OccupancyInferenceService
            model_path = os.path.join(PROJECT_ROOT, "models", "final_unified_occupancy_pipeline.pkl")
            self._service = OccupancyInferenceService(model_path, threshold=0.5)
            logger.info("ML model loaded for experiment controller")
        except Exception as e:
            logger.warning(f"ML model not available: {e}")
            self._service = None
    
    def decide(self, sensors, room_type, true_occupancy=None):
        if self._service is None:
            return {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "FALLBACK"}
        
        try:
            result = self._service.predict(sensors)
            prob = result.occupancy_probability
            
            tuning = get_room_control_tuning(room_type)
            if prob < tuning["empty_threshold"]:
                return {"light_action": "OFF", "hvac_action": "ECO", "control_mode": "EMPTY"}
            elif prob < tuning["occupied_threshold"]:
                return {"light_action": "DIM", "hvac_action": "LOW", "control_mode": "STANDBY"}
            else:
                return {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "OCCUPIED"}
        except Exception:
            return {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "FALLBACK"}

    def batch_decide(self, batch_inputs):
        if self._service is None:
            return [{"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "FALLBACK"} for _ in batch_inputs]
        try:
            sensors_list = [inp["sensors"] for inp in batch_inputs]
            results = self._service.batch_predict(sensors_list)
            
            from integration.building_config import get_room_control_tuning
            decisions = []
            for i, res in enumerate(results):
                prob = res.occupancy_probability
                tuning = get_room_control_tuning(batch_inputs[i]["room_type"])
                if prob < tuning["empty_threshold"]:
                    decisions.append({"light_action": "OFF", "hvac_action": "ECO", "control_mode": "EMPTY"})
                elif prob < tuning["occupied_threshold"]:
                    decisions.append({"light_action": "DIM", "hvac_action": "LOW", "control_mode": "STANDBY"})
                else:
                    decisions.append({"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "OCCUPIED"})
            return decisions
        except Exception as e:
            logger.error(f"Batch inference failed: {e}")
            return [{"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "FALLBACK"} for _ in batch_inputs]


class PerfectKnowledgeController:
    """Uses ground truth occupancy (perfect sensor). Upper bound for AI."""
    
    name = "Perfect Knowledge (Oracle)"
    
    def decide(self, sensors, room_type, true_occupancy=None):
        if true_occupancy and true_occupancy > 0:
            return {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "OCCUPIED"}
        else:
            return {"light_action": "OFF", "hvac_action": "ECO", "control_mode": "EMPTY"}


class ScheduleBasedController:
    """Uses time-of-day schedule to predict occupancy."""
    
    name = "Schedule-Based"
    
    def __init__(self):
        from integration.building_config import get_room_schedule
        self._get_schedule = get_room_schedule
        self._current_hour = 6.0
    
    def set_hour(self, hour):
        self._current_hour = hour
    
    def decide(self, sensors, room_type, true_occupancy=None):
        schedule = self._get_schedule(room_type)
        hour_idx = int(self._current_hour) % 24
        prob = schedule[hour_idx]
        
        if prob > 0.3:
            return {"light_action": "ON", "hvac_action": "NORMAL", "control_mode": "OCCUPIED"}
        elif prob > 0.1:
            return {"light_action": "DIM", "hvac_action": "LOW", "control_mode": "STANDBY"}
        else:
            return {"light_action": "OFF", "hvac_action": "ECO", "control_mode": "EMPTY"}


# =============================================================================
# ENERGY CALCULATOR
# =============================================================================

def compute_power(room_type: str, light_action: str, hvac_action: str) -> float:
    """Compute instantaneous power in watts for a room."""
    params = get_room_energy_params(room_type)
    
    if light_action == "ON":
        light_power = params["light_on"]
    elif light_action == "DIM":
        light_power = params["light_dim"]
    else:
        light_power = 5.0  # standby
    
    if hvac_action == "NORMAL":
        hvac_power = params["hvac_normal"]
    elif hvac_action == "LOW":
        hvac_power = params.get("hvac_normal", 350) * 0.4
    else:
        hvac_power = params["hvac_eco"]
    
    return light_power + hvac_power + params["base_load"]


def compute_comfort_score(temperature: float, humidity: float, co2: float, occupied: bool) -> float:
    """
    Compute comfort score (0-1, higher = better).
    Only penalized when room is occupied.
    """
    if not occupied:
        return 1.0  # No comfort penalty when empty
    
    # Temperature comfort (ideal: 22-25°C)
    if 22 <= temperature <= 25:
        temp_score = 1.0
    elif 20 <= temperature <= 27:
        temp_score = 0.7
    else:
        temp_score = max(0, 1.0 - abs(temperature - 23.5) * 0.1)
    
    # CO2 comfort (ideal: < 800 ppm)
    if co2 < 600:
        co2_score = 1.0
    elif co2 < 1000:
        co2_score = 1.0 - (co2 - 600) / 1000
    else:
        co2_score = max(0, 0.6 - (co2 - 1000) / 2000)
    
    # Humidity comfort (ideal: 40-60%)
    if 40 <= humidity <= 60:
        hum_score = 1.0
    else:
        hum_score = max(0, 1.0 - abs(humidity - 50) * 0.02)
    
    return round(temp_score * 0.5 + co2_score * 0.3 + hum_score * 0.2, 4)


# =============================================================================
# EXPERIMENT RUNNER
# =============================================================================

class ExperimentRunner:
    """Runs deterministic experiments over 24-hour simulation periods."""
    
    def __init__(self, sim_step_seconds: float = 60.0):
        """
        Args:
            sim_step_seconds: Simulation time step in seconds (60 = 1 minute steps).
        """
        self.sim_step = sim_step_seconds
        self.steps_per_day = int(86400 / sim_step_seconds)  # 1440 for 60s steps
    
    def run_experiment_a(self) -> str:
        """
        Experiment A: Baseline vs AI-Controlled Building.
        
        Compares energy consumption, HVAC runtime, and comfort scores
        between an always-on building and the ML-controlled building.
        """
        logger.info("=" * 60)
        logger.info("EXPERIMENT A: Baseline vs AI-Controlled Building")
        logger.info("=" * 60)
        
        controllers = [
            BaselineController(),
            MLThresholdController(),
            PerfectKnowledgeController(),
        ]
        
        return self._run_multi_controller_experiment(
            "experiment_a_baseline_vs_ai",
            controllers
        )
    
    def run_experiment_b(self) -> str:
        """
        Experiment B: Occupancy Detection Model Comparison.
        
        Compares ML prediction accuracy across different approaches:
        - ML Random Forest
        - CO2 Threshold
        - Schedule-Based
        - Perfect Knowledge (Oracle)
        """
        logger.info("=" * 60)
        logger.info("EXPERIMENT B: Occupancy Model Comparison")
        logger.info("=" * 60)
        
        controllers = [
            ThresholdCO2Controller(),
            MLThresholdController(),
            ScheduleBasedController(),
            PerfectKnowledgeController(),
        ]
        
        return self._run_multi_controller_experiment(
            "experiment_b_model_comparison",
            controllers
        )
    
    def run_experiment_c(self) -> str:
        """
        Experiment C: Controller Strategy Comparison.
        
        Compares energy savings and comfort across:
        - Baseline (always on)
        - Schedule-Based
        - CO2 Threshold
        - ML 3-Zone Controller
        """
        logger.info("=" * 60)
        logger.info("EXPERIMENT C: Controller Strategy Comparison")
        logger.info("=" * 60)
        
        controllers = [
            BaselineController(),
            ScheduleBasedController(),
            ThresholdCO2Controller(),
            MLThresholdController(),
        ]
        
        return self._run_multi_controller_experiment(
            "experiment_c_controller_comparison",
            controllers
        )
    
    def _run_multi_controller_experiment(
        self, experiment_name: str, controllers: list
    ) -> str:
        """Run the same 24h simulation for each controller and collect metrics."""
        
        all_results = {}
        
        for ctrl in controllers:
            logger.info(f"\n--- Running: {ctrl.name} ---")
            
            # Fresh simulator with same seed for determinism
            sim = MultiFloorSimulator(speed_factor=1.0, seed=42)
            
            # Metrics accumulators
            total_energy_wh = 0.0
            total_comfort_sum = 0.0
            total_comfort_count = 0
            hvac_on_steps = 0
            light_on_steps = 0
            total_steps_all_rooms = 0
            
            # Occupancy detection metrics
            true_positives = 0
            true_negatives = 0
            false_positives = 0
            false_negatives = 0
            
            # Per-floor energy
            floor_energy = {f["floor_id"]: 0.0 for f in BUILDING_CONFIG["floors"]}
            
            # Per-step log
            step_log = []
            
            for step_i in range(self.steps_per_day):
                sim.step_deterministic(self.sim_step)
                hour = sim.sim_hour
                
                # Update schedule controller hour if applicable
                if hasattr(ctrl, 'set_hour'):
                    ctrl.set_hour(hour)
                
                states = sim.get_all_room_states()
                step_power = 0.0
                step_comfort = 0.0
                step_comfort_n = 0
                
                # Prepare batch inputs
                batch_inputs = []
                for room_state in states:
                    sensors_for_model = room_state["sensors"].copy()
                    if room_state["device_state"]["light_on"]:
                        sensors_for_model["Light"] = max(0, sensors_for_model["Light"] - 400.0)
                    batch_inputs.append({
                        "sensors": sensors_for_model,
                        "room_type": room_state["room_type"],
                        "true_occupancy": room_state["ground_truth"]["true_occupancy"]
                    })
                    
                # Get batch decisions
                if hasattr(ctrl, "batch_decide"):
                    decisions = ctrl.batch_decide(batch_inputs)
                else:
                    decisions = [ctrl.decide(inp["sensors"], inp["room_type"], inp["true_occupancy"]) for inp in batch_inputs]
                
                for i, room_state in enumerate(states):
                    room_id = room_state["room_id"]
                    room_type = room_state["room_type"]
                    sensors = room_state["sensors"]
                    true_occ = room_state["ground_truth"]["true_occupancy"]
                    
                    decision = decisions[i]
                    
                    # Apply control to simulator
                    light_on = decision["light_action"] != "OFF"
                    hvac_mode = "heating" if decision["hvac_action"] == "NORMAL" else "off"
                    hvac_speed = 0.8 if decision["hvac_action"] == "NORMAL" else (0.3 if decision["hvac_action"] == "LOW" else 0.0)
                    sim.apply_control(room_id, light_on, hvac_mode, hvac_speed)
                    
                    # Compute metrics
                    power = compute_power(room_type, decision["light_action"], decision["hvac_action"])
                    energy_wh = power * (self.sim_step / 3600.0)
                    total_energy_wh += energy_wh
                    floor_energy[room_state["floor_id"]] += energy_wh
                    step_power += power
                    
                    comfort = compute_comfort_score(
                        sensors["Temperature"], sensors["Humidity"],
                        sensors["CO2"], true_occ > 0
                    )
                    if true_occ > 0:
                        step_comfort += comfort
                        step_comfort_n += 1
                        total_comfort_sum += comfort
                        total_comfort_count += 1
                    
                    # Track HVAC/Light runtime
                    if decision["hvac_action"] in ("NORMAL", "LOW"):
                        hvac_on_steps += 1
                    if decision["light_action"] != "OFF":
                        light_on_steps += 1
                    total_steps_all_rooms += 1
                    
                    # Occupancy detection accuracy
                    predicted_occ = 1 if decision["control_mode"] in ("OCCUPIED", "STANDBY", "ALWAYS_ON") else 0
                    actual_occ = 1 if true_occ > 0 else 0
                    
                    if predicted_occ == 1 and actual_occ == 1:
                        true_positives += 1
                    elif predicted_occ == 0 and actual_occ == 0:
                        true_negatives += 1
                    elif predicted_occ == 1 and actual_occ == 0:
                        false_positives += 1
                    elif predicted_occ == 0 and actual_occ == 1:
                        false_negatives += 1
                
                # Log every 15 minutes of sim time
                if step_i % 15 == 0:
                    step_log.append({
                        "sim_time": sim.simulation_time_str,
                        "hour": round(hour, 2),
                        "total_power_w": round(step_power, 1),
                        "avg_comfort": round(step_comfort / max(1, step_comfort_n), 4),
                        "outdoor_temp": sim.get_outdoor_conditions()["temperature"],
                    })
            
            # Compute summary metrics
            precision = true_positives / max(1, true_positives + false_positives)
            recall = true_positives / max(1, true_positives + false_negatives)
            f1 = 2 * precision * recall / max(0.001, precision + recall)
            accuracy = (true_positives + true_negatives) / max(1, total_steps_all_rooms)
            
            avg_comfort = total_comfort_sum / max(1, total_comfort_count)
            hvac_runtime_pct = hvac_on_steps / max(1, total_steps_all_rooms) * 100
            light_runtime_pct = light_on_steps / max(1, total_steps_all_rooms) * 100
            
            result = {
                "controller": ctrl.name,
                "total_energy_kwh": round(total_energy_wh / 1000, 2),
                "avg_comfort_score": round(avg_comfort, 4),
                "hvac_runtime_pct": round(hvac_runtime_pct, 1),
                "light_runtime_pct": round(light_runtime_pct, 1),
                "accuracy": round(accuracy, 4),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1_score": round(f1, 4),
                "floor_energy_kwh": {k: round(v/1000, 2) for k, v in floor_energy.items()},
                "step_log": step_log,
            }
            
            all_results[ctrl.name] = result
            logger.info(f"  Energy: {result['total_energy_kwh']} kWh | "
                        f"Comfort: {result['avg_comfort_score']} | "
                        f"HVAC: {result['hvac_runtime_pct']}% | "
                        f"Accuracy: {result['accuracy']}")
        
        # Write results to CSV
        csv_path = self._write_summary_csv(experiment_name, all_results)
        self._write_timeseries_csv(experiment_name, all_results)
        
        return csv_path
    
    def _write_summary_csv(self, name: str, results: dict) -> str:
        """Write summary comparison CSV."""
        path = os.path.join(OUTPUT_DIR, f"{name}_summary.csv")
        
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Controller", "Energy (kWh)", "Comfort Score",
                "HVAC Runtime %", "Light Runtime %",
                "Accuracy", "Precision", "Recall", "F1 Score",
                "Floor 0 kWh", "Floor 1 kWh", "Floor 2 kWh",
                "Floor 3 kWh", "Floor 4 kWh",
            ])
            
            for name_key, r in results.items():
                fe = r["floor_energy_kwh"]
                writer.writerow([
                    r["controller"], r["total_energy_kwh"], r["avg_comfort_score"],
                    r["hvac_runtime_pct"], r["light_runtime_pct"],
                    r["accuracy"], r["precision"], r["recall"], r["f1_score"],
                    fe.get(0, 0), fe.get(1, 0), fe.get(2, 0),
                    fe.get(3, 0), fe.get(4, 0),
                ])
        
        logger.info(f"Summary CSV written: {path}")
        return path
    
    def _write_timeseries_csv(self, name: str, results: dict):
        """Write per-controller time-series CSV for plotting."""
        for ctrl_name, r in results.items():
            safe_name = ctrl_name.replace(" ", "_").replace("(", "").replace(")", "").lower()
            path = os.path.join(OUTPUT_DIR, f"{name}_{safe_name}_timeseries.csv")
            
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["sim_time", "hour", "total_power_w", "avg_comfort", "outdoor_temp"])
                for entry in r["step_log"]:
                    writer.writerow([
                        entry["sim_time"], entry["hour"],
                        entry["total_power_w"], entry["avg_comfort"],
                        entry["outdoor_temp"],
                    ])
            
            logger.info(f"  Timeseries CSV: {path}")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Smart Building Experiment Runner")
    parser.add_argument("--experiment", choices=["A", "B", "C", "all"], default="all",
                        help="Which experiment to run")
    parser.add_argument("--step", type=float, default=60.0,
                        help="Simulation step size in seconds (default: 60)")
    args = parser.parse_args()
    
    runner = ExperimentRunner(sim_step_seconds=args.step)
    
    if args.experiment in ("A", "all"):
        runner.run_experiment_a()
    if args.experiment in ("B", "all"):
        runner.run_experiment_b()
    if args.experiment in ("C", "all"):
        runner.run_experiment_c()
    
    logger.info(f"\nAll results saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
