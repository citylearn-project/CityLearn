"""Progress observes evaluation without changing physics, KPI rows or BAU policy."""
from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from citylearn.agents.baseline import NormalPolicy
from citylearn.citylearn import CityLearnEnv
from test_independent_balances import scenario
from test_robustness import _event


def completed_env(tmp_path, *, dynamic=False, robust=False):
    initial = scenario(tmp_path, phase_limits=True, events=[
        dict(id='leave', time_step=3, operation='remove_member', target_member_id='Building_2'),
    ] if dynamic else None)
    schema = deepcopy(initial.schema)
    initial.close()
    if robust:
        path = tmp_path / 'events.csv'
        pd.DataFrame([_event(module='action', target_type='storage', target_id='*',
                            target_feature='electrical_storage', start=1, end=2, mode='dropout')]).to_csv(path, index=False)
        schema['robustness'] = dict(enabled=True, events_file=str(path), random_seed=7)
    env = CityLearnEnv(schema, random_seed=19, offline=True, render_mode='none',
                       physics_invariant_checks=True, export_kpis_on_episode_end=False)
    obs, _ = env.reset(seed=19)
    policy = NormalPolicy(env)
    while not env.terminated:
        obs, *_ = env.step(policy.predict(obs, deterministic=True))
    return env


@pytest.mark.parametrize('dynamic,robust', [(False, False), (True, False), (False, True), (True, True)])
def test_progress_is_local_ordered_and_preserves_results_and_physical_state(tmp_path, dynamic, robust):
    env = completed_env(tmp_path, dynamic=dynamic, robust=robust)
    try:
        before = [(b.electrical_storage.soc.copy(), b.electrical_storage.capacity_history[:])
                  for b in env._kpi_service._get_kpi_buildings()]
        plain = env.evaluate_v2(include_business_as_usual=False)
        events = []
        observed = env.evaluate_v2(include_business_as_usual=False, progress_callback=events.append)
        assert_frame_equal(plain, observed, check_exact=True)
        assert plain.attrs == observed.attrs
        assert events[0]['stage'] == events[-1]['stage'] == 'evaluation'
        assert events[0]['status'] == 'started' and events[-1]['status'] == 'completed'
        assert [e['sequence'] for e in events] == list(range(1, len(events) + 1))
        assert [e['elapsed_seconds'] for e in events] == sorted(e['elapsed_seconds'] for e in events)
        assert {'energy_and_service', 'ev', 'battery', 'solar', 'electrical_service',
                'market', 'thermal_equity_audit', 'provenance', 'formatting'} <= {e['stage'] for e in events}
        ev_events = [e for e in events if e['stage'] == 'ev']
        assert all(e['member'] and 1 <= e['member_index'] <= e['member_count'] for e in ev_events)
        json.dumps(events, allow_nan=False)
        assert all(e['stage_seconds'] >= 0 for e in events if e['status'] == 'completed')
        again = []
        env.evaluate_v2(include_business_as_usual=False, progress_callback=again.append)
        assert again[0]['sequence'] == 1
        assert not any('progress' in key for key in observed.attrs)
        for building, (soc, capacity) in zip(env._kpi_service._get_kpi_buildings(), before):
            np.testing.assert_array_equal(building.electrical_storage.soc, soc)
            np.testing.assert_array_equal(building.electrical_storage.capacity_history, capacity)
    finally:
        env.close()


def test_broken_observer_is_disabled_without_losing_valid_kpis(tmp_path, caplog):
    env = completed_env(tmp_path)
    try:
        expected = env.evaluate_v2(include_business_as_usual=False)
        calls = []
        def broken(event):
            calls.append(event)
            raise OSError('diagnostic destination unavailable')
        actual = env.evaluate_v2(include_business_as_usual=False, progress_callback=broken)
        assert_frame_equal(actual, expected, check_exact=True)
        assert len(calls) == 1
        assert 'reporting disabled' in caplog.text
        with pytest.raises(TypeError, match='progress_callback'):
            env.evaluate_v2(progress_callback=42)
    finally:
        env.close()


def test_numerical_failure_reports_the_member_and_family_and_propagates(tmp_path, monkeypatch):
    env = completed_env(tmp_path)
    try:
        events = []
        def fail(*args, **kwargs):
            raise RuntimeError('evaluation failed')
        monkeypatch.setattr(env._kpi_service, '_compute_ev_metrics', fail)
        with pytest.raises(RuntimeError, match='^evaluation failed$'):
            env.evaluate_v2(include_business_as_usual=False, progress_callback=events.append)
        failed = [e for e in events if e['stage'] == 'ev' and e['status'] == 'failed']
        assert len(failed) == 1 and failed[0]['member'] == 'Building_1'
        assert events[-1]['stage'] == 'evaluation' and events[-1]['status'] == 'failed'
    finally:
        env.close()


def test_long_audit_writes_current_and_historical_evaluation_progress(tmp_path):
    from scripts.audit.audit_long_run import run
    initial = scenario(tmp_path, phase_limits=True)
    schema = deepcopy(initial.schema)
    initial.close()
    schema['community_market']['grid_export_price'] = 0.0
    path = tmp_path / 'schema.json'
    path.write_text(json.dumps(schema))
    output = tmp_path / 'audit-output'
    assert run(SimpleNamespace(schema=path, start=0, transitions=7, seed=0,
                               block_steps=2, max_rss_mib=8192, max_seconds=120, output=output)) == 0
    summary = json.loads((output / 'summary.json').read_text())
    events = [json.loads(line) for line in (output / 'evaluation-progress.jsonl').read_text().splitlines()]
    assert summary['status'] == 'pass' and summary['phase'] == 'completed'
    assert summary['physics_invariant_checks'] is True
    assert summary['kpi_evaluation_seconds'] >= 0
    assert json.loads((output / 'evaluation-progress.json').read_text()) == events[-1]
    assert summary['evaluation_progress'] == events[-1]
    assert events[-1]['stage'] == 'evaluation' and events[-1]['status'] == 'completed'
    assert (output / 'kpis.csv').is_file() and (output / 'manifest.json').is_file()
