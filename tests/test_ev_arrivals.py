import json
import numpy as np
import pandas as pd
import pytest

from pathlib import Path

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.data import ChargerSimulation


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = str((ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json").resolve(strict=True))
MINUTE_SCHEMA_PATH = (ROOT / "tests/data/minute_ev_demo/schema.json").resolve(strict=True)


def _zero_actions(env: CityLearnEnv):
    return [np.zeros(space.shape, dtype="float32") for space in env.action_space]


def _find_transition(from_state: int):
    for csv_path in sorted(Path(SCHEMA_PATH).parent.glob("charger_*_*.csv")):
        df = pd.read_csv(csv_path)
        for idx in range(len(df) - 1):
            if (
                df.loc[idx, "electric_vehicle_charger_state"] == from_state
                and df.loc[idx + 1, "electric_vehicle_charger_state"] == 1
            ):
                return csv_path, idx

    raise AssertionError(f"No {from_state}->1 transition found in {Path(SCHEMA_PATH).parent}.")


@pytest.mark.parametrize("from_state", [2, 3])
def test_ev_soc_matches_dataset_on_arrival(from_state: int):
    csv_path, transition_index = _find_transition(from_state)
    charger_id = csv_path.stem

    env = CityLearnEnv(SCHEMA_PATH, central_agent=True, random_seed=0)
    env.reset()

    # Advance the environment to the timestep of interest.
    for _ in range(transition_index + 1):
        env.step(_zero_actions(env))

    # Identify the EV connected to the selected charger.
    target_ev_id = None

    for building in env.buildings:
        for charger in building.electric_vehicle_chargers or []:
            if charger.charger_id == charger_id:
                sim = charger.charger_simulation
                target_ev_id = sim.electric_vehicle_id[transition_index + 1]
                break
        if target_ev_id:
            break

    assert target_ev_id, "Expected EV id for charger transition not found."

    ev = next(ev for ev in env.electric_vehicles if ev.name == target_ev_id)

    step = env.time_step
    prev_state = sim.electric_vehicle_charger_state[step - 1] if step > 0 else float("nan")

    candidate_index = None
    if prev_state in (2, 3):
        candidate_index = step - 1
    elif 0 <= step < len(sim.electric_vehicle_estimated_soc_arrival):
        candidate_index = step

    estimated_soc = None
    if candidate_index is not None and 0 <= candidate_index < len(sim.electric_vehicle_estimated_soc_arrival):
        candidate_value = sim.electric_vehicle_estimated_soc_arrival[candidate_index]
        if isinstance(candidate_value, (float, np.floating)) and not np.isnan(candidate_value) and candidate_value >= 0:
            estimated_soc = float(candidate_value)

    if estimated_soc is None:
        expected_soc = float(ev.battery.soc[step - 1])
        required_soc = float(sim.electric_vehicle_required_soc_departure[step])
        assert float(ev.battery.soc[env.time_step]) == pytest.approx(expected_soc, abs=1e-6)
        if not np.isclose(expected_soc, required_soc):
            assert float(ev.battery.soc[env.time_step]) != pytest.approx(required_soc, abs=1e-6)
        return

    expected_soc = estimated_soc

    assert pytest.approx(expected_soc, abs=1e-6) == float(ev.battery.soc[env.time_step])


def test_arrival_soc_estimate_found_on_earlier_incoming_row():
    # charger_12_1: Electric_Vehicle_4 is incoming at rows 705 (one step to arrival, estimate 17 %) and
    # 706 (no estimate), then connects at 707.
    env = CityLearnEnv(
        SCHEMA_PATH, central_agent=True, simulation_start_time_step=695, simulation_end_time_step=730, random_seed=1,
    )
    env.reset()
    charger = next(
        c for b in env.buildings for c in (b.electric_vehicle_chargers or []) if c.charger_id == 'charger_12_1'
    )
    sim = charger.charger_simulation
    ev = next(e for e in env.electric_vehicles if e.name == 'Electric_Vehicle_4')
    arrival = 707 - 695
    assert sim.electric_vehicle_charger_state[arrival - 2:arrival + 1].tolist() == [2, 2, 1]
    assert sim.electric_vehicle_estimated_soc_arrival[arrival - 1] < 0.0, 'last incoming row has no estimate'
    estimate = float(sim.electric_vehicle_estimated_soc_arrival[arrival - 2])
    assert estimate == pytest.approx(0.17, abs=0.05)

    while env.time_step < arrival:
        env.step(_zero_actions(env))

    assert charger.connected_electric_vehicle is ev
    assert float(ev.battery.soc[arrival]) == pytest.approx(estimate, abs=1e-6)
    states = np.asarray(sim.electric_vehicle_charger_state, dtype='float64')
    assert env._kpi_service._ev_arrival_soc_for_interval(sim, ev, states, arrival) == pytest.approx(estimate, abs=1e-6)
    env.close()


def test_arrival_soc_index_reads_only_the_incoming_rows_of_the_arriving_ev():
    index = ChargerSimulation.arrival_soc_index
    states = np.array([1, 2, 2, 2, 1, 3, 2, 3, 1, 2, 2, 1], dtype='float32')
    ids = np.array(['A', 'A', 'A', 'A', 'A', None, 'A', None, 'A', 'A', 'B', 'B'], dtype=object)
    soc = np.array([-0.1, 0.3, 0.4, -0.1, -0.1, -0.1, 0.5, -0.1, -0.1, 0.6, -0.1, -0.1], dtype='float32')

    assert index(states, ids, soc, 4) == 2  # latest estimate of the incoming block
    soc[3] = 0.45
    assert index(states, ids, soc, 4) == 3  # the usual case: the last incoming row
    assert index(states, ids, soc, 8) is None  # an announcement behind away rows is stale
    assert index(states, ids, soc, 11) is None  # never another EV's estimate
    soc[0] = 0.2
    assert index(states, ids, soc, 0) == 0  # no preceding row: the arrival row itself


def test_connected_ev_without_arrival_soc_uses_initial_soc_on_reset():
    env = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, random_seed=0)
    env.reset()

    ev = env.electric_vehicles[0]
    charger = env.buildings[0].electric_vehicle_chargers[0]

    assert charger.connected_electric_vehicle is ev
    assert charger.charger_simulation.electric_vehicle_required_soc_departure[0] == pytest.approx(0.8)
    assert ev.battery.initial_soc == pytest.approx(0.4)
    assert float(ev.battery.soc[0]) == pytest.approx(ev.battery.initial_soc)


def test_charger_simulation_soc_fields_accept_fraction_and_percent_units():
    simulation = ChargerSimulation(
        electric_vehicle_charger_state=[1, 1, 2, 2, 3],
        electric_vehicle_id=["EV"] * 5,
        electric_vehicle_departure_time=[1, 1, -1, -1, -1],
        electric_vehicle_required_soc_departure=[0.8, 80.0, np.nan, -0.1, 150.0],
        electric_vehicle_estimated_arrival_time=[-1, -1, 1, 1, -1],
        electric_vehicle_estimated_soc_arrival=[0.4, 40.0, np.nan, -0.1, 125.0],
        noise_std=0.0,
    )

    np.testing.assert_allclose(
        simulation.electric_vehicle_required_soc_departure,
        [0.8, 0.8, -0.1, -0.1, 1.0],
        atol=1.0e-6,
    )
    np.testing.assert_allclose(
        simulation.electric_vehicle_estimated_soc_arrival,
        [0.4, 0.4, -0.1, -0.1, 1.0],
        atol=1.0e-6,
    )


def test_ev_battery_schema_attributes_are_loaded(tmp_path):
    schema = json.loads(MINUTE_SCHEMA_PATH.read_text())
    schema["root_directory"] = str(MINUTE_SCHEMA_PATH.parent.resolve())

    attrs = schema["electric_vehicles_def"]["Electric_Vehicle_1"]["battery"]["attributes"]
    attrs.update(
        {
            "efficiency": 1.0,
            "capacity_loss_coefficient": 0.0,
            "power_efficiency_curve": [[0.0, 1.0], [1.0, 1.0]],
            "capacity_power_curve": [[0.0, 1.0], [1.0, 1.0]],
        }
    )

    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema))

    env = CityLearnEnv(str(schema_path), central_agent=True, random_seed=0)
    env.reset()

    battery = env.electric_vehicles[0].battery
    assert battery.efficiency == pytest.approx(1.0)
    assert battery.capacity_loss_coefficient == pytest.approx(0.0)
    assert np.allclose(battery.power_efficiency_curve, np.array([[0.0, 1.0], [1.0, 1.0]]).T)
    assert np.allclose(battery.capacity_power_curve, np.array([[0.0, 1.0], [1.0, 1.0]]).T)


