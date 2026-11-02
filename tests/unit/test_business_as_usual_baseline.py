import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.agents.baseline import (
    BusinessAsUsualAgent, NormalPolicy, NormalNoBatteryPolicy,
    RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy,
)
from citylearn.citylearn import CityLearnEnv


SOURCE_DATASET = Path(__file__).resolve().parents[1] / "data/minute_ev_demo"


def _run_zero_episode(env: CityLearnEnv):
    observations, _ = env.reset(seed=0)
    while not env.terminated:
        actions = [np.zeros(space.shape, dtype="float32") for space in env.flat_action_space]
        observations, *_ = env.step(actions)
    return observations


def _schema_with_deferrable_appliance(tmp_path: Path, *, earliest=0, latest=0) -> Path:
    dataset_dir = tmp_path / "minute_ev_demo"
    shutil.copytree(SOURCE_DATASET, dataset_dir)

    pd.DataFrame(
        [
            {
                "profile_id": "normal",
                "duration_steps": 2,
                "total_energy_kwh": 0.3,
                "load_profile": "[0.1,0.2]",
            }
        ]
    ).to_csv(dataset_dir / "washer_cycle_profiles.csv", index=False)
    pd.DataFrame(
        [
            {
                "cycle_id": "cycle_1",
                "profile_id": "normal",
                "earliest_start_time_step": earliest,
                "latest_start_time_step": latest,
                "deadline_time_step": latest + 1,
                "priority": 0.75,
                "must_run": True,
            }
        ]
    ).to_csv(dataset_dir / "washer_flexibility_schedule.csv", index=False)

    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["actions"]["deferrable_appliance"] = {"active": True}
    schema["observations"].update(
        {
            "deferrable_appliance_pending": {"active": True, "shared_in_central_agent": True},
            "deferrable_appliance_running": {"active": True, "shared_in_central_agent": True},
            "deferrable_appliance_can_start": {"active": True, "shared_in_central_agent": True},
            "deferrable_appliance_deadline_missed": {"active": True, "shared_in_central_agent": True},
        }
    )
    schema["buildings"]["Building_1"]["deferrable_appliances"] = {
        "washer_1": {
            "type": "citylearn.energy_model.DeferrableAppliance",
            "cycle_profiles_file": "washer_cycle_profiles.csv",
            "flexibility_schedule_file": "washer_flexibility_schedule.csv",
        }
    }
    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema_path


def _business_action(env: CityLearnEnv):
    agent = BusinessAsUsualAgent(env)
    return agent.predict(env.observations)[0]


def test_business_as_usual_ev_charges_to_full_and_never_discharges():
    env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        action_names = env.action_names[0]
        ev_index = next(i for i, name in enumerate(action_names) if name.startswith("electric_vehicle_storage_"))
        action = _business_action(env)
        assert action[ev_index] > 0.0

        charger = env.buildings[0].electric_vehicle_chargers[0]
        charger.connected_electric_vehicle.battery.soc[env.time_step] = 1.0
        action = _business_action(env)
        assert action[ev_index] == pytest.approx(0.0)
        assert action[ev_index] >= 0.0
    finally:
        env.close()


