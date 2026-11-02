"""Contracts at the KPI, entity-snapshot and component-loading boundaries."""

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_independent_balances import scenario

from citylearn import energy_model
from citylearn.citylearn import CityLearnEnv
from scripts.audit.audit_refactor_parity import _commands

SCHEMA = (Path(__file__).resolve().parent / 'data/minute_ev_demo/schema.json').resolve(strict=True)


@pytest.mark.parametrize('keys,type_name', [
    (('type',), 'Building'),
    (('chargers', 'charger_1_1', 'type'), 'missing_c5_package.Charger'),
    (('chargers', 'charger_1_1', 'type'), 'math.pi'),
    (('electrical_storage', 'type'), 'citylearn.energy_model.MissingBattery'),
    (('pv', 'type'), 'types.MissingPV'),
    (('dynamics', 'type'), 'types.MissingDynamics'),
    (('occupant', 'type'), 'types.MissingOccupant'),
    (('power_outage', 'stochastic_power_outage_model', 'type'), 'types.MissingOutage'),
])
def test_component_configuration_errors_identify_the_schema_path(keys, type_name):
    schema = json.loads(SCHEMA.read_text())
    schema['root_directory'] = str(SCHEMA.parent)
    config = schema['buildings']['Building_1']
    for key in keys[:-1]:
        config = config.setdefault(key, {})
    config[keys[-1]] = type_name
    with pytest.raises(ValueError) as error:
        CityLearnEnv(schema, episode_time_steps=3, random_seed=0, offline=True,
                     render_mode='none', export_kpis_on_episode_end=False)
    assert 'buildings.Building_1.' + '.'.join(keys) in str(error.value)
    assert type_name in str(error.value)
    if type_name not in {'Building', 'math.pi'}:
        assert isinstance(error.value.__cause__, (ImportError, AttributeError))


def test_component_constructor_failure_is_not_replaced_by_a_default(monkeypatch):
    calls = []

    class ExplodingBattery:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError('equipment constructor failed')

    monkeypatch.setattr(energy_model, 'ExplodingBattery', ExplodingBattery, raising=False)
    schema = json.loads(SCHEMA.read_text())
    schema['root_directory'] = str(SCHEMA.parent)
    schema['buildings']['Building_1']['electrical_storage']['type'] = 'citylearn.energy_model.ExplodingBattery'
    with pytest.raises(RuntimeError, match='^equipment constructor failed$') as error:
        CityLearnEnv(schema, episode_time_steps=3, random_seed=0, offline=True,
                     render_mode='none', export_kpis_on_episode_end=False)
    assert len(calls) == 1
    assert error.value.__cause__ is None


def fixture_schema(tmp_path, interface, dynamic=False):
    initial = scenario(tmp_path, phase_limits=True)
    schema = deepcopy(initial.schema)
    initial.close()
    schema['interface'] = interface
    if dynamic:
        schema.update(topology_mode='dynamic', topology_events=[
            dict(id='leave', time_step=1, operation='remove_member', target_member_id='Building_2'),
        ])
    return schema


@pytest.mark.parametrize('dynamic', [False, True])
def test_entity_payload_copies_survive_later_observations_and_topology_changes(tmp_path, dynamic):
    env = CityLearnEnv(fixture_schema(tmp_path, 'entity', dynamic), random_seed=0,
                       physics_invariant_checks=True, export_kpis_on_episode_end=False, render_mode='none')
    try:
        first, _ = env.reset(seed=0)
        second = env.observations
        saved = deepcopy(second)
        for section in ('tables', 'edges'):
            for name, values in first[section].items():
                assert not np.shares_memory(values, second[section][name])
                values.fill(12345)
        third = env.observations
        for section in ('tables', 'edges'):
            for name, values in second[section].items():
                np.testing.assert_array_equal(values, saved[section][name])
                np.testing.assert_array_equal(third[section][name], saved[section][name])
        env.step(_commands(env))
        assert len(env.entity_specs['tables']['building']['ids']) == (1 if dynamic else 2)
        assert second['tables']['building'].shape[0] == 2
        for section in ('tables', 'edges'):
            for name, values in second[section].items():
                np.testing.assert_array_equal(values, saved[section][name])
    finally:
        env.close()


@pytest.mark.parametrize('interface', ['flat', 'entity'])
def test_kpi_family_aggregation_is_isolated_across_calls_and_reset(tmp_path, interface):
    env = CityLearnEnv(fixture_schema(tmp_path, interface), random_seed=0,
                       physics_invariant_checks=True, export_kpis_on_episode_end=False, render_mode='none')
    try:
        env.reset(seed=0)
        empty = env.evaluate_v2(include_business_as_usual=False)
        for _ in range(2):
            env.step(_commands(env))
        measured = env.evaluate_v2(include_business_as_usual=False)
        assert measured.loc[measured.cost_function == 'district_battery_total_throughput_kwh', 'value'].iloc[0] > 0.
        altered = env.evaluate_v2(include_business_as_usual=False)
        altered.loc[:, 'value'] = -12345.
        pd.testing.assert_frame_equal(measured, env.evaluate_v2(include_business_as_usual=False), check_exact=True)
        env.reset(seed=0)
        pd.testing.assert_frame_equal(empty, env.evaluate_v2(include_business_as_usual=False), check_exact=True)
        for _ in range(2):
            env.step(_commands(env))
        pd.testing.assert_frame_equal(measured, env.evaluate_v2(include_business_as_usual=False), check_exact=True)
    finally:
        env.close()
