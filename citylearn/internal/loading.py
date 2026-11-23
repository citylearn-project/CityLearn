from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import logging
import os
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, NamedTuple, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd

from citylearn import random_streams
from citylearn.base import EpisodeTracker
from citylearn.building import Building
from citylearn.data import (
    DataSet,
    EnergySimulation,
    DeferrableApplianceSimulation,
    EscalatorSimulation,
)
from citylearn.electric_vehicle import ElectricVehicle
from citylearn.energy_model import Battery, DeferrableAppliance, Escalator
from citylearn.reward_function import MultiBuildingRewardFunction, RewardFunction
from citylearn.utilities import parse_bool
from citylearn.internal import grid_availability, loading_inputs, loading_components
from citylearn.internal.physics_version import resolve_physics_version
from citylearn.internal.baseline import BaselineEVChargingSource

LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv


class MemberWindow(NamedTuple):
    """Active window of a dynamic-topology member source, in global dataset time steps.

    `start` is the first activation and `end` (exclusive) the end of that activation, clipped to the
    simulation end. `rejoins` is true when the member is activated again after leaving.
    """

    start: int
    end: int
    rejoins: bool = False


@dataclass
class LoadContext:
    """Lightweight holder for loading inputs."""

    schema: Mapping[str, Any]
    kwargs: Mapping[str, Any]


