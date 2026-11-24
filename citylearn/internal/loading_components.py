"""Construct building components and apply explicit equipment configuration.

Optional absence and existing autosize/seed semantics are preserved. Constructor
lookup fails with a schema path; actual constructor failures propagate without
falling back to a different class or equipment definition.
"""
from __future__ import annotations

import difflib
import hashlib
import importlib
import inspect
import os
import warnings
from typing import TYPE_CHECKING

import pandas as pd

from citylearn import random_streams
from citylearn.data import ChargerSimulation, LogisticRegressionOccupantParameters
from citylearn.energy_model import PV, Battery
from citylearn.internal.physics_version import physics_version_of, resolve_physics_version
from citylearn.utilities import parse_bool

if TYPE_CHECKING:
    from citylearn.internal.loading import CityLearnLoadingService


def component_constructor(type_name, path):
    """Resolve a configured callable, keeping import failures as explicit causes."""
    if not isinstance(type_name, str) or '.' not in type_name:
        raise ValueError(f'{path}: expected a fully qualified component type, got {type_name!r}.')
    module_name, name = type_name.rsplit('.', 1)
    if not module_name or not name:
        raise ValueError(f'{path}: expected a fully qualified component type, got {type_name!r}.')
    try:
        constructor = getattr(importlib.import_module(module_name), name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f'{path}: cannot load component type {type_name!r}: {exc}') from exc
    if not callable(constructor):
        raise ValueError(f'{path}: component type {type_name!r} is not callable.')
    return constructor


def base_building_options(building_schema):
    building_kwargs = {}
    if building_schema.get('charging_constraints') is not None:
        building_kwargs['charging_constraints'] = building_schema['charging_constraints']
    if building_schema.get('electrical_service') is not None:
        building_kwargs['electrical_service'] = building_schema['electrical_service']
    if building_schema.get('equity_group') is not None:
        building_kwargs['equity_group'] = building_schema.get('equity_group')
    electrical_storage_attributes = (building_schema.get('electrical_storage') or {}).get('attributes', {}) or {}
    if electrical_storage_attributes.get('phase_connection') is not None:
        building_kwargs['electrical_storage_phase_connection'] = electrical_storage_attributes.get('phase_connection')
    return building_kwargs


def accepts_keyword(constructor, name):
    """Whether `name` is an explicit `__init__` parameter of `constructor` or one of its base classes."""
    return any(
        name in inspect.signature(cls.__init__).parameters
        for cls in getattr(constructor, '__mro__', ())
        if '__init__' in vars(cls)
    )


def add_model_options(building_kwargs, building_name, building_schema, schema, episode_tracker, constructor):
    if building_schema.get('dynamics', None) is not None:
        dynamics_type = building_schema['dynamics']['type']
        dynamics_constructor = component_constructor(dynamics_type, f'buildings.{building_name}.dynamics.type')
        attributes = building_schema['dynamics'].get('attributes', {})
        attributes['filepath'] = os.path.join(schema['root_directory'], attributes['filename'])
        _ = attributes.pop('filename')
        building_kwargs['dynamics'] = dynamics_constructor(**attributes)
    else:
        building_kwargs['dynamics'] = None

    if building_schema.get('occupant', None) is not None:
        building_occupant = building_schema['occupant']
        occupant_type = building_occupant['type']
        occupant_constructor = component_constructor(occupant_type, f'buildings.{building_name}.occupant.type')
        attributes: dict = building_occupant.get('attributes', {})
        parameters_filepath = os.path.join(schema['root_directory'], building_occupant['parameters_filename'])
        parameters = pd.read_csv(parameters_filepath)
        attributes['parameters'] = LogisticRegressionOccupantParameters(**parameters.to_dict('list'))
        attributes['episode_tracker'] = episode_tracker
        attributes['random_seed'] = schema['random_seed']
        attributes['random_stream_version'] = schema['random_stream_version']
        attributes['random_stream_key'] = ('building', building_name, 'occupant')

        for key in ['increase', 'decrease']:
            attributes[f'setpoint_{key}_model_filepath'] = os.path.join(schema['root_directory'], attributes[f'setpoint_{key}_model_filename'])
            _ = attributes.pop(f'setpoint_{key}_model_filename')

        building_kwargs['occupant'] = occupant_constructor(**attributes)
    else:
        building_kwargs['occupant'] = None

    # Only building types with an occupant set-point hold take this option; others never received it.
    hold_time_steps = building_schema.get('set_point_hold_time_steps')
    if hold_time_steps is not None and accepts_keyword(constructor, 'set_point_hold_time_steps'):
        building_kwargs['set_point_hold_time_steps'] = hold_time_steps

    # Occupant set-point range (physics version 2 and later, CityLearn #352).
    set_point_limits = building_schema.get('set_point_limits')
    if set_point_limits is not None and accepts_keyword(constructor, 'set_point_limits'):
        building_kwargs['set_point_limits'] = set_point_limits


