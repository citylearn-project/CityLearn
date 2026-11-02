import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.experiment import experiment_manifest
from test_demand_response import (
    _copy_minute_schema,
    _clean_schema,
    _zero_entity_actions,
)


def schema_at(tmp_path, origin="2024-03-31T00:45:00Z", *, noise=0.0):
    schema = _copy_minute_schema(tmp_path)
    schema["demand_response"]["enabled"] = False
    root = Path(schema["_dataset_dir"])
    clock = pd.date_range(origin, periods=8, freq="15min")
    local = clock.tz_convert("Europe/Lisbon")
    (root / "shared").mkdir()
    pd.DataFrame(
        dict(
            time_step=range(8),
            timestamp_utc=clock.astype(str),
            timestamp_local=local.astype(str),
        )
    ).to_csv(root / "shared/calendar.csv", index=False)
    f = pd.read_csv(root / "Building_1.csv")
    f["month"] = local.month
    f["hour"] = local.hour + 1
    f["minutes"] = local.minute
    f.to_csv(root / "Building_1.csv", index=False)
    schema.update(
        start_date=str(clock[0].date()),
        timezone="Europe/Lisbon",
        time_axis={"calendar_file": "shared/calendar.csv"},
    )
    schema["buildings"]["Building_1"]["noise_std"] = noise
    return _clean_schema(schema), root


@pytest.mark.parametrize("origin", ["2024-03-31T00:45:00Z", "2024-10-27T00:45:00Z"])
def test_dst_does_not_change_dataset_resolution(tmp_path, origin):
    schema, _ = schema_at(tmp_path, origin)
    env = CityLearnEnv(schema, random_seed=3, offline=True)
    try:
        assert env.buildings[0].energy_simulation.dataset_seconds_per_time_step == 900
        assert env.buildings[0].time_step_ratio == 1
        env.reset(seed=3)
        env.step(_zero_entity_actions(env))
        expected = pd.Timestamp(origin).tz_convert("Europe/Lisbon") + pd.Timedelta(
            minutes=15
        )
        assert pd.Timestamp(env._get_iso_timestamp()) == expected
    finally:
        env.close()


def test_export_manifest_keeps_loaded_hash_after_input_changes(tmp_path):
    schema, root = schema_at(tmp_path)
    path = root / "pricing.csv"
    loaded = hashlib.sha256(path.read_bytes()).hexdigest()
    env = CityLearnEnv(schema, random_seed=2, offline=True)
    try:
        f = pd.read_csv(path)
        f.iloc[:, 0] = 99.0
        f.to_csv(path, index=False)
        m = experiment_manifest(env)
        assert m["data_files_sha256"]["pricing.csv"] == loaded
        assert "pricing.csv" in m["input_file_changes"]
        assert (
            m["temporal_reproducibility"]["definition_version"]
            == "temporal-evidence-v1"
        )
        with pytest.raises(ValueError, match="inputs changed"):
            env.run_business_as_usual_baseline()
    finally:
        env.close()


def test_unchanged_content_after_touch_does_not_invalidate_input(tmp_path):
    import os

    schema, root = schema_at(tmp_path)
    env = CityLearnEnv(schema, random_seed=2, offline=True)
    try:
        p = root / "pricing.csv"
        stat = p.stat()
        os.utime(p, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1000000))
        assert experiment_manifest(env)["input_file_changes"] == {}
    finally:
        env.close()


def test_pairing_records_initial_noise_seed_and_dependency_versions(tmp_path):
    from citylearn.internal.comparison import compare_manifests

    schema, _ = schema_at(tmp_path, noise=0.1)
    envs = []
    manifests = []
    try:
        for seed in (7, 8):
            e = CityLearnEnv(schema, random_seed=seed, offline=True)
            envs.append(e)
            e.reset(seed=19)
            m = experiment_manifest(e)
            m["controller_identity"] = dict(
                implementation="test",
                version="1",
                parameters={},
                observation_access="known",
            )
            manifests.append(m)
        assert "numpy" in manifests[0]["runtime_versions"]
        result = compare_manifests(*manifests)
        assert "temporal" in result["mismatches"]
    finally:
        for e in envs:
            e.close()


def test_seeded_reset_replays_fixed_window_and_preserves_unseeded_episode_variation(
    tmp_path,
):
    schema, _ = schema_at(tmp_path, origin="2024-01-01T00:00:00Z")
    env = CityLearnEnv(schema, random_seed=7, offline=True)
    try:
        traces = []
        for _ in range(2):
            env.reset(seed=7)
            while not env.terminated:
                env.step(_zero_entity_actions(env))
            traces.append(
                (env._ev_drift_seed, env.electric_vehicles[0].battery.soc.copy())
            )
        assert traces[0][0] == traces[1][0]
        np.testing.assert_array_equal(traces[0][1], traces[1][1])
        first = env._ev_drift_seed
        env.reset()
        assert env._ev_drift_seed != first
    finally:
        env.close()


