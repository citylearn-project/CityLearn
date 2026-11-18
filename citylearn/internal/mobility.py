"""Runtime service behind :mod:`citylearn.mobility`.

External chargers keep their schedule in an ordinary :class:`citylearn.data.ChargerSimulation`
whose rows start "away" and are written during the episode. Everything that reads charger rows
(association, arrival SOC, observations, KPIs, departure audit, business-as-usual reference) is
therefore unchanged. Environments without a provider and without external chargers never enter
this module's code paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

from citylearn.data import ChargerSimulation
from citylearn.mobility import MobilityInterface, MobilityProvider, _finite_number, _fraction, _steps

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv
    from citylearn.electric_vehicle import ElectricVehicle
    from citylearn.electric_vehicle_charger import Charger


EXTERNAL_SOURCE = 'external'
AWAY, CONNECTED, INCOMING = 3, 1, 2
UNKNOWN_STEPS = -1
UNKNOWN_SOC = -0.1


def parse_charger_simulation_source(value: Any, path: str) -> Optional[str]:
    """Return ``'external'`` for an external charger declaration, ``None`` for a schedule file."""

    if not isinstance(value, Mapping):
        return None

    unknown = sorted(set(value) - {'source'})
    if unknown:
        raise ValueError(f'{path}: unknown keys {unknown}; only "source" is supported.')

    source = value.get('source')
    if source != EXTERNAL_SOURCE:
        raise ValueError(f'{path}.source must be "{EXTERNAL_SOURCE}", got {source!r}.')

    return EXTERNAL_SOURCE


def external_charger_simulation(rows: int) -> ChargerSimulation:
    """Schedule of an external charger: ``rows`` time steps, all away until a provider writes them."""

    rows = int(rows)
    simulation = ChargerSimulation(
        electric_vehicle_charger_state=[AWAY] * rows,
        electric_vehicle_id=[''] * rows,
        electric_vehicle_departure_time=[np.nan] * rows,
        electric_vehicle_required_soc_departure=[np.nan] * rows,
        electric_vehicle_estimated_arrival_time=[np.nan] * rows,
        electric_vehicle_estimated_soc_arrival=[np.nan] * rows,
        electric_vehicle_session_id=[''] * rows,
        noise_std=0.0,
    )
    simulation.electric_vehicle_current_soc = np.full(rows, UNKNOWN_SOC, dtype='float32')
    simulation.electric_vehicle_connected_seconds = np.full(rows, np.nan, dtype='float64')
    simulation.electric_vehicle_discharge_soc_floor = np.full(rows, np.nan, dtype='float64')
    simulation.electric_vehicle_connected_since_seconds = np.full(rows, np.nan, dtype='float64')
    simulation.source = EXTERNAL_SOURCE
    return simulation


def is_external(charger: Any) -> bool:
    simulation = getattr(charger, 'charger_simulation', None)
    return getattr(simulation, 'source', None) == EXTERNAL_SOURCE


_ROW_FIELDS = (
    'electric_vehicle_charger_state',
    'electric_vehicle_id',
    'electric_vehicle_session_id',
    'electric_vehicle_departure_time',
    'electric_vehicle_required_soc_departure',
    'electric_vehicle_estimated_arrival_time',
    'electric_vehicle_estimated_soc_arrival',
    'electric_vehicle_connected_seconds',
    'electric_vehicle_discharge_soc_floor',
    'electric_vehicle_connected_since_seconds',
)


class CityLearnMobilityService:
    """Owns the mobility provider, the external charger rows and the provider's write phase."""

    def __init__(self, env: 'CityLearnEnv'):
        self.env = env
        self._provider: Optional[MobilityProvider] = None
        self._interface: Optional[MobilityInterface] = None
        self._writing = False
        self._external: Dict[str, 'Charger'] = {}
        self._chargers: Dict[str, 'Charger'] = {}
        self._names: Dict[str, List[str]] = {}
        self._vehicles: Dict[str, 'ElectricVehicle'] = {}
        self._soc_set_this_step = set()
        self._soc_writes: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        self.active = False

    # ------------------------------------------------------------- configuration

    @property
    def provider(self) -> Optional[MobilityProvider]:
        return self._provider

    @provider.setter
    def provider(self, provider: Optional[MobilityProvider]):
        if provider is not None and not (
            callable(getattr(provider, 'reset', None)) and callable(getattr(provider, 'update', None))
        ):
            raise TypeError(
                'mobility_provider must implement reset(env) and update(env, time_step); '
                f'got {type(provider).__name__}.'
            )

        self._provider = provider
        self.active = provider is not None or len(self._external) > 0

    @property
    def interface(self) -> MobilityInterface:
        if self._interface is None:
            self._interface = MobilityInterface(self)

        return self._interface

    def refresh(self):
        """Index chargers and vehicles of the current building and vehicle lists."""

        env = self.env
        self._chargers = {}
        self._external = {}
        self._names = {}

        for building in env.buildings:
            for charger in building.electric_vehicle_chargers or []:
                key = f'{building.name}/{charger.charger_id}'
                self._chargers[key] = charger
                self._names.setdefault(str(charger.charger_id), []).append(key)

                if is_external(charger):
                    self._external[key] = charger

        self._vehicles = {ev.name: ev for ev in env.electric_vehicles}
        self.active = self._provider is not None or len(self._external) > 0

    @property
    def external_charger_ids(self) -> List[str]:
        return [self._display_id(key) for key in self._external]

    @property
    def external_vehicle_ids(self) -> List[str]:
        return [name for name, ev in self._vehicles.items() if bool(getattr(ev, 'external', False))]

    @property
    def vehicle_ids(self) -> List[str]:
        return list(self._vehicles)

    def _display_id(self, key: str) -> str:
        building, name = key.split('/', 1)
        return name if len(self._names.get(name, [])) == 1 else key

    def managed_vehicle_names(self):
        """Vehicles whose SOC CityLearn must not drift randomly at the current time step."""

        names = set(self._soc_set_this_step)
        names.update(name for name, ev in self._vehicles.items() if bool(getattr(ev, 'external', False)))
        return names

    # --------------------------------------------------------------- lifecycle

    def reset(self):
        """Clear the external rows of the new episode and run the provider's ``reset``."""

        self.refresh()
        self._soc_set_this_step = set()
        self._soc_writes = {}

        if not self.active:
            return

        for charger in self._external.values():
            # The episode's view of the rows: earlier episodes may have written them.
            self._write_away(charger.charger_simulation, slice(None))

        self._call_provider(lambda provider: provider.reset(self.env))

    def advance(self, time_step: int, *, call_provider: bool):
        """Carry the external rows into ``time_step``, then run the provider's ``update``."""

        self._soc_set_this_step = set()

        for charger in self._external.values():
            self._carry_forward(charger.charger_simulation, int(time_step))

        if call_provider:
            self._call_provider(lambda provider: provider.update(self.env, int(time_step)))

    def before_association(self):
        """Record the SOC a session on an external charger starts with.

        The runtime arrival, the KPI arrival reference and the departure audit all read the
        session's first row of ``electric_vehicle_current_soc``. Without an explicit value it is
        the vehicle's own SOC, so the session continues from the SOC CityLearn holds.
        """

        t = int(self.env.time_step)
        for charger in self._external.values():
            simulation = charger.charger_simulation
            if not self._session_starts(simulation, t):
                continue

            reference = simulation.electric_vehicle_current_soc
            if 0.0 <= float(reference[t]) <= 1.0:
                continue

            ev = self._vehicles.get(simulation.electric_vehicle_id[t])
            if ev is not None:
                reference[t] = ev.battery.soc[t]

    def _call_provider(self, call):
        if self._provider is None:
            return

        self._writing = True
        try:
            call(self._provider)
        finally:
            self._writing = False

    # ---------------------------------------------------------------- row helpers

    @staticmethod
    def _write_away(simulation, t):
        simulation.electric_vehicle_charger_state[t] = AWAY
        simulation.electric_vehicle_id[t] = ''
        simulation.electric_vehicle_session_id[t] = ''
        simulation.electric_vehicle_departure_time[t] = UNKNOWN_STEPS
        simulation.electric_vehicle_required_soc_departure[t] = UNKNOWN_SOC
        simulation.electric_vehicle_estimated_arrival_time[t] = UNKNOWN_STEPS
        simulation.electric_vehicle_estimated_soc_arrival[t] = UNKNOWN_SOC
        simulation.electric_vehicle_current_soc[t] = UNKNOWN_SOC
        simulation.electric_vehicle_connected_seconds[t] = np.nan
        simulation.electric_vehicle_discharge_soc_floor[t] = np.nan
        simulation.electric_vehicle_connected_since_seconds[t] = np.nan

    @staticmethod
    def _count_down(value) -> int:
        value = int(value)
        return UNKNOWN_STEPS if value < 0 else max(value - 1, 0)

    def _carry_forward(self, simulation, t: int):
        if t <= 0 or t >= len(simulation.electric_vehicle_charger_state):
            return

        previous = t - 1
        state = simulation.electric_vehicle_charger_state[previous]
        self._write_away(simulation, t)

        if state == CONNECTED:
            simulation.electric_vehicle_charger_state[t] = CONNECTED
            simulation.electric_vehicle_id[t] = simulation.electric_vehicle_id[previous]
            simulation.electric_vehicle_session_id[t] = simulation.electric_vehicle_session_id[previous]
            simulation.electric_vehicle_departure_time[t] = self._count_down(
                simulation.electric_vehicle_departure_time[previous]
            )
            simulation.electric_vehicle_required_soc_departure[t] = (
                simulation.electric_vehicle_required_soc_departure[previous]
            )
            simulation.electric_vehicle_discharge_soc_floor[t] = (
                simulation.electric_vehicle_discharge_soc_floor[previous]
            )

        elif state == INCOMING:
            simulation.electric_vehicle_charger_state[t] = INCOMING
            simulation.electric_vehicle_id[t] = simulation.electric_vehicle_id[previous]
            simulation.electric_vehicle_estimated_arrival_time[t] = self._count_down(
                simulation.electric_vehicle_estimated_arrival_time[previous]
            )
            simulation.electric_vehicle_estimated_soc_arrival[t] = (
                simulation.electric_vehicle_estimated_soc_arrival[previous]
            )

    @staticmethod
    def _session_starts(simulation, t: int) -> bool:
        if simulation.electric_vehicle_charger_state[t] != CONNECTED:
            return False

        if t == 0:
            return True

        previous = t - 1
        return not (
            simulation.electric_vehicle_charger_state[previous] == CONNECTED
            and simulation.electric_vehicle_id[previous] == simulation.electric_vehicle_id[t]
            and simulation.electric_vehicle_session_id[previous] == simulation.electric_vehicle_session_id[t]
        )

    # ------------------------------------------------------------- validation

    def _require_writes(self, operation: str):
        if not self._writing:
            raise RuntimeError(
                f'env.mobility.{operation}() is accepted only while CityLearn calls the mobility provider '
                '(MobilityProvider.reset or MobilityProvider.update).'
            )

    def _resolve_charger(self, charger_id: Any, *, external: bool) -> Tuple[str, 'Charger']:
        key = str(charger_id)
        if key not in self._chargers:
            matches = self._names.get(key, [])
            if len(matches) > 1:
                raise ValueError(
                    f"Charger ID '{key}' is used by several buildings; write one of {sorted(matches)}."
                )
            if len(matches) == 0:
                known = sorted(self._display_id(k) for k in (self._external if external else self._chargers))
                raise ValueError(f"Unknown charger '{key}'. Known {'external ' if external else ''}chargers: {known}.")
            key = matches[0]

        charger = self._chargers[key]
        if external and key not in self._external:
            raise ValueError(
                f"Charger '{charger_id}' reads its schedule from a file. Only chargers declared with "
                '"charger_simulation": {"source": "external"} accept mobility writes.'
            )

        return key, charger

    def _resolve_vehicle(self, ev_id: Any) -> 'ElectricVehicle':
        ev = self._vehicles.get(str(ev_id))
        if ev is None:
            raise ValueError(f"Unknown electric vehicle '{ev_id}'. Known vehicles: {sorted(self._vehicles)}.")

        return ev

    def _holder(self, ev_name: str, t: int, exclude: Optional[str] = None) -> Optional[str]:
        for key, charger in self._chargers.items():
            if key == exclude:
                continue
            simulation = charger.charger_simulation
            states = getattr(simulation, 'electric_vehicle_charger_state', None)
            ids = getattr(simulation, 'electric_vehicle_id', None)
            if states is None or ids is None or t >= len(states) or t >= len(ids):
                continue
            if states[t] == CONNECTED and ids[t] == ev_name:
                return key

        return None

    def _in_running_session(self, ev_name: str, t: int) -> Optional[str]:
        """Charger at which ``ev_name`` continues a session from the previous time step."""

        if t <= 0:
            return None

        for key, charger in self._chargers.items():
            simulation = charger.charger_simulation
            states = getattr(simulation, 'electric_vehicle_charger_state', None)
            ids = getattr(simulation, 'electric_vehicle_id', None)
            if states is None or ids is None or t >= len(states):
                continue
            if states[t] != CONNECTED or ids[t] != ev_name:
                continue
            sessions = getattr(simulation, 'electric_vehicle_session_id', None)
            same_session = sessions is None or sessions[t - 1] == sessions[t]
            if states[t - 1] == CONNECTED and ids[t - 1] == ev_name and same_session:
                return key

        return None

    def _countdown(self, value: Any, name: str) -> int:
        steps = _steps(value, name)
        return min(steps, max(int(self.env.time_steps), 1))

    # ------------------------------------------------------------------ writes

    def connect(
        self, charger_id, ev_id, *, soc=None, departure_steps=None, required_soc=None, session_id=None,
        connected_seconds=None, discharge_soc_floor=None, connected_since_seconds=None,
    ):
        self._require_writes('connect')
        key, charger = self._resolve_charger(charger_id, external=True)
        ev = self._resolve_vehicle(ev_id)
        t = int(self.env.time_step)
        simulation = charger.charger_simulation

        soc = None if soc is None else _fraction(soc, 'soc')
        required_soc = None if required_soc is None else _fraction(required_soc, 'required_soc')
        discharge_soc_floor = None if discharge_soc_floor is None else _fraction(discharge_soc_floor, 'discharge_soc_floor')
        departure_steps = None if departure_steps is None else self._countdown(departure_steps, 'departure_steps')
        if connected_seconds is not None:
            connected_seconds = _finite_number(connected_seconds, 'connected_seconds')
            step_seconds = float(self.env.seconds_per_time_step)
            if not 0.0 <= connected_seconds <= step_seconds:
                raise ValueError(f'connected_seconds must be in [0, {step_seconds:g}], got {connected_seconds!r}.')
        if connected_since_seconds is not None:
            connected_since_seconds = _finite_number(connected_since_seconds, 'connected_since_seconds')
            step_seconds = float(self.env.seconds_per_time_step)
            plugged_in_at = max(-connected_since_seconds, 0.0)
            end = step_seconds if connected_seconds is None else connected_seconds
            if plugged_in_at > end:
                raise ValueError(
                    f'connected_since_seconds={connected_since_seconds!r} plugs the vehicle in after it leaves '
                    f'({end:g} s into the step).'
                )
        if session_id is not None:
            session_id = str(session_id)
            if session_id.strip() in {'', 'nan'}:
                raise ValueError('session_id must be a non-empty string.')

        state = simulation.electric_vehicle_charger_state[t]
        current_ev = simulation.electric_vehicle_id[t]
        if state == CONNECTED and current_ev != ev.name:
            raise ValueError(
                f"Charger '{charger_id}' is connected to '{current_ev}' at time step {t}; "
                f"call away('{charger_id}') before connecting '{ev.name}'."
            )

        holder = self._holder(ev.name, t, exclude=key)
        if holder is not None:
            raise ValueError(
                f"'{ev.name}' is connected to charger '{self._display_id(holder)}' at time step {t}; "
                'call away() for that charger first. A vehicle can be connected to one charger only.'
            )

        same_session = (
            state == CONNECTED
            and current_ev == ev.name
            and (session_id is None or session_id == simulation.electric_vehicle_session_id[t])
        )

        if same_session:
            if soc is not None and not self._session_starts(simulation, t):
                raise ValueError(
                    f"soc is accepted only when a session starts; '{ev.name}' continues its session at "
                    f"'{charger_id}'. CityLearn computes the SOC of a running session."
                )
            if connected_since_seconds is not None and not self._session_starts(simulation, t):
                raise ValueError(
                    f"connected_since_seconds is accepted only when a session starts; '{ev.name}' continues "
                    f"its session at '{charger_id}'."
                )
        else:
            self._write_away(simulation, t)
            simulation.electric_vehicle_charger_state[t] = CONNECTED
            simulation.electric_vehicle_id[t] = ev.name
            simulation.electric_vehicle_session_id[t] = (
                session_id if session_id is not None else f'{self._display_id(key)}:{ev.name}:{t}'
            )

        if departure_steps is not None:
            simulation.electric_vehicle_departure_time[t] = departure_steps
        if required_soc is not None:
            simulation.electric_vehicle_required_soc_departure[t] = required_soc
        if discharge_soc_floor is not None:
            simulation.electric_vehicle_discharge_soc_floor[t] = discharge_soc_floor
        if connected_seconds is not None:
            simulation.electric_vehicle_connected_seconds[t] = connected_seconds
        if connected_since_seconds is not None:
            simulation.electric_vehicle_connected_since_seconds[t] = connected_since_seconds
        if soc is not None:
            simulation.electric_vehicle_current_soc[t] = UNKNOWN_SOC
            self._set_soc(ev, soc)

    def incoming(self, charger_id, ev_id, *, arrival_steps=None, soc_on_arrival=None):
        self._require_writes('incoming')
        _, charger = self._resolve_charger(charger_id, external=True)
        ev = self._resolve_vehicle(ev_id)
        t = int(self.env.time_step)
        simulation = charger.charger_simulation
        arrival_steps = None if arrival_steps is None else self._countdown(arrival_steps, 'arrival_steps')
        soc_on_arrival = None if soc_on_arrival is None else _fraction(soc_on_arrival, 'soc_on_arrival')

        current_ev = simulation.electric_vehicle_id[t]
        if simulation.electric_vehicle_charger_state[t] == CONNECTED and current_ev != ev.name:
            raise ValueError(
                f"Charger '{charger_id}' is connected to '{current_ev}' at time step {t}; "
                f"call away('{charger_id}') before announcing '{ev.name}'."
            )

        # A row holds one state: announcing the vehicle connected here means it has left at this
        # step and will come back, so its session ends as with away().
        self._write_away(simulation, t)
        simulation.electric_vehicle_charger_state[t] = INCOMING
        simulation.electric_vehicle_id[t] = ev.name
        if arrival_steps is not None:
            simulation.electric_vehicle_estimated_arrival_time[t] = arrival_steps
        if soc_on_arrival is not None:
            simulation.electric_vehicle_estimated_soc_arrival[t] = soc_on_arrival

    def away(self, charger_id):
        self._require_writes('away')
        _, charger = self._resolve_charger(charger_id, external=True)
        self._write_away(charger.charger_simulation, int(self.env.time_step))

    def set_vehicle_soc(self, ev_id, soc):
        self._require_writes('set_vehicle_soc')
        ev = self._resolve_vehicle(ev_id)
        soc = _fraction(soc, 'soc')
        t = int(self.env.time_step)
        running = self._in_running_session(ev.name, t)
        if running is not None:
            raise ValueError(
                f"'{ev.name}' continues its charging session at '{self._display_id(running)}' at time step {t}; "
                'CityLearn computes the SOC of a running session. Call away() first if the vehicle has left.'
            )

        self._set_soc(ev, soc)

    def _set_soc(self, ev: 'ElectricVehicle', soc: float):
        battery = ev.battery
        t = int(battery.time_step)
        before = float(battery.soc[t])
        battery.force_set_soc(float(soc))
        # An SOC reported by the mobility simulation is known before this step's control action.
        ev._arrival_soc_time_step = t
        self._soc_set_this_step.add(ev.name)
        self._record_soc_write(ev.name, t, before, float(battery.soc[t]))

    def _record_soc_write(self, name: str, t: int, before: float, after: float):
        writes = self._soc_writes.get(name)
        if writes is None:
            rows = max(int(self.env.time_steps), t + 1)
            writes = (np.full(rows, np.nan, dtype='float32'), np.full(rows, np.nan, dtype='float32'))
            self._soc_writes[name] = writes

        before_values, after_values = writes
        if t < len(before_values):
            if np.isnan(before_values[t]):
                before_values[t] = before
            after_values[t] = after

    # ------------------------------------------------------------------- reads

    def vehicle_soc(self, ev_id) -> float:
        battery = self._resolve_vehicle(ev_id).battery
        return float(battery.soc[int(battery.time_step)])

    def charger_energy_kwh(self, charger_id) -> float:
        _, charger = self._resolve_charger(charger_id, external=False)
        t = int(self.env.time_step) - 1
        consumption = charger.electricity_consumption
        if t < 0 or t >= len(consumption):
            return 0.0

        return float(consumption[t])

    def charger_power_kw(self, charger_id) -> float:
        step_hours = max(float(self.env.seconds_per_time_step) / 3600.0, 1.0e-12)
        return self.charger_energy_kwh(charger_id) / step_hours

    # ------------------------------------------------------------------- replay

    def replay_provider(self) -> Optional['MobilityReplay']:
        """Provider that replays this episode's mobility in a business-as-usual sidecar."""

        if self._provider is None or (len(self._external) == 0 and len(self._soc_writes) == 0):
            return None

        rows = {}
        for key, charger in self._external.items():
            simulation = charger.charger_simulation
            rows[key] = {name: np.array(getattr(simulation, name), copy=True) for name in _ROW_FIELDS}

        writes = {name: (before.copy(), after.copy()) for name, (before, after) in self._soc_writes.items()}
        return MobilityReplay(rows, writes, int(self.env.time_step))


