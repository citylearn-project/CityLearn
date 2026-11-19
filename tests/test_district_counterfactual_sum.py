"""The district counterfactual sum matches the pandas reduction it replaces, bit for bit."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from test_deferrable_appliance_integration import _zero_entity_payload

ROOT = Path(__file__).resolve().parents[1]
COUNTERFACTUAL_PROPERTIES = [
    f'net_electricity_consumption{kind}_without_storage{suffix}'
    for suffix in ('_and_partial_load_and_pv', '_and_partial_load', '_and_pv', '')
    for kind in ('_emission', '_cost', '')
]


def _pandas_sum(rows):
    return pd.DataFrame(rows).sum(axis=0, min_count=1).to_numpy()


def _assert_bit_identical(actual, expected):
    assert actual.dtype == expected.dtype
    assert actual.shape == expected.shape
    assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize('members', [1, 7, 8, 17, 130])
@pytest.mark.parametrize('dtypes', [('float32',), ('float64',), ('float32', 'float64')])
@pytest.mark.parametrize('missing', ['none', 'some', 'all_members_at_a_step'])
def test_member_sum_matches_pandas_min_count_sum(members, dtypes, missing):
    # 8 or more members switch NumPy to pairwise summation, so the reduction order matters.
    rng = np.random.default_rng(members)
    rows = [rng.normal(0.0, 5.0, 49).astype(dtypes[i % len(dtypes)]) for i in range(members)]
    if missing != 'none':
        for row in rows[:max(1, members // 2)]:
            row[::3] = np.nan
    if missing == 'all_members_at_a_step':
        for row in rows:
            row[4] = np.nan

    actual = CityLearnEnv._sum_member_rows(rows)

    _assert_bit_identical(actual, _pandas_sum(rows))
    assert np.isnan(actual[4]) == (missing == 'all_members_at_a_step')


def test_member_sum_rejects_ragged_rows():
    # pandas would pad the shorter row with NaN and return float64; the counterfactual sum pads
    # departed members with zeros in their own dtype before summing, so ragged rows are an error.
    rows = [np.array([1.5, np.nan, 3.0], dtype='float32'), np.array([2.5, np.nan], dtype='float32')]

    with pytest.raises(ValueError):
        CityLearnEnv._sum_member_rows(rows)


def _static_env():
    return CityLearnEnv(
        str(ROOT / 'data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json'),
        episode_time_steps=6, random_seed=0,
    )


def _dynamic_env():
    path = ROOT / 'data/datasets/citylearn_three_phase_dynamic_topology_demo/schema.json'
    schema = json.loads(path.read_text())
    schema['root_directory'] = str(path.parent)
    schema['topology_events'] = [
        dict(id='join', time_step=2, operation='add_member', target_member_id='Building_18'),
        dict(id='leave', time_step=3, operation='remove_member', target_member_id='Building_6'),
        dict(id='rejoin', time_step=5, operation='add_member', target_member_id='Building_6'),
    ]
    return CityLearnEnv(schema, episode_time_steps=7, random_seed=0)


@pytest.mark.parametrize('make_env', [_static_env, _dynamic_env], ids=['static', 'dynamic'])
def test_district_counterfactual_properties_match_pandas_reduction(make_env, monkeypatch):
    env = make_env()
    try:
        env.reset(seed=0)
        while not env.terminated:
            if env.interface == 'entity':
                env.step(_zero_entity_payload(env))
            else:
                env.step([np.zeros(space.shape, dtype='float32') for space in env.action_space])

        actual = {name: getattr(env, name) for name in COUNTERFACTUAL_PROPERTIES}
        monkeypatch.setattr(CityLearnEnv, '_sum_member_rows', staticmethod(_pandas_sum))
        for name in COUNTERFACTUAL_PROPERTIES:
            _assert_bit_identical(actual[name], getattr(env, name))
    finally:
        env.close()
