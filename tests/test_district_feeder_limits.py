from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.balance_audit import IndependentBalanceAudit


MINUTE_DATASET_DIR = Path(__file__).resolve().parents[1] / "tests" / "data" / "minute_ev_demo"
MINUTE_SCHEMA = MINUTE_DATASET_DIR / "schema.json"

DISTRICT_FEEDER_KPIS = {
    "district_feeder_curtailed_import_kwh",
    "district_feeder_curtailed_export_kwh",
    "district_feeder_max_violation_kw",
}


def _build_two_building_feeder_dataset(
    tmp_path: Path,
    *,
    name: str = "feeder_district",
    rows: int = 4,
    seconds_per_time_step: int = 3600,
    base_loads_b1=None,
    base_loads_b2=None,
    solar_b1=None,
    solar_b2=None,
    b1_battery_power: float = 6.0,
    b2_battery_power: float = 4.0,
    b1_battery_efficiency: float = 0.90,
    b2_battery_efficiency: float = 0.90,
    b1_charger_max_charge: float = 10.0,
    b1_charger_min_charge: float = 0.0,
    b1_charger_max_discharge: float = 10.0,
    b1_charger_min_discharge: float = 0.0,
    b2_charger_max_charge: float = 8.0,
    b2_charger_min_charge: float = 0.0,
    b2_charger_max_discharge: float = 8.0,
    b2_charger_min_discharge: float = 0.0,
    ev_connected: bool = True,
    district_electrical_service=None,
    interface: str = "flat",
) -> dict:
    dataset_dir = tmp_path / name
    dataset_dir.mkdir(parents=True, exist_ok=True)

    hours = [((t * seconds_per_time_step) // 3600) % 24 for t in range(rows)]
    minutes = [((t * seconds_per_time_step) % 3600) // 60 for t in range(rows)]
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
            "electricity_pricing": [0.30 if 16 <= h < 19 else 0.12 for h in hours],
            "electricity_pricing_predicted_1": [0.12] * rows,
            "electricity_pricing_predicted_2": [0.12] * rows,
            "electricity_pricing_predicted_3": [0.12] * rows,
        }
    ).to_csv(dataset_dir / "pricing.csv", index=False)

    b1_load = list(base_loads_b1) if base_loads_b1 is not None else [2.0] * rows
    b2_load = list(base_loads_b2) if base_loads_b2 is not None else [1.5] * rows
    b1_pv = list(solar_b1) if solar_b1 is not None else [0.0] * rows
    b2_pv = list(solar_b2) if solar_b2 is not None else [0.0] * rows

    for b_name, loads, pv_series in (
        ("Building_1", b1_load, b1_pv),
        ("Building_2", b2_load, b2_pv),
    ):
        pd.DataFrame(
            {
                "month": [1] * rows,
                "hour": hours,
                "minutes": minutes,
                "day_type": [1] * rows,
                "daylight_savings_status": [0] * rows,
                "indoor_dry_bulb_temperature": [21.0] * rows,
                "average_unmet_cooling_setpoint_difference": [0.0] * rows,
                "indoor_relative_humidity": [45.0] * rows,
                "non_shiftable_load": loads,
                "dhw_demand": [0.0] * rows,
                "cooling_demand": [0.0] * rows,
                "heating_demand": [0.0] * rows,
                "solar_generation": pv_series,
            }
        ).to_csv(dataset_dir / f"{b_name}.csv", index=False)

    for idx, ev_name in enumerate(("EV_1", "EV_2"), start=1):
        if ev_connected:
            charger_df = pd.DataFrame(
                {
                    "electric_vehicle_charger_state": [1] * rows,
                    "electric_vehicle_id": [ev_name] * rows,
                    "electric_vehicle_departure_time": [float(max(rows - 1 - t, 1)) for t in range(rows)],
                    "electric_vehicle_required_soc_departure": [0.60] * rows,
                    "electric_vehicle_estimated_arrival_time": [np.nan] * rows,
                    "electric_vehicle_estimated_soc_arrival": [0.50 if t == 0 else np.nan for t in range(rows)],
                }
            )
        else:
            charger_df = pd.DataFrame(
                {
                    "electric_vehicle_charger_state": [0] * rows,
                    "electric_vehicle_id": [""] * rows,
                    "electric_vehicle_departure_time": [np.nan] * rows,
                    "electric_vehicle_required_soc_departure": [np.nan] * rows,
                    "electric_vehicle_estimated_arrival_time": [np.nan] * rows,
                    "electric_vehicle_estimated_soc_arrival": [np.nan] * rows,
                }
            )
        charger_df.to_csv(dataset_dir / f"charger_{idx}.csv", index=False)

    schema = {
        "random_seed": 0,
        "root_directory": str(dataset_dir),
        "central_agent": True,
        "interface": interface,
        "simulation_start_time_step": 0,
        "simulation_end_time_step": rows - 1,
        "episode_time_steps": rows,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "seconds_per_time_step": seconds_per_time_step,
        "observations": {
            "month": {"active": True, "shared_in_central_agent": True},
            "day_type": {"active": True, "shared_in_central_agent": True},
            "hour": {"active": True, "shared_in_central_agent": True},
            "minutes": {"active": True, "shared_in_central_agent": True},
            "outdoor_dry_bulb_temperature": {"active": True, "shared_in_central_agent": True},
            "carbon_intensity": {"active": True, "shared_in_central_agent": True},
            "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
            "solar_generation": {"active": True, "shared_in_central_agent": False},
            "electrical_storage_soc": {"active": True, "shared_in_central_agent": False},
            "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
            "electricity_pricing": {"active": True, "shared_in_central_agent": True},
            "electric_vehicle_charger_connected_state": {"active": True, "shared_in_central_agent": False},
            "connected_electric_vehicle_at_charger_battery_capacity": {"active": True, "shared_in_central_agent": False},
            "connected_electric_vehicle_at_charger_departure_time": {"active": True, "shared_in_central_agent": False},
            "connected_electric_vehicle_at_charger_required_soc_departure": {"active": True, "shared_in_central_agent": False},
            "connected_electric_vehicle_at_charger_soc": {"active": True, "shared_in_central_agent": False},
        },
        "actions": {
            "electrical_storage": {"active": True},
            "electric_vehicle_storage": {"active": True},
        },
        "reward_function": {
            "type": "citylearn.reward_function.RewardFunction",
            "attributes": {},
        },
        "electric_vehicles_def": {
            "EV_1": {
                "include": True,
                "battery": {
                    "type": "citylearn.energy_model.Battery",
                    "autosize": False,
                    "attributes": {
                        "capacity": 60.0,
                        "nominal_power": 15.0,
                        "initial_soc": 0.50,
                        "efficiency": 1.0,
                        "loss_coefficient": 0.0,
                        "capacity_loss_coefficient": 1.0e-3,
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
                        "capacity": 40.0,
                        "nominal_power": 15.0,
                        "initial_soc": 0.50,
                        "efficiency": 1.0,
                        "loss_coefficient": 0.0,
                        "capacity_loss_coefficient": 1.0e-3,
                        "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    },
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
                "inactive_observations": [],
                "inactive_actions": ["electrical_storage"] if b1_battery_power <= 0 else [],
                "pv": {
                    "type": "citylearn.energy_model.PV",
                    "autosize": False,
                    "attributes": {"nominal_power": 1.0, "generation_mode": "absolute"},
                },
                "electrical_storage": {
                    "type": "citylearn.energy_model.Battery",
                    "autosize": False,
                    "attributes": {
                        "capacity": 20.0 if b1_battery_power > 0 else 0.0,
                        "nominal_power": b1_battery_power,
                        "initial_soc": 0.50,
                        "efficiency": b1_battery_efficiency,
                        "loss_coefficient": 0.0,
                        "capacity_loss_coefficient": 0.0,
                        "power_efficiency_curve": [[0.0, b1_battery_efficiency], [1.0, b1_battery_efficiency]],
                        "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    },
                },
                "chargers": {
                    "charger_1": {
                        "type": "citylearn.electric_vehicle_charger.Charger",
                        "charger_simulation": "charger_1.csv",
                        "autosize": False,
                        "attributes": {
                            "nominal_power": max(b1_charger_max_charge, b1_charger_max_discharge, 1.0),
                            "efficiency": 1.0,
                            "charger_type": 0,
                            "max_charging_power": b1_charger_max_charge,
                            "min_charging_power": b1_charger_min_charge,
                            "max_discharging_power": b1_charger_max_discharge,
                            "min_discharging_power": b1_charger_min_discharge,
                        },
                    }
                },
            },
            "Building_2": {
                "include": True,
                "energy_simulation": "Building_2.csv",
                "weather": "weather.csv",
                "carbon_intensity": "carbon_intensity.csv",
                "pricing": "pricing.csv",
                "inactive_observations": [],
                "inactive_actions": ["electrical_storage"] if b2_battery_power <= 0 else [],
                "pv": {
                    "type": "citylearn.energy_model.PV",
                    "autosize": False,
                    "attributes": {"nominal_power": 1.0, "generation_mode": "absolute"},
                },
                "electrical_storage": {
                    "type": "citylearn.energy_model.Battery",
                    "autosize": False,
                    "attributes": {
                        "capacity": 20.0 if b2_battery_power > 0 else 0.0,
                        "nominal_power": b2_battery_power,
                        "initial_soc": 0.50,
                        "efficiency": b2_battery_efficiency,
                        "loss_coefficient": 0.0,
                        "capacity_loss_coefficient": 0.0,
                        "power_efficiency_curve": [[0.0, b2_battery_efficiency], [1.0, b2_battery_efficiency]],
                        "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                        "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    },
                },
                "chargers": {
                    "charger_2": {
                        "type": "citylearn.electric_vehicle_charger.Charger",
                        "charger_simulation": "charger_2.csv",
                        "autosize": False,
                        "attributes": {
                            "nominal_power": max(b2_charger_max_charge, b2_charger_max_discharge, 1.0),
                            "efficiency": 1.0,
                            "charger_type": 0,
                            "max_charging_power": b2_charger_max_charge,
                            "min_charging_power": b2_charger_min_charge,
                            "max_discharging_power": b2_charger_max_discharge,
                            "min_discharging_power": b2_charger_min_discharge,
                        },
                    }
                },
            },
        },
    }
    if district_electrical_service is not None:
        schema["district_electrical_service"] = deepcopy(district_electrical_service)
    return schema


def test_avoidable_violation_with_solar_ev_minimum_power_and_stationary_battery(tmp_path: Path):
    """Regression test for maintainer reproducer:
    5 kW solar surplus, 10 kW EV charging request with 7 kW minimum, 4 kW stationary battery
    charging request, and 1 kW limit in each direction -> EV paused (0 kW), battery held at 4 kW,
    district exports 1 kW (-1.0 kW net), meeting both limits with 0.0 kW violation.
    """
    schema = _build_two_building_feeder_dataset(
        tmp_path,
        name="avoidable_deadband",
        rows=2,
        base_loads_b1=[0.0, 0.0],
        base_loads_b2=[0.0, 0.0],
        solar_b1=[5.0, 5.0],
        solar_b2=[0.0, 0.0],
        b1_battery_power=0.0,
        b2_battery_power=4.0,
        b2_battery_efficiency=1.0,
        b1_charger_max_charge=10.0,
        b1_charger_min_charge=7.0,
        b2_charger_max_charge=8.0,
        b2_charger_min_charge=0.0,
        district_electrical_service={"enabled": True, "limits": {"import_kw": 1.0, "export_kw": 1.0}},
    )
    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        with IndependentBalanceAudit(env) as balance_audit:
            # Active actions: [b1_ev (10 kW), b2_storage (4 kW), b2_ev (0 kW)]
            env.step([np.array([1.0, 1.0, 0.0], dtype="float32")])
            proof = balance_audit.finish(check_kpis=True)
        assert proof["status"] == "pass"

        b1, b2 = env.buildings
        assert float(b1.chargers_electricity_consumption[0]) == pytest.approx(0.0, abs=1e-6)
        assert float(b2.electrical_storage.electricity_consumption[0]) == pytest.approx(4.0, abs=1e-6)
        assert float(env.net_electricity_consumption[0]) == pytest.approx(-1.0, abs=1e-6)
        assert float(env.feeder_limit_violation_kw[0]) == pytest.approx(0.0, abs=1e-6)
        assert float(env.feeder_curtailed_import_kwh[0]) == pytest.approx(10.0, abs=1e-5)
        assert float(env.feeder_curtailed_export_kwh[0]) == pytest.approx(0.0, abs=1e-6)

        kpis = env.evaluate_v2(include_business_as_usual=False)
        lookup = {(r.level, r.name, r.cost_function): r.value for r in kpis.itertuples()}
        assert lookup[("district", "District", "district_feeder_max_violation_kw")] == pytest.approx(0.0, abs=1e-6)
        assert lookup[("district", "District", "district_feeder_curtailed_import_kwh")] == pytest.approx(10.0, abs=1e-5)
        assert lookup[("district", "District", "district_feeder_curtailed_export_kwh")] == pytest.approx(0.0, abs=1e-6)
    finally:
        env.close()


def test_avoidable_export_violation_with_ev_minimum_discharging_power(tmp_path: Path):
    """Symmetric deadband check on export curtailment:
    5 kW passive load, -10 kW EV V2G discharge request with 7 kW minimum, -4 kW battery discharge,
    and 1 kW limit in each direction -> EV V2G paused (0 kW), battery held at -4 kW,
    district imports 1 kW (+1.0 kW net), meeting both limits with 0.0 kW violation.
    """
    schema = _build_two_building_feeder_dataset(
        tmp_path,
        name="avoidable_export_deadband",
        rows=2,
        base_loads_b1=[5.0, 5.0],
        base_loads_b2=[0.0, 0.0],
        solar_b1=[0.0, 0.0],
        solar_b2=[0.0, 0.0],
        b1_battery_power=0.0,
        b2_battery_power=4.0,
        b2_battery_efficiency=1.0,
        b1_charger_max_discharge=10.0,
        b1_charger_min_discharge=7.0,
        district_electrical_service={"enabled": True, "limits": {"import_kw": 1.0, "export_kw": 1.0}},
    )
    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        with IndependentBalanceAudit(env) as balance_audit:
            # Active actions: [b1_ev (-10 kW), b2_storage (-4 kW), b2_ev (0 kW)]
            env.step([np.array([-1.0, -1.0, 0.0], dtype="float32")])
            proof = balance_audit.finish(check_kpis=True)
        assert proof["status"] == "pass"

        b1, b2 = env.buildings
        assert float(b1.chargers_electricity_consumption[0]) == pytest.approx(0.0, abs=1e-6)
        assert float(b2.electrical_storage.electricity_consumption[0]) == pytest.approx(-4.0, abs=1e-6)
        assert float(env.net_electricity_consumption[0]) == pytest.approx(1.0, abs=1e-6)
        assert float(env.feeder_limit_violation_kw[0]) == pytest.approx(0.0, abs=1e-6)
        assert float(env.feeder_curtailed_export_kwh[0]) == pytest.approx(10.0, abs=1e-5)
    finally:
        env.close()


def test_unavoidable_solar_surplus_continues_and_records_4kw_exceedance(tmp_path: Path):
    """Unavoidable violation case:
    Fixed 5 kW solar surplus, no available control to absorb it, and 1 kW export limit ->
    simulation continues, reports 5 kW export (-5.0 kW net), and records 4 kW exceedance.
    """
    schema = _build_two_building_feeder_dataset(
        tmp_path,
        name="unavoidable_solar",
        rows=3,
        base_loads_b1=[0.0, 0.0, 0.0],
        base_loads_b2=[0.0, 0.0, 0.0],
        solar_b1=[3.0, 3.0, 3.0],
        solar_b2=[2.0, 2.0, 2.0],
        b1_battery_power=0.0,
        b2_battery_power=0.0,
        ev_connected=False,
        district_electrical_service={"enabled": True, "limits": {"import_kw": 1.0, "export_kw": 1.0}},
    )
    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        with IndependentBalanceAudit(env) as balance_audit:
            for _ in range(2):
                # Active actions: [b1_ev, b2_ev] (both chargers have no connected EV)
                env.step([np.zeros(2, dtype="float32")])
            proof = balance_audit.finish(check_kpis=True)
        assert proof["status"] == "pass"

        net = np.asarray(env.net_electricity_consumption, dtype="float64")
        assert np.allclose(net, [-5.0, -5.0], atol=1e-6)
        assert np.allclose(env.feeder_curtailed_import_kwh, [0.0, 0.0], atol=1e-9)
        assert np.allclose(env.feeder_curtailed_export_kwh, [0.0, 0.0], atol=1e-9)
        assert np.allclose(env.feeder_limit_violation_kw, [4.0, 4.0], atol=1e-6)

        kpis = env.evaluate_v2(include_business_as_usual=False)
        lookup = {(r.level, r.name, r.cost_function): r.value for r in kpis.itertuples()}
        assert lookup[("district", "District", "district_energy_grid_total_export_control_kwh")] == pytest.approx(10.0, abs=1e-5)
        assert lookup[("district", "District", "district_feeder_max_violation_kw")] == pytest.approx(4.0, abs=1e-6)
        assert lookup[("district", "District", "district_feeder_curtailed_export_kwh")] == pytest.approx(0.0, abs=1e-9)
    finally:
        env.close()


def test_independent_one_sided_import_and_export_limits(tmp_path: Path):
    # 1) Import limit only (export_kw unset / None): curtails import, leaves 26 kW export unconstrained.
    schema_imp = _build_two_building_feeder_dataset(
        tmp_path,
        name="import_only",
        rows=3,
        base_loads_b1=[2.0, 1.0, 1.0],
        base_loads_b2=[1.5, 1.0, 1.0],
        district_electrical_service={"enabled": True, "limits": {"import_kw": 15.0}},
    )
    env_imp = CityLearnEnv(schema_imp, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env_imp.reset(seed=0)
        env_imp.step([np.array([1.0, 1.0, 1.0, 1.0], dtype="float32")])   # 31.5 kW -> capped to 15.0 kW
        env_imp.step([np.array([-1.0, -1.0, -1.0, -1.0], dtype="float32")])  # -26.0 kW -> unconstrained export
        net = np.asarray(env_imp.net_electricity_consumption, dtype="float64")
        assert net[0] == pytest.approx(15.0, abs=1e-4)
        assert net[1] == pytest.approx(-26.0, abs=1e-4)
        assert np.allclose(env_imp.feeder_limit_violation_kw, [0.0, 0.0], atol=1e-6)
    finally:
        env_imp.close()

    # 2) Export limit only (import_kw unset / None) on entity interface: leaves 31.5 kW import unconstrained, caps export to 12.0 kW.
    schema_exp = _build_two_building_feeder_dataset(
        tmp_path,
        name="export_only",
        rows=3,
        base_loads_b1=[2.0, 1.0, 1.0],
        base_loads_b2=[1.5, 1.0, 1.0],
        interface="entity",
        district_electrical_service={"enabled": True, "limits": {"export_kw": 12.0}},
    )
    env_exp = CityLearnEnv(schema_exp, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env_exp.reset(seed=0)
        with IndependentBalanceAudit(env_exp) as balance_audit:
            pos_payload = {
                "tables": {name: np.full(space.shape, 1.0, dtype="float32") for name, space in env_exp.action_space["tables"].items()}
            }
            neg_payload = {
                "tables": {name: np.full(space.shape, -1.0, dtype="float32") for name, space in env_exp.action_space["tables"].items()}
            }
            env_exp.step(pos_payload)
            _, _, _, _, info = env_exp.step(neg_payload)
            charger_exec = {
                row["owner_module_id"]: row["applied_power_kw"]
                for row in info["entity_action_execution"]["entries"]
                if row["action_name"] == "electric_vehicle_storage"
            }
            assert charger_exec["Building_1/charger_1"] == pytest.approx(-5.0, abs=1e-4)
            assert charger_exec["Building_2/charger_2"] == pytest.approx(-4.0, abs=1e-4)
            proof = balance_audit.finish(check_kpis=True)
        assert proof["status"] == "pass"

        net = np.asarray(env_exp.net_electricity_consumption, dtype="float64")
        assert net[0] == pytest.approx(31.5, abs=1e-4)
        assert net[1] == pytest.approx(-12.0, abs=1e-4)
        assert np.allclose(env_exp.feeder_curtailed_export_kwh, [0.0, 14.0], atol=1e-3)
        assert np.allclose(env_exp.feeder_limit_violation_kw, [0.0, 0.0], atol=1e-6)
    finally:
        env_exp.close()


def test_proportional_import_curtailment_and_passive_load_violation(tmp_path: Path):
    schema = _build_two_building_feeder_dataset(
        tmp_path,
        name="prop_import",
        rows=4,
        base_loads_b1=[2.0, 2.0, 9.0, 2.0],
        base_loads_b2=[1.5, 1.5, 8.0, 1.5],
        district_electrical_service={"enabled": True, "limits": {"import_kw": 15.0}},
    )
    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        with IndependentBalanceAudit(env) as balance_audit:
            for _ in range(3):
                env.step([np.array([1.0, 1.0, 1.0, 1.0], dtype="float32")])
            proof = balance_audit.finish(check_kpis=True)
        assert proof["status"] == "pass"

        b1, b2 = env.buildings
        b1_ctrl_0 = float(b1.electrical_storage.electricity_consumption[0]) + float(b1.chargers_electricity_consumption[0])
        b2_ctrl_0 = float(b2.electrical_storage.electricity_consumption[0]) + float(b2.chargers_electricity_consumption[0])
        assert b1_ctrl_0 / b2_ctrl_0 == pytest.approx(16.0 / 12.0, rel=1e-4)

        net = np.asarray(env.net_electricity_consumption, dtype="float64")
        assert net == pytest.approx([15.0, 15.0, 17.0], abs=1e-4)
        assert env.feeder_limit_violation_kw == pytest.approx([0.0, 0.0, 2.0], abs=1e-4)
    finally:
        env.close()


def test_subhourly_time_varying_envelopes_and_config_validation(tmp_path: Path):
    import_envelope = [14.0, 8.0, 20.0, 20.0, 20.0]
    export_envelope = [20.0, 20.0, 6.0, 10.0, 20.0]
    schema = _build_two_building_feeder_dataset(
        tmp_path,
        name="subhourly_envelope",
        rows=5,
        seconds_per_time_step=900,
        base_loads_b1=[0.5] * 5,
        base_loads_b2=[0.5] * 5,
        district_electrical_service={
            "enabled": True,
            "limits": {"import_kw": import_envelope, "export_kw": export_envelope},
        },
    )
    env = CityLearnEnv(schema, offline=True, render_mode="none", physics_invariant_checks=True)
    try:
        env.reset(seed=0)
        env.step([np.array([1.0, 1.0, 1.0, 1.0], dtype="float32")])
        env.step([np.array([1.0, 1.0, 1.0, 1.0], dtype="float32")])
        env.step([np.array([-1.0, -1.0, -1.0, -1.0], dtype="float32")])
        env.step([np.array([-1.0, -1.0, -1.0, -1.0], dtype="float32")])

        district_kw = np.asarray(env.net_electricity_consumption, dtype="float64") / 0.25
        assert district_kw == pytest.approx([14.0, 8.0, -6.0, -10.0], abs=1e-3)
        assert np.allclose(env.feeder_limit_violation_kw, 0.0, atol=1e-6)
    finally:
        env.close()

    with pytest.raises(ValueError, match="must be >= 0.0"):
        CityLearnEnv(
            str(MINUTE_SCHEMA),
            offline=True,
            district_electrical_service={"enabled": True, "limits": {"import_kw": -5.0}},
        )

    with pytest.raises(ValueError, match="unknown keys"):
        CityLearnEnv(
            str(MINUTE_SCHEMA),
            offline=True,
            district_electrical_service={"enabled": True, "limits": {"imports_kw": 10.0}},
        )


def test_disabled_district_feeder_preserves_strict_bit_identity():
    env_default = CityLearnEnv(str(MINUTE_SCHEMA), offline=True, render_mode="none", random_seed=7)
    env_explicit_off = CityLearnEnv(
        str(MINUTE_SCHEMA),
        offline=True,
        render_mode="none",
        random_seed=7,
        district_electrical_service={"enabled": False, "limits": {"import_kw": 0.5, "export_kw": 0.5}},
    )
    try:
        obs_a, _ = env_default.reset(seed=7)
        obs_b, _ = env_explicit_off.reset(seed=7)
        assert env_default.feeder_curtailed_import_kwh is None
        assert env_explicit_off.feeder_curtailed_import_kwh is None
        assert env_explicit_off.feeder_curtailed_export_kwh is None
        assert env_explicit_off.feeder_limit_violation_kw is None
        assert np.array_equal(obs_a[0], obs_b[0])

        step_idx = 0
        while not env_default.terminated:
            action = [np.array([0.4 if step_idx % 2 == 0 else -0.3, 0.5], dtype="float32")]
            out_a = env_default.step(action)
            out_b = env_explicit_off.step(action)
            assert np.array_equal(out_a[0][0], out_b[0][0])
            assert out_a[1] == out_b[1]
            step_idx += 1

        assert env_default.net_electricity_consumption == env_explicit_off.net_electricity_consumption
        assert env_default.net_electricity_consumption_cost == env_explicit_off.net_electricity_consumption_cost
        assert env_default.net_electricity_consumption_emission == env_explicit_off.net_electricity_consumption_emission

        kpis_a = env_default.evaluate_v2(include_business_as_usual=True)
        kpis_b = env_explicit_off.evaluate_v2(include_business_as_usual=True)
        assert set(kpis_a["cost_function"]).isdisjoint(DISTRICT_FEEDER_KPIS)
        pd.testing.assert_frame_equal(kpis_a, kpis_b, check_exact=True)
    finally:
        env_default.close()
        env_explicit_off.close()
