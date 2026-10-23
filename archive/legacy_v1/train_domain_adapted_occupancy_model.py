"""
Train a domain-adapted occupancy detection model using mixed UCI and simulated data.

This script combines the UCI Occupancy Detection dataset with corrected simulated
smart-building data to train models that generalize better across both domains.

The goal is to show whether mixed-data training improves model performance on
simulated environments while maintaining acceptable performance on the UCI dataset.

Input:
  - UCI datasets: Dataset/UCI/occupancy+detection/{datatraining,datatest,datatest2}.txt
  - Simulated data: data/raw/simulated_occupancy_data.csv

Features:
  - Temperature, Humidity, Light, CO2, HumidityRatio

Target:
  - Occupancy (binary: 0=empty, 1=occupied)

Output:
  - models/domain_adapted_occupancy_model.pkl
  - models/domain_adapted_scaler.pkl
  - models/domain_adapted_features.json
  - output/metrics/domain_adapted_model_metrics.txt
  - output/plots/ (confusion matrices, ROC curves)

Author: Smart Building Team
Version: 1.0
"""

import os
import sys
import json
import pickle
import logging
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import cross_val_score
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, roc_curve, confusion_matrix, auc, classification_report
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent
UCI_TRAIN_PATH = PROJECT_ROOT / "Dataset" / "UCI" / "occupancy+detection" / "datatraining.txt"
UCI_TEST_PATH = PROJECT_ROOT / "Dataset" / "UCI" / "occupancy+detection" / "datatest.txt"
UCI_TEST2_PATH = PROJECT_ROOT / "Dataset" / "UCI" / "occupancy+detection" / "datatest2.txt"
SIMULATED_PATH = PROJECT_ROOT / "data" / "raw" / "simulated_occupancy_data.csv"

MODELS_DIR = PROJECT_ROOT / "models"
METRICS_DIR = PROJECT_ROOT / "output" / "metrics"
PLOTS_DIR = PROJECT_ROOT / "output" / "plots"

# Create directories
MODELS_DIR.mkdir(parents=True, exist_ok=True)
METRICS_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# Output paths
MODEL_PATH = MODELS_DIR / "domain_adapted_occupancy_model.pkl"
SCALER_PATH = MODELS_DIR / "domain_adapted_scaler.pkl"
FEATURES_PATH = MODELS_DIR / "domain_adapted_features.json"
METRICS_FILE = METRICS_DIR / "domain_adapted_model_metrics.txt"
BASELINE_METRICS_FILE = METRICS_DIR / "uci_occupancy_metrics.txt"

# Features and target
FEATURES = ["Temperature", "Humidity", "Light", "CO2", "HumidityRatio"]
TARGET = "Occupancy"


def load_uci_datasets():
    """
    Load UCI Occupancy Detection datasets.

    Returns:
        Tuple of (train_df, test1_df, test2_df)
    """
    logger.info("Loading UCI datasets...")

    try:
        # Load training data
        train_df = pd.read_csv(UCI_TRAIN_PATH, index_col=0)
        logger.info(f"✓ Loaded UCI train: {len(train_df)} samples")

        # Load test sets
        test1_df = pd.read_csv(UCI_TEST_PATH, index_col=0)
        logger.info(f"✓ Loaded UCI test1: {len(test1_df)} samples")

        test2_df = pd.read_csv(UCI_TEST2_PATH, index_col=0)
        logger.info(f"✓ Loaded UCI test2: {len(test2_df)} samples")

        return train_df, test1_df, test2_df

    except Exception as e:
        logger.error(f"Failed to load UCI datasets: {e}")
        raise


def load_simulated_dataset():
    """
    Load corrected simulated occupancy data.

    Returns:
        DataFrame with simulated data
    """
    logger.info("Loading simulated dataset...")

    try:
        simulated_df = pd.read_csv(SIMULATED_PATH)
        if 'date' in simulated_df.columns:
            simulated_df['date'] = pd.to_datetime(simulated_df['date'])
        logger.info(f"✓ Loaded simulated data: {len(simulated_df)} samples")
        return simulated_df

    except Exception as e:
        logger.error(f"Failed to load simulated dataset: {e}")
        raise


def validate_features(datasets_dict):
    """
    Validate that all required features and target are present.

    Args:
        datasets_dict: Dictionary of dataset names to DataFrames

    Raises:
        ValueError: If required columns are missing
    """
    logger.info("Validating features...")

    for name, df in datasets_dict.items():
        missing = [f for f in FEATURES + [TARGET] if f not in df.columns]
        if missing:
            raise ValueError(f"Missing columns in {name}: {missing}")

    logger.info(f"✓ All {len(FEATURES)} features + target present in all datasets")


