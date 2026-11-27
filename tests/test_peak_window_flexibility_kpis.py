"""Regression tests for opt-in recurring evaluation-window KPIs (#338)."""

from __future__ import annotations

from copy import deepcopy
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.comparison import compare_exports, compare_manifests
from citylearn.internal.evaluation_window import step_overlap_weights
from citylearn.internal.temporal import TimeAxis
from citylearn.multi_community import MultiCommunityEnv

ROOT = Path(__file__).resolve().parents[1]


def _write_synthetic_scenario(
    folder: Path,
    *,
    step_seconds: int = 3600,
    start_clock_seconds: int = 0,
    num_steps: int = 24,
    loads_kwh: Optional[Sequence[float]] = None,
    solar_kwh: Optional[Sequence[float]] = None,
    include_battery: bool = True,
    battery_capacity_kwh: float = 20.0,
    battery_power_kw: float = 10.0,
    battery_initial_soc: float = 0.5,
    include_ev: bool = True,
    ev_capacity_kwh: float = 40.0,
    ev_power_kw: float = 10.0,
    ev_initial_soc: float = 0.5,
    ev_required_soc_pct: float = 50.0,
    include_minutes_col: Optional[bool] = None,
    include_seconds_col: Optional[bool] = None,
    legacy_23h_as_zero: bool = False,
    declare_dataset_step: bool = False,
    use_utc_calendar: bool = False,
    calendar_start_utc: str = "2024-07-01T00:00:00Z",
    timezone: Optional[str] = None,
    evaluation_window: Any = None,
) -> Path:
    """Create a deterministic single-building CSV scenario with exact step clocks."""
    folder.mkdir(parents=True, exist_ok=True)
    n_rows = num_steps + 1  # final row is the terminal observation

    if include_minutes_col is None:
        include_minutes_col = (step_seconds % 3600) != 0
    if include_seconds_col is None:
        include_seconds_col = (step_seconds % 60) != 0

    loads = list(loads_kwh) if loads_kwh is not None else [2.0] * num_steps
    if len(loads) < n_rows:
        loads = loads + [loads[-1]] * (n_rows - len(loads))
    solars = list(solar_kwh) if solar_kwh is not None else [0.0] * num_steps
    if len(solars) < n_rows:
        solars = solars + [solars[-1]] * (n_rows - len(solars))

    b_rows: List[Dict[str, Any]] = []
    for idx in range(n_rows):
        sec_of_day = (start_clock_seconds + idx * step_seconds) % 86400
        hour_zero_based = sec_of_day // 3600
        # CityLearn dataset hour runs 1..24 where hour=1, minutes=0 starts at 00:00 and hour=24 starts at 23:00.
        hour = 0 if (legacy_23h_as_zero and hour_zero_based == 23) else (hour_zero_based + 1)
        minute = (sec_of_day % 3600) // 60
        second = sec_of_day % 60
        row: Dict[str, Any] = {
            "month": 7,
            "hour": int(hour),
        }
        if include_minutes_col:
            row["minutes"] = int(minute)
        if include_seconds_col:
            row["seconds"] = int(second)
        row.update({
            "day_type": 1,
            "daylight_savings_status": 0,
            "indoor_dry_bulb_temperature": 21.0,
            "average_unmet_cooling_setpoint_difference": 0.0,
            "indoor_relative_humidity": 45.0,
            "non_shiftable_load": float(loads[idx]),
            "dhw_demand": 0.0,
            "cooling_demand": 0.0,
            "heating_demand": 0.0,
            "solar_generation": float(solars[idx]),
        })
        b_rows.append(row)
    pd.DataFrame(b_rows).to_csv(folder / "Building_1.csv", index=False)

    pd.DataFrame({
        "outdoor_dry_bulb_temperature": [20.0] * n_rows,
        "outdoor_relative_humidity": [50.0] * n_rows,
        "diffuse_solar_irradiance": [0.0] * n_rows,
        "direct_solar_irradiance": [0.0] * n_rows,
        "outdoor_dry_bulb_temperature_predicted_1": [20.0] * n_rows,
        "outdoor_dry_bulb_temperature_predicted_2": [20.0] * n_rows,
        "outdoor_dry_bulb_temperature_predicted_3": [20.0] * n_rows,
        "outdoor_relative_humidity_predicted_1": [50.0] * n_rows,
        "outdoor_relative_humidity_predicted_2": [50.0] * n_rows,
        "outdoor_relative_humidity_predicted_3": [50.0] * n_rows,
        "diffuse_solar_irradiance_predicted_1": [0.0] * n_rows,
        "diffuse_solar_irradiance_predicted_2": [0.0] * n_rows,
        "diffuse_solar_irradiance_predicted_3": [0.0] * n_rows,
        "direct_solar_irradiance_predicted_1": [0.0] * n_rows,
        "direct_solar_irradiance_predicted_2": [0.0] * n_rows,
        "direct_solar_irradiance_predicted_3": [0.0] * n_rows,
    }).to_csv(folder / "weather.csv", index=False)

    pd.DataFrame({
        "electricity_pricing": [0.20] * n_rows,
        "electricity_pricing_predicted_1": [0.20] * n_rows,
        "electricity_pricing_predicted_2": [0.20] * n_rows,
        "electricity_pricing_predicted_3": [0.20] * n_rows,
    }).to_csv(folder / "pricing.csv", index=False)

    pd.DataFrame({"carbon_intensity": [0.15] * n_rows}).to_csv(folder / "carbon_intensity.csv", index=False)

    if use_utc_calendar:
        t0 = datetime.datetime.fromisoformat(calendar_start_utc.replace("Z", "+00:00"))
        cal_rows = [
            {
                "time_step": idx,
                "timestamp_utc": (
                    t0 + datetime.timedelta(seconds=idx * step_seconds)
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for idx in range(n_rows)
        ]
        pd.DataFrame(cal_rows).to_csv(folder / "calendar.csv", index=False)

    observations: Dict[str, Any] = {
        "month": {"active": True, "shared_in_central_agent": True},
        "day_type": {"active": True, "shared_in_central_agent": True},
        "hour": {"active": True, "shared_in_central_agent": True},
        "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
        "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
        "electricity_pricing": {"active": True, "shared_in_central_agent": True},
        "carbon_intensity": {"active": True, "shared_in_central_agent": True},
    }
    if include_minutes_col:
        observations["minutes"] = {"active": True, "shared_in_central_agent": True}

    actions: Dict[str, Any] = {}
    building_cfg: Dict[str, Any] = {
        "include": True,
        "energy_simulation": "Building_1.csv",
        "weather": "weather.csv",
        "carbon_intensity": "carbon_intensity.csv",
        "pricing": "pricing.csv",
        "inactive_observations": [],
        "inactive_actions": [],
    }
    if include_battery:
        observations["electrical_storage_soc"] = {"active": True, "shared_in_central_agent": False}
        actions["electrical_storage"] = {"active": True}
        building_cfg["electrical_storage"] = {
            "type": "citylearn.energy_model.Battery",
            "autosize": False,
            "attributes": {
                "capacity": float(battery_capacity_kwh),
                "nominal_power": float(battery_power_kw),
                "initial_soc": float(battery_initial_soc),
                "efficiency": 1.0,
                "depth_of_discharge": 1.0,
                "loss_coefficient": 0.0,
                "capacity_loss_coefficient": 0.0,
                "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
            },
        }

    evs_def: Dict[str, Any] = {}
    if include_ev:
        actions["electric_vehicle_storage"] = {"active": True}
        c_rows = [
            {
                "electric_vehicle_charger_state": 1,
                "electric_vehicle_id": "EV_1",
                "electric_vehicle_departure_time": max(num_steps - idx, 1),
                "electric_vehicle_required_soc_departure": float(ev_required_soc_pct),
                "electric_vehicle_estimated_arrival_time": "",
                "electric_vehicle_estimated_soc_arrival": "",
            }
            for idx in range(n_rows)
        ]
        pd.DataFrame(c_rows).to_csv(folder / "charger_1_1.csv", index=False)
        evs_def["EV_1"] = {
            "include": True,
            "battery": {
                "type": "citylearn.energy_model.Battery",
                "autosize": False,
                "attributes": {
                    "capacity": float(ev_capacity_kwh),
                    "nominal_power": float(ev_power_kw),
                    "initial_soc": float(ev_initial_soc),
                    "efficiency": 1.0,
                    "depth_of_discharge": 1.0,
                    "loss_coefficient": 0.0,
                    "capacity_loss_coefficient": 0.0,
                    "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
                    "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                    "discharge_power_curve": [[0.0, 1.0], [1.0, 1.0]],
                },
            },
        }
        building_cfg["chargers"] = {
            "charger_1_1": {
                "type": "citylearn.electric_vehicle_charger.Charger",
                "charger_simulation": "charger_1_1.csv",
                "autosize": False,
                "attributes": {
                    "nominal_power": float(ev_power_kw),
                    "efficiency": 1.0,
                    "charger_type": 0,
                    "max_charging_power": float(ev_power_kw),
                    "min_charging_power": 0.0,
                    "max_discharging_power": float(ev_power_kw),
                    "min_discharging_power": 0.0,
                },
            }
        }

    if not actions:
        # Keep one passive action slot when neither battery nor EV is present.
        observations["electrical_storage_soc"] = {"active": True, "shared_in_central_agent": False}
        actions["electrical_storage"] = {"active": True}
        building_cfg["electrical_storage"] = {
            "type": "citylearn.energy_model.Battery",
            "autosize": False,
            "attributes": {
                "capacity": 10.0,
                "nominal_power": 5.0,
                "initial_soc": 0.5,
                "efficiency": 1.0,
            },
        }

    schema: Dict[str, Any] = {
        "random_seed": 0,
        "root_directory": str(folder),
        "central_agent": True,
        "simulation_start_time_step": 0,
        "simulation_end_time_step": num_steps,
        "episode_time_steps": n_rows,
        "rolling_episode_split": False,
        "random_episode_split": False,
        "seconds_per_time_step": int(step_seconds),
        "start_date": "2024-07-01",
        "observations": observations,
        "actions": actions,
        "agent": {
            "type": "citylearn.agents.baseline.ZeroActionAgent",
            "attributes": {},
        },
        "reward_function": {
            "type": "citylearn.reward_function.RewardFunction",
            "attributes": {},
        },
        "buildings": {"Building_1": building_cfg},
    }
    if evs_def:
        schema["electric_vehicles_def"] = evs_def
    if declare_dataset_step:
        schema["dataset_seconds_per_time_step"] = int(step_seconds)
    if use_utc_calendar:
        schema["time_axis"] = {"calendar_file": "calendar.csv"}
    if timezone is not None:
        schema["timezone"] = timezone
    if evaluation_window is not None:
        schema["evaluation_window"] = evaluation_window

    schema_path = folder / "schema.json"
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema_path


def _kpi_map(df: pd.DataFrame, level: str = "district", name: Optional[str] = None) -> Dict[str, float]:
    sub = df[df["level"] == level]
    if name is not None:
        sub = sub[sub["name"] == name]
    return {
        str(row["cost_function"]): (np.nan if row["value"] is None else float(row["value"]))
        for _, row in sub.iterrows()
    }


def _run_episode(env: CityLearnEnv, step_actions: Optional[Sequence[Sequence[float]]] = None) -> pd.DataFrame:
    env.reset(seed=0)
    idx = 0
    n_act = len(env.action_names[0])
    while not env.terminated:
        if step_actions is not None and idx < len(step_actions):
            act = np.asarray(step_actions[idx], dtype="float32")
        else:
            act = np.zeros(n_act, dtype="float32")
        env.step([act])
        idx += 1
    return env


def test_default_disabled_leaves_kpi_and_export_contracts_unchanged(tmp_path: Path):
    schema_path = _write_synthetic_scenario(tmp_path / "scenario", num_steps=6)

    outputs = {}
    manifests = {}
    tables = {}
    for label, win_arg in (
        ("default", None),
        ("false_bool", False),
        ("false_dict", {"enabled": False}),
    ):
        kwargs: Dict[str, Any] = {
            "render_mode": "none",
            "render_directory": tmp_path / "exports",
            "render_session_name": label,
            "export_kpis_on_episode_end": False,
        }
        if win_arg is not None:
            kwargs["evaluation_window"] = win_arg
        env = CityLearnEnv(str(schema_path), **kwargs)
        try:
            _run_episode(env)
            env.set_experiment_identity(f"ctrl-{label}", "1.0", {})
            df = env.evaluate_v2()
            tables[label] = df
            assert not df["cost_function"].str.contains(
                "energy_grid_window_average_power_|ev_window_net_exchange_"
            ).any()
            env.export_final_kpis(export_business_as_usual_timeseries=False)
            out_dir = Path(env.new_folder_path)
            outputs[label] = pd.read_csv(out_dir / "exported_kpis.csv")
            manifests[label] = json.loads((out_dir / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
        finally:
            env.close()

    pd.testing.assert_frame_equal(tables["default"], tables["false_bool"])
    pd.testing.assert_frame_equal(tables["default"], tables["false_dict"])
    pd.testing.assert_frame_equal(outputs["default"], outputs["false_bool"])
    pd.testing.assert_frame_equal(outputs["default"], outputs["false_dict"])
    assert (
        manifests["default"]["comparison_context"]["physical_configuration_sha256"]
        == manifests["false_dict"]["comparison_context"]["physical_configuration_sha256"]
    )
    assert manifests["default"]["evaluation_window"]["enabled"] is False
    assert compare_manifests(manifests["default"], manifests["false_dict"])["status"] == "paired"


def test_starter_window_and_custom_window_shift_without_daily_peak_change(tmp_path: Path):
    # Base load has a 10 kW midday peak at 12:00, 4 kW during 17:00-20:00, and 2 kW elsewhere.
    loads = [2.0] * 24
    loads[12] = 10.0
    for h in (17, 18, 19):
        loads[h] = 4.0

    schema_path = _write_synthetic_scenario(
        tmp_path / "shift_scenario",
        num_steps=24,
        loads_kwh=loads,
        include_battery=True,
        battery_capacity_kwh=20.0,
        battery_power_kw=20.0,
        battery_initial_soc=0.5,
        include_ev=False,
    )

    # Starter window enabled via True and {"enabled": True} resolves to 16:00:00..19:00:00.
    env_starter = CityLearnEnv(str(schema_path), evaluation_window=True)
    try:
        assert env_starter.get_metadata()["evaluation_window"] == {
            "enabled": True,
            "start": "16:00:00",
            "end": "19:00:00",
            "timezone": "scenario_local",
        }
        _run_episode(env_starter)
        starter_kpis = _kpi_map(env_starter.evaluate_v2())
        # Starter window 16:00-19:00 covers hours 16 (2 kW), 17 (4 kW), 18 (4 kW) -> mean 10/3 kW.
        assert starter_kpis["district_energy_grid_window_average_power_control_kw"] == pytest.approx(10.0 / 3.0)
    finally:
        env_starter.close()

    # Custom window 17:00..20:00: controller charges +9 kWh off-peak (hours 1,2,3 at +3 kWh/step -> 0.15 action)
    # and discharges -3 kWh/step during 17:00, 18:00, 19:00 (-0.15 of 20 kWh capacity), keeping the 10 kW peak at 12:00.
    actions = [[0.0] for _ in range(24)]
    for h in (1, 2, 3):
        actions[h] = [0.15]   # +3 kWh into 20 kWh battery -> net load 5 kW < 10 kW midday peak
    for h in (17, 18, 19):
        actions[h] = [-0.15]  # -3 kWh from 20 kWh battery -> net load drops from 4 kW to 1 kW

    env_custom = CityLearnEnv(
        str(schema_path),
        evaluation_window={"enabled": True, "start": "17:00", "end": "20:00"},
    )
    try:
        _run_episode(env_custom, actions)
        df = env_custom.evaluate_v2()
        d_kpis = _kpi_map(df, "district")
        b_kpis = _kpi_map(df, "building", "Building_1")

        # KPI IDs stay identical regardless of the configured hours.
        assert set(d_kpis) >= {
            "district_energy_grid_window_average_power_control_kw",
            "district_energy_grid_window_average_power_business_as_usual_kw",
            "district_energy_grid_window_average_power_delta_to_business_as_usual_kw",
            "district_ev_window_net_exchange_control_kwh",
        }
        # Daily peak stayed at 10 kW in both control and BAU, while 17:00-20:00 dropped from 4 kW to 1 kW (-3 kW).
        assert d_kpis["district_energy_grid_shape_quality_peak_daily_average_delta_to_business_as_usual_kw"] == pytest.approx(0.0, abs=1.0e-6)
        assert d_kpis["district_energy_grid_window_average_power_control_kw"] == pytest.approx(1.0, abs=1.0e-6)
        assert d_kpis["district_energy_grid_window_average_power_business_as_usual_kw"] == pytest.approx(4.0, abs=1.0e-6)
        assert d_kpis["district_energy_grid_window_average_power_delta_to_business_as_usual_kw"] == pytest.approx(-3.0, abs=1.0e-6)
        assert b_kpis["building_energy_grid_window_average_power_delta_to_business_as_usual_kw"] == pytest.approx(-3.0, abs=1.0e-6)
        assert d_kpis["district_ev_window_net_exchange_control_kwh"] == pytest.approx(0.0, abs=1.0e-9)
    finally:
        env_custom.close()


def test_subhour_boundaries_15min_and_15sec_with_and_without_seconds_column(tmp_path: Path):
    # 1) 15-minute steps (900 s) from 16:00 to 17:00 (4 steps): window 16:15 to 16:30 selects step 1 only.
    schema_15m = _write_synthetic_scenario(
        tmp_path / "s_15m",
        step_seconds=900,
        start_clock_seconds=16 * 3600,
        num_steps=4,
        loads_kwh=[1.0, 2.5, 0.5, 1.0],  # kWh per 0.25 h -> step 1 base power = 10.0 kW
        include_battery=False,
        include_ev=True,
        ev_capacity_kwh=40.0,
        ev_power_kw=8.0,
        ev_initial_soc=0.5,
        ev_required_soc_pct=50.0,
    )
    # Action on EV charger: step 0 charges (+0.5 -> 4 kW = 1.0 kWh), step 1 discharges V2G (-0.5 -> -4 kW = -1.0 kWh).
    env_15m = CityLearnEnv(str(schema_15m), evaluation_window={"start": "16:15", "end": "16:30"})
    try:
        _run_episode(env_15m, [[0.5], [-0.5], [0.0], [0.0]])
        d_15m = _kpi_map(env_15m.evaluate_v2())
        # Step 1 control net = 2.5 kWh - 1.0 kWh = 1.5 kWh over 0.25 h -> 6.0 kW; EV net in window = -1.0 kWh.
        assert d_15m["district_energy_grid_window_average_power_control_kw"] == pytest.approx(6.0, abs=1.0e-6)
        assert d_15m["district_ev_window_net_exchange_control_kwh"] == pytest.approx(-1.0, abs=1.0e-6)
    finally:
        env_15m.close()

    # 2) 15-second steps (15 s) from 16:14:00 to 16:31:00 (68 steps), tested WITH and WITHOUT a seconds column.
    # Steps 4..63 (60 steps = 900 s = 0.25 h) lie inside [16:15:00, 16:30:00).
    loads_15s = [0.05 if 4 <= idx < 64 else 0.25 for idx in range(68)]  # 0.05 kWh / (15/3600 h) = 12.0 kW inside
    for label, has_seconds in (("with_seconds", True), ("without_seconds", False)):
        schema_15s = _write_synthetic_scenario(
            tmp_path / f"s_15s_{label}",
            step_seconds=15,
            start_clock_seconds=16 * 3600 + 14 * 60,
            num_steps=68,
            loads_kwh=loads_15s,
            include_battery=False,
            include_ev=True,
            ev_capacity_kwh=40.0,
            ev_power_kw=12.0,
            ev_initial_soc=0.5,
            ev_required_soc_pct=50.0,
            include_minutes_col=True,
            include_seconds_col=has_seconds,
            declare_dataset_step=not has_seconds,
        )
        # Charge at full 12 kW (0.05 kWh per 15-s step -> 3.0 kWh across 60 window steps) inside [16:15, 16:30).
        acts_15s = [[1.0] if 4 <= idx < 64 else [0.0] for idx in range(68)]
        env_15s = CityLearnEnv(str(schema_15s), evaluation_window={"start": "16:15", "end": "16:30"})
        try:
            _run_episode(env_15s, acts_15s)
            d_15s = _kpi_map(env_15s.evaluate_v2())
            assert d_15s["district_ev_window_net_exchange_control_kwh"] == pytest.approx(3.0, abs=1.0e-5)
            assert d_15s["district_energy_grid_window_average_power_control_kw"] == pytest.approx(24.0, abs=1.0e-4)
        finally:
            env_15s.close()


def test_midnight_wrap_and_1_to_24_hour_convention(tmp_path: Path):
    # 10 hourly steps starting at 21:00 local time:
    # clock starts [21:00, 22:00, 23:00, 00:00, 01:00, 02:00, 03:00, 04:00, 05:00, 06:00]
    # dataset hour [   22,    23,    24,     1,     2,     3,     4,     5,     6,     7].
    # Window 22:00 to 06:00 covers indices 1..8 (8 hours); indices 0 (21:00, hour=22) and 9 (06:00, hour=7) are outside.
    loads = [20.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 3.0, 20.0]
    for label, use_zero_for_23h in (("standard_1_to_24", False), ("legacy_zero_at_23h", True)):
        schema_wrap = _write_synthetic_scenario(
            tmp_path / f"wrap_{label}",
            step_seconds=3600,
            start_clock_seconds=21 * 3600,
            num_steps=10,
            loads_kwh=loads,
            include_battery=False,
            include_ev=True,
            ev_capacity_kwh=50.0,
            ev_power_kw=5.0,
            ev_initial_soc=0.5,
            ev_required_soc_pct=50.0,
            legacy_23h_as_zero=use_zero_for_23h,
        )
        b_df = pd.read_csv(schema_wrap.parent / "Building_1.csv")
        assert int(b_df.loc[2, "hour"]) == (0 if use_zero_for_23h else 24)  # 23:00 local
        assert int(b_df.loc[3, "hour"]) == 1                                # 00:00 local
        # Charge +2 kW during indices 1..4 (+8 kWh) and discharge -1 kW during indices 5..8 (-4 kWh) -> net +4 kWh.
        acts = [[0.0]] + [[0.4]] * 4 + [[-0.2]] * 4 + [[0.0]]
        env = CityLearnEnv(str(schema_wrap), evaluation_window={"start": "22:00", "end": "06:00"})
        try:
            _run_episode(env, acts)
            d_kpis = _kpi_map(env.evaluate_v2())
            # Window net grid energy = 8 * 3.0 + 4.0 = 28.0 kWh over 8 h -> 3.5 kW.
            assert d_kpis["district_ev_window_net_exchange_control_kwh"] == pytest.approx(4.0, abs=1.0e-6)
            assert d_kpis["district_energy_grid_window_average_power_control_kw"] == pytest.approx(3.5, abs=1.0e-6)
        finally:
            env.close()


def test_bundled_portugal_datasets_match_timestamp_local_and_time_axis(tmp_path: Path):
    pytest.importorskip("pyarrow")

    # 1) pt_rec_30/evaluation/rec_30_combined.json: verify selected starter-window steps against timestamp_local
    # in both winter (+00:00, step 4080 = 2023-02-12 12:00) and summer DST (+01:00, step 12840 = 2023-05-14 19:00).
    rec30_schema_path = ROOT / "data" / "datasets" / "pt_rec_30" / "evaluation" / "rec_30_combined.json"
    rec30_schema = json.loads(rec30_schema_path.read_text(encoding="utf-8"))
    events_by_step = {int(ev["time_step"]): ev["timestamp_local"] for ev in rec30_schema["topology_events"]}
    assert events_by_step[4080].startswith("2023-02-12 12:00:00+00:00")
    assert events_by_step[12840].startswith("2023-05-14 19:00:00+01:00")

    # Winter slice 4080..4112 (2023-02-12 12:00 to 20:00 local, 32 quarter-hour steps):
    # 16:00..18:45 local is 4h..6h45m after 12:00 -> offsets 16..27 (global steps 4096..4107, hour=17..19).
    env_winter = CityLearnEnv(
        str(rec30_schema_path),
        simulation_start_time_step=4080,
        simulation_end_time_step=4112,
        evaluation_window=True,
    )
    try:
        m1_es = env_winter.buildings[0].energy_simulation
        assert (int(m1_es.hour[0]), int(m1_es.minutes[0])) == (13, 0)    # 12:00 local
        assert (int(m1_es.hour[16]), int(m1_es.minutes[16])) == (17, 0)  # 16:00 local
        assert (int(m1_es.hour[27]), int(m1_es.minutes[27])) == (19, 45) # 18:45 local
        assert (int(m1_es.hour[28]), int(m1_es.minutes[28])) == (20, 0)  # 19:00 local
        w_winter = step_overlap_weights(env_winter, env_winter._evaluation_window_parsed, 32)
        expected_winter = np.array([1.0 if 16 <= idx < 28 else 0.0 for idx in range(32)], dtype="float64")
        assert np.array_equal(w_winter, expected_winter)
    finally:
        env_winter.close()

    # Summer DST slice 12824..12844 (2023-05-14 15:00 to 20:00+01:00, 20 quarter-hour steps):
    # step 12840 (offset 16) has timestamp_local 2023-05-14 19:00:00+01:00, so 16:00..18:45 is offsets 4..15.
    env_summer = CityLearnEnv(
        str(rec30_schema_path),
        simulation_start_time_step=12824,
        simulation_end_time_step=12844,
        evaluation_window=True,
    )
    try:
        m1_sum = env_summer.buildings[0].energy_simulation
        assert (int(m1_sum.hour[4]), int(m1_sum.minutes[4])) == (17, 0)   # 16:00+01:00
        assert (int(m1_sum.hour[15]), int(m1_sum.minutes[15])) == (19, 45) # 18:45+01:00
        assert (int(m1_sum.hour[16]), int(m1_sum.minutes[16])) == (20, 0)  # 19:00+01:00 (event 12840)
        w_summer = step_overlap_weights(env_summer, env_summer._evaluation_window_parsed, 20)
        expected_summer = np.array([1.0 if 4 <= idx < 16 else 0.0 for idx in range(20)], dtype="float64")
        assert np.array_equal(w_summer, expected_summer)
    finally:
        env_summer.close()

    # 2) pt_rec_4: run 1 full day (96 steps, 2023-01-01 00:00 to 24:00 Europe/Lisbon), verify steps 64..75
    # (16:00..18:45 local, hour=17..19) are selected, and confirm exact parity with a canonical TimeAxis calendar.
    rec4_schema_path = ROOT / "data" / "datasets" / "pt_rec_4" / "schema.json"
    env_rec4 = CityLearnEnv(
        str(rec4_schema_path),
        simulation_start_time_step=0,
        simulation_end_time_step=96,
        evaluation_window=True,
    )
    try:
        env_rec4.reset(seed=0)
        while not env_rec4.terminated:
            env_rec4.step({
                "tables": {
                    table: np.zeros(space.shape, dtype="float32")
                    for table, space in env_rec4.action_space["tables"].items()
                }
            })
        w_inferred = step_overlap_weights(env_rec4, env_rec4._evaluation_window_parsed, 96)
        expected_day = np.array([1.0 if 64 <= idx < 76 else 0.0 for idx in range(96)], dtype="float64")
        assert np.array_equal(w_inferred, expected_day)

        cal_csv = tmp_path / "rec4_calendar.csv"
        t0_utc = datetime.datetime(2023, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
        pd.DataFrame([
            {
                "time_step": idx,
                "timestamp_utc": (t0_utc + datetime.timedelta(seconds=idx * 900)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for idx in range(97)
        ]).to_csv(cal_csv, index=False)
        env_rec4._time_axis = TimeAxis({
            "root_directory": str(tmp_path),
            "timezone": "Europe/Lisbon",
            "time_axis": {"calendar_file": "rec4_calendar.csv"},
        })
        w_calendar = step_overlap_weights(env_rec4, env_rec4._evaluation_window_parsed, 96)
        assert np.array_equal(w_inferred, w_calendar)

        env_rec4._time_axis = None
        d_rec4 = _kpi_map(env_rec4.evaluate_v2(include_business_as_usual=False))
        expected_kw = float(np.sum(np.asarray(env_rec4.net_electricity_consumption[64:76], dtype="float64")) / 3.0)
        assert d_rec4["district_energy_grid_window_average_power_control_kw"] == pytest.approx(expected_kw, abs=1.0e-6)
    finally:
        env_rec4.close()


def test_steps_straddling_window_boundaries_and_utc_time_axis_timezone(tmp_path: Path):
    # Hourly steps starting at 15:00: [15:00, 16:00, 17:00, 18:00, 19:00].
    # Window 16:30 to 18:30 gives weights [0.0, 0.5, 1.0, 0.5, 0.0] -> H_W = 2.0 h.
    schema_straddle = _write_synthetic_scenario(
        tmp_path / "straddle",
        step_seconds=3600,
        start_clock_seconds=15 * 3600,
        num_steps=5,
        loads_kwh=[50.0, 10.0, 4.0, 6.0, 50.0],
        include_battery=False,
        include_ev=True,
        ev_capacity_kwh=40.0,
        ev_power_kw=8.0,
        ev_initial_soc=0.5,
        ev_required_soc_pct=50.0,
    )
    # Charger kWh per step: [0, +8, -2, +4, 0] -> weighted = 0.5*8 + 1.0*(-2) + 0.5*4 = +4.0 kWh.
    # Net grid kWh per step: [50, 18, 2, 10, 50] -> weighted = 0.5*18 + 1.0*2 + 0.5*10 = 16.0 kWh -> 8.0 kW.
    acts = [[0.0], [1.0], [-0.25], [0.5], [0.0]]
    env = CityLearnEnv(str(schema_straddle), evaluation_window={"start": "16:30", "end": "18:30"})
    try:
        _run_episode(env, acts)
        d_kpis = _kpi_map(env.evaluate_v2())
        assert d_kpis["district_ev_window_net_exchange_control_kwh"] == pytest.approx(4.0, abs=1.0e-6)
        assert d_kpis["district_energy_grid_window_average_power_control_kw"] == pytest.approx(8.0, abs=1.0e-6)
    finally:
        env.close()

    # Canonical UTC TimeAxis on 2024-07-01T15:00:00Z (16:00:00 in Europe/Lisbon WEST = UTC+1).
    # The calendar columns of the data are Lisbon civil time, as the calendar converted to the timezone (#464).
    schema_tz = _write_synthetic_scenario(
        tmp_path / "tz_lisbon",
        step_seconds=3600,
        start_clock_seconds=16 * 3600,
        num_steps=4,
        loads_kwh=[9.0, 3.0, 3.0, 20.0],  # UTC 15,16,17,18 -> Lisbon 16,17,18,19
        include_battery=False,
        include_ev=False,
        use_utc_calendar=True,
        calendar_start_utc="2024-07-01T15:00:00Z",
        timezone="Europe/Lisbon",
    )
    env_lisbon = CityLearnEnv(str(schema_tz), evaluation_window=True)
    try:
        assert env_lisbon.get_metadata()["evaluation_window"]["timezone"] == "Europe/Lisbon"
        _run_episode(env_lisbon)
        # Lisbon 16:00-19:00 selects indices 0,1,2 -> (9 + 3 + 3) / 3 = 5.0 kW.
        assert _kpi_map(env_lisbon.evaluate_v2())["district_energy_grid_window_average_power_control_kw"] == pytest.approx(5.0)
    finally:
        env_lisbon.close()


def test_no_matching_steps_returns_nan_across_levels(tmp_path: Path):
    # Simulate 08:00 to 12:00 while evaluation_window is 16:00 to 19:00 -> 0 overlap hours -> NaN.
    schema_a = _write_synthetic_scenario(
        tmp_path / "no_match_a",
        step_seconds=3600,
        start_clock_seconds=8 * 3600,
        num_steps=4,
        loads_kwh=[3.0, 4.0, 5.0, 6.0],
    )
    schema_b = _write_synthetic_scenario(
        tmp_path / "no_match_b",
        step_seconds=3600,
        start_clock_seconds=8 * 3600,
        num_steps=4,
        loads_kwh=[2.0, 2.0, 2.0, 2.0],
    )
    portfolio = MultiCommunityEnv(
        communities=[
            {"community_id": "a", "schema": str(schema_a), "weight": 1.0},
            {"community_id": "b", "schema": str(schema_b), "weight": 2.0},
        ],
        evaluation_window={"enabled": True, "start": "16:00", "end": "19:00"},
    )
    try:
        portfolio.reset(seed=0)
        while not portfolio.terminated:
            portfolio.step({
                cid: [np.zeros(space.shape, dtype="float32") for space in child.action_space]
                for cid, child in portfolio.envs.items()
            })
        df = portfolio.evaluate_v2()
        win_rows = df[df["cost_function"].str.contains(
            "energy_grid_window_average_power_|ev_window_net_exchange_"
        )]
        assert not win_rows.empty
        assert win_rows["value"].isna().all()
    finally:
        portfolio.close()


def test_bau_disabled_and_zero_ev_scenarios(tmp_path: Path):
    schema_no_ev = _write_synthetic_scenario(
        tmp_path / "no_ev",
        step_seconds=3600,
        start_clock_seconds=16 * 3600,
        num_steps=3,
        loads_kwh=[6.0, 6.0, 6.0],
        include_battery=True,
        battery_capacity_kwh=20.0,
        battery_power_kw=20.0,
        battery_initial_soc=0.5,
        include_ev=False,
    )
    env = CityLearnEnv(str(schema_no_ev), evaluation_window=True)
    try:
        # Discharge stationary battery at -3 kWh/step (-0.15) inside 16:00-19:00 -> control 3 kW vs BAU 4 kW, EV stays 0 kWh.
        _run_episode(env, [[-0.15], [-0.15], [-0.15]])
        with_bau = env.evaluate_v2(include_business_as_usual=True)
        without_bau = env.evaluate_v2(include_business_as_usual=False)

        assert not without_bau["cost_function"].str.contains("business_as_usual", na=False).any()
        d_with = _kpi_map(with_bau)
        d_without = _kpi_map(without_bau)
        assert d_without["district_energy_grid_window_average_power_control_kw"] == pytest.approx(3.0, abs=1.0e-6)
        assert d_with["district_energy_grid_window_average_power_control_kw"] == pytest.approx(3.0, abs=1.0e-6)
        assert d_with["district_energy_grid_window_average_power_business_as_usual_kw"] == pytest.approx(4.0, abs=1.0e-6)
        assert d_with["district_energy_grid_window_average_power_delta_to_business_as_usual_kw"] == pytest.approx(-1.0, abs=1.0e-6)
        assert d_with["district_ev_window_net_exchange_control_kwh"] == pytest.approx(0.0, abs=1.0e-9)
        assert d_without["district_ev_window_net_exchange_control_kwh"] == pytest.approx(0.0, abs=1.0e-9)
    finally:
        env.close()


def test_multi_community_signed_aggregation_cancellation_and_mismatch_guard(tmp_path: Path):
    # 1-hour window 16:00-17:00: Community A has 0 base load and charges EV +6 kWh (+6 kW);
    # Community B has 0 base load and discharges EV via V2G -6 kWh (-6 kW) with different community weight.
    schema_a = _write_synthetic_scenario(
        tmp_path / "comm_a",
        step_seconds=3600,
        start_clock_seconds=16 * 3600,
        num_steps=1,
        loads_kwh=[0.0],
        include_battery=False,
        include_ev=True,
        ev_capacity_kwh=30.0,
        ev_power_kw=10.0,
        ev_initial_soc=0.4,
        ev_required_soc_pct=40.0,
    )
    schema_b = _write_synthetic_scenario(
        tmp_path / "comm_b",
        step_seconds=3600,
        start_clock_seconds=16 * 3600,
        num_steps=1,
        loads_kwh=[0.0],
        include_battery=False,
        include_ev=True,
        ev_capacity_kwh=30.0,
        ev_power_kw=10.0,
        ev_initial_soc=0.6,
        ev_required_soc_pct=60.0,
    )

    portfolio = MultiCommunityEnv(
        communities=[
            {"community_id": "comm_a", "schema": str(schema_a), "weight": 1.0},
            {"community_id": "comm_b", "schema": str(schema_b), "weight": 4.0},
        ],
        render_directory=tmp_path / "mc_exports",
        render_session_name="signed_cancel",
        evaluation_window={"enabled": True, "start": "16:00", "end": "17:00"},
    )
    try:
        portfolio.reset(seed=0)
        portfolio.step({
            "comm_a": [np.array([0.6], dtype="float32")],   # +6 kWh AC draw
            "comm_b": [np.array([-0.6], dtype="float32")],  # -6 kWh V2G AC export
        })
        df = portfolio.evaluate_v2()
        p_kpis = _kpi_map(df, "portfolio")
        assert p_kpis["portfolio_ev_window_net_exchange_control_kwh"] == pytest.approx(0.0, abs=1.0e-6)
        assert p_kpis["portfolio_energy_grid_window_average_power_control_kw"] == pytest.approx(0.0, abs=1.0e-6)

        portfolio.export_final_kpis(export_business_as_usual_timeseries=False)
        mc_csv = tmp_path / "mc_exports" / "signed_cancel" / "exported_kpis_multi_community.csv"
        exported = pd.read_csv(mc_csv)
        p_rows = exported[exported["level"] == "portfolio"].set_index("cost_function")
        assert p_rows.loc["portfolio_energy_grid_window_average_power_control_kw", "unit"] == "kW"
        assert p_rows.loc["portfolio_ev_window_net_exchange_control_kwh", "unit"] == "kWh"
    finally:
        portfolio.close()

    with pytest.raises(ValueError, match="share the same evaluation_window"):
        MultiCommunityEnv(
            communities=[
                {
                    "community_id": "comm_a",
                    "schema": str(schema_a),
                    "env_kwargs": {"evaluation_window": {"start": "16:00", "end": "19:00"}},
                },
                {
                    "community_id": "comm_b",
                    "schema": str(schema_b),
                    "env_kwargs": {"evaluation_window": {"start": "17:00", "end": "20:00"}},
                },
            ]
        )


def test_manifest_provenance_and_compare_manifests_window_mismatch(tmp_path: Path):
    schema_path = _write_synthetic_scenario(
        tmp_path / "manifest_scenario",
        step_seconds=3600,
        start_clock_seconds=16 * 3600,
        num_steps=4,
    )

    def _export(session: str, win_cfg: Any, identity: str) -> Path:
        env = CityLearnEnv(
            str(schema_path),
            render_directory=tmp_path / "runs",
            render_session_name=session,
            export_kpis_on_episode_end=False,
            evaluation_window=win_cfg,
        )
        try:
            _run_episode(env)
            env.set_experiment_identity(identity, "1.0", {})
            env.export_final_kpis(export_business_as_usual_timeseries=False)
            return Path(env.new_folder_path) / "exported_kpis.csv"
        finally:
            env.close()

    csv_a = _export("run_a", True, "ctrl-a")
    csv_b = _export("run_b", {"enabled": True, "start": "16:00", "end": "19:00"}, "ctrl-b")
    csv_c = _export("run_c", {"enabled": True, "start": "17:00", "end": "20:00"}, "ctrl-c")
    csv_disabled = _export("run_disabled", None, "ctrl-disabled")

    manifest_a = json.loads(csv_a.with_name("exported_kpis.manifest.json").read_text(encoding="utf-8"))
    assert manifest_a["evaluation_window"] == {
        "enabled": True,
        "start": "16:00:00",
        "end": "19:00:00",
        "timezone": "scenario_local",
    }
    assert manifest_a["effective_schema"]["evaluation_window"] == manifest_a["evaluation_window"]
    assert manifest_a["comparison_context"]["evaluation_window"] == manifest_a["evaluation_window"]
    assert manifest_a["kpi_definitions"]["district_energy_grid_window_average_power_control_kw"]["unit"] == "kW"
    assert manifest_a["kpi_definitions"]["district_ev_window_net_exchange_control_kwh"]["unit"] == "kWh"

    paired_report = compare_exports(csv_a, csv_b)
    assert paired_report["status"] == "paired"
    assert paired_report["evaluation_window"]["status"] == "paired"
    assert paired_report["evaluation_window"]["comparable"] is True
    assert paired_report["unpaired_window_kpis"] == []

    mismatch_report = compare_exports(csv_a, csv_c)
    assert mismatch_report["status"] == "incompatible"
    assert "evaluation_window" in mismatch_report["mismatches"]
    assert mismatch_report["evaluation_window"]["status"] == "incompatible"
    assert mismatch_report["evaluation_window"]["comparable"] is False

    one_sided_report = compare_exports(csv_a, csv_disabled)
    assert one_sided_report["status"] == "paired"
    assert one_sided_report["permitted_claim"] == "controller_difference"
    assert one_sided_report["mismatches"] == []
    assert "evaluation_window_one_sided" in one_sided_report["declared_differences"]
    assert one_sided_report["evaluation_window"]["status"] == "one_sided"
    assert one_sided_report["evaluation_window"]["comparable"] is False
    assert set(one_sided_report["unpaired_window_kpis"]) >= {
        "district_energy_grid_window_average_power_control_kw",
        "district_energy_grid_window_average_power_business_as_usual_kw",
        "district_energy_grid_window_average_power_delta_to_business_as_usual_kw",
        "district_ev_window_net_exchange_control_kwh",
    }
    rows_by_key = {(r["name"], r["kpi"]): r for r in one_sided_report["kpis"]}
    assert rows_by_key[("District", "district_cost_total_control_eur")]["delta_right_minus_left"] == pytest.approx(0.0)
    win_row = rows_by_key[("District", "district_energy_grid_window_average_power_control_kw")]
    assert win_row["left"] is not None and win_row["right"] is None
    assert win_row["delta_right_minus_left"] is None
    assert win_row["window_status"] == "one_sided"

    tz_variant = deepcopy(manifest_a)
    tz_variant["comparison_context"]["evaluation_window"]["timezone"] = "Europe/Lisbon"
    tz_variant["controller_identity"]["name"] = "ctrl-tz"
    assert "evaluation_window" in compare_manifests(manifest_a, tz_variant)["mismatches"]


def test_cli_simulate_export_and_post_run_csv_exploration_snippet(tmp_path: Path):
    schema_path = _write_synthetic_scenario(
        tmp_path / "cli_scenario",
        step_seconds=3600,
        start_clock_seconds=0,
        num_steps=24,
        loads_kwh=[2.0 + 0.25 * (h % 6) for h in range(24)],
        include_battery=True,
        include_ev=True,
        ev_initial_soc=0.35,
        ev_required_soc_pct=85.0,
    )
    # Use BasicElectricVehicleRBC_ReferenceController so CLI simulation exercises active EV charging.
    schema_data = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_data["agent"] = {
        "type": "citylearn.agents.rbc.BasicElectricVehicleRBC_ReferenceController",
        "attributes": {},
    }
    schema_path.write_text(json.dumps(schema_data, indent=2), encoding="utf-8")

    out_root = tmp_path / "cli_out"
    ke_payload = json.dumps({
        "render_mode": "end",
        "render_directory": str(out_root),
        "render_session_name": "cli_win",
        "export_kpis_on_episode_end": True,
        "evaluation_window": {"enabled": True, "start": "16:00", "end": "19:00"},
    })
    subprocess.run(
        [
            sys.executable,
            "-m",
            "citylearn",
            "simulate",
            str(schema_path),
            "-d",
            str(tmp_path / "sim_work"),
            "-ke",
            ke_payload,
            "evaluate",
        ],
        check=True,
        cwd=str(tmp_path),
    )

    export_dir = out_root / "cli_win"
    exported_kpis = pd.read_csv(export_dir / "exported_kpis.csv").set_index("KPI")
    manifest = json.loads((export_dir / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
    assert manifest["evaluation_window"] == {
        "enabled": True,
        "start": "16:00:00",
        "end": "19:00:00",
        "timezone": "scenario_local",
    }

    # Execute the exact post-run CSV exploration snippet documented in docs/kpis_reference.md.
    ref_doc = (ROOT / "docs" / "kpis_reference.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)\n```", ref_doc, re.S)
    post_run_block = next(b for b in blocks if "exported_data_community_ep0.csv" in b)
    executable = post_run_block.replace('Path("render_logs/my_session")', f"Path({str(export_dir)!r})")
    scope: Dict[str, Any] = {}
    exec(compile(executable, "kpis_reference_post_run.py", "exec"), scope)

    assert scope["control_kw"] == pytest.approx(
        float(exported_kpis.loc["district_energy_grid_window_average_power_control_kw", "District"]),
        abs=1.0e-6,
    )
    assert scope["bau_kw"] == pytest.approx(
        float(exported_kpis.loc["district_energy_grid_window_average_power_business_as_usual_kw", "District"]),
        abs=1.0e-6,
    )
    assert scope["delta_kw"] == pytest.approx(
        float(exported_kpis.loc["district_energy_grid_window_average_power_delta_to_business_as_usual_kw", "District"]),
        abs=1.0e-6,
    )
    assert scope["ev_net_kwh"] == pytest.approx(
        float(exported_kpis.loc["district_ev_window_net_exchange_control_kwh", "District"]),
        abs=1.0e-6,
    )


@pytest.mark.parametrize(
    "bad_config",
    [
        "16:00-19:00",
        {"enabled": True, "start": "25:00", "end": "19:00"},
        {"enabled": True, "start": "16:60", "end": "19:00"},
        {"enabled": True, "start": "16:00", "end": "16:00"},
        {"enabled": True, "unknown_key": 1},
        {"enabled": True, "timezone": "Invalid/NoSuchZone"},
    ],
)
def test_invalid_evaluation_window_configs_fail_early(tmp_path: Path, bad_config: Any):
    schema_path = _write_synthetic_scenario(tmp_path / "invalid_cfg", num_steps=2)
    with pytest.raises(ValueError):
        CityLearnEnv(str(schema_path), evaluation_window=bad_config)
