"""Prepare building time-series inputs using the loader's cache and windows."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from citylearn.data import CarbonIntensity, EnergySimulation, Pricing, Weather
from citylearn.internal.shared_series import share_identical_series

if TYPE_CHECKING:
    from citylearn.internal.loading import CityLearnLoadingService


@dataclass(frozen=True)
class BuildingInputs:
    energy_simulation: EnergySimulation
    weather: Weather
    carbon_intensity: CarbonIntensity
    pricing: Pricing
    time_step_ratio: float


def check_time_step_ratio(mode, time_step_ratio, *, source, dataset_seconds_per_time_step, seconds_per_time_step):
    """Refuse a control step that differs from the dataset step unless `mode` is `'compress'`.

    CityLearn reads one data row per control step and does not resample, so a ratio other than 1 would
    run the calendar, prices and schedules at the wrong rate.
    """

    if mode == 'compress' or time_step_ratio is None:
        return

    ratio = float(time_step_ratio)

    if np.isfinite(ratio) and abs(ratio - 1.0) <= 1.0e-9:
        return

    dataset_seconds = 'unknown' if dataset_seconds_per_time_step is None else f'{float(dataset_seconds_per_time_step):g}'
    raise ValueError(
        f'seconds_per_time_step={float(seconds_per_time_step):g} differs from the dataset step of '
        f'{dataset_seconds} s inferred for {source} (time_step_ratio={ratio:g}). '
        'CityLearn reads one data row per control step and does not resample, so this run would advance the '
        'calendar, prices and EV schedules one row per control step while scaling energies by the ratio. Set '
        'seconds_per_time_step to the dataset step, resample the dataset, or pass time_step_ratio_mode='
        "'compress' to keep the CityLearn 3.6.0 behaviour."
    )


def load_building_inputs(loader: "CityLearnLoadingService", building_name, schema,
                         expected_rows, member_window) -> BuildingInputs:
    building_schema = schema['buildings'][building_name]
    seconds_per_time_step = schema['seconds_per_time_step']
    noise_std = building_schema.get('noise_std', 0.0)
    energy_simulation_filepath = os.path.join(schema['root_directory'], building_schema['energy_simulation'])
    sim_start = int(schema['simulation_start_time_step'])
    sim_end = int(schema['simulation_end_time_step'])
    window_key = tuple(member_window) if (loader._dynamic_mode and member_window is not None) else None
    parsed_data = getattr(loader, '_parsed_data', None)
    share_readonly = bool(getattr(loader, '_share_readonly_series', False))
    energy_simulation = None

    if parsed_data is not None:
        hit = parsed_data.find_energy(
            energy_simulation_filepath,
            simulation_start=sim_start,
            simulation_end=sim_end,
            expected_rows=int(expected_rows),
            window_key=window_key,
            seconds_per_time_step=float(seconds_per_time_step),
        )
        if hit is not None:
            entry, slc = hit
            energy_simulation = entry.build(
                slc,
                seconds_per_time_step=seconds_per_time_step,
                noise_std=noise_std,
                dataset_seconds_per_time_step=loader.env._time_axis.seconds,
                noise_seed=loader._noise_seed(schema, 'energy:'+building_name),
                noise_start_index=sim_start,
                share_readonly=share_readonly,
            )

    if energy_simulation is None:
        energy_df = loader._read_member_timeseries(
            schema,
            energy_simulation_filepath,
            expected_rows=expected_rows,
            window=member_window,
            source_label=f'buildings.{building_name}.energy_simulation',
        )
        energy_simulation = EnergySimulation(
            **loader._dataframe_to_constructor_kwargs(energy_df),
            seconds_per_time_step=seconds_per_time_step,
            noise_std=noise_std,
            dataset_seconds_per_time_step=loader.env._time_axis.seconds,
            noise_seed=loader._noise_seed(schema, 'energy:'+building_name),
            noise_start_index=sim_start,
        )
        loader._set_time_step_offset(energy_simulation, sim_start)
        share_identical_series(loader._shared_timeseries_cache, energy_simulation)
        if parsed_data is not None and not parsed_data.frozen and loader._last_read_window_spec is not None:
            parsed_data.capture_energy(
                energy_simulation_filepath,
                energy_df,
                energy_simulation,
                spec=loader._last_read_window_spec,
                noise_std=noise_std,
            )
    else:
        loader._set_time_step_offset(energy_simulation, sim_start)
        share_identical_series(loader._shared_timeseries_cache, energy_simulation)
    ratios = getattr(energy_simulation, 'time_step_ratios', None) or []
    time_step_ratio = ratios[-1] if len(ratios) > 0 else 1.0
    check_time_step_ratio(
        getattr(loader.env, 'time_step_ratio_mode', 'reject'),
        time_step_ratio,
        source=energy_simulation_filepath,
        dataset_seconds_per_time_step=getattr(energy_simulation, 'dataset_seconds_per_time_step', None),
        seconds_per_time_step=seconds_per_time_step,
    )
    loader._print_time_step_conversion_notice(
        building_name=building_name,
        source=energy_simulation_filepath,
        dataset_seconds_per_time_step=getattr(energy_simulation, 'dataset_seconds_per_time_step', None),
        seconds_per_time_step=seconds_per_time_step,
        time_step_ratio=time_step_ratio,
    )
    weather_filepath = os.path.join(schema['root_directory'], building_schema['weather'])
    weather = loader._load_shared_timeseries(
        Weather,
        schema=schema,
        filepath=weather_filepath,
        expected_rows=expected_rows,
        window=member_window,
        source_label=f'buildings.{building_name}.weather',
        noise_std=noise_std,
    )

    if building_schema.get('carbon_intensity', None) is not None:
        carbon_intensity_filepath = os.path.join(schema['root_directory'], building_schema['carbon_intensity'])
        carbon_intensity = loader._load_shared_timeseries(
            CarbonIntensity,
            schema=schema,
            filepath=carbon_intensity_filepath,
            expected_rows=expected_rows,
            window=member_window,
            source_label=f'buildings.{building_name}.carbon_intensity',
            noise_std=noise_std,
        )
    else:
        carbon_intensity = CarbonIntensity(np.zeros(energy_simulation.hour.shape[0], dtype='float32'), noise_std=noise_std, noise_seed=loader._noise_seed(schema,'carbon:'+building_name), noise_start_index=schema['simulation_start_time_step'])
        loader._set_time_step_offset(carbon_intensity, schema['simulation_start_time_step'])

    if building_schema.get('pricing', None) is not None:
        pricing_filepath = os.path.join(schema['root_directory'], building_schema['pricing'])
        pricing = loader._load_shared_timeseries(
            Pricing,
            schema=schema,
            filepath=pricing_filepath,
            expected_rows=expected_rows,
            window=member_window,
            source_label=f'buildings.{building_name}.pricing',
            noise_std=noise_std,
        )
    else:
        pricing = Pricing(
            np.zeros(energy_simulation.hour.shape[0], dtype='float32'),
            np.zeros(energy_simulation.hour.shape[0], dtype='float32'),
            np.zeros(energy_simulation.hour.shape[0], dtype='float32'),
            np.zeros(energy_simulation.hour.shape[0], dtype='float32'),
            noise_std=noise_std,
            noise_seed=loader._noise_seed(schema,'pricing:'+building_name),
            noise_start_index=schema['simulation_start_time_step'],
        )
        loader._set_time_step_offset(pricing, schema['simulation_start_time_step'])
    return BuildingInputs(energy_simulation, weather, carbon_intensity, pricing,
                          time_step_ratio)
