from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.community_dataset import InventoryBattery
from citylearn.energy_model import Battery, StorageTank


MINUTE_EV_SCHEMA = Path(__file__).resolve().parent / "data" / "minute_ev_demo" / "schema.json"


def _make_battery(
    *,
    capacity: float = 100.0,
    nominal_power: float = 40.0,
    initial_soc: float = 0.5,
    efficiency: float = 0.81,
    capacity_loss_coefficient: float = 1.0e-3,
    loss_coefficient: float = 0.0,
    depth_of_discharge: float = 1.0,
    seconds_per_time_step: int = 3600,
    time_step_ratio: float = 1.0,
    episode_time_steps: int = 4,
    legacy_discharge_power_limit: bool = False,
) -> Battery:
    tracker = EpisodeTracker(0, episode_time_steps - 1)
    tracker.next_episode(episode_time_steps, rolling_episode_split=False, random_episode_split=False, random_seed=0)
    battery = Battery(
        capacity=capacity,
        nominal_power=nominal_power,
        initial_soc=initial_soc,
        efficiency=efficiency,
        loss_coefficient=loss_coefficient,
        capacity_loss_coefficient=capacity_loss_coefficient,
        depth_of_discharge=depth_of_discharge,
        power_efficiency_curve=[[0.0, efficiency], [1.0, efficiency]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 0.8]],
        discharge_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratio=time_step_ratio,
        episode_tracker=tracker,
        random_seed=0,
    )
    battery.legacy_discharge_power_limit = legacy_discharge_power_limit
    battery.reset()
    return battery


@pytest.mark.parametrize("legacy_discharge_power_limit", [False, True])
@pytest.mark.parametrize(
    ("first_kwh", "second_kwh"),
    [
        (6.0, 4.0),
        (-6.0, -4.0),
    ],
)
def test_two_same_direction_transfers_in_one_step(
    legacy_discharge_power_limit: bool,
    first_kwh: float,
    second_kwh: float,
):
    battery = _make_battery(legacy_discharge_power_limit=legacy_discharge_power_limit)
    one_way = battery.efficiency**0.5
    c0 = float(battery.capacity)
    e0 = float(battery.soc[0]) * c0

    battery.charge(first_kwh)
    c1_expected = c0 - battery.capacity_loss_coefficient * c0 * abs(first_kwh) / (2.0 * c0)
    assert len(battery.capacity_history) == 2
    assert battery.degraded_capacity == pytest.approx(c1_expected, rel=1e-12)

    battery.charge(second_kwh)

    net_terminal = first_kwh + second_kwh
    expected_stored = e0 + (net_terminal * one_way if net_terminal >= 0.0 else net_terminal / one_way)
    c2_expected = c1_expected - battery.capacity_loss_coefficient * c0 * abs(second_kwh) / (2.0 * c1_expected)

    assert battery.energy_balance[0] == pytest.approx(net_terminal, rel=1e-6)
    assert battery.electricity_consumption[0] == pytest.approx(net_terminal, rel=1e-6)
    assert battery.soc[0] * c0 == pytest.approx(expected_stored, rel=1e-6)
    assert len(battery.capacity_history) == 2
    assert battery.capacity_before_step[0] == pytest.approx(c0, rel=1e-12)
    assert battery.degraded_capacity == pytest.approx(c2_expected, rel=1e-12)
    assert len(battery.efficiency_history) == 3

    if net_terminal >= 0.0:
        assert battery.gross_energy_charge[0] == pytest.approx(net_terminal, rel=1e-6)
        assert battery.gross_energy_discharge[0] == pytest.approx(0.0, abs=1e-9)
    else:
        assert battery.gross_energy_charge[0] == pytest.approx(0.0, abs=1e-9)
        assert battery.gross_energy_discharge[0] == pytest.approx(-net_terminal, rel=1e-6)


