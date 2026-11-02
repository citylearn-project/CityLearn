"""Independent physical-flow network versus runtime accounting and reported KPIs."""

from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.balance_audit import (
    IndependentBalanceAudit,
    BalanceAuditError,
    weighted_imports,
    FlowNetwork,
)
from test_deferrable_appliance_integration import (
    _schema_with_deferrable_appliance,
    _zero_entity_payload,
)
from test_market_phase_invariants import _write_residual_market_schema


def scenario(
    tmp_path,
    *,
    seconds=900,
    events=None,
    version=1,
    tariff=False,
    start=0,
    outage=False,
    phase_limits=False,
    negative=False,
    unknown_carbon=False,
):
    path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=1)
    schema = json.loads(path.read_text())
    schema.update(
        interface="entity",
        physics_invariant_checks=True,
        seconds_per_time_step=seconds,
        simulation_start_time_step=start,
        simulation_end_time_step=7,
        episode_time_steps=8 - start,
        export_kpis_on_episode_end=False,
    )
    schema["community_market"] = {
        "enabled": True,
        "local_price_ratio_to_grid_import": 0.8,
        "grid_export_price": 0.05,
        "settlement_version": version,
        "import_member_weights": {"Building_1": 2.0, "Building_2": 1.0},
    }
    first = schema["buildings"]["Building_1"]
    first["pv"] = {
        "type": "citylearn.energy_model.PV",
        "autosize": False,
        "attributes": {"generation_mode": "absolute", "nominal_power": 200.0},
    }
    first["electrical_storage"]["attributes"].update(
        initial_soc=0.25,
        efficiency=0.81,
        loss_coefficient=0.01,
        capacity_loss_coefficient=0.0,
        power_efficiency_curve=[[0.0, 0.81], [1.0, 0.81]],
        capacity_power_curve=[[0.0, 1.0], [1.0, 1.0]],
    )
    first["deferrable_appliances"]["washer_1"]["attributes"] = {"nominal_power": 20.0}
    second = deepcopy(first)
    second["energy_simulation"] = "Building_2.csv"
    second["chargers"] = {}
    second["deferrable_appliances"] = {}
    second["electrical_storage"]["attributes"]["initial_soc"] = 0.6
    schema["buildings"]["Building_2"] = second
    frame = pd.read_csv(path.parent / "Building_1.csv")
    for key in ("cooling_demand", "heating_demand", "dhw_demand"):
        frame[key] = 0.0
    frame["minutes"] = [int(i * seconds / 60) % 60 for i in range(8)]
    frame["hour"] = [int(i * seconds / 3600) % 24 for i in range(8)]
    for name, load, pv in [
        (
            "Building_1",
            [0.3, 0.2, 0.6, 0.2, 0.4, 0.1, 0.2, 0.3],
            [1.8, 0.0, 0.2, 2.0, 0.0, 1.0, 0.1, 0.2],
        ),
        (
            "Building_2",
            [0.8, 1.0, 0.3, 0.2, 0.1, 0.6, 0.1, 0.3],
            [0.0, 0.1, 1.2, 0.0, 2.0, 0.1, 0.6, 0.2],
        ),
    ]:
        f = frame.copy()
        f["non_shiftable_load"] = load
        f["solar_generation"] = pv
        f["power_outage"] = [0, 0, 1, 1, 0, 0, 0, 0] if outage else 0
        f.to_csv(path.parent / (name + ".csv"), index=False)
        schema["buildings"][name]["power_outage"] = {
            "simulate_power_outage": bool(outage)
        }
    carbon = pd.read_csv(path.parent / "carbon_intensity.csv")
    carbon["carbon_intensity"] = [0.2, 0.6, 0.1, 0.7, 0.15, 0.4, 0.1, 0.2]
    carbon.to_csv(path.parent / "carbon_intensity.csv", index=False)
    if unknown_carbon:
        carbon["carbon_intensity"] = np.nan
        carbon.to_csv(path.parent / "carbon_intensity.csv", index=False)
    if negative:
        prices = pd.read_csv(path.parent / "pricing.csv")
        prices.iloc[:, :] = -0.1
        prices.to_csv(path.parent / "pricing.csv", index=False)
    if phase_limits:
        for building in schema["buildings"].values():
            building["electrical_service"] = {
                "mode": "three_phase",
                "default_split": "balanced",
                "limits": {
                    "total": {"import_kw": 4.0, "export_kw": 50.0},
                    "per_phase": {
                        p: {"import_kw": 1.5, "export_kw": 20.0}
                        for p in ("L1", "L2", "L3")
                    },
                },
            }
        first["chargers"]["charger_1_1"]["attributes"]["phase_connection"] = "L1"
    if tariff:
        schema["community_market"]["tariff_files"] = {}
        for i, name in enumerate(schema["buildings"]):
            file = name + "_tariffs.csv"
            pd.DataFrame(
                {
                    "grid_export_price": [0.05] * 8,
                    "community_buy_price": [0.18 + i * 0.02] * 8,
                    "community_sell_price": [0.12 + i * 0.02] * 8,
                }
            ).to_csv(path.parent / file, index=False)
            schema["community_market"]["tariff_files"][name] = file
    if events is not None:
        schema.update(topology_mode="dynamic", topology_events=events)
    return CityLearnEnv(schema, random_seed=19, offline=True)


