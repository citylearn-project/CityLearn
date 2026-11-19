"""Drive electric vehicle connections at runtime from an external mobility simulator.

A charger whose schema entry declares ``"charger_simulation": {"source": "external"}`` has no
schedule file. Its schedule rows (connected, incoming or away, EV, session, departure countdown,
required departure SOC, estimated arrival) are written while the episode runs by a
:class:`MobilityProvider`, for example an adapter around SUMO or CARLA. CityLearn then uses those
rows exactly like rows read from a file: for the charger-EV association, the arrival SOC, the
observations, the KPIs, the departure audit and the business-as-usual reference.

The provider writes through :attr:`citylearn.citylearn.CityLearnEnv.mobility`, a
:class:`MobilityInterface`. Writes are accepted only while CityLearn calls the provider:

* :meth:`MobilityProvider.reset` runs inside ``env.reset()``, after the buildings and vehicles are
  reset and before the chargers are associated for time step 0.
* :meth:`MobilityProvider.update` runs inside ``env.step()``, after the energy of the finished
  interval has been computed and the environment has advanced to ``time_step``, and before the
  chargers are associated for ``time_step``. The observations that ``step()`` returns therefore
  already show the connections written here. It is not called for the terminal transition, after
  which no action is taken; if the provider defines ``finalize(env)``, CityLearn calls that
  read-only hook instead so the last interval's settled energy and SOC can be read inside ``step()``.

See ``docs/mobility_provider.md`` for the contract, the schema keys and an example.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from citylearn.citylearn import CityLearnEnv
    from citylearn.internal.mobility import CityLearnMobilityService

__all__ = ['MobilityProvider', 'MobilityInterface']


@runtime_checkable
class MobilityProvider(Protocol):
    """Source of EV connections, arrivals, departures and driving SOC changes.

    Any object with these two methods can be passed as ``CityLearnEnv(mobility_provider=...)`` or
    assigned to ``env.mobility_provider`` before ``env.reset()``. An optional ``finalize(env)``
    method, when present, is called after the terminal transition settles (read-only).
    """

    def reset(self, env: 'CityLearnEnv') -> None:
        """Start a new episode and write the mobility state of time step 0.

        Called by every ``env.reset()``, including the one the constructor runs when the provider
        is passed to it.
        """

    def update(self, env: 'CityLearnEnv', time_step: int) -> None:
        """Write the mobility state of ``time_step``, the new current time step.

        The energy of interval ``time_step - 1`` is final; read it with
        :meth:`MobilityInterface.vehicle_soc` and :meth:`MobilityInterface.charger_energy_kwh`.
        The provider may advance the mobility simulation to ``time_step`` here.
        """


def _finite_number(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} must be a number, got {value!r}.') from None

    if not math.isfinite(number):
        raise ValueError(f'{name} must be finite, got {value!r}.')

    return number


def _fraction(value: Any, name: str) -> float:
    number = _finite_number(value, name)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f'{name} must be in [0, 1], got {value!r}.')

    return number


def _steps(value: Any, name: str) -> int:
    number = _finite_number(value, name)
    if number < 0.0 or number != int(number):
        raise ValueError(f'{name} must be a non-negative whole number of time steps, got {value!r}.')

    return int(number)


class MobilityInterface:
    """Validated write and read access to the external chargers and vehicles of an environment.

    Charger IDs are the charger names of the schema. A name used by more than one building is
    written ``'<building>/<charger>'``. Vehicle IDs are the names in ``electric_vehicles_def``.
    State of charge (SOC) values are fractions in [0, 1].

    A connection persists from one time step to the next until :meth:`away` or another call
    changes it; the departure and arrival countdowns decrease by one per step and stop at 0.
    ``connected_seconds`` applies to one time step only.
    """

    def __init__(self, service: 'CityLearnMobilityService'):
        self._service = service

    # ------------------------------------------------------------------ writes

    def connect(
        self,
        charger_id: str,
        ev_id: str,
        *,
        soc: Optional[float] = None,
        departure_steps: Optional[int] = None,
        required_soc: Optional[float] = None,
        session_id: Optional[str] = None,
        connected_seconds: Optional[float] = None,
        discharge_soc_floor: Optional[float] = None,
        charge_soc_ceiling: Optional[float] = None,
        connected_since_seconds: Optional[float] = None,
        departure_seconds: Optional[float] = None,
    ) -> None:
        """Plug ``ev_id`` into the external charger ``charger_id`` at the current time step.

        Parameters
        ----------
        charger_id: str
            External charger.
        ev_id: str
            Vehicle. It must not be connected to another charger at this time step.
        soc: float, optional
            SOC on arrival. Allowed only when this call starts a session; it sets the vehicle's
            SOC like :meth:`set_vehicle_soc`. Without it the session starts from the SOC the
            vehicle has in CityLearn.
        departure_steps: int, optional
            Time steps until departure; the vehicle leaves at the end of the time step where the
            countdown is 1. Values beyond the episode length are stored as the episode length,
            the upper bound of the observation space. Unknown (``-1``) when omitted at session
            start; kept when omitted on a running session.
        required_soc: float, optional
            SOC the user requires at departure. Unknown when omitted at session start; kept when
            omitted on a running session.
        session_id: str, optional
            Session identity. A different ID for the vehicle already connected here starts a new
            session. Generated when omitted at session start.
        connected_seconds: float, optional
            Seconds of this time step during which the vehicle is plugged in, in
            [0, ``seconds_per_time_step``]. The energy of this step is limited to that time at the
            commanded power. Applies to the current time step only.
        discharge_soc_floor: float, optional
            Discharging in this session never takes the battery below this SOC, e.g. the energy
            the vehicle needs for its next trip. Kept for the rest of the session.
        charge_soc_ceiling: float, optional
            Charging in this session never takes the battery above this SOC, e.g. a target SOC
            cap when an external controller commands full power. Discharging is unaffected. Kept
            for the rest of the session.
        connected_since_seconds: float, optional
            Session age at the start of this time step, only when the call starts a session. A
            positive value means the vehicle plugged in that many seconds before the step started,
            e.g. during the previous interval; that time counts towards the charger's
            ``start_delay_seconds``. A negative value means it plugs in that many seconds after the
            step starts; no energy flows before. Default 0: plugged in at the start of the step.
        departure_seconds: float, optional
            Exact expected departure, in seconds (> 0) from the start of this time step. It counts down
            by the step length at every step and sets ``departure_steps`` to
            ``ceil(departure_seconds / seconds_per_time_step)``, the whole-step countdown that the
            observations show; given together, the two must agree. The exact time is not observed:
            it places the charger's ``stop_delay_seconds`` and, in the step that contains it, ends
            the connection. Giving ``departure_steps`` alone later replaces it.
        """

        self._service.connect(
            charger_id, ev_id, soc=soc, departure_steps=departure_steps, required_soc=required_soc,
            session_id=session_id, connected_seconds=connected_seconds,
            discharge_soc_floor=discharge_soc_floor, charge_soc_ceiling=charge_soc_ceiling,
            connected_since_seconds=connected_since_seconds,
            departure_seconds=departure_seconds,
        )

    def incoming(
        self,
        charger_id: str,
        ev_id: str,
        *,
        arrival_steps: Optional[int] = None,
        soc_on_arrival: Optional[float] = None,
    ) -> None:
        """Announce that ``ev_id`` is on its way to the external charger ``charger_id``.

        ``arrival_steps`` (time steps until arrival) and ``soc_on_arrival`` are estimates that the
        observations show; the SOC the session starts with is set by :meth:`connect` or
        :meth:`set_vehicle_soc`.

        A schedule row holds one state per time step. If ``ev_id`` itself is connected to this
        charger, the call means it has left at this time step and will return: its session ends as
        with :meth:`away`. A charger connected to another vehicle must be freed with :meth:`away`
        first.
        """

        self._service.incoming(charger_id, ev_id, arrival_steps=arrival_steps, soc_on_arrival=soc_on_arrival)

    def away(self, charger_id: str) -> None:
        """Leave the external charger ``charger_id`` free (no vehicle connected or incoming)."""

        self._service.away(charger_id)

    def set_vehicle_soc(self, ev_id: str, soc: float) -> None:
        """Set the current SOC of a vehicle that is not in a running charging session.

        Use it for the energy a vehicle consumed or received away from CityLearn's chargers,
        e.g. while driving. An SOC set here is part of the observation of this time step.
        """

        self._service.set_vehicle_soc(ev_id, soc)

    # ------------------------------------------------------------------- reads

    def vehicle_soc(self, ev_id: str) -> float:
        """Current SOC of ``ev_id`` as CityLearn holds it.

        In :meth:`MobilityProvider.update` this is the SOC the vehicle starts the new interval
        with: after the charging of the finished interval and the battery's standby loss.
        """

        return self._service.vehicle_soc(ev_id)

    def charger_energy_kwh(self, charger_id: str) -> float:
        """Signed AC energy of ``charger_id`` in the last finished interval, in kWh.

        Positive values are drawn from the building (charging), negative values are fed to it
        (vehicle-to-building). Any charger can be read, not only external ones. 0 before the
        first interval.
        """

        return self._service.charger_energy_kwh(charger_id)

    def charger_power_kw(self, charger_id: str) -> float:
        """Average AC power of ``charger_id`` over the last finished interval, in kW."""

        return self._service.charger_power_kw(charger_id)

    def transfer_efficiency(
        self,
        charger_id: str,
        ev_id: str,
        power_kw: Optional[float] = None,
        *,
        charging: bool = True,
    ) -> float:
        """Combined one-way AC-to-stored (or stored-to-AC) efficiency of ``charger_id`` and ``ev_id``.

        Evaluates the charger's charge/discharge efficiency curve at ``power_kw`` (AC power at the
        charger inlet; defaults to the charger's maximum power for that direction) together with the
        vehicle battery's one-way efficiency at the corresponding DC terminal power.
        """

        return self._service.transfer_efficiency(charger_id, ev_id, power_kw, charging=charging)

    @property
    def external_charger_ids(self) -> List[str]:
        """IDs of the chargers whose schedule the provider writes."""

        return self._service.external_charger_ids

    @property
    def external_vehicle_ids(self) -> List[str]:
        """IDs of the vehicles declared ``"external": true``."""

        return self._service.external_vehicle_ids

    @property
    def vehicle_ids(self) -> List[str]:
        """IDs of all vehicles of the environment."""

        return self._service.vehicle_ids
