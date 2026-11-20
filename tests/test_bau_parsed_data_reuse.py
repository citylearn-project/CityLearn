"""Tests for reusing already-parsed environment data in the native BAU reference (#291)."""
from __future__ import annotations

from copy import deepcopy
import gc
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "data" / "datasets"


def _load_schema(dataset_name: str) -> dict:
    folder = DATASETS / dataset_name
    schema = json.loads((folder / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(folder)
    return schema


def _step_episode(env: CityLearnEnv, *, active_actions: bool = True, max_steps: int | None = None) -> None:
    env.reset()
    rng = np.random.default_rng(19)
    steps = 0
    while not (env.terminated or env.truncated):
        if max_steps is not None and steps >= max_steps:
            break
        space = env.action_space
        if isinstance(space, list):
            if active_actions:
                actions = [
                    np.clip(rng.uniform(-0.85, 0.85, s.shape), s.low, s.high).astype("float32")
                    for s in space
                ]
            else:
                actions = [np.zeros(s.shape, dtype="float32") for s in space]
        else:
            if active_actions:
                actions = {
                    "tables": {
                        k: np.clip(rng.uniform(-0.85, 0.85, v.shape), v.low, v.high).astype("float32")
                        for k, v in space["tables"].items()
                    }
                }
            else:
                actions = {"tables": {}}
        env.step(actions)
        steps += 1


def _assert_kpis_bit_identical(actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    assert list(actual.columns) == list(expected.columns)
    assert len(actual) == len(expected)
    for col in ("cost_function", "name", "level", "unit", "description"):
        if col in actual.columns:
            assert actual[col].tolist() == expected[col].tolist()

    left = actual["value"].to_numpy(dtype="float64")
    right = expected["value"].to_numpy(dtype="float64")
    nan_left = np.isnan(left)
    nan_right = np.isnan(right)
    assert np.array_equal(nan_left, nan_right)
    finite = ~nan_left
    assert np.array_equal(left[finite].view("u8"), right[finite].view("u8"))


def _export_bau_bytes(env: CityLearnEnv, tmp_path: Path, tag: str, fmt: str = "csv") -> bytes:
    out_dir = tmp_path / f"{tag}_{fmt}"
    out_dir.mkdir(parents=True, exist_ok=True)
    env.render_file_format = fmt
    env.new_folder_path = str(out_dir)
    env._episode_exporter._chunk_counters.clear()
    env._episode_exporter.export_business_as_usual_timeseries(env)
    files = sorted(out_dir.iterdir())
    assert files
    return b"||".join(f.read_bytes() for f in files)


def _record_tabular_reads(monkeypatch) -> list[str]:
    calls: list[str] = []

    def wrap(fn):
        def wrapper(*args, **kwargs):
            calls.append(str(args[0]) if args else "<unknown>")
            return fn(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(pd, "read_csv", wrap(pd.read_csv))
    monkeypatch.setattr(pd, "read_parquet", wrap(pd.read_parquet))
    try:
        import pyarrow.parquet as pq
        monkeypatch.setattr(pq, "ParquetFile", wrap(pq.ParquetFile))
        monkeypatch.setattr(pq, "read_table", wrap(pq.read_table))
    except ImportError:
        pass
    return calls


def _assert_bau_matches_fresh_load_with_zero_reads(
    env: CityLearnEnv,
    tmp_path: Path,
    monkeypatch,
    *,
    tag: str,
    expect_zero_reads: bool = True,
    check_parquet_export: bool = False,
) -> CityLearnEnv:
    saved_parsed = env._parsed_data

    # Fresh reference load from disk (parsed cache disabled).
    env._business_as_usual_baseline_service.clear()
    env._kpi_service._settled_cost_cache = None
    env._parsed_data = None
    kpis_fresh = env.evaluate_v2(include_business_as_usual=True)
    csv_fresh = _export_bau_bytes(env, tmp_path, f"{tag}_fresh", "csv")
    pq_fresh = _export_bau_bytes(env, tmp_path, f"{tag}_fresh", "parquet") if check_parquet_export else None

    # Cached reference load from env._parsed_data.
    env._business_as_usual_baseline_service.clear()
    env._kpi_service._settled_cost_cache = None
    env._parsed_data = saved_parsed
    reads = _record_tabular_reads(monkeypatch)
    kpis_cached = env.evaluate_v2(include_business_as_usual=True)
    if expect_zero_reads:
        assert reads == [], f"Expected 0 CSV/Parquet reads during BAU evaluation, got: {reads}"
    else:
        assert len(reads) > 0

    _assert_kpis_bit_identical(kpis_cached, kpis_fresh)
    csv_cached = _export_bau_bytes(env, tmp_path, f"{tag}_cached", "csv")
    assert csv_cached == csv_fresh
    if check_parquet_export:
        pq_cached = _export_bau_bytes(env, tmp_path, f"{tag}_cached", "parquet")
        assert pq_cached == pq_fresh

    cache = env._business_as_usual_baseline_cache
    return next(iter(cache.values())).env


def test_bau_reuses_parsed_series_read_only_and_copies_writable_series(tmp_path, monkeypatch):
    schema = _load_schema("citylearn_challenge_2022_phase_all_plus_evs")
    schema["buildings"] = dict(list(schema["buildings"].items())[:3])
    env = CityLearnEnv(
        schema,
        offline=True,
        simulation_start_time_step=0,
        simulation_end_time_step=240,
        episode_time_steps=[(48, 96)],
        random_seed=7,
        render_mode="none",
    )
    _step_episode(env, active_actions=True)

    # Mutate post-episode arrays in place on the evaluated env to prove BAU reads pristine parsed data.
    b0_sim = env.buildings[0].energy_simulation
    b0_sim.cooling_demand[:] = 999.0
    b0_sim.heating_demand[:] = 0.0
    b0_sim.indoor_dry_bulb_temperature[:] = 45.0
    b0_sim.hvac_mode[:] = 0

    bau_env = _assert_bau_matches_fresh_load_with_zero_reads(env, tmp_path, monkeypatch, tag="std_ev")
    bau_b0_sim = bau_env.buildings[0].energy_simulation

    # Simulator-writable series on BAU are independent writable copies.
    for writable_name in (
        "cooling_demand",
        "heating_demand",
        "indoor_dry_bulb_temperature",
        "indoor_dry_bulb_temperature_cooling_set_point",
        "indoor_dry_bulb_temperature_heating_set_point",
    ):
        arr = bau_b0_sim.__dict__[f"_{writable_name}"]
        assert arr.flags.writeable, writable_name
        assert not np.shares_memory(arr, b0_sim.__dict__[f"_{writable_name}"])

    assert not np.any(bau_b0_sim.cooling_demand == 999.0)

    # Exogenous / simulator-read-only series on BAU are read-only views into env._parsed_data.
    for readonly_name in (
        "month",
        "hour",
        "day_type",
        "non_shiftable_load",
        "dhw_demand",
        "solar_generation",
        "hvac_mode",
        "power_outage",
        "comfort_band",
        "cooling_demand_without_control",
    ):
        arr = bau_b0_sim.__dict__[f"_{readonly_name}"]
        assert not arr.flags.writeable, readonly_name
        with pytest.raises(ValueError):
            arr[0] = arr[0]

    assert not bau_env.buildings[0].weather._outdoor_dry_bulb_temperature.flags.writeable
    assert not bau_env.buildings[0].pricing._electricity_pricing.flags.writeable
    assert not bau_env.buildings[0].carbon_intensity._carbon_intensity.flags.writeable
    for building in bau_env.buildings:
        for charger in building.electric_vehicle_chargers or []:
            assert not charger.charger_simulation._electric_vehicle_charger_state.flags.writeable
            assert not charger.charger_simulation._electric_vehicle_required_soc_departure.flags.writeable

    # Sidecar itself does not retain a duplicate parsed-data cache.
    assert bau_env._parsed_data is None


def test_bau_parquet_pt_rec_and_terminal_padding_bit_identical_zero_reads(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    schema = _load_schema("pt_rec_4")
    # Include both a mid-year split and the terminal-padded end-of-year split.
    env = CityLearnEnv(
        schema,
        offline=True,
        episode_time_steps=[(96, 144), (35008, 35040)],
        random_seed=3,
        render_mode="none",
    )

    _step_episode(env, active_actions=True)
    _assert_bau_matches_fresh_load_with_zero_reads(
        env, tmp_path, monkeypatch, tag="pt_rec_4_ep0", check_parquet_export=True,
    )

    # Advance to the second episode (ending on the synthesized terminal-observation row 35040).
    _step_episode(env, active_actions=True)
    _assert_bau_matches_fresh_load_with_zero_reads(
        env, tmp_path, monkeypatch, tag="pt_rec_4_ep1_terminal", check_parquet_export=True,
    )
    del env
    gc.collect()


def test_bau_15s_parquet_and_dynamic_topology_bit_identical_zero_reads(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    schema_15s = _load_schema("citylearn_three_phase_electrical_service_demo_15s_parquet")
    schema_15s["buildings"] = dict(list(schema_15s["buildings"].items())[:4])
    env_15s = CityLearnEnv(
        schema_15s,
        offline=True,
        simulation_start_time_step=0,
        simulation_end_time_step=1200,
        episode_time_steps=[(240, 360)],
        random_seed=5,
        render_mode="none",
    )
    _step_episode(env_15s, active_actions=True)
    _assert_bau_matches_fresh_load_with_zero_reads(
        env_15s, tmp_path, monkeypatch, tag="15s_parquet", check_parquet_export=True,
    )
    del env_15s
    gc.collect()

    schema_dyn = _load_schema("citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet")
    env_dyn = CityLearnEnv(
        schema_dyn,
        offline=True,
        simulation_start_time_step=0,
        simulation_end_time_step=2400,
        episode_time_steps=[(600, 720)],
        random_seed=5,
        render_mode="none",
    )
    _step_episode(env_dyn, active_actions=True)
    _assert_bau_matches_fresh_load_with_zero_reads(env_dyn, tmp_path, monkeypatch, tag="dyn_15s")
    del env_dyn
    gc.collect()


def test_bau_with_nonzero_noise_std_matches_fresh_indexed_noise_draws(tmp_path, monkeypatch):
    schema = _load_schema("citylearn_challenge_2022_phase_all_plus_evs")
    schema["buildings"] = dict(list(schema["buildings"].items())[:3])
    for b_cfg in schema["buildings"].values():
        b_cfg["noise_std"] = 0.65
        for c_cfg in (b_cfg.get("chargers") or {}).values():
            c_cfg["noise_std"] = 3.0

    env = CityLearnEnv(
        schema,
        offline=True,
        simulation_start_time_step=24,
        simulation_end_time_step=240,
        episode_time_steps=[(72, 120)],
        random_seed=123,
        render_mode="none",
    )
    _step_episode(env, active_actions=True)
    _assert_bau_matches_fresh_load_with_zero_reads(env, tmp_path, monkeypatch, tag="noisy")


def test_bau_thermal_dynamics_and_occupant_mutations_do_not_leak_into_reference(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    schema = _load_schema("citylearn_challenge_2023_phase_2_local_evaluation")
    env = CityLearnEnv(
        schema,
        offline=True,
        simulation_start_time_step=0,
        simulation_end_time_step=120,
        episode_time_steps=[(24, 72)],
        random_seed=11,
        render_mode="none",
    )
    _step_episode(env, active_actions=True)

    # Active HVAC actions under LSTM thermal dynamics and occupant models mutate temperatures,
    # demands and set-point deltas during the episode; verify they changed from uncontrolled values.
    changed = any(
        not np.array_equal(b.energy_simulation.cooling_demand, b.energy_simulation.cooling_demand_without_control)
        or not np.array_equal(
            b.energy_simulation.indoor_dry_bulb_temperature,
            b.energy_simulation.indoor_dry_bulb_temperature_without_control,
        )
        for b in env.buildings
    )
    assert changed

    _assert_bau_matches_fresh_load_with_zero_reads(env, tmp_path, monkeypatch, tag="dynamics_occupant")


def test_bau_demand_response_robustness_and_community_tariffs_zero_reads(tmp_path, monkeypatch):
    for ds_name, tag in (
        ("citylearn_challenge_2022_phase_all_demand_response", "dr"),
        ("citylearn_challenge_2022_phase_all_robustness", "rob"),
    ):
        schema = _load_schema(ds_name)
        schema["buildings"] = dict(list(schema["buildings"].items())[:2])
        env = CityLearnEnv(
            schema,
            offline=True,
            simulation_start_time_step=0,
            simulation_end_time_step=96,
            episode_time_steps=[(12, 48)],
            random_seed=9,
            render_mode="none",
        )
        _step_episode(env, active_actions=True)
        _assert_bau_matches_fresh_load_with_zero_reads(env, tmp_path, monkeypatch, tag=tag)

    # Community market with explicit tariff_files inside dataset root.
    tariff_root = tmp_path / "tariff_ds"
    src_root = DATASETS / "citylearn_three_phase_electrical_service_demo"
    schema_tariff = json.loads((src_root / "schema.json").read_text(encoding="utf-8"))
    schema_tariff["buildings"] = dict(list(schema_tariff["buildings"].items())[:2])
    tariff_root.mkdir()
    for b_cfg in schema_tariff["buildings"].values():
        for key in ("energy_simulation", "weather", "carbon_intensity", "pricing"):
            fname = b_cfg.get(key)
            if fname and not (tariff_root / fname).exists():
                (tariff_root / fname).write_bytes((src_root / fname).read_bytes())
        for c_cfg in (b_cfg.get("chargers") or {}).values():
            fname = c_cfg.get("charger_simulation")
            if fname and not (tariff_root / fname).exists():
                (tariff_root / fname).write_bytes((src_root / fname).read_bytes())
        b_cfg.pop("deferrable_appliances", None)
    b0_name = next(iter(schema_tariff["buildings"]))
    pd.DataFrame({
        "grid_export_price": np.full(64, 0.04),
        "community_buy_price": np.full(64, 0.11),
        "community_sell_price": np.full(64, 0.09),
    }).to_csv(tariff_root / "tariff_b0.csv", index=False)
    schema_tariff["root_directory"] = str(tariff_root)
    schema_tariff.setdefault("community_market", {})["enabled"] = True
    schema_tariff["community_market"]["tariff_files"] = {b0_name: "tariff_b0.csv"}

    env_tariff = CityLearnEnv(
        schema_tariff,
        offline=True,
        simulation_start_time_step=0,
        simulation_end_time_step=48,
        episode_time_steps=[(8, 32)],
        random_seed=4,
        render_mode="none",
    )
    _step_episode(env_tariff, active_actions=True)
    _assert_bau_matches_fresh_load_with_zero_reads(env_tariff, tmp_path, monkeypatch, tag="tariffs")


def test_bau_skips_parsed_window_reuse_and_stays_bit_identical_when_autosized(tmp_path, monkeypatch):
    # Test autosizing fallback without requiring PyTorch (citylearn_challenge_2021 autosizes devices).
    schema = _load_schema("citylearn_challenge_2021")
    schema["buildings"] = dict(list(schema["buildings"].items())[:2])
    env = CityLearnEnv(
        schema,
        offline=True,
        simulation_start_time_step=0,
        simulation_end_time_step=240,
        episode_time_steps=[(24, 72)],
        random_seed=13,
        render_mode="none",
    )
    _step_episode(env, active_actions=True)
    _assert_bau_matches_fresh_load_with_zero_reads(
        env, tmp_path, monkeypatch, tag="autosized_2021", expect_zero_reads=False,
    )


def test_loader_accepts_parsed_data_source_directly_and_deepcopy_shares_it(monkeypatch):
    schema = _load_schema("citylearn_challenge_2022_phase_all")
    schema["buildings"] = dict(list(schema["buildings"].items())[:2])
    env = CityLearnEnv(
        deepcopy(schema),
        offline=True,
        simulation_start_time_step=0,
        simulation_end_time_step=96,
        episode_time_steps=24,
        random_seed=0,
        render_mode="none",
    )
    assert env._parsed_data is not None and env._parsed_data.frozen
    copied_env = deepcopy(env)
    assert copied_env._parsed_data is env._parsed_data

    reads = _record_tabular_reads(monkeypatch)
    rebuilt = CityLearnEnv(
        deepcopy(schema),
        offline=True,
        simulation_start_time_step=12,
        simulation_end_time_step=48,
        episode_time_steps=[(12, 48)],
        random_seed=0,
        render_mode="none",
        _parsed_data=env._parsed_data,
    )
    assert reads == []
    assert [b.name for b in rebuilt.buildings] == [b.name for b in env.buildings]
    np.testing.assert_array_equal(
        rebuilt.buildings[0].energy_simulation.non_shiftable_load,
        env.buildings[0].energy_simulation._non_shiftable_load[12:49],
    )


def test_compact_charger_series_preserves_exact_dtypes_values_and_noise():
    from citylearn.data import ChargerSimulation
    from citylearn.internal.parsed_data import ParsedDataSource, WindowSpec

    df = pd.DataFrame({
        "electric_vehicle_charger_state": [1, 2, 3, np.nan, -1, 1.5, 0],
        "electric_vehicle_id": ["EV_01", "EV_01", "", np.nan, "01", "1", "EV_02"],
        "electric_vehicle_session_id": ["S01", "S01", "", np.nan, "01", "1", "S02"],
        "electric_vehicle_departure_time": [12.0, np.nan, -1.0, 0.0, 40_000.0, 5.0, np.nan],
        "electric_vehicle_estimated_arrival_time": [np.nan, 8.0, -1.0, 0.0, 3.0, np.nan, 15.0],
        "electric_vehicle_required_soc_departure": [0.8, 85.0, np.nan, -0.0, 105.0, -0.1, 1.0],
        "electric_vehicle_estimated_soc_arrival": [0.25, 40.0, np.nan, 0.0, 0.9, -2.0, 100.0],
    })
    pds = ParsedDataSource()
    spec = WindowSpec(
        simulation_start=0,
        simulation_end=len(df) - 1,
        source_end=len(df) - 1,
        expected_rows=len(df),
        window_key=None,
        sliceable=True,
    )
    entry = pds.store_charger("charger_edge.csv", df, spec=spec)
    assert entry is not None
    assert entry.charger_state.dtype == np.int8
    assert entry.estimated_arrival_time.dtype == np.int16
    assert entry.departure_time.dtype == np.int32  # 40_000 > int16 max

    for slc, offset in ((slice(0, len(df)), 0), (slice(1, 6), 1)):
        sub = df.iloc[slc]
        for noise_std in (0.0, 2.5):
            ref = ChargerSimulation(
                sub["electric_vehicle_charger_state"].to_numpy(),
                sub["electric_vehicle_id"].to_numpy(),
                sub["electric_vehicle_departure_time"].to_numpy(),
                sub["electric_vehicle_required_soc_departure"].to_numpy(),
                sub["electric_vehicle_estimated_arrival_time"].to_numpy(),
                sub["electric_vehicle_estimated_soc_arrival"].to_numpy(),
                electric_vehicle_session_id=sub["electric_vehicle_session_id"].to_numpy(),
                noise_std=noise_std,
                noise_seed=42,
                noise_start_index=offset,
            )
            for share_readonly in (False, True):
                built = entry.build(
                    slc,
                    noise_std=noise_std,
                    noise_seed=42,
                    noise_start_index=offset,
                    time_step_offset=offset,
                    share_readonly=share_readonly,
                )
                for attr in (
                    "electric_vehicle_charger_state",
                    "electric_vehicle_departure_time",
                    "electric_vehicle_estimated_arrival_time",
                    "electric_vehicle_required_soc_departure",
                    "electric_vehicle_estimated_soc_arrival",
                ):
                    a = built.__dict__[f"_{attr}"]
                    b = ref.__dict__[f"_{attr}"]
                    assert a.dtype == b.dtype
                    assert np.array_equal(a.view(f"u{a.dtype.itemsize}"), b.view(f"u{b.dtype.itemsize}"))
                for obj_attr in ("electric_vehicle_id", "electric_vehicle_session_id"):
                    a_obj = built.__dict__[f"_{obj_attr}"]
                    b_obj = ref.__dict__[f"_{obj_attr}"]
                    assert a_obj.dtype == object and a_obj.flags.writeable == (not share_readonly)
                    assert [
                        ("nan", type(x)) if isinstance(x, float) and np.isnan(x) else (type(x), x)
                        for x in a_obj
                    ] == [
                        ("nan", type(x)) if isinstance(x, float) and np.isnan(x) else (type(x), x)
                        for x in b_obj
                    ]


def _stage_single_cycle_deferrable_scenario(root: Path) -> Path:
    src = DATASETS / "citylearn_three_phase_electrical_service_demo"
    schema = json.loads((src / "schema.json").read_text(encoding="utf-8"))
    schema["buildings"] = {"Building_1": deepcopy(schema["buildings"]["Building_1"])}
    b1 = schema["buildings"]["Building_1"]
    b1.pop("chargers", None)
    schema["electric_vehicles_def"] = {}

    root.mkdir(parents=True, exist_ok=True)
    for key in ("energy_simulation", "weather", "carbon_intensity", "pricing"):
        fname = b1[key]
        (root / fname).write_bytes((src / fname).read_bytes())

    pd.DataFrame([
        {
            "profile_id": "profile_001",
            "duration_steps": 2,
            "total_energy_kwh": 0.3,
            "load_profile": "[0.1, 0.2]",
        }
    ]).to_csv(root / "deferrable_appliance_1_cycle_profiles.csv", index=False)
    pd.DataFrame([
        {
            "cycle_id": "cycle_0001",
            "profile_id": "profile_001",
            "earliest_start_time_step": 1,
            "latest_start_time_step": 3,
            "deadline_time_step": 5,
            "priority": 1.0,
            "must_run": True,
        }
    ]).to_csv(root / "deferrable_appliance_1_flexibility_schedule.csv", index=False)

    schema["simulation_start_time_step"] = 0
    schema["simulation_end_time_step"] = 12
    schema_path = root / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    return schema_path


def _assert_bau_reference_timeseries_equal(actual_bau: CityLearnEnv, expected_bau: CityLearnEnv) -> None:
    assert int(actual_bau.time_step) == int(expected_bau.time_step)
    for attr in (
        "net_electricity_consumption",
        "net_electricity_consumption_cost",
        "net_electricity_consumption_emission",
    ):
        left = np.asarray(getattr(actual_bau, attr), dtype="float64")
        right = np.asarray(getattr(expected_bau, attr), dtype="float64")
        assert np.array_equal(left.view("u8"), right.view("u8")), attr

    assert len(actual_bau.buildings) == len(expected_bau.buildings)
    for b_act, b_exp in zip(actual_bau.buildings, expected_bau.buildings):
        for attr in (
            "net_electricity_consumption",
            "net_electricity_consumption_cost",
            "net_electricity_consumption_emission",
            "solar_generation",
        ):
            left = np.asarray(getattr(b_act, attr), dtype="float64")
            right = np.asarray(getattr(b_exp, attr), dtype="float64")
            assert np.array_equal(left.view("u8"), right.view("u8")), f"{b_act.name}.{attr}"

        if b_act.electrical_storage is not None and b_exp.electrical_storage is not None:
            for attr in ("electricity_consumption", "soc"):
                left = np.asarray(getattr(b_act.electrical_storage, attr), dtype="float64")
                right = np.asarray(getattr(b_exp.electrical_storage, attr), dtype="float64")
                assert np.array_equal(left.view("u8"), right.view("u8")), f"{b_act.name}.battery.{attr}"

        assert len(b_act.deferrable_appliances) == len(b_exp.deferrable_appliances)
        for app_act, app_exp in zip(b_act.deferrable_appliances, b_exp.deferrable_appliances):
            left = np.asarray(app_act.electricity_consumption, dtype="float64")
            right = np.asarray(app_exp.electricity_consumption, dtype="float64")
            assert np.array_equal(left.view("u8"), right.view("u8")), app_act.name
            assert app_act.service_summary() == app_exp.service_summary()
            assert app_act.service_audit() == app_exp.service_audit()


def _public_export_bau_artifacts(
    env: CityLearnEnv, render_root: Path, session_name: str, fmt: str,
) -> tuple[pd.DataFrame, bytes, bytes]:
    env.render_output_root = render_root
    env.render_session_name = session_name
    env.render_file_format = fmt
    env._render_directory_path = None
    env._render_dir_initialized = False
    env._episode_exporter._chunk_counters.clear()
    env.export_final_kpis(
        filepath="exported_kpis.csv",
        include_business_as_usual=True,
        export_business_as_usual_timeseries=True,
    )
    out_dir = Path(env.new_folder_path)
    if fmt == "csv":
        bau_files = sorted(out_dir.glob("exported_data_business_as_usual_ep*.csv"))
        kpi_files = sorted(out_dir.glob("exported_kpis.csv"))
        assert len(bau_files) == 1 and len(kpi_files) == 1
        frame = pd.read_csv(bau_files[0])
    else:
        bau_files = sorted(out_dir.glob("exported_data_business_as_usual_ep*.parquet"))
        kpi_files = sorted(out_dir.glob("exported_kpis.parquet"))
        assert len(bau_files) >= 1 and len(kpi_files) == 1
        frame = pd.concat([pd.read_parquet(p) for p in bau_files], ignore_index=True)

    bau_bytes = b"||".join(p.read_bytes() for p in bau_files)
    kpi_bytes = b"||".join(p.read_bytes() for p in kpi_files)
    return frame, bau_bytes, kpi_bytes


@pytest.mark.parametrize(
    "mutation_kind",
    [
        "clear_schedule_before_eval",
        "mutate_schedule_list_before_rollout",
        "edit_schedule_entry_dict_fields_only",
        "edit_schedule_entry_and_profile_in_place",
        "edit_cycle_profiles_catalogue_and_array_in_place",
    ],
)
def test_bau_deferrable_appliance_isolated_from_evaluated_env_mutations(tmp_path, monkeypatch, mutation_kind):
    pytest.importorskip("pyarrow")
    schema_path = _stage_single_cycle_deferrable_scenario(tmp_path / "scenario")

    def _build_and_run(disable_parsed_cache: bool) -> CityLearnEnv:
        env = CityLearnEnv(
            str(schema_path),
            offline=True,
            episode_time_steps=[(0, 7)],
            random_seed=7,
            render_mode="none",
        )
        if disable_parsed_cache:
            env._parsed_data = None

        app = env.buildings[0].deferrable_appliances[0]
        sim = app.deferrable_appliance_simulation

        if mutation_kind == "mutate_schedule_list_before_rollout":
            sim.flexibility_schedule.clear()
            sim.flexibility_schedule.append({
                "cycle_id": "injected_cycle",
                "profile_id": "profile_001",
                "earliest_start_time_step": 0,
                "latest_start_time_step": 1,
                "deadline_time_step": 3,
                "priority": 1.0,
                "must_run": True,
                "duration_steps": 2,
                "total_energy_kwh": 0.9,
                "load_profile": np.array([0.45, 0.45], dtype="float32"),
            })
        elif mutation_kind == "edit_schedule_entry_dict_fields_only":
            entry = sim.flexibility_schedule[0]
            entry["earliest_start_time_step"] = 9
            entry["latest_start_time_step"] = 10
            entry["deadline_time_step"] = 11
            entry["total_energy_kwh"] = 1.6
            entry["must_run"] = False
            entry["priority"] = 0.25
            entry["load_profile"] = np.array([0.7, 0.9], dtype="float32")
        elif mutation_kind == "edit_schedule_entry_and_profile_in_place":
            entry = sim.flexibility_schedule[0]
            entry["earliest_start_time_step"] = 9
            entry["latest_start_time_step"] = 10
            entry["deadline_time_step"] = 11
            entry["total_energy_kwh"] = 1.6
            entry["must_run"] = False
            entry["priority"] = 0.25
            entry["load_profile"][:] = np.array([0.7, 0.9], dtype="float32")
        elif mutation_kind == "edit_cycle_profiles_catalogue_and_array_in_place":
            prof = sim.cycle_profiles["profile_001"]
            prof["load_profile"][:] = np.array([0.8, 0.9], dtype="float32")
            prof["total_energy_kwh"] = 1.7
            prof["duration_steps"] = 1
            sim.cycle_profiles.clear()

        _step_episode(env, active_actions=False)

        if mutation_kind == "clear_schedule_before_eval":
            sim.flexibility_schedule.clear()

        return env

    render_root = tmp_path / "renders"
    env_fresh = _build_and_run(disable_parsed_cache=True)
    kpis_fresh = env_fresh.evaluate_v2(include_business_as_usual=True)
    bau_fresh = env_fresh.run_business_as_usual_baseline().env
    csv_frame_fresh, csv_bau_fresh, csv_kpi_fresh = _public_export_bau_artifacts(
        env_fresh, render_root, f"{mutation_kind}_fresh_csv", "csv",
    )
    pq_frame_fresh, pq_bau_fresh, pq_kpi_fresh = _public_export_bau_artifacts(
        env_fresh, render_root, f"{mutation_kind}_fresh_pq", "parquet",
    )

    env_cached = _build_and_run(disable_parsed_cache=False)
    assert env_cached._parsed_data is not None and env_cached._parsed_data.frozen
    reads = _record_tabular_reads(monkeypatch)
    kpis_cached = env_cached.evaluate_v2(include_business_as_usual=True)
    assert reads == [], f"Expected 0 disk reads during cached BAU evaluation, got: {reads}"
    bau_cached = env_cached.run_business_as_usual_baseline().env

    # Verify the native BAU reference still completed the 1 scheduled cycle and served 0.3 kWh.
    kpi_lookup = dict(zip(kpis_cached["cost_function"], kpis_cached["value"]))
    assert kpi_lookup["district_deferrable_appliance_service_completed_cycles_business_as_usual_count"] == pytest.approx(1.0)
    assert kpi_lookup["district_deferrable_appliance_service_served_energy_total_business_as_usual_kwh"] == pytest.approx(0.3)

    # 1. Reference BAU time-series and service-audit parity.
    _assert_bau_reference_timeseries_equal(bau_cached, bau_fresh)

    # 2. Full KPI table parity (rows, metadata columns, and IEEE-754 float64 bit values).
    _assert_kpis_bit_identical(kpis_cached, kpis_fresh)

    # 3. Exported BAU time-series and KPI parity in both CSV and Parquet via public export API.
    csv_frame_cached, csv_bau_cached, csv_kpi_cached = _public_export_bau_artifacts(
        env_cached, render_root, f"{mutation_kind}_cached_csv", "csv",
    )
    pq_frame_cached, pq_bau_cached, pq_kpi_cached = _public_export_bau_artifacts(
        env_cached, render_root, f"{mutation_kind}_cached_pq", "parquet",
    )
    pd.testing.assert_frame_equal(csv_frame_cached, csv_frame_fresh, check_exact=True)
    pd.testing.assert_frame_equal(pq_frame_cached, pq_frame_fresh, check_exact=True)
    assert csv_bau_cached == csv_bau_fresh
    assert csv_kpi_cached == csv_kpi_fresh
    assert pq_bau_cached == pq_bau_fresh
    assert pq_kpi_cached == pq_kpi_fresh



