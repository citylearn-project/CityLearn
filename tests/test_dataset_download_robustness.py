"""Dataset downloads: error responses, concurrent first downloads and the `directory` argument."""

import os
import shutil
import threading
import time
from pathlib import Path

import pytest
import requests

from citylearn.data import DataSet

pytestmark = pytest.mark.use_real_dataset_resolution
FILES = [f'Building_{i}.csv' for i in range(1, 7)] + ['weather.csv', 'schema.json']


def _response(url: str, status: int = 200, content: bytes = b'a,b\n1,2\n') -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = content
    response.url = url
    response.reason = 'OK' if status == 200 else 'Too Many Requests'
    return response


class _Session:
    def __init__(self, failing: str = None, delay: float = 0.0):
        self.failing = failing
        self.delay = delay

    def get(self, url, **kwargs):
        time.sleep(self.delay)
        if self.failing is not None and url.endswith(self.failing):
            return _response(url, 429, b'{"message": "API rate limit exceeded"}')
        return _response(url, content=b'{"buildings": {}}' if url.endswith('schema.json') else b'a,b\n1,2\n')


def _dataset_class(cache: Path, session: _Session, listing_calls: list = None):
    class _DataSet(DataSet):
        @property
        def cache_directory(self):
            return str(cache)

        def _find_local_dataset_root(self, name):
            return None  # force the download path

        def get_github_contents(self, path=None):
            if listing_calls is not None:
                listing_calls.append(path)
            return [dict(type='file', name=n, path=f'data/datasets/demo/{n}', download_url=f'https://raw.example/demo/{n}')
                    for n in FILES]

        def get_requests_session(self, **kwargs):
            return session

    return _DataSet


def _leftovers(cache: Path) -> list:
    """Hidden staging or stale folders left in the cache (the lock files stay)."""

    datasets = cache/'datasets'
    return [p.name for p in datasets.iterdir() if p.name.startswith('.') and p.suffix != '.lock'] if datasets.is_dir() else []


def test_error_response_raises_and_is_not_cached(tmp_path):
    calls = []
    failing = _dataset_class(tmp_path, _Session(failing='Building_3.csv'), calls)

    with pytest.raises(requests.HTTPError):
        failing(offline=False).get_dataset('demo')

    # Previously the 429 body was saved as Building_3.csv and the dataset counted as cached.
    assert not (tmp_path/'datasets'/'demo').exists()
    assert _leftovers(tmp_path) == []

    working = _dataset_class(tmp_path, _Session(), calls)
    schema = working(offline=False).get_dataset('demo')

    assert len(calls) == 2  # the second call downloads again
    assert Path(schema).read_bytes() == b'{"buildings": {}}'
    assert (Path(schema).parent/'Building_3.csv').read_bytes() == b'a,b\n1,2\n'


class _InterleavingSession(_Session):
    """Worker A pauses half-way through its download until worker B has started downloading;
    B then waits until A has checked the files that its returned dataset holds."""

    def __init__(self):
        super().__init__()
        self.a_paused, self.b_started, self.a_checked = threading.Event(), threading.Event(), threading.Event()
        self.a_calls = 0

    def get(self, url, **kwargs):
        if threading.current_thread().name == 'A':
            self.a_calls += 1
            if self.a_calls == len(FILES)//2:
                self.a_paused.set()
                self.b_started.wait(5)
        elif not self.b_started.is_set():
            self.b_started.set()
            self.a_checked.wait(5)
        return super().get(url, **kwargs)


def test_concurrent_first_downloads_both_get_a_complete_dataset(tmp_path):
    session = _InterleavingSession()
    dataset = _dataset_class(tmp_path, session)
    missing, errors = {}, []

    def worker(name):
        try:
            root = Path(dataset(offline=False).get_dataset('demo')).parent
            missing[name] = [n for n in FILES if not (root/n).is_file()]
        except Exception as error:  # pragma: no cover - reported below
            errors.append(repr(error))
        finally:
            if name == 'A':
                session.a_checked.set()

    a = threading.Thread(target=worker, args=('A',), name='A')
    b = threading.Thread(target=worker, args=('B',), name='B')
    a.start()
    assert session.a_paused.wait(5)
    b.start()
    a.join(10)
    b.join(10)

    # Previously B deleted the cache folder that A was still filling, so A returned an incomplete dataset.
    assert errors == []
    assert missing == {'A': [], 'B': []}
    assert sorted(os.listdir(tmp_path/'datasets'/'demo')) == sorted(FILES)
    assert _leftovers(tmp_path) == []


class _StaleFolderSession(_Session):
    """Worker A pauses before downloading its last file until worker B has got past its check of the cache folder."""

    def __init__(self):
        super().__init__()
        self.a_paused, self.b_checked = threading.Event(), threading.Event()

    def get(self, url, **kwargs):
        if threading.current_thread().name == 'A' and url.endswith(FILES[-1]):
            self.a_paused.set()
            self.b_checked.wait(5)
        return super().get(url, **kwargs)


