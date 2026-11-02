import json
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from citylearn.cost_function import CostFunction
from citylearn.internal.demand_response import (
    CityLearnDemandResponseService,
    DemandResponseRequest,
)
from citylearn.citylearn import CityLearnEnv
from test_demand_response import (
    _copy_minute_schema,
    _clean_schema,
    _write_requests,
    _request,
    _zero_entity_actions,
)


def dr_env(*, seconds=900, topology=None):
    dt = seconds / 3600
    buildings = [
        SimpleNamespace(
            name="a", net_electricity_consumption=np.array([2, 2, 2, 2, 0]) * dt
        ),
        SimpleNamespace(
            name="b", net_electricity_consumption=np.array([2, 2, 2, 2, 5]) * dt
        ),
    ]
    env = SimpleNamespace(
        schema={"demand_response": {"enabled": True, "baseline_window_seconds": 3600}},
        interface="entity",
        time_step=4,
        seconds_per_time_step=seconds,
        buildings=buildings,
        episode_tracker=SimpleNamespace(episode_start_time_step=0),
        net_electricity_consumption=sum(
            b.net_electricity_consumption for b in buildings
        ),
        topology_mode="dynamic" if topology else "static",
        _topology_service=topology,
    )
    service = CityLearnDemandResponseService(env)
    service._requests = [
        DemandResponseRequest("one", "dso", "down", 4, 4, 2.0, 2.0, 5.0, 0.0, 0)
    ]
    return env, service


def test_legacy_discomfort_deltas_condition_on_actual_violations():
    r = CostFunction.discomfort(
        [20, 17, 20, 25], [22] * 4, [20] * 4, band=1, occupant_count=[1, 1, 0, 1]
    )
    assert [r[i][-1] for i in (3, 4, 5, 6, 7, 8)] == pytest.approx([3] * 6)
    assert r[0][-1] == pytest.approx(2 / 3)


def test_legacy_discomfort_rolling_denominator_uses_observed_occupancy():
    result = CostFunction.discomfort(
        [17, 20, 25], [22] * 3, [20] * 3, band=1, occupant_count=[1, 0, 1]
    )
    assert result[0] == pytest.approx([1, 1, 1])


def test_dr_rounds_preparation_up_to_full_requested_duration():
    _, s = dr_env(seconds=2500)
    assert s._baseline_window_steps() == 2


def test_dr_duplicate_ids_are_rejected_before_cache_collision():
    import pandas as pd

    _, s = dr_env()
    with pytest.raises(ValueError, match="duplicate|unique"):
        s._parse_requests(pd.DataFrame([_request(start=4), _request(start=6, end=6)]))


def test_dr_overlaps_cannot_be_silently_dropped_when_flag_enabled():
    import pandas as pd

    _, s = dr_env()
    s.allow_overlapping_requests = True
    s._requests = s._parse_requests(
        pd.DataFrame(
            [_request(start=4, end=6), _request(request_id="other", start=5, end=7)]
        )
    )
    with pytest.raises(
        (ValueError, NotImplementedError), match="(?i)overlap|simultaneous"
    ):
        s._validate_overlaps()


def test_dr_topology_change_does_not_count_as_delivery():
    topology = SimpleNamespace(topology_version_at=lambda t: 0 if t < 3 else 1)
    _, s = dr_env(topology=topology)
    row = s.settle_current_time_step()
    assert not row["baseline_valid"]
    assert row["baseline_reason"] == "topology_changed"
    assert row["revenue_eur"] == row["penalty_eur"] == 0


