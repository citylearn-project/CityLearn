# Full Reference Schema

[`examples/schema_full_reference.json`](https://github.com/citylearn-project/CityLearn/blob/master/examples/schema_full_reference.json)
is a complete schema that writes out every option CityLearn reads. It runs as it is from a source checkout: it uses two
buildings (`Building_1` and `Building_4`) and two EVs of the `citylearn_challenge_2022_phase_all_plus_evs` dataset.
Copy it, point `root_directory` at your data and change only what you need.

```python
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv("examples/schema_full_reference.json")
```

JSON has no comments, so this page walks through the file section by section. Each block below is a part of the file
(together they are the whole file), followed by what each key does, its default and its alternatives. The
[schema reference](schema_reference.md) has the full rules.

How to read the values:

- Where a key has a default, the file uses it. A `null` in device, charger and EV `attributes` means "use the default",
  including defaults drawn from the random stream.
- Required keys without a default (file names, sizes, the time window) use the dataset's values.
- Features that are off by default (community market, demand response, robustness, outages, dynamic topology) are
  written out with `enabled: false` or empty lists, so you can see their shape and turn them on.
- The selection of active observations and actions is an example; every name is `false` by default.

Portuguese version: [pt/schema_full_reference.md](pt/schema_full_reference.md).

## Data location, seeds and versions

```json
{
  "root_directory": "../data/datasets/citylearn_challenge_2022_phase_all_plus_evs",
  "random_seed": 2022,
  "random_stream_version": "v2",
  "physics_version": 2,
  "baseline_version": 2
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `root_directory` | dataset folder, relative to the schema file | the schema's folder | Every file name below is read from here. A `dict` schema must set it. The `root_directory` argument overrides it. |
| `random_seed` | `2022` | a new random seed at each construction | Set it for repeatable runs: drawn device parameters, EV initial SOC and drift, noise and random episodes depend on it. |
| `random_stream_version` | `"v2"` | `"v2"` | `"v1"` reproduces the random draws of CityLearn 3.6.0. |
| `physics_version` | `2` | `2` | `1` reproduces the physics of 3.6.0; see [What each version changes](schema_reference.md#what-each-version-changes). |
| `baseline_version` | `2` | `2` | `1`: the KPI baseline adds no EV charging back, and the BAU sends zero to the HVAC actions, as in 3.6.0. This dataset has no HVAC actions, so its BAU is the same under both versions. |

## Agent layout, time window and episodes

```json
{
  "central_agent": false,
  "interface": "flat",
  "seconds_per_time_step": 3600,
  "time_step_ratio_mode": "reject",
  "simulation_start_time_step": 0,
  "simulation_end_time_step": 8759,
  "episode_time_steps": null,
  "rolling_episode_split": false,
  "random_episode_split": false,
  "episode_split_boundary": "shared",
  "ev_soc_carryover": false,
  "episode_end": "truncated"
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `central_agent` | `false` | required | `true`: one observation and action vector for all buildings. |
| `interface` | `"flat"` | `"flat"` | `"entity"`: tables and edges, needed for demand response and dynamic topology. |
| `seconds_per_time_step` | `3600` | required | Must equal the data step (hourly here). |
| `time_step_ratio_mode` | `"reject"` | `"reject"` | `"compress"` reads one data row per control step when the steps differ, as 3.6.0 did. |
| `simulation_start_time_step`, `simulation_end_time_step` | `0`, `8759` | required | Data rows, both inclusive: one year, 8759 control steps. |
| `episode_time_steps` | `null` | `null` | `null`: one episode. An int `N`: episodes of `N` rows. A list of `[start, end]`: fixed episodes. |
| `rolling_episode_split` | `false` | `false` | `true`: every row can start an episode. |
| `random_episode_split` | `false` | `false` | `true`: draw the episode at each reset. |
| `episode_split_boundary` | `"shared"` | `"shared"` | `"disjoint"`: the 3.6.0 splits, which skip one interval between episodes. |
| `ev_soc_carryover` | `false` | `false` | `true`: an episode that continues the previous one in time starts each EV from its SOC at the end of that episode. |
| `episode_end` | `"truncated"` | `"truncated"` | `"terminated"`: the last step returns `terminated=True`, as 3.7.0 and earlier did. |

## Calendar and dataset clock

```json
{
  "time_axis": {"calendar_file": null},
  "timezone": null,
  "dataset_seconds_per_time_step": null,
  "dataset_contract_version": null,
  "terminal_observation_padding": false,
  "start_date": "2024-01-01"
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `time_axis.calendar_file` | `null` | none | A CSV or Parquet calendar with `time_step` and `timestamp_utc`; it sets the dataset step and the exported timestamps. |
| `timezone` | `null` | none | IANA name such as `"Europe/Lisbon"` for calendar timestamps. |
| `dataset_seconds_per_time_step` | `null` | inferred from the calendar columns | Declare the data step when `hour`/`minutes`/`seconds` cannot give it. |
| `dataset_contract_version` | `null` | none | Metadata; a value starting with `portugal-native` selects `shared/calendar.parquet` as calendar. |
| `terminal_observation_padding` | `false` | `false` | `true` allows files one row short of the window. |
| `start_date` | `"2024-01-01"` | `"2024-01-01"` | Date of row 0 in exported timestamps. It does not change the simulation. |

## Reward and agent

```json
{
  "reward_function": {
    "type": "citylearn.reward_function.RewardFunction",
    "attributes": {"exponent": 1.0, "charging_constraint_penalty_coefficient": 1.0}
  },
  "agent": {"type": "citylearn.agents.baseline.BusinessAsUsualAgent", "attributes": {}}
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `reward_function.type` | `RewardFunction` | required | Other classes: `ComfortReward`, `SolarPenaltyReward`, `SolarPenaltyAndComfortReward`, `Electric_Vehicles_Reward_Function`, `OutageUnservedEnergyReward`, `MARL`, `IndependentSACReward`; or an object keyed by building with `"default"`. |
| `reward_function.attributes` | the two defaults of `RewardFunction` | `{}` | `exponent` raises the import to a power; `charging_constraint_penalty_coefficient` is accepted here but only `Electric_Vehicles_Reward_Function` uses it, to weight charging-limit violations. |
| `agent.type`, `agent.attributes` | `BusinessAsUsualAgent` | none | Used by `env.load_agent()` without arguments. The `citylearn simulate` command uses its `-a` option instead. |

## Observations

Every observation name CityLearn accepts in the catalogue is listed, except
`occupant_interaction_indoor_dry_bulb_temperature_set_point_delta`, which exists only for the occupant building type:
a name that a building cannot produce raises `KeyError` at construction, even when it is not active. `active` (default `false`) turns a name on for
every building that can produce it; `shared_in_central_agent` (default `false`) puts it once in the central vector when
`central_agent` is `true`. This file turns on a small example set and marks calendar, weather, price and carbon names
as shared, because they are the same for every building.

Names starting with `electric_vehicle_`, `connected_electric_vehicle_at_charger_` and
`incoming_electric_vehicle_at_charger_` are expanded per charger, `deferrable_appliance_*` per appliance and
`escalator_*` per escalator (for example `electric_vehicle_charger_charger_1_1_connected_state`). Electrical-service
observations are not listed here: `electrical_service.observations` switches them.

```json
{
  "observations": {
    "month": {"active": true, "shared_in_central_agent": true},
    "day_type": {"active": true, "shared_in_central_agent": true},
    "hour": {"active": true, "shared_in_central_agent": true},
    "minutes": {"active": false, "shared_in_central_agent": true},
    "seconds": {"active": false, "shared_in_central_agent": true},
    "daylight_savings_status": {"active": false, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature": {"active": true, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature_predicted_1": {"active": false, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature_predicted_2": {"active": false, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature_predicted_3": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity_predicted_1": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity_predicted_2": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity_predicted_3": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance_predicted_1": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance_predicted_2": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance_predicted_3": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance_predicted_1": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance_predicted_2": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance_predicted_3": {"active": false, "shared_in_central_agent": true},
    "electricity_pricing": {"active": true, "shared_in_central_agent": true},
    "electricity_pricing_predicted_1": {"active": false, "shared_in_central_agent": true},
    "electricity_pricing_predicted_2": {"active": false, "shared_in_central_agent": true},
    "electricity_pricing_predicted_3": {"active": false, "shared_in_central_agent": true},
    "carbon_intensity": {"active": true, "shared_in_central_agent": true},
    "non_shiftable_load": {"active": true, "shared_in_central_agent": false},
    "cooling_demand": {"active": false, "shared_in_central_agent": false},
    "heating_demand": {"active": false, "shared_in_central_agent": false},
    "dhw_demand": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature": {"active": false, "shared_in_central_agent": false},
    "indoor_relative_humidity": {"active": false, "shared_in_central_agent": false},
    "average_unmet_cooling_setpoint_difference": {"active": false, "shared_in_central_agent": false},
    "occupant_count": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_cooling_set_point": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_heating_set_point": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_cooling_delta": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_heating_delta": {"active": false, "shared_in_central_agent": false},
    "comfort_band": {"active": false, "shared_in_central_agent": false},
    "hvac_mode": {"active": false, "shared_in_central_agent": false},
    "cooling_device_efficiency": {"active": false, "shared_in_central_agent": false},
    "heating_device_efficiency": {"active": false, "shared_in_central_agent": false},
    "dhw_device_efficiency": {"active": false, "shared_in_central_agent": false},
    "cooling_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "heating_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "dhw_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "cooling_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "heating_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "dhw_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "electrical_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "cooling_storage_soc": {"active": false, "shared_in_central_agent": false},
    "heating_storage_soc": {"active": false, "shared_in_central_agent": false},
    "dhw_storage_soc": {"active": false, "shared_in_central_agent": false},
    "electrical_storage_soc": {"active": true, "shared_in_central_agent": false},
    "solar_generation": {"active": true, "shared_in_central_agent": false},
    "net_electricity_consumption": {"active": true, "shared_in_central_agent": false},
    "power_outage": {"active": false, "shared_in_central_agent": false},
    "power_outage_unserved_energy": {"active": false, "shared_in_central_agent": false},
    "electric_vehicle_charger_connected_state": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_departure_time": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_required_soc_departure": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_soc": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_battery_capacity": {"active": false, "shared_in_central_agent": false},
    "electric_vehicle_charger_incoming_state": {"active": false, "shared_in_central_agent": false},
    "incoming_electric_vehicle_at_charger_estimated_arrival_time": {"active": false, "shared_in_central_agent": false},
    "incoming_electric_vehicle_at_charger_estimated_soc_arrival": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_pending": {"active": true, "shared_in_central_agent": false},
    "deferrable_appliance_running": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_can_start": {"active": true, "shared_in_central_agent": false},
    "deferrable_appliance_deadline_missed": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_earliest_start_time_step": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_latest_start_time_step": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_deadline_time_step": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_hours_until_latest_start": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_hours_until_deadline": {"active": true, "shared_in_central_agent": false},
    "deferrable_appliance_slack_steps": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_slack_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_urgency_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_duration_steps": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_energy_kwh": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_remaining_energy_kwh": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_current_step_energy_kwh": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_priority": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_must_run": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_average_power_kw": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_peak_power_kw": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_load_factor_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_peak_step_offset_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_remaining_duration_steps": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_remaining_average_power_kw": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_current_step_power_kw": {"active": false, "shared_in_central_agent": false},
    "escalator_passengers_from_trains_15min": {"active": false, "shared_in_central_agent": false},
    "escalator_background_pedestrians_15min": {"active": false, "shared_in_central_agent": false},
    "escalator_passengers_expected_15min": {"active": false, "shared_in_central_agent": false},
    "escalator_people_detected": {"active": false, "shared_in_central_agent": false},
    "escalator_passing_trains": {"active": false, "shared_in_central_agent": false},
    "escalator_minutes_to_next_train": {"active": false, "shared_in_central_agent": false},
    "escalator_available": {"active": false, "shared_in_central_agent": false},
    "escalator_state": {"active": false, "shared_in_central_agent": false},
    "escalator_requested_state": {"active": false, "shared_in_central_agent": false},
    "escalator_power_kw": {"active": false, "shared_in_central_agent": false},
    "escalator_service_required": {"active": false, "shared_in_central_agent": false},
    "escalator_service_met": {"active": false, "shared_in_central_agent": false},
    "escalator_unserved_passengers_15min": {"active": false, "shared_in_central_agent": false}
  }
}
```

See the [observation catalogue](schema_reference.md#observations) for what each name means, and
[Observation bounds](interfaces_flat_entity.md#observation-bounds) for their limits.

## Actions

```json
{
  "actions": {
    "cooling_or_heating_device": {"active": false},
    "cooling_device": {"active": false},
    "heating_device": {"active": false},
    "cooling_storage": {"active": false},
    "heating_storage": {"active": false},
    "dhw_storage": {"active": false},
    "electrical_storage": {"active": true},
    "electric_vehicle_storage": {"active": true},
    "deferrable_appliance": {"active": true},
    "escalator": {"active": false}
  }
}
```

| Action | Here | Range and meaning |
|---|---|---|
| `cooling_or_heating_device`, `cooling_device`, `heating_device` | off | HVAC control; effective only for dynamics building types. |
| `cooling_storage`, `heating_storage`, `dhw_storage` | off | Charge (positive) or discharge (negative) the thermal storage. |
| `electrical_storage` | on | [-1, 1] × battery `nominal_power`. |
| `electric_vehicle_storage` | on | One action per charger: [-1, 1] × `max_charging_power` / `max_discharging_power`. |
| `deferrable_appliance` | on | One action per appliance: start the next cycle above `trigger_threshold`. |
| `escalator` | off | One action per escalator: standby, slow or normal. |

## Entity bundles and derived forecasts

These keys are read only with `"interface": "entity"`.

```json
{
  "observation_bundles": {
    "entity_core_electrical": false,
    "entity_community_operational": false,
    "entity_forecasts_existing": false,
    "entity_forecasts_derived": false,
    "entity_temporal_derived": false,
    "entity_action_feedback": false,
    "entity_demand_response": false,
    "entity_robustness": false
  },
  "derived_forecasts": {
    "load_pv_method": "actual_future",
    "persistence_period_seconds": 86400,
    "cold_start": "current_step",
    "price_source": "known_future_market_input",
    "price_horizon_steps": [1, 2, 3]
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `observation_bundles.<bundle>` | all `false` | `false` | Turn on the feature groups you need; `entity_base` is always on. |
| `derived_forecasts.load_pv_method` | `"actual_future"` | `"actual_future"` | `"daily_persistence"` gives causal load and PV forecasts. |
| `derived_forecasts.persistence_period_seconds` | `86400` | `86400` | Persistence period. |
| `derived_forecasts.cold_start` | `"current_step"` | `"current_step"` | The only value. |
| `derived_forecasts.price_source` | `"known_future_market_input"` | `"known_future_market_input"` | `"publication_aware_day_ahead_market_input"` or `"daily_persistence"` for causal prices. |
| `derived_forecasts.price_horizon_steps` | `[1, 2, 3]` | `[1, 2, 3]` | Lead of the three `electricity_pricing_predicted_*` columns, in steps. |

## Topology

```json
{"topology_mode": "static", "topology_events": []}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `topology_mode` | `"static"` | `"static"` | `"dynamic"` (with `"interface": "entity"`) applies `topology_events`. |
| `topology_events` | `[]` | `[]` | `add_member`, `remove_member`, `add_asset`, `remove_asset` events; see [Dynamic topology](schema_reference.md#dynamic-topology). |

## Building_1: data and selection

```json
{
  "buildings": {
    "Building_1": {
      "include": true,
      "type": "citylearn.building.Building",
      "energy_simulation": "Building_1.csv",
      "weather": "weather.csv",
      "pricing": "pricing.csv",
      "carbon_intensity": "carbon_intensity.csv",
      "noise_std": 0.0,
      "inactive_observations": [],
      "inactive_actions": [],
      "equity_group": null
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `include` | `true` | `true` | `false` leaves the building out (an inactive member under dynamic topology). |
| `type` | `citylearn.building.Building` | the same | `LSTMDynamicsBuilding` and the occupant types for indoor-temperature dynamics. |
| `energy_simulation`, `weather` | dataset files | required | |
| `pricing`, `carbon_intensity` | dataset files | zero series | With a zero series the cost or emissions ratios are NaN (0/0). |
| `noise_std` | `0.0` | `0.0` | Gaussian noise on weather, prices, carbon, PV profile and indoor conditions. |
| `inactive_observations`, `inactive_actions` | `[]` | `[]` | Template names turned off for this building only. |
| `equity_group` | `null` | none | `"asset_rich"` or `"asset_poor"` on every building enables the equity ratio KPI. |

## Building_1: HVAC devices

`Building_1` has no thermal demand in this dataset, so these devices only show the shape. On a building with demand,
size them or use `"autosize": true`.

```json
{
  "buildings": {
    "Building_1": {
      "cooling_device": {
        "type": "citylearn.energy_model.HeatPump",
        "autosize": false,
        "autosize_attributes": {"safety_factor": 1.0},
        "attributes": {
          "nominal_power": 4.0,
          "efficiency": null,
          "target_heating_temperature": null,
          "target_cooling_temperature": null
        }
      },
      "heating_device": {
        "type": "citylearn.energy_model.HeatPump",
        "autosize": false,
        "autosize_attributes": {"safety_factor": 1.0},
        "attributes": {
          "nominal_power": 4.0,
          "efficiency": null,
          "target_heating_temperature": null,
          "target_cooling_temperature": null
        }
      },
      "dhw_device": {
        "type": "citylearn.energy_model.ElectricHeater",
        "autosize": false,
        "autosize_attributes": {"safety_factor": 1.0},
        "attributes": {"nominal_power": 2.0, "efficiency": null}
      }
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `type` | `HeatPump` (cooling, heating), `ElectricHeater` (hot water) | required | `cooling_device` must be a `HeatPump`. |
| `nominal_power` | 4 kW, 4 kW, 2 kW | `0` | Electric input power. |
| `efficiency` | `null` | drawn: 0.2-0.3 (Carnot fraction) for heat pumps, 0.9-0.99 for heaters | |
| `target_heating_temperature`, `target_cooling_temperature` | `null` | drawn: 45-50 °C and 7-10 °C | Supply temperatures used for the COP. |
| `autosize` | `false` | `false` | `true` sizes `nominal_power` from the peak demand. |
| `autosize_attributes.safety_factor` | `1.0` | `1.0` | Multiplies the autosized power. |

## Building_1: thermal storage

```json
{
  "buildings": {
    "Building_1": {
      "cooling_storage": {
        "type": "citylearn.energy_model.StorageTank",
        "autosize": false,
        "autosize_attributes": {"safety_factor": null, "duration": 1.0},
        "attributes": {
          "capacity": 4.0,
          "efficiency": null,
          "loss_coefficient": null,
          "initial_soc": null,
          "max_input_power": null,
          "max_output_power": null
        }
      },
      "heating_storage": {
        "type": "citylearn.energy_model.StorageTank",
        "autosize": false,
        "autosize_attributes": {"safety_factor": null, "duration": 1.0},
        "attributes": {
          "capacity": 4.0,
          "efficiency": null,
          "loss_coefficient": null,
          "initial_soc": null,
          "max_input_power": null,
          "max_output_power": null
        }
      },
      "dhw_storage": {
        "type": "citylearn.energy_model.StorageTank",
        "autosize": false,
        "autosize_attributes": {"safety_factor": null, "duration": 1.0},
        "attributes": {
          "capacity": 2.0,
          "efficiency": null,
          "loss_coefficient": null,
          "initial_soc": null,
          "max_input_power": null,
          "max_output_power": null
        }
      }
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `type` | `StorageTank` | required | |
| `capacity` | 4, 4 and 2 kWh | `0` | Thermal energy. |
| `efficiency` | `null` | drawn in 0.90-0.98 | Round trip. |
| `loss_coefficient` | `null` | drawn in 0.001-0.009 per hour | Standby loss. |
| `initial_soc` | `null` | `0` | |
| `max_input_power`, `max_output_power` | `null` | unlimited | kW. |
| `autosize_attributes.safety_factor` | `null` | drawn in 1-2 | |
| `autosize_attributes.duration` | `1.0` | `1.0` hour | Hours of peak demand (physics version 2). |

## Building_1: battery and PV

```json
{
  "buildings": {
    "Building_1": {
      "electrical_storage": {
        "type": "citylearn.energy_model.Battery",
        "autosize": false,
        "autosize_attributes": {"duration": null, "parallel": false, "safety_factor": 1.0},
        "attributes": {
          "capacity": 6.4,
          "nominal_power": 5.0,
          "efficiency": null,
          "depth_of_discharge": null,
          "initial_soc": null,
          "loss_coefficient": null,
          "capacity_loss_coefficient": null,
          "power_efficiency_curve": null,
          "capacity_power_curve": null,
          "discharge_power_curve": null,
          "phase_connection": null
        }
      },
      "pv": {
        "type": "citylearn.energy_model.PV",
        "autosize": false,
        "autosize_attributes": {
          "epw_filepath": null,
          "use_sample_target": false,
          "zero_net_energy_proportion": null,
          "roof_area": null,
          "safety_factor": 1.0
        },
        "attributes": {"nominal_power": 12.0, "generation_mode": "per_kw", "efficiency": null}
      }
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `electrical_storage.attributes.capacity`, `nominal_power` | 6.4 kWh, 5 kW | `0` | A battery of size 0 cannot take the `electrical_storage` action. |
| `efficiency` | `null` | drawn in 0.90-0.98 | Round trip; enter a one-way datasheet value squared. |
| `depth_of_discharge` | `null` | `1.0` | Discharge floor `1 - depth_of_discharge`. |
| `initial_soc` | `null` | `1 - depth_of_discharge` | Start empty by default. |
| `loss_coefficient` | `null` | drawn in 0.001-0.009 per hour | |
| `capacity_loss_coefficient` | `null` | drawn in 1e-5-1e-4 | Capacity fade per equivalent full cycle. |
| `power_efficiency_curve`, `capacity_power_curve` | `null` | drawn curves | Give them to make the battery independent of the seed. |
| `discharge_power_curve` | `null` | `[[0, 1], [1, 1]]` | Physics version 1 uses `capacity_power_curve` for discharge too. |
| `phase_connection` | `null` | `L1` (single phase) | Phase under the electrical service. |
| `autosize_attributes` | `duration` drawn in 1.5-3.5 h, `parallel` `false`, `safety_factor` `1.0` | | Used only with `"autosize": true`. |
| `pv.attributes.nominal_power` | 12 kW | `0` | |
| `pv.attributes.generation_mode` | `"per_kw"` | `"per_kw"` | `"absolute"` when `solar_generation` is already kWh per step. |
| `pv.attributes.efficiency` | `null` | drawn, not used | |
| `pv.autosize_attributes` | `epw_filepath`, `use_sample_target`, `zero_net_energy_proportion`, `roof_area`, `safety_factor` | | PV autosizing needs an EPW weather file and `nrel-pysam`. |

## Building_1: charger

```json
{
  "buildings": {
    "Building_1": {
      "chargers": {
        "charger_1_1": {
          "type": "citylearn.electric_vehicle_charger.Charger",
          "charger_simulation": "charger_1_1.csv",
          "soc_unit": null,
          "noise_std": 0.0,
          "attributes": {
            "nominal_power": 11.0,
            "max_charging_power": 11.0,
            "min_charging_power": 1.4,
            "max_discharging_power": 7.2,
            "min_discharging_power": 0.0,
            "efficiency": 0.95,
            "charge_efficiency_curve": null,
            "discharge_efficiency_curve": null,
            "phase_connection": null,
            "charger_type": 0
          }
        }
      }
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `type` | `Charger` | required | |
| `charger_simulation` | `charger_1_1.csv` | required | Schedule of the connected and incoming EVs. |
| `soc_unit` | `null` | inferred per column | `"percent"` or `"fraction"` to declare the SOC columns' unit. |
| `noise_std` | `0.0` | `0.0` | Noise, in SOC percentage points, on the requested and arrival SOC. |
| `nominal_power`, `max_charging_power` | 11 kW | `max_charging_power` = `nominal_power` | |
| `min_charging_power` | 1.4 kW | `0` | Requests below it give 0. |
| `max_discharging_power` | 7.2 kW | `0` (no V2G) | Set above 0 for V2G or vehicle-to-building. |
| `min_discharging_power` | `0.0` | `0` | |
| `efficiency` | 0.95 | `1.0` | Used where there is no curve. |
| `charge_efficiency_curve`, `discharge_efficiency_curve` | `null` | none | `[[power fraction, efficiency], ...]`. |
| `phase_connection` | `null` | `L1` | |
| `charger_type` | `0` | none | Label only. |

## Building_1: deferrable appliance and escalators

```json
{
  "buildings": {
    "Building_1": {
      "deferrable_appliances": {
        "deferrable_appliance_1": {
          "type": "citylearn.energy_model.DeferrableAppliance",
          "cycle_profiles_file": "deferrable_appliance_1_cycle_profiles.csv",
          "flexibility_schedule_file": "deferrable_appliance_1_flexibility_schedule.csv",
          "attributes": {"trigger_threshold": 0.5, "nominal_power": 0.0, "efficiency": null}
        }
      },
      "escalators": {}
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `type` | `DeferrableAppliance` | the same | |
| `cycle_profiles_file`, `flexibility_schedule_file` | dataset files | required | Cycles and their windows. |
| `attributes.trigger_threshold` | `0.5` | `0.5` | An action above it starts the next cycle. |
| `attributes.nominal_power` | `0.0` | `0.0` | When above 0, every cycle's peak power must fit under it. |
| `attributes.efficiency` | `null` | drawn, not used | |
| `escalators` | `{}` | `{}` | Escalators need a passenger file and the flat interface; see [Escalators](schema_reference.md#escalators). |

## Building_1: electrical service

```json
{
  "buildings": {
    "Building_1": {
      "electrical_service": {
        "mode": "single_phase",
        "default_split": "balanced",
        "limits": {
          "total": {"import_kw": 17.25, "export_kw": 6.9},
          "per_phase": {
            "L1": {"import_kw": 17.25, "export_kw": 6.9}
          }
        },
        "available_grid_power": null,
        "observations": {
          "headroom": true,
          "headroom_export": true,
          "violation": true,
          "phase_encoding": false,
          "available_grid_power": true
        }
      }
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `mode` | `"single_phase"` | `"single_phase"` | `"three_phase"` adds `L2` and `L3`. |
| `default_split` | `"balanced"` | `"balanced"` | Phase of load without a phase connection. |
| `limits.total.import_kw`, `export_kw` | 17.25 kW, 6.9 kW | no limit | A 25 A single-phase connection with a 6.9 kW export limit. Leave a key out for no limit. |
| `limits.per_phase.L1.import_kw`, `export_kw` | 17.25 kW, 6.9 kW | no limit | |
| `available_grid_power` | `null` | none | A file (or `{filename, column}`) with the import limit per step. |
| `observations.headroom`, `headroom_export`, `violation`, `available_grid_power` | `true` | `true` | Adds `charging_building_headroom_kw`, the export and `L1` headrooms and `charging_constraint_violation_kwh` to the observations. |
| `observations.phase_encoding` | `false` | `false` | One-hot phase of each charger. |

## Building_1: outages, dynamics and occupants

```json
{
  "buildings": {
    "Building_1": {
      "power_outage": {
        "simulate_power_outage": false,
        "stochastic_power_outage": false,
        "stochastic_power_outage_model": {
          "type": "citylearn.power_outage.ReliabilityMetricsPowerOutage",
          "attributes": {"saifi": 1.436, "caidi": 331.2, "start_time_steps": null, "random_seed": null}
        },
        "vehicle_to_building": false
      },
      "dynamics": null,
      "occupant": null,
      "set_point_hold_time_steps": null,
      "set_point_limits": [15.0, 30.0]
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `power_outage.simulate_power_outage` | `false` | `false` | `true` reads the `power_outage` column, or the model below. |
| `power_outage.stochastic_power_outage` | `false` | `false` | `true` draws outages from the model. |
| `power_outage.stochastic_power_outage_model` | `ReliabilityMetricsPowerOutage` with its defaults | `PowerOutage` (each step an outage with probability 0.5) | `saifi` interruptions per year, `caidi` minutes each. |
| `power_outage.vehicle_to_building` | `false` | `false` | `true` lets the connected EV supply the house during an outage. |
| `dynamics`, `occupant` | `null` | none | For dynamics and occupant building types only. |
| `set_point_hold_time_steps` | `null` | `null` | Occupant building types only. |
| `set_point_limits` | `[15.0, 30.0]` | `[15, 30]` | Occupant building types only; physics version 2. |

## Building_4: the short form

`Building_4` shows the same sections written with only the keys that have no default, and the legacy
`charging_constraints` (read only because the building has no `electrical_service`).

```json
{
  "buildings": {
    "Building_4": {
      "include": true,
      "type": "citylearn.building.Building",
      "energy_simulation": "Building_4.csv",
      "weather": "weather.csv",
      "pricing": "pricing.csv",
      "carbon_intensity": "carbon_intensity.csv",
      "electrical_storage": {
        "type": "citylearn.energy_model.Battery",
        "autosize": false,
        "attributes": {"capacity": 6.4, "nominal_power": 5.0}
      },
      "pv": {
        "type": "citylearn.energy_model.PV",
        "autosize": false,
        "attributes": {"nominal_power": 8.0}
      },
      "chargers": {
        "charger_4_1": {
          "type": "citylearn.electric_vehicle_charger.Charger",
          "charger_simulation": "charger_4_1.csv",
          "attributes": {
            "nominal_power": 22.0,
            "max_charging_power": 22.0,
            "min_charging_power": 3.7,
            "max_discharging_power": 22.0,
            "min_discharging_power": 3.7,
            "efficiency": 0.95
          }
        }
      },
      "charging_constraints": {
        "building_limit_kw": null,
        "phases": [{"name": "phase_1", "limit_kw": null, "chargers": ["charger_4_1"]}],
        "expose_observations": true,
        "observations": {"headroom": true, "headroom_export": false, "violation": true, "phase_encoding": false}
      }
    }
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `charging_constraints.building_limit_kw` | `null` | no limit | Limit on the building's total charging power. |
| `charging_constraints.phases` | one phase with `charger_4_1` and no limit | `[]` | `limit_kw` limits the listed chargers together. |
| `charging_constraints.expose_observations` | `true` | `true` | Fallback for `observations.headroom`. |
| `charging_constraints.observations` | `headroom` `true`, `headroom_export` `false`, `violation` `true`, `phase_encoding` `false` | the same | |

## Electric vehicles and EV evaluation

```json
{
  "electric_vehicles_def": {
    "Electric_Vehicle_7": {
      "type": "citylearn.electric_vehicle.ElectricVehicle",
      "include": true,
      "battery": {
        "type": "citylearn.energy_model.Battery",
        "attributes": {
          "capacity": 40.0,
          "nominal_power": 50.0,
          "initial_soc": null,
          "depth_of_discharge": 1.0,
          "loss_coefficient": 0.0,
          "efficiency": null,
          "capacity_loss_coefficient": null,
          "power_efficiency_curve": null,
          "capacity_power_curve": null,
          "discharge_power_curve": null,
          "random_seed": null
        }
      }
    },
    "Electric_Vehicle_8": {
      "type": "citylearn.electric_vehicle.ElectricVehicle",
      "include": true,
      "battery": {
        "type": "citylearn.energy_model.Battery",
        "attributes": {
          "capacity": 40.0,
          "nominal_power": 50.0,
          "initial_soc": null,
          "depth_of_discharge": 1.0,
          "loss_coefficient": 0.0,
          "efficiency": null,
          "capacity_loss_coefficient": null,
          "power_efficiency_curve": null,
          "capacity_power_curve": null,
          "discharge_power_curve": null,
          "random_seed": null
        }
      }
    }
  },
  "ev_departure_within_tolerance": 0.05,
  "ev_departure_service_tolerance": 0.05,
  "business_as_usual_ev_charge_target": "full"
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| (EV ID) | `Electric_Vehicle_7`, `Electric_Vehicle_8` | | Must match the `electric_vehicle_id` text in the charger files. |
| `type` | `ElectricVehicle` | the same | |
| `include` | `true` | `true` | `false` leaves the EV out; chargers then never see it connected. |
| `battery.type` | `Battery` | the same | |
| `battery.attributes.capacity`, `nominal_power` | 40 kWh, 50 kW | required | |
| `battery.attributes.initial_soc` | `null` | drawn in [0, 1] per EV from `random_seed` | |
| `battery.attributes.depth_of_discharge` | `1.0` | `1.0` | |
| `battery.attributes.loss_coefficient` | `0.0` | `0.0` for EVs | |
| other `battery.attributes` | `null` | as for the stationary battery | |
| `ev_departure_within_tolerance`, `ev_departure_service_tolerance` | `0.05` | `0.05` | SOC tolerances of the departure KPIs. The target met test uses 0.005, or the service tolerance if smaller. |
| `business_as_usual_ev_charge_target` | `"full"` | `"full"` | `"requested"`: the BAU stops at the requested departure SOC. |

## Community market

```json
{
  "community_market": {
    "enabled": false,
    "local_price_ratio_to_grid_import": 0.8,
    "settlement_version": 1,
    "grid_export_price": 0.0,
    "tariff_files": {},
    "local_trading_enabled": true,
    "import_member_weights": {},
    "kpis": {"community_local_traded_enabled": true, "community_self_consumption_enabled": true},
    "matching_granularity": "aggregate_building",
    "counterfactual": "grid_only"
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `enabled` | `false` | `false` | `true` settles imports and exports inside the community every step. |
| `local_price_ratio_to_grid_import` | `0.8` | `0.8` | Local price as a fraction of the grid import price. |
| `settlement_version` | `1` | `1` | `2` allows a non-zero `grid_export_price`. |
| `grid_export_price` | `0.0` | `0.0` | EUR/kWh for residual exports. |
| `tariff_files` | `{}` | `{}` | Per-member price files. |
| `local_trading_enabled` | `true` | `true` | `false` keeps the settlement but trades nothing locally. |
| `import_member_weights` | `{}` | every member 1.0 | Priority of importers for local energy. |
| `kpis.*` | `true` | `true` | Report the local-traded and import-share KPIs. |
| `matching_granularity`, `counterfactual` | the only values | the same | |

## Demand response

```json
{
  "demand_response": {
    "enabled": false,
    "requests_file": null,
    "baseline_method": "rolling_pre_event_average",
    "baseline_window_seconds": 3600,
    "allow_overlapping_requests": false,
    "request_purposes": {}
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `enabled` | `false` | `false` | `true` needs `"interface": "entity"` and a `requests_file`. |
| `requests_file` | `null` | none | CSV or Parquet file of DSO/TSO requests. |
| `baseline_method` | `"rolling_pre_event_average"` | the same | The only method. |
| `baseline_window_seconds` | `3600` | `3600` | Window before each request for the baseline. |
| `allow_overlapping_requests` | `false` | `false` | Requests must not overlap. |
| `request_purposes` | `{}` | `{}` | `service`, `stress` or `unspecified` per request ID, for the audit KPIs. |

## Robustness

```json
{
  "robustness": {
    "enabled": false,
    "events_file": null,
    "random_seed": null,
    "missing_replacement_value": -9999.0,
    "modules": {
      "observations": {"enabled": true},
      "forecasts": {"enabled": true},
      "actions": {"enabled": true},
      "assets": {"enabled": true}
    },
    "agent_observation_contract": {"mode": "known_faults", "features": {}}
  }
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `enabled` | `false` | `false` | `true` applies the events of `events_file`. |
| `events_file` | `null` | none | CSV or Parquet file of observation, forecast, action and asset events. |
| `random_seed` | `null` | the root `random_seed` | Seed of the event noise. |
| `missing_replacement_value` | `-9999.0` | `-9999.0` | Value of missing observations. |
| `modules.*.enabled` | `true` | `true` | Turn a module off without editing the events. |
| `agent_observation_contract.mode` | `"known_faults"` | `"known_faults"` | `"hidden_faults"` hides fault labels and masks unlisted entity features. |
| `agent_observation_contract.features` | `{}` | `{}` | Features visible under `hidden_faults`. |

## Outputs and diagnostics

```json
{
  "render_mode": "none",
  "render": false,
  "render_file_format": "csv",
  "render_chunk_size": null,
  "render_session_name": null,
  "export_kpis_on_episode_end": false,
  "evaluation_window": {"enabled": false},
  "district_electrical_service": {"enabled": false, "limits": {"import_kw": null, "export_kw": null}},
  "export_only_final_episode": true,
  "debug_timing": false,
  "check_observation_limits": false,
  "physics_invariant_checks": false,
  "energy_provenance": true,
  "metrics_log_interval": 0
}
```

| Key | Here | Default | Notes and alternatives |
|---|---|---|---|
| `render_mode` | `"none"` | `"none"` | `"during"` or `"end"` to write time series. Wins over the constructor argument. |
| `render` | `false` | follows `render_mode` | Legacy switch; wins over the constructor argument. |
| `render_file_format` | `"csv"` | `"csv"` | `"parquet"` needs `pyarrow`. |
| `render_chunk_size` | `null` | 100000 rows for CSV, 50000 for Parquet | |
| `render_session_name` | `null` | a timestamp | Subfolder of the exports. |
| `export_kpis_on_episode_end` | `false` | follows rendering | `true` writes `exported_kpis.csv` at the end of each episode. |
| `evaluation_window` | `{"enabled": false}` | off | `{"enabled": true, "start": "16:00", "end": "19:00"}` adds the recurring-window KPIs to `evaluate_v2()` and the KPI exports. See [Evaluation window](schema_reference.md#evaluation-window). |
| `district_electrical_service` | disabled | disabled | `{"enabled": true, "limits": {"import_kw": 50.0, "export_kw": 20.0}}` reports the district feeder exceedances in `evaluate_v2()` without curtailing anything. See [District electrical service](schema_reference.md#district-electrical-service). |
| `export_only_final_episode` | `true` | `true` | For planned multi-episode runs. |
| `debug_timing` | `false` | `false` | Timing fields in the step `info`. |
| `check_observation_limits` | `false` | `false` | DEBUG logs for observations outside their bounds. |
| `physics_invariant_checks` | `false` | `false` | Raise on an energy-balance violation. |
| `energy_provenance` | `true` | `true` | `false` is faster and drops the provenance KPIs. |
| `metrics_log_interval` | `0` | `0` | Log a summary line every N steps. |

## Turning features on

| To | Change |
|---|---|
| Train on random one-week episodes | `"episode_time_steps": 169`, `"random_episode_split": true` |
| Reproduce CityLearn 3.6.0 | `"physics_version": 1`, `"baseline_version": 1`, `"random_stream_version": "v1"`, `"episode_split_boundary": "disjoint"` |
| Control both buildings with one agent | `"central_agent": true` |
| Use entity tables | `"interface": "entity"` and the `observation_bundles` you need |
| Settle energy locally and pay exports | `community_market`: `"enabled": true`, `"settlement_version": 2`, `"grid_export_price": 0.05` |
| Limit the grid connection of `Building_1` | `electrical_service.limits.total.import_kw` |
| Allow V2G on `charger_4_1` only | set `max_discharging_power` to `0.0` on `charger_1_1` |
| Simulate realistic outages | `"simulate_power_outage": true`, `"stochastic_power_outage": true` |
| Export time series at the end of each episode | `"render_mode": "end"` |
| Check energy balances every step | `"physics_invariant_checks": true` |
