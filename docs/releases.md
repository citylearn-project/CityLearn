# Releases

Changes, compatibility, validation and measured performance for the current
CityLearn release. Older notes are retained in the [release archive](releases_archive.md).

Portuguese version: [pt/releases.md](pt/releases.md).

For package publication, version policy and the release checklist, see the
[publishing guide](publishing.md).

## Unreleased

### Added

- **Reward versions.** `Electric_Vehicles_Reward_Function`, `ComfortReward` and `SolarPenaltyAndComfortReward` accept `version`, and version 2 follows their documented definitions ([#249](https://github.com/citylearn-project/CityLearn/issues/249)). In version 1, a building with EV chargers got only its EV terms, a building without chargers got 0, and leaving 0.25 or more below the required departure SOC added `weights['soc_under'] ** 2`, a bonus of +25 with the default weights; with a required SOC of 0.8, departing at 0.2 scored +15 and departing at 0.65 scored -20. Version 2 adds the MARL base reward to every building and replaces the bonus with `min(2 * w, -(w ** 2))` (-25), so the same departures score -35 and -20. In cooling and heating mode, the version 1 comfort reward took heating or cooling from the larger demand at the step, so in heating mode at 21.5 °C with a 20 °C set point it was 0 with the heater off and -1.5 with it on; version 2 takes it from `hvac_mode` and gives -1.5 in both cases. Version 1 stays the default, so bundled schemas and trained policies keep their reward, and the reward evidence in the environment metadata records the version. See the [migration guide](migration.md#unreleased).

### Fixed

- **Generic agents on the entity interface.** Under the entity interface the action and observation spaces are dictionaries of entity tables, so `Agent` and `ZeroActionBaselineAgent` failed with `AttributeError` at the first `predict()`. They now keep the flat spaces and return flat-like action vectors, which the entity interface accepts, also under a dynamic topology. `SAC`, `SACRBC`, `MARLISA`, `MARLISARBC` and `TabularQLearning` read flat observation vectors and now raise a `ValueError` that names the flat interface on the entity interface. Flat runs are unchanged ([#250](https://github.com/citylearn-project/CityLearn/issues/250)).
- **Rule baselines as SACRBC and MARLISARBC exploration controllers.** `rbc` accepts any agent instance, agent class or import path, including `RBCBasicPolicy`, `RBCSmartPolicy`, `RBCCommunityPolicy` and `BusinessAsUsualAgent`, which raised `TypeError` as instances and `ValueError` for the SAC hyperparameters as classes. A controller built from a class or a path no longer receives the learner's hyperparameters (`lr`, `batch_size`, `hidden_dimension`, ...); the other keyword arguments still reach it. The bundled `RBC` classes ignored those hyperparameters, so their runs are unchanged ([#250](https://github.com/citylearn-project/CityLearn/issues/250)).
- **Non-finite actions.** A NaN action used to pass every `min`/`max` limit unchanged, so a NaN storage action became the largest possible discharge: on `tests/data/minute_ev_demo` the battery went from 50% to 0% SOC in one 15-minute step, twice its power limit. `env.step()` now raises `ValueError` for NaN or infinite actions on both interfaces, including the entity `map` and per-entity overrides (the entity interface used to clip infinity to a bound and apply non-finite overrides as 0), and storage `charge()` rejects non-finite energy ([#228](https://github.com/citylearn-project/CityLearn/issues/228)).
- **Physics invariant checks.** With `physics_invariant_checks=True`, a NaN or infinite state now counts as a violation instead of being read as 0, and the checks raise `PhysicsInvariantError`, a subclass of `AssertionError`, so `python -O` no longer disables them ([#228](https://github.com/citylearn-project/CityLearn/issues/228)). Replacing the net-balance identity with independent identities stays open in that issue.
- **EV deadline features.** In the step a vehicle departs with energy still missing, `required_average_power_kw`, `avg_power_to_departure_kw`, `charging_slack_kw`, `departure_feasibility_ratio` and `min_required_action_normalized` reached about 1e7, far outside their observation bounds. They now saturate at their bounds and keep their meaning ("not deliverable in time"); the rule baselines take the same actions and the KPIs are unchanged ([#242](https://github.com/citylearn-project/CityLearn/issues/242)).
- **CLI.** `citylearn list_datasets` and `list_default_time_series_variables` print one item per line to stdout and exit with 0; they used to print a Python list to stderr and exit with 1. `run_work_order` exits with 1 when a job fails, and `list_datasets` no longer reads the dataset cache while the parser is built ([#252](https://github.com/citylearn-project/CityLearn/issues/252)).
- **Invalid configuration fails early.** Unknown `CityLearnEnv` keyword arguments raise `TypeError` with a suggestion (a typo such as `physics_invariants_checks=True` used to be ignored). Topology events that reference a member missing from the schema, and asset overrides with unknown keys or invalid values, fail at construction instead of when the event fires (or being ignored). `community_market.local_trading_enabled` accepts `"false"`, `"no"` and `"0"`, which used to enable trading, and malformed or reversed `episode_time_steps` windows raise a clear error ([#253](https://github.com/citylearn-project/CityLearn/issues/253)).
- **Per-building reward functions.** With the schema's `reward_function.type` mapped per building, every building's function read the first building's metadata and functions were paired with buildings by position. With `SolarPenaltyReward`, a building with a 10 kWh battery next to one without a battery got 0 instead of -7.5. Each function now reads its own building's metadata and is paired by building name, also when members join or leave under a dynamic topology. No bundled dataset uses per-building reward functions. See the [migration guide](migration.md#unreleased) ([#249](https://github.com/citylearn-project/CityLearn/issues/249)).

### Changed

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
- **Undefined service KPIs.** The deferrable start delay without completed cycles, ratios with a missing operand and the deferrable service ratios to the BAU when no cycle was due are now missing instead of 0 or 1. ([#243](https://github.com/citylearn-project/CityLearn/issues/243))
- **Portfolio rates.** `MultiCommunityEnv` pools the portfolio EV departure rates and means, service levels, start delay and self-consumption from their additive denominators instead of weighting them by community. ([#244](https://github.com/citylearn-project/CityLearn/issues/244))
- **BAU ramping average.** `district_energy_grid_shape_quality_ramping_average_business_as_usual_kw` was the sum of upward ramps over the episode. It is now the mean per step transition; the sum is kept as `*_ramping_total_*_kw`. ([#245](https://github.com/citylearn-project/CityLearn/issues/245))

### Physics

Work package 4 of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), in [#279](https://github.com/citylearn-project/CityLearn/pull/279).

- **Versioned physics.** `physics_version` (schema key and `CityLearnEnv` argument) selects the physics of a run: `1` is the physics of 3.6.0 and earlier, and `2`, the default, holds the corrections of the physics work package of the 3.6.0 audit ([#226](https://github.com/citylearn-project/CityLearn/issues/226)). The BAU reference of `evaluate_v2()` uses the version of the evaluated environment, and the run metadata of the exports records it. See the [migration guide](migration.md#physics-version).
- **Standby loss of EVs away from their charger.** The away-from-charger SOC drift started from the previous step and discarded that step's standby loss, so an EV with a non-zero battery `loss_coefficient` kept its charge while away. Under physics version 2 the drift starts from the SOC after the loss, as it already did for suspended EVs ([#236](https://github.com/citylearn-project/CityLearn/issues/236)).
- **HVAC demand caps at steps longer than one hour.** The cooling and heating demand caps compared an energy per dataset step with the device's available power, which capped HVAC output at one hour of nominal power per step. Under physics version 2 the heat pump and the electric heater compare energy with energy ([#235](https://github.com/citylearn-project/CityLearn/issues/235)).
- **Autosizing at sub-hourly resolution.** Under physics version 2 storage tanks hold one hour of peak demand power (the `duration` autosize attribute changes it), so 15-minute data get the same tanks as hourly data instead of a quarter of them, and PV autosizing groups years by the dataset resolution and repeats the hourly PVWatts output at sub-hourly steps, where it used to fail ([#233](https://github.com/citylearn-project/CityLearn/issues/233)).
- **Battery discharge power.** `capacity_power_curve` describes how charging power tapers near full charge, but it also limited discharge, so a full battery could discharge at only a fraction of its nominal power. Under physics version 2 a new battery attribute, `discharge_power_curve`, limits discharge; it defaults to a flat curve at `nominal_power` and can derate at low state of charge, and `InventoryBattery` keeps its `max_discharge_kw` ([#227](https://github.com/citylearn-project/CityLearn/issues/227)).
- **Battery discharge during outages.** An islanded battery's discharge was capped by a pre-step load estimate that ignored the thermal storage discharge and the device limits, so the battery could discharge more than the building consumed and the surplus was reported as PV curtailment, even without PV. Under physics version 2 the battery discharges after the step's thermal demand and thermal storage discharges and only up to the islanded load that PV leaves, and `physics_invariant_checks` asserts it ([#229](https://github.com/citylearn-project/CityLearn/issues/229)).
- **One-way storage efficiency.** `StorageDevice.round_trip_efficiency` returned the one-way efficiency, the square root of `efficiency`. `one_way_efficiency` now holds that value, and `round_trip_efficiency` keeps it with a `DeprecationWarning`; the metadata and the entity feature `round_trip_efficiency_ratio` keep their names and values. `Battery.efficiency_history` gains one entry per charge or discharge instead of two ([#226](https://github.com/citylearn-project/CityLearn/issues/226)).

Physics version 1 reproduces 3.6.0: the BAU and `RBCSmartPolicy` give bit-identical series and `evaluate_v2()` tables to 3.6.0 on `citylearn_challenge_2022_phase_all_plus_evs`, `citylearn_challenge_2023_phase_2_local_evaluation`, `pt_rec_4`, `pt_rec_30` and the outage week of `pt_rec_30/evaluation/rec_30_robustness.json`, and the frozen refactor and NumPy references run under it. Under version 2 the discharge curve changes the challenge datasets slightly: over four weeks of `citylearn_challenge_2022_phase_all_plus_evs` the BAU imports 0.05% less, and over the 30 days of `citylearn_challenge_2023_phase_2_local_evaluation` the BAU costs 0.25% more, because a full battery now discharges at its nominal power. Rerun results under version 2, or set `physics_version=1` to reproduce 3.6.0.

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
