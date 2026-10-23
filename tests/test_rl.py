"""RL: PPO maths, environment API, shapes, rewards, constraints, save/load, inference, safety and failure."""
import math
import os
from datetime import datetime, timedelta

import numpy as np
import pytest

from rl.policy import ACTIONS, AC_DWELL_S, N_ACT, N_OBS, PPOController, action_command
from rl.ppo import PPO, Policy, PPOConfig, _softmax, gae
from twin.controllers import Observation
from twin.runner import run_episode
from twin.safety import SETPOINT_RANGE


def test_actor_and_critic_gradients_match_finite_differences():
    rng = np.random.default_rng(0)
    pi = Policy(5, 4, hidden=(7, 6), seed=1)
    o = rng.standard_normal((9, 5)); a = rng.integers(0, 4, 9); lo = np.log(rng.uniform(0.1, 0.5, 9))
    A = rng.standard_normal(9); clip, ec = 0.2, 0.05

    def loss():
        p = _softmax(pi.actor.forward(o)[0]); lp = np.log(p[np.arange(9), a] + 1e-12)
        r = np.exp(lp - lo); c = np.clip(r, 1 - clip, 1 + clip)
        return -np.minimum(r * A, c * A).mean() - ec * (-(p * np.log(p + 1e-12)).sum(1)).mean()

    logits, acts = pi.actor.forward(o); p = _softmax(logits); lp_all = np.log(p + 1e-12); lp = lp_all[np.arange(9), a]
    ratio = np.exp(lp - lo); use = (ratio * A) <= (np.clip(ratio, 1 - clip, 1 + clip) * A)
    oh = np.zeros_like(p); oh[np.arange(9), a] = 1
    g = (np.where(use, -A * ratio, 0.0) / 9)[:, None] * (oh - p)
    ent = -(p * lp_all).sum(1); g += ec * p * (lp_all + ent[:, None]) / 9
    grads = pi.actor.backward(acts, g)
    for P, G in zip(pi.actor.params(), grads):
        idx = tuple(rng.integers(0, s) for s in P.shape)
        old = P[idx]; P[idx] = old + 1e-6; l1 = loss(); P[idx] = old - 1e-6; l2 = loss(); P[idx] = old
        assert abs((l1 - l2) / 2e-6 - G[idx]) < 1e-7


def test_gae_known_values():
    r = np.array([[1.0], [1.0], [1.0]]); v = np.zeros((3, 1)); d = np.zeros((3, 1))
    adv, ret = gae(r, v, np.zeros(1), d, gamma=1.0, lam=1.0)
    assert np.allclose(adv[:, 0], [3, 2, 1])
    d[1] = 1.0                                          # terminated after step 1: no bootstrap across
    adv, _ = gae(r, v, np.array([10.0]), d, gamma=1.0, lam=1.0)
    assert np.allclose(adv[:, 0], [2, 1, 11])


def test_policy_save_load_roundtrip_and_shape_check(tmp_path):
    pi = Policy(N_OBS, N_ACT, seed=3)
    p = tmp_path / "pol.json"
    pi.save(str(p))
    q = Policy.load(str(p))
    x = np.random.default_rng(0).normal(size=(5, N_OBS))
    assert np.allclose(pi.probs(x), q.probs(x))
    with pytest.raises(ValueError):
        PPOController(Policy(N_OBS + 1, N_ACT))


def test_environment_reset_step_shapes_rewards_and_truncation():
    from rl.env import BuildingVecEnv
    env = BuildingVecEnv(days=1 / 24, warmup_h=0.5)
    o = env.reset(seed=11, scenario="normal", start=datetime(2026, 3, 2, 9))
    assert o.shape == (25, N_OBS) and np.isfinite(o).all()
    rng = np.random.default_rng(0)
    steps = 0
    while True:
        o, r, done, info = env.step(rng.integers(0, N_ACT, 25))
        steps += 1
        assert o.shape == (25, N_OBS) and r.shape == (25,) and np.isfinite(r).all() and (r <= 0).all()
        if done:
            break
    assert steps == 12                                 # 1 h of 5-min decisions, then truncated
    o2 = env.reset(seed=11, scenario="normal", start=datetime(2026, 3, 2, 9))
    o3 = env.reset(seed=11, scenario="normal", start=datetime(2026, 3, 2, 9))
    assert np.array_equal(o2, o3)                     # reset is reproducible
    with pytest.raises(ValueError):
        env.step([N_ACT] * 25)                        # outside the action space


