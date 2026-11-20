import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.agents.baseline import (
    BusinessAsUsualAgent, RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy,
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


def _ev_action(agent_class, env: CityLearnEnv, **kwargs) -> float:
    agent = agent_class(env, **kwargs)
    action = agent.predict([])[0]
    index = next(i for i, name in enumerate(env.action_names[0]) if name.startswith("electric_vehicle_storage_"))
    return action[index]


def _ev_env(**kwargs) -> CityLearnEnv:
    env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4, random_seed=0, **kwargs)
    env.reset(seed=0)
    return env


def test_requested_target_bau_charges_at_once_up_to_user_target_and_never_discharges():
    # Fixture: 20 kWh EV, requested departure SOC 0.8, 7.2 kW charger, 15-minute steps.
    env = _ev_env()
    try:
        battery = env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery
        battery.soc[0] = 0.4
        assert _ev_action(BusinessAsUsualAgent, env, ev_charge_target="requested") == pytest.approx(1.0)

        # The last command is limited to the remaining energy gap.
        battery.soc[0] = 0.79
        expected = (0.8 - 0.79 - 1.0e-6) * 20.0 / (0.25 * 7.2)
        assert _ev_action(BusinessAsUsualAgent, env, ev_charge_target="requested") == pytest.approx(expected, rel=1.0e-4)

        for soc in (0.8, 0.95, 1.0):
            battery.soc[0] = soc
            assert _ev_action(BusinessAsUsualAgent, env, ev_charge_target="requested") == pytest.approx(0.0)
    finally:
        env.close()


def _bau_step_with_nearly_full_ev(tmp_path: Path, seconds: int, core_bundle: bool):
    # The load is zero in the data, so the settled net observation at reset is
    # zero and the one-step lag of issue #190 plays no part.
    dataset_dir = tmp_path / f"minute_ev_demo_{seconds}_{core_bundle}"
    shutil.copytree(SOURCE_DATASET, dataset_dir)
    load_path = dataset_dir / "Building_1.csv"
    load = pd.read_csv(load_path)
    load["non_shiftable_load"] = 0.0
    load.to_csv(load_path, index=False)
    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    if core_bundle:
        schema["observation_bundles"] = {"entity_core_electrical": True}
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    env = CityLearnEnv(
        str(schema_path), central_agent=True, seconds_per_time_step=seconds, episode_time_steps=4, random_seed=0, time_step_ratio_mode='compress'
    )
    try:
        env.reset(seed=0)
        building = env.buildings[0]
        ev = building.electric_vehicle_chargers[0].connected_electric_vehicle
        ev.battery.soc[0] = 0.999
        actions = BusinessAsUsualAgent(env).predict([])
        env.step(actions)
        return actions[0], float(ev.battery.soc[0]), float(building.net_electricity_consumption[0])
    finally:
        env.close()


# At 15 s steps the EV battery's capacity-power curve limits charging below the
# available_charge_power_kw observation, which leaves a small export with and
# without the bundle. That curve is not observable, see docs/baselines.md.
@pytest.mark.parametrize("seconds", [900, 3600])
def test_bau_battery_covers_accepted_ev_energy_instead_of_exporting_nominal_request(tmp_path: Path, seconds: int):
    # Issue #190, consequence 2: without entity_core_electrical, BAU reserved
    # the charger's 7.2 kW for an EV that accepts ~0.02 kWh, and the home
    # battery discharged for it and exported.
    results = {bundle: _bau_step_with_nearly_full_ev(tmp_path, seconds, bundle) for bundle in (False, True)}
    for actions, soc, net in results.values():
        assert actions[-1] == 1.0
        assert soc == pytest.approx(1.0, abs=1e-6)
        assert net >= -1.0e-5
    # Without the bundle, the estimate leads to the decision the observation gives.
    np.testing.assert_allclose(results[False][0], results[True][0], rtol=0.0, atol=1.0e-6)


