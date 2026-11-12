"""KPI references must simulate and price the same world as the evaluated control."""

import json
import weakref
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.baseline import CityLearnBusinessAsUsualBaselineService
from citylearn.internal.comparison import configuration_differences, inventory
from test_market_phase_invariants import _rollout_zero_actions, _write_residual_market_schema

BAU_DATASET = 'citylearn_challenge_2023_phase_1'
OVERRIDES = dict(simulate_power_outage=True, inactive_actions=['electrical_storage'], solar_generation=False)
# Per-building lists follow the env's building order: with `buildings=[1, 0]` the first entry is Building_2's.
PER_BUILDING_OVERRIDES = dict(
    simulate_power_outage=[True, False], solar_generation=[False, True], inactive_actions=[['electrical_storage'], []],
)


def _value(frame, cost_function, name='District'):
    rows = frame[(frame['cost_function'] == cost_function) & (frame['name'] == name)]
    assert len(rows) == 1, (cost_function, name)
    return float(rows['value'].iloc[0])


def _business_as_usual_self_comparison(env):
    """BAU ratios and deltas of a `BusinessAsUsualAgent` episode evaluated against the native BAU reference."""
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)

    while not env.terminated:
        observations, *_ = env.step(agent.predict(observations, deterministic=True))

    kpis = env.evaluate_v2()
    names = kpis['cost_function']
    ratios = kpis[names.str.contains('to_business_as_usual') & names.str.endswith('ratio') & ~names.str.contains('delta')]
    deltas = kpis[names.str.contains('delta_to_business_as_usual')]
    return pd.to_numeric(ratios['value'], errors='coerce').dropna(), pd.to_numeric(deltas['value'], errors='coerce').dropna()


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
    ratio_values, delta_values = _business_as_usual_self_comparison(env)

    assert len(ratio_values) > 0 and len(delta_values) > 0
    # Without the overrides the reference kept PV, storage control and grid supply: cost ratio 2.08.
    np.testing.assert_allclose(ratio_values, 1.0, atol=1.0e-6)
    np.testing.assert_allclose(delta_values, 0.0, atol=1.0e-6)


AUTOSIZED_DATASETS = ('tx_travis_county_neighborhood', 'vt_chittenden_county_neighborhood', 'ca_alameda_county_neighborhood')
# What each autosizer resolves (PV is left out: it needs PySAM).
AUTOSIZED_ATTRIBUTES = {
    'cooling_device': ('nominal_power',), 'heating_device': ('nominal_power',), 'dhw_device': ('nominal_power',),
    'cooling_storage': ('capacity',), 'heating_storage': ('capacity',), 'dhw_storage': ('capacity',),
    'electrical_storage': ('capacity', 'nominal_power', 'efficiency', 'depth_of_discharge', 'loss_coefficient',
                           'capacity_loss_coefficient'),
}


def _autosized_equipment(env, schema):
    return [
        (building.name, device, attribute, float(getattr(getattr(building, device), attribute)))
        for building in env.buildings
        for device, attributes in AUTOSIZED_ATTRIBUTES.items()
        if (schema['buildings'][building.name].get(device) or {}).get('autosize')
        for attribute in attributes
    ]


@pytest.mark.parametrize('dataset', AUTOSIZED_DATASETS)
def test_business_as_usual_reference_keeps_equipment_autosized_over_the_loaded_data(dataset):
    path = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / dataset / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    names = [name for name, building in schema['buildings'].items()
             if (building.get('electrical_storage') or {}).get('autosize')][:4]
    assert names, 'dataset no longer autosizes batteries'
    # PV autosizing needs PySAM; batteries, heat pumps and DHW heaters still autosize.
    kwargs = dict(buildings=names, central_agent=True, random_seed=0, solar_generation=False)
    env = CityLearnEnv(schema, episode_time_steps=24, **kwargs)
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0, options={'episode_index': 2})
    start, end = env.episode_tracker.episode_start_time_step, env.episode_tracker.episode_end_time_step
    assert (start, end) == (48, 71)

    # Sizing over the episode alone picks other equipment, as the reference used to.
    episode_only = CityLearnEnv(schema, simulation_start_time_step=start, simulation_end_time_step=end, **kwargs)
    equipment = _autosized_equipment(env, schema)
    assert len(equipment) > 0
    assert _autosized_equipment(episode_only, schema) != equipment

    sidecar = env._business_as_usual_baseline_service._new_sidecar_env()
    sidecar.reset()
    tracker = sidecar.episode_tracker
    assert (tracker.simulation_start_time_step, tracker.simulation_end_time_step) == (0, 8759)
    assert (tracker.episode_start_time_step, tracker.episode_end_time_step) == (start, end)
    assert _autosized_equipment(sidecar, schema) == equipment

    while not env.terminated:
        observations, *_ = env.step(agent.predict(observations, deterministic=True))

    # Raised "Native BAU initial inventory differs from the evaluated episode".
    kpis = env.evaluate_v2()
    cost_functions = kpis['cost_function']
    ratios = kpis[cost_functions.str.contains('to_business_as_usual') & cost_functions.str.endswith('ratio')
                  & ~cost_functions.str.contains('delta')]
    deltas = kpis[cost_functions.str.contains('delta_to_business_as_usual')]
    ratio_values = pd.to_numeric(ratios['value'], errors='coerce').dropna()
    delta_values = pd.to_numeric(deltas['value'], errors='coerce').dropna()

    assert len(ratio_values) > 0 and len(delta_values) > 0
    # Same equipment and the same agent: the reference reproduces the control exactly.
    np.testing.assert_array_equal(ratio_values, 1.0)
    np.testing.assert_array_equal(delta_values, 0.0)


