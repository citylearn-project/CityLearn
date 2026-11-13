"""Fault precedence, fail-fast event validation and physical regressions."""

from copy import deepcopy
import json
import re

import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.balance_audit import IndependentBalanceAudit
from test_deferrable_appliance_integration import (
    _schema_with_deferrable_appliance,
    _zero_entity_payload,
)
from test_independent_balances import commands, scenario
from test_robustness import (
    PACKAGED_2022_ROBUSTNESS_SCHEMA_PATH,
    _clean_schema,
    _copy_schema,
    _event,
    _kpi_value,
    _storage_action,
    _write_events,
    _zero_actions,
)


@pytest.mark.parametrize("interface", ["flat", "entity"])
@pytest.mark.parametrize("asset_first", [True, False])
@pytest.mark.parametrize("feature", ["control", "both"])
@pytest.mark.parametrize(
    "mode,parameters",
    [
        ("bias", {"value": 1.0}),
        ("noise", {"std": 0.5}),
        ("clip", {"min_value": 0.3, "max_value": 0.8}),
        ("stuck", {}),
        ("delay", {"delay_steps": 1}),
        ("dropout", {}),
    ],
)
def test_asset_control_unavailability_wins_after_action_channels(
    tmp_path, interface, asset_first, feature, mode, parameters
):
    schema = _copy_schema(tmp_path, interface=interface)
    asset = _event(
        event_id="asset",
        module="asset",
        target_type="storage",
        target_id="*",
        target_feature=feature,
        start=1,
        end=1,
        mode="unavailable",
    )
    channel = _event(
        event_id="channel",
        module="action",
        target_type="storage",
        target_id="*",
        target_feature="electrical_storage",
        start=1,
        end=1,
        mode=mode,
        **parameters,
    )
    _write_events(schema, [asset, channel] if asset_first else [channel, asset])
    env = CityLearnEnv(
        _clean_schema(schema),
        central_agent=True,
        simulation_end_time_step=3,
        episode_time_steps=4,
        random_seed=0,
        physics_invariant_checks=True,
        export_kpis_on_episode_end=False,
    )
    try:
        episodes = []
        histories = []
        for _ in range(2):
            env.reset(seed=0)
            for step, value in enumerate([0.4, 0.8, 0.2]):
                _, _, _, _, info = env.step(_storage_action(env, value))
                if step == 1 and interface == "entity":
                    entry = next(
                        row for row in info["entity_action_execution"]["entries"]
                        if row["action_name"] == "electrical_storage"
                    )
                    assert entry["requested_value"] == pytest.approx(value)
                    assert entry["post_channel_value"] == 0.0
                    assert entry["applied_power_kw"] == 0.0
            energy = np.asarray(
                env.buildings[0].electrical_storage_electricity_consumption[:3]
            ).copy()
            assert energy[0] > 0.0
            assert energy[1] == 0.0
            assert energy[2] > 0.0  # Control returns after the event ends.
            record = env._robustness_service.history[1]
            assert record["event_ids"] == ["asset", "channel"]
            assert len(record["action"]) == 2
            assert len(record["asset"]) == 1
            episodes.append(energy)
            histories.append(env._robustness_service.history)
        np.testing.assert_array_equal(*episodes)
        assert histories[0] == histories[1]
    finally:
        env.close()


PV_OUTAGE_STEPS = range(36, 40)  # global steps of the outage, inside the 32-43 episode


def _pv_outage_rollout(tmp_path, *, interface, feature=None):
    """Zero-action rollout of two 2022 buildings, with Building_1's PV unavailable at PV_OUTAGE_STEPS."""

    schema = json.loads(PACKAGED_2022_ROBUSTNESS_SCHEMA_PATH.read_text())
    schema["root_directory"] = str(PACKAGED_2022_ROBUSTNESS_SCHEMA_PATH.parent)
    schema["interface"] = interface
    for name, building in schema["buildings"].items():
        building["include"] = name in {"Building_1", "Building_2"}
    if feature is None:
        schema["robustness"]["enabled"] = False
    else:
        events_file = tmp_path / f"pv_outage_{interface}_{feature}.csv"
        pd.DataFrame([_event(
            event_id="pv_out", module="asset", target_type="pv", target_id="Building_1",
            target_feature=feature, start=PV_OUTAGE_STEPS[0], end=PV_OUTAGE_STEPS[-1], mode="unavailable",
        )]).to_csv(events_file, index=False)
        schema["robustness"]["events_file"] = str(events_file)
    env = CityLearnEnv(
        schema, central_agent=True, simulation_start_time_step=32, simulation_end_time_step=43, random_seed=0,
    )
    env.reset(seed=0)
    while not env.terminated:
        env.step(_zero_actions(env))
    return env


