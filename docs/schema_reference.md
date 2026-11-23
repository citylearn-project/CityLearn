# Schema Reference

This page documents the `schema.json` contract. The schema is the source of truth for buildings, devices, EVs, deferrable appliances, escalators, interfaces, observation bundles, demand response, robustness, dynamic topology and local market configuration.

Portuguese version: [pt/schema_reference.md](pt/schema_reference.md).

## General Rules

| Rule | Contract |
|---|---|
| Paths | Relative paths are resolved from `root_directory`; absolute paths are allowed. |
| Tabular files | CSV and Parquet are interchangeable when columns and units are equivalent. |
| Energy | Dataset energy series are `kWh/step`. |
| Power and limits | Power ratings and limits are `kW`. |
| Prices | Prices are per `kWh`. |
| Emissions | Carbon intensity is `kgCO2/kWh`. |
| Timesteps | Windows, deadlines and topology events use global simulation timestep indices. |
| Legacy washing machines | `washing_machines` and `washing_machine_energy_simulation` are not the official format. Use `deferrable_appliances`. |

## Top-Level Keys

| Key | Type | Required | Purpose |
|---|---:|---:|---|
| `root_directory` | string | yes | Base folder for dataset files. |
| `random_seed` | int/null | no | Global random seed. |
| `random_stream_version` | string | no | How random streams are derived from `random_seed`: `v2` (default, one independent `SeedSequence` stream per purpose, object and episode) or `v1` (CityLearn 3.6.0 and earlier). The `random_stream_version` constructor argument overrides it. See the [migration guide](migration.md#random-streams). |
| `central_agent` | bool | yes | Single controller or one agent per building. |
| `seconds_per_time_step` | number | yes | Physical duration of each step. |
| `simulation_start_time_step` | int | yes | First global timestep. |
| `simulation_end_time_step` | int | yes | Last global timestep. |
| `episode_time_steps` | int/list/null | no | Episode length or explicit episode windows. |
| `rolling_episode_split` | bool/null | no | Sequential episode windows. |
| `random_episode_split` | bool/null | no | Random episode windows. |
| `time_step_ratio_mode` | `reject`/`compress`/null | no | `reject` (default) refuses a `seconds_per_time_step` that differs from the dataset step; `compress` keeps the 3.6.0 behaviour of reading one data row per control step and scaling energies. |
| `episode_split_boundary` | `shared`/`disjoint`/null | no | How consecutive episode splits meet. `shared` (default) starts each split on the terminal row of the previous one, so every interval is simulated; `disjoint` keeps the 3.6.0 splits, which skip the interval between two episodes. |
| `reward_function` | object/string | yes | Reward class and kwargs. |
| `observations` | object | yes | Flat observation catalog and flags. |
| `actions` | object | yes | Flat action catalog and flags. |
| `buildings` | object | yes | Building definitions. |
| `agent` | object/string | no | CLI agent configuration. |
| `electric_vehicles_def` | object | if EVs exist | EV catalog. |
| `interface` | `flat`/`entity` | no | Environment I/O mode. |
| `observation_bundles` | object | no | Additional entity observation bundles. |
| `topology_mode` | `static`/`dynamic` | no | Enables topology events. |
| `topology_events` | list | if dynamic | Add/remove events. |
| `demand_response` | object | no | Dataset-driven DSO/TSO flexibility requests and settlement. |
| `robustness` | object | no | Dataset-driven observation, forecast, action and asset availability perturbations. |
| `community_market` | object | no | Local market and market KPIs. |
| `ev_departure_within_tolerance` | float | no | Symmetric departure SOC accuracy tolerance, default `0.05`. |
| `ev_departure_service_tolerance` | float | no | Lower departure SOC service tolerance for minimum acceptable EV service, default `0.05`. |
| `render_mode` | string | no | `none`, `during` or `end`. |
| `render_file_format` | `csv`/`parquet` | no | Export format for render, KPI and BAU time-series files. |
| `render_chunk_size` | int | no | Rows per export chunk; defaults to `50000` for parquet and `100000` for CSV. |
| `export_kpis_on_episode_end` | bool | no | Export KPIs at episode end. |
| `start_date` | string | no | Base date for render/export. |
| `debug_timing` | bool | no | Runtime timing logs. |
| `check_observation_limits` | bool | no | Validate observation bounds. |
| `physics_invariant_checks` | bool | no | Runtime physical invariant checks. |
| `physics_version` | int | no | Physics version, `1` or `2` (default). `1` reproduces the physics of CityLearn 3.6.0; see the [migration guide](migration.md#physics-version). The `physics_version` argument of `CityLearnEnv` takes precedence. |
| `metrics_log_interval` | int | no | Runtime metric log cadence. |

### Calendar and dataset metadata keys

These keys describe the dataset clock and its provenance; the Portugal REC
schemas (`pt_rec_*`) use several of them. The first five change how the dataset
clock is read; the others are descriptive metadata that
the simulator does not read, kept so a dataset can be traced to its source.

| Key | Type | Effect |
|---|---:|---|
| `time_axis.calendar_file` | string | Canonical calendar with the columns `time_step` and `timestamp_utc` (and optionally `timestamp_local`), one regular row per dataset row. It sets the dataset step and the timestamps of rendered and exported series, unless `start_date` is passed to `CityLearnEnv`. |
| `timezone` | string | IANA time zone of the calendar, e.g. `Europe/Lisbon`. Exported timestamps are converted from UTC to this zone; an unknown name raises an error at load time. Without a calendar it is only recorded. |
| `dataset_seconds_per_time_step` | number | Declared dataset step in seconds, for data whose calendar columns cannot give it. It must agree with the calendar. |
| `dataset_contract_version` | string | Version of the dataset's data contract. A value starting with `portugal-native` makes `shared/calendar.parquet` the calendar when `time_axis` is absent; otherwise it is metadata. |
| `terminal_observation_padding` | bool | Allows the files to stop one row short of the window and repeats the last row as the terminal observation only, which is never simulated. Default `false`. |
| `dataset_id`, `dataset_family` | string | Metadata: dataset identifiers. |
| `experimental_design` | object | Metadata: the evaluation design the dataset was built for (factors, purpose, labels). |
| `native_compatibility` | object | Metadata: the engine commit and checks the dataset was validated with. |
| `_derivation`, `_derived_from` | object/string | Metadata: how a derived dataset was produced from its source. |

## `observations`

```json
"hour": {
  "active": true,
  "shared_in_central_agent": true
}
```

| Field | Type | Default | Purpose |
|---|---:|---:|---|
| `active` | bool | `false` | Enables the flat observation. |
| `shared_in_central_agent` | bool | `false` | Includes a common observation once in central-agent vectors. |

Observation names with prefix `electric_vehicle_` are expanded per charger. Names with prefix `deferrable_appliance_` are expanded per deferrable appliance. Names with prefix `escalator_` are expanded per escalator.

## `actions`

```json
"electrical_storage": {
  "active": true
}
```

| Field | Type | Default | Purpose |
|---|---:|---:|---|
| `active` | bool | `false` | Enables the action. |

`electric_vehicle_storage` expands to `electric_vehicle_storage_{charger_id}`. `deferrable_appliance` expands to `deferrable_appliance_{appliance_id}`. `escalator` expands to `escalator_{escalator_id}`.

## `observation_bundles`

Entity-only configuration:

```json
"observation_bundles": {
  "entity_core_electrical": true,
  "entity_community_operational": true,
  "entity_forecasts_existing": false,
  "entity_forecasts_derived": false,
  "entity_demand_response": false,
  "entity_robustness": false,
  "entity_action_feedback": false,
  "entity_temporal_derived": true
}
```

| Bundle | Default | Adds |
|---|---:|---|
| `entity_base` | always on | Essential charger, storage, phase and deferrable features. |
| `entity_core_electrical` | `false` | Power, step energy, PV, BESS, EV, efficiency and building electrical metrics. |
| `entity_community_operational` | `false` | District/community aggregates, headroom, counts and topology version. |
| `entity_forecasts_existing` | `false` | Forecasts already present in the dataset. |
| `entity_forecasts_derived` | `false` | Compact point forecasts for price, load, PV and net demand. |
| `entity_demand_response` | `false` | Current district DR request fields, frozen baseline and previous-step delivery/shortfall. |
| `entity_robustness` | `false` | Active robustness state and previous-step corruption counters in the district table. |
| `entity_temporal_derived` | `false` | Short lags, rolling means and calendar sin/cos features. |
| `entity_action_feedback` | `false` | Requested, limited and applied action feedback plus clipping-reason flags. |

Load/PV sources for the derived bundle are configurable:

```json
"derived_forecasts": {
  "load_pv_method": "daily_persistence",
  "persistence_period_seconds": 86400,
  "cold_start": "current_step",
  "price_source": "publication_aware_day_ahead_market_input",
  "price_publication_time_local": "13:00",
  "price_unpublished_fallback": "daily_persistence",
  "price_horizon_steps": [4, 24, 96]
}
```

`actual_future` remains the backward-compatible load/PV default. Use
`daily_persistence` for causal algorithm benchmarks that must not expose future
load or PV truth.

## `buildings`

```json
"buildings": {
  "Building_1": {
    "include": true,
    "type": "citylearn.building.Building",
    "energy_simulation": "Building_1.csv",
    "weather": "weather.parquet",
    "pricing": "pricing.csv",
    "carbon_intensity": "carbon.csv"
  }
}
```

| Key | Type | Required | Purpose |
|---|---:|---:|---|
| `include` | bool | no | Include the building initially. In dynamic topology it may start inactive. |
| `type` | string | no | Building class path, e.g. `citylearn.building.Building`. |
| `energy_simulation` | string | yes | Main load, calendar and PV input file. |
| `weather` | string/object | yes | Weather file. |
| `pricing` | string/object | yes | Pricing file. |
| `carbon_intensity` | string/object | no | Carbon intensity file. |
| `inactive_observations` | list | no | Disable observations for this building. |
| `inactive_actions` | list | no | Disable actions for this building. |
| `cooling_device`, `heating_device`, `dhw_device` | object | HVAC datasets | End-use devices. |
| `cooling_storage`, `heating_storage`, `dhw_storage` | object | HVAC datasets | Thermal storages. |
| `electrical_storage` | object | no | Building BESS. |
| `pv` | object | no | Building PV. |
| `chargers` | object | no | EV chargers. |
| `deferrable_appliances` | object | no | Normalized deferrable appliances. |
| `charging_constraints` | object | no | Building/phase charging limits. |
| `electrical_service` | object | no | Import/export service limits, see [Electrical Service](#electrical-service). |
| `equity_group` | string | no | Group used by equity KPIs. |
| `dynamics` | object | no | Indoor temperature dynamics model. |
| `occupant` | object | no | Occupant interaction model. |
| `power_outage` | object | no | Outage configuration. |
| `set_point_hold_time_steps` | int | no | Hold time for occupant interaction. |
| `set_point_limits` | [float, float] | no | Range, in °C, an occupant can move a heating or cooling set point to; default `[15, 30]`. Physics version 2 and later; see the [migration guide](migration.md#occupant-set-point-limits). |

`power_outage` keys:

| Key | Type | Default | Purpose |
|---|---:|---|---|
| `simulate_power_outage` | bool | `false` | Simulate grid outages for this building. |
| `stochastic_power_outage` | bool | `false` | Draw outages from `stochastic_power_outage_model` instead of the `power_outage` column. |
| `stochastic_power_outage_model` | object | `PowerOutage` | Outage model class and attributes. |
| `vehicle_to_building` | bool | `false` | Let a connected EV discharge to the building during an outage (vehicle-to-building backup), up to the islanded load that PV and the battery leave uncovered. The entity charger features `can_discharge` and `available_discharge_power_kw` report the vehicle's discharge capacity during the outage. The discharge can take the vehicle below its required departure SOC. |

## Device Sections

Common shape:

```json
"electrical_storage": {
  "type": "citylearn.energy_model.Battery",
  "attributes": {
    "capacity": 50.0,
    "nominal_power": 25.0,
    "depth_of_discharge": 0.9
  },
  "autosize": false,
  "autosize_attributes": {}
}
```

| Field | Type | Purpose |
|---|---:|---|
| `type` | string | Python class path. |
| `attributes` | object | Constructor kwargs. |
| `autosize` | bool | Calls the building autosizer when available. |
| `autosize_attributes` | object | Autosizer kwargs. |

Common classes:

| Class | Main attributes |
|---|---|
| `citylearn.energy_model.HeatPump` | `nominal_power`, `efficiency`, `target_heating_temperature`, `target_cooling_temperature`. |
| `citylearn.energy_model.ElectricHeater` | `nominal_power`, `efficiency`. |
| `citylearn.energy_model.StorageTank` | `capacity`, `efficiency`, `loss_coefficient`, `initial_soc`, `max_output_power`, `max_input_power`. |
| `citylearn.energy_model.Battery` | `capacity`, `nominal_power`, `capacity_loss_coefficient`, `power_efficiency_curve`, `capacity_power_curve` (charging), `discharge_power_curve` (discharging, physics version 2), `depth_of_discharge`. |
| `citylearn.energy_model.PV` | `nominal_power`, `generation_mode`. |

## PV

```json
"pv": {
  "type": "citylearn.energy_model.PV",
  "attributes": {
    "nominal_power": 120.0,
    "generation_mode": "absolute"
  }
}
```

| `generation_mode` | Aliases | Interprets `energy_simulation.solar_generation` as | Formula |
|---|---|---|---|
| `per_kw` | `profile`, `w_per_kw` | Normalized profile per installed kW in `W/kW`. | `generation_kwh = nominal_power * value / 1000`. |
| `absolute` | `absolute_kwh`, `kwh`, `kwh_step`, `energy` | Absolute generation already in `kWh/step`. | `generation_kwh = value`. |

Use `absolute` for real measured generation or converter-generated energy series. Use `per_kw` for normalized PV profiles.

## Electrical Service

`buildings.<name>.electrical_service` sets the building's grid connection limits. Limits are
active power in kW; `null`, a missing key or `Infinity` means no limit.

```json
"electrical_service": {
  "mode": "single_phase",
  "limits": {
    "total": {"import_kw": 17.25, "export_kw": 6.9},
    "per_phase": {"L1": {"import_kw": 17.25, "export_kw": 6.9}}
  },
  "available_grid_power": {"filename": "available_grid_power.csv", "column": "Building_1"},
  "observations": {"available_grid_power": true}
}
```

| Field | Type | Purpose |
|---|---:|---|
| `mode` | `single_phase`, `three_phase` | Service type. Single-phase services only have `L1`. |
| `default_split` | `balanced`, `L1`, `L2`, `L3` | Phase split of load without a phase connection. |
| `limits.total.import_kw`, `limits.total.export_kw` | kW | Static connection capacity. |
| `limits.per_phase.<L1/L2/L3>.import_kw`, `export_kw` | kW | Static per-phase limits. |
| `available_grid_power` | path or object | Optional per-step import availability series, see below. |
| `observations.headroom`, `observations.headroom_export` | bool | Expose import/export headroom observations. Default true. |
| `observations.violation` | bool | Expose `charging_constraint_violation_kwh`. Default true. |
| `observations.phase_encoding` | bool | Expose one-hot charger phase assignment. Default false. |
| `observations.available_grid_power` | bool | Expose the `available_grid_power` observation when a series is set. Default true. |

### Available grid power

`available_grid_power` names a CSV or Parquet file with one row per time step, aligned with
`energy_simulation`. Give it as a file name or as `{"filename": ..., "column": ...}`. Without
`column`, the column named after the building is used, then a column named
`available_grid_power`, so one file can hold a column per building. Values are the grid power
the building may import at that step, in kW (power, not energy per step).

The import limit in force at a step is the smaller of `limits.total.import_kw` and the series
value. A blank value applies the static limit only; it is an error when `import_kw` is not
set. Values must be finite and non-negative. Use it for curtailment below the connection
capacity, such as a distribution system operator dimming controllable devices (German
§14a EnWG) or a capacity reduction during grid stress.

The limit acts like the static one: EV chargers and the electrical storage are curtailed
first, and load that cannot be curtailed is still served and counted as an electrical-service
violation. A limit of 0 kW does not island the building; use [`power_outage`](#buildings)
for a blackout. Per-phase limits stay static. The `available_grid_power` observation reports
the limit for the coming interval; the headroom observations describe the last executed
interval, so they reflect the limit that was in force then.

## Chargers

```json
"chargers": {
  "AC001": {
    "type": "citylearn.electric_vehicle_charger.Charger",
    "charger_simulation": "chargers/AC001.parquet",
    "attributes": {
      "max_charging_power": 7.4,
      "min_charging_power": 1.4,
      "max_discharging_power": 0.0,
      "min_discharging_power": 0.0,
      "efficiency": 0.95,
      "phase_connection": "L1"
    }
  }
}
```

| Field | Unit | Purpose |
|---|---:|---|
| `charger_simulation` | path | Charger schedule file. |
| `max_charging_power` | kW | Charging upper limit. |
| `min_charging_power` | kW | Technical minimum charging power. |
| `max_discharging_power` | kW | V2G upper limit. |
| `min_discharging_power` | kW | Technical minimum V2G power. |
| `efficiency` | ratio | Fixed/default efficiency. |
| `charge_efficiency_curve` | ratio vs normalized power | Optional charging efficiency curve. |
| `discharge_efficiency_curve` | ratio vs normalized power | Optional discharging efficiency curve. |
| `phase_connection` | `L1`, `L2`, `L3`, `all_phases` | Electrical phase assignment. |

## EV Definitions

```json
"electric_vehicles_def": {
  "EV_1": {
    "type": "citylearn.electric_vehicle.ElectricVehicle",
    "include": true,
    "battery": {
      "attributes": {
        "capacity": 60.0,
        "nominal_power": 50.0,
        "initial_soc": 0.4,
        "depth_of_discharge": 0.9
      }
    }
  }
}
```

| Field | Purpose |
|---|---|
| `type` | EV class path. |
| `include` | Include the EV in the initial pool. |
| `battery.attributes` | `Battery` kwargs. |

EV battery standby loss is intentionally isolated from stationary storage defaults:

- Missing or `null` `battery.attributes.loss_coefficient` defaults to `0.0` for EVs.
- Explicit EV `loss_coefficient` values are interpreted as hourly loss ratios.
- All `StorageDevice` implementations, including stationary `Battery` and `StorageTank`, convert hourly `loss_coefficient` values to effective per-step loss with `loss_coefficient * seconds_per_time_step / 3600`.
- Stationary storage default parameter ranges are unchanged.

## Deferrable Appliances

```json
"deferrable_appliances": {
  "washer_1": {
    "type": "citylearn.energy_model.DeferrableAppliance",
    "cycle_profiles_file": "deferrables/washer_profiles.csv",
    "flexibility_schedule_file": "deferrables/washer_schedule.csv",
    "attributes": {
      "trigger_threshold": 0.5
    }
  }
}
```

| Field | Required | Purpose |
|---|---:|---|
| `type` | no | Appliance class. Default: `citylearn.energy_model.DeferrableAppliance`. |
| `cycle_profiles_file` | yes | Physical cycle profile catalog. |
| `flexibility_schedule_file` | yes | Flexibility requests/windows. |
| `attributes.trigger_threshold` | no | Start action threshold (default `0.5`; `action > threshold` is interpreted as ON). |

## Escalators (flat interface)

```json
"escalators": {
  "EscadaRolante_1": {
    "type": "citylearn.energy_model.Escalator",
    "simulation": "EscadaRolante_1.csv",
    "attributes": {
      "standby_power": 0.08,
      "slow_power": 0.42,
      "normal_power": 2.10,
      "minimum_state_steps": 1,
      "service_threshold_passengers": 0.5
    }
  }
}
```

| Field | Required | Purpose |
|---|---:|---|
| `type` | no | Escalator class. Default: `citylearn.energy_model.Escalator`. |
| `simulation` | yes | CSV with one row per simulation step. |
| `attributes.standby_power`, `slow_power`, `normal_power` | yes | Non-negative kW powers; must be non-decreasing. |
| `attributes.minimum_state_steps` | no | Minimum residence in a state; default `1`. |
| `attributes.service_threshold_passengers` | no | Passenger demand above which service is required; default `0.5`. |

The CSV requires `time_step`, `passengers_from_trains_15min`,
`background_pedestrians_15min`, `passengers_expected_15min`, `people_detected`,
`arriving_trains`, `departing_trains`, `minutes_to_next_train` and `available`.
`passengers_expected_15min` must equal the sum of the two passenger components.
Escalator support is currently exposed through the flat interface.

## Dynamic Topology

`topology_mode="dynamic"` requires `interface="entity"`.

```json
"topology_events": [
  {
    "id": "add_pv_b2_t100",
    "time_step": 100,
    "operation": "add_asset",
    "target_member_id": "Building_2",
    "target_asset_type": "pv",
    "target_asset_id": "pv_1",
    "source_member_id": "Building_1",
    "source_asset_id": "pv_1",
    "overrides": {"nominal_power": 80.0}
  }
]
```

| Field | Type | Purpose |
|---|---:|---|
| `id` | string | Event ID. |
| `time_step` | int | Global timestep where the event is applied. |
| `operation` | enum | `add_member`, `remove_member`, `add_asset`, `remove_asset`. |
| `target_member_id` | string | Target building. |
| `target_asset_type` | enum | `charger`, `deferrable_appliance`, `pv`, `electrical_storage`. |
| `target_asset_id` | string | Target asset. |
| `source_member_id` | string | Source building for cloning. |
| `source_asset_id` | string | Source asset for cloning. |
| `overrides` | object | Attributes applied after cloning. |

Removing a deferrable appliance cancels pending/running cycles and clears future consumption. Removing PV creates a zero PV. Removing storage creates a zero BESS.

A member's time-series files (energy simulation, chargers, escalators) are either full-horizon, with one row per dataset time step, or member-window files, shorter than the dataset, whose first row is the time step of the member's `add_member` event. A member-window file should cover the member's active steps in the simulation window (otherwise its last row is repeated, with a warning), and a member that joins again after leaving needs full-horizon files. A member that joins mid-episode starts its battery and thermal storage at `initial_soc`.

## Demand Response

Demand response v1 is dataset-driven and entity-only. The agent observes district-level flexibility requests and responds through the physical actions that already exist, such as storage, EVs and flexible loads.

```json
"demand_response": {
  "enabled": true,
  "requests_file": "demand_response_requests.csv",
  "baseline_method": "rolling_pre_event_average",
  "baseline_window_seconds": 3600,
  "allow_overlapping_requests": false
}
```

| Field | Default | Purpose |
|---|---:|---|
| `enabled` | `false` | Enables demand-response request loading, observations, settlement and KPIs. |
| `requests_file` | required when enabled | CSV or Parquet file relative to `root_directory` or the schema folder. |
| `baseline_method` | `rolling_pre_event_average` | Baseline method. This is the only v1 method. |
| `baseline_window_seconds` | `3600` | Pre-event history window used to compute the frozen event baseline. |
| `allow_overlapping_requests` | `false` | Overlapping requests are rejected in v1. |

Request file columns:

| Column | Unit/domain | Meaning |
|---|---:|---|
| `request_id` | string | Unique request ID. Exposed in observation `meta`. |
| `issuer` | `dso`/`tso` | Entity that issued the request. |
| `direction` | `up`/`down` | Load perspective: `up` increases net load, `down` reduces net load. |
| `start_time_step`, `end_time_step` | global timestep | Inclusive activation window. |
| `target_power_kw` | kW | Positive district target power. |
| `activation_price_eur_per_kwh` | currency/kWh | Credited delivery price. |
| `shortfall_penalty_eur_per_kwh` | currency/kWh | Penalty for shortfall. |
| `tolerance_power_kw` | kW | Optional tolerance; defaults to `0`. |

When active, enable the observation bundle:

```json
"observation_bundles": {
  "entity_demand_response": true
}
```

The numeric features are added to the `district` entity table. The active `request_id` is kept in `observations["meta"]["demand_response"]`, not in the numeric matrix.

## Robustness

Robustness v1 is dataset-driven and fully optional. Observation and forecast events corrupt only the payload returned to the agent. Rewards, physical KPIs and demand-response settlement continue to use the real simulator state. Action and asset-control events change the action effectively applied.

```json
"robustness": {
  "enabled": true,
  "events_file": "robustness_events.csv",
  "random_seed": 0,
  "missing_replacement_value": -9999.0,
  "modules": {
    "observations": {"enabled": true},
    "forecasts": {"enabled": true},
    "actions": {"enabled": true},
    "assets": {"enabled": true}
  }
}
```

| Field | Default | Purpose |
|---|---:|---|
| `enabled` | `false` | Enables robustness event loading and application. |
| `events_file` | required when enabled | CSV or Parquet file relative to `root_directory` or the schema folder. |
| `random_seed` | `0` | Deterministic seed for event noise. |
| `missing_replacement_value` | `-9999.0` | Default sentinel for missing observation/telemetry values. |
| `modules.*.enabled` | `true` when robustness is enabled | Individually enables observations, forecasts, actions and assets. |

Event file columns:

| Column | Unit/domain | Meaning |
|---|---:|---|
| `event_id` | string | Unique event ID exposed in metadata. |
| `module` | `observation`/`forecast`/`action`/`asset` | Perturbation module. |
| `target_type` | entity type | `district`, `building`, `storage`, `charger`, `ev`, `pv` or `deferrable_appliance`. |
| `target_id` | id or `*` | Target entity name/id, or all compatible targets. |
| `target_feature` | feature/action | For assets use `telemetry`, `control` or `both`. |
| `start_time_step`, `end_time_step` | global timestep | Inclusive activation window. |
| `mode` | enum | Observation/forecast: `missing`, `noise`, `bias`, `stuck`, `clip`; action: `dropout`, `noise`, `bias`, `stuck`, `delay`, `clip`; asset: `unavailable`. |
| `value`, `std`, `min_value`, `max_value` | numeric | Optional mode parameters. |
| `replacement_value` | numeric | Optional missing/telemetry sentinel. |
| `delay_steps` | count | Optional action delay horizon. |

When using entity observations, enable diagnostics if needed:

```json
"observation_bundles": {
  "entity_robustness": true
}
```

Metadata is exposed under `observations["meta"]["robustness"]`.

## Community Market

```json
"community_market": {
  "enabled": true,
  "local_price_ratio_to_grid_import": 0.8,
  "import_member_weights": {
    "Building_1": 1.0,
    "Building_2": 2.0
  },
  "kpis": {
    "community_local_traded_enabled": true,
    "community_self_consumption_enabled": true
  }
}
```

| Field | Default | Purpose |
|---|---:|---|
| `enabled` | `false` | Enables local settlement. |
| `local_price_ratio_to_grid_import` | `0.8` | Local price relative to grid import price. A number from 0 to 1. |
| `intra_community_sell_ratio` | alias | Legacy name for the same ratio. If both keys are set, they must be equal. |
| `settlement_version` | `1` | The integer `1` or `2`. `2` enables `grid_export_price`; with `1`, residual grid exports earn nothing. |
| `grid_export_price` | `0.0` | EUR/kWh paid for residual grid exports. A finite number; a non-zero value requires `"settlement_version": 2`. |
| `tariff_files` | `{}` | Per-member CSV tariffs, `{"<building>": "<file inside the dataset>"}`. Each file has one row per global time step with `grid_export_price`, `community_buy_price` and `community_sell_price` (EUR/kWh) and must cover the episode. A member with a file uses these prices instead of the ratio and `grid_export_price`. |
| `local_trading_enabled` | `true` | `false` keeps the market's settlement and KPIs but trades no energy locally. Booleans or `"true"`/`"false"`. |
| `import_member_weights` | `{}` | Weights for allocating local energy among importers, `{"<building>": weight}`. Each building must be in the schema and each weight a finite number of at least 0. |
| `kpis.community_local_traded_enabled` | `true` | Enables local traded energy KPI. |
| `kpis.community_self_consumption_enabled` | `true` | Enables local import-share KPI. |
| `matching_granularity` | `"aggregate_building"` | The only supported value; recorded in the metadata. |

## Important Combinations

The settings are checked when the env is built, even with `enabled: false`.
An unknown key (for example `enable`), a ratio that is not a number or is
outside `[0, 1]`, a `settlement_version` other than the integer `1` or `2`
(the string `"2"` included), a non-zero `grid_export_price` without
`"settlement_version": 2`, and a member weight or tariff file for a building
that is not in the schema raise a `ValueError`. Earlier releases ignored these
settings or replaced them with defaults. The legacy
`intra_community_sell_ratio` key is an alias.

The settings are read from the schema at construction. Setting the market
attributes on the env afterwards (`community_market_sell_ratio`,
`community_market_grid_export_price`, `community_market_import_member_weights`,
`community_market_local_enabled`, `community_tariffs`) is not supported: the
native BAU reference is rebuilt from the schema, so `evaluate_v2()` with the
BAU comparison raises a `ValueError` when they differ. To change the market,
edit `schema['community_market']` and build a new env. Local settlement values
same-timestep member imports and exports; it does not change the physical
device dispatch.

Each side of a local trade is priced with its own member's tariff. When members
have different grid tariffs or `tariff_files`, importers can pay a different amount
from what exporters receive for the same energy. The difference is reported as
`community_operator_balance_total_eur` (positive when the market keeps money);
it is zero with a single shared tariff.

| Case | Configuration |
|---|---|
| Classic flat training | Omit `interface` or use `interface="flat"`; static topology. |
| Entity/GNN/Transformer | `interface="entity"` plus desired observation bundles. |
| Dynamic topology | `interface="entity"`, `topology_mode="dynamic"`, `topology_events`. |
| Demand response | `interface="entity"`, `demand_response.enabled=true`, `entity_demand_response` bundle. |
| Robustness | Any interface, `robustness.enabled=true`; add `entity_robustness` for entity diagnostics. |
| Real PV measurements | `pv.attributes.generation_mode="absolute"`. |
| 15-second data | `seconds_per_time_step=15` and files already at that cadence. |
| Large datasets | Prefer Parquet paths with the same columns. |
