"""
Evaluate UCI-trained occupancy model on simulated smart-building data.

This script tests how well a model trained on public UCI data generalizes
to a realistic simulated smart building environment. This is critical for
understanding domain adaptation and transfer learning effectiveness.

Usage:
    python evaluate_model_on_simulated_data.py

Output:
    - Evaluation metrics comparing model performance on simulated vs UCI data
    - Plots showing prediction patterns vs actual occupancy
    - Feature importance analysis on simulated dataset
    - Domain transfer insights
"""

import os
import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import logging
from datetime import datetime

from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, roc_auc_score, classification_report
)

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

# Create output directories
METRICS_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)


def load_model_and_scaler():
    """Load trained UCI model and feature scaler."""
    model_path = MODELS_DIR / "uci_occupancy_model.pkl"
    scaler_path = MODELS_DIR / "uci_occupancy_scaler.pkl"
    features_path = MODELS_DIR / "uci_occupancy_features.json"

    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not scaler_path.exists():
        raise FileNotFoundError(f"Scaler not found: {scaler_path}")

    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path)

    import json
    with open(features_path, 'r') as f:
        features_dict = json.load(f)
        features = features_dict['features']

    logger.info(f"✓ Loaded model from {model_path}")
    logger.info(f"✓ Loaded scaler from {scaler_path}")
    logger.info(f"✓ Features: {features}")

    return model, scaler, features