def test_business_as_usual_stops_below_target_instead_of_overshooting_charger_minimum(tmp_path: Path):
    dataset_dir = tmp_path / "minute_ev_demo"
    shutil.copytree(SOURCE_DATASET, dataset_dir)
    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    # The remaining 0.2 kWh needs ~0.8 kW for 15 minutes, below this minimum.
    schema["buildings"]["Building_1"]["chargers"]["charger_1_1"]["attributes"]["min_charging_power"] = 1.38
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 0.79
        assert _ev_action(BusinessAsUsualAgent, env, ev_charge_target="requested") == pytest.approx(0.0)
        env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 0.4
        assert _ev_action(BusinessAsUsualAgent, env, ev_charge_target="requested") == pytest.approx(1.0)
    finally:
        env.close()


def test_business_as_usual_episode_never_charges_above_user_target():
    env = _ev_env()
    try:
        ev = env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle
        ev.battery.soc[0] = 0.7
        agent = BusinessAsUsualAgent(env, ev_charge_target="requested")
        while not env.terminated:
            env.step(agent.predict([]))
        assert max(float(v) for v in ev.battery.soc[: env.time_step + 1]) <= 0.8 + 1.0e-4
    finally:
        env.close()


def test_bau_definition_and_removed_names():
    import citylearn.agents.baseline as baseline

    for name in ("NormalPolicy", "NormalTargetPolicy", "NormalNoBatteryPolicy", "ServiceOnlyBaselineAgent",
                 "GridAwareBaselineAgent", "CommunityAwareBaselineAgent"):
        assert not hasattr(baseline, name)
    assert BusinessAsUsualAgent.DEFINITION_VERSION == "immediate-full-charge-v3"


@pytest.mark.parametrize("kwargs", [
    {"ev_charge_target": "requested", "ev_normal_target_soc": 0.5}, {"not_a_parameter": 1.0},
])
def test_business_as_usual_rejects_invalid_configuration(kwargs):
    env = _ev_env()
    try:
        with pytest.raises(ValueError):
            BusinessAsUsualAgent(env, **kwargs)
    finally:
        env.close()


@pytest.mark.parametrize("agent_class", [RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy])
def test_rule_based_baselines_stop_at_departure_target(agent_class):
    env = _ev_env()
    try:
        env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 0.85
        assert _ev_action(agent_class, env) == pytest.approx(0.0)
    finally:
        env.close()


@pytest.mark.parametrize("agent_class", [RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy])
def test_rule_based_baselines_serve_a_tight_departure(agent_class):
    env = _ev_env()
    try:
        # 8 kWh in four 15-minute steps at 7.2 kW needs more than full power: serve now.
        env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 0.4
        assert _ev_action(agent_class, env) > 0.5
    finally:
        env.close()


@pytest.mark.parametrize(
    "agent_class",
    [BusinessAsUsualAgent, RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy],
)
def test_baselines_take_the_same_actions_under_flat_and_entity_interfaces(agent_class):
    trajectories = []
    for interface in ("flat", "entity"):
        env = CityLearnEnv(
            str(SOURCE_DATASET / "schema.json"), central_agent=False, episode_time_steps=4,
            random_seed=0, interface=interface,
        )
        try:
            observations, _ = env.reset(seed=0)
            agent = agent_class(env)
            actions = []
            while not env.terminated:
                action = agent.predict(observations)
                actions.append(action)
                observations, *_ = env.step(action)
            trajectories.append(actions)
        finally:
            env.close()
    np.testing.assert_allclose(np.asarray(trajectories[0]), np.asarray(trajectories[1]))


def _robust_minute_schema(tmp_path: Path, enabled: bool = True) -> str:
    dataset_dir = tmp_path / f"minute_ev_demo_robust_{enabled}"
    shutil.copytree(SOURCE_DATASET, dataset_dir)
    # Events valid under both interfaces target building features, here ones
    # the baselines read: the settled net import, the load and the battery SOC.
    event = dict(module="observation", target_type="building", target_id="Building_1", std=None, value=None)
    events = [
        dict(event, event_id="net_noise", target_feature="net_electricity_consumption", start_time_step=0,
             end_time_step=7, mode="noise", std=2.0),
        dict(event, event_id="load_bias", target_feature="non_shiftable_load", start_time_step=2, end_time_step=5,
             mode="bias", value=2.0),
        dict(event, event_id="soc_stuck", target_feature="electrical_storage_soc", start_time_step=1,
             end_time_step=7, mode="stuck"),
    ]
    pd.DataFrame(events).to_csv(dataset_dir / "robustness_events.csv", index=False)
    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["robustness"] = {"enabled": enabled, "events_file": "robustness_events.csv", "random_seed": 7}
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    return str(schema_path)


