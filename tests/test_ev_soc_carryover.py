"""EV SOC carried across consecutive episode splits (CityLearn #388)."""

from copy import deepcopy
import json
import warnings

import numpy as np
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.comparison import compare_exports, compare_manifests
from citylearn.internal.experiment import experiment_manifest
from test_deferrable_appliance_integration import _schema_with_deferrable_appliance
from test_settings_recorded import _export

DATASET = 'citylearn_challenge_2022_phase_all_plus_evs'
KEYS = ('ev_events_departure_count', 'ev_departure_audit_departures_count', 'ev_events_departure_met_count')
FEASIBILITY = tuple(
    f'{family}_{threshold}_{kind}_count'
    for family in ('ev_events_departure', 'ev_departure_audit')
    for threshold in ('target', 'min_acceptable')
    for kind in ('feasible', 'infeasible')
)


def _bau(episodes=1, **kwargs):
    """Per-episode KPI frames and the EV SOC at step 0 and at the last control step of each episode."""
    env = CityLearnEnv(DATASET, interface='flat', render_mode='none', export_kpis_on_episode_end=False, **kwargs)
    frames, soc = [], []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            for _ in range(episodes):
                obs, _ = env.reset()
                first = {ev.name: float(ev.battery.soc[0]) for ev in env.electric_vehicles}
                agent = BusinessAsUsualAgent(env)
                while not env.terminated:
                    obs, *_ = env.step(agent.predict(obs))
                last = {ev.name: float(ev.battery.soc[ev.battery.time_step]) for ev in env.electric_vehicles}
                frames.append(env.evaluate_v2())
                soc.append((first, last))
        return frames, soc
    finally:
        env.close()


def _value(frame, name, key):
    return float(frame[(frame.name == name) & (frame.cost_function == key)]['value'].iloc[0])


def _split(boundary):
    end = 1900 + (99 if boundary == 'shared' else 100) + 99
    return dict(simulation_start_time_step=1900, simulation_end_time_step=end), dict(
        episode_time_steps=100, episode_split_boundary=boundary)


def test_shared_split_with_carryover_scores_like_one_run():
    window, split = _split('shared')
    (full,), _ = _bau(**window)
    frames, soc = _bau(episodes=2, ev_soc_carryover=True, **window, **split)

    # Each EV starts the second episode from the SOC it reached at the end of the first one.
    # Here every EV is connected across the boundary, so none takes a schedule SOC at step 0.
    assert soc[1][0] == pytest.approx(soc[0][1])
    names = ['District'] + sorted({n for n in full.name if n.startswith('Building_')})
    for name in names:
        level = 'district' if name == 'District' else 'building'
        for key in KEYS + ('ev_events_departure_deficit_sum',):
            key = f'{level}_{key}'
            if key not in set(full.cost_function):
                continue
            assert sum(_value(f, name, key) for f in frames) == pytest.approx(_value(full, name, key)), (name, key)
    # 67 with the exact target test; 70 since a departure within 0.005 SOC of its target meets it.
    assert sum(_value(f, 'District', 'district_ev_events_departure_met_count') for f in frames) == 70

    # The carried SOC is the session's start SOC for feasibility and the energy accounting too: the
    # feasible classes add up to one run, and no episode counts the previous episode's charge again.
    for key in FEASIBILITY:
        key = f'district_{key}'
        assert sum(_value(f, 'District', key) for f in frames) == _value(full, 'District', key), key
    assert [_value(f, 'District', 'district_ev_energy_accounting_shortfall_kwh') for f in frames] == [0., 0.]


@pytest.mark.parametrize('boundary', ['shared', 'disjoint'])
def test_carryover_counts_each_session_once(boundary):
    window, split = _split(boundary)
    (full,), _ = _bau(**window)
    frames, _ = _bau(episodes=2, ev_soc_carryover=True, **window, **split)
    for key in KEYS[:2]:
        key = f'district_{key}'
        assert sum(_value(f, 'District', key) for f in frames) == _value(full, 'District', key)
    met = sum(_value(f, 'District', 'district_ev_events_departure_met_count') for f in frames)
    assert met <= _value(full, 'District', 'district_ev_events_departure_met_count')
    # Each episode's connected SOC gain starts from the carried SOC, which its own charging explains.
    assert [_value(f, 'District', 'district_ev_energy_accounting_shortfall_kwh') for f in frames] == [0., 0.]