@pytest.mark.parametrize("legacy_discharge_power_limit", [False, True])
@pytest.mark.parametrize(
    ("first_kwh", "second_kwh"),
    [
        (8.0, -3.0),
        (-8.0, 3.0),
        (5.0, -5.0),
    ],
)
def test_two_opposite_direction_transfers_in_one_step(
    legacy_discharge_power_limit: bool,
    first_kwh: float,
    second_kwh: float,
):
    battery = _make_battery(legacy_discharge_power_limit=legacy_discharge_power_limit)
    one_way = battery.efficiency**0.5
    c0 = float(battery.capacity)
    e0 = float(battery.soc[0]) * c0

    battery.charge(first_kwh)
    battery.charge(second_kwh)

    delta_1 = first_kwh * one_way if first_kwh >= 0.0 else first_kwh / one_way
    delta_2 = second_kwh * one_way if second_kwh >= 0.0 else second_kwh / one_way
    expected_stored = e0 + delta_1 + delta_2
    net_terminal = first_kwh + second_kwh

    c1_expected = c0 - battery.capacity_loss_coefficient * c0 * abs(first_kwh) / (2.0 * c0)
    c2_expected = c1_expected - battery.capacity_loss_coefficient * c0 * abs(second_kwh) / (2.0 * c1_expected)

    assert battery.energy_balance[0] == pytest.approx(net_terminal, abs=1e-6)
    assert battery.electricity_consumption[0] == pytest.approx(net_terminal, abs=1e-6)
    assert battery.soc[0] * c0 == pytest.approx(expected_stored, rel=1e-6)
    assert len(battery.capacity_history) == 2
    assert battery.capacity_before_step[0] == pytest.approx(c0, rel=1e-12)
    assert battery.degraded_capacity == pytest.approx(c2_expected, rel=1e-12)
    # Even when first_kwh + second_kwh == 0, both physical transfers degrade the battery.
    assert c0 - battery.degraded_capacity > 0.0
    assert battery.gross_energy_charge[0] == pytest.approx(
        max(first_kwh, 0.0) + max(second_kwh, 0.0), rel=1e-6
    )
    assert battery.gross_energy_discharge[0] == pytest.approx(
        max(-first_kwh, 0.0) + max(-second_kwh, 0.0), rel=1e-6
    )

    # Advancing to step 1 and resetting keeps capacity_history aligned one entry per step.
    battery.next_time_step()
    assert battery.capacity_before_step[1] == pytest.approx(c2_expected, rel=1e-12)
    battery.charge(2.0)
    assert len(battery.capacity_history) == 3

    battery.reset()
    assert len(battery.capacity_history) == 1
    battery.charge(4.0)
    assert len(battery.capacity_history) == 2
    assert battery.energy_balance[0] == pytest.approx(4.0, rel=1e-6)
    assert battery.electricity_consumption[0] == pytest.approx(4.0, rel=1e-6)


def test_subhourly_time_step_ratio_and_storage_tank_and_inventory_battery():
    battery = _make_battery(seconds_per_time_step=900, time_step_ratio=0.25)
    # Dataset-resolution inputs of +8.0 and -2.0 scale by 0.25 to +2.0 and -0.5 control-step kWh.
    battery.charge(8.0)
    battery.charge(-2.0)
    assert battery.energy_balance[0] == pytest.approx(1.5, rel=1e-6)
    assert battery.electricity_consumption[0] == pytest.approx(1.5, rel=1e-6)
    assert len(battery.capacity_history) == 2

    tracker = EpisodeTracker(0, 3)
    tracker.next_episode(4, rolling_episode_split=False, random_episode_split=False, random_seed=0)
    inv = InventoryBattery(
        capacity=50.0,
        max_charge_kw=20.0,
        max_discharge_kw=20.0,
        min_soc=0.1,
        max_soc=0.9,
        initial_soc=0.5,
        charging_efficiency=0.95,
        discharging_efficiency=0.90,
        capacity_loss_coefficient=1.0e-3,
        seconds_per_time_step=3600,
        episode_tracker=tracker,
        random_seed=0,
    )
    inv.reset()
    inv.charge(6.0)
    inv.charge(-2.0)
    assert inv.energy_balance[0] == pytest.approx(4.0, rel=1e-6)
    assert inv.electricity_consumption[0] == pytest.approx(4.0, rel=1e-6)
    assert len(inv.capacity_history) == 2

    tank = StorageTank(
        capacity=20.0,
        initial_soc=0.5,
        efficiency=0.81,
        loss_coefficient=0.0,
        seconds_per_time_step=3600,
        episode_tracker=tracker,
        random_seed=0,
    )
    tank.reset()
    tank.charge(3.0)
    tank.charge(-1.0)
    assert tank.energy_balance[0] == pytest.approx(2.0, rel=1e-6)


