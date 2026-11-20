"""The performance changes of #257 must give the same results as the code they replaced, bit for bit."""

import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from citylearn.internal import kpi_equipment, temporal
from citylearn.wrappers import DiscreteCombinations

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all'


def _reference_district_pv_metrics(kpi, buildings, building_windows, *, final_t):
    """The (step x building) loop that compute_district_pv_metrics replaced, kept verbatim."""

    series_by_building = []
    for building in buildings:
        t_start, t_end = building_windows.get(building.name, (0, -1))
        if t_end < t_start:
            continue

        series_by_building.append((
            building.name, int(t_start), int(t_end),
            kpi._energy_values(building, building.solar_generation),
            kpi._energy_values(building, building.net_electricity_consumption),
            kpi._energy_values(building, getattr(building, 'pv_curtailment', np.zeros_like(building.solar_generation))),
        ))

    pv_generation_total = 0.0
    pv_export_total = 0.0
    pv_curtailment_total = 0.0
    for t in range(int(max(final_t, 0)) + 1):
        generation_t = 0.0
        district_net_t = 0.0
        curtailment_t = 0.0
        for _, t_start, t_end, solar, net, curtailed in series_by_building:
            if not (t_start <= t <= t_end):
                continue

            solar_value = kpi._to_scalar(solar[t] if t < len(solar) else np.nan, 0.0)
            net_value = kpi._to_scalar(net[t] if t < len(net) else np.nan, 0.0)
            curtailment_t += float(curtailed[t]) if t < len(curtailed) else 0.0
            generation_t += max(-solar_value, 0.0)
            district_net_t += net_value

        pv_generation_total += generation_t
        pv_curtailment_total += curtailment_t
        pv_export_total += min(max(generation_t - curtailment_t, 0.0), max(-district_net_t, 0.0))

    ratio = None if pv_generation_total <= 0.0 else (pv_generation_total - pv_export_total - pv_curtailment_total) / pv_generation_total
    return {
        'pv_curtailment_total_kwh': float(pv_curtailment_total),
        'pv_generation_total_kwh': float(pv_generation_total),
        'pv_export_total_kwh': float(pv_export_total),
        'pv_self_consumption_ratio': ratio,
    }


class _KPI:
    @staticmethod
    def _to_scalar(value, default=0.0):
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)
        return scalar if np.isfinite(scalar) else float(default)

    @staticmethod
    def _energy_values(building, values):
        return np.asarray(values, dtype='float64').copy()


def _series(rng, length, *, nan=False):
    values = rng.normal(0.0, 3.0, length) * rng.integers(0, 2, length)
    values[rng.random(length) < 0.1] = -0.0
    if nan:
        values[rng.random(length) < 0.05] = np.nan
        values[rng.random(length) < 0.02] = np.inf
    return values


def _bits(metrics):
    return {k: (None if v is None else np.float64(v).tobytes()) for k, v in metrics.items()}


@pytest.mark.parametrize('seed', range(25))
def test_district_pv_metrics_match_the_step_loop_bit_for_bit(seed):
    rng = np.random.default_rng(seed)
    final_t = int(rng.integers(-1, 120))
    buildings, windows = [], {}

    for i in range(int(rng.integers(0, 7))):
        name = f'Building_{i}'
        length = int(rng.integers(0, 140))
        buildings.append(SimpleNamespace(
            name=name,
            solar_generation=-np.abs(_series(rng, length, nan=True)),
            net_electricity_consumption=_series(rng, length, nan=True),
            pv_curtailment=np.abs(_series(rng, int(rng.integers(0, 140)), nan=seed % 3 == 0)),
        ))
        start = int(rng.integers(-5, 130))
        windows[name] = (start, start + int(rng.integers(-3, 130)))

    expected = _reference_district_pv_metrics(_KPI, buildings, windows, final_t=final_t)
    actual = kpi_equipment.compute_district_pv_metrics(_KPI, buildings, windows, final_t=final_t)
    assert _bits(actual) == _bits(expected)


