"""Action names reach `Building.apply_actions` through one routing rule (#467).

Every bundled action layout is parsed by the flat parser, the entity flat-vector parser and the entity table
parser, and each result is compared with the same reference. The robustness validation must expose exactly
the action targets that the runtime then offers to action events.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from private_access import entity_service, robustness_service, runtime_service

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.actions import building_action_kwargs, zero_building_action_kwargs
from citylearn.internal.capabilities import unsupported_reason

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'datasets'
MINUTE_DATASET = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'
ESCALATOR_LAYOUT = 'minute_ev_demo+escalator'


def _active_actions(schema: dict) -> tuple:
    return tuple(sorted(k for k, v in (schema.get('actions') or {}).items() if (v or {}).get('active')))


def _bundled_layouts() -> dict:
    """One static-topology dataset per distinct set of active actions, plus the flat EV fixture."""

    candidates = [(path.name, path) for path in sorted(DATASETS.iterdir()) if (path / 'schema.json').is_file()]
    candidates.append(('minute_ev_demo', MINUTE_DATASET))
    layouts = {}
    for name, path in candidates:
        schema = json.loads((path / 'schema.json').read_text(encoding='utf-8'))
        if schema.get('topology_mode', 'static') == 'dynamic':
            continue
        layouts.setdefault(_active_actions(schema), name)
    return {name: key for key, name in layouts.items()}


LAYOUTS = _bundled_layouts()


def _escalator_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / 'escalator'
    shutil.copytree(MINUTE_DATASET, dataset)
    steps = len(pd.read_csv(dataset / 'Building_1.csv'))
    pd.DataFrame({
        'time_step': range(steps),
        'passengers_from_trains_15min': [10.0] * steps,
        'background_pedestrians_15min': [2.0] * steps,
        'passengers_expected_15min': [12.0] * steps,
        'people_detected': [1.0] * steps,
        'arriving_trains': [1.0] * steps,
        'departing_trains': [0.0] * steps,
        'minutes_to_next_train': [5.0] * steps,
        'available': [1.0] * steps,
    }).to_csv(dataset / 'escalator.csv', index=False)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    schema['actions']['escalator'] = {'active': True}
    schema['buildings']['Building_1']['escalators'] = {'esc_1': {'simulation': 'escalator.csv', 'attributes': {
        'standby_power': 0.5, 'slow_power': 2.0, 'normal_power': 4.0}}}
    (dataset / 'schema.json').write_text(json.dumps(schema, indent=2), encoding='utf-8')
    return dataset


def _schema(name: str, tmp_path: Path, interface: str) -> dict:
    if name == ESCALATOR_LAYOUT:
        path = _escalator_dataset(tmp_path)
    elif name == 'minute_ev_demo':
        path = MINUTE_DATASET
    else:
        path = DATASETS / name
    schema = json.loads((path / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(path)
    schema['interface'] = interface
    # Two members are enough to cover a layout and keep construction short.
    for index, building in enumerate(schema['buildings'].values()):
        building['include'] = index < 2
    return schema


def _env(name: str, tmp_path: Path, interface: str):
    schema = _schema(name, tmp_path, interface)
    if unsupported_reason(schema, interface) is not None:
        return None
    env = CityLearnEnv(schema, central_agent=False, episode_time_steps=2, random_seed=0)
    env.reset(seed=0)
    return env


def _vectors(env: CityLearnEnv) -> list:
    rng = np.random.default_rng(467)
    # Values beyond the bounds as well, so clipping is part of what is compared.
    return [
        rng.uniform(space.low - 0.25, space.high + 0.25).astype('float32').tolist()
        for space in env.action_space
    ]


def _reference(env: CityLearnEnv, vectors: list) -> list:
    """The routing rule written out independently of the library helper."""

    parsed = []
    for building, vector in zip(env.buildings, vectors):
        values = np.clip(vector, building.action_space.low, building.action_space.high)
        kwargs, ev, deferrable, escalator = {}, {}, {}, {}
        for name, value in zip(building.active_actions, values):
            if name.startswith('electric_vehicle_storage_'):
                ev[name[len('electric_vehicle_storage_'):]] = float(value)
            elif name.startswith('deferrable_appliance_'):
                deferrable[name] = float(value)
            elif name.startswith('escalator_'):
                escalator[name] = float(value)
            else:
                kwargs[f'{name}_action'] = float(value)
        for key, group in (
            ('electric_vehicle_storage_actions', ev),
            ('deferrable_appliance_actions', deferrable),
            ('escalator_actions', escalator),
        ):
            if group:
                kwargs[key] = group
        parsed.append(kwargs)
    return parsed


def _flatten(parsed: list) -> dict:
    flat = {}
    for index, kwargs in enumerate(parsed):
        for key, value in kwargs.items():
            if isinstance(value, dict):
                for inner, inner_value in value.items():
                    flat[(index, key, inner)] = float(inner_value)
            else:
                flat[(index, key)] = float(value)
    return flat


def _tables(env: CityLearnEnv, vectors: list) -> dict:
    service = entity_service(env)
    tables = {name: np.zeros(space.shape, dtype='float32') for name, space in env.action_space['tables'].items()}
    for building_index, (building, vector) in enumerate(zip(env.buildings, vectors)):
        for name, value in zip(building.active_actions, vector):
            if name in service._building_action_col_by_name:
                tables['building'][building_index, service._building_action_col_by_name[name]] = value
            elif name.startswith('electric_vehicle_storage_'):
                tables['charger'][service._charger_row_by_ev_action_name[(building_index, name)], 0] = value
            elif name.startswith('deferrable_appliance_'):
                row = service._deferrable_appliance_row_by_action_name[(building_index, name)]
                tables['deferrable_appliance'][row, 0] = value
            else:
                raise AssertionError(f'No entity table column for action {name!r}.')
    return {'tables': tables}


def _target_keys(descriptors) -> list:
    return sorted(descriptor['target_key'] for descriptor in descriptors)


def test_bundled_layouts_cover_every_device_action():
    names = {name for layout in LAYOUTS.values() for name in layout}
    assert {
        'cooling_or_heating_device', 'cooling_device', 'heating_device', 'cooling_storage', 'dhw_storage',
        'electrical_storage', 'electric_vehicle_storage', 'deferrable_appliance',
    } <= names


@pytest.mark.parametrize('name', sorted(LAYOUTS) + [ESCALATOR_LAYOUT])
def test_every_parser_routes_a_layout_the_same_way(name: str, tmp_path: Path):
    if name == 'ca_alameda_county_neighborhood':
        # This dataset sizes its PV with PySAM, which has no wheel for every Python version.
        pytest.importorskip('PySAM')
    flat_env = _env(name, tmp_path / 'flat', 'flat')
    try:
        vectors = _vectors(flat_env)
        reference = _flatten(_reference(flat_env, vectors))
        flat_parsed = runtime_service(flat_env).parse_actions(vectors)
        assert _flatten(flat_parsed) == pytest.approx(reference)

        # Validation and runtime expose the same action targets, so a validated event can reach its action.
        robustness = robustness_service(flat_env)
        assert _target_keys(robustness._validation_action_descriptors()) == _target_keys(
            robustness._action_descriptors(flat_parsed)
        )
    finally:
        flat_env.close()

    entity_env = _env(name, tmp_path / 'entity', 'entity')
    if entity_env is None:
        assert name == ESCALATOR_LAYOUT
        return
    try:
        assert _flatten(entity_service(entity_env).parse_actions(vectors)) == pytest.approx(reference)
        assert _flatten(entity_service(entity_env).parse_actions(_tables(entity_env, vectors))) == pytest.approx(
            reference
        )
    finally:
        entity_env.close()


def test_routing_matches_prefixes_and_keeps_charger_ids_whole():
    kwargs = building_action_kwargs(
        [
            'electrical_storage',
            'electric_vehicle_storage_electric_vehicle_storage_1',
            'deferrable_appliance_washer',
            'escalator_esc_1',
        ],
        [0.1, 0.2, 0.3, 0.4],
    )
    assert kwargs == {
        'electrical_storage_action': 0.1,
        'electric_vehicle_storage_actions': {'electric_vehicle_storage_1': 0.2},
        'deferrable_appliance_actions': {'deferrable_appliance_washer': 0.3},
        'escalator_actions': {'escalator_esc_1': 0.4},
    }
    assert zero_building_action_kwargs(['cooling_device']) == {'cooling_device_action': 0.0}
    assert building_action_kwargs([], []) == {}


def test_flat_charger_whose_id_repeats_the_action_prefix_is_controlled(tmp_path: Path):
    dataset = tmp_path / 'prefixed_charger'
    shutil.copytree(MINUTE_DATASET, dataset)
    schema = json.loads((dataset / 'schema.json').read_text(encoding='utf-8'))
    chargers = schema['buildings']['Building_1']['chargers']
    chargers['electric_vehicle_storage_1'] = chargers.pop('charger_1_1')
    schema['root_directory'] = str(dataset)
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=2, random_seed=0)
    try:
        env.reset(seed=0)
        names = env.action_names[0]
        assert 'electric_vehicle_storage_electric_vehicle_storage_1' in names
        action = np.zeros(len(names), dtype='float32')
        action[names.index('electric_vehicle_storage_electric_vehicle_storage_1')] = 0.5
        parsed = runtime_service(env).parse_actions([action.tolist()])
        assert parsed[0]['electric_vehicle_storage_actions'] == {'electric_vehicle_storage_1': pytest.approx(0.5)}
        env.step([action.tolist()])
    finally:
        env.close()


def test_flat_robustness_action_event_reaches_an_escalator(tmp_path: Path):
    schema = _schema(ESCALATOR_LAYOUT, tmp_path, 'flat')
    dataset = Path(schema['root_directory'])
    pd.DataFrame([{
        'event_id': 'escalator_dropout',
        'module': 'action',
        'target_type': 'building',
        'target_id': 'Building_1',
        'target_feature': 'escalator_esc_1',
        'start_time_step': 0,
        'end_time_step': 0,
        'mode': 'dropout',
    }]).to_csv(dataset / 'robustness_events.csv', index=False)
    schema['robustness'] = {
        'enabled': True,
        'events_file': 'robustness_events.csv',
        'random_seed': 7,
        'modules': {name: {'enabled': True} for name in ('observations', 'forecasts', 'actions', 'assets')},
    }
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=2, random_seed=0)
    try:
        env.reset(seed=0)
        names = env.action_names[0]
        action = np.zeros(len(names), dtype='float32')
        action[names.index('escalator_esc_1')] = 1.0
        parsed = runtime_service(env).parse_actions([action.tolist()])
        applied = robustness_service(env).apply_actions(parsed)
        assert parsed[0]['escalator_actions'] == {'escalator_esc_1': pytest.approx(1.0)}
        assert applied[0]['escalator_actions'] == {'escalator_esc_1': 0.0}

        env.step([action.tolist()])
        escalator = env.buildings[0].escalators[0]
        assert escalator.requested_state_history[0] == escalator.STATE_STANDBY
    finally:
        env.close()
