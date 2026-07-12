"""
Decision Engine - Centralized Control Decision Making

Implements pluggable control strategies for intelligent building automation.
Separates decision-making from simulation for clean architecture and ML readiness.

Phase 4: Comfort optimization, energy efficiency, and decision logging.
"""

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from enum import Enum
import math


@dataclass
class DecisionContext:
    """
    Immutable input context for decision makers.

    Contains all room state, comfort metrics, and environmental conditions
    needed to make intelligent control decisions.
    """
    # Room identity
    room_id: int
    zone_type: str  # "office", "meeting", "corridor", "storage", "lobby"

    # Temperature sensors (from Phase 3)
    temperature_zone: float  # Zone air temperature (°C)
    temperature_wall: float  # Wall surface temperature (°C)
    temperature_operative: float  # Operative temperature (°C)

    # Other sensors
    humidity: float  # Relative humidity (%)
    co2: float  # CO2 concentration (ppm)
    light_level: float  # Light level (lux)
    occupancy: float  # Occupancy fraction (0-1)

    # Comfort metrics (from Phase 3)
    pmv: float  # Predicted Mean Vote (-3 to +3)
    ppd: float  # Predicted Percentage Dissatisfied (0-100)
    comfort_index: float  # Overall comfort (0-100)

    # Environmental
    outdoor_temperature: float  # °C
    solar_irradiance: float  # W/m²
    wind_speed: float  # m/s

    # Current actuator state
    light_on: bool
    hvac_mode: str  # "off", "heating", "cooling", "fan_only", "auto"
    hvac_setpoint: float  # °C
    hvac_speed: float  # 0-1
    shading_factor: float  # 0-1

    # Time context
    hour_of_day: float  # 0-24
    is_occupied: bool  # True if occupancy > 0.1

    def __post_init__(self):
        """Validate context values."""
        assert -3.0 <= self.pmv <= 3.0, f"PMV out of range: {self.pmv}"
        assert 0 <= self.ppd <= 100, f"PPD out of range: {self.ppd}"
        assert 0 <= self.comfort_index <= 100, f"Comfort index out of range"
        assert 0 <= self.humidity <= 100, f"Humidity out of range"
        assert 0 <= self.occupancy <= 100.0, f"Occupancy out of range"
        assert 0 <= self.shading_factor <= 1.0, f"Shading factor out of range"


@dataclass
class DecisionOutput:
    """
    Standard output from control strategies.

    Contains all actuator commands and reasoning for decision.
    """
    light_on: bool = False
    hvac_mode: str = "off"  # "off", "heating", "cooling", "fan_only", "auto"
    hvac_setpoint: float = 21.0  # Target temperature (°C)
    hvac_speed: float = 0.0  # Compressor/fan speed (0-1)
    shading_factor: float = 0.0  # Window shading (0-1, 0=open, 1=fully shaded)
    light_threshold: float = 400.0  # Configurable lux threshold used for decision
    decision_reason: str = ""  # Brief explanation of decision

    def validate(self) -> bool:
        """Validate output values."""
        # Sanitize internal physics/ML drift overflows
        self.hvac_speed = max(0.0, min(1.0, float(self.hvac_speed)))
        self.shading_factor = max(0.0, min(1.0, float(self.shading_factor)))
        
        assert isinstance(self.light_on, bool), "light_on must be bool"
        assert self.hvac_mode in ["off", "heating", "cooling", "fan_only", "auto"], \
            f"Invalid HVAC mode: {self.hvac_mode}"
        assert 15.0 <= self.hvac_setpoint <= 28.0, \
            f"HVAC setpoint out of range: {self.hvac_setpoint}"
        assert 0.0 <= self.hvac_speed <= 1.0, \
            f"HVAC speed out of range: {self.hvac_speed}"
        assert 0.0 <= self.shading_factor <= 1.0, \
            f"Shading factor out of range: {self.shading_factor}"
        assert self.light_threshold >= 0.0, \
            f"Light threshold must be positive: {self.light_threshold}"
        return True


class ControlStrategy(ABC):
    """
    Abstract base class for control strategies.

    Each strategy implements a specific control philosophy
    (rule-based, comfort-optimized, energy-optimized, etc.)
    """

    @abstractmethod
    def make_decision(self, context: DecisionContext) -> DecisionOutput:
        """
        Make control decision based on context.

        Args:
            context: Room state and environment

        Returns:
            DecisionOutput with actuator commands
        """
        pass

    @abstractmethod
    def name(self) -> str:
        """Get strategy name for logging."""
        pass


