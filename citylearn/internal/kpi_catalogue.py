"""Read the shared catalogue of KPI names, units and descriptions."""

import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import yaml


def expand(pattern):
    """Expand brace alternatives, including optional parts such as `{,_delta}`."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if match is None:
        return [pattern]
    head, tail = pattern[:match.start()], pattern[match.end():]
    return [name for option in match.group(1).split(",") for name in expand(head + option + tail)]


def load(path=None):
    source = files("citylearn").joinpath("misc", "kpi_catalogue.yml") if path is None else Path(path)
    families = yaml.safe_load(source.read_text(encoding="utf-8"))
    for family in families:
        for kpi in family["kpis"]:
            kpi["expanded"] = expand(kpi["names"])
            unknown = set(kpi["levels"]) - {"building", "district"}
            if unknown:
                raise ValueError(f"{kpi['names']}: unknown levels {sorted(unknown)}")
    return families


def kpi_entries(families):
    """Index full names by family and catalogue entry."""
    entries = {}
    for family in families:
        for kpi in family["kpis"]:
            for name in kpi["expanded"]:
                full_names = [name] if name.startswith("topology_") else [
                    f"{level}_{name}" for level in kpi["levels"]
                ]
                for full_name in full_names:
                    if full_name in entries:
                        raise ValueError(f"{full_name} is listed twice")
                    entries[full_name] = (family["id"], kpi)
    return entries


@lru_cache(maxsize=1)
def _metadata():
    return {
        name: (kpi["unit"], " ".join(kpi["en"].split()))
        for name, (_, kpi) in kpi_entries(load()).items()
    }


def kpi_metadata(name):
    """Return unit and English description. Unknown extension KPIs have empty metadata."""
    if not isinstance(name, str):
        return None, None
    if name.startswith("portfolio_"):
        name = "district_" + name[len("portfolio_"):]
    return _metadata().get(name, (None, None))


def kpi_definitions(names):
    """Manifest definitions for the catalogued KPIs present in an export."""
    definitions = {}
    for name in names:
        unit, description = kpi_metadata(name)
        if unit is not None:
            definitions[name] = {"unit": unit, "description": description}
    return definitions


def attach_kpi_metadata(table):
    """Insert the metadata columns after the original four KPI columns."""
    definitions = {name: kpi_metadata(name) for name in table["cost_function"].unique()}
    for index, column in enumerate(("unit", "description")):
        table.insert(4 + index, column, table["cost_function"].map({
            name: metadata[index] for name, metadata in definitions.items()
        }))
    return table
