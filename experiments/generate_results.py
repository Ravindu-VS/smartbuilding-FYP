"""
Generate Experiment Results

Parses CSV outputs from ExperimentRunner and produces
publication-ready matplotlib charts.
"""

import os
import sys
import glob
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output", "experiments")

# Set publication style
plt.style.use('seaborn-v0_8-whitegrid')
sns.set_context("paper", font_scale=1.5)

def plot_experiment_a(summary_file):
    if not os.path.exists(summary_file):
        return
        
    df = pd.read_csv(summary_file)
    
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    
    # 1. Energy Comparison
    sns.barplot(data=df, x="Controller", y="Energy (kWh)", ax=axes[0], palette="Blues_d")
    axes[0].set_title("Total Energy Consumption (24h)")
    axes[0].set_ylabel("Energy (kWh)")
    for i, p in enumerate(axes[0].patches):
        axes[0].annotate(f"{p.get_height():.1f}", 
                        (p.get_x() + p.get_width() / 2., p.get_height()), 
                        ha='center', va='bottom')

    # 2. HVAC Runtime
    sns.barplot(data=df, x="Controller", y="HVAC Runtime %", ax=axes[1], palette="Oranges_d")
    axes[1].set_title("HVAC Active Runtime (%)")
    axes[1].set_ylabel("Percentage (%)")
    axes[1].set_ylim(0, 100)
    for i, p in enumerate(axes[1].patches):
        axes[1].annotate(f"{p.get_height():.1f}%", 
                        (p.get_x() + p.get_width() / 2., p.get_height()), 
                        ha='center', va='bottom')
                        
    # 3. Comfort Score
    sns.barplot(data=df, x="Controller", y="Comfort Score", ax=axes[2], palette="Greens_d")
    axes[2].set_title("Average Comfort Score")
    axes[2].set_ylabel("Score (0-1)")
    axes[2].set_ylim(0, 1.1)
    for i, p in enumerate(axes[2].patches):
        axes[2].annotate(f"{p.get_height():.2f}", 
                        (p.get_x() + p.get_width() / 2., p.get_height()), 
                        ha='center', va='bottom')
                        
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "exp_a_baseline_vs_ai.png"), dpi=300)
    plt.close()

def plot_experiment_b(summary_file):
    if not os.path.exists(summary_file):
        return
        
    df = pd.read_csv(summary_file)
    df_melt = pd.melt(df, id_vars=["Controller"], 
                     value_vars=["Accuracy", "Precision", "Recall", "F1 Score"],
                     var_name="Metric", value_name="Score")
                     
    plt.figure(figsize=(12, 7))
    sns.barplot(data=df_melt, x="Metric", y="Score", hue="Controller", palette="viridis")
    plt.title("Occupancy Detection Model Comparison")
    plt.ylim(0, 1.1)
    plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "exp_b_model_comparison.png"), dpi=300)
    plt.close()

def plot_experiment_c(summary_file):
    if not os.path.exists(summary_file):
        return
        
    df = pd.read_csv(summary_file)
    
    # Plot Energy vs Comfort tradeoff
    plt.figure(figsize=(10, 8))
    
    # Define colors
    colors = ['#e74c3c', '#3498db', '#f1c40f', '#2ecc71', '#9b59b6']
    
    for i, row in df.iterrows():
        plt.scatter(row["Energy (kWh)"], row["Comfort Score"], 
                   s=300, c=colors[i % len(colors)], label=row["Controller"], alpha=0.8)
                   
        # Add labels
        plt.annotate(row["Controller"], 
                    (row["Energy (kWh)"], row["Comfort Score"]),
                    xytext=(10, -10), textcoords='offset points',
                    fontsize=12)
                    
    plt.title("Controller Strategy: Energy vs. Comfort Trade-off")
    plt.xlabel("Total Energy Consumption (kWh) - Lower is better")
    plt.ylabel("Average Comfort Score - Higher is better")
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "exp_c_energy_comfort_tradeoff.png"), dpi=300)
    plt.close()

def plot_timeseries():
    # Find all timeseries CSVs
    ts_files = glob.glob(os.path.join(OUTPUT_DIR, "*_timeseries.csv"))
    if not ts_files:
        return
        
    # Group by experiment
    exp_groups = {}
    for f in ts_files:
        filename = os.path.basename(f)
        if filename.startswith("experiment_a"):
            exp_groups.setdefault("Exp A", []).append(f)
        elif filename.startswith("experiment_c"):
            exp_groups.setdefault("Exp C", []).append(f)
            
    for exp_name, files in exp_groups.items():
        plt.figure(figsize=(14, 8))
        
        for f in files:
            # Extract controller name from filename
            ctrl_name = os.path.basename(f).split("_timeseries")[0].replace("experiment_a_baseline_vs_ai_", "").replace("experiment_c_controller_comparison_", "").replace("_", " ").title()
            
            df = pd.read_csv(f)
            plt.plot(df["hour"], df["total_power_w"] / 1000, label=ctrl_name, linewidth=2)
            
        plt.title(f"{exp_name}: Building Power Profile Over 24 Hours")
        plt.xlabel("Hour of Day (0-24)")
        plt.ylabel("Total Power (kW)")
        plt.xlim(0, 24)
        plt.xticks(range(0, 25, 2))
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(OUTPUT_DIR, f"{exp_name.replace(' ', '_').lower()}_power_profile.png"), dpi=300)
        plt.close()

if __name__ == "__main__":
    print("Generating charts...")
    plot_experiment_a(os.path.join(OUTPUT_DIR, "experiment_a_baseline_vs_ai_summary.csv"))
    plot_experiment_b(os.path.join(OUTPUT_DIR, "experiment_b_model_comparison_summary.csv"))
    plot_experiment_c(os.path.join(OUTPUT_DIR, "experiment_c_controller_comparison_summary.csv"))
    plot_timeseries()
    print(f"Charts saved to {OUTPUT_DIR}")
