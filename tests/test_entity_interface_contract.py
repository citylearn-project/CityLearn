import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
ELECTRICAL_SERVICE_SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "data/datasets/citylearn_three_phase_electrical_service_demo/schema.json"
)


def _zero_entity_actions(env: CityLearnEnv):
    tables = env.action_space["tables"]
    return {
        "tables": {
            name: np.zeros(space.shape, dtype="float32")
            for name, space in tables.items()
            if name in {"building", "charger", "deferrable_appliance"}
        }
    }


def _entity_storage_action(env: CityLearnEnv, value: float):
    payload = _zero_entity_actions(env)
    building = payload["tables"]["building"]
    features = env.entity_specs["actions"]["building"]["features"]

    if "electrical_storage" not in features:
        pytest.skip("Dataset does not expose electrical_storage action in entity mode.")

    building[0, features.index("electrical_storage")] = value
    return payload


def test_entity_interface_shapes_and_specs_are_consistent():
    env = CityLearnEnv(str(SCHEMA), interface="entity", central_agent=True, episode_time_steps=6, random_seed=0)

    try:
        observations, _ = env.reset()
        specs = env.entity_specs

        assert isinstance(observations, dict)
        assert "tables" in observations
        assert "edges" in observations
        assert observations["tables"]["district"].shape[1] == len(specs["tables"]["district"]["features"])
        assert observations["tables"]["building"].shape[0] == len(env.buildings)
        assert observations["tables"]["building"].shape[1] == len(specs["tables"]["building"]["features"])
        assert observations["tables"]["charger"].shape[1] == len(specs["tables"]["charger"]["features"])
        assert observations["tables"]["ev"].shape[1] == len(specs["tables"]["ev"]["features"])
        assert observations["tables"]["storage"].shape[1] == len(specs["tables"]["storage"]["features"])
        assert observations["tables"]["pv"].shape[1] == len(specs["tables"]["pv"]["features"])
        for table_name in ("district", "building", "charger", "ev", "storage", "pv", "deferrable_appliance"):
            feature_metadata = specs["tables"][table_name]["feature_metadata"]
            for feature in specs["tables"][table_name]["features"]:
                assert feature in feature_metadata
                assert set(feature_metadata[feature].keys()) == {"unit", "bundle", "legacy"}
        assert specs["version"] == "entity_v1"
        assert specs["temporal_semantics"]["endogenous"] == "t_minus_1_settled"
        assert specs["normalization"]["policy"] == "external_running_stats"
        assert specs["normalization"]["simulator_applies_normalization"] is False
        assert specs["normalization"]["dynamic_topology"]["stable_ids"] is True
        assert specs["runtime_status_contract"]["version"] == "runtime_status_v1"
        assert specs["runtime_status_contract"]["emits_health_state"] is False
        assert specs["action_execution_contract"]["version"] == "entity_action_execution_v1"
        runtime_status = observations["meta"]["runtime_status"]
        assert runtime_status["version"] == "runtime_status_v1"
        assert runtime_status["emits_health_state"] is False
        assert len(runtime_status["asset_connections"]) == len(specs["tables"]["charger"]["ids"])
        assert all("health" not in record for record in runtime_status["asset_connections"])
    finally:
        env.close()


def test_entity_interface_has_deterministic_id_and_edge_indexing():
    env = CityLearnEnv(str(SCHEMA), interface="entity", central_agent=True, episode_time_steps=6, random_seed=0)

    try:
        first_obs, _ = env.reset(seed=0)
        first_specs = env.entity_specs
        first_building_to_charger = first_obs["edges"]["building_to_charger"].copy()

        second_obs, _ = env.reset(seed=0)
        second_specs = env.entity_specs
        second_building_to_charger = second_obs["edges"]["building_to_charger"].copy()

        assert first_specs["tables"]["building"]["ids"] == second_specs["tables"]["building"]["ids"]
        assert first_specs["tables"]["charger"]["ids"] == second_specs["tables"]["charger"]["ids"]
        assert first_specs["tables"]["ev"]["ids"] == second_specs["tables"]["ev"]["ids"]
        assert first_specs["tables"]["pv"]["ids"] == second_specs["tables"]["pv"]["ids"]
        assert np.array_equal(first_building_to_charger, second_building_to_charger)
        assert np.array_equal(first_obs["edges"]["building_to_pv"], second_obs["edges"]["building_to_pv"])
    finally:
        env.close()


