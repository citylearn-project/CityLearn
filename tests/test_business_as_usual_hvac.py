"""Under ``baseline_version=3`` the native BAU delivers the dataset heating and cooling demand (#362).

Up to version 2 the BAU sends zero to the HVAC actions, so on datasets with temperature dynamics its
buildings are neither heated nor cooled. Version 3 is opt-in, and it changes nothing where no HVAC action
is active.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.building import DynamicsBuilding
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.baseline_version import DEFAULT_BASELINE_VERSION

DATASETS = Path(__file__).resolve().parents[1] / 'data' / 'datasets'
MINUTE_EV_SCHEMA = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo' / 'schema.json'
STEPS = 30
CASES = {
    # case: (dataset, HVAC action, simulation start, heating?)
    'heating_device': ('quebec_neighborhood_without_demand_response_set_points', 'heating_device', 0, True),
    'cooling_device': ('citylearn_challenge_2023_phase_1', 'cooling_device', 200, False),
    'cooling_or_heating_device_heating': ('vt_chittenden_county_neighborhood', 'cooling_or_heating_device', 0, True),
    # Summer in Texas: cooling, so the shared action must be negative.
    'cooling_or_heating_device_cooling': ('tx_travis_county_neighborhood', 'cooling_or_heating_device', 4344, False),
}


def _schema(dataset):
    """First building only, to keep the runs small."""

    source = DATASETS/dataset
    schema = json.loads((source/'schema.json').read_text(encoding='utf-8'))
    first = next(name for name, building in schema['buildings'].items() if building.get('include', True))
    schema['buildings'] = {first: {**schema['buildings'][first], 'include': True}}
    schema['root_directory'] = str(source)
    return schema


def _run_bau(dataset, start, baseline_version=None, seconds_per_time_step=3600, **kwargs):
    env = CityLearnEnv(
        _schema(dataset), central_agent=True, random_seed=0, render_mode='none', solar_generation=False,
        simulation_start_time_step=start, episode_time_steps=STEPS, seconds_per_time_step=seconds_per_time_step,
        time_step_ratio_mode='compress', baseline_version=baseline_version,
    )
    agent = BusinessAsUsualAgent(env, **kwargs)
    observations, _ = env.reset()
    actions = []

    while not env.terminated:
        action = agent.predict(observations, deterministic=True)
        actions.append(action[0])
        observations, *_ = env.step(action)

    return env, agent, np.asarray(actions)


def _delivered_and_demand(building, heating):
    simulation = building.energy_simulation
    n = building.time_step + 1
    delivered = building.energy_from_heating_device if heating else building.energy_from_cooling_device
    demand = simulation.heating_demand_without_control if heating else simulation.cooling_demand_without_control
    return np.asarray(delivered[:n], dtype=float), np.asarray(demand[:n], dtype=float)


def test_default_baseline_version_is_still_2_and_the_bau_hvac_is_off():
    env = CityLearnEnv(_schema(CASES['heating_device'][0]), central_agent=True, episode_time_steps=4)
    agent = BusinessAsUsualAgent(env)

    assert DEFAULT_BASELINE_VERSION == 2 and env.baseline_version == 2
    assert agent.hvac == 'off'
    assert agent.DEFINITION_VERSION == 'immediate-full-charge-v4'
    assert 'hvac' not in agent.comparison_identity()['parameters']


@pytest.mark.parametrize('case', list(CASES))
@pytest.mark.parametrize('seconds_per_time_step', [3600, 900])
def test_version_3_bau_delivers_the_dataset_demand(case, seconds_per_time_step):
    dataset, action_name, start, heating = CASES[case]
    env, agent, actions = _run_bau(dataset, start, baseline_version=3, seconds_per_time_step=seconds_per_time_step)
    building = env.buildings[0]
    assert isinstance(building, DynamicsBuilding)
    assert agent.hvac == 'dataset_demand'
    assert agent.DEFINITION_VERSION == 'immediate-full-charge-v4+hvac-dataset-demand-v1'
    assert agent.comparison_identity()['parameters']['hvac'] == 'dataset_demand'

    delivered, demand = _delivered_and_demand(building, heating)
    controlled = np.asarray(building.energy_simulation.indoor_dry_bulb_temperature[:len(demand)]) != np.asarray(
        building.energy_simulation.indoor_dry_bulb_temperature_without_control[:len(demand)])
    # After the LSTM warm-up the dynamics run, so the action sets the demand.
    assert controlled.any()
    assert demand.sum() > 0.0
    np.testing.assert_allclose(delivered, demand, rtol=1e-5, atol=1e-6)

    position = env.action_names[0].index(action_name)
    hvac_actions = actions[:, position]
    assert np.all(np.abs(hvac_actions) <= 1.0)
    # Only cooling_or_heating_device has a sign: negative is cooling.
    cooling_sign = action_name == 'cooling_or_heating_device' and not heating
    assert np.all(hvac_actions <= 0.0) if cooling_sign else np.all(hvac_actions >= 0.0)


@pytest.mark.parametrize('case', list(CASES))
def test_version_2_bau_still_sends_zero_to_the_hvac(case):
    dataset, action_name, start, heating = CASES[case]
    env, agent, actions = _run_bau(dataset, start, baseline_version=2)
    building = env.buildings[0]
    assert agent.hvac == 'off'
    assert np.all(actions[:, env.action_names[0].index(action_name)] == 0.0)

    # Once the dynamics run, the zero action leaves the building without heating or cooling (#362).
    delivered, demand = _delivered_and_demand(building, heating)
    lookback = building.dynamics.lookback
    assert demand[lookback + 1:].sum() > 0.0
    assert delivered[lookback + 1:].sum() == 0.0


def test_hvac_argument_overrides_the_version():
    dataset, _, start, heating = CASES['heating_device']
    explicit, _, _ = _run_bau(dataset, start, baseline_version=2, hvac='dataset_demand')
    by_version, _, _ = _run_bau(dataset, start, baseline_version=3)
    off, agent, _ = _run_bau(dataset, start, baseline_version=3, hvac='off')
    assert agent.DEFINITION_VERSION == 'immediate-full-charge-v4'
    np.testing.assert_array_equal(explicit.buildings[0].net_electricity_consumption,
                                  by_version.buildings[0].net_electricity_consumption)
    zero, _, _ = _run_bau(dataset, start, baseline_version=2)
    np.testing.assert_array_equal(off.buildings[0].net_electricity_consumption,
                                  zero.buildings[0].net_electricity_consumption)

    with pytest.raises(ValueError, match='hvac must be one of'):
        BusinessAsUsualAgent(explicit, hvac='thermostat')


def _evaluate(baseline_version):
    env = CityLearnEnv(str(MINUTE_EV_SCHEMA), central_agent=True, random_seed=0, render_mode='none',
                       baseline_version=baseline_version)
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)

    while not env.terminated:
        observations, *_ = env.step(agent.predict(observations, deterministic=True))

    return env, env.evaluate_v2(), env.evaluate()


def test_version_3_equals_version_2_without_hvac_actions():
    v2_env, v2_kpis, v2_legacy = _evaluate(2)
    v3_env, v3_kpis, v3_legacy = _evaluate(3)
    assert not any(a in names for names in v3_env.action_names
                   for a in ('heating_device', 'cooling_device', 'cooling_or_heating_device'))

    for left, right in zip(v2_env.buildings, v3_env.buildings):
        np.testing.assert_array_equal(left.net_electricity_consumption, right.net_electricity_consumption)

    pd.testing.assert_frame_equal(v2_kpis, v3_kpis)
    pd.testing.assert_frame_equal(v2_legacy, v3_legacy)


def test_bau_sidecar_follows_a_version_change_after_evaluation():
    dataset, _, start, _ = CASES['heating_device']
    env = CityLearnEnv(_schema(dataset), central_agent=True, random_seed=0, render_mode='none',
                       solar_generation=False, simulation_start_time_step=start, episode_time_steps=STEPS)
    env.reset()

    while not env.terminated:
        env.step([np.zeros(len(env.action_names[0])).tolist()])

    def bau_cost(kpis):
        rows = kpis[kpis['cost_function'].astype(str) == 'district_cost_total_business_as_usual_eur']
        return rows['value'].astype(float).to_numpy()

    v2 = bau_cost(env.evaluate_v2())
    assert env._business_as_usual_baseline_cache[next(iter(env._business_as_usual_baseline_cache))].hvac == 'off'
    env.baseline_version = 3
    v3 = bau_cost(env.evaluate_v2())
    cached = next(iter(env._business_as_usual_baseline_cache.values()))
    assert cached.hvac == 'dataset_demand'
    assert cached.env._native_reference_metadata['definition_version'].endswith('+hvac-dataset-demand-v1')
    assert v2.size == 1 and v3[0] > v2[0]
