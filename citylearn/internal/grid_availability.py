"""Time-varying grid import availability for a building's electrical service.

A building's ``electrical_service`` may reference a per-time-step series of the grid power
that the building may import, in [kW]. It models curtailment of the grid connection below its
static capacity, for example a distribution system operator dimming controllable devices
(the German §14a EnWG scheme) or a temporary capacity reduction during grid stress.

The import limit in force at a time step is the smaller of the static
``electrical_service.limits.total.import_kw`` and the series value. A missing (NaN) series value
falls back to the static limit. The limit acts through the existing electrical-service
allocation: EV chargers and the electrical storage are curtailed first, and load that cannot be
curtailed stays served and is recorded as a service violation. It does not island the building;
model a blackout with ``power_outage`` instead.
"""
from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, Any, Mapping, Optional, Tuple

import numpy as np

from citylearn.data import TimeSeriesData

if TYPE_CHECKING:
    from citylearn.internal.loading import CityLearnLoadingService

CONFIG_KEY = 'available_grid_power'
OBSERVATION_NAME = 'available_grid_power'
DEFAULT_COLUMN = 'available_grid_power'
_COLUMN_PREFIX = 'column__'


class GridAvailabilityData(TimeSeriesData):
    """Columns of an available grid power file; one row per dataset time step.

    Every column is kept, so buildings that share one file (one column per building) also share
    one loaded copy. Column values are read through :meth:`column` and follow the episode window
    like any other time series.
    """

    def __init__(self, start_time_step: int = None, end_time_step: int = None, noise_std: float = 0.0,
                 noise_seed: int = None, noise_start_index: int = 0, **columns: Any):
        super().__init__(start_time_step=start_time_step, end_time_step=end_time_step)

        for name, values in columns.items():
            setattr(self, _COLUMN_PREFIX + str(name), np.asarray(values))

    def column_names(self):
        prefix = '_' + _COLUMN_PREFIX
        return [k[len(prefix):] for k in vars(self) if k.startswith(prefix)]

    def column(self, name: str, start_time_step: int = None, end_time_step: int = None) -> np.ndarray:
        """Column values in the current episode window, or in an explicit file-index window."""

        attribute = _COLUMN_PREFIX + name

        if start_time_step is None and end_time_step is None:
            return getattr(self, attribute)

        return self.__getattr__(attribute, start_time_step=start_time_step, end_time_step=end_time_step)

    def replace_column(self, name: str, values: np.ndarray):
        setattr(self, _COLUMN_PREFIX + name, values)


class AvailableGridPower:
    """One building's available grid import power series, in [kW]."""

    def __init__(self, data: GridAvailabilityData, column: str, source: str = None):
        self.data = data
        self.column = column
        self.source = source

    @property
    def values(self) -> np.ndarray:
        """Series in the current episode window, indexed by the building's time step."""

        return self.data.column(self.column)

    def window(self, start_time_step: int, end_time_step: int) -> np.ndarray:
        """Series between two simulation (file) time steps, inclusive."""

        return self.data.column(self.column, start_time_step=start_time_step, end_time_step=end_time_step)

    def value(self, step: int) -> float:
        """Series value at an episode time step; NaN outside the episode or where the file has none."""

        values = self.values
        step = int(step)

        if step < 0 or step >= len(values):
            return float('nan')

        return float(values[step])

    def has_missing_values(self) -> bool:
        """Whether any loaded row, in or out of the current episode, has no value."""

        loaded = self.data.__dict__['_' + _COLUMN_PREFIX + self.column]

        return bool(np.isnan(np.asarray(loaded, dtype='float64')).any())


def parse_config(electrical_service: Optional[Mapping[str, Any]], building_name: str) -> Optional[Tuple[str, Optional[str]]]:
    """Return ``(filename, column)`` from ``electrical_service.available_grid_power``, if set.

    The value is either a file name or a mapping with ``filename`` and an optional ``column``.
    """

    config = (electrical_service or {}).get(CONFIG_KEY) if isinstance(electrical_service, Mapping) else None
    path = f'buildings.{building_name}.electrical_service.{CONFIG_KEY}'

    if config is None:
        return None

    if isinstance(config, str):
        filename, column = config, None

    elif isinstance(config, Mapping):
        unknown = set(config) - {'filename', 'column'}

        if unknown:
            raise ValueError(f'{path} has unknown keys {sorted(unknown)}; use filename and column.')

        filename, column = config.get('filename'), config.get('column')

    else:
        raise ValueError(f'{path} must be a file name or a mapping with filename and column.')

    if not isinstance(filename, str) or filename.strip() == '':
        raise ValueError(f'{path}.filename must be a non-empty file name.')

    if column is not None and (not isinstance(column, str) or column.strip() == ''):
        raise ValueError(f'{path}.column must be a non-empty column name.')

    return filename, column


