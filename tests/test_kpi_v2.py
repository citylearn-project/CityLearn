import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv, EvaluationCondition
from citylearn.cost_function import CostFunction
from citylearn.internal.kpi import CityLearnKPIService


SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
THREE_PHASE_SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_three_phase_electrical_service_demo/schema.json"
MINUTE_DATASET_DIR = Path(__file__).resolve().parents[1] / "tests" / "data" / "minute_ev_demo"
LEGACY_KPI_KEYS = {
    "all_time_peak_average",
    "annual_normalized_unserved_energy_total",
    "carbon_emissions_total",
    "cost_total",
    "daily_one_minus_load_factor_average",
    "daily_peak_average",
    "discomfort_cold_delta_average",
    "discomfort_cold_delta_maximum",
    "discomfort_cold_delta_minimum",
    "discomfort_cold_proportion",
    "discomfort_hot_delta_average",
    "discomfort_hot_delta_maximum",
    "discomfort_hot_delta_minimum",
    "discomfort_hot_proportion",
    "discomfort_proportion",
    "electricity_consumption_total",
    "monthly_one_minus_load_factor_average",
    "one_minus_thermal_resilience_proportion",
    "power_outage_normalized_unserved_energy_total",
    "ramping_average",
    "zero_net_energy",
}


def _run_episode(schema: Path, seconds_per_time_step: int, episode_steps: int = 24) -> CityLearnEnv:
    env = CityLearnEnv(
        str(schema),
        interface="flat",
        central_agent=True,
        episode_time_steps=episode_steps,
        seconds_per_time_step=seconds_per_time_step,
        random_seed=0,
    )
    env.reset()

    action_names = env.action_names[0]
    base_action = np.zeros(env.action_space[0].shape[0], dtype="float32")
    ev_indices = [i for i, name in enumerate(action_names) if name.startswith("electric_vehicle_storage_")]
    bess_indices = [i for i, name in enumerate(action_names) if name == "electrical_storage"]

    while not env.terminated:
        action = base_action.copy()
        if ev_indices:
            action[ev_indices] = 0.7
        if bess_indices:
            action[bess_indices] = 0.5
        env.step([action])

    return env


def _fake_departure_charger(actual_soc: float, target_soc: float = 0.80, *, charger_id: str = "fake_charger"):
    ev = SimpleNamespace(battery=SimpleNamespace(soc=[float(actual_soc), float(actual_soc)]))
    return SimpleNamespace(
        charger_id=charger_id,
        electricity_consumption=np.zeros(2, dtype="float64"),
        charger_simulation=SimpleNamespace(
            electric_vehicle_charger_state=np.array([1.0, 0.0], dtype="float64"),
            electric_vehicle_required_soc_departure=np.array([float(target_soc), float(target_soc)], dtype="float64"),
        ),
        past_connected_evs=[ev, None],
    )


def _fake_feasibility_departure_charger(
    actual_soc: float,
    target_soc: float = 0.80,
    *,
    arrival_soc: float = 0.20,
    capacity_kwh: float = 10.0,
    max_charging_power_kw: float = 10.0,
    charger_id: str = "fake_feasibility_charger",
):
    ev = SimpleNamespace(
        battery=SimpleNamespace(
            soc=[float(actual_soc), float(actual_soc)],
            initial_soc=float(arrival_soc),
            capacity=float(capacity_kwh),
            nominal_power=float(max_charging_power_kw),
            seconds_per_time_step=3600,
            capacity_power_curve=np.array([[0.0, 1.0], [1.0, 1.0]], dtype="float64"),
            power_efficiency_curve=np.array([[0.0, 1.0], [1.0, 1.0]], dtype="float64"),
        )
    )
    return SimpleNamespace(
        charger_id=charger_id,
        max_charging_power=float(max_charging_power_kw),
        efficiency=1.0,
        seconds_per_time_step=3600,
        electricity_consumption=np.zeros(2, dtype="float64"),
        charger_simulation=SimpleNamespace(
            electric_vehicle_charger_state=np.array([1.0, 0.0], dtype="float64"),
            electric_vehicle_id=np.array(["EV_1", "EV_1"]),
            electric_vehicle_required_soc_departure=np.array([float(target_soc), float(target_soc)], dtype="float64"),
            electric_vehicle_estimated_soc_arrival=np.array([float(arrival_soc), -0.1], dtype="float64"),
        ),
        past_connected_evs=[ev, None],
    )


def test_ev_energy_accounting_detects_soc_gain_without_charger_energy():
    charger = _fake_feasibility_departure_charger(
        actual_soc=0.80,
        arrival_soc=0.20,
        capacity_kwh=10.0,
    )
    building = SimpleNamespace(
        name="Building_1",
        time_step=1,
        electric_vehicle_chargers=[charger],
    )
    service = CityLearnKPIService(SimpleNamespace(topology_mode="static"))

    metrics = service._compute_ev_metrics(building)

    assert metrics["ev_connected_soc_gain_total_kwh"] == pytest.approx(6.0)
    assert metrics["ev_charge_total_kwh"] == pytest.approx(0.0)
    assert metrics["ev_energy_accounting_shortfall_kwh"] == pytest.approx(6.0)


def test_ev_energy_accounting_accepts_charger_energy_above_soc_gain():
    charger = _fake_feasibility_departure_charger(
        actual_soc=0.80,
        arrival_soc=0.20,
        capacity_kwh=10.0,
    )
    charger.electricity_consumption = np.array([6.5, 0.0], dtype="float64")
    building = SimpleNamespace(
        name="Building_1",
        time_step=1,
        electric_vehicle_chargers=[charger],
    )
    service = CityLearnKPIService(SimpleNamespace(topology_mode="static"))

    metrics = service._compute_ev_metrics(building)

    assert metrics["ev_connected_soc_gain_total_kwh"] == pytest.approx(6.0)
    assert metrics["ev_charge_total_kwh"] == pytest.approx(6.5)
    assert metrics["ev_energy_accounting_shortfall_kwh"] == pytest.approx(0.0)


