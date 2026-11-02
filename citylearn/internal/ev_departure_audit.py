"""Additive departure-quality KPIs; legacy feasibility keeps its old contract."""
from collections import Counter

import numpy as np

from citylearn.energy_model import Battery


DEFINITION_VERSION = 'ev-departure-audit-v1'
THRESHOLDS = ('target', 'min_acceptable', 'within_tolerance')
# A departure receives the first applicable reason, so reason counts reconcile.
UNKNOWN_REASONS = (
    'missing_target', 'missing_ev', 'missing_battery', 'invalid_capacity',
    'invalid_charger_power', 'invalid_charger_efficiency', 'invalid_time_step', 'missing_arrival_soc',
    'unsupported_battery_model', 'invalid_battery_parameters',
    'outage_supply_not_replayed',
)


def empty_counts():
    counts = Counter(departures_count=0, service_observed_count=0, service_unknown_count=0)
    for threshold in THRESHOLDS:
        for suffix in ('feasible', 'infeasible', 'unknown', 'service_met',
                       'feasible_service_observed', 'feasible_service_met'):
            counts[f'{threshold}_{suffix}_count'] = 0
        for reason in UNKNOWN_REASONS:
            counts[f'{threshold}_unknown_{reason}_count'] = 0
    return counts


def metrics(counts):
    result = dict(counts)
    total = counts['departures_count']
    observed = counts['service_observed_count']
    result['service_coverage_ratio'] = observed / total if total else None
    for threshold in THRESHOLDS:
        known = counts[f'{threshold}_feasible_count'] + counts[f'{threshold}_infeasible_count']
        feasible_observed = counts[f'{threshold}_feasible_service_observed_count']
        result[f'{threshold}_coverage_ratio'] = known / total if total else None
        result[f'{threshold}_service_observed_ratio'] = (
            counts[f'{threshold}_service_met_count'] / observed if observed else None)
        result[f'{threshold}_service_feasible_ratio'] = (
            counts[f'{threshold}_feasible_service_met_count'] / feasible_observed
            if feasible_observed else None)
    return result


def arrival_soc(service, sim, battery, states, start):
    """Use a boundary value, never the post-action SOC being judged."""
    value = service._safe_sequence_value
    candidates = [value(getattr(sim, 'electric_vehicle_current_soc', None), start)]
    estimated = getattr(sim, 'electric_vehicle_estimated_soc_arrival', None)
    ids = getattr(sim, 'electric_vehicle_id', None)
    if start > 0 and states[start - 1] in (2, 3):
        previous = service._normal_ev_id(value(ids, start - 1))
        current = service._normal_ev_id(value(ids, start))
        if previous is None or current is None or previous == current:
            candidates.append(value(estimated, start - 1))
    candidates.append(value(estimated, start))
    if start == 0:
        candidates.append(getattr(battery, 'initial_soc', None))
    for candidate in candidates:
        normalized = service._normalize_soc_target(candidate)
        if normalized is not None:
            return normalized
    return None


def connected_start(service, charger, sim, ev, states, step):
    """Intersect the scheduled session with the actually observed connection."""
    start = service._ev_connected_interval_start(sim, states, step)
    value = service._safe_sequence_value
    history = getattr(charger, 'past_connected_evs', None)
    countdown = getattr(sim, 'electric_vehicle_departure_time', None)
    sessions = getattr(sim, 'electric_vehicle_session_id', None)
    for t in range(start, step):
        if value(history, t) is not ev:
            start = t + 1
        previous = service._to_scalar(value(countdown, t), np.nan)
        following = service._to_scalar(value(countdown, t + 1), np.nan)
        if (service._normal_ev_id(value(sessions, t)) is None
                and service._normal_ev_id(value(sessions, t + 1)) is None
                and 0. <= previous <= 1. + service.EV_DEPARTURE_EPS
                and following > previous + service.EV_DEPARTURE_EPS):
            start = t + 1
    return start


