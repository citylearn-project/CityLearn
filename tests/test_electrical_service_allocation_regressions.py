"""Service clipping must preserve usable power after overlapping limit checks."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import NormalPolicy
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.building_ops import BuildingOpsService


PHASES = ('L1', 'L2', 'L3')
SOURCE = Path(__file__).parent / 'data/minute_ev_demo'


def allocation_case(powers, connections, base_kw, total_limits, phase_limits):
    chargers = {
        name: SimpleNamespace(max_charging_power=power, min_charging_power=4.14,
                              max_discharging_power=power, min_discharging_power=4.14)
        for name, power in powers.items()
    }
    building = SimpleNamespace(
        _electrical_service_enabled=True, _electrical_service_mode='three_phase',
        _electrical_service_default_split='balanced', _charger_lookup=chargers,
        _charger_phase_map=connections, electrical_storage=SimpleNamespace(nominal_power=16.),
        electrical_storage_phase_connection='L2', seconds_per_time_step=900,
        _electrical_service_limits={'total': total_limits, 'per_phase': phase_limits},
        _record_charging_constraint_state=lambda **kwargs: None,
    )
    ops = BuildingOpsService(building)
    ops._estimate_non_controllable_base_power = lambda actions: (
        base_kw, {phase: base_kw / 3 for phase in PHASES})
    building._ops_service = ops
    return building


def allocate(layer, building, ev_actions, storage_action=None):
    if layer == 'runtime':
        return building._ops_service._apply_electrical_service_constraints(ev_actions, storage_action)
    names = ['electric_vehicle_storage_' + name for name in ev_actions]
    values = list(ev_actions.values())
    if storage_action is not None:
        names.append('electrical_storage')
        values.append(storage_action)
    result = NormalPolicy._apply_electrical_service_limits(
        None, building, tuple(names), tuple([(-1., 1.)] * len(names)), values)
    return dict(zip(ev_actions, result)), result[-1] if storage_action is not None else None


@pytest.mark.parametrize('layer', ['policy', 'runtime'])
@pytest.mark.parametrize('direction', [1., -1.], ids=['import', 'export'])
@pytest.mark.parametrize('powers,expected_kw', [
    ({'a': 11.04, 'b': 11.04}, {'a': 9.189344, 'b': 9.189344}),
    ({'a': 22.08, 'b': 11.04}, {'a': 12.252458666666666, 'b': 6.126229333333333}),
])
def test_total_and_balanced_phase_limits_share_power_once(layer, direction, powers, expected_kw):
    # The real failure: stale phase totals cut 9.189 kW shares below the
    # 4.14 kW minimum, turning both chargers off despite available service.
    base_kw = direction * 2.321312
    building = allocation_case(
        powers, {name: 'all_phases' for name in powers}, base_kw,
        {'import_kw': 20.7, 'export_kw': 20.7},
        {phase: {'import_kw': 6.9, 'export_kw': 6.9} for phase in PHASES})
    actions, _ = allocate(layer, building, {name: direction for name in powers})
    delivered = {name: actions[name] * power for name, power in powers.items()}
    for name, power in delivered.items():
        assert power == pytest.approx(direction * expected_kw[name])
        assert abs(power) >= 4.14
    assert abs(base_kw + sum(delivered.values())) == pytest.approx(20.7)
    # Preserve proportional sharing: equal chargers get equal shares; a
    # double-rated request retains twice the share, without target priorities.
    assert actions['a'] == pytest.approx(actions['b'])


@pytest.mark.parametrize('layer', ['policy', 'runtime'])
@pytest.mark.parametrize('direction', [1., -1.], ids=['import', 'export'])
def test_shared_three_phase_charger_uses_reduced_totals_at_later_phases(layer, direction):
    building = allocation_case(
        {'a': 12., 'b': 6.}, {'a': 'all_phases', 'b': 'L1'}, direction * 3.,
        {'import_kw': 50., 'export_kw': 50.},
        {phase: {'import_kw': limit, 'export_kw': limit}
         for phase, limit in zip(PHASES, [8., 4., 4.])})
    actions, _ = allocate(layer, building, {'a': direction, 'b': direction})
    assert actions == pytest.approx({'a': direction * .7, 'b': direction * .7})
    # L1 binds. Its reduction already brings L2 and L3 to 3.8 kW; checking
    # their original 5 kW must not reduce the shared charger a second time.
    assert abs(direction + 12 * actions['a'] / 3 + 6 * actions['b']) == pytest.approx(8.)
    assert abs(direction + 12 * actions['a'] / 3) == pytest.approx(3.8)


@pytest.mark.parametrize('layer', ['policy', 'runtime'])
@pytest.mark.parametrize('direction', [1., -1.], ids=['EV-import', 'EV-export'])
def test_opposing_ev_and_storage_keep_feasible_power_after_total_and_phase_checks(layer, direction):
    building = allocation_case(
        {'a': 16.}, {'a': 'L1'}, 0., {'import_kw': 6., 'export_kw': 6.},
        {'L1': {'import_kw': 10., 'export_kw': 10.},
         'L2': {'import_kw': 4., 'export_kw': 4.}})
    actions, storage = allocate(layer, building, {'a': direction}, -direction * .5)
    # Final EV and BESS powers are 10 and -4 kW (or the reverse), so both
    # phase limits and the 6 kW total bind without avoidable extra clipping.
    assert 16 * actions['a'] == pytest.approx(direction * 10.)
    assert 16 * storage == pytest.approx(-direction * 4.)


def two_charger_schema(tmp_path, price):
    dataset = tmp_path / 'two_chargers'
    shutil.copytree(SOURCE, dataset)
    schema = json.loads((dataset / 'schema.json').read_text())
    schema['root_directory'] = str(dataset)
    schema['actions']['electrical_storage']['active'] = False
    building = schema['buildings']['Building_1']
    building['electrical_service'] = {
        'mode': 'three_phase', 'default_split': 'balanced',
        'limits': {'total': {'import_kw': 20.7, 'export_kw': 20.7},
                   'per_phase': {p: {'import_kw': 6.9, 'export_kw': 6.9} for p in PHASES}},
    }
    original = building['chargers']['charger_1_1']
    original.update(noise_std=0.)
    original['attributes'].update(
        max_charging_power=11.04, min_charging_power=4.14, phase_connection='all_phases')
    building['chargers']['charger_1_2'] = deepcopy(original)
    building['chargers']['charger_1_2']['charger_simulation'] = 'charger_1_2.csv'
    vehicle = schema['electric_vehicles_def']['Electric_Vehicle_1']
    vehicle['battery']['attributes'] = dict(
        capacity=64., nominal_power=10.488, initial_soc=.7, efficiency=.96,
        depth_of_discharge=1., loss_coefficient=0., capacity_loss_coefficient=0.,
        power_efficiency_curve=[[0., .96], [1., .96]],
        capacity_power_curve=[[0., 1.], [1., 1.]])
    schema['electric_vehicles_def']['Electric_Vehicle_2'] = deepcopy(vehicle)
    schedule = pd.read_csv(dataset / 'charger_1_1.csv')
    schedule['electric_vehicle_required_soc_departure'] = 60.
    schedule.to_csv(dataset / 'charger_1_1.csv', index=False)
    schedule['electric_vehicle_id'] = 'Electric_Vehicle_2'
    schedule.to_csv(dataset / 'charger_1_2.csv', index=False)
    load = pd.read_csv(dataset / 'Building_1.csv')
    load['non_shiftable_load'] = 2.321312 / 4
    load.to_csv(dataset / 'Building_1.csv', index=False)
    pricing = pd.read_csv(dataset / 'pricing.csv')
    pricing.loc[:, pricing.columns.str.startswith('electricity_pricing')] = price
    pricing.to_csv(dataset / 'pricing.csv', index=False)
    return schema


@pytest.mark.parametrize('driver', ['normal', 'raw-maximum'])
@pytest.mark.parametrize('price', [.01, 1.])
def test_two_ev_chargers_receive_available_power_and_keep_charging_above_targets(tmp_path, driver, price):
    env = CityLearnEnv(two_charger_schema(tmp_path, price), central_agent=True,
                       episode_time_steps=5, random_seed=0, physics_invariant_checks=True,
                       render_mode='none', export_kpis_on_episode_end=False)
    try:
        env.reset(seed=0)
        policy = NormalPolicy(env)
        building = env.buildings[0]
        chargers = list(building.electric_vehicle_chargers)
        vehicles = [c.connected_electric_vehicle for c in chargers]
        assert all(ev.battery.soc[0] > .6 for ev in vehicles)
        for t in range(4):
            actions = policy.predict([]) if driver == 'normal' else [[1., 1.]]
            env.step(actions)
            energies = [float(c.electricity_consumption[t]) for c in chargers]
            assert energies == pytest.approx([9.189344 / 4] * 2, abs=1e-6)
            assert building.net_electricity_consumption[t] * 4 == pytest.approx(20.7, abs=1e-5)
        assert all(ev.battery.soc[3] > .8 for ev in vehicles)
        assert policy.DEFINITION_VERSION == 'immediate-full-charge-v1'
    finally:
        env.close()
