"""Executable onboarding examples and documentation/source consistency."""

import ast
import importlib.util
import inspect
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]


def python_blocks(path):
    return re.findall(r"```python\n(.*?)\n```", path.read_text(encoding="utf-8"), re.S)


def test_readme_matches_runnable_example():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert python_blocks(ROOT / "README.md") == [
        (ROOT / "examples/first_simulation.py").read_text(encoding="utf-8").strip()
    ]
    assert "releases.md" not in readme
    assert "Current source release:" not in readme
    assert (ROOT / "assets/images/citylearn-v3-overview.png").is_file()
    assert "Tiago Fonseca" in (ROOT / "assets/tables/citylearn_contributors.csv").read_text(encoding="utf-8")


def test_first_simulation_and_scorecard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scope = {}
    exec(compile((ROOT / "examples/first_simulation.py").read_text(encoding="utf-8"), "first_simulation.py", "exec"), scope)
    assert scope["env"].time_step == 23
    assert scope["terminated"] or scope["truncated"]
    assert set(("cost_function", "value", "name", "level")) <= set(scope["kpis"].columns)
    from citylearn.internal.kpi import CityLearnKPIService
    assert set(CityLearnKPIService.SCORECARD_DEFAULT_KPIS) <= set(scope["kpis"]["cost_function"])
    for node in ast.walk(ast.parse(python_blocks(ROOT / "docs/scorecard.md")[0])):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "selected" for t in node.targets):
            assert set(ast.literal_eval(node.value)) <= set(scope["kpis"]["cost_function"])
    exec(compile(python_blocks(ROOT / "docs/scorecard.md")[0], "scorecard.md", "exec"), scope)
    assert (tmp_path / "scorecard.csv").is_file()
    assert len(scope["scorecard"]) == len(scope["selected"])


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("directory", ["docs", "docs/pt"])
def test_running_guide_examples(index, directory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scope = {}
    try:
        exec(compile(python_blocks(ROOT / directory / "running_simulations.md")[index], "running_simulations.md", "exec"), scope)
        assert "env" in scope
    finally:
        if "env" in scope:
            scope["env"].close()


@pytest.mark.parametrize("directory", ["docs", "docs/pt"])
def test_multi_community_example(directory, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    scope = {}
    exec(compile(python_blocks(ROOT / directory / "multi_community_reference.md")[0], "multi_community_reference.md", "exec"), scope)
    assert "portfolio" in set(scope["kpis"]["level"])
    assert scope["terminated"] or scope["truncated"]


def test_feature_examples_are_public():
    content = (ROOT / "docs/features.md").read_text(encoding="utf-8")
    for name in re.findall(r"`(citylearn_[a-z0-9_]+)`", content):
        assert (ROOT / "data/datasets" / name / "schema.json").is_file(), name


def test_generated_scorecard_uses_runtime_selection():
    spec = importlib.util.spec_from_file_location("citylearn_guides", ROOT / "docs/source/_ext/citylearn_guides.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from citylearn.internal.kpi import CityLearnKPIService
    assert module.scorecard_names(ROOT) == CityLearnKPIService.SCORECARD_DEFAULT_KPIS


def test_website_omits_repository_translation_links():
    spec = importlib.util.spec_from_file_location("citylearn_guides", ROOT / "docs/source/_ext/citylearn_guides.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = "# Guide\n\nPortuguese version: [pt/guide.md](pt/guide.md).\n\n## Details\n\nText.\n"
    assert module.website_guide_content(source) == "# Guide\n\n## Details\n\nText.\n"
    index = (ROOT / "docs/source/index.rst").read_text(encoding="utf-8")
    assert "guides/pt/" not in index
    assert "guides/retired_datasets" not in index


@pytest.mark.parametrize("central_agent", [False, True])
def test_custom_controller_and_reward(central_agent, monkeypatch, tmp_path):
    from examples.custom_controller import GridImportReward, run

    monkeypatch.chdir(tmp_path)
    kpis = run(central_agent=central_agent)
    assert "district_cost_total_control_eur" in set(kpis["cost_function"])
    reward = GridImportReward({"central_agent": central_agent})
    observations = [
        {"net_electricity_consumption": 2.0},
        {"net_electricity_consumption": -1.0},
    ]
    assert reward.calculate(observations) == ([-2.0] if central_agent else [-2.0, 0.0])


def test_ui_export_example(monkeypatch, tmp_path):
    import pandas as pd
    from examples.export_for_ui import run

    monkeypatch.chdir(tmp_path)
    output = run()
    assert output == tmp_path / "outputs/ui_exports/bau_48h"
    kpis = pd.read_csv(output / "exported_kpis.csv")
    assert {"KPI", "District", "Building_1"} <= set(kpis.columns)
    assert kpis["KPI"].str.contains("business_as_usual").any()
    community = pd.read_csv(output / "exported_data_community_ep0.csv")
    # reset() provides the initial state; 48 states produce 47 step exports.
    assert len(community) == 47
    assert any(output.glob("exported_data_building_*_ep0.csv"))


def test_documented_bau_defaults():
    from citylearn.agents.baseline import BusinessAsUsualAgent

    content = (ROOT / "docs/baselines.md").read_text(encoding="utf-8")
    rows = re.findall(r"\| `([a-z_]+)` \| `([^`]+)` \|", content)
    defaults = inspect.signature(BusinessAsUsualAgent).parameters
    assert len(rows) == 8
    for name, value in rows:
        assert ast.literal_eval(value) == defaults[name].default


def test_kpi_only_ui_export(tmp_path):
    import pandas as pd
    from citylearn.agents.baseline import BusinessAsUsualAgent
    from citylearn.citylearn import CityLearnEnv

    env = CityLearnEnv(
        "citylearn_challenge_2022_phase_all_plus_evs",
        episode_time_steps=4,
        render_mode="none",
        render_directory=tmp_path,
        render_session_name="kpi_only",
        random_seed=0,
    )
    try:
        agent = BusinessAsUsualAgent(env)
        observations, _ = env.reset(seed=0)
        while not env.terminated:
            observations, _, _, _, _ = env.step(agent.predict(observations))
        env.export_final_kpis(export_business_as_usual_timeseries=False)
        output = Path(env.new_folder_path)
        assert {path.name for path in output.iterdir()} == {
            "exported_kpis.csv", "exported_kpis.deferrable_service.json",
            "exported_kpis.manifest.json",
        }
        assert not list(output.glob("exported_data_*"))
        assert json.loads((output / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
        assert "District" in pd.read_csv(output / "exported_kpis.csv").columns
    finally:
        env.close()


def test_navigation_and_current_ui():
    index = (ROOT / "docs/source/index.rst").read_text(encoding="utf-8")
    evaluate = index.split(":caption: Evaluate")[1].split(".. toctree::")[0]
    assert "guides/baselines" in evaluate
    assert "kpis" in evaluate
    assert "\n   ui\n" not in evaluate
    assert ":caption: Visualize" in index
    assert "publications" in index
    assert "assets/images/citylearn-v3-overview.png" in index
    assert "assets/images/dr.jpg" not in index
    overview = (ROOT / "docs/source/overview/index.rst").read_text(encoding="utf-8")
    assert "Core concepts\n=============" in overview
    assert ".. _overview:" in overview
    assert ".. figure:: ../../../assets/images/dr.jpg" in overview
    assert (ROOT / "assets/images/dr.jpg").is_file()
    ui = (ROOT / "docs/source/ui.rst").read_text(encoding="utf-8")
    for text in ("Create Schema", "v2.5.0", "/admin/help", "schema-structure.png"):
        assert text not in ui
    for text in ("Choose folders", "Timeseries", "KPIs", "Compare baseline"):
        assert text in ui
    for name in ("v3-timeseries.png", "v3-scorecard.png"):
        assert (ROOT / "docs/source/_static/ui" / name).is_file()


@pytest.mark.parametrize("name", ["pv-storage-flow", "ev-service-window"])
def test_feature_diagrams(name):
    path = ROOT / "assets/images" / (name + ".svg")
    svg = ET.parse(path).getroot()
    assert svg.find("{http://www.w3.org/2000/svg}title") is not None
    assert f"../assets/images/{name}.svg" in (ROOT / "docs/features.md").read_text(encoding="utf-8")


def test_load_environment_notebook(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    notebook = json.loads((ROOT / "examples/load_environment.ipynb").read_text(encoding="utf-8"))
    scope = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            code = "".join(cell["source"])
            if code.startswith("%pip"):
                continue
            exec(compile(code, "load_environment.ipynb", "exec"), scope)
            assert not cell["outputs"]
    assert Path(scope["schema_filepath"]).is_file()
    assert scope["env"].central_agent is True


@pytest.mark.parametrize("name", ["quickstart", "load_environment", "cli"])
def test_tutorials_have_no_stale_outputs(name):
    notebook = json.loads((ROOT / "examples" / f"{name}.ipynb").read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell["outputs"] == []
            assert cell["execution_count"] is None


def test_v3_citation_added_alongside_v2():
    bibliography = (ROOT / "docs/source/references.bib").read_text(encoding="utf-8")
    entry = re.search(r"@misc\{fonseca2026citylearnv3,\n(.*?)\n\}", bibliography, re.S)
    assert entry is not None
    fields = dict(re.findall(r"^\s*(\w+)\s*=\s*\{(.*)\},?$", entry[1], re.M))
    assert fields["eprint"] == "2609.21570"
    assert fields["year"] == "2026"
    assert fields["url"] == "https://arxiv.org/abs/2609.21570"
    assert fields["author"].split(" and ") == [
        "Fonseca, Tiago", "Ferreira, Luis Lino", "Sousa, Armando",
        "Mohammadi, Ava", "Nagy, Zoltan",
    ]
    assert "@article{doi:10.1080/19401493.2024.2418813," in bibliography
    index = (ROOT / "docs/source/index.rst").read_text(encoding="utf-8")
    assert "@article{doi:10.1080/19401493.2024.2418813," in index
    assert ":start-at: @misc{fonseca2026citylearnv3," in index
    assert "fonseca2026citylearnv3" in (ROOT / "docs/source/publications.rst").read_text(encoding="utf-8")