def outage_options(index, building_name, building_schema, kwargs):
    building_schema_power_outage = building_schema.get('power_outage', {})
    simulate_power_outage = kwargs.get('simulate_power_outage')
    simulate_power_outage = building_schema_power_outage.get('simulate_power_outage') if simulate_power_outage is None else simulate_power_outage
    simulate_power_outage = simulate_power_outage[index] if isinstance(simulate_power_outage, list) else simulate_power_outage
    stochastic_power_outage = building_schema_power_outage.get('stochastic_power_outage')

    if building_schema_power_outage.get('stochastic_power_outage_model', None) is not None:
        stochastic_power_outage_model_type = building_schema_power_outage['stochastic_power_outage_model']['type']
        stochastic_power_outage_model_constructor = component_constructor(
            stochastic_power_outage_model_type, f'buildings.{building_name}.power_outage.stochastic_power_outage_model.type')
        attributes = building_schema_power_outage.get('stochastic_power_outage_model', {}).get('attributes', {})
        stochastic_power_outage_model = stochastic_power_outage_model_constructor(**attributes)
    else:
        stochastic_power_outage_model = None
    return dict(simulate_power_outage=simulate_power_outage,
                stochastic_power_outage=stochastic_power_outage,
                stochastic_power_outage_model=stochastic_power_outage_model,
                outage_vehicle_to_building=building_schema_power_outage.get('vehicle_to_building'))


def load_chargers(loader: "CityLearnLoadingService", building_name, building_schema,
                  schema, episode_tracker, expected_rows, time_step_ratio):
    chargers_list = []
    if building_schema.get('chargers', None) is not None:
        for charger_name, charger_config in building_schema['chargers'].items():
            noise_std = charger_config.get('noise_std', 0.0)

            charger_simulation_filepath = os.path.join(schema['root_directory'], charger_config['charger_simulation'])
            # CSV has no column types. Preserve textual IDs such as "01" and "1" before inference.
            charger_window = loader._dynamic_charger_windows.get((building_name, charger_name))
            charger_simulation_file = loader._read_member_timeseries(
                schema,
                charger_simulation_filepath,
                expected_rows=expected_rows,
                window=charger_window,
                source_label=f'buildings.{building_name}.chargers.{charger_name}.charger_simulation',
                csv_dtypes={'electric_vehicle_session_id': object},
            )

            # Keep the constructor contract stable when charger datasets add
            # optional telemetry columns.  Passing the complete dataframe
            # positionally would silently reinterpret a seventh column as
            # ``start_time_step``.
            charger_columns = (
                'electric_vehicle_charger_state',
                'electric_vehicle_id',
                'electric_vehicle_departure_time',
                'electric_vehicle_required_soc_departure',
                'electric_vehicle_estimated_arrival_time',
                'electric_vehicle_estimated_soc_arrival',
            )
            missing_charger_columns = [
                column for column in charger_columns
                if column not in charger_simulation_file.columns
            ]
            if missing_charger_columns:
                raise ValueError(
                    f"Charger simulation '{charger_simulation_filepath}' is missing "
                    f"required columns: {missing_charger_columns}."
                )
            check_charger_keys(charger_config, f'buildings.{building_name}.chargers.{charger_name}')
            # One unit per SOC column (#368). The loader reads only the simulation window, so the unit
            # is decided from the whole column of the file unless the schema declares it. Physics
            # version 1 keeps the old value-by-value rule.
            soc_unit = ChargerSimulation._resolve_soc_unit(
                charger_config.get('soc_unit'), path=f'buildings.{building_name}.chargers.{charger_name}.soc_unit',
            )
            if soc_unit is not None:
                soc_unit = {column: soc_unit for column in ChargerSimulation._SOC_COLUMNS}
            elif resolve_physics_version(schema.get('physics_version')) < 2:
                soc_unit = {column: 'per_value' for column in ChargerSimulation._SOC_COLUMNS}
            else:
                soc_unit = loader._charger_soc_units(charger_simulation_filepath)
            charger_simulation = ChargerSimulation(
                *(charger_simulation_file[column].to_numpy() for column in charger_columns),
                electric_vehicle_session_id=(
                    charger_simulation_file['electric_vehicle_session_id'].to_numpy()
                    if 'electric_vehicle_session_id' in charger_simulation_file.columns
                    else None
                ),
                noise_std=noise_std,
                noise_seed=loader._noise_seed(schema, 'charger:'+building_name+':'+charger_name),
                noise_start_index=schema['simulation_start_time_step'],
                soc_unit=soc_unit,
            )
            loader._set_time_step_offset(charger_simulation, schema['simulation_start_time_step'])
            if 'electric_vehicle_current_soc' in charger_simulation_file.columns:
                current_soc_raw = pd.to_numeric(charger_simulation_file['electric_vehicle_current_soc'], errors='coerce').to_numpy(dtype='float32')
                charger_simulation.electric_vehicle_current_soc = ChargerSimulation._normalize_soc_series(
                    current_soc_raw,
                    default_soc_value=-0.1,
                    noise_std=0.0,
                    unit=soc_unit.get('electric_vehicle_current_soc'),
                )
                charger_simulation._soc_units['electric_vehicle_current_soc'] = (
                    soc_unit.get('electric_vehicle_current_soc')
                    or ChargerSimulation._soc_series_unit(current_soc_raw)
                )

            charger_type = charger_config['type']
            charger_class = component_constructor(charger_type, f'buildings.{building_name}.chargers.{charger_name}.type')
            charger_attributes = dict(charger_config.get('attributes', {}) or {})
            charger_path = f'buildings.{building_name}.chargers.{charger_name}'
            charger_attributes = charger_power_attributes(
                charger_class, charger_attributes, charger_path,
                resolve_physics_version(schema.get('physics_version')),
            )
            charger_attributes['episode_tracker'] = episode_tracker
            # Chargers draw no random values, but an unseeded one draws its seed from Python's global `random`.
            charger_attributes.setdefault('random_seed', schema['random_seed'])
            charger_object = charger_class(
                charger_simulation=charger_simulation,
                charger_id=charger_name,
                **charger_attributes,
                seconds_per_time_step=schema['seconds_per_time_step'],
                time_step_ratio=time_step_ratio,
            )
            chargers_list.append(charger_object)
    return chargers_list


