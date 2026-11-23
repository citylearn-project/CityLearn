# Contributing to CityLearn

Thank you for considering a contribution to CityLearn. This page explains how to
report a problem or ask a question, how to set up a development environment, and
what a pull request needs before it can be merged. Every contributor follows the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Questions, bugs and ideas

Open an [issue](https://github.com/citylearn-project/CityLearn/issues/new/choose)
and choose the template that fits: a bug report, a feature request or a usage
question. A bug report is most useful when it states the CityLearn, Python and
NumPy versions, the dataset or schema, and the shortest code that reproduces the
problem, together with the full error message. Before you open a question, check
the [documentation](https://www.citylearn.net), whose installation page lists the
optional dependencies, the dataset cache and the offline settings.

## Development environment

CityLearn requires Python 3.10 or newer. Create an isolated environment from a
clone of the repository and install the package in editable mode with the test
dependencies:

```console
git clone https://github.com/citylearn-project/CityLearn.git
cd CityLearn
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r test_requirements.txt
python -m pip install -e .
```

The test dependencies include PyTorch, because the suite covers LSTM thermal
dynamics and the SAC and MARLISA controllers. Without a GPU, install the CPU-only
PyTorch first, which avoids several GB of CUDA libraries:

```console
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Parquet datasets need `pyarrow` and PV autosizing needs NREL-PySAM; the
[developer guide](docs/developer_guide.md) lists these optional dependencies.

## Tests

The unit tests run in about a minute and cover most of the simulator, so run
them while you work:

```console
python -m pytest -q tests/unit
```

Before you open a pull request, run the full suite. It takes several minutes on
one process; with `pytest-xdist` installed, `-n 4` runs it on four processes:

```console
python -m pytest -q
python -m pytest -q -n 4
```

pytest.ini sets a 600 s timeout per test (`pytest-timeout`), so a hung test
fails instead of blocking CI; the slowest tests take about two minutes.
`python -m pytest -q --cov=citylearn --cov-report=term` prints the coverage
(`pytest-cov`); a separate workflow (`.github/workflows/coverage.yml`) reports
it weekly and on manual dispatch without slowing down pull-request checks.
`tests/test_property_energy_conservation.py` uses `hypothesis` to draw step
lengths, physics and settlement versions, outages, phase limits, topology events
and every action of short episodes, and checks the physics invariants and the
independent energy, cash and carbon balances. The search is derandomized, so a
failure reproduces locally; Hypothesis prints the falsifying example.

CI also runs the linter with the rules selected in `pyproject.toml`
(`[tool.ruff.lint]`); run the same command before you push:

```console
python -m ruff check citylearn tests scripts/manual scripts/ci
```

Changes to the physics, the KPIs or the entity interface should also pass the
audits that CI runs:

```console
python scripts/audit/run_full_audit.py --strict --output-dir audit-output
```

## Documentation

The guides are Markdown files in `docs/` and the site is built with Sphinx from
`docs/source/`. The [developer guide](docs/developer_guide.md#build-and-check-the-documentation)
shows how to build and check it. The example notebooks in `examples/` are
published on the site and executed in CI; keep their episodes short, commit them
without outputs, and check them with:

```console
python -m pip install nbclient nbformat ipykernel
python scripts/ci/run_notebooks.py
```

## Pull requests

1. Open the pull request against `master` and link the issue it addresses.
2. Sign off every commit (`git commit -s`): the Developer Certificate of Origin
   check fails without a `Signed-off-by` line.
3. Add tests for new behaviour, and a regression test for every bug fix.
4. State whether simulated results or KPIs change. A change of results on the
   bundled datasets needs a versioned setting or definition that keeps the
   earlier behaviour available, and an entry in the migration guide.
5. Add an entry under `Unreleased` in `docs/releases.md`, and in
   `docs/pt/releases.md` for user-facing changes, and update the guides that
   describe the changed behaviour.
6. Keep each pull request to one topic, so that it can be reviewed and reverted
   on its own.

CI runs the lint, the test suite on Python 3.10 to 3.14 (and NumPy 1 on Python
3.10), an installation on macOS and Windows, the runtime audits and the example
notebooks. A maintainer reviews the pull request once CI is green.
