"""``energy_provenance=False`` skips the accounting ledger without changing the simulation."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
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


MINUTE_EV_SCHEMA = Path(__file__).resolve().parent/'data'/'minute_ev_demo'/'schema.json'
EXPORT_STEPS = 6


def _minute_ev_env(tmp_path, *, schema_value=None, constructor_value=None):
    schema = json.loads(MINUTE_EV_SCHEMA.read_text(encoding='utf-8'))
    schema['root_directory'] = str(MINUTE_EV_SCHEMA.parent)
    schema.update(physics_invariant_checks=True, simulation_start_time_step=0,
                  simulation_end_time_step=EXPORT_STEPS - 1, episode_time_steps=EXPORT_STEPS)
    if schema_value is not None:
        schema['energy_provenance'] = schema_value
    kwargs = {} if constructor_value is None else dict(energy_provenance=constructor_value)
    env = CityLearnEnv(schema, central_agent=True, random_seed=0, offline=True,
                       render_directory=tmp_path/'exports', export_kpis_on_episode_end=False, **kwargs)
    env.reset(seed=0)
    while not env.terminated:
        env.step([np.zeros(space.shape, dtype='float32').tolist() for space in env.action_space])
    return env


# (schema value, constructor value) -> effective setting
CONFIGURATIONS = {
    'default': (None, None, True),
    'schema_off': (False, None, False),
    'constructor_off': (None, False, False),
    'constructor_overrides_schema_on': (False, True, True),
}


@pytest.mark.parametrize('configuration', list(CONFIGURATIONS))
@pytest.mark.parametrize('include_business_as_usual', [False, True])
def test_kpi_export_handles_provenance_setting(tmp_path, configuration, include_business_as_usual):
    schema_value, constructor_value, effective = CONFIGURATIONS[configuration]
    env = _minute_ev_env(tmp_path, schema_value=schema_value, constructor_value=constructor_value)
    try:
        assert env.energy_provenance is effective
        env.export_final_kpis(filepath='kpis.csv', include_business_as_usual=include_business_as_usual,
                              export_business_as_usual_timeseries=False)
        output = Path(env.new_folder_path)
        manifest = json.loads((output/'kpis.manifest.json').read_text())
        kpis = pd.read_csv(output/'kpis.csv')

        assert manifest['energy_provenance'] is effective
        assert manifest['completed_intervals'] == EXPORT_STEPS - 1  # six states, five intervals
        assert (manifest['provenance_summary'] is not None) is effective
        assert (manifest['source_destinations'] is not None) is effective
        assert bool(kpis['KPI'].str.contains('energy_provenance').any()) is effective
    finally:
        env.close()


@pytest.mark.parametrize('configuration', list(CONFIGURATIONS))
def test_business_as_usual_sidecar_uses_effective_provenance_setting(tmp_path, configuration):
    schema_value, constructor_value, effective = CONFIGURATIONS[configuration]
    env = _minute_ev_env(tmp_path, schema_value=schema_value, constructor_value=constructor_value)
    try:
        sidecar = env.run_business_as_usual_baseline().env
        assert sidecar.energy_provenance is effective
        assert sidecar._provenance_service.enabled is effective
    finally:
        env.close()
