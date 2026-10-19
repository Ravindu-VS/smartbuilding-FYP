"""
Energy Service — Current consumption, history, and forecasting.
Wraps the existing EnergyForecaster and StateManager energy metrics.
"""
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class EnergyService:
    """
    Service layer for energy consumption data and forecasting.
    """

    def __init__(self, state_manager=None, db_persistence=None):
        self.state_manager = state_manager
        self.db = db_persistence
        self._forecaster = None
        self._load_forecaster()

    def _load_forecaster(self):
        """Load the energy forecasting model."""
        try:
            from ai.forecasting import EnergyForecaster
            self._forecaster = EnergyForecaster(n_estimators=100)
            logger.info("✓ Energy Forecaster initialized")
        except Exception as e:
            logger.warning(f"Energy Forecaster not available: {e}")

    def get_current_energy(self) -> Dict[str, Any]:
        """Get current real-time energy consumption snapshot."""
        now = datetime.now()

        if self.state_manager:
            try:
                summary = self.state_manager.get_system_summary()
                return {
                    "timestamp": now.isoformat(),
                    "total_power_watts": summary.get("total_power_watts", 0.0),
                    "hvac_power_watts": summary.get("hvac_power_watts", 0.0),
                    "lighting_power_watts": summary.get("lighting_power_watts", 0.0),
                    "plug_power_watts": summary.get("plug_power_watts", 0.0),
                    "total_cumulative_energy_wh": summary.get("total_cumulative_energy_wh", 0.0),
                    "baseline_energy_wh": summary.get("baseline_energy_wh", 0.0),
                    "ai_energy_wh": summary.get("ai_energy_wh", 0.0),
                    "energy_saved_wh": summary.get("energy_saved_wh", 0.0),
                    "percentage_saved": summary.get("percentage_saved", 0.0),
                    "comfort_score": summary.get("comfort_score", 0.0),
                }
            except Exception as e:
                logger.error(f"Error retrieving current energy: {e}")

        # Return default values when state manager unavailable
        return {
            "timestamp": now.isoformat(),
            "total_power_watts": 0.0,
            "hvac_power_watts": 0.0,
            "lighting_power_watts": 0.0,
            "plug_power_watts": 0.0,
            "total_cumulative_energy_wh": 0.0,
            "baseline_energy_wh": 0.0,
            "ai_energy_wh": 0.0,
            "energy_saved_wh": 0.0,
            "percentage_saved": 0.0,
            "comfort_score": 0.0,
        }

    def get_energy_history(self, hours: float = 24.0) -> Dict[str, Any]:
        """
        Get historical energy consumption data.

        Args:
            hours: Number of hours of history to retrieve
        """
        entries = []

        if self.db:
            try:
                records = self.db.get_energy_history(hours=hours)
                for rec in records:
                    entries.append({
                        "timestamp": rec.get("timestamp", ""),
                        "power_watts": rec.get("power_watts", 0.0),
                        "energy_wh": rec.get("energy_wh", 0.0),
                        "zone": rec.get("zone"),
                    })
            except Exception as e:
                logger.debug(f"Energy history retrieval: {e}")

        # If no DB data, generate from state manager history buffers
        if not entries and self.state_manager:
            try:
                history = self.state_manager.get_history_buffer()
                if history:
                    for entry in history[-100:]:  # Last 100 entries
                        entries.append({
                            "timestamp": entry.get("timestamp", ""),
                            "power_watts": entry.get("total_power_watts", 0.0),
                            "energy_wh": entry.get("total_cumulative_energy_wh", 0.0),
                            "zone": None,
                        })
            except Exception as e:
                logger.debug(f"History buffer: {e}")

        return {
            "entries": entries,
            "total_records": len(entries),
            "time_range_hours": hours,
        }

    def get_energy_prediction(self) -> Dict[str, Any]:
        """
        Generate 24-hour energy forecast using the Random Forest model.
        """
        now = datetime.now()
        predictions = []

        if self._forecaster and self._forecaster.is_fitted:
            try:
                import pandas as pd
                import numpy as np

                # Create feature matrix for next 24 hours
                future_hours = []
                for h in range(24):
                    future_time = now + timedelta(hours=h)
                    future_hours.append({
                        "timestamp": future_time,
                        "outdoor_temp": 28.0 + 5.0 * np.sin(2 * np.pi * (h - 14) / 24),
                        "predicted_occupancy": 0.8 if 8 <= (now.hour + h) % 24 <= 18 else 0.1,
                    })

                df = pd.DataFrame(future_hours)
                predicted = self._forecaster.predict(df)

                for i, wh in enumerate(predicted):
                    predictions.append({
                        "hour": i,
                        "predicted_wh": float(wh),
                    })
            except Exception as e:
                logger.warning(f"Energy prediction failed: {e}")

        # Fallback: simple sinusoidal model
        if not predictions:
            import math
            for h in range(24):
                hour = (now.hour + h) % 24
                base = 3000 + 2000 * math.sin(math.pi * max(0, hour - 6) / 12) if 6 <= hour <= 18 else 1500
                predictions.append({
                    "hour": h,
                    "predicted_wh": round(base + (h * 50), 1),
                })

        return {
            "timestamp": now.isoformat(),
            "predictions": predictions,
            "model_type": "RandomForest" if (self._forecaster and self._forecaster.is_fitted) else "Heuristic",
            "confidence": 0.85 if (self._forecaster and self._forecaster.is_fitted) else 0.5,
        }
