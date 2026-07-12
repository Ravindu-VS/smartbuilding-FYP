"""
Production-style training script for UCI Occupancy Detection Model.

This script trains and evaluates binary occupancy prediction models
using the UCI Occupancy Detection dataset. It serves as a baseline
for room occupancy classification and is designed to be extended
with simulated smart-building data for transfer learning.

Dataset: https://archive.ics.uci.edu/dataset/357/occupancy+detection
Files:
  - datatraining.txt: Training set
  - datatest.txt: First test set
  - datatest2.txt: Second test set

Author: Smart Building Team
Version: 1.0
"""

import os
import sys
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, Any

import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, roc_auc_score, roc_curve,
    classification_report, ConfusionMatrixDisplay
)

# Configure paths
PROJECT_ROOT = Path(__file__).parent
DATASET_DIR = PROJECT_ROOT / "Dataset" / "UCI" / "occupancy+detection"
MODELS_DIR = PROJECT_ROOT / "models"
METRICS_DIR = PROJECT_ROOT / "output" / "metrics"
PLOTS_DIR = PROJECT_ROOT / "output" / "plots"

# Create directories if they don't exist
MODELS_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Load all three UCI Occupancy Detection datasets.

    Returns:
        Tuple of (training_df, test_df, test2_df)

    Raises:
        FileNotFoundError: If dataset files are missing.
        ValueError: If data loading fails.
    """
    try:
        logger.info("Loading UCI Occupancy Detection datasets...")

        training_path = DATASET_DIR / "datatraining.txt"
        test_path = DATASET_DIR / "datatest.txt"
        test2_path = DATASET_DIR / "datatest2.txt"

        # Verify files exist
        for path in [training_path, test_path, test2_path]:
            if not path.exists():
                raise FileNotFoundError(f"Dataset file not found: {path}")

        # Load with pandas (skip first column which is row index)
        training_df = pd.read_csv(training_path, index_col=0)
        test_df = pd.read_csv(test_path, index_col=0)
        test2_df = pd.read_csv(test2_path, index_col=0)

        logger.info(f"Training set: {training_df.shape[0]} samples")
        logger.info(f"Test set 1: {test_df.shape[0]} samples")
        logger.info(f"Test set 2: {test2_df.shape[0]} samples")

        return training_df, test_df, test2_df

    except Exception as e:
        logger.error(f"Failed to load datasets: {e}")
        raise


def preprocess_data(
    train_df: pd.DataFrame,
    test_dfs: list[pd.DataFrame],
    feature_cols: list[str] = None,
    target_col: str = "Occupancy"
) -> Dict[str, Any]:
    """
    Preprocess datasets: parse datetime, handle missing values, and scale features.

    Args:
        train_df: Training dataframe
        test_dfs: List of test dataframes
        feature_cols: List of feature columns (if None, uses defaults)
        target_col: Name of target column

    Returns:
        Dictionary with processed data and scalers:
        {
            'X_train': scaled training features,
            'y_train': training target,
            'X_tests': list of scaled test features,
            'y_tests': list of test targets,
            'scaler': fitted StandardScaler,
            'feature_cols': feature column names
        }
    """
    try:
        logger.info("Preprocessing datasets...")

        # Default features if not provided
        if feature_cols is None:
            feature_cols = ["Temperature", "Humidity", "Light", "CO2", "HumidityRatio"]

        # Parse datetime
        for df in [train_df] + test_dfs:
            df["date"] = pd.to_datetime(df["date"])

        # Check for missing values
        logger.info(f"Missing values in training set:\n{train_df[feature_cols + [target_col]].isnull().sum()}")

        # Drop any rows with missing target values
        train_df = train_df.dropna(subset=[target_col])
        test_dfs = [df.dropna(subset=[target_col]) for df in test_dfs]

        # Extract features and targets
        X_train = train_df[feature_cols].values
        y_train = train_df[target_col].values

        X_tests = [df[feature_cols].values for df in test_dfs]
        y_tests = [df[target_col].values for df in test_dfs]

        # Scale features using training set statistics
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_tests = [scaler.transform(X_test) for X_test in X_tests]

        logger.info(f"Feature scaling complete. Features: {feature_cols}")
        logger.info(f"Target distribution (training):\n{pd.Series(y_train).value_counts().sort_index()}")

        return {
            'X_train': X_train,
            'y_train': y_train,
            'X_tests': X_tests,
            'y_tests': y_tests,
            'scaler': scaler,
            'feature_cols': feature_cols
        }

    except Exception as e:
        logger.error(f"Preprocessing failed: {e}")
        raise


def train_models(X_train: np.ndarray, y_train: np.ndarray) -> Dict[str, Any]:
    """
    Train baseline models: Logistic Regression and Random Forest.

    Args:
        X_train: Scaled training features
        y_train: Training target

    Returns:
        Dictionary of trained models:
        {
            'logistic_regression': fitted LogisticRegression,
            'random_forest': fitted RandomForestClassifier
        }
    """
    try:
        logger.info("Training models...")

        models = {}

        # Logistic Regression
        logger.info("Training Logistic Regression...")
        lr = LogisticRegression(
            max_iter=1000,
            random_state=42,
            n_jobs=-1,
            solver='lbfgs'
        )
        lr.fit(X_train, y_train)
        models['logistic_regression'] = lr
        logger.info("✓ Logistic Regression trained")

        # Random Forest
        logger.info("Training Random Forest Classifier...")
        rf = RandomForestClassifier(
            n_estimators=100,
            max_depth=15,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
        rf.fit(X_train, y_train)
        models['random_forest'] = rf
        logger.info("✓ Random Forest trained")

        return models

    except Exception as e:
        logger.error(f"Model training failed: {e}")
        raise


def evaluate_model(
    model: Any,
    X_test: np.ndarray,
    y_test: np.ndarray,
    model_name: str
) -> Dict[str, Any]:
    """
    Evaluate a single model with comprehensive metrics.

    Args:
        model: Trained model with predict() method
        X_test: Test features
        y_test: Test target
        model_name: Name of the model (for logging)

    Returns:
        Dictionary of evaluation metrics:
        {
            'accuracy': float,
            'precision': float,
            'recall': float,
            'f1': float,
            'roc_auc': float,
            'confusion_matrix': np.ndarray,
            'classification_report': str,
            'y_pred': np.ndarray,
            'y_pred_proba': np.ndarray
        }
    """
    try:
        # Make predictions
        y_pred = model.predict(X_test)
        y_pred_proba = model.predict_proba(X_test)[:, 1]

        # Calculate metrics
        metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred, zero_division=0),
            'recall': recall_score(y_test, y_pred, zero_division=0),
            'f1': f1_score(y_test, y_pred, zero_division=0),
            'roc_auc': roc_auc_score(y_test, y_pred_proba),
            'confusion_matrix': confusion_matrix(y_test, y_pred),
            'classification_report': classification_report(y_test, y_pred),
            'y_pred': y_pred,
            'y_pred_proba': y_pred_proba
        }

        logger.info(f"\n{model_name} Evaluation:")
        logger.info(f"  Accuracy:  {metrics['accuracy']:.4f}")
        logger.info(f"  Precision: {metrics['precision']:.4f}")
        logger.info(f"  Recall:    {metrics['recall']:.4f}")
        logger.info(f"  F1-Score:  {metrics['f1']:.4f}")
        logger.info(f"  ROC-AUC:   {metrics['roc_auc']:.4f}")

        return metrics

    except Exception as e:
        logger.error(f"Model evaluation failed: {e}")
        raise


def save_artifacts(
    models: Dict[str, Any],
    metrics: Dict[str, Dict[str, Any]],
    feature_cols: list[str],
    scaler: StandardScaler,
    best_model_name: str = 'random_forest'
) -> None:
    """
    Save trained models, metrics, and scalers to disk.

    Args:
        models: Dictionary of trained models
        metrics: Dictionary of evaluation results
        feature_cols: List of feature column names
        scaler: Fitted StandardScaler
        best_model_name: Name of the best model to save as primary
    """
    try:
        logger.info("Saving artifacts...")

        # Save best model and scaler
        best_model = models[best_model_name]
        model_path = MODELS_DIR / "uci_occupancy_model.pkl"
        scaler_path = MODELS_DIR / "uci_occupancy_scaler.pkl"

        joblib.dump(best_model, model_path)
        joblib.dump(scaler, scaler_path)
        logger.info(f"✓ Saved model to {model_path}")
        logger.info(f"✓ Saved scaler to {scaler_path}")

        # Save all models for comparison
        models_path = MODELS_DIR / "uci_occupancy_all_models.pkl"
        joblib.dump(models, models_path)
        logger.info(f"✓ Saved all models to {models_path}")

        # Save feature names
        features_path = MODELS_DIR / "uci_occupancy_features.json"
        with open(features_path, 'w') as f:
            json.dump({'features': feature_cols}, f, indent=2)
        logger.info(f"✓ Saved features to {features_path}")

        # Save metrics
        metrics_path = METRICS_DIR / "uci_occupancy_metrics.txt"
        with open(metrics_path, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("UCI OCCUPANCY DETECTION MODEL - EVALUATION METRICS\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")

            f.write(f"DATASET SPLIT:\n")
            f.write(f"  Training: 1 file\n")
            f.write(f"  Testing:  2 files\n\n")

            f.write(f"FEATURES USED ({len(feature_cols)}):\n")
            for feat in feature_cols:
                f.write(f"  - {feat}\n")
            f.write("\n")

            f.write(f"MODELS TRAINED:\n")
            for model_name in models.keys():
                f.write(f"  - {model_name}\n")
            f.write("\n")

            # Per-model metrics
            for model_name, model_metrics in metrics.items():
                f.write(f"\n{model_name.upper().replace('_', ' ')}:\n")
                f.write("-" * 80 + "\n")
                f.write(f"Accuracy:  {model_metrics['accuracy']:.6f}\n")
                f.write(f"Precision: {model_metrics['precision']:.6f}\n")
                f.write(f"Recall:    {model_metrics['recall']:.6f}\n")
                f.write(f"F1-Score:  {model_metrics['f1']:.6f}\n")
                f.write(f"ROC-AUC:   {model_metrics['roc_auc']:.6f}\n\n")
                f.write(f"Confusion Matrix:\n{model_metrics['confusion_matrix']}\n\n")
                f.write(f"Classification Report:\n{model_metrics['classification_report']}\n")
                f.write("=" * 80 + "\n")

        logger.info(f"✓ Saved metrics to {metrics_path}")

    except Exception as e:
        logger.error(f"Failed to save artifacts: {e}")
        raise


def plot_confusion_matrices(
    metrics: Dict[str, Dict[str, Any]],
    y_tests: list[np.ndarray]
) -> None:
    """
    Generate and save confusion matrix plots for all models.

    Args:
        metrics: Dictionary of evaluation metrics
        y_tests: List of test targets (for sizing)
    """
    try:
        logger.info("Generating confusion matrix plots...")

        n_models = len(metrics)
        fig, axes = plt.subplots(1, n_models, figsize=(6 * n_models, 5))

        if n_models == 1:
            axes = [axes]

        for idx, (model_name, model_metrics) in enumerate(metrics.items()):
            cm = model_metrics['confusion_matrix']
            disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=['No Occupancy', 'Occupancy'])
            disp.plot(ax=axes[idx], cmap='Blues', values_format='d')
            axes[idx].set_title(f"{model_name.replace('_', ' ').title()}\nConfusion Matrix")

        plt.tight_layout()
        plot_path = PLOTS_DIR / "confusion_matrices.png"
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved confusion matrices to {plot_path}")
        plt.close()

    except Exception as e:
        logger.error(f"Failed to create confusion matrix plots: {e}")


def plot_feature_importance(
    models: Dict[str, Any],
    feature_cols: list[str]
) -> None:
    """
    Generate and save feature importance plots for tree-based models.

    Args:
        models: Dictionary of trained models
        feature_cols: List of feature names
    """
    try:
        logger.info("Generating feature importance plots...")

        # Only plot for Random Forest (has feature_importances_)
        if 'random_forest' not in models:
            logger.info("Skipping feature importance plot (Random Forest not trained)")
            return

        rf_model = models['random_forest']
        importances = rf_model.feature_importances_
        indices = np.argsort(importances)[::-1]

        plt.figure(figsize=(10, 6))
        plt.title("Feature Importance - Random Forest Classifier", fontsize=14, fontweight='bold')
        plt.bar(range(len(importances)), importances[indices], align='center')
        plt.xticks(range(len(importances)), [feature_cols[i] for i in indices], rotation=45, ha='right')
        plt.ylabel("Importance", fontsize=12)
        plt.xlabel("Feature", fontsize=12)
        plt.tight_layout()

        plot_path = PLOTS_DIR / "feature_importance.png"
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved feature importance to {plot_path}")
        plt.close()

    except Exception as e:
        logger.error(f"Failed to create feature importance plot: {e}")


def plot_roc_curves(
    metrics: Dict[str, Dict[str, Any]],
    y_tests: list[np.ndarray]
) -> None:
    """
    Generate and save ROC curve plots for all models.

    Args:
        metrics: Dictionary of evaluation metrics
        y_tests: List of test targets
    """
    try:
        logger.info("Generating ROC curve plots...")

        plt.figure(figsize=(10, 8))
        colors = ['blue', 'red']

        for idx, (model_name, model_metrics) in enumerate(metrics.items()):
            # Combine all test sets for ROC curve
            all_y_test = np.concatenate(y_tests)
            all_y_pred_proba = np.concatenate(
                [model_metrics['y_pred_proba'] for _ in range(len(y_tests))]
            ) if len(y_tests) > 1 else model_metrics['y_pred_proba']

            # Only use the first dataset prediction for clarity
            fpr, tpr, _ = roc_curve(y_tests[0], model_metrics['y_pred_proba'][:len(y_tests[0])])
            roc_auc = model_metrics['roc_auc']

            plt.plot(fpr, tpr, color=colors[idx], lw=2,
                    label=f"{model_name.replace('_', ' ').title()} (AUC = {roc_auc:.3f})")

        # Plot random classifier
        plt.plot([0, 1], [0, 1], color='gray', lw=2, linestyle='--', label='Random Classifier')

        plt.xlim([0.0, 1.0])
        plt.ylim([0.0, 1.05])
        plt.xlabel('False Positive Rate', fontsize=12)
        plt.ylabel('True Positive Rate', fontsize=12)
        plt.title('ROC Curves - Occupancy Detection Models', fontsize=14, fontweight='bold')
        plt.legend(loc="lower right", fontsize=10)
        plt.grid(alpha=0.3)
        plt.tight_layout()

        plot_path = PLOTS_DIR / "roc_curves.png"
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved ROC curves to {plot_path}")
        plt.close()

    except Exception as e:
        logger.error(f"Failed to create ROC curve plot: {e}")


# ============================================================================
# EXTENSION GUIDE: Using Simulated Smart-Building Data
# ============================================================================

def extend_with_simulated_data(
    model_path: str = None,
    scaler_path: str = None,
    simulated_data_csv: str = None
) -> None:
    """
    EXTENSION SECTION: Template for fine-tuning with simulated smart-building data.

    This function demonstrates how to extend the baseline UCI model with
    simulated data from the smart building digital twin. Use this for:

    1. TRANSFER LEARNING: Load the UCI-trained model and fine-tune on simulated data
    2. DOMAIN ADAPTATION: Adjust model to specific building characteristics
    3. SCENARIO TESTING: Validate performance under different occupancy patterns

    WORKFLOW:
    ---------
    1. Generate simulated occupancy data from simulation/engine.py
       Output CSV format: date, Temperature, Humidity, Light, CO2, HumidityRatio, Occupancy

    2. Load simulated data: df_sim = pd.read_csv(simulated_data_csv)

    3. Preprocess using same scaler: X_sim = scaler.transform(df_sim[feature_cols])

    4. OPTION A - Evaluation: Test UCI model on simulated data for generalization
    5. OPTION B - Fine-tuning: Use SGDClassifier for incremental training
    6. OPTION C - Ensemble: Combine UCI predictions with simulated model outputs

    Args:
        model_path: Path to saved UCI model
        scaler_path: Path to saved scaler
        simulated_data_csv: Path to simulated smart-building data (CSV format)

    Example:
    --------
    >>> # After training this script, generate simulated data:
    >>> # from simulation/engine.py export_occupancy_data()
    >>> extend_with_simulated_data(
    ...     model_path="models/uci_occupancy_model.pkl",
    ...     scaler_path="models/uci_occupancy_scaler.pkl",
    ...     simulated_data_csv="output/simulated_occupancy.csv"
    ... )

    Future Enhancements:
    - Implement FINE_TUNING mode with SGDClassifier for online learning
    - Add ensemble voting with simulated model output
    - Track model performance on building-specific scenarios
    - Export retraining pipeline as MLOps artifact
    """
    logger.info("\n" + "="*80)
    logger.info("EXTENSION: Simulated Smart-Building Data Integration")
    logger.info("="*80)

    logger.info("""
    This is a template for extending the baseline model with simulated data.

    TO USE THIS:

    1. In simulation/engine.py, add export method:
       def export_occupancy_data(self, output_path):
           df = pd.DataFrame({
               'date': self.timestamps,
               'Temperature': self.temperatures,
               'Humidity': self.humidities,
               'Light': self.lights,
               'CO2': self.co2_levels,
               'HumidityRatio': self.humidity_ratios,
               'Occupancy': self.occupancy_counts
           })
           df.to_csv(output_path, index=False)
           logger.info(f"Exported {len(df)} simulated samples to {output_path}")

    2. Generate simulated data by running the smart building simulator

    3. Call this function with paths to model and data

    4. Suggested pipeline:
       - Evaluate UCI model on simulated data (baseline generalization test)
       - If performance degrades: fine-tune using simulated samples
       - If performance holds: model generalizes well to building physics
    """)

    if simulated_data_csv and os.path.exists(simulated_data_csv):
        logger.info(f"Simulated data found at: {simulated_data_csv}")
        logger.info("Ready for fine-tuning workflow. Implement in future phase.")
    else:
        logger.info("Simulated data not provided. Generate using smart-building simulator.")


def main():
    """Main training pipeline."""
    try:
        logger.info("="*80)
        logger.info("UCI OCCUPANCY DETECTION MODEL - TRAINING PIPELINE")
        logger.info("="*80)

        # Load data
        train_df, test_df, test2_df = load_data()

        # Preprocess
        preprocessed = preprocess_data(
            train_df, [test_df, test2_df]
        )

        # Train models
        models = train_models(
            preprocessed['X_train'],
            preprocessed['y_train']
        )

        # Evaluate models
        metrics = {}
        for model_name, model in models.items():
            # Evaluate on combined test set for comprehensive metrics
            X_test_combined = np.vstack(preprocessed['X_tests'])
            y_test_combined = np.concatenate(preprocessed['y_tests'])

            metrics[model_name] = evaluate_model(
                model, X_test_combined, y_test_combined, model_name
            )

        # Determine best model
        best_model = max(metrics.items(), key=lambda x: x[1]['f1'])[0]
        logger.info(f"\nBest model: {best_model} (F1-Score: {metrics[best_model]['f1']:.4f})")

        # Save artifacts
        save_artifacts(
            models,
            metrics,
            preprocessed['feature_cols'],
            preprocessed['scaler'],
            best_model_name=best_model
        )

        # Generate plots
        plot_confusion_matrices(metrics, preprocessed['y_tests'])
        plot_feature_importance(models, preprocessed['feature_cols'])
        plot_roc_curves(metrics, preprocessed['y_tests'])

        # Extension guide
        extend_with_simulated_data()

        logger.info("\n" + "="*80)
        logger.info("TRAINING COMPLETE")
        logger.info("="*80)
        logger.info(f"Model saved to:    {MODELS_DIR / 'uci_occupancy_model.pkl'}")
        logger.info(f"Metrics saved to:  {METRICS_DIR / 'uci_occupancy_metrics.txt'}")
        logger.info(f"Plots saved to:    {PLOTS_DIR}")

        return 0

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
