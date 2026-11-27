"""The default KPI baseline charges the EVs as the native BAU does, whatever the controller (#365).

Baseline version 1, the baseline of CityLearn 3.6.0 that removed the EV charging and added nothing back, was removed
in CityLearn 3.8.1 (#466).
"""

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent, RBCSmartPolicy
from citylearn.citylearn import CityLearnEnv

SCHEMA = Path(__file__).resolve().parent / 'data/minute_ev_demo/schema.json'


def _random_actions(env):
    """Seeded uniform random actions, so the EV is charged and discharged (V2G)."""

    # `env.action_space` builds new spaces at each access: seed and sample the same ones.
    spaces = list(env.action_space)

    for space in spaces:
        space.seed(0)

    return lambda observations: [space.sample().tolist() for space in spaces]


def _run(controller='bau', **kwargs):
    env = CityLearnEnv(str(SCHEMA), central_agent=True, random_seed=0, render_mode='none', **kwargs)

    if controller == 'random':
        predict = _random_actions(env)
    else:
        agent = (BusinessAsUsualAgent if controller == 'bau' else RBCSmartPolicy)(env)
        predict = lambda observations: agent.predict(observations, deterministic=True)

    observations, _ = env.reset(seed=0)

    while not env.terminated:
        observations, *_ = env.step(predict(observations))

    return env


def _without_storage_and_ev(building):
    """Net consumption without the storage devices and without the EV charging of the controlled run."""

    return np.asarray(building.net_electricity_consumption) - np.sum([
        building.cooling_storage_electricity_consumption,
        building.heating_storage_electricity_consumption,
        building.dhw_storage_electricity_consumption,
        building.electrical_storage_electricity_consumption,
        building.chargers_electricity_consumption,
    ], axis=0)


def _baseline_ev_charging(building):
    """The EV charging the baseline adds back."""

    return np.asarray(building.net_electricity_consumption_without_storage) - _without_storage_and_ev(building)


def _rows(kpis, pattern):
    rows = kpis[kpis['cost_function'].str.contains(pattern, regex=True)]
    return rows.set_index(['name', 'cost_function'])['value'].sort_index()


@pytest.fixture(scope='module')
def runs():
    envs = {
        'bau': _run('bau'),
        'rbc': _run('rbc'),
        'random': _run('random'),
    }
    kpis = {name: env.evaluate_v2() for name, env in envs.items()}
    yield envs, kpis

    for env in envs.values():
        env.close()


def test_baseline_adds_back_the_ev_charging_of_the_full_bau(runs):
    envs, _ = runs
    env = envs['bau']
    building = env.buildings[0]
    bau = env.run_business_as_usual_baseline().env.buildings[0]
    charging = np.asarray(bau.chargers_electricity_consumption)

    assert env.baseline_version == 2 and building.baseline_version == 2
    assert env.business_as_usual_ev_charge_target == 'full'
    assert charging.sum() > 1.0, 'the demo must charge its EV for this test to mean anything'
    np.testing.assert_allclose(_baseline_ev_charging(building), charging, rtol=0.0, atol=1.0e-6)
    np.testing.assert_allclose(
        building.net_electricity_consumption_without_storage_and_pv,
        np.asarray(building.net_electricity_consumption_without_storage) - np.asarray(building.solar_generation),
        rtol=0.0, atol=1.0e-6,
    )


def test_baseline_ev_charging_does_not_depend_on_the_controller_and_has_no_v2g(runs):
    envs, _ = runs
    charged = {name: np.asarray(envs[name].buildings[0].chargers_electricity_consumption) for name in ('bau', 'rbc', 'random')}

    # The controllers charge differently, and the random actions discharge the EV (V2G).
    assert not np.allclose(charged['bau'], charged['random'])
    assert charged['random'].min() < -1.0e-3, 'the random actions must use V2G for this test to mean anything'

    reference = _baseline_ev_charging(envs['bau'].buildings[0])
    assert reference.min() >= 0.0

    for name in ('rbc', 'random'):
        np.testing.assert_allclose(_baseline_ev_charging(envs[name].buildings[0]), reference, rtol=0.0, atol=1.0e-6)


