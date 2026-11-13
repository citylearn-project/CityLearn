import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


SOURCE_DATASET = Path(__file__).resolve().parent / "data/minute_ev_demo"
DEFERRABLE_OBSERVATIONS = [
    "deferrable_appliance_pending",
    "deferrable_appliance_running",
    "deferrable_appliance_can_start",
    "deferrable_appliance_deadline_missed",
    "deferrable_appliance_earliest_start_time_step",
    "deferrable_appliance_latest_start_time_step",
    "deferrable_appliance_deadline_time_step",
    "deferrable_appliance_hours_until_latest_start",
    "deferrable_appliance_hours_until_deadline",
    "deferrable_appliance_slack_steps",
    "deferrable_appliance_slack_ratio",
    "deferrable_appliance_urgency_ratio",
    "deferrable_appliance_cycle_duration_steps",
    "deferrable_appliance_cycle_energy_kwh",
    "deferrable_appliance_remaining_energy_kwh",
    "deferrable_appliance_current_step_energy_kwh",
    "deferrable_appliance_priority",
    "deferrable_appliance_must_run",
    "deferrable_appliance_cycle_average_power_kw",
    "deferrable_appliance_cycle_peak_power_kw",
    "deferrable_appliance_cycle_load_factor_ratio",
    "deferrable_appliance_cycle_peak_step_offset_ratio",
    "deferrable_appliance_remaining_duration_steps",
    "deferrable_appliance_remaining_average_power_kw",
    "deferrable_appliance_current_step_power_kw",
]


def _schema_with_deferrable_appliance(tmp_path: Path, *, earliest=1, latest=1, profile=None) -> Path:
    dataset_dir = tmp_path / "minute_ev_demo"
    shutil.copytree(SOURCE_DATASET, dataset_dir)
    profile = [0.1, 0.2] if profile is None else profile

    pd.DataFrame(
        [
            {
                "profile_id": "normal",
                "duration_steps": len(profile),
                "total_energy_kwh": round(sum(profile), 12),  # 0.3, not 0.30000000000000004: pandas 2 and 3 parse it alike
                "load_profile": json.dumps(profile),
            }
        ]
    ).to_csv(dataset_dir / "washer_cycle_profiles.csv", index=False)
    pd.DataFrame(
        [
            {
                "cycle_id": "cycle_1",
                "profile_id": "normal",
                "earliest_start_time_step": earliest,
                "latest_start_time_step": latest,
                "deadline_time_step": latest + len(profile) - 1,
                "priority": 0.75,
                "must_run": True,
            }
        ]
    ).to_csv(dataset_dir / "washer_flexibility_schedule.csv", index=False)

    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    for observation in DEFERRABLE_OBSERVATIONS:
        schema["observations"][observation] = {"active": True, "shared_in_central_agent": True}
    schema["actions"]["deferrable_appliance"] = {"active": True}
    schema["buildings"]["Building_1"]["deferrable_appliances"] = {
        "washer_1": {
            "type": "citylearn.energy_model.DeferrableAppliance",
            "cycle_profiles_file": "washer_cycle_profiles.csv",
            "flexibility_schedule_file": "washer_flexibility_schedule.csv",
        }
    }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema_path


def _zero_flat_actions(env: CityLearnEnv):
    return [np.zeros(space.shape, dtype="float32") for space in env.action_space]


def _zero_entity_payload(env: CityLearnEnv):
    return {
        "tables": {
            name: np.zeros(space.shape, dtype="float32")
            for name, space in env.action_space["tables"].items()
            if name in {"building", "charger", "deferrable_appliance"}
        }
    }


def _kpi_value(df, *, level, name, cost_function):
    row = df[(df["level"] == level) & (df["name"] == name) & (df["cost_function"] == cost_function)]
    assert len(row) == 1
    return float(row["value"].iloc[0])