@pytest.mark.parametrize("physics_version", [1, 2])
def test_environment_physics_invariants_and_single_transfer_parity_v1_and_v2(physics_version: int):
    # 1. Calling Battery.charge() twice inside a simulated step satisfies physics_invariant_checks under both v1 and v2.
    env = CityLearnEnv(
        str(MINUTE_EV_SCHEMA),
        central_agent=True,
        episode_time_steps=4,
        physics_version=physics_version,
        physics_invariant_checks=True,
        random_seed=0,
    )
    env.reset()
    building = env.buildings[0]
    storage = building.electrical_storage
    original_charge = storage.charge

    def split_charge(energy: float):
        # Split the step's requested transfer into an overshoot + opposite-direction correction with the same net request,
        # and also exercise a same-direction split on step 1.
        if building.time_step == 0:
            original_charge(0.6)
            original_charge(-0.2)
        else:
            original_charge(0.25)
            original_charge(0.15)

    storage.charge = split_charge
    zeros = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
    env.step(zeros)
    assert storage.energy_balance[0] == pytest.approx(0.4 * (storage.time_step_ratio or 1.0), rel=1e-5)
    assert storage.electricity_consumption[0] == pytest.approx(storage.energy_balance[0], rel=1e-5)
    assert len(storage.capacity_history) == 2

    env.step(zeros)
    assert storage.energy_balance[1] == pytest.approx(0.4 * (storage.time_step_ratio or 1.0), rel=1e-5)
    assert storage.electricity_consumption[1] == pytest.approx(storage.energy_balance[1], rel=1e-5)
    assert len(storage.capacity_history) == 3
    env.close()

    # 2. Normal single-transfer-per-step dispatch produces bit-identical single-call accounting to the direct formula.
    b_single = _make_battery(legacy_discharge_power_limit=(physics_version == 1))
    b_single.charge(4.5)
    one_way = b_single.efficiency**0.5
    raw_delta = (50.0 + 4.5 * one_way) - 50.0
    expected_f32_balance = float(np.float32(raw_delta / one_way))
    assert float(b_single.energy_balance[0]) == expected_f32_balance
    assert float(b_single.electricity_consumption[0]) == expected_f32_balance
    expected_cap = 100.0 - b_single.capacity_loss_coefficient * 100.0 * abs(expected_f32_balance) / 200.0
    assert b_single.degraded_capacity == expected_cap


@pytest.mark.parametrize("legacy_discharge_power_limit", [False, True])
def test_repeated_transfers_share_one_power_budget_per_step(legacy_discharge_power_limit: bool):
    # Issue #363: each call used to receive the full nominal_power x step budget, so three 5 kWh charges
    # moved 13.38 kWh through a 5 kW battery in one hour.
    battery = _make_battery(nominal_power=5.0, capacity_loss_coefficient=0.0,
                            legacy_discharge_power_limit=legacy_discharge_power_limit)
    input_budget = battery.get_max_input_power()
    assert input_budget == pytest.approx(4.5)

    for _ in range(3):
        battery.charge(5.0)

    assert battery.energy_balance[0] == pytest.approx(input_budget, rel=1e-6)
    assert battery.electricity_consumption[0] == pytest.approx(input_budget, rel=1e-6)
    assert battery.gross_energy_charge[0] == pytest.approx(input_budget, rel=1e-6)
    assert battery.preview_charge(1.0) == pytest.approx(0.0, abs=1e-6)

    # The charges used the whole step, so nothing is left to discharge in it either.
    for _ in range(3):
        battery.charge(-5.0)

    assert battery.gross_energy_discharge[0] == pytest.approx(0.0, abs=1e-6)
    assert battery.energy_balance[0] == pytest.approx(input_budget, rel=1e-6)
    assert battery.preview_charge(-1.0) == pytest.approx(0.0, abs=1e-6)

    # The next step starts with a full budget.
    battery.next_time_step()
    battery.charge(5.0)
    assert battery.energy_balance[1] == pytest.approx(battery.get_max_input_power(energy_init=battery.soc[0] * 100.0),
                                                      rel=1e-6)