def test_concurrent_downloads_replacing_an_incomplete_folder_keep_the_published_dataset(tmp_path, monkeypatch):
    # An interrupted download by CityLearn <= 3.2.0, which wrote into the cache folder in listing order, left it
    # without schema.json.
    folder = tmp_path/'datasets'/'demo'
    folder.mkdir(parents=True)

    for n in FILES[:2]:
        (folder/n).write_bytes(b'a,')

    session = _StaleFolderSession()
    dataset = _dataset_class(tmp_path, session)
    a_returned, b_removed, a_checked = threading.Event(), threading.Event(), threading.Event()
    rmtree = shutil.rmtree

    def interleaving_rmtree(path, *args, **kwargs):
        # B removes the folder it found incomplete only once A has published and returned its dataset, and moves its
        # own copy into place only once A has read that dataset.
        if threading.current_thread().name == 'B' and Path(path) == folder:
            session.b_checked.set()
            a_returned.wait(5)
            rmtree(path, *args, **kwargs)
            b_removed.set()
            a_checked.wait(5)
        else:
            rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, 'rmtree', interleaving_rmtree)
    missing, errors = {}, []

    def worker(name):
        try:
            schema = Path(dataset(offline=False).get_dataset('demo'))

            if name == 'A':
                a_returned.set()
                b_removed.wait(5)

            schema.read_bytes()
            missing[name] = [n for n in FILES if not (schema.parent/n).is_file()]
        except Exception as error:  # pragma: no cover - reported below
            errors.append(f'{name}: {error!r}')
        finally:
            for event in ([a_returned, a_checked] if name == 'A' else [session.b_checked, b_removed]):
                event.set()

    a = threading.Thread(target=worker, args=('A',), name='A')
    b = threading.Thread(target=worker, args=('B',), name='B')
    a.start()
    assert session.a_paused.wait(5)
    b.start()
    a.join(20)
    b.join(20)

    # Previously B, which had found the folder incomplete, deleted the complete dataset that A had just published and
    # returned, so A's schema.json did not exist when A opened it.
    assert errors == []
    assert missing == {'A': [], 'B': []}
    assert sorted(os.listdir(folder)) == sorted(FILES)
    assert (folder/FILES[0]).read_bytes() == b'a,b\n1,2\n'
    assert _leftovers(tmp_path) == []


def test_directory_argument_returns_an_existing_schema(tmp_path):
    dataset = _dataset_class(tmp_path/'cache', _Session())
    schema = Path(dataset(offline=False).get_dataset('demo', directory=tmp_path/'copy'))

    assert schema == tmp_path/'copy'/'demo'/'schema.json'
    assert schema.is_file()
    assert sorted(p.name for p in schema.parent.iterdir()) == sorted(FILES)


def test_requests_retry_rate_limits():
    retry = DataSet.get_requests_session().get_adapter('https://').max_retries

    assert 429 in retry.status_forcelist
    assert retry.respect_retry_after_header


def test_incomplete_cached_dataset_with_schema_recovers_from_local_source_offline(tmp_path, monkeypatch):
    from citylearn.citylearn import CityLearnEnv

    minute_demo = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'
    cache_root = tmp_path / 'cache'
    cached_demo = cache_root / 'datasets' / 'minute_ev_demo'
    cached_demo.mkdir(parents=True)
    shutil.copyfile(minute_demo / 'schema.json', cached_demo / 'schema.json')

    local_root = tmp_path / 'local_datasets'
    shutil.copytree(minute_demo, local_root / 'minute_ev_demo')

    monkeypatch.setattr(DataSet, 'cache_directory', property(lambda self: str(cache_root)))
    monkeypatch.setenv('CITYLEARN_LOCAL_DATASETS_PATH', str(local_root))
    monkeypatch.setattr(
        DataSet,
        'get_requests_session',
        staticmethod(lambda **kw: (_ for _ in ()).throw(AssertionError('Unexpected network call'))),
    )

    schema = DataSet(offline=True).get_schema('minute_ev_demo')
    env = CityLearnEnv(schema, offline=True, central_agent=True, episode_time_steps=2, render_mode='none')

    try:
        observations, _ = env.reset()
        assert len(observations) == 1
        assert (cached_demo / 'Building_1.csv').is_file()
        assert (cached_demo / 'charger_1_1.csv').is_file()
        assert _leftovers(cache_root) == []
    finally:
        env.close()

    # Also verify direct resolution by dataset name through CityLearnEnv when cache only has schema.json.
    shutil.rmtree(cached_demo)
    cached_demo.mkdir(parents=True)
    shutil.copyfile(minute_demo / 'schema.json', cached_demo / 'schema.json')

    env_by_name = CityLearnEnv('minute_ev_demo', offline=True, central_agent=True, episode_time_steps=2, render_mode='none')
    try:
        assert len(env_by_name.buildings) == 1
        assert (cached_demo / 'Building_1.csv').is_file()
        assert _leftovers(cache_root) == []
    finally:
        env_by_name.close()


