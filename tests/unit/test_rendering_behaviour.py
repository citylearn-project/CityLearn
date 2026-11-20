"""Rendering/export behaviour tests (pytest version)."""

import csv
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import warnings
import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController as Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.exporter import EpisodeExporter


DATASET = Path(__file__).resolve().parents[2] / 'data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json'


def _load_schema_dict() -> dict:
    with DATASET.open() as f:
        schema = json.load(f)

    schema['root_directory'] = str(DATASET.parent)
    return schema


def _cleanup_env(env: CityLearnEnv):
    paths = set()
    outputs = getattr(env, 'new_folder_path', None)
    if outputs:
        paths.add(Path(outputs))

    session_dir = getattr(env, '_render_session_dir', None)
    if session_dir:
        paths.add(Path(session_dir))

    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


def _step_once(env: CityLearnEnv):
    env.reset()
    zeros = [np.zeros(env.action_space[0].shape[0], dtype='float32')]
    env.step(zeros)


def test_render_disabled_leaves_no_directory():
    env = CityLearnEnv(str(DATASET), central_agent=True, episode_time_steps=2)
    try:
        _step_once(env)
        assert getattr(env, 'new_folder_path', None) is None
    finally:
        _cleanup_env(env)
        env.close()


def test_render_enabled_creates_default_directory():
    env = CityLearnEnv(str(DATASET), central_agent=True, episode_time_steps=2, render_mode="during")
    try:
        _step_once(env)

        outputs_path = Path(env.new_folder_path)
        assert outputs_path.is_dir()
        assert outputs_path.parent == env.render_output_root
        assert (outputs_path / 'exported_data_community_ep0.csv').is_file()
    finally:
        _cleanup_env(env)
        env.close()


def test_export_final_kpis_when_render_off(tmp_path):
    env = CityLearnEnv(str(DATASET), central_agent=True, episode_time_steps=2, render_directory=tmp_path)

    class _Model:
        pass

    model = _Model()
    model.env = env

    try:
        env.export_final_kpis(model, filepath='exported_kpis_test.csv')
        outputs_path = Path(env.new_folder_path)
        assert (outputs_path / 'exported_kpis_test.csv').is_file()
    finally:
        _cleanup_env(env)
        env.close()


def test_none_mode_does_not_auto_export_kpis_by_default(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="none",
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        while not env.terminated:
            _, _, terminated, truncated, _ = env.step(zeros)
            if terminated or truncated:
                break

        assert env.new_folder_path is None
        assert not env._final_kpis_exported
    finally:
        _cleanup_env(env)
        env.close()


def test_none_mode_can_auto_export_kpis_when_enabled(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="none",
        render_directory=tmp_path,
        export_kpis_on_episode_end=True,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        while not env.terminated:
            _, _, terminated, truncated, _ = env.step(zeros)
            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        assert outputs_path.is_dir()
        assert (outputs_path / "exported_kpis.csv").is_file()
        assert env._final_kpis_exported
    finally:
        _cleanup_env(env)
        env.close()


def test_auto_kpi_export_reports_debug_timing(tmp_path, monkeypatch):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="none",
        render_directory=tmp_path,
        export_kpis_on_episode_end=True,
        debug_timing=True,
        random_seed=0,
    )
    calls = 0

    def _export_final_kpis(*args, **kwargs):
        nonlocal calls
        calls += 1
        env._final_kpis_exported = True

    monkeypatch.setattr(env, "export_final_kpis", _export_final_kpis)

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        info = {}
        while not env.terminated:
            _, _, terminated, truncated, info = env.step(zeros)
            if terminated or truncated:
                break

        assert calls == 1
        assert info["end_export_time"] == pytest.approx(0.0)
        assert info["final_kpi_export_time"] >= 0.0
        assert info["terminal_export_time"] == pytest.approx(info["final_kpi_export_time"])
    finally:
        _cleanup_env(env)
        env.close()


def test_debug_timing_reports_step_breakdown():
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=3,
        render_mode="none",
        debug_timing=True,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        _, _, _, _, info = env.step(zeros)

        expected_keys = [
            "step_total_time",
            "parse_actions_time",
            "apply_actions_time",
            "update_variables_time",
            "reward_observations_time",
            "reward_calculation_time",
            "next_time_step_time",
            "next_observations_time",
            "building_observations_retrieval_time",
        ]
        for key in expected_keys:
            assert key in info
            assert info[key] >= 0.0

        assert info["building_observations_retrieval_time"] == pytest.approx(
            info["reward_observations_time"]
        )
        assert info["step_total_time"] >= info["apply_actions_time"]
    finally:
        _cleanup_env(env)
        env.close()


def test_reward_observation_names_attribute_limits_reward_payload():
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=3,
        render_mode="none",
        random_seed=0,
    )

    class _ExternalReward:
        required_observation_names = ("net_electricity_consumption",)

        def __init__(self):
            self.keys = None

        def calculate(self, observations):
            self.keys = [tuple(sorted(o.keys())) for o in observations]
            return [0.0]

    reward = _ExternalReward()

    try:
        env.reset()
        env.reward_function = reward
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        env.step(zeros)

        assert reward.keys
        assert set(reward.keys[0]) == {"net_electricity_consumption"}
    finally:
        _cleanup_env(env)
        env.close()


