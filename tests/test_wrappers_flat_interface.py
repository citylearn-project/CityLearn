"""The flat-vector wrappers on entity-interface datasets (#351).

The pt_rec_* datasets default to `interface='entity'`. `NormalizedObservationWrapper` read the entity dictionaries
as flat lists and crashed at `reset()` with a `TypeError` in `PeriodicNormalization`. The flat wrappers now refuse an
entity environment with an error that names the fix, and normalise the pt_rec observations with `interface='flat'`.
"""

from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn import wrappers

PT_REC_4 = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / 'pt_rec_4' / 'schema.json'

FLAT_WRAPPERS = [
    wrappers.ClippedObservationWrapper,
    wrappers.NormalizedObservationWrapper,
    wrappers.NormalizedActionWrapper,
    wrappers.NormalizedSpaceWrapper,
    wrappers.DiscreteObservationWrapper,
    wrappers.DiscreteActionWrapper,
    wrappers.TabularQLearningObservationWrapper,
    wrappers.TabularQLearningActionWrapper,
    wrappers.StableBaselines3ObservationWrapper,
    wrappers.StableBaselines3ActionWrapper,
    wrappers.StableBaselines3RewardWrapper,
    wrappers.StableBaselines3Wrapper,
]


def _env(**kwargs):
    return CityLearnEnv(str(PT_REC_4), episode_time_steps=4, random_seed=0, **kwargs)


@pytest.mark.parametrize('central_agent', [False, True])
@pytest.mark.parametrize('wrapper', FLAT_WRAPPERS, ids=lambda w: w.__name__)
def test_flat_wrappers_refuse_the_entity_interface_with_the_fix(wrapper, central_agent):
    env = _env(central_agent=central_agent)
    assert env.interface == 'entity'

    with pytest.raises(ValueError, match=r"needs interface='flat'.*interface='entity'"):
        wrapper(env)


@pytest.mark.parametrize('central_agent', [False, True])
def test_normalized_observations_on_pt_rec_4_with_the_flat_interface(central_agent):
    env = wrappers.NormalizedObservationWrapper(_env(central_agent=central_agent, interface='flat'))
    reference = _env(central_agent=central_agent, interface='flat')
    observations, _ = env.reset()
    reference_observations, _ = reference.reset()

    while True:
        for values, space in zip(observations, env.observation_space):
            values = np.array(values, dtype='float32')
            assert values.shape == space.shape and space.contains(values)

        # Normalising must leave the environment's own observations as they are.
        assert env.unwrapped.observations == reference_observations

        actions = [np.zeros(s.shape, dtype='float32') for s in env.action_space]
        observations, _, terminated, truncated, _ = env.step(actions)
        reference_observations, _, _, _, _ = reference.step(actions)

        if terminated or truncated:
            break
