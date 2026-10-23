"""
Proximal Policy Optimization (clipped surrogate, GAE) in numpy.

Why numpy and not stable-baselines3: the earlier SB3 agent (archived) needed PyTorch, which
cannot be installed in the development environment (no CPU wheel index reachable) and is a
heavy dependency for a Raspberry Pi 4B.  The algorithm is the same PPO (Schulman et al.
2017): clipped surrogate objective, generalized advantage estimation (Schulman et al.
2016), value-function loss, entropy bonus, Adam, gradient-norm clipping, minibatch epochs.
Correctness is checked on CartPole-v1 (rl/cartpole_check.py) before use on the building.

Networks: separate actor and critic MLPs (tanh hidden layers), categorical policy over a
discrete action set.  Inference needs numpy only (Policy.act / Policy.probs).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ====================================================================== network
class MLP:
    """Fully connected net: tanh hidden layers, linear output.  Manual backprop."""

    def __init__(self, sizes: Sequence[int], rng: np.random.Generator, out_gain: float = 1.0):
        self.sizes = list(sizes)
        self.W: List[np.ndarray] = []
        self.b: List[np.ndarray] = []
        for i, (a, c) in enumerate(zip(sizes[:-1], sizes[1:])):
            gain = out_gain if i == len(sizes) - 2 else math.sqrt(2.0)
            q, _ = np.linalg.qr(rng.standard_normal((max(a, c), min(a, c))))   # orthogonal init
            w = q[:a, :c] if a >= c else q[:c, :a].T
            self.W.append((gain * w).astype(np.float64))
            self.b.append(np.zeros(c))

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, List[np.ndarray]]:
        acts = [x]
        h = x
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            h = h @ W + b
            if i < len(self.W) - 1:
                h = np.tanh(h)
            acts.append(h)
        return h, acts

    def backward(self, acts: List[np.ndarray], grad_out: np.ndarray) -> List[np.ndarray]:
        """Gradients [dW0, db0, dW1, db1, ...] of sum(grad_out * output)."""
        grads: List[np.ndarray] = [None] * (2 * len(self.W))
        g = grad_out
        for i in reversed(range(len(self.W))):
            a_in = acts[i]
            grads[2 * i] = a_in.T @ g
            grads[2 * i + 1] = g.sum(axis=0)
            if i > 0:
                g = (g @ self.W[i].T) * (1.0 - acts[i] ** 2)     # tanh'
        return grads

    def params(self) -> List[np.ndarray]:
        out = []
        for W, b in zip(self.W, self.b):
            out += [W, b]
        return out

    def to_dict(self) -> Dict:
        return {"sizes": self.sizes, "W": [w.tolist() for w in self.W], "b": [b.tolist() for b in self.b]}

    @classmethod
    def from_dict(cls, d: Dict) -> "MLP":
        m = cls.__new__(cls)
        m.sizes = list(d["sizes"])
        m.W = [np.asarray(w, dtype=np.float64) for w in d["W"]]
        m.b = [np.asarray(b, dtype=np.float64) for b in d["b"]]
        return m


class Adam:
    def __init__(self, params: List[np.ndarray], lr: float = 3e-4, b1: float = 0.9, b2: float = 0.999, eps: float = 1e-5):
        self.params, self.lr, self.b1, self.b2, self.eps = params, lr, b1, b2, eps
        self.m = [np.zeros_like(p) for p in params]
        self.v = [np.zeros_like(p) for p in params]
        self.t = 0

    def step(self, grads: List[np.ndarray]) -> None:
        self.t += 1
        for p, g, m, v in zip(self.params, grads, self.m, self.v):
            m *= self.b1
            m += (1 - self.b1) * g
            v *= self.b2
            v += (1 - self.b2) * g * g
            mh = m / (1 - self.b1 ** self.t)
            vh = v / (1 - self.b2 ** self.t)
            p -= self.lr * mh / (np.sqrt(vh) + self.eps)


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


# ====================================================================== policy
class Policy:
    """Actor-critic pair.  act() samples (training) or takes the most likely action (deployment)."""

    def __init__(self, n_obs: int, n_act: int, hidden: Sequence[int] = (64, 64), seed: int = 0):
        rng = np.random.default_rng(seed)
        self.n_obs, self.n_act = n_obs, n_act
        self.actor = MLP([n_obs, *hidden, n_act], rng, out_gain=0.01)
        self.critic = MLP([n_obs, *hidden, 1], rng, out_gain=1.0)
        self.meta: Dict = {}

    def probs(self, obs: np.ndarray) -> np.ndarray:
        logits, _ = self.actor.forward(np.atleast_2d(obs))
        return _softmax(logits)

    def value(self, obs: np.ndarray) -> np.ndarray:
        v, _ = self.critic.forward(np.atleast_2d(obs))
        return v[:, 0]

    def act(self, obs: np.ndarray, rng: Optional[np.random.Generator] = None, deterministic: bool = False):
        p = self.probs(obs)
        if deterministic or rng is None:
            a = p.argmax(axis=1)
        else:
            u = rng.random((p.shape[0], 1))
            a = (p.cumsum(axis=1) < u).sum(axis=1)
            a = np.minimum(a, self.n_act - 1)
        logp = np.log(p[np.arange(len(a)), a] + 1e-12)
        return a, logp, p

    def save(self, path: str, meta: Optional[Dict] = None) -> None:
        d = {"format": "smartbuilding-ppo/1", "n_obs": self.n_obs, "n_act": self.n_act,
             "actor": self.actor.to_dict(), "critic": self.critic.to_dict(), "meta": meta or self.meta}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f)

    @classmethod
    def load(cls, path: str) -> "Policy":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("format") != "smartbuilding-ppo/1":
            raise ValueError(f"{path}: not a PPO policy file")
        p = cls.__new__(cls)
        p.n_obs, p.n_act = int(d["n_obs"]), int(d["n_act"])
        p.actor, p.critic = MLP.from_dict(d["actor"]), MLP.from_dict(d["critic"])
        p.meta = d.get("meta", {})
        if p.actor.sizes[0] != p.n_obs or p.actor.sizes[-1] != p.n_act:
            raise ValueError(f"{path}: network shape does not match n_obs/n_act")
        return p


# ====================================================================== PPO update
@dataclass
class PPOConfig:
    gamma: float = 0.99
    lam: float = 0.95
    clip: float = 0.2
    lr: float = 3e-4
    epochs: int = 8
    minibatch: int = 1024
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    hidden: Tuple[int, ...] = (64, 64)


def gae(rewards: np.ndarray, values: np.ndarray, last_value: np.ndarray, dones: np.ndarray,
        gamma: float, lam: float) -> Tuple[np.ndarray, np.ndarray]:
    """rewards/values/dones shaped (T, N); last_value (N,) bootstraps the step after T-1.
    dones[t] = 1 when the episode TERMINATED after step t (no bootstrap)."""
    T = rewards.shape[0]
    adv = np.zeros_like(rewards)
    last = np.zeros(rewards.shape[1])
    for t in reversed(range(T)):
        nv = last_value if t == T - 1 else values[t + 1]
        nonterm = 1.0 - dones[t]
        delta = rewards[t] + gamma * nv * nonterm - values[t]
        last = delta + gamma * lam * nonterm * last
        adv[t] = last
    return adv, adv + values


class PPO:
    def __init__(self, policy: Policy, cfg: PPOConfig, seed: int = 0):
        self.pi, self.cfg = policy, cfg
        self.rng = np.random.default_rng(seed)
        self.opt_a = Adam(policy.actor.params(), lr=cfg.lr)
        self.opt_c = Adam(policy.critic.params(), lr=cfg.lr)

    @staticmethod
    def _clip(grads: List[np.ndarray], max_norm: float) -> float:
        norm = math.sqrt(sum(float((g * g).sum()) for g in grads))
        if norm > max_norm:
            for g in grads:
                g *= max_norm / (norm + 1e-8)
        return norm

    def update(self, obs: np.ndarray, act: np.ndarray, logp_old: np.ndarray, adv: np.ndarray, ret: np.ndarray,
               lr_frac: float = 1.0, ent_coef: Optional[float] = None) -> Dict[str, float]:
        c = self.cfg
        ent_coef = c.ent_coef if ent_coef is None else ent_coef
        self.opt_a.lr = self.opt_c.lr = c.lr * lr_frac
        n = len(obs)
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
        stats = {"pi_loss": 0.0, "v_loss": 0.0, "entropy": 0.0, "approx_kl": 0.0, "clip_frac": 0.0}
        count = 0
        for _ in range(c.epochs):
            idx = self.rng.permutation(n)
            for s in range(0, n, c.minibatch):
                mb = idx[s:s + c.minibatch]
                o, a, lo, A, R = obs[mb], act[mb], logp_old[mb], adv[mb], ret[mb]
                m = len(mb)
                # ---- actor
                logits, acts = self.pi.actor.forward(o)
                p = _softmax(logits)
                lp_all = np.log(p + 1e-12)
                lp = lp_all[np.arange(m), a]
                ratio = np.exp(lp - lo)
                clipped = np.clip(ratio, 1 - c.clip, 1 + c.clip)
                use_unclipped = (ratio * A) <= (clipped * A)        # min picks the unclipped term
                # d(-min)/d lp = -A * ratio where the unclipped term is active, else 0
                d_lp = np.where(use_unclipped, -A * ratio, 0.0) / m
                onehot = np.zeros_like(p)
                onehot[np.arange(m), a] = 1.0
                g_logits = d_lp[:, None] * (onehot - p)
                ent = -(p * lp_all).sum(axis=1)
                # d(-ent_coef * H)/d logits = ent_coef * p * (log p + H)
                g_logits += ent_coef * p * (lp_all + ent[:, None]) / m
                ga = self.pi.actor.backward(acts, g_logits)
                self._clip(ga, c.max_grad_norm)
                self.opt_a.step(ga)
                # ---- critic
                v, cacts = self.pi.critic.forward(o)
                v = v[:, 0]
                g_v = (c.vf_coef * 2.0 * (v - R) / m)[:, None]
                gc = self.pi.critic.backward(cacts, g_v)
                self._clip(gc, c.max_grad_norm)
                self.opt_c.step(gc)
                stats["pi_loss"] += float(-np.minimum(ratio * A, clipped * A).mean())
                stats["v_loss"] += float(((v - R) ** 2).mean())
                stats["entropy"] += float(ent.mean())
                stats["approx_kl"] += float((lo - lp).mean())
                stats["clip_frac"] += float((np.abs(ratio - 1) > c.clip).mean())
                count += 1
        return {k: v / max(1, count) for k, v in stats.items()}