def test_split_transfer_moves_the_same_energy_as_one_transfer():
    single = _make_battery(nominal_power=5.0, capacity_loss_coefficient=0.0)
    single.charge(10.0)

    split = _make_battery(nominal_power=5.0, capacity_loss_coefficient=0.0)
    split.charge(2.0)
    assert split.preview_charge(10.0) == pytest.approx(float(single.energy_balance[0]) - 2.0, rel=1e-6)
    split.charge(10.0)

    assert split.energy_balance[0] == pytest.approx(single.energy_balance[0], rel=1e-6)
    assert split.soc[0] == pytest.approx(single.soc[0], rel=1e-6)


def test_subhourly_repeated_transfers_share_the_control_step_budget():
    # 15-minute steps: the budget is 4.5 kW x 0.25 h = 1.125 kWh per control step, while each 4.0 kWh
    # dataset-resolution request is 1.0 kWh of control-step energy at time_step_ratio 0.25.
    battery = _make_battery(nominal_power=5.0, capacity_loss_coefficient=0.0, seconds_per_time_step=900,
                            time_step_ratio=0.25)
    for _ in range(3):
        battery.charge(4.0)

    assert battery.energy_balance[0] == pytest.approx(1.125, rel=1e-6)
    assert battery.electricity_consumption[0] == pytest.approx(1.125, rel=1e-6)


def _make_tank(*, seconds_per_time_step: int = 3600, time_step_ratio: float = 1.0) -> StorageTank:
    tracker = EpisodeTracker(0, 3)
    tracker.next_episode(4, rolling_episode_split=False, random_episode_split=False, random_seed=0)
    tank = StorageTank(
        capacity=100.0, max_input_power=5.0, max_output_power=4.0, initial_soc=0.5, efficiency=0.9,
        loss_coefficient=0.0, seconds_per_time_step=seconds_per_time_step, time_step_ratio=time_step_ratio,
        episode_tracker=tracker, random_seed=0,
    )
    tank.reset()
    return tank


def test_storage_tank_repeated_transfers_share_one_power_budget_per_step():
    # Same per-call limit as #363, in StorageTank: three 5 kWh charges used to put 15 kWh through a 5 kW tank.
    tank = _make_tank()
    for _ in range(3):
        tank.charge(5.0)
    assert tank.energy_balance[0] == pytest.approx(5.0, rel=1e-6)

    # The charges used the whole step, so nothing is left to discharge in it either.
    for _ in range(3):
        tank.charge(-5.0)
    assert tank.energy_balance[0] == pytest.approx(5.0, rel=1e-6)

    # A split transfer moves the same energy as one transfer, and the next step starts with a full budget.
    tank.next_time_step()
    tank.charge(2.0)
    tank.charge(10.0)
    assert tank.energy_balance[1] == pytest.approx(5.0, rel=1e-6)

    tank.reset()
    tank.charge(5.0)
    assert tank.energy_balance[0] == pytest.approx(5.0, rel=1e-6)


