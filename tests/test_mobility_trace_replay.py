"""Charger-simulation files replay what an external mobility provider wrote (session rows and trip energy)."""

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.data import ChargerSimulation

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "tests" / "data" / "minute_ev_demo"
EV = "Electric_Vehicle_1"
CONSUMPTION = 0.07
CHARGERS = ("charger_1_1", "charger_2_1")
FILE_COLUMNS = (
    "electric_vehicle_charger_state",
    "electric_vehicle_id",
    "electric_vehicle_session_id",
    "electric_vehicle_departure_time",
    "electric_vehicle_required_soc_departure",
    "electric_vehicle_estimated_arrival_time",
    "electric_vehicle_estimated_soc_arrival",
    "electric_vehicle_current_soc",
    *ChargerSimulation.SESSION_COLUMNS[:4],
)


def _schema(root=DEMO, external=True):
    """Two buildings with one 7.2 kW charger each and one EV (8 x 15 min); external or read from files."""

    schema = json.loads((DEMO / "schema.json").read_text())
    schema["root_directory"] = str(root)
    building_1 = schema["buildings"]["Building_1"]
    charger = building_1["chargers"]["charger_1_1"]
    building_2 = copy.deepcopy(building_1)
    building_2["chargers"] = {"charger_2_1": copy.deepcopy(charger)}
    schema["buildings"]["Building_2"] = building_2
    for name, definition in (("charger_1_1", charger), ("charger_2_1", building_2["chargers"]["charger_2_1"])):
        definition["charger_simulation"] = {"source": "external"} if external else f"{name}.csv"
    vehicle = schema["electric_vehicles_def"][EV]
    vehicle["external"] = True
    vehicle["battery"]["attributes"]["loss_coefficient"] = 0.0
    return schema


class Scripted:
    """Mobility of the recorded episode: a session in building 1, a drive that uses energy, a session in building 2."""

    def reset(self, env):
        self._run(env, 0)

    def update(self, env, time_step):
        self._run(env, int(time_step))

    def _run(self, env, t):
        mobility = env.mobility
        if t == 0:
            mobility.connect(
                "charger_1_1", EV, soc=0.3, departure_seconds=1700.0, required_soc=0.9, connected_seconds=800.0,
                discharge_soc_floor=0.2, connected_since_seconds=-100.0,
            )
        elif t == 1:
            mobility.connect("charger_1_1", EV, connected_seconds=800.0)
        elif t == 2:
            soc = mobility.vehicle_soc(EV)
            mobility.away("charger_1_1")
            mobility.set_vehicle_soc(EV, soc - CONSUMPTION)
        elif t == 3:
            mobility.incoming("charger_2_1", EV, arrival_steps=1, soc_on_arrival=0.2)
        elif t == 4:
            mobility.away("charger_2_1")
            mobility.connect("charger_2_1", EV, departure_seconds=2700.0, required_soc=0.8)


def _actions(env, ev):
    return [np.array([ev if name.startswith("electric_vehicle_storage") else 0.0 for name in names], dtype="float32")
            for names in env.action_names]


def _run(env, ev):
    env.reset()
    while not env.terminated:
        env.step(_actions(env, ev))


def _charger(env, name):
    return next(c for b in env.buildings for c in b.electric_vehicle_chargers or [] if c.charger_id == name)


def _export(env, directory):
    """Write the rows the provider wrote as charger files; trip energy on the first row of a session."""

    shutil.copytree(DEMO, directory, dirs_exist_ok=True)
    capacity = env.electric_vehicles[0].battery.capacity
    for name in CHARGERS:
        simulation = _charger(env, name).charger_simulation
        frame = pd.DataFrame({column: getattr(simulation, column) for column in FILE_COLUMNS})
        frame["electric_vehicle_trip_energy_kwh"] = np.nan
        if name == "charger_2_1":
            frame.loc[4, "electric_vehicle_trip_energy_kwh"] = CONSUMPTION * capacity
        frame.to_csv(directory / f"{name}.csv", index=False)


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    directory = tmp_path_factory.mktemp("trace")
    live = CityLearnEnv(_schema(), central_agent=True, random_seed=0, mobility_provider=Scripted())
    _run(live, 1.0)
    _export(live, directory)
    return live, directory


def _replay(directory, ev):
    env = CityLearnEnv(_schema(directory, external=False), central_agent=True, random_seed=0)
    _run(env, ev)
    return env


