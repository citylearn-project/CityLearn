"""Time-varying available grid import power (issue #119).

The fixture is a single-phase building on 15-minute steps with a 1 kW fixed load and one 7.2 kW EV
charger whose vehicle is connected for the first four steps. An episode of five time steps
has four transitions. The import limit in force is the smaller
of the static `import_kw` and the series value; a blank value falls back to the static limit.
"""

from copy import deepcopy
import json
import math
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal import grid_availability

SOURCE = Path(__file__).parent/'data'/'minute_ev_demo'
STATIC_IMPORT_KW = 20.0
FIXED_LOAD_KW = 1.0
CHARGER_KW = 7.2
SERIES = [20.0, 3.0, 0.0, np.nan, 2.0, 2.0, 2.0, 2.0]


def make_schema(tmp_path, series=SERIES, static_import_kw=STATIC_IMPORT_KW, config=None, frame=None):
    dataset = tmp_path/'grid_limited'
    shutil.copytree(SOURCE, dataset)
    schema = json.loads((dataset/'schema.json').read_text())
    schema['root_directory'] = str(dataset)
    schema['actions']['electrical_storage']['active'] = False
    building = schema['buildings']['Building_1']
    limits = {} if static_import_kw is None else {'total': {'import_kw': static_import_kw}}
    building['electrical_service'] = {
        'mode': 'single_phase',
        'limits': limits,
        grid_availability.CONFIG_KEY: (
            {'filename': 'available_grid_power.csv', 'column': 'Building_1'} if config is None else config),
    }
    charger = building['chargers']['charger_1_1']
    charger.update(noise_std=0.)
    charger['attributes'].update(min_charging_power=0.0, max_charging_power=CHARGER_KW)
    schema['electric_vehicles_def']['Electric_Vehicle_1']['battery']['attributes'] = dict(
        capacity=60., nominal_power=11., initial_soc=.2, efficiency=1.,
        depth_of_discharge=1., loss_coefficient=0., capacity_loss_coefficient=0.,
        power_efficiency_curve=[[0., 1.], [1., 1.]], capacity_power_curve=[[0., 1.], [1., 1.]])
    load = pd.read_csv(dataset/'Building_1.csv')
    load['non_shiftable_load'] = FIXED_LOAD_KW/4
    load['solar_generation'] = 0.0
    load.to_csv(dataset/'Building_1.csv', index=False)

    if frame is None:
        frame = pd.DataFrame({'Building_1': series, 'Building_2': [99.0]*len(series)})

    frame.to_csv(dataset/'available_grid_power.csv', index=False)

    return schema


def make_env(schema, **kwargs):
    kwargs = {'central_agent': True, 'random_seed': 0, 'render_mode': 'none',
              'export_kpis_on_episode_end': False, **kwargs}
    return CityLearnEnv(schema, **kwargs)


def expected_limit(value):
    return STATIC_IMPORT_KW if math.isnan(value) else min(STATIC_IMPORT_KW, value)


def test_charger_is_curtailed_to_the_available_grid_power_at_each_step(tmp_path):
    env = make_env(make_schema(tmp_path), episode_time_steps=5)

    try:
        env.reset(seed=0)
        building = env.buildings[0]
        charger = building.electric_vehicle_chargers[0]
        delivered_kw = []

        for t in range(4):
            assert building.available_grid_power == pytest.approx(expected_limit(SERIES[t]))
            env.step([[1.0]])
            delivered_kw.append(float(charger.electricity_consumption[t])*4)

        # Full power, (3 - 1) kW, nothing at 0 kW, then the static limit for a blank value.
        assert delivered_kw == pytest.approx([CHARGER_KW, 2.0, 0.0, CHARGER_KW], abs=1e-5)
        imports_kw = np.asarray(building.net_electricity_consumption[:4])*4
        assert imports_kw == pytest.approx([CHARGER_KW + 1.0, 3.0, 1.0, CHARGER_KW + 1.0], abs=1e-5)

    finally:
        env.close()


def test_observation_reports_the_limit_and_headroom_follows_it(tmp_path):
    env = make_env(make_schema(tmp_path), episode_time_steps=5)

    try:
        observations, _ = env.reset(seed=0)
        building = env.buildings[0]
        assert grid_availability.OBSERVATION_NAME in building.active_observations
        index = env.observation_names[0].index(grid_availability.OBSERVATION_NAME)
        headroom_index = env.observation_names[0].index('charging_building_headroom_kw')
        seen, headroom = [], []

        for t in range(4):
            seen.append(observations[0][index])
            headroom.append(observations[0][headroom_index])
            observations, *_ = env.step([[0.0]])

        # The limit is exogenous and observed for the coming interval. Headroom is endogenous: like
        # every settled quantity it describes the last executed interval, so it follows the limit
        # that was in force then (the reset observation uses the first interval).
        assert seen == pytest.approx([expected_limit(v) for v in SERIES[:4]])
        settled = [SERIES[0]] + SERIES[:3]
        assert headroom == pytest.approx([expected_limit(v) - FIXED_LOAD_KW for v in settled], abs=1e-5)

        # The observation space spans every limit in the simulation period.
        low, high = building.estimate_observation_space_limits()
        delta = building.observation_space_limit_delta
        assert low[grid_availability.OBSERVATION_NAME] + delta == pytest.approx(0.0)
        assert high[grid_availability.OBSERVATION_NAME] - delta == pytest.approx(STATIC_IMPORT_KW)

    finally:
        env.close()


def test_observation_can_be_disabled(tmp_path):
    schema = make_schema(tmp_path)
    schema['buildings']['Building_1']['electrical_service']['observations'] = {
        grid_availability.OBSERVATION_NAME: False}
    env = make_env(schema, episode_time_steps=4)

    try:
        env.reset(seed=0)
        assert grid_availability.OBSERVATION_NAME not in env.buildings[0].active_observations
        # The limit still applies.
        assert env.buildings[0].electrical_service_import_limit_kw(2) == pytest.approx(0.0)

    finally:
        env.close()


