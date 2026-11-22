"""A copied environment continues exactly like the original, KPIs included (CityLearn #307).

Look-ahead controllers, parallel rollouts and checkpoints copy a stepped environment with
``copy.deepcopy`` or ``pickle``. The copy must keep simulating the same trajectory, and its
``evaluate_v2()`` table, energy-provenance rows included, must equal an uncopied run's.
"""

import copy
import pickle

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv


def _actions(env, t, non_negative=False):
    """A deterministic schedule that charges and discharges storage."""

    value = np.float32(0.4*np.sin(t/3.0))
    return [
        np.clip(np.full(space.shape, value, dtype='float32'), np.maximum(space.low, 0.0) if non_negative else space.low,
                space.high)
        for space in env.action_space
    ]


def _run(env, t, non_negative):
    while not env.terminated:
        env.step(_actions(env, t, non_negative))
        t += 1

    return env.evaluate_v2(include_business_as_usual=False)


def _copy(env, mode):
    return copy.deepcopy(env) if mode == 'deepcopy' else pickle.loads(pickle.dumps(env))


def _assert_copy_matches(dataset, end, copy_at, mode, non_negative=False):
    def make():
        env = CityLearnEnv(dataset, simulation_start_time_step=0, simulation_end_time_step=end)
        env.reset()
        return env

    expected = _run(make(), 0, non_negative)
    original = make()

    for t in range(copy_at):
        original.step(_actions(original, t, non_negative))

    copied = _copy(original, mode)
    actual = _run(copied, copy_at, non_negative)

    merged = expected.merge(actual, on=['cost_function', 'name'], suffixes=('_expected', '_actual'), how='outer')
    assert len(merged) == len(expected) == len(actual)
    differ = ~np.isclose(
        merged['value_expected'].astype(float), merged['value_actual'].astype(float), rtol=1e-9, atol=1e-9,
        equal_nan=True,
    )
    assert not differ.any(), merged.loc[differ, ['cost_function', 'name', 'value_expected', 'value_actual']].head(10)
    assert merged['cost_function'].str.contains('energy_provenance').any()


@pytest.mark.parametrize('mode', ['deepcopy', 'pickle'])
@pytest.mark.parametrize('copy_at', [0, 10])
def test_copied_env_kpis_match_uncopied_run(mode, copy_at):
    _assert_copy_matches('citylearn_challenge_2022_phase_all_plus_evs', 23, copy_at, mode)


@pytest.mark.parametrize('mode', ['deepcopy', 'pickle'])
def test_copied_lstm_env_kpis_match_uncopied_run(mode):
    pytest.importorskip('torch')
    # The deepcopy failed once the LSTM had run a prediction, after its lookback warm-up.
    _assert_copy_matches('citylearn_challenge_2023_phase_1', 29, 16, mode, non_negative=True)
