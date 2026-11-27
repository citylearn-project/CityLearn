"""Seeded sampling (#441), applied actions in the CLI (#439), reward arguments (#438) and the zero bin (#440)."""

from pathlib import Path

import numpy as np
import pytest

from citylearn.agents.base import Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi_family_audit import _reward_parameters
from citylearn.reward_function import (
    Electric_Vehicles_Reward_Function, OutageUnservedEnergyReward, RewardFunction, SolarPenaltyReward,
)
from citylearn.wrappers import (
    DiscreteActionWrapper, NormalizedActionWrapper, NormalizedObservationWrapper, StableBaselines3Wrapper,
    TabularQLearningWrapper,
)

SCHEMA = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"


def _flat(parsed):
    """Values of parsed actions, with the per-device mappings flattened in order."""

    values = []
    for building in parsed:
        for value in building.values():
            values.extend(value.values() if isinstance(value, dict) else [value])
    return [float(v) for v in values]


def _first(space):
    return space[0] if isinstance(space, list) else space


def _env(**kwargs) -> CityLearnEnv:
    kwargs = {"central_agent": True, "episode_time_steps": 4, "random_seed": 0, **kwargs}
    return CityLearnEnv(str(SCHEMA), **kwargs)


# --- #441 -----------------------------------------------------------------------------------------------------


def test_central_and_wrapped_action_spaces_keep_their_seed():
    for make in (
        lambda: _env(),
        lambda: NormalizedActionWrapper(_env()),
        lambda: StableBaselines3Wrapper(NormalizedObservationWrapper(_env())),
        lambda: DiscreteActionWrapper(_env()),
    ):
        envs = [make(), make()]
        try:
            # The same space object on every access, so seeding it lasts.
            assert all(_first(e.action_space) is _first(e.action_space) for e in envs)
            samples = []
            for e in envs:
                _first(e.action_space).seed(7)
                samples.append([_first(e.action_space).sample() for _ in range(5)])
            for a, b in zip(*samples):
                np.testing.assert_array_equal(a, b)
        finally:
            for e in envs:
                e.close()


def test_random_agent_actions_follow_the_random_seed():
    runs = []
    for _ in range(2):
        env = _env()
        try:
            agent = Agent(env)
            env.reset(seed=0)
            runs.append([np.asarray(agent.predict(None)[0]) for _ in range(3)])
        finally:
            env.close()
    for a, b in zip(*runs):
        np.testing.assert_array_equal(a, b)


def test_a_seed_set_before_the_agent_is_kept():
    env = _env()
    try:
        env.action_space[0].seed(123)
        expected = env.action_space[0].sample()
        env.action_space[0].seed(123)
        agent = Agent(env)
        np.testing.assert_array_equal(np.asarray(agent.predict(None)[0], dtype="float32"), expected)
    finally:
        env.close()


# --- #439 -----------------------------------------------------------------------------------------------------


def test_step_keeps_the_actions_applied_after_the_wrappers():
    env = NormalizedActionWrapper(_env())
    try:
        env.reset(seed=0)
        raw = [np.full(env.action_space[0].shape[0], 0.5, dtype="float32")]
        expected = env.unwrapped._parse_actions(env.action(raw))
        env.step(raw)
        # The recorded actions are the denormalised ones the environment applied, not the agent's 0.5.
        assert _flat(env.unwrapped._last_parsed_actions) == pytest.approx(_flat(expected))
        assert _flat(expected) != pytest.approx([0.5] * len(_flat(expected)))
    finally:
        env.close()


def test_tabular_wrapper_step_records_the_applied_values():
    env = TabularQLearningWrapper(_env(active_observations=["hour"]))
    try:
        env.reset(seed=0)
        env.step([[0]])
        # Index 0 is the lowest bin of every action: the recorded values are those bounds, not the index.
        assert _flat(env.unwrapped._last_parsed_actions) == pytest.approx(list(env.unwrapped.action_space[0].low))
    finally:
        env.close()


# --- #438 -----------------------------------------------------------------------------------------------------


def _metadata():
    env = _env()
    try:
        return env.get_metadata()
    finally:
        env.close()


def test_built_in_rewards_reject_unknown_arguments_with_the_closest_name():
    metadata = _metadata()
    with pytest.raises(TypeError, match="exponent"):
        RewardFunction(metadata, exponant=2.0)
    with pytest.raises(TypeError, match="coefficient"):
        OutageUnservedEnergyReward(metadata, coeficient=2.0)
    # The documented keys are still accepted.
    assert RewardFunction(metadata, exponent=2.0, charging_constraint_penalty_coefficient=3.0).exponent == 2.0


def test_custom_rewards_outside_citylearn_still_receive_extra_arguments():
    class CustomReward(RewardFunction):
        def __init__(self, env_metadata, **kwargs):
            self.my_setting = kwargs.pop("my_setting", None)
            super().__init__(env_metadata, **kwargs)

    assert CustomReward(_metadata(), my_setting=4, other=5).my_setting == 4


def test_ev_reward_takes_the_penalty_coefficient_and_outage_reward_passes_keys_to_its_base():
    metadata = _metadata()
    assert Electric_Vehicles_Reward_Function(metadata, charging_constraint_penalty_coefficient=2.5) \
        .charging_constraint_penalty_coefficient == 2.5
    reward = OutageUnservedEnergyReward(metadata, coefficient=2.0, exponent=3.0)
    assert reward.base_reward.exponent == 3.0
    reward = OutageUnservedEnergyReward(
        metadata, base_reward={"type": "citylearn.reward_function.RewardFunction"}, exponent=2.0,
    )
    assert reward.base_reward.exponent == 2.0
    with pytest.raises(TypeError):
        OutageUnservedEnergyReward(metadata, base_reward=RewardFunction(metadata), exponent=2.0)


def test_reward_evidence_records_only_parameters_the_reward_uses():
    metadata = _metadata()
    assert set(_reward_parameters(RewardFunction(metadata), [])) == {"exponent"}
    assert "charging_constraint_penalty_coefficient" in _reward_parameters(
        Electric_Vehicles_Reward_Function(metadata), [],
    )
    assert "exponent" not in _reward_parameters(SolarPenaltyReward(metadata), [])


# --- #440 -----------------------------------------------------------------------------------------------------


def test_discrete_action_grid_contains_zero():
    grid = DiscreteActionWrapper.action_grid
    assert 0.0 in grid(-1.0, 1.0, 11)
    assert 0.0 in grid(-1.0, 1.0, 10)
    assert 0.0 in grid(-0.3, 1.0, 7)
    np.testing.assert_array_equal(grid(0.0, 1.0, 5), np.linspace(0.0, 1.0, 5))
    np.testing.assert_allclose(grid(-1.0, 1.0, 11), np.round(np.linspace(-1.0, 1.0, 11), 12), atol=1e-12)


def test_discrete_wrapper_defaults_to_eleven_bins_and_can_stay_idle():
    env = DiscreteActionWrapper(_env())
    try:
        assert set(np.asarray(env.action_space[0].nvec).tolist()) == {11}
        env.reset(seed=0)
        cs = env.unwrapped.action_space[0]
        idle = [int(np.argmin(np.abs(DiscreteActionWrapper.action_grid(lo, hi, 11)))) for lo, hi in zip(cs.low, cs.high)]
        env.step([idle])
        expected = [0.0 if lo < 0 < hi else float(lo) for lo, hi in zip(cs.low, cs.high)]
        assert _flat(env.unwrapped._last_parsed_actions) == pytest.approx(expected)
    finally:
        env.close()
