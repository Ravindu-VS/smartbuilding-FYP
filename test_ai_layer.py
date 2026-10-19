import unittest
import numpy as np
import pandas as pd
import os
import sys
import yaml

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.building_env import BuildingEnv
from control.ppo_controller import PPOController
from ai.maintenance import PredictiveMaintenance
from ai.forecasting import EnergyForecaster
from gymnasium.utils.env_checker import check_env

class TestAILayer(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        with open("config.yaml", "r") as f:
            cls.config = yaml.safe_load(f)

    def test_gym_env(self):
        print("Testing Gymnasium BuildingEnv...")
        env = BuildingEnv(config_path="config.yaml", max_steps_per_episode=10)
        
        # Check standard Gymnasium interface compliance
        # We check the unwrapped environment to bypass SB3 Monitor wrappers if any
        check_env(env.unwrapped, skip_render_check=True)
        
        obs, info = env.reset()
        self.assertEqual(obs.shape, env.observation_space.shape)
        
        # Run a small step loop
        for _ in range(5):
            action = env.action_space.sample()
            obs, reward, terminated, truncated, info = env.step(action)
            self.assertEqual(obs.shape, env.observation_space.shape)
            self.assertIsInstance(reward, float)
            self.assertIsInstance(terminated, bool)
            self.assertIsInstance(truncated, bool)
            self.assertIn("step_cost", info)
            
        env.close()

    def test_ppo_controller(self):
        print("Testing PPO Controller Adapter...")
        controller = PPOController(self.config)
        
        # Mock zone states matching the format expected by compute_all_actions
        zone_states = {
            "Office": {"temperature": 23.5, "illumination": 350.0, "occupancy": 2},
            "MeetingRoom": {"temperature": 21.0, "illumination": 200.0, "occupancy": 0},
            "Corridor": {"temperature": 22.0, "illumination": 100.0, "occupancy": 0}
        }
        
        actions = controller.compute_all_actions(
            zone_states=zone_states,
            outdoor_temp=18.5,
            daylight_lux=400.0
        )
        
        self.assertEqual(len(actions), 3)
        for zone_name, action in actions.items():
            self.assertHasAttr(action, "hvac_setpoint")
            self.assertHasAttr(action, "fan_on")
            self.assertHasAttr(action, "dimming_level")
            self.assertTrue(18.0 <= action.hvac_setpoint <= 26.0)
            self.assertTrue(0.0 <= action.dimming_level <= 1.0)
            
    def assertHasAttr(self, obj, attr):
        self.assertTrue(hasattr(obj, attr), f"Object missing attribute {attr}")

    def test_predictive_maintenance(self):
        print("Testing Isolation Forest Predictive Maintenance...")
        pm = PredictiveMaintenance(contamination=0.05)
        
        # Generate normal training data (temp, hum, co2, lux, hvac_w, light_w)
        # 100 samples centered around typical office operations
        np.random.seed(42)
        normal_data = np.random.normal(
            loc=[23.0, 50.0, 450.0, 300.0, 500.0, 150.0],
            scale=[0.5, 2.0, 10.0, 20.0, 50.0, 10.0],
            size=(100, 6)
        )
        pm.fit(normal_data)
        self.assertTrue(pm.is_fitted)
        
        # Test normal reading
        normal_reading = np.array([23.1, 50.5, 455.0, 295.0, 510.0, 148.0])
        is_anomaly, score = pm.detect_anomalies(normal_reading)
        self.assertFalse(is_anomaly)
        
        # Test anomalous reading (severe temperature spike, extremely high CO2)
        anomaly_reading = np.array([45.0, 95.0, 2000.0, 10.0, 9000.0, 5.0])
        is_anomaly_detected, _ = pm.detect_anomalies(anomaly_reading)
        self.assertTrue(is_anomaly_detected)
        
        # Test diagnosis
        history = [
            {"temperature": 23.0, "co2": 500.0, "hvac_action": "NORMAL", "hvac_power_w": 600.0}
            for _ in range(10)
        ]
        # Introduce stuck temperature sensor scenario
        stuck_diag = pm.diagnose_failure_mode(history)
        self.assertIn("Stuck Temperature Sensor", stuck_diag)

    def test_energy_forecaster(self):
        print("Testing Energy Forecaster Random Forest...")
        forecaster = EnergyForecaster()
        
        # Generate dummy historical dataframe
        timestamps = pd.date_range("2024-01-15 00:00:00", periods=48, freq="h")
        hist_df = pd.DataFrame({
            "timestamp": timestamps,
            "outdoor_temp": np.random.uniform(10.0, 20.0, len(timestamps)),
            "predicted_occupancy": np.random.randint(0, 15, len(timestamps)),
            "energy_consumed_wh": np.random.uniform(100.0, 800.0, len(timestamps))
        })
        
        forecaster.fit(hist_df)
        self.assertTrue(forecaster.is_fitted)
        
        # Generate next day forecast parameters
        next_day_timestamps = pd.date_range("2024-01-17 00:00:00", periods=24, freq="h")
        forecast_df = pd.DataFrame({
            "timestamp": next_day_timestamps,
            "outdoor_temp": np.random.uniform(10.0, 20.0, 24),
            "predicted_occupancy": np.random.randint(0, 15, 24)
        })
        
        predictions = forecaster.forecast_next_day(forecast_df)
        self.assertEqual(len(predictions), 24)
        self.assertTrue(all(p >= 0 for p in predictions))

if __name__ == '__main__':
    unittest.main()
