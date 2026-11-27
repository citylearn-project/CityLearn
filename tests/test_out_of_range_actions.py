"""Actions outside `action_space` follow one rule in both interfaces: they are clipped to the space.

Entity table and map payloads were clipped to the action space, while flat actions, and flat vectors sent to an
entity environment, reached the devices as given. On `citylearn_challenge_2020_climate_zone_1` the thermal storage
then charged or discharged beyond the bounds the space advertises, so the same request gave a different simulation
depending on the payload. Actions inside the space must still reach the devices bit for bit as sent.
"""

from pathlib import Path

import numpy as np
import pytest

from citylearn.agents.rbc import BasicBatteryRBC, BasicRBC, OptimizedRBC
from citylearn.citylearn import CityLearnEnv

DATASETS = Path(__file__).resolve().parents[1] / 'data' / 'datasets'
THERMAL = str(DATASETS / 'citylearn_challenge_2020_climate_zone_1' / 'schema.json')
PT_REC_4 = str(DATASETS / 'pt_rec_4' / 'schema.json')
PLUS_EVS = str(DATASETS / 'citylearn_challenge_2022_phase_all_plus_evs' / 'schema.json')


def _env(schema, steps=48, start=0, **kwargs):
    return CityLearnEnv(
        schema,
        simulation_start_time_step=start,
        simulation_end_time_step=start + steps - 1,
        random_seed=0,
        export_kpis_on_episode_end=False,
        **kwargs,
    )


def _entity_tables(env, vector):
    """The entity table payload that carries a central flat action vector."""

    service = env._entity_service
    specs = env.entity_specs['actions']
    building = np.zeros((len(specs['building']['ids']), len(specs['building']['features'])), dtype=np.float32)
    charger = np.zeros((len(specs['charger']['ids']), 1), dtype=np.float32)
    deferrable = np.zeros((len(specs['deferrable_appliance']['ids']), 1), dtype=np.float32)
    cursor = 0

    for index, b in enumerate(env.buildings):
        for name in b.active_actions:
            value = vector[cursor]
            cursor += 1

            if name in specs['building']['features']:
                building[index, specs['building']['features'].index(name)] = value
            elif name.startswith('electric_vehicle_storage_'):
                charger[service._charger_row_by_ev_action_name[(index, name)], 0] = value
            elif name.startswith('deferrable_appliance_'):
                deferrable[service._deferrable_appliance_row_by_action_name[(index, name)], 0] = value

    tables = {'building': building, 'charger': charger, 'deferrable_appliance': deferrable}
    return {'tables': {name: table for name, table in tables.items() if table.shape[0] > 0}}


def _run(schema, interface, payload, *, scale=1.0, clip=False, **kwargs):
    env = _env(schema, interface=interface, central_agent=True, **kwargs)
    env.reset(seed=0)
    rng = np.random.default_rng(0)
    space = env.flat_action_space[0]
    low, high = space.low.astype(float), space.high.astype(float)

    while not env.terminated:
        # float32 values, so that the entity tables (cast to float32) carry exactly the same actions.
        actions = (scale * rng.uniform(low, high)).astype(np.float32).astype(float)

        if clip:
            actions = np.minimum(np.maximum(actions, low), high)

        env.step(_entity_tables(env, actions) if payload == 'tables' else [actions.tolist()])

    return {
        b.name: np.asarray(b.net_electricity_consumption, dtype=float)
        for b in env.buildings
    }


def _assert_same(left, right):
    assert left.keys() == right.keys()

    for name in left:
        np.testing.assert_array_equal(left[name], right[name], err_msg=name)


def test_out_of_range_flat_actions_give_the_clipped_simulation():
    unclipped = _run(THERMAL, 'flat', 'vector', scale=3.0)
    clipped = _run(THERMAL, 'flat', 'vector', scale=3.0, clip=True)
    tables = _run(THERMAL, 'entity', 'tables', scale=3.0)
    flat_like = _run(THERMAL, 'entity', 'vector', scale=3.0)

    _assert_same(unclipped, clipped)
    _assert_same(tables, clipped)
    _assert_same(flat_like, clipped)


