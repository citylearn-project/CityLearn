"""Opt-in recurring local evaluation-window configuration, step overlap weights, and KPI calculations."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from citylearn.internal.units import seconds_to_hours
from citylearn.utilities import parse_bool

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv
    from citylearn.internal.kpi import CityLearnKPIService


DEFAULT_EVALUATION_WINDOW_START = '16:00:00'
DEFAULT_EVALUATION_WINDOW_END = '19:00:00'
DEFAULT_EVALUATION_WINDOW_TIMEZONE = 'scenario_local'

_CLOCK_PATTERN = re.compile(r'^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$')


def _parse_clock_time(value: Any, path: str) -> Tuple[int, str]:
    """Parse ``'HH:MM'`` or ``'HH:MM:SS'`` into ``(seconds_of_day, 'HH:MM:SS')``."""
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a 'HH:MM' or 'HH:MM:SS' string.")

    match = _CLOCK_PATTERN.match(value)
    if match is None:
        raise ValueError(f"{path} must be in 'HH:MM' or 'HH:MM:SS' 24-hour format, got {value!r}.")

    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or '0')

    if hour == 24 and minute == 0 and second == 0:
        return 0, '00:00:00'
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"{path} has out-of-range clock time {value!r}.")

    total_seconds = hour * 3600 + minute * 60 + second
    return total_seconds, f'{hour:02d}:{minute:02d}:{second:02d}'


def _resolve_timezone(raw_tz: Any, schema_timezone: Optional[str]) -> str:
    tz_candidate = raw_tz if raw_tz is not None else schema_timezone
    if tz_candidate is None or str(tz_candidate).strip() == '':
        return DEFAULT_EVALUATION_WINDOW_TIMEZONE

    tz_str = str(tz_candidate).strip()
    if tz_str == DEFAULT_EVALUATION_WINDOW_TIMEZONE:
        return DEFAULT_EVALUATION_WINDOW_TIMEZONE

    try:
        ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise ValueError(f'evaluation_window.timezone {tz_str!r} is not a valid IANA time zone.') from exc
    return tz_str


def parse_evaluation_window_config(
    config: Any,
    *,
    schema_timezone: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate and normalize ``evaluation_window`` configuration."""
    if config is None or config is False:
        tz = _resolve_timezone(None, schema_timezone)
        return {
            'enabled': False,
            'start': None,
            'end': None,
            'start_seconds': None,
            'end_seconds': None,
            'timezone': tz,
        }

    if config is True:
        tz = _resolve_timezone(None, schema_timezone)
        start_s, start_str = _parse_clock_time(DEFAULT_EVALUATION_WINDOW_START, 'evaluation_window.start')
        end_s, end_str = _parse_clock_time(DEFAULT_EVALUATION_WINDOW_END, 'evaluation_window.end')
        return {
            'enabled': True,
            'start': start_str,
            'end': end_str,
            'start_seconds': start_s,
            'end_seconds': end_s,
            'timezone': tz,
        }

    if not isinstance(config, Mapping):
        raise ValueError('evaluation_window must be a boolean, mapping, or None.')

    unknown = set(config.keys()) - {'enabled', 'start', 'end', 'timezone'}
    if unknown:
        raise ValueError(
            f'evaluation_window has unknown keys {sorted(unknown)}; use enabled, start, end, and timezone.'
        )

    tz = _resolve_timezone(config.get('timezone'), schema_timezone)
    has_bounds = ('start' in config and config.get('start') is not None) or (
        'end' in config and config.get('end') is not None
    )
    enabled = bool(
        parse_bool(
            config.get('enabled', has_bounds),
            default=has_bounds,
            path='evaluation_window.enabled',
        )
    )
    if not enabled:
        return {
            'enabled': False,
            'start': None,
            'end': None,
            'start_seconds': None,
            'end_seconds': None,
            'timezone': tz,
        }

    raw_start = config.get('start')
    raw_end = config.get('end')
    start_s, start_str = _parse_clock_time(
        DEFAULT_EVALUATION_WINDOW_START if raw_start is None else raw_start,
        'evaluation_window.start',
    )
    end_s, end_str = _parse_clock_time(
        DEFAULT_EVALUATION_WINDOW_END if raw_end is None else raw_end,
        'evaluation_window.end',
    )
    if start_s == end_s:
        raise ValueError('evaluation_window start and end must define a non-empty sub-24h window.')

    return {
        'enabled': True,
        'start': start_str,
        'end': end_str,
        'start_seconds': start_s,
        'end_seconds': end_s,
        'timezone': tz,
    }


