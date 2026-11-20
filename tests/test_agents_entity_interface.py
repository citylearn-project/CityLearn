"""Generic and SAC-based agents on the entity interface, and rule baselines as SACRBC/MARLISARBC exploration (#250)."""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.agents.base import Agent
from citylearn.agents.baseline import RBCBasicPolicy, ZeroActionBaselineAgent
from citylearn.citylearn import CityLearnEnv

DATASET = 'citylearn_challenge_2022_phase_all_plus_evs'
SAC_HYPERPARAMETERS = dict(
    hidden_dimension=[8, 8], batch_size=4, lr=1e-3, replay_buffer_capacity=100,
    standardize_start_time_step=20, end_exploration_time_step=20,
)


def _schema():
    # Read the schema in place: loading the dataset by name copies it into the shared cache, which races under xdist.
    path = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / DATASET / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    return schema


def _env(interface, central_agent=False, **kwargs):
    return CityLearnEnv(
        _schema(), interface=interface, central_agent=central_agent, buildings=[0, 1],
        episode_time_steps=6, random_seed=0, **kwargs,
    )


def _run(env, agent, steps=3):
    observations, _ = env.reset()
    actions = []

    for _ in range(steps):
        action = agent.predict(observations)
        actions.append(action)
        observations, *_ = env.step(action)

    return actions


@pytest.mark.parametrize('central_agent', [False, True])
@pytest.mark.parametrize('agent_class', [Agent, ZeroActionBaselineAgent])
def test_generic_agents_act_on_the_entity_interface(agent_class, central_agent):
    env = _env('entity', central_agent=central_agent)
    agent = agent_class(env)
    flat = env.flat_action_space

    assert [s.shape for s in agent.action_space] == [s.shape for s in flat]

    for action in _run(env, agent):
        assert [len(a) for a in action] == [s.shape[0] for s in flat]

        if agent_class is ZeroActionBaselineAgent:
            assert all(v == 0.0 for a in action for v in a)

    env.close()


def test_generic_agents_keep_the_flat_spaces_on_the_flat_interface():
    env = _env('flat')
    agent = ZeroActionBaselineAgent(env)

    for agent_spaces, env_spaces in ((agent.action_space, env.action_space), (agent.observation_space, env.observation_space)):
        assert isinstance(agent_spaces, list) and agent_spaces == env_spaces
    env.close()


def test_reinforcement_learning_agents_require_the_flat_interface():
    pytest.importorskip('torch')
    pytest.importorskip('sklearn')
    from citylearn.agents.marlisa import MARLISA
    from citylearn.agents.q_learning import TabularQLearning
    from citylearn.agents.sac import SAC, SACRBC

    env = _env('entity')

    for agent_class in (SAC, SACRBC, MARLISA, TabularQLearning):
        with pytest.raises(ValueError, match="requires interface='flat'"):
            agent_class(env)

    env.close()


def _exploration_actions(agent, env, steps=3):
    observations, _ = env.reset()
    actions = []

    for _ in range(steps):
        action = agent.predict(observations)
        actions.append(np.asarray([v for vector in action for v in vector], dtype='float64'))
        observations, *_ = env.step(action)

    return actions


@pytest.mark.parametrize('learner', ['SACRBC', 'MARLISARBC'])
@pytest.mark.parametrize('form', ['instance', 'class', 'path'])
def test_rule_baselines_guide_sac_exploration(learner, form):
    torch = pytest.importorskip('torch')
    pytest.importorskip('sklearn')
    from citylearn.agents.marlisa import MARLISARBC
    from citylearn.agents.sac import SACRBC

    learner_class = {'SACRBC': SACRBC, 'MARLISARBC': MARLISARBC}[learner]
    torch.manual_seed(0)
    env = _env('flat')
    rbc = {
        'instance': RBCBasicPolicy(env, basic_price_policy='forecast_relative'),
        'class': RBCBasicPolicy,
        'path': 'citylearn.agents.baseline.RBCBasicPolicy',
    }[form]
    rbc_kwargs = {} if form == 'instance' else {'basic_price_policy': 'forecast_relative'}
    # The learner's hyperparameters stay with the learner; the rest reaches the baseline.
    # MARLISA's PCA needs fewer components than the short replay buffer holds.
    learner_kwargs = {'pca_compression': 0.1} if learner == 'MARLISARBC' else {}
    agent = learner_class(env, rbc=rbc, **SAC_HYPERPARAMETERS, **learner_kwargs, **rbc_kwargs)

    assert isinstance(agent.rbc, RBCBasicPolicy)
    assert agent.rbc.hyperparameters == {'basic_price_policy': 'forecast_relative'}
    assert agent.lr == SAC_HYPERPARAMETERS['lr']

    guided = _exploration_actions(agent, env)
    env.close()

    reference_env = _env('flat')
    reference = RBCBasicPolicy(reference_env, basic_price_policy='forecast_relative')
    observations, _ = reference_env.reset()
    expected = []

    for _ in range(len(guided)):
        action = reference.predict(observations)
        expected.append(np.asarray([v for vector in action for v in vector], dtype='float64'))
        observations, *_ = reference_env.step(action)

    reference_env.close()
    np.testing.assert_array_equal(np.concatenate(guided, axis=None), np.concatenate(expected, axis=None))


def test_rule_baseline_instance_must_share_the_environment():
    pytest.importorskip('torch')
    from citylearn.agents.sac import SACRBC

    env, other = _env('flat'), _env('flat')

    with pytest.raises(ValueError, match='same environment'):
        SACRBC(env, rbc=RBCBasicPolicy(other), **SAC_HYPERPARAMETERS)

    env.close()
    other.close()
