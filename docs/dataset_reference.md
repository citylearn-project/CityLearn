# Dataset Reference

This page explains how to build simulator-compatible datasets, including CSV, Parquet, real power data in kW, EVs, absolute PV, normalized deferrable appliances and demand-response requests.

Portuguese version: [pt/dataset_reference.md](pt/dataset_reference.md).

## Supported File Formats

| Format | Extensions | Loader | When to use |
|---|---|---|---|
| CSV | `.csv` | `pandas.read_csv` with `skiprows/nrows` for windows | Small/medium datasets and easy inspection. |
| Parquet | `.parquet`, `.pq`, `.parq` | `pyarrow.parquet` batches for windows | Large datasets, 15s data, many assets or full-year runs. |

CSV and Parquet are interchangeable when the schema path is updated and columns, units and types remain equivalent.

## Public datasets and local data

Resolve available names with `DataSet().get_dataset_names()` or use the CLI after
installing its dependencies. Pass a dataset name to `CityLearnEnv` for automatic
download and caching, or pass your own local `schema.json` path. Use
`offline=True` with locally available files to disable network fallbacks.

## Unit Contract

| Data | Expected unit |
|---|---:|
| Load and consumption series | kWh/step |
| PV with `generation_mode="absolute"` | kWh/step |
| PV with `generation_mode="per_kw"` | W/kW |
| BESS and charger power limits | kW |
| EV required/estimated SOC in charger files | percent in the raw file, converted to ratio internally |
| Prices | currency/kWh |
| DR request target power | kW |
| DR request prices and penalties | currency/kWh |
| Carbon intensity | kgCO2/kWh |
| Weather temperature | C |
| Irradiance | W/m2 |

Real power data must be converted before writing energy columns:

```text
kWh_per_step = kW * seconds_per_time_step / 3600
kW = kWh_per_step * 3600 / seconds_per_time_step
```

For 15 seconds:

```text
1 kW during 15s = 1 * 15 / 3600 = 0.0041666667 kWh
```

## `energy_simulation` Columns

| Column | Required | Unit | Meaning |
|---|---:|---:|---|
| `month` | yes | 1-12 | Month. |
| `hour` | yes | 1-24 | Hour. |
| `day_type` | yes | 1-8 | Day of week or special day. |
| `minutes` | recommended sub-hour | 0-59 | Minute. |
| `seconds` | recommended sub-minute | 0-59 | Second. |
| `indoor_dry_bulb_temperature` | yes | C | Indoor temperature. |
| `non_shiftable_load` | yes | kWh/step | Non-flexible load. |
| `dhw_demand` | yes | kWh/step | Domestic hot water demand. |
| `cooling_demand` | yes | kWh/step | Cooling demand. |
| `heating_demand` | yes | kWh/step | Heating demand. |
| `solar_generation` | yes | depends on PV mode | PV input. |
| `daylight_savings_status` | no | 0/1 | DST. |
| `average_unmet_cooling_setpoint_difference` | no | C | Cooling discomfort. |
| `indoor_relative_humidity` | no | percent | Indoor humidity. |
| `occupant_count` | no | people | Occupancy. |
| `indoor_dry_bulb_temperature_cooling_set_point` | no | C | Cooling setpoint. |
| `indoor_dry_bulb_temperature_heating_set_point` | no | C | Heating setpoint. |
| `hvac_mode` | no | enum | 0 off, 1 cooling, 2 heating, 3 auto. |
| `power_outage` | no | 0/1 | Outage flag. |
| `comfort_band` | no | C | Comfort band. |

Cooling and heating demand cannot both be positive in the same timestep.

## Weather, Pricing and Carbon Files

| File | Required columns | Units |
|---|---|---|
| `weather` | `outdoor_dry_bulb_temperature`, `outdoor_relative_humidity`, `diffuse_solar_irradiance`, `direct_solar_irradiance`, plus `*_predicted_1/2/3` | C, percent, W/m2 |
| `pricing` | `electricity_pricing`, `electricity_pricing_predicted_1/2/3` | currency/kWh |
| `carbon_intensity` | `carbon_intensity` | kgCO2/kWh |

## Charger Simulation Columns