def test_service_violation_kpi_uses_the_limit_in_force_at_each_step(tmp_path):
    env = make_env(make_schema(tmp_path), episode_time_steps=5)

    try:
        env.reset(seed=0)

        for _ in range(4):
            env.step([[1.0]])

        metrics = env._kpi_service._compute_phase_metrics(env.buildings[0], t_start=0, t_final=3)
        # Only the 0 kW step leaves load above the limit: 1 kW for a quarter hour.
        assert metrics['electrical_service_violation_total_kwh'] == pytest.approx(0.25, abs=1e-6)
        assert metrics['electrical_service_violation_time_step_count'] == 1.0

    finally:
        env.close()


def test_deferrable_feasibility_checks_the_limit_at_each_future_step(tmp_path):
    env = make_env(make_schema(tmp_path), episode_time_steps=4)

    try:
        env.reset(seed=0)
        ops = env.buildings[0]._ops_service
        assert ops._electrical_service_allows(5.0, {'L1': 5.0}, 0)
        assert not ops._electrical_service_allows(5.0, {'L1': 5.0}, 1)
        assert not ops._electrical_service_allows(0.5, {'L1': 0.5}, 2)
        assert ops._electrical_service_allows(5.0, {'L1': 5.0}, 3)

    finally:
        env.close()


def test_series_follows_the_episode_window(tmp_path):
    env = make_env(make_schema(tmp_path), episode_time_steps=4)

    try:
        env.reset(seed=0)
        env.reset(seed=0)  # second split: file rows 4-7
        building = env.buildings[0]
        assert building.episode_tracker.episode_start_time_step == 4
        assert [building.electrical_service_import_limit_kw(t) for t in range(4)] == pytest.approx([2.0]*4)

    finally:
        env.close()


def test_column_defaults_to_the_building_name_then_the_generic_name(tmp_path):
    frame = pd.DataFrame({'available_grid_power': [5.0]*8})
    env = make_env(make_schema(tmp_path, config='available_grid_power.csv', frame=frame), episode_time_steps=4)

    try:
        env.reset(seed=0)
        assert env.buildings[0].available_grid_power == pytest.approx(5.0)

    finally:
        env.close()


def test_series_without_static_limit_needs_complete_values(tmp_path):
    with pytest.raises(ValueError, match='missing values'):
        make_env(make_schema(tmp_path/'a', static_import_kw=None), episode_time_steps=4)

    complete = [4.0]*8
    env = make_env(make_schema(tmp_path/'b', series=complete, static_import_kw=None), episode_time_steps=4)

    try:
        env.reset(seed=0)
        assert env.buildings[0].electrical_service_import_limit_kw(0) == pytest.approx(4.0)

    finally:
        env.close()


@pytest.mark.parametrize('values,match', [
    ([-1.0] + [5.0]*7, 'non-negative'),
    ([np.inf] + [5.0]*7, 'infinite'),
])
def test_invalid_series_values_are_rejected(tmp_path, values, match):
    with pytest.raises(ValueError, match=match):
        make_env(make_schema(tmp_path, series=values), episode_time_steps=4)


@pytest.mark.parametrize('config,error,match', [
    ({'filename': 'missing.csv'}, FileNotFoundError, 'not found'),
    ({'filename': 'available_grid_power.csv', 'column': 'nope'}, ValueError, "no column 'nope'"),
    ({'filename': 'available_grid_power.csv', 'columns': 'x'}, ValueError, 'unknown keys'),
    (5, ValueError, 'file name or a mapping'),
])
def test_invalid_configuration_is_rejected(tmp_path, config, error, match):
    with pytest.raises(error, match=match):
        make_env(make_schema(tmp_path, config=config), episode_time_steps=4)


def test_static_limits_are_returned_unchanged_without_a_series(tmp_path):
    schema = make_schema(tmp_path)
    del schema['buildings']['Building_1']['electrical_service'][grid_availability.CONFIG_KEY]
    env = make_env(deepcopy(schema), episode_time_steps=4)

    try:
        env.reset(seed=0)
        building = env.buildings[0]
        total = building._electrical_service_limits['total']
        assert grid_availability.total_limits_at(building, total, 2) is total
        assert building.available_grid_power is None
        assert grid_availability.OBSERVATION_NAME not in building.active_observations
        assert building.electrical_service_import_limit_kw(2) == STATIC_IMPORT_KW

    finally:
        env.close()


def test_rule_policies_plan_against_the_observed_limit(tmp_path):
    from citylearn.agents._rule_engine import RulePolicyBase

    policy = RulePolicyBase({'simulator': {'schema': make_schema(tmp_path)}})
    policy._agent_buildings = {0: 'Building_1'}
    policy._current_base_power_kw = lambda obs, obs_map: FIXED_LOAD_KW
    headroom = policy._computed_current_service_headroom_kw

    # Without the observation the policy only knows the static connection capacity.
    assert headroom(0, np.array([0.0]), {}, 'building', False) == pytest.approx(STATIC_IMPORT_KW - FIXED_LOAD_KW)
    assert headroom(0, np.array([3.0]), {grid_availability.OBSERVATION_NAME: 0}, 'building', False) \
        == pytest.approx(3.0 - FIXED_LOAD_KW)
    # A limit above the static capacity cannot raise it.
    assert headroom(0, np.array([50.0]), {grid_availability.OBSERVATION_NAME: 0}, 'building', False) \
        == pytest.approx(STATIC_IMPORT_KW - FIXED_LOAD_KW)
