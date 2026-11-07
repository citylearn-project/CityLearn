"""Dataset downloads: error responses, concurrent first downloads and the `directory` argument."""

import os
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
    datasets = cache/'datasets'
    return [p.name for p in datasets.iterdir() if p.name.startswith('.')] if datasets.is_dir() else []


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
