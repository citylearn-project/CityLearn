"""OutageUnservedEnergyReward: outage-only penalty and agreement with the unserved-energy KPI."""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.reward_function import OutageUnservedEnergyReward, RewardFunction

DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'
STEPS = 48


def _schema(outages: bool, central_agent: bool = True):
    path = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / DATASET / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    schema['central_agent'] = central_agent
    schema['reward_function'] = {'type': 'citylearn.reward_function.RewardFunction', 'attributes': {}}

    for building in schema['buildings'].values():
        building['power_outage'] = {
            'simulate_power_outage': outages,
            'stochastic_power_outage': outages,
            # The base model marks about half of the time steps as outages, so short tests see many.
            'stochastic_power_outage_model': {'type': 'citylearn.power_outage.PowerOutage', 'attributes': {'random_seed': 7}},
        }

    return schema


def _env(outages: bool = True, central_agent: bool = True):
    return CityLearnEnv(
        _schema(outages, central_agent), central_agent=central_agent,
        simulation_start_time_step=0, simulation_end_time_step=STEPS - 1, random_seed=0,
    )


def _discharge_actions(env):
    """Discharge every storage fully and run other devices at mid range, within each action space."""

    actions = []

    for names, space in zip(env.action_names, env.action_space):
        actions.append([
            float(low) if 'storage' in name else float((low + high)/2.0)
            for name, low, high in zip(names, space.low, space.high)
        ])

    return actions


def _run(env, reward_function=None):
    """Discharge storage every step so outages leave load unserved, and return the reward series."""

    if reward_function is not None:
        env.reward_function = reward_function

    env.reset()
    rewards = []
    terminated = False

    while not terminated:
        _, reward, terminated, _, _ = env.step(_discharge_actions(env))
        rewards.append(reward)

    return np.array(rewards, dtype='float64')


def _kpi_unserved_during_outage(env):
    """Unserved energy per building over outage steps, from the KPI service's own service-energy series."""

    kpi = CityLearnKPIService(env)
    totals = []

    for building in env.buildings:
        expected, served = kpi._service_energy(building)
        outage = np.asarray(building.power_outage_signal, dtype='float64')[:len(expected)] > 0
        shortfall = (expected - np.minimum(expected, served)).sum(axis=1)
        totals.append(float(shortfall[outage].sum()))

    return np.array(totals)


def test_reward_equals_base_reward_without_outages():
    base = _run(_env(outages=False))
    env = _env(outages=False)
    reward = _run(env, OutageUnservedEnergyReward(env, coefficient=10.0))
    np.testing.assert_allclose(reward, base)


def test_penalty_is_applied_only_at_outage_steps_and_matches_unserved_energy():
    # Two environments with the same schedule and actions: one with the base reward, one with the outage reward.
    base_env = _env(outages=True, central_agent=False)
    env = _env(outages=True, central_agent=False)
    env.reward_function = OutageUnservedEnergyReward(env, coefficient=2.0, base_reward=RewardFunction(env.get_metadata()))
    base = _run(base_env)
    reward = _run(env)
    penalties = base - reward
    # Reward k is computed at time step k, before the environment advances.
    outages = np.array([np.asarray(b.power_outage_signal[:len(penalties)]) > 0 for b in env.buildings]).T

    assert outages.any(), 'test schedule should contain outages'
    assert np.all(penalties >= -1e-9)
    np.testing.assert_allclose(penalties[~outages], 0.0, atol=1e-9)
    assert penalties[outages].sum() > 0.0, 'discharging every step should leave some load unserved during outages'
    np.testing.assert_allclose(penalties.sum(axis=0)/2.0, _kpi_unserved_during_outage(env), rtol=1e-6, atol=1e-6)


def test_central_reward_is_base_reward_minus_summed_unserved_energy():
    env = _env(outages=True, central_agent=True)
    reward = _run(env, OutageUnservedEnergyReward(env, coefficient=3.0))
    base = _run(_env(outages=True, central_agent=True))
    assert reward.shape == base.shape
    # Same actions give the same physics, so only the penalty differs.
    np.testing.assert_allclose(base.sum() - reward.sum(), 3.0*_kpi_unserved_during_outage(env).sum(), rtol=1e-6)


def test_default_base_reward_is_the_environment_reward():
    env = _env(outages=False)
    original = env.reward_function
    rf = OutageUnservedEnergyReward(env)
    assert rf.base_reward is original
    assert rf.coefficient == 1.0