def test_business_as_usual_cache_keeps_only_the_latest_reference():
    env = CityLearnEnv(BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0)
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)
    results = []

    for _ in range(3):
        for _ in range(4):
            observations, *_ = env.step(agent.predict(observations, deterministic=True))

        results.append(env.run_business_as_usual_baseline())
        # Each entry holds a whole sidecar env; earlier time steps are never read again.
        assert list(env._business_as_usual_baseline_cache) == [(env.episode_tracker.episode, env.time_step)]
        assert env.run_business_as_usual_baseline() is results[-1]

    # Results already handed out are left intact.
    assert [(result.time_step, result.env.time_step) for result in results] == [(4, 4), (8, 8), (12, 12)]
    env.reset(seed=0)
    assert env._business_as_usual_baseline_cache == {}


def test_business_as_usual_reference_is_released_before_the_next_one_is_built(monkeypatch):
    env = CityLearnEnv(BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0)
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)
    service = env._business_as_usual_baseline_service
    build = service._new_sidecar_env
    built, alive_at_build = [], []

    def tracked_build():
        alive_at_build.extend(reference() is not None for reference in built)
        sidecar = build()
        built.append(weakref.ref(sidecar))
        return sidecar

    monkeypatch.setattr(service, '_new_sidecar_env', tracked_build)

    for _ in range(3):
        for _ in range(4):
            observations, *_ = env.step(agent.predict(observations, deterministic=True))

        env.run_business_as_usual_baseline()

    # The service's handle on the cache and the envs' reference cycles kept the previous reference
    # alive while the next one was built, so two were held at the peak.
    assert len(built) == 3
    assert alive_at_build == [False, False, False]


def test_business_as_usual_reference_rejects_other_equipment_even_with_the_same_batteries(monkeypatch):
    # The 2020 challenge autosizes heat pumps, heaters and storage tanks, not batteries. Sized over the
    # episode alone, as the reference used to be, they differed silently: the inventory checks batteries.
    monkeypatch.setattr(CityLearnBusinessAsUsualBaselineService, '_autosizes_equipment', staticmethod(lambda *_: False))
    env = CityLearnEnv('citylearn_challenge_2020_climate_zone_1', buildings=['Building_1', 'Building_2'],
                       central_agent=True, episode_time_steps=24, random_seed=0)
    env.reset(seed=0, options={'episode_index': 2})
    sidecar = env._business_as_usual_baseline_service._new_sidecar_env()
    sidecar.reset()
    assert inventory(sidecar) == env._comparison_initial_inventory

    with pytest.raises(ValueError, match=r'equipment differs .* Building_1/cooling_device: nominal_power'):
        env.run_business_as_usual_baseline()


def test_business_as_usual_reference_rejects_devices_changed_after_loading():
    env = CityLearnEnv(BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0)
    building = env.buildings[0]
    # The reference rebuilds devices from the schema, so it would simulate the original heat pump.
    building.cooling_device.nominal_power = building.cooling_device.nominal_power + 1.0
    env.reset(seed=0)
    env.step([[0.0] * len(env.action_names[0])])

    with pytest.raises(ValueError, match=rf'equipment differs .* {building.name}/cooling_device: nominal_power'):
        env.evaluate_v2()

    assert not env.evaluate_v2(include_business_as_usual=False).empty


def test_business_as_usual_reference_loads_only_the_episode_without_autosizing():
    env = CityLearnEnv(BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0)
    env.reset(seed=0, options={'episode_index': 2})
    sidecar = env._business_as_usual_baseline_service._new_sidecar_env()
    sidecar.reset()
    tracker = sidecar.episode_tracker

    # Equipment does not depend on the data here, so the cheaper episode-only load is kept.
    assert (tracker.simulation_start_time_step, tracker.simulation_end_time_step) == (48, 71)
    assert (tracker.episode_start_time_step, tracker.episode_end_time_step) == (48, 71)


@pytest.mark.parametrize('solar_generation', [False, [False, False, False]])
def test_business_as_usual_reference_loads_only_the_episode_when_disabled_pv_is_the_only_autosized_device(
    solar_generation,
):
    path = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / BAU_DATASET / 'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    for building in schema['buildings'].values():
        building['pv']['autosize'] = True

    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=24, random_seed=0, solar_generation=solar_generation)
    env.reset(seed=0, options={'episode_index': 2})
    sidecar = env._business_as_usual_baseline_service._new_sidecar_env()
    sidecar.reset()
    tracker = sidecar.episode_tracker

    # Disabled PV is not loaded and sizes nothing; the reference used to load the source's window, 0 to 719.
    assert (tracker.simulation_start_time_step, tracker.simulation_end_time_step) == (48, 71)
    assert (tracker.episode_start_time_step, tracker.episode_end_time_step) == (48, 71)