def commands(env, values, *, start=False):
    payload = _zero_entity_payload(env)
    payload["tables"]["building"][:, 0] = values[: len(env.buildings)]
    if len(payload["tables"]["charger"]):
        payload["tables"]["charger"][:, 0] = 0.35
    if start and len(payload["tables"]["deferrable_appliance"]):
        payload["tables"]["deferrable_appliance"][:, 0] = 1.0
    return payload


@pytest.mark.parametrize("seconds", [60, 900, 3600])
@pytest.mark.parametrize("fast", [False, True])
def test_joint_equipment_sharing_losses_and_carbon(tmp_path, seconds, fast):
    env = scenario(tmp_path, seconds=seconds)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            original = deepcopy(env.observations)
            step = env._runtime_service.step_without_feedback if fast else env.step
            while not env.terminated:
                t = env.time_step
                step(
                    commands(
                        env,
                        [0.5 if t % 2 == 0 else -0.4, -0.2 if t % 2 == 0 else 0.4],
                        start=t == 0,
                    )
                )
            result = audit.finish()
        assert result["status"] == "pass"
        assert result["completed_intervals"] == 7
        assert result["checks"] > 150
        assert any(
            r["destination"] == "loss" and r["energy_kwh"] > 0
            for r in result["source_destinations"]
        )
        assert env.get_deferrable_service_audit()["district"][
            "served_energy_kwh"
        ] == pytest.approx(0.3, abs=1e-6)
    finally:
        env.close()


@pytest.mark.parametrize("seed", [3, 29, 71])
def test_seeded_saturation_sequences(tmp_path, seed):
    env = scenario(tmp_path)
    rng = np.random.default_rng(seed)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                values = rng.choice([-1.0, -0.75, 0.0, 0.75, 1.0], size=2)
                env.step(commands(env, values, start=env.time_step == 0))
            result = audit.finish()
        assert result["max_tolerance_fraction"] <= 1
    finally:
        env.close()


@pytest.mark.parametrize("kind", ["member", "asset"])
def test_history_survives_exit_and_recommissioning(tmp_path, kind):
    target = {"target_member_id": "Building_1"}
    if kind == "asset":
        target.update(target_asset_type="electrical_storage", target_asset_id="battery")
    events = [
        dict(id="exit", time_step=2, operation="remove_" + kind, **target),
        dict(id="return", time_step=4, operation="add_" + kind, **target),
    ]
    env = scenario(tmp_path, events=events)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.4, -0.3], start=env.time_step == 0))
            result = audit.finish()
        assert any(
            r["destination"] == "asset_exit" for r in result["source_destinations"]
        )
        history = env._topology_service.historical_storages("Building_1")
        assert len(history) == 2
        # Querying must not consume source or destination evidence.
        before = deepcopy(result["source_destinations"])
        assert audit.finish()["source_destinations"] == before
    finally:
        env.close()


def test_nonzero_window_asymmetric_tariffs_and_operator_balance(tmp_path):
    env = scenario(tmp_path, version=2, tariff=True, start=2)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            report = audit.finish()
        assert any(
            abs(m["operator_balance_eur"]) > 0 for m in report["members"].values()
        )
    finally:
        env.close()


def test_outage_does_not_reuse_available_energy(tmp_path):
    env = scenario(tmp_path, outage=True)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0], start=env.time_step == 0))
            report = audit.finish()
        assert report["status"] == "pass"
    finally:
        env.close()


