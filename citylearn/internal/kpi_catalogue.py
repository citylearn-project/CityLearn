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


# Statuses a catalogue entry may declare; rows named as a replacement are `canonical`, the others `current`.
DECLARED_STATUSES = ("legacy", "deprecated")
STATUSES = ("current", "canonical", "legacy", "deprecated")


def load(path=None):
    source = files("citylearn").joinpath("misc", "kpi_catalogue.yml") if path is None else Path(path)
    families = yaml.safe_load(source.read_text(encoding="utf-8"))
    for family in families:
        for kpi in family["kpis"]:
            kpi["expanded"] = expand(kpi["names"])
            unknown = set(kpi["levels"]) - {"building", "district"}
            if unknown:
                raise ValueError(f"{kpi['names']}: unknown levels {sorted(unknown)}")
            status, replacement = kpi.get("status"), kpi.get("replacement")
            if status is None and replacement is None:
                continue
            if status not in DECLARED_STATUSES or not replacement:
                raise ValueError(f"{kpi['names']}: status must be one of {DECLARED_STATUSES} with a replacement")
            replacements = expand(replacement)
            if len(replacements) not in (1, len(kpi["expanded"])):
                raise ValueError(f"{kpi['names']}: replacement {replacement} does not expand to one name per name")
            kpi["replacements"] = dict(zip(kpi["expanded"], replacements * len(kpi["expanded"])
                                           if len(replacements) == 1 else replacements))
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


def statuses(families):
    """Full KPI name -> (status, full replacement name or None)."""
    entries = kpi_entries(families)
    result = {}
    for family in families:
        for kpi in family["kpis"]:
            for name, replacement in (kpi.get("replacements") or {}).items():
                for level in kpi["levels"]:
                    full, target = f"{level}_{name}", f"{level}_{replacement}"
                    if target not in entries:
                        raise ValueError(f"{full}: replacement {target} is not in the catalogue")
                    result[full] = (kpi["status"], target)
    for status, target in list(result.values()):
        if target in result:
            raise ValueError(f"{target} is a replacement but is itself {result[target][0]}")
        result.setdefault(target, ("canonical", None))
    return {name: result.get(name, ("current", None)) for name in entries}


@lru_cache(maxsize=1)
def _metadata():
    families = load()
    status = statuses(families)
    return {
        name: (kpi["unit"], " ".join(kpi["en"].split()), *status[name])
        for name, (_, kpi) in kpi_entries(families).items()
    }


def _portfolio(name):
    """The district name of a portfolio row, which shares its catalogue entry."""
    return "district_" + name[len("portfolio_"):] if name.startswith("portfolio_") else name


def kpi_status(name):
    """Return the status (`current`, `canonical`, `legacy` or `deprecated`) and the replacement of a KPI.

    The replacement is the full name of the canonical row for `legacy` and `deprecated` rows, else None. A
    portfolio row takes the status of its district row and a portfolio replacement. Unknown names give
    (None, None).
    """
    if not isinstance(name, str):
        return None, None
    _, _, status, replacement = _metadata().get(_portfolio(name), (None, None, None, None))
    if replacement is not None and name.startswith("portfolio_"):
        replacement = "portfolio_" + replacement[len("district_"):]
    return status, replacement


def kpi_metadata(name):
    """Return unit and English description. Unknown extension KPIs have empty metadata."""
    if not isinstance(name, str):
        return None, None
    return _metadata().get(_portfolio(name), (None, None))[:2]


def kpi_definitions(names):
    """Manifest definitions for the catalogued KPIs present in an export."""
    definitions = {}
    for name in names:
        unit, description = kpi_metadata(name)
        if unit is not None:
            status, replacement = kpi_status(name)
            definitions[name] = {"unit": unit, "description": description, "status": status,
                                 "replacement": replacement}
    return definitions


METADATA_COLUMNS = ("unit", "description", "status", "replacement")


def attach_kpi_metadata(table):
    """Insert the metadata columns (unit, description, status, replacement) after the four KPI columns."""
    definitions = {name: (*kpi_metadata(name), *kpi_status(name)) for name in table["cost_function"].unique()}
    for index, column in enumerate(METADATA_COLUMNS):
        table.insert(4 + index, column, table["cost_function"].map({
            name: metadata[index] for name, metadata in definitions.items()
        }))
    return table
