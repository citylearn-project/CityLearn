import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.multi_community import MultiCommunityEnv


MINUTE_SCHEMA = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"


def _community(community_id: str, schema=MINUTE_SCHEMA, weight=None, **env_kwargs):
    kwargs = {
        "central_agent": True,
        "episode_time_steps": 8,
        "render_mode": "none",
        "random_seed": 0,
    }
    kwargs.update(env_kwargs)
    entry = {
        "community_id": community_id,
        "schema": str(schema) if isinstance(schema, Path) else schema,
        "env_kwargs": kwargs,
    }
    if weight is not None:
        entry["weight"] = weight
    return entry


def _zero_actions(env: CityLearnEnv):
    if env.interface == "entity":
        return {
            "tables": {
                table_name: np.zeros(space.shape, dtype="float32")
                for table_name, space in env.action_space["tables"].items()
            }
        }

    return [np.zeros(space.shape, dtype="float32") for space in env.action_space]


def _multi_zero_actions(env: MultiCommunityEnv):
    return {
        community_id: _zero_actions(child)
        for community_id, child in env.envs.items()
    }


def _copy_dr_schema(tmp_path: Path, community_id: str, request_id: str, *, target_power_kw: float = 1.0):
    dataset_dir = tmp_path / community_id
    shutil.copytree(MINUTE_SCHEMA.parent, dataset_dir)
    schema = json.loads((dataset_dir / "schema.json").read_text(encoding="utf-8"))
    schema["root_directory"] = str(dataset_dir)
    schema["interface"] = "entity"
    schema["observation_bundles"] = {"entity_demand_response": {"active": True}}
    schema["demand_response"] = {
        "enabled": True,
        "requests_file": "demand_response_requests.csv",
        "baseline_method": "rolling_pre_event_average",
        "baseline_window_seconds": 3600,
        "allow_overlapping_requests": False,
    }
    pd.DataFrame(
        [
            {
                "request_id": request_id,
                "issuer": "dso",
                "direction": "down",
                "start_time_step": 4,
                "end_time_step": 4,
                "target_power_kw": target_power_kw,
                "activation_price_eur_per_kwh": 2.0,
                "shortfall_penalty_eur_per_kwh": 5.0,
                "tolerance_power_kw": 0.0,
            }
        ]
    ).to_csv(dataset_dir / "demand_response_requests.csv", index=False)
    return schema


def _kpi_value(kpis: pd.DataFrame, cost_function: str, *, community_id: str, level: str):
    rows = kpis[
        (kpis["cost_function"] == cost_function)
        & (kpis["community_id"] == community_id)
        & (kpis["level"] == level)
    ]
    assert len(rows) == 1, cost_function
    return rows["value"].iloc[0]


def test_constructor_accepts_named_communities_and_exposes_spaces():
    env = MultiCommunityEnv(
        communities=[
            _community("community_a"),
            _community("community_b"),
        ]
    )

    try:
        assert env.community_ids == ["community_a", "community_b"]
        assert set(env.action_space) == {"community_a", "community_b"}
        assert set(env.observation_space) == {"community_a", "community_b"}
        assert set(env.entity_specs) == {"community_a", "community_b"}
        assert env.interface == "flat"
        assert env.central_agent is True
    finally:
        env.close()


@pytest.mark.parametrize(
    "communities,match",
    [
        ([{"community_id": "", "schema": str(MINUTE_SCHEMA)}], "non-empty"),
        ([{"community_id": "../bad", "schema": str(MINUTE_SCHEMA)}], "safe for a relative path"),
        ([_community("same"), _community("same")], "Duplicate"),
        ([_community("a", weight=-1.0)], "weight"),
        ([_community("a", weight=float("nan"))], "weight"),
        ([_community("a", weight=0.0), _community("b", weight=0.0)], "greater than zero"),
    ],
)
def test_constructor_rejects_invalid_community_config(communities, match):
    with pytest.raises((TypeError, ValueError), match=match):
        MultiCommunityEnv(communities=communities)


def test_constructor_rejects_mismatched_time_resolution_or_episode_length():
    with pytest.raises(ValueError, match="seconds_per_time_step"):
        MultiCommunityEnv(
            communities=[
                _community("community_a", seconds_per_time_step=900),
                _community("community_b", seconds_per_time_step=300),
            ]
        )

    with pytest.raises(ValueError, match="episode length"):
        MultiCommunityEnv(
            communities=[
                _community("community_a", episode_time_steps=8),
                _community("community_b", episode_time_steps=7),
            ]
        )


def test_constructor_rejects_mixed_interface_or_central_agent():
    with pytest.raises(ValueError, match="same interface"):
        MultiCommunityEnv(
            communities=[
                _community("community_a", interface="flat"),
                _community("community_b", interface="entity"),
            ]
        )

    with pytest.raises(ValueError, match="central_agent"):
        MultiCommunityEnv(
            communities=[
                _community("community_a", central_agent=True),
                _community("community_b", central_agent=False),
            ]
        )