def test_dr_cached_baseline_is_invalidated_after_topology_change_during_event():
    env, s = dr_env(
        topology=SimpleNamespace(topology_version_at=lambda t: 0 if t < 5 else 1)
    )
    s._requests = [
        DemandResponseRequest("one", "dso", "down", 4, 5, 2.0, 2.0, 5.0, 0.0, 0)
    ]
    assert s.settle_current_time_step()["baseline_valid"]
    env.time_step = 5
    for b in env.buildings:
        b.net_electricity_consumption = np.append(b.net_electricity_consumption, 0.0)
    env.net_electricity_consumption = np.append(env.net_electricity_consumption, 0.0)
    assert not s.settle_current_time_step()["baseline_valid"]
    assert s.audit_summary()["all"]["baseline_coverage_ratio"] == 0.5


def test_dr_missing_baseline_sample_exposes_exclusion_reason():
    env, s = dr_env()
    env.buildings[0].net_electricity_consumption[1] = np.nan
    row = s.settle_current_time_step()
    assert not row["baseline_valid"] and row["baseline_reason"] == "nonfinite_history"


def test_dr_up_cash_is_consistent_with_hand_example():
    _, s = dr_env()
    s._requests = [
        DemandResponseRequest("one", "tso", "up", 4, 4, 2.0, 2.0, 5.0, 0.0, 0)
    ]
    row = s.settle_current_time_step()
    assert row["delivered_kwh"] == 0.25 and row["credited_kwh"] == 0.25
    assert row["shortfall_kwh"] == 0.25 and row["revenue_eur"] == 0.5
    assert row["penalty_eur"] == 1.25 and row["net_revenue_eur"] == -0.75


def test_dr_member_credit_shortfall_are_not_additive_but_cash_is():
    _, s = dr_env()
    row = s.settle_current_time_step()
    a = row["building_allocations"]
    assert row["delivered_kwh"] == pytest.approx(-0.25)
    assert row["credited_kwh"] == 0
    assert row["shortfall_kwh"] == pytest.approx(0.75)
    assert sum(r["credited_kwh"] for r in a) == pytest.approx(0.5)
    assert sum(r["shortfall_kwh"] for r in a) == pytest.approx(1.0)
    assert sum(r["delivered_kwh"] for r in a) == pytest.approx(row["delivered_kwh"])
    assert sum(r["net_revenue_eur"] for r in a) == pytest.approx(row["net_revenue_eur"])


def test_dr_quality_separates_declared_stress_and_unknown_purpose():
    _, s = dr_env()
    row = s.settle_current_time_step()
    s._settlement_by_time_step.clear()
    for i, purpose in enumerate(["service", "stress", "unspecified"]):
        s._settlement_by_time_step[i] = dict(row, purpose=purpose, request_id=str(i))
    report = s.audit_summary()
    assert report["all"]["events_count"] == 3
    for purpose in ("service", "stress", "unspecified"):
        assert report[purpose]["events_count"] == 1
        assert report[purpose]["baseline_coverage_ratio"] == 1
    assert report["service"]["compliance_ratio"] == 0


def test_dr_no_events_has_undefined_compliance_and_coverage():
    _, s = dr_env()
    r = s.audit_summary()["all"]
    assert r["active_intervals_count"] == 0
    assert r["compliance_ratio"] is None and r["baseline_coverage_ratio"] is None


def test_dr_incomplete_history_is_unknown_service_not_a_failure():
    env, s = dr_env()
    env.episode_tracker.episode_start_time_step = 3
    env.time_step = 1
    row = s.settle_current_time_step()
    r = s.audit_summary()["all"]
    assert not row["baseline_valid"]
    assert row["baseline_reason"] == "insufficient_history"
    assert r["baseline_coverage_ratio"] == 0
    assert r["compliance_ratio"] is None
    assert r["requested_kwh"] > 0.0 and r["valid_requested_kwh"] == 0


@pytest.mark.parametrize("purpose", ["service", "stress", "unspecified"])
def test_dr_explicit_purpose_is_parsed_without_inference(purpose):
    import pandas as pd

    _, s = dr_env()
    row = dict(_request(), purpose=purpose)
    assert s._parse_requests(pd.DataFrame([row]))[0].purpose == purpose


