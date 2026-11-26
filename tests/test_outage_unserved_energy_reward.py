"""OutageUnservedEnergyReward and the power_outage_unserved_energy observation it reads."""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.internal.service_energy import unserved_energy
from citylearn.reward_function import (
    ComfortReward, MultiBuildingRewardFunction, OutageUnservedEnergyReward, RewardFunction,
)

DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'
STEPS = 48
REWARD_PATH = 'citylearn.reward_function.OutageUnservedEnergyReward'


def _schema(outages: bool = True, central_agent: bool = True, reward_function: dict = None):
    path = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / DATASET / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    schema['central_agent'] = central_agent
    schema['reward_function'] = reward_function or {'type': 'citylearn.reward_function.RewardFunction', 'attributes': {}}

    for building in schema['buildings'].values():
        building['power_outage'] = {
            'simulate_power_outage': outages,
            'stochastic_power_outage': outages,
            # The base model marks about half of the time steps as outages, so short tests see many.
            'stochastic_power_outage_model': {'type': 'citylearn.power_outage.PowerOutage', 'attributes': {'random_seed': 7}},
        }

    return schema


def _env(outages: bool = True, central_agent: bool = True, reward_function: dict = None, **kwargs):
    return CityLearnEnv(
        _schema(outages, central_agent, reward_function), central_agent=central_agent,
        simulation_start_time_step=0, simulation_end_time_step=STEPS - 1, random_seed=0, **kwargs,
    )


def _discharge_actions(env):
    """Discharge every storage fully and run other devices at mid range, within each action space."""

    return [
        [float(low) if 'storage' in name else float((low + high)/2.0) for name, low, high in zip(names, space.low, space.high)]
        for names, space in zip(env.action_names, env.action_space)
    ]


def _run(env):
    """Discharge storage every step so outages leave load unserved, and return the reward series."""

    env.reset()
    rewards = []
    terminated = truncated = False

    while not (terminated or truncated):
        _, reward, terminated, truncated, _ = env.step(_discharge_actions(env))
        rewards.append(reward)

    return np.array(rewards, dtype='float64')


def _kpi_unserved_during_outage(env):
    """Unserved energy per building over outage steps, from the KPI service's service-energy series."""

    kpi = CityLearnKPIService(env)
    totals = []

    for building in env.buildings:
        expected, served = kpi._service_energy(building)
        outage = np.asarray(building.power_outage_signal, dtype='float64')[:len(expected)] > 0
        shortfall = (expected - np.minimum(expected, served)).sum(axis=1)
        totals.append(float(shortfall[outage].sum()))

    return np.array(totals)


def test_unserved_energy_observation_matches_kpi():
    env = _env()
    _run(env)

    for building, kpi_total in zip(env.buildings, _kpi_unserved_during_outage(env)):
        outage = np.asarray(building.power_outage_signal) > 0
        values = np.array([unserved_energy(building, t) for t in range(len(outage))])
        assert outage.any() and values[outage].sum() > 0.0
        np.testing.assert_allclose(values[~outage], 0.0)
        np.testing.assert_allclose(values.sum(), kpi_total, rtol=1e-9, atol=1e-9)


def test_schema_reward_equals_base_reward_without_outages():
    reward_function = {'type': REWARD_PATH, 'attributes': {'coefficient': 10.0}}
    np.testing.assert_allclose(_run(_env(outages=False, reward_function=reward_function)), _run(_env(outages=False)))


