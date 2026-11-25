# Moving an existing project to CityLearn v3

Both the distribution and import name are `citylearn`. Install it from PyPI, or
use the [developer guide](developer_guide.md) for a repository checkout.

Portuguese version: [pt/migration.md](pt/migration.md).

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

### Dataset cache keyed by content

Local copies of datasets are now cached under the key of their content, in
`datasets_by_content/<key>/<dataset>` of `DataSet().cache_directory`, instead
of `datasets/<dataset>`. Nothing needs to change in code that loads datasets by
name or by the path that `DataSet().get_dataset()` returns.

- Copies cached by earlier runs under `datasets/<dataset>` are no longer read
  while a complete local copy exists, and they are left untouched. A run that
  used a stale cached schema now loads the local one, which can change its
  results; to reproduce such a run, pass the old `schema.json` path explicitly.
- Each different content of a dataset keeps its own copy, so checkouts that
  switch between branches accumulate copies. `DataSet().clear_cache()` removes
  them all.
- Code that built the cache path by hand from `cache_directory`, `datasets` and
  the dataset name should use the path returned by `DataSet().get_dataset(name)`.
- Downloads, used when no local copy exists, are still cached under
  `datasets/<dataset>` of the release tag.

`IndependentBalanceAudit` accepts `flow_relative_tolerance` (default 1e-8),
which scales the tolerance of the district balance residuals with their gross
flow; its report records the value. Pass `flow_relative_tolerance=0` to keep
the previous fixed tolerance.

### EV charging in the default baseline