@pytest.mark.parametrize("interface,feature", [("flat", "control"), ("flat", "both"), ("entity", "both")])
def test_pv_control_unavailability_stops_generation_and_counts_in_balance(tmp_path, interface, feature):
    reference = _pv_outage_rollout(tmp_path, interface=interface)
    faulted = _pv_outage_rollout(tmp_path, interface=interface, feature=feature)
    try:
        start = faulted.episode_tracker.episode_start_time_step
        outage = np.isin(np.arange(faulted.time_step) + start, PV_OUTAGE_STEPS)
        steps = faulted.time_step
        ref, out = reference.buildings[0], faulted.buildings[0]
        ref_pv = np.asarray(ref.solar_generation[:steps], dtype=float)
        out_pv = np.asarray(out.solar_generation[:steps], dtype=float)
        assert outage.sum() == 4 and np.all(ref_pv[outage] < 0.0), "scenario must lose daytime generation"

        np.testing.assert_array_equal(out_pv[outage], 0.0)
        np.testing.assert_array_equal(out_pv[~outage], ref_pv[~outage])
        # The lost generation is bought from the grid; nothing else changes.
        np.testing.assert_allclose(
            np.asarray(out.net_electricity_consumption[:steps], dtype=float),
            np.asarray(ref.net_electricity_consumption[:steps], dtype=float) - np.where(outage, ref_pv, 0.0),
            rtol=0.0, atol=1.0e-5,
        )
        np.testing.assert_array_equal(
            np.asarray(faulted.buildings[1].net_electricity_consumption),
            np.asarray(reference.buildings[1].net_electricity_consumption),
        )

        kpis = faulted.evaluate_v2()
        assert _kpi_value(kpis, "district_robustness_asset_unavailable_time_step_count") == pytest.approx(4.0)
        # The business-as-usual reference runs in the same physical world, with the same outage.
        sidecar = faulted._business_as_usual_baseline_service.run().env.buildings[0]
        np.testing.assert_array_equal(np.asarray(sidecar.solar_generation[:steps], dtype=float)[outage], 0.0)

        faulted.reset(seed=0)  # The next episode starts from the dataset production again.
        np.testing.assert_array_equal(
            faulted.buildings[0]._Building__solar_generation, reference.buildings[0]._Building__solar_generation,
        )
    finally:
        reference.close()
        faulted.close()


def test_pv_telemetry_unavailability_keeps_generation(tmp_path):
    reference = _pv_outage_rollout(tmp_path, interface="entity")
    faulted = _pv_outage_rollout(tmp_path, interface="entity", feature="telemetry")
    try:
        np.testing.assert_array_equal(
            np.asarray(faulted.buildings[0].net_electricity_consumption),
            np.asarray(reference.buildings[0].net_electricity_consumption),
        )
        np.testing.assert_array_equal(
            np.asarray(faulted.buildings[0].solar_generation), np.asarray(reference.buildings[0].solar_generation),
        )
    finally:
        reference.close()
        faulted.close()


@pytest.mark.parametrize("asset_first", [True, False])
@pytest.mark.parametrize("outage", [True, False])
@pytest.mark.parametrize("fast", [True, False])
def test_unavailability_composes_with_bias_and_preserves_independent_balances(
    tmp_path, asset_first, outage, fast
):
    initial = scenario(tmp_path, outage=outage, phase_limits=True)
    schema = deepcopy(initial.schema)
    initial.close()
    assets = [
        _event(
            event_id=f"unavailable_{target}", module="asset", target_type=target,
            target_id="*", target_feature="control", start=1, end=3,
            mode="unavailable",
        )
        for target in ["storage", "charger"]
    ]
    channels = [
        _event(
            event_id=f"bias_{target}", module="action", target_type=target,
            target_id="*", target_feature="*", start=1, end=3,
            mode="bias", value=0.8,
        )
        for target in ["storage", "charger"]
    ]
    events_file = tmp_path / "composition.csv"
    pd.DataFrame(assets + channels if asset_first else channels + assets).to_csv(
        events_file, index=False
    )
    schema["robustness"] = {"enabled": True, "events_file": str(events_file), "random_seed": 7}
    schema["community_market"]["grid_export_price"] = 0.0
    env = CityLearnEnv(schema, random_seed=19, offline=True)
    try:
        env.reset(seed=19)
        with IndependentBalanceAudit(env) as audit:
            step = env._runtime_service.step_without_feedback if fast else env.step
            while not env.terminated:
                step(commands(env, [0.4, 0.3], start=env.time_step == 0))
            result = audit.finish()
        assert result["status"] == "pass"
        assert result["completed_intervals"] == 7
        assert result["checks"] > 150
        for building in env.buildings:
            np.testing.assert_array_equal(
                building.electrical_storage_electricity_consumption[1:4], 0.0
            )
            for charger in building.electric_vehicle_chargers or []:
                np.testing.assert_array_equal(charger.electricity_consumption[1:4], 0.0)
    finally:
        env.close()