@pytest.mark.parametrize('central_agent', [True, False])
def test_flat_parser_clips_to_the_action_space_and_keeps_in_range_values(central_agent):
    env = _env(THERMAL, steps=4, interface='flat', central_agent=central_agent)
    env.reset(seed=0)
    spaces = env.action_space
    # Far outside, just outside by float64 rounding of the float32 bound, and well inside the space.
    vectors = []

    for space in spaces:
        low, high = space.low.tolist(), space.high.tolist()
        vectors.append([
            [h + 1.0 + 10.0 * abs(h) for h in high],
            [float(np.nextafter(lo, -np.inf)) for lo in low],
            [lo + 0.37 * (h - lo) for lo, h in zip(low, high)],
        ])

    for case in range(3):
        actions = [v[case] for v in vectors]
        parsed = env._parse_actions(actions)
        sent = [a for v in actions for a in v]
        flat_low = [x for s in spaces for x in s.low.tolist()]
        flat_high = [x for s in spaces for x in s.high.tolist()]
        values = [value for building in parsed for value in building.values()]
        assert len(values) == len(sent)

        for value, request, low, high in zip(values, sent, flat_low, flat_high):
            if case == 0:
                assert value == high and type(value) is float
            elif case == 1:
                assert value == low
            else:
                # Inside the space: the very value sent, not a float32 rounding of it.
                assert value == request and low <= value <= high


def test_entity_flat_like_vectors_are_clipped_like_tables():
    env = _env(PLUS_EVS, steps=4, interface='entity', central_agent=True)
    env.reset(seed=0)
    space = env.flat_action_space[0]
    request = (3.0 * space.high.astype(float)).tolist()
    from_vector = env._entity_service.parse_actions([request])
    from_tables = env._entity_service.parse_actions(_entity_tables(env, request))
    assert from_vector == from_tables

    for building in from_vector:
        for key, value in building.items():
            values = value.values() if isinstance(value, dict) else [value]
            assert all(v <= 1.0 for v in values), key


@pytest.mark.parametrize('interface', ['flat', 'entity'])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_non_finite_actions_are_still_rejected(interface, bad):
    env = _env(THERMAL, steps=4, interface=interface, central_agent=True)
    env.reset(seed=0)
    actions = np.zeros(env.flat_action_space[0].shape[0])
    actions[0] = bad

    with pytest.raises(ValueError, match='must be finite'):
        env.step([actions.tolist()])


def test_clip_action_rule():
    from citylearn.internal.scalars import clip_action

    assert clip_action(2.0, -1.0, 1.0) == 1.0
    assert clip_action(-2.0, np.float32(-0.25), 1.0) == float(np.float32(-0.25))
    value = 0.30000000000000004
    assert clip_action(value, 0.0, 1.0) is value
    float32_value = np.float32(0.3)
    assert clip_action(float32_value, 0.0, 1.0) is float32_value
    assert clip_action(1, 0.0, 1.0) == 1 and type(clip_action(1, 0.0, 1.0)) is int

    for bad in (np.nan, np.inf, -np.inf, 'x', None):
        result = clip_action(bad, 0.0, 1.0)
        assert result is bad or (isinstance(bad, float) and np.isnan(bad) and np.isnan(result))


@pytest.mark.parametrize('agent_class', [BasicRBC, OptimizedRBC, BasicBatteryRBC])
def test_hour_rbcs_stay_inside_the_action_space_on_chargers_without_v2g(agent_class):
    # pt_rec_4 chargers cannot discharge (EV action space [0, 1]); the storage rule of the hour RBCs sends
    # negative values to every action whose name contains "storage", EV chargers included.
    env = _env(PT_REC_4, steps=48, start=2000, interface='flat', central_agent=False)
    agent = agent_class(env)
    observations, _ = env.reset(seed=0)
    assert any(
        name.startswith('electric_vehicle_storage_') and low == 0.0
        for b in env.buildings
        for name, low in zip(b.active_actions, b.action_space.low)
    )

    while not env.terminated:
        actions = agent.predict(observations, deterministic=True)

        for values, space in zip(actions, env.action_space):
            values = np.asarray(values, dtype=float)
            assert np.all(values >= space.low) and np.all(values <= space.high)

        observations, *_ = env.step(actions)
