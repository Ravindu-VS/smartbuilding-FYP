import os
import glob
import pandas as pd
import numpy as np

KAGGLE_DIR = os.path.join("data", "raw", "kaggle_occupancy")
SIMULATED_DATA_PATH = os.path.join("data", "raw", "simulated_occupancy_data.csv")
FEATURES = ['Temperature', 'Humidity', 'Light', 'CO2', 'HumidityRatio']
TARGET = 'Occupancy'

def load_and_standardize(file_paths: list, source_name: str) -> pd.DataFrame:
    if not file_paths:
        return pd.DataFrame()
        
    df = pd.concat([pd.read_csv(f) for f in file_paths], ignore_index=True)
    
    target_col = TARGET
    if TARGET not in df.columns:
        possible_targets = ['occupancy', 'target', 'Target', 'Room_Occupancy_Count', 'true_occupancy']
        for pt in possible_targets:
            if pt in df.columns:
                target_col = pt
                break
                
    if target_col in df.columns:
        df['Occupancy_Binary'] = df[target_col].apply(lambda x: 1 if float(x) > 0 else 0)
    else:
        df['Occupancy_Binary'] = 0
        
    lower_cols = {c.lower(): c for c in df.columns}
    for feature in FEATURES:
        if feature not in df.columns and feature.lower() in lower_cols:
            df[feature] = df[lower_cols[feature.lower()]].astype(np.float64)
        elif feature not in df.columns:
            df[feature] = 0.0
        else:
            df[feature] = df[feature].astype(np.float64)
            
    return df[FEATURES + ['Occupancy_Binary']].copy()

def main():
    # 1. Kaggle
    kaggle_csv = glob.glob(os.path.join(KAGGLE_DIR, "*.csv"))
    if not kaggle_csv:
        kaggle_csv = glob.glob(os.path.join("Dataset", "Kaggle_Room_Occupancy", "*.csv")) + \
                     glob.glob(os.path.join("Dataset", "Kaggle_Room_Occupancy", "*.txt"))
    df_kaggle = load_and_standardize(kaggle_csv, "Kaggle Dataset")
    
    # 2. UCI
    uci_files = glob.glob(os.path.join("Dataset", "UCI", "occupancy+detection", "*.txt")) + \
                glob.glob(os.path.join("Dataset", "UCI", "occupancy+detection", "*.csv"))
    df_uci = load_and_standardize(uci_files, "UCI Dataset")
    
    # 3. Simulated
    sim_paths = [SIMULATED_DATA_PATH, os.path.join("data", "raw", "simulated_occupancy_data_baseline.csv")]
    df_sim = pd.DataFrame()
    for sp in sim_paths:
        if os.path.exists(sp):
            df_sim = load_and_standardize([sp], "Simulated Data")
            break

    datasets = {
        "Kaggle Dataset": df_kaggle,
        "UCI Dataset": df_uci,
        "Simulated Dataset": df_sim
    }

    # Write Markdown Summary
    with open('dataset_comparison.md', 'w') as f:
        f.write("# Dataset Comparison Summary\n\n")
        f.write("| Dataset | Total Records | Occupied Rate | Temp (Mean) | Humidity (Mean) | CO2 (Mean) | Light (Mean) | HumidityRatio (Mean) |\n")
        f.write("|---------|---------------|---------------|-------------|-----------------|------------|--------------|----------------------|\n")

        for name, df in datasets.items():
            if df.empty:
                f.write(f"| {name} | NO DATA | - | - | - | - | - | - |\n")
                continue
                
            occupancy_rate = df['Occupancy_Binary'].mean() * 100
            t_mean = df['Temperature'].mean()
            h_mean = df['Humidity'].mean()
            co2_mean = df['CO2'].mean()
            l_mean = df['Light'].mean()
            hr_mean = df['HumidityRatio'].mean()
            f.write(f"| {name} | {len(df):,} | {occupancy_rate:.1f}% | {t_mean:.2f} | {h_mean:.2f} | {co2_mean:.2f} | {l_mean:.2f} | {hr_mean:.6f} |\n")

    # Write Detailed Text Summary
    with open('dataset_comparison.txt', 'w', encoding='utf-8') as f:
        f.write("="*64 + "\n")
        f.write("DATASET COMPARISON SUMMARY\n")
        f.write("="*64 + "\n\n")
        
        for name, df in datasets.items():
            f.write(f"--- {name.upper()} ---\n")
            if df.empty:
                f.write("NO DATA\n\n")
                continue
                
            occupancy_rate = df['Occupancy_Binary'].mean() * 100
            f.write(f"Total Records: {len(df):,}\n")
            f.write(f"Occupied Rate: {occupancy_rate:.1f}%\n")
            f.write("Feature Means:\n")
            
            for feature in FEATURES:
                mean_val = df[feature].mean()
                std_val = df[feature].std()
                if feature == 'HumidityRatio':
                    f.write(f"  - {feature:<15}: {mean_val:>9.6f} (± {std_val:>9.6f})\n")
                else:
                    f.write(f"  - {feature:<15}: {mean_val:>9.2f} (± {std_val:>9.2f})\n")
            f.write("\n")

if __name__ == "__main__":
    main()

