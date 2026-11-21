"""Update the versions.json of the published documentation site (#296).

The site root ``/`` (and ``/stable/``) serves the latest final (non-prerelease) release so the public Documentation
link, the site home, and existing links to individual documentation pages open the latest stable release by default.
Each release tag ``v<version>`` is also published under ``/<version>/``, and the ``master`` development documentation
is published under ``/dev/``. ``versions.json`` lists these entries for the top selector and the left-sidebar
**Other versions** navigation (``docs/source/_static/version_switcher.js``).

Usage: python scripts/ci/update_versions.py [--existing OLD.json] --output NEW.json [--add VERSION]
Prints ``stable=<version>`` and ``is_stable=true|false`` (whether ``--add`` is the latest final release) for CI.
"""

import argparse
import json
from pathlib import Path

from packaging.version import InvalidVersion, Version


def release_versions(entries):
    """Release versions in a versions.json, as strings."""

    found = []

    for entry in entries:
        try:
            Version(entry['version'])

        except (InvalidVersion, KeyError):
            continue  # "stable" and "dev" are generated

        found.append(entry['version'])

    return found


def build_entries(versions):
    """Return versions.json entries: stable (at site root ``''``), releases newest-first, and ``dev/``."""

    ordered = sorted(set(versions), key=Version, reverse=True)
    stable = next((v for v in ordered if not Version(v).is_prerelease), None)
    entries = []

    if stable is not None:
        entries.append({'name': f'stable ({stable})', 'version': 'stable', 'path': ''})

    entries.extend({'name': v, 'version': v, 'path': f'{v}/'} for v in ordered)
    entries.append({'name': 'dev (master)', 'version': 'dev', 'path': 'dev/'})

    return entries, stable


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--existing', type=Path, help='versions.json of the published site, if any.')
    parser.add_argument('--add', help='Release version to add, without the leading "v".')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    existing = []

    if args.existing and args.existing.is_file():
        existing = release_versions(json.loads(args.existing.read_text(encoding='utf-8')))

    if args.add is not None:
        Version(args.add)  # fail early on malformed tags
        existing.append(args.add)

    entries, stable = build_entries(existing)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(entries, indent=2) + '\n', encoding='utf-8')
    print(f'stable={stable or ""}')
    print(f'is_stable={"true" if args.add is not None and args.add == stable else "false"}')


if __name__ == '__main__':
    main()
