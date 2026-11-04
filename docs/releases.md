# Releases

Changes, compatibility, validation and measured performance for the current
CityLearn release. Older notes are retained in the [release archive](releases_archive.md).

Portuguese version: [pt/releases.md](pt/releases.md).

For package publication, version policy and the release checklist, see the
[publishing guide](publishing.md).

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