def test_connected_ev_soc_carries_forward_to_current_observations():
    env = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, random_seed=0)
    env.reset()

    charger = env.buildings[0].electric_vehicle_chargers[0]
    ev = charger.connected_electric_vehicle
    initial_soc = float(ev.battery.soc[env.time_step])

    env.step(_zero_actions(env))

    assert charger.connected_electric_vehicle is ev
    assert float(ev.battery.soc[env.time_step]) == pytest.approx(initial_soc)

    observations = env.buildings[0].observations(
        include_all=True,
        normalize=False,
        periodic_normalization=False,
        check_limits=True,
    )
    soc_key = f"connected_electric_vehicle_at_charger_{charger.charger_id}_soc"
    assert observations[soc_key] == pytest.approx(initial_soc)


def test_connected_ev_current_soc_reference_does_not_overwrite_runtime_control():
    env = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, random_seed=0)
    env.reset()

    charger = env.buildings[0].electric_vehicle_chargers[0]
    ev = charger.connected_electric_vehicle
    assert ev is not None
    initial_soc = float(ev.battery.soc[env.time_step])
    forced_reference = min(initial_soc + 0.35, 0.95)
    current_soc = np.full(
        len(charger.charger_simulation.electric_vehicle_charger_state),
        -0.1,
        dtype="float32",
    )
    current_soc[1] = forced_reference
    charger.charger_simulation.electric_vehicle_current_soc = current_soc

    env.step(_zero_actions(env))

    assert charger.connected_electric_vehicle is ev
    assert float(ev.battery.soc[env.time_step]) == pytest.approx(initial_soc)
    assert float(ev.battery.soc[env.time_step]) != pytest.approx(forced_reference)
    env.close()


