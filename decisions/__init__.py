"""
Decision Engine Module

Centralized control decision-making for intelligent building automation.

Exports:
- DecisionEngine: Main orchestrator
- ControlStrategy: Base class for strategies
- MLControlStrategy: ML model-based control (Phase 6)
- DecisionContext: Input context dataclass
- DecisionOutput: Output commands dataclass

ML Model Integration (Phase 6):
- MLModelInterface: Abstract base for ML models
- SklearnModelAdapter: scikit-learn wrapper
- TorchModelAdapter: PyTorch wrapper
- RulesAdapter: Rule-based as ML interface
- ModelFactory: Create models from config
- FeatureSchema: Standard feature definitions
- FeatureExtractor: Extract features from context
- ModelPrediction: Standard ML outputs
- ActionDecoder: Convert predictions to decisions
"""

from decisions.controller import (
    DecisionEngine,
    ControlStrategy,
    MLControlStrategy,
    DecisionContext,
    DecisionOutput,
)

from decisions.model_interface import (
    MLModelInterface,
    SklearnModelAdapter,
    TorchModelAdapter,
    RulesAdapter,
    ModelFactory,
)

from decisions.feature_schema import (
    FeatureSchema,
    FeatureExtractor,
    FeatureDefinition,
)

from decisions.prediction_schema import (
    ModelPrediction,
    ActionDecoder,
    PredictionLogger,
)

__all__ = [
    # Core
    "DecisionEngine",
    "ControlStrategy",
    "MLControlStrategy",
    "DecisionContext",
    "DecisionOutput",
    # ML Models
    "MLModelInterface",
    "SklearnModelAdapter",
    "TorchModelAdapter",
    "RulesAdapter",
    "ModelFactory",
    # Features
    "FeatureSchema",
    "FeatureExtractor",
    "FeatureDefinition",
    # Predictions
    "ModelPrediction",
    "ActionDecoder",
    "PredictionLogger",
]