def test_incomplete_cached_dataset_with_schema_raises_clear_error_when_unrecoverable(tmp_path, monkeypatch):
    from citylearn.citylearn import CityLearnEnv, UnknownSchemaError
    from citylearn.data import OfflineDataError

    minute_demo = Path(__file__).resolve().parent / 'data' / 'minute_ev_demo'
    cache_root = tmp_path / 'cache'
    cached_demo = cache_root / 'datasets' / 'minute_ev_demo'
    cached_demo.mkdir(parents=True)
    shutil.copyfile(minute_demo / 'schema.json', cached_demo / 'schema.json')

    empty_local_root = tmp_path / 'empty_local'
    empty_local_root.mkdir()
    monkeypatch.setattr(DataSet, 'cache_directory', property(lambda self: str(cache_root)))
    monkeypatch.setenv('CITYLEARN_LOCAL_DATASETS_PATH', str(empty_local_root))

    with pytest.raises(OfflineDataError, match=r'minute_ev_demo.*Building_1\.csv'):
        DataSet(offline=True).get_schema('minute_ev_demo')

    with pytest.raises(UnknownSchemaError, match=r'minute_ev_demo.*offline mode is enabled.*Building_1\.csv'):
        CityLearnEnv('minute_ev_demo', offline=True, central_agent=True, episode_time_steps=2, render_mode='none')

    # Online download that omits a referenced file must fail before publishing an incomplete folder.
    schema_bytes = (
        b'{"buildings": {"Building_1": {"include": true, "energy_simulation": "Building_1.csv", "weather": "weather.csv"}}}'
    )

    class _IncompleteRemoteSession(_Session):
        def get(self, url, **kwargs):
            return _response(url, content=schema_bytes if url.endswith('schema.json') else b'a,b\n1,2\n')

    class _IncompleteRemoteDataSet(_dataset_class(tmp_path / 'online_cache', _IncompleteRemoteSession())):
        def get_github_contents(self, path=None):
            return [
                dict(type='file', name='schema.json', path='data/datasets/demo/schema.json', download_url='https://raw.example/demo/schema.json'),
                dict(type='file', name='weather.csv', path='data/datasets/demo/weather.csv', download_url='https://raw.example/demo/weather.csv'),
            ]

    with pytest.raises(FileNotFoundError, match=r'Building_1\.csv'):
        _IncompleteRemoteDataSet(offline=False).get_dataset('demo')

    assert not (tmp_path / 'online_cache' / 'datasets' / 'demo').exists()
    assert _leftovers(tmp_path / 'online_cache') == []


def test_concurrent_downloads_replacing_incomplete_folder_with_schema_keep_published_dataset(tmp_path):
    import json

    schema_doc = {
        'buildings': {
            f'Building_{i}': {
                'include': True,
                'energy_simulation': f'Building_{i}.csv',
                'weather': 'weather.csv',
            }
            for i in range(1, 7)
        }
    }
    schema_bytes = json.dumps(schema_doc).encode('utf-8')
    folder = tmp_path / 'datasets' / 'demo'
    folder.mkdir(parents=True)
    (folder / 'schema.json').write_bytes(schema_bytes)
    (folder / 'Building_1.csv').write_bytes(b'partial')

    class _SchemaAwareStaleSession(_StaleFolderSession):
        def get(self, url, **kwargs):
            if threading.current_thread().name == 'A' and url.endswith(FILES[-1]):
                self.a_paused.set()
                self.b_checked.wait(5)
            return _response(url, content=schema_bytes if url.endswith('schema.json') else b'a,b\n1,2\n')

    session = _SchemaAwareStaleSession()
    dataset = _dataset_class(tmp_path, session)
    a_returned, a_checked = threading.Event(), threading.Event()
    missing, errors = {}, []

    orig_is_complete = DataSet._is_complete_dataset_directory

    class _InterleavedDataSet(dataset):
        @classmethod
        def _is_complete_dataset_directory(cls, directory):
            result = orig_is_complete(directory)
            if threading.current_thread().name == 'B' and not session.b_checked.is_set():
                session.b_checked.set()
                a_returned.wait(5)
            return result

    def worker(name):
        try:
            schema = Path(_InterleavedDataSet(offline=False).get_dataset('demo'))
            if name == 'A':
                a_returned.set()
            schema.read_bytes()
            missing[name] = [n for n in FILES if not (schema.parent / n).is_file()]
        except Exception as error:  # pragma: no cover
            errors.append(f'{name}: {error!r}')
        finally:
            for event in ([a_returned, a_checked] if name == 'A' else [session.b_checked]):
                event.set()

    a = threading.Thread(target=worker, args=('A',), name='A')
    b = threading.Thread(target=worker, args=('B',), name='B')
    a.start()
    assert session.a_paused.wait(5)
    b.start()
    a.join(20)
    b.join(20)

    assert errors == []
    assert missing == {'A': [], 'B': []}
    assert sorted(os.listdir(folder)) == sorted(FILES)
    assert (folder / 'Building_1.csv').read_bytes() == b'a,b\n1,2\n'
    assert _leftovers(tmp_path) == []


