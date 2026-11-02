"""Indexed lifecycle parity against the former full-calendar traversal."""
import copy
import pickle

import numpy as np
import pytest

from citylearn.base import EpisodeTracker
from citylearn.data import DeferrableApplianceSimulation
from citylearn.energy_model import DeferrableAppliance


class ScanAppliance(DeferrableAppliance):
    """Frozen scan rules used before indexing, independent of the new helper."""
    def _next_pending_cycle(self):
        return next((c for c in self.deferrable_appliance_simulation.flexibility_schedule
                     if self.cycle_state.get(c['cycle_id']) == 'pending'), None)

    def _current_or_next_cycle(self):
        states = self.cycle_state
        for state in ('running', 'pending', 'missed'):
            for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
                if states.get(cycle['cycle_id']) == state:
                    return cycle
        return None

    def _update_cycle_states(self):
        current = self._current_global_time_step()
        states = self._DeferrableAppliance__cycle_state
        starts = self._DeferrableAppliance__cycle_start_time_steps
        for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
            key = cycle['cycle_id']
            if states.get(key) == 'running':
                start = starts.get(key)
                if start is not None and current > start + int(cycle['duration_steps']) - 1:
                    states[key] = 'completed'
                    self._DeferrableAppliance__cycle_completion_time_steps[key] = current - 1
            elif states.get(key) == 'pending' and current > int(cycle['latest_start_time_step']):
                self._mark_missed(cycle, current)

    def _finalize_running_cycles_at_current_step(self):
        current = self._current_global_time_step()
        states = self._DeferrableAppliance__cycle_state
        for cycle in self.deferrable_appliance_simulation.flexibility_schedule:
            key = cycle['cycle_id']
            start = self._DeferrableAppliance__cycle_start_time_steps.get(key)
            if states.get(key) == 'running' and start is not None and current >= start + int(cycle['duration_steps']) - 1:
                states[key] = 'completed'
                self._DeferrableAppliance__cycle_completion_time_steps[key] = start + int(cycle['duration_steps']) - 1


def make(cls=DeferrableAppliance, *, count=8, seconds=900, offset=0):
    profile = np.array([0.001, 0.002], dtype='float32')
    cycles = [dict(cycle_id=f'c{i}', earliest_start_time_step=i*6,
                   latest_start_time_step=i*6+2, deadline_time_step=i*6+3,
                   duration_steps=2, total_energy_kwh=float(profile.sum()),
                   load_profile=profile.copy(), priority=.5, must_run=True)
              for i in range(count)]
    simulation = DeferrableApplianceSimulation(cycle_profiles={}, flexibility_schedule=cycles)
    horizon = count*6+6
    tracker = EpisodeTracker(offset, offset+horizon-1)
    tracker.next_episode(horizon, rolling_episode_split=False, random_episode_split=False, random_seed=0)
    appliance = cls(deferrable_appliance_simulation=simulation, name='washer',
                    episode_tracker=tracker, seconds_per_time_step=seconds,
                    nominal_power=5., random_seed=0)
    appliance.reset()
    return appliance


def same(a, b):
    assert a.observations() == b.observations()
    assert a.cycle_state == b.cycle_state
    np.testing.assert_array_equal(a.electricity_consumption, b.electricity_consumption)
    np.testing.assert_array_equal(a.past_action_values, b.past_action_values)
    for suffix in ('start', 'completion', 'missed', 'cancelled'):
        name = f'_DeferrableAppliance__cycle_{suffix}_time_steps'
        assert getattr(a, name) == getattr(b, name)
    assert a.service_audit() == b.service_audit()


@pytest.mark.parametrize('seconds', [15, 60, 900, 3600])
@pytest.mark.parametrize('offset', [0, 7, 30])
def test_scan_parity_through_actions_misses_activation_and_finalization(seconds, offset):
    a, b = make(seconds=seconds, offset=offset), make(ScanAppliance, seconds=seconds, offset=offset)
    rng = np.random.RandomState(17)
    for step in range(48):
        same(a, b)
        action = [0., 1., .5, float('nan')][rng.randint(4)]
        np.testing.assert_array_equal(a.preview_start_profile_kwh(action), b.preview_start_profile_kwh(action))
        a.start_cycle(action); b.start_cycle(action)
        same(a, b)  # state changes inside this very step must be visible immediately
        a.record_service_interval(); b.record_service_interval()
        if step % 3 == 0:
            assert a.service_summary() == b.service_summary()
            same(a, b)
        if step == 5:
            a.skip_cycles_before(12); b.skip_cycles_before(12)
        if step == 11:
            a.exclude_previously_offered_cycles(['c3', 'c5']); b.exclude_previously_offered_cycles(['c3', 'c5'])
        if step == 37:
            a.cancel_pending_and_running(); b.cancel_pending_and_running()
        a.next_time_step(); b.next_time_step()
    same(a, b)
    assert a.service_summary() == b.service_summary()