@pytest.mark.parametrize("reverse,expected", [(False, 0.5), (True, 0.8)])
def test_noncommuting_action_channels_keep_file_order(tmp_path, reverse, expected):
    schema = _copy_schema(tmp_path)
    events = [
        _event(
            event_id="bias", module="action", target_type="storage", target_id="*",
            target_feature="electrical_storage", mode="bias", value=0.3,
        ),
        _event(
            event_id="clip", module="action", target_type="storage", target_id="*",
            target_feature="electrical_storage", mode="clip", max_value=0.5,
        ),
    ]
    _write_events(schema, events[::-1] if reverse else events)
    env = CityLearnEnv(_clean_schema(schema), episode_time_steps=4)
    try:
        parsed = [{"electrical_storage_action": 0.8}]
        applied = env._robustness_service.apply_actions(parsed)
        assert applied[0]["electrical_storage_action"] == pytest.approx(expected)
        assert parsed[0]["electrical_storage_action"] == 0.8
    finally:
        env.close()


@pytest.mark.parametrize("asset_first", [True, False])
@pytest.mark.parametrize("already_running", [True, False])
def test_appliance_control_outage_blocks_new_starts_but_not_a_running_cycle(
    tmp_path, asset_first, already_running
):
    path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=1)
    schema = json.loads(path.read_text())
    schema["interface"] = "entity"
    start = 1 if already_running else 0
    asset = _event(
        event_id="washer_unavailable", module="asset", target_type="deferrable_appliance",
        target_id="*", target_feature="control", start=start, end=1, mode="unavailable",
    )
    channel = _event(
        event_id="washer_bias", module="action", target_type="deferrable_appliance",
        target_id="*", target_feature="start", start=start, end=1, mode="bias", value=1.0,
    )
    events_file = tmp_path / "washer_events.csv"
    pd.DataFrame([asset, channel] if asset_first else [channel, asset]).to_csv(
        events_file, index=False
    )
    schema["robustness"] = {"enabled": True, "events_file": str(events_file)}
    env = CityLearnEnv(
        schema, simulation_end_time_step=3, episode_time_steps=4,
        physics_invariant_checks=True, export_kpis_on_episode_end=False,
    )
    try:
        env.reset(seed=0)
        for _ in range(3):
            payload = _zero_entity_payload(env)
            payload["tables"]["deferrable_appliance"][:, 0] = 1.0
            env.step(payload)
        np.testing.assert_allclose(
            env.buildings[0].deferrable_appliances_electricity_consumption[:3],
            [0.1, 0.2, 0.0] if already_running else [0.0, 0.0, 0.0],
            atol=1e-7,
        )
    finally:
        env.close()


