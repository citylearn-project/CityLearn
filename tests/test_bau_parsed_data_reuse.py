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
    for col in ("cost_function", "name", "level"):
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