class MLControlStrategy(ControlStrategy):
    """
    ML-based control strategy using pluggable model interface.

    Phase 6: Wraps MLModelInterface to work with DecisionEngine.
    Supports scikit-learn, PyTorch, and other ML models.
    Maintains backward compatibility with ControlStrategy interface.
    """

    def __init__(self, ml_model):
        """
        Initialize ML control strategy.

        Args:
            ml_model: MLModelInterface instance (sklearn, torch, or rules adapter)
        """
        self.ml_model = ml_model

    def make_decision(self, context: DecisionContext) -> DecisionOutput:
        """
        Make decision using ML model.

        Args:
            context: Room state and environment

        Returns:
            DecisionOutput from model prediction
        """
        from decisions.prediction_schema import ActionDecoder

        # Get model prediction
        prediction = self.ml_model.predict(context)

        # Decode prediction to DecisionOutput
        decision = ActionDecoder.decode(prediction, context_reason="")

        return decision

    def name(self) -> str:
        """Get strategy name from model."""
        return f"ML ({self.ml_model.get_model_name()})"


class DecisionEngine:
    """
    Centralized decision-making engine.

    Loads and executes control strategies, coordinates multi-zone decisions,
    and logs all decisions for analysis and ML training.
    """

    def __init__(self, config: dict = None):
        """
        Initialize decision engine.

        Args:
            config: Configuration with strategy/model selection
                   Format:
                   {
                       "control_strategy": "rule|comfort|energy|hybrid|ml",
                       "ml_model": MLModelInterface (if strategy=="ml"),
                       "comfort_weight": 0.6 (for hybrid),
                       "energy_weight": 0.4 (for hybrid),
                       "decision_logging": False,
                   }
        """
        self.config = config or {}

        # Load strategy from config
        strategy_name = self.config.get("control_strategy", "comfort").lower()
        comfort_weight = self.config.get("comfort_weight", 0.6)
        energy_weight = self.config.get("energy_weight", 0.4)

        # Import strategies (avoid circular imports)
        from decisions.strategies import (
            RuleBasedController,
            ComfortOptimizer,
            EnergyOptimizer,
            HybridController
        )

        # Check if using ML model
        if strategy_name == "ml":
            if "ml_model" not in self.config:
                raise ValueError(
                    "ML strategy selected but no ml_model provided in config"
                )
            self.strategy = MLControlStrategy(self.config["ml_model"])
        else:
            # Traditional rule-based strategies
            strategies = {
                "rule": RuleBasedController(),
                "comfort": ComfortOptimizer(),
                "energy": EnergyOptimizer(),
                "hybrid": HybridController(comfort_weight, energy_weight),
            }

            if strategy_name not in strategies:
                raise ValueError(f"Unknown strategy: {strategy_name}")

            self.strategy = strategies[strategy_name]

        self.strategy_name = strategy_name

        # Decision logging
        self.enable_logging = self.config.get("decision_logging", False)
        self.decision_history: Dict[int, List] = {}

        print(f"[OK] Decision Engine initialized")
        print(f"  Strategy: {self.strategy.name()}")
        if self.strategy_name == "hybrid":
            print(f"  Comfort weight: {comfort_weight}, Energy weight: {energy_weight}")
        elif self.strategy_name == "ml":
            model_info = self.config["ml_model"].get_model_info()
            print(f"  Model: {model_info.get('model_name', 'Unknown')}")
            print(f"  Type: {model_info.get('type', 'Unknown')}")

    def make_decision(self, context: DecisionContext) -> DecisionOutput:
        """
        Make control decision for a room.

        Args:
            context: Room state and environment

        Returns:
            DecisionOutput with actuator commands
        """
        # Get decision from strategy
        decision = self.strategy.make_decision(context)

        # Validate output
        decision.validate()

        # Log if enabled
        if self.enable_logging:
            if context.room_id not in self.decision_history:
                self.decision_history[context.room_id] = []

            self.decision_history[context.room_id].append({
                "context": context,
                "decision": decision,
            })

        return decision

    def get_history(self, room_id: int) -> List:
        """Get decision history for a room."""
        return self.decision_history.get(room_id, [])

    def get_strategy_name(self) -> str:
        """Get name of active strategy."""
        return self.strategy.name()
