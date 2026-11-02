# Releases

Release notes for the official CityLearn v3 line appear first. Older entries
record the Soft-CPS development line integrated into v3; they are not a
replacement for the historical CityLearn v1/v2 changelogs.

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

## v3.0.2 - 2026-09-09

Release owner: [@calofonseca](https://github.com/calofonseca).

### Changed

- Removed the 19 `ALADI` datasets, the five `rec_2023_*` datasets and
  `EC_Ermesinde` from the public dataset registry and release tag.
- The supported runtime capabilities remain available; only those public data
  artifacts and their repository-bound EC Ermesinde integration test were
  retired.

### Dataset/Schema Impact

- Default discovery now returns 32 public datasets.
- Existing users that depend on a removed dataset must provide their own local
  schema and files rather than resolving it from the official registry.

### Compatibility

- No Python API change. The package and import name remain `citylearn`.

### Validation

- Full local suite: 457 tests passed.
- Critical lint rules: passed.
- Wheel and source archive build plus `twine check`: passed.
- Repository scan: 32 discoverable datasets and no retired dataset names.

## v3.0.1 - 2026-09-09

Release owner: [@calofonseca](https://github.com/calofonseca).

### Fixed

- Points the installed package's default dataset registry at the official
  `citylearn-project/CityLearn` repository and matching release tag. Version
  3.0.0 incorrectly retained the Simulator fork as its default registry.
- Installs `twine` in the dedicated PyPI publication job before upload.

### Validation

- Clean PyPI installation with full runtime dependencies.
- Remote dataset discovery against the official Version 3 tag.
- Environment reset and simulation-step smoke test using a downloaded dataset.

## v3.0.0 - 2026-09-09

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

- Promotes the complete Soft-CPS Simulator development line into the official
  CityLearn repository as the new Version 3 baseline.
- Unifies the official `citylearn` distribution with the extended runtime,
  datasets, documentation, audits and regression suite previously maintained
  in the fork.

### Major Capabilities

- Flat and entity interfaces, dynamic topology and multi-community orchestration.
- Sub-hourly physics, EV/BESS/PV and deferrable-asset modeling.
- Single/three-phase electrical-service constraints and local market settlement.
- KPI v2, robust export contracts, perturbation scenarios and annual REC benchmarks.

### Dataset/Schema Impact

- Adds the datasets and schema extensions maintained in the Simulator fork.
- Existing CityLearn 2.x schemas remain supported where covered by the regression suite;
  users of new capabilities should review the Version 3 schema and unit contracts.

### Compatibility and Migration

- The distribution name is `citylearn`; the Python import path remains `citylearn`.
- Replace `softcpsrecsimulator` dependency pins with `citylearn==3.0.0` when moving
  workloads from the fork to the official package.
- This is a major release. Downstream users should validate KPI/export consumers and
  custom schemas before upgrading production workflows.

### Validation

- Full validation results are recorded in `RELEASE_NOTES_3.0.0.md` before publication.

## v1.8.0 - 2026-08-22

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

- Minor release introducing the canonical annual REC benchmark suite and the
  runtime, topology and KPI contracts required to evaluate it reproducibly.
- Separates controller-request pressure from post-projection electrical-service
  violations, so constraint activation is no longer reported as an applied-power
  safety failure.

### Added

- Four deterministic 2023 quarter-hour REC dataset families: `MICRO-4-Q`,
  `CORE-15-STRIPPED`, `CORE-30` and `PREMIUM-100`, comprising nine clean,
  safety, health, dynamic and combined schemas.
- A reproducible annual-suite generator using official 2023 Portuguese OMIE
  day-ahead prices, together with structural, scientific, diversity,
  deterministic-regeneration and execution-smoke audits.
- Separate member, physical-charger, EV and charging-session identities;
  multiple chargers per member; deferrable-service contracts; Portuguese
  connection-power and phase-headroom surrogates; settlement and grid-only
  counterfactuals.
- Causal daily-persistence load/PV forecasts and publication-aware OMIE price
  forecasts for benchmark schemas.
- Optional `terminal_observation_padding`, providing one observation-only
  boundary after the requested control intervals for complete terminal service
  accounting.
- Historical dynamic-asset aggregation for charger, stationary-storage and
  deferrable KPIs, including remove/reinstall lifecycles.
- `*_electrical_service_phase_requested_pressure_energy_total_kwh` and
  `*_electrical_service_phase_requested_pressure_event_count` KPI v2 rows.
- EV connected-SOC-gain and energy-accounting-shortfall evidence.
- Causal tests for a clipped controllable request and for a structurally
  infeasible non-controllable load.
- Regression coverage requiring asset-unavailability KPIs to count one
  physical asset once per affected time step, independently of how many entity
  features and action ports expose the outage.

### Changed

- Dynamic topology now replays pre-window events at the episode boundary,
  initializes newly activated members and assets without simulating omitted
  history, skips expired deferrable requests and preserves prior runtime
  instances for end-of-episode evidence.
- EV arrival and departure accounting now respects explicit session identity,
  back-to-back sessions and terminal departures. Current-SOC telemetry is used
  as a connection-boundary reference and does not overwrite controlled SOC
  trajectories.
- Derived entity forecasts can select causal persistence instead of simulator-
  perfect future load/PV values. Existing schemas retain their previous default.
- `*_electrical_service_phase_violations_*` now measures residual exceedance in
  the post-projection total and phase active-power histories.
- The legacy `charging_constraint_violation_kwh` observation and reward penalty
  retain pre-projection pressure semantics for controller feedback and backward
  compatibility.
- `robustness_asset_unavailable_time_step_count` now counts unique
  asset-identity/time-step pairs instead of target-field applications.

### Dataset/Schema Impact

- The annual suite uses 35,040 steps at 900 seconds over calendar year 2023,
  with UTC timestamps and `Europe/Lisbon` calendar/DST attributes.
- Variant schemas share frozen physical data and differ only in the declared
  experimental dimension. `file_checksums.sha256` freezes every generated
  family file.
- The scenarios are calibrated hybrid benchmarks, not statistically fitted
  samples of Portuguese communities. Electrical safety covers active-power
  connection and phase headroom, not feeder voltage, reactive power,
  protection or power flow.

### Compatibility

- Existing flat and entity schemas remain loadable; new forecast and terminal-
  boundary behaviour is opt-in.
- Consumers that previously interpreted
  `*_electrical_service_phase_violations_*` as requested-action clipping pressure
  must migrate to the new `*_requested_pressure_*` rows.
- The annual datasets are repository benchmark assets. Consumers of the PyPI
  package should provide a checkout or mounted dataset path when using them.

### Validation

- `.venv/bin/pytest -q`: pass, `457 passed, 18 warnings`.
- Critical lint, Python 3.9 syntax targeting and the CI performance smoke: pass.
- Annual REC structural, diversity, scientific and deterministic-generation
  audits: pass.
- Nine-schema annual REC smoke: pass, `6,048` regular transitions, all `120`
  topology-event effects and `31,565` causal price features checked.

### Migration Notes

- No migration is needed for existing scenarios that do not opt into the new
  features.
- Pin `softcpsrecsimulator==1.8.0` in algorithm environments that use the new
  terminal-boundary, dynamic-history or KPI contracts.

## v1.6.1 - 2026-08-06

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release adding aggregate escalator control for station-energy simulations and the final
15-minute EC_Ermesinde scenario.

### Added

- Added `EscalatorSimulation` and `Escalator` with normalized standby/slow/normal actions.
- Added flat escalator demand, train-context, state, power and service observations.
- Added escalator electricity, passenger-service and state-change KPI v2 rows.
- Added the annual `EC_Ermesinde` dataset, its reproducible generator and integration tests.

### Changed

- Building net electricity consumption now includes escalator electricity use.
- The loader expands `escalator_*` observations and `escalator` actions per configured asset.

### Dataset/Schema Impact

- `EC_Ermesinde` uses 900-second steps and six escalator CSV files.
- Existing schemas are unaffected. Escalator support is additive and currently uses the flat interface.

### Compatibility

- Compatible patch release for existing schemas and flat-interface users.
- New scenarios should provide the required escalator CSV columns documented in the schema reference.

### Validation

- `.venv/bin/pytest -q tests/test_escalator_integration.py tests/test_deferrable_appliance_integration.py tests/test_scenario_smoke.py`: pass, `19 passed`.
- Annual EC_Ermesinde smoke simulation: pass, `35,039` transitions completed.
- Standby/slow/normal control comparison: pass; slow and normal serve demand while using distinct energy.

### Migration Notes

- No migration is required. To enable the feature, add `buildings.<id>.escalators`, the
  `escalator_*` observation helpers and the `escalator` action helper.

## v1.5.6 - 2026-07-29

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release fixing dynamic-topology reset semantics across repeated episodes. Dynamic environments
now restore the schema-loaded member pool and asset composition before replaying topology events, so
multi-episode training no longer inherits structural mutations from the previous episode.

### Added

- Added multi-episode regression coverage for full member/charger/PV/BESS topology timelines.
- Added reset coverage for removed deferrable appliances and runtime-cloned members.

### Changed

- `CityLearnTopologyService` now keeps a lightweight structural snapshot of schema-loaded buildings.
- Dynamic reset restores member order, member pool, chargers, deferrable appliances, PV, electrical
  storage and topology-managed metadata without copying full building time series.

### Fixed

- Fixed added chargers remaining attached after `reset()` and causing later `add_asset` events to be no-ops.
- Fixed removed chargers and deferrable appliances remaining absent in later episodes.
- Fixed added or removed PV and electrical storage leaking into the initial state of later episodes.
- Fixed runtime-cloned members remaining in the topology pool between episodes.
- Fixed topology event logs and `topology_version` timelines diverging after the first episode.

### Dataset/Schema Impact

- No schema or dataset migration is required.
- Existing topology event definitions and time-step semantics are unchanged.

### Compatibility

- Compatible patch release for static and single-episode environments.
- Multi-episode dynamic environments now follow the intended clean-reset behavior. Workarounds that
  reconstructed `CityLearnEnv` for every episode are no longer required.

### Validation

- `.venv/bin/python -m pytest -q`: pass, `426 passed, 18 warnings`.
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass.
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` scenarios.
- `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci --select E9,F821`: pass.
- Package build and `twine check`: pass.

### Migration Notes

- No migration is required. Algorithms should pin `softcpsrecsimulator>=1.5.6` when reusing a dynamic
  environment across episodes.

## v1.5.5 - 2026-06-29

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release adding simulator-native baseline policies used by the CityLearn v3 application examples and tightening KPI settlement replay for community-market accounting. The release keeps the existing environment, schema and action contracts compatible while making the baseline API easier to reuse outside paper scripts.

### Added

- Added `ZeroActionBaselineAgent`, `ServiceOnlyBaselineAgent`, `NormalPolicy`, `NormalNoBatteryPolicy`, `RBCBasicPolicy`, `RBCSmartPolicy` and `RBCCommunityPolicy` to `citylearn.agents.baseline`.
- Added explicit public exports for the baseline module.
- Added backward-compatible `GridAwareBaselineAgent` and `CommunityAwareBaselineAgent` names that map to the smart and community-aware RBC policies.

### Changed

- `BusinessAsUsualAgent` now supports EV departure-service targets when available, while preserving the default day-to-day charging behavior.
- BAU and derived baseline actions now respect electrical-service clipping when the dataset enables those constraints.
- Community-market KPI settlement replay now preloads per-building net-load and price series and handles short price series defensively.
- Local paper/Overleaf working folders are ignored by Git.

### Fixed

- Removed duplicate `GridAwareBaselineAgent` and `CommunityAwareBaselineAgent` definitions that could make the public baseline API ambiguous.
- Fixed direct EV baseline action calls so charger service context receives the parent building.

### Dataset/Schema Impact

- No schema or dataset migration is required.
- Existing action and observation names are preserved.

### Compatibility

- Compatible patch release for existing `CityLearnEnv` users.
- New baseline classes are additive. The legacy `GridAwareBaselineAgent` and `CommunityAwareBaselineAgent` import names remain available.

### Validation

- `.venv/bin/python -m pytest tests/unit/test_business_as_usual_baseline.py tests/test_kpi_golden.py tests/test_electrical_service_and_market.py tests/test_market_phase_invariants.py`: pass, `39 passed, 10 warnings`.
- `.venv/bin/python -m pytest`: pass, `423 passed, 18 warnings`.
- `python3 -m py_compile citylearn/__init__.py citylearn/agents/baseline.py citylearn/internal/kpi.py`: pass.
- `git diff --check`: pass.

### Migration Notes

- No migration is required.
- Downstream code may import the new RBC baseline classes directly instead of relying on paper-local controller definitions.

## v1.5.4 - 2026-06-10

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focused on EV charging observation semantics, EV reward correctness and electrical-service constraint accounting. Available EV/BESS charge/discharge observations now represent admissible absolute setpoints for the next action, not only incremental residual headroom, so controllers can keep an already clipped charge active without oscillating between charge and zero.

### Added

- Regression coverage for EV reward `soc_impossible` and disconnected-charger penalties.
- Cadence coverage for entity `prev_15m` windows, forecast point offsets and storage availability at 15s, 60s, 900s and 3600s control steps.
- Observation-space containment coverage for electrical-service headroom observations.

### Changed

- Entity EV charger and storage `available_*_power_kw` and `available_*_action_normalized` now account for the currently applied power when converting residual headroom into next-step absolute setpoint limits.
- Electrical-service `charging_constraint_violation_kwh` now counts pre-clip over-requests as well as residual physical violations, aligning clipped service requests with legacy charging-constraint penalty semantics.
- Electrical-service default headroom and headroom observation bounds now include estimated base building load and controllable asset margins.
- Entity temporal `prev_1` and `prev_3` features now use the latest settled transition instead of the previous previous step.

### Fixed

- Fixed EV reward `soc_impossible` so it penalizes unreachable SOC deficits, not SOC surplus above the requested departure target.
- Fixed disconnected EV charger observations to expose the commanded charger energy, making `no_car_charging` reward penalties reachable through normal `env.step`.
- Fixed EV KPI departure feasibility to apply charger `min_charging_power` after SOC and headroom limits.
- Fixed derived PV forecasts to read future PV inputs from the dataset instead of the current-time clipped building property.
- Fixed legacy/electrical-service headroom bounds that could mark valid negative residual headroom observations as out of bounds.

### Dataset/Schema Impact

- No schema or dataset migration is required.
- Existing observation names are preserved, but their available-power semantics are clarified as absolute next-command setpoints.
- Electrical-service violation KPI/reward totals may increase for agents that request power beyond service limits because clipped over-requests are now counted.

### Compatibility

- Compatible patch release for APIs, actions, schemas and dataset files.
- Controllers that used `available_charge_action_normalized == 0` as "must stop current charge" should update to the clarified setpoint interpretation.

### Validation

- `.venv/bin/pytest tests/unit/test_ev_reward_function.py tests/test_entity_observation_bundles.py tests/test_kpi_v2.py tests/test_electrical_service_and_market.py tests/test_market_phase_invariants.py tests/unit/test_charging_constraints.py tests/test_charging_constraints_e2e.py -q`: pass, `91 passed, 8 warnings`.
- `.venv/bin/pytest -q`: pass, `423 passed, 18 warnings`.
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass.
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16 executed, 16 passed`.
- `git diff --check`: pass.

### Migration Notes

- No code migration is required for standard CityLearn agents.
- If downstream analytics compare electrical-service violation totals across versions, expect a discontinuity when agents over-request and the simulator clips the command.

## v1.5.3 - 2026-06-05

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focused on the remaining 15-second full-year dynamic initialization cost after `v1.5.2`. The loader now avoids Python-list materialization for full-year parquet data, reuses full-horizon shared time series across dynamic member windows, and skips unnecessary charger-schedule scans when no EV pool exists.

### Added

- Representative initialization benchmark notes for `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`.

### Changed

- Loader construction passes dataframe columns as NumPy arrays instead of boxing full-year parquet data through `DataFrame.to_dict('list')`.
- Full-horizon shared weather, pricing and carbon series can now be reused across dynamic member windows.
- Dynamic dataframe alignment avoids extra copies when the source already covers the full configured horizon with a default `RangeIndex`.
- Dynamic topology reset now skips full charger-schedule scans when the environment has no EV pool.

### Fixed

- Reduced full-year 15-second dynamic initialization time caused by pandas list boxing and repeated shared time-series materialization.

### Dataset/Schema Impact

- No schema or dataset migration is required.
- Explicit full-year `env.reset()` calls still allocate dense full-horizon histories; use `simulation_start_time_step` and `simulation_end_time_step` for memory-constrained training windows.

### Compatibility

- Compatible patch release for APIs, actions, observations, KPIs and dataset files.
- Numerical outputs are expected to remain unchanged; the patch changes loading/materialization strategy, not physical equations.

### Validation

- `.venv/bin/pytest tests/test_15_second_power_fixture.py tests/test_dynamic_topology_entity_mode.py tests/test_scenario_smoke.py -q`: pass, `19 passed`.
- `.venv/bin/pytest -q`: pass, `398 passed, 18 warnings`.
- `git diff --check`: pass.
- Manual performance check on `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`: full-year initialization `~24 s` and `~6.4 GB` RSS before explicit reset; earlier local check was `~90 s` and `~7.1 GB` RSS. Explicit reset still raised RSS to `~10.7 GB` because dense full-horizon histories remain allocated.

### Migration Notes

- No code migration is needed. For full-year 15-second memory reduction beyond initialization, the remaining work is a larger `history_mode="training"` or reusable reset-buffer change.

## v1.5.2 - 2026-06-05

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focused on the 15-second full-year dynamic dataset runtime stall. Full-year entity/dynamic runs no longer perform full-horizon array work inside common per-step energy accessors, bringing first-step throughput back in line with short-window runs. Initialization and memory use for full-year 15-second runs remain high because the simulator still materializes full-horizon histories.

### Added

- Representative local benchmark notes for `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`, comparing a 10k-step window with the full-year dynamic run.

### Changed

- `ElectricDevice.available_nominal_power` now reads only the current timestep instead of materializing the full electricity-consumption vector.
- `ElectricDevice.electricity_consumption` returns the stored array directly when `time_step_ratio == 1.0`, avoiding an unnecessary full-array multiply.
- Building storage energy helper properties now slice the simulated history before applying `clip`, avoiding full-year array work during early timesteps.

### Fixed

- Fixed the main per-step stall observed on full-year 15-second entity/dynamic datasets, where repeated full-horizon vector operations made early timesteps much slower than equivalent short-window runs.

### Dataset/Schema Impact

- No schema or dataset migration is required.
- Full-year 15-second datasets still allocate dense full-horizon state and observation histories. Use `simulation_start_time_step` and `simulation_end_time_step` to run smaller training windows when memory is the limiting factor.

### Compatibility

- Compatible patch release for APIs, actions, observations, KPIs and dataset files.
- Numerical outputs are expected to remain unchanged; the patch changes when arrays are sliced/materialized, not the physical equations.

### Validation

- `.venv/bin/pytest tests/test_15_second_power_fixture.py tests/test_kpis.py::test_histories_and_kpi_consistency_with_subhour_steps tests/test_scenario_smoke.py -q`: pass, `9 passed`.
- `.venv/bin/pytest -q`: pass, `398 passed, 18 warnings`.
- `git diff --check`: pass.
- Manual performance check on `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`: 10k-step window first 100 steps `~0.010 s/step`, full-year first 100 steps after patch `~0.010 s/step`; pre-patch full-year was `~0.161 s/step` in the same local check.

### Migration Notes

- No code migration is needed. For memory-constrained 15-second training, prefer explicit simulation windows until a future `history_mode="training"` or online-KPI mode removes the dense full-horizon histories.

## v1.5.1 - 2026-06-04

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release from the final KPI cost and solar audit. Community-market cost settlement no longer gives revenue for energy exported outside the community, district solar self-consumption now treats intra-community PV use as self-consumed, and EV/BESS/PV totals ignore isolated non-finite samples instead of turning whole totals into `NaN`.

### Added

- Regression coverage for zero external-grid export price in community-market settlement.
- Regression coverage for district PV self-consumption when one member exports PV and another member consumes it in the same timestep.
- Regression coverage proving EV/V2G, BESS and PV totals ignore non-finite samples.

### Changed

- `district_solar_self_consumption_total_export_kwh` is now PV-backed net export from the district to outside the community, rather than the sum of member-level PV exports.
- `district_solar_self_consumption_ratio_self_consumption_ratio` now counts same-timestep intra-community PV transfers as district/community self-consumption.

### Fixed

- Community-market cost KPIs and runtime settlement no longer credit energy exported outside the community.
- Building and district cost totals now charge only positive net grid import when the community market is disabled.
- EV charge/V2G, stationary battery charge/discharge and PV generation/export totals use finite-value summation to avoid `NaN` propagation from isolated missing samples.
- KPI replay for market-enabled control and baseline conditions applies the same zero external export price rule as runtime settlement.

### Dataset/Schema Impact

- No schema or dataset migration is required.
- Existing datasets with community market enabled may report different cost and district solar self-consumption KPI values because external export revenue is removed and district PV export is now community-net.

### Compatibility

- Compatible patch release for APIs, actions, observations and dataset files.
- KPI consumers that interpreted district solar self-consumption as a sum of individual building self-consumption should migrate to the new community-net interpretation.

### Validation

- `.venv/bin/pytest -q`: pass, `398 passed, 18 warnings`.
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict --output-dir /tmp/citylearn_audit_final`: pass.
- `.venv/bin/python scripts/audit/audit_physics.py --output /tmp/citylearn_audit_final/physics_audit.json`: pass, `16 passed`.
- `git diff --check`: pass.
- Manual KPI audit across cost settlement, market replay, district PV aggregation, EV/BESS/PV finite summation and scorecard rows: pass.

### Migration Notes

- No code migration is needed. Rebaseline dashboards or golden KPI expectations that include community-market costs or district solar self-consumption.

## v1.5.0 - 2026-06-01

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release aligning simulator exports with the EnergAIze job scorecard and reducing multi-episode export overhead. Planned training runs now export only the final episode by default, and v2 KPIs include the scorecard rows needed for direct UI comparison against BAU.

### Added

- `CityLearnKPIService.SCORECARD_DEFAULT_KPIS`, an explicit contract for the KPIs consumed by the job scorecard.
- Business-as-usual and delta rows for solar self-consumption ratio at district and building levels.
- Business-as-usual and delta rows for solar generation/export totals and daily averages.
- `export_only_final_episode` environment setting, defaulting to `true`, plus final-episode export planning for `Agent.learn(episodes=...)` and CLI training.
- Regression coverage proving default `evaluate_v2()` exports the scorecard KPI contract.
- Regression coverage proving a planned two-episode training run exports only the final episode's timeseries, KPIs and BAU audit.

### Changed

- Automatic render exports, final KPI exports and BAU timeseries exports are skipped for non-final episodes in planned multi-episode runs.
- Skipped intermediate episodes no longer calculate or write final KPIs/BAU, reducing runtime and disk usage for training jobs.
- Manual `export_final_kpis()`, direct `evaluate_v2()` calls and unplanned reset/step loops keep their existing behavior.

### Fixed

- Solar self-consumption can now be compared against BAU when the simulator exports BAU rows, instead of showing only the policy value.

### Dataset/Schema Impact

- New optional top-level schema setting: `export_only_final_episode`.
- Existing datasets need no changes; the default is `true`.
- KPI v2 output is additive: existing KPI names remain, and new BAU/delta solar self-consumption rows are added.

### Compatibility

- Planned multi-episode training with automatic exports now writes only the final episode by default. Set `export_only_final_episode=false` to restore per-episode automatic exports.
- Single-episode jobs, manual exports and manual evaluation remain compatible.

### Validation

- `.venv/bin/pytest -q`: pass, `395 passed, 18 warnings`
- `git diff --check`: pass
- `.venv/bin/python -m compileall -q citylearn/__main__.py citylearn/agents/base.py citylearn/citylearn.py citylearn/exporter.py citylearn/internal/runtime.py citylearn/internal/kpi.py citylearn/__init__.py`: pass

### Migration Notes

- For training jobs, consume `exported_kpis.csv` and `exported_data_*_epN.*` from the final planned episode.
- If downstream tooling expects every episode to be exported, set `export_only_final_episode=false` in the schema or environment kwargs.

## v1.4.0 - 2026-05-28

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Adds optional dataset-driven robustness v1 for `CityLearnEnv`. Existing datasets keep the old behavior unless `robustness.enabled=true`.

### Added

- Internal `CityLearnRobustnessService` with sparse CSV/Parquet event loading, deterministic event ordering and reproducible noise.
- Robustness modules for observations, forecasts, actions and logical asset availability.
- `entity_robustness` observation bundle with district diagnostics and `observations["meta"]["robustness"]`.
- Robustness KPI counters for district/building levels.
- Packaged no-EV robustness dataset at `data/datasets/citylearn_challenge_2022_phase_all_robustness/schema.json`, copied from the 2022 phase-all dataset with local files and sparse robustness events.
- Bilingual robustness reference documentation.
- Unit coverage for disabled behavior, CSV/Parquet parsing, module toggles, validation errors, flat/entity observations, forecasts, action modes, asset outages, KPIs, multi-community aggregation and packaged dataset loading.

### Changed

- Entity contract snapshots now include `entity_robustness` as an inactive default bundle.
- `CityLearnEnv` metadata includes a `robustness` section.

### Dataset/Schema Impact

- New optional top-level `robustness` schema section.
- New optional `entity_robustness` observation bundle.
- No existing dataset behavior changes when robustness is absent or disabled.

### Compatibility

- Additive for existing `CityLearnEnv` users.
- Observation/forecast corruption is agent-facing only; real physical state, reward, DR settlement and normal KPIs remain based on uncorrupted simulator state.
- Action and asset-control events intentionally change the applied physical action.

### Validation

- `.venv/bin/pytest -q`: pass, `393 passed, 17 warnings`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` scenarios
- `git diff --check`: pass

### Migration Notes

- Existing datasets do not need changes.
- Add `robustness.enabled=true` plus an `events_file` only for robustness experiments.

## v1.3.0 - 2026-05-28

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release adding multi-community orchestration v1 through a new public `MultiCommunityEnv`. The wrapper runs multiple independent `CityLearnEnv` communities in synchronized lockstep, preserves each community's physics, rewards, demand response and KPIs, and adds portfolio-level KPI rows for cross-community reporting.

### Added

- Public `citylearn.multi_community.MultiCommunityEnv` wrapper.
- Per-community `reset()` and `step()` payloads keyed by `community_id`.
- Per-community `action_space`, `observation_space` and `entity_specs` mappings.
- Synchronization validation for `seconds_per_time_step`, effective episode length, `interface` and `central_agent`.
- Portfolio reward info with finite child reward sums, weighted total reward and weighted mean reward.
- Multi-community `evaluate_v2()` output with `community_id` on local rows and `level="portfolio"` rows for district KPI aggregation.
- Multi-community KPI export layout with per-community child folders and a global `exported_kpis_multi_community.csv`.
- Bilingual multi-community reference documentation and quickstarts.
- Unit coverage for constructor validation, reset/step routing, reward aggregation, entity mode, independent demand response, portfolio KPIs, export layout and single-community regression.

### Changed

- README and feature/running documentation now include multi-community usage and links.
- `citylearn.__init__` lazily exposes `MultiCommunityEnv` without importing the simulator at package import time.

### Fixed

- No unrelated fixes.

### Dataset/Schema Impact

- No new dataset files and no schema changes.
- `MultiCommunityEnv` uses whichever child schemas are passed in `communities[*].schema`.
- Demand response remains configured per child dataset; no global DSO/TSO coordination or portfolio DR request file is introduced in v1.

### Compatibility

- Additive minor release for existing `CityLearnEnv` users.
- Existing single-community imports, datasets, KPIs and flat/entity contracts are unchanged unless users explicitly instantiate `MultiCommunityEnv`.
- Multi-community v1 rejects mixed interface modes, mixed `central_agent` modes, mismatched time resolutions and mismatched effective episode lengths.

### Validation

- `.venv/bin/pytest -q tests/test_multi_community_env.py`: pass, `15 passed`
- `.venv/bin/pytest -q tests/test_multi_community_env.py tests/test_demand_response.py tests/test_kpis.py tests/unit/test_export_logic.py`: pass, `33 passed`
- `.venv/bin/pytest -q`: pass, `371 passed, 17 warnings`
- `git diff --check`: pass

### Migration Notes

- Existing users do not need to change anything.
- To run a portfolio, instantiate `MultiCommunityEnv` with one child schema per community and pass actions keyed by `community_id`.
- Portfolio KPI rows are emitted only by `MultiCommunityEnv.evaluate_v2()` and do not appear in regular `CityLearnEnv.evaluate_v2()` output.

## v1.2.0 - 2026-05-28

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release adding dataset-driven demand response v1 for entity-mode simulations. DSO/TSO requests are loaded from dataset files, exposed through district entity observations, settled after each physical step, and reported through district/building KPIs.

### Added

- `demand_response` schema section with CSV/Parquet `requests_file` support.
- `entity_demand_response` observation bundle with district DR request state, baseline, prices and previous-step delivery/shortfall fields.
- Internal `CityLearnDemandResponseService` with sparse request loading, cursor-based activation, rolling pre-event baselines and active-step settlement only.
- District and building demand-response KPIs for events, active steps, requested/delivered/shortfall energy, compliance, revenue, penalty, net revenue and invalid-baseline steps.
- Packaged no-EV demand-response dataset at `data/datasets/citylearn_challenge_2022_phase_all_demand_response/schema.json`, copied from the 2022 phase-all dataset with local files and all entity observation bundles enabled.
- Unit coverage for CSV/Parquet parsing, entity observation exposure, flat-interface rejection, overlap rejection, up/down semantics, KPI/economic settlement, invalid baselines and packaged dataset loading.

### Changed

- Native business-as-usual KPI sidecar switches to entity interface when demand response is enabled, preserving the entity-only DR contract.

### Fixed

- No unrelated fixes.

### Dataset/Schema Impact

- New optional top-level `demand_response` schema key:
  `enabled`, `requests_file`, `baseline_method`, `baseline_window_seconds` and `allow_overlapping_requests`.
- Demand response v1 requires `interface="entity"` when enabled.
- Request files must define `request_id`, `issuer`, `direction`, `start_time_step`, `end_time_step`, `target_power_kw`, `activation_price_eur_per_kwh`, `shortfall_penalty_eur_per_kwh` and optional `tolerance_power_kw`.
- `entity_demand_response` adds only district table features; active `request_id` is exposed in observation `meta`, not as a numeric feature.

### Compatibility

- Additive minor release for existing flat/entity datasets that do not enable demand response.
- Schemas that enable `demand_response.enabled=true` with `interface="flat"` now fail fast with a clear error.
- Overlapping DR requests are rejected in v1 unless future support is implemented.

### Validation

- `.venv/bin/pytest -q tests/test_demand_response.py`: pass, `9 passed`
- `.venv/bin/pytest -q`: pass, `356 passed, 17 warnings`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` scenarios
- Demand-response packaged dataset smoke run for 30 entity steps plus `evaluate_v2(include_business_as_usual=False)`: pass, `180` DR KPI rows
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.2.0-dist`: pass, generated sdist and wheel
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.2.0-dist/*`: pass

### Migration Notes

- Existing datasets need no change unless they want demand response.
- To train with DR, enable `interface="entity"`, set `demand_response.enabled=true`, provide a request file and activate `observation_bundles.entity_demand_response`.
- Fixed-width entity agents must refresh `env.entity_specs` when enabling `entity_demand_response`.

## v1.1.0 - 2026-05-26

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release focused on making 15-second entity-mode simulations practical with all observation bundles enabled. The main work removes the `entity_action_feedback` memory leak, replaces the oversized derived-forecast contract with compact point forecasts, reduces recurring entity observation overhead, and moves long exports toward chunked Parquet.

### Added

- `render_file_format="parquet"` and `render_chunk_size` support for render/KPI/BAU exports. Parquet render output is written as chunked `*_partNNNNN.parquet` files.
- Fine-grained entity observation timing fields when `debug_timing=True`, including `entity_observation_building_time`, `entity_observation_charger_time`, `entity_observation_storage_time`, `entity_observation_district_time`, `entity_observation_copy_time` and related table sections.
- Chunk cleanup for previous Parquet render artifacts in the session output directory.

### Changed

- `entity_forecasts_derived` now keeps the same bundle name but exposes compact point forecasts only:
  - building: `forecast_{load,pv,net}_next_{15m,1h,3h,6h,24h}_kw`
  - district: `forecast_price_next_*` and `forecast_community_{load,pv,net}_next_*_kw`
- Removed the old derived-forecast mean/sum/peak/headroom/surplus/bucket feature grid and the reset-time forecast cache.
- Entity observation assembly now uses precomputed feature columns, sparse/direct row writes, static asset rows and precomputed forecast step offsets.
- Dynamic topology history now records snapshots only when active members/assets or topology version change.
- Battery capacity/efficiency histories now use compact numeric arrays instead of Python float lists.
- Boolean action-feedback flags and clipping reasons are stored as boolean arrays instead of `float32`.
- Environment-level KPI/export aggregate series now use numpy streaming sums instead of temporary pandas DataFrames.

### Fixed

- Fixed the dominant `entity_action_feedback` RSS growth, caused by a cache keyed on transient storage series objects.
- Fixed excessive initialization/reset overhead from derived forecasts on 15-second datasets.
- Fixed avoidable memory retention in dynamic topology history when no topology event occurs.
- Fixed avoidable export/KPI memory spikes from temporary DataFrames over all building time series.

### Benchmark Notes

Representative local measurements on `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet`, entity interface, dynamic topology, all observation bundles, `render_mode="none"`, `export_kpis_on_episode_end=False`:

| Area | Before | After | Impact |
|---|---:|---:|---:|
| Entity all-bundles feature columns | ~732 | ~322 | ~56% fewer columns |
| Derived forecast init/reset path | ~15.0s init / ~12.8s reset | ~2.0s init / ~0.15s reset | ~87% init reduction, ~99% reset reduction |
| `entity_action_feedback` RSS growth over 700 steps | ~+2071 MiB | ~+5 MiB | leak removed |
| Action-feedback cache size over 700 steps | 11,224 entries / 3.9M cached values | 24-25 entries | stable per-asset cache |
| 40,320-step 15s window post-reset RSS | ~658.7 MiB | ~630.4 MiB | ~28 MiB lower at reset after boolean flags |
| `next_observations` on 1k-step debug smoke | ~6.49 ms/step | ~5.80 ms/step | ~11% faster |
| 5k-step no-debug smoke | n/a | ~12.4 ms/step, ~718 MiB RSS at 5k | current operating point |

For full-year 15-second datasets, retained simulator histories still scale linearly with step count, assets and enabled KPI/export needs. This release removes the pathological cache growth, but it does not make a full-year all-bundles run constant-memory.

### Dataset/Schema Impact

- No packaged dataset files or schema keys are renamed.
- The entity observation feature contract changes when `entity_forecasts_derived` is active because the old large derived-forecast grid is intentionally removed.
- Parquet export requires a pandas Parquet engine such as `pyarrow`; CSV remains the default export format.

### Compatibility

- Minor release with an intentional entity observation contract change for `entity_forecasts_derived`.
- Physics equations, action application, dynamic topology event semantics, KPI formulas and flat observation behavior are intended to remain unchanged.
- Fixed-width RL agents or saved normalizers trained against v1.0.x all-bundles entity observations must refresh `entity_specs`, feature columns and input statistics before using v1.1.0.

### Validation

- `.venv/bin/pytest tests/test_entity_observation_bundles.py tests/test_dynamic_topology_entity_mode.py tests/test_dynamic_topology_full_timeline.py tests/test_dynamic_topology_assets_only_dataset.py tests/unit/test_physics_units_refactor.py tests/unit/test_physics_invariants.py tests/unit/test_subhour_scaling.py tests/unit/test_rendering_behaviour.py::test_parquet_render_format_writes_chunked_exports_and_kpis -q`: pass, `71 passed`
- `.venv/bin/pytest tests/test_deferrable_appliance_integration.py::test_entity_action_feedback_for_deferrable_start tests/test_deferrable_appliance_integration.py::test_entity_action_feedback_for_blocked_deferrable_start tests/test_kpis.py tests/test_kpi_v2.py tests/test_kpi_golden.py tests/test_series_integrity.py tests/unit/test_export_logic.py tests/unit/test_ui_export_contract.py -q`: pass, `57 passed, 17 warnings`
- `.venv/bin/pytest tests/unit/test_step_many.py -q`: pass, `5 passed`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` scenarios
- `.venv/bin/pytest -q`: pass, `347 passed, 17 warnings`
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.1.0-dist`: pass, generated sdist and wheel
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.1.0-dist/*`: pass

### Migration Notes

- Refresh `env.entity_specs` and retrain or remap any fixed-width model inputs that used `entity_forecasts_derived`.
- To use chunked Parquet exports, set `render_file_format="parquet"` and optionally `render_chunk_size`.
- For long 15-second runs, keep render/KPI exports disabled unless needed, or export in Parquet chunks.

## v1.0.2 - 2026-05-23

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release to correct the GitHub Actions performance smoke gate for the v1 entity observation contract. The simulator code, physics behavior, schemas and observation outputs are unchanged from v1.0.1.

### Added

- No new public observation, action, KPI or dataset contract.

### Changed

- The CI performance smoke job now uses an explicit entity latency budget for the all-bundles entity configuration.
- The entity/flat overhead ratio and baseline regression slack in CI now match the current v1 entity contract and GitHub-hosted runner variance.

### Fixed

- Fixed the `run_tests` CI false failure where entity all-bundles latency on `ubuntu-24.04` exceeded a pre-v1 baseline gate despite the simulator performance being within the optimized v1 envelope.

### Dataset/Schema Impact

- No schema or dataset content changes from v1.0.1.

### Compatibility

- Compatible patch release.
- Runtime simulator logic, physics constraints, KPI formulas, entity table names and feature contracts are unchanged from v1.0.1.

### Validation

- `.venv/bin/ruff check citylearn tests scripts/manual scripts/ci --select E9,F821`: pass
- `.venv/bin/pytest tests/unit/test_perf_smoke_thresholds.py -q`: pass
- `.venv/bin/pytest -q --ignore=scripts/manual`: pass, `346 passed, 17 warnings`
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --none-max-ms 30 --end-max-ms 45 --entity-max-ms 50 --ratio-max 2.0 --entity-overhead-ratio-max 3.75 --baseline-file scripts/ci/perf_baseline.json --baseline-regression-ratio 4.5 --baseline-slack-ms 15.0`: pass
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.0.2-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.0.2-dist/*`: pass

### Migration Notes

- No migration required from v1.0.1.

## v1.0.1 - 2026-05-23

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release for the v1 entity RL observation contract. This release keeps the v1.0.0 schema and physics contract intact while reducing entity observation overhead after all RL-oriented bundles are enabled.

### Added

- No new public observation, action, KPI or dataset contract.

### Changed

- Derived entity forecast generation now reuses precomputed horizon/window statistics instead of recomputing equivalent future slices every step.
- Entity observation assembly avoids repeated name lookups and only requests base observation fields used by the entity tables.
- Action-feedback bookkeeping reuses per-episode arrays instead of repeatedly rediscovering or allocating them.
- Entity row filling and short-window action-feedback metrics use cached/vectorized paths where the output contract is unchanged.

### Fixed

- CI lint typing/import failure from the v1.0.0 preparation path.
- Performance smoke thresholds now measure recurring rollout latency separately from terminal export/KPI work.

### Dataset/Schema Impact

- No schema or dataset content changes from v1.0.0.
- The 15-second schemas and `citylearn_challenge_2022_phase_all_plus_evs` still enable all entity observation bundles by default.

### Compatibility

- Compatible patch release.
- Flat observations, entity table names, legacy feature names, dynamic topology behavior, physics constraints and KPI formulas are unchanged.
- Fixed-width entity models do not need feature-list changes relative to v1.0.0.

### Validation

- `.venv/bin/ruff check citylearn tests scripts/manual scripts/ci --select E9,F821`: pass
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py --strict`: pass, `16/16` scenarios
- `.venv/bin/pytest -q`: pass, `346 passed, 17 warnings`
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --none-max-ms 30 --end-max-ms 45 --ratio-max 2.0 --entity-overhead-ratio-max 1.08 --baseline-file scripts/ci/perf_baseline.json --baseline-regression-ratio 3.0 --baseline-slack-ms 10.0`: pass
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.0.1-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.0.1-dist/*`: pass

### Performance Notes

Representative local benchmark, 600 steps, `seconds_per_time_step=60`, render disabled:

| Case | avg ms/step | p95 ms | vs flat |
|---|---:|---:|---:|
| flat | 4.7270 | 4.9251 | 1.000x |
| entity_base | 5.2227 | 5.4199 | 1.105x |
| entity_all | 14.7545 | 17.5723 | 3.121x |

### Migration Notes

- No migration required from v1.0.0.
- Users should still refresh `env.entity_specs` when changing datasets or topology modes.

## v1.0.0 - Entity RL Observation Contract

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

First stable simulator-contract release for entity-mode RL workflows. This release promotes the additive entity observation contract for forecasts, physical deadlines, action feedback, clipping diagnostics and asset-level feasible action capacity.

### Added

- Entity-only derived forecast bundle `entity_forecasts_derived` with physical horizons `15m`, `1h`, `3h`, `6h`, `24h` and 15-minute grid buckets up to 6h.
- Entity action feedback bundle `entity_action_feedback` with requested, limited and applied EV/BESS/deferrable actions plus clipping-reason flags.
- RL deadline-pressure observations for EV charging, including `departure_feasibility_ratio`, `departure_energy_margin_kwh`, `max_deliverable_energy_until_departure_kwh` and `min_required_action_normalized`.
- Feasible action-capacity observations for chargers and BESS, including `can_charge`, `can_discharge`, available power and normalized available action magnitudes.
- BESS per-step energy capacity observations split into nominal `max_*_energy_kwh_step` and constrained `available_*_energy_kwh_step`.
- Building and community aggregate flexible charge/discharge capacity and energy slack observations.
- Deferrable deadline-pressure observations, including `remaining_duration_hours`, `cycle_remaining_fraction_ratio`, `start_energy_kwh_step`, `start_power_kw` and `must_start_now`.
- Robust temporal entity observations while keeping raw `time_step` in payload `meta`.

### Changed

- 15-second entity datasets and `citylearn_challenge_2022_phase_all_plus_evs` now declare all entity observation bundles active in their schemas.
- Entity `meta` exposes `seconds_per_time_step` and the forecast config used by derived forecasts.
- Documentation now describes the entity observation bundles, RL deadline-pressure features and dataset bundle defaults.

### Fixed

- No intentional KPI or physics behavior break. EV departure countdowns remain relative in steps, while `hours_until_departure` is physical hours computed from `seconds_per_time_step`.

### Dataset/Schema Impact

- Updated schemas:
  - `citylearn_challenge_2022_phase_all_plus_evs`
  - `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet`
  - `citylearn_three_phase_dynamic_assets_only_demo_15s`
  - `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`
  - `citylearn_three_phase_electrical_service_demo_15s`
  - `citylearn_three_phase_electrical_service_demo_15s_parquet`
- New bundles remain disabled by default for schemas that do not opt in.

### Compatibility

- Flat observations, legacy names and existing default bundle behavior are preserved.
- Algorithms that consume the affected entity schemas will see wider entity tables because all bundles are active by default in those datasets.
- Real-world adapters should fill the same derived forecast contract with real forecasts rather than simulator `actual_future` values.

### Validation

- `.venv/bin/python -m pytest -q`: pass, `346 passed, 17 warnings`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` scenarios
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.0.0-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.0.0-dist/*`: pass

### Migration Notes

- RL policies should prefer physical deadline and pressure features such as `hours_until_departure`, `departure_feasibility_ratio`, `departure_energy_margin_kwh`, `available_*_power_kw` and action feedback fields over raw step indices.
- If fixed-width entity models were trained on earlier schemas, refresh feature lists from `env.entity_specs` before loading/retraining.

## v0.6.9 - Macro-Step Action Repeat

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release that adds a simulator-native `step_many()` API for RL action-repeat/macro-step training while preserving internal substep physics and exports.

### Added

- `CityLearnEnv.step_many(action, repeat_steps=..., stop_on_done=True, return_substeps=False)` for repeating a fixed action across multiple internal simulator transitions.
- Macro-transition metadata in `info`: `executed_steps`, `seconds_per_time_step` and `macro_seconds`.
- Optional debug payloads when `return_substeps=True`: `substep_rewards`, `substep_infos` and `substep_actions_applied`.
- Parity tests covering flat mode, entity mode, early termination, reward aggregation and optional substep debug output.

### Changed

- Runtime `step()` now uses a shared internal one-step core so `step_many()` and `step()` execute the same physics/action/reward path.
- `step_many()` avoids assembling final observations and info on intermediate substeps by default, but still runs constraints, EVs, batteries, deferrables, phase/headroom checks, rewards, KPIs and render/export state at every internal step.
- Static action layouts parse the repeated action once per macro-step; dynamic topology mode reparses per substep so action layouts can change safely.
- Running simulation docs now describe action repeat and the `gamma ** executed_steps` discounting pattern for RL algorithms.

### Fixed

- No intentional physics or KPI behavior changes. `step_many()` parity tests compare final observations, accumulated rewards, termination state, time step and KPI outputs against repeated `step()` calls.

### Dataset/Schema Impact

- No schema or dataset changes.

### Compatibility

- Backward compatible. Existing `step()` callers are unchanged.
- `stop_on_done=False` is accepted for API symmetry, but CityLearn still stops when the episode reaches a terminal/truncated state because the environment cannot advance beyond done without `reset()`.

### Validation

- `.venv/bin/python -m pytest tests/unit/test_step_many.py -q`: pass (`5 passed`)
- `.venv/bin/python -m pytest tests/unit/test_rendering_behaviour.py tests/test_entity_interface_contract.py tests/unit/test_step_many.py -q`: pass (`33 passed`)
- `.venv/bin/python -m pytest -q`: pass (`338 passed`, `17 warnings`)
- `.venv/bin/python -m compileall -q citylearn tests/unit/test_step_many.py`: pass
- `.venv/bin/python -m ruff check citylearn tests/unit/test_step_many.py --select E9,F821`: pass
- `git diff --check`: pass
- Step-many smoke: pass (`step_many` measured `3.3377 ms/internal-step` vs repeated `step()` `3.8041 ms/internal-step`, `1.14x` faster over 200 internal substeps)

### Migration Notes

- RL replay buffers can store `(obs_t, action_t, reward_sum, obs_t_plus_n, done, executed_steps)` and use `gamma ** executed_steps`.
- Keep `return_substeps=False` for long training runs; enable it only for debugging substep rewards or infos.

## v0.6.8 - Runtime Profiling and Step Optimizations

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focused on recurring step latency, BAU/export observability and safer final-episode export control.

### Added

- `scripts/audit/profile_step_breakdown.py` for measuring `step()` component costs such as action application, reward payload assembly, reward calculation and next observations.
- `scripts/audit/profile_lifecycle.py` for measuring reset, rollout, KPI, render and BAU export costs separately.
- Reward functions can declare minimal observation payloads through `required_observation_names`, `required_observations` or `get_required_observation_names()`.

### Changed

- Built-in rewards now use reduced observation payloads instead of full `include_all` observations during normal `step()` calls.
- `Building.observations()` and internal observation assembly can compute only requested fields while preserving full-observation fallback behavior.
- `apply_actions` skips inactive outage/constraint paths where possible and reuses cached action and asset lookups.
- Heat pump, storage and battery scalar paths avoid repeated property and NumPy work while preserving physical outputs.
- Runtime timing now reports finer `info` keys for action application, reward observation assembly, reward calculation, next observations and terminal exports.
- Docs clarify how to disable render/KPI/BAU export during training episodes and enable only the final episode output.

### Fixed

- No intentional physics changes. A deterministic equivalence check against the pre-optimization code matched 179 steps and 220 physical series with `max_abs_diff=0.0`.

### Dataset/Schema Impact

- No schema or dataset changes.

### Compatibility

- Backward compatible. Custom rewards without declared observation requirements still receive full observation dictionaries.
- KPI/export APIs are unchanged; callers can still choose BAU KPI rows and BAU timeseries through existing `export_final_kpis()` flags.

### Validation

- `.venv/bin/python -m pytest -q`: pass (`333 passed`, `17 warnings`)
- `.venv/bin/python -m compileall -q citylearn scripts`: pass
- `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci scripts/audit --select E9,F821`: pass
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass (`16 passed`)
- `git diff --check`: pass
- Physics equivalence against pre-optimization commit: pass (`179 steps`, `220 series`, `max_abs_diff=0.0`)
- `.venv/bin/python scripts/audit/profile_step_breakdown.py --episode-steps 300 --seconds 60 --agent rbc --interface flat --render-mode none --no-write --table-limit 14`: pass (`3.8973 ms/step`, `apply_actions_time=2.4688 ms`)
- `.venv/bin/python scripts/audit/profile_lifecycle.py --episode-steps 300 --seconds 60 --skip-exports --no-write`: pass (`3.8735 ms/step`, `evaluate_v2_with_bau_cold=2.2838 s`, `evaluate_v2_with_bau_cached=0.4336 s`)
- External reward fallback smoke: pass (`5.2452 ms/step` with full reward observations)
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-0.6.8-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-0.6.8-dist/*`: pass

### Migration Notes

- For fastest custom rewards, expose `required_observation_names` with the minimal fields used by `calculate()`.
- For training runs, keep `render_enabled` and `export_kpis_on_episode_end` disabled except on episodes where CSV output is required.

## v0.6.6 - Electrical-Service-Aware EV Feasibility

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release that makes EV departure feasibility KPIs use the same electrical headroom constraints that the simulator applies to charging actions.

### Fixed

- EV departure feasibility now considers configured total import headroom, per-phase import headroom, charger phase assignment, power outages and charger/battery efficiency before marking a strict target, minimum acceptable SOC or within-tolerance lower bound as reachable.
- Building 15 in three-phase/electrical-service scenarios is no longer overcredited as feasible when L1/L2 phase limits or building headroom make the requested departure SOC physically unreachable.

### Dataset/Schema Impact

- No schema changes. Feasibility now uses existing electrical service, phase connection, headroom, charger efficiency and battery efficiency configuration in addition to charger schedule, EV battery capacity, charger power and arrival SOC fields.

### Compatibility

- KPI names and export shape are unchanged. Only the feasible/infeasible classification becomes stricter when electrical-service limits or efficiency reduce physically available charging power.

### Validation

- `.venv/bin/python -m pytest tests/test_kpi_v2.py -q`: pass (`30 passed`)
- `.venv/bin/python -m pytest tests/unit/test_charging_constraints.py -q`: pass (`5 passed`)
- `.venv/bin/python -m pytest tests/test_kpi_golden.py tests/test_charging_constraints_dataset.py tests/test_charging_constraints_e2e.py -q`: pass (`13 passed`)
- `git diff --check`: pass

### Migration Notes

- Use the same feasible-only EV departure KPIs as before. In scenarios with tight building/phase headroom, some departures previously counted as feasible may now correctly move to infeasible.

## v0.6.5 - Fair EV Departure Feasibility KPIs

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release that separates raw EV departure outcomes from controller-fair outcomes when the requested SOC was physically unreachable during the connected interval.

### Added

- Feasibility counters for EV departures whose strict target, minimum acceptable service threshold or within-tolerance lower bound could/could not be reached by charging at maximum charger/battery power.
- Feasible-only EV departure KPI ratios:
  - `*_ev_performance_departure_success_feasible_ratio`
  - `*_ev_performance_departure_min_acceptable_feasible_ratio`
  - `*_ev_performance_departure_within_tolerance_feasible_ratio`

### Changed

- Existing EV departure ratios remain raw over all valid departures.
- The recommended controller-quality KPI is now `*_ev_performance_departure_min_acceptable_feasible_ratio`; use raw ratios plus infeasible counts to understand user experience and schedule feasibility.
- CI performance smoke now reports terminal render/KPI/BAU export time separately from recurring step latency, so `render_mode=end` exports do not inflate `avg_step_ms` while still being checked against the baseline.

### Dataset/Schema Impact

- No schema changes. Feasibility uses existing charger schedule, EV battery capacity, charger power and arrival SOC fields.
- Missing charger, battery or arrival-SOC data is treated as feasible for backward compatibility.

### Compatibility

- Additive KPI rows in `evaluate_v2()` and exports. Existing KPI names and semantics are preserved.

### Validation

- `.venv/bin/python -m pytest tests/test_kpi_v2.py -q`: pass (`28 passed`)
- `.venv/bin/python -m pytest tests/test_kpi_golden.py tests/unit/test_subhour_scaling.py::test_15_second_charge_immediately_meets_ev_departure_kpis -q`: pass (`11 passed`)
- `.venv/bin/python -m pytest tests/test_ev_arrivals.py::test_ev_kpi_evaluation_with_evs_and_chargers -q`: pass (`1 passed`)
- `.venv/bin/python -m pytest tests/unit/test_rendering_behaviour.py::test_auto_kpi_export_reports_debug_timing -q`: pass (`1 passed`)
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --none-max-ms 30 --end-max-ms 45 --ratio-max 2.0 --entity-overhead-ratio-max 1.08 --baseline-file scripts/ci/perf_baseline.json --baseline-regression-ratio 3.0 --baseline-slack-ms 10.0 --metrics-output /tmp/perf_smoke_report.json`: pass
- `.venv/bin/python -m compileall citylearn/internal/kpi.py`: pass

### Migration Notes

- Score controller service with `*_ev_performance_departure_min_acceptable_feasible_ratio`.
- Use `*_ev_events_departure_*_infeasible_count` as a scenario/data diagnostic, not as controller failure.

## v0.6.4 - Readiness Audit Fixes

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release from the final readiness audit across EVs, stationary BESS, deferrable appliances, observations, actions, KPIs, dynamic topology and all bundled datasets.

### Changed

- Large observation-space bounds now use vectorized finite-safe reductions, improving audit/runtime behavior on 15-second CSV and parquet datasets.
- Entity-mode smoke actions now cover every advertised action table, including deferrable appliances.
- Performance regression checks now accept render/export `end` mode when absolute step latency stays inside the configured budget.
- SAC KPI snapshots are seeded through the agent action spaces for deterministic audit output.

### Fixed

- First-step reset-populated device electricity loads are cleared before applying control actions, preventing false demand-limit failures in neighborhood datasets.
- Dataset audit schema roots now resolve repository-relative `root_directory` values correctly.
- Dataset audits release closed environments before continuing, reducing memory retention on large segmented checks.

### Dataset/Schema Impact

- No schema migration required.
- All bundled dataset schemas were validated through default, flat/entity where feasible, and dynamic probe rollouts.

### Compatibility

- Compatible patch for valid schemas and agents.
- Audit baselines were refreshed to match the hardened KPI/export contract from v0.6.3 and the first-step physics fix.

### Validation

- `.venv/bin/python -m compileall -q citylearn scripts`: pass
- `.venv/bin/python -m pytest -q tests/unit/test_subhour_scaling.py tests/test_15_second_power_fixture.py tests/unit/test_physics_units_refactor.py tests/test_dynamic_topology_entity_mode.py tests/test_dataset_loader_window_parquet.py`: pass (`53 passed`)
- `.venv/bin/python -m pytest -q`: pass (`326 passed`)
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py --max-scenarios 32`: pass (`16 passed`)
- `.venv/bin/python scripts/audit/audit_performance_results.py --strict`: pass
- Segmented dataset audit over all bundled schemas: pass (`31 passed`, `0 failed`, `0 timeout`)
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 240 --seconds 60 --seed 0`: pass
- `.venv/bin/pip check`: pass

### Migration Notes

- None.

## v0.6.3 - Physics, Bounds and Dynamic Topology Hardening

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release from the second deep audit of EVs, stationary BESS, deferrable appliances, observations, KPIs and dynamic topology exports.

### Changed

- Observation bounds now account for real EV/deferrable schedules, sub-hour profiles and zero-based minute values.
- Dynamic topology KPI/export paths use per-timestep active membership for buildings, chargers, stationary storage and deferrable appliances.
- KPI daily averages for dynamic buildings use each building's active window instead of the global episode window.
- Peak and ramping BAU shape metrics are reported on power values in kW rather than raw kWh/step.
- KPI CSV export preserves raw KPI precision by default; rounding is opt-in.

### Fixed

- Stationary BESS standby loss is applied once per timestep and cannot push SOC below the physical DoD minimum.
- BESS discharge during outages is limited to local load that can actually be served.
- Initial outage loads are clipped to available local PV/BESS supply instead of triggering a negative-flexibility assertion.
- EV required/arrival SOC inputs accept both fractions and percentages while preserving negative missing-value sentinels.
- Deferrable `can_start` and action constraints validate the full multi-step profile against outages and electrical-service headroom.
- Deferrable cycle profiles above `nominal_power` are rejected.
- Community-market settled, counterfactual and savings KPIs are exposed through the v2/export KPI contract.
- Dynamic phase peaks are accumulated on the aligned district timeline instead of truncated building-local windows.

### Dataset/Schema Impact

- No schema migration required.
- Minute observations now use `0..59`, matching normal clock semantics.
- Observation-space bounds may be wider for long EV/deferrable schedules and sub-hour appliance profiles.

### Compatibility

- Compatible patch for valid schemas.
- Invalid battery efficiencies above `1.0`, invalid DoD values and impossible deferrable power profiles now fail fast.
- Exported KPI precision may include more decimals unless `kpi_round_decimals` is provided.

### Validation

- `.venv/bin/python -m compileall -q citylearn`: pass
- `.venv/bin/python -m pytest -q`: pass
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py --max-scenarios 32`: pass (`16 passed`)
- `.venv/bin/python scripts/manual/demo_ev_rbc.py`: pass
- `.venv/bin/python scripts/manual/demo_ev_rbc_export_minutes.py`: pass
- `.venv/bin/python scripts/manual/demo_charging_constraints_export_end.py`: pass
- Dynamic topology entity smoke with zero actions and BAU KPI evaluation: pass (`95 steps`, `2937 KPI rows`)
- `git diff --check`: pass

### Migration Notes

- Algorithms that hard-code minute bounds as `1..61` should switch to `0..59`.
- Consumers that expect rounded exported KPIs should pass `kpi_round_decimals=3`.

## v0.6.0 - Native Business-As-Usual Baseline

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Adds a native operational business-as-usual baseline that is separate from the existing counterfactual KPI baseline. The new BAU reference models normal day-to-day behavior: connected EVs charge toward 100%, deferrable appliances start as soon as possible, and stationary batteries do simple PV self-consumption.

### Added

- `citylearn.agents.baseline.BusinessAsUsualAgent`, with no dependency on the external `Algorithms` repository.
- Lazy/cached `CityLearnEnv.run_business_as_usual_baseline(force=False)` sidecar simulation.
- `evaluate_v2(include_business_as_usual=True)` rows for BAU totals, deltas and ratios across cost, emissions, grid import/export/net exchange, EVs, BESS, deferrables and district shape-quality KPIs.
- `exported_data_business_as_usual_ep{episode}.csv`, a compact timestep audit for BAU building and district series.
- Unit/integration coverage for BAU EV, deferrable, BESS, KPI, export and CLI behavior.

### Changed

- `citylearn simulate` now defaults to `citylearn.agents.baseline.BusinessAsUsualAgent`.
- `export_final_kpis(...)` now includes BAU KPI rows and exports the BAU audit timeseries by default.
- `BaselineAgent` documentation now describes it as the legacy passive/no-control baseline.

### Dataset/Schema Impact

- No schema migration and no new schema keys.
- BAU uses the same dataset/schema window, selected buildings/EVs and physical timestep as the evaluated environment.

### Compatibility

- Minor release with intentional behavioral changes in default simulation, KPI and export behavior.
- Behavioral CLI change: simulations without `--agent_name` now run the operational BAU agent instead of the passive no-control `BaselineAgent`.
- Existing v2 KPI names with `baseline` are preserved; BAU uses new `business_as_usual`, `delta_to_business_as_usual`, and `ratio_to_business_as_usual` names.
- `evaluate_v2(include_business_as_usual=False)` and `export_final_kpis(include_business_as_usual=False)` preserve the pre-BAU output shape and avoid the sidecar simulation cost.

### Validation

- `.venv/bin/python -m pytest tests/unit/test_business_as_usual_baseline.py -q`: pass (`9 passed`)
- `.venv/bin/python -m pytest tests/test_kpi_v2.py tests/unit/test_ui_export_contract.py tests/unit/test_rendering_behaviour.py -q`: pass (`43 passed`)
- `.venv/bin/python -m pytest tests/test_deferrable_appliance_integration.py tests/test_ev_arrivals.py tests/unit/test_electric_vehicle.py tests/unit/test_battery.py -q`: pass (`41 passed`)
- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`308 passed`)
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass (`16 passed`)
- `.venv/bin/python scripts/manual/demo_ev_rbc.py`: pass
- `../Algorithms/.venv/bin/python -m pytest tests/test_rbc_agent.py tests/test_baseline_policies.py tests/test_benchmark_agents.py tests/test_wrapper_action_clipping.py tests/test_entity_adapter.py tests/test_wrapper_entity_mode.py -q`: pass (`45 passed`)
- `git diff --check`: pass

### Migration Notes

- Use `citylearn.agents.base.BaselineAgent` explicitly if you need the old passive/no-control CLI behavior.
- Consumers that enumerate v2 KPI names should allow the new BAU rows in `evaluate_v2()` and `exported_kpis.csv`.

## v0.5.4 - EV/BESS/Deferrable Physical Semantics and Outage Hardening

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release from the deep simulator audit focused on making EVs, stationary batteries, deferrable appliances, outage behavior, raw dataset signals and observation bounds physically consistent across timestep sizes from seconds to hours.

### Added

- Runtime outage local-balance invariant that asserts local loads during an outage are not greater than local sources.
- Regression coverage for raw pricing/carbon values, outage blocking of EV/deferrable loads without local surplus, and storage observation bounds in kWh per control step.
- Entity contract snapshots updated for the normalized `deferrable_appliance_*` dataset naming.

### Changed

- Dataset/schema timestep mismatch handling remains user-owned: the simulator prints an explicit unit-conversion notice but does not resample data automatically.
- Pricing and carbon intensity time series now preserve raw dataset values instead of clipping to `[0, 1]`; negative electricity prices are supported.
- Observation-space limits for device and storage electricity consumption now use kWh per control step, not nominal kW.
- Deferrable appliance starts are included in electrical-service headroom calculations before EV/BESS actions are scaled.
- During power outages, EV charging and deferrable starts are limited to available local surplus. EV discharge is blocked in the outage control path because the current model does not route EV discharge into building-local load supply.

### Fixed

- EV arrival handling no longer falls back to required departure SOC when current/arrival SOC is missing; existing battery SOC carries forward instead.
- EV battery schema attributes such as efficiency, degradation and power curves are now loaded into the actual EV battery.
- EV and stationary battery SOC now carries forward to current-step observations when no energy is requested.
- Stationary BESS carry-forward applies standby loss consistently through the shared storage timestep path.
- Normalized unserved-energy KPIs now ignore surplus as negative unserved energy, mask non-outage steps for outage KPIs, and return zero instead of NaN when the expected-energy denominator is zero.

### Dataset/Schema Impact

- No required schema migration.
- Dataset authors remain responsible for aligning `seconds_per_time_step` with data cadence or intentionally using `time_step_ratio`.
- Algorithms that previously assumed prices or carbon intensity were encoded to `[0, 1]` must normalize externally.
- Gym observation-space bounds may change for electricity-consumption observations in sub-hourly and multi-hour runs because bounds now use kWh per step.

### Compatibility

- Compatible patch for valid schemas.
- Behavioral change for invalid/physically impossible outage commands: EV/deferrable loads can no longer draw unavailable grid energy during outages.
- Behavioral change for datasets with negative prices or values above one: raw values are now exposed to algorithms and KPIs.

### Validation

- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`299 passed`)
- `.venv/bin/python scripts/audit/audit_physics.py`: pass (`16 passed`)
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/manual/demo_ev_rbc.py`: pass
- `../Algorithms/.venv/bin/python -m pytest tests/test_rbc_agent.py tests/test_baseline_policies.py tests/test_benchmark_agents.py tests/test_wrapper_action_clipping.py tests/test_entity_adapter.py tests/test_wrapper_entity_mode.py -q`: pass (`45 passed`)
- `git diff --check`: pass

### Migration Notes

- Keep pricing/carbon normalization in the algorithm/preprocessing layer, not in the simulator.
- For outage experiments, use stationary storage/PV as local sources; EV discharge should not be treated as V2B until that routing exists explicitly.
- Review trained agents that depend on previous kW-sized observation bounds or clipped market signals.

## v0.5.3 - Storage/EV Sub-Hour Physics Hardening

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release that fixes storage timestep physics for sub-hour and multi-hour datasets, and prevents EV batteries from inheriting implicit stationary-storage standby loss when EV schemas do not explicitly configure `loss_coefficient`.

### Fixed

- EV batteries now default to `loss_coefficient=0.0` when `electric_vehicles_def.*.battery.attributes.loss_coefficient` is missing or `null`.
- `StorageDevice.loss_coefficient` is now interpreted as an hourly loss ratio and converted to effective per-step loss with `loss_coefficient * seconds_per_time_step / 3600`.
- `Battery.charge(...)` now enforces charge/discharge power limits in physical kWh per control step instead of treating kWh commands as kW.
- `Battery` efficiency curves now use average power over the physical step, not raw step energy.
- `StorageTank` now preserves the constructor `time_step_ratio`; previously the base `Device` init could overwrite it.
- Stationary BESS actions are clipped to `[-1, 1]` before conversion to physical kWh.
- Native sub-hour datasets, including 15-second datasets, no longer lose EV SOC artificially over thousands of connected steps because of the stationary storage default.

### Dataset/Schema Impact

- Existing EV schemas remain valid.
- EV `battery.attributes.loss_coefficient` is optional and should usually be omitted.
- If EV `loss_coefficient` is provided, it is a per-hour loss ratio. The storage model converts it to effective loss per physical step.
- Stationary storage default parameter ranges are unchanged, but `loss_coefficient` now has physical hourly semantics across native sub-hour, hourly and multi-hour timesteps.

### Compatibility

- Backward compatible for schemas that do not set EV `loss_coefficient`.
- EV schemas that explicitly set `loss_coefficient` now receive timestep-correct hourly semantics; this is intentional for sub-hour correctness.
- Observations, rewards and EV departure KPI names are unchanged.
- Stationary storage simulations that explicitly relied on the old ratio-based standby loss behavior in non-hourly datasets will see corrected physical losses.

### Validation

- `.venv/bin/python -m pytest -q tests/unit/test_subhour_scaling.py tests/unit/test_battery.py tests/unit/test_electric_vehicle_charger.py tests/test_ev_soc_behavior.py tests/unit/test_physics_units_refactor.py tests/unit/test_physics_invariants.py tests/test_kpi_v2.py tests/test_kpi_golden.py tests/unit/test_deferrable_appliance.py tests/test_deferrable_appliance_integration.py`: pass (`113 passed`)
- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`286 passed`)

### Migration Notes

- Do not configure EV `loss_coefficient` unless standby loss is intentionally needed.
- For EVs, use an hourly loss ratio if the field is configured; the simulator handles sub-hour scaling.
- For stationary storage, keep existing hourly `loss_coefficient` values. The simulator now scales those values by the actual timestep duration.

## v0.5.2 - EV Departure Service KPIs

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release that separates EV departure target fulfillment, minimum acceptable user service and symmetric SOC target accuracy.

### Added

- `ev_departure_service_tolerance` environment/schema setting, default `0.05`.
- Building and district KPIs for minimum acceptable EV departures.
- Building and district KPIs for SOC shortfall beyond service tolerance.
- EV departure SOC surplus, absolute error and configured tolerance diagnostics.

### Changed

- Existing EV departure success, within-tolerance and deficit KPI names and semantics are preserved.
- `ev_departure_within_tolerance` remains the symmetric proximity tolerance.

### Dataset/Schema Impact

- Existing schemas remain valid.
- New optional top-level schema key: `ev_departure_service_tolerance`.
- Existing optional top-level key `ev_departure_within_tolerance` can configure symmetric target accuracy tolerance.

### Compatibility

- Backward compatible additive KPI release.
- Consumers that enumerate all v2 KPI names should allow the new EV rows in `evaluate_v2()` and `exported_kpis.csv`.

### Validation

- `.venv/bin/python -m pytest -q tests/test_kpi_v2.py -q`: pass
- `.venv/bin/python -m pytest -q tests/test_kpi_golden.py -q`: pass
- `.venv/bin/python -m pytest -q tests/unit/test_export_logic.py tests/unit/test_ui_export_contract.py -q`: pass
- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`276 passed`)
- `.venv/bin/python -m compileall -q citylearn tests/test_kpi_v2.py`: pass

### Migration Notes

- Use `*_ev_performance_departure_min_acceptable_ratio` as the primary user-comfort EV departure KPI.
- Use `*_ev_performance_departure_success_ratio` for strict target fulfillment.
- Use `*_ev_performance_departure_within_tolerance_ratio` and absolute error for target accuracy and efficiency analysis.

## v0.5.1 - Deferrable Start Command Hardening

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focused on making deferrable appliance control safer for RL training by treating start actions as explicit ON/OFF commands and avoiding accidental early starts from small positive continuous actions.

### Changed

| Area | Change |
|---|---|
| Deferrable action semantics | `DeferrableAppliance.trigger_threshold` default changed from `0.0` to `0.5`. |
| Start command robustness | Non-finite values (`nan`, `inf`) are treated as OFF and do not start cycles. |
| Controller contract | Documentation now states binary start intent (`0` off, `1` on) and recommends using `deferrable_appliance_can_start` as readiness signal. |

### Dataset/Schema Impact

- No schema structure change.
- Existing optional `attributes.trigger_threshold` remains supported.
- Schemas that relied on implicit default `0.0` now use safer default `0.5` unless explicitly overridden.

### Compatibility

Behavioral patch change:
- with default settings, low positive deferrable actions no longer trigger starts.
- to preserve legacy behavior, set `deferrable_appliances.<id>.attributes.trigger_threshold: 0.0`.

### Validation

| Command/group | Result |
|---|---|
| `.venv/bin/pytest -q tests/unit/test_deferrable_appliance.py tests/test_deferrable_appliance_integration.py` | Pass (`10 passed`). |
| `.venv/bin/pytest -q tests/test_dynamic_topology_entity_mode.py -k deferrable` | Pass (`1 passed`, `13 deselected`). |

### Migration Notes

- If a controller previously emitted arbitrary continuous values in `[0, 1]`, map intent explicitly to ON/OFF (for example, `0.0` or `1.0`).
- If you intentionally need old permissive behavior, configure `trigger_threshold=0.0` per deferrable appliance.

## v0.5.0 - Action-Asset Consistency Hardening (Breaking)

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Breaking release that removes silent action/device mismatches for storage control, enforces strict topology-mode compatibility for dynamic schemas and consolidates the public deferrable dataset contract.

### Added

| Area | Change |
|---|---|
| 15s Parquet datasets | Added tracked 15-second parquet datasets for `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet` and `citylearn_three_phase_electrical_service_demo_15s_parquet`. |
| Dataset naming normalization | Migrated legacy dataset files/asset IDs from `washing_machine_*` to `deferrable_appliance_*` in `citylearn_three_phase_electrical_service_demo`, `citylearn_three_phase_dynamic_topology_demo` and `citylearn_challenge_2022_phase_all_plus_evs`. |

### Changed

| Area | Change |
|---|---|
| Topology mode validation | Schemas that declare dynamic topology (`topology_mode: dynamic` or `topology_events`) now reject `topology_mode='static'` at initialization. |
| Static consistency | In static mode, if `electrical_storage` action is active for a building without an effective storage asset and without `inactive_actions` opt-out, initialization now fails fast. |
| Dynamic action exposure | Dynamic metadata synchronization now keeps `inactive_actions` precedence for `electrical_storage`, EV charger actions and deferrable appliance actions. |

### Dataset/Schema Impact

- Dynamic datasets must be executed with `topology_mode='dynamic'` and `interface='entity'`.
- Static datasets with `actions.electrical_storage.active=true` must either:
  - declare an effective `electrical_storage` asset for participating buildings, or
  - explicitly opt-out per building via `inactive_actions: ["electrical_storage"]`.
- Official deferrable naming in provided datasets is now `deferrable_appliance_*`; legacy `washing_machine_*` naming was removed from `data/datasets`.
- 15-second parquet schemas are now first-class tracked dataset artifacts for direct use in smoke/regression validation.

### Compatibility

Breaking behavior change by design:
- no more silent fallback for static storage-action inconsistencies;
- no more running dynamic-topology schemas in static mode.

### Validation

| Command/group | Result |
|---|---|
| `tests/test_dynamic_topology_entity_mode.py` targeted consistency tests | Pass. |
| `.venv/bin/pytest -q tests/test_dynamic_topology_entity_mode.py tests/test_dynamic_topology_assets_only_dataset.py` | Pass (`15 passed`). |
| `.venv/bin/pytest -q tests/test_dynamic_topology_entity_mode.py tests/test_15_second_power_fixture.py tests/test_dataset_loader_window_parquet.py` | Pass (`17 passed`). |
| 15s dataset smoke (`CityLearnEnv` reset + step) for CSV and parquet variants of dynamic-assets-only and electrical-service demos | Pass (`4/4`). |
| Whole-catalog smoke with windowed loading (`31` schemas) | `27` pass; `4` known pre-existing HVAC sizing assertion failures outside EV/deferrable migration scope. |

### Migration Notes

- If you previously ran dynamic schemas in static mode, update runtime configs to `topology_mode='dynamic'` and `interface='entity'`.
- If static runs now fail with storage consistency errors, fix schema intent explicitly (declare storage or set per-building `inactive_actions`).

## v0.4.3 - Documentation Contract and Release Readiness

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Release focused on making the simulator easier to adopt, audit and integrate by turning the README into a documentation portal and adding bilingual reference documentation.

### Added

| Area | Changes |
|---|---|
| README | English default documentation map with Portuguese links. |
| Running simulations | Install, quickstarts, CLI, `CityLearnEnv` parameters, render/export and validation commands. |
| Schema | Full schema reference for buildings, devices, PV modes, EVs, chargers, deferrables, topology and community market. |
| Interfaces | Flat/entity contracts, entity specs, tables, edges and dynamic topology guidance. |
| Actions | Action names, ranges, physical conversions and entity action payloads. |
| Observations | Observation dictionary with units, sentinels, bundles, entity tables and edges. |
| Datasets | CSV/Parquet contract, real-data conversion, 15s guidance and deferrable dataset format. |
| KPIs | v1/v2 explanation, units, equations and EV/BESS/deferrable/community/phase families. |
| Features | Simulator capability inventory. |
| Releases | Release checklist, versioning policy and changelog template. |
| Developer guide | Tests, audits, performance checks and internal architecture. |
| Publishing guide | PyPI release workflow and local build checks. |
| Portuguese docs | Full Portuguese mirror under `docs/pt/`. |

### Compatibility

No runtime API break is introduced by the documentation work. The release keeps the additive simulator changes documented under `v0.4.2`.

### Validation

| Check | Result |
|---|---|
| Local Markdown links | Pass. |
| `git diff --check` | Pass. |
| Flat smoke simulation | Pass. |
| Entity smoke simulation | Pass. |
| 15s Parquet smoke simulation | Pass. |

## v0.4.2 - Additive Physical Observation Expansion

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Additive release focused on exposing richer physical observations to algorithms without removing older features.

### Added

| Area | Changes |
|---|---|
| Chargers | `min_charging_power_kw`, `min_discharging_power_kw`, `charger_efficiency_ratio`. |
| Charger core | `charge_efficiency_at_max_ratio`, `discharge_efficiency_at_max_ratio`, incoming EV required/departure/hours/ratio. |
| Storage | `min_charge_power_kw`, `min_discharge_power_kw`, `efficiency_ratio`, `round_trip_efficiency_ratio`. |
| Storage core | `current_efficiency_ratio`, `degraded_capacity_kwh`, `soc_min_ratio`. |
| Storage phases | `phase_connection_L1/L2/L3`. |
| Deferrables | `must_run`, average/peak/load factor, peak offset, remaining duration/power and current-step power. |
| Building core | `charging_total_service_power_kw`, `charging_phase_L1/L2/L3_power_kw`. |
| PV | `generation_capacity_factor_ratio`. |

### Compatibility

Compatible additive change. Existing observations and EV/charger duplication are intentionally preserved.

### Validation

| Command/group | Result |
|---|---|
| Focused entity/bundle/deferrable/parquet tests | Pass. |
| Broader simulator tests | Pass. |
| Full suite | Pass. |
| `audit_entity_contract.py --strict` | Pass. |
| `audit_physics.py` | Pass. |

## v0.4.0 - Normalized Deferrable Appliances

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Introduced the official `deferrable_appliances` model with a cycle catalog and sparse flexibility schedule, replacing the old washing-machine format.

### Added

| Area | Changes |
|---|---|
| Schema | `deferrable_appliances` with `cycle_profiles_file` and `flexibility_schedule_file`. |
| Model | `DeferrableAppliance` with pending/running/missed/completed states. |
| Actions | `deferrable_appliance_{id}` in flat mode and `start` in the entity table. |
| Observations | Pending, running, can_start, deadlines, slack, priority and remaining energy. |
| KPIs | Completed/missed cycles, service level, served/unserved energy and average delay. |
| Dynamic topology | Add/remove `deferrable_appliance`. |

### Compatibility

Breaking schema change: `washing_machines` is no longer the official dataset format.

## v0.3.2 - Performance, 15s and Parquet

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Consolidated sub-hourly support and improved performance for large datasets, especially 15-second datasets.

### Added/Changed

| Area | Changes |
|---|---|
| Loader | Windowed CSV and Parquet reads. |
| Cache | Shared weather/pricing/carbon when the file is identical and `noise_std=0`. |
| Parquet | 15s datasets can use `.parquet`. |
| Sub-hourly | Fixtures/tests for 15s, 1min, 5min, 15min and 1h. |
| PV | `absolute` mode for real datasets in `kWh/step`. |
| Unit contract | Formal documentation for `kWh/step`, `kW`, prices and emissions. |

## Pre-v0.3 - Initial EVs and Washing Machines

Fork owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Before normalized deferrables, the fork introduced initial EV/charger support and early washing-machine flexibility.

### Added

| Area | Changes |
|---|---|
| EVs | EV definitions, charger schedules and connected/incoming observations. |
| Chargers | Charging/discharging actions and charger schedules. |
| Washing machines | First flexible appliance model. |
| Algorithms integration | Initial support for RBC/MADDPG and external algorithm repositories. |