def _flat_observation_value(env: CityLearnEnv, suffix: str) -> float:
    index = next(i for i, name in enumerate(env.observation_names[0]) if name.endswith(suffix))
    return float(env.observations[0][index])


def test_flat_start_action_consumption_and_service_kpis_are_golden(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=1, latest=1)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        action_index = env.action_names[0].index("deferrable_appliance_washer_1")

        env.step(_zero_flat_actions(env))

        start_actions = _zero_flat_actions(env)
        start_actions[0][action_index] = 1.0
        env.step(start_actions)
        building = env.buildings[0]

        assert building.deferrable_appliances_electricity_consumption[1] == pytest.approx(0.1)

        env.step(_zero_flat_actions(env))
        assert building.deferrable_appliances_electricity_consumption[2] == pytest.approx(0.2)

        kpis = env.evaluate_v2()
        assert _kpi_value(
            kpis,
            level="building",
            name="Building_1",
            cost_function="building_deferrable_appliance_service_completed_cycles_count",
        ) == 1.0
        assert _kpi_value(
            kpis,
            level="building",
            name="Building_1",
            cost_function="building_deferrable_appliance_service_missed_cycles_count",
        ) == 0.0
        assert _kpi_value(
            kpis,
            level="district",
            name="District",
            cost_function="district_deferrable_appliance_service_service_level_ratio",
        ) == 1.0
        assert _kpi_value(
            kpis,
            level="district",
            name="District",
            cost_function="district_deferrable_appliance_service_served_energy_total_kwh",
        ) == pytest.approx(0.3)
    finally:
        env.close()


