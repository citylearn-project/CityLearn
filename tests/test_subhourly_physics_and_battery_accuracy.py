from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import citylearn.occupant as occupant_module
from citylearn.citylearn import CityLearnEnv
from citylearn.community_dataset import InventoryBattery
from citylearn.data import CarbonIntensity, DataSet, EnergySimulation, LogisticRegressionOccupantParameters, Weather
from citylearn.energy_model import Battery, Escalator, EscalatorSimulation
from citylearn.internal.balance_audit import IndependentBalanceAudit
from citylearn.occupant import LogisticRegressionOccupant
from test_deferrable_appliance_integration import _zero_entity_payload
from test_robustness import _clean_schema, _copy_schema, _event, _write_events


MINUTE_DATASET = Path(__file__).resolve().parent / "data/minute_ev_demo"
HOURLY_2021_SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/citylearn_challenge_2021/schema.json"


class _FixedClassifier:
    def __init__(self, value: int):
        self.value = value

    def predict(self, x):
        return [self.value]


@pytest.mark.parametrize("seconds_per_time_step", [900, 60])
def test_subhourly_thermal_storage_charging_respects_device_nominal_power(seconds_per_time_step: int):
    env = CityLearnEnv(
        str(HOURLY_2021_SCHEMA),
        central_agent=True,
        episode_time_steps=6,
        seconds_per_time_step=seconds_per_time_step,
        simulation_start_time_step=4000,
        random_seed=0,
    )
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        names = env.action_names[0]
        actions = np.zeros(len(names), dtype="float32")
        for idx, name in enumerate(names):
            if "cooling_storage" in name or "dhw_storage" in name:
                actions[idx] = 1.0

        step_hours = seconds_per_time_step / 3600.0
        for _ in range(4):
            t = building.time_step
            env.step([actions])
            assert building.cooling_device.electricity_consumption[t] <= (
                building.cooling_device.nominal_power * step_hours + 1.0e-5
            )
            assert building.dhw_device.electricity_consumption[t] <= (
                building.dhw_device.nominal_power * step_hours + 1.0e-5
            )
            assert 0.0 <= building.cooling_device.available_nominal_power <= building.cooling_device.nominal_power + 1.0e-6
    finally:
        env.close()


def test_subhourly_outage_curtailment_uses_full_control_step_supply(tmp_path: Path):
    dataset_dir = tmp_path / "outage_subhourly"
    shutil.copytree(MINUTE_DATASET, dataset_dir)
    building_csv = dataset_dir / "Building_1.csv"
    df = pd.read_csv(building_csv)
    # Remove `minutes` so dataset resolution is 1 hour (3600s) while control step is 900s (`time_step_ratio = 0.25`).
    if "minutes" in df.columns:
        df = df.drop(columns=["minutes"])
    df["hour"] = np.arange(len(df)) % 24
    df["power_outage"] = 1
    df["non_shiftable_load"] = 4.0  # 4.0 kWh/dataset_hour == 1.0 kWh per 15-min control step
    df["solar_generation"] = 1.0  # absolute mode: 1.0 kWh/dataset_hour * 0.25 == 0.25 kWh unless scaled; set 4.0 -> 1.0 kWh/step
    df["solar_generation"] = 4.0
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df.to_csv(building_csv, index=False)

    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["seconds_per_time_step"] = 900
    schema.pop("dataset_seconds_per_time_step", None)
    schema["buildings"]["Building_1"]["power_outage"] = {"simulate_power_outage": True}
    schema["buildings"]["Building_1"]["chargers"] = {}
    schema["buildings"]["Building_1"]["pv"] = {
        "type": "citylearn.energy_model.PV",
        "autosize": False,
        "attributes": {"generation_mode": "absolute", "nominal_power": 20.0},
    }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, seconds_per_time_step=900, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        assert building.time_step_ratio == pytest.approx(0.25)
        env.step([np.zeros(env.action_space[0].shape, dtype="float32")])
        # 1.0 kWh PV in 15 min must serve the full 1.0 kWh control-step load (not 0.25 kWh).
        assert building.non_shiftable_load_device.electricity_consumption[0] == pytest.approx(1.0, abs=1.0e-6)
        assert building.net_electricity_consumption[0] == pytest.approx(0.0, abs=1.0e-6)
    finally:
        env.close()