class CityLearnLoadingService:
    """Internal loader service that builds env components from schema."""

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self._dynamic_mode: bool = False
        self._dynamic_expected_rows: int = 0
        self._dynamic_member_windows: Dict[str, MemberWindow] = {}
        self._dynamic_charger_windows: Dict[Tuple[str, str], MemberWindow] = {}
        self._dynamic_rejoining_members: set = set()
        self._dynamic_dataset_rows: Optional[int] = None
        self._timeseries_row_counts: Dict[str, int] = {}
        self._charger_soc_unit_cache: Dict[str, Dict[str, str]] = {}
        self._shared_timeseries_cache: Dict[Tuple[Any, ...], Any] = {}

    @staticmethod
    def _dataframe_to_constructor_kwargs(dataframe: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Return column arrays without boxing every value into Python lists."""

        return {
            str(column): series.to_numpy(copy=False)
            for column, series in dataframe.items()
        }

    @staticmethod
    def _print_time_step_conversion_notice(
        *,
        building_name: str,
        source: str,
        dataset_seconds_per_time_step,
        seconds_per_time_step,
        time_step_ratio,
    ):
        """Print an explicit notice when runtime energy conversions are active."""

        try:
            ratio = float(time_step_ratio)
        except (TypeError, ValueError):
            return

        if not np.isfinite(ratio) or abs(ratio - 1.0) <= 1.0e-9:
            return

        dataset_seconds = "unknown" if dataset_seconds_per_time_step is None else f"{float(dataset_seconds_per_time_step):g}"
        schema_seconds = "unknown" if seconds_per_time_step is None else f"{float(seconds_per_time_step):g}"
        print(
            "[CityLearn][unit-conversion] "
            f"Building '{building_name}' dataset resolution differs from schema/control step: "
            f"dataset_seconds_per_time_step={dataset_seconds}, "
            f"seconds_per_time_step={schema_seconds}, "
            f"time_step_ratio={ratio:g}. "
            "No automatic resampling is performed. Keep schema seconds_per_time_step aligned with the dataset unless "
            "you intentionally want runtime energy conversion through time_step_ratio. "
            f"source={source}"
        )

    def load(
        self,
        schema: Mapping[str, Any],
        **kwargs,
    ) -> Tuple[
        Union[os.PathLike, str],
        List[Building],
        List[ElectricVehicle],
        Union[int, List[Tuple[int, int]]],
        bool,
        bool,
        float,
        RewardFunction,
        bool,
        List[str],
        EpisodeTracker,
    ]:
        """Return env objects as defined by schema."""

        schema['root_directory'] = kwargs['root_directory'] if kwargs.get('root_directory') is not None else schema['root_directory']
        # The environment resolved the physics version from its argument and the schema.
        schema['physics_version'] = getattr(self.env, 'physics_version', schema.get('physics_version'))
        schema['random_seed'] = schema.get('random_seed', None) if kwargs.get('random_seed', None) is None else kwargs['random_seed']
        if schema['random_seed'] is None:
            schema['random_seed'] = self.env.random_seed
        # Resolved by the environment from its constructor argument or the schema.
        schema['random_stream_version'] = self.env.random_stream_version
        from citylearn.internal.temporal import TimeAxis, snapshot_inputs
        self.env._initialization_seed = schema['random_seed']
        self.env._input_snapshot = snapshot_inputs(schema)
        self.env._time_axis = TimeAxis(schema)

        schema['central_agent'] = parse_bool(
            kwargs['central_agent'] if kwargs.get('central_agent') is not None else schema['central_agent'],
            default=False,
            path='central_agent',
        )

        schema['chargers_observations_helper'] = {key: value for key, value in schema["observations"].items() if "electric_vehicle_" in key}
        schema['chargers_actions_helper'] = {key: value for key, value in schema["actions"].items() if "electric_vehicle_" in key}
        schema['chargers_shared_observations_helper'] = {
            key: value
            for key, value in schema["observations"].items()
            if "electric_vehicle_" in key and value.get("shared_in_central_agent", True)
        }

        schema['deferrable_appliance_observations_helper'] = {
            key: value for key, value in schema["observations"].items()
            if key.startswith("deferrable_appliance_")
        }
        schema['deferrable_appliance_actions_helper'] = {
            key: value for key, value in schema["actions"].items()
            if key == "deferrable_appliance" or key.startswith("deferrable_appliance_")
        }
        schema['escalator_observations_helper'] = {
            key: value for key, value in schema['observations'].items()
            if key.startswith('escalator_')
        }
        schema['escalator_actions_helper'] = {
            key: value for key, value in schema['actions'].items()
            if key == 'escalator' or key.startswith('escalator_')
        }

        schema['observations'] = {
            key: value
            for key, value in schema["observations"].items()
            if key not in (
                set(schema['chargers_observations_helper'])
                | set(schema['deferrable_appliance_observations_helper'])
                | set(schema['escalator_observations_helper'])
            )
        }
        schema['actions'] = {
            key: value
            for key, value in schema['actions'].items()
            if key not in (
                set(schema['chargers_actions_helper'])
                | set(schema['deferrable_appliance_actions_helper'])
                | set(schema['escalator_actions_helper'])
            )
        }

        schema['shared_observations'] = (
            kwargs['shared_observations']
            if kwargs.get('shared_observations') is not None
            else [
                k
                for k, v in schema['observations'].items()
                if not k.startswith("electric_vehicle_")
                and not k.startswith("deferrable_appliance_")
                and not k.startswith("escalator_")
                and parse_bool(v.get('shared_in_central_agent', False), default=False, path=f'observations.{k}.shared_in_central_agent')
            ]
        )

        schema['episode_time_steps'] = kwargs['episode_time_steps'] if kwargs.get('episode_time_steps') is not None else schema.get('episode_time_steps', None)
        schema['rolling_episode_split'] = kwargs['rolling_episode_split'] if kwargs.get('rolling_episode_split') is not None else schema.get('rolling_episode_split', None)
        schema['random_episode_split'] = kwargs['random_episode_split'] if kwargs.get('random_episode_split') is not None else schema.get('random_episode_split', None)
        schema['seconds_per_time_step'] = kwargs['seconds_per_time_step'] if kwargs.get('seconds_per_time_step') is not None else schema['seconds_per_time_step']

        schema['simulation_start_time_step'] = kwargs['simulation_start_time_step'] if kwargs.get('simulation_start_time_step') is not None else schema['simulation_start_time_step']
        schema['simulation_end_time_step'] = kwargs['simulation_end_time_step'] if kwargs.get('simulation_end_time_step') is not None else schema['simulation_end_time_step']
        if (
            kwargs.get('episode_time_steps') is None
            and isinstance(schema['episode_time_steps'], list)
            and (kwargs.get('simulation_start_time_step') is not None or kwargs.get('simulation_end_time_step') is not None)
        ):
            schema['episode_time_steps'] = self._restrict_schema_episodes(
                schema['episode_time_steps'], schema['simulation_start_time_step'], schema['simulation_end_time_step']
            )

        episode_tracker = EpisodeTracker(schema['simulation_start_time_step'], schema['simulation_end_time_step'])

        pv_sizing_data = None
        battery_sizing_data = None

        dynamic_mode = getattr(self.env, 'topology_mode', 'static') == 'dynamic'
        self._dynamic_mode = dynamic_mode
        self._dynamic_expected_rows = int(episode_tracker.simulation_time_steps)
        self._dynamic_member_windows = {}
        self._dynamic_charger_windows = {}
        self._dynamic_rejoining_members = set()
        self._dynamic_dataset_rows = None
        self._shared_timeseries_cache = {}

        if dynamic_mode:
            self._dynamic_member_windows = self._build_dynamic_member_windows(schema, self._dynamic_expected_rows)
            self._dynamic_charger_windows = self._build_dynamic_charger_windows(
                schema,
                self._dynamic_member_windows,
                self._dynamic_expected_rows,
            )

        buildings_to_include = list(schema['buildings'].keys())
        buildings: List[Building] = []

        if kwargs.get('buildings') is not None and len(kwargs['buildings']) > 0:
            if isinstance(kwargs['buildings'][0], Building):
                buildings = kwargs['buildings']

                for building in buildings:
                    building.episode_tracker = episode_tracker

                buildings_to_include = []

            elif isinstance(kwargs['buildings'][0], str):
                buildings_to_include = [b for b in buildings_to_include if b in kwargs['buildings']]

            elif isinstance(kwargs['buildings'][0], int):
                buildings_to_include = [buildings_to_include[i] for i in kwargs['buildings']]

            else:
                raise Exception('Unknown buildings type. Allowed types are citylearn.building.Building, int and str.')

        else:
            if dynamic_mode:
                # Dynamic topology needs both initially active members and potential templates.
                buildings_to_include = list(schema['buildings'].keys())
            else:
                buildings_to_include = [
                    b for b in buildings_to_include
                    if parse_bool(schema['buildings'][b].get('include', True), default=True, path=f'buildings.{b}.include')
                ]

        if len(buildings_to_include) > 0:
            solar_generation = kwargs.get('solar_generation')
            solar_generation = True if solar_generation is None else solar_generation

            def _is_solar_generation_enabled(index: int) -> bool:
                if isinstance(solar_generation, list):
                    return bool(
                        parse_bool(
                            solar_generation[index],
                            default=True,
                            path=f'solar_generation[{index}]',
                        )
                    )

                return bool(parse_bool(solar_generation, default=True, path='solar_generation'))

            require_pv_sizing_data = False
            require_battery_sizing_data = False

            for i, building_name in enumerate(buildings_to_include):
                building_schema = schema['buildings'][building_name]
                pv_schema = building_schema.get('pv') or {}
                electrical_storage_schema = building_schema.get('electrical_storage') or {}
                pv_autosize = parse_bool(
                    pv_schema.get('autosize', False),
                    default=False,
                    path=f'buildings.{building_name}.pv.autosize',
                )
                battery_autosize = parse_bool(
                    electrical_storage_schema.get('autosize', False),
                    default=False,
                    path=f'buildings.{building_name}.electrical_storage.autosize',
                )
                require_pv_sizing_data = require_pv_sizing_data or (pv_autosize and _is_solar_generation_enabled(i))
                require_battery_sizing_data = require_battery_sizing_data or battery_autosize

                if require_pv_sizing_data and require_battery_sizing_data:
                    break

            if require_pv_sizing_data or require_battery_sizing_data:
                dataset = DataSet(offline=self.env.offline)

                if require_pv_sizing_data:
                    pv_sizing_data = dataset.get_pv_sizing_data()

                if require_battery_sizing_data:
                    battery_sizing_data = dataset.get_battery_sizing_data()

        for i, building_name in enumerate(buildings_to_include):
            buildings.append(self.load_building(i, building_name, schema, episode_tracker, pv_sizing_data, battery_sizing_data, **kwargs))

        if not dynamic_mode:
            self._validate_static_action_asset_consistency(buildings)

        electric_vehicles: List[ElectricVehicle] = []
        if kwargs.get('electric_vehicles_def') is not None and len(kwargs['electric_vehicles_def']) > 0:
            electric_vehicle_schemas = kwargs['electric_vehicles_def']
        else:
            electric_vehicle_schemas = schema.get('electric_vehicles_def', {})

        for electric_vehicle_name, electric_vehicle_schema in electric_vehicle_schemas.items():
            include_ev = True if dynamic_mode else parse_bool(
                electric_vehicle_schema.get('include', True),
                default=True,
                path=f'electric_vehicles_def.{electric_vehicle_name}.include',
            )
            if include_ev:
                time_step_ratio = buildings[0].time_step_ratio if len(buildings) > 0 else 1.0
                electric_vehicles.append(
                    self.load_electric_vehicle(electric_vehicle_name, schema, electric_vehicle_schema, episode_tracker, time_step_ratio)
                )

        reward_schema = schema['reward_function']
        reward_type = reward_schema['type']
        reward_attrs = reward_schema.get('attributes', {})
        is_multi = isinstance(reward_type, dict)
        reward_override = kwargs.get('reward_function')
        reward_override_kwargs = kwargs.get('reward_function_kwargs')

        if reward_override is not None:
            # The constructor argument overrides the schema definition, including per-building ones.
            reward_function = self._construct_reward_override(
                reward_override, reward_override_kwargs, None if is_multi else reward_type, reward_attrs,
            )

        elif is_multi:
            default_type = reward_type.get('default')
            if default_type is None and reward_type:
                default_type = next(iter(reward_type.values()))

            default_attrs = reward_attrs.get('default')
            if default_attrs is None and reward_attrs:
                default_attrs = next(iter(reward_attrs.values()))

            reward_functions = {}
            for building in buildings:
                name = building.name
                r_type = reward_type.get(name, default_type)
                r_attr = reward_attrs.get(name, default_attrs) or {}

                if r_type is None:
                    raise ValueError(f"No reward function defined for building '{name}' and no default provided")

                module_name = '.'.join(r_type.split('.')[:-1])
                class_name = r_type.split('.')[-1]
                module = importlib.import_module(module_name)
                constructor = getattr(module, class_name)
                reward_functions[name] = constructor(None, **r_attr)

            reward_function = MultiBuildingRewardFunction(None, reward_functions)

        else:
            reward_function_attributes = reward_attrs if reward_override_kwargs is None else reward_override_kwargs
            reward_function = self._import_object(reward_type)(None, **(reward_function_attributes or {}))

        return (
            schema['root_directory'],
            buildings,
            electric_vehicles,
            schema['episode_time_steps'],
            schema['rolling_episode_split'],
            schema['random_episode_split'],
            schema['seconds_per_time_step'],
            reward_function,
            schema['central_agent'],
            schema['shared_observations'],
            episode_tracker,
        )

    @staticmethod
    def _restrict_schema_episodes(splits, simulation_start: int, simulation_end: int) -> List[List[int]]:
        """Clip a schema's explicit episode list to a simulation window the caller narrowed (CityLearn #308).

        Only the window's rows are loaded, so a schema episode outside it would read past the data
        or simulate rows outside the window. Each episode keeps the part that overlaps the window,
        and episodes without an interval inside it are dropped.
        """

        simulation_start, simulation_end = int(simulation_start), int(simulation_end)
        restricted = []

        for split in splits:
            try:
                start, end = int(split[0]), int(split[1])
            except (TypeError, ValueError, IndexError):
                return splits  # malformed: let the episode tracker raise its error

            clipped_start, clipped_end = max(start, simulation_start), min(end, simulation_end)

            if clipped_start > clipped_end or (clipped_start == clipped_end and start < end):
                continue

            restricted.append([clipped_start, clipped_end])

        if not restricted:
            raise ValueError(
                f'None of the schema episode_time_steps {splits} overlaps the simulation window '
                f'({simulation_start}, {simulation_end}). Pass episode_time_steps for this window.'
            )

        return restricted

    @staticmethod
    def _import_object(path: str):
        module_name, _, attribute_name = path.rpartition('.')
        return getattr(importlib.import_module(module_name), attribute_name)

    def _construct_reward_override(self, reward_override, reward_override_kwargs, schema_type, schema_attributes):
        """Build the reward function passed to the constructor.

        An instance is used as given (the environment sets its metadata). A class or import path is
        constructed with ``reward_override_kwargs`` when provided. Otherwise the schema's attributes are
        used only if the override is the schema's own reward type, because they parameterize that type.
        """

        if isinstance(reward_override, RewardFunction):
            if reward_override_kwargs:
                LOGGER.warning('reward_function_kwargs are ignored when reward_function is an instance.')

            return reward_override

        if isinstance(reward_override, str):
            path = reward_override
            constructor = self._import_object(path)
        else:
            constructor = reward_override
            path = f'{constructor.__module__}.{constructor.__name__}'

        if reward_override_kwargs is not None:
            attributes = reward_override_kwargs
        elif schema_type is not None and path == schema_type:
            attributes = schema_attributes
        else:
            if schema_attributes:
                LOGGER.warning(
                    'Schema reward_function attributes %s belong to %s and are not applied to the override %s; '
                    'pass reward_function_kwargs to configure it.',
                    sorted(schema_attributes), schema_type or 'the per-building schema reward functions', path,
                )

            attributes = {}

        return constructor(None, **(attributes or {}))

    def load_building(
        self,
        index: int,
        building_name: str,
        schema: dict,
        episode_tracker: EpisodeTracker,
        pv_sizing_data: pd.DataFrame,
        battery_sizing_data: pd.DataFrame,
        **kwargs,
    ) -> Building:
        """Orchestrate input preparation, metadata and component construction."""
        building_schema = schema['buildings'][building_name]
        options = loading_components.base_building_options(building_schema)
        expected_rows = int(getattr(self, '_dynamic_expected_rows', episode_tracker.simulation_time_steps))
        member_window = self._dynamic_member_windows.get(building_name)
        inputs = loading_inputs.load_building_inputs(self, building_name, schema, expected_rows, member_window)
        options['time_step_ratio'] = inputs.time_step_ratio
        available_grid_power = grid_availability.load(
            self, building_name, building_schema, schema, expected_rows, member_window)

        if available_grid_power is not None:
            options['available_grid_power'] = available_grid_power

        building_type = ('citylearn.citylearn.Building' if building_schema.get('type') is None
                         else building_schema['type'])
        constructor = loading_components.component_constructor(building_type, f'buildings.{building_name}.type')
        loading_components.add_model_options(options, building_name, building_schema, schema, episode_tracker, constructor)
        outage = loading_components.outage_options(index, building_name, building_schema, kwargs)
        chargers = loading_components.load_chargers(
            self, building_name, building_schema, schema, episode_tracker, expected_rows, inputs.time_step_ratio)

        appliance_schemas = (kwargs['deferrable_appliances'] if kwargs.get('deferrable_appliances')
                             else building_schema.get('deferrable_appliances', {}))
        appliances = [self.load_deferrable_appliance(name, building_name, schema, config, episode_tracker)
                      for name, config in appliance_schemas.items()]
        escalators = [self.load_escalator(
            name, building_name, schema, config, episode_tracker, expected_rows=expected_rows,
            window=member_window, time_step_ratio=inputs.time_step_ratio,
        ) for name, config in (building_schema.get('escalators', {}) or {}).items()]
        inactive_actions = self._resolve_inactive_actions(index, building_schema, kwargs)
        observation_metadata, action_metadata = self.process_metadata(
            schema, building_schema, chargers, appliances, escalators, index, inputs.energy_simulation, **kwargs)
        building = constructor(
            energy_simulation=inputs.energy_simulation, deferrable_appliances=appliances,
            escalators=escalators, electric_vehicle_chargers=chargers, weather=inputs.weather,
            observation_metadata=observation_metadata, action_metadata=action_metadata,
            carbon_intensity=inputs.carbon_intensity, pricing=inputs.pricing, name=building_name,
            seconds_per_time_step=schema['seconds_per_time_step'], random_seed=schema['random_seed'],
            random_stream_version=schema['random_stream_version'], random_stream_key=('building', building_name),
            episode_tracker=episode_tracker, **outage, **options,
        )
        building._declared_inactive_actions = set(inactive_actions)
        # Before the devices are configured: autosizing depends on the physics version.
        building.physics_version = getattr(self.env, 'physics_version', schema.get('physics_version'))
        building.baseline_version = getattr(self.env, 'baseline_version', schema.get('baseline_version'))
        building._baseline_ev_charging_source = BaselineEVChargingSource(self.env)
        loading_components.configure_devices(
            building, building_name, building_type, building_schema, schema, index, kwargs,
            pv_sizing_data, battery_sizing_data,
        )
        building.observation_space = building.estimate_observation_space()
        building.action_space = building.estimate_action_space()
        return building

    def process_metadata(
        self,
        schema,
        building_schema,
        chargers_list,
        deferrable_appliances_list,
        escalators_list,
        index,
        energy_simulation: EnergySimulation,
        **kwargs,
    ):
        """Build observation and action metadata for one building."""

        observation_metadata = {
            k: parse_bool(v.get('active', False), default=False, path=f'observations.{k}.active')
            for k, v in schema['observations'].items()
        }
        if 'minutes' in observation_metadata and energy_simulation.minutes is None:
            observation_metadata.pop('minutes', None)
        if 'seconds' in observation_metadata and getattr(energy_simulation, 'seconds', None) is None:
            observation_metadata.pop('seconds', None)

        chargers_observations_metadata_helper = {
            k: parse_bool(v.get('active', False), default=False, path=f'observations.{k}.active')
            for k, v in schema['chargers_observations_helper'].items()
        }
        deferrable_appliance_observations_metadata_helper = {
            k: parse_bool(v.get('active', False), default=False, path=f'observations.{k}.active')
            for k, v in schema['deferrable_appliance_observations_helper'].items()
        }
        escalator_observations_metadata_helper = {
            k: parse_bool(v.get('active', False), default=False, path=f'observations.{k}.active')
            for k, v in schema['escalator_observations_helper'].items()
        }

        if kwargs.get('active_observations') is not None:
            active_observations = kwargs['active_observations']
            active_observations = active_observations[index] if isinstance(active_observations[0], list) else active_observations
            observation_metadata = {k: True if k in active_observations else False for k in observation_metadata}
            chargers_observations_metadata_helper = {k: True if k in active_observations else False for k in chargers_observations_metadata_helper}
            deferrable_appliance_observations_metadata_helper = {k: True if k in active_observations else False for k in deferrable_appliance_observations_metadata_helper}
            escalator_observations_metadata_helper = {k: True if k in active_observations else False for k in escalator_observations_metadata_helper}

        if kwargs.get('inactive_observations') is not None:
            inactive_observations = kwargs['inactive_observations']
            inactive_observations = inactive_observations[index] if isinstance(inactive_observations[0], list) else inactive_observations
        elif building_schema.get('inactive_observations') is not None:
            inactive_observations = building_schema['inactive_observations']
        else:
            inactive_observations = []

        observation_metadata = {
            k: False if k in inactive_observations else observation_metadata[k]
            for k in observation_metadata
        }
        chargers_observations_metadata_helper = {
            k: False if k in inactive_observations else chargers_observations_metadata_helper[k]
            for k in chargers_observations_metadata_helper
        }
        deferrable_appliance_observations_metadata_helper = {
            k: False if k in inactive_observations else deferrable_appliance_observations_metadata_helper[k]
            for k in deferrable_appliance_observations_metadata_helper
        }
        escalator_observations_metadata_helper = {
            k: False if k in inactive_observations else escalator_observations_metadata_helper[k]
            for k in escalator_observations_metadata_helper
        }

        action_metadata = {
            k: parse_bool(v.get('active', False), default=False, path=f'actions.{k}.active')
            for k, v in schema['actions'].items()
        }
        chargers_actions_metadata_helper = {
            k: parse_bool(v.get('active', False), default=False, path=f'actions.{k}.active')
            for k, v in schema['chargers_actions_helper'].items()
        }
        deferrable_appliance_actions_metadata_helper = {
            k: parse_bool(v.get('active', False), default=False, path=f'actions.{k}.active')
            for k, v in schema['deferrable_appliance_actions_helper'].items()
        }
        escalator_actions_metadata_helper = {
            k: parse_bool(v.get('active', False), default=False, path=f'actions.{k}.active')
            for k, v in schema['escalator_actions_helper'].items()
        }

        if kwargs.get('active_actions') is not None:
            active_actions = kwargs['active_actions']
            active_actions = active_actions[index] if isinstance(active_actions[0], list) else active_actions
            action_metadata = {k: True if k in active_actions else False for k in action_metadata}
            chargers_actions_metadata_helper = {k: True if k in active_actions else False for k in chargers_actions_metadata_helper}
            deferrable_appliance_actions_metadata_helper = {k: True if k in active_actions else False for k in deferrable_appliance_actions_metadata_helper}
            escalator_actions_metadata_helper = {k: True if k in active_actions else False for k in escalator_actions_metadata_helper}

        inactive_actions = self._resolve_inactive_actions(index, building_schema, kwargs)

        action_metadata = {k: False if k in inactive_actions else v for k, v in action_metadata.items()}
        chargers_actions_metadata_helper = {k: False if k in inactive_actions else v for k, v in chargers_actions_metadata_helper.items()}
        deferrable_appliance_actions_metadata_helper = {k: False if k in inactive_actions else v for k, v in deferrable_appliance_actions_metadata_helper.items()}
        escalator_actions_metadata_helper = {k: False if k in inactive_actions else v for k, v in escalator_actions_metadata_helper.items()}

        if len(chargers_list) > 0:
            for charger in chargers_list:
                charger_id = charger.charger_id

                if chargers_observations_metadata_helper.get('electric_vehicle_charger_connected_state', False):
                    observation_metadata[f'electric_vehicle_charger_{charger_id}_connected_state'] = True

                if chargers_observations_metadata_helper.get('connected_electric_vehicle_at_charger_departure_time', False):
                    observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_departure_time'] = True

                if chargers_observations_metadata_helper.get('connected_electric_vehicle_at_charger_required_soc_departure', False):
                    observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_required_soc_departure'] = True

                if chargers_observations_metadata_helper.get('connected_electric_vehicle_at_charger_soc', False):
                    observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_soc'] = True

                if chargers_observations_metadata_helper.get('connected_electric_vehicle_at_charger_battery_capacity', False):
                    observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_battery_capacity'] = True

                if chargers_observations_metadata_helper.get('electric_vehicle_charger_incoming_state', False):
                    observation_metadata[f'electric_vehicle_charger_{charger_id}_incoming_state'] = True

                if chargers_observations_metadata_helper.get('incoming_electric_vehicle_at_charger_estimated_arrival_time', False):
                    observation_metadata[f'incoming_electric_vehicle_at_charger_{charger_id}_estimated_arrival_time'] = True

                if chargers_observations_metadata_helper.get('incoming_electric_vehicle_at_charger_estimated_soc_arrival', False):
                    observation_metadata[f'incoming_electric_vehicle_at_charger_{charger_id}_estimated_soc_arrival'] = True

                if chargers_actions_metadata_helper.get('electric_vehicle_storage', False):
                    action_metadata[f'electric_vehicle_storage_{charger.charger_id}'] = True

        if len(deferrable_appliances_list) > 0:
            for appliance in deferrable_appliances_list:
                for helper_name, active in deferrable_appliance_observations_metadata_helper.items():
                    if active:
                        feature_name = helper_name.replace('deferrable_appliance_', '', 1)
                        observation_metadata[f'deferrable_appliance_{appliance.name}_{feature_name}'] = True

                if deferrable_appliance_actions_metadata_helper.get('deferrable_appliance', False):
                    action_metadata[f'deferrable_appliance_{appliance.name}'] = True

        if len(escalators_list) > 0:
            for escalator in escalators_list:
                for helper_name, active in escalator_observations_metadata_helper.items():
                    if active:
                        feature_name = helper_name.replace('escalator_', '', 1)
                        observation_metadata[f'escalator_{escalator.name}_{feature_name}'] = True

                if escalator_actions_metadata_helper.get('escalator', False):
                    action_metadata[f'escalator_{escalator.name}'] = True

        return observation_metadata, action_metadata

    def load_electric_vehicle(
        self,
        electric_vehicle_name: str,
        schema: dict,
        electric_vehicle_schema: dict,
        episode_tracker: EpisodeTracker,
        time_step_ratio,
    ) -> ElectricVehicle:
        """Initialize and return an electric vehicle model."""

        attrs = electric_vehicle_schema['battery']['attributes']
        battery_type = electric_vehicle_schema['battery'].get('type', 'citylearn.energy_model.Battery')
        module, class_name = battery_type.rsplit('.', 1)
        battery_constructor = getattr(importlib.import_module(module), class_name)
        if not issubclass(battery_constructor, Battery):
            raise ValueError('An electric vehicle battery must extend Battery')
        from citylearn.community_dataset import InventoryBattery
        capacity = attrs['capacity']
        initial_soc = attrs.get('initial_soc')
        if initial_soc is None:
            seed_source = f"{schema['random_seed']}:{electric_vehicle_name}:initial_soc"
            deterministic_seed = int(hashlib.md5(seed_source.encode('utf-8')).hexdigest()[:8], 16)
            # Draw within the declared SOC limits; InventoryBattery rejects an initial SOC outside them.
            initial_soc = float(np.random.RandomState(deterministic_seed).uniform(
                attrs.get('min_soc', 0.0), attrs.get('max_soc', 1.0),
            ))
        depth_of_discharge = attrs.get('depth_of_discharge', 1.0)
        loss_coefficient = attrs.get('loss_coefficient', 0.0)

        if loss_coefficient is None:
            loss_coefficient = 0.0
        elif isinstance(loss_coefficient, (list, tuple)):
            loss_coefficient = tuple(float(value) for value in loss_coefficient)
        else:
            loss_coefficient = float(loss_coefficient)

        # Each EV draws its unspecified battery parameters (efficiency, curves, capacity fade) from
        # its own seed, as `initial_soc` above does; a shared seed gave every EV identical values.
        battery_random_seed = attrs.get('random_seed')
        if battery_random_seed is None and schema['random_stream_version'] == random_streams.LEGACY_RANDOM_STREAM_VERSION:
            seed_source = f"{schema['random_seed']}:{electric_vehicle_name}:battery"
            battery_random_seed = int(hashlib.md5(seed_source.encode('utf-8')).hexdigest()[:8], 16)
        elif battery_random_seed is None:
            # The stream key below separates the EVs; the seed stays the environment seed.
            battery_random_seed = schema['random_seed']

        battery_kwargs = {
            'capacity': capacity,
            'initial_soc': initial_soc,
            'loss_coefficient': loss_coefficient,
            'seconds_per_time_step': schema['seconds_per_time_step'],
            'time_step_ratio': time_step_ratio,
            'random_seed': battery_random_seed,
            'random_stream_version': schema['random_stream_version'],
            'random_stream_key': () if attrs.get('random_seed') is not None else ('electric_vehicle', electric_vehicle_name, 'battery'),
            'episode_tracker': episode_tracker,
            'depth_of_discharge': depth_of_discharge,
        }

        for attribute in [
            'efficiency',
            'capacity_loss_coefficient',
            'power_efficiency_curve',
            'capacity_power_curve',
            'discharge_power_curve',
            'max_charge_kw',
            'max_discharge_kw',
            'min_soc',
            'max_soc',
            'charging_efficiency',
            'discharging_efficiency',
        ]:
            if attribute in attrs:
                battery_kwargs[attribute] = attrs[attribute]

        # InventoryBattery derives nominal_power from max_charge_kw and max_discharge_kw.
        if 'nominal_power' in attrs or not issubclass(battery_constructor, InventoryBattery):
            battery_kwargs['nominal_power'] = attrs['nominal_power']

        battery = battery_constructor(**battery_kwargs)
        # Physics version 1 limits battery discharge with the charging curve (#227).
        battery.legacy_discharge_power_limit = resolve_physics_version(
            getattr(self.env, 'physics_version', schema.get('physics_version'))) < 2

        electric_vehicle_type = 'citylearn.citylearn.ElectricVehicle' if electric_vehicle_schema.get('type', None) is None else electric_vehicle_schema['type']
        electric_vehicle_type_module = '.'.join(electric_vehicle_type.split('.')[0:-1])
        electric_vehicle_type_name = electric_vehicle_type.split('.')[-1]
        electric_vehicle_constructor = getattr(importlib.import_module(electric_vehicle_type_module), electric_vehicle_type_name)

        electric_vehicle: ElectricVehicle = electric_vehicle_constructor(
            battery=battery,
            name=electric_vehicle_name,
            seconds_per_time_step=schema['seconds_per_time_step'],
            random_seed=schema['random_seed'],
            episode_tracker=episode_tracker,
        )

        return electric_vehicle

    def load_deferrable_appliance(
        self,
        appliance_name: str,
        building_name: str,
        schema: dict,
        appliance_schema: dict,
        episode_tracker: EpisodeTracker,
    ) -> DeferrableAppliance:
        """Load sparse profile/schedule data and initialize a deferrable appliance."""

        profiles_file = os.path.join(schema['root_directory'], appliance_schema['cycle_profiles_file'])
        schedule_file = os.path.join(schema['root_directory'], appliance_schema['flexibility_schedule_file'])

        profiles = self._read_dataframe(profiles_file)
        schedule = self._read_dataframe(schedule_file)
        # Sparse requests use global calendar indexes. Keep the catalogue intact:
        # a local loading window can discard current requests in partial episodes
        # and future requests after member re-entry. Activation/audit owns eligibility.

        source_label = f'buildings.{building_name}.deferrable_appliances.{appliance_name}'
        simulation = DeferrableApplianceSimulation.from_dataframes(
            cycle_profiles=profiles,
            flexibility_schedule=schedule,
            source_label=source_label,
        )

        appliance_type = appliance_schema.get('type', 'citylearn.energy_model.DeferrableAppliance')
        appliance_module = '.'.join(appliance_type.split('.')[0:-1])
        appliance_class_name = appliance_type.split('.')[-1]
        appliance_class = getattr(importlib.import_module(appliance_module), appliance_class_name)
        attributes = dict(appliance_schema.get('attributes', {}) or {})
        attributes.setdefault('random_stream_version', schema['random_stream_version'])
        attributes.setdefault('random_stream_key', ('building', building_name, 'deferrable_appliance', appliance_name))

        appliance = appliance_class(
            deferrable_appliance_simulation=simulation,
            episode_tracker=episode_tracker,
            name=appliance_name,
            seconds_per_time_step=schema['seconds_per_time_step'],
            random_seed=schema['random_seed'],
            **attributes,
        )

        return appliance

    def load_escalator(
        self,
        escalator_name: str,
        building_name: str,
        schema: dict,
        escalator_schema: dict,
        episode_tracker: EpisodeTracker,
        *,
        expected_rows: int,
        window: Optional[MemberWindow],
        time_step_ratio: float,
    ) -> Escalator:
        """Load one aggregate escalator demand series and operating specification."""

        simulation_file = escalator_schema.get('simulation') or escalator_schema.get('simulation_file')
        if not simulation_file:
            raise ValueError(f'buildings.{building_name}.escalators.{escalator_name}.simulation is required.')
        filepath = os.path.join(schema['root_directory'], simulation_file)
        dataframe = self._read_member_timeseries(
            schema,
            filepath,
            expected_rows=expected_rows,
            window=window,
            source_label=f'buildings.{building_name}.escalators.{escalator_name}.simulation',
        )
        source_label = f'buildings.{building_name}.escalators.{escalator_name}'
        simulation = EscalatorSimulation.from_dataframe(dataframe, source_label=source_label)
        self._set_time_step_offset(simulation, schema['simulation_start_time_step'])

        escalator_type = escalator_schema.get('type', 'citylearn.energy_model.Escalator')
        module_name = '.'.join(escalator_type.split('.')[:-1])
        class_name = escalator_type.split('.')[-1]
        constructor = getattr(importlib.import_module(module_name), class_name)
        attributes = dict(escalator_schema.get('attributes', {}) or {})
        attributes.setdefault('random_stream_version', schema['random_stream_version'])
        attributes.setdefault('random_stream_key', ('building', building_name, 'escalator', escalator_name))
        return constructor(
            escalator_simulation=simulation,
            episode_tracker=episode_tracker,
            name=escalator_name,
            seconds_per_time_step=schema['seconds_per_time_step'],
            time_step_ratio=time_step_ratio,
            random_seed=schema['random_seed'],
            **attributes,
        )

    def load_washing_machine(self, *args, **kwargs):
        raise ValueError(
            "Legacy 'washing_machines' schemas are no longer supported. "
            "Use 'deferrable_appliances' with cycle_profiles_file and flexibility_schedule_file."
        )

    @staticmethod
    def _set_time_step_offset(time_series_data: Any, offset: int):
        """Record the original file index represented by row 0 after windowed loading."""

        setattr(time_series_data, 'time_step_offset', int(offset or 0))

    @staticmethod
    def _file_format(filepath: Union[str, os.PathLike]) -> str:
        suffix = os.path.splitext(str(filepath))[1].lower()
        if suffix in {'.parquet', '.pq', '.parq'}:
            return 'parquet'

        return 'csv'

    def _read_simulation_dataframe(
        self,
        schema: Mapping[str, Any],
        filepath: Union[str, os.PathLike],
        *,
        csv_dtypes: Optional[Mapping[str, Any]] = None,
    ) -> pd.DataFrame:
        """Read only the configured simulation window from a CSV or Parquet time series file."""

        dataframe = self._read_timeseries_dataframe(
            filepath,
            start_time_step=int(schema['simulation_start_time_step']),
            end_time_step=int(schema['simulation_end_time_step']),
            csv_dtypes=csv_dtypes,
        )
        if not parse_bool(
            schema.get('terminal_observation_padding', False),
            default=False,
            path='terminal_observation_padding',
        ):
            return dataframe

        expected_rows = (
            int(schema['simulation_end_time_step'])
            - int(schema['simulation_start_time_step'])
            + 1
        )
        if len(dataframe) == expected_rows:
            return dataframe
        if len(dataframe) != expected_rows - 1 or dataframe.empty:
            raise ValueError(
                'terminal_observation_padding may add exactly one terminal state '
                f'after the available data; expected {expected_rows - 1} source rows '
                f'but read {len(dataframe)} from {filepath}.'
            )

        terminal = dataframe.iloc[-1].copy()
        # The padded row is a terminal observation, not an additional physical
        # interval. Calendar fields describe the next quarter-hour boundary.
        if {'month', 'hour', 'minutes', 'day_type'}.issubset(dataframe.columns):
            minutes = int(terminal['minutes']) + int(
                round(float(schema.get('seconds_per_time_step', 3600)) / 60.0)
            )
            hour_increment, terminal['minutes'] = divmod(minutes, 60)
            hour = int(terminal['hour']) + hour_increment
            day_increment, terminal['hour'] = divmod(hour, 24)
            if day_increment:
                terminal['day_type'] = (int(terminal['day_type']) % 7) + 1
                if int(terminal['month']) == 12:
                    terminal['month'] = 1

        # A vehicle whose countdown reaches one leaves at the boundary after
        # the final controlled interval. Make that transition observable to the
        # KPI layer without inventing a 2024 charging interval.
        if {
            'electric_vehicle_charger_state',
            'electric_vehicle_departure_time',
        }.issubset(dataframe.columns):
            state = pd.to_numeric(
                pd.Series([terminal['electric_vehicle_charger_state']]),
                errors='coerce',
            ).iloc[0]
            departure = pd.to_numeric(
                pd.Series([terminal['electric_vehicle_departure_time']]),
                errors='coerce',
            ).iloc[0]
            if state == 1 and np.isfinite(departure) and 0.0 <= float(departure) <= 1.0:
                terminal['electric_vehicle_charger_state'] = 3
                for column in (
                    'electric_vehicle_session_id',
                    'electric_vehicle_departure_time',
                    'electric_vehicle_required_soc_departure',
                    'electric_vehicle_current_soc',
                ):
                    if column in dataframe.columns:
                        terminal[column] = np.nan

        terminal_frame = pd.DataFrame(
            {
                column: pd.Series([terminal[column]], dtype=dtype)
                for column, dtype in dataframe.dtypes.items()
            }
        )
        return pd.concat(
            [dataframe, terminal_frame],
            ignore_index=True,
        )

    def _read_timeseries_dataframe(
        self,
        filepath: Union[str, os.PathLike],
        *,
        start_time_step: Optional[int] = None,
        end_time_step: Optional[int] = None,
        csv_dtypes: Optional[Mapping[str, Any]] = None,
    ) -> pd.DataFrame:
        if start_time_step is not None and end_time_step is not None and end_time_step < start_time_step:
            raise ValueError(
                f'end_time_step ({end_time_step}) must be >= start_time_step ({start_time_step}) '
                f'for source={filepath}.'
            )

        if self._file_format(filepath) == 'parquet':
            return self._read_parquet_timeseries_dataframe(
                filepath,
                start_time_step=start_time_step,
                end_time_step=end_time_step,
            )

        nrows = None if end_time_step is None else int(end_time_step) - int(start_time_step or 0) + 1

        if start_time_step is None or int(start_time_step) <= 0:
            return pd.read_csv(filepath, nrows=nrows, dtype=csv_dtypes)

        return pd.read_csv(filepath, skiprows=range(1, int(start_time_step) + 1), nrows=nrows, dtype=csv_dtypes)

    @staticmethod
    def _read_parquet_timeseries_dataframe(
        filepath: Union[str, os.PathLike],
        *,
        start_time_step: Optional[int] = None,
        end_time_step: Optional[int] = None,
    ) -> pd.DataFrame:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ImportError(
                "Reading Parquet CityLearn datasets requires pyarrow, an optional dependency of CityLearn. "
                'Install it with: pip install "citylearn[parquet]", or use CSV files in the schema.'
            ) from exc

        start = 0 if start_time_step is None else max(0, int(start_time_step))
        end = None if end_time_step is None else int(end_time_step)
        parquet_file = pq.ParquetFile(filepath)

        if start == 0 and end is None:
            return parquet_file.read().to_pandas()

        batches = []
        row_cursor = 0

        for batch in parquet_file.iter_batches(batch_size=65_536):
            batch_rows = batch.num_rows
            batch_start = row_cursor
            batch_end = row_cursor + batch_rows

            if batch_end <= start:
                row_cursor = batch_end
                continue

            if end is not None and batch_start > end:
                break

            local_start = max(0, start - batch_start)
            local_end = batch_rows if end is None else min(batch_rows, end + 1 - batch_start)

            if local_end > local_start:
                batches.append(batch.slice(local_start, local_end - local_start))

            row_cursor = batch_end

        if len(batches) == 0:
            schema = parquet_file.schema_arrow
            arrays = [pa.array([], type=field.type) for field in schema]
            return pa.Table.from_arrays(arrays, names=schema.names).to_pandas()

        return pa.Table.from_batches(batches).to_pandas()

    @staticmethod
    def _noise_seed(schema, label):
        payload = f"{schema.get('random_seed',0)}:{label}".encode()
        return int.from_bytes(hashlib.sha256(payload).digest()[:4], 'big')

    def _read_dataframe(self, filepath: Union[str, os.PathLike]) -> pd.DataFrame:
        if self._file_format(filepath) == 'parquet':
            return self._read_parquet_timeseries_dataframe(filepath)
        return pd.read_csv(filepath)

    def _load_shared_timeseries(
        self,
        constructor: Any,
        *,
        schema: Mapping[str, Any],
        filepath: Union[str, os.PathLike],
        expected_rows: int,
        window: Optional[MemberWindow],
        source_label: str,
        noise_std: float,
    ) -> Any:
        cacheable = float(noise_std or 0.0) == 0.0
        base_cache_key = (
            constructor.__name__,
            os.path.abspath(str(filepath)),
            int(schema['simulation_start_time_step']),
            int(schema['simulation_end_time_step']),
            int(expected_rows),
        )
        full_horizon_cache_key = (*base_cache_key, None)
        window_cache_key = (*base_cache_key, tuple(window) if window is not None else None)

        if cacheable:
            if full_horizon_cache_key in self._shared_timeseries_cache:
                return self._shared_timeseries_cache[full_horizon_cache_key]
            if window_cache_key in self._shared_timeseries_cache:
                return self._shared_timeseries_cache[window_cache_key]

        # A file that covers the whole simulation window is the same for every member window.
        full_horizon_source = window is None or (
            not self._is_member_window_file(schema, filepath, window)
            and self._timeseries_row_count(filepath)
            >= int(schema['simulation_start_time_step']) + int(expected_rows)
        )
        dataframe = self._read_member_timeseries(
            schema,
            filepath,
            expected_rows=expected_rows,
            window=window,
            source_label=source_label,
        )
        time_series = constructor(**self._dataframe_to_constructor_kwargs(dataframe), noise_std=noise_std,
            noise_seed=self._noise_seed(schema, source_label), noise_start_index=schema['simulation_start_time_step'])
        self._set_time_step_offset(time_series, schema['simulation_start_time_step'])

        if cacheable:
            cache_key = full_horizon_cache_key if full_horizon_source else window_cache_key
            self._shared_timeseries_cache[cache_key] = time_series

        return time_series

    @staticmethod
    def _collect_topology_events(schema: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        raw_events = schema.get('topology_events', []) if isinstance(schema, Mapping) else []
        events = [event for event in raw_events if isinstance(event, Mapping)]
        events.sort(
            key=lambda event: (
                int(event.get('time_step', 0)),
                str(event.get('id', '')),
            )
        )
        return events

    @staticmethod
    def _normalize_action_tokens(values: Any) -> List[str]:
        if values is None:
            return []
        if not isinstance(values, (list, tuple, set)):
            values = [values]
        return [str(value) for value in values]

    def _resolve_inactive_actions(
        self,
        index: int,
        building_schema: Mapping[str, Any],
        kwargs: Mapping[str, Any],
    ) -> List[str]:
        inactive_actions_override = kwargs.get('inactive_actions')
        if inactive_actions_override is not None:
            if isinstance(inactive_actions_override, list) and len(inactive_actions_override) > 0 and isinstance(inactive_actions_override[0], list):
                if index < len(inactive_actions_override):
                    inactive_actions_override = inactive_actions_override[index]
                else:
                    inactive_actions_override = []
            return self._normalize_action_tokens(inactive_actions_override)

        inactive_actions_schema = None if building_schema is None else building_schema.get('inactive_actions')
        return self._normalize_action_tokens(inactive_actions_schema)

    @staticmethod
    def _building_has_electrical_storage_asset(building: Building) -> bool:
        battery = getattr(building, 'electrical_storage', None)
        if battery is None:
            return False
        capacity = float(getattr(battery, 'capacity', 0.0) or 0.0)
        nominal_power = float(getattr(battery, 'nominal_power', 0.0) or 0.0)
        return capacity > 0.0 and nominal_power > 0.0

    def _declared_inactive_actions_for_building(self, building: Building) -> Set[str]:
        declared = getattr(building, '_declared_inactive_actions', None)
        if isinstance(declared, (set, list, tuple)):
            return {str(value) for value in declared}

        schema = self.env.schema if isinstance(getattr(self.env, 'schema', None), Mapping) else {}
        building_schema = (schema.get('buildings', {}) or {}).get(getattr(building, 'name', ''), {})
        return set(self._normalize_action_tokens((building_schema or {}).get('inactive_actions')))

    def _validate_static_action_asset_consistency(self, buildings: List[Building]) -> None:
        inconsistent: List[str] = []

        for building in buildings:
            action_enabled = bool(getattr(building, 'action_metadata', {}).get('electrical_storage', False))
            if not action_enabled:
                continue

            if self._building_has_electrical_storage_asset(building):
                continue

            if 'electrical_storage' in self._declared_inactive_actions_for_building(building):
                continue

            inconsistent.append(str(getattr(building, 'name', '<unknown>')))

        if inconsistent:
            joined = ', '.join(inconsistent)
            raise ValueError(
                'Schema/action inconsistency in static topology: electrical_storage action is active '
                f'for building(s) without electrical_storage asset declaration or positive capacity/power: {joined}. '
                "Fix by declaring electrical_storage for those buildings or adding 'electrical_storage' to each building's inactive_actions."
            )

    def _build_dynamic_member_windows(
        self,
        schema: Mapping[str, Any],
        expected_rows: int,
    ) -> Dict[str, MemberWindow]:
        """Active window of each member, in global dataset time steps.

        A window `(start, end)` holds the global time step of the member's first activation, from the
        `include` flag (0) or its first `add_member` event, and the end of that activation clipped to the
        simulation end, from its first later `remove_member` event. Topology-event time steps are global
        dataset rows, so the windows are global as well; `_read_member_timeseries` places them in the
        simulation window. Members that join again after leaving are recorded in
        `_dynamic_rejoining_members`.
        """

        windows: Dict[str, MemberWindow] = {}
        events = self._collect_topology_events(schema)
        buildings = schema.get('buildings', {}) if isinstance(schema, Mapping) else {}
        simulation_end = int(schema['simulation_start_time_step']) + int(expected_rows)

        for member_id, member_schema in buildings.items():
            include = parse_bool(
                (member_schema or {}).get('include', True),
                default=True,
                path=f'buildings.{member_id}.include',
            )
            active = bool(include)
            activations = [0] if active else []
            first_end = None

            for event in events:
                if event.get('target_member_id') != member_id:
                    continue
                operation = str(event.get('operation', '')).strip().lower()
                time_step = int(event.get('time_step', 0))

                if operation == 'add_member' and not active:
                    active = True
                    activations.append(time_step)
                elif operation == 'remove_member' and active:
                    active = False
                    if first_end is None:
                        first_end = time_step

            if len(activations) == 0:
                continue

            rejoins = len(activations) > 1
            if rejoins:
                self._dynamic_rejoining_members.add(str(member_id))

            start = max(0, int(activations[0]))
            end = simulation_end if first_end is None else min(int(first_end), simulation_end)
            windows[str(member_id)] = MemberWindow(start, max(start, end), rejoins)

        return windows

    def _build_dynamic_charger_windows(
        self,
        schema: Mapping[str, Any],
        member_windows: Mapping[str, MemberWindow],
        expected_rows: int,
    ) -> Dict[Tuple[str, str], MemberWindow]:
        windows: Dict[Tuple[str, str], MemberWindow] = {}
        events = self._collect_topology_events(schema)
        buildings = schema.get('buildings', {}) if isinstance(schema, Mapping) else {}

        for member_id, member_schema in buildings.items():
            member_window = member_windows.get(str(member_id))
            if member_window is None:
                continue

            base_start, base_end, rejoins = member_window
            chargers = (member_schema or {}).get('chargers', {}) or {}

            for charger_id in chargers.keys():
                start, end = int(base_start), int(base_end)

                for event in events:
                    if str(event.get('operation', '')).strip().lower() != 'remove_asset':
                        continue
                    if str(event.get('target_asset_type', '')).strip().lower() != 'charger':
                        continue
                    if event.get('target_member_id') != member_id:
                        continue
                    if event.get('target_asset_id') != charger_id:
                        continue
                    candidate = int(event.get('time_step', 0))
                    if candidate >= start:
                        end = min(end, candidate)
                        break

                windows[(str(member_id), str(charger_id))] = MemberWindow(start, max(start, end), rejoins)

        return windows

    def _read_member_timeseries(
        self,
        schema: Mapping[str, Any],
        filepath: Union[str, os.PathLike],
        *,
        expected_rows: int,
        window: Optional[MemberWindow],
        source_label: str,
        csv_dtypes: Optional[Mapping[str, Any]] = None,
    ) -> pd.DataFrame:
        """Read a member time series and align it with the simulation window.

        Outside dynamic topology, or for a source without a member window, this is the plain
        simulation-window read. In dynamic topology a member source is either:

        - a full-horizon file, with one row per dataset time step (as many rows as the dataset); or
        - a member-window file, shorter than the dataset, whose first row is the member's first
          activation, the time step of its `add_member` event.

        A full-horizon file is sliced to the simulation window like any other file. A member-window
        file is read from the row that corresponds to the later of the activation and the simulation
        start, and placed at that offset of the simulation window; its values are carried backwards
        before the activation and forwards after the member leaves, where the member is inactive. A
        member that joins again after leaving needs a full-horizon file, because a member-window file
        only covers its first activation.
        """

        if not self._dynamic_mode or window is None:
            return self._read_simulation_dataframe(schema, filepath, csv_dtypes=csv_dtypes)

        expected_rows = int(expected_rows)
        simulation_start = int(schema['simulation_start_time_step'])
        join, end, rejoins = window
        join, end = int(join), int(end)

        if not self._is_member_window_file(schema, filepath, window):
            dataframe = self._read_simulation_dataframe(schema, filepath, csv_dtypes=csv_dtypes)

            if len(dataframe) >= expected_rows:
                dataframe = dataframe.iloc[:expected_rows]
                index = dataframe.index
                if not (
                    isinstance(index, pd.RangeIndex)
                    and int(index.start) == 0
                    and int(index.step) == 1
                ):
                    dataframe = dataframe.reset_index(drop=True)

                return dataframe

            if len(dataframe) == 0:
                raise ValueError(
                    f'{source_label} has no rows in the simulation window in dynamic mode. '
                    f'Provide a full-horizon file or one that starts at the member\'s add_member time step.'
                )

            # A file that starts at row 0 but ends early, such as one for a member that leaves.
            return self._place_member_rows(dataframe, expected_rows=expected_rows, local_start=0)

        if rejoins:
            raise ValueError(
                f'{source_label} is shorter than the dataset, so it is read as starting at the member\'s '
                f'add_member time step ({join}), but the member joins again after leaving. Provide a '
                'full-horizon file, with one row per dataset time step, for a member that rejoins.'
            )

        first = max(join, simulation_start)
        last = min(end, simulation_start + expected_rows)

        if last <= first:
            # The member is never active in this simulation window. Its values are only read for
            # sizing and space estimation, so the nearest row of its file stands in for every step.
            row = 0 if first == join else max(0, self._timeseries_row_count(filepath) - 1)
            dataframe = self._read_timeseries_dataframe(
                filepath, start_time_step=row, end_time_step=row, csv_dtypes=csv_dtypes,
            )
            if len(dataframe) == 0:
                raise ValueError(f'{source_label} has 0 rows in dynamic mode.')

            return self._place_member_rows(dataframe, expected_rows=expected_rows, local_start=0)

        file_start = first - join
        rows = last - first
        dataframe = self._read_timeseries_dataframe(
            filepath,
            start_time_step=file_start,
            end_time_step=file_start + rows - 1,
            csv_dtypes=csv_dtypes,
        )

        if len(dataframe) == 0:
            raise ValueError(
                f'{source_label} has {self._timeseries_row_count(filepath)} rows. It is shorter than the '
                f'dataset, so its first row is the add_member time step ({join}), but it has no row for the '
                f'first active step {first} of this simulation window. Provide a full-horizon file.'
            )

        if len(dataframe) < rows:
            # As in CityLearn 3.6.0 the last row is carried forward, but no longer silently.
            warnings.warn(
                f'{source_label} has {self._timeseries_row_count(filepath)} rows. It is shorter than the '
                f'dataset, so its first row is the add_member time step ({join}), and it ends before the '
                f'member\'s active steps {first} to {last - 1} of this simulation window: its last row is '
                'repeated for the remaining steps. Provide the missing rows or a full-horizon file.',
                UserWarning,
                stacklevel=2,
            )

        return self._place_member_rows(
            dataframe, expected_rows=expected_rows, local_start=first - simulation_start,
        )

    def _is_member_window_file(
        self,
        schema: Mapping[str, Any],
        filepath: Union[str, os.PathLike],
        window: Optional[MemberWindow],
    ) -> bool:
        """True if a dynamic member source starts at the member's activation instead of dataset row 0."""

        return (
            self._dynamic_mode
            and window is not None
            and int(window[0]) > 0
            and self._timeseries_row_count(filepath) < self._dataset_row_count(schema)
        )

    @staticmethod
    def _place_member_rows(dataframe: pd.DataFrame, *, expected_rows: int, local_start: int) -> pd.DataFrame:
        """Place `dataframe` at `local_start` of a frame of `expected_rows`, carrying values to the edges."""

        local_start = max(0, min(int(local_start), int(expected_rows)))
        rows = min(len(dataframe), int(expected_rows) - local_start)
        aligned = pd.DataFrame(index=np.arange(expected_rows), columns=dataframe.columns)
        aligned.iloc[local_start:local_start + rows, :] = dataframe.iloc[:rows].to_numpy()
        for column in aligned.columns:
            with pd.option_context('future.no_silent_downcasting', True):
                aligned[column] = aligned[column].ffill().bfill()
        return aligned.reset_index(drop=True)

    def _charger_soc_units(self, filepath: Union[str, os.PathLike]) -> Dict[str, str]:
        """SOC unit of each SOC column of a charger file, decided from all its rows, cached by path."""

        from citylearn.data import ChargerSimulation

        key = os.path.abspath(str(filepath))

        if key not in self._charger_soc_unit_cache:
            columns = ChargerSimulation._SOC_COLUMNS

            if self._file_format(filepath) == 'parquet':
                import pyarrow.parquet as pq

                names = set(pq.ParquetFile(filepath).schema_arrow.names)
                dataframe = pq.read_table(filepath, columns=[c for c in columns if c in names]).to_pandas()
            else:
                dataframe = pd.read_csv(filepath, usecols=lambda c: c in columns)

            units = {
                c: ChargerSimulation._soc_series_unit(dataframe[c].to_numpy()) for c in columns if c in dataframe.columns
            }

            for column, unit in units.items():
                if unit != 'percent':
                    continue

                fractions = ChargerSimulation._soc_fraction_values_in_percent(dataframe[column].to_numpy())

                if fractions.size > 0:
                    warnings.warn(
                        f"Column {column!r} of {filepath} is read as percent because it has values above 1, "
                        f"but {fractions.size} of its values lie between 0 and 1 (e.g. {fractions[0]:g}), "
                        f"which become {fractions[0] / 100.0:g}. If the column holds fractions, fix the values "
                        "above 1 or set the charger's soc_unit to 'fraction'.",
                        UserWarning,
                        stacklevel=2,
                    )

            self._charger_soc_unit_cache[key] = units

        return self._charger_soc_unit_cache[key]

    def _timeseries_row_count(self, filepath: Union[str, os.PathLike]) -> int:
        """Number of data rows in a CSV or Parquet time series file, cached by path."""

        key = os.path.abspath(str(filepath))

        if key not in self._timeseries_row_counts:
            if self._file_format(filepath) == 'parquet':
                import pyarrow.parquet as pq

                count = int(pq.ParquetFile(filepath).metadata.num_rows)

            else:
                count = 0
                last = b''

                with open(filepath, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        count += chunk.count(b'\n')
                        last = chunk

                # Count a last line without a trailing newline, then drop the header.
                if last and not last.endswith(b'\n'):
                    count += 1

                count = max(0, count - 1)

            self._timeseries_row_counts[key] = count

        return self._timeseries_row_counts[key]

    def _dataset_row_count(self, schema: Mapping[str, Any]) -> int:
        """Number of dataset time steps: the longest building energy simulation file of the schema."""

        if self._dynamic_dataset_rows is None:
            counts = []

            for member_schema in (schema.get('buildings', {}) or {}).values():
                filename = (member_schema or {}).get('energy_simulation')
                if not filename:
                    continue
                filepath = os.path.join(schema['root_directory'], filename)
                if os.path.isfile(filepath):
                    counts.append(self._timeseries_row_count(filepath))

            self._dynamic_dataset_rows = max(counts) if counts else int(schema['simulation_end_time_step']) + 1

        return self._dynamic_dataset_rows
