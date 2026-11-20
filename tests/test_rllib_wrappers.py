"""Short training runs of the RLlib wrappers on the new API stack of a current Ray release (CityLearn #293).

The tests skip when Ray RLlib is not installed. They run local rollouts (``num_env_runners=0``) of a
few iterations on a day of the bundled hourly dataset.
"""

import numpy as np
import pytest
import torch

pytest.importorskip('ray.rllib')

import ray  # noqa: E402
from ray.rllib.algorithms.ppo import PPOConfig  # noqa: E402
from ray.rllib.algorithms.sac import SACConfig  # noqa: E402
from ray.rllib.core.columns import Columns  # noqa: E402

from citylearn.wrappers import (  # noqa: E402
    ClippedObservationWrapper,
    NormalizedObservationWrapper,
    RLlibMultiAgentActionWrapper,
    RLlibMultiAgentEnv,
    RLlibSingleAgentWrapper,
)

pytestmark = pytest.mark.filterwarnings('ignore')

ENV_CONFIG = {
    'env_kwargs': {
        'schema': 'citylearn_challenge_2023_phase_2_local_evaluation',
        'simulation_start_time_step': 0,
        'simulation_end_time_step': 23,
    },
    'wrappers': [NormalizedObservationWrapper, ClippedObservationWrapper],
}
ITERATIONS = 2


@pytest.fixture(scope='module', autouse=True)
def ray_session():
    ray.init(num_cpus=1, include_dashboard=False, logging_level='ERROR', ignore_reinit_error=True)
    yield
    ray.shutdown()


def _train(config):
    algo = config.build_algo()

    try:
        for _ in range(ITERATIONS):
            result = algo.train()

        assert result['num_env_steps_sampled_lifetime'] > 0
        return algo, result

    except BaseException:
        algo.stop()
        raise


def _inference_action(module, observation):
    batch = {Columns.OBS: torch.as_tensor(np.asarray(observation, dtype='float32'))[None]}

    with torch.no_grad():
        outputs = module.forward_inference(batch)

    return outputs


@pytest.mark.parametrize('config_class', [PPOConfig, SACConfig])
def test_single_agent_wrapper_trains_and_infers(config_class):
    config = config_class().environment(RLlibSingleAgentWrapper, env_config=ENV_CONFIG).env_runners(num_env_runners=0)

    if config_class is PPOConfig:
        config = config.training(train_batch_size_per_learner=48, minibatch_size=24, num_epochs=1)

    else:
        config = config.training(train_batch_size_per_learner=24, num_steps_sampled_before_learning_starts=24)

    algo, _ = _train(config)

    try:
        env = RLlibSingleAgentWrapper({**ENV_CONFIG, 'env_kwargs': dict(ENV_CONFIG['env_kwargs'])})
        observation, _ = env.reset()
        outputs = _inference_action(algo.get_module(), observation)
        assert Columns.ACTION_DIST_INPUTS in outputs or Columns.ACTIONS in outputs

    finally:
        algo.stop()


def test_multi_agent_env_trains_and_infers():
    env = RLlibMultiAgentEnv({**ENV_CONFIG, 'env_kwargs': dict(ENV_CONFIG['env_kwargs'])})
    agent_ids = list(env._agent_ids)
    assert env.agents == env.possible_agents == agent_ids
    assert set(env.observation_spaces) == set(env.action_spaces) == set(agent_ids)
    config = (
        PPOConfig()
        .environment(RLlibMultiAgentEnv, env_config=ENV_CONFIG)
        .multi_agent(policies=set(agent_ids), policy_mapping_fn=lambda agent_id, *args, **kwargs: agent_id)
        .env_runners(num_env_runners=0)
        .training(train_batch_size_per_learner=48, minibatch_size=24, num_epochs=1)
    )
    algo, _ = _train(config)

    try:
        observations, _ = env.reset()

        for agent_id in agent_ids:
            outputs = _inference_action(algo.get_module(agent_id), observations[agent_id])
            assert Columns.ACTION_DIST_INPUTS in outputs or Columns.ACTIONS in outputs

    finally:
        algo.stop()


def test_multi_agent_action_wrapper_orders_actions_by_agent_id():
    from citylearn.citylearn import CityLearnEnv

    env = RLlibMultiAgentActionWrapper(CityLearnEnv(central_agent=False, **ENV_CONFIG['env_kwargs']))
    n = len(env.unwrapped.buildings)
    actions = {f'agent_{i}': np.full(env.unwrapped.action_space[i].shape, float(i)) for i in reversed(range(n))}
    parsed = env.action(actions)
    assert [set(a) for a in parsed] == [{float(i)} for i in range(n)]