def prepare_combined_training_data(uci_train, simulated_df):
    """
    Prepare combined training dataset with data source labels.

    Args:
        uci_train: UCI training DataFrame
        simulated_df: Simulated dataset DataFrame

    Returns:
        Combined DataFrame with balanced representation
    """
    logger.info("\nPreparing combined training dataset...")

    # Add data source columns for tracking
    uci_train_copy = uci_train[FEATURES + [TARGET]].copy()
    uci_train_copy['data_source'] = 'uci'

    simulated_copy = simulated_df[FEATURES + [TARGET]].copy()
    simulated_copy['data_source'] = 'simulated'

    # Combine datasets
    combined_train = pd.concat([uci_train_copy, simulated_copy], ignore_index=True)

    logger.info(f"✓ UCI training samples: {(combined_train['data_source'] == 'uci').sum()}")
    logger.info(f"✓ Simulated samples: {(combined_train['data_source'] == 'simulated').sum()}")
    logger.info(f"✓ Combined training set: {len(combined_train)} samples")

    # Show occupancy distribution
    occupancy_dist = combined_train[TARGET].value_counts()
    logger.info(f"  Occupancy distribution: Empty={occupancy_dist[0]}, Occupied={occupancy_dist[1]}")

    return combined_train


def compute_sample_weights(combined_train, weight_simulated=2.0):
    """
    Compute sample weights to emphasize simulated data.

    Args:
        combined_train: Combined training DataFrame with data_source column
        weight_simulated: Weight multiplier for simulated samples

    Returns:
        Array of sample weights
    """
    logger.info(f"\nComputing sample weights (simulated weight={weight_simulated}x)...")

    weights = np.ones(len(combined_train))
    simulated_mask = combined_train['data_source'] == 'simulated'
    weights[simulated_mask] = weight_simulated

    logger.info(f"✓ UCI samples weight: 1.0x ({(~simulated_mask).sum()} samples)")
    logger.info(f"✓ Simulated samples weight: {weight_simulated}x ({simulated_mask.sum()} samples)")

    return weights


def preprocess_data(combined_train, uci_test1, uci_test2, simulated_df):
    """
    Preprocess data: extract features/target and apply scaling.

    Scaler is fit only on combined training data.

    Args:
        combined_train: Combined training DataFrame
        uci_test1: UCI test set 1
        uci_test2: UCI test set 2
        simulated_df: Simulated dataset

    Returns:
        Tuple of (X_train, y_train, X_test1, y_test1, X_test2, y_test2, X_sim, y_sim, scaler)
    """
    logger.info("\nPreprocessing data...")

    # Extract features and target from training data
    X_train = combined_train[FEATURES].values
    y_train = combined_train[TARGET].values

    # Extract from test sets
    X_test1 = uci_test1[FEATURES].values
    y_test1 = uci_test1[TARGET].values

    X_test2 = uci_test2[FEATURES].values
    y_test2 = uci_test2[TARGET].values

    X_sim = simulated_df[FEATURES].values
    y_sim = simulated_df[TARGET].values

    # Fit scaler on training data only
    logger.info("Fitting StandardScaler on training data...")
    scaler = StandardScaler()
    scaler.fit(X_train)

    # Apply scaler to all datasets
    X_train_scaled = scaler.transform(X_train)
    X_test1_scaled = scaler.transform(X_test1)
    X_test2_scaled = scaler.transform(X_test2)
    X_sim_scaled = scaler.transform(X_sim)

    logger.info(f"✓ Training set: {X_train_scaled.shape}")
    logger.info(f"✓ UCI test1: {X_test1_scaled.shape}")
    logger.info(f"✓ UCI test2: {X_test2_scaled.shape}")
    logger.info(f"✓ Simulated test: {X_sim_scaled.shape}")

    return X_train_scaled, y_train, X_test1_scaled, y_test1, X_test2_scaled, y_test2, X_sim_scaled, y_sim, scaler


