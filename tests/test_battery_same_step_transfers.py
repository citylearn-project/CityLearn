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
