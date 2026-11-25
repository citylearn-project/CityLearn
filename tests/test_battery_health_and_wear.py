from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.energy_model import Battery
from citylearn.multi_community import MultiCommunityEnv


MINUTE_DATASET_DIR = Path(__file__).resolve().parents[1] / "tests" / "data" / "minute_ev_demo"
MINUTE_SCHEMA = MINUTE_DATASET_DIR / "schema.json"

BATTERY_HEALTH_AUDIT_KPIS = {
    "building_ev_battery_health_terminal_soh_ratio",
    "building_ev_battery_health_capacity_fade_kwh",
    "building_ev_battery_health_capacity_fade_ratio",
    "building_ev_battery_health_equivalent_full_cycles_count",
    "district_ev_battery_health_terminal_soh_ratio",
    "district_ev_battery_health_capacity_fade_kwh",
    "district_ev_battery_health_capacity_fade_ratio",
    "district_ev_battery_health_equivalent_full_cycles_count",
}

REMOVED_STATIONARY_DUPLICATE_KPIS = {
    "building_battery_health_terminal_soh_ratio",
    "building_battery_health_capacity_fade_kwh",
    "district_battery_health_terminal_soh_ratio",
    "district_battery_health_capacity_fade_kwh",
    "portfolio_battery_health_terminal_soh_ratio",
    "portfolio_battery_health_capacity_fade_kwh",
    "building_ev_battery_terminal_soh_ratio",
    "building_ev_battery_capacity_fade_kwh",
    "building_ev_battery_capacity_fade_ratio",
    "building_ev_battery_equivalent_full_cycles_count",
    "district_ev_battery_terminal_soh_ratio",
    "district_ev_battery_capacity_fade_kwh",
    "district_ev_battery_capacity_fade_ratio",
    "district_ev_battery_equivalent_full_cycles_count",
    "portfolio_ev_battery_terminal_soh_ratio",
    "portfolio_ev_battery_capacity_fade_kwh",
    "portfolio_ev_battery_capacity_fade_ratio",
    "portfolio_ev_battery_equivalent_full_cycles_count",
}


