#!/usr/bin/env python3
"""Lightweight performance smoke test for CI.

This catches major rollout-loop regressions and optionally compares against a
versioned baseline checked into the repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.citylearn import CityLearnEnv  # noqa: E402

SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
DEFAULT_BASELINE_FILE = ROOT / "scripts/ci/perf_baseline.json"


def run_case(render_mode: str, episode_steps: int, seconds_per_time_step: int, seed: int, interface: str = "flat") -> Dict[str, Any]:
    render_dir = Path(tempfile.mkdtemp(prefix=f"citylearn_perf_{render_mode}_"))

    kwargs = {
        "central_agent": True,
        "episode_time_steps": episode_steps,
        "seconds_per_time_step": seconds_per_time_step,
        # The timing step may differ from the dataset step: keep the compressed time of CityLearn 3.6.0.
        "time_step_ratio_mode": "compress",
        "random_seed": seed,
        "debug_timing": True,
        "interface": interface,
    }

    if render_mode != "none":
        kwargs.update(
            {
                "render_mode": render_mode,
                "render_directory": render_dir,
                "render_session_name": f"perf_{render_mode}",
            }
        )

    t0 = time.perf_counter()
    env = CityLearnEnv(str(SCHEMA), **kwargs)
    t1 = time.perf_counter()

    observations, _ = env.reset()
    t2 = time.perf_counter()

    if interface == "entity":
        action = {"tables": {}}
        for table_name, table_space in env.action_space["tables"].items():
            action["tables"][table_name] = np.zeros(table_space.shape, dtype="float32")
    else:
        action = np.zeros(env.action_space[0].shape[0], dtype="float32")

    step_times = []
    raw_step_times = []
    end_export_s = 0.0
    final_kpi_export_s = 0.0
    terminal_export_s = 0.0

    while not env.terminated:
        s0 = time.perf_counter()
        if interface == "entity":
            observations, _, terminated, truncated, info = env.step(action)
        else:
            observations, _, terminated, truncated, info = env.step([action])
        s1 = time.perf_counter()
        raw_step_time = s1 - s0
        raw_step_times.append(raw_step_time)

        step_end_export_s = float(info.get("end_export_time", 0.0))
        step_final_kpi_export_s = float(info.get("final_kpi_export_time", 0.0))
        step_terminal_export_s = float(
            info.get("terminal_export_time", step_end_export_s + step_final_kpi_export_s)
        )

        # Keep step latency focused on recurring control-loop work. The final
        # step may run render/KPI/BAU exports, which are reported separately.
        step_times.append(max(0.0, raw_step_time - step_terminal_export_s))
        end_export_s += step_end_export_s
        final_kpi_export_s += step_final_kpi_export_s
        terminal_export_s += step_terminal_export_s

        if terminated or truncated:
            break

    t3 = time.perf_counter()
    env.close()

    avg_step_ms = float(np.mean(step_times) * 1000.0) if step_times else 0.0
    p95_step_ms = float(np.percentile(step_times, 95) * 1000.0) if step_times else 0.0
    raw_avg_step_ms = float(np.mean(raw_step_times) * 1000.0) if raw_step_times else 0.0
    raw_p95_step_ms = float(np.percentile(raw_step_times, 95) * 1000.0) if raw_step_times else 0.0

    return {
        "render_mode": render_mode,
        "interface": interface,
        "configured_steps": episode_steps,
        "executed_steps": len(step_times),
        "seconds_per_time_step": seconds_per_time_step,
        "init_s": round(t1 - t0, 4),
        "reset_s": round(t2 - t1, 4),
        "rollout_s": round(t3 - t2, 4),
        "avg_step_ms": round(avg_step_ms, 4),
        "p95_step_ms": round(p95_step_ms, 4),
        "raw_avg_step_ms": round(raw_avg_step_ms, 4),
        "raw_p95_step_ms": round(raw_p95_step_ms, 4),
        "end_export_s": round(end_export_s, 4),
        "final_kpi_export_s": round(final_kpi_export_s, 4),
        "terminal_export_s": round(terminal_export_s, 4),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-steps", type=int, default=600)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)

    parser.add_argument("--none-max-ms", type=float, default=30.0)
    parser.add_argument("--end-max-ms", type=float, default=45.0)
    parser.add_argument(
        "--entity-max-ms",
        type=float,
        default=None,
        help="Allowed entity interface avg/p95 step latency. Defaults to --none-max-ms.",
    )
    parser.add_argument("--ratio-max", type=float, default=2.0)
    parser.add_argument(
        "--entity-overhead-ratio-max",
        type=float,
        default=1.12,
        help=(
            "Allowed entity(flat-none baseline) avg_step_ms ratio upper bound. "
            "The ratio only fails when the entity absolute latency also exceeds --entity-max-ms."
        ),
    )

    parser.add_argument(
        "--baseline-file",
        type=Path,
        default=DEFAULT_BASELINE_FILE,
        help="Path to versioned baseline JSON.",
    )
    parser.add_argument(
        "--baseline-regression-ratio",
        type=float,
        default=2.5,
        help="Allowed multiplier over baseline metrics before failing.",
    )
    parser.add_argument(
        "--baseline-slack-ms",
        type=float,
        default=5.0,
        help="Absolute millisecond slack added on top of baseline*ratio.",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write a new baseline file with current measurements and exit successfully.",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=None,
        help="Optional output path for JSON report artifact.",
    )

    return parser.parse_args()


def _build_report(args: argparse.Namespace, none_case: Dict[str, Any], end_case: Dict[str, Any], entity_case: Dict[str, Any]) -> Dict[str, Any]:
    try:
        schema_path = str(SCHEMA.relative_to(ROOT))
    except ValueError:
        schema_path = str(SCHEMA)

    return {
        "metadata": {
            "generated_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "schema": schema_path,
            "episode_steps": args.episode_steps,
            "seconds_per_time_step": args.seconds,
            "seed": args.seed,
        },
        "cases": {
            "none": none_case,
            "end": end_case,
            "entity_none": entity_case,
        },
        "thresholds": {
            "none_max_ms": args.none_max_ms,
            "end_max_ms": args.end_max_ms,
            "entity_max_ms": args.entity_max_ms if args.entity_max_ms is not None else args.none_max_ms,
            "ratio_max": args.ratio_max,
            "entity_overhead_ratio_max": args.entity_overhead_ratio_max,
            "baseline_regression_ratio": args.baseline_regression_ratio,
            "baseline_slack_ms": args.baseline_slack_ms,
        },
    }


def _compare_to_baseline(report: Dict[str, Any], baseline: Dict[str, Any], regression_ratio: float, slack_ms: float) -> list[str]:
    errors: list[str] = []
    baseline_cases = baseline.get("cases", {})
    current_cases = report.get("cases", {})

    for case_name in ("none", "end", "entity_none"):
        if case_name not in baseline_cases or case_name not in current_cases:
            continue

        base = baseline_cases[case_name]
        cur = current_cases[case_name]

        for metric in ("avg_step_ms", "p95_step_ms"):
            base_value = float(base.get(metric, 0.0))
            cur_value = float(cur.get(metric, 0.0))
            allowed = (base_value * regression_ratio) + slack_ms

            if cur_value > allowed:
                errors.append(
                    f"{case_name} {metric} regression: {cur_value:.4f} > {allowed:.4f} "
                    f"(baseline={base_value:.4f}, ratio={regression_ratio}, slack_ms={slack_ms})"
                )

        if case_name == "end":
            for metric in ("end_export_s", "terminal_export_s"):
                if metric not in base or metric not in cur:
                    continue

                base_export = float(base.get(metric, 0.0))
                cur_export = float(cur.get(metric, 0.0))
                allowed_export = (base_export * regression_ratio) + max(0.5, slack_ms / 10.0)
                if cur_export > allowed_export:
                    errors.append(
                        f"end {metric} regression: {cur_export:.4f} > {allowed_export:.4f} "
                        f"(baseline={base_export:.4f})"
                    )

    return errors


def _validate_absolute_thresholds(
    report: Dict[str, Any],
    none_max_ms: float,
    end_max_ms: float,
    entity_max_ms: float,
    ratio_max: float,
    entity_overhead_ratio_max: float,
) -> list[str]:
    errors: list[str] = []
    none_case = report["cases"]["none"]
    end_case = report["cases"]["end"]
    entity_case = report["cases"]["entity_none"]

    if none_case["executed_steps"] <= 0 or end_case["executed_steps"] <= 0:
        errors.append("No steps executed in one or more perf-smoke runs.")

    if none_case["avg_step_ms"] > none_max_ms:
        errors.append(
            f"none avg_step_ms too high: {none_case['avg_step_ms']} > {none_max_ms}"
        )

    if end_case["avg_step_ms"] > end_max_ms:
        errors.append(
            f"end avg_step_ms too high: {end_case['avg_step_ms']} > {end_max_ms}"
        )

    if entity_case["avg_step_ms"] > entity_max_ms:
        errors.append(
            f"entity avg_step_ms too high: {entity_case['avg_step_ms']} > {entity_max_ms}"
        )

    if none_case["avg_step_ms"] > 0:
        ratio = end_case["avg_step_ms"] / none_case["avg_step_ms"]
        absolute_end_ok = end_case["avg_step_ms"] <= end_max_ms and end_case["p95_step_ms"] <= end_max_ms
        if ratio > ratio_max and not absolute_end_ok:
            errors.append(f"end/none ratio too high: {ratio:.3f} > {ratio_max}")

    if none_case["avg_step_ms"] > 0:
        entity_ratio = entity_case["avg_step_ms"] / none_case["avg_step_ms"]
        absolute_entity_ok = (
            entity_case["avg_step_ms"] <= entity_max_ms
            and entity_case["p95_step_ms"] <= entity_max_ms
        )
        if entity_ratio > entity_overhead_ratio_max and not absolute_entity_ok:
            errors.append(
                f"entity/flat ratio too high: {entity_ratio:.3f} > {entity_overhead_ratio_max}"
            )

    return errors


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    none_case = run_case("none", args.episode_steps, args.seconds, args.seed, interface="flat")
    end_case = run_case("end", args.episode_steps, args.seconds, args.seed, interface="flat")
    entity_case = run_case("none", args.episode_steps, args.seconds, args.seed, interface="entity")
    report = _build_report(args, none_case, end_case, entity_case)

    if args.write_baseline:
        _write_json(args.baseline_file, report)
        print(f"Wrote baseline to {args.baseline_file}")
        if args.metrics_output is not None:
            _write_json(args.metrics_output, report)
        return 0

    errors = _validate_absolute_thresholds(
        report,
        none_max_ms=args.none_max_ms,
        end_max_ms=args.end_max_ms,
        entity_max_ms=args.entity_max_ms if args.entity_max_ms is not None else args.none_max_ms,
        ratio_max=args.ratio_max,
        entity_overhead_ratio_max=args.entity_overhead_ratio_max,
    )

    baseline_loaded = False
    if args.baseline_file.is_file():
        baseline_loaded = True
        baseline_data = json.loads(args.baseline_file.read_text(encoding="utf-8"))
        errors.extend(
            _compare_to_baseline(
                report,
                baseline_data,
                regression_ratio=args.baseline_regression_ratio,
                slack_ms=args.baseline_slack_ms,
            )
        )

    report["baseline"] = {
        "path": str(args.baseline_file),
        "loaded": baseline_loaded,
    }

    print(json.dumps(report, indent=2))

    if args.metrics_output is not None:
        _write_json(args.metrics_output, report)

    if errors:
        for error in errors:
            print(f"PERF_SMOKE_ERROR: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
