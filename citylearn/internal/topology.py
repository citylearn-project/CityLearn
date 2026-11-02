from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

import numpy as np

from citylearn.energy_model import Battery, DeferrableAppliance, PV
from citylearn.utilities import parse_bool

if TYPE_CHECKING:
    from citylearn.building import Building
    from citylearn.citylearn import CityLearnEnv
    from citylearn.electric_vehicle import ElectricVehicle
    from citylearn.electric_vehicle_charger import Charger


SUPPORTED_OPERATIONS = {
    'add_member',
    'remove_member',
    'add_asset',
    'remove_asset',
}
SUPPORTED_ASSET_TYPES = {
    'charger',
    'deferrable_appliance',
    'pv',
    'electrical_storage',
}


@dataclass(frozen=True)
class TopologyEvent:
    """Canonical in-memory topology event."""

    event_id: str
    time_step: int
    operation: str
    target_member_id: Optional[str]
    target_asset_type: Optional[str]
    target_asset_id: Optional[str]
    source_member_id: Optional[str]
    source_asset_id: Optional[str]
    overrides: Mapping[str, Any]
    order: int


@dataclass(frozen=True)
class _BuildingStructureSnapshot:
    """Lightweight references and metadata needed to restore a building topology."""

    electric_vehicle_chargers: Sequence[Charger]
    deferrable_appliances: Sequence[DeferrableAppliance]
    pv: PV
    electrical_storage: Battery
    observation_metadata: Mapping[str, bool]
    action_metadata: Mapping[str, bool]
    building_override_values: Mapping[str, Any]


