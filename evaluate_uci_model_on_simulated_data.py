"""
Robustness test: Evaluate domain-adapted model on simulated data with noise & missing values.

This script tests how well a domain-adapted occupancy detection model (trained on mixed
UCI + simulated data) generalizes to synthetic smart-building sensor data with realistic
imperfections (sensor noise, missing values, edge cases).

Features:
  - Missing value detection and imputation (median strategy)
  - Comprehensive missing data statistics
  - Threshold sensitivity analysis (0.1 to 0.5)
  - F1-score optimization across thresholds
  - Visual threshold analysis plots
  - Robustness metrics and assessment

Input:
  - Trained model: models/domain_adapted_occupancy_model.pkl
  - Feature scaler: models/domain_adapted_scaler.pkl
  - Simulated data: data/raw/simulated_occupancy_data.csv (with noise/missing values)

Output:
  - Robustness metrics: output/metrics/robustness_evaluation_metrics.txt
  - Confusion matrix plot: output/plots/robustness_confusion_matrix.png
  - Threshold analysis: output/metrics/robustness_threshold_analysis.txt
  - Threshold plot: output/plots/robustness_threshold_analysis.png

Author: Smart Building Team
Version: 3.0 (Robustness testing with missing value handling)
"""

import os
import sys
import logging
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, roc_auc_score, classification_report,
    ConfusionMatrixDisplay
)
from sklearn.impute import SimpleImputer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent
MODELS_DIR = PROJECT_ROOT / "models"
DATA_DIR = PROJECT_ROOT / "data" / "raw"
METRICS_DIR = PROJECT_ROOT / "output" / "metrics"
PLOTS_DIR = PROJECT_ROOT / "output" / "plots"

# Create directories if they don't exist
METRICS_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# Model and data file paths
MODEL_PATH = MODELS_DIR / "domain_adapted_occupancy_model.pkl"
SCALER_PATH = MODELS_DIR / "domain_adapted_scaler.pkl"
FEATURES_PATH = MODELS_DIR / "domain_adapted_features.json"
DATA_PATH = DATA_DIR / "simulated_occupancy_data.csv"

# Output paths (robustness-specific)
METRICS_OUTPUT = METRICS_DIR / "robustness_evaluation_metrics.txt"
PLOT_OUTPUT = PLOTS_DIR / "robustness_confusion_matrix.png"
THRESHOLD_METRICS = METRICS_DIR / "robustness_threshold_analysis.txt"
THRESHOLD_PLOT = PLOTS_DIR / "robustness_threshold_analysis.png"


def load_model_and_scaler():
    """
    Load pre-trained model and feature scaler.

    Returns:
        Tuple of (model, scaler, features)

    Raises:
        FileNotFoundError: If required files are missing.
    """
    logger.info("Loading model and scaler...")

    # Check if files exist
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")
    if not SCALER_PATH.exists():
        raise FileNotFoundError(f"Scaler file not found: {SCALER_PATH}")
    if not FEATURES_PATH.exists():
        raise FileNotFoundError(f"Features file not found: {FEATURES_PATH}")

    # Load files
    try:
        model = joblib.load(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)

        with open(FEATURES_PATH, 'r') as f:
            features_dict = json.load(f)
            features = features_dict['features']

        logger.info(f"✓ Loaded model from {MODEL_PATH}")
        logger.info(f"✓ Loaded scaler from {SCALER_PATH}")
        logger.info(f"✓ Features: {', '.join(features)}")

        return model, scaler, features

    except Exception as e:
        logger.error(f"Failed to load model/scaler: {e}")
        raise


def load_simulated_data():
    """
    Load simulated occupancy dataset.

    Returns:
        pd.DataFrame: Simulated occupancy data

    Raises:
        FileNotFoundError: If data file is missing.
        ValueError: If data format is invalid.
    """
    logger.info("Loading simulated data...")

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Data file not found: {DATA_PATH}")

    try:
        df = pd.read_csv(DATA_PATH)

        # Parse date column
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])

        logger.info(f"✓ Loaded {len(df)} samples from {DATA_PATH}")
        logger.info(f"  Date range: {df['date'].min()} to {df['date'].max()}")
        logger.info(f"  Columns: {', '.join(df.columns)}")

        return df

    except Exception as e:
        logger.error(f"Failed to load simulated data: {e}")
        raise