def test_reset_and_step_return_community_payloads_and_weighted_rewards():
    env = MultiCommunityEnv(
        communities=[
            {**_community("community_a"), "weight": 1.0},
            {**_community("community_b"), "weight": 2.0},
        ]
    )

    try:
        observations, info = env.reset(seed=0)
        assert set(observations) == {"community_a", "community_b"}
        assert info["time_step"] == 0
        assert set(info["communities"]) == {"community_a", "community_b"}

        next_observations, rewards, terminated, truncated, info = env.step(_multi_zero_actions(env))
        assert set(next_observations) == {"community_a", "community_b"}
        assert set(rewards) == {"community_a", "community_b"}
        assert not terminated
        assert not truncated

        scalar_a = info["community_rewards_scalar"]["community_a"]
        scalar_b = info["community_rewards_scalar"]["community_b"]
        expected_total = scalar_a + 2.0 * scalar_b
        assert info["reward_total"] == pytest.approx(expected_total)
        assert info["reward_mean_weighted"] == pytest.approx(expected_total / 3.0)
        assert info["terminated_by_community"] == {"community_a": False, "community_b": False}
        assert info["truncated_by_community"] == {"community_a": False, "community_b": False}
    finally:
        env.close()


def test_step_terminates_wrapper_when_any_child_terminates():
    env = MultiCommunityEnv(
        communities=[
            _community("community_a", episode_time_steps=2),
            _community("community_b", episode_time_steps=2),
        ]
    )

    try:
        env.reset(seed=0)
        _, _, terminated, truncated, info = env.step(_multi_zero_actions(env))
        assert terminated
        assert not truncated
        assert info["terminated_by_community"] == {"community_a": True, "community_b": True}

        with pytest.raises(RuntimeError, match="reset"):
            env.step(_multi_zero_actions(env))
    finally:
        env.close()


def test_entity_interface_reset_and_demand_response_are_independent_by_community(tmp_path: Path):
    schema_a = _copy_dr_schema(tmp_path, "community_a_dataset", "dr_a", target_power_kw=1.0)
    schema_b = _copy_dr_schema(tmp_path, "community_b_dataset", "dr_b", target_power_kw=2.0)
    env = MultiCommunityEnv(
        communities=[
            _community("community_a", schema=schema_a, interface="entity"),
            _community("community_b", schema=schema_b, interface="entity"),
        ]
    )

    try:
        observations, _ = env.reset(seed=0)
        assert set(observations) == {"community_a", "community_b"}

        while int(env.time_step) < 4:
            observations, *_ = env.step(_multi_zero_actions(env))

        assert observations["community_a"]["meta"]["demand_response"]["active_request_id"] == "dr_a"
        assert observations["community_b"]["meta"]["demand_response"]["active_request_id"] == "dr_b"

        observations, rewards, terminated, truncated, info = env.step(_multi_zero_actions(env))
        assert not terminated
        assert not truncated
        kpis = env.evaluate_v2(include_business_as_usual=False)

        assert "community_id" in kpis.columns
        assert "community_a" in set(kpis["community_id"])
        assert "community_b" in set(kpis["community_id"])
        assert MultiCommunityEnv.PORTFOLIO_COMMUNITY_ID in set(kpis["community_id"])

        for suffix in (
            "requested_total_kwh",
            "delivered_total_kwh",
            "shortfall_total_kwh",
            "revenue_total_eur",
            "penalty_total_eur",
            "net_revenue_total_eur",
        ):
            local_total = (
                _kpi_value(kpis, f"district_demand_response_{suffix}", community_id="community_a", level="district")
                + _kpi_value(kpis, f"district_demand_response_{suffix}", community_id="community_b", level="district")
            )
            portfolio_total = _kpi_value(
                kpis,
                f"portfolio_demand_response_{suffix}",
                community_id=MultiCommunityEnv.PORTFOLIO_COMMUNITY_ID,
                level="portfolio",
            )
            assert portfolio_total == pytest.approx(local_total)
    finally:
        env.close()


