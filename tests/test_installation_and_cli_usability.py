"""Optional dependencies, actionable errors, CLI output hygiene and the example notebooks (#259, #265-#269, #273)."""

import json
from pathlib import Path
import re
import sys

import pytest

from citylearn.__main__ import Simulator
from citylearn.citylearn import CityLearnEnv, UnknownSchemaError
from citylearn.data import DataSet, OfflineDataError
from citylearn.internal.optional_dependencies import missing_dependency
from citylearn.utilities import FileHandler

from test_bau_export_and_cli_regressions import _TrainingRecordingAgent, _minute_ev_demo_schema

ROOT = Path(__file__).resolve().parents[1]
LSTM_DATASET = ROOT / 'data' / 'datasets' / 'citylearn_challenge_2023_phase_2_local_evaluation'


# #259: PyTorch and scikit-learn are optional extras with actionable errors.

def _requirements(path):
    return {re.split(r'[<>=;\[ ]', line.strip())[0].lower() for line in path.read_text().splitlines() if line.strip()}


def test_core_requirements_leave_pytorch_and_scikit_learn_to_extras():
    pyproject = (ROOT / 'pyproject.toml').read_text()
    core = _requirements(ROOT / 'requirements.txt')

    assert not core & {'torch', 'scikit-learn', 'sklearn'}
    assert 'dynamics = ["torch"]' in pyproject
    assert 'rl = ["torch", "scikit-learn"]' in pyproject
    assert {'torch', 'scikit-learn'} <= _requirements(ROOT / 'test_requirements.txt')
    assert 'ray' not in _requirements(ROOT / 'test_requirements.txt')


def test_missing_dependency_names_the_extra_and_the_cpu_only_pytorch():
    message = str(missing_dependency('SAC', 'PyTorch', 'rl'))

    assert 'pip install "citylearn[rl]"' in message
    assert 'download.pytorch.org/whl/cpu' in message
    assert 'download.pytorch.org' not in str(missing_dependency('MARLISA', 'scikit-learn', 'rl'))


