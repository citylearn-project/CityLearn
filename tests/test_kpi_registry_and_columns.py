"""Tests for the KPI metadata registry and evaluate_v2() unit/description columns (#298)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv
from citylearn.internal.comparison import compare_exports, load_kpis
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.internal.kpi_registry import (
    KPI_COLUMNS,
    KPI_REGISTRY,
    KPI_UNITS,
    get_kpi_definition,
    resolve_kpi_metadata,
)
from citylearn.multi_community import MultiCommunityEnv

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BASE_COLUMNS = [
    "cost_function",
    "value",
    "name",
    "level",
    "unit",
    "description",
]


def _step_zero(env: CityLearnEnv) -> None:
    env.reset(seed=0)
    if hasattr(env.action_space, "spaces"):
        action = {
            "tables": {
                name: np.zeros(space.shape, dtype="float32")
                for name, space in env.action_space["tables"].items()
            }
        }
    else:
        action = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
    env.step(action)


def _assert_valid_kpi_metadata_columns(frame: pd.DataFrame) -> None:
    assert list(frame.columns[:6]) == EXPECTED_BASE_COLUMNS
    assert not frame.empty
    assert frame["unit"].notna().all()
    assert frame["description"].notna().all()

    for row in frame[["cost_function", "unit", "description"]].drop_duplicates().itertuples(index=False):
        expected_unit, expected_desc = resolve_kpi_metadata(str(row.cost_function))
        assert row.unit == expected_unit
        assert row.description == expected_desc
        assert row.unit in KPI_UNITS
        assert isinstance(row.description, str) and len(row.description) >= 10
        assert row.description.endswith(".")


def test_registry_invariants_and_ui_long_table_text_safety():
    assert list(KPI_COLUMNS) == EXPECTED_BASE_COLUMNS
    assert len(KPI_REGISTRY) >= 1800

    for key, definition in KPI_REGISTRY.items():
        assert definition.cost_function == key
        assert definition.unit in KPI_UNITS
        assert definition.level in {"building", "district", "portfolio"}
        assert definition.description and definition.description.endswith(".")
        assert "\n" not in definition.description
        # CityLearn UI's analyzeTable() treats non-KPI long columns as text only when
        # no cell parses as a finite number (src/results/quality.js:152-153).
        with pytest.raises(ValueError):
            float(definition.description)

    with pytest.raises(KeyError, match="Unregistered KPI cost_function"):
        get_kpi_definition("district_unknown_unregistered_metric_kwh")


def test_registry_resolves_dynamic_phase_peaks_and_portfolio_counterparts():
    for level in ("building", "district", "portfolio"):
        for direction in ("import", "export"):
            for phase in ("l1", "l2", "l3", "l4", "phase_a", "n"):
                cf = f"{level}_electrical_service_phase_phase_peaks_{direction}_peak_{phase}_kw"
                definition = get_kpi_definition(cf)
                assert definition.unit == "kW"
                assert phase.upper() in definition.description
                assert direction in definition.description

    custom_portfolio = get_kpi_definition(
        "portfolio_electrical_service_phase_phase_peaks_import_peak_phase_b_kw"
    )
    assert custom_portfolio.unit == "kW"
    assert custom_portfolio.level == "portfolio"
    assert "multi-community portfolio" in custom_portfolio.description


def test_registry_covers_scorecard_docs_and_parity_snapshot():
    for name in CityLearnEnv.SCORECARD_DEFAULT_KPIS:
        unit, description = resolve_kpi_metadata(name)
        assert unit in KPI_UNITS
        assert description.endswith(".")

    doc_files = (
        ROOT / "docs/KPI_V2_TREE.md",
        ROOT / "docs/kpis_reference.md",
        ROOT / "docs/pt/kpis_reference.md",
        ROOT / "docs/scorecard.md",
        ROOT / "docs/multi_community_reference.md",
        ROOT / "docs/pt/multi_community_reference.md",
    )
    doc_kpis = set()
    for path in doc_files:
        text = path.read_text(encoding="utf-8")
        for match in re.findall(r"`((?:district|building|portfolio)_[a-z0-9_]+)`", text):
            if match != "building_mean" and not match.endswith("_"):
                doc_kpis.add(match)

    assert len(doc_kpis) >= 170
    for name in sorted(doc_kpis):
        unit, description = resolve_kpi_metadata(name)
        assert unit in KPI_UNITS
        assert description.endswith(".")

    snapshot = json.loads(
        (ROOT / "scripts/audit/snapshots/refactor_parity.json").read_text(encoding="utf-8")
    )
    snapshot_kpis = {
        key.split("/", 2)[2]
        for case in snapshot["cases"].values()
        for key in case["kpis"]
    } | {
        name
        for case in snapshot["cases"].values()
        for name in case["exported_kpis"]["KPI"]
    }
    assert len(snapshot_kpis) >= 650
    for name in sorted(snapshot_kpis):
        unit, description = resolve_kpi_metadata(name)
        assert unit in KPI_UNITS
        assert description.endswith(".")


@pytest.mark.parametrize(
    ("dataset", "kwargs", "with_bau"),
    [
        ("citylearn_challenge_2022_phase_all_plus_evs", {"episode_time_steps": 4, "central_agent": True}, True),
        ("citylearn_challenge_2022_phase_all_demand_response", {"episode_time_steps": 4, "interface": "entity"}, True),
        ("citylearn_challenge_2022_phase_all_robustness", {"episode_time_steps": 4, "central_agent": True}, True),
        ("citylearn_three_phase_electrical_service_demo", {"episode_time_steps": 4, "central_agent": True}, True),
        ("citylearn_three_phase_dynamic_topology_demo", {"episode_time_steps": 4, "interface": "entity"}, True),
        ("citylearn_challenge_2023_phase_1", {"episode_time_steps": 4, "central_agent": True}, True),
        ("pt_rec_4", {"episode_time_steps": 4, "interface": "entity"}, True),
    ],
)
def test_evaluate_v2_and_scorecard_columns_and_registry_coverage(dataset, kwargs, with_bau):
    env = CityLearnEnv(dataset, render_mode="none", random_seed=0, **kwargs)
    try:
        _step_zero(env)
        kpis = env.evaluate_v2(include_business_as_usual=with_bau)
        _assert_valid_kpi_metadata_columns(kpis)

        if getattr(env, "topology_mode", "static") == "dynamic":
            assert list(kpis.columns) == [
                *EXPECTED_BASE_COLUMNS,
                "topology_born_at",
                "topology_removed_at",
                "topology_active",
            ]
        else:
            assert list(kpis.columns) == EXPECTED_BASE_COLUMNS

        scorecard = env.scorecard(kpis)
        assert list(scorecard.columns) == list(kpis.columns)
        assert not scorecard.empty
        assert scorecard["unit"].notna().all()
        assert scorecard["description"].notna().all()
    finally:
        env.close()


def test_empty_evaluate_v2_preserves_six_column_contract():
    empty = CityLearnKPIService._empty_v2_frame({"energy_accounting": {"kpi_definition_version": "2.0.0"}})
    assert empty.empty
    assert list(empty.columns) == EXPECTED_BASE_COLUMNS
    assert empty.attrs["energy_accounting"]["kpi_definition_version"] == "2.0.0"

    mc_shell = object.__new__(MultiCommunityEnv)
    mc_empty = MultiCommunityEnv._combine_community_kpis(mc_shell, {})
    assert mc_empty.empty
    assert list(mc_empty.columns) == [*EXPECTED_BASE_COLUMNS, "community_id"]

    scorecard_empty = CityLearnEnv.scorecard(object.__new__(CityLearnEnv), empty)
    assert scorecard_empty.empty
    assert list(scorecard_empty.columns) == EXPECTED_BASE_COLUMNS


def test_exports_keep_wide_csv_numeric_and_long_multi_community_with_metadata(tmp_path):
    mc = MultiCommunityEnv(
        communities=[
            {
                "community_id": "community_a",
                "schema": "citylearn_challenge_2022_phase_all_plus_evs",
                "env_kwargs": {"episode_time_steps": 3, "central_agent": True, "render_mode": "none", "random_seed": 0},
            },
            {
                "community_id": "community_b",
                "schema": "citylearn_challenge_2022_phase_all_plus_evs",
                "env_kwargs": {"episode_time_steps": 3, "central_agent": True, "render_mode": "none", "random_seed": 0},
            },
        ],
        render_directory=tmp_path / "renders",
        render_session_name="mc_meta",
    )
    try:
        mc.reset(seed=0)
        mc.step({
            cid: [np.zeros(space.shape, dtype="float32") for space in child.action_space]
            for cid, child in mc.envs.items()
        })
        mc.envs["community_a"].set_experiment_identity("ctrl-a", "1.0", {})
        mc.envs["community_b"].set_experiment_identity("ctrl-b", "1.0", {})
        mc.export_final_kpis(include_business_as_usual=False, export_business_as_usual_timeseries=False)

        root = tmp_path / "renders" / "mc_meta"
        global_csv = root / "exported_kpis_multi_community.csv"
        long_df = pd.read_csv(global_csv)
        assert list(long_df.columns) == [*EXPECTED_BASE_COLUMNS, "community_id"]
        _assert_valid_kpi_metadata_columns(long_df)
        assert "portfolio" in set(long_df["level"])

        # load_kpis() and compare_exports() read both long and wide KPI exports cleanly.
        loaded_long = load_kpis(global_csv)
        assert len(loaded_long) == len(long_df)

        child_csv = root / "community_a" / "exported_kpis.csv"
        wide_df = pd.read_csv(child_csv)
        assert wide_df.columns[0] == "KPI"
        assert "unit" not in wide_df.columns
        assert "description" not in wide_df.columns
        assert "District" in wide_df.columns
        loaded_wide = load_kpis(child_csv)
        assert len(loaded_wide) > 0

        report = compare_exports(child_csv, root / "community_b" / "exported_kpis.csv")
        assert report["status"] == "paired"

        manifest = json.loads((root / "community_a" / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
        assert "kpi_definitions" in manifest
        assert set(manifest["kpi_definitions"]) == set(wide_df["KPI"])
        for cf, entry in manifest["kpi_definitions"].items():
            expected_unit, expected_desc = resolve_kpi_metadata(cf)
            assert entry == {"unit": expected_unit, "description": expected_desc}
    finally:
        mc.close()


def test_sphinx_guides_generate_scorecard_and_catalogue_from_registry():
    spec = importlib.util.spec_from_file_location(
        "citylearn_guides_test",
        ROOT / "docs/source/_ext/citylearn_guides.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    scorecard_md = module.scorecard_kpi_page(ROOT)
    assert "| KPI | Unit | Description |" in scorecard_md
    for name in CityLearnKPIService.SCORECARD_DEFAULT_KPIS:
        unit, description = resolve_kpi_metadata(name)
        assert f"| `{name}` | `{unit}` | {description} |" in scorecard_md

    catalogue_md = module.kpi_catalogue(ROOT)
    assert "# Complete KPI catalogue" in catalogue_md
    assert "`district_cost_total_control_eur`" in catalogue_md
    assert "`topology_lifecycle_presence`" in catalogue_md