def test_subhourly_thermal_demand_observation_converts_storage_discharge_consistently():
    schema = DataSet().get_schema("citylearn_challenge_2023_phase_2_local_evaluation")
    schema["seconds_per_time_step"] = 900.0
    names = list(schema["buildings"])
    for name, bldg in schema["buildings"].items():
        bldg["type"] = "citylearn.building.Building"
        bldg.pop("dynamics", None)
        bldg["power_outage"] = {"simulate_power_outage": False}
        bldg["dhw_storage"]["attributes"]["initial_soc"] = 0.8
        bldg["include"] = name == names[0]

    env = CityLearnEnv(schema, central_agent=False, simulation_start_time_step=0, simulation_end_time_step=12)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        dhw_ix = env.action_names[0].index("dhw_storage")
        discharged_any = False
        for _ in range(8):
            t = building.time_step
            cmd = [0.0] * len(env.action_names[0])
            cmd[dhw_ix] = -1.0
            env.step([cmd])
            if building.dhw_storage.energy_balance[t] < -1.0e-6:
                discharged_any = True
                obs_At_t = building._ops_service.get_observations_data(include_all=True, observation_names=["dhw_demand"])
                # Need next-step or current-step check: at `env.step`, `building.time_step` has advanced to `t + 1`,
                # so agent observation (`include_all=False`) reads `endogenous_t = t`.
                agent_obs = building.observations(normalize=False, periodic_normalization=False)
                if "dhw_demand" in agent_obs:
                    assert agent_obs["dhw_demand"] == pytest.approx(float(building.energy_simulation.dhw_demand[t]), rel=1.0e-5, abs=1.0e-5)
                else:
                    settled = building.energy_from_dhw_device[t] + abs(min(building.dhw_storage.energy_balance[t], 0.0)) / building.time_step_ratio
                    assert settled == pytest.approx(float(building.energy_simulation.dhw_demand[t]), rel=1.0e-5, abs=1.0e-5)
                assert obs_At_t is not None
        assert discharged_any
    finally:
        env.close()


def test_battery_cc_cv_discharge_curve_and_degraded_capacity_taper():
    curve = [[0.0, 1.0], [0.8, 1.0], [1.0, 0.2]]
    battery = Battery(
        capacity=10.0,
        nominal_power=5.0,
        initial_soc=1.0,
        efficiency=0.9,
        loss_coefficient=0.0,
        capacity_loss_coefficient=0.0,
        capacity_power_curve=curve,
        power_efficiency_curve=[[0.0, 0.9], [1.0, 0.9]],
    )
    # Full battery (SoC = 1.0): CV tapers charging to 20%, while discharging gets 100% CC power.
    assert battery.get_max_input_power(energy_init=10.0) == pytest.approx(1.0)
    assert battery.get_max_output_power(energy_init=10.0) == pytest.approx(5.0)

    # Near-empty battery (SoC = 0.0): charging gets 100% CC power, while discharging tapers to 20%.
    assert battery.get_max_input_power(energy_init=0.0) == pytest.approx(5.0)
    assert battery.get_max_output_power(energy_init=0.0) == pytest.approx(1.0)

    # Degraded battery (capacity faded from 10.0 to 8.0 kWh): 8.0 kWh is now 100% degraded SoC.
    battery._capacity_history[-1] = 8.0
    assert battery.degraded_capacity == pytest.approx(8.0)
    assert battery.get_max_input_power(energy_init=8.0) == pytest.approx(1.0)
    assert battery.get_max_output_power(energy_init=8.0) == pytest.approx(5.0)

    inv = InventoryBattery(
        capacity=10.0,
        max_charge_kw=4.0,
        max_discharge_kw=4.0,
        min_soc=0.0,
        max_soc=1.0,
        initial_soc=1.0,
        charging_efficiency=0.95,
        discharging_efficiency=0.95,
        capacity_power_curve=curve,
    )
    assert inv.get_max_output_power(energy_init=10.0) == pytest.approx(4.0)
    assert inv.get_max_output_power(energy_init=0.0) == pytest.approx(0.8)


