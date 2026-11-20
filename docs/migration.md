# Moving an existing project to CityLearn v3

Both the distribution and import name are `citylearn`. Install it from PyPI, or
use the [developer guide](developer_guide.md) for a repository checkout.

## Keep the controller loop explicit

```python
observations, info = env.reset(seed=0)
observations, rewards, terminated, truncated, info = env.step(actions)
```

Stop at `terminated or truncated`. `info` is the last return value, not the third.
The flat interface retains one observation/action vector per building, or one
combined vector with `central_agent=True`. Read action and observation order
from the environment rather than hard-coding positions.

## Choose the interface and timestep

Start fixed-membership controllers with `interface="flat"`. Use
`interface="entity"` for identified entity tables, relational edges and dynamic
membership. Entity observations are an input representation; a GNN or Transformer
policy must still be supplied by the user.

Match `seconds_per_time_step` to the data cadence. Energy columns use `kWh/step`;
power limits use `kW`. See the [unit contract](data_unit_contract.md).

## Choose the evaluation API

`evaluate()` retains legacy cost-function names. `evaluate_v2()` returns the
structured KPI names used by the current exports and scorecard. The `v2` in the
method name denotes the KPI interface, not CityLearn version 2.

The [scorecard](scorecard.md) distinguishes the conventional counterfactual
baseline from the native business-as-usual controller and explains service,
target accuracy and requested/applied electrical-limit indicators.

## Resolve public and local data separately

Public dataset names are resolved against the installed package's release tag.
Use `DataSet().get_dataset_names()` to see that version's catalogue (import
`DataSet` from `citylearn.data`). Supply your own
local schema and files for data that are not in the public catalogue; a
repository-relative path is not created by `pip install`.

The [release history](releases.md) retains version-specific changes and the
development-line history.

## Unreleased

### Numeric and configuration hygiene

These changes require no dataset, schema or KPI migration. Valid runs give the same results; a few silent mistakes now raise.

- **Non-finite actions raise.** `env.step()` raises `ValueError` for NaN or infinite actions. A training loop that used to continue with a diverged policy now stops at the first bad action; check the policy output or replace non-finite values before stepping.
- **Unknown constructor arguments raise.** `CityLearnEnv(..., **kwargs)` raises `TypeError` for an unknown keyword argument, with the closest valid name. Remove or correct arguments that were silently ignored before.
- **Topology events are validated at construction.** An event that names a member missing from the schema, or an asset override with an unknown key or an invalid value, raises when the environment is built. Members declared in the schema but not loaded (`buildings=[...]`) are still accepted.
- **Logging.** CityLearn no longer configures the root logger. Warnings still print; to see INFO messages, configure logging in your script, for example `logging.basicConfig(level=logging.INFO)`. `learn(logging_level=...)` and `DataSet(logging_level=...)` set the level of the `citylearn` logger only when passed.
- **Export location.** Exports go to `./render_logs` in the working directory by default, and relative `render_directory` values resolve against the working directory. Pass an absolute `render_directory` to keep the previous location.
- **Physics invariants** raise `PhysicsInvariantError`, which is an `AssertionError`, so existing handlers keep working.

### Consecutive episode splits share their boundary row

An episode of N data rows executes N - 1 control steps: its last row is only
the terminal observation. Consecutive (non-rolling) splits of an integer
`episode_time_steps` used to advance by N rows, so the interval between the
last row of one episode and the first row of the next was never simulated in
any episode; daily episodes on hourly data never simulated 23:00-24:00.

Consecutive splits now advance by N - 1 rows (`episode_split_boundary='shared'`,
the default): each episode starts on the terminal row of the previous one, and
every interval up to the last complete split is simulated once. Episodes keep
N rows and N - 1 steps. The first episode is unchanged; later episodes start
earlier, so their results change. Rolling splits, explicit
`[(start, end), ...]` splits and whole-window episodes are unchanged.

- To keep day-aligned episodes that cover every hour of hourly data, use
  `episode_time_steps=25`: each episode then runs from 00:00 to the next 00:00.
- `episode_time_steps=1` with more than one split now raises a `ValueError`; an
  episode of one row has no interval to simulate.
- `episode_split_boundary='disjoint'` (constructor argument or schema key)
  restores the 3.6.0 splits.

### Dynamic topology: joining members, storage and district series

These changes only affect `topology_mode='dynamic'`:

- A member file shorter than the dataset is read as starting at the member's
  `add_member` time step. It was misaligned when `simulation_start_time_step`
  was not 0, which also affected the native BAU reference of every dynamic
  episode that does not start at row 0 (the BAU sidecar loads the episode
  window). A member that joins again after leaving needs a full-horizon file and
  now raises a `ValueError` otherwise, instead of reusing frozen rows. A file that
  ends before the member leaves still repeats its last row for the remaining
  steps, but now with a `UserWarning`.
- A member that joins (or rejoins) mid-episode starts its cooling, heating and
  DHW storage at `initial_soc`, as its battery already did, instead of empty.
- `env.non_shiftable_load`, `env.solar_generation`, `env.power_outage` and the
  other district sums of building series keep a departed member's past values
  and count a member only from the step it joins, like
  `net_electricity_consumption`. KPIs are unchanged by this item.
