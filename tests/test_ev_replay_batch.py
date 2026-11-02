"""Threshold batches share only one departure replay, preserving physical state."""
from copy import deepcopy
import pickle
from types import SimpleNamespace as NS

import numpy as np
import pytest

from citylearn.internal.kpi import CityLearnKPIService
from test_ev_feasibility_replay import setup
from test_ev_departure_audit import event


@pytest.mark.parametrize('seconds', [60, 900, 3600])
@pytest.mark.parametrize('audit', [False, True])
def test_batch_matches_real_full_trajectory_and_preserves_battery_rng(seconds, audit, monkeypatch):
    battery, sim, charger = setup(power=2., efficiency=.8, loss=.02, seconds=seconds)
    service = CityLearnKPIService(NS(seconds_per_time_step=seconds))
    limits = [10., 3., 1.]
    monkeypatch.setattr(service, '_ev_constraint_limited_charge_power_kw', lambda building, ch, t, cap: limits[t])
    monkeypatch.setattr(service, '_ev_power_outage_at_step', lambda building, t: t == 1)
    before = pickle.dumps(battery.__dict__)
    global_rng = pickle.dumps(np.random.get_state())
    physical = deepcopy(battery)
    for t, power in enumerate(limits):
        if t:
            physical.next_time_step()
        if audit and t == 1:
            power = 0.
        physical.charge(power * seconds / 3600. * .8)
    reached = float(physical.soc[2])
    thresholds = (reached + .01, reached, max(reached - .01, 0.))
    kwargs = dict(audit=True, audit_interval_start=0, audit_arrival_soc=.2) if audit else {}
    assert service._ev_departure_thresholds_feasible(
        None, charger, sim, NS(battery=battery), np.ones(4), 2, thresholds, **kwargs) == (False, True, True)
    assert pickle.dumps(battery.__dict__) == before
    assert pickle.dumps(np.random.get_state()) == global_rng
    assert not any('replay' in key for key in service.__dict__)


def test_legacy_all_zero_or_missing_thresholds_do_not_replay(monkeypatch):
    service = CityLearnKPIService(NS())
    def fail(*args, **kwargs):
        raise AssertionError('legacy trivial thresholds must not replay')
    monkeypatch.setattr(service, '_ev_departure_max_charge_soc', fail)
    assert service._ev_departure_thresholds_feasible(None, None, None, None, [], 0, [None, 0., -1.]) == (True, True, True)
    assert service._ev_departure_thresholds_feasible(None, None, None, None, [], 0, []) == ()


def test_nonfinite_replay_keeps_legacy_false_audit_unknown_and_zero_exception(monkeypatch):
    service = CityLearnKPIService(NS())
    monkeypatch.setattr(service, '_ev_departure_max_charge_soc', lambda *args, **kwargs: np.nan)
    assert service._ev_departure_thresholds_feasible(None, None, None, None, [], 0, [.8, .7, 0.]) == (False, False, True)
    assert service._ev_departure_thresholds_feasible(None, None, None, None, [], 0, [.8, .7, 0.], audit=True) == (None, None, None)


@pytest.mark.parametrize('invalid', ['battery', 'capacity', 'power', 'seconds', 'arrival'])
def test_permissive_legacy_inputs_keep_single_threshold_contract(invalid):
    battery, sim, charger = setup()
    if invalid == 'battery':
        battery = None
    elif invalid == 'capacity':
        battery = NS(capacity=0.)
    elif invalid == 'power':
        charger.max_charging_power = np.nan
    elif invalid == 'seconds':
        charger.seconds_per_time_step = 0.
    else:
        sim.electric_vehicle_current_soc = [-1.] * 4
        battery = NS(capacity=10., initial_soc=None, soc=[np.nan] * 4)
    service = CityLearnKPIService(NS(seconds_per_time_step=3600))
    ev = NS(battery=battery)
    expected = tuple(service._ev_departure_threshold_feasible(None, charger, sim, ev, np.ones(4), 2, target)
                     for target in [.8, .7, 0.])
    assert service._ev_departure_thresholds_feasible(None, charger, sim, ev, np.ones(4), 2, [.8, .7, 0.]) == expected == (True, True, True)


def test_new_batches_recompute_after_physical_inputs_change():
    battery, sim, charger = setup(power=10.)
    service = CityLearnKPIService(NS(seconds_per_time_step=3600))
    args = (None, charger, sim, NS(battery=battery), np.ones(4), 0, [.8, .7, .6])
    keys = set(service.__dict__)
    assert service._ev_departure_thresholds_feasible(*args) == (True, True, True)
    charger.max_charging_power = 0.
    assert service._ev_departure_thresholds_feasible(*args) == (False, False, False)
    charger.max_charging_power = 10.
    assert service._ev_departure_thresholds_feasible(*args) == (True, True, True)
    assert set(service.__dict__) == keys


def test_one_replay_per_legacy_and_audited_context_even_when_boundaries_differ(monkeypatch):
    service, building, charger, ev = event(actual=.2, initial=.2, target=.8, power=2., steps=3)
    other = NS(battery=deepcopy(ev.battery))
    charger.past_connected_evs[0] = other
    charger.charger_simulation.electric_vehicle_current_soc[1] = .3
    original = service._ev_departure_max_charge_soc
    contexts = []
    def replay(*args, **kwargs):
        contexts.append(kwargs.copy())
        return original(*args, **kwargs)
    monkeypatch.setattr(service, '_ev_departure_max_charge_soc', replay)
    before = pickle.dumps(ev.battery.__dict__)
    result = service._compute_ev_metrics(building)
    assert len(contexts) == 2
    assert sum(bool(c['audit']) for c in contexts) == 1
    audited = next(c for c in contexts if c['audit'])
    assert audited['audit_interval_start'] == 1
    assert audited['audit_arrival_soc'] == .3
    assert result['_departure_audit']['departures_count'] == 1
    assert result['departures_total'] == 1
    assert pickle.dumps(ev.battery.__dict__) == before
    contexts.clear()
    assert service._compute_ev_metrics(building) == result
    assert len(contexts) == 2  # No retention between evaluations.


def test_replay_does_not_stop_when_target_is_reached_before_standby_losses():
    battery, sim, charger = setup(initial=.8, loss=.1)
    charger.max_charging_power = 0.
    service = CityLearnKPIService(NS(seconds_per_time_step=3600))
    assert service._ev_departure_thresholds_feasible(
        None, charger, sim, NS(battery=battery), np.ones(4), 2, [.8, .75, .6]) == (False, False, True)