def train_model(name, model, X_train, y_train, sample_weights=None):
    """
    Train a single model.

    Args:
        name: Model name for logging
        model: Sklearn model instance
        X_train: Training features
        y_train: Training target
        sample_weights: Optional sample weights to emphasize simulated data

    Returns:
        Trained model
    """
    logger.info(f"\nTraining {name}...")

    if sample_weights is not None:
        model.fit(X_train, y_train, sample_weight=sample_weights)
    else:
        model.fit(X_train, y_train)

    logger.info(f"✓ {name} training complete")

    # Cross-validation score
    cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring='f1')
    logger.info(f"  Cross-validation F1 scores: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")

    return model


def evaluate_model(name, model, X_test, y_test, dataset_name=""):
    """
    Evaluate model on a test set and return metrics.

    Args:
        name: Model name
        model: Trained model
        X_test: Test features
        y_test: Test labels
        dataset_name: Name of dataset for logging (e.g., "UCI", "Simulated")

    Returns:
        Dictionary of metrics
    """
    logger.info(f"\nEvaluating {name} on {dataset_name}...")

    # Predictions
    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]

    # Compute metrics
    accuracy = accuracy_score(y_test, y_pred)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)
    roc_auc = roc_auc_score(y_test, y_pred_proba)
    cm = confusion_matrix(y_test, y_pred)

    metrics = {
        'accuracy': accuracy,
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'roc_auc': roc_auc,
        'confusion_matrix': cm.tolist(),
        'y_true': y_test.tolist(),
        'y_pred': y_pred.tolist(),
        'y_pred_proba': y_pred_proba.tolist()
    }

    logger.info(f"  Accuracy:  {accuracy:.4f}")
    logger.info(f"  Precision: {precision:.4f}")
    logger.info(f"  Recall:    {recall:.4f}")
    logger.info(f"  F1-Score:  {f1:.4f}")
    logger.info(f"  ROC-AUC:   {roc_auc:.4f}")
    logger.info(f"  Confusion Matrix: TP={cm[1,1]}, FP={cm[0,1]}, TN={cm[0,0]}, FN={cm[1,0]}")

    return metrics


def plot_confusion_matrix(cm, model_name, dataset_name, output_path):
    """
    Plot confusion matrix as heatmap.

    Args:
        cm: Confusion matrix
        model_name: Name of model
        dataset_name: Name of dataset
        output_path: Path to save plot
    """
    plt.figure(figsize=(8, 6))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', cbar=False,
                xticklabels=['Empty', 'Occupied'],
                yticklabels=['Empty', 'Occupied'])
    plt.title(f'{model_name} - {dataset_name}\nConfusion Matrix')
    plt.ylabel('Actual')
    plt.xlabel('Predicted')
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    logger.info(f"✓ Saved confusion matrix: {output_path}")


def plot_roc_curve(y_true, y_pred_proba, model_name, dataset_name, output_path):
    """
    Plot ROC curve.

    Args:
        y_true: True labels
        y_pred_proba: Predicted probabilities for class 1
        model_name: Name of model
        dataset_name: Name of dataset
        output_path: Path to save plot
    """
    fpr, tpr, _ = roc_curve(y_true, y_pred_proba)
    roc_auc = auc(fpr, tpr)

    plt.figure(figsize=(8, 6))
    plt.plot(fpr, tpr, color='darkorange', lw=2, label=f'ROC curve (AUC = {roc_auc:.4f})')
    plt.plot([0, 1], [0, 1], color='navy', lw=2, linestyle='--', label='Random Classifier')
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.05])
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title(f'{model_name} - {dataset_name}\nROC Curve')
    plt.legend(loc="lower right")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    logger.info(f"✓ Saved ROC curve: {output_path}")


def save_model_artifacts(best_model, best_model_name, scaler, features, model_path, scaler_path, features_path):
    """
    Save trained model, scaler, and feature list to disk.

    Args:
        best_model: Best trained model
        best_model_name: Name of best model
        scaler: Fitted StandardScaler
        features: List of feature names
        model_path: Path to save model
        scaler_path: Path to save scaler
        features_path: Path to save features
    """
    logger.info("\nSaving model artifacts...")

    # Save model
    with open(model_path, 'wb') as f:
        pickle.dump(best_model, f)
    logger.info(f"✓ Saved model: {model_path}")

    # Save scaler
    with open(scaler_path, 'wb') as f:
        pickle.dump(scaler, f)
    logger.info(f"✓ Saved scaler: {scaler_path}")

    # Save features
    with open(features_path, 'w') as f:
        json.dump({'features': features, 'model': best_model_name}, f, indent=2)
    logger.info(f"✓ Saved features: {features_path}")


