"""Estimated CO2 (ppm) from the MQ-135 on the Room 101 board.

The MQ-135 is a metal-oxide sensor: its resistance Rs falls when CO2, but also alcohol, ammonia,
toluene and other gases, rise. It is not an NDIR CO2 sensor, so the result is an *estimate*
("eCO2"), labelled `co2_source = "mq135_estimate"` everywhere it appears.

Conversion (the widely used MQ-135 CO2 curve, after G. Krocker's MQ135 library and the Hanwei
sensitivity chart):

    Vout   = Vadc * divider              (ADC millivolts back to the module's AO voltage)
    Rs     = RL * (Vcc - Vout) / Vout    (load resistor RL on the module)
    Rs_c   = Rs / f(T, RH)               (temperature/humidity dependence, datasheet curve fit)
    ppm    = A * (Rs_c / R0) ** -B       (A = 116.6020682, B = 2.769034857)

R0 is the sensor's resistance at the reference concentration. It is set by baseline calibration:
the cleanest air the sensor sees (highest temperature/humidity-corrected Rs) is taken as the
reference concentration, by default 420 ppm (outdoor air). That is the automatic baseline
correction (ABC) idea used by commercial CO2 sensors: an occupied building returns to near-outdoor
CO2 when it is empty or ventilated. Until the baseline has seen a long enough period (24 h by
default) the calibration is reported as *provisional*. The estimate is smoothed with a median of
the last five readings because metal-oxide sensors are noisy.
"""
from __future__ import annotations

import json
import os
import statistics
import threading
import time
from collections import deque
from typing import Any, Dict, Optional

CO2_SOURCE_MQ135 = "mq135_estimate"
PARA, PARB = 116.6020682, 2.769034857
# temperature/humidity correction (curve fit of the datasheet's dependence chart)
CORA, CORB, CORC, CORD = 0.00035, 0.02718, 1.39538, 0.0018
CORE, CORF, CORG = -0.003333333, -0.001923077, 1.130128205


def correction_factor(temp_c: Optional[float], rh_pct: Optional[float]) -> float:
    if temp_c is None or rh_pct is None:
        return 1.0
    if temp_c < 20.0:
        return CORA * temp_c * temp_c - CORB * temp_c + CORC - (rh_pct - 33.0) * CORD
    return CORE * temp_c + CORF * rh_pct + CORG


