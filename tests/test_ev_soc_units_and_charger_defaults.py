"""Regression tests for #368 (SOC unit of charger files) and #369 (charger defaults and attribute names)."""

import copy
import warnings

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.data import ChargerSimulation, DataSet
from citylearn.electric_vehicle_charger import Charger

EV_DATASET = 'citylearn_challenge_2022_phase_all_plus_evs'


@pytest.fixture(scope='module')
def ev_schema():
    return DataSet().get_schema(EV_DATASET)


def _charger(env, building, index=0):
    return [b for b in env.buildings if b.name == building][0].electric_vehicle_chargers[index]


def _run_bau(schema, **kwargs):
    env = CityLearnEnv(schema, interface='flat', render_mode='none', **kwargs)
    observations, _ = env.reset()
    agent = BusinessAsUsualAgent(env)
    done = False

    while not done:
        observations, _, terminated, truncated, _ = env.step(agent.predict(observations))
        done = terminated or truncated

    return env


# #368 ------------------------------------------------------------------------------------------


@pytest.mark.parametrize('physics_version, expected_unit', [(2, 'percent'), (1, 'per_value')])
def test_one_percent_arrival_soc_is_not_read_as_full(ev_schema, physics_version, expected_unit):
    """charger_12_1 gives an arrival SOC of 1 (1 %) at steps 4167-4169; the EV connects at 4170.

    The rows of this window hold no value above 1, so only a unit decided from the whole file reads
    them as percent.
    """

    env = _run_bau(
        copy.deepcopy(ev_schema), simulation_start_time_step=4160, simulation_end_time_step=4190,
        physics_version=physics_version,
    )
    charger = _charger(env, 'Building_12')
    raw = pd.read_csv(f"{env.schema['root_directory']}/charger_12_1.csv").iloc[4160:4191]
    assert raw['electric_vehicle_estimated_soc_arrival'].iloc[7:10].tolist() == [1.0, 1.0, 1.0]
    assert raw['electric_vehicle_estimated_soc_arrival'].max() <= 1.0
    assert charger.charger_simulation._soc_units['electric_vehicle_estimated_soc_arrival'] == expected_unit

    ev = charger.past_connected_evs[10]
    charged = float(np.sum(charger.electricity_consumption[:30]))

    if physics_version >= 2:
        assert float(ev.battery.soc[10]) < 0.2
        assert charged > 40.0
    else:
        # Physics version 1 keeps the 3.6.0 reading: the EV arrives full and is not charged.
        assert float(ev.battery.soc[10]) == pytest.approx(1.0)
        assert charged == pytest.approx(0.0)

    env.close()


def test_schema_can_declare_the_soc_unit(ev_schema):
    schema = copy.deepcopy(ev_schema)
    schema['buildings']['Building_12']['chargers']['charger_12_1']['soc_unit'] = 'fraction'
    env = CityLearnEnv(
        schema, interface='flat', render_mode='none', simulation_start_time_step=4160, simulation_end_time_step=4190,
    )
    simulation = _charger(env, 'Building_12').charger_simulation
    assert set(simulation._soc_units.values()) == {'fraction'}
    assert simulation.electric_vehicle_estimated_soc_arrival[7] == pytest.approx(1.0)
    env.close()

    schema['buildings']['Building_12']['chargers']['charger_12_1']['soc_unit'] = '%'
    with pytest.raises(ValueError, match='charger_12_1.soc_unit'):
        CityLearnEnv(schema, interface='flat', render_mode='none', episode_time_steps=24)


def test_fraction_files_with_rounding_above_one_stay_fractions():
    assert ChargerSimulation._soc_series_unit([0.2, 1.0000000000000013, np.nan, -0.1]) == 'fraction'
    assert ChargerSimulation._soc_series_unit([0.2, 1.0], [0.5, 80.0]) == 'percent'
    assert ChargerSimulation._soc_series_unit([np.nan, -1.0]) == 'fraction'


# #369 ------------------------------------------------------------------------------------------


def _schema_with_charger_5_1(ev_schema, attributes):
    schema = copy.deepcopy(ev_schema)
    schema['buildings']['Building_5']['chargers']['charger_5_1']['attributes'] = attributes
    return schema


def _run_v2g(schema, **kwargs):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        env = CityLearnEnv(schema, interface='flat', render_mode='none', episode_time_steps=24, **kwargs)

    observations, _ = env.reset()
    done = False

    while not done:
        actions = []

        for names, space in zip(env.action_names, env.action_space):
            action = np.zeros(space.shape, dtype='float32')
            action[[i for i, n in enumerate(names) if n == 'electric_vehicle_storage_charger_5_1']] = -1.0
            actions.append(np.clip(action, space.low, space.high))

        observations, _, terminated, truncated, _ = env.step(actions)
        done = terminated or truncated

    messages = [str(w.message) for w in caught if 'charger_5_1' in str(w.message)]
    return env, _charger(env, 'Building_5'), messages


def test_omitted_discharging_power_means_no_v2g(ev_schema):
    env, charger, messages = _run_v2g(_schema_with_charger_5_1(ev_schema, {'max_charging_power': 7.4}))
    assert (charger.max_charging_power, charger.max_discharging_power) == (7.4, 0.0)
    assert float(np.min(charger.electricity_consumption[:env.time_step])) >= 0.0
    assert any('max_discharging_power=0 kW' in m and 'efficiency=1.0' in m for m in messages)
    env.close()


