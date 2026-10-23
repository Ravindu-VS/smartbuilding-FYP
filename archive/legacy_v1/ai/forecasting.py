import numpy as np
import pandas as pd
import logging
from sklearn.ensemble import RandomForestRegressor

logger = logging.getLogger(__name__)

class EnergyForecaster:
    """
    Energy Forecasting Module.
    Uses a Random Forest Regressor to predict next-day hourly energy profiles
    based on weather predictions, occupancy schedules, and time features.
    """
    
    def __init__(self, n_estimators=100):
        self.model = RandomForestRegressor(n_estimators=n_estimators, random_state=42)
        self.is_fitted = False
        
    def _create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create temporal features from datetime column."""
        features = pd.DataFrame()
        
        # Ensure timestamp is datetime
        timestamps = pd.to_datetime(df["timestamp"])
        
        features["hour"] = timestamps.dt.hour
        features["dayofweek"] = timestamps.dt.dayofweek
        features["is_weekend"] = features["dayofweek"].isin([5, 6]).astype(int)
        
        # Numeric inputs
        features["outdoor_temp"] = df["outdoor_temp"].astype(float)
        features["predicted_occupancy"] = df["predicted_occupancy"].astype(float)
        
        return features

    def fit(self, historical_data: pd.DataFrame):
        """
        Train the forecaster using historical metrics logs.
        
        Args:
            historical_data: pandas DataFrame containing:
                             ['timestamp', 'outdoor_temp', 'predicted_occupancy', 'energy_consumed_wh']
        """
        try:
            required_cols = ["timestamp", "outdoor_temp", "predicted_occupancy", "energy_consumed_wh"]
            if not all(col in historical_data.columns for col in required_cols):
                raise ValueError(f"Historical data must contain columns: {required_cols}")
                
            X = self._create_features(historical_data)
            y = historical_data["energy_consumed_wh"].values
            
            self.model.fit(X, y)
            self.is_fitted = True
            logger.info("✓ Energy Forecaster Random Forest model trained successfully")
        except Exception as e:
            logger.error(f"Failed to train energy forecaster: {e}")
            self.is_fitted = False
            
    def forecast_next_day(self, next_day_forecast: pd.DataFrame) -> np.ndarray:
        """
        Predict hourly energy consumption for the next 24 hours.
        
        Args:
            next_day_forecast: pandas DataFrame with 24 rows (hourly) containing:
                               ['timestamp', 'outdoor_temp', 'predicted_occupancy']
                               
        Returns:
            Numpy array of 24 predicted hourly energy consumption values (Wh).
        """
        if not self.is_fitted:
            # Return baseline mock consumption profile if not trained yet
            # Typically energy peaks around 9-11am and 2-4pm, minimums overnight
            mock_profile = np.array([
                50.0, 50.0, 50.0, 50.0, 60.0, 80.0, 150.0, 450.0,
                800.0, 950.0, 850.0, 800.0, 750.0, 850.0, 900.0, 750.0,
                550.0, 400.0, 250.0, 150.0, 100.0, 70.0, 50.0, 50.0
            ])
            logger.warning("[Warning] Forecaster not trained. Returning mock base profile.")
            return mock_profile
            
        try:
            X = self._create_features(next_day_forecast)
            predictions = self.model.predict(X)
            return predictions
        except Exception as e:
            logger.error(f"Error forecasting next day: {e}")
            return np.zeros(24)