| Column | Unit/format | Meaning |
|---|---:|---|
| `electric_vehicle_charger_state` | enum | 1 connected, 2 incoming, 3 away/commuting. |
| `electric_vehicle_id` | string | EV ID. |
| `electric_vehicle_departure_time` | steps | Steps until departure. Internal default `-1`. |
| `electric_vehicle_required_soc_departure` | percent | Required departure SOC. Converted to ratio. |
| `electric_vehicle_estimated_arrival_time` | steps | Steps until arrival. Internal default `-1`. |
| `electric_vehicle_estimated_soc_arrival` | percent | Estimated arrival SOC on the incoming (state 2) rows. Converted to ratio. At connection the EV starts from the latest estimate in the incoming rows of the same EV just before it, usually the last one; an estimate on rows before an away (state 3) gap is not used. |
| `electric_vehicle_current_soc` | percent or ratio | Optional current-SOC telemetry. In the annual REC suite this is a neutral constant-rate boundary-initialization reference, used only when an episode starts inside an occupied session; it does not override SOC during an uninterrupted rollout. |

For sub-hourly datasets, countdown fields must be expressed in timesteps at the dataset resolution. Example: 1 hour at 15s is 240 steps.

## Entity Observation Bundles in Packaged Datasets

The packaged 15-second entity datasets and `citylearn_challenge_2022_phase_all_plus_evs` opt in to all entity observation bundles:

| Bundle | Purpose |
|---|---|
| `entity_core_electrical` | Physical power, energy, SOC and asset capability descriptors. |
| `entity_community_operational` | Community power, headroom and flexible capacity aggregates. |
| `entity_forecasts_existing` | Existing dataset `*_predicted_*` observations. |
| `entity_forecasts_derived` | Compact point forecasts; the annual REC suite uses causal daily persistence for load/PV and publication-aware OMIE prices. |
| `entity_temporal_derived` | Robust calendar and short lag features. |
| `entity_action_feedback` | Requested, limited and applied action feedback with clipping reasons. |
| `entity_demand_response` | Current district demand-response request, baseline and previous delivery/shortfall. |
| `entity_robustness` | Active robustness state and previous-step corruption counters. |

Other schemas keep the default-compatible behavior unless they declare `observation_bundles`.

## Demand Response Request Files

Demand-response datasets set `schema["demand_response"]["enabled"] = true`, point `requests_file` to a CSV or Parquet file, use `interface="entity"` and normally enable `observation_bundles.entity_demand_response`.

| Column | Unit/domain | Meaning |
|---|---:|---|
| `request_id` | string | Unique request ID. |
| `issuer` | `dso`/`tso` | Request issuer. |
| `direction` | `up`/`down` | Load perspective: `up` increases net load, `down` reduces net load. |
| `start_time_step`, `end_time_step` | global timestep | Inclusive activation window. |
| `target_power_kw` | kW | Positive community/district power target. |
| `activation_price_eur_per_kwh` | currency/kWh | Payment for credited delivered energy. |
| `shortfall_penalty_eur_per_kwh` | currency/kWh | Penalty for shortfall energy. |
| `tolerance_power_kw` | kW | Optional tolerance; defaults to `0`. |

The v1 simulator computes a frozen baseline at event start from the previous `baseline_window_seconds`, settles only active request steps, and keeps history sparse instead of writing dense per-timestep arrays.

## Robustness Event Files

Robustness datasets set `schema["robustness"]["enabled"] = true`, point `events_file` to a CSV or Parquet file, and enable only the modules they want to study. Flat and entity interfaces are supported; entity datasets can add `observation_bundles.entity_robustness` for diagnostics.

| Column | Unit/domain | Meaning |
|---|---:|---|
| `event_id` | string | Unique event ID. |
| `module` | enum | `observation`, `forecast`, `action` or `asset`. |
| `target_type` | entity type | `district`, `building`, `storage`, `charger`, `ev`, `pv` or `deferrable_appliance`. |
| `target_id` | id or `*` | Entity id/name or all compatible targets. |
| `target_feature` | feature/action | For assets use `telemetry`, `control` or `both`. |
| `start_time_step`, `end_time_step` | global timestep | Inclusive event window. |
| `mode` | enum | Mode supported by the selected module. |
| `value`, `std`, `min_value`, `max_value`, `replacement_value`, `delay_steps` | optional | Mode parameters. |