def test_deferrable_start_reduces_ev_headroom_in_electrical_service_constraints(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    building_schema = schema["buildings"]["Building_1"]
    building_schema["electrical_service"] = {
        "mode": "single_phase",
        "limits": {"total": {"import_kw": 5.2, "export_kw": 8.0}},
        "observations": {"headroom": True, "violation": True},
    }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        action_names = env.action_names[0]
        actions = np.zeros(len(action_names), dtype="float32")
        actions[action_names.index("deferrable_appliance_washer_1")] = 1.0
        ev_action_name = next(name for name in action_names if name.startswith("electric_vehicle_storage_"))
        actions[action_names.index(ev_action_name)] = 1.0

        env.step([actions])

        building = env.buildings[0]
        charger = building.electric_vehicle_chargers[0]
        state = building._charging_constraints_state

        assert building.deferrable_appliances_electricity_consumption[0] == pytest.approx(0.1)
        assert state["total_power_kw"] <= 5.2 + 1e-6
        assert building._charging_constraint_last_penalty_kwh > 0.0
        assert charger.past_charging_action_values_kwh[0] == pytest.approx(0.0, abs=1e-6)
    finally:
        env.close()


def test_can_start_observation_is_false_when_electrical_service_blocks_cycle(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    dataset_dir = schema_path.parent
    building_csv = dataset_dir / "Building_1.csv"
    df = pd.read_csv(building_csv)
    df["non_shiftable_load"] = 0.0
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df["solar_generation"] = 0.0
    df.to_csv(building_csv, index=False)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["buildings"]["Building_1"]["electrical_service"] = {
        "mode": "single_phase",
        "limits": {"total": {"import_kw": 0.05, "export_kw": 8.0}},
    }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        assert _flat_observation_value(env, "washer_1_can_start") == pytest.approx(0.0)
    finally:
        env.close()


def test_outage_blocks_ev_charge_and_deferrable_without_local_surplus(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    dataset_dir = schema_path.parent
    building_csv = dataset_dir / "Building_1.csv"
    df = pd.read_csv(building_csv)
    df["power_outage"] = 1
    df["solar_generation"] = 0.0
    df["non_shiftable_load"] = 0.0
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df.to_csv(building_csv, index=False)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["physics_invariant_checks"] = True
    schema["buildings"]["Building_1"]["power_outage"] = {"simulate_power_outage": True}
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        assert _flat_observation_value(env, "washer_1_can_start") == pytest.approx(0.0)
        action_names = env.action_names[0]
        actions = np.zeros(len(action_names), dtype="float32")
        actions[action_names.index("deferrable_appliance_washer_1")] = 1.0
        ev_action_name = next(name for name in action_names if name.startswith("electric_vehicle_storage_"))
        actions[action_names.index(ev_action_name)] = 1.0

        env.step([actions])

        building = env.buildings[0]
        charger = building.electric_vehicle_chargers[0]
        assert building.deferrable_appliances_electricity_consumption[0] == pytest.approx(0.0)
        assert charger.past_charging_action_values_kwh[0] == pytest.approx(0.0)
        assert charger.electricity_consumption[0] == pytest.approx(0.0)
    finally:
        env.close()


def test_bess_discharge_is_blocked_during_outage_without_local_load(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    dataset_dir = schema_path.parent
    building_csv = dataset_dir / "Building_1.csv"
    df = pd.read_csv(building_csv)
    df["power_outage"] = 1
    df["solar_generation"] = 0.0
    df["non_shiftable_load"] = 0.0
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df.to_csv(building_csv, index=False)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["physics_invariant_checks"] = True
    schema["buildings"]["Building_1"]["power_outage"] = {"simulate_power_outage": True}
    schema["buildings"]["Building_1"]["electrical_storage"]["attributes"]["initial_soc"] = 1.0
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        action_names = env.action_names[0]
        actions = np.zeros(len(action_names), dtype="float32")
        actions[action_names.index("electrical_storage")] = -1.0

        env.step([actions])

        building = env.buildings[0]
        assert building.electrical_storage.electricity_consumption[0] == pytest.approx(0.0, abs=1e-8)
        assert building.net_electricity_consumption[0] == pytest.approx(0.0, abs=1e-8)
    finally:
        env.close()


def test_initial_outage_load_is_clipped_instead_of_asserting(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    dataset_dir = schema_path.parent
    building_csv = dataset_dir / "Building_1.csv"
    df = pd.read_csv(building_csv)
    df["power_outage"] = 1
    df["solar_generation"] = 0.0
    df["non_shiftable_load"] = 1.2
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df.to_csv(building_csv, index=False)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["buildings"]["Building_1"]["power_outage"] = {"simulate_power_outage": True}
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        building = env.buildings[0]
        assert building.non_shiftable_load_device.electricity_consumption[0] == pytest.approx(0.0)
        assert building.downward_electrical_flexibility == pytest.approx(0.0)
    finally:
        env.close()


def test_deferrable_start_is_blocked_when_cycle_crosses_future_outage_without_surplus(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    dataset_dir = schema_path.parent
    building_csv = dataset_dir / "Building_1.csv"
    df = pd.read_csv(building_csv)
    df["power_outage"] = 0
    df.loc[1, "power_outage"] = 1
    df["solar_generation"] = 0.0
    df["non_shiftable_load"] = 0.0
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df.to_csv(building_csv, index=False)

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["buildings"]["Building_1"]["power_outage"] = {"simulate_power_outage": True}
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        action_names = env.action_names[0]
        actions = np.zeros(len(action_names), dtype="float32")
        actions[action_names.index("deferrable_appliance_washer_1")] = 1.0

        env.step([actions])

        building = env.buildings[0]
        assert building.deferrable_appliances_electricity_consumption[0] == pytest.approx(0.0)
        assert building.deferrable_appliances_electricity_consumption[1] == pytest.approx(0.0)
    finally:
        env.close()


def test_flat_deferrable_power_bounds_scale_to_subhour_steps(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0, profile=[0.1])
    env = CityLearnEnv(
        str(schema_path),
        central_agent=True,
        episode_time_steps=4,
        seconds_per_time_step=15,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        index = next(i for i, name in enumerate(env.observation_names[0]) if name.endswith("washer_1_cycle_peak_power_kw"))
        assert env.observation_space[0].high[index] >= env.observations[0][index]
        assert env.observations[0][index] == pytest.approx(24.0)
    finally:
        env.close()


def test_entity_absolute_time_bounds_cover_deferrable_and_ev_schedules(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=29, latest=31)
    env = CityLearnEnv(
        str(schema_path),
        interface="entity",
        central_agent=True,
        episode_time_steps=8,
        random_seed=0,
    )

    try:
        observations, _ = env.reset(seed=0)
        deferrable_features = env.entity_specs["tables"]["deferrable_appliance"]["features"]
        deferrable_space = env.observation_space["tables"]["deferrable_appliance"]
        deadline_ix = deferrable_features.index("deadline_time_step")
        assert deferrable_space.high[0, deadline_ix] >= observations["tables"]["deferrable_appliance"][0, deadline_ix]

        charger_features = env.entity_specs["tables"]["charger"]["features"]
        charger_space = env.observation_space["tables"]["charger"]
        departure_ix = charger_features.index("connected_ev_departure_time_step")
        if observations["tables"]["charger"].shape[0] > 0:
            assert np.all(charger_space.high[:, departure_ix] >= observations["tables"]["charger"][:, departure_ix])
    finally:
        env.close()


def test_missed_cycle_service_kpis_are_golden(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=1, latest=1)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step(_zero_flat_actions(env))

        kpis = env.evaluate_v2()
        assert _kpi_value(
            kpis,
            level="building",
            name="Building_1",
            cost_function="building_deferrable_appliance_service_completed_cycles_count",
        ) == 0.0
        assert _kpi_value(
            kpis,
            level="building",
            name="Building_1",
            cost_function="building_deferrable_appliance_service_missed_cycles_count",
        ) == 1.0
        assert _kpi_value(
            kpis,
            level="district",
            name="District",
            cost_function="district_deferrable_appliance_service_service_level_ratio",
        ) == 0.0
        assert _kpi_value(
            kpis,
            level="district",
            name="District",
            cost_function="district_deferrable_appliance_service_unserved_energy_total_kwh",
        ) == pytest.approx(0.3)
    finally:
        env.close()


def test_entity_table_action_edge_and_start(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    env = CityLearnEnv(str(schema_path), interface="entity", central_agent=True, episode_time_steps=3, random_seed=0)

    try:
        observations, _ = env.reset(seed=0)
        specs = env.entity_specs
        assert "deferrable_appliance" in specs["tables"]
        assert specs["tables"]["deferrable_appliance"]["ids"] == ["Building_1/washer_1"]
        assert specs["actions"]["deferrable_appliance"]["features"] == ["start"]
        assert "building_to_deferrable_appliance" in specs["edges"]
        features = specs["tables"]["deferrable_appliance"]["features"]
        assert observations["tables"]["deferrable_appliance"].shape == (1, len(features))
        for feature in [
            "remaining_duration_hours",
            "cycle_remaining_fraction_ratio",
            "hours_until_earliest_start",
            "start_window_width_hours",
            "start_energy_kwh_step",
            "start_power_kw",
            "must_start_now",
        ]:
            assert feature in features

        def value(name: str) -> float:
            return float(observations["tables"]["deferrable_appliance"][0, features.index(name)])

        step_hours = env.seconds_per_time_step / 3600.0
        assert value("must_run") == 1.0
        assert value("cycle_average_power_kw") == pytest.approx(0.3 / (2 * step_hours))
        assert value("cycle_peak_power_kw") == pytest.approx(0.2 / step_hours)
        assert value("cycle_load_factor_ratio") == pytest.approx(0.75)
        assert value("cycle_peak_step_offset_ratio") == pytest.approx(1.0)
        assert value("remaining_duration_steps") == pytest.approx(2.0)
        assert value("remaining_duration_hours") == pytest.approx(2 * step_hours)
        assert value("cycle_remaining_fraction_ratio") == pytest.approx(1.0)
        assert value("hours_until_earliest_start") == pytest.approx(0.0)
        assert value("start_window_width_hours") == pytest.approx(0.0)
        assert value("start_energy_kwh_step") == pytest.approx(0.1)
        assert value("start_power_kw") == pytest.approx(0.1 / step_hours)
        assert value("must_start_now") == pytest.approx(1.0)
        assert value("remaining_average_power_kw") == pytest.approx(0.3 / (2 * step_hours))
        assert value("current_step_power_kw") == pytest.approx(0.0)

        payload = {
            "tables": {
                name: np.zeros(space.shape, dtype="float32")
                for name, space in env.action_space["tables"].items()
                if name in {"building", "charger", "deferrable_appliance"}
            }
        }
        payload["tables"]["deferrable_appliance"][0, 0] = 1.0
        env.step(payload)

        assert env.buildings[0].deferrable_appliances_electricity_consumption[0] == pytest.approx(0.1)
    finally:
        env.close()


def test_entity_action_feedback_for_deferrable_start(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=0)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["observation_bundles"] = {"entity_action_feedback": {"active": True}}
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    env = CityLearnEnv(str(schema_path), interface="entity", central_agent=True, episode_time_steps=3, random_seed=0)

    try:
        env.reset(seed=0)
        payload = _zero_entity_payload(env)
        payload["tables"]["deferrable_appliance"][0, 0] = 1.0
        observations, *_ = env.step(payload)
        features = env.entity_specs["tables"]["deferrable_appliance"]["features"]

        def value(name: str) -> float:
            return float(observations["tables"]["deferrable_appliance"][0, features.index(name)])

        assert value("last_start_requested") == pytest.approx(1.0)
        assert value("last_start_applied") == pytest.approx(1.0)
        assert value("start_blocked") == pytest.approx(0.0)
    finally:
        env.close()


def test_entity_action_feedback_for_blocked_deferrable_start(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=1, latest=1)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["observation_bundles"] = {"entity_action_feedback": {"active": True}}
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    env = CityLearnEnv(str(schema_path), interface="entity", central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        payload = _zero_entity_payload(env)
        payload["tables"]["deferrable_appliance"][0, 0] = 1.0
        observations, *_ = env.step(payload)
        features = env.entity_specs["tables"]["deferrable_appliance"]["features"]

        def value(name: str) -> float:
            return float(observations["tables"]["deferrable_appliance"][0, features.index(name)])

        assert value("last_start_requested") == pytest.approx(1.0)
        assert value("last_start_applied") == pytest.approx(0.0)
        assert value("start_blocked") == pytest.approx(1.0)
        assert value("clip_reason_deferrable_window") == pytest.approx(1.0)
    finally:
        env.close()


def test_entity_deferrable_start_command_is_binary_and_uses_can_start(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=1)
    env = CityLearnEnv(str(schema_path), interface="entity", central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        observations, _ = env.reset(seed=0)
        specs = env.entity_specs
        features = specs["tables"]["deferrable_appliance"]["features"]
        can_start_ix = features.index("can_start")

        def can_start(obs):
            return float(obs["tables"]["deferrable_appliance"][0, can_start_ix])

        assert can_start(observations) == 1.0

        payload = _zero_entity_payload(env)
        payload["tables"]["deferrable_appliance"][0, 0] = 0.5
        observations, *_ = env.step(payload)
        assert env.buildings[0].deferrable_appliances_electricity_consumption[0] == pytest.approx(0.0)
        assert can_start(observations) == 1.0

        payload = _zero_entity_payload(env)
        payload["tables"]["deferrable_appliance"][0, 0] = 1.0
        env.step(payload)
        assert env.buildings[0].deferrable_appliances_electricity_consumption[1] == pytest.approx(0.1)
    finally:
        env.close()