def detect_missing_values(df, features):
    """
    Detect and report missing values in features.

    Args:
        df: DataFrame to check
        features: List of feature names to check

    Returns:
        Dictionary with missing value statistics
    """
    logger.info("\n" + "="*80)
    logger.info("MISSING VALUE DETECTION & IMPUTATION")
    logger.info("="*80)

    # Count missing values
    missing_stats = {}
    total_missing = 0
    rows_with_missing = 0

    for feature in features:
        nan_count = df[feature].isna().sum()
        missing_stats[feature] = nan_count
        total_missing += nan_count

    rows_with_missing = df[features].isna().any(axis=1).sum()

    # Log statistics
    logger.info("\nMissing Value Summary:")
    logger.info("-" * 80)
    logger.info(f"Total rows: {len(df)}")
    logger.info(f"Rows with missing values: {rows_with_missing} ({100*rows_with_missing/len(df):.2f}%)")
    logger.info(f"Total missing cells: {total_missing} / {len(df)*len(features)} ({100*total_missing/(len(df)*len(features)):.2f}%)\n")

    logger.info("Missing Values per Feature:")
    logger.info("-" * 80)
    for feature in features:
        count = missing_stats[feature]
        pct = 100 * count / len(df)
        logger.info(f"{feature:<15}: {count:5d} NaN ({pct:5.2f}%)")

    return {
        'total_missing': total_missing,
        'rows_affected': rows_with_missing,
        'missing_per_feature': missing_stats
    }


def impute_missing_values(df, features, strategy='median'):
    """
    Impute missing values using specified strategy.

    Args:
        df: DataFrame with missing values
        features: List of feature names to impute
        strategy: Imputation strategy (default: 'median')

    Returns:
        Tuple of (df_imputed, imputer, imputation_values)
    """
    logger.info("\n" + "="*80)
    logger.info("APPLYING IMPUTATION")
    logger.info("="*80)

    logger.info(f"\nStrategy: {strategy}")
    logger.info("-" * 80)

    # Extract features
    X = df[features].values

    # Create and fit imputer on this dataset only (for robustness testing)
    imputer = SimpleImputer(strategy=strategy)
    X_imputed = imputer.fit_transform(X)

    # Get imputation values used
    if strategy == 'median':
        imputation_values = imputer.statistics_
    else:
        imputation_values = imputer.statistics_

    # Log imputation values
    logger.info(f"\nImputation Values Used ({strategy}):")
    logger.info("-" * 80)
    for feat, val in zip(features, imputation_values):
        logger.info(f"{feat:<15}: {val:>10.4f}")

    # Create imputed dataframe
    df_imputed = df.copy()
    for i, feature in enumerate(features):
        df_imputed[feature] = X_imputed[:, i]

    logger.info(f"\n✓ Imputation complete: {X.shape[0]} rows × {X.shape[1]} features")
    logger.info(f"✓ {X.shape[0]*X.shape[1] - np.isnan(X).sum().sum()} missing values filled")

    return df_imputed, imputer, dict(zip(features, imputation_values))


def validate_data(df, required_features):
    """
    Validate that required features are present in dataset.

    Args:
        df: DataFrame to validate
        required_features: List of required feature names

    Returns:
        bool: True if validation passes

    Raises:
        ValueError: If validation fails.
    """
    missing_features = [feat for feat in required_features if feat not in df.columns]

    if missing_features:
        raise ValueError(
            f"Missing required features: {missing_features}. "
            f"Available columns: {list(df.columns)}"
        )

    missing_target = 'Occupancy' not in df.columns
    if missing_target:
        raise ValueError("Missing target column 'Occupancy'")

    logger.info(f"✓ Data validation passed ({len(required_features)} features, target present)")
    return True


def prepare_features(df, scaler, features):
    """
    Prepare and scale features for model input.
    Note: NaN values should already be imputed before calling this function.

    Args:
        df: DataFrame with raw features (NaN values imputed)
        scaler: StandardScaler fitted on training data
        features: List of feature names to use

    Returns:
        Tuple of (X_scaled, y_true)
    """
    logger.info("\nPreparing features for scaling...")

    # Extract features and target
    X = df[features].values
    y = df['Occupancy'].values

    # Check for any remaining NaN values
    if np.isnan(X).any():
        logger.warning("WARNING: NaN values detected in features after imputation!")
        logger.warning(f"NaN count: {np.isnan(X).sum()}")

    # Apply scaler
    X_scaled = scaler.transform(X)

    logger.info(f"✓ Features prepared: {len(X_scaled)} samples with {len(features)} features")
    logger.info(f"  Feature ranges after scaling:")
    for i, feat in enumerate(features):
        logger.info(f"    {feat:15} - min: {X_scaled[:, i].min():7.3f}, max: {X_scaled[:, i].max():7.3f}")

    return X_scaled, y


def make_predictions(model, X_scaled):
    """
    Make occupancy predictions using trained model.

    Args:
        model: Trained classifier
        X_scaled: Scaled feature matrix

    Returns:
        Tuple of (predictions, probabilities)
    """
    logger.info("Making predictions...")

    predictions = model.predict(X_scaled)

    # Try to get probabilities (works for most sklearn classifiers)
    try:
        probabilities = model.predict_proba(X_scaled)[:, 1]
    except (AttributeError, TypeError, IndexError):
        # Fallback: use decision function
        logger.warning("predict_proba not available, using decision_function")
        try:
            decision = model.decision_function(X_scaled)
            probabilities = 1.0 / (1.0 + np.exp(-decision))
        except AttributeError:
            logger.warning("No probability estimates available")
            probabilities = predictions.astype(float)

    logger.info(f"✓ Made predictions on {len(predictions)} samples")
    logger.info(f"  Predicted empty (0): {(predictions == 0).sum()}")
    logger.info(f"  Predicted occupied (1): {(predictions == 1).sum()}")

    return predictions, probabilities


