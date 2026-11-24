"""A cached dataset counts only when the files its loading reads exist (issue #176)."""

import builtins
import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet, OfflineDataError
from citylearn.internal import temporal

pytestmark = pytest.mark.use_real_dataset_resolution
ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_DEMO = ROOT/'tests'/'data'/'minute_ev_demo'


def _no_network(*args, **kwargs):
    raise AssertionError('Offline tests must not use the network.')


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """A private cache and an empty local datasets root; the network is unavailable."""

    cache, local = tmp_path/'cache', tmp_path/'local'
    local.mkdir()
    monkeypatch.setattr('citylearn.data.user_cache_dir', lambda **kwargs: str(cache))
    monkeypatch.setenv('CITYLEARN_LOCAL_DATASETS_PATH', str(local))
    monkeypatch.setattr(DataSet, 'get_requests_session', staticmethod(_no_network))
    return cache/'datasets', local


def _content_root(datasets: Path, local_root: Path) -> Path:
    """The cache folder that a complete local dataset folder is copied to."""

    return datasets.parent/DataSet.CONTENT_CACHE_DIRECTORY/DataSet._content_key(local_root)/local_root.name


def _copy(source: Path, target: Path, **schema_changes) -> Path:
    shutil.copytree(source, target)

    if schema_changes:
        schema = json.loads((target/'schema.json').read_text())
        schema.update(schema_changes)
        (target/'schema.json').write_text(json.dumps(schema))

    return target


def _env(name: str) -> CityLearnEnv:
    return CityLearnEnv(name, offline=True, central_agent=True, episode_time_steps=2, render_mode='none')


def test_a_cached_schema_without_its_files_is_repaired_from_a_complete_local_copy(roots):
    # An interrupted download left schema.json in the cache without Building_1.csv. Previously the cache counted as
    # complete and the environment failed with FileNotFoundError on Building_1.csv, offline as well as online.
    cache, local = roots
    _copy(MINUTE_EV_DEMO, local/'demo')
    (_copy(MINUTE_EV_DEMO, cache/'demo')/'Building_1.csv').unlink()

    env = _env('demo')

    assert len(env.buildings) == 1
    # The complete local copy is cached under its content key; the incomplete copy is no longer read.
    cached = _content_root(cache, local/'demo')
    assert Path(env.root_directory).resolve() == cached.resolve()
    assert (cached/'Building_1.csv').read_bytes() == (MINUTE_EV_DEMO/'Building_1.csv').read_bytes()
    assert not any(p.name.startswith('.demo-') for p in cached.parent.iterdir())


def test_a_damaged_content_keyed_copy_is_repaired_from_the_local_copy(roots):
    cache, local = roots
    _copy(MINUTE_EV_DEMO, local/'demo')
    cached = Path(DataSet(offline=True).get_dataset('demo')).parent
    (cached/'Building_1.csv').unlink()

    env = _env('demo')

    assert len(env.buildings) == 1
    assert Path(env.root_directory).resolve() == cached.resolve()
    assert (cached/'Building_1.csv').read_bytes() == (MINUTE_EV_DEMO/'Building_1.csv').read_bytes()
    assert not any(p.name.startswith('.demo-') for p in cached.parent.iterdir())


def test_an_incomplete_cache_without_a_local_copy_raises_a_clear_error_offline(roots):
    cache, local = roots
    (_copy(MINUTE_EV_DEMO, cache/'demo')/'Building_1.csv').unlink()
    (_copy(MINUTE_EV_DEMO, local/'demo')/'charger_1_1.csv').unlink()

    with pytest.raises(OfflineDataError) as error:
        DataSet(offline=True).get_dataset('demo')

    message = str(error.value)
    assert f"cached copy at '{cache/'demo'}' lacks Building_1.csv" in message
    assert f"local copy at '{(local/'demo').resolve()}' lacks charger_1_1.csv" in message
    assert str(local) in message
    assert not (cache/'demo'/'Building_1.csv').exists()


