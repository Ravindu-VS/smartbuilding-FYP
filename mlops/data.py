"""
Data pipeline for the room-occupancy model: raw telemetry → validation → cleaning → features → split.

Data: UCI Occupancy Detection (Candanedo & Feldheim 2016), 20 560 one-minute readings of a real office,
2–18 Feb 2015 (`data/raw/kaggle_occupancy/Occupancy.csv`). Columns: date, Temperature (°C), Humidity (%),
Light (lux), CO2 (ppm, NDIR), HumidityRatio (kg/kg), Occupancy (0/1).

Feature sets
  room101       Temperature, Humidity, Light, HumidityRatio + time of day.
                Only what Room 101's board measures (no NDIR CO2 there: the MQ-135 is not a calibrated ppm sensor).
                No weekend flag: nobody entered the UCI office at weekends, so a model with the flag learns that
                office's timetable (weekend = empty), which does not hold for Room 101. Dropping it costs about
                0.006 test F1 and keeps the model about the room's physics, not one office's calendar.
  with_weekend  room101 + weekend flag (comparison run).
  with_co2      room101 + CO2: comparison run to show what an NDIR sensor would add.

Leakage control: the split is chronological by calendar day (train before validation before test), features
use only the current reading and its timestamp (no look-ahead, no target-derived features), and the scaler
is fitted inside the model pipeline on training rows only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA = os.path.join(ROOT, "data", "raw", "kaggle_occupancy", "Occupancy.csv")

SCHEMA = {"date": "datetime", "Temperature": "float", "Humidity": "float", "Light": "float", "CO2": "float",
          "HumidityRatio": "float", "Occupancy": "int"}
# physical ranges; a value outside is a sensor fault, not an observation
RANGES = {"Temperature": (0.0, 50.0), "Humidity": (0.0, 100.0), "Light": (0.0, 5000.0), "CO2": (250.0, 5000.0),
          "HumidityRatio": (0.0, 0.03)}
FEATURE_SETS = {
    "room101": ["Temperature", "Humidity", "Light", "HumidityRatio", "hour_sin", "hour_cos"],
    "with_weekend": ["Temperature", "Humidity", "Light", "HumidityRatio", "hour_sin", "hour_cos", "is_weekend"],
    "with_co2": ["Temperature", "Humidity", "Light", "HumidityRatio", "CO2", "hour_sin", "hour_cos"],
}
TARGET = "Occupancy"
# chronological split by day (first day of each later part)
SPLIT_DAYS = {"validation": "2015-02-12", "test": "2015-02-15"}


class DataValidationError(ValueError):
    pass


@dataclass
class ValidationReport:
    rows_in: int = 0
    rows_out: int = 0
    errors: List[str] = field(default_factory=list)       # stop the pipeline
    warnings: List[str] = field(default_factory=list)     # rows dropped or fixed
    dropped: Dict[str, int] = field(default_factory=dict)
    missing_share: Dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> Dict:
        return {"ok": self.ok, "rows_in": self.rows_in, "rows_out": self.rows_out, "errors": self.errors,
                "warnings": self.warnings, "dropped": self.dropped, "missing_share": self.missing_share}


def load(path: str = DEFAULT_DATA) -> pd.DataFrame:
    return pd.read_csv(path)


def validate_and_clean(raw: pd.DataFrame, max_missing: float = 0.05) -> Tuple[pd.DataFrame, ValidationReport]:
    """Schema and range checks. Hard errors (missing column, too many gaps, label not 0/1) stop the run;
    out-of-range rows, unparseable timestamps and duplicates are dropped and counted."""
    rep = ValidationReport(rows_in=len(raw))
    missing_cols = [c for c in SCHEMA if c not in raw.columns]
    if missing_cols:
        rep.errors.append(f"missing columns: {missing_cols}")
        return raw.iloc[0:0], rep
    df = raw[list(SCHEMA)].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c, t in SCHEMA.items():
        if t in ("float", "int"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    rep.missing_share = {c: float(df[c].isna().mean()) for c in SCHEMA}
    for c, share in rep.missing_share.items():
        if share > max_missing:
            rep.errors.append(f"{c}: {share:.1%} missing (limit {max_missing:.0%})")
    labels = set(df[TARGET].dropna().unique().tolist())
    if not labels <= {0, 1}:
        rep.errors.append(f"{TARGET} has values other than 0/1: {sorted(labels)[:5]}")
    if rep.errors:
        return df.iloc[0:0], rep

    def drop(mask: pd.Series, why: str):
        n = int(mask.sum())
        if n:
            rep.dropped[why] = rep.dropped.get(why, 0) + n
            rep.warnings.append(f"dropped {n} rows: {why}")
        return df[~mask]

    df = drop(df.isna().any(axis=1), "missing value or unparseable timestamp")
    for c, (lo, hi) in RANGES.items():
        df = drop((df[c] < lo) | (df[c] > hi), f"{c} outside {lo}..{hi}")
    df = drop(df.duplicated(subset=["date"], keep="first"), "duplicate timestamp")
    df = df.sort_values("date").reset_index(drop=True)
    df[TARGET] = df[TARGET].astype(int)
    rep.rows_out = len(df)
    if rep.rows_out < 0.9 * rep.rows_in:
        rep.errors.append(f"cleaning removed {rep.rows_in - rep.rows_out} of {rep.rows_in} rows (more than 10%)")
    return df, rep


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row features only (current reading + its timestamp): no information from other rows."""
    out = df.copy()
    hours = out["date"].dt.hour + out["date"].dt.minute / 60.0
    out["hour_sin"] = np.sin(2 * np.pi * hours / 24.0)
    out["hour_cos"] = np.cos(2 * np.pi * hours / 24.0)
    out["is_weekend"] = (out["date"].dt.dayofweek >= 5).astype(int)
    return out


