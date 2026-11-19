"""Power [kW] and energy [kWh] are kept apart at sub-hourly control steps, and related estimate fixes.

Each test reproduces a defect of CityLearn 3.5.0 and fails on it, except the 3600 s case of
`available_nominal_power` and the plain-building case of the set-point hold, which pin behaviour that must not
change. At 3600 s steps kW and kWh per step are numerically equal, so the unit defects only appear at
sub-hourly resolution or when the dataset and control steps differ (`time_step_ratio` != 1).
"""

from __future__ import annotations

import json
import shutil
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.energy_model import HeatPump

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'datasets'
MINUTE_DATASET = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'


def _bundled_schema(name: str, buildings: int = 1) -> dict:
    schema = json.loads((DATASETS / name / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASETS / name)
    for index, building in enumerate(schema['buildings'].values()):
        building['include'] = index < buildings
    return schema


def _minute_dataset(tmp_path: Path, name: str) -> tuple[Path, dict, pd.DataFrame]:
    dataset = tmp_path / name
    shutil.copytree(MINUTE_DATASET, dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    return dataset, schema, pd.read_csv(dataset / 'Building_1.csv')


def _write(dataset: Path, schema: dict, frame: pd.DataFrame) -> str:
    frame.to_csv(dataset / 'Building_1.csv', index=False)
    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema, indent=2), encoding='utf-8')
    return str(path)


def _action(env: CityLearnEnv, **values: float) -> list:
    names = env.action_names[0]
    action = np.zeros(len(names), dtype='float32')
    for name, value in values.items():
        action[names.index(name)] = value
    return [action.tolist()]


@pytest.mark.parametrize('seconds, expected_kw', [(900, 0.0), (3600, 7.5)])
def test_available_nominal_power_subtracts_power_not_step_energy(seconds, expected_kw):
    tracker = EpisodeTracker(0, 3)
    tracker.next_episode(4, False, False, 0)
    device = HeatPump(nominal_power=10.0, seconds_per_time_step=seconds, episode_tracker=tracker, random_seed=0)
    device.reset()
    # 2.5 kWh is the full 10 kW over 900 s, but only a quarter of it over 3600 s.
    device.update_electricity_consumption(2.5)
    assert device.available_nominal_power == pytest.approx(expected_kw)


