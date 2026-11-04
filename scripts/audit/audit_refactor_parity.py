#!/usr/bin/env python3
"""Check bounded fixed-command references before/after internal refactoring.

Requires the checkout's test fixtures/dependencies. No policy, training, annual
campaign or BAU sidecar is run. References are never updated by verification.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFINITION = "refactor-parity-v2-compounded-standby"
DEFAULT_REFERENCE = ROOT / "scripts/audit/snapshots/refactor_parity.json"
CASES = {
    "flat_900s": dict(seconds=900, interface="flat"),
    "entity_60s": dict(seconds=60, interface="entity"),
    "entity_900s": dict(seconds=900, interface="entity"),
    "entity_3600s": dict(seconds=3600, interface="entity"),
    "entity_outage_300s": dict(seconds=300, interface="entity", outage=True),
    "entity_lifecycle_faults_900s": dict(seconds=900, interface="entity", dynamic=True),
}
TOLERANCES = {
    "energy_kwh": dict(atol=1e-6, rtol=1e-7),
    "money_eur": dict(atol=1e-7, rtol=1e-7),
    "soc_ratio": dict(atol=1e-7, rtol=1e-7),
    "power_kw": dict(atol=1e-5, rtol=1e-7),
    "other_numeric": dict(atol=1e-6, rtol=1e-7),
}


def canonical(value, directory):
    import numpy as np
    if isinstance(value, np.ndarray):
        return {"dtype": str(value.dtype), "shape": list(value.shape), "values": canonical(value.tolist(), directory)}
    if isinstance(value, np.generic):
        return canonical(value.item(), directory)
    if isinstance(value, dict):
        return {str(key): canonical(item, directory) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical(item, directory) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": "nan" if math.isnan(value) else "inf" if value > 0 else "-inf"}
    if isinstance(value, Path):
        value = str(value)
    if isinstance(value, str):
        return value.replace(str(directory), "<CASE>").replace(str(ROOT), "<REPO>")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported reference value: {type(value).__name__}")


def _tolerance(path):
    if any(word in path for word in ("soc", "ratio")):
        return TOLERANCES["soc_ratio"]
    if any(word in path for word in ("eur", "cost", "price", "revenue")):
        return TOLERANCES["money_eur"]
    if any(word in path for word in ("kwh", "energy", "consumption")):
        return TOLERANCES["energy_kwh"]
    if any(word in path for word in ("power", "_kw")):
        return TOLERANCES["power_kw"]
    return TOLERANCES["other_numeric"]


def compare(expected, actual):
    differences = []
    count = 0

    def visit(left, right, path):
        nonlocal count
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(left.keys() | right.keys()):
                if key not in left or key not in right:
                    mismatch(path + "/" + key, "missing_or_extra_key", key in left, key in right)
                else:
                    visit(left[key], right[key], path + "/" + key)
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                mismatch(path, "length", len(left), len(right))
            for i, (a, b) in enumerate(zip(left, right)):
                visit(a, b, path + f"/{i}")
        elif isinstance(left, bool) or isinstance(right, bool):
            if type(left) is not type(right) or left != right:
                mismatch(path, "value_or_type", left, right)
        elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
            exact = path.startswith("/tolerances/") or any(part.endswith("_count") for part in path.split("/"))
            if exact or isinstance(left, int) and isinstance(right, int):
                equal = left == right
            else:
                tolerance = _tolerance(path)
                equal = math.isclose(left, right, abs_tol=tolerance["atol"], rel_tol=tolerance["rtol"])
            if not equal:
                mismatch(path, "numeric", left, right)
        elif type(left) is not type(right) or left != right:
            mismatch(path, "value_or_type", left, right)

    def mismatch(path, kind, left, right):
        nonlocal count
        count += 1
        if len(differences) < 20:
            differences.append(dict(path=path, kind=kind, expected=left, actual=right))

    visit(expected, actual, "")
    return dict(matches=count == 0, difference_count=count, differences=differences)


def _observations(env, observation):
    if env.interface == "flat":
        return [{"names": names, "values": dict(zip(names, values))}
                for names, values in zip(env.observation_names, observation)]
    tables = {}
    for name, matrix in observation["tables"].items():
        spec = env.entity_specs["tables"][name]
        tables[name] = dict(dtype=str(matrix.dtype), shape=list(matrix.shape), features=spec["features"],
                            rows=[dict(id=identity, values=dict(zip(spec["features"], row)))
                                  for identity, row in zip(spec["ids"], matrix)])
    return dict(tables=tables, edges=observation["edges"], meta=observation["meta"])


def _commands(env):
    import numpy as np
    t = int(env.time_step)
    storage = {b.name: (0.5 if t % 2 == 0 else -0.4) if b.name == "Building_1"
               else (-0.2 if t % 2 == 0 else 0.4) for b in env.buildings}
    if env.interface == "flat":
        vectors = [np.asarray([storage[b.name] if name == "electrical_storage"
                               else 0.35 if name.startswith("electric_vehicle_storage_")
                               else float(t == 0) if name.startswith("deferrable_appliance_")
                               else 0.0 for name in b.active_actions], dtype="float32") for b in env.buildings]
        return [np.concatenate(vectors)]
    payload = {"tables": {name: np.zeros(space.shape, dtype="float32")
                          for name, space in env.action_space["tables"].items()}}
    for table, spec in env.entity_specs["actions"].items():
        for column, feature in enumerate(spec["features"]):
            if table == "building" and feature == "electrical_storage":
                payload["tables"][table][:, column] = [storage[name] for name in spec["ids"]]
            elif table == "charger":
                payload["tables"][table][:, column] = 0.35
            elif table == "deferrable_appliance":
                payload["tables"][table][:, column] = float(t == 0)
    return payload


def run_case(name, directory):
    import pandas as pd
    from citylearn.citylearn import CityLearnEnv
    from citylearn.internal.balance_audit import IndependentBalanceAudit
    from scripts.audit.audit_entity_contract import normalize_entity_specs
    (ROOT / 'tests/data/minute_ev_demo/schema.json').resolve(strict=True)
    sys.path.insert(0, str(ROOT / "tests"))
    from test_independent_balances import scenario

    config = CASES[name]
    directory.mkdir(parents=True, exist_ok=True)
    initial = scenario(directory, seconds=config["seconds"], outage=config.get("outage", False), phase_limits=True)
    schema = deepcopy(initial.schema)
    initial.close()
    schema["interface"] = config["interface"]
    schema["community_market"]["grid_export_price"] = 0.0
    if config.get("dynamic"):
        schema["buildings"]["Building_2"]["include"] = False
        schema.update(topology_mode="dynamic", topology_events=[
            dict(id="join", time_step=2, operation="add_member", target_member_id="Building_2"),
            dict(id="leave", time_step=4, operation="remove_member", target_member_id="Building_2"),
            dict(id="return", time_step=6, operation="add_member", target_member_id="Building_2"),
        ])
        path = directory / "faults.csv"
        common = dict(target_type="storage", target_id="Building_1", start_time_step=1, end_time_step=3)
        pd.DataFrame([
            dict(event_id="outage", module="asset", target_feature="control", mode="unavailable", **common),
            dict(event_id="channel", module="action", target_feature="electrical_storage", mode="bias", value=0.8, **common),
            dict(event_id="future_sensor", module="observation", target_type="building", target_id="Building_2",
                 target_feature="non_shiftable_load", mode="bias", value=0.25, start_time_step=0, end_time_step=7),
        ]).to_csv(path, index=False)
        schema["robustness"] = dict(enabled=True, events_file=str(path), random_seed=7)
    inputs = {str(p.relative_to(directory)): pd.read_csv(p).to_dict("list")
              for p in sorted(directory.rglob("*.csv"))}
    fingerprint = hashlib.sha256(json.dumps(canonical(dict(schema=schema, inputs=inputs), directory),
                                            sort_keys=True, allow_nan=False).encode()).hexdigest()
    env = CityLearnEnv(schema, random_seed=7, offline=True, central_agent=True,
                       render_mode="none", render_directory=directory / "exports", render_session_name="parity",
                       physics_invariant_checks=True, export_kpis_on_episode_end=False)
    try:
        observation, _ = env.reset(seed=7)
        result = dict(input_fingerprint=fingerprint, configuration=config,
                      initial_observation=_observations(env, observation), layouts=[], transitions=[])
        # Spaces are data, not repr strings (which can hide channel/shape drift).
        def space_data(space):
            from gymnasium import spaces
            if isinstance(space, list):
                return [space_data(item) for item in space]
            if isinstance(space, spaces.Dict):
                return {key: space_data(value) for key, value in space.spaces.items()}
            return dict(dtype=str(space.dtype), shape=list(space.shape), low=space.low, high=space.high)
        def layout_index():
            specs = (normalize_entity_specs(env.entity_specs) if env.interface == "entity"
                     else dict(observations=env.observation_names, actions=env.action_names))
            layout = canonical(dict(specs=specs, observation_space=space_data(env.observation_space),
                                    action_space=space_data(env.action_space)), directory)
            if not result["layouts"] or result["layouts"][-1] != layout:
                result["layouts"].append(layout)
            return len(result["layouts"]) - 1
        result["initial_layout"] = layout_index()
        with IndependentBalanceAudit(env) as audit:
            while not env.terminated:
                t = int(env.time_step)
                action = _commands(env)
                requested = env._runtime_service.parse_actions(action)
                buildings = list(env.buildings)
                observation, reward, *_ , info = env.step(action)
                physical = {}
                for building in buildings:
                    physical[building.name] = dict(
                        net_kwh=building.net_electricity_consumption[t],
                        base_kwh=building.non_shiftable_load_device.electricity_consumption[t],
                        storage_kwh=building.electrical_storage.electricity_consumption[t],
                        storage_soc=building.electrical_storage.soc[t],
                        pv_kwh=building.solar_generation[t],
                        machine_kwh=building.deferrable_appliances_electricity_consumption[t],
                        chargers={c.charger_id: c.electricity_consumption[t] for c in building.electric_vehicle_chargers or []},
                    )
                result["transitions"].append(dict(index=t, requested=requested,
                    execution=info.get("entity_action_execution"), physical=physical, reward=reward,
                    settlement=deepcopy(env._last_community_market_settlement), observation=_observations(env, observation),
                    layout=layout_index()))
            proof = audit.finish()
        kpis = env.evaluate_v2(include_business_as_usual=False)
        result["kpis"] = {f"{r.level}/{r.name}/{r.cost_function}": None if pd.isna(r.value) else r.value for r in kpis.itertuples()}
        result["service"] = env.get_deferrable_service_audit()
        result["robustness"] = env.get_robustness_audit() if env._robustness_service.enabled else None
        result["ev_soc"] = {ev.name: ev.battery.soc for ev in env.electric_vehicles}
        env.export_final_kpis(include_business_as_usual=False, export_business_as_usual_timeseries=False)
        export_dir = Path(env.new_folder_path)
        result["exported_kpis"] = pd.read_csv(export_dir / "exported_kpis.csv").to_dict("list")
        result["exported_service"] = json.loads((export_dir / "exported_kpis.deferrable_service.json").read_text())
        if env._robustness_service.enabled:
            result["exported_robustness"] = json.loads((export_dir / "exported_kpis.robustness.json").read_text())
        manifest = json.loads((export_dir / "exported_kpis.manifest.json").read_text())
        result["export_conditions"] = {key: manifest[key] for key in (
            "seconds_per_time_step", "random_seed", "completed_intervals",
            "episode_start_time_step", "episode_end_time_step", "community_market", "energy_accounting")}
        return canonical(result, directory), dict(status=proof["status"], intervals=proof["completed_intervals"], checks=proof["checks"])
    finally:
        env.close()


def capture(directory):
    cases, proofs = {}, {}
    for name in CASES:
        cases[name], proofs[name] = run_case(name, directory / name)
    return dict(definition_version=DEFINITION, tolerances=TOLERANCES, cases=cases), proofs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    mode.add_argument("--capture-reference", type=Path, help="Write a NEW reference proposal; never overwrite an existing reference.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    protected = {DEFAULT_REFERENCE.resolve(), args.reference.expanduser().resolve()}
    if args.capture_reference:
        protected.add(args.capture_reference.expanduser().resolve())
    if args.output.expanduser().resolve() in protected:
        parser.error("The output report must differ from all reference/proposal files.")
    if args.capture_reference and args.capture_reference.exists():
        parser.error("Reference proposal already exists; verification never updates references.")
    try:
        expected = None if args.capture_reference else json.loads(args.reference.read_text())
        with tempfile.TemporaryDirectory(prefix="simulator-parity-") as temporary:
            actual, proofs = capture(Path(temporary))
        if args.capture_reference:
            args.capture_reference.parent.mkdir(parents=True, exist_ok=True)
            args.capture_reference.write_text(json.dumps(actual, indent=2, sort_keys=True, allow_nan=False) + "\n")
            report = dict(status="reference_proposal", verification_passed=False, reference=str(args.capture_reference.resolve()), proofs=proofs)
        else:
            comparison = compare(expected, actual)
            report = dict(status="pass" if comparison["matches"] else "fail", verification_passed=comparison["matches"],
                          reference=str(args.reference.resolve()), comparison=comparison, proofs=proofs)
        code = 0 if args.capture_reference or report["verification_passed"] else 1
    except ModuleNotFoundError as error:
        report = dict(status="missing_dependencies", verification_passed=False, error=str(error))
        code = 2
    except Exception as error:
        # CLI boundary: preserve failures as diagnostics, never as a passing run.
        report = dict(status="fail", verification_passed=False, error_type=type(error).__name__, error=str(error))
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