- An event at the terminal step no longer moves the buildings onto the
  unexecuted terminal row, so their series hold executed intervals only.

### Control step different from the dataset step

CityLearn reads one data row per control step and does not resample. A
`seconds_per_time_step` that differs from the dataset step therefore ran the
calendar, prices and EV schedules at the wrong rate while scaling energies by
`time_step_ratio`. Such a configuration now raises a `ValueError`. Set
`seconds_per_time_step` to the dataset step or resample the dataset; pass
`time_step_ratio_mode='compress'` (constructor argument or schema key) to keep
the 3.6.0 behaviour.

The dataset step is now inferred from every row (the median interval) rather
than from the first two rows, so one irregular row no longer rescales every
energy. Rows that mix cadences, where fewer than 90 % of the intervals match
that median, raise a `ValueError`; declare the step with
`dataset_seconds_per_time_step` if the calendar columns cannot be fixed. The
`time_step_ratio` constructor argument, previously ignored, must match the
inferred ratio. The bundled datasets all use their native step and are not
affected.

### Per-building reward functions and reward versions

When the schema's `reward_function.type` maps buildings to reward functions,
each function now reads its own building's metadata and is paired with its
building by name. Per-building functions that read building metadata, such as
`SolarPenaltyReward`, used the first building's storage capacities for every
building, so their rewards change; functions that read only observations, such
as `RewardFunction`, give the same rewards. Retrain policies trained with such a
schema. No bundled dataset uses per-building reward functions.

`Electric_Vehicles_Reward_Function`, `ComfortReward` and
`SolarPenaltyAndComfortReward` accept a `version` attribute. Version 1, the
default, is the reward of 3.6.0, so existing schemas and trained policies keep
their reward. Version 2 corrects the EV departure penalty, adds the base reward
and follows the HVAC mode in the comfort term, as the reward function overview
of the documentation describes. Set `"version": 2` in the
reward attributes for new training runs, and compare policies only within one
version. The reward evidence in the environment metadata records the version.

### KPI definitions

