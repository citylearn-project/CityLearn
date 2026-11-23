from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
import pytest
from private_access import (
    charging_constraint_last_penalty_kwh,
    charging_constraints_state,
    market_settlement_history,
    member_pool,
    topology_service,
)

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.internal.runtime import CityLearnRuntimeService


MINUTE_DATASET_DIR = Path(__file__).resolve().parents[1] / "tests" / "data" / "minute_ev_demo"
DYNAMIC_TOPOLOGY_SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "data/datasets/citylearn_three_phase_dynamic_topology_demo/schema.json"
)
DYNAMIC_ASSETS_SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "data/datasets/citylearn_three_phase_dynamic_assets_only_demo/schema.json"
)


def _clone_minute_schema(tmp_path: Path, name: str, mutator=None) -> Path:
    dataset_dir = tmp_path / name
    shutil.copytree(MINUTE_DATASET_DIR, dataset_dir)
    schema_path = dataset_dir / "schema.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if mutator is not None:
        mutator(schema)
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    return schema_path


def _zero_entity_actions(env: CityLearnEnv):
    tables = env.action_space["tables"]
    return {
        "tables": {
            name: np.zeros(space.shape, dtype="float32")
            for name, space in tables.items()
            if name in {"building", "charger", "deferrable_appliance"}
        }
    }


def _rollout_zero_actions(env: CityLearnEnv):
    env.reset(seed=0)
    while not env.terminated and not env.truncated:
        if env.interface == "entity":
            env.step(_zero_entity_actions(env))
        else:
            env.step([np.zeros(len(env.action_names[0]), dtype="float32")])


