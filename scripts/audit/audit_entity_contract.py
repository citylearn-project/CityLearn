#!/usr/bin/env python3
"""Audit entity-mode API contract stability via normalized entity_specs snapshots."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

try:
    import numpy as np
except Exception:  # pragma: no cover - optional fallback
    np = None


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


REQUIRED_TOP_LEVEL_KEYS = [
    "version",
    "temporal_semantics",
    "normalization",
    "tables",
    "actions",
    "edges",
    "topology",
]
REQUIRED_FEATURE_METADATA_KEYS = {"unit", "bundle", "legacy"}


@dataclass(frozen=True)
class DatasetConfig:
    name: str
    schema_path: Path
    interface: str = "entity"
    topology_mode: Optional[str] = None
    seed: int = 0
    episode_time_steps: int = 8


def _jsonable(value: Any) -> Any:
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _ordered_dict(keys: Iterable[str], source: Mapping[str, Any]) -> Dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _normalize_table_spec(table_spec: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ids": list(table_spec.get("ids", [])),
        "features": list(table_spec.get("features", [])),
        "units": list(table_spec.get("units", [])),
        "feature_metadata": _jsonable(table_spec.get("feature_metadata", {})),
    }


def normalize_entity_specs(specs: Mapping[str, Any]) -> Dict[str, Any]:
    table_order = ["district", "building", "charger", "ev", "storage", "pv", "deferrable_appliance"]
    action_order = ["building", "charger", "deferrable_appliance"]
    edge_order = [
        "district_to_building",
        "building_to_charger",
        "building_to_storage",
        "building_to_pv",
        "building_to_deferrable_appliance",
        "charger_to_ev_connected",
        "charger_to_ev_incoming",
    ]

    tables = specs.get("tables", {}) if isinstance(specs.get("tables"), Mapping) else {}
    actions = specs.get("actions", {}) if isinstance(specs.get("actions"), Mapping) else {}
    edges = specs.get("edges", {}) if isinstance(specs.get("edges"), Mapping) else {}

    normalized_tables: Dict[str, Any] = {}
    for table_name in table_order:
        if table_name in tables:
            normalized_tables[table_name] = _normalize_table_spec(tables[table_name])
    for table_name in sorted(k for k in tables.keys() if k not in normalized_tables):
        normalized_tables[str(table_name)] = _normalize_table_spec(tables[table_name])

    normalized_actions: Dict[str, Any] = {}
    for action_name in action_order:
        if action_name in actions:
            action_spec = actions[action_name]
            normalized_actions[action_name] = {
                "ids": list(action_spec.get("ids", [])),
                "features": list(action_spec.get("features", [])),
                "units": list(action_spec.get("units", [])),
            }
    for action_name in sorted(k for k in actions.keys() if k not in normalized_actions):
        action_spec = actions[action_name]
        normalized_actions[str(action_name)] = {
            "ids": list(action_spec.get("ids", [])),
            "features": list(action_spec.get("features", [])),
            "units": list(action_spec.get("units", [])),
        }

    normalized_edges: Dict[str, Any] = {}
    for edge_name in edge_order:
        if edge_name in edges:
            normalized_edges[edge_name] = _jsonable(edges[edge_name])
    for edge_name in sorted(k for k in edges.keys() if k not in normalized_edges):
        normalized_edges[str(edge_name)] = _jsonable(edges[edge_name])

    normalized = {
        "version": specs.get("version"),
        "temporal_semantics": _jsonable(specs.get("temporal_semantics", {})),
        "normalization": _jsonable(specs.get("normalization", {})),
        "observation_bundles": _jsonable(specs.get("observation_bundles", {})),
        "tables": normalized_tables,
        "actions": normalized_actions,
        "edges": normalized_edges,
        "topology": _jsonable(specs.get("topology", {})),
    }

    return normalized


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _first_diff(a: Any, b: Any, path: str = "$") -> Optional[Dict[str, Any]]:
    if type(a) is not type(b):
        return {
            "path": path,
            "reason": "type_mismatch",
            "left_type": type(a).__name__,
            "right_type": type(b).__name__,
        }

    if isinstance(a, Mapping):
        a_keys = sorted(str(k) for k in a.keys())
        b_keys = sorted(str(k) for k in b.keys())
        if a_keys != b_keys:
            return {
                "path": path,
                "reason": "key_mismatch",
                "left_keys": a_keys,
                "right_keys": b_keys,
            }

        for key in a_keys:
            diff = _first_diff(a[key], b[key], f"{path}.{key}")
            if diff is not None:
                return diff

        return None

    if isinstance(a, list):
        if len(a) != len(b):
            return {
                "path": path,
                "reason": "length_mismatch",
                "left_length": len(a),
                "right_length": len(b),
            }

        for index, (left_item, right_item) in enumerate(zip(a, b)):
            diff = _first_diff(left_item, right_item, f"{path}[{index}]")
            if diff is not None:
                return diff

        return None

    if a != b:
        return {
            "path": path,
            "reason": "value_mismatch",
            "left": a,
            "right": b,
        }

    return None


def _validate_feature_contract(specs: Mapping[str, Any]) -> List[str]:
    issues: List[str] = []
    tables = specs.get("tables")
    if not isinstance(tables, Mapping):
        issues.append("top_level.tables is missing or not a mapping")
        return issues

    for table_name, table_spec in tables.items():
        if not isinstance(table_spec, Mapping):
            issues.append(f"tables.{table_name} is not a mapping")
            continue

        features = table_spec.get("features")
        units = table_spec.get("units")
        feature_metadata = table_spec.get("feature_metadata")

        if not isinstance(features, list):
            issues.append(f"tables.{table_name}.features is not a list")
            continue
        if not isinstance(units, list):
            issues.append(f"tables.{table_name}.units is not a list")
            continue
        if not isinstance(feature_metadata, Mapping):
            issues.append(f"tables.{table_name}.feature_metadata is not a mapping")
            continue

        if len(features) != len(units):
            issues.append(
                f"tables.{table_name}: features/units length mismatch ({len(features)} vs {len(units)})"
            )

        if len(set(features)) != len(features):
            issues.append(f"tables.{table_name}: duplicate feature names")

        feature_keys = list(feature_metadata.keys())
        if set(feature_keys) != set(features):
            missing = [name for name in features if name not in feature_metadata]
            extra = [name for name in feature_keys if name not in set(features)]
            issues.append(
                f"tables.{table_name}: feature_metadata key mismatch missing={missing} extra={extra}"
            )

        for index, feature_name in enumerate(features):
            metadata = feature_metadata.get(feature_name)
            if not isinstance(metadata, Mapping):
                issues.append(f"tables.{table_name}.feature_metadata[{feature_name}] is not a mapping")
                continue

            keys = set(metadata.keys())
            if keys != REQUIRED_FEATURE_METADATA_KEYS:
                issues.append(
                    f"tables.{table_name}.feature_metadata[{feature_name}] keys mismatch "
                    f"expected={sorted(REQUIRED_FEATURE_METADATA_KEYS)} got={sorted(keys)}"
                )

            if index < len(units) and metadata.get("unit") != units[index]:
                issues.append(
                    f"tables.{table_name}: unit mismatch for {feature_name} "
                    f"units[{index}]={units[index]!r} metadata.unit={metadata.get('unit')!r}"
                )

    actions = specs.get("actions")
    if not isinstance(actions, Mapping):
        issues.append("top_level.actions is missing or not a mapping")
        return issues

    for action_name, action_spec in actions.items():
        if not isinstance(action_spec, Mapping):
            issues.append(f"actions.{action_name} is not a mapping")
            continue

        features = action_spec.get("features")
        units = action_spec.get("units")
        ids = action_spec.get("ids")

        if not isinstance(features, list):
            issues.append(f"actions.{action_name}.features is not a list")
            continue
        if not isinstance(units, list):
            issues.append(f"actions.{action_name}.units is not a list")
            continue
        if not isinstance(ids, list):
            issues.append(f"actions.{action_name}.ids is not a list")
            continue

        if len(features) != len(units):
            issues.append(
                f"actions.{action_name}: features/units length mismatch ({len(features)} vs {len(units)})"
            )

        if len(set(features)) != len(features):
            issues.append(f"actions.{action_name}: duplicate feature names")
        if len(set(ids)) != len(ids):
            issues.append(f"actions.{action_name}: duplicate ids")

    return issues


def _validate_required_keys(specs: Mapping[str, Any]) -> Tuple[bool, List[str]]:
    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in specs]
    return len(missing) == 0, missing


def _determinism_issues(first: Mapping[str, Any], second: Mapping[str, Any]) -> List[str]:
    issues: List[str] = []

    for table_name, table_spec in first.get("tables", {}).items():
        if table_name not in second.get("tables", {}):
            issues.append(f"tables.{table_name} missing on second reset")
            continue

        second_table = second["tables"][table_name]
        if table_spec.get("ids") != second_table.get("ids"):
            issues.append(f"tables.{table_name}.ids order differs across same-seed resets")
        if table_spec.get("features") != second_table.get("features"):
            issues.append(f"tables.{table_name}.features order differs across same-seed resets")
        if table_spec.get("units") != second_table.get("units"):
            issues.append(f"tables.{table_name}.units order differs across same-seed resets")

    for action_name, action_spec in first.get("actions", {}).items():
        if action_name not in second.get("actions", {}):
            issues.append(f"actions.{action_name} missing on second reset")
            continue

        second_action = second["actions"][action_name]
        if action_spec.get("ids") != second_action.get("ids"):
            issues.append(f"actions.{action_name}.ids order differs across same-seed resets")
        if action_spec.get("features") != second_action.get("features"):
            issues.append(f"actions.{action_name}.features order differs across same-seed resets")
        if action_spec.get("units") != second_action.get("units"):
            issues.append(f"actions.{action_name}.units order differs across same-seed resets")

    if first != second:
        diff = _first_diff(first, second)
        if diff is not None:
            issues.append(f"full_snapshot differs at {diff['path']}: {diff['reason']}")

    return issues


def _load_runtime_specs(dataset: DatasetConfig) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    from citylearn.citylearn import CityLearnEnv

    kwargs: Dict[str, Any] = {
        "interface": dataset.interface,
        "central_agent": True,
        "episode_time_steps": dataset.episode_time_steps,
        "random_seed": dataset.seed,
    }
    if dataset.topology_mode is not None:
        kwargs["topology_mode"] = dataset.topology_mode

    env = CityLearnEnv(str(dataset.schema_path), **kwargs)
    try:
        env.reset(seed=dataset.seed)
        specs_first = copy.deepcopy(env.entity_specs)

        env.reset(seed=dataset.seed)
        specs_second = copy.deepcopy(env.entity_specs)
    finally:
        env.close()

    return specs_first, specs_second


def _audit_dataset(
    dataset: DatasetConfig,
    snapshot_dir: Path,
    update_snapshots: bool,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "name": dataset.name,
        "schema_path": str(dataset.schema_path),
        "snapshot_path": str(snapshot_dir / f"{dataset.name}.json"),
        "status": "fail",
        "checks": {},
        "snapshot": {},
    }

    try:
        specs_first_raw, specs_second_raw = _load_runtime_specs(dataset)
    except Exception as exc:
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        return report

    specs_first = normalize_entity_specs(specs_first_raw)
    specs_second = normalize_entity_specs(specs_second_raw)

    keys_ok, missing_keys = _validate_required_keys(specs_first_raw)
    report["checks"]["required_top_level_keys"] = {
        "ok": keys_ok,
        "missing": missing_keys,
    }

    feature_issues = _validate_feature_contract(specs_first_raw)
    report["checks"]["names_order_units_feature_metadata"] = {
        "ok": len(feature_issues) == 0,
        "issues": feature_issues,
    }

    determinism_issues = _determinism_issues(specs_first, specs_second)
    report["checks"]["deterministic_order_same_seed"] = {
        "ok": len(determinism_issues) == 0,
        "issues": determinism_issues,
    }

    runtime_hash = _hash_payload(specs_first)
    report["runtime_snapshot_sha256"] = runtime_hash

    snapshot_path = snapshot_dir / f"{dataset.name}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    expected_exists = snapshot_path.exists()
    expected_snapshot = None
    if expected_exists:
        expected_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    drift = False
    drift_detail = None
    if expected_snapshot is None:
        drift = True
        drift_detail = {
            "reason": "missing_snapshot",
            "path": None,
        }
    else:
        drift_detail = _first_diff(expected_snapshot, specs_first)
        drift = drift_detail is not None

    updated = False
    if update_snapshots:
        snapshot_path.write_text(json.dumps(specs_first, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        updated = True
        expected_exists = True
        expected_snapshot = specs_first
        drift = False
        drift_detail = None

    report["snapshot"] = {
        "exists": expected_exists,
        "updated": updated,
        "drift": drift,
        "drift_detail": drift_detail,
        "snapshot_sha256": _hash_payload(expected_snapshot) if expected_snapshot is not None else None,
    }

    all_checks_ok = all(check.get("ok", False) for check in report["checks"].values())
    report["status"] = "pass" if all_checks_ok else "fail"
    report["normalized_snapshot"] = specs_first
    return report


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    default_output_dir = repo_root / "outputs" / "audit"

    parser = argparse.ArgumentParser(description="Audit entity_specs API contract stability.")
    parser.add_argument(
        "--update-snapshots",
        action="store_true",
        help="Write current normalized snapshots to scripts/audit/snapshots/*.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir,
        help="Directory where entity_contract_audit.json is written (default: outputs/audit).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero exit code when snapshot drift is detected.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    snapshot_dir = Path(__file__).resolve().parent / "snapshots"

    datasets = [
        DatasetConfig(
            name="official_static",
            schema_path=repo_root / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json",
            topology_mode="static",
            episode_time_steps=8,
            seed=0,
        ),
        DatasetConfig(
            name="dynamic_topology_demo",
            schema_path=repo_root / "data/datasets/citylearn_three_phase_dynamic_topology_demo/schema.json",
            topology_mode="dynamic",
            episode_time_steps=12,
            seed=0,
        ),
    ]

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strict": bool(args.strict),
        "update_snapshots": bool(args.update_snapshots),
        "datasets": [],
        "summary": {},
    }

    for dataset in datasets:
        dataset_report = _audit_dataset(
            dataset=dataset,
            snapshot_dir=snapshot_dir,
            update_snapshots=bool(args.update_snapshots),
        )
        report["datasets"].append(dataset_report)

    total = len(report["datasets"])
    failed_contract = sum(1 for item in report["datasets"] if item.get("status") != "pass")
    drifted = sum(1 for item in report["datasets"] if item.get("snapshot", {}).get("drift") is True)
    report["summary"] = {
        "total_datasets": total,
        "failed_contract": failed_contract,
        "drifted_snapshots": drifted,
        "all_contract_checks_passed": failed_contract == 0,
    }

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "entity_contract_audit.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    should_fail = False
    if failed_contract > 0:
        should_fail = True
    if args.strict and drifted > 0:
        should_fail = True

    if should_fail:
        print(f"[entity-contract-audit] FAIL -> {output_path}")
        return 1

    print(f"[entity-contract-audit] PASS -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