def thermal(**kwargs):
    from citylearn.internal.kpi_family_audit import thermal_counts, thermal_metrics

    args = dict(
        temperature=[20, 17, 99, 25],
        cooling=[22] * 4,
        heating=[20] * 4,
        band=1.0,
        occupants=[1, 1, 0, 1],
        expected=np.array([[1, 0, 0, 1]] * 4),
        served=np.array([[1, 0, 0, 1], [0, 0, 0, 1], [5, 0, 0, 0], [1, 0, 0, 0]]),
        outage=[0, 1, 0, 1],
        step_hours=0.25,
    )
    args.update(kwargs)
    return thermal_metrics(thermal_counts(**args))


def test_thermal_independent_counts_energy_and_time():
    r = thermal()
    assert r["discomfort_ratio"] == pytest.approx(2 / 3)
    assert r["outage_discomfort_ratio"] == 1
    assert r["unserved_service_energy_kwh"] == 3
    assert r["expected_service_energy_kwh"] == 8
    assert r["unserved_service_ratio"] == pytest.approx(3 / 8)
    assert r["outage_unserved_service_ratio"] == 0.5
    assert r["cold_degree_hours"] == r["hot_degree_hours"] == 0.75


def test_thermal_oversupply_in_one_service_cannot_cancel_another_shortfall():
    r = thermal(
        expected=np.array([[1, 0, 0, 1]] * 4), served=np.array([[4, 0, 0, 0]] * 4)
    )
    assert r["unserved_service_ratio"] == 0.5


def test_thermal_unknown_and_empty_denominators_are_explicit():
    r = thermal(temperature=[np.nan] * 4)
    assert r["occupied_intervals_count"] == 3
    assert r["evaluated_occupied_intervals_count"] == 0
    assert r["thermal_coverage_ratio"] == 0
    assert r["discomfort_ratio"] is None
    r = thermal(occupants=[0] * 4, expected=np.zeros((4, 4)))
    assert r["discomfort_ratio"] is None and r["unserved_service_ratio"] is None


def test_thermal_unknown_energy_exposes_coverage():
    values = np.ones((4, 4))
    values[1, 0] = np.nan
    r = thermal(expected=values)
    assert r["energy_coverage_ratio"] == 0.75


@pytest.mark.parametrize("seconds", [60, 900, 3600])
def test_service_energy_uses_control_interval_kwh_at_each_resolution(tmp_path, seconds):
    import pandas as pd

    schema = _copy_minute_schema(tmp_path)
    schema["demand_response"]["enabled"] = False
    p = tmp_path / "minute_dr_csv_entity" / "Building_1.csv"
    f = pd.read_csv(p)
    for name in ("cooling_demand", "heating_demand", "dhw_demand"):
        f[name] = 0.0
    f.to_csv(p, index=False)
    env = CityLearnEnv(
        _clean_schema(schema),
        random_seed=0,
        offline=True,
        seconds_per_time_step=seconds,
    )
    try:
        env.reset()
        for _ in range(2):
            env.step(_zero_entity_actions(env))
        actual = float(
            sum(env.buildings[0].non_shiftable_load_device.electricity_consumption[:2])
        )
        r = env.get_kpi_family_audit()["district"]
        assert r["served_service_energy_kwh"] == pytest.approx(actual)
        assert r["expected_service_energy_kwh"] == pytest.approx(actual)
    finally:
        env.close()


def test_thermal_tank_energy_is_already_at_control_scale():
    from citylearn.internal.kpi import CityLearnKPIService

    values = dict(
        name="x",
        time_step_ratio=0.25,
        cooling_demand=[1.0],
        heating_demand=[0.0],
        dhw_demand=[0.0],
        non_shiftable_load=[0.0],
        energy_from_cooling_device=[0.6],
        energy_from_cooling_storage=[0.1],
        energy_from_heating_device=[0.0],
        energy_from_heating_storage=[0.0],
        energy_from_dhw_device=[0.0],
        energy_from_dhw_storage=[0.0],
        energy_to_non_shiftable_load=[0.0],
    )
    b = SimpleNamespace(**values)
    service = CityLearnKPIService(SimpleNamespace(time_step=1, topology_mode="static"))
    expected, served = service._service_energy(b)
    assert expected[0, 0] == 0.25
    assert served[0, 0] == pytest.approx(0.25)


