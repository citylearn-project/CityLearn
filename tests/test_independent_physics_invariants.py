"""Independent runtime physics invariants (#277).

Verifies the four physical invariant families that do not rebuild net electricity from
the same component arrays as ``Building.update_variables()``:
1. Thermal device conversion: ``electricity * COP == thermal_to_load + storage_charge``
   for ``HeatPump`` and ``ElectricHeater``;
2. Served energy bounded by demand: ``0 <= served <= demand`` for cooling, heating,
   DHW, and ``non_shiftable_load``;
3. Battery depth-of-discharge reserve floor: ``soc >= min(1 - depth_of_discharge, pre_transfer_soc)``
   and ``soc >= 1 - depth_of_discharge`` whenever discharging;
4. Outage local-load bound: zero grid exchange, no unauthorized EV discharge, and
   battery + V2B discharge ``<= max(0, non_storage_loads - pv)`` with bounded PV curtailment.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.physics_invariants import PhysicsInvariantError

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "data" / "datasets"
MINUTE_EV_DEMO = ROOT / "tests" / "data" / "minute_ev_demo" / "schema.json"
PLUS_EVS = DATASETS / "citylearn_challenge_2022_phase_all_plus_evs" / "schema.json"
CHALLENGE_2021 = DATASETS / "citylearn_challenge_2021" / "schema.json"
CHALLENGE_2023_P1 = DATASETS / "citylearn_challenge_2023_phase_1" / "schema.json"
BAEDA_3DEM = DATASETS / "baeda_3dem" / "schema.json"
PARQUET_15S = DATASETS / "citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet" / "schema.json"


def _sample_deterministic_actions(env: CityLearnEnv, rng: np.random.Generator):
    if str(getattr(env, "interface", "flat")).lower() == "entity":
        return {
            "tables": {
                name: rng.uniform(space.low, space.high).astype(space.dtype)
                for name, space in env.action_space["tables"].spaces.items()
            }
        }
    return [rng.uniform(space.low, space.high).astype(space.dtype) for space in env.action_space]


def _apply_zero_building_actions(env: CityLearnEnv, building_index: int = 0):
    zero = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
    parsed = env._runtime_service.parse_actions(zero)
    building = env.buildings[building_index]
    if int(building.time_step) == 0:
        building.clear_step_electric_loads_for_action()
    building.apply_actions(**parsed[building_index])


def _assert_error_details(exc_info, *, check_name: str, building_name: str, step: int):
    msg = str(exc_info.value)
    assert check_name in msg
    assert building_name in msg
    assert f"t={step}" in msg
    assert "expected" in msg
    assert "actual=" in msg
    assert "residual=" in msg


# ---------------------------------------------------------------------------
# 1. Positive checks across datasets, time-step ratios, interfaces & outages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [3600, 900])
def test_positive_invariants_plus_evs_3600s_and_900s(seconds: int):
    kwargs = {"seconds_per_time_step": seconds}
    if seconds != 3600:
        kwargs["time_step_ratio_mode"] = "compress"

    env = CityLearnEnv(
        str(PLUS_EVS),
        central_agent=True,
        episode_time_steps=16,
        random_seed=0,
        physics_invariant_checks=True,
        offline=True,
        **kwargs,
    )
    try:
        env.reset(seed=0)
        rng = np.random.default_rng(11)
        while not env.terminated and not env.truncated:
            env.step(_sample_deterministic_actions(env, rng))
    finally:
        env.close()


@pytest.mark.parametrize("seconds", [3600, 900])
def test_positive_invariants_thermal_storage_heat_pump_and_electric_heater(seconds: int):
    kwargs = {"seconds_per_time_step": seconds}
    if seconds != 3600:
        kwargs["time_step_ratio_mode"] = "compress"

    env = CityLearnEnv(
        str(CHALLENGE_2021),
        buildings=[0, 1],
        central_agent=True,
        simulation_start_time_step=4000,
        simulation_end_time_step=4023,
        episode_time_steps=24,
        random_seed=0,
        physics_invariant_checks=True,
        offline=True,
        **kwargs,
    )
    try:
        env.reset(seed=0)
        rng = np.random.default_rng(22)
        while not env.terminated and not env.truncated:
            env.step(_sample_deterministic_actions(env, rng))
    finally:
        env.close()


@pytest.mark.parametrize(
    "schema_path,seconds",
    [
        (CHALLENGE_2023_P1, 3600),
        (CHALLENGE_2023_P1, 900),
        (BAEDA_3DEM, 3600),
    ],
)
def test_positive_invariants_dynamics_and_warmup_datasets(schema_path: Path, seconds: int):
    pytest.importorskip("torch")
    kwargs = {"seconds_per_time_step": seconds}
    if seconds != 3600:
        kwargs["time_step_ratio_mode"] = "compress"

    env = CityLearnEnv(
        str(schema_path),
        central_agent=True,
        episode_time_steps=16,
        random_seed=0,
        physics_invariant_checks=True,
        offline=True,
        **kwargs,
    )
    try:
        env.reset(seed=0)
        rng = np.random.default_rng(33)
        while not env.terminated and not env.truncated:
            env.step(_sample_deterministic_actions(env, rng))
    finally:
        env.close()


def test_positive_invariants_15s_parquet_dynamic_topology():
    pytest.importorskip("pyarrow")
    env = CityLearnEnv(
        str(PARQUET_15S),
        interface="entity",
        topology_mode="dynamic",
        central_agent=True,
        episode_time_steps=16,
        random_seed=0,
        physics_invariant_checks=True,
        offline=True,
    )
    try:
        env.reset(seed=0)
        rng = np.random.default_rng(44)
        while not env.terminated and not env.truncated:
            env.step(_sample_deterministic_actions(env, rng))
    finally:
        env.close()


@pytest.mark.parametrize("v2b", [False, True])
@pytest.mark.parametrize("outage_at_reset", [False, True])
def test_positive_invariants_power_outage_and_v2b(tmp_path: Path, v2b: bool, outage_at_reset: bool):
    dataset = tmp_path / f"minute_outage_{v2b}_{outage_at_reset}"
    shutil.copytree(MINUTE_EV_DEMO.parent, dataset)
    schema = json.loads((dataset / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset)

    b_csv = dataset / "Building_1.csv"
    df = pd.read_csv(b_csv)
    outage = np.zeros(len(df), dtype=int)
    if outage_at_reset:
        outage[:4] = 1
    else:
        outage[2:6] = 1
    df["power_outage"] = outage
    df.to_csv(b_csv, index=False)

    schema["buildings"]["Building_1"]["power_outage"] = {
        "simulate_power_outage": True,
        "stochastic_power_outage": False,
        "outage_vehicle_to_building": v2b,
    }
    schema["buildings"]["Building_1"]["pv"] = {
        "type": "citylearn.energy_model.PV",
        "autosize": False,
        "attributes": {"nominal_power": 3.0},
    }

    c_csv = dataset / "charger_1_1.csv"
    cdf = pd.read_csv(c_csv)
    cdf["electric_vehicle_charger_state"] = 1
    cdf["electric_vehicle_id"] = "Electric_Vehicle_1"
    cdf["electric_vehicle_departure_time"] = np.arange(len(cdf), 0, -1)
    cdf.to_csv(c_csv, index=False)

    env = CityLearnEnv(schema, central_agent=True, physics_invariant_checks=True, random_seed=0, offline=True)
    try:
        env.reset(seed=0)
        while not env.terminated and not env.truncated:
            # Command full battery and EV discharge during outage to exercise islanded load caps.
            action = np.full(env.action_space[0].shape, -1.0, dtype="float32")
            action = np.clip(action, env.action_space[0].low, env.action_space[0].high)
            env.step([action])
    finally:
        env.close()


def test_invariant_checks_do_not_alter_simulation_outputs():
    actions_seed = 99
    unchecked = CityLearnEnv(
        str(MINUTE_EV_DEMO), central_agent=True, physics_invariant_checks=False, random_seed=0, offline=True
    )
    checked = CityLearnEnv(
        str(MINUTE_EV_DEMO), central_agent=True, physics_invariant_checks=True, random_seed=0, offline=True
    )
    try:
        unchecked.reset(seed=0)
        checked.reset(seed=0)
        rng_a = np.random.default_rng(actions_seed)
        rng_b = np.random.default_rng(actions_seed)
        while not unchecked.terminated:
            obs_a, rew_a, term_a, trunc_a, _ = unchecked.step(_sample_deterministic_actions(unchecked, rng_a))
            obs_b, rew_b, term_b, trunc_b, _ = checked.step(_sample_deterministic_actions(checked, rng_b))
            np.testing.assert_array_equal(obs_a[0], obs_b[0])
            np.testing.assert_array_equal(rew_a, rew_b)
            assert (term_a, trunc_a) == (term_b, trunc_b)
        np.testing.assert_array_equal(unchecked.net_electricity_consumption, checked.net_electricity_consumption)
    finally:
        unchecked.close()
        checked.close()


# ---------------------------------------------------------------------------
# 2. Negative tests for each of the 4 independent physical invariant families
# ---------------------------------------------------------------------------


def test_issue_277_reproducer_non_shiftable_device_100kwh_caught_after_update_variables():
    """Exact #277 reproduction on minute_ev_demo: +100 kWh on non-shiftable device + update_variables()."""
    env = CityLearnEnv(
        str(MINUTE_EV_DEMO), central_agent=True, physics_invariant_checks=True, random_seed=0, offline=True
    )
    try:
        env.reset(seed=0)
        zero = [np.zeros(env.action_space[0].shape, dtype="float32")]
        env.step(zero)
        env.step(zero)

        building = env.buildings[0]
        t = int(building.time_step)
        assert float(building.energy_simulation.non_shiftable_load[t]) == pytest.approx(1.0)

        # Populate step t=2 normally, then inject +100 kWh on non_shiftable_load_device and call update_variables().
        _apply_zero_building_actions(env)
        building.non_shiftable_load_device.update_electricity_consumption(100.0)
        building.update_variables()

        assert float(building.net_electricity_consumption[t]) > 100.0
        # The legacy net-balance check passes because net was rebuilt from the corrupted component.
        env._physics_invariant_service._assert_building_energy_balance(building, t)

        with pytest.raises(PhysicsInvariantError, match="served_energy_bounds") as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(exc_info, check_name="served_energy_bounds", building_name=building.name, step=t)
    finally:
        env.close()