def test_explicit_episode_index_replays_random_split(tmp_path):
    schema, _ = schema_at(tmp_path, origin="2024-01-01T00:00:00Z")
    env = CityLearnEnv(
        schema,
        random_seed=9,
        episode_time_steps=4,
        random_episode_split=True,
        offline=True,
    )
    try:
        env.reset(seed=9, options={"episode_index": 3})
        first = (env.episode_tracker.episode_start_time_step, env._ev_drift_seed)
        env.reset(seed=9, options={"episode_index": 3})
        assert first == (
            env.episode_tracker.episode_start_time_step,
            env._ev_drift_seed,
        )
        with pytest.raises(ValueError):
            env.reset(options={"episode_index": -1})
    finally:
        env.close()


def test_native_reference_retains_initialization_seed_after_reset_seed_change(tmp_path):
    schema, _ = schema_at(tmp_path, origin="2024-01-01T00:00:00Z", noise=0.1)
    schema["electric_vehicles_def"]["Electric_Vehicle_1"]["battery"]["attributes"].pop(
        "initial_soc", None
    )
    env = CityLearnEnv(schema, random_seed=7, offline=True)
    try:
        env.reset(seed=19)
        env.step(_zero_entity_actions(env))
        ref = env.run_business_as_usual_baseline().env
        assert ref._initialization_seed == env._initialization_seed == 7
        assert ref.random_seed == env.random_seed == 19
        np.testing.assert_array_equal(
            env.buildings[0].energy_simulation.solar_generation,
            ref.buildings[0].energy_simulation.solar_generation,
        )
    finally:
        env.close()


def test_robustness_default_seed_follows_explicit_reset_but_override_is_preserved(
    tmp_path,
):
    schema, _ = schema_at(tmp_path)
    env = CityLearnEnv(schema, random_seed=7, offline=True)
    try:
        env.reset(seed=19)
        assert env._robustness_service.random_seed == 19
        env.schema["robustness"] = {"enabled": False, "random_seed": 23}
        env._robustness_service.random_seed = 23
        env.reset(seed=20)
        assert env._robustness_service.random_seed == 23
    finally:
        env.close()


def test_noise_uses_owned_rng_and_global_window_coordinates(tmp_path):
    schema, root = schema_at(tmp_path, origin="2024-01-01T00:00:00Z", noise=0.1)
    before = np.random.get_state()
    environments = []
    try:
        a = CityLearnEnv(schema, random_seed=11, offline=True)
        environments.append(a)
        b = CityLearnEnv(schema, random_seed=11, offline=True)
        environments.append(b)
        np.testing.assert_array_equal(
            a.buildings[0].energy_simulation.solar_generation,
            b.buildings[0].energy_simulation.solar_generation,
        )
        after = np.random.get_state()
        assert before[0] == after[0] and before[2:] == after[2:]
        np.testing.assert_array_equal(before[1], after[1])
        short = CityLearnEnv(
            schema,
            random_seed=11,
            offline=True,
            simulation_start_time_step=2,
            simulation_end_time_step=5,
            episode_time_steps=4,
        )
        environments.append(short)
        np.testing.assert_array_equal(
            a.buildings[0].energy_simulation.solar_generation[2:6],
            short.buildings[0].energy_simulation.solar_generation,
        )
    finally:
        np.random.set_state(before)
        for e in environments:
            e.close()


@pytest.mark.parametrize(
    "source,target", [(900, 300), (300, 900), (900, 3600), (3600, 900), (60, 900)]
)
def test_typed_resampling_conserves_energy_and_constant_power(source, target):
    from citylearn.internal.temporal import resample_series

    duration = 3600
    n = duration // source
    energy = np.full(n, 2.0 * source / 3600.0)
    r = resample_series(energy, source, target, kind="energy")
    assert r.sum() == pytest.approx(2.0)
    np.testing.assert_allclose(
        resample_series(np.full(n, 2.0), source, target, kind="power"), 2.0
    )


def test_price_weighting_preserves_cost_without_claiming_time_mean_is_equivalent():
    from citylearn.internal.temporal import resample_series

    energy = np.array([1.0, 3.0, 0.0, 0.0])
    price = np.array([0.1, 0.3, 0.9, 0.2])
    coarse_energy = resample_series(energy, 900, 1800, kind="energy")
    coarse_price = resample_series(price, 900, 1800, kind="price", weights=energy)
    assert coarse_energy[0] * coarse_price[0] == pytest.approx(float(energy @ price))
    assert np.isnan(coarse_price[1])
    assert resample_series(price, 900, 1800, kind="price")[0] == pytest.approx(0.2)