def test_thermal_pooled_ratio_uses_exposure_not_mean_of_member_ratios():
    from citylearn.internal.kpi_family_audit import (
        pool_thermal,
        thermal_counts,
        thermal_metrics,
    )

    def c(temp):
        n = len(temp)
        return thermal_counts(
            temp,
            [22] * n,
            [20] * n,
            1,
            [1] * n,
            np.zeros((n, 4)),
            np.zeros((n, 4)),
            [1] * n,
            0.25,
        )

    r = thermal_metrics(pool_thermal([c([25]), c([20] * 3)]))
    assert r["discomfort_ratio"] == 0.25


def test_equity_coverage_and_positive_benefit_distribution():
    from citylearn.internal.kpi_family_audit import equity_metrics

    r = equity_metrics([(110, 100), (90, 100), (100, 100), (0, 0), (np.nan, 100)])
    assert r["eligible_members_count"] == 3
    assert r["population_members_count"] == 5
    assert r["coverage_ratio"] == 0.6
    assert r["excluded_nonpositive_reference_count"] == 1
    assert r["excluded_unknown_cost_count"] == 1
    assert r["losers_percent"] == pytest.approx(100 / 3)
    assert r["positive_benefit_gini_ratio"] == pytest.approx(2 / 3)
    assert r["positive_benefit_top20_ratio"] == 1


@pytest.mark.parametrize("costs", [[], [(0, 0)], [(2, 1), (3, 1)]])
def test_equity_without_positive_benefit_is_undefined(costs):
    from citylearn.internal.kpi_family_audit import equity_metrics

    r = equity_metrics(costs)
    assert r["positive_benefit_gini_ratio"] is None
    assert r["positive_benefit_top20_ratio"] is None


def test_native_building_band_is_respected(tmp_path):
    import pandas as pd

    schema = _copy_minute_schema(tmp_path)
    schema["demand_response"]["enabled"] = False
    p = tmp_path / "minute_dr_csv_entity" / "Building_1.csv"
    f = pd.read_csv(p)
    f["indoor_dry_bulb_temperature"] = 23.0
    f["indoor_dry_bulb_temperature_cooling_set_point"] = 22.0
    f["indoor_dry_bulb_temperature_heating_set_point"] = 20.0
    f["occupant_count"] = 1.0
    f["comfort_band"] = 0.25
    f.to_csv(p, index=False)
    env = CityLearnEnv(
        _clean_schema(schema),
        simulation_end_time_step=3,
        episode_time_steps=4,
        random_seed=0,
        offline=True,
    )
    try:
        env.reset()
        while not env.terminated:
            env.step(_zero_entity_actions(env))
        k = env.evaluate_v2(include_business_as_usual=False).set_index(
            ["name", "cost_function"]
        )["value"]
        assert (
            k["Building_1", "building_comfort_resilience_discomfort_overall_ratio"] == 1
        )
        assert k["Building_1", "building_thermal_service_audit_discomfort_ratio"] == 1
    finally:
        env.close()