class CityLearnTopologyService:
    """Schema-driven dynamic topology lifecycle and mutation service."""

    def __init__(self, env: "CityLearnEnv"):
        self.env = env
        self._member_pool: Dict[str, Building] = {}
        self._member_order: List[str] = []
        self._ev_pool: Dict[str, ElectricVehicle] = {}
        self._ev_order: List[str] = []
        self._initial_active_member_ids: List[str] = []
        self._initial_member_pool: Dict[str, Building] = {}
        self._initial_member_order: List[str] = []
        self._initial_building_structures: Dict[str, _BuildingStructureSnapshot] = {}
        self._active_member_ids: List[str] = []
        self._active_ev_ids: List[str] = []
        self._member_lifecycle: Dict[str, Dict[str, Any]] = {}
        self._events: List[TopologyEvent] = []
        self._event_cursor: int = 0
        self._topology_version: int = 0
        self._event_log: List[Mapping[str, Any]] = []
        self._active_member_history: Dict[int, List[str]] = {}
        self._active_ev_history: Dict[int, List[str]] = {}
        self._topology_version_history: Dict[int, int] = {}
        self._active_charger_history: Dict[int, Dict[str, Dict[str, Charger]]] = {}
        self._active_storage_history: Dict[int, Dict[str, Optional[Battery]]] = {}
        self._active_deferrable_appliance_history: Dict[int, Dict[str, Dict[str, DeferrableAppliance]]] = {}
        self._last_history_signature = None
        self._last_history_time_step = None
        self._charger_observation_flags = self._collect_charger_observation_flags()
        self._charger_action_enabled = self._is_schema_action_active('electric_vehicle_storage')

    @property
    def enabled(self) -> bool:
        return getattr(self.env, 'topology_mode', 'static') == 'dynamic'

    @property
    def member_pool(self) -> Mapping[str, Building]:
        return self._member_pool

    @property
    def ev_pool(self) -> Mapping[str, ElectricVehicle]:
        return self._ev_pool

    @property
    def active_member_ids(self) -> Sequence[str]:
        return tuple(self._active_member_ids)

    @property
    def active_ev_ids(self) -> Sequence[str]:
        return tuple(self._active_ev_ids)

    @property
    def topology_version(self) -> int:
        return int(self._topology_version)

    @property
    def event_log(self) -> Sequence[Mapping[str, Any]]:
        return tuple(self._event_log)

    @property
    def member_lifecycle(self) -> Mapping[str, Mapping[str, Any]]:
        return {
            member_id: dict(state)
            for member_id, state in self._member_lifecycle.items()
        }

    def initialize(self, buildings: Sequence[Building], electric_vehicles: Sequence[ElectricVehicle]):
        """Initialize static pools and parse deterministic event stream."""

        self._member_pool = {building.name: building for building in buildings}
        self._member_order = [building.name for building in buildings]
        self._ev_pool = {ev.name: ev for ev in electric_vehicles}
        self._ev_order = [ev.name for ev in electric_vehicles]
        self._events = self._parse_events()
        self._initial_member_pool = dict(self._member_pool)
        self._initial_member_order = list(self._member_order)
        self._initial_building_structures = {
            member_id: self._snapshot_building_structure(building)
            for member_id, building in self._member_pool.items()
        }

        include_flags = self._initial_member_include_flags()
        self._initial_active_member_ids = [
            member_id for member_id in self._member_order if include_flags.get(member_id, True)
        ]

        if len(self._initial_active_member_ids) == 0 and len(self._member_order) > 0:
            self._initial_active_member_ids = [self._member_order[0]]

    def reset(self):
        """Reset topology and pools for a fresh episode."""

        if not self.enabled:
            return

        self._restore_initial_structure()

        for building in self._member_pool.values():
            self._bind_building_runtime_context(building)
            building.reset()
            self._sync_dynamic_asset_metadata(building)
            building.observation_space = building.estimate_observation_space(include_all=False, normalize=False)
            building.action_space = building.estimate_action_space()

        for ev in self._ev_pool.values():
            self._bind_ev_runtime_context(ev)
            ev.reset()

        self._active_member_ids = list(self._initial_active_member_ids)
        self._active_ev_ids = []
        self._member_lifecycle = {
            member_id: {
                'born_at': 0 if member_id in set(self._active_member_ids) else None,
                'removed_at': None,
                'active': member_id in set(self._active_member_ids),
            }
            for member_id in self._member_order
        }

        self._event_cursor = 0
        self._topology_version = 0
        self._event_log = []
        self._active_member_history = {}
        self._active_ev_history = {}
        self._topology_version_history = {}
        self._active_charger_history = {}
        self._active_storage_history = {}
        self._active_deferrable_appliance_history = {}
        self._last_history_signature = None
        self._last_history_time_step = None

        self._set_active_views()
        self.apply_events_for_time_step(0)

    def _snapshot_building_structure(self, building: Building) -> _BuildingStructureSnapshot:
        override_values: Dict[str, Any] = {}
        for event in self._events:
            if event.operation != 'add_member' or event.target_member_id != building.name:
                continue

            for key in event.overrides:
                if key in {'name', 'chargers', 'deferrable_appliances', 'electrical_storage', 'pv'}:
                    continue
                if hasattr(building, key) and key not in override_values:
                    override_values[key] = deepcopy(getattr(building, key))

        return _BuildingStructureSnapshot(
            electric_vehicle_chargers=tuple(building.electric_vehicle_chargers or []),
            deferrable_appliances=tuple(building.deferrable_appliances or []),
            pv=building.pv,
            electrical_storage=building.electrical_storage,
            observation_metadata=dict(building.observation_metadata),
            action_metadata=dict(building.action_metadata),
            building_override_values=override_values,
        )

    def _restore_initial_structure(self):
        """Restore the schema-loaded member pool and asset composition before reset."""

        self._member_pool = dict(self._initial_member_pool)
        self._member_order = list(self._initial_member_order)

        for member_id in self._member_order:
            building = self._member_pool[member_id]
            snapshot = self._initial_building_structures[member_id]
            building.electric_vehicle_chargers = list(snapshot.electric_vehicle_chargers)
            building.deferrable_appliances = list(snapshot.deferrable_appliances)
            building.pv = snapshot.pv
            building.electrical_storage = snapshot.electrical_storage

            for key, value in snapshot.building_override_values.items():
                setattr(building, key, deepcopy(value))

            building.observation_metadata = dict(snapshot.observation_metadata)
            building.action_metadata = dict(snapshot.action_metadata)

    def apply_events_for_time_step(self, time_step: int) -> bool:
        """Apply schema events due at the current episode-local time step.

        Topology-event timestamps belong to the global dataset timeline, while
        ``Environment.time_step`` is local to the current episode.  Replaying
        events before the episode start reconstructs the composition that must
        be visible at local step zero; events inside the episode are then
        applied when their global timestamp is reached.
        """

        if not self.enabled:
            return False

        changed = False
        tracker = getattr(self.env, 'episode_tracker', None)
        episode_start = int(
            getattr(tracker, 'episode_start_time_step', 0) or 0
        )
        global_time_step = episode_start + int(time_step)

        while self._event_cursor < len(self._events):
            event = self._events[self._event_cursor]

            if event.time_step > global_time_step:
                break

            # An event before the selected episode window is replayed at local
            # step zero to establish topology state without simulating the
            # omitted history.  In-window events use the actual local step so
            # newly inserted assets align with the sliced time-series state.
            event_local_time_step = (
                int(time_step)
                if event.time_step >= episode_start
                else 0
            )
            event_changed = self._apply_event(event, event_local_time_step)
            changed = changed or event_changed
            self._event_log.append(
                {
                    'id': event.event_id,
                    'time_step': event.time_step,
                    'operation': event.operation,
                    'target_member_id': event.target_member_id,
                    'target_asset_type': event.target_asset_type,
                    'target_asset_id': event.target_asset_id,
                    'source_member_id': event.source_member_id,
                    'source_asset_id': event.source_asset_id,
                    'applied': bool(event_changed),
                    'topology_version': int(self._topology_version),
                    'episode_time_step': event_local_time_step,
                }
            )
            self._event_cursor += 1

        if changed:
            self._set_active_views()

        self._record_history(time_step)

        return changed

    def active_member_ids_at(self, time_step: int) -> List[str]:
        return self._history_lookup(self._active_member_history, time_step, list(self._active_member_ids))

    def active_ev_ids_at(self, time_step: int) -> List[str]:
        return self._history_lookup(self._active_ev_history, time_step, list(self._active_ev_ids))

    def topology_version_at(self, time_step: int) -> int:
        values = self._history_lookup(self._topology_version_history, time_step, int(self._topology_version))
        return int(values)

    def active_chargers_at(self, time_step: int, member_id: str) -> Mapping[str, Charger]:
        snapshot = self._history_lookup_reference(self._active_charger_history, time_step, {})
        member_chargers = snapshot.get(member_id, {})
        return dict(member_chargers)

    def active_storage_at(self, time_step: int, member_id: str) -> Optional[Battery]:
        snapshot = self._history_lookup_reference(self._active_storage_history, time_step, {})
        return snapshot.get(member_id)

    def active_deferrable_appliances_at(self, time_step: int, member_id: str) -> Mapping[str, DeferrableAppliance]:
        snapshot = self._history_lookup_reference(self._active_deferrable_appliance_history, time_step, {})
        member_appliances = snapshot.get(member_id, {})
        return dict(member_appliances)

    def historical_chargers(self, member_id: str) -> Sequence[Charger]:
        """Return every distinct charger instance that was active for a member.

        Dynamic remove/reinstall events create a fresh runtime instance from the
        immutable schema template.  Retaining both instances is necessary for
        end-of-episode KPIs: the current building view alone otherwise drops EV
        service and energy recorded before the removal.
        """

        return tuple(self._historical_asset_instances(
            self._active_charger_history,
            member_id,
        ))

    def historical_deferrable_appliances(self, member_id: str) -> Sequence[DeferrableAppliance]:
        """Return every distinct deferrable instance active for a member."""

        return tuple(self._historical_asset_instances(
            self._active_deferrable_appliance_history,
            member_id,
        ))

    def historical_storages(self, member_id: str) -> Sequence[Battery]:
        """Return every distinct stationary-storage instance active for a member.

        Storage removal followed by catalogue-based recommissioning creates a
        new physical/runtime instance.  Keeping both objects prevents the KPI
        layer from silently discarding throughput and degradation accumulated
        by the instance that was removed.
        """

        instances: List[Battery] = []
        seen_object_ids = set()
        for time_step in sorted(self._active_storage_history):
            storage = self._active_storage_history[time_step].get(member_id)
            if storage is None or id(storage) in seen_object_ids:
                continue

            seen_object_ids.add(id(storage))
            instances.append(storage)

        return tuple(instances)

    @staticmethod
    def _historical_asset_instances(
        history: Mapping[int, Mapping[str, Mapping[str, Any]]],
        member_id: str,
    ) -> List[Any]:
        instances: List[Any] = []
        seen_object_ids = set()

        for time_step in sorted(history):
            member_assets = history[time_step].get(member_id, {})
            for asset in member_assets.values():
                object_id = id(asset)
                if object_id in seen_object_ids:
                    continue

                seen_object_ids.add(object_id)
                instances.append(asset)

        return instances

    @staticmethod
    def _history_lookup(history: Mapping[int, Any], time_step: int, default: Any):
        if time_step in history:
            return deepcopy(history[time_step])

        valid = (k for k in history.keys() if k <= time_step)
        latest = max(valid, default=None)
        if latest is None:
            return deepcopy(default)

        return deepcopy(history[latest])

    @staticmethod
    def _history_lookup_reference(history: Mapping[int, Any], time_step: int, default: Any):
        if time_step in history:
            return history[time_step]

        valid = (k for k in history.keys() if k <= time_step)
        latest = max(valid, default=None)
        if latest is None:
            return default

        return history[latest]

    def _record_history(self, time_step: int):
        time_step = int(time_step)
        signature = (
            tuple(self._active_member_ids),
            tuple(self._active_ev_ids),
            int(self._topology_version),
        )
        if (
            self._last_history_time_step is not None
            and time_step != self._last_history_time_step
            and signature == self._last_history_signature
        ):
            return

        self._active_member_history[time_step] = list(self._active_member_ids)
        self._active_ev_history[time_step] = list(self._active_ev_ids)
        self._topology_version_history[time_step] = int(self._topology_version)
        charger_snapshot: Dict[str, Dict[str, Charger]] = {}
        storage_snapshot: Dict[str, Optional[Battery]] = {}
        deferrable_snapshot: Dict[str, Dict[str, DeferrableAppliance]] = {}

        for member_id in self._active_member_ids:
            building = self._member_pool.get(member_id)
            if building is None:
                continue

            charger_snapshot[member_id] = {
                charger.charger_id: charger for charger in (building.electric_vehicle_chargers or [])
            }
            storage_snapshot[member_id] = (
                building.electrical_storage if self._has_electrical_storage_asset(building) else None
            )
            deferrable_snapshot[member_id] = {
                appliance.name: appliance for appliance in (building.deferrable_appliances or [])
            }

        self._active_charger_history[time_step] = charger_snapshot
        self._active_storage_history[time_step] = storage_snapshot
        self._active_deferrable_appliance_history[time_step] = deferrable_snapshot
        self._last_history_signature = signature
        self._last_history_time_step = time_step

    def _set_active_views(self):
        env = self.env
        active_set = set(self._active_member_ids)
        active_buildings = [
            self._member_pool[member_id]
            for member_id in self._member_order
            if member_id in active_set
        ]
        env.buildings = active_buildings

        t = int(getattr(env, 'time_step', 0))
        for building in active_buildings:
            self._bind_building_runtime_context(building)
            self._set_building_time_step(building, t)

        active_ev_ids = self._collect_active_ev_ids(active_buildings)
        self._active_ev_ids = [ev_id for ev_id in self._ev_order if ev_id in active_ev_ids]
        env.electric_vehicles = [self._ev_pool[ev_id] for ev_id in self._active_ev_ids]

        for ev in env.electric_vehicles:
            self._bind_ev_runtime_context(ev)
            self._set_ev_time_step(ev, t)

    @staticmethod
    def _set_building_time_step(building: Building, time_step: int):
        building.time_step = time_step

        for attr_name in (
            'cooling_device',
            'heating_device',
            'dhw_device',
            'non_shiftable_load_device',
            'cooling_storage',
            'heating_storage',
            'dhw_storage',
            'electrical_storage',
            'pv',
        ):
            obj = getattr(building, attr_name, None)
            if obj is not None and hasattr(obj, 'time_step'):
                obj.time_step = time_step

        for charger in building.electric_vehicle_chargers or []:
            charger.time_step = time_step

        for appliance in building.deferrable_appliances or []:
            appliance.time_step = time_step

    @staticmethod
    def _set_ev_time_step(ev: ElectricVehicle, time_step: int):
        ev.time_step = time_step
        if getattr(ev, 'battery', None) is not None:
            ev.battery.time_step = time_step

    @staticmethod
    def _initialize_storage_at_activation(building: Building):
        """Apply the declared initial SoC at a mid-episode activation boundary."""

        storage = getattr(building, 'electrical_storage', None)
        if storage is None or not hasattr(storage, 'force_set_soc'):
            return
        capacity = float(getattr(storage, 'capacity', 0.0) or 0.0)
        nominal_power = float(getattr(storage, 'nominal_power', 0.0) or 0.0)
        if capacity <= 0.0 or nominal_power <= 0.0:
            return
        initial_soc = float(getattr(storage, 'initial_soc', 0.0) or 0.0)
        minimum_soc = getattr(storage, '_minimum_soc', lambda: 0.0)()
        storage.force_set_soc(float(np.clip(initial_soc, minimum_soc, 1.0)))

    def _bind_ev_runtime_context(self, ev: ElectricVehicle):
        env = self.env
        ev.episode_tracker = env.episode_tracker
        ev.random_seed = env.random_seed
        ev.time_step_ratio = env.time_step_ratio

    def _bind_building_runtime_context(self, building: Building):
        env = self.env
        building.episode_tracker = env.episode_tracker
        building.random_seed = env.random_seed
        building.time_step_ratio = env.time_step_ratio

        for charger in building.electric_vehicle_chargers or []:
            charger.episode_tracker = env.episode_tracker
            charger.random_seed = env.random_seed
            charger.time_step_ratio = building.time_step_ratio

        for appliance in building.deferrable_appliances or []:
            appliance.episode_tracker = env.episode_tracker
            appliance.random_seed = env.random_seed
            appliance.time_step_ratio = building.time_step_ratio

    def _collect_active_ev_ids(self, buildings: Iterable[Building]) -> Set[str]:
        active_ev_ids: Set[str] = set()

        if not self._ev_pool:
            return active_ev_ids

        for building in buildings:
            for charger in building.electric_vehicle_chargers or []:
                sim_ids = getattr(charger.charger_simulation, 'electric_vehicle_id', None)
                if sim_ids is not None:
                    for ev_id in sim_ids:
                        if self._is_valid_ev_id(ev_id) and ev_id in self._ev_pool:
                            active_ev_ids.add(ev_id)

                for ev_obj in (
                    getattr(charger, 'connected_electric_vehicle', None),
                    getattr(charger, 'incoming_electric_vehicle', None),
                ):
                    ev_name = getattr(ev_obj, 'name', None)
                    if isinstance(ev_name, str) and ev_name in self._ev_pool:
                        active_ev_ids.add(ev_name)

        return active_ev_ids

    @staticmethod
    def _is_valid_ev_id(value: Any) -> bool:
        if not isinstance(value, str):
            return False

        text = value.strip()
        return text not in {'', 'nan'}

    def _apply_event(self, event: TopologyEvent, time_step: int) -> bool:
        op = event.operation

        if op == 'add_member':
            return self._add_member(event, time_step)

        if op == 'remove_member':
            return self._remove_member(event, time_step)

        if op == 'add_asset':
            return self._add_asset(event, time_step)

        if op == 'remove_asset':
            return self._remove_asset(event, time_step)

        raise ValueError(f'Unsupported topology operation: {op}')

    def _add_member(self, event: TopologyEvent, time_step: int) -> bool:
        target_member_id = event.target_member_id
        if target_member_id is None:
            raise ValueError('add_member requires target_member_id.')

        if target_member_id not in self._member_pool:
            source_member_id = event.source_member_id
            if source_member_id is None or source_member_id not in self._member_pool:
                raise ValueError(
                    f"add_member target '{target_member_id}' is not preloaded and source_member_id is invalid."
                )

            cloned = deepcopy(self._member_pool[source_member_id])
            cloned.name = target_member_id
            self._bind_building_runtime_context(cloned)
            self._member_pool[target_member_id] = cloned
            self._member_order.append(target_member_id)
            self._member_lifecycle[target_member_id] = {
                'born_at': None,
                'removed_at': None,
                'active': False,
            }

        if target_member_id in self._active_member_ids:
            return False

        building = self._member_pool[target_member_id]
        rejoining = self._member_lifecycle.get(target_member_id, {}).get('born_at') is not None
        prefix, storage_prefix = self._capture_member_energy_prefix(building, time_step) if rejoining else ([], None)
        if rejoining:
            # Histories keep physical instances; resetting them would erase
            # pre-exit throughput and charger service as well as building totals.
            building.deferrable_appliances = [deepcopy(a) for a in building.deferrable_appliances or []]
            building.electrical_storage = deepcopy(building.electrical_storage)
            building.electric_vehicle_chargers = [deepcopy(c) for c in building.electric_vehicle_chargers or []]
        self._bind_building_runtime_context(building)
        building.reset()
        for obj, key, values in prefix:
            current = getattr(obj, key)
            current[:len(values)] = values
        building._archived_storage_electricity = storage_prefix
        self._set_building_time_step(building, time_step)
        self._initialize_storage_at_activation(building)
        self._skip_expired_deferrable_requests(
            building,
            self._global_time_step(time_step),
        )

        for appliance in building.deferrable_appliances or []:
            self._exclude_previous_deferrable_requests(target_member_id, appliance)
        self._active_member_ids.append(target_member_id)
        lifecycle = self._member_lifecycle.setdefault(target_member_id, {'born_at': None, 'removed_at': None, 'active': False})
        lifecycle['active'] = True
        lifecycle['removed_at'] = None
        if lifecycle.get('born_at') is None:
            lifecycle['born_at'] = int(time_step)

        self._apply_building_overrides(building, event.overrides)
        self._refresh_building_after_mutation(building)
        self._topology_version += 1
        return True

    @staticmethod
    def _capture_member_energy_prefix(building, time_step):
        """Preserve completed electrical/thermal flows, not recommissioned SoC."""
        objects = [building, building.cooling_device, building.heating_device,
                   building.dhw_device, building.non_shiftable_load_device,
                   building.cooling_storage, building.heating_storage, building.dhw_storage]
        prefixes = []
        seen = set()
        for obj in objects:
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            for key, values in vars(obj).items():
                is_flow = any(token in key for token in ('electricity_consumption', 'solar_generation',
                    'energy_balance', 'energy_from_', 'energy_to_', 'power_outage_signal', 'pv_curtailment'))
                if is_flow and isinstance(values, np.ndarray) and values.ndim == 1:
                    prefixes.append((obj, key, values[:time_step].copy()))
        storage_prefix = np.zeros(time_step, dtype=float)
        values = building.electrical_storage_electricity_consumption
        size = min(time_step, len(values))
        storage_prefix[:size] = values[:size]
        return prefixes, storage_prefix

    def _global_time_step(self, local_time_step: int) -> int:
        tracker = getattr(self.env, 'episode_tracker', None)
        episode_start = int(
            getattr(tracker, 'episode_start_time_step', 0) or 0
        )
        return episode_start + int(local_time_step)

    @staticmethod
    def _skip_expired_deferrable_requests(
        building: Building,
        global_time_step: int,
    ):
        for appliance in building.deferrable_appliances or []:
            if hasattr(appliance, 'skip_cycles_before'):
                appliance.skip_cycles_before(global_time_step)

    @staticmethod
    def _zero_action_kwargs(building: Building) -> Mapping[str, Any]:
        active_actions = set(list(getattr(building, 'active_actions', []) or []))
        kwargs: Dict[str, Any] = {}

        if 'cooling_or_heating_device' in active_actions:
            kwargs['cooling_or_heating_device_action'] = 0.0
        if 'cooling_device' in active_actions:
            kwargs['cooling_device_action'] = 0.0
        if 'heating_device' in active_actions:
            kwargs['heating_device_action'] = 0.0
        if 'cooling_storage' in active_actions:
            kwargs['cooling_storage_action'] = 0.0
        if 'heating_storage' in active_actions:
            kwargs['heating_storage_action'] = 0.0
        if 'dhw_storage' in active_actions:
            kwargs['dhw_storage_action'] = 0.0
        if 'electrical_storage' in active_actions:
            kwargs['electrical_storage_action'] = 0.0

        ev_actions: Dict[str, float] = {}
        deferrable_actions: Dict[str, float] = {}
        for action_name in active_actions:
            if action_name.startswith('electric_vehicle_storage_'):
                charger_id = action_name.replace('electric_vehicle_storage_', '')
                ev_actions[charger_id] = 0.0
            elif action_name.startswith('deferrable_appliance_'):
                deferrable_actions[action_name] = 0.0

        if ev_actions:
            kwargs['electric_vehicle_storage_actions'] = ev_actions
        if deferrable_actions:
            kwargs['deferrable_appliance_actions'] = deferrable_actions

        return kwargs

    def _remove_member(self, event: TopologyEvent, time_step: int) -> bool:
        target_member_id = event.target_member_id
        if target_member_id is None:
            raise ValueError('remove_member requires target_member_id.')

        if target_member_id not in self._active_member_ids:
            return False

        for appliance in self._member_pool[target_member_id].deferrable_appliances or []:
            appliance.cancel_pending_and_running(self._global_time_step(time_step), reason='member_removed')
        self._active_member_ids = [member_id for member_id in self._active_member_ids if member_id != target_member_id]
        lifecycle = self._member_lifecycle.setdefault(target_member_id, {'born_at': None, 'removed_at': None, 'active': False})
        lifecycle['active'] = False
        lifecycle['removed_at'] = int(time_step)
        self._topology_version += 1
        return True

    def _add_asset(self, event: TopologyEvent, time_step: int) -> bool:
        building = self._resolve_target_building(event)
        asset_type = event.target_asset_type

        if asset_type == 'charger':
            return self._add_charger_asset(building, event, time_step)

        if asset_type == 'deferrable_appliance':
            return self._add_deferrable_appliance_asset(building, event, time_step)

        if asset_type == 'pv':
            source_building = self._resolve_source_building(event)
            building.pv = deepcopy(self._resolve_source_pv(source_building))
            self._apply_object_overrides(building.pv, event.overrides)
            self._bind_building_runtime_context(building)
            building.pv.reset()
            self._set_building_time_step(building, time_step)
            building._refresh_pv_generation_from(time_step)
            self._refresh_building_after_mutation(building)
            self._topology_version += 1
            return True

        if asset_type == 'electrical_storage':
            source_building = self._resolve_source_building(event)
            building.electrical_storage = deepcopy(self._resolve_source_storage(source_building))
            self._apply_object_overrides(building.electrical_storage, event.overrides)
            self._bind_building_runtime_context(building)
            building.electrical_storage.reset()
            self._set_building_time_step(building, time_step)
            self._initialize_storage_at_activation(building)
            self._sync_electrical_storage_metadata(building)
            self._refresh_building_after_mutation(building)
            self._topology_version += 1
            return True

        raise ValueError(f'Unsupported target_asset_type for add_asset: {asset_type}')

    def _remove_asset(self, event: TopologyEvent, time_step: int) -> bool:
        building = self._resolve_target_building(event)
        asset_type = event.target_asset_type

        if asset_type == 'charger':
            charger_id = event.target_asset_id
            if charger_id is None:
                raise ValueError('remove_asset for charger requires target_asset_id.')

            chargers = list(building.electric_vehicle_chargers or [])
            remaining = [charger for charger in chargers if charger.charger_id != charger_id]

            if len(remaining) == len(chargers):
                return False

            building.electric_vehicle_chargers = remaining
            self._sync_charger_metadata(building)
            self._refresh_building_after_mutation(building)
            self._set_building_time_step(building, time_step)
            self._topology_version += 1
            return True

        if asset_type == 'deferrable_appliance':
            appliance_id = event.target_asset_id
            if appliance_id is None:
                raise ValueError('remove_asset for deferrable_appliance requires target_asset_id.')

            appliances = list(building.deferrable_appliances or [])
            removed = [appliance for appliance in appliances if appliance.name == appliance_id]
            remaining = [appliance for appliance in appliances if appliance.name != appliance_id]

            if len(remaining) == len(appliances):
                return False

            for appliance in removed:
                if hasattr(appliance, 'cancel_pending_and_running'):
                    appliance.cancel_pending_and_running(self._global_time_step(time_step), reason='asset_removed')

            building.deferrable_appliances = remaining
            self._sync_deferrable_appliance_metadata(building)
            self._refresh_building_after_mutation(building)
            self._set_building_time_step(building, time_step)
            self._topology_version += 1
            return True

        if asset_type == 'pv':
            building.pv = PV(0.0, seconds_per_time_step=building.seconds_per_time_step)
            self._bind_building_runtime_context(building)
            building.pv.reset()
            self._set_building_time_step(building, time_step)
            building._refresh_pv_generation_from(time_step)
            self._refresh_building_after_mutation(building)
            self._topology_version += 1
            return True

        if asset_type == 'electrical_storage':
            building.electrical_storage = Battery(0.0, 0.0, seconds_per_time_step=building.seconds_per_time_step)
            self._bind_building_runtime_context(building)
            building.electrical_storage.reset()
            self._set_building_time_step(building, time_step)
            self._sync_electrical_storage_metadata(building)
            self._refresh_building_after_mutation(building)
            self._topology_version += 1
            return True

        raise ValueError(f'Unsupported target_asset_type for remove_asset: {asset_type}')

    def _add_charger_asset(self, building: Building, event: TopologyEvent, time_step: int) -> bool:
        target_asset_id = event.target_asset_id
        if target_asset_id is None:
            raise ValueError('add_asset for charger requires target_asset_id.')

        if any(charger.charger_id == target_asset_id for charger in building.electric_vehicle_chargers or []):
            return False

        source_building = self._resolve_source_building(event)
        source_asset_id = event.source_asset_id if event.source_asset_id is not None else target_asset_id
        source_charger = self._resolve_source_charger(source_building, source_asset_id)
        cloned: Charger = deepcopy(source_charger)
        cloned.charger_id = target_asset_id
        self._apply_object_overrides(cloned, event.overrides)
        cloned.episode_tracker = building.episode_tracker
        cloned.random_seed = building.random_seed
        cloned.time_step_ratio = building.time_step_ratio
        cloned.reset()
        cloned.time_step = time_step

        chargers = list(building.electric_vehicle_chargers or [])
        chargers.append(cloned)
        building.electric_vehicle_chargers = chargers
        self._sync_charger_metadata(building)
        self._refresh_building_after_mutation(building)
        self._set_building_time_step(building, time_step)

        self._topology_version += 1
        return True

    def _exclude_previous_deferrable_requests(self, member_id, appliance):
        offered = set()
        for previous in self.historical_deferrable_appliances(member_id):
            if previous is not appliance and previous.name == appliance.name:
                offered.update(row['cycle_id'] for row in previous.service_audit()['records'] if row['included'])
        appliance.exclude_previously_offered_cycles(offered)

    def _add_deferrable_appliance_asset(self, building: Building, event: TopologyEvent, time_step: int) -> bool:
        target_asset_id = event.target_asset_id
        if target_asset_id is None:
            raise ValueError('add_asset for deferrable_appliance requires target_asset_id.')

        if any(appliance.name == target_asset_id for appliance in building.deferrable_appliances or []):
            return False

        source_building = self._resolve_source_building(event)
        source_asset_id = event.source_asset_id if event.source_asset_id is not None else target_asset_id
        source_appliance = self._resolve_source_deferrable_appliance(source_building, source_asset_id)
        cloned: DeferrableAppliance = deepcopy(source_appliance)
        cloned.name = target_asset_id
        self._apply_object_overrides(cloned, event.overrides)
        cloned.episode_tracker = building.episode_tracker
        cloned.random_seed = building.random_seed
        cloned.time_step_ratio = building.time_step_ratio
        cloned.reset()
        cloned.time_step = time_step
        cloned.skip_cycles_before(self._global_time_step(time_step))
        self._exclude_previous_deferrable_requests(building.name, cloned)

        appliances = list(building.deferrable_appliances or [])
        appliances.append(cloned)
        building.deferrable_appliances = appliances
        self._sync_deferrable_appliance_metadata(building)
        self._refresh_building_after_mutation(building)
        self._set_building_time_step(building, time_step)

        self._topology_version += 1
        return True

    def _resolve_target_building(self, event: TopologyEvent) -> Building:
        member_id = event.target_member_id
        if member_id is None:
            raise ValueError(f'{event.operation} requires target_member_id.')

        building = self._member_pool.get(member_id)
        if building is None:
            raise ValueError(f"Unknown target_member_id '{member_id}' in topology event '{event.event_id}'.")

        if member_id not in self._active_member_ids:
            raise ValueError(f"target_member_id '{member_id}' is inactive. Activate member before asset mutation.")

        return building

    def _resolve_source_building(self, event: TopologyEvent) -> Building:
        source_member_id = event.source_member_id if event.source_member_id is not None else event.target_member_id

        if source_member_id is None:
            raise ValueError(f"{event.operation} requires source_member_id or target_member_id.")

        source_building = self._member_pool.get(source_member_id)
        if source_building is None:
            raise ValueError(f"Unknown source_member_id '{source_member_id}' in topology event '{event.event_id}'.")

        return source_building

    def _resolve_source_charger(self, source_building: Building, source_asset_id: str):
        if source_asset_id is None:
            raise ValueError('source_asset_id is required for charger add_asset operations.')

        for charger in source_building.electric_vehicle_chargers or []:
            if charger.charger_id == source_asset_id:
                return charger

        # A remove -> reinstall sequence must be able to recover the exact
        # schema-loaded charger, including its independent EV schedule.  The
        # initial structure snapshot is deliberately retained across topology
        # mutations and resets, so it is the canonical template pool when the
        # live asset has already been removed.
        snapshot = self._initial_building_structures.get(source_building.name)
        for charger in (() if snapshot is None else snapshot.electric_vehicle_chargers):
            if charger.charger_id == source_asset_id:
                return charger

        raise ValueError(f"Source charger '{source_asset_id}' was not found in member '{source_building.name}'.")

    def _resolve_source_deferrable_appliance(self, source_building: Building, source_asset_id: str):
        if source_asset_id is None:
            raise ValueError('source_asset_id is required for deferrable_appliance add_asset operations.')

        for appliance in source_building.deferrable_appliances or []:
            if appliance.name == source_asset_id:
                return appliance

        snapshot = self._initial_building_structures.get(source_building.name)
        for appliance in (() if snapshot is None else snapshot.deferrable_appliances):
            if appliance.name == source_asset_id:
                return appliance

        raise ValueError(f"Source deferrable appliance '{source_asset_id}' was not found in member '{source_building.name}'.")

    def _resolve_source_pv(self, source_building: Building) -> PV:
        pv = getattr(source_building, 'pv', None)
        if pv is not None and float(getattr(pv, 'nominal_power', 0.0)) > 0.0:
            return pv

        snapshot = self._initial_building_structures.get(source_building.name)
        if snapshot is not None and float(getattr(snapshot.pv, 'nominal_power', 0.0)) > 0.0:
            return snapshot.pv

        raise ValueError(f"Source PV was not found in member '{source_building.name}'.")

    def _resolve_source_storage(self, source_building: Building) -> Battery:
        storage = getattr(source_building, 'electrical_storage', None)
        if storage is not None and self._has_electrical_storage_asset(source_building):
            return storage

        snapshot = self._initial_building_structures.get(source_building.name)
        if snapshot is not None:
            capacity = float(getattr(snapshot.electrical_storage, 'capacity', 0.0))
            nominal_power = float(getattr(snapshot.electrical_storage, 'nominal_power', 0.0))
            if capacity > 0.0 and nominal_power > 0.0:
                return snapshot.electrical_storage

        raise ValueError(f"Source electrical storage was not found in member '{source_building.name}'.")

    def _refresh_building_after_mutation(self, building: Building):
        self._bind_building_runtime_context(building)

        if hasattr(building, '_update_charger_lookup'):
            building._update_charger_lookup()

        if hasattr(building, '_initialize_charging_constraints'):
            building._initialize_charging_constraints(
                getattr(building, '_charging_constraints_config', {}) or {},
                electrical_service=getattr(building, '_electrical_service_config', {}) or {},
                electrical_storage_phase_connection=getattr(building, '_electrical_storage_phase_connection', None),
            )

        self._sync_dynamic_asset_metadata(building)
        building.observation_space = building.estimate_observation_space(include_all=False, normalize=False)
        building.action_space = building.estimate_action_space()

    def _sync_dynamic_asset_metadata(self, building: Building):
        self._sync_charger_metadata(building)
        self._sync_deferrable_appliance_metadata(building)
        self._sync_electrical_storage_metadata(building)

    def _sync_charger_metadata(self, building: Building):
        if not hasattr(building, 'observation_metadata') or not hasattr(building, 'action_metadata'):
            return

        charger_observation_prefixes = (
            'electric_vehicle_charger_',
            'connected_electric_vehicle_at_charger_',
            'incoming_electric_vehicle_at_charger_',
        )
        for key in list(building.observation_metadata.keys()):
            if key.startswith(charger_observation_prefixes):
                building.observation_metadata[key] = False

        for key in list(building.action_metadata.keys()):
            if key.startswith('electric_vehicle_storage_'):
                building.action_metadata[key] = False

        global_charger_action_inactive = self._is_action_inactive_for_building(
            building,
            'electric_vehicle_storage',
        )

        for charger in building.electric_vehicle_chargers or []:
            charger_id = charger.charger_id

            if self._charger_observation_flags.get('electric_vehicle_charger_connected_state', False):
                building.observation_metadata[f'electric_vehicle_charger_{charger_id}_connected_state'] = True

            if self._charger_observation_flags.get('connected_electric_vehicle_at_charger_departure_time', False):
                building.observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_departure_time'] = True

            if self._charger_observation_flags.get('connected_electric_vehicle_at_charger_required_soc_departure', False):
                building.observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_required_soc_departure'] = True

            if self._charger_observation_flags.get('connected_electric_vehicle_at_charger_soc', False):
                building.observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_soc'] = True

            if self._charger_observation_flags.get('connected_electric_vehicle_at_charger_battery_capacity', False):
                building.observation_metadata[f'connected_electric_vehicle_at_charger_{charger_id}_battery_capacity'] = True

            if self._charger_observation_flags.get('electric_vehicle_charger_incoming_state', False):
                building.observation_metadata[f'electric_vehicle_charger_{charger_id}_incoming_state'] = True

            if self._charger_observation_flags.get('incoming_electric_vehicle_at_charger_estimated_arrival_time', False):
                building.observation_metadata[f'incoming_electric_vehicle_at_charger_{charger_id}_estimated_arrival_time'] = True

            if self._charger_observation_flags.get('incoming_electric_vehicle_at_charger_estimated_soc_arrival', False):
                building.observation_metadata[f'incoming_electric_vehicle_at_charger_{charger_id}_estimated_soc_arrival'] = True

            if self._charger_action_enabled and not global_charger_action_inactive and not self._is_action_inactive_for_building(
                building,
                f'electric_vehicle_storage_{charger_id}',
            ):
                building.action_metadata[f'electric_vehicle_storage_{charger_id}'] = True

    def _sync_deferrable_appliance_metadata(self, building: Building):
        if not hasattr(building, 'observation_metadata') or not hasattr(building, 'action_metadata'):
            return

        for key in list(building.observation_metadata.keys()):
            if key.startswith('deferrable_appliance_'):
                building.observation_metadata[key] = False

        for key in list(building.action_metadata.keys()):
            if key.startswith('deferrable_appliance_'):
                building.action_metadata[key] = False

        schema = self.env.schema if isinstance(getattr(self.env, 'schema', None), Mapping) else {}
        helper_observations = {
            key: parse_bool(value.get('active', False), default=False, path=f'observations.{key}.active')
            for key, value in (schema.get('deferrable_appliance_observations_helper', {}) or {}).items()
        }
        if not helper_observations:
            helper_observations = {
                key: parse_bool(value.get('active', False), default=False, path=f'observations.{key}.active')
                for key, value in (schema.get('observations', {}) or {}).items()
                if str(key).startswith('deferrable_appliance_')
            }
        action_enabled = self._is_schema_action_active('deferrable_appliance')
        global_action_inactive = self._is_action_inactive_for_building(building, 'deferrable_appliance')

        for appliance in building.deferrable_appliances or []:
            for helper_name, enabled in helper_observations.items():
                if enabled:
                    feature_name = helper_name.replace('deferrable_appliance_', '', 1)
                    building.observation_metadata[f'deferrable_appliance_{appliance.name}_{feature_name}'] = True

            if action_enabled and not global_action_inactive and not self._is_action_inactive_for_building(
                building,
                f'deferrable_appliance_{appliance.name}',
            ):
                building.action_metadata[f'deferrable_appliance_{appliance.name}'] = True

    def _sync_electrical_storage_metadata(self, building: Building):
        has_storage = self._has_electrical_storage_asset(building)
        action_enabled = self._is_schema_action_active('electrical_storage')
        action_inactive = self._is_action_inactive_for_building(building, 'electrical_storage')

        if 'electrical_storage' in building.action_metadata:
            building.action_metadata['electrical_storage'] = bool(has_storage and action_enabled and not action_inactive)

        if 'electrical_storage_soc' in building.observation_metadata:
            building.observation_metadata['electrical_storage_soc'] = bool(
                has_storage and self._is_schema_observation_active('electrical_storage_soc')
            )

        if 'electrical_storage_electricity_consumption' in building.observation_metadata:
            building.observation_metadata['electrical_storage_electricity_consumption'] = bool(
                has_storage and self._is_schema_observation_active('electrical_storage_electricity_consumption')
            )

    @staticmethod
    def _has_electrical_storage_asset(building: Building) -> bool:
        battery = getattr(building, 'electrical_storage', None)
        if battery is None:
            return False

        capacity = getattr(battery, 'capacity', 0.0)
        nominal_power = getattr(battery, 'nominal_power', 0.0)
        return float(capacity) > 0.0 and float(nominal_power) > 0.0

    def _declared_inactive_actions(self, building: Building) -> Set[str]:
        cached = getattr(building, '_declared_inactive_actions', None)
        if isinstance(cached, (set, list, tuple)):
            return {str(value) for value in cached}

        schema = self.env.schema if isinstance(getattr(self.env, 'schema', None), Mapping) else {}
        building_schema = (schema.get('buildings', {}) or {}).get(getattr(building, 'name', ''), {})
        raw = (building_schema or {}).get('inactive_actions')
        if raw is None:
            return set()
        if not isinstance(raw, (list, tuple, set)):
            raw = [raw]
        return {str(value) for value in raw}

    def _is_action_inactive_for_building(self, building: Building, action_name: str) -> bool:
        return str(action_name) in self._declared_inactive_actions(building)

    @staticmethod
    def _apply_object_overrides(obj: Any, overrides: Mapping[str, Any]):
        if not isinstance(overrides, Mapping):
            return

        for key, value in overrides.items():
            if hasattr(obj, key):
                try:
                    setattr(obj, key, value)
                except Exception:
                    continue

    @staticmethod
    def _apply_building_overrides(building: Building, overrides: Mapping[str, Any]):
        if not isinstance(overrides, Mapping):
            return

        for key, value in overrides.items():
            if key in {'name', 'chargers', 'deferrable_appliances', 'electrical_storage', 'pv'}:
                continue
            if hasattr(building, key):
                try:
                    setattr(building, key, value)
                except Exception:
                    continue

    def _parse_events(self) -> List[TopologyEvent]:
        raw_events = []
        if isinstance(self.env.schema, Mapping):
            raw_events = self.env.schema.get('topology_events', []) or []

        events: List[TopologyEvent] = []

        for order, item in enumerate(raw_events):
            if not isinstance(item, Mapping):
                raise ValueError(f'topology_events[{order}] must be an object.')

            event_id = str(item.get('id', f'topology_event_{order}'))
            try:
                time_step = int(item.get('time_step'))
            except Exception as exc:
                raise ValueError(f"topology_events[{order}].time_step must be an integer.") from exc

            operation = str(item.get('operation', '')).strip().lower()
            if operation not in SUPPORTED_OPERATIONS:
                raise ValueError(
                    f"topology_events[{order}].operation='{operation}' is not supported."
                )

            target_asset_type = item.get('target_asset_type')
            if target_asset_type is not None:
                target_asset_type = str(target_asset_type).strip().lower()

            if operation in {'add_asset', 'remove_asset'} and target_asset_type not in SUPPORTED_ASSET_TYPES:
                raise ValueError(
                    f"topology_events[{order}] target_asset_type must be one of {sorted(SUPPORTED_ASSET_TYPES)}."
                )

            events.append(
                TopologyEvent(
                    event_id=event_id,
                    time_step=time_step,
                    operation=operation,
                    target_member_id=self._normalize_optional_str(item.get('target_member_id')),
                    target_asset_type=target_asset_type,
                    target_asset_id=self._normalize_optional_str(item.get('target_asset_id')),
                    source_member_id=self._normalize_optional_str(item.get('source_member_id')),
                    source_asset_id=self._normalize_optional_str(item.get('source_asset_id')),
                    overrides=deepcopy(item.get('overrides', {}) or {}),
                    order=order,
                )
            )

        events.sort(key=lambda e: (e.time_step, e.order, e.event_id))

        seen_ids: Set[str] = set()
        for event in events:
            if event.event_id in seen_ids:
                raise ValueError(f"Duplicate topology event id '{event.event_id}'.")
            seen_ids.add(event.event_id)

        return events

    @staticmethod
    def _normalize_optional_str(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return None if text == '' else text

    def _initial_member_include_flags(self) -> Mapping[str, bool]:
        flags: Dict[str, bool] = {}
        schema_buildings = {}

        if isinstance(self.env.schema, Mapping):
            schema_buildings = self.env.schema.get('buildings', {}) or {}

        for member_id in self._member_order:
            include = True
            schema_building = schema_buildings.get(member_id, {}) if isinstance(schema_buildings, Mapping) else {}
            include = parse_bool(
                schema_building.get('include', True),
                default=True,
                path=f'buildings.{member_id}.include',
            )
            flags[member_id] = bool(include)

        return flags

    def _collect_charger_observation_flags(self) -> Mapping[str, bool]:
        observations = {}
        if isinstance(self.env.schema, Mapping):
            observations = self.env.schema.get('observations', {}) or {}

        flags = {}
        for key in (
            'electric_vehicle_charger_connected_state',
            'connected_electric_vehicle_at_charger_departure_time',
            'connected_electric_vehicle_at_charger_required_soc_departure',
            'connected_electric_vehicle_at_charger_soc',
            'connected_electric_vehicle_at_charger_battery_capacity',
            'electric_vehicle_charger_incoming_state',
            'incoming_electric_vehicle_at_charger_estimated_arrival_time',
            'incoming_electric_vehicle_at_charger_estimated_soc_arrival',
        ):
            value = observations.get(key, {}) if isinstance(observations, Mapping) else {}
            active = parse_bool(
                value.get('active', False) if isinstance(value, Mapping) else False,
                default=False,
                path=f'observations.{key}.active',
            )
            flags[key] = bool(active)

        return flags

    def _is_schema_action_active(self, action_name: str) -> bool:
        actions = {}
        if isinstance(self.env.schema, Mapping):
            actions = self.env.schema.get('actions', {}) or {}

        action_data = actions.get(action_name, {}) if isinstance(actions, Mapping) else {}
        return bool(
            parse_bool(
                action_data.get('active', False) if isinstance(action_data, Mapping) else False,
                default=False,
                path=f'actions.{action_name}.active',
            )
        )

    def _is_schema_observation_active(self, observation_name: str) -> bool:
        observations = {}
        if isinstance(self.env.schema, Mapping):
            observations = self.env.schema.get('observations', {}) or {}

        obs_data = observations.get(observation_name, {}) if isinstance(observations, Mapping) else {}
        return bool(
            parse_bool(
                obs_data.get('active', False) if isinstance(obs_data, Mapping) else False,
                default=False,
                path=f'observations.{observation_name}.active',
            )
        )
