"""
Simulation Control Evaluator

Evaluates the impact of AI-assisted occupancy control on building energy usage
and comfort compared to baseline rule-based control.

Compares:
- Baseline: Simple rule-based occupancy control
- AI-Assisted: ML-based occupancy prediction and adaptive control

Metrics:
- Total energy usage (kWh)
- Energy savings vs baseline (%)
- Occupancy prediction accuracy
- False shutoff events
- Comfort violations (temperature outside setpoint range)
- Control action frequencies

Usage:
    evaluator = ControlEvaluator(simulation_duration_hours=24)

    for step in simulation:
        evaluator.add_timestep(
            timestamp=step.timestamp,
            sensor_data={...},
            true_occupancy=step.occupancy
        )

    metrics = evaluator.compute_metrics()
    evaluator.save_results(output_dir='output/metrics/')
    evaluator.plot_results(output_dir='output/plots/')
"""

import logging
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
import numpy as np
import matplotlib.pyplot as plt
from smart_building_controller import SmartBuildingController
from occupancy_inference_service import OccupancyInferenceService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class SimulationStep:
    """Single timestep in simulation."""
    timestamp: datetime
    temperature: float
    humidity: float
    light: float
    co2: float
    humidity_ratio: float
    true_occupancy: int  # 0 or 1

    # Will be populated by evaluator
    predicted_occupancy_prob: float = 0.0
    predicted_occupancy_class: int = 0
    baseline_light: str = "OFF"
    baseline_hvac: str = "ECO"
    ai_light: str = "OFF"
    ai_hvac: str = "ECO"
    baseline_control_mode: str = "EMPTY"
    ai_control_mode: str = "EMPTY"
    baseline_energy_wh: float = 0.0
    ai_energy_wh: float = 0.0
    comfort_violation: bool = False


@dataclass
class ControlMetrics:
    """Aggregated control metrics."""
    # Energy metrics
    baseline_total_energy_kwh: float = 0.0
    ai_total_energy_kwh: float = 0.0
    energy_saved_kwh: float = 0.0
    energy_saved_percent: float = 0.0

    # Occupancy prediction metrics
    occupancy_accuracy: float = 0.0
    occupancy_precision: float = 0.0
    occupancy_recall: float = 0.0
    occupancy_f1: float = 0.0
    false_positives: int = 0  # Predicted occupied, actually empty
    false_negatives: int = 0  # Predicted empty, actually occupied

    # Control action metrics
    baseline_light_on_percent: float = 0.0
    ai_light_on_percent: float = 0.0
    baseline_hvac_on_percent: float = 0.0
    ai_hvac_on_percent: float = 0.0

    # Comfort metrics
    total_comfort_violations: int = 0
    comfort_violation_percent: float = 0.0

    # Control switching
    baseline_control_changes: int = 0
    ai_control_changes: int = 0

    # False shutoff events (predicted empty but actually occupied = lights OFF when occupied)
    false_shutoff_events: int = 0


class BaselineController:
    """Simple rule-based occupancy control (no prediction)."""

    COMFORT_TEMP_MIN = 18.0  # °C
    COMFORT_TEMP_MAX = 26.0  # °C
    OCCUPANCY_CO2_THRESHOLD = 500  # ppm - CO2-based occupancy detection

    def __init__(self):
        """Initialize baseline controller."""
        logger.info("Initializing Baseline Rule-Based Controller")

    def get_control(self, sensor_data: Dict, true_occupancy: int) -> Tuple[str, str, str]:
        """
        Get control decision based on true occupancy and simple rules.

        Args:
            sensor_data: Sensor readings dict
            true_occupancy: Ground truth occupancy (0 or 1)

        Returns:
            Tuple of (control_mode, light_action, hvac_action)
        """
        # Simple rule: if occupied, turn on; if empty, turn off
        if true_occupancy == 1:
            control_mode = "OCCUPIED"
            light_action = "ON"
            hvac_action = "NORMAL"
        else:
            control_mode = "EMPTY"
            light_action = "OFF"
            hvac_action = "ECO"

        return control_mode, light_action, hvac_action