@pytest.mark.parametrize("explicit_session_identity", [False, True])
def test_back_to_back_session_of_same_ev_reinitializes_arrival_soc_once(
    explicit_session_identity: bool,
):
    env = CityLearnEnv(str(MINUTE_SCHEMA_PATH), central_agent=True, random_seed=0)
    env.reset()

    charger = env.buildings[0].electric_vehicle_chargers[0]
    ev = charger.connected_electric_vehicle
    assert ev is not None
    sim = charger.charger_simulation
    sim.electric_vehicle_charger_state[:2] = 1
    sim.electric_vehicle_id[:2] = ev.name
    sim.electric_vehicle_session_id[:2] = (
        ["SESSION_1", "SESSION_2"] if explicit_session_identity else ["", ""]
    )
    sim.electric_vehicle_departure_time[:2] = [1, 4]
    sim.electric_vehicle_current_soc = np.full(
        len(sim.electric_vehicle_charger_state), -0.1, dtype="float32"
    )
    sim.electric_vehicle_current_soc[1] = 0.25

    env.step(_zero_actions(env))

    assert charger.connected_electric_vehicle is ev
    assert float(ev.battery.soc[env.time_step]) == pytest.approx(0.25)
    env.close()


def test_static_battery_soc_carries_forward_to_current_observations(tmp_path):
    schema = json.loads(MINUTE_SCHEMA_PATH.read_text())
    schema["root_directory"] = str(MINUTE_SCHEMA_PATH.parent.resolve())
    schema["buildings"]["Building_1"]["electrical_storage"]["attributes"]["loss_coefficient"] = 0.0

    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema))

    env = CityLearnEnv(str(schema_path), central_agent=True, random_seed=0)
    env.reset()

    building = env.buildings[0]
    initial_soc = float(building.electrical_storage.soc[env.time_step])

    env.step(_zero_actions(env))

    assert float(building.electrical_storage.soc[env.time_step]) == pytest.approx(initial_soc)
    observations = building.observations(
        include_all=True,
        normalize=False,
        periodic_normalization=False,
        check_limits=True,
    )
    assert observations["electrical_storage_soc"] == pytest.approx(initial_soc)


