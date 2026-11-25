"""Opt-in EV battery state-of-health, degradation, and equivalent-cycle KPIs."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from citylearn.internal.kpi_population import current_population

if TYPE_CHECKING:
    from citylearn.internal.kpi import CityLearnKPIService


def _battery_step_series(
    battery: object,
    executed_steps: int,
) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(nominal_cap_kwh, degraded_after_step, fade_per_step, throughput_per_step)`` over ``[0, executed_steps)``."""
    empty = np.zeros(0, dtype='float64')
    if battery is None:
        return 0.0, empty, empty, empty

    cap = float(getattr(battery, 'capacity', 0.0) or 0.0)
    if not math.isfinite(cap) or cap <= 0.0:
        return 0.0, empty, empty, empty

    if executed_steps <= 0:
        return cap, empty, empty, empty

    degraded_current = float(getattr(battery, 'degraded_capacity', cap))
    if not math.isfinite(degraded_current):
        degraded_current = cap
    degraded_current = float(np.clip(degraded_current, 0.0, cap))

    before = getattr(battery, 'capacity_before_step', None)
    battery_t = getattr(battery, 'time_step', None)
    after = np.full(executed_steps, np.nan, dtype='float64')
    if before is not None and len(before) > 1:
        limit_s = len(before) - 1 if battery_t is None else min(len(before) - 1, int(battery_t))
        copy_count = min(executed_steps, max(limit_s, 0))
        if copy_count > 0:
            after[:copy_count] = np.asarray(before[1:copy_count + 1], dtype='float64')

    next_valid = degraded_current
    for idx in range(executed_steps - 1, -1, -1):
        if np.isfinite(after[idx]):
            after[idx] = float(np.clip(after[idx], 0.0, cap))
            next_valid = after[idx]
        else:
            after[idx] = next_valid

    c0 = cap
    if before is not None and len(before) > 0 and np.isfinite(before[0]):
        c0 = float(np.clip(float(before[0]), 0.0, cap))

    prev = np.empty(executed_steps, dtype='float64')
    prev[0] = c0
    if executed_steps > 1:
        prev[1:] = after[:-1]
    fade_per_step = np.maximum(0.0, prev - after)

    throughput = np.zeros(executed_steps, dtype='float64')
    charge = getattr(battery, 'gross_energy_charge', None)
    discharge = getattr(battery, 'gross_energy_discharge', None)
    if charge is not None and discharge is not None:
        nc = min(executed_steps, len(charge))
        if nc > 0:
            c_arr = np.asarray(charge[:nc], dtype='float64')
            throughput[:nc] += np.where(np.isfinite(c_arr), np.maximum(c_arr, 0.0), 0.0)
        nd = min(executed_steps, len(discharge))
        if nd > 0:
            d_arr = np.asarray(discharge[:nd], dtype='float64')
            throughput[:nd] += np.where(np.isfinite(d_arr), np.maximum(d_arr, 0.0), 0.0)
    else:
        balances = getattr(battery, 'energy_balance', None)
        if balances is not None:
            nb = min(executed_steps, len(balances))
            if nb > 0:
                b_arr = np.asarray(balances[:nb], dtype='float64')
                throughput[:nb] = np.where(np.isfinite(b_arr), np.abs(b_arr), 0.0)

    return cap, after, fade_per_step, throughput


def _active_executed_steps(
    kpi: "CityLearnKPIService",
    building,
    t_start: int,
    t_end_raw: int,
    executed_steps: int,
) -> Iterable[int]:
    """Return executed step indices ``t`` in ``[t_start, min(t_end_raw, executed_steps - 1)]`` where ``building`` was active."""
    if executed_steps <= 0 or t_end_raw < t_start:
        return ()

    lo = max(int(t_start), 0)
    hi = min(int(t_end_raw), executed_steps - 1)
    if hi < lo:
        return ()

    env = kpi.env
    if getattr(env, 'topology_mode', 'static') != 'dynamic':
        return range(lo, hi + 1)

    population = current_population(kpi)
    if population is not None:
        mask = population.mask(building.name, executed_steps, energy=True)
        return [t for t in range(lo, hi + 1) if bool(mask[t])]

    topology_service = getattr(env, '_topology_service', None)
    if topology_service is not None and hasattr(topology_service, 'active_member_ids_at'):
        return [t for t in range(lo, hi + 1) if building.name in topology_service.active_member_ids_at(t)]

    return range(lo, hi + 1)


