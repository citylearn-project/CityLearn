"""Regression tests for MARLISA, MARLISARBC, TabularQLearning, the clipped and discrete wrappers and one-hot encoding."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('torch')
pytest.importorskip('sklearn')

from gymnasium import spaces

from citylearn.agents.marlisa import MARLISA, MARLISARBC
from citylearn.agents.q_learning import TabularQLearning
from citylearn.agents.rbc import BasicRBC
from citylearn.citylearn import CityLearnEnv
from citylearn.preprocessing import OnehotEncoding
from citylearn.wrappers import (
    ClippedObservationWrapper,
    DiscreteActionWrapper,
    DiscreteObservationWrapper,
    NormalizedActionWrapper,
    NormalizedObservationWrapper,
    TabularQLearningObservationWrapper,
    TabularQLearningWrapper,
)

DATASET = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all'


def _schema(observations=None, actions=None):
    schema = json.loads((DATASET / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASET)

    if observations is not None:
        for name in schema['observations']:
            schema['observations'][name]['active'] = name in observations

    if actions is not None:
        for name in schema['actions']:
            schema['actions'][name]['active'] = name in actions

    return schema


def test_marlisa_learns_with_pca_compression_below_one():
    env = CityLearnEnv(_schema(), central_agent=False, episode_time_steps=24, buildings=[0, 1], random_seed=0)
    agent = MARLISA(
        env, hidden_dimension=[8, 8], pca_compression=0.5, information_sharing=True, batch_size=8,
        start_regression_time_step=2, standardize_start_time_step=30, end_exploration_time_step=31,
    )

    # The networks used to read the uncompressed size and failed once the replay buffer held PCA output.
    agent.learn(episodes=2)

    assert all(agent.pca_flag)
    for i, policy in enumerate(agent.policy_net):
        components = agent.pca[i].n_components
        # PCA compresses the encoded observations and the two coordination variables of information sharing.
        assert components == int(0.5*(agent.observation_dimension[i] + 2))
        assert policy.linear1.in_features == components
        assert agent.soft_q_net1[i].linear1.in_features == components + agent.action_dimension[i]


def test_marlisa_rbc_explores_with_its_rbc():
    def make_env():
        return CityLearnEnv(_schema(), central_agent=False, episode_time_steps=8, buildings=[0, 1], random_seed=3)

    env = make_env()
    agent = MARLISARBC(env, rbc=BasicRBC, hidden_dimension=[8, 8])
    reference = BasicRBC(make_env())
    observations, _ = env.reset()

    for _ in range(3):
        expected = reference.predict(observations)
        actions = agent.predict(observations)
        np.testing.assert_allclose(actions, expected)
        observations, _, _, _, _ = env.step(actions)


def _q_learning_agent():
    schema = _schema(observations=['hour'], actions=['electrical_storage'])
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=24, buildings=[0])
    env = TabularQLearningWrapper(env, observation_bin_sizes=[{'hour': 24}], action_bin_sizes=[{'electrical_storage': 3}])

    return TabularQLearning(env, learning_rate=1.0, discount_factor=0.9)


@pytest.mark.parametrize('terminated, truncated, expected', [
    (True, False, -2.0),
    # A time-limit truncation still bootstraps from the next state.
    (False, True, -2.0 + 0.9*50.0),
])
def test_tabular_q_learning_does_not_bootstrap_from_terminal_states(terminated, truncated, expected):
    agent = _q_learning_agent()
    agent.q[0][:] = np.nan
    agent.q[0][4] = [10.0, 50.0, 5.0]

    agent.update([[3]], [[1]], [-2.0], [[4]], terminated=terminated, truncated=truncated)

    assert agent.q[0][3, 1] == pytest.approx(expected)


def test_clipped_observation_wrapper_does_not_change_the_env_observations():
    # One fixed split, so both resets start the same episode.
    env = CityLearnEnv(_schema(), central_agent=True, episode_time_steps=[[0, 3]], buildings=[0])
    wrapper = ClippedObservationWrapper(env)
    raw, _ = env.reset()
    raw = [list(o) for o in raw]
    # A space narrower than the data, so that clipping changes values.
    narrow = env.observation_space[0]
    wrapper.observation_space = [spaces.Box(low=narrow.low, high=narrow.low, dtype=np.float32)]

    clipped, _ = wrapper.reset()

    np.testing.assert_allclose(clipped[0], narrow.low)
    assert env.observations == raw


def test_discrete_observation_wrapper_bins_the_wrapped_observations():
    env = CityLearnEnv(_schema(), central_agent=True, episode_time_steps=4, buildings=[0, 1])
    normalized = NormalizedObservationWrapper(env)
    wrapper = DiscreteObservationWrapper(normalized, default_bin_size=5)
    normalized_observations, _ = normalized.reset()

    observations = wrapper.observation(normalized_observations)

    # Periodic observations become cos and sin features, so there are more of them than active observations.
    assert len(wrapper.observation_space[0]) == len(normalized_observations[0]) == len(normalized.observation_names[0])
    assert wrapper.observation_space[0].contains(np.array(observations[0]))
    space = normalized.observation_space[0]
    expected = [
        np.digitize(o, np.linspace(low, high, 5), right=True)
        for o, low, high in zip(normalized_observations[0], space.low, space.high)
    ]
    assert observations[0] == expected


def test_discrete_observation_wrapper_puts_values_above_the_space_in_the_top_bin():
    env = CityLearnEnv(_schema(), central_agent=False, episode_time_steps=4, buildings=[0])
    wrapper = DiscreteObservationWrapper(env, default_bin_size=5)
    above = [list(env.observation_space[0].high + 1.0)]

    observations = wrapper.observation(above)

    assert observations == [[4]*len(above[0])]
    assert wrapper.observation_space[0].contains(np.array(observations[0]))


def test_discrete_action_wrapper_bins_the_wrapped_action_space():
    env = CityLearnEnv(_schema(actions=['electrical_storage']), central_agent=True, episode_time_steps=4, buildings=[0])
    normalized = NormalizedActionWrapper(env)
    wrapper = DiscreteActionWrapper(normalized, default_bin_size=3)

    # The bins span NormalizedActionWrapper's [0, 1] space, which then maps them onto the env's space.
    assert wrapper.action([[0]]) == [[0.0]]
    assert wrapper.action([[1]]) == [[0.5]]
    space = env.action_space[0]
    assert normalized.action(wrapper.action([[2]])) == [[pytest.approx(float(space.high[0]))]]


def test_tabular_q_learning_observation_space_covers_every_encoded_state():
    schema = _schema(observations=['hour', 'day_type'], actions=['electrical_storage'])
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=24, buildings=[0])
    wrapper = TabularQLearningObservationWrapper(env, bin_sizes=[{'hour': 4, 'day_type': 3}])
    high = [list(env.observation_space[0].high + 1.0)]

    state = wrapper.observation(wrapper.env.observation(high))

    assert wrapper.observation_space[0].n == 4*3
    # Values above the space fall into the top bins, i.e. the last of the 4*3 states.
    assert state == [[4*3 - 1]]

    agent = TabularQLearning(
        TabularQLearningWrapper(
            CityLearnEnv(schema, central_agent=True, episode_time_steps=24, buildings=[0]),
            observation_bin_sizes=[{'hour': 4, 'day_type': 3}], action_bin_sizes=[{'electrical_storage': 3}],
        ),
        learning_rate=1.0,
    )
    assert agent.q[0].shape == (4*3, 3)
    agent.update([state[0]], [[0]], [1.0], [state[0]], terminated=False, truncated=False)
    assert agent.q[0][4*3 - 1, 0] == pytest.approx(1.0)


def test_onehot_encoding_rejects_unknown_values():
    encoder = OnehotEncoding([1, 2, 3])

    np.testing.assert_array_equal(encoder*2, [0.0, 1.0, 0.0])
    np.testing.assert_array_equal(2.0*encoder, [0.0, 1.0, 0.0])

    with pytest.raises(ValueError, match='not one of the OnehotEncoding classes'):
        encoder*4

    with pytest.raises(ValueError, match='not one of the OnehotEncoding classes'):
        math.nan*encoder