def test_lstm_dataset_without_pytorch_names_the_dynamics_extra(monkeypatch):
    import citylearn.dynamics

    monkeypatch.setattr(citylearn.dynamics, 'torch', None)
    schema = json.loads((LSTM_DATASET / 'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(LSTM_DATASET)

    with pytest.raises(ImportError, match=re.escape('pip install "citylearn[dynamics]"')):
        CityLearnEnv(schema, episode_time_steps=4)


# #268: data errors point to the next step.

def test_unknown_dataset_name_suggests_the_closest_names():
    with pytest.raises(UnknownSchemaError) as error:
        CityLearnEnv('citylearn_challenge_2022_phase_all_plus_ev')

    message = str(error.value)
    assert "Did you mean 'citylearn_challenge_2022_phase_all_plus_evs'" in message
    assert 'get_dataset_names()' in message and 'get_names' not in message


def test_parquet_dataset_without_pyarrow_fails_before_downloading(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pyarrow', None)

    with pytest.raises(ImportError, match=re.escape('pip install "citylearn[parquet]"')):
        DataSet._require_parquet_engine('pt_rec_4', ['schema.json', 'members/Building_1.parquet'])

    DataSet._require_parquet_engine('csv_only', ['schema.json', 'Building_1.csv'])


@pytest.mark.use_real_dataset_resolution
def test_offline_error_with_an_empty_cache_explains_how_to_get_data(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setattr(DataSet, 'local_datasets_directories', property(lambda self: []))

    with pytest.raises(OfflineDataError) as error:
        DataSet(offline=True).get_dataset_names()

    message = str(error.value)
    assert 'CITYLEARN_LOCAL_DATASETS_PATH' in message and 'CITYLEARN_OFFLINE=0' in message
    assert str(tmp_path / 'cache') in message


def test_data_messages_no_longer_say_dne():
    assert 'DNE' not in (ROOT / 'citylearn' / 'data.py').read_text(encoding='utf-8')


# #269: CLI evaluation window, host information, output paths and wrapped environments.

def _train(tmp_path, **kwargs):
    _TrainingRecordingAgent.trained_ids.clear()
    _TrainingRecordingAgent.evaluated_ids.clear()
    Simulator.train(
        episodes=1, evaluate=True, schema=str(_minute_ev_demo_schema(tmp_path)),
        agent_name=f'{_TrainingRecordingAgent.__module__}._TrainingRecordingAgent',
        time_series_variables=['net_electricity_consumption'], output_directory=tmp_path / 'simulation',
        simulation_id='train', **kwargs,
    )
    return (
        FileHandler.read_json(tmp_path / 'simulation' / 'train-train.json'),
        FileHandler.read_json(tmp_path / 'simulation' / 'train-evaluation.json'),
    )


def test_train_evaluates_the_first_training_episode_and_omits_host_information(tmp_path, capsys):
    training, evaluation = _train(tmp_path, env_kwargs={'central_agent': True, 'random_seed': 0, 'episode_time_steps': 4})

    assert evaluation['evaluation_episode_time_steps'] == [0, 3]
    assert 'hostname' not in training and 'username' not in training
    output = capsys.readouterr().out
    assert f"Wrote the training summary to {tmp_path / 'simulation' / 'train-train.json'}" in output
    assert f"Wrote the evaluation to {tmp_path / 'simulation' / 'train-evaluation.json'}" in output


def test_record_host_adds_the_host_information(tmp_path):
    training, _ = _train(tmp_path, env_kwargs={'central_agent': True, 'random_seed': 0}, record_host=True)

    assert training['hostname'] and training['username']


def test_evaluate_runs_through_gymnasium_wrappers(tmp_path):
    Simulator.evaluate(
        schema=str(_minute_ev_demo_schema(tmp_path)), env_kwargs={'random_seed': 0},
        wrappers=['citylearn.wrappers.ClippedObservationWrapper'], time_series_variables=['net_electricity_consumption'],
        output_directory=tmp_path / 'simulation', simulation_id='wrapped',
    )

    assert (tmp_path / 'simulation' / 'wrapped-evaluation.json').is_file()


def test_stable_baselines3_agent_without_policy_shows_the_argument(tmp_path):
    pytest.importorskip('stable_baselines3')

    with pytest.raises(TypeError, match=re.escape('-ka \'{"policy": "MlpPolicy"}\'')):
        Simulator(
            schema=str(_minute_ev_demo_schema(tmp_path)), agent_name='stable_baselines3.SAC',
            env_kwargs={'central_agent': True}, output_directory=tmp_path / 'simulation',
            wrappers=['citylearn.wrappers.NormalizedObservationWrapper', 'citylearn.wrappers.StableBaselines3Wrapper'],
        )


# #265-#267: the published notebooks.

def _code_cells(name):
    notebook = json.loads((ROOT / 'examples' / f'{name}.ipynb').read_text(encoding='utf-8'))
    return [''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code']


def test_passive_agent_cell_evaluates_without_the_bau_reference():
    cell = next(c for c in _code_cells('controller_examples') if 'NoControlAgent' in c)

    assert 'evaluate_v2(include_business_as_usual=False)' in cell


def test_notebooks_use_current_reinforcement_learning_dependencies():
    for name in ('controller_examples', 'cli', 'rl_training'):
        source = '\n'.join(_code_cells(name))
        assert 'stable-baselines3==' not in source and 'ray[rllib]==' not in source and 'from ray' not in source

    assert not (ROOT / 'examples' / 'tutorial.ipynb').exists()
    assert 'rl_training' in (ROOT / 'docs' / 'source' / 'usage' / 'index.rst').read_text(encoding='utf-8')


def test_notebook_runner_skips_install_and_tagged_cells():
    pytest.importorskip('nbformat')
    pytest.importorskip('nbclient')
    sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))

    try:
        from run_notebooks import NOTEBOOKS, executable_copy
    finally:
        sys.path.remove(str(ROOT / 'scripts' / 'ci'))

    assert {Path(n).stem for n in NOTEBOOKS} == {'controller_examples', 'load_environment', 'cli', 'rl_training'}
    cells = executable_copy(ROOT / 'examples' / 'controller_examples.ipynb').cells
    assert not any(c.cell_type == 'code' and c.source.lstrip().startswith('%pip') for c in cells)
    assert not any('Neighborhood()' in c.source for c in cells if c.cell_type == 'code')


# #273: contributor onboarding.

def test_contributor_files_point_to_the_current_maintainer():
    assert (ROOT / 'CONTRIBUTING.md').is_file()
    templates = ROOT / '.github' / 'ISSUE_TEMPLATE'

    for name in ('bug_report.md', 'feature_request.md', 'question.md'):
        text = (templates / name).read_text(encoding='utf-8')
        assert 'assignees: calofonseca' in text and 'kingsleynweye' not in text

    assert (templates / 'config.yml').is_file()