BUILDING_TZ = os.environ.get("BUILDING_TZ", "Asia/Colombo")     # the model's time features are local building time


def local_time(value=None) -> pd.Timestamp:
    """A reading's time in the building's time zone. Naive timestamps are already local; aware ones
    (e.g. the ingestion service's UTC receive time) are converted; missing = now."""
    if not value:
        return pd.Timestamp.now(tz=BUILDING_TZ)
    ts = pd.Timestamp(value)
    return ts.tz_localize(BUILDING_TZ) if ts.tzinfo is None else ts.tz_convert(BUILDING_TZ)


def features_from_reading(reading: Dict) -> Dict[str, float]:
    """The same feature construction for one live reading (serving path)."""
    ts = local_time(reading.get("timestamp"))
    hours = ts.hour + ts.minute / 60.0
    out = {"Temperature": reading.get("temperature"), "Humidity": reading.get("humidity"),
           "Light": reading.get("lux"), "CO2": reading.get("co2"),
           "hour_sin": float(np.sin(2 * np.pi * hours / 24.0)), "hour_cos": float(np.cos(2 * np.pi * hours / 24.0)),
           "is_weekend": int(ts.dayofweek >= 5)}
    hr = reading.get("humidity_ratio")
    if hr is None and out["Temperature"] is not None and out["Humidity"] is not None:
        hr = humidity_ratio(float(out["Temperature"]), float(out["Humidity"]))
    out["HumidityRatio"] = hr
    return out


def humidity_ratio(temp_c: float, rh_pct: float, pressure_kpa: float = 101.325) -> float:
    """kg water / kg dry air from temperature and RH (Magnus formula), as in the UCI data."""
    p_ws = 0.61094 * np.exp(17.625 * temp_c / (temp_c + 243.04))
    p_w = rh_pct / 100.0 * p_ws
    return float(0.62198 * p_w / (pressure_kpa - p_w))


def split(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Chronological split by calendar day; every row is in exactly one part."""
    v, t = pd.Timestamp(SPLIT_DAYS["validation"]), pd.Timestamp(SPLIT_DAYS["test"])
    parts = {"train": df[df["date"] < v], "validation": df[(df["date"] >= v) & (df["date"] < t)],
             "test": df[df["date"] >= t]}
    for name, part in parts.items():
        if len(part) == 0 or part[TARGET].nunique() < 2:
            raise DataValidationError(f"{name} split has {len(part)} rows and {part[TARGET].nunique()} classes")
    assert parts["train"]["date"].max() < parts["validation"]["date"].min() <= parts["validation"]["date"].max() \
        < parts["test"]["date"].min(), "splits overlap in time"
    return parts


def summary(parts: Dict[str, pd.DataFrame]) -> Dict[str, Dict]:
    return {k: {"rows": int(len(p)), "first": str(p["date"].min()), "last": str(p["date"].max()),
                "positive_share": round(float(p[TARGET].mean()), 4)} for k, p in parts.items()}
