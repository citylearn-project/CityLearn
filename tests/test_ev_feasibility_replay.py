"""Departure feasibility must obey the same physics without touching the vehicle."""
from copy import deepcopy
from types import SimpleNamespace as NS

import numpy as np
import pytest

from citylearn.base import EpisodeTracker
from citylearn.community_dataset import InventoryBattery
from citylearn.internal.kpi import CityLearnKPIService


def setup(*, power=10., max_soc=1., efficiency=1., loss=0., seconds=3600, initial=.2):
    tracker = EpisodeTracker(0, 3)
    tracker.next_episode(4, False, False, 0)
    battery = InventoryBattery(capacity=10., initial_soc=initial, max_charge_kw=power,
        max_discharge_kw=10., max_soc=max_soc, charging_efficiency=1.,
        discharging_efficiency=1., loss_coefficient=loss,
        episode_tracker=tracker, seconds_per_time_step=seconds, time_step_ratio=1.)
    battery.reset()
    sim = NS(electric_vehicle_current_soc=[initial]*4,
             electric_vehicle_id=['EV']*4)
    charger = NS(max_charging_power=10., efficiency=efficiency, seconds_per_time_step=seconds)
    return battery, sim, charger


@pytest.mark.parametrize('power,max_soc,eta,blocked,departure,target,expected', [
    (10., 1., 1., True, 1, .8, True),
    (10., .6, 1., False, 0, .8, False),
    (1., 1., 1., False, 0, .8, False),
    (5., 1., .5, False, 0, .6, True),
])
def test_four_audit_regressions(power, max_soc, eta, blocked, departure, target, expected):
    b, sim, charger = setup(power=power, max_soc=max_soc, efficiency=eta)
    before = deepcopy(b.__dict__)
    building = NS(_charging_constraints_enabled=True, _electrical_service_enabled=False,
                  _ops_service=NS(_power_outage_at_step=lambda t: blocked and t == 0))
    service = CityLearnKPIService(NS(seconds_per_time_step=3600))
    for _ in range(2):
        assert service._ev_departure_threshold_feasible(
            building, charger, sim, NS(battery=b), np.ones(4), departure, target) is expected
    assert b.time_step == 0
    np.testing.assert_array_equal(b.soc, before['_StorageDevice__soc'])
    assert list(b.capacity_history) == list(before['_capacity_history'])
    assert list(b.efficiency_history) == list(before['_efficiency_history'])
    assert b.episode_tracker is before['_Environment__episode_tracker'] or b.episode_tracker.episode_time_steps == 4


def test_initial_target_must_survive_standby_until_departure():
    b, sim, charger = setup(initial=.8, loss=.1)
    charger.max_charging_power = 0.
    service = CityLearnKPIService(NS(seconds_per_time_step=3600))
    assert not service._ev_departure_threshold_feasible(
        None, charger, sim, NS(battery=b), np.ones(4), 2, .75)


@pytest.mark.parametrize('seconds', [60, 900, 3600])
def test_replay_matches_real_trajectory_at_departure(seconds):
    b, sim, charger = setup(power=2., efficiency=.8, loss=.02, seconds=seconds)
    service = CityLearnKPIService(NS(seconds_per_time_step=seconds))
    real = deepcopy(b)
    for t in range(3):
        if t:
            real.next_time_step()
        real.charge(10.*seconds/3600.*.8)
    target = float(real.soc[2])
    for threshold, expected in [(target-1e-4, True), (target+1e-4, False)]:
        assert service._ev_departure_threshold_feasible(
            None, charger, sim, NS(battery=b), np.ones(4), 2, threshold) is expected


def test_historical_capacity_is_available_even_without_a_charge_call_on_arrival():
    b, sim, charger = setup()
    b.capacity_loss_coefficient = .5
    b.charge(6.)
    assert b.degraded_capacity == pytest.approx(8.5)
    b.next_time_step()
    b.force_set_soc(.2)
    # The new session has no real charge call yet; its capacity still must be known.
    assert b.capacity_before_step[1] == pytest.approx(8.5)
    service = CityLearnKPIService(NS(seconds_per_time_step=3600))
    assert not service._ev_departure_threshold_feasible(
        None, charger, sim, NS(battery=b), np.array([0., 1., 0., 0.]), 1, .9)
