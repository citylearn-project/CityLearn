"""Entity storage features during a power outage (issue #220).

The battery can discharge into the islanded building, up to its local load, but the entity storage table
reported `can_discharge = 0` and `available_discharge_power_kw = 0` during every outage.
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv

MINUTE_DATASET = Path(__file__).resolve().parent/'data'/'minute_ev_demo'


def _env(tmp_path: Path, outage: int) -> CityLearnEnv:
    dataset = tmp_path/'battery_outage'
    shutil.copytree(MINUTE_DATASET, dataset)
    frame = pd.read_csv(dataset/'Building_1.csv')
    frame['power_outage'] = outage
    frame['non_shiftable_load'] = 2.0  # kWh per 900 s row
    frame['solar_generation'] = 0.0
    frame.to_csv(dataset/'Building_1.csv', index=False)

    schema = json.loads((dataset/'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    building = schema['buildings']['Building_1']
    building['power_outage'] = {'simulate_power_outage': True}
    building['electrical_storage']['attributes']['initial_soc'] = 0.8
    schema.setdefault('observation_bundles', {})['entity_core_electrical'] = True
    path = dataset/'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    return CityLearnEnv(str(path), interface='entity', episode_time_steps=4, random_seed=0)


def _storage_features(env, observations):
    features = list(env.entity_specs['tables']['storage']['features'])
    row = observations['tables']['storage'][0]
    return float(row[features.index('can_discharge')]), float(row[features.index('available_discharge_power_kw')])


def test_battery_discharge_features_match_the_discharge_during_an_outage(tmp_path):
    env = _env(tmp_path, outage=1)
    try:
        observations, _ = env.reset(seed=0)
        can_discharge, available_kw = _storage_features(env, observations)
        assert env.buildings[0].power_outage
        assert can_discharge == 1.0
        assert available_kw > 0.0

        # A full discharge request delivers what the features announced, to the 2 kWh load.
        actions = {'tables': {key: np.zeros_like(value) for key, value in env.action_space.sample()['tables'].items()}}
        actions['tables']['building'][...] = -1.0
        env.step(actions)
        battery = env.buildings[0].electrical_storage
        delivered_kwh = -float(battery.electricity_consumption[0])
        assert delivered_kwh > 0.0
        assert delivered_kwh == pytest.approx(available_kw*0.25, rel=1.0e-5)
        assert float(env.buildings[0].net_electricity_consumption[0]) >= -1.0e-6
    finally:
        env.close()


def test_battery_discharge_features_without_an_outage_are_unchanged(tmp_path):
    env = _env(tmp_path, outage=0)
    try:
        observations, _ = env.reset(seed=0)
        can_discharge, available_kw = _storage_features(env, observations)
        assert can_discharge == 1.0
        assert available_kw > 0.0
    finally:
        env.close()
