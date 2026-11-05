"""Regressions in the bundled reinforcement learning agents."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip('torch')

from citylearn.agents.marlisa import MARLISA
from citylearn.agents.q_learning import TabularQLearning
from citylearn.agents.sac import SAC
from citylearn.citylearn import CityLearnEnv
from citylearn.wrappers import TabularQLearningWrapper

DATASET = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all'


def _schema():
    schema = json.loads((DATASET / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASET)
    return schema


def test_marlisa_coordinated_actions_use_each_buildings_policy(monkeypatch):
    env = CityLearnEnv(_schema(), central_agent=False, episode_time_steps=24, buildings=[0, 1], random_seed=0)
    # More coordination iterations than buildings used to raise IndexError.
    agent = MARLISA(env, hidden_dimension=[8, 8], iterations=3, information_sharing=True)
    calls = []

    for k, net in enumerate(agent.policy_net):
        def sample(_, _k=k, _dimension=agent.action_dimension[k]):
            calls.append(_k)
            action = torch.full((1, _dimension), float(_k))
            return action, None, action

        monkeypatch.setattr(net, 'sample', sample)

    for c in range(len(agent.pca)):
        agent.pca[c] = SimpleNamespace(transform=lambda x: x)

    monkeypatch.setattr(agent, 'get_encoded_observations', lambda i, o: np.asarray(o, dtype=float))
    monkeypatch.setattr(agent, 'get_normalized_observations', lambda i, o: o)
    monkeypatch.setattr(agent, 'predict_demand', lambda i, o, a: 0.0)
    observations = [[0.0]*len(space.low) for space in env.observation_space]

    actions, _ = agent.get_post_exploration_prediction_with_information_sharing(observations, deterministic=True)

    assert calls == [0, 1]*3
    assert [action[0] for action in actions] == [0.0, 1.0]


def _q_learning_agent():
    schema = _schema()
    for name in schema['observations']:
        schema['observations'][name]['active'] = name == 'hour'
    for name in schema['actions']:
        schema['actions'][name]['active'] = name == 'electrical_storage'
    first = next(iter(schema['buildings']))
    for name in schema['buildings']:
        schema['buildings'][name]['include'] = name == first

    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=24)
    env = TabularQLearningWrapper(
        env, observation_bin_sizes=[{'hour': 24}], action_bin_sizes=[{'electrical_storage': 3}],
    )
    return TabularQLearning(env, learning_rate=1.0, discount_factor=0.9)


def test_tabular_q_learning_bootstraps_on_best_next_value():
    agent = _q_learning_agent()
    state, next_state, action, reward = 3, 4, 0, 1.0
    agent.q[0][:] = np.nan
    agent.q[0][next_state] = [5.0, 100.0, 1.0]
    agent.q[0][state, action] = 0.0

    agent.update([[state]], [[action]], [reward], [[next_state]], terminated=False, truncated=False)

    # Previously r + gamma*argmax-index = 1.9.
    assert agent.q[0][state, action] == pytest.approx(reward + 0.9*100.0)


def test_tabular_q_learning_unvisited_next_state_contributes_zero():
    agent = _q_learning_agent()
    agent.q[0][:] = np.nan

    agent.update([[3]], [[0]], [2.0], [[4]], terminated=False, truncated=False)

    assert agent.q[0][3, 0] == pytest.approx(2.0)


@pytest.fixture(scope='module')
def sac_env():
    return CityLearnEnv(_schema(), central_agent=False, episode_time_steps=24, buildings=[0], random_seed=0)


def test_rlc_accepts_documented_action_scaling_coefficient(sac_env):
    agent = SAC(sac_env, action_scaling_coefficient=1.0, hidden_dimension=[8, 8])
    policy = agent.policy_net[0]

    assert agent.action_scaling_coefficient == 1.0
    np.testing.assert_allclose((policy.action_bias + policy.action_scale).numpy(), sac_env.action_space[0].high)
    np.testing.assert_allclose((policy.action_bias - policy.action_scale).numpy(), sac_env.action_space[0].low)


def test_rlc_misspelled_action_scaling_coefficient_is_deprecated_alias(sac_env):
    with pytest.warns(DeprecationWarning, match='action_scaling_coefficienct'):
        agent = SAC(sac_env, action_scaling_coefficienct=0.8, hidden_dimension=[8, 8])

    assert agent.action_scaling_coefficient == 0.8

    with pytest.raises(TypeError, match='conflicting'):
        SAC(sac_env, action_scaling_coefficient=1.0, action_scaling_coefficienct=0.8, hidden_dimension=[8, 8])


def test_rlc_action_scaling_coefficient_default_unchanged(sac_env):
    assert SAC(sac_env, hidden_dimension=[8, 8]).action_scaling_coefficient == 0.5
