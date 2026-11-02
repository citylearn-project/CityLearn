"""Side-effect-free allocation of signed electrical-service requests, in kW.

Positive power imports/consumes; negative power exports/supplies. Callers provide
their own base-load estimate and phase split. This calculation reduces requests
proportionally; it neither dispatches devices nor guarantees that fixed loads
alone satisfy the service limits. Device physics and sequential outage supply
checks remain the runtime's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Dict, Mapping, Optional, Sequence, Tuple, TypedDict


class PowerRequest(TypedDict):
    request_total_kw: float
    request_phase_kw: Mapping[str, float]


@dataclass(frozen=True)
class ElectricalServiceAllocation:
    scales: Dict[str, float]
    total_kw: float
    phase_kw: Dict[str, float]
    requested_violation_kw: float
    residual_violation_kw: float


def _finite_scalar(value, default: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if isfinite(value) else default


def _compute_totals(
    base_total_kw: float,
    base_phase_kw: Mapping[str, float],
    controls: Mapping[str, PowerRequest],
    scales: Mapping[str, float],
) -> Tuple[float, Dict[str, float]]:
    total_kw = float(base_total_kw)
    phase_kw = {phase: float(value) for phase, value in base_phase_kw.items()}
    for control_id, control in controls.items():
        scale = scales[control_id]
        total_kw += control['request_total_kw'] * scale
        for phase_name, value in control['request_phase_kw'].items():
            phase_kw[phase_name] = phase_kw.get(phase_name, 0.0) + value * scale
    return total_kw, phase_kw


def electrical_service_violation_kw(
    total_kw: float,
    phase_kw: Mapping[str, float],
    total_limits: Mapping[str, Optional[float]],
    per_phase_limits: Mapping[str, Mapping[str, Optional[float]]],
    phase_names: Sequence[str],
) -> float:
    """Sum requested/residual excess over total and phase limits, in kW.

    This pressure metric counts each scope separately; it is not unmet energy.
    Missing/non-finite limits are unbounded, as in the service configuration.
    """
    violation_kw = 0.0
    for phase_name in (None, *phase_names):
        value = total_kw if phase_name is None else phase_kw.get(phase_name, 0.0)
        value = _finite_scalar(value, 0.0)
        limits = total_limits if phase_name is None else per_phase_limits.get(phase_name, {})
        import_limit = _finite_scalar(limits.get('import_kw'), float('nan'))
        export_limit = _finite_scalar(limits.get('export_kw'), float('nan'))
        if isfinite(import_limit):
            violation_kw += max(value - import_limit, 0.0)
        if isfinite(export_limit):
            violation_kw += max(-value - export_limit, 0.0)
    return float(violation_kw)


def _scale_scope(
    current_value_kw: float,
    limit_kw: Optional[float],
    controls: Mapping[str, PowerRequest],
    scales: Dict[str, float],
    phase_name: Optional[str],
    *,
    export: bool,
) -> bool:
    limit_kw = _finite_scalar(limit_kw, float('nan'))
    current_value_kw = _finite_scalar(current_value_kw, 0.0)
    if not isfinite(limit_kw):
        return False
    magnitude_kw = max(-current_value_kw, 0.0) if export else current_value_kw
    if magnitude_kw <= limit_kw + 1.0e-9:
        return False

    relevant = []
    for control_id, control in controls.items():
        component_kw = (control['request_total_kw'] if phase_name is None
                        else control['request_phase_kw'].get(phase_name, 0.0))
        if (component_kw < 0.0 if export else component_kw > 0.0) and scales[control_id] > 0.0:
            relevant.append((control_id, abs(component_kw)))
    if not relevant:
        return False

    current_relevant_kw = sum(scales[key] * component for key, component in relevant)
    if current_relevant_kw <= 1.0e-9:
        return False
    if export:
        fixed_kw = current_value_kw + current_relevant_kw
        allowed_kw = limit_kw + fixed_kw
    else:
        fixed_kw = current_value_kw - current_relevant_kw
        allowed_kw = limit_kw - fixed_kw
    factor = 0.0 if allowed_kw <= 0.0 else min(1.0, allowed_kw / current_relevant_kw)
    if factor >= 1.0 - 1.0e-9:
        return False
    for control_id, _ in relevant:
        scales[control_id] *= factor
    return True


def allocate_electrical_service(
    base_total_kw: float,
    base_phase_kw: Mapping[str, float],
    controls: Mapping[str, PowerRequest],
    total_limits: Mapping[str, Optional[float]],
    per_phase_limits: Mapping[str, Mapping[str, Optional[float]]],
    phase_names: Sequence[str],
) -> ElectricalServiceAllocation:
    """Return reductions and pressure without mutating any input or device.

    Preserve the established eight-pass maximum, scope order (total, then the
    supplied phases) and import-before-export order. Every scope reads totals
    after earlier reductions; opposite-sign controls can couple scopes, requiring
    a later pass. Scales only decrease, preserving proportional sharing within
    each constrained group. There is no redistribution or service prioritisation.
    """
    scales = {control_id: 1.0 for control_id in controls}
    requested_total_kw, requested_phase_kw = _compute_totals(base_total_kw, base_phase_kw, controls, scales)
    requested_violation_kw = electrical_service_violation_kw(
        requested_total_kw, requested_phase_kw, total_limits, per_phase_limits, phase_names)

    for _ in range(8):
        changed = False
        for phase_name in (None, *phase_names):
            limits = total_limits if phase_name is None else per_phase_limits.get(phase_name, {})
            for export in (False, True):
                total_kw, phase_kw = _compute_totals(base_total_kw, base_phase_kw, controls, scales)
                changed |= _scale_scope(
                    total_kw if phase_name is None else phase_kw.get(phase_name, 0.0),
                    limits.get('export_kw' if export else 'import_kw'),
                    controls, scales, phase_name, export=export,
                )
        if not changed:
            break

    total_kw, phase_kw = _compute_totals(base_total_kw, base_phase_kw, controls, scales)
    total_kw = _finite_scalar(total_kw, 0.0)
    phase_kw = {phase: _finite_scalar(value, 0.0) for phase, value in phase_kw.items()}
    residual_violation_kw = electrical_service_violation_kw(
        total_kw, phase_kw, total_limits, per_phase_limits, phase_names)
    return ElectricalServiceAllocation(
        scales, total_kw, phase_kw, requested_violation_kw, residual_violation_kw)
