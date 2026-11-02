"""Actual execution, topology and export regressions for machine service."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from test_deferrable_appliance_integration import (
    _schema_with_deferrable_appliance, _zero_flat_actions, _zero_entity_payload,
)


def make_env(tmp_path, *, earliest=0, latest=3, start=0, steps=8, events=None, seconds=900):
    path = _schema_with_deferrable_appliance(tmp_path, earliest=earliest, latest=latest)
    schema = json.loads(path.read_text())
    schema.update(physics_invariant_checks=True, seconds_per_time_step=seconds,
                  simulation_start_time_step=start, simulation_end_time_step=start+steps-1,
                  episode_time_steps=steps)
    if events is not None:
        schema.update(interface='entity', topology_mode='dynamic', topology_events=events)
        # A remaining member keeps the environment meaningful while Building_1 leaves.
        schema['buildings']['Building_2'] = deepcopy(schema['buildings']['Building_1'])
        schema['buildings']['Building_2']['deferrable_appliances'] = {}
    return CityLearnEnv(schema, random_seed=0, offline=True, render_directory=tmp_path/'exports',
                        export_kpis_on_episode_end=False)


def action(env, start=False):
    if env.interface == 'entity':
        result = _zero_entity_payload(env)
        if start:
            result['map'] = {'deferrable_appliance:washer_1': {'start': 1.0}}
        return result
    result = _zero_flat_actions(env)
    if start:
        result[0][env.action_names[0].index('deferrable_appliance_washer_1')] = 1.0
    return result


def request(env):
    rows = env.get_deferrable_service_audit()['records']
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize('seconds', [60, 900, 3600])
@pytest.mark.parametrize('feedback', [True, False])
def test_executed_prefix_completion_and_reset(tmp_path, seconds, feedback):
    env = make_env(tmp_path, seconds=seconds)
    try:
        env.reset()
        step = env.step if feedback else env._runtime_service.step_without_feedback
        assert request(env)['state'] == 'excluded'
        step(action(env, True))
        row = request(env)
        assert row['state'] == 'running'
        assert row['served_energy_kwh'] == pytest.approx(.1)
        assert row['outstanding_energy_kwh'] == pytest.approx(.2)
        before = deepcopy(env.get_deferrable_service_audit())
        # Legacy evaluation may finalize a reserved cycle; audited service must not change.
        env.evaluate_v2(include_business_as_usual=False)
        assert env.get_deferrable_service_audit() == before
        step(action(env))
        assert request(env)['state'] == 'completed'
        summary = env.get_deferrable_service_audit()['district']
        assert summary['physical_energy_kwh'] == pytest.approx(.3)
        assert summary['physical_balance_residual_kwh'] == pytest.approx(0, abs=1e-7)
        assert summary['service_balance_residual_kwh'] == pytest.approx(0, abs=1e-7)
        env.reset()
        assert request(env)['served_energy_kwh'] == 0
        assert request(env)['state'] == 'excluded'
    finally:
        env.close()


@pytest.mark.parametrize('kind', ['asset', 'member'])
def test_removal_and_reentry_preserve_partial_service_once(tmp_path, kind):
    common = dict(target_member_id='Building_1')
    if kind == 'asset':
        common.update(target_asset_type='deferrable_appliance', target_asset_id='washer_1')
    events = [dict(id='remove', time_step=3, operation='remove_'+kind, **common),
              dict(id='restore', time_step=4, operation='add_'+kind, **common)]
    env = make_env(tmp_path, earliest=2, latest=5, start=2, steps=6, events=events)
    try:
        env.reset()
        old = env.buildings[0].deferrable_appliances[0]
        env.step(action(env, True))
        row = request(env)
        assert row['state'] == 'cancelled'
        assert row['reason'] == kind+'_removed'
        assert row['exit_time_step'] == 3
        assert row['served_energy_kwh'] == pytest.approx(.1)
        assert row['final_unserved_energy_kwh'] == pytest.approx(.2)
        env.step(action(env))
        history = env._topology_service.historical_deferrable_appliances('Building_1')
        assert len(history) == 2 and history[0] is old
        assert history[1].service_audit()['records'][0]['reason'] == 'already_accounted_previous_instance'
        while not env.terminated:
            env.step(action(env, True))
        assert request(env)['state'] == 'cancelled'
        summary = env.get_deferrable_service_audit()['district']
        assert summary['offered_count'] == 1
        assert summary['duplicate_offered_count'] == 0
        assert summary['physical_energy_kwh'] == pytest.approx(.1)
        assert summary['physical_balance_residual_kwh'] == pytest.approx(0, abs=1e-7)
    finally:
        env.close()


def test_outage_blocked_start_is_real_unserved_service(tmp_path):
    path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    csv_path = path.parent/'Building_1.csv'
    frame = pd.read_csv(csv_path)
    frame['power_outage'] = 1
    for column in ('solar_generation', 'non_shiftable_load', 'cooling_demand', 'heating_demand', 'dhw_demand'):
        frame[column] = 0.0
    frame.to_csv(csv_path, index=False)
    schema = json.loads(path.read_text())
    schema['physics_invariant_checks'] = True
    schema['buildings']['Building_1']['power_outage'] = {'simulate_power_outage': True}
    env = CityLearnEnv(schema, episode_time_steps=4, offline=True, export_kpis_on_episode_end=False)
    try:
        env.reset()
        env.step(action(env, True))
        row = request(env)
        assert row['state'] == 'missed'
        assert row['reason'] == 'start_window_elapsed'
        assert row['served_energy_kwh'] == 0
        assert row['final_unserved_energy_kwh'] == pytest.approx(.3)
        assert env.get_deferrable_service_audit()['district']['physical_energy_kwh'] == 0
    finally:
        env.close()


def test_kpi_export_has_request_evidence_and_definition(tmp_path):
    env = make_env(tmp_path, earliest=0, latest=0)
    try:
        env.reset()
        env.step(action(env, True))
        env.step(action(env))
        env.export_final_kpis(filepath='audit.csv', include_business_as_usual=False)
        output = Path(env.new_folder_path)
        evidence = json.loads((output/'audit.deferrable_service.json').read_text())
        manifest = json.loads((output/'audit.manifest.json').read_text())
        assert evidence['definition_version'] == 'deferrable-service-audit-v1'
        assert manifest['deferrable_service_audit']['definition_version'] == evidence['definition_version']
        assert evidence['records'][0]['state'] == 'completed'
        frame = pd.read_csv(output/'audit.csv').set_index('KPI')
        assert frame.loc['district_deferrable_appliance_audit_completed_count', 'District'] == 1
        assert frame.loc['district_deferrable_appliance_audit_served_energy_kwh', 'District'] == pytest.approx(.3)
        assert frame.loc['district_deferrable_appliance_audit_resolved_coverage_ratio', 'District'] == 1
    finally:
        env.close()


def test_dynamic_window_keeps_global_calendar_requests(tmp_path):
    env = make_env(tmp_path, earliest=5, latest=5, start=4, steps=4, events=[])
    try:
        env.reset()
        assert request(env)['reason'] == 'not_yet_available'
        env.step(action(env))
        env.step(action(env, True))
        env.step(action(env))
        row = request(env)
        assert row['start_time_step'] == 5
        assert row['state'] == 'completed'
        assert row['served_energy_kwh'] == pytest.approx(.3)
    finally:
        env.close()


def test_member_reentry_retains_later_calendar_requests(tmp_path):
    path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=1)
    schedule = pd.read_csv(path.parent/'washer_flexibility_schedule.csv')
    second = schedule.iloc[0].to_dict()
    second.update(cycle_id='cycle_2', earliest_start_time_step=4,
                  latest_start_time_step=4, deadline_time_step=5)
    pd.concat([schedule, pd.DataFrame([second])], ignore_index=True).to_csv(
        path.parent/'washer_flexibility_schedule.csv', index=False)
    schema = json.loads(path.read_text())
    schema.update(interface='entity', topology_mode='dynamic', physics_invariant_checks=True,
                  topology_events=[dict(id='out', time_step=2, operation='remove_member', target_member_id='Building_1'),
                                   dict(id='in', time_step=3, operation='add_member', target_member_id='Building_1')])
    schema['buildings']['Building_2'] = deepcopy(schema['buildings']['Building_1'])
    schema['buildings']['Building_2']['deferrable_appliances'] = {}
    env = CityLearnEnv(schema, random_seed=0, offline=True, export_kpis_on_episode_end=False)
    try:
        env.reset()
        while not env.terminated:
            env.step(action(env, env.time_step in (0, 4)))
        audit = env.get_deferrable_service_audit()
        rows = audit['records']
        assert len(rows) == 2
        assert [r['state'] for r in rows] == ['completed', 'completed']
        assert audit['district']['offered_count'] == 2
        assert audit['district']['duplicate_offered_count'] == 0
        assert audit['district']['served_energy_kwh'] == pytest.approx(.6)
    finally:
        env.close()
