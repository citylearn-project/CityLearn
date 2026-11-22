"""Every bundled non-learning agent runs and can be evaluated on current datasets (CityLearn #309).

``NoControlAgent`` could not be evaluated against the native BAU reference, and failed under a
dynamic topology; the hour-based RBCs raised ``Unknown action name`` on datasets with deferrable
appliances.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.agents.base import Agent, NoControlAgent
from citylearn.agents.baseline import (
    BusinessAsUsualAgent, RBCBasicPolicy, RBCCommunityPolicy, RBCSmartPolicy, ZeroActionAgent,
)
from citylearn.agents.rbc import (
    BasicBatteryRBC, BasicElectricVehicleRBC_ReferenceController, BasicRBC, HourRBC, OptimizedRBC,
)
from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT/'data'/'datasets'
AGENTS = [
    Agent, NoControlAgent, ZeroActionAgent, HourRBC, BasicRBC, OptimizedRBC, BasicBatteryRBC,
    BasicElectricVehicleRBC_ReferenceController, RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy,
    BusinessAsUsualAgent,
]
# One flat dataset per family with deferrable appliances: the challenge EV dataset and a Portuguese REC.
DATASET_NAMES = ['citylearn_challenge_2022_phase_all_plus_evs', 'pt_rec_4']
HOUR_RBCS = [BasicRBC, OptimizedRBC, BasicBatteryRBC]


def _schema(name):
    # Read the schema in place: loading by name copies the dataset into the shared cache, which races under xdist.
    path = DATASETS/name/'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    return schema


def _env(name, **kwargs):
    kwargs = {'simulation_start_time_step': 0, 'simulation_end_time_step': 7, 'random_seed': 0, **kwargs}
    return CityLearnEnv(_schema(name), interface='flat', **kwargs)


def _run(env, agent):
    observations, _ = env.reset()

    while not env.terminated:
        observations, *_ = env.step(agent.predict(observations, deterministic=True))


@pytest.mark.parametrize('dataset', DATASET_NAMES)
@pytest.mark.parametrize('agent_class', AGENTS, ids=lambda c: c.__name__)
def test_bundled_agent_runs_and_is_evaluated(agent_class, dataset):
    env = _env(dataset)
    _run(env, agent_class(env))
    kpis = env.evaluate_v2(include_business_as_usual=False)

    assert len(kpis) > 0 and np.isfinite(kpis['value'].astype(float)).any()
    env.close()


@pytest.mark.parametrize('dataset', DATASET_NAMES)
@pytest.mark.parametrize('agent_class', HOUR_RBCS, ids=lambda c: c.__name__)
def test_hour_rbcs_start_deferrable_cycles_as_soon_as_allowed(agent_class, dataset):
    env = _env(dataset)
    agent = agent_class(env)
    deferrable = [n for names in agent.action_names for n in names if n.startswith('deferrable_appliance')]

    assert deferrable
    for action_map, names in zip(agent.action_map, agent.action_names):
        for name in names:
            if name.startswith('deferrable_appliance'):
                assert set(action_map[name].values()) == {1.0}
                assert sorted(action_map[name]) == list(range(1, 25))

    env.close()


def test_hour_rbcs_keep_their_schedule_for_other_actions():
    env = _env('citylearn_challenge_2022_phase_all_plus_evs')
    action_map = BasicRBC(env).action_map[0]

    assert action_map['electrical_storage'][3] == 0.091
    assert action_map['electrical_storage'][12] == -0.08
    env.close()


def test_hour_rbcs_still_reject_unknown_actions():
    env = _env('citylearn_challenge_2022_phase_all_plus_evs')
    agent = BasicRBC(env)
    agent.action_names = [['not_an_action']]

    with pytest.raises(ValueError, match='Unknown action name: not_an_action'):
        agent.action_map = None

    env.close()


def test_no_control_agent_is_evaluated_against_the_native_bau():
    env = _env('citylearn_challenge_2022_phase_all_plus_evs', buildings=[0, 1])
    loaded = [sorted(b.active_actions) for b in env.buildings]
    agent = NoControlAgent(env)

    assert all(b.active_actions == [] for b in env.buildings)
    _run(env, agent)
    kpis = env.evaluate_v2()

    assert kpis['cost_function'].str.contains('business_as_usual').any()
    assert [b._no_control_loaded_active_actions for b in env.buildings] == loaded
    env.close()


@pytest.mark.parametrize('central_agent', [False, True])
def test_no_control_agent_runs_under_dynamic_topology(central_agent):
    schema = DATASETS/'pt_rec_30'/'evaluation'/'rec_30_topology.json'
    # Member_007 joins at step 4080 and a battery is commissioned at Member_014 at step 4200.
    env = CityLearnEnv(
        str(schema), simulation_start_time_step=4075, simulation_end_time_step=4205, central_agent=central_agent,
    )
    agent = NoControlAgent(env)
    observations, _ = env.reset()
    members = len(env.buildings)

    while not env.terminated:
        actions = agent.predict(observations)
        # Members and assets that joined since the last step are disabled before acting.
        assert all(len(a) == 0 for a in actions)
        assert all(b.active_actions == [] for b in env.buildings)
        observations, *_ = env.step(actions)

    assert len(env.buildings) > members
    env.close()
