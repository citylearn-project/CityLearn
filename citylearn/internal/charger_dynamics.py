"""Charging-session dynamics of an EV charger: start-up, set-point delay, ramp limits and stop.

The AC power of a charger during a step is a piecewise-linear function of time. Its energy is the
exact integral of that function (sums of trapezoids over its linear pieces), with no sub-stepping.

Model, with times in seconds from the start of a control step of length ``step``:

* A session starts when a vehicle connects. For ``start_delay_seconds`` after the connection the
  charger delivers no energy (coupling and the communication start-up before power delivery). The
  session's age at the start of its first step is 0 by default; a positive age means the vehicle
  plugged in before the step started, a negative age that it plugs in during the step.
* The controller's command of a step is issued at the start of the step and takes effect
  ``setpoint_delay_seconds`` later; until then the previous set-point stays in force. A command
  delayed beyond the step takes effect in a later step.
* The power follows the set-point at most at ``ramp_up_kw_per_second`` while its magnitude rises and
  at most at ``ramp_down_kw_per_second`` while its magnitude falls. A reversal between charging and
  discharging passes through zero: down at the ramp-down rate, then up at the ramp-up rate.
* When the departure is known (the departure countdown, or a connection that ends within the
  step), the charger stops ``stop_delay_seconds`` before it: the set-point becomes zero and the power
  ramps down at the ramp-down rate. The power is zero once the vehicle is disconnected.

Omitted parameters mean no delay and an unlimited ramp: the power then equals the commanded power
for the whole connected time, as without session dynamics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class SessionDynamics:
    start_delay_seconds: float = 0.0
    setpoint_delay_seconds: float = 0.0
    ramp_up_kw_per_second: float = math.inf
    ramp_down_kw_per_second: float = math.inf
    stop_delay_seconds: float = 0.0

    @classmethod
    def from_attributes(cls, start_delay_seconds=None, setpoint_delay_seconds=None, ramp_up_kw_per_second=None,
                        ramp_down_kw_per_second=None, stop_delay_seconds=None) -> 'SessionDynamics':
        def delay(value, name):
            if value is None:
                return 0.0
            value = float(value)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f'{name} must be a finite number >= 0, got {value!r}.')
            return value

        def ramp(value, name):
            if value is None:
                return math.inf
            value = float(value)
            if not value > 0.0:
                raise ValueError(f'{name} must be > 0 (omit it for an unlimited ramp), got {value!r}.')
            return value

        return cls(
            delay(start_delay_seconds, 'start_delay_seconds'),
            delay(setpoint_delay_seconds, 'setpoint_delay_seconds'),
            ramp(ramp_up_kw_per_second, 'ramp_up_kw_per_second'),
            ramp(ramp_down_kw_per_second, 'ramp_down_kw_per_second'),
            delay(stop_delay_seconds, 'stop_delay_seconds'),
        )

    @property
    def enabled(self) -> bool:
        return (
            self.start_delay_seconds > 0.0 or self.setpoint_delay_seconds > 0.0 or self.stop_delay_seconds > 0.0
            or math.isfinite(self.ramp_up_kw_per_second) or math.isfinite(self.ramp_down_kw_per_second)
        )


@dataclass
class SessionState:
    """Session state at the start of a step: age, AC power, set-point in force and pending set-points.

    ``pending`` holds ``(seconds from the start of the step, set-point in kW)`` of commands that
    take effect later.
    """

    age_seconds: float = 0.0
    power_kw: float = 0.0
    setpoint_kw: float = 0.0
    pending: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class Piece:
    seconds: float
    start_kw: float
    end_kw: float

    @property
    def energy_kwh(self) -> float:
        return 0.5 * (self.start_kw + self.end_kw) * self.seconds / 3600.0


@dataclass
class StepProfile:
    pieces: List[Piece]
    state: SessionState

    def parts(self) -> List[Tuple[int, float, float]]:
        """``(sign, energy_kwh, seconds)`` for charging (+1) and discharging (-1), in time order."""

        totals = {}
        order = []
        for piece in self.pieces:
            if piece.start_kw == 0.0 and piece.end_kw == 0.0:
                continue
            sign = 1 if piece.start_kw + piece.end_kw > 0.0 else -1
            if sign not in totals:
                totals[sign] = [0.0, 0.0]
                order.append(sign)
            totals[sign][0] += piece.energy_kwh
            totals[sign][1] += piece.seconds
        return [(sign, totals[sign][0], totals[sign][1]) for sign in order]

    @property
    def energy_kwh(self) -> float:
        return sum(piece.energy_kwh for piece in self.pieces)


def known_departure_seconds(countdown, connected_seconds, step_seconds, departure_seconds=None) -> Optional[float]:
    """Seconds from the start of a step to a known departure, else ``None``.

    An exact ``departure_seconds`` (written by a mobility provider) is used when given. Otherwise a
    departure countdown of 1 means the vehicle leaves at the end of this step (the convention of
    charger schedules). A connection that ends within the step ends at ``connected_seconds``.
    """

    step_seconds = float(step_seconds)
    departure = None
    if departure_seconds is not None and math.isfinite(float(departure_seconds)):
        departure = float(departure_seconds)
    elif countdown is not None and math.isfinite(float(countdown)) and float(countdown) >= 1.0:
        departure = float(countdown) * step_seconds

    if connected_seconds is not None and connected_seconds < step_seconds:
        departure = connected_seconds if departure is None else min(departure, connected_seconds)

    return departure


def connected_until(connected_seconds, departure_seconds, step_seconds) -> Optional[float]:
    """Connected time from the start of the step: a departure within the step ends the connection."""

    if departure_seconds is None or not math.isfinite(float(departure_seconds)) or departure_seconds >= step_seconds:
        return connected_seconds

    departure_seconds = max(float(departure_seconds), 0.0)
    return departure_seconds if connected_seconds is None else min(float(connected_seconds), departure_seconds)


def departure_countdown(departure_seconds, step_seconds) -> int:
    """Whole-step departure countdown of a departure ``departure_seconds`` after the start of the step.

    The vehicle leaves at the end of the step where the countdown is 1, so a departure in
    (0, step] gives 1, in (step, 2 step] gives 2, and so on.
    """

    return int(math.ceil(float(departure_seconds) / float(step_seconds) - 1.0e-9))


def _sign(value: float) -> int:
    return (value > 0.0) - (value < 0.0)


def _ramp(power: float, target: float, seconds: float, up: float, down: float, pieces: List[Piece]) -> float:
    """Move ``power`` towards ``target`` for ``seconds`` within the ramp limits; append linear pieces."""

    remaining = seconds
    while remaining > 0.0:
        if power == target:
            pieces.append(Piece(remaining, power, power))
            return power

        if power == 0.0 or (_sign(power) == _sign(target) and abs(target) > abs(power)):
            rate, goal = up, target
        else:
            rate, goal = down, (target if _sign(target) == _sign(power) else 0.0)

        if math.isinf(rate):
            power = goal
            continue

        needed = abs(goal - power) / rate
        if needed <= remaining:
            pieces.append(Piece(needed, power, goal))
            remaining -= needed
            power = goal
        else:
            end = power + math.copysign(rate * remaining, goal - power)
            pieces.append(Piece(remaining, power, end))
            return end

    return power


def integrate_step(
    dynamics: SessionDynamics,
    state: SessionState,
    *,
    command_kw: float,
    step_seconds: float,
    connected_seconds: Optional[float] = None,
    departure_seconds: Optional[float] = None,
) -> StepProfile:
    """Power profile of one step and the session state at the start of the next step.

    ``connected_seconds`` is the connected time from the start of the step (default: the whole
    step); ``departure_seconds`` the known departure time from the start of the step, if any.
    """

    step = float(step_seconds)
    end = step if connected_seconds is None else min(max(float(connected_seconds), 0.0), step)
    enabled_from = max(dynamics.start_delay_seconds - state.age_seconds, 0.0)
    stop_at = math.inf if departure_seconds is None else float(departure_seconds) - dynamics.stop_delay_seconds

    pending = sorted(state.pending + [(dynamics.setpoint_delay_seconds, float(command_kw))], key=lambda item: item[0])
    setpoint = state.setpoint_kw
    times = sorted({0.0, end, *(t for t in (enabled_from, stop_at) if 0.0 < t < end),
                    *(t for t, _ in pending if 0.0 < t < end)})

    pieces: List[Piece] = []
    power = state.power_kw
    for start, stop in zip(times[:-1], times[1:]):
        while pending and pending[0][0] <= start:
            setpoint = pending.pop(0)[1]
        target = setpoint if enabled_from <= start < stop_at else 0.0
        power = _ramp(power, target, stop - start, dynamics.ramp_up_kw_per_second,
                      dynamics.ramp_down_kw_per_second, pieces)

    while pending and pending[0][0] < step:
        setpoint = pending.pop(0)[1]

    next_state = SessionState(
        age_seconds=state.age_seconds + step,
        # A vehicle that left during the step takes the power to zero.
        power_kw=power if end >= step else 0.0,
        setpoint_kw=setpoint,
        pending=[(t - step, value) for t, value in pending],
    )
    return StepProfile(pieces, next_state)
