"""Observation values, encodings and limits that agents rely on."""

import logging

import numpy as np
import pytest

import citylearn.utilities as utilities
from citylearn.building import Building
from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet
from citylearn.preprocessing import PeriodicNormalization


def test_net_consumption_stays_within_limits_with_evs_and_deferrable_loads():
    logging.disable(logging.WARNING)

    try:
        env = CityLearnEnv('citylearn_challenge_2022_phase_all_plus_evs', central_agent=False, random_seed=0)
    finally:
        logging.disable(logging.NOTSET)

    env.reset()
    rng = np.random.default_rng(0)
    limits = [b.estimate_observation_space_limits(include_all=True, periodic_normalization=False) for b in env.buildings]
    worst = 0.0

    for _ in range(1000):
        env.step([rng.uniform(space.low, space.high).tolist() for space in env.action_space])

        for building, (low, high) in zip(env.buildings, limits):
            value = float(building.net_electricity_consumption[building.time_step - 1])
            worst = max(worst, value - high['net_electricity_consumption'], low['net_electricity_consumption'] - value)

    assert worst <= 1.0e-4


@pytest.mark.parametrize(('values', 'expected'), [(range(0, 60), 60), (range(1, 25), 24), (range(1, 13), 12), (range(1, 8), 7)])
def test_periodic_cycle_length(values, expected):
    assert Building.periodic_cycle_length(values) == expected


def test_minute_encoding_distinguishes_last_minute_and_matches_space_limits():
    cycle = Building.periodic_cycle_length(Building.get_periodic_observation_metadata()['minutes'])
    first, last = PeriodicNormalization(cycle) * 0, PeriodicNormalization(cycle) * 59
    assert not np.allclose(first, last)

    env = CityLearnEnv('citylearn_three_phase_electrical_service_demo_15s_parquet', central_agent=False)
    env.reset()
    building = env.buildings[0]
    minutes = float(building.energy_simulation.minutes[building.time_step])
    observations = building.observations(include_all=True, normalize=False, periodic_normalization=True)

    assert observations['minutes_sin'] == pytest.approx(np.sin(2.0 * np.pi * minutes / 60.0), abs=1.0e-6)
    assert observations['minutes_cos'] == pytest.approx(np.cos(2.0 * np.pi * minutes / 60.0), abs=1.0e-6)


class _NoInteraction:
    def predict(self, x):
        return [0]


def test_occupant_set_point_delta_observation_is_delivered(monkeypatch):
    original = utilities.FileHandler.read_pickle
    monkeypatch.setattr(
        utilities.FileHandler, 'read_pickle',
        staticmethod(lambda path, **kwargs: _NoInteraction() if str(path).endswith('.pkl') else original(path, **kwargs)),
    )
    key = 'occupant_interaction_indoor_dry_bulb_temperature_set_point_delta'
    schema = DataSet().get_schema('quebec_neighborhood_without_demand_response_set_points')
    schema['observations'][key]['active'] = True
    names = list(schema['buildings'])

    for name in names[1:]:
        schema['buildings'][name]['include'] = False

    env = CityLearnEnv(schema, central_agent=False)
    observations, _ = env.reset()
    building = env.buildings[0]
    live = building.occupant.parameters.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta.copy()
    low, high = building.estimate_observation_space_limits(include_all=False)
    delta = max(abs(value) for value in building.occupant.delta_output_map.values())

    assert key in building.observations()
    assert len(observations[0]) == len(building.active_observations) == building.observation_space.shape[0]
    assert (low[key], high[key]) == pytest.approx((-delta, delta))
    # Estimating limits must not write into the occupant's live series.
    np.testing.assert_array_equal(
        building.occupant.parameters.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta, live,
    )


def test_partial_load_baseline_uses_heating_device_and_per_step_temperature():
    schema = DataSet().get_schema('vt_chittenden_county_neighborhood')
    names = list(schema['buildings'])

    for name in names[1:]:
        schema['buildings'][name]['include'] = False

    schema['buildings'][names[0]]['pv'] = {
        'type': 'citylearn.energy_model.PV', 'autosize': False, 'attributes': {'nominal_power': 2.0},
    }
    schema.update(simulation_start_time_step=0, simulation_end_time_step=199, episode_time_steps=None)
    env = CityLearnEnv(schema, central_agent=True)
    env.reset()
    building = env.buildings[0]
    index = env.action_names[0].index('cooling_or_heating_device')

    for _ in range(150):
        values = [0.0] * len(env.action_names[0])
        values[index] = 0.3
        env.step([values])

    temperature = building.weather.outdoor_dry_bulb_temperature[0:building.time_step + 1]
    heating_difference = building.heating_demand_without_partial_load - building.heating_demand
    cooling_difference = building.cooling_demand_without_partial_load - building.cooling_demand
    assert np.abs(heating_difference).sum() > 0.0, 'scenario must use partial heating'
    expected = building.net_electricity_consumption_without_storage \
        + building.cooling_device.get_input_power(cooling_difference, temperature, heating=False) \
        + building.heating_device.get_input_power(heating_difference, temperature, heating=True)

    np.testing.assert_allclose(building.net_electricity_consumption_without_storage_and_partial_load, expected, rtol=1.0e-6)
