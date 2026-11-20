from typing import Optional

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.base import EpisodeTracker
from citylearn.data import ChargerSimulation
from citylearn.electric_vehicle import ElectricVehicle
from citylearn.electric_vehicle_charger import Charger
from citylearn.energy_model import Battery


def _make_tracker(length: int = 4) -> EpisodeTracker:
    tracker = EpisodeTracker(0, length - 1)
    tracker.next_episode(length, False, False, 0)
    return tracker


def _make_simulation(length: int, ev_id: str) -> ChargerSimulation:
    return ChargerSimulation(
        electric_vehicle_charger_state=[1] * length,
        electric_vehicle_id=[ev_id] * length,
        electric_vehicle_departure_time=[-1] * length,
        electric_vehicle_required_soc_departure=[-0.1] * length,
        electric_vehicle_estimated_arrival_time=[-1] * length,
        electric_vehicle_estimated_soc_arrival=[-0.1] * length,
    )


def _make_battery(
    tracker: EpisodeTracker,
    initial_soc: float = 0.5,
    seconds_per_time_step: int = 3600,
    time_step_ratio: float = 1.0,
) -> Battery:
    battery = Battery(
        capacity=100.0,
        nominal_power=50.0,
        initial_soc=initial_soc,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=0.0,
        power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratio=time_step_ratio,
        episode_tracker=tracker,
    )
    battery.reset()
    return battery


def _make_ev(
    tracker: EpisodeTracker,
    initial_soc: float = 0.5,
    seconds_per_time_step: int = 3600,
    time_step_ratio: float = 1.0,
) -> ElectricVehicle:
    battery = _make_battery(
        tracker,
        initial_soc=initial_soc,
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratio=time_step_ratio,
    )
    ev = ElectricVehicle(
        episode_tracker=tracker,
        battery=battery,
        name="EV-1",
        seconds_per_time_step=seconds_per_time_step,
    )
    ev.reset()
    return ev


def _make_charger(
    tracker: EpisodeTracker,
    sim: ChargerSimulation,
    ev: Optional[ElectricVehicle],
    **kwargs,
) -> Charger:
    charger = Charger(
        episode_tracker=tracker,
        charger_simulation=sim,
        charger_id="charger-1",
        max_charging_power=kwargs.get("max_charging_power", 10.0),
        min_charging_power=kwargs.get("min_charging_power", 0.0),
        max_discharging_power=kwargs.get("max_discharging_power", 10.0),
        min_discharging_power=kwargs.get("min_discharging_power", 0.0),
        efficiency=kwargs.get("efficiency", 1.0),
        connected_electric_vehicle=ev,
        seconds_per_time_step=kwargs.get("seconds_per_time_step", 3600),
    )
    charger.reset()
    charger.connected_electric_vehicle = ev
    return charger


@pytest.fixture
def tracker() -> EpisodeTracker:
    return _make_tracker(length=4)


@pytest.fixture
def electric_vehicle(tracker: EpisodeTracker) -> ElectricVehicle:
    return _make_ev(tracker, initial_soc=0.5)


@pytest.fixture
def charger_simulation(tracker: EpisodeTracker, electric_vehicle: ElectricVehicle) -> ChargerSimulation:
    return _make_simulation(tracker.episode_time_steps, electric_vehicle.name)


@pytest.fixture
def charger(
    tracker: EpisodeTracker,
    charger_simulation: ChargerSimulation,
    electric_vehicle: ElectricVehicle,
) -> Charger:
    electric_vehicle.electric_vehicle_simulation = charger_simulation
    return _make_charger(tracker, charger_simulation, electric_vehicle, efficiency=0.9)


def _expected_soc_after_charge(ev: ElectricVehicle, energy_to_battery: float) -> float:
    capacity = ev.battery.capacity
    energy_init = ev.battery.initial_soc * capacity
    return (energy_init + energy_to_battery * ev.battery.one_way_efficiency) / capacity


