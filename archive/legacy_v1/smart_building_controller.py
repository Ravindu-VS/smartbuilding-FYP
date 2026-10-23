"""
Smart Building Controller

Real-time building automation decisions based on occupancy predictions.

Loads the domain-adapted occupancy detection pipeline and uses occupancy probability
to make intelligent building control decisions:
- Light control (OFF, DIM, ON)
- HVAC mode control (ECO/OFF, LOW, NORMAL)
- Energy-saving mode selection

Features:
- 3-zone occupancy control strategy
- Threshold-based decision making (default: 0.20 for occupancy detection)
- Missing value handling via integrated pipeline
- Comprehensive logging and diagnostics
- JSON-serializable control decision output

Usage:
    controller = SmartBuildingController('models/final_unified_occupancy_pipeline.pkl')
    decision = controller.get_control_decision({
        'Temperature': 21.5,
        'Humidity': 35.0,
        'Light': 450.0,
        'CO2': 700.0,
        'HumidityRatio': 0.0045
    })
    print(decision['control_mode'])  # 'OCCUPIED'
    print(decision['light_action'])  # 'ON'
    print(decision['hvac_action'])   # 'NORMAL'
"""

import logging
import json
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from occupancy_inference_service import OccupancyInferenceService, InferenceResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ControlDecision:
    """Building control decision output."""
    occupancy_probability: float
    occupancy_prediction: int
    control_mode: str
    light_action: str
    hvac_action: str
    energy_mode: str
    confidence: float
    missing_values_count: int
    diagnostics: Dict


class SmartBuildingController:
    """
    Smart building automation controller using occupancy inference.

    Converts occupancy probability to building control decisions across
    three control zones with threshold-based decision logic.
    """

    # Control zone thresholds
    EMPTY_THRESHOLD = 0.20      # Probability below this → EMPTY mode
    OCCUPIED_THRESHOLD = 0.60   # Probability above this → OCCUPIED mode
    # 0.20-0.60 is STANDBY zone

    # Control actions for each zone
    CONTROL_ACTIONS = {
        'EMPTY': {
            'light': 'OFF',
            'hvac': 'ECO',
            'energy_mode': 'MAXIMUM_SAVINGS',
            'description': 'No occupancy - maximize energy savings'
        },
        'STANDBY': {
            'light': 'DIM',
            'hvac': 'LOW',
            'energy_mode': 'COMFORT_SAVINGS',
            'description': 'Possible occupancy - balanced control'
        },
        'OCCUPIED': {
            'light': 'ON',
            'hvac': 'NORMAL',
            'energy_mode': 'COMFORT_PRIORITY',
            'description': 'Confirmed occupancy - comfort mode'
        }
    }

    def __init__(self, model_path: str = "models/final_unified_occupancy_pipeline.pkl", empty_threshold: float = 0.20,
                 occupied_threshold: float = 0.60):
        """
        Initialize the smart building controller.

        Args:
            model_path: Path to the trained domain-adapted occupancy pipeline
            empty_threshold: Probability threshold for EMPTY mode (default: 0.20)
            occupied_threshold: Probability threshold for OCCUPIED mode (default: 0.60)

        Raises:
            FileNotFoundError: If model file doesn't exist
            ValueError: If thresholds are invalid
        """
        # Validate thresholds
        if not (0 < empty_threshold < occupied_threshold < 1.0):
            raise ValueError(
                f"Invalid thresholds: empty={empty_threshold}, occupied={occupied_threshold}. "
                f"Must have: 0 < empty < occupied < 1.0"
            )

        self.empty_threshold = empty_threshold
        self.occupied_threshold = occupied_threshold
        self.model_path = Path(model_path)

        logger.info(f"Initializing SmartBuildingController")
        logger.info(f"Model path: {self.model_path}")
        logger.info(f"Control thresholds: EMPTY<{empty_threshold}, "
                   f"STANDBY [{empty_threshold}-{occupied_threshold}], "
                   f"OCCUPIED≥{occupied_threshold}")

        # Initialize inference service (loads pipeline once)
        self.inference_service = OccupancyInferenceService(
            str(self.model_path),
            threshold=empty_threshold
        )
        logger.info("✓ SmartBuildingController ready")

    def get_control_decision(self, sensor_data: Dict[str, Optional[float]]) -> ControlDecision:
        """
        Get building control decision from sensor data.

        Args:
            sensor_data: Dictionary with sensor readings
                        {
                            'Temperature': 20.5,
                            'Humidity': 35.0,
                            'Light': 200.0,
                            'CO2': 600.0,
                            'HumidityRatio': 0.0045,
                            # Missing values can be None or omitted
                        }

        Returns:
            ControlDecision with occupancy prediction and building control actions

        Raises:
            ValueError: If sensor_data is invalid
        """
        # Get occupancy prediction from inference service
        inference_result: InferenceResult = self.inference_service.predict(sensor_data)

        # Determine control zone
        occupancy_prob = inference_result.occupancy_probability
        control_mode = self._get_control_mode(occupancy_prob)

        # Get control actions for the determined zone
        actions = self.CONTROL_ACTIONS[control_mode]

        # Log decision
        logger.info(f"Control Decision | Probability={occupancy_prob:.4f} | Mode={control_mode} | "
                   f"Light={actions['light']} | HVAC={actions['hvac']}")

        # Build control decision
        decision = ControlDecision(
            occupancy_probability=inference_result.occupancy_probability,
            occupancy_prediction=inference_result.occupancy_prediction,
            control_mode=control_mode,
            light_action=actions['light'],
            hvac_action=actions['hvac'],
            energy_mode=actions['energy_mode'],
            confidence=inference_result.confidence,
            missing_values_count=inference_result.missing_count,
            diagnostics={
                'threshold_description': actions['description'],
                'empty_threshold': self.empty_threshold,
                'occupied_threshold': self.occupied_threshold,
                'confidence': inference_result.confidence,
                'missing_values': inference_result.missing_values,
                'model_diagnostics': inference_result.diagnostics
            }
        )

        return decision

    def _get_control_mode(self, occupancy_probability: float) -> str:
        """
        Determine control mode from occupancy probability.

        Args:
            occupancy_probability: Predicted occupancy probability [0, 1]

        Returns:
            Control mode: 'EMPTY', 'STANDBY', or 'OCCUPIED'
        """
        if occupancy_probability < self.empty_threshold:
            return 'EMPTY'
        elif occupancy_probability < self.occupied_threshold:
            return 'STANDBY'
        else:
            return 'OCCUPIED'

    def batch_control_decisions(self, sensor_data_list: list) -> list:
        """
        Get control decisions for multiple sensor readings.

        Args:
            sensor_data_list: List of sensor data dictionaries

        Returns:
            List of ControlDecision objects
        """
        logger.info(f"Processing batch control decisions for {len(sensor_data_list)} readings")
        decisions = [self.get_control_decision(data) for data in sensor_data_list]
        logger.info(f"✓ Batch processing complete")
        return decisions

    def to_json(self, decision: ControlDecision) -> str:
        """
        Serialize control decision to JSON.

        Args:
            decision: ControlDecision object

        Returns:
            JSON string representation
        """
        decision_dict = asdict(decision)
        return json.dumps(decision_dict, indent=2)

    def print_decision_summary(self, decision: ControlDecision) -> None:
        """Print human-readable summary of control decision."""
        print("\n" + "="*70)
        print("BUILDING CONTROL DECISION")
        print("="*70)
        print(f"Occupancy Probability: {decision.occupancy_probability:.4f}")
        print(f"Confidence:            {decision.confidence:.4f}")
        print(f"Missing Values:        {decision.missing_values_count}")
        print(f"\nControl Mode:          {decision.control_mode}")
        print(f"  - Light Action:      {decision.light_action}")
        print(f"  - HVAC Action:       {decision.hvac_action}")
        print(f"  - Energy Mode:       {decision.energy_mode}")
        print(f"\nDescription:           {decision.diagnostics['threshold_description']}")
        print("="*70 + "\n")


