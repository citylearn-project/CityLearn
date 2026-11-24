"""Independent examples for information coverage and observed departure service."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace as NS

import numpy as np
import pandas as pd
import pytest

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.community_dataset import InventoryBattery
from citylearn.internal import ev_departure_audit as audit
from citylearn.internal.kpi import CityLearnKPIService
from private_access import kpi_service


SOURCE = Path(__file__).parent / 'data/minute_ev_demo'


def event(*, actual=.8, initial=.2, target=.8, power=10., steps=1):
    tracker = EpisodeTracker(0, steps)
    tracker.next_episode(steps + 1, False, False, 0)
    battery = InventoryBattery(
        capacity=10., initial_soc=initial, max_charge_kw=power, max_discharge_kw=10.,
        charging_efficiency=1., discharging_efficiency=1., loss_coefficient=0.,
        episode_tracker=tracker, seconds_per_time_step=3600, time_step_ratio=1.)
    battery.reset()
    for t in range(steps):
        if t:
            battery.next_time_step()
        battery.force_set_soc(actual)
    ev = NS(battery=battery)
    sim = NS(electric_vehicle_charger_state=np.array([1.] * steps + [0.]),
             electric_vehicle_current_soc=[initial] * (steps + 1),
             electric_vehicle_id=['EV'] * (steps + 1),
             electric_vehicle_required_soc_departure=[target] * (steps + 1))
    charger = NS(charger_id='charger', max_charging_power=10., efficiency=1.,
                 seconds_per_time_step=3600, charger_simulation=sim,
                 electricity_consumption=np.zeros(steps + 1), past_connected_evs=[ev] * steps + [None])
    building = NS(name='B', time_step=steps, electric_vehicle_chargers=[charger])
    service = CityLearnKPIService(NS(topology_mode='static', seconds_per_time_step=3600))
    return service, building, charger, ev


def counts(service, building, **kwargs):
    return service._compute_ev_metrics(building, **kwargs)['_departure_audit']


def assert_partition(c):
    for threshold in audit.THRESHOLDS:
        assert sum(c[f'{threshold}_{s}_count'] for s in ['feasible', 'infeasible', 'unknown']) == c['departures_count']
        assert sum(c[f'{threshold}_unknown_{r}_count'] for r in audit.UNKNOWN_REASONS) == c[f'{threshold}_unknown_count']
    assert c['service_observed_count'] + c['service_unknown_count'] == c['departures_count']


@pytest.mark.parametrize('reason', audit.UNKNOWN_REASONS[:-1])
def test_unknown_inputs_are_counted_with_one_reason(reason, monkeypatch):
    service, building, charger, ev = event()
    if reason == 'missing_target':
        charger.charger_simulation.electric_vehicle_required_soc_departure = [-1., -1.]
    elif reason == 'missing_ev':
        charger.past_connected_evs = [None, None]
    elif reason == 'missing_battery':
        ev.battery = None
    elif reason == 'invalid_capacity':
        ev.battery = NS(capacity=np.nan, soc=[.8, .8])
    elif reason == 'invalid_charger_power':
        charger.max_charging_power = np.nan
    elif reason == 'invalid_charger_efficiency':
        charger.efficiency = np.nan
    elif reason == 'invalid_time_step':
        charger.seconds_per_time_step = np.nan
    elif reason == 'missing_arrival_soc':
        charger.charger_simulation.electric_vehicle_current_soc = [-1., -1.]
        ev.battery = NS(capacity=10., initial_soc=None, soc=[.8, .8])
    elif reason == 'unsupported_battery_model':
        ev.battery = NS(capacity=10., initial_soc=.2, soc=[.8, .8])
    elif reason == 'invalid_battery_parameters':
        monkeypatch.setattr(type(ev.battery), 'efficiency', property(lambda self: np.nan))
    # Avoid asking the permissive historical physics to run a deliberately
    # malformed native model; exercise the strict evaluator directly here.
    c = audit.empty_counts()
    sim = charger.charger_simulation
    audit.record_departure(service, c, building, charger, sim, charger.past_connected_evs[0],
                           sim.electric_vehicle_charger_state, 0,
                           service._normalize_soc_target(sim.electric_vehicle_required_soc_departure[0]))
    assert c['target_unknown_count'] == 1
    assert c[f'target_unknown_{reason}_count'] == 1
    assert audit.metrics(c)['target_coverage_ratio'] == 0.
    assert audit.metrics(c)['target_service_feasible_ratio'] is None
    assert_partition(c)


def test_missing_arrival_never_uses_the_final_soc_as_its_own_evidence():
    service, building, charger, ev = event()
    charger.charger_simulation.electric_vehicle_current_soc = [-1., -1.]
    ev.battery = NS(capacity=10., initial_soc=None, soc=[.8, .8])
    m = service._compute_ev_metrics(building)
    assert m['departures_total'] == 1  # historical observed service preserved
    assert m['departures_target_feasible'] == 1  # historical permissive fallback
    assert m['_departure_audit']['target_unknown_missing_arrival_soc_count'] == 1
    assert m['_departure_audit']['target_service_met_count'] == 1


@pytest.mark.parametrize('missing', ['ev', 'battery', 'target', 'soc'])
def test_missing_service_data_does_not_disappear_from_the_audit(missing):
    service, building, charger, ev = event()
    if missing == 'ev':
        charger.past_connected_evs = []
    elif missing == 'battery':
        ev.battery = None
    elif missing == 'target':
        charger.charger_simulation.electric_vehicle_required_soc_departure = []
    else:
        ev.battery.soc[0] = np.nan
    c = counts(service, building)
    assert c['departures_count'] == c['service_unknown_count'] == 1
    assert_partition(c)


def test_mixed_population_has_independent_service_and_feasibility_denominators():
    service, building, _, _ = event(actual=.8)
    _, _, failed, _ = event(actual=.2)
    _, _, impossible, _ = event(actual=.3, power=1.)  # .2 + 1 kWh / 10 kWh = .3
    _, _, unknown, _ = event(actual=.8)
    unknown.max_charging_power = np.nan
    building.electric_vehicle_chargers += [failed, impossible, unknown]
    c = counts(service, building)
    assert_partition(c)
    assert (c['target_feasible_count'], c['target_infeasible_count'], c['target_unknown_count']) == (2, 1, 1)
    m = audit.metrics(c)
    assert m['target_coverage_ratio'] == .75
    assert m['target_service_observed_ratio'] == .5
    assert m['target_service_feasible_ratio'] == .5
    assert m['service_coverage_ratio'] == 1.


def test_thresholds_have_their_own_feasibility_and_service_populations():
    service, building, _, _ = event(actual=.76, power=5.6)
    c = counts(service, building)
    assert c['target_infeasible_count'] == 1
    assert c['min_acceptable_feasible_count'] == c['within_tolerance_feasible_count'] == 1
    assert c['target_service_met_count'] == 0
    assert c['min_acceptable_service_met_count'] == c['within_tolerance_service_met_count'] == 1
    assert_partition(c)


def test_outage_recovery_is_sufficient_but_unreplayed_local_supply_is_not_infeasibility():
    service, building, _, _ = event(steps=2)
    building.power_outage_signal = [1., 0., 0.]
    c = counts(service, building)
    assert c['target_feasible_count'] == c['target_service_met_count'] == 1
    building.power_outage_signal = [1., 1., 0.]
    c = counts(service, building)
    assert c['target_unknown_outage_supply_not_replayed_count'] == 1
    assert c['target_service_met_count'] == 1  # observed service is still known


def test_repeated_evaluation_and_removed_charger_preserve_physical_state():
    service, building, charger, ev = event(steps=2)
    before = deepcopy(ev.battery.__dict__)
    service.env.topology_mode = 'dynamic'
    service.env._topology_service = NS(historical_chargers=lambda name: [charger])
    building.electric_vehicle_chargers = []
    c = counts(service, building)
    assert c == counts(service, building)
    assert c['departures_count'] == 1
    np.testing.assert_array_equal(ev.battery.soc, before['_StorageDevice__soc'])
    assert list(ev.battery.capacity_history) == list(before['_capacity_history'])
    assert list(ev.battery.efficiency_history) == list(before['_efficiency_history'])
    assert ev.battery.time_step == 1


def test_partial_windows_only_count_real_departures_and_empty_denominators_are_null():
    service, building, charger, _ = event(steps=2)
    assert counts(service, building, t_final=0)['departures_count'] == 0
    assert counts(service, building, t_start=1)['departures_count'] == 1
    assert counts(service, building, t_start=2)['departures_count'] == 0
    assert audit.metrics(counts(service, building, t_start=3))['target_coverage_ratio'] is None
    charger.charger_simulation.electric_vehicle_charger_state = np.ones(2)
    charger.charger_simulation.electric_vehicle_departure_time = [-1., -1.]
    assert counts(service, building)['departures_count'] == 0


def test_activation_does_not_borrow_charging_time_before_connection():
    service, building, charger, _ = event(power=3., steps=2)
    charger.past_connected_evs[0] = None
    c = counts(service, building)
    # One observed hour: .2 + 3/10 = .5, not .8 using the inactive hour.
    assert c['target_infeasible_count'] == 1
    assert_partition(c)


def test_reinstalled_charger_does_not_duplicate_an_inactive_scheduled_departure():
    service, building, charger, _ = event()
    _, _, replacement, _ = event()
    service.env.topology_mode = 'dynamic'
    service.env._topology_service = NS(
        historical_chargers=lambda name: [charger, replacement],
        active_chargers_at=lambda t, name: {'charger': charger})
    c = counts(service, building)
    assert c['departures_count'] == c['target_feasible_count'] == 1
    assert_partition(c)


def test_back_to_back_countdown_reset_does_not_borrow_previous_session_time():
    service, building, charger, _ = event(power=3., steps=3)
    charger.charger_simulation.electric_vehicle_departure_time = [1., 2., 1., -1.]
    # Each new connection starts at .1: first session cannot reach .8; neither
    # can the second (.1 + 2*3/10=.7), although all three hours would suffice.
    charger.charger_simulation.electric_vehicle_current_soc = [.1] * 4
    c = counts(service, building)
    assert c['departures_count'] == c['target_infeasible_count'] == 2
    assert_partition(c)


@pytest.mark.parametrize('countdown,expected', [(1., 1), (0., 1), (2., 0), (-1., 0)])
def test_session_that_ends_with_the_window_is_a_departure(countdown, expected):
    # Issue #370: the EV stays connected through the schedule's terminal row,
    # so only the "last step" rule can record its departure.
    service, building, charger, ev = event(steps=3)
    sim = charger.charger_simulation
    sim.electric_vehicle_charger_state = np.ones(4)
    sim.electric_vehicle_id = ['EV'] * 4
    sim.electric_vehicle_departure_time = [countdown + 2., countdown + 1., countdown, max(countdown - 1., -1.)]
    charger.past_connected_evs = [ev] * 4
    building.time_step = 2
    metrics = service._compute_ev_metrics(building)
    assert metrics['_departure_audit']['departures_count'] == expected
    assert metrics['departures_total'] == expected
    if expected:
        assert metrics['departures_met'] == 1
    if countdown == 1.:
        # A window one step longer still counts the session once.
        building.time_step = 3
        assert counts(service, building)['departures_count'] == 1


def split_window(*, boundary='shared', start=2, states=(1., 1., 1., 0.), countdowns=(2., 1., 0., -1.),
                 ids=('EV',) * 4, session_ids=None):
    """A one-step window at full schedule row `start` of a schedule that starts at the simulation start."""
    service, building, charger, ev = event(steps=1)
    service.env.episode_split_boundary = boundary
    sim = charger.charger_simulation
    full = dict(electric_vehicle_charger_state=np.array(states),
                electric_vehicle_departure_time=list(countdowns), electric_vehicle_id=list(ids))
    if session_ids is not None:
        full['electric_vehicle_session_id'] = list(session_ids)
    for name, values in full.items():
        setattr(sim, f'_{name}', values)
        setattr(sim, name, values[start:start + 2])
    sim.start_time_step = start
    return service, building


@pytest.mark.parametrize('kwargs,expected', [
    # The session was connected on the row before step 0, whatever its countdown there.
    (dict(), 0),
    (dict(boundary='disjoint'), 0),
    (dict(countdowns=(2., -1., 0., -1.)), 0),
    (dict(boundary='disjoint', states=(0., 1., 1., 0.), countdowns=(-1., 1., 0., -1.)), 0),
    # A different session at the row before, or a charger that was free there.
    (dict(ids=('A', 'A', 'B', None)), 1),
    (dict(session_ids=('s1', 's1', 's2', None)), 1),
    (dict(countdowns=(2., 0., 1., -1.)), 1),
    (dict(boundary='disjoint', states=(1., 0., 1., 0.), countdowns=(0., -1., 0., -1.)), 1),
])
def test_departure_at_step_zero_is_not_counted_twice(kwargs, expected):
    service, building = split_window(**kwargs)
    metrics = service._compute_ev_metrics(building)
    assert metrics['_departure_audit']['departures_count'] == expected
    assert metrics['departures_total'] == expected


@pytest.mark.parametrize('boundary,expected', [('shared', 0), ('disjoint', 1)])
def test_last_step_counts_a_session_that_leaves_before_the_next_control_step(boundary, expected):
    # The window's last step is row 2, with countdown 2: the EV stays connected until row 4.
    # That row is the next window's step 0 under disjoint boundaries, which skips it, and its
    # step 1 under shared ones, which counts it.
    service, building = split_window(boundary=boundary, start=1, states=(1., 1., 1., 1., 1., 0.),
                                     countdowns=(3., 3., 2., 1., 0., -1.), ids=('EV',) * 6)
    charger = building.electric_vehicle_chargers[0]
    charger.past_connected_evs = [charger.past_connected_evs[0]] * 2
    metrics = service._compute_ev_metrics(building)
    assert metrics['_departure_audit']['departures_count'] == expected
    assert metrics['departures_total'] == expected


def test_first_window_counts_a_departure_at_step_zero():
    service, building = split_window(start=0, states=(1., 0., 0., 0.), countdowns=(0., -1., -1., -1.))
    assert counts(service, building)['departures_count'] == 1


def _bau_departures(**kwargs):
    from citylearn.agents.baseline import BusinessAsUsualAgent

    episodes = kwargs.pop('episodes', 1)
    env = CityLearnEnv('citylearn_challenge_2022_phase_all_plus_evs', interface='flat',
                       render_mode='none', export_kpis_on_episode_end=False, **kwargs)
    try:
        results = []
        for _ in range(episodes):
            obs, _ = env.reset()
            agent = BusinessAsUsualAgent(env)
            done = False
            while not done:
                obs, _, terminated, truncated, _ = env.step(agent.predict(obs))
                done = terminated or truncated
            results.append(env.evaluate_v2())
        return env, results
    finally:
        env.close()


def test_bundled_episode_ending_at_a_departure_counts_it():
    """Reproduction from issue #370 on the bundled EV dataset."""
    env, (frame,) = _bau_departures(simulation_start_time_step=1900, simulation_end_time_step=1999)
    sim = next(b for b in env.buildings if b.name == 'Building_1').electric_vehicle_chargers[0].charger_simulation
    assert list(sim.electric_vehicle_charger_state[95:100]) == [1.] * 5
    assert list(sim.electric_vehicle_departure_time[95:100]) == [4., 3., 2., 1., 0.]
    values = frame[frame.name == 'Building_1'].set_index('cost_function')['value']
    assert values['building_ev_events_departure_count'] == 5
    assert values['building_ev_departure_audit_departures_count'] == 5


