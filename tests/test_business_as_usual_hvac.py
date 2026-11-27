"""The native BAU delivers the dataset heating and cooling demand (#362).

In CityLearn 3.6.0 the BAU sent zero to the HVAC actions, so on datasets with temperature dynamics its buildings were
neither heated nor cooled; ``hvac='off'`` still does that, and baseline version 1, which made it the default, was
removed in CityLearn 3.8.1 (#466). Where no HVAC action is active the HVAC rule changes nothing.
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


def _run_bau(dataset, start, seconds_per_time_step=3600, **kwargs):
    env = CityLearnEnv(
        _schema(dataset), central_agent=True, random_seed=0, render_mode='none', solar_generation=False,
        simulation_start_time_step=start, episode_time_steps=STEPS, seconds_per_time_step=seconds_per_time_step,
        time_step_ratio_mode='compress',
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


def test_default_baseline_version_is_2_and_the_bau_runs_the_hvac():
    env = CityLearnEnv(_schema(CASES['heating_device'][0]), central_agent=True, episode_time_steps=4)
    agent = BusinessAsUsualAgent(env)

    assert DEFAULT_BASELINE_VERSION == 2 and env.baseline_version == 2
    assert agent.hvac == 'dataset_demand'
    assert agent.DEFINITION_VERSION == 'immediate-full-charge-v4+hvac-dataset-demand-v1'
    assert agent.comparison_identity()['parameters']['hvac'] == 'dataset_demand'


@pytest.mark.parametrize('version', [1, 3])
def test_only_version_2_exists(version):
    with pytest.raises(ValueError, match=r'baseline_version must be 2, got .*Version 1 was removed in CityLearn 3\.8\.1'):
        CityLearnEnv(_schema(CASES['heating_device'][0]), central_agent=True, episode_time_steps=4,
                     baseline_version=version)


@pytest.mark.parametrize('case', list(CASES))
@pytest.mark.parametrize('seconds_per_time_step', [3600, 900])
def test_version_2_bau_delivers_the_dataset_demand(case, seconds_per_time_step):
    dataset, action_name, start, heating = CASES[case]
    env, agent, actions = _run_bau(dataset, start, seconds_per_time_step=seconds_per_time_step)
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
def test_hvac_off_bau_sends_zero_to_the_hvac(case):
    dataset, action_name, start, heating = CASES[case]
    env, agent, actions = _run_bau(dataset, start, hvac='off')
    building = env.buildings[0]
    assert agent.hvac == 'off'
    assert agent.DEFINITION_VERSION == 'immediate-full-charge-v4'
    assert 'hvac' not in agent.comparison_identity()['parameters']
    assert np.all(actions[:, env.action_names[0].index(action_name)] == 0.0)

    # Once the dynamics run, the zero action leaves the building without heating or cooling (#362).
    delivered, demand = _delivered_and_demand(building, heating)
    lookback = building.dynamics.lookback
    assert demand[lookback + 1:].sum() > 0.0
    assert delivered[lookback + 1:].sum() == 0.0


def test_hvac_argument_overrides_the_default():
    dataset, _, start, heating = CASES['heating_device']
    explicit, _, _ = _run_bau(dataset, start, hvac='dataset_demand')
    by_default, _, _ = _run_bau(dataset, start)
    off, agent, _ = _run_bau(dataset, start, hvac='off')
    assert agent.DEFINITION_VERSION == 'immediate-full-charge-v4'
    np.testing.assert_array_equal(explicit.buildings[0].net_electricity_consumption,
                                  by_default.buildings[0].net_electricity_consumption)
    assert not np.array_equal(off.buildings[0].net_electricity_consumption,
                              by_default.buildings[0].net_electricity_consumption)

    with pytest.raises(ValueError, match='hvac must be one of'):
        BusinessAsUsualAgent(explicit, hvac='thermostat')


def _evaluate(hvac):
    env = CityLearnEnv(str(MINUTE_EV_SCHEMA), central_agent=True, random_seed=0, render_mode='none')
    agent = BusinessAsUsualAgent(env, hvac=hvac)
    observations, _ = env.reset(seed=0)

    while not env.terminated:
        observations, *_ = env.step(agent.predict(observations, deterministic=True))

    return env, env.evaluate_v2(), env.evaluate()


def test_default_bau_keeps_its_earlier_definition_without_hvac_actions():
    env = CityLearnEnv(str(MINUTE_EV_SCHEMA), central_agent=True, episode_time_steps=4)
    agent = BusinessAsUsualAgent(env)

    assert env.baseline_version == 2
    assert agent.hvac == 'off'
    assert agent.DEFINITION_VERSION == 'immediate-full-charge-v4'
    assert 'hvac' not in agent.comparison_identity()['parameters']


def test_the_hvac_rule_changes_nothing_without_hvac_actions():
    off_env, off_kpis, off_legacy = _evaluate('off')
    on_env, on_kpis, on_legacy = _evaluate('dataset_demand')
    assert not any(a in names for names in on_env.action_names
                   for a in ('heating_device', 'cooling_device', 'cooling_or_heating_device'))

    for left, right in zip(off_env.buildings, on_env.buildings):
        np.testing.assert_array_equal(left.net_electricity_consumption, right.net_electricity_consumption)

    pd.testing.assert_frame_equal(off_kpis, on_kpis)
    pd.testing.assert_frame_equal(off_legacy, on_legacy)
