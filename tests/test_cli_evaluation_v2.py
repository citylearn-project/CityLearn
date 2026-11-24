"""The CLI writes the evaluate_v2() KPI table next to the legacy evaluation JSON (#367)."""

import json
import sys

import pandas as pd
import pytest

import citylearn.__main__ as cli
from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.citylearn import CityLearnEnv
from citylearn.utilities import FileHandler

# pt_rec_4 has the community market enabled, so the table must hold market and business-as-usual rows.
SCHEMA = 'pt_rec_4'
ENV_KWARGS = {'episode_time_steps': 24, 'simulation_end_time_step': 47, 'random_seed': 0, 'offline': True}


def _run_cli(monkeypatch, tmp_path, *options):
    argv = [
        'citylearn', 'simulate', SCHEMA, '-ke', json.dumps(ENV_KWARGS), '-d', str(tmp_path / 'out'),
        '-sid', 'run', *options, 'evaluate',
    ]
    monkeypatch.setattr(sys, 'argv', argv)
    assert cli.main() == 0

    return tmp_path / 'out'


def _python_evaluate_v2(include_business_as_usual: bool) -> pd.DataFrame:
    env = CityLearnEnv(SCHEMA, **ENV_KWARGS)

    try:
        agent = BusinessAsUsualAgent(env)
        observations, _ = env.reset()

        while not env.terminated:
            observations, _, _, _, _ = env.step(agent.predict(observations, deterministic=True))

        return env.evaluate_v2(include_business_as_usual=include_business_as_usual)

    finally:
        env.close()


@pytest.mark.parametrize('business_as_usual', [True, False], ids=['with_bau', 'without_bau'])
def test_cli_writes_the_evaluate_v2_table(monkeypatch, tmp_path, business_as_usual):
    options = () if business_as_usual else ('--no_business_as_usual',)
    output_directory = _run_cli(monkeypatch, tmp_path, *options)

    filepath = output_directory / 'run-evaluation_v2.csv'
    assert filepath.is_file()
    written = pd.read_csv(filepath)
    expected = _python_evaluate_v2(business_as_usual)
    pd.testing.assert_frame_equal(written, expected.reset_index(drop=True), check_dtype=False)

    names = set(written['cost_function'])
    assert any('community_market' in n for n in names), 'market rows missing'
    has_bau = any('business_as_usual' in n for n in names)
    assert has_bau is business_as_usual

    # The legacy JSON keeps its format for existing parsers.
    legacy = FileHandler.read_json(output_directory / 'run-evaluation.json')
    assert 'cost_total' in legacy['evaluation']['District']
    assert {'time_series', 'actions', 'episode_rewards'} <= set(legacy)
