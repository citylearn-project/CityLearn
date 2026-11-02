"""Equipment KPI calculations and per-evaluation aggregation.

Each accumulator belongs to one evaluate() call. EV counts, BESS capacities and
phase samples retain their own denominators; district ratios are never averages
of per-member ratios.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from citylearn.internal.evaluation_progress import run
from citylearn.internal import ev_departure_audit

if TYPE_CHECKING:
    from citylearn.internal.kpi import CityLearnKPIService


def compute_bess_metrics(kpi, building, *, t_start: int = 0, t_final: Optional[int] = None) -> Dict[str, float]:
    upper = int(max(building.time_step, 0))
    t_start = int(max(t_start, 0))
    t_final = upper if t_final is None else int(min(max(t_final, 0), upper))
    if t_final < t_start:
        capacity = kpi._to_scalar(getattr(getattr(building, 'electrical_storage', None), 'capacity', 0.0), 0.0)
        return {
            'bess_charge_total_kwh': 0.0,
            'bess_discharge_total_kwh': 0.0,
            'bess_throughput_total_kwh': 0.0,
            'bess_equivalent_full_cycles': None,
            'bess_capacity_fade_ratio': None,
            '_bess_capacity_kwh': capacity,
            '_bess_degraded_capacity_kwh': capacity,
        }

    storages = [
        storage for storage in kpi._storages_for_metrics(building)
        if kpi._to_scalar(getattr(storage, 'capacity', 0.0), 0.0) > 0.0
    ]
    charge_series, discharge_series = [], []
    for storage in storages:
        values = getattr(storage, 'electricity_consumption', None)
        if values is None and len(storages) == 1:
            # Compatibility for legacy/custom building facades that expose
            # only the aggregate storage series on the building.
            values = getattr(
                building,
                'electrical_storage_electricity_consumption',
                [],
            )
        charge = getattr(storage, 'gross_energy_charge', None)
        discharge = getattr(storage, 'gross_energy_discharge', None)
        charge_series.append(kpi._slice_window(charge if charge is not None else np.clip(values, 0., None), t_start, t_final))
        discharge_series.append(kpi._slice_window(discharge if discharge is not None else np.clip(-np.asarray(values), 0., None), t_start, t_final))
    charge_total = sum(kpi._sum_finite(values) for values in charge_series)
    discharge_total = sum(kpi._sum_finite(values) for values in discharge_series)
    throughput_total = charge_total + discharge_total

    capacity = sum(
        kpi._to_scalar(getattr(storage, 'capacity', 0.0), 0.0)
        for storage in storages
    )
    degraded_capacity = sum(
        kpi._to_scalar(
            getattr(storage, 'degraded_capacity', getattr(storage, 'capacity', 0.0)),
            kpi._to_scalar(getattr(storage, 'capacity', 0.0), 0.0),
        )
        for storage in storages
    )
    equivalent_cycles = None if capacity <= 0.0 else throughput_total / (2.0 * capacity)
    fade_ratio = None if capacity <= 0.0 else (capacity - degraded_capacity) / capacity

    if fade_ratio is not None:
        fade_ratio = float(np.clip(fade_ratio, 0.0, 1.0))

    return {
        'bess_charge_total_kwh': charge_total,
        'bess_discharge_total_kwh': discharge_total,
        'bess_throughput_total_kwh': throughput_total,
        'bess_equivalent_full_cycles': equivalent_cycles,
        'bess_capacity_fade_ratio': fade_ratio,
        '_bess_capacity_kwh': capacity,
        '_bess_degraded_capacity_kwh': degraded_capacity,
    }


def compute_pv_metrics(kpi, building, *, t_start: int = 0, t_final: Optional[int] = None) -> Dict[str, float]:
    upper = int(max(building.time_step, 0))
    t_start = int(max(t_start, 0))
    t_final = upper if t_final is None else int(min(max(t_final, 0), upper))
    if t_final < t_start:
        return {
            'pv_curtailment_total_kwh': 0.0,
            'pv_generation_total_kwh': 0.0,
            'pv_export_total_kwh': 0.0,
            'pv_self_consumption_ratio': None,
        }

    solar = np.array(kpi._energy_values(building, building.solar_generation)[t_start:t_final + 1], dtype='float64')
    net = np.array(kpi._energy_values(building, building.net_electricity_consumption)[t_start:t_final + 1], dtype='float64')

    curtailment = kpi._energy_values(building, getattr(building, 'pv_curtailment', np.zeros_like(building.solar_generation)))[t_start:t_final + 1]
    generation = np.clip(-solar, 0.0, None)
    export = np.clip(-net, 0.0, None)
    pv_generation_total = kpi._sum_finite(generation)
    pv_export_total = kpi._sum_finite(np.minimum(generation, export))
    self_consumption_ratio = None if pv_generation_total <= 0.0 else (pv_generation_total - pv_export_total - kpi._sum_finite(curtailment)) / pv_generation_total

    return {
        'pv_curtailment_total_kwh': kpi._sum_finite(curtailment),
        'pv_generation_total_kwh': pv_generation_total,
        'pv_export_total_kwh': pv_export_total,
        'pv_self_consumption_ratio': self_consumption_ratio,
    }


def compute_district_pv_metrics(
    kpi,
    buildings: Sequence,
    building_windows: Mapping[str, Tuple[int, int]],
    *,
    final_t: int,
) -> Dict[str, float]:
    series_by_building = []
    for building in buildings:
        t_start, t_end = building_windows.get(building.name, (0, -1))
        if t_end < t_start:
            continue

        series_by_building.append(
            (
                building.name,
                int(t_start),
                int(t_end),
                kpi._energy_values(building, building.solar_generation),
                kpi._energy_values(building, building.net_electricity_consumption),
                kpi._energy_values(building, getattr(building, 'pv_curtailment', np.zeros_like(building.solar_generation))),
            )
        )

    pv_generation_total = 0.0
    pv_export_total = 0.0

    pv_curtailment_total = 0.0
    for t in range(int(max(final_t, 0)) + 1):
        generation_t = 0.0
        district_net_t = 0.0

        curtailment_t = 0.0
        for _, t_start, t_end, solar, net, curtailed in series_by_building:
            if not (t_start <= t <= t_end):
                continue

            solar_value = kpi._to_scalar(solar[t] if t < len(solar) else np.nan, 0.0)
            net_value = kpi._to_scalar(net[t] if t < len(net) else np.nan, 0.0)
            curtailment_t += float(curtailed[t]) if t < len(curtailed) else 0.0
            generation_t += max(-solar_value, 0.0)
            district_net_t += net_value

        pv_generation_total += generation_t
        pv_curtailment_total += curtailment_t
        pv_export_total += min(max(generation_t-curtailment_t,0.0), max(-district_net_t, 0.0))

    self_consumption_ratio = None if pv_generation_total <= 0.0 else (pv_generation_total - pv_export_total - pv_curtailment_total) / pv_generation_total

    return {
        'pv_curtailment_total_kwh': float(pv_curtailment_total),
        'pv_generation_total_kwh': float(pv_generation_total),
        'pv_export_total_kwh': float(pv_export_total),
        'pv_self_consumption_ratio': self_consumption_ratio,
    }


def compute_phase_metrics(kpi, building, *, t_start: int = 0, t_final: Optional[int] = None) -> Dict[str, object]:
    if not getattr(building, '_electrical_service_enabled', False):
        return {
            'electrical_service_violation_total_kwh': 0.0,
            'electrical_service_violation_time_step_count': 0.0,
            'electrical_service_requested_pressure_total_kwh': 0.0,
            'electrical_service_requested_pressure_time_step_count': 0.0,
            'phase_imbalance_ratio_average': None,
            'phase_import_peak_kw': {},
            'phase_export_peak_kw': {},
            '_imbalance_sum': 0.0,
            '_imbalance_count': 0.0,
        }

    upper = int(max(building.time_step, 0))
    t_start = int(max(t_start, 0))
    t_final = upper if t_final is None else int(min(max(t_final, 0), upper))
    if t_final < t_start:
        return {
            'electrical_service_violation_total_kwh': 0.0,
            'electrical_service_violation_time_step_count': 0.0,
            'electrical_service_requested_pressure_total_kwh': 0.0,
            'electrical_service_requested_pressure_time_step_count': 0.0,
            'phase_imbalance_ratio_average': None,
            'phase_import_peak_kw': {},
            'phase_export_peak_kw': {},
            '_imbalance_sum': 0.0,
            '_imbalance_count': 0.0,
        }

    # The constraint penalty records requested-action pressure before
    # projection. It is useful controller feedback, but it is not evidence
    # that post-projection power still violates the declared service limits.
    pressure_history = np.array(
        getattr(building, '_charging_constraint_violation_history', [0.0]),
        dtype='float64',
    )[t_start:t_final + 1]
    requested_pressure_total = float(np.clip(pressure_history, 0.0, None).sum())
    requested_pressure_count = float(np.count_nonzero(pressure_history > 1e-9))

    all_total_history = np.array(
        getattr(building, '_charging_total_power_history_kw', [0.0]),
        dtype='float64',
    )
    total_history = all_total_history[t_start:t_final + 1]
    phase_history = getattr(building, '_charging_phase_power_history_kw', {}) or {}
    total_limits = getattr(building, '_electrical_service_limits', {}).get('total', {}) or {}
    per_phase_limits = getattr(building, '_electrical_service_limits', {}).get('per_phase', {}) or {}
    step_hours = max(
        kpi._to_scalar(getattr(building, 'seconds_per_time_step', 3600.0), 3600.0) / 3600.0,
        0.0,
    )
    residual_violation_kw = np.zeros(len(total_history), dtype='float64')

    def accumulate_limit(values: np.ndarray, limits: Mapping[str, float]) -> None:
        import_limit = kpi._to_scalar(limits.get('import_kw'), np.nan)
        export_limit = kpi._to_scalar(limits.get('export_kw'), np.nan)
        if np.isfinite(import_limit):
            excess = np.clip(values - import_limit, 0.0, None)
            excess[excess <= kpi.ELECTRICAL_RESIDUAL_EPS_KW] = 0.0
            residual_violation_kw[:] += excess
        if np.isfinite(export_limit):
            excess = np.clip(-values - export_limit, 0.0, None)
            excess[excess <= kpi.ELECTRICAL_RESIDUAL_EPS_KW] = 0.0
            residual_violation_kw[:] += excess

    accumulate_limit(total_history, total_limits)
    for phase_name in kpi._electrical_service_phase_names(building):
        full_values = np.array(
            phase_history.get(phase_name, np.zeros(len(all_total_history))),
            dtype='float64',
        )
        values = full_values[t_start:t_final + 1]
        if len(values) != len(residual_violation_kw):
            aligned = np.zeros(len(residual_violation_kw), dtype='float64')
            count = min(len(values), len(aligned))
            aligned[:count] = values[:count]
            values = aligned
        accumulate_limit(values, per_phase_limits.get(phase_name, {}) or {})

    violation_history = residual_violation_kw * step_hours
    violation_total = float(np.clip(violation_history, 0.0, None).sum())
    violation_count = float(np.count_nonzero(violation_history > 1e-9))

    phase_history = getattr(building, '_charging_phase_power_history_kw', {}) or {}
    phase_import_peak = {}
    phase_export_peak = {}

    for phase_name, values in phase_history.items():
        series = np.array(values[t_start:t_final + 1], dtype='float64')
        phase_import_peak[phase_name] = float(np.clip(series, 0.0, None).max(initial=0.0))
        phase_export_peak[phase_name] = float(np.clip(-series, 0.0, None).max(initial=0.0))

    imbalance_sum = 0.0
    imbalance_count = 0.0
    imbalance_average = None

    if getattr(building, '_electrical_service_mode', 'single_phase') == 'three_phase':
        names = [n for n in ['L1', 'L2', 'L3'] if n in phase_history]
        if len(names) == 3:
            stacked = np.stack([np.array(phase_history[n][t_start:t_final + 1], dtype='float64') for n in names], axis=1)
            for row in stacked:
                abs_row = np.abs(row)
                mean_abs = float(abs_row.mean())
                if mean_abs <= 1e-9:
                    ratio = 0.0
                else:
                    ratio = float((abs_row.max() - abs_row.min()) / mean_abs)
                imbalance_sum += ratio
                imbalance_count += 1.0

            if imbalance_count > 0:
                imbalance_average = imbalance_sum / imbalance_count

    return {
        'electrical_service_violation_total_kwh': violation_total,
        'electrical_service_violation_time_step_count': violation_count,
        'electrical_service_requested_pressure_total_kwh': requested_pressure_total,
        'electrical_service_requested_pressure_time_step_count': requested_pressure_count,
        'phase_imbalance_ratio_average': imbalance_average,
        'phase_import_peak_kw': phase_import_peak,
        'phase_export_peak_kw': phase_export_peak,
        '_imbalance_sum': imbalance_sum,
        '_imbalance_count': imbalance_count,
    }


class EquipmentKPIAccumulator:
    def __init__(self, kpi: "CityLearnKPIService"):
        self.kpi = kpi
        self.ev_audit_counts = ev_departure_audit.empty_counts()
        self.ev_departures_total = 0.0
        self.ev_departures_met = 0.0
        self.ev_departures_min_acceptable = 0.0
        self.ev_departures_within_tolerance = 0.0
        self.ev_departures_target_feasible = 0.0
        self.ev_departures_target_infeasible = 0.0
        self.ev_departures_min_acceptable_feasible = 0.0
        self.ev_departures_min_acceptable_infeasible = 0.0
        self.ev_departures_within_tolerance_feasible = 0.0
        self.ev_departures_within_tolerance_infeasible = 0.0
        self.ev_departures_met_target_feasible = 0.0
        self.ev_departures_min_acceptable_feasible_met = 0.0
        self.ev_departures_within_tolerance_feasible_met = 0.0
        self.ev_deficit_sum = 0.0
        self.ev_shortfall_beyond_tolerance_sum = 0.0
        self.ev_surplus_sum = 0.0
        self.ev_absolute_error_sum = 0.0
        self.ev_charge_total = 0.0
        self.ev_v2g_total = 0.0
        self.ev_connected_soc_gain_total = 0.0
        self.ev_energy_accounting_shortfall_total = 0.0

        self.bess_charge_total = 0.0
        self.bess_discharge_total = 0.0
        self.bess_throughput_total = 0.0
        self.bess_capacity_total = 0.0
        self.bess_capacity_loss_total = 0.0

        self.phase_violation_total = 0.0
        self.phase_violation_count = 0.0
        self.phase_requested_pressure_total = 0.0
        self.phase_requested_pressure_count = 0.0
        self.phase_imbalance_sum = 0.0
        self.phase_imbalance_count = 0.0

    def building_records(self, building, t_start, t_end, *, progress=None):
        kpi = self.kpi
        building_days = kpi._building_days(building, t_start, t_end)
        extended_building_rows = []
        ev_metrics = run(progress, 'ev', kpi._compute_ev_metrics, building, t_start=t_start, t_final=t_end)
        self.ev_audit_counts.update(ev_metrics['_departure_audit'])
        extended_building_rows.extend(
            kpi._metric(f'ev_departure_audit_{key}', value, building.name, 'building')
            for key, value in ev_departure_audit.metrics(ev_metrics['_departure_audit']).items()
        )
        extended_building_rows.extend([
            kpi._metric('ev_departure_events_count', ev_metrics['departures_total'], building.name, 'building'),
            kpi._metric('ev_departure_met_events_count', ev_metrics['departures_met'], building.name, 'building'),
            kpi._metric('ev_departure_min_acceptable_events_count', ev_metrics['departures_min_acceptable'], building.name, 'building'),
            kpi._metric('ev_departure_within_tolerance_events_count', ev_metrics['departures_within_tolerance'], building.name, 'building'),
            kpi._metric('ev_departure_target_feasible_events_count', ev_metrics['departures_target_feasible'], building.name, 'building'),
            kpi._metric('ev_departure_target_infeasible_events_count', ev_metrics['departures_target_infeasible'], building.name, 'building'),
            kpi._metric('ev_departure_min_acceptable_feasible_events_count', ev_metrics['departures_min_acceptable_feasible'], building.name, 'building'),
            kpi._metric('ev_departure_min_acceptable_infeasible_events_count', ev_metrics['departures_min_acceptable_infeasible'], building.name, 'building'),
            kpi._metric('ev_departure_within_tolerance_feasible_events_count', ev_metrics['departures_within_tolerance_feasible'], building.name, 'building'),
            kpi._metric('ev_departure_within_tolerance_infeasible_events_count', ev_metrics['departures_within_tolerance_infeasible'], building.name, 'building'),
            kpi._metric('ev_departure_success_rate', ev_metrics['ev_departure_success_rate'], building.name, 'building'),
            kpi._metric('ev_departure_min_acceptable_rate', ev_metrics['ev_departure_min_acceptable_rate'], building.name, 'building'),
            kpi._metric('ev_departure_within_tolerance_rate', ev_metrics['ev_departure_within_tolerance_rate'], building.name, 'building'),
            kpi._metric('ev_departure_success_feasible_rate', ev_metrics['ev_departure_success_feasible_rate'], building.name, 'building'),
            kpi._metric('ev_departure_min_acceptable_feasible_rate', ev_metrics['ev_departure_min_acceptable_feasible_rate'], building.name, 'building'),
            kpi._metric('ev_departure_within_tolerance_feasible_rate', ev_metrics['ev_departure_within_tolerance_feasible_rate'], building.name, 'building'),
            kpi._metric('ev_departure_soc_deficit_mean', ev_metrics['ev_departure_soc_deficit_mean'], building.name, 'building'),
            kpi._metric('ev_departure_shortfall_beyond_tolerance_mean', ev_metrics['ev_departure_shortfall_beyond_tolerance_mean'], building.name, 'building'),
            kpi._metric('ev_departure_soc_surplus_mean', ev_metrics['ev_departure_soc_surplus_mean'], building.name, 'building'),
            kpi._metric('ev_departure_soc_absolute_error_mean', ev_metrics['ev_departure_soc_absolute_error_mean'], building.name, 'building'),
            kpi._metric('ev_departure_tolerance_ratio', ev_metrics['ev_departure_tolerance_ratio'], building.name, 'building'),
            kpi._metric('ev_charge_total_kwh', ev_metrics['ev_charge_total_kwh'], building.name, 'building'),
            kpi._metric('ev_v2g_export_total_kwh', ev_metrics['ev_v2g_export_total_kwh'], building.name, 'building'),
            kpi._metric('ev_connected_soc_gain_total_kwh', ev_metrics['ev_connected_soc_gain_total_kwh'], building.name, 'building'),
            kpi._metric('ev_energy_accounting_shortfall_kwh', ev_metrics['ev_energy_accounting_shortfall_kwh'], building.name, 'building'),
        ])
        self.ev_departures_total += ev_metrics['departures_total']
        self.ev_departures_met += ev_metrics['departures_met']
        self.ev_departures_min_acceptable += ev_metrics['departures_min_acceptable']
        self.ev_departures_within_tolerance += ev_metrics['departures_within_tolerance']
        self.ev_departures_target_feasible += ev_metrics['departures_target_feasible']
        self.ev_departures_target_infeasible += ev_metrics['departures_target_infeasible']
        self.ev_departures_min_acceptable_feasible += ev_metrics['departures_min_acceptable_feasible']
        self.ev_departures_min_acceptable_infeasible += ev_metrics['departures_min_acceptable_infeasible']
        self.ev_departures_within_tolerance_feasible += ev_metrics['departures_within_tolerance_feasible']
        self.ev_departures_within_tolerance_infeasible += ev_metrics['departures_within_tolerance_infeasible']
        self.ev_departures_met_target_feasible += ev_metrics['_departures_met_target_feasible']
        self.ev_departures_min_acceptable_feasible_met += ev_metrics['_departures_min_acceptable_feasible_met']
        self.ev_departures_within_tolerance_feasible_met += ev_metrics['_departures_within_tolerance_feasible_met']
        self.ev_deficit_sum += ev_metrics['departure_deficit_sum']
        self.ev_shortfall_beyond_tolerance_sum += ev_metrics['departure_shortfall_beyond_tolerance_sum']
        self.ev_surplus_sum += ev_metrics['departure_surplus_sum']
        self.ev_absolute_error_sum += ev_metrics['departure_absolute_error_sum']
        self.ev_charge_total += ev_metrics['ev_charge_total_kwh']
        self.ev_v2g_total += ev_metrics['ev_v2g_export_total_kwh']
        self.ev_connected_soc_gain_total += ev_metrics['ev_connected_soc_gain_total_kwh']
        self.ev_energy_accounting_shortfall_total += ev_metrics['ev_energy_accounting_shortfall_kwh']

        bess_metrics = run(progress, 'battery', kpi._compute_bess_metrics, building, t_start=t_start, t_final=t_end)
        extended_building_rows.extend([
            kpi._metric('bess_charge_total_kwh', bess_metrics['bess_charge_total_kwh'], building.name, 'building'),
            kpi._metric('bess_discharge_total_kwh', bess_metrics['bess_discharge_total_kwh'], building.name, 'building'),
            kpi._metric('bess_throughput_total_kwh', bess_metrics['bess_throughput_total_kwh'], building.name, 'building'),
            kpi._metric('bess_equivalent_full_cycles', bess_metrics['bess_equivalent_full_cycles'], building.name, 'building'),
            kpi._metric('bess_capacity_fade_ratio', bess_metrics['bess_capacity_fade_ratio'], building.name, 'building'),
        ])
        self.bess_charge_total += bess_metrics['bess_charge_total_kwh']
        self.bess_discharge_total += bess_metrics['bess_discharge_total_kwh']
        self.bess_throughput_total += bess_metrics['bess_throughput_total_kwh']
        self.bess_capacity_total += bess_metrics['_bess_capacity_kwh']
        self.bess_capacity_loss_total += max(bess_metrics['_bess_capacity_kwh'] - bess_metrics['_bess_degraded_capacity_kwh'], 0.0)

        pv_metrics = run(progress, 'solar', kpi._compute_pv_metrics, building, t_start=t_start, t_final=t_end)
        extended_building_rows.extend([
            kpi._metric('pv_curtailment_total_kwh', pv_metrics['pv_curtailment_total_kwh'], building.name, 'building'),
            kpi._metric('pv_generation_total_kwh', pv_metrics['pv_generation_total_kwh'], building.name, 'building'),
            kpi._metric('pv_export_total_kwh', pv_metrics['pv_export_total_kwh'], building.name, 'building'),
            kpi._metric('pv_generation_daily_average_kwh', kpi._daily_average(pv_metrics['pv_generation_total_kwh'], building_days), building.name, 'building'),
            kpi._metric('pv_export_daily_average_kwh', kpi._daily_average(pv_metrics['pv_export_total_kwh'], building_days), building.name, 'building'),
            kpi._metric('pv_self_consumption_ratio', pv_metrics['pv_self_consumption_ratio'], building.name, 'building'),
        ])
        phase_metrics = run(progress, 'electrical_service', kpi._compute_phase_metrics, building, t_start=t_start, t_final=t_end)
        extended_building_rows.extend([
            kpi._metric('electrical_service_violation_total_kwh', phase_metrics['electrical_service_violation_total_kwh'], building.name, 'building'),
            kpi._metric('electrical_service_violation_time_step_count', phase_metrics['electrical_service_violation_time_step_count'], building.name, 'building'),
            kpi._metric('electrical_service_requested_pressure_total_kwh', phase_metrics['electrical_service_requested_pressure_total_kwh'], building.name, 'building'),
            kpi._metric('electrical_service_requested_pressure_time_step_count', phase_metrics['electrical_service_requested_pressure_time_step_count'], building.name, 'building'),
            kpi._metric('phase_imbalance_ratio_average', phase_metrics['phase_imbalance_ratio_average'], building.name, 'building'),
        ])
        for phase_name, value in phase_metrics['phase_import_peak_kw'].items():
            extended_building_rows.append(kpi._metric(f'phase_import_peak_kw_{phase_name}', value, building.name, 'building'))
        for phase_name, value in phase_metrics['phase_export_peak_kw'].items():
            extended_building_rows.append(kpi._metric(f'phase_export_peak_kw_{phase_name}', value, building.name, 'building'))

        self.phase_violation_total += phase_metrics['electrical_service_violation_total_kwh']
        self.phase_violation_count += phase_metrics['electrical_service_violation_time_step_count']
        self.phase_requested_pressure_total += phase_metrics['electrical_service_requested_pressure_total_kwh']
        self.phase_requested_pressure_count += phase_metrics['electrical_service_requested_pressure_time_step_count']
        self.phase_imbalance_sum += phase_metrics['_imbalance_sum']
        self.phase_imbalance_count += phase_metrics['_imbalance_count']
        return extended_building_rows

    def district_records(self, kpi_buildings, building_windows, simulated_days):
        kpi = self.kpi
        env = kpi.env
        extended_district_rows = []
        extended_district_rows.extend(
            kpi._metric(f'ev_departure_audit_{key}', value, 'District', 'district')
            for key, value in ev_departure_audit.metrics(self.ev_audit_counts).items()
        )
        ev_success_rate = None if self.ev_departures_total <= 0.0 else self.ev_departures_met / self.ev_departures_total
        ev_min_acceptable_rate = None if self.ev_departures_total <= 0.0 else self.ev_departures_min_acceptable / self.ev_departures_total
        ev_within_tolerance_rate = None if self.ev_departures_total <= 0.0 else self.ev_departures_within_tolerance / self.ev_departures_total
        ev_success_feasible_rate = (
            None if self.ev_departures_target_feasible <= 0.0
            else self.ev_departures_met_target_feasible / self.ev_departures_target_feasible
        )
        ev_min_acceptable_feasible_rate = (
            None if self.ev_departures_min_acceptable_feasible <= 0.0
            else self.ev_departures_min_acceptable_feasible_met / self.ev_departures_min_acceptable_feasible
        )
        ev_within_tolerance_feasible_rate = (
            None if self.ev_departures_within_tolerance_feasible <= 0.0
            else self.ev_departures_within_tolerance_feasible_met / self.ev_departures_within_tolerance_feasible
        )
        ev_deficit_mean = None if self.ev_departures_total <= 0.0 else self.ev_deficit_sum / self.ev_departures_total
        ev_shortfall_beyond_tolerance_mean = None if self.ev_departures_total <= 0.0 else self.ev_shortfall_beyond_tolerance_sum / self.ev_departures_total
        ev_surplus_mean = None if self.ev_departures_total <= 0.0 else self.ev_surplus_sum / self.ev_departures_total
        ev_absolute_error_mean = None if self.ev_departures_total <= 0.0 else self.ev_absolute_error_sum / self.ev_departures_total
        extended_district_rows.extend([
            kpi._metric('ev_departure_events_count', self.ev_departures_total, 'District', 'district'),
            kpi._metric('ev_departure_met_events_count', self.ev_departures_met, 'District', 'district'),
            kpi._metric('ev_departure_min_acceptable_events_count', self.ev_departures_min_acceptable, 'District', 'district'),
            kpi._metric('ev_departure_within_tolerance_events_count', self.ev_departures_within_tolerance, 'District', 'district'),
            kpi._metric('ev_departure_target_feasible_events_count', self.ev_departures_target_feasible, 'District', 'district'),
            kpi._metric('ev_departure_target_infeasible_events_count', self.ev_departures_target_infeasible, 'District', 'district'),
            kpi._metric('ev_departure_min_acceptable_feasible_events_count', self.ev_departures_min_acceptable_feasible, 'District', 'district'),
            kpi._metric('ev_departure_min_acceptable_infeasible_events_count', self.ev_departures_min_acceptable_infeasible, 'District', 'district'),
            kpi._metric('ev_departure_within_tolerance_feasible_events_count', self.ev_departures_within_tolerance_feasible, 'District', 'district'),
            kpi._metric('ev_departure_within_tolerance_infeasible_events_count', self.ev_departures_within_tolerance_infeasible, 'District', 'district'),
            kpi._metric('ev_departure_success_rate', ev_success_rate, 'District', 'district'),
            kpi._metric('ev_departure_min_acceptable_rate', ev_min_acceptable_rate, 'District', 'district'),
            kpi._metric('ev_departure_within_tolerance_rate', ev_within_tolerance_rate, 'District', 'district'),
            kpi._metric('ev_departure_success_feasible_rate', ev_success_feasible_rate, 'District', 'district'),
            kpi._metric('ev_departure_min_acceptable_feasible_rate', ev_min_acceptable_feasible_rate, 'District', 'district'),
            kpi._metric('ev_departure_within_tolerance_feasible_rate', ev_within_tolerance_feasible_rate, 'District', 'district'),
            kpi._metric('ev_departure_soc_deficit_mean', ev_deficit_mean, 'District', 'district'),
            kpi._metric('ev_departure_shortfall_beyond_tolerance_mean', ev_shortfall_beyond_tolerance_mean, 'District', 'district'),
            kpi._metric('ev_departure_soc_surplus_mean', ev_surplus_mean, 'District', 'district'),
            kpi._metric('ev_departure_soc_absolute_error_mean', ev_absolute_error_mean, 'District', 'district'),
            kpi._metric('ev_departure_tolerance_ratio', kpi._ev_departure_service_tolerance(), 'District', 'district'),
            kpi._metric('ev_charge_total_kwh', self.ev_charge_total, 'District', 'district'),
            kpi._metric('ev_v2g_export_total_kwh', self.ev_v2g_total, 'District', 'district'),
            kpi._metric('ev_connected_soc_gain_total_kwh', self.ev_connected_soc_gain_total, 'District', 'district'),
            kpi._metric('ev_energy_accounting_shortfall_kwh', self.ev_energy_accounting_shortfall_total, 'District', 'district'),
        ])

        district_bess_cycles = None if self.bess_capacity_total <= 0.0 else self.bess_throughput_total / (2.0 * self.bess_capacity_total)
        district_bess_fade = None if self.bess_capacity_total <= 0.0 else self.bess_capacity_loss_total / self.bess_capacity_total
        extended_district_rows.extend([
            kpi._metric('bess_charge_total_kwh', self.bess_charge_total, 'District', 'district'),
            kpi._metric('bess_discharge_total_kwh', self.bess_discharge_total, 'District', 'district'),
            kpi._metric('bess_throughput_total_kwh', self.bess_throughput_total, 'District', 'district'),
            kpi._metric('bess_equivalent_full_cycles', district_bess_cycles, 'District', 'district'),
            kpi._metric('bess_capacity_fade_ratio', district_bess_fade, 'District', 'district'),
        ])

        final_t = int(max(getattr(env, 'time_step', 0), 0))
        district_pv_metrics = kpi._compute_district_pv_metrics(kpi_buildings, building_windows, final_t=final_t)
        pv_generation_total = district_pv_metrics['pv_generation_total_kwh']
        pv_export_total = district_pv_metrics['pv_export_total_kwh']
        district_pv_ratio = district_pv_metrics['pv_self_consumption_ratio']
        extended_district_rows.extend([
            kpi._metric('pv_curtailment_total_kwh', district_pv_metrics['pv_curtailment_total_kwh'], 'District', 'district'),
            kpi._metric('pv_generation_total_kwh', pv_generation_total, 'District', 'district'),
            kpi._metric('pv_export_total_kwh', pv_export_total, 'District', 'district'),
            kpi._metric('pv_generation_daily_average_kwh', kpi._daily_average(pv_generation_total, simulated_days), 'District', 'district'),
            kpi._metric('pv_export_daily_average_kwh', kpi._daily_average(pv_export_total, simulated_days), 'District', 'district'),
            kpi._metric('pv_self_consumption_ratio', district_pv_ratio, 'District', 'district'),
        ])

        district_phase_imbalance = None if self.phase_imbalance_count <= 0.0 else self.phase_imbalance_sum / self.phase_imbalance_count
        extended_district_rows.extend([
            kpi._metric('electrical_service_violation_total_kwh', self.phase_violation_total, 'District', 'district'),
            kpi._metric('electrical_service_violation_time_step_count', self.phase_violation_count, 'District', 'district'),
            kpi._metric('electrical_service_requested_pressure_total_kwh', self.phase_requested_pressure_total, 'District', 'district'),
            kpi._metric('electrical_service_requested_pressure_time_step_count', self.phase_requested_pressure_count, 'District', 'district'),
            kpi._metric('phase_imbalance_ratio_average', district_phase_imbalance, 'District', 'district'),
        ])

        phase_union = ['L1', 'L2', 'L3']
        for phase_name in phase_union:
            phase_series = np.zeros(final_t + 1, dtype='float64')
            has_phase_data = False
            for building in kpi_buildings:
                history_map = getattr(building, '_charging_phase_power_history_kw', {}) or {}
                if phase_name not in history_map:
                    continue
                t_start, t_end = building_windows.get(building.name, (0, -1))
                if t_end < t_start:
                    continue
                values = np.array(history_map[phase_name], dtype='float64')
                start = max(int(t_start), 0)
                end = min(int(t_end), final_t, len(values) - 1)
                if end < start:
                    continue
                phase_series[start:end + 1] += values[start:end + 1]
                has_phase_data = True

            if not has_phase_data:
                continue

            extended_district_rows.append(
                kpi._metric(f'phase_import_peak_kw_{phase_name}', float(np.clip(phase_series, 0.0, None).max(initial=0.0)), 'District', 'district')
            )
            extended_district_rows.append(
                kpi._metric(f'phase_export_peak_kw_{phase_name}', float(np.clip(-phase_series, 0.0, None).max(initial=0.0)), 'District', 'district')
            )
        return extended_district_rows
