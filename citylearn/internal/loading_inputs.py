"""Prepare building time-series inputs using the loader's cache and windows."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from citylearn.data import CarbonIntensity, EnergySimulation, Pricing, Weather

if TYPE_CHECKING:
    from citylearn.internal.loading import CityLearnLoadingService


@dataclass(frozen=True)
class BuildingInputs:
    energy_simulation: EnergySimulation
    weather: Weather
    carbon_intensity: CarbonIntensity
    pricing: Pricing
    time_step_ratio: float


def load_building_inputs(loader: "CityLearnLoadingService", building_name, schema,
                         expected_rows, member_window) -> BuildingInputs:
    building_schema = schema['buildings'][building_name]
    seconds_per_time_step = schema['seconds_per_time_step']
    noise_std = building_schema.get('noise_std', 0.0)
    energy_simulation_filepath = os.path.join(schema['root_directory'], building_schema['energy_simulation'])
    energy_simulation = loader._read_simulation_dataframe(schema, energy_simulation_filepath)
    energy_simulation = loader._align_dynamic_timeseries_dataframe(
        energy_simulation,
        expected_rows=expected_rows,
        window=member_window,
        source_label=f'buildings.{building_name}.energy_simulation',
    )
    energy_simulation = EnergySimulation(
        **loader._dataframe_to_constructor_kwargs(energy_simulation),
        seconds_per_time_step=seconds_per_time_step,
        noise_std=noise_std,
        dataset_seconds_per_time_step=loader.env._time_axis.seconds,
        noise_seed=loader._noise_seed(schema, 'energy:'+building_name),
        noise_start_index=schema['simulation_start_time_step'],
    )
    loader._set_time_step_offset(energy_simulation, schema['simulation_start_time_step'])
    ratios = getattr(energy_simulation, 'time_step_ratios', None) or []
    time_step_ratio = ratios[-1] if len(ratios) > 0 else 1.0
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
