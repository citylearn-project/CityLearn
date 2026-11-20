"""Per-step histories live in preallocated buffers but the public attributes stay lists (#290)."""

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.histories import RowHistory, ScalarHistory

SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def _run(env, steps, rng=None):
    rewards = []

    for _ in range(steps):
        if rng is None:
            actions = [np.zeros(s.shape, dtype="float32") for s in env.action_space]
        else:
            actions = [rng.uniform(s.low, s.high).astype("float32") for s in env.action_space]

        _, reward, *_ = env.step(actions)
        rewards.append(reward)

    return rewards


# ---------------------------------------------------------------- unit tests of the containers


def test_scalar_history_matches_list_semantics():
    history, reference = ScalarHistory(2), []

    # append, overwrite the last entry, grow beyond the preallocated capacity
    for index, value in [(0, 1.5), (0, 2.5), (1, 3.5), (2, -0.0), (3, np.nan), (4, 7.0)]:
        value = np.float64(value)
        history.put(index, value)

        if len(reference) == index:
            reference.append(value)
        else:
            reference[index] = value

    assert len(history) == len(reference) == 5
    assert [v.tobytes() for v in history.to_list()] == [np.float64(v).tobytes() for v in (2.5, 3.5, -0.0, np.nan, 7.0)]
    assert all(type(v) is np.float64 for v in history.to_list())
    assert np.signbit(history[2]) and history[-1] == 7.0
    assert history.to_list() is history.to_list()
    assert [v.tobytes() for v in history] == [v.tobytes() for v in reference]


def test_scalar_history_irregular_writes_fall_back_to_list():
    history = ScalarHistory(4)
    history.put(0, np.float64(1.0))
    history.put(3, np.float64(4.0))  # gap: list rule pads with 0.0
    assert history.to_list() == [1.0, 0.0, 0.0, 4.0]
    history.put(1, 5.0)  # a Python float is not stored in the buffer; list rule truncates after index 1
    assert history.to_list() == [1.0, 0.0, 5.0]
    assert len(history) == 3


def test_row_history_returns_exactly_what_was_appended():
    history = RowHistory(1)
    rows = [[], [1.0, 2.0], [np.float64(3.0)] * 3, [float("inf")], [], [-0.0, 1e-320, 5e300, 0.1, 0.2]]

    for row in rows:
        history.append(row)

    out = history.to_list()
    assert out == rows and type(out) is list
    assert [[type(v) for v in row] for row in out] == [[type(v) for v in row] for row in rows]
    assert np.signbit(out[-1][0])
    assert len(history) == len(rows) and list(history.rows(2)) == rows[2:]
    assert history[1] == [1.0, 2.0] and history[-1] == rows[-1]


def test_row_history_unsupported_rows_fall_back_to_list():
    history = RowHistory(4)
    odd = np.array([1.0, 2.0])
    history.append([1.0])
    history.append(odd)  # not a list: stored as given
    history.append([1, 2.5])  # mixed element types
    history.append([2.0])
    out = history.to_list()
    assert out[0] == [1.0] and out[1] is odd and out[2] == [1, 2.5] and out[3] == [2.0]
    assert type(out[2][0]) is int


def test_history_list_is_a_copy():
    scalar, rows = ScalarHistory(4), RowHistory(4)
    scalar.put(0, np.float64(1.0))
    rows.append([1.0, 2.0])
    scalar.to_list().append(99.0)
    scalar.to_list()[0] = 7.0
    rows.to_list()[0].append(9.0)
    rows.to_list()[0][0] = 8.0
    scalar.put(1, np.float64(2.0))
    rows.append([3.0])
    assert scalar.to_list() == [1.0, 2.0]
    assert rows.to_list() == [[1.0, 2.0], [3.0]]


# ---------------------------------------------------------------- environment behaviour


@pytest.fixture(scope="module")
def stepped_env():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=8, random_seed=0)
    env.reset(seed=0)
    step_rewards = _run(env, 5, np.random.default_rng(0))
    yield env, step_rewards
    env.close()