_CHARGER_KEYS = ('type', 'charger_simulation', 'attributes', 'autosize', 'noise_std', 'soc_unit')


def check_charger_keys(charger_config: dict, path: str):
    """Warn about charger keys the loader does not read, such as a misspelt `soc_unit`."""

    unknown = [key for key in charger_config if key not in _CHARGER_KEYS]

    if unknown:
        details = []

        for key in sorted(unknown):
            match = difflib.get_close_matches(key, _CHARGER_KEYS, n=1)
            details.append(f"'{key}'" + (f" (did you mean '{match[0]}'?)" if match else ''))

        warnings.warn(
            f"{path} has keys the loader ignores: {', '.join(details)}. "
            'Charger attributes go under "attributes".',
            UserWarning,
            stacklevel=2,
        )


def charger_power_attributes(charger_class, attributes: dict, path: str, physics_version: int) -> dict:
    """Validate a charger's schema `attributes` and resolve its omitted power limits (#369).

    A name the charger class does not accept raises `ValueError` instead of being dropped. Under
    physics version 2 an omitted `max_discharging_power` is 0 (no V2G) and an omitted
    `max_charging_power` is `nominal_power`; physics version 1 keeps the 50 kW of 3.6.0 for both.
    A warning names the limits that fall back to an assumed value.
    """

    validate = getattr(charger_class, '_validate_attributes', None)

    if validate is not None:
        validate(attributes, path=f'{path}.attributes')

    attributes = dict(attributes)
    assumed = []

    if physics_version < 2:
        legacy = getattr(charger_class, '_LEGACY_DEFAULT_POWER', 50.0)

        for key in ('max_charging_power', 'max_discharging_power'):
            if attributes.get(key) is None:
                attributes[key] = legacy
                assumed.append(f'{key}={legacy:g} kW')

    else:
        if attributes.get('max_charging_power') is None and attributes.get('nominal_power') is None:
            default = getattr(charger_class, '_DEFAULT_MAX_CHARGING_POWER', 50.0)
            assumed.append(f'max_charging_power={default:g} kW')

        if attributes.get('max_discharging_power') is None:
            assumed.append('max_discharging_power=0 kW (no V2G)')

    # `efficiency` applies only to a direction without an efficiency curve, and discharging only if
    # the charger can discharge.
    can_discharge = (attributes.get('max_discharging_power') or 0.0) > 0.0
    efficiency_used = attributes.get('charge_efficiency_curve') is None or (
        can_discharge and attributes.get('discharge_efficiency_curve') is None
    )

    if attributes.get('efficiency') is None and efficiency_used:
        assumed.append('efficiency=1.0')

    if assumed:
        warnings.warn(
            f"{path} does not set {', '.join(a.split('=')[0] for a in assumed)}; using {', '.join(assumed)}. "
            'Set them in the charger attributes to silence this warning.',
            UserWarning,
            stacklevel=2,
        )

    return attributes


