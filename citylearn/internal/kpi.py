from __future__ import annotations

from copy import copy
from citylearn.internal.kpi_population import current_population, population_scope
from functools import wraps
from citylearn.internal.market_history import MarketSettlementHistory
from citylearn.internal.evaluation_progress import EvaluationProgress, run, span
from types import SimpleNamespace
from array import array

from citylearn.energy_model import Battery
from citylearn.internal import ev_departure_audit, deferrable_service_audit
from citylearn.internal import kpi_energy, kpi_equipment, kpi_community, kpi_service_metrics

from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from citylearn.data import ZERO_DIVISION_PLACEHOLDER, ChargerSimulation

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv


def settled_cost_scope(function):
    """Share market-settled cost series across the KPI readers of one evaluation call."""
    @wraps(function)
    def wrapper(service, *args, **kwargs):
        if getattr(service, '_settled_cost_cache', None) is not None:
            return function(service, *args, **kwargs)
        service._settled_cost_cache = {}
        try:
            return function(service, *args, **kwargs)
        finally:
            service._settled_cost_cache = None
    return wrapper


class CityLearnKPIService:
    """Internal KPI/evaluation service for `CityLearnEnv`."""

    EV_DEPARTURE_WITHIN_TOLERANCE_DEFAULT = 0.05
    EV_DEPARTURE_SERVICE_TOLERANCE_DEFAULT = 0.05
    EV_DEPARTURE_EPS = 1.0e-6
    ELECTRICAL_RESIDUAL_EPS_KW = 1.0e-5
    SCORECARD_DEFAULT_KPIS: Tuple[str, ...] = (
        'district_thermal_service_audit_discomfort_ratio',
        'district_thermal_service_audit_thermal_coverage_ratio',
        'district_thermal_service_audit_outage_discomfort_ratio',
        'district_thermal_service_audit_unserved_service_ratio',
        'district_thermal_service_audit_outage_unserved_service_ratio',
        'district_thermal_service_audit_energy_coverage_ratio',
        'district_equity_audit_coverage_ratio',
        # Final destinations and external carbon use the versioned ledger.
        'district_energy_provenance_pv_useful_building_ratio',
        'district_energy_provenance_pv_useful_with_mobility_ratio',
        'district_energy_provenance_pv_stored_kwh',
        'district_energy_provenance_pv_grid_export_kwh',
        'district_energy_provenance_external_purchase_emissions_kgco2',
        'district_energy_provenance_external_purchase_emissions_business_as_usual_kgco2',
        # Cost scorecard values and BAU reference.
        'district_cost_total_control_eur',
        'district_cost_total_business_as_usual_eur',
        'district_cost_total_delta_to_business_as_usual_eur',
        'building_cost_total_control_eur',
        'building_cost_total_business_as_usual_eur',
        'building_cost_total_delta_to_business_as_usual_eur',

        # EV service and grid-safety values are judged directly, not vs BAU.
        'district_ev_departure_audit_min_acceptable_service_feasible_ratio',
        'district_ev_departure_audit_within_tolerance_service_feasible_ratio',
        'district_ev_departure_audit_target_coverage_ratio',
        'district_ev_departure_audit_service_coverage_ratio',
        'district_ev_departure_audit_target_unknown_count',
        'district_electrical_service_phase_violations_energy_total_kwh',
        'district_electrical_service_phase_requested_pressure_energy_total_kwh',
        'building_ev_departure_audit_min_acceptable_service_feasible_ratio',
        'building_ev_departure_audit_within_tolerance_service_feasible_ratio',
        'building_ev_departure_audit_target_coverage_ratio',
        'building_ev_departure_audit_service_coverage_ratio',
        'building_ev_departure_audit_target_unknown_count',
        'building_electrical_service_phase_violations_energy_total_kwh',
        'building_electrical_service_phase_requested_pressure_energy_total_kwh',

        # Battery and V2G totals with BAU reference rows.
        'district_battery_total_throughput_kwh',
        'district_battery_total_throughput_business_as_usual_kwh',
        'district_battery_total_throughput_delta_to_business_as_usual_kwh',
        'district_ev_total_v2g_export_kwh',
        'district_ev_total_v2g_export_business_as_usual_kwh',
        'district_ev_total_v2g_export_delta_to_business_as_usual_kwh',
        'building_battery_total_throughput_kwh',
        'building_battery_total_throughput_business_as_usual_kwh',
        'building_battery_total_throughput_delta_to_business_as_usual_kwh',
        'building_ev_total_v2g_export_kwh',
        'building_ev_total_v2g_export_business_as_usual_kwh',
        'building_ev_total_v2g_export_delta_to_business_as_usual_kwh',

        # Solar self-consumption with BAU reference rows.
        'district_solar_self_consumption_ratio_self_consumption_ratio',
        'district_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio',
        'district_solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio',
        'building_solar_self_consumption_ratio_self_consumption_ratio',
        'building_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio',
        'building_solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio',

        # Community/building grid exchange values with BAU reference rows.
        'district_energy_grid_total_import_control_kwh',
        'district_energy_grid_total_import_business_as_usual_kwh',
        'district_energy_grid_total_import_delta_to_business_as_usual_kwh',
        'district_energy_grid_total_export_control_kwh',
        'district_energy_grid_total_export_business_as_usual_kwh',
        'district_energy_grid_total_export_delta_to_business_as_usual_kwh',
        'district_energy_grid_total_net_exchange_control_kwh',
        'district_energy_grid_total_net_exchange_business_as_usual_kwh',
        'district_energy_grid_total_net_exchange_delta_to_business_as_usual_kwh',
        'building_energy_grid_total_import_control_kwh',
        'building_energy_grid_total_import_business_as_usual_kwh',
        'building_energy_grid_total_import_delta_to_business_as_usual_kwh',
        'building_energy_grid_total_export_control_kwh',
        'building_energy_grid_total_export_business_as_usual_kwh',
        'building_energy_grid_total_export_delta_to_business_as_usual_kwh',
        'building_energy_grid_total_net_exchange_control_kwh',
        'building_energy_grid_total_net_exchange_business_as_usual_kwh',
        'building_energy_grid_total_net_exchange_delta_to_business_as_usual_kwh',

        # District-only grid-shape ratios used by the community scorecard.
        'district_energy_grid_shape_quality_peak_daily_average_to_business_as_usual_ratio',
        'district_energy_grid_shape_quality_peak_all_time_average_to_business_as_usual_ratio',
        'district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_business_as_usual_ratio',
    )
    LEGACY_COST_FUNCTIONS = {
        'all_time_peak_average',
        'annual_normalized_unserved_energy_total',
        'carbon_emissions_total',
        'cost_total',
        'daily_one_minus_load_factor_average',
        'daily_peak_average',
        'discomfort_cold_delta_average',
        'discomfort_cold_delta_maximum',
        'discomfort_cold_delta_minimum',
        'discomfort_cold_proportion',
        'discomfort_hot_delta_average',
        'discomfort_hot_delta_maximum',
        'discomfort_hot_delta_minimum',
        'discomfort_hot_proportion',
        'discomfort_proportion',
        'electricity_consumption_total',
        'monthly_one_minus_load_factor_average',
        'one_minus_thermal_resilience_proportion',
        'power_outage_normalized_unserved_energy_total',
        'ramping_average',
        'zero_net_energy',
    }

    def __init__(self, env: "CityLearnEnv"):
        self.env = env

    @staticmethod
    def _to_scalar(value, default: float = 0.0) -> float:
        try:
            scalar = float(value)
        except (TypeError, ValueError):
            return float(default)

        if not np.isfinite(scalar):
            return float(default)

        return scalar

    @staticmethod
    def _safe_div(control_value: float, baseline_value: float):
        c = CityLearnKPIService._to_scalar(control_value, 0.0)
        b = CityLearnKPIService._to_scalar(baseline_value, 0.0)
        eps = float(ZERO_DIVISION_PLACEHOLDER)

        if abs(b) <= eps:
            return 1.0 if abs(c) <= eps else None

        return c / b

    @staticmethod
    def _signed_ratio(control_value: float, baseline_value: float):
        """Lower-is-better ratio for totals that can be negative, e.g. net exchange.

        Equals `control / baseline` for a positive baseline. For a negative
        baseline (a net exporter) it is `1 + (control - baseline) / |baseline|`,
        so a higher control total never reads as an improvement.
        """
        ratio = CityLearnKPIService._safe_div(control_value, baseline_value)
        b = CityLearnKPIService._to_scalar(baseline_value, 0.0)

        if ratio is None or b >= -float(ZERO_DIVISION_PLACEHOLDER):
            return ratio

        return 2.0 - ratio

    @staticmethod
    def _window_steps(window_seconds: float, seconds_per_time_step: float) -> int:
        step_seconds = max(float(seconds_per_time_step), 1.0)
        return max(1, int(round(float(window_seconds) / step_seconds)))

    @staticmethod
    def _simulated_days(env: "CityLearnEnv") -> float:
        steps = max(int(env.time_step), 0) if hasattr(env, 'time_step') else 1
        step_seconds = max(float(getattr(env, 'seconds_per_time_step', 0) or 0), 1.0)
        return (steps * step_seconds) / (24.0 * 3600.0)

    @staticmethod
    def _window_days(t_start: int, t_final: int, seconds_per_time_step: float) -> float:
        if t_final < t_start:
            return 0.0
        steps = max(int(t_final) - int(t_start) + 1, 0)
        step_seconds = max(float(seconds_per_time_step or 0.0), 1.0)
        return (steps * step_seconds) / (24.0 * 3600.0)

    @staticmethod
    def _daily_average(total_value: float, simulated_days: float) -> Optional[float]:
        value = CityLearnKPIService._to_scalar(total_value, np.nan)

        if not np.isfinite(value):
            return None

        if simulated_days <= float(ZERO_DIVISION_PLACEHOLDER):
            return None

        return float(value / simulated_days)

    @staticmethod
    def _normalize_soc_target(value) -> Optional[float]:
        try:
            target = float(value)
        except (TypeError, ValueError):
            return None

        if not np.isfinite(target):
            return None

        if target > 1.0 and target <= 100.0:
            target = target / 100.0

        if target < 0.0 or target > 1.0:
            return None

        return float(target)

    @staticmethod
    def _safe_sequence_value(sequence, index: int, default=None):
        if sequence is None or index is None or index < 0:
            return default

        try:
            if index >= len(sequence):
                return default
            return sequence[index]
        except (TypeError, IndexError):
            return default

    @staticmethod
    def _normal_ev_id(value) -> Optional[str]:
        if not isinstance(value, str):
            return None

        value = value.strip()
        if value == '' or value.lower() == 'nan':
            return None

        return value

    @staticmethod
    def _interp_curve(curve, x: float, default: Optional[float] = None) -> Optional[float]:
        try:
            arr = np.array(curve, dtype='float64')
        except (TypeError, ValueError):
            return default

        if arr.ndim != 2:
            return default

        if arr.shape[0] != 2 and arr.shape[1] == 2:
            arr = arr.T

        if arr.shape[0] != 2:
            return default

        xs = arr[0]
        ys = arr[1]
        finite = np.isfinite(xs) & np.isfinite(ys)

        if not np.any(finite):
            return default

        xs = xs[finite]
        ys = ys[finite]
        order = np.argsort(xs)
        xs = xs[order]
        ys = ys[order]

        return float(np.interp(float(x), xs, ys))

    def _ev_connected_interval_start(self, sim, states: np.ndarray, departure_index: int) -> int:
        ev_ids = getattr(sim, 'electric_vehicle_id', None)
        session_ids = getattr(sim, 'electric_vehicle_session_id', None)
        current_ev_id = self._normal_ev_id(self._safe_sequence_value(ev_ids, departure_index))
        current_session_id = self._normal_ev_id(
            self._safe_sequence_value(session_ids, departure_index)
        )
        start = int(departure_index)

        while start > 0:
            previous_state = self._to_scalar(states[start - 1], np.nan)

            if previous_state != 1:
                break

            previous_ev_id = self._normal_ev_id(self._safe_sequence_value(ev_ids, start - 1))
            previous_session_id = self._normal_ev_id(
                self._safe_sequence_value(session_ids, start - 1)
            )

            if (
                current_ev_id is not None
                and previous_ev_id is not None
                and previous_ev_id != current_ev_id
            ):
                break
            if (
                current_session_id is not None
                and previous_session_id is not None
                and previous_session_id != current_session_id
            ):
                break

            start -= 1

        return start

    def _ev_kpi_connection_boundary(self, charger, sim, ev, states, departure_index):
        boundary_soc = getattr(charger, '_topology_connection_soc', {})
        if boundary_soc:
            start = ev_departure_audit.connected_start(self, charger, sim, ev, states, departure_index)
            if start in boundary_soc:
                return start, boundary_soc[start]
        else:
            start = self._ev_connected_interval_start(sim, states, departure_index)
        return start, self._ev_arrival_soc_for_interval(sim, ev, states, start)

    def _ev_arrival_soc_for_interval(self, sim, ev, states: np.ndarray, interval_start: int) -> Optional[float]:
        estimated_soc_arrival = getattr(sim, 'electric_vehicle_estimated_soc_arrival', None)
        current_soc_reference = getattr(sim, 'electric_vehicle_current_soc', None)
        # This is the same boundary reference used by the runtime for a normal
        # arrival, a partial-window reset, or a topology activation that exposes
        # an already occupied charger.  It is a boundary value only, not an
        # exogenous trajectory that may overwrite subsequent control.
        candidates = [self._safe_sequence_value(current_soc_reference, interval_start)]
        # Same estimate row as the runtime arrival. Without one the runtime
        # keeps the simulated SOC, which the battery candidates below give.
        index = ChargerSimulation.arrival_soc_index(
            states,
            getattr(sim, 'electric_vehicle_id', None),
            estimated_soc_arrival,
            interval_start,
            getattr(sim, 'electric_vehicle_session_id', None),
        )
        candidates.append(self._safe_sequence_value(estimated_soc_arrival, index))

        battery = getattr(ev, 'battery', None)
        battery_soc = getattr(battery, 'soc', None)

        if interval_start == 0:
            candidates.append(getattr(battery, 'initial_soc', None))
        else:
            candidates.append(self._safe_sequence_value(battery_soc, interval_start - 1))

        candidates.append(self._safe_sequence_value(battery_soc, interval_start))

        for candidate in candidates:
            soc = self._normalize_soc_target(candidate)
            if soc is not None:
                return soc

        return None

    def _ev_battery_max_input_power_kw(self, battery, charger_power_kw: float, soc: float) -> float:
        charger_power_kw = max(float(charger_power_kw), 0.0)
        nominal_power_kw = self._to_scalar(getattr(battery, 'nominal_power', np.nan), np.nan)

        if not np.isfinite(nominal_power_kw) or nominal_power_kw <= 0.0:
            return charger_power_kw

        multiplier = self._interp_curve(getattr(battery, 'capacity_power_curve', None), soc, default=1.0)
        multiplier = 1.0 if multiplier is None or not np.isfinite(multiplier) else max(float(multiplier), 0.0)
        return min(charger_power_kw, nominal_power_kw * multiplier)

    def _ev_battery_charge_round_trip_efficiency(self, battery, power_kw: float) -> float:
        nominal_power_kw = self._to_scalar(getattr(battery, 'nominal_power', np.nan), np.nan)
        normalized_power = (
            float(power_kw) / nominal_power_kw
            if np.isfinite(nominal_power_kw) and nominal_power_kw > 0.0
            else 1.0
        )
        efficiency = self._interp_curve(
            getattr(battery, 'power_efficiency_curve', None),
            np.clip(normalized_power, 0.0, 1.0),
            default=None,
        )

        if efficiency is None or not np.isfinite(efficiency):
            efficiency = self._to_scalar(getattr(battery, 'efficiency', np.nan), np.nan)

        if efficiency is None or not np.isfinite(efficiency):
            round_trip = self._to_scalar(getattr(battery, 'round_trip_efficiency', np.nan), np.nan)
            return float(np.clip(round_trip, 0.0, 1.0)) if np.isfinite(round_trip) else 1.0

        return float(np.sqrt(np.clip(efficiency, 0.0, 1.0)))

    def _ev_charger_charge_efficiency(self, charger, power_kw: float, max_power_kw: float) -> float:
        normalized_power = float(power_kw) / max(float(max_power_kw), ZERO_DIVISION_PLACEHOLDER)
        get_efficiency = getattr(charger, 'get_efficiency', None)

        if callable(get_efficiency):
            try:
                return float(np.clip(get_efficiency(np.clip(normalized_power, 0.0, 1.0), True), 0.0, 1.0))
            except (TypeError, ValueError):
                pass

        return float(np.clip(self._to_scalar(getattr(charger, 'efficiency', 1.0), 1.0), 0.0, 1.0))

    @staticmethod
    def _normalize_phase_connection_label(value) -> Optional[str]:
        if value is None:
            return None

        text = str(value).strip()
        if text == '':
            return None

        normalized = text.lower().replace('-', '_')
        aliases = {
            'l1': 'L1',
            'phase_1': 'L1',
            'l2': 'L2',
            'phase_2': 'L2',
            'l3': 'L3',
            'phase_3': 'L3',
            'all_phases': 'all_phases',
            'three_phase': 'all_phases',
        }
        return aliases.get(normalized, text)

    def _electrical_service_phase_names(self, building) -> List[str]:
        if getattr(building, '_electrical_service_mode', 'single_phase') == 'three_phase':
            return ['L1', 'L2', 'L3']

        return ['L1']

    def _split_unassigned_service_power(self, building, power_kw: float) -> Dict[str, float]:
        phase_names = self._electrical_service_phase_names(building)

        if len(phase_names) == 1:
            return {'L1': float(power_kw)}

        split_mode = str(getattr(building, '_electrical_service_default_split', 'balanced')).strip().lower()
        if split_mode in {'l1', 'l2', 'l3'}:
            return {phase: float(power_kw if phase.lower() == split_mode else 0.0) for phase in phase_names}

        share = float(power_kw) / len(phase_names)
        return {phase: share for phase in phase_names}

    def _split_service_power_by_connection(
        self,
        building,
        power_kw: float,
        phase_connection: Optional[str],
    ) -> Dict[str, float]:
        phase_names = self._electrical_service_phase_names(building)

        if len(phase_names) == 1:
            return {'L1': float(power_kw)}

        phase_connection = self._normalize_phase_connection_label(phase_connection)
        if phase_connection in {'L1', 'L2', 'L3'}:
            return {phase: float(power_kw if phase == phase_connection else 0.0) for phase in phase_names}

        if phase_connection == 'all_phases':
            share = float(power_kw) / len(phase_names)
            return {phase: share for phase in phase_names}

        return self._split_unassigned_service_power(building, power_kw)

    def _ev_power_outage_at_step(self, building, step: int) -> bool:
        ops_service = getattr(building, '_ops_service', None)
        outage_at_step = getattr(ops_service, '_power_outage_at_step', None)

        if callable(outage_at_step):
            try:
                return bool(outage_at_step(step))
            except Exception:
                pass

        signal = getattr(building, 'power_outage_signal', None)
        if signal is None:
            energy_simulation = getattr(building, 'energy_simulation', None)
            signal = getattr(energy_simulation, 'power_outage', None)

        return bool(self._safe_sequence_value(signal, step, 0.0))

    def _estimate_feasibility_base_power_at_step(self, building, step: int) -> Tuple[float, Dict[str, float]]:
        ops_service = getattr(building, '_ops_service', None)
        estimate = getattr(ops_service, '_estimate_base_power_at_step', None)

        if callable(estimate):
            try:
                total_kw, phase_kw = estimate(step)
                total_kw = self._to_scalar(total_kw, 0.0)
                phase_kw = {
                    phase: self._to_scalar(value, 0.0)
                    for phase, value in (phase_kw or {}).items()
                }
                return total_kw, phase_kw
            except Exception:
                pass

        phase_kw = {phase: 0.0 for phase in self._electrical_service_phase_names(building)}
        return 0.0, phase_kw

    def _ev_apply_charger_charge_deadband(self, charger, power_kw: float) -> float:
        power_kw = max(self._to_scalar(power_kw, 0.0), 0.0)
        if power_kw <= self.EV_DEPARTURE_EPS:
            return 0.0

        max_power_kw = max(self._to_scalar(getattr(charger, 'max_charging_power', power_kw), power_kw), 0.0)
        min_power_kw = max(self._to_scalar(getattr(charger, 'min_charging_power', 0.0), 0.0), 0.0)
        if max_power_kw > 0.0:
            min_power_kw = min(min_power_kw, max_power_kw)

        if min_power_kw > 0.0 and power_kw < min_power_kw:
            return 0.0

        return power_kw

    def _ev_constraint_limited_charge_power_kw(
        self,
        building,
        charger,
        step: int,
        requested_power_kw: float,
    ) -> float:
        requested_power_kw = max(self._to_scalar(requested_power_kw, 0.0), 0.0)

        if requested_power_kw <= self.EV_DEPARTURE_EPS:
            return 0.0

        if building is None or not getattr(building, '_charging_constraints_enabled', False):
            return self._ev_apply_charger_charge_deadband(charger, requested_power_kw)

        if self._ev_power_outage_at_step(building, step):
            return 0.0

        if getattr(building, '_electrical_service_enabled', False):
            base_total_kw, base_phase_kw = self._estimate_feasibility_base_power_at_step(building, step)
            total_limits = getattr(building, '_electrical_service_limits', {}).get('total', {}) or {}
            per_phase_limits = getattr(building, '_electrical_service_limits', {}).get('per_phase', {}) or {}
            cap_kw = requested_power_kw

            import_limit = self._to_scalar(total_limits.get('import_kw'), np.nan)
            if np.isfinite(import_limit):
                cap_kw = min(cap_kw, max(import_limit - base_total_kw, 0.0))

            charger_id = getattr(charger, 'charger_id', None)
            phase_connection = (getattr(building, '_charger_phase_map', {}) or {}).get(
                charger_id,
                getattr(charger, 'phase_connection', None),
            )
            request_phase_fraction = self._split_service_power_by_connection(building, 1.0, phase_connection)

            for phase_name, fraction in request_phase_fraction.items():
                fraction = self._to_scalar(fraction, 0.0)
                if fraction <= self.EV_DEPARTURE_EPS:
                    continue

                phase_limit = self._to_scalar(
                    (per_phase_limits.get(phase_name, {}) or {}).get('import_kw'),
                    np.nan,
                )
                if np.isfinite(phase_limit):
                    phase_base_kw = self._to_scalar(base_phase_kw.get(phase_name, 0.0), 0.0)
                    cap_kw = min(cap_kw, max((phase_limit - phase_base_kw) / fraction, 0.0))

            return self._ev_apply_charger_charge_deadband(charger, min(requested_power_kw, cap_kw))

        cap_kw = requested_power_kw
        building_limit = self._to_scalar(getattr(building, '_building_charger_limit_kw', None), np.nan)
        if np.isfinite(building_limit):
            cap_kw = min(cap_kw, max(building_limit, 0.0))

        charger_id = getattr(charger, 'charger_id', None)
        charger_phase_map = getattr(building, '_charger_phase_map', {}) or {}
        charger_phase = charger_phase_map.get(charger_id)

        for phase in getattr(building, '_phase_limits', []) or []:
            chargers = phase.get('chargers', []) or []
            if charger_id not in chargers and phase.get('name') != charger_phase:
                continue

            phase_limit = self._to_scalar(phase.get('limit_kw', phase.get('import_kw')), np.nan)
            if np.isfinite(phase_limit):
                cap_kw = min(cap_kw, max(phase_limit, 0.0))

        return self._ev_apply_charger_charge_deadband(charger, min(requested_power_kw, cap_kw))

    def _ev_departure_threshold_feasible(
        self,
        building,
        charger,
        sim,
        ev,
        states: np.ndarray,
        departure_index: int,
        threshold_soc: float,
        *,
        audit_arrival_soc: Optional[float] = None,
        audit_interval_start: Optional[int] = None,
        audit: bool = False,
    ) -> Optional[bool]:
        """Return whether a departure threshold was reachable with max charging.

        Missing charger/battery/arrival data is treated as feasible to preserve
        existing KPI semantics for legacy datasets that cannot support this audit.
        The additive departure audit validates its inputs first, supplies an
        observed connection boundary, and treats non-finite replay as unknown.
        """

        return self._ev_departure_thresholds_feasible(
            building, charger, sim, ev, states, departure_index, (threshold_soc,),
            audit_arrival_soc=audit_arrival_soc,
            audit_interval_start=audit_interval_start, audit=audit,
        )[0]

    def _ev_departure_thresholds_feasible(
        self, building, charger, sim, ev, states, departure_index, thresholds,
        *, audit_arrival_soc=None, audit_interval_start=None, audit=False,
    ):
        """Compare thresholds against one isolated maximum-charge replay.

        This batch belongs to one departure/context only. Legacy and audited
        callers use separate batches, even if their boundaries happen to match.
        No battery values or replay buffers are retained between batches.
        """
        thresholds = tuple(self._normalize_soc_target(value) for value in thresholds)
        if not thresholds:
            return ()
        if not audit and all(value is None or value <= 0.0 for value in thresholds):
            return (True,) * len(thresholds)
        soc = self._ev_departure_max_charge_soc(
            building, charger, sim, ev, states, departure_index,
            audit_arrival_soc=audit_arrival_soc,
            audit_interval_start=audit_interval_start, audit=audit,
        )
        results = []
        for threshold in thresholds:
            if (not audit and (threshold is None or threshold <= 0.0)) or soc is None:
                results.append(True)
            elif audit and not np.isfinite(soc):
                results.append(None)
            else:
                results.append(bool(soc + self.EV_DEPARTURE_EPS >= threshold))
        return tuple(results)

    def _ev_departure_max_charge_soc(
        self, building, charger, sim, ev, states, departure_index,
        *, audit_arrival_soc=None, audit_interval_start=None, audit=False,
    ):
        """Departure SOC after the unchanged full maximum-charge trajectory.

        None preserves the legacy permissive result for insufficient inputs;
        a non-finite replay SOC remains unknown for the additive audit.
        """
        battery = getattr(ev, 'battery', None)

        if battery is None:
            return None

        capacity_kwh = self._to_scalar(getattr(battery, 'capacity', np.nan), np.nan)
        charger_power_kw = self._to_scalar(getattr(charger, 'max_charging_power', np.nan), np.nan)

        if (
            not np.isfinite(capacity_kwh)
            or capacity_kwh <= 0.0
            or not np.isfinite(charger_power_kw)
            or charger_power_kw < 0.0
        ):
            return None

        if audit:
            interval_start, arrival_soc = audit_interval_start, audit_arrival_soc
        else:
            interval_start, arrival_soc = self._ev_kpi_connection_boundary(
                charger, sim, ev, states, departure_index,
            )

        if arrival_soc is None:
            return None

        seconds_per_time_step = self._to_scalar(
            getattr(
                charger,
                'seconds_per_time_step',
                getattr(battery, 'seconds_per_time_step', getattr(self.env, 'seconds_per_time_step', 3600.0)),
            ),
            3600.0,
        )
        step_hours = max(seconds_per_time_step / 3600.0, 0.0)

        if not np.isfinite(step_hours) or step_hours <= 0.0:
            return None

        soc = float(arrival_soc)
        connected_steps = max(int(departure_index) - int(interval_start) + 1, 0)

        # Replay the concrete battery implementation in compact, isolated buffers.
        # No real state, RNG, degradation history or episode tracker is advanced.
        replay = None
        if isinstance(battery, Battery):
            replay = copy(battery)
            replay.episode_tracker = SimpleNamespace(episode_time_steps=max(connected_steps, 1))
            replay.reset()
            capacities = getattr(battery, 'capacity_before_step', [])
            capacity = self._safe_sequence_value(capacities, interval_start)
            if capacity is not None and np.isfinite(capacity):
                replay._capacity_history = array('d', [float(capacity)])
            replay.force_set_soc(arrival_soc)

        for offset in range(connected_steps):
            step = int(interval_start) + offset
            # Service limits apply at the AC charger inlet; battery limits apply
            # downstream of charger losses, inside Battery.charge().
            power_kw = self._ev_constraint_limited_charge_power_kw(
                building, charger, step, charger_power_kw,
            )
            if audit and self._ev_power_outage_at_step(building, step):
                power_kw = 0.0
            charger_efficiency = self._ev_charger_charge_efficiency(charger, power_kw, charger_power_kw)
            if replay is not None:
                if offset:
                    replay.next_time_step()
                ratio = replay.time_step_ratio or 1.0
                replay.charge(power_kw * step_hours * charger_efficiency / ratio)
                soc = float(replay.soc[offset])
            else:
                # Compatibility for legacy battery adapters without a physical
                # charge method; never used for native Battery/InventoryBattery.
                if offset:
                    soc *= 1.0 - float(getattr(battery, 'loss_coefficient', 0.0))
                battery_power = self._ev_battery_max_input_power_kw(
                    battery, power_kw * charger_efficiency, soc,
                )
                eta = self._ev_battery_charge_round_trip_efficiency(battery, battery_power)
                soc = float(np.clip(soc + battery_power * step_hours * eta / capacity_kwh,
                                    0.0, getattr(battery, 'max_soc', 1.0)))

        return soc

    def _ev_departure_within_tolerance(self) -> float:
        return max(
            self._to_scalar(
                getattr(self.env, 'ev_departure_within_tolerance', self.EV_DEPARTURE_WITHIN_TOLERANCE_DEFAULT),
                self.EV_DEPARTURE_WITHIN_TOLERANCE_DEFAULT,
            ),
            0.0,
        )

    def _ev_departure_service_tolerance(self) -> float:
        return max(
            self._to_scalar(
                getattr(self.env, 'ev_departure_service_tolerance', self.EV_DEPARTURE_SERVICE_TOLERANCE_DEFAULT),
                self.EV_DEPARTURE_SERVICE_TOLERANCE_DEFAULT,
            ),
            0.0,
        )

    @staticmethod
    def _metric(cost_function: str, value, name: str, level: str) -> Dict[str, object]:
        return {
            'cost_function': cost_function,
            'value': value,
            'name': name,
            'level': level,
        }

    @staticmethod
    def _sum_finite(values) -> float:
        try:
            series = np.array(values, dtype='float64').flatten()
        except (TypeError, ValueError):
            return 0.0

        if series.size == 0:
            return 0.0

        finite = series[np.isfinite(series)]
        if finite.size == 0:
            return 0.0

        return float(finite.sum())

    @staticmethod
    def _as_float_array(values) -> np.ndarray:
        try:
            return np.array(values, dtype='float64').flatten()
        except (TypeError, ValueError):
            return np.zeros((0,), dtype='float64')

    @classmethod
    def _positive_total(cls, values) -> float:
        series = cls._as_float_array(values)
        if series.size == 0:
            return 0.0
        return cls._sum_finite(np.clip(series, 0.0, None))

    @classmethod
    def _net_total(cls, values) -> float:
        return cls._sum_finite(values)

    @classmethod
    def _ramping_final(cls, values, down_ramp: bool = None, net_export: bool = None) -> float:
        series = cls._as_float_array(values)
        if series.size == 0:
            return 0.0

        down_ramp = False if down_ramp is None else down_ramp
        net_export = True if net_export is None else net_export
        ramp = np.empty_like(series, dtype='float64')
        ramp[0] = np.nan
        if series.size > 1:
            ramp[1:] = series[1:] - series[:-1]

        if down_ramp:
            ramp = np.abs(ramp)
        else:
            ramp = np.clip(ramp, 0.0, None)

        if not net_export:
            ramp = np.where(series < 0.0, 0.0, ramp)

        return cls._sum_finite(ramp)

    @staticmethod
    def _group_slices(values: np.ndarray, window: int):
        window = max(int(window), 1)
        for start in range(0, values.size, window):
            yield values[start:start + window]

    @classmethod
    def _nan_mean_preserve_inf(cls, values: np.ndarray) -> float:
        values = cls._as_float_array(values)
        valid = values[~np.isnan(values)]
        if valid.size == 0:
            return float(np.nan)
        return float(np.mean(valid))

    @classmethod
    def _one_minus_load_factor_final(cls, values, window: int = None) -> float:
        series = cls._as_float_array(values)
        if series.size == 0:
            return 0.0

        window = 730 if window is None else window
        penalties = []
        for group in cls._group_slices(series, window):
            finite = group[np.isfinite(group)]
            if finite.size == 0:
                penalties.append(np.nan)
                continue
            peak = float(np.max(finite))
            mean = float(np.mean(finite))
            with np.errstate(divide='ignore', invalid='ignore'):
                penalties.append(float(1.0 - np.divide(mean, peak)))

        return cls._nan_mean_preserve_inf(np.array(penalties, dtype='float64'))

    @classmethod
    def _peak_final(cls, values, window: int = None) -> float:
        series = cls._as_float_array(values)
        if series.size == 0:
            return 0.0

        window = 24 if window is None else window
        peaks = []
        for group in cls._group_slices(series, window):
            finite = group[np.isfinite(group)]
            peaks.append(np.nan if finite.size == 0 else float(np.max(finite)))

        return cls._nan_mean_preserve_inf(np.array(peaks, dtype='float64'))

    @staticmethod
    def _equity_relative_benefit_percent(cost_scenario: float, cost_baseline: float) -> Optional[float]:
        scenario = CityLearnKPIService._to_scalar(cost_scenario, np.nan)
        baseline = CityLearnKPIService._to_scalar(cost_baseline, np.nan)

        if not np.isfinite(scenario) or not np.isfinite(baseline) or baseline <= 0.0:
            return None

        return float(100.0 * (baseline - scenario) / baseline)

    @staticmethod
    def _equity_distribution_metrics(relative_benefits: np.ndarray) -> Dict[str, Optional[float]]:
        benefits = np.array(relative_benefits, dtype='float64')
        benefits = benefits[np.isfinite(benefits)]

        if benefits.size == 0:
            return {
                'equity_gini_benefit': None,
                'equity_cr20_benefit': None,
                'equity_losers_percent': None,
            }

        losers_percent = float(100.0 * np.count_nonzero(benefits < 0.0) / benefits.size)
        benefits_plus = np.clip(benefits, 0.0, None)
        total_plus = float(benefits_plus.sum())

        if total_plus <= 0.0:
            return {
                'equity_gini_benefit': None,
                'equity_cr20_benefit': None,
                'equity_losers_percent': losers_percent,
            }

        n = benefits_plus.size
        diff_sum = float(np.abs(benefits_plus[:, None] - benefits_plus[None, :]).sum())
        gini = float(diff_sum / (2.0 * n * total_plus))

        k = max(1, int(np.ceil(0.2 * n)))
        top_sum = float(np.sort(benefits_plus)[::-1][:k].sum())
        cr20 = float(top_sum / total_plus)

        return {
            'equity_gini_benefit': gini,
            'equity_cr20_benefit': cr20,
            'equity_losers_percent': losers_percent,
        }

    @staticmethod
    def _equity_bpr(
        non_negative_relative_benefits: Mapping[str, float],
        groups: Mapping[str, Optional[str]],
    ) -> Optional[float]:
        if len(non_negative_relative_benefits) == 0:
            return None

        asset_poor_values = []
        asset_rich_values = []

        for building_name, value in non_negative_relative_benefits.items():
            group = groups.get(building_name)

            if group == 'asset_poor':
                asset_poor_values.append(float(value))
            elif group == 'asset_rich':
                asset_rich_values.append(float(value))
            else:
                return None

        if len(asset_poor_values) == 0 or len(asset_rich_values) == 0:
            return None

        rich_mean = float(np.mean(asset_rich_values))
        poor_mean = float(np.mean(asset_poor_values))

        if rich_mean <= 0.0:
            return None

        return float(poor_mean / rich_mean)

    def _compute_ev_metrics(self, building, *, t_start: int = 0, t_final: Optional[int] = None) -> Dict[str, float]:
        upper = int(max(building.time_step, 0))
        t_start = int(max(t_start, 0))
        t_final = upper if t_final is None else int(min(max(t_final, 0), upper))
        within_tolerance = self._ev_departure_within_tolerance()
        service_tolerance = self._ev_departure_service_tolerance()
        audit_counts = ev_departure_audit.empty_counts()
        if t_final < t_start:
            return {
                '_departure_audit': audit_counts,
                'departures_total': 0.0,
                'departures_met': 0.0,
                'departures_min_acceptable': 0.0,
                'departures_within_tolerance': 0.0,
                'departures_target_feasible': 0.0,
                'departures_target_infeasible': 0.0,
                'departures_min_acceptable_feasible': 0.0,
                'departures_min_acceptable_infeasible': 0.0,
                'departures_within_tolerance_feasible': 0.0,
                'departures_within_tolerance_infeasible': 0.0,
                '_departures_met_target_feasible': 0.0,
                '_departures_min_acceptable_feasible_met': 0.0,
                '_departures_within_tolerance_feasible_met': 0.0,
                'departure_deficit_sum': 0.0,
                'departure_shortfall_beyond_tolerance_sum': 0.0,
                'departure_surplus_sum': 0.0,
                'departure_absolute_error_sum': 0.0,
                'ev_departure_success_rate': None,
                'ev_departure_min_acceptable_rate': None,
                'ev_departure_within_tolerance_rate': None,
                'ev_departure_success_feasible_rate': None,
                'ev_departure_min_acceptable_feasible_rate': None,
                'ev_departure_within_tolerance_feasible_rate': None,
                'ev_departure_soc_deficit_mean': None,
                'ev_departure_shortfall_beyond_tolerance_mean': None,
                'ev_departure_soc_surplus_mean': None,
                'ev_departure_soc_absolute_error_mean': None,
                'ev_departure_tolerance_ratio': service_tolerance,
                'ev_charge_total_kwh': 0.0,
                'ev_v2g_export_total_kwh': 0.0,
                'ev_connected_soc_gain_total_kwh': 0.0,
                'ev_energy_accounting_shortfall_kwh': 0.0,
            }

        departures_total = 0
        departures_met = 0
        departures_min_acceptable = 0
        departures_within_tolerance = 0
        departures_target_feasible = 0
        departures_target_infeasible = 0
        departures_min_acceptable_feasible = 0
        departures_min_acceptable_infeasible = 0
        departures_within_tolerance_feasible = 0
        departures_within_tolerance_infeasible = 0
        departures_met_target_feasible = 0
        departures_min_acceptable_feasible_met = 0
        departures_within_tolerance_feasible_met = 0
        departure_deficit_sum = 0.0
        departure_shortfall_beyond_tolerance_sum = 0.0
        departure_surplus_sum = 0.0
        departure_absolute_error_sum = 0.0
        charge_total_kwh = 0.0
        v2g_export_total_kwh = 0.0
        connected_soc_gain_total_kwh = 0.0
        eps = self.EV_DEPARTURE_EPS

        for charger in self._chargers_for_metrics(building):
            consumption = np.array(charger.electricity_consumption[t_start:t_final + 1], dtype='float64')
            charge = getattr(charger, 'gross_energy_charge', None)
            discharge = getattr(charger, 'gross_energy_discharge', None)
            charge_total_kwh += self._sum_finite(charge[t_start:t_final + 1] if charge is not None else np.clip(consumption, 0.0, None))
            v2g_export_total_kwh += self._sum_finite(discharge[t_start:t_final + 1] if discharge is not None else np.clip(-consumption, 0.0, None))

            sim = charger.charger_simulation
            states = np.array(sim.electric_vehicle_charger_state, dtype='float64')
            required_soc = np.array(sim.electric_vehicle_required_soc_departure, dtype='float64')
            history_limit = min(
                t_final,
                len(states) - 1,
            )

            if history_limit < t_start:
                continue

            for t in range(t_start, history_limit + 1):
                current_state = states[t]
                next_state = states[t + 1] if t + 1 < len(states) else np.nan
                ev_ids = getattr(sim, 'electric_vehicle_id', None)
                session_ids = getattr(sim, 'electric_vehicle_session_id', None)
                current_ev_id = self._normal_ev_id(
                    self._safe_sequence_value(ev_ids, t)
                )
                next_ev_id = self._normal_ev_id(
                    self._safe_sequence_value(ev_ids, t + 1)
                )
                current_session_id = self._normal_ev_id(
                    self._safe_sequence_value(session_ids, t)
                )
                next_session_id = self._normal_ev_id(
                    self._safe_sequence_value(session_ids, t + 1)
                )
                departure_countdown = self._to_scalar(
                    self._safe_sequence_value(
                        getattr(sim, 'electric_vehicle_departure_time', None),
                        t,
                    ),
                    np.nan,
                )
                next_departure_countdown = self._to_scalar(
                    self._safe_sequence_value(
                        getattr(sim, 'electric_vehicle_departure_time', None),
                        t + 1,
                    ),
                    np.nan,
                )
                terminal_departure = (
                    t == len(states) - 1
                    and np.isfinite(departure_countdown)
                    # -1 is the schedule's unknown-departure sentinel.
                    and 0.0 <= departure_countdown <= 1.0 + self.EV_DEPARTURE_EPS
                )
                departure_transition = t + 1 < len(states) and (
                    next_state != 1
                    or (
                        current_session_id is not None
                        and next_session_id is not None
                        and next_session_id != current_session_id
                    )
                    or (
                        current_ev_id is not None
                        and next_ev_id is not None
                        and next_ev_id != current_ev_id
                    )
                    or (
                        current_session_id is None
                        and next_session_id is None
                        and np.isfinite(departure_countdown)
                        # Legacy schedules without explicit session identity
                        # expose a back-to-back boundary through a countdown
                        # reset while the charger remains connected.  A plain
                        # ``countdown <= 1`` check also counts ordinary
                        # departures one interval early, so require the next
                        # session's countdown to increase explicitly.
                        and 0.0 <= departure_countdown <= 1.0 + self.EV_DEPARTURE_EPS
                        and np.isfinite(next_departure_countdown)
                        and next_departure_countdown
                        > departure_countdown + self.EV_DEPARTURE_EPS
                    )
                )

                if current_state != 1 or not (departure_transition or terminal_departure):
                    continue

                ev = self._safe_sequence_value(charger.past_connected_evs, t)
                target_soc = self._normalize_soc_target(self._safe_sequence_value(required_soc, t))
                ev_departure_audit.record_departure(
                    self, audit_counts, building, charger, sim, ev, states, t, target_soc)
                if ev is None or getattr(ev, 'battery', None) is None:
                    continue

                if target_soc is None:
                    continue

                battery_soc = getattr(ev.battery, 'soc', [])
                if t >= len(battery_soc):
                    continue

                actual_soc = self._to_scalar(ev.battery.soc[t], np.nan)
                if not np.isfinite(actual_soc):
                    continue

                _, arrival_soc = self._ev_kpi_connection_boundary(charger, sim, ev, states, t)
                capacity_kwh = self._to_scalar(
                    getattr(ev.battery, 'capacity', np.nan),
                    np.nan,
                )
                if (
                    arrival_soc is not None
                    and np.isfinite(capacity_kwh)
                    and capacity_kwh > 0.0
                ):
                    connected_soc_gain_total_kwh += (
                        max(actual_soc - float(arrival_soc), 0.0)
                        * capacity_kwh
                    )

                departures_total += 1
                deficit = max(target_soc - actual_soc, 0.0)
                surplus = max(actual_soc - target_soc, 0.0)
                absolute_error = abs(actual_soc - target_soc)
                shortfall_beyond_tolerance = max(target_soc - service_tolerance - actual_soc, 0.0)
                min_acceptable_threshold = max(target_soc - service_tolerance, 0.0)
                within_tolerance_threshold = max(target_soc - within_tolerance, 0.0)
                target_feasible, min_acceptable_feasible, within_tolerance_feasible = (
                    self._ev_departure_thresholds_feasible(
                        building, charger, sim, ev, states, t,
                        (target_soc, min_acceptable_threshold, within_tolerance_threshold),
                    )
                )

                if absolute_error <= within_tolerance + eps:
                    departures_within_tolerance += 1
                if actual_soc + service_tolerance + eps >= target_soc:
                    departures_min_acceptable += 1
                departure_deficit_sum += deficit
                departure_surplus_sum += surplus
                departure_absolute_error_sum += absolute_error
                departure_shortfall_beyond_tolerance_sum += shortfall_beyond_tolerance
                if deficit <= eps:
                    departures_met += 1

                if target_feasible:
                    departures_target_feasible += 1
                    if deficit <= eps:
                        departures_met_target_feasible += 1
                else:
                    departures_target_infeasible += 1

                if min_acceptable_feasible:
                    departures_min_acceptable_feasible += 1
                    if actual_soc + service_tolerance + eps >= target_soc:
                        departures_min_acceptable_feasible_met += 1
                else:
                    departures_min_acceptable_infeasible += 1

                if within_tolerance_feasible:
                    departures_within_tolerance_feasible += 1
                    if absolute_error <= within_tolerance + eps:
                        departures_within_tolerance_feasible_met += 1
                else:
                    departures_within_tolerance_infeasible += 1

        success_rate = None if departures_total == 0 else departures_met / departures_total
        min_acceptable_rate = None if departures_total == 0 else departures_min_acceptable / departures_total
        within_tolerance_rate = None if departures_total == 0 else departures_within_tolerance / departures_total
        success_feasible_rate = None if departures_target_feasible == 0 else departures_met_target_feasible / departures_target_feasible
        min_acceptable_feasible_rate = (
            None if departures_min_acceptable_feasible == 0
            else departures_min_acceptable_feasible_met / departures_min_acceptable_feasible
        )
        within_tolerance_feasible_rate = (
            None if departures_within_tolerance_feasible == 0
            else departures_within_tolerance_feasible_met / departures_within_tolerance_feasible
        )
        deficit_mean = None if departures_total == 0 else departure_deficit_sum / departures_total
        shortfall_beyond_tolerance_mean = None if departures_total == 0 else departure_shortfall_beyond_tolerance_sum / departures_total
        surplus_mean = None if departures_total == 0 else departure_surplus_sum / departures_total
        absolute_error_mean = None if departures_total == 0 else departure_absolute_error_sum / departures_total

        return {
            '_departure_audit': audit_counts,
            'departures_total': float(departures_total),
            'departures_met': float(departures_met),
            'departures_min_acceptable': float(departures_min_acceptable),
            'departures_within_tolerance': float(departures_within_tolerance),
            'departures_target_feasible': float(departures_target_feasible),
            'departures_target_infeasible': float(departures_target_infeasible),
            'departures_min_acceptable_feasible': float(departures_min_acceptable_feasible),
            'departures_min_acceptable_infeasible': float(departures_min_acceptable_infeasible),
            'departures_within_tolerance_feasible': float(departures_within_tolerance_feasible),
            'departures_within_tolerance_infeasible': float(departures_within_tolerance_infeasible),
            '_departures_met_target_feasible': float(departures_met_target_feasible),
            '_departures_min_acceptable_feasible_met': float(departures_min_acceptable_feasible_met),
            '_departures_within_tolerance_feasible_met': float(departures_within_tolerance_feasible_met),
            'departure_deficit_sum': float(departure_deficit_sum),
            'departure_shortfall_beyond_tolerance_sum': float(departure_shortfall_beyond_tolerance_sum),
            'departure_surplus_sum': float(departure_surplus_sum),
            'departure_absolute_error_sum': float(departure_absolute_error_sum),
            'ev_departure_success_rate': success_rate,
            'ev_departure_min_acceptable_rate': min_acceptable_rate,
            'ev_departure_within_tolerance_rate': within_tolerance_rate,
            'ev_departure_success_feasible_rate': success_feasible_rate,
            'ev_departure_min_acceptable_feasible_rate': min_acceptable_feasible_rate,
            'ev_departure_within_tolerance_feasible_rate': within_tolerance_feasible_rate,
            'ev_departure_soc_deficit_mean': deficit_mean,
            'ev_departure_shortfall_beyond_tolerance_mean': shortfall_beyond_tolerance_mean,
            'ev_departure_soc_surplus_mean': surplus_mean,
            'ev_departure_soc_absolute_error_mean': absolute_error_mean,
            'ev_departure_tolerance_ratio': service_tolerance,
            'ev_charge_total_kwh': float(charge_total_kwh),
            'ev_v2g_export_total_kwh': float(v2g_export_total_kwh),
            'ev_connected_soc_gain_total_kwh': float(connected_soc_gain_total_kwh),
            'ev_energy_accounting_shortfall_kwh': float(max(
                connected_soc_gain_total_kwh - charge_total_kwh,
                0.0,
            )),
        }

    def _chargers_for_metrics(self, building) -> Sequence:
        topology_service = getattr(self.env, '_topology_service', None)
        if (
            getattr(self.env, 'topology_mode', 'static') == 'dynamic'
            and topology_service is not None
            and hasattr(topology_service, 'historical_chargers')
        ):
            chargers = list(topology_service.historical_chargers(building.name))
            if chargers:
                return chargers

        return list(building.electric_vehicle_chargers or [])

    def deferrable_service_audit(self):
        return deferrable_service_audit.environment_audit(self)

    def _deferrable_appliances_for_metrics(self, building) -> Sequence:
        topology_service = getattr(self.env, '_topology_service', None)
        if (
            getattr(self.env, 'topology_mode', 'static') == 'dynamic'
            and topology_service is not None
            and hasattr(topology_service, 'historical_deferrable_appliances')
        ):
            appliances = list(topology_service.historical_deferrable_appliances(building.name))
            if appliances:
                return appliances

        return list(getattr(building, 'deferrable_appliances', []) or [])

    def _storages_for_metrics(self, building) -> Sequence:
        topology_service = getattr(self.env, '_topology_service', None)
        if (
            getattr(self.env, 'topology_mode', 'static') == 'dynamic'
            and topology_service is not None
            and hasattr(topology_service, 'historical_storages')
        ):
            storages = list(topology_service.historical_storages(building.name))
            if storages:
                return storages

        storage = getattr(building, 'electrical_storage', None)
        return [] if storage is None else [storage]

    def _compute_bess_metrics(self, building, *, t_start: int = 0, t_final: Optional[int] = None) -> Dict[str, float]:
        return kpi_equipment.compute_bess_metrics(self, building, t_start=t_start, t_final=t_final)

    def _compute_pv_metrics(self, building, *, t_start: int = 0, t_final: Optional[int] = None) -> Dict[str, float]:
        return kpi_equipment.compute_pv_metrics(self, building, t_start=t_start, t_final=t_final)

    def _compute_district_pv_metrics(
        self,
        buildings: Sequence,
        building_windows: Mapping[str, Tuple[int, int]],
        *,
        final_t: int,
    ) -> Dict[str, float]:
        return kpi_equipment.compute_district_pv_metrics(self, buildings, building_windows, final_t=final_t)

    def _compute_phase_metrics(self, building, *, t_start: int = 0, t_final: Optional[int] = None) -> Dict[str, object]:
        return kpi_equipment.compute_phase_metrics(self, building, t_start=t_start, t_final=t_final)

    def _collect_market_totals(self, building_names: List[str]) -> Tuple[Mapping[str, Mapping[str, float]], Mapping[str, float]]:
        history = getattr(self.env, '_community_market_settlement_history', []) or []
        if isinstance(history, MarketSettlementHistory):
            return history.market_totals(building_names)
        by_building = {
            name: {
                'community_local_import_total_kwh': 0.0,
                'community_local_export_total_kwh': 0.0,
                'community_grid_import_after_local_total_kwh': 0.0,
                'community_grid_export_after_local_total_kwh': 0.0,
                'community_settled_cost_total_eur': 0.0,
                'community_counterfactual_cost_total_eur': 0.0,
                'community_market_savings_total_eur': 0.0,
            }
            for name in building_names
        }

        for rows in history:
            for row in rows:
                name = row.get('building')
                if name not in by_building:
                    continue

                target = by_building[name]
                target['community_local_import_total_kwh'] += self._to_scalar(row.get('local_import_kwh'), 0.0)
                target['community_local_export_total_kwh'] += self._to_scalar(row.get('local_export_kwh'), 0.0)
                target['community_grid_import_after_local_total_kwh'] += self._to_scalar(row.get('grid_import_kwh'), 0.0)
                target['community_grid_export_after_local_total_kwh'] += self._to_scalar(row.get('grid_export_kwh'), 0.0)
                target['community_settled_cost_total_eur'] += self._to_scalar(row.get('settled_cost_eur', row.get('settled_cost')), 0.0)
                target['community_counterfactual_cost_total_eur'] += self._to_scalar(row.get('counterfactual_cost_eur'), 0.0)
                target['community_market_savings_total_eur'] += self._to_scalar(row.get('market_savings_eur'), 0.0)

        district = {
            key: float(sum(values[key] for values in by_building.values()))
            for key in [
                'community_local_import_total_kwh',
                'community_local_export_total_kwh',
                'community_grid_import_after_local_total_kwh',
                'community_grid_export_after_local_total_kwh',
                'community_settled_cost_total_eur',
                'community_counterfactual_cost_total_eur',
                'community_market_savings_total_eur',
            ]
        }

        return by_building, district

    @staticmethod
    def _resolve_step_value(value, time_step: int, default: float = 0.0) -> float:
        if isinstance(value, (list, tuple, np.ndarray)):
            if len(value) == 0:
                return float(default)
            index = min(max(time_step, 0), len(value) - 1)
            return CityLearnKPIService._to_scalar(value[index], default)

        return CityLearnKPIService._to_scalar(value, default)

    @staticmethod
    def _allocate_weighted_share_import(imports: np.ndarray, traded_kwh: float, weights: np.ndarray) -> np.ndarray:
        allocations = np.zeros_like(imports, dtype='float64')
        remaining = max(float(traded_kwh), 0.0)
        eps = 1e-9
        weights = np.array(weights, dtype='float64')
        weights = np.clip(weights, 0.0, None)

        while remaining > eps:
            needs = imports - allocations
            active = needs > eps
            if not np.any(active):
                break

            active_weights = weights[active]
            sum_weights = float(active_weights.sum())

            if sum_weights <= eps:
                # Fallback to equal-share for active importers when weights are invalid.
                share = remaining / float(np.count_nonzero(active))
                granted = np.minimum(share, needs[active])
            else:
                granted = np.minimum(remaining * (active_weights / sum_weights), needs[active])

            granted_total = float(granted.sum())
            if granted_total <= eps:
                break

            allocations[active] += granted
            remaining -= granted_total

        return allocations

    def _default_building_conditions(self, building, control_condition, baseline_condition, *, evaluation_condition_cls, dynamics_building_cls):
        if isinstance(building, dynamics_building_cls):
            building_control_condition = (
                evaluation_condition_cls.WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV
                if control_condition is None else control_condition
            )
            building_baseline_condition = (
                evaluation_condition_cls.WITHOUT_STORAGE_AND_PARTIAL_LOAD_BUT_WITH_PV
                if baseline_condition is None else baseline_condition
            )
        else:
            building_control_condition = (
                evaluation_condition_cls.WITH_STORAGE_AND_PV
                if control_condition is None else control_condition
            )
            building_baseline_condition = (
                evaluation_condition_cls.WITHOUT_STORAGE_BUT_WITH_PV
                if baseline_condition is None else baseline_condition
            )

        return building_control_condition, building_baseline_condition

    def _get_kpi_buildings(self) -> List:
        env = self.env

        if getattr(env, 'topology_mode', 'static') != 'dynamic':
            return list(env.buildings)

        topology_service = getattr(env, '_topology_service', None)
        if topology_service is None:
            return list(env.buildings)

        population = current_population(self)
        lifecycle = (population.lifecycle if population is not None
                     else getattr(env, 'topology_member_lifecycle', {})) or {}
        pool = dict(getattr(topology_service, 'member_pool', {}) or {})
        if len(pool) == 0:
            return list(env.buildings)

        active_or_historical = []
        current_active_names = {b.name for b in env.buildings}
        for member_id, building in pool.items():
            state = lifecycle.get(member_id, {})
            if state.get('born_at') is None and member_id not in current_active_names:
                continue
            active_or_historical.append(building)

        return active_or_historical

    def _building_active_window(self, building) -> Tuple[int, int]:
        env = self.env
        final_t = int(max(getattr(env, 'time_step', 0), 0))

        if getattr(env, 'topology_mode', 'static') != 'dynamic':
            return 0, int(min(max(getattr(building, 'time_step', 0), 0), final_t))

        population = current_population(self)
        lifecycle = (population.lifecycle if population is not None
                     else getattr(env, 'topology_member_lifecycle', {})) or {}
        state = lifecycle.get(getattr(building, 'name', ''), {}) or {}

        born_at = state.get('born_at', 0)
        removed_at = state.get('removed_at', None)
        if born_at is None:
            return 1, 0

        start = int(max(born_at, 0))
        if removed_at is None:
            end = final_t
        else:
            end = min(final_t, int(removed_at) - 1)

        return start, end

    def _thermal_values(self, building, values, t_start=0, t_final=None):
        """Select completed active samples without inserting fictitious zero temperatures."""
        array = np.asarray(values, dtype=float)
        upper = min(len(array), int(getattr(self.env, 'time_step', len(array))))
        end = upper if t_final is None else min(upper, int(t_final)+1)
        indices = np.arange(max(0, int(t_start)), end)
        if getattr(self.env, 'topology_mode', 'static') == 'dynamic':
            population = current_population(self)
            if population is None:
                history = self.env._topology_service
                indices = np.array([i for i in indices if building.name in history.active_member_ids_at(int(i))], dtype=int)
            else:
                indices = indices[population.mask(building.name, upper)[indices]]
        return array[indices]

    def _service_energy(self, building, t_start=0, t_final=None):
        """Demand/device histories use dataset energy; tank balances already use control kWh."""
        take = lambda name: self._thermal_values(building, getattr(building, name), t_start, t_final)
        scale = float(getattr(building, 'time_step_ratio', 1.) or 1.)
        expected = np.array([take(name)*scale for name in ('cooling_demand','heating_demand','dhw_demand','non_shiftable_load')]).T
        served = np.array([take('energy_from_cooling_device')*scale+take('energy_from_cooling_storage'),
                           take('energy_from_heating_device')*scale+take('energy_from_heating_storage'),
                           take('energy_from_dhw_device')*scale+take('energy_from_dhw_storage'),
                           take('energy_to_non_shiftable_load')*scale]).T
        return expected, served

    @population_scope
    @settled_cost_scope
    def family_audit(self, comfort_band=None, control_condition=None, baseline_condition=None, *, progress=None):
        from citylearn.internal.kpi_family_audit import thermal_counts, thermal_metrics, pool_thermal, equity_metrics
        from citylearn.citylearn import EvaluationCondition
        from citylearn.building import DynamicsBuilding
        rows, counts, costs, conditions = {}, [], [], {}
        buildings = self._get_kpi_buildings()
        for member_index, building in enumerate(buildings, 1):
            with span(progress, 'thermal_service', member=building.name, member_index=member_index, member_count=len(buildings)):
                take = lambda name: self._thermal_values(building, getattr(building, name))
                expected, served = self._service_energy(building)
                bands = take('comfort_band') if comfort_band is None else comfort_band
                count = thermal_counts(take('indoor_dry_bulb_temperature'),take('indoor_dry_bulb_temperature_cooling_set_point'),
                    take('indoor_dry_bulb_temperature_heating_set_point'),bands,take('occupant_count'),expected,served,
                    take('power_outage_signal'),self.env.seconds_per_time_step/3600.)
                counts.append(count); rows[building.name] = thermal_metrics(count)
                dynamic = isinstance(building, DynamicsBuilding)
                control = control_condition if control_condition is not None else (EvaluationCondition.WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV if dynamic else EvaluationCondition.WITH_STORAGE_AND_PV)
                baseline = baseline_condition if baseline_condition is not None else (EvaluationCondition.WITHOUT_STORAGE_AND_PARTIAL_LOAD_BUT_WITH_PV if dynamic else EvaluationCondition.WITHOUT_STORAGE_BUT_WITH_PV)
                conditions[building.name] = dict(control=getattr(control,'name',control.value), reference=getattr(baseline,'name',baseline.value))
                if getattr(self.env, 'community_market_enabled', False):
                    control_costs, baseline_costs = self._market_cost_series(
                        control_condition, baseline_condition,
                        evaluation_condition_cls=EvaluationCondition, dynamics_building_cls=DynamicsBuilding,
                    )
                    costs.append((self._sum_finite(control_costs[building.name]),
                                  self._sum_finite(baseline_costs[building.name])))
                else:
                    costs.append((self._sum_finite(self._energy_values(building,getattr(building,'net_electricity_consumption_cost'+control.value))),
                                  self._sum_finite(self._energy_values(building,getattr(building,'net_electricity_consumption_cost'+baseline.value)))))
        return dict(buildings=rows,district=thermal_metrics(pool_thermal(counts)),equity=equity_metrics(costs),equity_conditions=conditions)

    def _building_days(self, building, t_start, t_final):
        if not hasattr(self.env, 'time_step'):
            return self._window_days(t_start, t_final, self.env.seconds_per_time_step)
        count = self._energy_values(building, np.ones(max(int(t_final)+1, 0)))
        active_steps = float(count[max(int(t_start), 0):].sum())
        return active_steps*self.env.seconds_per_time_step/86400.

    def _energy_values(self, building, values):
        """Energy belongs to executed active intervals, not the terminal observation."""
        array = np.asarray(values, dtype='float64')[:int(getattr(self.env, 'time_step', len(values)))].copy()
        if building is self.env or getattr(self.env, 'topology_mode', 'static') != 'dynamic':
            return array
        population = current_population(self)
        if population is not None:
            array[~population.mask(building.name, len(array), energy=True)] = 0.0
            return array
        history = self.env._topology_service._active_member_history
        steps = sorted(history)
        mask = np.zeros(len(array), dtype=bool)
        for i, start in enumerate(steps):
            end = steps[i + 1] if i + 1 < len(steps) else len(array)
            if building.name in history[start]:
                mask[start:min(end, len(array))] = True
        array[~mask] = 0.0
        return array

    @staticmethod
    def _slice_window(values, t_start: int, t_final: int) -> np.ndarray:
        array = np.array(values, dtype='float64')
        if array.size == 0:
            return np.zeros((0,), dtype='float64')

        lo = max(int(t_start), 0)
        hi = min(int(t_final), array.size - 1)
        if hi < lo:
            return np.zeros((0,), dtype='float64')
        return array[lo:hi + 1]

    @staticmethod
    def _cost_last(values: np.ndarray, fn, **kwargs) -> float:
        if values.size == 0:
            return 0.0
        out = fn(values, **kwargs) if kwargs else fn(values)
        if len(out) == 0:
            return 0.0
        return float(out[-1])

    def _condition_settled_cost_totals(
        self,
        *,
        condition_by_building: Mapping[str, object],
    ) -> Tuple[Mapping[str, float], float]:
        series = self._settled_cost_series(condition_by_building=condition_by_building)
        totals = {}
        for name, values in series.items():
            total = 0.0
            # Sequential sum in step order, as the totals were accumulated before; inactive steps add 0.0.
            for value in values.tolist():
                total += value
            totals[name] = total

        district_total = float(sum(totals.values()))
        return totals, district_total

    def _market_cost_series(
        self,
        control_condition,
        baseline_condition,
        *,
        evaluation_condition_cls,
        dynamics_building_cls,
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """Control and reference cost series per member, both settled by the community market."""
        control_condition_by_building = {}
        baseline_condition_by_building = {}
        for building in self._get_kpi_buildings():
            c_cond, b_cond = self._default_building_conditions(
                building,
                control_condition,
                baseline_condition,
                evaluation_condition_cls=evaluation_condition_cls,
                dynamics_building_cls=dynamics_building_cls,
            )
            control_condition_by_building[building.name] = c_cond
            baseline_condition_by_building[building.name] = b_cond

        return (
            self._settled_cost_series(condition_by_building=control_condition_by_building),
            self._settled_cost_series(condition_by_building=baseline_condition_by_building),
        )

    def _settled_cost_series(
        self,
        *,
        condition_by_building: Mapping[str, object],
    ) -> Dict[str, np.ndarray]:
        """Per-member cost series with the community market settled over each member's condition flows.

        The stored control cost is settled during simulation, but reference conditions are not;
        comparing the two would credit the market's savings to the controller. Every cost
        comparison therefore settles both sides here with the same rules.
        """
        cache = getattr(self, '_settled_cost_cache', None)
        cache_key = tuple(sorted(
            (name, getattr(condition, 'value', condition)) for name, condition in condition_by_building.items()
        ))
        if cache is not None and cache_key in cache:
            return cache[cache_key]

        env = self.env
        buildings = self._get_kpi_buildings()
        building_names = [b.name for b in buildings]
        windows = {b.name: self._building_active_window(b) for b in buildings}
        step_count = max(int(getattr(env, 'time_step', 0)), 0)
        series = {name: np.zeros(step_count, dtype='float64') for name in building_names}
        if len(building_names) == 0:
            return series

        final_t = int(max(getattr(env, 'time_step', 0), 0))
        ratio = self._to_scalar(getattr(env, 'community_market_sell_ratio', 0.8), 0.8)
        ratio = min(max(ratio, 0.0), 1.0)
        weights_config = getattr(env, 'community_market_import_member_weights', {}) or {}
        weights = np.array(
            [
                self._to_scalar(weights_config.get(name, 1.0), 1.0)
                for name in building_names
            ],
            dtype='float64',
        )
        weight_by_name = {name: float(weight) for name, weight in zip(building_names, weights)}
        net_series_by_name: Dict[str, np.ndarray] = {}
        price_series_by_name: Dict[str, np.ndarray] = {}

        for building in buildings:
            condition = condition_by_building.get(building.name)
            if condition is None:
                continue

            net_series_by_name[building.name] = np.asarray(
                self._energy_values(building, getattr(building, f'net_electricity_consumption{condition.value}')),
                dtype='float64',
            )
            price_series_by_name[building.name] = np.asarray(
                building.pricing.electricity_pricing,
                dtype='float64',
            )

        for t in range(min(final_t + 1, int(env.time_step))):
            net_values = []
            active_buildings_t = []
            active_weights_t = []
            for building in buildings:
                t_start, t_end = windows.get(building.name, (0, -1))
                if not (t_start <= t <= t_end):
                    continue
                if getattr(env, 'topology_mode', 'static') == 'dynamic':
                    population = current_population(self)
                    active = (building.name in env._topology_service.active_member_ids_at(t)
                              if population is None else population.mask(building.name, final_t)[t])
                    if not active:
                        continue

                net_series = net_series_by_name.get(building.name)
                if net_series is None:
                    continue

                net_values.append(self._to_scalar(net_series[t] if t < len(net_series) else np.nan, 0.0))
                active_buildings_t.append(building)
                active_weights_t.append(weight_by_name.get(building.name, 1.0))

            if len(active_buildings_t) == 0:
                continue

            net_values = np.array(net_values, dtype='float64')
            imports = np.clip(net_values, 0.0, None)
            exports = np.clip(-net_values, 0.0, None)
            total_import = float(imports.sum())
            total_export = float(exports.sum())
            traded_kwh = min(total_import, total_export) if getattr(env, 'community_market_local_enabled', True) else 0.0

            if total_import > 0.0 and traded_kwh > 0.0:
                local_import = self._allocate_weighted_share_import(
                    imports,
                    traded_kwh,
                    np.array(active_weights_t, dtype='float64'),
                )
            else:
                local_import = np.zeros_like(imports, dtype='float64')

            if total_export > 0.0 and traded_kwh > 0.0:
                local_export = exports * (traded_kwh / total_export)
            else:
                local_export = np.zeros_like(exports, dtype='float64')

            for idx, building in enumerate(active_buildings_t):
                price_series = price_series_by_name.get(building.name)
                grid_import_price = self._to_scalar(
                    price_series[t] if price_series is not None and t < len(price_series) else np.nan,
                    0.0,
                )
                from citylearn.community_dataset import settlement_prices
                grid_export_price, local_buy_price, local_sell_price = settlement_prices(env, building.name, t, grid_import_price)
                grid_export_remaining = max(exports[idx] - local_export[idx], 0.0)
                grid_import_remaining = max(imports[idx] - local_import[idx], 0.0)

                cost = (
                    grid_import_remaining * grid_import_price
                    + local_import[idx] * local_buy_price
                    - local_export[idx] * local_sell_price
                    - grid_export_remaining * grid_export_price
                )
                series[building.name][t] = float(cost)

        if cache is not None:
            cache[cache_key] = series

        return series

    @population_scope
    @settled_cost_scope
    def evaluate(
        self,
        control_condition=None,
        baseline_condition=None,
        comfort_band: float = None,
        *,
        evaluation_condition_cls,
        dynamics_building_cls,
        progress=None,
    ) -> pd.DataFrame:
        """Assemble KPI families in the established legacy/extended row order."""
        simulated_days = self._simulated_days(self.env)
        buildings = self._get_kpi_buildings()
        windows = {building.name: self._building_active_window(building) for building in buildings}
        groups = {building.name: getattr(building, 'equity_group', None) for building in buildings}
        benefits = {}
        equipment = kpi_equipment.EquipmentKPIAccumulator(self)
        legacy_frames, building_rows = [], []

        for member_index, building in enumerate(buildings, 1):
            t_start, t_end = windows.get(building.name, (0, -1))
            if t_end < t_start:
                continue
            with span(progress, 'member', member=building.name, member_index=member_index, member_count=len(buildings)):
                legacy, rows, benefit = run(progress, 'energy_and_service', kpi_energy.building_records,
                    self, building, t_start, t_end, control_condition, baseline_condition,
                    comfort_band, evaluation_condition_cls, dynamics_building_cls,
                )
                legacy_frames.append(legacy)
                building_rows.extend(rows)
                if benefit is not None:
                    benefits[building.name] = float(benefit)
                building_rows.extend(equipment.building_records(building, t_start, t_end, progress=progress))

        legacy_building = (pd.concat(legacy_frames, ignore_index=True) if legacy_frames
                           else pd.DataFrame(columns=['cost_function', 'value', 'name']))
        legacy_building['level'] = 'building'
        legacy, district_rows = run(progress, 'district_energy', kpi_energy.district_records,
            self, legacy_building, control_condition, baseline_condition,
            evaluation_condition_cls, simulated_days,
        )
        district_rows.extend(run(progress, 'district_equipment', equipment.district_records, buildings, windows, simulated_days))
        market_building, market_district = run(progress, 'market', kpi_community.market_records, self, buildings, windows, simulated_days)
        building_rows.extend(market_building)
        district_rows.extend(market_district)
        district_rows.extend(run(progress, 'equity', kpi_community.equity_records,
            self, [building.name for building in buildings], benefits, groups))
        for family in (kpi_service_metrics.deferrable_records, kpi_service_metrics.escalator_records):
            rows, district = run(progress, family.__name__, family, self, buildings)
            building_rows.extend(rows)
            district_rows.extend(district)
        return pd.concat([legacy, pd.DataFrame(district_rows), pd.DataFrame(building_rows)],
                         ignore_index=True, sort=False)

    @staticmethod
    def _v2_name(
        level: str,
        family: str,
        subfamily: str,
        metric: str,
        variant: Optional[str] = None,
        unit: Optional[str] = None,
    ) -> str:
        tokens = [level, family, subfamily, metric]

        if variant not in (None, ''):
            tokens.append(str(variant))

        if unit not in (None, ''):
            tokens.append(str(unit))

        return '_'.join(tokens)

    @classmethod
    def total_ratio_components(cls, level: str) -> Dict[str, Tuple[str, str, bool]]:
        """V2 ratio KPIs defined as a control total over a reference total.

        Maps each ratio name to `(control_total_name, reference_total_name, signed)`.
        Only ratios whose two totals add up across members are listed, so a pooled
        ratio can be rebuilt from summed totals. `signed` totals can be negative and
        use `_signed_ratio`; the others use `_safe_div`.
        """
        v2 = cls._v2_name
        components: Dict[str, Tuple[str, str, bool]] = {}

        for reference, subfamily in (('baseline', 'ratio_to_baseline'), ('business_as_usual', 'ratio_to_business_as_usual')):
            for family, unit, signed in (('cost', 'eur', True), ('emissions', 'kgco2', False)):
                components[v2(level, family, subfamily, 'total', None, 'ratio')] = (
                    v2(level, family, 'total', 'control', None, unit),
                    v2(level, family, 'total', reference, None, unit),
                    signed,
                )

            for metric in ('import', 'export', 'net_exchange'):
                components[v2(level, 'energy_grid', subfamily, f'{metric}_total', None, 'ratio')] = (
                    v2(level, 'energy_grid', 'total', metric, 'control', 'kwh'),
                    v2(level, 'energy_grid', 'total', metric, reference, 'kwh'),
                    metric == 'net_exchange',
                )

        # Business-as-usual references of additive equipment and service totals.
        for family, subfamily, metric, unit, ratio_metric in (
            ('solar_self_consumption', 'total', 'generation', 'kwh', 'generation_total'),
            ('solar_self_consumption', 'total', 'export', 'kwh', 'export_total'),
            ('ev', 'total', 'charge', 'kwh', 'charge_total'),
            ('ev', 'total', 'v2g_export', 'kwh', 'v2g_export_total'),
            ('battery', 'total', 'charge', 'kwh', 'charge'),
            ('battery', 'total', 'discharge', 'kwh', 'discharge'),
            ('battery', 'total', 'throughput', 'kwh', 'throughput'),
            ('deferrable_appliance', 'service', 'completed_cycles', 'count', 'completed_cycles'),
            ('deferrable_appliance', 'service', 'missed_cycles', 'count', 'missed_cycles'),
            ('deferrable_appliance', 'service', 'served_energy_total', 'kwh', 'served_energy_total'),
            ('deferrable_appliance', 'service', 'unserved_energy_total', 'kwh', 'unserved_energy_total'),
        ):
            components[v2(level, family, 'ratio_to_business_as_usual', ratio_metric, None, 'ratio')] = (
                v2(level, family, subfamily, metric, None, unit),
                v2(level, family, subfamily, metric, 'business_as_usual', unit),
                False,
            )

        return components

    def evaluate_legacy(
        self,
        control_condition=None,
        baseline_condition=None,
        comfort_band: float = None,
        *,
        evaluation_condition_cls,
        dynamics_building_cls,
    ) -> pd.DataFrame:
        all_metrics = self.evaluate(
            control_condition=control_condition,
            baseline_condition=baseline_condition,
            comfort_band=comfort_band,
            evaluation_condition_cls=evaluation_condition_cls,
            dynamics_building_cls=dynamics_building_cls,
        )

        legacy = all_metrics[all_metrics['cost_function'].isin(self.LEGACY_COST_FUNCTIONS)].copy()
        return legacy.reset_index(drop=True)

    def _add_business_as_usual_records(
        self,
        records: Dict[Tuple[str, str, str], Dict[str, object]],
        v2,
        simulated_days: float,
        *,
        evaluation_condition_cls,
        dynamics_building_cls,
    ):
        env = self.env
        result = env.run_business_as_usual_baseline()
        bau_df = result.kpis_v2
        if bau_df.empty:
            return

        bau_lookup = {
            (str(row['level']), str(row['name']), str(row['cost_function'])): row['value']
            for _, row in bau_df.iterrows()
        }

        # These references use the same provenance definition and physical
        # boundary because the BAU sidecar executes the same passive ledger.
        for (level, name, metric), record in list(records.items()):
            if metric.startswith(f'{level}_energy_provenance_'):
                reference = bau_lookup.get((level, name, metric))
                stem, unit = metric.rsplit('_', 1)
                reference_key = f'{stem}_business_as_usual_{unit}'
                records[(level, name, reference_key)] = dict(record, cost_function=reference_key, value=reference)
                a, b = self._to_scalar(record['value'], np.nan), self._to_scalar(reference, np.nan)
                delta_key = f'{stem}_delta_to_business_as_usual_{unit}'
                records[(level, name, delta_key)] = dict(record, cost_function=delta_key,
                    value=float(a-b) if np.isfinite(a) and np.isfinite(b) else None)

        def put(level: str, name: str, cost_function: str, value):
            records[(level, name, cost_function)] = {
                'cost_function': cost_function,
                'value': value,
                'name': name,
                'level': level,
            }

        def current(level: str, name: str, cost_function: str):
            return records.get((level, name, cost_function), {}).get('value')

        def bau(level: str, name: str, cost_function: str):
            return bau_lookup.get((level, name, cost_function))

        def finite_delta(a, b):
            a = self._to_scalar(a, np.nan)
            b = self._to_scalar(b, np.nan)
            return None if not (np.isfinite(a) and np.isfinite(b)) else float(a - b)

        def add_total_daily_ratio(
            level: str,
            name: str,
            *,
            family: str,
            total_subfamily: str,
            control_total_metric: str,
            bau_total_metric: str,
            delta_total_metric: str,
            daily_subfamily: str,
            control_daily_metric: str,
            bau_daily_metric: str,
            delta_daily_metric: str,
            ratio_metric: str,
            unit: str,
            control_variant: Optional[str] = None,
            bau_variant: Optional[str] = None,
            delta_variant: Optional[str] = None,
            signed: bool = False,
        ):
            control_total_key = v2(level, family, total_subfamily, control_total_metric, control_variant, unit)
            bau_total = bau(level, name, control_total_key)
            control_total = current(level, name, control_total_key)
            put(level, name, v2(level, family, total_subfamily, bau_total_metric, bau_variant, unit), bau_total)
            put(
                level,
                name,
                v2(level, family, total_subfamily, delta_total_metric, delta_variant, unit),
                finite_delta(control_total, bau_total),
            )
            put(
                level,
                name,
                v2(level, family, 'ratio_to_business_as_usual', ratio_metric, None, 'ratio'),
                (self._signed_ratio if signed else self._safe_div)(control_total, bau_total),
            )

            control_daily_key = v2(level, family, daily_subfamily, control_daily_metric, control_variant, unit)
            bau_daily = bau(level, name, control_daily_key)
            control_daily = current(level, name, control_daily_key)
            put(level, name, v2(level, family, daily_subfamily, bau_daily_metric, bau_variant, unit), bau_daily)
            put(
                level,
                name,
                v2(level, family, daily_subfamily, delta_daily_metric, delta_variant, unit),
                finite_delta(control_daily, bau_daily),
            )

        def add_plain_metric(
            level: str,
            name: str,
            *,
            family: str,
            subfamily: str,
            metric: str,
            unit: str,
            current_key: str,
            ratio_metric: str,
        ):
            bau_value = bau(level, name, current_key)
            control_value = current(level, name, current_key)
            put(level, name, v2(level, family, subfamily, metric, 'business_as_usual', unit), bau_value)
            put(
                level,
                name,
                v2(level, family, subfamily, metric, 'delta_to_business_as_usual', unit),
                finite_delta(control_value, bau_value),
            )
            put(
                level,
                name,
                v2(level, family, 'ratio_to_business_as_usual', ratio_metric, None, 'ratio'),
                self._safe_div(control_value, bau_value),
            )

        names_by_level = {}
        for level, name, _ in records.keys():
            names_by_level.setdefault(level, set()).add(name)

        for level, names in names_by_level.items():
            for name in names:
                add_total_daily_ratio(
                    level,
                    name,
                    family='cost',
                    total_subfamily='total',
                    control_total_metric='control',
                    bau_total_metric='business_as_usual',
                    delta_total_metric='delta_to_business_as_usual',
                    daily_subfamily='daily_average',
                    control_daily_metric='control',
                    bau_daily_metric='business_as_usual',
                    delta_daily_metric='delta_to_business_as_usual',
                    ratio_metric='total',
                    unit='eur',
                    signed=True,
                )
                add_total_daily_ratio(
                    level,
                    name,
                    family='emissions',
                    total_subfamily='total',
                    control_total_metric='control',
                    bau_total_metric='business_as_usual',
                    delta_total_metric='delta_to_business_as_usual',
                    daily_subfamily='daily_average',
                    control_daily_metric='control',
                    bau_daily_metric='business_as_usual',
                    delta_daily_metric='delta_to_business_as_usual',
                    ratio_metric='total',
                    unit='kgco2',
                )

                for metric, ratio_metric in [
                    ('import', 'import_total'),
                    ('export', 'export_total'),
                    ('net_exchange', 'net_exchange_total'),
                ]:
                    add_total_daily_ratio(
                        level,
                        name,
                        family='energy_grid',
                        total_subfamily='total',
                        control_total_metric=metric,
                        bau_total_metric=metric,
                        delta_total_metric=metric,
                        daily_subfamily='daily_average',
                        control_daily_metric=metric,
                        bau_daily_metric=metric,
                        delta_daily_metric=metric,
                        ratio_metric=ratio_metric,
                        unit='kwh',
                        control_variant='control',
                        bau_variant='business_as_usual',
                        delta_variant='delta_to_business_as_usual',
                        signed=metric == 'net_exchange',
                    )

                for metric, unit in [
                    ('charge', 'kwh'),
                    ('v2g_export', 'kwh'),
                ]:
                    add_plain_metric(
                        level,
                        name,
                        family='ev',
                        subfamily='total',
                        metric=metric,
                        unit=unit,
                        current_key=v2(level, 'ev', 'total', metric, None, unit),
                        ratio_metric=f'{metric}_total',
                    )

                for metric, unit in [
                    ('charge', 'kwh'),
                    ('discharge', 'kwh'),
                    ('throughput', 'kwh'),
                    ('equivalent_full_cycles', 'count'),
                    ('capacity_fade', 'ratio'),
                ]:
                    subfamily = 'health' if metric in {'equivalent_full_cycles', 'capacity_fade'} else 'total'
                    add_plain_metric(
                        level,
                        name,
                        family='battery',
                        subfamily=subfamily,
                        metric=metric,
                        unit=unit,
                        current_key=v2(level, 'battery', subfamily, metric, None, unit),
                        ratio_metric=metric,
                    )

                for metric in ['generation', 'export']:
                    add_total_daily_ratio(
                        level,
                        name,
                        family='solar_self_consumption',
                        total_subfamily='total',
                        control_total_metric=metric,
                        bau_total_metric=metric,
                        delta_total_metric=metric,
                        daily_subfamily='daily_average',
                        control_daily_metric=metric,
                        bau_daily_metric=metric,
                        delta_daily_metric=metric,
                        ratio_metric=f'{metric}_total',
                        unit='kwh',
                        bau_variant='business_as_usual',
                        delta_variant='delta_to_business_as_usual',
                    )

                add_plain_metric(
                    level,
                    name,
                    family='solar_self_consumption',
                    subfamily='ratio',
                    metric='self_consumption',
                    unit='ratio',
                    current_key=v2(level, 'solar_self_consumption', 'ratio', 'self_consumption', None, 'ratio'),
                    ratio_metric='self_consumption',
                )

                for metric, unit in [
                    ('completed_cycles', 'count'),
                    ('missed_cycles', 'count'),
                    ('service_level', 'ratio'),
                    ('served_energy_total', 'kwh'),
                    ('unserved_energy_total', 'kwh'),
                    ('average_start_delay', 'hours'),
                ]:
                    add_plain_metric(
                        level,
                        name,
                        family='deferrable_appliance',
                        subfamily='service',
                        metric=metric,
                        unit=unit,
                        current_key=v2(level, 'deferrable_appliance', 'service', metric, None, unit),
                        ratio_metric=metric,
                    )

        self._add_business_as_usual_shape_records(records, result.env, v2, simulated_days)

    def _add_business_as_usual_shape_records(
        self,
        records: Dict[Tuple[str, str, str], Dict[str, object]],
        bau_env: "CityLearnEnv",
        v2,
        simulated_days: float,
    ):
        env = self.env
        daily_steps = self._window_steps(24.0 * 3600.0, env.seconds_per_time_step)
        monthly_steps = self._window_steps(730.0 * 3600.0, env.seconds_per_time_step)
        current_net = np.array(env.net_electricity_consumption, dtype='float64')
        bau_net = np.array(bau_env.net_electricity_consumption, dtype='float64')
        step_hours = max(float(env.seconds_per_time_step) / 3600.0, 1.0e-12)
        current_net_power = current_net / step_hours
        bau_net_power = bau_net / step_hours

        metrics = [
            ('ramping_average', self._ramping_final(current_net_power), self._ramping_final(bau_net_power), 'kw'),
            (
                'load_factor_penalty_daily_average',
                self._one_minus_load_factor_final(current_net_power, window=daily_steps),
                self._one_minus_load_factor_final(bau_net_power, window=daily_steps),
                'ratio',
            ),
            (
                'load_factor_penalty_monthly_average',
                self._one_minus_load_factor_final(current_net_power, window=monthly_steps),
                self._one_minus_load_factor_final(bau_net_power, window=monthly_steps),
                'ratio',
            ),
            (
                'peak_daily_average',
                self._peak_final(current_net_power, window=daily_steps),
                self._peak_final(bau_net_power, window=daily_steps),
                'kw',
            ),
            (
                'peak_all_time_average',
                self._peak_final(current_net_power, window=max(int(getattr(env, 'time_steps', 1)), 1)),
                self._peak_final(bau_net_power, window=max(int(getattr(bau_env, 'time_steps', 1)), 1)),
                'kw',
            ),
        ]

        for metric, control_value, bau_value, unit in metrics:
            records[('district', 'District', v2('district', 'energy_grid', 'shape_quality', metric, 'business_as_usual', unit))] = {
                'cost_function': v2('district', 'energy_grid', 'shape_quality', metric, 'business_as_usual', unit),
                'value': bau_value,
                'name': 'District',
                'level': 'district',
            }
            records[('district', 'District', v2('district', 'energy_grid', 'shape_quality', metric, 'delta_to_business_as_usual', unit))] = {
                'cost_function': v2('district', 'energy_grid', 'shape_quality', metric, 'delta_to_business_as_usual', unit),
                'value': control_value - bau_value,
                'name': 'District',
                'level': 'district',
            }
            records[('district', 'District', v2('district', 'energy_grid', 'shape_quality', f'{metric}_to_business_as_usual', None, 'ratio'))] = {
                'cost_function': v2('district', 'energy_grid', 'shape_quality', f'{metric}_to_business_as_usual', None, 'ratio'),
                'value': self._safe_div(control_value, bau_value),
                'name': 'District',
                'level': 'district',
            }

    @population_scope
    @settled_cost_scope
    def evaluate_v2(
        self, control_condition=None, baseline_condition=None, comfort_band=None,
        include_business_as_usual=True, *, evaluation_condition_cls,
        dynamics_building_cls, progress_callback=None,
    ) -> pd.DataFrame:
        progress = None if progress_callback is None else EvaluationProgress(progress_callback)
        return run(progress, 'evaluation', self._evaluate_v2,
                   control_condition=control_condition, baseline_condition=baseline_condition,
                   comfort_band=comfort_band, include_business_as_usual=include_business_as_usual,
                   evaluation_condition_cls=evaluation_condition_cls,
                   dynamics_building_cls=dynamics_building_cls, progress=progress)

    def _evaluate_v2(
        self,
        control_condition=None,
        baseline_condition=None,
        comfort_band: float = None,
        include_business_as_usual: bool = True,
        *,
        evaluation_condition_cls,
        dynamics_building_cls,
        progress=None,
    ) -> pd.DataFrame:
        env = self.env
        all_metrics = self.evaluate(
            control_condition=control_condition,
            baseline_condition=baseline_condition,
            comfort_band=comfort_band,
            evaluation_condition_cls=evaluation_condition_cls,
            dynamics_building_cls=dynamics_building_cls,
            progress=progress,
        )
        legacy_df = all_metrics[all_metrics['cost_function'].isin(self.LEGACY_COST_FUNCTIONS)].copy()
        extended_df = all_metrics[~all_metrics['cost_function'].isin(self.LEGACY_COST_FUNCTIONS)].copy()
        simulated_days = self._simulated_days(env)

        records: Dict[Tuple[str, str, str], Dict[str, object]] = {}

        def put(level: str, name: str, cost_function: str, value):
            records[(level, name, cost_function)] = {
                'cost_function': cost_function,
                'value': value,
                'name': name,
                'level': level,
            }

        def v2(
            level: str,
            family: str,
            subfamily: str,
            metric: str,
            variant: Optional[str] = None,
            unit: Optional[str] = None,
        ) -> str:
            return self._v2_name(
                level,
                family,
                subfamily,
                metric,
                variant=variant,
                unit=unit,
            )

        def map_from(
            source_df: pd.DataFrame,
            old_name: str,
            family: str,
            subfamily: str,
            metric: str,
            variant: Optional[str] = None,
            unit: Optional[str] = None,
        ):
            subset = source_df[source_df['cost_function'] == old_name]
            for _, row in subset.iterrows():
                level = str(row['level'])
                put(
                    level,
                    str(row['name']),
                    v2(level, family, subfamily, metric, variant, unit),
                    row['value'],
                )

        # Ratios to baseline and comfort/resilience from legacy.
        legacy_map = [
            ('electricity_consumption_total', 'energy_grid', 'ratio_to_baseline', 'import_total', None, 'ratio'),
            ('zero_net_energy', 'energy_grid', 'ratio_to_baseline', 'net_exchange_total', None, 'ratio'),
            ('carbon_emissions_total', 'emissions', 'ratio_to_baseline', 'total', None, 'ratio'),
            ('cost_total', 'cost', 'ratio_to_baseline', 'total', None, 'ratio'),
            ('ramping_average', 'energy_grid', 'shape_quality', 'ramping_average_to_baseline', None, 'ratio'),
            ('daily_one_minus_load_factor_average', 'energy_grid', 'shape_quality', 'load_factor_penalty_daily_average_to_baseline', None, 'ratio'),
            ('monthly_one_minus_load_factor_average', 'energy_grid', 'shape_quality', 'load_factor_penalty_monthly_average_to_baseline', None, 'ratio'),
            ('daily_peak_average', 'energy_grid', 'shape_quality', 'peak_daily_average_to_baseline', None, 'ratio'),
            ('all_time_peak_average', 'energy_grid', 'shape_quality', 'peak_all_time_average_to_baseline', None, 'ratio'),
            ('discomfort_proportion', 'comfort_resilience', 'discomfort', 'overall', None, 'ratio'),
            ('discomfort_cold_proportion', 'comfort_resilience', 'discomfort', 'cold', None, 'ratio'),
            ('discomfort_hot_proportion', 'comfort_resilience', 'discomfort', 'hot', None, 'ratio'),
            ('discomfort_cold_delta_minimum', 'comfort_resilience', 'discomfort', 'cold_delta', 'min', 'c'),
            ('discomfort_cold_delta_maximum', 'comfort_resilience', 'discomfort', 'cold_delta', 'max', 'c'),
            ('discomfort_cold_delta_average', 'comfort_resilience', 'discomfort', 'cold_delta', 'average', 'c'),
            ('discomfort_hot_delta_minimum', 'comfort_resilience', 'discomfort', 'hot_delta', 'min', 'c'),
            ('discomfort_hot_delta_maximum', 'comfort_resilience', 'discomfort', 'hot_delta', 'max', 'c'),
            ('discomfort_hot_delta_average', 'comfort_resilience', 'discomfort', 'hot_delta', 'average', 'c'),
            ('one_minus_thermal_resilience_proportion', 'comfort_resilience', 'resilience', 'one_minus_thermal', None, 'ratio'),
            ('power_outage_normalized_unserved_energy_total', 'comfort_resilience', 'resilience', 'unserved_energy_outage_normalized', None, 'ratio'),
            ('annual_normalized_unserved_energy_total', 'comfort_resilience', 'resilience', 'unserved_energy_annual_normalized', None, 'ratio'),
        ]
        for old_name, family, subfamily, metric, variant, unit in legacy_map:
            map_from(legacy_df, old_name, family, subfamily, metric, variant, unit)

        extended_map = [
            ('cost_control_total_eur', 'cost', 'total', 'control', None, 'eur'),
            ('cost_baseline_total_eur', 'cost', 'total', 'baseline', None, 'eur'),
            ('cost_delta_total_eur', 'cost', 'total', 'delta', None, 'eur'),
            ('cost_control_daily_average_eur', 'cost', 'daily_average', 'control', None, 'eur'),
            ('cost_baseline_daily_average_eur', 'cost', 'daily_average', 'baseline', None, 'eur'),
            ('cost_delta_daily_average_eur', 'cost', 'daily_average', 'delta', None, 'eur'),
            ('electricity_consumption_control_total_kwh', 'energy_grid', 'total', 'import', 'control', 'kwh'),
            ('electricity_consumption_baseline_total_kwh', 'energy_grid', 'total', 'import', 'baseline', 'kwh'),
            ('electricity_consumption_delta_total_kwh', 'energy_grid', 'total', 'import', 'delta', 'kwh'),
            ('electricity_consumption_control_daily_average_kwh', 'energy_grid', 'daily_average', 'import', 'control', 'kwh'),
            ('electricity_consumption_baseline_daily_average_kwh', 'energy_grid', 'daily_average', 'import', 'baseline', 'kwh'),
            ('electricity_consumption_delta_daily_average_kwh', 'energy_grid', 'daily_average', 'import', 'delta', 'kwh'),
            ('electricity_export_control_total_kwh', 'energy_grid', 'total', 'export', 'control', 'kwh'),
            ('electricity_export_baseline_total_kwh', 'energy_grid', 'total', 'export', 'baseline', 'kwh'),
            ('electricity_export_delta_total_kwh', 'energy_grid', 'total', 'export', 'delta', 'kwh'),
            ('electricity_export_control_daily_average_kwh', 'energy_grid', 'daily_average', 'export', 'control', 'kwh'),
            ('electricity_export_baseline_daily_average_kwh', 'energy_grid', 'daily_average', 'export', 'baseline', 'kwh'),
            ('electricity_export_delta_daily_average_kwh', 'energy_grid', 'daily_average', 'export', 'delta', 'kwh'),
            ('zero_net_energy_control_total_kwh', 'energy_grid', 'total', 'net_exchange', 'control', 'kwh'),
            ('zero_net_energy_baseline_total_kwh', 'energy_grid', 'total', 'net_exchange', 'baseline', 'kwh'),
            ('zero_net_energy_delta_total_kwh', 'energy_grid', 'total', 'net_exchange', 'delta', 'kwh'),
            ('zero_net_energy_control_daily_average_kwh', 'energy_grid', 'daily_average', 'net_exchange', 'control', 'kwh'),
            ('zero_net_energy_baseline_daily_average_kwh', 'energy_grid', 'daily_average', 'net_exchange', 'baseline', 'kwh'),
            ('zero_net_energy_delta_daily_average_kwh', 'energy_grid', 'daily_average', 'net_exchange', 'delta', 'kwh'),
            ('carbon_emissions_control_total_kgco2', 'emissions', 'total', 'control', None, 'kgco2'),
            ('carbon_emissions_baseline_total_kgco2', 'emissions', 'total', 'baseline', None, 'kgco2'),
            ('carbon_emissions_delta_total_kgco2', 'emissions', 'total', 'delta', None, 'kgco2'),
            ('carbon_emissions_control_daily_average_kgco2', 'emissions', 'daily_average', 'control', None, 'kgco2'),
            ('carbon_emissions_baseline_daily_average_kgco2', 'emissions', 'daily_average', 'baseline', None, 'kgco2'),
            ('carbon_emissions_delta_daily_average_kgco2', 'emissions', 'daily_average', 'delta', None, 'kgco2'),
            ('pv_curtailment_total_kwh', 'solar_self_consumption', 'total', 'curtailment', None, 'kwh'),
            ('pv_generation_total_kwh', 'solar_self_consumption', 'total', 'generation', None, 'kwh'),
            ('pv_export_total_kwh', 'solar_self_consumption', 'total', 'export', None, 'kwh'),
            ('pv_generation_daily_average_kwh', 'solar_self_consumption', 'daily_average', 'generation', None, 'kwh'),
            ('pv_export_daily_average_kwh', 'solar_self_consumption', 'daily_average', 'export', None, 'kwh'),
            ('pv_self_consumption_ratio', 'solar_self_consumption', 'ratio', 'self_consumption', None, 'ratio'),
            ('ev_departure_events_count', 'ev', 'events', 'departure', None, 'count'),
            ('ev_departure_met_events_count', 'ev', 'events', 'departure_met', None, 'count'),
            ('ev_departure_min_acceptable_events_count', 'ev', 'events', 'departure_min_acceptable', None, 'count'),
            ('ev_departure_within_tolerance_events_count', 'ev', 'events', 'departure_within_tolerance', None, 'count'),
            ('ev_departure_target_feasible_events_count', 'ev', 'events', 'departure_target_feasible', None, 'count'),
            ('ev_departure_target_infeasible_events_count', 'ev', 'events', 'departure_target_infeasible', None, 'count'),
            ('ev_departure_min_acceptable_feasible_events_count', 'ev', 'events', 'departure_min_acceptable_feasible', None, 'count'),
            ('ev_departure_min_acceptable_infeasible_events_count', 'ev', 'events', 'departure_min_acceptable_infeasible', None, 'count'),
            ('ev_departure_within_tolerance_feasible_events_count', 'ev', 'events', 'departure_within_tolerance_feasible', None, 'count'),
            ('ev_departure_within_tolerance_infeasible_events_count', 'ev', 'events', 'departure_within_tolerance_infeasible', None, 'count'),
            ('ev_departure_success_rate', 'ev', 'performance', 'departure_success', None, 'ratio'),
            ('ev_departure_min_acceptable_rate', 'ev', 'performance', 'departure_min_acceptable', None, 'ratio'),
            ('ev_departure_within_tolerance_rate', 'ev', 'performance', 'departure_within_tolerance', None, 'ratio'),
            ('ev_departure_success_feasible_rate', 'ev', 'performance', 'departure_success', 'feasible', 'ratio'),
            ('ev_departure_min_acceptable_feasible_rate', 'ev', 'performance', 'departure_min_acceptable', 'feasible', 'ratio'),
            ('ev_departure_within_tolerance_feasible_rate', 'ev', 'performance', 'departure_within_tolerance', 'feasible', 'ratio'),
            ('ev_departure_soc_deficit_mean', 'ev', 'performance', 'departure_soc_deficit_mean', None, 'ratio'),
            ('ev_departure_shortfall_beyond_tolerance_mean', 'ev', 'performance', 'departure_shortfall_beyond_tolerance_mean', None, 'ratio'),
            ('ev_departure_soc_surplus_mean', 'ev', 'performance', 'departure_soc_surplus_mean', None, 'ratio'),
            ('ev_departure_soc_absolute_error_mean', 'ev', 'performance', 'departure_soc_absolute_error_mean', None, 'ratio'),
            ('ev_departure_tolerance_ratio', 'ev', 'performance', 'departure_tolerance', None, 'ratio'),
            ('ev_charge_total_kwh', 'ev', 'total', 'charge', None, 'kwh'),
            ('ev_v2g_export_total_kwh', 'ev', 'total', 'v2g_export', None, 'kwh'),
            ('ev_connected_soc_gain_total_kwh', 'ev', 'energy_accounting', 'connected_soc_gain', None, 'kwh'),
            ('ev_energy_accounting_shortfall_kwh', 'ev', 'energy_accounting', 'shortfall', None, 'kwh'),
            ('bess_charge_total_kwh', 'battery', 'total', 'charge', None, 'kwh'),
            ('bess_discharge_total_kwh', 'battery', 'total', 'discharge', None, 'kwh'),
            ('bess_throughput_total_kwh', 'battery', 'total', 'throughput', None, 'kwh'),
            ('bess_equivalent_full_cycles', 'battery', 'health', 'equivalent_full_cycles', None, 'count'),
            ('bess_capacity_fade_ratio', 'battery', 'health', 'capacity_fade', None, 'ratio'),
            ('electrical_service_violation_total_kwh', 'electrical_service_phase', 'violations', 'energy_total', None, 'kwh'),
            ('electrical_service_violation_time_step_count', 'electrical_service_phase', 'violations', 'event', None, 'count'),
            ('electrical_service_requested_pressure_total_kwh', 'electrical_service_phase', 'requested_pressure', 'energy_total', None, 'kwh'),
            ('electrical_service_requested_pressure_time_step_count', 'electrical_service_phase', 'requested_pressure', 'event', None, 'count'),
            ('phase_imbalance_ratio_average', 'electrical_service_phase', 'imbalance', 'phase_average', None, 'ratio'),
            ('community_local_import_total_kwh', 'energy_grid', 'community_market', 'local_import', 'total', 'kwh'),
            ('community_local_export_total_kwh', 'energy_grid', 'community_market', 'local_export', 'total', 'kwh'),
            ('community_grid_import_after_local_total_kwh', 'energy_grid', 'community_market', 'grid_import_after_local', 'total', 'kwh'),
            ('community_grid_export_after_local_total_kwh', 'energy_grid', 'community_market', 'grid_export_after_local', 'total', 'kwh'),
            ('community_local_import_daily_average_kwh', 'energy_grid', 'community_market', 'local_import', 'daily_average', 'kwh'),
            ('community_local_export_daily_average_kwh', 'energy_grid', 'community_market', 'local_export', 'daily_average', 'kwh'),
            ('community_grid_import_after_local_daily_average_kwh', 'energy_grid', 'community_market', 'grid_import_after_local', 'daily_average', 'kwh'),
            ('community_grid_export_after_local_daily_average_kwh', 'energy_grid', 'community_market', 'grid_export_after_local', 'daily_average', 'kwh'),
            ('community_settled_cost_total_eur', 'cost', 'community_market', 'settled', 'total', 'eur'),
            ('community_counterfactual_cost_total_eur', 'cost', 'community_market', 'counterfactual', 'total', 'eur'),
            ('community_market_savings_total_eur', 'cost', 'community_market', 'savings', 'total', 'eur'),
            ('community_settled_cost_daily_average_eur', 'cost', 'community_market', 'settled', 'daily_average', 'eur'),
            ('community_counterfactual_cost_daily_average_eur', 'cost', 'community_market', 'counterfactual', 'daily_average', 'eur'),
            ('community_market_savings_daily_average_eur', 'cost', 'community_market', 'savings', 'daily_average', 'eur'),
            ('community_local_share_of_demand', 'solar_self_consumption', 'community_market', 'local_share_of_demand', None, 'ratio'),
            ('community_local_share_of_export', 'solar_self_consumption', 'community_market', 'local_share_of_export', None, 'ratio'),
            ('equity_relative_benefit_percent', 'equity', 'benefit', 'relative', None, 'percent'),
            ('equity_gini_benefit', 'equity', 'distribution', 'gini_benefit', None, 'ratio'),
            ('equity_cr20_benefit', 'equity', 'distribution', 'top20_benefit', None, 'ratio'),
            ('equity_losers_percent', 'equity', 'distribution', 'losers', None, 'percent'),
            ('equity_bpr_asset_poor_over_rich', 'equity', 'distribution', 'bpr_asset_poor_over_rich', None, 'ratio'),
            ('deferrable_appliance_completed_cycles_count', 'deferrable_appliance', 'service', 'completed_cycles', None, 'count'),
            ('deferrable_appliance_missed_cycles_count', 'deferrable_appliance', 'service', 'missed_cycles', None, 'count'),
            ('deferrable_appliance_service_level_ratio', 'deferrable_appliance', 'service', 'service_level', None, 'ratio'),
            ('deferrable_appliance_served_energy_total_kwh', 'deferrable_appliance', 'service', 'served_energy_total', None, 'kwh'),
            ('deferrable_appliance_unserved_energy_total_kwh', 'deferrable_appliance', 'service', 'unserved_energy_total', None, 'kwh'),
            ('deferrable_appliance_average_start_delay_hours', 'deferrable_appliance', 'service', 'average_start_delay', None, 'hours'),
            ('escalator_requested_passengers_total_count', 'escalator', 'service', 'requested_passengers_total', None, 'count'),
            ('escalator_served_passengers_total_count', 'escalator', 'service', 'served_passengers_total', None, 'count'),
            ('escalator_unserved_passengers_total_count', 'escalator', 'service', 'unserved_passengers_total', None, 'count'),
            ('escalator_service_level_ratio', 'escalator', 'service', 'service_level', None, 'ratio'),
            ('escalator_electricity_consumption_total_kwh', 'escalator', 'energy', 'electricity_consumption_total', None, 'kwh'),
            ('escalator_state_changes_count', 'escalator', 'operation', 'state_changes', None, 'count'),
        ]
        for key in deferrable_service_audit.summarize([]):
            metric, unit = key.rsplit('_', 1)
            extended_map.append((f'deferrable_appliance_audit_{key}', 'deferrable_appliance', 'audit', metric, None, unit))
        for key in ev_departure_audit.metrics(ev_departure_audit.empty_counts()):
            metric, unit = key.rsplit('_', 1)
            extended_map.append((f'ev_departure_audit_{key}', 'ev', 'departure_audit', metric, None, unit))
        for old_name, family, subfamily, metric, variant, unit in extended_map:
            map_from(extended_df, old_name, family, subfamily, metric, variant, unit)

        # Phase peaks have dynamic suffixes (L1/L2/L3) and are conditionally present.
        for _, row in extended_df.iterrows():
            old_name = str(row['cost_function'])
            level = str(row['level'])
            name = str(row['name'])

            if old_name.startswith('phase_import_peak_kw_'):
                phase = old_name.split('phase_import_peak_kw_', 1)[1].lower()
                put(
                    level,
                    name,
                    v2(level, 'electrical_service_phase', 'phase_peaks', f'import_peak_{phase}', None, 'kw'),
                    row['value'],
                )
            elif old_name.startswith('phase_export_peak_kw_'):
                phase = old_name.split('phase_export_peak_kw_', 1)[1].lower()
                put(
                    level,
                    name,
                    v2(level, 'electrical_service_phase', 'phase_peaks', f'export_peak_{phase}', None, 'kw'),
                    row['value'],
                )

        kpi_buildings = self._get_kpi_buildings()
        building_windows = {building.name: self._building_active_window(building) for building in kpi_buildings}
        kpi_building_by_name = {building.name: building for building in kpi_buildings}
        building_names = [building.name for building in kpi_buildings]

        # Optional community KPIs are district-only.
        if getattr(env, 'community_market_enabled', False):
            district_rows = extended_df[(extended_df['level'] == 'district') & (extended_df['name'] == 'District')]
            if getattr(env, 'community_market_kpi_local_traded_enabled', True):
                local_total = district_rows[district_rows['cost_function'] == 'community_local_import_total_kwh']['value']
                local_daily = district_rows[district_rows['cost_function'] == 'community_local_import_daily_average_kwh']['value']
                if len(local_total) > 0:
                    put(
                        'district',
                        'District',
                        v2('district', 'energy_grid', 'community_market', 'local_traded', 'total', 'kwh'),
                        local_total.iloc[0],
                    )
                if len(local_daily) > 0:
                    put(
                        'district',
                        'District',
                        v2('district', 'energy_grid', 'community_market', 'local_traded', 'daily_average', 'kwh'),
                        local_daily.iloc[0],
                    )

            if getattr(env, 'community_market_kpi_self_consumption_enabled', True):
                local_total = district_rows[district_rows['cost_function'] == 'community_local_import_total_kwh']['value']
                if len(local_total) > 0:
                    local_total_value = self._to_scalar(local_total.iloc[0], 0.0)
                    grid_import_after_local = district_rows[
                        district_rows['cost_function'] == 'community_grid_import_after_local_total_kwh'
                    ]['value']
                    grid_import_after_local_value = (
                        self._to_scalar(grid_import_after_local.iloc[0], 0.0)
                        if len(grid_import_after_local) > 0 else 0.0
                    )
                    total_member_demand = local_total_value + grid_import_after_local_value
                    share = None if total_member_demand <= float(ZERO_DIVISION_PLACEHOLDER) else local_total_value / total_member_demand
                    put(
                        'district',
                        'District',
                        v2('district', 'solar_self_consumption', 'community_market', 'import_share', None, 'ratio'),
                        share,
                    )

        family_audit = run(progress, 'thermal_equity_audit', self.family_audit,comfort_band=comfort_band, control_condition=control_condition, baseline_condition=baseline_condition, progress=progress)
        for name, totals in list(family_audit['buildings'].items())+[('District',family_audit['district'])]:
            level = 'district' if name == 'District' else 'building'
            for suffix, value in totals.items():
                put(level, name, f'{level}_thermal_service_audit_{suffix}', value)
        for suffix, value in family_audit['equity'].items():
            put('district', 'District', f'district_equity_audit_{suffix}', value)

        demand_response_service = getattr(env, '_demand_response_service', None)
        if getattr(demand_response_service, 'enabled', False):
            dr_by_building, dr_district = demand_response_service.summarize(building_names)
            for purpose, totals in demand_response_service.audit_summary().items():
                for suffix, value in totals.items():
                    put('district', 'District', f'district_demand_response_audit_{purpose}_{suffix}', value)


            def dr_name(level: str, suffix: str) -> str:
                return f'{level}_demand_response_{suffix}'

            dr_metrics = [
                ('events_count', 'demand_response_events_count'),
                ('active_time_step_count', 'demand_response_active_time_step_count'),
                ('requested_total_kwh', 'demand_response_requested_total_kwh'),
                ('delivered_total_kwh', 'demand_response_delivered_total_kwh'),
                ('shortfall_total_kwh', 'demand_response_shortfall_total_kwh'),
                ('compliance_ratio', 'demand_response_compliance_ratio'),
                ('revenue_total_eur', 'demand_response_revenue_total_eur'),
                ('penalty_total_eur', 'demand_response_penalty_total_eur'),
                ('net_revenue_total_eur', 'demand_response_net_revenue_total_eur'),
                ('invalid_baseline_time_step_count', 'demand_response_invalid_baseline_time_step_count'),
            ]

            for suffix, key in dr_metrics:
                put('district', 'District', dr_name('district', suffix), dr_district.get(key))

            for building_name in building_names:
                totals = dr_by_building.get(building_name, {})
                for suffix, key in dr_metrics:
                    put('building', building_name, dr_name('building', suffix), totals.get(key))

        robustness_service = getattr(env, '_robustness_service', None)
        if getattr(robustness_service, 'enabled', False):
            robustness_by_building, robustness_district = run(progress, 'robustness', robustness_service.summarize, building_names)

            robustness_metrics = [
                'robustness_events_count',
                'robustness_active_time_step_count',
                'robustness_observation_corruption_count',
                'robustness_forecast_corruption_count',
                'robustness_action_corruption_count',
                'robustness_asset_unavailable_time_step_count',
                'robustness_missing_observation_count',
                'robustness_action_dropout_count',
            ]

            for key in robustness_metrics:
                put('district', 'District', f'district_{key}', robustness_district.get(key))

            for building_name in building_names:
                totals = robustness_by_building.get(building_name, {})
                for key in robustness_metrics:
                    put('building', building_name, f'building_{key}', totals.get(key))

        # Export ratio_to_baseline is derived from totals with safe division.
        for building in kpi_buildings:
            control_cond, baseline_cond = self._default_building_conditions(
                building,
                control_condition,
                baseline_condition,
                evaluation_condition_cls=evaluation_condition_cls,
                dynamics_building_cls=dynamics_building_cls,
            )
            t_start, t_end = building_windows.get(building.name, (0, -1))
            net_c = self._energy_values(building, getattr(building, f'net_electricity_consumption{control_cond.value}'))
            net_b = self._energy_values(building, getattr(building, f'net_electricity_consumption{baseline_cond.value}'))
            export_c = self._sum_finite(np.clip(-net_c, 0.0, None))
            export_b = self._sum_finite(np.clip(-net_b, 0.0, None))
            put(
                'building',
                building.name,
                v2('building', 'energy_grid', 'ratio_to_baseline', 'export_total', None, 'ratio'),
                self._safe_div(export_c, export_b),
            )

        env_control_condition = (
            evaluation_condition_cls.WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV
            if control_condition is None else control_condition
        )
        env_baseline_condition = (
            evaluation_condition_cls.WITHOUT_STORAGE_AND_PARTIAL_LOAD_BUT_WITH_PV
            if baseline_condition is None else baseline_condition
        )
        env_net_c = self._energy_values(env, getattr(env, f'net_electricity_consumption{env_control_condition.value}'))
        env_net_b = self._energy_values(env, getattr(env, f'net_electricity_consumption{env_baseline_condition.value}'))
        env_export_c = self._sum_finite(np.clip(-env_net_c, 0.0, None))
        env_export_b = self._sum_finite(np.clip(-env_net_b, 0.0, None))
        put(
            'district',
            'District',
            v2('district', 'energy_grid', 'ratio_to_baseline', 'export_total', None, 'ratio'),
            self._safe_div(env_export_c, env_export_b),
        )

        # Cost metrics: market-enabled scenarios settle both control and baseline with same rules.
        control_condition_by_building = {}
        baseline_condition_by_building = {}
        for building in kpi_buildings:
            c_cond, b_cond = self._default_building_conditions(
                building,
                control_condition,
                baseline_condition,
                evaluation_condition_cls=evaluation_condition_cls,
                dynamics_building_cls=dynamics_building_cls,
            )
            control_condition_by_building[building.name] = c_cond
            baseline_condition_by_building[building.name] = b_cond

        control_cost_totals: Dict[str, float] = {}
        baseline_cost_totals: Dict[str, float] = {}
        district_control_total = 0.0
        district_baseline_total = 0.0

        if getattr(env, 'community_market_enabled', False):
            control_cost_totals, district_control_total = run(progress, 'control_cost', self._condition_settled_cost_totals,
                condition_by_building=control_condition_by_building,
            )
            baseline_cost_totals, district_baseline_total = run(progress, 'reference_cost', self._condition_settled_cost_totals,
                condition_by_building=baseline_condition_by_building,
            )
        else:
            # Read mapped values from records when market is disabled.
            for building_name in building_names:
                key_control = ('building', building_name, v2('building', 'cost', 'total', 'control', None, 'eur'))
                key_baseline = ('building', building_name, v2('building', 'cost', 'total', 'baseline', None, 'eur'))
                control_cost_totals[building_name] = self._to_scalar(records.get(key_control, {}).get('value'), 0.0)
                baseline_cost_totals[building_name] = self._to_scalar(records.get(key_baseline, {}).get('value'), 0.0)

            district_control_total = self._to_scalar(
                records.get(('district', 'District', v2('district', 'cost', 'total', 'control', None, 'eur')), {}).get('value'),
                0.0,
            )
            district_baseline_total = self._to_scalar(
                records.get(('district', 'District', v2('district', 'cost', 'total', 'baseline', None, 'eur')), {}).get('value'),
                0.0,
            )

        for building_name in building_names:
            t_start, t_end = building_windows.get(building_name, (0, -1))
            building_days = self._building_days(kpi_building_by_name[building_name], t_start, t_end)
            control_total = self._to_scalar(control_cost_totals.get(building_name), 0.0)
            baseline_total = self._to_scalar(baseline_cost_totals.get(building_name), 0.0)
            delta_total = control_total - baseline_total
            put('building', building_name, v2('building', 'cost', 'total', 'control', None, 'eur'), control_total)
            put('building', building_name, v2('building', 'cost', 'total', 'baseline', None, 'eur'), baseline_total)
            put('building', building_name, v2('building', 'cost', 'total', 'delta', None, 'eur'), delta_total)
            put('building', building_name, v2('building', 'cost', 'daily_average', 'control', None, 'eur'), self._daily_average(control_total, building_days))
            put('building', building_name, v2('building', 'cost', 'daily_average', 'baseline', None, 'eur'), self._daily_average(baseline_total, building_days))
            put('building', building_name, v2('building', 'cost', 'daily_average', 'delta', None, 'eur'), self._daily_average(delta_total, building_days))
            put('building', building_name, v2('building', 'cost', 'ratio_to_baseline', 'total', None, 'ratio'), self._signed_ratio(control_total, baseline_total))

        district_delta_total = district_control_total - district_baseline_total
        put('district', 'District', v2('district', 'cost', 'total', 'control', None, 'eur'), district_control_total)
        put('district', 'District', v2('district', 'cost', 'total', 'baseline', None, 'eur'), district_baseline_total)
        put('district', 'District', v2('district', 'cost', 'total', 'delta', None, 'eur'), district_delta_total)
        put('district', 'District', v2('district', 'cost', 'daily_average', 'control', None, 'eur'), self._daily_average(district_control_total, simulated_days))
        put('district', 'District', v2('district', 'cost', 'daily_average', 'baseline', None, 'eur'), self._daily_average(district_baseline_total, simulated_days))
        put('district', 'District', v2('district', 'cost', 'daily_average', 'delta', None, 'eur'), self._daily_average(district_delta_total, simulated_days))
        put('district', 'District', v2('district', 'cost', 'ratio_to_baseline', 'total', None, 'ratio'), self._signed_ratio(district_control_total, district_baseline_total))

        # Equity metrics are recomputed from cost totals for consistency.
        equity_valid_benefits: Dict[str, float] = {}
        groups = {building.name: getattr(building, 'equity_group', None) for building in kpi_buildings}
        for building_name in building_names:
            benefit = self._equity_relative_benefit_percent(
                control_cost_totals.get(building_name, 0.0),
                baseline_cost_totals.get(building_name, 0.0),
            )
            put(
                'building',
                building_name,
                v2('building', 'equity', 'benefit', 'relative', None, 'percent'),
                benefit,
            )
            if benefit is not None:
                equity_valid_benefits[building_name] = float(benefit)

        equity_distribution = self._equity_distribution_metrics(np.array(list(equity_valid_benefits.values()), dtype='float64'))
        non_negative_benefits = {name: max(value, 0.0) for name, value in equity_valid_benefits.items()}
        has_complete_manual_groups = all(groups.get(name) in {'asset_rich', 'asset_poor'} for name in building_names)
        equity_bpr = self._equity_bpr(non_negative_benefits, groups) if has_complete_manual_groups else None
        put('district', 'District', v2('district', 'equity', 'distribution', 'gini_benefit', None, 'ratio'), equity_distribution['equity_gini_benefit'])
        put('district', 'District', v2('district', 'equity', 'distribution', 'top20_benefit', None, 'ratio'), equity_distribution['equity_cr20_benefit'])
        put('district', 'District', v2('district', 'equity', 'distribution', 'losers', None, 'percent'), equity_distribution['equity_losers_percent'])
        put('district', 'District', v2('district', 'equity', 'distribution', 'bpr_asset_poor_over_rich', None, 'ratio'), equity_bpr)

        provenance = getattr(env, '_provenance_service', None)
        if provenance is not None and getattr(provenance, 'enabled', True):
            members, district = run(progress, 'provenance', provenance.summary)
            for name, metrics in members.items():
                for metric, value in metrics.items():
                    put('building', name, f'building_energy_provenance_{metric}', value)
            for metric, value in district.items():
                put('district', 'District', f'district_energy_provenance_{metric}', value)

        if include_business_as_usual and not bool(getattr(env, '_business_as_usual_sidecar', False)):
            run(progress, 'business_as_usual', self._add_business_as_usual_records,
                records,
                v2,
                simulated_days,
                evaluation_condition_cls=evaluation_condition_cls,
                dynamics_building_cls=dynamics_building_cls,
            )

        output = pd.DataFrame(list(records.values()))
        if getattr(robustness_service, 'enabled', False):
            output.attrs['robustness_audit'] = robustness_service.audit_summary()
        if provenance is not None:
            output.attrs['energy_accounting'] = provenance.get_metadata()
        from citylearn.internal.kpi_family_audit import metadata as family_metadata
        output.attrs['kpi_family_audit'] = family_metadata()
        output.attrs['kpi_family_audit']['equity_conditions'] = family_audit['equity_conditions']
        if output.empty:
            return pd.DataFrame(columns=['cost_function', 'value', 'name', 'level'])

        if getattr(env, 'topology_mode', 'static') == 'dynamic':
            lifecycle = getattr(env, 'topology_member_lifecycle', {}) or {}
            existing_buildings = set(output[output['level'] == 'building']['name'].astype(str).tolist())
            lifecycle_rows = []

            for member_id in lifecycle.keys():
                if member_id not in existing_buildings:
                    lifecycle_rows.append(
                        {
                            'cost_function': 'topology_lifecycle_presence',
                            'value': np.nan,
                            'name': member_id,
                            'level': 'building',
                        }
                    )

            if lifecycle_rows:
                output = pd.concat([output, pd.DataFrame(lifecycle_rows)], ignore_index=True)

            output['topology_born_at'] = np.nan
            output['topology_removed_at'] = np.nan
            output['topology_active'] = np.nan
            for member_id, state in lifecycle.items():
                mask = (output['level'] == 'building') & (output['name'] == member_id)
                output.loc[mask, 'topology_born_at'] = state.get('born_at')
                output.loc[mask, 'topology_removed_at'] = state.get('removed_at')
                output.loc[mask, 'topology_active'] = 1.0 if state.get('active', False) else 0.0

        output = run(progress, 'formatting', lambda: output.sort_values(['level', 'name', 'cost_function']).reset_index(drop=True))
        return output
