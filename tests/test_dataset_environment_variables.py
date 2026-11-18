"""Dataset environment variables are read when a DataSet or CityLearnEnv is created, not when CityLearn is imported."""

from pathlib import Path

import pytest
from platformdirs import user_cache_dir

from citylearn.citylearn import CityLearnEnv, UnknownSchemaError
from citylearn.data import DataSet

pytestmark = pytest.mark.use_real_dataset_resolution
MINUTE_SCHEMA = Path(__file__).resolve().parents[1]/'tests'/'data'/'minute_ev_demo'/'schema.json'
VARIABLES = ['CITYLEARN_DATASET_GITHUB_ACCOUNT', 'CITYLEARN_DATASET_REPOSITORY', 'CITYLEARN_DATASET_TAG', 'CITYLEARN_OFFLINE']


@pytest.fixture(autouse=True)
def _unset(monkeypatch):
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_a_dataset_reads_its_environment_variables_when_it_is_created(monkeypatch):
    default = DataSet()
    assert (default.github_account, default.repository, default.tag, default.offline) == (
        DataSet.GITHUB_ACCOUNT, DataSet.REPOSITORY_NAME, DataSet.REPOSITORY_TAG, False,
    )

    # Previously these were read once, when citylearn.data was imported.
    monkeypatch.setenv('CITYLEARN_DATASET_GITHUB_ACCOUNT', 'owner')
    monkeypatch.setenv('CITYLEARN_DATASET_REPOSITORY', 'repo')
    monkeypatch.setenv('CITYLEARN_DATASET_TAG', 'v9')
    monkeypatch.setenv('CITYLEARN_OFFLINE', 'true')
    configured = DataSet()
    assert (configured.github_account, configured.repository, configured.tag, configured.offline) == ('owner', 'repo', 'v9', True)

    explicit = DataSet(github_account='a', repository='r', tag='t', offline=False)
    assert (explicit.github_account, explicit.repository, explicit.tag, explicit.offline) == ('a', 'r', 't', False)


def test_citylearn_env_offline_defaults_to_citylearn_offline(monkeypatch):
    def _no_network(*args, **kwargs):
        raise AssertionError('Offline mode must not use the network.')

    monkeypatch.setattr(DataSet, 'get_requests_session', staticmethod(_no_network))
    monkeypatch.setenv('CITYLEARN_OFFLINE', '1')

    # Previously offline=None meant False, whatever CITYLEARN_OFFLINE said.
    with pytest.raises(UnknownSchemaError, match='offline mode is enabled'):
        CityLearnEnv('missing_offline_dataset', central_agent=True, episode_time_steps=2, render_mode='none')

    env = CityLearnEnv(str(MINUTE_SCHEMA), central_agent=True, episode_time_steps=2, render_mode='none')
    assert env.offline is True
    env.offline = False
    assert env.offline is False
    monkeypatch.delenv('CITYLEARN_OFFLINE')
    env.offline = None
    assert env.offline is False


def test_the_unused_constants_are_deprecated(monkeypatch):
    with pytest.warns(DeprecationWarning, match='GITHUB_API_CONTENT_URL'):
        assert DataSet.GITHUB_API_CONTENT_URL == 'https://api.github.com/repos/citylearn-project/CityLearn/contents'

    monkeypatch.setenv('CITYLEARN_DATASET_TAG', 'v9')

    with pytest.warns(DeprecationWarning, match='DEFAULT_CACHE_DIRECTORY'):
        assert DataSet().DEFAULT_CACHE_DIRECTORY == str(Path(user_cache_dir('citylearn'))/'v9')