def test_issue_277_reproducer_both_served_series_and_device_100kwh_caught():
    """Even when both energy_to_non_shiftable_load and device consumption are set to 100 kWh, demand bounds catch it."""
    env = CityLearnEnv(
        str(MINUTE_EV_DEMO), central_agent=True, physics_invariant_checks=True, random_seed=0, offline=True
    )
    try:
        env.reset(seed=0)
        zero = [np.zeros(env.action_space[0].shape, dtype="float32")]
        env.step(zero)
        env.step(zero)

        building = env.buildings[0]
        t = int(building.time_step)
        _apply_zero_building_actions(env)
        building._Building__energy_to_non_shiftable_load[t] = 100.0
        building.non_shiftable_load_device.set_electricity_consumption(100.0, time_step=t)
        building.update_variables()

        env._physics_invariant_service._assert_building_energy_balance(building, t)

        with pytest.raises(PhysicsInvariantError, match="served_energy_bounds") as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(exc_info, check_name="served_energy_bounds", building_name=building.name, step=t)
    finally:
        env.close()


@pytest.mark.parametrize("seconds", [3600, 900])
@pytest.mark.parametrize("end_use", ["cooling", "dhw"])
def test_negative_thermal_device_cop_conversion_mismatch(seconds: int, end_use: str):
    """Family 1: HeatPump (cooling) and ElectricHeater (dhw) electricity * COP != thermal_to_load + storage_charge."""
    kwargs = {"seconds_per_time_step": seconds}
    if seconds != 3600:
        kwargs["time_step_ratio_mode"] = "compress"

    env = CityLearnEnv(
        str(CHALLENGE_2021),
        buildings=[0],
        central_agent=True,
        simulation_start_time_step=4000,
        simulation_end_time_step=4005,
        episode_time_steps=6,
        random_seed=0,
        physics_invariant_checks=True,
        offline=True,
        **kwargs,
    )
    try:
        env.reset(seed=0)
        env.step([np.array([0.1, 0.1, 0.0], dtype="float32")])
        building = env.buildings[0]
        t = int(building.time_step)
        _apply_zero_building_actions(env)
        device = getattr(building, f"{end_use}_device")
        device.update_electricity_consumption(2.5)
        building.update_variables()

        # Net balance passes because update_variables() summed the inflated device consumption.
        env._physics_invariant_service._assert_building_energy_balance(building, t)

        with pytest.raises(PhysicsInvariantError, match="thermal_device_energy_conversion") as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(
            exc_info, check_name="thermal_device_energy_conversion", building_name=building.name, step=t
        )
    finally:
        env.close()


