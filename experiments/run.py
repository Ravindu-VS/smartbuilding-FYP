#!/usr/bin/env python3
"""
Reproducible experiments 1-10 (configurations in experiments/configs/, results in experiments/results/).

    python experiments/run.py --list
    python experiments/run.py exp01_baseline exp05_control
    python experiments/run.py --all
    python experiments/run.py exp05_control --seeds 1 --days 1     # quick variant (not the reported result)

Each run writes experiments/results/<id>/:
  config.json   the configuration actually used (including overrides)
  status.json   status (PASS / FAIL / BLOCKED / ERROR), timing, commit, data and model versions, errors
  results.json  raw results;  summary.md  human-readable table;  log.txt  console output
A failed or blocked experiment is recorded as such - results are never filled in.
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import os
import sys
import time
import traceback
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CONFIGS = os.path.join(ROOT, "experiments", "configs")
RESULTS = os.path.join(ROOT, "experiments", "results")


def load_configs():
    out = {}
    for p in sorted(glob.glob(os.path.join(CONFIGS, "*.json"))):
        with open(p, encoding="utf-8") as f:
            c = json.load(f)
        out[c["id"]] = c
    return out


def versions_snapshot():
    from ml.common import git_commit, versions
    from ml.registry import Registry
    reg = Registry()
    active = {t: (reg.active(t) or {}).get("version") for t in reg.tasks()}
    data = {}
    mp = os.path.join(ROOT, "data", "manifest.json")
    if os.path.exists(mp):
        with open(mp, encoding="utf-8") as f:
            m = json.load(f)
        data = {k: v.get("sha256") for k, v in (m.get("processed") or {}).items()}
    return {"git_commit": git_commit(), "dependencies": versions(), "active_models": active, "processed_data_sha256": data}


# ---------------------------------------------------------------------------- types
def run_control(cfg, out_dir):
    from rl.evaluate import compare, markdown, save
    policy = None
    if "ppo" in cfg["controllers"]:
        from ml.registry import Registry
        act = Registry().active("ppo_policy")
        if act is None:
            cand = sorted(glob.glob(os.path.join(ROOT, "models", "ppo_runs", "v2_seed*", "policy_best.json")))
            if not cand:
                return "BLOCKED", {"reason": "no PPO policy (train with python -m rl.train)"}
            policy = cfg.get("policy") or cand[0]
        else:
            policy = os.path.join(act["path"], "policy.json")
    res = compare(cfg["controllers"], cfg["scenarios"], cfg["seeds"], cfg["days"], policy, workers=cfg.get("workers", 2))
    save(res, out_dir, cfg["title"])
    extra = {}
    for item in cfg.get("extra", []):
        extra[item] = EXTRA[item]()
    if extra:
        with open(os.path.join(out_dir, "extra.json"), "w", encoding="utf-8") as f:
            json.dump(extra, f, indent=1, default=str)
        with open(os.path.join(out_dir, "summary.md"), "a", encoding="utf-8") as f:
            f.write("\n## Additional checks\n\n")
            for k, v in extra.items():
                f.write(f"- **{k}**: {v['result']}\n")
    errors = [r for r in res["runs"] if r["status"] != "ok"]
    consistency = max(abs(r["metrics"]["consistency_room_sum_minus_total_kwh"]) for r in res["runs"] if r["status"] == "ok")
    status = "PASS" if not errors and all(v.get("passed", True) for v in extra.values()) else "FAIL"
    print(markdown(res["summary"], cfg["controllers"]))
    return status, {"policy": policy, "runs": len(res["runs"]), "errors": [e.get("error") for e in errors],
                    "max_room_sum_minus_total_kwh": consistency, "wall_s": res["wall_s"]}


def extra_controller_failure():
    from datetime import datetime as dt
    from twin.runner import run_episode

    class Crashing:
        name = "crashing controller"
        estimator = None

        def decide(self, obs):
            raise RuntimeError("simulated controller crash")
    r = run_episode("mo", "normal", seed=1, start=dt(2026, 3, 2, 8), days=0.25, warmup_days=0.1, controller_obj=Crashing())
    ok = r.metrics["failsafe_F2"] > 0 and r.metrics["energy_kwh"] > 0
    return {"passed": ok, "metrics": r.metrics, "result":
            f"every decision fell back to the rule-based schedule (F2 = {r.metrics['failsafe_F2']:.0f}), the building "
            f"kept running ({r.metrics['energy_kwh']:.0f} kWh in 6 h, discomfort {100 * r.metrics['discomfort_share']:.1f} % "
            f"of occupied time); error recorded: {r.meta.get('last_controller_error')}"}


def extra_model_load_failure():
    import tempfile
    from ml.registry import Registry
    from ml.serving import LiveModels
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "thermal_h30", "v1"))
        with open(os.path.join(d, "thermal_h30", "v1", "model.json"), "w") as f:
            f.write("{corrupted")
        with open(os.path.join(d, "thermal_h30", "v1", "metadata.json"), "w") as f:
            json.dump({"features": []}, f)
        lm = LiveModels(registry=Registry(d))
        s = lm.summary()
    loaded = [m for m in s["models"] if m["loaded"]]
    return {"passed": not loaded, "models": s["models"], "result":
            "a corrupted / missing model is reported as not loaded with its error, and no prediction is produced "
            "(no random or default substitute): " + "; ".join(f"{m['task']}: {m['error']}" for m in s["models"])}


def extra_ppo_seed_variability():
    """Every PPO training run's best policy on the same evaluation (normal scenario, seeds 1-3)."""
    from rl.evaluate import compare
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "models", "ppo_runs", "v2_seed*", "policy_best.json"))):
        run = os.path.basename(os.path.dirname(path))
        res = compare(["ppo"], ["normal"], [1, 2, 3], 7.0, path, workers=2)
        m = res["summary"]["normal"]["ppo"]
        out[run] = {k: m.get(k) for k in ("energy_kwh", "energy_kwh_sd", "discomfort_share", "discomfort_share_sd",
                                          "discomfort_pmv_h", "iaq_min", "light_switches", "hvac_changes", "failsafe_F2")}
    txt = "; ".join(f"{k}: {v['energy_kwh']:.0f} kWh, discomfort {100 * v['discomfort_share']:.1f} %" for k, v in out.items())
    return {"passed": bool(out), "runs": out, "result": f"best policy of each training run on normal/seeds 1-3 - {txt}"}


