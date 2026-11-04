"""``energy_provenance=False`` skips the accounting ledger without changing the simulation."""

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv

DATASET = 'citylearn_challenge_2022_phase_all_plus_evs'
STEPS = 48


def _run(energy_provenance):
    env = CityLearnEnv(
        DATASET, central_agent=True, random_seed=0, energy_provenance=energy_provenance,
        simulation_start_time_step=0, simulation_end_time_step=STEPS,
    )
    observations, _ = env.reset(seed=0)
    rng = np.random.default_rng(0)
    trace = [np.asarray(observations, dtype='float64').ravel()]
    rewards = []

    while not env.terminated:
        observations, reward, *_ = env.step([rng.uniform(s.low, s.high).tolist() for s in env.action_space])
        trace.append(np.asarray(observations, dtype='float64').ravel())
        rewards.append(reward)

    return env, np.concatenate(trace), np.asarray(rewards, dtype='float64')


def test_disabling_provenance_keeps_trajectory_and_non_provenance_kpis():
    enabled, enabled_trace, enabled_rewards = _run(True)
    disabled, disabled_trace, disabled_rewards = _run(False)

    np.testing.assert_array_equal(enabled_trace, disabled_trace)
    np.testing.assert_array_equal(enabled_rewards, disabled_rewards)
    np.testing.assert_array_equal(enabled.net_electricity_consumption, disabled.net_electricity_consumption)
    assert disabled._provenance_service.steps == enabled._provenance_service.steps == STEPS

    enabled_kpis = enabled.evaluate_v2(include_business_as_usual=False)
    disabled_kpis = disabled.evaluate_v2(include_business_as_usual=False)
    provenance_rows = enabled_kpis['cost_function'].str.contains('energy_provenance')
    assert provenance_rows.any()
    assert not disabled_kpis['cost_function'].str.contains('energy_provenance').any()

    key = ['level', 'name', 'cost_function']
    expected = enabled_kpis[~provenance_rows].set_index(key)['value'].sort_index()
    actual = disabled_kpis.set_index(key)['value'].sort_index()
    np.testing.assert_array_equal(actual.index.to_numpy(), expected.index.to_numpy())
    np.testing.assert_allclose(actual.to_numpy(dtype=float), expected.to_numpy(dtype=float), equal_nan=True)


def test_disabled_provenance_reports_itself():
    env, *_ = _run(False)

    assert env._provenance_service.get_metadata()['enabled'] is False

    with pytest.raises(RuntimeError, match='energy_provenance=True'):
        env._provenance_service.summary()