def test_the_bau_baseline_is_its_control_without_the_battery(runs):
    envs, kpis = runs
    import_rows = '^district_energy_grid_total_import_baseline_kwh$'
    v2 = _rows(kpis['bau'], import_rows)
    assert len(v2) == 1

    # Under the BAU, the baseline is the control without the battery.
    control = _rows(kpis['bau'], '^district_energy_grid_total_import_control_kwh$')
    battery = float(np.sum(envs['bau'].buildings[0].electrical_storage_electricity_consumption))
    assert abs(float(v2.iloc[0]) - float(control.iloc[0])) <= abs(battery) + 1.0e-6


def test_baseline_keeps_the_full_charging_when_the_bau_charges_to_the_requested_soc(runs):
    envs, _ = runs
    env = _run('rbc', business_as_usual_ev_charge_target='requested')

    try:
        kpis = env.evaluate_v2()
        assert env.run_business_as_usual_baseline().ev_charge_target == 'requested'
        np.testing.assert_allclose(
            _baseline_ev_charging(env.buildings[0]), _baseline_ev_charging(envs['bau'].buildings[0]), rtol=0.0, atol=1.0e-6
        )
        assert len(_rows(kpis, '_business_as_usual_')) > 0
    finally:
        env.close()


def test_setting_the_version_on_the_env_reaches_its_buildings(runs):
    envs, _ = runs
    env = envs['rbc']
    building = env.buildings[0]
    keeps = np.array(building.net_electricity_consumption_without_storage, copy=True)

    env.baseline_version = '2'
    assert building.baseline_version == 2
    assert env.get_metadata()['baseline_version'] == 2

    for value in (1, 2.0, True):
        with pytest.raises(ValueError, match='baseline_version must be 2.*Version 1 was removed in CityLearn 3.8.1'):
            env.baseline_version = value

    assert env.baseline_version == 2 and building.baseline_version == 2
    np.testing.assert_array_equal(building.net_electricity_consumption_without_storage, keeps)


def test_a_building_with_chargers_needs_its_environment_for_the_baseline(runs):
    envs, _ = runs
    building = envs['rbc'].buildings[0]
    source = building._baseline_ev_charging_source

    building._baseline_ev_charging_source = None
    try:
        with pytest.raises(ValueError, match='only an environment can supply'):
            building.net_electricity_consumption_without_storage
    finally:
        building._baseline_ev_charging_source = source


def test_copies_take_the_ev_charging_from_the_right_environment(runs):
    envs, _ = runs
    env = envs['rbc']
    building = env.buildings[0]

    # A building copied on its own (a member cloned by a topology event) keeps its environment.
    assert deepcopy(building)._baseline_ev_charging_source.env is env

    # A copied environment gives the same baseline from its own BAU run.
    copied = deepcopy(env)
    try:
        assert copied.buildings[0]._baseline_ev_charging_source.env is copied
        np.testing.assert_array_equal(
            copied.buildings[0].net_electricity_consumption_without_storage, building.net_electricity_consumption_without_storage
        )
    finally:
        copied.close()


def test_schema_key_selects_the_version_and_the_argument_wins():
    schema = json.loads(SCHEMA.read_text())
    schema['root_directory'] = str(SCHEMA.parent)
    schema['baseline_version'] = '2'
    env = CityLearnEnv(schema, central_agent=True, render_mode='none')
    assert env.baseline_version == 2 and env.buildings[0].baseline_version == 2
    env.close()

    schema['baseline_version'] = 1
    env = CityLearnEnv(schema, central_agent=True, render_mode='none', baseline_version=2)
    assert env.baseline_version == 2 and env.buildings[0].baseline_version == 2
    env.close()

    with pytest.raises(ValueError, match='baseline_version must be 2, got 1. Version 1 was removed in CityLearn 3.8.1'):
        CityLearnEnv(schema, central_agent=True, render_mode='none')