def test_evaluate_v2_includes_portfolio_sum_and_weighted_ratio_rows():
    env = MultiCommunityEnv(
        communities=[
            {**_community("community_a"), "weight": 1.0},
            {**_community("community_b"), "weight": 3.0},
        ]
    )

    try:
        env.reset(seed=0)
        env.step(_multi_zero_actions(env))
        kpis = env.evaluate_v2(include_business_as_usual=False)

        assert "community_id" in kpis.columns
        assert set(["community_a", "community_b", MultiCommunityEnv.PORTFOLIO_COMMUNITY_ID]).issubset(
            set(kpis["community_id"])
        )

        import_a = _kpi_value(kpis, "district_energy_grid_total_import_control_kwh", community_id="community_a", level="district")
        import_b = _kpi_value(kpis, "district_energy_grid_total_import_control_kwh", community_id="community_b", level="district")
        portfolio_import = _kpi_value(
            kpis,
            "portfolio_energy_grid_total_import_control_kwh",
            community_id=MultiCommunityEnv.PORTFOLIO_COMMUNITY_ID,
            level="portfolio",
        )
        assert portfolio_import == pytest.approx(import_a + import_b)

        ratio_rows = kpis[
            (kpis["level"] == "portfolio")
            & (kpis["community_id"] == MultiCommunityEnv.PORTFOLIO_COMMUNITY_ID)
            & (kpis["cost_function"].str.endswith("_ratio"))
        ]
        assert len(ratio_rows) > 0
    finally:
        env.close()


@pytest.mark.parametrize("weight_b", [3.0, 0.0])
def test_portfolio_ratios_to_a_reference_are_ratios_of_summed_totals(weight_b):
    env = MultiCommunityEnv(
        communities=[
            {**_community("community_a"), "weight": 1.0},
            {**_community("community_b"), "weight": weight_b},
        ]
    )

    def full_charge(child: CityLearnEnv):
        return [np.ones(space.shape, dtype="float32") for space in child.action_space]

    try:
        env.reset(seed=0)
        while not env.terminated:
            env.step({"community_a": _zero_actions(env.envs["community_a"]), "community_b": full_charge(env.envs["community_b"])})

        kpis = env.evaluate_v2(include_business_as_usual=False)
        portfolio = MultiCommunityEnv.PORTFOLIO_COMMUNITY_ID
        pooled_differs_from_mean = False

        for family, control, reference, ratio in [
            ("cost", "total_control_eur", "total_baseline_eur", "ratio_to_baseline_total_ratio"),
            ("emissions", "total_control_kgco2", "total_baseline_kgco2", "ratio_to_baseline_total_ratio"),
            ("energy_grid", "total_import_control_kwh", "total_import_baseline_kwh", "ratio_to_baseline_import_total_ratio"),
            ("energy_grid", "total_net_exchange_control_kwh", "total_net_exchange_baseline_kwh", "ratio_to_baseline_net_exchange_total_ratio"),
        ]:
            totals = [
                _kpi_value(kpis, f"portfolio_{family}_{name}", community_id=portfolio, level="portfolio")
                for name in (control, reference)
            ]
            assert totals[1] > 0.0
            pooled = _kpi_value(kpis, f"portfolio_{family}_{ratio}", community_id=portfolio, level="portfolio")
            assert pooled == pytest.approx(totals[0] / totals[1])

            local = [
                _kpi_value(kpis, f"district_{family}_{ratio}", community_id=community_id, level="district")
                for community_id in ("community_a", "community_b")
            ]
            mean = (local[0] + weight_b * local[1]) / (1.0 + weight_b)
            pooled_differs_from_mean |= abs(pooled - mean) > 1.0e-6

        assert pooled_differs_from_mean

        # Grid-shape ratios have no additive totals and remain weighted means.
        shape = "energy_grid_shape_quality_peak_daily_average_to_baseline_ratio"
        local = [
            _kpi_value(kpis, f"district_{shape}", community_id=community_id, level="district")
            for community_id in ("community_a", "community_b")
        ]
        assert _kpi_value(kpis, f"portfolio_{shape}", community_id=portfolio, level="portfolio") == pytest.approx(
            (local[0] + weight_b * local[1]) / (1.0 + weight_b)
        )
    finally:
        env.close()


def test_export_final_kpis_writes_child_subfolders_and_global_csv(tmp_path: Path):
    env = MultiCommunityEnv(
        communities=[
            _community("community_a", episode_time_steps=2),
            _community("community_b", episode_time_steps=2),
        ],
        render_directory=tmp_path / "renders",
        render_session_name="mc_export",
    )

    try:
        env.reset(seed=0)
        env.step(_multi_zero_actions(env))
        env.export_final_kpis(
            include_business_as_usual=False,
            export_business_as_usual_timeseries=False,
        )

        root = tmp_path / "renders" / "mc_export"
        assert (root / "exported_kpis_multi_community.csv").is_file()
        assert (root / "community_a" / "exported_kpis.csv").is_file()
        assert (root / "community_b" / "exported_kpis.csv").is_file()
    finally:
        env.close()


def test_citylearn_env_single_community_regression_still_resets_and_steps():
    env = CityLearnEnv(str(MINUTE_SCHEMA), central_agent=True, episode_time_steps=2, render_mode="none", random_seed=0)

    try:
        observations, _ = env.reset(seed=0)
        assert isinstance(observations, list)
        _, _, terminated, truncated, _ = env.step(_zero_actions(env))
        assert terminated
        assert not truncated
    finally:
        env.close()
