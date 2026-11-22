"""Opt-in vehicle-to-building (V2B) backup during power outages.

By default a connected electric vehicle cannot discharge while the grid is down, as before. With
`power_outage.vehicle_to_building` (`Building.outage_vehicle_to_building`), a discharge request supplies the
islanded loads, up to the load that PV and the battery leave uncovered, so nothing is exported to the failed grid.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.physics_invariants import PhysicsInvariantError

MINUTE_DATASET = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'
STEP_HOURS = 0.25  # the dataset and the control step are 900 s


def _env(tmp_path: Path, vehicle_to_building, non_shiftable_load=2.0, solar_generation=0.0,
         cooling_demand=0.0, interface='flat', *, outage_signal=1.0, physics_version=None) -> CityLearnEnv:
    dataset = tmp_path / 'v2b'
    shutil.copytree(MINUTE_DATASET, dataset)
    frame = pd.read_csv(dataset / 'Building_1.csv')
    frame['power_outage'] = outage_signal
    frame['non_shiftable_load'] = non_shiftable_load  # kWh per 900 s row
    frame['solar_generation'] = solar_generation
    frame['cooling_demand'] = cooling_demand
    frame['heating_demand'] = 0.0
    frame['dhw_demand'] = 0.0
    frame.to_csv(dataset / 'Building_1.csv', index=False)

    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    building = schema['buildings']['Building_1']
    building['power_outage'] = {'simulate_power_outage': True}
    if vehicle_to_building is not None:
        building['power_outage']['vehicle_to_building'] = vehicle_to_building
    building['electrical_storage']['attributes']['initial_soc'] = 0.0
    # Absolute mode: the solar_generation column is the PV output in kWh per row.
    building['pv'] = {'type': 'citylearn.energy_model.PV', 'autosize': False,
                      'attributes': {'generation_mode': 'absolute', 'nominal_power': 20.0}}
    if cooling_demand:
        building['cooling_device'] = {'type': 'citylearn.energy_model.HeatPump', 'autosize': False,
                                      'attributes': {'nominal_power': 20.0, 'efficiency': 0.3,
                                                     'target_cooling_temperature': 8.0}}
    if interface == 'entity':
        # The charger capability features (`can_discharge`, `available_discharge_power_kw`) are in this bundle.
        schema.setdefault('observation_bundles', {})['entity_core_electrical'] = True
    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    if interface == 'entity':
        env = CityLearnEnv(str(path), interface='entity', episode_time_steps=4, random_seed=0,
                           physics_version=physics_version)
    else:
        env = CityLearnEnv(str(path), central_agent=True, episode_time_steps=4, random_seed=0,
                           physics_version=physics_version)
    env.reset(seed=0)
    return env


def _step(env: CityLearnEnv, ev_action: float):
    names = env.action_names[0]
    action = np.zeros(len(names), dtype='float32')
    action[names.index('electric_vehicle_storage_charger_1_1')] = ev_action
    env.step([action.tolist()])


def test_vehicle_to_building_is_off_by_default(tmp_path):
    env = _env(tmp_path, vehicle_to_building=None)
    try:
        building = env.buildings[0]
        assert building.outage_vehicle_to_building is False
        _step(env, -1.0)
        charger = building.electric_vehicle_chargers[0]
        assert charger.electricity_consumption[0] == 0.0
        # Without local supply the non-shiftable load is not served.
        assert building.non_shiftable_load_device.electricity_consumption[0] == 0.0
    finally:
        env.close()


@pytest.mark.parametrize('net_kwh', [-1.5, 1.5], ids=['export', 'import'])
@pytest.mark.parametrize('outage_signal', [1.0, 0.5, -0.5])
@pytest.mark.parametrize('physics_version', [1, 2])
def test_physics_checks_reject_grid_exchange_during_outage(tmp_path, monkeypatch, net_kwh, outage_signal,
                                                          physics_version):
    env = _env(tmp_path, vehicle_to_building=False, outage_signal=outage_signal, physics_version=physics_version)
    env.physics_invariant_checks = True

    try:
        building = env.buildings[0]
        assert building.power_outage
        _step(env, 0.0)
        assert building.net_electricity_consumption[0] == 0.0

        update_variables = building.update_variables

        def record_grid_exchange():
            update_variables()
            building._Building__net_electricity_consumption[building.time_step] = net_kwh

        monkeypatch.setattr(building, 'update_variables', record_grid_exchange)
        with pytest.raises(PhysicsInvariantError, match=r"Non-zero grid exchange during outage for 'Building_1' at t=1"):
            _step(env, 0.0)
    finally:
        env.close()


def test_vehicle_discharge_serves_the_islanded_load_and_exports_nothing(tmp_path):
    env = _env(tmp_path, vehicle_to_building=True)
    try:
        building = env.buildings[0]
        assert building.outage_vehicle_to_building is True
        charger = building.electric_vehicle_chargers[0]
        # The first step also re-clips the loads to local supply when the episode starts; the second does not.
        for t in (0, 1):
            _step(env, -1.0)
            # 7.2 kW requested; the 8 kW load (2 kWh per 900 s) takes all the charger can give.
            assert charger.electricity_consumption[t] < 0.0
            assert building.non_shiftable_load_device.electricity_consumption[t] == pytest.approx(
                -charger.electricity_consumption[t], rel=1.0e-5)
            assert building.net_electricity_consumption[t] == pytest.approx(0.0, abs=1.0e-5)
    finally:
        env.close()


def test_vehicle_discharge_is_limited_to_the_uncovered_load(tmp_path):
    # 0.5 kWh of load per step and 0.3 kWh of PV leave 0.2 kWh (0.8 kW) for the vehicle.
    env = _env(tmp_path, vehicle_to_building=True, non_shiftable_load=0.5, solar_generation=0.3)
    try:
        building = env.buildings[0]
        _step(env, -1.0)
        charger = building.electric_vehicle_chargers[0]
        pv = abs(float(building.solar_generation[0]))
        assert charger.electricity_consumption[0] == pytest.approx(-(0.5 - pv), abs=1.0e-5)
        assert building.non_shiftable_load_device.electricity_consumption[0] == pytest.approx(0.5, abs=1.0e-5)
        assert building.net_electricity_consumption[0] == pytest.approx(0.0, abs=1.0e-5)
    finally:
        env.close()


def test_vehicle_discharge_covers_the_heat_pump_after_the_load_is_known(tmp_path):
    env = _env(tmp_path, vehicle_to_building=True, non_shiftable_load=0.2, cooling_demand=1.0)
    try:
        building = env.buildings[0]
        _step(env, -1.0)
        charger = building.electric_vehicle_chargers[0]
        loads = (float(building.non_shiftable_load_device.electricity_consumption[0])
                 + float(building.cooling_device.electricity_consumption[0]))
        assert building.cooling_device.electricity_consumption[0] > 0.0
        assert building.energy_from_cooling_device[0] == pytest.approx(1.0, rel=1.0e-5)
        assert -charger.electricity_consumption[0] == pytest.approx(loads, rel=1.0e-5)
    finally:
        env.close()


def test_charging_during_an_outage_is_unchanged_by_the_option(tmp_path):
    for flag in (None, True):
        env = _env(tmp_path / str(flag), vehicle_to_building=flag, non_shiftable_load=0.0, solar_generation=0.5)
        try:
            building = env.buildings[0]
            _step(env, 1.0)
            # Charging is limited to local supply in both settings.
            assert building.electric_vehicle_chargers[0].electricity_consumption[0] == pytest.approx(0.5, abs=1.0e-5)
        finally:
            env.close()


@pytest.mark.parametrize('vehicle_to_building', [None, True])
def test_entity_charger_observations_report_vehicle_to_building_discharge(tmp_path, vehicle_to_building):
    # During an outage the entity charger table reported no discharge capacity even when the option lets the
    # vehicle supply the building, so a controller was told the vehicle could not discharge.
    env = _env(tmp_path, vehicle_to_building=vehicle_to_building, interface='entity')
    try:
        # `_env` has reset the env; another reset would move to the next episode, where the vehicle is away.
        observations = env._entity_service.observation_payload()
        assert env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle is not None
        features = list(env.entity_specs['tables']['charger']['features'])
        row = observations['tables']['charger'][0]
        can_discharge = float(row[features.index('can_discharge')])
        available_kw = float(row[features.index('available_discharge_power_kw')])
        charger = env.buildings[0].electric_vehicle_chargers[0]
        if vehicle_to_building:
            assert can_discharge == 1.0
            assert 0.0 < available_kw <= charger.max_discharging_power + 1.0e-6
        else:
            assert can_discharge == 0.0
            assert available_kw == 0.0
    finally:
        env.close()
