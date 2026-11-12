"""Paired-experiment evidence must not depend on the platform or checkout location.

A Windows checkout used to record `\\` in `engine.source_sha256` keys, CRLF bytes in the
engine and data hashes, and machine-specific absolute paths, because `canonical()`
stripped the dataset root only when it was followed by `/`.
"""
import json
import ntpath
import os
import posixpath
import shutil
import subprocess
from pathlib import Path

import pytest

from citylearn.internal.comparison import canonical, compare_exports, digest, file_key, relative_to_root, source_sha256
from test_deferrable_appliance_integration import _schema_with_deferrable_appliance
from test_experiment_comparison import export_run

REPOSITORY = Path(__file__).resolve().parents[1]


def _v1_posix(value, root):
    """The paired-experiment-v1 prefix rule, which POSIX evidence keeps."""
    return value[len(root.rstrip('/')) + 1:] if value.startswith(root.rstrip('/') + '/') else None


@pytest.mark.parametrize('value,root', [
    ('/data/set/Building_1.csv', '/data/set'),
    ('/data/set/sub/x.csv', '/data/set/'),
    ('/data/set//x.csv', '/data/set'),
    ('/data/set', '/data/set'),
    ('/data/settings/x.csv', '/data/set'),
    ('/x.csv', '/'),
    ('/Data/Set/x.csv', '/data/set'),
    ('/data/set/a\\b.csv', '/data/set'),
    ('Building_1', '/data/set'),
    ('', '/data/set'),
])
def test_posix_root_stripping_is_unchanged(value, root):
    assert relative_to_root(value, root, path=posixpath) == _v1_posix(value, root)


@pytest.mark.parametrize('value,expected', [
    ('C:\\data\\set\\sub\\x.csv', 'sub/x.csv'),
    ('C:/data/set/sub/x.csv', 'sub/x.csv'),
    ('c:\\DATA\\Set\\x.csv', 'x.csv'),
    ('C:\\data\\settings\\x.csv', None),
    ('C:\\data\\set', None),
    ('D:\\data\\set\\x.csv', None),
    ('Building_1', None),
])
def test_windows_root_stripping_accepts_both_separators_and_any_case(value, expected):
    assert relative_to_root(value, 'C:\\data\\set', path=ntpath) == expected
    assert relative_to_root(value, 'C:\\data\\set\\', path=ntpath) == expected


# `file_key(reference, resolved, root)`: `resolved` stands in for the filesystem's answer, which
# `snapshot_inputs` records as the file's resolved path (spelled as on disk on Windows).
@pytest.mark.parametrize('reference,resolved', [
    ('Building_1.csv', '/data/set/Building_1.csv'),
    ('sub/x.csv', '/data/set/sub/x.csv'),
    ('./x.csv', '/data/set/x.csv'),
    ('sub/../x.csv', '/data/set/x.csv'),
    ('sub//x.csv', '/data/set/sub/x.csv'),
    ('Weather.csv', '/data/set/Weather.csv'),  # macOS: realpath keeps the case of the reference
    ('a\\b.csv', '/data/set/a\\b.csv'),  # `\` is part of a POSIX file name
    ('link.csv', '/elsewhere/target.csv'),
    ('/data/set/sub/x.csv', '/data/set/sub/x.csv'),
    ('/data/set/link.csv', '/elsewhere/x.csv'),
    ('/Data/Set/x.csv', '/Data/Set/x.csv'),
    ('/elsewhere/x.csv', '/elsewhere/x.csv'),
])
def test_posix_file_keys_are_the_v1_text(reference, resolved):
    v1 = _v1_posix(reference, '/data/set')
    assert file_key(reference, resolved, '/data/set', path=posixpath) == (reference if v1 is None else v1)


WINDOWS_ROOT = 'C:\\datasets\\demo'
WEATHER = WINDOWS_ROOT + '\\sub\\weather.csv'


