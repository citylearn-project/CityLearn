"""Regression tests for opt-in district feeder limit exceedance monitoring (#334)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.agents.baseline import RBCSmartPolicy
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.comparison import compare_exports, compare_manifests
from citylearn.multi_community import MultiCommunityEnv

ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_SCHEMA = ROOT / "tests" / "data" / "minute_ev_demo" / "schema.json"
PT_REC_4_SCHEMA = ROOT / "data" / "datasets" / "pt_rec_4" / "schema.json"


def _write_synthetic_feeder_scenario(
    folder: Path,
    *,
    step_seconds: int = 900,
    loads_kwh: Sequence[float] = (3.5, 0.5, 1.25, 0.5),
    solar_kwh: Sequence[float] = (0.0, 2.5, 0.0, 3.5),
    battery_capacity_kwh: float = 20.0,
    battery_power_kw: float = 20.0,
    battery_initial_soc: float = 0.5,
    district_electrical_service: Optional[Dict[str, Any]] = None,
) -> Path:
    """Create a deterministic single-building CSV scenario with exact settled powers."""
    folder.mkdir(parents=True, exist_ok=True)
    num_steps = len(loads_kwh)
    n_rows = num_steps + 1
    loads = list(loads_kwh) + [loads_kwh[-1]]
    solars = list(solar_kwh) + [solar_kwh[-1]]

    b_rows: List[Dict[str, Any]] = []
    for idx in range(n_rows):
        sec_of_day = (16 * 3600 + idx * step_seconds) % 86400
        hour = (sec_of_day // 3600) + 1
        minute = (sec_of_day % 3600) // 60
        row: Dict[str, Any] = {
            "month": 7,
            "hour": int(hour),
            "minutes": int(minute),
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
        }
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
        "observations": {
            "month": {"active": True, "shared_in_central_agent": True},
            "day_type": {"active": True, "shared_in_central_agent": True},
            "hour": {"active": True, "shared_in_central_agent": True},
            "minutes": {"active": True, "shared_in_central_agent": True},
            "non_shiftable_load": {"active": True, "shared_in_central_agent": False},
            "solar_generation": {"active": True, "shared_in_central_agent": False},
            "electrical_storage_soc": {"active": True, "shared_in_central_agent": False},
            "net_electricity_consumption": {"active": True, "shared_in_central_agent": False},
            "electricity_pricing": {"active": True, "shared_in_central_agent": True},
            "carbon_intensity": {"active": True, "shared_in_central_agent": True},
        },
        "actions": {
            "electrical_storage": {"active": True},
        },
        "agent": {
            "type": "citylearn.agents.baseline.ZeroActionAgent",
            "attributes": {},
        },
        "reward_function": {
            "type": "citylearn.reward_function.RewardFunction",
            "attributes": {},
        },
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
                    "attributes": {"nominal_power": 1.0, "generation_mode": "absolute"},
                },
                "electrical_storage": {
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
                },
            }
        },
    }
    if district_electrical_service is not None:
        schema["district_electrical_service"] = district_electrical_service

    schema_path = folder / "schema.json"
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema_path


def _district_kpis(df: pd.DataFrame) -> Dict[str, float]:
    sub = df[df["level"] == "district"]
    return {
        str(row["cost_function"]): (np.nan if row["value"] is None else float(row["value"]))
        for _, row in sub.iterrows()
    }


def test_default_disabled_parity_and_empty_post_reset_histories(tmp_path: Path):
    tables = {}
    manifests = {}
    for label, cfg in (("unset", None), ("disabled", {"enabled": False, "limits": {"import_kw": 2.0}})):
        kwargs: Dict[str, Any] = {
            "central_agent": True,
            "episode_time_steps": 5,
            "render_mode": "none",
            "render_directory": tmp_path / "exports",
            "render_session_name": label,
            "export_kpis_on_episode_end": False,
            "random_seed": 0,
        }
        if cfg is not None:
            kwargs["district_electrical_service"] = cfg
        env = CityLearnEnv(str(MINUTE_EV_SCHEMA), **kwargs)
        try:
            env.reset(seed=0)
            assert env.feeder_import_exceedance_kw.shape == (0,)
            assert env.feeder_export_exceedance_kw.shape == (0,)
            while not env.terminated:
                env.step([np.zeros(len(env.action_names[0]), dtype="float32")])
            assert np.array_equal(env.feeder_import_exceedance_kw, np.zeros(4, dtype="float64"))
            assert np.array_equal(env.feeder_export_exceedance_kw, np.zeros(4, dtype="float64"))
            df = env.evaluate_v2()
            assert not df["cost_function"].str.contains("feeder_limit").any()
            tables[label] = df
            env.set_experiment_identity(f"ctrl-{label}", "1.0", {})
            env.export_final_kpis(export_business_as_usual_timeseries=False)
            out_dir = Path(env.new_folder_path)
            manifests[label] = json.loads((out_dir / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
        finally:
            env.close()

    pd.testing.assert_frame_equal(tables["unset"], tables["disabled"])
    assert (
        manifests["unset"]["comparison_context"]["physical_configuration_sha256"]
        == manifests["disabled"]["comparison_context"]["physical_configuration_sha256"]
    )
    assert compare_manifests(manifests["unset"], manifests["disabled"])["status"] == "paired"


def test_simulation_invariance_under_tight_scalar_and_schedule_feeder_limits(tmp_path: Path):
    # 1) Bundled minute_ev_demo with RBCSmartPolicy and rendered CSV exports under tight exceeded limits.
    def _run_minute_demo(session: str, feeder_cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "central_agent": True,
            "episode_time_steps": 8,
            "render_mode": "end",
            "render_directory": tmp_path / "invariance",
            "render_session_name": session,
            "export_kpis_on_episode_end": True,
            "physics_invariant_checks": True,
            "random_seed": 0,
        }
        if feeder_cfg is not None:
            kwargs["district_electrical_service"] = feeder_cfg
        env = CityLearnEnv(str(MINUTE_EV_SCHEMA), **kwargs)
        try:
            agent = RBCSmartPolicy(env)
            obs, _ = env.reset(seed=0)
            chosen_actions = []
            step_obs = [copy.deepcopy(obs)]
            while not env.terminated:
                act = agent.predict(obs)
                chosen_actions.append([np.asarray(a, dtype="float32").copy() for a in act])
                obs, _, _, _, _ = env.step(act)
                step_obs.append(copy.deepcopy(obs))
            kpis = env.evaluate_v2()
            b1 = env.buildings[0]
            charger = b1.electric_vehicle_chargers[0]
            ev = env.electric_vehicles[0]
            out_dir = Path(env.new_folder_path)
            return {
                "actions": chosen_actions,
                "obs": step_obs,
                "rewards": copy.deepcopy(env.rewards),
                "district_net": list(env.net_electricity_consumption),
                "district_cost": list(env.net_electricity_consumption_cost),
                "district_emissions": list(env.net_electricity_consumption_emission),
                "building_net": np.asarray(b1.net_electricity_consumption).copy(),
                "bess_soc": np.asarray(b1.electrical_storage.soc).copy(),
                "bess_energy": np.asarray(b1.electrical_storage.electricity_consumption).copy(),
                "charger_energy": np.asarray(charger.electricity_consumption).copy(),
                "ev_soc": np.asarray(ev.battery.soc).copy(),
                "imp_exc": env.feeder_import_exceedance_kw.copy(),
                "exp_exc": env.feeder_export_exceedance_kw.copy(),
                "kpis": kpis,
                "community_csv": (out_dir / "exported_data_community_ep0.csv").read_text(encoding="utf-8"),
                "bau_csv": (out_dir / "exported_data_business_as_usual_ep0.csv").read_text(encoding="utf-8"),
            }
        finally:
            env.close()

    base = _run_minute_demo("without_limits", None)
    monitored = _run_minute_demo(
        "with_tight_limits",
        {
            "enabled": True,
            "limits": {
                "import_kw": [0.5, 0.25, 0.5, 0.25, 0.5, 0.25, 0.5],
                "export_kw": 0.0,
            },
        },
    )

    for a_step, b_step in zip(base["actions"], monitored["actions"]):
        assert np.array_equal(a_step[0], b_step[0])
    for a_obs, b_obs in zip(base["obs"], monitored["obs"]):
        assert np.array_equal(np.asarray(a_obs[0]), np.asarray(b_obs[0]))
    assert base["rewards"] == monitored["rewards"]
    assert base["district_net"] == monitored["district_net"]
    assert base["district_cost"] == monitored["district_cost"]
    assert base["district_emissions"] == monitored["district_emissions"]
    assert np.array_equal(base["building_net"], monitored["building_net"])
    assert np.array_equal(base["bess_soc"], monitored["bess_soc"])
    assert np.array_equal(base["bess_energy"], monitored["bess_energy"])
    assert np.array_equal(base["charger_energy"], monitored["charger_energy"])
    assert np.array_equal(base["ev_soc"], monitored["ev_soc"])
    assert base["community_csv"] == monitored["community_csv"]
    assert base["bau_csv"] == monitored["bau_csv"]
    assert np.any(monitored["imp_exc"] > 0.0)

    monitored_non_feeder = monitored["kpis"][
        ~monitored["kpis"]["cost_function"].str.contains("feeder_limit")
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(base["kpis"].reset_index(drop=True), monitored_non_feeder)

    # 2) Bundled pt_rec_4 (entity interface + community market + EVs + deferrable appliances) bit-identical dispatch.
    pytest.importorskip("pyarrow")
    runs_rec4 = {}
    for label, feeder_cfg in (
        ("off", None),
        ("on", {"enabled": True, "limits": {"import_kw": 0.5, "export_kw": 0.1}}),
    ):
        kwargs_rec4: Dict[str, Any] = {
            "simulation_start_time_step": 0,
            "simulation_end_time_step": 16,
            "physics_invariant_checks": True,
            "random_seed": 2023,
        }
        if feeder_cfg is not None:
            kwargs_rec4["district_electrical_service"] = feeder_cfg
        env = CityLearnEnv(str(PT_REC_4_SCHEMA), **kwargs_rec4)
        try:
            agent = RBCSmartPolicy(env)
            obs, _ = env.reset(seed=2023)
            while not env.terminated:
                obs, _, _, _, _ = env.step(agent.predict(obs))
            runs_rec4[label] = {
                "net": list(env.net_electricity_consumption),
                "cost": list(env.net_electricity_consumption_cost),
                "emissions": list(env.net_electricity_consumption_emission),
                "imp_exc": env.feeder_import_exceedance_kw.copy(),
                "kpis": env.evaluate_v2(include_business_as_usual=False),
            }
        finally:
            env.close()

    assert runs_rec4["off"]["net"] == runs_rec4["on"]["net"]
    assert runs_rec4["off"]["cost"] == runs_rec4["on"]["cost"]
    assert runs_rec4["off"]["emissions"] == runs_rec4["on"]["emissions"]
    assert np.any(runs_rec4["on"]["imp_exc"] > 0.0)
    on_non_feeder = runs_rec4["on"]["kpis"][
        ~runs_rec4["on"]["kpis"]["cost_function"].str.contains("feeder_limit")
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(runs_rec4["off"]["kpis"].reset_index(drop=True), on_non_feeder)


def test_per_step_exceedance_series_and_kpi_identities_with_bau_comparison(tmp_path: Path):
    # 4 quarter-hour steps (0.25 h each) starting at 16:00 local:
    # Step 0: load 3.5 kWh, solar 0.0 -> passive net +3.5 kWh (+14 kW)
    # Step 1: load 0.5 kWh, solar 2.5 -> passive net -2.0 kWh ( -8 kW)
    # Step 2: load 1.25 kWh, solar 0.0 -> passive net +1.25 kWh ( +5 kW)
    # Step 3: load 0.5 kWh, solar 3.5 -> passive net -3.0 kWh (-12 kW)
    schema_path = _write_synthetic_feeder_scenario(
        tmp_path / "exact_kpis",
        step_seconds=900,
        loads_kwh=(3.5, 0.5, 1.25, 0.5),
        solar_kwh=(0.0, 2.5, 0.0, 3.5),
        battery_capacity_kwh=20.0,
        battery_power_kw=20.0,
        battery_initial_soc=0.5,
    )
    feeder_cfg = {"enabled": True, "limits": {"import_kw": 6.0, "export_kw": 5.0}}

    # Controller action (nominal_power=20 kW -> 5 kWh max per 0.25 h step):
    # Step 0: discharge -1.0 kWh (action -0.20) -> net +2.5 kWh (+10 kW; import exc = 4 kW)
    # Step 1: charge +0.5 kWh (action +0.10)    -> net -1.5 kWh ( -6 kW; export exc = 1 kW)
    # Step 2: 0.0                               -> net +1.25 kWh ( +5 kW; import exc = 0 kW)
    # Step 3: 0.0                               -> net -3.0 kWh (-12 kW; export exc = 7 kW)
    actions = [[-0.20], [0.10], [0.0], [0.0]]

    env = CityLearnEnv(str(schema_path), district_electrical_service=feeder_cfg)
    try:
        env.reset(seed=0)
        assert env.feeder_import_exceedance_kw.shape == (0,)
        assert env.feeder_export_exceedance_kw.shape == (0,)

        for step_idx, act in enumerate(actions, start=1):
            env.step([np.asarray(act, dtype="float32")])
            assert env.feeder_import_exceedance_kw.shape == (step_idx,)
            assert env.feeder_export_exceedance_kw.shape == (step_idx,)

        assert env.feeder_import_exceedance_kw == pytest.approx([4.0, 0.0, 0.0, 0.0], abs=1.0e-5)
        assert env.feeder_export_exceedance_kw == pytest.approx([0.0, 1.0, 0.0, 7.0], abs=1.0e-5)

        without_bau = env.evaluate_v2(include_business_as_usual=False)
        assert not without_bau["cost_function"].str.contains("business_as_usual", na=False).any()
        d_no_bau = _district_kpis(without_bau)
        assert d_no_bau["district_energy_grid_feeder_limit_import_exceedance_energy_total_control_kwh"] == pytest.approx(1.0, abs=1.0e-5)
        assert d_no_bau["district_energy_grid_feeder_limit_import_exceedance_peak_control_kw"] == pytest.approx(4.0, abs=1.0e-5)
        assert d_no_bau["district_energy_grid_feeder_limit_import_exceedance_step_control_count"] == pytest.approx(1.0)
        assert d_no_bau["district_energy_grid_feeder_limit_export_exceedance_energy_total_control_kwh"] == pytest.approx(2.0, abs=1.0e-5)
        assert d_no_bau["district_energy_grid_feeder_limit_export_exceedance_peak_control_kw"] == pytest.approx(7.0, abs=1.0e-5)
        assert d_no_bau["district_energy_grid_feeder_limit_export_exceedance_step_control_count"] == pytest.approx(2.0)

        with_bau = env.evaluate_v2(include_business_as_usual=True)
        d_bau = _district_kpis(with_bau)
        for direction in ("import", "export"):
            for metric, unit in (
                ("exceedance_energy_total", "kwh"),
                ("exceedance_peak", "kw"),
                ("exceedance_step", "count"),
            ):
                prefix = f"district_energy_grid_feeder_limit_{direction}_{metric}"
                c_val = d_bau[f"{prefix}_control_{unit}"]
                b_val = d_bau[f"{prefix}_business_as_usual_{unit}"]
                delta_val = d_bau[f"{prefix}_delta_to_business_as_usual_{unit}"]
                assert np.isfinite(b_val)
                assert delta_val == pytest.approx(c_val - b_val, abs=1.0e-6)

    finally:
        env.close()


def test_business_as_usual_feeder_exceedance_matches_sidecar_net_consumption(tmp_path: Path):
    # A 1 kW battery cannot cancel the loads, so the BAU sidecar imports and exports above the limits.
    schema_path = _write_synthetic_feeder_scenario(
        tmp_path / "bau_values",
        step_seconds=900,
        loads_kwh=(3.5, 0.5, 1.25, 0.5),
        solar_kwh=(0.0, 2.5, 0.0, 3.5),
        battery_capacity_kwh=1.0,
        battery_power_kw=1.0,
        battery_initial_soc=0.5,
    )
    import_kw, export_kw, step_hours = 2.0, 2.0, 0.25
    feeder_cfg = {"enabled": True, "limits": {"import_kw": import_kw, "export_kw": export_kw}}

    env = CityLearnEnv(str(schema_path), district_electrical_service=feeder_cfg)
    try:
        env.reset(seed=0)

        for _ in range(4):
            env.step([np.asarray([0.0], dtype="float32")])

        d_bau = _district_kpis(env.evaluate_v2(include_business_as_usual=True))
        bau_env = env.run_business_as_usual_baseline().env
        bau_power_kw = np.asarray(bau_env.net_electricity_consumption, dtype="float64")[:4] / step_hours
        expected = {
            "import": np.maximum(bau_power_kw - import_kw, 0.0),
            "export": np.maximum(-bau_power_kw - export_kw, 0.0),
        }
        assert expected["import"].sum() + expected["export"].sum() > 0.0

        for direction, series in expected.items():
            assert getattr(bau_env, f"feeder_{direction}_exceedance_kw") == pytest.approx(series, abs=1.0e-5)
            prefix = f"district_energy_grid_feeder_limit_{direction}_exceedance"
            assert d_bau[f"{prefix}_energy_total_business_as_usual_kwh"] == pytest.approx(series.sum() * step_hours, abs=1.0e-5)
            assert d_bau[f"{prefix}_peak_business_as_usual_kw"] == pytest.approx(series.max(), abs=1.0e-5)
            assert d_bau[f"{prefix}_step_business_as_usual_count"] == pytest.approx(float(np.count_nonzero(series > 1.0e-9)))
    finally:
        env.close()


def test_single_direction_configured_emits_nan_for_unconfigured_direction(tmp_path: Path):
    schema_path = _write_synthetic_feeder_scenario(tmp_path / "one_dir")

    # Import limit only (via limits.total alias) -> export exceedance KPIs are NaN while time-series is 0.0.
    env_imp = CityLearnEnv(
        str(schema_path),
        district_electrical_service={"enabled": True, "limits": {"total": {"import_kw": 6.0}}},
    )
    try:
        env_imp.reset(seed=0)
        while not env_imp.terminated:
            env_imp.step([np.zeros(1, dtype="float32")])
        assert env_imp.feeder_import_exceedance_kw == pytest.approx([8.0, 0.0, 0.0, 0.0], abs=1.0e-5)
        assert np.array_equal(env_imp.feeder_export_exceedance_kw, np.zeros(4, dtype="float64"))
        d_imp = _district_kpis(env_imp.evaluate_v2(include_business_as_usual=True))
        assert d_imp["district_energy_grid_feeder_limit_import_exceedance_energy_total_control_kwh"] == pytest.approx(2.0, abs=1.0e-5)
        for variant in ("control", "business_as_usual", "delta_to_business_as_usual"):
            for metric, unit in (
                ("exceedance_energy_total", "kwh"),
                ("exceedance_peak", "kw"),
                ("exceedance_step", "count"),
            ):
                assert np.isnan(d_imp[f"district_energy_grid_feeder_limit_export_{metric}_{variant}_{unit}"])
    finally:
        env_imp.close()

    # Export limit only -> import exceedance KPIs are NaN while export exceedance KPIs are finite.
    env_exp = CityLearnEnv(
        str(schema_path),
        district_electrical_service={"enabled": True, "limits": {"export_kw": 5.0}},
    )
    try:
        env_exp.reset(seed=0)
        while not env_exp.terminated:
            env_exp.step([np.zeros(1, dtype="float32")])
        assert np.array_equal(env_exp.feeder_import_exceedance_kw, np.zeros(4, dtype="float64"))
        assert env_exp.feeder_export_exceedance_kw == pytest.approx([0.0, 3.0, 0.0, 7.0], abs=1.0e-5)
        d_exp = _district_kpis(env_exp.evaluate_v2(include_business_as_usual=True))
        assert d_exp["district_energy_grid_feeder_limit_export_exceedance_energy_total_control_kwh"] == pytest.approx(2.5, abs=1.0e-5)
        for variant in ("control", "business_as_usual", "delta_to_business_as_usual"):
            for metric, unit in (
                ("exceedance_energy_total", "kwh"),
                ("exceedance_peak", "kw"),
                ("exceedance_step", "count"),
            ):
                assert np.isnan(d_exp[f"district_energy_grid_feeder_limit_import_{metric}_{variant}_{unit}"])
    finally:
        env_exp.close()


def test_dataset_step_zero_anchored_schedules_episode_splits_and_validation(tmp_path: Path):
    # 6 steps (0..5) at 1 h resolution with constant 10 kW load and 0 PV.
    schema_path = _write_synthetic_feeder_scenario(
        tmp_path / "schedule_splits",
        step_seconds=3600,
        loads_kwh=(10.0, 10.0, 10.0, 10.0, 10.0, 10.0),
        solar_kwh=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    # Dataset-step-0 anchored import schedule: [100, 100, 7, 4, None, 8] kW.
    # Consecutive splits with episode_time_steps=4 (3 executed steps per episode, shared boundary):
    # Episode 0 executes dataset steps 0, 1, 2 -> limits [100, 100, 7] -> exceedances [0, 0, 3].
    # Episode 1 executes dataset steps 3, 4, 5 -> limits [4, None, 8]  -> exceedances [6, 0, 2].
    schedule_cfg = {
        "enabled": True,
        "limits": {
            "import_kw": [100.0, 100.0, 7.0, 4.0, None, 8.0],
        },
    }
    env = CityLearnEnv(
        str(schema_path),
        episode_time_steps=4,
        district_electrical_service=schedule_cfg,
    )
    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step([np.zeros(1, dtype="float32")])
        assert env.feeder_import_exceedance_kw == pytest.approx([0.0, 0.0, 3.0], abs=1.0e-5)

        env.reset()
        while not env.terminated:
            env.step([np.zeros(1, dtype="float32")])
        assert env.feeder_import_exceedance_kw == pytest.approx([6.0, 0.0, 2.0], abs=1.0e-5)
        d_ep1 = _district_kpis(env.evaluate_v2(include_business_as_usual=True))
        assert d_ep1["district_energy_grid_feeder_limit_import_exceedance_energy_total_control_kwh"] == pytest.approx(8.0, abs=1.0e-5)
        assert d_ep1["district_energy_grid_feeder_limit_import_exceedance_peak_control_kw"] == pytest.approx(6.0, abs=1.0e-5)
        assert d_ep1["district_energy_grid_feeder_limit_import_exceedance_step_control_count"] == pytest.approx(2.0)
    finally:
        env.close()

    with pytest.raises(TypeError, match="did you mean 'district_electrical_service'"):
        CityLearnEnv(str(schema_path), district_electrical_services=schedule_cfg)

    for bad_cfg in (
        "invalid",
        {"enabled": True, "unknown": 1},
        {"enabled": True, "limits": {"bad_key": 1.0}},
        {"enabled": True, "limits": {"import_kw": -1.0}},
        {"enabled": True, "limits": {"import_kw": True}},
        {"enabled": True, "limits": {"import_kw": float("nan")}},
        {"enabled": True, "limits": {"import_kw": []}},
        {"enabled": True, "limits": {"import_kw": [10.0, 10.0, 10.0]}},  # too short for 6 executed steps
    ):
        with pytest.raises(ValueError):
            CityLearnEnv(str(schema_path), district_electrical_service=bad_cfg)


def test_manifest_provenance_comparison_multi_community_and_deepcopy(tmp_path: Path):
    schema_path = _write_synthetic_feeder_scenario(tmp_path / "prov_scenario")

    def _export(session: str, cfg: Optional[Dict[str, Any]], identity: str) -> Path:
        kwargs: Dict[str, Any] = {
            "render_directory": tmp_path / "exports",
            "render_session_name": session,
            "export_kpis_on_episode_end": False,
        }
        if cfg is not None:
            kwargs["district_electrical_service"] = cfg
        env = CityLearnEnv(str(schema_path), **kwargs)
        try:
            env.reset(seed=0)
            while not env.terminated:
                env.step([np.zeros(1, dtype="float32")])
            env.set_experiment_identity(identity, "1.0", {})
            env.export_final_kpis(export_business_as_usual_timeseries=False)
            return Path(env.new_folder_path) / "exported_kpis.csv"
        finally:
            env.close()

    csv_direct = _export("direct", {"enabled": True, "limits": {"import_kw": 6.0, "export_kw": 5.0}}, "ctrl-a")
    csv_alias = _export(
        "alias",
        {"enabled": True, "limits": {"total": {"import_kw": 6.0, "export_kw": 5.0}}},
        "ctrl-b",
    )
    csv_diff = _export("diff", {"enabled": True, "limits": {"import_kw": 8.0, "export_kw": 5.0}}, "ctrl-c")

    manifest = json.loads(csv_direct.with_name("exported_kpis.manifest.json").read_text(encoding="utf-8"))
    expected_effective = {"enabled": True, "limits": {"import_kw": 6.0, "export_kw": 5.0}}
    assert manifest["district_electrical_service"] == expected_effective
    assert manifest["effective_schema"]["district_electrical_service"] == expected_effective
    assert manifest["comparison_context"]["district_electrical_service"] == expected_effective
    assert (
        manifest["kpi_definitions"][
            "district_energy_grid_feeder_limit_import_exceedance_energy_total_control_kwh"
        ]["unit"]
        == "kWh"
    )
    assert (
        manifest["kpi_definitions"][
            "district_energy_grid_feeder_limit_import_exceedance_peak_control_kw"
        ]["unit"]
        == "kW"
    )

    assert compare_exports(csv_direct, csv_alias)["status"] == "paired"
    mismatch = compare_exports(csv_direct, csv_diff)
    assert mismatch["status"] == "incompatible"
    assert "district_electrical_service" in mismatch["mismatches"]

    # MultiCommunityEnv portfolio sums _kwh and _count feeder exceedance KPIs and omits _kw peaks.
    portfolio = MultiCommunityEnv(
        communities=[
            {
                "community_id": "c1",
                "schema": str(schema_path),
                "env_kwargs": {"district_electrical_service": {"enabled": True, "limits": {"import_kw": 6.0, "export_kw": 5.0}}},
            },
            {
                "community_id": "c2",
                "schema": str(schema_path),
                "env_kwargs": {"district_electrical_service": {"enabled": True, "limits": {"import_kw": 6.0, "export_kw": 5.0}}},
            },
        ]
    )
    try:
        portfolio.reset(seed=0)
        while not portfolio.terminated:
            portfolio.step({"c1": [np.zeros(1, dtype="float32")], "c2": [np.zeros(1, dtype="float32")]})
        mc_df = portfolio.evaluate_v2(include_business_as_usual=False)
        p_rows = mc_df[mc_df["level"] == "portfolio"].set_index("cost_function")["value"]
        assert float(p_rows["portfolio_energy_grid_feeder_limit_import_exceedance_energy_total_control_kwh"]) == pytest.approx(4.0, abs=1.0e-5)
        assert float(p_rows["portfolio_energy_grid_feeder_limit_import_exceedance_step_control_count"]) == pytest.approx(2.0)
        assert "portfolio_energy_grid_feeder_limit_import_exceedance_peak_control_kw" not in p_rows.index
    finally:
        portfolio.close()

    # copy.deepcopy mid-episode preserves independent feeder exceedance histories.
    env_orig = CityLearnEnv(
        str(schema_path),
        district_electrical_service={"enabled": True, "limits": {"import_kw": 6.0, "export_kw": 5.0}},
    )
    try:
        env_orig.reset(seed=0)
        env_orig.step([np.zeros(1, dtype="float32")])  # step 0: +8 kW import exceedance
        env_clone = copy.deepcopy(env_orig)
        try:
            env_orig.step([np.zeros(1, dtype="float32")])     # step 1 passive: +3 kW export exceedance
            env_clone.step([np.array([0.4], dtype="float32")])  # step 1 +2 kWh charge (+8 kW) -> 0 export exceedance
            assert env_orig.feeder_export_exceedance_kw == pytest.approx([0.0, 3.0], abs=1.0e-5)
            assert env_clone.feeder_export_exceedance_kw == pytest.approx([0.0, 0.0], abs=1.0e-5)
        finally:
            env_clone.close()
    finally:
        env_orig.close()


@pytest.mark.parametrize(
    "cfg",
    [
        {"enabled": True},
        {"enabled": True, "limits": {}},
        {"enabled": True, "limits": None},
        {"enabled": True, "limits": {"import_kw": None, "export_kw": None}},
        {"enabled": True, "limits": {"import_kw": float("inf"), "export_kw": float("inf")}},
        {"enabled": True, "limits": {"total": {}}},
    ],
)
def test_enabled_without_any_limit_is_rejected(tmp_path: Path, cfg):
    # Every feeder KPI would be NaN: an unconfigured direction is undefined.
    schema_path = _write_synthetic_feeder_scenario(tmp_path / "no_limit")
    with pytest.raises(ValueError, match="enabled but has no limit"):
        CityLearnEnv(str(schema_path), district_electrical_service=cfg)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["district_electrical_service"] = cfg
    with pytest.raises(ValueError, match="enabled but has no limit"):
        CityLearnEnv(schema)


def test_disabled_or_single_direction_feeder_without_limits_is_still_accepted(tmp_path: Path):
    schema_path = _write_synthetic_feeder_scenario(tmp_path / "accepted")
    for cfg in (
        {"enabled": False},
        {"enabled": False, "limits": {}},
        {"enabled": True, "limits": {"export_kw": 5.0}},
        {"enabled": True, "limits": {"import_kw": [None, None, None, None, None]}},
    ):
        env = CityLearnEnv(str(schema_path), district_electrical_service=cfg)
        env.close()


def test_one_sided_feeder_monitor_is_a_declared_difference(tmp_path: Path):
    """The feeder monitor changes nothing simulated, so it follows the one-sided evaluation window rule."""
    schema_path = _write_synthetic_feeder_scenario(tmp_path / "one_sided")

    def _export(session: str, cfg: Optional[Dict[str, Any]]) -> Path:
        kwargs: Dict[str, Any] = {
            "render_directory": tmp_path / "exports",
            "render_session_name": session,
            "export_kpis_on_episode_end": False,
        }
        if cfg is not None:
            kwargs["district_electrical_service"] = cfg
        env = CityLearnEnv(str(schema_path), **kwargs)
        try:
            env.reset(seed=0)
            while not env.terminated:
                env.step([np.zeros(1, dtype="float32")])
            env.set_experiment_identity("zero", "1.0", {})
            env.export_final_kpis(export_business_as_usual_timeseries=False)
            return Path(env.new_folder_path) / "exported_kpis.csv"
        finally:
            env.close()

    def _manifest(csv: Path) -> Dict[str, Any]:
        return json.loads(csv.with_name("exported_kpis.manifest.json").read_text(encoding="utf-8"))

    limits_a = {"enabled": True, "limits": {"import_kw": 6.0, "export_kw": 5.0}}
    limits_b = {"enabled": True, "limits": {"import_kw": 8.0, "export_kw": 5.0}}
    csv_off = _export("off", None)
    csv_on = _export("on", limits_a)
    csv_on_again = _export("on_again", limits_a)
    csv_other = _export("other", limits_b)

    # The monitor is not part of the physical configuration hash.
    hashes = {
        _manifest(csv)["comparison_context"]["physical_configuration_sha256"]
        for csv in (csv_off, csv_on, csv_other)
    }
    assert len(hashes) == 1

    for left, right in ((csv_off, csv_on), (csv_on, csv_off)):
        report = compare_exports(left, right)
        assert report["status"] == "paired"
        assert report["mismatches"] == []
        assert "district_electrical_service_one_sided" in report["declared_differences"]
        assert report["district_electrical_service"]["status"] == "one_sided"
        assert report["district_electrical_service"]["comparable"] is False
        assert report["unpaired_feeder_kpis"]
        assert all("_energy_grid_feeder_limit_" in name for name in report["unpaired_feeder_kpis"])
        shared = [r for r in report["kpis"] if "_energy_grid_feeder_limit_" not in r["kpi"]]
        assert shared and all("feeder_status" not in r for r in shared)
        assert all(
            r["delta_right_minus_left"] in (None, 0.0) for r in shared
        ), "a monitor-only setting must not change any shared KPI"

    paired = compare_exports(csv_on, csv_on_again)
    assert paired["status"] == "paired"
    assert paired["district_electrical_service"]["status"] == "paired"
    assert "district_electrical_service_one_sided" not in paired["declared_differences"]
    assert paired["unpaired_feeder_kpis"] == []

    disabled = compare_manifests(_manifest(csv_off), _manifest(csv_off))
    assert disabled["district_electrical_service"]["status"] == "disabled"
    assert disabled["declared_differences"] == []

    mismatch = compare_exports(csv_on, csv_other)
    assert mismatch["status"] == "incompatible"
    assert mismatch["mismatches"] == ["district_electrical_service"]
    assert mismatch["district_electrical_service"]["status"] == "incompatible"