def test_autosizing_check_follows_each_buildings_solar_generation_setting():
    schema = {'buildings': {'A': {'pv': {'autosize': True}}, 'B': {'pv': {'autosize': False}}}}
    autosizes = CityLearnBusinessAsUsualBaselineService._autosizes_equipment

    assert autosizes(schema, ['A', 'B'])
    assert not autosizes(schema, ['A', 'B'], False)
    assert not autosizes(schema, ['A', 'B'], [False, True])
    assert autosizes(schema, ['A', 'B'], [True, False])
    # Per-building values follow the evaluated env's building order.
    assert autosizes(schema, ['B', 'A'], [False, True])
    assert not autosizes(schema, ['B', 'A'], [True, False])


def test_business_as_usual_reference_keeps_reversed_building_order_and_per_building_overrides():
    env = CityLearnEnv(
        BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0, buildings=[1, 0], **PER_BUILDING_OVERRIDES,
    )
    first, second = env.buildings
    assert (first.name, second.name) == ('Building_2', 'Building_1')
    assert first.simulate_power_outage and first.pv.nominal_power == 0.0 and 'electrical_storage' not in first.active_actions
    assert not second.simulate_power_outage and second.pv.nominal_power > 0.0 and 'electrical_storage' in second.active_actions

    sidecar = env._business_as_usual_baseline_service._new_sidecar_env()

    # The reference used to load Building_1 first and give it Building_2's outage, PV and storage settings.
    assert [b.name for b in sidecar.buildings] == ['Building_2', 'Building_1']
    for source, reference in zip(env.buildings, sidecar.buildings):
        assert reference.simulate_power_outage == source.simulate_power_outage
        assert reference.active_actions == source.active_actions
        assert reference.pv.nominal_power == source.pv.nominal_power

    ratio_values, delta_values = _business_as_usual_self_comparison(env)

    assert len(ratio_values) > 0 and len(delta_values) > 0
    # Previously 23 of 54 defined ratios differed from one, e.g. Building_2's cost ratio was 1.57.
    np.testing.assert_allclose(ratio_values, 1.0, atol=1.0e-6)
    np.testing.assert_allclose(delta_values, 0.0, atol=1.0e-6)


def test_business_as_usual_reference_in_another_building_order_is_rejected(monkeypatch):
    env = CityLearnEnv(
        BAU_DATASET, central_agent=True, episode_time_steps=24, random_seed=0, buildings=[1, 0], **PER_BUILDING_OVERRIDES,
    )
    # Selecting the reference's buildings by name, as before, loads them in schema order.
    monkeypatch.setattr(type(env._business_as_usual_baseline_service), '_schema_indices', staticmethod(lambda _, names: names))
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)
    env.step(agent.predict(observations, deterministic=True))

    with pytest.raises(ValueError, match=r"building order \(\['Building_2', 'Building_1'\] vs \['Building_1', 'Building_2'\]\)"):
        env.evaluate_v2()


def test_configuration_differences_name_each_changed_setting():
    def row(name, **settings):
        return dict(dict(name=name, simulate_power_outage=False, active_actions=['electrical_storage'], chargers={}), **settings)

    evaluated = [row('Building_1', chargers={'c1': {'max_charging_power': 0.0}}), row('Building_2', simulate_power_outage=True)]
    reference = [row('Building_1', chargers={'c1': {'max_charging_power': 7.2}}), row('Building_2')]

    assert configuration_differences(evaluated, evaluated) == []
    assert configuration_differences(evaluated, reference[::-1]) == [
        "building order (['Building_1', 'Building_2'] vs ['Building_2', 'Building_1'])",
    ]
    assert configuration_differences(evaluated, reference) == [
        'Building_1/charger c1: max_charging_power (0.0 vs 7.2)',
        'Building_2: simulate_power_outage (True vs False)',
    ]


def test_business_as_usual_reference_reports_a_charger_changed_before_reset():
    env = CityLearnEnv('citylearn_challenge_2022_phase_all_plus_evs', central_agent=True, episode_time_steps=24, random_seed=0)
    charger = next(c for b in env.buildings for c in b.electric_vehicle_chargers or [])
    assert charger.max_charging_power > 0.0
    # The reference rebuilds chargers from the schema, so it simulated the schema's limit and charged EVs.
    charger.max_charging_power = 0.0
    agent = BusinessAsUsualAgent(env)
    observations, _ = env.reset(seed=0)
    env.step(agent.predict(observations, deterministic=True))

    with pytest.raises(ValueError, match=rf'{charger.charger_id}: max_charging_power \(0\.0 vs '):
        env.evaluate_v2()

    assert len(env.evaluate_v2(include_business_as_usual=False)) > 0


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