def test_pv_terminal_observation_is_not_generated_energy(tmp_path):
    path = _write_residual_market_schema(tmp_path)
    frame = pd.read_csv(path.parent / "Building_B.csv")
    frame["solar_generation"] = 1.0
    frame.to_csv(path.parent / "Building_B.csv", index=False)
    env = CityLearnEnv(
        str(path),
        random_seed=0,
        physics_invariant_checks=True,
        export_kpis_on_episode_end=False,
    )
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step([np.zeros(env.action_space[0].shape)])
            report = audit.finish()
        assert report["members"]["Building_B"]["pv_generated_kwh"] == pytest.approx(3.0)
    finally:
        env.close()


@pytest.mark.parametrize(
    "weights,expected",
    [
        ([10, 1, 0], [1, 4, 1]),
        ([0, 0, 0], [1, 2.5, 2.5]),
        ([1e-12, 1e-12, 0], [1, 2.5, 2.5]),
    ],
)
def test_independent_weighted_demand_caps(weights, expected):
    np.testing.assert_allclose(
        weighted_imports([1, 4, 5], 6, weights), expected, atol=1e-8
    )


def test_audit_is_passive_restores_runtime_and_has_no_reset_leak(tmp_path):
    env = scenario(tmp_path)
    try:
        env.reset()
        method = env._runtime_service._step_once
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            first = audit.finish()
        assert env._runtime_service._step_once == method
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            second = audit.finish()
        assert first["source_destinations"] == second["source_destinations"]
    finally:
        env.close()


def test_corrupted_accounting_is_detected_without_using_it_as_expected(tmp_path):
    env = scenario(tmp_path)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            source = env._provenance_service.source_destinations

            def wrong():
                rows = source()
                rows[0]["energy_kwh"] += 0.1
                return rows

            env._provenance_service.source_destinations = wrong
            with pytest.raises(BalanceAuditError, match="provenance"):
                audit.finish()
    finally:
        env.close()


def test_conversion_loss_belongs_to_new_charge_before_stock_mixing():
    graph = FlowNetwork()
    pv = graph.node(5.0, {("pv", "new"): np.array([5.0, 0.0])})
    old = graph.node(2.0, {("grid", "old"): np.array([2.0, 0.4])})
    stored = graph.node(6.0)
    graph.edge(pv, stored, 4.0)
    graph.edge(old, stored, 2.0)
    graph.sink(pv, ("M", "loss"), 1.0)
    graph.sink(stored, ("M", "stored"), 6.0)

    def check(label, a, b):
        assert a == pytest.approx(b, abs=1e-10), label

    rows, _, _, _ = graph.solve(check)
    assert rows["M", "loss"][("pv", "new")][0] == pytest.approx(1.0)
    assert rows["M", "loss"][("grid", "old")][0] == pytest.approx(0.0)
    assert rows["M", "stored"][("grid", "old")][1] == pytest.approx(0.4)


def test_unused_pv_in_outage_is_curtailment_not_useful_load(tmp_path):
    path = _write_residual_market_schema(tmp_path)
    schema = json.loads(path.read_text())
    schema["root_directory"] = str(path.parent)
    for building in schema["buildings"].values():
        p = path.parent / building["energy_simulation"]
        frame = pd.read_csv(p)
        frame["power_outage"] = 1
        frame.to_csv(p, index=False)
        building["power_outage"] = {"simulate_power_outage": True}
    env = CityLearnEnv(
        schema,
        random_seed=0,
        physics_invariant_checks=True,
        export_kpis_on_episode_end=False,
    )
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step([np.zeros(env.action_space[0].shape)])
            report = audit.finish()
        summary = env._provenance_service.summary()[1]
        assert summary["pv_load_kwh"] == 0
        assert summary["pv_curtailment_kwh"] == pytest.approx(4.5)
        assert summary["pv_useful_building_ratio"] == 0
        assert sum(
            r["energy_kwh"]
            for r in report["source_destinations"]
            if r["destination"] == "curtailment"
        ) == pytest.approx(4.5)
    finally:
        env.close()