def extra_ppo_confirmation_new_seeds():
    """The approved PPO policy against the schedule and the optimiser on seeds 4-6. The reward was redesigned
    (v1 -> v2) after v1's evaluation on seeds 1-3, so this checks the result on seeds that played no part in
    that decision (and were never used for training: training uses simulator seeds >= 1000)."""
    from ml.registry import Registry
    from rl.evaluate import compare
    act = Registry().active("ppo_policy")
    if act is None:
        return {"passed": False, "result": "no approved ppo_policy version"}
    res = compare(["schedule", "mo", "ppo"], ["normal"], [4, 5, 6], 7.0, os.path.join(act["path"], "policy.json"),
                  workers=2)
    errors = [r.get("error") for r in res["runs"] if r["status"] != "ok"]
    s = res["summary"]["normal"]
    keys = ("energy_kwh", "energy_kwh_sd", "savings_vs_schedule_pct", "discomfort_share", "discomfort_pmv_h",
            "iaq_min", "ac_cycles", "light_switches")
    out = {c: {k: s[c].get(k) for k in keys} for c in ("schedule", "mo", "ppo") if c in s}
    txt = "; ".join(f"{c}: {v['energy_kwh']:.0f} kWh ({v['savings_vs_schedule_pct']:+.1f} % vs schedule), "
                    f"discomfort {100 * v['discomfort_share']:.1f} %, AC cycles {v['ac_cycles']:.0f}" for c, v in out.items())
    return {"passed": not errors, "errors": errors, "version": act.get("version"), "runs": out,
            "result": f"ppo_policy {act.get('version')} on normal / seeds 4-6 (not used in the reward redesign) - {txt}"}