def test_entity_interface_includes_ev_and_charger_tables_and_edges():
    env = CityLearnEnv(str(SCHEMA), interface="entity", central_agent=True, episode_time_steps=6, random_seed=0)

    try:
        observations, _ = env.reset()
        expected_chargers = sum(len(building.electric_vehicle_chargers or []) for building in env.buildings)
        expected_evs = len(env.electric_vehicles)
        expected_pv = sum(1 for building in env.buildings if float(getattr(building.pv, "nominal_power", 0.0)) > 0.0)

        assert observations["tables"]["charger"].shape[0] == expected_chargers
        assert observations["tables"]["ev"].shape[0] == expected_evs
        assert observations["tables"]["pv"].shape[0] == expected_pv
        assert observations["edges"]["building_to_charger"].shape[0] == expected_chargers
        assert observations["edges"]["building_to_pv"].shape[0] == expected_pv
    finally:
        env.close()


def test_entity_interface_keeps_charger_phase_connection_on_charger_table():
    env = CityLearnEnv(
        str(ELECTRICAL_SERVICE_SCHEMA),
        interface="entity",
        central_agent=False,
        episode_time_steps=6,
        random_seed=0,
    )

    try:
        observations, _ = env.reset()
        specs = env.entity_specs
        building_features = specs["tables"]["building"]["features"]
        charger_features = specs["tables"]["charger"]["features"]

        assert not any(name.startswith("charging_phase_one_hot_") for name in building_features)
        assert not any("charger_15_" in name for name in building_features)

        phase_features = [name for name in charger_features if name.startswith("phase_connection_")]
        assert phase_features
        for feature in phase_features:
            assert specs["tables"]["charger"]["feature_metadata"][feature]["bundle"] == "entity_base"
            assert specs["tables"]["charger"]["feature_metadata"][feature]["legacy"] is False

        charger_ids = specs["tables"]["charger"]["ids"]
        charger_15_rows = [
            idx for idx, charger_id in enumerate(charger_ids)
            if charger_id.startswith("Building_15/")
        ]
        assert charger_15_rows

        phase_cols = [charger_features.index(name) for name in phase_features]
        for row in charger_15_rows:
            assert observations["tables"]["charger"][row, phase_cols].sum() == pytest.approx(1.0)
    finally:
        env.close()


def test_entity_interface_marks_all_phase_charger_connections():
    schema = json.loads(ELECTRICAL_SERVICE_SCHEMA.read_text(encoding="utf-8"))
    schema["root_directory"] = str(ELECTRICAL_SERVICE_SCHEMA.parent)
    schema["buildings"]["Building_15"]["chargers"]["charger_15_1"]["attributes"]["phase_connection"] = "all_phases"

    env = CityLearnEnv(
        schema,
        interface="entity",
        central_agent=False,
        episode_time_steps=6,
        random_seed=0,
    )

    try:
        observations, _ = env.reset()
        specs = env.entity_specs
        charger_features = specs["tables"]["charger"]["features"]
        charger_ids = specs["tables"]["charger"]["ids"]

        assert "phase_connection_all_phases" not in charger_features
        row = charger_ids.index("Building_15/charger_15_1")
        phase_cols = [
            charger_features.index("phase_connection_L1"),
            charger_features.index("phase_connection_L2"),
            charger_features.index("phase_connection_L3"),
        ]

        assert observations["tables"]["charger"][row, phase_cols].tolist() == [1.0, 1.0, 1.0]
    finally:
        env.close()


