"""
Simple inference script for occupancy prediction using trained UCI model.

Use this to make occupancy predictions on new sensor data from your smart building.

Example:
    # Make predictions
    python occupancy_predictor.py --csv sensor_data.csv

    # Or use programmatically
    from occupancy_predictor import OccupancyPredictor

    predictor = OccupancyPredictor()
    data = {
        'Temperature': 21.5,
        'Humidity': 45.0,
        'Light': 450.0,
        'CO2': 520.0,
        'HumidityRatio': 0.075
    }
    occupancy, confidence = predictor.predict_single(data)
    print(f"Occupancy: {occupancy}, Confidence: {confidence:.2%}")
"""

import joblib
import pandas as pd
import numpy as np
import json
import logging
from pathlib import Path
from argparse import ArgumentParser

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent
MODELS_DIR = PROJECT_ROOT / "models"
MODEL_PATH = MODELS_DIR / "uci_occupancy_model.pkl"
SCALER_PATH = MODELS_DIR / "uci_occupancy_scaler.pkl"
FEATURES_PATH = MODELS_DIR / "uci_occupancy_features.json"


class OccupancyPredictor:
    """Simple occupancy predictor using trained UCI model."""

    def __init__(self, verbose=True):
        """Initialize predictor with trained model and scaler."""
        self.verbose = verbose

        # Load model, scaler, and features
        if not MODEL_PATH.exists() or not SCALER_PATH.exists():
            raise FileNotFoundError(
                f"Model files not found. Please run train_uci_occupancy_model.py first.\n"
                f"Expected: {MODEL_PATH}, {SCALER_PATH}"
            )

        self.model = joblib.load(MODEL_PATH)
        self.scaler = joblib.load(SCALER_PATH)

        with open(FEATURES_PATH, 'r') as f:
            self.features = json.load(f)['features']

        if self.verbose:
            logger.info(f"✓ Loaded model from {MODEL_PATH}")
            logger.info(f"✓ Loaded scaler from {SCALER_PATH}")
            logger.info(f"✓ Features: {', '.join(self.features)}")

    def predict_single(self, sensor_data):
        """
        Predict occupancy for a single sensor reading.

        Args:
            sensor_data (dict): Dictionary with keys matching feature names
                {
                    'Temperature': float,      # °C
                    'Humidity': float,         # %
                    'Light': float,            # lux
                    'CO2': float,              # ppm
                    'HumidityRatio': float     # kg_water/kg_dry_air
                }

        Returns:
            Tuple of (occupancy_prediction, confidence_probability)
            - occupancy_prediction: 0 (empty) or 1 (occupied)
            - confidence_probability: 0-1 (confidence in prediction)
        """
        # Prepare features in correct order
        X = np.array([[sensor_data[feat] for feat in self.features]])

        # Scale
        X_scaled = self.scaler.transform(X)

        # Predict
        prediction = self.model.predict(X_scaled)[0]

        # Get confidence (probability of occupancy)
        try:
            proba = self.model.predict_proba(X_scaled)[0, 1]
        except (AttributeError, TypeError):
            # Fallback for Logistic Regression
            proba = 1.0 / (1.0 + np.exp(-self.model.decision_function(X_scaled)[0]))

        return int(prediction), float(proba)

    def predict_batch(self, df):
        """
        Predict occupancy for a batch of sensor readings.

        Args:
            df (pd.DataFrame): DataFrame with feature columns

        Returns:
            np.ndarray: Array of occupancy predictions (0 or 1)
        """
        # Prepare features
        X = df[self.features].values

        # Scale
        X_scaled = self.scaler.transform(X)

        # Predict
        predictions = self.model.predict(X_scaled)

        return predictions

    def predict_batch_with_confidence(self, df):
        """
        Predict occupancy with confidence scores.

        Args:
            df (pd.DataFrame): DataFrame with feature columns

        Returns:
            Tuple of (predictions, probabilities)
        """
        X = df[self.features].values
        X_scaled = self.scaler.transform(X)

        predictions = self.model.predict(X_scaled)

        try:
            probabilities = self.model.predict_proba(X_scaled)[:, 1]
        except (AttributeError, TypeError):
            probabilities = 1.0 / (1.0 + np.exp(-self.model.decision_function(X_scaled)))

        return predictions, probabilities


def main():
    """Command-line interface for occupancy prediction."""
    parser = ArgumentParser(description="Predict room occupancy from sensor data")
    parser.add_argument(
        '--csv',
        type=str,
        help='Path to CSV file with sensor readings'
    )
    parser.add_argument(
        '--temperature',
        type=float,
        help='Room temperature (°C)'
    )
    parser.add_argument(
        '--humidity',
        type=float,
        help='Relative humidity (%)'
    )
    parser.add_argument(
        '--light',
        type=float,
        help='Light intensity (lux)'
    )
    parser.add_argument(
        '--co2',
        type=float,
        help='CO2 concentration (ppm)'
    )
    parser.add_argument(
        '--humidity-ratio',
        type=float,
        dest='humidity_ratio',
        help='Humidity ratio (kg_water/kg_dry_air)'
    )

    args = parser.parse_args()

    try:
        predictor = OccupancyPredictor()

        if args.csv:
            # Batch prediction from CSV
            df = pd.read_csv(args.csv)
            logger.info(f"Predicting on {len(df)} samples from {args.csv}")

            predictions, confidences = predictor.predict_batch_with_confidence(df)

            # Show results
            results_df = pd.DataFrame({
                'occupancy': predictions,
                'confidence': confidences
            })

            logger.info("\nPredictions:")
            logger.info(results_df.to_string())

            # Summary stats
            logger.info(f"\nSummary:")
            logger.info(f"  Predicted occupied: {(predictions == 1).sum()} ({100*(predictions==1).sum()/len(predictions):.1f}%)")
            logger.info(f"  Average confidence: {confidences.mean():.3f}")

        elif all([args.temperature is not None, args.humidity is not None,
                 args.light is not None, args.co2 is not None,
                 args.humidity_ratio is not None]):
            # Single prediction
            data = {
                'Temperature': args.temperature,
                'Humidity': args.humidity,
                'Light': args.light,
                'CO2': args.co2,
                'HumidityRatio': args.humidity_ratio
            }

            occupancy, confidence = predictor.predict_single(data)

            occupancy_str = "OCCUPIED" if occupancy == 1 else "EMPTY"

            logger.info(f"\nPrediction:")
            logger.info(f"  Room status: {occupancy_str}")
            logger.info(f"  Confidence: {confidence:.1%}")
            logger.info(f"\nInput readings:")
            for key, val in data.items():
                logger.info(f"  {key:15}: {val}")

        else:
            parser.print_help()

    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