def _resolve_column(data: GridAvailabilityData, column: Optional[str], building_name: str, source: str) -> str:
    names = data.column_names()

    if column is not None:
        if column not in names:
            raise ValueError(f"Available grid power file '{source}' has no column '{column}'. Columns: {names}.")

        return column

    for candidate in (building_name, DEFAULT_COLUMN):
        if candidate in names:
            return candidate

    raise ValueError(
        f"Available grid power file '{source}' needs a column named '{building_name}' or '{DEFAULT_COLUMN}', "
        'or set electrical_service.available_grid_power.column.'
    )


def _validated_values(raw: np.ndarray, source: str, column: str) -> np.ndarray:
    try:
        values = np.asarray(raw, dtype='float64')

    except (TypeError, ValueError) as error:
        raise ValueError(f"Available grid power column '{column}' in '{source}' must be numeric [kW].") from error

    if np.isinf(values).any():
        raise ValueError(
            f"Available grid power column '{column}' in '{source}' contains infinite values. Leave the value "
            'blank to apply only the static electrical_service.limits.total.import_kw limit.'
        )

    with np.errstate(invalid='ignore'):
        negative = values < 0.0

    if negative.any():
        raise ValueError(
            f"Available grid power column '{column}' in '{source}' must be non-negative [kW]; "
            f'found {int(negative.sum())} negative values.'
        )

    return values


def load(loader: 'CityLearnLoadingService', building_name: str, building_schema: Mapping[str, Any],
         schema: Mapping[str, Any], expected_rows: int, window) -> Optional[AvailableGridPower]:
    """Load a building's available grid power series aligned with its other time series."""

    parsed = parse_config(building_schema.get('electrical_service'), building_name)

    if parsed is None:
        return None

    filename, column = parsed
    filepath = os.path.join(schema['root_directory'], filename)

    if not os.path.isfile(filepath):
        raise FileNotFoundError(
            f"buildings.{building_name}.electrical_service.{CONFIG_KEY} file '{filepath}' was not found."
        )

    data = loader._load_shared_timeseries(
        GridAvailabilityData,
        schema=schema,
        filepath=filepath,
        expected_rows=expected_rows,
        window=window,
        source_label=f'buildings.{building_name}.electrical_service.{CONFIG_KEY}',
        noise_std=0.0,
    )
    column = _resolve_column(data, column, building_name, filepath)
    raw = data.__dict__['_' + _COLUMN_PREFIX + column]
    values = _validated_values(raw, filepath, column)

    if values is not raw:
        # Shared copies are converted once; later buildings find the float column already in place.
        data.replace_column(column, values)

    return AvailableGridPower(data, column, source=filepath)


def _static_import_limit_kw(building) -> float:
    limits = (getattr(building, '_electrical_service_limits', None) or {}).get('total', {}) or {}
    value = limits.get('import_kw')

    if value is None:
        return float('nan')

    value = float(value)

    return value if math.isfinite(value) else float('nan')


def combine(static_kw: float, available_kw):
    """Import limit from the static limit and the series value(s); NaN where neither limits import."""

    available = np.asarray(available_kw, dtype='float64')

    if math.isnan(static_kw):
        combined = available

    else:
        combined = np.where(np.isnan(available), static_kw, np.minimum(available, static_kw))

    return float(combined) if combined.ndim == 0 else combined


def import_limit_kw(building, step: int = None) -> float:
    """Total grid import limit in force at an episode time step, in [kW]; NaN when unlimited."""

    static_kw = _static_import_limit_kw(building)
    availability: Optional[AvailableGridPower] = getattr(building, '_available_grid_power', None)

    if availability is None:
        return static_kw

    step = getattr(building, 'time_step', None) if step is None else step
    # Before the first reset the building has no time step yet; report the first row.
    step = 0 if step is None else step

    return combine(static_kw, availability.value(step))


def import_limit_series_kw(building, start: int, end: int) -> Optional[np.ndarray]:
    """Import limits over episode time steps ``start`` to ``end`` inclusive, or None when static."""

    availability: Optional[AvailableGridPower] = getattr(building, '_available_grid_power', None)

    if availability is None:
        return None

    values = np.full(max(int(end) - int(start) + 1, 0), np.nan, dtype='float64')
    episode = np.asarray(availability.values, dtype='float64')[int(start):int(end) + 1]
    values[:len(episode)] = episode

    return combine(_static_import_limit_kw(building), values)


def total_limits_at(building, total_limits: Mapping[str, Any], step: int = None) -> Mapping[str, Any]:
    """``total_limits`` with the import limit in force at ``step``; unchanged without a series."""

    if getattr(building, '_available_grid_power', None) is None:
        return total_limits

    return {**total_limits, 'import_kw': import_limit_kw(building, step)}


def simulation_limits_kw(building) -> Optional[np.ndarray]:
    """Import limits over the whole simulation period (for observation-space bounds)."""

    availability: Optional[AvailableGridPower] = getattr(building, '_available_grid_power', None)

    if availability is None:
        return None

    tracker = building.episode_tracker
    values = availability.window(tracker.simulation_start_time_step, tracker.simulation_end_time_step)

    return np.atleast_1d(combine(_static_import_limit_kw(building), values))
