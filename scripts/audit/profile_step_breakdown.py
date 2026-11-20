#!/usr/bin/env python3
"""Profile CityLearn step-time breakdown from debug_timing info fields."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.citylearn import CityLearnEnv  # noqa: E402

DEFAULT_SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
DEFAULT_OUTPUT = ROOT / "outputs/audit/step_breakdown.json"

PRIMARY_COMPONENTS = [
    "parse_actions_time",
    "apply_actions_time",
    "update_variables_time",
    "physics_invariants_time",
    "reward_observations_time",
    "reward_calculation_time",
    "next_time_step_time",
    "topology_time",
    "periodic_metrics_time",
    "terminal_reward_summary_time",
    "terminal_export_time",
    "next_observations_time",
    "get_info_time",
]


def _numeric(value: Any) -> float | None:
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return None

    if not np.isfinite(scalar):
        return None

    return scalar


def _summarize(samples: Iterable[float], step_wall_total: float) -> Dict[str, float]:
    values = np.array(list(samples), dtype="float64")
    if values.size == 0:
        return {
            "count": 0,
            "total_s": 0.0,
            "avg_ms": 0.0,
            "p95_ms": 0.0,
            "max_ms": 0.0,
            "share_of_step_wall": 0.0,
        }

    total_s = float(values.sum())
    return {
        "count": int(values.size),
        "total_s": round(total_s, 6),
        "avg_ms": round(float(values.mean() * 1000.0), 4),
        "p95_ms": round(float(np.percentile(values, 95) * 1000.0), 4),
        "max_ms": round(float(values.max() * 1000.0), 4),
        "share_of_step_wall": round(total_s / step_wall_total, 4) if step_wall_total > 0.0 else 0.0,
    }


def _zero_action(env: CityLearnEnv, interface: str):
    if interface == "entity":
        action = {"tables": {}}
        for table_name, table_space in env.action_space["tables"].items():
            action["tables"][table_name] = np.zeros(table_space.shape, dtype="float32")
        return action

    return [np.zeros(env.action_space[0].shape[0], dtype="float32")]


def _rbc_agent(env: CityLearnEnv):
    from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController

    return BasicElectricVehicleRBC_ReferenceController(env)


def run_profile(args: argparse.Namespace) -> Dict[str, Any]:
    env_kwargs = {
        "central_agent": True,
        "episode_time_steps": args.episode_steps,
        "seconds_per_time_step": args.seconds,
        # --seconds may differ from the dataset step: keep the compressed time of CityLearn 3.6.0.
        "time_step_ratio_mode": "compress",
        "random_seed": args.seed,
        "render_mode": args.render_mode,
        "interface": args.interface,
        "topology_mode": args.topology_mode,
        "debug_timing": True,
        "physics_invariant_checks": args.physics_invariant_checks,
    }

    if args.render_directory is not None:
        env_kwargs["render_directory"] = args.render_directory

    init_start = time.perf_counter()
    env = CityLearnEnv(str(args.schema), **env_kwargs)
    init_s = time.perf_counter() - init_start

    try:
        agent = _rbc_agent(env) if args.agent == "rbc" else None

        reset_start = time.perf_counter()
        observations, _ = env.reset()
        reset_s = time.perf_counter() - reset_start

        action = _zero_action(env, args.interface)
        component_samples: Dict[str, List[float]] = {}
        step_wall_times: List[float] = []
        predict_times: List[float] = []

        while not env.terminated:
            predict_start = time.perf_counter()
            if agent is None:
                selected_action = action
            else:
                selected_action = agent.predict(observations, deterministic=True)
            predict_times.append(time.perf_counter() - predict_start)

            step_start = time.perf_counter()
            observations, _, terminated, truncated, info = env.step(selected_action)
            step_wall_times.append(time.perf_counter() - step_start)

            for key, value in info.items():
                scalar = _numeric(value)
                if scalar is not None and key.endswith("_time"):
                    component_samples.setdefault(key, []).append(scalar)

            if terminated or truncated:
                break

        step_wall_total = float(np.sum(step_wall_times))
        summary = {
            "step_wall_time": _summarize(step_wall_times, step_wall_total),
            "agent_predict_time": _summarize(predict_times, step_wall_total),
        }

        for key in sorted(component_samples):
            summary[key] = _summarize(component_samples[key], step_wall_total)

        primary_total = sum(summary.get(key, {}).get("total_s", 0.0) for key in PRIMARY_COMPONENTS)
        measured_total = float(summary["step_wall_time"]["total_s"])
        summary["primary_timing_gap"] = {
            "total_s": round(max(0.0, measured_total - primary_total), 6),
            "share_of_step_wall": round(max(0.0, measured_total - primary_total) / measured_total, 4)
            if measured_total > 0.0
            else 0.0,
        }

        return {
            "metadata": {
                "schema": str(args.schema),
                "agent": args.agent,
                "interface": args.interface,
                "topology_mode": args.topology_mode,
                "render_mode": args.render_mode,
                "episode_steps": int(args.episode_steps),
                "executed_steps": int(len(step_wall_times)),
                "seconds_per_time_step": int(args.seconds),
                "seed": int(args.seed),
                "init_s": round(float(init_s), 6),
                "reset_s": round(float(reset_s), 6),
            },
            "summary": summary,
        }
    finally:
        env.close()


def _print_table(report: Mapping[str, Any], limit: int) -> None:
    metadata = report["metadata"]
    summary = report["summary"]
    print(
        "schema={schema} agent={agent} interface={interface} render={render_mode} "
        "steps={executed_steps}/{episode_steps} seconds={seconds_per_time_step}".format(**metadata)
    )
    print(f"init_s={metadata['init_s']:.4f} reset_s={metadata['reset_s']:.4f}")
    print()
    print(f"{'component':45s} {'avg_ms':>10s} {'p95_ms':>10s} {'total_s':>10s} {'share':>8s}")

    rows = [
        (name, values)
        for name, values in summary.items()
        if isinstance(values, dict) and "total_s" in values
    ]
    rows.sort(key=lambda item: float(item[1]["total_s"]), reverse=True)

    for name, values in rows[:limit]:
        print(
            f"{name:45s} "
            f"{float(values.get('avg_ms', 0.0)):10.4f} "
            f"{float(values.get('p95_ms', 0.0)):10.4f} "
            f"{float(values.get('total_s', 0.0)):10.4f} "
            f"{float(values.get('share_of_step_wall', 0.0)):8.2%}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--episode-steps", type=int, default=600)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--agent", choices=["zero", "rbc"], default="rbc")
    parser.add_argument("--interface", choices=["flat", "entity"], default="flat")
    parser.add_argument("--topology-mode", choices=["static", "dynamic"], default="static")
    parser.add_argument("--render-mode", choices=["none", "during", "end"], default="none")
    parser.add_argument("--physics-invariant-checks", action="store_true")
    parser.add_argument("--render-directory", type=Path, default=None)
    parser.add_argument("--table-limit", type=int, default=30)
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_profile(args)
    _print_table(report, args.table_limit)

    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print()
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
