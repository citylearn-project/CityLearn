from __future__ import annotations

import csv
import datetime
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.building import DynamicsBuilding
from citylearn.citylearn import CityLearnEnv, EvaluationCondition
from citylearn.internal import ev_departure_audit
from citylearn.internal.balance_audit import IndependentBalanceAudit


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_three_phase_dynamic_topology_demo/schema.json"
STATIC_SCHEMA_PATH = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"


def _load_schema(*, tie_first_two_events: bool = False) -> Mapping[str, Any]:
    schema = json.loads(SCHEMA_PATH.read_text())
    schema["root_directory"] = str(SCHEMA_PATH.parent)
    schema["interface"] = "entity"
    schema["topology_mode"] = "dynamic"

    # Keep event order but move them early to keep tests fast.
    remapped_steps = [2, 3, 4, 5, 6, 7, 8, 9]
    for event, step in zip(schema.get("topology_events", []), remapped_steps):
        event["time_step"] = step

    if tie_first_two_events and len(schema.get("topology_events", [])) >= 2:
        schema["topology_events"][0]["time_step"] = 2
        schema["topology_events"][1]["time_step"] = 2

    return schema


def _load_static_schema() -> Mapping[str, Any]:
    schema = json.loads(STATIC_SCHEMA_PATH.read_text())
    schema["root_directory"] = str(STATIC_SCHEMA_PATH.parent)
    return schema


def _zero_entity_actions(env: CityLearnEnv):
    tables = env.action_space["tables"]
    return {
        "tables": {
            name: np.zeros(space.shape, dtype="float32")
            for name, space in tables.items()
            if name in {"building", "charger", "deferrable_appliance"}
        }
    }


def _step_until(env: CityLearnEnv, target_time_step: int):
    while env.time_step < target_time_step:
        env.step(_zero_entity_actions(env))


def _building_index_by_name(env: CityLearnEnv, building_name: str) -> int:
    return [b.name for b in env.buildings].index(building_name)


def test_dynamic_mode_requires_entity_interface():
    with pytest.raises(ValueError):
        CityLearnEnv(
            str(SCHEMA_PATH),
            interface="flat",
            topology_mode="dynamic",
            episode_time_steps=8,
            random_seed=0,
        )


def test_dynamic_schema_cannot_run_with_static_topology_mode():
    schema = _load_schema()
    schema.pop("topology_mode", None)

    with pytest.raises(ValueError, match="Schema declares dynamic topology"):
        CityLearnEnv(
            schema,
            interface="entity",
            topology_mode="static",
            episode_time_steps=8,
            random_seed=0,
        )


def test_static_mode_fails_fast_when_storage_action_enabled_without_storage_asset():
    schema = _load_static_schema()
    building = schema["buildings"]["Building_1"]
    building.pop("electrical_storage", None)
    building["inactive_actions"] = []
    schema["actions"]["electrical_storage"]["active"] = True

    with pytest.raises(ValueError, match="Schema/action inconsistency in static topology"):
        CityLearnEnv(
            schema,
            interface="flat",
            topology_mode="static",
            episode_time_steps=3,
            random_seed=0,
        )


def test_event_boundary_semantics_and_topology_version_increment():
    env = CityLearnEnv(_load_schema(), interface="entity", topology_mode="dynamic", episode_time_steps=14, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)
        initial_buildings = obs["tables"]["building"].shape[0]
        assert obs["meta"]["topology_version"] == 0

        # Event at t=2 must not apply while transitioning to t=1.
        obs, *_ = env.step(_zero_entity_actions(env))
        assert env.time_step == 1
        assert obs["meta"]["topology_version"] == 0
        assert obs["tables"]["building"].shape[0] == initial_buildings

        # Event at t=2 applies after transition 1->2 and before obs at t=2.
        obs, *_ = env.step(_zero_entity_actions(env))
        assert env.time_step == 2
        assert obs["meta"]["topology_version"] == 1
        assert obs["tables"]["building"].shape[0] == initial_buildings + 1
        assert "Building_18" in env.entity_specs["tables"]["building"]["ids"]
    finally:
        env.close()


def test_dynamic_shape_changes_and_action_availability_expand_and_shrink():
    env = CityLearnEnv(_load_schema(), interface="entity", topology_mode="dynamic", episode_time_steps=16, random_seed=0)

    try:
        env.reset(seed=0)
        b3_idx = _building_index_by_name(env, "Building_3")
        b12_idx = _building_index_by_name(env, "Building_12")

        initial_charger_rows = env.entity_specs["tables"]["charger"]["ids"]
        assert len(initial_charger_rows) > 0

        _step_until(env, 2)  # add member
        assert "Building_18" in [b.name for b in env.buildings]

        _step_until(env, 3)  # add charger to Building_2
        charger_rows_after_add = len(env.entity_specs["tables"]["charger"]["ids"])

        _step_until(env, 4)  # remove charger from Building_5
        charger_rows_after_remove = len(env.entity_specs["tables"]["charger"]["ids"])
        assert charger_rows_after_add - charger_rows_after_remove == 1

        _step_until(env, 7)  # remove battery from Building_12
        assert "electrical_storage" not in env.buildings[b12_idx].active_actions

        _step_until(env, 8)  # add battery to Building_3
        assert "electrical_storage" in env.buildings[b3_idx].active_actions

        _step_until(env, 9)  # remove member
        assert "Building_18" not in [b.name for b in env.buildings]
    finally:
        env.close()


