"""Regression tests for charger state parsing, InventoryBattery EVs and the entity SOC-limit metrics."""

import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.data import ChargerSimulation

MINUTE_EV_DEMO = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'


def _dataset(tmp_path: Path, inventory_battery: dict = None, entity_core: bool = False) -> Path:
    dataset = tmp_path / 'minute_ev_demo'
    shutil.copytree(MINUTE_EV_DEMO, dataset)
    schema_path = dataset / 'schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)

    if entity_core:
        schema['observation_bundles'] = {'entity_core_electrical': {'active': True}}

    if inventory_battery is not None:
        for ev in schema['electric_vehicles_def'].values():
            ev['battery']['type'] = 'citylearn.community_dataset.InventoryBattery'
            ev['battery']['attributes'] = dict(inventory_battery)

    schema_path.write_text(json.dumps(schema), encoding='utf-8')
    return schema_path


def _charger_simulation(states):
    n = len(states)
    return ChargerSimulation(states, ['ev']*n, [-1]*n, [-1.0]*n, [-1]*n, [-1.0]*n)


@pytest.mark.parametrize('states, expected', [
    ([1.0, 2.0, np.nan, 3.0], [1.0, 2.0, np.nan, 3.0]),
    (['1', '2.0', '', 'x', '-1', '2.5'], [1.0, 2.0, np.nan, np.nan, np.nan, np.nan]),
], ids=['float_column', 'strings'])
def test_charger_states_are_parsed_as_numbers(states, expected):
    np.testing.assert_array_equal(_charger_simulation(states).electric_vehicle_charger_state, expected)


def test_charger_file_with_a_blank_state_keeps_the_other_states(tmp_path):
    schema_path = _dataset(tmp_path)
    charger_path = schema_path.parent / 'charger_1_1.csv'
    charger = pd.read_csv(charger_path)
    charger['electric_vehicle_charger_state'] = charger['electric_vehicle_charger_state'].astype(object)
    charger.loc[len(charger) - 1, 'electric_vehicle_charger_state'] = ''
    charger.to_csv(charger_path, index=False)
    env = CityLearnEnv(str(schema_path), central_agent=True)

    try:
        env.reset()
        charger = env.buildings[0].electric_vehicle_chargers[0]
        states = charger.charger_simulation.electric_vehicle_charger_state

        # The blank made pandas read 1.0, 2.0, ..., which used to become NaN everywhere: no EV ever connected.
        np.testing.assert_array_equal(states[:7], [1, 1, 1, 1, 3, 3, 2])
        assert np.isnan(states[7])
        assert charger.connected_electric_vehicle is not None
    finally:
        env.close()


def test_inventory_battery_ev_without_nominal_power_loads(tmp_path):
    schema_path = _dataset(tmp_path, inventory_battery={
        'capacity': 20.0, 'initial_soc': 0.4, 'max_charge_kw': 11.0, 'max_discharge_kw': 7.5,
    })
    env = CityLearnEnv(str(schema_path), central_agent=True)

    try:
        assert env.electric_vehicles[0].battery.nominal_power == 11.0
    finally:
        env.close()


def test_plain_battery_ev_still_requires_nominal_power(tmp_path):
    schema_path = _dataset(tmp_path)
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    del schema['electric_vehicles_def']['Electric_Vehicle_1']['battery']['attributes']['nominal_power']
    schema_path.write_text(json.dumps(schema), encoding='utf-8')

    with pytest.raises(KeyError, match='nominal_power'):
        CityLearnEnv(str(schema_path), central_agent=True)


@pytest.mark.parametrize('random_seed', range(8))
def test_random_initial_soc_is_drawn_within_the_declared_soc_limits(tmp_path, random_seed):
    schema_path = _dataset(tmp_path, inventory_battery={
        'capacity': 20.0, 'max_charge_kw': 11.0, 'max_discharge_kw': 7.5, 'min_soc': 0.25, 'max_soc': 0.85,
    })
    # InventoryBattery used to reject draws from [0, 1] outside its limits.
    env = CityLearnEnv(str(schema_path), central_agent=True, random_seed=random_seed)

    try:
        seed = int(hashlib.md5(f'{random_seed}:Electric_Vehicle_1:initial_soc'.encode('utf-8')).hexdigest()[:8], 16)
        expected = np.random.RandomState(seed).uniform(0.25, 0.85)
        assert env.electric_vehicles[0].battery.initial_soc == pytest.approx(expected)
    finally:
        env.close()


def test_random_initial_soc_without_declared_limits_is_unchanged(tmp_path):
    schema_path = _dataset(tmp_path)
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    del schema['electric_vehicles_def']['Electric_Vehicle_1']['battery']['attributes']['initial_soc']
    schema_path.write_text(json.dumps(schema), encoding='utf-8')
    env = CityLearnEnv(str(schema_path), central_agent=True, random_seed=3)

    try:
        seed = int(hashlib.md5('3:Electric_Vehicle_1:initial_soc'.encode('utf-8')).hexdigest()[:8], 16)
        assert env.electric_vehicles[0].battery.initial_soc == np.random.RandomState(seed).uniform(0.0, 1.0)
    finally:
        env.close()


def test_entity_flexibility_metrics_stop_at_max_soc(tmp_path):
    schema_path = _dataset(tmp_path, entity_core=True, inventory_battery={
        'capacity': 20.0, 'initial_soc': 0.4, 'max_charge_kw': 11.0, 'max_discharge_kw': 7.5,
        'min_soc': 0.1, 'max_soc': 0.8,
    })
    env = CityLearnEnv(str(schema_path), interface='entity', central_agent=True)

    try:
        observations, _ = env.reset()
        service = env._entity_service
        ev = dict(zip(service._ev_features, observations['tables']['ev'][0]))
        charger = dict(zip(service._charger_features, observations['tables']['charger'][0]))
        building = dict(zip(service._building_features, observations['tables']['building'][0]))
        storage = dict(zip(service._storage_features, observations['tables']['storage'][0]))

        # The EV can take (0.8 - 0.4)*20 kWh, not (1 - 0.4)*20 kWh.
        assert ev['soc_max_ratio'] == pytest.approx(0.8)
        assert ev['energy_to_full_kwh'] == pytest.approx(8.0)
        assert charger['connected_ev_energy_to_full_kwh'] == pytest.approx(8.0)
        assert building['flexible_energy_to_full_kwh'] == pytest.approx(8.0 + storage['energy_to_full_kwh'])
    finally:
        env.close()
