"""Stable Baselines3 on CityLearn end to end, kept short (#311).

`check_env` on `StableBaselines3Wrapper(NormalizedObservationWrapper(env))`, a few SAC and PPO updates with a small
network, `predict` over a whole episode with every observation inside its space, `evaluate_v2()`, and the CLI saving a
model and loading it again. One day of `citylearn_challenge_2022_phase_all_plus_evs` (EVs and deferrable appliances),
so each test takes seconds. Skipped without stable-baselines3.
"""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('stable_baselines3')

from stable_baselines3 import PPO, SAC  # noqa: E402
from stable_baselines3.common.env_checker import check_env  # noqa: E402

from citylearn.__main__ import Simulator  # noqa: E402
from citylearn.citylearn import CityLearnEnv  # noqa: E402
from citylearn.wrappers import NormalizedObservationWrapper, StableBaselines3Wrapper  # noqa: E402

pytestmark = pytest.mark.filterwarnings('ignore')

SCHEMA = str(Path(__file__).resolve().parents[1] / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all_plus_evs' / 'schema.json')
ENV_KWARGS = {'central_agent': True, 'episode_time_steps': 24, 'simulation_end_time_step': 23, 'random_seed': 0}
WRAPPERS = ['citylearn.wrappers.NormalizedObservationWrapper', 'citylearn.wrappers.StableBaselines3Wrapper']


def _env():
    return StableBaselines3Wrapper(NormalizedObservationWrapper(CityLearnEnv(SCHEMA, **ENV_KWARGS)))


def test_wrapped_environment_passes_check_env():
    env = _env()
    check_env(env, warn=False)

    observations, _ = env.reset(seed=0)
    assert observations.dtype == np.float32 and observations.shape == env.observation_space.shape
    assert env.action_space.shape == (len(env.unwrapped.action_names[0]),)


@pytest.mark.parametrize('algorithm, kwargs', [
    (SAC, {'learning_starts': 8, 'batch_size': 8, 'buffer_size': 64}),
    (PPO, {'n_steps': 16, 'batch_size': 8, 'n_epochs': 1}),
], ids=['SAC', 'PPO'])
def test_short_training_predicts_a_whole_episode_inside_the_spaces(algorithm, kwargs):
    model = algorithm('MlpPolicy', _env(), seed=0, device='cpu', policy_kwargs={'net_arch': [16, 16]}, **kwargs)
    model.learn(total_timesteps=32)

    env = _env()
    observations, _ = env.reset(seed=0)
    steps = 0

    while True:
        assert env.observation_space.contains(observations)
        actions, _ = model.predict(observations, deterministic=True)
        assert env.action_space.contains(actions)
        observations, reward, terminated, truncated, _ = env.step(actions)
        assert np.isfinite(reward)
        steps += 1

        if terminated or truncated:
            break

    assert truncated and not terminated
    assert steps == env.unwrapped.time_steps - 1
    kpis = env.unwrapped.evaluate_v2()
    assert len(kpis) > 0 and kpis['value'].notna().any()


def test_cli_saves_and_loads_a_stable_baselines3_model(tmp_path):
    common = dict(
        schema=SCHEMA, agent_name='stable_baselines3.SAC', env_kwargs=dict(ENV_KWARGS), wrappers=WRAPPERS,
        agent_kwargs={'policy': 'MlpPolicy', 'learning_starts': 8, 'batch_size': 8, 'policy_kwargs': {'net_arch': [16, 16]}},
    )
    Simulator.train(episodes=1, save_agent=True, output_directory=tmp_path / 'train', simulation_id='sac', **common)
    model = tmp_path / 'train' / 'sac-agent.zip'
    assert model.is_file()

    # Loading used to call BaseAlgorithm.load, which cannot instantiate the abstract class.
    Simulator.evaluate(output_directory=tmp_path / 'evaluate', simulation_id='sac', agent_filepath=model, **common)
    assert (tmp_path / 'evaluate' / 'sac-evaluation.json').is_file()

    # Writing to the directory that holds the model would delete it before loading it.
    with pytest.raises(ValueError, match='holds the agent to load'):
        Simulator.evaluate(output_directory=tmp_path / 'train', simulation_id='sac', agent_filepath=model, **common)

    assert model.is_file()

    with pytest.raises(ValueError, match='-a must name the algorithm'):
        Simulator.evaluate(
            **{**common, 'agent_name': 'citylearn.agents.baseline.BusinessAsUsualAgent'},
            output_directory=tmp_path / 'other', simulation_id='sac', agent_filepath=model,
        )