def test_step_zero_arrival_without_file_soc_starts_from_the_carried_soc():
    # EV 2 arrives on `charger_7_1` at row 2107, the boundary row, with no arrival SOC in the file, so
    # it keeps its simulated SOC: the carried one. The energy accounting must start from that SOC too,
    # and not from the EV's initial SOC, which would count gain that never happened in the episode.
    window = dict(simulation_start_time_step=2084, simulation_end_time_step=2130)
    split = dict(episode_time_steps=[(2084, 2107), (2107, 2130)], episode_split_boundary='shared')
    (full,), _ = _bau(**window)
    frames, soc = _bau(episodes=2, ev_soc_carryover=True, **window, **split)

    assert soc[1][0] == pytest.approx(soc[0][1])
    key = 'building_ev_energy_accounting_shortfall_kwh'
    assert _value(full, 'Building_7', key) == 0.
    assert [_value(f, 'Building_7', key) for f in frames] == [0., 0.]
    assert [_value(f, 'District', 'district_ev_energy_accounting_shortfall_kwh') for f in frames] == [0., 0.]


def test_off_by_default_and_unchanged():
    window, split = _split('shared')
    default, soc_default = _bau(episodes=2, **window, **split)
    off, soc_off = _bau(episodes=2, ev_soc_carryover=False, **window, **split)
    assert soc_default == soc_off
    for a, b in zip(default, off):
        assert a.equals(b)


def test_episodes_that_do_not_continue_use_the_schedule_soc():
    # A gap between two explicit splits: the second episode starts from the schedule SOC.
    window = dict(simulation_start_time_step=1900, simulation_end_time_step=1999)
    split = dict(episode_time_steps=[(1900, 1949), (1960, 1999)])
    on, soc_on = _bau(episodes=2, ev_soc_carryover=True, **window, **split)
    off, soc_off = _bau(episodes=2, ev_soc_carryover=False, **window, **split)
    assert soc_on[1][0] == soc_off[1][0]
    assert on[1].equals(off[1])


def _carried_in(episodes=2, **kwargs):
    """`carried_in` and the window of each episode, with the BAU, and the warnings raised."""
    result = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        # The constructor resets the env once, so the warning can come from there.
        env = CityLearnEnv(DATASET, interface='flat', render_mode='none', export_kpis_on_episode_end=False,
                           ev_soc_carryover=True, **kwargs)
        try:
            for _ in range(episodes):
                obs, _ = env.reset()
                tracker = env.episode_tracker
                result.append((tracker.episode_start_time_step, tracker.episode_end_time_step,
                               env._ev_soc_carryover_context['carried_in']))
                agent = BusinessAsUsualAgent(env)
                while not env.terminated:
                    obs, *_ = env.step(agent.predict(obs))
        finally:
            env.close()
    messages = [str(w.message) for w in caught if 'ev_soc_carryover has no effect' in str(w.message)]
    return result, messages


@pytest.mark.parametrize('boundary,splits,carried', [
    ('shared', [(1900, 1949), (1949, 1999)], True),
    ('shared', [(1900, 1949), (1950, 1999)], False),
    ('disjoint', [(1900, 1949), (1950, 1999)], True),
    ('disjoint', [(1900, 1949), (1949, 1999)], False),
])
def test_explicit_splits_carry_only_when_the_window_continues_for_the_boundary(boundary, splits, carried):
    episodes, messages = _carried_in(simulation_start_time_step=1900, simulation_end_time_step=1999,
                                     episode_time_steps=splits, episode_split_boundary=boundary)
    assert [e[2] for e in episodes] == [False, carried]
    assert messages == []


def test_random_split_never_carries_even_when_it_picks_the_next_window():
    # With seed 1 the random picks over these four shared splits are [1900, 1923] then [1923, 1946],
    # the window that a sequential split would carry into.
    episodes, messages = _carried_in(simulation_start_time_step=1900, simulation_end_time_step=1992,
                                     episode_time_steps=24, random_episode_split=True, random_seed=1)
    assert [e[:2] for e in episodes] == [(1900, 1923), (1923, 1946)]
    assert [e[2] for e in episodes] == [False, False]
    assert len(messages) == 1


def test_rolling_split_never_carries():
    episodes, messages = _carried_in(simulation_start_time_step=1900, simulation_end_time_step=1910,
                                     episode_time_steps=2, rolling_episode_split=True)
    assert [e[:2] for e in episodes] == [(1900, 1901), (1901, 1902)]
    assert [e[2] for e in episodes] == [False, False]
    assert len(messages) == 1


