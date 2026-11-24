import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService


def _write_golden_schema(
    tmp_path: Path,
    *,
    seconds_per_time_step: int,
    steps: int,
    community_market: bool = False,
) -> Path:
    dataset_dir = tmp_path / f"golden_{seconds_per_time_step}s_{steps}"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    elapsed_seconds = np.arange(steps, dtype=int) * int(seconds_per_time_step)
    hours = ((elapsed_seconds // 3600) % 24).astype(int)
    minutes = ((elapsed_seconds % 3600) // 60).astype(int)
    seconds = (elapsed_seconds % 60).astype(int)

    weather = pd.DataFrame(
        {
            "outdoor_dry_bulb_temperature": np.full(steps, 10.0),
            "outdoor_relative_humidity": np.full(steps, 50.0),
            "diffuse_solar_irradiance": np.zeros(steps),
            "direct_solar_irradiance": np.zeros(steps),
            "outdoor_dry_bulb_temperature_predicted_1": np.full(steps, 10.0),
            "outdoor_dry_bulb_temperature_predicted_2": np.full(steps, 10.0),
            "outdoor_dry_bulb_temperature_predicted_3": np.full(steps, 10.0),
            "outdoor_relative_humidity_predicted_1": np.full(steps, 50.0),
            "outdoor_relative_humidity_predicted_2": np.full(steps, 50.0),
            "outdoor_relative_humidity_predicted_3": np.full(steps, 50.0),
            "diffuse_solar_irradiance_predicted_1": np.zeros(steps),
            "diffuse_solar_irradiance_predicted_2": np.zeros(steps),
            "diffuse_solar_irradiance_predicted_3": np.zeros(steps),
            "direct_solar_irradiance_predicted_1": np.zeros(steps),
            "direct_solar_irradiance_predicted_2": np.zeros(steps),
            "direct_solar_irradiance_predicted_3": np.zeros(steps),
        }
    )
    weather.to_csv(dataset_dir / "weather.csv", index=False)

    carbon = np.resize(np.array([0.5, 0.4, 0.3], dtype="float64"), steps)
    prices = np.resize(np.array([0.10, 0.20, 0.30], dtype="float64"), steps)
    pd.DataFrame({"carbon_intensity": carbon}).to_csv(dataset_dir / "carbon_intensity.csv", index=False)
    pd.DataFrame(
        {
            "electricity_pricing": prices,
            "electricity_pricing_predicted_1": prices,
            "electricity_pricing_predicted_2": prices,
            "electricity_pricing_predicted_3": prices,
        }
    ).to_csv(dataset_dir / "pricing.csv", index=False)

    base_building = {
        "month": np.ones(steps, dtype=int),
        "hour": hours,
        "minutes": minutes,
        "seconds": seconds,
        "day_type": np.ones(steps, dtype=int),
        "daylight_savings_status": np.zeros(steps, dtype=int),
        "indoor_dry_bulb_temperature": np.full(steps, 21.0),
        "average_unmet_cooling_setpoint_difference": np.zeros(steps),
        "indoor_relative_humidity": np.full(steps, 45.0),
        "non_shiftable_load": np.zeros(steps),
        "dhw_demand": np.zeros(steps),
        "cooling_demand": np.zeros(steps),
        "heating_demand": np.zeros(steps),
        "solar_generation": np.zeros(steps),
    }
    pd.DataFrame(base_building).to_csv(dataset_dir / "Building_A.csv", index=False)
    pd.DataFrame(base_building).to_csv(dataset_dir / "Building_B.csv", index=False)

    observations = {
        "month": {"active": True, "shared_in_central_agent": True},
        "hour": {"active": True, "shared_in_central_agent": True},
        "minutes": {"active": True, "shared_in_central_agent": True},
        "day_type": {"active": True, "shared_in_central_agent": True},
        "outdoor_dry_bulb_temperature": {"active": True, "shared_in_central_agent": True},
        "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
        "solar_generation": {"active": True, "shared_in_central_agent": False},
        "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
        "electricity_pricing": {"active": True, "shared_in_central_agent": True},
    }
    schema = {
        "random_seed": 0,
        "root_directory": None,
        "central_agent": True,
        "simulation_start_time_step": 0,
        "simulation_end_time_step": steps - 1,
        "episode_time_steps": steps,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "seconds_per_time_step": seconds_per_time_step,
        "observations": observations,
        "actions": {"electrical_storage": {"active": False}},
        "reward_function": {"type": "citylearn.reward_function.RewardFunction", "attributes": {}},
        "buildings": {},
    }
    if community_market:
        schema["community_market"] = {
            "enabled": True,
            "intra_community_sell_ratio": 0.8,
            # Settlement version 1 pays nothing for exports, so the price is 0 (#366).
            "grid_export_price": 0.0,
        }

    for name in ["Building_A", "Building_B"]:
        schema["buildings"][name] = {
            "include": True,
            "energy_simulation": f"{name}.csv",
            "weather": "weather.csv",
            "carbon_intensity": "carbon_intensity.csv",
            "pricing": "pricing.csv",
            "inactive_observations": [],
            "inactive_actions": [],
            "pv": {
                "type": "citylearn.energy_model.PV",
                "autosize": False,
                "attributes": {"nominal_power": 1.0, "generation_mode": "absolute"},
            },
        }

    schema_path = dataset_dir / "schema.json"
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema_path


def _series_cost(net: np.ndarray, prices: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(net, dtype="float64"), 0.0, None) * np.asarray(prices, dtype="float64")


def _series_emission(net: np.ndarray, carbon: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(net, dtype="float64"), 0.0, None) * np.asarray(carbon, dtype="float64")


def _finish_episode_state(env: CityLearnEnv, steps: int):
    env.time_step = steps
    for building in env.buildings:
        building.time_step = steps - 1


def _set_condition_series(env: CityLearnEnv, condition, building_nets: dict[str, np.ndarray]):
    first = env.buildings[0]
    prices = np.asarray(first.pricing.electricity_pricing[: len(next(iter(building_nets.values())))], dtype="float64")
    carbon = np.asarray(first.carbon_intensity.carbon_intensity[: len(prices)], dtype="float64")
    env_net = np.zeros(len(prices), dtype="float64")
    env_cost = np.zeros(len(prices), dtype="float64")

    for building in env.buildings:
        net = np.asarray(building_nets[building.name], dtype="float64")
        cost = _series_cost(net, prices)
        setattr(building, f"net_electricity_consumption{condition.value}", net)
        setattr(building, f"net_electricity_consumption_cost{condition.value}", cost)
        setattr(building, f"net_electricity_consumption_emission{condition.value}", _series_emission(net, carbon))
        env_net += net
        env_cost += cost

    setattr(env, f"net_electricity_consumption{condition.value}", env_net)
    setattr(env, f"net_electricity_consumption_cost{condition.value}", env_cost)
    setattr(env, f"net_electricity_consumption_emission{condition.value}", _series_emission(env_net, carbon))


def _set_solar_generation(building, values: np.ndarray):
    building._Building__solar_generation = -np.asarray(values, dtype="float32")


def _set_actual_net_consumption(building, values: np.ndarray):
    building._Building__net_electricity_consumption = np.asarray(values, dtype="float32")


def _set_battery_consumption(building, values: np.ndarray, *, capacity: float, degraded_capacity: float):
    storage = building.electrical_storage
    storage.capacity = capacity
    storage._capacity_history = [float(capacity), float(degraded_capacity)]
    ratio = 1.0 if storage.time_step_ratio in (None, 0) else float(storage.time_step_ratio)
    storage._ElectricDevice__electricity_consumption = np.asarray(values, dtype="float32") / ratio


def _set_fake_ev_charger(building, values: np.ndarray):
    ev = SimpleNamespace(battery=SimpleNamespace(soc=[0.50, 0.75, 0.75, 0.75]))
    charger = SimpleNamespace(
        charger_id="golden_charger",
        electricity_consumption=np.asarray(values, dtype="float64"),
        charger_simulation=SimpleNamespace(
            electric_vehicle_charger_state=np.array([1.0, 1.0, 0.0, 0.0], dtype="float64"),
            electric_vehicle_required_soc_departure=np.array([0.8, 0.8, 0.0, 0.0], dtype="float64"),
        ),
        past_connected_evs=[ev, ev, None, None],
    )
    building.electric_vehicle_chargers = [charger]


def _value(df: pd.DataFrame, name: str, cost_function: str):
    rows = df[(df["name"] == name) & (df["cost_function"] == cost_function)]
    assert len(rows) == 1, f"Missing or duplicated KPI: {name} / {cost_function}"
    return rows["value"].iloc[0]


def _assert_value(df: pd.DataFrame, name: str, cost_function: str, expected: float):
    assert float(_value(df, name, cost_function)) == pytest.approx(expected, abs=1e-7)


def test_district_pv_self_consumption_uses_net_district_export():
    service = CityLearnKPIService(SimpleNamespace())
    importer = SimpleNamespace(
        name="Importer",
        time_step=0,
        solar_generation=np.array([0.0], dtype="float64"),
        net_electricity_consumption=np.array([1.0], dtype="float64"),
    )
    exporter = SimpleNamespace(
        name="Exporter",
        time_step=0,
        solar_generation=np.array([-1.0], dtype="float64"),
        net_electricity_consumption=np.array([-1.0], dtype="float64"),
    )

    building_metrics = service._compute_pv_metrics(exporter)
    district_metrics = service._compute_district_pv_metrics(
        [importer, exporter],
        {"Importer": (0, 0), "Exporter": (0, 0)},
        final_t=0,
    )

    assert building_metrics["pv_export_total_kwh"] == pytest.approx(1.0)
    assert building_metrics["pv_self_consumption_ratio"] == pytest.approx(0.0)
    assert district_metrics["pv_generation_total_kwh"] == pytest.approx(1.0)
    assert district_metrics["pv_export_total_kwh"] == pytest.approx(0.0)
    assert district_metrics["pv_self_consumption_ratio"] == pytest.approx(1.0)


def test_domain_metric_totals_ignore_non_finite_samples():
    service = CityLearnKPIService(SimpleNamespace())
    charger = SimpleNamespace(
        electricity_consumption=np.array([1.0, np.nan, -0.5], dtype="float64"),
        charger_simulation=SimpleNamespace(
            electric_vehicle_charger_state=np.zeros(4, dtype="float64"),
            electric_vehicle_required_soc_departure=np.zeros(3, dtype="float64"),
        ),
        past_connected_evs=[None, None, None],
    )
    ev_building = SimpleNamespace(time_step=2, electric_vehicle_chargers=[charger])
    ev_metrics = service._compute_ev_metrics(ev_building)

    storage = SimpleNamespace(capacity=10.0, degraded_capacity=9.0)
    bess_building = SimpleNamespace(
        time_step=2,
        electrical_storage=storage,
        electrical_storage_electricity_consumption=np.array([1.0, np.nan, -0.25], dtype="float64"),
    )
    bess_metrics = service._compute_bess_metrics(bess_building)

    pv_building = SimpleNamespace(
        time_step=2,
        solar_generation=np.array([-1.0, np.nan, -2.0], dtype="float64"),
        net_electricity_consumption=np.array([-0.5, np.nan, -1.0], dtype="float64"),
    )
    pv_metrics = service._compute_pv_metrics(pv_building)

    assert ev_metrics["ev_charge_total_kwh"] == pytest.approx(1.0)
    assert ev_metrics["ev_v2g_export_total_kwh"] == pytest.approx(0.5)
    assert bess_metrics["bess_charge_total_kwh"] == pytest.approx(1.0)
    assert bess_metrics["bess_discharge_total_kwh"] == pytest.approx(0.25)
    assert bess_metrics["bess_throughput_total_kwh"] == pytest.approx(1.25)
    assert pv_metrics["pv_generation_total_kwh"] == pytest.approx(3.0)
    assert pv_metrics["pv_export_total_kwh"] == pytest.approx(1.5)


@pytest.mark.parametrize("seconds_per_time_step", [15, 60, 300, 900, 3600])
def test_kpi_v2_golden_grid_pv_bess_ev_and_shape_metrics(tmp_path: Path, seconds_per_time_step: int):
    steps = 3
    dt = seconds_per_time_step / 3600.0
    schema_path = _write_golden_schema(tmp_path, seconds_per_time_step=seconds_per_time_step, steps=steps)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=steps, random_seed=0)
    control = SimpleNamespace(value="_golden_control")
    baseline = SimpleNamespace(value="_golden_baseline")

    try:
        env.reset()
        _finish_episode_state(env, steps)

        control_a = np.array([2.0, 0.0, 4.0], dtype="float64") * dt
        control_b = np.array([-1.0, 3.0, -2.0], dtype="float64") * dt
        baseline_a = np.array([1.0, 2.0, 4.0], dtype="float64") * dt
        baseline_b = np.zeros(steps, dtype="float64")

        _set_condition_series(env, control, {"Building_A": control_a, "Building_B": control_b})
        _set_condition_series(env, baseline, {"Building_A": baseline_a, "Building_B": baseline_b})
        _set_actual_net_consumption(env.buildings[0], control_a)
        _set_actual_net_consumption(env.buildings[1], control_b)
        _set_solar_generation(env.buildings[0], np.zeros(steps, dtype="float64"))
        _set_solar_generation(env.buildings[1], np.array([1.0, 0.0, 2.0], dtype="float64") * dt)
        _set_battery_consumption(
            env.buildings[0],
            np.array([1.0, -0.5, 0.25], dtype="float64") * dt,
            capacity=10.0,
            degraded_capacity=9.5,
        )
        _set_fake_ev_charger(env.buildings[1], np.array([0.7, -0.2, 0.3], dtype="float64") * dt)

        df = env.evaluate_v2(control_condition=control, baseline_condition=baseline)

        _assert_value(df, "Building_A", "building_energy_grid_total_import_control_kwh", 6.0 * dt)
        _assert_value(df, "Building_B", "building_energy_grid_total_import_control_kwh", 3.0 * dt)
        _assert_value(df, "Building_B", "building_energy_grid_total_export_control_kwh", 3.0 * dt)
        _assert_value(df, "District", "district_energy_grid_total_import_control_kwh", 6.0 * dt)
        _assert_value(df, "District", "district_energy_grid_total_export_control_kwh", 0.0)
        _assert_value(df, "District", "district_energy_grid_total_net_exchange_control_kwh", 6.0 * dt)

        _assert_value(df, "Building_A", "building_cost_total_control_eur", 1.4 * dt)
        _assert_value(df, "Building_B", "building_cost_total_control_eur", 0.6 * dt)
        _assert_value(df, "District", "district_cost_total_control_eur", 2.0 * dt)
        _assert_value(df, "Building_A", "building_emissions_total_control_kgco2", 2.2 * dt)
        _assert_value(df, "Building_B", "building_emissions_total_control_kgco2", 1.2 * dt)
        _assert_value(df, "District", "district_emissions_total_control_kgco2", 2.3 * dt)

        _assert_value(df, "Building_B", "building_solar_self_consumption_total_generation_kwh", 3.0 * dt)
        _assert_value(df, "Building_B", "building_solar_self_consumption_total_export_kwh", 3.0 * dt)
        _assert_value(df, "Building_B", "building_solar_self_consumption_ratio_self_consumption_ratio", 0.0)
        _assert_value(df, "District", "district_solar_self_consumption_total_generation_kwh", 3.0 * dt)
        _assert_value(df, "District", "district_solar_self_consumption_total_export_kwh", 0.0)
        _assert_value(df, "District", "district_solar_self_consumption_ratio_self_consumption_ratio", 1.0)

        _assert_value(df, "Building_A", "building_battery_total_charge_kwh", 1.25 * dt)
        _assert_value(df, "Building_A", "building_battery_total_discharge_kwh", 0.5 * dt)
        _assert_value(df, "Building_A", "building_battery_total_throughput_kwh", 1.75 * dt)
        _assert_value(df, "Building_A", "building_battery_health_equivalent_full_cycles_count", (1.75 * dt) / 20.0)
        _assert_value(df, "Building_A", "building_battery_health_capacity_fade_ratio", 0.05)
        _assert_value(df, "District", "district_battery_total_throughput_kwh", 1.75 * dt)

        _assert_value(df, "Building_B", "building_ev_total_charge_kwh", 1.0 * dt)
        _assert_value(df, "Building_B", "building_ev_total_v2g_export_kwh", 0.2 * dt)
        _assert_value(df, "Building_B", "building_ev_events_departure_count", 1.0)
        _assert_value(df, "Building_B", "building_ev_events_departure_within_tolerance_count", 1.0)
        _assert_value(df, "Building_B", "building_ev_events_departure_met_count", 0.0)
        _assert_value(df, "Building_B", "building_ev_performance_departure_success_ratio", 0.0)
        _assert_value(df, "Building_B", "building_ev_performance_departure_soc_deficit_mean_ratio", 0.05)
        _assert_value(df, "District", "district_ev_total_charge_kwh", 1.0 * dt)
        _assert_value(df, "District", "district_ev_total_v2g_export_kwh", 0.2 * dt)

        _assert_value(df, "District", "district_energy_grid_shape_quality_ramping_average_to_baseline_ratio", 2.0 / 3.0)
        _assert_value(df, "District", "district_energy_grid_shape_quality_peak_daily_average_to_baseline_ratio", 3.0 / 4.0)
        _assert_value(df, "District", "district_energy_grid_shape_quality_peak_all_time_average_to_baseline_ratio", 3.0 / 4.0)
    finally:
        env.close()


@pytest.mark.parametrize("seconds_per_time_step", [15, 60, 300, 900, 3600])
def test_kpi_v2_golden_community_market_uses_bounded_local_demand_share(
    tmp_path: Path,
    seconds_per_time_step: int,
):
    steps = 2
    dt = seconds_per_time_step / 3600.0
    schema_path = _write_golden_schema(
        tmp_path,
        seconds_per_time_step=seconds_per_time_step,
        steps=steps,
        community_market=True,
    )
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=steps, random_seed=0)
    control = SimpleNamespace(value="_golden_control")
    baseline = SimpleNamespace(value="_golden_baseline")

    try:
        env.reset()
        _finish_episode_state(env, steps)

        building_a = np.array([2.0, 0.5], dtype="float64") * dt
        building_b = np.array([-1.0, -2.0], dtype="float64") * dt
        _set_condition_series(env, control, {"Building_A": building_a, "Building_B": building_b})
        _set_condition_series(env, baseline, {"Building_A": building_a, "Building_B": building_b})
        _set_actual_net_consumption(env.buildings[0], building_a)
        _set_actual_net_consumption(env.buildings[1], building_b)
        _set_solar_generation(env.buildings[0], np.zeros(steps, dtype="float64"))
        _set_solar_generation(env.buildings[1], np.array([1.0, 2.0], dtype="float64") * dt)

        env._community_market_settlement_history = [
            [
                {
                    "building": "Building_A",
                    "local_import_kwh": 1.0 * dt,
                    "local_export_kwh": 0.0,
                    "grid_import_kwh": 1.0 * dt,
                    "grid_export_kwh": 0.0,
                    "settled_cost_eur": 0.18 * dt,
                    "counterfactual_cost_eur": 0.2 * dt,
                    "market_savings_eur": 0.02 * dt,
                },
                {
                    "building": "Building_B",
                    "local_import_kwh": 0.0,
                    "local_export_kwh": 1.0 * dt,
                    "grid_import_kwh": 0.0,
                    "grid_export_kwh": 0.0,
                    "settled_cost_eur": -0.08 * dt,
                    "counterfactual_cost_eur": 0.0,
                    "market_savings_eur": 0.08 * dt,
                },
            ],
            [
                {
                    "building": "Building_A",
                    "local_import_kwh": 0.5 * dt,
                    "local_export_kwh": 0.0,
                    "grid_import_kwh": 0.0,
                    "grid_export_kwh": 0.0,
                    "settled_cost_eur": 0.08 * dt,
                    "counterfactual_cost_eur": 0.1 * dt,
                    "market_savings_eur": 0.02 * dt,
                },
                {
                    "building": "Building_B",
                    "local_import_kwh": 0.0,
                    "local_export_kwh": 0.5 * dt,
                    "grid_import_kwh": 0.0,
                    "grid_export_kwh": 1.5 * dt,
                    "settled_cost_eur": -0.08 * dt,
                    "counterfactual_cost_eur": 0.0,
                    "market_savings_eur": 0.08 * dt,
                },
            ],
        ]

        df = env.evaluate_v2(control_condition=control, baseline_condition=baseline)

        local_traded = 1.5 * dt
        grid_import_after_local = 1.0 * dt
        expected_share = local_traded / (local_traded + grid_import_after_local)
        simulated_days = steps * seconds_per_time_step / (24.0 * 3600.0)

        _assert_value(df, "District", "district_energy_grid_community_market_local_traded_total_kwh", local_traded)
        _assert_value(
            df,
            "District",
            "district_energy_grid_community_market_local_traded_daily_average_kwh",
            local_traded / simulated_days,
        )
        _assert_value(df, "District", "district_solar_self_consumption_community_market_import_share_ratio", expected_share)
        assert 0.0 <= float(_value(df, "District", "district_solar_self_consumption_community_market_import_share_ratio")) <= 1.0

        _assert_value(df, "Building_A", "building_cost_total_control_eur", 0.26 * dt)
        _assert_value(df, "Building_B", "building_cost_total_control_eur", -0.16 * dt)
        _assert_value(df, "District", "district_cost_total_control_eur", 0.10 * dt)
        _assert_value(df, "District", "district_cost_total_delta_eur", 0.0)
        _assert_value(df, "Building_A", "building_energy_grid_community_market_local_import_total_kwh", 1.5 * dt)
        _assert_value(df, "Building_A", "building_cost_community_market_settled_total_eur", 0.26 * dt)
        _assert_value(df, "Building_A", "building_cost_community_market_counterfactual_total_eur", 0.3 * dt)
        _assert_value(df, "Building_A", "building_cost_community_market_savings_total_eur", 0.04 * dt)
        _assert_value(df, "Building_B", "building_cost_community_market_savings_total_eur", 0.16 * dt)
        _assert_value(df, "District", "district_energy_grid_community_market_grid_export_after_local_total_kwh", 1.5 * dt)
        _assert_value(df, "District", "district_cost_community_market_settled_total_eur", 0.10 * dt)
        _assert_value(df, "District", "district_cost_community_market_counterfactual_total_eur", 0.3 * dt)
        _assert_value(df, "District", "district_cost_community_market_savings_total_eur", 0.2 * dt)
    finally:
        env.close()
