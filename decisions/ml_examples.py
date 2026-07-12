"""
ML Model Integration Examples - Phase 6

Shows how to train and integrate scikit-learn and PyTorch models
with the building control system.

Examples:
1. Train a scikit-learn RandomForest model
2. Train a PyTorch neural network
3. Load and use trained models with the decision engine
4. Compare ML models with rule-based baseline
"""

import numpy as np
from typing import List, Tuple, Dict, Any
import json

from decisions import (
    DecisionContext,
    DecisionEngine,
    MLModelInterface,
    SklearnModelAdapter,
    TorchModelAdapter,
    RulesAdapter,
    ModelFactory,
    FeatureExtractor,
    FeatureSchema,
)


# ============================================================================
# EXAMPLE 1: Training & Using a Scikit-Learn Model
# ============================================================================


class SklearnModelTrainer:
    """
    Example: Train a RandomForest model for building control decisions.

    Shows how to prepare training data and train an ML model.
    The trained model can then be wrapped with SklearnModelAdapter.
    """

    @staticmethod
    def generate_synthetic_training_data(num_samples: int = 10000) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generate synthetic training data.

        In real scenario, this would come from recorded building operation
        over several months/years.

        Args:
            num_samples: Number of training samples

        Returns:
            (features_array, targets_array) tuple
        """
        np.random.seed(42)

        # Features: extract from DecisionContext-like data
        features = np.random.rand(num_samples, FeatureSchema.get_feature_count())

        # Synthetic targets (8 outputs from decision)
        # Target 0: light_probability
        # Target 1-3: hvac mode probabilities (heating, cooling, off)
        # Target 4: hvac_speed
        # Target 5: hvac_setpoint
        # Target 6: shading_factor
        # Target 7: confidence
        targets = np.random.rand(num_samples, 8)

        # Make targets realistic based on features
        # Example: if temperature_zone (feature 0) is high, cooling more likely
        targets[features[:, 0] > 0.6, 2] = 0.8  # cooling prob high if temp high
        targets[features[:, 0] > 0.6, 1] = 0.1  # heating prob low if temp high

        # Light depends on occupancy (feature 7) and light_level (feature 6)
        occupancy = features[:, 7]
        light_level = features[:, 6]
        targets[:, 0] = ((occupancy > 0.3) & (light_level < 0.3)).astype(float)

        return features, targets

    @staticmethod
    def train_sklearn_model(features: np.ndarray, targets: np.ndarray):
        """
        Train a scikit-learn multi-output model.

        Args:
            features: Training features (n_samples, n_features)
            targets: Training targets (n_samples, 8)

        Returns:
            Trained sklearn model
        """
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.multioutput import MultiOutputRegressor

        # Use MultiOutputRegressor to handle 8 outputs
        model = MultiOutputRegressor(RandomForestRegressor(n_estimators=100, random_state=42))
        model.fit(features, targets)

        return model

    @staticmethod
    def create_sklearn_adapter() -> SklearnModelAdapter:
        """
        Create a ready-to-use scikit-learn adapter.

        Example: Load trained model and wrap with adapter.

        Returns:
            SklearnModelAdapter instance
        """
        # In practice: load from file
        # model = pickle.load(open('trained_forest.pkl', 'rb'))

        # For this example, train on synthetic data
        features, targets = SklearnModelTrainer.generate_synthetic_training_data(5000)
        sklearn_model = SklearnModelTrainer.train_sklearn_model(features, targets)

        # Wrap with adapter
        return SklearnModelAdapter(
            sklearn_model, model_name="RandomForest BldgControl v1.0"
        )


# ============================================================================
# EXAMPLE 2: Training & Using a PyTorch Model
# ============================================================================


class PyTorchModelTrainer:
    """
    Example: Train a PyTorch neural network for building control.

    Shows architecture and training loop for a multi-output NN.
    """

    @staticmethod
    def create_neural_network():
        """
        Create a PyTorch neural network for control decisions.

        Architecture:
        - Input: 20 features (temperature, occupancy, comfort, etc.)
        - Hidden: [128, 64, 32] with ReLU
        - Output: 8 (light_prob, 3x hvac modes, hvac_speed, setpoint, shading, confidence)

        Returns:
            PyTorch model
        """
        import torch
        import torch.nn as nn

        class ControlNet(nn.Module):
            """Neural network for building control decisions."""

            def __init__(self, input_size: int = 20, output_size: int = 8):
                super().__init__()
                self.fc1 = nn.Linear(input_size, 128)
                self.fc2 = nn.Linear(128, 64)
                self.fc3 = nn.Linear(64, 32)
                self.fc_out = nn.Linear(32, output_size)

                self.relu = nn.ReLU()
                self.sigmoid = nn.Sigmoid()

            def forward(self, x):
                x = self.relu(self.fc1(x))
                x = self.relu(self.fc2(x))
                x = self.relu(self.fc3(x))
                x = self.sigmoid(self.fc_out(x))  # Outputs 0-1
                return x

        return ControlNet(input_size=FeatureSchema.get_feature_count(), output_size=8)

    @staticmethod
    def train_torch_model(model, features: np.ndarray, targets: np.ndarray, epochs: int = 50):
        """
        Train PyTorch model.

        Args:
            model: PyTorch model
            features: Training features (n_samples, n_features)
            targets: Training targets (n_samples, 8)
            epochs: Number of training epochs

        Returns:
            Trained model
        """
        import torch
        import torch.optim as optim

        # Convert to tensors
        features_tensor = torch.FloatTensor(features)
        targets_tensor = torch.FloatTensor(targets)

        # Training setup
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        optimizer = optim.Adam(model.parameters(), lr=0.001)
        loss_fn = torch.nn.MSELoss()

        # Training loop
        model.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            outputs = model(features_tensor.to(device))
            loss = loss_fn(outputs, targets_tensor.to(device))
            loss.backward()
            optimizer.step()

            if (epoch + 1) % 10 == 0:
                print(f"Epoch {epoch+1}/{epochs}, Loss: {loss.item():.4f}")

        return model

    @staticmethod
    def create_torch_adapter() -> TorchModelAdapter:
        """
        Create a ready-to-use PyTorch adapter.

        Example: Train and wrap PyTorch model.

        Returns:
            TorchModelAdapter instance
        """
        import torch

        # Create and train model
        model = PyTorchModelTrainer.create_neural_network()

        # Generate synthetic training data
        features, targets = SklearnModelTrainer.generate_synthetic_training_data(5000)

        # Train model
        model = PyTorchModelTrainer.train_torch_model(model, features, targets, epochs=20)

        # Wrap with adapter
        device = "cuda" if torch.cuda.is_available() else "cpu"
        return TorchModelAdapter(model, model_name="ControlNet v1.0", device=device)


# ============================================================================
# EXAMPLE 3: Using Models with Decision Engine
# ============================================================================


class ModelIntegrationExample:
    """
    Examples of using ML models with the decision engine.
    """

    @staticmethod
    def example_sklearn_integration():
        """
        Example: Use scikit-learn model with decision engine.
        """
        print("\n" + "=" * 70)
        print("EXAMPLE: Scikit-Learn Model Integration")
        print("=" * 70)

        # Create model adapter
        sklearn_adapter = SklearnModelTrainer.create_sklearn_adapter()

        # Create decision engine with ML strategy
        config = {
            "control_strategy": "ml",
            "ml_model": sklearn_adapter,
            "decision_logging": True,
        }
        engine = DecisionEngine(config)

        # Make decisions
        context = DecisionContext(
            room_id=0,
            zone_type="office",
            temperature_zone=22.0,
            temperature_wall=21.5,
            temperature_operative=21.7,
            humidity=45.0,
            co2=600.0,
            light_level=300.0,
            occupancy=0.8,
            pmv=0.0,
            ppd=5.0,
            comfort_index=85.0,
            outdoor_temperature=15.0,
            solar_irradiance=400.0,
            wind_speed=3.0,
            light_on=True,
            hvac_mode="cooling",
            hvac_setpoint=21.0,
            hvac_speed=0.5,
            shading_factor=0.3,
            hour_of_day=14.0,
            is_occupied=True,
        )

        decision = engine.make_decision(context)

        print(f"\nDecision Output:")
        print(f"  Light ON: {decision.light_on}")
        print(f"  HVAC Mode: {decision.hvac_mode}")
        print(f"  HVAC Speed: {decision.hvac_speed:.1%}")
        print(f"  Shading: {decision.shading_factor:.1%}")
        print(f"  Reason: {decision.decision_reason}")

    @staticmethod
    def example_torch_integration():
        """
        Example: Use PyTorch model with decision engine.
        """
        print("\n" + "=" * 70)
        print("EXAMPLE: PyTorch Model Integration")
        print("=" * 70)

        print("\nNote: PyTorch example skipped (requires torch installation)")
        print("To run: uncomment and ensure torch is installed:")
        print("  torch_adapter = PyTorchModelTrainer.create_torch_adapter()")
        print("  config = {'control_strategy': 'ml', 'ml_model': torch_adapter}")
        print("  engine = DecisionEngine(config)")

    @staticmethod
    def example_model_comparison():
        """
        Example: Compare ML model with rule-based baseline.
        """
        print("\n" + "=" * 70)
        print("EXAMPLE: Model Comparison (ML vs Rules)")
        print("=" * 70)

        # Create rule-based baseline
        from decisions.strategies import RuleBasedController

        rules_adapter = RulesAdapter(RuleBasedController())

        # Create ML model
        sklearn_adapter = SklearnModelTrainer.create_sklearn_adapter()

        # Create test context
        contexts = [
            DecisionContext(
                room_id=i,
                zone_type="office",
                temperature_zone=20.0 + i * 0.5,
                temperature_wall=19.5 + i * 0.5,
                temperature_operative=19.7 + i * 0.5,
                humidity=40.0 + i * 2,
                co2=500.0 + i * 50,
                light_level=200.0 + i * 30,
                occupancy=0.5 + i * 0.05,
                pmv=-0.5 + i * 0.1,
                ppd=10.0 + i * 2,
                comfort_index=80.0 + i * 2,
                outdoor_temperature=15.0,
                solar_irradiance=300.0 + i * 100,
                wind_speed=2.0 + i * 0.2,
                light_on=False,
                hvac_mode="off",
                hvac_setpoint=21.0,
                hvac_speed=0.0,
                shading_factor=0.0,
                hour_of_day=10.0 + i,
                is_occupied=True,
            )
            for i in range(3)
        ]

        print("\nComparison for 3 different room scenarios:")
        print("-" * 70)

        for ctx in contexts:
            print(f"\nRoom {ctx.room_id} (Temp: {ctx.temperature_zone:.1f}°C, Solar: {ctx.solar_irradiance:.0f}W/m²)")

            # Rules decision
            rules_pred = rules_adapter.predict(ctx)
            rules_engine = DecisionEngine({"control_strategy": "rule"})
            rules_decision = rules_engine.make_decision(ctx)

            # ML decision
            ml_pred = sklearn_adapter.predict(ctx)

            print(f"  Rules   → Light: {rules_decision.light_on}, HVAC: {rules_decision.hvac_mode} {rules_decision.hvac_speed:.0%}")
            print(f"  ML      → Light: {ml_pred.light_probability:.1%} prob, HVAC Speed: {ml_pred.hvac_speed:.0%}")

    @staticmethod
    def example_model_factory():
        """
        Example: Use ModelFactory to create models from config.
        """
        print("\n" + "=" * 70)
        print("EXAMPLE: ModelFactory Configuration")
        print("=" * 70)

        # Create config for rule-based adapter
        rules_config = {
            "type": "rules",
        }

        model_factory = ModelFactory()
        rules_model = model_factory.create_from_config(rules_config)

        print(f"\nCreated model from config:")
        print(f"  Type: {rules_model.get_model_info()['type']}")
        print(f"  Name: {rules_model.get_model_name()}")
        print(f"  Trained: {rules_model.is_trained()}")

    @staticmethod
    def example_feature_extraction():
        """
        Example: Extract features for ML model training.
        """
        print("\n" + "=" * 70)
        print("EXAMPLE: Feature Extraction")
        print("=" * 70)

        context = DecisionContext(
            room_id=0,
            zone_type="office",
            temperature_zone=22.0,
            temperature_wall=21.5,
            temperature_operative=21.7,
            humidity=45.0,
            co2=600.0,
            light_level=300.0,
            occupancy=0.8,
            pmv=0.0,
            ppd=5.0,
            comfort_index=85.0,
            outdoor_temperature=15.0,
            solar_irradiance=400.0,
            wind_speed=3.0,
            light_on=True,
            hvac_mode="cooling",
            hvac_setpoint=21.0,
            hvac_speed=0.5,
            shading_factor=0.3,
            hour_of_day=14.0,
            is_occupied=True,
        )

        # Extract as dictionary
        features_dict = FeatureExtractor.extract_dict(context)
        print(f"\nFeature Dictionary ({len(features_dict)} features):")
        for name, value in list(features_dict.items())[:5]:
            print(f"  {name}: {value:.3f}")
        print(f"  ... ({len(features_dict)-5} more)")

        # Extract as normalized array
        features_array = FeatureExtractor.extract_array(context)
        print(f"\nNormalized Feature Array: shape {features_array.shape}")
        print(f"  Values (first 5): {features_array[:5]}")
        print(f"  Range: [{features_array.min():.3f}, {features_array.max():.3f}]")

        # Batch extraction
        contexts = [context] * 10
        batch_array = FeatureExtractor.extract_batch(contexts)
        print(f"\nBatch Extraction: shape {batch_array.shape}")

        print(f"\nFeature Schema Info:")
        print(f"  Total features: {FeatureSchema.get_feature_count()}")
        print(f"  Feature types: {set(f.feature_type for f in FeatureSchema.FEATURES.values())}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("PHASE 6: ML MODEL INTEGRATION EXAMPLES")
    print("=" * 70)

    # Run examples
    try:
        ModelIntegrationExample.example_sklearn_integration()
        ModelIntegrationExample.example_torch_integration()
        ModelIntegrationExample.example_model_comparison()
        ModelIntegrationExample.example_model_factory()
        ModelIntegrationExample.example_feature_extraction()

        print("\n" + "=" * 70)
        print("[OK] All examples completed successfully!")
        print("=" * 70 + "\n")

    except ImportError as e:
        print(f"\nNote: Some examples require additional libraries: {e}")
        print("Install with: pip install scikit-learn torch")

