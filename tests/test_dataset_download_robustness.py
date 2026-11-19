"""Dataset downloads: error responses, concurrent first downloads and the `directory` argument."""

import json
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

    assert calls.count('data/datasets/demo') == 2  # the second call downloads again
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


SCHEMA = json.dumps({'buildings': {
    f'Building_{i}': {'energy_simulation': f'Building_{i}.csv', 'weather': 'weather.csv'} for i in range(1, 7)
}}).encode()


class _RepairSession(_Session):
    """Serves a schema that names the building and weather files, and files that tell which worker downloaded them.
    Worker A pauses before its last file until worker B has started downloading; B then waits until A has returned."""

    def __init__(self):
        super().__init__()
        self.a_paused, self.b_started, self.a_returned = threading.Event(), threading.Event(), threading.Event()

    def get(self, url, **kwargs):
        worker = threading.current_thread().name

        if worker == 'A' and url.endswith(FILES[-1]):
            self.a_paused.set()
            self.b_started.wait(10)
        elif worker == 'B' and not self.b_started.is_set():
            self.b_started.set()
            self.a_returned.wait(10)

        return _response(url, content=SCHEMA if url.endswith('schema.json') else worker.encode())


def test_concurrent_repairs_of_a_cached_schema_without_its_files_keep_the_first_published_copy(tmp_path):
    # An interrupted download left schema.json in the cache with only one of the files it names. Previously the folder
    # counted as complete, so get_dataset returned it and loading failed on the first missing file.
    folder = tmp_path/'datasets'/'demo'
    folder.mkdir(parents=True)
    (folder/'schema.json').write_bytes(SCHEMA)
    (folder/'Building_1.csv').write_bytes(b'old')
    session = _RepairSession()
    dataset = _dataset_class(tmp_path, session)
    contents, errors = {}, []

    def worker(name):
        try:
            root = Path(dataset(offline=False).get_dataset('demo')).parent

            if name == 'A':
                session.a_returned.set()

            contents[name] = {n: (root/n).read_bytes() for n in FILES if n != 'schema.json'}
        except Exception as error:  # pragma: no cover - reported below
            errors.append(f'{name}: {error!r}')
        finally:
            (session.a_returned if name == 'A' else session.b_started).set()

    a = threading.Thread(target=worker, args=('A',), name='A')
    b = threading.Thread(target=worker, args=('B',), name='B')
    a.start()
    assert session.a_paused.wait(10)
    b.start()
    a.join(30)
    b.join(30)

    # A replaced the incomplete folder; B, which had also found it incomplete, kept A's complete copy.
    assert errors == []
    assert contents['A'] == contents['B'] == {n: b'A' for n in FILES if n != 'schema.json'}
    assert sorted(os.listdir(folder)) == sorted(FILES)
    assert _leftovers(tmp_path) == []


def test_a_download_lacking_files_its_schema_names_is_not_cached(tmp_path):
    # Publishing it would make every later call find the cache incomplete and download it again.
    class _SchemaSession(_Session):
        def get(self, url, **kwargs):
            return _response(url, content=SCHEMA)

    class _IncompleteDataSet(_dataset_class(tmp_path, _SchemaSession())):
        def get_github_contents(self, path=None):
            return [dict(type='file', name='schema.json', path=f'{path}/schema.json', download_url='https://raw.example/demo/schema.json')]

    with pytest.raises(FileNotFoundError, match='lacks Building_1.csv, weather.csv, Building_2.csv'):
        _IncompleteDataSet(offline=False).get_dataset('demo')

    assert not (tmp_path/'datasets'/'demo').exists()
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


