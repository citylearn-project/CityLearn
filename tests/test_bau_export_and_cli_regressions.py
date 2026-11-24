"""Regression tests for the BAU time-series export, charger export columns, CLI simulator and file encodings."""

import datetime
import json
import os
import sys
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import pytest

import citylearn.__main__ as cli
from citylearn.__main__ import Simulator, run_work_order
from citylearn.agents.base import Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.comparison import compare_exports, load_kpis
from citylearn.multi_community import MultiCommunityEnv
from citylearn.utilities import FileHandler
from citylearn.utils.file_handler import FileHandler as SharedFileHandler

MINUTE_EV_DEMO = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'
NON_ASCII_NAME = 'Edif' + chr(0xED) + 'cio'
UTF8_BOM = bytes([0xEF, 0xBB, 0xBF])


def _minute_ev_demo_schema(tmp_path: Path) -> Path:
    dataset = tmp_path / 'minute_ev_demo'
    shutil.copytree(MINUTE_EV_DEMO, dataset)
    schema_path = dataset / 'schema.json'
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    schema_path.write_text(json.dumps(schema), encoding='utf-8')
    return schema_path


def _run_zero_episode(env: CityLearnEnv):
    env.reset()

    while not (env.terminated or env.truncated):
        env.step([np.zeros(space.shape, dtype='float32') for space in env.action_space])


class _TrainingRecordingAgent(Agent):
    """Zero-action agent that records which instance was trained and which one evaluated."""

    trained_ids = []
    evaluated_ids = []

    def learn(self, episodes: int = None, **kwargs):
        super().learn(episodes=episodes, **kwargs)
        _TrainingRecordingAgent.trained_ids.append(id(self))

    def predict(self, observations, deterministic: bool = None):
        if deterministic:
            _TrainingRecordingAgent.evaluated_ids.append(id(self))

        actions = [[0.0]*len(names) for names in self.action_names]
        self.actions = actions
        self.next_time_step()

        return actions


class _MarkerAgent(Agent):
    def __init__(self, env, marker: float = None, **kwargs):
        super().__init__(env, **kwargs)
        self.marker = marker


def test_business_as_usual_timeseries_export_writes_only_executed_time_steps(tmp_path):
    env = CityLearnEnv(
        str(_minute_ev_demo_schema(tmp_path)), central_agent=True, random_seed=0, render_mode='end',
        render_directory=tmp_path / 'renders', render_session_name='bau',
    )

    try:
        _run_zero_episode(env)
        executed_time_steps = env.time_step
        env.export_final_kpis()
        output = Path(env.new_folder_path)
        bau = pd.read_csv(output / 'exported_data_business_as_usual_ep0.csv')
        district = bau[bau['level'] == 'district']
        control_rows = len(pd.read_csv(output / 'exported_data_building_1_ep0.csv'))
        reference = env.run_business_as_usual_baseline().env

        assert control_rows == executed_time_steps
        assert district['time_step'].tolist() == list(range(executed_time_steps))
        assert bau[bau['level'] == 'building']['time_step'].tolist() == list(range(executed_time_steps))
        # The terminal row repeated the last executed step, so the export total counted it twice.
        assert district['net_electricity_consumption_kwh'].sum() == pytest.approx(
            float(np.sum(reference.net_electricity_consumption[:executed_time_steps]))
        )
    finally:
        env.close()


def test_charger_export_without_vehicle_uses_the_soc_percent_column(tmp_path):
    env = CityLearnEnv(
        str(_minute_ev_demo_schema(tmp_path)), central_agent=True, random_seed=0, render_mode='end',
        render_directory=tmp_path / 'renders', render_session_name='charger',
    )

    try:
        _run_zero_episode(env)
        charger = pd.read_csv(Path(env.new_folder_path) / 'exported_data_building_1_charger_1_1_ep0.csv')

        # charger_1_1.csv has neither a connected nor an incoming EV at time steps 4 and 5.
        assert not charger['Is EV Connected'].all()
        assert 'EV SOC' not in charger.columns
        assert charger['EV SOC-%'].notna().all()
    finally:
        env.close()


def test_train_evaluates_the_trained_agent(tmp_path):
    _TrainingRecordingAgent.trained_ids.clear()
    _TrainingRecordingAgent.evaluated_ids.clear()

    Simulator.train(
        episodes=1,
        evaluate=True,
        schema=str(_minute_ev_demo_schema(tmp_path)),
        agent_name=f'{__name__}._TrainingRecordingAgent',
        env_kwargs={'central_agent': True, 'random_seed': 0},
        time_series_variables=['net_electricity_consumption'],
        output_directory=tmp_path / 'simulation',
        simulation_id='train',
    )

    assert len(_TrainingRecordingAgent.trained_ids) == 1
    assert set(_TrainingRecordingAgent.evaluated_ids) == set(_TrainingRecordingAgent.trained_ids)
    evaluation = FileHandler.read_json(tmp_path / 'simulation' / 'train-evaluation.json')
    assert evaluation['evaluation_episode_time_steps'] == [0, 7]
    # train --evaluate also writes the evaluate_v2() table (#367).
    kpis = pd.read_csv(tmp_path / 'simulation' / 'train-evaluation_v2.csv')
    assert {'cost_function', 'value', 'name', 'level'} <= set(kpis.columns)


