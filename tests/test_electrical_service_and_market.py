import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from private_access import charging_constraint_last_penalty_kwh, charging_constraints_state

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


MINUTE_DATASET_DIR = Path(__file__).resolve().parents[1] / "tests" / "data" / "minute_ev_demo"


def _clone_minute_schema(tmp_path: Path, name: str, mutator=None) -> Path:
    dataset_dir = tmp_path / name
    shutil.copytree(MINUTE_DATASET_DIR, dataset_dir)
    schema_path = dataset_dir / "schema.json"

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    if mutator is not None:
        mutator(schema)

    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    return schema_path


def _rollout_zero_actions(env: CityLearnEnv):
    env.reset()

    while not env.terminated:
        action = np.zeros(len(env.action_names[0]), dtype="float32")
        env.step([action])


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


def test_disabled_community_market_keeps_legacy_costs(tmp_path: Path):
    baseline_schema = _clone_minute_schema(tmp_path, "baseline")
    disabled_schema = _clone_minute_schema(
        tmp_path,
        "disabled_market",
        mutator=lambda s: s.update(
            {
                "community_market": {
                    "enabled": False,
                    "intra_community_sell_ratio": 0.2,
                    "grid_export_price": 0.9,
                }
            }
        ),
    )

    env_baseline = CityLearnEnv(str(baseline_schema), central_agent=True, episode_time_steps=4, random_seed=0)
    env_disabled = CityLearnEnv(str(disabled_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        _rollout_zero_actions(env_baseline)
        _rollout_zero_actions(env_disabled)

        np.testing.assert_allclose(
            np.asarray(env_baseline.net_electricity_consumption_cost, dtype="float64"),
            np.asarray(env_disabled.net_electricity_consumption_cost, dtype="float64"),
            rtol=1e-9,
            atol=1e-9,
        )
    finally:
        env_baseline.close()
        env_disabled.close()


def test_disabled_community_market_with_string_false_keeps_legacy_costs(tmp_path: Path):
    baseline_schema = _clone_minute_schema(tmp_path, "baseline_string_false")
    disabled_schema = _clone_minute_schema(
        tmp_path,
        "disabled_market_string_false",
        mutator=lambda s: s.update(
            {
                "community_market": {
                    "enabled": "false",
                    "intra_community_sell_ratio": 0.2,
                    "grid_export_price": 0.9,
                }
            }
        ),
    )

    env_baseline = CityLearnEnv(str(baseline_schema), central_agent=True, episode_time_steps=4, random_seed=0)
    env_disabled = CityLearnEnv(str(disabled_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        _rollout_zero_actions(env_baseline)
        _rollout_zero_actions(env_disabled)

        np.testing.assert_allclose(
            np.asarray(env_baseline.net_electricity_consumption_cost, dtype="float64"),
            np.asarray(env_disabled.net_electricity_consumption_cost, dtype="float64"),
            rtol=1e-9,
            atol=1e-9,
        )
    finally:
        env_baseline.close()
        env_disabled.close()


def test_disabled_community_market_does_not_credit_building_exports(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    schema["community_market"]["enabled"] = False
    schema["community_market"]["grid_export_price"] = 0.9
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        env.reset()
        env.step([np.zeros(len(env.action_names[0]), dtype="float32")])
        t = env.time_step - 1

        expected_total = 0.0
        for building in env.buildings:
            net = float(building.net_electricity_consumption[t])
            price = float(building.pricing.electricity_pricing[t])
            expected_cost = max(net, 0.0) * price
            assert building.net_electricity_consumption_cost[t] == pytest.approx(expected_cost, abs=1e-6)
            expected_total += expected_cost

        assert expected_total > 0.0
        assert env.net_electricity_consumption_cost[t] == pytest.approx(expected_total, abs=1e-6)
    finally:
        env.close()


def test_single_phase_rejects_non_l1_assets(tmp_path: Path):
    schema_path = _clone_minute_schema(
        tmp_path,
        "single_phase_invalid",
        mutator=lambda s: (
            s["buildings"]["Building_1"].update(
                {
                    "electrical_service": {
                        "mode": "single_phase",
                        "limits": {"total": {"import_kw": 8.0, "export_kw": 8.0}},
                    }
                }
            ),
            s["buildings"]["Building_1"]["chargers"]["charger_1_1"]["attributes"].update({"phase_connection": "L2"}),
        ),
    )

    with pytest.raises(ValueError, match="single_phase"):
        CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)


def test_three_phase_rejects_invalid_per_phase_keys(tmp_path: Path):
    schema_path = _clone_minute_schema(
        tmp_path,
        "three_phase_invalid_key",
        mutator=lambda s: s["buildings"]["Building_1"].update(
            {
                "electrical_service": {
                    "mode": "three_phase",
                    "limits": {
                        "total": {"import_kw": 8.0, "export_kw": 8.0},
                        "per_phase": {"L1": {"import_kw": 3.0}, "L4": {"import_kw": 3.0}},
                    },
                }
            }
        ),
    )

    with pytest.raises(ValueError, match="L1/L2/L3"):
        CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)


def test_electrical_service_rejects_nan_limits(tmp_path: Path):
    def _mutate(schema):
        building = schema["buildings"]["Building_1"]
        building["electrical_service"] = {
            "mode": "three_phase",
            "limits": {
                "total": {"import_kw": "NaN", "export_kw": 10.0},
                "per_phase": {},
            },
        }

    schema_path = _clone_minute_schema(tmp_path, "electrical_service_nan_limit", mutator=_mutate)

    with pytest.raises(ValueError, match="cannot be NaN"):
        CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)


def test_electrical_service_positive_infinite_limits_are_treated_as_unbounded(tmp_path: Path):
    def _mutate(schema):
        building = schema["buildings"]["Building_1"]
        building["electrical_service"] = {
            "mode": "three_phase",
            "limits": {
                "total": {"import_kw": "inf", "export_kw": "inf"},
                "per_phase": {
                    "L1": {"import_kw": "inf", "export_kw": "inf"},
                    "L2": {"import_kw": "inf", "export_kw": "inf"},
                    "L3": {"import_kw": "inf", "export_kw": "inf"},
                },
            },
            "observations": {"headroom": True, "violation": True},
        }
        building["electrical_storage"]["attributes"]["phase_connection"] = "all_phases"

    schema_path = _clone_minute_schema(tmp_path, "electrical_service_infinite_limit", mutator=_mutate)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset()
        action_names = env.action_names[0]
        actions = np.zeros(len(action_names), dtype="float32")
        actions[action_names.index("electrical_storage")] = 1.0
        ev_action_name = next(name for name in action_names if name.startswith("electric_vehicle_storage_"))
        actions[action_names.index(ev_action_name)] = 1.0
        env.step([actions])

        building = env.buildings[0]
        state = charging_constraints_state(building)
        assert state is not None
        assert state["building_headroom_kw"] is None
        assert state["building_export_headroom_kw"] is None
        assert state["phase_headroom_kw"]["L1"] is None
        assert state["phase_headroom_kw"]["L2"] is None
        assert state["phase_headroom_kw"]["L3"] is None
        assert state["phase_export_headroom_kw"]["L1"] is None
        assert state["phase_export_headroom_kw"]["L2"] is None
        assert state["phase_export_headroom_kw"]["L3"] is None
        assert np.isfinite(state["total_power_kw"])
        assert np.isfinite(charging_constraint_last_penalty_kwh(building))
        assert charging_constraint_last_penalty_kwh(building) == pytest.approx(0.0, abs=1e-6)
    finally:
        env.close()


def test_three_phase_limits_clip_controllable_actions(tmp_path: Path):
    total_import_limit_kw = 5.0
    per_phase_import_limit_kw = 2.0

    def _mutate(schema):
        building = schema["buildings"]["Building_1"]
        building["electrical_service"] = {
            "mode": "three_phase",
            "default_split": "balanced",
            "limits": {
                "total": {"import_kw": total_import_limit_kw, "export_kw": 2.5},
                "per_phase": {
                    "L1": {"import_kw": per_phase_import_limit_kw, "export_kw": 1.0},
                    "L2": {"import_kw": per_phase_import_limit_kw, "export_kw": 1.0},
                    "L3": {"import_kw": per_phase_import_limit_kw, "export_kw": 1.0},
                },
            },
            "observations": {"headroom": True, "violation": True},
        }
        building["chargers"]["charger_1_1"]["attributes"]["phase_connection"] = "L1"
        building["electrical_storage"]["attributes"]["phase_connection"] = "all_phases"

    schema_path = _clone_minute_schema(tmp_path, "three_phase_clip", mutator=_mutate)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=1)

    try:
        env.reset()
        action_names = env.action_names[0]
        actions = np.zeros(len(action_names), dtype="float32")
        actions[action_names.index("electrical_storage")] = 1.0
        ev_action_name = next(name for name in action_names if name.startswith("electric_vehicle_storage_"))
        actions[action_names.index(ev_action_name)] = 1.0
        env.step([actions])

        building = env.buildings[0]
        state = charging_constraints_state(building)
        assert state is not None
        assert state["total_power_kw"] <= total_import_limit_kw + 1e-6
        assert state["phase_power_kw"]["L1"] <= per_phase_import_limit_kw + 1e-6
        assert state["phase_power_kw"]["L2"] <= per_phase_import_limit_kw + 1e-6
        assert state["phase_power_kw"]["L3"] <= per_phase_import_limit_kw + 1e-6
        assert charging_constraint_last_penalty_kwh(building) > 0.0

        t = building.time_step - 1
        charger = building.electric_vehicle_chargers[0]
        commanded_kwh = charger.past_charging_action_values_kwh[t]
        assert commanded_kwh < (charger.max_charging_power * (building.seconds_per_time_step / 3600.0))

        district = env.evaluate_v2()
        district = district[(district["level"] == "district") & (district["name"] == "District")]
        values = district.set_index("cost_function")["value"]
        assert values["district_electrical_service_phase_requested_pressure_energy_total_kwh"] > 0.0
        assert values["district_electrical_service_phase_violations_energy_total_kwh"] == pytest.approx(0.0, abs=1e-6)
    finally:
        env.close()


def test_residual_violation_when_non_controllable_exceeds_limit(tmp_path: Path):
    def _mutate(schema):
        building = schema["buildings"]["Building_1"]
        building["electrical_service"] = {
            "mode": "three_phase",
            "default_split": "balanced",
            "limits": {
                "total": {"import_kw": 0.1, "export_kw": 2.0},
                "per_phase": {},
            },
            "observations": {"headroom": True, "violation": True},
        }
        building["electrical_storage"]["attributes"]["phase_connection"] = "all_phases"

    schema_path = _clone_minute_schema(tmp_path, "residual_violation", mutator=_mutate)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=2)

    try:
        env.reset()
        actions = np.zeros(len(env.action_names[0]), dtype="float32")
        env.step([actions])

        building = env.buildings[0]
        assert charging_constraint_last_penalty_kwh(building) > 0.0
        state = charging_constraints_state(building)
        assert state["total_power_kw"] > 0.1
        obs = building.observations(include_all=True, normalize=False, periodic_normalization=False)
        assert obs["charging_constraint_violation_kwh"] > 0.0

        district = env.evaluate_v2()
        district = district[(district["level"] == "district") & (district["name"] == "District")]
        values = district.set_index("cost_function")["value"]
        assert values["district_electrical_service_phase_requested_pressure_energy_total_kwh"] > 0.0
        assert values["district_electrical_service_phase_violations_energy_total_kwh"] > 0.0
    finally:
        env.close()


