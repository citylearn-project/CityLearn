"""The `unit` and `description` columns of the `evaluate_v2()` table come from one registry (#298)."""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal import kpi_registry
from citylearn.multi_community import MultiCommunityEnv

ROOT = Path(__file__).resolve().parents[1]
MINUTE_SCHEMA = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"
FIRST_COLUMNS = ["cost_function", "value", "name", "level"]
# Bundled datasets that between them produce every KPI family: EV, deferrable appliances, community market,
# electrical service and phases, demand response, robustness and dynamic topology.
DATASETS = (
    "pt_rec_4",
    "citylearn_challenge_2022_phase_all_demand_response",
    "citylearn_challenge_2022_phase_all_robustness",
    "citylearn_challenge_2022_phase_all_plus_evs",
    "citylearn_three_phase_dynamic_topology_demo",
    "citylearn_challenge_2022_phase_all",
)


def _zero_actions(env):
    if env.interface == "entity":
        return {"tables": {name: np.zeros(space.shape, dtype="float32") for name, space in env.action_space["tables"].items()}}

    return [np.zeros(space.shape, dtype="float32") for space in env.action_space]


def _evaluate(dataset: str) -> pd.DataFrame:
    env = CityLearnEnv(dataset, central_agent=True, episode_time_steps=4, random_seed=0, render_mode="none")

    try:
        env.reset(seed=0)

        while not env.terminated:
            env.step(_zero_actions(env))

        return env.evaluate_v2()
    finally:
        env.close()


@pytest.fixture(scope="module")
def tables():
    return {dataset: _evaluate(dataset) for dataset in DATASETS}


def _community(community_id: str):
    return {
        "community_id": community_id,
        "schema": str(MINUTE_SCHEMA),
        "env_kwargs": {"central_agent": True, "episode_time_steps": 4, "render_mode": "none", "random_seed": 0},
    }


@pytest.fixture(scope="module")
def portfolio_table():
    env = MultiCommunityEnv(communities=[_community("community_a"), _community("community_b")])

    try:
        env.reset(seed=0)

        while not env.terminated:
            env.step({community_id: _zero_actions(child) for community_id, child in env.envs.items()})

        return env.evaluate_v2()
    finally:
        env.close()


def test_table_keeps_its_columns_and_adds_unit_and_description_after_them(tables):
    for dataset, table in tables.items():
        columns = list(table.columns)
        assert columns[:6] == FIRST_COLUMNS + ["unit", "description"], dataset


def test_every_kpi_name_has_a_registry_entry_with_a_unit_and_a_description(tables, portfolio_table):
    names = set().union(*(set(table["cost_function"]) for table in tables.values()))
    names |= set(portfolio_table["cost_function"])
    assert len(names) > 1000
    missing = sorted(name for name in names if kpi_registry.description_of(name) is None)
    assert not missing, f"KPI names without a registry entry: {missing[:20]}"

    for table in list(tables.values()) + [portfolio_table]:
        assert table["unit"].isin(list(kpi_registry.UNITS)).all()
        assert table["description"].map(lambda text: isinstance(text, str) and len(text.strip()) > 0).all()


def test_the_unit_is_the_name_suffix_unless_an_explicit_entry_says_otherwise(tables):
    names = set().union(*(set(table["cost_function"]) for table in tables.values()))
    explicit = {name for name in names if kpi_registry.unit_of(name) != kpi_registry.unit_from_suffix(name)}
    assert explicit == {"topology_lifecycle_presence"}
    assert kpi_registry.unit_of("district_thermal_service_audit_cold_degree_hours") == "degree_hours"
    assert kpi_registry.unit_of("district_deferrable_appliance_service_average_start_delay_hours") == "hours"


def test_a_name_without_an_entry_gets_the_suffix_unit_and_no_description():
    assert kpi_registry.describe("district_new_family_total_kwh") == ("kwh", None)
    assert kpi_registry.describe("district_new_family_total") == (None, None)


def test_level_prefixes_share_one_entry():
    stripped = kpi_registry.describe("district_cost_total_control_eur")
    assert stripped == kpi_registry.describe("building_cost_total_control_eur")
    assert stripped == kpi_registry.describe("portfolio_cost_total_control_eur")
    assert stripped == ("eur", "Total electricity cost (control run).")


