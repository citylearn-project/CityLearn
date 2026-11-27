"""Generate the KPI catalogue pages from citylearn/misc/kpi_catalogue.yml.

The catalogue lists every KPI name that `evaluate_v2()` emits, grouped by family, with a one-line
definition in English and Portuguese. The equations live in the KPI reference pages, which the
catalogue links to. `tests/test_kpi_catalogue.py` checks that the catalogue covers every emitted
name and that the committed pages match this generator.

Usage:
    python scripts/docs/kpi_catalogue.py          # rewrite docs/KPI_V2_TREE.md and docs/pt/KPI_V2_TREE.md
    python scripts/docs/kpi_catalogue.py --check  # exit 1 if they are out of date
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from citylearn.internal.kpi_catalogue import kpi_entries, load  # noqa: E402

PAGES = {"en": ROOT / "docs" / "KPI_V2_TREE.md", "pt": ROOT / "docs" / "pt" / "KPI_V2_TREE.md"}

TEXT = {
    "en": {
        "title": "KPI catalogue",
        "intro": [
            "This page lists every KPI name that `evaluate_v2()` emits, grouped by family, with a short",
            "definition. It is generated from `citylearn/misc/kpi_catalogue.yml` by `scripts/docs/kpi_catalogue.py`,",
            "and a test checks that every name the simulator emits is listed here. The equations, the",
            "district aggregation and the undefined-value rules of each family are in the",
            "[KPI reference](kpis_reference.md), which each family links to.",
            "",
            "Names read `<level>_<family>_<subfamily>_<metric>[_<variant>]_<unit>`. The level is",
            "`building` or `district`; `MultiCommunityEnv` adds `portfolio` rows built from the district",
            "rows (see [Levels](kpis_reference.md#levels)). In the tables, `{a,b}` stands for each",
            "alternative and `{,_x}` for an optional part; the full names follow each table.",
            "Which rows appear depends on the scenario's assets and services.",
            "",
            "Rows marked **Legacy** keep an older definition so earlier results stay comparable, and rows marked",
            "**Deprecated** return the same value as another row; both name the canonical row to report instead.",
            "`evaluate_v2()` gives each row its `status` (`current`, `canonical`, `legacy` or `deprecated`) and",
            "`replacement`, and export manifests record them in `kpi_definitions`.",
        ],
        "legacy": "**Legacy**; canonical row: `{replacement}`.",
        "deprecated": "**Deprecated** alias of `{replacement}`.",
        "family": "Family",
        "names": "Names",
        "levels": "Levels",
        "unit": "Unit",
        "meaning": "Meaning",
        "formulas": "Equations and rules",
        "reference": "kpis_reference.md",
        "all_names": "All {count} names",
    },
    "pt": {
        "title": "Catálogo de KPIs",
        "intro": [
            "Esta página lista todos os nomes de KPI que `evaluate_v2()` emite, agrupados por família, com",
            "uma definição curta. É gerada a partir de `citylearn/misc/kpi_catalogue.yml` por",
            "`scripts/docs/kpi_catalogue.py`, e um teste verifica que todos os nomes que o simulador emite",
            "constam daqui. As equações, a agregação ao distrito e as regras de valores indefinidos de cada",
            "família estão na [referência de KPIs](kpis_reference.md), para a qual cada família remete.",
            "",
            "Os nomes seguem `<nível>_<família>_<subfamília>_<métrica>[_<variante>]_<unidade>`. O nível é",
            "`building` ou `district`; `MultiCommunityEnv` acrescenta linhas `portfolio` construídas a",
            "partir das linhas de distrito (ver [Níveis](kpis_reference.md#níveis)). Nas tabelas, `{a,b}`",
            "representa cada alternativa e `{,_x}` uma parte opcional; os nomes completos seguem cada tabela.",
            "As linhas presentes dependem dos equipamentos e serviços do cenário.",
            "",
            "As linhas marcadas **Legada** mantêm uma definição anterior para que resultados antigos continuem",
            "comparáveis, e as marcadas **Obsoleta** devolvem o mesmo valor que outra linha; ambas indicam a linha",
            "canónica a reportar. `evaluate_v2()` dá a cada linha o seu `status` (`current`, `canonical`, `legacy`",
            "ou `deprecated`) e `replacement`, e os manifestos das exportações registam-nos em `kpi_definitions`.",
        ],
        "legacy": "**Legada**; linha canónica: `{replacement}`.",
        "deprecated": "**Obsoleta**, alias de `{replacement}`.",
        "family": "Família",
        "names": "Nomes",
        "levels": "Níveis",
        "unit": "Unidade",
        "meaning": "Significado",
        "formulas": "Equações e regras",
        "reference": "kpis_reference.md",
        "all_names": "Todos os {count} nomes",
    },
}


def documented_names(families):
    """Full KPI name -> family id, for every building and district name of the catalogue."""
    return {name: family for name, (family, _) in kpi_entries(families).items()}


def anchor(title):
    """GitHub and MyST heading slug."""
    slug = re.sub(r"[^\w\- ]", "", title.lower(), flags=re.UNICODE).strip().replace(" ", "-")
    return slug


def _cell(text):
    return " ".join(str(text).split()).replace("|", "\\|")


def render(families, language):
    text = TEXT[language]
    names = documented_names(families)
    lines = [f"# {text['title']}", "", *text["intro"], ""]
    lines += [f"| {text['family']} | {text['names']} |", "|---|---:|"]
    for family in families:
        count = sum(1 for family_id in names.values() if family_id == family["id"])
        title = family["title"][language]
        lines.append(f"| [{title}](#{anchor(title)}) | {count} |")
    lines.append("")
    for family in families:
        title = family["title"][language]
        lines += [f"## {title}", "", " ".join(family["intro"][language].split()), ""]
        lines += [f"{text['formulas']}: [{title}]({text['reference']}#{anchor(title)}).", ""]
        lines += [
            f"| {text['names']} | {text['levels']} | {text['unit']} | {text['meaning']} |",
            "|---|---|---|---|",
        ]
        for kpi in family["kpis"]:
            meaning = _cell(kpi[language])
            if kpi.get("status"):
                meaning = text[kpi["status"]].format(replacement=kpi["replacement"]) + " " + meaning
            lines.append(
                f"| `{kpi['names']}` | {', '.join(kpi['levels'])} | {kpi['unit']} | {meaning} |"
            )
        full = sorted(name for name, family_id in names.items() if family_id == family["id"])
        lines += [
            "", "<details>", f"<summary>{text['all_names'].format(count=len(full))}</summary>", "",
            "```text", *full, "```", "", "</details>", "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed pages are out of date")
    args = parser.parse_args()
    families = load()
    stale = []
    for language, path in PAGES.items():
        page = render(families, language)
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != page:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(page, encoding="utf-8")
    if stale:
        print("Out of date, run python scripts/docs/kpi_catalogue.py: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
