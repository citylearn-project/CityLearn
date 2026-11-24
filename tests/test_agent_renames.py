"""BaselineAgent and ZeroActionBaselineAgent renamed NoControlAgent and ZeroActionAgent, with deprecated aliases (#297)."""

import json
import pickle
from pathlib import Path

import pytest

import citylearn.agents.base as base
import citylearn.agents.baseline as baseline
from citylearn.agents.base import NoControlAgent
from citylearn.agents.baseline import ZeroActionAgent
from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_DEMO = ROOT / 'tests' / 'data' / 'minute_ev_demo' / 'schema.json'

RENAMES = [
    (base, 'BaselineAgent', NoControlAgent),
    (baseline, 'ZeroActionBaselineAgent', ZeroActionAgent),
]


@pytest.mark.parametrize('module,old,new', RENAMES)
def test_old_names_are_deprecated_aliases_of_the_same_class(module, old, new):
    with pytest.warns(DeprecationWarning, match=f'{old} is deprecated') as record:
        alias = getattr(module, old)

    assert alias is new
    message = str(record[0].message)
    assert f'{module.__name__}.{new.__name__}' in message and "'baseline' names the KPI counterfactual" in message


@pytest.mark.parametrize('module,old,new', RENAMES)
def test_old_import_paths_and_pickles_resolve_to_the_new_class(module, old, new):
    namespace = {}

    with pytest.warns(DeprecationWarning):
        exec(f'from {module.__name__} import {old} as alias', namespace)

    assert namespace['alias'] is new

    # Agents pickled before the rename name the old class (protocol 0 GLOBAL opcode); unpickling looks it up.
    with pytest.warns(DeprecationWarning):
        assert pickle.loads(f'c{module.__name__}\n{old}\n.'.encode()) is new


def test_cli_and_schema_lookups_accept_the_old_and_the_new_names():
    env = CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=4)

    assert isinstance(env.load_agent('citylearn.agents.base.NoControlAgent', env=env), NoControlAgent)

    env = CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=4)

    with pytest.warns(DeprecationWarning, match='BaselineAgent is deprecated'):
        assert isinstance(env.load_agent('citylearn.agents.base.BaselineAgent', env=env), NoControlAgent)


def test_bundled_schemas_and_settings_use_the_new_names():
    for path in (ROOT / 'data' / 'datasets').glob('*/schema.json'):
        agent = (json.loads(path.read_text(encoding='utf-8')).get('agent') or {}).get('type', '')
        assert 'BaselineAgent' not in agent.replace('BusinessAsUsualAgent', ''), path

    assert 'agents.base.BaselineAgent' not in (ROOT / 'citylearn' / 'misc' / 'settings.yaml').read_text(encoding='utf-8')