def test_schema_reward_penalizes_only_outage_steps_and_matches_kpi():
    reward_function = {'type': REWARD_PATH, 'attributes': {'coefficient': 2.0}}
    env = _env(central_agent=False, reward_function=reward_function)
    assert isinstance(env.reward_function, OutageUnservedEnergyReward)
    penalties = _run(_env(central_agent=False)) - _run(env)
    # Reward k is computed at time step k, before the environment advances.
    outages = np.array([np.asarray(b.power_outage_signal[:len(penalties)]) > 0 for b in env.buildings]).T

    assert np.all(penalties >= -1e-9)
    np.testing.assert_allclose(penalties[~outages], 0.0, atol=1e-9)
    np.testing.assert_allclose(penalties.sum(axis=0)/2.0, _kpi_unserved_during_outage(env), rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize('reward_function', [OutageUnservedEnergyReward, REWARD_PATH])
def test_constructor_override_with_central_agent(reward_function):
    # The constructor argument overrides the schema's reward (citylearn/internal/loading.py, _construct_reward_override).
    env = CityLearnEnv(
        _schema(central_agent=True), central_agent=True, simulation_start_time_step=0, simulation_end_time_step=STEPS - 1,
        random_seed=0, reward_function=reward_function, reward_function_kwargs={'coefficient': 3.0},
    )
    assert isinstance(env.reward_function, OutageUnservedEnergyReward)
    reward = _run(env)
    base = _run(_env(central_agent=True))
    assert reward.shape == base.shape
    np.testing.assert_allclose(base.sum() - reward.sum(), 3.0*_kpi_unserved_during_outage(env).sum(), rtol=1e-6)


def test_per_building_schema_reward():
    reward_function = {'type': {'default': REWARD_PATH}, 'attributes': {'default': {'coefficient': 1.0}}}
    env = _env(central_agent=False, reward_function=reward_function)
    assert isinstance(env.reward_function, MultiBuildingRewardFunction)
    penalties = _run(_env(central_agent=False)) - _run(env)
    np.testing.assert_allclose(penalties.sum(axis=0), _kpi_unserved_during_outage(env), rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize('base_reward, expected_type', [
    (None, RewardFunction),
    ('citylearn.reward_function.ComfortReward', ComfortReward),
    ({'type': 'citylearn.reward_function.ComfortReward', 'attributes': {'band': 2.0}}, ComfortReward),
])
def test_base_reward_forms(base_reward, expected_type):
    reward = OutageUnservedEnergyReward(None, base_reward=base_reward)
    assert type(reward.base_reward) is expected_type
    if isinstance(base_reward, dict):
        assert reward.base_reward.band == 2.0

    instance = ComfortReward(None)
    assert OutageUnservedEnergyReward(None, base_reward=instance).base_reward is instance


def test_invalid_base_reward_is_rejected():
    with pytest.raises(TypeError, match='base_reward'):
        OutageUnservedEnergyReward(None, base_reward=42)


def test_required_observation_names_add_the_unserved_energy_observation():
    names = OutageUnservedEnergyReward(None).get_required_observation_names()
    assert set(names) == {'net_electricity_consumption', 'power_outage_unserved_energy'}

    class AllObservations(RewardFunction):
        def calculate(self, observations):
            return [0.0]*len(observations)

    assert OutageUnservedEnergyReward(None, base_reward=AllObservations(None)).get_required_observation_names() is None


def _read_unserved(building):
    return building.observations(
        observation_names=['power_outage_unserved_energy'], normalize=False, periodic_normalization=False,
    )['power_outage_unserved_energy']


def test_agent_observation_reads_the_last_settled_step():
    env = _env()
    env.reset()
    assert all(_read_unserved(b) == 0.0 for b in env.buildings)

    for _ in range(STEPS - 2):
        env.step(_discharge_actions(env))

        for building in env.buildings:
            assert _read_unserved(building) == pytest.approx(unserved_energy(building, building.time_step - 1))


def test_active_observation_stays_within_its_space_limits():
    schema = _schema()
    schema['observations']['power_outage_unserved_energy'] = {'active': True, 'shared_in_central_agent': False}
    env = CityLearnEnv(schema, central_agent=False, simulation_start_time_step=0, simulation_end_time_step=STEPS - 1, random_seed=0)
    env.reset()
    terminated = truncated = False
    seen = []

    while not (terminated or truncated):
        _, _, terminated, truncated, _ = env.step(_discharge_actions(env))

        for building in env.buildings:
            low, high = building.estimate_observation_space_limits()
            value = _read_unserved(building)
            assert low['power_outage_unserved_energy'] <= value <= high['power_outage_unserved_energy']
            seen.append(value)

    assert max(seen) > 0.0