def test_storage_observation_bounds_are_scaled_to_control_step_energy(tmp_path):
    schema = json.loads(MINUTE_SCHEMA_PATH.read_text())
    schema["root_directory"] = str(MINUTE_SCHEMA_PATH.parent.resolve())
    schema["observations"]["electrical_storage_electricity_consumption"] = {
        "active": True,
        "shared_in_central_agent": False,
    }

    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema))

    env = CityLearnEnv(str(schema_path), central_agent=True, random_seed=0)
    env.reset()

    building = env.buildings[0]
    low, high = building.estimate_observation_space_limits(
        include_all=True,
        periodic_normalization=False,
    )
    expected_limit = building.electrical_storage.nominal_power * building.seconds_per_time_step / 3600.0
    delta = building.observation_space_limit_delta

    assert low["electrical_storage_electricity_consumption"] == pytest.approx(-expected_limit - delta)
    assert high["electrical_storage_electricity_consumption"] == pytest.approx(expected_limit + delta)


def test_ev_kpi_evaluation_with_evs_and_chargers():
    env = CityLearnEnv(SCHEMA_PATH, central_agent=True, random_seed=0)
    env.reset()

    for _ in range(10):
        env.step(_zero_actions(env))

    df = env.evaluate()

    district_values = df[df["level"] == "district"]["value"]
    assert district_values.notna().any(), "District-level KPI values should contain finite entries when EVs are present."


def test_ev_current_soc_overrides_arrival_estimate_when_present():
    csv_path, transition_index = _find_transition(2)
    charger_id = csv_path.stem

    env = CityLearnEnv(SCHEMA_PATH, central_agent=True, random_seed=0)
    env.reset()

    target_charger = None
    for building in env.buildings:
        for charger in building.electric_vehicle_chargers or []:
            if charger.charger_id == charger_id:
                target_charger = charger
                break
        if target_charger is not None:
            break

    assert target_charger is not None, "Expected charger for transition was not found."
    sim = target_charger.charger_simulation
    forced_soc = 0.42
    current_soc = np.full(len(sim.electric_vehicle_charger_state), -0.1, dtype="float32")
    current_soc[transition_index + 1] = forced_soc
    sim.electric_vehicle_current_soc = current_soc

    for _ in range(transition_index + 1):
        env.step(_zero_actions(env))

    connected_ev = target_charger.connected_electric_vehicle
    assert connected_ev is not None, "Expected EV to be connected at the transition step."
    assert float(connected_ev.battery.soc[env.time_step]) == pytest.approx(forced_soc, abs=1e-6)
    building=next(b for b in env.buildings if target_charger in (b.electric_vehicle_chargers or []))
    key=f'connected_electric_vehicle_at_charger_{target_charger.charger_id}_soc'
    building.observation_metadata[key]=True
    assert building.observations()[key]==pytest.approx(forced_soc,abs=1e-6)
    env.step(_zero_actions(env))
    assert building.observations()[key]==pytest.approx(connected_ev.battery.soc[env.time_step-1],abs=1e-6)
    env.close()


def test_current_soc_initializes_runtime_reconnection_inside_occupied_window():
    csv_path, transition_index = _find_transition(2)
    charger_id = csv_path.stem
    env = CityLearnEnv(SCHEMA_PATH, central_agent=True, random_seed=0)
    env.reset()

    for _ in range(transition_index + 2):
        env.step(_zero_actions(env))

    target_charger = next(
        charger
        for building in env.buildings
        for charger in (building.electric_vehicle_chargers or [])
        if charger.charger_id == charger_id
    )
    sim = target_charger.charger_simulation
    assert sim.electric_vehicle_charger_state[env.time_step - 1] == 1
    assert sim.electric_vehicle_charger_state[env.time_step] == 1

    forced_soc = 0.42
    current_soc = np.full(len(sim.electric_vehicle_charger_state), -0.1, dtype="float32")
    current_soc[env.time_step] = forced_soc
    sim.electric_vehicle_current_soc = current_soc
    target_charger.connected_electric_vehicle = None
    # A newly activated/recommissioned charger has no committed association at
    # the preceding runtime step even if its annual schedule says occupied.
    target_charger.past_connected_evs[env.time_step - 1] = None

    env.associate_chargers_to_electric_vehicles()

    connected_ev = target_charger.connected_electric_vehicle
    assert connected_ev is not None
    assert float(connected_ev.battery.soc[env.time_step]) == pytest.approx(forced_soc, abs=1e-6)
    env.close()


def test_negative_soc_sentinels_remain_missing_values():
    values = ChargerSimulation.normalize_soc_series([-1.0, -0.1, np.nan, 0.0, 1.0, 80.0, 150.0])
    assert values.tolist() == pytest.approx([-0.1, -0.1, -0.1, 0.0, 1.0, 0.8, 1.0])
