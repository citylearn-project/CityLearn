"""Regressions in the bundled SAC and MARLISA agents (normalisation, schedule, seeding, MARLISA coordination)."""

import copy
import json
import random
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip('torch')
pytest.importorskip('sklearn')

from citylearn.agents.marlisa import MARLISA
from citylearn.agents.sac import SAC
from citylearn.citylearn import CityLearnEnv

DATASET = Path(__file__).resolve().parents[1] / 'data' / 'datasets' / 'citylearn_challenge_2022_phase_all'
# Encoded SAC/MARLISA observation layout for this dataset: month -> (sin, cos), day_type -> 8 one-hot, hour -> (sin, cos), ...
MONTH_COLUMNS = [0, 1]


@pytest.fixture(autouse=True)
def _single_torch_thread():
    # The networks here are tiny; intra-op threads only add contention (minutes when other suites run alongside).
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(threads)


def _schema():
    schema = json.loads((DATASET / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(DATASET)
    return schema


def _env(episode_time_steps=24, buildings=(0,), random_seed=0):
    return CityLearnEnv(
        _schema(), central_agent=False, episode_time_steps=episode_time_steps, buildings=list(buildings),
        random_seed=random_seed,
    )


def _observation(base, names, month, hour):
    observation = list(base)
    observation[names.index('month')] = month
    observation[names.index('hour')] = hour
    return observation


def _feed_constant_month_warm_up(agent, env, steps):
    """Learn from `steps` January transitions with a constant reward; returns a builder for further observations."""

    observations, _ = env.reset()
    names = env.observation_names[0]
    observation = lambda month, hour: _observation(observations[0], names, month, hour)

    for t in range(steps):
        actions = agent.predict([observation(1, t%24 + 1)])
        agent.update(
            [observation(1, t%24 + 1)], actions, [-1.0], [observation(1, (t + 1)%24 + 1)],
            terminated=False, truncated=False,
        )

    return observation


# --- standardisation of features that are constant during warm-up ------------------------------------------------

def test_sac_standardisation_centres_but_does_not_amplify_warm_up_constants():
    env = _env()
    agent = SAC(env, hidden_dimension=[8, 8], batch_size=8, standardize_start_time_step=8, end_exploration_time_step=20)
    observation = _feed_constant_month_warm_up(agent, env, 8)
    assert agent.normalized[0]

    # month and the reward never vary in the warm-up buffer: centred, scale 1 (was nanstd + 1e-5 ~ 1e-5).
    np.testing.assert_array_equal(agent.norm_std[0][MONTH_COLUMNS], 1.0)
    assert agent.r_norm_std[0] == 1.0

    # A February observation used to z-score to ~1e4 on the month columns, saturating every action.
    february = agent.get_normalized_observations(0, agent.get_encoded_observations(0, observation(2, 5)))
    assert np.max(np.abs(february[MONTH_COLUMNS])) < 1.0
    assert abs(agent.get_normalized_reward(0, -2.0)) == pytest.approx(1.0)

    # Features that vary keep the previous scale exactly: nanstd + 1e-5 over the 8 warm-up transitions.
    hour_columns = [10, 11]
    X = np.array([o for o, *_ in agent.replay_buffer[0].buffer], dtype=float)  # standardised in place
    assert len(X) == 8
    np.testing.assert_allclose(
        np.std(X[:, hour_columns]*agent.norm_std[0][hour_columns], axis=0) + 1e-5, agent.norm_std[0][hour_columns],
        rtol=1e-9,
    )


def test_marlisa_standardisation_centres_but_does_not_amplify_warm_up_constants():
    env = _env()
    agent = MARLISA(
        env, hidden_dimension=[8, 8], batch_size=8, start_regression_time_step=1, standardize_start_time_step=41,
        end_exploration_time_step=50,
    )
    _feed_constant_month_warm_up(agent, env, 41)
    assert agent.pca_flag[0]
    np.testing.assert_array_equal(agent.norm_std[0][MONTH_COLUMNS], 1.0)
    assert agent.r_norm_std[0] == 1.0


# --- reproducibility from the environment seed --------------------------------------------------------------------

def _policy_parameters(agent):
    return [p.detach().clone() for net in agent.policy_net for p in net.parameters()]


def _actions(agent):
    return [[list(a) for a in history if len(a)] for history in agent.actions]


@pytest.mark.parametrize('agent_class, buildings, episodes, kwargs', [
    (SAC, (0,), 2, {'batch_size': 8, 'standardize_start_time_step': 10, 'end_exploration_time_step': 15}),
    (MARLISA, (0, 1), 3, {
        'batch_size': 8, 'start_regression_time_step': 2, 'standardize_start_time_step': 42,
        'end_exploration_time_step': 45,
    }),
])
def test_agents_with_identically_seeded_envs_act_and_learn_identically(agent_class, buildings, episodes, kwargs):
    agents = [agent_class(_env(buildings=buildings, random_seed=7), hidden_dimension=[8, 8], **kwargs) for _ in range(2)]

    agents[0].learn(episodes=episodes)
    # Global generators are consumed between the runs; a seeded agent must not depend on them.
    random.random(), np.random.random(), torch.rand(3)
    agents[1].learn(episodes=episodes)

    assert agents[0].time_step > agents[0].end_exploration_time_step
    assert _actions(agents[0]) == _actions(agents[1])

    for a, b in zip(_policy_parameters(agents[0]), _policy_parameters(agents[1])):
        assert torch.equal(a, b)


def test_sac_exploration_honours_explicitly_seeded_action_spaces():
    env = _env()
    agent = SAC(env, hidden_dimension=[8, 8])
    agent.action_space[0].seed(123)
    reference = copy.deepcopy(agent.action_space[0])
    observations, _ = env.reset()

    actions = agent.predict(observations)

    np.testing.assert_array_equal(actions[0], agent.action_scaling_coefficient*reference.sample())