def test_during_mode_can_disable_auto_kpi_export(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="during",
        render_directory=tmp_path,
        export_kpis_on_episode_end=False,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        while not env.terminated:
            _, _, terminated, truncated, _ = env.step(zeros)
            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        assert (outputs_path / "exported_data_community_ep0.csv").is_file()
        assert not (outputs_path / "exported_kpis.csv").exists()
        assert not env._final_kpis_exported
    finally:
        _cleanup_env(env)
        env.close()


def test_agent_learn_exports_only_final_episode_by_default(tmp_path, monkeypatch):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="during",
        render_directory=tmp_path,
        random_seed=0,
    )
    export_calls = []
    original_export_final_kpis = env.export_final_kpis

    def _export_final_kpis(*args, **kwargs):
        export_calls.append(env.episode_tracker.episode)
        return original_export_final_kpis(*args, **kwargs)

    monkeypatch.setattr(env, "export_final_kpis", _export_final_kpis)

    try:
        controller = Agent(env)
        controller.learn(episodes=2, logging_level=50)

        outputs_path = Path(env.new_folder_path)
        assert export_calls == [1]
        assert not any(outputs_path.glob("exported_data_*_ep0.csv"))
        assert (outputs_path / "exported_data_community_ep1.csv").is_file()
        assert (outputs_path / "exported_data_business_as_usual_ep1.csv").is_file()
        assert not (outputs_path / "exported_data_business_as_usual_ep0.csv").exists()
        assert (outputs_path / "exported_kpis.csv").is_file()
    finally:
        _cleanup_env(env)
        env.close()