def _eligible_district_evs(env, realized_evs: Sequence[object]) -> List[object]:
    """Return unique eligible EVs in the district fleet (counted at most once, ``capacity > 0``)."""
    topology = getattr(env, '_topology_service', None)
    if getattr(env, 'topology_mode', 'static') == 'dynamic' and topology is not None:
        ev_pool = getattr(topology, 'ev_pool', {}) or {}
        ev_order = getattr(topology, '_ev_order', list(ev_pool.keys()))
        started = set(getattr(topology, '_started_ev_ids', set()) or set())
        candidates: List[object] = [
            ev_pool[ev_id] for ev_id in ev_order if ev_id in started and ev_id in ev_pool
        ]
        candidates.extend(getattr(env, 'electric_vehicles', None) or [])
        candidates.extend(getattr(topology, 'suspended_evs', None) or ())
        candidates.extend(realized_evs)
    else:
        candidates = list(getattr(env, 'electric_vehicles', None) or [])
        candidates.extend(realized_evs)

    unique_evs: List[object] = []
    seen_ids = set()
    seen_names = set()
    for ev in candidates:
        if ev is None or id(ev) in seen_ids:
            continue
        ev_name = getattr(ev, 'name', None)
        if isinstance(ev_name, str) and ev_name.strip() != '':
            if ev_name in seen_names:
                continue
            seen_names.add(ev_name)
        battery = getattr(ev, 'battery', None)
        cap = float(getattr(battery, 'capacity', 0.0) or 0.0)
        if battery is None or not math.isfinite(cap) or cap <= 0.0:
            continue
        seen_ids.add(id(ev))
        unique_evs.append(ev)

    return unique_evs


