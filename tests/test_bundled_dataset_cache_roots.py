"""Bundled datasets load from the dataset cache, not only from a repository checkout (issue #194).

A schema read from the repository finds its data even with a repository-relative ``root_directory``,
because ``FileHandler.resolve_schema_root`` also tries the ancestors of the schema folder. The dataset
cache has no such ancestor, so these tests resolve every bundled schema from a private cache.
"""

import os
import shutil
from pathlib import Path

import pytest

from citylearn.data import DataSet
from citylearn.internal.temporal import FILE_TYPES
from citylearn.utils.file_handler import FileHandler

pytestmark = pytest.mark.use_real_dataset_resolution
DATASETS = Path(__file__).resolve().parents[1] / 'data' / 'datasets'
PARQUET_15S_DATASETS = [
    'citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet',
    'citylearn_three_phase_dynamic_assets_only_demo_15s_parquet',
    'citylearn_three_phase_electrical_service_demo_15s_parquet',
]


@pytest.fixture
def private_cache(tmp_path, monkeypatch) -> Path:
    """Point every `DataSet` at an empty cache in `tmp_path`."""

    cache = tmp_path / 'cache'
    monkeypatch.setattr(DataSet, 'cache_directory', property(lambda self: str(cache)))
    return cache


def _skip_data_files(directory: str, names: list) -> list:
    return [n for n in names if os.path.isfile(os.path.join(directory, n)) and not n.endswith('.json')]


def _input_files(value, key: str = ''):
    """Yield `(key, path)` for every schema string that names an input file.

    `experimental_design` is skipped: it is descriptive metadata that CityLearn never reads, and its
    `paired_reference` entries name repository paths.
    """

    if isinstance(value, dict):
        for k, v in value.items():
            if k not in ('root_directory', 'experimental_design'):
                yield from _input_files(v, f'{key}.{k}' if key else k)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _input_files(v, f'{key}[{i}]')
    elif isinstance(value, str) and Path(value).suffix.lower() in FILE_TYPES:
        yield key, value


def test_every_bundled_schema_resolves_its_input_files_from_the_cache(private_cache, tmp_path, monkeypatch):
    """Resolve the top-level and nested schemas of every bundled dataset from the cache.

    The cache is filled by `DataSet.get_dataset` from a local copy of `data/datasets` that holds only
    the JSON files, which keeps the test fast. The cache is a full copy of the dataset folder in normal
    use, so an input file exists under the resolved root exactly when it exists at the same relative
    path in `data/datasets`.
    """

    local_copy = tmp_path / 'json_only_datasets'
    shutil.copytree(DATASETS, local_copy, ignore=_skip_data_files)
    monkeypatch.setenv('CITYLEARN_LOCAL_DATASETS_PATH', str(local_copy))
    dataset = DataSet(offline=True)
    names = dataset.get_dataset_names()
    assert names == sorted(p.name for p in DATASETS.iterdir() if (p / 'schema.json').is_file())
    problems = []
    schema_count = 0

    for name in names:
        cached = Path(dataset.get_dataset(name)).resolve().parent
        assert cached == (private_cache / 'datasets' / name).resolve()

        for schema_path in sorted(cached.rglob('*.json')):
            schema = FileHandler.read_json(schema_path)

            if not isinstance(schema, dict) or 'buildings' not in schema:
                continue

            schema_count += 1
            label = schema_path.relative_to(cached.parent).as_posix()
            root = FileHandler.resolve_schema_root(schema, schema_path)

            if not root.is_dir() or not root.is_relative_to(cached):
                problems.append(
                    f"{label}: root_directory {schema.get('root_directory')!r} resolves to {root}, "
                    f"which is not a folder inside the cached dataset {cached}"
                )
                continue

            files = dict(_input_files(schema))
            missing_keys = [f'buildings.{b}.energy_simulation' for b in schema['buildings']
                            if f'buildings.{b}.energy_simulation' not in files]
            problems += [f'{label}: {key} does not name an input file' for key in missing_keys]
            source_root = DATASETS / name / root.relative_to(cached)

            for key, value in files.items():
                if Path(value).is_absolute() or not (source_root / value).is_file():
                    problems.append(f'{label}: {key} = {value!r} is not a file under the resolved root {root}')

    assert schema_count >= len(names)
    assert problems == [], '\n'.join(problems)


@pytest.mark.parametrize('load_by', ['name', 'cached schema path'])
@pytest.mark.parametrize('name', PARQUET_15S_DATASETS)
def test_15s_parquet_dataset_runs_from_the_cache(name, load_by, private_cache):
    pytest.importorskip('pyarrow')
    from citylearn.citylearn import CityLearnEnv
    from scripts.audit.audit_datasets import build_zero_action

    schema = name if load_by == 'name' else DataSet(offline=True).get_dataset(name)
    env = CityLearnEnv(schema, offline=True, episode_time_steps=4,
                       simulation_start_time_step=0, simulation_end_time_step=3,
                       physics_invariant_checks=True, export_kpis_on_episode_end=False)

    try:
        assert Path(env.root_directory).resolve() == (private_cache / 'datasets' / name).resolve()
        env.reset(seed=0)

        for _ in range(3):
            env.step(build_zero_action(env))

        assert env.time_step == 3
    finally:
        env.close()
