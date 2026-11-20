"""Physics version 2 corrections to the electrical-service limit and deferrable starts (tracking issue #226, theme 4).

#231: headroom was allocated to requests that devices cannot draw, curtailing the other devices.
#230: headroom was allocated before thermal storage charging, so import could exceed the limit unrecorded.
#232: deferrable start feasibility used the realised future outage, load and PV.

Each test reproduces its issue under physics version 1, which keeps the behaviour of CityLearn 3.6.0, and checks
the correction under version 2.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'datasets'
MINUTE_DATASET = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'


def _actions(env: CityLearnEnv, **prefixes: float) -> list:
    names = env.action_names[0]
    actions = np.zeros(len(names), dtype='float32')
    for prefix, value in prefixes.items():
        for index, name in enumerate(names):
            if name.startswith(prefix):
                actions[index] = value
    return [actions.tolist()]


def _run(env: CityLearnEnv, actions: list):
    env.reset()
    while not env.terminated:
        env.step(actions)
    return env.buildings[0]


# --- #231 ---------------------------------------------------------------------------------------------

def _service_demo(tmp_path: Path, *, battery_soc: float, no_ev: bool) -> str:
    """`Building_15` of the three-phase electrical-service demo with a 9 kW import limit, as in the issue."""

    source = DATASETS / 'citylearn_three_phase_electrical_service_demo'
    dataset = tmp_path / f'service_{battery_soc}_{no_ev}'
    shutil.copytree(source, dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    for name, building in schema['buildings'].items():
        building['include'] = name == 'Building_15'
    building = schema['buildings']['Building_15']
    building['electrical_storage']['attributes']['initial_soc'] = battery_soc
    building['electrical_service']['limits']['total']['import_kw'] = 9.0
    if no_ev:
        for charger in building['chargers'].values():
            frame = pd.read_csv(dataset / charger['charger_simulation'])
            for column in frame.columns:
                frame[column] = np.nan
            frame.to_csv(dataset / charger['charger_simulation'], index=False)
    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    return str(path)


def _service_env(path: str, physics_version: int) -> CityLearnEnv:
    return CityLearnEnv(path, central_agent=True, episode_time_steps=48, simulation_end_time_step=47, random_seed=0,
                        physics_version=physics_version)


def _ev_energy(path: str, physics_version: int, battery_action: float) -> np.ndarray:
    env = _service_env(path, physics_version)
    building = _run(env, _actions(env, electric_vehicle_storage=1.0, electrical_storage=battery_action))
    return sum(np.asarray(c.electricity_consumption[:48], dtype=float) for c in building.electric_vehicle_chargers)


def _battery_energy(path: str, physics_version: int, charger_action: float) -> np.ndarray:
    env = _service_env(path, physics_version)
    building = _run(env, _actions(env, electric_vehicle_storage=charger_action, electrical_storage=1.0))
    return np.asarray(building.electrical_storage.electricity_consumption[:48], dtype=float)


def test_issue_231_full_battery_request_does_not_curtail_ev_charging(tmp_path):
    path = _service_demo(tmp_path, battery_soc=1.0, no_ev=False)

    legacy_idle, legacy_request = _ev_energy(path, 1, 0.0), _ev_energy(path, 1, 1.0)
    idle, request = _ev_energy(path, 2, 0.0), _ev_energy(path, 2, 1.0)

    # 3.6.0: the full battery's request takes EV headroom (7.08 against 8.62 kWh at step 0).
    assert legacy_request[0] < legacy_idle[0] - 1.0
    np.testing.assert_allclose(request, idle, atol=1.0e-6)


def test_issue_231_chargers_without_ev_do_not_curtail_battery_charging(tmp_path):
    path = _service_demo(tmp_path, battery_soc=0.0, no_ev=True)

    legacy_idle, legacy_request = _battery_energy(path, 1, 0.0), _battery_energy(path, 1, 1.0)
    idle, request = _battery_energy(path, 2, 0.0), _battery_energy(path, 2, 1.0)

    # 3.6.0: the requests of the chargers without an EV take battery headroom (1.92 against 4.79 kWh at step 0).
    assert legacy_request[0] < legacy_idle[0] - 1.0
    np.testing.assert_allclose(request, idle, atol=1.0e-6)


# --- #230 ---------------------------------------------------------------------------------------------

def _thermal_storage_env(tmp_path: Path, physics_version: int) -> CityLearnEnv:
    """The issue's repro: an electric DHW heater and tank behind a 6 kW single-phase limit."""

    dataset = tmp_path / f'dhw_v{physics_version}'
    shutil.copytree(MINUTE_DATASET, dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    schema['actions']['dhw_storage'] = {'active': True}
    building = schema['buildings']['Building_1']
    building['dhw_device'] = {'type': 'citylearn.energy_model.ElectricHeater', 'autosize': False,
                              'attributes': {'nominal_power': 30.0, 'efficiency': 1.0}}
    building['dhw_storage'] = {'type': 'citylearn.energy_model.StorageTank', 'autosize': False,
                               'attributes': {'capacity': 10.0, 'loss_coefficient': 0.0}}
    building['electrical_service'] = {'mode': 'single_phase', 'limits': {'total': {'import_kw': 6.0}},
                                      'observations': {'headroom': True, 'violation': True}}
    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    return CityLearnEnv(str(path), central_agent=True, random_seed=0, physics_version=physics_version)


def _thermal_storage_run(tmp_path: Path, physics_version: int):
    env = _thermal_storage_env(tmp_path, physics_version)
    env.reset()
    env.step([np.ones(env.action_space[0].shape, dtype='float32').tolist()])
    building = env.buildings[0]
    actual_kw = float(building.net_electricity_consumption[0]) / 0.25
    recorded_kw = float(building._charging_total_power_history_kw[0])
    violation_kwh = float(building._charging_constraint_violation_history[0])
    tank_kwh = float(building.dhw_storage.energy_balance[0])
    return actual_kw, recorded_kw, violation_kwh, tank_kwh


def test_issue_230_physics_version_1_records_the_pre_allocation_import(tmp_path):
    actual_kw, recorded_kw, _, tank_kwh = _thermal_storage_run(tmp_path, 1)

    assert tank_kwh == pytest.approx(2.5)
    assert actual_kw > 6.0 + 5.0
    assert recorded_kw == pytest.approx(6.0)


def test_issue_230_settled_import_and_its_violation_are_recorded(tmp_path):
    actual_kw, recorded_kw, violation_kwh, tank_kwh = _thermal_storage_run(tmp_path, 2)

    assert tank_kwh == pytest.approx(2.5)
    assert recorded_kw == pytest.approx(actual_kw, rel=1.0e-5)
    # The penalty is the settled excess, or the excess the requests would have caused when larger.
    assert violation_kwh >= (actual_kw - 6.0) * 0.25 - 1.0e-5


def test_issue_230_thermal_storage_charging_takes_headroom_before_ev_and_battery(tmp_path):
    env = _thermal_storage_env(tmp_path, 2)
    env.reset()
    env.step([np.ones(env.action_space[0].shape, dtype='float32').tolist()])
    building = env.buildings[0]

    # The tank alone exceeds the limit, so the EV and the battery get no headroom.
    assert float(building.electrical_storage.electricity_consumption[0]) == pytest.approx(0.0, abs=1.0e-6)
    assert sum(float(c.electricity_consumption[0]) for c in building.electric_vehicle_chargers) \
        == pytest.approx(0.0, abs=1.0e-6)


# --- #232 ---------------------------------------------------------------------------------------------

def _deferrable_env(tmp_path: Path, physics_version: int, *, outage_step: int = None, spike_step: int = None,
                    limit_kw: float = None) -> CityLearnEnv:
    dataset = tmp_path / f'deferrable_v{physics_version}_{outage_step}_{spike_step}'
    shutil.copytree(MINUTE_DATASET, dataset)
    profile = [0.1, 0.2, 0.3]
    pd.DataFrame([{'profile_id': 'normal', 'duration_steps': len(profile), 'total_energy_kwh': 0.6,
                   'load_profile': json.dumps(profile)}]).to_csv(dataset / 'washer_cycle_profiles.csv', index=False)
    pd.DataFrame([{'cycle_id': 'cycle_1', 'profile_id': 'normal', 'earliest_start_time_step': 1,
                   'latest_start_time_step': 2, 'deadline_time_step': 4, 'priority': 0.75, 'must_run': True}]
                 ).to_csv(dataset / 'washer_flexibility_schedule.csv', index=False)
    frame = pd.read_csv(dataset / 'Building_1.csv')
    frame['non_shiftable_load'] = 1.0
    frame['solar_generation'] = 0.0
    frame['power_outage'] = 0
    if outage_step is not None:
        frame.loc[outage_step, 'power_outage'] = 1
    if spike_step is not None:
        frame.loc[spike_step, 'non_shiftable_load'] = 1.5
    frame.to_csv(dataset / 'Building_1.csv', index=False)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    for name in ('can_start', 'running', 'pending'):
        schema['observations'][f'deferrable_appliance_{name}'] = {'active': True, 'shared_in_central_agent': True}
    schema['observations']['power_outage'] = {'active': True, 'shared_in_central_agent': True}
    schema['actions']['deferrable_appliance'] = {'active': True}
    building = schema['buildings']['Building_1']
    building['deferrable_appliances'] = {'washer_1': {
        'type': 'citylearn.energy_model.DeferrableAppliance',
        'cycle_profiles_file': 'washer_cycle_profiles.csv',
        'flexibility_schedule_file': 'washer_flexibility_schedule.csv',
    }}
    if outage_step is not None:
        building['power_outage'] = {'simulate_power_outage': True}
    if limit_kw is not None:
        building['electrical_service'] = {'mode': 'single_phase', 'limits': {'total': {'import_kw': limit_kw}}}
    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    return CityLearnEnv(str(path), central_agent=True, random_seed=0, physics_version=physics_version,
                        physics_invariant_checks=True)


def _observation(env: CityLearnEnv, suffix: str) -> float:
    names = env.observation_names[0]
    return float(env.observations[0][next(i for i, name in enumerate(names) if name.endswith(suffix))])


def _start_at_step_1(env: CityLearnEnv):
    env.reset()
    env.step(_actions(env))
    can_start = _observation(env, 'washer_1_can_start')
    outage = _observation(env, 'power_outage')
    env.step(_actions(env, deferrable_appliance=1.0))
    started = float(env.buildings[0].deferrable_appliances_electricity_consumption[1]) > 0.0
    while not env.terminated:
        env.step(_actions(env))
    return can_start, outage, started


@pytest.mark.parametrize('scenario', ['outage', 'load'])
def test_issue_232_physics_version_1_leaks_future_events_through_can_start(tmp_path, scenario):
    kwargs = dict(outage_step=3) if scenario == 'outage' else dict(spike_step=3, limit_kw=6.5)
    can_start, outage, started = _start_at_step_1(_deferrable_env(tmp_path, 1, **kwargs))

    assert outage == 0.0
    assert can_start == 0.0
    assert not started


@pytest.mark.parametrize('scenario', ['outage', 'load'])
def test_issue_232_start_feasibility_uses_only_the_current_step(tmp_path, scenario):
    kwargs = dict(outage_step=3) if scenario == 'outage' else dict(spike_step=3, limit_kw=6.5)
    can_start, outage, started = _start_at_step_1(_deferrable_env(tmp_path, 2, **kwargs))

    assert outage == 0.0
    assert can_start == 1.0
    assert started


def test_issue_232_an_outage_curtails_a_running_cycle_and_the_shortfall_is_reported(tmp_path):
    env = _deferrable_env(tmp_path, 2, outage_step=3)
    _start_at_step_1(env)
    building = env.buildings[0]
    appliance = building.deferrable_appliances[0]
    consumption = np.asarray(building.deferrable_appliances_electricity_consumption[:5], dtype=float)

    # No PV and no battery discharge: the islanded building cannot serve the cycle's last step, so it stops.
    np.testing.assert_allclose(consumption[1:4], [0.1, 0.2, 0.0], atol=1.0e-6)
    summary = appliance.service_summary()
    assert summary['completed_cycles'] == 0.0
    assert summary['missed_cycles'] == 1.0
    (record,) = [row for row in appliance.service_audit()['records'] if row['included']]
    assert (record['state'], record['reason']) == ('missed', 'profile_energy_shortfall')
    assert record['served_energy_kwh'] == pytest.approx(0.3)


def test_issue_232_a_start_during_an_outage_is_still_refused(tmp_path):
    env = _deferrable_env(tmp_path, 2, outage_step=1)
    can_start, outage, started = _start_at_step_1(env)

    assert outage == 1.0
    assert can_start == 0.0
    assert not started