@pytest.mark.parametrize('reference', [
    'sub/weather.csv', 'sub\\weather.csv', 'sub\\Weather.csv', 'SUB/WEATHER.CSV',
    'C:\\datasets\\demo\\sub\\weather.csv', 'C:\\datasets\\demo\\sub\\Weather.csv',
    'c:/DATASETS/Demo/Sub/weather.csv',
])
def test_windows_spellings_of_one_file_get_its_on_disk_key(reference):
    assert file_key(reference, WEATHER, WINDOWS_ROOT, path=ntpath) == 'sub/weather.csv'


@pytest.mark.parametrize('reference,resolved,key', [
    ('.\\sub\\weather.csv', WEATHER, './sub/weather.csv'),
    ('sub\\..\\sub\\Weather.csv', WEATHER, 'sub/../sub/Weather.csv'),
    ('sub\\\\weather.csv', WEATHER, 'sub//weather.csv'),
    ('SUB\\WEATHE~1.CSV', WEATHER, 'SUB/WEATHE~1.CSV'),
    ('sub\\link.csv', 'D:\\elsewhere\\weather.csv', 'sub/link.csv'),
    ('D:\\elsewhere\\Weather.csv', 'D:\\elsewhere\\weather.csv', 'D:/elsewhere/Weather.csv'),
    # In a folder with case sensitivity enabled both files can exist; each keeps its own name.
    ('Weather.csv', WINDOWS_ROOT + '\\Weather.csv', 'Weather.csv'),
    ('weather.csv', WINDOWS_ROOT + '\\weather.csv', 'weather.csv'),
])
def test_windows_other_spellings_keep_their_text(reference, resolved, key):
    assert file_key(reference, resolved, WINDOWS_ROOT, path=ntpath) == key


def test_canonical_strips_the_platform_root(tmp_path):
    root = str(tmp_path.resolve())
    value = os.path.join(root, 'sub', 'x.csv')
    assert canonical({'file': value, 'name': 'Building_1', 'files': [value]}, root) == \
        {'file': 'sub/x.csv', 'name': 'Building_1', 'files': ['sub/x.csv']}


def test_canonical_writes_input_file_references_as_their_keys():
    files = {'sub\\Weather.csv': 'sub/weather.csv'}
    schema = {'weather': 'sub\\Weather.csv', 'pricing': ['sub\\Weather.csv'], 'name': 'sub\\Weather'}
    assert canonical(schema, '/data/set', files) == \
        {'weather': 'sub/weather.csv', 'pricing': ['sub/weather.csv'], 'name': 'sub\\Weather'}


def test_source_digest_ignores_separators_and_line_endings(tmp_path):
    files = {'a.py': 'X = """a\nb"""\n', 'sub/b.py': 'def f(y):\n    return y + 1\n'}
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(text.encode())
    import hashlib
    linux = digest({name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()})
    assert source_sha256(tmp_path) == linux
    for newline in ('\r\n', '\r'):
        for name, text in files.items():
            (tmp_path / name).write_bytes(text.replace('\n', newline).encode())
        assert source_sha256(tmp_path) == linux
    (tmp_path / 'sub/b.py').write_bytes(b'def f(y):\n    return y + 2\n')
    assert source_sha256(tmp_path) != linux


def _absolute_references(schema_path):
    """Rewrite every schema file reference as an absolute, platform-native path."""
    root = schema_path.parent.resolve()

    def rewrite(value):
        if isinstance(value, dict):
            return {k: rewrite(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v) for v in value]
        if isinstance(value, str) and value and (root / value).is_file():
            return str(root / value)
        return value

    schema = rewrite(json.loads(schema_path.read_text()))
    schema['root_directory'] = str(root)
    schema_path.write_text(json.dumps(schema))
    return schema


