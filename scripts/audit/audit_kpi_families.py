#!/usr/bin/env python3
"""Bounded independent DR settlement check plus thermal/equity quality evidence."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import pandas as pd
from citylearn.citylearn import CityLearnEnv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--policy", choices=["normal", "zero"], default="normal")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    schema = json.loads(args.schema.read_text())
    config = schema.get("demand_response") or {}
    root = Path(schema.get("root_directory") or ".")
    root = root if root.is_absolute() else args.schema.resolve().parent / root
    filename = root / config["requests_file"]
    requests = (
        pd.read_parquet(filename)
        if filename.suffix in {".parquet", ".pq"}
        else pd.read_csv(filename)
    )
    selected = requests[requests.request_id == args.request_id]
    if len(selected) != 1:
        parser.error("request-id must identify exactly one declared request")
    request = selected.iloc[0]
    seconds = float(schema.get("seconds_per_time_step") or 3600.0)
    dt = seconds / 3600.0
    required = max(
        1, math.ceil(float(config.get("baseline_window_seconds", 3600.0)) / seconds)
    )
    start = max(
        int(schema["simulation_start_time_step"]),
        int(request.start_time_step) - required,
    )
    end = int(request.end_time_step) + 1
    if end > int(schema["simulation_end_time_step"]):
        parser.error("The request lacks a terminal observation inside this dataset")
    report = dict(
        definition_version="kpi-families-audit-v1",
        schema=str(args.schema.resolve()),
        schema_sha256=hashlib.sha256(args.schema.read_bytes()).hexdigest(),
        requests_sha256=hashlib.sha256(filename.read_bytes()).hexdigest(),
        request_id=args.request_id,
        start=start,
        end=end,
        policy=args.policy,
        seed=args.seed,
        required_preparation_steps=required,
        preparation_seconds=required * seconds,
        physics_invariant_checks=True,
        independent_reference="DR energy and cash only; thermal/equity use separately tested audit populations",
    )
    env = None
    comparisons = 0
    max_error = 0.0

    def check(label, actual, expected):
        nonlocal comparisons, max_error
        comparisons += 1
        error = abs(float(actual) - float(expected))
        max_error = max(max_error, error)
        if not np.isfinite(error) or error > 1e-5 + 1e-7 * max(
            abs(actual), abs(expected)
        ):
            raise AssertionError(f"{label}: actual={actual}, expected={expected}")

    try:
        env = CityLearnEnv(
            str(args.schema.resolve()),
            simulation_start_time_step=start,
            simulation_end_time_step=end,
            episode_time_steps=end - start + 1,
            random_seed=args.seed,
            offline=True,
            physics_invariant_checks=True,
            export_kpis_on_episode_end=False,
            render_mode="none",
        )
        obs, _ = env.reset(seed=args.seed)
        if args.policy == "normal":
            from citylearn.agents.baseline import NormalPolicy

            agent = NormalPolicy(env)
        history, versions = {}, {}
        independent_rows = []
        while not (env.terminated or env.truncated):
            t = int(env.time_step)
            active = list(env.buildings)
            versions[t] = int(env.topology_version)
            if args.policy == "normal":
                action = agent.predict(obs, deterministic=True)
            else:
                action = {
                    "tables": {
                        name: np.zeros(space.shape, dtype="float32")
                        for name, space in env.action_space["tables"].items()
                    }
                }
            obs, *_ = env.step(action)
            history[t] = {
                b.name: float(b.net_electricity_consumption[t]) / dt for b in active
            }
            global_t = start + t
            candidates = requests[
                (requests.start_time_step <= global_t)
                & (requests.end_time_step >= global_t)
            ]
            if len(candidates) == 0:
                continue
            raw = candidates.iloc[0]
            local_start = int(raw.start_time_step) - start
            samples = range(local_start - required, local_start)
            complete = local_start >= required and all(i in history for i in samples)
            stable = (
                complete
                and len({versions[i] for i in range(local_start - required, t + 1)})
                == 1
            )
            finite = complete and all(
                np.isfinite(v) for i in samples for v in history[i].values()
            )
            valid = bool(complete and stable and finite and active)
            requested = float(raw.target_power_kw) * dt
            expected = dict(
                requested_kwh=requested,
                valid_requested_kwh=requested if valid else 0.0,
                delivered_kwh=0.0,
                credited_kwh=0.0,
                shortfall_kwh=0.0,
                revenue_eur=0.0,
                penalty_eur=0.0,
                net_revenue_eur=0.0,
            )
            if valid:
                reference = sum(sum(history[i].values()) for i in samples) / required
                actual = sum(history[t].values())
                delivered = (actual - reference) * (1 if raw.direction == "up" else -1)
                expected.update(
                    delivered_kwh=delivered * dt,
                    credited_kwh=min(max(delivered, 0.0), float(raw.target_power_kw))
                    * dt,
                    shortfall_kwh=max(
                        float(raw.target_power_kw)
                        - delivered
                        - float(raw.get("tolerance_power_kw", 0.0)),
                        0.0,
                    )
                    * dt,
                )
                expected["revenue_eur"] = expected["credited_kwh"] * float(
                    raw.activation_price_eur_per_kwh
                )
                expected["penalty_eur"] = expected["shortfall_kwh"] * float(
                    raw.shortfall_penalty_eur_per_kwh
                )
                expected["net_revenue_eur"] = (
                    expected["revenue_eur"] - expected["penalty_eur"]
                )
            observed = env._demand_response_service._settlement_by_time_step[t]
            if bool(observed["baseline_valid"]) != valid:
                raise AssertionError("Independent baseline validity differs")
            for key, value in expected.items():
                check("DR " + key, observed[key], value)
            allocations = observed["building_allocations"]
            for key in (
                "requested_kwh",
                "valid_requested_kwh",
                "delivered_kwh",
                "revenue_eur",
                "penalty_eur",
                "net_revenue_eur",
            ):
                check(
                    "Additive allocation " + key,
                    sum(r[key] for r in allocations),
                    observed[key],
                )
            independent_rows.append(
                dict(
                    global_time_step=global_t,
                    request_id=str(raw.request_id),
                    baseline_valid=valid,
                    **expected,
                )
            )
        frame = env.evaluate_v2(include_business_as_usual=False)
        metric = frame[frame.name == "District"].set_index("cost_function").value
        for key, suffix in [
            ("delivered_kwh", "delivered_total_kwh"),
            ("shortfall_kwh", "shortfall_total_kwh"),
            ("revenue_eur", "revenue_total_eur"),
            ("penalty_eur", "penalty_total_eur"),
            ("net_revenue_eur", "net_revenue_total_eur"),
        ]:
            check(
                "DR KPI " + suffix,
                metric["district_demand_response_" + suffix],
                sum(r[key] for r in independent_rows),
            )
        report.update(
            status="pass",
            completed_intervals=len(history),
            checks=comparisons,
            max_absolute_error=max_error,
            absolute_tolerance=1e-5,
            relative_tolerance=1e-7,
            independent_settlements=independent_rows,
            demand_response=env._demand_response_service.audit_summary(),
            family_audit=env.get_kpi_family_audit(),
            reward=env.get_metadata()["reward_evidence"],
        )
        report["evaluation_quality"] = (
            "complete_reference"
            if all(r["baseline_valid"] for r in independent_rows)
            else "incomplete_reference"
        )
    except Exception as error:
        report.update(status="fail", error_type=type(error).__name__, error=str(error))
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
                    "request_id",
                    "start",
                    "end",
                    "completed_intervals",
                    "checks",
                    "max_absolute_error",
                    "evaluation_quality",
                    "error",
                )
            }
        )
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