def test_public_histories_are_lists_with_executed_length(stepped_env):
    env, _ = stepped_env
    assert type(env.rewards) is list and len(env.rewards) == 6
    assert env.rewards[0] == []

    for series in (env.net_electricity_consumption, env.net_electricity_consumption_cost,
                   env.net_electricity_consumption_emission):
        assert type(series) is list and len(series) == 5
        assert all(type(v) is np.float64 for v in series)

    assert all(type(v) is float for v in env.rewards[1])
    assert len(env.rewards[1]) == len(env.buildings)


def test_histories_support_list_operations(stepped_env):
    env, _ = stepped_env
    assert env.rewards[1:3] == [env.rewards[1], env.rewards[2]]
    assert env.net_electricity_consumption[-2:] == env.net_electricity_consumption[3:]
    assert env.net_electricity_consumption == list(env.net_electricity_consumption)
    assert json.loads(json.dumps(env.rewards)) == env.rewards
    assert json.loads(json.dumps(env.net_electricity_consumption)) == [float(v) for v in env.net_electricity_consumption]
    assert env.net_electricity_consumption.copy() == env.net_electricity_consumption


def test_histories_equal_the_values_the_simulation_returned(stepped_env):
    env, step_rewards = stepped_env
    # exact equality with what step() returned and with the sum of the building series
    assert env.rewards[1:] == [list(r) for r in step_rewards]

    for t in range(5):
        for name in ("net_electricity_consumption", "net_electricity_consumption_cost",
                     "net_electricity_consumption_emission"):
            expected = sum((getattr(b, name)[t] for b in env.buildings), np.float64(0))
            assert getattr(env, name)[t].tobytes() == np.float64(expected).tobytes()


def test_mutating_a_returned_list_does_not_change_the_environment():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=6, random_seed=0)

    try:
        env.reset(seed=0)
        _run(env, 2)
        expected = [list(r) for r in env.rewards]
        net = list(env.net_electricity_consumption)
        env.rewards.append([1.0])
        env.rewards[1][0] = 1e9
        env.net_electricity_consumption.clear()
        _run(env, 1)
        assert len(env.rewards) == 4 and env.rewards[1:3] == expected[1:3]
        assert env.net_electricity_consumption[:2] == net[:2]
        assert len(env.net_electricity_consumption) == 3
    finally:
        env.close()


def test_reset_clears_histories_in_every_episode():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=5, random_seed=0)

    try:
        for episode in range(3):
            env.reset(seed=1)
            assert env.rewards == [[]] and len(env.net_electricity_consumption) == 1
            step_rewards = _run(env, 4, np.random.default_rng(1))
            assert env.terminated and len(env.rewards) == 5
            assert env.rewards[1:] == [list(r) for r in step_rewards]

            for t in range(4):
                expected = sum((b.net_electricity_consumption[t] for b in env.buildings), np.float64(0))
                assert env.net_electricity_consumption[t].tobytes() == np.float64(expected).tobytes()

            assert len(env.episode_rewards) == episode + 1
    finally:
        env.close()


def test_history_grows_beyond_the_preallocated_episode_length():
    env = CityLearnEnv(str(SCHEMA), episode_time_steps=6, random_seed=0)

    try:
        env.reset(seed=0)
        _run(env, 4)
        reference = ([list(r) for r in env.rewards], list(env.net_electricity_consumption))
        # smaller preallocation than the steps taken forces doubling, with the same contents
        env._rewards_history = RowHistory(1)
        env._net_electricity_consumption_history = ScalarHistory(1)

        for row in reference[0]:
            env._rewards_history.append(row)

        for index, value in enumerate(reference[1]):
            env._net_electricity_consumption_history.put(index, value)

        assert env.rewards == reference[0] and env.net_electricity_consumption == reference[1]
    finally:
        env.close()


def test_cli_style_json_export_is_unchanged(stepped_env):
    env, _ = stepped_env
    text = json.dumps({'episode_rewards': env.rewards})
    assert json.loads(text)['episode_rewards'][0] == []
    assert text == json.dumps({'episode_rewards': [[]] + [list(r) for r in env.rewards[1:]]})
