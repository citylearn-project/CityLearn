from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd
import pytest
from private_access import demand_response_service

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


MINUTE_SCHEMA_PATH = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"
PACKAGED_2022_DR_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "data/datasets/citylearn_challenge_2022_phase_all_demand_response/schema.json"
)


def _copy_minute_schema(tmp_path: Path, *, request_format: str = "csv", interface: str = "entity") -> Mapping:
    dataset_dir = tmp_path / f"minute_dr_{request_format}_{interface}"
    shutil.copytree(MINUTE_SCHEMA_PATH.parent, dataset_dir)
    schema = json.loads((dataset_dir / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["interface"] = interface
    schema["observation_bundles"] = {
        "entity_demand_response": {"active": True},
    }
    request_file = f"demand_response_requests.{request_format}"
    schema["demand_response"] = {
        "enabled": True,
        "requests_file": request_file,
        "baseline_method": "rolling_pre_event_average",
        "baseline_window_seconds": 3600,
        "allow_overlapping_requests": False,
    }
    schema["_dataset_dir"] = str(dataset_dir)
    schema["_request_file"] = request_file
    return schema


def _write_requests(schema: Mapping, rows, *, request_format: str = "csv"):
    dataset_dir = Path(schema["_dataset_dir"])
    request_file = dataset_dir / schema["_request_file"]
    frame = pd.DataFrame(rows)
    if request_format == "parquet":
        pytest.importorskip("pyarrow")
        frame.to_parquet(request_file, index=False)
    else:
        frame.to_csv(request_file, index=False)


def _clean_schema(schema: Mapping) -> dict:
    cleaned = dict(schema)
    cleaned.pop("_dataset_dir", None)
    cleaned.pop("_request_file", None)
    return cleaned


def _zero_entity_actions(env: CityLearnEnv):
    return {
        "tables": {
            name: np.zeros(space.shape, dtype="float32")
            for name, space in env.action_space["tables"].items()
        }
    }


def _advance_to(env: CityLearnEnv, target_time_step: int):
    obs, _ = env.reset(seed=0)
    while int(env.time_step) < target_time_step:
        obs, *_ = env.step(_zero_entity_actions(env))
    return obs


def _request(direction: str = "down", *, request_id: str = "dr_1", start: int = 4, end: int = 4):
    return {
        "request_id": request_id,
        "issuer": "dso",
        "direction": direction,
        "start_time_step": start,
        "end_time_step": end,
        "target_power_kw": 1.0,
        "activation_price_eur_per_kwh": 2.0,
        "shortfall_penalty_eur_per_kwh": 5.0,
        "tolerance_power_kw": 0.0,
    }


def test_demand_response_csv_request_appears_in_entity_observations(tmp_path: Path):
    schema = _copy_minute_schema(tmp_path)
    _write_requests(schema, [_request("down")])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        obs = _advance_to(env, 4)
        features = env.entity_specs["tables"]["district"]["features"]
        row = obs["tables"]["district"][0]

        assert "dr_active" in features
        assert row[features.index("dr_active")] == pytest.approx(1.0)
        assert row[features.index("dr_issuer_code")] == pytest.approx(1.0)
        assert row[features.index("dr_direction")] == pytest.approx(-1.0)
        assert row[features.index("dr_target_power_kw")] == pytest.approx(1.0)
        assert row[features.index("dr_baseline_power_kw")] > 0.0
        assert obs["meta"]["demand_response"]["active_request_id"] == "dr_1"
        assert obs["meta"]["demand_response"]["baseline_valid"] is True
    finally:
        env.close()


def test_demand_response_parquet_request_file_is_supported(tmp_path: Path):
    schema = _copy_minute_schema(tmp_path, request_format="parquet")
    _write_requests(schema, [_request("down")], request_format="parquet")
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        obs = _advance_to(env, 4)
        features = env.entity_specs["tables"]["district"]["features"]
        assert obs["tables"]["district"][0, features.index("dr_active")] == pytest.approx(1.0)
    finally:
        env.close()


def test_demand_response_requires_entity_interface(tmp_path: Path):
    schema = _copy_minute_schema(tmp_path, interface="flat")
    _write_requests(schema, [_request("down")])
    with pytest.raises(ValueError, match="requires interface='entity'"):
        CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)


def test_demand_response_rejects_overlapping_requests(tmp_path: Path):
    schema = _copy_minute_schema(tmp_path)
    _write_requests(
        schema,
        [
            _request("down", request_id="dr_1", start=3, end=5),
            _request("up", request_id="dr_2", start=5, end=6),
        ],
    )
    with pytest.raises(ValueError, match="Overlapping demand_response requests"):
        CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)


