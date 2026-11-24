"""Regression tests for the versioned random streams of agents and neighborhood generation (issue #287).

TabularQLearning and MARLISA used ``RandomState(random_seed + time_step)``, and the neighborhood generator seeded
partial-load simulation ``i`` of building ``b`` with ``b + i``, so streams overlapped across seeds, time steps and
buildings. With ``random_stream_version='v2'`` they come from ``SeedSequence``; ``'v1'`` keeps the 3.6.0 streams.

TabularQLearning also sampled its exploration actions from action spaces that nothing seeded; it now seeds them
from the agent seed, as SAC does, under both versions.
"""

import copy
import json
import random
from pathlib import Path

import gymnasium
from gymnasium import spaces
import numpy as np
import pytest

from citylearn import random_streams
from citylearn.citylearn import CityLearnEnv

DATASET = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all'
STEPS = 12


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


def _q_learning_env(random_seed, random_stream_version):
    from citylearn.wrappers import TabularQLearningWrapper

    env = CityLearnEnv(
        _schema(observations=['hour'], actions=['electrical_storage']), central_agent=True, episode_time_steps=24,
        buildings=[0], random_seed=random_seed, random_stream_version=random_stream_version,
    )

    return TabularQLearningWrapper(env, observation_bin_sizes=[{'hour': 24}], action_bin_sizes=[{'electrical_storage': 3}])


def _q_learning_agent(random_seed, random_stream_version, env=None):
    from citylearn.agents.q_learning import TabularQLearning

    env = _q_learning_env(random_seed, random_stream_version) if env is None else env
    env.reset()

    return TabularQLearning(env)


def _exploration_draws(agent, count=STEPS):
    draws = []

    for time_step in range(count):
        agent.time_step = time_step
        draws.append(agent._TabularQLearning__exploration_draw())

    return np.array(draws)


def _marlisa_agent(random_seed, random_stream_version):
    pytest.importorskip('torch')
    pytest.importorskip('sklearn')
    from citylearn.agents.marlisa import MARLISA

    env = CityLearnEnv(
        _schema(), central_agent=False, episode_time_steps=24, buildings=[0, 1, 2, 3, 4], random_seed=random_seed,
        random_stream_version=random_stream_version,
    )
    env.reset()

    return MARLISA(env, hidden_dimension=[8, 8], information_sharing=True)


def _coordination_orders(agent, count=STEPS):
    orders = []

    for time_step in range(count):
        agent.time_step = time_step
        order = list(range(5))
        agent.shuffle_coordination_order(order)
        orders.append(order)

    return orders


# --- agents follow their environment -----------------------------------------------------------------------------

@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_agents_follow_the_random_stream_version_of_their_environment(version):
    assert _q_learning_agent(0, version).random_stream_version == version


# --- TabularQLearning exploration --------------------------------------------------------------------------------

def test_q_learning_v1_reproduces_the_additive_exploration_seed():
    draws = {seed: _exploration_draws(_q_learning_agent(seed, 'v1')) for seed in (0, 1)}

    np.testing.assert_array_equal(draws[0], [np.random.RandomState(t).random() for t in range(STEPS)])
    # The overlap of #287: seed 0 at time step t + 1 repeats seed 1 at time step t.
    np.testing.assert_array_equal(draws[0][1:], draws[1][:-1])


def test_q_learning_v2_draws_from_one_generator_per_episode():
    agent = _q_learning_agent(0, 'v2')
    episode = agent.episode_tracker.random_stream_episode
    expected = random_streams.generator(0, random_streams.AGENT_EXPLORATION, episode).random(STEPS)

    np.testing.assert_array_equal(_exploration_draws(agent), expected)

    agent.env.reset()
    next_episode = agent.episode_tracker.random_stream_episode
    assert next_episode == episode + 1
    expected = random_streams.generator(0, random_streams.AGENT_EXPLORATION, next_episode).random(STEPS)
    np.testing.assert_array_equal(_exploration_draws(agent), expected)
    # Only the generator of the current episode is kept.
    assert [k for k in agent._random_generators if k[0] == random_streams.AGENT_EXPLORATION] == [
        (random_streams.AGENT_EXPLORATION, next_episode)
    ]


def test_q_learning_v2_streams_of_neighbouring_seeds_do_not_overlap():
    draws = {seed: _exploration_draws(_q_learning_agent(seed, 'v2')) for seed in (0, 1)}

    assert not np.isin(draws[0], draws[1]).any()


def test_q_learning_v2_deterministic_predictions_do_not_consume_exploration_draws():
    agent = _q_learning_agent(0, 'v2')
    observations, _ = agent.env.reset()
    agent.predict(observations, deterministic=True)
    episode = agent.episode_tracker.random_stream_episode

    assert agent._TabularQLearning__exploration_draw() == pytest.approx(
        random_streams.generator(0, random_streams.AGENT_EXPLORATION, episode).random()
    )


# --- TabularQLearning action spaces ------------------------------------------------------------------------------

