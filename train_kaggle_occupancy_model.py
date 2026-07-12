import os
import glob
import pandas as pd
import numpy as np
import json
import joblib
import logging
from typing import Tuple, Dict, Any

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
    confusion_matrix, roc_curve
)
from sklearn.impute import SimpleImputer
import matplotlib.pyplot as plt
import seaborn as sns

# Optional imports for Kaggle and XGBoost
try:
    import kaggle
    KAGGLE_AVAILABLE = True
except (OSError, ImportError) as e:
    KAGGLE_AVAILABLE = False
    print(f"⚠️ Kaggle API not configured or installed. Error: {e}")
    print("Assuming data is already downloaded manually into 'data/raw/kaggle_occupancy/'.")

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    print("⚠️ XGBoost not installed. Skipping XGBoost model.")

# =============================================================================
# CONFIGURATION
# =============================================================================
KAGGLE_DATASET = "kukuroo3/room-occupancy-detection-data-iot-sensor"
KAGGLE_DIR = os.path.join("data", "raw", "kaggle_occupancy")
SIMULATED_DATA_PATH = os.path.join("data", "raw", "simulated_occupancy_data.csv")

MODELS_DIR = "models"
OUTPUT_PLOTS_DIR = os.path.join("output", "plots")
for d in [KAGGLE_DIR, MODELS_DIR, OUTPUT_PLOTS_DIR]:
    os.makedirs(d, exist_ok=True)

FEATURES = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']
TARGET = 'Occupancy'


# =============================================================================
# STEP 1: DOWNLOAD DATA
# =============================================================================
def download_kaggle_data():
    """Download and extract dataset using Kaggle API."""
    print("\n--- STEP 1: DOWNLOAD DATA ---")
    if KAGGLE_AVAILABLE:
        print(f"Downloading {KAGGLE_DATASET} to {KAGGLE_DIR}...")
        kaggle.api.dataset_download_files(KAGGLE_DATASET, path=KAGGLE_DIR, unzip=True)
        print("Download and extraction complete.")
    else:
        print("Skipping download (Kaggle API not ready). Looking for existing CSV files...")

# =============================================================================
# HELPER: LOAD & STANDARDIZE DATAFRAME
# =============================================================================
def load_and_standardize(file_paths: list, source_name: str) -> pd.DataFrame:
    """Loads CSVs and standardizes feature names and target column."""
    if not file_paths:
        print(f"⚠️ No files found for {source_name}.")
        return pd.DataFrame()
        
    df = pd.concat([pd.read_csv(f) for f in file_paths], ignore_index=True)
    print(f"Loaded {source_name}: {df.shape[0]} rows")
    
    # Detect target column
    target_col = TARGET
    if TARGET not in df.columns:
        possible_targets = ['occupancy', 'target', 'Target', 'Room_Occupancy_Count', 'true_occupancy']
        for pt in possible_targets:
            if pt in df.columns:
                target_col = pt
                break
                
    if target_col in df.columns:
        df['Occupancy_Binary'] = df[target_col].apply(lambda x: 1 if x > 0 else 0)
    else:
        df['Occupancy_Binary'] = 0
        
    # Standardize feature names
    lower_cols = {c.lower(): c for c in df.columns}
    for feature in FEATURES:
        if feature not in df.columns and feature.lower() in lower_cols:
            df[feature] = df[lower_cols[feature.lower()]]
        elif feature not in df.columns:
            df[feature] = 0.0 # Missing feature fallback
            
    # Return exactly the requested columns
    return df[FEATURES + ['Occupancy_Binary']].copy()

# =============================================================================
# STEP 2: LOAD ALL 3 DATASETS (KAGGLE, UCI, SIMULATED)
# =============================================================================
def aggregate_all_datasets() -> Tuple[pd.DataFrame, pd.Series]:
    """Loads Kaggle, UCI, and Simulated datasets and combines them."""
    print("\n--- STEP 2: LOAD & AGGREGATE ALL DATASETS ---")
    
    # 1. Kaggle Dataset
    kaggle_csv = glob.glob(os.path.join(KAGGLE_DIR, "*.csv"))
    df_kaggle = load_and_standardize(kaggle_csv, "Kaggle Dataset")
    
    # 2. UCI Dataset
    # Filter out anything copied into kaggle dir just in case, read straight from Dataset/UCI natively
    uci_files = glob.glob(os.path.join("Dataset", "UCI", "occupancy+detection", "*.txt")) + \
                glob.glob(os.path.join("Dataset", "UCI", "occupancy+detection", "*.csv"))
    df_uci = load_and_standardize(uci_files, "UCI Dataset")
    
    # 3. Simulated Dataset
    if os.path.exists(SIMULATED_DATA_PATH):
        df_sim = load_and_standardize([SIMULATED_DATA_PATH], "Simulated Smart Building Dataset")
    else:
        df_sim = pd.DataFrame()
        
    # Combine ALL together
    df_all = pd.concat([df_kaggle, df_uci, df_sim], ignore_index=True).drop_duplicates()
    print(f"Total Combined Master Dataset Shape: {df_all.shape}")
    
    X = df_all[FEATURES]
    y = df_all['Occupancy_Binary']
    
    # Impute Missing Values across the massive dataset
    print("Imputing any missing boundaries with Median Strategy...")
    imputer = SimpleImputer(strategy='median')
    X_imputed = pd.DataFrame(imputer.fit_transform(X), columns=FEATURES)
    
    return X_imputed, y

