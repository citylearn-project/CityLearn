"""Conservation across low-SOC arrivals, reserve limits and standby losses."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.energy_model import Battery
from citylearn.internal.physics_invariants import CityLearnPhysicsInvariantService


def _battery(initial_soc=.5, loss=0., seconds=900):
    tracker = EpisodeTracker(0, 7)
    tracker.next_episode(8, False, False, 0)
    battery = Battery(
        capacity=60., nominal_power=11., initial_soc=initial_soc,
        depth_of_discharge=.8, efficiency=.64, loss_coefficient=loss,
        capacity_loss_coefficient=0.,
        power_efficiency_curve=[[0., .64], [1., .64]],
        capacity_power_curve=[[0., 1.], [1., 1.]],
        episode_tracker=tracker, seconds_per_time_step=seconds,
        time_step_ratio=1.,
    )
    battery.reset()
    return battery


def test_initial_soc_below_reserve_is_not_filled_for_free():
    battery = _battery(initial_soc=.1)
    assert battery.soc[0] == pytest.approx(.1)
    assert battery.energy_init == pytest.approx(6.)
    battery.charge(0.)
    assert battery.soc[0] == pytest.approx(.1)
    assert battery.energy_balance[0] == pytest.approx(0.)


@pytest.mark.parametrize('command,stored_delta,terminal_energy', [
    (0., 0., 0.), (-10., 0., 0.), (1., .8, 1.),
])
def test_arrival_below_reserve_preserves_energy(command, stored_delta, terminal_energy):
    battery = _battery()
    battery.force_set_soc(.1)
    battery.charge(command)
    assert battery.soc[0]*60. == pytest.approx(6.+stored_delta, abs=1e-5)
    assert battery.energy_balance[0] == pytest.approx(terminal_energy, abs=1e-5)
    assert battery.electricity_consumption[0] == pytest.approx(terminal_energy, abs=1e-5)
    battery.next_time_step()
    assert battery.soc[1]*60. == pytest.approx(6.+stored_delta, abs=1e-5)


@pytest.mark.parametrize('initial_soc', [.1, .2])
def test_standby_losses_can_cross_operational_reserve(initial_soc):
    battery = _battery(loss=.01, seconds=3600)
    battery.force_set_soc(initial_soc)
    battery.next_time_step()
    expected_soc = initial_soc*.99
    assert battery.soc[1] == pytest.approx(expected_soc)
    battery.charge(-10.)
    assert battery.soc[1] == pytest.approx(expected_soc)
    assert battery.energy_balance[1] == pytest.approx(0.)


def test_conservation_sums_multiple_transfers_at_their_own_efficiencies():
    battery = _battery(seconds=3600)
    battery.power_efficiency_curve = [[0., .64], [1., 1.]]
    env = SimpleNamespace(buildings=[], electric_vehicles=[SimpleNamespace(name='EV', battery=battery)])
    checker = CityLearnPhysicsInvariantService(env)
    checker.capture_battery_energy_before_actions(0)
    expected = 0.
    for command in (1., 2., -1.):
        battery.charge(command)
        efficiency = (.64+.36*abs(command)/11.)**.5
        expected += command*efficiency if command > 0. else command/efficiency
    assert battery.stored_energy_transfer == pytest.approx(expected, abs=1e-5)
    assert battery.soc[0]*60. == pytest.approx(30.+expected, abs=1e-5)
    checker._assert_battery_energy_changes(0)
    battery.next_time_step()
    assert battery.stored_energy_transfer == 0.
    battery.charge(1.)
    assert battery.stored_energy_transfer > 0.
    battery.reset()
    assert battery.stored_energy_transfer == 0.


def _arrival_env(tmp_path, inventory, interface, seconds):
    source = Path(__file__).parent/'data/minute_ev_demo'
    dataset = tmp_path/'dataset'
    shutil.copytree(source, dataset)
    schema = json.loads((dataset/'schema.json').read_text())
    schema['root_directory'] = str(dataset)
    schema['seconds_per_time_step'] = seconds
    definition = schema['electric_vehicles_def']['Electric_Vehicle_1']['battery']
    attributes = definition['attributes']
    attributes.update(
        capacity=60., initial_soc=.5, nominal_power=11., depth_of_discharge=.8,
        efficiency=.64, loss_coefficient=0., capacity_loss_coefficient=0.,
        power_efficiency_curve=[[0., .64], [1., .64]],
        capacity_power_curve=[[0., 1.], [1., 1.]],
    )
    if inventory:
        definition['type'] = 'citylearn.community_dataset.InventoryBattery'
        attributes.update(max_charge_kw=11., max_discharge_kw=11.,
                          min_soc=.2, max_soc=.9, charging_efficiency=.8,
                          discharging_efficiency=.9)
    charger_attrs = schema['buildings']['Building_1']['chargers']['charger_1_1']['attributes']
    charger_attrs.update(efficiency=.95,
                         charge_efficiency_curve=[[0., .95], [1., .95]],
                         discharge_efficiency_curve=[[0., .95], [1., .95]])
    csv = dataset/'charger_1_1.csv'
    frame = pd.read_csv(csv)
    frame['electric_vehicle_charger_state'] = 1
    frame['electric_vehicle_id'] = 'Electric_Vehicle_1'
    frame['electric_vehicle_departure_time'] = np.arange(len(frame), 0, -1)
    frame['electric_vehicle_current_soc'] = -0.1
    frame.loc[0, 'electric_vehicle_current_soc'] = .1
    frame.to_csv(csv, index=False)
    env = CityLearnEnv(schema, central_agent=True, interface=interface,
                       physics_invariant_checks=True, random_seed=0)
    env.reset()
    return env


def _actions(env, charger_value):
    if env.interface == 'entity':
        tables = {name: np.zeros(space.shape, dtype='float32')
                  for name, space in env.action_space['tables'].items()
                  if name in {'building', 'charger', 'deferrable_appliance'}}
        tables['charger'][:] = charger_value
        return {'tables': tables}
    return [[charger_value if name.startswith('electric_vehicle_storage') else 0.
             for name in names] for names in env.action_names]


@pytest.mark.parametrize('inventory', [False, True], ids=['legacy', 'inventory'])
@pytest.mark.parametrize('interface', ['flat', 'entity'])
@pytest.mark.parametrize('seconds', [15, 900, 3600])
def test_loaded_arrival_below_reserve_needs_real_charge(tmp_path, inventory, interface, seconds):
    env = _arrival_env(tmp_path, inventory, interface, seconds)
    try:
        ev = env.electric_vehicles[0]
        charger = env.buildings[0].electric_vehicle_chargers[0]
        assert ev.battery.soc[0] == pytest.approx(.1)
        for value in (0., -1.):
            t = env.time_step
            env.step(_actions(env, value))
            assert ev.battery.soc[t] == pytest.approx(.1)
            assert ev.battery.soc[env.time_step] == pytest.approx(.1)
            assert charger.electricity_consumption[t] == pytest.approx(0.)
        t = env.time_step
        env.step(_actions(env, .5))
        grid_energy = 7.2*.5*seconds/3600.
        assert charger.electricity_consumption[t] == pytest.approx(grid_energy, abs=1e-5)
        assert ev.battery.soc[t]*60. == pytest.approx(6.+grid_energy*.95*.8, abs=1e-5)
    finally:
        env.close()


@pytest.mark.parametrize('fast_path', [False, True])
@pytest.mark.parametrize('asset', ['stationary', 'ev'])
def test_invariants_detect_stored_energy_created_without_charge(tmp_path, monkeypatch, fast_path, asset):
    env = _arrival_env(tmp_path, True, 'flat', 900)
    try:
        battery = (env.buildings[0].electrical_storage if asset == 'stationary'
                   else env.electric_vehicles[0].battery)
        original_charge = battery.charge

        def broken_charge(energy):
            original_charge(energy)
            battery.force_set_soc(float(battery.soc[battery.time_step])+.05)

        monkeypatch.setattr(battery, 'charge', broken_charge)
        step = env._runtime_service.step_without_feedback if fast_path else env.step
        with pytest.raises(AssertionError, match='Stored battery energy mismatch'):
            step(_actions(env, 0.))
    finally:
        env.close()