@pytest.mark.parametrize("event_format", ["csv", "parquet"])
@pytest.mark.parametrize(
    "changes,field",
    [
        ({"start_time_step": 0.9}, "start_time_step"),
        ({"end_time_step": 1.9}, "end_time_step"),
        ({"start_time_step": "nan"}, "start_time_step"),
        ({"end_time_step": "inf"}, "end_time_step"),
        ({"start_time_step": -1}, "start_time_step"),
        ({"end_time_step": -1}, "end_time_step"),
        ({"start_time_step": 2, "end_time_step": 1}, "end_time_step"),
        ({"start_time_step": True}, "start_time_step"),
        ({"mode": "delay", "delay_steps": 0.5}, "delay_steps"),
        ({"mode": "delay", "delay_steps": 0}, "delay_steps"),
        ({"mode": "delay", "delay_steps": -1}, "delay_steps"),
        ({"mode": "delay", "delay_steps": "inf"}, "delay_steps"),
        ({"mode": "delay", "delay_steps": "bad"}, "delay_steps"),
        ({"mode": "noise", "std": -0.1}, "std"),
        ({"mode": "noise", "std": "bad"}, "std"),
        ({"mode": "noise", "std": "inf"}, "std"),
        ({"mode": "noise", "std": "nan"}, "std"),
        ({"mode": "bias", "value": "bad"}, "value"),
        ({"mode": "bias", "value": "inf"}, "value"),
        ({"mode": "clip", "min_value": 2, "max_value": 1}, "max_value"),
        ({"mode": "clip", "min_value": "-inf"}, "min_value"),
        ({"replacement_value": "inf"}, "replacement_value"),
        ({"replacement_value": "bad"}, "replacement_value"),
    ],
)
def test_invalid_event_parameters_rejected_before_episode_reset(
    tmp_path, monkeypatch, event_format, changes, field
):
    schema = _copy_schema(tmp_path, event_format=event_format)
    row = _event(
        event_id="invalid_event", module="action", target_type="storage",
        target_id="*", target_feature="electrical_storage", start=1, end=1,
        mode="bias",
    )
    row.update(changes)
    _write_events(schema, [row])

    def unexpected_reset(*args, **kwargs):
        pytest.fail("Invalid robustness configuration reached episode reset.")

    monkeypatch.setattr(CityLearnEnv, "reset", unexpected_reset)
    with pytest.raises(ValueError, match=re.escape(f"'invalid_event'.{field}")):
        CityLearnEnv(_clean_schema(schema), episode_time_steps=4)


@pytest.mark.parametrize("event_format", ["csv", "parquet"])
def test_duplicate_event_ids_rejected_even_across_disabled_modules(tmp_path, event_format):
    schema = _copy_schema(tmp_path, event_format=event_format, modules={"forecasts": False})
    _write_events(schema, [
        _event(event_id="duplicate", mode="bias", value=1),
        _event(event_id=" duplicate ", module="forecast", mode="bias", value=1),
    ])
    with pytest.raises(ValueError, match="duplicate.*event_id|event_id.*duplicate"):
        CityLearnEnv(_clean_schema(schema), episode_time_steps=4)


@pytest.mark.parametrize(
    "field,value",
    [
        ("random_seed", 1.5),
        ("random_seed", "inf"),
        ("random_seed", "bad"),
        ("random_seed", True),
        ("missing_replacement_value", "inf"),
        ("missing_replacement_value", "nan"),
        ("missing_replacement_value", float("nan")),
        ("missing_replacement_value", "bad"),
        ("missing_replacement_value", True),
    ],
)
def test_invalid_robustness_defaults_rejected_before_loading(tmp_path, monkeypatch, field, value):
    schema = _copy_schema(tmp_path)
    schema["robustness"][field] = value

    def unexpected_load(*args, **kwargs):
        pytest.fail("Invalid robustness defaults reached equipment loading.")

    monkeypatch.setattr(CityLearnEnv, "_load", unexpected_load)
    with pytest.raises(ValueError, match=re.escape(f"robustness.{field}")):
        CityLearnEnv(_clean_schema(schema), episode_time_steps=4)


@pytest.mark.parametrize("event_format", ["csv", "parquet"])
def test_optional_parameters_and_integral_numeric_steps_remain_supported(tmp_path, event_format):
    schema = _copy_schema(tmp_path, event_format=event_format)
    _write_events(schema, [
        _event(event_id="noise", mode="noise", start=0.0, end=1.0),
        _event(event_id="bias", mode="bias", value=-0.25, start=0.0, end=1.0),
        _event(event_id="clip", mode="clip", min_value=-2.0),
        _event(
            event_id="delay", module="action", target_type="storage", target_id="*",
            target_feature="electrical_storage", mode="delay", delay_steps=2.0,
        ),
    ])
    env = CityLearnEnv(_clean_schema(schema), episode_time_steps=4, physics_invariant_checks=True)
    try:
        events = {event.event_id: event for event in env._robustness_service.events}
        assert events["noise"].std is None
        assert events["noise"].delay_steps == 1
        assert events["delay"].delay_steps == 2
        env.step(_storage_action(env, 0.2))
    finally:
        env.close()
