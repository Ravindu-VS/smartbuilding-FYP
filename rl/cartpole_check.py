#!/usr/bin/env python3
"""
Correctness check of the numpy PPO on a standard benchmark (gymnasium CartPole-v1).

    python -m rl.cartpole_check

Passes when the deterministic policy averages >= 475 steps over 20 evaluation episodes
(CartPole-v1's "solved" threshold is 475).  Writes experiments/results/ppo_cartpole.json.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rl.ppo import PPO, Policy, PPOConfig, gae      # noqa: E402


def run(seed: int = 0, iterations: int = 60, n_env: int = 8, steps: int = 256) -> dict:
    import gymnasium as gym
    envs = [gym.make("CartPole-v1") for _ in range(n_env)]
    obs = np.stack([e.reset(seed=seed * 100 + i)[0] for i, e in enumerate(envs)])
    pi = Policy(4, 2, seed=seed)
    ppo = PPO(pi, PPOConfig(lr=1e-3, epochs=10, minibatch=256, ent_coef=0.0), seed=seed)
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    curve = []
    ep_len = np.zeros(n_env)
    finished = []
    for it in range(iterations):
        O = np.zeros((steps, n_env, 4)); A = np.zeros((steps, n_env), int); L = np.zeros((steps, n_env))
        R = np.zeros((steps, n_env)); D = np.zeros((steps, n_env)); V = np.zeros((steps, n_env))
        for t in range(steps):
            a, lp, _ = pi.act(obs, rng)
            V[t] = pi.value(obs)
            O[t], A[t], L[t] = obs, a, lp
            for i, e in enumerate(envs):
                o2, r, term, trunc, _ = e.step(int(a[i]))
                R[t, i] = r
                ep_len[i] += 1
                if trunc and not term:                       # bootstrap through time-limit truncation
                    R[t, i] += ppo.cfg.gamma * float(pi.value(o2)[0])
                if term or trunc:
                    D[t, i] = 1.0
                    finished.append(ep_len[i])
                    ep_len[i] = 0
                    o2, _ = e.reset()
                obs[i] = o2
        adv, ret = gae(R, V, pi.value(obs), D, ppo.cfg.gamma, ppo.cfg.lam)
        ppo.update(O.reshape(-1, 4), A.reshape(-1), L.reshape(-1), adv.reshape(-1), ret.reshape(-1),
                   lr_frac=1.0 - it / iterations)
        curve.append(float(np.mean(finished[-20:])) if finished else 0.0)
    # deterministic evaluation
    env = gym.make("CartPole-v1")
    lens = []
    for k in range(20):
        o, _ = env.reset(seed=10_000 + k)
        n = 0
        while True:
            a, _, _ = pi.act(o[None, :], deterministic=True)
            o, r, term, trunc, _ = env.step(int(a[0]))
            n += 1
            if term or trunc:
                break
        lens.append(n)
    return {"seed": seed, "iterations": iterations, "env_steps": iterations * steps * n_env,
            "train_curve_last20_mean_len": curve, "eval_mean_len": float(np.mean(lens)), "eval_min_len": int(min(lens)),
            "passed": bool(np.mean(lens) >= 475), "wall_s": time.perf_counter() - t0}


def main() -> int:
    results = [run(seed) for seed in (0, 1, 2)]
    for r in results:
        print(f"seed {r['seed']}: eval mean {r['eval_mean_len']:.1f} (min {r['eval_min_len']}) "
              f"{'PASS' if r['passed'] else 'FAIL'} in {r['wall_s']:.0f} s")
    out = os.path.join(ROOT, "experiments", "results", "ppo_cartpole.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