@pytest.mark.parametrize("direction,sign", [("down", -1.0), ("up", 1.0)])
def test_demand_response_settlement_uses_load_perspective_direction(tmp_path: Path, direction: str, sign: float):
    schema = _copy_minute_schema(tmp_path)
    _write_requests(schema, [_request(direction)])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        _advance_to(env, 4)
        step_hours = env.seconds_per_time_step / 3600.0
        expected_baseline_kw = float(np.mean(env.net_electricity_consumption[0:4])) / step_hours

        env.step(_zero_entity_actions(env))
        row = demand_response_service(env).settlement_history[-1]
        actual_kw = env.net_electricity_consumption[4] / step_hours
        expected_delivered_kw = (
            actual_kw - expected_baseline_kw
            if direction == "up"
            else expected_baseline_kw - actual_kw
        )

        assert row["baseline_power_kw"] == pytest.approx(expected_baseline_kw)
        assert row["actual_power_kw"] == pytest.approx(actual_kw)
        assert row["delivered_power_kw"] == pytest.approx(expected_delivered_kw)
        assert row["direction"] == direction
        assert sign * row["delivered_power_kw"] == pytest.approx(sign * expected_delivered_kw)
    finally:
        env.close()


def test_demand_response_kpis_and_building_allocation_for_single_building(tmp_path: Path):
    schema = _copy_minute_schema(tmp_path)
    _write_requests(schema, [_request("down")])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        _advance_to(env, 4)
        env.step(_zero_entity_actions(env))
        row = demand_response_service(env).settlement_history[-1]
        kpis = env.evaluate_v2(include_business_as_usual=False)

        def value(name: str, level: str = "district", entity_name: str = "District"):
            subset = kpis[
                (kpis["cost_function"] == name)
                & (kpis["level"] == level)
                & (kpis["name"] == entity_name)
            ]
            assert len(subset) == 1, name
            return subset["value"].iloc[0]

        assert value("district_demand_response_events_count") == pytest.approx(1.0)
        assert value("district_demand_response_active_time_step_count") == pytest.approx(1.0)
        assert value("district_demand_response_requested_total_kwh") == pytest.approx(row["requested_kwh"])
        assert value("district_demand_response_delivered_total_kwh") == pytest.approx(row["delivered_kwh"])
        assert value("district_demand_response_shortfall_total_kwh") == pytest.approx(row["shortfall_kwh"])
        assert value("district_demand_response_revenue_total_eur") == pytest.approx(row["revenue_eur"])
        assert value("district_demand_response_penalty_total_eur") == pytest.approx(row["penalty_eur"])
        assert value("district_demand_response_net_revenue_total_eur") == pytest.approx(row["net_revenue_eur"])
        assert value("district_demand_response_invalid_baseline_time_step_count") == pytest.approx(0.0)

        building_row = row["building_allocations"][0]
        assert value("building_demand_response_revenue_total_eur", "building", "Building_1") == pytest.approx(building_row["revenue_eur"])
        assert value("building_demand_response_penalty_total_eur", "building", "Building_1") == pytest.approx(building_row["penalty_eur"])
    finally:
        env.close()


def test_demand_response_invalid_baseline_is_counted_without_settlement_economics(tmp_path: Path):
    schema = _copy_minute_schema(tmp_path)
    _write_requests(schema, [_request("down", start=0, end=0)])
    env = CityLearnEnv(_clean_schema(schema), central_agent=True, episode_time_steps=8, random_seed=0)

    try:
        env.reset(seed=0)
        env.step(_zero_entity_actions(env))
        row = demand_response_service(env).settlement_history[-1]

        assert row["baseline_valid"] is False
        assert row["revenue_eur"] == pytest.approx(0.0)
        assert row["penalty_eur"] == pytest.approx(0.0)

        kpis = env.evaluate_v2(include_business_as_usual=False)
        subset = kpis[kpis["cost_function"] == "district_demand_response_invalid_baseline_time_step_count"]
        assert subset["value"].iloc[0] == pytest.approx(1.0)
    finally:
        env.close()


def test_packaged_2022_no_ev_demand_response_dataset_loads():
    env = CityLearnEnv(str(PACKAGED_2022_DR_SCHEMA_PATH), episode_time_steps=48, render_mode="none")

    try:
        obs, _ = env.reset(seed=0)
        assert len(env.electric_vehicles) == 0
        assert env.topology_mode == "static"
        assert env.entity_specs["observation_bundles"]["entity_demand_response"]["active"] is True

        while int(env.time_step) < 24:
            obs, *_ = env.step(_zero_entity_actions(env))

        features = env.entity_specs["tables"]["district"]["features"]
        assert "dr_active" in features
        assert obs["tables"]["district"][0, features.index("dr_active")] == pytest.approx(1.0)
        assert obs["meta"]["demand_response"]["active_request_id"] == "dr_day_002_evening_down"
    finally:
        env.close()
