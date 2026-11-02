"""Observation preparation preserves live inputs, timing and custom reward contracts."""
import gc
import math
from types import MethodType, SimpleNamespace
import weakref

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.entity_interface import CityLearnEntityInterfaceService as Entity
from citylearn.reward_function import RewardFunction
from test_internal_service_contracts import fixture_schema


class Source:
    def __init__(self, **fields):
        self.fields, self.reads = fields, {}

    def __getattr__(self, name):
        if name not in self.fields:
            raise AttributeError(name)
        self.reads[name] = self.reads.get(name, 0) + 1
        return self.fields[name]


class Device:
    def get_input_power(self, demand, *args, **kwargs):
        return demand / 2.0


def forecast_fixture(seconds=900, method='daily_persistence', length=1024):
    service = Entity.__new__(Entity)
    service.env = SimpleNamespace(seconds_per_time_step=seconds, schema={
        'derived_forecasts': {'load_pv_method': method}})
    service._forecast_step_offsets = tuple(
        (label, max(int(np.ceil(duration/seconds)), 1))
        for label, duration in service.FORECAST_HORIZONS)
    values = np.arange(length, dtype='float64') / 100
    energy = Source(**{name: values.copy() for name in (
        'non_shiftable_load', 'cooling_demand', 'heating_demand', 'dhw_demand', 'solar_generation')})
    weather = Source(outdoor_dry_bulb_temperature=values.copy())
    building = SimpleNamespace(energy_simulation=energy, weather=weather, time_step_ratio=.25,
        cooling_device=Device(), heating_device=Device(), dhw_device=Device(),
        deferrable_appliances=[SimpleNamespace(electricity_consumption=values.copy())],
        _pv_generation_to_control_step=lambda value: np.array(value)*.25)
    return service, building


def scan_forecasts(service, building, step):
    """Original per-horizon computation: no source/result reuse."""
    result = {}
    length = len(building.energy_simulation.non_shiftable_load)
    for label, ahead in service._forecast_step_offsets:
        point = service._derived_forecast_point_index_from_steps(step, ahead, length)
        values = service._building_forecast_components_at_step(building, point) if point >= 0 else (0., 0., 0.)
        for signal, value in zip(('load', 'pv', 'net'), values):
            result[f'forecast_{signal}_next_{label}_kw'] = value
    return result


@pytest.mark.parametrize('seconds', [15, 60, 900, 3600])
@pytest.mark.parametrize('method', ['daily_persistence', 'actual_future'])
@pytest.mark.parametrize('step', [0, 100, 1023])
def test_forecast_reuse_matches_uncached_horizons_exactly(seconds, method, step):
    service, building = forecast_fixture(seconds, method)
    assert service._build_derived_forecast_building_metrics(building=building, time_step=step) == scan_forecasts(service, building, step)


@pytest.mark.parametrize('length', [0, 1, 7])
def test_empty_and_short_series_preserve_horizon_boundaries(length):
    service, building = forecast_fixture(length=length)
    assert service._build_derived_forecast_building_metrics(building=building, time_step=0) == scan_forecasts(service, building, 0)


def test_source_views_are_retrieved_once_for_distinct_points_in_one_request():
    service, building = forecast_fixture()
    service._build_derived_forecast_building_metrics(building=building, time_step=200)
    assert building.weather.reads['outdoor_dry_bulb_temperature'] == 1
    assert building.energy_simulation.reads['cooling_demand'] == 1
    assert building.energy_simulation.reads['solar_generation'] == 1
    # One length query plus the single source view retrieval.
    assert building.energy_simulation.reads['non_shiftable_load'] == 2


def test_cold_start_repeated_points_compute_once_but_next_request_recomputes(monkeypatch):
    service, building = forecast_fixture()
    original = service._building_forecast_components_at_step
    calls = []
    def counted(*args, **kwargs):
        calls.append(args[1]); return original(*args, **kwargs)
    monkeypatch.setattr(service, '_building_forecast_components_at_step', counted)
    service._build_derived_forecast_building_metrics(building=building, time_step=0)
    assert calls == [0]
    service._build_derived_forecast_building_metrics(building=building, time_step=0)
    assert calls == [0, 0]


def test_same_step_mutations_of_sources_devices_and_booked_load_are_visible():
    service, building = forecast_fixture()
    first = service._build_derived_forecast_building_metrics(building=building, time_step=200)
    building.energy_simulation.fields['non_shiftable_load'] += 3.
    building.weather.fields['outdoor_dry_bulb_temperature'][:] = 12.
    building.heating_device.get_input_power = lambda demand: demand / 4.
    building.deferrable_appliances[0].electricity_consumption += 2.
    second = service._build_derived_forecast_building_metrics(building=building, time_step=200)
    assert second != first
    assert second == scan_forecasts(service, building, 200)
    second[next(iter(second))] = -12345.
    assert service._build_derived_forecast_building_metrics(building=building, time_step=200) == scan_forecasts(service, building, 200)