def test_gymnasium_api_check():
    pytest.importorskip("gymnasium")
    from gymnasium.utils.env_checker import check_env
    from rl.env import RoomControlEnv
    check_env(RoomControlEnv(days=0.03, warmup_h=0.5), skip_render_check=True)


def test_actions_only_produce_allowed_commands():
    for a in range(N_ACT):
        for design in (22.0, 23.0, 24.0):
            light, hvac, sp = action_command(a, design)
            assert light in ("OFF", "DIM", "ON") and hvac in ("ECO", "LOW", "NORMAL")
            if hvac == "NORMAL":
                assert SETPOINT_RANGE[0] <= sp <= SETPOINT_RANGE[1]


def _controller():
    return PPOController(Policy(N_OBS, N_ACT, seed=5))


def _obs(t, hvac="ECO", sp=None):
    return Observation("f2_office_b2", "office", t, 26.0, 60.0, 200.0, 650.0, 0.012, 30.0, current_hvac=hvac,
                       current_setpoint=sp, outdoor_temperature=31.0, hvac_power_w=0.0)


def test_controller_holds_decisions_and_respects_dwell():
    c = _controller()
    t = datetime(2026, 3, 2, 10)
    d0 = c.decide(_obs(t))
    d1 = c.decide(_obs(t + timedelta(minutes=1)))
    assert (d0.light_action, d0.hvac_action, d0.setpoint_c) == (d1.light_action, d1.hvac_action, d1.setpoint_c)
    # the AC changed just now: a new decision within 10 min may not change it again
    c2 = _controller()
    t2 = datetime(2026, 3, 2, 11)
    c2.decide(_obs(t2, "NORMAL", 24.0))
    c2.builder._ac_since["f2_office_b2"] = t2.timestamp()
    d = c2.decide(_obs(t2 + timedelta(minutes=5), "NORMAL", 24.0))
    if (d.hvac_action, d.setpoint_c) != ("NORMAL", 24.0):
        pytest.fail("AC command changed inside the dwell time")
    assert AC_DWELL_S == 600.0


def test_policy_runs_without_training_environment(tmp_path):
    pi = Policy(N_OBS, N_ACT, seed=2)
    path = tmp_path / "policy.json"
    pi.save(str(path))
    c = PPOController.load(str(path))                  # numpy + twin types only, no simulator, no gymnasium
    d = c.decide(_obs(datetime(2026, 3, 2, 10)))
    assert d.hvac_action in ("ECO", "LOW", "NORMAL")


def test_ppo_in_the_runner_passes_safety_and_guard(tmp_path):
    pi = Policy(N_OBS, N_ACT, seed=4)
    path = tmp_path / "policy.json"
    pi.save(str(path))
    r = run_episode("ppo", "normal", seed=6, start=datetime(2026, 3, 2, 8), days=0.1, warmup_days=0.05,
                    ppo_policy=str(path), record_every=5)
    assert r.metrics["failsafe_F2"] == 0 and r.metrics["failsafe_F3"] == 0
    srv = [x for x in r.records if x["room_id"] == "f2_server"]
    assert all(x["hvac_cmd"] == "NORMAL" and x["setpoint_c"] <= 24.0 for x in srv)   # safety R2 holds for any policy


def test_policy_failure_falls_back_to_rules(tmp_path):
    class Exploding(PPOController):
        def decide(self, o):
            raise FloatingPointError("NaN in network")
    ctl = Exploding(Policy(N_OBS, N_ACT, seed=1))
    r = run_episode("ppo", "normal", seed=6, start=datetime(2026, 3, 2, 8), days=0.05, warmup_days=0.02,
                    controller_obj=ctl)
    assert r.metrics["failsafe_F2"] > 0
    assert "FloatingPointError" in r.meta["last_controller_error"]


def test_missing_policy_file_is_an_error_not_a_substitute(tmp_path):
    with pytest.raises((FileNotFoundError, OSError)):
        PPOController.load(str(tmp_path / "nope.json"))
