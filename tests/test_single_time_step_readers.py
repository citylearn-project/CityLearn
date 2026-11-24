"""Single-time-step readers return exactly what the full-series properties they replace return.

Each case runs an episode and, after every step, compares the per-step readers used in the
step, observation and entity code (fast path) with indexing the full series properties
(reference path) in the same run: same type and same bits. The sub-hourly cases make
``ElectricDevice.electricity_consumption`` scale the series, the LSTM case covers dynamics
buildings, and the entity cases cover the entity electrical metrics.
"""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from private_access import entity_service, ops_service

ROOT = Path(__file__).resolve().parents[1]
STEPS = 24
CASES = {
    'ev_flat_60s': ('citylearn_challenge_2022_phase_all_plus_evs', dict(seconds_per_time_step=60)),
    'ev_entity_60s': ('citylearn_challenge_2022_phase_all_plus_evs', dict(seconds_per_time_step=60, interface='entity')),
    'three_phase_15s': ('citylearn_three_phase_electrical_service_demo_15s_parquet', {}),
    'lstm_2023': ('citylearn_challenge_2023_phase_2_local_evaluation', {}),
}


def _schema(dataset):
    """Dataset schema loading only the rows the episode reads (the 15 s dataset has 2.1 million per building)."""
    directory = ROOT/'data'/'datasets'/dataset
    schema = json.loads((directory/'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(directory)
    schema['simulation_end_time_step'] = int(schema.get('simulation_start_time_step') or 0) + STEPS + 10
    return schema


def _identical(fast, reference):
    return type(fast) is type(reference) and np.asarray(fast).tobytes() == np.asarray(reference).tobytes()


def _action(t, j, low, high):
    return min(max(0.8*math.sin(0.7*t + 1.3*j), float(low)), float(high))


def _actions(env, t):
    if env.interface == 'entity':
        return {'tables': {
            name: np.array([_action(t, j, lo, hi) for j, (lo, hi) in enumerate(zip(box.low.ravel(), box.high.ravel()))],
                           dtype='float32').reshape(box.shape)
            for name, box in env.action_space['tables'].spaces.items()
        }}
    return [np.array([_action(t, j, lo, hi) for j, (lo, hi) in enumerate(zip(box.low, box.high))], dtype='float32')
            for box in env.action_space]


def _check_building(building, mismatches):
    t = building.time_step
    devices = {
        'cooling_device': building.cooling_device,
        'heating_device': building.heating_device,
        'dhw_device': building.dhw_device,
        'non_shiftable_load_device': building.non_shiftable_load_device,
        'electrical_storage': building.electrical_storage,
        **{f'deferrable:{a.name}': a for a in building.deferrable_appliances or []},
        **{f'escalator:{e.name}': e for e in building.escalators or []},
    }

    for name, device in devices.items():
        series = device.electricity_consumption
        for i in range(t + 1):
            if not _identical(device.electricity_consumption_at(i), series[i]):
                mismatches.append((building.name, name, i))

    for storage in ('cooling', 'heating', 'dhw', 'electrical'):
        series = getattr(building, f'{storage}_storage_electricity_consumption')
        for i in range(t + 1):
            if not _identical(building.storage_electricity_consumption_at(storage, i), series[i]):
                mismatches.append((building.name, f'{storage}_storage_electricity_consumption', i))

    for storage in ('cooling', 'heating', 'dhw', 'electrical'):
        series = getattr(building, f'energy_from_{storage}_storage')
        for i in range(t + 1):
            fast = building._energy_from_storage(getattr(building, f'{storage}_storage'), slice(i, i + 1))[0]
            if not _identical(fast, series[i]):
                mismatches.append((building.name, f'energy_from_{storage}_storage', i))

    data = ops_service(building).get_observations_data(include_all=True)
    reference = {
        'cooling_electricity_consumption': building.cooling_electricity_consumption[t],
        'heating_electricity_consumption': building.heating_electricity_consumption[t],
        'dhw_electricity_consumption': building.dhw_electricity_consumption[t],
        **{
            f'{storage}_storage_electricity_consumption': getattr(building, f'{storage}_storage_electricity_consumption')[t]
            for storage in ('cooling', 'heating', 'dhw', 'electrical')
        },
    }
    for name, value in reference.items():
        if not _identical(data[name], value):
            mismatches.append((building.name, f'observation:{name}', t))


def _check_entity(env, mismatches):
    entity = entity_service(env)
    endogenous_t = max(int(env.time_step) - 1, 0)
    step_hours = entity._step_hours()
    for building in env.buildings:
        metrics = entity._build_electrical_building_metrics(
            building=building, endogenous_t=endogenous_t, control_t=int(env.time_step), step_hours=step_hours,
        )
        index = entity._safe_index
        bess = index(building.electrical_storage_electricity_consumption, endogenous_t)
        loads = [
            index(getattr(building, f'{name}_electricity_consumption'), endogenous_t)
            for name in ('cooling', 'heating', 'dhw', 'non_shiftable_load', 'deferrable_appliances', 'chargers')
        ]
        load = max(sum(loads), 0.0)
        for name, value in (('bess_energy_kwh_step', bess), ('load_energy_kwh_step', load)):
            if not _identical(metrics[name], value):
                mismatches.append((building.name, f'entity:{name}', endogenous_t))


@pytest.mark.parametrize('case', CASES)
def test_single_time_step_readers_match_full_series(case):
    dataset, kwargs = CASES[case]
    env = CityLearnEnv(_schema(dataset), central_agent=True, episode_time_steps=STEPS, random_seed=0,
                       time_step_ratio_mode='compress', **kwargs)
    mismatches = []
    try:
        env.reset(seed=0)
        t = 0
        while not env.terminated:
            env.step(_actions(env, t))
            for building in env.buildings:
                _check_building(building, mismatches)
            if env.interface == 'entity':
                _check_entity(env, mismatches)
            t += 1

        assert t == STEPS - 1
        assert mismatches == []
        # The episode exercised storage discharge, storage charging and device consumption.
        assert any(np.any(b.electrical_storage.energy_balance[:t] < 0.0) for b in env.buildings)
        assert any(np.any(b.electrical_storage.energy_balance[:t] > 0.0) for b in env.buildings)
    finally:
        env.close()


def test_archived_storage_consumption_overlay_matches_full_series():
    env = CityLearnEnv(
        _schema('citylearn_challenge_2022_phase_all_plus_evs'), central_agent=True, buildings=[0],
        episode_time_steps=STEPS, seconds_per_time_step=60, random_seed=0,
        time_step_ratio_mode='compress',
    )
    try:
        env.reset(seed=0)
        for t in range(10):
            env.step(_actions(env, t))
        building = env.buildings[0]
        building._archived_storage_electricity = np.linspace(-0.5, 0.5, 6)
        series = building.electrical_storage_electricity_consumption
        assert np.array_equal(series[:6], building._archived_storage_electricity.astype('float32'))
        for i in range(building.time_step + 1):
            assert _identical(building.storage_electricity_consumption_at('electrical', i), series[i]), i
    finally:
        env.close()
