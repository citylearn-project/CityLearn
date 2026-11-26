from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


SCHEMA = Path(__file__).resolve().parents[2] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def _reward_array(reward) -> np.ndarray:
    array = np.asarray(reward, dtype="float64")
    return array.reshape(1) if array.ndim == 0 else array.reshape(-1)


def _sum_rewards(rewards) -> list[float]:
    total = None
    for reward in rewards:
        array = _reward_array(reward)
        total = array.copy() if total is None else total + array

    return [float(value) for value in total.tolist()]


def _assert_nested_allclose(left, right):
    if isinstance(left, Mapping):
        assert set(left) == set(right)
        for key in left:
            _assert_nested_allclose(left[key], right[key])
        return

    if isinstance(left, (list, tuple)):
        assert len(left) == len(right)
        for left_item, right_item in zip(left, right):
            _assert_nested_allclose(left_item, right_item)
        return

    try:
        np.testing.assert_allclose(
            np.asarray(left),
            np.asarray(right),
            rtol=1e-6,
            atol=1e-6,
            equal_nan=True,
        )
    except TypeError:
        assert left == right


def _flat_action(env: CityLearnEnv):
    action = np.zeros(env.action_space[0].shape[0], dtype="float32")

    for index, name in enumerate(env.action_names[0]):
        if name == "electrical_storage":
            action[index] = 0.25
        elif name.startswith("electric_vehicle_storage_"):
            action[index] = 0.35

    return [action]


def _zero_entity_action(env: CityLearnEnv):
    tables = env.action_space["tables"]
    return {
        "tables": {
            name: np.zeros(space.shape, dtype="float32")
            for name, space in tables.items()
            if name in {"building", "charger", "deferrable_appliance"}
        }
    }


def _run_repeated_steps(env: CityLearnEnv, action, repeat_steps: int):
    observations = None
    rewards = []
    terminated = truncated = False
    info = {}

    for _ in range(repeat_steps):
        observations, reward, terminated, truncated, info = env.step(action)
        rewards.append(reward)
        if terminated or truncated:
            break

    return observations, _sum_rewards(rewards), terminated, truncated, info, len(rewards)


def _sorted_kpis(env: CityLearnEnv) -> pd.DataFrame:
    return (
        env.evaluate_v2(include_business_as_usual=False)
        .sort_values(["level", "name", "cost_function"])
        .reset_index(drop=True)
    )


def test_step_many_matches_repeated_flat_steps():
    env_many = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=10, render_mode="none", random_seed=0)
    env_loop = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=10, render_mode="none", random_seed=0)

    try:
        env_many.reset()
        env_loop.reset()
        action = _flat_action(env_many)

        many_obs, many_reward, many_terminated, many_truncated, many_info = env_many.step_many(
            action,
            repeat_steps=5,
        )
        loop_obs, loop_reward, loop_terminated, loop_truncated, _loop_info, loop_steps = _run_repeated_steps(
            env_loop,
            action,
            repeat_steps=5,
        )

        _assert_nested_allclose(many_obs, loop_obs)
        np.testing.assert_allclose(many_reward, loop_reward, rtol=1e-6, atol=1e-6)
        assert many_terminated == loop_terminated
        assert many_truncated == loop_truncated
        assert many_info["executed_steps"] == loop_steps == 5
        assert many_info["seconds_per_time_step"] == env_many.seconds_per_time_step
        assert many_info["macro_seconds"] == pytest.approx(loop_steps * env_many.seconds_per_time_step)
        assert env_many.time_step == env_loop.time_step
        assert len(env_many.rewards) == len(env_loop.rewards)
        pd.testing.assert_frame_equal(_sorted_kpis(env_many), _sorted_kpis(env_loop), check_exact=False)
    finally:
        env_many.close()
        env_loop.close()


def test_step_many_matches_repeated_entity_steps():
    env_many = CityLearnEnv(
        str(SCHEMA),
        interface="entity",
        central_agent=True,
        episode_time_steps=8,
        render_mode="none",
        random_seed=0,
    )
    env_loop = CityLearnEnv(
        str(SCHEMA),
        interface="entity",
        central_agent=True,
        episode_time_steps=8,
        render_mode="none",
        random_seed=0,
    )

    try:
        env_many.reset()
        env_loop.reset()
        action = _zero_entity_action(env_many)

        many_obs, many_reward, many_terminated, many_truncated, many_info = env_many.step_many(
            action,
            repeat_steps=4,
        )
        loop_obs, loop_reward, loop_terminated, loop_truncated, _loop_info, loop_steps = _run_repeated_steps(
            env_loop,
            action,
            repeat_steps=4,
        )

        _assert_nested_allclose(many_obs, loop_obs)
        np.testing.assert_allclose(many_reward, loop_reward, rtol=1e-6, atol=1e-6)
        assert many_terminated == loop_terminated
        assert many_truncated == loop_truncated
        assert many_info["executed_steps"] == loop_steps == 4
        assert env_many.time_step == env_loop.time_step
    finally:
        env_many.close()
        env_loop.close()


def test_step_many_stops_at_episode_end_and_reports_executed_steps():
    env_many = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, render_mode="none", random_seed=0)
    env_loop = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, render_mode="none", random_seed=0)

    try:
        env_many.reset()
        env_loop.reset()
        action = _flat_action(env_many)

        many_obs, many_reward, many_terminated, many_truncated, many_info = env_many.step_many(
            action,
            repeat_steps=20,
        )
        loop_obs, loop_reward, loop_terminated, loop_truncated, _loop_info, loop_steps = _run_repeated_steps(
            env_loop,
            action,
            repeat_steps=20,
        )

        _assert_nested_allclose(many_obs, loop_obs)
        np.testing.assert_allclose(many_reward, loop_reward, rtol=1e-6, atol=1e-6)
        assert many_terminated == loop_terminated is False
        assert many_truncated == loop_truncated is True
        assert many_info["executed_steps"] == loop_steps < 20
        assert many_info["macro_seconds"] == pytest.approx(loop_steps * env_many.seconds_per_time_step)
        assert env_many.time_step == env_loop.time_step
    finally:
        env_many.close()
        env_loop.close()


def test_step_many_can_return_substep_debug_payloads():
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=6,
        render_mode="none",
        debug_timing=True,
        random_seed=0,
    )

    try:
        env.reset()
        observations, reward, terminated, truncated, info = env.step_many(
            _flat_action(env),
            repeat_steps=3,
            return_substeps=True,
        )

        assert observations is not None
        assert not terminated
        assert not truncated
        assert info["executed_steps"] == 3
        assert len(info["substep_rewards"]) == 3
        assert len(info["substep_infos"]) == 3
        assert len(info["substep_actions_applied"]) == 3
        assert info["step_many_total_time"] >= 0.0
        assert all("step_total_time" in substep_info for substep_info in info["substep_infos"])
        np.testing.assert_allclose(reward, _sum_rewards(info["substep_rewards"]), rtol=1e-6, atol=1e-6)
    finally:
        env.close()


def test_step_many_rejects_invalid_repeat_steps():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, render_mode="none", random_seed=0)

    try:
        env.reset()
        with pytest.raises(ValueError, match="repeat_steps"):
            env.step_many(_flat_action(env), repeat_steps=0)
    finally:
        env.close()