@pytest.mark.parametrize('boundary,step', [('shared', 99), ('disjoint', 100)])
def test_split_episodes_count_each_session_once(boundary, step):
    # Shared: Electric_Vehicle_7 on charger_1_1 leaves after row 1999, so episode 0 counts it at
    # its last step (row 1998) and episode 1 skips it at step 0. Disjoint: five sessions have
    # countdown 2 at row 1998 and leave after row 2000, so episode 0 counts them with the SOC
    # BAU reached, and episode 1 skips them at step 0 instead of scoring the SOC set at reset.
    end = 1900 + step + 99
    _, frames = _bau_departures(simulation_start_time_step=1900, simulation_end_time_step=end,
                                episode_time_steps=100, episode_split_boundary=boundary, episodes=2)
    _, (full,) = _bau_departures(simulation_start_time_step=1900, simulation_end_time_step=end)

    def value(frame, name='Building_1', key='building_ev_departure_audit_departures_count'):
        return frame[frame.name == name].set_index('cost_function')['value'][key]

    for key in ('ev_departure_audit_departures_count', 'ev_events_departure_count'):
        assert sum(value(f, 'District', f'district_{key}') for f in frames) == value(full, 'District', f'district_{key}')
    assert [value(f) for f in frames] == [5, value(full) - 5]
    if boundary == 'disjoint':
        # The gap row is never controlled, so each session is scored at a row both runs control.
        names = ['District'] + [f'Building_{i}' for i in (5, 7, 10, 12, 15)]
        for name in names:
            level = 'district' if name == 'District' else 'building'
            for key in ('ev_events_departure_count', 'ev_events_departure_met_count'):
                key = f'{level}_{key}'
                assert sum(value(f, name, key) for f in frames) == value(full, name, key)
        met = [value(frames[1], 'Building_5', f'building_ev_events_departure_{k}') for k in ('count', 'met_count')]
        assert met == [4, 4]


