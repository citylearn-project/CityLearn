"""Shared kW budgets must remain pure and subordinate to runtime physics."""

from copy import deepcopy

import numpy as np
import pytest

from citylearn.agents.baseline import NormalPolicy
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.balance_audit import IndependentBalanceAudit
from citylearn.internal.electrical_limits import (
    allocate_electrical_service,
    electrical_service_violation_kw,
)
from test_electrical_service_allocation_regressions import two_charger_schema


def request(kw):
    return {'request_total_kw': kw, 'request_phase_kw': {'L1': kw}}


def test_allocation_does_not_change_inputs_or_share_results_between_calls():
    inputs = (2., {'L1': 2.}, {'a': request(8.), 'b': request(4.)},
              {'import_kw': 8.}, {'L1': {'import_kw': 8.}}, ['L1'])
    before = deepcopy(inputs)
    allocation = allocate_electrical_service(*inputs)
    assert inputs == before
    assert allocation.scales == pytest.approx({'a': .5, 'b': .5})
    assert allocation.total_kw == pytest.approx(8.)
    assert allocation.phase_kw == pytest.approx({'L1': 8.})
    # Pressure counts total and phase scopes independently; it is not energy shed.
    assert allocation.requested_violation_kw == pytest.approx(12.)
    assert allocation.residual_violation_kw == 0.
    allocation.scales['a'] = 0.
    allocation.phase_kw['L1'] = 999.
    again = allocate_electrical_service(*inputs)
    assert again.scales['a'] == pytest.approx(.5)
    assert again.phase_kw['L1'] == pytest.approx(8.)


@pytest.mark.parametrize('direction', [1., -1.], ids=['import', 'export'])
def test_uncontrollable_overload_stays_visible_and_helpful_power_is_kept(direction):
    # Fixed 8 kW, 2 kW helpful opposite flow, 10 kW harmful request: even after
    # removing the latter, 1 kW exceeds the 5 kW limit. Do not claim feasibility.
    allocation = allocate_electrical_service(
        direction * 8., {'L1': direction * 8.},
        {'harmful': request(direction * 10.), 'helpful': request(-direction * 2.)},
        {'import_kw': 5., 'export_kw': 5.}, {}, ['L1'])
    assert allocation.scales == {'harmful': 0., 'helpful': 1.}
    assert allocation.total_kw == pytest.approx(direction * 6.)
    assert allocation.requested_violation_kw == pytest.approx(11.)
    assert allocation.residual_violation_kw == pytest.approx(1.)


@pytest.mark.parametrize('limit', [None, float('inf'), float('nan')], ids=['absent', 'infinite', 'nan'])
def test_unbounded_limits_preserve_requests(limit):
    allocation = allocate_electrical_service(
        2., {'L1': 2.}, {'a': request(10.)},
        {'import_kw': limit}, {'L1': {'import_kw': limit}}, ['L1'])
    assert allocation.scales == {'a': 1.}
    assert allocation.total_kw == 12.
    assert allocation.requested_violation_kw == allocation.residual_violation_kw == 0.


@pytest.mark.parametrize('direction', [1., -1.], ids=['import', 'export'])
def test_zero_limit_is_a_real_budget_and_does_not_increase_helpful_requests(direction):
    allocation = allocate_electrical_service(
        direction * 5., {'L1': direction * 5.},
        {'helpful': request(-direction * 2.), 'harmful': request(direction * 4.)},
        {'import_kw': 0., 'export_kw': 0.}, {}, ['L1'])
    assert allocation.scales == {'helpful': 1., 'harmful': 0.}
    assert allocation.total_kw == pytest.approx(direction * 3.)
    assert allocation.residual_violation_kw == pytest.approx(3.)


def test_no_controls_preserves_fixed_load_and_phase_pressure():
    allocation = allocate_electrical_service(
        12., {'L1': 7., 'L2': -3., 'L3': 8.}, {},
        {'import_kw': 10.}, {'L1': {'import_kw': 4.}, 'L2': {'export_kw': 1.}},
        ['L1', 'L2', 'L3'])
    assert allocation.scales == {}
    assert allocation.total_kw == 12.
    assert allocation.phase_kw == {'L1': 7., 'L2': -3., 'L3': 8.}
    assert allocation.requested_violation_kw == allocation.residual_violation_kw == 7.
    assert electrical_service_violation_kw(
        12., allocation.phase_kw, {'import_kw': 10.},
        {'L1': {'import_kw': 4.}, 'L2': {'export_kw': 1.}}, ['L1', 'L2', 'L3']) == 7.


def test_prediction_leaves_device_and_runtime_accounting_state_untouched(tmp_path):
    env = CityLearnEnv(two_charger_schema(tmp_path, .2), central_agent=True,
                       episode_time_steps=5, random_seed=0, physics_invariant_checks=True,
                       render_mode='none', export_kpis_on_episode_end=False)
    try:
        env.reset(seed=0)
        policy = NormalPolicy(env)
        building = env.buildings[0]
        state = deepcopy(building._charging_constraints_state)
        penalties = (building._charging_constraint_penalty_kwh, building._charging_constraint_last_penalty_kwh)
        chargers = list(building.electric_vehicle_chargers)
        stocks = [c.connected_electric_vehicle.battery.soc.copy() for c in chargers]
        meters = [c.electricity_consumption.copy() for c in chargers]
        action = policy.predict([])
        assert action[0] == pytest.approx([9.189344 / 11.04] * 2)
        assert building._charging_constraints_state == state
        assert (building._charging_constraint_penalty_kwh, building._charging_constraint_last_penalty_kwh) == penalties
        for charger, stock, meter in zip(chargers, stocks, meters):
            np.testing.assert_array_equal(charger.connected_electric_vehicle.battery.soc, stock)
            np.testing.assert_array_equal(charger.electricity_consumption, meter)
    finally:
        env.close()


def test_runtime_recalculates_budget_after_an_underestimated_policy_load(tmp_path, monkeypatch):
    env = CityLearnEnv(two_charger_schema(tmp_path, .2), central_agent=True,
                       episode_time_steps=5, random_seed=0, physics_invariant_checks=True,
                       render_mode='none', export_kpis_on_episode_end=False)
    try:
        env.reset(seed=0)
        policy = NormalPolicy(env)
        building = env.buildings[0]
        # An inaccurate prospective estimate must not override runtime's actual
        # base load. Restore the estimator before execution; no meter is changed.
        with monkeypatch.context() as prediction:
            prediction.setattr(building._ops_service, '_estimate_non_controllable_base_power',
                               lambda actions: (0., dict.fromkeys(('L1', 'L2', 'L3'), 0.)))
            actions = policy.predict([])
        assert actions[0] == pytest.approx([10.35 / 11.04] * 2)
        with IndependentBalanceAudit(env) as audit:
            env.step(actions)
            actual = [float(c.electricity_consumption[0]) for c in building.electric_vehicle_chargers]
            assert actual == pytest.approx([9.189344 / 4] * 2, abs=1e-6)
            assert building.net_electricity_consumption[0] * 4 == pytest.approx(20.7, abs=1e-5)
            while not env.terminated:
                env.step(policy.predict([]))
            assert audit.finish()['status'] == 'pass'
    finally:
        env.close()