def test_thermal_storage_charging_respects_device_nominal_power_at_900_s():
    schema = _bundled_schema('citylearn_challenge_2021')
    building = next(iter(schema['buildings'].values()))
    # A large tank makes the requested charge exceed what the devices can deliver in a 900 s step.
    for storage in ('cooling_storage', 'dhw_storage'):
        building[storage]['autosize'] = False
        building[storage]['attributes']['capacity'] = 2000.0

    env = CityLearnEnv(schema, central_agent=True, seconds_per_time_step=900, episode_time_steps=6,
                       simulation_start_time_step=4000, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        assert building.time_step_ratio == pytest.approx(0.25)
        action = _action(env, cooling_storage=1.0, dhw_storage=1.0)
        for _ in range(4):
            t = building.time_step
            env.step(action)
            assert building.cooling_storage.energy_balance[t] > 0.0
            for device in (building.cooling_device, building.dhw_device):
                # Control-step energy cannot exceed nominal power for 900 s.
                assert device.electricity_consumption[t] <= device.nominal_power * 0.25 + 1.0e-4
    finally:
        env.close()


@pytest.mark.parametrize('load', ['non_shiftable_load', 'cooling_device'])
def test_islanded_supply_limits_loads_in_control_step_energy(tmp_path, load):
    dataset, schema, frame = _minute_dataset(tmp_path, 'outage_hourly_data')
    # Hourly rows at a 900 s control step: `time_step_ratio` is 0.25.
    frame = frame.drop(columns=['minutes'])
    frame['hour'] = np.arange(len(frame)) % 24
    frame['power_outage'] = 1
    frame['solar_generation'] = 4.0  # absolute mode: 4 kWh per hour, 1 kWh per 900 s step
    frame['non_shiftable_load'] = 8.0 if load == 'non_shiftable_load' else 0.0
    frame['cooling_demand'] = 400.0 if load == 'cooling_device' else 0.0
    frame['heating_demand'] = 0.0
    frame['dhw_demand'] = 0.0
    building = schema['buildings']['Building_1']
    building['power_outage'] = {'simulate_power_outage': True}
    building['chargers'] = {}
    building['pv'] = {'type': 'citylearn.energy_model.PV', 'autosize': False,
                      'attributes': {'generation_mode': 'absolute', 'nominal_power': 20.0}}
    building['cooling_device'] = {'type': 'citylearn.energy_model.HeatPump', 'autosize': False,
                                  'attributes': {'nominal_power': 50.0, 'efficiency': 0.3,
                                                 'target_cooling_temperature': 8.0}}
    schema.pop('dataset_seconds_per_time_step', None)

    env = CityLearnEnv(_write(dataset, schema, frame), central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        assert building.time_step_ratio == pytest.approx(0.25)
        env.step(_action(env))
        device = building.non_shiftable_load_device if load == 'non_shiftable_load' else building.cooling_device
        # The 1 kWh of PV in the step is all available to the load, not a quarter of it.
        assert device.electricity_consumption[0] == pytest.approx(1.0, abs=1.0e-5)
        assert building.net_electricity_consumption[0] == pytest.approx(0.0, abs=1.0e-5)
    finally:
        env.close()


def test_demand_observation_converts_storage_discharge_to_dataset_resolution():
    schema = _bundled_schema('citylearn_challenge_2021')
    # A small full tank covers only part of the demand, so the device serves the rest.
    dhw_storage = next(iter(schema['buildings'].values()))['dhw_storage']
    dhw_storage['autosize'] = False
    dhw_storage['attributes'].update(capacity=1.0, initial_soc=1.0)
    env = CityLearnEnv(schema, central_agent=True, seconds_per_time_step=900, episode_time_steps=6,
                       simulation_start_time_step=4000, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        assert building.time_step_ratio == pytest.approx(0.25)
        t = building.time_step
        env.step(_action(env, dhw_storage=-1.0))
        assert building.dhw_storage.energy_balance[t] < 0.0
        assert building.energy_from_dhw_device[t] > 0.0
        observed = building._ops_service.get_observations_data(observation_names=['dhw_demand'])['dhw_demand']
        # Device and tank together serve the dataset demand; both terms are dataset-resolution kWh.
        assert observed == pytest.approx(float(building.energy_simulation.dhw_demand[t]), rel=1.0e-5)
    finally:
        env.close()


def test_base_power_estimate_does_not_subtract_thermal_discharge_twice():
    schema = _bundled_schema('citylearn_challenge_2021')
    next(iter(schema['buildings'].values()))['cooling_storage']['attributes']['initial_soc'] = 0.8
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=6, simulation_start_time_step=4000,
                       random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        t = building.time_step
        env.step(_action(env, cooling_storage=-1.0))
        assert building.cooling_storage.energy_balance[t] < 0.0
        # Hourly steps: kWh per step equals kW.
        expected_kw = sum(float(device.electricity_consumption[t]) for device in (
            building.cooling_device, building.heating_device, building.dhw_device, building.non_shiftable_load_device,
        )) + float(building.solar_generation[t])
        estimate_kw, _ = building._ops_service._estimate_base_power_at_step(t)
        assert estimate_kw == pytest.approx(expected_kw, abs=1.0e-4)
    finally:
        env.close()


def test_escalator_request_counts_against_electrical_service_import_limit(tmp_path):
    dataset, schema, frame = _minute_dataset(tmp_path, 'escalator_service')
    for column in ('non_shiftable_load', 'solar_generation', 'cooling_demand', 'heating_demand', 'dhw_demand'):
        frame[column] = 0.0
    steps = len(frame)
    pd.DataFrame({
        'time_step': range(steps),
        'passengers_from_trains_15min': [10.0] * steps,
        'background_pedestrians_15min': [2.0] * steps,
        'passengers_expected_15min': [12.0] * steps,
        'people_detected': [1.0] * steps,
        'arriving_trains': [1.0] * steps,
        'departing_trains': [0.0] * steps,
        'minutes_to_next_train': [5.0] * steps,
        'available': [1.0] * steps,
    }).to_csv(dataset / 'escalator.csv', index=False)
    schema['actions']['escalator'] = {'active': True}
    building = schema['buildings']['Building_1']
    building['escalators'] = {'esc_1': {'simulation': 'escalator.csv', 'attributes': {
        'standby_power': 0.5, 'slow_power': 2.0, 'normal_power': 4.0}}}
    building['electrical_service'] = {'mode': 'single_phase', 'limits': {'total': {'import_kw': 6.0, 'export_kw': 10.0}}}

    env = CityLearnEnv(_write(dataset, schema, frame), central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        env.step(_action(env, escalator_esc_1=1.0, electric_vehicle_storage_charger_1_1=1.0))
        escalator_kw = float(building.escalators[0].electricity_consumption[0]) / 0.25
        charger_kw = float(building.electric_vehicle_chargers[0].electricity_consumption[0]) / 0.25
        assert escalator_kw == pytest.approx(4.0)
        # 6 kW import limit less the 4 kW escalator leaves 2 kW for the 7.2 kW charge request.
        assert charger_kw == pytest.approx(2.0, abs=1.0e-4)
    finally:
        env.close()


def test_occupant_set_point_hold_is_read_from_the_schema():
    schema = _bundled_schema('quebec_neighborhood_without_demand_response_set_points')
    building_schema = next(iter(schema['buildings'].values()))
    assert building_schema['set_point_hold_time_steps'] == 4
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        assert env.buildings[0].set_point_hold_time_steps == 4
    finally:
        env.close()


def test_set_point_hold_is_not_passed_to_buildings_without_occupant_hold():
    schema = _bundled_schema('citylearn_challenge_2021')
    next(iter(schema['buildings'].values()))['set_point_hold_time_steps'] = 4
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        assert not hasattr(env.buildings[0], 'set_point_hold_time_steps')
    finally:
        env.close()


def test_normalized_observations_without_periodic_encoding():
    env = CityLearnEnv(_bundled_schema('citylearn_challenge_2021'), central_agent=True, episode_time_steps=4,
                       random_seed=0)
    try:
        env.reset(seed=0)
        observations = env.buildings[0].observations(normalize=True, periodic_normalization=False)
        assert 'month' in observations and 'month_cos' not in observations
        assert all(-1.0e-6 <= float(value) <= 1.0 + 1.0e-6 for value in observations.values())
    finally:
        env.close()


def test_clip_reasons_name_only_the_charger_phase_and_direction(tmp_path):
    dataset, schema, frame = _minute_dataset(tmp_path, 'three_phase_reasons')
    frame['non_shiftable_load'] = 0.0
    frame['solar_generation'] = 0.0
    charger = pd.read_csv(dataset / 'charger_1_1.csv')
    charger['electric_vehicle_charger_state'] = 1
    charger.to_csv(dataset / 'charger_1_1.csv', index=False)
    charger['electric_vehicle_id'] = 'Electric_Vehicle_2'
    charger.to_csv(dataset / 'charger_1_2.csv', index=False)
    schema['interface'] = 'entity'
    schema['observation_bundles'] = {'entity_action_feedback': {'active': True}}
    schema['electric_vehicles_def']['Electric_Vehicle_2'] = json.loads(
        json.dumps(schema['electric_vehicles_def']['Electric_Vehicle_1']))
    building = schema['buildings']['Building_1']
    building['chargers']['charger_1_1']['attributes']['phase_connection'] = 'L1'
    building['chargers']['charger_1_2'] = json.loads(json.dumps(building['chargers']['charger_1_1']))
    building['chargers']['charger_1_2']['charger_simulation'] = 'charger_1_2.csv'
    building['chargers']['charger_1_2']['attributes']['phase_connection'] = 'L2'
    building['electrical_service'] = {
        'mode': 'three_phase',
        'default_split': 'balanced',
        'limits': {
            'total': {'import_kw': 4.0, 'export_kw': 10.0},
            'per_phase': {
                'L1': {'import_kw': 2.0, 'export_kw': 5.0},
                'L2': {'import_kw': 10.0, 'export_kw': 5.0},
                'L3': {'import_kw': 10.0, 'export_kw': 5.0},
            },
        },
    }

    env = CityLearnEnv(_write(dataset, schema, frame), episode_time_steps=4, random_seed=0,
                       export_kpis_on_episode_end=False)
    try:
        env.reset(seed=0)
        tables = {name: np.zeros(space.shape, dtype='float32') for name, space in env.action_space['tables'].items()}
        # L1 reaches its 2 kW phase limit; L2 is limited by the 4 kW total, far below its 10 kW phase limit.
        tables['charger'][:, 0] = 1.0
        observations, *_ = env.step({'tables': tables})
        features = env.entity_specs['tables']['charger']['features']
        ids = env.entity_specs['tables']['charger']['ids']
        row = lambda charger_id, feature: observations['tables']['charger'][ids.index(f'Building_1/{charger_id}'),
                                                                           features.index(feature)]
        assert row('charger_1_1', 'clip_reason_phase_headroom') == pytest.approx(1.0)
        assert row('charger_1_2', 'clip_reason_building_headroom') == pytest.approx(1.0)
        assert row('charger_1_2', 'clip_reason_phase_headroom') == pytest.approx(0.0)
        assert row('charger_1_2', 'clip_reason_export_headroom') == pytest.approx(0.0)
    finally:
        env.close()


def test_undersized_device_on_native_subhourly_data_is_clipped_with_one_warning_per_episode(tmp_path):
    dataset, schema, frame = _minute_dataset(tmp_path, 'undersized_native_900s')
    frame['cooling_demand'] = 30.0  # kWh per 900 s row: 120 kW of cooling
    frame['heating_demand'] = 0.0
    frame['dhw_demand'] = 0.0
    building = schema['buildings']['Building_1']
    building['chargers'] = {}
    building['cooling_device'] = {'type': 'citylearn.energy_model.HeatPump', 'autosize': False,
                                  'attributes': {'nominal_power': 2.0, 'efficiency': 0.3,
                                                 'target_cooling_temperature': 8.0}}
    env = CityLearnEnv(_write(dataset, schema, frame), central_agent=True, episode_time_steps=4, random_seed=0,
                       export_kpis_on_episode_end=False)
    try:
        for _ in range(2):
            env.reset(seed=0)
            building = env.buildings[0]
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                while not env.terminated:
                    env.step(_action(env))
            messages = [str(w.message) for w in caught if issubclass(w.category, RuntimeWarning)
                        and 'cooling_device cannot meet' in str(w.message)]
            assert len(messages) == 1

            steps = env.time_step
            served = building.energy_from_cooling_device[:steps]
            # Output is clipped to nominal power over 900 s: 2 kW x COP x 0.25 h.
            cop = building.cooling_device.get_cop(building.weather.outdoor_dry_bulb_temperature[:steps], heating=False)
            np.testing.assert_allclose(served, 2.0 * cop * 0.25, rtol=1.0e-5)
            np.testing.assert_allclose(building.cooling_device.electricity_consumption[:steps], 0.5, rtol=1.0e-5)
            audit = env.get_kpi_family_audit()['buildings']['Building_1']
            assert audit['unserved_service_energy_kwh'] == pytest.approx(float(np.sum(30.0 - served)), rel=1.0e-4)
    finally:
        env.close()
