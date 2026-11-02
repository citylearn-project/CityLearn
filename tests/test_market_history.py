"""Lossless history, exact aggregation and native market/runtime compatibility."""
from copy import deepcopy
import json
import pickle
import random
import struct
from types import SimpleNamespace

import numpy as np
import pytest
from pandas.testing import assert_frame_equal

from citylearn.internal.kpi import CityLearnKPIService
from citylearn.internal.market_history import FIELDS, MarketSettlementHistory
from test_evaluation_progress import completed_env


def record(name='house / 001', value=0.1):
    return dict(building=name, **{field: float(value + i / 7) for i, field in enumerate(FIELDS)})


def legacy_totals(history, names):
    return CityLearnKPIService(SimpleNamespace(_community_market_settlement_history=history))._collect_market_totals(names)


def test_binary64_round_trip_windows_and_independent_snapshots():
    values = [0.0, -0.0, 1e-280, -1e280, np.nextafter(0.8, 1.0), float('inf'), float('nan')]
    steps = [[dict(building='名前 / casa', **dict.fromkeys(FIELDS, float(v)))] for v in values]
    history = MarketSettlementHistory(steps)
    for expected, actual in zip(steps, history):
        assert list(actual[0]) == list(expected[0])
        for field in FIELDS:
            assert struct.pack('d', actual[0][field]) == struct.pack('d', expected[0][field])
    assert history[-3:-1] == steps[-3:-1]
    assert history[::-2][1:] == steps[::-2][1:]
    first = history[0]
    first[0]['local_price'] = 999.0
    assert history[0][0]['local_price'] == 0.0
    with pytest.raises(IndexError):
        _ = history[len(history)]
    with pytest.raises(TypeError):
        _ = history[1.1]
    assert len(list(history)) == len(steps)
    assert history.market_totals(['名前 / casa']) == legacy_totals(steps, ['名前 / casa'])


def test_unknown_legacy_fields_and_values_are_not_dropped():
    steps = [[{'building': 'legacy', 'settled_cost': 0.7, 'extra': {'source': [1, 2]},
               'market_savings_eur': 'invalid'}], [], [record('normal')]]
    history = MarketSettlementHistory(steps)
    assert list(history) == steps
    assert json.dumps(list(history)) == json.dumps(steps)
    assert history.market_totals(['legacy', 'normal', 'absent']) == legacy_totals(steps, ['legacy', 'normal', 'absent'])
    steps[0][0]['extra']['source'].append(3)
    assert history[0][0]['extra']['source'] == [1, 2]
    assert list(pickle.loads(pickle.dumps(history))) == list(history)
    assert list(deepcopy(history)) == list(history)


def test_random_edits_empty_steps_members_and_totals_match_list_exactly():
    rng = random.Random(18)
    history, reference = MarketSettlementHistory(), []
    names = ['removed', 'added', 'persistent', 'absent']
    for i in range(240):
        rows = [record(name, rng.uniform(-3, 3)) for name in names[:3] if rng.random() > 0.45]
        operation = rng.choice(['append', 'replace', 'truncate', 'insert', 'slice'])
        if not reference or operation == 'append':
            reference.append(rows); history.append(rows)
        elif operation == 'replace':
            index = rng.randrange(-len(reference), len(reference))
            reference[index] = rows; history[index] = rows
        elif operation == 'truncate':
            index = rng.randrange(len(reference) + 1)
            del reference[index:]; del history[index:]
        elif operation == 'insert':
            index = rng.randrange(-len(reference), len(reference) + 2)
            reference.insert(index, rows); history.insert(index, rows)
        else:
            reference[::2] = [rows for _ in reference[::2]]
            history[::2] = [rows for _ in history[::2]]
        assert list(history) == reference
        assert history.market_totals(names) == legacy_totals(reference, names)
    totals = history.market_totals(names)
    totals[0]['absent']['community_settled_cost_total_eur'] = 999
    assert history.market_totals(names) == legacy_totals(reference, names)
    history.clear()
    assert list(history) == []
    assert history.market_totals(names) == legacy_totals([], names)


@pytest.mark.parametrize('dynamic,robust', [(False, False), (True, False), (False, True), (True, True)])
def test_native_kpis_exports_and_reset_match_materialized_history(tmp_path, dynamic, robust):
    env = completed_env(tmp_path, dynamic=dynamic, robust=robust)
    try:
        compact = env._community_market_settlement_history
        assert isinstance(compact, MarketSettlementHistory)
        expected_rows = list(compact)
        compact_frame = env.evaluate_v2(include_business_as_usual=False)
        last = deepcopy(env._last_community_market_settlement)
        # Legacy caller-supplied histories keep their existing KPI path.
        env._community_market_settlement_history = expected_rows
        legacy_frame = env.evaluate_v2(include_business_as_usual=False)
        assert_frame_equal(compact_frame, legacy_frame, check_exact=True)
        assert compact_frame.attrs == legacy_frame.attrs
        assert env._last_community_market_settlement == last == expected_rows[-1]
        env._community_market_settlement_history = compact
        env.reset(seed=19)
        assert isinstance(env._community_market_settlement_history, MarketSettlementHistory)
        # Reset settles the initial t=0 interval, as the legacy runtime did.
        reset_history = env._community_market_settlement_history
        assert len(reset_history) == 1
        assert reset_history[0] == env._last_community_market_settlement
        names = [b.name for b in env.buildings]
        assert reset_history.market_totals(names) == legacy_totals(list(reset_history), names)
        assert env._community_market_settlement_history is not compact
        assert list(compact) == expected_rows
    finally:
        env.close()


def test_append_totals_do_not_materialize_historical_rows(monkeypatch):
    history = MarketSettlementHistory([[record('old')]])
    del history[:]  # Initial-step resettlement must not disable incremental totals.
    history.append([record('new', -0.2)])
    history.append([record('old', 0.3)])
    expected = legacy_totals(list(history), ['old', 'new'])
    def fail(*args):
        raise AssertionError('incremental totals must not reconstruct history')
    monkeypatch.setattr(MarketSettlementHistory, '__iter__', fail)
    assert history.market_totals(['old', 'new']) == expected


@pytest.mark.parametrize('index', [100.5, '1', None])
def test_insert_rejects_non_integer_indices_without_modifying_history(index):
    history = MarketSettlementHistory([[record()]])
    expected = list(history)
    with pytest.raises(TypeError):
        history.insert(index, [record('other')])
    assert list(history) == expected
