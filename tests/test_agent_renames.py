"""BaselineAgent and ZeroActionBaselineAgent were renamed NoControlAgent and ZeroActionAgent (#297); the old names
were removed in CityLearn 3.8.1 (#466)."""

import json
from pathlib import Path

import pytest

import citylearn.agents.base as base
import citylearn.agents.baseline as baseline
from citylearn.agents.base import NoControlAgent
from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
MINUTE_EV_DEMO = ROOT / 'tests' / 'data' / 'minute_ev_demo' / 'schema.json'

REMOVED = [(base, 'BaselineAgent'), (baseline, 'ZeroActionBaselineAgent')]


@pytest.mark.parametrize('module,old', REMOVED)
def test_old_names_were_removed(module, old):
    assert not hasattr(module, old)

    with pytest.raises(ImportError):
        exec(f'from {module.__name__} import {old}', {})


def test_cli_and_schema_lookups_accept_the_new_names_only():
    env = CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=4)

    assert isinstance(env.load_agent('citylearn.agents.base.NoControlAgent', env=env), NoControlAgent)

    env = CityLearnEnv(str(MINUTE_EV_DEMO), episode_time_steps=4)

    with pytest.raises(AttributeError, match='BaselineAgent'):
        env.load_agent('citylearn.agents.base.BaselineAgent', env=env)


def test_bundled_schemas_and_settings_use_the_new_names():
    for path in (ROOT / 'data' / 'datasets').glob('*/schema.json'):
        agent = (json.loads(path.read_text(encoding='utf-8')).get('agent') or {}).get('type', '')
        assert 'BaselineAgent' not in agent.replace('BusinessAsUsualAgent', ''), path

    assert 'agents.base.BaselineAgent' not in (ROOT / 'citylearn' / 'misc' / 'settings.yaml').read_text(encoding='utf-8')
