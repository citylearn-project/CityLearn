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

`test_requirements.txt` installs PyTorch and scikit-learn, which the tests of
LSTM thermal dynamics and of the SAC and MARLISA controllers need. Without a
GPU, run `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu`
first to avoid several GB of CUDA libraries. Ray RLlib is not a test
dependency: the RLlib wrappers import it only when it is installed.

Optional dependencies:

| Feature | Command |
|---|---|
| Parquet datasets | `.venv/bin/pip install -e ".[parquet]"` |
| PV autosizing | `.venv/bin/pip install -e ".[pysam]"` |
| Parallel tests | `.venv/bin/pip install pytest-xdist` |
| Coverage report (`--cov=citylearn`) and the 600 s per-test timeout of `pytest.ini` | `.venv/bin/pip install pytest-cov pytest-timeout` (both are in `test_requirements.txt`) |
| Property-based energy-conservation tests | `.venv/bin/pip install hypothesis` (in `test_requirements.txt`; `tests/test_property_energy_conservation.py` skips without it) |
| Notebook checks | `.venv/bin/pip install nbclient nbformat ipykernel` |
| RLlib wrappers | `.venv/bin/pip install "ray[rllib]"` (tested with Ray 2.60.0; `tests/test_rllib_wrappers.py` skips without it) |
| Build checks | `.venv/bin/pip install build twine` |

## Portable experiment evidence

`.gitattributes` makes every checkout byte-identical to the repository: text
files use LF and files under `data/` and `tests/data/` are never converted, even
with Git for Windows' default `core.autocrlf=true`. Experiment manifests hash
these files, so the hashes then agree on all platforms. A checkout made before
`.gitattributes` existed may still hold CRLF copies; `git status` lists converted
data files as modified. Make a fresh clone and set it up as in
[Local Environment](#local-environment): the clone applies the new checkout
rules and leaves the existing working copy, including uncommitted changes,
untouched. The dataset cache keys local copies by the content of their files, so
copies made from the old checkout are not read; clear it to free the space they
take:

```console
git clone https://github.com/citylearn-project/CityLearn.git
python -c "from citylearn.data import DataSet; DataSet().clear_cache()"
```

Manifests record each input file by its path below the dataset root, with `/`
separators, so a moved or copied dataset keeps its evidence. On Windows, where
`\` and `/` are both separators and file names ignore case, a reference that
differs from the file's path only in separators or case records the file's
on-disk spelling: with the dataset root `C:\data\demo` and the file
`C:\data\demo\sub\weather.csv`, the references `sub\Weather.csv`,
`SUB/weather.csv` and `C:\Data\Demo\sub\WEATHER.csv` all record
`sub/weather.csv`. Other spellings of an input file keep their text, with `/`
for `\` on Windows: `.` or `..` components, repeated separators, links, 8.3
short names and files outside the dataset root. Strings that are not hashed
input files (see `FILE_TYPES` in `citylearn/internal/temporal.py`) keep their
text without the dataset root. On Linux and macOS every reference keeps its
text, without the dataset root; macOS file names ignore case by default, but the
evidence does not. If two runs spell one file in ways that are not normalised,
the comparison reports `incompatible` rather than a pair.

## Core Validation

| Check | Command |
|---|---|
| Fast subset (about one minute) | `.venv/bin/pytest -q tests/unit` |
| Full test suite (several minutes; `-n 4` with pytest-xdist) | `.venv/bin/pytest -q` |
| Example notebooks | `.venv/bin/python scripts/ci/run_notebooks.py` |
| Lint (rules in `pyproject.toml`, as in CI) | `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci` |
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
.venv/bin/python scripts/ci/perf_smoke.py --require-baseline
```

It times the 2022 `plus_evs` dataset (flat, flat with end rendering and entity, 60 s step on hourly data),
`pt_rec_4` at its native step with `time_step_ratio_mode='reject'` and the physics invariant checks on, and the
construction of the whole 15 s Parquet electrical-service dataset. The gates are loose; the thresholds are the
script's defaults and `scripts/ci/perf_baseline.json` stores only measurements. CI writes the ratio of every
metric to its baseline to the job summary. Re-record the baseline once per release with `--write-baseline`;
`--cases` limits a run (or a re-recording) to some cases. Constructing the 15 s dataset needs about 6 GB of memory.

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
its argument parser. Documentation examples are tested separately.

The notebooks in `examples/` are stored without outputs. The Sphinx workflow
executes them before the build (`python scripts/ci/run_notebooks.py --output-dir examples`,
which overwrites the sources in that checkout only) and runs
`check_docs.py --require-notebook-outputs`, so the published notebook pages show
the outputs of that run, including a short RL training run. To reproduce it
locally, run these two commands and discard the changes in `examples/` afterwards
(`git checkout examples`). Without the execution step the pages show the code only.

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

CI runs the physics audit, the official dataset audit, and the entity contract and
refactor parity audits as three parallel jobs (`audit (physics)`, `audit (datasets)`,
`audit (entity-contract-and-refactor-parity)`), each with `--strict` and its own
`--audits` selection. Each job uploads its JSON evidence as
`citylearn-runtime-audits-<name>`, and the `runtime-audits` job fails unless all
three pass.

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
