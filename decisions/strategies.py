"""
Control Strategies for Building Automation

Implements multiple decision-making strategies:
- RuleBasedController: Simple thresholds (backward compatible with Phase 3)
- ComfortOptimizer: Maximize occupant comfort using PMV/comfort metrics
- EnergyOptimizer: Minimize energy consumption
- HybridController: Balance comfort and energy with configurable weights

Phase 4: Intelligent decision-making for HVAC, lighting, and shading.
"""

import math
from decisions.controller import ControlStrategy, DecisionContext, DecisionOutput


class RuleBasedController(ControlStrategy):
    """
    Simple rule-based control strategy.

    Uses fixed thresholds for lights, HVAC, and shading.
    Backward compatible with Phase 3 control logic.
    """

    def name(self) -> str:
        return "Rule-Based"

    def make_decision(self, context: DecisionContext) -> DecisionOutput:
        """
        Make decisions using simple threshold rules.

        Light: IF occupancy > 0.3 AND light_level < 300 THEN on
        HVAC: IF occupancy > 0.3 AND temp < 21°C THEN heat, else IF temp > 23°C THEN cool
        Shading: IF solar > 500 AND occupied THEN shade to 0.5
        """
        decision_reasons = []

        lux_threshold = 400.0  # Default rule-based threshold
        lux = context.light_level

        if context.occupancy == 0:
            light_on = False
            decision_reasons.append("Empty room -> Light OFF")
        elif context.occupancy > 0 and lux < lux_threshold:
            light_on = True
            decision_reasons.append("Occupied + low daylight -> Light ON")
        else:
            light_on = False
            decision_reasons.append("Occupied + sufficient daylight -> Light OFF")

        # ===== HVAC DECISION =====
        hvac_mode = "off"
        hvac_setpoint = 21.0
        hvac_speed = 0.0

        if context.occupancy > 0:
            # Occupied - maintain comfort
            if context.temperature_zone < 20.0:
                hvac_mode = "heating"
                hvac_speed = 0.5 + 0.5 * (20.0 - context.temperature_zone) / 5.0
                decision_reasons.append(f"HVAC: occupied + cold → heating {hvac_speed:.1%}")
            elif context.temperature_zone > 23.0:
                hvac_mode = "cooling"
                hvac_speed = 0.5 + 0.5 * (context.temperature_zone - 23.0) / 5.0
                decision_reasons.append(f"HVAC: occupied + warm → cooling {hvac_speed:.1%}")
            else:
                hvac_mode = "fan_only"
                decision_reasons.append("HVAC: occupied, good temp → fan only")
        else:
            decision_reasons.append("HVAC: unoccupied → off")

        # ===== SHADING DECISION =====
        shading_factor = 0.0
        if context.solar_irradiance > 500.0 and context.is_occupied:
            shading_factor = 0.5
            decision_reasons.append(f"Shading: high solar + occupied → 50%")
        elif context.solar_irradiance > 800.0:  # Even if unoccupied, very high solar
            shading_factor = 0.3
            decision_reasons.append(f"Shading: very high solar → 30%")
        else:
            decision_reasons.append("Shading: low solar → open")

        return DecisionOutput(
            light_on=light_on,
            hvac_mode=hvac_mode,
            hvac_setpoint=hvac_setpoint,
            hvac_speed=hvac_speed,
            shading_factor=shading_factor,
            light_threshold=lux_threshold,
            decision_reason=" | ".join(decision_reasons)
        )


