"""Publish the canonical Markdown guides without maintaining duplicate copies."""

from pathlib import Path
import ast
import importlib.util
import re
import sys
from urllib.parse import urlsplit


def load_kpi_registry(root):
    path = root / "citylearn/internal/kpi_registry.py"
    spec = importlib.util.spec_from_file_location("_citylearn_kpi_registry", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scorecard_names(root):
    tree = ast.parse((root / "citylearn/internal/kpi.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "SCORECARD_DEFAULT_KPIS":
                return ast.literal_eval(node.value)
    raise RuntimeError("SCORECARD_DEFAULT_KPIS was not found")


DATASET_ORIGINS = (
    # (name prefix, description); the first matching prefix wins.
    ("citylearn_challenge_2022_phase_all_plus_evs", "CityLearn Challenge 2022 buildings with EVs; the quickstart dataset"),
    ("citylearn_challenge_2022_phase_all_demand_response", "CityLearn Challenge 2022 buildings with demand-response requests"),
    ("citylearn_challenge_2022_phase_all_robustness", "CityLearn Challenge 2022 buildings with robustness events"),
    ("citylearn_challenge_2020", "CityLearn Challenge 2020"),
    ("citylearn_challenge_2021", "CityLearn Challenge 2021"),
    ("citylearn_challenge_2022", "CityLearn Challenge 2022"),
    ("citylearn_challenge_2023", "CityLearn Challenge 2023"),
    ("citylearn_three_phase", "Feature demonstration"),
    ("pt_rec_", "Portuguese renewable energy community ([Portugal REC datasets](portugal_rec_datasets.md))"),
    ("", "Neighbourhood"),
)
PARQUET_SUFFIXES = (".parquet", ".pq", ".parq")


def _schema_values(node, key):
    """Every value stored under `key` anywhere in a schema."""
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                yield value
            yield from _schema_values(value, key)
    elif isinstance(node, list):
        for value in node:
            yield from _schema_values(value, key)


def _enabled(section):
    return isinstance(section, dict) and bool(section.get("enabled", False))


def _duration(seconds):
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


def dataset_catalogue_rows(root):
    """One row per public dataset, read from its schema and files."""
    import json

    rows = []
    for directory in sorted((root / "data/datasets").iterdir()):
        path = directory / "schema.json"
        if not path.is_file():
            continue
        schema = json.loads(path.read_text(encoding="utf-8"))
        files = [file for file in directory.rglob("*") if file.is_file()]
        buildings = schema.get("buildings", {})
        step = int(schema["seconds_per_time_step"])
        rows_in_window = int(schema["simulation_end_time_step"]) - int(schema["simulation_start_time_step"]) + 1
        building_types = [str(b.get("type", "")) for b in buildings.values() if isinstance(b, dict)]
        features = []
        if schema.get("electric_vehicles_def"):
            features.append("EVs")
        if any(_schema_values(buildings, "deferrable_appliances")):
            features.append("flexible appliances")
        if any(_schema_values(buildings, "electrical_storage")):
            features.append("batteries")
        if any(value for key in ("cooling_storage", "heating_storage", "dhw_storage")
               for value in _schema_values(buildings, key)):
            features.append("thermal storage")
        if any(isinstance(limits, dict) and limits.get("per_phase") for limits in _schema_values(buildings, "limits")):
            features.append("phase limits")
        if _enabled(schema.get("demand_response")):
            features.append("demand response")
        if any(value is True for key in ("simulate_power_outage", "stochastic_power_outage")
               for value in _schema_values(buildings, key)):
            features.append("power outages")
        if _enabled(schema.get("community_market")):
            features.append("community market")
        if schema.get("topology_mode") == "dynamic" or schema.get("topology_events"):
            features.append("dynamic topology")
        if _enabled(schema.get("robustness")):
            features.append("robustness events")
        if any("Dynamics" in name for name in building_types) or any(file.suffix == ".pth" for file in files):
            features.append("LSTM thermal dynamics (PyTorch)")
        origin = next(text for prefix, text in DATASET_ORIGINS if directory.name.startswith(prefix))
        rows.append({
            "name": directory.name,
            "origin": origin,
            "buildings": len(buildings),
            "evs": len(schema.get("electric_vehicles_def") or {}),
            "step": _duration(step),
            "days": rows_in_window*step/86400,
            "format": "Parquet (pyarrow)" if any(file.suffix in PARQUET_SUFFIXES for file in files) else "CSV",
            "size_mb": sum(file.stat().st_size for file in files)/1.0e6,
            "features": features,
        })
    return rows


def dataset_catalogue(root):
    lines = [
        "# Dataset catalogue", "",
        "This table is generated from the bundled schemas when the documentation is built.",
        "Pass a name to `CityLearnEnv` to download and cache the dataset on first use; the size",
        "is the download. *Default window* is the schema's simulation window, which",
        "`simulation_start_time_step`, `simulation_end_time_step` and `episode_time_steps` can shorten.",
        "Parquet datasets need `pip install \"citylearn[parquet]\"`, and datasets with LSTM thermal",
        "dynamics need PyTorch; see the [installation guide](../installation.rst).", "",
        "## Where to start", "",
        "- **First runs and controller comparisons:** `citylearn_challenge_2022_phase_all_plus_evs`,",
        "  used by the [quickstart](../quickstart.rst).",
        "- **Electrical limits, dynamic topology and sub-minute data:** the `citylearn_three_phase_*`",
        "  demonstrations; see the [features guide](features.md).",
        "- **Renewable energy communities with a local market:** `pt_rec_4` first, then `pt_rec_15`,",
        "  `pt_rec_30` and `pt_rec_100`.",
        "- **Demand response and robustness:** `citylearn_challenge_2022_phase_all_demand_response` and",
        "  `citylearn_challenge_2022_phase_all_robustness`.", "",
        "## All public datasets", "",
        "| Dataset | Origin | Buildings | EVs | Step | Default window | Format | Size | Features |",
        "|---|---|---:|---:|---:|---:|---|---:|---|",
    ]
    for row in dataset_catalogue_rows(root):
        days = row["days"]
        window = f"{days:.0f} days" if days >= 1.5 else f"{days*24:.0f} h"
        size = f"{row['size_mb']:.0f} MB" if row["size_mb"] >= 1 else "< 1 MB"
        lines.append(
            f"| `{row['name']}` | {row['origin']} | {row['buildings']} | {row['evs']} | {row['step']} | {window} "
            f"| {row['format']} | {size} | {', '.join(row['features']) or '-'} |"
        )
    lines += ["", "See the [dataset reference](dataset_reference.md) to build your own dataset.", ""]
    return "\n".join(lines)


def website_guide_content(content):
    """Keep repository translations out of the English-only website."""
    content = re.sub(r"^Portuguese version:.*\n\n?", "", content, flags=re.MULTILINE)
    # The website copy lives two levels deeper than the canonical Markdown file.
    return content.replace("(../assets/", "(../../../assets/")


def scorecard_kpi_page(root):
    names = scorecard_names(root)
    registry = load_kpi_registry(root)
    lines = [
        "# Default scorecard KPI names", "",
        "This table is generated from `SCORECARD_DEFAULT_KPIS` and the KPI metadata registry",
        "at documentation build time. See [How to read the scorecard](scorecard.md)",
        "for interpretation and [KPI reference](kpis_reference.md) for equations.",
        "The full evaluation table contains additional KPIs; see the [complete KPI catalogue](kpi_catalogue.md).", "",
    ]
    for level in ("district", "building"):
        lines += [
            "## " + level.capitalize(), "",
            "| KPI | Unit | Description |",
            "|---|---|---|",
        ]
        for name in names:
            if name.startswith(level + "_"):
                unit, description = registry.resolve_kpi_metadata(name)
                lines.append(f"| `{name}` | `{unit}` | {description} |")
        lines.append("")
    return "\n".join(lines)


def kpi_catalogue(root):
    registry = load_kpi_registry(root)
    lines = [
        "# Complete KPI catalogue", "",
        "This page is generated from `citylearn.internal.kpi_registry` when the documentation is built.",
        "Every row returned by `evaluate_v2()`, `scorecard()` and `MultiCommunityEnv.evaluate_v2()`",
        "resolves its `unit` and `description` columns from this registry.", "",
        "## Canonical units", "",
        "| Unit | Meaning |",
        "|---|---|",
    ]
    for unit, meaning in registry.KPI_UNITS.items():
        lines.append(f"| `{unit}` | {meaning} |")
    lines.append("")

    for level in ("district", "building", "portfolio"):
        entries = [
            item for item in registry.KPI_REGISTRY.values()
            if item.level == level and item.cost_function != "topology_lifecycle_presence"
        ]
        lines += [f"## {level.capitalize()} KPIs", ""]
        families = sorted({item.family for item in entries})
        for family in families:
            lines += [
                f"### `{family}`", "",
                "| KPI | Unit | Description |",
                "|---|---|---|",
            ]
            for item in sorted((e for e in entries if e.family == family), key=lambda x: x.cost_function):
                lines.append(f"| `{item.cost_function}` | `{item.unit}` | {item.description} |")
            lines.append("")

    lifecycle = registry.get_kpi_definition("topology_lifecycle_presence")
    lines += [
        "## Dynamic topology lifecycle placeholder", "",
        "| KPI | Unit | Description |",
        "|---|---|---|",
        f"| `{lifecycle.cost_function}` | `{lifecycle.unit}` | {lifecycle.description} |",
        "",
    ]
    return "\n".join(lines)


def prepare_guides(app):
    root = Path(app.confdir).parents[1]
    source = root / "docs"
    destination = Path(app.srcdir) / "guides"
    destination.mkdir(exist_ok=True)
    for path in sorted(source.glob("*.md")):
        if path.name == "retired_datasets.md":
            continue
        content = website_guide_content(path.read_text(encoding="utf-8"))
        (destination / path.name).write_text(content, encoding="utf-8")
    (destination / "scorecard_kpi_names.md").write_text(scorecard_kpi_page(root), encoding="utf-8")
    (destination / "kpi_catalogue.md").write_text(kpi_catalogue(root), encoding="utf-8")
    (destination / "dataset_catalogue.md").write_text(dataset_catalogue(root), encoding="utf-8")


def setup(app):
    app.connect("builder-inited", prepare_guides)
    app.connect("html-page-context", guide_source_link)
    app.connect("doctree-resolved", local_site_links)
    return {"version": "1", "parallel_read_safe": True, "parallel_write_safe": True}


def guide_source_link(app, pagename, templatename, context, doctree):
    """Point edit links at maintained sources, not generated guide copies."""
    if not pagename.startswith("guides/"):
        return
    if pagename in ("guides/scorecard_kpi_names", "guides/kpi_catalogue", "guides/dataset_catalogue"):
        context["display_github"] = False
    else:
        context["meta"] = dict(context.get("meta") or {})
        context["meta"]["github_url"] = (
            "https://github.com/citylearn-project/CityLearn/blob/master/docs/"
            + pagename.removeprefix("guides/") + ".md"
        )


def local_site_links(app, doctree, docname):
    """Keep canonical website links inside local/offline documentation builds."""
    from docutils import nodes

    if app.builder.format != "html":
        return
    for node in doctree.findall(nodes.reference):
        url = urlsplit(node.get("refuri", ""))
        if url.netloc not in ("www.citylearn.net", "citylearn.net"):
            continue
        target = url.path.lstrip("/")
        target = target[:-5] if target.endswith(".html") else target
        target = target or "index"
        if target in app.env.found_docs and not url.query:
            node["refuri"] = app.builder.get_relative_uri(docname, target)
            if url.fragment:
                node["refuri"] += "#" + url.fragment