class ControlEvaluator:
    """
    Evaluates AI-assisted occupancy control vs baseline.

    Runs both control strategies on the same simulation data and compares
    energy usage, comfort, and control effectiveness.
    """

    # Energy consumption estimates (Watts)
    ENERGY_ESTIMATES = {
        "light_on": 500,      # Lights full brightness (W)
        "light_dim": 250,     # Lights dimmed (W)
        "light_off": 0,       # Lights off (W)
        "hvac_normal": 2000,  # HVAC normal operation (W)
        "hvac_low": 800,      # HVAC low operation (W)
        "hvac_eco": 200,      # HVAC eco/standby (W)
    }

    # Comfort constraints
    COMFORT_TEMP_MIN = 18.0  # °C
    COMFORT_TEMP_MAX = 26.0  # °C

    def __init__(self, ai_model_path: str = "models/domain_adapted_occupancy_pipeline.pkl"):
        """
        Initialize control evaluator.

        Args:
            ai_model_path: Path to trained occupancy model
        """
        self.ai_model_path = ai_model_path
        self.steps: List[SimulationStep] = []
        self.baseline_controller = BaselineController()
        self.ai_controller = SmartBuildingController(ai_model_path)
        self.inference_service = OccupancyInferenceService(ai_model_path)

        self.last_baseline_mode = "EMPTY"
        self.last_ai_mode = "EMPTY"

        logger.info("ControlEvaluator initialized")
        logger.info(f"AI Model: {ai_model_path}")

    def add_timestep(
        self,
        timestamp: datetime,
        sensor_data: Dict[str, float],
        true_occupancy: int,
    ) -> None:
        """
        Add a simulation timestep for evaluation.

        Args:
            timestamp: Timestamp of this step
            sensor_data: Sensor readings (Temperature, Humidity, Light, CO2, HumidityRatio)
            true_occupancy: Ground truth occupancy (0 or 1)
        """
        # Create simulation step
        step = SimulationStep(
            timestamp=timestamp,
            temperature=sensor_data.get("Temperature", 20.0),
            humidity=sensor_data.get("Humidity", 40.0),
            light=sensor_data.get("Light", 200.0),
            co2=sensor_data.get("CO2", 500.0),
            humidity_ratio=sensor_data.get("HumidityRatio", 0.0045),
            true_occupancy=true_occupancy,
        )

        # Get AI prediction
        try:
            ai_result = self.inference_service.predict(sensor_data)
            step.predicted_occupancy_prob = ai_result.occupancy_probability
            step.predicted_occupancy_class = ai_result.occupancy_prediction
        except Exception as e:
            logger.warning(f"AI prediction error at {timestamp}: {e}")
            step.predicted_occupancy_prob = 0.5
            step.predicted_occupancy_class = 0

        # Get baseline control
        baseline_mode, baseline_light, baseline_hvac = self.baseline_controller.get_control(
            sensor_data, true_occupancy
        )
        step.baseline_control_mode = baseline_mode
        step.baseline_light = baseline_light
        step.baseline_hvac = baseline_hvac

        # Get AI control decision
        try:
            ai_decision = self.ai_controller.get_control_decision(sensor_data)
            step.ai_control_mode = ai_decision.control_mode
            step.ai_light = ai_decision.light_action
            step.ai_hvac = ai_decision.hvac_action
        except Exception as e:
            logger.warning(f"AI control error at {timestamp}: {e}")
            step.ai_control_mode = "EMPTY"
            step.ai_light = "OFF"
            step.ai_hvac = "ECO"

        # Estimate energy consumption (per minute assuming 1-minute timestep)
        baseline_light_w = self._get_light_power(step.baseline_light)
        baseline_hvac_w = self._get_hvac_power(step.baseline_hvac)
        step.baseline_energy_wh = (baseline_light_w + baseline_hvac_w) / 60  # Convert Wh per minute

        ai_light_w = self._get_light_power(step.ai_light)
        ai_hvac_w = self._get_hvac_power(step.ai_hvac)
        step.ai_energy_wh = (ai_light_w + ai_hvac_w) / 60

        # Detect comfort violations (temperature outside acceptable range)
        step.comfort_violation = (
            step.temperature < self.COMFORT_TEMP_MIN
            or step.temperature > self.COMFORT_TEMP_MAX
        )

        self.steps.append(step)

    def _get_light_power(self, light_action: str) -> float:
        """Get power consumption for light action."""
        if light_action == "ON":
            return self.ENERGY_ESTIMATES["light_on"]
        elif light_action == "DIM":
            return self.ENERGY_ESTIMATES["light_dim"]
        else:  # OFF
            return self.ENERGY_ESTIMATES["light_off"]

    def _get_hvac_power(self, hvac_action: str) -> float:
        """Get power consumption for HVAC action."""
        if hvac_action == "NORMAL":
            return self.ENERGY_ESTIMATES["hvac_normal"]
        elif hvac_action == "LOW":
            return self.ENERGY_ESTIMATES["hvac_low"]
        else:  # ECO
            return self.ENERGY_ESTIMATES["hvac_eco"]

    def compute_metrics(self) -> ControlMetrics:
        """
        Compute evaluation metrics.

        Returns:
            ControlMetrics object with all aggregated metrics
        """
        metrics = ControlMetrics()

        if len(self.steps) == 0:
            logger.warning("No timesteps to evaluate")
            return metrics

        # Energy metrics
        metrics.baseline_total_energy_kwh = sum(s.baseline_energy_wh for s in self.steps) / 1000
        metrics.ai_total_energy_kwh = sum(s.ai_energy_wh for s in self.steps) / 1000
        metrics.energy_saved_kwh = metrics.baseline_total_energy_kwh - metrics.ai_total_energy_kwh
        if metrics.baseline_total_energy_kwh > 0:
            metrics.energy_saved_percent = (
                100 * metrics.energy_saved_kwh / metrics.baseline_total_energy_kwh
            )

        # Occupancy prediction metrics
        true_occupied = [s.true_occupancy for s in self.steps]
        pred_occupied = [s.predicted_occupancy_class for s in self.steps]

        if len(true_occupied) > 0:
            tp = sum(1 for t, p in zip(true_occupied, pred_occupied) if t == 1 and p == 1)
            fp = sum(1 for t, p in zip(true_occupied, pred_occupied) if t == 0 and p == 1)
            fn = sum(1 for t, p in zip(true_occupied, pred_occupied) if t == 1 and p == 0)
            tn = sum(1 for t, p in zip(true_occupied, pred_occupied) if t == 0 and p == 0)

            metrics.occupancy_accuracy = (tp + tn) / len(true_occupied)
            metrics.false_positives = fp
            metrics.false_negatives = fn

            if tp + fp > 0:
                metrics.occupancy_precision = tp / (tp + fp)
            if tp + fn > 0:
                metrics.occupancy_recall = tp / (tp + fn)

            if metrics.occupancy_precision + metrics.occupancy_recall > 0:
                metrics.occupancy_f1 = (
                    2
                    * (metrics.occupancy_precision * metrics.occupancy_recall)
                    / (metrics.occupancy_precision + metrics.occupancy_recall)
                )

        # Control action metrics
        baseline_light_on = sum(1 for s in self.steps if s.baseline_light != "OFF")
        ai_light_on = sum(1 for s in self.steps if s.ai_light != "OFF")
        baseline_hvac_on = sum(1 for s in self.steps if s.baseline_hvac != "ECO")
        ai_hvac_on = sum(1 for s in self.steps if s.ai_hvac != "ECO")

        n_steps = len(self.steps)
        metrics.baseline_light_on_percent = 100 * baseline_light_on / n_steps if n_steps > 0 else 0
        metrics.ai_light_on_percent = 100 * ai_light_on / n_steps if n_steps > 0 else 0
        metrics.baseline_hvac_on_percent = 100 * baseline_hvac_on / n_steps if n_steps > 0 else 0
        metrics.ai_hvac_on_percent = 100 * ai_hvac_on / n_steps if n_steps > 0 else 0

        # Comfort metrics
        metrics.total_comfort_violations = sum(1 for s in self.steps if s.comfort_violation)
        metrics.comfort_violation_percent = (
            100 * metrics.total_comfort_violations / n_steps if n_steps > 0 else 0
        )

        # Control switching (number of mode changes)
        for i, step in enumerate(self.steps):
            if i > 0:
                if step.baseline_control_mode != self.steps[i - 1].baseline_control_mode:
                    metrics.baseline_control_changes += 1
                if step.ai_control_mode != self.steps[i - 1].ai_control_mode:
                    metrics.ai_control_changes += 1

        # False shutoff events (AI says empty but actually occupied)
        metrics.false_shutoff_events = sum(
            1
            for s in self.steps
            if s.predicted_occupancy_class == 0 and s.true_occupancy == 1 and s.ai_light == "OFF"
        )

        logger.info("Metrics computation complete")
        logger.info(f"  Baseline Energy: {metrics.baseline_total_energy_kwh:.2f} kWh")
        logger.info(f"  AI Energy: {metrics.ai_total_energy_kwh:.2f} kWh")
        logger.info(f"  Energy Saved: {metrics.energy_saved_kwh:.2f} kWh ({metrics.energy_saved_percent:.1f}%)")
        logger.info(f"  Occupancy Accuracy: {metrics.occupancy_accuracy:.1%}")
        logger.info(f"  False Shutoff Events: {metrics.false_shutoff_events}")

        return metrics

    def save_detailed_log(self, output_path: str = "output/metrics/control_evaluation_log.csv") -> None:
        """
        Save detailed timestep-by-timestep log to CSV.

        Args:
            output_path: Path to save CSV file
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "timestamp",
            "temperature",
            "humidity",
            "light",
            "co2",
            "humidity_ratio",
            "true_occupancy",
            "predicted_occupancy_prob",
            "predicted_occupancy_class",
            "baseline_control_mode",
            "baseline_light",
            "baseline_hvac",
            "baseline_energy_wh",
            "ai_control_mode",
            "ai_light",
            "ai_hvac",
            "ai_energy_wh",
            "comfort_violation",
        ]

        try:
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for step in self.steps:
                    row = {
                        "timestamp": step.timestamp.isoformat(),
                        "temperature": f"{step.temperature:.2f}",
                        "humidity": f"{step.humidity:.2f}",
                        "light": f"{step.light:.2f}",
                        "co2": f"{step.co2:.2f}",
                        "humidity_ratio": f"{step.humidity_ratio:.4f}",
                        "true_occupancy": step.true_occupancy,
                        "predicted_occupancy_prob": f"{step.predicted_occupancy_prob:.4f}",
                        "predicted_occupancy_class": step.predicted_occupancy_class,
                        "baseline_control_mode": step.baseline_control_mode,
                        "baseline_light": step.baseline_light,
                        "baseline_hvac": step.baseline_hvac,
                        "baseline_energy_wh": f"{step.baseline_energy_wh:.2f}",
                        "ai_control_mode": step.ai_control_mode,
                        "ai_light": step.ai_light,
                        "ai_hvac": step.ai_hvac,
                        "ai_energy_wh": f"{step.ai_energy_wh:.2f}",
                        "comfort_violation": step.comfort_violation,
                    }
                    writer.writerow(row)

            logger.info(f"[OK] Detailed log saved: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save detailed log: {e}")

    def save_metrics_summary(self, output_path: str = "output/metrics/control_evaluation.txt") -> None:
        """
        Save summary metrics to text file.

        Args:
            output_path: Path to save metrics file
            metrics: Computed metrics object
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        metrics = self.compute_metrics()

        try:
            with open(output_path, "w") as f:
                f.write("=" * 80 + "\n")
                f.write("CONTROL EVALUATION SUMMARY\n")
                f.write("=" * 80 + "\n\n")

                f.write(f"Evaluation Period: {len(self.steps)} timesteps\n")
                if len(self.steps) > 0:
                    duration = (self.steps[-1].timestamp - self.steps[0].timestamp).total_seconds() / 3600
                    f.write(f"Duration: {duration:.1f} hours\n")
                f.write("\n")

                f.write("ENERGY METRICS\n")
                f.write("-" * 80 + "\n")
                f.write(f"Baseline Total Energy:     {metrics.baseline_total_energy_kwh:.2f} kWh\n")
                f.write(f"AI Total Energy:           {metrics.ai_total_energy_kwh:.2f} kWh\n")
                f.write(f"Energy Saved:              {metrics.energy_saved_kwh:.2f} kWh\n")
                f.write(f"Energy Saved:              {metrics.energy_saved_percent:.1f}%\n")
                f.write("\n")

                f.write("OCCUPANCY PREDICTION METRICS\n")
                f.write("-" * 80 + "\n")
                f.write(f"Accuracy:                  {metrics.occupancy_accuracy:.1%}\n")
                f.write(f"Precision:                 {metrics.occupancy_precision:.1%}\n")
                f.write(f"Recall:                    {metrics.occupancy_recall:.1%}\n")
                f.write(f"F1-Score:                  {metrics.occupancy_f1:.1%}\n")
                f.write(f"False Positives:           {metrics.false_positives}\n")
                f.write(f"False Negatives:           {metrics.false_negatives}\n")
                f.write("\n")

                f.write("CONTROL ACTION METRICS\n")
                f.write("-" * 80 + "\n")
                f.write(f"Baseline Lights On:        {metrics.baseline_light_on_percent:.1f}%\n")
                f.write(f"AI Lights On:              {metrics.ai_light_on_percent:.1f}%\n")
                f.write(f"Baseline HVAC On:          {metrics.baseline_hvac_on_percent:.1f}%\n")
                f.write(f"AI HVAC On:                {metrics.ai_hvac_on_percent:.1f}%\n")
                f.write(f"Baseline Mode Changes:     {metrics.baseline_control_changes}\n")
                f.write(f"AI Mode Changes:           {metrics.ai_control_changes}\n")
                f.write("\n")

                f.write("COMFORT & SAFETY METRICS\n")
                f.write("-" * 80 + "\n")
                f.write(f"Comfort Violations:        {metrics.total_comfort_violations}\n")
                f.write(f"Comfort Violation Rate:    {metrics.comfort_violation_percent:.1f}%\n")
                f.write(f"False Shutoff Events:      {metrics.false_shutoff_events}\n")
                f.write("  (Times AI turned off lights while room was occupied)\n")
                f.write("\n")

                f.write("=" * 80 + "\n")
                f.write("EVALUATION COMPLETE\n")
                f.write("=" * 80 + "\n")

            logger.info(f"[OK] Metrics summary saved: {output_path}")
        except Exception as e:
            logger.error(f"Failed to save metrics summary: {e}")

    def plot_results(self, output_dir: str = "output/plots/") -> None:
        """
        Create visualization plots of evaluation results.

        Args:
            output_dir: Directory to save plots
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if len(self.steps) == 0:
            logger.warning("No data to plot")
            return

        timestamps = [s.timestamp for s in self.steps]
        times_hours = [(t - timestamps[0]).total_seconds() / 3600 for t in timestamps]

        try:
            # Plot 1: Energy consumption over time
            fig, ax = plt.subplots(figsize=(14, 6))
            baseline_energy = np.cumsum([s.baseline_energy_wh for s in self.steps]) / 1000
            ai_energy = np.cumsum([s.ai_energy_wh for s in self.steps]) / 1000

            ax.plot(times_hours, baseline_energy, label="Baseline", linewidth=2, alpha=0.8)
            ax.plot(times_hours, ai_energy, label="AI-Assisted", linewidth=2, alpha=0.8)
            ax.fill_between(times_hours, baseline_energy, ai_energy, alpha=0.2, label="Energy Saved")

            ax.set_xlabel("Time (hours)", fontsize=12)
            ax.set_ylabel("Cumulative Energy (kWh)", fontsize=12)
            ax.set_title("Cumulative Energy Consumption: Baseline vs AI-Assisted Control", fontsize=14)
            ax.legend(fontsize=11)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(f"{output_dir}cumulative_energy.png", dpi=300, bbox_inches="tight")
            plt.close()
            logger.info(f"[OK] Saved: {output_dir}cumulative_energy.png")

            # Plot 2: Occupancy prediction accuracy over time
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

            # True vs predicted occupancy
            true_occ = [s.true_occupancy for s in self.steps]
            pred_occ = [s.predicted_occupancy_prob for s in self.steps]

            ax1.scatter(times_hours, true_occ, label="True Occupancy", alpha=0.5, s=20)
            ax1.plot(times_hours, pred_occ, label="Predicted Probability", linewidth=2, alpha=0.8)
            ax1.axhline(y=0.5, color="r", linestyle="--", alpha=0.5, label="Decision Threshold")

            ax1.set_ylabel("Occupancy", fontsize=12)
            ax1.set_title("Occupancy: True vs Predicted Probability", fontsize=14)
            ax1.legend(fontsize=11)
            ax1.grid(True, alpha=0.3)
            ax1.set_ylim(-0.1, 1.1)

            # Control decisions
            baseline_modes = [s.baseline_control_mode for s in self.steps]
            ai_modes = [s.ai_control_mode for s in self.steps]

            mode_to_num = {"EMPTY": 0, "STANDBY": 1, "OCCUPIED": 2}
            baseline_mode_nums = [mode_to_num.get(m, 0) for m in baseline_modes]
            ai_mode_nums = [mode_to_num.get(m, 0) for m in ai_modes]

            ax2.plot(times_hours, baseline_mode_nums, label="Baseline", linewidth=2, alpha=0.8)
            ax2.plot(times_hours, ai_mode_nums, label="AI-Assisted", linewidth=2, alpha=0.8)

            ax2.set_xlabel("Time (hours)", fontsize=12)
            ax2.set_ylabel("Control Mode", fontsize=12)
            ax2.set_title("Control Mode Over Time", fontsize=14)
            ax2.set_yticks([0, 1, 2])
            ax2.set_yticklabels(["EMPTY", "STANDBY", "OCCUPIED"])
            ax2.legend(fontsize=11)
            ax2.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.savefig(f"{output_dir}occupancy_and_control.png", dpi=300, bbox_inches="tight")
            plt.close()
            logger.info(f"[OK] Saved: {output_dir}occupancy_and_control.png")

            # Plot 3: Control actions (lights and HVAC)
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

            # Light actions
            baseline_light = [s.baseline_light for s in self.steps]
            ai_light = [s.ai_light for s in self.steps]

            light_to_num = {"OFF": 0, "DIM": 0.5, "ON": 1}
            baseline_light_nums = [light_to_num.get(l, 0) for l in baseline_light]
            ai_light_nums = [light_to_num.get(l, 0) for l in ai_light]

            ax1.plot(times_hours, baseline_light_nums, label="Baseline", linewidth=2, alpha=0.8)
            ax1.plot(times_hours, ai_light_nums, label="AI-Assisted", linewidth=2, alpha=0.8)

            ax1.set_ylabel("Light Action", fontsize=12)
            ax1.set_title("Lighting Control Over Time", fontsize=14)
            ax1.set_yticks([0, 0.5, 1])
            ax1.set_yticklabels(["OFF", "DIM", "ON"])
            ax1.legend(fontsize=11)
            ax1.grid(True, alpha=0.3)

            # HVAC actions
            baseline_hvac = [s.baseline_hvac for s in self.steps]
            ai_hvac = [s.ai_hvac for s in self.steps]

            hvac_to_num = {"ECO": 0, "LOW": 1, "NORMAL": 2}
            baseline_hvac_nums = [hvac_to_num.get(h, 0) for h in baseline_hvac]
            ai_hvac_nums = [hvac_to_num.get(h, 0) for h in ai_hvac]

            ax2.plot(times_hours, baseline_hvac_nums, label="Baseline", linewidth=2, alpha=0.8)
            ax2.plot(times_hours, ai_hvac_nums, label="AI-Assisted", linewidth=2, alpha=0.8)

            ax2.set_xlabel("Time (hours)", fontsize=12)
            ax2.set_ylabel("HVAC Action", fontsize=12)
            ax2.set_title("HVAC Control Over Time", fontsize=14)
            ax2.set_yticks([0, 1, 2])
            ax2.set_yticklabels(["ECO", "LOW", "NORMAL"])
            ax2.legend(fontsize=11)
            ax2.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.savefig(f"{output_dir}control_actions.png", dpi=300, bbox_inches="tight")
            plt.close()
            logger.info(f"[OK] Saved: {output_dir}control_actions.png")

            # Plot 4: Temperature and comfort violations
            fig, ax = plt.subplots(figsize=(14, 6))

            temps = [s.temperature for s in self.steps]
            ax.plot(times_hours, temps, label="Temperature", linewidth=2, alpha=0.8)
            ax.axhline(y=self.COMFORT_TEMP_MIN, color="b", linestyle="--", alpha=0.5, label="Min Comfort")
            ax.axhline(y=self.COMFORT_TEMP_MAX, color="r", linestyle="--", alpha=0.5, label="Max Comfort")

            # Highlight comfort violations
            violations = [s.comfort_violation for s in self.steps]
            violation_times = [t for t, v in zip(times_hours, violations) if v]
            violation_temps = [tmp for tmp, v in zip(temps, violations) if v]

            if violation_times:
                ax.scatter(violation_times, violation_temps, color="red", s=50, alpha=0.7, label="Violations")

            ax.set_xlabel("Time (hours)", fontsize=12)
            ax.set_ylabel("Temperature (°C)", fontsize=12)
            ax.set_title("Temperature Profile and Comfort Violations", fontsize=14)
            ax.legend(fontsize=11)
            ax.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.savefig(f"{output_dir}temperature_comfort.png", dpi=300, bbox_inches="tight")
            plt.close()
            logger.info(f"[OK] Saved: {output_dir}temperature_comfort.png")

            logger.info(f"[OK] All plots saved to {output_dir}")

        except Exception as e:
            logger.error(f"Failed to generate plots: {e}")

    def save_all_results(
        self,
        metrics_output_dir: str = "output/metrics/",
        plots_output_dir: str = "output/plots/",
    ) -> None:
        """
        Save all evaluation results (logs, metrics, plots).

        Args:
            metrics_output_dir: Directory for CSV and metrics files
            plots_output_dir: Directory for plot images
        """
        logger.info("=" * 80)
        logger.info("SAVING EVALUATION RESULTS")
        logger.info("=" * 80)

        self.save_detailed_log(f"{metrics_output_dir}control_evaluation_log.csv")
        self.save_metrics_summary(f"{metrics_output_dir}control_evaluation.txt")
        self.plot_results(plots_output_dir)

        logger.info("=" * 80)
        logger.info("RESULTS SAVED SUCCESSFULLY")
        logger.info("=" * 80)


# Example usage and demo
if __name__ == "__main__":
    logger.info("CONTROL EVALUATOR - DEMO")
    logger.info("=" * 80)

    # Create evaluator
    evaluator = ControlEvaluator()

    # Simulate 24 hours (1440 minutes) of operation
    logger.info("Running 24-hour evaluation simulation...")

    start_time = datetime(2026, 4, 4, 6, 0, 0)  # 6 AM
    for i in range(1440):  # 24 hours at 1 min per timestep
        current_time = start_time + timedelta(minutes=i)
        hour_of_day = current_time.hour

        # Generate realistic occupancy pattern
        # Occupied: 8 AM - 6 PM (office hours)
        # Occasional: 6 PM - 8 PM
        # Empty: 8 PM - 8 AM
        if 8 <= hour_of_day < 18:
            true_occupancy = 1  # Occupied during office hours
        elif 18 <= hour_of_day < 20:
            true_occupancy = int(np.random.random() > 0.5)  # 50% chance after hours
        else:
            true_occupancy = 0  # Empty at night

        # Generate realistic sensor readings
        base_temp = 21.0
        if hour_of_day < 12:
            temp_offset = (hour_of_day - 6) * 0.5  # Warming up in morning
        else:
            temp_offset = (18 - hour_of_day) * 0.5  # Cooling down in afternoon

        sensor_data = {
            "Temperature": base_temp + temp_offset + np.random.normal(0, 0.5),
            "Humidity": 40 + (true_occupancy * 10) + np.random.normal(0, 2),
            "Light": (true_occupancy * 300) + np.random.normal(0, 50),
            "CO2": 400 + (true_occupancy * 200) + np.random.normal(0, 20),
            "HumidityRatio": 0.004 + (true_occupancy * 0.001) + np.random.normal(0, 0.0005),
        }

        evaluator.add_timestep(current_time, sensor_data, true_occupancy)

    # Compute metrics and save results
    metrics = evaluator.compute_metrics()
    evaluator.save_all_results()

    logger.info("=" * 80)
    logger.info("DEMO COMPLETE")
    logger.info("=" * 80)