def test_nested_dataset_folders_are_downloaded(tmp_path):
    # Datasets such as the Portugal REC ones keep their series in subfolders; only the root was downloaded before.
    urls = []
    trees = {
        'sha-timeseries': [
            dict(type='blob', path='members/M01.parquet'),
            dict(type='tree', path='members'),
            dict(type='blob', path='weather.parquet'),
        ],
        'sha-evaluation': [dict(type='blob', path='scenario.json')],
    }

    class _RecordingSession(_Session):
        def get(self, url, **kwargs):
            urls.append(url)
            return super().get(url, **kwargs)

    class _NestedDataSet(_dataset_class(tmp_path, _RecordingSession())):
        def get_github_contents(self, path=None):
            return [
                dict(type='file', name='schema.json', path=f'{path}/schema.json', download_url='https://raw.example/demo/schema.json'),
                dict(type='dir', name='timeseries', path=f'{path}/timeseries', sha='sha-timeseries'),
                dict(type='dir', name='evaluation', path=f'{path}/evaluation', sha='sha-evaluation'),
            ]

        def get_github_tree(self, sha):
            return trees[sha]

    dataset = _NestedDataSet(offline=False, github_account='owner', repository='repo', tag='v9')
    root = Path(dataset.get_dataset('demo')).parent

    assert sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()) == [
        'evaluation/scenario.json', 'schema.json', 'timeseries/members/M01.parquet', 'timeseries/weather.parquet',
    ]
    assert 'https://raw.githubusercontent.com/owner/repo/v9/data/datasets/demo/timeseries/members/M01.parquet' in urls


def test_dataset_paths_outside_the_dataset_are_rejected(tmp_path):
    class _EscapingDataSet(_dataset_class(tmp_path, _Session())):
        def get_github_contents(self, path=None):
            return [dict(type='dir', name='timeseries', path=f'{path}/timeseries', sha='sha')]

        def get_github_tree(self, sha):
            return [dict(type='blob', path='../../escape.csv')]

    with pytest.raises(ValueError, match='Invalid dataset path'):
        _EscapingDataSet(offline=False).get_dataset('demo')

    assert not (tmp_path/'escape.csv').exists()
    assert not (tmp_path/'datasets'/'demo').exists()


def test_github_listing_uses_the_requested_repository():
    urls = []

    class _ListingSession:
        def get(self, url, **kwargs):
            urls.append((url, kwargs.get('params')))
            response = _response(url, content=b'[]')
            return response

    class _ListingDataSet(DataSet):
        def get_requests_session(self, **kwargs):
            return _ListingSession()

    _ListingDataSet(github_account='owner', repository='repo', tag='v9', offline=False).get_github_contents('data/datasets')

    assert urls == [('https://api.github.com/repos/owner/repo/contents/data/datasets', {'ref': 'v9'})]


def test_a_nested_dataset_costs_two_github_api_requests(tmp_path):
    # Listing the dataset's parent gives its tree; one recursive tree request then lists every nested file.
    listings, trees, urls = [], [], []

    class _RecordingSession(_Session):
        def get(self, url, **kwargs):
            urls.append(url)
            return super().get(url, **kwargs)

    class _TreeDataSet(_dataset_class(tmp_path, _RecordingSession())):
        def get_github_contents(self, path=None):
            listings.append(path)
            return [
                dict(type='dir', name='other', path='data/datasets/other', sha='sha-other'),
                dict(type='dir', name='demo', path='data/datasets/demo', sha='sha-demo'),
            ]

        def get_github_tree(self, sha):
            trees.append(sha)
            return [
                dict(type='blob', path='schema.json'),
                dict(type='tree', path='timeseries'),
                dict(type='blob', path='timeseries/members/M01.parquet'),
                dict(type='tree', path='timeseries/members'),
            ]

    root = Path(_TreeDataSet(offline=False, github_account='owner', repository='repo', tag='v9').get_dataset('demo')).parent

    assert listings == ['data/datasets'] and trees == ['sha-demo']
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()) == [
        'schema.json', 'timeseries/members/M01.parquet',
    ]
    assert sorted(urls) == [
        'https://raw.githubusercontent.com/owner/repo/v9/data/datasets/demo/schema.json',
        'https://raw.githubusercontent.com/owner/repo/v9/data/datasets/demo/timeseries/members/M01.parquet',
    ]


def test_github_api_requests_use_a_token_when_set(monkeypatch):
    headers = []

    class _ListingSession:
        def get(self, url, **kwargs):
            headers.append(kwargs.get('headers'))
            return _response(url, content=b'[]')

    class _ListingDataSet(DataSet):
        def get_requests_session(self, **kwargs):
            return _ListingSession()

    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.delenv('CITYLEARN_GITHUB_TOKEN', raising=False)
    _ListingDataSet(offline=False).get_github_contents('data/datasets')
    monkeypatch.setenv('CITYLEARN_GITHUB_TOKEN', 'secret')
    _ListingDataSet(offline=False).get_github_contents('data/datasets')

    assert headers == [None, {'Authorization': 'Bearer secret'}]