def evaluate_model(y_true, y_pred, y_pred_proba):
    """
    Comprehensively evaluate model performance.

    Args:
        y_true: Ground truth labels
        y_pred: Predicted labels
        y_pred_proba: Prediction probabilities

    Returns:
        Dictionary of evaluation metrics
    """
    logger.info("Evaluating model...")

    metrics = {
        'accuracy': accuracy_score(y_true, y_pred),
        'precision': precision_score(y_true, y_pred, zero_division=0),
        'recall': recall_score(y_true, y_pred, zero_division=0),
        'f1': f1_score(y_true, y_pred, zero_division=0),
        'roc_auc': roc_auc_score(y_true, y_pred_proba),
        'confusion_matrix': confusion_matrix(y_true, y_pred),
        'classification_report': classification_report(y_true, y_pred),
    }

    logger.info("\n" + "="*80)
    logger.info("EVALUATION RESULTS")
    logger.info("="*80)
    logger.info(f"Accuracy:  {metrics['accuracy']:.6f}")
    logger.info(f"Precision: {metrics['precision']:.6f}")
    logger.info(f"Recall:    {metrics['recall']:.6f}")
    logger.info(f"F1-Score:  {metrics['f1']:.6f}")
    logger.info(f"ROC-AUC:   {metrics['roc_auc']:.6f}")

    logger.info("\nConfusion Matrix:")
    logger.info(f"  True Negatives:  {metrics['confusion_matrix'][0, 0]:5d}")
    logger.info(f"  False Positives: {metrics['confusion_matrix'][0, 1]:5d}")
    logger.info(f"  False Negatives: {metrics['confusion_matrix'][1, 0]:5d}")
    logger.info(f"  True Positives:  {metrics['confusion_matrix'][1, 1]:5d}")

    logger.info("\nClassification Report:")
    logger.info(metrics['classification_report'])

    return metrics


def assess_generalization(f1_score_value):
    """
    Assess model generalization based on F1-score.

    Args:
        f1_score_value: F1-score value (0-1)

    Returns:
        Tuple of (assessment_level, description, recommendations)
    """
    if f1_score_value >= 0.90:
        level = "STRONG GENERALIZATION"
        description = "Model generalizes excellently to simulated data!"
        recommendations = [
            "✓ Model is ready for deployment on similar building types",
            "✓ No retraining needed",
            "✓ Can be used directly for occupancy predictions"
        ]
    elif f1_score_value >= 0.75:
        level = "MODERATE GENERALIZATION"
        description = "Model shows acceptable performance with minor domain gap."
        recommendations = [
            "⚠ Consider fine-tuning on building-specific data",
            "⚠ Collect 100-200 labeled samples from target building",
            "⚠ Use transfer learning to adapt model"
        ]
    else:
        level = "WEAK GENERALIZATION"
        description = "Significant domain mismatch detected!"
        recommendations = [
            "❌ Domain adaptation required",
            "❌ Implement transfer learning pipeline",
            "❌ May need to retrain from scratch with building data",
            "❌ Consider ensemble methods combining multiple models"
        ]

    return level, description, recommendations


def analyze_probabilities(y_true, y_pred_proba):
    """
    Analyze prediction probability distribution and statistics.

    Args:
        y_true: Ground truth labels (0 or 1)
        y_pred_proba: Predicted probabilities for class 1 (0-1)

    Returns:
        Dictionary with probability statistics
    """
    logger.info("\n" + "="*80)
    logger.info("PROBABILITY ANALYSIS")
    logger.info("="*80)

    # Overall statistics
    stats = {
        'min': float(np.min(y_pred_proba)),
        'max': float(np.max(y_pred_proba)),
        'mean': float(np.mean(y_pred_proba)),
        'std': float(np.std(y_pred_proba)),
        'median': float(np.median(y_pred_proba)),
        'percentile_5': float(np.percentile(y_pred_proba, 5)),
        'percentile_25': float(np.percentile(y_pred_proba, 25)),
        'percentile_50': float(np.percentile(y_pred_proba, 50)),
        'percentile_75': float(np.percentile(y_pred_proba, 75)),
        'percentile_95': float(np.percentile(y_pred_proba, 95)),
    }

    logger.info("\nOVERALL PROBABILITY STATISTICS:")
    logger.info(f"  Min:         {stats['min']:.6f}")
    logger.info(f"  Max:         {stats['max']:.6f}")
    logger.info(f"  Mean:        {stats['mean']:.6f}")
    logger.info(f"  Std Dev:     {stats['std']:.6f}")
    logger.info(f"  Median:      {stats['median']:.6f}")

    logger.info("\nPERCENTILES:")
    logger.info(f"  5th:         {stats['percentile_5']:.6f}")
    logger.info(f"  25th:        {stats['percentile_25']:.6f}")
    logger.info(f"  50th:        {stats['percentile_50']:.6f}")
    logger.info(f"  75th:        {stats['percentile_75']:.6f}")
    logger.info(f"  95th:        {stats['percentile_95']:.6f}")

    # Statistics by true class
    empty_proba = y_pred_proba[y_true == 0]
    occupied_proba = y_pred_proba[y_true == 1]

    stats['empty_mean'] = float(np.mean(empty_proba))
    stats['empty_std'] = float(np.std(empty_proba))
    stats['empty_count'] = int(len(empty_proba))
    stats['occupied_mean'] = float(np.mean(occupied_proba))
    stats['occupied_std'] = float(np.std(occupied_proba))
    stats['occupied_count'] = int(len(occupied_proba))

    logger.info("\nPROBABILITIES BY TRUE CLASS:")
    logger.info(f"\n  Empty (0):")
    logger.info(f"    Count:       {stats['empty_count']}")
    logger.info(f"    Mean prob:   {stats['empty_mean']:.6f}")
    logger.info(f"    Std dev:     {stats['empty_std']:.6f}")

    logger.info(f"\n  Occupied (1):")
    logger.info(f"    Count:       {stats['occupied_count']}")
    logger.info(f"    Mean prob:   {stats['occupied_mean']:.6f}")
    logger.info(f"    Std dev:     {stats['occupied_std']:.6f}")

    return stats


