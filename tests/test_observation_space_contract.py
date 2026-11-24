"""The observation spaces describe the observations that `reset()` and `step()` return (#306).

For every bundled dataset below, in both interfaces and with central and decentralised agents, an
episode is run and every observation is checked, in order, against its space: the same keys, the
same shapes and the values within the bounds at the same position. The actions are random, except
on Quebec, where random heating drives the LSTM indoor temperature past its estimated bounds within
a few steps; there the HVAC is left uncontrolled and the occupants still move the set points.
"""

from pathlib import Path

import numpy as np
import pytest

from citylearn.agents.base import NoControlAgent
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.entity_layout import EntityMetaSpace

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'datasets'

# (dataset, simulation start, episode length, controller): EV chargers with charging constraints
# and phase encodings, deferrable appliances, three-phase service, LSTM dynamics whose HVAC action
# sets the demand, and occupant interaction.
EPISODES = [
    ('pt_rec_4', 2000, 96, 'random'),
    ('citylearn_three_phase_electrical_service_demo', 2000, 96, 'random'),
    ('citylearn_challenge_2022_phase_all_plus_evs', 4000, 96, 'random'),
    ('citylearn_challenge_2023_phase_1', 0, 96, 'random'),
    ('quebec_neighborhood_with_demand_response_set_points', 0, 168, 'no_control'),
]


def _env(dataset, start, steps, interface, central_agent):
    return CityLearnEnv(
        str(DATASETS / dataset / 'schema.json'),
        interface=interface,
        central_agent=central_agent,
        simulation_start_time_step=start,
        simulation_end_time_step=start + steps - 1,
        episode_time_steps=steps,
        random_seed=0,
        export_kpis_on_episode_end=False,
    )


def _flat_names(env):
    """Names the flat space should follow, built from the buildings' flat order."""

    if not env.central_agent:
        return [list(b.flat_observation_order) for b in env.buildings]

    names, seen_shared = [], set()

    for i, b in enumerate(env.buildings):
        for name in b.flat_observation_order:
            if i == 0 or name not in env.shared_observations or name not in seen_shared:
                names.append(name)

            if name in env.shared_observations:
                seen_shared.add(name)

    return [names]


def _check_flat(env, observations, t):
    names = env.observation_names
    assert names == _flat_names(env), f'time step {t}: observation names do not follow the flat order'
    assert len(observations) == len(env.observation_space)

    for agent, (values, space, agent_names) in enumerate(zip(observations, env.observation_space, names)):
        values = np.asarray(values, dtype=np.float32)
        assert values.shape == space.shape == (len(agent_names),), f'time step {t}, agent {agent}: shape'
        outside = np.flatnonzero((values < space.low) | (values > space.high))
        assert outside.size == 0, f'time step {t}, agent {agent}: ' + ', '.join(
            f'{agent_names[i]}={values[i]} not in [{space.low[i]}, {space.high[i]}]' for i in outside
        )
        assert space.contains(values)


def _check_entity(env, observations, t):
    space = env.observation_space
    assert set(observations) == set(space.spaces), f'time step {t}: keys {sorted(observations)}'
    assert isinstance(space['meta'], EntityMetaSpace)
    specs = env.entity_specs['tables']

    for group in ('tables', 'edges'):
        assert set(observations[group]) == set(space[group].spaces), f'time step {t}: {group} keys'

        for name, box in space[group].spaces.items():
            values = np.asarray(observations[group][name])
            assert values.shape == box.shape, f'time step {t}: {group}/{name} shape {values.shape} vs {box.shape}'
            outside = np.argwhere((values < box.low) | (values > box.high))
            if group == 'tables':
                details = [
                    f'{specs[name]["ids"][r]}.{specs[name]["features"][c]}={values[r, c]} '
                    f'not in [{box.low[r, c]}, {box.high[r, c]}]' for r, c in outside
                ]
            else:
                details = [str(tuple(i)) for i in outside]
            assert len(details) == 0, f'time step {t}: {group}/{name}: ' + ', '.join(details)

    assert space.contains(observations), f'time step {t}: entity observation outside its space'


@pytest.mark.parametrize('interface', ['flat', 'entity'])
@pytest.mark.parametrize('central_agent', [False, True], ids=['decentralized', 'central'])
@pytest.mark.parametrize('dataset,start,steps,controller', EPISODES, ids=[e[0] for e in EPISODES])
def test_every_observation_lies_in_its_space_over_an_episode(
    dataset, start, steps, controller, interface, central_agent
):
    env = _env(dataset, start, steps, interface, central_agent)
    check = _check_flat if interface == 'flat' else _check_entity

    try:
        agent = NoControlAgent(env) if controller == 'no_control' else None
        observations, _ = env.reset(seed=0)
        rng = np.random.default_rng(0)

        if interface == 'entity':
            env.action_space.seed(0)

        t = 0

        while True:
            check(env, observations, t)

            if agent is not None:
                actions = agent.predict(observations, deterministic=True)
            elif interface == 'flat':
                actions = [s.low + rng.random(s.shape) * (s.high - s.low) for s in env.action_space]
            else:
                actions = env.action_space.sample()

            observations, _, terminated, truncated, _ = env.step(actions)
            t += 1

            if terminated or truncated:
                break

        check(env, observations, t)
        assert t == steps - 1

    finally:
        env.close()


def test_flat_space_bounds_follow_the_observation_names():
    """On pt_rec_4 the charging headroom used to get the bounds of an EV state of charge."""

    env = _env('pt_rec_4', 2000, 8, 'flat', False)

    try:
        env.reset()

        for building, names, space in zip(env.buildings, env.observation_names, env.observation_space):
            low, high = building.estimate_observation_space_limits(include_all=False, periodic_normalization=False)
            assert names == list(low)
            np.testing.assert_array_equal(space.low, np.array([low[n] for n in names], dtype=np.float32))
            np.testing.assert_array_equal(space.high, np.array([high[n] for n in names], dtype=np.float32))

        member = env.buildings[0]
        names = env.observation_names[0]
        assert names != member.active_observations, 'pt_rec_4 Member_001 should reorder its EV observations'
        position = names.index('charging_building_headroom_kw')
        assert env.observation_space[0].high[position] > 1.0

    finally:
        env.close()


def test_entity_meta_is_declared():
    env = _env('pt_rec_4', 2000, 4, 'entity', False)

    try:
        observations, _ = env.reset()
        meta_space = env.observation_space['meta']
        assert meta_space.contains(observations['meta'])
        assert meta_space.contains(meta_space.sample())
        assert not meta_space.contains({'time_step': 0})
        assert env.observation_space.contains(observations)

    finally:
        env.close()