## Deferrable Appliances

The official format is sparse: a cycle profile catalog plus a flexibility request schedule. Do not repeat the full `load_profile` at every timestep.

### `cycle_profiles_file`

| Column | Unit | Meaning |
|---|---:|---|
| `profile_id` | string | Profile ID. |
| `duration_steps` | steps | Cycle duration. |
| `total_energy_kwh` | kWh | Sum of the profile. |
| `load_profile` | list of kWh/step | Step energy profile. |

Validation:

| Check | Rule |
|---|---|
| `profile_id` | Non-empty and unique. |
| `duration_steps` | Integer > 0. |
| `load_profile` | Non-empty, finite and non-negative. |
| Sum | `sum(load_profile) == total_energy_kwh` within tolerance. |

### `flexibility_schedule_file`

| Column | Unit | Meaning |
|---|---:|---|
| `cycle_id` | string | Unique request/cycle ID. |
| `profile_id` | string | Reference to the profile catalog. |
| `earliest_start_time_step` | global timestep | First allowed start. |
| `latest_start_time_step` | global timestep | Last allowed start. |
| `deadline_time_step` | global timestep | Completion deadline. |
| `priority` | ratio | Priority 0-1, clipped. |
| `must_run` | bool | Mandatory request flag. |

Validation:

| Check | Rule |
|---|---|
| `cycle_id` | Unique and non-empty. |
| `profile_id` | Must exist in the catalog. |
| Windows | `earliest <= latest`. |
| Deadline | `latest + duration_steps - 1 <= deadline`. |
| Timesteps | Global integer indices >= 0. |

## PV Datasets

| Case | Schema | `solar_generation` column |
|---|---|---|
| Real/measured generation | `"generation_mode": "absolute"` | `kWh/step`. |
| Normalized profile | `"generation_mode": "per_kw"` | `W/kW` per 1 kW installed. |

For real production datasets, `absolute` is the recommended mode.

## 15-Second Datasets

| Topic | Recommendation |
|---|---|
| `seconds_per_time_step` | `15`. |
| Real power data | Convert kW to kWh/step before writing dataset energy columns. |
| Real PV | Write kWh/step and use `generation_mode="absolute"`. |
| EV countdowns | Express `*_departure_time` and `*_arrival_time` in 15s steps. |
| Large files | Prefer Parquet. |
| Pre-training smoke test | Run a short window and call `evaluate_v2()`. |
| Compact dynamic-assets example | `data/datasets/citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet/schema.json` contains 7 days at 15s with charger, PV and BESS add/remove events. |
| Demand-response example | `data/datasets/citylearn_challenge_2022_phase_all_demand_response/schema.json` contains 2022 phase-all buildings without EVs plus district DR requests. |
| Robustness example | `data/datasets/citylearn_challenge_2022_phase_all_robustness/schema.json` contains 2022 phase-all buildings without EVs plus sparse robustness events. |

## Performance and Loader Behavior

| Optimization | Effect |
|---|---|
| Windowed CSV | Uses `skiprows/nrows` to load only the requested window. |
| Windowed Parquet | Reads batches and slices rows. |
| Shared cache | Reuses weather/pricing/carbon when several buildings point to the same file and `noise_std=0`. |
| Parquet | Smaller files, typed reads and better large-dataset behavior. |

## New Dataset Checklist

1. Define `seconds_per_time_step`.
2. Convert measured power to `kWh/step` where the simulator expects energy.
3. Choose PV `absolute` or `per_kw`.
4. Ensure EV schedules use countdowns in dataset timesteps.
5. Write deferrables as catalog plus schedule.
6. For demand response, write a sparse request file and enable entity mode plus `entity_demand_response`.
7. For robustness, write sparse event files and enable only the needed modules.
8. Prefer Parquet for annual or sub-minute datasets.
9. Run a smoke episode and `evaluate_v2()`.
10. Run `audit_physics.py` for new critical datasets.
