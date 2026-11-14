"""Tests for pure-NumPy district counterfactual series, Box dtype cleanliness, Pandas 4 export, and packaging."""

from __future__ import annotations

import json
from pathlib import Path
import time
import warnings

import numpy as np
import pandas as pd
import pytest

from citylearn.building import DynamicsBuilding
from citylearn.citylearn import CityLearnEnv
from citylearn.utilities import FileHandler

ROOT = Path(__file__).resolve().parents[1]
DATASET_2022 = ROOT / "data" / "datasets" / "citylearn_challenge_2022_phase_all_plus_evs" / "schema.json"
MINUTE_DEMO = ROOT / "tests" / "data" / "minute_ev_demo" / "schema.json"

COUNTERFACTUAL_PROPERTIES = (
    (
        "net_electricity_consumption_emission_without_storage_and_partial_load_and_pv",
        "net_electricity_consumption_emission_without_storage_and_pv",
    ),
    (
        "net_electricity_consumption_cost_without_storage_and_partial_load_and_pv",
        "net_electricity_consumption_cost_without_storage_and_pv",
    ),
    (
        "net_electricity_consumption_without_storage_and_partial_load_and_pv",
        "net_electricity_consumption_without_storage_and_pv",
    ),
    (
        "net_electricity_consumption_emission_without_storage_and_partial_load",
        "net_electricity_consumption_emission_without_storage",
    ),
    (
        "net_electricity_consumption_cost_without_storage_and_partial_load",
        "net_electricity_consumption_cost_without_storage",
    ),
    (
        "net_electricity_consumption_without_storage_and_partial_load",
        "net_electricity_consumption_without_storage",
    ),
    ("net_electricity_consumption_emission_without_storage_and_pv", None),
    ("net_electricity_consumption_cost_without_storage_and_pv", None),
    ("net_electricity_consumption_without_storage_and_pv", None),
    ("net_electricity_consumption_emission_without_storage", None),
    ("net_electricity_consumption_cost_without_storage", None),
    ("net_electricity_consumption_without_storage", None),
)


def _reference_dataframe_sum(env: CityLearnEnv, attr: str, fallback: str | None) -> np.ndarray:
    if fallback is None:
        rows = [getattr(b, attr) for b in env.buildings]
    else:
        rows = [
            getattr(b, attr if isinstance(b, DynamicsBuilding) else fallback)
            for b in env.buildings
        ]
    return pd.DataFrame(rows).sum(axis=0, min_count=1).to_numpy()


def test_district_counterfactual_properties_match_pandas_reference_and_avoid_dataframe_overhead():
    env = CityLearnEnv(str(DATASET_2022), central_agent=True, episode_time_steps=48, random_seed=0)
    try:
        env.reset(seed=0)
        for _ in range(8):
            zeros = [np.zeros(env.action_space[0].shape, dtype=np.float32)]
            env.step(zeros)

        for prop_name, fallback_name in COUNTERFACTUAL_PROPERTIES:
            actual = getattr(env, prop_name)
            expected = _reference_dataframe_sum(env, prop_name, fallback_name)
            np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12, err_msg=prop_name)

        # Verify NaN and ragged-length handling in _sum_building_series matches min_count=1 DataFrame sum.
        class _DummyBuilding:
            def __init__(self, values):
                self.series = np.asarray(values, dtype=np.float64)

        original_buildings = env.buildings
        try:
            env.buildings = [
                _DummyBuilding([1.5, np.nan, 3.0]),
                _DummyBuilding([2.5, np.nan]),
            ]
            actual_ragged = env._sum_building_series("series")
            assert actual_ragged.shape == (3,)
            assert actual_ragged[0] == pytest.approx(4.0)
            assert np.isnan(actual_ragged[1])
            assert actual_ragged[2] == pytest.approx(3.0)
        finally:
            env.buildings = original_buildings

        # Benchmark: 100 counterfactual evaluations should comfortably beat DataFrame construction.
        t0 = time.perf_counter()
        for _ in range(100):
            _ = env.net_electricity_consumption_without_storage
        numpy_elapsed = time.perf_counter() - t0

        t1 = time.perf_counter()
        for _ in range(100):
            _ = _reference_dataframe_sum(env, "net_electricity_consumption_without_storage", None)
        df_elapsed = time.perf_counter() - t1

        assert numpy_elapsed < df_elapsed
    finally:
        env.close()