def solar_generation_enabled(solar_generation, index: int) -> bool:
    """Whether the `solar_generation` constructor argument keeps the PV of the building loaded at `index`.

    It is one value for every building or a list in the env's building order; None keeps the PV.
    """
    solar_generation = True if solar_generation is None else solar_generation
    solar_generation = solar_generation[index] if isinstance(solar_generation, list) else solar_generation
    return bool(solar_generation)


def configure_devices(building, building_name, building_type, building_schema, schema,
                      index, kwargs, pv_sizing_data, battery_sizing_data):
    device_metadata = {
        'cooling_device': {'autosizer': building.autosize_cooling_device},
        'heating_device': {'autosizer': building.autosize_heating_device},
        'dhw_device': {'autosizer': building.autosize_dhw_device},
        'dhw_storage': {'autosizer': building.autosize_dhw_storage},
        'cooling_storage': {'autosizer': building.autosize_cooling_storage},
        'heating_storage': {'autosizer': building.autosize_heating_storage},
        'electrical_storage': {'autosizer': building.autosize_electrical_storage},
        'pv': {'autosizer': building.autosize_pv},
    }
    solar_generation = solar_generation_enabled(kwargs.get('solar_generation'), index)

    for device_name in device_metadata:
        if building_schema.get(device_name, None) is None:
            device = None

        elif device_name == 'pv' and not solar_generation:
            device = None

        else:
            device_type: str = building_schema[device_name]['type']
            constructor = component_constructor(device_type, f'buildings.{building_name}.{device_name}.type')
            attributes = dict(building_schema[device_name].get('attributes', {}) or {})
            if device_name == 'electrical_storage':
                attributes.pop('phase_connection', None)
            attributes['seconds_per_time_step'] = schema['seconds_per_time_step']

            if schema['random_stream_version'] == random_streams.LEGACY_RANDOM_STREAM_VERSION:
                md5 = hashlib.md5()
                device_random_seed = 0

                for string in [building_name, building_type, device_name, device_type]:
                    md5.update(string.encode())
                    hash_to_integer_base = 16
                    device_random_seed += int(md5.hexdigest(), hash_to_integer_base)

                device_random_seed = int(str(device_random_seed * (schema['random_seed'] + 1))[:9])

            else:
                # The stream key separates the devices; the seed stays the environment seed.
                device_random_seed = schema['random_seed']

            attributes = {
                **attributes,
                'random_seed': attributes['random_seed'] if attributes.get('random_seed', None) is not None else device_random_seed,
                'random_stream_version': attributes.get('random_stream_version', schema['random_stream_version']),
                # An explicit seed is the device's own stream, as for a device built on its own; the
                # environment seed is keyed by building and device so devices draw independently.
                'random_stream_key': attributes.get(
                    'random_stream_key',
                    () if attributes.get('random_seed', None) is not None else ('building', building_name, device_name),
                ),
            }
            device = constructor(**attributes)
            autosize = parse_bool(
                building_schema[device_name].get('autosize', False),
                default=False,
                path=f'buildings.{building.name}.{device_name}.autosize',
            )
            if isinstance(device, Battery):
                # Physics version 1 limits battery discharge with the charging curve (#227).
                device.legacy_discharge_power_limit = physics_version_of(building) < 2
            building.__setattr__(device_name, device)
            # Schema-built devices do not know the dataset/control-step ratio yet, but the autosizers
            # convert dataset-resolution demand with it. Without this, hourly data run at 15-minute
            # control sizes thermal devices and batteries 4x too large.
            device.time_step_ratio = building.time_step_ratio

            if autosize:
                autosizer = device_metadata[device_name]['autosizer']
                autosize_kwargs = {} if building_schema[device_name].get('autosize_attributes', None) is None else building_schema[device_name]['autosize_attributes']

                if isinstance(device, PV):
                    autosize_kwargs['epw_filepath'] = os.path.join(schema['root_directory'], autosize_kwargs['epw_filepath'])
                    autosize_kwargs['sizing_data'] = pv_sizing_data

                elif isinstance(device, Battery):
                    autosize_kwargs['sizing_data'] = battery_sizing_data

                autosizer(**autosize_kwargs)

            device.random_seed = schema['random_seed']
