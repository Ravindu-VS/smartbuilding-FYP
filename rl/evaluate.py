#!/usr/bin/env python3
"""
Matched comparison of controllers in the digital twin, and PPO registration.

    python -m rl.evaluate --policy models/ppo_runs/seed0/policy_best.json \
        --scenarios normal hot_weather --seeds 1 2 3 --out experiments/results/exp05_control
    python -m rl.evaluate ... --register        # also register the PPO policy (acceptance-tested)

Matched conditions: for a given (scenario, seed) every controller runs on a building rebuilt
from the same seed, so weather, occupants, sensor noise and faults are identical; all are
measured over the same 7 days (Monday 2 Mar 2026 00:00 onwards by default).  Warm-up before
the measurement: 7 days for the multi-objective controller (its learning week, as in the live
system) and 2 days for the others (thermal settling only; they do not learn).
Evaluation seeds (1, 2, 3) are never used for PPO training (training seeds start at 1000).

Savings (%) = (E_schedule - E_controller) / E_schedule x 100, negative when the controller uses
more energy than the conventional schedule.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from twin.runner import DEFAULT_START, run_episode   # noqa: E402

WARMUP = {"mo": 7.0}
DEFAULT_WARMUP = 2.0
KEYS = ["energy_kwh", "hvac_kwh", "lighting_kwh", "plug_kwh", "controllable_kwh", "discomfort_share",
        "discomfort_min", "discomfort_pmv_h", "overheat_min", "temp_rmse_occupied_c", "iaq_min", "light_switches",
        "hvac_changes", "ac_cycles", "safety_overrides", "vent_boost_min", "failsafe_F1", "failsafe_F2",
        "failsafe_F3", "decision_ms_mean", "decision_ms_p95", "peak_kw", "occupied_min", "wall_s",
        "consistency_room_sum_minus_total_kwh"]


CACHE_DIR = os.path.join(ROOT, "experiments", "results", "run_cache")


def _source_hash(controller: str, policy: Optional[str]) -> str:
    """Hash of everything a run depends on: simulator and controller code, the policy file, and the
    registry's active occupancy_rf (used by threshold_rf).  A cached run is reused only on a match."""
    import glob
    import hashlib
    h = hashlib.sha256()
    files = sorted(glob.glob(os.path.join(ROOT, "twin", "*.py"))) + [os.path.join(ROOT, "rl", f) for f in
                                                                    ("policy.py", "ppo.py", "evaluate.py")]
    for f in files + ([policy] if policy else []):
        with open(f, "rb") as fh:
            h.update(fh.read().replace(b"\r\n", b"\n"))
    if controller == "threshold_rf":
        from ml.registry import Registry
        h.update(str((Registry().active("occupancy_rf") or {}).get("version")).encode())
    return h.hexdigest()[:16]


