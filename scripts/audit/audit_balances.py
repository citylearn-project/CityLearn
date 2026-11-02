#!/usr/bin/env python3
"""Bounded independent audit of physical energy, provenance, cash and KPIs."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.balance_audit import IndependentBalanceAudit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--start", type=int)
    parser.add_argument("--transitions", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--policy", choices=["zero", "normal", "seeded"], default="normal"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    schema = json.loads(args.schema.read_text())
    start = (
        args.start if args.start is not None else schema["simulation_start_time_step"]
    )
    if (
        args.transitions < 1
        or start < schema["simulation_start_time_step"]
        or start + args.transitions > schema["simulation_end_time_step"]
    ):
        parser.error(
            "The requested executed window must fit the dataset, including its terminal observation"
        )
    report = dict(
        schema=str(args.schema.resolve()),
        schema_sha256=hashlib.sha256(args.schema.read_bytes()).hexdigest(),
        start=start,
        end=start + args.transitions,
        seed=args.seed,
        policy=args.policy,
        physics_invariant_checks=True,
    )
    env = None
    try:
        env = CityLearnEnv(
            str(args.schema.resolve()),
            simulation_start_time_step=start,
            simulation_end_time_step=start + args.transitions,
            episode_time_steps=args.transitions + 1,
            rolling_episode_split=False,
            random_episode_split=False,
            random_seed=args.seed,
            offline=True,
            physics_invariant_checks=True,
            render_mode="none",
            export_kpis_on_episode_end=False,
        )
        obs, _ = env.reset(seed=args.seed)
        report["members_initial"] = len(env.buildings)
        if args.policy == "normal":
            from citylearn.agents.baseline import NormalPolicy

            agent = NormalPolicy(env)
        rng = np.random.default_rng(args.seed)
        with IndependentBalanceAudit(env) as auditor:
            while not (env.terminated or env.truncated):
                if args.policy == "normal":
                    actions = agent.predict(obs, deterministic=True)
                elif env.interface == "entity":
                    actions = {
                        "tables": {
                            key: (
                                rng.uniform(space.low, space.high).astype("float32")
                                if args.policy == "seeded"
                                else np.zeros(space.shape, dtype="float32")
                            )
                            for key, space in env.action_space["tables"].items()
                        }
                    }
                else:
                    actions = [
                        rng.uniform(space.low, space.high).astype("float32")
                        if args.policy == "seeded"
                        else np.zeros(space.shape, dtype="float32")
                        for space in env.action_space
                    ]
                obs, *_ = env.step(actions)
            report.update(auditor.finish())
        report["members_final"] = len(env.buildings)
    except Exception as error:
        report.update(
            status="fail",
            error_type=type(error).__name__,
            error=str(error),
            time_step=int(env.time_step) if env is not None else None,
        )
    finally:
        if env is not None:
            env.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                key: report.get(key)
                for key in (
                    "status",
                    "start",
                    "end",
                    "completed_intervals",
                    "checks",
                    "max_absolute_error",
                    "error",
                )
            }
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
