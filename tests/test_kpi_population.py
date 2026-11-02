"""Evaluation-local masks preserve legacy sample selection and temporal scopes."""
from copy import deepcopy
import gc
from types import SimpleNamespace
import weakref

import numpy as np
import pytest
from pandas.testing import assert_frame_equal

from citylearn.agents.baseline import NormalPolicy
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.internal.kpi_population import current_population, population_scope
from citylearn.internal.topology import CityLearnTopologyService
from test_evaluation_progress import completed_env
from test_independent_balances import scenario


def sample_service(history, *, horizon=7):
    topology = object.__new__(CityLearnTopologyService)
    topology._active_member_history = deepcopy(history)
    topology._active_member_ids = ['fallback', 'b']
    topology._topology_version = 0
    env = SimpleNamespace(topology_mode='dynamic', time_step=horizon, _topology_service=topology,
                          topology_member_lifecycle={}, episode_tracker=SimpleNamespace(
                              episode=0, episode_start_time_step=100, episode_end_time_step=107))
    return CityLearnKPIService(env)


@pytest.mark.parametrize('history', [{}, {2: ['a'], 5: ['b']},
    {0: ['a', 'b'], 2: ['b'], 4: ['a'], 6: []}])
def test_membership_windows_short_histories_and_nan_match_uncached_readers(history):
    kpi = sample_service(history)
    queries = [(name, length, start, end) for name in ['a', 'b', 'fallback', 'absent']
               for length in [0, 3, 10] for start, end in [(0, None), (-2, 1), (2, 5), (8, 9), (0, -1)]]
    data = np.array([0.0, np.nan, -2.5, 3.0, 0.0, np.nan, 7.0, 99.0, 100.0, 101.0])
    expected = [kpi._thermal_values(SimpleNamespace(name=n), data[:length], start, end)
                for n, length, start, end in queries]
    energy_expected = {name: kpi._energy_values(SimpleNamespace(name=name), data) for name in ['a', 'b', 'fallback', 'absent']}

    @population_scope
    def compare(service):
        for (name, length, start, end), values in zip(queries, expected):
            actual = service._thermal_values(SimpleNamespace(name=name), data[:length], start, end)
            np.testing.assert_array_equal(actual, values)
        for name, values in energy_expected.items():
            actual = service._energy_values(SimpleNamespace(name=name), data)
            np.testing.assert_array_equal(actual, values)
        population = current_population(service)
        mask = population.mask('a', 7)
        assert population.mask('a', 7) is mask
        assert not mask.flags.writeable
        with pytest.raises(ValueError):
            mask[0] = True
        result = service._energy_values(SimpleNamespace(name='a'), data)
        result[:] = 1000
        np.testing.assert_array_equal(service._energy_values(SimpleNamespace(name='a'), data), energy_expected['a'])
    compare(kpi)
    assert not hasattr(kpi, '_evaluation_population')
    np.testing.assert_array_equal(data, [0.0, np.nan, -2.5, 3.0, 0.0, np.nan, 7.0, 99.0, 100.0, 101.0])


def test_fallback_before_first_snapshot_differs_from_energy_zero_prefix():
    kpi = sample_service({3: ['a']})
    @population_scope
    def check(service):
        pop = current_population(service)
        assert pop.mask('b', 7).tolist() == [True, True, True, False, False, False, False]
        assert pop.mask('b', 7, energy=True).tolist() == [False] * 7
        assert pop.mask('a', 7).tolist() == [False, False, False, True, True, True, True]
    check(kpi)


def test_scope_refreshes_episode_window_horizon_history_and_topology_then_releases():
    kpi = sample_service({0: ['a']})
    refs = []
    @population_scope
    def nested(service):
        return current_population(service)
    @population_scope
    def check(service):
        pop = current_population(service)
        assert nested(service) is pop
        for update in [
            lambda: setattr(service.env, 'time_step', 5),
            lambda: setattr(service.env.episode_tracker, 'episode', 1),
            lambda: setattr(service.env.episode_tracker, 'episode_start_time_step', 102),
            lambda: setattr(service.env.episode_tracker, 'episode_end_time_step', 109),
            lambda: setattr(service.env._topology_service, '_topology_version', 1),
            lambda: setattr(service.env._topology_service, '_active_member_history', {0: ['b']}),
        ]:
            refs.append(weakref.ref(pop));update();new = current_population(service)
            assert new is not pop
            assert nested(service) is new
            pop = new
        assert pop.mask('b', 5).all()
        refs.append(weakref.ref(pop))
    check(kpi)
    gc.collect()
    assert not hasattr(kpi, '_evaluation_population')
    assert all(ref() is None for ref in refs)


