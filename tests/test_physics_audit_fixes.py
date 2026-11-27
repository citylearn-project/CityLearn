"""Physics corrections from the 3.7.0 code audit (#420, #421, #423, #424, #425, #426, #461).

Each test reproduces its issue and checks the correction.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'datasets'


# --- #420 ---------------------------------------------------------------------------------------------

def _thermal_outage_env(tmp_path: Path, start: int = 4000, length: int = 6) -> CityLearnEnv:
    """`citylearn_challenge_2021` Building_1 with a large full battery and an outage over the whole window."""

    dataset = tmp_path / 'outage_thermal'
    shutil.copytree(DATASETS / 'citylearn_challenge_2021', dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)

    for index, (name, building) in enumerate(schema['buildings'].items()):
        building['include'] = index == 0
        if index != 0:
            continue
        frame = pd.read_csv(dataset / building['energy_simulation'])
        outage = np.zeros(len(frame), dtype=int)
        outage[start:start + length] = 1
        frame['power_outage'] = outage
        frame.to_csv(dataset / building['energy_simulation'], index=False)
        building['power_outage'] = {'simulate_power_outage': True}
        # A battery large enough to cover the whole islanded load.
        building['electrical_storage']['attributes'].update(capacity=2000.0, nominal_power=1000.0, initial_soc=1.0)
        for storage in ('cooling_storage', 'dhw_storage'):
            building[storage]['attributes']['initial_soc'] = 0.0

    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    return CityLearnEnv(str(path), central_agent=True, simulation_start_time_step=start,
                        simulation_end_time_step=start + length - 1, episode_time_steps=length, random_seed=0,
                        physics_invariant_checks=True)


def test_issue_420_outage_thermal_storage_charges_only_from_what_the_loads_leave(tmp_path):
    env = _thermal_outage_env(tmp_path)
    env.reset()
    names = env.action_names[0]
    actions = np.zeros(len(names), dtype='float32')
    for index, name in enumerate(names):
        if name == 'electrical_storage':
            actions[index] = -1.0
        elif name in ('cooling_storage', 'dhw_storage'):
            actions[index] = 1.0

    building = env.buildings[0]
    while not env.terminated:
        t = env.time_step
        env.step([actions.tolist()])
        assert building.power_outage_signal[t]
        # The battery covers the islanded load. 3.8.0 let the thermal storage take
        # that supply before the non-shiftable load, which was then reported as unserved.
        assert float(building.energy_to_non_shiftable_load[t]) == pytest.approx(float(building.non_shiftable_load[t]))
        assert float(building.non_shiftable_load_electricity_consumption[t]) \
            == pytest.approx(float(building.non_shiftable_load[t]))


# --- #421 ---------------------------------------------------------------------------------------------

MINUTE_DATASET = ROOT / 'tests' / 'data' / 'minute_ev_demo'
FLAT = [[0.0, 0.81], [1.0, 0.81]]  # round trip 0.81: each conversion keeps 0.9


def _minute_env(tmp_path: Path, battery: dict = None, ev_battery: dict = None, charger_frame: pd.DataFrame = None,
                charger: dict = None, steps: int = 4) -> CityLearnEnv:
    dataset = tmp_path / 'minute'
    shutil.copytree(MINUTE_DATASET, dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    schema.setdefault('observation_bundles', {})['entity_core_electrical'] = True
    building = schema['buildings']['Building_1']
    building['electrical_storage']['attributes'].update(battery or {})
    building['chargers']['charger_1_1']['attributes'].update(charger or {})
    schema['electric_vehicles_def']['Electric_Vehicle_1']['battery']['attributes'].update(ev_battery or {})
    if charger_frame is not None:
        charger_frame.to_csv(dataset / 'charger_1_1.csv', index=False)
    path = dataset / 'schema.json'
    path.write_text(json.dumps(schema), encoding='utf-8')
    return CityLearnEnv(str(path), interface='entity', episode_time_steps=steps, random_seed=0)


def _feature(env, observations, table: str, name: str) -> float:
    features = list(env.entity_specs['tables'][table]['features'])
    return float(observations['tables'][table][0][features.index(name)])


def _zero_actions(env) -> dict:
    return {'tables': {key: np.zeros_like(value) for key, value in env.action_space.sample()['tables'].items()}}


def test_issue_421_bess_available_discharge_uses_the_one_way_efficiency(tmp_path):
    # 1 kWh above the floor and a battery much more powerful than that energy: the SOC limits the discharge.
    env = _minute_env(tmp_path, battery=dict(capacity=5.0, nominal_power=20.0, initial_soc=0.2,
                                             power_efficiency_curve=FLAT, capacity_power_curve=[[0, 1], [1, 1]],
                                             loss_coefficient=0.0, capacity_loss_coefficient=0.0))
    try:
        observations, _ = env.reset(seed=0)
        available_kw = _feature(env, observations, 'storage', 'available_discharge_power_kw')
        action = _feature(env, observations, 'storage', 'available_discharge_action_normalized')
        # 1 kWh stored delivers 0.9 kWh in the 0.25 h step; 3.8.0 read 0.81 kWh.
        assert available_kw == pytest.approx(0.9 / 0.25)

        actions = _zero_actions(env)
        actions['tables']['building'][...] = -action
        env.step(actions)
        battery = env.buildings[0].electrical_storage
        assert -float(battery.electricity_consumption[0]) == pytest.approx(available_kw * 0.25, rel=1.0e-6)
        assert float(battery.soc[0]) == pytest.approx(0.0, abs=1.0e-9)
    finally:
        env.close()


def test_issue_421_bess_available_charge_uses_the_one_way_efficiency(tmp_path):
    env = _minute_env(tmp_path, battery=dict(capacity=5.0, nominal_power=20.0, initial_soc=0.8,
                                             power_efficiency_curve=FLAT, capacity_power_curve=[[0, 1], [1, 1]],
                                             loss_coefficient=0.0, capacity_loss_coefficient=0.0))
    try:
        observations, _ = env.reset(seed=0)
        # 1 kWh to full takes 1 / 0.9 kWh at the terminals in the 0.25 h step; 3.8.0 read 1 / 0.81 kWh.
        assert _feature(env, observations, 'storage', 'available_charge_power_kw') == pytest.approx(1.0 / 0.9 / 0.25)
    finally:
        env.close()


def _ev_charger_frame(required_soc_percent: float) -> pd.DataFrame:
    frame = pd.read_csv(MINUTE_DATASET / 'charger_1_1.csv')
    frame['electric_vehicle_required_soc_departure'] = required_soc_percent
    return frame


def test_issue_421_ev_power_features_are_ac_side_and_reach_the_target(tmp_path):
    env = _minute_env(
        tmp_path,
        ev_battery=dict(power_efficiency_curve=FLAT, capacity_power_curve=[[0, 1], [1, 1]], loss_coefficient=0.0,
                        capacity_loss_coefficient=0.0),
        charger_frame=_ev_charger_frame(60.0),
        steps=8,
    )
    try:
        observations, _ = env.reset(seed=0)
        conversion = 0.95 * 0.9  # charger efficiency times EV battery one-way efficiency
        energy = _feature(env, observations, 'charger', 'energy_to_required_soc_kwh')
        hours = _feature(env, observations, 'charger', 'hours_until_departure')
        assert energy == pytest.approx((0.6 - 0.4) * 20.0)
        assert hours == pytest.approx(1.0)
        required_kw = _feature(env, observations, 'charger', 'required_average_power_kw')
        assert required_kw == pytest.approx(energy / (hours * conversion))
        assert _feature(env, observations, 'charger', 'min_required_action_normalized') \
            == pytest.approx(required_kw / 7.2)
        assert _feature(env, observations, 'charger', 'charging_priority_ratio') == pytest.approx(required_kw / 7.2)
        assert _feature(env, observations, 'charger', 'max_deliverable_energy_until_departure_kwh') \
            == pytest.approx(7.2 * hours * conversion)

        # Charging at `min_required_action_normalized` until departure reaches the required SOC; 3.8.0 compared
        # the battery-side energy with the AC charger power and fell short by the conversion losses.
        ev = env.electric_vehicles[0]
        for _ in range(4):
            actions = _zero_actions(env)
            actions['tables']['charger'][...] = _feature(env, observations, 'charger', 'min_required_action_normalized')
            observations, *_ = env.step(actions)
        assert float(ev.battery.soc[3]) == pytest.approx(0.6, abs=1.0e-6)
    finally:
        env.close()


def test_issue_421_rule_baselines_add_their_service_margin_to_their_own_estimate_only():
    from citylearn.agents._baseline_engine import RBCBasicPolicy

    # The rule engine behind `citylearn.agents.baseline.RBCBasicPolicy`.
    policy = object.__new__(RBCBasicPolicy)
    policy.__dict__.update(ev_service_target_soc=0.0, energy_epsilon=1.0e-9, ev_deadline_buffer_hours=0.25,
                           ev_subhour_deadline_buffer_steps=0, step_hours=1.0)
    ctx = dict(connected=True, required_soc=0.8, soc=0.4, capacity=10.0, max_power=10.0, hours_to_departure=1.25)

    # The engine's battery-side estimate is 0.4 and gets the 0.05 margin for the losses it cannot observe.
    assert policy._required_ev_charge_rate({**ctx, 'min_required_action': 0.2}, margin_rate=0.05) == pytest.approx(0.45)
    # The AC-side simulator requirement already includes those losses: no margin on top (3.8.0 returned 0.55).
    assert policy._required_ev_charge_rate({**ctx, 'min_required_action': 0.5}, margin_rate=0.05) == pytest.approx(0.5)


# --- #423 ---------------------------------------------------------------------------------------------

def _tracker(steps: int = 4):
    from citylearn.base import EpisodeTracker

    tracker = EpisodeTracker(0, steps - 1)
    tracker.next_episode(steps, False, False, 0)
    return tracker


def _battery(**kwargs):
    from citylearn.energy_model import Battery

    attributes = dict(capacity=10.0, nominal_power=5.0, initial_soc=0.5, efficiency=0.9, loss_coefficient=0.0,
                      capacity_loss_coefficient=0.0, episode_tracker=_tracker(), seconds_per_time_step=3600,
                      random_seed=0, capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
                      power_efficiency_curve=[[0.0, 0.9], [1.0, 0.9]])
    attributes.update(kwargs)
    battery = Battery(**attributes)
    battery.reset()
    return battery


def test_issue_423_battery_efficiency_curve_is_held_at_its_end_points():
    # The issue's example: 3.8.0 extrapolated to 1.05 at full power and stopped the run with an AssertionError.
    battery = _battery(power_efficiency_curve=[[0.0, 0.85], [0.5, 0.95]])

    assert battery.get_current_efficiency(5.0) == pytest.approx(0.95)
    battery.charge(5.0)
    assert float(battery.soc[0]) * 10.0 == pytest.approx(5.0 + 5.0 * 0.95 ** 0.5)


def test_issue_423_battery_power_curves_are_held_at_their_end_points():
    battery = _battery(capacity_power_curve=[[0.2, 1.0], [0.8, 0.5]], discharge_power_curve=[[0.2, 0.5], [0.8, 1.0]],
                       initial_soc=1.0)
    # 3.8.0 extrapolated to 0.333 and 1.167 of nominal power.
    assert battery.get_max_input_power() == pytest.approx(5.0 * 0.5)
    assert battery.get_max_output_power() == pytest.approx(5.0 * 1.0)
    assert battery.get_max_input_power(energy_init=0.0) == pytest.approx(5.0 * 1.0)
    assert battery.get_max_output_power(energy_init=0.0) == pytest.approx(5.0 * 0.5)


@pytest.mark.parametrize('name, curve, message', [
    ('power_efficiency_curve', [[0.5, 0.9], [0.2, 0.9]], 'strictly increasing'),
    ('power_efficiency_curve', [[0.0, 0.9], [1.0, 1.05]], r'\(0, 1\]'),
    ('power_efficiency_curve', [[0.0, 0.0], [1.0, 0.9]], r'\(0, 1\]'),
    ('capacity_power_curve', [[0.0, 1.0], [1.2, 1.0]], r'within \[0, 1\]'),
    ('capacity_power_curve', [[0.0, -0.1], [1.0, 1.0]], '>= 0'),
    ('discharge_power_curve', [[0.0, 1.0]], 'at least two'),
])
def test_issue_423_invalid_battery_curves_fail_at_construction(name, curve, message):
    with pytest.raises(ValueError, match=f'{name}.*{message}'):
        _battery(**{name: curve})


@pytest.mark.parametrize('name, curve', [
    ('charge_efficiency_curve', [[0.0, 0.9], [1.0, 1.05]]),
    ('discharge_efficiency_curve', [[1.0, 0.9], [0.0, 0.9]]),
])
def test_issue_423_invalid_charger_curves_fail_at_construction(tmp_path, name, curve):
    # 3.8.0 accepted a charging efficiency above 1, which creates energy.
    with pytest.raises(ValueError, match=f'buildings.Building_1.chargers.charger_1_1.attributes.{name}'):
        _minute_env(tmp_path, charger={name: curve})


def test_issue_423_invalid_battery_curve_error_names_the_schema_path(tmp_path):
    with pytest.raises(ValueError, match='buildings.Building_1.electrical_storage.attributes.power_efficiency_curve'):
        _minute_env(tmp_path, battery=dict(power_efficiency_curve=[[0.0, 0.9], [1.0, 1.1]]))

    with pytest.raises(ValueError, match='electric_vehicles_def.Electric_Vehicle_1.battery.attributes.capacity_power_curve'):
        _minute_env(tmp_path / 'ev', ev_battery=dict(capacity_power_curve=[[1.0, 1.0], [0.0, 1.0]]))


# --- #424 ---------------------------------------------------------------------------------------------

def _limited_charger(**kwargs):
    from citylearn.data import ChargerSimulation
    from citylearn.electric_vehicle import ElectricVehicle
    from citylearn.electric_vehicle_charger import Charger

    tracker = _tracker()
    # Nearly full EV: it accepts 0.2 kWh, much less than the 1.8 kWh a full-power command delivers.
    battery = _battery(capacity=20.0, nominal_power=7.2, initial_soc=0.99, efficiency=1.0,
                       power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]], episode_tracker=tracker,
                       seconds_per_time_step=900)
    ev = ElectricVehicle(episode_tracker=tracker, battery=battery, seconds_per_time_step=900)
    ev.reset()
    simulation = ChargerSimulation(
        electric_vehicle_charger_state=[1] * 4, electric_vehicle_id=[ev.name] * 4,
        electric_vehicle_departure_time=[-1] * 4, electric_vehicle_required_soc_departure=[-0.1] * 4,
        electric_vehicle_estimated_arrival_time=[-1] * 4, electric_vehicle_estimated_soc_arrival=[-0.1] * 4,
    )
    charger = Charger(episode_tracker=tracker, charger_simulation=simulation, charger_id='test', max_charging_power=7.2,
                      max_discharging_power=7.2, seconds_per_time_step=900, **kwargs)
    charger.reset()
    charger.connected_electric_vehicle = ev
    return charger, ev


def test_issue_424_charger_efficiency_is_read_at_the_applied_power():
    curve = [[0.0, 0.5], [1.0, 1.0]]
    charger, ev = _limited_charger(charge_efficiency_curve=curve)

    preview_kw = charger.preview_power_kw(1.0)
    charger.update_connected_electric_vehicle_soc(1.0)
    accepted = float(ev.battery.energy_balance[0])
    ac = float(charger.electricity_consumption[0])
    assert accepted == pytest.approx(0.2, rel=1.0e-6)

    # The charger efficiency at the applied AC power converts it to the accepted energy. 3.8.0 used the
    # efficiency at the commanded full power (1.0), so the AC energy equalled the accepted energy.
    efficiency = charger.get_efficiency(ac / 0.25 / 7.2, True)
    assert efficiency < 0.65
    assert ac * efficiency == pytest.approx(accepted, rel=1.0e-6)
    assert preview_kw * 0.25 == pytest.approx(ac, rel=1.0e-6)


def test_issue_424_constant_charger_efficiency_is_unchanged():
    charger, ev = _limited_charger(efficiency=0.9)
    charger.update_connected_electric_vehicle_soc(1.0)

    assert float(charger.electricity_consumption[0]) == pytest.approx(float(ev.battery.energy_balance[0]) / 0.9)


# --- #425 ---------------------------------------------------------------------------------------------

ASSETS_DEMO = DATASETS / 'citylearn_three_phase_dynamic_assets_only_demo'


def _assets_demo_schema(change=None, source_battery: dict = None) -> dict:
    schema = json.loads((ASSETS_DEMO / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(ASSETS_DEMO)
    if source_battery:
        schema['buildings']['Building_1']['electrical_storage']['attributes'].update(source_battery)
    if change is not None:
        change(schema['topology_events'])
    return schema


def _event(events, event_id):
    return next(event for event in events if event['id'] == event_id)


def test_issue_425_topology_efficiency_override_takes_effect_after_reset():
    def change(events):
        _event(events, 'evt_add_batt_b3')['overrides'] = {'efficiency': 0.7}

    # The battery event (time step 2100) is replayed when the episode starts after it.
    env = CityLearnEnv(_assets_demo_schema(change), interface='entity', topology_mode='dynamic',
                       simulation_start_time_step=2101, simulation_end_time_step=2104, episode_time_steps=4)
    try:
        for _ in range(2):
            env.reset(seed=0)
            battery = next(b for b in env.buildings if b.name == 'Building_3').electrical_storage
            # 3.8.0 kept the source's 0.9 after reset and simulated the source's efficiency curve.
            assert battery.efficiency == pytest.approx(0.7)
            assert float(np.max(battery.power_efficiency_curve[1])) == pytest.approx(0.7)
    finally:
        env.close()


def test_issue_425_efficiency_override_without_effect_is_rejected():
    def change(events):
        _event(events, 'evt_add_batt_b3')['overrides'] = {'efficiency': 0.7}

    schema = _assets_demo_schema(change, source_battery={'power_efficiency_curve': [[0.0, 0.9], [1.0, 0.9]]})
    with pytest.raises(ValueError, match='power_efficiency_curve'):
        CityLearnEnv(schema, interface='entity', topology_mode='dynamic', episode_time_steps=4)


# --- #426 ---------------------------------------------------------------------------------------------

def test_issue_426_loss_coefficient_reads_back_the_hourly_value():
    from citylearn.energy_model import StorageTank

    tank = StorageTank(capacity=10.0, loss_coefficient=0.009, initial_soc=1.0, seconds_per_time_step=900,
                       episode_tracker=_tracker(), random_seed=0)
    tank.reset()
    step_loss = 1.0 - (1.0 - 0.009) ** 0.25

    # 3.8.0 read back the per-step value, 0.00226, under the schema key.
    assert tank.loss_coefficient == pytest.approx(0.009)
    assert tank.step_loss_fraction == pytest.approx(step_loss)
    metadata = tank.get_metadata()
    assert metadata['loss_coefficient'] == pytest.approx(0.009)
    assert metadata['step_loss_fraction'] == pytest.approx(step_loss)

    # Re-assigning the value read back keeps the physics.
    tank.loss_coefficient = tank.loss_coefficient
    tank.next_time_step()
    assert float(tank.soc[1]) == pytest.approx(1.0 - step_loss)


# --- #461 ---------------------------------------------------------------------------------------------

def test_issue_461_events_for_members_not_loaded_fail_at_construction():
    schema = DATASETS / 'pt_rec_30' / 'evaluation' / 'rec_30_topology.json'
    # 3.8.0 accepted this and failed at step 4080, when Member_007 joins.
    with pytest.raises(ValueError, match="Member_007.*not loaded"):
        CityLearnEnv(str(schema), buildings=['Member_002', 'Member_003'])


@pytest.mark.parametrize('event, message', [
    # A misspelt charger id was ignored when the event fired.
    ({'id': 'bad', 'time_step': 1600, 'operation': 'remove_asset', 'target_member_id': 'Building_7',
      'target_asset_type': 'charger', 'target_asset_id': 'charger_7_x'}, "removes charger 'charger_7_x'"),
    # An id that exists already was ignored when the event fired.
    ({'id': 'bad', 'time_step': 1600, 'operation': 'add_asset', 'target_member_id': 'Building_7',
      'target_asset_type': 'charger', 'target_asset_id': 'charger_7_1', 'source_member_id': 'Building_18',
      'source_asset_id': 'charger_18_1'}, "already has one"),
    # Without source_asset_id the event copies the target id from the source, which does not have it.
    ({'id': 'bad', 'time_step': 1600, 'operation': 'add_asset', 'target_member_id': 'Building_7',
      'target_asset_type': 'charger', 'target_asset_id': 'charger_7_dyn', 'source_member_id': 'Building_18'},
     "copies charger 'charger_7_dyn'"),
    # Override keys of a charger added without source_asset_id were not checked at construction.
    ({'id': 'bad', 'time_step': 1600, 'operation': 'add_asset', 'target_member_id': 'Building_7',
      'target_asset_type': 'charger', 'target_asset_id': 'charger_18_1', 'source_member_id': 'Building_18',
      'overrides': {'max_charging_powr': 3.0}}, 'Unknown override'),
])
def test_issue_461_invalid_asset_events_fail_at_construction(event, message):
    schema = _assets_demo_schema(lambda events: events.append(event))

    with pytest.raises(ValueError, match=message):
        CityLearnEnv(schema, interface='entity', topology_mode='dynamic', episode_time_steps=4)


def test_issue_461_remove_then_reinstall_of_a_charger_is_accepted():
    def change(events):
        events.append({'id': 'reinstall', 'time_step': 1600, 'operation': 'add_asset', 'target_member_id': 'Building_5',
                       'target_asset_type': 'charger', 'target_asset_id': 'charger_5_1'})

    env = CityLearnEnv(_assets_demo_schema(change), interface='entity', topology_mode='dynamic', episode_time_steps=4)
    env.close()
