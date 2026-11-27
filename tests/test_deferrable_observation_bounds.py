"""Deferrable `*_kwh` observations have bounds derived from the appliances' cycles.

The flat `deferrable_appliance_*_cycle_energy_kwh`, `*_remaining_energy_kwh` and `*_current_step_energy_kwh`
observations were bounded by [-1, 1e6], so `NormalizedObservationWrapper` turned them into constants of about 1e-6
and an agent could not see how much energy a cycle needs. Their bounds are now [0, largest cycle energy] and
[0, largest step energy] of the building's appliances. Only the observation space changes, not the simulation.
"""

from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.wrappers import NormalizedObservationWrapper

DATASETS = Path(__file__).resolve().parents[1] / 'data' / 'datasets'
PT_REC_4 = str(DATASETS / 'pt_rec_4' / 'schema.json')
PLUS_EVS = str(DATASETS / 'citylearn_challenge_2022_phase_all_plus_evs' / 'schema.json')
ENERGY_FEATURES = ('cycle_energy_kwh', 'remaining_energy_kwh', 'current_step_energy_kwh')


def _env(schema, start, steps, **kwargs):
    return CityLearnEnv(
        schema,
        simulation_start_time_step=start,
        simulation_end_time_step=start + steps - 1,
        random_seed=0,
        export_kpis_on_episode_end=False,
        **kwargs,
    )


def _cycle_values(appliance):
    """Every cycle energy, remaining energy and step energy the appliance's cycle definitions can give."""

    cycle, step = [], []
    simulation = appliance.deferrable_appliance_simulation

    for c in list(simulation.cycle_profiles.values()) + list(simulation.flexibility_schedule):
        profile = c['load_profile']
        cycle.append(float(c['total_energy_kwh']))
        cycle.extend(float(np.sum(profile[offset:])) for offset in range(len(profile)))
        step.extend(float(v) for v in profile)

    return cycle, step


@pytest.mark.parametrize('schema', [PT_REC_4, PLUS_EVS], ids=['pt_rec_4', 'plus_evs'])
def test_energy_bounds_cover_every_cycle_and_are_tight(schema):
    env = _env(schema, 0, 24, interface='flat', central_agent=False)
    checked = 0

    for b in env.buildings:
        if not b.deferrable_appliances:
            continue

        low, high = b.estimate_observation_space_limits()
        cycle, step = [], []

        for appliance in b.deferrable_appliances:
            c, s = _cycle_values(appliance)
            cycle += c
            step += s

        for appliance in b.deferrable_appliances:
            for feature in ENERGY_FEATURES:
                key = f'deferrable_appliance_{appliance.name}_{feature}'

                if key not in high:
                    continue

                values = step if feature == 'current_step_energy_kwh' else cycle
                assert low[key] == 0.0
                # Tight: the largest value the building's appliances can report, never the old 1e6 placeholder.
                assert high[key] == max(values), key
                assert np.float32(max(values)) <= np.float32(high[key])
                checked += 1

    assert checked > 0


def test_normalised_energy_observations_keep_their_signal():
    env = NormalizedObservationWrapper(_env(PT_REC_4, 2000, 672, interface='flat', central_agent=True))
    observations, _ = env.reset(seed=0)
    names = env.observation_names[0]
    keys = [i for i, n in enumerate(names) if n.startswith('deferrable_appliance_') and n.endswith('_kwh')]
    assert keys
    rng = np.random.default_rng(0)
    values = []

    while not env.unwrapped.terminated:
        values.append([observations[0][i] for i in keys])
        space = env.unwrapped.action_space[0]
        observations, *_ = env.step([rng.uniform(space.low, space.high).tolist()])

    values = np.asarray(values)
    assert values.min() >= 0.0 and values.max() <= 1.0 + 1.0e-6
    # Each feature spans a usable part of [0, 1]; under the 1e6 bound they all stayed below 1e-4.
    assert np.all(values.max(axis=0) - values.min(axis=0) > 0.1)


@pytest.mark.parametrize('interface', ['flat', 'entity'])
def test_deferrable_energy_observations_stay_inside_the_space(interface):
    env = _env(PT_REC_4, 2000, 672, interface=interface, central_agent=True)
    observations, _ = env.reset(seed=0)
    rng = np.random.default_rng(0)

    if interface == 'flat':
        names = env.observation_names[0]
        keys = [i for i, n in enumerate(names) if n.startswith('deferrable_appliance_') and n.endswith('_kwh')]
        space = env.observation_space[0]
    else:
        features = env.entity_specs['tables']['deferrable_appliance']['features']
        keys = [i for i, n in enumerate(features) if n in ENERGY_FEATURES]
        space = env.observation_space['tables']['deferrable_appliance']

    assert keys

    while True:
        if interface == 'flat':
            values = np.asarray(observations[0], dtype=np.float32)[keys]
            low, high = space.low[keys], space.high[keys]
        else:
            values = np.asarray(observations['tables']['deferrable_appliance'], dtype=np.float32)[:, keys]
            low, high = space.low[:, keys], space.high[:, keys]

        assert np.all(values >= low) and np.all(values <= high)
        assert np.all(high < 1.0e3)

        if env.terminated:
            break

        action_space = env.flat_action_space[0]
        observations, *_ = env.step([rng.uniform(action_space.low, action_space.high).tolist()])
