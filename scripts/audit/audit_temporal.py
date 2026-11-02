#!/usr/bin/env python3
"""Audit canonical input clocks and bounded seeded replay without editing datasets."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
import pandas as pd
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.temporal import TimeAxis, sha256


_FILE_CACHE = {}


def static_audit(path):
    schema = json.loads(path.read_text())
    root = Path(schema.get("root_directory") or ".")
    root = root if root.is_absolute() else path.resolve().parent / root
    schema["root_directory"] = str(root)
    axis = TimeAxis(schema)
    if axis.utc is None:
        raise ValueError("Canonical calendar required for full input-clock audit")
    local = axis.utc.tz_convert(axis.timezone or "UTC")
    n = len(local)
    files = {}
    expected_labels = [
        ("month", local.month),
        ("minutes", local.minute),
        (
            "daylight_savings_status",
            np.array([int(x.dst().total_seconds() != 0) for x in local]),
        ),
    ]
    clock_hash = sha256(root / axis.filename)
    for member, b in schema["buildings"].items():
        for field in ("energy_simulation", "weather", "pricing", "carbon_intensity"):
            if not isinstance(b.get(field), str):
                continue
            source = root / b[field]
            if str(source.relative_to(root)) in files:
                continue
            cache_key = (str(source.resolve()), source.stat().st_mtime_ns, clock_hash)
            if cache_key in _FILE_CACHE:
                files[str(source.relative_to(root))] = _FILE_CACHE[cache_key]
                continue
            if source.suffix in {".parquet", ".pq"}:
                import pyarrow.parquet as pq

                p = pq.ParquetFile(source)
                rows = p.metadata.num_rows
                columns = p.schema.names
            else:
                f = pd.read_csv(source)
                rows = len(f)
                columns = list(f)
            if rows != n:
                raise AssertionError(f"Clock coverage {source}: {rows} != {n}")
            check_columns = [
                c
                for c in ("month", "hour", "minutes", "daylight_savings_status")
                if c in columns
            ]
            if check_columns:
                f = (
                    pd.read_parquet(source, columns=check_columns)
                    if source.suffix in {".parquet", ".pq"}
                    else pd.read_csv(source, usecols=check_columns)
                )
                for column, expected in expected_labels:
                    if column in f and not np.array_equal(f[column], expected):
                        raise AssertionError(
                            f"Local calendar mismatch: {source}:{column}"
                        )
                if "hour" in f and not (
                    np.array_equal(f.hour, local.hour)
                    or np.array_equal(f.hour, local.hour + 1)
                ):
                    raise AssertionError("Local hour mismatch: " + str(source))
            files[str(source.relative_to(root))] = dict(
                rows=rows, clock_columns=check_columns, sha256=sha256(source)
            )
            _FILE_CACHE[cache_key] = files[str(source.relative_to(root))]
    events = 0
    for event in schema.get("topology_events") or []:
        t = int(event["time_step"])
        if t < 0 or t > n:
            raise AssertionError("Invalid structural event boundary")
        if t < n and event.get("timestamp_local"):
            if pd.Timestamp(event["timestamp_local"]) != axis.utc[t]:
                raise AssertionError("Event timestamp and index disagree")
        events += 1
    sessions = {}
    catalog = root / "catalogs/charging_sessions.parquet"
    if catalog.is_file():
        frame = pd.read_parquet(catalog)
        a = pd.to_numeric(frame.arrival_time_step, errors="coerce")
        d = pd.to_numeric(frame.departure_time_step, errors="coerce")
        if ((a < 0) | (a >= n) | ((d < a) & d.notna())).any():
            raise AssertionError("Invalid EV catalogue boundary")
        sessions = dict(
            count=len(frame),
            open_at_terminal=int((d.isna() | (d >= n)).sum()),
            catalog_sha256=sha256(catalog),
        )
    days = pd.Series(local.strftime("%Y-%m-%d")).value_counts()
    selected = {
        d: int(days.get(d, 0))
        for d in ("2023-03-26", "2023-10-29", "2024-02-29", "2024-03-31", "2024-10-27")
    }
    return dict(
        schema=str(path.resolve()),
        schema_sha256=sha256(path),
        status="pass",
        calendar_sha256=sha256(root / axis.filename),
        rows=n,
        seconds_per_source_step=axis.seconds,
        timezone=axis.timezone,
        local_day_counts=selected,
        source_files=files,
        structural_events=events,
        ev_catalogue=sessions,
        boundary="source samples; final observation is not automatically dispatched",
    )


def state(env):
    return dict(
        step=int(env.time_step),
        members=[b.name for b in env.buildings],
        net=[float(v) for v in env.net_electricity_consumption],
        cost=[float(v) for v in env.net_electricity_consumption_cost],
        bess=[
            (
                b.name,
                float(b.electrical_storage.energy_init),
                float(b.electrical_storage.capacity),
            )
            for b in env.buildings
        ],
        ev=[
            (e.name, float(e.battery.energy_init), float(e.battery.capacity))
            for e in getattr(env, "_all_electric_vehicles", env.electric_vehicles)
        ],
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, default=lambda x: x.tolist(), allow_nan=False
        ).encode()
    ).hexdigest()


def replay(path, start, transitions, seed):
    environments = []
    traces = []
    metadata = []

    def make():
        e = CityLearnEnv(
            str(path.resolve()),
            simulation_start_time_step=start,
            simulation_end_time_step=start + transitions,
            episode_time_steps=transitions + 1,
            random_seed=seed,
            offline=True,
            physics_invariant_checks=True,
            render_mode="none",
            export_kpis_on_episode_end=False,
        )
        environments.append(e)
        return e

    try:
        env = make()
        for fresh, queries in [(False, False), (False, True), (True, True)]:
            if fresh:
                env = make()
            from citylearn.agents.baseline import NormalPolicy

            obs, _ = env.reset(seed=seed)
            agent = NormalPolicy(env)
            trace = []
            while not env.terminated:
                actions = agent.predict(obs, deterministic=True)
                obs, *_ = env.step(actions)
                if queries and env.time_step == min(2, transitions):
                    before = digest(state(env))
                    env.evaluate_v2(include_business_as_usual=False)
                    env.get_kpi_family_audit()
                    if digest(state(env)) != before:
                        raise AssertionError("KPI query changed physical state")
                trace.append(dict(actions=actions, state=state(env)))
            traces.append(digest(trace))
            metadata.append(env.get_metadata()["temporal_reproducibility"])
        if len(set(traces)) != 1:
            raise AssertionError(
                "Seeded repeated/fresh/KPI-query rollouts differ: " + str(traces)
            )
        return dict(
            status="pass",
            schema=str(path.resolve()),
            start=start,
            end=start + transitions,
            seed=seed,
            transitions=transitions,
            replays=3,
            trace_sha256=traces[0],
            physics_invariant_checks=True,
            temporal_evidence=metadata,
            policy="citylearn.agents.baseline.NormalPolicy",
            queries_are_passive=True,
        )
    finally:
        for e in environments:
            e.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, action="append", required=True)
    parser.add_argument("--start", type=int)
    parser.add_argument("--transitions", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = dict(
        definition_version="temporal-evidence-v1",
        python=sys.version,
        platform=platform.platform(),
        numpy=np.__version__,
        pandas=pd.__version__,
        static=[],
        replay=[],
    )
    try:
        for schema in args.schema:
            report["static"].append(static_audit(schema))
            if args.start is not None:
                report["replay"].append(
                    replay(schema, args.start, args.transitions, args.seed)
                )
        report["status"] = "pass"
    except Exception as error:
        report.update(status="fail", error_type=type(error).__name__, error=str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps({key: report.get(key) for key in ("status", "error_type", "error")})
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
