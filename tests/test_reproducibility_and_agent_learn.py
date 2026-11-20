import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController as Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.runtime import CityLearnRuntimeService


SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def test_agent_learn_handles_single_timestep_episode_without_calling_step(monkeypatch):
    # One-row consecutive episodes are only accepted with the 3.6.0 disjoint splits.
    env = CityLearnEnv(
        str(SCHEMA), central_agent=True, episode_time_steps=1, episode_split_boundary="disjoint",
        render_mode="none", random_seed=7,
    )
    agent = Agent(env)

    step_called = False

    def _unexpected_step(_actions):
        nonlocal step_called
        step_called = True
        raise AssertionError("env.step() should not be called when episode is terminal after reset.")

    monkeypatch.setattr(env, "step", _unexpected_step)

    try:
        agent.learn(episodes=1, deterministic=True, logging_level=40)
        assert not step_called
    finally:
        env.close()


def _run_rbc_episode(render_mode: str, output_root: Path, seed: int = 7):
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=128,
        render_mode=render_mode,
        render_directory=output_root,
        random_seed=seed,
    )
    agent = Agent(env)

    try:
        observations, _ = env.reset()
        rewards = []

        while not env.terminated:
            actions = agent.predict(observations, deterministic=True)
            observations, reward, terminated, truncated, _ = env.step(actions)
            rewards.append(np.array(reward, dtype="float64").reshape(-1))

            if terminated or truncated:
                break

        reward_trace = np.vstack(rewards) if rewards else np.zeros((0, len(env.action_space)), dtype="float64")
        ev_soc_trace = {
            ev.name: np.array(ev.battery.soc[: env.time_step + 1], dtype="float64")
            for ev in env.electric_vehicles
        }
        return reward_trace, ev_soc_trace
    finally:
        env.close()


def test_same_seed_is_reproducible_across_render_modes_without_global_numpy_seed(tmp_path):
    during_rewards, during_ev_soc = _run_rbc_episode("during", tmp_path / "during")
    end_rewards, end_ev_soc = _run_rbc_episode("end", tmp_path / "end")

    assert during_rewards.shape == end_rewards.shape
    assert np.allclose(during_rewards, end_rewards)
    assert set(during_ev_soc.keys()) == set(end_ev_soc.keys())

    for ev_name in during_ev_soc:
        assert during_ev_soc[ev_name].shape == end_ev_soc[ev_name].shape
        assert np.allclose(during_ev_soc[ev_name], end_ev_soc[ev_name])


def test_runtime_random_seed_overrides_schema_seed_for_loading_defaults():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    missing_initial_soc = [
        name
        for name, ev in (schema.get("electric_vehicles_def", {}) or {}).items()
        if "initial_soc" not in ((ev.get("battery", {}) or {}).get("attributes", {}) or {})
    ]
    assert missing_initial_soc, "Expected at least one EV without explicit initial_soc in schema."

    env_a = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=8, render_mode="none", random_seed=1)
    env_b = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=8, render_mode="none", random_seed=2)
    env_c = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=8, render_mode="none", random_seed=1)

    try:
        soc_a = {ev.name: float(ev.battery.initial_soc) for ev in env_a.electric_vehicles}
        soc_b = {ev.name: float(ev.battery.initial_soc) for ev in env_b.electric_vehicles}
        soc_c = {ev.name: float(ev.battery.initial_soc) for ev in env_c.electric_vehicles}

        # different runtime seeds should alter default-initialized EV SOCs
        assert any(not np.isclose(soc_a[name], soc_b[name]) for name in missing_initial_soc)

        # same runtime seed should reproduce the same default SOCs
        assert all(np.isclose(soc_a[name], soc_c[name]) for name in missing_initial_soc)
    finally:
        env_a.close()
        env_b.close()
        env_c.close()


def test_ev_unconnected_drift_std_scales_with_physical_timestep():
    hourly = CityLearnRuntimeService._ev_unconnected_drift_std(3600)
    minute = CityLearnRuntimeService._ev_unconnected_drift_std(60)
    quarter_hour = CityLearnRuntimeService._ev_unconnected_drift_std(900)

    assert np.isclose(hourly, 0.2)
    assert np.isclose(quarter_hour, 0.1)
    assert minute < quarter_hour < hourly


def test_unconnected_ev_soc_drift_uses_time_aware_variance():
    class _RandomState:
        def __init__(self):
            self.calls = []

        def normal(self, loc, scale):
            self.calls.append((float(loc), float(scale)))
            return float(loc + scale)

    class _Battery:
        def __init__(self, soc, target_index):
            self.soc = list(soc)
            self._target_index = target_index

        def force_set_soc(self, value):
            self.soc[self._target_index] = float(value)

    class _EV:
        def __init__(self, name, battery):
            self.name = name
            self.battery = battery

    class _EpisodeTracker:
        def __init__(self, episode_time_steps):
            self.episode_time_steps = episode_time_steps
            self.episode = 0

    class _Env:
        def __init__(self, seconds_per_time_step):
            self.seconds_per_time_step = seconds_per_time_step
            self.time_step = 1
            self.episode_tracker = _EpisodeTracker(episode_time_steps=8)
            # The battery has advanced to step 1, so its SOC there already holds the standby loss (none here).
            self.electric_vehicles = [_EV("EV1", _Battery([0.5, 0.5], target_index=1))]
            self.buildings = []
            self.random_seed = 7
            self._ev_drift_random_state = _RandomState()

    env_hourly = _Env(3600)
    env_minute = _Env(60)
    CityLearnRuntimeService(env_hourly).simulate_unconnected_ev_soc()
    CityLearnRuntimeService(env_minute).simulate_unconnected_ev_soc()

    hourly_scale = env_hourly._ev_drift_random_state.calls[0][1]
    minute_scale = env_minute._ev_drift_random_state.calls[0][1]

    assert hourly_scale > minute_scale
    assert env_hourly.electric_vehicles[0].battery.soc[1] > env_minute.electric_vehicles[0].battery.soc[1]
