"""Regressions for the KPI definitions of the 3.6.0 audit (#237, #238, #240, #241, #243, #244, #245)."""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.multi_community import MultiCommunityEnv

ROOT = Path(__file__).resolve().parents[1]
PLUS_EVS = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
DEMAND_RESPONSE = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_demand_response/schema.json"


def _value(kpis: pd.DataFrame, cost_function: str, name: str = "District"):
    rows = kpis[(kpis["cost_function"] == cost_function) & (kpis["name"] == name)]
    assert len(rows) == 1, cost_function
    value = rows["value"].iloc[0]
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else float(value)


def _building_values(kpis: pd.DataFrame, cost_function: str) -> pd.Series:
    rows = kpis[(kpis["cost_function"] == cost_function) & (kpis["level"] == "building")]
    return pd.to_numeric(rows.set_index("name")["value"], errors="coerce")


@pytest.fixture(scope="module")
def random_plus_evs():
    """The #237 and #238 repro: 49 steps of random actions, decentralized."""
    env = CityLearnEnv(str(PLUS_EVS), episode_time_steps=49, central_agent=False, random_seed=0, render_mode="none")
    try:
        env.reset()
        rng = np.random.default_rng(0)
        while not env.terminated:
            env.step([list(rng.uniform(space.low, space.high)) for space in env.action_space])
        kpis = env.evaluate_v2(include_business_as_usual=False)
        legacy = env.evaluate()
        yield env, kpis, legacy
    finally:
        env.close()


def test_district_ratios_to_baseline_are_ratios_of_district_totals(random_plus_evs):
    """#237: the district import, net-exchange and emissions ratios divide district totals."""
    _, kpis, legacy = random_plus_evs
    cases = [
        ("district_energy_grid_ratio_to_baseline_import_total_ratio",
         "district_energy_grid_total_import_control_kwh", "district_energy_grid_total_import_baseline_kwh",
         "building_energy_grid_ratio_to_baseline_import_total_ratio", "electricity_consumption_total", False),
        ("district_energy_grid_ratio_to_baseline_net_exchange_total_ratio",
         "district_energy_grid_total_net_exchange_control_kwh", "district_energy_grid_total_net_exchange_baseline_kwh",
         "building_energy_grid_ratio_to_baseline_net_exchange_total_ratio", "zero_net_energy", True),
        ("district_emissions_ratio_to_baseline_total_ratio",
         "district_emissions_total_control_kgco2", "district_emissions_total_baseline_kgco2",
         "building_emissions_ratio_to_baseline_total_ratio", "carbon_emissions_total", False),
    ]
    differs = False
    for ratio, control, baseline, building_ratio, legacy_name, signed in cases:
        ratio_of_totals = (CityLearnKPIService._signed_ratio if signed else CityLearnKPIService._safe_div)(
            _value(kpis, control), _value(kpis, baseline)
        )
        assert _value(kpis, ratio) == pytest.approx(ratio_of_totals)

        # The 3.6.0 value, the mean of the building ratios, keeps a distinct name
        # and is still the district row of the legacy API.
        stem = ratio[: -len("_ratio")]
        building_mean = _value(kpis, f"{stem}_building_mean_ratio")
        assert building_mean == pytest.approx(_building_values(kpis, building_ratio).mean())
        legacy_district = legacy[(legacy["cost_function"] == legacy_name) & (legacy["level"] == "district")]
        assert float(legacy_district["value"].iloc[0]) == pytest.approx(building_mean)
        differs |= abs(building_mean - ratio_of_totals) > 1.0e-6

    assert differs


