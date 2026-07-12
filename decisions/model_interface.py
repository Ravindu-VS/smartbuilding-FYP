"""
ML Model Interface - Abstraction for Pluggable ML Models

Defines standard interface for ML decision models.
Supports scikit-learn, PyTorch, and other frameworks through adapters.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple
import numpy as np

from decisions.controller import DecisionContext, DecisionOutput
from decisions.feature_schema import FeatureExtractor, FeatureSchema
from decisions.prediction_schema import ModelPrediction, ActionDecoder


class MLModelInterface(ABC):
    """
    Abstract base class for ML decision models.

    Any ML framework can be integrated by implementing this interface.
    Used by MLControlStrategy to make decisions.
    """

    @abstractmethod
    def predict(self, context: DecisionContext) -> ModelPrediction:
        """
        Make prediction based on context.

        Args:
            context: Decision context from simulation

        Returns:
            ModelPrediction with raw model outputs
        """
        pass

    @abstractmethod
    def predict_batch(self, contexts: list[DecisionContext]) -> np.ndarray:
        """
        Make batch predictions (for efficiency).

        Args:
            contexts: List of decision contexts

        Returns:
            Array of shape (batch_size, 8) with predictions
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get human-readable model name."""
        pass

    @abstractmethod
    def is_trained(self) -> bool:
        """Check if model is trained and ready for predictions."""
        pass

    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """Get model metadata (version, architecture, etc.)."""
        pass


class SklearnModelAdapter(MLModelInterface):
    """
    Adapter for scikit-learn ML models.

    Wraps trained sklearn models to work with the ML interface.
    Supports any sklearn model with predict() method.
    """

    def __init__(self, sklearn_model, model_name: str = "Sklearn Model"):
        """
        Initialize sklearn adapter.

        Args:
            sklearn_model: Trained sklearn model (RandomForest, SVM, etc.)
            model_name: Human-readable name
        """
        self.model = sklearn_model
        self.model_name = model_name
        self._trained = True  # Assume pre-trained

    def predict(self, context: DecisionContext) -> ModelPrediction:
        """Make single prediction from context."""
        features = FeatureExtractor.extract_array(context).reshape(1, -1)
        raw_output = self.model.predict(features)[0]

        # Adapt output to ModelPrediction format (8 outputs expected)
        if len(raw_output) >= 8:
            return ModelPrediction(
                light_probability=float(np.clip(raw_output[0], 0, 1)),
                hvac_heating_prob=float(np.clip(raw_output[1], 0, 1)),
                hvac_cooling_prob=float(np.clip(raw_output[2], 0, 1)),
                hvac_off_prob=float(np.clip(raw_output[3], 0, 1)),
                hvac_speed=float(np.clip(raw_output[4], 0, 1)),
                hvac_setpoint=float(np.clip(raw_output[5], 0, 1)),
                shading_factor=float(np.clip(raw_output[6], 0, 1)),
                confidence=float(np.clip(raw_output[7], 0, 1))
                if len(raw_output) > 7
                else 0.8,
            )
        else:
            raise ValueError(f"Model expected 8 outputs, got {len(raw_output)}")

    def predict_batch(self, contexts: list[DecisionContext]) -> np.ndarray:
        """Make batch predictions."""
        features = FeatureExtractor.extract_batch(contexts)
        return self.model.predict(features)

    def get_model_name(self) -> str:
        """Get model name."""
        return self.model_name

    def is_trained(self) -> bool:
        """Check if model is trained."""
        return self._trained

    def get_model_info(self) -> Dict[str, Any]:
        """Get model metadata."""
        return {
            "type": "sklearn",
            "model_class": type(self.model).__name__,
            "model_name": self.model_name,
            "trained": self._trained,
        }


class TorchModelAdapter(MLModelInterface):
    """
    Adapter for PyTorch ML models.

    Wraps trained PyTorch models to work with the ML interface.
    Handles tensor conversion and GPU/CPU placement.
    """

    def __init__(self, torch_model, model_name: str = "PyTorch Model", device: str = "cpu"):
        """
        Initialize PyTorch adapter.

        Args:
            torch_model: Trained PyTorch neural network
            model_name: Human-readable name
            device: "cpu" or "cuda" for inference
        """
        self.model = torch_model
        self.model_name = model_name
        self.device = device
        self.model.to(device)
        self.model.eval()  # Set to evaluation mode
        self._trained = True

    def predict(self, context: DecisionContext) -> ModelPrediction:
        """Make single prediction from context."""
        import torch

        features = FeatureExtractor.extract_array(context)
        features_tensor = torch.FloatTensor(features).unsqueeze(0).to(self.device)

        with torch.no_grad():
            output = self.model(features_tensor)

        # Handle both single output and tuple outputs
        if isinstance(output, tuple):
            raw_output = torch.cat(output, dim=1)[0].cpu().numpy()
        else:
            raw_output = output[0].cpu().numpy()

        if len(raw_output) >= 8:
            return ModelPrediction(
                light_probability=float(np.clip(raw_output[0], 0, 1)),
                hvac_heating_prob=float(np.clip(raw_output[1], 0, 1)),
                hvac_cooling_prob=float(np.clip(raw_output[2], 0, 1)),
                hvac_off_prob=float(np.clip(raw_output[3], 0, 1)),
                hvac_speed=float(np.clip(raw_output[4], 0, 1)),
                hvac_setpoint=float(np.clip(raw_output[5], 0, 1)),
                shading_factor=float(np.clip(raw_output[6], 0, 1)),
                confidence=float(np.clip(raw_output[7], 0, 1))
                if len(raw_output) > 7
                else 0.8,
            )
        else:
            raise ValueError(f"Model expected 8 outputs, got {len(raw_output)}")

    def predict_batch(self, contexts: list[DecisionContext]) -> np.ndarray:
        """Make batch predictions."""
        import torch

        features = FeatureExtractor.extract_batch(contexts)
        features_tensor = torch.FloatTensor(features).to(self.device)

        with torch.no_grad():
            output = self.model(features_tensor)

        if isinstance(output, tuple):
            return torch.cat(output, dim=1).cpu().numpy()
        else:
            return output.cpu().numpy()

    def get_model_name(self) -> str:
        """Get model name."""
        return self.model_name

    def is_trained(self) -> bool:
        """Check if model is trained."""
        return self._trained

    def get_model_info(self) -> Dict[str, Any]:
        """Get model metadata."""
        return {
            "type": "pytorch",
            "model_class": type(self.model).__name__,
            "model_name": self.model_name,
            "device": self.device,
            "trained": self._trained,
        }


class RulesAdapter(MLModelInterface):
    """
    Adapter wrapping rule-based controller as pseudo-model.

    Allows comparing rule-based decisions with ML model decisions.
    Useful for A/B testing and baseline comparison.
    """

    def __init__(self, rule_based_controller):
        """
        Initialize rules adapter.

        Args:
            rule_based_controller: RuleBasedController instance
        """
        from decisions.strategies import RuleBasedController

        assert isinstance(
            rule_based_controller, RuleBasedController
        ), "Must be RuleBasedController"
        self.controller = rule_based_controller

    def predict(self, context: DecisionContext) -> ModelPrediction:
        """
        Convert rule-based decision to ModelPrediction.

        Args:
            context: Decision context

        Returns:
            ModelPrediction representing rule-based decision
        """
        decision = self.controller.make_decision(context)

        # Convert deterministic decision to probabilistic prediction
        return ModelPrediction(
            light_probability=1.0 if decision.light_on else 0.0,
            hvac_heating_prob=1.0 if decision.hvac_mode == "heating" else 0.0,
            hvac_cooling_prob=1.0 if decision.hvac_mode == "cooling" else 0.0,
            hvac_off_prob=1.0 if decision.hvac_mode == "off" else 0.0,
            hvac_speed=decision.hvac_speed,
            hvac_setpoint=(decision.hvac_setpoint - 18.0) / 7.0,  # Normalize
            shading_factor=decision.shading_factor,
            confidence=1.0,  # Rules are deterministic (high confidence)
        )

    def predict_batch(self, contexts: list[DecisionContext]) -> np.ndarray:
        """Batch predict using rules."""
        predictions = []
        for context in contexts:
            prediction = self.predict(context)
            predictions.append(
                [
                    prediction.light_probability,
                    prediction.hvac_heating_prob,
                    prediction.hvac_cooling_prob,
                    prediction.hvac_off_prob,
                    prediction.hvac_speed,
                    prediction.hvac_setpoint,
                    prediction.shading_factor,
                    prediction.confidence,
                ]
            )
        return np.array(predictions)

    def get_model_name(self) -> str:
        """Get model name."""
        return f"Rules ({self.controller.name()})"

    def is_trained(self) -> bool:
        """Rules are always 'trained' (hardcoded)."""
        return True

    def get_model_info(self) -> Dict[str, Any]:
        """Get model metadata."""
        return {
            "type": "rules",
            "controller": self.controller.name(),
            "trained": True,
        }


class ModelFactory:
    """
    Factory for creating model instances from config.

    Simplifies loading models from configuration files.
    """

    @staticmethod
    def create_from_config(config: Dict[str, Any]) -> MLModelInterface:
        """
        Create model from configuration dict.

        Config format:
        {
            "type": "sklearn" | "torch" | "rules",
            "model_path": "path/to/model.pkl" (sklearn/torch),
            "model_name": "My Model",
            "device": "cpu" (torch only),
            "controller": RuleBasedController instance (rules),
        }

        Args:
            config: Model configuration

        Returns:
            MLModelInterface instance
        """
        model_type = config.get("type", "rules").lower()

        if model_type == "sklearn":
            import pickle

            model_path = config["model_path"]
            with open(model_path, "rb") as f:
                sklearn_model = pickle.load(f)
            return SklearnModelAdapter(
                sklearn_model, model_name=config.get("model_name", "Sklearn Model")
            )

        elif model_type == "torch":
            torch_model = config["model"]  # Must pass loaded model
            return TorchModelAdapter(
                torch_model,
                model_name=config.get("model_name", "PyTorch Model"),
                device=config.get("device", "cpu"),
            )

        elif model_type == "rules":
            if "controller" not in config:
                from decisions.strategies import RuleBasedController

                config["controller"] = RuleBasedController()
            return RulesAdapter(config["controller"])

        else:
            raise ValueError(f"Unknown model type: {model_type}")