class ComfortOptimizer(ControlStrategy):
    """
    Comfort-optimized control strategy.

    Uses PMV (Predicted Mean Vote) and comfort metrics to maximize
    occupant satisfaction. Prioritizes comfort over energy efficiency.
    """

    def name(self) -> str:
        return "Comfort Optimizer"

    def make_decision(self, context: DecisionContext) -> DecisionOutput:
        """
        Make decisions optimizing for occupant comfort.

        Light: IF occupancy > 0.1 AND light_level < 300 THEN on (more aggressive)
        HVAC: IF PMV < 0 THEN heat, IF PMV > 0 THEN cool (target neutral comfort)
               Modulate speed based on |PMV|
        Shading: Balance solar gain with comfort (prevent overheating)
        """
        decision_reasons = []

        lux_threshold = 500.0  # More aggressive for comfort
        lux = context.light_level

        if context.occupancy == 0:
            light_on = False
            decision_reasons.append("Empty room -> Light OFF")
        elif context.occupancy > 0 and lux < lux_threshold:
            light_on = True
            decision_reasons.append("Occupied + low daylight -> Light ON")
        else:
            light_on = False
            decision_reasons.append("Occupied + sufficient daylight -> Light OFF")

        # ===== HVAC DECISION =====
        # Target PMV = 0 (neutral - no dissatisfaction)
        hvac_mode = "off"
        hvac_setpoint = 22.0  # Slightly warmer for comfort
        hvac_speed = 0.0
        decision_reasons.append(f"PMV: {context.pmv:.2f} (target: 0.0)")

        if context.occupancy > 0:
            # Occupied - adjust to target PMV = 0
            if context.pmv < -1.5:
                # Too cold - strong heating
                hvac_mode = "heating"
                hvac_speed = 1.0
                decision_reasons.append("HVAC: very cold (PMV < -1.5) → heating 100%")

            elif context.pmv < -0.5:
                # Cool - proportional heating
                hvac_mode = "heating"
                hvac_speed = 0.5 + 0.5 * (-context.pmv) / 1.0
                decision_reasons.append(f"HVAC: cool (PMV {context.pmv:.1f}) → heating {hvac_speed:.0%}")

            elif context.pmv > 1.5:
                # Too warm - strong cooling
                hvac_mode = "cooling"
                hvac_speed = 1.0
                decision_reasons.append("HVAC: very warm (PMV > 1.5) → cooling 100%")

            elif context.pmv > 0.5:
                # Warm - proportional cooling
                hvac_mode = "cooling"
                hvac_speed = 0.5 + 0.5 * context.pmv / 1.0
                decision_reasons.append(f"HVAC: warm (PMV {context.pmv:.1f}) → cooling {hvac_speed:.0%}")

            else:
                # Neutral comfort - just air circulation
                hvac_mode = "fan_only"
                decision_reasons.append(f"HVAC: neutral comfort (PMV {context.pmv:.1f}) → fan only")

        else:
            # Unoccupied - minimal conditioning
            decision_reasons.append("HVAC: unoccupied → off")

        # ===== SHADING DECISION =====
        # Balance solar gain with comfort
        shading_factor = 0.0

        if context.is_occupied:
            # If overheating (comfort low), use shading to cool
            if context.comfort_index < 50.0 and context.temperature_operative > 23.0:
                shading_factor = min(0.8, (context.temperature_operative - 23.0) / 2.0)
                decision_reasons.append(f"Shading: low comfort + warm → {shading_factor:.0%}")
            # If comfortable and solar high, reduce shading to prevent overshadowing
            elif context.solar_irradiance > 600.0:
                shading_factor = 0.3
                decision_reasons.append("Shading: high solar, maintaining view → 30%")
        else:
            # Unoccupied - minimal shading (save energy)
            decision_reasons.append("Shading: unoccupied → open")

        return DecisionOutput(
            light_on=light_on,
            hvac_mode=hvac_mode,
            hvac_setpoint=hvac_setpoint,
            hvac_speed=hvac_speed,
            shading_factor=shading_factor,
            light_threshold=lux_threshold,
            decision_reason=" | ".join(decision_reasons)
        )