EXTRA = {"controller_failure": extra_controller_failure, "model_load_failure": extra_model_load_failure,
         "ppo_seed_variability": extra_ppo_seed_variability,
         "ppo_confirmation_new_seeds": extra_ppo_confirmation_new_seeds}


def run_ml(cfg, out_dir):
    import importlib
    mod = importlib.import_module(cfg["module"])
    rc = mod.main(["--no-register"])        # reproduce the evaluation; registering is a separate decision
    report = {"ml.occupancy": "occupancy.md", "ml.thermal": "thermal.md", "ml.energy": "energy.md"}[cfg["module"]]
    src = os.path.join(ROOT, "docs", "results", report)
    if os.path.exists(src):
        with open(src, encoding="utf-8") as f, open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as g:
            g.write(f.read())
    return ("PASS" if rc == 0 else "FAIL"), {"report": os.path.relpath(src, ROOT)}


def run_consistency(cfg, out_dir):
    from datetime import datetime as dt
    from twin.building import TwinBuilding
    from twin.live import LiveTwin
    from twin.spec import build_spec
    checks = []
    b = TwinBuilding(build_spec(), 1, dt(2026, 3, 2))
    for rid in b.ids:
        b.apply(rid, "ON", "NORMAL", 24.0)
    b.advance(24 * 3600)
    total = b.energy_wh
    checks.append(("sum of rooms = building", sum(b.physics[r].total_energy_wh for r in b.ids), total))
    checks.append(("sum of floors = building", sum(b.energy_by_floor_wh().values()), total))
    checks.append(("sum of end uses = building", sum(b.energy_by_end_use_wh().values()), total))
    # every comparison run recorded its own room-sum check
    for p in glob.glob(os.path.join(RESULTS, "exp0[5-8]_*", "results.json")) + glob.glob(os.path.join(RESULTS, "exp01_*", "results.json")):
        with open(p, encoding="utf-8") as f:
            res = json.load(f)
        worst = max((abs(r["metrics"]["consistency_room_sum_minus_total_kwh"]) for r in res["runs"] if r["status"] == "ok"),
                    default=0.0)
        checks.append((f"{os.path.basename(os.path.dirname(p))}: room sum - total (max over runs, kWh)", worst, 0.0))
    lt = LiveTwin(seed=7, warmup=False)
    e_before = sum(lt.ctrl.physics[r].total_energy_wh for r in lt.ids) / 1000.0
    seg_before = sum(s["kwh"] for s in lt.segments)
    for _ in range(180):
        lt.control_step(measure=True)
    seg_kwh = sum(s["kwh"] for s in lt.segments) - seg_before
    rooms_kwh = sum(lt.ctrl.physics[r].total_energy_wh for r in lt.ids) / 1000.0 - e_before
    checks.append(("live twin: meter segments = energy of the 25 rooms over 3 simulated hours (kWh)", seg_kwh, rooms_kwh))
    rows = [{"check": c, "value": float(v), "expected": float(e), "abs_diff": abs(float(v) - float(e)),
             "passed": abs(float(v) - float(e)) <= 1e-6 * max(1.0, abs(float(e)))} for c, v, e in checks]
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# {cfg['title']}\n\n| check | value | expected | difference | result |\n|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['check']} | {r['value']:.6f} | {r['expected']:.6f} | {r['abs_diff']:.2e} | {'PASS' if r['passed'] else 'FAIL'} |\n")
    for r in rows:
        print(("PASS " if r["passed"] else "FAIL ") + r["check"], r["abs_diff"])
    return ("PASS" if all(r["passed"] for r in rows) else "FAIL"), {"checks": rows}


