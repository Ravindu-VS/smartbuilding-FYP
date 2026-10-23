import os
import sys
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.building_env import BuildingEnv
from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.results_plotter import load_results, ts2xy

def train_ppo(total_timesteps=50000, model_dir="models", log_dir="output/logs", plot_dir="output/plots"):
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(plot_dir, exist_ok=True)
    
    # 1. Initialize environment
    print("Initializing Building Gymnasium Environment...")
    env = BuildingEnv(config_path="config.yaml", max_steps_per_episode=1440)
    
    # Wrap environment to monitor rewards
    env = Monitor(env, log_dir)
    
    # 2. Setup PPO Agent
    print("Setting up PPO Agent...")
    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        verbose=1,
        tensorboard_log=None
    )
    
    # 3. Train the model
    print(f"Training PPO Agent for {total_timesteps} steps...")
    model.learn(total_timesteps=total_timesteps)
    
    # 4. Save model
    model_path = os.path.join(model_dir, "ppo_building_controller")
    model.save(model_path)
    print(f"Model saved successfully to {model_path}.zip")
    
    # 5. Plot training results
    plot_training_results(log_dir, plot_dir)

def plot_training_results(log_dir, plot_dir):
    try:
        x, y = ts2xy(load_results(log_dir), 'timesteps')
        if len(x) > 0:
            # Compute moving average
            window = 5
            y_smoothed = pd.Series(y).rolling(window, min_periods=1).mean()
            
            plt.figure(figsize=(10, 5))
            plt.plot(x, y, alpha=0.3, label="Raw Episode Reward")
            plt.plot(x, y_smoothed, color="red", linewidth=2, label=f"Smoothed Reward (window={window})")
            plt.title("PPO Agent Training Convergence")
            plt.xlabel("Simulation Steps")
            plt.ylabel("Total Episode Reward")
            plt.legend()
            plt.grid(True)
            
            plot_path = os.path.join(plot_dir, "ppo_training_rewards.png")
            plt.savefig(plot_path, dpi=300, bbox_inches="tight")
            plt.close()
            print(f"[OK] Training reward curves plotted and saved to {plot_path}")
        else:
            print("No training logs found to plot.")
    except Exception as e:
        print(f"Failed to plot training logs: {e}")

if __name__ == "__main__":
    train_ppo(total_timesteps=30000) # Fast local execution run