def test_storage_tank_subhourly_repeated_transfers_share_the_control_step_budget():
    # 15-minute steps: 5 kW x 0.25 h = 1.25 kWh per control step; each 4.0 kWh dataset-resolution request is
    # 1.0 kWh of control-step energy at time_step_ratio 0.25.
    tank = _make_tank(seconds_per_time_step=900, time_step_ratio=0.25)
    for _ in range(3):
        tank.charge(4.0)
    assert tank.energy_balance[0] == pytest.approx(1.25, rel=1e-6)


@pytest.mark.parametrize("legacy_discharge_power_limit", [False, True])
@pytest.mark.parametrize(("first_share", "first_sign"), [(1.0, 1.0), (0.5, 1.0), (1.0, -1.0), (0.25, -1.0)])
def test_opposite_transfers_in_one_step_share_the_step(legacy_discharge_power_limit, first_share, first_sign):
    # A charge and a discharge in the same step each used to get a full budget: +5 then -5 kWh moved 9.5 kWh
    # through a 5 kW battery in one hour. A transfer takes its share of the step, |E|/(P*dt), and the shares
    # of the step's transfers add up to at most one.
    battery = _make_battery(nominal_power=5.0, capacity_loss_coefficient=0.0,
                            legacy_discharge_power_limit=legacy_discharge_power_limit)
    input_budget, output_budget = battery.get_max_input_power(), battery.get_max_output_power()
    first_budget, second_budget = (input_budget, output_budget) if first_sign > 0 else (output_budget, input_budget)

    battery.charge(first_sign*first_share*first_budget)
    assert battery.preview_charge(-first_sign*10.0) == pytest.approx(-first_sign*(1.0 - first_share)*second_budget,
                                                                     abs=1e-6)
    for _ in range(2):
        battery.charge(-first_sign*10.0)
        battery.charge(first_sign*10.0)

    used = battery.gross_energy_charge[0]/input_budget + battery.gross_energy_discharge[0]/output_budget
    assert used == pytest.approx(1.0, abs=1e-6)
    second_moved = battery.gross_energy_discharge[0] if first_sign > 0 else battery.gross_energy_charge[0]
    assert second_moved == pytest.approx((1.0 - first_share)*second_budget, abs=1e-6)

    # The next step has the whole step again.
    battery.next_time_step()
    battery.charge(-10.0)
    assert battery.gross_energy_discharge[1] == pytest.approx(
        battery.get_max_output_power(energy_init=battery.soc[0]*100.0), rel=1e-6
    )


def test_storage_tank_opposite_transfers_in_one_step_share_the_step():
    tank = _make_tank()  # 5 kW in, 4 kW out
    tank.charge(2.5)
    tank.charge(-10.0)
    tank.charge(10.0)
    assert tank.energy_balance[0] == pytest.approx(2.5 - 2.0, rel=1e-6)

    subhourly = _make_tank(seconds_per_time_step=900, time_step_ratio=0.25)
    subhourly.charge(-2.0)  # 0.5 kWh of control-step energy, half of 4 kW x 0.25 h
    subhourly.charge(10.0)
    assert subhourly.energy_balance[0] == pytest.approx(-0.5 + 0.625, rel=1e-6)


def test_inventory_battery_shares_the_step_by_power_not_by_soc_headroom():
    tracker = EpisodeTracker(0, 3)
    tracker.next_episode(4, rolling_episode_split=False, random_episode_split=False, random_seed=0)
    battery = InventoryBattery(
        capacity=50.0, max_charge_kw=20.0, max_discharge_kw=20.0, min_soc=0.1, max_soc=0.9, initial_soc=0.88,
        charging_efficiency=1.0, discharging_efficiency=1.0, capacity_loss_coefficient=0.0,
        seconds_per_time_step=3600, episode_tracker=tracker, random_seed=0,
    )
    battery.reset()
    battery.charge(10.0)  # 1 kWh of SOC headroom: 1/20 of the step at 20 kW
    assert battery.gross_energy_charge[0] == pytest.approx(1.0, rel=1e-6)
    battery.charge(-30.0)
    assert battery.gross_energy_discharge[0] == pytest.approx(19.0, rel=1e-6)
