"""Electric vehicles draw unspecified battery parameters independently and reproducibly."""

import json
from pathlib import Path

import numpy as np

from citylearn.citylearn import CityLearnEnv

DATASET = Path(__file__).resolve().parents[1]/'data'/'datasets'/'citylearn_challenge_2022_phase_all_plus_evs'


def _schema(**battery_attributes):
    schema = json.loads((DATASET/'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASET)
    for definition in schema['electric_vehicles_def'].values():
        definition['battery'].setdefault('attributes', {}).update(battery_attributes)
    return schema


def _battery_parameters(env):
    return {
        ev.name: (
            float(ev.battery.efficiency),
            float(ev.battery.capacity_loss_coefficient),
            tuple(np.round(np.asarray(ev.battery.power_efficiency_curve, dtype=float).ravel(), 12)),
        )
        for ev in env.electric_vehicles
    }


def test_each_electric_vehicle_draws_its_own_battery_parameters():
    parameters = _battery_parameters(CityLearnEnv(_schema(), episode_time_steps=2, random_seed=0))

    assert len(parameters) > 1
    # Previously every EV shared the schema seed, so all drew the same values.
    assert len(set(parameters.values())) == len(parameters)


def test_battery_parameters_are_reproducible_and_follow_the_environment_seed():
    first = _battery_parameters(CityLearnEnv(_schema(), episode_time_steps=2, random_seed=0))
    second = _battery_parameters(CityLearnEnv(_schema(), episode_time_steps=2, random_seed=0))
    other_seed = _battery_parameters(CityLearnEnv(_schema(), episode_time_steps=2, random_seed=1))

    assert first == second
    assert first != other_seed


def test_explicit_battery_random_seed_is_honoured():
    parameters = _battery_parameters(CityLearnEnv(_schema(random_seed=123), episode_time_steps=2, random_seed=0))

    assert len(set(parameters.values())) == 1
