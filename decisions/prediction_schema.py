"""
Prediction Schema - Standard ML Model Outputs

Defines what ML models output and how to convert predictions to control decisions.
Enables pluggable scikit-learn and PyTorch models.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np
from decisions.controller import DecisionOutput


@dataclass
class ModelPrediction:
    """
    Standard output from ML decision models.

    All values are in normalized space (0-1) before conversion to DecisionOutput.
    Models output these raw predictions; ActionDecoder converts to control commands.
    """

    # Light decision (0-1: 0=off, 1=on)
    light_probability: float = 0.0

    # HVAC mode (3 values sum to 1.0)
    hvac_heating_prob: float = 0.0  # Probability of heating mode
    hvac_cooling_prob: float = 0.0  # Probability of cooling mode
    hvac_off_prob: float = 0.0  # Probability of off mode

    # HVAC continuous (0-1)
    hvac_speed: float = 0.5  # Continuous speed (0 = off, 1 = max)
    hvac_setpoint: float = 0.5  # Normalized setpoint (0.5 = 21.5°C middle)

    # Shading factor (0-1)
    shading_factor: float = 0.0  # 0 = open, 1 = fully closed

    # Model metadata
    confidence: float = 1.0  # Model confidence (0-1)
    model_version: str = "1.0"  # For tracking model versions

    def __post_init__(self):
        """Validate prediction values."""
        assert 0.0 <= self.light_probability <= 1.0, "light_probability out of range"
        assert 0.0 <= self.hvac_heating_prob <= 1.0, "hvac_heating_prob out of range"
        assert 0.0 <= self.hvac_cooling_prob <= 1.0, "hvac_cooling_prob out of range"
        assert 0.0 <= self.hvac_off_prob <= 1.0, "hvac_off_prob out of range"
        assert 0.0 <= self.hvac_speed <= 1.0, "hvac_speed out of range"
        assert 0.0 <= self.shading_factor <= 1.0, "shading_factor out of range"
        assert 0.0 <= self.confidence <= 1.0, "confidence out of range"

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary for logging."""
        return {
            "light_probability": self.light_probability,
            "hvac_heating_prob": self.hvac_heating_prob,
            "hvac_cooling_prob": self.hvac_cooling_prob,
            "hvac_off_prob": self.hvac_off_prob,
            "hvac_speed": self.hvac_speed,
            "hvac_setpoint": self.hvac_setpoint,
            "shading_factor": self.shading_factor,
            "confidence": self.confidence,
        }