# =============================================================================
# STEP 3: MODEL TRAINING & EVALUATION
# =============================================================================
def train_and_evaluate_models(X_train, X_test, y_train, y_test):
    """Train multiple models and select best by F1 score."""
    print("\n--- STEP 3: MODEL TRAINING ---")
    
    models = {
        "Logistic Regression": LogisticRegression(max_iter=1000, random_state=42),
        "Random Forest": RandomForestClassifier(n_estimators=100, random_state=42),
        "Gradient Boosting": GradientBoostingClassifier(n_estimators=100, random_state=42)
    }
    
    if XGB_AVAILABLE:
        models["XGBoost"] = xgb.XGBClassifier(use_label_encoder=False, eval_metric='logloss', random_state=42)
        
    results = {}
    best_f1 = -1
    best_name = None
    best_model = None
    
    for name, model in models.items():
        print(f"Training {name}...")
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        y_prob = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else y_pred
        
        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        roc = roc_auc_score(y_test, y_prob)

        results[name] = {"Accuracy": acc, "Precision": prec, "Recall": rec, "F1-score": f1, "ROC-AUC": roc}
        
        if f1 > best_f1:
            best_f1 = f1
            best_name = name
            best_model = model

    print("\n--- MODEL EVALUATION RESULTS ---")
    results_df = pd.DataFrame(results).T
    print(results_df.round(4))
    
    print(f"\n🏆 Best Model: {best_name} (F1: {best_f1:.4f})")
    return best_model, best_name

# =============================================================================
# STEP 4: MODEL SAVING
# =============================================================================
def save_artifacts(model, scaler, prefix="kaggle"):
    """Save model, scaler, and feature definitions."""
    print(f"\n--- STEP 4: SAVING MODELS ({prefix}) ---")
    
    model_path = os.path.join(MODELS_DIR, f"{prefix}_occupancy_model.pkl")
    scaler_path = os.path.join(MODELS_DIR, f"{prefix}_scaler.pkl")
    features_path = os.path.join(MODELS_DIR, f"{prefix}_features.json")
    
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)
    
    with open(features_path, "w") as f:
        json.dump(FEATURES, f)
        
    print(f"Saved: {model_path}")
    print(f"Saved: {scaler_path}")
    print(f"Saved: {features_path}")

# =============================================================================
# STEP 5: VISUALIZATION
# =============================================================================
def generate_plots(model, X_test, y_test, model_name, prefix="kaggle"):
    """Generate confusion matrix, ROC curve, and feature importance."""
    print(f"\n--- STEP 5: VISUALIZATION ({prefix}) ---")
    
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else y_pred
    
    # 1. Confusion Matrix
    cm = confusion_matrix(y_test, y_pred)
    plt.figure(figsize=(6,5))
    sns.heatmap(cm, annot=True, fmt="d", cmap="Blues")
    plt.title(f"{model_name} Confusion Matrix")
    plt.ylabel("Actual")
    plt.xlabel("Predicted")
    plt.savefig(os.path.join(OUTPUT_PLOTS_DIR, f"{prefix}_confusion_matrix.png"))
    plt.close()
    
    # 2. ROC Curve
    fpr, tpr, _ = roc_curve(y_test, y_prob)
    plt.figure(figsize=(6,5))
    plt.plot(fpr, tpr, label=f"AUC = {roc_auc_score(y_test, y_prob):.3f}")
    plt.plot([0,1], [0,1], 'r--')
    plt.title(f"{model_name} ROC Curve")
    plt.legend()
    plt.savefig(os.path.join(OUTPUT_PLOTS_DIR, f"{prefix}_roc_curve.png"))
    plt.close()
    
    # 3. Feature Importance (if applicable)
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1]
        
        plt.figure(figsize=(8,5))
        plt.bar(range(len(FEATURES)), importances[indices], align="center")
        plt.xticks(range(len(FEATURES)), [FEATURES[i] for i in indices], rotation=45)
        plt.title(f"{model_name} Feature Importances")
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_PLOTS_DIR, f"{prefix}_feature_importance.png"))
        plt.close()
        
    print(f"Plots saved to {OUTPUT_PLOTS_DIR}/")

# We removed perform_domain_adaptation as it is natively embedded by training the master combined dataset.

# =============================================================================
# MAIN EXECUTION
# =============================================================================
def main():
    print("🚀 Starting Master Occupancy Pipeline (Kaggle + UCI + Simulated)...")
    
    # Step 1: Download
    download_kaggle_data()
    
    # Step 2: Preprocess ALL Datasets
    X, y = aggregate_all_datasets()
    
    # Scaling
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    # Splitting
    X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2, random_state=42)
    
    # Step 3: Train & Evaluate Master Model
    print("Evaluating models on combined master dataset...")
    best_model, best_name = train_and_evaluate_models(X_train, X_test, y_train, y_test)
    
    # Step 4 & 5: Save & Plot
    save_artifacts(best_model, scaler, prefix="domain_adapted_kaggle")
    generate_plots(best_model, X_test, y_test, best_name, prefix="domain_adapted_kaggle")
    print(f"\n✅ Successfully saved MOST ACCURATE model ({best_name}) to production integration!")

if __name__ == "__main__":
    main()
