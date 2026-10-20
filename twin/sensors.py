"""
Copied unchanged from the thesis code (simulation/sensor_models.py, commit eb82674).

Sensor models for the digital twin.

Each room carries the same sensor set as the planned edge node, with noise,
first-order response lag and quantisation.  The noise levels are assumptions
of the same order as typical datasheet accuracies (BME280-class temperature/
humidity, BH1750-class light, NDIR-class CO2, PIR motion); they are not
measured on the project's hardware.

All randomness comes from one seeded numpy Generator, so a run is
reproducible for a given seed.
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np

DEFAULTS = {
    "temperature_noise_c": 0.1,
    "temperature_tau_s": 60.0,
    "humidity_noise_pct": 1.0,
    "humidity_tau_s": 60.0,
    "light_noise_frac": 0.02,
    "co2_noise_ppm": 10.0,
    "co2_noise_frac": 0.01,
    "co2_tau_s": 60.0,
    # PIR: probability per second that a present occupant makes a detectable movement
    "pir_move_rate_per_s": 1.0 / 60.0,
    "pir_false_rate_per_s": 1.0 / 36000.0,
}


class AdvancedSensorModels:
    def __init__(self, config: Dict = None, seed: int = 0):
        cfg = dict(DEFAULTS)
        cfg.update(config or {})
        self.cfg = cfg
        self.rng = np.random.default_rng([int(seed), 23])
        self._lag: Dict[tuple, float] = {}
        self._last_motion_s: Dict[int, float] = {}

    def _lagged(self, key: tuple, true_value: float, dt: float, tau: float) -> float:
        prev = self._lag.get(key)
        if prev is None:
            prev = true_value
        a = 1.0 - math.exp(-dt / tau) if tau > 0 else 1.0
        v = prev + a * (true_value - prev)
        self._lag[key] = v
        return v

    # each method returns the reading after advancing the sensor state by dt
    def temperature(self, room_id: int, true_c: float, dt: float) -> float:
        v = self._lagged(("T", room_id), true_c, dt, self.cfg["temperature_tau_s"])
        return round(v + self.rng.normal(0, self.cfg["temperature_noise_c"]), 2)

    def humidity(self, room_id: int, true_pct: float, dt: float) -> float:
        v = self._lagged(("RH", room_id), true_pct, dt, self.cfg["humidity_tau_s"])
        return float(np.clip(round(v + self.rng.normal(0, self.cfg["humidity_noise_pct"]), 1), 0.0, 100.0))

    def light(self, true_lux: float) -> float:
        v = true_lux * (1.0 + self.rng.normal(0, self.cfg["light_noise_frac"]))
        return float(max(0.0, round(v)))  # 1 lux resolution

    def co2(self, room_id: int, true_ppm: float, dt: float) -> float:
        v = self._lagged(("CO2", room_id), true_ppm, dt, self.cfg["co2_tau_s"])
        sd = self.cfg["co2_noise_ppm"] + self.cfg["co2_noise_frac"] * v
        return float(max(380.0, round(v + self.rng.normal(0, sd))))

    def pir_step(self, room_id: int, occupants: int, dt: float, now_s: float) -> None:
        """Advance the PIR model by dt seconds; remembers the last detection time."""
        rate = occupants * self.cfg["pir_move_rate_per_s"] + self.cfg["pir_false_rate_per_s"]
        if self.rng.random() < 1.0 - math.exp(-rate * dt):
            self._last_motion_s[room_id] = now_s

    def seconds_since_motion(self, room_id: int, now_s: float) -> float:
        t = self._last_motion_s.get(room_id)
        return float("inf") if t is None else max(0.0, now_s - t)

    def reset_state(self) -> None:
        self._lag.clear()
        self._last_motion_s.clear()
