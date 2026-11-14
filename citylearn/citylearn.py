from collections import defaultdict
from copy import deepcopy
from enum import Enum
import hashlib
import importlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Mapping, Tuple, Union
from gymnasium import Env, spaces
import datetime
import numpy as np
import pandas as pd
import random
from citylearn.base import Environment, EpisodeTracker
from citylearn.building import Building, DynamicsBuilding
from citylearn.cost_function import CostFunction
from citylearn.data import CarbonIntensity, DataSet, OfflineDataError, ChargerSimulation, EnergySimulation, LogisticRegressionOccupantParameters, Pricing, Weather
from citylearn.electric_vehicle import ElectricVehicle
from citylearn.energy_model import Battery, DeferrableAppliance, PV
from citylearn.exporter import EpisodeExporter
from citylearn.internal.market_history import MarketSettlementHistory
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.internal.loading import CityLearnLoadingService
from citylearn.internal.baseline import CityLearnBusinessAsUsualBaselineService
from citylearn.internal.physics_invariants import CityLearnPhysicsInvariantService
from citylearn.internal.provenance import CityLearnProvenanceService
from citylearn.internal.runtime import CityLearnRuntimeService
from citylearn.internal.entity_interface import CityLearnEntityInterfaceService
from citylearn.internal.topology import CityLearnTopologyService
from citylearn.internal.demand_response import CityLearnDemandResponseService
from citylearn.internal.robustness import CityLearnRobustnessService
from citylearn.utilities import parse_bool
from citylearn.reward_function import (
    MultiBuildingRewardFunction,
    RewardFunction,
)
from citylearn.utilities import FileHandler

if TYPE_CHECKING:
    from citylearn.agents.base import Agent

LOGGER = logging.getLogger()
logging.getLogger('matplotlib.font_manager').disabled = True
logging.getLogger('matplotlib.pyplot').disabled = True

class EvaluationCondition(Enum):
    """Evaluation conditions.
    
    Used in `citylearn.CityLearnEnv.calculate` method.
    """

    # general (soft private)
    _DEFAULT = ''
    _STORAGE_SUFFIX = '_without_storage'
    _PARTIAL_LOAD_SUFFIX = '_and_partial_load'
    _PV_SUFFIX = '_and_pv'

    # Building type
    WITH_STORAGE_AND_PV = _DEFAULT
    WITHOUT_STORAGE_BUT_WITH_PV = _STORAGE_SUFFIX
    WITHOUT_STORAGE_AND_PV = WITHOUT_STORAGE_BUT_WITH_PV +_PV_SUFFIX

    # DynamicsBuilding type
    WITH_STORAGE_AND_PARTIAL_LOAD_AND_PV = WITH_STORAGE_AND_PV
    WITHOUT_STORAGE_BUT_WITH_PARTIAL_LOAD_AND_PV = WITHOUT_STORAGE_BUT_WITH_PV
    WITHOUT_STORAGE_AND_PARTIAL_LOAD_BUT_WITH_PV = WITHOUT_STORAGE_BUT_WITH_PARTIAL_LOAD_AND_PV + _PARTIAL_LOAD_SUFFIX
    WITHOUT_STORAGE_AND_PARTIAL_LOAD_AND_PV = WITHOUT_STORAGE_AND_PARTIAL_LOAD_BUT_WITH_PV + _PV_SUFFIX