def test_district_emissions_follow_the_netted_district_import(random_plus_evs):
    """#238: local sharing between members carries no grid carbon."""
    env, kpis, _ = random_plus_evs
    netted = _value(kpis, "district_emissions_total_control_kgco2")
    member_sum = _value(kpis, "district_emissions_total_control_member_sum_kgco2")

    # The ledger charges carbon only to the external purchase of the district.
    assert netted == pytest.approx(_value(kpis, "district_energy_provenance_external_purchase_emissions_kgco2"), rel=1.0e-5)
    assert member_sum == pytest.approx(_building_values(kpis, "building_emissions_total_control_kgco2").sum(), rel=1.0e-6)
    # Members imported and exported in the same steps, so sharing lowers emissions.
    assert netted < member_sum - 1.0

    steps = int(env.time_step)
    net = np.asarray(env.net_electricity_consumption, dtype="float64")[:steps]
    carbon = np.asarray(env.buildings[0].carbon_intensity.carbon_intensity, dtype="float64")[:steps]
    assert netted == pytest.approx(float(np.sum(np.clip(net, 0.0, None)*carbon)), rel=1.0e-5)
    assert _value(kpis, "district_emissions_total_baseline_member_sum_kgco2") >= _value(kpis, "district_emissions_total_baseline_kgco2")


