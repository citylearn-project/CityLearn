import copy
import json
import shutil
from pathlib import Path
from typing import Mapping, Optional
import warnings

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


@pytest.mark.parametrize("key", ["wieght", "env_kwarg", "Schema"])
def test_constructor_rejects_unknown_community_keys(key):
    entry = _community("a")
    entry[key] = 3.0

    with pytest.raises(ValueError) as excinfo:
        MultiCommunityEnv(communities=[entry, _community("b")])

    message = str(excinfo.value)
    assert "communities[0]" in message
    assert repr(key) in message
    for accepted in ("community_id", "schema", "env_kwargs", "weight"):
        assert accepted in message


@pytest.mark.parametrize("weight", [True, False, np.bool_(True)])
def test_constructor_rejects_boolean_weight(weight):
    with pytest.raises(ValueError, match="boolean"):
        MultiCommunityEnv(communities=[_community("a", weight=weight), _community("b")])


@pytest.mark.parametrize("weight", ["2", "1.5", b"2", [1.0], {"w": 1.0}])
def test_constructor_rejects_non_numeric_weight(weight):
    # float() would turn '2' into 2.0; the weight must be a number, as for booleans.
    with pytest.raises(ValueError, match="weight must be a non-negative finite number"):
        MultiCommunityEnv(communities=[_community("a", weight=weight), _community("b")])


@pytest.mark.parametrize(
    "setting, value_a, value_b",
    [
        ("business_as_usual_ev_charge_target", "full", "requested"),
        ("ev_soc_carryover", False, True),
    ],
)
def test_constructor_rejects_communities_with_different_bau_or_ev_settings(setting, value_a, value_b):
    # Portfolio BAU totals and ratios to the BAU add the district BAU runs, which these settings define.
    with pytest.raises(ValueError, match=f"share {setting}") as excinfo:
        MultiCommunityEnv(
            communities=[
                _community("community_a", **{setting: value_a}),
                _community("community_b", **{setting: value_b}),
            ]
        )
    message = str(excinfo.value)
    assert "community_a" in message and "community_b" in message
    assert repr(value_a) in message and repr(value_b) in message

    env = MultiCommunityEnv(
        communities=[
            _community("community_a", **{setting: value_b}),
            _community("community_b", **{setting: value_b}),
        ]
    )
    try:
        assert {getattr(child, setting) for child in env.envs.values()} == {value_b}
    finally:
        env.close()


def test_reset_rejects_ev_soc_carryover_changed_on_one_community():
    env = MultiCommunityEnv(communities=[_community("community_a"), _community("community_b")])
    try:
        env.envs["community_b"].ev_soc_carryover = True
        with pytest.raises(ValueError, match="share ev_soc_carryover"):
            env.reset(seed=0)
    finally:
        env.close()


def test_constructor_keeps_valid_entries_with_every_accepted_key():
    env = MultiCommunityEnv(
        communities=[
            _community("a", weight=3),
            _community("b", weight=np.float64(0.5)),
            {"community_id": "c", "schema": str(MINUTE_SCHEMA), "env_kwargs": _community("c")["env_kwargs"]},
        ]
    )

    try:
        assert env.weights == {"a": 3.0, "b": 0.5, "c": 1.0}
    finally:
        env.close()


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
        # The episode ends at its time limit, so step() reports truncation (Gymnasium semantics).
        assert not terminated
        assert truncated
        assert env.done and env.terminated
        assert info["terminated_by_community"] == {"community_a": False, "community_b": False}

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