def test_entity_interface_exposes_three_phase_power_and_storage_phase_connection():
    schema = json.loads(ELECTRICAL_SERVICE_SCHEMA.read_text(encoding="utf-8"))
    schema["root_directory"] = str(ELECTRICAL_SERVICE_SCHEMA.parent)
    schema["observation_bundles"] = {"entity_core_electrical": {"active": True}}

    env = CityLearnEnv(
        schema,
        interface="entity",
        central_agent=False,
        episode_time_steps=6,
        random_seed=0,
    )

    try:
        observations, _ = env.reset(seed=0)
        specs = env.entity_specs

        building_features = specs["tables"]["building"]["features"]
        expected_phase_power_features = [
            "charging_phase_L1_power_kw",
            "charging_phase_L2_power_kw",
            "charging_phase_L3_power_kw",
        ]
        assert "charging_total_service_power_kw" in building_features
        for feature in expected_phase_power_features:
            assert feature in building_features
            assert specs["tables"]["building"]["feature_metadata"][feature]["bundle"] == "entity_core_electrical"

        storage_features = specs["tables"]["storage"]["features"]
        storage_phase_features = [
            "phase_connection_L1",
            "phase_connection_L2",
            "phase_connection_L3",
        ]
        for feature in storage_phase_features:
            assert feature in storage_features
            assert specs["tables"]["storage"]["feature_metadata"][feature]["bundle"] == "entity_base"

        storage_ids = specs["tables"]["storage"]["ids"]
        assert storage_ids
        phase_cols = [storage_features.index(name) for name in storage_phase_features]
        assert observations["tables"]["storage"][0, phase_cols].sum() >= 1.0
    finally:
        env.close()


def test_entity_observations_use_latest_settled_endogenous_transition():
    env = CityLearnEnv(str(SCHEMA), interface="entity", central_agent=True, episode_time_steps=6, random_seed=0)

    try:
        env.reset()
        obs, _, terminated, truncated, _ = env.step(_zero_entity_actions(env))
        assert not terminated
        assert not truncated

        feature_names = env.entity_specs["tables"]["building"]["features"]
        feature_index = feature_names.index("net_electricity_consumption")
        settled_t = max(env.time_step - 1, 0)
        expected_current = float(env.buildings[0].net_electricity_consumption[settled_t])

        assert obs["meta"]["endogenous_time_step"] == settled_t
        assert obs["tables"]["building"][0, feature_index] == pytest.approx(expected_current)
    finally:
        env.close()


def test_entity_observation_payload_returns_independent_arrays():
    env = CityLearnEnv(str(SCHEMA), interface="entity", central_agent=True, episode_time_steps=6, random_seed=0)

    try:
        observations, _ = env.reset(seed=0)
        building_table = observations["tables"]["building"]
        building_snapshot = building_table.copy()
        connected_edges = observations["edges"]["charger_to_ev_connected"]
        connected_edges_snapshot = connected_edges.copy()

        next_observations, _, terminated, truncated, _ = env.step(_zero_entity_actions(env))
        assert not terminated
        assert not truncated

        assert building_table is not next_observations["tables"]["building"]
        assert connected_edges is not next_observations["edges"]["charger_to_ev_connected"]
        assert np.array_equal(building_table, building_snapshot)
        assert np.array_equal(connected_edges, connected_edges_snapshot)
    finally:
        env.close()


def test_entity_soc_uses_settled_index_after_nonzero_storage_action():
    env = CityLearnEnv(str(SCHEMA), interface="entity", central_agent=True, episode_time_steps=6, random_seed=0)

    try:
        env.reset(seed=0)
        obs, _, terminated, truncated, _ = env.step(_entity_storage_action(env, 0.5))
        assert not terminated
        assert not truncated

        feature_names = env.entity_specs["tables"]["building"]["features"]
        soc_index = feature_names.index("electrical_storage_soc")
        settled_t = max(env.time_step - 1, 0)
        expected_soc = float(env.buildings[0].electrical_storage.soc[settled_t])

        assert obs["meta"]["endogenous_time_step"] == settled_t
        assert obs["tables"]["building"][0, soc_index] == pytest.approx(expected_soc)
    finally:
        env.close()