def _baseline_actions(schema: str, interface: str, agent_class) -> np.ndarray:
    env = CityLearnEnv(schema, central_agent=False, episode_time_steps=8, random_seed=0, interface=interface)
    try:
        observations, _ = env.reset(seed=0)
        agent = agent_class(env)
        actions = []
        while not env.terminated:
            action = agent.predict(observations)
            actions.append(action)
            observations, *_ = env.step(action)
        return np.asarray(actions, dtype="float64")
    finally:
        env.close()


@pytest.mark.parametrize(
    "agent_class",
    [BusinessAsUsualAgent, RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy],
)
def test_baselines_read_the_same_corrupted_observations_under_flat_and_entity_interfaces(tmp_path, agent_class):
    # Issue #192: under the flat interface the env corrupts only the flat
    # vectors, which the baselines do not read.
    schema = _robust_minute_schema(tmp_path)
    flat = _baseline_actions(schema, "flat", agent_class)
    np.testing.assert_array_equal(flat, _baseline_actions(schema, "entity", agent_class))
    clean = _baseline_actions(_robust_minute_schema(tmp_path, enabled=False), "flat", agent_class)
    assert not np.array_equal(flat, clean)


def test_flat_baseline_robustness_view_leaves_the_env_and_its_random_streams_unchanged(tmp_path):
    schema = _robust_minute_schema(tmp_path)

    def run(actions=None):
        env = CityLearnEnv(schema, central_agent=False, episode_time_steps=8, random_seed=0, interface="flat")
        try:
            observations, _ = env.reset(seed=0)
            agent = BusinessAsUsualAgent(env) if actions is None else None
            taken, seen = [], []
            while not env.terminated:
                seen.append(np.asarray(observations, dtype="float64"))
                action = agent.predict(observations) if agent else actions[len(taken)]
                taken.append(action)
                observations, *_ = env.step(action)
            service = env._robustness_service
            return dict(
                actions=taken, observations=seen, history=service.history, stuck=dict(service._stuck_values),
                net=np.asarray(env.net_electricity_consumption, dtype="float64"),
                np_random=env.np_random.bit_generator.state,
                ev_drift=env._ev_drift_random_state.get_state(),
            )
        finally:
            env.close()

    # The baseline reads its corrupted entity payload; the replay reads nothing.
    with_view = run()
    replay = run(actions=with_view["actions"])
    np.testing.assert_array_equal(np.asarray(with_view["observations"]), np.asarray(replay["observations"]))
    np.testing.assert_array_equal(with_view["net"], replay["net"])
    assert with_view["history"] == replay["history"]
    assert with_view["stuck"] == replay["stuck"]
    assert with_view["np_random"] == replay["np_random"]
    left, right = with_view["ev_drift"], replay["ev_drift"]
    np.testing.assert_array_equal(left[1], right[1])
    assert (left[0],) + tuple(left[2:]) == (right[0],) + tuple(right[2:])


def test_native_bau_reference_input_stays_uncorrupted_under_flat_robustness(tmp_path):
    actions = []
    for enabled in (True, False):
        env = CityLearnEnv(
            _robust_minute_schema(tmp_path, enabled), central_agent=False, episode_time_steps=8, random_seed=0,
            interface="flat",
        )
        try:
            env.reset(seed=0)
            agent = BusinessAsUsualAgent(env)
            env.step(agent.predict([]))
            actions.append(agent.predict([]))
        finally:
            env.close()
    np.testing.assert_array_equal(np.asarray(actions[0]), np.asarray(actions[1]))