@pytest.mark.parametrize("capacities", [(5.0, 15.0, 0.0), (0.0, 0.0, 0.0)])
def test_portfolio_battery_cycles_use_total_nominal_capacity(capacities):
    communities = []
    for capacity, community_id, weight in zip(capacities, ("a", "b", "c"), (1.0, 0.0, 5.0)):
        schema = json.loads(MINUTE_SCHEMA.read_text(encoding="utf-8"))
        schema["root_directory"] = str(MINUTE_SCHEMA.parent)
        building = schema["buildings"]["Building_1"]
        building["electrical_storage"]["attributes"]["capacity"] = capacity
        if capacity == 0:
            building["inactive_actions"].append("electrical_storage")
        communities.append(_community(community_id, schema=schema, weight=weight))

    env = MultiCommunityEnv(communities=communities)
    try:
        env.reset(seed=0)
        while not env.terminated:
            actions = _multi_zero_actions(env)
            # The idle battery still contributes its nominal capacity.
            action_names = env.envs["a"].action_names[0]
            if "electrical_storage" in action_names:
                actions["a"][0][action_names.index("electrical_storage")] = -0.2
            env.step(actions)
        kpis = env.evaluate_v2()
    finally:
        env.close()

    def portfolio(metric):
        return _kpi_value(kpis, f"portfolio_{metric}", community_id=env.PORTFOLIO_COMMUNITY_ID, level="portfolio")

    cycle_stem = "battery_health_equivalent_full_cycles"
    control = portfolio(f"{cycle_stem}_count")
    bau = portfolio(f"{cycle_stem}_business_as_usual_count")
    delta = portfolio(f"{cycle_stem}_delta_to_business_as_usual_count")
    ratio = portfolio("battery_ratio_to_business_as_usual_equivalent_full_cycles_ratio")
    if sum(capacities) == 0:
        assert all(pd.isna(value) for value in (control, bau, delta, ratio))
        return

    control_throughput = portfolio("battery_total_throughput_kwh")
    bau_throughput = portfolio("battery_total_throughput_business_as_usual_kwh")
    assert control_throughput > 0 and bau_throughput > 0
    assert control == pytest.approx(control_throughput / (2 * sum(capacities)))
    assert bau == pytest.approx(bau_throughput / (2 * sum(capacities)))
    assert delta == pytest.approx(control - bau)
    assert ratio == pytest.approx(control / bau)


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
        long = pd.read_csv(root / "exported_kpis_multi_community.csv")
        assert list(long.columns) == [
            "cost_function", "value", "name", "level", "unit", "description", "status", "replacement", "community_id",
        ]
        child_dir = root / "community_a"
        wide = pd.read_csv(child_dir / "exported_kpis.csv")
        assert set(wide.columns) == {"KPI", "Building_1", "District"}
        manifest = json.loads((child_dir / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
        definitions = manifest["kpi_definitions"]
        assert set(definitions) == set(wide["KPI"])
        for name, metadata in definitions.items():
            rows = long[(long["community_id"] == "community_a") & (long["cost_function"] == name)]
            rows = rows[["unit", "description", "status", "replacement"]].astype(object)
            rows = rows.where(rows.notna(), None)
            assert rows.to_dict("records") == [metadata] * len(rows)
        assert (root / "community_b" / "exported_kpis.csv").is_file()
    finally:
        env.close()


def test_export_final_kpis_csv_writes_missing_kpis_as_empty_cells_without_warnings(tmp_path: Path):
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
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            env.export_final_kpis(include_business_as_usual=False, export_business_as_usual_timeseries=False)

        # pandas 3 warns that fillna("") fills float columns with a string.
        export_warnings = [
            str(w.message) for w in caught if Path(w.filename).name in {"multi_community.py", "exporter.py"}
        ]
        assert export_warnings == []
        frame = pd.read_csv(
            tmp_path / "renders" / "mc_export" / "exported_kpis_multi_community.csv",
            dtype=str,
            keep_default_na=False,
        )
        assert not {"nan", "NaN", "<NA>"} & set(frame.to_numpy().ravel())
    finally:
        env.close()


def test_citylearn_env_single_community_regression_still_resets_and_steps():
    env = CityLearnEnv(str(MINUTE_SCHEMA), central_agent=True, episode_time_steps=2, render_mode="none", random_seed=0)

    try:
        observations, _ = env.reset(seed=0)
        assert isinstance(observations, list)
        _, _, terminated, truncated, _ = env.step(_zero_actions(env))
        assert not terminated
        assert truncated
    finally:
        env.close()


PT_REC_4_SCHEMA = Path(__file__).resolve().parents[1] / "data/datasets/pt_rec_4/schema.json"
# Summer midday at 900 s steps: one pt_rec_4 member exports while others import.
PT_REC_4_WINDOW = [17324, 17335]
MARKET_ENERGY = "energy_grid_community_market_"
MARKET_COST = "cost_community_market_"
MARKET_SHARE = "solar_self_consumption_community_market_"


def _pt_rec_4_portfolio(markets: Mapping[str, Optional[dict]]) -> MultiCommunityEnv:
    """pt_rec_4 communities over a sunny midday window; ``None`` disables the market."""

    base = json.loads(PT_REC_4_SCHEMA.read_text(encoding="utf-8"))
    base["root_directory"] = str(PT_REC_4_SCHEMA.parent)
    communities = []
    for community_id, market in markets.items():
        schema = copy.deepcopy(base)
        if market is None:
            schema["community_market"]["enabled"] = False
        else:
            schema["community_market"].update(market)
        communities.append(_community(
            community_id, schema=schema, interface="flat", episode_time_steps=[PT_REC_4_WINDOW],
        ))

    return MultiCommunityEnv(communities=communities)


def _run_zero_actions(env: MultiCommunityEnv) -> pd.DataFrame:
    env.reset(seed=0)
    while not env.terminated:
        env.step(_multi_zero_actions(env))

    return env.evaluate_v2(include_business_as_usual=False)


def test_mixed_portfolio_market_rows_include_communities_without_a_market():
    """#373: a community without a market adds its plain grid settlement to the portfolio market rows."""

    env = _pt_rec_4_portfolio({
        "market": {},
        # Settlement version 1 pays nothing for exports, so the export price is 0 (#366).
        "market_export_tariff": {"local_price_ratio_to_grid_import": 1.0, "grid_export_price": 0.0},
        "no_market": None,
    })

    try:
        kpis = _run_zero_actions(env)
        portfolio_id = MultiCommunityEnv.PORTFOLIO_COMMUNITY_ID

        def portfolio(name):
            return _kpi_value(kpis, f"portfolio_{name}", community_id=portfolio_id, level="portfolio")

        def district(community_id, name):
            return _kpi_value(kpis, f"district_{name}", community_id=community_id, level="district")

        # By hand from the members' series of the community without a market: it pays the grid for its
        # imports and gets nothing for its exports.
        child = env.envs["no_market"]
        steps = child.time_step
        grid_import = grid_export = cost = 0.0
        for building in child.buildings:
            net = np.asarray(building.net_electricity_consumption[:steps], dtype="float64")
            price = np.asarray(building.pricing.electricity_pricing[:steps], dtype="float64")
            grid_import += float(np.clip(net, 0.0, None).sum())
            grid_export += float(np.clip(-net, 0.0, None).sum())
            cost += float((np.clip(net, 0.0, None)*price).sum())
        days = steps*child.seconds_per_time_step/86400.0
        assert grid_export > 0.0
        assert cost == pytest.approx(district("no_market", "cost_total_control_eur"))

        markets = ("market", "market_export_tariff")

        def market_sum(name):
            return sum(district(community_id, name) for community_id in markets)

        local_import = market_sum(f"{MARKET_ENERGY}local_import_total_kwh")
        local_export = market_sum(f"{MARKET_ENERGY}local_export_total_kwh")
        assert local_import > 0.0
        expected = {
            "local_import": local_import,
            "local_export": local_export,
            "grid_import_after_local": market_sum(f"{MARKET_ENERGY}grid_import_after_local_total_kwh") + grid_import,
            "grid_export_after_local": market_sum(f"{MARKET_ENERGY}grid_export_after_local_total_kwh") + grid_export,
        }
        for metric, value in expected.items():
            assert portfolio(f"{MARKET_ENERGY}{metric}_total_kwh") == pytest.approx(value, rel=1e-9)
            # Every community shares the step length and episode length, so daily averages add up.
            assert portfolio(f"{MARKET_ENERGY}{metric}_daily_average_kwh") == pytest.approx(value/days, rel=1e-9)

        expected_costs = {
            "settled": market_sum(f"{MARKET_COST}settled_total_eur") + cost,
            "counterfactual": market_sum(f"{MARKET_COST}counterfactual_total_eur") + cost,
            "savings": market_sum(f"{MARKET_COST}savings_total_eur"),
        }
        for metric, value in expected_costs.items():
            # The building cost series are float32, so costs match to about 1e-9.
            assert portfolio(f"{MARKET_COST}{metric}_total_eur") == pytest.approx(value, rel=1e-7)
            assert portfolio(f"{MARKET_COST}{metric}_daily_average_eur") == pytest.approx(value/days, rel=1e-7)
        assert portfolio(f"{MARKET_COST}operator_balance_total_eur") == pytest.approx(
            market_sum(f"{MARKET_COST}operator_balance_total_eur"), abs=1e-12,
        )
        assert portfolio(f"{MARKET_ENERGY}local_traded_total_kwh") == pytest.approx(local_import, rel=1e-9)

        # The settled cost now covers the whole portfolio: each market community's cost is its settled cost.
        assert portfolio(f"{MARKET_COST}settled_total_eur") == pytest.approx(portfolio("cost_total_control_eur"), rel=1e-9)

        # Shares of the whole portfolio, by hand from the pooled totals.
        demand_share = local_import/(local_import + expected["grid_import_after_local"])
        export_share = local_export/(local_export + expected["grid_export_after_local"])
        assert portfolio(f"{MARKET_SHARE}import_share_ratio") == pytest.approx(demand_share, rel=1e-9)
        assert portfolio(f"{MARKET_SHARE}local_share_of_demand_ratio") == pytest.approx(demand_share, rel=1e-9)
        assert portfolio(f"{MARKET_SHARE}local_share_of_export_ratio") == pytest.approx(export_share, rel=1e-9)

        # The community's own district rows keep the documented zeros.
        assert district("no_market", f"{MARKET_ENERGY}grid_import_after_local_total_kwh") == 0.0
        assert district("no_market", f"{MARKET_COST}settled_total_eur") == 0.0
    finally:
        env.close()


@pytest.mark.parametrize("markets", [
    {"a": {}, "b": {"local_price_ratio_to_grid_import": 0.5}},
    {"a": None, "b": None},
], ids=["every_community_has_a_market", "no_community_has_a_market"])
def test_uniform_portfolios_keep_their_market_rows(monkeypatch, markets):
    """#373 changes only portfolios that mix communities with and without a market."""

    env = _pt_rec_4_portfolio(markets)

    try:
        kpis = _run_zero_actions(env)
        monkeypatch.setattr(MultiCommunityEnv, "_with_plain_grid_settlement", lambda self, district, local: district)
        previous = env.evaluate_v2(include_business_as_usual=False)
        pd.testing.assert_frame_equal(kpis, previous)
        assert (kpis["cost_function"].str.startswith("portfolio_") & kpis["cost_function"].str.contains("community_market")).any()
    finally:
        env.close()


def test_mixed_portfolio_changes_only_portfolio_market_rows(monkeypatch):
    env = _pt_rec_4_portfolio({"market": {}, "no_market": None})

    try:
        kpis = _run_zero_actions(env)
        monkeypatch.setattr(MultiCommunityEnv, "_with_plain_grid_settlement", lambda self, district, local: district)
        previous = env.evaluate_v2(include_business_as_usual=False)
        values = pd.to_numeric(kpis["value"], errors="coerce")
        before = pd.to_numeric(previous["value"], errors="coerce")
        changed = kpis.loc[~(np.isclose(values, before, rtol=0.0, atol=0.0) | (values.isna() & before.isna())), "cost_function"]
        assert not changed.empty
        assert changed.str.startswith("portfolio_").all()
        assert changed.str.contains("_community_market_").all()
    finally:
        env.close()


def test_communities_with_the_same_seed_and_names_draw_independent_streams():
    # Both communities load the same dataset (same building and EV names) with the same seed (#462).
    env = MultiCommunityEnv(communities=[_community("community_a"), _community("community_b")])

    try:
        env.reset(seed=0)
        a, b = env.envs["community_a"], env.envs["community_b"]
        assert a.random_stream_namespace == "community_a" and b.random_stream_namespace == "community_b"
        # The episode split still follows the shared seed, so the windows stay synchronised.
        assert a.episode_tracker.episode_start_time_step == b.episode_tracker.episode_start_time_step

        def draws(child):
            building = child.buildings[0]
            return (
                building.random_generator("test").random(4).tolist(),
                building.electrical_storage.random_generator("test").random(4).tolist(),
                child._runtime_service.ev_drift_generator("Electric_Vehicle_1", "test").random(4).tolist(),
                child._ev_drift_seed,
            )

        for left, right in zip(draws(a), draws(b)):
            assert left != right
        assert a.get_metadata()["random_stream_namespace"] == "community_a"
    finally:
        env.close()


def test_a_single_environment_keeps_its_stream_keys():
    env = CityLearnEnv(str(MINUTE_SCHEMA), central_agent=True, episode_time_steps=2, render_mode="none", random_seed=0)
    named = CityLearnEnv(
        str(MINUTE_SCHEMA), central_agent=True, episode_time_steps=2, render_mode="none", random_seed=0,
        random_stream_namespace="community_a",
    )

    try:
        assert env.random_stream_namespace is None
        assert env.buildings[0].random_stream_key == ("building", "Building_1")
        assert named.buildings[0].random_stream_key == ("building", "Building_1", "namespace", "community_a")
        # The BAU reference is rebuilt with the namespace, so it simulates the same drawn devices.
        named.reset(seed=0)
        sidecar = named._business_as_usual_baseline_service._new_sidecar_env()
        try:
            assert sidecar.random_stream_namespace == "community_a"
        finally:
            sidecar.close()
    finally:
        env.close()
        named.close()

    with pytest.raises(ValueError, match="random_stream_namespace"):
        CityLearnEnv(str(MINUTE_SCHEMA), render_mode="none", random_stream_namespace="  ")


def _district_frame(values: Mapping[str, float], capacity: float = 0.0) -> pd.DataFrame:
    from citylearn.internal.kpi import BATTERY_NOMINAL_CAPACITY_ATTR

    frame = pd.DataFrame([
        {"cost_function": name, "value": value, "name": "District", "level": "district", "unit": "ratio",
         "description": "District definition."}
        for name, value in values.items()
    ])
    frame.attrs[BATTERY_NOMINAL_CAPACITY_ATTR] = {"control": capacity, "business_as_usual": capacity}
    return frame


@pytest.mark.parametrize("weight_b", [1.0, 0.0])
def test_portfolio_audit_ratios_are_pooled_from_their_counts(weight_b):
    # Two departures, none met, against 200 departures, all met: the pooled rate is 200 / 202 (#428).
    small = {
        "district_ev_departure_audit_departures_count": 2.0,
        "district_ev_departure_audit_service_observed_count": 2.0,
        "district_ev_departure_audit_target_service_met_count": 0.0,
        "district_ev_departure_audit_target_service_observed_ratio": 0.0,
        "district_thermal_service_audit_evaluated_occupied_intervals_count": 10.0,
        "district_thermal_service_audit_discomfort_intervals_count": 10.0,
        "district_thermal_service_audit_discomfort_ratio": 1.0,
        "district_deferrable_appliance_audit_offered_count": 1.0,
        "district_deferrable_appliance_audit_completed_count": 0.0,
        "district_deferrable_appliance_audit_observed_completion_ratio": 0.0,
        "district_equity_audit_population_members_count": 4.0,
        "district_equity_audit_coverage_ratio": 0.5,
        "district_equity_audit_eligible_members_count": 2.0,
        "district_equity_audit_losers_percent": 100.0,
        "district_equity_audit_positive_benefit_gini_ratio": 0.2,
        "district_energy_provenance_pv_generated_kwh": 10.0,
        "district_energy_provenance_pv_useful_building_ratio": 0.1,
        "district_energy_provenance_pv_generated_business_as_usual_kwh": 10.0,
        "district_energy_provenance_pv_useful_building_business_as_usual_ratio": 0.1,
        "district_energy_provenance_pv_useful_building_delta_to_business_as_usual_ratio": 0.0,
        "district_battery_health_capacity_fade_ratio": 0.1,
        "district_battery_health_capacity_fade_business_as_usual_ratio": 0.05,
        "district_battery_ratio_to_business_as_usual_capacity_fade_ratio": 2.0,
        "district_energy_provenance_storage_max_residual_kwh": 1.0e-6,
        "district_energy_provenance_storage_max_residual_business_as_usual_kwh": 1.0e-9,
        "district_energy_provenance_storage_max_residual_delta_to_business_as_usual_kwh": 1.0e-6 - 1.0e-9,
    }
    large = {
        "district_ev_departure_audit_departures_count": 200.0,
        "district_ev_departure_audit_service_observed_count": 200.0,
        "district_ev_departure_audit_target_service_met_count": 200.0,
        "district_ev_departure_audit_target_service_observed_ratio": 1.0,
        "district_thermal_service_audit_evaluated_occupied_intervals_count": 90.0,
        "district_thermal_service_audit_discomfort_intervals_count": 0.0,
        "district_thermal_service_audit_discomfort_ratio": 0.0,
        "district_deferrable_appliance_audit_offered_count": 99.0,
        "district_deferrable_appliance_audit_completed_count": 99.0,
        "district_deferrable_appliance_audit_observed_completion_ratio": 1.0,
        "district_equity_audit_population_members_count": 16.0,
        "district_equity_audit_coverage_ratio": 1.0,
        "district_equity_audit_eligible_members_count": 16.0,
        "district_equity_audit_losers_percent": 0.0,
        "district_equity_audit_positive_benefit_gini_ratio": 0.4,
        "district_energy_provenance_pv_generated_kwh": 90.0,
        "district_energy_provenance_pv_useful_building_ratio": 0.9,
        "district_energy_provenance_pv_generated_business_as_usual_kwh": 30.0,
        "district_energy_provenance_pv_useful_building_business_as_usual_ratio": 0.5,
        "district_energy_provenance_pv_useful_building_delta_to_business_as_usual_ratio": 0.4,
        "district_battery_health_capacity_fade_ratio": 0.2,
        "district_battery_health_capacity_fade_business_as_usual_ratio": 0.2,
        "district_battery_ratio_to_business_as_usual_capacity_fade_ratio": 1.0,
        "district_energy_provenance_storage_max_residual_kwh": 3.0e-6,
        "district_energy_provenance_storage_max_residual_business_as_usual_kwh": 2.0e-6,
        "district_energy_provenance_storage_max_residual_delta_to_business_as_usual_kwh": 1.0e-6,
    }
    env = MultiCommunityEnv(communities=[
        {**_community("community_a"), "weight": 1.0},
        {**_community("community_b"), "weight": weight_b},
    ])
    try:
        kpis = env._combine_community_kpis({
            "community_a": _district_frame(small, capacity=10.0),
            "community_b": _district_frame(large, capacity=30.0),
        })
    finally:
        env.close()

    def portfolio(name):
        return _kpi_value(kpis, f"portfolio_{name}", community_id=env.PORTFOLIO_COMMUNITY_ID, level="portfolio")

    assert portfolio("ev_departure_audit_target_service_observed_ratio") == pytest.approx(200.0 / 202.0)
    assert portfolio("thermal_service_audit_discomfort_ratio") == pytest.approx(10.0 / 100.0)
    assert portfolio("deferrable_appliance_audit_observed_completion_ratio") == pytest.approx(99.0 / 100.0)
    assert portfolio("equity_audit_coverage_ratio") == pytest.approx(18.0 / 20.0)
    assert portfolio("equity_audit_losers_percent") == pytest.approx(100.0 * 2.0 / 18.0)
    pv_control, pv_bau = (1.0 + 81.0) / 100.0, (1.0 + 15.0) / 40.0
    assert portfolio("energy_provenance_pv_useful_building_ratio") == pytest.approx(pv_control)
    assert portfolio("energy_provenance_pv_useful_building_business_as_usual_ratio") == pytest.approx(pv_bau)
    assert portfolio("energy_provenance_pv_useful_building_delta_to_business_as_usual_ratio") == pytest.approx(
        pv_control - pv_bau
    )
    assert portfolio("battery_health_capacity_fade_ratio") == pytest.approx((1.0 + 6.0) / 40.0)
    assert portfolio("battery_health_capacity_fade_business_as_usual_ratio") == pytest.approx((0.5 + 6.0) / 40.0)
    assert portfolio("battery_ratio_to_business_as_usual_capacity_fade_ratio") == pytest.approx(7.0 / 6.5)
    assert portfolio("energy_provenance_storage_max_residual_kwh") == pytest.approx(3.0e-6)
    assert portfolio("energy_provenance_storage_max_residual_delta_to_business_as_usual_kwh") == pytest.approx(1.0e-6)
    # Distributional ratios have no additive denominator and stay means weighted by the community weight.
    assert portfolio("equity_audit_positive_benefit_gini_ratio") == pytest.approx(
        (0.2 + weight_b * 0.4) / (1.0 + weight_b)
    )
    rows = kpis[kpis["level"] == "portfolio"].set_index("cost_function")
    description = rows.loc["portfolio_ev_departure_audit_target_service_observed_ratio", "description"]
    assert description.startswith("Portfolio: pooled over the communities")
    assert "`portfolio_ev_departure_audit_service_observed_count`" in description
    assert description.endswith("Each community: District definition.")
    assert kpis.attrs["portfolio_aggregation"]["portfolio_equity_audit_positive_benefit_gini_ratio"] == {
        "rule": "weighted_mean", "over": [],
    }


def _exported_portfolio(tmp_path: Path, session: str, *, identity=True, **export_kwargs):
    env = MultiCommunityEnv(
        communities=[_community("community_a", episode_time_steps=2), _community("community_b", episode_time_steps=2)],
        render_directory=tmp_path / "renders",
        render_session_name=session,
    )
    try:
        if identity:
            env.set_experiment_identity(implementation="tests.Zero", version="1", parameters={})
        env.reset(seed=0)
        while not env.terminated:
            env.step(_multi_zero_actions(env))
        manifest = env.export_final_kpis(export_business_as_usual_timeseries=False, **export_kwargs)
        return Path(env.new_folder_path), manifest
    finally:
        env.close()


def test_portfolio_export_writes_a_manifest_that_compare_exports_pairs(tmp_path: Path):
    from citylearn.internal.comparison import compare_exports

    left, manifest = _exported_portfolio(tmp_path, "left", kpi_round_decimals=6)
    right, _ = _exported_portfolio(tmp_path, "right", kpi_round_decimals=6)
    saved = json.loads((left / "exported_kpis_multi_community.manifest.json").read_text(encoding="utf-8"))
    assert saved["kind"] == "multi_community"
    assert saved["community_ids"] == ["community_a", "community_b"]
    assert saved["weights"] == {"community_a": 1.0, "community_b": 1.0}
    assert saved["kpi_export"]["kpi_round_decimals"] == 6
    assert saved["kpi_export"]["include_battery_health_audit"] is False
    assert saved["communities"]["community_a"]["manifest"] == "community_a/exported_kpis.manifest.json"
    assert saved["communities"]["community_a"]["random_stream_namespace"] == "community_a"
    assert saved["portfolio_aggregation"]["portfolio_energy_grid_total_import_control_kwh"]["rule"] == "sum"
    assert saved["kpi_definitions"]["portfolio_energy_grid_total_import_control_kwh"]["description"].startswith(
        "Portfolio: sum of the community values."
    )
    assert saved["controller_identity"]["implementation"] == "tests.Zero"

    report = compare_exports(left / "exported_kpis_multi_community.csv", right / "exported_kpis_multi_community.csv")
    assert report["status"] == "paired", (report["mismatches"], report["missing_evidence"])
    assert any(row["name"] == "__portfolio__:Portfolio" for row in report["outcome_summary"])


def test_portfolio_comparison_names_the_community_that_lacks_evidence(tmp_path: Path):
    from citylearn.internal.comparison import compare_exports

    left, _ = _exported_portfolio(tmp_path, "left")
    right, _ = _exported_portfolio(tmp_path, "right", identity=False)
    report = compare_exports(left / "exported_kpis_multi_community.csv", right / "exported_kpis_multi_community.csv")
    assert report["status"] == "unknown"
    assert {"community_a:controller_identity", "community_b:controller_identity"} <= set(report["missing_evidence"])


def test_kpi_exports_can_include_the_battery_health_audit(tmp_path: Path):
    root, manifest = _exported_portfolio(tmp_path, "health", include_battery_health_audit=True)
    portfolio = pd.read_csv(root / "exported_kpis_multi_community.csv")
    assert portfolio["cost_function"].str.contains("ev_battery_health").any()
    community = pd.read_csv(root / "community_a" / "exported_kpis.csv")
    assert community["KPI"].str.contains("ev_battery_health").any()
    child = json.loads((root / "community_a" / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
    assert child["kpi_export"] == {
        "include_business_as_usual": True, "include_battery_health_audit": True, "kpi_round_decimals": None,
    }
    assert manifest["kpi_export"]["include_battery_health_audit"] is True


def test_portfolio_export_follows_the_parquet_render_format(tmp_path: Path):
    env = MultiCommunityEnv(
        communities=[
            _community("community_a", episode_time_steps=2, render_file_format="parquet"),
            _community("community_b", episode_time_steps=2, render_file_format="parquet"),
        ],
        render_directory=tmp_path / "renders",
        render_session_name="parquet",
    )
    try:
        env.reset(seed=0)
        env.step(_multi_zero_actions(env))
        env.export_final_kpis(include_business_as_usual=False, export_business_as_usual_timeseries=False)
        root = Path(env.new_folder_path)
    finally:
        env.close()
    assert (root / "exported_kpis_multi_community.parquet").is_file()
    assert not (root / "exported_kpis_multi_community.csv").exists()
    manifest = json.loads((root / "exported_kpis_multi_community.manifest.json").read_text(encoding="utf-8"))
    assert manifest["kpi_export"]["file_format"] == "parquet"
    assert manifest["communities"]["community_a"]["manifest"] == "community_a/exported_kpis.manifest.json"


def test_portfolio_scorecard_lists_the_default_kpis_of_every_level():
    env = MultiCommunityEnv(communities=[_community("community_a"), _community("community_b")])
    try:
        env.reset(seed=0)
        env.step(_multi_zero_actions(env))
        kpis = env.evaluate_v2(include_business_as_usual=False)
        card = env.scorecard(kpis, level="portfolio")
        assert len(card) > 0 and set(card["level"]) == {"portfolio"}
        default = list(CityLearnEnv.SCORECARD_DEFAULT_KPIS)
        order = [default.index(name.replace("portfolio_", "district_", 1)) for name in card["cost_function"]]
        assert order == sorted(order)
        district = env.scorecard(kpis, level="district")
        assert list(district["community_id"].unique()) == ["community_a", "community_b"]
        with pytest.raises(ValueError, match="level"):
            env.scorecard(kpis, level="community")
    finally:
        env.close()
