"""Local schema roots work from any cwd, including legacy repository schemas."""
from pathlib import Path

import pytest

from citylearn.utils.file_handler import FileHandler
from scripts.audit.audit_datasets import dataset_root_from_schema


def test_legacy_repository_root_and_schema_relative_precedence(tmp_path, monkeypatch):
    dataset = tmp_path / 'repo/data/datasets/demo'
    dataset.mkdir(parents=True)
    schema_path = dataset / 'schema.json'
    schema = {'root_directory': 'data/datasets/demo'}
    monkeypatch.chdir(tmp_path)
    assert FileHandler.resolve_schema_root(schema, schema_path) == dataset
    assert dataset_root_from_schema(schema, dataset) == dataset
    local = dataset / schema['root_directory']
    local.mkdir(parents=True)
    assert FileHandler.resolve_schema_root(schema, schema_path) == local
    assert schema['root_directory'] == 'data/datasets/demo'
    assert FileHandler.resolve_schema_root({'root_directory': '../demo'}, schema_path) == dataset
    assert FileHandler.resolve_schema_root({'root_directory': str(dataset)}, schema_path) == dataset
    assert FileHandler.resolve_schema_root({'root_directory': 'missing'}, schema_path) == dataset / 'missing'


@pytest.mark.parametrize('name', [
    'citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet',
    'citylearn_three_phase_dynamic_assets_only_demo_15s_parquet',
    'citylearn_three_phase_electrical_service_demo_15s_parquet',
])
def test_official_parquet_schema_from_other_directory(name, tmp_path, monkeypatch):
    pytest.importorskip('pyarrow')
    from citylearn.citylearn import CityLearnEnv
    from scripts.audit.audit_datasets import build_zero_action
    path = Path(__file__).resolve().parents[1] / 'data/datasets' / name / 'schema.json'
    monkeypatch.chdir(tmp_path)
    env = CityLearnEnv(path, offline=True, episode_time_steps=3,
                       simulation_start_time_step=0, simulation_end_time_step=2,
                       physics_invariant_checks=True, export_kpis_on_episode_end=False)
    try:
        env.reset(seed=0)
        env.step(build_zero_action(env))
        assert Path(env.root_directory) == path.parent
    finally:
        env.close()
