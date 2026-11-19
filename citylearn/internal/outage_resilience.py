"""Per-outage-event service resilience audit built on `service_energy.py`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from citylearn.data import ZERO_DIVISION_PLACEHOLDER

if TYPE_CHECKING:
    from citylearn.internal.kpi import CityLearnKPIService

DEFINITION_VERSION = 'outage-resilience-audit-v1'
END_USES: Tuple[str, ...] = ('cooling', 'heating', 'dhw', 'non_shiftable')
FULL_SERVICE_EPS_KWH = 1.0e-9

EVENT_COLUMNS: Tuple[str, ...] = (
    'building',
    'event_index',
    'start_time_step',
    'end_time_step',
    'duration_steps',
    'duration_hours',
    'expected_energy_kwh',
    'served_energy_kwh',
    'unserved_energy_kwh',
    'unserved_energy_ratio',
    'peak_unserved_power_kw',
    'fully_served',
    'cooling_expected_energy_kwh',
    'cooling_served_energy_kwh',
    'cooling_unserved_energy_kwh',
    'heating_expected_energy_kwh',
    'heating_served_energy_kwh',
    'heating_unserved_energy_kwh',
    'dhw_expected_energy_kwh',
    'dhw_served_energy_kwh',
    'dhw_unserved_energy_kwh',
    'non_shiftable_expected_energy_kwh',
    'non_shiftable_served_energy_kwh',
    'non_shiftable_unserved_energy_kwh',
)

SUMMARY_COLUMNS: Tuple[str, ...] = (
    'level',
    'name',
    'events_count',
    'fully_served_events_count',
    'fully_served_events_ratio',
    'outage_steps_count',
    'outage_hours',
    'expected_energy_kwh',
    'served_energy_kwh',
    'unserved_energy_kwh',
    'unserved_energy_ratio',
    'worst_event_unserved_energy_kwh',
    'peak_unserved_power_kw',
    'cooling_expected_energy_kwh',
    'cooling_served_energy_kwh',
    'cooling_unserved_energy_kwh',
    'heating_expected_energy_kwh',
    'heating_served_energy_kwh',
    'heating_unserved_energy_kwh',
    'dhw_expected_energy_kwh',
    'dhw_served_energy_kwh',
    'dhw_unserved_energy_kwh',
    'non_shiftable_expected_energy_kwh',
    'non_shiftable_served_energy_kwh',
    'non_shiftable_unserved_energy_kwh',
)


def metadata() -> Dict[str, Any]:
    return dict(
        definition_version=DEFINITION_VERSION,
        topology_support='static',
        interval_boundary='executed_active_intervals',
        event_definition='maximal_consecutive_steps_with_positive_power_outage_signal',
        service_energy='cooling, heating, dhw and non_shiftable_load from service_energy.py; component shortfalls never cancel',
        zero_denominator=None,
    )


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    if denominator <= float(ZERO_DIVISION_PLACEHOLDER):
        return None
    return float(numerator / denominator)


def _contiguous_runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    """Return inclusive `(start, end)` indices of True runs in 1-D boolean `mask`."""
    if mask.size == 0 or not np.any(mask):
        return []
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    transitions = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(start), int(end - 1)) for start, end in zip(transitions[0::2], transitions[1::2])]


def _clean_service_arrays(
    expected_raw: np.ndarray,
    served_raw: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sanitize and cap per-end-use service energy to match `CostFunction.normalized_unserved_energy`."""
    if expected_raw.size == 0:
        empty = np.zeros((0, len(END_USES)), dtype='float64')
        return empty, empty, empty

    expected = np.asarray(expected_raw, dtype='float64').reshape(-1, len(END_USES))
    served = np.asarray(served_raw, dtype='float64').reshape(-1, len(END_USES))
    expected = np.where(np.isfinite(expected), np.maximum(expected, 0.0), 0.0)
    served = np.where(np.isfinite(served), np.maximum(served, 0.0), 0.0)
    served = np.minimum(expected, served)
    unserved = np.maximum(expected - served, 0.0)
    return expected, served, unserved


def _end_use_totals(
    expected: np.ndarray,
    served: np.ndarray,
    unserved: np.ndarray,
) -> Dict[str, float]:
    totals: Dict[str, float] = {}
    for col, end_use in enumerate(END_USES):
        totals[f'{end_use}_expected_energy_kwh'] = float(expected[:, col].sum()) if expected.size else 0.0
        totals[f'{end_use}_served_energy_kwh'] = float(served[:, col].sum()) if served.size else 0.0
        totals[f'{end_use}_unserved_energy_kwh'] = float(unserved[:, col].sum()) if unserved.size else 0.0
    return totals