def test_dynamic_inactive_actions_keep_storage_action_disabled_after_add_asset():
    schema = _load_schema()
    building_3 = schema["buildings"]["Building_3"]
    inactive = list(building_3.get("inactive_actions", []))
    if "electrical_storage" not in inactive:
        inactive.append("electrical_storage")
    building_3["inactive_actions"] = inactive

    env = CityLearnEnv(schema, interface="entity", topology_mode="dynamic", episode_time_steps=16, random_seed=0)

    try:
        env.reset(seed=0)
        b3_idx = _building_index_by_name(env, "Building_3")

        _step_until(env, 8)  # add battery to Building_3
        assert "Building_3/electrical_storage" in env.entity_specs["tables"]["storage"]["ids"]
        assert "electrical_storage" not in env.buildings[b3_idx].active_actions

        payload = _zero_entity_actions(env)
        payload["map"] = {"building:Building_3": {"electrical_storage": 0.2}}
        with pytest.raises(AssertionError, match="Unknown building action keys"):
            env._entity_service.parse_actions(payload)
    finally:
        env.close()


def test_hybrid_action_tables_plus_map_precedence_and_unknown_ids_validation():
    env = CityLearnEnv(_load_schema(), interface="entity", topology_mode="dynamic", episode_time_steps=12, random_seed=0)

    try:
        env.reset(seed=0)

        building = env.buildings[0]
        building_idx = 0
        non_ev_actions = [
            name for name in building.active_actions
            if not name.startswith("electric_vehicle_storage_") and "deferrable_appliance" not in name
        ]
        if not non_ev_actions:
            pytest.skip("No non-EV building actions available in this scenario.")

        action_name = non_ev_actions[0]
        payload = _zero_entity_actions(env)
        payload["map"] = {
            f"building:{building.name}": {
                action_name: 0.5,
            }
        }

        parsed = env._entity_service.parse_actions(payload)
        assert parsed[building_idx][f"{action_name}_action"] == pytest.approx(0.5)

        with pytest.raises(AssertionError):
            env._entity_service.parse_actions(
                {
                    "tables": payload["tables"],
                    "map": {
                        "building:unknown_member": {action_name: 0.1},
                    },
                }
            )
    finally:
        env.close()


def test_removed_charger_action_id_is_invalid_after_topology_removal():
    env = CityLearnEnv(_load_schema(), interface="entity", topology_mode="dynamic", episode_time_steps=12, random_seed=0)

    try:
        env.reset(seed=0)
        removed_id = None
        for charger_id in env.entity_specs["actions"]["charger"]["ids"]:
            if charger_id.startswith("Building_5/") and charger_id.endswith("charger_5_1"):
                removed_id = charger_id
                break

        assert removed_id is not None

        _step_until(env, 4)  # event removes Building_5 charger 5_1
        assert removed_id not in env.entity_specs["actions"]["charger"]["ids"]

        payload = _zero_entity_actions(env)
        payload["map"] = {
            f"charger:{removed_id}": {
                "electric_vehicle_storage": 0.2,
            }
        }

        with pytest.raises(AssertionError, match="Unknown charger id"):
            env._entity_service.parse_actions(payload)
    finally:
        env.close()


