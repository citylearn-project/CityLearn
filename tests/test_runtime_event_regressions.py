"""Regressions for real Portugal outage and dynamic-policy failures."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import NormalPolicy
from citylearn.citylearn import CityLearnEnv

SOURCE = Path(__file__).parent / 'data/minute_ev_demo'


def outage_schema(tmp_path, *, outage_start=0, appliance=False):
    root = tmp_path / 'outage'
    shutil.copytree(SOURCE, root)
    schema = json.loads((root / 'schema.json').read_text())
    schema.update(root_directory=str(root), physics_invariant_checks=True)
    frame = pd.read_csv(root / 'Building_1.csv')
    frame['power_outage'] = (np.arange(len(frame)) >= outage_start).astype(int)
    frame['solar_generation'] = 0.6
    frame['non_shiftable_load'] = 0.1
    frame[['cooling_demand', 'heating_demand', 'dhw_demand']] = 0.0
    frame.to_csv(root / 'Building_1.csv', index=False)
    b = schema['buildings']['Building_1']
    b['power_outage'] = {'simulate_power_outage': True}
    b['pv'] = {'type': 'citylearn.energy_model.PV', 'autosize': False,
               'attributes': {'nominal_power': 2.4, 'generation_mode': 'absolute'}}
    schema['electric_vehicles_def']['Electric_Vehicle_2'] = deepcopy(schema['electric_vehicles_def']['Electric_Vehicle_1'])
    schedule = pd.read_csv(root / 'charger_1_1.csv')
    schedule['electric_vehicle_id'] = 'Electric_Vehicle_2'
    schedule.to_csv(root / 'charger_2.csv', index=False)
    b['chargers']['charger_2'] = deepcopy(b['chargers']['charger_1_1'])
    b['chargers']['charger_2']['charger_simulation'] = 'charger_2.csv'
    if appliance:
        pd.DataFrame([{'profile_id': 'wash', 'duration_steps': 2,
                       'total_energy_kwh': 0.3, 'load_profile': '[0.1, 0.2]'}]).to_csv(root / 'profiles.csv', index=False)
        pd.DataFrame([{'cycle_id': 'cycle', 'profile_id': 'wash',
                       'earliest_start_time_step': 0, 'latest_start_time_step': 0,
                       'deadline_time_step': 1, 'priority': 1.0, 'must_run': True}]).to_csv(root / 'cycles.csv', index=False)
        schema['actions']['deferrable_appliance'] = {'active': True}
        b['deferrable_appliances'] = {'washer': {
            'type': 'citylearn.energy_model.DeferrableAppliance',
            'cycle_profiles_file': 'profiles.csv', 'flexibility_schedule_file': 'cycles.csv'}}
    return schema


def charging_actions(env, *, charge=1.0, wash=0.0):
    return [[charge if n.startswith('electric_vehicle_storage_') else
             wash if n.startswith('deferrable_appliance_') else 0.0
             for n in env.action_names[0]]]


@pytest.mark.parametrize('outage_start', [0, 1])
def test_multiple_chargers_share_remaining_outage_supply(tmp_path, outage_start):
    env = CityLearnEnv(outage_schema(tmp_path, outage_start=outage_start),
                       central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        while not env.terminated:
            t = env.time_step
            env.step(charging_actions(env))
            b = env.buildings[0]
            charging = sum(c.electricity_consumption[t] for c in b.electric_vehicle_chargers)
            if t >= outage_start:
                assert charging > 0.0
                assert charging + b.non_shiftable_load_device.electricity_consumption[t] <= 0.6 + 1e-6
                assert b.net_electricity_consumption[t] == pytest.approx(0.0)
            else:
                assert charging > 0.6  # Grid-connected operation is unrestricted by PV.
    finally:
        env.close()


@pytest.mark.parametrize('already_running', [False, True])
def test_outage_chargers_and_appliance_do_not_reuse_supply(tmp_path, already_running):
    env = CityLearnEnv(outage_schema(tmp_path, appliance=True), central_agent=True,
                       episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        env.step(charging_actions(env, charge=0.0 if already_running else 1.0, wash=1.0))
        b = env.buildings[0]
        assert b.deferrable_appliances_electricity_consumption[0] == pytest.approx(0.1 if already_running else 0.0)
        env.step(charging_actions(env))
        for t in [0, 1]:
            load = (b.non_shiftable_load_device.electricity_consumption[t]
                    + b.chargers_electricity_consumption[t]
                    + b.deferrable_appliances_electricity_consumption[t])
            assert load <= 0.6 + 1e-6
    finally:
        env.close()


def dynamic_schema():
    schema = json.loads((SOURCE / 'schema.json').read_text())
    schema.update(root_directory=str(SOURCE), interface='entity', topology_mode='dynamic')
    template = deepcopy(schema['buildings']['Building_1'])
    template.pop('chargers')
    schema['buildings'] = {name: deepcopy(template) for name in ['A', 'B', 'C']}
    schema['buildings']['C']['include'] = False
    schema['electric_vehicles_def'] = {}
    schema['actions']['electric_vehicle_storage']['active'] = False
    schema['topology_events'] = [
        {'id': 'leave_a', 'time_step': 1, 'operation': 'remove_member', 'target_member_id': 'A'},
        {'id': 'join_c', 'time_step': 2, 'operation': 'add_member', 'target_member_id': 'C'},
        {'id': 'leave_b', 'time_step': 3, 'operation': 'remove_member', 'target_member_id': 'B'},
        {'id': 'return_a', 'time_step': 3, 'operation': 'add_member', 'target_member_id': 'A'},
        {'id': 'replace_storage_out', 'time_step': 4, 'operation': 'remove_asset',
         'target_member_id': 'C', 'target_asset_type': 'electrical_storage', 'target_asset_id': 'electrical_storage'},
    ]
    return schema


@pytest.mark.parametrize('central', [False, True])
@pytest.mark.parametrize('start', [0, 1])
def test_normal_policy_tracks_dynamic_member_identity_and_reset(central, start):
    env = CityLearnEnv(dynamic_schema(), central_agent=central,
                       simulation_start_time_step=start, simulation_end_time_step=6,
                       episode_time_steps=7-start, random_seed=0)
    try:
        agent = NormalPolicy(env)
        for episode in range(2):
            obs, _ = env.reset(seed=0)
            expected = {}
            while not env.terminated:
                t = env.time_step
                names = [b.name for b in env.buildings]
                actions = agent.predict(obs)
                assert agent.action_dimension == [space.shape[0] for space in env.flat_action_space]
                ids = ['central_agent'] if central else names
                for name, action in zip(ids, actions):
                    expected.setdefault(name, {})[t] = list(action)
                obs, *_ = env.step(actions)
            assert set(agent.action_history_ids) == set(expected)
            for name, history in zip(agent.action_history_ids, agent.actions):
                for t in range(env.time_step):
                    assert history[t] == expected[name].get(t, [])
            if not central:
                assert agent.actions[agent.action_history_ids.index('C')][0] == []
    finally:
        env.close()


def test_normal_policy_learn_preserves_entity_observations_and_dynamic_rewards(monkeypatch):
    env = CityLearnEnv(dynamic_schema(), central_agent=False, episode_time_steps=7,
                       random_seed=0, render_mode='none', export_kpis_on_episode_end=False)
    try:
        agent = NormalPolicy(env)
        original = agent.predict

        def predict(observations, deterministic=None):
            assert isinstance(observations, dict)
            assert 'tables' in observations
            return original(observations, deterministic=deterministic)

        monkeypatch.setattr(agent, 'predict', predict)
        agent.learn(episodes=2, deterministic=True)
        assert agent.time_step == 6
        assert set(agent.action_history_ids) == {'A', 'B', 'C'}
    finally:
        env.close()