def test_district_pv_totals_keep_positive_zero_like_the_step_loop():
    building = SimpleNamespace(
        name='b', solar_generation=np.array([-0.0, 0.0]), net_electricity_consumption=np.array([0.0, -0.0]),
        pv_curtailment=np.array([-0.0, -0.0]),
    )
    actual = kpi_equipment.compute_district_pv_metrics(_KPI, [building], {'b': (0, 1)}, final_t=1)
    expected = _reference_district_pv_metrics(_KPI, [building], {'b': (0, 1)}, final_t=1)
    assert _bits(actual) == _bits(expected)


@pytest.mark.parametrize('sizes', [[], [1], [3], [2, 3], [4, 1, 5], [3, 2, 2, 3]])
def test_discrete_combinations_follow_itertools_product(sizes):
    reference = list(itertools.product(*[list(range(n)) for n in sizes]))
    combinations = DiscreteCombinations(sizes)

    assert len(combinations) == len(reference)
    assert list(combinations) == reference
    assert [combinations[i] for i in range(len(reference))] == reference
    assert all(type(v) is int for c in (combinations[i] for i in range(len(reference))) for v in c)
    assert [combinations.index(c) for c in reference] == list(range(len(reference)))
    assert combinations[-1] == reference[-1]

    with pytest.raises(IndexError):
        combinations[len(reference)]


def test_discrete_combinations_index_matches_list_membership():
    reference = list(itertools.product(range(3), range(4)))
    combinations = DiscreteCombinations([3, 4])

    for value in [(np.int64(2), np.int64(3)), (1.0, 2), (True, 0)]:
        assert combinations.index(value) == reference.index(value)

    for value in [(3, 0), (-1, 0), (0, 4), (0.5, 1), (0,), (0, 1, 2)]:
        with pytest.raises(ValueError):
            reference.index(value)
        with pytest.raises(ValueError):
            combinations.index(value)

    assert (2, 3) in combinations and (2, 4) not in combinations


def test_large_state_product_is_not_materialized():
    combinations = DiscreteCombinations([10] * 10)

    assert len(combinations) == 10**10
    assert combinations.index((9,) * 10) == 10**10 - 1
    assert combinations[123456789] == (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)


def test_input_digest_cache_reuses_unchanged_files_and_rehashes_changed_ones(tmp_path, monkeypatch):
    path = tmp_path / 'input.csv'
    path.write_text('a,b\n1,2\n')
    old = time.time_ns() - 10_000_000_000
    os.utime(path, ns=(old, old))
    calls = []
    original = temporal.sha256
    monkeypatch.setattr(temporal, 'sha256', lambda p: calls.append(p) or original(p))
    monkeypatch.setattr(temporal, '_DIGEST_CACHE', {})
    # os.utime sets the change time to now, which the age rule would treat as a fresh write.
    monkeypatch.setattr(temporal, '_DIGEST_CACHE_MIN_AGE_NS', 0)

    first = temporal.cached_sha256(path)
    assert temporal.cached_sha256(path) == first == original(path)
    assert len(calls) == 1

    # Same size and modification time: the change time still tells the files apart once the clock has ticked
    # (within one tick, the age rule keeps a file from being cached at all, see the next test).
    time.sleep(0.05)
    path.write_text('a,b\n1,3\n')
    os.utime(path, ns=(old, old))
    assert temporal.cached_sha256(path) == original(path) != first
    assert len(calls) == 2


def test_recently_written_inputs_are_always_hashed(tmp_path, monkeypatch):
    path = tmp_path / 'input.csv'
    path.write_text('x\n')
    calls = []
    original = temporal.sha256
    monkeypatch.setattr(temporal, 'sha256', lambda p: calls.append(p) or original(p))
    monkeypatch.setattr(temporal, '_DIGEST_CACHE', {})

    temporal.cached_sha256(path)
    temporal.cached_sha256(path)
    assert len(calls) == 2


def test_importing_the_environment_does_not_import_torch():
    # citylearn.wrappers is left out: it imports ray when installed, and ray may import torch itself.
    code = (
        'import sys\n'
        'from citylearn.citylearn import CityLearnEnv\n'
        'import citylearn.agents.rbc, citylearn.agents.q_learning\n'
        'print(sorted(m for m in ("torch", "citylearn.dynamics") if m in sys.modules))\n'
    )
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.environ.get('PYTHONPATH', '')]))
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, check=True, cwd=ROOT)
    assert result.stdout.strip().splitlines()[-1] == '[]'


