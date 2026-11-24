"""Local datasets are cached under the key of their content, not only under the release tag.

The dataset cache was keyed only by `v{__version__}`, so checkouts that share a version read each other's
copies: a run by dataset name could load a stale schema, and a process that republished the folder during
another one's run made its `evaluate_v2()` raise "Native BAU inputs changed since loading".
"""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet

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
    return cache, local


def _change_building_file(root: Path, delta: float = 1.0):
    filepath = root/'Building_1.csv'
    data = pd.read_csv(filepath)
    data.iloc[0, -1] += delta
    data.to_csv(filepath, index=False)


def _env(schema) -> CityLearnEnv:
    return CityLearnEnv(schema, offline=True, central_agent=True, episode_time_steps=6, render_mode='none',
                        random_seed=0)


def _run(env: CityLearnEnv):
    env.reset(seed=0)

    while not env.terminated:
        env.step([[0.0]*env.action_space[0].shape[0]])

    return env.evaluate_v2()


def test_different_contents_are_cached_in_different_folders_and_equal_contents_in_one(roots, tmp_path):
    cache, local = roots
    first = shutil.copytree(MINUTE_EV_DEMO, tmp_path/'first'/'demo')
    same = shutil.copytree(MINUTE_EV_DEMO, tmp_path/'same'/'demo')
    other = shutil.copytree(MINUTE_EV_DEMO, tmp_path/'other'/'demo')
    _change_building_file(other)
    dataset = DataSet(offline=True)

    first_cached = Path(dataset.get_dataset(str(first))).parent
    same_cached = Path(dataset.get_dataset(str(same))).parent
    other_cached = Path(dataset.get_dataset(str(other))).parent

    assert first_cached == same_cached
    assert first_cached != other_cached
    assert first_cached.name == other_cached.name == 'demo'
    assert first_cached.parent.parent == other_cached.parent.parent == cache/DataSet.CONTENT_CACHE_DIRECTORY
    assert (first_cached/'Building_1.csv').read_bytes() == (MINUTE_EV_DEMO/'Building_1.csv').read_bytes()
    assert (other_cached/'Building_1.csv').read_bytes() == (other/'Building_1.csv').read_bytes()


def test_a_stale_copy_cached_under_the_same_tag_is_not_read(roots):
    # The report's case: another checkout with the same __version__ filled `<cache>/datasets/<name>` with an
    # older schema (here a different end time step). A run by name used that schema instead of the local one.
    cache, local = roots
    current = shutil.copytree(MINUTE_EV_DEMO, local/'demo')
    stale = shutil.copytree(MINUTE_EV_DEMO, cache/'datasets'/'demo')
    stale_schema = json.loads((stale/'schema.json').read_text())
    stale_schema['simulation_end_time_step'] = 3
    (stale/'schema.json').write_text(json.dumps(stale_schema))

    schema = DataSet(offline=True).get_schema('demo')
    env = _env('demo')

    current_schema = json.loads((current/'schema.json').read_text())
    assert schema['simulation_end_time_step'] == current_schema['simulation_end_time_step'] != 3
    assert {k: v for k, v in schema.items() if k != 'root_directory'} == {
        k: v for k, v in current_schema.items() if k != 'root_directory'
    }
    assert Path(env.root_directory).resolve() != stale.resolve()
    assert json.loads((stale/'schema.json').read_text()) == stale_schema  # left untouched


def test_caching_new_content_does_not_disturb_an_open_environment(roots):
    # Another process caching a different copy of the dataset used to move the open environment's folder aside,
    # and its next evaluate_v2() raised "Native BAU inputs changed since loading".
    cache, local = roots
    source = shutil.copytree(MINUTE_EV_DEMO, local/'demo')
    env = _env('demo')
    first = _run(env)
    root = Path(env.root_directory)
    files = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}

    _change_building_file(source)
    new_root = Path(DataSet(offline=True).get_dataset('demo')).parent
    new_env = _env('demo')

    assert new_root != root
    assert Path(new_env.root_directory).resolve() == new_root.resolve()
    assert {p: p.read_bytes() for p in root.rglob('*') if p.is_file()} == files
    pd.testing.assert_frame_equal(env.evaluate_v2(), first)


def test_the_content_key_is_computed_once_per_process_until_a_file_changes(roots, monkeypatch):
    cache, local = roots
    source = shutil.copytree(MINUTE_EV_DEMO, local/'demo')
    calls = []
    hash_directory = DataSet._hash_directory
    monkeypatch.setattr(DataSet, '_hash_directory', staticmethod(lambda *a: calls.append(a[0]) or hash_directory(*a)))
    dataset = DataSet(offline=True)

    first = dataset.get_dataset('demo')
    local_hashes = [c for c in calls if Path(c).resolve() == source.resolve()]
    assert len(local_hashes) == 1
    assert dataset.get_dataset('demo') == first
    assert len([c for c in calls if Path(c).resolve() == source.resolve()]) == 1

    _change_building_file(source, delta=2.0)

    assert dataset.get_dataset('demo') != first
    assert len([c for c in calls if Path(c).resolve() == source.resolve()]) == 2


def test_a_local_copy_that_changes_while_it_is_cached_is_not_published(roots, monkeypatch):
    cache, local = roots
    source = shutil.copytree(MINUTE_EV_DEMO, local/'demo')
    copytree = shutil.copytree

    def copy_then_change(src, dst, **kwargs):
        result = copytree(src, dst, **kwargs)
        _change_building_file(Path(dst))
        return result

    monkeypatch.setattr('citylearn.data.shutil.copytree', copy_then_change)

    with pytest.raises(RuntimeError, match='changed while it was being cached'):
        DataSet(offline=True).get_dataset('demo')

    content = cache/DataSet.CONTENT_CACHE_DIRECTORY/DataSet._content_key(source)
    assert not (content/'demo').exists()
    assert not any(content.iterdir())