def test_electrical_service_headroom_observations_stay_inside_space_bounds(tmp_path: Path):
    def _mutate(schema):
        building = schema["buildings"]["Building_1"]
        building["electrical_service"] = {
            "mode": "single_phase",
            "limits": {"total": {"import_kw": 6.0, "export_kw": 6.0}},
            "observations": {"headroom": True, "headroom_export": True, "violation": True},
        }

    schema_path = _clone_minute_schema(tmp_path, "electrical_service_headroom_bounds", mutator=_mutate)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset()
        building = env.buildings[0]
        low, high = building.estimate_observation_space_limits(include_all=True, periodic_normalization=False)
        keys = ["charging_building_headroom_kw", "charging_building_export_headroom_kw"]

        def assert_headroom_in_bounds():
            obs = building.observations(include_all=True, normalize=False, periodic_normalization=False)
            for key in keys:
                assert low[key] <= obs[key] <= high[key], (key, low[key], obs[key], high[key])

        assert_headroom_in_bounds()

        actions = np.zeros(len(env.action_names[0]), dtype="float32")
        actions[env.action_names[0].index("electrical_storage")] = 1.0
        env.step([actions])
        assert_headroom_in_bounds()
    finally:
        env.close()


def test_community_market_settlement_matches_expected_values(tmp_path: Path):
    schema_path = _build_two_building_market_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=2, random_seed=0)

    try:
        env.reset()
        env.step([np.zeros(len(env.action_names[0]), dtype="float32")])

        building_a = next(building for building in env.buildings if building.name == "Building_A")
        building_b = next(building for building in env.buildings if building.name == "Building_B")
        t = env.time_step - 1

        net_a = float(building_a.net_electricity_consumption[t])
        net_b = float(building_b.net_electricity_consumption[t])
        imports = np.array([max(net_a, 0.0), max(net_b, 0.0)], dtype="float64")
        exports = np.array([max(-net_a, 0.0), max(-net_b, 0.0)], dtype="float64")

        traded = min(float(imports.sum()), float(exports.sum()))
        local_import = imports * (traded / max(float(imports.sum()), 1e-12))
        local_export = exports * (traded / max(float(exports.sum()), 1e-12))
        grid_import_remaining = imports - local_import
        grid_export_remaining = exports - local_export

        p_grid = 0.5
        p_local = 0.8 * p_grid
        p_export = 0.0
        expected_cost_a = (
            grid_import_remaining[0] * p_grid
            + local_import[0] * p_local
            - local_export[0] * p_local
            - grid_export_remaining[0] * p_export
        )
        expected_cost_b = (
            grid_import_remaining[1] * p_grid
            + local_import[1] * p_local
            - local_export[1] * p_local
            - grid_export_remaining[1] * p_export
        )

        assert building_a.net_electricity_consumption_cost[t] == pytest.approx(expected_cost_a, abs=1e-6)
        assert building_b.net_electricity_consumption_cost[t] == pytest.approx(expected_cost_b, abs=1e-6)
        assert env.net_electricity_consumption_cost[t] == pytest.approx(expected_cost_a + expected_cost_b, abs=1e-6)
    finally:
        env.close()


def test_community_market_equal_share_allocator():
    from citylearn.internal.runtime import CityLearnRuntimeService

    allocations = CityLearnRuntimeService._allocate_equal_share_import(
        np.array([7.0, 7.0, 7.0, 7.0], dtype='float64'),
        20.0,
    )
    np.testing.assert_allclose(allocations, np.array([5.0, 5.0, 5.0, 5.0], dtype='float64'), atol=1e-9, rtol=1e-9)

    capped_allocations = CityLearnRuntimeService._allocate_equal_share_import(
        np.array([2.0, 8.0, 8.0, 8.0], dtype='float64'),
        20.0,
    )
    np.testing.assert_allclose(capped_allocations, np.array([2.0, 6.0, 6.0, 6.0], dtype='float64'), atol=1e-9, rtol=1e-9)