def test_lstm_dynamics_still_resolve_from_the_schema_path():
    pytest.importorskip('torch')
    import importlib

    import torch
    from citylearn.building import LSTMDynamicsBuilding  # noqa: F401  (imports without torch at module level)

    constructor = getattr(importlib.import_module('citylearn.dynamics'), 'LSTMDynamics')
    assert issubclass(constructor, torch.nn.Module)

    # Names citylearn.building used to import eagerly still resolve from it.
    import citylearn.building as building_module
    from citylearn.building import Dynamics, LSTMDynamics

    assert LSTMDynamics is constructor and issubclass(LSTMDynamics, Dynamics)
    assert building_module.torch is torch


def _wrapped_env(central_agent):
    from citylearn.citylearn import CityLearnEnv

    schema = json.loads((DATASET / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASET)
    return CityLearnEnv(schema, central_agent=central_agent, buildings=[0, 1], episode_time_steps=6, random_seed=0)


@pytest.mark.parametrize('central_agent', [False, True])
def test_cached_wrapper_spaces_equal_fresh_estimates(central_agent):
    from citylearn.wrappers import DiscreteObservationWrapper, NormalizedObservationWrapper

    env = DiscreteObservationWrapper(NormalizedObservationWrapper(_wrapped_env(central_agent)))
    normalized = env.env
    env.reset()

    for _ in range(3):
        env.step([s.sample() * 0 for s in env.action_space])
        fresh = normalized._estimate_normalized_observation_space()
        cached = normalized.observation_space
        assert [(s.low.tobytes(), s.high.tobytes(), s.dtype) for s in cached] == [(s.low.tobytes(), s.high.tobytes(), s.dtype) for s in fresh]
        assert [tuple(s.nvec) for s in env.observation_space] == [tuple(s.nvec) for s in env._build_observation_space()]

    # Deactivating an observation changes the key, so the spaces are estimated again.
    building = normalized.unwrapped.buildings[0]
    name = building.active_observations[-1]
    building.observation_metadata = {**building.observation_metadata, name: False}
    assert normalized.observation_space[0].shape == normalized._estimate_normalized_observation_space()[0].shape


def test_identical_series_are_shared_read_only_and_different_bits_are_not():
    from citylearn.data import TimeSeriesData
    from citylearn.internal.shared_series import share_identical_series

    def data(**series):
        item = TimeSeriesData(start_time_step=2, end_time_step=5)
        for name, values in series.items():
            setattr(item, name, np.array(values))
        return item

    cache = {}
    nan_payload = np.array([np.nan, 1.0], dtype='float32')
    other_nan = nan_payload.copy()
    other_nan.view('u4')[0] ^= 1
    first = data(hour=np.arange(10, dtype='int32'), month=np.zeros(2, dtype='float32'), day_type=nan_payload)
    second = data(hour=np.arange(10, dtype='int32'), month=-np.zeros(2, dtype='float32'), day_type=other_nan)
    third = data(hour=np.arange(1, 11, dtype='int32'))

    for item in (first, second, third):
        share_identical_series(cache, item, names=('hour', 'month', 'day_type'))

    assert second._hour is first._hour and not first._hour.flags.writeable
    np.testing.assert_array_equal(second.hour, np.arange(2, 6))
    assert second._month is not first._month
    assert second._day_type is not first._day_type
    assert third._hour is not first._hour

    with pytest.raises(ValueError):
        second.hour[0] = 1


def test_buildings_share_calendar_series_with_unchanged_values():
    import pandas as pd
    from citylearn.citylearn import CityLearnEnv

    env = CityLearnEnv(str(DATASET / 'schema.json'), episode_time_steps=4, random_seed=0)
    first, second = env.buildings[0].energy_simulation, env.buildings[1].energy_simulation
    source = pd.read_csv(DATASET / env.schema['buildings'][env.buildings[1].name]['energy_simulation'])

    assert second._hour is first._hour and second._month is first._month
    np.testing.assert_array_equal(second._hour, source['hour'].to_numpy(dtype='int32'))
    # Series a building owns, and the ones that may be written in place, are not shared.
    for name in ('non_shiftable_load', 'cooling_demand', 'hvac_mode', 'power_outage', 'comfort_band', 'occupant_count'):
        assert getattr(second, f'_{name}') is not getattr(first, f'_{name}')
        assert getattr(second, f'_{name}').flags.writeable


def _reference_settled_cost_series(self, *, condition_by_building):
    """The (step x member) loop that CityLearnKPIService._settled_cost_series replaced, kept verbatim (no cache)."""
    from citylearn.community_dataset import settlement_prices
    from citylearn.internal.kpi_population import current_population

    env = self.env
    buildings = self._get_kpi_buildings()
    building_names = [b.name for b in buildings]
    windows = {b.name: self._building_active_window(b) for b in buildings}
    step_count = max(int(getattr(env, 'time_step', 0)), 0)
    series = {name: np.zeros(step_count, dtype='float64') for name in building_names}
    if len(building_names) == 0:
        return series

    final_t = int(max(getattr(env, 'time_step', 0), 0))
    weights_config = getattr(env, 'community_market_import_member_weights', {}) or {}
    weights = np.array([self._to_scalar(weights_config.get(name, 1.0), 1.0) for name in building_names], dtype='float64')
    weight_by_name = {name: float(weight) for name, weight in zip(building_names, weights)}
    net_series_by_name, price_series_by_name = {}, {}

    for building in buildings:
        condition = condition_by_building.get(building.name)
        if condition is None:
            continue
        net_series_by_name[building.name] = np.asarray(
            self._energy_values(building, getattr(building, f'net_electricity_consumption{condition.value}')), dtype='float64')
        price_series_by_name[building.name] = np.asarray(building.pricing.electricity_pricing, dtype='float64')

    for t in range(min(final_t + 1, int(env.time_step))):
        net_values, active_buildings_t, active_weights_t = [], [], []
        for building in buildings:
            t_start, t_end = windows.get(building.name, (0, -1))
            if not (t_start <= t <= t_end):
                continue
            if getattr(env, 'topology_mode', 'static') == 'dynamic':
                population = current_population(self)
                active = (building.name in env._topology_service.active_member_ids_at(t)
                          if population is None else population.mask(building.name, final_t)[t])
                if not active:
                    continue
            net_series = net_series_by_name.get(building.name)
            if net_series is None:
                continue
            net_values.append(self._to_scalar(net_series[t] if t < len(net_series) else np.nan, 0.0))
            active_buildings_t.append(building)
            active_weights_t.append(weight_by_name.get(building.name, 1.0))

        if len(active_buildings_t) == 0:
            continue

        net_values = np.array(net_values, dtype='float64')
        imports = np.clip(net_values, 0.0, None)
        exports = np.clip(-net_values, 0.0, None)
        total_import = float(imports.sum())
        total_export = float(exports.sum())
        traded_kwh = min(total_import, total_export) if getattr(env, 'community_market_local_enabled', True) else 0.0
        if total_import > 0.0 and traded_kwh > 0.0:
            local_import = self._allocate_weighted_share_import(imports, traded_kwh, np.array(active_weights_t, dtype='float64'))
        else:
            local_import = np.zeros_like(imports, dtype='float64')
        if total_export > 0.0 and traded_kwh > 0.0:
            local_export = exports * (traded_kwh / total_export)
        else:
            local_export = np.zeros_like(exports, dtype='float64')

        for idx, building in enumerate(active_buildings_t):
            price_series = price_series_by_name.get(building.name)
            grid_import_price = self._to_scalar(
                price_series[t] if price_series is not None and t < len(price_series) else np.nan, 0.0)
            grid_export_price, local_buy_price, local_sell_price = settlement_prices(env, building.name, t, grid_import_price)
            grid_export_remaining = max(exports[idx] - local_export[idx], 0.0)
            grid_import_remaining = max(imports[idx] - local_import[idx], 0.0)
            cost = (
                grid_import_remaining * grid_import_price
                + local_import[idx] * local_buy_price
                - local_export[idx] * local_sell_price
                - grid_export_remaining * grid_export_price
            )
            series[building.name][t] = float(cost)

    return series


def _run_market_env(schema, steps, seed):
    from citylearn.citylearn import CityLearnEnv

    env = CityLearnEnv(schema, episode_time_steps=steps, random_seed=0)
    env.reset()
    rng = np.random.default_rng(seed)
    done = False
    while not done:
        space = env.action_space
        if isinstance(space, list):
            actions = [rng.uniform(-1.0, 1.0, s.shape).astype('float32') for s in space]
        else:
            actions = {'tables': {k: rng.uniform(-1.0, 1.0, v.shape).astype('float32') for k, v in space['tables'].items()}}
        _, _, terminated, truncated, _ = env.step(actions)
        done = terminated or truncated
    return env


def _assert_settled_costs_match(env, variants):
    from citylearn.citylearn import EvaluationCondition

    service = env._kpi_service
    names = [b.name for b in service._get_kpi_buildings()]
    conditions = [
        {name: EvaluationCondition.WITH_STORAGE_AND_PV for name in names},
        {name: EvaluationCondition.WITHOUT_STORAGE_BUT_WITH_PV for name in names},
        {name: EvaluationCondition.WITHOUT_STORAGE_AND_PV for i, name in enumerate(names) if i % 3},
    ]
    from citylearn.internal.kpi_population import ActivePopulation

    populations = [None]
    if getattr(env, 'topology_mode', 'static') == 'dynamic':
        populations.append(ActivePopulation(env))

    traded = 0
    for variant in variants:
        variant(env)
        for population in populations:
            service._evaluation_population = population
            for condition_by_building in conditions:
                service._settled_cost_cache = None
                expected = _reference_settled_cost_series(service, condition_by_building=condition_by_building)
                actual = service._settled_cost_series(condition_by_building=condition_by_building)
                assert list(actual) == list(expected)
                for name in expected:
                    assert actual[name].dtype == expected[name].dtype
                    assert actual[name].tobytes() == expected[name].tobytes(), name
                traded += sum(int(np.count_nonzero(v)) for v in expected.values())
    service._evaluation_population = None
    assert traded > 0


def _market_variants(names):
    def default(env):
        pass

    def weighted(env):
        env.community_market_import_member_weights = {name: (i % 4) * 0.37 for i, name in enumerate(names)}

    def zero_weights(env):
        env.community_market_import_member_weights = {name: 0.0 for name in names}

    def export_price(env):
        env.community_market_import_member_weights = {}
        env.community_market_grid_export_price = 0.0371
        env.community_market_sell_ratio = 0.63

    def tariffs(env):
        rng = np.random.default_rng(5)
        length = env.episode_tracker.episode_start_time_step + env.time_step + 3
        env.community_tariffs = {name: rng.uniform(0.0, 0.3, (length, 3)) for name in names[::2]}

    def local_off(env):
        env.community_tariffs = {}
        env.community_market_local_enabled = False

    return [default, weighted, zero_weights, export_price, tariffs, local_off]


def test_settled_cost_series_match_the_step_loop_bit_for_bit_static():
    root = ROOT / 'data' / 'datasets' / 'citylearn_three_phase_electrical_service_demo'
    schema = json.loads((root / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(root)
    env = _run_market_env(schema, 30, seed=11)
    _assert_settled_costs_match(env, _market_variants([b.name for b in env.buildings]))


def test_settled_cost_series_match_the_step_loop_bit_for_bit_dynamic_topology():
    root = ROOT / 'data' / 'datasets' / 'citylearn_three_phase_dynamic_topology_demo'
    schema = json.loads((root / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(root)
    shift = {1000: 4, 1300: 9, 1500: 13, 1600: 17, 1800: 20, 1900: 23, 2100: 26, 3200: 28}
    for event in schema['topology_events']:
        event['time_step'] = shift.get(event['time_step'], event['time_step'] - 3000)
    schema['topology_events'] = [e for e in schema['topology_events'] if 0 < e['time_step'] < 30]
    env = _run_market_env(schema, 30, seed=12)
    names = list(schema['buildings'])
    _assert_settled_costs_match(env, _market_variants(names))
