"""Physics invariant identities that do not reuse the net-balance components (#277).

The net balance rebuilds a building's net consumption from the device series that produced it, so an
accounting error inside a device model passes it. Each test below injects such an error into one device
model during a step, checks that the net balance still holds, and checks that the device identity raises
``PhysicsInvariantError``.
"""

from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.physics_invariants import PhysicsInvariantError
from private_access import physics_invariant_service

ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_DEMO = ROOT/'tests'/'data'/'minute_ev_demo'/'schema.json'
CHALLENGE_2021 = ROOT/'data'/'datasets'/'citylearn_challenge_2021'/'schema.json'
# A summer window of the 2021 challenge, with cooling demand in every building.
SUMMER = dict(simulation_start_time_step=4800, simulation_end_time_step=4823)


def _env(schema, first_step=True, **kwargs):
    """A checked environment after one normal step.

    At the first step `update_variables()` recomputes the thermal and non-shiftable consumption from the
    device outputs, which would overwrite an injected error, so the tests inject at the second step.
    """

    kwargs.setdefault('central_agent', True)
    env = CityLearnEnv(str(schema), random_seed=0, offline=True, physics_invariant_checks=True, **kwargs)
    env.reset(seed=0)
    if first_step:
        env.step(_zero(env) if kwargs['central_agent'] else [[0.0]*len(names) for names in env.action_names])
    return env


def _zero(env):
    return [np.zeros(space.shape, dtype='float32') for space in env.action_space]


def _step_with_unchecked_net_balance(env, action):
    """Step, and check that the net balance alone accepts the step the device identity rejects."""

    service = physics_invariant_service(env)
    net_balance = service._assert_building_energy_balance
    with pytest.raises(PhysicsInvariantError) as error:
        env.step(action)
    t = int(env.buildings[0].time_step)
    for building in env.buildings:
        net_balance(building, t)
    return str(error.value)


@pytest.mark.parametrize('physics_version', [1, 2])
@pytest.mark.parametrize('schema,window', [(MINUTE_EV_DEMO, dict(episode_time_steps=8)), (CHALLENGE_2021, SUMMER)])
def test_identities_hold_in_normal_rollouts(schema, window, physics_version):
    env = _env(schema, first_step=False, physics_version=physics_version, **window)
    try:
        spaces = env.action_space
        for space in spaces:
            space.seed(0)
        while not env.terminated:
            env.step([space.sample() for space in spaces])
    finally:
        env.close()


def test_injected_non_shiftable_consumption_is_caught():
    # The repro of #277: 100 kWh added to the non-shiftable device's consumption, whose dataset load is
    # 1.0 kWh. Net consumption follows the device, so the net balance holds.
    env = _env(MINUTE_EV_DEMO, central_agent=False, episode_time_steps=4)
    building = env.buildings[0]
    update = building.update_non_shiftable_load

    def inflated():
        update()
        building.non_shiftable_load_device.update_electricity_consumption(100.0)

    building.update_non_shiftable_load = inflated
    try:
        message = _step_with_unchecked_net_balance(env, [[0.0]*len(env.action_names[0])])
        assert 'Served non-shiftable load exceeds demand' in message
        t = int(building.time_step)
        assert building.non_shiftable_load_device.electricity_consumption[t] > 100.0
        assert building.net_electricity_consumption[t] > 100.0
    finally:
        env.close()


def test_heat_pump_electricity_must_match_heat_output_over_cop():
    env = _env(CHALLENGE_2021, **SUMMER)
    building = env.buildings[0]
    update = building.update_energy_from_cooling_device

    def overdrawn():
        update()
        building.cooling_device.update_electricity_consumption(1.0)

    building.update_energy_from_cooling_device = overdrawn
    try:
        message = _step_with_unchecked_net_balance(env, _zero(env))
        assert 'Thermal device conversion mismatch' in message and '(cooling)' in message
    finally:
        env.close()


def test_electric_heater_electricity_must_match_heat_output_over_efficiency():
    env = _env(CHALLENGE_2021, **SUMMER)
    building = next(b for b in env.buildings if b.energy_simulation.dhw_demand[b.time_step] > 0.0)
    update = building.update_energy_from_dhw_device

    def underdrawn():
        update()
        t = int(building.time_step)
        consumption = float(building.dhw_device.electricity_consumption[t])
        assert consumption > 0.0
        building.dhw_device.set_electricity_consumption(0.5*consumption, time_step=t)

    building.update_energy_from_dhw_device = underdrawn
    try:
        message = _step_with_unchecked_net_balance(env, _zero(env))
        assert 'Thermal device conversion mismatch' in message and '(dhw)' in message
    finally:
        env.close()


def test_served_cooling_must_not_exceed_demand():
    # Heat output and electricity are inflated consistently, so the device conversion holds.
    env = _env(CHALLENGE_2021, **SUMMER)
    building = env.buildings[0]
    update = building.update_energy_from_cooling_device

    def oversupplied():
        update()
        t = int(building.time_step)
        temperature = building.weather.outdoor_dry_bulb_temperature[t]
        building._Building__energy_from_cooling_device[t] += 5.0
        building.cooling_device.update_electricity_consumption(5.0/building.cooling_device.get_cop(temperature, heating=False))

    building.update_energy_from_cooling_device = oversupplied
    try:
        message = _step_with_unchecked_net_balance(env, _zero(env))
        assert 'Served cooling energy exceeds demand' in message
    finally:
        env.close()


def test_battery_terminal_energy_must_match_its_stored_energy_change():
    # 1 kWh more at the battery terminals than the battery stored: the battery's own transfer journal
    # agrees with its SOC, and net consumption follows the terminal energy.
    env = _env(MINUTE_EV_DEMO, central_agent=False, episode_time_steps=4)
    building = env.buildings[0]
    update = building.update_electrical_storage

    def leaky(action):
        update(action)
        building.electrical_storage.update_electricity_consumption(1.0, enforce_polarity=False)

    building.update_electrical_storage = leaky
    try:
        message = _step_with_unchecked_net_balance(env, [[0.0]*len(env.action_names[0])])
        assert 'Battery terminal energy does not match its charge and discharge operations' in message
    finally:
        env.close()


def test_battery_discharge_must_stop_at_the_depth_of_discharge_reserve():
    env = _env(MINUTE_EV_DEMO, central_agent=False, episode_time_steps=4)
    building = env.buildings[0]
    battery = building.electrical_storage
    battery.depth_of_discharge = 0.5
    reserve_soc = 1.0 - battery.depth_of_discharge
    t = int(battery.time_step)
    battery._StorageDevice__soc[t] = reserve_soc + 0.02
    # A model that ignores the reserve: no discharge limit other than the stored energy.
    battery._minimum_soc = lambda: 0.0
    battery._limit_charge_energy = lambda energy, energy_init, degraded_capacity: (energy, battery.efficiency)
    names = env.action_names[0]
    action = [0.0]*len(names)
    action[names.index('electrical_storage')] = -0.2
    try:
        message = _step_with_unchecked_net_balance(env, [action])
        assert 'below its depth-of-discharge reserve' in message
        assert battery.soc[t] < reserve_soc
    finally:
        env.close()