if __name__ == "__main__":
    # Demo usage
    logger.info("="*80)
    logger.info("SMART BUILDING CONTROLLER - DEMO")
    logger.info("="*80)

    try:
        controller = SmartBuildingController(
            "models/final_unified_occupancy_pipeline.pkl",
            empty_threshold=0.20,
            occupied_threshold=0.60
        )

        # Example 1: Clear occupancy (morning with people in room)
        print("\n[Example 1] Morning - Occupied Room")
        sensor_data_1 = {
            'Temperature': 21.5,
            'Humidity': 35.0,
            'Light': 450.0,
            'CO2': 700.0,
            'HumidityRatio': 0.0045
        }
        decision_1 = controller.get_control_decision(sensor_data_1)
        controller.print_decision_summary(decision_1)

        # Example 2: Standby occupancy (room partially occupied, dimmed lights)
        print("\n[Example 2] Afternoon - Minimal Activity")
        sensor_data_2 = {
            'Temperature': 20.0,
            'Humidity': 40.0,
            'Light': 150.0,
            'CO2': 520.0,
            'HumidityRatio': 0.0038
        }
        decision_2 = controller.get_control_decision(sensor_data_2)
        controller.print_decision_summary(decision_2)

        # Example 3: Empty room (evening after everyone leaves)
        print("\n[Example 3] Evening - Empty Room")
        sensor_data_3 = {
            'Temperature': 19.5,
            'Humidity': 25.0,
            'Light': 50.0,
            'CO2': 420.0,
            'HumidityRatio': 0.0035
        }
        decision_3 = controller.get_control_decision(sensor_data_3)
        controller.print_decision_summary(decision_3)

        # Example 4: Missing sensor value (one sensor temporarily down)
        print("\n[Example 4] System Fault - Missing Humidity Sensor")
        sensor_data_4 = {
            'Temperature': 21.0,
            'Humidity': None,  # Sensor down - will be imputed by pipeline
            'Light': 350.0,
            'CO2': 650.0,
            'HumidityRatio': 0.0044
        }
        decision_4 = controller.get_control_decision(sensor_data_4)
        controller.print_decision_summary(decision_4)

        # Batch processing demo
        print("\n[Batch Example] Processing 3 readings in sequence")
        batch_data = [sensor_data_1, sensor_data_2, sensor_data_3]
        batch_decisions = controller.batch_control_decisions(batch_data)
        for i, decision in enumerate(batch_decisions, 1):
            print(f"Batch {i}: {decision.control_mode} mode, "
                  f"Light={decision.light_action}, HVAC={decision.hvac_action}")

        logger.info("="*80)
        logger.info("DEMO COMPLETE - All examples executed successfully")
        logger.info("="*80)

    except FileNotFoundError as e:
        logger.error(f"Demo skipped - Model file not found: {e}")
    except Exception as e:
        logger.error(f"Demo error: {e}", exc_info=True)