@pytest.mark.parametrize('evaluation_episode_time_steps', [[[1, 6]], [1, 6]], ids=['cli_pairs', 'single_pair'])
def test_evaluate_runs_with_default_time_series_and_requested_window(tmp_path, evaluation_episode_time_steps):
    Simulator.evaluate(
        evaluation_episode_time_steps=evaluation_episode_time_steps,
        schema=str(_minute_ev_demo_schema(tmp_path)),
        agent_name='citylearn.agents.baseline.BusinessAsUsualAgent',
        env_kwargs={'central_agent': True, 'random_seed': 0},
        output_directory=tmp_path / 'simulation',
        simulation_id='evaluate',
    )

    evaluation = FileHandler.read_json(tmp_path / 'simulation' / 'evaluate-evaluation.json')
    assert evaluation['evaluation_episode_time_steps'] == [1, 6]
    # Six time steps in the window, five executed: data and storage SOC series drop the terminal row.
    assert evaluation['time_series']['time_step'] == [0, 1, 2, 3, 4]
    assert len(evaluation['time_series']['electrical_storage_soc']) == 5


def test_evaluate_reports_missing_time_series_variables_as_empty(tmp_path):
    Simulator.evaluate(
        schema=str(_minute_ev_demo_schema(tmp_path)),
        agent_name='citylearn.agents.baseline.BusinessAsUsualAgent',
        env_kwargs={'central_agent': True, 'random_seed': 0},
        time_series_variables=['net_electricity_consumption', 'not_a_building_attribute'],
        output_directory=tmp_path / 'simulation',
        simulation_id='missing',
    )

    time_series = FileHandler.read_json(tmp_path / 'simulation' / 'missing-evaluation.json')['time_series']
    assert len(time_series['net_electricity_consumption']) == 7
    # It used to repeat the previous variable's series under the missing variable's name.
    assert time_series['not_a_building_attribute'] == [None]*7


def test_simulator_timestamps_do_not_require_datetime_utc(tmp_path, monkeypatch):
    # datetime.UTC exists only from Python 3.11, while CityLearn supports Python 3.9.
    monkeypatch.delattr(datetime, 'UTC', raising=False)
    Simulator.train(
        episodes=1,
        schema=str(_minute_ev_demo_schema(tmp_path)),
        agent_name='citylearn.agents.baseline.BusinessAsUsualAgent',
        env_kwargs={'central_agent': True, 'random_seed': 0},
        output_directory=tmp_path / 'simulation',
        simulation_id='utc',
    )

    summary = FileHandler.read_json(tmp_path / 'simulation' / 'utc-train.json')
    assert summary['train_start_timestamp'].endswith('+00:00')


def test_run_work_order_activates_windows_virtual_environments_with_activate_bat(tmp_path, monkeypatch):
    commands = []

    class _InlineExecutor:
        def __init__(self, max_workers=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, function, **kwargs):
            commands.append(kwargs['args'])
            future = cli.concurrent.futures.Future()
            future.set_result(None)
            return future

    monkeypatch.setattr(cli.concurrent.futures, 'ProcessPoolExecutor', _InlineExecutor)
    work_order = tmp_path / 'work_order.sh'
    work_order.write_text('echo first\n', encoding='utf-8')
    venv = tmp_path / 'venv'
    run_work_order(work_order, max_workers=1, virtual_environment_path=str(venv), windows_system=True)

    assert commands == [f'call "{os.path.join(str(venv), "Scripts", "activate.bat")}" && echo first']


@pytest.mark.skipif(os.name != 'nt', reason='runs the work order in cmd.exe')
def test_run_work_order_runs_jobs_inside_the_windows_virtual_environment(tmp_path):
    venv = tmp_path / 'venv'
    (venv / 'Scripts').mkdir(parents=True)
    (venv / 'Scripts' / 'activate.bat').write_text('@set CITYLEARN_WORK_ORDER_VENV=active\r\n', encoding='ascii')
    output = tmp_path / 'job.txt'
    python = Path(sys.executable)
    job = (
        f'"{python}" -c "import os; open(r\'{output}\', \'w\').write('
        "os.environ.get('CITYLEARN_WORK_ORDER_VENV', 'missing'))\""
    )
    work_order = tmp_path / 'work_order.txt'
    work_order.write_text(job + '\n', encoding='utf-8')

    # windows_system is not passed: the CLI has no option for it, so it must follow the OS.
    run_work_order(work_order, max_workers=1, virtual_environment_path=str(venv))

    assert output.read_text() == 'active'


