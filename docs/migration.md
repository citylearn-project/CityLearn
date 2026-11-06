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
