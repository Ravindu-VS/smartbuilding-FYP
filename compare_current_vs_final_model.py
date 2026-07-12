import os
import joblib
import pandas as pd
import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

def load_data(path, is_empirical=False):
    if os.path.isdir(path):
        dfs = []
        for file in os.listdir(path):
            if not file.endswith('.txt') and not file.endswith('.csv'): continue
            try:
                df = pd.read_csv(os.path.join(path, file))
                features = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio', 'Occupancy']
                if all(col in df.columns for col in features):
                    dfs.append(df[features])
            except Exception:
                pass
        df = pd.concat(dfs, ignore_index=True)
    else:
        df = pd.read_csv(path)
        features = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio', 'Occupancy']
        df = df[features]
        
    if is_empirical:
        df = df.drop_duplicates()
        
    return df.dropna()

def calculate_metrics(y_true, y_pred, y_prob):
    return {
        'Accuracy': accuracy_score(y_true, y_pred),
        'Precision': precision_score(y_true, y_pred, zero_division=0),
        'Recall': recall_score(y_true, y_pred, zero_division=0),
        'F1-score': f1_score(y_true, y_pred, zero_division=0),
        'ROC-AUC': roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else np.nan
    }

def main():
    print("Loading models...")
    try:
        current_model = joblib.load('models/domain_adapted_occupancy_pipeline.pkl')
        current_model_name = "Currently Deployed (domain_adapted_occupancy_pipeline)"
    except Exception as e:
        print("Could not load pipeline, trying model+scaler...")
        current_model = joblib.load('models/domain_adapted_kaggle_occupancy_model.pkl')
        # Simplified assumption: If we fall back, we will just use the model object directly, 
        # but evaluation might fail if it needs scaling. Let's stick with the pipeline.
        raise ValueError("Requires a deployed pipeline to compare against.")

    final_model = joblib.load('models/final_unified_occupancy_pipeline.pkl')
    
    print("Loading test datasets...")
    # Empirical test data
    kaggle_df = load_data('Dataset/Unified/Kaggle', is_empirical=True)
    uci_df = load_data('Dataset/Unified/UCI', is_empirical=True)
    empirical_df = pd.concat([kaggle_df, uci_df]).drop_duplicates()
    
    # Simulated test data
    simulated_df = load_data('data/raw/simulated_occupancy_data.csv')
    
    # Noisy simulated test data
    noisy_simulated_df = load_data('data/raw/simulated_occupancy_data_baseline.csv')

    datasets = {
        'Empirical Data': empirical_df,
        'Simulated Data': simulated_df,
        'Noisy Simulated Data': noisy_simulated_df
    }

    results = []

    for model_name, model in [("Current Deployed Model", current_model), ("Final Unified Model", final_model)]:
        for ds_name, df in datasets.items():
            X = df[['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']]
            y = df['Occupancy']
            
            y_pred = model.predict(X)
            y_prob = model.predict_proba(X)[:, 1] if hasattr(model, 'predict_proba') else [0]*len(y)
            
            metrics = calculate_metrics(y, y_pred, y_prob)
            metrics['Model'] = model_name
            metrics['Dataset'] = ds_name
            results.append(metrics)
            
    results_df = pd.DataFrame(results)
    
    # Format a table
    metrics_cols = ['Accuracy', 'Precision', 'Recall', 'F1-score', 'ROC-AUC']
    
    output_lines = []
    output_lines.append("="*80)
    output_lines.append(" MODEL COMPARISON REPORT ")
    output_lines.append("="*80 + "\n")
    
    for ds_name in datasets.keys():
        output_lines.append(f"--- Evaluation on: {ds_name} ---")
        ds_results = results_df[results_df['Dataset'] == ds_name]
        
        # Build tabular
        output_lines.append(f"{'Metric':<15} | {'Current Deployed Model':<25} | {'Final Unified Model':<25}")
        output_lines.append("-" * 70)
        
        for metric in metrics_cols:
            curr_val = ds_results[ds_results['Model'] == 'Current Deployed Model'][metric].values[0]
            fin_val = ds_results[ds_results['Model'] == 'Final Unified Model'][metric].values[0]
            output_lines.append(f"{metric:<15} | {curr_val:<25.4f} | {fin_val:<25.4f}")
        output_lines.append("\n")

    # Recommendation
    final_sim_f1 = results_df[(results_df['Model'] == 'Final Unified Model') & (results_df['Dataset'] == 'Simulated Data')]['F1-score'].values[0]
    curr_sim_f1 = results_df[(results_df['Model'] == 'Current Deployed Model') & (results_df['Dataset'] == 'Simulated Data')]['F1-score'].values[0]
    
    final_emp_f1 = results_df[(results_df['Model'] == 'Final Unified Model') & (results_df['Dataset'] == 'Empirical Data')]['F1-score'].values[0]
    curr_emp_f1 = results_df[(results_df['Model'] == 'Current Deployed Model') & (results_df['Dataset'] == 'Empirical Data')]['F1-score'].values[0]
    
    output_lines.append("="*80)
    output_lines.append(" RECOMMENDATION ")
    output_lines.append("="*80)
    
    replace = final_sim_f1 > curr_sim_f1 or (final_sim_f1 >= curr_sim_f1 and final_emp_f1 > curr_emp_f1)
    
    if replace:
        output_lines.append("✅ RECOMMENDATION: REPLACE the current live model with the Final Unified Model.")
        output_lines.append("Reasoning:")
        output_lines.append(f"The Final Unified Model shows superior or equal performance, particularly on the ")
        output_lines.append(f"Simulated Data F1-score ({final_sim_f1:.4f} vs {curr_sim_f1:.4f}) and Empirical F1-score ({final_emp_f1:.4f} vs {curr_emp_f1:.4f}).")
    else:
        output_lines.append("❌ RECOMMENDATION: DO NOT replace the current live model.")
        output_lines.append("Reasoning:")
        output_lines.append(f"The Current Deployed Model still outperforms the Final Unified Model on key simulated data metrics ")
        output_lines.append(f"(Current F1: {curr_sim_f1:.4f} vs Final F1: {final_sim_f1:.4f}).")
        
    output_text = "\n".join(output_lines)
    print(output_text)
    
    os.makedirs('output/metrics', exist_ok=True)
    with open('output/metrics/model_comparison.txt', 'w', encoding='utf-8') as f:
        f.write(output_text)
        
    print("\nResults saved to output/metrics/model_comparison.txt")

if __name__ == "__main__":
    main()