def test_ev_departure_at_terminal_episode_boundary_is_counted():
    charger = _fake_feasibility_departure_charger(
        actual_soc=0.80,
        arrival_soc=0.20,
        capacity_kwh=10.0,
    )
    charger.electricity_consumption = np.array([6.5], dtype="float64")
    charger.charger_simulation.electric_vehicle_charger_state = np.array(
        [1.0], dtype="float64"
    )
    charger.charger_simulation.electric_vehicle_id = np.array(["EV_1"])
    charger.charger_simulation.electric_vehicle_required_soc_departure = np.array(
        [0.80], dtype="float64"
    )
    charger.charger_simulation.electric_vehicle_estimated_soc_arrival = np.array(
        [0.20], dtype="float64"
    )
    charger.charger_simulation.electric_vehicle_departure_time = np.array(
        [1.0], dtype="float64"
    )
    charger.past_connected_evs = [charger.past_connected_evs[0]]
    charger.past_connected_evs[0].battery.soc = [0.80]
    building = SimpleNamespace(
        name="Building_1",
        time_step=0,
        electric_vehicle_chargers=[charger],
    )
    service = CityLearnKPIService(SimpleNamespace(topology_mode="static"))

    metrics = service._compute_ev_metrics(building)

    assert metrics["departures_total"] == 1.0
    assert metrics["departures_met"] == 1.0
    assert metrics["ev_connected_soc_gain_total_kwh"] == pytest.approx(6.0)
    assert metrics["ev_charge_total_kwh"] == pytest.approx(6.5)
    assert metrics["ev_energy_accounting_shortfall_kwh"] == pytest.approx(0.0)


@pytest.mark.parametrize('countdown', [2.0, -1.0, np.nan])
def test_connected_ev_without_terminal_departure_is_not_counted(countdown):
    charger = _fake_feasibility_departure_charger(actual_soc=0.80)
    charger.charger_simulation.electric_vehicle_charger_state = np.array(
        [1.0], dtype="float64"
    )
    charger.charger_simulation.electric_vehicle_id = np.array(["EV_1"])
    charger.charger_simulation.electric_vehicle_required_soc_departure = np.array(
        [0.80], dtype="float64"
    )
    charger.charger_simulation.electric_vehicle_estimated_soc_arrival = np.array(
        [0.20], dtype="float64"
    )
    charger.charger_simulation.electric_vehicle_departure_time = np.array(
        [countdown], dtype="float64"
    )
    charger.past_connected_evs = [charger.past_connected_evs[0]]
    charger.past_connected_evs[0].battery.soc = [0.80]
    building = SimpleNamespace(
        name="Building_1",
        time_step=0,
        electric_vehicle_chargers=[charger],
    )
    service = CityLearnKPIService(SimpleNamespace(topology_mode="static"))

    metrics = service._compute_ev_metrics(building)

    assert metrics["departures_total"] == 0.0


@pytest.mark.parametrize("explicit_session_identity", [False, True])
def test_back_to_back_session_change_of_same_ev_counts_both_departures(
    explicit_session_identity: bool,
):
    ev = SimpleNamespace(battery=SimpleNamespace(soc=[0.80, 0.80, 0.80]))
    simulation = SimpleNamespace(
        electric_vehicle_charger_state=np.array([1.0, 1.0, 0.0]),
        electric_vehicle_id=np.array(["EV_1", "EV_1", "EV_1"], dtype=object),
        electric_vehicle_departure_time=np.array([1.0, 4.0, -1.0]),
        electric_vehicle_required_soc_departure=np.array([0.80, 0.80, 0.80]),
    )
    if explicit_session_identity:
        simulation.electric_vehicle_session_id = np.array(
            ["SESSION_1", "SESSION_2", "SESSION_2"], dtype=object
        )
    charger = SimpleNamespace(
        charger_id="shared_charger",
        electricity_consumption=np.zeros(3, dtype="float64"),
        charger_simulation=simulation,
        past_connected_evs=[ev, ev, None],
    )
    building = SimpleNamespace(
        name="Building_1",
        time_step=2,
        electric_vehicle_chargers=[charger],
    )
    service = CityLearnKPIService(SimpleNamespace(topology_mode="static"))

    metrics = service._compute_ev_metrics(building)

    assert metrics["departures_total"] == 2.0
    assert metrics["departures_met"] == 2.0


def _fake_ev_building(actual_socs: list[float], *, name: str = "Building_1"):
    return SimpleNamespace(
        name=name,
        time_step=1,
        electric_vehicle_chargers=[
            _fake_departure_charger(actual_soc, charger_id=f"{name}_charger_{index}")
            for index, actual_soc in enumerate(actual_socs)
        ],
    )


def _step_once(env: CityLearnEnv):
    env.reset()
    env.step([np.zeros(len(env.action_names[0]), dtype="float32")])


def _kpi_value(df: pd.DataFrame, name: str, cost_function: str):
    rows = df[(df["name"] == name) & (df["cost_function"] == cost_function)]
    assert len(rows) == 1, f"Missing or duplicated KPI: {name} / {cost_function}"
    return rows["value"].iloc[0]


def test_normalized_unserved_energy_clips_surplus_and_zero_denominator():
    assert CostFunction.normalized_unserved_energy([0.0, 0.0], [1.0, 0.0]) == [0.0, 0.0]

    values = CostFunction.normalized_unserved_energy([1.0, 1.0], [2.0, 0.5])
    assert values == pytest.approx([0.0, 0.25])


def test_normalized_unserved_energy_masks_non_outage_steps():
    values = CostFunction.normalized_unserved_energy(
        [1.0, 1.0],
        [0.0, 0.0],
        power_outage=[0, 1],
    )

    assert values == pytest.approx([0.0, 1.0])


