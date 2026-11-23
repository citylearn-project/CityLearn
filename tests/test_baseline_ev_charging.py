"""The default KPI baseline keeps the EV charging of the controlled run (#365)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.citylearn import CityLearnEnv

SCHEMA = Path(__file__).resolve().parent / 'data/minute_ev_demo/schema.json'


def _run(**kwargs):
    env = CityLearnEnv(str(SCHEMA), central_agent=True, random_seed=0, render_mode='none', **kwargs)
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)

    while not env.terminated:
        observations, *_ = env.step(agent.predict(observations, deterministic=True))

    return env


def _storage(building):
    return np.sum([
        building.cooling_storage_electricity_consumption,
        building.heating_storage_electricity_consumption,
        building.dhw_storage_electricity_consumption,
        building.electrical_storage_electricity_consumption,
    ], axis=0)


def _rows(kpis, pattern):
    rows = kpis[kpis['cost_function'].str.contains(pattern, regex=True)]
    return rows.set_index(['name', 'cost_function'])['value'].sort_index()


@pytest.fixture(scope='module')
def runs():
    envs = {version: _run(baseline_version=version) for version in (1, 2)}
    kpis = {version: env.evaluate_v2() for version, env in envs.items()}
    yield envs, kpis

    for env in envs.values():
        env.close()


def test_baseline_keeps_the_ev_charging_and_removes_the_storage(runs):
    envs, _ = runs
    env = envs[2]
    building = env.buildings[0]
    chargers = np.asarray(building.chargers_electricity_consumption)

    assert env.baseline_version == 2 and building.baseline_version == 2
    assert chargers.sum() > 1.0, 'the demo must charge its EV for this test to mean anything'
    assert np.abs(np.asarray(building.electrical_storage_electricity_consumption)).sum() > 0.0
    np.testing.assert_allclose(
        building.net_electricity_consumption_without_storage,
        np.asarray(building.net_electricity_consumption) - _storage(building),
        rtol=0.0, atol=1.0e-6,
    )
    np.testing.assert_allclose(
        building.net_electricity_consumption_without_storage_and_pv,
        np.asarray(building.net_electricity_consumption_without_storage) - np.asarray(building.solar_generation),
        rtol=0.0, atol=1.0e-6,
    )


def test_baseline_version_1_removes_the_ev_charging_as_in_3_6_0(runs):
    envs, _ = runs
    building = envs[1].buildings[0]

    np.testing.assert_allclose(
        building.net_electricity_consumption_without_storage,
        np.asarray(building.net_electricity_consumption) - _storage(building)
        - np.asarray(building.chargers_electricity_consumption),
        rtol=0.0, atol=1.0e-6,
    )


def test_simulation_and_bau_rows_do_not_depend_on_the_baseline_version(runs):
    envs, kpis = runs

    for name in ('net_electricity_consumption', 'chargers_electricity_consumption'):
        np.testing.assert_array_equal(getattr(envs[1].buildings[0], name), getattr(envs[2].buildings[0], name))

    bau = '_business_as_usual|_delta_to_business_as_usual_|_to_business_as_usual_ratio|_control_'
    v1, v2 = _rows(kpis[1], bau), _rows(kpis[2], bau)
    assert len(v1) > 0
    pd.testing.assert_series_equal(v1, v2)

    # The baseline rows do change: under the BAU the version 2 baseline differs from the control only by the
    # battery, so it imports the EV charging the version 1 baseline left out.
    import_rows = '^district_energy_grid_total_import_baseline_kwh$'
    v1, v2 = _rows(kpis[1], import_rows), _rows(kpis[2], import_rows)
    assert len(v1) == 1
    assert (v2 > v1 + 1.0).all()

    # Under the BAU, the version 2 baseline is the control without the battery.
    control = _rows(kpis[2], '^district_energy_grid_total_import_control_kwh$')
    building = envs[2].buildings[0]
    battery = float(np.sum(building.electrical_storage_electricity_consumption))
    assert abs(float(v2.iloc[0]) - float(control.iloc[0])) <= abs(battery) + 1.0e-6


def test_setting_the_version_on_the_env_reaches_its_buildings(runs):
    envs, _ = runs
    env = envs[2]
    building = env.buildings[0]
    keeps = np.array(building.net_electricity_consumption_without_storage, copy=True)

    env.baseline_version = 1
    try:
        assert building.baseline_version == 1
        np.testing.assert_allclose(
            building.net_electricity_consumption_without_storage,
            keeps - np.asarray(building.chargers_electricity_consumption), rtol=0.0, atol=1.0e-6,
        )
        assert env.get_metadata()['baseline_version'] == 1
    finally:
        env.baseline_version = 2

    np.testing.assert_array_equal(building.net_electricity_consumption_without_storage, keeps)


def test_schema_key_selects_the_version_and_the_argument_wins():
    import json

    schema = json.loads(SCHEMA.read_text())
    schema['root_directory'] = str(SCHEMA.parent)
    schema['baseline_version'] = 1
    env = CityLearnEnv(schema, central_agent=True, render_mode='none')
    assert env.baseline_version == 1 and env.buildings[0].baseline_version == 1
    env.close()

    env = CityLearnEnv(schema, central_agent=True, render_mode='none', baseline_version=2)
    assert env.baseline_version == 2 and env.buildings[0].baseline_version == 2
    env.close()