def _summarize_events(
    events: Sequence[Mapping[str, Any]],
    *,
    step_hours: float,
    peak_unserved_power_kw: Optional[float] = None,
) -> Dict[str, Any]:
    events_count = len(events)
    fully_served_count = sum(1 for event in events if event['fully_served'])
    outage_steps = sum(int(event['duration_steps']) for event in events)
    expected_total = float(sum(float(event['expected_energy_kwh']) for event in events))
    served_total = float(sum(float(event['served_energy_kwh']) for event in events))
    unserved_total = float(sum(float(event['unserved_energy_kwh']) for event in events))
    worst_event_unserved = max((float(event['unserved_energy_kwh']) for event in events), default=0.0)
    max_event_peak_kw = max((float(event['peak_unserved_power_kw']) for event in events), default=0.0)

    summary: Dict[str, Any] = dict(
        events_count=int(events_count),
        fully_served_events_count=int(fully_served_count),
        fully_served_events_ratio=float(fully_served_count / events_count) if events_count > 0 else None,
        outage_steps_count=int(outage_steps),
        outage_hours=float(outage_steps * step_hours),
        expected_energy_kwh=expected_total,
        served_energy_kwh=served_total,
        unserved_energy_kwh=unserved_total,
        unserved_energy_ratio=_ratio(unserved_total, expected_total),
        worst_event_unserved_energy_kwh=float(worst_event_unserved),
        peak_unserved_power_kw=float(max_event_peak_kw if peak_unserved_power_kw is None else peak_unserved_power_kw),
    )
    for end_use in END_USES:
        for kind in ('expected', 'served', 'unserved'):
            key = f'{end_use}_{kind}_energy_kwh'
            summary[key] = float(sum(float(event[key]) for event in events))
    return summary