def test_a_file_name_in_free_text_is_not_required(roots):
    cache, local = roots
    _copy(MINUTE_EV_DEMO, local/'demo', notes='see README.txt')

    assert 'demo' in DataSet(offline=True).get_dataset_names()
    assert len(_env('demo').buildings) == 1
    assert len(_env('demo').buildings) == 1  # from the cache
    assert not (_content_root(cache, local/'demo')/'README.txt').exists()


def test_a_missing_file_of_an_excluded_building_is_not_required(roots):
    cache, local = roots
    schema = json.loads((MINUTE_EV_DEMO/'schema.json').read_text())
    excluded = {**schema['buildings']['Building_1'], 'include': False, 'energy_simulation': 'Building_2.csv'}
    _copy(MINUTE_EV_DEMO, local/'demo', buildings={**schema['buildings'], 'Building_2': excluded})

    assert 'demo' in DataSet(offline=True).get_dataset_names()
    assert [b.name for b in _env('demo').buildings] == ['Building_1']
    assert [b.name for b in _env('demo').buildings] == ['Building_1']  # from the cache


# Representative datasets, with the number of buildings kept (None: all): CSV with an EV charger; a challenge dataset
# with LSTM dynamics; a dynamic three-phase topology in Parquet whose excluded building still loads; nested Portugal REC
# Parquet files; occupant models (two buildings, which take 1 s instead of 15 s); demand-response requests; robustness
# events.
DATASETS = [
    (MINUTE_EV_DEMO, None),
    (ROOT/'data'/'datasets'/'citylearn_challenge_2023_phase_3_1', None),
    (ROOT/'data'/'datasets'/'citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet', None),
    (ROOT/'data'/'datasets'/'pt_rec_4', None),
    (ROOT/'data'/'datasets'/'quebec_neighborhood_with_demand_response_set_points', 2),
    (ROOT/'data'/'datasets'/'citylearn_challenge_2022_phase_all_demand_response', None),
    (ROOT/'data'/'datasets'/'citylearn_challenge_2022_phase_all_robustness', None),
]


def _key(path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


@pytest.mark.parametrize('dataset, buildings', DATASETS, ids=[d.name for d, _ in DATASETS])
def test_the_completeness_check_lists_exactly_the_files_construction_reads(dataset, buildings, monkeypatch):
    # Record every dataset file that constructing the environment opens, through Python's open, pandas or pyarrow. The
    # input snapshot hashes every file name in the schema when the file exists, needed or not, so it is not recorded.
    import pyarrow.parquet as pq

    opened, hashing = set(), []

    def recording(function):
        def wrapper(*args, **kwargs):
            if not hashing and args and isinstance(args[0], (str, os.PathLike)):
                opened.add(_key(args[0]))
            return function(*args, **kwargs)
        return wrapper

    def sha256(path):
        hashing.append(path)
        try:
            return original_sha256(path)
        finally:
            hashing.pop()

    original_sha256 = temporal.sha256
    monkeypatch.setattr(temporal, 'sha256', sha256)
    monkeypatch.setattr(builtins, 'open', recording(builtins.open))
    monkeypatch.setattr(pd, 'read_csv', recording(pd.read_csv))
    monkeypatch.setattr(pd, 'read_parquet', recording(pd.read_parquet))
    monkeypatch.setattr(pq, 'ParquetFile', recording(pq.ParquetFile))
    monkeypatch.setattr(pq, 'read_table', recording(pq.read_table))
    # Load the schema like DataSet.get_schema, with the dataset folder as root.
    schema = json.loads((dataset/'schema.json').read_text(encoding='utf-8'))
    schema['root_directory'] = str(dataset)
    schema['buildings'] = dict(list(schema['buildings'].items())[:buildings])
    CityLearnEnv(schema, offline=True, render_mode='none')
    root = _key(dataset)
    read = {p for p in opened if p.startswith(root + os.sep)} - {_key(dataset/'schema.json')}
    listed = {_key(os.path.join(dataset, f)) for f in DataSet._dataset_input_files(schema, str(dataset))}

    assert read, 'nothing recorded'
    assert sorted(read - listed) == [], 'read but not checked'
    assert sorted(listed - read) == [], 'checked but not read'