def prerequisites(service, charger, sim, ev, states, start, target):
    if target is None:
        return 'missing_target', None
    if ev is None:
        return 'missing_ev', None
    battery = getattr(ev, 'battery', None)
    if battery is None:
        return 'missing_battery', None
    number = service._to_scalar
    capacity = number(getattr(battery, 'capacity', None), np.nan)
    if not np.isfinite(capacity) or capacity <= 0:
        return 'invalid_capacity', None
    power = number(getattr(charger, 'max_charging_power', None), np.nan)
    if not np.isfinite(power) or power < 0:
        return 'invalid_charger_power', None
    efficiency = number(getattr(charger, 'efficiency', None), np.nan)
    if not np.isfinite(efficiency) or not 0. <= efficiency <= 1.:
        return 'invalid_charger_efficiency', None
    seconds = number(getattr(charger, 'seconds_per_time_step',
                             getattr(battery, 'seconds_per_time_step',
                                     getattr(service.env, 'seconds_per_time_step', None))), np.nan)
    if not np.isfinite(seconds) or seconds <= 0:
        return 'invalid_time_step', None
    initial = arrival_soc(service, sim, battery, states, start)
    if initial is None:
        return 'missing_arrival_soc', None
    if not isinstance(battery, Battery):
        return 'unsupported_battery_model', None
    # Native models supply these parameters. Do not certify a broken model via
    # the permissive fallback used by the historical adapter implementation.
    for name, lower, upper in (
        ('nominal_power', 0., np.inf), ('efficiency', 0., 1.),
        ('loss_coefficient', 0., 1.), ('max_soc', 0., 1.),
    ):
        # Battery has a fixed upper SOC of 1; InventoryBattery exposes max_soc.
        v = number(getattr(battery, name, 1. if name == 'max_soc' else None), np.nan)
        if not np.isfinite(v) or not lower <= v <= upper:
            return 'invalid_battery_parameters', None
    return None, initial


def record_departure(service, counts, building, charger, sim, ev, states, step, target):
    topology = getattr(service.env, '_topology_service', None)
    active = getattr(topology, 'active_chargers_at', None)
    if getattr(service.env, 'topology_mode', 'static') == 'dynamic' and callable(active):
        if not any(candidate is charger for candidate in active(step, building.name).values()):
            # Reinstalled assets have distinct instances with the same schedule.
            # Their inactive scheduled departures are not missing observations.
            return
    counts['departures_count'] += 1
    battery = getattr(ev, 'battery', None)
    actual = service._to_scalar(service._safe_sequence_value(
        getattr(battery, 'soc', None), step), np.nan)
    observed = target is not None and np.isfinite(actual) and 0. <= actual <= 1.
    counts['service_observed_count' if observed else 'service_unknown_count'] += 1
    start = connected_start(service, charger, sim, ev, states, step)
    reason, initial = prerequisites(service, charger, sim, ev, states, start, target)
    outage = any(service._ev_power_outage_at_step(building, t) for t in range(start, step + 1))
    tolerances = (0., service._ev_departure_service_tolerance(), service._ev_departure_within_tolerance())
    for label, tolerance in zip(THRESHOLDS, tolerances):
        met = observed and (abs(actual - target) <= tolerance + service.EV_DEPARTURE_EPS
                           if label == 'within_tolerance'
                           else actual + tolerance + service.EV_DEPARTURE_EPS >= target)
        counts[f'{label}_service_met_count'] += int(met)
        unknown = reason
        feasible = None
        if unknown is None:
            feasible = service._ev_departure_threshold_feasible(
                building, charger, sim, ev, states, step, max(target - tolerance, 0.),
                audit_arrival_soc=initial, audit_interval_start=start, audit=True)
            if feasible is None:
                unknown = 'invalid_battery_parameters'
            elif not feasible and outage:
                # Zero outage charging is a conservative sufficient test only:
                # runtime may use local PV/storage. A failure is not proof that
                # the target was impossible without a joint supply replay.
                unknown = 'outage_supply_not_replayed'
        status = 'unknown' if unknown else 'feasible' if feasible else 'infeasible'
        counts[f'{label}_{status}_count'] += 1
        if unknown:
            counts[f'{label}_unknown_{unknown}_count'] += 1
        elif feasible and observed:
            counts[f'{label}_feasible_service_observed_count'] += 1
            counts[f'{label}_feasible_service_met_count'] += int(met)
