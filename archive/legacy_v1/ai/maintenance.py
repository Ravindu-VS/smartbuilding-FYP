import numpy as np
import logging
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

class PredictiveMaintenance:
    """
    Predictive Maintenance Module.
    Uses Isolation Forest and heuristic checks to detect building system anomalies:
    - Sensor drift / stuck sensors
    - HVAC performance degradation
    - Power consumption spikes
    """
    
    def __init__(self, contamination=0.02):
        self.model = IsolationForest(contamination=contamination, random_state=42)
        self.is_fitted = False
        
    def fit(self, training_data: np.ndarray):
        """
        Fit the Isolation Forest model on normal historical operating data.
        
        Args:
            training_data: numpy array of shape (N, D) where columns are:
                           [temperature, humidity, co2, lux, hvac_power_w, lighting_power_w]
        """
        try:
            self.model.fit(training_data)
            self.is_fitted = True
            logger.info("✓ Predictive Maintenance Isolation Forest model fitted successfully")
        except Exception as e:
            logger.error(f"Failed to fit isolation forest: {e}")
            self.is_fitted = False
            
    def detect_anomalies(self, current_reading: np.ndarray) -> tuple:
        """
        Score a single telemetry reading using Isolation Forest.
        
        Args:
            current_reading: 1D array [temp, hum, co2, lux, hvac_w, light_w]
            
        Returns:
            Tuple of (is_anomaly: bool, anomaly_score: float)
        """
        if not self.is_fitted:
            # Fallback if model not trained
            return False, 0.0
            
        reading_reshaped = current_reading.reshape(1, -1)
        prediction = self.model.predict(reading_reshaped)[0]
        score = float(self.model.score_samples(reading_reshaped)[0])
        
        # Isolation Forest outputs -1 for anomalies, 1 for normal
        is_anomaly = prediction == -1
        
        return is_anomaly, score

    def diagnose_failure_mode(self, history: list) -> str:
        """
        Diagnose the physical cause of anomalies by inspecting recent room history.
        
        Args:
            history: List of dicts containing recent room states (sensor telemetry and actions)
            
        Returns:
            String description of the failure mode, or "Normal"
        """
        if len(history) < 10:
            return "Insufficient history for diagnosis"
            
        temps = [r.get("temperature", 22.0) for r in history]
        hvac_modes = [r.get("hvac_action", "ECO") for r in history]
        co2_levels = [r.get("co2", 400.0) for r in history]
        hvac_powers = [r.get("hvac_power_w", 0.0) for r in history]
        
        # 1. Diagnose Stuck Temperature Sensor
        # If temperature variance is extremely low but HVAC or environment is active
        temp_var = np.var(temps)
        if temp_var < 1e-4:
            return "ANOMALY: Stuck Temperature Sensor detected (zero temperature variance)"
            
        # 2. Diagnose HVAC Efficiency Decay (Struggle / No cooling effect)
        # If HVAC is running at NORMAL capacity (high energy), but temperature is rising
        # (Assuming cooling mode is active in warm season)
        if hvac_modes[-1] == "NORMAL" and len(temps) >= 5:
            temp_trend = temps[-1] - temps[-5]
            if temp_trend > 0.8 and sum(hvac_powers[-5:]) > 2000.0:
                return "ANOMALY: HVAC Performance Degradation detected (temperature rising despite high cooling load)"
                
        # 3. Diagnose Ventilation / Fresh Air system failure
        # If CO2 builds up and remains high despite HVAC fan running
        if co2_levels[-1] > 1200.0 and all(c > 1000.0 for c in co2_levels[-5:]):
            return "ANOMALY: Ventilation System Failure / Air Stagnation detected (excessive CO2 levels)"
            
        return "Normal"
