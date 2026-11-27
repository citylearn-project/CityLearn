#!/usr/bin/env python3
"""Performance smoke check for CI.

Cases:

- ``none``, ``end`` and ``entity_none``: the 2022 ``plus_evs`` dataset with a 60 s step on hourly data
  (``time_step_ratio_mode='compress'``), flat without and with end-of-episode rendering, and entity.
- ``pt_rec``: ``pt_rec_4`` under the entity interface at its native 900 s step, with
  ``time_step_ratio_mode='reject'`` and the physics invariant checks on.
- ``construction_15s``: construction time of the whole 15 s Parquet electrical-service dataset.

The hard gates are loose, because hosted runners are noisy and slower than the machine that recorded the
baseline. The ratios against the stored baseline are printed and, on GitHub Actions, written to the job
summary, so that a 1.2x change is visible on the pull request even when no gate fails.

Re-record the baseline once per release with ``--write-baseline`` (see docs/publishing.md). The thresholds
live in this script only; the baseline file stores measurements.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.citylearn import CityLearnEnv  # noqa: E402

SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
PT_REC_SCHEMA = ROOT / "data/datasets/pt_rec_4/schema.json"
CONSTRUCTION_SCHEMA = ROOT / "data/datasets/citylearn_three_phase_electrical_service_demo_15s_parquet/schema.json"
DEFAULT_BASELINE_FILE = ROOT / "scripts/ci/perf_baseline.json"

STEP_CASES = ("none", "end", "entity_none", "pt_rec")
CONSTRUCTION_CASES = ("construction_15s",)
ALL_CASES = STEP_CASES + CONSTRUCTION_CASES
STEP_METRICS = ("avg_step_ms", "p95_step_ms")
CONSTRUCTION_METRIC = "init_s"
# A row whose ratio is this much above (or below) the median ratio of all rows is marked in the summary.
VISIBLE_CHANGE_RATIO = 1.2
# Tail latencies are gated and shown, but too noisy on shared runners to be marked.
UNMARKED_METRICS = ("p95_step_ms",)


def _relative(path: Path) -> str:
    try:
        return str(Path(path).relative_to(ROOT))
    except ValueError:
        return str(path)


def run_case(
    render_mode: str,
    episode_steps: int,
    seconds_per_time_step: Optional[int],
    seed: int,
    interface: str = "flat",
    schema: Optional[Path] = None,
    time_step_ratio_mode: str = "compress",
    env_kwargs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Time construction, reset and a zero-action rollout of one episode.

    ``seconds_per_time_step=None`` keeps the dataset's own step. ``schema`` defaults to :data:`SCHEMA`.
    """

    schema = Path(schema) if schema is not None else SCHEMA
    render_dir = Path(tempfile.mkdtemp(prefix=f"citylearn_perf_{render_mode}_"))

    kwargs = {
        "central_agent": True,
        "episode_time_steps": episode_steps,
        "time_step_ratio_mode": time_step_ratio_mode,
        "random_seed": seed,
        "debug_timing": True,
        "interface": interface,
    }
    if seconds_per_time_step is not None:
        kwargs["seconds_per_time_step"] = seconds_per_time_step
    kwargs.update(env_kwargs or {})

    if render_mode != "none":
        kwargs.update(
            {
                "render_mode": render_mode,
                "render_directory": render_dir,
                "render_session_name": f"perf_{render_mode}",
            }
        )

    t0 = time.perf_counter()
    env = CityLearnEnv(str(schema), **kwargs)
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
    executed_seconds_per_time_step = int(env.seconds_per_time_step)
    physics_invariant_checks = bool(getattr(env, "physics_invariant_checks", False))
    env.close()

    avg_step_ms = float(np.mean(step_times) * 1000.0) if step_times else 0.0
    p95_step_ms = float(np.percentile(step_times, 95) * 1000.0) if step_times else 0.0
    raw_avg_step_ms = float(np.mean(raw_step_times) * 1000.0) if raw_step_times else 0.0
    raw_p95_step_ms = float(np.percentile(raw_step_times, 95) * 1000.0) if raw_step_times else 0.0

    return {
        "schema": _relative(schema),
        "render_mode": render_mode,
        "interface": interface,
        "time_step_ratio_mode": time_step_ratio_mode,
        "physics_invariant_checks": physics_invariant_checks,
        "configured_steps": episode_steps,
        "executed_steps": len(step_times),
        "seconds_per_time_step": executed_seconds_per_time_step,
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


def run_construction_case(schema: Path, seed: int) -> Dict[str, Any]:
    """Time the construction of the whole dataset, as a user loads it, without reset or rollout."""

    t0 = time.perf_counter()
    env = CityLearnEnv(str(schema), central_agent=True, random_seed=seed)
    t1 = time.perf_counter()
    time_steps = int(env.time_steps)
    seconds_per_time_step = int(env.seconds_per_time_step)
    env.close()

    return {
        "schema": _relative(schema),
        "seconds_per_time_step": seconds_per_time_step,
        "time_steps": time_steps,
        "init_s": round(t1 - t0, 4),
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode-steps", type=int, default=600)
    parser.add_argument("--seconds", type=int, default=60, help="Control step of the plus_evs cases.")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=ALL_CASES,
        default=list(ALL_CASES),
        help="Cases to run (default: all).",
    )

    parser.add_argument("--none-max-ms", type=float, default=30.0)
    parser.add_argument("--end-max-ms", type=float, default=45.0)
    parser.add_argument(
        "--entity-max-ms",
        type=float,
        default=50.0,
        help="Allowed entity interface avg/p95 step latency on plus_evs.",
    )
    parser.add_argument("--ratio-max", type=float, default=2.0)
    parser.add_argument(
        "--entity-overhead-ratio-max",
        type=float,
        default=3.75,
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
        "--require-baseline",
        action="store_true",
        help="Fail when the baseline file, or the baseline of a case that ran, is missing.",
    )
    parser.add_argument(
        "--baseline-regression-ratio",
        type=float,
        default=4.5,
        help="Allowed multiplier over baseline step metrics before failing.",
    )
    parser.add_argument(
        "--baseline-slack-ms",
        type=float,
        default=15.0,
        help="Absolute millisecond slack added on top of baseline*ratio for step metrics.",
    )
    parser.add_argument(
        "--construction-regression-ratio",
        type=float,
        default=3.0,
        help="Allowed multiplier over the baseline construction time before failing.",
    )
    parser.add_argument(
        "--construction-slack-s",
        type=float,
        default=5.0,
        help="Absolute second slack added on top of baseline*ratio for construction time.",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write the measured cases to the baseline file and exit successfully.",
    )
    parser.add_argument(
        "--metrics-output",
        type=Path,
        default=None,
        help="Optional output path for JSON report artifact.",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        default=Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None,
        help="Markdown file the ratio table is appended to (default: $GITHUB_STEP_SUMMARY when set).",
    )

    return parser.parse_args(argv)


def _thresholds(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "none_max_ms": args.none_max_ms,
        "end_max_ms": args.end_max_ms,
        "entity_max_ms": args.entity_max_ms if args.entity_max_ms is not None else args.none_max_ms,
        "ratio_max": args.ratio_max,
        "entity_overhead_ratio_max": args.entity_overhead_ratio_max,
        "baseline_regression_ratio": args.baseline_regression_ratio,
        "baseline_slack_ms": args.baseline_slack_ms,
        "construction_regression_ratio": getattr(args, "construction_regression_ratio", 3.0),
        "construction_slack_s": getattr(args, "construction_slack_s", 5.0),
    }


def _build_report(
    args: argparse.Namespace,
    none_case: Optional[Dict[str, Any]],
    end_case: Optional[Dict[str, Any]],
    entity_case: Optional[Dict[str, Any]],
    extra_cases: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cases = {"none": none_case, "end": end_case, "entity_none": entity_case}
    cases.update(extra_cases or {})

    return {
        "metadata": {
            "generated_utc": dt.datetime.now(dt.timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z",
            "episode_steps": args.episode_steps,
            "seconds_per_time_step": args.seconds,
            "seed": args.seed,
        },
        "cases": {name: case for name, case in cases.items() if case is not None},
        "thresholds": _thresholds(args),
    }


def _baseline_rows(
    report: Mapping[str, Any],
    baseline: Mapping[str, Any],
    regression_ratio: float,
    slack_ms: float,
    construction_ratio: float = 3.0,
    construction_slack_s: float = 5.0,
) -> List[Dict[str, Any]]:
    """One row per (case, metric) that ran: current value, baseline value, ratio and the allowed value."""

    rows: List[Dict[str, Any]] = []
    baseline_cases = baseline.get("cases", {}) if isinstance(baseline, Mapping) else {}

    for case_name, cur in report.get("cases", {}).items():
        base = baseline_cases.get(case_name)
        if case_name in CONSTRUCTION_CASES:
            metrics = [(CONSTRUCTION_METRIC, "s", construction_ratio, construction_slack_s)]
        else:
            metrics = [(metric, "ms", regression_ratio, slack_ms) for metric in STEP_METRICS]
            if case_name == "end":
                metrics += [
                    (metric, "s", regression_ratio, max(0.5, slack_ms / 10.0))
                    for metric in ("end_export_s", "terminal_export_s")
                ]

        for metric, unit, ratio_max, slack in metrics:
            if metric not in cur:
                continue
            current = float(cur[metric])
            row = {
                "case": case_name,
                "metric": metric,
                "unit": unit,
                "current": current,
                "baseline": None,
                "ratio": None,
                "allowed": None,
            }
            if isinstance(base, Mapping) and metric in base:
                base_value = float(base[metric])
                row["baseline"] = base_value
                row["ratio"] = current / base_value if base_value > 0 else None
                row["allowed"] = base_value * ratio_max + slack
            rows.append(row)

    return rows


def _compare_to_baseline(
    report: Dict[str, Any],
    baseline: Dict[str, Any],
    regression_ratio: float,
    slack_ms: float,
    construction_ratio: float = 3.0,
    construction_slack_s: float = 5.0,
) -> list[str]:
    errors: list[str] = []
    for row in _baseline_rows(report, baseline, regression_ratio, slack_ms, construction_ratio, construction_slack_s):
        if row["allowed"] is not None and row["current"] > row["allowed"]:
            errors.append(
                f"{row['case']} {row['metric']} regression: {row['current']:.4f} > {row['allowed']:.4f} "
                f"(baseline={row['baseline']:.4f})"
            )
    return errors


def _missing_baselines(report: Mapping[str, Any], baseline: Optional[Mapping[str, Any]]) -> List[str]:
    baseline_cases = (baseline or {}).get("cases", {})
    return [name for name in report.get("cases", {}) if name not in baseline_cases]


def _validate_absolute_thresholds(
    report: Dict[str, Any],
    none_max_ms: float,
    end_max_ms: float,
    entity_max_ms: float,
    ratio_max: float,
    entity_overhead_ratio_max: float,
) -> list[str]:
    errors: list[str] = []
    cases = report["cases"]
    none_case = cases.get("none")
    end_case = cases.get("end")
    entity_case = cases.get("entity_none")

    for name in STEP_CASES:
        if name in cases and cases[name]["executed_steps"] <= 0:
            errors.append(f"No steps executed in the {name} perf-smoke run.")

    if none_case is not None and none_case["avg_step_ms"] > none_max_ms:
        errors.append(
            f"none avg_step_ms too high: {none_case['avg_step_ms']} > {none_max_ms}"
        )

    if end_case is not None and end_case["avg_step_ms"] > end_max_ms:
        errors.append(
            f"end avg_step_ms too high: {end_case['avg_step_ms']} > {end_max_ms}"
        )

    if entity_case is not None and entity_case["avg_step_ms"] > entity_max_ms:
        errors.append(
            f"entity avg_step_ms too high: {entity_case['avg_step_ms']} > {entity_max_ms}"
        )

    if none_case is not None and end_case is not None and none_case["avg_step_ms"] > 0:
        ratio = end_case["avg_step_ms"] / none_case["avg_step_ms"]
        absolute_end_ok = end_case["avg_step_ms"] <= end_max_ms and end_case["p95_step_ms"] <= end_max_ms
        if ratio > ratio_max and not absolute_end_ok:
            errors.append(f"end/none ratio too high: {ratio:.3f} > {ratio_max}")

    if none_case is not None and entity_case is not None and none_case["avg_step_ms"] > 0:
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


def _summary_markdown(
    rows: List[Mapping[str, Any]],
    baseline: Optional[Mapping[str, Any]],
    baseline_path: Path,
    errors: List[str],
) -> str:
    ratios = [row["ratio"] for row in rows if row["ratio"] is not None]
    median = statistics.median(ratios) if ratios else None
    generated = ((baseline or {}).get("metadata") or {}).get("generated_utc", "unknown")

    lines = ["## Performance smoke check", ""]
    if errors:
        lines += ["**Failed:**", ""] + [f"- {error}" for error in errors] + [""]
    else:
        lines += ["All gates passed.", ""]

    lines += [
        f"Baseline: `{_relative(baseline_path)}`, recorded {generated}.",
        "",
        "| Case | Metric | Baseline | Current | Ratio | Ratio / median | Gate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        unit = row["unit"]
        baseline_text = "missing" if row["baseline"] is None else f"{row['baseline']:.4f} {unit}"
        ratio_text = "" if row["ratio"] is None else f"{row['ratio']:.2f}x"
        relative_text = ""
        if row["ratio"] is not None and median:
            relative = row["ratio"] / median
            relative_text = f"{relative:.2f}x"
            if row["metric"] in UNMARKED_METRICS:
                pass
            elif relative >= VISIBLE_CHANGE_RATIO:
                relative_text = f"**{relative_text} slower**"
            elif relative <= 1.0 / VISIBLE_CHANGE_RATIO:
                relative_text = f"**{relative_text} faster**"
        gate_text = "" if row["allowed"] is None else f"{row['allowed']:.4f} {unit}"
        lines.append(
            f"| {row['case']} | {row['metric']} | {baseline_text} | {row['current']:.4f} {unit} | "
            f"{ratio_text} | {relative_text} | {gate_text} |"
        )

    if median is not None:
        lines += [
            "",
            f"The median ratio is {median:.2f}x. It mostly measures how fast this runner is compared with the "
            "machine that recorded the baseline, so the column \"Ratio / median\" shows which case changed "
            f"relative to the others; values {VISIBLE_CHANGE_RATIO:.1f}x away from it are marked (p95 rows are "
            "not marked, because tail latency is noisy on shared runners). A change of every case at once shows "
            "only in the ratio itself.",
        ]

    return "\n".join(lines) + "\n"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _run_cases(args: argparse.Namespace) -> Dict[str, Dict[str, Any]]:
    selected = set(args.cases)
    cases: Dict[str, Dict[str, Any]] = {}
    if "none" in selected:
        cases["none"] = run_case("none", args.episode_steps, args.seconds, args.seed, interface="flat")
    if "end" in selected:
        cases["end"] = run_case("end", args.episode_steps, args.seconds, args.seed, interface="flat")
    if "entity_none" in selected:
        cases["entity_none"] = run_case("none", args.episode_steps, args.seconds, args.seed, interface="entity")
    if "pt_rec" in selected:
        cases["pt_rec"] = run_case(
            "none",
            args.episode_steps,
            None,
            args.seed,
            interface="entity",
            schema=PT_REC_SCHEMA,
            time_step_ratio_mode="reject",
            env_kwargs={"physics_invariant_checks": True},
        )
    if "construction_15s" in selected:
        cases["construction_15s"] = run_construction_case(CONSTRUCTION_SCHEMA, args.seed)
    return cases


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        cases = _run_cases(args)
    except Exception as error:
        # A case that cannot run must fail the job with its reason in the summary, not only in the log.
        if args.summary_file is not None:
            args.summary_file.parent.mkdir(parents=True, exist_ok=True)
            with open(args.summary_file, "a", encoding="utf-8") as handle:
                handle.write(f"## Performance smoke check\n\n**Failed:** a case raised `{type(error).__name__}: {error}`.\n")
        print(f"PERF_SMOKE_ERROR: a case raised {type(error).__name__}: {error}")
        raise
    report = _build_report(args, None, None, None, extra_cases=cases)

    if args.write_baseline:
        baseline = {"metadata": report["metadata"], "cases": report["cases"]}
        if args.baseline_file.is_file():
            # A partial run (--cases) replaces only the cases it measured.
            previous = json.loads(args.baseline_file.read_text(encoding="utf-8"))
            merged = dict(previous.get("cases", {}))
            merged.update(report["cases"])
            baseline["cases"] = {name: merged[name] for name in ALL_CASES if name in merged}
        _write_json(args.baseline_file, baseline)
        print(f"Wrote baseline to {args.baseline_file}")
        if args.metrics_output is not None:
            _write_json(args.metrics_output, report)
        return 0

    thresholds = report["thresholds"]
    errors = _validate_absolute_thresholds(
        report,
        none_max_ms=thresholds["none_max_ms"],
        end_max_ms=thresholds["end_max_ms"],
        entity_max_ms=thresholds["entity_max_ms"],
        ratio_max=thresholds["ratio_max"],
        entity_overhead_ratio_max=thresholds["entity_overhead_ratio_max"],
    )

    baseline_data = None
    if args.baseline_file.is_file():
        baseline_data = json.loads(args.baseline_file.read_text(encoding="utf-8"))
        errors.extend(
            _compare_to_baseline(
                report,
                baseline_data,
                regression_ratio=thresholds["baseline_regression_ratio"],
                slack_ms=thresholds["baseline_slack_ms"],
                construction_ratio=thresholds["construction_regression_ratio"],
                construction_slack_s=thresholds["construction_slack_s"],
            )
        )
    if args.require_baseline:
        if baseline_data is None:
            errors.append(f"Baseline file {args.baseline_file} not found; record it with --write-baseline.")
        else:
            for name in _missing_baselines(report, baseline_data):
                errors.append(f"No baseline for case {name!r} in {args.baseline_file}; re-record it with --write-baseline.")

    report["baseline"] = {
        "path": str(args.baseline_file),
        "loaded": baseline_data is not None,
    }
    rows = _baseline_rows(
        report,
        baseline_data or {},
        thresholds["baseline_regression_ratio"],
        thresholds["baseline_slack_ms"],
        thresholds["construction_regression_ratio"],
        thresholds["construction_slack_s"],
    )
    report["comparison"] = rows

    print(json.dumps(report, indent=2))
    summary = _summary_markdown(rows, baseline_data, args.baseline_file, errors)
    print(summary)
    if args.summary_file is not None:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        with open(args.summary_file, "a", encoding="utf-8") as handle:
            handle.write(summary)

    if args.metrics_output is not None:
        _write_json(args.metrics_output, report)

    if errors:
        for error in errors:
            print(f"PERF_SMOKE_ERROR: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
