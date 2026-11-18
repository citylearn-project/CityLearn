"""External mobility provider: runtime EV connections written into external charger rows."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.mobility import MobilityProvider

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "tests" / "data" / "minute_ev_demo"
EV = "Electric_Vehicle_1"
EV2 = "Electric_Vehicle_2"
STEP_SECONDS = 900.0


def _schema(*, second_ev_external=None, file_charger_in_building_1=False):
    """Two buildings with one external 7.2 kW charger each and one external EV (8 x 15 min)."""

    schema = json.loads((DEMO / "schema.json").read_text())
    schema["root_directory"] = str(DEMO)
    building_1 = schema["buildings"]["Building_1"]
    charger = building_1["chargers"]["charger_1_1"]
    building_2 = copy.deepcopy(building_1)
    building_2["chargers"] = {"charger_2_1": copy.deepcopy(charger)}
    building_2["chargers"]["charger_2_1"]["charger_simulation"] = {"source": "external"}
    if not file_charger_in_building_1:
        charger["charger_simulation"] = {"source": "external"}
    schema["buildings"]["Building_2"] = building_2
    vehicle = schema["electric_vehicles_def"][EV]
    vehicle["external"] = True
    # The EVs never lose charge on standby here, so every SOC change has a known cause.
    vehicle["battery"]["attributes"]["loss_coefficient"] = 0.0
    if second_ev_external is not None:
        second = copy.deepcopy(vehicle)
        second["external"] = second_ev_external
        schema["electric_vehicles_def"][EV2] = second
    return schema


class Scripted:
    """Runs `plan[t](env)` in reset (t = 0) and update (t >= 1) and records the calls."""

    def __init__(self, plan=None):
        self.plan = plan or {}
        self.calls = []
        self.seen = {}

    def reset(self, env):
        self.calls.append(("reset", int(env.time_step)))
        self._run(env, 0)

    def update(self, env, time_step):
        self.calls.append(("update", int(time_step), int(env.time_step)))
        self._run(env, int(time_step))

    def _run(self, env, t):
        action = self.plan.get(t)
        if action is not None:
            action(env)


def _flat_actions(env, ev=0.0, storage=0.0):
    actions = []
    for names in env.action_names:
        actions.append(np.array([ev if name.startswith("electric_vehicle_storage") else storage for name in names],
                                dtype="float32"))
    return actions


def _entity_actions(env, ev=0.0, storage=0.0):
    tables = env.action_space["tables"]
    return {"tables": {
        "building": np.full(tables["building"].shape, storage, dtype="float32"),
        "charger": np.full(tables["charger"].shape, ev, dtype="float32"),
    }}


def _actions(env, ev=0.0):
    return _entity_actions(env, ev) if env.interface == "entity" else _flat_actions(env, ev)


def _charger(env, name):
    return next(c for b in env.buildings for c in b.electric_vehicle_chargers or [] if c.charger_id == name)


def _vehicle(env, name=EV):
    return next(ev for ev in env.electric_vehicles if ev.name == name)


def _flat_observation(env, observations, name):
    """Value of an observation by name in a flat (central or per-building) observation."""

    for names, values in zip(env.observation_names, observations):
        if name in names:
            return float(values[names.index(name)])
    raise KeyError(name)


def _connected(env, observations, charger_id):
    if env.interface == "entity":
        specs = env.entity_specs["tables"]["charger"]
        row = [i for i, key in enumerate(specs["ids"]) if key.endswith("/" + charger_id)][0]
        state = observations["tables"]["charger"][row, specs["features"].index("connected_state")]
        soc = observations["tables"]["charger"][row, specs["features"].index("connected_ev_soc")]
        return float(state), float(soc)
    return (
        _flat_observation(env, observations, f"electric_vehicle_charger_{charger_id}_connected_state"),
        _flat_observation(env, observations, f"connected_electric_vehicle_at_charger_{charger_id}_soc"),
    )


# ---------------------------------------------------------------------------- basic contract


def test_external_rows_start_away_and_run_without_provider():
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0)
    env.reset()
    for name in ("charger_1_1", "charger_2_1"):
        simulation = _charger(env, name).charger_simulation
        assert np.all(simulation.electric_vehicle_charger_state == 3)
        assert len(simulation.electric_vehicle_charger_state) == env.time_steps
    assert env.mobility.external_charger_ids == ["charger_1_1", "charger_2_1"]
    assert env.mobility.external_vehicle_ids == [EV]

    while not env.terminated:
        env.step(_flat_actions(env, ev=1.0))

    assert all(np.all(_charger(env, name).electricity_consumption == 0.0) for name in ("charger_1_1", "charger_2_1"))


def test_provider_is_a_protocol_and_must_have_both_methods():
    assert isinstance(Scripted(), MobilityProvider)
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0)
    with pytest.raises(TypeError, match="reset\\(env\\) and update\\(env, time_step\\)"):
        env.mobility_provider = object()


def test_update_runs_after_the_interval_and_before_association_for_every_non_terminal_step():
    energy_seen = {}

    def record(env):
        t = int(env.time_step)
        energy_seen[t] = (env.mobility.charger_energy_kwh("charger_1_1"), env.mobility.vehicle_soc(EV))

    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.2)}
    plan.update({t: record for t in range(1, 8)})
    provider = Scripted(plan)
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0)
    env.mobility_provider = provider
    env.reset()
    assert provider.calls == [("reset", 0)]

    while not env.terminated:
        env.step(_flat_actions(env, ev=1.0))

    # Updates for t = 1 .. T - 2: the terminal transition takes no further action.
    assert provider.calls[1:] == [("update", t, t) for t in range(1, env.time_steps - 1)]
    charger = _charger(env, "charger_1_1")
    battery = _vehicle(env).battery
    for t, (energy, soc) in energy_seen.items():
        # The finished interval's energy and the SOC it produced are already final.
        assert energy == pytest.approx(float(charger.electricity_consumption[t - 1]))
        assert energy > 0.0
        assert soc == pytest.approx(float(battery.soc[t - 1]))


@pytest.mark.parametrize("interface", ["flat", "entity"])
@pytest.mark.parametrize("central_agent", [True, False])
def test_vehicle_moves_between_buildings_with_soc_continuity(interface, central_agent):
    consumption = 0.07
    recorded = {}

    def leave(env):
        recorded["before_drive"] = env.mobility.vehicle_soc(EV)
        env.mobility.away("charger_1_1")
        env.mobility.set_vehicle_soc(EV, recorded["before_drive"] - consumption)

    plan = {
        0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.3, departure_steps=2, required_soc=0.9),
        2: leave,
        3: lambda env: env.mobility.incoming("charger_2_1", EV, arrival_steps=1, soc_on_arrival=0.2),
        4: lambda env: (env.mobility.away("charger_2_1"),
                        env.mobility.connect("charger_2_1", EV, departure_steps=3, required_soc=0.8)),
    }
    env = CityLearnEnv(_schema(), central_agent=central_agent, interface=interface, random_seed=0,
                       mobility_provider=Scripted(plan))
    observations, _ = env.reset()
    assert _connected(env, observations, "charger_1_1") == (1.0, pytest.approx(0.3))
    assert _connected(env, observations, "charger_2_1")[0] == 0.0

    trace = [observations]
    while not env.terminated:
        observations, *_ = env.step(_actions(env, ev=1.0))
        trace.append(observations)

    battery = _vehicle(env).battery
    # Charged at building 1 in intervals 0 and 1, then driven: the SOC is carried, not reset.
    assert battery.soc[1] > battery.soc[0] > 0.3
    assert recorded["before_drive"] == pytest.approx(float(battery.soc[1]))
    assert battery.soc[2] == pytest.approx(recorded["before_drive"] - consumption, abs=1e-6)
    # No charging and no drift while away (external vehicle, no standby loss).
    assert battery.soc[3] == pytest.approx(float(battery.soc[2]))
    # The session at building 2 starts from the vehicle's own SOC and is the KPI arrival reference.
    simulation = _charger(env, "charger_2_1").charger_simulation
    assert float(simulation.electric_vehicle_current_soc[4]) == pytest.approx(float(battery.soc[3]))
    assert battery.soc[4] > battery.soc[3]
    # Observations returned by step() already show the connections written in that step's update.
    assert [_connected(env, trace[t], "charger_1_1")[0] for t in range(8)] == [1, 1, 0, 0, 0, 0, 0, 0]
    assert [_connected(env, trace[t], "charger_2_1")[0] for t in range(8)] == [0, 0, 0, 0, 1, 1, 1, 1]
    # The connected SOC observed on arrival is the arrival SOC, known before the action.
    assert _connected(env, trace[4], "charger_2_1")[1] == pytest.approx(float(battery.soc[3]))
    if interface == "flat":
        assert _flat_observation(env, trace[3], "electric_vehicle_charger_charger_2_1_incoming_state") == 1.0
        assert _flat_observation(
            env, trace[4], "connected_electric_vehicle_at_charger_charger_2_1_departure_time") == 3.0
        assert _flat_observation(
            env, trace[6], "connected_electric_vehicle_at_charger_charger_2_1_departure_time") == 1.0
    assert np.all(_charger(env, "charger_1_1").electricity_consumption[2:] == 0.0)


def test_set_vehicle_soc_is_observed_in_the_same_step():
    plan = {3: lambda env: env.mobility.set_vehicle_soc(EV, 0.123)}
    env = CityLearnEnv(_schema(), central_agent=True, interface="entity", random_seed=0,
                       mobility_provider=Scripted(plan))
    env.reset()
    for _ in range(3):
        observations, *_ = env.step(_entity_actions(env))
    specs = env.entity_specs["tables"]["ev"]
    soc = observations["tables"]["ev"][specs["ids"].index(EV), specs["features"].index("soc")]
    assert soc == pytest.approx(0.123)


# -------------------------------------------------------------------- energy limits


def _single_step_energy(*, connected_seconds=None, action=1.0, soc=0.4, floor=None):
    kwargs = {}
    if connected_seconds is not None:
        kwargs["connected_seconds"] = connected_seconds
    if floor is not None:
        kwargs["discharge_soc_floor"] = floor
    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=soc, **kwargs)}
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0, mobility_provider=Scripted(plan))
    env.reset()
    env.step(_flat_actions(env, ev=action))
    return env, float(_charger(env, "charger_1_1").electricity_consumption[0]), float(_vehicle(env).battery.soc[0])


def test_connected_seconds_limit_the_energy_of_that_step_only():
    _, full, full_soc = _single_step_energy()
    _, half, half_soc = _single_step_energy(connected_seconds=STEP_SECONDS / 2)
    _, none, none_soc = _single_step_energy(connected_seconds=0.0)

    assert full == pytest.approx(7.2 * STEP_SECONDS / 3600.0, rel=1e-6)
    assert half == pytest.approx(full / 2.0, rel=1e-6)
    assert half_soc - 0.4 == pytest.approx((full_soc - 0.4) / 2.0, rel=1e-5)
    assert none == 0.0 and none_soc == pytest.approx(0.4)

    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.4, connected_seconds=300.0)}
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0, mobility_provider=Scripted(plan))
    env.reset()
    env.step(_flat_actions(env, ev=1.0))
    env.step(_flat_actions(env, ev=1.0))
    consumption = _charger(env, "charger_1_1").electricity_consumption
    simulation = _charger(env, "charger_1_1").charger_simulation
    assert np.isnan(simulation.electric_vehicle_connected_seconds[1])
    assert consumption[1] == pytest.approx(3.0 * consumption[0], rel=1e-5)


def test_partial_connection_applies_battery_power_limit_over_the_connected_time():
    schema = _schema()
    attributes = schema["buildings"]["Building_1"]["chargers"]["charger_1_1"]["attributes"]
    attributes["max_charging_power"] = 22.0
    attributes["nominal_power"] = 22.0
    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.2, connected_seconds=450.0)}
    env = CityLearnEnv(schema, central_agent=True, random_seed=0, mobility_provider=Scripted(plan))
    env.reset()
    env.step(_flat_actions(env, ev=1.0))
    battery = _vehicle(env).battery
    # The battery (7.2 kW nominal, derated by its capacity-power curve) limits the 22 kW charger
    # over the 450 s it is plugged in, not over the whole 900 s step.
    battery_power_kw = float(battery.get_max_input_power(energy_init=0.2 * battery.capacity))
    assert 6.0 < battery_power_kw <= 7.2
    assert float(battery.energy_balance[0]) == pytest.approx(battery_power_kw * 450.0 / 3600.0, rel=1e-6)
    assert float(_charger(env, "charger_1_1").electricity_consumption[0]) < 22.0 * 450.0 / 3600.0


def test_discharge_soc_floor_stops_discharging_at_the_floor():
    _, free_energy, free_soc = _single_step_energy(action=-1.0, soc=0.5)
    _, floor_energy, floor_soc = _single_step_energy(action=-1.0, soc=0.5, floor=0.45)
    _, below_energy, below_soc = _single_step_energy(action=-1.0, soc=0.4, floor=0.45)
    _, charge_energy, charge_soc = _single_step_energy(action=1.0, soc=0.4, floor=0.45)

    assert free_soc < 0.45 and free_energy < 0.0
    assert floor_soc == pytest.approx(0.45, abs=1e-6)
    assert 0.0 > floor_energy > free_energy
    # Below the floor there is nothing to discharge; charging is unaffected.
    assert below_energy == 0.0 and below_soc == pytest.approx(0.4)
    assert charge_energy > 0.0 and charge_soc > 0.4


def test_discharge_floor_lasts_for_the_session():
    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.5, discharge_soc_floor=0.42)}
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0, mobility_provider=Scripted(plan))
    env.reset()
    for _ in range(4):
        env.step(_flat_actions(env, ev=-1.0))
    soc = _vehicle(env).battery.soc[:4]
    assert np.all(soc >= 0.42 - 1e-6)
    assert soc[3] == pytest.approx(0.42, abs=1e-6)


def test_external_vehicle_has_no_random_drift_but_other_vehicles_keep_it():
    env = CityLearnEnv(_schema(second_ev_external=False), central_agent=True, random_seed=0,
                       mobility_provider=Scripted())
    env.reset()
    while not env.terminated:
        env.step(_flat_actions(env))
    external = _vehicle(env, EV).battery.soc[:env.time_steps - 1]
    drifting = _vehicle(env, EV2).battery.soc[:env.time_steps - 1]
    assert np.all(external == external[0])
    assert len(set(np.round(drifting, 6))) > 1


# ----------------------------------------------------------------------- episodes


def test_every_episode_starts_away_and_calls_reset():
    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.5, departure_steps=10),
            2: lambda env: env.mobility.connect("charger_2_1", EV2)}
    provider = Scripted(plan)
    env = CityLearnEnv(_schema(second_ev_external=True), central_agent=True, random_seed=0, episode_time_steps=4,
                       mobility_provider=provider)
    for episode in range(2):
        provider.calls.clear()
        env.reset()
        assert env.time_steps == 4
        # Clamped to the episode length, the observation-space bound.
        assert _charger(env, "charger_1_1").charger_simulation.electric_vehicle_departure_time[0] == 4
        assert np.all(_charger(env, "charger_2_1").charger_simulation.electric_vehicle_charger_state == 3)
        while not env.terminated:
            env.step(_flat_actions(env, ev=1.0))
        assert provider.calls == [("reset", 0), ("update", 1, 1), ("update", 2, 2)]
        states = _charger(env, "charger_2_1").charger_simulation.electric_vehicle_charger_state
        assert list(states) == [3, 3, 1, 1]


def test_entity_interface_and_step_many_call_the_provider_once_per_step():
    provider = Scripted({0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.5)})
    env = CityLearnEnv(_schema(), central_agent=True, interface="entity", random_seed=0, mobility_provider=provider)
    provider.calls.clear()
    env.reset()
    env.step(_entity_actions(env, ev=0.5))
    _ = env.observations
    _ = env.observations
    env.step_many(_entity_actions(env, ev=0.5), repeat_steps=3)
    assert provider.calls == [("reset", 0)] + [("update", t, t) for t in range(1, 5)]


# ------------------------------------------------------------------ KPIs and BAU


def test_departure_kpis_and_business_as_usual_replay_follow_the_written_sessions():
    plan = {
        0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.3, departure_steps=2, required_soc=0.5),
        2: lambda env: (env.mobility.away("charger_1_1"), env.mobility.set_vehicle_soc(EV, 0.25)),
        3: lambda env: env.mobility.connect("charger_2_1", EV, departure_steps=2, required_soc=0.95,
                                            connected_seconds=600.0),
        5: lambda env: env.mobility.away("charger_2_1"),
    }
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0, mobility_provider=Scripted(plan))
    env.reset()
    while not env.terminated:
        # Half power: the BAU charges at full power and must deliver more in the same sessions.
        env.step(_flat_actions(env, ev=0.5))

    kpis = env.evaluate_v2()
    district = kpis[kpis["level"] == "district"].set_index("cost_function")["value"]
    assert district["district_ev_events_departure_count"] == 2
    assert district["district_ev_departure_audit_departures_count"] == 2
    assert district["district_ev_departure_audit_service_coverage_ratio"] == 1.0
    assert district["district_ev_departure_audit_target_unknown_count"] == 0
    controlled = float(sum(np.sum(_charger(env, c).electricity_consumption) for c in ("charger_1_1", "charger_2_1")))
    assert district["district_ev_total_charge_kwh"] == pytest.approx(controlled, rel=1e-5)
    assert district["district_ev_total_charge_business_as_usual_kwh"] > controlled

    bau = env.run_business_as_usual_baseline().env
    bau_battery = _vehicle(bau).battery
    for name in ("charger_1_1", "charger_2_1"):
        ours = _charger(env, name).charger_simulation
        theirs = _charger(bau, name).charger_simulation
        assert list(theirs.electric_vehicle_charger_state[:7]) == list(ours.electric_vehicle_charger_state[:7])
        assert list(theirs.electric_vehicle_session_id[:7]) == list(ours.electric_vehicle_session_id[:7])
    # The BAU starts from the same arrival SOC, then sees the same driving consumption as a change.
    assert bau_battery.soc[0] > _vehicle(env).battery.soc[0]
    driven = float(_vehicle(env).battery.soc[2]) - float(_vehicle(env).battery.soc[1])
    assert float(bau_battery.soc[2]) - float(bau_battery.soc[1]) == pytest.approx(driven, abs=1e-6)
    # The BAU's partial-interval step at building 2 is two thirds of a full-power step.
    bau_consumption = _charger(bau, "charger_2_1").electricity_consumption
    assert bau_consumption[3] == pytest.approx(7.2 * 600.0 / 3600.0, rel=1e-5)


# ----------------------------------------------------------------------- errors


def _error_env(action, *, second_ev=True, file_charger=False):
    plan = {0: action}
    env = CityLearnEnv(
        _schema(second_ev_external=True if second_ev else None, file_charger_in_building_1=file_charger),
        central_agent=True, random_seed=0,
    )
    env.mobility_provider = Scripted(plan)
    return env


@pytest.mark.parametrize(
    "action, message",
    [
        (lambda env: env.mobility.connect("charger_9_9", EV), "Unknown charger 'charger_9_9'"),
        (lambda env: env.mobility.connect("charger_1_1", "Nobody"), "Unknown electric vehicle 'Nobody'"),
        (lambda env: (env.mobility.connect("charger_1_1", EV), env.mobility.connect("charger_2_1", EV)),
         "connected to charger 'charger_1_1'"),
        (lambda env: (env.mobility.connect("charger_1_1", EV), env.mobility.connect("charger_1_1", EV2)),
         "is connected to 'Electric_Vehicle_1'"),
        (lambda env: (env.mobility.connect("charger_1_1", EV), env.mobility.incoming("charger_1_1", EV2)),
         "before announcing"),
        (lambda env: env.mobility.connect("charger_1_1", EV, soc=1.2), r"soc must be in \[0, 1\]"),
        (lambda env: env.mobility.connect("charger_1_1", EV, soc=float("nan")), "soc must be finite"),
        (lambda env: env.mobility.connect("charger_1_1", EV, required_soc=-0.1), "required_soc must be in"),
        (lambda env: env.mobility.connect("charger_1_1", EV, discharge_soc_floor=2), "discharge_soc_floor must be in"),
        (lambda env: env.mobility.set_vehicle_soc(EV, -0.01), r"soc must be in \[0, 1\]"),
        (lambda env: env.mobility.incoming("charger_1_1", EV, soc_on_arrival=1.5), "soc_on_arrival must be in"),
        (lambda env: env.mobility.connect("charger_1_1", EV, connected_seconds=901), r"connected_seconds must be in \[0, 900\]"),
        (lambda env: env.mobility.connect("charger_1_1", EV, connected_seconds=-1), "connected_seconds must be in"),
        (lambda env: env.mobility.connect("charger_1_1", EV, departure_steps=-2), "departure_steps must be"),
        (lambda env: env.mobility.connect("charger_1_1", EV, departure_steps=1.5), "departure_steps must be"),
        (lambda env: env.mobility.connect("charger_1_1", EV, session_id=" "), "session_id must be"),
    ],
)
def test_invalid_writes_raise_clear_errors(action, message):
    env = _error_env(action)
    with pytest.raises(ValueError, match=message):
        env.reset()


def test_writes_to_running_sessions_and_file_chargers_are_rejected():
    env = _error_env(lambda env: env.mobility.connect("charger_1_1", EV), file_charger=True)
    with pytest.raises(ValueError, match="reads its schedule from a file"):
        env.reset()

    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.4),
            1: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.6)}
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0, mobility_provider=Scripted(plan))
    env.reset()
    with pytest.raises(ValueError, match="soc is accepted only when a session starts"):
        env.step(_flat_actions(env))

    plan = {0: lambda env: env.mobility.connect("charger_1_1", EV, soc=0.4),
            1: lambda env: env.mobility.set_vehicle_soc(EV, 0.6)}
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0, mobility_provider=Scripted(plan))
    env.reset()
    with pytest.raises(ValueError, match="continues its charging session"):
        env.step(_flat_actions(env))


def test_writes_outside_the_provider_are_rejected():
    env = CityLearnEnv(_schema(), central_agent=True, random_seed=0)
    env.reset()
    with pytest.raises(RuntimeError, match="only while CityLearn calls the mobility provider"):
        env.mobility.connect("charger_1_1", EV)
    assert env.mobility.vehicle_soc(EV) == pytest.approx(0.4)
    assert env.mobility.charger_energy_kwh("charger_1_1") == 0.0


def test_ambiguous_charger_names_need_the_building():
    schema = _schema()
    schema["buildings"]["Building_2"]["chargers"] = {
        "charger_1_1": schema["buildings"]["Building_2"]["chargers"]["charger_2_1"]}
    env = CityLearnEnv(schema, central_agent=True, random_seed=0,
                       mobility_provider=Scripted({0: lambda env: env.mobility.connect("Building_2/charger_1_1", EV)}))
    env.reset()
    assert env.buildings[1].electric_vehicle_chargers[0].charger_simulation.electric_vehicle_charger_state[0] == 1
    env.mobility_provider = Scripted({0: lambda env: env.mobility.connect("charger_1_1", EV)})
    with pytest.raises(ValueError, match="used by several buildings"):
        env.reset()


def test_schema_errors():
    schema = _schema()
    schema["buildings"]["Building_1"]["chargers"]["charger_1_1"]["charger_simulation"] = {"source": "sumo"}
    with pytest.raises(ValueError, match='charger_simulation.source must be "external"'):
        CityLearnEnv(schema, central_agent=True)

    schema = _schema()
    schema["buildings"]["Building_1"]["chargers"]["charger_1_1"]["charger_simulation"] = {
        "source": "external", "file": "x.csv"}
    with pytest.raises(ValueError, match="unknown keys"):
        CityLearnEnv(schema, central_agent=True)

    with pytest.raises(ValueError, match='not supported with topology_mode="dynamic"'):
        CityLearnEnv(_schema(), central_agent=True, interface="entity", topology_mode="dynamic")