def test_removed_charger_can_be_reinstalled_from_its_initial_template():
    schema = _load_schema()
    schema["topology_events"] = [
        {
            "id": "remove_charger",
            # The first catalogue session departs before removal, while the
            # second departs after recommissioning.  This makes the test cover
            # end-of-episode KPI aggregation across both runtime instances.
            "time_step": 16,
            "operation": "remove_asset",
            "target_member_id": "Building_5",
            "target_asset_type": "charger",
            "target_asset_id": "charger_5_1",
        },
        {
            "id": "reinstall_charger",
            "time_step": 18,
            "operation": "add_asset",
            "target_member_id": "Building_5",
            "target_asset_type": "charger",
            "target_asset_id": "charger_5_1",
            "source_member_id": "Building_5",
            "source_asset_id": "charger_5_1",
        },
    ]
    env = CityLearnEnv(
        schema,
        interface="entity",
        topology_mode="dynamic",
        episode_time_steps=42,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        charger_id = "Building_5/charger_5_1"
        initial_charger = env._topology_service.member_pool["Building_5"].electric_vehicle_chargers[0]
        assert charger_id in env.entity_specs["tables"]["charger"]["ids"]

        _step_until(env, 16)
        assert charger_id not in env.entity_specs["tables"]["charger"]["ids"]

        _step_until(env, 18)
        assert charger_id in env.entity_specs["tables"]["charger"]["ids"]
        assert [event["applied"] for event in env.topology_event_log] == [True, True]
        restored_charger = env._topology_service.member_pool["Building_5"].electric_vehicle_chargers[0]
        historical_chargers = env._topology_service.historical_chargers("Building_5")
        assert restored_charger is not initial_charger
        assert historical_chargers == (initial_charger, restored_charger)
        assert env._kpi_service._chargers_for_metrics(
            env._topology_service.member_pool["Building_5"]
        ) == list(historical_chargers)
        _step_until(env, 40)
        ev_metrics = env._kpi_service._compute_ev_metrics(
            env._topology_service.member_pool["Building_5"],
            t_start=0,
            t_final=env.time_step,
        )
        assert ev_metrics["departures_total"] == 2.0
    finally:
        env.close()


def _ev_lifecycle_env(tmp_path, seconds, *, first_activation=False, second_charger=False, **env_options):
    shutil.copytree(STATIC_SCHEMA_PATH.parent, tmp_path, dirs_exist_ok=True)
    schema = json.loads((tmp_path / "schema.json").read_text())
    schema.update(root_directory=str(tmp_path), seconds_per_time_step=seconds)
    ev_id = "Electric_Vehicle_1"
    schema["electric_vehicles_def"][ev_id]["battery"]["attributes"].update(
        initial_soc=.25, loss_coefficient=.04, depth_of_discharge=.8,
        capacity_loss_coefficient=0., power_efficiency_curve=[[0., .81], [1., .81]],
    )
    building = schema["buildings"]["Building_1"]
    charger = building["chargers"]["charger_1_1"]
    charger["attributes"].update(charge_efficiency_curve=[[0., .95], [1., .95]])
    schedule_path = tmp_path / charger["charger_simulation"]
    schedule = pd.read_csv(schedule_path)
    schedule["electric_vehicle_charger_state"] = 1
    schedule["electric_vehicle_id"] = ev_id
    schedule["electric_vehicle_departure_time"] = np.arange(len(schedule), 0, -1)
    schedule["electric_vehicle_estimated_soc_arrival"] = -0.1
    schedule.to_csv(schedule_path, index=False)
    if second_charger:
        schedule["electric_vehicle_current_soc"] = .1
        schedule.to_csv(tmp_path / "charger_1_2.csv", index=False)
        building["chargers"]["charger_1_2"] = {**charger, "charger_simulation": "charger_1_2.csv"}
    events = [
        {"operation": "remove_asset", "time_step": 2},
        {"operation": "add_asset", "time_step": 5},
    ]
    if first_activation:
        schema["buildings"]["Template"] = {**building, "include": False}
        building["chargers"] = {}
        events = [{"operation": "add_asset", "time_step": 5, "source_member_id": "Template"}]
    schema["topology_events"] = [
        {**event, "target_member_id": "Building_1", "target_asset_type": "charger",
         "target_asset_id": "charger_1_1"} for event in events
    ]
    return CityLearnEnv(schema, interface="entity", topology_mode="dynamic", random_seed=19,
                        physics_invariant_checks=True, export_kpis_on_episode_end=False, **env_options)


def _assert_lifecycle_ev_observation(env, ev, expected):
    spec = env.entity_specs["tables"]["ev"]
    row = spec["ids"].index(ev.name)
    col = spec["features"].index("soc")
    assert env.observations["tables"]["ev"][row, col] == pytest.approx(expected)


@pytest.mark.parametrize("seconds", [3600, 900])
def test_reinstalled_charger_recovers_the_same_evolved_ev(tmp_path, seconds):
    env = _ev_lifecycle_env(tmp_path, seconds)
    try:
        env.reset(seed=19)
        ev, = env.electric_vehicles
        battery = ev.battery
        with IndependentBalanceAudit(env) as audit:
            _step_until(env, 2)
            assert ev not in env.electric_vehicles
            assert "Building_1/charger_1_1" not in env.entity_specs["actions"]["charger"]["ids"]
            expected = float(battery.soc[2])
            mobility_rng = np.random.RandomState(np.random.SeedSequence([19, 1]).generate_state(1)[0])
            retention = .96**(seconds/3600)
            for step in range(3, 6):
                _step_until(env, step)
                expected *= retention * np.clip(mobility_rng.normal(1., .2*np.sqrt(seconds/3600)), .6, 1.4)
                assert ev.time_step == battery.time_step == step
                assert float(battery.soc[step]) == pytest.approx(expected, abs=1e-7)
                assert battery.energy_balance[step] == 0.
                standby, mobility = battery.energy_provenance_events
                assert [standby["kind"], mobility["kind"]] == ["standby", "external"]
                assert standby["before"] - standby["after"] == pytest.approx(
                    standby["before"]*(1.-retention), abs=1e-5,
                )
                assert standby["after"] == pytest.approx(mobility["before"])
                assert mobility["after"] == pytest.approx(expected * battery.capacity)
            assert env.electric_vehicles == [ev]
            charger, = env.buildings[0].electric_vehicle_chargers
            assert charger.connected_electric_vehicle is ev
            assert "Building_1/charger_1_1" in env.entity_specs["actions"]["charger"]["ids"]
            _assert_lifecycle_ev_observation(env, ev, expected)
            opening = battery.energy_init
            kpi = env._kpi_service
            sim = charger.charger_simulation
            states = sim.electric_vehicle_charger_state
            boundary_step, boundary_soc = kpi._ev_kpi_connection_boundary(charger, sim, ev, states, 6)
            assert boundary_step == 5
            assert boundary_soc == pytest.approx(opening / battery.capacity)
            start = ev_departure_audit.connected_start(kpi, charger, sim, ev, states, 5)
            reason, audit_soc = ev_departure_audit.prerequisites(kpi, charger, sim, ev, states, start, .8)
            assert start == 5 and reason is None
            assert audit_soc == pytest.approx(boundary_soc)
            reward_observation = env.buildings[0]._get_observations_data(include_all=True)
            assert reward_observation["electric_vehicles_chargers_dict"][charger.charger_id][
                "previous_battery_soc"
            ] == pytest.approx(boundary_soc)
            action = _zero_entity_actions(env)
            action["tables"]["charger"][:] = 1.
            env.step(action)
            ac = float(charger.electricity_consumption[5])
            assert 0. < ac <= charger.max_charging_power * seconds/3600 + 1e-5
            assert battery.soc[5]*battery.capacity - opening == pytest.approx(ac*.95*.9, abs=1e-5)
            _step_until(env, 7)
            assert audit.finish()["status"] == "pass"
        env.reset(seed=19)
        _step_until(env, 5)
        assert float(ev.battery.soc[5]) == pytest.approx(expected)
    finally:
        env.close()


@pytest.mark.parametrize("seconds", [3600, 900])
def test_first_ev_activation_accounts_for_opening_stock(tmp_path, seconds):
    env = _ev_lifecycle_env(tmp_path, seconds, first_activation=True)
    try:
        env.reset(seed=19)
        assert not env.electric_vehicles
        _step_until(env, 5)
        ev, = env.electric_vehicles
        battery = ev.battery
        assert ev.time_step == battery.time_step == 5
        assert battery.soc[5] == pytest.approx(.25)
        _assert_lifecycle_ev_observation(env, ev, .25)
        opening, = battery.energy_provenance_events
        assert opening["kind"] == "external"
        assert opening["before"] == 0.
        assert opening["after"] == pytest.approx(.25*battery.capacity)
        assert opening["terminal"] == battery.energy_balance[5] == 0.
        stock = env._provenance_service.stocks[id(battery)]
        assert stock.bag[("unknown", "Building_1")][0] == pytest.approx(.25*battery.capacity)
    finally:
        env.close()


@pytest.mark.parametrize("seconds", [3600, 900])
def test_another_charger_keeps_the_ev_active_during_removal(tmp_path, seconds):
    with pytest.warns(RuntimeWarning, match="already plugged"):
        env = _ev_lifecycle_env(tmp_path, seconds, second_charger=True)
    try:
        env.reset(seed=19)
        ev, = env.electric_vehicles
        _step_until(env, 2)
        alternate, = env.buildings[0].electric_vehicle_chargers
        assert alternate.connected_electric_vehicle is ev
        assert env._provenance_service.stocks[id(ev.battery)].connection is alternate
        with pytest.warns(RuntimeWarning, match="already plugged"):
            _step_until(env, 5)
        assert env.electric_vehicles == [ev]
        assert not env._topology_service.suspended_evs
        assert ev.battery.soc[5] == pytest.approx(.25*.96**(5*seconds/3600))
        chargers = env.buildings[0].electric_vehicle_chargers
        assert [charger for charger in chargers if charger.connected_electric_vehicle is ev] == [alternate]
        action = _zero_entity_actions(env)
        action["tables"]["charger"][:] = 1.
        env.step(action)
        assert alternate.electricity_consumption[5] > 0.
        assert sum(charger.electricity_consumption[5] > 0. for charger in chargers) == 1
    finally:
        env.close()


@pytest.mark.parametrize("seconds", [3600, 900])
def test_removed_charger_cannot_apply_its_arrival_soc(tmp_path, seconds):
    env = _ev_lifecycle_env(tmp_path, seconds)
    try:
        env.reset(seed=19)
        ev, = env.electric_vehicles
        charger, = env.buildings[0].electric_vehicle_chargers
        sim = charger.charger_simulation
        sim.electric_vehicle_session_id[:8] = ["a", "a", "b", "b", "b", "b", "b", "b"]
        sim.electric_vehicle_current_soc = np.full(8, -0.1, dtype="float32")
        sim.electric_vehicle_current_soc[2] = .9
        _step_until(env, 1)
        expected = float(ev.battery.soc[1]) * .96**(seconds/3600)
        _step_until(env, 2)
        assert not env.buildings[0].electric_vehicle_chargers
        assert charger.past_connected_evs[2] is None
        assert charger.electricity_consumption[2] == 0.
        assert ev.battery.soc[2] == pytest.approx(expected)
        assert [event["kind"] for event in ev.battery.energy_provenance_events] == ["standby"]
    finally:
        env.close()


@pytest.mark.parametrize("seconds", [3600, 900])
def test_kpi_and_audit_start_a_new_session_after_reentry(tmp_path, seconds):
    env = _ev_lifecycle_env(tmp_path, seconds)
    try:
        env.reset(seed=19)
        _step_until(env, 5)
        charger, = env.buildings[0].electric_vehicle_chargers
        ev = charger.connected_electric_vehicle
        sim = charger.charger_simulation
        sim.electric_vehicle_departure_time[5:8] = [1, 2, -1]
        sim.electric_vehicle_charger_state[7] = 3
        sim.electric_vehicle_current_soc = np.full(8, -0.1, dtype="float32")
        sim.electric_vehicle_current_soc[6] = .6
        sim.electric_vehicle_required_soc_departure[5:7] = .8
        _step_until(env, 7)

        service = env._kpi_service
        states = sim.electric_vehicle_charger_state
        start = ev_departure_audit.connected_start(service, charger, sim, ev, states, 6)
        reason, audit_soc = ev_departure_audit.prerequisites(service, charger, sim, ev, states, start, .8)
        kpi_step, kpi_soc = service._ev_kpi_connection_boundary(charger, sim, ev, states, 6)
        assert reason is None
        assert kpi_step == start == 6
        assert kpi_soc == pytest.approx(audit_soc)
        assert kpi_soc == pytest.approx(.6)
        metrics = service._compute_ev_metrics(env.buildings[0])
        assert metrics["ev_charge_total_kwh"] == 0.
        assert metrics["ev_connected_soc_gain_total_kwh"] == pytest.approx(0.)
        assert metrics["ev_energy_accounting_shortfall_kwh"] == pytest.approx(0.)
    finally:
        env.close()


@pytest.mark.parametrize("file_format", ["csv", "parquet"])
def test_charger_export_matches_actual_connection_during_handover(tmp_path, file_format):
    with pytest.warns(RuntimeWarning, match="already plugged"):
        env = _ev_lifecycle_env(tmp_path, 900, second_charger=True, render=True,
                                render_mode="end", render_directory=tmp_path / "exports",
                                render_file_format=file_format, render_chunk_size=3)
    try:
        env.reset(seed=19)
        ev, = env.electric_vehicles
        with pytest.warns(RuntimeWarning, match="already plugged"):
            _step_until(env, 7)

        # The reinstalled charger is present again at 5, but the second
        # charger retains the only actual connection.
        root = Path(env.new_folder_path)
        for charger_id, expected in (("charger_1_1", [True, True, False, False]),
                                     ("charger_1_2", [False, False, True, True, True, True, True])):
            files = sorted(root.glob(f"exported_data_building_1_{charger_id}_ep0*.{file_format}"))
            read = pd.read_csv if file_format == "csv" else pd.read_parquet
            exported = pd.concat([read(file) for file in files], ignore_index=True)
            assert exported["Is EV Connected"].tolist() == expected
            assert exported["EV Name"].dropna().replace("", np.nan).dropna().unique().tolist() == [ev.name]
        assert [c.charger_id for c in env.buildings[0].electric_vehicle_chargers
                if c.connected_electric_vehicle is ev] == ["charger_1_2"]
    finally:
        env.close()


def test_removed_pv_storage_and_deferrable_can_be_restored_from_same_member_templates():
    schema = _load_schema()
    schema["buildings"]["Building_12"]["electrical_storage"]["attributes"][
        "initial_soc"
    ] = 0.1
    schema["buildings"]["Building_12"]["electrical_storage"]["attributes"]["depth_of_discharge"] = 0.8
    schema["topology_events"] = [
        {
            "id": "remove_pv",
            "time_step": 1,
            "operation": "remove_asset",
            "target_member_id": "Building_11",
            "target_asset_type": "pv",
            "target_asset_id": "pv",
        },
        {
            "id": "remove_storage",
            "time_step": 1,
            "operation": "remove_asset",
            "target_member_id": "Building_12",
            "target_asset_type": "electrical_storage",
            "target_asset_id": "electrical_storage",
        },
        {
            "id": "remove_deferrable",
            "time_step": 1,
            "operation": "remove_asset",
            "target_member_id": "Building_1",
            "target_asset_type": "deferrable_appliance",
            "target_asset_id": "deferrable_appliance_1",
        },
        {
            "id": "restore_pv",
            "time_step": 2,
            "operation": "add_asset",
            "target_member_id": "Building_11",
            "target_asset_type": "pv",
            "target_asset_id": "pv",
            "source_member_id": "Building_11",
            "source_asset_id": "pv",
        },
        {
            "id": "restore_storage",
            "time_step": 2,
            "operation": "add_asset",
            "target_member_id": "Building_12",
            "target_asset_type": "electrical_storage",
            "target_asset_id": "electrical_storage",
            "source_member_id": "Building_12",
            "source_asset_id": "electrical_storage",
        },
        {
            "id": "restore_deferrable",
            "time_step": 2,
            "operation": "add_asset",
            "target_member_id": "Building_1",
            "target_asset_type": "deferrable_appliance",
            "target_asset_id": "deferrable_appliance_1",
            "source_member_id": "Building_1",
            "source_asset_id": "deferrable_appliance_1",
        },
    ]
    env = CityLearnEnv(
        schema,
        interface="entity",
        topology_mode="dynamic",
        episode_time_steps=5,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        pv_member = env._topology_service.member_pool["Building_11"]
        storage_member = env._topology_service.member_pool["Building_12"]
        initial_pv_power = float(pv_member.pv.nominal_power)
        expected_pv_generation = (
            pv_member._pv_generation_to_control_step(
                pv_member.energy_simulation.solar_generation
            )
            * -1.0
        )
        initial_storage = storage_member.electrical_storage
        initial_storage_capacity = float(storage_member.electrical_storage.capacity)
        initial_storage_soc = float(initial_storage.initial_soc)
        initial_storage.set_electricity_consumption(
            1.0,
            time_step=0,
            enforce_polarity=False,
        )
        initial_deferrable = env._topology_service.member_pool["Building_1"].deferrable_appliances[0]

        _step_until(env, 1)
        assert float(pv_member.pv.nominal_power) == pytest.approx(0.0)
        committed_pv_generation = getattr(
            pv_member,
            "_Building__solar_generation",
        )
        assert np.allclose(committed_pv_generation[1:], 0.0)
        assert float(storage_member.electrical_storage.capacity) == pytest.approx(0.0)
        assert "Building_1/deferrable_appliance_1" not in env.entity_specs["tables"]["deferrable_appliance"]["ids"]

        _step_until(env, 2)
        assert float(pv_member.pv.nominal_power) == pytest.approx(initial_pv_power)
        committed_pv_generation = getattr(
            pv_member,
            "_Building__solar_generation",
        )
        assert np.allclose(committed_pv_generation[2:], expected_pv_generation[2:])
        assert float(storage_member.electrical_storage.capacity) == pytest.approx(initial_storage_capacity)
        restored_storage = storage_member.electrical_storage
        assert restored_storage is not initial_storage
        assert float(restored_storage.soc[restored_storage.time_step]) == pytest.approx(
            initial_storage_soc
        )
        assert restored_storage.energy_provenance_events[-1]["after"] == pytest.approx(
            initial_storage_capacity * initial_storage_soc
        )
        restored_storage.set_electricity_consumption(
            -0.5,
            time_step=restored_storage.time_step,
            enforce_polarity=False,
        )
        historical_storages = env._topology_service.historical_storages("Building_12")
        assert historical_storages == (initial_storage, restored_storage)
        bess_metrics = env._kpi_service._compute_bess_metrics(
            storage_member,
            t_start=0,
            t_final=restored_storage.time_step,
        )
        assert bess_metrics["bess_charge_total_kwh"] == pytest.approx(1.0)
        assert bess_metrics["bess_discharge_total_kwh"] == pytest.approx(0.5)
        assert bess_metrics["bess_throughput_total_kwh"] == pytest.approx(1.5)
        assert bess_metrics["_bess_capacity_kwh"] == pytest.approx(
            2.0 * initial_storage_capacity
        )
        assert "Building_1/deferrable_appliance_1" in env.entity_specs["tables"]["deferrable_appliance"]["ids"]
        assert [event["applied"] for event in env.topology_event_log] == [True] * 6

        restored_deferrable = env._topology_service.member_pool["Building_1"].deferrable_appliances[0]
        historical_deferrables = env._topology_service.historical_deferrable_appliances("Building_1")
        assert restored_deferrable is not initial_deferrable
        assert historical_deferrables == (initial_deferrable, restored_deferrable)
        assert env._kpi_service._deferrable_appliances_for_metrics(
            env._topology_service.member_pool["Building_1"]
        ) == list(historical_deferrables)
    finally:
        env.close()


def test_dynamic_deferrable_appliance_add_start_and_remove_cancels_future_consumption():
    schema = _load_schema()
    schema["topology_events"] = [
        {
            "id": "evt_add_deferrable_b2",
            "time_step": 1,
            "operation": "add_asset",
            "target_member_id": "Building_2",
            "target_asset_type": "deferrable_appliance",
            "target_asset_id": "dyn_washer",
            "source_member_id": "Building_1",
            "source_asset_id": "deferrable_appliance_1",
        },
        {
            "id": "evt_remove_deferrable_b2",
            "time_step": 2,
            "operation": "remove_asset",
            "target_member_id": "Building_2",
            "target_asset_type": "deferrable_appliance",
            "target_asset_id": "dyn_washer",
        },
    ]
    env = CityLearnEnv(schema, interface="entity", topology_mode="dynamic", episode_time_steps=5, random_seed=0)

    try:
        env.reset(seed=0)
        initial_count = len(env.entity_specs["tables"]["deferrable_appliance"]["ids"])

        env.step(_zero_entity_actions(env))
        assert len(env.entity_specs["tables"]["deferrable_appliance"]["ids"]) == initial_count + 1
        assert any(row_id.endswith("/dyn_washer") for row_id in env.entity_specs["tables"]["deferrable_appliance"]["ids"])

        payload = _zero_entity_actions(env)
        payload["map"] = {"deferrable_appliance:dyn_washer": {"start": 1.0}}
        env.step(payload)

        building_2 = env.buildings[_building_index_by_name(env, "Building_2")]
        assert all(appliance.name != "dyn_washer" for appliance in building_2.deferrable_appliances)
        assert not any(row_id.endswith("/dyn_washer") for row_id in env.entity_specs["tables"]["deferrable_appliance"]["ids"])
        assert building_2.deferrable_appliances_electricity_consumption[1] > 0.0

        if len(building_2.deferrable_appliances_electricity_consumption) > 2:
            assert building_2.deferrable_appliances_electricity_consumption[2] == pytest.approx(0.0)
    finally:
        env.close()


def test_dynamic_reset_restores_removed_deferrable_appliance_before_event_replay():
    schema = _load_schema()
    schema["topology_events"] = [
        {
            "id": "evt_remove_deferrable_b1",
            "time_step": 1,
            "operation": "remove_asset",
            "target_member_id": "Building_1",
            "target_asset_type": "deferrable_appliance",
            "target_asset_id": "deferrable_appliance_1",
        }
    ]
    env = CityLearnEnv(
        schema,
        interface="entity",
        topology_mode="dynamic",
        # Repeated resets deliberately select the same global window.  Integer
        # episode lengths normally advance to the next non-overlapping window,
        # where the global event at t=1 must already have been replayed.
        episode_time_steps=[(0, 2)],
        random_seed=0,
        render_mode="none",
    )

    try:
        for _ in range(2):
            env.reset(seed=0)
            initial_ids = env.entity_specs["tables"]["deferrable_appliance"]["ids"]
            assert "Building_1/deferrable_appliance_1" in initial_ids

            env.step(_zero_entity_actions(env))
            current_ids = env.entity_specs["tables"]["deferrable_appliance"]["ids"]
            assert "Building_1/deferrable_appliance_1" not in current_ids
            assert env.topology_event_log[-1]["applied"] is True
    finally:
        env.close()


def test_dynamic_entity_layout_normalization_and_encoding_contract_stays_consistent():
    env = CityLearnEnv(_load_schema(), interface="entity", topology_mode="dynamic", episode_time_steps=16, random_seed=0)

    try:
        obs, _ = env.reset(seed=0)

        for _ in range(11):
            spec = env.entity_specs
            space = env.observation_space

            assert obs["tables"]["building"].shape == space["tables"]["building"].shape
            assert obs["tables"]["charger"].shape == space["tables"]["charger"].shape
            assert obs["tables"]["storage"].shape == space["tables"]["storage"].shape
            assert obs["tables"]["ev"].shape == space["tables"]["ev"].shape
            assert obs["tables"]["pv"].shape == space["tables"]["pv"].shape
            assert obs["tables"]["deferrable_appliance"].shape == space["tables"]["deferrable_appliance"].shape

            assert obs["tables"]["building"].shape[0] == len(spec["tables"]["building"]["ids"])
            assert obs["tables"]["charger"].shape[0] == len(spec["tables"]["charger"]["ids"])
            assert obs["tables"]["storage"].shape[0] == len(spec["tables"]["storage"]["ids"])
            assert obs["tables"]["pv"].shape[0] == len(spec["tables"]["pv"]["ids"])
            assert obs["tables"]["deferrable_appliance"].shape[0] == len(spec["tables"]["deferrable_appliance"]["ids"])

            # Numerical stability contract for dynamic layouts: no NaN/inf while topology changes.
            for table_name in ("district", "building", "charger", "ev", "storage", "pv", "deferrable_appliance"):
                assert np.all(np.isfinite(obs["tables"][table_name]))

            # Phase encodings must remain binary during topology mutations.
            building_features = spec["tables"]["building"]["features"]
            phase_columns = [idx for idx, name in enumerate(building_features) if str(name).startswith("phase_")]
            if phase_columns:
                phase_values = obs["tables"]["building"][:, phase_columns]
                assert np.all((phase_values == 0.0) | (phase_values == 1.0))

            # Basic edge encoding integrity for graph models.
            b_count = obs["tables"]["building"].shape[0]
            c_count = obs["tables"]["charger"].shape[0]
            s_count = obs["tables"]["storage"].shape[0]
            p_count = obs["tables"]["pv"].shape[0]
            d_count = obs["tables"]["deferrable_appliance"].shape[0]

            if c_count > 0:
                building_to_charger = obs["edges"]["building_to_charger"]
                assert np.all((building_to_charger[:, 0] >= 0) & (building_to_charger[:, 0] < max(b_count, 1)))
                assert np.all((building_to_charger[:, 1] >= 0) & (building_to_charger[:, 1] < max(c_count, 1)))

            if s_count > 0:
                building_to_storage = obs["edges"]["building_to_storage"]
                assert np.all((building_to_storage[:, 0] >= 0) & (building_to_storage[:, 0] < max(b_count, 1)))
                assert np.all((building_to_storage[:, 1] >= 0) & (building_to_storage[:, 1] < max(s_count, 1)))

            if p_count > 0:
                building_to_pv = obs["edges"]["building_to_pv"]
                assert np.all((building_to_pv[:, 0] >= 0) & (building_to_pv[:, 0] < max(b_count, 1)))
                assert np.all((building_to_pv[:, 1] >= 0) & (building_to_pv[:, 1] < max(p_count, 1)))
            if d_count > 0:
                building_to_deferrable = obs["edges"]["building_to_deferrable_appliance"]
                assert np.all((building_to_deferrable[:, 0] >= 0) & (building_to_deferrable[:, 0] < max(b_count, 1)))
                assert np.all((building_to_deferrable[:, 1] >= 0) & (building_to_deferrable[:, 1] < max(d_count, 1)))

            obs, *_ = env.step(_zero_entity_actions(env))
    finally:
        env.close()


def test_event_order_is_deterministic_for_same_time_step():
    env = CityLearnEnv(_load_schema(tie_first_two_events=True), interface="entity", topology_mode="dynamic", episode_time_steps=12, random_seed=0)

    try:
        env.reset(seed=0)
        _step_until(env, 2)
        event_ids = [entry["id"] for entry in env.topology_event_log if entry["time_step"] == 2]
        assert event_ids[:2] == ["evt_add_member_18", "evt_add_charger_to_b2"]
    finally:
        env.close()


def test_global_topology_events_are_replayed_and_offset_in_partial_window():
    schema = _load_schema()
    env = CityLearnEnv(
        schema,
        interface="entity",
        topology_mode="dynamic",
        simulation_start_time_step=3,
        simulation_end_time_step=6,
        episode_time_steps=4,
        random_seed=0,
    )

    try:
        env.reset(seed=0)

        # The events at global steps 2 and 3 must already define the topology
        # visible at local step zero of a window that starts at global step 3.
        assert "Building_18" in env._topology_service.active_member_ids
        assert "Building_2/charger_2_dyn_1" in env.entity_specs["tables"]["charger"]["ids"]
        assert [entry["time_step"] for entry in env.topology_event_log] == [2, 3]
        assert [entry["episode_time_step"] for entry in env.topology_event_log] == [0, 0]

        # The event at global step 4 is reached after one local transition.
        _step_until(env, 1)
        assert "Building_5/charger_5_1" not in env.entity_specs["tables"]["charger"]["ids"]
        assert env.topology_event_log[-1]["time_step"] == 4
        assert env.topology_event_log[-1]["episode_time_step"] == 1
    finally:
        env.close()


def test_added_member_does_not_inherit_missed_pre_membership_requests():
    schema = _load_schema()
    add_member = dict(schema["topology_events"][0])
    add_member["time_step"] = 1019
    schema["topology_events"] = [add_member]
    env = CityLearnEnv(
        schema,
        interface="entity",
        topology_mode="dynamic",
        simulation_start_time_step=1000,
        simulation_end_time_step=1025,
        episode_time_steps=26,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        _step_until(env, 20)

        member = env._topology_service.member_pool["Building_18"]
        summary = member.deferrable_appliances[0].service_summary()
        assert summary["completed_cycles"] == 0.0
        assert summary["missed_cycles"] == 0.0
        assert summary["unserved_energy_kwh"] == 0.0
    finally:
        env.close()


def test_dynamic_non_central_agent_reward_summary_handles_variable_member_count():
    env = CityLearnEnv(
        _load_schema(),
        interface="entity",
        topology_mode="dynamic",
        central_agent=False,
        episode_time_steps=12,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        while not env.terminated and not env.truncated:
            env.step(_zero_entity_actions(env))

        assert len(env.episode_rewards) == 1
        summary = env.episode_rewards[0]
        for key in ("min", "max", "sum", "mean"):
            assert key in summary
            # At least one aggregated reward entry must exist.
            value = summary[key]
            if isinstance(value, list):
                assert len(value) > 0
            else:
                assert np.isfinite(float(value))
    finally:
        env.close()


def test_end_mode_exports_respect_dynamic_asset_activity_windows(tmp_path):
    env = CityLearnEnv(
        _load_schema(),
        interface="entity",
        topology_mode="dynamic",
        central_agent=True,
        episode_time_steps=12,
        random_seed=0,
        render_mode="end",
        render=True,
        render_directory=tmp_path,
    )

    def _timestamps(path: Path):
        with path.open(newline="") as handle:
            return [row["timestamp"] for row in csv.DictReader(handle)]

    try:
        env.reset(seed=0)
        while not env.terminated and not env.truncated:
            env.step(_zero_entity_actions(env))

        outputs_path = Path(env.new_folder_path)
        episode_num = env.episode_tracker.episode

        b18_file = outputs_path / f"exported_data_building_18_ep{episode_num}.csv"
        add_charger_file = outputs_path / f"exported_data_building_2_charger_2_dyn_1_ep{episode_num}.csv"
        removed_charger_file = outputs_path / f"exported_data_building_5_charger_5_1_ep{episode_num}.csv"
        removed_battery_file = outputs_path / f"exported_data_building_12_battery_ep{episode_num}.csv"
        added_battery_file = outputs_path / f"exported_data_building_3_battery_ep{episode_num}.csv"

        assert b18_file.is_file()
        assert add_charger_file.is_file()
        assert removed_charger_file.is_file()
        assert removed_battery_file.is_file()
        assert added_battery_file.is_file()

        start_dt = datetime.datetime.combine(env.render_start_date, datetime.time())
        start_dt += datetime.timedelta(seconds=int(env.episode_tracker.episode_start_time_step) * env.seconds_per_time_step)

        def _step_timestamp(step: int) -> str:
            return (start_dt + datetime.timedelta(seconds=step * env.seconds_per_time_step)).strftime("%Y-%m-%dT%H:%M:%S")

        b18_ts = _timestamps(b18_file)
        add_charger_ts = _timestamps(add_charger_file)
        removed_charger_ts = _timestamps(removed_charger_file)
        removed_battery_ts = _timestamps(removed_battery_file)
        added_battery_ts = _timestamps(added_battery_file)

        assert b18_ts[0] >= _step_timestamp(2)
        assert add_charger_ts[0] >= _step_timestamp(3)
        assert removed_charger_ts[-1] < _step_timestamp(4)
        assert removed_battery_ts[-1] < _step_timestamp(7)
        assert added_battery_ts[0] >= _step_timestamp(8)
    finally:
        env.close()


def test_business_as_usual_export_respects_dynamic_member_history(tmp_path):
    env = CityLearnEnv(
        _load_schema(),
        interface="entity",
        topology_mode="dynamic",
        central_agent=True,
        episode_time_steps=11,
        random_seed=0,
        render_directory=tmp_path,
    )

    try:
        env.reset(seed=0)
        while not env.terminated and not env.truncated:
            env.step(_zero_entity_actions(env))

        env.export_final_kpis(filepath="dynamic_kpis.csv")
        timeseries_path = Path(env.new_folder_path) / "exported_data_business_as_usual_ep0.csv"
        assert timeseries_path.is_file()

        with timeseries_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

        building_18_steps = sorted(
            int(row["time_step"])
            for row in rows
            if row["name"] == "Building_18" and row["level"] == "building"
        )
        assert building_18_steps
        assert min(building_18_steps) >= 2
        assert max(building_18_steps) < 9
    finally:
        env.close()


def test_dynamic_kpis_for_added_member_use_active_window_only():
    env = CityLearnEnv(_load_schema(), interface="entity", topology_mode="dynamic", episode_time_steps=12, random_seed=0)

    try:
        env.reset(seed=0)
        while not env.terminated and not env.truncated:
            env.step(_zero_entity_actions(env))

        kpis = env.evaluate_v2()
        row = kpis[
            (kpis["level"] == "building")
            & (kpis["name"] == "Building_18")
            & (kpis["cost_function"] == "building_energy_grid_total_import_control_kwh")
        ]
        daily_row = kpis[
            (kpis["level"] == "building")
            & (kpis["name"] == "Building_18")
            & (kpis["cost_function"] == "building_energy_grid_daily_average_import_control_kwh")
        ]
        assert len(row) == 1
        assert len(daily_row) == 1

        building_18 = env._topology_service.member_pool["Building_18"]
        lifecycle = env.topology_member_lifecycle["Building_18"]
        t_start = int(lifecycle["born_at"])
        removed_at = lifecycle["removed_at"]
        t_end = int(env.time_step) if removed_at is None else int(removed_at) - 1

        control_cond, _ = env._kpi_service._default_building_conditions(
            building_18,
            None,
            None,
            evaluation_condition_cls=EvaluationCondition,
            dynamics_building_cls=DynamicsBuilding,
        )
        series = np.array(
            getattr(building_18, f"net_electricity_consumption{control_cond.value}"),
            dtype="float64",
        )[t_start:t_end + 1]
        expected_import = float(np.clip(series, 0.0, None).sum())
        active_days = ((t_end - t_start + 1) * env.seconds_per_time_step) / (24 * 3600)

        assert float(row["value"].iloc[0]) == pytest.approx(expected_import)
        assert float(daily_row["value"].iloc[0]) == pytest.approx(expected_import / active_days)
    finally:
        env.close()