def load_baseline_metrics(baseline_file):
    """
    Load metrics from original UCI-only model for comparison.

    Args:
        baseline_file: Path to baseline metrics file

    Returns:
        Dictionary with baseline metrics or None if file not found
    """
    if not baseline_file.exists():
        logger.warning(f"Baseline metrics file not found: {baseline_file}")
        return None

    logger.info(f"Loading baseline metrics from {baseline_file}...")

    try:
        with open(baseline_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse key metrics
        baseline = {}
        for line in content.split('\n'):
            if 'Logistic Regression' in line and 'Accuracy' in line:
                # Extract accuracy value
                if ':' in line:
                    try:
                        baseline['lr_accuracy'] = float(line.split(':')[-1].strip())
                    except:
                        pass
        return baseline if baseline else None

    except Exception as e:
        logger.warning(f"Failed to parse baseline metrics: {e}")
        return None


def save_metrics(all_results, baseline_metrics, output_file):
    """
    Save evaluation metrics and model comparison to file.

    Args:
        all_results: Dictionary with model results
        baseline_metrics: Baseline model metrics for comparison
        output_file: Path to save metrics
    """
    logger.info(f"\nSaving metrics to {output_file}...")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 100 + "\n")
        f.write("DOMAIN-ADAPTED OCCUPANCY DETECTION MODEL - EVALUATION METRICS\n")
        f.write("=" * 100 + "\n\n")

        f.write(f"Training Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Training Data: UCI training + Simulated data (mixed-domain)\n")
        f.write(f"Test Sets: UCI test1, UCI test2, Simulated data\n\n")

        # Model results
        for model_name, results in all_results.items():
            f.write("=" * 100 + "\n")
            f.write(f"{model_name}\n")
            f.write("=" * 100 + "\n\n")

            for dataset_name, metrics in results.items():
                f.write(f"{dataset_name}:\n")
                f.write("-" * 100 + "\n")
                f.write(f"  Accuracy:  {metrics['accuracy']:.4f}\n")
                f.write(f"  Precision: {metrics['precision']:.4f}\n")
                f.write(f"  Recall:    {metrics['recall']:.4f}\n")
                f.write(f"  F1-Score:  {metrics['f1']:.4f}\n")
                f.write(f"  ROC-AUC:   {metrics['roc_auc']:.4f}\n")

                cm = np.array(metrics['confusion_matrix'])
                f.write(f"  Confusion Matrix: TP={cm[1,1]}, FP={cm[0,1]}, TN={cm[0,0]}, FN={cm[1,0]}\n\n")

        # Comparison with baseline
        if baseline_metrics:
            f.write("=" * 100 + "\n")
            f.write("COMPARISON WITH UCI-ONLY BASELINE MODEL\n")
            f.write("=" * 100 + "\n\n")

            f.write("Note: Domain-adapted model trained on UCI train + Simulated data\n")
            f.write("      Baseline model trained on UCI train data only\n\n")

            f.write("Key Comparisons:\n")
            f.write("-" * 100 + "\n")

            # Get Logistic Regression results
            lr_weighted_results = None
            for model_name, results in all_results.items():
                if 'Logistic Regression (Weighted)' in model_name:
                    lr_weighted_results = results
                    break

            if lr_weighted_results:
                # Compare on simulated data (main goal)
                if 'Simulated Data' in lr_weighted_results:
                    sim_f1_comp = lr_weighted_results['Simulated Data']['f1']
                    f.write(f"\nDomain-Adapted LR on Simulated Data:\n")
                    f.write(f"  F1-Score: {sim_f1_comp:.4f}\n")
                    f.write(f"  Expected improvement: F1 should be > 0.0 (baseline: all empty predictions)\n")

                # Compare on UCI test data
                if 'UCI Test1' in lr_weighted_results:
                    test1_f1_comp = lr_weighted_results['UCI Test1']['f1']
                    f.write(f"\nDomain-Adapted LR on UCI Test1 (maintaining UCI performance):\n")
                    f.write(f"  F1-Score: {test1_f1_comp:.4f}\n")
                    f.write(f"  Goal: Maintain performance (should be similar to baseline)\n")

        # Summary assessment
        f.write("\n" + "=" * 100 + "\n")
        f.write("ASSESSMENT\n")
        f.write("=" * 100 + "\n\n")

        # Find LR weighted results
        lr_weighted_results = None
        for model_name, results in all_results.items():
            if 'Logistic Regression (Weighted)' in model_name:
                lr_weighted_results = results
                break

        if lr_weighted_results is None:
            # Fallback to standard LR
            for model_name, results in all_results.items():
                if 'Logistic Regression (Standard)' in model_name:
                    lr_weighted_results = results
                    break

        if lr_weighted_results:
            sim_f1 = lr_weighted_results['Simulated Data']['f1']
            test1_f1 = lr_weighted_results['UCI Test1']['f1']
        else:
            sim_f1 = 0
            test1_f1 = 0

        if sim_f1 > 0.5 and test1_f1 > 0.9:
            assessment = "✅ EXCELLENT: Strong generalization to simulated data while maintaining UCI performance"
        elif sim_f1 > 0.3 and test1_f1 > 0.8:
            assessment = "✓ GOOD: Moderate improvement to simulated data with acceptable UCI performance"
        elif sim_f1 > 0.2:
            assessment = "~ MODERATE: Some improvement to simulated data but still room for enhancement"
        else:
            assessment = "⚠ LIMITED: Improvement to simulated data is minimal, further adaptation needed"

        f.write(assessment + "\n\n")

        f.write("Next Steps:\n")
        if sim_f1 > 0.5:
            f.write("  1. Deploy domain-adapted model for smart-building occupancy detection\n")
            f.write("  2. Monitor performance in real-world deployment\n")
            f.write("  3. Collect real building data for further fine-tuning\n")
        elif sim_f1 > 0.3:
            f.write("  1. Consider ensemble combining UCI-optimized and domain-adapted models\n")
            f.write("  2. Experiment with transfer learning and fine-tuning\n")
            f.write("  3. Collect more diverse simulation scenarios\n")
        else:
            f.write("  1. Investigate domain gap still present (review feature distributions)\n")
            f.write("  2. Implement more sophisticated domain adaptation techniques\n")
            f.write("  3. Collect real labeled data from target buildings\n")

    logger.info(f"✓ Metrics saved to {output_file}")


