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


FEEDER_EXCEEDANCE_EPS_KW = 1.0e-5


def _parse_district_limit_spec(value, path: str, *, enabled: bool):
    """Parse a static non-negative limit [kW] or a dataset-indexed per-step sequence of limits."""
    import math as _math
    import numpy as np

    if value is None:
        return None

    if isinstance(value, bool):
        raise ValueError(f'{path} must be a non-negative number, sequence, or null.')

    if isinstance(value, (int, float, np.number)):
        scalar = float(value)
        if _math.isnan(scalar):
            raise ValueError(f'{path} cannot be NaN.')
        if _math.isinf(scalar):
            if scalar < 0.0:
                raise ValueError(f'{path} must be >= 0.0 when provided.')
            return None
        if scalar < 0.0:
            raise ValueError(f'{path} must be >= 0.0 when provided.')
        return scalar

    if isinstance(value, (str, bytes, Mapping)):
        raise ValueError(f'{path} must be a non-negative number, sequence, or null.')

    try:
        items = list(np.asarray(value).tolist() if isinstance(value, np.ndarray) else value)
    except TypeError as exc:
        raise ValueError(f'{path} must be a non-negative number, sequence, or null.') from exc

    if len(items) == 0:
        if enabled:
            raise ValueError(f'{path} sequence cannot be empty when district_electrical_service is enabled.')
        return None

    parsed_items = []
    for idx, item in enumerate(items):
        if item is None:
            parsed_items.append(None)
            continue
        if isinstance(item, bool):
            raise ValueError(f'{path}[{idx}] must be a non-negative number or null.')
        try:
            scalar = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{path}[{idx}] must be a non-negative number or null.') from exc
        if _math.isnan(scalar):
            parsed_items.append(None)
            continue
        if _math.isinf(scalar):
            if scalar < 0.0:
                raise ValueError(f'{path}[{idx}] must be >= 0.0 when provided.')
            parsed_items.append(None)
            continue
        if scalar < 0.0:
            raise ValueError(f'{path}[{idx}] must be >= 0.0 when provided.')
        parsed_items.append(scalar)

    return tuple(parsed_items)


def parse_district_electrical_service_config(config) -> Dict[str, object]:
    """Validate and normalize ``district_electrical_service`` configuration."""
    from citylearn.utilities import parse_bool

    if config is None:
        return {'enabled': False, 'import_kw': None, 'export_kw': None}

    if not isinstance(config, Mapping):
        raise ValueError('district_electrical_service must be a mapping or None.')

    unknown = set(config.keys()) - {'enabled', 'limits'}
    if unknown:
        raise ValueError(f'district_electrical_service has unknown keys {sorted(unknown)}; use enabled and limits.')

    enabled = bool(parse_bool(config.get('enabled', False), default=False, path='district_electrical_service.enabled'))
    limits = config.get('limits')
    if limits is None:
        limits = {}
    elif not isinstance(limits, Mapping):
        raise ValueError('district_electrical_service.limits must be a mapping when provided.')

    unknown_limits = set(limits.keys()) - {'import_kw', 'export_kw', 'total'}
    if unknown_limits:
        raise ValueError(
            f'district_electrical_service.limits has unknown keys {sorted(unknown_limits)}; '
            'use import_kw and export_kw.'
        )

    total_block = limits.get('total')
    if total_block is not None and not isinstance(total_block, Mapping):
        raise ValueError('district_electrical_service.limits.total must be a mapping when provided.')
    if isinstance(total_block, Mapping):
        unknown_total = set(total_block.keys()) - {'import_kw', 'export_kw'}
        if unknown_total:
            raise ValueError(
                f'district_electrical_service.limits.total has unknown keys {sorted(unknown_total)}; '
                'use import_kw and export_kw.'
            )

    raw_import = limits.get('import_kw', total_block.get('import_kw') if isinstance(total_block, Mapping) else None)
    raw_export = limits.get('export_kw', total_block.get('export_kw') if isinstance(total_block, Mapping) else None)

    import_kw = _parse_district_limit_spec(raw_import, 'district_electrical_service.limits.import_kw', enabled=enabled)
    export_kw = _parse_district_limit_spec(raw_export, 'district_electrical_service.limits.export_kw', enabled=enabled)

    if enabled and import_kw is None and export_kw is None:
        # An unconfigured direction is undefined, so every feeder KPI would be NaN.
        raise ValueError(
            'district_electrical_service is enabled but has no limit: give limits.import_kw and/or '
            'limits.export_kw (a finite kW value or a per-step sequence), or set enabled to false. '
            'Without a limit every feeder exceedance KPI would be NaN.'
        )

    return {
        'enabled': enabled,
        'import_kw': import_kw,
        'export_kw': export_kw,
    }


def _serialize_limit_spec(spec):
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return float(spec) if isfinite(float(spec)) else None
    if isinstance(spec, tuple):
        return [None if item is None else float(item) for item in spec]
    return None


