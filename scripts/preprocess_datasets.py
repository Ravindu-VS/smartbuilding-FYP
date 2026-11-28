#!/usr/bin/env python3
"""
Turn the raw public datasets (data/raw/) into the processed tables used for training
(data/processed/).  Deterministic: the same raw files give byte-identical outputs,
whose SHA-256 are written to data/manifest.json ("processed").

    python scripts/preprocess_datasets.py

Outputs
  data/processed/uci_occupancy.csv
      The three UCI files concatenated and sorted by time, one row per minute, with
      the file each row came from (source_file) and provenance "public_real".
      No values are changed; rows are only re-ordered.  Overlap between the files
      is checked (there is none: datatest 2-4 Feb, datatraining 4-10 Feb,
      datatest2 11-18 Feb 2015).
  data/processed/bdg2_panther_office.csv
      Hourly electricity (kWh per hour) of the BDG2 "Panther" site's office buildings
      that have at least 90 % of hours present from 1 Jun 2016 to 31 Dec 2017 (the
      site's cleaned electricity starts in late May 2016), joined with the
      site's hourly weather (NOAA ISD-Lite as distributed with BDG2).  Panther's
      metadata coordinates (28.52 N, 81.38 W, US/Eastern) put it in a humid
      subtropical climate, the closest of the 19 BDG2 sites to Colombo's.  Weather
      gaps of up to 3 h are filled by linear interpolation and flagged
      (weather_interpolated = 1); longer gaps stay empty.  Missing or removed
      electricity readings stay empty (they are never filled).
  data/processed/data_quality.json
      Row counts, missing shares, gaps and class balance for both tables.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "data", "processed")
MANIFEST = os.path.join(ROOT, "data", "manifest.json")
UCI_FILES = ("datatest.txt", "datatraining.txt", "datatest2.txt")
UCI_MIRROR = os.path.join(ROOT, "Dataset", "UCI", "occupancy+detection")
BDG2_SITE = "Panther"
MIN_COMPLETENESS = 0.90
# Panther's electricity in the cleaned files starts in late May 2016 (about 61 % of 2016 is
# empty for every office building), so the study period starts on 1 June 2016.
PERIOD = ("2016-06-01 00:00:00", "2017-12-31 23:00:00")
WEATHER_COLS = ["airTemperature", "dewTemperature", "cloudCoverage", "windSpeed", "precipDepth1HR", "seaLvlPressure"]


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _uci_path(fname: str) -> str:
    p = os.path.join(RAW, "uci_occupancy", fname)
    return p if os.path.exists(p) else os.path.join(UCI_MIRROR, fname)


def uci() -> tuple[pd.DataFrame, dict]:
    parts = []
    for fname in UCI_FILES:
        df = pd.read_csv(_uci_path(fname))            # first column is the row id in the original files
        df = df.rename(columns={"date": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["source_file"] = fname
        parts.append(df[["timestamp", "Temperature", "Humidity", "Light", "CO2", "HumidityRatio",
                         "Occupancy", "source_file"]])
    spans = {p["source_file"].iat[0]: (p["timestamp"].min(), p["timestamp"].max()) for p in parts}
    ordered = sorted(spans.items(), key=lambda kv: kv[1][0])
    for (fa, (_, end_a)), (fb, (start_b, _)) in zip(ordered, ordered[1:]):
        if start_b <= end_a:
            raise SystemExit(f"UCI files overlap in time: {fa} ends {end_a}, {fb} starts {start_b}")
    df = pd.concat(parts, ignore_index=True).sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    dup = int(df.duplicated(subset=["timestamp"]).sum())
    df["provenance"] = "public_real"
    gaps = df["timestamp"].diff().dt.total_seconds().fillna(60)
    quality = {
        "rows": len(df), "duplicate_timestamps": dup,
        "files": {f: {"rows": int((df.source_file == f).sum()),
                      "first": str(spans[f][0]), "last": str(spans[f][1]),
                      "occupied_share": round(float(df.loc[df.source_file == f, "Occupancy"].mean()), 4)}
                  for f in UCI_FILES},
        "gaps_over_5min": int((gaps > 300).sum()),
        "missing_values": {c: int(df[c].isna().sum()) for c in df.columns},
        "occupied_share": round(float(df["Occupancy"].mean()), 4),
    }
    return df, quality


def bdg2() -> tuple[pd.DataFrame, dict]:
    meta = pd.read_csv(os.path.join(RAW, "bdg2", "metadata.csv"))
    offices = meta[(meta.site_id == BDG2_SITE) & (meta.primaryspaceusage == "Office")]
    path = os.path.join(RAW, "bdg2", "electricity_cleaned.csv")
    header = set(pd.read_csv(path, nrows=0).columns)
    absent = sorted(b for b in offices.building_id if b not in header)   # no cleaned electricity meter
    ids = sorted(b for b in offices.building_id if b in header)
    elec = pd.read_csv(path, usecols=["timestamp"] + ids, parse_dates=["timestamp"])
    elec = elec.set_index("timestamp").sort_index()
    keep, completeness = [], {}
    in_period = elec.loc[PERIOD[0]:PERIOD[1]]
    for b in ids:
        c = float(in_period[b].notna().mean())
        completeness[b] = {"2016": round(float(elec[b][elec.index.year == 2016].notna().mean()), 4),
                           "2017": round(float(elec[b][elec.index.year == 2017].notna().mean()), 4),
                           "study_period": round(c, 4)}
        if c >= MIN_COMPLETENESS:
            keep.append(b)
    w = pd.read_csv(os.path.join(RAW, "bdg2", "weather.csv"), parse_dates=["timestamp"])
    w = w[w.site_id == BDG2_SITE].set_index("timestamp").sort_index()[WEATHER_COLS]
    full = pd.date_range(PERIOD[0], PERIOD[1], freq="h")
    w = w[~w.index.duplicated()].reindex(full)
    missing_before = w["airTemperature"].isna()
    w_filled = w.interpolate(method="time", limit=3, limit_area="inside")
    interp = missing_before & w_filled["airTemperature"].notna()
    w_filled["weather_interpolated"] = interp.astype(int)
    rows = []
    for b in keep:
        d = pd.DataFrame({"timestamp": full, "building_id": b,
                          "electricity_kwh": elec[b].reindex(full).values})
        rows.append(d)
    df = pd.concat(rows, ignore_index=True)
    df = df.merge(w_filled.rename_axis("timestamp").reset_index(), on="timestamp", how="left")
    sqm = offices.set_index("building_id")["sqm"].to_dict()
    df["floor_area_m2"] = df["building_id"].map(sqm)
    df["provenance"] = "public_real"
    df = df.sort_values(["building_id", "timestamp"], kind="mergesort").reset_index(drop=True)
    quality = {
        "site": BDG2_SITE, "office_buildings_at_site": len(ids) + len(absent),
        "without_cleaned_electricity": absent, "selected": keep,
        "selection_rule": f">= {MIN_COMPLETENESS:.0%} of hours present in the study period {PERIOD[0]} - {PERIOD[1]}",
        "completeness": completeness, "rows": len(df),
        "electricity_missing_share": round(float(df.electricity_kwh.isna().mean()), 4),
        "weather_missing_share_after_fill": round(float(df.airTemperature.isna().mean()), 4),
        "weather_interpolated_hours": int(interp.sum()),
        "period": [str(full.min()), str(full.max())],
    }
    return df, quality


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    quality = {}
    df_u, quality["uci_occupancy"] = uci()
    p_u = os.path.join(OUT, "uci_occupancy.csv")
    df_u.to_csv(p_u, index=False, float_format="%.10g", lineterminator="\n")
    if os.path.exists(os.path.join(RAW, "bdg2", "electricity_cleaned.csv")):
        df_b, quality["bdg2_panther_office"] = bdg2()
        p_b = os.path.join(OUT, "bdg2_panther_office.csv")
        df_b.to_csv(p_b, index=False, float_format="%.6g", lineterminator="\n")
    else:
        print("BDG2 raw files missing: run scripts/fetch_datasets.py first (skipping the energy table)")
        p_b = None
    with open(os.path.join(OUT, "data_quality.json"), "w", encoding="utf-8") as f:
        json.dump(quality, f, indent=2)
    processed = manifest.setdefault("processed", {})
    for p in (p_u, p_b):
        if p:
            processed[os.path.basename(p)] = {"sha256": sha256(p), "bytes": os.path.getsize(p),
                                              "produced_by": "scripts/preprocess_datasets.py"}
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    for name, q in quality.items():
        print(name, json.dumps({k: v for k, v in q.items() if k not in ("completeness", "files")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
