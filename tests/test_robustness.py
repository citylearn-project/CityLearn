from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.multi_community import MultiCommunityEnv


MINUTE_SCHEMA_PATH = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"
PACKAGED_2022_ROBUSTNESS_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "data/datasets/citylearn_challenge_2022_phase_all_robustness/schema.json"
)


def _copy_schema(
    tmp_path: Path,
    *,
    name: str = "minute_robustness",
    interface: str = "flat",
    event_format: str = "csv",
    enabled: bool = True,
    modules: Mapping[str, bool] = None,
):
    dataset_dir = tmp_path / name
    shutil.copytree(MINUTE_SCHEMA_PATH.parent, dataset_dir)
    schema = json.loads((dataset_dir / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["interface"] = interface
    if interface == "entity":
        schema["observation_bundles"] = {
            "entity_core_electrical": {"active": True},
            "entity_forecasts_existing": {"active": True},
            "entity_robustness": {"active": True},
        }
    module_flags = {
        "observations": True,
        "forecasts": True,
        "actions": True,
        "assets": True,
    }
    if modules is not None:
        module_flags.update(modules)
    schema["robustness"] = {
        "enabled": enabled,
        "events_file": f"robustness_events.{event_format}",
        "random_seed": 7,
        "missing_replacement_value": -9999.0,
        "modules": {
            name: {"enabled": active}
            for name, active in module_flags.items()
        },
    }
    schema["_dataset_dir"] = str(dataset_dir)
    schema["_event_format"] = event_format
    return schema


def _write_events(schema: Mapping, rows: Iterable[Mapping], *, event_format: str = None):
    dataset_dir = Path(schema["_dataset_dir"])
    event_format = event_format or schema["_event_format"]
    path = dataset_dir / schema["robustness"]["events_file"]
    frame = pd.DataFrame(rows)
    if event_format == "parquet":
        pytest.importorskip("pyarrow")
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def _clean_schema(schema: Mapping) -> dict:
    cleaned = dict(schema)
    cleaned.pop("_dataset_dir", None)
    cleaned.pop("_event_format", None)
    return cleaned


def _event(
    *,
    event_id: str = "event_1",
    module: str = "observation",
    target_type: str = "building",
    target_id: str = "Building_1",
    target_feature: str = "non_shiftable_load",
    start: int = 0,
    end: int = 0,
    mode: str = "missing",
    value=None,
    std=None,
    min_value=None,
    max_value=None,
    replacement_value=None,
    delay_steps=None,
    event_domain=None,
):
    return {
        "event_id": event_id,
        "module": module,
        "target_type": target_type,
        "target_id": target_id,
        "target_feature": target_feature,
        "start_time_step": start,
        "end_time_step": end,
        "mode": mode,
        "value": value,
        "std": std,
        "min_value": min_value,
        "max_value": max_value,
        "replacement_value": replacement_value,
        "delay_steps": delay_steps,
        "event_domain": event_domain,
    }


def _zero_actions(env: CityLearnEnv):
    if env.interface == "entity":
        return {
            "tables": {
                table_name: np.zeros(space.shape, dtype="float32")
                for table_name, space in env.action_space["tables"].items()
            }
        }

    return [np.zeros(space.shape, dtype="float32") for space in env.action_space]


def _storage_action(env: CityLearnEnv, value: float):
    if env.interface == "entity":
        action = _zero_actions(env)
        features = env.entity_specs["actions"]["building"]["features"]
        action["tables"]["building"][:, features.index("electrical_storage")] = float(value)
        return action

    action = _zero_actions(env)
    action[0][env.action_names[0].index("electrical_storage")] = float(value)
    return action


def _flat_value(env: CityLearnEnv, observations, feature: str) -> float:
    return float(observations[0][env.observation_names[0].index(feature)])


def _kpi_value(kpis: pd.DataFrame, cost_function: str, *, level: str = "district", name: str = "District"):
    rows = kpis[
        (kpis["cost_function"] == cost_function)
        & (kpis["level"] == level)
        & (kpis["name"] == name)
    ]
    assert len(rows) == 1, cost_function
    return rows["value"].iloc[0]


def test_robustness_disabled_preserves_default_observations_and_rewards(tmp_path: Path):
    schema = _copy_schema(tmp_path, enabled=False)
    _write_events(schema, [_event()])
    baseline = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, episode_time_steps=4, random_seed=0)
    robust = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        baseline_obs, _ = baseline.reset(seed=0)
        robust_obs, _ = robust.reset(seed=0)
        assert np.allclose(baseline_obs[0], robust_obs[0])

        _, baseline_reward, *_ = baseline.step(_zero_actions(baseline))
        _, robust_reward, *_ = robust.step(_zero_actions(robust))
        assert np.allclose(np.asarray(baseline_reward), np.asarray(robust_reward))
        assert robust._robustness_service.history == {}
    finally:
        baseline.close()
        robust.close()


@pytest.mark.parametrize("event_format", ["csv", "parquet"])
def test_robustness_events_file_supports_csv_and_parquet(tmp_path: Path, event_format: str):
    schema = _copy_schema(tmp_path, name=f"events_{event_format}", event_format=event_format)
    _write_events(schema, [_event(replacement_value=-1234.0)], event_format=event_format)
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)
        assert len(env._robustness_service.events) == 1
        assert _flat_value(env, obs, "non_shiftable_load") == pytest.approx(-1234.0)
    finally:
        env.close()