def environment_audit(service: "CityLearnKPIService") -> Dict[str, Any]:
    """Compute per-event, per-building and district outage resilience metrics."""
    env = service.env
    if getattr(env, 'topology_mode', 'static') == 'dynamic':
        raise NotImplementedError(
            "Per-outage-event resilience metrics currently support static topology only "
            "(topology_mode='static')."
        )

    step_seconds = max(float(getattr(env, 'seconds_per_time_step', 3600.0) or 3600.0), 1.0)
    step_hours = step_seconds / 3600.0
    executed_steps = max(int(getattr(env, 'time_step', 0) or 0), 0)

    all_events: List[Dict[str, Any]] = []
    buildings_summary: Dict[str, Dict[str, Any]] = {}
    district_outage_mask = np.zeros(executed_steps, dtype=bool)
    district_active_buildings_per_step = np.zeros(executed_steps, dtype=int)
    district_expected_per_step = np.zeros((executed_steps, len(END_USES)), dtype='float64')
    district_served_per_step = np.zeros((executed_steps, len(END_USES)), dtype='float64')
    district_unserved_per_step = np.zeros((executed_steps, len(END_USES)), dtype='float64')
    building_masks: Dict[str, np.ndarray] = {}

    for building in service._get_kpi_buildings():
        t_start, t_end = service._building_active_window(building)
        if executed_steps == 0 or t_end < t_start:
            buildings_summary[building.name] = _summarize_events((), step_hours=step_hours)
            continue

        raw_signal = service._thermal_values(building, building.power_outage_signal, t_start, t_end)
        expected_raw, served_raw = service._service_energy(building, t_start, t_end)
        length = min(len(raw_signal), len(expected_raw), executed_steps)

        if length <= 0 or not bool(getattr(building, 'simulate_power_outage', True)):
            buildings_summary[building.name] = _summarize_events((), step_hours=step_hours)
            continue

        signal = np.asarray(raw_signal[:length], dtype='float64')
        outage_mask = np.isfinite(signal) & (signal > 0.0)
        expected, served, unserved = _clean_service_arrays(expected_raw[:length], served_raw[:length])

        offset = max(int(t_start), 0)
        end_idx = min(offset + length, executed_steps)
        span_len = max(end_idx - offset, 0)
        if span_len > 0:
            active_slice = outage_mask[:span_len]
            full_mask = np.zeros(executed_steps, dtype=bool)
            full_mask[offset:end_idx] = active_slice
            building_masks[building.name] = full_mask
            district_outage_mask[offset:end_idx] |= active_slice
            district_active_buildings_per_step[offset:end_idx] += active_slice.astype(int)
            district_expected_per_step[offset:end_idx] += np.where(active_slice[:, None], expected[:span_len], 0.0)
            district_served_per_step[offset:end_idx] += np.where(active_slice[:, None], served[:span_len], 0.0)
            district_unserved_per_step[offset:end_idx] += np.where(active_slice[:, None], unserved[:span_len], 0.0)

        building_events: List[Dict[str, Any]] = []
        for event_index, (run_start, run_end) in enumerate(_contiguous_runs(outage_mask)):
            sl = slice(run_start, run_end + 1)
            ev_expected = expected[sl]
            ev_served = served[sl]
            ev_unserved = unserved[sl]
            step_unserved = ev_unserved.sum(axis=1)
            expected_kwh = float(ev_expected.sum())
            served_kwh = float(ev_served.sum())
            unserved_kwh = float(step_unserved.sum())
            duration_steps = int(run_end - run_start + 1)
            peak_kw = float(np.max(step_unserved) / step_hours) if step_unserved.size else 0.0

            record: Dict[str, Any] = dict(
                building=building.name,
                event_index=int(event_index),
                start_time_step=int(offset + run_start),
                end_time_step=int(offset + run_end),
                duration_steps=duration_steps,
                duration_hours=float(duration_steps * step_hours),
                expected_energy_kwh=expected_kwh,
                served_energy_kwh=served_kwh,
                unserved_energy_kwh=unserved_kwh,
                unserved_energy_ratio=_ratio(unserved_kwh, expected_kwh),
                peak_unserved_power_kw=peak_kw,
                fully_served=bool(unserved_kwh <= FULL_SERVICE_EPS_KWH),
                **_end_use_totals(ev_expected, ev_served, ev_unserved),
            )
            building_events.append(record)

        buildings_summary[building.name] = _summarize_events(building_events, step_hours=step_hours)
        all_events.extend(building_events)

    coincident_events: List[Dict[str, Any]] = []
    for event_index, (run_start, run_end) in enumerate(_contiguous_runs(district_outage_mask)):
        sl = slice(run_start, run_end + 1)
        ev_expected = district_expected_per_step[sl]
        ev_served = district_served_per_step[sl]
        ev_unserved = district_unserved_per_step[sl]
        step_unserved = ev_unserved.sum(axis=1)
        expected_kwh = float(ev_expected.sum())
        served_kwh = float(ev_served.sum())
        unserved_kwh = float(step_unserved.sum())
        duration_steps = int(run_end - run_start + 1)
        affected = [name for name, mask in building_masks.items() if np.any(mask[sl])]
        coincident_events.append(dict(
            event_index=int(event_index),
            start_time_step=int(run_start),
            end_time_step=int(run_end),
            duration_steps=duration_steps,
            duration_hours=float(duration_steps * step_hours),
            affected_buildings=affected,
            affected_buildings_count=int(len(affected)),
            max_simultaneous_buildings_count=int(np.max(district_active_buildings_per_step[sl])),
            expected_energy_kwh=expected_kwh,
            served_energy_kwh=served_kwh,
            unserved_energy_kwh=unserved_kwh,
            unserved_energy_ratio=_ratio(unserved_kwh, expected_kwh),
            peak_unserved_power_kw=float(np.max(step_unserved) / step_hours) if step_unserved.size else 0.0,
            fully_served=bool(unserved_kwh <= FULL_SERVICE_EPS_KWH),
            **_end_use_totals(ev_expected, ev_served, ev_unserved),
        ))

    district_step_unserved_total = district_unserved_per_step.sum(axis=1)
    district_peak_kw = (
        float(np.max(district_step_unserved_total) / step_hours)
        if district_step_unserved_total.size and np.any(district_outage_mask)
        else 0.0
    )
    district_summary = _summarize_events(
        all_events,
        step_hours=step_hours,
        peak_unserved_power_kw=district_peak_kw,
    )
    coincident_fully_served = sum(1 for event in coincident_events if event['fully_served'])
    coincident_steps = int(np.count_nonzero(district_outage_mask))
    district_summary.update(
        max_building_peak_unserved_power_kw=max(
            (float(event['peak_unserved_power_kw']) for event in all_events),
            default=0.0,
        ),
        coincident_events_count=int(len(coincident_events)),
        coincident_fully_served_events_count=int(coincident_fully_served),
        coincident_fully_served_events_ratio=(
            float(coincident_fully_served / len(coincident_events))
            if coincident_events
            else None
        ),
        coincident_outage_steps_count=coincident_steps,
        coincident_outage_hours=float(coincident_steps * step_hours),
        worst_coincident_event_unserved_energy_kwh=max(
            (float(event['unserved_energy_kwh']) for event in coincident_events),
            default=0.0,
        ),
    )

    return dict(
        **metadata(),
        seconds_per_time_step=step_seconds,
        executed_time_steps=executed_steps,
        events=all_events,
        coincident_events=coincident_events,
        buildings=buildings_summary,
        district=district_summary,
    )


def to_dataframes(audit: Mapping[str, Any]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Format an `environment_audit` dictionary as `(events_df, summary_df)`."""
    events = audit.get('events') or []
    events_df = (
        pd.DataFrame([{col: row.get(col) for col in EVENT_COLUMNS} for row in events], columns=EVENT_COLUMNS)
        if events
        else pd.DataFrame(columns=EVENT_COLUMNS)
    )

    summary_rows: List[Dict[str, Any]] = []
    for building_name, totals in (audit.get('buildings') or {}).items():
        row = {'level': 'building', 'name': building_name}
        for col in SUMMARY_COLUMNS[2:]:
            row[col] = totals.get(col)
        summary_rows.append(row)

    district_totals = audit.get('district') or {}
    district_row: Dict[str, Any] = {'level': 'district', 'name': 'District'}
    for col in SUMMARY_COLUMNS[2:]:
        district_row[col] = district_totals.get(col)
    summary_rows.append(district_row)

    summary_df = pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS)
    return events_df, summary_df