def compute_battery_health_audit_records(
    kpi: "CityLearnKPIService",
    *,
    kpi_buildings: Sequence,
    building_windows: Mapping[str, Tuple[int, int]],
) -> Tuple[List[Dict[str, object]], float]:
    """Compute opt-in EV battery health and wear KPI rows and district EV nominal capacity."""
    env = kpi.env
    executed_steps = max(int(getattr(env, 'time_step', 0) or 0), 0)

    rows: List[Dict[str, object]] = []

    def add(level: str, name: str, cost_function: str, value) -> None:
        rows.append({
            'cost_function': cost_function,
            'value': value,
            'name': name,
            'level': level,
        })

    series_cache: Dict[int, Tuple[float, np.ndarray, np.ndarray, np.ndarray]] = {}

    def get_ev_series(battery: object) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
        key = id(battery)
        if key not in series_cache:
            series_cache[key] = _battery_step_series(battery, executed_steps)
        return series_cache[key]

    realized_district_evs: List[object] = []
    claimed_ev_step = set()

    for building in kpi_buildings:
        b_name = str(building.name)
        t_start, t_end_raw = building_windows.get(b_name, (0, -1))

        chargers = list(kpi._chargers_for_metrics(building))
        last_connection_by_ev: Dict[int, Tuple[float, float]] = {}
        building_ev_fade_kwh = 0.0
        building_ev_throughput_kwh = 0.0

        if chargers:
            for t in _active_executed_steps(kpi, building, t_start, t_end_raw, executed_steps):
                for charger in chargers:
                    past_evs = getattr(charger, 'past_connected_evs', None)
                    ev = past_evs[t] if (past_evs is not None and t < len(past_evs)) else None
                    if ev is None:
                        continue
                    battery = getattr(ev, 'battery', None)
                    cap, after, fade_per_step, throughput_per_step = get_ev_series(battery)
                    if cap <= 0.0 or t >= len(after):
                        continue

                    realized_district_evs.append(ev)
                    last_connection_by_ev[id(ev)] = (cap, float(after[t]))
                    ev_step_key = (id(ev), t)
                    if ev_step_key not in claimed_ev_step:
                        claimed_ev_step.add(ev_step_key)
                        building_ev_fade_kwh += float(fade_per_step[t])
                        building_ev_throughput_kwh += float(throughput_per_step[t])

        b_ev_soh: Optional[float]
        b_ev_fade_ratio: Optional[float]
        b_ev_efc: Optional[float]
        if not last_connection_by_ev:
            b_ev_soh = None
            b_ev_fade_kwh = 0.0
            b_ev_fade_ratio = None
            b_ev_efc = None
        else:
            b_ev_cap_total = sum(cap for cap, _ in last_connection_by_ev.values())
            b_ev_last_degraded_total = sum(last_deg for _, last_deg in last_connection_by_ev.values())
            b_ev_soh = float(np.clip(b_ev_last_degraded_total / b_ev_cap_total, 0.0, 1.0))
            b_ev_fade_kwh = float(max(0.0, building_ev_fade_kwh))
            b_ev_fade_ratio = float(np.clip(b_ev_fade_kwh / b_ev_cap_total, 0.0, 1.0))
            b_ev_efc = float(max(0.0, building_ev_throughput_kwh) / (2.0 * b_ev_cap_total))

        add('building', b_name, 'building_ev_battery_health_terminal_soh_ratio', b_ev_soh)
        add('building', b_name, 'building_ev_battery_health_capacity_fade_kwh', b_ev_fade_kwh)
        add('building', b_name, 'building_ev_battery_health_capacity_fade_ratio', b_ev_fade_ratio)
        add('building', b_name, 'building_ev_battery_health_equivalent_full_cycles_count', b_ev_efc)

    eligible_evs = _eligible_district_evs(env, realized_district_evs)
    d_ev_cap_kwh = 0.0
    d_ev_degraded_kwh = 0.0
    d_ev_fade_kwh = 0.0
    d_ev_throughput_kwh = 0.0

    for ev in eligible_evs:
        battery = getattr(ev, 'battery', None)
        cap, after, fade_per_step, throughput_per_step = get_ev_series(battery)
        if cap <= 0.0:
            continue
        d_ev_cap_kwh += cap
        if executed_steps <= 0 or len(after) == 0:
            d_ev_degraded_kwh += cap
        else:
            d_ev_degraded_kwh += float(after[-1])
            d_ev_fade_kwh += float(fade_per_step.sum())
            d_ev_throughput_kwh += float(throughput_per_step.sum())

    d_ev_soh: Optional[float]
    d_ev_fade_ratio: Optional[float]
    d_ev_efc: Optional[float]
    if d_ev_cap_kwh <= 0.0:
        d_ev_soh = None
        d_ev_fade_ratio = None
        d_ev_efc = None
        d_ev_fade_kwh_out = 0.0
    else:
        d_ev_soh = float(np.clip(d_ev_degraded_kwh / d_ev_cap_kwh, 0.0, 1.0))
        d_ev_fade_kwh_out = float(max(0.0, d_ev_fade_kwh))
        d_ev_fade_ratio = float(np.clip(d_ev_fade_kwh_out / d_ev_cap_kwh, 0.0, 1.0))
        d_ev_efc = float(max(0.0, d_ev_throughput_kwh) / (2.0 * d_ev_cap_kwh))

    add('district', 'District', 'district_ev_battery_health_terminal_soh_ratio', d_ev_soh)
    add('district', 'District', 'district_ev_battery_health_capacity_fade_kwh', d_ev_fade_kwh_out)
    add('district', 'District', 'district_ev_battery_health_capacity_fade_ratio', d_ev_fade_ratio)
    add('district', 'District', 'district_ev_battery_health_equivalent_full_cycles_count', d_ev_efc)

    return rows, float(d_ev_cap_kwh)