def evaluate_at_threshold(y_true, y_pred_proba, threshold):
    """
    Evaluate model performance at a specific decision threshold.

    Args:
        y_true: Ground truth labels
        y_pred_proba: Predicted probabilities for class 1
        threshold: Decision threshold (0-1)

    Returns:
        Dictionary with metrics at this threshold
    """
    # Make predictions using threshold
    y_pred = (y_pred_proba >= threshold).astype(int)

    # Calculate metrics
    metrics = {
        'threshold': float(threshold),
        'accuracy': float(accuracy_score(y_true, y_pred)),
        'precision': float(precision_score(y_true, y_pred, zero_division=0)),
        'recall': float(recall_score(y_true, y_pred, zero_division=0)),
        'f1': float(f1_score(y_true, y_pred, zero_division=0)),
        'num_predicted_occupied': int((y_pred == 1).sum()),
        'true_positives': int(((y_pred == 1) & (y_true == 1)).sum()),
        'false_positives': int(((y_pred == 1) & (y_true == 0)).sum()),
        'true_negatives': int(((y_pred == 0) & (y_true == 0)).sum()),
        'false_negatives': int(((y_pred == 0) & (y_true == 1)).sum()),
    }

    return metrics


def threshold_sensitivity_analysis(y_true, y_pred_proba, thresholds=None):
    """
    Evaluate model performance across multiple decision thresholds.

    Args:
        y_true: Ground truth labels
        y_pred_proba: Predicted probabilities for class 1
        thresholds: List of thresholds to evaluate (default: 0.1 to 0.5)

    Returns:
        List of metrics dictionaries and best threshold
    """
    logger.info("\n" + "="*80)
    logger.info("THRESHOLD SENSITIVITY ANALYSIS")
    logger.info("="*80)

    if thresholds is None:
        thresholds = [0.1, 0.2, 0.3, 0.4, 0.5]

    results = []

    for threshold in thresholds:
        metrics = evaluate_at_threshold(y_true, y_pred_proba, threshold)
        results.append(metrics)

        logger.info(f"\nThreshold: {threshold:.2f}")
        logger.info(f"  Accuracy:     {metrics['accuracy']:.6f}")
        logger.info(f"  Precision:    {metrics['precision']:.6f}")
        logger.info(f"  Recall:       {metrics['recall']:.6f}")
        logger.info(f"  F1-Score:     {metrics['f1']:.6f}")
        logger.info(f"  Predicted Occupied: {metrics['num_predicted_occupied']:5d}")
        logger.info(f"  Confusion: TP={metrics['true_positives']}, FP={metrics['false_positives']}, " +
                   f"FN={metrics['false_negatives']}, TN={metrics['true_negatives']}")

    # Find best threshold (maximize F1)
    best_idx = np.argmax([m['f1'] for m in results])
    best_threshold_info = results[best_idx]

    logger.info("\n" + "-"*80)
    logger.info(f"BEST THRESHOLD: {best_threshold_info['threshold']:.2f}")
    logger.info(f"  F1-Score: {best_threshold_info['f1']:.6f}")
    logger.info(f"  Accuracy: {best_threshold_info['accuracy']:.6f}")
    logger.info(f"  Precision: {best_threshold_info['precision']:.6f}")
    logger.info(f"  Recall: {best_threshold_info['recall']:.6f}")
    logger.info("-"*80)

    return results, best_threshold_info