def _write_residual_market_schema(tmp_path: Path) -> Path:
    dataset_dir = tmp_path / "residual_market"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    steps = 4

    pd.DataFrame(
        {
            "outdoor_dry_bulb_temperature": [10.0] * steps,
            "outdoor_relative_humidity": [50.0] * steps,
            "diffuse_solar_irradiance": [0.0] * steps,
            "direct_solar_irradiance": [0.0] * steps,
            "outdoor_dry_bulb_temperature_predicted_1": [10.0] * steps,
            "outdoor_dry_bulb_temperature_predicted_2": [10.0] * steps,
            "outdoor_dry_bulb_temperature_predicted_3": [10.0] * steps,
            "outdoor_relative_humidity_predicted_1": [50.0] * steps,
            "outdoor_relative_humidity_predicted_2": [50.0] * steps,
            "outdoor_relative_humidity_predicted_3": [50.0] * steps,
            "diffuse_solar_irradiance_predicted_1": [0.0] * steps,
            "diffuse_solar_irradiance_predicted_2": [0.0] * steps,
            "diffuse_solar_irradiance_predicted_3": [0.0] * steps,
            "direct_solar_irradiance_predicted_1": [0.0] * steps,
            "direct_solar_irradiance_predicted_2": [0.0] * steps,
            "direct_solar_irradiance_predicted_3": [0.0] * steps,
        }
    ).to_csv(dataset_dir / "weather.csv", index=False)
    pd.DataFrame({"carbon_intensity": [0.2] * steps}).to_csv(dataset_dir / "carbon_intensity.csv", index=False)
    pd.DataFrame(
        {
            "electricity_pricing": [0.5, 0.2, 0.1, 0.1],
            "electricity_pricing_predicted_1": [0.5, 0.2, 0.1, 0.1],
            "electricity_pricing_predicted_2": [0.5, 0.2, 0.1, 0.1],
            "electricity_pricing_predicted_3": [0.5, 0.2, 0.1, 0.1],
        }
    ).to_csv(dataset_dir / "pricing.csv", index=False)

    base = {
        "month": [1] * steps,
        "hour": list(range(steps)),
        "minutes": [0] * steps,
        "day_type": [1] * steps,
        "daylight_savings_status": [0] * steps,
        "indoor_dry_bulb_temperature": [21.0] * steps,
        "average_unmet_cooling_setpoint_difference": [0.0] * steps,
        "indoor_relative_humidity": [45.0] * steps,
        "dhw_demand": [0.0] * steps,
        "cooling_demand": [0.0] * steps,
        "heating_demand": [0.0] * steps,
    }
    pd.DataFrame(
        {
            **base,
            "non_shiftable_load": [2.0, 1.0, 0.5, 0.0],
            "solar_generation": [0.0] * steps,
        }
    ).to_csv(dataset_dir / "Building_A.csv", index=False)
    pd.DataFrame(
        {
            **base,
            "non_shiftable_load": [0.0] * steps,
            "solar_generation": [1.0, 3.0, 0.5, 0.0],
        }
    ).to_csv(dataset_dir / "Building_B.csv", index=False)

    common_building = {
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
    schema = {
        "random_seed": 0,
        "root_directory": None,
        "central_agent": True,
        "simulation_start_time_step": 0,
        "simulation_end_time_step": steps - 1,
        "episode_time_steps": steps,
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
        "actions": {"electrical_storage": {"active": False}},
        "reward_function": {"type": "citylearn.reward_function.RewardFunction", "attributes": {}},
        "community_market": {
            "enabled": True,
            "intra_community_sell_ratio": 0.8,
            "grid_export_price": 0.05,
        },
        "buildings": {
            "Building_A": {"include": True, "energy_simulation": "Building_A.csv", **common_building},
            "Building_B": {"include": True, "energy_simulation": "Building_B.csv", **common_building},
        },
    }
    schema_path = dataset_dir / "schema.json"
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema_path


def _assert_market_settlement_conservation(
    env: CityLearnEnv,
    *,
    time_step: int,
    rows,
    building_by_name: Mapping[str, object],
    expected_names=None,
):
    eps = 1.0e-6
    row_names = {row["building"] for row in rows}
    if expected_names is not None:
        assert row_names == set(expected_names)

    total_import = 0.0
    total_export = 0.0
    total_local_import = 0.0
    total_local_export = 0.0
    total_grid_import = 0.0
    total_grid_export = 0.0
    total_cost = 0.0

    for row in rows:
        name = row["building"]
        building = building_by_name[name]
        net = float(building.net_electricity_consumption[time_step])
        member_import = max(net, 0.0)
        member_export = max(-net, 0.0)
        local_import = float(row["local_import_kwh"])
        local_export = float(row["local_export_kwh"])
        grid_import = float(row["grid_import_kwh"])
        grid_export = float(row["grid_export_kwh"])
        grid_export_price = float(row["grid_export_price"])

        assert local_import >= -eps
        assert local_export >= -eps
        assert grid_import >= -eps
        assert grid_export >= -eps
        assert grid_export_price == pytest.approx(0.0, abs=eps)
        assert local_import + grid_import == pytest.approx(member_import, abs=eps)
        assert local_export + grid_export == pytest.approx(member_export, abs=eps)
        assert not (local_import > eps and local_export > eps)
        assert not (grid_import > eps and grid_export > eps)

        expected_cost = (
            grid_import * float(row["grid_import_price"])
            + local_import * float(row["local_price"])
            - local_export * float(row["local_price"])
            - grid_export * grid_export_price
        )
        assert float(row["settled_cost_eur"]) == pytest.approx(expected_cost, abs=eps)
        assert float(building.net_electricity_consumption_cost[time_step]) == pytest.approx(expected_cost, abs=eps)

        total_import += member_import
        total_export += member_export
        total_local_import += local_import
        total_local_export += local_export
        total_grid_import += grid_import
        total_grid_export += grid_export
        total_cost += expected_cost

    traded = min(total_import, total_export)
    assert total_local_import == pytest.approx(traded, abs=eps)
    assert total_local_export == pytest.approx(traded, abs=eps)
    assert total_grid_import == pytest.approx(max(total_import - traded, 0.0), abs=eps)
    assert total_grid_export == pytest.approx(max(total_export - traded, 0.0), abs=eps)
    assert not (total_grid_import > eps and total_grid_export > eps)
    assert float(env.net_electricity_consumption_cost[time_step]) == pytest.approx(total_cost, abs=eps)


def _assert_phase_state_coherent(building, *, history_time_step: int):
    state = charging_constraints_state(building)
    assert state is not None

    eps = 1.0e-5
    phase_power = {name: float(value) for name, value in state["phase_power_kw"].items()}
    total_power = float(state["total_power_kw"])
    assert sum(phase_power.values()) == pytest.approx(total_power, abs=eps)
    assert float(building._charging_total_power_history_kw[history_time_step]) == pytest.approx(total_power, abs=eps)

    total_limits = building._electrical_service_limits["total"]
    import_limit = total_limits.get("import_kw")
    export_limit = total_limits.get("export_kw")
    if import_limit is not None:
        assert state["building_headroom_kw"] == pytest.approx(float(import_limit) - total_power, abs=eps)
    if export_limit is not None:
        assert state["building_export_headroom_kw"] == pytest.approx(float(export_limit) + total_power, abs=eps)

    for phase_name, phase_value in phase_power.items():
        assert float(building._charging_phase_power_history_kw[phase_name][history_time_step]) == pytest.approx(
            phase_value,
            abs=eps,
        )
        limits = building._electrical_service_limits["per_phase"][phase_name]
        if limits.get("import_kw") is not None:
            assert state["phase_headroom_kw"][phase_name] == pytest.approx(
                float(limits["import_kw"]) - phase_value,
                abs=eps,
            )
        if limits.get("export_kw") is not None:
            assert state["phase_export_headroom_kw"][phase_name] == pytest.approx(
                float(limits["export_kw"]) + phase_value,
                abs=eps,
            )


def test_community_market_runtime_settlement_conserves_energy_with_grid_residuals(tmp_path: Path):
    schema_path = _write_residual_market_schema(tmp_path)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        _rollout_zero_actions(env)
        building_by_name = {building.name: building for building in env.buildings}

        saw_grid_import = False
        saw_grid_export = False
        for t, rows in enumerate(market_settlement_history(env)):
            _assert_market_settlement_conservation(
                env,
                time_step=t,
                rows=rows,
                building_by_name=building_by_name,
                expected_names=building_by_name.keys(),
            )
            saw_grid_import = saw_grid_import or sum(row["grid_import_kwh"] for row in rows) > 1.0e-6
            saw_grid_export = saw_grid_export or sum(row["grid_export_kwh"] for row in rows) > 1.0e-6

        assert saw_grid_import
        assert saw_grid_export
    finally:
        env.close()


def test_community_market_weighted_allocator_matches_kpi_replay_and_caps_demand():
    imports = np.array([1.0, 2.0, 10.0], dtype="float64")
    weights = np.array([10.0, 10.0, 1.0], dtype="float64")
    traded = 8.0

    runtime_allocations = CityLearnRuntimeService._allocate_weighted_share_import(imports, traded, weights)
    kpi_allocations = CityLearnKPIService._allocate_weighted_share_import(imports, traded, weights)

    np.testing.assert_allclose(runtime_allocations, np.array([1.0, 2.0, 5.0]), atol=1e-9, rtol=1e-9)
    np.testing.assert_allclose(kpi_allocations, runtime_allocations, atol=1e-9, rtol=1e-9)
    assert float(runtime_allocations.sum()) == pytest.approx(traded, abs=1e-9)
    assert np.all(runtime_allocations <= imports + 1e-9)


def test_three_phase_service_state_conserves_total_phase_power_and_headroom(tmp_path: Path):
    def _mutate(schema):
        building = schema["buildings"]["Building_1"]
        building["electrical_service"] = {
            "mode": "three_phase",
            "default_split": "balanced",
            "limits": {
                "total": {"import_kw": 20.0, "export_kw": 20.0},
                "per_phase": {
                    "L1": {"import_kw": 10.0, "export_kw": 10.0},
                    "L2": {"import_kw": 10.0, "export_kw": 10.0},
                    "L3": {"import_kw": 10.0, "export_kw": 10.0},
                },
            },
            "observations": {"headroom": True, "headroom_export": True, "violation": True},
        }
        building["chargers"]["charger_1_1"]["attributes"]["phase_connection"] = "L1"
        building["electrical_storage"]["attributes"]["phase_connection"] = "all_phases"

    schema_path = _clone_minute_schema(tmp_path, "three_phase_state", mutator=_mutate)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset()
        names = env.action_names[0]
        actions = np.zeros(len(names), dtype="float32")
        actions[names.index("electrical_storage")] = 1.0
        ev_action = next(name for name in names if name.startswith("electric_vehicle_storage_"))
        actions[names.index(ev_action)] = 1.0
        env.step([actions])

        building = env.buildings[0]
        _assert_phase_state_coherent(building, history_time_step=building.time_step - 1)
        assert charging_constraint_last_penalty_kwh(building) > 0.0
    finally:
        env.close()


def _dynamic_assets_schema_with_phase_service() -> Mapping:
    schema = json.loads(DYNAMIC_ASSETS_SCHEMA.read_text(encoding="utf-8"))
    schema["root_directory"] = str(DYNAMIC_ASSETS_SCHEMA.parent)
    schema["interface"] = "entity"
    schema["topology_mode"] = "dynamic"
    for event, step in zip(schema.get("topology_events", []), [2, 3, 4, 5, 6, 7]):
        event["time_step"] = step

    service = {
        "mode": "three_phase",
        "default_split": "balanced",
        "limits": {
            "total": {"import_kw": 80.0, "export_kw": 80.0},
            "per_phase": {
                "L1": {"import_kw": 40.0, "export_kw": 40.0},
                "L2": {"import_kw": 40.0, "export_kw": 40.0},
                "L3": {"import_kw": 40.0, "export_kw": 40.0},
            },
        },
        "observations": {
            "headroom": True,
            "headroom_export": True,
            "violation": True,
            "phase_encoding": True,
        },
    }
    for building_name, building in schema["buildings"].items():
        building["electrical_service"] = service
        storage = building.get("electrical_storage")
        if storage is not None:
            storage.setdefault("attributes", {})["phase_connection"] = "all_phases"
        for charger in (building.get("chargers") or {}).values():
            charger.setdefault("attributes", {})["phase_connection"] = "L1"

    schema["buildings"]["Building_18"]["chargers"]["charger_18_1"]["attributes"]["phase_connection"] = "L2"
    return schema


def test_dynamic_asset_phase_metadata_refreshes_after_charger_add_remove():
    env = CityLearnEnv(
        _dynamic_assets_schema_with_phase_service(),
        interface="entity",
        topology_mode="dynamic",
        episode_time_steps=10,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        while env.time_step < 2:
            env.step(_zero_entity_actions(env))

        building_2 = next(building for building in env.buildings if building.name == "Building_2")
        assert "charger_2_dyn_1" in building_2._charger_lookup
        assert building_2._charger_phase_map["charger_2_dyn_1"] == "L2"
        assert any(
            phase["name"] == "L2" and "charger_2_dyn_1" in phase.get("chargers", [])
            for phase in building_2._phase_limits
        )

        actions = _zero_entity_actions(env)
        actions["map"] = {
            "charger:Building_2/charger_2_dyn_1": {
                "electric_vehicle_storage": 1.0,
            }
        }
        env.step(actions)
        _assert_phase_state_coherent(building_2, history_time_step=2)

        building_5 = next(building for building in env.buildings if building.name == "Building_5")
        assert "charger_5_1" not in building_5._charger_lookup
        assert all("charger_5_1" not in phase.get("chargers", []) for phase in building_5._phase_limits)
    finally:
        env.close()


def test_dynamic_topology_community_market_conservation_tracks_active_members():
    schema = json.loads(DYNAMIC_TOPOLOGY_SCHEMA.read_text(encoding="utf-8"))
    schema["root_directory"] = str(DYNAMIC_TOPOLOGY_SCHEMA.parent)
    schema["interface"] = "entity"
    schema["topology_mode"] = "dynamic"
    for event, step in zip(schema.get("topology_events", []), [2, 3, 4, 5, 6, 7, 8, 9]):
        event["time_step"] = step

    env = CityLearnEnv(schema, interface="entity", topology_mode="dynamic", episode_time_steps=12, random_seed=0)

    try:
        _rollout_zero_actions(env)
        pool = member_pool(env)

        for t, rows in enumerate(market_settlement_history(env)):
            active_ids = topology_service(env).active_member_ids_at(t)
            _assert_market_settlement_conservation(
                env,
                time_step=t,
                rows=rows,
                building_by_name=pool,
                expected_names=active_ids,
            )
    finally:
        env.close()
