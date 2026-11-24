"""Short training runs of the RLlib wrappers on the new API stack of a current Ray release (CityLearn #293).

The tests skip when Ray RLlib is not installed. They run local rollouts (``num_env_runners=0``) of a
few iterations on a day of the bundled hourly dataset.
"""

import json
from pathlib import Path

import numpy as np
import pytest
import torch

pytest.importorskip('ray.rllib')

import ray  # noqa: E402
from ray.rllib.algorithms.ppo import PPOConfig  # noqa: E402
from ray.rllib.algorithms.sac import SACConfig  # noqa: E402
from ray.rllib.connectors.module_to_env.normalize_and_clip_actions import NormalizeAndClipActions  # noqa: E402
from ray.rllib.core.columns import Columns  # noqa: E402
from ray.rllib.models.torch.torch_distributions import TorchDiagGaussian  # noqa: E402
from ray.rllib.utils.spaces.space_utils import clip_action, unsquash_action  # noqa: E402

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


def _load_tutorial_deterministic_action():
    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root / 'examples' / 'rllib_training.ipynb').read_text(encoding='utf-8'))
    scope = {
        'Columns': Columns,
        'clip_action': clip_action,
        'np': np,
        'torch': torch,
        'unsquash_action': unsquash_action,
    }

    for cell in notebook['cells']:
        if cell['cell_type'] != 'code':
            continue

        source = ''.join(cell['source'])

        if 'def deterministic_action(' in source:
            fn_source = source.split('\n\ndef evaluate(')[0]
            exec(compile(fn_source, 'rllib_training.ipynb', 'exec'), scope)
            return scope['deterministic_action']

    raise AssertionError('deterministic_action not found in examples/rllib_training.ipynb')


class _ConstantMeanModule:
    """Stub RLModule returning fixed Gaussian mean/log-std logits for deterministic action conversion checks."""

    def __init__(self, mean_values: np.ndarray):
        mean = np.asarray(mean_values, dtype='float32')
        log_std = np.zeros_like(mean, dtype='float32')
        self._logits = torch.as_tensor(np.concatenate([mean, log_std], axis=-1))[None]

    def forward_inference(self, batch):
        assert Columns.OBS in batch
        return {Columns.ACTION_DIST_INPUTS: self._logits}

    @staticmethod
    def get_inference_action_dist_cls():
        return TorchDiagGaussian


def test_tutorial_deterministic_action_matches_rllib_action_normalization():
    deterministic_action = _load_tutorial_deterministic_action()

    # Single-agent: cooling_device has asymmetric bounds [0, 1] alongside [-1, 1] storage bounds.
    single_env = RLlibSingleAgentWrapper({**ENV_CONFIG, 'env_kwargs': dict(ENV_CONFIG['env_kwargs'])})
    single_space = single_env.action_space
    cooling_mask = (single_space.low == 0.0) & (single_space.high == 1.0)
    symmetric_mask = (single_space.low == -1.0) & (single_space.high == 1.0)
    assert np.any(cooling_mask), 'expected asymmetric [0, 1] cooling_device action in tutorial dataset'
    assert np.any(symmetric_mask)

    obs, _ = single_env.reset()
    zero_module = _ConstantMeanModule(np.zeros(single_space.shape, dtype='float32'))

    # Default PPO training (normalize_actions=True): 0.0 maps to 0.5 on [0, 1] and 0.0 on [-1, 1].
    converted = deterministic_action(zero_module, obs, single_space, normalize_actions=True)
    connector = NormalizeAndClipActions(
        input_observation_space=single_env.observation_space,
        input_action_space=single_space,
        normalize_actions=True,
        clip_actions=False,
    )
    connector.recompute_output_action_space(single_env.observation_space, single_space)
    rllib_batch = connector(
        rl_module=None,
        batch={Columns.ACTIONS: [np.zeros(single_space.shape, dtype='float32')]},
        episodes=[],
    )
    np.testing.assert_allclose(converted, rllib_batch[Columns.ACTIONS_FOR_ENV][0])
    np.testing.assert_allclose(converted[cooling_mask], 0.5)
    np.testing.assert_allclose(converted[symmetric_mask], 0.0)

    # Non-normalized training (normalize_actions=False): clips raw output directly without rescaling.
    raw_probe = np.where(cooling_mask, -0.25, 1.5).astype('float32')
    unnormalized = deterministic_action(
        _ConstantMeanModule(raw_probe), obs, single_space, normalize_actions=False,
    )
    np.testing.assert_allclose(unnormalized, np.clip(raw_probe, single_space.low, single_space.high))
    np.testing.assert_allclose(unnormalized[cooling_mask], 0.0)

    # Multi-agent: verify every agent_id applies the exact same per-agent NormalizeAndClipActions mapping.
    multi_env = RLlibMultiAgentEnv({**ENV_CONFIG, 'env_kwargs': dict(ENV_CONFIG['env_kwargs'])})
    multi_obs, _ = multi_env.reset()
    multi_connector = NormalizeAndClipActions(
        input_observation_space=multi_env.observation_space,
        input_action_space=multi_env.action_space,
        normalize_actions=True,
        clip_actions=False,
    )
    multi_connector.recompute_output_action_space(multi_env.observation_space, multi_env.action_space)
    raw_multi = {
        agent_id: np.zeros(multi_env.action_space[agent_id].shape, dtype='float32')
        for agent_id in multi_env.possible_agents
    }
    rllib_multi = multi_connector(
        rl_module=None,
        batch={Columns.ACTIONS: [dict(raw_multi)]},
        episodes=[],
    )[Columns.ACTIONS_FOR_ENV][0]

    for agent_id in multi_env.possible_agents:
        agent_space = multi_env.action_space[agent_id]
        agent_cooling = (agent_space.low == 0.0) & (agent_space.high == 1.0)
        assert np.any(agent_cooling)
        agent_action = deterministic_action(
            _ConstantMeanModule(raw_multi[agent_id]),
            multi_obs[agent_id],
            agent_space,
            normalize_actions=True,
        )
        np.testing.assert_allclose(agent_action, rllib_multi[agent_id])
        np.testing.assert_allclose(agent_action[agent_cooling], 0.5)