def test_district_emissions_with_member_specific_carbon_intensity_match_the_ledger(tmp_path):
    """#238: with different carbon intensities the netted emissions follow the provenance ledger."""
    dataset = tmp_path / "plus_evs"
    shutil.copytree(PLUS_EVS.parent, dataset)
    carbon = pd.read_csv(dataset / "carbon_intensity.csv")
    (carbon*3.0).to_csv(dataset / "carbon_intensity_building_1.csv", index=False)
    schema = json.loads((dataset / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset)
    schema["buildings"]["Building_1"]["carbon_intensity"] = "carbon_intensity_building_1.csv"
    env = CityLearnEnv(schema, episode_time_steps=24, central_agent=True, random_seed=0, render_mode="none")
    try:
        env.reset()
        assert env.buildings[0].carbon_intensity.carbon_intensity[0] != env.buildings[1].carbon_intensity.carbon_intensity[0]
        rng = np.random.default_rng(1)
        while not env.terminated:
            env.step([list(rng.uniform(space.low, space.high)) for space in env.action_space])
        kpis = env.evaluate_v2(include_business_as_usual=False)
        assert _value(kpis, "district_emissions_total_control_kgco2") == pytest.approx(
            _value(kpis, "district_energy_provenance_external_purchase_emissions_kgco2"), rel=1.0e-5)
    finally:
        env.close()


def test_building_demand_response_settlement_adds_up_to_the_district():
    """#240: building credit and shortfall respect the district tolerance and cap."""
    env = CityLearnEnv(str(DEMAND_RESPONSE), episode_time_steps=30, render_mode="none")

    def actions(value):
        return {"tables": {name: np.full(space.shape, value, dtype="float32") for name, space in env.action_space["tables"].items()}}

    try:
        env.reset(seed=0)
        while not env.terminated:
            t = int(env.time_step)
            env.step(actions(1.0 if 18 <= t <= 22 else -1.0 if 24 <= t <= 26 else 0.0))

        service = env._demand_response_service
        rows = [row for row in service.settlement_history if row["baseline_valid"]]
        assert len(rows) == 3
        for row in rows:
            allocations = row["building_allocations"]
            for key in ("credited_kwh", "shortfall_kwh", "delivered_kwh", "revenue_eur", "penalty_eur"):
                assert sum(a[key] for a in allocations) == pytest.approx(row[key], abs=1.0e-9)
            assert all(a["credited_kwh"] >= 0.0 and a["shortfall_kwh"] >= 0.0 for a in allocations)
            if row["shortfall_kwh"] == 0.0:
                assert all(a["shortfall_kwh"] == 0.0 for a in allocations)
        # The repro caps the first step at the 20 kW target while members delivered more.
        assert rows[0]["credited_kwh"] == pytest.approx(20.0)
        assert sum(a["uncapped_contribution_kwh"] for a in rows[0]["building_allocations"]) > 20.0

        kpis = env.evaluate_v2(include_business_as_usual=False)
        for suffix in ("shortfall_total_kwh", "delivered_total_kwh", "revenue_total_eur", "penalty_total_eur"):
            assert _building_values(kpis, f"building_demand_response_{suffix}").sum() == pytest.approx(
                _value(kpis, f"district_demand_response_{suffix}"), abs=1.0e-6)
        uncapped = _building_values(kpis, "building_demand_response_uncapped_contribution_total_kwh")
        assert uncapped.sum() > 20.0
        district_compliance = _value(kpis, "district_demand_response_compliance_ratio")
        building_compliance = _building_values(kpis, "building_demand_response_compliance_ratio")
        # Each member is credited against its equal share of the request, so the
        # mean of the member ratios (capped at 1) cannot exceed the district ratio.
        assert building_compliance.mean() <= district_compliance + 1.0e-9
        assert env._demand_response_service.get_metadata()["definition_version"] == "demand-response-audit-v2"
    finally:
        env.close()


def test_load_factor_uses_import_and_leaves_windows_without_import_undefined():
    """#241: a window with no positive peak is undefined, never a perfect 0."""
    lf = CityLearnKPIService._one_minus_load_factor_final

    assert lf([0.0, -2.0, 0.0, 1.0, 2.0, 3.0], window=3) == pytest.approx(1.0/3.0)
    assert CityLearnKPIService._safe_div(lf([0.0, -2.0, 0.0, 1.0, 2.0, 3.0], window=3), 0.5) == pytest.approx(2.0/3.0)
    assert np.isnan(lf([-1.0, -2.0, -3.0], window=3))
    assert CityLearnKPIService._safe_div(lf([-1.0, -2.0, -3.0], window=3), 0.5) is None
    assert lf([5.0, -2.0, 3.0], window=3) == pytest.approx(1.0 - (8.0/3.0)/5.0)

    # The legacy signed-net definition, kept under its own name, is still defined
    # on windows with a positive peak; windows without one are undefined.
    assert lf([5.0, -2.0, 3.0], window=3, signed_net=True) == pytest.approx(1.0 - 2.0/5.0)
    assert np.isnan(lf([0.0, -2.0, 0.0], window=3, signed_net=True))


def test_undefined_values_propagate_through_safe_division():
    """#243: missing values are never read as zero."""
    safe_div = CityLearnKPIService._safe_div
    assert safe_div(None, 2.0) is None
    assert safe_div(2.0, None) is None
    assert safe_div(None, None) is None
    assert safe_div(float("nan"), 1.0) is None
    assert safe_div(float("inf"), 0.5) is None
    assert safe_div(0.0, 0.0) == 1.0
    assert safe_div(0.0, 0.0, zero_over_zero=None) is None
    assert safe_div(1.0, 4.0) == pytest.approx(0.25)
    assert CityLearnKPIService._signed_ratio(None, -2.0) is None


@pytest.fixture(scope="module")
def short_plus_evs_with_bau():
    """The #243 and #245 repro: 4 steps of zero actions, with the BAU reference."""
    env = CityLearnEnv(str(PLUS_EVS), episode_time_steps=4, central_agent=True, random_seed=0, render_mode="none")
    try:
        env.reset()
        while not env.terminated:
            env.step([np.zeros(space.shape, dtype="float32") for space in env.action_space])
        yield env, env.evaluate_v2(include_business_as_usual=True)
    finally:
        env.close()


def test_undefined_deferrable_service_kpis_are_missing(short_plus_evs_with_bau):
    """#243: no completed cycle leaves the start delay and the service comparisons undefined."""
    _, kpis = short_plus_evs_with_bau
    prefix = "district_deferrable_appliance"
    assert _value(kpis, f"{prefix}_service_completed_cycles_count") == 0.0
    assert _value(kpis, f"{prefix}_service_missed_cycles_count") == 0.0
    assert _value(kpis, f"{prefix}_service_average_start_delay_hours") is None
    assert _value(kpis, f"{prefix}_ratio_to_business_as_usual_average_start_delay_ratio") is None
    assert _value(kpis, f"{prefix}_service_service_level_ratio") is None
    assert _value(kpis, f"{prefix}_ratio_to_business_as_usual_service_level_ratio") is None
    assert _value(kpis, f"{prefix}_ratio_to_business_as_usual_missed_cycles_ratio") is None

    # Buildings without a completed cycle report no delay either.
    delays = _building_values(kpis, "building_deferrable_appliance_service_average_start_delay_hours")
    completed = _building_values(kpis, "building_deferrable_appliance_service_completed_cycles_count")
    assert delays[completed == 0.0].isna().all()


def test_business_as_usual_ramping_average_is_a_mean_per_step():
    """#245: the average divides the episode sum by the step transitions; the sum keeps its own name."""
    env = CityLearnEnv(str(PLUS_EVS), episode_time_steps=24, central_agent=True, random_seed=0, render_mode="none")
    try:
        env.reset()
        while not env.terminated:
            env.step([np.zeros(space.shape, dtype="float32") for space in env.action_space])
        kpis = env.evaluate_v2(include_business_as_usual=True)
    finally:
        env.close()
    stem = "district_energy_grid_shape_quality_ramping"
    average = _value(kpis, f"{stem}_average_business_as_usual_kw")
    total = _value(kpis, f"{stem}_total_business_as_usual_kw")
    transitions = int(env.time_step) - 1
    assert total > 0.0
    assert average == pytest.approx(total/transitions)
    assert _value(kpis, f"{stem}_average_delta_to_business_as_usual_kw") == pytest.approx(
        _value(kpis, f"{stem}_total_delta_to_business_as_usual_kw")/transitions)
    assert CityLearnKPIService._ramping_mean([0.0, 2.0, 1.0, 4.0]) == pytest.approx(5.0/3.0)
    assert CityLearnKPIService._ramping_mean([3.0]) is None


def test_portfolio_rates_are_pooled_from_their_denominators():
    """#244: a two-community portfolio weights rates by counts, not by community."""
    district = pd.DataFrame([
        {"community_id": "big", "cost_function": "district_ev_performance_departure_success_ratio", "value": 1.0},
        {"community_id": "big", "cost_function": "district_ev_events_departure_count", "value": 14.0},
        {"community_id": "small", "cost_function": "district_ev_performance_departure_success_ratio", "value": 0.0},
        {"community_id": "small", "cost_function": "district_ev_events_departure_count", "value": 2.0},
    ])
    district["numeric_value"] = district["value"]
    weights = CityLearnKPIService.pooled_mean_components("district")["district_ev_performance_departure_success_ratio"]
    assert MultiCommunityEnv._pooled_mean(district, "district_ev_performance_departure_success_ratio", weights) == pytest.approx(14.0/16.0)


def _community(community_id, weight):
    return {
        "community_id": community_id,
        "schema": str(PLUS_EVS),
        "weight": weight,
        "env_kwargs": {"central_agent": True, "episode_time_steps": 24, "render_mode": "none", "random_seed": 0},
    }


def test_portfolio_self_consumption_and_service_levels_match_portfolio_totals():
    """#244: pooled portfolio ratios agree with the portfolio's own totals."""
    env = MultiCommunityEnv(communities=[_community("a", 1.0), _community("b", 3.0)])
    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step({
                "a": [np.zeros(space.shape, dtype="float32") for space in env.envs["a"].action_space],
                "b": [np.ones(space.shape, dtype="float32") for space in env.envs["b"].action_space],
            })
        kpis = env.evaluate_v2(include_business_as_usual=True)
        portfolio = kpis[kpis["level"] == "portfolio"]

        def total(name):
            return _value(portfolio, f"portfolio_{name}", MultiCommunityEnv.PORTFOLIO_NAME)

        generation = total("solar_self_consumption_total_generation_kwh")
        assert generation > 0.0
        expected = (generation - total("solar_self_consumption_total_export_kwh")
                    - total("solar_self_consumption_total_curtailment_kwh"))/generation
        assert total("solar_self_consumption_ratio_self_consumption_ratio") == pytest.approx(expected)

        departures = total("ev_events_departure_count")
        success = total("ev_performance_departure_success_ratio")
        if departures > 0:
            assert success == pytest.approx(total("ev_events_departure_met_count")/departures)
        else:
            assert success is None

        due = total("deferrable_appliance_service_completed_cycles_count") + total("deferrable_appliance_service_missed_cycles_count")
        level = total("deferrable_appliance_service_service_level_ratio")
        if due > 0:
            assert level == pytest.approx(total("deferrable_appliance_service_completed_cycles_count")/due)
        else:
            assert level is None

        bau = total("solar_self_consumption_ratio_self_consumption_business_as_usual_ratio")
        control = total("solar_self_consumption_ratio_self_consumption_ratio")
        assert total("solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio") == pytest.approx(control - bau)
        assert total("solar_self_consumption_ratio_to_business_as_usual_self_consumption_ratio") == pytest.approx(control/bau)
    finally:
        env.close()


ELECTRICAL_SERVICE = ROOT / "data/datasets/citylearn_three_phase_electrical_service_demo/schema.json"


def _entity_portfolio(schema, episode_time_steps, policies):
    """Run a two-community portfolio on the entity interface; `policies` maps community -> (weight, action of t)."""
    env = MultiCommunityEnv(communities=[
        {
            "community_id": community_id,
            "schema": str(schema),
            "weight": weight,
            "env_kwargs": {"episode_time_steps": episode_time_steps, "render_mode": "none", "random_seed": 0},
        }
        for community_id, (weight, _) in policies.items()
    ])
    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step({
                community_id: {"tables": {
                    name: np.full(space.shape, policy(int(env.envs[community_id].time_step)), dtype="float32")
                    for name, space in env.envs[community_id].action_space["tables"].items()
                }}
                for community_id, (_, policy) in policies.items()
            })
        kpis = env.evaluate_v2(include_business_as_usual=False)
    finally:
        env.close()
    return kpis[kpis["level"] == "portfolio"], kpis[kpis["level"] == "district"]


def test_portfolio_demand_response_compliance_is_pooled_from_energy():
    """#285: portfolio DR compliance is credited over valid requested energy of the whole portfolio."""
    portfolio, district = _entity_portfolio(DEMAND_RESPONSE, 30, {
        "delivers": (1.0, lambda t: 1.0 if 18 <= t <= 22 else -1.0 if 24 <= t <= 26 else 0.0),
        "idle": (3.0, lambda t: 0.0),
    })

    def total(name):
        return _value(portfolio, f"portfolio_{name}", MultiCommunityEnv.PORTFOLIO_NAME)

    for community_id in ("delivers", "idle"):
        rows = district[district["community_id"] == community_id]
        credited = _value(rows, "district_demand_response_credited_total_kwh")
        valid = _value(rows, "district_demand_response_valid_requested_total_kwh")
        assert valid > 0.0
        assert _value(rows, "district_demand_response_compliance_ratio") == pytest.approx(credited/valid)

    credited, valid = total("demand_response_credited_total_kwh"), total("demand_response_valid_requested_total_kwh")
    compliance = total("demand_response_compliance_ratio")
    assert compliance == pytest.approx(credited/valid)
    community = {
        cid: _value(district[district["community_id"] == cid], "district_demand_response_compliance_ratio")
        for cid in ("delivers", "idle")
    }
    # The two communities differ, so the old community-weighted mean would give another value.
    assert community["delivers"] != pytest.approx(community["idle"])
    assert compliance != pytest.approx((community["delivers"] + 3.0*community["idle"])/4.0)
    audit = "demand_response_audit_all"
    assert total(f"{audit}_compliance_ratio") == pytest.approx(total(f"{audit}_credited_kwh")/total(f"{audit}_valid_requested_kwh"))
    assert total(f"{audit}_requested_energy_coverage_ratio") == pytest.approx(
        total(f"{audit}_valid_requested_kwh")/total(f"{audit}_requested_kwh"))
    assert total(f"{audit}_baseline_coverage_ratio") == pytest.approx(
        total(f"{audit}_valid_intervals_count")/total(f"{audit}_active_intervals_count"))


def test_portfolio_community_market_shares_are_pooled_from_energy():
    """#285: portfolio local shares are local over local plus grid energy of the whole portfolio."""
    portfolio, district = _entity_portfolio(ELECTRICAL_SERVICE, 24, {
        "idle": (1.0, lambda t: 0.0),
        "charging": (3.0, lambda t: 1.0),
    })

    def total(name):
        return _value(portfolio, f"portfolio_{name}", MultiCommunityEnv.PORTFOLIO_NAME)

    market = "energy_grid_community_market"
    local_import, grid_import = total(f"{market}_local_import_total_kwh"), total(f"{market}_grid_import_after_local_total_kwh")
    local_export, grid_export = total(f"{market}_local_export_total_kwh"), total(f"{market}_grid_export_after_local_total_kwh")
    assert local_import > 0.0
    demand_share = local_import/(local_import + grid_import)
    assert total("solar_self_consumption_community_market_local_share_of_demand_ratio") == pytest.approx(demand_share)
    assert total("solar_self_consumption_community_market_import_share_ratio") == pytest.approx(demand_share)
    assert total("solar_self_consumption_community_market_local_share_of_export_ratio") == pytest.approx(
        local_export/(local_export + grid_export))
    shares = [
        _value(district[district["community_id"] == cid], "district_solar_self_consumption_community_market_local_share_of_demand_ratio")
        for cid in ("idle", "charging")
    ]
    assert shares[0] != pytest.approx(shares[1])
    assert demand_share != pytest.approx((shares[0] + 3.0*shares[1])/4.0)


def _residual_market_kpis(tmp_path, *, local_trading, ratio=0.8):
    from test_market_phase_invariants import _rollout_zero_actions, _write_residual_market_schema

    path = _write_residual_market_schema(tmp_path)
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(path.parent)
    schema["community_market"].update(local_trading_enabled=local_trading, intra_community_sell_ratio=ratio)
    env = CityLearnEnv(schema, central_agent=True, random_seed=0)
    try:
        _rollout_zero_actions(env)
        imports = [
            sum(max(float(b.net_electricity_consumption[t]), 0.0)*float(b.carbon_intensity.carbon_intensity[t])
                for b in env.buildings)
            for t in range(env.time_step)
        ]
        return env.evaluate_v2(include_business_as_usual=False), float(sum(imports))
    finally:
        env.close()


@pytest.mark.parametrize("local_trading", [True, False])
def test_district_emissions_follow_the_local_exchange_switch(tmp_path, local_trading):
    """#327: with local trading off, no energy is shared, so district emissions are the member imports'."""
    kpis, member_imports = _residual_market_kpis(tmp_path, local_trading=local_trading)
    emissions = _value(kpis, "district_emissions_total_control_kgco2")
    assert emissions == pytest.approx(
        _value(kpis, "district_energy_provenance_external_purchase_emissions_kgco2"), rel=1.0e-6, abs=1.0e-9)
    if local_trading:
        assert emissions < member_imports - 0.1
    else:
        assert emissions == pytest.approx(member_imports, rel=1.0e-9)
        assert emissions == pytest.approx(_value(kpis, "district_emissions_total_control_member_sum_kgco2"), rel=1.0e-9)


@pytest.mark.parametrize("local_trading", [True, False])
def test_district_emissions_do_not_depend_on_the_local_price_ratio(tmp_path, local_trading):
    """#327: the local price ratio only prices the exchange; it never changes the emissions."""
    values = []
    for ratio in (0.5, 0.8, 1.0):
        kpis, _ = _residual_market_kpis(tmp_path / str(ratio), local_trading=local_trading, ratio=ratio)
        values.append((
            _value(kpis, "district_emissions_total_control_kgco2"),
            _value(kpis, "district_energy_provenance_external_purchase_emissions_kgco2"),
        ))
    assert all(v == pytest.approx(values[0], rel=1.0e-12) for v in values[1:])
