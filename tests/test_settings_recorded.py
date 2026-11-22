"""Settings added since 3.6.0 are recorded in the metadata and manifest, and compared (#301, #302)."""

import ast
from copy import deepcopy
import json
from pathlib import Path
import warnings

import pytest

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.comparison import compare_exports, compare_manifests
from citylearn.internal.experiment import experiment_manifest
from citylearn.multi_community import MultiCommunityEnv
from citylearn.reward_function import MultiBuildingRewardFunction
from test_deferrable_appliance_integration import _schema_with_deferrable_appliance, _zero_flat_actions

REWARD_DATASET = 'citylearn_challenge_2023_phase_2_local_evaluation'
MINUTE_SCHEMA = Path(__file__).resolve().parent / 'data/minute_ev_demo/schema.json'


def _export(path, output, **kwargs):
    env = CityLearnEnv(str(path), episode_time_steps=4, random_seed=0, render_directory=output,
                       export_kpis_on_episode_end=False, **kwargs)
    env.reset()
    env.set_experiment_identity('controller-a', 'test-v1', {'action': 0.})
    while not env.terminated:
        env.step(_zero_flat_actions(env))
    env.export_final_kpis(filepath='kpis.csv', include_business_as_usual=False)
    p = Path(env.new_folder_path)/'kpis.csv'
    env.close()
    return p


def test_exports_under_different_physics_versions_are_incompatible(tmp_path):
    path = _schema_with_deferrable_appliance(tmp_path/'source')
    a = _export(path, tmp_path/'a', physics_version=1)
    b = _export(path, tmp_path/'b', physics_version=2)
    left, right = (json.loads(p.with_suffix('.manifest.json').read_text()) for p in (a, b))

    assert (left['physics_version'], right['physics_version']) == (1, 2)
    assert left['comparison_context']['physics_version'] == 1
    assert left['temporal_reproducibility']['physics_version'] == 1

    report = compare_exports(a, b)
    assert report['status'] == 'incompatible'
    assert 'physics_version' in report['mismatches']
    assert report['permitted_claim'] is None

    # The same run compared with itself still pairs, so physics_version is the only difference.
    assert compare_manifests(left, deepcopy(left))['status'] == 'paired'
    other = deepcopy(right)
    other['comparison_context']['physics_version'] = 1
    assert 'physics_version' not in compare_manifests(left, other)['mismatches']

    # A manifest without the physics version (written before it was recorded) cannot be paired.
    other = deepcopy(left)
    del other['comparison_context']['physics_version']
    report = compare_manifests(left, other)
    assert report['status'] == 'unknown' and 'physics_version' in report['missing_evidence']


def test_metadata_and_manifest_record_split_boundary_and_ratio_mode(tmp_path):
    path = _schema_with_deferrable_appliance(tmp_path)
    env = CityLearnEnv(str(path), episode_time_steps=4, random_seed=0, episode_split_boundary='disjoint',
                       time_step_ratio_mode='compress', physics_version=1, render_directory=tmp_path/'out')
    env.reset()
    metadata = env.get_metadata()
    manifest = experiment_manifest(env)
    env.close()

    for record in (metadata, metadata['temporal_reproducibility'], manifest, manifest['temporal_reproducibility']):
        assert record['episode_split_boundary'] == 'disjoint'
        assert record['time_step_ratio_mode'] == 'compress'
        assert record['physics_version'] == 1


@pytest.mark.parametrize('option,value,match', [
    ('episode_split_boundary', 'overlapping', 'episode_split_boundary must be one of'),
    ('time_step_ratio_mode', 'squash', 'time_step_ratio_mode must be one of'),
    ('physics_version', 3, r'physics_version must be one of \[1, 2\]'),
    ('physics_version', True, r'physics_version must be one of \[1, 2\]'),
    ('random_stream_version', 'v9', 'random_stream_version'),
])
def test_invalid_setting_values_are_rejected(tmp_path, option, value, match):
    path = _schema_with_deferrable_appliance(tmp_path)

    with pytest.raises(ValueError, match=match):
        CityLearnEnv(str(path), episode_time_steps=4, **{option: value})

    schema = json.loads(path.read_text())
    schema[option] = value

    with pytest.raises(ValueError, match=match):
        CityLearnEnv(schema, episode_time_steps=4)


def _kwargs_read_by_constructor():
    source = Path(__file__).resolve().parents[1]/'citylearn'/'citylearn.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    init = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '__init__'
                and any(a.arg == 'schema' for a in n.args.args))
    names = set()
    for node in ast.walk(init):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'pop'
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'kwargs'):
            names.add(node.args[0].value)
    return names


def test_every_constructor_kwarg_is_a_known_option():
    names = _kwargs_read_by_constructor()
    assert {'physics_version', 'random_stream_version', 'episode_split_boundary'} <= names
    assert names <= set(CityLearnEnv._KNOWN_CONSTRUCTOR_OPTIONS)


def test_misspelled_physics_version_gets_a_suggestion(tmp_path):
    path = _schema_with_deferrable_appliance(tmp_path)

    with pytest.raises(TypeError, match="'physics_versoin' \\(did you mean 'physics_version'\\?\\)"):
        CityLearnEnv(str(path), physics_versoin=1)


def test_reward_evidence_records_each_building_reward_version():
    path = Path(__file__).resolve().parents[1]/'data'/'datasets'/REWARD_DATASET/'schema.json'
    schema = json.loads(path.read_text(encoding='utf-8'))
    schema['root_directory'] = str(path.parent)
    schema['reward_function'] = {
        'type': {'default': 'citylearn.reward_function.Electric_Vehicles_Reward_Function'},
        'attributes': {'default': {'version': 2}},
    }
    env = CityLearnEnv(schema, episode_time_steps=4)
    evidence = env.get_metadata()['reward_evidence']
    names = [b.name for b in env.buildings]
    env.close()

    assert isinstance(env.reward_function, MultiBuildingRewardFunction)
    assert sorted(evidence['per_building']) == sorted(names)

    for name in names:
        member = evidence['per_building'][name]
        assert member['resolved_class'] == 'citylearn.reward_function.Electric_Vehicles_Reward_Function'
        assert member['effective_public_parameters']['version'] == 2

    # A single reward function keeps its parameters at top level and has no per-building block.
    schema['reward_function'] = {'type': 'citylearn.reward_function.Electric_Vehicles_Reward_Function',
                                 'attributes': {'version': 2}}
    env = CityLearnEnv(schema, episode_time_steps=4)
    evidence = env.get_metadata()['reward_evidence']
    env.close()
    assert evidence['per_building'] is None
    assert evidence['effective_public_parameters']['version'] == 2


def _community(community_id, **env_kwargs):
    kwargs = dict(central_agent=True, episode_time_steps=8, render_mode='none', random_seed=0)
    kwargs.update(env_kwargs)
    return dict(community_id=community_id, schema=str(MINUTE_SCHEMA), env_kwargs=kwargs)


@pytest.mark.parametrize('setting,values', [
    ('physics_version', (1, 2)),
    ('random_stream_version', ('v1', 'v2')),
])
def test_multi_community_rejects_mixed_definition_versions(setting, values):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with pytest.raises(ValueError, match=f'share {setting}'):
            MultiCommunityEnv(communities=[
                _community('community_a', **{setting: values[0]}),
                _community('community_b', **{setting: values[1]}),
            ])

        env = MultiCommunityEnv(communities=[
            _community('community_a', **{setting: values[0]}),
            _community('community_b', **{setting: values[0]}),
        ])

    metadata = env.get_metadata()
    env.close()
    assert metadata[setting] == values[0]
