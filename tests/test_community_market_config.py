"""Invalid `community_market` settings fail at construction instead of being ignored (#366)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.market_config import parse_community_market
from test_market_phase_invariants import _rollout_zero_actions, _write_residual_market_schema

ROOT = Path(__file__).resolve().parents[1]
BUILDINGS = ["Building_A", "Building_B"]


def _schema(tmp_path, **market):
    path = _write_residual_market_schema(tmp_path)
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["root_directory"] = str(path.parent)
    schema["community_market"] = {"enabled": True, "local_price_ratio_to_grid_import": 0.8, **market}
    return schema


@pytest.mark.parametrize(
    "market, message",
    [
        ({"enable": True}, r"unknown key\(s\): 'enable' \(did you mean 'enabled'\?\)"),
        ({"local_price_ratio_to_grid_import": "0,7"}, "must be a number"),
        ({"local_price_ratio_to_grid_import": "0.7"}, "must be a number"),
        ({"local_price_ratio_to_grid_import": None}, "must be a number"),
        ({"local_price_ratio_to_grid_import": True}, "must be a number"),
        ({"local_price_ratio_to_grid_import": float("nan")}, "must be finite"),
        ({"local_price_ratio_to_grid_import": 1.5}, "between 0 and 1"),
        ({"local_price_ratio_to_grid_import": -0.1}, "between 0 and 1"),
        ({"intra_community_sell_ratio": 0.5}, "disagree"),
        ({"grid_export_price": 0.05}, "settlement_version\": 2"),
        ({"grid_export_price": 0.05, "settlement_version": 1}, "settlement_version\": 2"),
        ({"grid_export_price": 0.05, "settlement_version": "2"}, "integer 1 or 2"),
        ({"settlement_version": 2.0}, "integer 1 or 2"),
        ({"settlement_version": 3}, "integer 1 or 2"),
        ({"settlement_version": True}, "integer 1 or 2"),
        ({"grid_export_price": "0.05", "settlement_version": 2}, "grid_export_price must be a number"),
        ({"grid_export_price": float("inf"), "settlement_version": 2}, "grid_export_price must be finite"),
        ({"import_member_weights": {"Building_Z": 1.0}}, "not in the schema: 'Building_Z'"),
        ({"import_member_weights": {"Building_A": "heavy"}}, "import_member_weights.Building_A must be a number"),
        ({"import_member_weights": {"Building_A": -1.0}}, "must not be negative"),
        ({"import_member_weights": [1.0, 2.0]}, "import_member_weights must be a mapping"),
        ({"tariff_files": {"Building_Z": "tariff.csv"}}, "tariff_files names building"),
        ({"kpis": {"community_local_trade_enabled": False}}, r"did you mean 'community_local_traded_enabled'"),
        ({"matching_granularity": "per_device"}, "matching_granularity"),
    ],
)
def test_invalid_market_settings_fail_at_construction(tmp_path, market, message):
    schema = _schema(tmp_path, **market)
    with pytest.raises(ValueError, match=message):
        CityLearnEnv(schema, central_agent=True, random_seed=0)


def test_market_section_must_be_a_mapping(tmp_path):
    schema = _schema(tmp_path)
    schema["community_market"] = True
    with pytest.raises(ValueError, match="community_market must be a mapping"):
        CityLearnEnv(schema, central_agent=True, random_seed=0)


@pytest.mark.parametrize(
    "market, ratio, export_price, weights",
    [
        ({}, 0.8, 0.0, {}),
        ({"local_price_ratio_to_grid_import": 1, "intra_community_sell_ratio": 1.0}, 1.0, 0.0, {}),
        ({"local_price_ratio_to_grid_import": 0}, 0.0, 0.0, {}),
        ({"grid_export_price": 0.0, "settlement_version": 1}, 0.8, 0.0, {}),
        ({"grid_export_price": 0.05, "settlement_version": 2}, 0.8, 0.05, {}),
        ({"import_member_weights": {"Building_A": 2, "Building_B": 0.0}}, 0.8, 0.0, {"Building_A": 2.0, "Building_B": 0.0}),
        ({"import_member_weights": None, "kpis": None, "tariff_files": None}, 0.8, 0.0, {}),
    ],
)
def test_valid_market_settings_resolve(market, ratio, export_price, weights):
    parsed = parse_community_market({"enabled": True, **market}, BUILDINGS)
    assert parsed["local_price_ratio_to_grid_import"] == ratio
    assert parsed["grid_export_price"] == export_price
    assert parsed["import_member_weights"] == weights


def test_disabled_market_is_still_validated(tmp_path):
    schema = _schema(tmp_path, enabled=False, local_price_ratio_to_grid_import=1.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        CityLearnEnv(schema, central_agent=True, random_seed=0)


def test_every_bundled_market_configuration_is_valid():
    found = 0
    for path in sorted((ROOT / "data" / "datasets").glob("**/*.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(schema, dict) or "community_market" not in schema:
            continue
        buildings = schema.get("buildings")
        parsed = parse_community_market(schema["community_market"], list(buildings) if buildings else None)
        # Same values as before validation, so bundled results do not change.
        assert (parsed["local_price_ratio_to_grid_import"], parsed["grid_export_price"]) == (0.8, 0.0), path
        found += 1
    assert found >= 10


@pytest.mark.parametrize(
    "mutate",
    [
        lambda env: setattr(env, "community_market_sell_ratio", 0.5),
        lambda env: setattr(env, "community_market_grid_export_price", 0.05),
        lambda env: setattr(env, "community_market_import_member_weights", {"Building_A": 3.0}),
        lambda env: setattr(env, "community_market_local_enabled", False),
    ],
)
@pytest.mark.parametrize("before_reset", [True, False])
def test_bau_reference_rejects_market_attributes_changed_after_construction(tmp_path, mutate, before_reset):
    env = CityLearnEnv(_schema(tmp_path), central_agent=True, random_seed=0)
    try:
        if before_reset:
            mutate(env)
            _rollout_zero_actions(env)
        else:
            _rollout_zero_actions(env)
            mutate(env)
        with pytest.raises(ValueError, match="community market settings differ"):
            env.evaluate_v2(include_business_as_usual=True)
        env.evaluate_v2(include_business_as_usual=False)
    finally:
        env.close()


def test_bau_reference_follows_market_changed_through_the_schema(tmp_path):
    env = CityLearnEnv(_schema(tmp_path), central_agent=True, random_seed=0)
    try:
        env.schema["community_market"]["local_price_ratio_to_grid_import"] = 0.5
        env._configure_community_market()
        _rollout_zero_actions(env)
        env.evaluate_v2(include_business_as_usual=True)
    finally:
        env.close()