Several `evaluate_v2()` KPIs change definition, and the KPI definition version
(`kpi_definition_version`) becomes `2.0.0`. Simulations are unchanged; rerun
`evaluate_v2()` on saved environments, or rerun the episodes, before comparing
with 3.6.0 tables. The [KPI reference](kpis_reference.md#definitions-changed-after-360)
lists every changed row and the name that keeps its 3.6.0 value.

- **District ratios to the baseline** of import, net exchange and emissions are
  ratios of the district totals instead of means of the building ratios
  ([#237](https://github.com/citylearn-project/CityLearn/issues/237)). The
  3.6.0 values are published as `*_building_mean_ratio`, and the legacy
  `evaluate()` district rows still hold them.
- **District emissions** are those of the netted district import, so local
  sharing between members lowers them, consistent with district import and
  cost ([#238](https://github.com/citylearn-project/CityLearn/issues/238)).
  The sum over members is published as `district_emissions_total_*_member_sum_kgco2`.
  Building emissions are unchanged.
- **Building demand-response settlement** allocates the district credited energy
  and shortfall to buildings with the revenue and penalty weights, so building
  shortfall and compliance follow the district tolerance and cap
  ([#240](https://github.com/citylearn-project/CityLearn/issues/240)). District
  KPIs and all cash flows are unchanged. The demand-response definition version
  becomes `demand-response-audit-v2`.
- **Load-factor penalties** in `evaluate_v2()` use import power, and windows
  without import are undefined instead of a perfect 0
  ([#241](https://github.com/citylearn-project/CityLearn/issues/241)). The
  signed-net values are published as `*_signed_net_*`; the legacy `evaluate()`
  rows keep the signed-net series.
- **Undefined values stay undefined**: a ratio with a missing control or
  reference, the deferrable start delay without completed cycles, and the
  deferrable service ratios to the BAU when no cycle was due are now missing
  instead of 0 or 1 ([#243](https://github.com/citylearn-project/CityLearn/issues/243)).
  Code that reads these cells must handle `None`/NaN.
- **Portfolio rates** of `MultiCommunityEnv` (EV departure rates and means,
  service levels, start delay, self-consumption) are pooled from their additive
  denominators instead of weighted by community
  ([#244](https://github.com/citylearn-project/CityLearn/issues/244)).
- **BAU ramping average** is the mean upward ramp per step instead of the sum
  over the episode; the sum is published as `*_ramping_total_*_kw`
  ([#245](https://github.com/citylearn-project/CityLearn/issues/245)). The ratio
  to the BAU is unchanged.

### Physics version

Corrections to the simulated physics are grouped into versioned physics
definitions, selected with the `physics_version` schema key or the
`CityLearnEnv(physics_version=...)` argument, which takes precedence. Version
`1` is the physics of CityLearn 3.6.0 and earlier; version `2`, the default,
contains the corrections below. The native BAU reference of `evaluate_v2()`
uses the version of the evaluated environment, and exports record it in the
run metadata. To reproduce a 3.6.0 result, set `physics_version` to `1`; to
compare controllers, run them under the same version.

Version 2 changes no result on bundled datasets as shipped. It changes runs
that use the following:

- **EVs with a standby loss.** An EV away from its charger now keeps the
  standby loss of each step; version 1 discarded it, so a non-zero battery
  `loss_coefficient` had no effect while the EV was away
  ([#236](https://github.com/citylearn-project/CityLearn/issues/236)).
- **Steps longer than one hour.** The cooling and heating demand caps compared
  an energy per step with a power, which limited HVAC output to one hour of
  nominal power per step
  ([#235](https://github.com/citylearn-project/CityLearn/issues/235)).
- **Autosizing at sub-hourly resolution.** Storage tanks are sized to hold one
  hour of peak demand power (the `duration` autosize attribute, in hours,
  changes it) instead of the largest demand per step, so hourly data are sized
  as before and 15-minute data get the same tanks as hourly data. PV autosizing
  groups years by the dataset resolution and repeats the hourly PVWatts output
  at sub-hourly steps; at sub-hourly resolution it used to fail or to size the
  PV for a quarter of the demand
  ([#233](https://github.com/citylearn-project/CityLearn/issues/233)).

`StorageDevice.round_trip_efficiency` returned the one-way efficiency, the
square root of `efficiency`. Use `one_way_efficiency` for that value, or
`efficiency` for the round-trip efficiency; `round_trip_efficiency` keeps its
value, warns with `DeprecationWarning` and will be removed. Device metadata adds
`one_way_efficiency` and keeps `round_trip_efficiency` with the same value. The
entity feature `round_trip_efficiency_ratio` keeps its name and value, which is
the one-way efficiency. `Battery.efficiency_history` now gains one entry per
charge or discharge instead of two. No simulated value changes.

## Upgrade from 3.5.0 to 3.6.0

### Battery discharge features during outages

During a power outage the entity `storage` features `can_discharge` and
`available_discharge_power_kw` now report the battery's discharge capacity
instead of zero. Controllers that read them, including the BAU and the
rule-based baselines, can take different actions during outages, so the
native BAU reference changes on scenarios with outages under the entity
interface, such as `pt_rec_30/evaluation/rec_30_robustness.json`,
`rec_30_combined.json` and `pt_rec_100/evaluation/rec_100_allin.json`. This
change belongs to the same 3.6.0 baseline definitions as the change for
datasets without `entity_core_electrical` (`immediate-full-charge-v3` and the
others). Rerun the controller and its reference on those scenarios. Agents
trained on these features may need retraining.

### Baselines without the `entity_core_electrical` bundle

On datasets whose schema does not enable `entity_core_electrical`, the BAU and
the rule-based baselines take different actions: the BAU reserves only the EV
power the EV can accept, and no baseline counts the last interval's export as
PV surplus. Their definition versions change to `immediate-full-charge-v3`,
`immediate-user-target-v2`, `basic-v3`, `smart-local-v3` and `community-v3`, and
the native BAU reference of `evaluate_v2()` changes with them. Rerun the
controller and its reference before comparing with earlier results. Datasets
with the bundle, including `pt_rec_*` and
`citylearn_challenge_2022_phase_all_plus_evs`, are unchanged.

### Baselines under the flat interface with robustness observation events

`BusinessAsUsualAgent`, `RBCBasicPolicy`, `RBCSmartPolicy` and
`RBCCommunityPolicy` run as controllers under the flat interface now read the
corrupted observations, as they already did under the entity interface
([#192](https://github.com/citylearn-project/CityLearn/issues/192)). Their
actions and the controller KPIs of such runs can change. The native BAU
reference of `evaluate_v2()`, runs without observation events and runs under
the entity interface are unchanged.

### Robustness noise stays within physical ranges

Runs with `noise_std = 0`, which includes every bundled dataset, are unchanged.
With `noise_std > 0`, noisy solar generation and solar irradiance (and their
forecasts) are no longer negative and stay zero at night, outdoor relative
humidity stays within [0, 100] % and carbon intensity is no longer negative.
The noise draws are the same, so all other values, and the series of other
buildings and seeds, are unchanged. Runs whose solar or carbon series became
negative under noise change; agents trained on such series may need retraining.
See the [data unit contract](data_unit_contract.md#robustness-noise).
### Python 3.10 or newer

CityLearn requires Python 3.10 or newer. Environments on Python 3.9 keep
resolving CityLearn 3.5.0; upgrade the interpreter to use later releases.
### Vehicle-to-building backup during outages

New and off by default: `power_outage.vehicle_to_building` in a building schema
(`Building.outage_vehicle_to_building`). Without it nothing changes: an EV
cannot discharge while the grid is down. With it, a negative EV action during an
outage discharges the vehicle into the building, up to the islanded load that PV
and the battery do not cover. Results change only for buildings that enable the
option and request EV discharge during an outage.

### JSON files with NumPy values

No dataset, schema or simulation migration is required. Simulated trajectories,
KPIs and export manifests are unchanged.

- **JSON files with NumPy values.** `FileHandler.write_json` (in `citylearn.utilities`
  and `citylearn.utils.file_handler`) writes NumPy booleans, integers and floats as
  JSON booleans and numbers, and NumPy arrays of booleans and numbers as lists. They
  used to be written as text: `np.float32(2.5)` as `"2.5"`, `np.bool_(True)` as
  `"True"` and `np.array([1.0, np.nan])` as `"[ 1. nan]"`; they are now `2.5`,
  `true` and `[1.0, null]`. A `np.float32` is written with its exact value, so
  `np.float32(0.1)` becomes `0.10000000149011612`. Code that parsed these strings
  must read numbers instead. With `ignore_nan=False`, a NaN or infinite NumPy float
  now raises `ValueError`, as a Python float already did; it used to be written as
  `"nan"`. namedtuples (written as objects), `Decimal` values (written as numbers
  with their exact text) and all other values are written as before.

### BAU export, charger exports, CLI and file encoding

No dataset or schema migration is required. Simulated trajectories and KPIs are
unchanged.

- **BAU time-series export.** `exported_data_business_as_usual_ep<N>.csv` holds one
  row per building and one district row for each executed time step, as the
  control exports do. It used to add the terminal time step, whose values repeated
  the last executed step, so totals summed from the file counted that step twice.
- **Charger exports.** A charger without a connected or incoming EV writes `-1.00`
  under `EV SOC-%`, the column used when an EV is present. Charger export files no
  longer have a separate `EV SOC` column.
- **Schema agent attributes.** `CityLearnEnv.load_agent()` called without `agent`
  builds the schema's agent from `schema['agent']['attributes']` updated by the
  keyword arguments. Any keyword argument, such as the `env=` that `Simulator`
  always passes, used to discard the schema attributes, so
  `Simulator(..., agent_name=None)` built the schema's agent with its default
  parameters. Such runs now use the schema's parameters; pass keyword arguments to
  override them. `"attributes": null` is read as no attributes. An explicitly named
  agent, including the CLI default `BusinessAsUsualAgent`, still takes only the
  keyword arguments.
- **CLI.** `citylearn simulate ... evaluate` and `train --evaluate` complete and
  write the evaluation JSON, also with `-te`; `train --evaluate` evaluates the
  trained agent instead of a new one. Evaluation time series hold one row per
  executed time step, and a variable that a building does not have is reported as
  empty instead of repeating the previous variable. The CLI runs on Python 3.9 and
  3.10.
- **Windows.** `run_work_order(..., virtual_environment_path=...)` activates the
  environment with `Scripts\activate.bat` on Windows, detected automatically when
  `windows_system` is not given. JSON and YAML files are read and written as UTF-8
  instead of the locale's code page.

### Agents and wrappers

No dataset, schema or export-file migration is required. Environment trajectories
and KPIs for a given action sequence are unchanged; the results of the agents and
wrappers below change.

- **`TabularQLearning`.** A transition with `terminated=True` no longer bootstraps
  from the next state's Q-values, as for `SAC`; truncated transitions still do.
  Q-tables and the actions learned from them change.
- **`MARLISARBC`.** Exploration now uses the RBC passed as `rbc`. It used to discard
  the RBC's actions and explore with random actions while still advancing the RBC,
  so its exploration and everything learned from it change.
- **`MARLISA` with `pca_compression < 1`.** The networks read the PCA output
  (`int(pca_compression*(observations + coordination variables))` features). These
  runs used to fail at the first network update; `pca_compression=1` (the default)
  is unchanged.
- **Discrete and tabular wrappers.** `DiscreteObservationWrapper` puts values above
  the observation space's upper bound into the top bin; they used to get an index
  one past the `MultiDiscrete` space. `TabularQLearningObservationWrapper` numbers
  the `prod(bins)` states of its `Discrete` space with `itertools.product` over the
  bins; it used to enumerate one extra value per observation, declare
  `prod(bins + 1) - 1` states and give the last state an index outside the space.
  Saved Q-tables are therefore indexed differently and have a different size;
  retrain them. Episodes whose observations stay within the observation space
  otherwise learn the same Q-values.
- **Wrapped spaces.** `DiscreteObservationWrapper` bins the observations and
  bounds of the env it wraps, so over `NormalizedObservationWrapper` it bins the
  normalized features, including the cos and sin of periodic observations.
  `DiscreteActionWrapper` bins the action space of the env it wraps.
  `ClippedObservationWrapper` returns new lists instead of clipping the
  environment's cached observation lists in place.
- **`OnehotEncoding`.** A value that is not one of the classes raises `ValueError`
  naming the value, instead of `IndexError`.

### Data loading edge cases

No dataset, schema or export-file migration is required. The datasets shipped
with CityLearn load and simulate as before: none of their 455 charger files is
parsed differently, and none of their EVs uses `InventoryBattery`.

- **Charger states.** `electric_vehicle_charger_state` is parsed as a number. A
  blank cell makes pandas read the whole column as floats (`1.0`, `2.0`), which
  used to turn every state of that charger into "no state", so no EV ever
  connected. Values that are not non-negative integers remain "no state".
- **`InventoryBattery` EVs.** `nominal_power` may be omitted for an EV battery of
  type `InventoryBattery`, which derives it from `max_charge_kw` and
  `max_discharge_kw`. A `Battery` still requires it.
- **Random initial SOC.** An EV battery without `initial_soc` draws it uniformly
  between its `min_soc` and `max_soc` (0 and 1 when they are not declared, which
  gives the same values as before). An `InventoryBattery` with declared limits
  used to receive a draw from [0, 1], and the run failed when it fell outside them;
  where it fell inside, the initial SOC now differs.
- **Entity SOC limits.** For an `InventoryBattery` with `max_soc < 1`, the entity
  observations report `soc_max_ratio` as `max_soc`, and the energy and power a
  battery can still take (`energy_to_full_kwh`, `connected_ev_energy_to_full_kwh`,
  `flexible_energy_to_full_kwh`, charge headroom and available charge power)
  stop at `max_soc` instead of a full battery; `usable_soc_ratio` is relative to
  `max_soc`. Batteries without `max_soc` give the same values as before.

### Dynamic-topology district KPIs

No dataset, schema or export-file migration is required. Static topology results are
unchanged. In dynamic topology, KPIs change in two cases; rerun both the controller and
its reference before comparing with earlier results.

- **District reference series keep departed members.** The district
  `net_electricity_consumption*_without_storage*` series (the conventional baseline) summed
  only the members active when they were read, while the control series keep each
  member's consumption for the steps at which it belonged to the district. A member that
  had left therefore dropped out of the baseline side only. The reference series now sum
  every member that has been active, each over the steps at which it was a member, so a
  member that joins late no longer adds its PV-free series before it joins either. This
  changes the district baseline and delta totals (import, export, net exchange, emissions,
  and cost without the community market), the district export ratio to baseline and the
  district ramping, load-factor and peak ratios of scenarios with membership changes.
- **Electrical-service histories survive topology events.** The requested-pressure,
  total-power and per-phase power histories of a member were erased when it rejoined or
  when one of its assets was added or removed. They are now kept, so the
  `electrical_service_*` violation and requested-pressure KPIs and the phase peak and
  imbalance KPIs include the steps before the event.

### Sub-hourly power and energy units

These fixes leave runs whose dataset and control step are both 3600 s unchanged.
Runs with a sub-hourly `seconds_per_time_step`, or whose dataset resolution
differs from the control step (`time_step_ratio` other than 1), can change:

- Heat pumps and electric heaters no longer exceed `nominal_power` when they
  charge thermal storage at sub-hourly steps, and `available_nominal_power` is a
  power in kW at every step length.
- On native sub-hourly data (`time_step_ratio` 1), a device delivers at most
  `nominal_power` x step duration per step. Previously it could deliver
  3600 / `seconds_per_time_step` times that energy. Autosized devices are not
  affected, because autosizing already converts the demand per row to power; a
  device whose `nominal_power` was set to the largest demand per row (kWh read
  as kW) is now too small.
- During an outage, the local supply available to devices and to the
  non-shiftable load is converted from step energy to power and to dataset
  resolution; with hourly data at a 900 s step, loads previously received a
  quarter of that supply.
- `cooling_demand`, `heating_demand` and `dhw_demand` observations convert the
  storage discharge to dataset resolution, the unit of the device term and of the
  observation bounds.

**Undersized devices.** A device that cannot meet the demand left after its
storage no longer raises `AssertionError: demand is greater than ..._device max
output`. CityLearn clips the device output to its limit, as it already does
during outages, and warns once per device and episode with a `RuntimeWarning`.
The shortfall is unserved thermal energy: it is reported by
`building_thermal_service_audit_unserved_service_energy_kwh` and
`..._unserved_service_ratio` (and the district equivalents) and by
`env.get_kpi_family_audit()`. If a dataset relabelled from hourly to sub-hourly
rows now warns, its devices or its demand series do not match the new step:
autosize or enlarge the devices, or rescale the demand to energy per step.

### Estimates, diagnostics and schema options

- The base-power estimate behind electrical-service headroom, deferrable start
  checks, the outage battery limit and the feasibility KPIs no longer subtracts
  thermal storage discharge twice, and it counts escalator power. A requested
  escalator state now reduces the import headroom left for EV and battery
  actions in the same step. This applies at every step length, but only to
  buildings with an electrical-service limit and thermal storage or escalators;
  no bundled dataset combines them.
- `clip_reason_phase_headroom` and `clip_reason_export_headroom` are set only
  for the phases that carry the asset and for the clipped direction.
- `observations(normalize=True, periodic_normalization=False)` no longer raises
  `KeyError: 'month'`.
- `set_point_hold_time_steps` in a building schema now reaches building types
  whose constructor accepts it (`LogisticRegressionOccupantInteractionBuilding`).
  The Quebec neighbourhood datasets set it to 4: occupant set-point changes now
  revert to the schedule after 4 steps without interaction instead of holding
  for the rest of the episode, which changes their hourly results. Other
  building types ignore the key as before.

## Upgrade from 3.4.0 to 3.5.0

No dataset, schema, export-file or BAU migration is required; existing datasets and
KPIs are unchanged. 3.5.0 adds the [Portugal REC datasets](portugal_rec_datasets.md)
and downloads nested dataset folders. If you download several datasets within an
hour, set `CITYLEARN_GITHUB_TOKEN` (or `GITHUB_TOKEN`) to a GitHub token to raise
the anonymous limit of 60 API requests per hour.

## Upgrade from 3.3 to 3.4.0

No dataset, schema or export-file migration is required.

- **BAU.** `BusinessAsUsualAgent` still charges EVs at once to 100% by default
  (`immediate-full-charge-v2`), but it now decides from the entity observations,
  with the battery and appliance rules of the Algorithms BAU. The native BAU
  reference added by `evaluate_v2()` changes with it, so every
  `business_as_usual`, `delta_to_business_as_usual` and
  `ratio_to_business_as_usual` KPI can differ from 3.3. Rerun both the controller
  and its reference; do not mix 3.3 and 3.4 BAU values. To charge only to the
  user's requested departure SOC, set `business_as_usual_ev_charge_target='requested'`
  on the environment (or in the schema) and use
  `BusinessAsUsualAgent(env, ev_charge_target='requested')`.
- **Unlimited headroom.** In the entity tables, a building without an electrical
  service limit (or without a limit on a phase or direction) now publishes its
  headroom features (`charging_*headroom_kw`, `building_*_headroom_kw`,
  `*_phase_headroom_kw`) as 1,000,000 kW, the upper bound of their observation
  space, instead of 0 kW. 0 kW read as "no capacity left". Models trained on 3.3
  entity observations of such buildings saw 0 there; retrain or re-evaluate them.
- **BAU parameters.** The 3.3 constructor arguments `ev_target_soc`,
  `ev_follow_required_soc`, `ev_service_margin_rate`, `ev_service_floor_rate` and
  `storage_deadband_kw` no longer exist; unknown keyword arguments raise
  `ValueError`. `storage_min_soc`, `storage_max_soc` and `deferrable_start_action`
  keep their names and defaults. See the [baselines guide](baselines.md#default-parameters).
- **Removed names.** `NormalPolicy`, `NormalNoBatteryPolicy` and
  `ServiceOnlyBaselineAgent` are removed; use `BusinessAsUsualAgent`.
  `GridAwareBaselineAgent` and `CommunityAwareBaselineAgent` are removed; use
  `RBCSmartPolicy` and `RBCCommunityPolicy`. Code importing these names must be
  updated before upgrading to 3.4.0.
- **Rule-based baselines.** `RBCBasicPolicy`, `RBCSmartPolicy` and
  `RBCCommunityPolicy` are replaced by the Basic, Smart and Community baselines
  validated in the Soft-CPS Algorithms repository. Their decisions, parameters and
  results differ from 3.3. Pass parameters as keyword arguments, for example
  `RBCCommunityPolicy(env, community_import_threshold_kw=10.0)`.
- **Observations.** All baselines now decide from the named entity observations
  rather than from simulator objects. Code that changes a building series or a
  device after loading is seen by the baselines only through the observations
  the simulator publishes for that step.
- **Experiment identity.** `comparison_identity()` and the BAU reference
  metadata report `observation_access='entity_observations'` and include the
  definition version and resolved parameters.

## Upgrade from 3.3.0 to 3.3.1

No dataset, schema or export-file migration is required. The native BAU
reference built by `evaluate_v2()` now uses the entity interface whenever the
evaluated env does, so entity schemas with static topology and robustness events
on `ev`, `storage` or `pv` observations no longer fail. BAU actions and KPIs are
unchanged, because the BAU agent reads simulator state rather than observations.

## Upgrade from 3.2.0 to 3.3.0

No dataset, schema or export-file migration is required.

- **NumPy 2 and Python 3.12+:** `numpy<2` and `scikit-learn<=1.2.2` are no
  longer pinned. The occupant models of the Quebec datasets are read from their
  pickles without scikit-learn and evaluated with NumPy, giving predictions
  bit-identical to scikit-learn 1.2.2; loading them no longer runs code from the
  file. Arithmetic whose type NumPy 2 changed (NEP 50 promotion of float32
  scalars with Python numbers) is written to give NumPy 1's result, so
  observations, rewards and simulated time series are identical on both
  versions. KPIs can differ in the last binary digits (relative differences of
  order 1e-15): NumPy 2.3 and later add up more than 8,192 values in a different
  order, which affects totals over episodes longer than 8,192 time steps and the
  district Gini ratio of more than 90 members, and the equity audit's Gini ratio
  uses a BLAS dot product, whose last digit depends on the BLAS build and CPU.
- **Custom occupant models:** `RandomForestClassifier` and
  `DecisionTreeClassifier` pickles are read the same way, with any pickle
  protocol (0 to 5) and when the model was fitted with a
  `numpy.random.RandomState` as `random_state`. Predictions are those of the
  scikit-learn release that saved the model. Best-split decision trees from
  1.3, random forests from 1.4 and random-split decision trees from 1.6 route
  missing (NaN) inputs using `missing_go_to_left`. Older versions of each
  estimator reject those inputs, as do models with monotonic constraints
  saved with scikit-learn 1.4 through 1.8.
  Other pickled models are unpickled with the installed
  scikit-learn. If it cannot read one saved with scikit-learn 1.2.2 or earlier,
  install `scikit-learn==1.2.2` with `numpy<2` (Python 3.11 or older), or refit
  the model and save it with the installed release.
- **Experiment evidence:** KPI-export manifests written on Windows record input
  files and the engine source as on Linux and macOS (file paths below the dataset
  root with `/`, engine source hashed with LF line endings), so Windows exports
  of one dataset pair across locations and their hashes can be checked against
  the committed files. Linux and macOS evidence is unchanged. Runs on different
  operating systems still do not pair: `engine.runtime_versions` records the OS.
  [Portable experiment evidence](developer_guide.md#portable-experiment-evidence)
  lists the file-reference spellings that are normalised and how to update a
  checkout made before `.gitattributes`.
- **RL agent keyword:** pass `action_scaling_coefficient=` to `SAC`, `MARLISA`
  and other `RLC` agents. The misspelled `action_scaling_coefficienct=` still
  works with a `DeprecationWarning`; before, only the misspelling took effect.
- **Native BAU reference check:** `evaluate_v2()` raises a `ValueError` naming
  the setting when the reference, which is rebuilt from the schema and the
  constructor arguments, differs from the evaluated env as captured at its last
  `reset()`: the building order, a building's `simulate_power_outage` or active
  actions, or any parameter of its devices (heat pumps, heaters, storage tanks,
  PV, batteries, chargers, appliances and EV batteries), not only battery
  capacities. Before, the reference silently simulated the schema's values. A
  change made after `reset()` is not detected. Evaluate with
  `include_business_as_usual=False` in that case.

- **Dataset downloads:** `DataSet.get_dataset(name, directory=...)` copies the
  dataset into `directory/<name>` and returns that schema path. Failed
  downloads raise instead of being cached, and concurrent first downloads no
  longer interfere, including when they replace a cache folder missing
  `schema.json`. `filelock`, already installed with `torch`, is now a
  declared requirement.
- **SAC and MARLISA:** default schedules now work on episodes shorter than the
  default batch; inconsistent given values raise `ValueError` instead of
  `assert False`. Runs are repeatable from the environment seed. Agents saved
  with 3.2.0 resume training: the random streams they lack are derived from
  their seed. MARLISA fills in missing scikit-learn parameters using the
  installed defaults and refits its demand model on its whole buffer at the
  first update.

Fixes that **change results** where they apply:

- Storage activation and EV topology: the discharge reserve limits energy
  leaving a battery. A newly activated battery uses its configured initial SOC,
  including below the reserve. Removing or moving a charger preserves EV identity.
  While the EV is away, standby losses and seeded mobility continue to apply.
  A newly activated EV starts from its configured SOC, and an explicit arrival
  estimate is accounted for as external energy. Exports identify the charger
  that actually served the EV.

- Stochastic power outages: built-in models without an explicit seed now
  derive one from the environment seed, episode window and building name.
  The native BAU reference uses the same seed and outage signal.
- Agents: MARLISA's coordinated actions use each building's own policy;
  `TabularQLearning` bootstraps on the best next-state value; an explicit
  `action_scaling_coefficient` now takes effect (the default stays 0.5).
- KPI references: the native BAU reference re-applies `simulate_power_outage`,
  `solar_generation` and active/inactive action and observation overrides, to
  the same buildings when `buildings=` lists them in another order than the
  schema; with the community market enabled, legacy cost and the equity audit
  settle the counterfactual too. Autosized equipment in the reference is sized
  over the same data as the evaluated env, not only the current episode:
  `evaluate_v2()` no longer fails on the tx, vt and ca neighbourhood datasets
  when episodes are shorter than the data, and BAU KPIs of the 2020 and 2021
  challenge datasets change because their reference heat pumps and storage now
  match.
- Equipment: autosized batteries simulate their datasheet efficiency (tx, vt and
  ca neighbourhood datasets), and an EV connects to at most one charger per step,
  which affects charger clones in the dynamic-topology demos.

- EV datasets: each EV draws its own unspecified battery parameters
  (efficiency, curves, capacity fade) instead of all sharing one set. An
  arriving EV starts from the latest arrival state of charge on the incoming
  rows of its own session, also when only an earlier incoming row holds it, or
  else from the one on its connection row. It never takes an estimate across a
  change of `electric_vehicle_session_id`, and the KPI and departure-audit
  arrival references use the same value.
- SAC/MARLISA: features or rewards constant during warm-up are centred but no
  longer scaled by ~1e5; exploration, replay sampling and policy noise use
  seeded generators; MARLISA stores each transition with its own coordination
  variables and refits its demand model as data accumulates.
- KPIs: net-exchange and cost ratios with a negative (net-exporting or
  market-credited) reference use `1 + (control - reference) / |reference|`, so
  lower stays better; the counterfactual baseline exchanges no energy with the
  grid during power outages; multi-community ratios to a reference are ratios
  of summed totals.
- Subhourly control with hourly data: the partial-load baseline top-up is
  converted to the control step.
- Robustness: a PV `asset` `unavailable` event with the `control` or `both`
  part stops generation, not only its telemetry.
- Terminal observation: calendar, weather and prices come from the terminal
  row, and endogenous values from the last executed step, as for every other
  observation. Episode length and termination are unchanged.

Changes that **preserve trajectories and KPI values**: the zero-size placeholders
for absent devices, and EV chargers, are seeded, so the placeholders' unused
parameters are reproducible and building an env no longer advances Python's
global `random` stream; the native BAU cache keeps only the latest reference and
releases it before building the next, so repeated mid-episode `evaluate_v2()`
calls hold at most one reference env; and the reference loads only the episode,
not the whole data window, when the only device marked for autosizing is PV that
`solar_generation` disables.

## Upgrade from 3.1.1 to 3.2.0

CityLearn supports Gymnasium from 0.28.1 up to, but excluding, 2.0. Dataset names
now resolve against the `v3.2.0` tag. Existing dataset files and export formats
remain compatible.

Install `citylearn[end_use_load_profiles]` when generating datasets with the
EULP/EnergyPlus tools. Standard simulations use the core installation.

- **Per-building reward functions:** `MultiBuildingRewardFunction.calculate()`
  (used when the schema's `reward_function.type` maps buildings to functions)
  now returns one float per building, e.g. `[-1.0, -2.0]` instead of the nested
  `[[-1.0], [-2.0]]`, like every other reward function. With
  `central_agent=True` it returns their sum as `[total]`. Replace indexing such
  as `reward[i][0]` with `reward[i]`.
- **KPI exports:** the manifest records `energy_provenance`. With
  `energy_provenance=False` its `provenance_summary` and `source_destinations`
  are `null` instead of failing the export, and the native BAU reference uses the
  same setting.

Fixes that **change results** where they apply:

- Observations: LSTM dynamics buildings report the simulated indoor temperature
  (#165); zero-based minute and second features use a 60-step cycle; occupant
  set-point deltas and EV/deferrable consumption bounds are corrected.
- Dynamics: LSTM dropout is disabled at inference, so Quebec-model trajectories
  are deterministic for a seed and differ from earlier, noisy runs.
- Subhourly control with hourly data (`time_step_ratio` other than 1): LSTM
  heating and cooling actions request the stated fraction of nominal power,
  converted to energy once; thermal-storage charging and discharge limits use the
  same conversion, and autosizing uses each building's dataset/control ratio.
- Episodes: thermal-storage discharge at the first step is counted once, and
  action feedback, constraint penalties and dynamic series reset with each
  episode, which changes second and later episodes.

Changes that **preserve trajectories and KPI values**: the `energy_provenance`
option (default on), LSTM input trimming and scalar fast paths; gymnasium 1.x
support; and crash fixes for `hvac_mode` 0, partial-day outage signals and the
CLI without stable-baselines3.

## Upgrade from 3.1.0 to 3.1.1

No dataset, schema or export-file migration is required. Dataset names resolve
against the `v3.1.1` tag by default; its dataset files are unchanged from 3.1.0.

- Explicit `random_episode_split` constructor values now take precedence over the
  schema. Pass `None` to retain the schema's setting.
- Standby loss is an hourly fraction compounded over elapsed physical time.
  Subhourly SOC trajectories and their derived KPIs can therefore differ slightly.
- Autosizing converts energy demand to power before sizing power-rated devices
  and batteries. Recheck automatically chosen equipment in subhourly experiments;
  explicitly configured equipment and thermal capacity in step kWh are retained.
- Public energy-command interfaces and native BAU control logic are unchanged.
  Compare experiments using matching versions and resolved equipment settings;
  corrected results must not be labelled identical to old subhourly references.

## Upgrade from 3.0.2 to 3.1.0

The distribution, import namespace and default dataset registry remain
`citylearn`, `citylearn` and `citylearn-project/CityLearn` at `v3.1.0`.
All 32 public datasets are retained byte-for-byte; no CPS production datasets
are imported, and the datasets retired in 3.0.2 remain retired.

- **BAU behavior:** the native `BusinessAsUsualAgent` now requests immediate
  maximum charging to 100% for connected EVs. Concurrent vehicles share the
  available electrical capacity proportionally. It does not schedule charging
  against PV, prices or departure targets. The existing constructor order is
  retained, but non-default EV target/deadline options are rejected explicitly;
  use the configurable RBC policies for those experiments. Saved BAU trajectories
  from 3.0.2 must not silently serve as 3.1.0 references.
- **Corrected accounting:** outage dispatch shares one energy budget across
  served loads, storage reserves conserve energy, electrical limits use applied
  actions, and service/KPI denominators use executed intervals and events. Some
  previously saved KPI values can therefore change. Use version-matched runs
  when comparing experiments; keep raw energy, cost and service evidence.
- **Exports:** KPI-only exports still omit episode time series but include
  manifest and deferrable-service JSON sidecars. CSV and partitioned Parquet
  output remain supported. Keep sidecars with the exported KPI file.
- **Compact histories:** public market and robustness history access retains
  its legacy values and structure, reconstructed on demand. A returned market
  record is a snapshot: assign an edited record back through the history mapping
  rather than relying on nested in-place mutation. Repeatedly materializing full
  public histories can allocate substantial memory; retain compact histories
  during simulation and reconstruct them when needed.
- **Local schemas:** roots are resolved from the schema location. Existing
  repository-relative roots are also accepted when found under an ancestor;
  an existing schema-relative root takes precedence. Resolution does not depend
  on the process working directory, and input files are not rewritten.

The performance changes preserve trajectories and KPI values relative to the
corrected functional implementation. They do not imply equality with all
historical 3.0.2 results. See the [3.1.0 release notes](releases.md#v310---2026-11-02)
for measured scope and limitations.
