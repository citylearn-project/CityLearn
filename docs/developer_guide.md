# Developer Guide

This page collects local development commands, validation checks, performance smoke tests and the current internal architecture map.

Portuguese version: [pt/developer_guide.md](pt/developer_guide.md).

## Local Environment

Create an isolated environment from a repository checkout:

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r test_requirements.txt
python -m pip install -e .
```

Optional dependencies:

| Feature | Command |
|---|---|
| Parquet datasets | `.venv/bin/pip install pyarrow` |
| PV autosizing | `.venv/bin/pip install ".[pysam]"` |
| Build checks | `.venv/bin/pip install build twine` |

## Core Validation

| Check | Command |
|---|---|
| Full test suite | `.venv/bin/pytest -q` |
| Critical lint | `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci --select E9,F821` |
| Entity contract audit | `.venv/bin/python scripts/audit/audit_entity_contract.py --strict` |
| Physics audit | `.venv/bin/python scripts/audit/audit_physics.py` |
| Diff whitespace check | `git diff --check` |

The physics audit intentionally exercises resolution conversion paths, so unit-conversion warnings can be expected when the audit fixture forces dataset/schema mismatches.

## Manual Simulation Scripts

Manual utility scripts live in `scripts/manual` and are excluded from default pytest collection.

```console
.venv/bin/python scripts/manual/demo_ev_rbc.py
.venv/bin/python scripts/manual/demo_ev_rbc_export_end.py
```

Runtime benchmark:

```console
.venv/bin/python scripts/manual/bench_runtime.py --seconds 5 60 --render-modes none end --episode-steps 1200
```

CI performance smoke check:

```console
.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --baseline-file scripts/ci/perf_baseline.json
```

Step/component profiling:

```console
.venv/bin/python scripts/audit/profile_step_breakdown.py --episode-steps 300 --seconds 60 --agent rbc --interface flat --render-mode none --no-write --table-limit 14
```

Lifecycle and KPI/BAU profiling:

```console
.venv/bin/python scripts/audit/profile_lifecycle.py --episode-steps 300 --seconds 60 --skip-exports --no-write
```

Drop `--skip-exports` when the CSV export paths themselves need to be timed.

For ad hoc code, pass `debug_timing=True` to `CityLearnEnv` and inspect `info` keys such as `apply_actions_time`, `reward_observations_time`, `next_observations_time`, `terminal_export_time` and `step_total_time`.

## Internal Architecture

Public APIs remain centered on `CityLearnEnv` and `Building`. Internal orchestration is split into service modules under `citylearn/internal`.

| Module | Responsibility |
|---|---|
| `loading.py` | Schema-driven loading and building assembly. |
| `runtime.py` | Episode runtime orchestration, `step`, action parsing, time progression and EV/charger association. |
| `building_ops.py` | Building observation/action orchestration. |
| `kpi.py` | KPI/evaluation pipeline. |
| `entity_interface.py` | Entity tables, edges, action specs and observation bundles. |

## Build and check the documentation

The canonical English guides are `docs/*.md`. The Sphinx extension copies them
into the generated `docs/source/guides/` directory at build time, preserving
cross-links and publishing the same text as the repository. Do not edit the
generated directory. The scorecard name list is generated from the runtime
selection. Historical releases appear under Project, not in the README.

```console
python -m pip install -r docs/requirements.txt
sphinx-apidoc citylearn -o docs/source/api -e -M
sphinx-build -b html docs/source docs/build/html
python scripts/ci/check_docs.py docs/build/html
python -m pytest -q tests/test_documentation_examples.py
```

Install Pandoc for the retained notebook tutorials. Use the `sphinx-build`
executable: the current CLI reference detects that executable when returning
its argument parser. Documentation examples are tested separately; the site
build does not train learning agents.

## Development rules

| Rule | Reason |
|---|---|
| Keep schema/API changes documented in the same change. | Algorithms and datasets depend on explicit contracts. |
| Add tests for new physics or observations. | Sub-hourly and entity behavior are easy to regress silently. |
| Prefer additive observations in patch releases. | Avoid breaking trained algorithms and wrappers. |
| Run audits before tagging. | They catch contract drift outside normal unit tests. |

## Verification and internal modules in 3.1

Run `python scripts/audit/run_full_audit.py --strict --output-dir /tmp/citylearn-audit`
to verify physics, entity contracts, official datasets and six fixed-command
reference trajectories. Missing dependencies/scripts, child failures and reference
drift fail verification; ordinary runs do not rewrite snapshots. Algorithm audits
remain explicit opt-in tools. Reference tests generate small temporary cases from
existing fixtures; no SoftCPS production datasets are included.

Public facades delegate to focused internal modules for energy/equipment/service/
community KPIs, entity observation/layout preparation, loading inputs/components
and robustness contracts/auditing. Electrical-service allocation is shared by
control and runtime. Public imports, executable examples and the official registry
retain CityLearn identity; internal modules are not stable extension APIs.