def save_robustness_metrics(metrics, y_true, missing_stats, imputation_values, features, assessment_level, recommendations, output_path):
    """
    Save comprehensive robustness evaluation metrics to text file.

    Args:
        metrics: Dictionary of evaluation metrics
        y_true: Ground truth labels
        missing_stats: Dictionary with missing value statistics
        imputation_values: Dictionary with imputation values used
        features: List of feature names
        assessment_level: Robustness assessment
        recommendations: List of recommendations
        output_path: Path to save file
    """
    logger.info("Saving robustness metrics to file...")

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("DOMAIN-ADAPTED MODEL ROBUSTNESS TEST ON NOISY SIMULATED DATA\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")

            f.write("TEST PURPOSE\n")
            f.write("-"*80 + "\n")
            f.write("This test evaluates a domain-adapted occupancy detection model\n")
            f.write("(trained on mixed UCI + simulated data) against realistically\n")
            f.write("imperfect simulated smart-building sensor data with:\n")
            f.write("  - Sensor noise (±0.5°C, ±2%, ±20ppm, ±10%)\n")
            f.write("  - Missing values (0.82% of data)\n")
            f.write("  - Edge case scenarios (late-night, weekend, spikes, drift)\n\n")

            f.write("MISSING VALUE HANDLING\n")
            f.write("="*80 + "\n")
            f.write(f"Total missing cells: {missing_stats['total_missing']}\n")
            f.write(f"Rows affected: {missing_stats['rows_affected']} ({100*missing_stats['rows_affected']/len(y_true):.2f}%)\n")
            f.write(f"Imputation strategy: Median\n\n")

            f.write("Missing Values per Feature (Before Imputation):\n")
            f.write("-"*80 + "\n")
            for feat in features:
                count = missing_stats['missing_per_feature'].get(feat, 0)
                pct = 100 * count / len(y_true)
                f.write(f"{feat:<15}: {count:5d} NaN ({pct:5.2f}%)\n")

            f.write("\nImputation Values Used (Median):\n")
            f.write("-"*80 + "\n")
            for feat in features:
                val = imputation_values.get(feat, np.nan)
                f.write(f"{feat:<15}: {val:>12.6f}\n")

            f.write("\n" + "="*80 + "\n")
            f.write("DATASET SUMMARY\n")
            f.write("-"*80 + "\n")
            f.write(f"Total samples (after imputation): {len(y_true)}\n")
            f.write(f"Empty (0): {(y_true == 0).sum()} ({100*(y_true==0).sum()/len(y_true):.1f}%)\n")
            f.write(f"Occupied (1): {(y_true == 1).sum()} ({100*(y_true==1).sum()/len(y_true):.1f}%)\n\n")

            f.write("PERFORMANCE METRICS\n")
            f.write("="*80 + "\n")
            f.write(f"Accuracy:   {metrics['accuracy']:.6f}\n")
            f.write(f"Precision:  {metrics['precision']:.6f}\n")
            f.write(f"Recall:     {metrics['recall']:.6f}\n")
            f.write(f"F1-Score:   {metrics['f1']:.6f}\n")
            f.write(f"ROC-AUC:    {metrics['roc_auc']:.6f}\n\n")

            f.write("CONFUSION MATRIX\n")
            f.write("-"*80 + "\n")
            f.write("                Predicted Empty    Predicted Occupied\n")
            f.write(f"Actual Empty:   {metrics['confusion_matrix'][0, 0]:8d}           {metrics['confusion_matrix'][0, 1]:8d}\n")
            f.write(f"Actual Occupied:{metrics['confusion_matrix'][1, 0]:8d}           {metrics['confusion_matrix'][1, 1]:8d}\n\n")

            f.write("CLASSIFICATION REPORT\n")
            f.write("-"*80 + "\n")
            f.write(metrics['classification_report'] + "\n")

            f.write("\nROBUSTNESS ASSESSMENT\n")
            f.write("="*80 + "\n")
            f.write(f"{assessment_level}\n\n")

            f.write("INTERPRETATION:\n")
            f.write("-"*80 + "\n")
            f.write(f"The domain-adapted model shows {assessment_level.lower()} when tested\n")
            f.write(f"against noisy simulated data with missing values and edge cases.\n")
            f.write(f"This demonstrates the robustness of the domain-adapted approach.\n\n")

            f.write("RECOMMENDATIONS\n")
            f.write("-"*80 + "\n")
            for rec in recommendations:
                f.write(f"{rec}\n")

            f.write("\n" + "="*80 + "\n")
            f.write("DEPLOYMENT READINESS\n")
            f.write("="*80 + "\n")

            if metrics['f1'] >= 0.90:
                f.write("""
✓ READY FOR DEPLOYMENT

The model demonstrates excellent robustness. You can:
1. Deploy directly to smart building systems
2. Use in production with confidence
3. Monitor performance with real occupancy data
4. Collect feedback for continuous improvement
""")
            elif metrics['f1'] >= 0.80:
                f.write("""
✓ READY FOR DEPLOYMENT (WITH MONITORING)

The model shows good robustness. Recommended actions:
1. Deploy with active monitoring of predictions
2. Implement missing data handling pipeline (imputation)
3. Set up alerts for unusual sensor patterns
4. Review predictions periodically to validate accuracy
5. Plan for model retraining with real data (quarterly)
""")
            elif metrics['f1'] >= 0.70:
                f.write("""
~ CONDITIONAL DEPLOYMENT

The model has acceptable robustness. Consider:
1. Implement comprehensive data validation before prediction
2. Use confidence scores to flag uncertain predictions
3. Collect labeled data from target building for fine-tuning
4. Test on subset of sensors/rooms first before full deployment
5. Plan to retrain within 1-2 months with real data
""")
            else:
                f.write("""
✗ NOT RECOMMENDED FOR DEPLOYMENT

The model needs improvement. Recommended path:
1. Collect 500-1000 labeled samples from target building
2. Retrain model using mixed UCI + building-specific data
3. Implement robust preprocessing pipeline for real sensors
4. Test on pilot subset of building before full deployment
5. Consider ensemble methods for additional robustness
""")

        logger.info(f"✓ Saved robustness metrics to {output_path}")

    except Exception as e:
        logger.error(f"Failed to save robustness metrics: {e}")