def test_charger_charging_updates_ev_soc_and_grid_accounting(charger: Charger, electric_vehicle: ElectricVehicle):
    charger.charge_efficiency_curve = [
        [0.0, 0.85],
        [0.5, 0.9],
        [1.0, 0.95],
    ]
    action = 0.4
    efficiency = charger.get_efficiency(abs(action), charging=True)

    initial_soc = float(electric_vehicle.battery.soc[electric_vehicle.time_step])
    commanded_energy = action * charger.max_charging_power * charger.algorithm_action_based_time_step_hours_ratio

    charger.update_connected_electric_vehicle_soc(action)

    stored_energy = commanded_energy * efficiency
    expected_soc = _expected_soc_after_charge(electric_vehicle, stored_energy)

    assert electric_vehicle.battery.soc[electric_vehicle.time_step] == pytest.approx(expected_soc)
    assert electric_vehicle.battery.soc[electric_vehicle.time_step] > initial_soc
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(commanded_energy)
    assert charger.electricity_consumption[charger.time_step] == pytest.approx(commanded_energy)
    assert electric_vehicle.observations()["electric_vehicle_soc"] == pytest.approx(
        electric_vehicle.battery.soc[electric_vehicle.time_step]
    )


def test_charger_discharging_updates_ev_soc_and_tracking(charger: Charger, electric_vehicle: ElectricVehicle):
    electric_vehicle.battery.force_set_soc(0.7)
    charger.discharge_efficiency_curve = [
        [0.0, 0.88],
        [0.5, 0.86],
        [1.0, 0.8],
    ]

    action = -0.3
    efficiency = charger.get_efficiency(abs(action), charging=False)
    commanded_energy = action * charger.max_discharging_power * charger.algorithm_action_based_time_step_hours_ratio

    charger.update_connected_electric_vehicle_soc(action)

    energy_to_battery = commanded_energy / efficiency
    expected_soc = (0.7 * electric_vehicle.battery.capacity + energy_to_battery) / electric_vehicle.battery.capacity

    assert electric_vehicle.battery.soc[electric_vehicle.time_step] == pytest.approx(expected_soc)
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(commanded_energy)
    assert charger.electricity_consumption[charger.time_step] == pytest.approx(commanded_energy)
    assert electric_vehicle.observations()["electric_vehicle_soc"] == pytest.approx(
        electric_vehicle.battery.soc[electric_vehicle.time_step]
    )


def test_update_soc_respects_minimum_power_deadband(tracker: EpisodeTracker, charger_simulation: ChargerSimulation):
    ev = _make_ev(tracker)
    charger = _make_charger(
        tracker,
        charger_simulation,
        ev,
        max_charging_power=10.0,
        min_charging_power=1.0,
        max_discharging_power=10.0,
        min_discharging_power=1.0,
    )

    assert charger.get_requested_power_kw(0.05) == pytest.approx(0.0)
    charger.update_connected_electric_vehicle_soc(0.05)
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(0.0)

    assert charger.get_requested_power_kw(0.1) == pytest.approx(1.0)
    charger.update_connected_electric_vehicle_soc(0.1)
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(1.0)

    ev.battery.force_set_soc(0.6)
    assert charger.get_requested_power_kw(-0.03) == pytest.approx(0.0)
    charger.update_connected_electric_vehicle_soc(-0.03)
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(0.0)

    assert charger.get_requested_power_kw(-0.1) == pytest.approx(-1.0)
    charger.update_connected_electric_vehicle_soc(-0.1)
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(-1.0)


def test_no_ev_connected_records_zero_consumption(tracker: EpisodeTracker, charger_simulation: ChargerSimulation):
    charger = _make_charger(tracker, charger_simulation, ev=None)
    charger.update_connected_electric_vehicle_soc(0.7)

    assert np.allclose(charger.electricity_consumption, 0.0)
    expected_energy = 0.7 * charger.max_charging_power * charger.algorithm_action_based_time_step_hours_ratio
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(expected_energy)


def test_zero_action_keeps_connected_ev_soc_consistent(tracker: EpisodeTracker, charger_simulation: ChargerSimulation):
    ev = _make_ev(tracker, initial_soc=0.6)
    charger = _make_charger(tracker, charger_simulation, ev=ev)

    charger.time_step = 1
    ev.time_step = 1
    ev.battery.time_step = 1
    ev.battery.soc[0] = 0.6

    charger.update_connected_electric_vehicle_soc(0.0)

    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(0.0)
    assert charger.electricity_consumption[charger.time_step] == pytest.approx(0.0)
    assert ev.battery.soc[1] == pytest.approx(0.6)