def test_baseline_comparison_identity_records_definition_and_parameters():
    env = _ev_env()
    try:
        identity = RBCCommunityPolicy(env, community_import_threshold_kw=10.0).comparison_identity()
        assert identity["implementation"] == "citylearn.agents.baseline.RBCCommunityPolicy"
        assert identity["parameters"]["definition_version"] == RBCCommunityPolicy.DEFINITION_VERSION
        assert identity["parameters"]["community_import_threshold_kw"] == 10.0
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


def _bau_storage_action(*, solar_kwh: float, load_kwh: float, net_kwh: float, soc: float) -> float:
    """Storage command of the BAU engine for one observed 15-minute building state."""
    from gymnasium import spaces
    from citylearn.agents import _baseline_engine as engines

    engine = engines.NormalTargetPolicy({"algorithm": {"hyperparameters": {}}})
    names = [
        "solar_generation", "non_shiftable_load", "net_electricity_consumption",
        "storage::B/electrical_storage::soc", "storage::B/electrical_storage::capacity_kwh",
        "storage::B/electrical_storage::nominal_power_kw",
    ]
    engine.attach_environment(
        observation_names=[names], action_names=[["electrical_storage"]],
        action_space=[spaces.Box(-1.0, 1.0, (1,))], observation_space=[None],
        metadata={"seconds_per_time_step": 900, "building_names": ["B"]},
    )
    observation = np.asarray([solar_kwh, load_kwh, net_kwh, soc, 5.0, 5.0], dtype="float64")
    return engine.predict([observation])[0][0]


def test_business_as_usual_bess_self_consumption_respects_soc_and_threshold():
    # 0.5 kWh PV surplus in 15 minutes is 2 kW: charge at 2 kW of the 5 kW battery.
    assert _bau_storage_action(solar_kwh=0.5, load_kwh=0.0, net_kwh=-0.5, soc=0.5) == pytest.approx(0.4)
    assert _bau_storage_action(solar_kwh=0.5, load_kwh=0.0, net_kwh=-0.5, soc=0.95) == pytest.approx(0.0)
    # 0.5 kWh local import in 15 minutes is 2 kW: discharge at 2 kW.
    assert _bau_storage_action(solar_kwh=0.0, load_kwh=0.5, net_kwh=0.5, soc=0.5) == pytest.approx(-0.4)
    assert _bau_storage_action(solar_kwh=0.0, load_kwh=0.5, net_kwh=0.5, soc=0.1) == pytest.approx(0.0)
    # 0.004 kW is below the 0.05 kW discharge threshold.
    assert _bau_storage_action(solar_kwh=0.0, load_kwh=0.001, net_kwh=0.001, soc=0.5) == pytest.approx(0.0)


