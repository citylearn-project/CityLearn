#!/usr/bin/env python3
"""Audit the canonical 2023 quarter-hour REC dataset suite."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import List, Mapping

import numpy as np
import pandas as pd


N_STEPS = 35_040
N_HOURS = 8_760
DATASET_CONTRACT_VERSION = "2023-q15-v1.9"
FAMILY_DIRECTORIES = (
    "rec_2023_micro_4_q",
    "rec_2023_core_15_stripped",
    "rec_2023_core_30",
    "rec_2023_premium_100",
)
EXPECTED_COMPOSITION = {
    "MICRO-4-Q": (4, 2, 1, 2, 2, 1),
    "CORE-15-STRIPPED": (15, 7, 3, 6, 7, 4),
    "CORE-30": (30, 15, 6, 12, 15, 8),
    "PREMIUM-100": (100, 55, 22, 45, 80, 30),
}


def _check(condition: bool, message: str, checks: List[Mapping]) -> None:
    checks.append({"status": "pass" if condition else "fail", "check": message})
    if not condition:
        raise AssertionError(message)


def _read_json(path: Path) -> Mapping:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_suite(dataset_root: Path) -> Mapping:
    checks: List[Mapping] = []
    core15 = dataset_root / "rec_2023_core_15_stripped"
    core30 = dataset_root / "rec_2023_core_30"
    shared_files = (
        "shared/calendar.parquet",
        "shared/weather.parquet",
        "shared/pricing_omie_2023.parquet",
        "shared/carbon_intensity.parquet",
    )
    subset_files = [*shared_files]
    subset_files.extend(f"timeseries/Member_{i:03d}.parquet" for i in range(1, 16))
    subset_files.extend(
        f"chargers/CHG-M{i:03d}-{j:02d}.parquet"
        for i, count in {1: 1, 2: 1, 4: 1, 5: 1, 6: 2, 10: 1}.items()
        for j in range(1, count + 1)
    )
    subset_files.extend(
        f"deferrables/DEF-M{i:03d}-01_{suffix}.parquet"
        for i in (2, 6, 9, 14)
        for suffix in ("profiles", "schedule")
    )
    _check(
        all(_sha256(core15 / relative) == _sha256(core30 / relative) for relative in subset_files),
        "CORE-15-STRIPPED is a byte-identical physical subset of CORE-30",
        checks,
    )

    premium = dataset_root / "rec_2023_premium_100"
    clean = _read_json(premium / "schemas/premium_100_clean.json")
    allin = _read_json(premium / "schemas/premium_100_allin.json")
    _check(clean["topology_events"] == allin["topology_events"], "Premium Clean and AllIn use identical topology events", checks)
    active = {member_id for member_id, building in clean["buildings"].items() if building.get("include", True)}
    seen = set(active)
    returns = 0
    exits = 0
    populations = [len(active)]
    for event in clean["topology_events"]:
        if event["operation"] == "add_member":
            returns += int(event["target_member_id"] in seen)
            seen.add(event["target_member_id"])
            active.add(event["target_member_id"])
        elif event["operation"] == "remove_member":
            exits += 1
            active.discard(event["target_member_id"])
        populations.append(len(active))
    _check(min(populations) >= 70 and max(populations) == 100, "Premium active population remains between 70 and 100 and reaches 100", checks)
    _check(exits == 6 and returns == 0, "Premium has six permanent departures and no state-resetting member re-entry", checks)
    _check("robustness" not in clean and allin.get("robustness", {}).get("enabled") is True, "Premium AllIn adds health faults while Clean does not", checks)
    return {"status": "pass", "check_count": len(checks), "checks": checks}


def audit_family(root: Path) -> Mapping:
    checks: List[Mapping] = []
    manifest = _read_json(root / "dataset_manifest.json")
    composition = manifest["composition"]
    calendar = pd.read_parquet(root / "shared/calendar.parquet")
    pricing = pd.read_parquet(root / "shared/pricing_omie_2023.parquet")
    omie = pd.read_parquet(root / "sources/omie_2023_hourly.parquet")
    omie_provenance = pd.read_csv(root / "sources/omie_2023_daily_provenance.csv")
    members = pd.read_parquet(root / "catalogs/members.parquet")
    chargers = pd.read_parquet(root / "catalogs/chargers.parquet")
    evs = pd.read_parquet(root / "catalogs/electric_vehicles.parquet")
    sessions = pd.read_parquet(root / "catalogs/charging_sessions.parquet")
    deferrables = pd.read_parquet(root / "catalogs/deferrables.parquet")
    electrical = pd.read_parquet(root / "catalogs/electrical_services.parquet")

    _check(
        manifest["dataset_contract_version"] == DATASET_CONTRACT_VERSION,
        "dataset uses the frozen v1.9 quarter-hour contract",
        checks,
    )
    calendar_contract = manifest.get("calibration_and_scope", {}).get(
        "calendar", {}
    )
    _check(
        calendar_contract.get("routine_time_basis")
        == "Europe/Lisbon civil wall clock localized before UTC conversion"
        and calendar_contract.get("nonexistent_spring_time_policy")
        == "shift forward by one hour"
        and calendar_contract.get("ambiguous_autumn_time_policy")
        == "first occurrence",
        "routine schedules declare deterministic civil-time DST semantics",
        checks,
    )
    _check(len(calendar) == N_STEPS, "calendar has 35,040 rows", checks)
    _check(calendar["time_step"].tolist() == list(range(N_STEPS)), "time_step is contiguous", checks)
    timestamps = pd.to_datetime(calendar["timestamp_utc"], utc=True)
    _check(timestamps.iloc[0] == pd.Timestamp("2023-01-01T00:00:00Z"), "UTC calendar starts at 2023-01-01", checks)
    _check(timestamps.iloc[-1] == pd.Timestamp("2023-12-31T23:45:00Z"), "UTC calendar ends at 2023-12-31 23:45", checks)
    _check((timestamps.diff().dropna() == pd.Timedelta(minutes=15)).all(), "UTC cadence is exactly 15 minutes", checks)
    _check(set(calendar["timezone"]) == {"Europe/Lisbon"}, "local timezone is Europe/Lisbon", checks)
    _check(set(calendar["utc_offset_minutes"]) == {0, 60}, "Lisbon UTC offsets include winter and DST", checks)
    local_dates = pd.to_datetime(calendar["timestamp_local"], utc=True).dt.tz_convert(
        "Europe/Lisbon"
    ).dt.date
    local_day_lengths = pd.Series(local_dates).value_counts().value_counts().to_dict()
    _check(
        local_day_lengths == {96: 363, 92: 1, 100: 1},
        "local calendar contains 363 regular, one 23-hour and one 25-hour day",
        checks,
    )

    _check(len(omie) == N_HOURS, "official OMIE series has 8,760 physical hours", checks)
    _check(len(omie_provenance) == 365, "OMIE provenance identifies all 365 daily source files", checks)
    _check(omie_provenance["raw_sha256"].str.fullmatch(r"[0-9a-f]{64}").all(), "every OMIE daily source has a SHA-256 hash", checks)
    _check(omie_provenance["url"].str.startswith("https://www.omie.es/").all(), "every OMIE source URL is official", checks)
    _check(int(omie_provenance["periods"].sum()) == N_HOURS, "daily OMIE physical periods sum to 8,760", checks)
    _check(len(pricing) == N_STEPS, "quarter-hour pricing has 35,040 rows", checks)
    prices = pricing["electricity_pricing"].to_numpy(dtype="float64")
    _check(np.allclose(prices.reshape(-1, 4), prices.reshape(-1, 4)[:, :1]), "each official hourly price is repeated four times", checks)
    official = omie["price_portugal_eur_per_mwh"].to_numpy(dtype="float64") / 1000.0
    _check(np.allclose(prices[::4], official, atol=1e-7), "EUR/MWh to EUR/kWh conversion is exact", checks)
    current_indices = np.arange(N_STEPS, dtype="int64")
    local_index = pd.DatetimeIndex(timestamps).tz_convert("Europe/Lisbon")
    for number, horizon in enumerate((4, 24, 96), start=1):
        target_indices = np.minimum(current_indices + horizon, N_STEPS - 1)
        target = prices[target_indices]
        target_delivery_dates = local_index[target_indices].normalize()
        publication_instants = target_delivery_dates - pd.Timedelta(days=1) + pd.Timedelta(hours=13)
        published = local_index >= publication_instants
        prediction = pricing[f"electricity_pricing_predicted_{number}"].to_numpy(dtype="float64")
        _check(
            np.allclose(prediction[published], target[published], atol=1.0e-7),
            f"published OMIE values are exact at price horizon {horizon}",
            checks,
        )
        persistence_indices = np.maximum(target_indices - 96, 0)
        persistence_indices = np.minimum(persistence_indices, current_indices)
        expected_unpublished = prices[persistence_indices]
        _check(
            np.allclose(prediction[~published], expected_unpublished[~published], atol=1.0e-7),
            f"unpublished price horizon {horizon} uses causal daily persistence",
            checks,
        )
    horizon_24_target = prices[np.minimum(current_indices + 96, N_STEPS - 1)]
    horizon_24_prediction = pricing["electricity_pricing_predicted_3"].to_numpy(dtype="float64")
    horizon_24_delivery_dates = local_index[np.minimum(current_indices + 96, N_STEPS - 1)].normalize()
    horizon_24_published = local_index >= (
        horizon_24_delivery_dates - pd.Timedelta(days=1) + pd.Timedelta(hours=13)
    )
    _check(
        not np.allclose(horizon_24_prediction[~horizon_24_published], horizon_24_target[~horizon_24_published]),
        "24-hour price bundle does not leak unpublished realised prices",
        checks,
    )
    weather = pd.read_parquet(root / "shared/weather.parquet")
    weather_forecasts_have_error = []
    for variable in (
        "outdoor_dry_bulb_temperature",
        "outdoor_relative_humidity",
        "diffuse_solar_irradiance",
        "direct_solar_irradiance",
    ):
        values = weather[variable].to_numpy(dtype="float64")
        for number, horizon in enumerate((4, 24, 96), start=1):
            truth = np.empty_like(values)
            truth[:-horizon] = values[horizon:]
            truth[-horizon:] = values[-1]
            prediction = weather[f"{variable}_predicted_{number}"].to_numpy(dtype="float64")
            weather_forecasts_have_error.append(not np.allclose(prediction, truth))
    _check(all(weather_forecasts_have_error), "all weather forecast horizons include non-perfect scenario error", checks)

    _check(len(members) == composition["members"], "member count matches manifest", checks)
    _check(int(members["has_pv"].sum()) == composition["pv_assets"], "PV count matches manifest", checks)
    _check(int(members["has_battery"].sum()) == composition["stationary_batteries"], "battery count matches manifest", checks)
    _check(len(chargers) == composition["physical_chargers"], "physical charger count matches manifest", checks)
    _check(chargers["member_id"].nunique() == composition["charger_equipped_members"], "charging-member count matches manifest", checks)
    _check(len(deferrables) == composition["deferrable_appliances"], "deferrable count matches manifest", checks)
    _check(len(electrical) == len(members), "every member has one electrical-connection record", checks)
    _check(electrical["member_id"].is_unique, "electrical-connection member identities are unique", checks)
    expected = EXPECTED_COMPOSITION[manifest["dataset_family"]]
    observed = (
        len(members),
        int(members["has_pv"].sum()),
        int(members["has_battery"].sum()),
        chargers["member_id"].nunique(),
        len(chargers),
        len(deferrables),
    )
    _check(observed == expected, "composition matches the consolidated suite contract", checks)
    _check(
        members["routine_archetype"].notna().all(),
        "every member has an explicit routine archetype",
        checks,
    )
    routine_counts = members.groupby("category")["routine_archetype"].nunique()
    category_counts = members["category"].value_counts()
    _check(
        all(
            int(routine_counts[category]) == min(5, int(count))
            for category, count in category_counts.items()
        ),
        "routine archetypes are stratified up to five classes per member category",
        checks,
    )
    pv_members = members[members["has_pv"]]
    _check(
        all(
            group["pv_capacity_kw"].nunique() >= max(1, int(np.ceil(len(group) * 0.50)))
            for _, group in pv_members.groupby("category")
        ),
        "PV capacities are heterogeneous within each represented category",
        checks,
    )
    battery_members = members[members["has_battery"]]
    if len(battery_members) > 1:
        _check(
            battery_members["battery_capacity_kwh"].nunique() >= 2,
            "multi-battery families contain more than one stationary-storage capacity",
            checks,
        )
        _check(
            battery_members["battery_initial_soc"].nunique() == len(battery_members),
            "stationary batteries have member-specific initial SOC values",
            checks,
        )
    charger_counts = chargers.groupby("member_id").size().to_dict()
    catalog_counts = members.set_index("member_id")["physical_charger_count"].astype(int).to_dict()
    _check(all(charger_counts.get(member_id, 0) == count for member_id, count in catalog_counts.items()), "per-member charger multiplicity matches the catalog", checks)
    _check(max(catalog_counts.values()) >= (1 if len(chargers) else 0), "at least one declared charger is present", checks)
    if manifest["dataset_family"] in {"CORE-15-STRIPPED", "CORE-30", "PREMIUM-100"}:
        _check(max(catalog_counts.values()) >= 2, "the family contains a member with multiple chargers", checks)
    if manifest["dataset_family"] == "PREMIUM-100":
        category_counts = members["category"].value_counts().to_dict()
        _check(category_counts == {"residential": 70, "small_service": 20, "high_consumption": 10}, "Premium member categories are 70/20/10", checks)
        by_category = chargers.merge(members[["member_id", "category"]], on="member_id").groupby("category").size().to_dict()
        _check(by_category == {"residential": 36, "small_service": 20, "high_consumption": 24}, "Premium charger distribution is 36/20/24", checks)

    for frame, column, label in (
        (members, "member_id", "member"),
        (chargers, "charger_id", "charger"),
        (evs, "ev_id", "EV"),
        (sessions, "session_id", "session"),
        (deferrables, "deferrable_id", "deferrable"),
    ):
        _check(frame[column].notna().all() and frame[column].is_unique, f"{label} identities are non-null and unique", checks)

    _check(set(chargers["member_id"]).issubset(set(members["member_id"])), "every charger belongs to a known member", checks)
    _check(set(sessions["charger_id"]).issubset(set(chargers["charger_id"])), "every session uses a known charger", checks)
    _check(set(sessions["ev_id"]).issubset(set(evs["ev_id"])), "every session uses a known EV", checks)
    _check((sessions["departure_time_step"] > sessions["arrival_time_step"]).all(), "all EV session deadlines follow arrival", checks)
    _check((sessions["deadline_time_step"] == sessions["departure_time_step"]).all(), "EV deadlines equal departure steps", checks)
    expected_arrival_utc = timestamps.iloc[
        sessions["arrival_time_step"].to_numpy(dtype="int64")
    ].reset_index(drop=True)
    declared_arrival_utc = pd.to_datetime(
        sessions["arrival_timestamp_utc"], utc=True
    ).reset_index(drop=True)
    _check(
        expected_arrival_utc.equals(declared_arrival_utc),
        "EV arrival timestamps map exactly to their quarter-hour time steps",
        checks,
    )
    expected_departure_utc = timestamps.iloc[0] + pd.to_timedelta(
        sessions["departure_time_step"].to_numpy(dtype="int64") * 15,
        unit="min",
    )
    declared_departure_utc = pd.DatetimeIndex(
        pd.to_datetime(sessions["departure_timestamp_utc"], utc=True)
    )
    _check(
        pd.DatetimeIndex(expected_departure_utc).equals(declared_departure_utc),
        "EV departure timestamps map exactly to their quarter-hour boundaries",
        checks,
    )
    _check(sessions["individual_charger_feasible"].all(), "all ordinary EV sessions are individually feasible", checks)
    _check((sessions["required_energy_kwh"] > 0.0).all(), "all EV sessions request positive energy", checks)
    _check(
        (sessions["required_energy_kwh"] <= sessions["individual_charger_deliverable_energy_kwh"] + 1.0e-6).all(),
        "EV required energy never exceeds charger-window deliverability",
        checks,
    )
    _check((sessions["individual_charger_slack_kwh"] >= -1.0e-6).all(), "EV sessions retain non-negative individual charger slack", checks)
    _check((sessions["temporal_slack_steps"] >= 0).all(), "EV sessions retain non-negative full-power temporal slack", checks)
    _check(
        sessions.merge(
            members[["member_id", "routine_archetype"]],
            on="member_id",
            suffixes=("_session", "_member"),
        ).eval("routine_archetype_session == routine_archetype_member").all(),
        "every EV session retains its host routine archetype",
        checks,
    )

    _check((sessions.groupby("ev_id")["charger_id"].nunique() == 1).all(), "each EV belongs to one charger schedule", checks)
    overlap_free = True
    for _, group in sessions.sort_values(["ev_id", "arrival_time_step"]).groupby("ev_id"):
        departures = group["departure_time_step"].to_numpy(dtype="int64")
        arrivals = group["arrival_time_step"].to_numpy(dtype="int64")
        if len(group) > 1 and not np.all(departures[:-1] <= arrivals[1:]):
            overlap_free = False
            break
    _check(overlap_free, "EV sessions never overlap", checks)

    for charger in chargers.itertuples(index=False):
        schedule_path = root / "chargers" / f"{charger.charger_id}.parquet"
        schedule = pd.read_parquet(schedule_path)
        _check(len(schedule) == N_STEPS, f"{charger.charger_id} has 35,040 rows", checks)
        charger_sessions = sessions[sessions["charger_id"] == charger.charger_id]
        connected_windows_valid = True
        identity_windows_valid = True
        session_identity_windows_valid = True
        boundary_soc_valid = True
        for session in charger_sessions.itertuples(index=False):
            window = schedule.iloc[int(session.arrival_time_step):int(session.departure_time_step)]
            connected_windows_valid = connected_windows_valid and bool(
                (window["electric_vehicle_charger_state"] == 1).all()
            )
            identity_windows_valid = identity_windows_valid and bool(
                (window["electric_vehicle_id"] == session.ev_id).all()
            )
            session_identity_windows_valid = session_identity_windows_valid and bool(
                "electric_vehicle_session_id" in window.columns
                and (window["electric_vehicle_session_id"] == session.session_id).all()
            )
            reference = window["electric_vehicle_current_soc"].to_numpy(dtype="float64")
            boundary_soc_valid = boundary_soc_valid and bool(
                len(reference) > 0
                and np.isfinite(reference).all()
                and np.isclose(reference[0], float(session.arrival_soc), atol=1.0e-6)
                and (reference >= float(session.arrival_soc) - 1.0e-6).all()
                and (reference < float(session.required_departure_soc) + 1.0e-6).all()
                and (np.diff(reference) >= -1.0e-7).all()
                and np.isclose(
                    reference[-1] + (
                        float(session.required_departure_soc) - float(session.arrival_soc)
                    ) / len(reference),
                    float(session.required_departure_soc),
                    atol=2.0e-6,
                )
            )
        _check(connected_windows_valid, f"{charger.charger_id} sessions are connected throughout occupied windows", checks)
        _check(identity_windows_valid, f"{charger.charger_id} preserves every EV-to-session association", checks)
        _check(
            session_identity_windows_valid,
            f"{charger.charger_id} preserves every explicit session-to-charger association",
            checks,
        )
        connected = schedule["electric_vehicle_charger_state"] == 1
        observed_session_ids = set(
            schedule.loc[connected, "electric_vehicle_session_id"].astype(str)
        )
        declared_session_ids = set(charger_sessions["session_id"].astype(str))
        _check(
            bool((schedule.loc[connected, "electric_vehicle_session_id"].astype(str) != "").all())
            and bool((schedule.loc[~connected & (schedule["electric_vehicle_charger_state"] == 3), "electric_vehicle_session_id"].astype(str) == "").all())
            and observed_session_ids == declared_session_ids,
            f"{charger.charger_id} runtime session identity is complete and bijective with the catalogue",
            checks,
        )
        _check(boundary_soc_valid, f"{charger.charger_id} provides a feasible mid-session SOC initialization reference", checks)
        disconnected = schedule["electric_vehicle_charger_state"] != 1
        _check(
            schedule.loc[disconnected, "electric_vehicle_current_soc"].isna().all(),
            f"{charger.charger_id} exposes no current-SOC reference while disconnected",
            checks,
        )

    load_signatures = []
    varying_occupancy_members = 0
    for member in members.itertuples(index=False):
        frame = pd.read_parquet(root / "timeseries" / f"{member.member_id}.parquet")
        _check(len(frame) == N_STEPS, f"{member.member_id} has 35,040 rows", checks)
        _check((frame["non_shiftable_load"] >= 0).all(), f"{member.member_id} load is non-negative", checks)
        _check((frame["solar_generation"] >= 0).all(), f"{member.member_id} PV is non-negative", checks)
        load_signatures.append(hashlib.sha256(frame["non_shiftable_load"].to_numpy().tobytes()).hexdigest())
        varying_occupancy_members += int(frame["occupant_count"].nunique() > 1)
    _check(len(set(load_signatures)) == len(load_signatures), "member load traces contain no exact duplicates", checks)
    _check(varying_occupancy_members > 0, "the family contains time-varying occupancy routines", checks)
    _check(
        not members["annual_load_target_kwh"].isin([1_100.0, 6_500.0, 7_000.0, 45_000.0, 75_000.0, 350_000.0]).any(),
        "annual demand sampling creates no clipping-limit point masses",
        checks,
    )

    for item in deferrables.itertuples(index=False):
        profiles = pd.read_parquet(root / "deferrables" / f"{item.deferrable_id}_profiles.parquet")
        schedule = pd.read_parquet(root / "deferrables" / f"{item.deferrable_id}_schedule.parquet")
        profile_ids = set(profiles["profile_id"])
        _check(set(schedule["profile_id"]).issubset(profile_ids), f"{item.deferrable_id} schedules reference known profiles", checks)
        _check((schedule["earliest_start_time_step"] <= schedule["latest_start_time_step"]).all(), f"{item.deferrable_id} earliest/latest windows are ordered", checks)
        _check((schedule["latest_start_time_step"] <= schedule["deadline_time_step"]).all(), f"{item.deferrable_id} start windows precede deadlines", checks)
        _check(schedule["must_run"].notna().all(), f"{item.deferrable_id} defines must_run", checks)
        ordered_schedule = schedule.sort_values("earliest_start_time_step")
        _check(
            len(ordered_schedule) < 2
            or (
                ordered_schedule["earliest_start_time_step"].to_numpy(dtype="int64")[1:]
                > ordered_schedule["deadline_time_step"].to_numpy(dtype="int64")[:-1]
            ).all(),
            f"{item.deferrable_id} cycle request windows do not overlap",
            checks,
        )
        _check(
            item.routine_archetype == members.set_index("member_id").loc[item.member_id, "routine_archetype"],
            f"{item.deferrable_id} retains its host routine archetype",
            checks,
        )

    member_categories = members.set_index("member_id")["category"].to_dict()
    normalized_btn = {3.45, 4.60, 5.75, 6.90, 10.35, 13.80, 17.25, 20.70, 27.60, 34.50, 41.40}
    _check(
        all(
            round(float(row.contracted_power_kva), 2) in normalized_btn
            for row in electrical.itertuples(index=False)
            if member_categories[row.member_id] != "high_consumption"
        ),
        "residential and small-service contracts use normalized Portuguese BTN levels",
        checks,
    )
    _check(
        all(
            float(row.contracted_power_kva) > 41.40
            for row in electrical.itertuples(index=False)
            if member_categories[row.member_id] == "high_consumption"
        ),
        "high-consumption members use representative BTE-level contracted powers",
        checks,
    )
    _check(
        all(
            float(row.contracted_power_kva) <= 10.35
            for row in electrical.itertuples(index=False)
            if row.connection_type == "single_phase"
        ),
        "single-phase contracts do not exceed 10.35 kVA",
        checks,
    )
    phase_columns = [f"{phase}_import_limit_kw" for phase in ("l1", "l2", "l3")]
    phase_sums = electrical[phase_columns].sum(axis=1)
    _check(
        np.allclose(phase_sums, electrical["total_import_limit_kw"], atol=0.002),
        "per-phase import limits sum to each total connection limit",
        checks,
    )
    _check(
        all(
            sum(float(getattr(row, column)) > 0.0 for column in phase_columns) == 1
            for row in electrical.itertuples(index=False)
            if row.connection_type == "single_phase"
        ),
        "each single-phase connection is assigned to exactly one community phase",
        checks,
    )
    _check(
        set(chargers["phase_connection"]).issubset({"L1", "L2", "L3", "all_phases"}),
        "charger phase labels use the supported electrical model",
        checks,
    )
    residential_chargers = chargers.merge(
        members[["member_id", "category"]], on="member_id"
    )
    residential_chargers = residential_chargers[
        (residential_chargers["category"] == "residential")
        & residential_chargers["phase_connection"].isin({"L1", "L2", "L3"})
    ]
    if len(residential_chargers) >= 3:
        phase_counts = residential_chargers["phase_connection"].value_counts().reindex(
            ["L1", "L2", "L3"], fill_value=0
        )
        _check(
            int(phase_counts.max() - phase_counts.min()) <= 1,
            "individually connected residential chargers are balanced across L1/L2/L3",
            checks,
        )

    settlement = _read_json(root / "settlement_contract.json")
    _check(settlement["local_price_ratio_to_grid_import"] == 0.8, "local price is 80% of OMIE", checks)
    _check(settlement["grid_export_price_eur_per_kwh"] == 0.0, "residual export has no remuneration", checks)
    _check(settlement["counterfactual"].startswith("grid_only"), "grid-only counterfactual is declared", checks)

    schemas = {name: _read_json(root / relative) for name, relative in manifest["variants"].items()}
    physical_signatures = []
    for name, schema in schemas.items():
        _check(
            schema["dataset_contract_version"] == DATASET_CONTRACT_VERSION,
            f"{name} declares the v1.9 dataset contract",
            checks,
        )
        forecast_contract = schema.get("derived_forecasts", {})
        _check(
            forecast_contract.get("load_pv_method") == "daily_persistence"
            and float(forecast_contract.get("persistence_period_seconds", 0.0)) == 86_400.0
            and forecast_contract.get("cold_start") == "current_step",
            f"{name} uses causal daily-persistence load/PV forecasts",
            checks,
        )
        _check(
            forecast_contract.get("price_source") == "publication_aware_day_ahead_market_input"
            and forecast_contract.get("price_publication_time_local") == "13:00"
            and forecast_contract.get("price_unpublished_fallback") == "daily_persistence"
            and forecast_contract.get("price_horizon_steps") == [4, 24, 96],
            f"{name} declares publication-aware causal OMIE price forecasts",
            checks,
        )
        _check(schema["seconds_per_time_step"] == 900, f"{name} uses 900-second steps", checks)
        _check(schema["simulation_end_time_step"] == N_STEPS - 1, f"{name} spans the complete year", checks)
        _check(len(schema["buildings"]) == len(members), f"{name} contains the complete member catalog", checks)
        signature = {
            member_id: (
                building["energy_simulation"],
                building["weather"],
                building["carbon_intensity"],
                building["pricing"],
                tuple(sorted((building.get("chargers") or {}).keys())),
                tuple(sorted((building.get("deferrable_appliances") or {}).keys())),
            )
            for member_id, building in schema["buildings"].items()
        }
        physical_signatures.append(signature)
        storage_matches_catalog = all(
            (
                "electrical_storage" not in schema["buildings"][member.member_id]
                if not bool(member.has_battery)
                else (
                    float(schema["buildings"][member.member_id]["electrical_storage"]["attributes"]["capacity"])
                    == float(member.battery_capacity_kwh)
                    and float(schema["buildings"][member.member_id]["electrical_storage"]["attributes"]["nominal_power"])
                    == float(member.battery_nominal_power_kw)
                    and float(schema["buildings"][member.member_id]["electrical_storage"]["attributes"]["initial_soc"])
                    == float(member.battery_initial_soc)
                )
            )
            for member in members.itertuples(index=False)
        )
        _check(storage_matches_catalog, f"{name} stationary-storage attributes match the member catalog", checks)
    _check(all(value == physical_signatures[0] for value in physical_signatures[1:]), "scenario twins share identical physical files and asset identities", checks)
    dynamic_schemas = [schema for schema in schemas.values() if schema.get("topology_mode") == "dynamic"]
    if dynamic_schemas:
        mutated_asset_types = {
            event.get("target_asset_type")
            for schema in dynamic_schemas
            for event in schema.get("topology_events", [])
            if event.get("operation") in {"add_asset", "remove_asset"}
        }
        _check(
            {"charger", "pv", "electrical_storage", "deferrable_appliance"}.issubset(mutated_asset_types),
            "dynamic variants independently remove and restore charger, PV, storage and deferrable assets",
            checks,
        )

    checksum_path = root / manifest["file_integrity"]
    declared_checksums = {}
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", maxsplit=1)
        declared_checksums[relative] = digest
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in {"file_checksums.sha256", "validation_report.json"}
    }
    _check(set(declared_checksums) == actual_files, "checksum manifest covers every generated family file", checks)
    _check(
        all(_sha256(root / relative) == digest for relative, digest in declared_checksums.items()),
        "all generated family files match their SHA-256 checksums",
        checks,
    )

    return {
        "dataset_family": manifest["dataset_family"],
        "status": "pass",
        "check_count": len(checks),
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parents[2] / "data/datasets"
    parser.add_argument("--dataset-root", type=Path, default=default_root)
    parser.add_argument("--families", nargs="*", default=list(FAMILY_DIRECTORIES))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports = []
    for directory in args.families:
        root = args.dataset_root / directory
        report = audit_family(root)
        reports.append(report)
        (root / "validation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{directory}: PASS ({report['check_count']} checks)")
    suite_report = None
    if set(FAMILY_DIRECTORIES).issubset(set(args.families)):
        suite_report = audit_suite(args.dataset_root)
        suite_report_path = args.dataset_root / "rec_2023_source_data/suite_validation_report.json"
        suite_report_path.parent.mkdir(parents=True, exist_ok=True)
        suite_report_path.write_text(
            json.dumps(suite_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"annual suite: PASS ({suite_report['check_count']} cross-family checks)")
    print(json.dumps({"status": "pass", "families": len(reports), "suite": suite_report is not None}, indent=2))


if __name__ == "__main__":
    main()
