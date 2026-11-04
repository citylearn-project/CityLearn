"""Regressions for observation normalization, the CLI module and occupant set-point updates."""

import importlib
import sys

import numpy as np
import pytest

import citylearn.utilities as utilities
from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet
from citylearn.wrappers import NormalizedObservationWrapper

DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'


@pytest.mark.parametrize('central_agent', [False, True])
def test_normalized_observation_wrapper_matches_building_normalization(central_agent):
    env = CityLearnEnv(DATASET, central_agent=central_agent, simulation_start_time_step=0, simulation_end_time_step=10)
    wrapper = NormalizedObservationWrapper(env)
    observations, _ = wrapper.reset()
    observations, *_ = wrapper.step([[0.0] * space.shape[0] for space in env.action_space])
    expected = NormalizedObservationWrapper(env).observation(env.observations)

    if central_agent:
        assert len(observations[0]) == wrapper.observation_space[0].shape[0]
    else:
        expected_values = [list(b.observations(normalize=True, periodic_normalization=True).values()) for b in env.buildings]
        np.testing.assert_allclose(np.concatenate(observations), np.concatenate(expected_values), rtol=1.0e-6)

    np.testing.assert_allclose(np.concatenate(observations), np.concatenate(expected), rtol=1.0e-6)


@pytest.mark.parametrize('central_agent', [False, True])
def test_normalized_observation_wrapper_keeps_upstream_observation_changes(central_agent):
    env = CityLearnEnv(DATASET, central_agent=central_agent, simulation_start_time_step=0, simulation_end_time_step=10)
    wrapper = NormalizedObservationWrapper(env)
    wrapper.reset()
    names = env.observation_names
    raw = [list(values) for values in env.observations]
    key = 'non_shiftable_load'
    index = names[0].index(key)
    raw[0][index] = raw[0][index] + 1.0  # e.g. a biased sensor upstream

    normalized = wrapper.observation(raw)
    building = env.buildings[0]
    expected = building.transform_observations({key: raw[0][index]}, normalize=True)[key]
    normalized_names = wrapper.observation_names[0]

    assert normalized[0][normalized_names.index(key)] == pytest.approx(expected)
    assert expected != pytest.approx(building.observations(normalize=True, periodic_normalization=True)[key])


def test_cli_module_imports_without_stable_baselines3(monkeypatch):
    monkeypatch.setitem(sys.modules, 'stable_baselines3', None)
    monkeypatch.delitem(sys.modules, 'citylearn.__main__', raising=False)
    module = importlib.import_module('citylearn.__main__')
    assert callable(module.main)


class _AlwaysIncrease:
    def predict(self, x):
        return [1]


def test_occupant_set_points_with_hvac_off(monkeypatch):
    original = utilities.FileHandler.read_pickle
    monkeypatch.setattr(
        utilities.FileHandler, 'read_pickle',
        staticmethod(lambda path, **kwargs: _AlwaysIncrease() if str(path).endswith('.pkl') else original(path, **kwargs)),
    )
    schema = DataSet().get_schema('quebec_neighborhood_without_demand_response_set_points')
    names = list(schema['buildings'])

    for name in names[1:]:
        schema['buildings'][name]['include'] = False

    env = CityLearnEnv(schema, central_agent=True, simulation_start_time_step=0, simulation_end_time_step=40)
    env.reset()
    building = env.buildings[0]
    building.energy_simulation.hvac_mode[:] = 0

    for _ in range(30):
        env.step([[0.5] * env.action_space[0].shape[0]])

    assert building.simulate_dynamics
    assert not np.any(building.occupant.parameters.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta)
