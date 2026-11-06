"""Reward function construction and per-building reward aggregation."""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.reward_function import MultiBuildingRewardFunction, RewardFunction, SolarPenaltyReward

DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'


def _schema(**reward_function):
    path = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / DATASET / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)

    if reward_function:
        schema['reward_function'] = reward_function

    return schema


def _first_reward(env):
    env.reset()
    return env.step([[0.0] * space.shape[0] for space in env.action_space])[1]


@pytest.mark.parametrize('central_agent', [False, True])
def test_per_building_reward_functions_return_flat_rewards(central_agent):
    schema = _schema(type={'default': 'citylearn.reward_function.RewardFunction'}, attributes={})
    multi = CityLearnEnv(schema, central_agent=central_agent, simulation_start_time_step=0, simulation_end_time_step=5)
    single = CityLearnEnv(
        _schema(type='citylearn.reward_function.RewardFunction', attributes={}),
        central_agent=central_agent, simulation_start_time_step=0, simulation_end_time_step=5,
    )

    assert isinstance(multi.reward_function, MultiBuildingRewardFunction)
    reward = _first_reward(multi)
    assert all(isinstance(value, float) for value in reward)
    assert len(reward) == (1 if central_agent else len(multi.buildings))
    np.testing.assert_allclose(reward, _first_reward(single))


def test_reward_function_instance_is_used_as_given():
    reward_function = RewardFunction(None, exponent=2.0)
    env = CityLearnEnv(DATASET, reward_function=reward_function)

    assert env.reward_function is reward_function
    assert env.reward_function.env_metadata['central_agent'] == env.central_agent


def test_override_class_does_not_receive_other_types_schema_attributes():
    # The dataset schema configures ComfortReward with attributes SolarPenaltyReward does not accept.
    env = CityLearnEnv(DATASET, reward_function=SolarPenaltyReward)
    assert type(env.reward_function) is SolarPenaltyReward


def test_empty_reward_function_kwargs_are_respected():
    schema = _schema(type='citylearn.reward_function.RewardFunction', attributes={'exponent': 3.0})

    assert CityLearnEnv(schema).reward_function.exponent == 3.0
    assert CityLearnEnv(schema, reward_function_kwargs={}).reward_function.exponent == 1.0
    assert CityLearnEnv(schema, reward_function_kwargs={'exponent': 2.0}).reward_function.exponent == 2.0


def test_override_takes_precedence_over_per_building_schema():
    schema = _schema(type={'default': 'citylearn.reward_function.RewardFunction'}, attributes={})
    env = CityLearnEnv(schema, reward_function='citylearn.reward_function.SolarPenaltyReward')
    assert type(env.reward_function) is SolarPenaltyReward