class Mq135Co2Estimator:
    def __init__(self, path: str, vcc_mv: float = 5000.0, rl_kohm: float = 1.0, divider: float = 1.0,
                 reference_ppm: float = 420.0, adc_limit_mv: float = 3100.0, warmup_s: float = 1800.0,
                 abc_window_h: float = 168.0, provisional_h: float = 24.0):
        self.path = path
        self.vcc_mv, self.rl_kohm, self.divider = vcc_mv, rl_kohm, divider
        self.reference_ppm, self.adc_limit_mv = reference_ppm, adc_limit_mv
        self.warmup_s, self.abc_window_h, self.provisional_h = warmup_s, abc_window_h, provisional_h
        self.lock = threading.Lock()
        self.r0: Optional[float] = None
        self.r0_source: Optional[str] = None
        self.hourly_max: Dict[str, float] = {}       # "YYYY-mm-ddTHH" -> highest corrected Rs that hour
        self.first_seen: Optional[float] = None       # wall-clock time of the first usable reading
        self.recent = deque(maxlen=5)
        self.last: Dict[str, Any] = {}
        self.saturated = 0
        self._dirty_at = 0.0
        self.discarded_calibration: Optional[Dict[str, Any]] = None
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return
        cfg = d.get("config") or {}
        # The constructor describes the circuit. A calibration saved for another circuit (different supply,
        # load resistor or divider) does not apply to this one, so it is set aside and the baseline restarts.
        if any(isinstance(cfg.get(k), (int, float)) and abs(float(cfg[k]) - getattr(self, k)) > 1e-3
               for k in ("vcc_mv", "rl_kohm", "divider")):
            self.discarded_calibration = {"config": cfg, "r0_kohm": d.get("r0_kohm"), "r0_source": d.get("r0_source")}
            return
        if d.get("r0_source") == "manual" and isinstance(cfg.get("reference_ppm"), (int, float)):
            self.reference_ppm = float(cfg["reference_ppm"])
        self.r0 = d.get("r0_kohm") if isinstance(d.get("r0_kohm"), (int, float)) else None
        self.r0_source = d.get("r0_source")
        self.hourly_max = {k: float(v) for k, v in (d.get("hourly_max_rs_kohm") or {}).items()}
        self.first_seen = d.get("first_seen")

    def save(self) -> None:
        with self.lock:
            data = {"config": {"vcc_mv": self.vcc_mv, "rl_kohm": self.rl_kohm, "divider": self.divider,
                               "reference_ppm": self.reference_ppm},
                    "r0_kohm": self.r0, "r0_source": self.r0_source, "first_seen": self.first_seen,
                    "hourly_max_rs_kohm": self.hourly_max, "saved": time.time()}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ physics
    def resistance(self, adc_mv: float) -> Optional[float]:
        vout = adc_mv * self.divider
        if adc_mv <= 5 or vout >= self.vcc_mv:
            return None
        return self.rl_kohm * (self.vcc_mv - vout) / vout

    def ppm(self, rs_corr: float) -> Optional[float]:
        if not self.r0 or rs_corr <= 0:
            return None
        return PARA * (rs_corr / self.r0) ** (-PARB)

    def r0_for(self, rs_corr: float, ppm: float) -> float:
        return rs_corr * (ppm / PARA) ** (1.0 / PARB)

    # ------------------------------------------------------------------ main entry
    def update(self, adc_mv: Optional[float], temp_c: Optional[float], rh_pct: Optional[float],
               uptime_s: Optional[float] = None, now: Optional[float] = None) -> Dict[str, Any]:
        """Feed one board reading; returns {"co2_ppm", "state", ...}. co2_ppm is None when unusable."""
        now = time.time() if now is None else now
        out: Dict[str, Any] = {"co2_ppm": None, "source": CO2_SOURCE_MQ135}
        if adc_mv is None:
            out["state"] = "no_mq135_reading"
            return self._remember(out)
        if adc_mv >= self.adc_limit_mv:
            self.saturated += 1
            out["state"] = "adc_saturated"        # AO above the ESP32 ADC range: add a divider
            return self._remember(out)
        rs = self.resistance(adc_mv)
        if rs is None:
            out["state"] = "invalid_voltage"
            return self._remember(out)
        rs_c = rs / correction_factor(temp_c, rh_pct)
        out.update({"rs_kohm": round(rs, 3), "rs_corrected_kohm": round(rs_c, 3),
                    "correction": round(correction_factor(temp_c, rh_pct), 4)})
        warming = uptime_s is not None and uptime_s < self.warmup_s
        with self.lock:
            if not warming:
                if self.first_seen is None:
                    self.first_seen = now
                hour = time.strftime("%Y-%m-%dT%H", time.localtime(now))
                self.hourly_max[hour] = max(self.hourly_max.get(hour, 0.0), rs_c)
                cutoff = time.strftime("%Y-%m-%dT%H", time.localtime(now - self.abc_window_h * 3600))
                for k in [k for k in self.hourly_max if k < cutoff]:
                    del self.hourly_max[k]
                self._abc()
            est = self.ppm(rs_c)
            if est is not None:
                self.recent.append(est)
            smoothed = statistics.median(self.recent) if self.recent else None
        if warming:
            out["state"] = "warming_up"
        elif smoothed is None:
            out["state"] = "not_calibrated"
        else:
            out["state"] = "provisional" if self.provisional(now) else "calibrated"
            out["co2_ppm"] = round(max(350.0, min(10000.0, smoothed)), 0)
        if now - self._dirty_at > 300:
            self._dirty_at = now
            try:
                self.save()
            except OSError:
                pass
        return self._remember(out)

    def _abc(self) -> None:
        """Baseline: the cleanest hour in the window is the reference concentration."""
        if self.r0_source == "manual":
            return
        if not self.hourly_max:
            return
        best = max(self.hourly_max.values())
        self.r0 = self.r0_for(best, self.reference_ppm)
        self.r0_source = "abc"

    def provisional(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return self.first_seen is None or (now - self.first_seen) < self.provisional_h * 3600

    def calibrate_now(self, rs_corrected_kohm: float, reference_ppm: Optional[float] = None,
                      manual: bool = False) -> Dict[str, Any]:
        """Set R0 from a measured resistance at a known concentration (e.g. fresh outdoor air)."""
        ref = float(reference_ppm or self.reference_ppm)
        with self.lock:
            self.r0 = self.r0_for(rs_corrected_kohm, ref)
            self.r0_source = "manual" if manual else "abc"
            if manual:
                self.reference_ppm = ref
            self.recent.clear()
        self.save()
        return self.status()

    def release_manual(self) -> Dict[str, Any]:
        with self.lock:
            self.r0_source = None
            self._abc()
        self.save()
        return self.status()

    def _remember(self, out: Dict[str, Any]) -> Dict[str, Any]:
        self.last = dict(out, at=time.time())
        return out

    def status(self) -> Dict[str, Any]:
        with self.lock:
            hours = len(self.hourly_max)
            return {"source": CO2_SOURCE_MQ135, "r0_kohm": round(self.r0, 3) if self.r0 else None,
                    "r0_source": self.r0_source, "reference_ppm": self.reference_ppm,
                    "provisional": self.provisional(), "baseline_hours": hours,
                    "first_seen": self.first_seen, "saturated_readings": self.saturated,
                    "config": {"vcc_mv": self.vcc_mv, "rl_kohm": self.rl_kohm, "divider": self.divider,
                               "adc_limit_mv": self.adc_limit_mv, "warmup_s": self.warmup_s},
                    "last": self.last, "discarded_calibration": self.discarded_calibration,
                    "note": "estimated CO2 from a metal-oxide MQ-135 (also sensitive to VOCs, alcohol, NH3); "
                            "not an NDIR measurement"}
