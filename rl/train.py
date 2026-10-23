#!/usr/bin/env python3
"""
Train the PPO building controller offline in the digital twin (never on the real room).

    python -m rl.train --seed 0                          # one training run (160 one-day episodes)
    python -m rl.train --seed 0 --episodes 2 --days 0.5  # smoke test

Each episode: a random training scenario (rl/env.py TRAIN_SCENARIOS), a random start date in
2026, a fresh simulator seed (1000 + 1000 x run seed + episode; the evaluation seeds 1-3 are
never used for training), 1 simulated day with decisions every 5 min for all 25 rooms (one
shared policy; 7 200 room-decisions per episode).  After each episode one PPO update.
Every `--eval-every` episodes the deterministic policy is scored on a fixed validation episode
(seed 999, normal scenario); the best-scoring policy is kept.

Outputs: models/ppo_runs/v2_seed<k>/{policy_best.json, policy_last.json, train_log.csv, config.json}
(models/ppo_runs/seed0, seed1: the first runs with reward v1, kept for the record)
Register the chosen run with `python -m rl.evaluate --register` (after the comparison).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rl.env import REWARD_WEIGHTS, TRAIN_SCENARIOS, BuildingVecEnv   # noqa: E402
from rl.policy import N_ACT, N_OBS                                    # noqa: E402
from rl.ppo import PPO, Policy, PPOConfig, gae                        # noqa: E402

RUNS = os.path.join(ROOT, "models", "ppo_runs")
VAL_SEED, VAL_START = 999, datetime(2026, 4, 6)


def run_validation(pi: Policy, days: float) -> dict:
    env = BuildingVecEnv(days=days)
    obs = env.reset(seed=VAL_SEED, scenario="normal", start=VAL_START)
    total, energy, disc, n = 0.0, 0.0, 0.0, 0
    while True:
        a, _, _ = pi.act(obs, deterministic=True)
        obs, r, done, info = env.step(a)
        total += float(r.sum())
        energy += info["energy_wh"]
        disc += info["discomfort"]
        n += 1
        if done:
            break
    return {"val_return": total / len(env.ids), "val_energy_kwh": energy / 1000.0, "val_discomfort": disc / n}


def train(seed: int, episodes: int, days: float, eval_every: int, cfg: PPOConfig, out_dir: str,
          ent_final: float = 0.001) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(seed)
    pi = Policy(N_OBS, N_ACT, hidden=cfg.hidden, seed=seed)
    ppo = PPO(pi, cfg, seed=seed)
    env = BuildingVecEnv(days=days)
    config = {"seed": seed, "episodes": episodes, "days_per_episode": days, "ppo": asdict(cfg),
              "reward_weights": REWARD_WEIGHTS, "train_scenarios": TRAIN_SCENARIOS, "n_obs": N_OBS, "n_act": N_ACT,
              "validation": {"seed": VAL_SEED, "start": VAL_START.isoformat(), "scenario": "normal"},
              "started": datetime.now().isoformat(timespec="seconds")}
    with open(os.path.join(out_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    log_path = os.path.join(out_dir, "train_log.csv")
    best = -1e18
    t_start = time.perf_counter()
    with open(log_path, "w", newline="", encoding="utf-8") as logf:
        w = None
        for ep in range(episodes):
            scenario = TRAIN_SCENARIOS[int(rng.integers(len(TRAIN_SCENARIOS)))]
            start = datetime(2026, 1, 5) + timedelta(days=int(rng.integers(0, 350)))
            sim_seed = 1000 + 1000 * seed + ep
            obs = env.reset(seed=sim_seed, scenario=scenario, start=start)
            O, A, L, R, V = [], [], [], [], []
            ep_energy, ep_disc = 0.0, 0.0
            t0 = time.perf_counter()
            while True:
                a, lp, _ = pi.act(obs, rng)
                V.append(pi.value(obs))
                O.append(obs); A.append(a); L.append(lp)
                obs, r, done, info = env.step(a)
                R.append(r)
                ep_energy += info["energy_wh"]
                ep_disc += info["discomfort"]
                if done:
                    break
            O, A, L, R, V = (np.asarray(x) for x in (O, A, L, R, V))
            last_v = pi.value(obs)                       # truncation: bootstrap
            D = np.zeros_like(R)
            adv, ret = gae(R, V, last_v, D, cfg.gamma, cfg.lam)
            frac = 1.0 - ep / episodes
            ent = ent_final + (cfg.ent_coef - ent_final) * frac
            stats = ppo.update(O.reshape(-1, N_OBS), A.reshape(-1), L.reshape(-1), adv.reshape(-1), ret.reshape(-1),
                               lr_frac=max(0.1, frac), ent_coef=ent)
            row = {"episode": ep, "scenario": scenario, "start": start.date().isoformat(), "sim_seed": sim_seed,
                   "mean_reward": float(R.mean()), "episode_return_per_room": float(R.sum(axis=0).mean()),
                   "energy_kwh": ep_energy / 1000.0, "discomfort": ep_disc / len(R),
                   "sim_s": time.perf_counter() - t0, **stats}
            if eval_every and (ep + 1) % eval_every == 0 or ep == episodes - 1:
                val = run_validation(pi, days=1.0)
                row.update(val)
                if val["val_return"] > best:
                    best = val["val_return"]
                    pi.save(os.path.join(out_dir, "policy_best.json"),
                            meta={"episode": ep, **val, "seed": seed, "config": config})
            if w is None:
                fields = list(row.keys()) + ["val_return", "val_energy_kwh", "val_discomfort"]
                w = csv.DictWriter(logf, fieldnames=list(dict.fromkeys(fields)))
                w.writeheader()
            w.writerow(row)
            logf.flush()
            print(f"seed {seed} ep {ep:3d} {scenario:16s} R/step {row['mean_reward']:.4f} E {row['energy_kwh']:7.0f} kWh "
                  f"disc {row['discomfort']:.3f} ent {stats['entropy']:.3f} kl {stats['approx_kl']:.4f}"
                  + (f" | val {row['val_return']:.2f}" if "val_return" in row else ""), flush=True)
    pi.save(os.path.join(out_dir, "policy_last.json"), meta={"episode": episodes - 1, "seed": seed, "config": config})
    return {"seed": seed, "best_val_return": best, "wall_s": time.perf_counter() - t_start, "out_dir": out_dir}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--episodes", type=int, default=160)
    ap.add_argument("--days", type=float, default=1.0)
    ap.add_argument("--eval-every", type=int, default=5)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--minibatch", type=int, default=512)
    ap.add_argument("--ent", type=float, default=0.005)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    cfg = PPOConfig(lr=args.lr, epochs=args.epochs, minibatch=args.minibatch, ent_coef=args.ent)
    out = args.out or os.path.join(RUNS, f"v2_seed{args.seed}")      # reward v2 (rl/env.py); v1 runs: seed0, seed1
    res = train(args.seed, args.episodes, args.days, args.eval_every, cfg, out)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