@pytest.mark.parametrize('agent_class', [BusinessAsUsualAgent, NormalPolicy, NormalNoBatteryPolicy])
@pytest.mark.parametrize('soc', [0.2, 0.8, 0.999])
def test_bau_requests_maximum_until_full_even_above_departure_target(agent_class, soc):
    env = CityLearnEnv(str(SOURCE_DATASET / 'schema.json'), episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        charger = env.buildings[0].electric_vehicle_chargers[0]
        charger.connected_electric_vehicle.battery.soc[0] = soc
        charger.min_charging_power = 1.38
        agent = agent_class(env)
        # A long deadline and a lower service target must never slow down BAU.
        agent._ev_service_context_for_charger = lambda *args: {
            'soc': soc, 'required_soc': 0.6, 'departure_hours': 100.0, 'capacity_kwh': 20.0,
        }
        assert agent._ev_action_for_charger(charger, -1.0, 1.0, building=env.buildings[0]) == 1.0
        assert agent._ev_action_for_charger(charger, -1.0, 0.4, building=env.buildings[0]) == 0.4
        charger.connected_electric_vehicle = None
        assert agent._ev_action_for_charger(charger, -1.0, 1.0) == 0.0
    finally:
        env.close()


def test_bau_finishes_the_last_charge_interval_despite_charger_deadband():
    env = CityLearnEnv(str(SOURCE_DATASET / 'schema.json'), episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        charger = env.buildings[0].electric_vehicle_chargers[0]
        ev = charger.connected_electric_vehicle
        ev.battery.soc[0] = 0.999
        charger.min_charging_power = 1.38
        agent = BusinessAsUsualAgent(env)
        action = agent._ev_action_for_charger(charger, -1.0, 1.0)
        charger.update_connected_electric_vehicle_soc(action)
        assert ev.battery.soc[0] == pytest.approx(1.0, abs=1e-6)
        assert agent._ev_action_for_charger(charger, -1.0, 1.0) == 0.0
    finally:
        env.close()


@pytest.mark.parametrize('seconds', [15, 900, 3600])
def test_bau_battery_covers_accepted_ev_energy_instead_of_exporting_nominal_request(seconds):
    env = CityLearnEnv(str(SOURCE_DATASET / 'schema.json'), central_agent=True,
                      seconds_per_time_step=seconds, episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        charger = building.electric_vehicle_chargers[0]
        ev = charger.connected_electric_vehicle
        ev.battery.soc[0] = 0.999
        building.energy_simulation.non_shiftable_load[0] = 0.0
        building._Building__solar_generation[0] = 0.0
        agent = BusinessAsUsualAgent(env)
        before = ev.battery.soc.copy()
        efficiency = ev.battery.efficiency
        actions = agent.predict([])
        np.testing.assert_array_equal(ev.battery.soc, before)
        assert ev.battery.efficiency == efficiency
        assert actions[0][-1] == 1.0
        env.step(actions)
        assert 0.999 < ev.battery.soc[0] <= 1.0
        if seconds >= 900:
            assert ev.battery.soc[0] == pytest.approx(1.0, abs=1e-6)
        assert building.net_electricity_consumption[0] >= -1.0e-5
    finally:
        env.close()


@pytest.mark.parametrize('kwargs', [
    {'ev_target_soc': 0.8}, {'ev_follow_required_soc': True}, {'ev_service_floor_rate': 0.5},
])
def test_bau_rejects_configuration_that_changes_its_full_charge_definition(kwargs):
    env = CityLearnEnv(str(SOURCE_DATASET / 'schema.json'), episode_time_steps=4, random_seed=0)
    try:
        with pytest.raises(ValueError, match='RBC'):
            BusinessAsUsualAgent(env, **kwargs)
    finally:
        env.close()


@pytest.mark.parametrize('agent_class', [RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy])
def test_native_rbcs_still_stop_at_departure_target(agent_class):
    env = CityLearnEnv(str(SOURCE_DATASET / 'schema.json'), episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        charger = building.electric_vehicle_chargers[0]
        charger.connected_electric_vehicle.battery.soc[0] = 0.8
        agent = agent_class(env)
        agent._ev_service_context_for_charger = lambda *args: {
            'soc': 0.8, 'required_soc': 0.6, 'departure_hours': 100.0, 'capacity_kwh': 20.0,
        }
        assert agent._ev_action_for_charger(charger, 0.0, 1.0, building=building) == 0.0
    finally:
        env.close()


def test_business_as_usual_deferrable_starts_at_first_available_step(tmp_path: Path):
    schema_path = _schema_with_deferrable_appliance(tmp_path, earliest=0, latest=1)
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        action_names = env.action_names[0]
        index = action_names.index("deferrable_appliance_washer_1")
        action = _business_action(env)
        assert action[index] == pytest.approx(1.0)

        env.step([np.asarray(action, dtype="float32")])
        action = _business_action(env)
        assert action[index] == pytest.approx(0.0)
    finally:
        env.close()


def test_business_as_usual_bess_self_consumption_respects_soc_and_deadband():
    env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        env.reset(seed=0)
        building = env.buildings[0]
        building.electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 1.0
        action_names = env.action_names[0]
        storage_index = action_names.index("electrical_storage")

        building.energy_simulation.non_shiftable_load[0] = 0.0
        building._Building__solar_generation[0] = -0.5
        action = _business_action(env)
        assert action[storage_index] > 0.0

        building.electrical_storage.soc[0] = 0.95
        action = _business_action(env)
        assert action[storage_index] == pytest.approx(0.0)

        building.electrical_storage.soc[0] = 0.5
        building._Building__solar_generation[0] = 0.0
        building.energy_simulation.non_shiftable_load[0] = 0.5
        action = _business_action(env)
        assert action[storage_index] < 0.0

        building.electrical_storage.soc[0] = 0.1
        action = _business_action(env)
        assert action[storage_index] == pytest.approx(0.0)

        building.electrical_storage.soc[0] = 0.5
        building.energy_simulation.non_shiftable_load[0] = 0.001
        action = _business_action(env)
        assert action[storage_index] == pytest.approx(0.0)
    finally:
        env.close()


@pytest.mark.parametrize("seconds_per_time_step", [15, 300, 3600])
def test_business_as_usual_storage_action_uses_power_not_timestep_energy(seconds_per_time_step: int):
    env = CityLearnEnv(
        str(SOURCE_DATASET / "schema.json"),
        central_agent=True,
        episode_time_steps=4,
        seconds_per_time_step=seconds_per_time_step,
        random_seed=0,
    )

    try:
        env.reset(seed=0)
        building = env.buildings[0]
        building.electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 1.0
        storage_index = env.action_names[0].index("electrical_storage")
        step_hours = seconds_per_time_step / 3600.0
        target_surplus_kw = 2.0

        building.energy_simulation.non_shiftable_load[0] = 0.0
        building._Building__solar_generation[0] = -(target_surplus_kw * step_hours)
        action = _business_action(env)

        assert action[storage_index] == pytest.approx(target_surplus_kw / building.electrical_storage.nominal_power)
    finally:
        env.close()


def test_evaluate_v2_adds_business_as_usual_rows_and_can_disable_them():
    env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        _run_zero_episode(env)

        with_bau = env.evaluate_v2()
        assert "district_cost_total_business_as_usual_eur" in set(with_bau["cost_function"])
        assert "district_energy_grid_ratio_to_business_as_usual_import_total_ratio" in set(with_bau["cost_function"])
        assert "district_ev_total_charge_business_as_usual_kwh" in set(with_bau["cost_function"])
        assert "district_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio" in set(with_bau["cost_function"])
        assert "building_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio" in set(with_bau["cost_function"])

        cache_before = env.run_business_as_usual_baseline()
        cache_after = env.run_business_as_usual_baseline()
        assert cache_before is cache_after

        without_bau = env.evaluate_v2(include_business_as_usual=False)
        assert not without_bau["cost_function"].str.contains("business_as_usual", na=False).any()
    finally:
        env.close()


def test_business_as_usual_fast_rollout_matches_regular_step():
    regular_env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4, random_seed=0)
    fast_env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4, random_seed=0)

    try:
        regular_agent = BusinessAsUsualAgent(regular_env)
        fast_agent = BusinessAsUsualAgent(fast_env)
        regular_env.reset(seed=0)
        fast_env.reset(seed=0)

        while not regular_env.terminated:
            actions = regular_agent.predict([], deterministic=True)
            regular_env.step(actions)

        while not fast_env.terminated:
            actions = fast_agent.predict([], deterministic=True)
            fast_env._runtime_service.step_without_feedback(actions)

        assert fast_env.time_step == regular_env.time_step
        np.testing.assert_allclose(
            np.asarray(fast_env.net_electricity_consumption, dtype="float64"),
            np.asarray(regular_env.net_electricity_consumption, dtype="float64"),
        )

        regular_kpis = regular_env.evaluate_v2(include_business_as_usual=False).sort_values(
            ["level", "name", "cost_function"]
        ).reset_index(drop=True)
        fast_kpis = fast_env.evaluate_v2(include_business_as_usual=False).sort_values(
            ["level", "name", "cost_function"]
        ).reset_index(drop=True)
        pd.testing.assert_frame_equal(regular_kpis, fast_kpis, check_exact=False, atol=1e-10, rtol=1e-10)
    finally:
        regular_env.close()
        fast_env.close()


def test_export_writes_combined_kpis_and_business_as_usual_timeseries(tmp_path: Path):
    env = CityLearnEnv(
        str(SOURCE_DATASET / "schema.json"),
        central_agent=True,
        episode_time_steps=4,
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        _run_zero_episode(env)
        env.export_final_kpis(filepath="exported_kpis.csv")
        kpis_path = Path(env.new_folder_path) / "exported_kpis.csv"
        timeseries_path = Path(env.new_folder_path) / "exported_data_business_as_usual_ep0.csv"

        assert kpis_path.is_file()
        assert timeseries_path.is_file()

        kpis = pd.read_csv(kpis_path)
        assert "district_cost_total_business_as_usual_eur" in set(kpis["KPI"])

        timeseries = pd.read_csv(timeseries_path)
        assert {"time_step", "name", "level", "net_electricity_consumption_kwh"}.issubset(timeseries.columns)
        assert {"Building_1", "District"}.issubset(set(timeseries["name"]))
        for _, group in timeseries.groupby("time_step"):
            building_solar = group[group["level"] == "building"]["solar_generation_kwh"].sum()
            district_solar = group[group["level"] == "district"]["solar_generation_kwh"].iloc[0]
            assert district_solar == pytest.approx(building_solar)
    finally:
        env.close()


def test_cli_default_agent_is_business_as_usual(monkeypatch):
    from citylearn.__main__ import main

    monkeypatch.setattr(sys, "argv", ["sphinx-build"])
    parser = main()
    simulate = next(action for action in parser._actions if action.dest == "subcommands").choices["simulate"]
    agent_action = next(action for action in simulate._actions if action.dest == "agent_name")

    assert agent_action.default == "citylearn.agents.baseline.BusinessAsUsualAgent"