def test_parquet_render_format_writes_chunked_exports_and_kpis(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="end",
        render_file_format="parquet",
        render_chunk_size=2,
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        while not env.terminated:
            _, _, terminated, truncated, _ = env.step(zeros)
            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        parquet_files = sorted(outputs_path.glob("*.parquet"))
        assert parquet_files
        assert any(path.name.startswith("exported_data_community_ep0_part") for path in parquet_files)
        assert any("business_as_usual" in path.name for path in parquet_files)
        assert (outputs_path / "exported_kpis.parquet").is_file()
        assert not (outputs_path / "exported_kpis.csv").exists()
        assert len(pd.read_parquet(outputs_path / "exported_kpis.parquet")) > 0
    finally:
        env.close()
        _cleanup_env(env)


def test_parquet_render_normalizes_mixed_numeric_string_and_numpy_scalars(tmp_path):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=2,
        render_mode="end",
        render_file_format="parquet",
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        env.reset()
        env._episode_exporter.ensure_output_dir()
        env._episode_exporter.write_render_rows(
            "mixed_numeric.parquet",
            [
                {"state": "-1.00", "name": ""},
                {"state": np.float32(1.0), "name": "EV-1"},
            ],
        )
        output = next(Path(env.new_folder_path).glob("mixed_numeric_part*.parquet"))
        frame = pd.read_parquet(output)
        assert frame["state"].tolist() == pytest.approx([-1.0, 1.0])
        assert pd.isna(frame.loc[0, "name"])
        assert frame.loc[1, "name"] == "EV-1"
    finally:
        env.close()
        _cleanup_env(env)


def test_csv_kpi_export_writes_missing_kpis_as_empty_cells_without_warnings(tmp_path):
    pd = pytest.importorskip("pandas")
    env = CityLearnEnv(str(DATASET), central_agent=True, episode_time_steps=2, render_directory=tmp_path)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            env.export_final_kpis(SimpleNamespace(env=env), filepath="kpis.csv")

        # pandas 3 warns that fillna('') fills float columns with a string.
        exporter_warnings = [str(w.message) for w in caught if Path(w.filename).name == "exporter.py"]
        assert exporter_warnings == []
        frame = pd.read_csv(Path(env.new_folder_path) / "kpis.csv", dtype=str, keep_default_na=False)
        cells = set(frame.drop(columns="KPI").to_numpy().ravel())
        assert "" in cells
        assert not {"nan", "NaN", "<NA>"} & cells
    finally:
        _cleanup_env(env)
        env.close()


def _write_parquet_rows(tmp_path, rows):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    exporter = EpisodeExporter(SimpleNamespace(new_folder_path=str(tmp_path)))
    exporter._write_parquet_rows("rows.parquet", rows)
    return pd.read_parquet(tmp_path / "rows_part00000.parquet")


def test_parquet_render_writes_text_mixed_with_numbers_as_text(tmp_path):
    frame = _write_parquet_rows(
        tmp_path,
        [
            {"ev": "EV-1"},
            {"ev": np.int64(42)},
            {"ev": np.float32(0.1)},
            {"ev": np.bool_(True)},
            {"ev": 3.5},
            {"ev": ""},
            {"ev": None},
        ],
    )

    # The number and boolean cells hold the text the CSV export writes for them
    # (str() of the value), not the float64 expansion of a float32.
    assert frame["ev"].iloc[:5].tolist() == ["EV-1", "42", "0.1", "True", "3.5"]
    assert frame["ev"].iloc[5:].isna().all()


def test_parquet_render_selects_text_columns_without_deprecation_warnings(tmp_path):
    with warnings.catch_warnings():
        # pandas 3 emits Pandas4Warning (a DeprecationWarning) from
        # select_dtypes(include=['object']) when a column has the str dtype.
        warnings.simplefilter("error", DeprecationWarning)
        warnings.simplefilter("error", FutureWarning)
        frame = _write_parquet_rows(
            tmp_path,
            [{"name": "EV-1", "state": "-1.00"}, {"name": "EV-2", "state": np.float32(1.0)}],
        )

    assert frame["name"].tolist() == ["EV-1", "EV-2"]
    assert frame["state"].tolist() == [-1.0, 1.0]


def test_parquet_render_keeps_list_cells_as_lists(tmp_path):
    pa = pytest.importorskip("pyarrow")
    frame = _write_parquet_rows(tmp_path / "lists", [{"v": [1, 2]}, {"v": [3]}, {"v": ""}])
    assert [list(value) for value in frame["v"].iloc[:2]] == [[1, 2], [3]]
    assert frame["v"].iloc[2] is None

    # No render row mixes lists with text. Such a column is not converted to
    # text: PyArrow rejects it, as it does on earlier releases.
    with pytest.raises(pa.ArrowInvalid):
        _write_parquet_rows(tmp_path / "mixed", [{"v": [1, 2]}, {"v": "EV-1"}])


def test_render_directory_override(tmp_path):
    custom_root = tmp_path / 'custom_results'

    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=2,
        render_mode="during",
        render_directory=custom_root,
    )

    try:
        _step_once(env)
        outputs_path = Path(env.new_folder_path)
        assert env.render_output_root == custom_root.resolve()
        assert outputs_path.is_dir()
        assert outputs_path.parent == env.render_output_root
    finally:
        _cleanup_env(env)
        env.close()


def test_default_start_date_used_for_render_timestamp():
    schema = _load_schema_dict()
    schema.pop('start_date', None)

    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=2)

    try:
        env.reset()
        timestamp = env._get_iso_timestamp()
        date_part, time_part = timestamp.split('T')
        year_str, month_str, day_str = date_part.split('-')

        assert int(year_str) == env.render_start_date.year == 2024
        assert int(day_str) == env.render_start_date.day
        assert int(month_str) == env.render_start_date.month
        assert time_part == "00:00:00"
    finally:
        env.close()


def test_schema_start_date_overrides_default_timestamp_start():
    schema = _load_schema_dict()
    schema['start_date'] = '2026-05-15'

    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=2)

    try:
        env.reset()
        timestamp = env._get_iso_timestamp()
        date_part, _ = timestamp.split('T')
        year_str, month_str, day_str = date_part.split('-')

        assert (int(year_str), int(month_str), int(day_str)) == (2026, 5, 15)
    finally:
        env.close()


def test_render_timestamp_advances_with_seconds_per_time_step():
    schema = _load_schema_dict()
    schema.pop('start_date', None)

    env = CityLearnEnv(
        schema,
        central_agent=True,
        episode_time_steps=4,
        seconds_per_time_step=60,
        time_step_ratio_mode='compress',
    )

    try:
        env.reset()
        t0 = env._get_iso_timestamp()
        env.step([np.zeros(env.action_space[0].shape[0], dtype="float32")])
        t1 = env._get_iso_timestamp()
        assert t0.endswith("00:00:00")
        assert t1.endswith("00:01:00")
    finally:
        env.close()


