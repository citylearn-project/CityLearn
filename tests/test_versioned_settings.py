"""One rule for every versioned setting (#469) and the versions removed in CityLearn 3.8.1 (#466).

`physics_version`, `baseline_version`, `random_stream_version`, the reward `version` and
`community_market.settlement_version` were parsed differently: `2.0` was accepted by three and rejected by two,
and `"2"` the other way round. All five now accept an integer or a string of digits and reject floats and
booleans.
"""

import numpy as np
import pytest

from citylearn.internal.baseline_version import resolve_baseline_version
from citylearn.internal.market_config import parse_community_market
from citylearn.internal.physics_version import resolve_physics_version
from citylearn.internal.versions import parse_version
from citylearn.random_streams import parse_random_stream_version
from citylearn.reward_function import ComfortReward, Electric_Vehicles_Reward_Function, SolarPenaltyAndComfortReward


def _settlement(value):
    return parse_community_market({'settlement_version': value})['settlement_version']


# Each setting, the canonical result of version 2, and the path its error names.
SETTINGS = {
    'physics_version': (resolve_physics_version, 2, 'physics_version'),
    'baseline_version': (resolve_baseline_version, 2, 'baseline_version'),
    'random_stream_version': (parse_random_stream_version, 'v2', 'random_stream_version'),
    'comfort_reward_version': (lambda v: ComfortReward(None, version=v).version, 2, 'ComfortReward version'),
    'ev_reward_version': (
        lambda v: Electric_Vehicles_Reward_Function(None, version=v).version, 2, 'Electric_Vehicles_Reward_Function version',
    ),
    'solar_comfort_reward_version': (
        lambda v: SolarPenaltyAndComfortReward(None, version=v).version, 2, 'ComfortReward version',
    ),
    'settlement_version': (_settlement, 2, 'community_market.settlement_version'),
}


@pytest.mark.parametrize('setting', SETTINGS)
@pytest.mark.parametrize('value', [2, '2', ' 2 ', np.int64(2)])
def test_every_setting_accepts_an_integer_or_a_string_of_digits(setting, value):
    parse, expected, _ = SETTINGS[setting]
    assert parse(value) == expected


@pytest.mark.parametrize('setting', SETTINGS)
@pytest.mark.parametrize('value', [2.0, np.float64(2.0), True, False, np.bool_(True), '2.0', '', 'two', [2], 3, -2])
def test_every_setting_rejects_floats_booleans_and_other_values(setting, value):
    parse, _, path = SETTINGS[setting]
    with pytest.raises(ValueError, match=f'{path} must be'):
        parse(value)


@pytest.mark.parametrize('setting', SETTINGS)
def test_every_setting_defaults_when_omitted(setting):
    parse, expected, _ = SETTINGS[setting]
    assert parse(None) == (1 if setting == 'settlement_version' else expected)


def test_settlement_version_1_is_still_supported():
    assert _settlement(1) == 1
    assert _settlement('1') == 1


@pytest.mark.parametrize('setting', [s for s in SETTINGS if s != 'settlement_version'])
def test_version_1_of_the_3_6_0_settings_was_removed(setting):
    parse, _, path = SETTINGS[setting]
    removed = 'v1' if setting == 'random_stream_version' else 1
    with pytest.raises(ValueError, match=f'{path} must be .*, got .*Version .*1.* was removed in CityLearn 3\\.8\\.1; '
                                         'CityLearn 3\\.7 reproduces CityLearn 3\\.6\\.0'):
        parse(removed)


def test_parse_version_names_the_accepted_values():
    with pytest.raises(ValueError, match=r"^setting must be one of 1, 2, got 3\.$"):
        parse_version(3, (1, 2), 'setting')
    with pytest.raises(ValueError, match=r"^setting must be 'v2', got 'v3'\.$"):
        parse_version('v3', (2,), 'setting', prefix='v')
    assert parse_version(None, (1, 2), 'setting') == 2
    assert parse_version(None, (1, 2), 'setting', default=1) == 1
    assert parse_version('V2', (2,), 'setting', prefix='v') == 'v2'
    # A prefix is accepted only by the settings that have one.
    with pytest.raises(ValueError):
        parse_version('v2', (2,), 'setting')