@pytest.mark.parametrize("central_agent", [True, False])
def test_flat_and_entity_spaces_emit_no_box_precision_warnings(central_agent: bool):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        env = CityLearnEnv(str(MINUTE_DEMO), central_agent=central_agent, episode_time_steps=4, random_seed=0)
        try:
            env.reset(seed=0)
            _ = env.observation_space
            _ = env.action_space
            _ = env.flat_observation_space
            _ = env.flat_action_space
        finally:
            env.close()

    box_warnings = [w for w in caught if "precision lowered" in str(w.message).lower()]
    assert box_warnings == []


def test_parquet_exporter_handles_pandas_string_dtype_and_mixed_textual_columns_across_chunks(tmp_path: Path):
    pytest.importorskip("pyarrow")
    env = CityLearnEnv(
        str(MINUTE_DEMO),
        central_agent=True,
        episode_time_steps=3,
        render_mode="end",
        render_file_format="parquet",
        render_directory=tmp_path,
        random_seed=0,
    )
    try:
        env.reset(seed=0)
        env._episode_exporter.ensure_output_dir()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Chunk 0: purely string-encoded numeric values (StringDtype in Pandas 3/4) + mixed label
            env._episode_exporter.write_render_rows(
                "chunked_mixed.parquet",
                [
                    {"state": "-1.00", "label": "idle"},
                    {"state": "0.00", "label": ""},
                ],
            )
            # Chunk 1: float32 numeric values + mixed string/int textual values
            env._episode_exporter.write_render_rows(
                "chunked_mixed.parquet",
                [
                    {"state": np.float32(1.0), "label": "EV-1"},
                    {"state": np.float32(0.5), "label": np.int64(42)},
                ],
            )

        pandas4_warnings = [w for w in caught if "select_dtypes" in str(w.message)]
        assert pandas4_warnings == []

        parts = sorted(Path(env.new_folder_path).glob("chunked_mixed_part*.parquet"))
        assert len(parts) == 2
        frames = [pd.read_parquet(p) for p in parts]
        combined = pd.concat(frames, ignore_index=True)
        assert combined["state"].tolist() == pytest.approx([-1.0, 0.0, 1.0, 0.5])
        assert combined.loc[0, "label"] == "idle"
        assert pd.isna(combined.loc[1, "label"])
        assert combined.loc[2, "label"] == "EV-1"
        assert combined.loc[3, "label"] == "42"
    finally:
        env.close()


def test_file_handler_stdlib_json_handles_nan_inf_and_numpy_scalars(tmp_path: Path):
    target = tmp_path / "payload.json"
    payload = {
        "finite_f32": np.float32(2.5),
        "nan_val": float("nan"),
        "np_nan": np.float64("nan"),
        "pos_inf": float("inf"),
        "neg_inf": -np.inf,
        "int64": np.int64(7),
        "flag": np.bool_(True),
        "nested": [np.array([1.0, np.nan, 3.0]), {"path": Path("a/b")}],
    }
    FileHandler.write_json(str(target), payload)
    raw_text = target.read_text(encoding="utf-8")
    # Strict RFC 8259 JSON must not contain bare NaN or Infinity tokens.
    assert "NaN" not in raw_text
    assert "Infinity" not in raw_text

    loaded = FileHandler.read_json(str(target))
    assert loaded["finite_f32"] == pytest.approx(2.5)
    assert loaded["nan_val"] is None
    assert loaded["np_nan"] is None
    assert loaded["pos_inf"] is None
    assert loaded["neg_inf"] is None
    assert loaded["int64"] == 7
    assert loaded["flag"] is True
    assert loaded["nested"][0] == [1.0, None, 3.0]


def test_packaging_metadata_files_are_consistent():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert 'name = "citylearn"' in pyproject
    assert 'build-backend = "setuptools.build_meta"' in pyproject
    assert "README.md" in manifest
    assert "README_PYPI.md" not in manifest
    assert "simplejson" not in {line.strip() for line in requirements if line.strip()}