def test_render_after_episode_completion(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="during",
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        while not env.terminated:
            env.step(zeros)

        outputs_path = Path(env.new_folder_path)
        assert (outputs_path / 'exported_data_community_ep0.csv').exists()
    finally:
        _cleanup_env(env)
        env.close()


def test_render_mid_and_end_exports(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=4,
        render_mode="end",
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        mid_step = env.episode_tracker.episode_time_steps // 2

        for step in range(env.episode_tracker.episode_time_steps):
            _, _, terminated, truncated, _ = env.step(zeros)

            if step == mid_step:
                env.render()

            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        community_file = outputs_path / 'exported_data_community_ep0.csv'
        assert community_file.is_file()
        assert any(outputs_path.glob('exported_data_*_ep0.csv'))

        with community_file.open(newline='') as handle:
            reader = csv.reader(handle)
            rows = list(reader)

        # Header + one row per simulated timestep
        assert len(rows) == env.time_step + 1

        class _Model:
            pass

        model = _Model()
        model.env = env
        env.export_final_kpis(model)

        assert (outputs_path / 'exported_kpis.csv').is_file()
    finally:
        _cleanup_env(env)
        env.close()


def test_export_final_kpis_flushes_end_mode(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=3,
        render_mode="end",
        render_directory=tmp_path,
        random_seed=0,
    )

    class _Model:
        pass

    model = _Model()
    model.env = env

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
        while not env.terminated:
            env.step(zeros)

        env.export_final_kpis(model, filepath="exported_kpis_end.csv")

        outputs_path = Path(env.new_folder_path)
        community_file = outputs_path / "exported_data_community_ep0.csv"
        assert community_file.is_file()
        assert (outputs_path / "exported_kpis_end.csv").is_file()

        with community_file.open(newline="") as handle:
            rows = list(csv.reader(handle))

        assert len(rows) == env.time_step + 1
    finally:
        _cleanup_env(env)
        env.close()


def test_end_mode_exports_without_per_step_buffer_growth(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        episode_time_steps=5,
        render_mode="end",
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]

        while not env.terminated:
            _, _, terminated, truncated, _ = env.step(zeros)
            assert not any(env._render_buffer.values())
            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        community_file = outputs_path / "exported_data_community_ep0.csv"
        assert community_file.is_file()

        with community_file.open(newline="") as handle:
            rows = list(csv.reader(handle))

        # Header + one row per realized transition.
        assert len(rows) == env.time_step + 1
    finally:
        _cleanup_env(env)
        env.close()


def test_end_mode_export_file_contract_matches_during_mode(tmp_path):
    def _run(render_mode: str):
        env = CityLearnEnv(
            str(DATASET),
            central_agent=True,
            episode_time_steps=4,
            render_mode=render_mode,
            render_directory=tmp_path / render_mode,
            random_seed=0,
        )
        try:
            env.reset()
            zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]
            while not env.terminated:
                _, _, terminated, truncated, _ = env.step(zeros)
                if terminated or truncated:
                    break

            outputs_path = Path(env.new_folder_path)
            export_files = sorted(p.name for p in outputs_path.glob("exported_data_*_ep0.csv"))
            community_file = outputs_path / "exported_data_community_ep0.csv"
            with community_file.open(newline="") as handle:
                header = next(csv.reader(handle))

            return export_files, header
        finally:
            _cleanup_env(env)
            env.close()

    during_files, during_header = _run("during")
    end_files, end_header = _run("end")

    assert end_files == during_files
    assert end_header == during_header


def test_end_mode_ev_and_charger_content_matches_during_mode(tmp_path):
    def _run(render_mode: str) -> Path:
        env = CityLearnEnv(
            str(DATASET),
            central_agent=True,
            episode_time_steps=128,
            render_mode=render_mode,
            render_directory=tmp_path / render_mode,
            random_seed=7,
        )
        agent = Agent(env)

        try:
            observations, _ = env.reset()

            while not env.terminated:
                actions = agent.predict(observations, deterministic=True)
                observations, _, terminated, truncated, _ = env.step(actions)

                if terminated or truncated:
                    break

            return Path(env.new_folder_path)
        finally:
            env.close()

    during_dir = _run("during")
    end_dir = _run("end")

    all_files = sorted(p.name for p in during_dir.glob("exported_data_*_ep0.csv"))
    relevant_files = [name for name in all_files if ("charger" in name or "electric_vehicle" in name)]
    assert relevant_files, "Expected EV/charger export files to be present."

    for filename in relevant_files:
        during_path = during_dir / filename
        end_path = end_dir / filename
        assert end_path.exists(), f"Missing end-mode file: {filename}"

        with during_path.open(newline="") as handle:
            during_rows = list(csv.DictReader(handle))

        with end_path.open(newline="") as handle:
            end_rows = list(csv.DictReader(handle))

        assert during_rows == end_rows, f"Mismatch in EV/charger export data for file {filename}"