def _job(args) -> Dict:
    controller, scenario, seed, days, policy, start = args
    key = f"{controller}_{scenario}_s{seed}_d{days:g}_{start:%Y%m%d}_{_source_hash(controller, policy if controller == 'ppo' else None)}"
    cache = os.path.join(CACHE_DIR, key + ".json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as f:
            r = json.load(f)
        r["cached"] = True
        return r
    r = _run(args)
    if r["status"] == "ok":
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(r, f, default=str)
    return r


def _run(args) -> Dict:
    controller, scenario, seed, days, policy, start = args
    t0 = time.perf_counter()
    try:
        r = run_episode(controller, scenario, seed=seed, start=start, days=days,
                        warmup_days=WARMUP.get(controller, DEFAULT_WARMUP), ppo_policy=policy)
        return {"controller": controller, "scenario": scenario, "seed": seed, "status": "ok", "metrics": r.metrics,
                "daily_kwh": r.daily_kwh, "meta": r.meta, "per_room": r.per_room}
    except Exception as e:                      # recorded, never hidden
        return {"controller": controller, "scenario": scenario, "seed": seed, "status": "error",
                "error": f"{type(e).__name__}: {e}", "wall_s": time.perf_counter() - t0}


def compare(controllers: List[str], scenarios: List[str], seeds: List[int], days: float = 7.0,
            policy: Optional[str] = None, start: datetime = DEFAULT_START, workers: int = 2) -> Dict:
    jobs = [(c, s, k, days, policy, start) for s in scenarios for k in seeds for c in controllers]
    t0 = time.perf_counter()
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            runs = list(ex.map(_job, jobs))
    else:
        runs = [_job(j) for j in jobs]
    return {"runs": runs, "summary": summarise(runs, controllers, scenarios), "controllers": controllers,
            "scenarios": scenarios, "seeds": seeds, "days": days, "start": start.isoformat(), "policy": policy,
            "warmup_days": {c: WARMUP.get(c, DEFAULT_WARMUP) for c in controllers}, "wall_s": time.perf_counter() - t0}


def summarise(runs: List[Dict], controllers: List[str], scenarios: List[str]) -> Dict:
    out: Dict = {}
    for s in scenarios:
        out[s] = {}
        base_by_seed = {r["seed"]: r["metrics"]["energy_kwh"] for r in runs
                        if r["scenario"] == s and r["controller"] == "schedule" and r["status"] == "ok"}
        for c in controllers:
            rs = [r for r in runs if r["scenario"] == s and r["controller"] == c and r["status"] == "ok"]
            errs = [r for r in runs if r["scenario"] == s and r["controller"] == c and r["status"] != "ok"]
            if not rs:
                out[s][c] = {"status": "error", "errors": [e.get("error") for e in errs]}
                continue
            m = {}
            for k in KEYS:
                vals = np.array([r["metrics"][k] for r in rs], dtype=float)
                m[k] = float(vals.mean())
                m[k + "_sd"] = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
            sav = [100.0 * (base_by_seed[r["seed"]] - r["metrics"]["energy_kwh"]) / base_by_seed[r["seed"]]
                   for r in rs if r["seed"] in base_by_seed]
            m["savings_vs_schedule_pct"] = float(np.mean(sav)) if sav else float("nan")
            m["savings_vs_schedule_pct_sd"] = float(np.std(sav, ddof=1)) if len(sav) > 1 else 0.0
            m["seeds"] = len(rs)
            m["errors"] = [e.get("error") for e in errs]
            out[s][c] = m
    return out


def markdown(summary: Dict, controllers: List[str]) -> str:
    lines = []
    for s, by_c in summary.items():
        lines += [f"### {s}", "",
                  "| controller | energy kWh | savings vs schedule % | HVAC kWh | lighting kWh | discomfort % of occupied time | "
                  "PMV-hours over 0.5 | overheat room-min | IAQ room-min >1000 ppm | switches (light/AC) | AC on-off | "
                  "fail-safe F1/F2/F3 | ms per decision |", "|" + "---|" * 13]
        for c in controllers:
            m = by_c.get(c)
            if not m or m.get("status") == "error":
                lines.append(f"| {c} | error: {(m or {}).get('errors')} |" + " |" * 11)
                continue
            lines.append(
                f"| {c} | {m['energy_kwh']:.0f} ± {m['energy_kwh_sd']:.0f} | {m['savings_vs_schedule_pct']:.1f} ± "
                f"{m['savings_vs_schedule_pct_sd']:.1f} | {m['hvac_kwh']:.0f} | {m['lighting_kwh']:.0f} | "
                f"{100 * m['discomfort_share']:.1f} ± {100 * m['discomfort_share_sd']:.1f} | {m['discomfort_pmv_h']:.1f} | "
                f"{m['overheat_min']:.0f} | {m['iaq_min']:.0f} | {m['light_switches']:.0f}/{m['hvac_changes']:.0f} | "
                f"{m['ac_cycles']:.0f} | {m['failsafe_F1']:.0f}/{m['failsafe_F2']:.0f}/{m['failsafe_F3']:.0f} | "
                f"{m['decision_ms_mean']:.3f} |")
        lines.append("")
    return "\n".join(lines)


def save(result: Dict, out_dir: str, title: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    slim = dict(result)
    slim["runs"] = [{k: v for k, v in r.items() if k != "per_room"} for r in result["runs"]]
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, indent=1, default=str)
    with open(os.path.join(out_dir, "per_room.json"), "w", encoding="utf-8") as f:
        json.dump([{k: r.get(k) for k in ("controller", "scenario", "seed", "per_room")} for r in result["runs"]], f)
    md = [f"# {title}", "", f"Controllers: {', '.join(result['controllers'])}; seeds {result['seeds']}; "
          f"{result['days']:g} measured days from {result['start']}; warm-up {result['warmup_days']}. "
          f"Values are means ± standard deviation over the seeds. Provenance: synthetic (simulator).", "",
          markdown(result["summary"], result["controllers"])]
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))