class EnergyOptimizer(ControlStrategy):
    """
    Energy-efficient control strategy.

    Minimizes energy consumption while maintaining acceptable comfort.
    Accepts wider temperature ranges and less aggressive control.
    """

    def name(self) -> str:
        return "Energy Optimizer"

    def make_decision(self, context: DecisionContext) -> DecisionOutput:
        """
        Make decisions minimizing energy consumption.

        Light: IF occupancy > 0.5 AND light_level < 500 THEN on (less aggressive)
        HVAC: Wider deadband (19-23°C), lower speed, prefer fan-only
        Shading: Aggressive shading to reduce cooling load
        """
        decision_reasons = []

        lux_threshold = 300.0  # Accept lower light for efficiency
        lux = context.light_level

        if context.occupancy == 0:
            light_on = False
            decision_reasons.append("Empty room -> Light OFF")
        elif context.occupancy > 0 and lux < lux_threshold:
            light_on = True
            decision_reasons.append("Occupied + low daylight -> Light ON")
        else:
            light_on = False
            decision_reasons.append("Occupied + sufficient daylight -> Light OFF")

        # ===== HVAC DECISION =====
        # Wider deadband (19-23°C) to save energy
        hvac_mode = "off"
        hvac_setpoint = 21.0
        hvac_speed = 0.0

        if context.occupancy > 0:
            # Only act if temperature is well outside comfort range
            if context.temperature_zone < 19.0:
                # Only heat if very cold
                hvac_mode = "heating"
                hvac_speed = 0.3 + 0.2 * (19.0 - context.temperature_zone) / 5.0
                decision_reasons.append(f"HVAC: cold (< 19°C) → heating {hvac_speed:.0%}")

            elif context.temperature_zone > 23.0:
                # Only cool if warm
                hvac_mode = "cooling"
                hvac_speed = 0.3 + 0.2 * (context.temperature_zone - 23.0) / 5.0
                decision_reasons.append(f"HVAC: warm (> 23°C) → cooling {hvac_speed:.0%}")

            elif context.comfort_index < 40.0:
                # Only if comfort is unacceptable
                hvac_mode = "fan_only"
                decision_reasons.append("HVAC: low comfort → fan only")
            else:
                decision_reasons.append("HVAC: within tolerance → off")
        else:
            # Unoccupied - no conditioning
            decision_reasons.append("HVAC: unoccupied → off")

        # ===== SHADING DECISION =====
        # Aggressive shading to reduce cooling load
        shading_factor = 0.0

        if context.solar_irradiance > 400.0:
            # Always shade when solar is significant (reduce cooling need)
            shading_factor = 0.6 + 0.2 * min(1.0, context.solar_irradiance / 1000.0)
            decision_reasons.append(f"Shading: solar {context.solar_irradiance:.0f}W/m² → {shading_factor:.0%}")
        else:
            decision_reasons.append("Shading: low solar → open (maximize passive gain)")

        return DecisionOutput(
            light_on=light_on,
            hvac_mode=hvac_mode,
            hvac_setpoint=hvac_setpoint,
            hvac_speed=hvac_speed,
            shading_factor=shading_factor,
            light_threshold=lux_threshold,
            decision_reason=" | ".join(decision_reasons)
        )


class HybridController(ControlStrategy):
    """
    Hybrid control strategy balancing comfort and energy.

    Weighted combination of comfort and energy objectives.
    Default: 60% comfort, 40% energy (configurable).
    """

    def __init__(self, comfort_weight: float = 0.6, energy_weight: float = 0.4):
        """
        Initialize hybrid controller.

        Args:
            comfort_weight: Importance of comfort (0-1)
            energy_weight: Importance of energy (0-1)
        """
        total = comfort_weight + energy_weight
        self.comfort_weight = comfort_weight / total
        self.energy_weight = energy_weight / total

    def name(self) -> str:
        return f"Hybrid ({self.comfort_weight:.0%} comfort, {self.energy_weight:.0%} energy)"

    def make_decision(self, context: DecisionContext) -> DecisionOutput:
        """
        Make blended decision between comfort and energy strategies.
        """
        # Get both strategies
        comfort_controller = ComfortOptimizer()
        energy_controller = EnergyOptimizer()

        comfort_decision = comfort_controller.make_decision(context)
        energy_decision = energy_controller.make_decision(context)

        # Blend decisions based on weights
        # For HVAC speed: weighted average
        hvac_speed = (
            self.comfort_weight * comfort_decision.hvac_speed +
            self.energy_weight * energy_decision.hvac_speed
        )

        # For HVAC mode: choose based on weighted priority
        # Both agree on mode? Use it. Otherwise, pick weighted winner.
        if comfort_decision.hvac_mode == energy_decision.hvac_mode:
            hvac_mode = comfort_decision.hvac_mode
        else:
            # Temperature-based: if very cold/hot, comfort wins
            if context.pmv < -1.0 or context.pmv > 1.0:
                hvac_mode = comfort_decision.hvac_mode
            else:
                hvac_mode = energy_decision.hvac_mode

        # Lighting: comfort wants easier on, energy wants off
        light_on = comfort_decision.light_on if self.comfort_weight > 0.5 else energy_decision.light_on

        # Shading: blend factor
        shading_factor = (
            self.comfort_weight * comfort_decision.shading_factor +
            self.energy_weight * energy_decision.shading_factor
        )

        reason = (
            f"Comfort: {comfort_decision.decision_reason[:40]}... | "
            f"Energy: {energy_decision.decision_reason[:40]}... | "
            f"Hybrid blend: HVAC {hvac_mode} {hvac_speed:.0%}"
        )

        lux_threshold = (
            self.comfort_weight * comfort_decision.light_threshold +
            self.energy_weight * energy_decision.light_threshold
        )

        return DecisionOutput(
            light_on=light_on,
            hvac_mode=hvac_mode,
            hvac_setpoint=21.0,
            hvac_speed=hvac_speed,
            shading_factor=shading_factor,
            light_threshold=lux_threshold,
            decision_reason=reason
        )