class CityLearnEnv(Environment, Env):
    r"""CityLearn nvironment class.

    Parameters
    ----------
    schema: Union[str, Path, Mapping[str, Any]]
        Name of CityLearn data set, filepath to JSON representation or :code:`dict` object of a CityLearn schema.
        Call :py:meth:`citylearn.data.DataSet.get_names` for list of available CityLearn data sets.
    root_directory: Union[str, Path]
        Absolute path to directory that contains the data files including the schema.
    buildings: Union[List[Building], List[str], List[int]], optional
        Buildings to include in environment. If list of :code:`citylearn.building.Building` is provided, will override :code:`buildings` definition in schema.
        If list of :str: is provided will include only schema :code:`buildings` keys that are contained in provided list of :code:`str`.
        If list of :int: is provided will include only schema :code:`buildings` whose index is contained in provided list of :code:`int`.
    simulation_start_time_step: int, optional
        Time step to start reading data files contents.
    simulation_end_time_step: int, optional
        Time step to end reading from data files contents.
    episode_time_steps: Union[int, List[Tuple[int, int]]], optional
        If type is `int`, it is the number of time steps in an episode. If type is `List[Tuple[int, int]]]` is provided, 
        it is a list of episode start and end time steps between `simulation_start_time_step` and `simulation_end_time_step`. 
        Defaults to (`simulation_end_time_step` - `simulation_start_time_step`) + 1. Will ignore `rolling_episode_split` if `episode_splits` is of type `List[Tuple[int, int]]]`.
    rolling_episode_split: bool, default: False
        True if episode sequences are split such that each time step is a candidate for `episode_start_time_step` otherwise, False to split episodes in steps of `episode_time_steps`.
    random_episode_split: bool, default: False
        True if episode splits are to be selected at random during training otherwise, False to select sequentially.
    seconds_per_time_step: float
        Number of seconds in 1 `time_step` and must be set to >= 1.
    reward_function: Union[RewardFunction, str], optional
        Reward function class instance or path to function class e.g. 'citylearn.reward_function.IndependentSACReward'.
        If provided, will override :code:`reward_function` definition in schema.
    reward_function_kwargs: Mapping[str, Any], optional
        Parameters to be parsed to :py:attr:`reward_function` at intialization.
    central_agent: bool, optional
        Expect 1 central agent to control all buildings.
    shared_observations: List[str], optional
        Names of common observations across all buildings i.e. observations that have the same value irrespective of the building.
    active_observations: Union[List[str], List[List[str]]], optional
        List of observations to be made available in the buildings. Can be specified for all buildings in a :code:`List[str]` or for  
        each building independently in a :code:`List[List[str]]`. Will override the observations defined in the :code:`schema`.
    inactive_observations: Union[List[str], List[List[str]]], optional
        List of observations to be made unavailable in the buildings. Can be specified for all buildings in a :code:`List[str]` or for  
        each building independently in a :code:`List[List[str]]`. Will override the observations defined in the :code:`schema`.
    active_actions: Union[List[str], List[List[str]]], optional
        List of actions to be made available in the buildings. Can be specified for all buildings in a :code:`List[str]` or for  
        each building independently in a :code:`List[List[str]]`. Will override the actions defined in the :code:`schema`.
    inactive_actions: Union[List[str], List[List[str]]], optional
        List of actions to be made unavailable in the buildings. Can be specified for all buildings in a :code:`List[str]` or for  
        each building independently in a :code:`List[List[str]]`. Will override the actions defined in the :code:`schema`.
    simulate_power_outage: Union[bool, List[bool]]
        Whether to simulate power outages. Can be specified for all buildings as single :code:`bool` or for  
        each building independently in a :code:`List[bool]`. Will override power outage defined in the :code:`schema`.
    solar_generation: Union[bool, List[bool]]
        Wehther to allow solar generation. Can be specified for all buildings as single :code:`bool` or for  
        each building independently in a :code:`List[bool]`. Will override :code:`pv` defined in the :code:`schema`.
    random_seed: int, optional
        Pseudorandom number generator seed for repeatable results.
    offline: bool, default: False
        If True, disables all network fallbacks for datasets and misc sizing data. Initialization fails with a clear
        error when required files are not available locally.

    Other Parameters
    ----------------
    render_directory: Union[str, Path], optional
        Base directory where rendering and export artifacts are stored. Relative paths are resolved from the project root.
    render_directory_name: str, optional
        Folder name created inside the project root for rendering and export artifacts when ``render_directory`` is not provided.
        Defaults to ``render_logs``.
    render_session_name: str, optional
        Name of the subfolder created under ``render_directory``/``render_directory_name`` for export artifacts. When omitted,
        a timestamp is used.
    render_mode: str, optional
        Rendering strategy. Accepted values are ``'none'`` (default), ``'during'`` for streaming exports each step, and
        ``'end'`` for exports performed at episode completion while still allowing manual snapshots via :meth:`render`.
    export_kpis_on_episode_end: bool, optional
        Whether to automatically export ``exported_kpis.csv`` when an episode terminates.
        If not provided, defaults to the effective rendering setting (enabled when rendering is enabled).
    export_only_final_episode: bool, optional
        Whether automatic exports should run only on the final planned episode. Defaults to ``True``.
    ev_departure_within_tolerance: float, optional
        Symmetric SOC target accuracy tolerance used by EV departure within-tolerance KPIs. Defaults to ``0.05``.
    ev_departure_service_tolerance: float, optional
        Lower SOC service tolerance used by EV departure minimum-acceptable KPIs. Defaults to ``0.05``.
    energy_provenance: bool, optional
        Whether to keep the per-step electricity provenance ledger (``*_energy_provenance_*`` KPIs and
        provenance audits). Defaults to ``True``. Disabling it does not change any simulated quantity and
        makes ``step()`` substantially faster, e.g. for training runs that do not report provenance KPIs.
    **kwargs : dict
        Other keyword arguments used to initialize super classes.

    Notes
    -----
    Parameters passed to `citylearn.citylearn.CityLearnEnv.__init__` that are also defined in `schema` will override their `schema` definition.
    """

    DEFAULT_RENDER_START_DATE = datetime.date(2024, 1, 1)

    def __init__(self,
        schema: Union[str, Path, Mapping[str, Any]], root_directory: Union[str, Path] = None, buildings: Union[List[Building], List[str], List[int]] = None,
        electric_vehicles: Union[List[ElectricVehicle], List[str], List[int]] = None,
        simulation_start_time_step: int = None, simulation_end_time_step: int = None, episode_time_steps: Union[int, List[Tuple[int, int]]] = None, rolling_episode_split: bool = None,
        random_episode_split: bool = None, seconds_per_time_step: float = None, reward_function: Union[RewardFunction, str] = None, reward_function_kwargs: Mapping[str, Any] = None,
        central_agent: bool = None, shared_observations: List[str] = None, active_observations: Union[List[str], List[List[str]]] = None,
        inactive_observations: Union[List[str], List[List[str]]] = None, active_actions: Union[List[str], List[List[str]]] = None,
        inactive_actions: Union[List[str], List[List[str]]] = None, simulate_power_outage: bool = None, solar_generation: bool = None, random_seed: int = None, offline: bool = None, time_step_ratio: int = None,
        interface: str = None,
        topology_mode: str = None,
        start_date: Union[str, datetime.date] = None, render_session_name: str = None, render_mode: str = 'none',
        export_kpis_on_episode_end: bool = None, **kwargs: Any
    ):
        render_directory = kwargs.pop('render_directory', None)
        render_directory_name = kwargs.pop('render_directory_name', 'render_logs')
        render_flag = kwargs.pop('render', None)
        render_file_format = kwargs.pop('render_file_format', None)
        render_chunk_size = kwargs.pop('render_chunk_size', None)
        export_only_final_episode = kwargs.pop('export_only_final_episode', None)
        kw_export_kpis_on_episode_end = kwargs.pop('export_kpis_on_episode_end', None)
        if kw_export_kpis_on_episode_end is not None and export_kpis_on_episode_end is None:
            export_kpis_on_episode_end = kw_export_kpis_on_episode_end
        debug_timing = kwargs.pop('debug_timing', None)
        check_observation_limits = kwargs.pop('check_observation_limits', None)
        physics_invariant_checks = kwargs.pop('physics_invariant_checks', None)
        energy_provenance = kwargs.pop('energy_provenance', None)
        metrics_log_interval = kwargs.pop('metrics_log_interval', None)
        ev_departure_within_tolerance = kwargs.pop('ev_departure_within_tolerance', None)
        ev_departure_service_tolerance = kwargs.pop('ev_departure_service_tolerance', None)
        kw_render_mode = kwargs.pop('render_mode', None)
        requested_render_mode = render_mode if kw_render_mode is None else kw_render_mode
        requested_render_mode = 'none' if requested_render_mode is None else str(requested_render_mode).lower()
        kw_render_session_name = kwargs.pop('render_session_name', None)
        if kw_render_session_name is not None:
            render_session_name = kw_render_session_name if render_session_name is None else render_session_name
        self.offline = offline
        self.schema = schema
        schema_interface = self.schema.get('interface') if isinstance(self.schema, dict) else None
        self.interface = interface if interface is not None else schema_interface
        schema_topology_mode = self.schema.get('topology_mode') if isinstance(self.schema, dict) else None
        self.topology_mode = topology_mode if topology_mode is not None else schema_topology_mode
        self.community_market_enabled = False
        self.community_market_sell_ratio = 0.8
        self.community_market_grid_export_price = 0.0
        self.community_market_import_member_weights: Mapping[str, float] = {}
        self.community_market_kpi_local_traded_enabled = True
        self.community_market_kpi_self_consumption_enabled = True
        self._last_community_market_settlement = []
        self._community_market_settlement_history = MarketSettlementHistory()
        self._configure_community_market()
        schema_start_date = self.schema.get('start_date') if isinstance(self.schema, dict) else None
        schema_render_mode = self.schema.get('render_mode') if isinstance(self.schema, dict) else None
        schema_render_file_format = self.schema.get('render_file_format') if isinstance(self.schema, dict) else None
        schema_render_chunk_size = self.schema.get('render_chunk_size') if isinstance(self.schema, dict) else None
        schema_export_kpis = self.schema.get('export_kpis_on_episode_end') if isinstance(self.schema, dict) else None
        schema_export_only_final_episode = self.schema.get('export_only_final_episode') if isinstance(self.schema, dict) else None
        if schema_export_kpis is not None and export_kpis_on_episode_end is None:
            export_kpis_on_episode_end = parse_bool(
                schema_export_kpis,
                default=False,
                path='export_kpis_on_episode_end',
            )
        if schema_export_only_final_episode is not None and export_only_final_episode is None:
            export_only_final_episode = parse_bool(
                schema_export_only_final_episode,
                default=True,
                path='export_only_final_episode',
            )
        if schema_render_mode is not None:
            requested_render_mode = str(schema_render_mode).lower()
        if requested_render_mode not in {'none', 'during', 'end'}:
            raise ValueError("render_mode must be one of {'none', 'during', 'end'}.")
        self.render_mode = requested_render_mode
        requested_render_file_format = render_file_format if render_file_format is not None else schema_render_file_format
        requested_render_file_format = 'csv' if requested_render_file_format is None else str(requested_render_file_format).strip().lower()
        if requested_render_file_format not in {'csv', 'parquet'}:
            raise ValueError("render_file_format must be one of {'csv', 'parquet'}.")
        self.render_file_format = requested_render_file_format
        requested_render_chunk_size = render_chunk_size if render_chunk_size is not None else schema_render_chunk_size
        if requested_render_chunk_size is None:
            requested_render_chunk_size = 50_000 if requested_render_file_format == 'parquet' else 100_000
        self.render_chunk_size = max(int(requested_render_chunk_size), 1)
        self._buffer_render = False
        self._defer_render_flush = False
        self._render_buffer = defaultdict(list)
        self.debug_timing = parse_bool(
            self.schema.get('debug_timing', False) if debug_timing is None else debug_timing,
            default=False,
            path='debug_timing',
        )
        self.check_observation_limits = parse_bool(
            self.schema.get('check_observation_limits', False) if check_observation_limits is None else check_observation_limits,
            default=False,
            path='check_observation_limits',
        )
        self.physics_invariant_checks = parse_bool(
            self.schema.get('physics_invariant_checks', False) if physics_invariant_checks is None else physics_invariant_checks,
            default=False,
            path='physics_invariant_checks',
        )
        self.energy_provenance = parse_bool(
            self.schema.get('energy_provenance', True) if energy_provenance is None else energy_provenance,
            default=True,
            path='energy_provenance',
        )
        self.metrics_log_interval = int(self.schema.get('metrics_log_interval', 0) if metrics_log_interval is None else metrics_log_interval)
        self.ev_departure_within_tolerance = self._parse_non_negative_float(
            self.schema.get('ev_departure_within_tolerance', CityLearnKPIService.EV_DEPARTURE_WITHIN_TOLERANCE_DEFAULT)
            if ev_departure_within_tolerance is None else ev_departure_within_tolerance,
            default=CityLearnKPIService.EV_DEPARTURE_WITHIN_TOLERANCE_DEFAULT,
            path='ev_departure_within_tolerance',
        )
        self.ev_departure_service_tolerance = self._parse_non_negative_float(
            self.schema.get('ev_departure_service_tolerance', CityLearnKPIService.EV_DEPARTURE_SERVICE_TOLERANCE_DEFAULT)
            if ev_departure_service_tolerance is None else ev_departure_service_tolerance,
            default=CityLearnKPIService.EV_DEPARTURE_SERVICE_TOLERANCE_DEFAULT,
            path='ev_departure_service_tolerance',
        )
        self._observations_cache: List[List[float]] = None
        self._observations_cache_time_step: int = -1
        self._render_origin_overridden = start_date is not None
        self._render_start_date = self._parse_render_start_date(start_date if start_date is not None else schema_start_date)
        self.previous_month = None
        self.current_day = self._render_start_date.day
        self.year = self._render_start_date.year
        self._final_kpis_exported = False
        self._final_export_episode_index = None
        self.__rewards = None
        self.buildings = []
        self.random_seed = self.schema.get('random_seed', None) if random_seed is None else random_seed
        schema_render_session = self.schema.get('render_session_name') if isinstance(self.schema, dict) else None
        self.render_session_name = render_session_name if render_session_name is not None else schema_render_session
        if self.render_session_name is not None:
            self.render_session_name = str(self.render_session_name).strip()
            if self.render_session_name == '':
                self.render_session_name = None
            elif Path(self.render_session_name).is_absolute():
                raise ValueError('render_session_name must be a relative path. Use render_directory to choose an absolute location.')
            elif '..' in Path(self.render_session_name).parts:
                raise ValueError('render_session_name cannot contain parent directory references (“..”).')
        # The business-as-usual sidecar is rebuilt from `schema`, which these overrides do not
        # modify, so it must re-apply them to simulate the same devices, PV and outages.
        self._constructor_overrides = deepcopy({
            'active_observations': active_observations,
            'inactive_observations': inactive_observations,
            'active_actions': active_actions,
            'inactive_actions': inactive_actions,
            'simulate_power_outage': simulate_power_outage,
            'solar_generation': solar_generation,
        })
        self._loading_service = CityLearnLoadingService(self)
        self._runtime_service = CityLearnRuntimeService(self)
        self._kpi_service = CityLearnKPIService(self)
        self._business_as_usual_baseline_service = CityLearnBusinessAsUsualBaselineService(self)
        self._physics_invariant_service = CityLearnPhysicsInvariantService(self)
        self._provenance_service = CityLearnProvenanceService(self)
        self._entity_service = CityLearnEntityInterfaceService(self)
        self._topology_service = CityLearnTopologyService(self)
        self._demand_response_service = CityLearnDemandResponseService(self)
        self._robustness_service = CityLearnRobustnessService(self)
        root_directory, buildings, electric_vehicles, episode_time_steps, rolling_episode_split, random_episode_split, \
            seconds_per_time_step, reward_function, central_agent, shared_observations, episode_tracker = self._load(
                deepcopy(self.schema),
                root_directory=root_directory,
                buildings=buildings,
                electric_vehicles=electric_vehicles,
                simulation_start_time_step=simulation_start_time_step,
                simulation_end_time_step=simulation_end_time_step,
                episode_time_steps=episode_time_steps,
                rolling_episode_split=rolling_episode_split,
                random_episode_split=random_episode_split,
                seconds_per_time_step=seconds_per_time_step,
                time_step_ratio=time_step_ratio,
                reward_function=reward_function,
                reward_function_kwargs=reward_function_kwargs,
                central_agent=central_agent,
                shared_observations=shared_observations,
                active_observations=active_observations,
                inactive_observations=inactive_observations,
                active_actions=active_actions,
                inactive_actions=inactive_actions,
                simulate_power_outage=simulate_power_outage,
                solar_generation=solar_generation,
                random_seed=self.random_seed,
            )
        self.root_directory = root_directory
        self._all_buildings = list(buildings)
        self._all_electric_vehicles = list(electric_vehicles)
        if self.topology_mode == 'dynamic':
            self._topology_service.initialize(self._all_buildings, self._all_electric_vehicles)
            self.buildings = list(self._all_buildings)
            self.electric_vehicles = list(self._all_electric_vehicles)
        else:
            self.buildings = buildings
            self.electric_vehicles = electric_vehicles
        self._demand_response_service.initialize()
        self._robustness_service.initialize()
        reference_buildings = self.buildings if len(self.buildings) > 0 else self._all_buildings
        get_time_step_ratio = reference_buildings[0].time_step_ratio if len(reference_buildings) > 0 else 1.0
        self.time_step_ratio = get_time_step_ratio

        # now call super class initialization and set episode tracker now that buildings are set
        super().__init__(seconds_per_time_step=seconds_per_time_step, random_seed=self.random_seed, episode_tracker=episode_tracker, time_step_ratio=self.time_step_ratio)

        # set other class variables
        self.episode_time_steps = episode_time_steps
        self.rolling_episode_split = rolling_episode_split
        self.random_episode_split = random_episode_split
        self.central_agent = central_agent
        self.shared_observations = shared_observations

        # set reward function
        self.reward_function = reward_function
        self._refresh_action_cache()

        # rendering switch: schema['render'] overrides explicit flag, otherwise rely on render_mode defaults
        schema_render = self.schema.get('render', None) if isinstance(self.schema, dict) else None
        if schema_render is not None:
            render_enabled_flag = parse_bool(schema_render, default=False, path='render')
        elif render_flag is not None:
            render_enabled_flag = parse_bool(render_flag, default=False, path='render')
        else:
            render_enabled_flag = self.render_mode in {'during', 'end'}

        self.render_enabled = render_enabled_flag
        if export_kpis_on_episode_end is None:
            export_kpis_on_episode_end = self.render_enabled
        else:
            export_kpis_on_episode_end = parse_bool(
                export_kpis_on_episode_end,
                default=self.render_enabled,
                path='export_kpis_on_episode_end',
            )
        self.export_kpis_on_episode_end = export_kpis_on_episode_end
        self.export_only_final_episode = True if export_only_final_episode is None else parse_bool(
            export_only_final_episode,
            default=True,
            path='export_only_final_episode',
        )

        # reset environment and initializes episode time steps
        self.reset()
        from citylearn.internal.temporal import input_changes
        if input_changes(self._input_snapshot):
            raise RuntimeError('Input files changed during environment construction')

        # reset episode tracker to start after initializing episode time steps during reset
        self.episode_tracker.reset_episode_index()

        # set reward metadata
        self.reward_function.env_metadata = self.get_metadata()

        # reward history tracker
        self.__episode_rewards = []

        # reward history tracker

        if self.root_directory is None:
            self.root_directory = os.path.dirname(os.path.abspath(__file__))

        project_root = Path(__file__).resolve().parents[1]
        render_directory_name = render_directory_name or 'render_logs'

        if render_directory is not None:
            render_root = Path(render_directory).expanduser()
            if not render_root.is_absolute():
                render_root = project_root / render_root
        else:
            render_root = project_root / render_directory_name

        self.render_output_root = render_root.expanduser().resolve()
        self._render_timestamp = None
        self._render_directory_path = None
        self._render_dir_initialized = False
        self.new_folder_path = None
        self._render_start_datetime = None
        self._episode_exporter = EpisodeExporter(self)

        if self.render_enabled:
            self._ensure_render_output_dir(ensure_exists=False)

    @property
    def render_start_date(self) -> datetime.date:
        """Date used as the origin for rendered timestamps."""

        return self._render_start_date

    @property
    def schema(self) -> Mapping[str, Any]:
        """`dict` object of CityLearn schema."""

        return self.__schema

    @property
    def offline(self) -> bool:
        """Whether network access should be disabled for dataset/misc lookups."""

        return self.__offline

    @property
    def render_enabled(self) -> bool:
        """Whether environment rendering/logging is enabled."""

        return getattr(self, '_CityLearnEnv__render_enabled', False)

    @property
    def export_kpis_on_episode_end(self) -> bool:
        """Whether KPIs are exported automatically when an episode terminates."""

        return getattr(self, '_CityLearnEnv__export_kpis_on_episode_end', False)

    @property
    def export_only_final_episode(self) -> bool:
        """Whether automatic exports are limited to the final planned episode."""

        return getattr(self, '_CityLearnEnv__export_only_final_episode', True)

    @property
    def root_directory(self) -> Union[str, Path]:
        """Absolute path to directory that contains the data files including the schema."""

        return self.__root_directory

    @property
    def buildings(self) -> List[Building]:
        """Buildings in CityLearn environment."""

        return self.__buildings

    @property
    def electric_vehicles(self) -> List[ElectricVehicle]:
        """Electric Vehicles in CityLearn environment."""

        return self.__electric_vehicles

    @property
    def time_steps(self) -> int:
        """Number of time steps in current episode split."""

        return self.episode_tracker.episode_time_steps

    @property
    def episode_time_steps(self) -> Union[int, List[Tuple[int, int]]]:
        """If type is `int`, it is the number of time steps in an episode. If type is `List[Tuple[int, int]]]` is provided, it is a list of 
        episode start and end time steps between `simulation_start_time_step` and `simulation_end_time_step`. Defaults to (`simulation_end_time_step` 
        - `simulation_start_time_step`) + 1. Will ignore `rolling_episode_split` if `episode_splits` is of type `List[Tuple[int, int]]]`."""

        return self.__episode_time_steps

    @property
    def rolling_episode_split(self) -> bool:
        """True if episode sequences are split such that each time step is a candidate for `episode_start_time_step` otherwise, 
        False to split episodes in steps of `episode_time_steps`."""

        return self.__rolling_episode_split

    @property
    def random_episode_split(self) -> bool:
        """True if episode splits are to be selected at random during training otherwise, False to select sequentially."""

        return self.__random_episode_split

    @property
    def episode(self) -> int:
        """Current episode index."""

        return self.episode_tracker.episode

    @property
    def reward_function(self) -> RewardFunction:
        """Reward function class instance."""

        return self.__reward_function

    @property
    def rewards(self) -> List[List[float]]:
        """Reward time series"""

        return self.__rewards

    @property
    def episode_rewards(self) -> List[Mapping[str, Union[float, List[float]]]]:
        """Reward summary statistics for elapsed episodes."""

        return self.__episode_rewards

    @property
    def central_agent(self) -> bool:
        """Expect 1 central agent to control all buildings."""

        return self.__central_agent

    @property
    def shared_observations(self) -> List[str]:
        """Names of common observations across all buildings i.e. observations that have the same value irrespective of the building."""

        return self.__shared_observations

    @property
    def interface(self) -> str:
        """Environment I/O interface mode."""

        return self.__interface

    @property
    def topology_mode(self) -> str:
        """Topology execution mode."""

        return self.__topology_mode

    @property
    def topology_version(self) -> int:
        """Incrementing topology mutation version."""

        if getattr(self, '_topology_service', None) is None or self.topology_mode != 'dynamic':
            return 0

        return self._topology_service.topology_version

    @property
    def topology_event_log(self) -> List[Mapping[str, Any]]:
        """Applied topology event trace for the current episode."""

        if getattr(self, '_topology_service', None) is None or self.topology_mode != 'dynamic':
            return []

        return [dict(entry) for entry in self._topology_service.event_log]

    @property
    def topology_member_lifecycle(self) -> Mapping[str, Mapping[str, Any]]:
        """Member lifecycle metadata keyed by member id."""

        if getattr(self, '_topology_service', None) is None or self.topology_mode != 'dynamic':
            return {}

        return self._topology_service.member_lifecycle

    @property
    def terminated(self) -> bool:
        """Check if simulation has reached completion."""

        return self.time_step >= self.time_steps - 1

    @property
    def truncated(self) -> bool:
        """Check if episode truncates due to a time limit or a reason that is not defined as part of the task MDP."""

        return False

    @property
    def observation_space(self) -> Union[List[spaces.Box], spaces.Dict]:
        """Controller(s) observation spaces.

        Returns
        -------
        observation_space : List[spaces.Box]
            List of agent(s) observation spaces.
        
        Notes
        -----
        If `central_agent` is True, a list of 1 `spaces.Box` object is returned that contains all buildings' limits with the limits in the same order as `buildings`. 
        The `shared_observations` limits are only included in the first building's limits. If `central_agent` is False, a list of `space.Box` objects as
        many as `buildings` is returned in the same order as `buildings`.
        """

        if self.interface == 'entity':
            return self._robustness_service.adjust_observation_space(self._entity_service.observation_space)

        return self._robustness_service.adjust_observation_space(self._get_flat_observation_space())

    def _get_flat_observation_space(self) -> List[spaces.Box]:
        if self.central_agent:
            low_limit = []
            high_limit = []
            shared_observations = []

            for i, b in enumerate(self.buildings):
                for l, h, s in zip(b.observation_space.low, b.observation_space.high, b.active_observations):
                    if i == 0 or s not in self.shared_observations or s not in shared_observations:
                        low_limit.append(l)
                        high_limit.append(h)

                    else:
                        pass

                    if s in self.shared_observations and s not in shared_observations:
                        shared_observations.append(s)

                    else:
                        pass

            observation_space = [
                spaces.Box(
                    low=np.asarray(low_limit, dtype=np.float32),
                    high=np.asarray(high_limit, dtype=np.float32),
                    dtype=np.float32,
                )
            ]

        else:
            observation_space = [b.observation_space for b in self.buildings]

        return observation_space

    @property
    def action_space(self) -> Union[List[spaces.Box], spaces.Dict]:
        """Controller(s) action spaces.

        Returns
        -------
        action_space : List[spaces.Box]
            List of agent(s) action spaces.
        
        Notes
        -----
        If `central_agent` is True, a list of 1 `spaces.Box` object is returned that contains all buildings' limits with the limits in the same order as `buildings`. 
        If `central_agent` is False, a list of `space.Box` objects as many as `buildings` is returned in the same order as `buildings`.
        """

        if self.interface == 'entity':
            return self._entity_service.action_space

        return self._get_flat_action_space()

    def _get_flat_action_space(self) -> List[spaces.Box]:
        if self.central_agent:
            low_limit = [v for b in self.buildings for v in b.action_space.low]
            high_limit = [v for b in self.buildings for v in b.action_space.high]
            action_space = [
                spaces.Box(
                    low=np.asarray(low_limit, dtype=np.float32),
                    high=np.asarray(high_limit, dtype=np.float32),
                    dtype=np.float32,
                )
            ]
        else:
            action_space = [b.action_space for b in self.buildings]

        return action_space

    @property
    def observations(self) -> Union[List[List[float]], Mapping[str, Any]]:
        """Observations at current time step.
        
        Notes
        -----
        If `central_agent` is True, a list of 1 sublist containing all building observation values is returned in the same order as `buildings`. 
        The `shared_observations` values are only included in the first building's observation values. If `central_agent` is False, a list of sublists 
        is returned where each sublist is a list of 1 building's observation values and the sublist in the same order as `buildings`.
        """
        if self.interface == 'entity':
            return self._robustness_service.apply_observations(self._entity_service.observation_payload())

        if self._observations_cache is not None and self._observations_cache_time_step == self.time_step:
            return self._observations_cache

        building_observations = [
            b.observations(
                normalize=False,
                periodic_normalization=False,
                check_limits=self.check_observation_limits,
            ) for b in self.buildings
        ]

        if self.central_agent:
            observations = []
            shared_observations = set()
            shared_observation_names = self._shared_observations_set

            for i, b_observations in enumerate(building_observations):
                for k, v in b_observations.items():
                    if i == 0 or k not in shared_observation_names or k not in shared_observations:
                        observations.append(v)

                    if k in shared_observation_names:
                        shared_observations.add(k)

            observations = [observations]

        else:
            observations = [list(o.values()) for o in building_observations]

        self._observations_cache = observations
        self._observations_cache_time_step = self.time_step

        return self._robustness_service.apply_observations(observations)

    @property
    def observation_names(self) -> List[List[str]]:
        """Names of returned observations.

        Notes
        -----
        If `central_agent` is True, a list of 1 sublist containing all building observation names is returned in the same order as `buildings`. 
        The `shared_observations` names are only included in the first building's observation names. If `central_agent` is False, a list of sublists 
        is returned where each sublist is a list of 1 building's observation names and the sublist in the same order as `buildings`.
        """

        if self.central_agent:
            observation_names = []

            for i, b in enumerate(self.buildings):
                for k, _ in b.observations(normalize=False, periodic_normalization=False).items():
                    if i == 0 or k not in self.shared_observations or k not in observation_names:
                        observation_names.append(k)

                    else:
                        pass

            observation_names = [observation_names]

        else:
            observation_names = [list(b.observations().keys()) for b in self.buildings]

        return observation_names

    @property
    def action_names(self) -> List[List[str]]:
        """Names of received actions.

        Notes
        -----
        If `central_agent` is True, a list of 1 sublist containing all building action names is returned in the same order as `buildings`. 
        If `central_agent` is False, a list of sublists is returned where each sublist is a list of 1 building's action names and the sublist 
        in the same order as `buildings`.
        """

        if self.central_agent:
            action_names = []

            for b in self.buildings:
                action_names += b.active_actions

            action_names = [action_names]

        else:
            action_names = [b.active_actions for b in self.buildings]

        return action_names

    @property
    def flat_observation_space(self) -> List[spaces.Box]:
        """Flat interface observation space irrespective of `interface` mode."""

        return self._get_flat_observation_space()

    @property
    def flat_action_space(self) -> List[spaces.Box]:
        """Flat interface action space irrespective of `interface` mode."""

        return self._get_flat_action_space()

    @property
    def entity_specs(self) -> Mapping[str, Any]:
        """Canonical entity interface schema for tooling and model builders."""

        return self._entity_service.specs

    def _refresh_action_cache(self):
        self._active_actions_cache = [list(b.active_actions) for b in self.buildings]
        self._expected_central_action_count = sum(len(actions) for actions in self._active_actions_cache)

    @property
    def net_electricity_consumption_emission_without_storage_and_partial_load_and_pv(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_emission_without_storage_and_partial_load_and_pv` time series, in [kg_co2]."""

        return self._sum_building_series(
            'net_electricity_consumption_emission_without_storage_and_partial_load_and_pv',
            non_dynamics_attribute='net_electricity_consumption_emission_without_storage_and_pv',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_cost_without_storage_and_partial_load_and_pv(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_cost_without_storage_and_partial_load_and_pv` time series, in [$]."""

        return self._sum_building_series(
            'net_electricity_consumption_cost_without_storage_and_partial_load_and_pv',
            non_dynamics_attribute='net_electricity_consumption_cost_without_storage_and_pv',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_without_storage_and_partial_load_and_pv(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_without_storage_and_partial_load_and_pv` time series, in [kWh]."""

        return self._sum_building_series(
            'net_electricity_consumption_without_storage_and_partial_load_and_pv',
            non_dynamics_attribute='net_electricity_consumption_without_storage_and_pv',
            preserve_dtype=True,
        )


    @property
    def net_electricity_consumption_emission_without_storage_and_partial_load(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_emission_without_storage_and_partial_load` time series, in [kg_co2]."""

        return self._sum_building_series(
            'net_electricity_consumption_emission_without_storage_and_partial_load',
            non_dynamics_attribute='net_electricity_consumption_emission_without_storage',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_cost_without_storage_and_partial_load(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_cost_without_storage_and_partial_load` time series, in [$]."""

        return self._sum_building_series(
            'net_electricity_consumption_cost_without_storage_and_partial_load',
            non_dynamics_attribute='net_electricity_consumption_cost_without_storage',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_without_storage_and_partial_load(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_without_storage_and_partial_load` time series, in [kWh]."""

        return self._sum_building_series(
            'net_electricity_consumption_without_storage_and_partial_load',
            non_dynamics_attribute='net_electricity_consumption_without_storage',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_emission_without_storage_and_pv(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_emission_without_storage_and_pv` time series, in [kg_co2]."""

        return self._sum_building_series(
            'net_electricity_consumption_emission_without_storage_and_pv',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_cost_without_storage_and_pv(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_cost_without_storage_and_pv` time series, in [$]."""

        return self._sum_building_series(
            'net_electricity_consumption_cost_without_storage_and_pv',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_without_storage_and_pv(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_without_storage_and_pv` time series, in [kWh]."""

        return self._sum_building_series(
            'net_electricity_consumption_without_storage_and_pv',
            preserve_dtype=True,
        )


    @property
    def net_electricity_consumption_emission_without_storage(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_emission_without_storage` time series, in [kg_co2]."""

        return self._sum_building_series(
            'net_electricity_consumption_emission_without_storage',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_cost_without_storage(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_cost_without_storage` time series, in [$]."""

        return self._sum_building_series(
            'net_electricity_consumption_cost_without_storage',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_without_storage(self) -> np.ndarray:
        """Summed `Building.net_electricity_consumption_without_storage` time series, in [kWh]."""

        return self._sum_building_series(
            'net_electricity_consumption_without_storage',
            preserve_dtype=True,
        )

    @property
    def net_electricity_consumption_emission(self) -> List[float]:
        """Summed `Building.net_electricity_consumption_emission` time series, in [kg_co2]."""

        return self.__net_electricity_consumption_emission

    @property
    def net_electricity_consumption_cost(self) -> List[float]:
        """Summed `Building.net_electricity_consumption_cost` time series, in [$]."""

        return self.__net_electricity_consumption_cost

    @property
    def net_electricity_consumption(self) -> List[float]:
        """Summed `Building.net_electricity_consumption` time series, in [kWh]."""

        return self.__net_electricity_consumption

    def _sum_building_series(
        self,
        attribute: str,
        non_dynamics_attribute: str = None,
        *,
        preserve_dtype: bool = False,
    ) -> np.ndarray:
        if len(self.buildings) == 0:
            return np.array([], dtype='float64')

        if non_dynamics_attribute is None:
            series = [np.asarray(getattr(b, attribute)).reshape(-1) for b in self.buildings]
        else:
            series = [
                np.asarray(
                    getattr(b, attribute if isinstance(b, DynamicsBuilding) else non_dynamics_attribute)
                ).reshape(-1)
                for b in self.buildings
            ]

        out_dtype = np.dtype('float64')
        if preserve_dtype:
            non_empty = [values for values in series if len(values) > 0]
            if non_empty:
                inferred = np.result_type(*(values.dtype for values in non_empty))
                out_dtype = np.promote_types(inferred, np.float32) if np.issubdtype(inferred, np.number) else np.dtype('float64')

        length = max((len(values) for values in series), default=0)
        if length == 0:
            return np.array([], dtype=out_dtype)

        if preserve_dtype:
            padded = []
            for values in series:
                casted = np.asarray(values, dtype=out_dtype).reshape(-1)
                if len(casted) < length:
                    buf = np.full(length, np.nan, dtype=out_dtype)
                    buf[:len(casted)] = casted
                    casted = buf
                padded.append(casted)
            matrix = np.column_stack(padded)
            nan_mask = np.isnan(matrix)
            if not nan_mask.any():
                return matrix.sum(axis=1)
            total = np.nansum(matrix, axis=1)
            total[nan_mask.all(axis=1)] = np.nan
            return total

        total = np.zeros(length, dtype='float64')
        valid = np.zeros(length, dtype=bool)

        for values in series:
            end = len(values)
            if end == 0:
                continue

            try:
                mask = ~np.isnan(values)
            except TypeError:
                values = np.asarray(values, dtype='float64').reshape(-1)
                mask = ~np.isnan(values)
            if not np.any(mask):
                continue

            target = total[:end]
            target[mask] = target[mask] + values[mask]
            valid[:end] = valid[:end] | mask

        total[~valid] = np.nan
        return total

    @property
    def cooling_electricity_consumption(self) -> np.ndarray:
        """Summed `Building.cooling_electricity_consumption` time series, in [kWh]."""

        return self._sum_building_series('cooling_electricity_consumption')

    @property
    def heating_electricity_consumption(self) -> np.ndarray:
        """Summed `Building.heating_electricity_consumption` time series, in [kWh]."""

        return self._sum_building_series('heating_electricity_consumption')

    @property
    def dhw_electricity_consumption(self) -> np.ndarray:
        """Summed `Building.dhw_electricity_consumption` time series, in [kWh]."""

        return self._sum_building_series('dhw_electricity_consumption')

    @property
    def cooling_storage_electricity_consumption(self) -> np.ndarray:
        """Summed `Building.cooling_storage_electricity_consumption` time series, in [kWh]."""

        return self._sum_building_series('cooling_storage_electricity_consumption')

    @property
    def heating_storage_electricity_consumption(self) -> np.ndarray:
        """Summed `Building.heating_storage_electricity_consumption` time series, in [kWh]."""

        return self._sum_building_series('heating_storage_electricity_consumption')

    @property
    def dhw_storage_electricity_consumption(self) -> np.ndarray:
        """Summed `Building.dhw_storage_electricity_consumption` time series, in [kWh]."""

        return self._sum_building_series('dhw_storage_electricity_consumption')

    @property
    def electrical_storage_electricity_consumption(self) -> np.ndarray:
        """Summed `Building.electrical_storage_electricity_consumption` time series, in [kWh]."""

        return self._sum_building_series('electrical_storage_electricity_consumption')

    @property
    def energy_from_cooling_device_to_cooling_storage(self) -> np.ndarray:
        """Summed `Building.energy_from_cooling_device_to_cooling_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_from_cooling_device_to_cooling_storage')

    @property
    def energy_from_heating_device_to_heating_storage(self) -> np.ndarray:
        """Summed `Building.energy_from_heating_device_to_heating_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_from_heating_device_to_heating_storage')

    @property
    def energy_from_dhw_device_to_dhw_storage(self) -> np.ndarray:
        """Summed `Building.energy_from_dhw_device_to_dhw_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_from_dhw_device_to_dhw_storage')

    @property
    def energy_to_electrical_storage(self) -> np.ndarray:
        """Summed `Building.energy_to_electrical_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_to_electrical_storage')

    @property
    def energy_from_cooling_device(self) -> np.ndarray:
        """Summed `Building.energy_from_cooling_device` time series, in [kWh]."""

        return self._sum_building_series('energy_from_cooling_device')

    @property
    def energy_from_heating_device(self) -> np.ndarray:
        """Summed `Building.energy_from_heating_device` time series, in [kWh]."""

        return self._sum_building_series('energy_from_heating_device')

    @property
    def energy_from_dhw_device(self) -> np.ndarray:
        """Summed `Building.energy_from_dhw_device` time series, in [kWh]."""

        return self._sum_building_series('energy_from_dhw_device')

    @property
    def energy_to_non_shiftable_load(self) -> np.ndarray:
        """Summed `Building.energy_to_non_shiftable_load` time series, in [kWh]."""

        return self._sum_building_series('energy_to_non_shiftable_load')

    @property
    def energy_from_cooling_storage(self) -> np.ndarray:
        """Summed `Building.energy_from_cooling_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_from_cooling_storage')


    @property
    def total_self_consumption(self) -> np.ndarray:
        """Total self-consumption from electrical and thermal storage, in [kWh]."""
        return (
            self.energy_from_electrical_storage +
            self.energy_from_cooling_storage +
            self.energy_from_heating_storage +
            self.energy_from_dhw_storage
        )

    @property
    def energy_from_heating_storage(self) -> np.ndarray:
        """Summed `Building.energy_from_heating_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_from_heating_storage')

    @property
    def energy_from_dhw_storage(self) -> np.ndarray:
        """Summed `Building.energy_from_dhw_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_from_dhw_storage')

    @property
    def energy_from_electrical_storage(self) -> np.ndarray:
        """Summed `Building.energy_from_electrical_storage` time series, in [kWh]."""

        return self._sum_building_series('energy_from_electrical_storage')

    @property
    def cooling_demand(self) -> np.ndarray:
        """Summed `Building.cooling_demand`, in [kWh]."""

        return self._sum_building_series('cooling_demand')

    @property
    def heating_demand(self) -> np.ndarray:
        """Summed `Building.heating_demand`, in [kWh]."""

        return self._sum_building_series('heating_demand')

    @property
    def dhw_demand(self) -> np.ndarray:
        """Summed `Building.dhw_demand`, in [kWh]."""

        return self._sum_building_series('dhw_demand')

    @property
    def non_shiftable_load(self) -> np.ndarray:
        """Summed `Building.non_shiftable_load`, in [kWh]."""

        return self._sum_building_series('non_shiftable_load')

    @property
    def solar_generation(self) -> np.ndarray:
        """Summed `Building.solar_generation, in [kWh]`."""

        return self._sum_building_series('solar_generation')

    @property
    def power_outage(self) -> np.ndarray:
        """Time series of number of buildings experiencing power outage."""

        return self._sum_building_series('power_outage_signal')[:self.time_step + 1]

    @staticmethod
    def _schema_declares_dynamic_topology(schema: Any) -> bool:
        if not isinstance(schema, Mapping):
            return False

        schema_mode = str(schema.get('topology_mode', '')).strip().lower()
        if schema_mode == 'dynamic':
            return True

        events = schema.get('topology_events', [])
        return isinstance(events, list) and any(isinstance(event, Mapping) for event in events)

    @staticmethod
    def _parse_non_negative_float(value: Any, *, default: float, path: str) -> float:
        if value is None:
            return float(default)

        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'{path} must be a non-negative finite number.') from exc

        if not np.isfinite(parsed) or parsed < 0.0:
            raise ValueError(f'{path} must be a non-negative finite number.')

        return parsed

    @schema.setter
    def schema(self, schema: Union[str, Path, Mapping[str, Any]]):
        dataset = DataSet(offline=self.offline)

        if isinstance(schema, (str, Path)):
            schema_path = Path(schema).expanduser()

            if schema_path.is_dir():
                schema_path = schema_path / 'schema.json'

            if schema_path.is_file():
                schema = FileHandler.read_json(schema_path)
                schema['root_directory'] = str(FileHandler.resolve_schema_root(schema, schema_path))

            elif isinstance(schema, str):
                try:
                    dataset_names = dataset.get_dataset_names()
                except OfflineDataError as e:
                    raise UnknownSchemaError(str(e)) from e

                if schema in dataset_names:
                    schema = dataset.get_schema(schema)
                    schema['root_directory'] = '' if schema['root_directory'] is None else schema['root_directory']
                else:
                    if self.offline:
                        raise UnknownSchemaError(
                            f"Schema '{schema}' was not found locally while offline mode is enabled. "
                            "Provide a local schema.json file path or place the dataset under a local datasets root."
                        )

                    raise UnknownSchemaError()

            else:
                raise UnknownSchemaError(f'Schema file path does not exist: {schema_path}')

        elif isinstance(schema, dict):
            schema = deepcopy(schema)
            schema['root_directory'] = '' if schema['root_directory'] is None else schema['root_directory']
        
        else:
            raise UnknownSchemaError()
        
        self.__schema = schema

    @offline.setter
    def offline(self, value: bool):
        self.__offline = False if value is None else bool(parse_bool(value, default=False, path='offline'))

    @render_enabled.setter
    def render_enabled(self, enabled: bool):
        self.__render_enabled = bool(enabled)

    @export_kpis_on_episode_end.setter
    def export_kpis_on_episode_end(self, enabled: bool):
        self.__export_kpis_on_episode_end = bool(enabled)

    @export_only_final_episode.setter
    def export_only_final_episode(self, enabled: bool):
        self.__export_only_final_episode = bool(enabled)

    @root_directory.setter
    def root_directory(self, root_directory: Union[str, Path]):
        self.__root_directory = root_directory

    @buildings.setter
    def buildings(self, buildings: List[Building]):
        self.__buildings = buildings

    @electric_vehicles.setter
    def electric_vehicles(self, electric_vehicles: List[ElectricVehicle]):
        self.__electric_vehicles = electric_vehicles

    @Environment.episode_tracker.setter
    def episode_tracker(self, episode_tracker: EpisodeTracker):
        Environment.episode_tracker.fset(self, episode_tracker)

        for b in self.buildings:
            b.episode_tracker = self.episode_tracker

    @episode_time_steps.setter
    def episode_time_steps(self, episode_time_steps: Union[int, List[Tuple[int, int]]]):
        self.__episode_time_steps = self.episode_tracker.simulation_time_steps if episode_time_steps is None else episode_time_steps

    @rolling_episode_split.setter
    def rolling_episode_split(self, rolling_episode_split: bool):
        self.__rolling_episode_split = False if rolling_episode_split is None else rolling_episode_split

    @random_episode_split.setter
    def random_episode_split(self, random_episode_split: bool):
        self.__random_episode_split = False if random_episode_split is None else random_episode_split

    @reward_function.setter
    def reward_function(self, reward_function: RewardFunction):
        self.__reward_function = reward_function

    @central_agent.setter
    def central_agent(self, central_agent: bool):
        self.__central_agent = central_agent

    @shared_observations.setter
    def shared_observations(self, shared_observations: List[str]):
        self.__shared_observations = self.get_default_shared_observations() if shared_observations is None else shared_observations
        self._shared_observations_set = set(self.__shared_observations)

    @interface.setter
    def interface(self, interface: str):
        mode = 'flat' if interface is None else str(interface).strip().lower()
        if mode not in {'flat', 'entity'}:
            raise ValueError("interface must be one of {'flat', 'entity'}.")
        if mode != 'entity' and getattr(self, '_CityLearnEnv__topology_mode', 'static') == 'dynamic':
            raise ValueError("topology_mode='dynamic' requires interface='entity'.")
        self.__interface = mode

    @topology_mode.setter
    def topology_mode(self, topology_mode: str):
        mode = 'static' if topology_mode is None else str(topology_mode).strip().lower()
        if mode not in {'static', 'dynamic'}:
            raise ValueError("topology_mode must be one of {'static', 'dynamic'}.")
        if mode == 'dynamic' and getattr(self, '_CityLearnEnv__interface', 'flat') != 'entity':
            raise ValueError("topology_mode='dynamic' requires interface='entity'.")
        schema = getattr(self, '_CityLearnEnv__schema', None)
        if mode == 'static' and self._schema_declares_dynamic_topology(schema):
            raise ValueError(
                "Schema declares dynamic topology (topology_mode='dynamic' or topology_events are defined). "
                "Use topology_mode='dynamic' with interface='entity'."
            )
        self.__topology_mode = mode

    @Environment.random_seed.setter
    def random_seed(self, seed: int):
        Environment.random_seed.fset(self, seed)

        for b in self.buildings:
            b.random_seed = self.random_seed

    @Environment.time_step_ratio.setter
    def time_step_ratio(self, time_step_ratio: int):
        Environment.time_step_ratio.fset(self, time_step_ratio)

        for b in self.buildings:
            b.time_step_ratio = self.time_step_ratio        

    def set_experiment_identity(self, implementation, version, parameters, observation_access='agent_payload'):
        """Declare the controller used for exported paired comparisons."""
        import json
        if not implementation or not version or not isinstance(parameters, dict):
            raise ValueError('Controller implementation, version and parameter dictionary are required')
        self._controller_identity = json.loads(json.dumps(dict(implementation=implementation,
            version=version, parameters=parameters, observation_access=observation_access), allow_nan=False))

    def get_deferrable_service_audit(self):
        """Return executed appliance service, including partial and excluded requests."""
        return self._kpi_service.deferrable_service_audit()

    def get_robustness_audit(self):
        """Return versioned fault coverage, telemetry and completed-interval counters."""
        return self._robustness_service.audit_summary()

    def get_metadata(self) -> Mapping[str, Any]:
        from citylearn.internal.deferrable_service_audit import metadata as deferrable_metadata
        from citylearn.internal.kpi_family_audit import metadata as family_metadata, reward_metadata
        from citylearn.internal.temporal import axis_metadata
        return {
            'deferrable_service_audit': deferrable_metadata(),
            'kpi_family_audit': family_metadata(),
            'reward_evidence': reward_metadata(self),
            **super().get_metadata(),
            'interface': self.interface,
            'topology_mode': self.topology_mode,
            'topology_version': self.topology_version,
            'topology_event_log': self.topology_event_log,
            'physics_invariant_checks': bool(getattr(self, 'physics_invariant_checks', False)),
            'energy_accounting': self._provenance_service.get_metadata(),
            'temporal_reproducibility': axis_metadata(self),
            'ev_departure_within_tolerance': self.ev_departure_within_tolerance,
            'ev_departure_service_tolerance': self.ev_departure_service_tolerance,
            'reward_function': self.reward_function.__class__.__name__,
            'central_agent': self.central_agent,
            'shared_observations': self.shared_observations,
            'community_market': {
                'enabled': self.community_market_enabled,
                'local_price_ratio_to_grid_import': self.community_market_sell_ratio,
                'intra_community_sell_ratio': self.community_market_sell_ratio,
                'grid_export_price': self.community_market_grid_export_price,
                'local_trading_enabled': getattr(self, 'community_market_local_enabled', True),
                'settlement_version': (self.schema.get('community_market') or {}).get('settlement_version', 1),
                'import_member_weights': self.community_market_import_member_weights,
                'kpis': {
                    'community_local_traded_enabled': self.community_market_kpi_local_traded_enabled,
                    'community_self_consumption_enabled': self.community_market_kpi_self_consumption_enabled,
                },
                'matching_granularity': 'aggregate_building',
            },
            'demand_response': self._demand_response_service.get_metadata(),
            'robustness': self._robustness_service.get_metadata(),
            'entity_specs': self._entity_service.specs if self.interface == 'entity' else None,
            'buildings': [b.get_metadata() for b in self.buildings],
        }

    @staticmethod
    def get_default_shared_observations() -> List[str]:
        """Names of default common observations across all buildings i.e. observations that have the same value irrespective of the building.
        
        Notes
        -----
        May be used to assigned :attr:`shared_observations` value during `CityLearnEnv` object initialization.
        """

        return [
            'month', 'day_type', 'hour', 'minutes', 'seconds', 'daylight_savings_status',
            'outdoor_dry_bulb_temperature', 'outdoor_dry_bulb_temperature_predicted_1',
            'outdoor_dry_bulb_temperature_predicted_2', 'outdoor_dry_bulb_temperature_predicted_3',
            'outdoor_relative_humidity', 'outdoor_relative_humidity_predicted_1',
            'outdoor_relative_humidity_predicted_2', 'outdoor_relative_humidity_predicted_3',
            'diffuse_solar_irradiance', 'diffuse_solar_irradiance_predicted_1',
            'diffuse_solar_irradiance_predicted_2', 'diffuse_solar_irradiance_predicted_3',
            'direct_solar_irradiance', 'direct_solar_irradiance_predicted_1',
            'direct_solar_irradiance_predicted_2', 'direct_solar_irradiance_predicted_3',
            'carbon_intensity', 'electricity_pricing', 'electricity_pricing_predicted_1',
            'electricity_pricing_predicted_2', 'electricity_pricing_predicted_3',
        ]

    def step(self, actions: Any) -> Tuple[Any, List[float], bool, bool, dict]:
        """Apply actions and advance the environment by one transition."""

        return self._runtime_service.step(actions)

    def step_many(
        self,
        action: Any,
        repeat_steps: int = 1,
        stop_on_done: bool = True,
        return_substeps: bool = False,
    ) -> Tuple[Any, List[float], bool, bool, dict]:
        """Apply the same action for multiple internal simulator transitions."""

        return self._runtime_service.step_many(
            action,
            repeat_steps=repeat_steps,
            stop_on_done=stop_on_done,
            return_substeps=return_substeps,
        )

    def get_info(self) -> Mapping[Any, Any]:
        """Other information to return from the `citylearn.CityLearnEnv.step` function."""

        return {}

    def _maybe_log_periodic_metrics(self):
        """Lightweight periodic metrics logging for long training runs."""

        interval = max(0, int(self.metrics_log_interval))

        if interval == 0:
            return

        if self.time_step <= 0:
            return

        if self.time_step % interval != 0 and not self.terminated:
            return

        idx = min(self.time_step - 1, len(self.__net_electricity_consumption) - 1)

        if idx < 0:
            return

        LOGGER.info(
            "Episode %s Step %s/%s | net_kwh=%.5f cost=%.5f co2=%.5f",
            self.episode_tracker.episode,
            self.time_step,
            self.time_steps - 1,
            float(self.__net_electricity_consumption[idx]),
            float(self.__net_electricity_consumption_cost[idx]),
            float(self.__net_electricity_consumption_emission[idx]),
        )

    def _parse_actions(self, actions: Any) -> List[Mapping[str, float]]:
        """Compatibility wrapper for runtime action parsing service."""

        return self._runtime_service.parse_actions(actions)

    def evaluate(self, control_condition: EvaluationCondition = None, baseline_condition: EvaluationCondition = None, comfort_band: float = None) -> pd.DataFrame:
        r"""Evaluate cost functions at current time step."""

        return self._kpi_service.evaluate_legacy(
            control_condition=control_condition,
            baseline_condition=baseline_condition,
            comfort_band=comfort_band,
            evaluation_condition_cls=EvaluationCondition,
            dynamics_building_cls=DynamicsBuilding,
        )

    def evaluate_v2(
        self,
        control_condition: EvaluationCondition = None,
        baseline_condition: EvaluationCondition = None,
        comfort_band: float = None,
        include_business_as_usual: bool = True,
        *,
        progress_callback=None,
    ) -> pd.DataFrame:
        r"""Evaluate v2 KPIs; optional progress callback receives scalar stage events.

        Callback failures are logged and disable reporting, preserving evaluation.
        No progress events or timings are added to the returned KPI table.

        With `include_business_as_usual`, the native BAU reference is rebuilt from the schema and
        the constructor arguments. A `ValueError` names the setting when it differs from this env as
        captured at its last `reset()`; see the baselines guide for the settings that are compared.
        """

        return self._kpi_service.evaluate_v2(
            control_condition=control_condition,
            baseline_condition=baseline_condition,
            comfort_band=comfort_band,
            include_business_as_usual=include_business_as_usual,
            evaluation_condition_cls=EvaluationCondition,
            dynamics_building_cls=DynamicsBuilding,
            progress_callback=progress_callback,
        )

    def get_kpi_family_audit(self, *, comfort_band=None, control_condition=None, baseline_condition=None):
        """Return observed populations, thermal service and equity audit evidence."""
        return self._kpi_service.family_audit(comfort_band=comfort_band,
            control_condition=control_condition, baseline_condition=baseline_condition)

    def run_business_as_usual_baseline(self, force: bool = False):
        """Run or return the cached native business-as-usual baseline."""

        return self._business_as_usual_baseline_service.run(force=force)

    def next_time_step(self):
        r"""Advance all buildings to next `time_step`."""

        return self._runtime_service.next_time_step()

    def associate_chargers_to_electric_vehicles(self):
        r"""Associate charger to its corresponding electric_vehicle based on charger simulation state."""

        return self._runtime_service.associate_chargers_to_electric_vehicles()

    def simulate_unconnected_ev_soc(self):
        """Simulate SOC changes for EVs that are not under charger control at t+1."""

        return self._runtime_service.simulate_unconnected_ev_soc()

    def export_final_kpis(
        self,
        model: 'Agent' = None,
        filepath: str = "exported_kpis.csv",
        include_business_as_usual: bool = True,
        export_business_as_usual_timeseries: bool = True,
        kpi_round_decimals: int = None,
    ):
        """Export episode KPIs to csv."""

        return self._episode_exporter.export_final_kpis(
            model=model,
            filepath=filepath,
            include_business_as_usual=include_business_as_usual,
            export_business_as_usual_timeseries=export_business_as_usual_timeseries,
            kpi_round_decimals=kpi_round_decimals,
        )

    def plan_final_episode_exports(self, episodes: int = None):
        """Plan automatic exports for the final episode in the next ``episodes`` resets."""

        previous = getattr(self, '_final_export_episode_index', None)

        if episodes is None:
            self._final_export_episode_index = None
            return previous

        episodes = int(episodes)
        if episodes <= 0:
            raise ValueError(f'episodes must be >= 1, got {episodes}.')

        current_episode = int(getattr(self.episode_tracker, 'episode', -1))
        self._final_export_episode_index = current_episode + episodes
        return previous

    def _should_export_current_episode(self) -> bool:
        if not self.export_only_final_episode:
            return True

        final_episode_index = getattr(self, '_final_export_episode_index', None)
        if final_episode_index is None:
            return True

        current_episode = int(getattr(self.episode_tracker, 'episode', -1))
        return current_episode >= int(final_episode_index)

    def render(self):
        """Render current state of the environment to CSV outputs."""

        return self._episode_exporter.render()

    def _export_episode_render_data(self, final_index: int):
        """Export full episode render rows in one pass for `render_mode='end'`."""

        return self._episode_exporter.export_episode_render_data(final_index)

    def _save_to_csv(self, filename, data):
        """Compatibility wrapper for tests and internal legacy calls."""

        return self._episode_exporter.save_to_csv(filename, data)

    def _flush_render_buffer(self):
        """Write any buffered render rows to disk."""

        return self._episode_exporter.flush_render_buffer()

    def _write_render_rows(self, filename: str, rows: List[Mapping[str, Any]]):
        """Compatibility wrapper for tests and internal legacy calls."""

        return self._episode_exporter.write_render_rows(filename, rows)

    def _parse_render_start_date(self, start_date: Union[str, datetime.date]) -> datetime.date:
        """Return a valid start date for rendering timestamps."""

        return EpisodeExporter.parse_render_start_date(start_date)

    def _ensure_render_output_dir(self, *, ensure_exists: bool = True):
        """Prepare the render output directory and optionally create it on disk."""

        return self._episode_exporter.ensure_output_dir(ensure_exists=ensure_exists)

    def _get_iso_timestamp(self):
        return self._episode_exporter.get_iso_timestamp()

    def _override_render_time_step(self, index: int):
        return self._episode_exporter.override_render_time_step(index)

    @staticmethod
    def _restore_render_time_step(snapshot):
        return EpisodeExporter.restore_render_time_step(snapshot)

    def _reset_time_tracking(self):
        return self._episode_exporter.reset_time_tracking()

    def close(self):
        """Flush pending render rows before closing the environment."""

        if hasattr(self, '_episode_exporter'):
            self._flush_render_buffer()

        return super().close()

    def reset(self, seed: int = None, options: Mapping[str, Any] = None) -> Tuple[Any, dict]:
        r"""Reset `CityLearnEnv` to initial state.

        Parameters
        ----------
        seed: int, optional
            Use to updated :code:`citylearn.CityLearnEnv.random_seed` if value is provided.
        options: Mapping[str, Any], optional
            Optional ``episode_index`` selects a specific episode split for replay.
        
        Returns
        -------
        observations: List[List[float]]
            :attr:`observations`.
        info: dict
            A dictionary that may contain additional information regarding the reason for a `terminated` signal.
            `info` contains auxiliary diagnostic information (helpful for debugging, learning, and logging).
            Override :meth"`get_info` to get custom key-value pairs in `info`.
        """

        # object reset
        super().reset()
        self._final_kpis_exported = False
        if hasattr(self, '_business_as_usual_baseline_service'):
            self._business_as_usual_baseline_service.clear()

        # update seed
        if seed is not None:
            self.random_seed = seed
        else:
            pass

        # Gymnasium API: reset(seed=...) also seeds the environment's own `np_random` generator.
        Env.reset(self, seed=seed)

        # update time steps for time series
        self._episode_index_explicit = bool(options and 'episode_index' in options)
        if self._episode_index_explicit:
            self.episode_tracker.set_next_episode_index(options['episode_index'])
        self.episode_tracker.next_episode(
            self.episode_time_steps,
            self.rolling_episode_split,
            self.random_episode_split,
            self.random_seed,
        )

        if self.topology_mode == 'dynamic':
            self._topology_service.reset()
        else:
            for building in self.buildings:
                building.reset()

            for ev in self.electric_vehicles:
                ev.reset()

        self._demand_response_service.reset()
        self._robustness_service.reset()
        self.associate_chargers_to_electric_vehicles()
        self._provenance_service.reset()
        from citylearn.internal.comparison import equipment, inventory, reference_configuration
        self._comparison_initial_inventory = inventory(self)
        self._comparison_initial_configuration = reference_configuration(self)
        # Taken here because the dynamic topology adds and removes devices during the episode.
        self._comparison_initial_equipment = equipment(self)

        # reset reward function (does nothing by default)
        self.reward_function.reset()

        # variable reset
        self.__rewards = [[]]
        self.__net_electricity_consumption = []
        self.__net_electricity_consumption_cost = []
        self.__net_electricity_consumption_emission = []
        self._last_community_market_settlement = []
        self._community_market_settlement_history = MarketSettlementHistory()
        self._observations_cache = None
        self._observations_cache_time_step = -1
        episode_index = int(getattr(self.episode_tracker, 'episode', 0))
        self._reset_seed_explicit = seed is not None
        self._ev_drift_seed = int(self.random_seed) if seed is not None else int(self.random_seed) + episode_index
        self._ev_drift_random_state = np.random.RandomState(self._ev_drift_seed)
        self._ev_suspended_drift_random_state = None
        self._render_buffer.clear()
        self._refresh_action_cache()
        self.update_variables()
        if bool(getattr(self, 'physics_invariant_checks', False)):
            self._physics_invariant_service.assert_step_invariants(int(self.time_step))
        self._entity_service.reset()
        self._robustness_service.validate_targets()
        self.reward_function.env_metadata = self.get_metadata()

        return self.observations, self.get_info()

    def _configure_community_market(self):
        config = {}
        if isinstance(self.schema, dict):
            config = self.schema.get('community_market', {}) or {}

        self.community_market_enabled = parse_bool(
            config.get('enabled', False),
            default=False,
            path='community_market.enabled',
        )
        ratio = config.get('local_price_ratio_to_grid_import', config.get('intra_community_sell_ratio', 0.8))

        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            ratio = 0.8

        self.community_market_sell_ratio = min(max(ratio, 0.0), 1.0)
        export_price = float(config.get('grid_export_price', 0.0)) if config.get('settlement_version') == 2 else 0.0
        if not np.isfinite(export_price):
            raise ValueError('grid_export_price must be finite')
        self.community_market_grid_export_price = export_price
        from citylearn.community_dataset import configure_tariffs
        configure_tariffs(self, config)
        weights = config.get('import_member_weights', {}) or {}
        parsed_weights = {}
        if isinstance(weights, Mapping):
            for key, value in weights.items():
                try:
                    parsed_weights[str(key)] = max(float(value), 0.0)
                except (TypeError, ValueError):
                    continue

        self.community_market_import_member_weights = parsed_weights
        kpis_config = config.get('kpis', {}) or {}
        self.community_market_kpi_local_traded_enabled = parse_bool(
            kpis_config.get('community_local_traded_enabled', True),
            default=True,
            path='community_market.kpis.community_local_traded_enabled',
        )
        self.community_market_kpi_self_consumption_enabled = parse_bool(
            kpis_config.get('community_self_consumption_enabled', True),
            default=True,
            path='community_market.kpis.community_self_consumption_enabled',
        )

    def update_variables(self):
        """Update district-level aggregate variables."""

        return self._runtime_service.update_variables()

    def load_agent(self, agent: Union[str, 'Agent'] = None, **kwargs) -> Union[Any, 'Agent']:
        """Return :class:`Agent` or sub class object as defined by the `schema`.

        Parameters
        ----------
        agent: Union[str, 'citylearn.agents.base.Agent], optional
            Agent class or string describing path to agent class, e.g. 'citylearn.agents.base.BaselineAgent'.
            If a value is not provided, defaults to the agent defined in the schema:agent:type.

        **kwargs : dict
            Agent initialization attributes. For most agents e.g. CityLearn and Stable-Baselines3 agents, 
            an intialized :py:attr:`env` must be parsed to the agent :py:meth:`init` function.
        
        Returns
        -------
        agent: Agent
            Initialized agent.
        """

        # set agent class
        if agent is not None:
            agent_type = agent

            if not isinstance(agent_type, str):
                agent_type = [agent_type.__module__] + [agent_type.__name__]
                agent_type = '.'.join(agent_type)

            else:
                pass

        # set agent init attributes
        else:
            agent_type = self.schema['agent']['type']

        if kwargs is not None and len(kwargs) > 0:
            agent_attributes = dict(kwargs)

        elif agent is None:
            agent_attributes = dict(self.schema['agent'].get('attributes', {}))

        else:
            agent_attributes = {}

        if 'env' not in agent_attributes:
            agent_attributes['env'] = self

        agent_module = '.'.join(agent_type.split('.')[0:-1])
        agent_name = agent_type.split('.')[-1]
        agent_constructor = getattr(importlib.import_module(agent_module), agent_name)
        agent = agent_constructor(**agent_attributes)

        return agent

    def _load(self, schema: Mapping[str, Any], **kwargs) -> Tuple[Union[Path, str], List[Building], List[ElectricVehicle], Union[int, List[Tuple[int, int]]], bool, bool, float, RewardFunction, bool, List[str], EpisodeTracker]:
        """Compatibility wrapper for schema loading service."""

        return self._loading_service.load(schema, **kwargs)

    def _load_building(self, index: int, building_name: str, schema: dict, episode_tracker: EpisodeTracker, pv_sizing_data: pd.DataFrame, battery_sizing_data: pd.DataFrame, **kwargs) -> Building:
        """Compatibility wrapper for building loading service."""

        return self._loading_service.load_building(
            index,
            building_name,
            schema,
            episode_tracker,
            pv_sizing_data,
            battery_sizing_data,
            **kwargs,
        )

    def process_metadata(self, schema, building_schema, chargers_list, deferrable_appliances_list, escalators_list, index, energy_simulation: EnergySimulation, **kwargs):
        """Compatibility wrapper for metadata processing service."""

        return self._loading_service.process_metadata(
            schema,
            building_schema,
            chargers_list,
            deferrable_appliances_list,
            escalators_list,
            index,
            energy_simulation,
            **kwargs,
        )

    def _load_electric_vehicle(self, electric_vehicle_name: str, schema: dict, electric_vehicle_schema: dict, episode_tracker: EpisodeTracker, time_step_ratio) -> ElectricVehicle:
        """Compatibility wrapper for electric vehicle loading service."""

        return self._loading_service.load_electric_vehicle(
            electric_vehicle_name,
            schema,
            electric_vehicle_schema,
            episode_tracker,
            time_step_ratio,
        )

    def _load_deferrable_appliance(
        self,
        appliance_name: str,
        building_name: str,
        schema: dict,
        appliance_schema: dict,
        episode_tracker: EpisodeTracker
    ) -> DeferrableAppliance:
        """Compatibility wrapper for deferrable appliance loading service."""

        return self._loading_service.load_deferrable_appliance(
            appliance_name,
            building_name,
            schema,
            appliance_schema,
            episode_tracker,
        )

    def _load_washing_machine(self, *args, **kwargs):
        return self._loading_service.load_washing_machine(*args, **kwargs)

    def __str__(self) -> str:
        """
        Return a string representation of the current simulation state.

        Useful for logging or quick inspection of internal values.
        """
        return str(self.as_dict())

    def as_dict(self) -> dict:
        """
        Convert the current simulation state to a dictionary.

        This includes key performance indicators such as energy usage, emissions, 
        and electricity pricing at the current time step.

        Returns
        -------
        dict
            Dictionary with energy and environmental metrics for the current step.
        """
        if len(self.net_electricity_consumption) == 0:
            idx = 0
        else:
            idx = max(0, min(self.time_step, len(self.net_electricity_consumption) - 1))

        def _safe_value(series, index: int) -> float:
            return float(series[index]) if 0 <= index < len(series) else 0.0

        self_consumption = 0.0
        stored_energy = 0.0
        total_solar_generation = 0.0

        for building in self.buildings:
            self_consumption += (
                _safe_value(building.energy_from_electrical_storage, idx)
                + _safe_value(building.energy_from_cooling_storage, idx)
                + _safe_value(building.energy_from_heating_storage, idx)
                + _safe_value(building.energy_from_dhw_storage, idx)
            )
            stored_energy += _safe_value(building.energy_to_electrical_storage, idx)
            total_solar_generation += _safe_value(building.solar_generation, idx)

        return {
            "Net Electricity Consumption-kWh": _safe_value(self.net_electricity_consumption, idx),
            "Self Consumption-kWh": self_consumption,
            "Stored energy by community- kWh": stored_energy,
            "Total Solar Generation-kWh": total_solar_generation,
            "CO2-kg_co2": _safe_value(self.net_electricity_consumption_emission, idx),
            "Price-$": _safe_value(self.net_electricity_consumption_cost, idx),
        }
class Error(Exception):
    """Base class for other exceptions."""

class UnknownSchemaError(Error):
    """Raised when a schema is not a data set name, dict nor filepath."""
    __MESSAGE = 'Unknown schema parsed into constructor. Schema must be name of CityLearn data set,'\
        ' a filepath to JSON representation or `dict` object of a CityLearn schema.'\
        ' Call citylearn.data.DataSet.get_names() for list of available CityLearn data sets.'

    def __init__(self,message=None):
        super().__init__(self.__MESSAGE if message is None else message)
