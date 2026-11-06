"""Wrapper stacking, agents on wrapped environments and Gymnasium seeding (CityLearn #162).

Gymnasium 1.x no longer forwards unknown attributes through wrappers, so CityLearn code must read
environment attributes from ``env.unwrapped`` (or ``get_wrapper_attr``). These tests run on both the
pinned Gymnasium and 1.x.
"""

import numpy as np
import pytest

from citylearn.agents.base import Agent, get_env_attr
from citylearn.agents.rbc import BasicRBC
from citylearn.citylearn import CityLearnEnv
from citylearn.wrappers import (
    ClippedObservationWrapper,
    DiscreteObservationWrapper,
    NormalizedObservationWrapper,
    RLlibMultiAgentActionWrapper,
    RLlibMultiAgentObservationWrapper,
)

DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'


def _env(central_agent, steps=11):
    return CityLearnEnv(DATASET, central_agent=central_agent, simulation_start_time_step=0, simulation_end_time_step=steps)


@pytest.mark.parametrize('central_agent', [False, True])
def test_normalized_observation_wrapper_on_top_of_another_wrapper(central_agent):
    wrapper = NormalizedObservationWrapper(ClippedObservationWrapper(_env(central_agent)))
    observations, _ = wrapper.reset()
    names = wrapper.observation_names
    spaces = wrapper.observation_space

    for _ in range(3):
        observations, *_ = wrapper.step([[0.0] * space.shape[0] for space in wrapper.unwrapped.action_space])

    assert [len(values) for values in observations] == [len(n) for n in names] == [s.shape[0] for s in spaces]


def test_discrete_observation_wrapper_on_top_of_another_wrapper_central():
    wrapper = DiscreteObservationWrapper(ClippedObservationWrapper(_env(True)))
    observations, _ = wrapper.reset()
    assert len(observations[0]) == len(wrapper.observation_space[0].nvec)


def test_rllib_multi_agent_wrapper_stack_constructs():
    wrapper = RLlibMultiAgentObservationWrapper(RLlibMultiAgentActionWrapper(_env(False)))
    assert set(wrapper.observation_space.keys()) == {f'agent_{i}' for i in range(len(wrapper.unwrapped.buildings))}


@pytest.mark.parametrize(('agent_type', 'wrapper_type'), [
    (BasicRBC, ClippedObservationWrapper),
    (Agent, NormalizedObservationWrapper),
])
def test_agents_learn_on_wrapped_environments(agent_type, wrapper_type):
    wrapper = wrapper_type(_env(True))
    agent = agent_type(wrapper)

    assert agent.observation_names == get_env_attr(wrapper, 'observation_names')
    agent.learn(episodes=1)
    assert wrapper.unwrapped.terminated


def test_reset_seed_seeds_gymnasium_random_generator():
    def draws(seed):
        env = _env(True)
        env.reset(seed=seed)
        return env.np_random.integers(0, 2**31, size=4)

    np.testing.assert_array_equal(draws(7), draws(7))
    assert not np.array_equal(draws(7), draws(8))