def test_load_kpis_reads_multi_community_exports(tmp_path):
    community = {'central_agent': True, 'episode_time_steps': 2, 'render_mode': 'none', 'random_seed': 0}
    env = MultiCommunityEnv(
        communities=[
            {'community_id': 'community_a', 'schema': str(MINUTE_EV_DEMO / 'schema.json'), 'env_kwargs': dict(community)},
            {'community_id': 'community_b', 'schema': str(MINUTE_EV_DEMO / 'schema.json'), 'env_kwargs': dict(community)},
        ],
        render_directory=tmp_path / 'renders',
        render_session_name='multi',
    )

    try:
        env.reset(seed=0)
        env.step({
            community_id: [np.zeros(space.shape, dtype='float32') for space in child.action_space]
            for community_id, child in env.envs.items()
        })
        env.export_final_kpis(include_business_as_usual=False, export_business_as_usual_timeseries=False)
    finally:
        env.close()

    path = tmp_path / 'renders' / 'multi' / 'exported_kpis_multi_community.csv'
    exported = pd.read_csv(path)
    kpis = load_kpis(path)

    assert len(kpis) == len(exported)
    district_cost = exported[(exported['community_id'] == 'community_b') & (exported['level'] == 'district')
        & (exported['cost_function'] == 'district_cost_total_control_eur')]['value'].iloc[0]
    assert kpis[('community_b:District', 'district_cost_total_control_eur')] == pytest.approx(district_cost)
    summary = compare_exports(path, path)['outcome_summary']
    assert {'community_a:District', 'community_b:District'} <= {row['name'] for row in summary}


@pytest.mark.parametrize('handler', [FileHandler, SharedFileHandler], ids=['utilities', 'utils'])
def test_file_handlers_read_and_write_utf8(tmp_path, handler):
    # Without an explicit encoding, Python on Windows opens text files in the ANSI code page (cp1252).
    json_path = tmp_path / 'in.json'
    json_path.write_bytes(UTF8_BOM + f'{{"name": "{NON_ASCII_NAME}"}}'.encode('utf-8'))
    yaml_path = tmp_path / 'in.yaml'
    yaml_path.write_bytes(UTF8_BOM + f'name: {NON_ASCII_NAME}'.encode('utf-8'))

    assert handler.read_json(json_path) == {'name': NON_ASCII_NAME}
    assert handler.read_yaml(yaml_path) == {'name': NON_ASCII_NAME}

    handler.write_json(tmp_path / 'out.json', {'name': NON_ASCII_NAME}, ensure_ascii=False)
    handler.write_yaml(tmp_path / 'out.yaml', {'name': NON_ASCII_NAME}, allow_unicode=True)

    assert NON_ASCII_NAME.encode('utf-8') in (tmp_path / 'out.json').read_bytes()
    assert NON_ASCII_NAME.encode('utf-8') in (tmp_path / 'out.yaml').read_bytes()


def test_env_reads_non_ascii_names_from_a_utf8_schema(tmp_path):
    schema_path = _minute_ev_demo_schema(tmp_path)
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    schema['buildings'] = {NON_ASCII_NAME: schema['buildings']['Building_1']}
    schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding='utf-8')
    env = CityLearnEnv(str(schema_path), central_agent=True)

    try:
        assert [b.name for b in env.buildings] == [NON_ASCII_NAME]
    finally:
        env.close()


def test_load_agent_updates_schema_agent_attributes_with_keyword_arguments(tmp_path):
    schema = json.loads(_minute_ev_demo_schema(tmp_path).read_text(encoding='utf-8'))
    schema['agent'] = {'type': f'{__name__}._MarkerAgent', 'attributes': {'marker': 0.33}}
    env = CityLearnEnv(schema, central_agent=True)

    try:
        assert env.load_agent().marker == 0.33
        # Simulator always passes env=, which used to discard the schema attributes.
        assert env.load_agent(env=env).marker == 0.33
        assert env.load_agent(env=env, marker=0.5).marker == 0.5
        # An explicitly named agent still takes only the keyword arguments.
        assert env.load_agent(agent=_MarkerAgent, env=env).marker is None

        simulator = Simulator(schema=schema, env_kwargs={'central_agent': True}, output_directory=tmp_path / 'simulation')
        assert isinstance(simulator.agent, _MarkerAgent)
        assert simulator.agent.marker == 0.33

        env.schema['agent']['attributes'] = None
        assert env.load_agent(env=env).marker is None
    finally:
        env.close()
