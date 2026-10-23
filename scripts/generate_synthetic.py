#!/usr/bin/env python3
"""
Generate synthetic building data from the digital twin (provenance "synthetic").

    python scripts/generate_synthetic.py --scenario normal --seed 1 --days 7
    python scripts/generate_synthetic.py --scenario all --seed 1 2 3 --days 7 --controller schedule

One CSV (gzip) per (scenario, seed, controller) in data/synthetic/, one row per
simulated room every --every minutes, plus <name>.meta.json with the configuration,
scenario, seed, code version, row count, SHA-256 and the result of the validation
checks (twin/validation.py).  The same arguments always give the same file.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from twin.runner import CONTROLLER_NAMES, DEFAULT_START, run_episode   # noqa: E402
from twin.scenarios import SCENARIOS                                     # noqa: E402
from twin.validation import validate_records                             # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def generate(scenario: str, seed: int, days: float, controller: str, every_min: int, warmup_days: float,
             out_dir: str, start: datetime = DEFAULT_START) -> dict:
    res = run_episode(controller, scenario, seed=seed, start=start, days=days, warmup_days=warmup_days,
                      record_every=every_min)
    rows = res.records
    problems = validate_records(rows)
    name = f"{scenario}_seed{seed}_{controller}"
    os.makedirs(out_dir, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    data = buf.getvalue().encode()
    path = os.path.join(out_dir, name + ".csv.gz")
    with open(path, "wb") as f:                      # mtime=0: identical bytes for identical data
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
            gz.write(data)
    meta = {
        "name": name, "provenance": "synthetic", "generator": "scripts/generate_synthetic.py",
        "git_commit": git_commit(), "scenario": scenario, "scenario_description": SCENARIOS[scenario].description,
        "seed": seed, "controller": controller, "start": start.isoformat(), "days": days,
        "warmup_days": warmup_days, "interval_min": every_min, "rows": len(rows),
        "csv_sha256": hashlib.sha256(data).hexdigest(), "validation_problems": problems,
        "metrics": res.metrics, "fault_rooms": res.meta["fault_rooms"],
        "stuck_temperature_rooms": res.meta["stuck_temperature_rooms"],
    }
    with open(os.path.join(out_dir, name + ".meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", nargs="+", default=["normal"], help=f"'all' or any of {sorted(SCENARIOS)}")
    ap.add_argument("--seed", type=int, nargs="+", default=[1])
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--warmup-days", type=float, default=2.0)
    ap.add_argument("--controller", default="schedule", choices=CONTROLLER_NAMES)
    ap.add_argument("--every", type=int, default=5, help="minutes between rows")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "synthetic"))
    args = ap.parse_args(argv)
    scenarios = sorted(SCENARIOS) if args.scenario == ["all"] else args.scenario
    failed = 0
    for sc in scenarios:
        for seed in args.seed:
            meta = generate(sc, seed, args.days, args.controller, args.every, args.warmup_days, args.out)
            status = "OK" if not meta["validation_problems"] else f"{len(meta['validation_problems'])} PROBLEMS"
            failed += bool(meta["validation_problems"])
            print(f"{meta['name']}: {meta['rows']} rows, {meta['metrics']['energy_kwh']:.0f} kWh, validation {status}")
            for p in meta["validation_problems"][:5]:
                print("   ", p)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