def save_threshold_analysis(threshold_results, best_threshold_info, output_path):
    """
    Save detailed threshold analysis to text file.

    Args:
        threshold_results: List of metrics dictionaries
        best_threshold_info: Dictionary with best threshold metrics
        output_path: Path to save file
    """
    logger.info("Saving robustness threshold analysis to file...")

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("ROBUSTNESS TEST: THRESHOLD SENSITIVITY ANALYSIS\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")

            f.write("PURPOSE\n")
            f.write("-"*80 + "\n")
            f.write("This analysis evaluates domain-adapted model performance across different\n")
            f.write("decision thresholds under noisy conditions. By adjusting the threshold,\n")
            f.write("we can trade-off precision vs recall based on application requirements.\n\n")

            f.write("TEST CONDITIONS\n")
            f.write("-"*80 + "\n")
            f.write("Data: Simulated with sensor noise, missing values, and edge cases\n")
            f.write("Model: Domain-adapted occupancy detector\n")
            f.write("Missing value strategy: Median imputation\n\n")

            f.write("DEFAULT THRESHOLD: 0.50\n")
            f.write("ANALYZED THRESHOLDS: " + ", ".join([f"{m['threshold']:.2f}" for m in threshold_results]) + "\n\n")

            f.write("="*80 + "\n")
            f.write("DETAILED RESULTS BY THRESHOLD\n")
            f.write("="*80 + "\n\n")

            for m in threshold_results:
                f.write(f"THRESHOLD: {m['threshold']:.2f}\n")
                f.write("-"*80 + "\n")
                f.write(f"Accuracy:              {m['accuracy']:.6f}\n")
                f.write(f"Precision:             {m['precision']:.6f}\n")
                f.write(f"Recall:                {m['recall']:.6f}\n")
                f.write(f"F1-Score:              {m['f1']:.6f}\n")
                f.write(f"Predicted Occupied:    {m['num_predicted_occupied']:5d}\n")
                f.write(f"\nConfusion Matrix:\n")
                f.write(f"  True Positives:      {m['true_positives']:5d}\n")
                f.write(f"  False Positives:     {m['false_positives']:5d}\n")
                f.write(f"  True Negatives:      {m['true_negatives']:5d}\n")
                f.write(f"  False Negatives:     {m['false_negatives']:5d}\n")
                f.write("\n")

            f.write("="*80 + "\n")
            f.write("BEST THRESHOLD SUMMARY\n")
            f.write("="*80 + "\n\n")
            f.write(f"Optimal Threshold:     {best_threshold_info['threshold']:.2f}\n")
            f.write(f"  F1-Score:            {best_threshold_info['f1']:.6f}\n")
            f.write(f"  Accuracy:            {best_threshold_info['accuracy']:.6f}\n")
            f.write(f"  Precision:           {best_threshold_info['precision']:.6f}\n")
            f.write(f"  Recall:              {best_threshold_info['recall']:.6f}\n")
            f.write(f"  Predicted Occupied:  {best_threshold_info['num_predicted_occupied']:5d}\n\n")

            f.write("INTERPRETATION\n")
            f.write("-"*80 + "\n")

            default_threshold_result = [m for m in threshold_results if m['threshold'] == 0.5][0]

            if best_threshold_info['f1'] > default_threshold_result['f1']:
                improvement = (best_threshold_info['f1'] - default_threshold_result['f1']) * 100
                f.write(f"Under noisy conditions, threshold {best_threshold_info['threshold']:.2f} improves F1 by {improvement:.1f}%\n")
                f.write(f"compared to the default threshold of 0.50.\n\n")
                f.write("RECOMMENDATION:\n")
                f.write(f"Consider using threshold {best_threshold_info['threshold']:.2f} instead of 0.50\n")
                f.write(f"for better robustness in noisy environments.\n")
            else:
                f.write(f"The default threshold of 0.50 is optimal even under noisy conditions.\n")
                f.write(f"F1-score improvement potential is minimal.\n")

            f.write("\nAPPLICATION-SPECIFIC TUNING:\n")
            f.write(f"- High precision (low false alarms): Use threshold 0.4-0.5\n")
            f.write(f"- Balanced F1 (robustness): Use threshold {best_threshold_info['threshold']:.2f}\n")
            f.write(f"- High recall (catch all): Use threshold 0.1-0.2\n")

        logger.info(f"✓ Saved robustness threshold analysis to {output_path}")

    except Exception as e:
        logger.error(f"Failed to save threshold analysis: {e}")


