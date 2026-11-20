#!/usr/bin/env python3
"""Profile expensive CityLearn lifecycle phases around rollout, KPI and BAU work."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController as RBCAgent  # noqa: E402
from citylearn.citylearn import CityLearnEnv  # noqa: E402

DEFAULT_SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
DEFAULT_OUTPUT = ROOT / "outputs/audit/lifecycle_profile.json"


def _timed(label: str, fn: Callable[[], Any]) -> Tuple[str, float, int | None]:
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    rows = len(result) if hasattr(result, "__len__") else None
    return label, elapsed, rows


def _new_env(args: argparse.Namespace, *, render_directory: Path | None = None) -> Tuple[CityLearnEnv, float]:
    env_kwargs = {
        "central_agent": True,
        "episode_time_steps": args.episode_steps,
        "seconds_per_time_step": args.seconds,
        # --seconds may differ from the dataset step: keep the compressed time of CityLearn 3.6.0.
        "time_step_ratio_mode": "compress",
        "random_seed": args.seed,
        "render_mode": "none",
        "debug_timing": False,
        "physics_invariant_checks": args.physics_invariant_checks,
    }
    if render_directory is not None:
        env_kwargs["render_directory"] = render_directory

    start = time.perf_counter()
    env = CityLearnEnv(str(args.schema), **env_kwargs)
    return env, time.perf_counter() - start


def _rollout(args: argparse.Namespace, *, render_directory: Path | None = None):
    env, init_s = _new_env(args, render_directory=render_directory)
    agent_start = time.perf_counter()
    agent = RBCAgent(env)
    agent_init_s = time.perf_counter() - agent_start

    reset_start = time.perf_counter()
    observations, _ = env.reset()
    reset_s = time.perf_counter() - reset_start

    predict_s = 0.0
    step_s = 0.0
    executed_steps = 0

    while not env.terminated:
        predict_start = time.perf_counter()
        actions = agent.predict(observations, deterministic=True)
        predict_s += time.perf_counter() - predict_start

        step_start = time.perf_counter()
        observations, _, terminated, truncated, _ = env.step(actions)
        step_s += time.perf_counter() - step_start
        executed_steps += 1

        if terminated or truncated:
            break

    timings = {
        "env_init_s": init_s,
        "agent_init_s": agent_init_s,
        "env_reset_s": reset_s,
        "agent_predict_total_s": predict_s,
        "env_step_total_s": step_s,
        "env_step_avg_ms": (step_s / executed_steps * 1000.0) if executed_steps else 0.0,
        "executed_steps": executed_steps,
    }
    return env, timings


def run_profile(args: argparse.Namespace) -> Dict[str, Any]:
    env, rollout_timings = _rollout(args)
    try:
        timings: List[Dict[str, Any]] = [
            {"phase": key, "seconds": value, "rows": None}
            for key, value in rollout_timings.items()
            if key != "executed_steps"
        ]

        for label, elapsed, rows in [
            _timed("evaluate_legacy", lambda: env.evaluate()),
            _timed("evaluate_v2_no_bau", lambda: env.evaluate_v2(include_business_as_usual=False)),
        ]:
            timings.append({"phase": label, "seconds": elapsed, "rows": rows})

        env._business_as_usual_baseline_service.clear()
        label, elapsed, rows = _timed(
            "evaluate_v2_with_bau_cold",
            lambda: env.evaluate_v2(include_business_as_usual=True),
        )
        timings.append({"phase": label, "seconds": elapsed, "rows": rows})

        label, elapsed, rows = _timed(
            "evaluate_v2_with_bau_cached",
            lambda: env.evaluate_v2(include_business_as_usual=True),
        )
        timings.append({"phase": label, "seconds": elapsed, "rows": rows})

        env._business_as_usual_baseline_service.clear()
        label, elapsed, rows = _timed(
            "run_bau_baseline_force",
            lambda: env.run_business_as_usual_baseline(force=True).kpis_v2,
        )
        timings.append({"phase": label, "seconds": elapsed, "rows": rows})
    finally:
        env.close()

    if not args.skip_exports:
        for include_bau, export_bau_timeseries in [
            (False, False),
            (True, False),
            (True, True),
        ]:
            render_directory = Path(tempfile.mkdtemp(prefix="citylearn_lifecycle_export_"))
            env, _rollout_timings = _rollout(args, render_directory=render_directory)
            try:
                label = (
                    f"export_final_kpis_include_bau_{include_bau}"
                    f"_timeseries_{export_bau_timeseries}"
                )
                start = time.perf_counter()
                env.export_final_kpis(
                    filepath=f"{label}.csv",
                    include_business_as_usual=include_bau,
                    export_business_as_usual_timeseries=export_bau_timeseries,
                )
                timings.append(
                    {
                        "phase": label,
                        "seconds": time.perf_counter() - start,
                        "rows": None,
                        "output_dir": str(render_directory),
                    }
                )
            finally:
                env.close()

    return {
        "metadata": {
            "schema": str(args.schema),
            "episode_steps": int(args.episode_steps),
            "executed_steps": int(rollout_timings["executed_steps"]),
            "seconds_per_time_step": int(args.seconds),
            "seed": int(args.seed),
            "physics_invariant_checks": bool(args.physics_invariant_checks),
        },
        "timings": [
            {
                **item,
                "seconds": round(float(item["seconds"]), 6),
            }
            for item in timings
        ],
    }


def _print_report(report: Dict[str, Any]) -> None:
    metadata = report["metadata"]
    print(
        "schema={schema} steps={executed_steps}/{episode_steps} "
        "seconds={seconds_per_time_step} seed={seed}".format(**metadata)
    )
    print()
    print(f"{'phase':55s} {'seconds':>10s} {'rows':>8s}")
    for item in report["timings"]:
        rows = "" if item.get("rows") is None else str(item["rows"])
        print(f"{item['phase']:55s} {float(item['seconds']):10.4f} {rows:>8s}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--episode-steps", type=int, default=600)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--physics-invariant-checks", action="store_true")
    parser.add_argument("--skip-exports", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_profile(args)
    _print_report(report)

    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print()
        print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