def test_later_arrival_of_a_carried_ev_takes_the_file_soc():
    """Only the session connected across the boundary starts from the carried SOC (CityLearn #388)."""
    window, split = _split('shared')

    def second_episode(carry):
        env = CityLearnEnv(DATASET, interface='flat', render_mode='none', export_kpis_on_episode_end=False,
                           ev_soc_carryover=carry, **window, **split)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                for _ in range(2):
                    obs, _ = env.reset()
                    continuing = list((env._ev_soc_carryover_context or {}).get('continuing', []))
                    agent = BusinessAsUsualAgent(env)
                    while not env.terminated:
                        obs, *_ = env.step(agent.predict(obs))
            arrivals = {}
            for building in env.buildings:
                for charger in building.electric_vehicle_chargers or []:
                    sim = charger.charger_simulation
                    states, ids = sim.electric_vehicle_charger_state, sim.electric_vehicle_id
                    for t in range(1, env.time_step):
                        if states[t] == 1 and (states[t - 1] != 1 or ids[t - 1] != ids[t]):
                            arrivals.setdefault(str(ids[t]), t)
            soc = {ev.name: np.array(ev.battery.soc[:env.time_step]) for ev in env.electric_vehicles}
            return continuing, arrivals, soc
        finally:
            env.close()

    continuing, arrivals, on = second_episode(True)
    _, _, off = second_episode(False)
    later = [name for name in continuing if name in arrivals]
    assert later
    for name in later:
        t = arrivals[name]
        # The next arrival of a carried EV starts from the file SOC, as without carry-over.
        assert on[name][t] == pytest.approx(off[name][t], abs=1e-9)
    assert any(on[name][0] != pytest.approx(off[name][0]) for name in continuing)


def test_unit_last_step_and_step_zero_rules_follow_the_carryover_context():
    from test_ev_departure_audit import counts, split_window

    # Countdown 1 at the last control step: the session is still connected on the next episode's first row.
    service, building = split_window(start=1, states=(1., 1., 1., 1., 0., 0.),
                                     countdowns=(3., 2., 1., 0., -1., -1.), ids=('EV',) * 6, simulation_end=100)
    charger = building.electric_vehicle_chargers[0]
    charger.past_connected_evs = [charger.past_connected_evs[0]] * 2
    assert counts(service, building)['departures_count'] == 1
    service.env._ev_soc_carryover_context = dict(carried_in=False, soc={}, continuing=[], last_step_countdown=0.)
    assert counts(service, building)['departures_count'] == 0

    # Step 0 counts a session carried across the boundary instead of skipping it.
    service, building = split_window()
    assert counts(service, building)['departures_count'] == 0
    service.env._ev_soc_carryover_context = dict(carried_in=True, soc={'EV': .5}, continuing=['EV'],
                                                 last_step_countdown=1.)
    assert counts(service, building)['departures_count'] == 1


def test_setting_is_recorded_and_exports_with_different_values_are_incompatible(tmp_path):
    path = _schema_with_deferrable_appliance(tmp_path/'source')
    env = CityLearnEnv(str(path), episode_time_steps=4, random_seed=0, ev_soc_carryover=True,
                       render_directory=tmp_path/'out')
    env.reset()
    metadata, manifest = env.get_metadata(), experiment_manifest(env)
    env.close()
    for record in (metadata, metadata['temporal_reproducibility'], manifest, manifest['temporal_reproducibility'],
                   manifest['comparison_context']):
        assert record['ev_soc_carryover'] is True

    schema = json.loads(path.read_text())
    schema['ev_soc_carryover'] = True
    env = CityLearnEnv(schema, episode_time_steps=4)
    assert env.ev_soc_carryover is True
    env.close()

    a = _export(path, tmp_path/'a')
    b = _export(path, tmp_path/'b', ev_soc_carryover=True)
    report = compare_exports(a, b)
    assert report['status'] == 'incompatible' and 'ev_soc_carryover' in report['mismatches']

    # A manifest written before the setting existed pairs with a run without it.
    left = json.loads(a.with_suffix('.manifest.json').read_text())
    older = deepcopy(left)
    del older['comparison_context']['ev_soc_carryover']
    assert 'ev_soc_carryover' not in compare_manifests(left, older)['mismatches']


def test_business_as_usual_reference_starts_from_the_carried_soc():
    window, split = _split('disjoint')
    env = CityLearnEnv(DATASET, interface='flat', render_mode='none', export_kpis_on_episode_end=False,
                       ev_soc_carryover=True, **window, **split)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            for _ in range(2):
                obs, _ = env.reset()
                agent = BusinessAsUsualAgent(env)
                while not env.terminated:
                    obs, *_ = env.step(agent.predict(obs))
            assert env._ev_soc_carryover_context['carried_in']
            # The reference rejects an initial inventory that differs from the evaluated episode's.
            reference = env._business_as_usual_baseline_service.run().env
            assert reference.ev_soc_carryover is True
            assert reference._ev_soc_carryover_context == env._ev_soc_carryover_context
    finally:
        env.close()
