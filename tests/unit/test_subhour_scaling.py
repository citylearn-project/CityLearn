"""Tests verifying sub-hour simulation support."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.data import EnergySimulation
from citylearn.energy_model import Battery, ElectricDevice, StorageDevice, StorageTank


_MISSING = object()
ROOT = Path(__file__).resolve().parents[2]
EV_SCHEMA = str((ROOT / 'data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json').resolve(strict=True))
MINUTE_SCHEMA = str((ROOT / 'tests/data/minute_ev_demo/schema.json').resolve(strict=True))


def _make_tracker(length: int) -> EpisodeTracker:
    tracker = EpisodeTracker(0, length - 1)
    tracker.next_episode(length, rolling_episode_split=False, random_episode_split=False, random_seed=0)
    return tracker


def _write_15_second_ev_schema(
    tmp_path: Path,
    *,
    steps: int = 240,
    initial_soc: float = 0.5,
    target_soc: float = 0.8,
    capacity: float = 10.0,
    nominal_power: float = 50.0,
    charger_power: float = 7.2,
    loss_coefficient=_MISSING,
) -> Path:
    dataset_dir = tmp_path / "native_15s_ev"
    dataset_dir.mkdir()

    elapsed_seconds = np.arange(steps, dtype=int) * 15
    hours = ((elapsed_seconds // 3600) % 24).astype(int)
    minutes = ((elapsed_seconds % 3600) // 60).astype(int)
    seconds = (elapsed_seconds % 60).astype(int)

    building_data = pd.DataFrame({
        "month": np.ones(steps, dtype=int),
        "hour": hours,
        "minutes": minutes,
        "seconds": seconds,
        "day_type": np.ones(steps, dtype=int),
        "daylight_savings_status": np.zeros(steps, dtype=int),
        "indoor_dry_bulb_temperature": np.full(steps, 21.0),
        "average_unmet_cooling_setpoint_difference": np.zeros(steps),
        "indoor_relative_humidity": np.full(steps, 45.0),
        "non_shiftable_load": np.full(steps, 0.1),
        "dhw_demand": np.zeros(steps),
        "cooling_demand": np.zeros(steps),
        "heating_demand": np.zeros(steps),
        "solar_generation": np.zeros(steps),
    })
    building_data.to_csv(dataset_dir / "Building_1.csv", index=False)

    weather_data = {
        "outdoor_dry_bulb_temperature": np.full(steps, 12.0),
        "outdoor_relative_humidity": np.full(steps, 60.0),
        "diffuse_solar_irradiance": np.zeros(steps),
        "direct_solar_irradiance": np.zeros(steps),
    }
    for horizon in [1, 2, 3]:
        weather_data[f"outdoor_dry_bulb_temperature_predicted_{horizon}"] = np.full(steps, 12.0)
        weather_data[f"outdoor_relative_humidity_predicted_{horizon}"] = np.full(steps, 60.0)
        weather_data[f"diffuse_solar_irradiance_predicted_{horizon}"] = np.zeros(steps)
        weather_data[f"direct_solar_irradiance_predicted_{horizon}"] = np.zeros(steps)
    pd.DataFrame(weather_data).to_csv(dataset_dir / "weather.csv", index=False)

    pd.DataFrame({"carbon_intensity": np.full(steps, 0.2)}).to_csv(dataset_dir / "carbon_intensity.csv", index=False)
    pd.DataFrame({
        "electricity_pricing": np.full(steps, 0.1),
        "electricity_pricing_predicted_1": np.full(steps, 0.1),
        "electricity_pricing_predicted_2": np.full(steps, 0.1),
        "electricity_pricing_predicted_3": np.full(steps, 0.1),
    }).to_csv(dataset_dir / "pricing.csv", index=False)

    charger_state = np.ones(steps, dtype=int)
    charger_state[-1] = 3
    required_soc = np.full(steps, target_soc * 100.0)
    required_soc[-1] = np.nan
    departure_time = np.array([max(steps - 1 - i, 1) for i in range(steps)], dtype=float)
    departure_time[-1] = -1.0

    pd.DataFrame({
        "electric_vehicle_charger_state": charger_state,
        "electric_vehicle_id": ["Electric_Vehicle_1"] * steps,
        "electric_vehicle_departure_time": departure_time,
        "electric_vehicle_required_soc_departure": required_soc,
        "electric_vehicle_estimated_arrival_time": np.full(steps, np.nan),
        "electric_vehicle_estimated_soc_arrival": np.full(steps, np.nan),
    }).to_csv(dataset_dir / "charger_1_1.csv", index=False)

    ev_attrs = {
        "capacity": capacity,
        "nominal_power": nominal_power,
        "initial_soc": initial_soc,
        "depth_of_discharge": 1.0,
    }
    if loss_coefficient is not _MISSING:
        ev_attrs["loss_coefficient"] = loss_coefficient

    schema = {
        "root_directory": None,
        "central_agent": True,
        "seconds_per_time_step": 15,
        "simulation_start_time_step": 0,
        "simulation_end_time_step": steps - 1,
        "episode_time_steps": steps,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "random_seed": 0,
        "start_date": "2024-01-01",
        "observations": {
            "month": {"active": True, "shared_in_central_agent": True},
            "hour": {"active": True, "shared_in_central_agent": True},
            "minutes": {"active": True, "shared_in_central_agent": True},
            "day_type": {"active": True, "shared_in_central_agent": True},
            "outdoor_dry_bulb_temperature": {"active": True, "shared_in_central_agent": True},
            "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
            "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
            "electricity_pricing": {"active": True, "shared_in_central_agent": True},
            "electric_vehicle_charger_connected_state": {"active": True, "shared_in_central_agent": False},
            "connected_electric_vehicle_at_charger_soc": {"active": True, "shared_in_central_agent": False},
        },
        "actions": {
            "electrical_storage": {"active": False},
            "electric_vehicle_storage": {"active": True},
        },
        "reward_function": {
            "type": "citylearn.reward_function.RewardFunction",
            "attributes": {},
        },
        "weather": "weather.csv",
        "carbon_intensity": "carbon_intensity.csv",
        "pricing": "pricing.csv",
        "electric_vehicles_def": {
            "Electric_Vehicle_1": {
                "include": True,
                "battery": {
                    "type": "citylearn.energy_model.Battery",
                    "autosize": False,
                    "attributes": ev_attrs,
                },
            },
        },
        "buildings": {
            "Building_1": {
                "include": True,
                "energy_simulation": "Building_1.csv",
                "weather": "weather.csv",
                "carbon_intensity": "carbon_intensity.csv",
                "pricing": "pricing.csv",
                "chargers": {
                    "charger_1_1": {
                        "type": "citylearn.electric_vehicle_charger.Charger",
                        "autosize": False,
                        "charger_simulation": "charger_1_1.csv",
                        "attributes": {
                            "nominal_power": charger_power,
                            "charger_type": 0,
                            "max_charging_power": charger_power,
                            "min_charging_power": 0.0,
                            "max_discharging_power": 0.0,
                            "min_discharging_power": 0.0,
                            "efficiency": 1.0,
                        },
                    },
                },
            },
        },
    }

    schema_path = dataset_dir / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    return schema_path


def test_energy_simulation_ratio_matches_dataset_cadence():
    seconds_per_time_step = 900  # 15 minutes
    num_steps = 4
    minutes = [0, 15, 30, 45]

    sim = EnergySimulation(
        month=[1] * num_steps,
        hour=[0] * num_steps,
        minutes=minutes,
        day_type=[1] * num_steps,
        indoor_dry_bulb_temperature=[20.0] * num_steps,
        non_shiftable_load=[1.0] * num_steps,
        dhw_demand=[0.0] * num_steps,
        cooling_demand=[0.0] * num_steps,
        heating_demand=[0.0] * num_steps,
        solar_generation=[0.0] * num_steps,
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratios=[],
    )

    assert sim.time_step_ratios[0] == pytest.approx(1.0)
    assert sim.dataset_seconds_per_time_step == pytest.approx(900.0)


def test_energy_simulation_ratio_matches_15_second_dataset_cadence():
    seconds_per_time_step = 15
    num_steps = 4
    seconds = [0, 15, 30, 45]

    sim = EnergySimulation(
        month=[1] * num_steps,
        hour=[0] * num_steps,
        minutes=[0] * num_steps,
        seconds=seconds,
        day_type=[1] * num_steps,
        indoor_dry_bulb_temperature=[20.0] * num_steps,
        non_shiftable_load=[1.0] * num_steps,
        dhw_demand=[0.0] * num_steps,
        cooling_demand=[0.0] * num_steps,
        heating_demand=[0.0] * num_steps,
        solar_generation=[0.0] * num_steps,
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratios=[],
    )

    assert sim.time_step_ratios[0] == pytest.approx(1.0)
    assert sim.dataset_seconds_per_time_step == pytest.approx(15.0)


def test_energy_simulation_subminute_without_seconds_assumes_schema_cadence():
    seconds_per_time_step = 15
    num_steps = 4

    sim = EnergySimulation(
        month=[1] * num_steps,
        hour=[0] * num_steps,
        minutes=[0] * num_steps,
        day_type=[1] * num_steps,
        indoor_dry_bulb_temperature=[20.0] * num_steps,
        non_shiftable_load=[1.0] * num_steps,
        dhw_demand=[0.0] * num_steps,
        cooling_demand=[0.0] * num_steps,
        heating_demand=[0.0] * num_steps,
        solar_generation=[0.0] * num_steps,
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratios=[],
    )

    assert sim.time_step_ratios[0] == pytest.approx(1.0)
    assert sim.dataset_seconds_per_time_step == pytest.approx(15.0)


def test_energy_simulation_ratio_subhour_control_from_hourly_dataset():
    seconds_per_time_step = 900  # 15 minutes control step
    num_steps = 4

    sim = EnergySimulation(
        month=[1] * num_steps,
        hour=[0, 1, 2, 3],
        day_type=[1] * num_steps,
        indoor_dry_bulb_temperature=[20.0] * num_steps,
        non_shiftable_load=[1.0] * num_steps,
        dhw_demand=[0.0] * num_steps,
        cooling_demand=[0.0] * num_steps,
        heating_demand=[0.0] * num_steps,
        solar_generation=[0.0] * num_steps,
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratios=[],
    )

    # Hourly dataset, 15-minute control -> ratio should be 0.25
    assert sim.time_step_ratios[0] == pytest.approx(0.25)
    assert sim.dataset_seconds_per_time_step == pytest.approx(3600.0)


def test_energy_simulation_time_step_ratio_default_not_shared_across_instances():
    num_steps = 4

    sim_hourly = EnergySimulation(
        month=[1] * num_steps,
        hour=[0, 1, 2, 3],
        day_type=[1] * num_steps,
        indoor_dry_bulb_temperature=[20.0] * num_steps,
        non_shiftable_load=[1.0] * num_steps,
        dhw_demand=[0.0] * num_steps,
        cooling_demand=[0.0] * num_steps,
        heating_demand=[0.0] * num_steps,
        solar_generation=[0.0] * num_steps,
        seconds_per_time_step=3600,
    )
    sim_subhour = EnergySimulation(
        month=[1] * num_steps,
        hour=[0, 1, 2, 3],
        day_type=[1] * num_steps,
        indoor_dry_bulb_temperature=[20.0] * num_steps,
        non_shiftable_load=[1.0] * num_steps,
        dhw_demand=[0.0] * num_steps,
        cooling_demand=[0.0] * num_steps,
        heating_demand=[0.0] * num_steps,
        solar_generation=[0.0] * num_steps,
        seconds_per_time_step=900,
    )

    assert len(sim_hourly.time_step_ratios) == 1
    assert len(sim_subhour.time_step_ratios) == 1
    assert sim_hourly.time_step_ratios[0] == pytest.approx(1.0)
    assert sim_subhour.time_step_ratios[0] == pytest.approx(0.25)


def test_storage_charge_scaling_respects_time_ratio():
    tracker = _make_tracker(4)
    storage = StorageDevice(
        capacity=10.0,
        efficiency=1.0,
        loss_coefficient=0.0,
        initial_soc=0.0,
        time_step_ratio=0.25,
        episode_tracker=tracker,
        seconds_per_time_step=900,
    )
    storage.reset()

    energy_actual = 2.5  # kWh to add over a 15-minute step at full power
    dataset_energy = energy_actual / storage.time_step_ratio
    storage.charge(dataset_energy)

    assert storage.energy_balance[0] == pytest.approx(energy_actual)


def test_storage_tank_uses_single_time_ratio_scaling_and_step_power_limits():
    tracker = _make_tracker(4)
    tank = StorageTank(
        capacity=10.0,
        efficiency=1.0,
        loss_coefficient=0.0,
        initial_soc=0.0,
        max_input_power=2.0,
        time_step_ratio=0.25,
        seconds_per_time_step=900,
        episode_tracker=tracker,
    )
    tank.reset()

    tank.charge(100.0)

    assert tank.energy_balance[0] == pytest.approx(0.5)


def test_electric_device_set_electricity_consumption_is_absolute():
    tracker = _make_tracker(4)
    device = ElectricDevice(
        nominal_power=10.0,
        time_step_ratio=0.25,
        seconds_per_time_step=900,
        episode_tracker=tracker,
    )
    device.reset()

    # Additive updates use dataset-resolution values when ratio != 1.
    device.update_electricity_consumption(4.0)
    assert device.electricity_consumption[0] == pytest.approx(1.0)

    # Absolute setter must overwrite, not accumulate.
    device.set_electricity_consumption(2.5)
    assert device.electricity_consumption[0] == pytest.approx(2.5)

    device.set_electricity_consumption(0.5)
    assert device.electricity_consumption[0] == pytest.approx(0.5)


def test_battery_electricity_consumption_tracks_energy_balance_in_subhour():
    tracker = _make_tracker(4)
    battery = Battery(
        capacity=100.0,
        nominal_power=50.0,
        initial_soc=0.5,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=0.0,
        power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        time_step_ratio=0.25,
        seconds_per_time_step=900,
        episode_tracker=tracker,
    )
    battery.reset()

    # Dataset-resolution command corresponding to 2.5 kWh over a 15-minute step.
    battery.charge(10.0)

    assert battery.energy_balance[0] == pytest.approx(2.5)
    assert battery.electricity_consumption[0] == pytest.approx(2.5)


def test_battery_degradation_uses_step_energy_without_extra_ratio_scaling():
    tracker = _make_tracker(4)
    battery = Battery(
        capacity=100.0,
        nominal_power=50.0,
        initial_soc=0.5,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=1e-5,
        power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        time_step_ratio=0.25,
        seconds_per_time_step=900,
        episode_tracker=tracker,
    )
    battery.reset()
    battery.charge(10.0)

    expected = (
        battery.capacity_loss_coefficient
        * battery.capacity
        * abs(battery.energy_balance[0])
        / (2.0 * max(battery.degraded_capacity, 1e-10))
    )
    assert battery.degrade() == pytest.approx(expected)


def test_storage_loss_coefficient_compounds_with_physical_step_hours():
    hourly_loss = 0.0036

    for seconds_per_time_step in [15, 900, 3600, 7200]:
        tracker = _make_tracker(4)
        battery = Battery(
            capacity=100.0,
            nominal_power=50.0,
            initial_soc=0.5,
            loss_coefficient=hourly_loss,
            capacity_loss_coefficient=0.0,
            time_step_ratio=1.0,
            seconds_per_time_step=seconds_per_time_step,
            episode_tracker=tracker,
        )
        tank = StorageTank(
            capacity=100.0,
            initial_soc=0.5,
            loss_coefficient=hourly_loss,
            time_step_ratio=1.0,
            seconds_per_time_step=seconds_per_time_step,
            episode_tracker=tracker,
        )

        expected_step_loss = 1.0 - (1.0 - hourly_loss)**(seconds_per_time_step / 3600.0)
        assert battery.loss_coefficient == pytest.approx(expected_step_loss)
        assert tank.loss_coefficient == pytest.approx(expected_step_loss)


def test_storage_tank_constructor_preserves_time_step_ratio():
    tracker = _make_tracker(4)
    tank = StorageTank(
        capacity=10.0,
        initial_soc=0.5,
        time_step_ratio=0.25,
        seconds_per_time_step=900,
        episode_tracker=tracker,
    )

    assert tank.time_step_ratio == pytest.approx(0.25)


def test_battery_native_multi_hour_power_limit_uses_step_hours():
    tracker = _make_tracker(4)
    battery = Battery(
        capacity=500.0,
        nominal_power=50.0,
        initial_soc=0.0,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=0.0,
        power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        depth_of_discharge=1.0,
        time_step_ratio=1.0,
        seconds_per_time_step=7200,
        episode_tracker=tracker,
    )
    battery.reset()
    battery.charge(1000.0)

    assert battery.energy_balance[0] == pytest.approx(100.0)


def test_battery_subhour_capacity_headroom_uses_physical_kwh():
    tracker = _make_tracker(4)
    battery = Battery(
        capacity=100.0,
        nominal_power=50.0,
        initial_soc=0.95,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=0.0,
        power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        depth_of_discharge=1.0,
        time_step_ratio=0.25,
        seconds_per_time_step=900,
        episode_tracker=tracker,
    )
    battery.reset()

    # Dataset-resolution command equivalent to 12.5 physical kWh over 15 minutes.
    battery.charge(50.0)

    assert battery.energy_balance[0] == pytest.approx(5.0)
    assert battery.soc[0] == pytest.approx(1.0)


def test_battery_power_efficiency_curve_uses_average_power():
    tracker = _make_tracker(4)
    battery = Battery(
        capacity=100.0,
        nominal_power=50.0,
        initial_soc=0.0,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=0.0,
        power_efficiency_curve=[[0.0, 0.5], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        depth_of_discharge=1.0,
        time_step_ratio=1.0,
        seconds_per_time_step=15,
        episode_tracker=tracker,
    )
    battery.reset()

    battery.charge(7.2 * 15 / 3600)

    assert battery.efficiency == pytest.approx(0.5 + 0.5 * (7.2 / 50.0))


def test_env_supports_subhour_seconds_per_time_step():
    schema = EV_SCHEMA
    env = CityLearnEnv(
        schema,
        central_agent=True,
        episode_time_steps=2,
        seconds_per_time_step=900,
    )

    obs, _ = env.reset()
    assert env.seconds_per_time_step == 900
    assert obs is not None

    zeros = [np.zeros(env.action_space[0].shape[0], dtype='float32')]
    env.step(zeros)
    env.close()


def test_subhour_ev_charger_reward_observation_uses_physical_hours():
    env = CityLearnEnv(
        MINUTE_SCHEMA,
        central_agent=True,
        episode_time_steps=8,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        observations = env.buildings[0].observations(include_all=True, normalize=False)
        charger = observations['electric_vehicles_chargers_dict']['charger_1_1']

        assert charger['hours_until_departure'] == pytest.approx(4 * 900 / 3600)
    finally:
        env.close()


def test_ev_charger_schedule_aligns_with_nonzero_episode_start():
    env = CityLearnEnv(
        MINUTE_SCHEMA,
        central_agent=True,
        episode_time_steps=4,
        rolling_episode_split=False,
        random_episode_split=False,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        env.reset(seed=0)

        assert env.episode_tracker.episode_start_time_step == 4
        charger = env.buildings[0].electric_vehicle_chargers[0]
        sim = charger.charger_simulation

        assert sim.electric_vehicle_charger_state[0] == pytest.approx(3.0)
        assert sim.electric_vehicle_departure_time[0] == -1
        assert charger.connected_electric_vehicle is None
    finally:
        env.close()


def test_ev_charger_schedule_alignment_respects_simulation_start_offset():
    env = CityLearnEnv(
        MINUTE_SCHEMA,
        central_agent=True,
        simulation_start_time_step=2,
        simulation_end_time_step=7,
        episode_time_steps=3,
        rolling_episode_split=False,
        random_episode_split=False,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        charger = env.buildings[0].electric_vehicle_chargers[0]
        assert env.episode_tracker.episode_start_time_step == 2
        assert charger.charger_simulation.electric_vehicle_charger_state[0] == pytest.approx(1.0)
        assert charger.charger_simulation.electric_vehicle_departure_time[0] == 2

        env.reset(seed=0)
        assert env.episode_tracker.episode_start_time_step == 5
        assert charger.charger_simulation.electric_vehicle_charger_state[0] == pytest.approx(3.0)
        assert charger.charger_simulation.electric_vehicle_departure_time[0] == -1
    finally:
        env.close()


@pytest.mark.parametrize(
    "loss_coefficient",
    [
        pytest.param(_MISSING, id="missing"),
        pytest.param(None, id="null"),
    ],
)
def test_ev_loader_defaults_missing_loss_coefficient_to_zero_for_subhour(tmp_path, loss_coefficient):
    schema_path = _write_15_second_ev_schema(tmp_path, steps=8, loss_coefficient=loss_coefficient)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        assert env.seconds_per_time_step == 15
        assert env.time_step_ratio == pytest.approx(1.0)
        assert env.electric_vehicles[0].battery.time_step_ratio == pytest.approx(1.0)
        assert env.electric_vehicles[0].battery.loss_coefficient == pytest.approx(0.0)
    finally:
        env.close()


def test_ev_loader_scales_explicit_hourly_loss_for_native_15_second_schema(tmp_path):
    hourly_loss = 0.0036
    schema_path = _write_15_second_ev_schema(tmp_path, steps=8, loss_coefficient=hourly_loss)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        expected_step_loss = 1.0 - (1.0 - hourly_loss)**(15 / 3600.0)

        assert env.time_step_ratio == pytest.approx(1.0)
        assert env.electric_vehicles[0].battery.loss_coefficient == pytest.approx(expected_step_loss)
    finally:
        env.close()


def test_15_second_ev_time_observation_bounds_use_step_counts(tmp_path):
    schema_path = _write_15_second_ev_schema(tmp_path, steps=240)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["observations"]["connected_electric_vehicle_at_charger_departure_time"] = {
        "active": True,
        "shared_in_central_agent": False,
    }
    schema["observations"]["incoming_electric_vehicle_at_charger_estimated_arrival_time"] = {
        "active": True,
        "shared_in_central_agent": False,
    }
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=240, random_seed=0)

    try:
        building = env.buildings[0]
        _, high = building.estimate_observation_space_limits(include_all=True, periodic_normalization=False)
        departure_key = "connected_electric_vehicle_at_charger_charger_1_1_departure_time"
        arrival_key = "incoming_electric_vehicle_at_charger_charger_1_1_estimated_arrival_time"

        assert departure_key in high
        assert arrival_key in high
        assert high[departure_key] >= 239
        assert high[arrival_key] >= 239
    finally:
        env.close()


def test_zero_minute_is_inside_periodic_minute_bounds(tmp_path):
    schema_path = _write_15_second_ev_schema(tmp_path, steps=16)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=16, random_seed=0)

    try:
        metadata = env.buildings[0].get_periodic_observation_metadata()
        assert 0 in metadata["minutes"]
        assert 59 in metadata["minutes"]
        assert 60 not in metadata["minutes"]

        low, high = env.buildings[0].estimate_observation_space_limits(
            include_all=True,
            periodic_normalization=True,
        )
        assert "minutes_sin" in low
        assert "minutes_cos" in high
    finally:
        env.close()


def test_15_second_connected_ev_zero_action_does_not_lose_soc_from_default_loss(tmp_path):
    schema_path = _write_15_second_ev_schema(tmp_path, steps=120, initial_soc=0.6, target_soc=0.8)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=120, random_seed=0)

    try:
        env.reset(seed=0)
        ev = env.electric_vehicles[0]
        initial_soc = float(ev.battery.soc[0])
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]

        while env.time_step < env.episode_time_steps - 2:
            env.step(zeros)

        settled_index = max(env.time_step - 1, 0)
        assert float(ev.battery.soc[settled_index]) == pytest.approx(initial_soc, abs=1.0e-9)
    finally:
        env.close()


def test_15_second_charge_immediately_meets_ev_departure_kpis(tmp_path):
    schema_path = _write_15_second_ev_schema(
        tmp_path,
        steps=362,
        initial_soc=0.2,
        target_soc=0.8,
        capacity=10.0,
        charger_power=7.2,
    )
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=362, random_seed=0)

    try:
        env.reset(seed=0)
        ev = env.electric_vehicles[0]
        ev_action_index = env.action_names[0].index("electric_vehicle_storage_charger_1_1")
        soc_history = []

        while not env.terminated:
            actions = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
            actions[0][ev_action_index] = 1.0
            env.step(actions)

            settled_index = max(env.time_step - 1, 0)
            if settled_index < len(ev.battery.soc):
                soc_history.append(float(ev.battery.soc[settled_index]))

        assert soc_history
        assert np.min(np.diff(soc_history)) >= -1.0e-9
        assert soc_history[-1] >= 0.8 - 1.0e-6

        kpis = env.evaluate_v2()
        district = kpis[kpis["name"] == "District"].set_index("cost_function")["value"]

        assert float(district["district_ev_performance_departure_min_acceptable_ratio"]) == pytest.approx(1.0)
        assert float(district["district_ev_performance_departure_success_ratio"]) == pytest.approx(1.0)
        assert float(district["district_ev_performance_departure_soc_deficit_mean_ratio"]) == pytest.approx(0.0)
        assert float(district["district_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio"]) == pytest.approx(0.0)
    finally:
        env.close()


def test_env_prints_explicit_notice_when_dataset_resolution_is_converted(capsys):
    schema = EV_SCHEMA
    env = CityLearnEnv(
        schema,
        central_agent=True,
        episode_time_steps=2,
        seconds_per_time_step=900,
        random_seed=0,
    )

    try:
        captured = capsys.readouterr()

        assert "[CityLearn][unit-conversion]" in captured.out
        assert "dataset_seconds_per_time_step=3600" in captured.out
        assert "seconds_per_time_step=900" in captured.out
        assert "time_step_ratio=0.25" in captured.out
    finally:
        env.close()


def test_subhour_env_scales_initial_and_step_energy_histories():
    schema = EV_SCHEMA
    hourly = CityLearnEnv(schema, central_agent=True, episode_time_steps=24, seconds_per_time_step=3600, random_seed=0)
    quarter_hour = CityLearnEnv(schema, central_agent=True, episode_time_steps=24, seconds_per_time_step=900, random_seed=0)

    try:
        hourly.reset()
        quarter_hour.reset()
        scale = quarter_hour.time_step_ratio / hourly.time_step_ratio

        hourly_building = hourly.buildings[0]
        quarter_hour_building = quarter_hour.buildings[0]

        assert quarter_hour_building.non_shiftable_load_electricity_consumption[0] == pytest.approx(
            hourly_building.non_shiftable_load_electricity_consumption[0] * scale
        )

        for env in [hourly, quarter_hour]:
            for _ in range(12):
                env.step([np.zeros(env.action_space[0].shape[0], dtype='float32')])

        assert quarter_hour_building.non_shiftable_load_electricity_consumption[1] == pytest.approx(
            hourly_building.non_shiftable_load_electricity_consumption[1] * scale
        )

        hourly_pv_building = next(b for b in hourly.buildings if b.pv.nominal_power > 0.0)
        quarter_hour_pv_building = next(b for b in quarter_hour.buildings if b.name == hourly_pv_building.name)
        solar_indices = np.flatnonzero(np.abs(hourly_pv_building.solar_generation) > 1.0e-8)

        assert len(solar_indices) > 0
        solar_index = int(solar_indices[0])
        assert quarter_hour_pv_building.solar_generation[solar_index] == pytest.approx(
            hourly_pv_building.solar_generation[solar_index] * scale
        )
    finally:
        hourly.close()
        quarter_hour.close()
