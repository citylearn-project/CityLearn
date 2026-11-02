"""Application evidence survives compaction, deduplication and windowed reads."""
from copy import deepcopy
import pickle
from types import SimpleNamespace

import pytest

from citylearn.internal.robustness import CityLearnRobustnessService
from citylearn.internal.robustness_history import RobustnessHistory, _StepRecord


def service():
    result = object.__new__(CityLearnRobustnessService)
    result.env = SimpleNamespace(time_step=0, episode_tracker=SimpleNamespace(episode_start_time_step=100))
    result._history = RobustnessHistory()
    return result


def apply(s, step, *, event='event', module='observation', kind='observation', mode='noise',
          target='meter', building='house / α', global_id=None):
    s.env.time_step = step - 100
    s._record_application(SimpleNamespace(event_id=event, module=module), kind,
                          dict(target_key=target, building=building, global_id=global_id), mode=mode)


def test_exact_order_deduplication_asset_identity_and_terminal_populations():
    s = service()
    for feature in ['soc', 'power']:
        apply(s, 100, event='offline', module='asset', kind='asset', mode='unavailable',
              target=feature, global_id='same-battery')
        apply(s, 100, event='offline', module='asset', kind='observation', mode='unavailable', target=feature)
        apply(s, 100, event='offline', module='asset', kind='action', mode='unavailable', target=feature)
    # Same key, repeated observation query: no additional application.
    apply(s, 100, event='offline', module='asset', target='soc', mode='unavailable')
    expected = deepcopy(s.history[100])
    assert [a['kind'] for a in expected['applications']] == ['asset', 'observation', 'action', 'observation', 'action']
    assert expected['applications'][0]['target_key'] == 'soc'
    assert s._counts_for_step(100) == dict(observation=2, forecast=0, action=2, asset=1, missing=2, dropout=2)
    apply(s, 101, event='terminal', kind='forecast', module='forecast', mode='missing', building=None)
    assert s.history[100] == expected
    assert s.history[101]['applications'][0]['building'] is None
    by, district = s.summarize(['house / α', 'absent'])
    executed_by, executed = s.summarize(['house / α', 'absent'], executed_only=True)
    assert district['robustness_events_count'] == 2
    assert district['robustness_active_time_step_count'] == 2
    assert district['robustness_forecast_corruption_count'] == 1
    assert district['robustness_missing_observation_count'] == 3
    assert executed['robustness_events_count'] == executed['robustness_active_time_step_count'] == 1
    assert executed['robustness_forecast_corruption_count'] == 0
    assert by == executed_by
    assert by['house / α']['robustness_asset_unavailable_time_step_count'] == 1
    assert by['house / α']['robustness_active_time_step_count'] == 1
    assert all(value == 0 for value in by['absent'].values())
    assert s._counts_for_step(99) == dict.fromkeys(['observation', 'forecast', 'action', 'asset', 'missing', 'dropout'], 0)


def test_duplicate_mode_updates_district_sets_but_preserves_first_application():
    s = service()
    apply(s, 100, mode='noise')
    apply(s, 100, mode='missing')
    apply(s, 101, mode='noise')  # Seal the previous step.
    by, district = s.summarize(['house / α'])
    assert district['robustness_missing_observation_count'] == 1
    assert by['house / α']['robustness_missing_observation_count'] == 0
    assert s.history[100]['applications'][0]['mode'] == 'noise'
    assert len(s.history[100]['applications']) == 1


def test_sparse_steps_reopened_in_place_and_arbitrary_executed_cutoffs():
    s = service()
    apply(s, 105, event='late', building='removed')
    apply(s, 101, event='early', module='action', kind='action', mode='delay', building='new')
    apply(s, 105, event='additional', module='action', kind='action', mode='dropout', building='removed')
    apply(s, 109, event='final', building=None)
    assert list(s._history) == [105, 101, 109]
    assert list(s.history) == [101, 105, 109]
    assert [a['event_id'] for a in s.history[105]['applications']] == ['late', 'additional']
    for cutoff, events, observations, actions, active in [
        (100, 0, 0, 0, 0), (102, 1, 0, 1, 1), (106, 3, 1, 2, 2), (110, 4, 2, 2, 3),
    ]:
        by, result = s._history.summary(['removed', 'new'], executed_before=cutoff)
        assert result['robustness_events_count'] == events
        assert result['robustness_observation_corruption_count'] == observations
        assert result['robustness_action_corruption_count'] == actions
        assert result['robustness_active_time_step_count'] == active
    assert s._history.summary(['removed', 'new'])[1] == result
    assert [scope[:3] for scope in s._history.application_scopes()] == [
        (105, 'late', 'observation'), (105, 'additional', 'action'),
        (101, 'early', 'action'), (109, 'final', 'observation'),
    ]


def test_incremental_summary_does_not_decode_sealed_applications(monkeypatch):
    s = service()
    for step in range(100, 150):
        apply(s, step)
    expected = s.summarize(['house / α'])
    expected_executed = s.summarize(['house / α'], executed_only=True)
    def fail(*args):
        raise AssertionError('A full-prefix summary must reuse accumulated counts')
    monkeypatch.setattr(_StepRecord, '__getitem__', fail)
    assert s.summarize(['house / α']) == expected
    assert s.summarize(['house / α'], executed_only=True) == expected_executed
    assert s._counts_for_step(101)['observation'] == 1


def test_window_stream_snapshots_pickle_and_copy_keep_all_fields():
    s = service()
    for step in [100, 104, 108]:
        apply(s, step, target='name:with/slashes', mode='stuck')
    original = deepcopy(s.history)
    assert s.history_window(101, 108) == {104: original[104]}
    assert list(s.iter_history(100, 105)) == [(100, original[100]), (104, original[104])]
    window = s.history_window()
    window[108]['applications'][0]['target_key'] = 'changed'
    window[100]['event_ids'].clear()
    assert s.history == original
    for history in [deepcopy(s._history), pickle.loads(pickle.dumps(s._history))]:
        assert {step: s._public_record(record) for step, record in sorted(history.items())} == original
        assert history.summary(['house / α']) == s._history.summary(['house / α'])
    apply(s, 109, event='later')
    assert s.history_window(100, 109) == original


def test_empty_history_queries_and_fresh_episode_are_independent():
    s = service()
    assert s.history == s.history_window() == {}
    assert list(s.iter_history()) == []
    assert all(v == 0.0 for v in s.summarize(['missing'])[1].values())
    apply(s, 100)
    old = s._history
    s._history = RobustnessHistory()
    assert s.history == {}
    assert old.summary(['house / α'])[1]['robustness_events_count'] == 1
    assert s.summarize(['house / α'])[1]['robustness_events_count'] == 0