def test_time_jump_keeps_missed_timestamp_and_completion_rules():
    a, b = make(), make(ScanAppliance)
    a.start_cycle(1.); b.start_cycle(1.)
    a.time_step = b.time_step = 32
    same(a, b)
    assert a._DeferrableAppliance__cycle_completion_time_steps['c0'] == 31
    assert a._DeferrableAppliance__cycle_missed_time_steps['c1'] == 32


def test_terminal_finalize_is_distinct_from_next_step_completion():
    a, b = make(), make(ScanAppliance)
    a.start_cycle(1.); b.start_cycle(1.)
    a.next_time_step(); b.next_time_step()
    assert a.cycle_state['c0'] == 'running'
    assert a.service_summary() == b.service_summary()
    assert a.cycle_state['c0'] == 'completed'
    same(a, b)


@pytest.mark.parametrize('clone', [copy.deepcopy, lambda a: pickle.loads(pickle.dumps(a))])
def test_copy_and_pickle_keep_index_states_independent(clone):
    a = make(); a.start_cycle(1.); a.observations()
    b = clone(a)
    same(a, b)
    b.cancel_pending_and_running()
    assert a.cycle_state['c0'] == 'running'
    assert b.cycle_state['c0'] == 'cancelled'
    same(a, clone(a))
    a.reset(); b.reset(); same(a, b)


def test_schedule_replacement_and_same_length_simulation_setter_rebuild_lookups():
    a, b = make(), make(ScanAppliance)
    a.observations(); b.observations()
    for x in (a, b):
        x.deferrable_appliance_simulation.flexibility_schedule = list(x.deferrable_appliance_simulation.flexibility_schedule)
    same(a, b)
    for x in (a, b):
        x.deferrable_appliance_simulation = copy.deepcopy(x.deferrable_appliance_simulation)
    same(a, b)
    a.start_cycle(1.); b.start_cycle(1.); same(a, b)


def test_current_cycle_fields_are_not_cached_after_a_preview():
    a, b = make(), make(ScanAppliance)
    a.preview_start_profile_kwh(1.); b.preview_start_profile_kwh(1.)
    for x in (a, b):
        cycle = x.deferrable_appliance_simulation.flexibility_schedule[0]
        cycle['latest_start_time_step'] = 1
    a.time_step = b.time_step = 2
    same(a, b)
    assert a.cycle_state['c0'] == 'missed'


class CountingSchedule(list):
    traversals = 0
    def __iter__(self):
        self.traversals += 1
        return super().__iter__()


def test_repeated_reads_do_not_walk_a_two_year_calendar():
    a = make(count=730)
    calendar = CountingSchedule(a.deferrable_appliance_simulation.flexibility_schedule)
    a.deferrable_appliance_simulation.flexibility_schedule = calendar
    a.observations(); calendar.traversals = 0
    for _ in range(100):
        a.observations(); a.preview_start_profile_kwh(1.)
    assert calendar.traversals == 0
    a.start_cycle(1.)
    assert a.observations()['running'] == 1.
    a.cancel_pending_and_running()
    assert a.observations()['pending'] == 0.
    assert a.observations()['running'] == 0.


def test_empty_calendar_has_no_pending_running_or_missed_cycle():
    a, b = make(count=0), make(ScanAppliance, count=0)
    a.start_cycle(1.); b.start_cycle(1.)
    same(a, b)
    assert a.service_summary() == b.service_summary()
    assert a.observations()['cycle_duration_steps'] == 0.


def test_permissive_direct_constructor_nonmonotonic_latest_bounds_keeps_scan_semantics():
    a, b = make(), make(ScanAppliance)
    for x in (a, b):
        # The direct constructor checks non-overlap by deadlines, unlike the dataframe parser.
        cycles = copy.deepcopy(x.deferrable_appliance_simulation.flexibility_schedule)
        cycles[0]['latest_start_time_step'] = 40
        x.deferrable_appliance_simulation = DeferrableApplianceSimulation(
            cycle_profiles={}, flexibility_schedule=cycles)
        x.reset()
        x.time_step = 16
    same(a, b)
    assert a.cycle_state['c0'] == 'pending'
    assert a.cycle_state['c1'] == 'missed'


def test_snapshot_without_a_cycle_index_rebuilds_it_lazily():
    appliance = make()
    appliance.start_cycle(1.)
    del appliance._cycle_index
    restored = pickle.loads(pickle.dumps(appliance))
    assert restored.observations() == appliance.observations()
    restored.next_time_step(); appliance.next_time_step()
    same(restored, appliance)