def _build_battery_health_schema(
    dataset_dir: Path,
    *,
    rows: int = 5,
    b1_storage_capacity: float = 20.0,
    b2_storage_capacity: float = 30.0,
    b1_storage_loss_coeff: float = 1.0e-3,
    b2_storage_loss_coeff: float = 2.0e-3,
    b1_storage_nominal_power: float = 6.0,
    b2_storage_nominal_power: float = 6.0,
    ev1_capacity: float = 60.0,
    ev2_capacity: float = 40.0,
    ev1_loss_coeff: float = 1.0e-3,
    ev2_loss_coeff: float = 2.0e-3,
    charger1_max_power: float = 10.0,
    charger2_max_power: float = 8.0,
    charger1_schedule: dict | None = None,
    charger2_schedule: dict | None = None,
    include_evs: bool = True,
    include_chargers: bool = True,
    include_unequipped_building: bool = True,
) -> dict:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    hours = [t % 24 for t in range(rows)]
    weather = pd.DataFrame(
        {
            "outdoor_dry_bulb_temperature": [20.0] * rows,
            "outdoor_relative_humidity": [50.0] * rows,
            "diffuse_solar_irradiance": [0.0] * rows,
            "direct_solar_irradiance": [0.0] * rows,
            "outdoor_dry_bulb_temperature_predicted_1": [20.0] * rows,
            "outdoor_dry_bulb_temperature_predicted_2": [20.0] * rows,
            "outdoor_dry_bulb_temperature_predicted_3": [20.0] * rows,
            "outdoor_relative_humidity_predicted_1": [50.0] * rows,
            "outdoor_relative_humidity_predicted_2": [50.0] * rows,
            "outdoor_relative_humidity_predicted_3": [50.0] * rows,
            "diffuse_solar_irradiance_predicted_1": [0.0] * rows,
            "diffuse_solar_irradiance_predicted_2": [0.0] * rows,
            "diffuse_solar_irradiance_predicted_3": [0.0] * rows,
            "direct_solar_irradiance_predicted_1": [0.0] * rows,
            "direct_solar_irradiance_predicted_2": [0.0] * rows,
            "direct_solar_irradiance_predicted_3": [0.0] * rows,
        }
    )
    weather.to_csv(dataset_dir / "weather.csv", index=False)
    pd.DataFrame({"carbon_intensity": [0.2] * rows}).to_csv(dataset_dir / "carbon_intensity.csv", index=False)
    pd.DataFrame(
        {
            "electricity_pricing": [0.15] * rows,
            "electricity_pricing_predicted_1": [0.15] * rows,
            "electricity_pricing_predicted_2": [0.15] * rows,
            "electricity_pricing_predicted_3": [0.15] * rows,
        }
    ).to_csv(dataset_dir / "pricing.csv", index=False)

    building_names = ["Building_1", "Building_2"] + (["Building_3"] if include_unequipped_building else [])
    for b_name in building_names:
        pd.DataFrame(
            {
                "month": [1] * rows,
                "hour": hours,
                "minutes": [0] * rows,
                "day_type": [1] * rows,
                "daylight_savings_status": [0] * rows,
                "indoor_dry_bulb_temperature": [21.0] * rows,
                "average_unmet_cooling_setpoint_difference": [0.0] * rows,
                "indoor_relative_humidity": [45.0] * rows,
                "non_shiftable_load": [2.0] * rows,
                "dhw_demand": [0.0] * rows,
                "cooling_demand": [0.0] * rows,
                "heating_demand": [0.0] * rows,
                "solar_generation": [0.0] * rows,
            }
        ).to_csv(dataset_dir / f"{b_name}.csv", index=False)

    if include_chargers:
        schedules = (
            (1, "EV_1", charger1_schedule),
            (2, "EV_2", charger2_schedule),
        )
        for idx, default_ev_name, custom in schedules:
            base = {
                "electric_vehicle_charger_state": [1] * rows,
                "electric_vehicle_id": [default_ev_name] * rows,
                "electric_vehicle_departure_time": [float(max(rows - 1 - t, 1)) for t in range(rows)],
                "electric_vehicle_required_soc_departure": [0.60] * rows,
                "electric_vehicle_estimated_arrival_time": [np.nan] * rows,
                "electric_vehicle_estimated_soc_arrival": [0.50 if t == 0 else np.nan for t in range(rows)],
            }
            if custom is not None:
                base.update(custom)
            pd.DataFrame(base).to_csv(dataset_dir / f"charger_{idx}.csv", index=False)

    b1_inactive_obs = []
    b1_inactive_act = []
    if b1_storage_capacity <= 0.0:
        b1_inactive_obs.append("electrical_storage_soc")
        b1_inactive_act.append("electrical_storage")
    if not include_chargers:
        b1_inactive_obs.extend(
            [
                "electric_vehicle_charger_connected_state",
                "connected_electric_vehicle_at_charger_battery_capacity",
                "connected_electric_vehicle_at_charger_departure_time",
                "connected_electric_vehicle_at_charger_required_soc_departure",
                "connected_electric_vehicle_at_charger_soc",
            ]
        )
        b1_inactive_act.append("electric_vehicle_storage")

    b2_inactive_obs = []
    b2_inactive_act = []
    if b2_storage_capacity <= 0.0:
        b2_inactive_obs.append("electrical_storage_soc")
        b2_inactive_act.append("electrical_storage")
    if not include_chargers:
        b2_inactive_obs.extend(
            [
                "electric_vehicle_charger_connected_state",
                "connected_electric_vehicle_at_charger_battery_capacity",
                "connected_electric_vehicle_at_charger_departure_time",
                "connected_electric_vehicle_at_charger_required_soc_departure",
                "connected_electric_vehicle_at_charger_soc",
            ]
        )
        b2_inactive_act.append("electric_vehicle_storage")

    buildings_cfg = {
        "Building_1": {
            "include": True,
            "energy_simulation": "Building_1.csv",
            "weather": "weather.csv",
            "carbon_intensity": "carbon_intensity.csv",
            "pricing": "pricing.csv",
            "inactive_observations": b1_inactive_obs,
            "inactive_actions": b1_inactive_act,
            "electrical_storage": {
                "type": "citylearn.energy_model.Battery",
                "autosize": False,
                "attributes": {
                    "capacity": b1_storage_capacity,
                    "nominal_power": b1_storage_nominal_power if b1_storage_capacity > 0.0 else 0.0,
                    "initial_soc": 0.50 if b1_storage_capacity > 0.0 else 0.0,
                    "efficiency": 1.0,
                    "loss_coefficient": 0.0,
                    "capacity_loss_coefficient": b1_storage_loss_coeff,
                    "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                    "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                },
            },
        },
        "Building_2": {
            "include": True,
            "energy_simulation": "Building_2.csv",
            "weather": "weather.csv",
            "carbon_intensity": "carbon_intensity.csv",
            "pricing": "pricing.csv",
            "inactive_observations": b2_inactive_obs,
            "inactive_actions": b2_inactive_act,
            "electrical_storage": {
                "type": "citylearn.energy_model.Battery",
                "autosize": False,
                "attributes": {
                    "capacity": b2_storage_capacity,
                    "nominal_power": b2_storage_nominal_power if b2_storage_capacity > 0.0 else 0.0,
                    "initial_soc": 0.50 if b2_storage_capacity > 0.0 else 0.0,
                    "efficiency": 1.0,
                    "loss_coefficient": 0.0,
                    "capacity_loss_coefficient": b2_storage_loss_coeff,
                    "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                    "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                },
            },
        },
    }

    if include_chargers:
        buildings_cfg["Building_1"]["chargers"] = {
            "charger_1": {
                "type": "citylearn.electric_vehicle_charger.Charger",
                "charger_simulation": "charger_1.csv",
                "autosize": False,
                "attributes": {
                    "nominal_power": charger1_max_power,
                    "efficiency": 1.0,
                    "charger_type": 0,
                    "max_charging_power": charger1_max_power,
                    "min_charging_power": 0.0,
                    "max_discharging_power": charger1_max_power,
                    "min_discharging_power": 0.0,
                },
            }
        }
        buildings_cfg["Building_2"]["chargers"] = {
            "charger_2": {
                "type": "citylearn.electric_vehicle_charger.Charger",
                "charger_simulation": "charger_2.csv",
                "autosize": False,
                "attributes": {
                    "nominal_power": charger2_max_power,
                    "efficiency": 1.0,
                    "charger_type": 0,
                    "max_charging_power": charger2_max_power,
                    "min_charging_power": 0.0,
                    "max_discharging_power": charger2_max_power,
                    "min_discharging_power": 0.0,
                },
            }
        }

    if include_unequipped_building:
        buildings_cfg["Building_3"] = {
            "include": True,
            "energy_simulation": "Building_3.csv",
            "weather": "weather.csv",
            "carbon_intensity": "carbon_intensity.csv",
            "pricing": "pricing.csv",
            "inactive_observations": [
                "electrical_storage_soc",
                "electric_vehicle_charger_connected_state",
                "connected_electric_vehicle_at_charger_battery_capacity",
                "connected_electric_vehicle_at_charger_departure_time",
                "connected_electric_vehicle_at_charger_required_soc_departure",
                "connected_electric_vehicle_at_charger_soc",
            ],
            "inactive_actions": ["electrical_storage", "electric_vehicle_storage"],
        }

    ev_defs = {}
    if include_evs:
        ev_defs = {
            "EV_1": {
                "include": True,
                "battery": {
                    "type": "citylearn.energy_model.Battery",
                    "autosize": False,
                    "attributes": {
                        "capacity": ev1_capacity,
                        "nominal_power": max(25.0, charger1_max_power, charger2_max_power),
                        "initial_soc": 0.50 if ev1_capacity > 0.0 else 0.0,
                        "efficiency": 1.0,
                        "loss_coefficient": 0.0,
                        "capacity_loss_coefficient": ev1_loss_coeff,
                        "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    },
                },
            },
            "EV_2": {
                "include": True,
                "battery": {
                    "type": "citylearn.energy_model.Battery",
                    "autosize": False,
                    "attributes": {
                        "capacity": ev2_capacity,
                        "nominal_power": max(25.0, charger1_max_power, charger2_max_power),
                        "initial_soc": 0.50 if ev2_capacity > 0.0 else 0.0,
                        "efficiency": 1.0,
                        "loss_coefficient": 0.0,
                        "capacity_loss_coefficient": ev2_loss_coeff,
                        "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    },
                },
            },
        }

    return {
        "random_seed": 0,
        "root_directory": str(dataset_dir),
        "central_agent": True,
        "interface": "flat",
        "simulation_start_time_step": 0,
        "simulation_end_time_step": rows - 1,
        "episode_time_steps": rows,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "seconds_per_time_step": 3600,
        "observations": {
            "hour": {"active": True, "shared_in_central_agent": True},
            "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
            "electrical_storage_soc": {
                "active": (b1_storage_capacity > 0.0 or b2_storage_capacity > 0.0),
                "shared_in_central_agent": False,
            },
            "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
            "electricity_pricing": {"active": True, "shared_in_central_agent": True},
            "electric_vehicle_charger_connected_state": {"active": include_chargers, "shared_in_central_agent": False},
            "connected_electric_vehicle_at_charger_battery_capacity": {
                "active": include_chargers,
                "shared_in_central_agent": False,
            },
            "connected_electric_vehicle_at_charger_departure_time": {
                "active": include_chargers,
                "shared_in_central_agent": False,
            },
            "connected_electric_vehicle_at_charger_required_soc_departure": {
                "active": include_chargers,
                "shared_in_central_agent": False,
            },
            "connected_electric_vehicle_at_charger_soc": {
                "active": include_chargers,
                "shared_in_central_agent": False,
            },
        },
        "actions": {
            "electrical_storage": {"active": (b1_storage_capacity > 0.0 or b2_storage_capacity > 0.0)},
            "electric_vehicle_storage": {"active": include_chargers},
        },
        "reward_function": {
            "type": "citylearn.reward_function.RewardFunction",
            "attributes": {},
        },
        "electric_vehicles_def": ev_defs,
        "buildings": buildings_cfg,
    }


def test_battery_soh_degradation_and_equivalent_full_cycles_properties():
    zero_battery = Battery(capacity=0.0, nominal_power=0.0, random_seed=0)
    # Zero capacity before reset()
    assert zero_battery.current_state_of_health == 1.0
    assert np.array_equal(zero_battery.state_of_health, np.array([1.0]))
    assert zero_battery.equivalent_full_cycles == 0.0
    assert zero_battery.capacity_fade_kwh == 0.0

    tracker = MagicMock()
    tracker.episode_time_steps = 4
    zero_battery.episode_tracker = tracker
    zero_battery.reset()
    assert zero_battery.current_state_of_health == 1.0
    assert np.array_equal(zero_battery.state_of_health, np.array([1.0]))
    assert zero_battery.equivalent_full_cycles == 0.0
    assert zero_battery.capacity_fade_kwh == 0.0

    battery = Battery(
        capacity=50.0,
        nominal_power=25.0,
        initial_soc=0.5,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=1.0e-3,
        power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        discharge_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        seconds_per_time_step=3600,
        random_seed=0,
    )
    # Positive capacity before reset()
    assert battery.current_state_of_health == 1.0
    assert np.array_equal(battery.state_of_health, np.array([1.0]))
    assert battery.equivalent_full_cycles == 0.0
    assert battery.capacity_fade_kwh == 0.0

    battery.episode_tracker = tracker
    battery.reset()
    # At time_step == 0 before the first transfer
    assert battery.current_state_of_health == 1.0
    assert np.array_equal(battery.state_of_health, np.array([1.0]))
    assert battery.equivalent_full_cycles == 0.0
    assert battery.capacity_fade_kwh == 0.0

    battery.charge(10.0)
    c1 = 50.0 - (1.0e-3 * 50.0 * 10.0 / (2.0 * 50.0))
    assert battery.degraded_capacity == pytest.approx(c1, rel=1e-12)
    assert battery.current_state_of_health == pytest.approx(c1 / 50.0, rel=1e-12)
    assert battery.capacity_fade_kwh == pytest.approx(50.0 - c1, rel=1e-12)
    assert battery.equivalent_full_cycles == pytest.approx(10.0 / 100.0, rel=1e-12)

    battery.next_time_step()
    assert len(battery.state_of_health) == 2
    assert battery.state_of_health[0] == pytest.approx(c1 / 50.0, rel=1e-12)
    assert battery.state_of_health[1] == pytest.approx(c1 / 50.0, rel=1e-12)

    battery.next_time_step()
    battery.charge(-15.0)
    c2 = c1 - (1.0e-3 * 50.0 * 15.0 / (2.0 * c1))
    soh_series = battery.state_of_health
    assert soh_series.shape == (3,)
    assert soh_series[0] == pytest.approx(c1 / 50.0, rel=1e-12)
    assert soh_series[1] == pytest.approx(c1 / 50.0, rel=1e-12)
    assert soh_series[2] == pytest.approx(c2 / 50.0, rel=1e-12)
    assert battery.current_state_of_health == pytest.approx(c2 / 50.0, rel=1e-12)
    assert battery.capacity_fade_kwh == pytest.approx(50.0 - c2, rel=1e-12)
    assert battery.equivalent_full_cycles == pytest.approx((10.0 + 15.0) / 100.0, rel=1e-12)


def test_battery_same_step_multiple_transfers_count_gross_accepted_terminal_energy():
    tracker = MagicMock()
    tracker.episode_time_steps = 3
    battery = Battery(
        capacity=50.0,
        nominal_power=25.0,
        initial_soc=0.5,
        efficiency=1.0,
        loss_coefficient=0.0,
        capacity_loss_coefficient=1.0e-3,
        power_efficiency_curve=[[0.0, 1.0], [1.0, 1.0]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        discharge_power_curve=[[0.0, 1.0], [1.0, 1.0]],
        seconds_per_time_step=3600,
        random_seed=0,
    )
    battery.episode_tracker = tracker
    battery.reset()

    # Same-step opposing calls (+10 kWh and -10 kWh): gross counters record 20 kWh -> 0.20 EFC (not 0.10)
    battery.charge(10.0)
    battery.charge(-10.0)
    assert float(battery.gross_energy_charge[0]) == pytest.approx(10.0, rel=1e-9)
    assert float(battery.gross_energy_discharge[0]) == pytest.approx(10.0, rel=1e-9)
    assert battery.equivalent_full_cycles == pytest.approx(0.20, rel=1e-9)

    c_after_charge = 50.0 - (1.0e-3 * 50.0 * 10.0 / (2.0 * 50.0))
    c_after_discharge = c_after_charge - (1.0e-3 * 50.0 * 10.0 / (2.0 * c_after_charge))
    assert battery.degraded_capacity == pytest.approx(c_after_discharge, rel=1e-12)
    assert battery.capacity_fade_kwh == pytest.approx(50.0 - c_after_discharge, rel=1e-12)

    # Next step: two same-direction transfers (+6 kWh and +4 kWh) plus a capacity-clipped request
    battery.next_time_step()
    battery.charge(6.0)
    battery.charge(4.0)
    assert float(battery.gross_energy_charge[1]) == pytest.approx(10.0, rel=1e-9)
    assert battery.equivalent_full_cycles == pytest.approx((20.0 + 10.0) / 100.0, rel=1e-9)


def test_normal_dispatch_uses_single_direction_per_step_and_matches_throughput_kpis(tmp_path: Path):
    schema = _build_battery_health_schema(tmp_path / "single_dir_dispatch", rows=4, include_unequipped_building=False)
    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        # Step 0: B1 charges storage & EV, B2 discharges storage & EV
        # Step 1: B1 discharges storage & EV, B2 charges storage & EV
        # Step 2: B1 charges storage & EV, B2 discharges storage & EV
        for step_actions in (
            [1.0, 0.6, -0.5, -0.5],
            [-0.5, -0.4, 1.0, 0.75],
            [0.25, 0.3, -0.25, -0.25],
        ):
            t = int(env.time_step)
            env.step([np.array(step_actions, dtype="float32")])
            for b in env.buildings:
                s = b.electrical_storage
                assert not (float(s.gross_energy_charge[t]) > 0.0 and float(s.gross_energy_discharge[t]) > 0.0)
            for ev in env.electric_vehicles:
                s = ev.battery
                assert not (float(s.gross_energy_charge[t]) > 0.0 and float(s.gross_energy_discharge[t]) > 0.0)

        kpis = env.evaluate_v2(include_business_as_usual=False, include_battery_health_audit=True)
        lookup = {(r.level, r.name, r.cost_function): r.value for r in kpis.itertuples()}

        b1, b2 = env.buildings
        ev1 = next(ev for ev in env.electric_vehicles if ev.name == "EV_1")
        ev2 = next(ev for ev in env.electric_vehicles if ev.name == "EV_2")

        # Both charge and discharge occurred across separate steps on every battery
        for battery in (b1.electrical_storage, b2.electrical_storage, ev1.battery, ev2.battery):
            assert float(np.sum(battery.gross_energy_charge[:3])) > 0.0
            assert float(np.sum(battery.gross_energy_discharge[:3])) > 0.0

        # Battery.equivalent_full_cycles agrees with existing stationary cycle KPI and EV cycle KPI
        assert b1.electrical_storage.equivalent_full_cycles == pytest.approx(
            lookup[("building", "Building_1", "building_battery_health_equivalent_full_cycles_count")],
            rel=1e-7,
        )
        assert b2.electrical_storage.equivalent_full_cycles == pytest.approx(
            lookup[("building", "Building_2", "building_battery_health_equivalent_full_cycles_count")],
            rel=1e-7,
        )
        assert ev1.battery.equivalent_full_cycles == pytest.approx(
            lookup[("building", "Building_1", "building_ev_battery_health_equivalent_full_cycles_count")],
            rel=1e-7,
        )
        assert ev2.battery.equivalent_full_cycles == pytest.approx(
            lookup[("building", "Building_2", "building_ev_battery_health_equivalent_full_cycles_count")],
            rel=1e-7,
        )
    finally:
        env.close()


def test_ev_moving_between_buildings_attributes_wear_and_last_connection_soh(tmp_path: Path):
    # 60 kWh EV_1 connects at Building_1 in step 0 (charges 6 kWh), then moves to Building_2 in step 1 (0 kWh)
    # and step 2 (charges another 6 kWh). Only EV_1 is in the fleet.
    rows = 4
    c1_sched = {
        "electric_vehicle_charger_state": [1, 0, 0, 0],
        "electric_vehicle_id": ["EV_1", "", "", ""],
        "electric_vehicle_departure_time": [1.0, -1.0, -1.0, -1.0],
        "electric_vehicle_required_soc_departure": [0.60, np.nan, np.nan, np.nan],
        "electric_vehicle_estimated_arrival_time": [np.nan] * rows,
        "electric_vehicle_estimated_soc_arrival": [0.50, np.nan, np.nan, np.nan],
    }
    c2_sched = {
        "electric_vehicle_charger_state": [0, 1, 1, 0],
        "electric_vehicle_id": ["", "EV_1", "EV_1", ""],
        "electric_vehicle_departure_time": [-1.0, 2.0, 1.0, -1.0],
        "electric_vehicle_required_soc_departure": [np.nan, 0.60, 0.60, np.nan],
        "electric_vehicle_estimated_arrival_time": [np.nan] * rows,
        "electric_vehicle_estimated_soc_arrival": [np.nan, 0.60, np.nan, np.nan],
    }
    schema = _build_battery_health_schema(
        tmp_path / "ev_moves",
        rows=rows,
        ev1_capacity=60.0,
        ev1_loss_coeff=1.0e-3,
        charger1_max_power=10.0,
        charger2_max_power=10.0,
        charger1_schedule=c1_sched,
        charger2_schedule=c2_sched,
        include_unequipped_building=False,
    )
    del schema["electric_vehicles_def"]["EV_2"]

    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        # Step 0: EV_1 at Building_1 charges 0.6 * 10 kW * 1 h = 6.0 kWh -> 0.05 EFC, 0.003 kWh fade
        env.step([np.array([0.0, 0.6, 0.0, 0.0], dtype="float32")])
        # Step 1: EV_1 connects at Building_2 and exchanges 0 kWh
        env.step([np.array([0.0, 0.0, 0.0, 0.0], dtype="float32")])

        kpis_after_idle_visit = env.evaluate_v2(include_business_as_usual=False, include_battery_health_audit=True)
        lookup_mid = {(r.level, r.name, r.cost_function): r.value for r in kpis_after_idle_visit.itertuples()}

        expected_soh_step0 = (60.0 - 0.003) / 60.0
        # Building_1 gets 0.05 EFC and 0.003 kWh loss
        assert lookup_mid[("building", "Building_1", "building_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            0.05, rel=1e-9
        )
        assert lookup_mid[("building", "Building_1", "building_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            0.003, rel=1e-9
        )
        assert lookup_mid[("building", "Building_1", "building_ev_battery_health_capacity_fade_ratio")] == pytest.approx(
            0.003 / 60.0, rel=1e-9
        )
        assert lookup_mid[("building", "Building_1", "building_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            expected_soh_step0, rel=1e-9
        )

        # Building_2 exchanged 0 kWh: 0.0 EFC and 0.0 kWh loss, with SOH at EV_1's connection there
        assert lookup_mid[("building", "Building_2", "building_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            0.0, abs=1e-12
        )
        assert lookup_mid[("building", "Building_2", "building_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            0.0, abs=1e-12
        )
        assert lookup_mid[("building", "Building_2", "building_ev_battery_health_capacity_fade_ratio")] == pytest.approx(
            0.0, abs=1e-12
        )
        assert lookup_mid[("building", "Building_2", "building_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            expected_soh_step0, rel=1e-9
        )

        # District counts EV_1 (60 kWh) once
        assert lookup_mid[("district", "District", "district_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            0.05, rel=1e-9
        )
        assert lookup_mid[("district", "District", "district_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            0.003, rel=1e-9
        )
        assert lookup_mid[("district", "District", "district_ev_battery_health_capacity_fade_ratio")] == pytest.approx(
            0.003 / 60.0, rel=1e-9
        )
        assert lookup_mid[("district", "District", "district_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            expected_soh_step0, rel=1e-9
        )

        # Step 2: EV_1 charges another 6 kWh at Building_2 -> degrades further at Building_2 only
        env.step([np.array([0.0, 0.0, 0.0, 0.6], dtype="float32")])
        kpis_end = env.evaluate_v2(include_business_as_usual=False, include_battery_health_audit=True)
        lookup_end = {(r.level, r.name, r.cost_function): r.value for r in kpis_end.itertuples()}

        c1 = 60.0 - 0.003
        fade_step2 = 1.0e-3 * 60.0 * 6.0 / (2.0 * c1)
        c2 = c1 - fade_step2

        # Building_1 terminal SOH stays at EV_1's last actual connection at Building_1 (step 0), NOT step 2!
        assert lookup_end[("building", "Building_1", "building_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            c1 / 60.0, rel=1e-12
        )
        assert lookup_end[("building", "Building_1", "building_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            0.003, rel=1e-9
        )
        assert lookup_end[("building", "Building_1", "building_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            0.05, rel=1e-9
        )

        # Building_2 attributes step 2's 6 kWh transfer and fade, and terminal SOH at step 2
        assert lookup_end[("building", "Building_2", "building_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            c2 / 60.0, rel=1e-12
        )
        assert lookup_end[("building", "Building_2", "building_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            fade_step2, rel=1e-9
        )
        assert lookup_end[("building", "Building_2", "building_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            0.05, rel=1e-9
        )

        # District counts EV_1 once (60 kWh): total EFC = 0.10, total fade = 0.003 + fade_step2
        assert lookup_end[("district", "District", "district_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            0.10, rel=1e-9
        )
        assert lookup_end[("district", "District", "district_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            0.003 + fade_step2, rel=1e-9
        )
        assert lookup_end[("district", "District", "district_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            c2 / 60.0, rel=1e-12
        )
    finally:
        env.close()


def test_ev_listed_in_disconnected_schedule_never_connects_and_district_counts_each_eligible_ev_once(tmp_path: Path):
    # Building_2 lists EV_2 in its schedule, with state=0 for every executed step (steps 0, 1) and state=1
    # only on unexecuted step 2. EV_3 has include=False (ineligible).
    rows = 4
    c1_sched = {
        "electric_vehicle_charger_state": [1, 1, 1, 1],
        "electric_vehicle_id": ["EV_1"] * rows,
        "electric_vehicle_departure_time": [3.0, 2.0, 1.0, 1.0],
        "electric_vehicle_required_soc_departure": [0.60] * rows,
        "electric_vehicle_estimated_arrival_time": [np.nan] * rows,
        "electric_vehicle_estimated_soc_arrival": [0.50, np.nan, np.nan, np.nan],
    }
    c2_sched = {
        "electric_vehicle_charger_state": [0, 0, 1, 0],
        "electric_vehicle_id": ["EV_2", "EV_2", "EV_2", "EV_2"],
        "electric_vehicle_departure_time": [-1.0, -1.0, 1.0, -1.0],
        "electric_vehicle_required_soc_departure": [0.60] * rows,
        "electric_vehicle_estimated_arrival_time": [np.nan] * rows,
        "electric_vehicle_estimated_soc_arrival": [np.nan, np.nan, 0.50, np.nan],
    }
    schema = _build_battery_health_schema(
        tmp_path / "ev_never_connects",
        rows=rows,
        ev1_capacity=60.0,
        ev2_capacity=40.0,
        ev1_loss_coeff=1.0e-3,
        ev2_loss_coeff=2.0e-3,
        charger1_max_power=10.0,
        charger2_max_power=10.0,
        charger1_schedule=c1_sched,
        charger2_schedule=c2_sched,
        include_unequipped_building=False,
    )
    schema["electric_vehicles_def"]["EV_3"] = {
        "include": False,
        "battery": {
            "type": "citylearn.energy_model.Battery",
            "autosize": False,
            "attributes": {
                "capacity": 80.0,
                "nominal_power": 25.0,
                "initial_soc": 0.50,
                "efficiency": 1.0,
                "loss_coefficient": 0.0,
                "capacity_loss_coefficient": 1.0e-3,
                "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
            },
        },
    }

    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        # Execute only steps 0 and 1 (so step 2 is NOT executed even though EV_2 was pre-associated for step 2)
        env.step([np.array([0.0, 0.6, 0.0, 0.5], dtype="float32")])
        env.step([np.array([0.0, 0.0, 0.0, 0.5], dtype="float32")])

        kpis = env.evaluate_v2(include_business_as_usual=False, include_battery_health_audit=True)
        lookup = {(r.level, r.name, r.cost_function): r.value for r in kpis.itertuples()}

        # Building_2 had zero realized connections during executed steps 0..1 -> NaN ratios/cycles (NOT 1.0 SOH!)
        assert np.isnan(lookup[("building", "Building_2", "building_ev_battery_health_terminal_soh_ratio")])
        assert lookup[("building", "Building_2", "building_ev_battery_health_capacity_fade_kwh")] == pytest.approx(0.0, abs=1e-12)
        assert np.isnan(lookup[("building", "Building_2", "building_ev_battery_health_capacity_fade_ratio")])
        assert np.isnan(lookup[("building", "Building_2", "building_ev_battery_health_equivalent_full_cycles_count")])

        # District fleet population includes unique eligible EVs (EV_1: 60 kWh + EV_2: 40 kWh = 100 kWh; EV_3 excluded)
        assert lookup[("district", "District", "district_ev_battery_health_capacity_fade_kwh")] == pytest.approx(0.003, rel=1e-9)
        assert lookup[("district", "District", "district_ev_battery_health_capacity_fade_ratio")] == pytest.approx(
            0.003 / 100.0, rel=1e-9
        )
        assert lookup[("district", "District", "district_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            (59.997 + 40.0) / 100.0, rel=1e-9
        )
        assert lookup[("district", "District", "district_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            6.0 / (2.0 * 100.0), rel=1e-9
        )
    finally:
        env.close()


def test_battery_health_audit_kpis_building_district_and_unequipped_building(tmp_path: Path):
    schema = _build_battery_health_schema(tmp_path / "health_3b", rows=4, include_unequipped_building=True)
    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        # Actions: [b1_storage, b1_ev, b2_storage, b2_ev]
        env.step([np.array([1.0, 1.0, -0.5, -0.5], dtype="float32")])
        env.step([np.array([-0.5, -0.8, 1.0, 0.75], dtype="float32")])
        env.step([np.array([0.5, 0.4, -0.25, -0.25], dtype="float32")])

        kpis = env.evaluate_v2(include_business_as_usual=False, include_battery_health_audit=True)
        assert kpis[["unit", "description"]].notna().all().all()
        assert set(kpis["cost_function"]).isdisjoint(REMOVED_STATIONARY_DUPLICATE_KPIS)
        lookup = {(r.level, r.name, r.cost_function): r.value for r in kpis.itertuples()}

        b1, b2, b3 = env.buildings
        ev1 = next(ev for ev in env.electric_vehicles if ev.name == "EV_1")
        ev2 = next(ev for ev in env.electric_vehicles if ev.name == "EV_2")

        # Stationary Battery properties align with the existing Batteries KPI family
        assert b1.electrical_storage.current_state_of_health == pytest.approx(
            1.0 - lookup[("building", "Building_1", "building_battery_health_capacity_fade_ratio")],
            rel=1e-9,
        )
        assert b2.electrical_storage.current_state_of_health == pytest.approx(
            1.0 - lookup[("building", "Building_2", "building_battery_health_capacity_fade_ratio")],
            rel=1e-9,
        )

        assert lookup[("building", "Building_1", "building_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            ev1.battery.current_state_of_health, rel=1e-9
        )
        assert lookup[("building", "Building_1", "building_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            ev1.battery.capacity_fade_kwh, rel=1e-9
        )
        assert lookup[("building", "Building_1", "building_ev_battery_health_capacity_fade_ratio")] == pytest.approx(
            ev1.battery.capacity_fade_kwh / 60.0, rel=1e-9
        )
        assert lookup[("building", "Building_1", "building_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            ev1.battery.equivalent_full_cycles, rel=1e-9
        )

        # Building_3 has zero-capacity storage and no EV chargers: Battery.equivalent_full_cycles returns 0.0,
        # whereas the cycle and SOH/fade KPIs are undefined (NaN), and fade kWh is 0.0
        assert b3.electrical_storage.equivalent_full_cycles == 0.0
        assert np.isnan(lookup[("building", "Building_3", "building_battery_health_equivalent_full_cycles_count")])
        assert np.isnan(lookup[("building", "Building_3", "building_ev_battery_health_terminal_soh_ratio")])
        assert lookup[("building", "Building_3", "building_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            0.0, abs=1e-12
        )
        assert np.isnan(lookup[("building", "Building_3", "building_ev_battery_health_capacity_fade_ratio")])
        assert np.isnan(lookup[("building", "Building_3", "building_ev_battery_health_equivalent_full_cycles_count")])

        # District EV batteries pool over nominal capacity
        expected_dist_ev_soh = (ev1.battery.degraded_capacity + ev2.battery.degraded_capacity) / (60.0 + 40.0)
        expected_dist_ev_fade = ev1.battery.capacity_fade_kwh + ev2.battery.capacity_fade_kwh
        expected_dist_ev_efc = (
            ev1.battery.equivalent_full_cycles * 60.0 + ev2.battery.equivalent_full_cycles * 40.0
        ) / 100.0
        assert lookup[("district", "District", "district_ev_battery_health_terminal_soh_ratio")] == pytest.approx(
            expected_dist_ev_soh, rel=1e-9
        )
        assert lookup[("district", "District", "district_ev_battery_health_capacity_fade_kwh")] == pytest.approx(
            expected_dist_ev_fade, rel=1e-9
        )
        assert lookup[("district", "District", "district_ev_battery_health_capacity_fade_ratio")] == pytest.approx(
            expected_dist_ev_fade / 100.0, rel=1e-9
        )
        assert lookup[("district", "District", "district_ev_battery_health_equivalent_full_cycles_count")] == pytest.approx(
            expected_dist_ev_efc, rel=1e-9
        )
    finally:
        env.close()


def test_multi_community_portfolio_pools_ev_health_ratios_and_cycles_by_nominal_capacity(tmp_path: Path):
    # Stress test: two equally weighted communities with 100 kWh and 50 kWh of EV capacity,
    # capacity_loss_coefficient=1.0, and 9 kWh vs 0 kWh lost -> physical portfolio fade = 6% (0.06), SOH = 94% (0.94).
    schema_a = _build_battery_health_schema(
        tmp_path / "comm_a",
        rows=2,
        ev1_capacity=60.0,
        ev2_capacity=40.0,
        ev1_loss_coeff=1.0,
        ev2_loss_coeff=1.0,
        charger1_max_power=20.0,
        charger2_max_power=20.0,
        include_unequipped_building=False,
    )
    schema_b = _build_battery_health_schema(
        tmp_path / "comm_b",
        rows=2,
        ev1_capacity=30.0,
        ev2_capacity=20.0,
        ev1_loss_coeff=1.0,
        ev2_loss_coeff=1.0,
        charger1_max_power=20.0,
        charger2_max_power=20.0,
        include_unequipped_building=False,
    )
    portfolio = MultiCommunityEnv(
        communities=[
            {"community_id": "a", "schema": schema_a, "weight": 1.0, "env_kwargs": {"offline": True, "render_mode": "none"}},
            {"community_id": "b", "schema": schema_b, "weight": 1.0, "env_kwargs": {"offline": True, "render_mode": "none"}},
        ]
    )
    try:
        portfolio.reset(seed=0)
        # In Community a: EV_1 charges 10.8 kWh (0.54 * 20 kW) -> 5.4 kWh loss; EV_2 charges 7.2 kWh (0.36 * 20 kW) -> 3.6 kWh loss.
        # Total EV loss in Community a = 9.0 kWh; Community b stays idle (0 kWh loss).
        portfolio.step(
            {
                "a": [np.array([0.0, 0.54, 0.0, 0.36], dtype="float32")],
                "b": [np.zeros(4, dtype="float32")],
            }
        )
        kpis = portfolio.evaluate_v2(include_business_as_usual=False, include_battery_health_audit=True)
        assert kpis[["unit", "description"]].notna().all().all()
        assert set(kpis["cost_function"]).isdisjoint(REMOVED_STATIONARY_DUPLICATE_KPIS)

        def pval(metric: str) -> float:
            return float(
                kpis[(kpis["level"] == "portfolio") & (kpis["cost_function"] == metric)]["value"].iloc[0]
            )

        def dval(comm: str, metric: str) -> float:
            return float(
                kpis[
                    (kpis["community_id"] == comm)
                    & (kpis["level"] == "district")
                    & (kpis["cost_function"] == metric)
                ]["value"].iloc[0]
            )

        # EV family: 9 kWh loss over 150 kWh pooled capacity -> 6% fade and 94% SOH (NOT 4.5% / 95.5%)
        assert dval("a", "district_ev_battery_health_capacity_fade_kwh") == pytest.approx(9.0, rel=1e-6)
        assert dval("b", "district_ev_battery_health_capacity_fade_kwh") == pytest.approx(0.0, abs=1e-12)
        assert pval("portfolio_ev_battery_health_capacity_fade_kwh") == pytest.approx(9.0, rel=1e-6)
        assert pval("portfolio_ev_battery_health_capacity_fade_ratio") == pytest.approx(0.06, rel=1e-6)
        assert pval("portfolio_ev_battery_health_terminal_soh_ratio") == pytest.approx(0.94, rel=1e-6)

        efc_a = dval("a", "district_ev_battery_health_equivalent_full_cycles_count")
        efc_b = dval("b", "district_ev_battery_health_equivalent_full_cycles_count")
        assert efc_a == pytest.approx(18.0 / 200.0, rel=1e-6)
        assert efc_b == pytest.approx(0.0, abs=1e-12)
        assert pval("portfolio_ev_battery_health_equivalent_full_cycles_count") == pytest.approx(
            (100.0 * efc_a + 50.0 * efc_b) / 150.0, rel=1e-6
        )
    finally:
        portfolio.close()


@pytest.mark.parametrize("include_bau", [False, True])
def test_multi_community_portfolio_empty_fleet_returns_nan_ratios(tmp_path: Path, include_bau: bool):
    schema_a = _build_battery_health_schema(
        tmp_path / f"empty_a_{include_bau}",
        rows=2,
        b1_storage_capacity=0.0,
        b2_storage_capacity=0.0,
        include_evs=False,
        include_chargers=False,
        include_unequipped_building=False,
    )
    schema_b = _build_battery_health_schema(
        tmp_path / f"empty_b_{include_bau}",
        rows=2,
        b1_storage_capacity=0.0,
        b2_storage_capacity=0.0,
        include_evs=False,
        include_chargers=False,
        include_unequipped_building=False,
    )
    portfolio = MultiCommunityEnv(
        communities=[
            {"community_id": "a", "schema": schema_a, "weight": 1.0, "env_kwargs": {"offline": True, "render_mode": "none"}},
            {"community_id": "b", "schema": schema_b, "weight": 2.0, "env_kwargs": {"offline": True, "render_mode": "none"}},
        ]
    )
    try:
        portfolio.reset(seed=0)
        portfolio.step({"a": [np.zeros(0, dtype="float32")], "b": [np.zeros(0, dtype="float32")]})
        kpis = portfolio.evaluate_v2(include_business_as_usual=include_bau, include_battery_health_audit=True)
        assert kpis[["unit", "description"]].notna().all().all()
        assert set(kpis["cost_function"]).isdisjoint(REMOVED_STATIONARY_DUPLICATE_KPIS)

        port = kpis[kpis["level"] == "portfolio"].set_index("cost_function")["value"]
        assert port["portfolio_ev_battery_health_capacity_fade_kwh"] == pytest.approx(0.0, abs=1e-12)
        assert pd.isna(port["portfolio_ev_battery_health_terminal_soh_ratio"])
        assert pd.isna(port["portfolio_ev_battery_health_capacity_fade_ratio"])
        assert pd.isna(port["portfolio_ev_battery_health_equivalent_full_cycles_count"])
    finally:
        portfolio.close()


def test_representative_24h_challenge_2022_evs_magnitude_and_single_direction_dispatch():
    env = CityLearnEnv(
        "citylearn_challenge_2022_phase_all_plus_evs",
        episode_time_steps=25,
        offline=True,
        render_mode="none",
        physics_invariant_checks=True,
    )
    try:
        env.reset(seed=0)
        step_idx = 0
        while not env.terminated:
            t = int(env.time_step)
            val = 0.25 if (step_idx % 2 == 0) else -0.25
            actions = [
                np.array([val if ("storage" in name) else 0.0 for name in names], dtype="float32")
                for names in env.action_names
            ]
            env.step(actions)
            for building in env.buildings:
                s = building.electrical_storage
                assert not (float(s.gross_energy_charge[t]) > 0.0 and float(s.gross_energy_discharge[t]) > 0.0)
            for ev in env.electric_vehicles:
                s = ev.battery
                assert not (float(s.gross_energy_charge[t]) > 0.0 and float(s.gross_energy_discharge[t]) > 0.0)
            step_idx += 1

        kpis = env.evaluate_v2(include_business_as_usual=False, include_battery_health_audit=True)
        assert set(kpis["cost_function"]).isdisjoint(REMOVED_STATIONARY_DUPLICATE_KPIS)
        dist = kpis[kpis["level"] == "district"].set_index("cost_function")["value"]

        bess_cap = sum(float(b.electrical_storage.capacity) for b in env.buildings)
        ev_cap = sum(float(ev.battery.capacity) for ev in env.electric_vehicles)
        assert bess_cap == pytest.approx(108.8, rel=1e-9)
        assert ev_cap == pytest.approx(540.0, rel=1e-9)

        # Stationary wear from Battery properties aligns with the existing Batteries KPI family
        bess_fade_kwh = sum(float(b.electrical_storage.capacity_fade_kwh) for b in env.buildings)
        bess_fade_ratio = float(dist["district_battery_health_capacity_fade_ratio"])
        assert 1.0e-4 < bess_fade_kwh < 1.0e-2
        assert bess_fade_ratio == pytest.approx(bess_fade_kwh / bess_cap, rel=1e-9)

        ev_fade_kwh = float(dist["district_ev_battery_health_capacity_fade_kwh"])
        ev_fade_ratio = float(dist["district_ev_battery_health_capacity_fade_ratio"])
        ev_soh = float(dist["district_ev_battery_health_terminal_soh_ratio"])
        ev_efc = float(dist["district_ev_battery_health_equivalent_full_cycles_count"])
        assert 1.0e-3 < ev_fade_kwh < 5.0e-2
        assert ev_fade_ratio == pytest.approx(ev_fade_kwh / ev_cap, rel=1e-9)
        assert ev_soh == pytest.approx(1.0 - ev_fade_ratio, rel=1e-9)
        assert ev_efc > 0.1

        # Building-level EV capacity fade sums exactly to district EV capacity fade
        building_ev_fade_sum = float(
            kpis[(kpis["level"] == "building") & (kpis["cost_function"] == "building_ev_battery_health_capacity_fade_kwh")][
                "value"
            ].sum()
        )
        assert building_ev_fade_sum == pytest.approx(ev_fade_kwh, rel=1e-9)
    finally:
        env.close()


def test_default_evaluate_v2_preserves_strict_bit_identity():
    env = CityLearnEnv(str(MINUTE_SCHEMA), offline=True, render_mode="none", random_seed=7)
    try:
        env.reset(seed=7)
        while not env.terminated:
            env.step([np.array([0.3, 0.4], dtype="float32")])
        kpis_default = env.evaluate_v2(include_business_as_usual=True)
        kpis_explicit_false = env.evaluate_v2(include_business_as_usual=True, include_battery_health_audit=False)
        assert set(kpis_default["cost_function"]).isdisjoint(BATTERY_HEALTH_AUDIT_KPIS)
        pd.testing.assert_frame_equal(kpis_default, kpis_explicit_false, check_exact=True)
    finally:
        env.close()