@pytest.mark.parametrize("kind", ["stationary", "ev"])
def test_opposing_calls_preserve_gross_throughput(tmp_path, kind):
    env = scenario(tmp_path, seconds=3600)
    try:
        # Opposing calls must retain both actual terminal movements.
        b = env.buildings[0]
        b.electrical_storage.initial_soc = 0.0
        b.electrical_storage.efficiency = 1.0
        b.electrical_storage.power_efficiency_curve = [[0.0, 1.0], [1.0, 1.0]]
        b.electrical_storage.depth_of_discharge = 1.0
        b.electrical_storage.loss_coefficient = 0.0
        env.reset()
        original = b.apply_actions

        def with_cycle(**kwargs):
            original(**kwargs)
            if kind == "stationary":
                b.electrical_storage.charge(1.0)
                b.electrical_storage.charge(-1.0)
            else:
                charger = b.electric_vehicle_chargers[0]
                if charger.connected_electric_vehicle is not None:
                    charger.update_connected_electric_vehicle_soc(0.1)
                    charger.update_connected_electric_vehicle_soc(-0.1)

        b.apply_actions = with_cycle
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            report = audit.finish()
        assert report["status"] == "pass"
        assert report["members"][b.name][kind + "_discharge_kwh"] > 0.0
    finally:
        env.close()


def test_source_free_network_has_no_invented_external_origin():
    graph = FlowNetwork()
    a = graph.node(1.0)
    b = graph.node(1.0)
    graph.edge(a, b, 1.0)
    graph.edge(b, a, 1.0)

    def check(label, a, b):
        assert a == pytest.approx(b), label

    result, _, _, nullity = graph.solve(check)
    assert result == {} and nullity == 1


def test_phase_limited_actions_match_independently_split_power(tmp_path):
    env = scenario(tmp_path, phase_limits=True)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                t = env.time_step
                env.step(commands(env, [1.0, 1.0]))
                for b in env.buildings:
                    dt = env.seconds_per_time_step / 3600.0
                    total = float(b.net_electricity_consumption[t]) / dt
                    ev = float(b.chargers_electricity_consumption[t]) / dt
                    phases = [
                        (total - ev) / 3.0 + ev,
                        (total - ev) / 3.0,
                        (total - ev) / 3.0,
                    ]
                    assert max(phases) <= 1.5 + 1e-5
                    assert total <= 4.0 + 1e-5
            assert audit.finish()["status"] == "pass"
    finally:
        env.close()


@pytest.mark.parametrize("version", [1, 2])
def test_negative_grid_price_cash_balance(tmp_path, version):
    env = scenario(tmp_path, version=version, negative=True)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            assert audit.finish()["status"] == "pass"
    finally:
        env.close()


def test_terminal_only_member_has_inventory_but_no_executed_energy(tmp_path):
    env = scenario(
        tmp_path,
        events=[
            dict(
                id="join",
                time_step=7,
                operation="add_member",
                target_member_id="Building_1",
            )
        ],
    )
    try:
        env.schema["buildings"]["Building_1"]["include"] = False
        # Rebuild to apply the initial membership selection.
        schema = deepcopy(env.schema)
        env.close()
        env = CityLearnEnv(schema, random_seed=19, offline=True)
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            report = audit.finish()
        assert report["members"]["Building_1"]["pv_generated_kwh"] == 0
        assert report["members"]["Building_1"]["cost_eur"] == 0
    finally:
        env.close()


def test_partial_appliance_service_agrees_with_executed_prefix(tmp_path):
    env = scenario(
        tmp_path,
        events=[
            dict(
                id="remove",
                time_step=1,
                operation="remove_asset",
                target_member_id="Building_1",
                target_asset_type="deferrable_appliance",
                target_asset_id="washer_1",
            )
        ],
    )
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0], start=env.time_step == 0))
            report = audit.finish()
        summary = env.get_deferrable_service_audit()["district"]
        assert report["members"]["Building_1"]["appliance_kwh"] == pytest.approx(0.1)
        assert summary["cancelled_count"] == 1
        assert summary["final_unserved_energy_kwh"] == pytest.approx(0.2)
    finally:
        env.close()


def test_unknown_grid_carbon_keeps_unknown_energy_cohort(tmp_path):
    env = scenario(tmp_path, unknown_carbon=True)
    try:
        env.reset()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                env.step(commands(env, [0.0, 0.0]))
            report = audit.finish()
        assert any(
            r["origin"] == "grid_unknown_carbon" and r["energy_kwh"] > 0
            for r in report["source_destinations"]
        )
    finally:
        env.close()
