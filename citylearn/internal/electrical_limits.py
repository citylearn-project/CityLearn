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


@dataclass(frozen=True)
class DistrictFeederAllocation:
    scales: Dict[str, float]
    projected_power_kw: float
    curtailed: bool


def _parse_district_limit_spec(value, path: str, *, enabled: bool):
    """Parse a static non-negative limit [kW] or a per-step sequence of limits."""
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

    return {
        'enabled': enabled,
        'import_kw': _parse_district_limit_spec(
            raw_import, 'district_electrical_service.limits.import_kw', enabled=enabled
        ),
        'export_kw': _parse_district_limit_spec(
            raw_export, 'district_electrical_service.limits.export_kw', enabled=enabled
        ),
    }


def resolve_district_feeder_limits_at(
    parsed_config: Mapping[str, object],
    time_step: int,
    *,
    episode_start_time_step: int = 0,
    episode_time_steps: Optional[int] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """Resolve scalar ``(import_kw, export_kw)`` feeder limits for ``time_step``."""
    resolved = []
    step = max(int(time_step), 0)
    offset = max(int(episode_start_time_step), 0)

    for key in ('import_kw', 'export_kw'):
        spec = parsed_config.get(key)
        if spec is None or isinstance(spec, float):
            resolved.append(spec)
            continue
        if isinstance(spec, tuple):
            n = len(spec)
            if n == 0:
                resolved.append(None)
                continue
            if episode_time_steps is not None and n > int(episode_time_steps) and offset + step < n:
                idx = offset + step
            else:
                idx = min(step, n - 1)
            resolved.append(spec[idx])
            continue
        resolved.append(None)

    return resolved[0], resolved[1]


def district_feeder_violation_kw(
    total_power_kw: float,
    import_limit_kw: Optional[float],
    export_limit_kw: Optional[float],
    *,
    residual_eps_kw: float = 1.0e-5,
) -> float:
    """Residual excess over ``import_limit_kw`` or ``export_limit_kw`` in [kW]."""
    power = _finite_scalar(total_power_kw, 0.0)
    violation = 0.0
    imp = _finite_scalar(import_limit_kw, float('nan'))
    exp = _finite_scalar(export_limit_kw, float('nan'))
    if isfinite(imp):
        excess = max(power - imp, 0.0)
        if excess > residual_eps_kw:
            violation += excess
    if isfinite(exp):
        excess = max(-power - exp, 0.0)
        if excess > residual_eps_kw:
            violation += excess
    return float(violation)


def _waterfill_deadband_subset(
    group_ids: Sequence[str],
    active_ids: Sequence[str],
    u_kw: Mapping[str, float],
    m_kw: Mapping[str, float],
    target_sum_kw: float,
) -> Tuple[Dict[str, float], bool]:
    """Allocate ``target_sum_kw`` across ``active_ids`` respecting ``m_kw[i] <= x[i] <= u_kw[i]``."""
    alloc = {cid: 0.0 for cid in group_ids}
    if not active_ids or target_sum_kw <= 1.0e-12:
        return alloc, True

    u_sum = sum(u_kw[cid] for cid in active_ids)
    if target_sum_kw >= u_sum - 1.0e-12:
        for cid in active_ids:
            alloc[cid] = u_kw[cid]
        return alloc, True

    m_sum = sum(m_kw[cid] for cid in active_ids)
    if target_sum_kw <= m_sum + 1.0e-12:
        for cid in active_ids:
            alloc[cid] = m_kw[cid]
        return alloc, (m_sum <= 1.0e-12)

    unpinned = list(active_ids)
    rem = float(target_sum_kw)
    pinned_any = False

    while unpinned:
        rem_u = sum(u_kw[cid] for cid in unpinned)
        if rem_u <= 1.0e-12:
            break
        alpha = rem / rem_u
        below = [cid for cid in unpinned if alpha * u_kw[cid] + 1.0e-12 < m_kw[cid]]
        if not below:
            for cid in unpinned:
                alloc[cid] = min(u_kw[cid], max(m_kw[cid], alpha * u_kw[cid]))
            break
        pinned_any = True
        for cid in below:
            alloc[cid] = m_kw[cid]
            rem = max(0.0, rem - m_kw[cid])
        below_set = set(below)
        unpinned = [cid for cid in unpinned if cid not in below_set]

    return alloc, (not pinned_any)


def _allocate_one_side_with_deadband(
    group_ids: Sequence[str],
    u_kw: Mapping[str, float],
    m_kw: Mapping[str, float],
    c_min_kw: float,
    c_max_kw: float,
) -> Dict[str, float]:
    """Choose scales in ``[0, 1]`` for ``group_ids`` minimizing violation of ``[c_min_kw, c_max_kw]``."""
    from itertools import combinations

    if not group_ids:
        return {}

    if c_max_kw <= 1.0e-12:
        return {cid: 0.0 for cid in group_ids}

    g_zero = [cid for cid in group_ids if m_kw[cid] <= 1.0e-9]
    g_plus = [cid for cid in group_ids if m_kw[cid] > 1.0e-9]

    if not g_plus:
        u_total = sum(u_kw[cid] for cid in group_ids)
        target = min(u_total, c_max_kw)
        factor = 0.0 if u_total <= 1.0e-12 else min(1.0, max(0.0, target / u_total))
        return {cid: factor for cid in group_ids}

    candidate_sets = []
    seen = set()

    def add_candidate(seq: Sequence[str]) -> None:
        key = tuple(seq)
        if key not in seen:
            seen.add(key)
            candidate_sets.append(key)

    if len(g_plus) <= 12:
        for k in range(len(g_plus), -1, -1):
            for subset in combinations(g_plus, k):
                add_candidate(subset)
    else:
        # Iterative proportional drop (batch and single-worst) plus ordered prefixes.
        cur = list(g_plus)
        while True:
            add_candidate(cur)
            if not cur:
                break
            active = cur + g_zero
            u_sum = sum(u_kw[cid] for cid in active)
            target = min(u_sum, c_max_kw)
            alpha = 0.0 if u_sum <= 1.0e-12 else target / u_sum
            violators = [cid for cid in cur if alpha * u_kw[cid] + 1.0e-9 < m_kw[cid]]
            if not violators:
                break
            viol_set = set(violators)
            cur = [cid for cid in cur if cid not in viol_set]

        cur = list(g_plus)
        while cur:
            add_candidate(cur)
            active = cur + g_zero
            u_sum = sum(u_kw[cid] for cid in active)
            target = min(u_sum, c_max_kw)
            alpha = 0.0 if u_sum <= 1.0e-12 else target / u_sum
            worst = max(cur, key=lambda cid: m_kw[cid] - alpha * u_kw[cid])
            cur = [cid for cid in cur if cid != worst]
        add_candidate(())

        for ordered in (
            sorted(g_plus, key=lambda cid: (m_kw[cid], -u_kw[cid])),
            sorted(g_plus, key=lambda cid: (m_kw[cid] / max(u_kw[cid], 1.0e-12), m_kw[cid])),
        ):
            for k in range(len(ordered), -1, -1):
                add_candidate(ordered[:k])

    best_score = None
    best_alloc = None

    for subset in candidate_sets:
        active = list(subset) + g_zero
        m_sum = sum(m_kw[cid] for cid in subset)
        u_sum = sum(u_kw[cid] for cid in active)
        target = min(u_sum, c_max_kw) if m_sum <= c_max_kw else m_sum
        viol = max(0.0, target - c_max_kw) + max(0.0, c_min_kw - target)
        viol_key = 0.0 if viol <= 1.0e-7 else round(viol, 9)
        alloc, unpinned_ok = _waterfill_deadband_subset(group_ids, active, u_kw, m_kw, target)
        score = (viol_key, -round(target, 7), 0 if unpinned_ok else 1, -len(subset))
        if best_score is None or score < best_score:
            best_score = score
            best_alloc = alloc

    assert best_alloc is not None
    return {
        cid: min(1.0, max(0.0, best_alloc[cid] / u_kw[cid]))
        for cid in group_ids
    }


def allocate_district_feeder_envelope(
    total_power_kw: float,
    controls_power_kw: Mapping[str, float],
    import_limit_kw: Optional[float],
    export_limit_kw: Optional[float],
    *,
    controls_min_power_kw: Optional[Mapping[str, float]] = None,
    tolerance_kw: float = 1.0e-6,
) -> DistrictFeederAllocation:
    """Curtail controllable charging/discharging to satisfy shared feeder import and export limits.

    Accounts for minimum-power deadbands (e.g. EV charger ``min_charging_power`` /
    ``min_discharging_power``) and checks both directions so pausing a deadband-constrained
    device does not overshoot the opposite feeder limit when continuous controls can hold power
    inside ``[-export_limit_kw, +import_limit_kw]``.
    """
    scales: Dict[str, float] = {cid: 1.0 for cid in controls_power_kw}
    min_map = controls_min_power_kw or {}
    base_kw = float(total_power_kw) - sum(float(p) for p in controls_power_kw.values())

    pos_ids = [cid for cid, p in controls_power_kw.items() if float(p) > 1.0e-9]
    neg_ids = [cid for cid, p in controls_power_kw.items() if float(p) < -1.0e-9]

    pos_u = {cid: float(controls_power_kw[cid]) for cid in pos_ids}
    pos_m = {
        cid: min(max(_finite_scalar(min_map.get(cid, 0.0), 0.0), 0.0), pos_u[cid])
        for cid in pos_ids
    }
    neg_u = {cid: -float(controls_power_kw[cid]) for cid in neg_ids}
    neg_m = {
        cid: min(max(_finite_scalar(min_map.get(cid, 0.0), 0.0), 0.0), neg_u[cid])
        for cid in neg_ids
    }

    def current_total() -> float:
        return (
            base_kw
            + sum(pos_u[cid] * scales[cid] for cid in pos_ids)
            - sum(neg_u[cid] * scales[cid] for cid in neg_ids)
        )

    imp = _finite_scalar(import_limit_kw, float('nan'))
    exp = _finite_scalar(export_limit_kw, float('nan'))

    for _ in range(2):
        changed = False
        cur_kw = current_total()
        if isfinite(imp) and cur_kw > imp + tolerance_kw and pos_ids:
            fixed_other_kw = base_kw - sum(neg_u[cid] * scales[cid] for cid in neg_ids)
            c_max = imp - fixed_other_kw
            c_min = max(0.0, -exp - fixed_other_kw) if isfinite(exp) else 0.0
            new_pos = _allocate_one_side_with_deadband(pos_ids, pos_u, pos_m, c_min, c_max)
            for cid, s in new_pos.items():
                if abs(s - scales[cid]) > 1.0e-9:
                    scales[cid] = s
                    changed = True

        cur_kw = current_total()
        if isfinite(exp) and -cur_kw > exp + tolerance_kw and neg_ids:
            fixed_other_kw = base_kw + sum(pos_u[cid] * scales[cid] for cid in pos_ids)
            c_max = exp + fixed_other_kw
            c_min = max(0.0, fixed_other_kw - imp) if isfinite(imp) else 0.0
            new_neg = _allocate_one_side_with_deadband(neg_ids, neg_u, neg_m, c_min, c_max)
            for cid, s in new_neg.items():
                if abs(s - scales[cid]) > 1.0e-9:
                    scales[cid] = s
                    changed = True

        if not changed:
            break

    projected = _finite_scalar(current_total(), 0.0)
    curtailed = any(scale < 1.0 - 1.0e-9 for scale in scales.values())
    return DistrictFeederAllocation(scales=scales, projected_power_kw=projected, curtailed=curtailed)
