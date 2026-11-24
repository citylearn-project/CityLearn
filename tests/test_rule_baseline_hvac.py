"""The rule-based baselines run the HVAC at the dataset's heating and cooling demand, as the v3 BAU does.

Up to now ``RBCBasicPolicy``, ``RBCSmartPolicy`` and ``RBCCommunityPolicy`` sent zero to the HVAC actions, so
on datasets with temperature dynamics their buildings were neither heated nor cooled. They now deliver the
dataset demand by default; ``hvac='off'`` keeps the old behaviour. Without HVAC actions nothing changes.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import (
    BusinessAsUsualAgent, RBCBasicPolicy, RBCCommunityPolicy, RBCSmartPolicy, ZeroActionAgent,
)
from citylearn.citylearn import CityLearnEnv

DATASETS = Path(__file__).resolve().parents[1] / 'data' / 'datasets'
MINUTE_EV_SCHEMA = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo' / 'schema.json'
RBCS = [RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy]
STEPS = 30
CASES = {
    # case: (dataset, HVAC action, simulation start, heating?)
    'heating_device': ('quebec_neighborhood_without_demand_response_set_points', 'heating_device', 0, True),
    'cooling_device': ('citylearn_challenge_2023_phase_1', 'cooling_device', 200, False),
    'cooling_or_heating_device_heating': ('vt_chittenden_county_neighborhood', 'cooling_or_heating_device', 0, True),
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


def _run(controller, dataset, start, **kwargs):
    env = CityLearnEnv(
        _schema(dataset), central_agent=True, random_seed=0, render_mode='none', solar_generation=False,
        simulation_start_time_step=start, episode_time_steps=STEPS,
    )
    agent = controller(env, **kwargs)
    observations, _ = env.reset(seed=0)
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


@pytest.mark.parametrize('controller', RBCS)
@pytest.mark.parametrize('case', list(CASES))
def test_rbc_delivers_the_dataset_demand_by_default(controller, case):
    dataset, action_name, start, heating = CASES[case]
    env, agent, actions = _run(controller, dataset, start)
    assert agent.hvac == 'dataset_demand'

    delivered, demand = _delivered_and_demand(env.buildings[0], heating)
    assert demand.sum() > 0.0
    np.testing.assert_allclose(delivered, demand, rtol=1e-5, atol=1e-6)

    hvac_actions = actions[:, env.action_names[0].index(action_name)]
    assert np.all(np.abs(hvac_actions) <= 1.0)
    cooling_sign = action_name == 'cooling_or_heating_device' and not heating
    assert np.all(hvac_actions <= 0.0) if cooling_sign else np.all(hvac_actions >= 0.0)

    identity = agent.comparison_identity()['parameters']
    assert identity['hvac'] == 'dataset_demand'
    assert identity['definition_version'] == agent.DEFINITION_VERSION + '+hvac-dataset-demand-v1'


@pytest.mark.parametrize('controller', RBCS)
def test_rbc_hvac_matches_the_v3_bau_hvac(controller):
    """Same HVAC rule as the BAU under baseline_version=3: the same heat each step."""

    dataset, _, start, heating = CASES['heating_device']
    rbc, _, _ = _run(controller, dataset, start)
    bau, _, _ = _run(BusinessAsUsualAgent, dataset, start, hvac='dataset_demand')
    np.testing.assert_array_equal(_delivered_and_demand(rbc.buildings[0], heating)[0],
                                  _delivered_and_demand(bau.buildings[0], heating)[0])


@pytest.mark.parametrize('controller', RBCS)
def test_rbc_hvac_off_still_sends_zero(controller):
    dataset, action_name, start, heating = CASES['heating_device']
    env, agent, actions = _run(controller, dataset, start, hvac='off')
    building = env.buildings[0]
    assert agent.hvac == 'off'
    assert np.all(actions[:, env.action_names[0].index(action_name)] == 0.0)
    assert 'hvac' not in agent.comparison_identity()['parameters']
    assert agent.comparison_identity()['parameters']['definition_version'] == agent.DEFINITION_VERSION

    delivered, demand = _delivered_and_demand(building, heating)
    lookback = building.dynamics.lookback
    assert demand[lookback + 1:].sum() > 0.0
    assert delivered[lookback + 1:].sum() == 0.0


def test_invalid_hvac_is_rejected():
    env = CityLearnEnv(_schema(CASES['heating_device'][0]), central_agent=True, episode_time_steps=4)

    with pytest.raises(ValueError, match='hvac must be one of'):
        RBCSmartPolicy(env, hvac='thermostat')


def test_zero_action_agent_still_sends_zero():
    dataset, action_name, start, _ = CASES['heating_device']
    env = CityLearnEnv(_schema(dataset), central_agent=True, episode_time_steps=4)
    env.reset()
    actions = ZeroActionAgent(env).predict(env.observations)
    assert actions[0][env.action_names[0].index(action_name)] == 0.0


def _evaluate(controller, hvac):
    env = CityLearnEnv(str(MINUTE_EV_SCHEMA), central_agent=True, random_seed=0, render_mode='none')
    agent = controller(env, hvac=hvac)
    observations, _ = env.reset(seed=0)
    actions = []

    while not env.terminated:
        action = agent.predict(observations, deterministic=True)
        actions.append(action[0])
        observations, *_ = env.step(action)

    return env, agent, np.asarray(actions), env.evaluate_v2(), env.evaluate()


@pytest.mark.parametrize('controller', RBCS)
def test_rbc_without_hvac_actions_is_unchanged(controller):
    off_env, off_agent, off_actions, off_kpis, off_legacy = _evaluate(controller, 'off')
    on_env, on_agent, on_actions, on_kpis, on_legacy = _evaluate(controller, 'dataset_demand')
    assert not any(a in names for names in on_env.action_names
                   for a in ('heating_device', 'cooling_device', 'cooling_or_heating_device'))

    np.testing.assert_array_equal(off_actions, on_actions)
    for left, right in zip(off_env.buildings, on_env.buildings):
        np.testing.assert_array_equal(left.net_electricity_consumption, right.net_electricity_consumption)

    pd.testing.assert_frame_equal(off_kpis, on_kpis)
    pd.testing.assert_frame_equal(off_legacy, on_legacy)
    # The identity is the one of earlier releases, so earlier runs stay comparable.
    assert on_agent.comparison_identity()['parameters'] == off_agent.comparison_identity()['parameters']