def serialize_district_electrical_service_config(parsed_config: Optional[Mapping[str, object]]) -> Dict[str, object]:
    """Return a canonical JSON-serializable representation of ``parsed_config`` for schemas and manifests."""
    if not parsed_config or not bool(parsed_config.get('enabled', False)):
        return {'enabled': False, 'limits': {'import_kw': None, 'export_kw': None}}

    return {
        'enabled': True,
        'limits': {
            'import_kw': _serialize_limit_spec(parsed_config.get('import_kw')),
            'export_kw': _serialize_limit_spec(parsed_config.get('export_kw')),
        },
    }


def validate_district_feeder_schedule_bounds(
    parsed_config: Optional[Mapping[str, object]],
    *,
    simulation_start_time_step: int = 0,
    simulation_end_time_step: int = 0,
    episode_start_time_step: Optional[int] = None,
    episode_end_time_step: Optional[int] = None,
) -> None:
    """Validate that dataset-indexed sequence limits cover all executed dataset time steps."""
    if not parsed_config or not bool(parsed_config.get('enabled', False)):
        return

    sim_start = max(int(simulation_start_time_step or 0), 0)
    sim_end = max(int(simulation_end_time_step or 0), sim_start)
    # A window [start, end] with end > start executes transitions at dataset steps start .. end - 1.
    max_executed_step = sim_end - 1 if sim_end > sim_start else sim_start

    if episode_start_time_step is not None and episode_end_time_step is not None:
        ep_start = max(int(episode_start_time_step), 0)
        ep_end = max(int(episode_end_time_step), ep_start)
        ep_max_executed = ep_end - 1 if ep_end > ep_start else ep_start
        max_executed_step = max(max_executed_step, ep_max_executed)

    required_len = max_executed_step + 1
    for key in ('import_kw', 'export_kw'):
        spec = parsed_config.get(key)
        if isinstance(spec, tuple) and len(spec) < required_len:
            raise ValueError(
                f'district_electrical_service.limits.{key} sequence has length {len(spec)}, '
                f'which does not cover executed dataset time step {max_executed_step} '
                f'(schedules are anchored at dataset step 0 and need at least {required_len} entries).'
            )


def resolve_district_feeder_limits_at(
    parsed_config: Mapping[str, object],
    time_step: int,
    *,
    episode_start_time_step: int = 0,
    episode_time_steps: Optional[int] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Resolve scalar ``(import_kw, export_kw)`` feeder limits at dataset step ``episode_start_time_step + time_step``."""
    del episode_time_steps  # Sequences are always anchored to dataset step 0.
    resolved = []
    step = max(int(time_step), 0)
    offset = max(int(episode_start_time_step), 0)
    global_step = offset + step

    for key in ('import_kw', 'export_kw'):
        spec = parsed_config.get(key)
        if spec is None or isinstance(spec, float):
            resolved.append(spec)
            continue
        if isinstance(spec, tuple):
            if global_step >= len(spec):
                raise ValueError(
                    f'district_electrical_service.limits.{key} sequence has length {len(spec)}, '
                    f'which does not cover dataset time step {global_step} '
                    f'(episode_start_time_step={offset}, time_step={step}).'
                )
            resolved.append(spec[global_step])
            continue
        resolved.append(None)

    return resolved[0], resolved[1]


def district_feeder_exceedances_kw(
    total_power_kw: float,
    import_limit_kw: Optional[float],
    export_limit_kw: Optional[float],
    *,
    eps_kw: float = FEEDER_EXCEEDANCE_EPS_KW,
) -> Tuple[float, float]:
    """Return ``(import_exceedance_kw, export_exceedance_kw)`` on settled district net power."""
    power = _finite_scalar(total_power_kw, 0.0)
    imp = _finite_scalar(import_limit_kw, float('nan'))
    exp = _finite_scalar(export_limit_kw, float('nan'))

    imp_exc = 0.0
    if isfinite(imp):
        excess = max(power - imp, 0.0)
        if excess > eps_kw:
            imp_exc = float(excess)

    exp_exc = 0.0
    if isfinite(exp):
        excess = max(-power - exp, 0.0)
        if excess > eps_kw:
            exp_exc = float(excess)

    return imp_exc, exp_exc


def district_feeder_direction_configured(
    parsed_config: Optional[Mapping[str, object]],
    direction: str,
    executed_steps: int,
    *,
    episode_start_time_step: int = 0,
) -> bool:
    """Return True when ``direction`` ('import' or 'export') defines at least one active limit."""
    if not parsed_config or not bool(parsed_config.get('enabled', False)):
        return False
    spec = parsed_config.get(f'{direction}_kw')
    if spec is None:
        return False
    if isinstance(spec, (int, float)):
        return isfinite(float(spec))
    if isinstance(spec, tuple):
        if executed_steps <= 0:
            return any(item is not None and isfinite(float(item)) for item in spec)
        offset = max(int(episode_start_time_step), 0)
        window = spec[offset:min(offset + executed_steps, len(spec))]
        return any(item is not None and isfinite(float(item)) for item in window)
    return False
