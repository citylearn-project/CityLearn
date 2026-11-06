"""Energy units when the control step differs from one hour or from the dataset resolution.

Hourly data run at a shorter control step uses ``time_step_ratio`` < 1: demand series are
dataset-resolution kWh while storage balances and device electricity are control-step kWh.
"""

import logging

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet

HOURLY_2021 = 'data/datasets/citylearn_challenge_2021/schema.json'


@pytest.fixture(autouse=True)
def _quiet_unit_conversion_notice():
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


def _hourly_2021(seconds):
    return CityLearnEnv(
        HOURLY_2021, central_agent=True, episode_time_steps=12, seconds_per_time_step=seconds,
        random_seed=0, simulation_start_time_step=4000,
    )


def test_autosized_device_power_does_not_depend_on_control_step():
    hourly = _hourly_2021(3600).buildings[0]
    quarter_hourly = _hourly_2021(900).buildings[0]

    assert quarter_hourly.time_step_ratio == pytest.approx(0.25)
    assert quarter_hourly.cooling_device.nominal_power == pytest.approx(hourly.cooling_device.nominal_power)
    assert quarter_hourly.dhw_device.nominal_power == pytest.approx(hourly.dhw_device.nominal_power)


def test_thermal_storage_charging_electricity_matches_delivered_heat():
    env = _hourly_2021(900)
    env.reset()
    building = env.buildings[0]
    names = env.action_names[0]
    index = [i for i, name in enumerate(names) if 'cooling_storage' in name][0]

    for _ in range(4):
        t = building.time_step
        values = np.zeros(len(names), dtype='float32')
        values[index] = 1.0
        env.step([values])
        cop = float(building.cooling_device.get_cop(building.weather.outdoor_dry_bulb_temperature[t], heating=False))
        demand = float(building.energy_simulation.cooling_demand[t]) * building.time_step_ratio
        stored = float(building.cooling_storage.energy_balance[t])
        electricity = float(building.cooling_device.electricity_consumption[t])

        assert stored > 0.0, 'scenario must charge the tank'
        assert electricity * cop == pytest.approx(demand + stored, rel=1.0e-4)


def test_thermal_storage_discharge_is_limited_by_control_step_demand():
    schema = DataSet().get_schema('citylearn_challenge_2023_phase_2_local_evaluation')
    schema['seconds_per_time_step'] = 1800.0  # hourly data, time_step_ratio = 0.5
    names = list(schema['buildings'])

    for name, building in schema['buildings'].items():
        building['type'] = 'citylearn.building.Building'
        building.pop('dynamics', None)
        building['power_outage'] = {'simulate_power_outage': False}
        building['dhw_storage']['attributes']['initial_soc'] = 0.5
        building['include'] = name == names[0]

    env = CityLearnEnv(schema, central_agent=False)
    env.reset()
    building = env.buildings[0]
    index = env.action_names[0].index('dhw_storage')
    assert building.time_step_ratio == pytest.approx(0.5)

    for action in (0.0, -1.0, -1.0):
        t = building.time_step
        values = [0.0] * len(env.action_names[0])
        values[index] = action
        env.step([values])

    demand = float(building.energy_simulation.dhw_demand[t]) * building.time_step_ratio
    delivered = -float(building.dhw_storage.energy_balance[t])
    assert 0.0 < delivered <= demand + 1.0e-6
    assert float(building.energy_from_dhw_device[t]) * building.time_step_ratio == pytest.approx(demand - delivered, abs=1.0e-6)


def test_heating_action_is_scaled_to_the_control_step_like_cooling():
    seconds = 900.0
    schema = DataSet().get_schema('vt_chittenden_county_neighborhood')
    names = list(schema['buildings'])

    for name in names[1:]:
        schema['buildings'][name]['include'] = False

    schema['buildings'][names[0]]['pv'] = {
        'type': 'citylearn.energy_model.PV', 'autosize': False, 'attributes': {'nominal_power': 2.0},
    }
    schema.update(
        seconds_per_time_step=seconds, dataset_seconds_per_time_step=seconds,
        simulation_start_time_step=0, simulation_end_time_step=99,
    )
    env = CityLearnEnv(schema, central_agent=True)
    env.reset()
    building = env.buildings[0]

    for _ in range(20):
        env.step([[0.0] * len(env.action_names[0])])

    assert building.simulate_dynamics
    t = building.time_step
    temperature = float(building.weather.outdoor_dry_bulb_temperature[t])
    building.update_heating_demand(0.5)
    expected = 0.5 * building.heating_device.nominal_power * seconds / 3600.0 \
        * float(building.heating_device.get_cop(temperature, heating=True))

    assert float(building.energy_simulation.heating_demand[t]) == pytest.approx(expected, rel=1.0e-5)