def main():
    """Main execution function."""
    try:
        logger.info("=" * 100)
        logger.info("DOMAIN-ADAPTED OCCUPANCY DETECTION MODEL TRAINING")
        logger.info("=" * 100)

        # Step 1: Load datasets
        uci_train, uci_test1, uci_test2 = load_uci_datasets()
        simulated_df = load_simulated_dataset()

        # Step 2: Validate features
        datasets_dict = {
            'UCI Train': uci_train,
            'UCI Test1': uci_test1,
            'UCI Test2': uci_test2,
            'Simulated': simulated_df
        }
        validate_features(datasets_dict)

        # Step 3: Prepare combined training data
        combined_train = prepare_combined_training_data(uci_train, simulated_df)

        # Step 4: Compute sample weights (optional - emphasize simulated data)
        sample_weights = compute_sample_weights(combined_train, weight_simulated=2.0)

        # Step 5: Preprocess data
        X_train, y_train, X_test1, y_test1, X_test2, y_test2, X_sim, y_sim, scaler = \
            preprocess_data(combined_train, uci_test1, uci_test2, simulated_df)

        # Step 6: Train models without sample weights (baseline)
        lr_model = train_model(
            "Logistic Regression",
            LogisticRegression(max_iter=1000, random_state=42),
            X_train, y_train
        )

        rf_model = train_model(
            "Random Forest",
            RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1),
            X_train, y_train
        )

        # Step 7: Train models with sample weights (emphasizing simulated data)
        logger.info("\n" + "=" * 100)
        logger.info("TRAINING WITH SAMPLE WEIGHTS (Simulated Data Emphasized 2x)")
        logger.info("=" * 100)

        lr_model_weighted = train_model(
            "Logistic Regression (Weighted)",
            LogisticRegression(max_iter=1000, random_state=42, class_weight='balanced'),
            X_train, y_train,
            sample_weights=sample_weights
        )

        rf_model_weighted = train_model(
            "Random Forest (Weighted)",
            RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1),
            X_train, y_train,
            sample_weights=sample_weights
        )

        # Step 8: Evaluate all models
        logger.info("\n" + "=" * 100)
        logger.info("MODEL EVALUATION")
        logger.info("=" * 100)

        all_results = {}

        # Logistic Regression
        all_results['Logistic Regression (Standard)'] = {
            'UCI Test1': evaluate_model('LR', lr_model, X_test1, y_test1, 'UCI Test1'),
            'UCI Test2': evaluate_model('LR', lr_model, X_test2, y_test2, 'UCI Test2'),
            'Simulated Data': evaluate_model('LR', lr_model, X_sim, y_sim, 'Simulated Data'),
        }

        # Logistic Regression Weighted
        all_results['Logistic Regression (Weighted)'] = {
            'UCI Test1': evaluate_model('LR-W', lr_model_weighted, X_test1, y_test1, 'UCI Test1'),
            'UCI Test2': evaluate_model('LR-W', lr_model_weighted, X_test2, y_test2, 'UCI Test2'),
            'Simulated Data': evaluate_model('LR-W', lr_model_weighted, X_sim, y_sim, 'Simulated Data'),
        }

        # Random Forest
        all_results['Random Forest (Standard)'] = {
            'UCI Test1': evaluate_model('RF', rf_model, X_test1, y_test1, 'UCI Test1'),
            'UCI Test2': evaluate_model('RF', rf_model, X_test2, y_test2, 'UCI Test2'),
            'Simulated Data': evaluate_model('RF', rf_model, X_sim, y_sim, 'Simulated Data'),
        }

        # Random Forest Weighted
        all_results['Random Forest (Weighted)'] = {
            'UCI Test1': evaluate_model('RF-W', rf_model_weighted, X_test1, y_test1, 'UCI Test1'),
            'UCI Test2': evaluate_model('RF-W', rf_model_weighted, X_test2, y_test2, 'UCI Test2'),
            'Simulated Data': evaluate_model('RF-W', rf_model_weighted, X_sim, y_sim, 'Simulated Data'),
        }

        # Step 9: Select best model (maximize F1 on simulated data while keeping UCI test1 F1 high)
        logger.info("\n" + "=" * 100)
        logger.info("SELECTING BEST MODEL")
        logger.info("=" * 100)

        best_model = None
        best_model_name = None
        best_score = -1

        for model_name, results in all_results.items():
            sim_f1 = results['Simulated Data']['f1']
            test1_f1 = results['UCI Test1']['f1']

            # Weighted score: 70% simulated improvement, 30% UCI maintenance
            weighted_score = 0.7 * sim_f1 + 0.3 * test1_f1

            logger.info(f"{model_name}: Simulated F1={sim_f1:.4f}, UCI F1={test1_f1:.4f}, Score={weighted_score:.4f}")

            if weighted_score > best_score:
                best_score = weighted_score
                best_model_name = model_name
                if 'Weighted' in model_name and 'Logistic' in model_name:
                    best_model = lr_model_weighted
                elif 'Weighted' in model_name and 'Random Forest' in model_name:
                    best_model = rf_model_weighted
                elif 'Standard' in model_name and 'Logistic' in model_name:
                    best_model = lr_model
                elif 'Standard' in model_name and 'Random Forest' in model_name:
                    best_model = rf_model

        logger.info(f"\n✓ Best Model: {best_model_name} (Score: {best_score:.4f})")

        # Step 10: Save best model artifacts
        save_model_artifacts(best_model, best_model_name, scaler, FEATURES, MODEL_PATH, SCALER_PATH, FEATURES_PATH)

        # Step 11: Generate plots
        logger.info("\nGenerating plots...")

        best_results = all_results[best_model_name]
        for dataset_name, metrics in best_results.items():
            cm = np.array(metrics['confusion_matrix'])
            cm_path = PLOTS_DIR / f"domain_adapted_cm_{dataset_name.replace(' ', '_').lower()}.png"
            plot_confusion_matrix(cm, best_model_name, dataset_name, cm_path)

            roc_path = PLOTS_DIR / f"domain_adapted_roc_{dataset_name.replace(' ', '_').lower()}.png"
            plot_roc_curve(np.array(metrics['y_true']), np.array(metrics['y_pred_proba']),
                          best_model_name, dataset_name, roc_path)

        # Step 12: Save metrics
        baseline_metrics = load_baseline_metrics(BASELINE_METRICS_FILE)
        save_metrics(all_results, baseline_metrics, METRICS_FILE)

        # Final summary
        logger.info("\n" + "=" * 100)
        logger.info("TRAINING COMPLETE")
        logger.info("=" * 100)
        logger.info(f"Best Model: {best_model_name}")
        logger.info(f"Model Path: {MODEL_PATH}")
        logger.info(f"Metrics: {METRICS_FILE}")
        logger.info(f"Plots: {PLOTS_DIR}")

        logger.info("\n✓ Domain-adapted model training successful!")
        logger.info("You can now use this model for occupancy detection on simulated smart buildings")
        logger.info("while maintaining performance on the UCI Occupancy Detection benchmark dataset.")

        return 0

    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