def _deterministic_fallback_actions(agent, count=STEPS):
    """Actions of deterministic predictions while every Q-value is NaN, which sample the action space."""

    observations, _ = agent.env.reset()

    return [agent.predict(observations, deterministic=True)[0][0] for _ in range(count)]


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_q_learning_runs_with_identically_seeded_envs_act_and_learn_identically(version):
    agents = [_q_learning_agent(7, version) for _ in range(2)]

    agents[0].learn(episodes=2)
    # Global generators are consumed between the runs; a seeded agent must not depend on them.
    random.random(), np.random.random()
    agents[1].learn(episodes=2)

    actions = [[a for a in history if len(a)] for history in agents[0].actions]
    # Exploration dominates (epsilon starts at 1.0), so most actions are samples of the action space.
    assert agents[0].q_exploration[0].sum() > 0
    assert len({a[0] for a in actions[0]}) > 1
    assert actions == [[a for a in history if len(a)] for history in agents[1].actions]

    for name in ('q', 'q_exploration', 'q_exploitation'):
        for a, b in zip(getattr(agents[0], name), getattr(agents[1], name)):
            np.testing.assert_array_equal(a, b)


def test_q_learning_action_spaces_are_seeded_from_the_agent_seed():
    agent = _q_learning_agent(7, 'v2')
    reference = spaces.Discrete(agent.action_space[0].n, seed=agent._get_seed(0, 0))

    assert _deterministic_fallback_actions(agent) == [reference.sample() for _ in range(STEPS)]


def test_q_learning_keeps_the_stream_of_an_action_space_the_caller_seeded():
    # TabularQLearningWrapper builds new spaces on every access; pin them so that the caller can seed them.
    env = gymnasium.Wrapper(_q_learning_env(7, 'v2'))
    env.action_space = env.env.action_space
    env.action_space[0].seed(123)
    reference = copy.deepcopy(env.action_space[0])
    agent = _q_learning_agent(7, 'v2', env=env)

    assert agent.action_space[0] is env.action_space[0]
    assert _deterministic_fallback_actions(agent) == [reference.sample() for _ in range(STEPS)]


# --- MARLISA coordination order ----------------------------------------------------------------------------------

def test_marlisa_v1_reproduces_the_additive_coordination_seed():
    orders = {seed: _coordination_orders(_marlisa_agent(seed, 'v1')) for seed in (0, 1)}
    expected = []

    for t in range(STEPS):
        order = list(range(5))
        np.random.RandomState(t).shuffle(order)
        expected.append(order)

    assert orders[0] == expected
    assert orders[0][1:] == orders[1][:-1]


def test_marlisa_v2_shuffles_with_one_generator_per_episode():
    agent = _marlisa_agent(0, 'v2')
    generator = random_streams.generator(
        0, random_streams.AGENT_COORDINATION_ORDER, agent.episode_tracker.random_stream_episode
    )
    expected = []

    for _ in range(STEPS):
        order = list(range(5))
        generator.shuffle(order)
        expected.append(order)

    assert _coordination_orders(agent) == expected
    assert _coordination_orders(_marlisa_agent(1, 'v2'))[:-1] != expected[1:]


# --- neighborhood partial-load simulations -----------------------------------------------------------------------

def test_partial_load_simulation_seed_v1_is_building_plus_index():
    seeds = {
        (b, i): random_streams.partial_load_simulation_seed(7, b, i, 'v1') for b in (100, 101) for i in range(4)
    }

    assert seeds[(100, 0)] == 100
    # The overlap of #287: simulation i + 1 of building b repeats simulation i of building b + 1.
    assert all(seeds[(100, i + 1)] == seeds[(101, i)] for i in range(3))
    # The neighborhood seed is ignored.
    assert random_streams.partial_load_simulation_seed(8, 100, 1, 'v1') == seeds[(100, 1)]


def test_partial_load_simulation_seed_v2_is_distinct_per_building_simulation_and_seed():
    seeds = {
        (s, b, i): random_streams.partial_load_simulation_seed(s, b, i)
        for s in (7, 8) for b in (100, 101, '102') for i in range(6)
    }

    assert len(set(seeds.values())) == len(seeds)
    assert all(0 <= v < 2**32 for v in seeds.values())
    assert seeds[(7, 100, 2)] == random_streams.derived_seed(7, random_streams.PARTIAL_LOAD_SIMULATION, 100, 2)
    # String and integer building identifiers name the same building.
    assert random_streams.partial_load_simulation_seed(7, '100', 2) == seeds[(7, 100, 2)]


def test_neighborhood_passes_its_stream_version_to_partial_load_seeds():
    neighborhood = pytest.importorskip('citylearn.end_use_load_profiles.neighborhood')

    assert neighborhood.Neighborhood(random_seed=3).random_stream_version == 'v2'
    assert neighborhood.Neighborhood(random_seed=3, random_stream_version='v1').random_stream_version == 'v1'

    with pytest.raises(ValueError, match='random_stream_version'):
        neighborhood.Neighborhood(random_seed=3, random_stream_version='v3')