@pytest.mark.parametrize('target,expected_met', [(45., 1), (90., 0)])
def test_real_outage_delayed_charge_and_departure_service_export(tmp_path, target, expected_met):
    root = tmp_path / 'data'
    shutil.copytree(SOURCE, root)
    schema = json.loads((root / 'schema.json').read_text())
    schema.update(root_directory=str(root), physics_invariant_checks=True)
    frame = pd.read_csv(root / 'Building_1.csv')
    frame['power_outage'] = [1, 1, 0, 0, 0, 0, 0, 0]
    frame['solar_generation'] = 0.
    frame.to_csv(root / 'Building_1.csv', index=False)
    schedule = pd.read_csv(root / 'charger_1_1.csv')
    schedule['electric_vehicle_required_soc_departure'] = target
    schedule.to_csv(root / 'charger_1_1.csv', index=False)
    schema['buildings']['Building_1']['power_outage'] = {'simulate_power_outage': True}
    env = CityLearnEnv(schema, episode_time_steps=6, central_agent=True, random_seed=0,
                       render_directory=tmp_path / 'export', export_kpis_on_episode_end=False)
    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step([[1. if name.startswith('electric_vehicle_storage_') else 0.
                       for name in env.action_names[0]]])
        b = env.buildings[0]
        assert sum(b.chargers_electricity_consumption[:2]) == 0.
        assert sum(b.chargers_electricity_consumption[2:4]) > 0.
        c = kpi_service(env)._compute_ev_metrics(b)['_departure_audit']
        assert c['departures_count'] == 1
        assert c['target_service_met_count'] == expected_met
        assert_partition(c)
        frame = env.evaluate_v2()
        key = 'district_ev_departure_audit_target_service_observed_ratio'
        assert float(frame.loc[frame.cost_function == key, 'value'].iloc[0]) == expected_met
        env.export_final_kpis(filepath='audit.csv', include_business_as_usual=False)
        exported = pd.read_csv(Path(env.new_folder_path) / 'audit.csv')
        assert key in set(exported.KPI)
        assert float(exported.loc[exported.KPI == key, 'District'].iloc[0]) == expected_met
        manifest = json.loads((Path(env.new_folder_path) / 'audit.manifest.json').read_text())
        assert audit.DEFINITION_VERSION in json.dumps(manifest)
    finally:
        env.close()


