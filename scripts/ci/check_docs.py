"""Check links and assets in the built site without network requests."""

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Pages rendered from the notebooks in examples/ (docs/source/usage/*.nblink).
NOTEBOOK_PAGES = [
    "usage/agents.html",
    "usage/load_environment.html",
    "usage/cli.html",
    "usage/rl_training.html",
    "usage/rllib_training.html",
]


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.nb_outputs = 0
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "nboutput" in (attrs.get("class") or "").split():
            self.nb_outputs += 1
        for key in (("id", "name") if tag == "a" else ("id",)):
            if attrs.get(key):
                self.ids.add(attrs[key])
        for key in ("href", "src"):
            if attrs.get(key):
                self.links.append(attrs[key])


def check_site(root, notebook_outputs=False):
    root = root.resolve()
    pages = {
        path.resolve(): Page(path.read_text(encoding="utf-8"))
        for path in root.rglob("*.html")
    }
    errors = set()
    checked = 0
    for source, page in pages.items():
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                if url.netloc not in ("www.citylearn.net", "citylearn.net"):
                    continue
                target = root / unquote(url.path).lstrip("/")
            elif url.path.startswith("/"):
                target = root / unquote(url.path).lstrip("/")
            else:
                target = source.parent / unquote(url.path) if url.path else source
            target = target.resolve()
            if target.is_dir():
                target /= "index.html"
            checked += 1
            if not target.is_file():
                errors.add(f"{source.relative_to(root)}: missing target {link}")
            elif url.fragment and target in pages:
                fragment = unquote(url.fragment)
                if fragment not in pages[target].ids and not fragment.startswith(":~:text="):
                    errors.add(f"{source.relative_to(root)}: missing anchor {link}")
    required = [
        "index.html", "quickstart.html", "installation.html",
        "guides/features.html", "guides/scorecard.html",
        "guides/scorecard_kpi_names.html", "guides/kpis_reference.html",
        "guides/releases.html", "_images/citylearn-v3-overview.png",
        "guides/baselines.html", "kpis.html", "ui.html", "publications.html",
        "usage/custom_controller.html", "_images/pv-storage-flow.svg",
        "_images/ev-service-window.svg", "_images/v3-timeseries.png",
        "_images/v3-scorecard.png",
        "overview/index.html", "_images/dr.jpg",
        "glossary.html", "guides/dataset_catalogue.html", "python_api.html", "guides/KPI_V2_TREE.html",
    ]
    for name in required:
        if not (root / name).is_file():
            errors.add(f"Required site asset missing: {name}")
    if notebook_outputs:
        for name in NOTEBOOK_PAGES:
            page = pages.get((root / name).resolve())
            if page is None:
                errors.add(f"Notebook page missing: {name}")
            elif not page.nb_outputs:
                errors.add(f"Notebook page has no outputs: {name}")
    for name in ("guides/pt", "guides/retired_datasets.html", "api/citylearn.internal.html"):
        if (root / name).exists():
            errors.add(f"Removed website section still published: {name}")
    return len(pages), checked, sorted(errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path, help="Sphinx HTML build directory")
    parser.add_argument(
        "--require-notebook-outputs", action="store_true",
        help="Fail when a notebook page has no outputs (the notebooks were not executed before the build)",
    )
    args = parser.parse_args()
    if not args.site.is_dir():
        parser.error(f"Not a site directory: {args.site}")
    pages, links, errors = check_site(args.site, args.require_notebook_outputs)
    for error in errors:
        print(error)
    print(f"Documentation: {pages} HTML pages, {links} local links/assets, {len(errors)} errors")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
