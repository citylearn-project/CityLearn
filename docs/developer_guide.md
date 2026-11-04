# Developer Guide

Set up a development environment, run regression checks and profile the runtime.
For simulation-level checks and published measurements, start with
[Validation and performance](validation.md).

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

### Evaluation progress

`env.evaluate_v2(progress_callback=callback)` optionally reports scalar stage events
without adding timings to the KPI table or its attributes. Each event includes a
sequence number, stage, status and elapsed seconds. Member stages and their equipment
families also include the member ID, index and total. Completed/failed stages include
the stage duration. Observers receive fresh dictionaries; they must avoid slow I/O
and must not mutate the environment. A failing observer is logged and disabled;
actual evaluation errors still propagate with failed-stage events.

The long-run auditor writes `phase` in `summary.json`, the latest KPI stage in
`evaluation-progress.json` and the event history in `evaluation-progress.jsonl`.
It distinguishes loading, dispatch, final evaluation, KPI export, reconciliation
and evidence export. `kpi_evaluation_seconds` excludes export/reconciliation;
`final_kpi_and_export_seconds` retains its existing combined meaning. Progress is
reported at stage boundaries, so a long individual family may stay active for some
time. No background thread or per-step callback is installed by KPI reporting.

### Market settlement history

The internal settlement history stores binary64 numeric columns and member IDs,
with offsets for each executed interval. No rows are sampled or rounded. Indexing,
slicing and iteration expose ordinary per-step lists of dictionaries as detached
snapshots; assign an edited step back to persist it. Use a slice to read a window
or iterate to stream the history, rather than materializing an entire long run.
The current-step settlement and export schemas are unchanged. Legacy rows with
additional/missing fields are retained in full. Market KPI totals are accumulated
in chronological order and rebuilt after historical edits. Reset clears both
history and totals.

### Robustness application journal

The sparse robustness journal retains every recorded application and its order.
Completed steps use integer references to shared descriptions; the current step
keeps writable sets for identical deduplication. Summaries accumulate completed
steps and handle unexecuted terminal telemetry separately. No numeric channel
values, RNG state, event application rules or physical state are changed.
`env._robustness_service.history` keeps its complete public dictionary contract.
For bounded reads, use `history_window(start, stop)` or `iter_history(start, stop)`
on that service; bounds are global step indices, start inclusive and stop exclusive.
These window/stream records are detached snapshots. Reset clears journal and
summary counters together. The bounded action-delay buffer remains unchanged.

### KPI active populations

Dynamic KPI evaluation snapshots sparse membership transitions and lifecycle
metadata once. Nested KPI families reuse read-only masks keyed by member, series
horizon and semantics. Energy masking retains absent intervals as zero; thermal
selection removes absent samples. Completed intervals still exclude the terminal
observation, and historical assets continue to use their existing readers.
The scope includes environment, episode window, executed horizon, history identity
and topology version. It refreshes if those change and releases masks after each
evaluation, including exceptions; no physical values or KPI results are cached.
Public topology queries still return independent lists with their original rules.

### EV departure replay reuse

Departure feasibility compares target, minimum acceptable and tolerance thresholds
against one maximum-charge replay per departure/context. The existing single-
threshold helper remains available. Legacy and audited batches stay separate: their
arrival boundaries and outage rules can differ. The replay still runs through the
whole connection interval, including losses after a target may have been reached.
Physical charge/efficiency/taper/capacity/deadband/service-limit rules are unchanged.
Missing-input permissive legacy results and audited unknown classifications keep
their existing contracts. No memo or replay battery is retained between batches,
sessions, evaluations or episodes; only the departure endpoint is shared within
the three comparisons. Native BAU actions and real battery histories are untouched.