class ActionDecoder:
    """
    Converts normalized ML predictions to concrete DecisionOutput commands.

    Handles:
    - Probability thresholding for discrete decisions
    - Normalization reversal for continuous values
    - Fallback to safe defaults on invalid predictions
    """

    # Thresholds for discrete decisions
    LIGHT_ON_THRESHOLD = 0.5  # >0.5 prob → turn on
    HVAC_MODE_THRESHOLD = 0.4  # Mode prob must exceed this to be selected
    SHADING_DEADBAND = 0.05  # Hysteresis for shading factor

    @staticmethod
    def decode(prediction: ModelPrediction, context_reason: str = "") -> DecisionOutput:
        """
        Convert model prediction to DecisionOutput.

        Args:
            prediction: ModelPrediction from ML model
            context_reason: Optional reasoning to include

        Returns:
            DecisionOutput with validated control commands
        """

        # ===== LIGHT DECISION =====
        light_on = prediction.light_probability > ActionDecoder.LIGHT_ON_THRESHOLD

        # ===== HVAC MODE DECISION =====
        hvac_modes = {
            "heating": prediction.hvac_heating_prob,
            "cooling": prediction.hvac_cooling_prob,
            "off": prediction.hvac_off_prob,
        }

        # Find mode with highest probability (if above threshold)
        best_mode = max(hvac_modes, key=hvac_modes.get)
        best_prob = hvac_modes[best_mode]

        if best_prob < ActionDecoder.HVAC_MODE_THRESHOLD:
            hvac_mode = "off"  # Fallback if no mode confident
        else:
            hvac_mode = best_mode

        # ===== HVAC SETPOINT (denormalize) =====
        # Prediction assumed 0.5 = 21.5°C center
        # Range: 18°C (0.0) to 25°C (1.0)
        hvac_setpoint = 18.0 + prediction.hvac_setpoint * 7.0
        hvac_setpoint = np.clip(hvac_setpoint, 15.0, 28.0)

        # ===== HVAC SPEED =====
        hvac_speed = prediction.hvac_speed
        if hvac_mode == "off":
            hvac_speed = 0.0  # Force off if mode is off

        # ===== SHADING FACTOR =====
        shading_factor = prediction.shading_factor

        # ===== BUILD REASON =====
        reason_parts = []

        if prediction.confidence < 0.6:
            reason_parts.append(f"(Low confidence: {prediction.confidence:.1%})")

        confidence_str = "high" if prediction.confidence > 0.8 else "moderate"
        reason_parts.append(f"[ML Model v{prediction.model_version}, {confidence_str} confidence]")

        decision_reason = " ".join(reason_parts) if reason_parts else "ML decision"

        # ===== VALIDATE & RETURN =====
        decision = DecisionOutput(
            light_on=light_on,
            hvac_mode=hvac_mode,
            hvac_setpoint=hvac_setpoint,
            hvac_speed=hvac_speed,
            shading_factor=shading_factor,
            decision_reason=decision_reason,
        )

        decision.validate()
        return decision

    @staticmethod
    def decode_array(predictions_array: np.ndarray) -> List[DecisionOutput]:
        """
        Batch decode predictions from numpy array.

        Args:
            predictions_array: Array of shape (batch_size, 8) with raw predictions

        Returns:
            List of DecisionOutput objects
        """
        decisions = []
        for pred_row in predictions_array:
            prediction = ModelPrediction(
                light_probability=pred_row[0],
                hvac_heating_prob=pred_row[1],
                hvac_cooling_prob=pred_row[2],
                hvac_off_prob=pred_row[3],
                hvac_speed=pred_row[4],
                hvac_setpoint=pred_row[5],
                shading_factor=pred_row[6],
                confidence=pred_row[7] if len(pred_row) > 7 else 0.5,
            )
            decisions.append(ActionDecoder.decode(prediction))
        return decisions


class PredictionLogger:
    """
    Logs model predictions for analysis and retraining.

    Tracks what models predict vs. what actually happened (ground truth).
    Useful for model improvement and domain adaptation.
    """

    def __init__(self):
        """Initialize prediction logger."""
        self.predictions_log: List[Dict] = []

    def log_prediction(
        self, room_id: int, model_name: str, prediction: ModelPrediction,
        decision: DecisionOutput, actual_features: Dict = None
    ):
        """
        Log a model prediction.

        Args:
            room_id: Room identifier
            model_name: Name of model that made prediction
            prediction: Raw ModelPrediction
            decision: Decoded DecisionOutput
            actual_features: Optional: actual environmental outcome (for later comparison)
        """
        log_entry = {
            "room_id": room_id,
            "model_name": model_name,
            "prediction": prediction.to_dict(),
            "decision": {
                "light_on": decision.light_on,
                "hvac_mode": decision.hvac_mode,
                "hvac_setpoint": decision.hvac_setpoint,
                "hvac_speed": decision.hvac_speed,
                "shading_factor": decision.shading_factor,
            },
        }

        if actual_features:
            log_entry["actual"] = actual_features

        self.predictions_log.append(log_entry)

    def get_logs(self) -> List[Dict]:
        """Get all logged predictions."""
        return self.predictions_log

    def save_logs(self, filepath: str):
        """Save predictions to JSON for analysis."""
        import json
        with open(filepath, "w") as f:
            json.dump(self.predictions_log, f, indent=2)

    def clear_logs(self):
        """Clear prediction logs."""
        self.predictions_log = []
