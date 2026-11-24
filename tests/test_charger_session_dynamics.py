"""Charger session dynamics: closed-form step energy against fine numerical integration."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.charger_dynamics import SessionDynamics, SessionState, integrate_step
from citylearn.internal.comparison import equipment

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "tests" / "data" / "minute_ev_demo"
EV = "Electric_Vehicle_1"

# Measured values cited in docs/charger_session_dynamics.md: robotic plug-in 24 s and DC start-up
# 27 s (start delay), local set-point activation 4 s, ramps 3.35 / 3.31 kW/s, robotic plug-out 22 s.
MEASURED = dict(start_delay_seconds=24.0 + 27.0, setpoint_delay_seconds=4.0, ramp_up_kw_per_second=3.35,
                ramp_down_kw_per_second=3.31, stop_delay_seconds=22.0)
DYNAMICS = SessionDynamics.from_attributes(**MEASURED)


# ------------------------------------------------------------------ numerical reference


def _toward(power, target, seconds, up, down):
    """Ramp-limited move over a short interval, independent of the event-based implementation."""

    while seconds > 0.0 and power != target:
        rising = power == 0.0 or (np.sign(power) == np.sign(target) and abs(target) > abs(power))
        rate = up if rising else down
        goal = target if rising or np.sign(target) == np.sign(power) else 0.0
        if math.isinf(rate):
            power = goal
            continue
        move = min(abs(goal - power), rate * seconds)
        seconds -= move / rate
        power += math.copysign(move, goal - power)
    return power


def reference(dynamics, state, schedule, duration, *, connected=None, departure=None, dt=0.001, step=None):
    """(charge, discharge) kWh by time stepping at ``dt`` with the trapezoidal rule.

    ``schedule`` lists (seconds from the start, set-point kW) in time order, including the set-point
    delay; ``duration`` may cover several control steps. With ``step``, the signed energy of each
    control step is returned instead.
    """

    end = duration if connected is None else connected
    start_at = dynamics.start_delay_seconds - state.age_seconds
    stop_at = math.inf if departure is None else departure - dynamics.stop_delay_seconds
    schedule = list(state.pending) + list(schedule)
    power, setpoint = state.power_kw, state.setpoint_kw
    charge = discharge = 0.0
    per_step = [0.0] * (1 if step is None else int(round(duration / step)))
    for i in range(int(round(duration / dt))):
        tau = i * dt
        while schedule and schedule[0][0] <= tau + 1e-9:
            setpoint = schedule.pop(0)[1]
        if tau >= end - 1e-9:
            power = 0.0
            continue
        target = setpoint if start_at - 1e-9 <= tau < stop_at - 1e-9 else 0.0
        following = _toward(power, target, dt, dynamics.ramp_up_kw_per_second, dynamics.ramp_down_kw_per_second)
        if power * following < 0.0:
            # A reversal inside dt: integrate both sides of the zero crossing exactly.
            to_zero = abs(power) / dynamics.ramp_down_kw_per_second
            parts = (0.5 * power * to_zero, 0.5 * following * (dt - to_zero))
        else:
            parts = (0.5 * (power + following) * dt,)
        for part in parts:
            if part > 0.0:
                charge += part / 3600.0
            else:
                discharge += part / 3600.0
            if step is not None:
                per_step[int((tau + 0.5 * dt) // step)] += part / 3600.0
        power = following
    return (charge, discharge) if step is None else per_step


def closed_form(dynamics, state, command, step, *, connected=None, departure=None):
    profile = integrate_step(dynamics, state, command_kw=command, step_seconds=step,
                             connected_seconds=connected, departure_seconds=departure)
    parts = profile.parts()
    return (sum(e for sign, e, _ in parts if sign > 0), sum(e for sign, e, _ in parts if sign < 0), profile)


def _check(closed, expected):
    assert closed[0] == pytest.approx(expected[0], rel=2e-6, abs=1e-9)
    assert closed[1] == pytest.approx(expected[1], rel=2e-6, abs=1e-9)


STEPS = [(60.0, 0.001), (900.0, 0.01)]


# ----------------------------------------------------------------------- unit tests


@pytest.mark.parametrize("step, dt", STEPS)
def test_new_session_waits_for_start_up_then_ramps(step, dt):
    closed = closed_form(DYNAMICS, SessionState(), 11.0, step)
    _check(closed, reference(DYNAMICS, SessionState(), [(4.0, 11.0)], step, dt=dt))
    ramp = 11.0 / 3.35
    # Exact by hand: nothing for 51 s, a linear ramp to 11 kW, then 11 kW to the end of the step.
    assert closed[0] == pytest.approx((0.5 * 11.0 * ramp + 11.0 * (step - 51.0 - ramp)) / 3600.0, rel=1e-12)
    assert closed[2].state.power_kw == pytest.approx(11.0)


@pytest.mark.parametrize("step, dt", STEPS)
@pytest.mark.parametrize("plugged_in_at", [0.25, 0.75])
def test_session_starting_mid_step(step, dt, plugged_in_at):
    # The vehicle plugs in during the step: the start-up runs from the plug-in time.
    state = SessionState(age_seconds=-plugged_in_at * step)
    closed = closed_form(DYNAMICS, state, 7.4, step)
    _check(closed, reference(DYNAMICS, state, [(4.0, 7.4)], step, dt=dt))
    idle = 0.0
    for piece in closed[2].pieces:
        if piece.start_kw != 0.0 or piece.end_kw != 0.0:
            break
        idle += piece.seconds
    assert idle == pytest.approx(min(plugged_in_at * step + 51.0, step))
    # Plugged in during the previous interval: the elapsed time counts towards the start-up.
    state = SessionState(age_seconds=30.0)
    _check(closed_form(DYNAMICS, state, 7.4, step), reference(DYNAMICS, state, [(4.0, 7.4)], step, dt=dt))


@pytest.mark.parametrize("step, dt", STEPS)
@pytest.mark.parametrize("command", [3.0, 11.0, 0.0])
def test_set_point_change_holds_the_previous_set_point_then_ramps(step, dt, command):
    state = SessionState(age_seconds=600.0, power_kw=7.0, setpoint_kw=7.0)
    closed = closed_form(DYNAMICS, state, command, step)
    _check(closed, reference(DYNAMICS, state, [(4.0, command)], step, dt=dt))
    assert closed[2].pieces[0].seconds == pytest.approx(4.0)
    assert closed[2].pieces[0].start_kw == closed[2].pieces[0].end_kw == 7.0
    assert closed[2].state.power_kw == pytest.approx(command)


@pytest.mark.parametrize("step, dt", STEPS)
def test_ramp_limited_reversal_from_charge_to_discharge(step, dt):
    remote = SessionDynamics.from_attributes(**{**MEASURED, "setpoint_delay_seconds": 7.0})
    state = SessionState(age_seconds=600.0, power_kw=11.0, setpoint_kw=11.0)
    charge, discharge, profile = closed_form(remote, state, -10.0, step)
    _check((charge, discharge), reference(remote, state, [(7.0, -10.0)], step, dt=dt))
    assert [sign for sign, _, _ in profile.parts()] == [1, -1]
    # 7 s at 11 kW, 11 / 3.31 s down to zero, 10 / 3.35 s up to -10 kW, then -10 kW.
    down, up = 11.0 / 3.31, 10.0 / 3.35
    assert charge == pytest.approx((11.0 * 7.0 + 0.5 * 11.0 * down) / 3600.0, rel=1e-12)
    assert discharge == pytest.approx(-(0.5 * 10.0 * up + 10.0 * (step - 7.0 - down - up)) / 3600.0, rel=1e-12)


@pytest.mark.parametrize("step, dt", STEPS)
def test_charger_stops_before_a_known_departure(step, dt):
    state = SessionState(age_seconds=600.0, power_kw=11.0, setpoint_kw=11.0)
    # Departure at the end of the step (countdown 1).
    closed = closed_form(DYNAMICS, state, 11.0, step, departure=step)
    _check(closed, reference(DYNAMICS, state, [(4.0, 11.0)], step, departure=step, dt=dt))
    down = 11.0 / 3.31
    assert closed[0] == pytest.approx((11.0 * (step - 22.0) + 0.5 * 11.0 * down) / 3600.0, rel=1e-12)
    # Departure within the step: unplugged after 45 s, so the stop is commanded at 23 s.
    closed = closed_form(DYNAMICS, state, 11.0, step, connected=45.0, departure=45.0)
    _check(closed, reference(DYNAMICS, state, [(4.0, 11.0)], step, connected=45.0, departure=45.0, dt=dt))
    assert closed[2].state.power_kw == 0.0


def test_set_point_delay_longer_than_a_step_takes_effect_in_a_later_step():
    slow = SessionDynamics.from_attributes(setpoint_delay_seconds=90.0, ramp_up_kw_per_second=1.0)
    state = SessionState(age_seconds=600.0)
    first = integrate_step(slow, state, command_kw=11.0, step_seconds=60.0)
    assert first.energy_kwh == 0.0 and first.state.pending == [(30.0, 11.0)]
    second = integrate_step(slow, first.state, command_kw=5.0, step_seconds=60.0)
    expected = reference(slow, state, [(90.0, 11.0), (150.0, 5.0)], 120.0, dt=0.001)
    assert first.energy_kwh + second.energy_kwh == pytest.approx(expected[0], rel=2e-6)
    # The second command, issued at 60 s, takes effect at 150 s: 30 s into the third step.
    assert second.state.pending == [(30.0, 5.0)]


def test_defaults_deliver_the_commanded_power_for_the_connected_time():
    plain = SessionDynamics.from_attributes()
    assert not plain.enabled
    assert integrate_step(plain, SessionState(), command_kw=7.2, step_seconds=900.0).energy_kwh == pytest.approx(1.8)
    profile = integrate_step(plain, SessionState(), command_kw=-7.2, step_seconds=900.0, connected_seconds=450.0)
    assert profile.parts() == [(-1, pytest.approx(-0.9), pytest.approx(450.0))]


@pytest.mark.parametrize("name, value, message", [
    ("start_delay_seconds", -1.0, "start_delay_seconds must be a finite number >= 0"),
    ("stop_delay_seconds", float("inf"), "stop_delay_seconds must be a finite number >= 0"),
    ("ramp_up_kw_per_second", 0.0, "ramp_up_kw_per_second must be > 0"),
    ("ramp_down_kw_per_second", -3.0, "ramp_down_kw_per_second must be > 0"),
])
def test_invalid_parameters(name, value, message):
    with pytest.raises(ValueError, match=message):
        SessionDynamics.from_attributes(**{name: value})


# --------------------------------------------------------------------- environment


def _schema(dynamics=None, external=False):
    schema = json.loads((DEMO / "schema.json").read_text())
    schema["root_directory"] = str(DEMO)
    charger = schema["buildings"]["Building_1"]["chargers"]["charger_1_1"]
    if dynamics:
        charger["attributes"].update(dynamics)
    if external:
        charger["charger_simulation"] = {"source": "external"}
        schema["electric_vehicles_def"][EV]["external"] = True
    return schema


def _actions(env, ev):
    return [np.array([ev if name.startswith("electric_vehicle_storage") else 0.0 for name in names], dtype="float32")
            for names in env.action_names]


def _charger(env):
    return env.buildings[0].electric_vehicle_chargers[0]


def test_schedule_file_session_energy_follows_the_profile():
    """minute_ev_demo: EV connected for steps 0-3 (countdown 4..1) at 7.2 kW, 900 s steps."""

    env = CityLearnEnv(_schema(MEASURED), central_agent=True, random_seed=0)
    env.reset()
    for _ in range(4):
        env.step(_actions(env, 1.0))
    charger = _charger(env)
    ramp_up, ramp_down = 7.2 / 3.35, 7.2 / 3.31
    expected = [
        (0.5 * 7.2 * ramp_up + 7.2 * (900.0 - 51.0 - ramp_up)) / 3600.0,  # start-up, then ramp
        7.2 * 900.0 / 3600.0,
        7.2 * 900.0 / 3600.0,
        (7.2 * (900.0 - 22.0) + 0.5 * 7.2 * ramp_down) / 3600.0,  # stop 22 s before departure
    ]
    # The commanded AC energy is the profile integral; the battery's power curve may cap it further.
    np.testing.assert_allclose(charger.past_charging_action_values_kwh[:4], expected, rtol=1e-6)
    np.testing.assert_allclose(charger.electricity_consumption[:2], expected[:2], rtol=1e-6)
    assert np.all(charger.electricity_consumption[2:4] <= np.array(expected[2:]) + 1e-6)


def test_dynamics_do_not_change_observations_or_spaces():
    plain = CityLearnEnv(_schema(), central_agent=True, random_seed=0)
    dynamic = CityLearnEnv(_schema(MEASURED), central_agent=True, random_seed=0)
    assert plain.observation_names == dynamic.observation_names
    assert plain.action_names == dynamic.action_names
    np.testing.assert_array_equal(plain.observation_space[0].high, dynamic.observation_space[0].high)
    assert "session_dynamics" not in equipment(plain)["Building_1/charger charger_1_1"]
    assert equipment(dynamic)["Building_1/charger charger_1_1"]["session_dynamics"]["start_delay_seconds"] == 51.0


class _Connect:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def reset(self, env):
        env.mobility.connect("charger_1_1", EV, soc=0.3, **self.kwargs)

    def update(self, env, time_step):
        pass


def test_provider_session_age_counts_towards_the_start_up():
    # Plugged in 30 s before the step: 21 s of start-up remain.
    env = CityLearnEnv(_schema(dict(start_delay_seconds=51.0), external=True), central_agent=True, random_seed=0,
                       mobility_provider=_Connect(connected_since_seconds=30.0))
    env.reset()
    env.step(_actions(env, 1.0))
    assert _charger(env).electricity_consumption[0] == pytest.approx(7.2 * (900.0 - 21.0) / 3600.0, rel=1e-6)

    # Plugs in 300 s into the step: no energy before, even without session dynamics.
    env = CityLearnEnv(_schema(external=True), central_agent=True, random_seed=0,
                       mobility_provider=_Connect(connected_since_seconds=-300.0))
    env.reset()
    env.step(_actions(env, 1.0))
    env.step(_actions(env, 1.0))
    consumption = _charger(env).electricity_consumption
    assert consumption[0] == pytest.approx(7.2 * 600.0 / 3600.0, rel=1e-6)
    assert consumption[1] == pytest.approx(7.2 * 900.0 / 3600.0, rel=1e-6)


def test_provider_session_age_validation():
    env = CityLearnEnv(_schema(external=True), central_agent=True, random_seed=0)
    env.mobility_provider = _Connect(connected_since_seconds=-500.0, connected_seconds=400.0)
    with pytest.raises(ValueError, match="plugs the vehicle in after it leaves"):
        env.reset()

    class Late(_Connect):
        def update(self, env, time_step):
            env.mobility.connect("charger_1_1", EV, connected_since_seconds=10.0)

    env.mobility_provider = Late()
    env.reset()
    with pytest.raises(ValueError, match="connected_since_seconds is accepted only when a session starts"):
        env.step(_actions(env, 1.0))


def test_departure_feasibility_replays_the_session_profile():
    """A one-step session reachable at full power is not reachable after a 300 s start-up."""

    def run(dynamics):
        battery = 20.0
        target = 0.3 + 0.95 * 7.2 * 0.25 * 0.9 / battery  # below the full-step gain of about 0.0855

        class OneStep:
            def reset(self, env):
                env.mobility.connect("charger_1_1", EV, soc=0.3, departure_steps=1, required_soc=target)

            def update(self, env, time_step):
                if time_step == 1:
                    env.mobility.away("charger_1_1")

        env = CityLearnEnv(_schema(dynamics, external=True), central_agent=True, random_seed=0,
                           mobility_provider=OneStep())
        env.reset()
        while not env.terminated:
            env.step(_actions(env, 1.0))
        kpis = env.evaluate_v2(include_business_as_usual=False)
        district = kpis[kpis["level"] == "district"].set_index("cost_function")["value"]
        return district

    plain, delayed = run(None), run(dict(start_delay_seconds=300.0))
    assert plain["district_ev_departure_audit_departures_count"] == delayed["district_ev_departure_audit_departures_count"] == 1
    assert plain["district_ev_departure_audit_target_feasible_count"] == 1
    assert plain["district_ev_departure_audit_target_service_met_count"] == 1
    # The audit charges only after the start-up, like the runtime; the target is then infeasible.
    assert delayed["district_ev_departure_audit_target_infeasible_count"] == 1
    assert delayed["district_ev_departure_audit_target_service_met_count"] == 0


# ---------------------------------------------------------------- exact departure


class _Departure:
    """Connects at step 0, optionally announces an exact departure at ``update_at``, leaves after it."""

    def __init__(self, step, *, at_start=None, update_at=None, update_seconds=None, countdown=8):
        self.step, self.at_start, self.update_at, self.update_seconds = step, at_start, update_at, update_seconds
        self.countdown = countdown
        if update_at is not None:
            self.departure_step = math.ceil((update_at * step + update_seconds) / step - 1e-9) - 1
        elif at_start is not None:
            self.departure_step = math.ceil(at_start / step - 1e-9) - 1
        else:
            self.departure_step = countdown - 1
        self.observed = {}

    def reset(self, env):
        if self.at_start is None:
            env.mobility.connect("charger_1_1", EV, soc=0.3, departure_steps=self.countdown)
        else:
            env.mobility.connect("charger_1_1", EV, soc=0.3, departure_seconds=self.at_start)

    def update(self, env, time_step):
        if time_step == self.update_at:
            env.mobility.connect("charger_1_1", EV, departure_seconds=self.update_seconds)
        if time_step == self.departure_step + 1:
            env.mobility.away("charger_1_1")


@pytest.mark.parametrize("step, scenario", [
    (60.0, dict(at_start=130.0)),                   # leaves 10 s into step 2; the stop (108 s) is in step 1
    (15.0, dict(at_start=95.0)),                    # leaves 5 s into step 6; the stop (73 s) is in step 4
    (60.0, dict(update_at=2, update_seconds=70.0)),  # announced during the session; stop in step 2, departure in step 3
    (15.0, dict(update_at=4, update_seconds=50.0)),  # stop 28 s after step 4 starts (step 5), departure in step 7
])
def test_exact_departure_places_the_stop_in_an_earlier_step(step, scenario):
    provider = _Departure(step, **scenario)
    env = CityLearnEnv(_schema(MEASURED, external=True), central_agent=True, random_seed=0,
                       seconds_per_time_step=step, time_step_ratio_mode="compress",
                       mobility_provider=provider)
    observations, _ = env.reset()
    trace = [observations]
    while not env.terminated:
        observations, *_ = env.step(_actions(env, 1.0))
        trace.append(observations)

    departure = (provider.at_start if provider.update_at is None
                 else provider.update_at * step + provider.update_seconds)
    stop = departure - MEASURED["stop_delay_seconds"]
    steps = provider.departure_step + 1
    assert int(stop // step) < provider.departure_step
    expected = reference(DYNAMICS, SessionState(), [(4.0, 7.2)], steps * step,
                         connected=departure, departure=departure, dt=0.001, step=step)
    commanded = _charger(env).past_charging_action_values_kwh[:steps]
    np.testing.assert_allclose(commanded, expected, rtol=2e-6, atol=1e-9)

    # The controller still observes only the whole-step countdown.
    key = "connected_electric_vehicle_at_charger_charger_1_1_departure_time"
    names = env.observation_names[0]
    known_from = 0 if provider.update_at is None else provider.update_at
    for t in range(known_from, steps):
        countdown = trace[t][0][names.index(key)]
        assert countdown == math.ceil((departure - t * step) / step - 1e-9)


@pytest.mark.parametrize("step", [60.0, 15.0])
def test_whole_step_departure_keeps_its_previous_behaviour(step):
    """Without departure_seconds the stop follows the countdown, as before: later than the exact stop."""

    exact = _Departure(step, at_start=130.0 if step == 60.0 else 95.0)
    countdown = _Departure(step, countdown=exact.departure_step + 1)
    energies = []
    for provider in (exact, countdown):
        env = CityLearnEnv(_schema(MEASURED, external=True), central_agent=True, random_seed=0,
                           seconds_per_time_step=step, time_step_ratio_mode="compress",
                           mobility_provider=provider)
        env.reset()
        while not env.terminated:
            env.step(_actions(env, 1.0))
        energies.append(_charger(env).past_charging_action_values_kwh[:exact.departure_step + 1].copy())
        assert np.all(np.isnan(_charger(env).charger_simulation.electric_vehicle_departure_seconds)) == (
            provider is countdown)

    end = (exact.departure_step + 1) * step
    expected = reference(DYNAMICS, SessionState(), [(4.0, 7.2)], end, departure=end, dt=0.001, step=step)
    np.testing.assert_allclose(energies[1], expected, rtol=2e-6, atol=1e-9)
    assert energies[1].sum() > energies[0].sum()


def test_exact_departure_validation_and_countdown():
    class Plan(_Connect):
        def __init__(self, plan):
            self.plan = plan

        def reset(self, env):
            self.plan[0](env)

        def update(self, env, time_step):
            if time_step in self.plan:
                self.plan[time_step](env)

    def run(plan):
        env = CityLearnEnv(_schema(external=True), central_agent=True, random_seed=0, mobility_provider=Plan(plan))
        env.reset()
        for _ in range(3):
            env.step(_actions(env, 1.0))
        return _charger(env).charger_simulation

    simulation = run({0: lambda env: env.mobility.connect("charger_1_1", EV, departure_seconds=2000.0,
                                                          departure_steps=3)})
    np.testing.assert_allclose(simulation.electric_vehicle_departure_seconds[:4], [2000.0, 1100.0, 200.0, np.nan])
    assert list(simulation.electric_vehicle_departure_time[:4]) == [3, 2, 1, 0]

    # A countdown given alone replaces the exact departure.
    simulation = run({0: lambda env: env.mobility.connect("charger_1_1", EV, departure_seconds=2000.0),
                      1: lambda env: env.mobility.connect("charger_1_1", EV, departure_steps=5)})
    assert np.isnan(simulation.electric_vehicle_departure_seconds[1])
    assert list(simulation.electric_vehicle_departure_time[:3]) == [3, 5, 4]

    for kwargs, message in [
        (dict(departure_seconds=2000.0, departure_steps=2), "disagrees with departure_seconds"),
        (dict(departure_seconds=0.0), "departure_seconds must be > 0"),
        (dict(departure_seconds=float("nan")), "departure_seconds must be finite"),
        (dict(departure_seconds=300.0, connected_since_seconds=-400.0), "plugs the vehicle in after it leaves"),
    ]:
        with pytest.raises(ValueError, match=message):
            run({0: lambda env, kwargs=kwargs: env.mobility.connect("charger_1_1", EV, **kwargs)})


def test_exact_departure_within_the_step_ends_the_connection_without_dynamics():
    env = CityLearnEnv(_schema(external=True), central_agent=True, random_seed=0,
                       mobility_provider=_Connect(departure_seconds=300.0))
    env.reset()
    env.step(_actions(env, 1.0))
    assert _charger(env).electricity_consumption[0] == pytest.approx(7.2 * 300.0 / 3600.0, rel=1e-6)


def test_polarity_reversal_in_environment_conserves_battery_and_charger_energy():
    """A charge-to-discharge reversal within one step accumulates both parts on battery and charger."""

    schema = _schema({**MEASURED, "setpoint_delay_seconds": 60.0}, external=True)
    schema["electric_vehicles_def"][EV]["battery"]["attributes"]["loss_coefficient"] = 0.0
    env = CityLearnEnv(
        schema,
        central_agent=True,
        random_seed=0,
        physics_invariant_checks=True,
        mobility_provider=_Connect(),
    )
    env.reset()
    env.step(_actions(env, 1.0))
    battery = env.electric_vehicles[0].battery
    charger = _charger(env)
    cap_len_after_step0 = len(battery.capacity_history)

    # Step 1 reverses from +7.2 kW (held during the 60 s set-point delay) to -7.2 kW.
    env.step(_actions(env, -1.0))
    assert charger.gross_energy_charge[1] > 0.0
    assert charger.gross_energy_discharge[1] > 0.0
    assert charger.electricity_consumption[1] == pytest.approx(
        charger.gross_energy_charge[1] - charger.gross_energy_discharge[1], rel=1e-6
    )
    assert battery.gross_energy_charge[1] > 0.0
    assert battery.gross_energy_discharge[1] > 0.0
    assert battery.energy_balance[1] == pytest.approx(
        battery.gross_energy_charge[1] - battery.gross_energy_discharge[1], rel=1e-6
    )
    ratio = battery.time_step_ratio or 1.0
    assert battery.electricity_consumption[1] == pytest.approx(battery.energy_balance[1] / ratio, rel=1e-6)
    assert len(battery.capacity_history) == cap_len_after_step0 + 1
    assert env._provenance_service.max_bus_residual < 1e-6
