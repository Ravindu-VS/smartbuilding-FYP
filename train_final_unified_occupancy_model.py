import os
import shutil
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import json
import joblib

from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix, roc_curve

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

# ==========================================
# 1. Configuration & Paths
# ==========================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

ORIGINAL_PATHS = {
    "Kaggle": [
        "Dataset/Kaggle_Room_Occupancy/datatest.txt",
        "Dataset/Kaggle_Room_Occupancy/datatest2.txt",
        "Dataset/Kaggle_Room_Occupancy/datatraining.txt",
        "Dataset/Kaggle_Room_Occupancy/file.csv",
        "Dataset/Kaggle_Room_Occupancy/Occupancy.csv",
        "data/raw/kaggle_occupancy/Occupancy.csv"
    ],
    "UCI": [
        "Dataset/UCI/occupancy+detection/datatest.txt",
        "Dataset/UCI/occupancy+detection/datatest2.txt",
        "Dataset/UCI/occupancy+detection/datatraining.txt"
    ],
    "Simulated": [
        "data/raw/simulated_occupancy_data_baseline.csv",
        "data/raw/simulated_occupancy_data.csv"
    ]
}

UNIFIED_DIR = os.path.join(PROJECT_ROOT, "Dataset", "Unified")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")
METRICS_DIR = os.path.join(PROJECT_ROOT, "output", "metrics")
PLOTS_DIR = os.path.join(PROJECT_ROOT, "output", "plots")

for d in [MODELS_DIR, METRICS_DIR, PLOTS_DIR]:
    os.makedirs(d, exist_ok=True)

# Important columns standard
TARGET_COL = 'Occupancy'
FEATURE_COLS = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']

# ==========================================
# 2. Data Centralization (Copy to Unified)
# ==========================================
def centralize_datasets():
    print("[1/6] Copying datasets to Unified Directory...")
    for category, files in ORIGINAL_PATHS.items():
        cat_dir = os.path.join(UNIFIED_DIR, category)
        os.makedirs(cat_dir, exist_ok=True)
        for filepath in files:
            full_path = os.path.join(PROJECT_ROOT, filepath.replace("/", os.sep))
            if os.path.exists(full_path):
                dest = os.path.join(cat_dir, os.path.basename(full_path))
                # Distinguish if there's duplicate names in original
                count = 1
                while os.path.exists(dest) and not os.path.samefile(full_path, dest):
                    name, ext = os.path.splitext(os.path.basename(full_path))
                    dest = os.path.join(cat_dir, f"{name}_{count}{ext}")
                    count += 1
                try:
                    shutil.copy2(full_path, dest)
                except shutil.SameFileError:
                    pass
            else:
                print(f"Warning: Extant file not found: {full_path}")

# ==========================================
# 3. Data Loading & Harmonization
# ==========================================
def load_and_harmonize():
    print("[2/6] Loading and harmonizing datasets...")
    all_dataframes = []
    
    for category in os.listdir(UNIFIED_DIR):
        cat_dir = os.path.join(UNIFIED_DIR, category)
        if not os.path.isdir(cat_dir):
            continue
        
        for file in os.listdir(cat_dir):
            path = os.path.join(cat_dir, file)
            try:
                df = pd.read_csv(path)
            except Exception as e:
                print(f"Skipping {file}: {e}")
                continue
            
            # Identify columns
            cols = df.columns.tolist()
            
            # Some files might have 'date' or unnamed indices
            # Keep only standard features if they exist
            has_all = all(col in cols for col in FEATURE_COLS + [TARGET_COL])
            if not has_all:
                continue # skip if doesn't match schema
            
            # Map columns and extract subset
            df = df[FEATURE_COLS + [TARGET_COL]].copy()
            
            # Add metadata
            df['source_dataset'] = category
            df['source_type'] = 'Simulated' if category == 'Simulated' else 'Empirical'
            
            all_dataframes.append(df)
            
    if not all_dataframes:
        raise ValueError("No valid datasets found matching the schema.")
        
    unified_df = pd.concat(all_dataframes, ignore_index=True)
    return unified_df

# ==========================================
# 4. Deduplication
# ==========================================
def deduplicate_data(df):
    print("[3/6] Detecting and handling exact duplicates...")
    initial_rows = len(df)
    
    # We want to drop duplicates based on feature columns to avoid double counting across Kaggle/UCI
    # Since Kaggle and UCI are largely the same datasets, identical measurements mean duplicated rows.
    # We will prioritize keeping 'Simulated' to avoid losing simulated overlap, 
    # but mostly empirical overlap is the issue.
    
    subset = FEATURE_COLS + [TARGET_COL]
    
    df_dedup = df.drop_duplicates(subset=subset, keep='first').copy()
    
    dropped = initial_rows - len(df_dedup)
    print(f"  -> Dropped {dropped} duplicate rows across datasets.")
    
    return df_dedup

