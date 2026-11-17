"""The installation guide's version compatibility table must describe the current release (#150)."""

import csv
from pathlib import Path
import re

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from citylearn import __version__

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT/'docs'/'source'/'installation.rst'
# requirements.txt package -> table column holding its version specifier ("any" when unpinned).
COLUMNS = {'numpy': 'NumPy', 'scikit-learn': 'scikit-learn', 'torch': 'PyTorch'}


def table_rows():
    text = GUIDE.read_text(encoding='utf-8')
    block = text.split('.. csv-table::', 1)[1]
    lines = block.splitlines()[1:]
    header = next(line for line in lines if line.strip().startswith(':header:'))
    rows = []

    for line in lines[lines.index(header) + 1:]:
        if line.strip() == '':
            if rows:
                break
            continue
        if not line.startswith('   '):
            break
        rows.append(line.strip())

    columns = next(csv.reader([header.split(':header:', 1)[1].strip()], skipinitialspace=True))
    return [dict(zip(columns, values)) for values in csv.reader(rows, skipinitialspace=True)]


def current_row():
    current = Version(__version__)

    for row in table_rows():
        versions = [Version(v) for v in re.findall(r'\d+\.\d+\.\d+', row['CityLearn'])]
        if versions[0] <= current <= versions[-1]:
            return row

    raise AssertionError(f'No row of the compatibility table in {GUIDE} covers CityLearn {__version__}.')


def python_requires():
    for name in ('setup.py', 'pyproject.toml'):
        path = ROOT/name
        if path.is_file():
            match = re.search(r"""(?:python_requires|requires-python)\s*=\s*['"]([^'"]+)['"]""", path.read_text(encoding='utf-8'))
            if match:
                return match.group(1)

    raise AssertionError('No python_requires found')


def requirements():
    lines = (ROOT/'requirements.txt').read_text(encoding='utf-8').splitlines()
    return [Requirement(line.strip()) for line in lines if line.strip() and not line.strip().startswith('#')]


def test_table_rows_are_complete_and_ordered():
    rows = table_rows()
    assert len(rows) >= 7
    assert all(len(row) == 9 and all(value.strip() for value in row.values()) for row in rows)
    starts = [Version(re.findall(r'\d+\.\d+\.\d+', row['CityLearn'])[0]) for row in rows]
    assert starts == sorted(starts, reverse=True)


def test_current_release_row_matches_the_package_requirements():
    # Update the table in docs/source/installation.rst whenever a release changes its requirements.
    row = current_row()
    assert row['Python'] == python_requires()
    pinned = {requirement.name.lower(): requirement for requirement in requirements()}

    for name, column in COLUMNS.items():
        specifier = pinned[name].specifier if name in pinned else SpecifierSet()
        documented = SpecifierSet() if row[column] == 'any' else SpecifierSet(row[column])
        assert documented == specifier, (column, row[column], str(specifier))

    gymnasium = Requirement(row['Gym / Gymnasium'])
    assert gymnasium.name == 'gymnasium'
    assert gymnasium.specifier == pinned['gymnasium'].specifier

    others = [r for name, r in pinned.items() if name not in COLUMNS and name != 'gymnasium' and r.specifier]
    for requirement in others:
        assert str(requirement) in row['Other pins'], requirement

    if not others:
        assert row['Other pins'].startswith('none')