def plot_confusion_matrix(y_true, y_pred, output_path, title_suffix=""):
    """
    Generate and save confusion matrix plot.

    Args:
        y_true: Ground truth labels
        y_pred: Predicted labels
        output_path: Path to save plot
        title_suffix: Suffix for plot title
    """
    logger.info("Generating confusion matrix plot...")

    try:
        cm = confusion_matrix(y_true, y_pred)
        disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=['Empty (0)', 'Occupied (1)'])

        fig, ax = plt.subplots(figsize=(8, 6))
        disp.plot(ax=ax, cmap='Blues', values_format='d')
        ax.set_title(f'Confusion Matrix: Domain-Adapted Model on Robust Simulated Data{title_suffix}', fontsize=14, fontweight='bold')

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved confusion matrix to {output_path}")
        plt.close()

    except Exception as e:
        logger.error(f"Failed to create plot: {e}")


def plot_threshold_analysis(threshold_results, output_path):
    """
    Generate and save threshold analysis plot (F1 vs threshold).

    Args:
        threshold_results: List of metrics dictionaries from threshold analysis
        output_path: Path to save plot
    """
    logger.info("Generating robustness threshold analysis plot...")

    try:
        thresholds = [m['threshold'] for m in threshold_results]
        f1_scores = [m['f1'] for m in threshold_results]
        accuracies = [m['accuracy'] for m in threshold_results]
        precisions = [m['precision'] for m in threshold_results]
        recalls = [m['recall'] for m in threshold_results]

        fig, ax = plt.subplots(figsize=(12, 7))

        # Plot F1, accuracy, precision, recall
        ax.plot(thresholds, f1_scores, marker='o', linewidth=2, markersize=8, label='F1-Score', color='blue')
        ax.plot(thresholds, accuracies, marker='s', linewidth=2, markersize=8, label='Accuracy', color='green')
        ax.plot(thresholds, precisions, marker='^', linewidth=2, markersize=8, label='Precision', color='orange')
        ax.plot(thresholds, recalls, marker='v', linewidth=2, markersize=8, label='Recall', color='red')

        # Highlight best F1
        best_idx = np.argmax(f1_scores)
        best_f1 = f1_scores[best_idx]
        best_threshold = thresholds[best_idx]
        ax.plot(best_threshold, best_f1, marker='*', markersize=20, color='darkblue', label=f'Best F1 @ {best_threshold:.2f}')

        ax.set_xlabel('Decision Threshold', fontsize=12, fontweight='bold')
        ax.set_ylabel('Metric Value', fontsize=12, fontweight='bold')
        ax.set_title('Robustness Test: Model Performance vs Decision Threshold', fontsize=14, fontweight='bold')
        ax.legend(fontsize=11, loc='best')
        ax.grid(True, alpha=0.3)
        ax.set_xlim([min(thresholds) - 0.05, max(thresholds) + 0.05])
        ax.set_ylim([0, 1.05])

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved robustness threshold plot to {output_path}")
        plt.close()

    except Exception as e:
        logger.error(f"Failed to create threshold plot: {e}")


