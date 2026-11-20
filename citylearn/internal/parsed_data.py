"""Read-only cache of already-parsed input time series and tables for loader reuse.

When `evaluate_v2(include_business_as_usual=True)` constructs its native business-as-usual
reference environment, and no equipment is autosized, the reference needs the exact inputs of
the evaluated episode window without re-reading or re-parsing the dataset files from disk.

Every array stored here is pristine (captured before robustness noise or in-place simulator
writes) and marked `writeable = False`. When building a reference environment from this source:
- Series that the simulator writes during an episode (`cooling_demand`, `heating_demand`,
  `indoor_dry_bulb_temperature`, cooling/heating set points, and the occupant set-point delta)
  are copied into fresh writable arrays.
- Series perturbed by `noise_std > 0` draw fresh indexed noise for the target window.
- All other series are shared as read-only NumPy slice views, just as `shared_series` shares
  calendar columns across buildings.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from citylearn.data import (
    CarbonIntensity,
    ChargerSimulation,
    DeferrableApplianceSimulation,
    EnergySimulation,
    EscalatorSimulation,
    LogisticRegressionOccupantParameters,
    Pricing,
    TimeSeriesData,
    Weather,
    add_robustness_noise,
)
from citylearn.internal.grid_availability import GridAvailabilityData, _COLUMN_PREFIX as _GRID_COLUMN_PREFIX
from citylearn.internal.shared_series import _fingerprint, _same_bits
from citylearn.utilities import IndexedNoise, NoiseUtils


ENERGY_INT32_COLUMNS = frozenset({
    'month',
    'hour',
    'day_type',
    'minutes',
    'seconds',
    'daylight_savings_status',
    'hvac_mode',
})

ENERGY_FLOAT32_COLUMNS = frozenset({
    'indoor_dry_bulb_temperature',
    'non_shiftable_load',
    'dhw_demand',
    'cooling_demand',
    'heating_demand',
    'solar_generation',
    'average_unmet_cooling_setpoint_difference',
    'indoor_relative_humidity',
    'occupant_count',
    'indoor_dry_bulb_temperature_cooling_set_point',
    'indoor_dry_bulb_temperature_heating_set_point',
    'power_outage',
    'comfort_band',
})

ENERGY_ALL_KNOWN_COLUMNS = ENERGY_INT32_COLUMNS | ENERGY_FLOAT32_COLUMNS

WEATHER_COLUMNS = (
    'outdoor_dry_bulb_temperature',
    'outdoor_relative_humidity',
    'diffuse_solar_irradiance',
    'direct_solar_irradiance',
    'outdoor_dry_bulb_temperature_predicted_1',
    'outdoor_dry_bulb_temperature_predicted_2',
    'outdoor_dry_bulb_temperature_predicted_3',
    'outdoor_relative_humidity_predicted_1',
    'outdoor_relative_humidity_predicted_2',
    'outdoor_relative_humidity_predicted_3',
    'diffuse_solar_irradiance_predicted_1',
    'diffuse_solar_irradiance_predicted_2',
    'diffuse_solar_irradiance_predicted_3',
    'direct_solar_irradiance_predicted_1',
    'direct_solar_irradiance_predicted_2',
    'direct_solar_irradiance_predicted_3',
)

PRICING_COLUMNS = (
    'electricity_pricing',
    'electricity_pricing_predicted_1',
    'electricity_pricing_predicted_2',
    'electricity_pricing_predicted_3',
)

CARBON_COLUMNS = ('carbon_intensity',)


def canonical_file_key(filepath: Union[str, os.PathLike]) -> str:
    """Normalized resolved path key for cache lookups."""

    return os.path.normcase(os.path.realpath(os.fspath(filepath)))


def _slice_1d(arr: np.ndarray, slc: slice) -> np.ndarray:
    """Return `arr` itself when `slc` spans its full length, preserving object identity."""

    if (
        slc.start in (None, 0)
        and (slc.stop is None or slc.stop >= arr.shape[0])
        and slc.step in (None, 1)
    ):
        return arr

    return arr[slc]


def _freeze_1d(
    values: Any,
    dtype: Any = None,
    *,
    pool: Optional[Dict[Tuple[Any, ...], List[np.ndarray]]] = None,
    pool_tag: str = '',
    own_buffer: bool = False,
) -> np.ndarray:
    """Return a 1-D read-only contiguous array, deduplicated through `pool` when numeric."""

    if (
        own_buffer
        and isinstance(values, np.ndarray)
        and (dtype is None or values.dtype == np.dtype(dtype))
        and values.ndim == 1
        and values.flags.c_contiguous
        and values.base is None
    ):
        arr = values
    else:
        arr = np.array(values, dtype=dtype, copy=True)

    arr.flags.writeable = False

    if pool is not None and arr.ndim == 1 and arr.dtype.kind in 'biuf' and arr.flags.c_contiguous:
        candidates = pool.setdefault((pool_tag, arr.dtype.str, arr.shape, _fingerprint(arr)), [])
        for candidate in candidates:
            if _same_bits(candidate, arr):
                return candidate
        candidates.append(arr)

    return arr


def _zero_and_clip_float32(
    raw: np.ndarray,
    *,
    lower: Optional[float] = None,
    upper: Optional[float] = None,
    pool: Optional[Dict[Tuple[Any, ...], List[np.ndarray]]] = None,
    pool_tag: str = '',
) -> np.ndarray:
    """Match `raw + 0.0f` (and optional unconditional `np.clip`) bit-for-bit, reusing `raw` when identical."""

    out = raw + np.float32(0.0)
    if lower is not None or upper is not None:
        out = np.clip(out, lower, upper).astype('float32', copy=False)

    if _same_bits(raw, out):
        return raw

    return _freeze_1d(out, dtype='float32', pool=pool, pool_tag=pool_tag, own_buffer=True)


@dataclass(frozen=True)
class WindowSpec:
    """Window metadata for a parsed time-series entry."""

    simulation_start: int
    simulation_end: int
    source_end: int
    expected_rows: int
    window_key: Optional[Tuple[Any, ...]]
    sliceable: bool
    padded_step_seconds: Optional[float] = None

    def resolve_slice(
        self,
        *,
        simulation_start: int,
        simulation_end: int,
        expected_rows: int,
        window_key: Optional[Tuple[Any, ...]],
        seconds_per_time_step: Optional[float] = None,
    ) -> Optional[slice]:
        """Return the local slice for a target window when guaranteed bit-identical, else None."""

        if (
            simulation_start == self.simulation_start
            and simulation_end == self.simulation_end
            and expected_rows == self.expected_rows
            and window_key == self.window_key
            and (
                simulation_end <= self.source_end
                or seconds_per_time_step is None
                or self.padded_step_seconds == float(seconds_per_time_step)
            )
        ):
            return slice(0, self.expected_rows)

        if not self.sliceable:
            return None

        if expected_rows != simulation_end - simulation_start + 1:
            return None

        if not (self.simulation_start <= simulation_start <= simulation_end <= self.simulation_end):
            return None

        # When terminal_observation_padding synthesized the final row at `simulation_end`, a 1-row
        # request starting past `source_end` has 0 source rows on disk and must not be served here,
        # and the synthesized calendar increment must match `seconds_per_time_step`.
        if simulation_start > self.source_end:
            return None

        if (
            simulation_end > self.source_end
            and seconds_per_time_step is not None
            and self.padded_step_seconds != float(seconds_per_time_step)
        ):
            return None

        rel_start = simulation_start - self.simulation_start
        rel_end = simulation_end - self.simulation_start + 1
        return slice(rel_start, rel_end)


@dataclass(frozen=True)
class ParsedEnergySeries:
    """Pristine read-only column arrays for `EnergySimulation`."""

    spec: WindowSpec
    raw_columns: Mapping[str, Optional[np.ndarray]]
    noiseless_indoor_temp: np.ndarray
    noiseless_solar: np.ndarray
    noiseless_humidity: Optional[np.ndarray]
    zeros_int32: np.ndarray
    zeros_float32: np.ndarray
    ones_int32: np.ndarray
    twos_float32: np.ndarray

    def build(
        self,
        slc: slice,
        *,
        seconds_per_time_step: Any,
        noise_std: Any,
        dataset_seconds_per_time_step: Any,
        noise_seed: Optional[int],
        noise_start_index: int,
        share_readonly: bool,
    ) -> EnergySimulation:
        """Construct an `EnergySimulation` preserving exact attribute order, dtypes and noise draws."""

        es = EnergySimulation.__new__(EnergySimulation)
        TimeSeriesData.__init__(es, start_time_step=None, end_time_step=None)
        es.noise_std = noise_std
        noisy = float(noise_std or 0.0) > 0.0
        noise_random_state = None if noise_seed is None else IndexedNoise(noise_seed, noise_start_index)

        raw = self.raw_columns
        # Calendar columns are always read-only and shared across buildings (#257).
        es.month = _slice_1d(raw['month'], slc)
        es.hour = _slice_1d(raw['hour'], slc)
        es.day_type = _slice_1d(raw['day_type'], slc)

        raw_temp = _slice_1d(raw['indoor_dry_bulb_temperature'], slc)
        if noisy or (float(noise_std or 0.0) != 0.0 and noise_random_state is not None):
            temp = np.clip(
                raw_temp + NoiseUtils.generate_gaussian_noise(raw_temp, es.noise_std, random_state=noise_random_state),
                -90,
                57,
            )
            es.indoor_dry_bulb_temperature = np.array(temp, dtype='float32', copy=True)
            temp_without_control = _freeze_1d(temp, dtype='float32')
        else:
            temp_slice = _slice_1d(self.noiseless_indoor_temp, slc)
            es.indoor_dry_bulb_temperature = temp_slice.copy()
            temp_without_control = temp_slice

        def _series(arr: np.ndarray, *, always_copy: bool = False) -> np.ndarray:
            sliced = _slice_1d(arr, slc)
            if always_copy or not share_readonly:
                return sliced.copy()
            return sliced

        non_shiftable_slice = _slice_1d(raw['non_shiftable_load'], slc)
        dhw_slice = _slice_1d(raw['dhw_demand'], slc)
        cooling_slice = _slice_1d(raw['cooling_demand'], slc)
        heating_slice = _slice_1d(raw['heating_demand'], slc)

        es.non_shiftable_load = non_shiftable_slice if share_readonly else non_shiftable_slice.copy()
        es.dhw_demand = dhw_slice if share_readonly else dhw_slice.copy()
        # Simulator thermal dynamics write cooling_demand and heating_demand in place.
        es.cooling_demand = cooling_slice.copy()
        es.heating_demand = heating_slice.copy()
        assert (es.cooling_demand * es.heating_demand).sum() == 0, (
            'Cooling and heating in the same time step is not allowed.'
        )

        raw_solar = _slice_1d(raw['solar_generation'], slc)
        if noisy or (float(noise_std or 0.0) != 0.0 and noise_random_state is not None):
            es.solar_generation = add_robustness_noise(
                raw_solar, es.noise_std, noise_random_state, lower=0.0, zero_stays_zero=True,
            )
        else:
            solar_slice = _slice_1d(self.noiseless_solar, slc)
            es.solar_generation = solar_slice if share_readonly else solar_slice.copy()

        es.minutes = None if raw['minutes'] is None else _slice_1d(raw['minutes'], slc)
        es.seconds = None if raw['seconds'] is None else _slice_1d(raw['seconds'], slc)

        time_delta_seconds = (
            None
            if dataset_seconds_per_time_step is not None
            else EnergySimulation.infer_time_step_seconds(
                es.hour, es.minutes, es.seconds, seconds_per_time_step=seconds_per_time_step,
            )
        )
        base_step_seconds = None
        if time_delta_seconds is not None:
            base_step_seconds = max(1, time_delta_seconds)
        if dataset_seconds_per_time_step is not None:
            if not np.isfinite(dataset_seconds_per_time_step) or dataset_seconds_per_time_step <= 0:
                raise ValueError('Invalid declared dataset interval')
            base_step_seconds = float(dataset_seconds_per_time_step)

        time_step_ratio = (
            seconds_per_time_step / base_step_seconds
            if seconds_per_time_step and base_step_seconds
            else None
        )
        es.dataset_seconds_per_time_step = base_step_seconds
        es.time_step_ratios = [time_step_ratio]
        es.noise_std = noise_std

        dst_src = self.zeros_int32 if raw['daylight_savings_status'] is None else raw['daylight_savings_status']
        es.daylight_savings_status = _slice_1d(dst_src, slc)

        unmet_src = (
            self.zeros_float32
            if raw['average_unmet_cooling_setpoint_difference'] is None
            else raw['average_unmet_cooling_setpoint_difference']
        )
        es.average_unmet_cooling_setpoint_difference = _series(unmet_src)

        if raw['indoor_relative_humidity'] is None:
            rh_slice = _slice_1d(self.zeros_float32, slc)
            es.indoor_relative_humidity = rh_slice if share_readonly else rh_slice.copy()
            rh_without_control = rh_slice
        elif noisy or (float(noise_std or 0.0) != 0.0 and noise_random_state is not None):
            raw_rh = _slice_1d(raw['indoor_relative_humidity'], slc)
            rh = np.clip(
                raw_rh + NoiseUtils.generate_gaussian_noise(raw_rh, es.noise_std, random_state=noise_random_state),
                0,
                100,
            )
            es.indoor_relative_humidity = np.array(rh, dtype='float32', copy=True)
            rh_without_control = _freeze_1d(rh, dtype='float32')
        else:
            rh_slice = _slice_1d(self.noiseless_humidity, slc)
            es.indoor_relative_humidity = rh_slice if share_readonly else rh_slice.copy()
            rh_without_control = rh_slice

        occ_src = self.zeros_float32 if raw['occupant_count'] is None else raw['occupant_count']
        es.occupant_count = _series(occ_src)

        cool_sp_src = (
            self.zeros_float32
            if raw['indoor_dry_bulb_temperature_cooling_set_point'] is None
            else raw['indoor_dry_bulb_temperature_cooling_set_point']
        )
        heat_sp_src = (
            self.zeros_float32
            if raw['indoor_dry_bulb_temperature_heating_set_point'] is None
            else raw['indoor_dry_bulb_temperature_heating_set_point']
        )
        cool_sp_slice = _slice_1d(cool_sp_src, slc)
        heat_sp_slice = _slice_1d(heat_sp_src, slc)
        # Occupant interaction models write cooling and heating set points in place.
        es.indoor_dry_bulb_temperature_cooling_set_point = cool_sp_slice.copy()
        es.indoor_dry_bulb_temperature_heating_set_point = heat_sp_slice.copy()

        outage_src = self.zeros_float32 if raw['power_outage'] is None else raw['power_outage']
        es.power_outage = _series(outage_src)

        band_src = self.twos_float32 if raw['comfort_band'] is None else raw['comfort_band']
        es.comfort_band = _series(band_src)

        # Uncontrolled reference series are never written in place; share read-only slices.
        es.indoor_dry_bulb_temperature_without_control = temp_without_control
        es.cooling_demand_without_control = cooling_slice
        es.heating_demand_without_control = heating_slice
        es.dhw_demand_without_control = dhw_slice
        es.non_shiftable_load_without_control = non_shiftable_slice
        es.indoor_relative_humidity_without_control = rh_without_control
        es.indoor_dry_bulb_temperature_cooling_set_point_without_control = cool_sp_slice
        es.indoor_dry_bulb_temperature_heating_set_point_without_control = heat_sp_slice

        hvac_src = self.ones_int32 if raw['hvac_mode'] is None else raw['hvac_mode']
        es.hvac_mode = _series(hvac_src)
        return es


@dataclass(frozen=True)
class ParsedSharedSeries:
    """Pristine read-only column arrays for `Weather`, `Pricing`, `CarbonIntensity`, or `GridAvailabilityData`."""

    constructor_name: str
    spec: WindowSpec
    raw_columns: Mapping[str, np.ndarray]
    noiseless_columns: Mapping[str, np.ndarray]

    def build(
        self,
        constructor: Any,
        slc: slice,
        *,
        noise_std: Any,
        noise_seed: Optional[int],
        noise_start_index: int,
        share_readonly: bool,
    ) -> Any:
        noisy = float(noise_std or 0.0) > 0.0
        if noisy or not share_readonly:
            kwargs = {name: _slice_1d(arr, slc) for name, arr in self.raw_columns.items()}
            return constructor(
                **kwargs,
                noise_std=noise_std,
                noise_seed=noise_seed,
                noise_start_index=noise_start_index,
            )

        name = self.constructor_name
        if name == 'Weather':
            instance = Weather.__new__(Weather)
            TimeSeriesData.__init__(instance, start_time_step=None, end_time_step=None)
            instance.noise_std = noise_std
            for col in WEATHER_COLUMNS:
                setattr(instance, col, _slice_1d(self.noiseless_columns[col], slc))
            return instance

        if name == 'Pricing':
            instance = Pricing.__new__(Pricing)
            TimeSeriesData.__init__(instance, start_time_step=None, end_time_step=None)
            instance.noise_std = noise_std
            for col in PRICING_COLUMNS:
                setattr(instance, col, _slice_1d(self.noiseless_columns[col], slc))
            return instance

        if name == 'CarbonIntensity':
            instance = CarbonIntensity.__new__(CarbonIntensity)
            instance.noise_std = noise_std
            TimeSeriesData.__init__(instance, start_time_step=None, end_time_step=None)
            instance.carbon_intensity = _slice_1d(self.noiseless_columns['carbon_intensity'], slc)
            return instance

        if name == 'GridAvailabilityData':
            instance = GridAvailabilityData.__new__(GridAvailabilityData)
            TimeSeriesData.__init__(instance, start_time_step=None, end_time_step=None)
            for col, arr in self.noiseless_columns.items():
                setattr(instance, _GRID_COLUMN_PREFIX + str(col), _slice_1d(arr, slc))
            return instance

        kwargs = {col: _slice_1d(arr, slc) for col, arr in self.raw_columns.items()}
        return constructor(
            **kwargs,
            noise_std=noise_std,
            noise_seed=noise_seed,
            noise_start_index=noise_start_index,
        )


@dataclass(frozen=True)
class ParsedChargerSeries:
    """Pristine read-only column arrays for `ChargerSimulation`."""

    spec: WindowSpec
    charger_state: np.ndarray
    ev_id: np.ndarray
    session_id: np.ndarray
    departure_time: np.ndarray
    estimated_arrival_time: np.ndarray
    raw_required_soc_departure: np.ndarray
    raw_estimated_soc_arrival: np.ndarray
    noiseless_required_soc_departure: np.ndarray
    noiseless_estimated_soc_arrival: np.ndarray
    current_soc: Optional[np.ndarray]

    def build(
        self,
        slc: slice,
        *,
        noise_std: Any,
        noise_seed: Optional[int],
        noise_start_index: int,
        time_step_offset: int,
        share_readonly: bool,
    ) -> ChargerSimulation:
        sim = ChargerSimulation.__new__(ChargerSimulation)
        TimeSeriesData.__init__(sim, start_time_step=None, end_time_step=None)
        sim.noise_std = noise_std
        noisy = bool(noise_std)

        def _arr(a: np.ndarray) -> np.ndarray:
            sliced = _slice_1d(a, slc)
            return sliced if share_readonly else sliced.copy()

        sim.electric_vehicle_charger_state = _arr(self.charger_state)
        sim.electric_vehicle_id = _arr(self.ev_id)
        sim.electric_vehicle_session_id = _arr(self.session_id)
        sim.electric_vehicle_departure_time = _arr(self.departure_time)
        sim.electric_vehicle_estimated_arrival_time = _arr(self.estimated_arrival_time)

        if noisy:
            noise_random_state = None if noise_seed is None else IndexedNoise(noise_seed, noise_start_index)
            sim.electric_vehicle_required_soc_departure = ChargerSimulation.normalize_soc_series(
                _slice_1d(self.raw_required_soc_departure, slc),
                default_soc_value=-0.1,
                noise_std=sim.noise_std,
                random_state=noise_random_state,
            )
            sim.electric_vehicle_estimated_soc_arrival = ChargerSimulation.normalize_soc_series(
                _slice_1d(self.raw_estimated_soc_arrival, slc),
                default_soc_value=-0.1,
                noise_std=sim.noise_std,
                random_state=noise_random_state,
            )
        else:
            sim.electric_vehicle_required_soc_departure = _arr(self.noiseless_required_soc_departure)
            sim.electric_vehicle_estimated_soc_arrival = _arr(self.noiseless_estimated_soc_arrival)

        setattr(sim, 'time_step_offset', int(time_step_offset or 0))
        if self.current_soc is not None:
            sim.electric_vehicle_current_soc = _arr(self.current_soc)

        return sim


@dataclass(frozen=True)
class ParsedEscalatorSeries:
    """Pristine read-only column arrays for `EscalatorSimulation`."""

    spec: WindowSpec
    columns: Tuple[Tuple[str, np.ndarray], ...]

    def build(self, slc: slice, *, source_label: str, share_readonly: bool) -> EscalatorSimulation:
        col_map = dict(self.columns)
        time_steps = _slice_1d(col_map['time_step'], slc)
        if not np.array_equal(time_steps.astype('int64', copy=False), np.arange(len(time_steps), dtype='int64')):
            raise ValueError(f'{source_label}.time_step must be contiguous and start at 0.')

        instance = EscalatorSimulation()
        for col, arr in self.columns:
            sliced = _slice_1d(arr, slc)
            setattr(instance, col, sliced if share_readonly else sliced.copy())
        return instance


@dataclass(frozen=True)
class ParsedOccupantParameters:
    """Pristine read-only column arrays for `LogisticRegressionOccupantParameters`."""

    a_increase: np.ndarray
    b_increase: np.ndarray
    a_decrease: np.ndarray
    b_decrease: np.ndarray
    zeros_without_control: np.ndarray

    def build(self, *, share_readonly: bool) -> LogisticRegressionOccupantParameters:
        params = LogisticRegressionOccupantParameters.__new__(LogisticRegressionOccupantParameters)
        TimeSeriesData.__init__(params, start_time_step=None, end_time_step=None)
        params.a_increase = self.a_increase if share_readonly else self.a_increase.copy()
        params.b_increase = self.b_increase if share_readonly else self.b_increase.copy()
        params.a_decrease = self.a_decrease if share_readonly else self.a_decrease.copy()
        params.b_decrease = self.b_decrease if share_readonly else self.b_decrease.copy()
        # Written in place by LogisticRegressionOccupantInteractionBuilding.update_set_points.
        params.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta = np.zeros(
            len(self.a_increase), dtype='float32',
        )
        params.occupant_interaction_indoor_dry_bulb_temperature_set_point_delta_without_control = (
            self.zeros_without_control if share_readonly else self.zeros_without_control.copy()
        )
        return params


@dataclass(frozen=True)
class RawTimeseriesTable:
    """Compact column store for short dynamic-topology member-window files."""

    start_row: int
    end_row: int
    exhausted: bool
    columns: Tuple[Tuple[str, np.ndarray, Any], ...]

    def slice_dataframe(self, start_time_step: Optional[int], end_time_step: Optional[int]) -> Optional[pd.DataFrame]:
        req_start = 0 if start_time_step is None else max(0, int(start_time_step))
        if req_start < self.start_row:
            return None

        if end_time_step is None:
            if not self.exhausted:
                return None
            req_end = self.end_row
        else:
            req_end = int(end_time_step)
            if req_end > self.end_row and not self.exhausted:
                return None
            req_end = min(req_end, self.end_row)

        local_start = req_start - self.start_row
        local_stop = max(local_start, req_end - self.start_row + 1)
        data = {}
        for name, arr, dtype in self.columns:
            sliced = arr[local_start:local_stop]
            data[name] = pd.Series(sliced, dtype=dtype, copy=False)
        return pd.DataFrame(data, copy=False)


class ParsedDataSource:
    """Read-only cache of parsed time-series arrays and dataset metadata."""

    def __init__(self):
        self.frozen: bool = False
        self._pool: Dict[Tuple[Any, ...], List[np.ndarray]] = {}
        self._defaults_cache: Dict[Tuple[str, int], np.ndarray] = {}
        self.energy_by_file: Dict[str, List[ParsedEnergySeries]] = {}
        self.shared_by_key: Dict[Tuple[str, str], List[ParsedSharedSeries]] = {}
        self.charger_by_file: Dict[str, List[ParsedChargerSeries]] = {}
        self.escalator_by_file: Dict[str, List[ParsedEscalatorSeries]] = {}
        self.deferrable_by_key: Dict[Tuple[str, str, str], DeferrableApplianceSimulation] = {}
        self.occupant_by_file: Dict[str, ParsedOccupantParameters] = {}
        self.calendar_by_file: Dict[str, Tuple[pd.DatetimeIndex, float]] = {}
        self.tariffs_by_file: Dict[str, np.ndarray] = {}
        self.demand_response_by_key: Dict[Tuple[Any, ...], Tuple[Any, ...]] = {}
        self.robustness_by_file: Dict[str, Tuple[Any, ...]] = {}
        self.raw_tables_by_key: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], List[RawTimeseriesTable]] = {}
        self.timeseries_row_counts: Dict[str, int] = {}
        self.dynamic_dataset_rows: Optional[int] = None

    def __deepcopy__(self, memo: Dict[int, Any]) -> "ParsedDataSource":
        # Every stored array and tuple is immutable; environments copied via deepcopy share it safely.
        return self

    def freeze(self) -> "ParsedDataSource":
        self.frozen = True
        return self

    def _default_array(self, kind: str, length: int) -> np.ndarray:
        key = (kind, int(length))
        cached = self._defaults_cache.get(key)
        if cached is not None:
            return cached

        if kind == 'zeros_int32':
            arr = np.zeros(length, dtype='int32')
        elif kind == 'ones_int32':
            arr = np.ones(length, dtype='int32')
        elif kind == 'zeros_float32':
            arr = np.zeros(length, dtype='float32')
        elif kind == 'twos_float32':
            arr = np.full(length, np.float32(EnergySimulation.DEFUALT_COMFORT_BAND), dtype='float32')
        else:
            raise KeyError(kind)

        arr.flags.writeable = False
        self._defaults_cache[key] = arr
        return arr

    # --- EnergySimulation ---

    def find_energy(
        self,
        filepath: Union[str, os.PathLike],
        *,
        simulation_start: int,
        simulation_end: int,
        expected_rows: int,
        window_key: Optional[Tuple[Any, ...]],
        seconds_per_time_step: Optional[float] = None,
    ) -> Optional[Tuple[ParsedEnergySeries, slice]]:
        entries = self.energy_by_file.get(canonical_file_key(filepath)) or ()
        for entry in entries:
            slc = entry.spec.resolve_slice(
                simulation_start=simulation_start,
                simulation_end=simulation_end,
                expected_rows=expected_rows,
                window_key=window_key,
                seconds_per_time_step=seconds_per_time_step,
            )
            if slc is not None:
                return entry, slc
        return None

    def store_energy(
        self,
        filepath: Union[str, os.PathLike],
        dataframe: pd.DataFrame,
        *,
        spec: WindowSpec,
    ) -> Optional[ParsedEnergySeries]:
        if self.frozen:
            return None

        columns = set(map(str, dataframe.columns))
        # Fall back to the standard constructor if unknown columns are present so TypeError surfaces identically.
        if not columns <= ENERGY_ALL_KNOWN_COLUMNS:
            return None
        required = {
            'month', 'hour', 'day_type', 'indoor_dry_bulb_temperature',
            'non_shiftable_load', 'dhw_demand', 'cooling_demand', 'heating_demand', 'solar_generation',
        }
        if not required <= columns:
            return None

        if 'hvac_mode' in columns:
            raw_hvac = dataframe['hvac_mode'].to_numpy(copy=False)
            unique = set(raw_hvac.tolist()) - {0, 1, 2, 3}
            if unique:
                return None

        raw_map: Dict[str, Optional[np.ndarray]] = {}
        for col in ENERGY_INT32_COLUMNS:
            if col in dataframe.columns:
                raw_map[col] = _freeze_1d(
                    dataframe[col].to_numpy(copy=False), dtype='int32', pool=self._pool, pool_tag=f'es:{col}',
                )
            else:
                raw_map[col] = None

        for col in ENERGY_FLOAT32_COLUMNS:
            if col in dataframe.columns:
                raw_map[col] = _freeze_1d(
                    dataframe[col].to_numpy(copy=False), dtype='float32', pool=self._pool, pool_tag=f'es:{col}',
                )
            else:
                raw_map[col] = None

        length = len(dataframe)
        noiseless_temp = _zero_and_clip_float32(
            raw_map['indoor_dry_bulb_temperature'],
            lower=-90.0,
            upper=57.0,
            pool=self._pool,
            pool_tag='es:temp_clean',
        )
        noiseless_solar = _zero_and_clip_float32(
            raw_map['solar_generation'],
            pool=self._pool,
            pool_tag='es:solar_clean',
        )
        noiseless_rh = (
            None
            if raw_map['indoor_relative_humidity'] is None
            else _zero_and_clip_float32(
                raw_map['indoor_relative_humidity'],
                lower=0.0,
                upper=100.0,
                pool=self._pool,
                pool_tag='es:rh_clean',
            )
        )
        entry = ParsedEnergySeries(
            spec=spec,
            raw_columns=raw_map,
            noiseless_indoor_temp=noiseless_temp,
            noiseless_solar=noiseless_solar,
            noiseless_humidity=noiseless_rh,
            zeros_int32=self._default_array('zeros_int32', length),
            zeros_float32=self._default_array('zeros_float32', length),
            ones_int32=self._default_array('ones_int32', length),
            twos_float32=self._default_array('twos_float32', length),
        )
        self.energy_by_file.setdefault(canonical_file_key(filepath), []).append(entry)
        return entry

    # --- Shared Time Series (Weather, Pricing, CarbonIntensity, GridAvailabilityData) ---

    def find_shared(
        self,
        constructor_name: str,
        filepath: Union[str, os.PathLike],
        *,
        simulation_start: int,
        simulation_end: int,
        expected_rows: int,
        window_key: Optional[Tuple[Any, ...]],
        seconds_per_time_step: Optional[float] = None,
    ) -> Optional[Tuple[ParsedSharedSeries, slice]]:
        entries = self.shared_by_key.get((constructor_name, canonical_file_key(filepath))) or ()
        for entry in entries:
            slc = entry.spec.resolve_slice(
                simulation_start=simulation_start,
                simulation_end=simulation_end,
                expected_rows=expected_rows,
                window_key=window_key,
                seconds_per_time_step=seconds_per_time_step,
            )
            if slc is not None:
                return entry, slc
        return None

    def store_shared(
        self,
        constructor_name: str,
        filepath: Union[str, os.PathLike],
        dataframe: pd.DataFrame,
        *,
        spec: WindowSpec,
    ) -> Optional[ParsedSharedSeries]:
        if self.frozen:
            return None

        col_names = tuple(map(str, dataframe.columns))
        raw_map: Dict[str, np.ndarray] = {}
        clean_map: Dict[str, np.ndarray] = {}

        if constructor_name in ('Weather', 'Pricing', 'CarbonIntensity'):
            expected = (
                WEATHER_COLUMNS if constructor_name == 'Weather'
                else PRICING_COLUMNS if constructor_name == 'Pricing'
                else CARBON_COLUMNS
            )
            if set(col_names) != set(expected):
                return None
            for col in expected:
                raw_arr = _freeze_1d(
                    dataframe[col].to_numpy(copy=False),
                    dtype='float32',
                    pool=self._pool,
                    pool_tag=f'{constructor_name}:{col}',
                )
                raw_map[col] = raw_arr
                clean_map[col] = _zero_and_clip_float32(
                    raw_arr, pool=self._pool, pool_tag=f'{constructor_name}:{col}:clean',
                )
        elif constructor_name == 'GridAvailabilityData':
            for col in col_names:
                values = dataframe[col].to_numpy(copy=False)
                try:
                    numeric = _freeze_1d(values, dtype='float64', pool=self._pool, pool_tag=f'grid:{col}')
                    raw_map[col] = numeric
                    clean_map[col] = numeric
                except (TypeError, ValueError):
                    frozen = np.array(values, copy=True)
                    frozen.flags.writeable = False
                    raw_map[col] = frozen
                    clean_map[col] = frozen
        else:
            return None

        entry = ParsedSharedSeries(
            constructor_name=constructor_name,
            spec=spec,
            raw_columns=raw_map,
            noiseless_columns=clean_map,
        )
        self.shared_by_key.setdefault((constructor_name, canonical_file_key(filepath)), []).append(entry)
        return entry

    # --- ChargerSimulation ---

    def find_charger(
        self,
        filepath: Union[str, os.PathLike],
        *,
        simulation_start: int,
        simulation_end: int,
        expected_rows: int,
        window_key: Optional[Tuple[Any, ...]],
        seconds_per_time_step: Optional[float] = None,
    ) -> Optional[Tuple[ParsedChargerSeries, slice]]:
        entries = self.charger_by_file.get(canonical_file_key(filepath)) or ()
        for entry in entries:
            slc = entry.spec.resolve_slice(
                simulation_start=simulation_start,
                simulation_end=simulation_end,
                expected_rows=expected_rows,
                window_key=window_key,
                seconds_per_time_step=seconds_per_time_step,
            )
            if slc is not None:
                return entry, slc
        return None

    def store_charger(
        self,
        filepath: Union[str, os.PathLike],
        dataframe: pd.DataFrame,
        *,
        spec: WindowSpec,
    ) -> Optional[ParsedChargerSeries]:
        if self.frozen:
            return None

        charger_state_series = pd.to_numeric(
            pd.Series(dataframe['electric_vehicle_charger_state'].to_numpy(copy=False), dtype=object),
            errors='coerce',
        )
        charger_state_series = charger_state_series.where(
            (charger_state_series >= 0) & (charger_state_series == np.floor(charger_state_series))
        )
        charger_state = _freeze_1d(
            charger_state_series.to_numpy(dtype='float32'),
            dtype='float32',
            pool=self._pool,
            pool_tag='charger:state',
            own_buffer=True,
        )

        ev_id = _freeze_1d(dataframe['electric_vehicle_id'].to_numpy(copy=False), dtype=object)
        if 'electric_vehicle_session_id' in dataframe.columns:
            session_id = _freeze_1d(dataframe['electric_vehicle_session_id'].to_numpy(copy=False), dtype=object)
        else:
            session_id = _freeze_1d([''] * len(ev_id), dtype=object)

        dep_arr = np.array(dataframe['electric_vehicle_departure_time'].to_numpy(copy=False), dtype='float32')
        departure_time = _freeze_1d(
            np.where(np.isnan(dep_arr), -1, dep_arr).astype('int32'),
            dtype='int32',
            pool=self._pool,
            pool_tag='charger:dep',
            own_buffer=True,
        )

        arr_arr = np.array(dataframe['electric_vehicle_estimated_arrival_time'].to_numpy(copy=False), dtype='float32')
        arrival_time = _freeze_1d(
            np.where(np.isnan(arr_arr), -1, arr_arr).astype('int32'),
            dtype='int32',
            pool=self._pool,
            pool_tag='charger:arr',
            own_buffer=True,
        )

        raw_req_soc = _freeze_1d(
            dataframe['electric_vehicle_required_soc_departure'].to_numpy(copy=False),
            dtype='float32',
            pool=self._pool,
            pool_tag='charger:req_soc_raw',
        )
        raw_est_soc = _freeze_1d(
            dataframe['electric_vehicle_estimated_soc_arrival'].to_numpy(copy=False),
            dtype='float32',
            pool=self._pool,
            pool_tag='charger:est_soc_raw',
        )
        clean_req_soc = _freeze_1d(
            ChargerSimulation.normalize_soc_series(raw_req_soc, default_soc_value=-0.1, noise_std=0.0),
            dtype='float32',
            pool=self._pool,
            pool_tag='charger:req_soc_clean',
            own_buffer=True,
        )
        clean_est_soc = _freeze_1d(
            ChargerSimulation.normalize_soc_series(raw_est_soc, default_soc_value=-0.1, noise_std=0.0),
            dtype='float32',
            pool=self._pool,
            pool_tag='charger:est_soc_clean',
            own_buffer=True,
        )

        current_soc = None
        if 'electric_vehicle_current_soc' in dataframe.columns:
            current_soc_raw = pd.to_numeric(
                dataframe['electric_vehicle_current_soc'], errors='coerce',
            ).to_numpy(dtype='float32')
            current_soc = _freeze_1d(
                ChargerSimulation.normalize_soc_series(current_soc_raw, default_soc_value=-0.1, noise_std=0.0),
                dtype='float32',
                pool=self._pool,
                pool_tag='charger:cur_soc',
                own_buffer=True,
            )

        entry = ParsedChargerSeries(
            spec=spec,
            charger_state=charger_state,
            ev_id=ev_id,
            session_id=session_id,
            departure_time=departure_time,
            estimated_arrival_time=arrival_time,
            raw_required_soc_departure=raw_req_soc,
            raw_estimated_soc_arrival=raw_est_soc,
            noiseless_required_soc_departure=clean_req_soc,
            noiseless_estimated_soc_arrival=clean_est_soc,
            current_soc=current_soc,
        )
        self.charger_by_file.setdefault(canonical_file_key(filepath), []).append(entry)
        return entry

    # --- EscalatorSimulation ---

    def find_escalator(
        self,
        filepath: Union[str, os.PathLike],
        *,
        simulation_start: int,
        simulation_end: int,
        expected_rows: int,
        window_key: Optional[Tuple[Any, ...]],
        seconds_per_time_step: Optional[float] = None,
    ) -> Optional[Tuple[ParsedEscalatorSeries, slice]]:
        entries = self.escalator_by_file.get(canonical_file_key(filepath)) or ()
        for entry in entries:
            slc = entry.spec.resolve_slice(
                simulation_start=simulation_start,
                simulation_end=simulation_end,
                expected_rows=expected_rows,
                window_key=window_key,
                seconds_per_time_step=seconds_per_time_step,
            )
            if slc is not None:
                return entry, slc
        return None

    def store_escalator(
        self,
        filepath: Union[str, os.PathLike],
        simulation: EscalatorSimulation,
        column_order: Sequence[str],
        *,
        spec: WindowSpec,
    ) -> Optional[ParsedEscalatorSeries]:
        if self.frozen:
            return None

        cols = []
        for col in column_order:
            arr = simulation.__dict__[f'_{col}']
            frozen = _freeze_1d(arr, pool=self._pool, pool_tag=f'escalator:{col}')
            cols.append((str(col), frozen))
        entry = ParsedEscalatorSeries(spec=spec, columns=tuple(cols))
        self.escalator_by_file.setdefault(canonical_file_key(filepath), []).append(entry)
        return entry

    # --- DeferrableApplianceSimulation ---

    def find_deferrable(
        self,
        profiles_filepath: Union[str, os.PathLike],
        schedule_filepath: Union[str, os.PathLike],
        source_label: str,
    ) -> Optional[DeferrableApplianceSimulation]:
        key = (
            canonical_file_key(profiles_filepath),
            canonical_file_key(schedule_filepath),
            str(source_label),
        )
        cached = self.deferrable_by_key.get(key)
        if cached is None:
            return None

        # Return a lightweight wrapper sharing the read-only cycle profiles and schedule rows,
        # skipping CSV/Parquet parsing, literal_eval and O(N) non-overlap re-validation.
        clone = DeferrableApplianceSimulation.__new__(DeferrableApplianceSimulation)
        clone.source_label = cached.source_label
        clone.cycle_profiles = dict(cached.cycle_profiles)
        clone.flexibility_schedule = list(cached.flexibility_schedule)
        return clone

    def store_deferrable(
        self,
        profiles_filepath: Union[str, os.PathLike],
        schedule_filepath: Union[str, os.PathLike],
        source_label: str,
        simulation: DeferrableApplianceSimulation,
    ) -> None:
        if self.frozen:
            return

        for profile in simulation.cycle_profiles.values():
            load_profile = profile.get('load_profile')
            if isinstance(load_profile, np.ndarray):
                load_profile.flags.writeable = False

        key = (
            canonical_file_key(profiles_filepath),
            canonical_file_key(schedule_filepath),
            str(source_label),
        )
        self.deferrable_by_key[key] = simulation

    # --- Occupant Parameters ---

    def find_occupant_parameters(
        self, filepath: Union[str, os.PathLike], *, share_readonly: bool,
    ) -> Optional[LogisticRegressionOccupantParameters]:
        entry = self.occupant_by_file.get(canonical_file_key(filepath))
        if entry is None:
            return None
        return entry.build(share_readonly=share_readonly)

    def store_occupant_parameters(
        self, filepath: Union[str, os.PathLike], dataframe: pd.DataFrame,
    ) -> ParsedOccupantParameters:
        a_inc = _freeze_1d(dataframe['a_increase'].to_numpy(copy=False), dtype='float32', pool=self._pool, pool_tag='occ:ai')
        b_inc = _freeze_1d(dataframe['b_increase'].to_numpy(copy=False), dtype='float32', pool=self._pool, pool_tag='occ:bi')
        a_dec = _freeze_1d(dataframe['a_decrease'].to_numpy(copy=False), dtype='float32', pool=self._pool, pool_tag='occ:ad')
        b_dec = _freeze_1d(dataframe['b_decrease'].to_numpy(copy=False), dtype='float32', pool=self._pool, pool_tag='occ:bd')
        zeros = self._default_array('zeros_float32', len(a_inc))
        entry = ParsedOccupantParameters(
            a_increase=a_inc,
            b_increase=b_inc,
            a_decrease=a_dec,
            b_decrease=b_dec,
            zeros_without_control=zeros,
        )
        if not self.frozen:
            self.occupant_by_file[canonical_file_key(filepath)] = entry
        return entry

    # --- Short Dynamic Member-Window Raw Tables ---

    @staticmethod
    def _dtypes_key(csv_dtypes: Optional[Mapping[str, Any]]) -> Tuple[Tuple[str, str], ...]:
        if not csv_dtypes:
            return ()
        return tuple(sorted((str(k), str(v)) for k, v in csv_dtypes.items()))

    def find_raw_table(
        self,
        filepath: Union[str, os.PathLike],
        *,
        start_time_step: Optional[int],
        end_time_step: Optional[int],
        csv_dtypes: Optional[Mapping[str, Any]],
    ) -> Optional[pd.DataFrame]:
        key = (canonical_file_key(filepath), self._dtypes_key(csv_dtypes))
        for table in self.raw_tables_by_key.get(key) or ():
            frame = table.slice_dataframe(start_time_step, end_time_step)
            if frame is not None:
                return frame
        return None

    def store_raw_table(
        self,
        filepath: Union[str, os.PathLike],
        dataframe: pd.DataFrame,
        *,
        start_row: int,
        requested_end_row: Optional[int],
        csv_dtypes: Optional[Mapping[str, Any]],
    ) -> None:
        if self.frozen:
            return

        nrows = len(dataframe)
        end_row = int(start_row) + nrows - 1
        exhausted = requested_end_row is None or nrows < (int(requested_end_row) - int(start_row) + 1)
        cols = []
        for col in dataframe.columns:
            series = dataframe[col]
            arr = np.array(series.to_numpy(copy=False), copy=True)
            arr.flags.writeable = False
            cols.append((str(col), arr, series.dtype))
        key = (canonical_file_key(filepath), self._dtypes_key(csv_dtypes))
        self.raw_tables_by_key.setdefault(key, []).append(
            RawTimeseriesTable(
                start_row=int(start_row),
                end_row=end_row,
                exhausted=exhausted,
                columns=tuple(cols),
            )
        )