def test_past_charging_actions_track_history(charger: Charger, electric_vehicle: ElectricVehicle):
    actions = [0.25, -0.4, 0.0]
    expected = [2.5, -4.0, 0.0]

    for idx, action in enumerate(actions):
        charger.time_step = idx
        electric_vehicle.time_step = idx
        electric_vehicle.battery.time_step = idx
        charger.update_connected_electric_vehicle_soc(action)

    history = charger.past_charging_action_values_kwh[: len(actions)]
    np.testing.assert_allclose(history, expected, atol=1e-6)

    assert charger.electricity_consumption[0] > 0
    assert charger.electricity_consumption[1] < 0

def test_render_simulation_end_data_includes_consumption(charger: Charger, electric_vehicle: ElectricVehicle):
    charger.update_connected_electric_vehicle_soc(0.5)
    summary = charger.render_simulation_end_data()

    assert summary["name"] == "charger-1"
    assert summary["charger_data"][0]["electricity_consumption"] != 0
    assert summary["charger_data"][0]["time_step"] == 0


@pytest.mark.parametrize("seconds_per_time_step", [5, 10, 60, 300, 900])
def test_subhour_energy_exchange_matches_power_times_delta_t(
    tracker: EpisodeTracker,
    charger_simulation: ChargerSimulation,
    seconds_per_time_step: int,
):
    ratio = seconds_per_time_step / 3600.0
    ev = _make_ev(
        tracker,
        initial_soc=0.5,
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratio=ratio,
    )
    charger = _make_charger(
        tracker,
        charger_simulation,
        ev,
        max_charging_power=10.0,
        efficiency=1.0,
        seconds_per_time_step=seconds_per_time_step,
    )

    charger.update_connected_electric_vehicle_soc(1.0)
    expected_energy = 10.0 * (seconds_per_time_step / 3600.0)

    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(expected_energy)
    assert charger.electricity_consumption[charger.time_step] == pytest.approx(expected_energy)
    assert ev.battery.energy_balance[ev.time_step] == pytest.approx(expected_energy)


def test_subhour_minimum_power_deadband_is_scaled_by_timestep(
    tracker: EpisodeTracker,
    charger_simulation: ChargerSimulation,
):
    seconds_per_time_step = 5
    ratio = seconds_per_time_step / 3600.0
    ev = _make_ev(
        tracker,
        initial_soc=0.5,
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratio=ratio,
    )
    charger = _make_charger(
        tracker,
        charger_simulation,
        ev,
        max_charging_power=10.0,
        min_charging_power=2.0,
        efficiency=1.0,
        seconds_per_time_step=seconds_per_time_step,
    )

    charger.update_connected_electric_vehicle_soc(0.19)
    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(0.0)
    assert charger.electricity_consumption[charger.time_step] == pytest.approx(0.0)

    charger.update_connected_electric_vehicle_soc(0.2)
    expected_energy = 2.0 * (seconds_per_time_step / 3600.0)

    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(expected_energy)
    assert charger.electricity_consumption[charger.time_step] == pytest.approx(expected_energy)


def test_v2g_disabled_when_max_discharging_power_is_zero(
    tracker: EpisodeTracker,
    charger_simulation: ChargerSimulation,
):
    ev = _make_ev(tracker, initial_soc=0.8)
    charger = _make_charger(
        tracker,
        charger_simulation,
        ev,
        max_discharging_power=0.0,
        min_discharging_power=0.0,
        efficiency=1.0,
    )

    initial_soc = float(ev.battery.soc[ev.time_step])
    charger.update_connected_electric_vehicle_soc(-1.0)

    assert charger.past_charging_action_values_kwh[charger.time_step] == pytest.approx(0.0)
    assert charger.electricity_consumption[charger.time_step] == pytest.approx(0.0)
    assert float(ev.battery.soc[ev.time_step]) == pytest.approx(initial_soc)
