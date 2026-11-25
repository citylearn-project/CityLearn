"""Every KPI name evaluate_v2() emits is in the KPI catalogue, and the catalogue pages are current (#326)."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.agents.baseline import RBCSmartPolicy
from citylearn.citylearn import CityLearnEnv
from citylearn.internal.kpi import CityLearnKPIService
from citylearn.internal.kpi_catalogue import expand, kpi_definitions
from citylearn.multi_community import MultiCommunityEnv

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "data" / "datasets"

# Together these emit every family: EVs and flexible appliances, phase limits and a community market, demand
# response, robustness events, dynamic topology, outages with LSTM thermal dynamics, and a portfolio.
SCENARIOS = (
    ("citylearn_challenge_2022_phase_all_plus_evs", 24, {"central_agent": True}),
    ("citylearn_challenge_2022_phase_all_plus_evs", 24, {"central_agent": True, "evaluation_window": {"enabled": True}}),
    ("citylearn_three_phase_electrical_service_demo", 24, {}),
    ("citylearn_challenge_2022_phase_all_demand_response", 24, {}),
    ("citylearn_challenge_2022_phase_all_robustness", 24, {}),
    ("citylearn_three_phase_dynamic_topology_demo", 48, {}),
    ("citylearn_challenge_2023_phase_1", 24, {}),
)


def _catalogue():
    spec = importlib.util.spec_from_file_location("kpi_catalogue", ROOT / "scripts" / "docs" / "kpi_catalogue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _names(kpis):
    assert list(kpis.columns[:6]) == ["cost_function", "value", "name", "level", "unit", "description"]
    assert kpis[["unit", "description"]].notna().all().all()
    return {(name, level) for name, level in zip(kpis["cost_function"], kpis["level"])}


@pytest.fixture(scope="module")
def emitted():
    """(name, level) of every row evaluate_v2() returns on the scenarios, with the BAU comparison."""
    names = set()
    for dataset, steps, kwargs in SCENARIOS:
        env = CityLearnEnv(str(DATASETS / dataset / "schema.json"), episode_time_steps=steps, render_mode="none", **kwargs)
        try:
            agent = RBCSmartPolicy(env)
            observations, _ = env.reset(seed=0)
            while not env.terminated:
                observations, *_ = env.step(agent.predict(observations))
            names |= _names(env.evaluate_v2())
        finally:
            env.close()

    portfolio = MultiCommunityEnv(communities=[
        {
            "community_id": community_id,
            "schema": str(DATASETS / "citylearn_challenge_2022_phase_all_plus_evs" / "schema.json"),
            "weight": weight,
            "env_kwargs": {"central_agent": True, "episode_time_steps": 24, "render_mode": "none"},
        }
        for community_id, weight in (("a", 1.0), ("b", 2.0))
    ])
    try:
        portfolio.reset(seed=0)
        while not portfolio.terminated:
            portfolio.step({
                community_id: [np.zeros(space.shape, dtype="float32") for space in env.action_space]
                for community_id, env in portfolio.envs.items()
            })
        names |= _names(portfolio.evaluate_v2())
    finally:
        portfolio.close()

    return names


def test_every_emitted_kpi_is_in_the_catalogue(emitted):
    catalogue = _catalogue()
    documented = catalogue.documented_names(catalogue.load())
    missing = sorted(
        name for name, level in emitted
        if (("district_" + name[len("portfolio_"):]) if level == "portfolio" else name) not in documented
    )
    assert not missing, (
        f"{len(missing)} KPI names are not in citylearn/misc/kpi_catalogue.yml; add them and run "
        f"python scripts/docs/kpi_catalogue.py: {missing[:20]}"
    )


def test_every_catalogued_kpi_is_emitted(emitted):
    catalogue = _catalogue()
    names = {name for name, level in emitted if level != "portfolio"}
    stale = sorted(set(catalogue.documented_names(catalogue.load())) - names)
    assert not stale, f"citylearn/misc/kpi_catalogue.yml lists names that no scenario emits: {stale[:20]}"


def test_scorecard_kpis_are_catalogued():
    catalogue = _catalogue()
    documented = catalogue.documented_names(catalogue.load())
    assert set(CityLearnKPIService.SCORECARD_DEFAULT_KPIS) <= set(documented)


def test_catalogue_pages_are_current():
    catalogue = _catalogue()
    families = catalogue.load()
    for language, path in catalogue.PAGES.items():
        assert path.read_text(encoding="utf-8") == catalogue.render(families, language), (
            f"{path.relative_to(ROOT)} is out of date; run python scripts/docs/kpi_catalogue.py"
        )


def test_catalogue_families_have_reference_sections():
    catalogue = _catalogue()
    for family in catalogue.load():
        for language, path in (("en", ROOT / "docs" / "kpis_reference.md"), ("pt", ROOT / "docs" / "pt" / "kpis_reference.md")):
            assert f"\n## {family['title'][language]}\n" in path.read_text(encoding="utf-8"), (family["id"], language)


def test_brace_patterns_expand():
    assert expand("a_{b,c}{,_d}_e") == ["a_b_e", "a_b_d_e", "a_c_e", "a_c_d_e"]
    assert expand("plain") == ["plain"]


def test_manifest_definitions_omit_unknown_extensions():
    name = "district_battery_total_throughput_kwh"
    definitions = kpi_definitions([name, "custom_extension"])
    assert list(definitions) == [name]
    assert definitions[name]["unit"] == "kWh"
    assert definitions[name]["description"]