def test_robustness_schema_validation_errors_are_clear(tmp_path: Path):
    missing_file_schema = _copy_schema(tmp_path, name="missing_file")
    with pytest.raises(FileNotFoundError, match="robustness.events_file"):
        CityLearnEnv(_clean_schema(missing_file_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    missing_columns_schema = _copy_schema(tmp_path, name="missing_columns")
    pd.DataFrame([{"event_id": "bad"}]).to_csv(
        Path(missing_columns_schema["_dataset_dir"]) / missing_columns_schema["robustness"]["events_file"],
        index=False,
    )
    with pytest.raises(ValueError, match="missing columns"):
        CityLearnEnv(_clean_schema(missing_columns_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    invalid_mode_schema = _copy_schema(tmp_path, name="invalid_mode")
    _write_events(invalid_mode_schema, [_event(mode="invalid")])
    with pytest.raises(ValueError, match="mode must be one of"):
        CityLearnEnv(_clean_schema(invalid_mode_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    invalid_target_schema = _copy_schema(tmp_path, name="invalid_target")
    _write_events(invalid_target_schema, [_event(target_feature="does_not_exist")])
    with pytest.raises(ValueError, match="target does not match"):
        CityLearnEnv(_clean_schema(invalid_target_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    invalid_domain_schema = _copy_schema(tmp_path, name="invalid_domain")
    _write_events(
        invalid_domain_schema,
        [_event(module="observation", event_domain="ACTUATOR_CHANNEL")],
    )
    with pytest.raises(ValueError, match="incompatible with module"):
        CityLearnEnv(_clean_schema(invalid_domain_schema), central_agent=True, episode_time_steps=4, random_seed=0)


def test_robustness_modules_can_be_disabled_individually(tmp_path: Path):
    schema = _copy_schema(tmp_path, modules={"observations": False})
    _write_events(schema, [_event(replacement_value=-1234.0)])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)
    baseline = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)
        baseline_obs, _ = baseline.reset(seed=0)
        assert _flat_value(env, obs, "non_shiftable_load") == pytest.approx(
            _flat_value(baseline, baseline_obs, "non_shiftable_load")
        )
        assert env._robustness_service.history == {}
    finally:
        env.close()
        baseline.close()


@pytest.mark.parametrize(
    "mode,kwargs,expected",
    [
        ("missing", {"replacement_value": -4321.0}, -4321.0),
        ("bias", {"value": 2.5}, "raw_plus_2_5"),
        ("clip", {"min_value": 0.0, "max_value": 0.0}, 0.0),
    ],
)
def test_flat_observation_corruption_modes(tmp_path: Path, mode: str, kwargs: Mapping, expected):
    schema = _copy_schema(tmp_path, name=f"obs_{mode}")
    _write_events(schema, [_event(mode=mode, **kwargs)])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)
    baseline = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)
        baseline_obs, _ = baseline.reset(seed=0)
        value = _flat_value(env, obs, "non_shiftable_load")
        raw = _flat_value(baseline, baseline_obs, "non_shiftable_load")
        if expected == "raw_plus_2_5":
            assert value == pytest.approx(raw + 2.5)
        else:
            assert value == pytest.approx(expected)
    finally:
        env.close()
        baseline.close()


def test_flat_observation_stuck_and_noise_are_deterministic(tmp_path: Path):
    stuck_schema = _copy_schema(tmp_path, name="obs_stuck")
    _write_events(stuck_schema, [_event(mode="stuck", end=1)])
    stuck_env = CityLearnEnv(_clean_schema(stuck_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    noise_schema = _copy_schema(tmp_path, name="obs_noise")
    _write_events(noise_schema, [_event(mode="noise", std=5.0)])
    noise_env = CityLearnEnv(_clean_schema(noise_schema), central_agent=True, episode_time_steps=4, random_seed=0)
    noise_env_replay = CityLearnEnv(_clean_schema(noise_schema), central_agent=True, episode_time_steps=4, random_seed=0)
    baseline = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        first_obs, _ = stuck_env.reset(seed=0)
        first_value = _flat_value(stuck_env, first_obs, "non_shiftable_load")
        next_obs, *_ = stuck_env.step(_zero_actions(stuck_env))
        assert _flat_value(stuck_env, next_obs, "non_shiftable_load") == pytest.approx(first_value)

        noise_obs_1, _ = noise_env.reset(seed=0)
        noise_value_1 = _flat_value(noise_env, noise_obs_1, "non_shiftable_load")
        noise_obs_2, _ = noise_env_replay.reset(seed=0)
        noise_value_2 = _flat_value(noise_env, noise_obs_2, "non_shiftable_load")
        baseline_obs, _ = baseline.reset(seed=0)
        assert noise_value_1 == pytest.approx(noise_value_2)
        assert noise_value_1 != pytest.approx(_flat_value(baseline, baseline_obs, "non_shiftable_load"))
    finally:
        stuck_env.close()
        noise_env.close()
        noise_env_replay.close()
        baseline.close()


def test_forecast_corruption_only_touches_forecast_features(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="forecast_bias")
    _write_events(
        schema,
        [
            _event(
                module="forecast",
                target_type="district",
                target_id="*",
                target_feature="electricity_pricing_predicted_1",
                mode="bias",
                value=1.0,
            )
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)
    baseline = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)
        baseline_obs, _ = baseline.reset(seed=0)
        assert _flat_value(env, obs, "electricity_pricing_predicted_1") == pytest.approx(
            _flat_value(baseline, baseline_obs, "electricity_pricing_predicted_1") + 1.0
        )
        assert _flat_value(env, obs, "electricity_pricing") == pytest.approx(
            _flat_value(baseline, baseline_obs, "electricity_pricing")
        )
    finally:
        env.close()
        baseline.close()


def test_entity_observation_bundle_and_meta_report_robustness_state(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="entity_obs", interface="entity")
    _write_events(schema, [_event(replacement_value=-555.0)])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)
        building_features = env.entity_specs["tables"]["building"]["features"]
        district_features = env.entity_specs["tables"]["district"]["features"]

        assert obs["tables"]["building"][0, building_features.index("non_shiftable_load")] == pytest.approx(-555.0)
        assert "robustness_active" in district_features
        assert obs["tables"]["district"][0, district_features.index("robustness_active")] == pytest.approx(1.0)
        assert obs["meta"]["robustness"]["enabled"] is True
        assert obs["meta"]["robustness"]["active_event_ids"] == ["event_1"]
        assert obs["meta"]["robustness"]["last_step_counts"]["observation"] == 1
    finally:
        env.close()


def test_runtime_status_preserves_fault_cause_without_deriving_health(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="runtime_status_stuck", interface="entity")
    _write_events(
        schema,
        [
            _event(
                mode="stuck",
                start=0,
                end=2,
                event_domain="SENSOR_CHANNEL",
            )
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        observations, _ = env.reset(seed=0)
        status = observations["meta"]["runtime_status"]
        assert status["version"] == "runtime_status_v1"
        assert status["emits_health_state"] is False
        assert status["active_events"][0]["fault_mode"] == "stuck"
        record = status["sensor_channels"][0]
        assert record["fault_mode"] == "stuck"
        assert record["quality"] == "IMPAIRED"
        assert record["availability"] == "AVAILABLE"
        assert record["age_steps"] == 0
        assert "health" not in record
        assert "health_state" not in record

        observations, *_ = env.step(_zero_actions(env))
        record = observations["meta"]["runtime_status"]["sensor_channels"][0]
        assert record["fault_mode"] == "stuck"
        assert record["age_steps"] == 1
        assert record["quality"] == "IMPAIRED"
    finally:
        env.close()


def test_runtime_status_keeps_connection_availability_and_channels_separate(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="runtime_status_domains", interface="entity")
    _write_events(
        schema,
        [
            _event(
                event_id="sensor_loss",
                event_domain="SENSOR_CHANNEL",
                mode="missing",
            ),
            _event(
                event_id="actuator_loss",
                module="action",
                target_type="storage",
                target_id="Building_1",
                target_feature="electrical_storage",
                mode="dropout",
                event_domain="ACTUATOR_CHANNEL",
            ),
            _event(
                event_id="community_link_loss",
                module="forecast",
                target_type="district",
                target_id="*",
                target_feature="electricity_pricing_predicted_1",
                mode="missing",
                event_domain="COMMUNICATION_LINK",
            ),
            _event(
                event_id="asset_unavailable",
                module="asset",
                target_type="storage",
                target_id="Building_1",
                target_feature="both",
                mode="unavailable",
                event_domain="ASSET_AVAILABILITY",
            ),
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        observations, _ = env.reset(seed=0)
        status = observations["meta"]["runtime_status"]
        assert {row["event_id"] for row in status["sensor_channels"]} == {"sensor_loss"}
        assert {row["event_id"] for row in status["actuator_channels"]} == {"actuator_loss"}
        assert {row["event_id"] for row in status["communication_links"]} == {"community_link_loss"}
        assert {row["event_id"] for row in status["asset_availability"]} == {"asset_unavailable"}
        assert status["asset_connections"]
        assert all("health" not in row for rows in status.values() if isinstance(rows, list) for row in rows)
    finally:
        env.close()


def test_entity_action_execution_distinguishes_requested_and_post_channel_values(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="runtime_action_execution", interface="entity")
    _write_events(
        schema,
        [
            _event(
                module="action",
                target_type="storage",
                target_id="Building_1",
                target_feature="electrical_storage",
                mode="dropout",
                event_domain="ACTUATOR_CHANNEL",
            )
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        _, _, _, _, info = env.step(_storage_action(env, 0.8))
        execution = info["entity_action_execution"]
        assert execution["version"] == "entity_action_execution_v1"
        storage = next(
            entry
            for entry in execution["entries"]
            if entry["action_name"] == "electrical_storage"
        )
        assert storage["requested_value"] == pytest.approx(0.8)
        assert storage["post_channel_value"] == pytest.approx(0.0)
        assert storage["limited_value"] == pytest.approx(0.0)
        assert storage["applied_power_kw"] == pytest.approx(0.0)
        assert "actuator_channel_modified" in storage["limitation_reasons"]
        assert info["topology_events_applied"] == []
    finally:
        env.close()


def test_action_execution_capture_is_entity_only_and_reuses_nominal_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    flat_schema = _copy_schema(
        tmp_path,
        name="runtime_execution_flat_fast_path",
        interface="flat",
        enabled=False,
    )
    _write_events(flat_schema, [_event()])
    flat = CityLearnEnv(
        _clean_schema(flat_schema),
        central_agent=True,
        episode_time_steps=4,
        random_seed=0,
    )
    flat_calls = 0
    flat_capture = flat._runtime_service._entity_action_records

    def count_flat(actions):
        nonlocal flat_calls
        flat_calls += 1
        return flat_capture(actions)

    monkeypatch.setattr(flat._runtime_service, "_entity_action_records", count_flat)
    try:
        flat.reset(seed=0)
        flat.step(_zero_actions(flat))
        assert flat_calls == 0
    finally:
        flat.close()

    entity_schema = _copy_schema(
        tmp_path,
        name="runtime_execution_entity_fast_path",
        interface="entity",
        enabled=False,
    )
    _write_events(entity_schema, [_event()])
    entity = CityLearnEnv(
        _clean_schema(entity_schema),
        central_agent=True,
        episode_time_steps=4,
        random_seed=0,
    )
    entity_calls = 0
    entity_capture = entity._runtime_service._entity_action_records

    def count_entity(actions):
        nonlocal entity_calls
        entity_calls += 1
        return entity_capture(actions)

    monkeypatch.setattr(entity._runtime_service, "_entity_action_records", count_entity)
    try:
        entity.reset(seed=0)
        _, _, _, _, info = entity.step(_zero_actions(entity))
        assert entity_calls == 1
        assert info["entity_action_execution"]["version"] == "entity_action_execution_v1"
    finally:
        entity.close()


@pytest.mark.parametrize(
    "mode,kwargs,input_value,expected",
    [
        ("dropout", {}, 0.8, 0.0),
        ("bias", {"value": 0.3}, 0.2, 0.5),
        ("clip", {"min_value": -0.1, "max_value": 0.1}, 0.8, 0.1),
    ],
)
def test_action_channel_dropout_bias_and_clip(tmp_path: Path, mode: str, kwargs: Mapping, input_value: float, expected: float):
    schema = _copy_schema(tmp_path, name=f"action_{mode}")
    _write_events(
        schema,
        [
            _event(
                module="action",
                target_type="storage",
                target_id="*",
                target_feature="electrical_storage",
                mode=mode,
                **kwargs,
            )
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        parsed = [{"electrical_storage_action": input_value}]
        applied = env._robustness_service.apply_actions(parsed)
        assert applied[0]["electrical_storage_action"] == pytest.approx(expected)
        assert parsed[0]["electrical_storage_action"] == pytest.approx(input_value)
    finally:
        env.close()


def test_action_channel_noise_stuck_and_delay(tmp_path: Path):
    noise_schema = _copy_schema(tmp_path, name="action_noise")
    _write_events(
        noise_schema,
        [_event(module="action", target_type="storage", target_id="*", target_feature="electrical_storage", mode="noise", std=0.25)],
    )
    noise_env = CityLearnEnv(_clean_schema(noise_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    stuck_schema = _copy_schema(tmp_path, name="action_stuck")
    _write_events(
        stuck_schema,
        [_event(module="action", target_type="storage", target_id="*", target_feature="electrical_storage", mode="stuck", end=1)],
    )
    stuck_env = CityLearnEnv(_clean_schema(stuck_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    delay_schema = _copy_schema(tmp_path, name="action_delay")
    _write_events(
        delay_schema,
        [
            _event(
                module="action",
                target_type="storage",
                target_id="*",
                target_feature="electrical_storage",
                start=1,
                end=1,
                mode="delay",
                delay_steps=1,
            )
        ],
    )
    delay_env = CityLearnEnv(_clean_schema(delay_schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        noise_env.reset(seed=0)
        first = noise_env._robustness_service.apply_actions([{"electrical_storage_action": 0.2}])[0]["electrical_storage_action"]
        second = noise_env._robustness_service.apply_actions([{"electrical_storage_action": 0.2}])[0]["electrical_storage_action"]
        assert first == pytest.approx(second)
        assert first != pytest.approx(0.2)

        stuck_env.reset(seed=0)
        stuck_env.step(_storage_action(stuck_env, 0.5))
        stuck_env.step(_storage_action(stuck_env, 0.0))
        assert stuck_env.buildings[0].electrical_storage_electricity_consumption[1] > 0.0

        delay_env.reset(seed=0)
        delay_env.step(_storage_action(delay_env, 0.7))
        delay_env.step(_storage_action(delay_env, 0.0))
        assert delay_env.buildings[0].electrical_storage_electricity_consumption[1] > 0.0
    finally:
        noise_env.close()
        stuck_env.close()
        delay_env.close()


def test_asset_unavailable_telemetry_and_control_without_dynamic_topology(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="asset_both", interface="entity")
    _write_events(
        schema,
        [
            _event(
                module="asset",
                target_type="storage",
                target_id="*",
                target_feature="both",
                mode="unavailable",
                replacement_value=-777.0,
            )
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)
        assert np.allclose(obs["tables"]["storage"], -777.0)
        env.step(_storage_action(env, 1.0))
        assert env.buildings[0].electrical_storage_electricity_consumption[0] == pytest.approx(0.0)
        counts = env._robustness_service.history[0]
        assert len(counts["asset"]) == 1
        assert len(counts["dropout"]) >= 1
        kpis = env.evaluate_v2(include_business_as_usual=False)
        assert _kpi_value(
            kpis,
            "district_robustness_asset_unavailable_time_step_count",
        ) == pytest.approx(1.0)
    finally:
        env.close()


def test_business_as_usual_reference_accepts_entity_only_targets_with_static_topology(tmp_path: Path):
    # An EV SOC event only resolves against the entity `ev` table. With static topology and no
    # demand response the BAU reference used to be built flat and rejected the evaluated schema.
    schema = _copy_schema(tmp_path, name="bau_entity_ev_soc", interface="entity")
    schema["topology_mode"] = "static"
    _write_events(
        schema,
        [
            _event(
                event_id="ev_soc_noise",
                target_type="ev",
                target_id="*",
                target_feature="soc",
                end=3,
                mode="noise",
                std=0.005,
            )
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        assert env.interface == "entity"
        assert env.topology_mode == "static"
        env.reset(seed=0)
        while not env.terminated:
            env.step(_zero_actions(env))
        sidecar = env._business_as_usual_baseline_service._new_sidecar_env()
        try:
            assert sidecar.interface == "entity"
        finally:
            sidecar.close()
        kpis = env.evaluate_v2()
        assert not kpis.empty
    finally:
        env.close()


def test_observation_only_robustness_keeps_reward_on_real_state(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="reward_real_state")
    _write_events(schema, [_event(replacement_value=-9999.0)])
    robust = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)
    baseline = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        robust.reset(seed=0)
        baseline.reset(seed=0)
        _, robust_reward, *_ = robust.step(_zero_actions(robust))
        _, baseline_reward, *_ = baseline.step(_zero_actions(baseline))
        assert np.allclose(np.asarray(robust_reward), np.asarray(baseline_reward))
        assert robust.net_electricity_consumption[0] == pytest.approx(baseline.net_electricity_consumption[0])
    finally:
        robust.close()
        baseline.close()


def test_robustness_kpis_count_events_steps_and_corruptions(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="kpis")
    _write_events(
        schema,
        [
            _event(event_id="obs", replacement_value=-9999.0),
            _event(
                event_id="act",
                module="action",
                target_type="storage",
                target_id="*",
                target_feature="electrical_storage",
                mode="dropout",
            ),
        ],
    )
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        env.step(_storage_action(env, 1.0))
        kpis = env.evaluate_v2(include_business_as_usual=False)

        assert _kpi_value(kpis, "district_robustness_events_count") == pytest.approx(2.0)
        assert _kpi_value(kpis, "district_robustness_active_time_step_count") == pytest.approx(1.0)
        assert _kpi_value(kpis, "district_robustness_observation_corruption_count") == pytest.approx(1.0)
        assert _kpi_value(kpis, "district_robustness_action_corruption_count") == pytest.approx(1.0)
        assert _kpi_value(kpis, "district_robustness_missing_observation_count") == pytest.approx(1.0)
        assert _kpi_value(kpis, "district_robustness_action_dropout_count") == pytest.approx(1.0)
        assert _kpi_value(kpis, "building_robustness_action_dropout_count", level="building", name="Building_1") == pytest.approx(1.0)
    finally:
        env.close()


def test_multi_community_keeps_robustness_independent_and_sums_count_kpis(tmp_path: Path):
    schema_a = _copy_schema(tmp_path, name="community_a", interface="entity")
    _write_events(schema_a, [_event(event_id="a_obs", replacement_value=-101.0)])
    schema_b = _copy_schema(tmp_path, name="community_b", interface="entity")
    _write_events(schema_b, [_event(event_id="b_obs", replacement_value=-202.0)])

    env = MultiCommunityEnv(
        communities=[
            {"community_id": "a", "schema": _clean_schema(schema_a), "env_kwargs": {"central_agent": True, "episode_time_steps": 4, "random_seed": 0}},
            {"community_id": "b", "schema": _clean_schema(schema_b), "env_kwargs": {"central_agent": True, "episode_time_steps": 4, "random_seed": 0}},
        ]
    )

    try:
        observations, _ = env.reset(seed=0)
        assert observations["a"]["meta"]["robustness"]["active_event_ids"] == ["a_obs"]
        assert observations["b"]["meta"]["robustness"]["active_event_ids"] == ["b_obs"]

        kpis = env.evaluate_v2(include_business_as_usual=False)
        portfolio = kpis[
            (kpis["community_id"] == "__portfolio__")
            & (kpis["cost_function"] == "portfolio_robustness_events_count")
        ]
        assert len(portfolio) == 1
        assert portfolio["value"].iloc[0] == pytest.approx(2.0)
    finally:
        env.close()


def test_robustness_history_is_sparse_for_long_runs(tmp_path: Path):
    schema = _copy_schema(tmp_path, name="sparse_history")
    _write_events(schema, [_event(start=5, end=5, replacement_value=-9999.0)])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        env.reset(seed=0)
        while int(env.time_step) < 7:
            env.step(_zero_actions(env))

        assert list(env._robustness_service.history.keys()) == [5]
    finally:
        env.close()


@pytest.mark.parametrize("interface", ["flat", "entity"])
def test_packaged_2022_robustness_dataset_loads_in_flat_and_entity(interface: str):
    env = CityLearnEnv(
        str(PACKAGED_2022_ROBUSTNESS_SCHEMA_PATH),
        interface=interface,
        episode_time_steps=8,
        render_mode="none",
    )

    try:
        observations, _ = env.reset(seed=0)
        assert env._robustness_service.enabled is True
        assert len(env.electric_vehicles) == 0
        assert env.topology_mode == "static"
        if interface == "entity":
            assert env.entity_specs["observation_bundles"]["entity_robustness"]["active"] is True
            assert "robustness" in observations["meta"]

        for _ in range(3):
            observations, *_ = env.step(_zero_actions(env))
    finally:
        env.close()