def serialize_evaluation_window_config(parsed_config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a canonical JSON-serializable representation of ``parsed_config`` for schemas and manifests."""
    if not parsed_config or not bool(parsed_config.get('enabled', False)):
        tz = (
            str(parsed_config.get('timezone'))
            if isinstance(parsed_config, Mapping) and parsed_config.get('timezone')
            else DEFAULT_EVALUATION_WINDOW_TIMEZONE
        )
        return {
            'enabled': False,
            'start': None,
            'end': None,
            'timezone': tz,
        }

    return {
        'enabled': True,
        'start': str(parsed_config['start']),
        'end': str(parsed_config['end']),
        'timezone': str(parsed_config.get('timezone') or DEFAULT_EVALUATION_WINDOW_TIMEZONE),
    }


def _interval_overlap_seconds(
    step_start_sec: float,
    step_duration_sec: float,
    win_segments: Sequence[Tuple[float, float]],
    win_daily_sec: float,
) -> float:
    """Overlap in seconds between ``[step_start_sec, step_start_sec + step_duration_sec)`` and daily ``win_segments``."""
    if step_duration_sec <= 0.0 or win_daily_sec <= 0.0:
        return 0.0

    full_days = int(step_duration_sec // 86400.0)
    rem = step_duration_sec - full_days * 86400.0
    overlap = full_days * win_daily_sec
    if rem <= 1.0e-12:
        return overlap

    a0 = float(step_start_sec % 86400.0)
    a1 = a0 + rem
    step_segments = [(a0, min(a1, 86400.0))]
    if a1 > 86400.0 + 1.0e-12:
        step_segments.append((0.0, a1 - 86400.0))

    for s0, s1 in step_segments:
        for w0, w1 in win_segments:
            hi = min(s1, w1)
            lo = max(s0, w0)
            if hi > lo:
                overlap += hi - lo
    return min(step_duration_sec, max(0.0, overlap))


def _step_start_seconds_array(
    env: "CityLearnEnv",
    parsed_config: Mapping[str, Any],
    executed_steps: int,
    *,
    reference_building: Any = None,
) -> Optional[np.ndarray]:
    """Return local wall-clock start second-of-day ``[0, 86400)`` for each executed step ``0 .. executed_steps - 1``."""
    if executed_steps <= 0:
        return np.zeros(0, dtype='float64')

    step_seconds = max(float(getattr(env, 'seconds_per_time_step', 3600.0) or 3600.0), 1.0e-9)
    axis = getattr(env, '_time_axis', None)
    tracker = getattr(env, 'episode_tracker', None)
    ep_start = int(getattr(tracker, 'episode_start_time_step', 0) or 0)

    if axis is not None and getattr(axis, 'utc', None) is not None:
        tz_name = str(parsed_config.get('timezone') or '')
        if not tz_name or tz_name == DEFAULT_EVALUATION_WINDOW_TIMEZONE:
            tz_name = getattr(axis, 'timezone', None) or 'UTC'
        tz_info = ZoneInfo(tz_name)
        starts = np.empty(executed_steps, dtype='float64')
        for t in range(executed_steps):
            dt_utc = axis.at(ep_start + t)
            dt_loc = dt_utc.astimezone(tz_info)
            starts[t] = (
                dt_loc.hour * 3600.0
                + dt_loc.minute * 60.0
                + dt_loc.second
                + dt_loc.microsecond * 1.0e-6
            )
        return starts

    building = reference_building
    if building is None:
        buildings = list(getattr(env, '_all_buildings', None) or getattr(env, 'buildings', []) or [])
        building = buildings[0] if buildings else None
    if building is None or getattr(building, 'energy_simulation', None) is None:
        return None

    es = building.energy_simulation
    hours = getattr(es, 'hour', None)
    if hours is None or len(hours) == 0:
        return None

    n = min(executed_steps, len(hours))
    h_arr = np.asarray(hours[:n], dtype='float64')
    if not np.isfinite(h_arr).all():
        return None
    # CityLearn dataset hour runs 1..24 where hour=1, minutes=0 is 00:00 (matching _build_calendar_temporal_metrics).
    h_mod = np.mod(np.rint(h_arr) - 1.0, 24.0)

    mins = getattr(es, 'minutes', None)
    secs = getattr(es, 'seconds', None)
    has_mins = mins is not None and len(mins) >= n
    has_secs = secs is not None and len(secs) >= n

    m_mod = np.mod(np.rint(np.asarray(mins[:n], dtype='float64')), 60.0) if has_mins else np.zeros(n, dtype='float64')
    s_mod = np.mod(np.asarray(secs[:n], dtype='float64'), 60.0) if has_secs else np.zeros(n, dtype='float64')

    raw_sec = np.mod(h_mod * 3600.0 + m_mod * 60.0 + s_mod, 86400.0)
    calendar_resolution = 1.0 if has_secs else (60.0 if has_mins else 3600.0)

    # Sub-minute or sub-hour steps without finer calendar columns repeat coarse stamps across sub-steps.
    if step_seconds + 1.0e-9 < calendar_resolution and n > 1:
        adjusted = raw_sec.copy()
        run_origin = raw_sec[0]
        run_offset = 0
        for idx in range(1, n):
            if abs(raw_sec[idx] - run_origin) <= 1.0e-9 and (run_offset + 1) * step_seconds < calendar_resolution + 1.0e-9:
                run_offset += 1
                adjusted[idx] = (run_origin + run_offset * step_seconds) % 86400.0
            else:
                run_origin = raw_sec[idx]
                run_offset = 0
        raw_sec = adjusted

    if n < executed_steps:
        pad = np.array(
            [(raw_sec[-1] + (k + 1) * step_seconds) % 86400.0 for k in range(executed_steps - n)],
            dtype='float64',
        )
        raw_sec = np.concatenate([raw_sec, pad])

    return raw_sec


def step_overlap_weights(
    env: "CityLearnEnv",
    parsed_config: Mapping[str, Any],
    executed_steps: int,
    *,
    reference_building: Any = None,
) -> np.ndarray:
    """Fraction ``w_t in [0, 1]`` of each executed step falling inside ``parsed_config``'s daily window."""
    if not parsed_config or not bool(parsed_config.get('enabled', False)) or executed_steps <= 0:
        return np.zeros(max(executed_steps, 0), dtype='float64')

    starts = _step_start_seconds_array(
        env, parsed_config, executed_steps, reference_building=reference_building
    )
    if starts is None or starts.size == 0:
        return np.zeros(max(executed_steps, 0), dtype='float64')

    step_seconds = max(float(getattr(env, 'seconds_per_time_step', 3600.0) or 3600.0), 1.0e-9)
    start_s = float(parsed_config['start_seconds'])
    end_s = float(parsed_config['end_seconds'])

    if start_s < end_s:
        win_segments = [(start_s, end_s)]
        win_daily_sec = end_s - start_s
    else:
        win_segments = [(start_s, 86400.0)]
        if end_s > 0.0:
            win_segments.append((0.0, end_s))
        win_daily_sec = (86400.0 - start_s) + end_s

    weights = np.empty(executed_steps, dtype='float64')
    for t in range(executed_steps):
        ov_sec = _interval_overlap_seconds(float(starts[t]), step_seconds, win_segments, win_daily_sec)
        weights[t] = ov_sec / step_seconds
    return weights


def compute_evaluation_window_control_records(
    kpi: "CityLearnKPIService",
    *,
    kpi_buildings: Sequence[Any],
    building_windows: Mapping[str, Tuple[int, int]],
) -> List[Dict[str, object]]:
    """Compute opt-in control KPI rows for ``evaluation_window`` at building and district levels."""
    env = kpi.env
    parsed = getattr(env, '_evaluation_window_parsed', None)
    if not parsed or not bool(parsed.get('enabled', False)):
        return []

    step_seconds = max(float(getattr(env, 'seconds_per_time_step', 3600.0) or 3600.0), 1.0e-9)
    step_hours = max(seconds_to_hours(step_seconds), 1.0e-12)
    executed_steps = min(
        len(getattr(env, 'net_electricity_consumption', []) or []),
        max(int(getattr(env, 'time_step', 0) or 0), 0),
    )

    rows: List[Dict[str, object]] = []

    def add(level: str, name: str, cost_function: str, value: Optional[float]) -> None:
        rows.append({
            'cost_function': cost_function,
            'value': value,
            'name': name,
            'level': level,
        })

    ref_building = kpi_buildings[0] if kpi_buildings else None
    district_weights = step_overlap_weights(env, parsed, executed_steps, reference_building=ref_building)
    district_charger_net_kwh = np.zeros(executed_steps, dtype='float64')

    for building in kpi_buildings:
        b_name = str(building.name)
        t_start, t_end_raw = building_windows.get(b_name, (0, -1))
        b_net_all = np.asarray(getattr(building, 'net_electricity_consumption', []), dtype='float64')
        start = max(int(t_start), 0)
        end = min(int(t_end_raw), executed_steps - 1, len(b_net_all) - 1)

        if executed_steps <= 0 or end < start:
            add('building', b_name, 'building_energy_grid_window_average_power_control_kw', None)
            add('building', b_name, 'building_ev_window_net_exchange_control_kwh', None)
            continue

        b_weights = step_overlap_weights(env, parsed, executed_steps, reference_building=building)[start:end + 1]
        active_len = end - start + 1
        charger_net = np.zeros(active_len, dtype='float64')
        for charger in kpi._chargers_for_metrics(building):
            c_arr = np.asarray(getattr(charger, 'electricity_consumption', []), dtype='float64')
            c_slice = c_arr[start:min(end + 1, c_arr.size)]
            if c_slice.size > 0:
                valid = np.where(np.isfinite(c_slice), c_slice, 0.0)
                charger_net[:valid.size] += valid

        district_charger_net_kwh[start:end + 1] += charger_net

        overlap_hours = float(np.sum(b_weights) * step_hours)
        if overlap_hours <= 1.0e-12:
            add('building', b_name, 'building_energy_grid_window_average_power_control_kw', None)
            add('building', b_name, 'building_ev_window_net_exchange_control_kwh', None)
            continue

        b_net_slice = b_net_all[start:end + 1]
        if not np.isfinite(b_net_slice).all():
            valid_mask = np.isfinite(b_net_slice)
            valid_hours = float(np.sum(b_weights[valid_mask]) * step_hours)
            grid_kw = (
                float(np.sum(b_weights[valid_mask] * b_net_slice[valid_mask]) / valid_hours)
                if valid_hours > 1.0e-12
                else None
            )
        else:
            grid_kw = float(np.sum(b_weights * b_net_slice) / overlap_hours)

        ev_net_kwh = float(np.sum(b_weights * charger_net))
        add('building', b_name, 'building_energy_grid_window_average_power_control_kw', grid_kw)
        add('building', b_name, 'building_ev_window_net_exchange_control_kwh', ev_net_kwh)

    d_overlap_hours = float(np.sum(district_weights) * step_hours) if executed_steps > 0 else 0.0
    if executed_steps <= 0 or d_overlap_hours <= 1.0e-12:
        add('district', 'District', 'district_energy_grid_window_average_power_control_kw', None)
        add('district', 'District', 'district_ev_window_net_exchange_control_kwh', None)
        return rows

    d_net_all = np.asarray(env.net_electricity_consumption[:executed_steps], dtype='float64')
    if not np.isfinite(d_net_all).all():
        d_mask = np.isfinite(d_net_all)
        valid_d_hours = float(np.sum(district_weights[d_mask]) * step_hours)
        d_grid_kw = (
            float(np.sum(district_weights[d_mask] * d_net_all[d_mask]) / valid_d_hours)
            if valid_d_hours > 1.0e-12
            else None
        )
    else:
        d_grid_kw = float(np.sum(district_weights * d_net_all) / d_overlap_hours)

    d_ev_net_kwh = float(np.sum(district_weights * district_charger_net_kwh))
    add('district', 'District', 'district_energy_grid_window_average_power_control_kw', d_grid_kw)
    add('district', 'District', 'district_ev_window_net_exchange_control_kwh', d_ev_net_kwh)
    return rows