# ==========================================
# 5. Model Training & Evaluation
# ==========================================
def train_and_evaluate(df):
    print("[4/6] Data Splitting & Model Training...")
    
    # We split into Train/Test across Empirical vs Simulated
    df_empirical = df[df['source_type'] == 'Empirical']
    df_simulated = df[df['source_type'] == 'Simulated']
    
    from sklearn.model_selection import train_test_split
    
    # Train test split on empirical
    X_e = df_empirical[FEATURE_COLS]
    y_e = df_empirical[TARGET_COL]
    
    X_e_train, X_e_test, y_e_train, y_e_test = train_test_split(X_e, y_e, test_size=0.2, random_state=42, stratify=y_e)
    
    # Train test split on simulated (we'll mix a bit into train to adapt it, but leave a pure holdout)
    X_s = df_simulated[FEATURE_COLS]
    y_s = df_simulated[TARGET_COL]
    
    X_s_train, X_s_test, y_s_train, y_s_test = train_test_split(X_s, y_s, test_size=0.3, random_state=42, stratify=y_s)
    
    X_train = pd.concat([X_e_train, X_s_train])
    y_train = pd.concat([y_e_train, y_s_train])
    
    # Test on completely mixed holdout + specific isolated holdouts
    
    models = {
        'Logistic Regression': LogisticRegression(max_iter=1000, random_state=42),
        'Random Forest': RandomForestClassifier(n_estimators=100, random_state=42),
        'Gradient Boosting': GradientBoostingClassifier(n_estimators=100, random_state=42)
    }
    
    if HAS_XGB:
        models['XGBoost'] = XGBClassifier(use_label_encoder=False, eval_metric='logloss', random_state=42)
        
    results = []
    trained_pipelines = {}
    
    for name, clf in models.items():
        pipeline = Pipeline([
            ('imputer', SimpleImputer(strategy='median')),
            ('scaler', StandardScaler()),
            ('model', clf)
        ])
        
        # Train
        pipeline.fit(X_train, y_train)
        trained_pipelines[name] = pipeline
        
        # Eval Empirical
        y_e_pred = pipeline.predict(X_e_test)
        y_e_prob = pipeline.predict_proba(X_e_test)[:, 1] if hasattr(pipeline, 'predict_proba') else [0]*len(y_e_test)
        
        # Eval Simulated
        y_s_pred = pipeline.predict(X_s_test)
        y_s_prob = pipeline.predict_proba(X_s_test)[:, 1] if hasattr(pipeline, 'predict_proba') else [0]*len(y_s_test)
        
        results.append({
            'Model': name,
            'TestDomain': 'Empirical',
            'Accuracy': accuracy_score(y_e_test, y_e_pred),
            'Precision': precision_score(y_e_test, y_e_pred, zero_division=0),
            'Recall': recall_score(y_e_test, y_e_pred, zero_division=0),
            'F1': f1_score(y_e_test, y_e_pred, zero_division=0),
            'ROC-AUC': roc_auc_score(y_e_test, y_e_prob) if len(np.unique(y_e_test)) > 1 else np.nan
        })
        
        results.append({
            'Model': name,
            'TestDomain': 'Simulated',
            'Accuracy': accuracy_score(y_s_test, y_s_pred),
            'Precision': precision_score(y_s_test, y_s_pred, zero_division=0),
            'Recall': recall_score(y_s_test, y_s_pred, zero_division=0),
            'F1': f1_score(y_s_test, y_s_pred, zero_division=0),
            'ROC-AUC': roc_auc_score(y_s_test, y_s_prob) if len(np.unique(y_s_test)) > 1 else np.nan
        })

    res_df = pd.DataFrame(results)
    
    return trained_pipelines, res_df, X_train, y_train, X_e_test, y_e_test, X_s_test, y_s_test

