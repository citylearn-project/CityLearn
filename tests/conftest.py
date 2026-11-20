"""
Pytest-wide configuration: make the repository importable without installation and
avoid external downloads during test runs.

By pushing the project root onto ``sys.path`` we allow ``import citylearn`` to
work even when the package has not been installed. This mirrors legacy scripts
and keeps local runs simple. Additionally, we make ``DataSet`` prefer the
bundled datasets so tests don't hit the GitHub API.
"""

import shutil
import sys
from pathlib import Path

import pytest
from typing import Union

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def _test_dataset_cache(tmp_path_factory) -> Path:
    """A dataset cache private to this pytest process (one per xdist worker).

    Tests used to copy datasets into the real user cache (``~/.cache/citylearn/<tag>``), which overwrote
    downloaded datasets and raced when several workers or test runs copied the same folder (#256).
    """

    return tmp_path_factory.mktemp("citylearn_dataset_cache")


@pytest.fixture(autouse=True)
def _prefer_local_datasets(monkeypatch, request, _test_dataset_cache):
    """Ensure tests use the repo's datasets without hitting the network."""

    if request.node.get_closest_marker("use_real_dataset_resolution") is not None:
        return

    from citylearn.data import DataSet

    local_root = ROOT / "data" / "datasets"
    original_get_dataset = DataSet.get_dataset
    original_get_dataset_names = DataSet.get_dataset_names

    def _copy_dataset(src: Path, dest: Path) -> None:
        if dest.exists():
            shutil.rmtree(dest)

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)

    def patched_get_dataset(self, name: str, directory: Union[Path, str, None] = None):
        src = local_root / name

        if src.is_dir():
            if directory is not None:
                directory = Path(directory)
                directory.mkdir(parents=True, exist_ok=True)
                dest = directory / name
                _copy_dataset(src, dest)
                return str(dest / "schema.json")

            cache_dir = _test_dataset_cache / "datasets" / name
            _copy_dataset(src, cache_dir)
            return str(cache_dir / "schema.json")

        return original_get_dataset(self, name, directory)

    def patched_get_dataset_names(self):
        if local_root.is_dir():
            return sorted(p.name for p in local_root.iterdir() if p.is_dir())

        return original_get_dataset_names(self)

    monkeypatch.setattr(DataSet, "get_dataset", patched_get_dataset)
    monkeypatch.setattr(DataSet, "get_dataset_names", patched_get_dataset_names)