@pytest.mark.parametrize("kind", ["event", "state", "unknown"])
def test_categorical_events_are_not_averaged(kind):
    from citylearn.internal.temporal import resample_series

    with pytest.raises(ValueError):
        resample_series([1, 2], 900, 1800, kind=kind)


def test_event_boundaries_are_exact_and_inclusive_end_is_explicit():
    from citylearn.internal.temporal import map_interval

    assert map_interval(1, 2, 900, 300, end_inclusive=True) == (3, 8)
    assert map_interval(0, 4, 900, 3600) == (0, 1)
    with pytest.raises(ValueError):
        map_interval(1, 2, 900, 3600)


def test_resampling_never_pads_a_partial_interval():
    from citylearn.internal.temporal import resample_series

    with pytest.raises(ValueError):
        resample_series([1, 2, 3], 900, 1000, kind="energy")


def test_loss_conversion_preserves_retention_for_equal_physical_duration():
    from citylearn.internal.temporal import rescale_step_loss

    quarter = rescale_step_loss(0.1, 3600, 900)
    assert (1 - quarter) ** 4 == pytest.approx(0.9)


def test_resampled_constant_power_rollouts_preserve_energy_cost_and_carbon(tmp_path):
    from citylearn.internal.temporal import resample_series
    results=[]
    for seconds in (900,300):
        folder=tmp_path/str(seconds);folder.mkdir()
        schema=_copy_minute_schema(folder);schema['demand_response']['enabled']=False
        root=Path(schema['_dataset_dir']);n=3600//seconds
        schema.update(seconds_per_time_step=seconds,simulation_end_time_step=n,episode_time_steps=n+1,
                      timezone='UTC',time_axis={'calendar_file':'calendar.csv'})
        schema['buildings']['Building_1']['chargers']={};schema['electric_vehicles_def']={}
        schema['actions']['electrical_storage']['active']=False
        schema['actions']['electric_vehicle_storage']['active']=False
        schema['buildings']['Building_1']['electrical_storage']['attributes'].update(capacity=0.,nominal_power=0.,initial_soc=0.)
        clock=pd.date_range('2024-01-01',periods=n+1,freq=f'{seconds}s',tz='UTC')
        pd.DataFrame(dict(time_step=range(n+1),timestamp_utc=clock.astype(str))).to_csv(root/'calendar.csv',index=False)
        original=pd.read_csv(root/'Building_1.csv');frame=pd.concat([original.iloc[[0]]]*(n+1),ignore_index=True)
        energy=resample_series([.5]*4,900,seconds,kind='energy')
        frame['hour']=clock.hour+1;frame['minutes']=clock.minute;frame['month']=1
        frame['non_shiftable_load']=np.r_[energy,energy[-1]]
        for name in ('cooling_demand','heating_demand','dhw_demand','solar_generation'):frame[name]=0.
        frame.to_csv(root/'Building_1.csv',index=False)
        for name in ('weather.csv','pricing.csv','carbon_intensity.csv'):
            original=pd.read_csv(root/name);f=pd.concat([original.iloc[[0]]]*(n+1),ignore_index=True)
            if name=='pricing.csv':
                prices=resample_series([.1,.2,.3,.4],900,seconds,kind='price')
                for column in f:f[column]=np.r_[prices,prices[-1]]
            if name=='carbon_intensity.csv':f['carbon_intensity']=.25
            f.to_csv(root/name,index=False)
        e=CityLearnEnv(_clean_schema(schema),random_seed=0,offline=True,physics_invariant_checks=True,export_kpis_on_episode_end=False)
        try:
            e.reset(seed=0)
            while not e.terminated:e.step(_zero_entity_actions(e))
            frame=e.evaluate_v2(include_business_as_usual=False).set_index(['name','cost_function']).value
            results.append([float(frame['District',key]) for key in ('district_energy_grid_total_import_control_kwh','district_cost_total_control_eur','district_energy_provenance_external_purchase_emissions_kgco2')])
        finally:e.close()
    np.testing.assert_allclose(results,[[2.,.5,.5],[2.,.5,.5]],atol=1e-6,rtol=1e-7)


