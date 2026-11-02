"""Explicit populations and sufficient statistics for KPI family audits."""

from collections import defaultdict
from math import ceil
import numpy as np

DEFINITION_VERSION = "kpi-families-audit-v1"


def ratio(a, b):
    return float(a / b) if b > 0 else None


def metadata():
    return dict(
        definition_version=DEFINITION_VERSION,
        interval_boundary="executed_active_intervals",
        district_thermal_aggregation="pooled_exposure_and_energy",
        service_energy="thermal demand energy plus base electrical demand; component shortfalls never cancel",
        undefined="null/NaN with population and coverage; never a synthetic success",
        legacy_zero_demand_unserved_ratio="retained as zero; use audited coverage for interpretation",
        empirical_calibration=False,
    )


def reward_metadata(env):
    reward = getattr(env, "reward_function", None)
    configured = dict((env.schema.get("reward_function") or {}).get("attributes") or {})
    effective = {}
    for name in set(configured) | {
        "exponent",
        "charging_constraint_penalty_coefficient",
    }:
        value = getattr(reward, name, None)
        if isinstance(value, (str, bool, int, float)):
            effective[name] = value
    return dict(
        definition_version="reward-evidence-v1",
        resolved_class=None
        if reward is None
        else type(reward).__module__ + "." + type(reward).__qualname__,
        configured_attributes=configured,
        effective_public_parameters=effective,
        dr_settlement_added_by_core=False,
        custom_reward_semantics="require explicit inspection; no automatic inference",
    )


def thermal_counts(
    temperature, cooling, heating, band, occupants, expected, served, outage, step_hours
):
    t, c, h, occ, out = [
        np.asarray(v, dtype=float)
        for v in (temperature, cooling, heating, occupants, outage)
    ]
    n = len(t)
    b = np.broadcast_to(np.asarray(band, dtype=float), t.shape)
    occupancy_known = np.isfinite(occ) & (occ >= 0)
    occupied = occupancy_known & (occ > 0)
    known = (
        np.isfinite(t)
        & np.isfinite(c)
        & np.isfinite(h)
        & np.isfinite(b)
        & (b >= 0)
        & (h <= c)
    )
    valid = occupied & known
    cold = valid & (t < h - b)
    hot = valid & (t > c + b)
    outage_known = np.isfinite(out) & (out >= 0)
    island = outage_known & (out > 0)
    e, s = [np.asarray(v, dtype=float).reshape(n, 4) for v in (expected, served)]
    energy_valid = np.all(np.isfinite(e) & np.isfinite(s) & (e >= 0) & (s >= 0), axis=1)
    e = np.where(energy_valid[:, None], e, 0.0)
    s = np.where(energy_valid[:, None], s, 0.0)
    short = np.maximum(e - s, 0.0)
    count = lambda mask: float(np.count_nonzero(mask))
    r = dict(
        executed_intervals_count=float(n),
        known_occupancy_intervals_count=count(occupancy_known),
        occupied_intervals_count=count(occupied),
        evaluated_occupied_intervals_count=count(valid),
        excluded_occupied_intervals_count=count(occupied & ~known),
        discomfort_intervals_count=count(cold | hot),
        cold_intervals_count=count(cold),
        hot_intervals_count=count(hot),
        occupied_hours=count(occupied) * step_hours,
        evaluated_occupied_hours=count(valid) * step_hours,
        discomfort_hours=count(cold | hot) * step_hours,
        cold_degree_hours=float(np.sum((h - t)[cold])) * step_hours,
        hot_degree_hours=float(np.sum((t - c)[hot])) * step_hours,
        outage_intervals_count=count(island),
        unknown_outage_intervals_count=count(~outage_known),
        outage_occupied_intervals_count=count(island & occupied),
        evaluated_outage_occupied_intervals_count=count(island & valid),
        outage_discomfort_intervals_count=count(island & (cold | hot)),
        energy_evaluated_intervals_count=count(energy_valid),
        expected_service_energy_kwh=float(e.sum()),
        served_service_energy_kwh=float(s.sum()),
        unserved_service_energy_kwh=float(short.sum()),
        outage_expected_service_energy_kwh=float(e[island].sum()),
        outage_unserved_service_energy_kwh=float(short[island].sum()),
    )
    return r


def pool_thermal(rows):
    result = defaultdict(float)
    for row in rows:
        for key, value in row.items():
            result[key] += value
    if not result:
        return thermal_counts(
            [], [], [], [], [], np.empty((0, 4)), np.empty((0, 4)), [], 1.0
        )
    return dict(result)


def thermal_metrics(counts):
    r = dict(counts)
    for key, a, b in [
        (
            "discomfort_ratio",
            "discomfort_intervals_count",
            "evaluated_occupied_intervals_count",
        ),
        (
            "thermal_coverage_ratio",
            "evaluated_occupied_intervals_count",
            "occupied_intervals_count",
        ),
        (
            "occupancy_coverage_ratio",
            "known_occupancy_intervals_count",
            "executed_intervals_count",
        ),
        (
            "outage_discomfort_ratio",
            "outage_discomfort_intervals_count",
            "evaluated_outage_occupied_intervals_count",
        ),
        (
            "outage_thermal_coverage_ratio",
            "evaluated_outage_occupied_intervals_count",
            "outage_occupied_intervals_count",
        ),
        (
            "energy_coverage_ratio",
            "energy_evaluated_intervals_count",
            "executed_intervals_count",
        ),
        (
            "unserved_service_ratio",
            "unserved_service_energy_kwh",
            "expected_service_energy_kwh",
        ),
        (
            "outage_unserved_service_ratio",
            "outage_unserved_service_energy_kwh",
            "outage_expected_service_energy_kwh",
        ),
    ]:
        r[key] = ratio(r[a], r[b])
    return r


def equity_metrics(costs):
    benefits = []
    nonpositive = unknown = 0
    for actual, reference in costs:
        if not np.isfinite(actual) or not np.isfinite(reference):
            unknown += 1
        elif reference <= 0:
            nonpositive += 1
        else:
            benefits.append(100.0 * (reference - actual) / reference)
    positive = np.maximum(benefits, 0.0)
    total = float(positive.sum())
    n = len(benefits)
    # Sorted-rank identity, avoiding the legacy pairwise matrix.
    ordered = np.sort(positive)
    gini = (
        float(np.dot(2 * np.arange(1, n + 1) - n - 1, ordered) / (n * total))
        if total > 0
        else None
    )
    return dict(
        population_members_count=float(len(costs)),
        eligible_members_count=float(n),
        excluded_nonpositive_reference_count=float(nonpositive),
        excluded_unknown_cost_count=float(unknown),
        coverage_ratio=ratio(n, len(costs)),
        losers_percent=ratio(100.0 * sum(v < 0 for v in benefits), n),
        positive_benefit_gini_ratio=gini,
        positive_benefit_top20_ratio=float(
            np.sort(positive)[-max(1, ceil(0.2 * n)) :].sum() / total
        )
        if total > 0
        else None,
    )