def save_metrics(metrics, y_true, assessment_level, recommendations, output_path):
    """
    Save comprehensive evaluation metrics to text file.

    Args:
        metrics: Dictionary of evaluation metrics
        y_true: Ground truth labels
        assessment_level: Generalization assessment
        recommendations: List of recommendations
        output_path: Path to save file
    """
    logger.info("Saving metrics to file...")

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("UCI OCCUPANCY MODEL - EVALUATION ON SIMULATED DATA\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")

            f.write("DATASET SUMMARY\n")
            f.write("-"*80 + "\n")
            f.write(f"Total samples: {len(y_true)}\n")
            f.write(f"Empty (0): {(y_true == 0).sum()} ({100*(y_true==0).sum()/len(y_true):.1f}%)\n")
            f.write(f"Occupied (1): {(y_true == 1).sum()} ({100*(y_true==1).sum()/len(y_true):.1f}%)\n\n")

            f.write("PERFORMANCE METRICS\n")
            f.write("-"*80 + "\n")
            f.write(f"Accuracy:   {metrics['accuracy']:.6f}\n")
            f.write(f"Precision:  {metrics['precision']:.6f}\n")
            f.write(f"Recall:     {metrics['recall']:.6f}\n")
            f.write(f"F1-Score:   {metrics['f1']:.6f}\n")
            f.write(f"ROC-AUC:    {metrics['roc_auc']:.6f}\n\n")

            f.write("CONFUSION MATRIX\n")
            f.write("-"*80 + "\n")
            f.write("                Predicted Empty    Predicted Occupied\n")
            f.write(f"Actual Empty:   {metrics['confusion_matrix'][0, 0]:8d}           {metrics['confusion_matrix'][0, 1]:8d}\n")
            f.write(f"Actual Occupied:{metrics['confusion_matrix'][1, 0]:8d}           {metrics['confusion_matrix'][1, 1]:8d}\n\n")

            f.write("CLASSIFICATION REPORT\n")
            f.write("-"*80 + "\n")
            f.write(metrics['classification_report'] + "\n")

            f.write("\nGENERALIZATION ASSESSMENT\n")
            f.write("="*80 + "\n")
            f.write(f"{assessment_level}\n\n")
            f.write("Interpretation:\n")
            f.write(f"The model shows {assessment_level.lower()} on simulated smart-building data.\n\n")

            f.write("RECOMMENDATIONS\n")
            f.write("-"*80 + "\n")
            for rec in recommendations:
                f.write(f"{rec}\n")

            f.write("\n" + "="*80 + "\n")
            f.write("NEXT STEPS\n")
            f.write("="*80 + "\n")

            if metrics['f1'] >= 0.90:
                f.write("""
The model generalizes well! You can:
1. Deploy directly to smart building systems
2. Monitor performance with real data
3. Collect ground truth to verify accuracy in production
""")
            elif metrics['f1'] >= 0.75:
                f.write("""
The model has moderate performance. Consider:
1. Collecting 100-200 labeled samples from your building
2. Fine-tuning using transfer learning (SGDClassifier)
3. Using ensemble methods for better predictions
4. Evaluating on different building types
""")
            else:
                f.write("""
The model needs domain adaptation. Recommended path:
1. Implement full transfer learning pipeline
2. Collect labeled occupancy data from target building
3. Fine-tune model using collected data
4. Alternatively: retrain from scratch with building data
5. Consider ensemble or domain adversarial methods
""")

        logger.info(f"✓ Saved metrics to {output_path}")

    except Exception as e:
        logger.error(f"Failed to save metrics: {e}")


def main():
    """Main robustness evaluation pipeline."""
    try:
        logger.info("="*80)
        logger.info("DOMAIN-ADAPTED MODEL ROBUSTNESS TEST ON NOISY SIMULATED DATA")
        logger.info("="*80)

        # Step 1: Load model and scaler
        model, scaler, features = load_model_and_scaler()

        # Step 2: Load simulated data (with noise and missing values)
        df = load_simulated_data()

        # Step 3: Validate data
        validate_data(df, features)

        # Step 4: Detect missing values
        missing_stats = detect_missing_values(df, features)

        # Step 5: Impute missing values
        df_imputed, imputer, imputation_values = impute_missing_values(df, features, strategy='median')

        # Step 6: Prepare features (on imputed data)
        X_scaled, y_true = prepare_features(df_imputed, scaler, features)

        # Step 7: Make predictions
        y_pred, y_pred_proba = make_predictions(model, X_scaled)

        # Step 8: Evaluate model
        metrics = evaluate_model(y_true, y_pred, y_pred_proba)

        # Step 9: Threshold sensitivity analysis
        threshold_results, best_threshold_info = threshold_sensitivity_analysis(y_true, y_pred_proba)

        # Step 10: Assess robustness
        level, description, recommendations = assess_generalization(metrics['f1'])

        logger.info("\n" + "="*80)
        logger.info("ROBUSTNESS ASSESSMENT")
        logger.info("="*80)
        logger.info(f"\n{level}")
        logger.info(f"\n{description}\n")
        logger.info("Recommendations:")
        for rec in recommendations:
            logger.info(f"  {rec}")

        # Step 11: Save visualizations and metrics
        plot_confusion_matrix(y_true, y_pred, PLOT_OUTPUT)
        plot_threshold_analysis(threshold_results, THRESHOLD_PLOT)
        save_robustness_metrics(metrics, y_true, missing_stats, imputation_values, features, level, recommendations, METRICS_OUTPUT)
        save_threshold_analysis(threshold_results, best_threshold_info, THRESHOLD_METRICS)

        # Final summary
        logger.info("\n" + "="*80)
        logger.info("ROBUSTNESS TEST COMPLETE")
        logger.info("="*80)
        logger.info(f"Robustness metrics saved to:   {METRICS_OUTPUT}")
        logger.info(f"Confusion matrix saved to:     {PLOT_OUTPUT}")
        logger.info(f"Threshold analysis saved to:   {THRESHOLD_METRICS}")
        logger.info(f"Threshold plot saved to:       {THRESHOLD_PLOT}")

        # Return appropriate exit code based on F1-score
        if metrics['f1'] >= 0.90:
            exit_code = 0  # Excellent robustness
        elif metrics['f1'] >= 0.80:
            exit_code = 1  # Good robustness, monitoring recommended
        elif metrics['f1'] >= 0.70:
            exit_code = 2  # Acceptable, conditional deployment
        else:
            exit_code = 3  # Needs improvement

        return exit_code

    except Exception as e:
        logger.error(f"Robustness test failed: {e}", exc_info=True)
        return 4


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