def test_dataset_and_env_respect_dynamic_env_vars_and_custom_repo(tmp_path, monkeypatch):
    from citylearn.citylearn import CityLearnEnv, UnknownSchemaError

    monkeypatch.setenv('CITYLEARN_OFFLINE', '1')
    monkeypatch.setenv('CITYLEARN_DATASET_GITHUB_ACCOUNT', 'custom-org')
    monkeypatch.setenv('CITYLEARN_DATASET_REPOSITORY', 'custom-repo')
    monkeypatch.setenv('CITYLEARN_DATASET_TAG', 'v9.9.9')

    ds = DataSet()
    assert ds.offline is True
    assert ds.github_account == 'custom-org'
    assert ds.repository == 'custom-repo'
    assert ds.tag == 'v9.9.9'

    monkeypatch.setattr(DataSet, 'cache_directory', property(lambda self: str(tmp_path / 'cache')))
    with pytest.raises(UnknownSchemaError, match='offline mode is enabled'):
        CityLearnEnv('nonexistent_env_offline_check', central_agent=True, episode_time_steps=2, render_mode='none')

    captured = {}

    class _CaptureSession:
        def get(self, url, params=None, **kwargs):
            captured['url'] = url
            captured['params'] = params
            return _response(url, content=b'[]')

    custom = DataSet(github_account='fork-owner', repository='ForkRepo', tag='v1.0.0', offline=False)
    monkeypatch.setattr(custom, 'get_requests_session', lambda **kw: _CaptureSession())
    assert custom.get_github_contents('data/datasets') == []
    assert captured['url'] == 'https://api.github.com/repos/fork-owner/ForkRepo/contents/data/datasets'
    assert captured['params'] == {'ref': 'v1.0.0'}


def test_nested_subdirectory_download_and_dataset_names_prefix(tmp_path, monkeypatch):
    schema_bytes = (
        b'{"buildings": {"Building_1": {"include": true, "energy_simulation": "Building_1.csv", "weather": "shared/weather.csv"}}}'
    )

    class _NestedSession(_Session):
        def get(self, url, **kwargs):
            return _response(url, content=schema_bytes if url.endswith('schema.json') else b'a,b\n1,2\n')

    class _NestedDataSet(DataSet):
        @property
        def cache_directory(self):
            return str(tmp_path / 'cache')

        @property
        def local_datasets_directories(self):
            return []

        @property
        def local_misc_directories(self):
            return []

        def get_github_contents(self, path=None):
            if path == 'data/datasets':
                return [
                    dict(type='dir', name='data', path='data/datasets/data'),
                    dict(type='dir', name='nested_demo', path='data/datasets/nested_demo'),
                ]
            if path == 'data/datasets/nested_demo':
                return [
                    dict(type='file', name='schema.json', path='data/datasets/nested_demo/schema.json', download_url='https://raw.example/nested_demo/schema.json'),
                    dict(type='file', name='Building_1.csv', path='data/datasets/nested_demo/Building_1.csv', download_url='https://raw.example/nested_demo/Building_1.csv'),
                    dict(type='dir', name='shared', path='data/datasets/nested_demo/shared'),
                ]
            if path == 'data/datasets/nested_demo/shared':
                return [
                    dict(type='file', name='weather.csv', path='data/datasets/nested_demo/shared/weather.csv', download_url='https://raw.example/nested_demo/shared/weather.csv'),
                ]
            if path == 'data/misc':
                return []
            raise AssertionError(f'Unexpected path: {path}')

        def get_requests_session(self, **kwargs):
            return _NestedSession()

    ds = _NestedDataSet(offline=False)
    assert ds.get_dataset_names() == ['data', 'nested_demo']

    schema_file = Path(ds.get_dataset('nested_demo'))
    assert (schema_file.parent / 'shared' / 'weather.csv').is_file()

    with pytest.raises(FileNotFoundError, match=r'lbl-tracking_the_sun-res-pv\.csv'):
        ds.get_pv_sizing_data()

