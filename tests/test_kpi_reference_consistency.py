"""KPI references must simulate and price the same world as the evaluated control."""

import json

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.citylearn import CityLearnEnv
from test_market_phase_invariants import _rollout_zero_actions, _write_residual_market_schema

BAU_DATASET = 'citylearn_challenge_2023_phase_1'
OVERRIDES = dict(simulate_power_outage=True, inactive_actions=['electrical_storage'], solar_generation=False)


def _value(frame, cost_function, name='District'):
    rows = frame[(frame['cost_function'] == cost_function) & (frame['name'] == name)]
    assert len(rows) == 1, (cost_function, name)
    return float(rows['value'].iloc[0])


def test_business_as_usual_sidecar_reapplies_constructor_overrides():
    env = CityLearnEnv(BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0, **OVERRIDES)
    sidecar = env._business_as_usual_baseline_service._new_sidecar_env()

    for source, reference in zip(env.buildings, sidecar.buildings):
        assert reference.simulate_power_outage == source.simulate_power_outage is True
        assert reference.active_actions == source.active_actions
        assert 'electrical_storage' not in reference.active_actions
        assert reference.pv.nominal_power == source.pv.nominal_power == 0.0


def test_business_as_usual_agent_scores_one_against_its_own_reference():
    env = CityLearnEnv(BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0, **OVERRIDES)
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)

    while not env.terminated:
        observations, *_ = env.step(agent.predict(observations, deterministic=True))

    kpis = env.evaluate_v2()
    names = kpis['cost_function']
    ratios = kpis[names.str.contains('to_business_as_usual') & names.str.endswith('ratio') & ~names.str.contains('delta')]
    deltas = kpis[names.str.contains('delta_to_business_as_usual')]
    ratio_values = pd.to_numeric(ratios['value'], errors='coerce').dropna()
    delta_values = pd.to_numeric(deltas['value'], errors='coerce').dropna()

    assert len(ratio_values) > 0 and len(delta_values) > 0
    # Without the overrides the reference kept PV, storage control and grid supply: cost ratio 2.08.
    np.testing.assert_allclose(ratio_values, 1.0, atol=1.0e-6)
    np.testing.assert_allclose(delta_values, 0.0, atol=1.0e-6)


@pytest.fixture
def market_env_with_identical_flows(tmp_path):
    """Two-member market without storage: control and reference flows are identical."""
    path = _write_residual_market_schema(tmp_path)
    schema = json.loads(path.read_text())
    schema['root_directory'] = str(path.parent)
    env = CityLearnEnv(schema, central_agent=True, random_seed=0)
    _rollout_zero_actions(env)
    building = env.buildings[0]
    np.testing.assert_array_equal(
        building.net_electricity_consumption, building.net_electricity_consumption_without_storage,
    )
    return env


def test_market_legacy_cost_compares_settled_control_with_settled_reference(market_env_with_identical_flows):
    env = market_env_with_identical_flows
    importer = env.buildings[0]
    settled = float(np.sum(importer.net_electricity_consumption_cost[:env.time_step]))
    unsettled = float(np.sum(importer.net_electricity_consumption_cost_without_storage[:env.time_step]))
    assert settled < unsettled  # the market lowers the importer's bill

    legacy = env.evaluate()

    # Previously settled/unsettled, i.e. the market's saving was credited to the controller.
    assert _value(legacy, 'cost_total', importer.name) == pytest.approx(1.0)
    assert _value(legacy, 'cost_total') == pytest.approx(1.0)


def test_market_equity_audit_sees_no_benefit_for_identical_flows(market_env_with_identical_flows):
    equity = market_env_with_identical_flows.get_kpi_family_audit()['equity']

    assert equity['losers_percent'] == 0.0
    assert equity['positive_benefit_gini_ratio'] is None


def test_market_v2_and_legacy_settled_costs_agree(market_env_with_identical_flows):
    env = market_env_with_identical_flows
    v2 = env.evaluate_v2(include_business_as_usual=False)

    assert _value(v2, 'district_cost_ratio_to_baseline_total_ratio') == pytest.approx(1.0)
    assert _value(v2, 'district_cost_total_baseline_eur') == pytest.approx(_value(v2, 'district_cost_total_control_eur'))
