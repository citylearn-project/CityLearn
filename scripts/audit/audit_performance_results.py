#!/usr/bin/env python3
"""Performance audit runner.

This script combines:
- perf smoke style checks (reusing scripts/ci/perf_smoke.py),
- explicit physics invariant overhead measurement (on vs off).

It used to also compare long RBC and SAC runs with stored KPI snapshots. Those
snapshots were retired (#314): results are checked by the refactor parity audit
and the frozen references of the test suite.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.citylearn import CityLearnEnv  # noqa: E402

DEFAULT_SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
DEFAULT_OUTPUT = ROOT / "outputs/audit/performance_results_audit.json"
DEFAULT_PERF_BASELINE = ROOT / "scripts/ci/perf_baseline.json"
DEFAULT_SECONDS = 60
DEFAULT_PERF_STEPS = 600
DEFAULT_INVARIANT_OVERHEAD_RATIO_MAX = 1.10
DEFAULT_INVARIANT_OVERHEAD_MS_MAX = 1.0
DEFAULT_ENTITY_OVERHEAD_RATIO_MAX = 1.12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--strict", action="store_true")

    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--perf-baseline-file", type=Path, default=DEFAULT_PERF_BASELINE)
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS)
    parser.add_argument("--perf-steps", type=int, default=DEFAULT_PERF_STEPS)
    parser.add_argument("--entity-overhead-ratio-max", type=float, default=DEFAULT_ENTITY_OVERHEAD_RATIO_MAX)
    parser.add_argument("--invariant-overhead-ratio-max", type=float, default=DEFAULT_INVARIANT_OVERHEAD_RATIO_MAX)
    parser.add_argument("--invariant-overhead-ms-max", type=float, default=DEFAULT_INVARIANT_OVERHEAD_MS_MAX)
    return parser.parse_args()


def _json_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _git_short_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT)
            .decode("utf-8")
            .strip()
        )
    except Exception:
        return "unknown"


def _load_perf_smoke_module():
    path = ROOT / "scripts/ci/perf_smoke.py"
    spec = importlib.util.spec_from_file_location("perf_smoke_module", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load perf smoke module at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_flat_zero_action_case(
    schema: Path,
    episode_steps: int,
    seconds_per_time_step: int,
    seed: int,
    physics_invariant_checks: bool,
) -> Dict[str, Any]:
    kwargs = {
        "central_agent": True,
        "episode_time_steps": episode_steps,
        "seconds_per_time_step": seconds_per_time_step,
        # Same setting as scripts/ci/perf_smoke.py: a 60 s step on hourly data.
        "time_step_ratio_mode": "compress",
        "random_seed": seed,
        "debug_timing": True,
        "interface": "flat",
        "render_mode": "none",
        "physics_invariant_checks": physics_invariant_checks,
    }

    t0 = time.perf_counter()
    env = CityLearnEnv(str(schema), **kwargs)
    t1 = time.perf_counter()

    try:
        _, _ = env.reset()
        t2 = time.perf_counter()
        action = np.zeros(env.action_space[0].shape[0], dtype="float32")
        step_times = []

        while not env.terminated:
            s0 = time.perf_counter()
            _, _, terminated, truncated, _ = env.step([action])
            s1 = time.perf_counter()
            step_times.append(s1 - s0)
            if terminated or truncated:
                break

        t3 = time.perf_counter()
        avg_step_ms = float(np.mean(step_times) * 1000.0) if step_times else 0.0
        p95_step_ms = float(np.percentile(step_times, 95) * 1000.0) if step_times else 0.0
        return {
            "physics_invariant_checks": bool(physics_invariant_checks),
            "configured_steps": int(episode_steps),
            "executed_steps": int(len(step_times)),
            "seconds_per_time_step": int(seconds_per_time_step),
            "init_s": round(float(t1 - t0), 4),
            "reset_s": round(float(t2 - t1), 4),
            "rollout_s": round(float(t3 - t2), 4),
            "avg_step_ms": round(avg_step_ms, 4),
            "p95_step_ms": round(p95_step_ms, 4),
        }
    finally:
        env.close()


def _build_perf_report(
    perf_smoke_module,
    schema: Path,
    perf_steps: int,
    seconds_per_time_step: int,
    seed: int,
    perf_baseline_file: Path,
    entity_overhead_ratio_max: float,
) -> Dict[str, Any]:
    # Reuse CI perf smoke cases and threshold checks.
    perf_smoke_module.SCHEMA = Path(schema)
    none_case = perf_smoke_module.run_case("none", perf_steps, seconds_per_time_step, seed, interface="flat")
    end_case = perf_smoke_module.run_case("end", perf_steps, seconds_per_time_step, seed, interface="flat")
    entity_case = perf_smoke_module.run_case("none", perf_steps, seconds_per_time_step, seed, interface="entity")

    ns = SimpleNamespace(
        episode_steps=perf_steps,
        seconds=seconds_per_time_step,
        seed=seed,
        none_max_ms=30.0,
        end_max_ms=45.0,
        entity_max_ms=30.0,
        ratio_max=2.0,
        entity_overhead_ratio_max=float(entity_overhead_ratio_max),
        baseline_regression_ratio=2.5,
        baseline_slack_ms=5.0,
    )
    report = perf_smoke_module._build_report(ns, none_case, end_case, entity_case)

    errors = perf_smoke_module._validate_absolute_thresholds(
        report,
        none_max_ms=ns.none_max_ms,
        end_max_ms=ns.end_max_ms,
        entity_max_ms=ns.entity_max_ms,
        ratio_max=ns.ratio_max,
        entity_overhead_ratio_max=ns.entity_overhead_ratio_max,
    )

    baseline_loaded = False
    if perf_baseline_file.is_file():
        baseline_loaded = True
        baseline_data = json.loads(perf_baseline_file.read_text(encoding="utf-8"))
        errors.extend(
            perf_smoke_module._compare_to_baseline(
                report,
                baseline_data,
                regression_ratio=ns.baseline_regression_ratio,
                slack_ms=ns.baseline_slack_ms,
            )
        )

    report["baseline"] = {
        "path": str(perf_baseline_file),
        "loaded": bool(baseline_loaded),
    }
    report["errors"] = errors
    return report


def main() -> int:
    args = parse_args()
    schema = args.schema.resolve()
    output_path = args.output.resolve()

    commit = _git_short_sha()
    metadata = {
        "generated_utc": _utc_now(),
        "git_commit_short": commit,
        "schema": str(schema),
        "perf_steps": int(args.perf_steps),
        "seconds_per_time_step": int(args.seconds),
        "seed": int(args.seed),
    }

    report: Dict[str, Any] = {
        "metadata": metadata,
        "config": {
            "strict": bool(args.strict),
            "entity_overhead_ratio_max": float(args.entity_overhead_ratio_max),
            "invariant_overhead_ratio_max": float(args.invariant_overhead_ratio_max),
            "invariant_overhead_ms_max": float(args.invariant_overhead_ms_max),
        },
    }

    strict_errors = []

    perf_smoke_module = _load_perf_smoke_module()
    perf_report = _build_perf_report(
        perf_smoke_module=perf_smoke_module,
        schema=schema,
        perf_steps=args.perf_steps,
        seconds_per_time_step=args.seconds,
        seed=args.seed,
        perf_baseline_file=args.perf_baseline_file.resolve(),
        entity_overhead_ratio_max=args.entity_overhead_ratio_max,
    )
    report["performance_ci_smoke"] = perf_report

    # Explicit overhead of physics invariant checks.
    perf_off = _run_flat_zero_action_case(
        schema=schema,
        episode_steps=args.perf_steps,
        seconds_per_time_step=args.seconds,
        seed=args.seed,
        physics_invariant_checks=False,
    )
    perf_on = _run_flat_zero_action_case(
        schema=schema,
        episode_steps=args.perf_steps,
        seconds_per_time_step=args.seconds,
        seed=args.seed,
        physics_invariant_checks=True,
    )

    off_avg = float(perf_off["avg_step_ms"])
    on_avg = float(perf_on["avg_step_ms"])
    overhead_ratio = (on_avg / off_avg) if off_avg > 0.0 else float("inf")
    overhead_delta_ms = on_avg - off_avg
    invariant_regression = (
        overhead_ratio > float(args.invariant_overhead_ratio_max)
        and overhead_delta_ms > float(args.invariant_overhead_ms_max)
    )

    invariant_overhead_report = {
        "off": perf_off,
        "on": perf_on,
        "overhead_ratio": round(float(overhead_ratio), 6),
        "overhead_delta_ms": round(float(overhead_delta_ms), 6),
        "regression": bool(invariant_regression),
        "thresholds": {
            "overhead_ratio_max": float(args.invariant_overhead_ratio_max),
            "overhead_delta_ms_max": float(args.invariant_overhead_ms_max),
        },
    }
    report["physics_invariant_overhead"] = invariant_overhead_report

    # Strict regression collection.
    if perf_report.get("errors"):
        strict_errors.extend([f"perf_ci_smoke: {e}" for e in perf_report["errors"]])

    if invariant_overhead_report["regression"]:
        strict_errors.append(
            "physics_invariant_overhead regression: "
            f"ratio={invariant_overhead_report['overhead_ratio']}, "
            f"delta_ms={invariant_overhead_report['overhead_delta_ms']}"
        )

    report["strict_regressions"] = strict_errors

    _json_write(output_path, report)
    print(json.dumps(report, indent=2))
    print(f"Audit report written to: {output_path}")

    if args.strict and strict_errors:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
