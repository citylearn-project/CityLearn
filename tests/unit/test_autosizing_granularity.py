"""Autosizing distinguishes dataset energy, step energy, power and capacity."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from citylearn.building import Building
from citylearn.energy_model import Battery, ElectricHeater, HeatPump, StorageDevice, StorageTank


INTERVALS = [
    pytest.param(3600, 1.0, id="hourly"),
    pytest.param(900, 1.0, id="native-quarter-hour"),
    pytest.param(900, 0.25, id="hourly-data-quarter-hour-control"),
    pytest.param(15, 1.0, id="native-fifteen-seconds"),
    pytest.param(7200, 1.0, id="two-hour"),
]


def _dataset_energy(power, seconds, ratio):
    return np.asarray(power) * (seconds / 3600.0) / ratio


def _sizing_data():
    return pd.DataFrame({
        "capacity": [5.0], "nominal_power": [5.0],
        "depth_of_discharge": [1.0], "efficiency": [1.0],
        "loss_coefficient": [0.0], "capacity_loss_coefficient": [0.0],
    })


@pytest.mark.parametrize("seconds,ratio", INTERVALS)
@pytest.mark.parametrize("container", [float, list, np.array])
def test_heater_autosize_serves_same_physical_load(seconds, ratio, container):
    heater = ElectricHeater(efficiency=0.8, seconds_per_time_step=seconds,
                           time_step_ratio=ratio)
    energy = float(_dataset_energy(10.0, seconds, ratio))
    demand = energy if container is float else container([energy/2, energy])
    heater.nominal_power = heater.autosize(demand, safety_factor=1.0)
    assert heater.nominal_power == pytest.approx(12.5)
    # The sized device can deliver the peak's thermal energy during the step.
    assert heater.nominal_power * heater.efficiency * seconds/3600.0 == pytest.approx(
        energy * ratio)


@pytest.mark.parametrize("seconds,ratio", INTERVALS)
@pytest.mark.parametrize("mode", ["heating", "cooling", "both"])
def test_heat_pump_autosize_uses_power_for_both_demands(seconds, ratio, mode):
    pump = HeatPump(efficiency=0.25, seconds_per_time_step=seconds, time_step_ratio=ratio)
    temperature = np.array([10.0, 20.0])
    demands = {}
    required_power = np.zeros(2)
    for end_use, power in [("cooling", [2.0, 10.0]), ("heating", [8.0, 4.0])]:
        if mode in (end_use, "both"):
            demands[end_use + "_demand"] = _dataset_energy(power, seconds, ratio).tolist()
            required_power += np.array(power) / pump.get_cop(temperature, end_use == "heating")
    assert pump.autosize(temperature, safety_factor=1.2, **demands) == pytest.approx(
        max(required_power) * 1.2)


@pytest.mark.parametrize("seconds,ratio", INTERVALS)
def test_battery_autosize_preserves_power_and_duration(seconds, ratio):
    battery = Battery(seconds_per_time_step=seconds, time_step_ratio=ratio, random_seed=0)
    result = battery.autosize(float(_dataset_energy(10.0, seconds, ratio)),
                             duration=2.0, parallel=True, safety_factor=1.0,
                             sizing_data=_sizing_data())
    assert result[:2] == pytest.approx((20.0, 20.0))
    assert battery.autosize_config["demand"] == pytest.approx(10.0)


@pytest.mark.parametrize("seconds,ratio", INTERVALS)
@pytest.mark.parametrize("storage_type", [StorageDevice, StorageTank])
def test_thermal_capacity_remains_energy_for_one_control_step(seconds, ratio, storage_type):
    storage = storage_type(seconds_per_time_step=seconds, time_step_ratio=ratio)
    demand = _dataset_energy([5.0, 10.0], seconds, ratio)
    assert storage.autosize(demand, safety_factor=1.5) == pytest.approx(
        10.0 * seconds/3600.0 * 1.5)


@pytest.mark.parametrize("seconds,ratio", INTERVALS)
def test_building_battery_uses_physical_days_for_average_peaks(seconds, ratio):
    hourly_power = np.ones(48)
    hourly_power[6] = 10.0
    hourly_power[24:] = 2.0
    hourly_power[42] = 6.0
    if seconds <= 3600:
        power = np.repeat(hourly_power, 3600 // seconds)
    else:
        power = hourly_power.reshape(-1, 2).max(axis=1)
    battery = Battery(seconds_per_time_step=seconds, time_step_ratio=ratio, random_seed=0)
    building = SimpleNamespace(
        seconds_per_time_step=seconds, electrical_storage=battery,
        _estimate_baseline_electricity_consumption=lambda: _dataset_energy(power, seconds, ratio),
    )
    Building.autosize_electrical_storage(
        building, duration=2.0, safety_factor=1.0, sizing_data=_sizing_data())
    assert battery.autosize_config["demand"] == pytest.approx(8.0)