@pytest.mark.parametrize("bad", ["duplicate", "missing", "reversed"])
def test_invalid_canonical_axis_is_rejected(tmp_path, bad):
    schema, root = schema_at(tmp_path)
    path = root / "shared/calendar.csv"
    f = pd.read_csv(path)
    if bad == "duplicate":
        f.loc[2, "timestamp_utc"] = f.loc[1, "timestamp_utc"]
    elif bad == "missing":
        f = f.drop(index=2)
    else:
        f = f.iloc[::-1]
    f.to_csv(path, index=False)
    with pytest.raises(ValueError):
        CityLearnEnv(schema, random_seed=0, offline=True)


def test_terminal_padding_is_explicit_and_clock_extends_only_at_terminal(tmp_path):
    schema, _ = schema_at(tmp_path, origin="2024-02-28T23:00:00Z")
    schema["terminal_observation_padding"] = True
    env = CityLearnEnv(
        schema,
        simulation_end_time_step=8,
        episode_time_steps=9,
        random_seed=0,
        offline=True,
    )
    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step(_zero_entity_actions(env))
        assert pd.Timestamp(env._get_iso_timestamp()) == pd.Timestamp(
            "2024-02-29T01:00:00Z"
        )
        m = experiment_manifest(env)["temporal_reproducibility"]
        assert m["executed_intervals"] == 8 and m["terminal_padding"] is True
    finally:
        env.close()


def test_unresampled_clock_mismatch_is_visible_in_manifest(tmp_path):
    schema, _ = schema_at(tmp_path)
    env = CityLearnEnv(schema, seconds_per_time_step=60, random_seed=0, offline=True)
    try:
        m = experiment_manifest(env)["temporal_reproducibility"]
        assert m["clock_consistent"] is False
        assert m["resampling"] == "none_runtime_energy_scaling_only"
    finally:
        env.close()


@pytest.mark.parametrize('dynamic',[False,True])
def test_member_daily_rates_use_executed_active_duration(tmp_path,dynamic):
    from test_independent_balances import scenario,commands
    events=[dict(id='out',time_step=2,operation='remove_member',target_member_id='Building_1'),dict(id='in',time_step=4,operation='add_member',target_member_id='Building_1')] if dynamic else None
    env=scenario(tmp_path,events=events)
    try:
        env.reset(seed=0)
        if dynamic:
            while not env.terminated:env.step(commands(env,[0.,0.]))
            intervals=5
        else:
            for _ in range(2):env.step(commands(env,[0.,0.]))
            intervals=2
        frame=env.evaluate_v2(include_business_as_usual=False).set_index(['name','cost_function']).value
        total=frame['Building_1','building_cost_total_control_eur']
        daily=frame['Building_1','building_cost_daily_average_control_eur']
        assert daily==pytest.approx(total/(intervals*env.seconds_per_time_step/86400))
    finally:env.close()


def test_legacy_render_origin_remains_naive_when_no_clock_is_declared():
    from citylearn.exporter import EpisodeExporter
    import datetime

    e = SimpleNamespace(
        schema={},
        time_step=2,
        seconds_per_time_step=60,
        episode_tracker=SimpleNamespace(episode_start_time_step=0),
        render_start_date=datetime.date(2024, 1, 1),
    )
    assert EpisodeExporter(e).get_iso_timestamp() == "2024-01-01T00:02:00"


@pytest.mark.parametrize('seed', [0, 2**32-1])
def test_random_split_stream_handles_zero_and_large_valid_seeds(seed):
    from citylearn.base import EpisodeTracker
    tracker = EpisodeTracker(0, 99)
    starts = []
    for _ in range(10):
        tracker.next_episode(5, False, True, seed)
        starts.append(tracker.episode_start_time_step)
    assert len(set(starts)) > 1
    tracker.reset_episode_index()
    for start in starts:
        tracker.next_episode(5, False, True, seed)
        assert tracker.episode_start_time_step == start
        assert 0 <= start <= tracker.episode_end_time_step <= 99


@pytest.mark.parametrize('unit', ['s', 'ms', 'us'])
def test_parquet_calendar_precision_does_not_change_physical_spacing(tmp_path, unit):
    from citylearn.internal.temporal import TimeAxis
    clock = pd.date_range('2024-01-01', periods=3, freq='15min', tz='UTC')
    # Parquet timestamps can preserve a coarser integer unit on reading.
    coarse = clock.as_unit(unit)
    pd.DataFrame({'time_step': range(3), 'timestamp_utc': coarse,
                  'timestamp_local': clock.tz_convert('Europe/Lisbon').astype(str)}).to_parquet(tmp_path/'clock.parquet')
    axis = TimeAxis({'root_directory': str(tmp_path),
                     'time_axis': {'calendar_file': 'clock.parquet'}})
    assert axis.seconds == 900
    assert axis.at(1) == pd.Timestamp('2024-01-01T00:15:00Z')