def test_replay_of_the_recorded_actions_matches_the_live_episode(recorded):
    live, directory = recorded
    replay = _replay(directory, 1.0)

    for name in CHARGERS:
        np.testing.assert_allclose(
            _charger(replay, name).electricity_consumption, _charger(live, name).electricity_consumption,
            rtol=1e-9, atol=1e-12,
        )

    connected = [0, 1, 4, 5, 6, 7]
    np.testing.assert_allclose(
        np.array(replay.electric_vehicles[0].battery.soc)[connected],
        np.array(live.electric_vehicles[0].battery.soc)[connected], rtol=1e-9,
    )
    live_kpis, replay_kpis = live.evaluate(), replay.evaluate()
    np.testing.assert_allclose(replay_kpis["value"].to_numpy(float), live_kpis["value"].to_numpy(float), rtol=1e-9,
                               equal_nan=True)


def test_session_rows_are_read_from_the_file(recorded):
    live, directory = recorded
    simulation = _charger(_replay(directory, 0.0), "charger_1_1").charger_simulation
    expected = _charger(live, "charger_1_1").charger_simulation

    for column in ChargerSimulation.SESSION_COLUMNS[:4]:
        np.testing.assert_array_equal(getattr(simulation, column), getattr(expected, column))

    assert simulation.electric_vehicle_connected_seconds[0] == 800.0
    assert simulation.electric_vehicle_departure_seconds[0] == 1700.0
    assert simulation.electric_vehicle_discharge_soc_floor[1] == 0.2


def test_arrival_soc_follows_the_soc_at_departure_minus_the_trip_energy(recorded):
    live, directory = recorded
    charger = _charger(live, "charger_2_1")
    capacity = live.electric_vehicles[0].battery.capacity

    for action in (1.0, -1.0, 0.0):
        replay = _replay(directory, action)
        soc = np.array(replay.electric_vehicles[0].battery.soc)
        # The EV holds its SOC while away (no drift) and arrives lower by the trip energy.
        assert soc[3] == pytest.approx(soc[2])
        arrival = float(np.clip(soc[3] - CONSUMPTION * capacity / capacity, 0.0, 1.0))
        assert _charger(replay, "charger_2_1").charger_simulation.electric_vehicle_current_soc[4] == \
            pytest.approx(arrival, abs=1e-6)

    # Only the recorded action reproduces the recorded arrival SOC; the absolute value would not follow the action.
    assert charger.charger_simulation.electric_vehicle_current_soc[4] == pytest.approx(
        _charger(_replay(directory, 1.0), "charger_2_1").charger_simulation.electric_vehicle_current_soc[4], abs=1e-6)
    assert _charger(_replay(directory, 0.0), "charger_2_1").charger_simulation.electric_vehicle_current_soc[4] \
        < charger.charger_simulation.electric_vehicle_current_soc[4] - 0.05


def test_trip_energy_that_exceeds_the_soc_clips_at_empty(recorded):
    _, directory = recorded
    path = directory / "charger_2_1.csv"
    frame = pd.read_csv(path)
    frame.loc[4, "electric_vehicle_trip_energy_kwh"] = 1.0e6
    frame.to_csv(path, index=False)
    env = _replay(directory, 0.0)
    assert _charger(env, "charger_2_1").charger_simulation.electric_vehicle_current_soc[4] == 0.0


def test_files_without_the_columns_load_as_before():
    schema = json.loads((DEMO / "schema.json").read_text())
    schema["root_directory"] = str(DEMO)
    simulation = _charger(CityLearnEnv(schema, central_agent=True, random_seed=0), "charger_1_1").charger_simulation

    for column in ChargerSimulation.SESSION_COLUMNS:
        assert not hasattr(simulation, column)

    assert not hasattr(simulation, "trip_energy_vehicle_ids")


@pytest.mark.parametrize("column,value,message", [
    ("electric_vehicle_connected_seconds", 901.0, "connected_seconds must be in"),
    ("electric_vehicle_connected_seconds", -1.0, "connected_seconds must be in"),
    ("electric_vehicle_discharge_soc_floor", 1.5, "ratio in"),
    ("electric_vehicle_departure_seconds", 0.0, "must be > 0"),
])
def test_invalid_session_columns_are_rejected(recorded, tmp_path, column, value, message):
    _, directory = recorded
    shutil.copytree(directory, tmp_path, dirs_exist_ok=True)
    path = tmp_path / "charger_1_1.csv"
    frame = pd.read_csv(path)
    frame.loc[0, column] = value
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match=message):
        _replay(tmp_path, 0.0)