def test_absolute_references_pair_across_locations_and_converted_data_does_not(tmp_path):
    schema_path = _schema_with_deferrable_appliance(tmp_path / 'a')
    copies = [schema_path.parent, tmp_path / 'b' / 'relocated', tmp_path / 'c' / 'converted']
    for copy in copies[1:]:
        shutil.copytree(copies[0], copy)
    paths = [_absolute_references(copy / 'schema.json') for copy in copies]
    assert os.path.isabs(paths[0]['buildings']['Building_1']['energy_simulation'])
    weather = copies[2] / 'weather.csv'
    lf = weather.read_bytes().replace(b'\r\n', b'\n')
    weather.write_bytes(lf if lf != weather.read_bytes() else lf.replace(b'\n', b'\r\n'))

    a, b, c = (export_run(copy / 'schema.json', tmp_path / f'out-{i}', identity=f'controller-{i}')
               for i, copy in enumerate(copies))
    report = compare_exports(a, b)
    assert report['status'] == 'paired', report
    context = json.loads(a.with_suffix('.manifest.json').read_text())['comparison_context']
    assert 'Building_1.csv' in context['data_files_sha256']
    # Line endings are content: the hash is of the bytes the simulator read, so a converted
    # copy is reported even though pandas parses it to the same frame.
    report = compare_exports(a, c)
    assert report['status'] == 'incompatible' and report['mismatches'] == ['data_files_sha256'], report
    assert all(r['delta_right_minus_left'] in (None, 0.) for r in report['kpis'])


@pytest.mark.skipif(os.name != 'nt', reason='Only Windows reads `\\` as a separator and ignores case')
def test_windows_spellings_of_one_data_file_pair(tmp_path):
    root = _schema_with_deferrable_appliance(tmp_path).parent.resolve()
    (root / 'sub').mkdir()
    (root / 'weather.csv').rename(root / 'sub' / 'weather.csv')
    schema = json.loads((root / 'schema.json').read_text())
    exports = []
    for i, reference in enumerate(('sub/weather.csv', 'SUB\\Weather.CSV', str(root).upper() + '\\sub\\WEATHER.csv')):
        schema['buildings']['Building_1']['weather'] = reference
        (root / f'schema_{i}.json').write_text(json.dumps(schema))
        exports.append(export_run(root / f'schema_{i}.json', tmp_path / f'out-{i}', identity=f'controller-{i}'))
        context = json.loads(exports[-1].with_suffix('.manifest.json').read_text())['comparison_context']
        assert 'sub/weather.csv' in context['data_files_sha256'], context['data_files_sha256']
    for export in exports[1:]:
        report = compare_exports(exports[0], export)
        assert report['status'] == 'paired', report


def _git(*args):
    return subprocess.run(['git', *args], cwd=REPOSITORY, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def checkout():
    if not (REPOSITORY / '.git').exists() or shutil.which('git') is None:
        pytest.skip('Needs a git checkout of the repository')
    try:
        _git('rev-parse', '--git-dir')
    except (OSError, subprocess.CalledProcessError):
        pytest.skip('Needs a git checkout of the repository')


def test_checkout_attributes_keep_hashed_bytes_identical(checkout):
    attributes = {}
    for line in _git('check-attr', 'text', 'eol', '--', 'data/datasets/x/Building_1.csv',
                     'tests/data/x/weather.csv', 'citylearn/x.py', 'data/datasets/x/a.parquet').splitlines():
        path, attribute, value = line.split(': ')
        attributes[path, attribute] = value
    assert attributes['data/datasets/x/Building_1.csv', 'text'] == 'unset'
    assert attributes['tests/data/x/weather.csv', 'text'] == 'unset'
    assert attributes['data/datasets/x/a.parquet', 'text'] == 'unset'
    assert attributes['citylearn/x.py', 'eol'] == 'lf'


def test_checked_out_data_files_are_the_committed_bytes(checkout):
    converted = []
    for line in _git('ls-files', '--eol', '--', 'data', 'tests/data').splitlines():
        index, worktree, _ = line.split(None, 2)
        name = line.split('\t', 1)[1]
        if worktree != 'w/' and index[2:] != worktree[2:]:
            converted.append(name)
    assert not converted, (
        f'{len(converted)} data files differ from the committed bytes (e.g. {converted[:3]}), so '
        'data_files_sha256 will not match other checkouts. This checkout predates .gitattributes; '
        'make a fresh clone as described in "Portable experiment evidence" '
        '(docs/developer_guide.md#portable-experiment-evidence).')
