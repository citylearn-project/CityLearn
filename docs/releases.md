# Releases

Changes, compatibility, validation and measured performance for the current
CityLearn release. Older notes are retained in the [release archive](releases_archive.md).

Portuguese version: [pt/releases.md](pt/releases.md).

For package publication, version policy and the release checklist, see the
[publishing guide](publishing.md).

## Unreleased

### Added

- **Recurring evaluation-window KPIs.** Opt-in `evaluation_window` configuration (schema key, `CityLearnEnv`, `MultiCommunityEnv` and CLI `-ke`) adds recurring local-window KPIs without changing simulation physics or existing KPI contracts when disabled: `{building,district,portfolio}_energy_grid_window_average_power_{control,business_as_usual,delta_to_business_as_usual}_kw` and `{building,district,portfolio}_ev_window_net_exchange_control_kwh`. Enabling `evaluation_window` without bounds defaults to `16:00:00` to `19:00:00` in scenario local time, supports sub-hour boundaries, straddling steps and midnight wrap (`start > end`), records the resolved bounds and time zone in `exported_kpis.manifest.json`, flags conflicting evaluation windows in `compare_manifests()`, and keeps shared KPIs paired while noting one-sided windowed rows when comparing an enabled run with a disabled run ([#338](https://github.com/citylearn-project/CityLearn/pull/338)).
- **RLlib wrappers on the current Ray.** `RLlibSingleAgentWrapper` and `RLlibMultiAgentEnv` are tested with Ray 2.60.0 (new API stack, Python 3.10 to 3.14, gymnasium 1.2.2): PPO and SAC train for a few iterations on one day of `citylearn_challenge_2023_phase_2_local_evaluation`, and the trained `RLModule` produces actions (`tests/test_rllib_wrappers.py`, skipped without Ray, run in the CI job that installs Ray). `RLlibMultiAgentEnv` failed on that release at the first `reset()` because it set neither `agents` nor `possible_agents`; it now sets both and the per-agent `observation_spaces` and `action_spaces`. `RLlibMultiAgentActionWrapper` orders the actions by agent ID instead of by the order of the dictionary. A new tutorial, [Train a controller with RLlib](https://www.citylearn.net/usage/rllib_training.html), trains single-agent and multi-agent PPO controllers and evaluates them with `evaluate_v2()`; CI executes it. Simulation results are unchanged ([#293](https://github.com/citylearn-project/CityLearn/issues/293)).
- **KPI units and descriptions.** `evaluate_v2()` and the long multi-community CSV include `unit` and `description` from the KPI catalogue. Wide CSV and Parquet exports keep their existing columns and provide the definitions in their manifest ([#298](https://github.com/citylearn-project/CityLearn/issues/298)).
- **KPI catalogue and complete KPI reference.** The [KPI catalogue](KPI_V2_TREE.md) lists every name that `evaluate_v2()` emits, grouped into 21 families, with its meaning in English and Portuguese. It is generated from `citylearn/misc/kpi_catalogue.yml`, and a test fails when an emitted name is missing from it. The [KPI reference](kpis_reference.md) now explains every family, including the audits, energy provenance, the community market, comfort and equity. It gives their equations, district and portfolio aggregation and undefined values, and names the canonical discomfort, Gini and local-share KPIs. Values do not change. ([#326](https://github.com/citylearn-project/CityLearn/issues/326))
- **Control values of the grid-shape KPIs.** With the BAU comparison, `evaluate_v2()` now also emits the control value behind each shape delta: `district_energy_grid_shape_quality_{peak_daily_average,peak_all_time_average,ramping_average,ramping_total}_control_kw` and `district_energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average{,_signed_net}_control_ratio`. Existing rows do not change. ([#326](https://github.com/citylearn-project/CityLearn/issues/326))
- **Documentation per release.** The site home (`/`, and `/stable/`) opens the latest final release by default while preserving existing links to shared documentation pages and redirecting development-only root URLs to `/dev/<page>`; each release tag `v*` is published under `/<version>/`, and `master` is published under `/dev/`. Every page provides both a top version selector and an **Other versions** section in the left sidebar driven by `/versions.json`, keeping the equivalent page open when switching versions or falling back to that version's home page when missing ([`docs/publishing.md`](publishing.md#documentation-site), [#296](https://github.com/citylearn-project/CityLearn/issues/296)).
- **Reward versions.** `Electric_Vehicles_Reward_Function`, `ComfortReward` and `SolarPenaltyAndComfortReward` accept `version`, and version 2 follows their documented definitions ([#249](https://github.com/citylearn-project/CityLearn/issues/249)). In version 1, a building with EV chargers got only its EV terms, a building without chargers got 0, and leaving 0.25 or more below the required departure SOC added `weights['soc_under'] ** 2`, a bonus of +25 with the default weights; with a required SOC of 0.8, departing at 0.2 scored +15 and departing at 0.65 scored -20. Version 2 adds the MARL base reward to every building and replaces the bonus with `min(2 * w, -(w ** 2))` (-25), so the same departures score -35 and -20. In cooling and heating mode, the version 1 comfort reward took heating or cooling from the larger demand at the step, so in heating mode at 21.5 °C with a 20 °C set point it was 0 with the heater off and -1.5 with it on; version 2 takes it from `hvac_mode` and gives -1.5 in both cases. Version 2 is the default, and every bundled schema that uses these rewards sets `"version": 2`, so the rewards of `citylearn_challenge_2022_phase_all_plus_evs`, the three-phase demos, the 2023 challenge, Quebec and `baeda_3dem` datasets change; simulations and KPIs do not ([#278](https://github.com/citylearn-project/CityLearn/issues/278)). Version 1 is deprecated: it exists only to reproduce runs made with CityLearn 3.6.0 or earlier, selecting it raises a `DeprecationWarning`, and it will be removed in a later release. A single current definition avoids comparing policies trained on different rewards. The reward evidence in the environment metadata and in export manifests records the version. See the [migration guide](migration.md#unreleased).

### Fixed

- **District emissions with local trading off.** With a community market enabled and `local_trading_enabled: false`, the settlement, the cost KPIs and the provenance ledger trade no energy locally, but the district emissions still netted one member's export against another's import. They now charge every member import at its carbon intensity, the `member_sum` value, and equal `district_energy_provenance_external_purchase_emissions_kgco2` in every market configuration. The local price ratio never affects emissions. Results change only for runs with local trading switched off; no bundled dataset does that. See the [migration guide](migration.md#district-emissions-with-local-trading-off) and [#327](https://github.com/citylearn-project/CityLearn/issues/327).
- **One-step delay in the BAU battery response.** The native reference uses current observed load and PV when dispatching the stationary battery. BAU-relative results can change, and the export manifest records the new definition. See the [migration guide](migration.md#the-native-bau-uses-current-step-load-and-solar) and [#190](https://github.com/citylearn-project/CityLearn/issues/190).
- **Portfolio battery cycles.** Equivalent full cycles use total throughput and total nominal battery capacity. The BAU delta and ratio compare the resulting control and BAU portfolio values. Earlier portfolio exports should be regenerated for comparisons of these KPIs ([#330](https://github.com/citylearn-project/CityLearn/issues/330)).
- **Generic agents on the entity interface.** Under the entity interface the action and observation spaces are dictionaries of entity tables, so `Agent` and `ZeroActionBaselineAgent` failed with `AttributeError` at the first `predict()`. They now keep the flat spaces and return flat-like action vectors, which the entity interface accepts, also under a dynamic topology. `SAC`, `SACRBC`, `MARLISA`, `MARLISARBC` and `TabularQLearning` read flat observation vectors and now raise a `ValueError` that names the flat interface on the entity interface. Flat runs are unchanged ([#250](https://github.com/citylearn-project/CityLearn/issues/250)).
- **`NoControlAgent` with the BAU comparison and a dynamic topology, and hour-based RBCs with deferrable appliances.** `NoControlAgent` disables every action of the env, so `evaluate_v2()` with the native BAU reference raised `ValueError: Native BAU configuration differs ... active_actions` on every dataset; the reference keeps the loaded actions, and the agent now records them for the check. Under a dynamic topology, reset and joining members or assets enable their actions again, and `step()` failed because the agent returned no actions; the agent now disables them again before each action. `BasicRBC`, `OptimizedRBC` and `BasicBatteryRBC` raised `ValueError: Unknown action name: deferrable_appliance_...` on datasets with deferrable appliances (`citylearn_challenge_2022_phase_all_plus_evs`, the `pt_rec_*` datasets); they now start each pending cycle as soon as its window allows, as `BasicElectricVehicleRBC_ReferenceController` does, since a cycle that is never started is missed. Runs that worked before are unchanged ([#309](https://github.com/citylearn-project/CityLearn/issues/309)).
- **Rule baselines as SACRBC and MARLISARBC exploration controllers.** `rbc` accepts any agent instance, agent class or import path, including `RBCBasicPolicy`, `RBCSmartPolicy`, `RBCCommunityPolicy` and `BusinessAsUsualAgent`, which raised `TypeError` as instances and `ValueError` for the SAC hyperparameters as classes. A controller built from a class or a path no longer receives the learner's hyperparameters (`lr`, `batch_size`, `hidden_dimension`, ...); the other keyword arguments still reach it. The bundled `RBC` classes ignored those hyperparameters, so their runs are unchanged ([#250](https://github.com/citylearn-project/CityLearn/issues/250)).
- **Non-finite actions.** A NaN action used to pass every `min`/`max` limit unchanged, so a NaN storage action became the largest possible discharge: on `tests/data/minute_ev_demo` the battery went from 50% to 0% SOC in one 15-minute step, twice its power limit. `env.step()` now raises `ValueError` for NaN or infinite actions on both interfaces, including the entity `map` and per-entity overrides (the entity interface used to clip infinity to a bound and apply non-finite overrides as 0), and storage `charge()` rejects non-finite energy ([#228](https://github.com/citylearn-project/CityLearn/issues/228)).
- **Physics invariant checks.** With `physics_invariant_checks=True`, a NaN or infinite state now counts as a violation instead of being read as 0, and the checks raise `PhysicsInvariantError`, a subclass of `AssertionError`, so `python -O` no longer disables them ([#228](https://github.com/citylearn-project/CityLearn/issues/228)).
- **Physics invariant identities independent of the net balance.** The net-balance check rebuilds net consumption from the device series that produced it, so an accounting error inside a device model passed it: on `tests/data/minute_ev_demo`, 100 kWh added to the consumption of a 1.0 kWh non-shiftable load raised nothing. `physics_invariant_checks` now also checks identities that compare each device series with the model's inputs and states. The electricity of each heat pump and electric heater must equal its heat output, including storage charging, divided by its COP or efficiency. Served cooling, heating, DHW and non-shiftable load must not exceed their demand. A battery's stored energy must change by its terminal energy at its efficiency, and a discharge must stop at the depth-of-discharge reserve. Each identity raises `PhysicsInvariantError`. The checks hold on every bundled dataset under both physics versions, and results do not change ([#277](https://github.com/citylearn-project/CityLearn/issues/277)).
- **EV deadline features.** In the step a vehicle departs with energy still missing, `required_average_power_kw`, `avg_power_to_departure_kw`, `charging_slack_kw`, `departure_feasibility_ratio` and `min_required_action_normalized` reached about 1e7, far outside their observation bounds. They now saturate at their bounds and keep their meaning ("not deliverable in time"); the rule baselines take the same actions and the KPIs are unchanged ([#242](https://github.com/citylearn-project/CityLearn/issues/242)).
- **CLI.** `citylearn list_datasets` and `list_default_time_series_variables` print one item per line to stdout and exit with 0; they used to print a Python list to stderr and exit with 1. `run_work_order` exits with 1 when a job fails, and `list_datasets` no longer reads the dataset cache while the parser is built ([#252](https://github.com/citylearn-project/CityLearn/issues/252)).
- **Invalid configuration fails early.** Unknown `CityLearnEnv` keyword arguments raise `TypeError` with a suggestion (a typo such as `physics_invariants_checks=True` used to be ignored). Topology events that reference a member missing from the schema, and asset overrides with unknown keys or invalid values, fail at construction instead of when the event fires (or being ignored). `community_market.local_trading_enabled` accepts `"false"`, `"no"` and `"0"`, which used to enable trading, and malformed or reversed `episode_time_steps` windows raise a clear error ([#253](https://github.com/citylearn-project/CityLearn/issues/253)).
- **Explicit episodes and a narrowed simulation window.** Only the rows of the simulation window are loaded, but an explicit `episode_time_steps` list was only checked for `0 <= start <= end`. On the Quebec datasets, whose schemas list three episodes, narrowing the window with `simulation_start_time_step`/`simulation_end_time_step` kept the schema's episode `[0, 2159]`: a window of 0 to 96 failed at step 97 with `IndexError`, and a window of 2200 to 2296 simulated January instead of the requested rows. When the caller narrows the window and does not pass `episode_time_steps`, the schema's list is now clipped to the window, and episodes without an interval inside it are dropped; an explicit list, from the caller or the schema, that reaches outside the window raises a `ValueError` at construction. Runs whose episodes lie inside the window are unchanged ([#308](https://github.com/citylearn-project/CityLearn/issues/308)).
- **Per-building reward functions.** With the schema's `reward_function.type` mapped per building, every building's function read the first building's metadata and functions were paired with buildings by position. With `SolarPenaltyReward`, a building with a 10 kWh battery next to one without a battery got 0 instead of -7.5. Each function now reads its own building's metadata and is paired by building name, also when members join or leave under a dynamic topology. No bundled dataset uses per-building reward functions. See the [migration guide](migration.md#unreleased) ([#249](https://github.com/citylearn-project/CityLearn/issues/249)).

- **Community market operator balance.** With different tariffs per member (different pricing files, or `tariff_files`), each side of a local trade is priced with its own member's tariff, so importers can pay a different amount from what exporters receive for the same energy. That residual was recorded per settlement step but not reported, so community cost KPIs did not close. It is now reported as the district KPI `community_operator_balance_total_eur` (positive when the market keeps money). Member costs are unchanged, and the KPI is zero with a single shared tariff, as in every bundled market dataset ([#239](https://github.com/citylearn-project/CityLearn/issues/239)).
- **Copied environments.** After `copy.deepcopy(env)` or a `pickle` round trip, the energy-provenance ledger lost track of every battery, because it keys its stocks by object identity: at the next step it booked all stored energy as `asset_exit` or `mobility` and opened new `unknown` stocks, so the copy's `*_energy_provenance_*` KPIs differed from an uncopied run (hundreds of `evaluate_v2()` rows on `citylearn_challenge_2022_phase_all_plus_evs`). The ledger now re-keys its stocks when it is copied or unpickled. `copy.deepcopy` also failed on datasets with LSTM thermal dynamics (the 2023 challenge, Quebec and `baeda_3dem` datasets) once the model had made a prediction, because the stored hidden state kept its autograd graph; the model now stores a detached hidden state, and its predictions are bit-identical to before. Uncopied runs are unchanged ([#307](https://github.com/citylearn-project/CityLearn/issues/307)).
- **Physics version in exports and comparisons.** Exports and comparisons did not record `physics_version`, so `compare_exports()` paired a run under physics 1 with one under physics 2 and reported their difference as a controller difference. The resolved version is now in the export manifest and its comparison context, and runs under different physics versions compare as `incompatible`. `MultiCommunityEnv` rejects communities with different `physics_version` or `random_stream_version`. Simulation results do not change. See the [migration guide](migration.md#physics-version) ([#301](https://github.com/citylearn-project/CityLearn/issues/301)).
- **Settings recorded with each run.** `get_metadata()`, the temporal metadata and the export manifest record `episode_split_boundary` and `time_step_ratio_mode`; the reward evidence of per-building reward functions records each building's reward class and version; and a misspelled `physics_version` argument gets a suggestion. Simulation results do not change. See the [migration guide](migration.md#recorded-settings) ([#302](https://github.com/citylearn-project/CityLearn/issues/302)).

### Changed

- **Agents renamed: `NoControlAgent` and `ZeroActionAgent`.** In CityLearn, "baseline" names the KPI counterfactual, the same buildings without storage and with PV, which the `*_baseline_*` KPIs report. Two agent classes used the word for something else, so they are renamed after what they do: `citylearn.agents.base.BaselineAgent`, which disables every active action, becomes `NoControlAgent`, and `citylearn.agents.baseline.ZeroActionBaselineAgent`, which requests zero for every action, becomes `ZeroActionAgent` ([#297](https://github.com/citylearn-project/CityLearn/issues/297)). The old names remain deprecated aliases of the same classes until a later release, so imports, CLI and schema agent paths and pickled agents keep working, with a `DeprecationWarning` that names the new class and the reason. Results are unchanged. See the [migration guide](migration.md#unreleased).
- **Lint and CI (engineering, no result change).** `ruff` runs with the rules in `pyproject.toml`: F401 (unused imports removed while keeping explicit `as` re-exports on public modules), F841 (unused variables), B006 (the mutable `hidden_dim` and `hidden_size` defaults in `citylearn/rl.py`, now `None`), E722 (bare `except`) and the earlier E9, F821 and NPY201. Third-party GitHub Actions are pinned to commit SHAs and Dependabot proposes weekly updates. A separate workflow (`.github/workflows/coverage.yml`) reports test coverage (`pytest-cov`, not a gate) outside pull-request checks, and `pytest.ini` sets a 600 s per-test timeout (`pytest-timeout`). Simulation results are unchanged. Switching to trusted publishing remains a maintainer action ([#289](https://github.com/citylearn-project/CityLearn/issues/289)).

- **Logging and NumPy state.** Importing CityLearn no longer calls `logging.basicConfig` or `np.seterr`, and the package logs through `citylearn.*` loggers, so it no longer changes the host program's root logger or NumPy error handling. Warnings still reach stderr; configure logging in your application (for example `logging.basicConfig(level=logging.INFO)`) to see INFO messages. The CLI does this itself, and `DataSet`/`Agent.learn()` change the `citylearn` logger's level only when `logging_level` is passed ([#251](https://github.com/citylearn-project/CityLearn/issues/251)).
- **Export folder.** The default render folder and relative `render_directory` values resolve against the current working directory (`./render_logs`); they used to resolve against the package's parent folder, which is `site-packages` for an installed wheel ([#254](https://github.com/citylearn-project/CityLearn/issues/254)).
- **LSTM checkpoints** load with `torch.load(..., weights_only=True)` on the CPU, so with torch 1.13 or newer a checkpoint shipped with a dataset cannot run code when unpickled, and a malformed checkpoint gives its real error ([#255](https://github.com/citylearn-project/CityLearn/issues/255)).

Simulation results and KPIs of valid runs are unchanged: the BAU and `RBCSmartPolicy` give bit-identical actions and `evaluate_v2()` tables to 3.6.0 over a week of `citylearn_challenge_2022_phase_all_plus_evs` and of `pt_rec_30`. See the [migration guide](migration.md#unreleased).

### Dynamic topology and data alignment

Work package 3 of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), in [#274](https://github.com/citylearn-project/CityLearn/pull/274). Results change for dynamic-topology runs with member-window files and for consecutive episode splits; the [migration guide](migration.md#unreleased) lists the options that restore the 3.6.0 behaviour.

- **Consecutive episode splits share their boundary row.** Consecutive splits used to advance by `episode_time_steps` rows, so the interval between two episodes was never simulated. They now advance by `episode_time_steps - 1` rows, and every interval up to the last complete split is simulated once; `episode_split_boundary='disjoint'` keeps the 3.6.0 splits. ([#247](https://github.com/citylearn-project/CityLearn/issues/247))
- **Dynamic-topology members are aligned with the simulation window.** A member file shorter than the dataset is read as starting at the member's `add_member` time step for any `simulation_start_time_step` and window length, which also corrects the native BAU inputs of dynamic episodes that do not start at row 0. A member that rejoins needs a full-horizon file, members that join mid-episode start their thermal storage at `initial_soc`, and the public district series keep departed members and count joining members only from their activation. ([#246](https://github.com/citylearn-project/CityLearn/issues/246))
- **A topology event at the terminal step** no longer adds an unexecuted interval to the building series.
- **A control step different from the dataset step is rejected.** CityLearn reads one data row per control step and does not resample, so such a run advanced the calendar, prices and EV schedules at the wrong rate. It now raises a `ValueError`; `time_step_ratio_mode='compress'` keeps the 3.6.0 behaviour. The dataset step is inferred from every row instead of the first two, and the `time_step_ratio` argument must match it. Bundled datasets are not affected. ([#234](https://github.com/citylearn-project/CityLearn/issues/234))

### KPI definitions

These changes alter KPI values, not simulations. The KPI definition version becomes `2.0.0`; the [migration guide](migration.md#kpi-definitions) lists what to rerun, and the [KPI reference](kpis_reference.md#definitions-changed-after-360) lists every changed row and the name that keeps its 3.6.0 value.

- **District ratios to the baseline.** The district import, net-exchange and emissions ratios to the baseline were the unweighted mean of the building ratios, so small buildings with extreme ratios dominated them. They are now ratios of the district totals, like the cost, export and BAU ratios. The 3.6.0 values are kept as `*_building_mean_ratio`. ([#237](https://github.com/citylearn-project/CityLearn/issues/237))
- **District emissions.** District emissions summed each member's emissions while district import is netted, so local sharing never lowered emissions. They are now the emissions of the netted district import and match the provenance `external_purchase_emissions`. The sum over members is kept as `district_emissions_total_*_member_sum_kgco2`. ([#238](https://github.com/citylearn-project/CityLearn/issues/238))
- **Building demand-response settlement.** Building credited energy and shortfall were an uncapped contribution and an equal share of the request without the tolerance, so they did not add up to the district and buildings could report full compliance while the request failed. They are now the district values allocated with the revenue and penalty weights. District KPIs and cash flows are unchanged; the uncapped contribution is kept as a diagnostic. The definition version becomes `demand-response-audit-v2`. ([#240](https://github.com/citylearn-project/CityLearn/issues/240))
- **Load-factor penalties.** They were computed on the signed net series, so a window whose peak was not positive gave an infinite or negative penalty that was reported as a perfect 0. `evaluate_v2()` now uses import power and leaves windows without import undefined; the signed-net values are kept as `*_signed_net_*`, and the legacy `evaluate()` rows keep the signed series. ([#241](https://github.com/citylearn-project/CityLearn/issues/241))
- **Undefined service KPIs.** The deferrable start delay without completed cycles, ratios with a missing operand and each deferrable-appliance ratio to the BAU whose own two totals are zero (for example the missed-cycle ratio when neither run missed a cycle, even if cycles were due) are now missing instead of 0 or 1. ([#243](https://github.com/citylearn-project/CityLearn/issues/243))
- **Portfolio rates.** `MultiCommunityEnv` pools the portfolio EV departure rates and means, service levels, start delay and self-consumption from their additive denominators instead of weighting them by community. ([#244](https://github.com/citylearn-project/CityLearn/issues/244))
- **Portfolio market shares and demand-response compliance.** The portfolio community-market local shares of demand and export were means weighted by community `weight`. They are now pooled from local and grid energy. The portfolio demand-response compliance and audit coverage ratios are now pooled from requested energy. New district rows `district_demand_response_valid_requested_total_kwh` and `district_demand_response_credited_total_kwh` export the components of the compliance ratio; district and building values do not change. ([#285](https://github.com/citylearn-project/CityLearn/issues/285))
- **BAU ramping average.** `district_energy_grid_shape_quality_ramping_average_business_as_usual_kw` was the sum of upward ramps over the episode. It is now the mean per step transition; the sum is kept as `*_ramping_total_*_kw`. ([#245](https://github.com/citylearn-project/CityLearn/issues/245))

### Physics

Work package 4 of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), in [#279](https://github.com/citylearn-project/CityLearn/pull/279).

- **Versioned physics.** `physics_version` (schema key and `CityLearnEnv` argument) selects the physics of a run: `1` is the physics of 3.6.0 and earlier, and `2`, the default, holds the corrections of the physics work package of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)). The BAU reference of `evaluate_v2()` uses the version of the evaluated environment, and the run metadata of the exports records it. See the [migration guide](migration.md#physics-version).
- **Standby loss of EVs away from their charger.** The away-from-charger SOC drift started from the previous step and discarded that step's standby loss, so an EV with a non-zero battery `loss_coefficient` kept its charge while away. Under physics version 2 the drift starts from the SOC after the loss, as it already did for suspended EVs ([#236](https://github.com/citylearn-project/CityLearn/issues/236)).
- **HVAC demand caps at steps longer than one hour.** The cooling and heating demand caps compared an energy per dataset step with the device's available power, which capped HVAC output at one hour of nominal power per step. Under physics version 2 the heat pump and the electric heater compare energy with energy ([#235](https://github.com/citylearn-project/CityLearn/issues/235)).
- **Autosizing at sub-hourly resolution.** Under physics version 2 storage tanks hold one hour of peak demand power (the `duration` autosize attribute changes it), so 15-minute data get the same tanks as hourly data instead of a quarter of them, and PV autosizing groups years by the dataset resolution and repeats the hourly PVWatts output at sub-hourly steps, where it used to fail ([#233](https://github.com/citylearn-project/CityLearn/issues/233)).
- **Battery discharge power.** `capacity_power_curve` describes how charging power tapers near full charge, but it also limited discharge, so a full battery could discharge at only a fraction of its nominal power. Under physics version 2 a new battery attribute, `discharge_power_curve`, limits discharge; it defaults to a flat curve at `nominal_power` and can derate at low state of charge, and `InventoryBattery` keeps its `max_discharge_kw` ([#227](https://github.com/citylearn-project/CityLearn/issues/227)).
- **Battery discharge during outages.** An islanded battery's discharge was capped by a pre-step load estimate that ignored the thermal storage discharge and the device limits, so the battery could discharge more than the building consumed and the surplus was reported as PV curtailment, even without PV. Under physics version 2 the battery discharges after the step's thermal demand and thermal storage discharges and only up to the islanded load that PV leaves, and `physics_invariant_checks` asserts it ([#229](https://github.com/citylearn-project/CityLearn/issues/229)).
- **Electrical-service headroom.** The import limit of a building with `electrical_service` was shared among the EV chargers and the battery in proportion to their requested power, including requests the device could not draw (a full battery, a charger without an EV), which curtailed the other devices. Under physics version 2 each request is first limited to the power its device can draw, and the headroom observations and the requested-violation penalty use the same powers ([#231](https://github.com/citylearn-project/CityLearn/issues/231)).
- **Thermal storage under an electrical-service limit.** The headroom was allocated before the step's thermal storage charging, so the import could exceed the limit while the recorded power, headroom and violation stayed within it. Under physics version 2 the headroom is allocated after the thermal, domestic hot water and non-shiftable updates, and the recorded power, headroom and violation come from the settled import ([#230](https://github.com/citylearn-project/CityLearn/issues/230)).
- **Deferrable appliance starts.** The start check used the realised future outage signal, load, PV and limits, which a controller cannot know, and reported the result through `can_start`, the action feedback and the refusal of the start. Under physics version 2 a start is decided on the current step and on whether the cycle ends within the episode; a cycle that later meets an outage is served from the islanded supply the other loads leave and, when that supply falls short, stops and is reported as missed ([#232](https://github.com/citylearn-project/CityLearn/issues/232)).
- **Energy to full of faded batteries.** `Battery.charge` stops at the degraded capacity, which capacity fade lowers below the nominal capacity, but the entity observations computed the energy a battery can still take from the nominal capacity. A battery that fade had made full was therefore observed as able to charge: over the year of `citylearn_challenge_2022_phase_all_plus_evs` with the BAU, chargers reported `can_charge` 1 and a positive `available_charge_power_kw` at 35,208 charger steps where the EV accepted nothing. The BAU reserved that power, and its home battery discharged for it and exported the energy. Under physics version 2, `energy_to_full_kwh`, `connected_ev_energy_to_full_kwh`, `flexible_energy_to_full_kwh` and the charge features derived from them stop at the lower of the SOC limit and the degraded capacity, for EV and stationary batteries. The simulated physics is unchanged, and batteries without fade, including every `pt_rec_*` battery, give the same observations. Without the `entity_core_electrical` bundle no observation shows the fade, so the BAU still estimates the EV headroom from the nominal capacity (see the [baselines guide](baselines.md#known-limits)).
- **One-way storage efficiency.** `StorageDevice.round_trip_efficiency` returned the one-way efficiency, the square root of `efficiency`. `one_way_efficiency` now holds that value, and `round_trip_efficiency` keeps it with a `DeprecationWarning`; the metadata and the entity feature `round_trip_efficiency_ratio` keep their names and values. `Battery.efficiency_history` gains one entry per charge or discharge instead of two ([#226](https://github.com/citylearn-project/CityLearn/issues/226)).
- **Frozen references for both physics versions.** The refactor parity audit (`scripts/audit/audit_refactor_parity.py`) and the NumPy version test (`tests/test_numpy_version_independence.py`) compared runs only with references recorded under physics version 1, so a change to the default physics passed both checks. Each check now runs under both versions and compares each run with the reference of its version: `scripts/audit/snapshots/refactor_parity_physics_v2.json` and `tests/data/numpy_version_reference_physics_v2.json` hold version 2, with the default `v2` random streams in the NumPy test, and the version 1 references are unchanged. The NumPy 1.x and 2.x CI jobs must both reproduce each reference. `--physics-version` selects one version in the audit ([#292](https://github.com/citylearn-project/CityLearn/issues/292)).

Physics version 1 reproduces 3.6.0: the BAU and `RBCSmartPolicy` give bit-identical series and `evaluate_v2()` tables to 3.6.0 on `citylearn_challenge_2022_phase_all_plus_evs`, `citylearn_challenge_2023_phase_2_local_evaluation`, `pt_rec_4`, `pt_rec_30` and the outage week of `pt_rec_30/evaluation/rec_30_robustness.json`, and the frozen refactor and NumPy references run under it. Under version 2 the discharge curve changes the challenge datasets slightly: over four weeks of `citylearn_challenge_2022_phase_all_plus_evs` the BAU imports 0.05% less, and over the 30 days of `citylearn_challenge_2023_phase_2_local_evaluation` the BAU costs 0.25% more, because a full battery now discharges at its nominal power. The electrical-service and deferrable corrections leave cost, import and peak of the BAU and `RBCSmartPolicy` on `pt_rec_4` and `pt_rec_30` unchanged; they correct the recorded per-phase import peaks of `pt_rec_30` (from 19.3 to 17.4 kW on L1 for the BAU, for example), which overstated the settled import, and in the outage week of `rec_30_robustness.json` the BAU's unserved deferrable energy falls from 1.47 to 0.28 kWh, because cycles are no longer refused for outages the controller could not know of. The energy-to-full correction changes the BAU on datasets whose EV batteries fade and that publish the `entity_core_electrical` bundle: over the year of `citylearn_challenge_2022_phase_all_plus_evs`, the BAU's home batteries export 51 kWh less of what they discharged for full EVs, member import falls by 46 kWh and the cost by 0.03% (32,211.91 to 32,202.41 EUR), and district import rises by 0.03% because that export no longer offsets other members' import; the EV departure KPIs are unchanged. Over one day of the 15-second three-phase demos, that battery export falls from 3.10 kWh to below 0.01 kWh and the BAU cost rises by 0.08 to 0.09%. `pt_rec_*` and `citylearn_three_phase_electrical_service_demo` are unchanged. Rerun results under version 2, or set `physics_version=1` to reproduce 3.6.0.

### Random streams and seeds

Work package 5 of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), in [#281](https://github.com/citylearn-project/CityLearn/pull/281). Results change for runs that use random device parameters, electric vehicles away from their charger, occupants or stochastic outages; `random_stream_version='v1'` restores the 3.6.0 random streams.

- **Random streams are derived per purpose, object and episode.** Random device parameters, the state of charge of electric vehicles away from their charger, occupant set-point interactions and stochastic outages reused or shared their random streams ([#248](https://github.com/citylearn-project/CityLearn/issues/248)). Every unspecified device parameter was the first draw of a new `RandomState`, so all of them sat at the same quantile; the EV drift seed was `random_seed + episode`, so seed `s` in episode 1 repeated seed `s + 1` in episode 0, and one stream was shared by every EV; every occupant drew `RandomState(max(random_seed, 1) + time_step)`, the same value in every building and episode; and `ReliabilityMetricsPowerOutage` skipped day 0 and the partial last day and floored durations. A new `random_stream_version` setting (schema key and constructor argument) selects the derivation. The default, `v2`, derives one `numpy.random.SeedSequence` stream per purpose, object and episode, keeps one generator per stream, and draws outages on every day with durations rounded to the nearest step. `v1` reproduces 3.6.0 for the same seed. On `citylearn_challenge_2023_phase_2_local_evaluation` the three buildings no longer share identical outages in every episode, and on `citylearn_challenge_2022_phase_all_plus_evs` the 168-hour net consumption changes by −1.6%. Runs without these random features are unchanged. See the [migration guide](migration.md#random-streams).
- **Agent and neighborhood-generation streams.** `TabularQLearning` drew its exploration decision, and MARLISA with information sharing shuffled its coordination order, with `RandomState(random_seed + time_step)`, and the neighborhood generator seeded partial-load simulation `i` of building `b` with `b + i`, so their streams overlapped across seeds, time steps and buildings ([#287](https://github.com/citylearn-project/CityLearn/issues/287)). With `v2`, agents keep one `SeedSequence` generator per purpose and episode and follow the `random_stream_version` of their environment, and `Neighborhood` takes a `random_stream_version` argument that derives the seed of each partial-load simulation from the neighborhood seed, the building and the simulation index. Agent exploration and newly generated datasets change; simulations and the bundled datasets do not, and `v1` restores the 3.6.0 streams.
- **`TabularQLearning` seeds its action spaces.** Random exploration actions, and the fallback action for an observation whose Q-values are all still NaN, were sampled from the gymnasium action spaces of `TabularQLearningWrapper`, which nothing seeded, so gymnasium seeded them from OS entropy and two runs with the same `random_seed` did not repeat. The agent now seeds each action space that is not already seeded from `random_seed`, as `SAC` does, and a space the caller has seeded keeps its stream. This applies with both `random_stream_version` values: these actions were never reproducible, so `v1` has no stream to preserve.
- **What `reset(seed=s)` repeats.** The migration guide, the `CityLearnEnv.reset` docstring and `EpisodeTracker.random_stream_episode` said that `reset(seed=s)` repeats the first episode of an environment built with `random_seed=s`. It restarts the per-episode streams (EV drift, occupant interactions, stochastic outages) at the key of episode 0, but the episode window still advances, and device and EV battery parameters and the initial EV state of charge keep the values drawn at construction. The documentation now says so, and recommends building a new environment to repeat a run with another seed and passing a seed to the first reset only, since a seed at every reset repeats the same streams in every episode. The behaviour is unchanged: making a seeded reset rebuild the environment or rewind the window would change every run that seeds its resets ([#303](https://github.com/citylearn-project/CityLearn/issues/303)).
- **Cloned members draw their own streams.** Under a dynamic topology, an `add_member` event that clones a member from `source_member_id` renamed the copy but kept the source's random stream keys, so the clone's occupant drew exactly the same set-point interactions as its source in every step and episode, and any later draw from its devices repeated the source's. The clone and everything under it (occupant, devices, chargers, appliances) are now keyed by the new member's name. Results change only for schemas that clone members with occupants or other random draws, under `random_stream_version='v2'`; `v2` is not yet released, `v1` is unchanged, and no bundled dataset clones a member. Device parameters drawn at construction are still copied from the source ([#304](https://github.com/citylearn-project/CityLearn/issues/304)).

### Engineering

- The test suite copies bundled datasets into a temporary cache private to each pytest process instead of the user's cache (`~/.cache/citylearn`), which overwrote downloaded datasets and made concurrent test runs fail with `FileNotFoundError` ([#256](https://github.com/citylearn-project/CityLearn/issues/256)).
- New tests: heat-pump COP (formula and the cap at 20, including a zero temperature difference), the private test cache, the optional end-use load-profile modules (when their extras are installed) and the operator balance.
- The publish workflow can use PyPI trusted publishing (OpenID Connect) once a trusted publisher is configured and the repository variable `PYPI_TRUSTED_PUBLISHING` is `true`; until then it uses the existing credentials. The pip cache key of the test workflow hashes `pyproject.toml` instead of the removed `setup.py`. The stale `README_PYPI.md` is removed ([#256](https://github.com/citylearn-project/CityLearn/issues/256)).
- Documentation: `settlement_version`, `grid_export_price`, `tariff_files` and `local_trading_enabled` are documented in the schema reference; the community import-share formula, the PV self-consumption formula (curtailment term) and the timing of the entity PV features are corrected; the `BasicElectricVehicleRBC_ReferenceController` and `RLC` docstrings describe what the code does ([#256](https://github.com/citylearn-project/CityLearn/issues/256)).

### Documentation and API reference

Part of work package 9 of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)). Simulation results and KPIs do not change.

- **`CityLearnEnv.scorecard()`** returns the default scorecard rows of an `evaluate_v2()` table, in the order of the new `CityLearnEnv.SCORECARD_DEFAULT_KPIS`, which used to be reachable only through an internal class ([#263](https://github.com/citylearn-project/CityLearn/issues/263)).
- **Quickstart.** One quickstart with its expected output, and a second step that compares `RBCBasicPolicy` with the BAU; the BAU is described as charging EVs to 100% by default ([#260](https://github.com/citylearn-project/CityLearn/issues/260)).
- **Glossary and concepts.** A glossary gives "baseline" and the other core terms one meaning each, and the core concepts are part of "Getting started" ([#261](https://github.com/citylearn-project/CityLearn/issues/261)).
- **Dataset catalogue.** A table of every public dataset, generated from the schemas: buildings, EVs, time step, window, format, size and features ([#262](https://github.com/citylearn-project/CityLearn/issues/262)).
- **API reference.** The `CityLearnEnv` docstring is corrected and documents every argument, `evaluate_v2()` documents its arguments and returned columns, a Python API page lists the public modules, `citylearn.internal` is no longer published, and the calendar and metadata keys of the `pt_rec_*` schemas are documented ([#263](https://github.com/citylearn-project/CityLearn/issues/263), [#264](https://github.com/citylearn-project/CityLearn/issues/264)).
- **Navigation.** One KPI landing page leads to the other KPI pages, the migration guide moves to "Project", the challenge pages to "History", and the validation commands that need a source checkout say so ([#271](https://github.com/citylearn-project/CityLearn/issues/271), [#272](https://github.com/citylearn-project/CityLearn/issues/272)).
- **Links and versions.** Dead links are fixed, a weekly job checks external links, and every page says that the site documents `master` and where to read the documentation of a release ([#270](https://github.com/citylearn-project/CityLearn/issues/270), [#271](https://github.com/citylearn-project/CityLearn/issues/271)).
- **Notebook outputs.** The notebook pages (`usage/agents`, `usage/load_environment`, `usage/cli`, `usage/rl_training`) show the outputs of a CI run: the Sphinx workflow executes the notebooks with `scripts/ci/run_notebooks.py --output-dir examples` before the build, and `check_docs.py --require-notebook-outputs` fails when a page has none. The notebooks in the repository stay free of outputs ([#299](https://github.com/citylearn-project/CityLearn/issues/299)).

### Installation, documentation and CLI

Work package 9 of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), part B. Simulations and KPIs are unchanged.

- **PyTorch and scikit-learn are optional.** A default installation took about 5.7 GB, mostly PyTorch with its CUDA libraries, although only LSTM thermal dynamics and the SAC and MARLISA controllers use it ([#259](https://github.com/citylearn-project/CityLearn/issues/259)). `pip install citylearn` now installs about 200 MB. The new extras `citylearn[dynamics]` (PyTorch, for the LSTM thermal dynamics of the 2023 challenge, Quebec, `baeda_3dem` and EULP neighbourhood datasets) and `citylearn[rl]` (PyTorch and scikit-learn, for SAC and MARLISA) add them, and `end_use_load_profiles` includes both. Loading such a dataset or controller without them raises an `ImportError` that names the extra and the CPU-only PyTorch command. The installation page starts with the installation steps, lists the extras and documents the dataset cache, offline use and every `CITYLEARN_*` variable; the reproducibility notes and the compatibility table move to its end. See the [migration guide](migration.md#unreleased).
- **Actionable data errors.** An unknown dataset name suggests the closest names and points to `DataSet().get_dataset_names()`, not the non-existent `get_names()`. A Parquet dataset without pyarrow fails before the download and names `citylearn[parquet]`. Offline errors with an empty cache name the cache folder, `CITYLEARN_LOCAL_DATASETS_PATH` and how to disable offline mode, and the log messages say "does not exist" instead of "DNE" ([#268](https://github.com/citylearn-project/CityLearn/issues/268)).
- **Example notebooks run in CI.** The controller notebook failed in its passive-agent cell, whose environment no longer matches the native BAU reference; it now evaluates without that reference ([#265](https://github.com/citylearn-project/CityLearn/issues/265)). The notebooks simulate one week, install `citylearn[rl]` and Stable Baselines3 2.4 or newer instead of the pin 2.3.2, which downgraded gymnasium to 0.29.1, and no longer run RLlib 2.10, which has no wheels for Python 3.12 or newer ([#266](https://github.com/citylearn-project/CityLearn/issues/266)). A new CI job executes every published notebook. A new tutorial, [Train and evaluate a reinforcement learning controller](https://www.citylearn.net/usage/rl_training.html), trains a Stable Baselines3 SAC controller, evaluates it on an unseen week and compares it with the BAU on a scorecard; the 2.1.2 tutorial notebook is removed ([#267](https://github.com/citylearn-project/CityLearn/issues/267)).
- **CLI.** `train --evaluate` evaluates on the first training episode window instead of the whole dataset, so `-ke '{"episode_time_steps": 24}'` evaluates 24 steps. The training summary records the host and user names only with `--record_host`. `simulate` prints the path of each file it writes, and a Stable Baselines3 agent without a policy raises a `TypeError` that shows `-ka '{"policy": "MlpPolicy"}'`. Evaluating a wrapped environment (for example a Stable Baselines3 agent) failed with `AttributeError` on gymnasium 1.x and now works. The documentation states the actual requirements and gives a Stable Baselines3 example ([#269](https://github.com/citylearn-project/CityLearn/issues/269)).
- **Contributing.** `CONTRIBUTING.md` covers the setup, a fast test subset, the documentation and notebook checks and the pull request checklist; the issue templates are assigned to the current maintainer, a question template is added, and `ray[rllib]` is no longer a test dependency ([#273](https://github.com/citylearn-project/CityLearn/issues/273)).

## v3.6.0 - 2026-11-19

### What's new

3.6.0 collects 26 pull requests: corrections to the physics, KPIs, baselines, agents, data loading and exports, faster simulation steps, three opt-in features, and a Python 3.10 floor with a wider CI. Results change only where a fix applies; the [migration guide](migration.md#upgrade-from-350-to-360) lists which runs to repeat.

### Fixes

Physics and KPIs:

- **Power and energy at sub-hourly steps.** Several limits compared a power in kW with an energy per step in kWh, which only coincide at 3600 s. `available_nominal_power` is now a power at every step length; heat pumps and electric heaters no longer exceed `nominal_power` when they charge thermal storage; on native sub-hourly data a device delivers at most `nominal_power` x step duration per step; during an outage, the local supply passed to devices and to the non-shiftable load is converted to power and to dataset resolution; and the `cooling_demand`, `heating_demand` and `dhw_demand` observations convert the storage discharge to dataset resolution when `time_step_ratio` is not 1. ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Undersized devices.** A device that cannot meet its demand no longer raises `AssertionError: demand is greater than ..._device max output`. Its output is clipped, a `RuntimeWarning` is issued once per device and episode, and the shortfall is reported as unserved thermal service energy. ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Base-power estimate.** The estimate behind electrical-service headroom and the feasibility KPIs no longer subtracts thermal storage discharge twice, and it counts escalator power, including a requested escalator state in the step it is requested. ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Clip reasons.** `clip_reason_phase_headroom` and `clip_reason_export_headroom` name only the asset's own phases and the clipped direction. ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Normalized observations.** `observations(normalize=True, periodic_normalization=False)` no longer raises `KeyError: 'month'`. ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Occupant set-point hold.** `set_point_hold_time_steps` in a building schema now reaches `LogisticRegressionOccupantInteractionBuilding`. On the Quebec neighbourhood datasets (4 steps), occupant set-point changes revert to the schedule after 4 steps without interaction instead of holding for the rest of the episode. ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Dynamic topology district baseline.** The district reference series summed only the members active at evaluation time, while the control series keep every member's past consumption, so a departed member counted on the control side only. With all-zero actions on `citylearn_three_phase_dynamic_topology_demo` (24 steps, `Building_6` leaving at step 12), the district import delta to baseline was 12.76 kWh, the export delta -11.00 kWh and the emissions delta 4.44 kg, although control and baseline coincide; they are now below 4e-6, the float32 rounding of the reference series. The reference series now sum every member that has been active, each over the steps at which it was a member. ([#182](https://github.com/citylearn-project/CityLearn/pull/182))
- **Electrical-service histories across topology events.** A member's requested-pressure, total-power and per-phase power histories were erased when it rejoined or when one of its assets changed, and the electrical-service and phase KPIs lost the earlier steps. They are now kept. ([#182](https://github.com/citylearn-project/CityLearn/pull/182))
- **Robustness noise.** With `noise_std > 0`, Gaussian noise could make solar generation, solar irradiance and carbon intensity negative, add generation at night and push outdoor relative humidity outside [0, 100] %. One rule now bounds the noisy values: solar quantities stay `>= 0` and get no noise at night, humidity stays within [0, 100] % and carbon intensity stays `>= 0`. The noise draws are unchanged, so values within range are bit-identical. Solar generation noise uses the generation series for its shape instead of the indoor temperature series; both have the same length, so the draws are the same. Runs with `noise_std = 0`, including all bundled datasets, are unchanged. See the [migration guide](migration.md#upgrade-from-350-to-360). ([#204](https://github.com/citylearn-project/CityLearn/pull/204))
- **Battery discharge features during outages.** During a power outage the entity `storage` table reported `can_discharge = 0` and `available_discharge_power_kw = 0`, although the battery can discharge into the islanded building up to its local load ([#220](https://github.com/citylearn-project/CityLearn/issues/220)). These features now report the battery's discharge capacity without the grid export headroom, as #205 does for vehicle-to-building discharge; the simulator still limits the discharge to the local load. The rule-based baselines read `can_discharge`, so they now use the battery during outages. In the week with the most outages of `pt_rec_30/evaluation/rec_30_robustness.json` and `rec_30_combined.json`, the BAU discharges 1.2 kWh more and the normalized unserved energy during outages falls from 0.0015 to 0.0007 and from 0.0017 to 0.0008; cost and emissions are unchanged. In `pt_rec_100/evaluation/rec_100_allin.json` the observations change but the BAU KPIs of that week do not. Datasets without outages, and the flat interface, are unchanged. See the [migration guide](migration.md#upgrade-from-350-to-360). This closes [#220](https://github.com/citylearn-project/CityLearn/issues/220). ([#221](https://github.com/citylearn-project/CityLearn/pull/221))

Baselines:

- **Baselines without the `entity_core_electrical` bundle.** Two changes apply only to datasets whose schema does not enable that bundle; `pt_rec_*` and `citylearn_challenge_2022_phase_all_plus_evs` enable it and are unchanged. First, the BAU battery reserved the charger's nominal power for a connected EV even when the EV accepted much less, for example in the last step before 100% SOC, and discharged for that demand; it now reserves the power the EV can accept, estimated from the observed SOC, battery capacity, charger power and efficiency as the simulator computes `available_charge_power_kw` ([#190](https://github.com/citylearn-project/CityLearn/issues/190)). Second, every baseline took the last interval's export as PV surplus, so when a battery discharge overshot the load and was exported, the battery recharged from the grid in the next step (22.8 kWh in the first 48 hours of `citylearn_three_phase_electrical_service_demo` with the BAU); only PV above the observed load now counts as surplus. The definition versions become `immediate-full-charge-v3`, `immediate-user-target-v2`, `basic-v3`, `smart-local-v3` and `community-v3`. Over 30 days, the control cost changes by −0.2% to −2.4% and the emissions by −0.8% to −2.5% for every baseline on `citylearn_challenge_2022_phase_all`, `citylearn_challenge_2023_phase_2_local_evaluation` and `citylearn_three_phase_electrical_service_demo`, except the default BAU on the last one, which costs 0.4% more because its battery now stores PV that previously went to the community market. See the [migration guide](migration.md#upgrade-from-350-to-360). The first change addresses consequence 2 of [#190](https://github.com/citylearn-project/CityLearn/issues/190); consequence 1, the one-step battery lag, is unchanged, and [#190](https://github.com/citylearn-project/CityLearn/issues/190) stays open. ([#213](https://github.com/citylearn-project/CityLearn/pull/213))
- **Baselines read corrupted observations under the flat interface.** Under the flat interface the env corrupts only the flat vectors, and the baselines, which read entity observations, decided from uncorrupted values; under the entity interface they read the corrupted ones ([#192](https://github.com/citylearn-project/CityLearn/issues/192)). Run as controllers (`predict(observations)`), they now get the step's robustness observation events applied to their entity observations as the entity interface applies them, and take the same actions under both interfaces. No random stream is consumed, and the env's flat observations and robustness history are unchanged; the controller KPIs of flat runs with observation events can change. The native BAU reference of `evaluate_v2()` (`predict([])`) stays uncorrupted. See the [migration guide](migration.md#upgrade-from-350-to-360). ([#212](https://github.com/citylearn-project/CityLearn/pull/212))

Agents and wrappers ([#208](https://github.com/citylearn-project/CityLearn/pull/208)):

- **`TabularQLearning`** no longer bootstraps from the next state on terminal transitions.
- **`MARLISARBC`** explores with its RBC; it used to explore with random actions.
- **`MARLISA` with `pca_compression < 1`** sizes its networks to the PCA output instead of failing at the first update.
- **Discrete wrappers.** `TabularQLearningObservationWrapper` declares exactly the `prod(bins)` states it encodes (it declared `prod(bins + 1) - 1` and could encode a state outside the space), and `DiscreteObservationWrapper` keeps values above the observation space in the top bin. `DiscreteObservationWrapper` and `DiscreteActionWrapper` bin the spaces of the env they wrap, so they work over the normalized wrappers. `ClippedObservationWrapper` no longer modifies the environment's cached observations.
- **`OnehotEncoding`** raises `ValueError` for a value outside its classes.

Data loading ([#209](https://github.com/citylearn-project/CityLearn/pull/209)):

- **Charger files with blank or float states.** Charger states are parsed as numbers. A blank cell used to make every state of the charger unreadable, so no EV connected.
- **`InventoryBattery` EVs** load without `nominal_power`, which the battery derives from `max_charge_kw` and `max_discharge_kw`.
- **Random initial EV SOC** is drawn within the battery's declared `min_soc` and `max_soc`; an `InventoryBattery` used to fail when the draw from [0, 1] fell outside them.
- **Entity observations with `max_soc < 1`** report `soc_max_ratio`, the energy to full and the available charge power up to `max_soc` instead of a full battery.

Datasets and dataset cache:

- **Incomplete dataset caches.** A cached dataset counted as complete as soon as its `schema.json` existed, so a cache left by an interrupted download raised `FileNotFoundError` for its first missing file. A cache is now complete only when every input file that `CityLearnEnv` reads from the schema exists; an incomplete cache is replaced in one step, and offline mode names the missing files ([#176](https://github.com/citylearn-project/CityLearn/issues/176), [#181](https://github.com/citylearn-project/CityLearn/pull/181)).
- **Dataset environment variables.** `CITYLEARN_OFFLINE`, `CITYLEARN_DATASET_GITHUB_ACCOUNT`, `CITYLEARN_DATASET_REPOSITORY` and `CITYLEARN_DATASET_TAG` are read when `CityLearnEnv` or `DataSet` is created instead of once at import, and `CityLearnEnv(offline=None)` honours `CITYLEARN_OFFLINE` ([#198](https://github.com/citylearn-project/CityLearn/pull/198)).
- **Dataset names.** `DataSet.get_dataset_names()` keeps a dataset whose name occurs in its parent path and accepts a `datasets_path` with a trailing slash; concurrent first calls list GitHub once and write the cached list atomically. The misc files share the dataset cache code ([#199](https://github.com/citylearn-project/CityLearn/pull/199)).
- **15 s Parquet datasets load from the dataset cache.** The schemas of `citylearn_three_phase_electrical_service_demo_15s_parquet`, `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet` and `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet` set a repository-relative `root_directory`. Passing the schema path returned by `DataSet().get_dataset(name)` to `CityLearnEnv` resolved it against the cache folder and raised `FileNotFoundError` for `<cache>/<dataset>/data/datasets/<dataset>/Building_1.parquet` ([#194](https://github.com/citylearn-project/CityLearn/issues/194)). The three schemas now set `"root_directory": null`, like the other datasets. `CityLearnEnv(name)` and schema paths inside a repository checkout already found the files and still read the same folder. ([#197](https://github.com/citylearn-project/CityLearn/pull/197))

Exports, CLI and files ([#207](https://github.com/citylearn-project/CityLearn/pull/207), [#202](https://github.com/citylearn-project/CityLearn/pull/202), [#203](https://github.com/citylearn-project/CityLearn/pull/203)):

- **BAU time-series export.** The BAU export writes the executed time steps only, like the control exports. It used to add the terminal step, a copy of the last executed step, which inflated totals summed from the file.
- **Charger exports.** Without an EV, the charger row writes `-1.00` under `EV SOC-%` instead of adding an `EV SOC` column.
- **CLI evaluation.** `citylearn simulate ... evaluate` and `train --evaluate` no longer fail (`All arrays must be of the same length`, or `not enough values to unpack` with `-te`), and `train --evaluate` evaluates the trained agent instead of a new one.
- **Schema agent attributes.** `load_agent()` without `agent` keeps `schema['agent']['attributes']` when keyword arguments such as `env=` are passed; keyword arguments override them. `Simulator(..., agent_name=None)` therefore builds the schema's agent with the schema's parameters.
- **Windows.** `run_work_order()` activates virtual environments with `activate.bat`, which `cmd.exe` can run. JSON and YAML files are read and written as UTF-8, so non-ASCII text in schemas is no longer decoded as cp1252.
- **Multi-community KPI comparison.** `load_kpis()` and `compare_exports()` read multi-community KPI exports, which repeat each name once per community, instead of raising `Duplicate KPI/name rows`.
- **JSON files with NumPy values.** `FileHandler.write_json` writes NumPy booleans, integers and floats as JSON booleans and numbers, and NumPy arrays of booleans and numbers as lists, instead of their text (`2.5` instead of `"2.5"`, `[1.0, null]` instead of `"[ 1. nan]"`). With `ignore_nan=False`, a NaN NumPy float raises `ValueError` like a Python float. namedtuples and `Decimal` values are written as before, and the export manifests are unchanged. See the [migration guide](migration.md#upgrade-from-350-to-360). ([#203](https://github.com/citylearn-project/CityLearn/pull/203))
- **pandas 3.** Exports no longer emit the two pandas 3 deprecation warnings, and a Parquet render column that mixes text and numbers is written instead of raising `ArrowTypeError`. Export files are unchanged ([#202](https://github.com/citylearn-project/CityLearn/pull/202)).

### Performance

None of these changes a result; each PR compared trajectories and KPIs bit for bit with master.

- **Single time steps.** Per-step code reads one time step of device and storage series instead of rebuilding the whole series, and `evaluate_v2()` builds its records without DataFrame scans ([#183](https://github.com/citylearn-project/CityLearn/pull/183)).
- **Time-series windows.** `TimeSeriesData` keeps each variable's episode window as a plain attribute, so reading weather, pricing, carbon, charger and energy-simulation values no longer goes through a Python `__getattribute__` and a new slice per read ([#210](https://github.com/citylearn-project/CityLearn/pull/210)).
- **District counterfactuals.** The twelve district `*_without_storage*` series sum a NumPy matrix instead of building a DataFrame; this speeds up `evaluate()` and `evaluate_v2()`, not the simulation step ([#206](https://github.com/citylearn-project/CityLearn/pull/206)).
- **Baseline resets.** The baselines build their policy engine once per agent instead of at every episode reset; the first `predict()` after a reset takes 48 ms instead of 81 ms (flat) and 22 ms instead of 54 ms (entity) on `citylearn_challenge_2022_phase_all_plus_evs` ([#211](https://github.com/citylearn-project/CityLearn/pull/211)).

### New opt-in features

These are off by default; existing schemas and results are unchanged.

- **Reward for load left unserved during power outages.** During an outage a building cannot import, so its net consumption is zero and rewards built on grid import give no signal about the load that PV and storage leave unserved. `OutageUnservedEnergyReward(coefficient, base_reward)` subtracts `coefficient` times that unserved energy from a base reward, and the new flat observation `power_outage_unserved_energy` (kWh per step, last settled step) gives it per building with the definition of the `power_outage_normalized_unserved_energy_total` KPI ([#188](https://github.com/citylearn-project/CityLearn/issues/188)). The reward works under both interfaces; the observation is flat only. Both are opt-in, so existing schemas and results are unchanged. ([#195](https://github.com/citylearn-project/CityLearn/pull/195))
- **Time-varying available grid power.** `buildings.<name>.electrical_service.available_grid_power` references a per-step series of the power a building may import, in kW, from a file with one column per building or a named column ([#119](https://github.com/citylearn-project/CityLearn/issues/119)). The import limit in force at a step is the smaller of the static `limits.total.import_kw` and the series value, and every reader of the total import limit uses it: the electrical-service allocation (EV chargers and the battery are curtailed first; fixed load stays served and counts as a violation), deferrable start feasibility, the headroom observations, the EV feasibility KPI and the electrical-service violation KPI. A limit of 0 kW does not island the building; outages stay in `power_outage`. The new flat observation `available_grid_power` reports the limit for the coming interval when a series is set, and the rule-based baselines cap their planned import headroom with it. Buildings without a series are unchanged. See the [schema reference](schema_reference.md#available-grid-power). ([#216](https://github.com/citylearn-project/CityLearn/pull/216))
- **Vehicle-to-building backup during outages (opt-in).** With `power_outage.vehicle_to_building: true`, a connected EV may discharge to its building while the grid is down, as a vehicle-to-home backup. The discharge is limited to the non-shiftable load and the thermal device load that PV and the battery leave uncovered, so the building exports nothing to the failed grid. Under the entity interface, the charger's `can_discharge` and `available_discharge_power_kw` report the vehicle's discharge capacity during the outage. The discharge can take the vehicle below its required departure SOC; that is left to the controller and shows in the EV departure KPIs. The option is off by default, and results without it are unchanged. See the [migration guide](migration.md#upgrade-from-350-to-360). ([#205](https://github.com/citylearn-project/CityLearn/pull/205))

### Build and CI

- **Python 3.10 or newer.** CityLearn now requires Python 3.10 and is tested on Python 3.10 to 3.14, with NumPy 1.x on 3.10. Python 3.9 reached its end of life in October 2025. On Python 3.9, `pip` keeps resolving CityLearn 3.5.0. The CLI commands `simulate train` and `simulate evaluate` used `datetime.UTC`, which exists only from Python 3.11, and failed on Python 3.10; they now use `datetime.timezone.utc`. See the [migration guide](migration.md#upgrade-from-350-to-360). ([#218](https://github.com/citylearn-project/CityLearn/pull/218))
- **Package metadata in `pyproject.toml`.** The metadata moves from `setup.py` to a PEP 621 `[project]` table and `setup.py` is removed; the wheel holds the same files ([#201](https://github.com/citylearn-project/CityLearn/pull/201)).
- **Install smoke and compatibility table.** CI builds the wheel, installs it with its PyPI dependencies and runs a simulation and export smoke on macOS (arm64) and Windows with Python 3.10 and 3.14; the Ubuntu build job already ran it on the installed wheel ([#138](https://github.com/citylearn-project/CityLearn/issues/138)). The installation guide gains a compatibility table of Python and dependency versions for every release from 1.5.0 ([#150](https://github.com/citylearn-project/CityLearn/issues/150)), kept in step with `requirements.txt` by a test, and the GitHub Actions are updated ([#217](https://github.com/citylearn-project/CityLearn/pull/217)).
- **Windows paths in tests.** The nested-dataset download tests compare paths in POSIX form, so they pass on Windows ([#200](https://github.com/citylearn-project/CityLearn/pull/200)).

### Validation

On master at the release commit, with Python 3.10 and NumPy 2: the full test suite passed (1,897 tests, 2 skipped) and the strict runtime audit passed (physics, entity contracts, all 41 bundled datasets and the fixed-command references). The sdist and wheel built and passed `twine check`. The wheel, installed with its dependencies in a clean virtual environment, passed `pip check` and the installed-package simulation and export smoke. CSV and Parquet exports of `pt_rec_4` made with 3.6.0 opened in the CityLearn UI result importer with the same 1,036 KPI rows and 15 series, and the UI test suite passed. The release CI covered Python 3.10 to 3.14, NumPy 1 on 3.10, the runtime audits and the install smoke on macOS and Windows.

### Contributors

- **Mark Colley** ([@M-Colley](https://github.com/M-Colley)): the physics, KPI, baseline, agent, data-loading, dataset-cache, export and build fixes, the performance work and vehicle-to-building backup in [#181](https://github.com/citylearn-project/CityLearn/pull/181), [#182](https://github.com/citylearn-project/CityLearn/pull/182), [#183](https://github.com/citylearn-project/CityLearn/pull/183), [#185](https://github.com/citylearn-project/CityLearn/pull/185), [#197](https://github.com/citylearn-project/CityLearn/pull/197), [#198](https://github.com/citylearn-project/CityLearn/pull/198), [#199](https://github.com/citylearn-project/CityLearn/pull/199), [#200](https://github.com/citylearn-project/CityLearn/pull/200), [#201](https://github.com/citylearn-project/CityLearn/pull/201), [#202](https://github.com/citylearn-project/CityLearn/pull/202), [#203](https://github.com/citylearn-project/CityLearn/pull/203), [#204](https://github.com/citylearn-project/CityLearn/pull/204), [#205](https://github.com/citylearn-project/CityLearn/pull/205), [#206](https://github.com/citylearn-project/CityLearn/pull/206), [#207](https://github.com/citylearn-project/CityLearn/pull/207), [#208](https://github.com/citylearn-project/CityLearn/pull/208), [#209](https://github.com/citylearn-project/CityLearn/pull/209), [#210](https://github.com/citylearn-project/CityLearn/pull/210), [#211](https://github.com/citylearn-project/CityLearn/pull/211), [#212](https://github.com/citylearn-project/CityLearn/pull/212), [#213](https://github.com/citylearn-project/CityLearn/pull/213), and the time-varying available grid power, install smoke, compatibility table and Python floor of #196, merged as [#216](https://github.com/citylearn-project/CityLearn/pull/216), [#217](https://github.com/citylearn-project/CityLearn/pull/217) and [#218](https://github.com/citylearn-project/CityLearn/pull/218).
- **Prawal Pokharel** ([@prawalpokharel](https://github.com/prawalpokharel)): the outage unserved-energy reward and observation in [#195](https://github.com/citylearn-project/CityLearn/pull/195).
- **Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)): reviewed, validated and integrated the release, split #196 into [#216](https://github.com/citylearn-project/CityLearn/pull/216), [#217](https://github.com/citylearn-project/CityLearn/pull/217) and [#218](https://github.com/citylearn-project/CityLearn/pull/218) with the Python 3.10 floor, and fixed the battery discharge features during outages in [#221](https://github.com/citylearn-project/CityLearn/pull/221).

[Full changelog](https://github.com/citylearn-project/CityLearn/compare/v3.5.0...v3.6.0)

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