def test_outage_v2g_serves_islanded_load_and_passes_independent_balance_audit(tmp_path: Path):
    dataset_dir = tmp_path / "outage_v2g"
    shutil.copytree(MINUTE_DATASET, dataset_dir)
    building_csv = dataset_dir / "Building_1.csv"
    df = pd.read_csv(building_csv)
    df["power_outage"] = 1
    df["solar_generation"] = 0.0
    df["non_shiftable_load"] = 0.5  # 0.5 kWh per 15-min step == 2.0 kW islanded load
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df.to_csv(building_csv, index=False)

    charger_csv = dataset_dir / "charger_1_1.csv"
    cdf = pd.read_csv(charger_csv)
    cdf["electric_vehicle_charger_state"] = 1
    cdf["electric_vehicle_id"] = "Electric_Vehicle_1"
    cdf["electric_vehicle_departure_time"] = 4
    cdf["electric_vehicle_required_soc_departure"] = 0.5
    cdf.to_csv(charger_csv, index=False)

    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["interface"] = "entity"
    schema["physics_invariant_checks"] = True
    schema["buildings"]["Building_1"]["power_outage"] = {"simulate_power_outage": True}
    schema["buildings"]["Building_1"]["electrical_storage"]["attributes"]["initial_soc"] = 0.0
    charger_attrs = schema["buildings"]["Building_1"]["chargers"]["charger_1_1"]["attributes"]
    charger_attrs["max_discharging_power"] = 7.2
    charger_attrs["min_discharging_power"] = 0.0
    ev_battery = schema["electric_vehicles_def"]["Electric_Vehicle_1"]["battery"]["attributes"]
    ev_battery["initial_soc"] = 0.8
    ev_battery["depth_of_discharge"] = 1.0
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env = CityLearnEnv(str(schema_path), episode_time_steps=4, random_seed=0, export_kpis_on_episode_end=False)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        charger = building.electric_vehicle_chargers[0]
        with IndependentBalanceAudit(env) as audit:
            for step_ix in range(3):
                payload = _zero_entity_payload(env)
                payload["tables"]["charger"][0, 0] = -1.0  # request -7.2 kW V2G; must clamp to -2.0 kW (-0.5 kWh)
                env.step(payload)
                assert charger.electricity_consumption[step_ix] == pytest.approx(-0.5, abs=1.0e-5)
                assert building.non_shiftable_load_device.electricity_consumption[step_ix] == pytest.approx(0.5, abs=1.0e-5)
                assert building.net_electricity_consumption[step_ix] == pytest.approx(0.0, abs=1.0e-5)
            report = audit.finish()
        assert report["status"] == "pass"
    finally:
        env.close()