def run_live_room(cfg, out_dir):
    """HTTP and MQTT paths with a simulated board (no physical board in this environment)."""
    import asyncio
    import socket
    import tempfile
    import threading
    import raspberry_pi.edge_brain as eb
    from raspberry_pi.edge_brain import HARDWARE_IDS, HARDWARE_ROOM_ID, EdgeBrain
    from raspberry_pi.mqtt_bridge import MqttBridge
    checks = []
    tmp = tempfile.mkdtemp()
    brain = EdgeBrain(speed_factor=360, warmup=False, store_path=os.path.join(tmp, "edge.sqlite3"))
    eb.brain = brain
    c = eb.app.test_client()
    st = c.get("/api/hardware/status").get_json()
    checks.append(("no board: room 101 shown as never connected", st["rooms"][0]["state"] == "never_connected"))
    # HTTP path (the firmware's transport), with the HTTP test sender's payload
    r = c.post("/api/hardware/sensor-data", json={"room_id": HARDWARE_ROOM_ID, "source": "test_sender", "temperature": 27.1,
                                                  "humidity": 64.0, "lux": 150.0, "co2": 700.0, "co2_source": "scd41_ndir",
                                                  "motion_detected": True, "presence": True})
    checks.append(("HTTP reading accepted and a decision returned", r.status_code == 200 and "fan_speed" in r.get_json()))
    room = next(x for x in brain.get_current_state()["rooms"] if x["room_id"] == HARDWARE_ROOM_ID)
    checks.append(("room 101 connected, values shown exactly", room["hardware"]["connected"] and room["sensors"]["Temperature"] == 27.1))
    checks.append(("test-sender data labelled synthetic, not measured", room["provenance"]["sensors"] == "synthetic"))
    # MQTT path with an in-process broker and the simulated device
    try:
        from amqtt.broker import Broker
    except ImportError:
        return "BLOCKED", {"reason": "amqtt not installed (pip install -r requirements/dev.txt)", "checks": checks}
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    loop = asyncio.new_event_loop()
    broker = Broker({"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}}, "sys_interval": 0,
                     "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]}, "topic-check": {"enabled": False}}, loop=loop)
    threading.Thread(target=lambda: (asyncio.set_event_loop(loop), loop.run_until_complete(broker.start()), loop.run_forever()),
                     daemon=True).start()
    time.sleep(1.5)
    bridge = MqttBridge(brain.inject_hardware_data, HARDWARE_IDS, store=brain.store, host="127.0.0.1", port=port,
                        client_id="exp10-edge")
    brain.mqtt = bridge
    bridge.start()
    t0 = time.time()
    while not bridge.connected and time.time() - t0 < 10:
        time.sleep(0.1)
    checks.append(("edge connected to the MQTT broker", bridge.connected))
    from raspberry_pi import mqtt_device_sim
    n = int(cfg.get("messages", 40))
    rc = mqtt_device_sim.main(["--host", "127.0.0.1", "--port", str(port), "--interval", str(cfg.get("interval_s", 0.2)),
                               "--count", str(n), "--duplicate-every", "10", "--bad-every", "13"])
    time.sleep(1.5)
    stats = bridge.status()["stats"]
    dup = n // 10
    checks.append(("device harness ran", rc == 0))
    checks.append((f"{n - dup} unique readings accepted, {dup} duplicates dropped",
                   stats["accepted"] == n - dup and stats["duplicates"] == dup))
    checks.append(("out-of-range values dropped and reported", stats["field_problems"] >= n // 13))
    checks.append(("every command acknowledged", stats["acks"] == stats["commands_sent"] and stats["ack_timeouts"] == 0))
    summ = brain.store.summary()
    checks.append(("readings stored with provenance synthetic (harness)", summ["provenance"]["readings"].get("synthetic", 0) >= n - dup))
    checks.append(("no harness reading stored as room101_measured", summ["provenance"]["readings"].get("room101_measured", 0) == 0))
    st = c.get("/api/hardware/mqtt").get_json()
    checks.append(("MQTT status endpoint reports the bridge", st["connected"] is True))
    # staleness: no reading for longer than the timeout
    link = brain.links[HARDWARE_ROOM_ID]
    link.last_rx_mono -= eb.HW_TIMEOUT_S + 1
    brain.tick(0.5)
    room = next(x for x in brain.get_current_state()["rooms"] if x["room_id"] == HARDWARE_ROOM_ID)
    checks.append(("silent board -> room shown as lost, no values", room["hardware"]["state"] == "lost"
                   and room["sensors"]["Temperature"] is None and room["freshness"]["stale"] is True))
    bridge.stop()
    asyncio.run_coroutine_threadsafe(broker.shutdown(), loop)
    rows = [{"check": k, "passed": bool(v)} for k, v in checks]
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(f"# {cfg['title']}\n\nTest harness: HTTP test payload and raspberry_pi/mqtt_device_sim.py over a local "
                "MQTT broker (amqtt). **Physical verification with the ESP32-S3 board: not performed in this "
                "environment (no board attached).**\n\n| check | result |\n|---|---|\n")
        for r in rows:
            f.write(f"| {r['check']} | {'PASS' if r['passed'] else 'FAIL'} |\n")
        f.write(f"\nBridge statistics: {json.dumps(stats)}\n\nStore: {json.dumps(summ['tables'])}\n")
    for r in rows:
        print(("PASS " if r["passed"] else "FAIL ") + r["check"])
    return ("PASS" if all(r["passed"] for r in rows) else "FAIL"), {"checks": rows, "bridge_stats": stats,
                                                                     "physical_verification": "not performed (no board)"}


RUNNERS = {"control_comparison": run_control, "ml_script": run_ml, "consistency": run_consistency, "live_room": run_live_room}


def run(cfg: dict) -> dict:
    out_dir = os.path.join(RESULTS, cfg["id"])
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    started = datetime.now().isoformat(timespec="seconds")
    t0 = time.perf_counter()
    log = io.StringIO()

    class Tee(io.TextIOBase):
        def write(self, s):
            sys.__stdout__.write(s)
            log.write(s)
            return len(s)

    status, info = "ERROR", {}
    with contextlib.redirect_stdout(Tee()):
        try:
            print(f"== {cfg['id']}: {cfg['title']}")
            status, info = RUNNERS[cfg["type"]](cfg, out_dir)
        except Exception as e:
            info = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()}
            print(info["traceback"])
    st = {"id": cfg["id"], "title": cfg["title"], "status": status, "started": started,
          "finished": datetime.now().isoformat(timespec="seconds"), "wall_s": round(time.perf_counter() - t0, 1),
          "question": cfg.get("question"), "info": info, **versions_snapshot()}
    with open(os.path.join(out_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, default=str)
    with open(os.path.join(out_dir, "log.txt"), "w", encoding="utf-8") as f:
        f.write(log.getvalue())
    print(f"== {cfg['id']}: {status} ({st['wall_s']} s)")
    return st


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--seeds", type=int, nargs="+")
    ap.add_argument("--days", type=float)
    args = ap.parse_args(argv)
    cfgs = load_configs()
    if args.list:
        for k, c in cfgs.items():
            print(f"{k:28s} {c['title']}")
        return 0
    ids = list(cfgs) if args.all else args.ids
    bad = [i for i in ids if i not in cfgs]
    if bad or not ids:
        ap.error(f"unknown or no experiment ids: {bad}")
    statuses = []
    for i in ids:
        cfg = dict(cfgs[i])
        if args.seeds:
            cfg["seeds"] = args.seeds
        if args.days:
            cfg["days"] = args.days
        statuses.append(run(cfg))
    print("\n".join(f"{s['id']:28s} {s['status']}" for s in statuses))
    return 0 if all(s["status"] in ("PASS", "BLOCKED") for s in statuses) else 1


if __name__ == "__main__":
    sys.exit(main())