class MobilityReplay:
    """Replays recorded external charger rows and SOC changes in another environment.

    The rows are copied as written. An SOC that the provider set is applied as the same SOC when
    the replaying vehicle had the same SOC before the write, and otherwise as the same change, so
    that the replaying run keeps its own charging history and adds the same driving consumption.
    """

    def __init__(
        self,
        rows: Mapping[str, Mapping[str, np.ndarray]],
        soc_writes: Mapping[str, Tuple[np.ndarray, np.ndarray]],
        recorded_time_step: int,
    ):
        self._rows = rows
        self._soc_writes = soc_writes
        self._recorded_time_step = int(recorded_time_step)

    def reset(self, env: 'CityLearnEnv') -> None:
        self._apply(env, 0)

    def update(self, env: 'CityLearnEnv', time_step: int) -> None:
        self._apply(env, int(time_step))

    def _apply(self, env: 'CityLearnEnv', t: int):
        if t > self._recorded_time_step:
            return

        service: CityLearnMobilityService = env._mobility_service
        for name, (before_values, after_values) in self._soc_writes.items():
            ev = service._vehicles.get(name)
            if ev is None or t >= len(after_values) or np.isnan(after_values[t]):
                continue
            before = float(ev.battery.soc[int(ev.battery.time_step)])
            if np.float32(before) == before_values[t]:
                value = float(after_values[t])
            else:
                value = float(np.clip(before + float(after_values[t]) - float(before_values[t]), 0.0, 1.0))
            service._set_soc(ev, value)

        for key, fields in self._rows.items():
            charger = service._external.get(key)
            if charger is None:
                continue
            simulation = charger.charger_simulation
            if t >= len(simulation.electric_vehicle_charger_state):
                continue
            for name, values in fields.items():
                if t < len(values):
                    getattr(simulation, name)[t] = values[t]
            simulation.electric_vehicle_current_soc[t] = UNKNOWN_SOC