def test_unexecuted_observation_is_excluded_during_partial_episode(tmp_path):
    import pandas as pd

    schema = _copy_minute_schema(tmp_path)
    schema["demand_response"]["enabled"] = False
    p = tmp_path / "minute_dr_csv_entity" / "Building_1.csv"
    f = pd.read_csv(p)
    f["indoor_dry_bulb_temperature"] = 20.0
    f.loc[3, "indoor_dry_bulb_temperature"] = 40.0
    f["indoor_dry_bulb_temperature_cooling_set_point"] = 22.0
    f["indoor_dry_bulb_temperature_heating_set_point"] = 20.0
    f["occupant_count"] = 1.0
    f.to_csv(p, index=False)
    env = CityLearnEnv(_clean_schema(schema), random_seed=0, offline=True)
    try:
        env.reset()
        assert env.get_kpi_family_audit()["district"]["executed_intervals_count"] == 0
        assert env.get_kpi_family_audit()["district"]["discomfort_ratio"] is None
        for _ in range(3):
            env.step(_zero_entity_actions(env))
        k = env.evaluate_v2(include_business_as_usual=False).set_index(
            ["name", "cost_function"]
        )["value"]
        assert (
            k["Building_1", "building_comfort_resilience_discomfort_overall_ratio"] == 0
        )
        assert (
            k["Building_1", "building_thermal_service_audit_executed_intervals_count"]
            == 3
        )
    finally:
        env.close()


def test_equity_audit_uses_explicit_reference_condition(tmp_path):
    from citylearn.citylearn import EvaluationCondition

    schema = _copy_minute_schema(tmp_path)
    schema["demand_response"]["enabled"] = False
    env = CityLearnEnv(_clean_schema(schema), random_seed=0, offline=True)
    try:
        env.reset()
        for _ in range(3):
            env.step(_zero_entity_actions(env))
        condition = EvaluationCondition.WITH_STORAGE_AND_PV
        r = env.get_kpi_family_audit(
            control_condition=condition, baseline_condition=condition
        )
        assert r["equity"]["losers_percent"] == 0
        assert r["equity"]["positive_benefit_gini_ratio"] is None
        assert r["equity_conditions"]["Building_1"]["reference"] == condition.name
    finally:
        env.close()


def test_public_audit_is_read_only_and_does_not_change_reward(tmp_path):
    schema = _copy_minute_schema(tmp_path)
    schema["demand_response"]["enabled"] = False
    env = CityLearnEnv(_clean_schema(schema), random_seed=0, offline=True)
    try:
        env.reset()
        env.step(_zero_entity_actions(env))
        b = env.buildings[0]
        before = (
            b.electrical_storage.soc.copy(),
            env.net_electricity_consumption.copy(),
            env.time_step,
            vars(env.reward_function).copy(),
        )
        first = env.get_kpi_family_audit()
        second = env.get_kpi_family_audit()
        assert first == second
        np.testing.assert_array_equal(before[0], b.electrical_storage.soc)
        np.testing.assert_array_equal(before[1], env.net_electricity_consumption)
        assert before[2] == env.time_step
        assert before[3] == vars(env.reward_function)
    finally:
        env.close()


def test_executed_active_population_and_manifest_survive_reentry(tmp_path):
    from test_independent_balances import scenario, commands
    from citylearn.internal.experiment import experiment_manifest

    events = [
        dict(
            id="out",
            time_step=2,
            operation="remove_member",
            target_member_id="Building_1",
        ),
        dict(
            id="in", time_step=4, operation="add_member", target_member_id="Building_1"
        ),
    ]
    env = scenario(tmp_path, events=events)
    try:
        env.reset()
        while not env.terminated:
            env.step(commands(env, [0.0, 0.0]))
        r = env._kpi_service.family_audit()
        assert r["buildings"]["Building_1"]["executed_intervals_count"] == 5
        assert r["buildings"]["Building_2"]["executed_intervals_count"] == 7
        assert r["district"]["executed_intervals_count"] == 12
        m = experiment_manifest(env)
        assert m["kpi_family_audit"]["definition_version"] == "kpi-families-audit-v1"
        assert (
            m["reward"]["resolved_class"] == "citylearn.reward_function.RewardFunction"
        )
        assert "configured_attributes" in m["reward"]
    finally:
        env.close()