@pytest.mark.parametrize("seconds_per_time_step", [15, 300, 3600])
def test_business_as_usual_storage_action_uses_power_not_timestep_energy(seconds_per_time_step: int):
    env = CityLearnEnv(
        str(SOURCE_DATASET / "schema.json"),
        central_agent=True,
        episode_time_steps=4,
        seconds_per_time_step=seconds_per_time_step,
        random_seed=0,
        time_step_ratio_mode='compress',
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


@pytest.mark.parametrize("agent_class", [BusinessAsUsualAgent, RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy])
def test_baselines_request_zero_for_actions_they_do_not_control(tmp_path: Path, agent_class):
    dataset_dir = tmp_path / "minute_ev_demo"
    shutil.copytree(SOURCE_DATASET, dataset_dir)
    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    env = CityLearnEnv(str(schema_path), central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        env.reset(seed=0)
        agent = agent_class(env)
        # Pretend the storage action is not controlled: it must be zero, the EV still served.
        agent._is_controlled_action = lambda name: name.startswith("electric_vehicle_storage")
        agent._attach(None)
        action = agent.predict([])[0]
        names = env.action_names[0]
        assert action[names.index("electrical_storage")] == 0.0
        assert action[next(i for i, n in enumerate(names) if n.startswith("electric_vehicle_storage_"))] > 0.0
    finally:
        env.close()


def test_buildings_without_service_limits_publish_unlimited_headroom(tmp_path: Path):
    from citylearn.internal.entity_interface import CityLearnEntityInterfaceService

    env = CityLearnEnv(str(_market_schema_with_bundles(tmp_path)), central_agent=False, episode_time_steps=4,
                       random_seed=0, interface="entity")
    try:
        payload, _ = env.reset(seed=0)
        features = env.entity_specs["tables"]["building"]["features"]
        table = np.asarray(payload["tables"]["building"])
        names = [b.name for b in env.buildings]
        unlimited, limited = names.index("Building_10"), names.index("Building_15")
        for feature in ("charging_building_headroom_kw", "charging_phase_L1_headroom_kw", "building_import_headroom_kw"):
            column = features.index(feature)
            # No limit is published as the space bound, never as 0 kW of headroom.
            assert table[unlimited, column] == CityLearnEntityInterfaceService.UNLIMITED_HEADROOM_KW
            assert 0.0 < table[limited, column] < CityLearnEntityInterfaceService.UNLIMITED_HEADROOM_KW
    finally:
        env.close()


@pytest.mark.parametrize("soc", [0.2, 0.8, 0.95])
def test_full_charge_bau_requests_maximum_until_full_even_above_departure_target(soc):
    env = _ev_env()
    try:
        env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = soc
        assert _ev_action(BusinessAsUsualAgent, env, ev_charge_target="full") == pytest.approx(1.0)
        env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 1.0
        assert _ev_action(BusinessAsUsualAgent, env, ev_charge_target="full") == pytest.approx(0.0)
    finally:
        env.close()


def test_bau_charge_target_is_validated_and_recorded():
    env = _ev_env()
    try:
        with pytest.raises(ValueError, match="ev_charge_target"):
            BusinessAsUsualAgent(env, ev_charge_target="half")
        assert BusinessAsUsualAgent(env).ev_charge_target == "full"
        agent = BusinessAsUsualAgent(env, ev_charge_target="requested")
        assert agent.DEFINITION_VERSION == "immediate-user-target-v2"
        parameters = agent.comparison_identity()["parameters"]
        assert parameters["ev_charge_target"] == "requested"
        assert parameters["definition_version"] == "immediate-user-target-v2"
    finally:
        env.close()


@pytest.mark.parametrize("target,definition", [("requested", "immediate-user-target-v2"), ("full", "immediate-full-charge-v3")])
def test_evaluate_v2_uses_the_selected_bau(target, definition):
    env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4,
                       random_seed=0, business_as_usual_ev_charge_target=target)
    try:
        env.reset(seed=0)
        env.buildings[0].electric_vehicle_chargers[0].connected_electric_vehicle.battery.soc[0] = 0.4
        _run_zero_episode(env)
        kpis = env.evaluate_v2()
        assert "district_ev_total_charge_business_as_usual_kwh" in set(kpis["cost_function"])
        reference = env.run_business_as_usual_baseline().env._native_reference_metadata
        assert reference["definition_version"] == definition
        assert env.get_metadata()["business_as_usual_ev_charge_target"] == target
    finally:
        env.close()


def test_env_rejects_unknown_bau_charge_target():
    with pytest.raises(ValueError, match="ev_charge_target"):
        CityLearnEnv(str(SOURCE_DATASET / "schema.json"), episode_time_steps=4, business_as_usual_ev_charge_target="x")


def _market_schema_with_bundles(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "data/datasets/citylearn_three_phase_electrical_service_demo"
    dataset_dir = tmp_path / "market_demo"
    shutil.copytree(source, dataset_dir)
    schema_path = dataset_dir / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["observation_bundles"] = {
        name: True for name in (
            "entity_core_electrical", "entity_community_operational",
            "entity_forecasts_existing", "entity_forecasts_derived",
        )
    }
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    return schema_path


def test_smart_and_community_use_forecast_and_community_bundles(tmp_path: Path):
    schema_path = _market_schema_with_bundles(tmp_path)
    actions = {}
    for agent_class in (RBCSmartPolicy, RBCCommunityPolicy):
        env = CityLearnEnv(str(schema_path), central_agent=False, episode_time_steps=48, random_seed=0)
        try:
            observations, _ = env.reset(seed=0)
            agent = agent_class(env)
            names = set(agent._engine._obs_index[0])
            # Both see the price and PV forecasts; only Community sees the community state.
            assert any(name.startswith("forecast_pv_next_") for name in names)
            assert any("price" in name and ("forecast" in name or "predicted" in name) for name in names)
            has_community = any("community_import_power_kw" in name for name in names)
            assert has_community == (agent_class is RBCCommunityPolicy)
            assert agent._engine.uses_community_dispatch == (agent_class is RBCCommunityPolicy)
            history = []
            while not env.terminated:
                action = agent.predict(observations)
                history.append(action)
                observations, *_ = env.step(action)
            actions[agent_class] = np.asarray(history, dtype=object)
        finally:
            env.close()
    smart = [np.concatenate(step) for step in actions[RBCSmartPolicy]]
    community = [np.concatenate(step) for step in actions[RBCCommunityPolicy]]
    assert any(not np.allclose(a, b) for a, b in zip(smart, community))


@pytest.mark.parametrize("dataset", ["citylearn_three_phase_dynamic_topology_demo", "citylearn_challenge_2022_phase_all_plus_evs"])
def test_fast_observation_layout_matches_reference(dataset):
    env = CityLearnEnv(dataset, central_agent=False, episode_time_steps=24, random_seed=0)
    try:
        observations, _ = env.reset(seed=0)
        agent = BusinessAsUsualAgent(env)
        while not env.terminated:
            payload = env._entity_service.observation_payload()
            fast_names, fast_values = agent._flattener.flatten(payload)
            names, values = agent._flattener.flatten_reference(payload)
            assert fast_names == names
            for fast, reference in zip(fast_values, values):
                np.testing.assert_array_equal(fast, reference)
            observations, *_ = env.step(agent.predict(observations))
    finally:
        env.close()


def test_bau_reference_cache_follows_the_selected_target():
    env = CityLearnEnv(str(SOURCE_DATASET / "schema.json"), central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        _run_zero_episode(env)
        full = env.run_business_as_usual_baseline()
        assert full.ev_charge_target == "full"
        env.business_as_usual_ev_charge_target = "requested"
        requested = env.run_business_as_usual_baseline()
        assert requested is not full
        assert requested.env._native_reference_metadata["definition_version"] == "immediate-user-target-v2"
    finally:
        env.close()


def _multi_episode_actions(env: CityLearnEnv, make_agent, episodes: int, fresh_agent_per_episode: bool):
    actions, agent = [], None
    for _ in range(episodes):
        observations, _ = env.reset()
        if agent is None or fresh_agent_per_episode:
            agent = make_agent(env)
        while not env.terminated:
            action = agent.predict(observations)
            actions.append([np.asarray(a, dtype="float64") for a in action])
            observations, *_ = env.step(action)
    return actions


def _assert_same_actions(left, right):
    assert len(left) == len(right)
    for step_left, step_right in zip(left, right):
        assert len(step_left) == len(step_right)
        for a, b in zip(step_left, step_right):
            np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize(
    "agent_class",
    [BusinessAsUsualAgent, RBCBasicPolicy, RBCSmartPolicy, RBCCommunityPolicy],
)
@pytest.mark.parametrize("interface", ["flat", "entity"])
def test_baselines_parse_the_dataset_once_and_keep_their_actions_across_episodes(agent_class, interface):
    from unittest import mock

    from citylearn.agents._rule_engine import RulePolicyBase
    from citylearn.agents.baseline import _RuleBaselineAgent

    def make_env():
        return CityLearnEnv(
            str(SOURCE_DATASET / "schema.json"), central_agent=False, episode_time_steps=4,
            rolling_episode_split=True, random_seed=0, interface=interface,
        )

    env = make_env()
    try:
        with mock.patch.object(
            RulePolicyBase, "_load_dataset_info", autospec=True, side_effect=RulePolicyBase._load_dataset_info,
        ) as parse, mock.patch.object(
            _RuleBaselineAgent, "_attach", autospec=True, side_effect=_RuleBaselineAgent._attach,
        ) as attach:
            reused = _multi_episode_actions(env, agent_class, episodes=3, fresh_agent_per_episode=False)
        # One agent, three episodes: the schema and EV files are parsed once and,
        # with a static topology, the engine is attached once.
        assert parse.call_count == 1
        assert attach.call_count == 1
    finally:
        env.close()

    env = make_env()
    try:
        # A new agent per episode builds and attaches a new engine, as every reset did before.
        rebuilt = _multi_episode_actions(env, agent_class, episodes=3, fresh_agent_per_episode=True)
    finally:
        env.close()
    _assert_same_actions(reused, rebuilt)


def test_baseline_attaches_again_when_the_topology_changes():
    from unittest import mock

    from citylearn.agents._rule_engine import RulePolicyBase
    from citylearn.agents.baseline import _RuleBaselineAgent

    def make_env():
        # Building_18 joins at global step 1000. Rolling episodes start at steps 995 and 996.
        return CityLearnEnv(
            "citylearn_three_phase_dynamic_topology_demo", central_agent=False,
            simulation_start_time_step=995, simulation_end_time_step=1014, episode_time_steps=10,
            rolling_episode_split=True, random_seed=0,
        )

    env = make_env()
    try:
        versions = []
        with mock.patch.object(
            RulePolicyBase, "_load_dataset_info", autospec=True, side_effect=RulePolicyBase._load_dataset_info,
        ) as parse, mock.patch.object(
            _RuleBaselineAgent, "_attach", autospec=True, side_effect=_RuleBaselineAgent._attach,
        ) as attach:
            agent = None
            reused = []
            for _ in range(2):
                observations, _ = env.reset()
                if agent is None:
                    agent = BusinessAsUsualAgent(env)
                while not env.terminated:
                    versions.append(env.topology_version)
                    action = agent.predict(observations)
                    reused.append([np.asarray(a, dtype="float64") for a in action])
                    observations, *_ = env.step(action)
        assert versions == [0] * 5 + [1] * 4 + [0] * 4 + [1] * 5
        assert parse.call_count == 1
        # Construction, the reset that restored the initial members, and the
        # member added at step 1000 in each episode.
        assert attach.call_count == 4
    finally:
        env.close()

    env = make_env()
    try:
        rebuilt = _multi_episode_actions(env, BusinessAsUsualAgent, episodes=2, fresh_agent_per_episode=True)
    finally:
        env.close()
    _assert_same_actions(reused, rebuilt)


@pytest.mark.parametrize("agent_class", [BusinessAsUsualAgent, RBCBasicPolicy])
def test_battery_does_not_recharge_from_the_grid_after_its_own_export(agent_class):
    # These baselines charge the battery only from PV surplus. (RBCSmartPolicy and RBCCommunityPolicy
    # also charge it from the grid at cheap prices by design, so they are not checked here.) Without the entity_core_electrical bundle the baselines took the last interval's export as PV
    # surplus. When a battery discharge overshot the load and was exported, the battery recharged from
    # the grid in the next step: 22.8 kWh in 27 of the first 48 hours of this dataset with the BAU.
    env = CityLearnEnv(
        "citylearn_three_phase_electrical_service_demo", central_agent=True, episode_time_steps=48,
        random_seed=0, interface="flat",
    )
    try:
        observations, _ = env.reset(seed=0)
        agent = agent_class(env)
        while not env.terminated:
            observations, *_ = env.step(agent.predict(observations))
        steps = env.time_step
        grid_charge = 0.0
        for building in env.buildings:
            battery = np.asarray(building.electrical_storage.electricity_consumption[:steps], dtype="float64")
            net = np.asarray(building.net_electricity_consumption[:steps], dtype="float64")
            charge = np.clip(battery, 0.0, None)
            surplus_without_battery = np.clip(battery - net, 0.0, None)
            grid_charge += float(np.sum(charge - np.minimum(charge, surplus_without_battery)))
        assert grid_charge == pytest.approx(0.0, abs=1.0e-6)
    finally:
        env.close()