def register_ppo(policy_path: str, result: Dict, train_dir: str) -> str:
    from ml.common import REGISTRY_DIR, git_commit, next_version, rounded, sha256_file, utc_now, versions
    from rl.policy import ACTIONS, N_ACT, N_OBS
    task = "ppo_policy"
    version = next_version(task)
    d = os.path.join(REGISTRY_DIR, task, version)
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(policy_path, os.path.join(d, "policy.json"))
    for extra in ("config.json", "train_log.csv"):
        src = os.path.join(train_dir, extra)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(d, extra))
    with open(policy_path, encoding="utf-8") as f:
        pmeta = json.load(f).get("meta", {})
    ev = {s: {c: {k: m[k] for k in KEYS + ["savings_vs_schedule_pct"] if k in m}
              for c, m in by_c.items() if m.get("status") != "error"} for s, by_c in result["summary"].items()}
    meta = {"task": task, "version": version, "kind": "policy", "algorithm": "PPO (clipped surrogate, GAE), numpy",
            "n_obs": N_OBS, "n_act": N_ACT, "actions": [f"{l}/{a}" for l, a in ACTIONS],
            "observation_code": "rl/policy.py ObsBuilder", "training": {"run": os.path.relpath(train_dir, ROOT),
                                                                        "best_episode": pmeta.get("episode"),
                                                                        "config": pmeta.get("config"),
                                                                        "provenance": "synthetic (simulator)"},
            "evaluation": ev, "evaluation_seeds": result["seeds"], "evaluation_days": result["days"],
            "files": {"policy.json": {"sha256": sha256_file(os.path.join(d, "policy.json")),
                                      "bytes": os.path.getsize(os.path.join(d, "policy.json"))}},
            "trained_utc": utc_now(), "git_commit": git_commit(), "dependencies": versions(), "provenance": "prediction"}
    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(rounded(meta, 6), f, indent=2, default=str)
    with open(os.path.join(d, "model_card.md"), "w", encoding="utf-8") as f:
        f.write(f"# Model card: {task} {version}\n\n- PPO policy for the 25 simulated rooms (one shared per-room policy)\n"
                f"- Trained offline in the digital twin only; deployed behind InputGuard/GuardedController and the SafetyLayer\n"
                f"- Observation {N_OBS} values, {N_ACT} discrete actions (rl/policy.py)\n\n## Evaluation (synthetic)\n\n"
                + markdown(result["summary"], result["controllers"]) +
                "\n## Limitations\n\n- Learned in the simulator; not validated on a real building. The real room keeps the "
                "rule-based / multi-objective controller.\n- One policy shared by all rooms (not a multi-agent system).\n")
    return version


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--controllers", nargs="+", default=["schedule", "threshold_rf", "mo", "ppo"])
    ap.add_argument("--scenarios", nargs="+", default=["normal"])
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--policy", default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default=os.path.join(ROOT, "experiments", "results", "controller_comparison"))
    ap.add_argument("--title", default="Controller comparison (digital twin)")
    ap.add_argument("--register", action="store_true")
    args = ap.parse_args(argv)
    if "ppo" in args.controllers and not args.policy:
        ap.error("--policy is required when comparing ppo")
    res = compare(args.controllers, args.scenarios, args.seeds, args.days, args.policy, workers=args.workers)
    save(res, args.out, args.title)
    print(markdown(res["summary"], args.controllers))
    if args.register:
        from ml.registry import Registry
        v = register_ppo(args.policy, res, os.path.dirname(args.policy))
        rep = Registry().evaluate("ppo_policy", v)
        print(json.dumps(rep, indent=1))
        if rep["passed"]:
            Registry().promote("ppo_policy", v, report=rep)
            print("promoted ppo_policy", v)
        else:
            Registry()._log("ppo_policy", {"action": "promotion_rejected", "version": v, "report": rep})
            print("ppo_policy", v, "stays a candidate (acceptance tests failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
