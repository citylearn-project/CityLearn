"""`citylearn simulate -rs <seed>` runs with the rule-based agents.

The CLI passes the seed to the environment and, as ``random_seed``, to the agent. The business-as-usual agent (the
CLI default) and the rule-based policies rejected it as an unknown engine hyperparameter, so every seeded run of
these agents stopped before its first step.
"""

import json
import sys

import pandas as pd
import pytest

import citylearn.__main__ as cli
from citylearn.agents.baseline import BusinessAsUsualAgent, RBCSmartPolicy
from citylearn.citylearn import CityLearnEnv

SCHEMA = 'pt_rec_4'
ENV_KWARGS = {'episode_time_steps': 24, 'simulation_end_time_step': 23, 'offline': True}
AGENTS = [
    None,  # the CLI default, BusinessAsUsualAgent
    'citylearn.agents.baseline.RBCBasicPolicy',
    'citylearn.agents.baseline.RBCSmartPolicy',
    'citylearn.agents.baseline.RBCCommunityPolicy',
]


def _run_cli(monkeypatch, output_directory, agent_name, env_kwargs, *options) -> pd.DataFrame:
    agent = () if agent_name is None else ('-a', agent_name)
    argv = [
        'citylearn', 'simulate', SCHEMA, *agent, '-ke', json.dumps(env_kwargs), '-d', str(output_directory),
        '-sid', 'run', *options, 'evaluate',
    ]
    monkeypatch.setattr(sys, 'argv', argv)
    assert cli.main() == 0

    return pd.read_csv(output_directory/'run-evaluation_v2.csv')


@pytest.mark.parametrize('agent_name', AGENTS, ids=['default', 'basic', 'smart', 'community'])
def test_cli_random_seed_runs_rule_agents(monkeypatch, tmp_path, agent_name):
    seeded = _run_cli(monkeypatch, tmp_path/'rs', agent_name, ENV_KWARGS, '-rs', '3', '--no_business_as_usual')
    # The seed given with -rs is the environment's seed: the run equals one seeded through the environment kwargs.
    expected = _run_cli(
        monkeypatch, tmp_path/'ke', agent_name, {**ENV_KWARGS, 'random_seed': 3}, '--no_business_as_usual'
    )
    pd.testing.assert_frame_equal(seeded, expected)


def test_rule_agents_accept_random_seed_without_changing_their_definition():
    env = CityLearnEnv(SCHEMA, **ENV_KWARGS, random_seed=0)

    try:
        for agent_type in (BusinessAsUsualAgent, RBCSmartPolicy):
            agent = agent_type(env, random_seed=0)
            reference = agent_type(env)
            assert agent.hyperparameters == reference.hyperparameters == {}
            assert agent.comparison_identity() == reference.comparison_identity()

            # Engine hyperparameters are still checked.
            with pytest.raises(ValueError, match='unknown hyperparameters'):
                agent_type(env, random_seed=0, not_a_hyperparameter=1)

    finally:
        env.close()