def test_source_replacement_and_episode_shape_change_do_not_reuse_old_views():
    service, building = forecast_fixture()
    service._build_derived_forecast_building_metrics(building=building, time_step=20)
    old = weakref.ref(building.energy_simulation.fields['non_shiftable_load'])
    building.energy_simulation.fields['non_shiftable_load'] = np.full(32, 90.)
    gc.collect()
    assert old() is None
    assert service._build_derived_forecast_building_metrics(building=building, time_step=20) == scan_forecasts(service, building, 20)


def test_daily_persistence_never_samples_future_truth():
    service, building = forecast_fixture()
    sampled = []
    class PastOnly:
        def __len__(self):return 1024
        def __getitem__(self, index):
            sampled.append(index)
            assert index <= 100
            return float(index)
    building.energy_simulation.fields = {name: PastOnly() for name in building.energy_simulation.fields}
    building.weather.fields['outdoor_dry_bulb_temperature'] = PastOnly()
    service._build_derived_forecast_building_metrics(building=building, time_step=100)
    assert sampled and max(sampled) <= 100


@pytest.mark.parametrize('value', [0., -0., 1., True, np.float32(.3), np.int64(2), np.array(3.),
                                    float('nan'), float('inf'), -float('inf'), None, 'bad', '2.3'])
def test_scalar_finiteness_fast_path_matches_previous_float_semantics(value):
    def original(v):
        try:s = float(v)
        except (TypeError, ValueError):return -7.
        return s if np.isfinite(s) else -7.
    actual, expected = Entity._safe_scalar(value, -7.), original(value)
    assert actual == expected
    if actual == 0.:assert math.copysign(1., actual) == math.copysign(1., expected)


def test_only_builtin_reward_declares_minimal_inputs_and_external_overrides_keep_fallback():
    reward = RewardFunction({'central_agent': False})
    assert reward.get_required_observation_names() == ('net_electricity_consumption',)
    class CustomReward(RewardFunction):
        def calculate(self, observations):return [o['solar_generation'] for o in observations]
    assert CustomReward({'central_agent': False}).get_required_observation_names() is None
    reward.calculate = MethodType(lambda self, observations: [o['solar_generation'] for o in observations], reward)
    assert reward.get_required_observation_names() is None


@pytest.mark.parametrize('interface', ['flat', 'entity'])
def test_default_reward_matches_full_payload_without_changing_values_or_custom_visibility(tmp_path, interface):
    env = CityLearnEnv(fixture_schema(tmp_path, interface, dynamic=(interface == 'entity')), random_seed=0,
        physics_invariant_checks=True, export_kpis_on_episode_end=False, render_mode='none')
    try:
        env.reset(seed=0)
        class InspectReward(RewardFunction):
            def calculate(self, observations):
                self.seen = [dict(o) for o in observations]
                return RewardFunction.calculate(self, observations)
        full = InspectReward(env.get_metadata())
        before = [b.observations(include_all=True) for b in env.buildings]
        minimal = [b.observations(include_all=True, observation_names=('net_electricity_consumption',)) for b in env.buildings]
        assert env.reward_function.calculate(before) == env.reward_function.calculate(minimal)
        env.reward_function = full
        action = ({'tables': {name: np.zeros(space.shape, dtype='float32')
            for name, space in env.action_space['tables'].items()}} if interface == 'entity'
            else [np.zeros(space.shape, dtype='float32') for space in env.action_space])
        env.step(action)
        assert full.seen and 'solar_generation' in full.seen[0]
        assert 'net_electricity_consumption' in full.seen[0]
    finally:env.close()


def test_episode_series_rebasing_and_forecast_method_change_are_visible_without_stale_views():
    from citylearn.data import TimeSeriesData
    service, building = forecast_fixture()
    for target in ('energy_simulation', 'weather'):
        source = getattr(building, target)
        series = TimeSeriesData(start_time_step=100, end_time_step=700)
        for name, values in source.fields.items():
            setattr(series, name, values)
        setattr(building, target, series)
    first = service._build_derived_forecast_building_metrics(building=building, time_step=100)
    building.energy_simulation.start_time_step = 200
    building.weather.start_time_step = 200
    second = service._build_derived_forecast_building_metrics(building=building, time_step=100)
    assert second != first
    assert second == scan_forecasts(service, building, 100)
    service.env.schema['derived_forecasts']['load_pv_method'] = 'actual_future'
    third = service._build_derived_forecast_building_metrics(building=building, time_step=100)
    assert third != second
    assert third == scan_forecasts(service, building, 100)


def test_multi_building_reward_keeps_unknown_child_requirements_unrestricted():
    from citylearn.reward_function import MultiBuildingRewardFunction
    metadata = {'central_agent': False}
    children = {name: RewardFunction(metadata) for name in ('A', 'B')}
    reward = MultiBuildingRewardFunction(metadata, children)
    assert tuple(reward.get_required_observation_names()) == ('net_electricity_consumption',)
    assert reward.calculate([{'net_electricity_consumption': 1.}, {'net_electricity_consumption': 2.}]) == [[-1.], [-2.]]
    class ExternalReward(RewardFunction):
        def calculate(self, observations):return [o['solar_generation'] for o in observations]
    children['B'] = ExternalReward(metadata)
    assert reward.get_required_observation_names() is None
    assert reward.calculate([{'net_electricity_consumption': 1.}, {'solar_generation': 3.}]) == [[-1.], [3.]]
