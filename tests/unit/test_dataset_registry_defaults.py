from pathlib import Path

from citylearn import __version__
from citylearn.data import DataSet


def test_dataset_registry_defaults_to_matching_official_release():
    dataset = DataSet()

    assert dataset.github_account == "citylearn-project"
    assert dataset.repository == "CityLearn"
    assert dataset.tag == f"v{__version__}"


def test_retired_datasets_are_not_in_the_public_repository():
    datasets_directory = Path(__file__).resolve().parents[2] / "data" / "datasets"
    names = {path.name for path in datasets_directory.iterdir() if path.is_dir()}

    assert "EC_Ermesinde" not in names
    assert not any(name.startswith("ALADI ") for name in names)
    assert not any(name.startswith("rec_2023_") for name in names)


def test_portugal_rec_datasets_are_in_the_public_repository():
    datasets_directory = Path(__file__).resolve().parents[2] / "data" / "datasets"

    for name in (
        "pt_rec_4", "pt_rec_15", "pt_rec_30", "pt_rec_100",
    ):
        assert (datasets_directory / name / "schema.json").is_file()
        assert (datasets_directory / name / "shared").is_dir()