def test_negative_thermal_storage_charge_mismatch_with_device_cop():
    """Family 1: thermal storage_charge corrupted without matching device electricity * COP raises."""
    env = CityLearnEnv(
        str(CHALLENGE_2021),
        buildings=[0],
        central_agent=True,
        simulation_start_time_step=4000,
        simulation_end_time_step=4005,
        episode_time_steps=6,
        random_seed=0,
        physics_invariant_checks=True,
        offline=True,
    )
    try:
        env.reset(seed=0)
        env.step([np.zeros(env.action_space[0].shape, dtype="float32")])
        building = env.buildings[0]
        t = int(building.time_step)
        _apply_zero_building_actions(env)
        building.cooling_storage._StorageDevice__energy_balance[t] = 5.0
        building.update_variables()

        env._physics_invariant_service._assert_building_energy_balance(building, t)

        with pytest.raises(PhysicsInvariantError, match="thermal_device_energy_conversion") as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(
            exc_info, check_name="thermal_device_energy_conversion", building_name=building.name, step=t
        )
    finally:
        env.close()


def test_negative_thermal_served_exceeds_demand_even_when_cop_matches():
    """Family 2: thermal served > demand raises even if electricity * COP == served and net balance holds."""
    env = CityLearnEnv(
        str(CHALLENGE_2021),
        buildings=[0],
        central_agent=True,
        simulation_start_time_step=4000,
        simulation_end_time_step=4005,
        episode_time_steps=6,
        random_seed=0,
        physics_invariant_checks=True,
        offline=True,
    )
    try:
        env.reset(seed=0)
        env.step([np.zeros(env.action_space[0].shape, dtype="float32")])
        building = env.buildings[0]
        t = int(building.time_step)
        _apply_zero_building_actions(env)

        inflated_output = float(building.cooling_demand[t]) + 10.0
        temp = float(building.weather.outdoor_dry_bulb_temperature[t])
        building._Building__energy_from_cooling_device[t] = inflated_output
        building.cooling_device.set_electricity_consumption(
            building.cooling_device.get_input_power(inflated_output, temp, heating=False),
            time_step=t,
        )
        building.update_variables()

        # Both net balance AND thermal COP conversion hold, so ONLY served <= demand catches this!
        env._physics_invariant_service._assert_building_energy_balance(building, t)
        env._physics_invariant_service._assert_thermal_device_energy_conversion(building, t)

        with pytest.raises(PhysicsInvariantError, match="served_energy_bounds") as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(exc_info, check_name="served_energy_bounds", building_name=building.name, step=t)
    finally:
        env.close()


