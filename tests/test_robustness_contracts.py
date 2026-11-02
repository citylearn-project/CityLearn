"""Fault bounds, declared dynamic targets and explicit counter populations."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.balance_audit import IndependentBalanceAudit
from test_deferrable_appliance_integration import _schema_with_deferrable_appliance
from test_independent_balances import commands, scenario
from test_robustness import _copy_schema, _clean_schema, _event, _write_events, _zero_actions


def _load(schema, *, steps=8, central_agent=True):
    return CityLearnEnv(
        _clean_schema(schema), central_agent=central_agent, random_seed=7,
        simulation_end_time_step=steps - 1, episode_time_steps=steps,
        physics_invariant_checks=True, render_mode="none", export_kpis_on_episode_end=False,
    )


def _value_and_bounds(env, observations, feature="non_shiftable_load"):
    if env.interface == "flat":
        column = env.observation_names[0].index(feature)
        box = env.observation_space[0]
        return float(observations[0][column]), float(box.low[column]), float(box.high[column])
    table = next(name for name, spec in env.entity_specs["tables"].items() if feature in spec["features"])
    column = env.entity_specs["tables"][table]["features"].index(feature)
    box = env.observation_space["tables"][table]
    return float(observations["tables"][table][0, column]), float(box.low[0, column]), float(box.high[0, column])


@pytest.mark.parametrize("interface,central", [("flat", True), ("flat", False), ("entity", True)])
@pytest.mark.parametrize("specs", [
    [("bias", {"value": 0.25})],
    [("bias", {"value": -0.35})],
    [("noise", {"std": 0.25})],
    [("noise", {"std": 0.0})],
    [("missing", {"replacement_value": 20.0})],
    [("clip", {"min_value": 5.0, "max_value": 6.0})],
    [("bias", {"value": 0.1}), ("bias", {"value": 0.3})],
    [("missing", {"replacement_value": -9.0}), ("bias", {"value": 0.1})],
    [("noise", {"std": 2.0}), ("clip", {"min_value": -0.1, "max_value": 0.1})],
    [("bias", {"value": 2.0, "end": 0}), ("stuck", {})],
])
def test_fault_envelopes_cover_composed_values_without_changing_physics(
    tmp_path, interface, central, specs
):
    schema = _copy_schema(tmp_path, interface=interface)
    rows = [_event(event_id=f"fault_{i}", mode=mode, **{"end": 3, **parameters})
            for i, (mode, parameters) in enumerate(specs)]
    _write_events(schema, rows)
    baseline_schema = deepcopy(schema)
    baseline_schema["robustness"]["enabled"] = False
    env, baseline = _load(schema, steps=4, central_agent=central), _load(baseline_schema, steps=4, central_agent=central)
    try:
        observations, _ = env.reset(seed=7)
        baseline.reset(seed=7)
        value, low, high = _value_and_bounds(env, observations)
        assert low <= value <= high
        if specs[0][0] == "noise" and specs[0][1]["std"] > 0:
            assert low == -np.inf and high == np.inf
        else:
            assert np.isfinite([low, high]).all()
        _, low, high = _value_and_bounds(env, observations, "month")
        _, base_low, base_high = _value_and_bounds(baseline, baseline.observations, "month")
        assert (low, high) == (base_low, base_high)
        while not env.terminated:
            observations, reward, *_ = env.step(_zero_actions(env))
            _, baseline_reward, *_ = baseline.step(_zero_actions(baseline))
            value, low, high = _value_and_bounds(env, observations)
            assert low <= value <= high
            np.testing.assert_array_equal(reward, baseline_reward)
        np.testing.assert_array_equal(env.net_electricity_consumption, baseline.net_electricity_consumption)
        assert env._provenance_service.summary() == baseline._provenance_service.summary()
    finally:
        env.close()
        baseline.close()


@pytest.mark.parametrize("hidden", [False, True])
def test_bounds_do_not_leak_fault_targets_or_change_edges(tmp_path, hidden):
    schema = _copy_schema(tmp_path, interface="entity")
    _write_events(schema, [_event(mode="noise", std=1.0)])
    if hidden:
        schema["robustness"]["agent_observation_contract"] = {
            "mode": "hidden_faults", "features": {"building": ["non_shiftable_load"]},
        }
    env = _load(schema)
    try:
        obs, _ = env.reset(seed=7)
        original = env._entity_service.observation_space
        adjusted = env.observation_space
        assert adjusted["edges"] is original["edges"]
        for table, box in adjusted["tables"].spaces.items():
            if hidden:
                assert np.isneginf(box.low).all() and np.isposinf(box.high).all()
                assert box.contains(obs["tables"][table])
        if hidden:
            assert "robustness" not in obs["meta"] and "runtime_status" not in obs["meta"]
            assert "event_1" not in json.dumps(obs["meta"])
        assert env.get_metadata()["robustness"]["counter_contract"]["definition_version"] == "robustness-audit-v1"
    finally:
        env.close()


@pytest.mark.parametrize("cloned", [False, True])
@pytest.mark.parametrize("mode", ["bias", "stuck"])
def test_future_member_absence_return_and_reset_have_exact_populations(tmp_path, cloned, mode):
    schema = _copy_schema(tmp_path, interface="entity")
    schema["topology_mode"] = "dynamic"
    if not cloned:
        second = deepcopy(schema["buildings"]["Building_1"])
        second.update(include=False, chargers={})
        schema["buildings"]["Building_2"] = second
    events = [
        dict(id="join", time_step=2, operation="add_member", target_member_id="Building_2", **({"source_member_id": "Building_1"} if cloned else {})),
        dict(id="leave", time_step=4, operation="remove_member", target_member_id="Building_2"),
        dict(id="return", time_step=6, operation="add_member", target_member_id="Building_2"),
    ]
    schema["topology_events"] = events
    _write_events(schema, [
        _event(event_id="sensor", target_id="Building_2", mode=mode, value=0.25, end=7),
        _event(event_id="control", module="asset", target_type="storage", target_id="Building_2", target_feature="control", mode="unavailable", end=7),
    ])
    env = _load(schema)
    try:
        reports = []
        for _ in range(2):
            obs, _ = env.reset(seed=7)
            while not env.terminated:
                meta = obs["meta"]["robustness"]
                if env.time_step in (0, 1, 4, 5):
                    assert meta["applied_event_ids"] == []
                obs, *_ = env.step(_zero_actions(env))
            report = env.get_robustness_audit()
            district = report["district"]
            assert district["observation_index_count"] == 8
            assert district["executed_interval_count"] == 7
            assert district["terminal_observation_count"] == 1
            assert district["window_observation_event_step_count"] == 8
            assert district["applied_observation_event_step_count"] == 4
            assert district["observation_application_coverage_ratio"] == 0.5
            assert district["window_action_event_step_count"] == 7
            assert district["applied_action_event_step_count"] == 3
            assert district["action_application_coverage_ratio"] == pytest.approx(3 / 7)
            assert set(env._robustness_service.history) == {2, 3, 6, 7}
            assert report["legacy"]["buildings"]["Building_2"]["robustness_observation_corruption_count"] == 4
            assert report["executed_intervals"]["buildings"]["Building_2"]["robustness_observation_corruption_count"] == 3
            assert env.evaluate_v2(include_business_as_usual=False).attrs["robustness_audit"] == report
            assert env.get_robustness_audit() == report  # Queries are passive/idempotent.
            reports.append(report)
        assert reports[0] == reports[1]
    finally:
        env.close()


@pytest.mark.parametrize("asset_type,source_id,target_id,table,feature", [
    ("charger", "charger_1_1", "later", "charger", "connected_state"),
    ("deferrable_appliance", "washer_1", "later", "deferrable_appliance", "pending"),
    ("electrical_storage", "electrical_storage", "electrical_storage", "storage", "soc"),
    ("pv", "pv", "pv", "pv", "generation_power_kw"),
])
def test_future_assets_removal_reinstallation_and_absent_rows(tmp_path, asset_type, source_id, target_id, table, feature):
    path = _schema_with_deferrable_appliance(tmp_path)
    schema = json.loads(path.read_text())
    schema.update(interface="entity", topology_mode="dynamic", observation_bundles={"entity_core_electrical": {"active": True}})
    schema["buildings"]["Building_1"]["pv"] = {"type": "citylearn.energy_model.PV", "autosize": False, "attributes": {"nominal_power": 2.0}}
    common = dict(target_member_id="Building_1", target_asset_type=asset_type)
    schema["topology_events"] = [
        dict(id="remove_source", time_step=0, operation="remove_asset", target_asset_id=source_id, **common),
        dict(id="add", time_step=2, operation="add_asset", target_asset_id=target_id, source_asset_id=source_id, **common),
        dict(id="remove", time_step=4, operation="remove_asset", target_asset_id=target_id, **common),
        dict(id="return", time_step=6, operation="add_asset", target_asset_id=target_id, source_asset_id=source_id, **common),
    ]
    events_file = Path(schema["root_directory"]) / "faults.csv"
    pd.DataFrame([_event(target_type=table, target_id=f"Building_1/{target_id}", target_feature=feature, mode="bias", value=0.25, end=7)]).to_csv(events_file, index=False)
    schema["robustness"] = {"enabled": True, "events_file": str(events_file)}
    env = _load(schema)
    try:
        for _ in range(2):
            env.reset(seed=7)
            while not env.terminated:
                env.step(_zero_actions(env))
            assert set(env._robustness_service.history) == {2, 3, 6, 7}
            assert env.get_robustness_audit()["district"]["applied_observation_event_step_count"] == 4
    finally:
        env.close()


@pytest.mark.parametrize("interface", ["flat", "entity"])
def test_terminal_telemetry_is_separate_from_executed_intervals(tmp_path, interface):
    schema = _copy_schema(tmp_path, interface=interface)
    _write_events(schema, [_event(start=1, end=1)])
    env = _load(schema, steps=2)
    try:
        env.reset(seed=7)
        env.step(_zero_actions(env))
        audit = env.get_robustness_audit()
        assert audit["legacy"]["district"]["robustness_events_count"] == 1
        assert audit["executed_intervals"]["district"]["robustness_events_count"] == 0
        assert audit["district"]["observation_index_count"] == 2
        assert audit["district"]["executed_interval_count"] == 1
        assert audit["district"]["terminal_observation_count"] == 1
        assert audit["district"]["action_application_coverage_ratio"] is None
        for _ in range(3):
            env.observations
        assert env.get_robustness_audit() == audit
        json.dumps(audit, allow_nan=False)
    finally:
        env.close()


@pytest.mark.parametrize("outage", [False, True])
@pytest.mark.parametrize("fast", [False, True])
def test_sensor_faults_and_dynamic_members_keep_physics_and_reward(tmp_path, outage, fast):
    initial = scenario(tmp_path, outage=outage, phase_limits=True, events=[
        dict(id="remove", time_step=2, operation="remove_member", target_member_id="Building_2"),
        dict(id="return", time_step=4, operation="add_member", target_member_id="Building_2"),
    ])
    schema = deepcopy(initial.schema)
    initial.close()
    path = tmp_path / "sensor.csv"
    pd.DataFrame([_event(target_id="Building_2", mode="noise", std=2.0, end=7)]).to_csv(path, index=False)
    schema["robustness"] = {"enabled": True, "events_file": str(path), "random_seed": 7}
    baseline_schema = deepcopy(schema)
    baseline_schema["robustness"]["enabled"] = False
    env, baseline = _load(schema), _load(baseline_schema)
    try:
        env.reset(seed=7)
        baseline.reset(seed=7)
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                payload = commands(env, [0.4, -0.2], start=env.time_step == 0)
                if fast:
                    env._runtime_service.step_without_feedback(payload)
                    baseline._runtime_service.step_without_feedback(payload)
                else:
                    _, reward, *_ = env.step(payload)
                    _, base_reward, *_ = baseline.step(payload)
                    np.testing.assert_array_equal(reward, base_reward)
            assert audit.finish()["status"] == "pass"
        np.testing.assert_array_equal(env.net_electricity_consumption, baseline.net_electricity_consumption)
        assert env._provenance_service.summary() == baseline._provenance_service.summary()
        if fast:
            assert env.get_robustness_audit()["district"]["observation_index_count"] == 1
    finally:
        env.close()
        baseline.close()


@pytest.mark.parametrize("interface", ["flat", "entity"])
def test_unknown_target_is_not_mistaken_for_an_inactive_target(tmp_path, interface):
    schema = _copy_schema(tmp_path, interface=interface)
    if interface == "entity":
        schema.update(topology_mode="dynamic", topology_events=[])
    _write_events(schema, [_event(module="asset", target_id="typo", target_feature="telemetry", mode="unavailable")])
    with pytest.raises(ValueError, match="target does not match"):
        _load(schema)


@pytest.mark.parametrize("interface", ["flat", "entity"])
@pytest.mark.parametrize("enabled", [False, True])
def test_forecast_bounds_respect_module_flags_and_feature_kind(tmp_path, interface, enabled):
    schema = _copy_schema(tmp_path, interface=interface, modules={"forecasts": enabled})
    feature = "electricity_pricing_predicted_1"
    _write_events(schema, [_event(module="forecast", target_type="district", target_id="*", target_feature=feature, mode="bias", value=2.5, end=7)])
    env = _load(schema)
    try:
        obs, _ = env.reset(seed=7)
        value, low, high = _value_and_bounds(env, obs, feature)
        assert low <= value <= high
        if interface == "flat":
            baseline = env._get_flat_observation_space()[0]
            col = env.observation_names[0].index(feature)
            original_high = float(baseline.high[col])
        else:
            col = env.entity_specs["tables"]["district"]["features"].index(feature)
            original_high = float(env._entity_service.observation_space["tables"]["district"].high[0, col])
        assert high >= original_high + 2.5 if enabled else high == original_high
    finally:
        env.close()


def test_future_ev_telemetry_only_applies_when_its_charger_is_present(tmp_path):
    schema = _copy_schema(tmp_path, interface="entity")
    common = dict(target_member_id="Building_1", target_asset_type="charger", target_asset_id="charger_1_1")
    schema.update(topology_mode="dynamic", topology_events=[
        dict(id="remove", time_step=0, operation="remove_asset", **common),
        dict(id="return", time_step=2, operation="add_asset", source_asset_id="charger_1_1", **common),
    ])
    _write_events(schema, [_event(target_type="ev", target_id="Electric_Vehicle_1", target_feature="soc", mode="bias", value=0.25, end=7)])
    env = _load(schema)
    try:
        env.reset(seed=7)
        assert not env.electric_vehicles
        while not env.terminated:
            env.step(_zero_actions(env))
        assert set(env._robustness_service.history) == set(range(2, 8))
    finally:
        env.close()


@pytest.mark.parametrize("action_inactive,bad_feature", [(True, False), (False, True)])
def test_future_target_validation_rejects_inactive_actions_and_unknown_features(tmp_path, action_inactive, bad_feature):
    schema = _copy_schema(tmp_path, interface="entity")
    building = deepcopy(schema["buildings"]["Building_1"])
    building.update(include=False, chargers={})
    if action_inactive:
        building["inactive_actions"] = ["electrical_storage"]
    schema["buildings"]["Building_2"] = building
    schema.update(topology_mode="dynamic", topology_events=[
        dict(id="join", time_step=2, operation="add_member", target_member_id="Building_2"),
    ])
    _write_events(schema, [_event(module="action", target_type="storage", target_id="Building_2", target_feature="typo" if bad_feature else "electrical_storage", mode="bias", value=0.2, end=7)])
    with pytest.raises(ValueError, match="target does not match"):
        _load(schema)


def test_events_outside_presence_or_episode_have_no_false_applications(tmp_path):
    schema = _copy_schema(tmp_path, interface="entity", modules={"forecasts": False})
    second = deepcopy(schema["buildings"]["Building_1"])
    second.update(include=False, chargers={})
    schema["buildings"]["Building_2"] = second
    schema.update(topology_mode="dynamic", topology_events=[
        dict(id="join", time_step=4, operation="add_member", target_member_id="Building_2"),
    ])
    _write_events(schema, [
        _event(event_id="absent", target_id="Building_2", start=0, end=2),
        _event(event_id="outside", start=20, end=30),
        _event(event_id="disabled", module="forecast", target_type="district", target_id="*", target_feature="electricity_pricing_predicted_1", end=7),
    ])
    env = _load(schema)
    try:
        env.reset(seed=7)
        while not env.terminated:
            env.step(_zero_actions(env))
        audit = env.get_robustness_audit()
        assert audit["district"]["configured_event_count"] == 3
        assert audit["district"]["enabled_event_count"] == 2
        assert audit["district"]["scheduled_event_count"] == 1
        assert audit["district"]["window_observation_event_step_count"] == 3
        assert audit["district"]["observation_application_coverage_ratio"] == 0.0
        assert not env._robustness_service.history
    finally:
        env.close()


def test_declared_view_does_not_mutate_the_runtime_inventory(tmp_path):
    from citylearn.internal.robustness_targets import declared_target_view
    schema = _copy_schema(tmp_path, interface="entity")
    schema.update(topology_mode="dynamic", topology_events=[
        dict(id="new", time_step=4, operation="add_member", target_member_id="New", source_member_id="Building_1"),
    ])
    _write_events(schema, [_event()])
    env = _load(schema)
    try:
        building = env.buildings[0]
        before = (env.topology_version, env._topology_service.event_log, env.get_metadata(),
                  building.active_actions, building.active_observations,
                  building.electrical_storage.soc.copy(), dict(building._charger_lookup))
        view = declared_target_view(env._robustness_service)
        assert [b.name for b in view.env.buildings] == ["Building_1", "New"]
        view.env.entity_specs
        after = (env.topology_version, env._topology_service.event_log, env.get_metadata(),
                 building.active_actions, building.active_observations,
                 building.electrical_storage.soc.copy(), dict(building._charger_lookup))
        assert before[:5] == after[:5]
        np.testing.assert_array_equal(before[5], after[5])
        assert before[6] == after[6]
        assert list(env._topology_service.member_pool) == ["Building_1"]
    finally:
        env.close()


@pytest.mark.parametrize("mode", ["known_faults", "hidden_faults"])
def test_feature_only_exposed_by_a_future_member_is_valid_across_its_lifecycle(tmp_path, mode):
    schema = _copy_schema(tmp_path, interface="entity")
    second = deepcopy(schema["buildings"]["Building_1"])
    second.update(include=False, chargers={})
    schema["buildings"]["Building_2"] = second
    schema["buildings"]["Building_1"]["inactive_observations"] = ["non_shiftable_load"]
    schema.update(topology_mode="dynamic", topology_events=[
        dict(id="join", time_step=2, operation="add_member", target_member_id="Building_2"),
        dict(id="leave", time_step=4, operation="remove_member", target_member_id="Building_2"),
    ])
    schema["robustness"]["agent_observation_contract"] = {
        "mode": mode, "features": {"building": ["non_shiftable_load"]},
    }
    _write_events(schema, [_event(target_id="Building_2", mode="bias", value=0.25, end=7)])
    env = _load(schema)
    try:
        env.reset(seed=7)
        while not env.terminated:
            obs, *_ = env.step(_zero_actions(env))
            if mode == "hidden_faults":
                assert "robustness" not in obs["meta"]
        assert set(env._robustness_service.history) == {2, 3}
    finally:
        env.close()


@pytest.mark.parametrize("file_format", ["csv", "parquet"])
def test_export_preserves_legacy_kpis_and_writes_versioned_robustness_audit(tmp_path, file_format):
    schema = _copy_schema(tmp_path, interface="entity")
    _write_events(schema, [_event(start=1, end=1)])
    env = CityLearnEnv(
        _clean_schema(schema), simulation_end_time_step=1, episode_time_steps=2,
        render_directory=tmp_path / "exports", render_session_name="audit",
        render_file_format=file_format, physics_invariant_checks=True,
        export_kpis_on_episode_end=False,
    )
    try:
        env.reset(seed=7)
        env.step(_zero_actions(env))
        snapshot = env.get_robustness_audit()
        env.export_final_kpis(include_business_as_usual=False)
        root = Path(env.new_folder_path)
        sidecar = root / "exported_kpis.robustness.json"
        assert json.loads(sidecar.read_text()) == snapshot
        path = root / f"exported_kpis.{file_format}"
        frame = pd.read_parquet(path) if file_format == "parquet" else pd.read_csv(path)
        value = frame.loc[frame.KPI == "district_robustness_events_count", "District"].item()
        assert value == 1.0
        assert snapshot["executed_intervals"]["district"]["robustness_events_count"] == 0.0
        assert env.get_robustness_audit() == snapshot
    finally:
        env.close()
