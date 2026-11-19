"""`TimeSeriesData` keeps windowed views of its variables without changing what callers read."""
import copy
import pickle
from pathlib import Path

import numpy as np

from citylearn.citylearn import CityLearnEnv
from citylearn.data import EnergySimulation, TimeSeriesData

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json'


def _series(start=2, end=5, size=10):
    series = TimeSeriesData(start_time_step=start, end_time_step=end)
    series.load = np.arange(size, dtype='float64')
    return series


def _time_series_objects(env):
    for building in env.buildings:
        for name in ('energy_simulation', 'weather', 'pricing', 'carbon_intensity'):
            yield f'{building.name}.{name}', getattr(building, name)
        for charger in building.electric_vehicle_chargers or []:
            yield f'{building.name}.{charger.charger_id}', charger.charger_simulation


def _same_array(left, right):
    if left.dtype != right.dtype or left.shape != right.shape:
        return False
    if left.dtype.kind == 'O':
        return all(x == y or (x != x and y != y) for x, y in zip(left.tolist(), right.tolist()))
    return np.array_equal(left, right, equal_nan=left.dtype.kind == 'f')


def _variable_names(series):
    return [key[1:] for key in vars(series) if key.startswith('_') and not key.startswith('__')]


def test_reads_match_the_window_slice_and_writes_reach_the_full_variable():
    series = _series()
    assert np.array_equal(series.load, [2, 3, 4, 5])
    series.load[1] = 99.0
    assert series._load[3] == 99.0

    series.start_time_step = 0
    series.end_time_step = 2
    assert np.array_equal(series.load, [0, 1, 2])
    assert np.array_equal(series.__getattr__('load', start_time_step=3, end_time_step=4), [99, 4])

    series.load = np.zeros(4)
    assert np.array_equal(series.load, [0, 0, 0])

    # A name with a leading underscore is stored as `__<name>` and read through `__getattr__`.
    series._hidden = np.arange(5)
    assert np.array_equal(series._hidden, [0, 1, 2])


def test_every_environment_variable_reads_as_its_window_slice():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=24, random_seed=0)
    try:
        env.reset()
        checked = 0
        for label, series in _time_series_objects(env):
            for name in _variable_names(series):
                expected = series.__getattr__(name)
                actual = getattr(series, name)
                assert type(actual) is type(expected), (label, name)
                if isinstance(expected, np.ndarray):
                    assert _same_array(actual, expected), (label, name)
                    assert np.shares_memory(actual, series.__dict__[f'_{name}']), (label, name)
                else:
                    assert actual == expected, (label, name)
                checked += 1
        assert checked > 100
    finally:
        env.close()


def test_time_step_ratios_reads_the_window_slice():
    size = 12
    zeros = np.zeros(size, dtype='float32')
    ones = np.ones(size, dtype='int32')
    simulation = EnergySimulation(
        month=ones, hour=ones, day_type=ones, indoor_dry_bulb_temperature=zeros + 22.0,
        non_shiftable_load=zeros + 1.0, dhw_demand=zeros, cooling_demand=zeros, heating_demand=zeros,
        solar_generation=zeros, seconds_per_time_step=900, time_step_ratios=[0.5, 0.25],
    )
    ratios = simulation._time_step_ratios
    assert len(ratios) == 3 and simulation.time_step_ratios == ratios
    simulation.start_time_step = 1
    simulation.end_time_step = 8
    assert simulation.time_step_ratios == ratios[1:9] == ratios[1:]


def test_pickle_stores_each_variable_once_and_rebuilds_views():
    series = _series(size=100_000)
    payload = pickle.dumps(series)
    assert len(payload) < 1.05 * series._load.nbytes

    restored = pickle.loads(payload)
    assert np.array_equal(restored.load, series.load)
    assert np.shares_memory(restored.load, restored._load)
    restored.load[0] = -1.0
    assert restored._load[2] == -1.0


def test_copies_rebuild_views_on_their_own_variables():
    series = _series()
    deep = copy.deepcopy(series)
    deep.load[0] = 42.0
    assert deep._load[2] == 42.0
    assert series._load[2] == 2.0

    shallow = copy.copy(series)
    shallow.load[0] = 7.0
    assert series._load[2] == 7.0


def test_pickled_environment_contains_no_view_copies():
    env = CityLearnEnv(str(SCHEMA), central_agent=True, buildings=[0, 1], episode_time_steps=24, random_seed=0)
    try:
        env.reset()
        for _, series in _time_series_objects(env):
            full_variables = {key: value for key, value in vars(series).items() if key.startswith('_')}
            assert len(pickle.dumps(series)) < len(pickle.dumps(full_variables)) + 256

        restored = pickle.loads(pickle.dumps(env))
        for (_, before), (label, after) in zip(_time_series_objects(env), _time_series_objects(restored)):
            for name in _variable_names(after):
                value = getattr(after, name)
                if isinstance(value, np.ndarray):
                    assert _same_array(value, getattr(before, name)), (label, name)
                    assert np.shares_memory(value, after.__dict__[f'_{name}']), (label, name)
    finally:
        env.close()