def test_thermal_discharge_not_double_subtracted_and_escalator_reduces_service_headroom(tmp_path: Path):
    schema = DataSet().get_schema("citylearn_challenge_2021")
    names = list(schema["buildings"])
    for name in names[1:]:
        schema["buildings"][name]["include"] = False
    first = schema["buildings"][names[0]]
    first["cooling_storage"]["attributes"]["initial_soc"] = 0.8
    env = CityLearnEnv(schema, central_agent=True, simulation_start_time_step=4000, simulation_end_time_step=4006, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        action_names = env.action_names[0]
        cmd = np.zeros(len(action_names), dtype="float32")
        cmd[action_names.index("cooling_storage")] = -1.0
        t = building.time_step
        env.step([cmd])
        assert building.cooling_storage.energy_balance[t] < -1.0e-6
        expected_cooling_kw = float(building.cooling_device.electricity_consumption[t])
        non_shift_kw = float(building.non_shiftable_load_device.electricity_consumption[t])
        dhw_kw = float(building.dhw_device.electricity_consumption[t])
        heating_kw = float(building.heating_device.electricity_consumption[t])
        solar_kw = float(building.solar_generation[t])
        est_kw, _ = building._ops_service._estimate_base_power_at_step(t)
        assert est_kw == pytest.approx(expected_cooling_kw + heating_kw + dhw_kw + non_shift_kw + solar_kw, abs=1.0e-5)
    finally:
        env.close()

    # Verify active escalator load is counted in electrical_service EV headroom.
    dataset_dir = tmp_path / "escalator_service"
    shutil.copytree(MINUTE_DATASET, dataset_dir)
    df = pd.read_csv(dataset_dir / "Building_1.csv")
    df["non_shiftable_load"] = 0.0
    df["solar_generation"] = 0.0
    df["cooling_demand"] = 0.0
    df["heating_demand"] = 0.0
    df["dhw_demand"] = 0.0
    df.to_csv(dataset_dir / "Building_1.csv", index=False)
    c_df = pd.read_csv(dataset_dir / "charger_1_1.csv")
    c_df["electric_vehicle_charger_state"] = 1
    c_df.to_csv(dataset_dir / "charger_1_1.csv", index=False)

    schema_path = dataset_dir / "schema.json"
    s2 = json.loads(schema_path.read_text(encoding="utf-8"))
    s2["root_directory"] = str(dataset_dir)
    s2["actions"]["escalator"] = {"active": True}
    s2["buildings"]["Building_1"]["electrical_service"] = {
        "mode": "single_phase",
        "limits": {"total": {"import_kw": 6.0, "export_kw": 10.0}},
        "observations": {"headroom": True, "violation": True},
    }
    schema_path.write_text(json.dumps(s2, indent=2), encoding="utf-8")

    env2 = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        b2 = env2.buildings[0]
        sim = EscalatorSimulation.from_dataframe(
            pd.DataFrame(
                {
                    "time_step": list(range(8)),
                    "passengers_from_trains_15min": [10.0] * 8,
                    "background_pedestrians_15min": [2.0] * 8,
                    "passengers_expected_15min": [12.0] * 8,
                    "people_detected": [1.0] * 8,
                    "arriving_trains": [1.0] * 8,
                    "departing_trains": [0.0] * 8,
                    "minutes_to_next_train": [5.0] * 8,
                    "available": [1.0] * 8,
                }
            )
        )
        esc = Escalator(
            escalator_simulation=sim,
            name="esc_1",
            standby_power=0.5,
            slow_power=2.0,
            normal_power=4.0,
            seconds_per_time_step=env2.seconds_per_time_step,
            episode_tracker=b2.episode_tracker,
        )
        b2.escalators = [esc]
        b2.action_metadata["escalator_esc_1"] = True
        b2._ops_service._apply_action_cache = None
        env2.reset(seed=0)
        esc.reset()

        # Request 4.0 kW normal escalator + 7.2 kW EV charge under 6.0 kW total import limit -> EV must be clipped to <= 2.0 kW.
        b2.apply_actions(
            escalator_actions={"escalator_esc_1": 1.0},
            electric_vehicle_storage_actions={"charger_1_1": 1.0},
        )
        b2.update_variables()
        charger_kw = float(b2.electric_vehicle_chargers[0].electricity_consumption[0]) / (env2.seconds_per_time_step / 3600.0)
        assert charger_kw <= 2.0 + 1.0e-5
    finally:
        env2.close()


def test_non_periodic_normalization_and_phase_specific_clip_reasons(tmp_path: Path):
    env = CityLearnEnv(
        "citylearn_challenge_2023_phase_2_local_evaluation",
        central_agent=False,
        simulation_start_time_step=0,
        simulation_end_time_step=6,
    )
    try:
        env.reset(seed=0)
        obs = env.buildings[0].observations(normalize=True, periodic_normalization=False)
        assert "hour" in obs
        assert all(0.0 - 1.0e-6 <= float(v) <= 1.0 + 1.0e-6 for v in obs.values())
    finally:
        env.close()

    dataset_dir = tmp_path / "three_phase_reasons"
    shutil.copytree(MINUTE_DATASET, dataset_dir)
    df = pd.read_csv(dataset_dir / "Building_1.csv")
    df["non_shiftable_load"] = 0.0
    df["solar_generation"] = 0.0
    df.to_csv(dataset_dir / "Building_1.csv", index=False)

    c1 = pd.read_csv(dataset_dir / "charger_1_1.csv")
    c1["electric_vehicle_charger_state"] = 1
    c1.to_csv(dataset_dir / "charger_1_1.csv", index=False)
    shutil.copy(dataset_dir / "charger_1_1.csv", dataset_dir / "charger_1_2.csv")

    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["interface"] = "entity"
    schema["observation_bundles"] = {"entity_action_feedback": {"active": True}}
    schema["electric_vehicles_def"]["Electric_Vehicle_2"] = json.loads(
        json.dumps(schema["electric_vehicles_def"]["Electric_Vehicle_1"])
    )
    c2_df = pd.read_csv(dataset_dir / "charger_1_2.csv")
    c2_df["electric_vehicle_id"] = "Electric_Vehicle_2"
    c2_df.to_csv(dataset_dir / "charger_1_2.csv", index=False)

    b1 = schema["buildings"]["Building_1"]
    b1["chargers"]["charger_1_1"]["attributes"]["phase_connection"] = "L1"
    b1["chargers"]["charger_1_2"] = json.loads(json.dumps(b1["chargers"]["charger_1_1"]))
    b1["chargers"]["charger_1_2"]["charger_simulation"] = "charger_1_2.csv"
    b1["chargers"]["charger_1_2"]["attributes"]["phase_connection"] = "L2"
    b1["electrical_service"] = {
        "mode": "three_phase",
        "default_split": "balanced",
        "limits": {
            "total": {"import_kw": 4.0, "export_kw": 10.0},
            "per_phase": {
                "L1": {"import_kw": 2.0, "export_kw": 5.0},
                "L2": {"import_kw": 10.0, "export_kw": 5.0},
                "L3": {"import_kw": 10.0, "export_kw": 5.0},
            },
        },
        "observations": {"headroom": True, "violation": True},
    }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    env2 = CityLearnEnv(str(schema_path), episode_time_steps=4, random_seed=0, export_kpis_on_episode_end=False)
    try:
        env2.reset(seed=0)
        payload = _zero_entity_payload(env2)
        payload["tables"]["charger"][:, 0] = 1.0  # L1 hits 2.0 kW phase limit; L2 hits 4.0 kW total limit (2.0 kW < 10.0 kW L2 limit)
        obs, *_ = env2.step(payload)
        feats = env2.entity_specs["tables"]["charger"]["features"]
        ids = env2.entity_specs["tables"]["charger"]["ids"]
        row_l1 = ids.index("Building_1/charger_1_1")
        row_l2 = ids.index("Building_1/charger_1_2")
        assert obs["tables"]["charger"][row_l1, feats.index("clip_reason_phase_headroom")] == pytest.approx(1.0)
        assert obs["tables"]["charger"][row_l2, feats.index("clip_reason_building_headroom")] == pytest.approx(1.0)
        assert obs["tables"]["charger"][row_l2, feats.index("clip_reason_phase_headroom")] == pytest.approx(0.0)
        assert obs["tables"]["charger"][row_l2, feats.index("clip_reason_export_headroom")] == pytest.approx(0.0)
    finally:
        env2.close()


def test_hidden_faults_preserves_demand_response_meta_and_multi_cycle_deadline_missed(tmp_path: Path):
    schema = _copy_schema(tmp_path / "dr_hidden", interface="entity", enabled=True)
    _write_events(
        schema,
        [_event(event_id="secret-fault", target_feature="non_shiftable_load", value=0.1, mode="bias", start=0, end=2)],
    )
    pd.DataFrame(
        [
            {
                "request_id": "dr_1",
                "issuer": "dso",
                "direction": "down",
                "start_time_step": 1,
                "end_time_step": 2,
                "target_power_kw": 1.0,
                "activation_price_eur_per_kwh": 2.0,
                "shortfall_penalty_eur_per_kwh": 5.0,
                "tolerance_power_kw": 0.0,
            }
        ]
    ).to_csv(Path(schema["_dataset_dir"]) / "demand_response_requests.csv", index=False)
    schema["demand_response"] = {
        "enabled": True,
        "requests_file": "demand_response_requests.csv",
        "baseline_method": "rolling_pre_event_average",
        "baseline_window_seconds": 3600,
        "allow_overlapping_requests": False,
    }
    schema["robustness"]["agent_observation_contract"] = {
        "mode": "hidden_faults",
        "features": {"building": ["non_shiftable_load"]},
    }
    env = CityLearnEnv(_clean_schema(schema), episode_time_steps=4, random_seed=0, export_kpis_on_episode_end=False)
    try:
        obs, _ = env.reset(seed=0)
        assert "demand_response" in obs["meta"]
        assert "robustness" not in obs["meta"]
        assert "runtime_status" not in obs["meta"]
    finally:
        env.close()

    # Multi-cycle deferrable appliance: missing cycle_1 must keep deadline_missed == 1.0 while cycle_2 is pending.
    dataset_dir = tmp_path / "multi_cycle_def"
    shutil.copytree(MINUTE_DATASET, dataset_dir)
    pd.DataFrame(
        [{"profile_id": "normal", "duration_steps": 1, "total_energy_kwh": 0.2, "load_profile": "[0.2]"}]
    ).to_csv(dataset_dir / "washer_profiles.csv", index=False)
    pd.DataFrame(
        [
            {
                "cycle_id": "cycle_1",
                "profile_id": "normal",
                "earliest_start_time_step": 0,
                "latest_start_time_step": 0,
                "deadline_time_step": 0,
                "priority": 1.0,
                "must_run": True,
            },
            {
                "cycle_id": "cycle_2",
                "profile_id": "normal",
                "earliest_start_time_step": 2,
                "latest_start_time_step": 3,
                "deadline_time_step": 3,
                "priority": 1.0,
                "must_run": True,
            },
        ]
    ).to_csv(dataset_dir / "washer_schedule.csv", index=False)

    s_path = dataset_dir / "schema.json"
    s = json.loads(s_path.read_text(encoding="utf-8"))
    s["root_directory"] = str(dataset_dir)
    s["interface"] = "entity"
    s["actions"]["deferrable_appliance"] = {"active": True}
    s["buildings"]["Building_1"]["deferrable_appliances"] = {
        "washer_1": {
            "type": "citylearn.energy_model.DeferrableAppliance",
            "cycle_profiles_file": "washer_profiles.csv",
            "flexibility_schedule_file": "washer_schedule.csv",
        }
    }
    s_path.write_text(json.dumps(s, indent=2), encoding="utf-8")

    env_def = CityLearnEnv(str(s_path), episode_time_steps=5, random_seed=0, export_kpis_on_episode_end=False)
    try:
        env_def.reset(seed=0)
        obs_after_miss, *_ = env_def.step(_zero_entity_payload(env_def))  # step 0 -> 1: cycle_1 missed, cycle_2 still pending!
        feats = env_def.entity_specs["tables"]["deferrable_appliance"]["features"]
        row = obs_after_miss["tables"]["deferrable_appliance"][0]
        assert row[feats.index("pending")] == pytest.approx(1.0)
        assert row[feats.index("deadline_missed")] == pytest.approx(1.0)
    finally:
        env_def.close()


def test_gaussian_noise_physical_polarity_and_occupant_auto_mode_and_hold_window(monkeypatch):
    n = 64
    es = EnergySimulation(
        month=[1] * n,
        hour=[(i % 24) + 1 for i in range(n)],
        day_type=[1] * n,
        indoor_dry_bulb_temperature=[22.0] * n,
        non_shiftable_load=[1.0] * n,
        dhw_demand=[0.0] * n,
        cooling_demand=[0.0] * n,
        heating_demand=[0.0] * n,
        solar_generation=[0.0 if i < 32 else 0.5 for i in range(n)],
        indoor_relative_humidity=[50.0] * n,
        noise_std=10.0,
        noise_seed=42,
    )
    assert np.all(es.solar_generation[:32] == 0.0)
    assert np.all(es.solar_generation >= 0.0)

    weather = Weather(
        outdoor_dry_bulb_temperature=[20.0] * n,
        outdoor_relative_humidity=[95.0] * n,
        diffuse_solar_irradiance=[0.0 if i < 32 else 1.0 for i in range(n)],
        direct_solar_irradiance=[0.0 if i < 32 else 1.0 for i in range(n)],
        outdoor_dry_bulb_temperature_predicted_1=[20.0] * n,
        outdoor_dry_bulb_temperature_predicted_2=[20.0] * n,
        outdoor_dry_bulb_temperature_predicted_3=[20.0] * n,
        outdoor_relative_humidity_predicted_1=[5.0] * n,
        outdoor_relative_humidity_predicted_2=[95.0] * n,
        outdoor_relative_humidity_predicted_3=[50.0] * n,
        diffuse_solar_irradiance_predicted_1=[0.0] * n,
        diffuse_solar_irradiance_predicted_2=[1.0] * n,
        diffuse_solar_irradiance_predicted_3=[0.0] * n,
        direct_solar_irradiance_predicted_1=[0.0] * n,
        direct_solar_irradiance_predicted_2=[1.0] * n,
        direct_solar_irradiance_predicted_3=[0.0] * n,
        noise_std=25.0,
        noise_seed=42,
    )
    assert np.all((weather.outdoor_relative_humidity >= 0.0) & (weather.outdoor_relative_humidity <= 100.0))
    assert np.all((weather.outdoor_relative_humidity_predicted_1 >= 0.0) & (weather.outdoor_relative_humidity_predicted_1 <= 100.0))
    assert np.all(weather.diffuse_solar_irradiance[:32] == 0.0)
    assert np.all(weather.direct_solar_irradiance[:32] == 0.0)
    assert np.all(weather.diffuse_solar_irradiance >= 0.0)
    assert np.all(weather.direct_solar_irradiance >= 0.0)
    assert np.all(weather.diffuse_solar_irradiance_predicted_1 == 0.0)
    assert np.all(weather.diffuse_solar_irradiance_predicted_2 >= 0.0)

    ci = CarbonIntensity([0.1] * n, noise_std=5.0, noise_seed=42)
    assert np.all(ci.carbon_intensity >= 0.0)

    # Occupant tie-resolution: high increase & decrease probabilities must not mutually cancel to 0.0.
    monkeypatch.setattr(
        occupant_module,
        "load_occupant_model",
        lambda path: _FixedClassifier(1),
    )
    params = LogisticRegressionOccupantParameters(
        a_increase=[10.0] * 10,
        b_increase=[0.0] * 10,
        a_decrease=[10.0] * 10,
        b_decrease=[0.0] * 10,
    )
    from citylearn.base import EpisodeTracker

    tracker = EpisodeTracker(0, 9)
    tracker.next_episode(10, False, False, 0)
    occ = LogisticRegressionOccupant(
        setpoint_increase_model_filepath="dummy_inc.pkl",
        setpoint_decrease_model_filepath="dummy_dec.pkl",
        delta_output_map={1: 1.5},
        parameters=params,
        episode_tracker=tracker,
        random_seed=7,
    )
    occ.reset()
    delta = occ.predict((24.0, [[22.0, 22.0, 2.0]]))
    assert abs(delta) == pytest.approx(1.5)

    # Occupant auto HVAC mode (`hvac_mode == 3`) and bounded hold slice preserving future schedule.
    schema = DataSet().get_schema("quebec_neighborhood_without_demand_response_set_points")
    names = list(schema["buildings"])
    for name in names[1:]:
        schema["buildings"][name]["include"] = False
    schema["buildings"][names[0]]["set_point_hold_time_steps"] = 2

    env = CityLearnEnv(schema, central_agent=True, simulation_start_time_step=0, simulation_end_time_step=35)
    try:
        env.reset(seed=0)
        bldg = env.buildings[0]
        bldg.energy_simulation.hvac_mode[:] = 3
        bldg.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[:] = 20.0
        bldg.energy_simulation.indoor_dry_bulb_temperature_heating_set_point_without_control[:] = 20.0
        bldg.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[30:] = 17.5
        bldg.energy_simulation.indoor_dry_bulb_temperature_heating_set_point_without_control[30:] = 17.5
        bldg.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[:] = 24.0
        bldg.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point_without_control[:] = 24.0
        bldg.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[30:] = 26.5
        bldg.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point_without_control[30:] = 26.5
        bldg.occupant.parameters.a_increase[:] = 20.0
        bldg.occupant.parameters.b_increase[:] = 0.0
        bldg.occupant.parameters.a_decrease[:] = -20.0
        bldg.occupant.parameters.b_decrease[:] = 0.0

        for _ in range(20):
            env.step([[0.5] * env.action_space[0].shape[0]])

        assert bldg.set_point_hold_time_steps == 2
        assert bldg.simulate_dynamics
        assert bldg.time_step < 25
        assert float(bldg.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[bldg.time_step]) <= 24.0 + 1.0e-5
        # Future schedules past the 2-step hold window (`30:`) must remain untouched!
        assert np.allclose(bldg.energy_simulation.indoor_dry_bulb_temperature_heating_set_point[30:], 17.5)
        assert np.allclose(bldg.energy_simulation.indoor_dry_bulb_temperature_cooling_set_point[30:], 26.5)
    finally:
        env.close()
