#!/usr/bin/env python3
"""Audit local CityLearn datasets for schema/data/runtime sanity."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import sys
import time
import traceback
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import numpy as np
except ModuleNotFoundError as exc:  # pragma: no cover - dependency gate
    np = None
    _NUMPY_IMPORT_ERROR = exc
else:
    _NUMPY_IMPORT_ERROR = None


DATASETS_ROOT = REPO_ROOT / "data/datasets"
OUTPUT_PATH = Path("outputs/audit/datasets_audit.json")
SUPPORTED_ASSET_TYPES = {"charger", "pv", "electrical_storage", "deferrable_appliance"}


class DependencyError(RuntimeError):
    """Raised when runtime dependencies are not available."""


@dataclass
class AuditContext:
    max_steps: int
    offline: bool
    fail_fast: bool
    dependency_error: Optional[str] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help="Maximum rollout steps per check.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run CityLearnEnv in offline mode.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at first hard failure.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Path to output JSON report (default: outputs/audit/datasets_audit.json).",
    )
    return parser.parse_args()


def discover_schema_paths(root: Path) -> List[Path]:
    if not root.exists():
        return []
    paths = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        evaluation = sorted((directory / "evaluation").glob("*.json"))
        if evaluation:
            paths.extend(evaluation)
        elif (directory / "schema.json").is_file():
            paths.append(directory / "schema.json")
    return paths


def read_json(path: Path) -> Mapping[str, Any]:
    from citylearn.utils.file_handler import FileHandler
    return FileHandler.read_json(path)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def dataset_root_from_schema(schema: Mapping[str, Any], dataset_dir: Path) -> Path:
    root = schema.get("root_directory")
    if root is None or str(root).strip() == "":
        return dataset_dir.resolve()
    root_path = Path(str(root))
    if not root_path.is_absolute():
        root_path = (dataset_dir / root_path).resolve()
    return root_path


def collect_csv_references(obj: Any, path: str = "$", out: Optional[List[Tuple[str, str]]] = None) -> List[Tuple[str, str]]:
    out = [] if out is None else out

    if isinstance(obj, Mapping):
        for key, value in obj.items():
            collect_csv_references(value, f"{path}.{key}", out)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            collect_csv_references(value, f"{path}[{index}]", out)
    elif isinstance(obj, str) and obj.lower().endswith(".csv"):
        out.append((path, obj))

    return out


def validate_csv_files(schema: Mapping[str, Any], dataset_dir: Path) -> Dict[str, Any]:
    start = time.perf_counter()
    refs = collect_csv_references(schema)
    root = dataset_root_from_schema(schema, dataset_dir)
    unique_by_rel: Dict[str, List[str]] = {}
    errors: List[str] = []

    for ref_path, rel_path in refs:
        unique_by_rel.setdefault(rel_path, []).append(ref_path)

    checked_files = 0
    for rel_path, ref_paths in sorted(unique_by_rel.items(), key=lambda kv: kv[0]):
        file_path = Path(rel_path)
        if not file_path.is_absolute():
            file_path = root / file_path
        file_path = file_path.resolve()

        if not file_path.exists():
            errors.append(
                f"Missing CSV '{rel_path}' referenced at {', '.join(ref_paths)} (resolved: {file_path})."
            )
            continue

        if not file_path.is_file():
            errors.append(
                f"CSV path '{rel_path}' is not a file at {file_path}."
            )
            continue

        try:
            with file_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                try:
                    header = next(reader)
                except StopIteration:
                    errors.append(f"CSV '{rel_path}' is empty (no header).")
                    continue
                if header is None or len(header) == 0:
                    errors.append(f"CSV '{rel_path}' has an empty header.")
                    continue
                try:
                    _ = next(reader)
                except StopIteration:
                    errors.append(f"CSV '{rel_path}' has header only (no data rows).")
                    continue
        except UnicodeDecodeError:
            errors.append(f"CSV '{rel_path}' is not valid UTF-8 text.")
            continue
        except Exception as exc:
            errors.append(f"CSV '{rel_path}' unreadable: {type(exc).__name__}: {exc}")
            continue

        checked_files += 1

    duration_s = time.perf_counter() - start
    return {
        "status": "pass" if len(errors) == 0 else "fail",
        "duration_s": duration_s,
        "total_references": len(refs),
        "unique_files": len(unique_by_rel),
        "checked_files": checked_files,
        "errors": errors,
    }


def _building_asset_index(schema: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    buildings = schema.get("buildings", {})
    index: Dict[str, Dict[str, Any]] = {}

    if not isinstance(buildings, Mapping):
        return index

    for member_id, member_schema in buildings.items():
        member_data = member_schema if isinstance(member_schema, Mapping) else {}
        chargers = member_data.get("chargers", {})
        chargers = chargers if isinstance(chargers, Mapping) else {}
        index[str(member_id)] = {
            "has_pv": member_data.get("pv") is not None,
            "has_storage": member_data.get("electrical_storage") is not None,
            "chargers": set(str(c) for c in chargers.keys()),
            "deferrable_appliances": set(str(a) for a in (member_data.get('deferrable_appliances') or {})),
        }

    return index


def _member_has_asset(
    asset_index: Mapping[str, Mapping[str, Any]],
    member_id: str,
    asset_type: str,
    asset_id: Optional[str],
) -> bool:
    member = asset_index.get(member_id)
    if member is None:
        return False

    if asset_type == "charger":
        if asset_id is None or str(asset_id).strip() == "":
            return False
        return str(asset_id) in set(member.get("chargers", set()))

    if asset_type == "pv":
        # Runtime PV/storage resolution is by the member's singleton slot;
        # event IDs are descriptive labels, not dictionary lookup keys.
        return bool(member.get("has_pv", False))

    if asset_type == "electrical_storage":
        return bool(member.get("has_storage", False))

    if asset_type == 'deferrable_appliance':
        return asset_id in member.get('deferrable_appliances', set())

    return False


def validate_dynamic_events(schema: Mapping[str, Any]) -> Dict[str, Any]:
    start = time.perf_counter()
    errors: List[str] = []
    warnings: List[str] = []
    topology_mode = str(schema.get("topology_mode", "static")).strip().lower()
    raw_events = schema.get("topology_events", [])

    if topology_mode != "dynamic" and not raw_events:
        return {
            "status": "skip",
            "duration_s": time.perf_counter() - start,
            "event_count": 0,
            "errors": [],
            "warnings": [],
            "message": "No dynamic topology events.",
        }

    if not isinstance(raw_events, list):
        return {
            "status": "fail",
            "duration_s": time.perf_counter() - start,
            "event_count": 0,
            "errors": ["topology_events must be a list when provided."],
            "warnings": [],
        }

    buildings = schema.get("buildings", {})
    member_ids = set(str(k) for k in buildings.keys()) if isinstance(buildings, Mapping) else set()
    asset_index = _building_asset_index(schema)
    seen_event_ids = set()
    previous_key: Optional[Tuple[int, str]] = None

    for i, event in enumerate(raw_events):
        if not isinstance(event, Mapping):
            errors.append(f"topology_events[{i}] must be an object.")
            continue

        event_id = str(event.get("id", f"topology_event_{i}"))
        if event_id in seen_event_ids:
            errors.append(f"Duplicate topology event id '{event_id}'.")
        seen_event_ids.add(event_id)

        if "time_step" not in event:
            errors.append(f"topology_events[{i}] missing required field 'time_step'.")
            continue
        try:
            time_step = int(event["time_step"])
        except Exception:
            errors.append(f"topology_events[{i}].time_step must be an integer.")
            continue
        if time_step < 0:
            errors.append(f"topology_events[{i}].time_step must be >= 0.")

        op = str(event.get("operation", "")).strip().lower()
        if op not in {"add_member", "remove_member", "add_asset", "remove_asset"}:
            errors.append(f"topology_events[{i}].operation '{op}' is not supported.")
            continue

        order_key = (time_step, event_id)
        if previous_key is not None and order_key < previous_key:
            warnings.append(
                f"Event order is not deterministic at index {i}; expected sorted by (time_step, id)."
            )
        previous_key = order_key

        target_member = event.get("target_member_id")
        target_member = None if target_member is None else str(target_member).strip()
        source_member = event.get("source_member_id")
        source_member = None if source_member is None else str(source_member).strip()
        target_asset_type = event.get("target_asset_type")
        target_asset_type = None if target_asset_type is None else str(target_asset_type).strip().lower()
        target_asset_id = event.get("target_asset_id")
        target_asset_id = None if target_asset_id is None else str(target_asset_id).strip()
        source_asset_id = event.get("source_asset_id")
        source_asset_id = None if source_asset_id is None else str(source_asset_id).strip()

        if op == "add_member":
            if target_member is None or target_member == "":
                errors.append(f"topology_events[{i}] add_member requires target_member_id.")
                continue
            if target_member not in member_ids:
                if source_member is None or source_member not in member_ids:
                    errors.append(
                        f"topology_events[{i}] add_member target '{target_member}' not in member pool and source_member_id is invalid."
                    )
            continue

        if op == "remove_member":
            if target_member is None or target_member == "":
                errors.append(f"topology_events[{i}] remove_member requires target_member_id.")
                continue
            if target_member not in member_ids:
                errors.append(
                    f"topology_events[{i}] remove_member target_member_id '{target_member}' not found in member pool."
                )
            continue

        if op in {"add_asset", "remove_asset"}:
            if target_member is None or target_member == "":
                errors.append(f"topology_events[{i}] {op} requires target_member_id.")
                continue
            if target_member not in member_ids:
                errors.append(
                    f"topology_events[{i}] target_member_id '{target_member}' not found in member pool."
                )
                continue
            if target_asset_type not in SUPPORTED_ASSET_TYPES:
                errors.append(
                    f"topology_events[{i}] target_asset_type '{target_asset_type}' is invalid; expected one of {sorted(SUPPORTED_ASSET_TYPES)}."
                )
                continue

            if op == "remove_asset":
                if not _member_has_asset(asset_index, target_member, target_asset_type, target_asset_id):
                    errors.append(
                        f"topology_events[{i}] remove_asset target '{target_asset_type}:{target_asset_id}' not resolvable in member '{target_member}'."
                    )
                continue

            # add_asset checks
            source_resolved = source_member if source_member not in {None, ""} else target_member
            if source_resolved not in member_ids:
                errors.append(
                    f"topology_events[{i}] add_asset source_member_id '{source_resolved}' not found in member pool."
                )
                continue
            expected_source_asset_id = source_asset_id if source_asset_id not in {None, ""} else target_asset_id
            if not _member_has_asset(asset_index, source_resolved, target_asset_type, expected_source_asset_id):
                errors.append(
                    f"topology_events[{i}] add_asset source '{target_asset_type}:{expected_source_asset_id}' not resolvable in member '{source_resolved}'."
                )
                continue
            if target_asset_type == "charger" and (target_asset_id is None or target_asset_id == ""):
                errors.append(f"topology_events[{i}] add_asset charger requires target_asset_id.")
            if target_asset_type in {'charger', 'deferrable_appliance'} and target_asset_id:
                collection = 'chargers' if target_asset_type == 'charger' else 'deferrable_appliances'
                asset_index[target_member][collection].add(target_asset_id)

    duration_s = time.perf_counter() - start
    status = "pass" if len(errors) == 0 else "fail"
    return {
        "status": status,
        "duration_s": duration_s,
        "event_count": len(raw_events),
        "errors": errors,
        "warnings": warnings,
    }


def import_citylearn_env() -> Any:
    try:
        from citylearn.citylearn import CityLearnEnv  # pylint: disable=import-outside-toplevel
    except ModuleNotFoundError as exc:
        missing = exc.name or "unknown module"
        raise DependencyError(
            f"Missing dependency '{missing}'. Install simulator runtime dependencies (e.g. gymnasium) to run rollouts."
        ) from exc
    except Exception as exc:
        raise DependencyError(f"Failed to import CityLearnEnv: {type(exc).__name__}: {exc}") from exc
    return CityLearnEnv


def extract_entity_shapes(observation: Any) -> Dict[str, List[int]]:
    if not isinstance(observation, Mapping):
        return {}
    tables = observation.get("tables", {})
    if not isinstance(tables, Mapping):
        return {}
    out: Dict[str, List[int]] = {}
    for table_name, value in tables.items():
        arr = np.asarray(value)
        out[str(table_name)] = [int(x) for x in arr.shape]
    return out


def build_zero_action(env: Any) -> Any:
    interface = str(getattr(env, "interface", "flat"))
    if interface == "entity":
        action_specs = env.entity_specs.get("actions", {})
        building_ids = action_specs.get("building", {}).get("ids", [])
        building_features = action_specs.get("building", {}).get("features", [])
        charger_ids = action_specs.get("charger", {}).get("ids", [])
        charger_features = action_specs.get("charger", {}).get("features", [])
        deferrable_ids = action_specs.get("deferrable_appliance", {}).get("ids", [])
        deferrable_features = action_specs.get("deferrable_appliance", {}).get("features", [])
        building_table = np.zeros((len(building_ids), len(building_features)), dtype=np.float32)
        charger_table = np.zeros((len(charger_ids), len(charger_features)), dtype=np.float32)
        deferrable_table = np.zeros((len(deferrable_ids), len(deferrable_features)), dtype=np.float32)
        return {
            "tables": {
                "building": building_table,
                "charger": charger_table,
                "deferrable_appliance": deferrable_table,
            }
        }

    if bool(getattr(env, "central_agent", False)):
        shape = tuple(int(x) for x in env.action_space[0].shape)
        return np.zeros(shape, dtype=np.float32)

    action_vectors = []
    for space in env.action_space:
        shape = tuple(int(x) for x in space.shape)
        action_vectors.append(np.zeros(shape, dtype=np.float32))
    return action_vectors


def run_rollout(
    citylearn_env_cls: Any,
    *,
    schema_input: Any,
    offline: bool,
    max_steps: int,
    interface: Optional[str] = None,
    topology_mode: Optional[str] = None,
    require_dynamic_shape_change: bool = False,
) -> Dict[str, Any]:
    start = time.perf_counter()
    env = None
    result: Dict[str, Any] = {
        "status": "pass",
        "steps_executed": 0,
        "duration_s": 0.0,
        "interface": interface,
        "topology_mode": topology_mode,
        "shape_change_count": None,
        "topology_version_span": None,
        "error": None,
    }

    try:
        kwargs: Dict[str, Any] = {
            "schema": schema_input,
            "offline": offline,
            "render_mode": "none",
            "export_kpis_on_episode_end": False,
        }
        if interface is not None:
            kwargs["interface"] = interface
        if topology_mode is not None:
            kwargs["topology_mode"] = topology_mode

        from citylearn.internal.capabilities import unsupported_reason
        schema = read_json(Path(schema_input)) if isinstance(schema_input, (str, Path)) else schema_input
        reason = unsupported_reason(schema, interface=interface, topology_mode=topology_mode)
        if reason:
            result.update(status="skip", error=reason)
            return result
        # A short catalogue probe must not allocate two years of episode state.
        start_step = safe_int(schema.get('simulation_start_time_step', 0))
        end_step = safe_int(schema.get('simulation_end_time_step', start_step+max_steps))
        kwargs.update(episode_time_steps=min(max_steps+1, max(end_step-start_step+1, 1)),
                      simulation_start_time_step=start_step,
                      simulation_end_time_step=min(end_step, start_step+max_steps),
                      rolling_episode_split=False, random_episode_split=False)
        env = citylearn_env_cls(**kwargs)
        obs, _ = env.reset()
        shape_history: List[Dict[str, List[int]]] = []
        topology_versions: List[int] = []
        if str(getattr(env, "interface", "flat")) == "entity":
            shape_history.append(extract_entity_shapes(obs))
        topology_versions.append(int(getattr(env, "topology_version", 0)))

        for _ in range(max_steps):
            if bool(getattr(env, "terminated", False)) or bool(getattr(env, "truncated", False)):
                break
            action = build_zero_action(env)
            obs, _, _, _, _ = env.step(action)
            result["steps_executed"] += 1
            if str(getattr(env, "interface", "flat")) == "entity":
                shape_history.append(extract_entity_shapes(obs))
            topology_versions.append(int(getattr(env, "topology_version", 0)))

        if shape_history:
            changes = 0
            for i in range(1, len(shape_history)):
                if shape_history[i] != shape_history[i - 1]:
                    changes += 1
            result["shape_change_count"] = int(changes)

        if topology_versions:
            result["topology_version_span"] = int(max(topology_versions) - min(topology_versions))

        if require_dynamic_shape_change:
            shape_changes = int(result.get("shape_change_count") or 0)
            topo_span = int(result.get("topology_version_span") or 0)
            initial_topo = int(topology_versions[0]) if topology_versions else 0
            if shape_changes <= 0 and topo_span <= 0 and initial_topo <= 0:
                result["status"] = "fail"
                result["error"] = (
                    "Dynamic probe completed but did not observe any topology/shape change."
                )

    except Exception as exc:
        result["status"] = "fail"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback_tail"] = traceback.format_exc(limit=5)
    finally:
        if env is not None and hasattr(env, "close"):
            try:
                env.close()
            except Exception:
                pass
        env = None
        gc.collect()
        result["duration_s"] = time.perf_counter() - start

    return result


def build_dynamic_probe_schema(schema: Mapping[str, Any], dataset_dir: Path) -> Mapping[str, Any]:
    probe = deepcopy(schema)
    probe["root_directory"] = str(dataset_root_from_schema(schema, dataset_dir))
    raw_events = probe.get("topology_events", [])
    if not isinstance(raw_events, list):
        probe["topology_events"] = []
        return probe

    step_map: Dict[int, int] = {}
    next_step = 1
    for event in raw_events:
        if not isinstance(event, Mapping):
            continue
        t = safe_int(event.get("time_step", 0), default=0)
        if t == 0:
            step_map.setdefault(0, 0)
            continue
        if t not in step_map:
            step_map[t] = next_step
            next_step += 1

    for event in raw_events:
        if not isinstance(event, Mapping):
            continue
        t = safe_int(event.get("time_step", 0), default=0)
        if t == 0:
            event["time_step"] = 0
        else:
            event["time_step"] = step_map.get(t, 1)

    return probe


def audit_dataset(
    schema_path: Path,
    ctx: AuditContext,
    citylearn_env_cls: Optional[Any],
) -> Dict[str, Any]:
    dataset_start = time.perf_counter()
    dataset_dir = schema_path.parent
    dataset_name = dataset_dir.parent.name + "/" + schema_path.stem if dataset_dir.name == "evaluation" else dataset_dir.name
    schema = read_json(schema_path)
    topology_mode = str(schema.get("topology_mode", "static")).strip().lower()
    dataset_result: Dict[str, Any] = {
        "dataset": dataset_name,
        "schema_path": str(schema_path),
        "topology_mode": topology_mode,
        "status": "pass",
        "errors": [],
        "warnings": [],
        "checks": {},
        "duration_s": 0.0,
    }

    csv_check = validate_csv_files(schema, dataset_dir)
    dataset_result["checks"]["csv_files"] = csv_check
    if csv_check["status"] != "pass":
        dataset_result["errors"].extend(csv_check["errors"])

    dynamic_check = validate_dynamic_events(schema)
    dataset_result["checks"]["dynamic_events"] = dynamic_check
    if dynamic_check["status"] == "fail":
        dataset_result["errors"].extend(dynamic_check["errors"])
    dataset_result["warnings"].extend(dynamic_check.get("warnings", []))

    if citylearn_env_cls is None:
        dependency_error = ctx.dependency_error or "Missing runtime dependencies for CityLearnEnv."
        for key in ("rollout_default", "rollout_flat", "rollout_entity"):
            dataset_result["checks"][key] = {
                "status": "fail",
                "error": dependency_error,
                "steps_executed": 0,
                "duration_s": 0.0,
            }
        if topology_mode == "dynamic":
            dataset_result["checks"]["rollout_dynamic_probe"] = {
                "status": "fail",
                "error": dependency_error,
                "steps_executed": 0,
                "duration_s": 0.0,
            }
        dataset_result["errors"].append(dependency_error)
    else:
        # default schema behavior
        dataset_result["checks"]["rollout_default"] = run_rollout(
            citylearn_env_cls,
            schema_input=str(schema_path),
            offline=ctx.offline,
            max_steps=ctx.max_steps,
        )

        # explicit flat interface (when feasible)
        if topology_mode == "dynamic":
            dataset_result["checks"]["rollout_flat"] = {
                "status": "skip",
                "error": "Not feasible: topology_mode='dynamic' requires interface='entity'.",
                "steps_executed": 0,
                "duration_s": 0.0,
            }
        else:
            dataset_result["checks"]["rollout_flat"] = run_rollout(
                citylearn_env_cls,
                schema_input=str(schema_path),
                offline=ctx.offline,
                max_steps=ctx.max_steps,
                interface="flat",
            )

        # explicit entity interface
        dataset_result["checks"]["rollout_entity"] = run_rollout(
            citylearn_env_cls,
            schema_input=str(schema_path),
            offline=ctx.offline,
            max_steps=ctx.max_steps,
            interface="entity",
            topology_mode=topology_mode if topology_mode in {"static", "dynamic"} else None,
        )

        # dynamic probe with compressed event times to force near-term topology updates
        if topology_mode == "dynamic":
            probe_schema = build_dynamic_probe_schema(schema, dataset_dir)
            dataset_result["checks"]["rollout_dynamic_probe"] = run_rollout(
                citylearn_env_cls,
                schema_input=probe_schema,
                offline=ctx.offline,
                max_steps=max(ctx.max_steps, 2),
                interface="entity",
                topology_mode="dynamic",
                require_dynamic_shape_change=True,
            )

    for check_name, check_result in dataset_result["checks"].items():
        status = check_result.get("status")
        if status == "fail":
            error = check_result.get("error")
            if error is not None:
                dataset_result["errors"].append(f"{check_name}: {error}")
        elif status == "skip":
            message = check_result.get("error") or check_result.get("message")
            if message:
                dataset_result["warnings"].append(f"{check_name}: {message}")

    if len(dataset_result["errors"]) > 0:
        dataset_result["status"] = "fail"

    dataset_result["duration_s"] = time.perf_counter() - dataset_start
    return dataset_result


def write_report(report: Mapping[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
        f.write("\n")


def build_summary(datasets: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    total = len(datasets)
    passed = sum(1 for d in datasets if d.get("status") == "pass")
    failed = sum(1 for d in datasets if d.get("status") == "fail")
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
    }


def main() -> int:
    args = parse_args()
    if args.max_steps < 1:
        print("--max-steps must be >= 1", file=sys.stderr)
        return 2

    ctx = AuditContext(
        max_steps=int(args.max_steps),
        offline=bool(args.offline),
        fail_fast=bool(args.fail_fast),
    )

    schema_paths = discover_schema_paths(DATASETS_ROOT)
    datasets: List[Dict[str, Any]] = []
    hard_failure = False
    dependency_exit = False
    citylearn_env_cls: Optional[Any] = None

    if _NUMPY_IMPORT_ERROR is not None:
        ctx.dependency_error = (
            f"Missing dependency '{_NUMPY_IMPORT_ERROR.name or 'numpy'}'. "
            "Install simulator runtime dependencies to run rollouts."
        )
        dependency_exit = True
        citylearn_env_cls = None
        print(f"[datasets-audit] dependency error: {ctx.dependency_error}", file=sys.stderr)
    else:
        try:
            citylearn_env_cls = import_citylearn_env()
        except DependencyError as exc:
            ctx.dependency_error = str(exc)
            dependency_exit = True
            print(f"[datasets-audit] dependency error: {ctx.dependency_error}", file=sys.stderr)

    for schema_path in schema_paths:
        try:
            dataset_result = audit_dataset(schema_path, ctx, citylearn_env_cls)
        except Exception as exc:
            dataset_result = dict(dataset=schema_path.parent.name, schema_path=str(schema_path),
                                  status="fail", errors=[f"{type(exc).__name__}: {exc}"],
                                  warnings=[], checks={}, duration_s=0.0)
        datasets.append(dataset_result)
        print(f"[datasets-audit] {dataset_result['dataset']}: {dataset_result['status']}", flush=True)
        if dataset_result["status"] == "fail":
            hard_failure = True
            if ctx.fail_fast:
                break

    report = {
        "generated_at_utc": utc_now_iso(),
        "datasets_root": str(DATASETS_ROOT.resolve()),
        "output_path": str(args.output.resolve()),
        "max_steps": int(ctx.max_steps),
        "offline": bool(ctx.offline),
        "fail_fast": bool(ctx.fail_fast),
        "dependency_error": ctx.dependency_error,
        "summary": build_summary(datasets),
        "datasets": datasets,
    }
    write_report(report, args.output)

    if dependency_exit:
        return 2
    if hard_failure:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
