#!/usr/bin/env python3
"""Measure behavioural and asset diversity in the annual REC dataset suite.

The structural and scientific audits establish integrity and scope.  This audit
adds distributional diagnostics that detect exact duplicates, hidden template
synchronisation and asset-size uniformity.  It deliberately evaluates scenario
diversity, not goodness of fit to a Portuguese population sample.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


FAMILY_DIRECTORIES = (
    "rec_2023_micro_4_q",
    "rec_2023_core_15_stripped",
    "rec_2023_core_30",
    "rec_2023_premium_100",
)
TIMEZONE = "Europe/Lisbon"


def _read_json(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _distribution(values: pd.Series | np.ndarray) -> Mapping[str, float | int]:
    array = np.asarray(values, dtype="float64")
    return {
        "count": int(array.size),
        "distinct": int(np.unique(array).size),
        "minimum": round(float(np.min(array)), 4),
        "p05": round(float(np.quantile(array, 0.05)), 4),
        "median": round(float(np.median(array)), 4),
        "p95": round(float(np.quantile(array, 0.95)), 4),
        "maximum": round(float(np.max(array)), 4),
        "mean": round(float(np.mean(array)), 4),
        "std": round(float(np.std(array)), 4),
    }


def _pairwise(values: np.ndarray) -> np.ndarray:
    if len(values) < 2:
        return np.array([], dtype="float64")
    correlation = np.corrcoef(values)
    return correlation[np.triu_indices(len(values), 1)]


def _correlation_summary(values: np.ndarray) -> Mapping[str, float | int | None]:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return {"pairs": 0, "median": None, "p95": None, "maximum": None}
    return {
        "pairs": int(len(finite)),
        "median": round(float(np.median(finite)), 5),
        "p95": round(float(np.quantile(finite, 0.95)), 5),
        "maximum": round(float(np.max(finite)), 5),
    }


def _cross_archetype_correlations(
    profiles: np.ndarray,
    archetypes: np.ndarray,
) -> np.ndarray:
    if len(profiles) < 2:
        return np.array([], dtype="float64")
    correlation = np.corrcoef(profiles)
    rows, columns = np.triu_indices(len(profiles), 1)
    keep = archetypes[rows] != archetypes[columns]
    return correlation[rows[keep], columns[keep]]


def _family_audit(root: Path) -> Mapping[str, Any]:
    manifest = _read_json(root / "dataset_manifest.json")
    members = pd.read_parquet(root / "catalogs/members.parquet")
    chargers = pd.read_parquet(root / "catalogs/chargers.parquet")
    sessions = pd.read_parquet(root / "catalogs/charging_sessions.parquet")
    deferrables = pd.read_parquet(root / "catalogs/deferrables.parquet")
    calendar = pd.read_parquet(root / "shared/calendar.parquet")
    local = pd.DatetimeIndex(calendar["timestamp_utc"]).tz_convert(TIMEZONE)
    weekday = local.dayofweek < 5
    morning = (local.hour >= 5) & (local.hour < 11)
    evening = (local.hour >= 17) & (local.hour < 23)
    clock_slot = local.hour.to_numpy(dtype="int16") * 4 + local.minute.to_numpy(dtype="int16") // 15
    clock_counts = np.bincount(clock_slot, minlength=96)

    load_rows = []
    pv_rows = []
    occupancy_rows = []
    signatures = []
    for member in members.itertuples(index=False):
        series = pd.read_parquet(
            root / "timeseries" / f"{member.member_id}.parquet",
            columns=["non_shiftable_load", "solar_generation", "occupant_count"],
        )
        load = series["non_shiftable_load"].to_numpy(dtype="float64")
        pv = series["solar_generation"].to_numpy(dtype="float64")
        occupancy = series["occupant_count"].to_numpy(dtype="float64")
        load_rows.append(load)
        pv_rows.append(pv)
        occupancy_rows.append(occupancy)
        signatures.append(hashlib.sha256(load.tobytes()).hexdigest())
    load_matrix = np.vstack(load_rows)
    np.vstack(pv_rows)
    occupancy_matrix = np.vstack(occupancy_rows)

    load_by_category = {}
    for category, group in members.groupby("category"):
        indices = group.index.to_numpy(dtype="int64")
        traces = load_matrix[indices]
        daily_profiles = np.vstack([
            np.bincount(clock_slot, weights=trace, minlength=96) / clock_counts
            for trace in traces
        ])
        daily_profiles /= daily_profiles.sum(axis=1, keepdims=True)
        archetypes = group["routine_archetype"].to_numpy(dtype=object)
        member_peak_minutes = np.argmax(daily_profiles, axis=1) * 15
        archetype_peak_minutes = {}
        for archetype, archetype_group in group.groupby("routine_archetype"):
            archetype_trace = load_matrix[archetype_group.index].mean(axis=0)
            profile = (
                np.bincount(clock_slot, weights=archetype_trace, minlength=96)
                / clock_counts
            )
            archetype_peak_minutes[str(archetype)] = int(np.argmax(profile) * 15)
        morning_evening = (
            traces[:, morning].mean(axis=1)
            / np.maximum(traces[:, evening].mean(axis=1), 1.0e-12)
        )
        weekday_weekend = (
            traces[:, weekday].mean(axis=1)
            / np.maximum(traces[:, ~weekday].mean(axis=1), 1.0e-12)
        )
        load_by_category[str(category)] = {
            "members": len(group),
            "routine_counts": {
                str(key): int(value)
                for key, value in group["routine_archetype"].value_counts().sort_index().items()
            },
            "annual_demand_kwh": _distribution(group["annual_non_shiftable_load_kwh"]),
            "annual_target_boundary_hits": int(
                group["annual_load_target_kwh"].isin(
                    [1_100.0, 6_500.0, 7_000.0, 45_000.0, 75_000.0, 350_000.0]
                ).sum()
            ),
            "full_trace_pairwise_correlation": _correlation_summary(_pairwise(traces)),
            "mean_daily_profile_pairwise_correlation": _correlation_summary(
                _pairwise(daily_profiles)
            ),
            "cross_archetype_daily_profile_correlation": _correlation_summary(
                _cross_archetype_correlations(daily_profiles, archetypes)
            ),
            "distinct_member_peak_times": int(np.unique(member_peak_minutes).size),
            "member_peak_minutes": sorted(int(value) for value in np.unique(member_peak_minutes)),
            "archetype_peak_minutes": archetype_peak_minutes,
            "morning_to_evening_ratio": _distribution(morning_evening),
            "weekday_to_weekend_ratio": _distribution(weekday_weekend),
        }

    pv_summary = {}
    for category, group in members[members["has_pv"]].groupby("category"):
        pv_summary[str(category)] = {
            "capacity_kw": _distribution(group["pv_capacity_kw"]),
            "capacity_unique_fraction": round(
                float(group["pv_capacity_kw"].nunique() / len(group)), 4
            ),
            "annual_pv_to_load_ratio": _distribution(group["annual_pv_to_load_ratio"]),
            "orientation_counts": {
                str(key): int(value)
                for key, value in group["pv_orientation_class"].value_counts().sort_index().items()
            },
            "derate_factor": _distribution(group["pv_derate_factor"]),
        }

    battery_summary = {}
    for category, group in members[members["has_battery"]].groupby("category"):
        battery_summary[str(category)] = {
            "capacity_kwh": _distribution(group["battery_capacity_kwh"]),
            "power_kw": _distribution(group["battery_nominal_power_kw"]),
            "initial_soc": _distribution(group["battery_initial_soc"]),
            "efficiency": _distribution(group["battery_efficiency"]),
            "depth_of_discharge": _distribution(group["battery_depth_of_discharge"]),
        }

    sessions = sessions.merge(
        members[["member_id", "category", "routine_archetype"]],
        on=["member_id", "routine_archetype"],
    )
    arrival_local = pd.to_datetime(
        sessions["arrival_timestamp_utc"], utc=True
    ).dt.tz_convert(TIMEZONE)
    departure_local = pd.to_datetime(
        sessions["departure_timestamp_utc"], utc=True
    ).dt.tz_convert(TIMEZONE)
    sessions["arrival_minute"] = arrival_local.dt.hour * 60 + arrival_local.dt.minute
    sessions["departure_minute"] = departure_local.dt.hour * 60 + departure_local.dt.minute
    sessions["energy_slack_ratio"] = (
        sessions["individual_charger_slack_kwh"]
        / sessions["individual_charger_deliverable_energy_kwh"]
    )
    ev_routines = {}
    for (category, archetype), group in sessions.groupby(["category", "routine_archetype"]):
        ev_routines[f"{category}/{archetype}"] = {
            "sessions": len(group),
            "arrival_minute": _distribution(group["arrival_minute"]),
            "departure_minute": _distribution(group["departure_minute"]),
            "connection_duration_hours": _distribution(group["connection_duration_hours"]),
            "required_energy_kwh": _distribution(group["required_energy_kwh"]),
            "temporal_slack_steps": _distribution(group["temporal_slack_steps"]),
        }
    charger_medians = sessions.groupby("charger_id")["arrival_minute"].median()
    ev_summary = {
        "sessions": len(sessions),
        "infeasible_sessions": int((~sessions["individual_charger_feasible"]).sum()),
        "negative_temporal_slack_sessions": int((sessions["temporal_slack_steps"] < 0).sum()),
        "distinct_arrival_clock_times": int(sessions["arrival_minute"].nunique()),
        "distinct_departure_clock_times": int(sessions["departure_minute"].nunique()),
        "distinct_charger_median_arrivals": int(charger_medians.nunique()),
        "connection_duration_hours": _distribution(sessions["connection_duration_hours"]),
        "required_energy_kwh": _distribution(sessions["required_energy_kwh"]),
        "energy_slack_ratio": _distribution(sessions["energy_slack_ratio"]),
        "temporal_slack_steps": _distribution(sessions["temporal_slack_steps"]),
        "by_routine": ev_routines,
    }

    deferrable_assets = []
    schedule_signatures = []
    for item in deferrables.itertuples(index=False):
        schedule = pd.read_parquet(
            root / "deferrables" / f"{item.deferrable_id}_schedule.parquet"
        )
        profile = pd.read_parquet(
            root / "deferrables" / f"{item.deferrable_id}_profiles.parquet"
        )
        earliest_clock = schedule["earliest_start_time_step"] % 96 * 15
        window_hours = (
            schedule["latest_start_time_step"]
            - schedule["earliest_start_time_step"]
        ) / 4.0
        deadline_margin_hours = (
            schedule["deadline_time_step"]
            - schedule["latest_start_time_step"]
        ) / 4.0
        signature_columns = [
            "profile_id",
            "earliest_start_time_step",
            "latest_start_time_step",
            "deadline_time_step",
            "priority",
            "must_run",
        ]
        schedule_signatures.append(
            hashlib.sha256(schedule[signature_columns].to_csv(index=False).encode()).hexdigest()
        )
        deferrable_assets.append(
            {
                "deferrable_id": item.deferrable_id,
                "member_id": item.member_id,
                "routine_archetype": item.routine_archetype,
                "appliance_type": item.appliance_type,
                "profile_scale": float(item.profile_scale),
                "annual_cycles": len(schedule),
                "profile_energy_kwh": _distribution(profile["total_energy_kwh"]),
                "earliest_start_clock_minute": _distribution(earliest_clock),
                "flexibility_window_hours": _distribution(window_hours),
                "deadline_margin_hours": _distribution(deadline_margin_hours),
                "must_run_rate": round(float(schedule["must_run"].mean()), 4),
            }
        )
    deferrable_summary = {
        "assets": len(deferrables),
        "routine_classes": int(deferrables["routine_archetype"].nunique()),
        "appliance_types": int(deferrables["appliance_type"].nunique()),
        "profile_scale_values": int(deferrables["profile_scale"].nunique()),
        "exact_duplicate_schedules": len(schedule_signatures) - len(set(schedule_signatures)),
        "per_asset": deferrable_assets,
    }

    return {
        "dataset_family": manifest["dataset_family"],
        "dataset_contract_version": manifest["dataset_contract_version"],
        "members": len(members),
        "exact_duplicate_load_traces": len(signatures) - len(set(signatures)),
        "members_with_time_varying_occupancy": int(
            sum(np.unique(row).size > 1 for row in occupancy_matrix)
        ),
        "load": load_by_category,
        "pv": pv_summary,
        "stationary_batteries": battery_summary,
        "chargers": {
            "physical": len(chargers),
            "charging_power_kw": _distribution(chargers["max_charging_power_kw"]),
            "phase_counts": {
                str(key): int(value)
                for key, value in chargers["phase_connection"].value_counts().sort_index().items()
            },
        },
        "ev_flexibility": ev_summary,
        "deferrables": deferrable_summary,
    }


def _findings(families: Mapping[str, Mapping[str, Any]]) -> list[Mapping[str, str]]:
    findings = []
    for family_name, family in families.items():
        if family["exact_duplicate_load_traces"]:
            findings.append({
                "severity": "critical",
                "id": f"{family_name}-DUPLICATE-LOAD",
                "finding": f"{family_name} contains exact duplicate member demand traces.",
            })
        if family["ev_flexibility"]["infeasible_sessions"] or family["ev_flexibility"]["negative_temporal_slack_sessions"]:
            findings.append({
                "severity": "critical",
                "id": f"{family_name}-EV-FEASIBILITY",
                "finding": f"{family_name} contains infeasible or negative-slack ordinary EV sessions.",
            })
        for category, metrics in family["load"].items():
            expected_routines = min(5, int(metrics["members"]))
            if len(metrics["routine_counts"]) != expected_routines:
                findings.append({
                    "severity": "high",
                    "id": f"{family_name}-{category}-ROUTINES",
                    "finding": f"{category} exposes {len(metrics['routine_counts'])} routines; {expected_routines} stratified classes were expected.",
                })
            correlation = metrics["cross_archetype_daily_profile_correlation"]["median"]
            if correlation is not None and correlation > 0.90:
                findings.append({
                    "severity": "high",
                    "id": f"{family_name}-{category}-PROFILE-SYNCHRONISATION",
                    "finding": f"Cross-archetype mean daily load correlation remains {correlation:.3f} for {category}.",
                })
        for category, metrics in family["pv"].items():
            if metrics["capacity_unique_fraction"] < 0.50:
                findings.append({
                    "severity": "medium",
                    "id": f"{family_name}-{category}-PV-UNIFORMITY",
                    "finding": f"Only {metrics['capacity_unique_fraction']:.1%} of PV capacities are distinct in {category}.",
                })
        for category, metrics in family["stationary_batteries"].items():
            if metrics["capacity_kwh"]["count"] > 1 and metrics["capacity_kwh"]["distinct"] < 2:
                findings.append({
                    "severity": "high",
                    "id": f"{family_name}-{category}-BESS-UNIFORMITY",
                    "finding": f"All {category} stationary batteries have the same capacity.",
                })
        if family["deferrables"]["exact_duplicate_schedules"]:
            findings.append({
                "severity": "high",
                "id": f"{family_name}-DEFERRABLE-DUPLICATES",
                "finding": f"{family_name} contains exact duplicate annual deferrable schedules.",
            })
    return findings


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Canonical annual REC suite: diversity audit",
        "",
        f"Audit date: {report['audit_date']}",
        "",
        f"Readiness: **{report['readiness']}**",
        "",
        "This audit measures controlled scenario diversity. It does not claim that archetype frequencies are fitted to a Portuguese REC population.",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines.extend(["No critical, high or medium diversity findings.", ""])
    for finding in report["findings"]:
        lines.extend(
            [
                f"### {finding['severity'].upper()}: {finding['id']}",
                "",
                finding["finding"],
                "",
            ]
        )
    lines.extend(["## Family summary", ""])
    for name, family in report["families"].items():
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Members: {family['members']}; exact duplicate loads: {family['exact_duplicate_load_traces']}.",
                f"- Time-varying occupancy: {family['members_with_time_varying_occupancy']} members.",
                f"- EV sessions: {family['ev_flexibility']['sessions']}; infeasible: {family['ev_flexibility']['infeasible_sessions']}.",
                f"- EV arrival clock times: {family['ev_flexibility']['distinct_arrival_clock_times']}.",
                f"- Deferrable assets: {family['deferrables']['assets']}; duplicate schedules: {family['deferrables']['exact_duplicate_schedules']}.",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    repository = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--dataset-root", type=Path, default=repository / "data/datasets"
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=repository / "results/raw/annual_rec_suite_diversity_audit_2026-08-21.json",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=repository / "results/raw/annual_rec_suite_diversity_audit_2026-08-21.md",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    families = {}
    for directory in FAMILY_DIRECTORIES:
        family = _family_audit(args.dataset_root / directory)
        families[family["dataset_family"]] = family
    findings = _findings(families)
    severe = [item for item in findings if item["severity"] in {"critical", "high"}]
    report = _json_ready(
        {
            "audit_date": date.today().isoformat(),
            "readiness": "pass" if not severe else "not_ready",
            "scope": "controlled scenario diversity; no population-frequency goodness-of-fit claim",
            "families": families,
            "findings": findings,
        }
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown_out.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"readiness": report["readiness"], "findings": len(findings)}, indent=2))
    for family_name, family in families.items():
        print(
            f"{family_name}: members={family['members']}, "
            f"duplicate_loads={family['exact_duplicate_load_traces']}, "
            f"ev_sessions={family['ev_flexibility']['sessions']}, "
            f"infeasible_ev={family['ev_flexibility']['infeasible_sessions']}"
        )


if __name__ == "__main__":
    main()