The default KPI baseline (`EvaluationCondition.WITHOUT_STORAGE_BUT_WITH_PV`,
the `*_without_storage` series) subtracted the EV charger consumption with the
battery and the thermal storage and added nothing back, so on EV datasets the
`*_baseline_*`, `*_delta_*` and `*_ratio_to_baseline_*` rows, and every value of
the legacy `evaluate()` table, compared the run with a community whose cars
never charge: any controller that charged the cars looked worse than the
baseline ([#365](https://github.com/citylearn-project/CityLearn/issues/365)).

- The baseline now adds back the EV charging of the native BAU with the
  `'full'` target: each car is charged on arrival at maximum power until it is
  full, and never discharged. The cars get the energy they need, without V2G,
  and the baseline is the same for every controller, so the `baseline` rows
  credit a controller with its storage dispatch, its EV charging and its V2G
  against charging on arrival. The deferrable appliances stay as the controller
  ran them. So does the HVAC, except in buildings with temperature dynamics
  (LSTM), where the default condition uses the dataset's ideal-load heating and
  cooling demand.
- On datasets with EV chargers, every evaluation runs the BAU sidecar for that
  charging, also the legacy `evaluate()` and
  `evaluate_v2(include_business_as_usual=False)`, and uses the `'full'` target
  whatever `business_as_usual_ev_charge_target` is. Where the sidecar cannot
  run, because inputs, buildings or devices changed after loading, evaluating
  raises `ValueError`; use `baseline_version=1` there. The manifest of such a
  run records the BAU reference as evaluated.
- Only datasets with EV chargers change: `citylearn_challenge_2022_phase_all_plus_evs`,
  the `pt_rec_*` datasets and the three-phase demos. The simulation, the
  control rows and the rewards do not change, and neither do the BAU rows on
  datasets without HVAC actions (see [HVAC in the BAU](#hvac-in-the-bau)). The equity KPIs,
  which are built from each member's benefit against the baseline, change with it.
- Set `baseline_version` to `1` (constructor argument or schema key) to
  reproduce the baseline of CityLearn 3.6.0, including its BAU that does not
  run the HVAC. The version is in
  `env.get_metadata()` and the export manifest, at top level and in
  `comparison_context`; `compare_exports()` reports two runs under different
  versions as `incompatible`. `MultiCommunityEnv` requires every community to
  use the same version.

### HVAC in the BAU

On datasets with HVAC actions (temperature dynamics), the BAU sent zero to
`heating_device`, `cooling_device` and `cooling_or_heating_device`, so its
buildings were neither heated nor cooled and the `*_business_as_usual` rows
compared the controller with unheated or uncooled houses
([#362](https://github.com/citylearn-project/CityLearn/issues/362)).

- Under `baseline_version=2`, the default, the BAU now delivers the dataset's
  own heating and cooling demand at each step, clipped to the action bounds
  and device limits. On those datasets the BAU definition becomes
  `immediate-full-charge-v4+hvac-dataset-demand-v1` (or
  `immediate-user-target-v3+hvac-dataset-demand-v1`). See
  [HVAC and the baseline version](baselines.md#hvac-and-the-baseline-version).
- On datasets with HVAC actions (`quebec_neighborhood_with_demand_response_set_points`,
  `quebec_neighborhood_without_demand_response_set_points`,
  `tx_travis_county_neighborhood`, `vt_chittenden_county_neighborhood`,
  `ca_alameda_county_neighborhood`, `baeda_3dem` and the
  `citylearn_challenge_2023_*` datasets) the default
  `*_business_as_usual` rows, and the deltas and ratios to the BAU, change. On
  `quebec_neighborhood_without_demand_response_set_points` (steps 0–335) the BAU cost goes from 631.8 to 4,403.8 EUR, its mean
  indoor temperature from 3.4 to 20.6 °C, and the cost ratio of
  `RBCSmartPolicy` to the BAU from 6.970 to 1.000.
- On datasets without HVAC actions nothing changes, bit for bit.
- `baseline_version=1` keeps the BAU with the HVAC at zero, as in CityLearn
  3.6.0, to reproduce earlier numbers.
- A `BusinessAsUsualAgent` you run yourself follows the environment's version;
  `hvac='off'` or `hvac='dataset_demand'` overrides it.
- A controller that does not drive the HVAC, such as `ZeroActionAgent`, now
  looks much cheaper than the BAU on these datasets, because the BAU pays for
  heating and cooling. Read its ratios to the BAU together with the comfort KPIs.

### The rule-based baselines run the HVAC

`RBCBasicPolicy`, `RBCSmartPolicy` and `RBCCommunityPolicy` now deliver the
dataset's heating and cooling demand through the HVAC actions, with the rule of
the default BAU.

- Datasets without HVAC actions: nothing changes, bit for bit, including
  `comparison_identity()`.
- Datasets with HVAC actions: the rule-based baselines heat and cool, so their
  energy, cost and comfort KPIs change. Under the default `baseline_version=2`
  the BAU heats and cools too, so their ratios to the BAU compare houses that
  are heated and cooled alike. Their identity records `hvac='dataset_demand'`
  and the definition gets the suffix `+hvac-dataset-demand-v1`.
- The storage, EV and appliance rules do not change, but where a dataset with
  HVAC actions also has batteries, the battery actions can change: the load the
  rules react to now includes the HVAC.
- `SACRBC` and `MARLISARBC` built with a rule baseline as `rbc` explore with the
  HVAC at the dataset demand. `hvac` is not a learner parameter, so
  `SACRBC(env, rbc=RBCBasicPolicy, hvac='off')` passes it to the rule baseline
  and keeps the old exploration.
- `RBCSmartPolicy(env, hvac='off')` (and the same for the other two) gives the
  zero HVAC of earlier releases, to reproduce earlier numbers. See
  [HVAC of the rule-based baselines](baselines.md#hvac-of-the-rule-based-baselines).

### District emissions with local trading off

With a community market enabled and `community_market.local_trading_enabled`
set to `false`, `district_emissions_total_*_kgco2` and the KPIs derived from it
now count every member import at its carbon intensity, because no energy is
exchanged locally. They used to net members' exports against other members'
imports as if trading were on. The new value equals the `member_sum` row and
`district_energy_provenance_external_purchase_emissions_kgco2`. Runs with
local trading on, runs without a market and every bundled dataset are
unchanged, and the local price ratio does not affect emissions. To compare
with an earlier run made with local trading off, re-evaluate it with the
current release. See [#327](https://github.com/citylearn-project/CityLearn/issues/327).

### Community market settings are validated

`CityLearnEnv` now checks the `community_market` section when it is built and
raises a `ValueError` for settings that earlier releases ignored or replaced:
unknown keys (`enable` instead of `enabled`), a ratio that is not a number or
is outside `[0, 1]`, ratio aliases with different values, a
`settlement_version` other than `1` or `2` (a string such as `"2"` included), a non-zero
`grid_export_price` without `"settlement_version": 2`, and member weights or
tariff files for buildings that are not in the schema. The message names the
key and the fix. A schema that loaded before and now raises was not simulating
what it said: for example, a ratio of 1.5 settled at 1.0 and a
`grid_export_price` without settlement version 2 paid nothing. Write the value
that was applied (ratio 1, `grid_export_price: 0`) to keep the earlier results,
or fix the setting to get what was intended. Every bundled dataset is valid and
its results do not change.

Market attributes set on the env after construction
(`community_market_enabled`, `community_market_sell_ratio`,
`community_market_grid_export_price`,
`community_market_import_member_weights`, `community_market_local_enabled`,
`community_tariffs`) are not supported. The native BAU reference is rebuilt
from the schema, so `evaluate_v2()` with the BAU comparison now raises when they
differ from it. Change `schema['community_market']` and build a new env instead.
See [#366](https://github.com/citylearn-project/CityLearn/issues/366).

### Portfolio market rows with and without markets

In a `MultiCommunityEnv` where some communities have a community market and
others do not, the `portfolio_*_community_market_*` rows now include the
communities without a market with their plain grid settlement: no local trade,
their members' grid import and export as grid import and export after local
trading, their `cost_total_control_eur` as settled and counterfactual cost, and
zero savings and operator balance. These rows used to add the zeros those
communities report, so they described only the market communities. Their
values, and the pooled local-trade shares, change for such portfolios only.
District rows, simulations, KPI names and portfolios where every community has
a market, or none has, are unchanged. Re-evaluate earlier mixed portfolios with
the current release before comparing their portfolio market rows. See
[#373](https://github.com/citylearn-project/CityLearn/issues/373).

### Occupant set-point limits

Under physics version 2, an occupant of a
`LogisticRegressionOccupantInteractionBuilding` can no longer move a heating or
cooling set point past `set_point_limits`, a building schema key (and
constructor argument) that defaults to `[15, 30]` °C. Before, each occupant
change was added to the current set point with no limit, and under arbitrary
HVAC control the occupant keeps interacting: over the first Quebec episode
the heating set point reached -2323 °C with random actions and 3230 °C with
`BusinessAsUsualAgent`, far outside its observation bounds
([#352](https://github.com/citylearn-project/CityLearn/issues/352),
[#357](https://github.com/citylearn-project/CityLearn/issues/357)).

- A change stops at the limit it would cross. A schedule value already outside
  the range is kept, and an occupant can still move the set point back towards
  the range.
- `occupant_interaction_indoor_dry_bulb_temperature_set_point_delta` still
  reports the change the occupant asked for, also when the limit stopped it.
- The cooling and heating set-point observation bounds of these buildings are
  the schedule range widened to `set_point_limits`, which the set points can
  no longer leave. On both Quebec neighbourhoods they become [15, 30] °C
  instead of the indoor temperature limits (about -1 to 42 °C), so
  bound-based normalisation of these features changes: agents trained there
  under physics version 2 should be retrained.
- With `NoControlAgent` nothing changes: the Quebec set points stay within
  16.6 to 26.6 °C over the first episode. With `BusinessAsUsualAgent` the
  simulation and the `evaluate()` KPIs do not change, because the large set
  points fall on unoccupied steps, but the set-point observations and the
  rewards that read them (such as `ComfortReward`) do. With random actions the
  discomfort KPIs change too; energy, cost and emissions do not, because the
  HVAC action, not the set point, sets the heating supplied.
- `set_point_limits` applies under physics version 2 and later only. Set
  `physics_version` to `1` to reproduce the unbounded set points of
  CityLearn 3.6.0. To widen or narrow the range, set `set_point_limits` in each
  building of the schema, for example `"set_point_limits": [16, 28]`.

The limits do not bound the LSTM indoor temperature: under random heating
actions the Quebec indoor temperature still reaches about 60 °C, because the
HVAC action sets the heating supplied whatever the set point. That temperature
is outside the range the LSTM models were trained on, so treat such runs with
care.

### EV SOC unit of charger files

Under physics version 2 the SOC columns of a charger file
(`electric_vehicle_required_soc_departure`, `electric_vehicle_estimated_soc_arrival`
and `electric_vehicle_current_soc`) each have one unit, decided once from the
whole column of the file: percent if any value is above 1, ratio otherwise. Before, the unit was
guessed value by value, so an arrival SOC of 1 (1 %) in a percent file was read
as 100 %: the EV arrived full and was not charged
([#368](https://github.com/citylearn-project/CityLearn/issues/368)).

- Bundled data: the EV charger files of `citylearn_challenge_2022_phase_all_plus_evs`,
  the three hourly three-phase demos and the 15-second
  `citylearn_three_phase_electrical_service_demo_15s_parquet` and
  `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet` are in percent
  and contain such rows. Over the simulated year, 8 of about 2,800 arrivals of
  the hourly datasets and 8 arrivals of each of those two 15-second demos start
  from such a row. `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet`
  has none and does not change. The `pt_rec_*` files are ratios and do not change.
- Results change for those datasets. With `BusinessAsUsualAgent` over the full
  year of `citylearn_challenge_2022_phase_all_plus_evs`, EV charging rises by
  534 kWh (0.58 %), district import by 0.31 % and cost by 0.33 % (31,412.62 to
  31,515.25 EUR); the three hourly three-phase demos change by 0.31 to 0.34 %
  in import and 0.35 to 0.38 % in cost. On the 15-second
  `citylearn_three_phase_electrical_service_demo_15s_parquet`, the day around
  such an arrival (steps 79,200 to 84,959) charges 474 instead of 377 kWh.
  The EV departure KPIs barely move (the surplus mean changes in the fifth
  decimal), because those EVs used to arrive full.
- A column whose values are all between 0 and 1 is read as ratio. If it is in
  percent, declare `"soc_unit": "percent"` on the charger, next to
  `charger_simulation`; `"fraction"` forces ratio. A misspelt charger key,
  such as `soc_units`, is reported with a warning.
- A column read as percent that also holds values between 0 and 1 gives a
  warning: one stray value above 1 (1.00001, say) in a ratio column makes the
  whole column percent, so 0.3 would become 0.3 %. Fix the stray value or
  declare `"soc_unit": "fraction"`.
- Set `physics_version` to `1` to reproduce the value-by-value rule of
  CityLearn 3.6.0.

### Charger defaults and attribute names

Charger `attributes` are checked by name: a name the charger does not accept
raises a `ValueError` that names the charger and suggests the closest valid
name. Before, a misspelt name such as `max_discharge_power` was dropped and the
limit fell back to its default. `nominal_power` and `charger_type`, which the
bundled schemas set, are now accepted explicitly: `nominal_power` is the
default of `max_charging_power`, and `charger_type` is a label without effect
([#369](https://github.com/citylearn-project/CityLearn/issues/369)).

Under physics version 2 an omitted limit no longer gives a 50 kW
bidirectional charger:

- an omitted `max_discharging_power` is 0, so the charger cannot discharge
  (V2G off) and its action space starts at 0 instead of -1. Set
  `max_discharging_power` to allow V2G;
- an omitted `max_charging_power` is `nominal_power`, or 50 kW when that is
  missing too;
- a warning names every limit that falls back to an assumed value
  (`max_charging_power`, `max_discharging_power`, `efficiency`); `efficiency`
  only when it is used, that is when an efficiency curve does not replace it.

Every bundled charger sets all its limits, so bundled results do not change.
A schema that omits `max_discharging_power` and relied on the 50 kW of V2G
needs it set explicitly, or `physics_version=1`, which keeps the 50 kW defaults
of CityLearn 3.6.0 (the name check applies to both versions).

### Charger ids are unique across the schema

Two buildings may no longer declare a charger with the same id: loading raises
`ValueError: Charger id 'charger_1_1' is declared by both Building_1 and
Building_2` ([#402](https://github.com/citylearn-project/CityLearn/issues/402)).
Give each charger its own id in the schema, for example `charger_2_1` for the
copy in `Building_2`. If you built the second building by copying the first,
check its `charger_simulation` file too: a copy that schedules the same EV
plugs one car into two chargers, and the second stays idle with a warning.

Deferrable-appliance names may still repeat across buildings. In an entity
action map, address such an appliance with its building,
`Building_2/washer_1`; the bare `washer_1` (or `deferrable_appliance:washer_1`)
now raises when two buildings have it instead of reaching the last of them.

### EV departures at the end of the window

A session that is still connected at the last step of a member's KPI window,
with a countdown to departure of 0 or 1, is now a departure, as the
[KPI reference](kpis_reference.md#departures) says. Its SOC at that step is
scored against its target in `ev_events` and `ev_performance`, and the
departure audit counts it. The last step is the last control step of the
episode, or the step before a member leaves under a dynamic topology. At most
one departure per charger is added per window, so short episodes that end at
a usual departure time change the most; the default episodes of the bundled
datasets do not change.

Over consecutive split episodes each session is now counted once, by the
episode that controlled it. Before, a session that ended with an episode was
counted at step 0 of the next one, with the SOC set at reset, under
`episode_split_boundary='shared'`, and not at all under `'disjoint'`, where a
session connected on the row between two episodes was instead scored at step
0 of the next one with the SOC set at reset. Now the last step of an episode
counts a session that leaves before the next control step (countdown in
[0, 1], or in [0, 2] when another `'disjoint'` split follows, so a run that is
not split does not depend on the boundary), with the SOC the controller
reached, and step 0 skips any session
that was connected on the row before it. Departure counts and rates from
earlier runs with short or split episodes should be recomputed before
comparing ([#370](https://github.com/citylearn-project/CityLearn/issues/370)).

### EV SOC carried across episode splits

Nothing changes unless `ev_soc_carryover=True` is set. With it, an episode that
continues the previous one in time (it starts on the previous episode's last
row, or on the row after it, and the previous episode ran to its end) starts
each EV from the SOC it reached at the end of that episode, and a session
connected across the boundary is scored where it really leaves, with that
charge, as described in the [KPI reference](kpis_reference.md#departures). Only the EV SOC is carried: batteries, thermal storage and indoor temperatures still start every episode from their initial state. The setting is a trade-off. Off, every episode is independent of the ones before it, but a session that crosses a boundary loses the charge it received. On, that charge is kept, but an episode that continues the previous one depends on what the previous controller did, so its KPIs are no longer those of an independent episode.
Met departures of split runs then rise towards those of one run, so results
with and without the setting are not comparable, and `compare_exports` reports
them as incompatible. Under `'disjoint'` the row between two episodes is never
controlled, so a session connected across it can be up to one charging step
behind one run. A carried episode starts from the SOC that the previous
controller left, which enters its initial inventory, so the same carried
episode run by two controllers is not comparable, and `compare_exports`
reports it as incompatible: with carry-over, compare whole split runs, not
single episodes. Random and rolling splits never carry, and the env warns
once that the setting has no effect there; an explicit list carries only when
a window starts exactly where the previous one ends for the split boundary, so
under the default `'shared'` a list without a gap, such as
`[(1900, 1949), (1950, 1999)]`, does not carry (it carries under `'disjoint'`,
or under `'shared'` when the next window starts on the previous window's last
row), and a `reset(options={'episode_index': ...})` that jumps elsewhere keeps the
schedule SOC. Only the session connected across the boundary is carried;
every later arrival takes the arrival SOC of the file, and an arrival without
one keeps the EV's simulated SOC, as in one run. Summed over the episodes,
departures, met departures and feasibility classes match one run, but the
connected SOC gain of the energy accounting is each episode's own gain, so its
sum is lower than in one run, and energy totals can differ slightly ([#388](https://github.com/citylearn-project/CityLearn/issues/388)).

### Out-of-range flat actions are clipped

A flat action outside `env.action_space`, or a flat vector sent to an entity
environment, is now clipped to the nearest bound, as entity `tables` and `map`
payloads already were. Actions inside the space are applied exactly as before.
A controller that sends actions beyond the bounds, for example a scripted
thermal-storage rule above `±limit`, now gets the clipped simulation, and its
earlier results are not comparable with new runs. This includes the hour RBCs
(`BasicRBC`, `OptimizedRBC`, `BasicBatteryRBC`) on `baeda_3dem`, the
`citylearn_challenge_2020_climate_zone_*` datasets and
`citylearn_challenge_2021`, whose storage rule exceeds the thermal storage
bound of some buildings. `physics_version=1` keeps
the 3.6.0 rule, flat actions applied as given, to reproduce such runs. Read the
bounds from `env.action_space`. See
[out-of-range actions](actions_reference.md#out-of-range-actions).

### Deferrable energy observation bounds

The flat bounds of `deferrable_appliance_*_cycle_energy_kwh`,
`*_remaining_energy_kwh` and `*_current_step_energy_kwh` change from
[-1, 1e6] to [0, largest cycle energy] and [0, largest step energy] of the
building's appliances, under the default physics version 2; `physics_version=1`
keeps [-1, 1e6]. The observation values and the simulation do not change.
Normalised (`NormalizedObservationWrapper`) and discretised observations, and the
encoders of `SAC` and `MARLISA`, read these bounds, so a policy trained on a
dataset with deferrable appliances (`pt_rec_*`,
`citylearn_challenge_2022_phase_all_plus_evs`, the three-phase demos) sees
different inputs: retrain it, and do not compare its earlier results with new
runs. A saved normaliser that stores the old bounds keeps working, but then
still hides these features. See
[observation bounds](interfaces_flat_entity.md#observation-bounds).

### Observation spaces follow the observations

The observation values, their order and `observation_names` do not change, and
neither do simulations or KPIs, except runs with robustness faults on the flat
interface of `pt_rec_*` or the three-phase electrical-service demo: those faults
now reach the feature they name. The observation spaces change, and so does
anything that reads bounds from them: agents trained on the datasets below
should be retrained, and their earlier results are not comparable.

- **Flat order.** `env.observation_space` now follows `env.observation_names`.
  Each building lists its own features first, in `active_observations` order,
  then the features of its EV chargers, deferrable appliances and escalators,
  grouped by device (`Building.flat_observation_order`). The space used to
  follow `active_observations`, so for buildings with EV chargers or deferrable
  appliances whose features are not already at the end of
  `active_observations`, positions carried another feature's bounds. This
  affects the flat interface of `pt_rec_4`, `pt_rec_15`, `pt_rec_30`,
  `pt_rec_100` and one building of the three-phase electrical-service demo
  (hourly and 15 s).
- **Entity `meta`.** `env.observation_space['meta']` is an `EntityMetaSpace`.
  It accepts a mapping with `time_step`, `endogenous_time_step`,
  `seconds_per_time_step` and `spec_version`, is not flattenable and should not
  be fed to a network. Code that iterates over `observation_space.spaces` should
  skip it, as it skips `observations['meta']`.
- **Wider estimated bounds**, in both interfaces:
  per-phase charging headroom (`charging_phase_*_headroom_kw` and
  `charging_phase_*_export_headroom_kw`) on `pt_rec_*`; `cooling_demand` and
  `heating_demand` of LSTM buildings whose HVAC action is active, on the 2023
  challenge datasets and both Quebec neighbourhoods; and the cooling and heating
  set points of occupant-interaction buildings, on both Quebec neighbourhoods,
  which now cover the indoor temperature limits.

These bounds are still estimates where the model has no hard limit. Under
arbitrary control, for example random actions over a full Quebec episode, the
LSTM indoor temperature, and under physics version 1 the occupant set points,
can leave them; `ClippedObservationWrapper` keeps such values inside the space.
Under physics version 2 the occupant set points stay within `set_point_limits`
(see [occupant set-point limits](#occupant-set-point-limits)). Without heating,
for example under the default BAU, the indoor temperature leaves them on the
cold side; see [observation bounds](interfaces_flat_entity.md#observation-bounds).

What reads the bounds:

| Consumer | Uses | Affected by |
|---|---|---|
| `RLC`, `SAC`, `MARLISA` encoders | `observation_space` by position | order and bounds |
| `ClippedObservationWrapper` | `observation_space` by position | order and bounds |
| `DiscreteObservationWrapper`, `TabularQLearningWrapper` | bins from `observation_space` by position | order and bounds |
| `NormalizedObservationWrapper` | building limits by name | bounds only |
| `StableBaselines3Wrapper`, `RLlibSingleAgentWrapper`, `RLlibMultiAgentEnv` | declare the space, do not rescale | only through a normalising wrapper or the algorithm's own use of the space |
| Robustness faults on the flat interface | feature by position | order (faults now reach the named feature) |

### The native BAU uses current-step load and solar

The native BAU now uses observed load and PV from the step being planned when
it requests battery charging or discharging. This can change BAU-relative KPIs.
Re-evaluate both runs with the current release and the same EV charging target
before comparing them. To reproduce a result using the previous BAU, use the
CityLearn release or commit recorded in its original manifest. See the
[BAU reference](baselines.md#known-limits).

### The rule-based baselines use current-step load and solar

`RBCBasicPolicy`, `RBCSmartPolicy` and `RBCCommunityPolicy` now plan the battery,
EV and appliance budget with the load and PV of the step being planned, as the
native BAU does, instead of the settled observations of the previous step.
`RBCSmartPolicy` and `RBCCommunityPolicy` also stop charging the battery from the
grid at a cheap price when PV is forecast and no PV-surplus forecast is observed
(no `entity_forecasts_derived` bundle).
Their definitions become `basic-v4`, `smart-local-v4` and `community-v4`.

- Their actions and KPIs change on every dataset with a battery. The default
  `RBCBasicPolicy` battery now follows the BAU rule exactly, so on datasets
  without EVs or flexible appliances it gives the BAU results.
- The grid-charge change acts only on datasets with a solar forecast and without
  `entity_forecasts_derived`, for example `citylearn_challenge_2022_phase_all`
  and `citylearn_three_phase_electrical_service_demo`; on `pt_rec_*` and
  `citylearn_challenge_2022_phase_all_plus_evs` only the current-step change
  applies.
- Run them again before comparing a controller with them. To reproduce a result
  of the earlier definitions, use the CityLearn release or commit recorded in its
  manifest, as for the BAU. See
  [the rule-based baselines](baselines.md#rule-based-baselines) and
  [#400](https://github.com/citylearn-project/CityLearn/issues/400).

### Numeric and configuration hygiene

These changes require no dataset, schema or KPI migration. Valid runs give the same results; a few silent mistakes now raise.

- **Non-finite actions raise.** `env.step()` raises `ValueError` for NaN or infinite actions. A training loop that used to continue with a diverged policy now stops at the first bad action; check the policy output or replace non-finite values before stepping.
- **Unknown constructor arguments raise.** `CityLearnEnv(..., **kwargs)` raises `TypeError` for an unknown keyword argument, with the closest valid name. Remove or correct arguments that were silently ignored before.
- **Topology events are validated at construction.** An event that names a member missing from the schema, or an asset override with an unknown key or an invalid value, raises when the environment is built. Members declared in the schema but not loaded (`buildings=[...]`) are still accepted.
- **Run settings beyond the data or mixed across communities raise.** A `simulation_end_time_step` or `simulation_start_time_step` past the end of the data raises `ValueError` at construction, with the last valid end step; such runs used to fail with an `IndexError` at their last step, so lower the value to the one in the message. `MultiCommunityEnv` raises when communities differ in `business_as_usual_ev_charge_target` or `ev_soc_carryover`; set the same value in every `env_kwargs`. A community `weight` given as a string, such as `'2'`, raises; pass a number. `district_electrical_service` with `enabled: true` and no `import_kw` or `export_kw` raises; add a limit or set `enabled` to false. `compare_manifests()` now pairs a run with the feeder monitor and the same run without it, with `'district_electrical_service_one_sided'` in `declared_differences`, where it used to report them as `incompatible`; `physical_configuration_sha256` no longer includes the feeder setting, so it changes for runs that enable it. Different feeder limits on both sides are still `incompatible`.
- **Logging.** CityLearn no longer configures the root logger. Warnings still print; to see INFO messages, configure logging in your script, for example `logging.basicConfig(level=logging.INFO)`. `learn(logging_level=...)` and `DataSet(logging_level=...)` set the level of the `citylearn` logger only when passed.
- **Export location.** Exports go to `./render_logs` in the working directory by default, and relative `render_directory` values resolve against the working directory. Pass an absolute `render_directory` to keep the previous location.
- **Physics invariants** raise `PhysicsInvariantError`, which is an `AssertionError`, so existing handlers keep working.
- **Per-step history reads.** `env.rewards`, `env.net_electricity_consumption`, `env.net_electricity_consumption_cost` and `env.net_electricity_consumption_emission` store their values in preallocated `float64` buffers. Reading one of these properties builds `_TrackedList`, a `list` subclass (`isinstance(..., list)` is `True` and `type(...) is list` is `False`), and the reward rows inside `env.rewards` are `_TrackedList` too; `pickle` gives plain lists, while `list(env.rewards)` gives a plain outer list whose rows are still `_TrackedList`. The list is extended when the property is read again, and an in-place edit detaches it, so caller edits cannot change the environment. A reference kept across `env.step()` calls (for example `rewards = env.rewards` after `reset()`) stays at the length it had when read until the property is read again; re-read the property on `env` when you need the updated history. Once read, the list is kept for the rest of the episode, so the memory saving of the buffers holds only while nothing reads these properties during the episode. In training loops, use the reward returned by `env.step()`, as the CityLearn agents do, and read the histories at the end of the episode.

### Recorded settings

The settings added since 3.6.0 are recorded with each run. `env.get_metadata()`,
its `temporal_reproducibility` block and the export manifest hold
`physics_version`, `episode_split_boundary` and `time_step_ratio_mode`; the
manifest also keeps `random_stream_version`. With per-building reward
functions, the reward evidence lists each building's reward class and
parameters, including `version`, under `per_building`, because the
`MultiBuildingRewardFunction` that combines them has no version of its own.
Invalid values of these settings raise `ValueError` that names the accepted
values, whether set in the schema or as a constructor argument, and a
misspelled `physics_version` argument gets a suggestion. Simulation results do
not change ([#301](https://github.com/citylearn-project/CityLearn/issues/301),
[#302](https://github.com/citylearn-project/CityLearn/issues/302)).

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
- A member cloned with `source_member_id` gives its chargers ids of their own
  (`charger_1_1` of `Building_1` becomes `charger_19_1` in `Building_19`), so
  the clone's observation, action and entity names change; update saved agents
  and robustness events that name the clone's chargers by the source's id.
- Under the default `baseline_version=2`, a battery removed or replaced by
  `remove_asset` or `add_asset` keeps what it moved before the event in the
  building's battery series, so the baselines without storage of that building
  and the district no longer keep its dispatch and no longer depend on the
  controller. Only the baseline rows (`*_baseline_*`, ratios and deltas to the
  baseline) of runs that remove or replace a battery change. Set
  `baseline_version=1` to keep the CityLearn 3.6.0 series, where the history
  was lost.

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
`SolarPenaltyAndComfortReward` accept a `version` attribute, and version 2 is
the default. Version 2 corrects the EV departure penalty, adds the base reward
and follows the HVAC mode in the comfort term, as the reward function overview
of the documentation describes. Every bundled schema that uses these rewards
sets `"version": 2`, so the rewards of `citylearn_challenge_2022_phase_all_plus_evs`,
the three-phase demos, the 2023 challenge datasets, both Quebec neighbourhoods
and `baeda_3dem` differ from 3.6.0; their simulations and KPIs do not. Retrain
policies trained on these rewards before comparing them with new runs, and
compare policies only within one version.

Version 1, the reward of 3.6.0, is deprecated and exists only to reproduce runs
made with CityLearn 3.6.0 or earlier. Select it with `"version": 1` in the
reward attributes (or `reward_function_kwargs={"version": 1}`); it raises a
`DeprecationWarning` and will be removed in a later release. Reward objects
pickled by 3.6.0, for example inside a saved agent or environment, keep version
1 without a warning. The reward evidence in the environment metadata and in
export manifests records the version.

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
  `evaluate()` district rows still hold them; on datasets with EV chargers,
  with `baseline_version=1` (see [EV charging in the default baseline](#ev-charging-in-the-default-baseline)).
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
  reference, the deferrable start delay without completed cycles, and each
  deferrable-appliance ratio to the BAU whose own two totals are zero (for
  example the missed-cycle ratio when neither run missed a cycle, even if cycles
  were due) are now missing instead of 0 or 1 ([#243](https://github.com/citylearn-project/CityLearn/issues/243)).
  Code that reads these cells must handle `None`/NaN.
- **Portfolio rates** of `MultiCommunityEnv` (EV departure rates and means,
  service levels, start delay, self-consumption) are pooled from their additive
  denominators instead of weighted by community
  ([#244](https://github.com/citylearn-project/CityLearn/issues/244)). The
  community-market local shares of demand and export and the demand-response
  compliance and audit coverage ratios are pooled the same way, from local plus
  grid energy and from requested energy; the new district rows
  `district_demand_response_valid_requested_total_kwh` and
  `district_demand_response_credited_total_kwh` are the components of the
  compliance ratio ([#285](https://github.com/citylearn-project/CityLearn/issues/285)).
  District and building values are unchanged; rerun `MultiCommunityEnv`
  evaluations whose portfolio rows you compare.
- **BAU ramping average** is the mean upward ramp per step instead of the sum
  over the episode; the sum is published as `*_ramping_total_*_kw`
  ([#245](https://github.com/citylearn-project/CityLearn/issues/245)). The ratio
  to the BAU is unchanged.
- **EV target met** uses a tolerance of 0.005 SOC instead of 1e-6, for the met
  rates, the target feasibility counts and the departure-audit target rows. The
  rule-based baselines, which stop 0.001 short, now count as meeting the target:
  on full-year `citylearn_challenge_2022_phase_all_plus_evs`,
  `district_ev_performance_departure_success_ratio` goes from 0.988 to 0.994
  (BAU), 0.598 to 0.994 (`RBCBasicPolicy`), 0.495 to 0.994 (`RBCSmartPolicy`)
  and 0.130 to 0.134 (random actions). Rerun the evaluation before comparing
  met rates with earlier tables; the departure audit's `definition_version` is
  now `ev-departure-audit-v2`, so `compare_exports` reports older exports as
  incompatible. Use the deficit or shortfall means, which stay
  exact, to measure how far short a controller leaves the cars.
- **Comfort KPIs of buildings without set-point columns** are undefined instead
  of judged against the 0 °C default; on the `pt_rec_*` datasets the discomfort
  ratios go from 1 to undefined for every controller, and the district skips
  those buildings. Code that reads these cells must handle `None`/NaN. Datasets
  with set points do not change, nor do the 2020–2022 challenge datasets and the
  three-phase demos, which have no set-point columns but no occupants either, so
  their comfort KPIs were already undefined.
- **Cost and emissions ratios of two zero totals** are undefined instead of 1,
  for example the emissions ratios on Quebec (zero carbon intensity) and the
  cost ratios on the `citylearn_challenge_2020_climate_zone_*` and
  `citylearn_challenge_2021` datasets (no prices), for every controller.
- **Total ratios with a negligible reference** are undefined instead of a
  finite but arbitrarily large quotient: a `*_ratio_to_baseline_*_total_ratio`
  or `*_ratio_to_business_as_usual_*_ratio` whose reference total is at most 1%
  of the mean |reference| of the building rows
  ([#403](https://github.com/citylearn-project/CityLearn/issues/403)). Only
  building rows changed on the bundled datasets: 8 of 8,774 rows on
  `citylearn_challenge_2022_phase_all_plus_evs` (336 steps, RBCSmart or random
  actions), 3 over the full year with zero actions, 3 of 8,789 on
  `citylearn_three_phase_electrical_service_demo`, none on `pt_rec_4`; no
  district row changed. Code that reads these cells must handle `None`/NaN. The
  control and reference totals and their delta stay in the table; divide them
  if you need the raw quotient.

### Physics version

Corrections to the simulated physics are grouped into versioned physics
definitions, selected with the `physics_version` schema key or the
`CityLearnEnv(physics_version=...)` argument, which takes precedence. Version
`1` is the physics of CityLearn 3.6.0 and earlier; version `2`, the default,
contains the corrections below. The native BAU reference of `evaluate_v2()`
uses the version of the evaluated environment. The resolved version is in
`env.get_metadata()`, its temporal block, and the export manifest, both at top
level and in `comparison_context`. `compare_manifests()` and `compare_exports()`
report two runs under different physics versions as `incompatible`, with
`physics_version` among the mismatches, and a manifest written before the
version was recorded as `unknown`, with `physics_version` among the missing
evidence; export such runs again to pair them. To reproduce a 3.6.0 result, set
`physics_version` to `1`, and also `baseline_version` to `1` for the KPIs of
datasets with EV chargers; to compare controllers, run them under the same
versions.

`MultiCommunityEnv` requires every community to use the same
`physics_version` and `random_stream_version`, because portfolio KPIs add up
the communities' totals; mixed versions raise `ValueError` at construction.
Its `get_metadata()` records both.

Version 2 changes the following on bundled datasets:

- **Battery discharge power.** `capacity_power_curve` describes how charging
  power tapers near full charge, but version 1 applied it to discharge too, so
  a full battery could discharge at only a fraction of its nominal power
  ([#227](https://github.com/citylearn-project/CityLearn/issues/227)). Version
  2 limits discharge with a separate battery attribute,
  `discharge_power_curve`, which defaults to a flat curve at `nominal_power`
  and can derate at low state of charge. `InventoryBattery` keeps its
  `max_discharge_kw`. This changes every battery and EV battery whose
  `capacity_power_curve` tapers, which includes the default curve, whenever it
  discharges above the taper point: the 2022 and 2023 challenge datasets, the
  three-phase demos, the neighbourhood datasets and most `pt_rec_*` batteries.
- **Battery discharge during outages.** Version 1 capped an islanded battery's
  discharge with a pre-step estimate of the load that ignored the thermal
  storage discharge and the device limits, so the battery could discharge more
  than the building consumed and the surplus was reported as PV curtailment,
  even without PV ([#229](https://github.com/citylearn-project/CityLearn/issues/229)).
  Version 2 discharges the battery after the step's thermal demand and thermal
  storage discharges are known and caps it at the islanded load that PV leaves.
  With `physics_invariant_checks`, a discharge above that load raises
  `PhysicsInvariantError`. This changes scenarios with outages and batteries, such as
  the `citylearn_challenge_2023_*` datasets with stochastic outages and the
  `pt_rec_*` robustness, combined and all-in scenarios.
- **Energy to full of faded batteries.** Charging stops at a battery's
  degraded capacity, which capacity fade lowers below its nominal capacity,
  but version 1 computed the entity observations of the energy a battery can
  still take from the nominal capacity, so a battery that fade had made full
  was observed with `can_charge` 1 and charge power available. Version 2 stops
  `energy_to_full_kwh`, `connected_ev_energy_to_full_kwh`,
  `flexible_energy_to_full_kwh` and the charge features derived from them at
  the degraded capacity (see [energy to full](observations_reference.md#energy-to-full)).
  The simulated physics is unchanged, but controllers that read these
  observations act differently: the BAU no longer reserves power for a faded EV
  that is already full, so its home battery no longer discharges for it and
  exports the energy. This changes the BAU on datasets whose EV batteries fade
  and that publish the `entity_core_electrical` bundle:
  `citylearn_challenge_2022_phase_all_plus_evs`, the dynamic assets and
  dynamic topology three-phase demos and the 15-second three-phase demos.
  Batteries without fade, including every `pt_rec_*` battery, and
  `citylearn_three_phase_electrical_service_demo`, which does not publish
  the bundle, are unchanged.

- **Electrical-service headroom.** The import limit of a building with
  `electrical_service` was shared among the EV chargers and the battery in
  proportion to their requested power, including requests that the device
  could not draw, such as a charge request to a full battery or to a charger
  without an EV, so the other devices were curtailed
  ([#231](https://github.com/citylearn-project/CityLearn/issues/231)). Version
  2 first limits each request to the power the device can draw at that step
  and shares the headroom among those powers; the headroom observations and the
  requested-violation penalty use the same powers. A controller is therefore no
  longer penalised for a request that has no physical effect.
- **Thermal storage under an electrical-service limit.** The headroom was
  allocated before the step's thermal storage charging, so the import could
  exceed the limit while the recorded power, headroom and violation stayed
  within it ([#230](https://github.com/citylearn-project/CityLearn/issues/230)).
  Version 2 allocates the headroom to the EV chargers and the battery after the
  thermal, domestic hot water and non-shiftable updates, and records the power,
  the headroom and the violation from the settled import of the step.
- **Deferrable appliance starts.** Version 1 allowed a start only if the whole
  cycle fitted the realised future outage signal, load, PV and limits, which a
  controller cannot know, and reported that decision through the `can_start`
  observation, the action feedback and the simulator's refusal of the start
  ([#232](https://github.com/citylearn-project/CityLearn/issues/232)).
  Version 2 decides a start on the current step and on whether the cycle ends
  within the episode. A cycle that later meets an outage is served from the
  islanded supply that the other loads leave, after them; when that supply
  does not cover the step, the cycle stops and is reported as missed. A cycle
  that later meets a load peak under an electrical-service limit continues, and
  any excess over the limit is recorded as a violation, as for the other loads
  the controller does not set.

These three changes affect the `pt_rec_*` datasets, where every member has an
electrical-service limit, and `Building_15` of the three-phase demos.

It also changes runs that use the following:

- **Charger files in percent.** The SOC unit is decided once per column, so an
  SOC of 1 in a percent file is 1 % instead of 100 %
  ([#368](https://github.com/citylearn-project/CityLearn/issues/368), see
  [EV SOC unit of charger files](#ev-soc-unit-of-charger-files)).
- **Chargers without `max_discharging_power`.** They cannot discharge; version
  1 gave them 50 kW of V2G
  ([#369](https://github.com/citylearn-project/CityLearn/issues/369), see
  [charger defaults and attribute names](#charger-defaults-and-attribute-names)).
- **Flat actions outside the action space.** They are clipped to the space, as
  entity tables are; version 1 applied them as given (see
  [out-of-range flat actions are clipped](#out-of-range-flat-actions-are-clipped)).
- **Deferrable energy observation bounds.** The flat `*_kwh` bounds come from the
  appliances' cycles; version 1 kept [-1, 1e6] (see
  [deferrable energy observation bounds](#deferrable-energy-observation-bounds)).
- **Occupant set points under arbitrary control.** An occupant change stops at
  `set_point_limits`, [15, 30] °C by default; version 1 had no limit
  ([#352](https://github.com/citylearn-project/CityLearn/issues/352), see
  [occupant set-point limits](#occupant-set-point-limits)).
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

### Random streams

CityLearn draws random values for unspecified device parameters (for example a
battery's `power_efficiency_curve`, `capacity_power_curve` or
`capacity_loss_coefficient`, or a tuple range given for a parameter), the state
of charge of electric vehicles away from their charger, occupant set-point
interactions and stochastic power outages. The new top-level schema key and
constructor argument `random_stream_version` selects how these streams are
derived from `random_seed` ([#248](https://github.com/citylearn-project/CityLearn/issues/248)).

`v2`, the new default, derives every stream with `numpy.random.SeedSequence`,
with the seed as entropy and the purpose, the object and the episode as spawn
key, and keeps one generator per stream:

- each device draws its parameters as successive values of its own stream,
  keyed by building and device name; in 3.6.0 every draw was the first value of
  a new `RandomState`, so all parameters of a device sat at the same quantile.
  A `random_seed` given in a device's or an EV battery's attributes is that
  object's own stream, so devices given the same seed draw the same parameters,
  as a device built on its own does;
- each electric vehicle has its own away-from-charger drift stream per episode;
  in 3.6.0 one stream seeded with `random_seed + episode` was shared by every
  EV, so seed `s` in episode 1 repeated seed `s + 1` in episode 0;
- each occupant has its own stream per episode; in 3.6.0 every occupant drew
  `RandomState(max(random_seed, 1) + time_step)`, the same value in every
  building and episode, and seeds 0 and 1 were identical;
- each building's stochastic outages are drawn per episode, including day 0
  and a partial last day, with durations rounded to the nearest step; 3.6.0
  skipped day 0 and the partial last day, floored durations, and repeated the
  same outages in every episode with the same window. A seed given to the
  outage model is now the root of that building's stream instead of a stream
  shared by every building that uses it.
- a member that a dynamic topology clones from `source_member_id` is keyed by
  its own name, so it draws its own occupant and device streams; it used to keep
  its source's keys and draw exactly what its source drew
  ([#304](https://github.com/citylearn-project/CityLearn/issues/304)). No
  bundled dataset clones a member. `v1` does not key its streams by object and
  is unchanged.

`reset(seed=s)` sets `random_seed` to `s` and restarts the per-episode streams
(EV drift, occupant interactions and stochastic outages) at episode key 0, the
key of the first episode of an environment built with `random_seed=s`. It does
not rebuild the environment, so it repeats that first episode only on a new
environment built with `random_seed=s`:

- the episode window still advances, so a second `reset(seed=s)` simulates the
  next window; `reset(seed=s, options={'episode_index': k})` simulates window
  `k` with the streams of episode 0;
- device and EV battery parameters drawn at construction, and the initial EV
  state of charge, keep the values drawn with the construction seed.

To repeat a run with another seed, build a new environment with that
`random_seed`. `reset(options={'episode_index': k})` without a seed repeats
episode `k` of the same environment, or of another one built with the same
seed. As Gymnasium recommends, pass a seed to the first reset only: a seed at
every reset gives every episode the same per-episode streams. The native BAU
reference uses the streams of the episode it evaluates.

Runs that use none of these random features are unchanged. To reproduce results
obtained with 3.6.0 or earlier for the same seed, set `random_stream_version`
to `v1`:

```python
env = CityLearnEnv(schema, random_seed=0, random_stream_version='v1')
```

or add `"random_stream_version": "v1"` to the schema. The version used is
recorded in `get_metadata()['random_stream_version']`, in the
`temporal_reproducibility` metadata and in the experiment manifest; comparisons
between runs with different versions report a temporal mismatch.

Measured with the same pseudo-random actions and the other settings at their
defaults, `v1` reproduces the random streams of 3.6.0 bit for bit on every run
below; `v2` changes:

- `citylearn_challenge_2022_phase_all` (168 h, random battery curves): control
  cost 1,171.0 → 1,171.1 EUR (+0.01%) and net consumption +0.1%;
- `citylearn_challenge_2022_phase_all_plus_evs` (two 168 h episodes, random
  battery curves and EV drift): net consumption −1.6% in both episodes,
  control cost −0.2% and −0.1%;
- `citylearn_challenge_2023_phase_2_local_evaluation` (720 h): with the
  bundled SAIFI the three buildings no longer share one 15-step outage, so the
  episode has none and the normalized outage unserved energy goes from 0.72 to
  0; with SAIFI 36.5/year the outages per building change from 23/23/23 steps
  in both episodes (identical in every building and episode) to 9/9/34 and
  5/1/4;
- `quebec_neighborhood_with_demand_response_set_points` (3 buildings, two
  168 h episodes): occupant draws now differ by building and episode; energy,
  temperature and comfort KPIs of these runs are unchanged.

Rerun stochastic experiments, and retrain policies whose results you compare
across seeds, with `v2`; keep `v1` only to reproduce published 3.6.0 numbers.

Agents and generated neighborhoods follow the same setting
([#287](https://github.com/citylearn-project/CityLearn/issues/287)).
`TabularQLearning` decided between exploration and exploitation with
`RandomState(random_seed + time_step)`, and MARLISA with information sharing
shuffled the order in which its buildings act with the same seed, so seed `s`
at time step `t + 1` repeated seed `s + 1` at time step `t`. With `v2`, an
agent keeps one generator per purpose and episode, derived from its seed and
the episode, and takes the version of its environment, so an environment built
with `random_stream_version='v1'` gives its agents the 3.6.0 streams. The
neighborhood generator (`citylearn.end_use_load_profiles.neighborhood.Neighborhood`)
seeded partial-load simulation `i` of building `b` with `b + i`, which ignored
the neighborhood seed and repeated simulation `i - 1` of building `b + 1`. Its
new `random_stream_version` argument, `v2` by default, derives that seed from
the neighborhood seed, the building and the simulation index:

```python
Neighborhood(random_seed=0, random_stream_version='v1')  # 3.6.0 partial-load seeds
```

These changes alter the exploration of these agents, and therefore the policies
they learn, and newly generated datasets; simulations and the bundled datasets
are unchanged.

### Optional PyTorch and scikit-learn

`pip install citylearn` no longer installs PyTorch or scikit-learn. Install the
extra that your study needs:

- `pip install "citylearn[dynamics]"` for datasets with LSTM thermal dynamics:
  the 2023 challenge datasets, both Quebec neighbourhoods, `baeda_3dem` and the
  EULP neighbourhood datasets (`ca_alameda_county_neighborhood`,
  `tx_travis_county_neighborhood`, `vt_chittenden_county_neighborhood`);
- `pip install "citylearn[rl]"` for the bundled `SAC`, `SACRBC`, `MARLISA` and
  `MARLISARBC` controllers (it also covers LSTM thermal dynamics);
- `pip install "citylearn[end_use_load_profiles]"`, which now includes both, to
  build datasets from End-Use Load Profiles.

Without the extra, constructing such an environment or importing these
controllers raises an `ImportError` that names it; it used to raise a plain
`Exception` for the controllers. Environments that already have PyTorch and
scikit-learn installed keep working unchanged. To avoid the CUDA libraries,
install the CPU-only PyTorch first with
`pip install torch --index-url https://download.pytorch.org/whl/cpu`. Stable
Baselines3 is not an extra: install `stable-baselines3>=2.4`, which supports
gymnasium 1.x.

### CLI evaluation window and host information

`citylearn simulate ... train --evaluate` evaluates on the first training
episode window when `-te` is not given; it used to evaluate on the whole
simulation window. Runs without `episode_time_steps` evaluate the same window
as before. Pass `-te start end` to evaluate on a chosen window. The training
summary JSON records `hostname` and `username` only with `--record_host`;
scripts that read these keys need the flag.

### Renamed agent classes

`citylearn.agents.base.BaselineAgent` is now `NoControlAgent`, and
`citylearn.agents.baseline.ZeroActionBaselineAgent` is now `ZeroActionAgent`. In
CityLearn, "baseline" names the KPI counterfactual, the same buildings without
storage and with PV, which the `*_baseline_*` KPIs report; the two agents are a
no-control and a zero-action controller, so their names now say so. The old
names are deprecated aliases of the same classes, so existing imports, CLI
`-a` paths, schema `agent.type` values and pickled agents keep working and only
raise a `DeprecationWarning`. Replace the old names before a later release
removes them:

```python
from citylearn.agents.base import NoControlAgent        # was BaselineAgent
from citylearn.agents.baseline import ZeroActionAgent  # was ZeroActionBaselineAgent
```

The bundled EULP neighbourhood schemas and the default agent of generated EULP
schemas use `citylearn.agents.base.NoControlAgent`. Results are unchanged.

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
