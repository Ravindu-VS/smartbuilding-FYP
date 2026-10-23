"""
Feature computation for live inference, numpy only (the Raspberry Pi needs no pandas or
scikit-learn).  Each class computes exactly what the training-side table code computes
(ml/features.py add_features, ml/thermal.py twin_frame); tests/test_ml.py checks the parity.
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

MAX_GAP_S = 300.0
BASE = ["Temperature", "Humidity", "Light", "CO2", "HumidityRatio"]
LIGHT = {"OFF": 0.0, "DIM": 0.4, "ON": 1.0}


class OnlineFeatures:
    """
    The same features computed reading by reading (live inference).  Keeps the last
    20 minutes of readings per room; a gap longer than MAX_GAP_S clears the history,
    exactly as add_features starts a new segment.
    """

    def __init__(self, window_min: float = 20.0):
        self.window_s = window_min * 60.0
        self._hist: Dict[str, Deque[Tuple[float, Dict[str, float]]]] = {}

    def update(self, room_id: str, ts: datetime, values: Dict[str, Optional[float]]) -> Dict[str, float]:
        now = ts.timestamp()
        h = self._hist.setdefault(room_id, deque())
        if h and now - h[-1][0] > MAX_GAP_S:
            h.clear()
        row = {k: (np.nan if values.get(k) is None else float(values[k])) for k in BASE}
        h.append((now, row))
        while h and now - h[0][0] > self.window_s:
            h.popleft()
        times = np.array([x[0] for x in h])

        def lag(key, minutes):
            pos = np.searchsorted(times, now - minutes * 60.0, side="right") - 1
            return h[pos][1][key] if pos >= 0 else np.nan

        f = dict(row)
        f["CO2_d5"] = row["CO2"] - lag("CO2", 5)
        f["CO2_d15"] = row["CO2"] - lag("CO2", 15)
        recent = np.array([x[1]["CO2"] for x in h if now - x[0] < 15 * 60.0])
        recent = recent[~np.isnan(recent)]
        f["CO2_std15"] = float(np.std(recent, ddof=1)) if len(recent) >= 3 else np.nan
        f["T_d15"] = row["Temperature"] - lag("Temperature", 15)
        f["HR_d15"] = row["HumidityRatio"] - lag("HumidityRatio", 15)
        f["Light_d1"] = row["Light"] - lag("Light", 1)
        rl = [x[1]["Light"] for x in h if now - x[0] < 5 * 60.0]
        f["Light_mean5"] = float(np.nanmean(rl)) if rl and not np.all(np.isnan(rl)) else np.nan
        hr = ts.hour + ts.minute / 60.0
        f["hour_sin"], f["hour_cos"] = float(np.sin(2 * np.pi * hr / 24.0)), float(np.cos(2 * np.pi * hr / 24.0))
        f["weekday"] = 1 if ts.weekday() < 5 else 0
        return f


def pir_features(seconds) -> Dict[str, float]:
    """PIR features from 'seconds since last motion' (None = no motion seen yet)."""
    s = 86400.0 if seconds is None or (isinstance(seconds, float) and np.isnan(seconds)) else min(float(seconds), 86400.0)
    return {"pir_2min": float(s <= 120), "pir_10min": float(s <= 600), "pir_20min": float(s <= 1200),
            "pir_log": float(np.log1p(s))}


def _room_static() -> Dict[str, Dict[str, float]]:
    from twin.spec import build_spec
    return {r.room_id: {"area_m2": r.area, "ac_w_per_m3": r.physics_params["ac_cool_capacity_w"] / r.volume,
                        "window_m2": r.window_area, "ac_max_electric_w": r.controller_overrides["ac_max_electric_w"]}
            for r in build_spec()}


class ThermalOnline:
    """
    The thermal-model features computed live, one 5-minute sample at a time, exactly as
    twin_frame() computes them from a table (checked by tests/test_ml.py).  Feed it every
    5 minutes with a record in the generator's format (twin/runner.py _record keys).
    """

    def __init__(self):
        self.static = _room_static()
        self.hist: Dict[str, List[Dict]] = {}

    def update(self, rec: Dict) -> Dict[str, float]:
        rid = rec["room_id"]
        h = self.hist.setdefault(rid, [])
        t_meas = rec.get("meas_temperature_c")
        if t_meas is None or (isinstance(t_meas, float) and math.isnan(t_meas)):
            # forward fill for at most two samples, as twin_frame does
            prev = [x for x in h[-2:] if x["_T_raw"] is not None]
            t_val = h[-1]["T"] if h and len(prev) > 0 and _ffill_ok(h) else float("nan")
        else:
            t_val = float(t_meas)
        sp = rec["setpoint_c"] if rec["hvac_cmd"] == "NORMAL" else (27.0 if rec["hvac_cmd"] == "LOW" else None)
        cmd_key = f"{rec['hvac_cmd']}|{rec['setpoint_c']}"
        since = 0
        if h and h[-1]["_cmd"] == cmd_key:
            since = min(120, h[-1]["min_since_hvac_change_raw"] + 5)
        co2 = rec.get("meas_co2_ppm")
        co2 = float("nan") if co2 is None else float(co2)

        def lag(key, k):
            return h[-k][key] if len(h) >= k else float("nan")

        ts = rec["timestamp"] if isinstance(rec["timestamp"], datetime) else datetime.fromisoformat(rec["timestamp"])
        hr = ts.hour + ts.minute / 60.0
        st = self.static[rid]
        f = {"T": t_val, "T_lag5": lag("T", 1), "T_lag10": lag("T", 2), "T_lag15": lag("T", 3)}
        f["dT5"], f["dT15"] = t_val - f["T_lag5"], t_val - f["T_lag15"]
        f["RH"] = float("nan") if rec.get("meas_humidity_pct") is None else float(rec["meas_humidity_pct"])
        f["CO2"] = co2
        f["CO2_d15"] = co2 - lag("CO2", 3)
        pir = rec.get("meas_pir_seconds")
        f["pir_recent"] = 1.0 if (pir is not None and not (isinstance(pir, float) and math.isnan(pir)) and pir <= 600) else 0.0
        f["ac_on"] = 1.0 if rec["hvac_cmd"] == "NORMAL" else 0.0
        f["ac_low"] = 1.0 if rec["hvac_cmd"] == "LOW" else 0.0
        f["setpoint_gap"] = 0.0 if sp is None else t_val - sp
        f["ac_power_frac"] = rec["hvac_w"] / st["ac_max_electric_w"]
        f["min_since_hvac_change"] = float(since)
        f["light_level"] = LIGHT[rec["light_cmd"]]
        f["vent"] = float(rec["vent_boost"])
        f["t_out"] = float(rec["t_out_c"])
        f["t_out_gap"] = f["t_out"] - t_val
        f["ghi"] = float(rec["ghi_w_m2"])
        f["hour_sin"], f["hour_cos"] = math.sin(2 * math.pi * hr / 24), math.cos(2 * math.pi * hr / 24)
        f["area_m2"], f["ac_w_per_m3"], f["window_m2"] = st["area_m2"], st["ac_w_per_m3"], st["window_m2"]
        h.append({"T": t_val, "_T_raw": t_meas, "CO2": co2, "_cmd": cmd_key, "min_since_hvac_change_raw": since})
        if len(h) > 6:
            del h[0]
        return f


def _ffill_ok(h: List[Dict]) -> bool:
    """True when the last real temperature is at most two samples back."""
    missing = 0
    for x in reversed(h):
        if x["_T_raw"] is not None and not (isinstance(x["_T_raw"], float) and math.isnan(x["_T_raw"])):
            return missing < 2
        missing += 1
    return False
