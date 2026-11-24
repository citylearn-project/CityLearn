"""Departed and rejoining members keep their history in district series and KPIs."""
import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.building import DynamicsBuilding
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi_equipment import compute_phase_metrics
from test_deferrable_appliance_integration import _zero_entity_payload
from test_independent_balances import commands, scenario
from private_access import kpi_buildings, kpi_service, member_pool

DYNAMIC_SCHEMA = Path(__file__).resolve().parents[1] / 'data/datasets/citylearn_three_phase_dynamic_topology_demo/schema.json'
EVENT_STEP = 4
COUNTERFACTUAL_PROPERTIES = [
    f'net_electricity_consumption{kind}_without_storage{suffix}'
    for suffix in ('_and_partial_load_and_pv', '_and_partial_load', '_and_pv', '')
    for kind in ('_emission', '_cost', '')
]


def _dynamic_env(events, episode_time_steps):
    schema = json.loads(DYNAMIC_SCHEMA.read_text())
    schema['root_directory'] = str(DYNAMIC_SCHEMA.parent)
    schema['topology_events'] = events
    return CityLearnEnv(schema, episode_time_steps=episode_time_steps, random_seed=0)


def test_district_counterfactual_series_keep_departed_members():
    # With zero actions storage stays idle, so each without-storage series must equal the control
    # series, which counts every member for the steps at which it belonged to the district.
    env = _dynamic_env([
        dict(id='join', time_step=2, operation='add_member', target_member_id='Building_18'),
        dict(id='leave', time_step=EVENT_STEP, operation='remove_member', target_member_id='Building_6'),
    ], episode_time_steps=7)
    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step(_zero_entity_payload(env))

        names = [b.name for b in env.buildings]
        assert 'Building_18' in names and 'Building_6' not in names
        executed = env.time_step
        assert executed > EVENT_STEP

        # Version 1 removes the EV charging of the run and adds none back; with zero actions the EVs and the
        # storage stay idle, so each without-storage series must equal the control series. Version 2 adds the
        # BAU's EV charging back, from a BAU run that must find the joined and the departed member too.
        for version in (1, 2):
            env.baseline_version = version

            if version == 1:
                for kind in ('', '_emission'):
                    control = np.asarray(getattr(env, f'net_electricity_consumption{kind}'), dtype='float64')[:executed]
                    for condition in ('_without_storage', '_without_storage_and_partial_load'):
                        baseline = np.asarray(getattr(env, f'net_electricity_consumption{kind}{condition}'), dtype='float64')
                        np.testing.assert_allclose(baseline[:executed], control, rtol=0.0, atol=1e-4, err_msg=kind + condition)

            # Every reference series, PV-free variants included, is the sum of the members' series over
            # the steps at which they were members, as the building-level KPIs read them.
            members = kpi_buildings(env)
            assert {'Building_6', 'Building_18'} <= {b.name for b in members}
            for name in COUNTERFACTUAL_PROPERTIES:
                expected = np.zeros(executed)
                for b in members:
                    values = kpi_service(env)._energy_values(b, getattr(
                        b, name if isinstance(b, DynamicsBuilding) else name.replace('_and_partial_load', '')
                    ))
                    expected[:len(values)] += values
                actual = np.asarray(getattr(env, name), dtype='float64')[:executed]
                np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-4, err_msg=f'{name} (version {version})')

            kpis = env.evaluate_v2(include_business_as_usual=False)
            district = kpis[kpis['level'] == 'district'].set_index('cost_function')['value']
            if version == 1:
                for name in (
                    'district_energy_grid_total_import_delta_kwh',
                    'district_energy_grid_total_export_delta_kwh',
                    'district_emissions_total_delta_kgco2',
                ):
                    assert abs(float(district[name])) < 1e-4, name
    finally:
        env.close()


@pytest.mark.parametrize('events', [
    pytest.param([
        dict(id='leave', time_step=EVENT_STEP, operation='remove_member', target_member_id='Building_1'),
        dict(id='rejoin', time_step=EVENT_STEP + 2, operation='add_member', target_member_id='Building_1'),
    ], id='leave_and_rejoin'),
    pytest.param([
        dict(id='remove_pv', time_step=EVENT_STEP, operation='remove_asset', target_member_id='Building_1',
             target_asset_type='pv', target_asset_id='pv'),
    ], id='asset_removal'),
])
def test_topology_events_keep_recorded_charging_and_phase_histories(tmp_path, events):
    env = scenario(tmp_path, phase_limits=True, events=events)
    try:
        env.reset()
        building = member_pool(env)['Building_1']
        while env.time_step < EVENT_STEP - 1:
            env.step(commands(env, [0.5, -0.4], start=env.time_step == 0))

        recorded = EVENT_STEP - 1
        keys = ('_charging_constraint_violation_history', '_charging_total_power_history_kw')
        before = {key: getattr(building, key)[:recorded].copy() for key in keys}
        before_phases = {
            name: values[:recorded].copy() for name, values in building._charging_phase_power_history_kw.items()
        }
        assert all(np.any(values != 0.0) for values in before.values())
        assert any(np.any(values != 0.0) for values in before_phases.values())

        while not env.terminated:
            env.step(_zero_entity_payload(env))

        assert 'Building_1' in [b.name for b in env.buildings]
        for key, values in before.items():
            np.testing.assert_array_equal(getattr(building, key)[:recorded], values, err_msg=key)
        for name, values in before_phases.items():
            np.testing.assert_array_equal(building._charging_phase_power_history_kw[name][:recorded], values, err_msg=name)

        # The member's KPI window still starts at 0, so the phase peaks recorded before the event count.
        t_start, t_end = kpi_service(env)._building_active_window(building)
        assert t_start == 0
        peaks = compute_phase_metrics(kpi_service(env), building, t_start=t_start, t_final=t_end)['phase_import_peak_kw']
        for name, values in before_phases.items():
            assert peaks[name] >= float(np.clip(values, 0.0, None).max()), name
    finally:
        env.close()