def _remote_only_class(cache: Path, listing, session=None):
    """A DataSet with no local dataset or misc roots, whose GitHub listings come from `listing(path)`."""

    cache.mkdir(parents=True, exist_ok=True)

    class _RemoteOnly(DataSet):
        calls = []

        @property
        def cache_directory(self):
            return str(cache)

        @property
        def local_datasets_directories(self):
            return []

        @property
        def local_misc_directories(self):
            return []

        def get_github_contents(self, path=None):
            self.calls.append(path)
            return listing(path)

        def get_requests_session(self, **kwargs):
            return _Session() if session is None else session

    return _RemoteOnly


def test_dataset_names_are_the_direct_subfolders_of_the_datasets_path(tmp_path):
    def listing(path):
        return [
            dict(type='dir', name='a', path='data/datasets/a'),
            dict(type='dir', name='demo', path='data/datasets/demo'),
            dict(type='file', name='README.md', path='data/datasets/README.md'),
        ]

    # Previously 'a' was dropped, because removing 'a' from 'data/datasets/a' also changed the parent path, and a
    # datasets_path with a trailing slash matched nothing.
    assert _remote_only_class(tmp_path/'1', listing)(offline=False).get_dataset_names() == ['a', 'demo']
    assert _remote_only_class(tmp_path/'2', listing)(offline=False, datasets_path='data/datasets/').get_dataset_names() == ['a', 'demo']


def _first_calls_overlap(dataset, call) -> list:
    """Run `call` in workers A and B; A's GitHub listing waits up to 1 s for B's. Return the listed paths."""

    a_listing, b_listing = threading.Event(), threading.Event()
    listing = dataset.get_github_contents

    def get_github_contents(self, path=None):
        (a_listing if threading.current_thread().name == 'A' else b_listing).set()

        if threading.current_thread().name == 'A':
            b_listing.wait(1)

        return listing(self, path)

    dataset.get_github_contents = get_github_contents
    errors = []

    def worker():
        try:
            call(dataset(offline=False))
        except Exception as error:  # pragma: no cover - reported below
            errors.append(repr(error))

    a = threading.Thread(target=worker, name='A')
    b = threading.Thread(target=worker, name='B')
    a.start()
    assert a_listing.wait(10)
    b.start()
    a.join(20)
    b.join(20)
    assert errors == []

    return dataset.calls


def test_concurrent_first_listings_of_dataset_names_query_github_once(tmp_path):
    dataset = _remote_only_class(tmp_path, lambda path: [dict(type='dir', name='demo', path='data/datasets/demo')])
    calls = _first_calls_overlap(dataset, lambda d: d.get_dataset_names())

    # Previously each worker found no cached list and spent its own GitHub API request.
    assert calls == ['data/datasets']
    assert json.loads((tmp_path/'dataset_names.json').read_text()) == ['demo']


def test_concurrent_first_requests_for_sizing_data_download_it_once(tmp_path):
    def listing(path):
        return [dict(type='file', name=DataSet.BATTERY_CHOICES_FILENAME, download_url='https://raw.example/battery.yaml')]

    class _YamlSession(_Session):
        def get(self, url, **kwargs):
            return _response(url, content=b'model_a:\n  attributes:\n    capacity: 1.0\n')

    dataset = _remote_only_class(tmp_path, listing, _YamlSession())
    calls = _first_calls_overlap(dataset, lambda d: d.get_battery_sizing_data())

    assert calls == ['data/misc']
    assert [p.name for p in (tmp_path/'misc').iterdir() if p.suffix != '.lock'] == ['battery_choices.yaml']


def test_sizing_data_missing_from_the_repository_raises_a_clear_error(tmp_path):
    dataset = _remote_only_class(tmp_path, lambda path: [dict(type='file', name='other.csv', download_url='https://raw.example/other.csv')])

    # Previously an IndexError.
    with pytest.raises(FileNotFoundError, match="'lbl-tracking_the_sun-res-pv.csv' is not in data/misc"):
        dataset(offline=False).get_pv_sizing_data()
