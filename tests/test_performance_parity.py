from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from citylearn.agents.baseline import RBCCommunityPolicy
from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv
from citylearn.data import DeferrableApplianceSimulation, EnergySimulation, TimeSeriesData
from citylearn.energy_model import Battery, ElectricDevice


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_2022 = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"
SCHEMA_3PHASE_15S = ROOT / "data/datasets/citylearn_three_phase_electrical_service_demo_15s_parquet/schema.json"


def test_timeseries_data_presliced_views_and_legacy_fallback():
    ts = TimeSeriesData(start_time_step=2, end_time_step=5)
    raw = np.arange(10, dtype="float32")
    ts.load = raw

    assert np.array_equal(ts.load, np.array([2, 3, 4, 5], dtype="float32"))
    # Mutating the pre-sliced view updates the backing array in place.
    ts.load[1] = 99.0
    assert raw[3] == 99.0

    # Changing episode bounds refreshes views automatically.
    ts.start_time_step = 0
    ts.end_time_step = 2
    assert np.array_equal(ts.load, np.array([0, 1, 2], dtype="float32"))
    assert np.array_equal(ts.__getattr__("load", start_time_step=3, end_time_step=4), np.array([99, 4], dtype="float32"))

    # Legacy unpickled state with only `_load` in `__dict__` still resolves via `__getattr__`.
    del ts.__dict__["load"]
    assert np.array_equal(ts.load, np.array([0, 1, 2], dtype="float32"))

    # EnergySimulation.time_step_ratios property remains intact even on non-zero start windows.
    n = 12
    zeros = np.zeros(n, dtype="float32")
    ones = np.ones(n, dtype="int32")
    es = EnergySimulation(
        month=ones,
        hour=ones,
        day_type=ones,
        indoor_dry_bulb_temperature=zeros + 22.0,
        non_shiftable_load=zeros + 1.0,
        dhw_demand=zeros,
        cooling_demand=zeros,
        heating_demand=zeros,
        solar_generation=zeros,
        start_time_step=4,
        end_time_step=8,
        seconds_per_time_step=900,
    )
    assert len(es.non_shiftable_load) == 5
    assert len(es.time_step_ratios) == 1


def test_electricity_consumption_at_and_loss_coefficient_parity():
    tracker = EpisodeTracker(0, 9)
    tracker.next_episode(10, False, False, 0)

    dev = ElectricDevice(
        nominal_power=10.0,
        episode_tracker=tracker,
        seconds_per_time_step=60,
        time_step_ratio=60.0 / 3600.0,
    )
    dev.reset()
    dev.update_electricity_consumption(3.25)

    series_scalar = dev.electricity_consumption[0]
    fast_scalar = dev.electricity_consumption_at(0)
    assert fast_scalar == series_scalar
    assert type(fast_scalar) is type(series_scalar)

    batt = Battery(
        capacity=10.0,
        nominal_power=5.0,
        loss_coefficient=0.01,
        episode_tracker=tracker,
        seconds_per_time_step=3600,
    )
    loss_hourly = batt.loss_coefficient
    assert loss_hourly == pytest.approx(0.01)

    batt.seconds_per_time_step = 900
    loss_quarter = batt.loss_coefficient
    assert loss_quarter == pytest.approx(1.0 - (1.0 - 0.01) ** 0.25)


def test_entity_forecast_cache_and_subhourly_rollout_parity():
    env = CityLearnEnv(
        str(SCHEMA_3PHASE_15S),
        central_agent=True,
        interface="entity",
        episode_time_steps=12,
        random_seed=0,
    )
    try:
        obs, _ = env.reset()
        assert "building" in obs["tables"]

        # Mutating derived_forecasts in-place invalidates cached config and validates live values.
        env.schema["derived_forecasts"] = {"load_pv_method": "daily_persistence"}
        cfg = env._entity_service._derived_forecast_config()
        assert cfg["method"] == "daily_persistence"

        env.schema["derived_forecasts"] = {"load_pv_method": "invalid_mode"}
        with pytest.raises(ValueError, match="load_pv_method"):
            env._entity_service._derived_forecast_config()

        env.schema.pop("derived_forecasts", None)
        zero_action = {
            "tables": {
                name: np.zeros(space.shape, dtype="float32")
                for name, space in env.action_space["tables"].items()
            }
        }
        while not (env.terminated or env.truncated):
            obs, _, terminated, truncated, _ = env.step(zero_action)
            if terminated or truncated:
                break

        kpis = env.evaluate_v2(include_business_as_usual=True)
        assert not kpis.empty
        assert {"cost_function", "value", "name", "level"}.issubset(kpis.columns)
    finally:
        env.close()


def test_community_baseline_and_deferrable_dataframe_loader_parity():
    profiles_df = pd.DataFrame(
        [
            {
                "profile_id": "wash_std",
                "duration_steps": 2,
                "total_energy_kwh": 1.5,
                "load_profile": "[0.9, 0.6]",
            }
        ]
    )
    schedule_df = pd.DataFrame(
        [
            {
                "cycle_id": "c1",
                "profile_id": "wash_std",
                "earliest_start_time_step": 0,
                "latest_start_time_step": 2,
                "deadline_time_step": 4,
                "priority": 0.8,
                "must_run": True,
            }
        ]
    )
    sim = DeferrableApplianceSimulation.from_dataframes(
        cycle_profiles=profiles_df,
        flexibility_schedule=schedule_df,
        source_label="unit",
    )
    assert "wash_std" in sim.cycle_profiles
    assert len(sim.flexibility_schedule) == 1
    assert np.allclose(sim.flexibility_schedule[0]["load_profile"], [0.9, 0.6])

    env = CityLearnEnv(
        str(SCHEMA_2022),
        central_agent=True,
        buildings=[0, 1, 2],
        episode_time_steps=8,
        random_seed=0,
    )
    try:
        agent = RBCCommunityPolicy(env)
        obs, _ = env.reset()
        while not (env.terminated or env.truncated):
            actions = agent.predict(obs, deterministic=True)
            obs, _, terminated, truncated, _ = env.step(actions)
            if terminated or truncated:
                break
        kpis = env.evaluate_v2(include_business_as_usual=True)
        assert not kpis.empty
    finally:
        env.close()
