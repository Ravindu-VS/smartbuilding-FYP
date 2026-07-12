"""
Compare feature distributions between UCI and simulated occupancy datasets.

This script analyzes the statistical properties of environmental sensor features
across two datasets:
  1. UCI Occupancy Detection (real office buildings)
  2. Simulated Smart Building (synthetic data)

The comparison helps identify domain mismatch issues that explain why models
trained on UCI data don't generalize well to simulated environments.

Input:
  - UCI dataset: data/raw/uci_occupancy_detection/datatraining.txt
  - Simulated dataset: data/raw/simulated_occupancy_data.csv

Output:
  - Feature stats CSV: output/metrics/feature_distribution_comparison.csv
  - Distribution plots: output/plots/feature_distribution_comparison.png
  - Console analysis with domain mismatch warnings

Features Compared:
  - Temperature (°C)
  - Humidity (%)
  - Light (lux)
  - CO2 (ppm)
  - HumidityRatio (kg_water/kg_dry_air)

Author: Smart Building Team
Version: 1.0
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent
UCI_PATH = PROJECT_ROOT / "Dataset" / "UCI" / "occupancy+detection" / "datatraining.txt"
SIMULATED_PATH = PROJECT_ROOT / "data" / "raw" / "simulated_occupancy_data.csv"
METRICS_DIR = PROJECT_ROOT / "output" / "metrics"
PLOTS_DIR = PROJECT_ROOT / "output" / "plots"

# Create directories if they don't exist
METRICS_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

# Output paths
COMPARISON_CSV = METRICS_DIR / "feature_distribution_comparison.csv"
COMPARISON_PLOT = PLOTS_DIR / "feature_distribution_comparison.png"

# Features to analyze
FEATURES = ["Temperature", "Humidity", "Light", "CO2", "HumidityRatio"]

# Statistical significance thresholds for warning
MEAN_RATIO_THRESHOLD = 2.0  # Warn if mean differs by more than 2x
STD_RATIO_THRESHOLD = 3.0   # Warn if std differs by more than 3x
RANGE_RATIO_THRESHOLD = 5.0 # Warn if range differs by more than 5x

# Alignment assessment thresholds (stricter for good alignment)
GOOD_MEAN_RATIO = 1.2      # Within ±20% for "good alignment"
GOOD_STD_RATIO = 1.5       # Within ±50% for "good alignment"
GOOD_RANGE_RATIO = 1.3     # Within ±30% for "good alignment"

MODERATE_MEAN_RATIO = 2.0  # Within ±100% for "moderate mismatch"
MODERATE_STD_RATIO = 3.0   # Within ±200% for "moderate mismatch"
MODERATE_RANGE_RATIO = 5.0 # Within ±400% for "moderate mismatch"


def load_datasets():
    """
    Load UCI and simulated datasets.

    Returns:
        Tuple of (uci_df, simulated_df)

    Raises:
        FileNotFoundError: If dataset files are missing.
    """
    logger.info("Loading datasets...")

    # Load UCI data
    if not UCI_PATH.exists():
        raise FileNotFoundError(f"UCI dataset not found: {UCI_PATH}")

    try:
        uci_df = pd.read_csv(UCI_PATH, index_col=0)
        logger.info(f"✓ Loaded UCI dataset: {len(uci_df)} samples")
    except Exception as e:
        logger.error(f"Failed to load UCI dataset: {e}")
        raise

    # Load simulated data
    if not SIMULATED_PATH.exists():
        raise FileNotFoundError(f"Simulated dataset not found: {SIMULATED_PATH}")

    try:
        simulated_df = pd.read_csv(SIMULATED_PATH)
        if 'date' in simulated_df.columns:
            simulated_df['date'] = pd.to_datetime(simulated_df['date'])
        logger.info(f"✓ Loaded simulated dataset: {len(simulated_df)} samples")
    except Exception as e:
        logger.error(f"Failed to load simulated dataset: {e}")
        raise

    return uci_df, simulated_df


def validate_features(uci_df, simulated_df, features):
    """
    Validate that all required features are present in both datasets.

    Args:
        uci_df: UCI dataset
        simulated_df: Simulated dataset
        features: List of feature names to check

    Returns:
        bool: True if all features present

    Raises:
        ValueError: If required features are missing.
    """
    logger.info("Validating features...")

    missing_uci = [f for f in features if f not in uci_df.columns]
    missing_sim = [f for f in features if f not in simulated_df.columns]

    if missing_uci:
        raise ValueError(f"Missing UCI features: {missing_uci}")
    if missing_sim:
        raise ValueError(f"Missing simulated features: {missing_sim}")

    logger.info(f"✓ All {len(features)} features present in both datasets")
    return True


def compute_statistics(df, features):
    """
    Compute distribution statistics for features.

    Args:
        df: DataFrame to analyze
        features: List of feature names

    Returns:
        Dictionary with statistics for each feature
    """
    stats = {}

    for feature in features:
        data = df[feature].dropna()

        stats[feature] = {
            'count': len(data),
            'min': float(np.min(data)),
            'max': float(np.max(data)),
            'range': float(np.max(data) - np.min(data)),
            'mean': float(np.mean(data)),
            'median': float(np.median(data)),
            'std': float(np.std(data)),
            'q25': float(np.percentile(data, 25)),
            'q75': float(np.percentile(data, 75)),
        }

    return stats


def print_statistics_comparison(uci_stats, simulated_stats, features):
    """
    Print side-by-side comparison of feature statistics.

    Args:
        uci_stats: Statistics dictionary for UCI data
        simulated_stats: Statistics dictionary for simulated data
        features: List of feature names
    """
    logger.info("\n" + "="*100)
    logger.info("FEATURE DISTRIBUTION COMPARISON: UCI vs SIMULATED")
    logger.info("="*100)

    for feature in features:
        uci = uci_stats[feature]
        sim = simulated_stats[feature]

        logger.info(f"\n{feature}:")
        logger.info("-"*100)
        logger.info(f"{'Metric':<15} {'UCI':<20} {'Simulated':<20} {'Ratio':<15} {'Status':<20}")
        logger.info("-"*100)

        # Count
        logger.info(f"{'Count':<15} {uci['count']:<20} {sim['count']:<20} {'-':<15} {'':20}")

        # Min
        ratio = sim['min'] / uci['min'] if uci['min'] != 0 else 0
        logger.info(f"{'Min':<15} {uci['min']:<20.6f} {sim['min']:<20.6f} {ratio:<15.2f} {'':20}")

        # Max
        ratio = sim['max'] / uci['max'] if uci['max'] != 0 else 0
        logger.info(f"{'Max':<15} {uci['max']:<20.6f} {sim['max']:<20.6f} {ratio:<15.2f} {'':20}")

        # Range
        ratio = sim['range'] / uci['range'] if uci['range'] != 0 else 0
        status = "⚠️ LARGE DIFF" if ratio > RANGE_RATIO_THRESHOLD or ratio < (1/RANGE_RATIO_THRESHOLD) else ""
        logger.info(f"{'Range':<15} {uci['range']:<20.6f} {sim['range']:<20.6f} {ratio:<15.2f} {status:<20}")

        # Mean
        ratio = sim['mean'] / uci['mean'] if uci['mean'] != 0 else 0
        status = "⚠️ MISMATCH" if ratio > MEAN_RATIO_THRESHOLD or ratio < (1/MEAN_RATIO_THRESHOLD) else ""
        logger.info(f"{'Mean':<15} {uci['mean']:<20.6f} {sim['mean']:<20.6f} {ratio:<15.2f} {status:<20}")

        # Median
        logger.info(f"{'Median':<15} {uci['median']:<20.6f} {sim['median']:<20.6f} {'-':<15} {'':20}")

        # Std Dev
        ratio = sim['std'] / uci['std'] if uci['std'] != 0 else 0
        status = "⚠️ HIGH VAR" if ratio > STD_RATIO_THRESHOLD or ratio < (1/STD_RATIO_THRESHOLD) else ""
        logger.info(f"{'Std Dev':<15} {uci['std']:<20.6f} {sim['std']:<20.6f} {ratio:<15.2f} {status:<20}")

        # IQR
        uci_iqr = uci['q75'] - uci['q25']
        sim_iqr = sim['q75'] - sim['q25']
        logger.info(f"{'IQR (Q3-Q1)':<15} {uci_iqr:<20.6f} {sim_iqr:<20.6f} {'-':<15} {'':20}")


def identify_domain_mismatches(uci_stats, simulated_stats, features):
    """
    Identify and report potential domain mismatch issues.

    Args:
        uci_stats: Statistics dictionary for UCI data
        simulated_stats: Statistics dictionary for simulated data
        features: List of feature names

    Returns:
        List of warnings/issues identified
    """
    logger.info("\n" + "="*100)
    logger.info("DOMAIN MISMATCH ANALYSIS")
    logger.info("="*100)

    issues = []

    for feature in features:
        uci = uci_stats[feature]
        sim = simulated_stats[feature]

        logger.info(f"\n{feature}:")
        logger.info("-"*100)

        # Check range mismatch
        range_ratio = sim['range'] / uci['range'] if uci['range'] != 0 else 0
        if range_ratio > RANGE_RATIO_THRESHOLD:
            msg = f"⚠️ RANGE MUCH LARGER: Simulated range {range_ratio:.1f}x larger than UCI"
            logger.warning(msg)
            issues.append((feature, "Range", msg))
        elif range_ratio < (1/RANGE_RATIO_THRESHOLD):
            msg = f"⚠️ RANGE MUCH SMALLER: Simulated range {1/range_ratio:.1f}x smaller than UCI"
            logger.warning(msg)
            issues.append((feature, "Range", msg))
        else:
            logger.info(f"✓ Range ratio: {range_ratio:.2f}x (acceptable)")

        # Check mean mismatch
        mean_ratio = sim['mean'] / uci['mean'] if uci['mean'] != 0 else 0
        if mean_ratio > MEAN_RATIO_THRESHOLD:
            msg = f"⚠️ MEAN MUCH HIGHER: Simulated mean {mean_ratio:.1f}x higher than UCI"
            logger.warning(msg)
            issues.append((feature, "Mean", msg))
        elif mean_ratio < (1/MEAN_RATIO_THRESHOLD):
            msg = f"⚠️ MEAN MUCH LOWER: Simulated mean {1/mean_ratio:.1f}x lower than UCI"
            logger.warning(msg)
            issues.append((feature, "Mean", msg))
        else:
            logger.info(f"✓ Mean ratio: {mean_ratio:.2f}x (acceptable)")

        # Check variability mismatch
        std_ratio = sim['std'] / uci['std'] if uci['std'] != 0 else 0
        if std_ratio > STD_RATIO_THRESHOLD:
            msg = f"⚠️ MUCH MORE VARIABLE: Simulated std {std_ratio:.1f}x higher than UCI"
            logger.warning(msg)
            issues.append((feature, "Variability", msg))
        elif std_ratio < (1/STD_RATIO_THRESHOLD):
            msg = f"⚠️ MUCH LESS VARIABLE: Simulated std {1/std_ratio:.1f}x lower than UCI"
            logger.warning(msg)
            issues.append((feature, "Variability", msg))
        else:
            logger.info(f"✓ Variability ratio: {std_ratio:.2f}x (acceptable)")

    logger.info("\n" + "-"*100)
    logger.info(f"SUMMARY: Found {len(issues)} potential domain mismatch issues")

    return issues


def check_scale_warnings(uci_df, simulated_df, features):
    """
    Check for potential scale or unit issues.

    Args:
        uci_df: UCI dataset
        simulated_df: Simulated dataset
        features: List of feature names

    Returns:
        List of scale warnings
    """
    logger.info("\n" + "="*100)
    logger.info("SCALE & UNIT ANALYSIS")
    logger.info("="*100)

    warnings = []

    # Expected ranges for each feature (based on domain knowledge)
    expected_ranges = {
        'Temperature': (10, 35),      # °C, reasonable room temperature
        'Humidity': (20, 70),         # %, indoor comfort range
        'Light': (0, 2000),          # lux, indoor lighting range
        'CO2': (400, 2000),          # ppm, air quality range
        'HumidityRatio': (0.002, 0.02)  # kg_water/kg_dry_air
    }

    for feature in features:
        if feature not in expected_ranges:
            continue

        expected_min, expected_max = expected_ranges[feature]
        uci_min = uci_df[feature].min()
        uci_max = uci_df[feature].max()
        sim_min = simulated_df[feature].min()
        sim_max = simulated_df[feature].max()

        logger.info(f"\n{feature}:")
        logger.info(f"  Expected range: {expected_min} - {expected_max}")
        logger.info(f"  UCI range:      {uci_min:.2f} - {uci_max:.2f}")
        logger.info(f"  Simulated range: {sim_min:.2f} - {sim_max:.2f}")

        # Check if ranges are realistic
        uci_realistic = (uci_min >= expected_min and uci_max <= expected_max)
        sim_realistic = (sim_min >= expected_min and sim_max <= expected_max)

        if not uci_realistic:
            msg = f"⚠️ UCI data outside expected range!"
            logger.warning(msg)
            warnings.append((feature, "UCI Scale", msg))
        else:
            logger.info("✓ UCI range realistic")

        if not sim_realistic:
            msg = f"⚠️ Simulated data outside expected range!"
            logger.warning(msg)
            warnings.append((feature, "Simulated Scale", msg))
        else:
            logger.info("✓ Simulated range realistic")

    return warnings


def assess_feature_alignment(uci_stats, simulated_stats, features):
    """
    Assess alignment quality for each feature.

    Categories:
    - "Good alignment": Feature distributions are very similar
    - "Moderate mismatch": Some differences but manageable
    - "Severe mismatch": Major differences requiring domain adaptation

    Args:
        uci_stats: Statistics dictionary for UCI data
        simulated_stats: Statistics dictionary for simulated data
        features: List of feature names

    Returns:
        Dictionary mapping feature → alignment assessment
    """
    alignments = {}

    for feature in features:
        uci = uci_stats[feature]
        sim = simulated_stats[feature]

        # Calculate ratios (clamp to 0.1-10 range for safer comparisons)
        mean_ratio = sim['mean'] / uci['mean'] if uci['mean'] != 0 else 1.0
        mean_ratio = np.clip(mean_ratio, 0.1, 10)

        std_ratio = sim['std'] / uci['std'] if uci['std'] != 0 else 1.0
        std_ratio = np.clip(std_ratio, 0.1, 10)

        range_ratio = sim['range'] / uci['range'] if uci['range'] != 0 else 1.0
        range_ratio = np.clip(range_ratio, 0.1, 10)

        # Determine alignment category
        # Check if within good thresholds
        mean_good = abs(1 - mean_ratio) <= (GOOD_MEAN_RATIO - 1)
        std_good = abs(1 - std_ratio) <= (GOOD_STD_RATIO - 1)
        range_good = abs(1 - range_ratio) <= (GOOD_RANGE_RATIO - 1)

        # Check if within moderate thresholds
        mean_moderate = abs(1 - mean_ratio) <= (MODERATE_MEAN_RATIO - 1)
        std_moderate = abs(1 - std_ratio) <= (MODERATE_STD_RATIO - 1)
        range_moderate = abs(1 - range_ratio) <= (MODERATE_RANGE_RATIO - 1)

        # Classification logic
        if mean_good and std_good and range_good:
            assessment = "GOOD"
        elif mean_moderate and std_moderate and range_moderate:
            assessment = "MODERATE"
        else:
            assessment = "SEVERE"

        alignments[feature] = {
            'assessment': assessment,
            'mean_ratio': mean_ratio,
            'std_ratio': std_ratio,
            'range_ratio': range_ratio,
            'details': {
                'mean_good': mean_good,
                'std_good': std_good,
                'range_good': range_good,
                'mean_moderate': mean_moderate,
                'std_moderate': std_moderate,
                'range_moderate': range_moderate
            }
        }

    return alignments


def print_alignment_assessment(alignments, features):
    """
    Print alignment assessment results for all features.

    Args:
        alignments: Dictionary of alignment assessments
        features: List of feature names
    """
    logger.info("\n" + "="*100)
    logger.info("ALIGNMENT ASSESSMENT: IS CORRECTED DATA READY FOR MODEL?")
    logger.info("="*100)

    logger.info(f"\n{'Feature':<20} {'Assessment':<15} {'Mean Ratio':<15} {'Std Ratio':<15} {'Range Ratio':<15}")
    logger.info("-"*100)

    good_count = 0
    moderate_count = 0
    severe_count = 0

    for feature in features:
        align = alignments[feature]
        assessment = align['assessment']

        # Count by category
        if assessment == "GOOD":
            good_count += 1
            status_symbol = "✓"
        elif assessment == "MODERATE":
            moderate_count += 1
            status_symbol = "~"
        else:
            severe_count += 1
            status_symbol = "✗"

        logger.info(
            f"{feature:<20} {status_symbol} {assessment:<13} "
            f"{align['mean_ratio']:<15.2f}x "
            f"{align['std_ratio']:<15.2f}x "
            f"{align['range_ratio']:<15.2f}x"
        )

    logger.info("\n" + "-"*100)
    logger.info(f"Summary: {good_count} GOOD, {moderate_count} MODERATE, {severe_count} SEVERE")
    logger.info("-"*100)

    # Special checks for critical features
    logger.info("\nCRITICAL FEATURE CHECK:")
    logger.info("-"*100)

    hr_status = alignments['HumidityRatio']['assessment']
    co2_status = alignments['CO2']['assessment']

    if hr_status == "GOOD":
        logger.info("✓ HumidityRatio: GOOD alignment (BUG FIX SUCCESSFUL!)")
    elif hr_status == "MODERATE":
        logger.info("~ HumidityRatio: MODERATE mismatch (acceptable for transfer learning)")
    else:
        logger.warning("✗ HumidityRatio: SEVERE mismatch (still problematic)")

    if co2_status == "GOOD":
        logger.info("✓ CO2: GOOD alignment (excellent occupancy signal)")
    elif co2_status == "MODERATE":
        logger.info("~ CO2: MODERATE mismatch (acceptable but could be better)")
    else:
        logger.warning("✗ CO2: SEVERE mismatch (weak occupancy discrimination)")

    return {
        'good': good_count,
        'moderate': moderate_count,
        'severe': severe_count,
        'humidity_ratio_status': hr_status,
        'co2_status': co2_status
    }


def save_comparison_csv(uci_stats, simulated_stats, alignments, features, output_path):
    """
    Save feature statistics comparison to CSV file with alignment assessment.

    Args:
        uci_stats: Statistics dictionary for UCI data
        simulated_stats: Statistics dictionary for simulated data
        alignments: Alignment assessment dictionary
        features: List of feature names
        output_path: Path to save CSV file
    """
    logger.info(f"\nSaving comparison to {output_path}...")

    try:
        rows = []

        for feature in features:
            uci = uci_stats[feature]
            sim = simulated_stats[feature]
            align = alignments[feature]

            for metric in ['count', 'min', 'max', 'range', 'mean', 'median', 'std', 'q25', 'q75']:
                uci_val = uci[metric]
                sim_val = sim[metric]

                # Calculate ratio with safety check
                if metric == 'count':
                    ratio = np.nan
                elif uci_val != 0:
                    ratio = sim_val / uci_val
                else:
                    ratio = np.nan

                # Add alignment assessment only for mean and std metrics
                if metric in ['mean', 'std']:
                    alignment = align['assessment']
                else:
                    alignment = ""

                rows.append({
                    'Feature': feature,
                    'Metric': metric,
                    'UCI': uci_val,
                    'Simulated': sim_val,
                    'Ratio (Sim/UCI)': ratio,
                    'Alignment': alignment
                })

        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False)
        logger.info(f"✓ Saved comparison to {output_path}")

    except Exception as e:
        logger.error(f"Failed to save CSV: {e}")


def plot_feature_distributions(uci_df, simulated_df, features, output_path):
    """
    Create histograms/density plots comparing UCI and simulated distributions.

    Args:
        uci_df: UCI dataset
        simulated_df: Simulated dataset
        features: List of feature names
        output_path: Path to save plot
    """
    logger.info(f"Creating distribution plots...")

    try:
        # Create subplots
        fig, axes = plt.subplots(2, 3, figsize=(16, 10))
        axes = axes.flatten()

        for idx, feature in enumerate(features):
            ax = axes[idx]

            # Get data
            uci_data = uci_df[feature].dropna()
            sim_data = simulated_df[feature].dropna()

            # Plot histograms with density
            ax.hist(uci_data, bins=50, alpha=0.6, label='UCI', color='blue', density=True, edgecolor='black')
            ax.hist(sim_data, bins=50, alpha=0.6, label='Simulated', color='orange', density=True, edgecolor='black')

            # Add density curves
            uci_data.plot(kind='density', ax=ax, linewidth=2, color='darkblue', label='UCI Density')
            sim_data.plot(kind='density', ax=ax, linewidth=2, color='darkorange', label='Simulated Density')

            ax.set_title(f'{feature} Distribution Comparison', fontsize=12, fontweight='bold')
            ax.set_xlabel('Value', fontsize=10)
            ax.set_ylabel('Density', fontsize=10)
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)

            # Add statistics text
            uci_mean = uci_data.mean()
            sim_mean = sim_data.mean()
            text = f"UCI mean: {uci_mean:.3f}\nSim mean: {sim_mean:.3f}"
            ax.text(0.98, 0.97, text, transform=ax.transAxes,
                   verticalalignment='top', horizontalalignment='right',
                   bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
                   fontsize=9)

        # Remove extra subplot
        fig.delaxes(axes[5])

        plt.tight_layout()
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        logger.info(f"✓ Saved plots to {output_path}")
        plt.close()

    except Exception as e:
        logger.error(f"Failed to create plots: {e}")


def assess_model_evaluation_readiness(alignment_summary):
    """
    Determine if corrected simulated data is ready for model evaluation.

    Args:
        alignment_summary: Dictionary from print_alignment_assessment()

    Returns:
        Dictionary with readiness assessment and recommendations
    """
    logger.info("\n" + "="*100)
    logger.info("MODEL EVALUATION READINESS ASSESSMENT")
    logger.info("="*100)

    good = alignment_summary['good']
    moderate = alignment_summary['moderate']
    severe = alignment_summary['severe']
    total = good + moderate + severe

    hr_status = alignment_summary['humidity_ratio_status']
    co2_status = alignment_summary['co2_status']

    # Determine readiness
    is_ready = False
    confidence = ""
    recommendations = []

    logger.info(f"\nAlignment Results: {good} GOOD | {moderate} MODERATE | {severe} SEVERE (out of {total} features)")
    logger.info("-"*100)

    # Readiness logic
    if severe == 0 and good >= 3:
        is_ready = True
        confidence = "HIGH"
        status_icon = "✅"
        logger.info(f"\n{status_icon} **READY FOR MODEL EVALUATION**")
        logger.info("   Corrected simulated data shows good alignment with UCI dataset.")
        logger.info("   Expected: Model should generalize better than before (F1 > 0.60).")

    elif severe == 0 and good >= 2:
        is_ready = True
        confidence = "MODERATE"
        status_icon = "✓"
        logger.info(f"\n{status_icon} **CONDITIONALLY READY FOR MODEL EVALUATION**")
        logger.info("   Most critical features aligned well.")
        logger.info("   Expected: Moderate improvement in model performance.")
        recommendations.append("Monitor feature-specific performance metrics during evaluation")

    elif severe <= 1 and good + moderate >= 4:
        is_ready = True
        confidence = "LOWER"
        status_icon = "⚠"
        logger.info(f"\n{status_icon} **READY FOR EVALUATION (WITH CAUTION)**")
        logger.info("   Some features still have mismatches.")
        logger.info("   Expected: May need transfer learning or domain adaptation.")
        recommendations.append("Consider threshold adjustment based on evaluation results")
        recommendations.append("Be prepared to implement domain adaptation techniques")

    else:
        is_ready = False
        confidence = "LOW"
        status_icon = "❌"
        logger.info(f"\n{status_icon} **NOT YET READY - NEEDS MORE TUNING**")
        logger.info("   Too many severe mismatches remain.")
        logger.info("   Recommendation: Review and further adjust simulation parameters.")
        recommendations.append("Re-examine CO2 and HumidityRatio generation logic")
        recommendations.append("Consider increasing measurement noise for realistic variability")

    # Critical feature summary
    logger.info("\nCritical Feature Status:")
    logger.info("-"*100)

    if hr_status == "GOOD":
        logger.info("✓ HumidityRatio: Well aligned (bug fix successful)")
    else:
        logger.info(f"~ HumidityRatio: {hr_status} alignment")
        if hr_status == "SEVERE":
            recommendations.append("URGENT: HumidityRatio still problematic - may need further corrections")

    if co2_status == "GOOD":
        logger.info("✓ CO2: Well aligned (strong occupancy signal)")
    else:
        logger.info(f"~ CO2: {co2_status} alignment")
        if co2_status == "SEVERE":
            recommendations.append("URGENT: CO2 still weak - adjust accumulation/decay rates")

    # Print recommendations
    if recommendations:
        logger.info("\nRecommendations:")
        logger.info("-"*100)
        for i, rec in enumerate(recommendations, 1):
            logger.info(f"  {i}. {rec}")

    logger.info("\n" + "="*100)
    logger.info("CONCLUSION")
    logger.info("="*100)

    if is_ready:
        logger.info(f"✅ **PROCEED WITH MODEL EVALUATION** (Confidence: {confidence})")
        if confidence == "HIGH":
            logger.info("\nExpected Results:")
            logger.info("  • Model accuracy should improve significantly from current baseline")
            logger.info("  • F1-score expected to be ~0.65-0.75 (up from 0.0)")
            logger.info("  • Occupancy discrimination should be strong due to CO2 + Light signals")
        elif confidence == "MODERATE":
            logger.info("\nExpected Results:")
            logger.info("  • Model accuracy improvement expected but not guaranteed")
            logger.info("  • F1-score expected to be ~0.55-0.70")
            logger.info("  • May benefit from transfer learning after baseline evaluation")
        else:
            logger.info("\nExpected Results:")
            logger.info("  • Some improvement possible but domain gap still significant")
            logger.info("  • F1-score may be ~0.45-0.65")
            logger.info("  • Plan to implement domain adaptation techniques")
    else:
        logger.info(f"❌ **DELAY EVALUATION - NEEDS MORE TUNING**")
        logger.info("\nNext Steps:")
        logger.info("  1. Review failing features in detail")
        logger.info("  2. Adjust simulation parameters (especially critical features)")
        logger.info("  3. Re-run data generation")
        logger.info("  4. Re-run this comparison script")
        logger.info("  5. Then proceed to model evaluation")

    logger.info("\n" + "="*100)

    return {
        'is_ready': is_ready,
        'confidence': confidence,
        'good_count': good,
        'moderate_count': moderate,
        'severe_count': severe,
        'recommendations': recommendations
    }


def print_summary_report(uci_stats, simulated_stats, features, issues, warnings):
    """
    Print comprehensive summary report.

    Args:
        uci_stats: Statistics for UCI data
        simulated_stats: Statistics for simulated data
        features: List of features analyzed
        issues: List of domain mismatch issues
        warnings: List of scale/unit warnings
    """
    logger.info("\n" + "="*100)
    logger.info("ANALYSIS SUMMARY REPORT")
    logger.info("="*100)

    logger.info(f"\nFeatures Analyzed: {', '.join(features)}")
    logger.info(f"Domain Mismatch Issues Found: {len(issues)}")
    logger.info(f"Scale/Unit Warnings: {len(warnings)}")

    if issues:
        logger.info("\n" + "-"*100)
        logger.info("DOMAIN MISMATCH ISSUES:")
        logger.info("-"*100)
        for feature, issue_type, message in issues:
            logger.warning(f"  {message}")

    if warnings:
        logger.info("\n" + "-"*100)
        logger.info("SCALE/UNIT WARNINGS:")
        logger.info("-"*100)
        for feature, warning_type, message in warnings:
            logger.warning(f"  {message}")

    # Overall assessment
    logger.info("\n" + "="*100)
    logger.info("OVERALL ASSESSMENT")
    logger.info("="*100)

    total_issues = len(issues) + len(warnings)

    if total_issues == 0:
        logger.info("✓ EXCELLENT: Distributions match well, minimal domain gap expected")
    elif total_issues <= 2:
        logger.info("⚠️ MODERATE: Some distribution differences, domain adaptation may help")
    else:
        logger.info("❌ SIGNIFICANT: Multiple distribution differences, domain adaptation needed")

    logger.info("\nIMPLICATIONS FOR MODEL GENERALIZATION:")
    logger.info("-"*100)

    # Analyze by issue type
    range_issues = [i for i in issues if i[1] == 'Range']
    mean_issues = [i for i in issues if i[1] == 'Mean']
    var_issues = [i for i in issues if i[1] == 'Variability']

    if range_issues:
        logger.info(f"• {len(range_issues)} feature(s) with different ranges")
        logger.info("  → Model may not see full range of values → Conservative predictions")

    if mean_issues:
        logger.info(f"• {len(mean_issues)} feature(s) with different means")
        logger.info("  → Feature center shifted → Poor calibration")

    if var_issues:
        logger.info(f"• {len(var_issues)} feature(s) with different variability")
        logger.info("  → Different data spread → Outlier handling differs")

    if total_issues > 0:
        logger.info("\nRECOMMENDED ACTIONS:")
        logger.info("  1. Use StandardScaler (fitted on UCI data) on new environments")
        logger.info("  2. Implement transfer learning with building-specific data")
        logger.info("  3. Consider domain adaptation techniques")
        logger.info("  4. Collect labeled data from target building")


def main():
    """Main feature comparison pipeline."""
    try:
        logger.info("="*100)
        logger.info("FEATURE DISTRIBUTION COMPARISON: UCI vs SIMULATED (v2.0 - WITH ALIGNMENT ASSESSMENT)")
        logger.info("="*100)

        # Step 1: Load datasets
        uci_df, simulated_df = load_datasets()

        # Step 2: Validate features
        validate_features(uci_df, simulated_df, FEATURES)

        # Step 3: Compute statistics
        logger.info("\nComputing statistics...")
        uci_stats = compute_statistics(uci_df, FEATURES)
        simulated_stats = compute_statistics(simulated_df, FEATURES)

        # Step 4: Print comparison
        print_statistics_comparison(uci_stats, simulated_stats, FEATURES)

        # Step 5: Assess feature alignment (NEW)
        logger.info("\nAssessing feature alignment...")
        alignments = assess_feature_alignment(uci_stats, simulated_stats, FEATURES)

        # Step 6: Print alignment assessment (NEW)
        alignment_summary = print_alignment_assessment(alignments, FEATURES)

        # Step 7: Identify domain mismatches
        issues = identify_domain_mismatches(uci_stats, simulated_stats, FEATURES)

        # Step 8: Check scale/unit warnings
        warnings = check_scale_warnings(uci_df, simulated_df, FEATURES)

        # Step 9: Save comparison CSV (UPDATED with alignments)
        save_comparison_csv(uci_stats, simulated_stats, alignments, FEATURES, COMPARISON_CSV)

        # Step 10: Create plots
        plot_feature_distributions(uci_df, simulated_df, FEATURES, COMPARISON_PLOT)

        # Step 11: Assess model evaluation readiness (NEW)
        readiness = assess_model_evaluation_readiness(alignment_summary)

        # Step 12: Print summary
        print_summary_report(uci_stats, simulated_stats, FEATURES, issues, warnings)

        # Final summary
        logger.info("\n" + "="*100)
        logger.info("COMPARISON COMPLETE")
        logger.info("="*100)
        logger.info(f"Comparison CSV saved: {COMPARISON_CSV}")
        logger.info(f"Distribution plots saved: {COMPARISON_PLOT}")
        logger.info(f"\nModel Evaluation Readiness: {'YES' if readiness['is_ready'] else 'NO'}")
        logger.info(f"Confidence Level: {readiness['confidence']}")

        return 0

    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
