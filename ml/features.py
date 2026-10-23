"""
Occupancy features, computed the same way at training and at inference.

All temporal features use only the current and past readings of the same room and the
same contiguous recording (a gap of more than MAX_GAP_S starts a new segment, so values
from before a gap are never used).  Nothing derived from the label is a feature.

Base readings (units)
  Temperature    degC          Humidity       % RH          Light   lux
  CO2            ppm           HumidityRatio  kg/kg (derived from T and RH)
Temporal (past only)
  CO2_d5, CO2_d15     CO2 now minus CO2 5 / 15 min earlier (ppm)
  CO2_std15           standard deviation of CO2 over the last 15 min (ppm)
  T_d15, HR_d15       temperature / humidity-ratio change over 15 min
  Light_d1            light now minus 1 min earlier (lux)
  Light_mean5         mean light over the last 5 min (lux)
Calendar
  hour_sin, hour_cos  time of day;  weekday  1 Mon-Fri, 0 weekend
"""
from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

MAX_GAP_S = 300.0
BASE = ["Temperature", "Humidity", "Light", "CO2", "HumidityRatio"]
TEMPORAL_CO2 = ["CO2_d5", "CO2_d15", "CO2_std15"]
TEMPORAL_OTHER = ["T_d15", "HR_d15", "Light_d1", "Light_mean5"]
CALENDAR = ["hour_sin", "hour_cos", "weekday"]

FEATURE_SETS: Dict[str, List[str]] = {
    # the project's original inputs (UCI columns)
    "env": BASE,
    "env_time": BASE + CALENDAR,
    "env_temporal": BASE + TEMPORAL_CO2 + TEMPORAL_OTHER,
    # without light: in an automated building the lights follow the controller, so light
    # level would feed the controller's own action back into the estimate
    "nolight_temporal": ["Temperature", "Humidity", "CO2", "HumidityRatio"] + TEMPORAL_CO2 + ["T_d15", "HR_d15"],
    # CO2 only (what the fusion estimator uses next to PIR)
    "co2": ["CO2"],
    "co2_temporal": ["CO2"] + TEMPORAL_CO2,
}
UNITS = {"Temperature": "degC", "Humidity": "%RH", "Light": "lux", "CO2": "ppm", "HumidityRatio": "kg/kg",
         "CO2_d5": "ppm/5min", "CO2_d15": "ppm/15min", "CO2_std15": "ppm", "T_d15": "K/15min",
         "HR_d15": "kg/kg per 15min", "Light_d1": "lux/min", "Light_mean5": "lux",
         "hour_sin": "-", "hour_cos": "-", "weekday": "0/1"}


def add_features(df: pd.DataFrame, time_col: str = "timestamp", group_col: Optional[str] = None) -> pd.DataFrame:
    """Add every feature to a table of readings (one row per reading, any regular or
    irregular interval).  Lags are taken by time (e.g. the reading 5 min earlier is the
    latest reading at or before t - 5 min within the same segment)."""
    out = []
    groups = df.groupby(group_col, sort=False) if group_col else [(None, df)]
    for _, g in groups:
        g = g.sort_values(time_col, kind="mergesort").copy()
        t = pd.to_datetime(g[time_col])
        seg = (t.diff().dt.total_seconds().fillna(0) > MAX_GAP_S).cumsum()
        g["_seg"] = seg.values
        parts = []
        for _, s in g.groupby("_seg", sort=False):
            parts.append(_segment_features(s, time_col))
        out.append(pd.concat(parts))
    res = pd.concat(out).drop(columns="_seg")
    return res.loc[df.index] if len(res) == len(df) else res


def _lag(s: pd.Series, t: pd.Series, minutes: float) -> np.ndarray:
    """Value of s at the latest time <= t - minutes (NaN if before the segment start)."""
    tv = t.values.astype("datetime64[ns]").astype(np.int64)
    target = tv - int(minutes * 60e9)
    pos = np.searchsorted(tv, target, side="right") - 1
    vals = s.values.astype(float)
    res = np.where(pos >= 0, vals[np.clip(pos, 0, None)], np.nan)
    return res


def _segment_features(s: pd.DataFrame, time_col: str) -> pd.DataFrame:
    s = s.copy()
    t = pd.to_datetime(s[time_col])
    co2 = s["CO2"].astype(float)
    s["CO2_d5"] = co2.values - _lag(co2, t, 5)
    s["CO2_d15"] = co2.values - _lag(co2, t, 15)
    ts = pd.Series(co2.values, index=t.values)
    s["CO2_std15"] = ts.rolling("15min", min_periods=3).std().values
    s["T_d15"] = s["Temperature"].values - _lag(s["Temperature"], t, 15)
    s["HR_d15"] = s["HumidityRatio"].values - _lag(s["HumidityRatio"], t, 15)
    light = s["Light"].astype(float)
    s["Light_d1"] = light.values - _lag(light, t, 1)
    s["Light_mean5"] = pd.Series(light.values, index=t.values).rolling("5min", min_periods=1).mean().values
    h = t.dt.hour + t.dt.minute / 60.0
    s["hour_sin"] = np.sin(2 * np.pi * h / 24.0).values
    s["hour_cos"] = np.cos(2 * np.pi * h / 24.0).values
    s["weekday"] = (t.dt.weekday < 5).astype(int).values
    return s


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


def matrix(df: pd.DataFrame, features: Sequence[str]) -> np.ndarray:
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise KeyError(f"missing feature columns: {missing}")
    return df[list(features)].to_numpy(dtype=float)
