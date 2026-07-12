"""
Occupancy Inference Service

Loads the trained domain-adapted occupancy detection pipeline and provides
inference services with diagnostics for missing values, confidence scores,
and predicted occupancy probabilities.

This module handles:
- Pipeline loading and caching
- Sensor input validation
- Inference with missing value detection
- Confidence scoring
- Detailed diagnostics reporting

    service = OccupancyInferenceService()
    result = service.predict(sensor_data={'Temperature': 20.5, 'Humidity': 35.0, ...})
    print(result['occupancy_probability'])
"""

import pickle
import joblib
import logging
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Expected features for the model
REQUIRED_FEATURES = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']


@dataclass
class InferenceResult:
    """Result from occupancy inference service."""
    occupancy_probability: float
    occupancy_prediction: int
    confidence: float
    missing_values: Dict[str, bool]
    missing_count: int
    missing_percentage: float
    input_features: Dict[str, Optional[float]]
    diagnostics: Dict


class OccupancyInferenceService:
    """
    Occupancy detection inference service using trained sklearn Pipeline.

    The pipeline includes:
    - SimpleImputer for handling missing values
    - StandardScaler for feature normalization
    - Classifier (Logistic Regression or Random Forest)
    """

    def __init__(self, model_path: str = "models/final_unified_occupancy_pipeline.pkl", scaler_path: Optional[str] = None, threshold: float = 0.5):
        """
        Initialize the inference service.

        Args:
            model_path: Path to the pickled model
            scaler_path: Path to the pickled scaler
            threshold: Decision threshold for occupancy (default: 0.5)

        Raises:
            FileNotFoundError: If model file doesn't exist
            ValueError: If model file can't be loaded
        """
        self.model_path = Path(model_path)
        self.scaler_path = Path(scaler_path) if scaler_path else None
        self.threshold = threshold
        self.model = None
        self.scaler = None

        logger.info(f"Initializing OccupancyInferenceService with model: {self.model_path} and scaler: {self.scaler_path}")
        logger.info(f"Using decision threshold: {self.threshold}")

        # Load artifacts
        self._load_artifacts()

    def _load_artifacts(self):
        """Load the trained model and scaler from disk."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        try:
            self.model = joblib.load(self.model_path)
            if self.scaler_path and self.scaler_path.exists():
                self.scaler = joblib.load(self.scaler_path)
            logger.info(f"✓ Model loaded successfully from {self.model_path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise ValueError(f"Can't load model: {e}")

    def predict(self, sensor_data: Dict[str, Optional[float]]) -> InferenceResult:
        """
        Make occupancy prediction from sensor data.

        Args:
            sensor_data: Dictionary with sensor values
                        {
                            'Temperature': 20.5,
                            'Humidity': 35.0,
                            'Light': 200.0,
                            'CO2': 600.0,
                            'HumidityRatio': 0.0045,
                            # Missing values can be None or omitted
                        }

        Returns:
            InferenceResult with predictions and diagnostics

        Raises:
            ValueError: If required features are missing
        """
        # Validate and prepare features
        features_array = self._prepare_features(sensor_data)

        # Build a DataFrame with proper column names for the pipeline
        features_df = pd.DataFrame([features_array], columns=REQUIRED_FEATURES)

        # If we have a separate scaler (legacy models), apply manual imputation + scaling
        if self.scaler:
            features_array = np.nan_to_num(features_array, nan=0.0)
            features_array = self.scaler.transform([features_array])[0]
            occupancy_pred = self.model.predict([features_array])[0]
            occupancy_prob = self.model.predict_proba([features_array])[0][1]
        else:
            # Unified pipeline handles imputation + scaling internally
            occupancy_pred = self.model.predict(features_df)[0]
            occupancy_prob = self.model.predict_proba(features_df)[0][1]

        # Calculate confidence
        confidence = max(occupancy_prob, 1 - occupancy_prob)

        # Detect missing values
        missing_values = {feat: sensor_data.get(feat) is None for feat in REQUIRED_FEATURES}
        missing_count = sum(missing_values.values())
        missing_percentage = 100 * missing_count / len(REQUIRED_FEATURES)

        # Build diagnostics
        diagnostics = {
            'threshold_used': self.threshold,
            'model_steps': ['scaler', 'model'],
            'imputation_strategy': 'fillna',
            'scaling_method': 'StandardScaler',
            'decision': 'OCCUPIED' if occupancy_prob >= self.threshold else 'EMPTY'
        }

        # Log inference
        logger.info(f"Inference: Probability={occupancy_prob:.4f}, Prediction={occupancy_pred}, "
                   f"Missing={missing_count}/{len(REQUIRED_FEATURES)}")

        return InferenceResult(
            occupancy_probability=float(occupancy_prob),
            occupancy_prediction=int(occupancy_pred),
            confidence=float(confidence),
            missing_values=missing_values,
            missing_count=missing_count,
            missing_percentage=float(missing_percentage),
            input_features={feat: sensor_data.get(feat) for feat in REQUIRED_FEATURES},
            diagnostics=diagnostics
        )

    def _prepare_features(self, sensor_data: Dict[str, Optional[float]]) -> np.ndarray:
        """
        Prepare and validate sensor data for inference.

        Args:
            sensor_data: Raw sensor measurements

        Returns:
            Feature array in correct order [Temperature, Humidity, Light, CO2, HumidityRatio]

        Raises:
            ValueError: If required features are missing
        """
        features = []

        for feature_name in REQUIRED_FEATURES:
            value = sensor_data.get(feature_name)
            # None values will be handled by SimpleImputer in the pipeline
            if value is None:
                features.append(np.nan)
            else:
                try:
                    features.append(float(value))
                except (ValueError, TypeError):
                    logger.warning(f"Invalid value for {feature_name}: {value}, using NaN")
                    features.append(np.nan)

        return np.array(features)

    def batch_predict(self, sensor_data_list: List[Dict]) -> List[InferenceResult]:
        """
        Make predictions for multiple sensor readings.

        Args:
            sensor_data_list: List of sensor data dictionaries

        Returns:
            List of InferenceResult objects
        """
        logger.info(f"Making batch predictions for {len(sensor_data_list)} samples")
        results = [self.predict(data) for data in sensor_data_list]
        logger.info(f"✓ Batch prediction complete")
        return results

    def get_confidence_metrics(self, results: List[InferenceResult]) -> Dict:
        """
        Calculate confidence metrics from a batch of results.

        Args:
            results: List of InferenceResult objects

        Returns:
            Dictionary with confidence statistics
        """
        confidences = [r.confidence for r in results]
        probs = [r.occupancy_probability for r in results]

        return {
            'mean_confidence': float(np.mean(confidences)),
            'min_confidence': float(np.min(confidences)),
            'max_confidence': float(np.max(confidences)),
            'std_confidence': float(np.std(confidences)),
            'mean_occupancy_probability': float(np.mean(probs)),
            'predicted_occupied_count': sum(1 for r in results if r.occupancy_prediction == 1),
            'predicted_empty_count': sum(1 for r in results if r.occupancy_prediction == 0),
        }


if __name__ == "__main__":
    # Demo usage
    logger.info("="*80)
    logger.info("OCCUPANCY INFERENCE SERVICE - DEMO")
    logger.info("="*80)

    # Initialize service
    try:
        service = OccupancyInferenceService(threshold=0.5)

        # Example 1: Room with clear occupancy
        print("\n[Example 1] Clear Occupancy")
        sensor_data_1 = {
            'Temperature': 21.5,
            'Humidity': 35.0,
            'Light': 450.0,
            'CO2': 700.0,
            'HumidityRatio': 0.0045
        }
        result_1 = service.predict(sensor_data_1)
        print(f"Probability: {result_1.occupancy_probability:.4f}")
        print(f"Prediction: {'OCCUPIED' if result_1.occupancy_prediction else 'EMPTY'}")
        print(f"Confidence: {result_1.confidence:.4f}")

        # Example 2: Empty room
        print("\n[Example 2] Empty Room")
        sensor_data_2 = {
            'Temperature': 19.5,
            'Humidity': 25.0,
            'Light': 50.0,
            'CO2': 420.0,
            'HumidityRatio': 0.0035
        }
        result_2 = service.predict(sensor_data_2)
        print(f"Probability: {result_2.occupancy_probability:.4f}")
        print(f"Prediction: {'OCCUPIED' if result_2.occupancy_prediction else 'EMPTY'}")
        print(f"Confidence: {result_2.confidence:.4f}")

        # Example 3: Missing sensor value
        print("\n[Example 3] Missing Humidity Value")
        sensor_data_3 = {
            'Temperature': 20.5,
            'Humidity': None,  # Missing value
            'Light': 300.0,
            'CO2': 550.0,
            'HumidityRatio': 0.0042
        }
        result_3 = service.predict(sensor_data_3)
        print(f"Probability: {result_3.occupancy_probability:.4f}")
        print(f"Prediction: {'OCCUPIED' if result_3.occupancy_prediction else 'EMPTY'}")
        print(f"Missing Values: {sum(result_3.missing_values.values())}")

    except FileNotFoundError as e:
        logger.warning(f"Demo skipped: {e}")