def _build_two_building_market_schema(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "market_dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    weather = pd.read_csv(MINUTE_DATASET_DIR / "weather.csv").iloc[:2].copy()
    weather.to_csv(dataset_dir / "weather.csv", index=False)

    carbon = pd.read_csv(MINUTE_DATASET_DIR / "carbon_intensity.csv").iloc[:2].copy()
    carbon.to_csv(dataset_dir / "carbon_intensity.csv", index=False)

    pricing = pd.DataFrame(
        {
            "electricity_pricing": [0.5, 0.5],
            "electricity_pricing_predicted_1": [0.5, 0.5],
            "electricity_pricing_predicted_2": [0.5, 0.5],
            "electricity_pricing_predicted_3": [0.5, 0.5],
        }
    )
    pricing.to_csv(dataset_dir / "pricing.csv", index=False)

    building_a = pd.DataFrame(
        {
            "month": [1, 1],
            "hour": [0, 1],
            "minutes": [0, 0],
            "day_type": [1, 1],
            "daylight_savings_status": [0, 0],
            "indoor_dry_bulb_temperature": [21.0, 21.0],
            "average_unmet_cooling_setpoint_difference": [0.0, 0.0],
            "indoor_relative_humidity": [45.0, 45.0],
            "non_shiftable_load": [2.0, 2.0],
            "dhw_demand": [0.0, 0.0],
            "cooling_demand": [0.0, 0.0],
            "heating_demand": [0.0, 0.0],
            "solar_generation": [0.0, 0.0],
        }
    )
    building_b = building_a.copy()
    building_b["non_shiftable_load"] = [0.0, 0.0]
    building_b["solar_generation"] = [2000.0, 2000.0]

    building_a.to_csv(dataset_dir / "Building_A.csv", index=False)
    building_b.to_csv(dataset_dir / "Building_B.csv", index=False)

    schema = {
        "random_seed": 0,
        "root_directory": None,
        "central_agent": True,
        "simulation_start_time_step": 0,
        "simulation_end_time_step": 1,
        "episode_time_steps": 2,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "seconds_per_time_step": 3600,
        "observations": {
            "month": {"active": True, "shared_in_central_agent": True},
            "hour": {"active": True, "shared_in_central_agent": True},
            "minutes": {"active": True, "shared_in_central_agent": True},
            "day_type": {"active": True, "shared_in_central_agent": True},
            "outdoor_dry_bulb_temperature": {"active": True, "shared_in_central_agent": True},
            "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
            "solar_generation": {"active": True, "shared_in_central_agent": False},
            "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
            "electricity_pricing": {"active": True, "shared_in_central_agent": True},
        },
        "actions": {
            "electrical_storage": {"active": False},
        },
        "reward_function": {
            "type": "citylearn.reward_function.RewardFunction",
            "attributes": {},
        },
        "community_market": {
            "enabled": True,
            "intra_community_sell_ratio": 0.8,
            "grid_export_price": 0.0,
        },
        "buildings": {
            "Building_A": {
                "include": True,
                "energy_simulation": "Building_A.csv",
                "weather": "weather.csv",
                "carbon_intensity": "carbon_intensity.csv",
                "pricing": "pricing.csv",
                "inactive_observations": [],
                "inactive_actions": [],
                "pv": {
                    "type": "citylearn.energy_model.PV",
                    "autosize": False,
                    "attributes": {"nominal_power": 0.0},
                },
            },
            "Building_B": {
                "include": True,
                "energy_simulation": "Building_B.csv",
                "weather": "weather.csv",
                "carbon_intensity": "carbon_intensity.csv",
                "pricing": "pricing.csv",
                "inactive_observations": [],
                "inactive_actions": [],
                "pv": {
                    "type": "citylearn.energy_model.PV",
                    "autosize": False,
                    "attributes": {"nominal_power": 1.0},
                },
            },
        },
    }

    schema_path = dataset_dir / "schema.json"
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    return schema_path


def _build_schema_with_manual_equity_groups(
    tmp_path: Path,
    source_schema: Path,
    *,
    missing_first_group: bool,
) -> Path:
    with open(source_schema, "r", encoding="utf-8") as f:
        schema = json.load(f)
    schema["root_directory"] = str(source_schema.parent)

    building_names = [name for name, config in schema.get("buildings", {}).items() if config.get("include", False)]

    for i, name in enumerate(building_names):
        if missing_first_group and i == 0:
            schema["buildings"][name].pop("equity_group", None)
            continue

        schema["buildings"][name]["equity_group"] = "asset_rich" if i % 2 == 0 else "asset_poor"

    schema_path = tmp_path / "schema_with_equity_groups.json"

    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    return schema_path


def _build_zero_sum_pricing_schema(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "zero_sum_pricing_dataset"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    weather = pd.read_csv(MINUTE_DATASET_DIR / "weather.csv").iloc[:3].copy()
    weather.to_csv(dataset_dir / "weather.csv", index=False)

    carbon = pd.read_csv(MINUTE_DATASET_DIR / "carbon_intensity.csv").iloc[:3].copy()
    carbon.to_csv(dataset_dir / "carbon_intensity.csv", index=False)

    pricing = pd.DataFrame(
        {
            "electricity_pricing": [1.0, -1.0, 0.0],
            "electricity_pricing_predicted_1": [1.0, -1.0, 0.0],
            "electricity_pricing_predicted_2": [1.0, -1.0, 0.0],
            "electricity_pricing_predicted_3": [1.0, -1.0, 0.0],
        }
    )
    pricing.to_csv(dataset_dir / "pricing.csv", index=False)

    building = pd.DataFrame(
        {
            "month": [1, 1, 1],
            "hour": [0, 1, 2],
            "minutes": [0, 0, 0],
            "day_type": [1, 1, 1],
            "daylight_savings_status": [0, 0, 0],
            "indoor_dry_bulb_temperature": [21.0, 21.0, 21.0],
            "average_unmet_cooling_setpoint_difference": [0.0, 0.0, 0.0],
            "indoor_relative_humidity": [45.0, 45.0, 45.0],
            "non_shiftable_load": [1.0, 2.0, 3.0],
            "dhw_demand": [0.0, 0.0, 0.0],
            "cooling_demand": [0.0, 0.0, 0.0],
            "heating_demand": [0.0, 0.0, 0.0],
            "solar_generation": [0.0, 0.0, 0.0],
        }
    )
    building.to_csv(dataset_dir / "Building_1.csv", index=False)

    schema = {
        "random_seed": 0,
        "root_directory": None,
        "central_agent": True,
        "simulation_start_time_step": 0,
        "simulation_end_time_step": 2,
        "episode_time_steps": 3,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "seconds_per_time_step": 3600,
        "observations": {
            "month": {"active": True, "shared_in_central_agent": True},
            "hour": {"active": True, "shared_in_central_agent": True},
            "minutes": {"active": True, "shared_in_central_agent": True},
            "day_type": {"active": True, "shared_in_central_agent": True},
            "outdoor_dry_bulb_temperature": {"active": True, "shared_in_central_agent": True},
            "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
            "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
            "electricity_pricing": {"active": True, "shared_in_central_agent": True},
        },
        "actions": {"electrical_storage": {"active": False}},
        "reward_function": {"type": "citylearn.reward_function.RewardFunction", "attributes": {}},
        "buildings": {
            "Building_1": {
                "include": True,
                "energy_simulation": "Building_1.csv",
                "weather": "weather.csv",
                "carbon_intensity": "carbon_intensity.csv",
                "pricing": "pricing.csv",
                "inactive_observations": [],
                "inactive_actions": [],
                "pv": {
                    "type": "citylearn.energy_model.PV",
                    "autosize": False,
                    "attributes": {"nominal_power": 0.0},
                },
            }
        },
    }

    schema_path = dataset_dir / "schema.json"
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    return schema_path


@pytest.mark.parametrize("seconds_per_time_step", [5, 10, 60, 300, 900])
def test_daily_and_monthly_kpis_use_time_aware_windows(seconds_per_time_step: int):
    env = _run_episode(SCHEMA, seconds_per_time_step=seconds_per_time_step, episode_steps=24)

    try:
        control = EvaluationCondition.WITH_STORAGE_AND_PV
        baseline = EvaluationCondition.WITHOUT_STORAGE_BUT_WITH_PV
        df = env.evaluate_v2(control_condition=control, baseline_condition=baseline)

        daily_steps = max(1, int(round((24 * 3600) / seconds_per_time_step)))
        monthly_steps = max(1, int(round((730 * 3600) / seconds_per_time_step)))

        dlf_daily_c = CostFunction.one_minus_load_factor(env.net_electricity_consumption, window=daily_steps)[-1]
        dlf_daily_b = CostFunction.one_minus_load_factor(
            getattr(env, f"net_electricity_consumption{baseline.value}"),
            window=daily_steps,
        )[-1]
        dlf_monthly_c = CostFunction.one_minus_load_factor(env.net_electricity_consumption, window=monthly_steps)[-1]
        dlf_monthly_b = CostFunction.one_minus_load_factor(
            getattr(env, f"net_electricity_consumption{baseline.value}"),
            window=monthly_steps,
        )[-1]
        peak_daily_c = CostFunction.peak(env.net_electricity_consumption, window=daily_steps)[-1]
        peak_daily_b = CostFunction.peak(
            getattr(env, f"net_electricity_consumption{baseline.value}"),
            window=daily_steps,
        )[-1]

        def safe_div(c, b):
            if b == 0.0:
                return 1.0 if c == 0.0 else np.nan
            return c / b

        expected_daily = safe_div(float(dlf_daily_c), float(dlf_daily_b))
        expected_monthly = safe_div(float(dlf_monthly_c), float(dlf_monthly_b))
        expected_peak_daily = safe_div(float(peak_daily_c), float(peak_daily_b))

        district = df[df["name"] == "District"].set_index("cost_function")["value"]
        assert float(district["district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_baseline_ratio"]) == pytest.approx(expected_daily)
        assert float(district["district_energy_grid_shape_quality_load_factor_penalty_monthly_average_to_baseline_ratio"]) == pytest.approx(expected_monthly)
        assert float(district["district_energy_grid_shape_quality_peak_daily_average_to_baseline_ratio"]) == pytest.approx(expected_peak_daily)
    finally:
        env.close()


def test_cost_baseline_total_eur_not_forced_to_zero_when_price_sum_is_zero(tmp_path: Path):
    schema_path = _build_zero_sum_pricing_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=3, random_seed=0)

    try:
        env.reset()
        zeros = np.zeros(len(env.action_names[0]), dtype="float32")
        while not env.terminated:
            env.step([zeros])

        baseline_condition = EvaluationCondition.WITHOUT_STORAGE_BUT_WITH_PV
        baseline_series = getattr(
            env.buildings[0],
            f"net_electricity_consumption_cost{baseline_condition.value}",
        )
        baseline_array = np.asarray(baseline_series, dtype="float64")
        expected_baseline_total = float(baseline_array[np.isfinite(baseline_array)].sum())

        df = env.evaluate_v2(
            control_condition=EvaluationCondition.WITH_STORAGE_AND_PV,
            baseline_condition=baseline_condition,
        )
        building_value = float(
            df[(df["name"] == "Building_1") & (df["cost_function"] == "building_cost_total_baseline_eur")]["value"].iloc[0]
        )
        district_value = float(
            df[(df["name"] == "District") & (df["cost_function"] == "district_cost_total_baseline_eur")]["value"].iloc[0]
        )

        assert expected_baseline_total != 0.0
        assert building_value == pytest.approx(expected_baseline_total, abs=1e-9)
        assert district_value == pytest.approx(expected_baseline_total, abs=1e-9)
    finally:
        env.close()


def test_kpi_v2_adds_domain_and_market_metrics(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        env.reset()
        env.step([np.zeros(len(env.action_names[0]), dtype="float32")])
        df = env.evaluate_v2()

        expected = {
            "building_energy_grid_total_import_control_kwh",
            "building_cost_total_control_eur",
            "building_cost_daily_average_control_eur",
            "building_ev_events_departure_within_tolerance_count",
            "building_ev_events_departure_target_infeasible_count",
            "building_ev_performance_departure_success_ratio",
            "building_ev_performance_departure_within_tolerance_ratio",
            "building_ev_performance_departure_success_feasible_ratio",
            "building_battery_total_throughput_kwh",
            "building_solar_self_consumption_total_generation_kwh",
            "building_solar_self_consumption_total_generation_business_as_usual_kwh",
            "building_solar_self_consumption_daily_average_export_kwh",
            "building_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio",
            "district_energy_grid_community_market_local_traded_total_kwh",
            "district_energy_grid_community_market_local_traded_daily_average_kwh",
            "district_solar_self_consumption_community_market_import_share_ratio",
        }
        assert expected.issubset(set(df["cost_function"].unique()))

        assert _kpi_value(df, "Building_B", "building_solar_self_consumption_total_generation_kwh") == pytest.approx(2.0)
        assert _kpi_value(df, "Building_B", "building_solar_self_consumption_total_export_kwh") == pytest.approx(2.0)
        assert _kpi_value(df, "Building_B", "building_solar_self_consumption_ratio_self_consumption_ratio") == pytest.approx(0.0)
        assert _kpi_value(
            df,
            "Building_B",
            "building_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio",
        ) == pytest.approx(0.0)
        assert _kpi_value(
            df,
            "Building_B",
            "building_solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio",
        ) == pytest.approx(0.0)
        assert pd.isna(_kpi_value(df, "Building_A", "building_solar_self_consumption_ratio_self_consumption_ratio"))
    finally:
        env.close()


def test_evaluate_v2_exports_default_scorecard_kpis(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        env.reset()
        env.step([np.zeros(len(env.action_names[0]), dtype="float32")])
        df = env.evaluate_v2()

        exported = set(df["cost_function"].unique())
        missing = sorted(set(CityLearnKPIService.SCORECARD_DEFAULT_KPIS) - exported)
        assert missing == []
    finally:
        env.close()


@pytest.mark.parametrize(
    "actual_soc, strict_success, min_acceptable, symmetric_tolerance, shortfall_beyond_tolerance",
    [
        (0.74, 0.0, 0.0, 0.0, 0.01),
        (0.75, 0.0, 1.0, 1.0, 0.00),
        (0.79, 0.0, 1.0, 1.0, 0.00),
        (0.80, 1.0, 1.0, 1.0, 0.00),
        (0.85, 1.0, 1.0, 1.0, 0.00),
        (0.90, 1.0, 1.0, 0.0, 0.00),
    ],
)
def test_ev_departure_service_threshold_cases(
    actual_soc: float,
    strict_success: float,
    min_acceptable: float,
    symmetric_tolerance: float,
    shortfall_beyond_tolerance: float,
):
    service = CityLearnKPIService(
        SimpleNamespace(
            ev_departure_within_tolerance=0.05,
            ev_departure_service_tolerance=0.05,
        )
    )
    metrics = service._compute_ev_metrics(_fake_ev_building([actual_soc]))

    assert metrics["departures_total"] == 1.0
    assert metrics["departures_met"] == strict_success
    assert metrics["departures_min_acceptable"] == min_acceptable
    assert metrics["departures_within_tolerance"] == symmetric_tolerance
    assert metrics["ev_departure_shortfall_beyond_tolerance_mean"] == pytest.approx(shortfall_beyond_tolerance, abs=1e-9)
    assert metrics["ev_departure_soc_deficit_mean"] == pytest.approx(max(0.80 - actual_soc, 0.0), abs=1e-9)
    assert metrics["ev_departure_soc_surplus_mean"] == pytest.approx(max(actual_soc - 0.80, 0.0), abs=1e-9)
    assert metrics["ev_departure_soc_absolute_error_mean"] == pytest.approx(abs(actual_soc - 0.80), abs=1e-9)


def test_ev_departure_feasible_rates_exclude_physically_unreachable_targets():
    service = CityLearnKPIService(
        SimpleNamespace(
            ev_departure_within_tolerance=0.05,
            ev_departure_service_tolerance=0.05,
            seconds_per_time_step=3600,
        )
    )
    building = SimpleNamespace(
        name="Building_1",
        time_step=1,
        electric_vehicle_chargers=[
            _fake_feasibility_departure_charger(
                actual_soc=0.70,
                arrival_soc=0.20,
                capacity_kwh=10.0,
                max_charging_power_kw=10.0,
                charger_id="feasible_but_failed",
            ),
            _fake_feasibility_departure_charger(
                actual_soc=0.21,
                arrival_soc=0.20,
                capacity_kwh=100.0,
                max_charging_power_kw=1.0,
                charger_id="target_unreachable",
            ),
        ],
    )

    metrics = service._compute_ev_metrics(building)

    assert metrics["departures_total"] == 2.0
    assert metrics["departures_met"] == 0.0
    assert metrics["ev_departure_success_rate"] == pytest.approx(0.0)
    assert metrics["departures_target_feasible"] == pytest.approx(1.0)
    assert metrics["departures_target_infeasible"] == pytest.approx(1.0)
    assert metrics["ev_departure_success_feasible_rate"] == pytest.approx(0.0)
    assert metrics["departures_min_acceptable_feasible"] == pytest.approx(1.0)
    assert metrics["departures_min_acceptable_infeasible"] == pytest.approx(1.0)
    assert metrics["ev_departure_min_acceptable_feasible_rate"] == pytest.approx(0.0)


def test_ev_departure_feasibility_respects_electrical_service_phase_headroom():
    service = CityLearnKPIService(
        SimpleNamespace(
            ev_departure_within_tolerance=0.05,
            ev_departure_service_tolerance=0.05,
            seconds_per_time_step=3600,
        )
    )
    charger = _fake_feasibility_departure_charger(
        actual_soc=0.21,
        arrival_soc=0.20,
        capacity_kwh=10.0,
        max_charging_power_kw=11.0,
        charger_id="charger_15_2",
    )
    building = SimpleNamespace(
        name="Building_15",
        time_step=1,
        electric_vehicle_chargers=[charger],
        _charging_constraints_enabled=True,
        _electrical_service_enabled=True,
        _electrical_service_mode="three_phase",
        _electrical_service_default_split="balanced",
        _electrical_service_limits={
            "total": {"import_kw": 100.0, "export_kw": 100.0},
            "per_phase": {
                "L1": {"import_kw": 100.0, "export_kw": 100.0},
                "L2": {"import_kw": 7.0, "export_kw": 100.0},
                "L3": {"import_kw": 100.0, "export_kw": 100.0},
            },
        },
        _charger_phase_map={"charger_15_2": "L2"},
        _ops_service=SimpleNamespace(
            _estimate_base_power_at_step=lambda step: (2.0, {"L1": 0.0, "L2": 2.0, "L3": 0.0}),
            _power_outage_at_step=lambda step: False,
        ),
    )

    metrics = service._compute_ev_metrics(building)

    assert metrics["departures_total"] == 1.0
    assert metrics["departures_target_feasible"] == pytest.approx(0.0)
    assert metrics["departures_target_infeasible"] == pytest.approx(1.0)
    assert metrics["departures_min_acceptable_feasible"] == pytest.approx(0.0)
    assert metrics["departures_min_acceptable_infeasible"] == pytest.approx(1.0)
    assert metrics["departures_within_tolerance_feasible"] == pytest.approx(0.0)
    assert metrics["departures_within_tolerance_infeasible"] == pytest.approx(1.0)


@pytest.mark.parametrize("building_limit_kw,expected_feasible", [(0.75, 0.0), (1.0, 1.0)])
def test_ev_departure_feasibility_applies_min_charging_power_after_headroom_limit(
    building_limit_kw,
    expected_feasible,
):
    service = CityLearnKPIService(
        SimpleNamespace(
            ev_departure_within_tolerance=0.0,
            ev_departure_service_tolerance=0.0,
            seconds_per_time_step=3600,
        )
    )
    charger = _fake_feasibility_departure_charger(
        actual_soc=0.21,
        target_soc=0.25,
        arrival_soc=0.20,
        capacity_kwh=10.0,
        max_charging_power_kw=10.0,
    )
    charger.min_charging_power = 1.0
    building = SimpleNamespace(
        name="Building_1",
        time_step=1,
        electric_vehicle_chargers=[charger],
        _charging_constraints_enabled=True,
        _electrical_service_enabled=False,
        _building_charger_limit_kw=building_limit_kw,
        _phase_limits=[],
        _charger_phase_map={},
    )

    metrics = service._compute_ev_metrics(building)

    assert metrics["departures_target_feasible"] == pytest.approx(expected_feasible)
    assert metrics["departures_target_infeasible"] == pytest.approx(1.0 - expected_feasible)
    assert metrics["departures_min_acceptable_feasible"] == pytest.approx(expected_feasible)
    assert metrics["departures_within_tolerance_feasible"] == pytest.approx(expected_feasible)


def test_ev_departure_feasibility_respects_charger_efficiency():
    service = CityLearnKPIService(
        SimpleNamespace(
            ev_departure_within_tolerance=0.05,
            ev_departure_service_tolerance=0.05,
            seconds_per_time_step=3600,
        )
    )
    charger = _fake_feasibility_departure_charger(
        actual_soc=0.21,
        arrival_soc=0.20,
        capacity_kwh=10.0,
        max_charging_power_kw=10.0,
    )
    charger.efficiency = 0.5
    building = SimpleNamespace(
        name="Building_1",
        time_step=1,
        electric_vehicle_chargers=[charger],
    )

    metrics = service._compute_ev_metrics(building)

    assert metrics["departures_total"] == 1.0
    assert metrics["departures_target_feasible"] == pytest.approx(0.0)
    assert metrics["departures_target_infeasible"] == pytest.approx(1.0)


def test_ev_departure_service_tolerance_is_configurable_from_schema_and_kwargs(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    schema["ev_departure_within_tolerance"] = 0.02
    schema["ev_departure_service_tolerance"] = 0.10
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    env = CityLearnEnv(
        str(schema_path),
        central_agent=True,
        episode_time_steps=2,
        ev_departure_service_tolerance=0.07,
        random_seed=0,
    )

    try:
        assert env.ev_departure_within_tolerance == pytest.approx(0.02)
        assert env.ev_departure_service_tolerance == pytest.approx(0.07)
        metadata = env.get_metadata()
        assert metadata["ev_departure_within_tolerance"] == pytest.approx(0.02)
        assert metadata["ev_departure_service_tolerance"] == pytest.approx(0.07)
    finally:
        env.close()


def test_ev_departure_min_acceptable_aggregates_by_building_and_district(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        _step_once(env)
        env.buildings[0].electric_vehicle_chargers = [
            _fake_departure_charger(0.74, charger_id="a_fail"),
            _fake_departure_charger(0.80, charger_id="a_met"),
        ]
        env.buildings[1].electric_vehicle_chargers = [
            _fake_departure_charger(0.75, charger_id="b_min"),
            _fake_departure_charger(0.90, charger_id="b_surplus"),
        ]

        df = env.evaluate_v2()

        assert float(_kpi_value(df, "Building_A", "building_ev_events_departure_count")) == pytest.approx(2.0)
        assert float(_kpi_value(df, "Building_A", "building_ev_events_departure_min_acceptable_count")) == pytest.approx(1.0)
        assert float(_kpi_value(df, "Building_B", "building_ev_events_departure_min_acceptable_count")) == pytest.approx(2.0)
        assert float(_kpi_value(df, "District", "district_ev_events_departure_min_acceptable_count")) == pytest.approx(3.0)
        assert float(_kpi_value(df, "District", "district_ev_performance_departure_min_acceptable_ratio")) == pytest.approx(0.75)
        assert float(_kpi_value(df, "District", "district_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio")) == pytest.approx(0.0025)
        assert float(_kpi_value(df, "District", "district_ev_performance_departure_soc_absolute_error_mean_ratio")) == pytest.approx(0.0525)
    finally:
        env.close()


def test_ev_departure_new_rates_are_empty_with_zero_departures(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        _step_once(env)
        df = env.evaluate_v2()

        for name, prefix in [("Building_A", "building"), ("District", "district")]:
            assert float(_kpi_value(df, name, f"{prefix}_ev_events_departure_min_acceptable_count")) == pytest.approx(0.0)
            assert pd.isna(_kpi_value(df, name, f"{prefix}_ev_performance_departure_min_acceptable_ratio"))
            assert pd.isna(_kpi_value(df, name, f"{prefix}_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio"))
            assert pd.isna(_kpi_value(df, name, f"{prefix}_ev_performance_departure_soc_absolute_error_mean_ratio"))
    finally:
        env.close()


def test_exported_kpis_csv_contains_ev_departure_service_metrics(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(
        str(schema_path),
        central_agent=True,
        episode_time_steps=2,
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        _step_once(env)
        env.buildings[0].electric_vehicle_chargers = [_fake_departure_charger(0.75)]
        env.export_final_kpis(filepath="exported_kpis.csv")

        exported = pd.read_csv(Path(env.new_folder_path) / "exported_kpis.csv")
        expected_kpis = {
            "building_ev_events_departure_min_acceptable_count",
            "building_ev_performance_departure_min_acceptable_ratio",
            "building_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio",
            "district_ev_events_departure_min_acceptable_count",
            "district_ev_performance_departure_min_acceptable_ratio",
            "district_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio",
        }
        assert expected_kpis.issubset(set(exported["KPI"]))
        assert {"Building_A", "District"}.issubset(set(exported.columns))
    finally:
        env.close()


def test_exported_kpis_csv_preserves_small_unrounded_values(tmp_path: Path, monkeypatch):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(
        str(schema_path),
        central_agent=True,
        episode_time_steps=2,
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        monkeypatch.setattr(
            env,
            "evaluate_v2",
            lambda include_business_as_usual=True: pd.DataFrame(
                [
                    {
                        "cost_function": "district_cost_total_control_eur",
                        "value": 0.0004,
                        "name": "District",
                        "level": "district",
                    }
                ]
            ),
        )

        env.export_final_kpis(filepath="exported_kpis.csv", include_business_as_usual=False)

        exported = pd.read_csv(Path(env.new_folder_path) / "exported_kpis.csv")
        row = exported[exported["KPI"] == "district_cost_total_control_eur"]
        assert len(row) == 1
        assert float(row["District"].iloc[0]) == pytest.approx(0.0004)
    finally:
        env.close()


def test_ev_within_tolerance_kpis_are_consistent():
    env = _run_episode(SCHEMA, seconds_per_time_step=60, episode_steps=120)

    try:
        df = env.evaluate_v2()
        keys = set(df["cost_function"].unique())
        assert "building_ev_events_departure_within_tolerance_count" in keys
        assert "building_ev_performance_departure_within_tolerance_ratio" in keys
        assert "district_ev_events_departure_within_tolerance_count" in keys
        assert "district_ev_performance_departure_within_tolerance_ratio" in keys

        for level, name in df[["level", "name"]].drop_duplicates().itertuples(index=False):
            scoped = df[(df["level"] == level) & (df["name"] == name)].set_index("cost_function")["value"]
            prefix = f"{level}_ev"

            total_key = f"{prefix}_events_departure_count"
            met_key = f"{prefix}_events_departure_met_count"
            within_key = f"{prefix}_events_departure_within_tolerance_count"
            success_ratio_key = f"{prefix}_performance_departure_success_ratio"
            within_ratio_key = f"{prefix}_performance_departure_within_tolerance_ratio"

            if total_key not in scoped:
                continue

            total = float(scoped[total_key])
            met = float(scoped[met_key])
            within = float(scoped[within_key])

            assert within <= total + 1e-9

            within_ratio = scoped[within_ratio_key]
            success_ratio = scoped[success_ratio_key]

            if total <= 1e-9:
                assert pd.isna(within_ratio)
            else:
                assert float(within_ratio) == pytest.approx(within / total, abs=1e-9)
                if not pd.isna(success_ratio):
                    assert 0.0 - 1e-9 <= float(success_ratio) <= 1.0 + 1e-9
            assert met <= total + 1e-9
    finally:
        env.close()


def test_daily_average_kpis_match_total_over_simulated_days(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        env.reset()
        env.step([np.zeros(len(env.action_names[0]), dtype="float32")])
        df = env.evaluate_v2()
        district = df[df["name"] == "District"].set_index("cost_function")["value"]

        simulated_days = max(int(env.time_step), 1) * float(env.seconds_per_time_step) / (24.0 * 3600.0)

        pairs = [
            ("district_cost_total_delta_eur", "district_cost_daily_average_delta_eur"),
            ("district_energy_grid_total_import_delta_kwh", "district_energy_grid_daily_average_import_delta_kwh"),
            ("district_solar_self_consumption_total_export_kwh", "district_solar_self_consumption_daily_average_export_kwh"),
            ("district_energy_grid_community_market_local_traded_total_kwh", "district_energy_grid_community_market_local_traded_daily_average_kwh"),
        ]

        for total_key, daily_key in pairs:
            total_value = float(district[total_key])
            daily_value = float(district[daily_key])
            assert daily_value == pytest.approx(total_value / simulated_days, abs=1e-9)
    finally:
        env.close()


def test_phase_kpis_are_present_only_when_electrical_service_is_enabled():
    env_phase = _run_episode(THREE_PHASE_SCHEMA, seconds_per_time_step=60, episode_steps=8)
    env_legacy = _run_episode(SCHEMA, seconds_per_time_step=60, episode_steps=8)

    try:
        phase_df = env_phase.evaluate_v2()
        legacy_df = env_legacy.evaluate_v2()

        phase_keys = set(phase_df["cost_function"].unique())
        legacy_keys = set(legacy_df["cost_function"].unique())

        assert "district_electrical_service_phase_phase_peaks_import_peak_l1_kw" in phase_keys
        assert "district_electrical_service_phase_phase_peaks_import_peak_l2_kw" in phase_keys
        assert "district_electrical_service_phase_phase_peaks_import_peak_l3_kw" in phase_keys
        assert "district_electrical_service_phase_violations_energy_total_kwh" in phase_keys
        assert "district_electrical_service_phase_requested_pressure_energy_total_kwh" in phase_keys

        assert "district_electrical_service_phase_phase_peaks_import_peak_l2_kw" not in legacy_keys
        assert "district_electrical_service_phase_phase_peaks_import_peak_l3_kw" not in legacy_keys
    finally:
        env_phase.close()
        env_legacy.close()


def test_equity_kpis_are_exported_and_bpr_is_none_when_groups_are_incomplete(tmp_path: Path):
    schema_path = _build_schema_with_manual_equity_groups(tmp_path, SCHEMA, missing_first_group=True)
    env = _run_episode(schema_path, seconds_per_time_step=60, episode_steps=12)

    try:
        df = env.evaluate_v2()
        expected = {
            "building_equity_benefit_relative_percent",
            "district_equity_distribution_gini_benefit_ratio",
            "district_equity_distribution_top20_benefit_ratio",
            "district_equity_distribution_losers_percent",
            "district_equity_distribution_bpr_asset_poor_over_rich_ratio",
        }
        assert expected.issubset(set(df["cost_function"].unique()))

        building_rows = df[
            (df["level"] == "building")
            & (df["cost_function"] == "building_equity_benefit_relative_percent")
        ]
        assert len(building_rows) == len(env.buildings)

        district = df[df["name"] == "District"].set_index("cost_function")["value"]
        assert pd.isna(district["district_equity_distribution_bpr_asset_poor_over_rich_ratio"])
    finally:
        env.close()


def test_equity_group_is_loaded_from_schema(tmp_path: Path):
    schema_path = _build_schema_with_manual_equity_groups(tmp_path, SCHEMA, missing_first_group=False)
    env = CityLearnEnv(
        str(schema_path),
        central_agent=True,
        episode_time_steps=2,
        random_seed=0,
    )

    try:
        env.reset()
        groups = [getattr(building, "equity_group", None) for building in env.buildings]
        assert all(group in {"asset_rich", "asset_poor"} for group in groups)
    finally:
        env.close()


def test_extended_cost_and_equity_use_raw_cost_series(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    schema["community_market"]["enabled"] = False
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        env.reset()
        env.step([np.zeros(len(env.action_names[0]), dtype="float32")])

        control = SimpleNamespace(value="_test_control")
        baseline = SimpleNamespace(value="_test_baseline")

        control_cost = np.array([-2.0, 1.0], dtype="float64")
        baseline_cost = np.array([1.0, 1.0], dtype="float64")
        control_net = np.array([0.5, 0.5], dtype="float64")
        baseline_net = np.array([1.0, 1.0], dtype="float64")
        zeros = np.array([0.0, 0.0], dtype="float64")

        for building in env.buildings:
            setattr(building, "net_electricity_consumption_test_control", control_net.copy())
            setattr(building, "net_electricity_consumption_test_baseline", baseline_net.copy())
            setattr(building, "net_electricity_consumption_emission_test_control", zeros.copy())
            setattr(building, "net_electricity_consumption_emission_test_baseline", zeros.copy())
            setattr(building, "net_electricity_consumption_cost_test_control", control_cost.copy())
            setattr(building, "net_electricity_consumption_cost_test_baseline", baseline_cost.copy())

        env_count = len(env.buildings)
        setattr(env, "net_electricity_consumption_test_control", control_net * env_count)
        setattr(env, "net_electricity_consumption_test_baseline", baseline_net * env_count)
        setattr(env, "net_electricity_consumption_emission_test_control", zeros.copy())
        setattr(env, "net_electricity_consumption_emission_test_baseline", zeros.copy())
        setattr(env, "net_electricity_consumption_cost_test_control", control_cost * env_count)
        setattr(env, "net_electricity_consumption_cost_test_baseline", baseline_cost * env_count)

        df = env.evaluate_v2(control_condition=control, baseline_condition=baseline)
        building_name = env.buildings[0].name
        building_df = df[df["name"] == building_name].set_index("cost_function")["value"]
        district_df = df[df["name"] == "District"].set_index("cost_function")["value"]

        settled_steps = max(int(env.time_step), 1)
        building_control_total = float(control_cost[:settled_steps].sum())
        building_baseline_total = float(baseline_cost[:settled_steps].sum())
        building_delta_total = building_control_total - building_baseline_total
        building_benefit_relative_percent = (
            (building_baseline_total - building_control_total) / building_baseline_total * 100.0
        )

        assert float(building_df["building_cost_total_control_eur"]) == pytest.approx(building_control_total)
        assert float(building_df["building_cost_total_baseline_eur"]) == pytest.approx(building_baseline_total)
        assert float(building_df["building_cost_total_delta_eur"]) == pytest.approx(building_delta_total)
        assert float(building_df["building_equity_benefit_relative_percent"]) == pytest.approx(building_benefit_relative_percent)

        # Legacy normalized cost still uses clipped CostFunction.cost semantics.
        legacy_df = env.evaluate(control_condition=control, baseline_condition=baseline)
        legacy_building = legacy_df[legacy_df["name"] == building_name].set_index("cost_function")["value"]
        expected_legacy_cost_total = float(CostFunction.cost(control_cost[:settled_steps])[-1])
        assert float(legacy_building["cost_total"]) == pytest.approx(expected_legacy_cost_total)

        assert float(district_df["district_cost_total_control_eur"]) == pytest.approx(building_control_total * env_count)
        assert float(district_df["district_cost_total_baseline_eur"]) == pytest.approx(building_baseline_total * env_count)
        assert float(district_df["district_cost_total_delta_eur"]) == pytest.approx(building_delta_total * env_count)
    finally:
        env.close()


def test_evaluate_is_legacy_only_and_v2_uses_prefixed_family_names():
    env = _run_episode(SCHEMA, seconds_per_time_step=60, episode_steps=10)

    try:
        legacy = env.evaluate()
        v2 = env.evaluate_v2()

        legacy_keys = set(legacy["cost_function"].unique())
        assert legacy_keys == LEGACY_KPI_KEYS

        v2_keys = set(v2["cost_function"].unique())
        assert not any(key in LEGACY_KPI_KEYS for key in v2_keys)
        assert all(key.startswith(("building_", "district_")) for key in v2_keys)
        assert all(re.match(r"^(building|district)_[a-z0-9]+(?:_[a-z0-9]+)+$", key) for key in v2_keys)

        # Community-only KPIs must stay district-level whenever they exist.
        for community_key in [
            "district_energy_grid_community_market_local_traded_total_kwh",
            "district_energy_grid_community_market_local_traded_daily_average_kwh",
            "district_solar_self_consumption_community_market_import_share_ratio",
        ]:
            rows = v2[v2["cost_function"] == community_key]
            if rows.empty:
                continue
            assert set(rows["level"]) == {"district"}
            assert set(rows["name"]) == {"District"}

        assert all("_autoconsumo_" not in key for key in v2_keys)
    finally:
        env.close()