def test_failed_scope_does_not_leak_or_reuse_stale_masks():
    kpi = sample_service({0: ['a']})
    @population_scope
    def fail(service):
        assert current_population(service).mask('a', 7).all()
        raise RuntimeError('evaluation failed')
    with pytest.raises(RuntimeError, match='evaluation failed'):
        fail(kpi)
    assert not hasattr(kpi, '_evaluation_population')
    # Same env/time/version, but a separate evaluation must take a fresh snapshot.
    kpi.env._topology_service._active_member_history[0] = ['b']
    @population_scope
    def again(service):
        assert not current_population(service).mask('a', 7).any()
    again(kpi)


@pytest.mark.parametrize('dynamic,robust', [(False, False), (True, False), (False, True), (True, True)])
def test_native_kpis_equal_uncached_and_release_after_repeated_evaluation(tmp_path, monkeypatch, dynamic, robust):
    env = completed_env(tmp_path, dynamic=dynamic, robust=robust)
    refs = []
    try:
        def observe(event):
            pop = getattr(env._kpi_service, '_evaluation_population', None)
            if pop is not None:
                refs.append(weakref.ref(pop))
        first = env.evaluate_v2(include_business_as_usual=False, progress_callback=observe)
        with monkeypatch.context() as patch:
            patch.setattr('citylearn.internal.kpi.current_population', lambda service: None)
            uncached = env.evaluate_v2(include_business_as_usual=False)
        assert_frame_equal(first, uncached, check_exact=True)
        assert first.attrs == uncached.attrs
        assert_frame_equal(first, env.evaluate_v2(include_business_as_usual=False), check_exact=True)
        assert not hasattr(env._kpi_service, '_evaluation_population')
        gc.collect()
        assert all(ref() is None for ref in refs)
        assert bool(refs) is dynamic
        if dynamic:
            original = env._topology_service.active_member_ids_at(0)
            changed = env._topology_service.active_member_ids_at(0)
            changed.clear()
            assert env._topology_service.active_member_ids_at(0) == original
    finally:
        env.close()


def test_partial_horizons_remove_rejoin_reset_and_native_bau(tmp_path, monkeypatch):
    env = scenario(tmp_path, phase_limits=True, events=[
        dict(id='leave', time_step=2, operation='remove_member', target_member_id='Building_2'),
        dict(id='rejoin', time_step=4, operation='add_member', target_member_id='Building_2'),
    ])
    try:
        obs, _ = env.reset(seed=19)
        policy = NormalPolicy(env)
        for step in range(8):
            if step in [0, 2, 4, 7]:
                cached = env.evaluate_v2(include_business_as_usual=False)
                with monkeypatch.context() as patch:
                    patch.setattr('citylearn.internal.kpi.current_population', lambda service: None)
                    uncached = env.evaluate_v2(include_business_as_usual=False)
                assert_frame_equal(cached, uncached, check_exact=True)
                assert cached.attrs == uncached.attrs
                assert not hasattr(env._kpi_service, '_evaluation_population')
            if env.terminated:
                break
            obs, *_ = env.step(policy.predict(obs, deterministic=True))
        # Native BAU is a different environment with its own evaluation scope.
        with_bau = env.evaluate_v2(include_business_as_usual=True)
        assert not with_bau.empty
        assert not hasattr(env._kpi_service, '_evaluation_population')
        for result in env._business_as_usual_baseline_cache.values():
            assert not hasattr(result.env._kpi_service, '_evaluation_population')
        env.reset(seed=19)
        assert not hasattr(env._kpi_service, '_evaluation_population')
        first = env.get_kpi_family_audit()
        assert first['district']['executed_intervals_count'] == 0
    finally:
        env.close()