@pytest.mark.parametrize("target", ["stationary", "ev"])
def test_negative_battery_soc_below_depth_of_discharge_floor(tmp_path: Path, target: str):
    """Family 3: stationary and connected EV batteries violating 1 - depth_of_discharge raise PhysicsInvariantError."""
    dataset = tmp_path / f"dod_{target}"
    shutil.copytree(MINUTE_EV_DEMO.parent, dataset)
    schema = json.loads((dataset / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset)
    schema["buildings"]["Building_1"]["electrical_storage"]["attributes"]["depth_of_discharge"] = 0.8
    schema["buildings"]["Building_1"]["electrical_storage"]["attributes"]["initial_soc"] = 0.5
    schema["electric_vehicles_def"]["Electric_Vehicle_1"]["battery"]["attributes"]["depth_of_discharge"] = 0.8
    schema["electric_vehicles_def"]["Electric_Vehicle_1"]["battery"]["attributes"]["initial_soc"] = 0.5

    c_csv = dataset / "charger_1_1.csv"
    cdf = pd.read_csv(c_csv)
    cdf["electric_vehicle_charger_state"] = 1
    cdf["electric_vehicle_id"] = "Electric_Vehicle_1"
    cdf["electric_vehicle_current_soc"] = 0.5
    cdf.to_csv(c_csv, index=False)

    env = CityLearnEnv(schema, central_agent=True, physics_invariant_checks=True, random_seed=0, offline=True)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        t = int(env.time_step)

        if target == "stationary":
            battery = building.electrical_storage
        else:
            battery = building.electric_vehicle_chargers[0].connected_electric_vehicle.battery

        # Reserve floor is 1 - 0.8 = 0.2; set SOC to 0.15 (still inside [0, 1], so _assert_soc_bounds passes).
        battery._StorageDevice__soc[t] = 0.15
        env._physics_invariant_service._assert_soc_bounds(building, t)

        with pytest.raises(PhysicsInvariantError, match="battery_dod_floor") as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(exc_info, check_name="battery_dod_floor", building_name=building.name, step=t)
    finally:
        env.close()


def test_negative_battery_discharge_from_low_arrival_soc_raises(tmp_path: Path):
    """Family 3: a battery starting below 1 - DoD may hold/charge, but discharging further raises."""
    dataset = tmp_path / "dod_low_arrival_discharge"
    shutil.copytree(MINUTE_EV_DEMO.parent, dataset)
    schema = json.loads((dataset / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset)
    schema["buildings"]["Building_1"]["electrical_storage"]["attributes"]["depth_of_discharge"] = 0.8
    schema["buildings"]["Building_1"]["electrical_storage"]["attributes"]["initial_soc"] = 0.15

    env = CityLearnEnv(schema, central_agent=True, physics_invariant_checks=True, random_seed=0, offline=True)
    try:
        # Reset at initial_soc=0.15 (< 0.20 reserve) passes because no discharge happened.
        env.reset(seed=0)
        building = env.buildings[0]
        t = int(env.time_step)
        building.electrical_storage._StorageDevice__energy_balance[t] = -0.25

        with pytest.raises(PhysicsInvariantError, match="battery_dod_floor") as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(exc_info, check_name="battery_dod_floor", building_name=building.name, step=t)
    finally:
        env.close()


@pytest.mark.parametrize(
    "mode",
    ["battery_over_discharge", "v2b_over_discharge", "unauthorized_ev_discharge", "grid_spill"],
)
def test_negative_outage_local_load_and_grid_bounds(tmp_path: Path, mode: str):
    """Family 4: outage battery/V2B over-discharge, unauthorized EV discharge, and failed-grid spill raise."""
    dataset = tmp_path / f"outage_neg_{mode}"
    shutil.copytree(MINUTE_EV_DEMO.parent, dataset)
    schema = json.loads((dataset / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset)

    b_csv = dataset / "Building_1.csv"
    df = pd.read_csv(b_csv)
    df["power_outage"] = 1
    df.to_csv(b_csv, index=False)

    schema["buildings"]["Building_1"]["power_outage"] = {
        "simulate_power_outage": True,
        "stochastic_power_outage": False,
        "outage_vehicle_to_building": mode == "v2b_over_discharge",
    }
    c_csv = dataset / "charger_1_1.csv"
    cdf = pd.read_csv(c_csv)
    cdf["electric_vehicle_charger_state"] = 1
    cdf["electric_vehicle_id"] = "Electric_Vehicle_1"
    cdf["electric_vehicle_departure_time"] = np.arange(len(cdf), 0, -1)
    cdf.to_csv(c_csv, index=False)

    env = CityLearnEnv(schema, central_agent=True, physics_invariant_checks=True, random_seed=0, offline=True)
    try:
        env.reset(seed=0)
        env.step([np.zeros(env.action_space[0].shape, dtype="float32")])

        building = env.buildings[0]
        t = int(building.time_step)
        _apply_zero_building_actions(env)

        if mode == "battery_over_discharge":
            # Over-discharge battery beyond local load; update_variables() keeps net=0 and books PV curtailment.
            building.electrical_storage.set_electricity_consumption(-1.2, time_step=t, enforce_polarity=False)
            building.update_variables()
            assert float(building.net_electricity_consumption[t]) == pytest.approx(0.0)
            expected_check = "outage_local_load_bound"
        elif mode == "v2b_over_discharge":
            charger = building.electric_vehicle_chargers[0]
            charger._Charger__electricity_consumption[t] = -1.5
            building.update_variables()
            assert float(building.net_electricity_consumption[t]) == pytest.approx(0.0)
            expected_check = "outage_local_load_bound"
        elif mode == "unauthorized_ev_discharge":
            charger = building.electric_vehicle_chargers[0]
            charger._Charger__electricity_consumption[t] = -0.5
            building.update_variables()
            expected_check = "outage_local_load_bound"
        else:
            building.update_variables()
            building._Building__net_electricity_consumption[t] = -1.5
            expected_check = "outage_grid_exchange"

        with pytest.raises(PhysicsInvariantError, match=expected_check) as exc_info:
            env._physics_invariant_service.assert_step_invariants(t)
        _assert_error_details(exc_info, check_name=expected_check, building_name=building.name, step=t)
    finally:
        env.close()