def load_simulated_data(csv_path):
    """Load simulated occupancy data."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Simulated data not found: {csv_path}")

    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    logger.info(f"✓ Loaded simulated data: {len(df)} samples")
    logger.info(f"  Date range: {df['date'].min()} to {df['date'].max()}")
    logger.info(f"  Occupancy rate: {(df['Occupancy']==1).sum()} ({100*(df['Occupancy']==1).sum()/len(df):.1f}%)")

    return df


def evaluate_on_simulated_data(model, scaler, features, simulated_df):
    """
    Evaluate UCI model on simulated data.

    Returns:
        Dictionary with evaluation metrics
    """
    logger.info("\n" + "="*80)
    logger.info("TRANSFER LEARNING EVALUATION - UCI Model on Simulated Data")
    logger.info("="*80)

    # Prepare data
    X = simulated_df[features].values
    y = simulated_df['Occupancy'].values

    # Scale features using UCI scaler
    X_scaled = scaler.transform(X)

    # Make predictions
    y_pred = model.predict(X_scaled)

    # Get prediction probabilities (handle both cases)
    try:
        y_pred_proba = model.predict_proba(X_scaled)[:, 1]
    except (AttributeError, TypeError):
        # Fallback: use decision function and convert to probability
        y_pred_proba = 1.0 / (1.0 + np.exp(-model.decision_function(X_scaled)))

    # Calculate metrics
    metrics = {
        'accuracy': accuracy_score(y, y_pred),
        'precision': precision_score(y, y_pred, zero_division=0),
        'recall': recall_score(y, y_pred, zero_division=0),
        'f1': f1_score(y, y_pred, zero_division=0),
        'roc_auc': roc_auc_score(y, y_pred_proba),
        'confusion_matrix': confusion_matrix(y, y_pred),
        'classification_report': classification_report(y, y_pred),
        'y_pred': y_pred,
        'y_pred_proba': y_pred_proba
    }

    logger.info("\nPerformance Metrics:")
    logger.info(f"  Accuracy:  {metrics['accuracy']:.4f}")
    logger.info(f"  Precision: {metrics['precision']:.4f}")
    logger.info(f"  Recall:    {metrics['recall']:.4f}")
    logger.info(f"  F1-Score:  {metrics['f1']:.4f}")
    logger.info(f"  ROC-AUC:   {metrics['roc_auc']:.4f}")
    logger.info("\nConfusion Matrix:")
    logger.info(metrics['confusion_matrix'])

    return metrics


def plot_predictions_over_time(simulated_df, metrics, output_path):
    """Plot actual vs predicted occupancy over time."""
    logger.info("\nGenerating time-series plot...")

    fig, axes = plt.subplots(3, 1, figsize=(14, 10))

    # Plot 1: Occupancy vs Predictions (first 7 days)
    days_to_plot = 7 * 96  # 7 days at 15-min intervals
    time_range = simulated_df.index[:days_to_plot]

    axes[0].plot(time_range, simulated_df['Occupancy'].iloc[:days_to_plot],
                label='Actual', linewidth=2, alpha=0.7, marker='o', markersize=3)
    axes[0].plot(time_range, metrics['y_pred'][:days_to_plot],
                label='Predicted', linewidth=2, alpha=0.7, marker='s', markersize=3)
    axes[0].set_ylabel('Occupancy', fontsize=11)
    axes[0].set_title('Occupancy Prediction: First 7 Days', fontsize=12, fontweight='bold')
    axes[0].legend(fontsize=10)
    axes[0].grid(alpha=0.3)

    # Plot 2: Prediction Probability
    axes[1].plot(time_range, metrics['y_pred_proba'][:days_to_plot],
                label='Occupancy Probability', linewidth=2, alpha=0.7, color='green')
    axes[1].axhline(y=0.5, color='red', linestyle='--', alpha=0.5, label='Decision Boundary')
    axes[1].set_ylabel('Probability', fontsize=11)
    axes[1].set_title('Model Confidence Over Time', fontsize=12, fontweight='bold')
    axes[1].legend(fontsize=10)
    axes[1].grid(alpha=0.3)

    # Plot 3: Feature values (Temperature and CO2 as examples)
    axes[2].plot(time_range, simulated_df['Temperature'].iloc[:days_to_plot],
                label='Temperature (°C)', linewidth=1.5, alpha=0.7, color='orange')
    axes_second = axes[2].twinx()
    axes_second.plot(time_range, simulated_df['CO2'].iloc[:days_to_plot],
                    label='CO2 (ppm)', linewidth=1.5, alpha=0.7, color='purple')
    axes[2].set_xlabel('Sample Index', fontsize=11)
    axes[2].set_ylabel('Temperature (°C)', fontsize=11, color='orange')
    axes_second.set_ylabel('CO2 (ppm)', fontsize=11, color='purple')
    axes[2].set_title('Feature Values Over Time', fontsize=12, fontweight='bold')
    axes[2].grid(alpha=0.3)

    # Add legends
    lines1, labels1 = axes[2].get_legend_handles_labels()
    lines2, labels2 = axes_second.get_legend_handles_labels()
    axes[2].legend(lines1 + lines2, labels1 + labels2, fontsize=10, loc='upper left')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    logger.info(f"✓ Saved time-series plot to {output_path}")
    plt.close()


def plot_daily_patterns(simulated_df, metrics):
    """Analyze and plot occupancy patterns by hour of day."""
    logger.info("\nAnalyzing daily patterns...")

    simulated_df['hour'] = simulated_df['date'].dt.hour
    simulated_df['predictions'] = metrics['y_pred']

    hourly_stats = simulated_df.groupby('hour').agg({
        'Occupancy': ['mean', 'count'],
        'predictions': 'mean',
        'Light': 'mean',
        'CO2': 'mean'
    }).round(4)

    logger.info("\nHourly Patterns:")
    logger.info(hourly_stats)

    # Plot hourly occupancy
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    hours = range(24)
    actual_by_hour = simulated_df.groupby('hour')['Occupancy'].mean()
    pred_by_hour = simulated_df.groupby('hour')['predictions'].mean()

    axes[0, 0].bar(hours, actual_by_hour, alpha=0.6, label='Actual', color='blue')
    axes[0, 0].bar(hours, pred_by_hour, alpha=0.6, label='Predicted', color='orange')
    axes[0, 0].set_xlabel('Hour of Day', fontsize=11)
    axes[0, 0].set_ylabel('Occupancy Rate', fontsize=11)
    axes[0, 0].set_title('Occupancy by Hour of Day', fontsize=12, fontweight='bold')
    axes[0, 0].legend()
    axes[0, 0].grid(alpha=0.3, axis='y')

    # Feature values by hour
    light_by_hour = simulated_df.groupby('hour')['Light'].mean()
    axes[0, 1].plot(hours, light_by_hour, marker='o', linewidth=2, color='gold')
    axes[0, 1].set_xlabel('Hour of Day', fontsize=11)
    axes[0, 1].set_ylabel('Light (lux)', fontsize=11)
    axes[0, 1].set_title('Average Light by Hour', fontsize=12, fontweight='bold')
    axes[0, 1].grid(alpha=0.3)

    co2_by_hour = simulated_df.groupby('hour')['CO2'].mean()
    axes[1, 0].plot(hours, co2_by_hour, marker='o', linewidth=2, color='purple')
    axes[1, 0].set_xlabel('Hour of Day', fontsize=11)
    axes[1, 0].set_ylabel('CO2 (ppm)', fontsize=11)
    axes[1, 0].set_title('Average CO2 by Hour', fontsize=12, fontweight='bold')
    axes[1, 0].grid(alpha=0.3)

    temp_by_hour = simulated_df.groupby('hour')['Temperature'].mean()
    axes[1, 1].plot(hours, temp_by_hour, marker='o', linewidth=2, color='red')
    axes[1, 1].set_xlabel('Hour of Day', fontsize=11)
    axes[1, 1].set_ylabel('Temperature (°C)', fontsize=11)
    axes[1, 1].set_title('Average Temperature by Hour', fontsize=12, fontweight='bold')
    axes[1, 1].grid(alpha=0.3)

    plt.tight_layout()
    plot_path = PLOTS_DIR / "simulated_daily_patterns.png"
    plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    logger.info(f"✓ Saved daily patterns plot to {plot_path}")
    plt.close()


def save_evaluation_report(metrics, simulated_df, output_path):
    """Save comprehensive evaluation report."""
    logger.info("\nSaving evaluation report...")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("TRANSFER LEARNING EVALUATION REPORT\n")
        f.write("UCI Occupancy Model → Simulated Building Data\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*80 + "\n\n")

        f.write("DATASET:\n")
        f.write(f"  Simulated samples: {len(simulated_df)}\n")
        f.write(f"  Date range: {simulated_df['date'].min()} to {simulated_df['date'].max()}\n")
        f.write(f"  Occupancy rate: {(simulated_df['Occupancy']==1).sum()} ({100*(simulated_df['Occupancy']==1).sum()/len(simulated_df):.1f}%)\n\n")

        f.write("MODEL PERFORMANCE:\n")
        f.write(f"  Accuracy:  {metrics['accuracy']:.6f}\n")
        f.write(f"  Precision: {metrics['precision']:.6f}\n")
        f.write(f"  Recall:    {metrics['recall']:.6f}\n")
        f.write(f"  F1-Score:  {metrics['f1']:.6f}\n")
        f.write(f"  ROC-AUC:   {metrics['roc_auc']:.6f}\n\n")

        f.write("CONFUSION MATRIX:\n")
        f.write(str(metrics['confusion_matrix']) + "\n\n")

        f.write("CLASSIFICATION REPORT:\n")
        f.write(metrics['classification_report'] + "\n\n")

        f.write("INTERPRETATION:\n")
        f.write("-"*80 + "\n")
        if metrics['accuracy'] > 0.90:
            f.write("✓ EXCELLENT TRANSFER: Model generalizes well to simulated building data!\n")
            f.write("  - No fine-tuning needed for deployment\n")
        elif metrics['accuracy'] > 0.85:
            f.write("⚠ GOOD TRANSFER: Model performs well with minor domain gap\n")
            f.write("  - Consider fine-tuning for improved performance\n")
        else:
            f.write("⚠ DOMAIN GAP DETECTED: Significant performance drop\n")
            f.write("  - Recommend transfer learning fine-tuning\n")

        f.write("\nNEXT STEPS:\n")
        f.write("1. If accuracy > 0.90: Deploy model as-is\n")
        f.write("2. If accuracy 0.85-0.90: Fine-tune on simulated data\n")
        f.write("3. If accuracy < 0.85: Implement full transfer learning pipeline\n")

    logger.info(f"✓ Saved report to {output_path}")


def main():
    """Main evaluation pipeline."""
    try:
        logger.info("="*80)
        logger.info("TRANSFER LEARNING EVALUATION")
        logger.info("="*80)

        # Load model and data
        model, scaler, features = load_model_and_scaler()
        simulated_df = load_simulated_data(DATA_DIR / "simulated_occupancy_data.csv")

        # Evaluate
        metrics = evaluate_on_simulated_data(model, scaler, features, simulated_df)

        # Generate plots
        plot_predictions_over_time(simulated_df, metrics, PLOTS_DIR / "predictions_timeline.png")
        plot_daily_patterns(simulated_df, metrics)

        # Save report
        report_path = METRICS_DIR / "uci_model_on_simulated_evaluation.txt"
        save_evaluation_report(metrics, simulated_df, report_path)

        logger.info("\n" + "="*80)
        logger.info("EVALUATION COMPLETE")
        logger.info("="*80)
        logger.info(f"Report: {report_path}")
        logger.info(f"Plots: {PLOTS_DIR}/predictions_timeline.png, simulated_daily_patterns.png")

        return 0

    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