def test_unit_and_description_do_not_depend_on_the_row(tables):
    for table in tables.values():
        assert table.groupby("cost_function")[["unit", "description"]].nunique(dropna=False).max().max() == 1


def test_portfolio_rows_carry_a_unit_and_a_description(portfolio_table):
    assert list(portfolio_table.columns[:6]) == FIRST_COLUMNS + ["unit", "description"]
    portfolio = portfolio_table[portfolio_table["level"] == "portfolio"]
    assert len(portfolio) > 100
    assert portfolio["unit"].notna().all() and portfolio["description"].notna().all()
    district = portfolio_table[portfolio_table["level"] == "district"].drop_duplicates("cost_function")
    expected = district.set_index(district["cost_function"].str.replace("district_", "portfolio_", regex=False))
    pooled = portfolio.set_index("cost_function")
    common = pooled.index.intersection(expected.index)
    assert len(common) > 100
    assert (pooled.loc[common, "unit"] == expected.loc[common, "unit"]).all()


def _documentation_rows():
    text = (ROOT / "docs/kpis_reference.md").read_text(encoding="utf-8")
    units = dict(re.findall(r"^\| `(\w+)` \| (.+?) \|$", text.split("\n## Units")[1].split("\n## ")[0], flags=re.MULTILINE))
    rows = {}

    for section in ("Demand Response KPIs", "Robustness KPIs"):
        body = text.split(f"## {section}")[1].split("\n## ")[0]
        for suffix, unit, meaning in re.findall(r"^\| `(\w+)` \| [\w/]+ \| (\w+) \| (.+?) \|$", body, flags=re.MULTILINE):
            rows[suffix] = (unit, meaning)

    return units, rows


def test_units_table_of_the_reference_matches_the_registry():
    units, _ = _documentation_rows()
    assert units == kpi_registry.UNITS


def test_demand_response_and_robustness_tables_of_the_reference_match_the_registry():
    _, rows = _documentation_rows()
    assert len(rows) == 19

    for suffix, (unit, meaning) in rows.items():
        for level in ("district", "building"):
            assert kpi_registry.describe(f"{level}_{suffix}") == (unit.lower(), meaning), suffix


def test_wide_export_keeps_its_columns_and_the_manifest_lists_units_and_descriptions(tmp_path: Path):
    env = CityLearnEnv(
        "citylearn_challenge_2022_phase_all_plus_evs", episode_time_steps=4, render_mode="none",
        render_directory=tmp_path, render_session_name="registry", random_seed=0,
    )

    try:
        env.reset(seed=0)

        while not env.terminated:
            env.step(_zero_actions(env))

        env.export_final_kpis(export_business_as_usual_timeseries=False)
        output = Path(env.new_folder_path)
        wide = pd.read_csv(output / "exported_kpis.csv")
        # The CityLearn UI reads every column after `KPI` as an entity, so no text columns are added.
        assert next(iter(wide.columns)) == "KPI"
        assert not {"unit", "description"} & set(wide.columns)
        catalogue = json.loads((output / "exported_kpis.manifest.json").read_text(encoding="utf-8"))["kpi_catalogue"]
        assert set(catalogue) == set(wide["KPI"])
        assert catalogue["district_cost_total_control_eur"] == {
            "unit": "eur", "description": "Total electricity cost (control run)."}
        assert all(entry["unit"] and entry["description"] for entry in catalogue.values())
    finally:
        env.close()


def test_multi_community_long_export_has_the_trailing_columns_after_the_first_four(tmp_path: Path):
    env = MultiCommunityEnv(
        communities=[_community("community_a"), _community("community_b")],
        render_directory=tmp_path / "renders", render_session_name="registry",
    )

    try:
        env.reset(seed=0)
        env.step({community_id: _zero_actions(child) for community_id, child in env.envs.items()})
        env.export_final_kpis(include_business_as_usual=False, export_business_as_usual_timeseries=False)
        frame = pd.read_csv(tmp_path / "renders" / "registry" / "exported_kpis_multi_community.csv", keep_default_na=False)
        assert list(frame.columns) == FIRST_COLUMNS + ["unit", "description", "community_id"]
        assert (frame["unit"] != "").all() and (frame["description"] != "").all()
    finally:
        env.close()