def test_dynamic_activation_and_reset_reconcile_building_and_district_counts(tmp_path):
    root = tmp_path / 'data'
    shutil.copytree(SOURCE, root)
    schema = json.loads((root / 'schema.json').read_text())
    schema.update(root_directory=str(root), physics_invariant_checks=True,
                  interface='entity', topology_mode='dynamic')
    schedule = pd.read_csv(root / 'charger_1_1.csv')
    schedule['electric_vehicle_current_soc'] = .4
    schedule['electric_vehicle_required_soc_departure'] = 45.
    schedule.to_csv(root / 'charger_1_1.csv', index=False)
    schema['buildings']['Building_1']['include'] = False
    schema['buildings']['Base'] = deepcopy(schema['buildings']['Building_1'])
    schema['buildings']['Base']['include'] = True
    schema['buildings']['Base'].pop('chargers')
    schema['topology_events'] = [dict(id='join', time_step=1, operation='add_member',
                                     target_member_id='Building_1')]
    env = CityLearnEnv(schema, episode_time_steps=6, central_agent=False, random_seed=0,
                       export_kpis_on_episode_end=False)
    try:
        results = []
        for _ in range(2):
            env.reset(seed=0)
            while not env.terminated:
                env.step({'tables': {k: np.zeros(v.shape, dtype='float32')
                                     for k, v in env.action_space['tables'].items()}})
            frame = env.evaluate_v2()
            def value(key):
                return frame.loc[frame.cost_function == key, 'value'].sum()
            total = value('district_ev_departure_audit_departures_count')
            assert total == value('building_ev_departure_audit_departures_count') == 1.
            assert value('district_ev_departure_audit_target_feasible_count') == 1.
            assert value('district_ev_departure_audit_target_service_met_count') == 0.
            results.append(frame.loc[frame.cost_function.str.contains('_departure_audit_')].reset_index(drop=True))
        pd.testing.assert_frame_equal(*results)
    finally:
        env.close()