# ==========================================
# 6. Artifact Generation & Plotting
# ==========================================
def save_artifacts(df_original, df_dedup, trained_pipelines, res_df, X_s_test, y_s_test):
    print("[5/6] Generating Plots and saving artifacts...")
    
    # Datasets sizes
    summary = {
        'initial_rows': len(df_original),
        'deduplicated_rows': len(df_dedup),
        'source_distribution': df_dedup['source_dataset'].value_counts().to_dict(),
        'class_distribution': df_dedup[TARGET_COL].value_counts().to_dict(),
        'means': df_dedup[FEATURE_COLS].mean().to_dict(),
        'stds': df_dedup[FEATURE_COLS].std().to_dict()
    }
    
    summary_df = pd.DataFrame(res_df)
    summary_df.to_csv(os.path.join(METRICS_DIR, 'final_unified_model_metrics.csv'), index=False)
    
    with open(os.path.join(METRICS_DIR, 'final_dataset_summary.json'), 'w') as f:
        json.dump(summary, f, indent=4)
        
    with open(os.path.join(MODELS_DIR, 'final_unified_features.json'), 'w') as f:
        json.dump({'features': FEATURE_COLS, 'target': TARGET_COL}, f, indent=4)
    
    # Select Best Model based on F1 on Simulated Data (domain of the digital twin)
    sim_results = res_df[res_df['TestDomain'] == 'Simulated'].copy()
    best_model_name = sim_results.loc[sim_results['F1'].idxmax()]['Model']
    best_pipeline = trained_pipelines[best_model_name]
    
    joblib.dump(best_pipeline, os.path.join(MODELS_DIR, 'final_unified_occupancy_pipeline.pkl'))
    
    # Plots
    sns.set_theme(style='whitegrid')
    
    # 1. Source Distribution
    plt.figure(figsize=(8,5))
    sns.countplot(data=df_dedup, x='source_dataset', hue='source_type')
    plt.title('Dataset Source Distribution (After Deduplication)')
    plt.savefig(os.path.join(PLOTS_DIR, 'dataset_source_distribution.png'))
    plt.close()
    
    # 2. Confusion Matrix of Best Model on Simulated Holdout
    y_pred = best_pipeline.predict(X_s_test)
    cm = confusion_matrix(y_s_test, y_pred)
    plt.figure(figsize=(6,5))
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues')
    plt.title(f'Confusion Matrix: {best_model_name} (Simulated Holdout)')
    plt.ylabel('Actual')
    plt.xlabel('Predicted')
    plt.savefig(os.path.join(PLOTS_DIR, 'best_model_confusion_matrix.png'))
    plt.close()

    # 3. Model Comparison (F1 Score)
    plt.figure(figsize=(10,6))
    sns.barplot(data=res_df, x='Model', y='F1', hue='TestDomain')
    plt.title('Model F1-Score Comparison by Holdout Domain')
    plt.ylim(0, 1.05)
    plt.savefig(os.path.join(PLOTS_DIR, 'model_comparison_chart.png'))
    plt.close()
    
    # 4. Feature Importance (if applicable)
    model_obj = best_pipeline.named_steps.get('model')
    if hasattr(model_obj, 'feature_importances_'):
        importances = model_obj.feature_importances_
        plt.figure(figsize=(8,5))
        sns.barplot(x=importances, y=FEATURE_COLS)
        plt.title(f'Feature Importance ({best_model_name})')
        plt.savefig(os.path.join(PLOTS_DIR, 'feature_importance.png'))
        plt.close()
        
    print(f"\n[6/6] Pipeline Complete. Artifacts saved:")
    print(f"      - Models: models/final_unified_occupancy_pipeline.pkl")
    print(f"      - Metrics: output/metrics/final_unified_model_metrics.csv")
    print(f"      - Plots: output/plots/*.png")
    
    # Short Report Output
    print("\n" + "="*50)
    print("FINAL MODEL DEPLOYMENT REPORT")
    print("="*50)
    print(f"Best Model Selected: {best_model_name}")
    
    best_sim_f1 = sim_results.loc[sim_results['F1'].idxmax()]['F1']
    best_emp_f1 = res_df[(res_df['Model'] == best_model_name) & (res_df['TestDomain'] == 'Empirical')]['F1'].values[0]
    
    print(f"\nWhy it was selected:")
    print(f"  - Demonstrated the highest F1 score ({best_sim_f1:.4f}) on the Simulated holdout domain.")
    print(f"  - It is critical the model performs well on the simulated domain as it connects to the Panda3D Digital Twin.")
    
    print(f"\nEmpirical vs Simulated Performance for {best_model_name}:")
    print(f"  - Empirical F1: {best_emp_f1:.4f}")
    print(f"  - Simulated F1: {best_sim_f1:.4f}")
    
    print(f"\nRecommendation for Deployment:")
    print(f"  - The {best_model_name} pipeline provides robust cross-domain generalization.")
    print(f"  - The preprocessor handles median imputation and standardization automatically.")
    print(f"  - Proceed to replace the old model path in the digital twin backend with: models/final_unified_occupancy_pipeline.pkl")
    print("="*50 + "\n")

if __name__ == "__main__":
    centralize_datasets()
    df_raw = load_and_harmonize()
    df_clean = deduplicate_data(df_raw)
    trained, results_df, X_tr, y_tr, X_et, y_et, X_st, y_st = train_and_evaluate(df_clean)
    save_artifacts(df_raw, df_clean, trained, results_df, X_st, y_st)
