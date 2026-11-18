# Releases

Changes, compatibility, validation and measured performance for the current
CityLearn release. Older notes are retained in the [release archive](releases_archive.md).

Portuguese version: [pt/releases.md](pt/releases.md).

For package publication, version policy and the release checklist, see the
[publishing guide](publishing.md).

## Unreleased

### Added

- **Reward for load left unserved during power outages.** During an outage a building cannot import, so its net consumption is zero and rewards built on grid import give no signal about the load that PV and storage leave unserved. `OutageUnservedEnergyReward(coefficient, base_reward)` subtracts `coefficient` times that unserved energy from a base reward, and the new flat observation `power_outage_unserved_energy` (kWh per step, last settled step) gives it per building with the definition of the `power_outage_normalized_unserved_energy_total` KPI ([#188](https://github.com/citylearn-project/CityLearn/issues/188)). The reward works under both interfaces; the observation is flat only. Both are opt-in, so existing schemas and results are unchanged.
- **Time-varying available grid power.** `buildings.<name>.electrical_service.available_grid_power` references a per-step series of the power a building may import, in kW, from a file with one column per building or a named column ([#119](https://github.com/citylearn-project/CityLearn/issues/119)). The import limit in force at a step is the smaller of the static `limits.total.import_kw` and the series value, and every reader of the total import limit uses it: the electrical-service allocation (EV chargers and the battery are curtailed first; fixed load stays served and counts as a violation), deferrable start feasibility, the headroom observations, the EV feasibility KPI and the electrical-service violation KPI. A limit of 0 kW does not island the building; outages stay in `power_outage`. The new flat observation `available_grid_power` reports the limit for the coming interval when a series is set, and the rule-based baselines cap their planned import headroom with it. Buildings without a series are unchanged. See the [schema reference](schema_reference.md#available-grid-power).

### Changed

- **Baselines read corrupted observations under the flat interface.** Under the flat interface the env corrupts only the flat vectors, and the baselines, which read entity observations, decided from uncorrupted values; under the entity interface they read the corrupted ones ([#192](https://github.com/citylearn-project/CityLearn/issues/192)). Run as controllers (`predict(observations)`), they now get the step's robustness observation events applied to their entity observations as the entity interface applies them, and take the same actions under both interfaces. No random stream is consumed, and the env's flat observations and robustness history are unchanged; the controller KPIs of flat runs with observation events can change. The native BAU reference of `evaluate_v2()` (`predict([])`) stays uncorrupted. See the [migration guide](migration.md#unreleased).

### Fixed

- **Robustness noise.** With `noise_std > 0`, Gaussian noise could make solar generation, solar irradiance and carbon intensity negative, add generation at night and push outdoor relative humidity outside [0, 100] %. One rule now bounds the noisy values: solar quantities stay `>= 0` and get no noise at night, humidity stays within [0, 100] % and carbon intensity stays `>= 0`. The noise draws are unchanged, so values within range are bit-identical. Solar generation noise uses the generation series for its shape instead of the indoor temperature series; both have the same length, so the draws are the same. Runs with `noise_std = 0`, including all bundled datasets, are unchanged. See the [migration guide](migration.md#unreleased).
- **15 s Parquet datasets load from the dataset cache.** The schemas of `citylearn_three_phase_electrical_service_demo_15s_parquet`, `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet` and `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet` set a repository-relative `root_directory`. Passing the schema path returned by `DataSet().get_dataset(name)` to `CityLearnEnv` resolved it against the cache folder and raised `FileNotFoundError` for `<cache>/<dataset>/data/datasets/<dataset>/Building_1.parquet` ([#194](https://github.com/citylearn-project/CityLearn/issues/194)). The three schemas now set `"root_directory": null`, like the other datasets. `CityLearnEnv(name)` and schema paths inside a repository checkout already found the files and still read the same folder.

The Parquet fix leaves input files and simulation results unchanged; no migration is required.

## v3.5.0 - 2026-11-17

### What's new

- **Portugal REC datasets.** Four synthetic Portuguese renewable energy communities with 4, 15, 30 and 100 residential and commercial members, 2023-2024 at 15 minutes: `pt_rec_4`, `pt_rec_15`, `pt_rec_30` and `pt_rec_100`. Nine main scenarios add membership changes, restricted import limits, grid interruptions, equipment faults, missing observations and demand response. Six comparison scenarios remove individual conditions. They are edition v3.4 of the dataset article *Synthetic electricity demand and flexibility datasets for Portuguese energy communities*, released under CC BY 4.0; series calculated from public sources carry the attribution of each source. See the [Portugal REC datasets](portugal_rec_datasets.md) guide.
- **Nested dataset folders.** `DataSet.get_dataset()` now downloads a dataset's subfolders; it previously fetched only the top-level files. A download costs two GitHub API requests however deeply the dataset is nested, and the files come from raw.githubusercontent.com. Set `CITYLEARN_GITHUB_TOKEN` or `GITHUB_TOKEN` to raise the anonymous limit of 60 API requests per hour. The contents listing now uses the account and repository given to `DataSet`.

No dataset, schema, export or BAU migration is required; existing datasets and KPIs are unchanged. See the [migration guide](migration.md#upgrade-from-340-to-350).

### Validation

CityLearn ships the 983 files that the schemas read (216 MB), each byte-identical to the v3.4 dataset package; its data tables, provenance records and checksums stay in the dataset deposit. The inventories match the article. On the 3.4.0 runtime, all 19 Portugal schemas (four dataset roots, nine main and six comparison scenarios) ran a one-week episode (672 steps) with `BusinessAsUsualAgent` and `evaluate_v2()` including the native BAU reference. Each week was the one with the most topology, robustness and demand-response events in the scenario, or a July week when it has none; peak memory was 1.7 GB. Unit tests cover nested, path-checked and token-authenticated downloads, and a real download of a nested dataset by name from GitHub loaded in CityLearn.

### Credits

The datasets are by Fonseca et al.; **Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)) integrated them in CityLearn.

[Full changelog](https://github.com/citylearn-project/CityLearn/compare/v3.4.0...v3.5.0)

## v3.4.0 - 2026-11-16

### What's new

- **Two selectable BAUs.** `BusinessAsUsualAgent` charges a connected EV at once and at full power, to 100% by default (`immediate-full-charge-v2`). With `ev_charge_target='requested'` (`immediate-user-target-v1`) it charges only up to the user's requested departure SOC; the last command is limited to the remaining energy gap, and below the charger minimum the EV stops slightly short of the target instead of overshooting it. `business_as_usual_ev_charge_target` (constructor or schema) selects which one `evaluate_v2()` uses as the KPI reference. The previous Basic, Smart and Community controllers and the names `NormalPolicy`, `NormalNoBatteryPolicy`, `ServiceOnlyBaselineAgent`, `GridAwareBaselineAgent` and `CommunityAwareBaselineAgent` are removed.
- **Basic, Smart and Community baselines.** `RBCBasicPolicy`, `RBCSmartPolicy` and `RBCCommunityPolicy` are replaced by the baselines validated in the Soft-CPS Algorithms repository. Basic uses the current price and service urgency. Smart schedules EVs and appliances from price and local PV-surplus forecasts and combines battery self-consumption, arbitrage and reserve. Community adds shareable member energy and, with the community market enabled, battery support during expensive periods once community import reaches 15 kW.
- **Unlimited headroom is no longer 0 kW.** In the entity tables, a building without an electrical service limit publishes its headroom as 1,000,000 kW (the observation bound) instead of 0 kW, which read as "no capacity left" and stopped rule-based EV charging.
- **One observation contract.** All baselines decide from the named entity observations and run under the flat and the entity interface, including dynamic topology. Keyword arguments set any policy parameter; unknown names raise an error. Experiment manifests record the definition version and resolved parameters.

BAU-relative KPIs change with the new reference. Rerun the controller and its reference together; see the [migration guide](migration.md#upgrade-from-33-to-340) and the [baselines guide](baselines.md).

### Validation

On the same observations, the CityLearn baselines request exactly the same actions as the Algorithms policies (commit `725a72a`) at every step, for both BAUs, Basic, Smart and Community, on three bundled datasets (EVs, three-phase limits with a community market, dynamic topology).

On 30 days of `citylearn_challenge_2022_phase_all_plus_evs`, the default BAU delivers the same EV energy as the 3.3.1 BAU (7,512 kWh) and costs 4.8% more (2,723 € vs 2,598 €): its battery reacts to the last observed step instead of reading the current step from the simulator. The user-target BAU costs 2,290 € and delivers 4,797 kWh. Basic, Smart and Community meet the minimum acceptable SOC at every feasible departure.

### Credits

**Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)) developed and validated the baselines in the Soft-CPS Algorithms repository and ported them to CityLearn in [#189](https://github.com/citylearn-project/CityLearn/pull/189).

[Full changelog](https://github.com/citylearn-project/CityLearn/compare/v3.3.1...v3.4.0)

## v3.3.1 - 2026-11-16

### Fixed

- **Native BAU reference with entity-only robustness targets.** `evaluate_v2()` no longer raises `ValueError: robustness event ... target does not match any declared observation target` on entity schemas with static topology whose robustness observation events target `ev`, `storage` or `pv` tables. The BAU reference env now uses the entity interface whenever the evaluated env does, as it already did for dynamic topology and demand response.

The BAU agent reads simulator state directly, so its actions and KPIs do not depend on the interface; on 13 Portugal schemas the reference KPIs were bit-identical before and after the change. No dataset, schema or export migration is required. See the [migration guide](migration.md#upgrade-from-330-to-331).

### Validation

A regression test covers an EV SOC robustness event on a static entity schema evaluated with the native BAU reference. The full test suite and the release CI matrix passed.

### Credits

**Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)) ported the fix from SoftCPS Simulator 2.1.1.

[Full changelog](https://github.com/citylearn-project/CityLearn/compare/v3.3.0...v3.3.1)

## v3.3.0 - 2026-11-13

### What's new

- **Battery and EV physics.** Activation respects the configured SOC below the discharge reserve. EVs retain their identity and evolve through charger removal, re-entry and handover. Accounting includes standby losses, mobility and explicit arrival energy. CSV and Parquet exports report the charger that actually served the EV.
- **BAU and KPIs.** Native BAU uses matching equipment, PV, actions and outages, including the same stochastic outages. Cost and net-exchange ratios, market comparisons and portfolio aggregation are corrected. Repeated evaluation retains only the latest BAU reference.
- **Compatibility and robustness.** Support NumPy 1 and 2 and legacy occupant models. Resume SAC and MARLISA training from 3.2.0 checkpoints. Keep EV session IDs, publish complete dataset caches atomically and make experiment evidence portable across checkouts.

Public dataset files and export layouts are preserved. If your scenario uses the corrected paths, rerun both the controller and its reference for comparisons. See the [migration guide](migration.md#upgrade-from-320-to-330).

### Validation

The integrated runtime passed the [CI matrix](https://github.com/citylearn-project/CityLearn/actions/runs/43354734920) on Python 3.9, 3.10 and 3.12, covering NumPy 1 and 2, runtime audits and installed-wheel exports. The battery and EV regression tests cover one-hour and 15-minute steps.

### Credits

Thanks to **Mark Colley** ([@M-Colley](https://github.com/M-Colley)) for the cross-platform, BAU, NumPy, KPI, EV arrival, agent and dataset-cache fixes in [#170](https://github.com/citylearn-project/CityLearn/pull/170)–[#175](https://github.com/citylearn-project/CityLearn/pull/175). **Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)) and the **CityLearn maintainers** reviewed, validated and integrated those changes, added matched stochastic outages, completed the EV session-ID and MARLISA fixes, and developed the battery reserve and EV lifecycle corrections in [#179](https://github.com/citylearn-project/CityLearn/pull/179) and [#180](https://github.com/citylearn-project/CityLearn/pull/180).

[Full changelog](https://github.com/citylearn-project/CityLearn/compare/v3.2.0...v3.3.0)

## v3.2.0 - 2026-11-06

Release maintainer: **Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)).
Simulator changes contributed by **Mark Colley** in [PR #169](https://github.com/citylearn-project/CityLearn/pull/169).

- Support Gymnasium 1.x alongside 0.28.1. Stacked wrappers and agents use the
  environment's public attribute access. The CLI starts without Stable-Baselines3.
- Return simulated indoor temperatures to agents using LSTM dynamics. Use
  deterministic LSTM inference, correct periodic and occupant observations,
  and reset action feedback, constraint violations and dynamic series at each episode.
- Convert LSTM heating and cooling actions, thermal storage and autosizing
  between dataset and control resolutions. Count initial thermal storage
  discharge once, and support outage signals in partial-day episodes.
- Keep the energy provenance ledger enabled by default. When disabled, skip
  optional provenance KPIs and carry the setting into BAU and the export manifest.
  CSV and partitioned Parquet, BAU control logic and dataset files are retained.
- Return one float per building for per-building reward functions. See the
  [migration guide](migration.md#upgrade-from-311-to-320) for the required
  indexing change, corrected trajectories and optional EULP dependencies.
- Reduce observation preparation for LSTM inference and use scalar clipping
  on frequently executed paths. The minute-encoding regression test reads a
  short window of the same 15-second dataset.

### Validation and performance

The runtime passed CI on Python 3.9 and 3.10, the installed-wheel export smoke
and the Sphinx build. The runtime audit covered 16 physical scenarios (12,000
intervals), 32 official dataset probes, entity contracts and six fixed-command
reference cases. Six real exports opened in the CityLearn UI. The two controlled
comparisons matched all 10,274 KPI records and retained the same BAU series and
scorecards.

| Bounded case | Mean step before → after (ms) | Peak process RSS before → after (MiB) |
|---|---:|---:|
| EVs, 400 steps | 7.27 → 7.24 | 637.95 → 636.25 |
| LSTM, 120 steps | 2.47 → 2.27 | 646.88 → 646.97 |
| Dynamic topology, 1,840 steps | 11.90 → 11.25 | 655.30 → 654.55 |

The table gives medians of three runs against the pre-merge 3.1.1 development
head, with identical inputs, fixed commands and physical checks enabled. The
dynamic case applied all five events at the same steps, and KPI evaluation
took 2.36 → 2.26 seconds. These measurements cover the stated windows.

## v3.1.1 - 2026-11-04

Release owner: **Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)).

- Honor explicit `random_episode_split=True` and `False` constructor overrides;
  `None` continues to inherit the schema setting (PR #166).
- Compound the configured hourly standby-loss fraction over the physical step,
  independently of dataset cadence (PR #164). A 1% hourly loss now leaves 99%
  after one hour at both hourly and 15-minute resolution, within float precision.
- Convert dataset energy to average step power when autosizing heat pumps,
  electric heaters and batteries. Battery daily peaks use physical 24-hour
  periods. Thermal storage capacity remains energy for one control step.
- Preserve public energy-command interfaces, explicit equipment settings, BAU
  control logic, KPI definitions, dataset files and export schemas. Subhourly SOC,
  derived KPIs and automatically selected equipment may change because of the
  corrections; no file migration is required. See [migration notes](migration.md#upgrade-from-310-to-311).
- Simplify user documentation and correct tutorial prose/docstring typos (PR #154),
  retaining notebook execution logic, stored outputs and metadata.

Validation of the corrected runtime: 1,249 tests, 16 physical scenarios, 32 bounded
official-dataset checks, entity contracts and six fixed-command reference cases
passed. The reviewed standby reference reproduces the old baseline exactly when
only the old loss formula is restored; hourly reference results are unchanged.
Release CI, distribution checks and installed-package evidence accompany the
GitHub release. No new annual campaign, equipment calibration or performance
improvement is claimed for this patch. The 3.1.0 performance evidence below remains
historical evidence for that release.

## v3.1.0 - 2026-11-02

Release owner and integration maintainer: **Tiago Fonseca**
([@calofonseca](https://github.com/calofonseca)).

### Summary

Integrates the validated runtime improvements from SoftCPS Simulator 2.0.0 into
CityLearn, with CityLearn package identity, interfaces and official datasets
preserved. Production CPS datasets and working audit notes are not imported.

### Fixed and added

- Shared outage energy budgets across simultaneous EV chargers, conservative
  battery reserves and applied single/three-phase service limits.
- Independent energy/cash balance checks, EV departure and deferrable-service
  ledgers, executed-window KPI populations, family coverage and temporal evidence.
- Robustness composition, missing-input validation, input fingerprints and
  versioned experiment comparison/export manifests.
- Internal loading, observation, electrical-limit and KPI responsibilities split
  into focused modules while retaining public entry points.
- Local schema roots resolve independently of the working directory, including
  the existing repository-relative Parquet schemas.
- Strict physics, entity, dataset and fixed-command audits; generic regression
  tests and installed-wheel export checks in CI and before publication.

### Performance evidence

Local medians of three repetitions on three existing official datasets, with
physics checks enabled, fixed zero commands, one BLAS thread, 1,200 / 1,400 /
1,200 transitions and current topology-aware action shapes. The market is
explicitly enabled; robustness events are extended in temporary copies only.
These are bounded integration measurements, not annual whole-catalog timings.

The optimization comparison uses the **corrected functional integration before
optimization**, with the same additional audits and KPI coverage:

| Case | Step, ms before → after | KPI evaluation, s before → after | RSS after evaluation, MiB before → after |
|---|---:|---:|---:|
| Static, flat | 6.304 → 6.162 (−2.3%) | 2.241 → 1.168 (−47.9%) | 658 → 641 |
| Dynamic topology, entity | 9.965 → 9.235 (−7.3%) | 7.225 → 1.653 (−77.1%) | 668 → 646 |
| Sustained robustness events, entity | 15.449 → 13.442 (−13.0%) | 1.683 → 0.724 (−57.0%) | 1,365 → 662 (−51.5%) |

- Compact market storage: 18.26 → 2.29 MB (static/robust), 22.45 →
  2.75 MB (dynamic), approximately 87% less retained storage.
- Robustness storage in the sustained-event case: 699.61 → 13.72 MB,
  98.0% less. Public history reconstruction remains available on demand.
- All 16,737 KPI rows across the three cases and every energy/cost trace are
  exactly equal before and after optimization, in all three repetitions.
- Changes include compact lossless histories, batched EV feasibility replay,
  reusable KPI populations, indexed deferrable cycles and cached observation /
  forecast preparation. Missing values retain their meaning.
- **Compared directly with original 3.0.2**, mean step times are 5.298 →
  6.162 ms (static), 8.885 → 9.235 ms (dynamic) and 14.548 → 13.442 ms
  (robust). KPI output grows from 2,099 / 2,227 / 2,243 to 5,427 / 5,739 /
  5,571 rows. The added checks and coverage have a cost: this release is not
  faster in every case than 3.0.2. Host load and allocator behavior affect timings.
- RAM measurements cover initialization through KPI evaluation, before deep
  storage inspection or reconstructing public histories. Raw measurements and
  the benchmark protocol accompany the GitHub release.

### Dataset and compatibility impact

- All 32 existing official datasets and existing data/test fixtures/assets are
  unchanged: 1,254 protected files verified by SHA-256. No dataset/schema
  migration is required; retired datasets remain retired.
- Distribution/import: `citylearn`; registry: `citylearn-project/CityLearn`
  at tag `v3.1.0`. CSV, partitioned Parquet and KPI sidecar exports are retained.
- The native BAU is now explicitly **immediate-full-charge-v1**: request maximum
  available EV charging to 100%, share electrical capacity proportionally and
  perform no PV, tariff or departure-target scheduling. Constructor order is
  retained; custom target/deadline EV options now raise a clear error and belong
  in configurable RBC policies. This deliberately changes historical BAU requests.
- Corrected functional KPI/accounting results can differ from 3.0.2. Use
  matching-version references. See the [migration guide](migration.md#upgrade-from-302-to-310).

### Validation and limits

- Complete local suite: **1,138 passed**, no failures or skips (44 Gymnasium float32 precision warnings).
- Strict runtime audits: 16/16 physical scenarios; 32/32 official datasets in
  bounded supported-interface probes; entity contracts; six fixed-command
  reference cases. No reference snapshot updates were needed.
- Critical lint, wheel/source builds and `twine check`: passed.
- Isolated installed-wheel KPI, BAU, provenance and service-sidecar export: passed.
- Documentation: 208 HTML pages, 19,096 local links/assets, zero link errors
  (40 retained Sphinx warnings).
- Benchmark: 27 successful runs, 34,200 transitions, active physical checks and
  exact functional/optimized KPI and energy/cost parity in all repetitions.

The physical models are validated by deterministic checks and simulated inputs;
this release does not claim calibration against real equipment, successful
annual runs of every official dataset or that every requested EV departure SOC
is physically attainable. Existing infeasible service events remain visible.

Earlier releases, with their original validation notes: [release archive](releases_archive.md).
