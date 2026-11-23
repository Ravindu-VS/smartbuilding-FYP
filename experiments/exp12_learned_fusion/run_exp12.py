import sys, time, json
from twin.runner import run_episode, make_controller, DEFAULT_START
from twin.spec import build_spec
ctrl_name, seed, days, warm = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
specs = build_spec(); transit = {r.room_id for r in specs if r.transit}
ctrl = make_controller(ctrl_name, specs)
conf = {"all": [0, 0, 0, 0], "rooms": [0, 0, 0, 0]}   # tp fp fn tn
orig = ctrl.decide
def decide(o, *a, **k):
    d = orig(o, *a, **k)
    if o.timestamp >= DEFAULT_START and o.true_occupants is not None:
        p = d.occupancy_probability; pred = p is not None and p >= 0.5; truth = o.true_occupants > 0
        i = 0 if pred and truth else 1 if pred else 2 if truth else 3
        conf["all"][i] += 1
        if o.room_id not in transit: conf["rooms"][i] += 1
    return d
ctrl.decide = decide
t = time.time(); r = run_episode(ctrl_name, "normal", seed, days=days, warmup_days=warm, controller_obj=ctrl)
m = r.metrics
def summ(c):
    tp, fp, fn, tn = c; n = sum(c); pr = tp / (tp + fp) if tp + fp else 0; rc = tp / (tp + fn) if tp + fn else 0
    return {"acc": round((tp + tn) / n, 4), "f1": round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0, "prec": round(pr, 4), "rec": round(rc, 4)}
out = {"controller": ctrl_name, "seed": seed, "wall_s": round(time.time() - t, 1),
       "energy_kwh": round(m["energy_kwh"], 1), "discomfort_pct": round(100 * m["discomfort_min"] / max(1, m["occupied_min"]), 2),
       "pmv_h": round(m["discomfort_pmv_h"], 1), "iaq_min": m["iaq_min"], "ac_cycles": m["ac_cycles"], "light_switches": m["light_switches"],
       "occ_all": summ(conf["all"]), "occ_rooms": summ(conf["rooms"])}
print(json.dumps(out)); sys.stdout.flush()