def test_physics_v1_keeps_the_50_kw_defaults(ev_schema):
    env, charger, messages = _run_v2g(
        _schema_with_charger_5_1(ev_schema, {'max_charging_power': 7.4}), physics_version=1,
    )
    assert (charger.max_charging_power, charger.max_discharging_power) == (7.4, 50.0)
    assert float(np.min(charger.electricity_consumption[:env.time_step])) < -7.4
    assert any('max_discharging_power=50 kW' in m for m in messages)
    env.close()


def test_nominal_power_is_the_default_charging_power(ev_schema):
    env, charger, _ = _run_v2g(_schema_with_charger_5_1(ev_schema, {'nominal_power': 7.4, 'charger_type': 0}))
    assert (charger.nominal_power, charger.max_charging_power, charger.max_discharging_power) == (7.4, 7.4, 0.0)
    assert charger.charger_type == 0
    env.close()


def test_misspelt_charger_attributes_raise(ev_schema):
    schema = _schema_with_charger_5_1(ev_schema, {'max_charge_power': 7.4, 'max_discharge_power': 0.0})

    with pytest.raises(ValueError) as error:
        CityLearnEnv(schema, interface='flat', render_mode='none', episode_time_steps=24)

    message = str(error.value)
    assert 'buildings.Building_5.chargers.charger_5_1.attributes' in message
    assert "'max_charge_power' (did you mean 'max_charging_power'?)" in message
    assert "'max_discharge_power' (did you mean 'max_discharging_power'?)" in message


def test_charger_constructor_rejects_unknown_arguments():
    tracker = EpisodeTracker(0, 1)

    with pytest.raises(TypeError, match="max_discharge_power"):
        Charger(episode_tracker=tracker, charger_simulation=None, charger_id='c', max_discharge_power=0.0)

    charger = Charger(episode_tracker=tracker, charger_simulation=None, charger_id='c')
    assert (charger.max_charging_power, charger.max_discharging_power, charger.efficiency) == (50.0, 0.0, 1.0)


def test_bundled_chargers_set_every_power_limit(ev_schema):
    """The bundled chargers rely on no default, so #369 does not change their results."""

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        env = CityLearnEnv(copy.deepcopy(ev_schema), interface='flat', render_mode='none', episode_time_steps=24)

    assert not [w for w in caught if 'chargers.' in str(w.message)]
    chargers = [c for b in env.buildings for c in b.electric_vehicle_chargers]
    assert chargers and all(c.max_discharging_power > 0 and c.nominal_power == c.max_charging_power for c in chargers)
    env.close()


def test_stray_value_above_one_in_a_ratio_column_warns(ev_schema, tmp_path):
    """One value just above 1 makes a ratio column percent; the loader says so."""

    schema = copy.deepcopy(ev_schema)
    charger = schema['buildings']['Building_5']['chargers']['charger_5_1']
    frame = pd.read_csv(f"{schema['root_directory']}/{charger['charger_simulation']}")
    column = 'electric_vehicle_estimated_soc_arrival'
    valid = frame[column] > 0
    frame.loc[valid, column] = frame.loc[valid, column] / 100.0
    frame.loc[frame.index[valid][0], column] = 1.00001
    path = tmp_path / 'charger_5_1_ratio.csv'
    frame.to_csv(path, index=False)
    charger['charger_simulation'] = str(path)

    with pytest.warns(UserWarning, match=f"{column}.*read as percent"):
        env = CityLearnEnv(schema, interface='flat', render_mode='none', episode_time_steps=24)

    env.close()


def test_misspelt_soc_unit_key_warns(ev_schema):
    schema = copy.deepcopy(ev_schema)
    schema['buildings']['Building_12']['chargers']['charger_12_1']['soc_units'] = 'percent'

    with pytest.warns(UserWarning, match=r"'soc_units' \(did you mean 'soc_unit'\?\)"):
        env = CityLearnEnv(schema, interface='flat', render_mode='none', episode_time_steps=24)

    env.close()


class GainCharger(Charger):
    def __init__(self, *args, gain: float = 1.0, **kwargs):
        self.gain = gain
        super().__init__(*args, **kwargs)


def test_charger_subclass_keyword_only_arguments_are_valid_attributes():
    from citylearn.internal.loading_components import charger_power_attributes

    attributes = {'gain': 2.0, 'max_charging_power': 7.4, 'max_discharging_power': 0.0, 'efficiency': 0.95}
    assert 'gain' in GainCharger._attribute_names()
    assert charger_power_attributes(GainCharger, attributes, 'charger', 2) == attributes
    charger = GainCharger(episode_tracker=EpisodeTracker(0, 1), charger_simulation=None, charger_id='c', **attributes)
    assert charger.gain == 2.0

    with pytest.raises(ValueError, match="'gian' \\(did you mean 'gain'\\?\\)"):
        charger_power_attributes(GainCharger, {'gian': 2.0}, 'charger', 2)


def test_efficiency_warning_only_when_efficiency_is_used():
    from citylearn.internal.loading_components import charger_power_attributes

    curve = [[0.0, 0.9], [1.0, 0.95]]
    limits = {'max_charging_power': 7.4, 'max_discharging_power': 7.4}

    with warnings.catch_warnings():
        warnings.simplefilter('error')
        charger_power_attributes(
            Charger, {**limits, 'charge_efficiency_curve': curve, 'discharge_efficiency_curve': curve}, 'c', 2,
        )
        charger_power_attributes(
            Charger, {'max_charging_power': 7.4, 'max_discharging_power': 0.0, 'charge_efficiency_curve': curve},
            'c', 2,
        )

    with pytest.warns(UserWarning, match='efficiency=1.0'):
        charger_power_attributes(Charger, {**limits, 'charge_efficiency_curve': curve}, 'c', 2)
