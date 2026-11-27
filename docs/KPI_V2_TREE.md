# KPI catalogue

This page lists every KPI name that `evaluate_v2()` emits, grouped by family, with a short
definition. It is generated from `citylearn/misc/kpi_catalogue.yml` by `scripts/docs/kpi_catalogue.py`,
and a test checks that every name the simulator emits is listed here. The equations, the
district aggregation and the undefined-value rules of each family are in the
[KPI reference](kpis_reference.md), which each family links to.

Names read `<level>_<family>_<subfamily>_<metric>[_<variant>]_<unit>`. The level is
`building` or `district`; `MultiCommunityEnv` adds `portfolio` rows built from the district
rows (see [Levels](kpis_reference.md#levels)). In the tables, `{a,b}` stands for each
alternative and `{,_x}` for an optional part; the full names follow each table.
Which rows appear depends on the scenario's assets and services.

| Family | Names |
|---|---:|
| [Cost](#cost) | 24 |
| [Grid energy and load shape](#grid-energy-and-load-shape) | 136 |
| [Emissions](#emissions) | 28 |
| [Solar self-consumption](#solar-self-consumption) | 38 |
| [Community market](#community-market) | 36 |
| [Batteries](#batteries) | 40 |
| [Electrical service and phases](#electrical-service-and-phases) | 22 |
| [Electric vehicles](#electric-vehicles) | 72 |
| [EV departure audit](#ev-departure-audit) | 128 |
| [Flexible appliances](#flexible-appliances) | 48 |
| [Flexible-appliance audit](#flexible-appliance-audit) | 68 |
| [Escalators](#escalators) | 12 |
| [Comfort and resilience](#comfort-and-resilience) | 24 |
| [Thermal-service audit](#thermal-service-audit) | 64 |
| [Equity](#equity) | 5 |
| [Equity audit](#equity-audit) | 8 |
| [Demand response](#demand-response) | 23 |
| [Demand-response audit](#demand-response-audit) | 72 |
| [Robustness](#robustness) | 16 |
| [Energy provenance](#energy-provenance) | 342 |
| [Dynamic topology](#dynamic-topology) | 1 |

## Cost

Electricity cost of each member and of the district over the evaluated episode; the rows appear in every run.

Equations and rules: [Cost](kpis_reference.md#cost).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `cost_{total,daily_average}_{control,baseline,delta}_eur` | building, district | EUR | Electricity cost of the controlled run (`control`), of the conventional counterfactual (`baseline`) and control minus baseline (`delta`), as an episode total or a daily average. |
| `cost_ratio_to_baseline_total_ratio` | building, district | ratio | Signed ratio of the control cost total to the baseline cost total; it stays lower-is-better when the totals are negative. |
| `cost_{total,daily_average}_{business_as_usual,delta_to_business_as_usual}_eur` | building, district | EUR | Electricity cost; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `cost_ratio_to_business_as_usual_total_ratio` | building, district | ratio | Signed ratio of the control cost total to the BAU cost total. |

<details>
<summary>All 24 names</summary>

```text
building_cost_daily_average_baseline_eur
building_cost_daily_average_business_as_usual_eur
building_cost_daily_average_control_eur
building_cost_daily_average_delta_eur
building_cost_daily_average_delta_to_business_as_usual_eur
building_cost_ratio_to_baseline_total_ratio
building_cost_ratio_to_business_as_usual_total_ratio
building_cost_total_baseline_eur
building_cost_total_business_as_usual_eur
building_cost_total_control_eur
building_cost_total_delta_eur
building_cost_total_delta_to_business_as_usual_eur
district_cost_daily_average_baseline_eur
district_cost_daily_average_business_as_usual_eur
district_cost_daily_average_control_eur
district_cost_daily_average_delta_eur
district_cost_daily_average_delta_to_business_as_usual_eur
district_cost_ratio_to_baseline_total_ratio
district_cost_ratio_to_business_as_usual_total_ratio
district_cost_total_baseline_eur
district_cost_total_business_as_usual_eur
district_cost_total_control_eur
district_cost_total_delta_eur
district_cost_total_delta_to_business_as_usual_eur
```

</details>

## Grid energy and load shape

Energy exchanged with the grid by each member and by the district, and the shape of the district load (peaks, ramping, load factor); the rows appear in every run, the shape rows at district level only.

Equations and rules: [Grid energy and load shape](kpis_reference.md#grid-energy-and-load-shape).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `energy_grid_{total,daily_average}_{import,export,net_exchange}_{control,baseline,delta}_kwh` | building, district | kWh | Grid import Σ max(net, 0), export Σ max(−net, 0) and signed net exchange Σ net of the controlled run, of the conventional counterfactual and control minus baseline; the district nets its members at each step. |
| `energy_grid_{total,daily_average}_{import,export,net_exchange}_{business_as_usual,delta_to_business_as_usual}_kwh` | building, district | kWh | Grid import, export and net exchange; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `energy_grid_ratio_to_baseline_{import,export,net_exchange}_total_ratio` | building, district | ratio | Control total over baseline total; signed ratio for net exchange. The district ratio divides the district totals. |
| `energy_grid_ratio_to_baseline_{import,net_exchange}_total_building_mean_ratio` | district | ratio | 3.6.0 definition kept for comparison: the unweighted mean of the building ratios, not a district ratio. |
| `energy_grid_ratio_to_business_as_usual_{import,export,net_exchange}_total_ratio` | building, district | ratio | Control total over BAU total; signed ratio for net exchange. |
| `energy_grid_shape_quality_peak_{daily,all_time}_average_to_baseline_ratio` | district | ratio | Control peak over baseline peak, where a peak is the mean over daily windows (or the single episode window) of the maximum signed net district power. |
| `energy_grid_shape_quality_peak_{daily,all_time}_average_{control,business_as_usual,delta_to_business_as_usual}_kw` | district | kW | Peak of the signed net district power in the controlled run, in the BAU run, and control minus BAU. |
| `energy_grid_shape_quality_peak_{daily,all_time}_average_to_business_as_usual_ratio` | district | ratio | Control peak over BAU peak, on signed net district power. |
| `energy_grid_shape_quality_ramping_average_to_baseline_ratio` | district | ratio | Summed upward ramps of the control district net series over those of the baseline (a ratio of totals, kept from 3.6.0). |
| `energy_grid_shape_quality_ramping_{average,total}_{control,business_as_usual,delta_to_business_as_usual}_kw` | district | kW | Upward ramping of the district net power in the controlled run, in the BAU run, and control minus BAU: `average` per step transition, `total` summed over the episode (3.6.0 value). |
| `energy_grid_shape_quality_ramping_average_to_business_as_usual_ratio` | district | ratio | Control mean upward ramp over BAU mean upward ramp; `ramping_total` has no ratio row. |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average_to_baseline_ratio` | district | ratio | Control load-factor penalty over baseline penalty, on district import power and daily (24 h) or monthly (730 h) windows. |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average_to_baseline_signed_net_ratio` | district | ratio | As the import ratio above, on the signed net series (3.6.0 definition). |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average{,_signed_net}_{control,business_as_usual,delta_to_business_as_usual}_ratio` | district | ratio | Load-factor penalty of the controlled run, of the BAU run, and control minus BAU, on import power or, with `_signed_net`, on signed net power (3.6.0). |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average{,_signed_net}_to_business_as_usual_ratio` | district | ratio | Control load-factor penalty over BAU penalty, on the same series. |
| `energy_grid_feeder_limit_{import,export}_exceedance_energy_total_{control,business_as_usual,delta_to_business_as_usual}_kwh` | district | kWh | Energy of settled district net import or export above the declared `district_electrical_service` feeder limit (excesses up to 1e-5 kW ignored; monitored without curtailment), for the controlled run, the BAU run, and control minus BAU; emitted only when `district_electrical_service.enabled` is true and undefined for an unconfigured direction. |
| `energy_grid_feeder_limit_{import,export}_exceedance_peak_{control,business_as_usual,delta_to_business_as_usual}_kw` | district | kW | Highest per-step settled district import or export power exceedance above the declared `district_electrical_service` feeder limit, for the controlled run, the BAU run, and control minus BAU; emitted only when `district_electrical_service.enabled` is true and undefined for an unconfigured direction. |
| `energy_grid_feeder_limit_{import,export}_exceedance_step_{control,business_as_usual,delta_to_business_as_usual}_count` | district | count | Number of executed steps with settled district import or export exceedance above 1e-9 kWh, for the controlled run, the BAU run, and control minus BAU; emitted only when `district_electrical_service.enabled` is true and undefined for an unconfigured direction. |
| `energy_grid_window_average_power_{control,business_as_usual,delta_to_business_as_usual}_kw` | building, district | kW | Mean signed net grid power inside the recurring local `evaluation_window` for the controlled run, the BAU run, and control minus BAU; emitted only when `evaluation_window.enabled` is true. |

<details>
<summary>All 136 names</summary>

```text
building_energy_grid_daily_average_export_baseline_kwh
building_energy_grid_daily_average_export_business_as_usual_kwh
building_energy_grid_daily_average_export_control_kwh
building_energy_grid_daily_average_export_delta_kwh
building_energy_grid_daily_average_export_delta_to_business_as_usual_kwh
building_energy_grid_daily_average_import_baseline_kwh
building_energy_grid_daily_average_import_business_as_usual_kwh
building_energy_grid_daily_average_import_control_kwh
building_energy_grid_daily_average_import_delta_kwh
building_energy_grid_daily_average_import_delta_to_business_as_usual_kwh
building_energy_grid_daily_average_net_exchange_baseline_kwh
building_energy_grid_daily_average_net_exchange_business_as_usual_kwh
building_energy_grid_daily_average_net_exchange_control_kwh
building_energy_grid_daily_average_net_exchange_delta_kwh
building_energy_grid_daily_average_net_exchange_delta_to_business_as_usual_kwh
building_energy_grid_ratio_to_baseline_export_total_ratio
building_energy_grid_ratio_to_baseline_import_total_ratio
building_energy_grid_ratio_to_baseline_net_exchange_total_ratio
building_energy_grid_ratio_to_business_as_usual_export_total_ratio
building_energy_grid_ratio_to_business_as_usual_import_total_ratio
building_energy_grid_ratio_to_business_as_usual_net_exchange_total_ratio
building_energy_grid_total_export_baseline_kwh
building_energy_grid_total_export_business_as_usual_kwh
building_energy_grid_total_export_control_kwh
building_energy_grid_total_export_delta_kwh
building_energy_grid_total_export_delta_to_business_as_usual_kwh
building_energy_grid_total_import_baseline_kwh
building_energy_grid_total_import_business_as_usual_kwh
building_energy_grid_total_import_control_kwh
building_energy_grid_total_import_delta_kwh
building_energy_grid_total_import_delta_to_business_as_usual_kwh
building_energy_grid_total_net_exchange_baseline_kwh
building_energy_grid_total_net_exchange_business_as_usual_kwh
building_energy_grid_total_net_exchange_control_kwh
building_energy_grid_total_net_exchange_delta_kwh
building_energy_grid_total_net_exchange_delta_to_business_as_usual_kwh
building_energy_grid_window_average_power_business_as_usual_kw
building_energy_grid_window_average_power_control_kw
building_energy_grid_window_average_power_delta_to_business_as_usual_kw
district_energy_grid_daily_average_export_baseline_kwh
district_energy_grid_daily_average_export_business_as_usual_kwh
district_energy_grid_daily_average_export_control_kwh
district_energy_grid_daily_average_export_delta_kwh
district_energy_grid_daily_average_export_delta_to_business_as_usual_kwh
district_energy_grid_daily_average_import_baseline_kwh
district_energy_grid_daily_average_import_business_as_usual_kwh
district_energy_grid_daily_average_import_control_kwh
district_energy_grid_daily_average_import_delta_kwh
district_energy_grid_daily_average_import_delta_to_business_as_usual_kwh
district_energy_grid_daily_average_net_exchange_baseline_kwh
district_energy_grid_daily_average_net_exchange_business_as_usual_kwh
district_energy_grid_daily_average_net_exchange_control_kwh
district_energy_grid_daily_average_net_exchange_delta_kwh
district_energy_grid_daily_average_net_exchange_delta_to_business_as_usual_kwh
district_energy_grid_feeder_limit_export_exceedance_energy_total_business_as_usual_kwh
district_energy_grid_feeder_limit_export_exceedance_energy_total_control_kwh
district_energy_grid_feeder_limit_export_exceedance_energy_total_delta_to_business_as_usual_kwh
district_energy_grid_feeder_limit_export_exceedance_peak_business_as_usual_kw
district_energy_grid_feeder_limit_export_exceedance_peak_control_kw
district_energy_grid_feeder_limit_export_exceedance_peak_delta_to_business_as_usual_kw
district_energy_grid_feeder_limit_export_exceedance_step_business_as_usual_count
district_energy_grid_feeder_limit_export_exceedance_step_control_count
district_energy_grid_feeder_limit_export_exceedance_step_delta_to_business_as_usual_count
district_energy_grid_feeder_limit_import_exceedance_energy_total_business_as_usual_kwh
district_energy_grid_feeder_limit_import_exceedance_energy_total_control_kwh
district_energy_grid_feeder_limit_import_exceedance_energy_total_delta_to_business_as_usual_kwh
district_energy_grid_feeder_limit_import_exceedance_peak_business_as_usual_kw
district_energy_grid_feeder_limit_import_exceedance_peak_control_kw
district_energy_grid_feeder_limit_import_exceedance_peak_delta_to_business_as_usual_kw
district_energy_grid_feeder_limit_import_exceedance_step_business_as_usual_count
district_energy_grid_feeder_limit_import_exceedance_step_control_count
district_energy_grid_feeder_limit_import_exceedance_step_delta_to_business_as_usual_count
district_energy_grid_ratio_to_baseline_export_total_ratio
district_energy_grid_ratio_to_baseline_import_total_building_mean_ratio
district_energy_grid_ratio_to_baseline_import_total_ratio
district_energy_grid_ratio_to_baseline_net_exchange_total_building_mean_ratio
district_energy_grid_ratio_to_baseline_net_exchange_total_ratio
district_energy_grid_ratio_to_business_as_usual_export_total_ratio
district_energy_grid_ratio_to_business_as_usual_import_total_ratio
district_energy_grid_ratio_to_business_as_usual_net_exchange_total_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_baseline_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_baseline_signed_net_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_to_baseline_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_to_baseline_signed_net_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_peak_all_time_average_business_as_usual_kw
district_energy_grid_shape_quality_peak_all_time_average_control_kw
district_energy_grid_shape_quality_peak_all_time_average_delta_to_business_as_usual_kw
district_energy_grid_shape_quality_peak_all_time_average_to_baseline_ratio
district_energy_grid_shape_quality_peak_all_time_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_peak_daily_average_business_as_usual_kw
district_energy_grid_shape_quality_peak_daily_average_control_kw
district_energy_grid_shape_quality_peak_daily_average_delta_to_business_as_usual_kw
district_energy_grid_shape_quality_peak_daily_average_to_baseline_ratio
district_energy_grid_shape_quality_peak_daily_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_ramping_average_business_as_usual_kw
district_energy_grid_shape_quality_ramping_average_control_kw
district_energy_grid_shape_quality_ramping_average_delta_to_business_as_usual_kw
district_energy_grid_shape_quality_ramping_average_to_baseline_ratio
district_energy_grid_shape_quality_ramping_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_ramping_total_business_as_usual_kw
district_energy_grid_shape_quality_ramping_total_control_kw
district_energy_grid_shape_quality_ramping_total_delta_to_business_as_usual_kw
district_energy_grid_total_export_baseline_kwh
district_energy_grid_total_export_business_as_usual_kwh
district_energy_grid_total_export_control_kwh
district_energy_grid_total_export_delta_kwh
district_energy_grid_total_export_delta_to_business_as_usual_kwh
district_energy_grid_total_import_baseline_kwh
district_energy_grid_total_import_business_as_usual_kwh
district_energy_grid_total_import_control_kwh
district_energy_grid_total_import_delta_kwh
district_energy_grid_total_import_delta_to_business_as_usual_kwh
district_energy_grid_total_net_exchange_baseline_kwh
district_energy_grid_total_net_exchange_business_as_usual_kwh
district_energy_grid_total_net_exchange_control_kwh
district_energy_grid_total_net_exchange_delta_kwh
district_energy_grid_total_net_exchange_delta_to_business_as_usual_kwh
district_energy_grid_window_average_power_business_as_usual_kw
district_energy_grid_window_average_power_control_kw
district_energy_grid_window_average_power_delta_to_business_as_usual_kw
```

</details>

## Emissions

Carbon emissions of the electricity imported from the grid by each member and by the district; the rows appear in every run.

Equations and rules: [Emissions](kpis_reference.md#emissions).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `emissions_{total,daily_average}_{control,baseline,delta}_kgco2` | building, district | kgCO2 | Emissions of grid import for the controlled run, the conventional counterfactual and control minus baseline; the district value is that of the netted district import, not the sum of the buildings. |
| `emissions_total_{control,baseline,business_as_usual}_member_sum_kgco2` | district | kgCO2 | 3.6.0 district definition kept for comparison: the sum of the members' own emissions in the control, baseline or BAU run. |
| `emissions_ratio_to_baseline_total_ratio` | building, district | ratio | Control emissions total over baseline emissions total; the district ratio divides the netted district totals. |
| `emissions_ratio_to_baseline_total_building_mean_ratio` | district | ratio | 3.6.0 definition kept for comparison: the unweighted mean of the building ratios. |
| `emissions_{total,daily_average}_{business_as_usual,delta_to_business_as_usual}_kgco2` | building, district | kgCO2 | Emissions of grid import; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `emissions_ratio_to_business_as_usual_total_ratio` | building, district | ratio | Control emissions total over BAU emissions total. |

<details>
<summary>All 28 names</summary>

```text
building_emissions_daily_average_baseline_kgco2
building_emissions_daily_average_business_as_usual_kgco2
building_emissions_daily_average_control_kgco2
building_emissions_daily_average_delta_kgco2
building_emissions_daily_average_delta_to_business_as_usual_kgco2
building_emissions_ratio_to_baseline_total_ratio
building_emissions_ratio_to_business_as_usual_total_ratio
building_emissions_total_baseline_kgco2
building_emissions_total_business_as_usual_kgco2
building_emissions_total_control_kgco2
building_emissions_total_delta_kgco2
building_emissions_total_delta_to_business_as_usual_kgco2
district_emissions_daily_average_baseline_kgco2
district_emissions_daily_average_business_as_usual_kgco2
district_emissions_daily_average_control_kgco2
district_emissions_daily_average_delta_kgco2
district_emissions_daily_average_delta_to_business_as_usual_kgco2
district_emissions_ratio_to_baseline_total_building_mean_ratio
district_emissions_ratio_to_baseline_total_ratio
district_emissions_ratio_to_business_as_usual_total_ratio
district_emissions_total_baseline_kgco2
district_emissions_total_baseline_member_sum_kgco2
district_emissions_total_business_as_usual_kgco2
district_emissions_total_business_as_usual_member_sum_kgco2
district_emissions_total_control_kgco2
district_emissions_total_control_member_sum_kgco2
district_emissions_total_delta_kgco2
district_emissions_total_delta_to_business_as_usual_kgco2
```

</details>

## Solar self-consumption

PV generation and how much of it is used inside each member or the district rather than exported or curtailed; the rows appear in every run and are zero or undefined without PV.

Equations and rules: [Solar self-consumption](kpis_reference.md#solar-self-consumption).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `solar_self_consumption_{total,daily_average}_{generation,export}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Available PV generation and PV-backed export to the grid, as a total or daily average; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `solar_self_consumption_total_curtailment_kwh` | building, district | kWh | PV energy that could not be used while the member was islanded by a power outage; zero outside outages. No BAU row. |
| `solar_self_consumption_ratio_self_consumption{,_business_as_usual,_delta_to_business_as_usual}_ratio` | building, district | ratio | Share of PV generation used locally, (generation − export − curtailment) / generation, undefined without generation; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `solar_self_consumption_ratio_to_business_as_usual_{generation_total,export_total,self_consumption}_ratio` | building, district | ratio | Control value over BAU value of total generation, total export or the self-consumption ratio. |

<details>
<summary>All 38 names</summary>

```text
building_solar_self_consumption_daily_average_export_business_as_usual_kwh
building_solar_self_consumption_daily_average_export_delta_to_business_as_usual_kwh
building_solar_self_consumption_daily_average_export_kwh
building_solar_self_consumption_daily_average_generation_business_as_usual_kwh
building_solar_self_consumption_daily_average_generation_delta_to_business_as_usual_kwh
building_solar_self_consumption_daily_average_generation_kwh
building_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio
building_solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio
building_solar_self_consumption_ratio_self_consumption_ratio
building_solar_self_consumption_ratio_to_business_as_usual_export_total_ratio
building_solar_self_consumption_ratio_to_business_as_usual_generation_total_ratio
building_solar_self_consumption_ratio_to_business_as_usual_self_consumption_ratio
building_solar_self_consumption_total_curtailment_kwh
building_solar_self_consumption_total_export_business_as_usual_kwh
building_solar_self_consumption_total_export_delta_to_business_as_usual_kwh
building_solar_self_consumption_total_export_kwh
building_solar_self_consumption_total_generation_business_as_usual_kwh
building_solar_self_consumption_total_generation_delta_to_business_as_usual_kwh
building_solar_self_consumption_total_generation_kwh
district_solar_self_consumption_daily_average_export_business_as_usual_kwh
district_solar_self_consumption_daily_average_export_delta_to_business_as_usual_kwh
district_solar_self_consumption_daily_average_export_kwh
district_solar_self_consumption_daily_average_generation_business_as_usual_kwh
district_solar_self_consumption_daily_average_generation_delta_to_business_as_usual_kwh
district_solar_self_consumption_daily_average_generation_kwh
district_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio
district_solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio
district_solar_self_consumption_ratio_self_consumption_ratio
district_solar_self_consumption_ratio_to_business_as_usual_export_total_ratio
district_solar_self_consumption_ratio_to_business_as_usual_generation_total_ratio
district_solar_self_consumption_ratio_to_business_as_usual_self_consumption_ratio
district_solar_self_consumption_total_curtailment_kwh
district_solar_self_consumption_total_export_business_as_usual_kwh
district_solar_self_consumption_total_export_delta_to_business_as_usual_kwh
district_solar_self_consumption_total_export_kwh
district_solar_self_consumption_total_generation_business_as_usual_kwh
district_solar_self_consumption_total_generation_delta_to_business_as_usual_kwh
district_solar_self_consumption_total_generation_kwh
```

</details>

## Community market

Local energy trading between the members of a community and its settlement. The rows appear in every run (zero, or undefined shares, when `community_market.enabled` is false), except `local_traded` and `import_share`, which need the market and their KPI switches.

Equations and rules: [Community market](kpis_reference.md#community-market).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `energy_grid_community_market_local_{import,export}_{total,daily_average}_kwh` | building, district | kWh | Energy bought from (import) or sold to (export) other members through local trading, summed over the executed steps; daily averages as in the shared rules. |
| `energy_grid_community_market_grid_{import,export}_after_local_{total,daily_average}_kwh` | building, district | kWh | Each member's grid import still needed, or surplus still exported to the grid, after local trading, summed over members without further netting; daily averages as in the shared rules. |
| `energy_grid_community_market_local_traded_{total,daily_average}_kwh` | district | kWh | Energy traded locally; equal to the district local import. Emitted only when the market is enabled and `community_market.kpis.community_local_traded_enabled` is true. |
| `cost_community_market_settled_{total,daily_average}_eur` | building, district | EUR | Cost after local settlement: grid import and local purchases minus local sales and grid export revenue; can be negative. |
| `cost_community_market_counterfactual_{total,daily_average}_eur` | building, district | EUR | Grid-only cost of the same controlled flows without local trading, `import · grid import price − export · grid export price`; not the `baseline` evaluation condition. |
| `cost_community_market_savings_{total,daily_average}_eur` | building, district | EUR | Counterfactual cost minus settled cost; positive when local trading lowered the cost. |
| `cost_community_market_operator_balance_total_eur` | district | EUR | Money the market keeps (positive) or pays (negative): importers' local payments minus exporters' local revenue. It is zero when all members share one local price at each step. |
| `solar_self_consumption_community_market_import_share_ratio` | district | ratio | Canonical local share of demand: `local import / (local import + grid import after local)`, the share of the members' gross import covered by local trading. Emitted only when the market is enabled and `community_market.kpis.community_self_consumption_enabled` is true. |
| `solar_self_consumption_community_market_local_share_of_demand_ratio` | building, district | ratio | Deprecated alias, kept for compatibility: same formula as `import_share` (emitted in every run, undefined only when the denominator is 0). At building level it is the only share of demand. |
| `solar_self_consumption_community_market_local_share_of_export_ratio` | building, district | ratio | `local export / (local export + grid export after local)`: the share of the members' gross export sold to other members. |

<details>
<summary>All 36 names</summary>

```text
building_cost_community_market_counterfactual_daily_average_eur
building_cost_community_market_counterfactual_total_eur
building_cost_community_market_savings_daily_average_eur
building_cost_community_market_savings_total_eur
building_cost_community_market_settled_daily_average_eur
building_cost_community_market_settled_total_eur
building_energy_grid_community_market_grid_export_after_local_daily_average_kwh
building_energy_grid_community_market_grid_export_after_local_total_kwh
building_energy_grid_community_market_grid_import_after_local_daily_average_kwh
building_energy_grid_community_market_grid_import_after_local_total_kwh
building_energy_grid_community_market_local_export_daily_average_kwh
building_energy_grid_community_market_local_export_total_kwh
building_energy_grid_community_market_local_import_daily_average_kwh
building_energy_grid_community_market_local_import_total_kwh
building_solar_self_consumption_community_market_local_share_of_demand_ratio
building_solar_self_consumption_community_market_local_share_of_export_ratio
district_cost_community_market_counterfactual_daily_average_eur
district_cost_community_market_counterfactual_total_eur
district_cost_community_market_operator_balance_total_eur
district_cost_community_market_savings_daily_average_eur
district_cost_community_market_savings_total_eur
district_cost_community_market_settled_daily_average_eur
district_cost_community_market_settled_total_eur
district_energy_grid_community_market_grid_export_after_local_daily_average_kwh
district_energy_grid_community_market_grid_export_after_local_total_kwh
district_energy_grid_community_market_grid_import_after_local_daily_average_kwh
district_energy_grid_community_market_grid_import_after_local_total_kwh
district_energy_grid_community_market_local_export_daily_average_kwh
district_energy_grid_community_market_local_export_total_kwh
district_energy_grid_community_market_local_import_daily_average_kwh
district_energy_grid_community_market_local_import_total_kwh
district_energy_grid_community_market_local_traded_daily_average_kwh
district_energy_grid_community_market_local_traded_total_kwh
district_solar_self_consumption_community_market_import_share_ratio
district_solar_self_consumption_community_market_local_share_of_demand_ratio
district_solar_self_consumption_community_market_local_share_of_export_ratio
```

</details>

## Batteries

Activity and wear of the stationary batteries; the rows appear in every run, with zero energy and undefined cycles and fade for members without a battery.

Equations and rules: [Batteries](kpis_reference.md#batteries).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `battery_total_{charge,discharge,throughput}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energy charged into and discharged from the batteries at their terminals, and throughput = charge + discharge; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `battery_health_equivalent_full_cycles{,_business_as_usual,_delta_to_business_as_usual}_count` | building, district | cycles | Equivalent full cycles, throughput / (2 · nominal capacity), pooled over capacity at district and portfolio levels. `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `battery_health_capacity_fade{,_business_as_usual,_delta_to_business_as_usual}_ratio` | building, district | ratio | Fraction of nominal capacity lost to degradation, (capacity − degraded capacity) / capacity, clipped to [0, 1]; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `battery_ratio_to_business_as_usual_{charge,discharge,throughput,equivalent_full_cycles,capacity_fade}_ratio` | building, district | ratio | Control value over BAU value of charge, discharge, throughput, equivalent full cycles or capacity fade. |

<details>
<summary>All 40 names</summary>

```text
building_battery_health_capacity_fade_business_as_usual_ratio
building_battery_health_capacity_fade_delta_to_business_as_usual_ratio
building_battery_health_capacity_fade_ratio
building_battery_health_equivalent_full_cycles_business_as_usual_count
building_battery_health_equivalent_full_cycles_count
building_battery_health_equivalent_full_cycles_delta_to_business_as_usual_count
building_battery_ratio_to_business_as_usual_capacity_fade_ratio
building_battery_ratio_to_business_as_usual_charge_ratio
building_battery_ratio_to_business_as_usual_discharge_ratio
building_battery_ratio_to_business_as_usual_equivalent_full_cycles_ratio
building_battery_ratio_to_business_as_usual_throughput_ratio
building_battery_total_charge_business_as_usual_kwh
building_battery_total_charge_delta_to_business_as_usual_kwh
building_battery_total_charge_kwh
building_battery_total_discharge_business_as_usual_kwh
building_battery_total_discharge_delta_to_business_as_usual_kwh
building_battery_total_discharge_kwh
building_battery_total_throughput_business_as_usual_kwh
building_battery_total_throughput_delta_to_business_as_usual_kwh
building_battery_total_throughput_kwh
district_battery_health_capacity_fade_business_as_usual_ratio
district_battery_health_capacity_fade_delta_to_business_as_usual_ratio
district_battery_health_capacity_fade_ratio
district_battery_health_equivalent_full_cycles_business_as_usual_count
district_battery_health_equivalent_full_cycles_count
district_battery_health_equivalent_full_cycles_delta_to_business_as_usual_count
district_battery_ratio_to_business_as_usual_capacity_fade_ratio
district_battery_ratio_to_business_as_usual_charge_ratio
district_battery_ratio_to_business_as_usual_discharge_ratio
district_battery_ratio_to_business_as_usual_equivalent_full_cycles_ratio
district_battery_ratio_to_business_as_usual_throughput_ratio
district_battery_total_charge_business_as_usual_kwh
district_battery_total_charge_delta_to_business_as_usual_kwh
district_battery_total_charge_kwh
district_battery_total_discharge_business_as_usual_kwh
district_battery_total_discharge_delta_to_business_as_usual_kwh
district_battery_total_discharge_kwh
district_battery_total_throughput_business_as_usual_kwh
district_battery_total_throughput_delta_to_business_as_usual_kwh
district_battery_total_throughput_kwh
```

</details>

## Electrical service and phases

Compliance with the declared total and per-phase power limits of the electrical service, and the balance and peaks of the phases; the values are zero or undefined unless the schema configures an electrical service.

Equations and rules: [Electrical service and phases](kpis_reference.md#electrical-service-and-phases).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `electrical_service_phase_violations_energy_total_kwh` | building, district | kWh | Energy of the applied power above the declared total and per-phase import and export limits, after constraint handling; excesses up to 1e-5 kW are ignored. |
| `electrical_service_phase_violations_event_count` | building, district | count | Number of time steps with a violation above 1e-9 kWh, summed over buildings at district level. |
| `electrical_service_phase_requested_pressure_energy_total_kwh` | building, district | kWh | Energy by which the controller's request, before projection onto the limits, would have exceeded them; it is not an applied violation. |
| `electrical_service_phase_requested_pressure_event_count` | building, district | count | Number of time steps with requested pressure above 1e-9 kWh, summed over buildings at district level. |
| `electrical_service_phase_imbalance_phase_average_ratio` | building, district | ratio | Mean over time steps of (max \|P\| − min \|P\|) / mean \|P\| over the three phases, 0 when mean \|P\| ≤ 1e-9 kW; three-phase buildings only, and the district value is the mean over all building-steps. |
| `electrical_service_phase_phase_peaks_{import,export}_peak_{l1,l2,l3}_kw` | building, district | kW | Highest import or export power on each phase; the district value is the peak of the summed phase power of its members. |

<details>
<summary>All 22 names</summary>

```text
building_electrical_service_phase_imbalance_phase_average_ratio
building_electrical_service_phase_phase_peaks_export_peak_l1_kw
building_electrical_service_phase_phase_peaks_export_peak_l2_kw
building_electrical_service_phase_phase_peaks_export_peak_l3_kw
building_electrical_service_phase_phase_peaks_import_peak_l1_kw
building_electrical_service_phase_phase_peaks_import_peak_l2_kw
building_electrical_service_phase_phase_peaks_import_peak_l3_kw
building_electrical_service_phase_requested_pressure_energy_total_kwh
building_electrical_service_phase_requested_pressure_event_count
building_electrical_service_phase_violations_energy_total_kwh
building_electrical_service_phase_violations_event_count
district_electrical_service_phase_imbalance_phase_average_ratio
district_electrical_service_phase_phase_peaks_export_peak_l1_kw
district_electrical_service_phase_phase_peaks_export_peak_l2_kw
district_electrical_service_phase_phase_peaks_export_peak_l3_kw
district_electrical_service_phase_phase_peaks_import_peak_l1_kw
district_electrical_service_phase_phase_peaks_import_peak_l2_kw
district_electrical_service_phase_phase_peaks_import_peak_l3_kw
district_electrical_service_phase_requested_pressure_energy_total_kwh
district_electrical_service_phase_requested_pressure_event_count
district_electrical_service_phase_violations_energy_total_kwh
district_electrical_service_phase_violations_event_count
```

</details>

## Electric vehicles

Departure service, charging and V2G energy of electric vehicles at the members' chargers, and opt-in EV battery health and wear (`evaluate_v2(include_battery_health_audit=True)`). Every member emits the departure and energy rows; without chargers, counts and energies are 0 and rates are undefined.

Equations and rules: [Electric vehicles](kpis_reference.md#electric-vehicles).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `ev_events_departure_count` | building, district | count | Departures with a connected EV and battery, a valid target SOC and a finite departure SOC; the denominator of the `ev_performance` rates and means. |
| `ev_events_departure_{met,min_acceptable,within_tolerance}_count` | building, district | count | Counted departures whose SOC met the target, the minimum acceptable SOC (target minus the service tolerance) or the symmetric tolerance band around the target. |
| `ev_events_departure_{target,min_acceptable,within_tolerance}_{feasible,infeasible}_count` | building, district | count | Counted departures whose threshold was or was not reachable by charging at maximum power during the connection; legacy rule, in which missing data counts as feasible, so feasible + infeasible equals the departure count. |
| `ev_performance_departure_{success,min_acceptable,within_tolerance}_ratio` | building, district | ratio | Share of counted departures that met the target, the minimum acceptable SOC or the tolerance band; undefined without departures. |
| `ev_performance_departure_{success,min_acceptable,within_tolerance}_feasible_ratio` | building, district | ratio | The same share over the departures feasible for that threshold under the legacy rule; undefined when none is feasible. |
| `ev_performance_departure_{soc_deficit,shortfall_beyond_tolerance,soc_surplus,soc_absolute_error}_mean_ratio` | building, district | ratio | Mean over counted departures, in SOC fraction, of max(target − SOC, 0), max(target − tolerance − SOC, 0), max(SOC − target, 0) or \|SOC − target\|; undefined without departures. |
| `ev_performance_departure_tolerance_ratio` | building, district | ratio | Configuration echo: the `ev_departure_service_tolerance` setting (default 0.05), not a measurement. |
| `ev_total_charge{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Gross AC energy drawn by the chargers to charge EVs, including charger losses; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `ev_total_v2g_export{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Gross AC energy delivered by the chargers from EV discharge, after charger losses; not grid export. `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `ev_ratio_to_business_as_usual_{charge,v2g_export}_total_ratio` | building, district | ratio | Control over BAU charge or V2G total, as in the shared rules; because the BAU never uses V2G, the V2G ratio is undefined whenever the controller discharges. |
| `ev_energy_accounting_connected_soc_gain_kwh` | building, district | kWh | Sum over counted departures of max(departure SOC − arrival SOC, 0) times the nominal battery capacity. |
| `ev_energy_accounting_shortfall_kwh` | building, district | kWh | Per member, max(SOC gain − charge total, 0): SOC gain not explained by metered charging; the district value is the sum of the member values. |
| `ev_window_net_exchange_control_kwh` | building, district | kWh | Signed net AC energy across EV chargers inside the recurring local `evaluation_window` (positive for charging draw, negative for V2X delivery); emitted only when `evaluation_window.enabled` is true. |
| `ev_battery_health_terminal_soh_ratio` | building, district | ratio | Opt-in capacity-weighted terminal EV battery state of health in [0, 1] (`include_battery_health_audit=True`). At building level, read at the end of each connected EV's last realized connection, including wear received at other buildings, so building SOH can be below 1 − ev_battery_health_capacity_fade_ratio; at district and portfolio levels, pooled over unique eligible fleet EVs by nominal capacity (equal to 1 − fade ratio); undefined when nominal capacity ≤ 0. |
| `ev_battery_health_capacity_fade_kwh` | building, district | kWh | Opt-in cumulative EV battery capacity lost to degradation in [kWh] (`include_battery_health_audit=True`), attributed to executed transfers at the member's chargers at building level and summed over unique eligible fleet EVs at district and portfolio levels. |
| `ev_battery_health_capacity_fade_ratio` | building, district | ratio | Opt-in fraction of nominal EV battery capacity lost to degradation in [0, 1] (`include_battery_health_audit=True`), from executed transfers over realized connected EV capacity at building level and pooled over unique eligible fleet EV nominal capacity at district and portfolio levels; undefined when nominal capacity ≤ 0. |
| `ev_battery_health_equivalent_full_cycles_count` | building, district | cycles | Opt-in equivalent full cycles of EV batteries from accepted gross battery-terminal throughput over (2 · nominal capacity) (`include_battery_health_audit=True`), attributed to executed transfers over realized connected EV capacity at building level and pooled over unique eligible fleet EV nominal capacity at district and portfolio levels; undefined when nominal capacity ≤ 0 (whereas `Battery.equivalent_full_cycles` returns `0.0`). |

<details>
<summary>All 72 names</summary>

```text
building_ev_battery_health_capacity_fade_kwh
building_ev_battery_health_capacity_fade_ratio
building_ev_battery_health_equivalent_full_cycles_count
building_ev_battery_health_terminal_soh_ratio
building_ev_energy_accounting_connected_soc_gain_kwh
building_ev_energy_accounting_shortfall_kwh
building_ev_events_departure_count
building_ev_events_departure_met_count
building_ev_events_departure_min_acceptable_count
building_ev_events_departure_min_acceptable_feasible_count
building_ev_events_departure_min_acceptable_infeasible_count
building_ev_events_departure_target_feasible_count
building_ev_events_departure_target_infeasible_count
building_ev_events_departure_within_tolerance_count
building_ev_events_departure_within_tolerance_feasible_count
building_ev_events_departure_within_tolerance_infeasible_count
building_ev_performance_departure_min_acceptable_feasible_ratio
building_ev_performance_departure_min_acceptable_ratio
building_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio
building_ev_performance_departure_soc_absolute_error_mean_ratio
building_ev_performance_departure_soc_deficit_mean_ratio
building_ev_performance_departure_soc_surplus_mean_ratio
building_ev_performance_departure_success_feasible_ratio
building_ev_performance_departure_success_ratio
building_ev_performance_departure_tolerance_ratio
building_ev_performance_departure_within_tolerance_feasible_ratio
building_ev_performance_departure_within_tolerance_ratio
building_ev_ratio_to_business_as_usual_charge_total_ratio
building_ev_ratio_to_business_as_usual_v2g_export_total_ratio
building_ev_total_charge_business_as_usual_kwh
building_ev_total_charge_delta_to_business_as_usual_kwh
building_ev_total_charge_kwh
building_ev_total_v2g_export_business_as_usual_kwh
building_ev_total_v2g_export_delta_to_business_as_usual_kwh
building_ev_total_v2g_export_kwh
building_ev_window_net_exchange_control_kwh
district_ev_battery_health_capacity_fade_kwh
district_ev_battery_health_capacity_fade_ratio
district_ev_battery_health_equivalent_full_cycles_count
district_ev_battery_health_terminal_soh_ratio
district_ev_energy_accounting_connected_soc_gain_kwh
district_ev_energy_accounting_shortfall_kwh
district_ev_events_departure_count
district_ev_events_departure_met_count
district_ev_events_departure_min_acceptable_count
district_ev_events_departure_min_acceptable_feasible_count
district_ev_events_departure_min_acceptable_infeasible_count
district_ev_events_departure_target_feasible_count
district_ev_events_departure_target_infeasible_count
district_ev_events_departure_within_tolerance_count
district_ev_events_departure_within_tolerance_feasible_count
district_ev_events_departure_within_tolerance_infeasible_count
district_ev_performance_departure_min_acceptable_feasible_ratio
district_ev_performance_departure_min_acceptable_ratio
district_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio
district_ev_performance_departure_soc_absolute_error_mean_ratio
district_ev_performance_departure_soc_deficit_mean_ratio
district_ev_performance_departure_soc_surplus_mean_ratio
district_ev_performance_departure_success_feasible_ratio
district_ev_performance_departure_success_ratio
district_ev_performance_departure_tolerance_ratio
district_ev_performance_departure_within_tolerance_feasible_ratio
district_ev_performance_departure_within_tolerance_ratio
district_ev_ratio_to_business_as_usual_charge_total_ratio
district_ev_ratio_to_business_as_usual_v2g_export_total_ratio
district_ev_total_charge_business_as_usual_kwh
district_ev_total_charge_delta_to_business_as_usual_kwh
district_ev_total_charge_kwh
district_ev_total_v2g_export_business_as_usual_kwh
district_ev_total_v2g_export_delta_to_business_as_usual_kwh
district_ev_total_v2g_export_kwh
district_ev_window_net_exchange_control_kwh
```

</details>

## EV departure audit

Audited EV departure service, with an explicit population, a three-way feasibility status and the reason for each unknown case. Every member emits these rows.

Equations and rules: [EV departure audit](kpis_reference.md#ev-departure-audit).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `ev_departure_audit_departures_count` | building, district | count | Every detected departure at a charger active at that step, whether or not its EV, target or SOC is known. |
| `ev_departure_audit_service_{observed,unknown}_count` | building, district | count | Departures whose service was observed (a valid target and a departure SOC in [0, 1]) or not; the two sum to the departure count. |
| `ev_departure_audit_service_coverage_ratio` | building, district | ratio | Observed departures over all departures; undefined without departures. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_{feasible,infeasible,unknown}_count` | building, district | count | Departures whose threshold was reachable, not reachable, or could not be judged by the audit replay; the three sum to the departure count. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_unknown_{missing_target,missing_ev,missing_battery,invalid_capacity,invalid_charger_power,invalid_charger_efficiency,invalid_time_step,missing_arrival_soc,unsupported_battery_model,invalid_battery_parameters,outage_supply_not_replayed}_count` | building, district | count | Unknown departures by their first applicable reason; the reasons sum to the threshold's unknown count. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_met_count` | building, district | count | Observed departures that met the threshold, whatever their feasibility. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_feasible_service_{observed,met}_count` | building, district | count | Feasible departures whose service was observed, and those of them that met the threshold. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_coverage_ratio` | building, district | ratio | (Feasible + infeasible) over all departures: the share whose feasibility is known; undefined without departures. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_observed_ratio` | building, district | ratio | Departures that met the threshold over observed departures, feasible or not; undefined without observed departures. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_feasible_ratio` | building, district | ratio | Feasible observed departures that met the threshold over feasible observed departures; the canonical controller-comparison ratio, undefined when the denominator is 0. |

<details>
<summary>All 128 names</summary>

```text
building_ev_departure_audit_departures_count
building_ev_departure_audit_min_acceptable_coverage_ratio
building_ev_departure_audit_min_acceptable_feasible_count
building_ev_departure_audit_min_acceptable_feasible_service_met_count
building_ev_departure_audit_min_acceptable_feasible_service_observed_count
building_ev_departure_audit_min_acceptable_infeasible_count
building_ev_departure_audit_min_acceptable_service_feasible_ratio
building_ev_departure_audit_min_acceptable_service_met_count
building_ev_departure_audit_min_acceptable_service_observed_ratio
building_ev_departure_audit_min_acceptable_unknown_count
building_ev_departure_audit_min_acceptable_unknown_invalid_battery_parameters_count
building_ev_departure_audit_min_acceptable_unknown_invalid_capacity_count
building_ev_departure_audit_min_acceptable_unknown_invalid_charger_efficiency_count
building_ev_departure_audit_min_acceptable_unknown_invalid_charger_power_count
building_ev_departure_audit_min_acceptable_unknown_invalid_time_step_count
building_ev_departure_audit_min_acceptable_unknown_missing_arrival_soc_count
building_ev_departure_audit_min_acceptable_unknown_missing_battery_count
building_ev_departure_audit_min_acceptable_unknown_missing_ev_count
building_ev_departure_audit_min_acceptable_unknown_missing_target_count
building_ev_departure_audit_min_acceptable_unknown_outage_supply_not_replayed_count
building_ev_departure_audit_min_acceptable_unknown_unsupported_battery_model_count
building_ev_departure_audit_service_coverage_ratio
building_ev_departure_audit_service_observed_count
building_ev_departure_audit_service_unknown_count
building_ev_departure_audit_target_coverage_ratio
building_ev_departure_audit_target_feasible_count
building_ev_departure_audit_target_feasible_service_met_count
building_ev_departure_audit_target_feasible_service_observed_count
building_ev_departure_audit_target_infeasible_count
building_ev_departure_audit_target_service_feasible_ratio
building_ev_departure_audit_target_service_met_count
building_ev_departure_audit_target_service_observed_ratio
building_ev_departure_audit_target_unknown_count
building_ev_departure_audit_target_unknown_invalid_battery_parameters_count
building_ev_departure_audit_target_unknown_invalid_capacity_count
building_ev_departure_audit_target_unknown_invalid_charger_efficiency_count
building_ev_departure_audit_target_unknown_invalid_charger_power_count
building_ev_departure_audit_target_unknown_invalid_time_step_count
building_ev_departure_audit_target_unknown_missing_arrival_soc_count
building_ev_departure_audit_target_unknown_missing_battery_count
building_ev_departure_audit_target_unknown_missing_ev_count
building_ev_departure_audit_target_unknown_missing_target_count
building_ev_departure_audit_target_unknown_outage_supply_not_replayed_count
building_ev_departure_audit_target_unknown_unsupported_battery_model_count
building_ev_departure_audit_within_tolerance_coverage_ratio
building_ev_departure_audit_within_tolerance_feasible_count
building_ev_departure_audit_within_tolerance_feasible_service_met_count
building_ev_departure_audit_within_tolerance_feasible_service_observed_count
building_ev_departure_audit_within_tolerance_infeasible_count
building_ev_departure_audit_within_tolerance_service_feasible_ratio
building_ev_departure_audit_within_tolerance_service_met_count
building_ev_departure_audit_within_tolerance_service_observed_ratio
building_ev_departure_audit_within_tolerance_unknown_count
building_ev_departure_audit_within_tolerance_unknown_invalid_battery_parameters_count
building_ev_departure_audit_within_tolerance_unknown_invalid_capacity_count
building_ev_departure_audit_within_tolerance_unknown_invalid_charger_efficiency_count
building_ev_departure_audit_within_tolerance_unknown_invalid_charger_power_count
building_ev_departure_audit_within_tolerance_unknown_invalid_time_step_count
building_ev_departure_audit_within_tolerance_unknown_missing_arrival_soc_count
building_ev_departure_audit_within_tolerance_unknown_missing_battery_count
building_ev_departure_audit_within_tolerance_unknown_missing_ev_count
building_ev_departure_audit_within_tolerance_unknown_missing_target_count
building_ev_departure_audit_within_tolerance_unknown_outage_supply_not_replayed_count
building_ev_departure_audit_within_tolerance_unknown_unsupported_battery_model_count
district_ev_departure_audit_departures_count
district_ev_departure_audit_min_acceptable_coverage_ratio
district_ev_departure_audit_min_acceptable_feasible_count
district_ev_departure_audit_min_acceptable_feasible_service_met_count
district_ev_departure_audit_min_acceptable_feasible_service_observed_count
district_ev_departure_audit_min_acceptable_infeasible_count
district_ev_departure_audit_min_acceptable_service_feasible_ratio
district_ev_departure_audit_min_acceptable_service_met_count
district_ev_departure_audit_min_acceptable_service_observed_ratio
district_ev_departure_audit_min_acceptable_unknown_count
district_ev_departure_audit_min_acceptable_unknown_invalid_battery_parameters_count
district_ev_departure_audit_min_acceptable_unknown_invalid_capacity_count
district_ev_departure_audit_min_acceptable_unknown_invalid_charger_efficiency_count
district_ev_departure_audit_min_acceptable_unknown_invalid_charger_power_count
district_ev_departure_audit_min_acceptable_unknown_invalid_time_step_count
district_ev_departure_audit_min_acceptable_unknown_missing_arrival_soc_count
district_ev_departure_audit_min_acceptable_unknown_missing_battery_count
district_ev_departure_audit_min_acceptable_unknown_missing_ev_count
district_ev_departure_audit_min_acceptable_unknown_missing_target_count
district_ev_departure_audit_min_acceptable_unknown_outage_supply_not_replayed_count
district_ev_departure_audit_min_acceptable_unknown_unsupported_battery_model_count
district_ev_departure_audit_service_coverage_ratio
district_ev_departure_audit_service_observed_count
district_ev_departure_audit_service_unknown_count
district_ev_departure_audit_target_coverage_ratio
district_ev_departure_audit_target_feasible_count
district_ev_departure_audit_target_feasible_service_met_count
district_ev_departure_audit_target_feasible_service_observed_count
district_ev_departure_audit_target_infeasible_count
district_ev_departure_audit_target_service_feasible_ratio
district_ev_departure_audit_target_service_met_count
district_ev_departure_audit_target_service_observed_ratio
district_ev_departure_audit_target_unknown_count
district_ev_departure_audit_target_unknown_invalid_battery_parameters_count
district_ev_departure_audit_target_unknown_invalid_capacity_count
district_ev_departure_audit_target_unknown_invalid_charger_efficiency_count
district_ev_departure_audit_target_unknown_invalid_charger_power_count
district_ev_departure_audit_target_unknown_invalid_time_step_count
district_ev_departure_audit_target_unknown_missing_arrival_soc_count
district_ev_departure_audit_target_unknown_missing_battery_count
district_ev_departure_audit_target_unknown_missing_ev_count
district_ev_departure_audit_target_unknown_missing_target_count
district_ev_departure_audit_target_unknown_outage_supply_not_replayed_count
district_ev_departure_audit_target_unknown_unsupported_battery_model_count
district_ev_departure_audit_within_tolerance_coverage_ratio
district_ev_departure_audit_within_tolerance_feasible_count
district_ev_departure_audit_within_tolerance_feasible_service_met_count
district_ev_departure_audit_within_tolerance_feasible_service_observed_count
district_ev_departure_audit_within_tolerance_infeasible_count
district_ev_departure_audit_within_tolerance_service_feasible_ratio
district_ev_departure_audit_within_tolerance_service_met_count
district_ev_departure_audit_within_tolerance_service_observed_ratio
district_ev_departure_audit_within_tolerance_unknown_count
district_ev_departure_audit_within_tolerance_unknown_invalid_battery_parameters_count
district_ev_departure_audit_within_tolerance_unknown_invalid_capacity_count
district_ev_departure_audit_within_tolerance_unknown_invalid_charger_efficiency_count
district_ev_departure_audit_within_tolerance_unknown_invalid_charger_power_count
district_ev_departure_audit_within_tolerance_unknown_invalid_time_step_count
district_ev_departure_audit_within_tolerance_unknown_missing_arrival_soc_count
district_ev_departure_audit_within_tolerance_unknown_missing_battery_count
district_ev_departure_audit_within_tolerance_unknown_missing_ev_count
district_ev_departure_audit_within_tolerance_unknown_missing_target_count
district_ev_departure_audit_within_tolerance_unknown_outage_supply_not_replayed_count
district_ev_departure_audit_within_tolerance_unknown_unsupported_battery_model_count
```

</details>

## Flexible appliances

Cycle service of deferrable (flexible) appliances from their cycle states and nominal cycle energies. Every member emits these rows; without appliances, counts and energies are 0 and rates are undefined.

Equations and rules: [Flexible appliances](kpis_reference.md#flexible-appliances).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `deferrable_appliance_service_completed_cycles{,_business_as_usual,_delta_to_business_as_usual}_count` | building, district | count | Cycles that ran their full profile; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `deferrable_appliance_service_missed_cycles{,_business_as_usual,_delta_to_business_as_usual}_count` | building, district | count | Cycles not started by their latest start step, plus running cycles interrupted by a power outage; BAU variants as in the shared rules. |
| `deferrable_appliance_service_service_level{,_business_as_usual,_delta_to_business_as_usual}_ratio` | building, district | ratio | completed / (completed + missed), undefined when both are 0; the delta is undefined when either side is. |
| `deferrable_appliance_service_served_energy_total{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Nominal energy of the completed cycles, from their requested profiles, not metered; BAU variants as in the shared rules. |
| `deferrable_appliance_service_unserved_energy_total{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Full nominal energy of the missed cycles, including any part consumed before an interruption; BAU variants as in the shared rules. |
| `deferrable_appliance_service_average_start_delay{,_business_as_usual,_delta_to_business_as_usual}_hours` | building, district | hours | Mean over completed cycles of (start − earliest start) in hours; undefined when no cycle completed. |
| `deferrable_appliance_ratio_to_business_as_usual_{completed_cycles,missed_cycles,service_level,served_energy_total,unserved_energy_total,average_start_delay}_ratio` | building, district | ratio | Control over BAU value; undefined when its own two totals are zero, even when cycles were due (#305), and when the BAU value is zero or either value is undefined. |

<details>
<summary>All 48 names</summary>

```text
building_deferrable_appliance_ratio_to_business_as_usual_average_start_delay_ratio
building_deferrable_appliance_ratio_to_business_as_usual_completed_cycles_ratio
building_deferrable_appliance_ratio_to_business_as_usual_missed_cycles_ratio
building_deferrable_appliance_ratio_to_business_as_usual_served_energy_total_ratio
building_deferrable_appliance_ratio_to_business_as_usual_service_level_ratio
building_deferrable_appliance_ratio_to_business_as_usual_unserved_energy_total_ratio
building_deferrable_appliance_service_average_start_delay_business_as_usual_hours
building_deferrable_appliance_service_average_start_delay_delta_to_business_as_usual_hours
building_deferrable_appliance_service_average_start_delay_hours
building_deferrable_appliance_service_completed_cycles_business_as_usual_count
building_deferrable_appliance_service_completed_cycles_count
building_deferrable_appliance_service_completed_cycles_delta_to_business_as_usual_count
building_deferrable_appliance_service_missed_cycles_business_as_usual_count
building_deferrable_appliance_service_missed_cycles_count
building_deferrable_appliance_service_missed_cycles_delta_to_business_as_usual_count
building_deferrable_appliance_service_served_energy_total_business_as_usual_kwh
building_deferrable_appliance_service_served_energy_total_delta_to_business_as_usual_kwh
building_deferrable_appliance_service_served_energy_total_kwh
building_deferrable_appliance_service_service_level_business_as_usual_ratio
building_deferrable_appliance_service_service_level_delta_to_business_as_usual_ratio
building_deferrable_appliance_service_service_level_ratio
building_deferrable_appliance_service_unserved_energy_total_business_as_usual_kwh
building_deferrable_appliance_service_unserved_energy_total_delta_to_business_as_usual_kwh
building_deferrable_appliance_service_unserved_energy_total_kwh
district_deferrable_appliance_ratio_to_business_as_usual_average_start_delay_ratio
district_deferrable_appliance_ratio_to_business_as_usual_completed_cycles_ratio
district_deferrable_appliance_ratio_to_business_as_usual_missed_cycles_ratio
district_deferrable_appliance_ratio_to_business_as_usual_served_energy_total_ratio
district_deferrable_appliance_ratio_to_business_as_usual_service_level_ratio
district_deferrable_appliance_ratio_to_business_as_usual_unserved_energy_total_ratio
district_deferrable_appliance_service_average_start_delay_business_as_usual_hours
district_deferrable_appliance_service_average_start_delay_delta_to_business_as_usual_hours
district_deferrable_appliance_service_average_start_delay_hours
district_deferrable_appliance_service_completed_cycles_business_as_usual_count
district_deferrable_appliance_service_completed_cycles_count
district_deferrable_appliance_service_completed_cycles_delta_to_business_as_usual_count
district_deferrable_appliance_service_missed_cycles_business_as_usual_count
district_deferrable_appliance_service_missed_cycles_count
district_deferrable_appliance_service_missed_cycles_delta_to_business_as_usual_count
district_deferrable_appliance_service_served_energy_total_business_as_usual_kwh
district_deferrable_appliance_service_served_energy_total_delta_to_business_as_usual_kwh
district_deferrable_appliance_service_served_energy_total_kwh
district_deferrable_appliance_service_service_level_business_as_usual_ratio
district_deferrable_appliance_service_service_level_delta_to_business_as_usual_ratio
district_deferrable_appliance_service_service_level_ratio
district_deferrable_appliance_service_unserved_energy_total_business_as_usual_kwh
district_deferrable_appliance_service_unserved_energy_total_delta_to_business_as_usual_kwh
district_deferrable_appliance_service_unserved_energy_total_kwh
```

</details>

## Flexible-appliance audit

Audited cycle service of flexible appliances from metered energy in executed intervals, with an explicit population and exclusive states. Every member emits these rows.

Equations and rules: [Flexible-appliance audit](kpis_reference.md#flexible-appliance-audit).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `deferrable_appliance_audit_{catalogue,offered,excluded}_count` | building, district | count | Cycle requests in the catalogue, those included in the audited population (offered), and the rest (excluded = catalogue − offered). |
| `deferrable_appliance_audit_duplicate_offered_count` | building, district | count | Offered requests seen again on a later instance of the same appliance, for example after a reinstall; only the first is kept. |
| `deferrable_appliance_audit_{pending,running,completed,missed,cancelled}_count` | building, district | count | Offered requests by exclusive final state. |
| `deferrable_appliance_audit_resolved_count` | building, district | count | completed + missed + cancelled. |
| `deferrable_appliance_audit_excluded_{expired_before_episode,expired_before_activation,not_yet_available,removed_before_available,outside_episode_service_horizon,already_accounted_previous_instance}_count` | building, district | count | Excluded requests by their first applicable exclusion reason; the reasons sum to the excluded count. |
| `deferrable_appliance_audit_reason_{profile_delivered,profile_energy_shortfall,start_window_elapsed,asset_removed,member_removed,window_open,profile_in_progress}_count` | building, district | count | Offered requests by the reason for their state. |
| `deferrable_appliance_audit_{requested,served,final_unserved,outstanding}_energy_kwh` | building, district | kWh | Over offered requests: requested energy, metered energy attributed to the cycles, the remainder of missed and cancelled requests, and the remainder of pending and running ones. |
| `deferrable_appliance_audit_excluded_requested_energy_kwh` | building, district | kWh | Requested energy of the excluded requests. |
| `deferrable_appliance_audit_physical_energy_kwh` | building, district | kWh | Metered appliance energy in all executed intervals, before attribution to cycles. |
| `deferrable_appliance_audit_physical_balance_residual_kwh` | building, district | kWh | Physical energy − served energy: metered energy that no offered request accounts for. |
| `deferrable_appliance_audit_service_balance_residual_kwh` | building, district | kWh | Requested − served − final unserved − outstanding; about 0 by construction, a consistency check. |
| `deferrable_appliance_audit_observed_completion_ratio` | building, district | ratio | completed / offered; undefined when nothing was offered. |
| `deferrable_appliance_audit_resolved_completion_ratio` | building, district | ratio | completed / resolved; undefined when nothing was resolved. |
| `deferrable_appliance_audit_resolved_coverage_ratio` | building, district | ratio | resolved / offered; undefined when nothing was offered. |

<details>
<summary>All 68 names</summary>

```text
building_deferrable_appliance_audit_cancelled_count
building_deferrable_appliance_audit_catalogue_count
building_deferrable_appliance_audit_completed_count
building_deferrable_appliance_audit_duplicate_offered_count
building_deferrable_appliance_audit_excluded_already_accounted_previous_instance_count
building_deferrable_appliance_audit_excluded_count
building_deferrable_appliance_audit_excluded_expired_before_activation_count
building_deferrable_appliance_audit_excluded_expired_before_episode_count
building_deferrable_appliance_audit_excluded_not_yet_available_count
building_deferrable_appliance_audit_excluded_outside_episode_service_horizon_count
building_deferrable_appliance_audit_excluded_removed_before_available_count
building_deferrable_appliance_audit_excluded_requested_energy_kwh
building_deferrable_appliance_audit_final_unserved_energy_kwh
building_deferrable_appliance_audit_missed_count
building_deferrable_appliance_audit_observed_completion_ratio
building_deferrable_appliance_audit_offered_count
building_deferrable_appliance_audit_outstanding_energy_kwh
building_deferrable_appliance_audit_pending_count
building_deferrable_appliance_audit_physical_balance_residual_kwh
building_deferrable_appliance_audit_physical_energy_kwh
building_deferrable_appliance_audit_reason_asset_removed_count
building_deferrable_appliance_audit_reason_member_removed_count
building_deferrable_appliance_audit_reason_profile_delivered_count
building_deferrable_appliance_audit_reason_profile_energy_shortfall_count
building_deferrable_appliance_audit_reason_profile_in_progress_count
building_deferrable_appliance_audit_reason_start_window_elapsed_count
building_deferrable_appliance_audit_reason_window_open_count
building_deferrable_appliance_audit_requested_energy_kwh
building_deferrable_appliance_audit_resolved_completion_ratio
building_deferrable_appliance_audit_resolved_count
building_deferrable_appliance_audit_resolved_coverage_ratio
building_deferrable_appliance_audit_running_count
building_deferrable_appliance_audit_served_energy_kwh
building_deferrable_appliance_audit_service_balance_residual_kwh
district_deferrable_appliance_audit_cancelled_count
district_deferrable_appliance_audit_catalogue_count
district_deferrable_appliance_audit_completed_count
district_deferrable_appliance_audit_duplicate_offered_count
district_deferrable_appliance_audit_excluded_already_accounted_previous_instance_count
district_deferrable_appliance_audit_excluded_count
district_deferrable_appliance_audit_excluded_expired_before_activation_count
district_deferrable_appliance_audit_excluded_expired_before_episode_count
district_deferrable_appliance_audit_excluded_not_yet_available_count
district_deferrable_appliance_audit_excluded_outside_episode_service_horizon_count
district_deferrable_appliance_audit_excluded_removed_before_available_count
district_deferrable_appliance_audit_excluded_requested_energy_kwh
district_deferrable_appliance_audit_final_unserved_energy_kwh
district_deferrable_appliance_audit_missed_count
district_deferrable_appliance_audit_observed_completion_ratio
district_deferrable_appliance_audit_offered_count
district_deferrable_appliance_audit_outstanding_energy_kwh
district_deferrable_appliance_audit_pending_count
district_deferrable_appliance_audit_physical_balance_residual_kwh
district_deferrable_appliance_audit_physical_energy_kwh
district_deferrable_appliance_audit_reason_asset_removed_count
district_deferrable_appliance_audit_reason_member_removed_count
district_deferrable_appliance_audit_reason_profile_delivered_count
district_deferrable_appliance_audit_reason_profile_energy_shortfall_count
district_deferrable_appliance_audit_reason_profile_in_progress_count
district_deferrable_appliance_audit_reason_start_window_elapsed_count
district_deferrable_appliance_audit_reason_window_open_count
district_deferrable_appliance_audit_requested_energy_kwh
district_deferrable_appliance_audit_resolved_completion_ratio
district_deferrable_appliance_audit_resolved_count
district_deferrable_appliance_audit_resolved_coverage_ratio
district_deferrable_appliance_audit_running_count
district_deferrable_appliance_audit_served_energy_kwh
district_deferrable_appliance_audit_service_balance_residual_kwh
```

</details>

## Escalators

Passenger service, operating-state changes and electricity use of escalators. Every member emits these rows; without escalators, totals are 0 and the service level is undefined.

Equations and rules: [Escalators](kpis_reference.md#escalators).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `escalator_service_requested_passengers_total_count` | building, district | count | Sum of the expected passenger values over the steps with an applied action. |
| `escalator_service_{served,unserved}_passengers_total_count` | building, district | count | Unserved: passengers at steps where service was required but the escalator was in standby or unavailable; served: requested − unserved. |
| `escalator_service_service_level_ratio` | building, district | ratio | served / requested passengers; undefined when none were requested. |
| `escalator_energy_electricity_consumption_total_kwh` | building, district | kWh | Escalator electricity consumption over the steps with an applied action. |
| `escalator_operation_state_changes_count` | building, district | count | Steps at which the applied operating state (standby, slow, normal) changed. |

<details>
<summary>All 12 names</summary>

```text
building_escalator_energy_electricity_consumption_total_kwh
building_escalator_operation_state_changes_count
building_escalator_service_requested_passengers_total_count
building_escalator_service_served_passengers_total_count
building_escalator_service_service_level_ratio
building_escalator_service_unserved_passengers_total_count
district_escalator_energy_electricity_consumption_total_kwh
district_escalator_operation_state_changes_count
district_escalator_service_requested_passengers_total_count
district_escalator_service_served_passengers_total_count
district_escalator_service_service_level_ratio
district_escalator_service_unserved_passengers_total_count
```

</details>

## Comfort and resilience

Legacy thermal-comfort and outage-resilience rows of each building, always emitted; the district value is the plain mean of the building values, and the canonical discomfort KPI is `district_thermal_service_audit_discomfort_ratio`.

Equations and rules: [Comfort and resilience](kpis_reference.md#comfort-and-resilience).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `comfort_resilience_discomfort_{overall,cold,hot}_ratio` | building, district | ratio | Share of evaluated occupied steps that are too cold (T < T_heat − band), too hot (T > T_cool + band) or either (`overall`); undefined when no occupied step is evaluated. The district value is the mean of the building values; for controller comparison use `thermal_service_audit_discomfort_ratio`. |
| `comfort_resilience_discomfort_{cold,hot}_delta_{min,max,average}_c` | building, district | degC | Minimum, maximum and mean distance from the set point over the too-cold (T_heat − T) or too-hot (T − T_cool) steps; always positive and larger than the band, undefined when there is no such step. The district value is the mean of the building values, not a district minimum or maximum. |
| `comfort_resilience_resilience_one_minus_thermal_ratio` | building, district | ratio | Overall discomfort ratio restricted to occupied steps during a power outage; undefined when no occupied outage step is evaluated. Same value per building as `thermal_service_audit_outage_discomfort_ratio`, but a plain mean at district level. |
| `comfort_resilience_resilience_unserved_energy_{outage,annual}_normalized_ratio` | building, district | ratio | Unserved service energy (cooling, heating, DHW and non-shiftable load) over expected service energy, over outage steps (`outage`) or all steps (`annual`). Reads 0, not undefined, when the expected energy is zero, so the outage variant is 0 in runs without outages. |

<details>
<summary>All 24 names</summary>

```text
building_comfort_resilience_discomfort_cold_delta_average_c
building_comfort_resilience_discomfort_cold_delta_max_c
building_comfort_resilience_discomfort_cold_delta_min_c
building_comfort_resilience_discomfort_cold_ratio
building_comfort_resilience_discomfort_hot_delta_average_c
building_comfort_resilience_discomfort_hot_delta_max_c
building_comfort_resilience_discomfort_hot_delta_min_c
building_comfort_resilience_discomfort_hot_ratio
building_comfort_resilience_discomfort_overall_ratio
building_comfort_resilience_resilience_one_minus_thermal_ratio
building_comfort_resilience_resilience_unserved_energy_annual_normalized_ratio
building_comfort_resilience_resilience_unserved_energy_outage_normalized_ratio
district_comfort_resilience_discomfort_cold_delta_average_c
district_comfort_resilience_discomfort_cold_delta_max_c
district_comfort_resilience_discomfort_cold_delta_min_c
district_comfort_resilience_discomfort_cold_ratio
district_comfort_resilience_discomfort_hot_delta_average_c
district_comfort_resilience_discomfort_hot_delta_max_c
district_comfort_resilience_discomfort_hot_delta_min_c
district_comfort_resilience_discomfort_hot_ratio
district_comfort_resilience_discomfort_overall_ratio
district_comfort_resilience_resilience_one_minus_thermal_ratio
district_comfort_resilience_resilience_unserved_energy_annual_normalized_ratio
district_comfort_resilience_resilience_unserved_energy_outage_normalized_ratio
```

</details>

## Thermal-service audit

Interval counts, hours, energy and ratios that audit thermal comfort and service energy of each building, always emitted; the district pools the counts, and `district_thermal_service_audit_discomfort_ratio` is the canonical discomfort KPI.

Equations and rules: [Thermal-service audit](kpis_reference.md#thermal-service-audit).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `thermal_service_audit_{executed,known_occupancy,occupied,evaluated_occupied,excluded_occupied}_intervals_count` | building, district | count | Executed intervals; intervals with a known occupant count (finite, ≥ 0); occupied intervals (count > 0); occupied intervals with valid temperature, set points and band (evaluated); occupied intervals without them (excluded). |
| `thermal_service_audit_{discomfort,cold,hot}_intervals_count` | building, district | count | Evaluated occupied intervals that are too cold (T < T_heat − band), too hot (T > T_cool + band) or either. |
| `thermal_service_audit_{outage,unknown_outage,outage_occupied,evaluated_outage_occupied,outage_discomfort}_intervals_count` | building, district | count | Intervals with a power outage (signal > 0) and with an unknown outage signal, whatever the occupancy; then outage intervals that are occupied, occupied and evaluated, and uncomfortable. |
| `thermal_service_audit_energy_evaluated_intervals_count` | building, district | count | Intervals whose expected and served energy are finite and non-negative for all four end uses; the others are left out of the service-energy totals. |
| `thermal_service_audit_{occupied,evaluated_occupied,discomfort}_hours` | building, district | hours | The matching interval count times the step length in hours. Not carried to the portfolio. |
| `thermal_service_audit_{cold,hot}_degree_hours` | building, district | degC_h | Degree-hours (°C·h) of discomfort: the sum over too-cold intervals of (T_heat − T), or over too-hot intervals of (T − T_cool), times the step length in hours; measured from the set point, not the band edge. Not carried to the portfolio. |
| `thermal_service_audit_{expected,served,unserved,outage_expected,outage_unserved}_service_energy_kwh` | building, district | kWh | Expected, served and unserved service energy over the energy-evaluated intervals, and the expected and unserved energy during outages; unserved energy is the sum over end uses of max(expected − served, 0). |
| `thermal_service_audit_discomfort_ratio` | building, district | ratio | Canonical discomfort KPI: discomfort intervals over evaluated occupied intervals, undefined when there are none. The district value is the ratio of the summed building counts. |
| `thermal_service_audit_outage_discomfort_ratio` | building, district | ratio | Outage discomfort intervals over evaluated occupied outage intervals; undefined when there are none. |
| `thermal_service_audit_{thermal,outage_thermal}_coverage_ratio` | building, district | ratio | Evaluated occupied intervals over occupied intervals, overall or during outages; undefined when there is no occupied interval. |
| `thermal_service_audit_{occupancy,energy}_coverage_ratio` | building, district | ratio | Intervals with known occupancy, or with valid service energy, over executed intervals. |
| `thermal_service_audit_{unserved,outage_unserved}_service_ratio` | building, district | ratio | Unserved over expected service energy, overall or during outages; undefined, not 0, when the expected energy is zero (for example without outages). |

<details>
<summary>All 64 names</summary>

```text
building_thermal_service_audit_cold_degree_hours
building_thermal_service_audit_cold_intervals_count
building_thermal_service_audit_discomfort_hours
building_thermal_service_audit_discomfort_intervals_count
building_thermal_service_audit_discomfort_ratio
building_thermal_service_audit_energy_coverage_ratio
building_thermal_service_audit_energy_evaluated_intervals_count
building_thermal_service_audit_evaluated_occupied_hours
building_thermal_service_audit_evaluated_occupied_intervals_count
building_thermal_service_audit_evaluated_outage_occupied_intervals_count
building_thermal_service_audit_excluded_occupied_intervals_count
building_thermal_service_audit_executed_intervals_count
building_thermal_service_audit_expected_service_energy_kwh
building_thermal_service_audit_hot_degree_hours
building_thermal_service_audit_hot_intervals_count
building_thermal_service_audit_known_occupancy_intervals_count
building_thermal_service_audit_occupancy_coverage_ratio
building_thermal_service_audit_occupied_hours
building_thermal_service_audit_occupied_intervals_count
building_thermal_service_audit_outage_discomfort_intervals_count
building_thermal_service_audit_outage_discomfort_ratio
building_thermal_service_audit_outage_expected_service_energy_kwh
building_thermal_service_audit_outage_intervals_count
building_thermal_service_audit_outage_occupied_intervals_count
building_thermal_service_audit_outage_thermal_coverage_ratio
building_thermal_service_audit_outage_unserved_service_energy_kwh
building_thermal_service_audit_outage_unserved_service_ratio
building_thermal_service_audit_served_service_energy_kwh
building_thermal_service_audit_thermal_coverage_ratio
building_thermal_service_audit_unknown_outage_intervals_count
building_thermal_service_audit_unserved_service_energy_kwh
building_thermal_service_audit_unserved_service_ratio
district_thermal_service_audit_cold_degree_hours
district_thermal_service_audit_cold_intervals_count
district_thermal_service_audit_discomfort_hours
district_thermal_service_audit_discomfort_intervals_count
district_thermal_service_audit_discomfort_ratio
district_thermal_service_audit_energy_coverage_ratio
district_thermal_service_audit_energy_evaluated_intervals_count
district_thermal_service_audit_evaluated_occupied_hours
district_thermal_service_audit_evaluated_occupied_intervals_count
district_thermal_service_audit_evaluated_outage_occupied_intervals_count
district_thermal_service_audit_excluded_occupied_intervals_count
district_thermal_service_audit_executed_intervals_count
district_thermal_service_audit_expected_service_energy_kwh
district_thermal_service_audit_hot_degree_hours
district_thermal_service_audit_hot_intervals_count
district_thermal_service_audit_known_occupancy_intervals_count
district_thermal_service_audit_occupancy_coverage_ratio
district_thermal_service_audit_occupied_hours
district_thermal_service_audit_occupied_intervals_count
district_thermal_service_audit_outage_discomfort_intervals_count
district_thermal_service_audit_outage_discomfort_ratio
district_thermal_service_audit_outage_expected_service_energy_kwh
district_thermal_service_audit_outage_intervals_count
district_thermal_service_audit_outage_occupied_intervals_count
district_thermal_service_audit_outage_thermal_coverage_ratio
district_thermal_service_audit_outage_unserved_service_energy_kwh
district_thermal_service_audit_outage_unserved_service_ratio
district_thermal_service_audit_served_service_energy_kwh
district_thermal_service_audit_thermal_coverage_ratio
district_thermal_service_audit_unknown_outage_intervals_count
district_thermal_service_audit_unserved_service_energy_kwh
district_thermal_service_audit_unserved_service_ratio
```

</details>

## Equity

Relative cost benefit of each building against the conventional baseline and its distribution over the district, always emitted; the canonical Gini KPI is `district_equity_audit_positive_benefit_gini_ratio`.

Equations and rules: [Equity](kpis_reference.md#equity).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `equity_benefit_relative_percent` | building | percent | 100 · (B − C) / B, with C and B the building's unclipped cost totals under control and under the conventional baseline condition (not BAU), market-settled when the community market is enabled; positive is a saving, undefined when B ≤ 0. Building level only. |
| `equity_distribution_gini_benefit_ratio` | district | ratio | Gini coefficient of the building benefits clipped at 0; undefined when no building has a defined benefit or all clipped benefits are 0. Same value as the canonical `equity_audit_positive_benefit_gini_ratio`. |
| `equity_distribution_top20_benefit_ratio` | district | ratio | Share of the summed clipped benefit held by the ceil(20 %) of buildings with the largest benefit (at least one); same undefined rule as the Gini. |
| `equity_distribution_losers_percent` | district | percent | Percentage of buildings with a defined benefit whose benefit is negative (cost above the baseline). |
| `equity_distribution_bpr_asset_poor_over_rich_ratio` | district | ratio | Mean clipped benefit of `asset_poor` buildings over that of `asset_rich` buildings; undefined unless every building has `equity_group` set to one of these two tags, both groups have a defined benefit and the `asset_rich` mean is positive. |

<details>
<summary>All 5 names</summary>

```text
building_equity_benefit_relative_percent
district_equity_distribution_bpr_asset_poor_over_rich_ratio
district_equity_distribution_gini_benefit_ratio
district_equity_distribution_losers_percent
district_equity_distribution_top20_benefit_ratio
```

</details>

## Equity audit

District equity rows with their member population, always emitted; `district_equity_audit_positive_benefit_gini_ratio` is the canonical Gini KPI.

Equations and rules: [Equity audit](kpis_reference.md#equity-audit).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `equity_audit_{population_members,eligible_members,excluded_nonpositive_reference,excluded_unknown_cost}_count` | district | count | KPI buildings; buildings with finite costs and a positive baseline cost (eligible); buildings excluded for a baseline cost ≤ 0; buildings excluded for a non-finite cost total, which the current cost sums never produce, so this count is always 0. |
| `equity_audit_coverage_ratio` | district | ratio | Eligible buildings over KPI buildings; undefined when there is no building. |
| `equity_audit_losers_percent` | district | percent | Percentage of eligible buildings with a negative benefit; same value as `equity_distribution_losers_percent`. |
| `equity_audit_positive_benefit_gini_ratio` | district | ratio | Canonical Gini KPI: Gini coefficient of the eligible buildings' benefits clipped at 0; undefined when the clipped benefits sum to 0. Report it with the losers percentage and the coverage ratio. |
| `equity_audit_positive_benefit_top20_ratio` | district | ratio | Share of the summed clipped benefit held by the ceil(20 %) most-benefiting eligible buildings (at least one); same value as `equity_distribution_top20_benefit_ratio`. |

<details>
<summary>All 8 names</summary>

```text
district_equity_audit_coverage_ratio
district_equity_audit_eligible_members_count
district_equity_audit_excluded_nonpositive_reference_count
district_equity_audit_excluded_unknown_cost_count
district_equity_audit_losers_percent
district_equity_audit_population_members_count
district_equity_audit_positive_benefit_gini_ratio
district_equity_audit_positive_benefit_top20_ratio
```

</details>

## Demand response

Delivery against dataset demand-response requests, measured from a pre-event baseline, and its settlement; the rows appear when `demand_response.enabled` is true.

Equations and rules: [Demand response](kpis_reference.md#demand-response).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `demand_response_events_count` | building, district | count | Distinct requests with at least one settled step; for a building, the requests active while it was a member. |
| `demand_response_active_time_step_count` | building, district | count | Executed steps with an active request, including steps with an invalid baseline; for a building, those steps at which it was a member. |
| `demand_response_invalid_baseline_time_step_count` | building, district | count | Active steps whose pre-event baseline was invalid, which are excluded from delivery and cash. |
| `demand_response_requested_total_kwh` | building, district | kWh | Requested energy, `target power · step hours`, over all active steps; split equally over the active members at building level. |
| `demand_response_valid_requested_total_kwh` | district | kWh | Requested energy of the active steps with a valid baseline: the denominator of the compliance ratio. |
| `demand_response_delivered_total_kwh` | building, district | kWh | Signed movement from the baseline in the requested direction, uncapped and without tolerance, over valid steps; at building level, the member's own movement. |
| `demand_response_credited_total_kwh` | district | kWh | Delivery credited against the requests: positive delivery capped at the target, without the tolerance; the numerator of the compliance ratio. |
| `demand_response_shortfall_total_kwh` | building, district | kWh | `max(target − delivery − tolerance, 0)` energy over valid steps; at building level, the district shortfall allocated by penalty weight. |
| `demand_response_compliance_ratio` | building, district | ratio | Credited energy over valid requested energy, clipped to [0, 1]; undefined without valid requested energy. At building level, the member's credited share over its equal share of the request. |
| `demand_response_{revenue,penalty,net_revenue}_total_eur` | building, district | EUR | Revenue (credited energy · activation price), penalty (shortfall · penalty price) and their difference. |
| `demand_response_uncapped_contribution_total_kwh` | building | kWh | Diagnostic: the member's own positive movement in the requested direction, without tolerance or cap; it does not add up to any district value. |

<details>
<summary>All 23 names</summary>

```text
building_demand_response_active_time_step_count
building_demand_response_compliance_ratio
building_demand_response_delivered_total_kwh
building_demand_response_events_count
building_demand_response_invalid_baseline_time_step_count
building_demand_response_net_revenue_total_eur
building_demand_response_penalty_total_eur
building_demand_response_requested_total_kwh
building_demand_response_revenue_total_eur
building_demand_response_shortfall_total_kwh
building_demand_response_uncapped_contribution_total_kwh
district_demand_response_active_time_step_count
district_demand_response_compliance_ratio
district_demand_response_credited_total_kwh
district_demand_response_delivered_total_kwh
district_demand_response_events_count
district_demand_response_invalid_baseline_time_step_count
district_demand_response_net_revenue_total_eur
district_demand_response_penalty_total_eur
district_demand_response_requested_total_kwh
district_demand_response_revenue_total_eur
district_demand_response_shortfall_total_kwh
district_demand_response_valid_requested_total_kwh
```

</details>

## Demand-response audit

District demand-response totals, coverage and exclusions split by the declared request purpose (`all`, `service`, `stress`, `unspecified`); the rows appear when demand response is enabled, for all four purposes.

Equations and rules: [Demand-response audit](kpis_reference.md#demand-response-audit).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `demand_response_audit_{all,service,stress,unspecified}_{requested,valid_requested,delivered,credited,shortfall}_kwh` | district | kWh | Requested, valid requested, delivered, credited and shortfall energy of the purpose's settled steps, defined as in demand response. |
| `demand_response_audit_{all,service,stress,unspecified}_{revenue,penalty,net_revenue}_eur` | district | EUR | Revenue, penalty and net revenue of the purpose's settled steps. |
| `demand_response_audit_{all,service,stress,unspecified}_events_count` | district | count | Distinct requests of the purpose with at least one settled step. |
| `demand_response_audit_{all,service,stress,unspecified}_{active,valid}_intervals_count` | district | count | Settled steps of the purpose (active), and those with a valid baseline (valid). |
| `demand_response_audit_{all,service,stress,unspecified}_excluded_{insufficient_history,nonfinite_history,no_members,topology_changed}_intervals_count` | district | count | Steps of the purpose with an invalid baseline, by reason; the four counts add up to active minus valid steps. |
| `demand_response_audit_{all,service,stress,unspecified}_baseline_coverage_ratio` | district | ratio | Valid steps over active steps; undefined when the purpose has no settled step. |
| `demand_response_audit_{all,service,stress,unspecified}_requested_energy_coverage_ratio` | district | ratio | Valid requested energy over requested energy; undefined when no energy was requested. |
| `demand_response_audit_{all,service,stress,unspecified}_compliance_ratio` | district | ratio | Credited over valid requested energy, clipped to [0, 1]; undefined when valid requested energy is 0. |

<details>
<summary>All 72 names</summary>

```text
district_demand_response_audit_all_active_intervals_count
district_demand_response_audit_all_baseline_coverage_ratio
district_demand_response_audit_all_compliance_ratio
district_demand_response_audit_all_credited_kwh
district_demand_response_audit_all_delivered_kwh
district_demand_response_audit_all_events_count
district_demand_response_audit_all_excluded_insufficient_history_intervals_count
district_demand_response_audit_all_excluded_no_members_intervals_count
district_demand_response_audit_all_excluded_nonfinite_history_intervals_count
district_demand_response_audit_all_excluded_topology_changed_intervals_count
district_demand_response_audit_all_net_revenue_eur
district_demand_response_audit_all_penalty_eur
district_demand_response_audit_all_requested_energy_coverage_ratio
district_demand_response_audit_all_requested_kwh
district_demand_response_audit_all_revenue_eur
district_demand_response_audit_all_shortfall_kwh
district_demand_response_audit_all_valid_intervals_count
district_demand_response_audit_all_valid_requested_kwh
district_demand_response_audit_service_active_intervals_count
district_demand_response_audit_service_baseline_coverage_ratio
district_demand_response_audit_service_compliance_ratio
district_demand_response_audit_service_credited_kwh
district_demand_response_audit_service_delivered_kwh
district_demand_response_audit_service_events_count
district_demand_response_audit_service_excluded_insufficient_history_intervals_count
district_demand_response_audit_service_excluded_no_members_intervals_count
district_demand_response_audit_service_excluded_nonfinite_history_intervals_count
district_demand_response_audit_service_excluded_topology_changed_intervals_count
district_demand_response_audit_service_net_revenue_eur
district_demand_response_audit_service_penalty_eur
district_demand_response_audit_service_requested_energy_coverage_ratio
district_demand_response_audit_service_requested_kwh
district_demand_response_audit_service_revenue_eur
district_demand_response_audit_service_shortfall_kwh
district_demand_response_audit_service_valid_intervals_count
district_demand_response_audit_service_valid_requested_kwh
district_demand_response_audit_stress_active_intervals_count
district_demand_response_audit_stress_baseline_coverage_ratio
district_demand_response_audit_stress_compliance_ratio
district_demand_response_audit_stress_credited_kwh
district_demand_response_audit_stress_delivered_kwh
district_demand_response_audit_stress_events_count
district_demand_response_audit_stress_excluded_insufficient_history_intervals_count
district_demand_response_audit_stress_excluded_no_members_intervals_count
district_demand_response_audit_stress_excluded_nonfinite_history_intervals_count
district_demand_response_audit_stress_excluded_topology_changed_intervals_count
district_demand_response_audit_stress_net_revenue_eur
district_demand_response_audit_stress_penalty_eur
district_demand_response_audit_stress_requested_energy_coverage_ratio
district_demand_response_audit_stress_requested_kwh
district_demand_response_audit_stress_revenue_eur
district_demand_response_audit_stress_shortfall_kwh
district_demand_response_audit_stress_valid_intervals_count
district_demand_response_audit_stress_valid_requested_kwh
district_demand_response_audit_unspecified_active_intervals_count
district_demand_response_audit_unspecified_baseline_coverage_ratio
district_demand_response_audit_unspecified_compliance_ratio
district_demand_response_audit_unspecified_credited_kwh
district_demand_response_audit_unspecified_delivered_kwh
district_demand_response_audit_unspecified_events_count
district_demand_response_audit_unspecified_excluded_insufficient_history_intervals_count
district_demand_response_audit_unspecified_excluded_no_members_intervals_count
district_demand_response_audit_unspecified_excluded_nonfinite_history_intervals_count
district_demand_response_audit_unspecified_excluded_topology_changed_intervals_count
district_demand_response_audit_unspecified_net_revenue_eur
district_demand_response_audit_unspecified_penalty_eur
district_demand_response_audit_unspecified_requested_energy_coverage_ratio
district_demand_response_audit_unspecified_requested_kwh
district_demand_response_audit_unspecified_revenue_eur
district_demand_response_audit_unspecified_shortfall_kwh
district_demand_response_audit_unspecified_valid_intervals_count
district_demand_response_audit_unspecified_valid_requested_kwh
```

</details>

## Robustness

Counters of the observation, forecast, action and asset perturbations applied by dataset robustness events; the rows appear when `robustness.enabled` is true.

Equations and rules: [Robustness](kpis_reference.md#robustness).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `robustness_events_count` | building, district | count | Distinct robustness events with at least one recorded application (for a building, attributed to it). |
| `robustness_active_time_step_count` | building, district | count | Steps with at least one recorded application, including the terminal observation. |
| `robustness_{observation,forecast,action}_corruption_count` | building, district | count | Distinct (event, target) corruptions of observations, forecasts or actions, summed over steps. |
| `robustness_asset_unavailable_time_step_count` | building, district | count | Asset-steps of unavailability: each (event, asset) counts once per step. |
| `robustness_missing_observation_count` | building, district | count | Observation or forecast applications in `missing` mode, plus observations hidden by asset events. |
| `robustness_action_dropout_count` | building, district | count | Action applications in `dropout` mode, plus actions blocked by asset events. |

<details>
<summary>All 16 names</summary>

```text
building_robustness_action_corruption_count
building_robustness_action_dropout_count
building_robustness_active_time_step_count
building_robustness_asset_unavailable_time_step_count
building_robustness_events_count
building_robustness_forecast_corruption_count
building_robustness_missing_observation_count
building_robustness_observation_corruption_count
district_robustness_action_corruption_count
district_robustness_action_dropout_count
district_robustness_active_time_step_count
district_robustness_asset_unavailable_time_step_count
district_robustness_events_count
district_robustness_forecast_corruption_count
district_robustness_missing_observation_count
district_robustness_observation_corruption_count
```

</details>

## Energy provenance

Traces every kWh of electricity from its origin (own or neighbour PV, grid import, or storage inventory of unknown origin) to its destination (load, storage, mobility, export, losses and others), with the grid carbon it carries; rows appear whenever the environment keeps the provenance ledger (`energy_provenance=True`, the default).

Equations and rules: [Energy provenance](kpis_reference.md#energy-provenance).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `energy_provenance_pv_generated{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | PV energy produced by the member, including the part later curtailed; `_business_as_usual` and `_delta_to_business_as_usual` as in the shared rules. |
| `energy_provenance_{pv,grid,unknown}_{load,mobility,grid_export,loss,asset_exit,external_reset,curtailment,stored}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energy of origin PV, grid (including grid import of unknown carbon) or unknown that reached the named destination in this member, counted by the receiving member; `stored` is the inventory still in the member's storage at evaluation, and only PV can be curtailed, so the grid and unknown curtailment rows are always 0. BAU variants as in the shared rules. |
| `energy_provenance_pv_load_{direct,after_storage}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Split of PV reaching the member's load: `direct` did not pass through storage in that interval, and `after_storage` is `max(pv_load - pv_load_direct, 0)`. BAU variants as in the shared rules. |
| `energy_provenance_unknown_input{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energy that entered the ledger with unknown origin: the opening inventory of each storage when the ledger first sees it (including the full stored energy of every EV at connection) and every externally imposed state of charge. BAU variants as in the shared rules. |
| `energy_provenance_{,pv_,grid_}{local_import,local_export}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energy received from (`local_import`) or sent to (`local_export`) other members in the same interval, in total and by origin; these are internal transfers, already counted in the receiving member's destinations. BAU variants as in the shared rules. |
| `energy_provenance_external_import{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Grid import of the member after local sharing, `max(net, 0) - local_import` summed over intervals, including intervals of unknown carbon intensity. BAU variants as in the shared rules. |
| `energy_provenance_external_purchase_emissions{,_business_as_usual,_delta_to_business_as_usual}_kgco2` | building, district | kgCO2 | Emissions of the member's grid import after local sharing, at the member's carbon intensity; intervals with a non-finite intensity add nothing, and exports earn no credit. BAU variants as in the shared rules. |
| `energy_provenance_external_purchase_unknown_carbon{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Part of `external_import` imported in intervals whose carbon intensity is not finite, and therefore missing from the emissions. BAU variants as in the shared rules. |
| `energy_provenance_carbon_{load,mobility,grid_export,loss,asset_exit,external_reset,curtailment,stored}{,_business_as_usual,_delta_to_business_as_usual}_kgco2` | building, district | kgCO2 | Grid carbon carried by the energy that reached the named destination in this member; only grid energy carries carbon, so `carbon_curtailment` is always 0. BAU variants as in the shared rules. |
| `energy_provenance_carbon_unknown_{load,mobility,grid_export,loss,asset_exit,external_reset,curtailment,stored}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energy (not carbon) in the named destination whose carbon is unknown: unknown-origin energy plus grid import of non-finite intensity; it shows how much energy the matching `carbon_*_kgco2` row leaves uncounted. BAU variants as in the shared rules. |
| `energy_provenance_{pv,grid,unknown}_balance_residual{,_business_as_usual,_delta_to_business_as_usual}_kwh` | district | kWh | Closure check per origin: input (`pv_generated`, `external_import` or `unknown_input`) minus the sum of its eight destinations; expected close to 0. District only, because members exchange energy. BAU variants as in the shared rules. |
| `energy_provenance_carbon_balance_residual{,_business_as_usual,_delta_to_business_as_usual}_kgco2` | district | kgCO2 | Carbon closure check: `external_purchase_emissions` minus the sum of the eight `carbon_*` destinations; expected close to 0. BAU variants as in the shared rules. |
| `energy_provenance_pv_useful_{building,with_mobility}{,_business_as_usual,_delta_to_business_as_usual}_ratio` | district | ratio | Share of district PV generation that reached a building load (`building`), or a building load or a departing EV (`with_mobility`); undefined when district PV generation is zero. BAU variants as in the shared rules. |
| `energy_provenance_{bus,storage}_max_residual{,_business_as_usual,_delta_to_business_as_usual}_kwh` | district | kWh | Diagnostics, not measurements of performance: the largest per-interval bus imbalance (`bus`) or gap between the ledger's and the physical stored energy (`storage`) over all members and intervals; expected close to 0. BAU variants as in the shared rules. |

<details>
<summary>All 342 names</summary>

```text
building_energy_provenance_carbon_asset_exit_business_as_usual_kgco2
building_energy_provenance_carbon_asset_exit_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_asset_exit_kgco2
building_energy_provenance_carbon_curtailment_business_as_usual_kgco2
building_energy_provenance_carbon_curtailment_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_curtailment_kgco2
building_energy_provenance_carbon_external_reset_business_as_usual_kgco2
building_energy_provenance_carbon_external_reset_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_external_reset_kgco2
building_energy_provenance_carbon_grid_export_business_as_usual_kgco2
building_energy_provenance_carbon_grid_export_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_grid_export_kgco2
building_energy_provenance_carbon_load_business_as_usual_kgco2
building_energy_provenance_carbon_load_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_load_kgco2
building_energy_provenance_carbon_loss_business_as_usual_kgco2
building_energy_provenance_carbon_loss_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_loss_kgco2
building_energy_provenance_carbon_mobility_business_as_usual_kgco2
building_energy_provenance_carbon_mobility_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_mobility_kgco2
building_energy_provenance_carbon_stored_business_as_usual_kgco2
building_energy_provenance_carbon_stored_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_stored_kgco2
building_energy_provenance_carbon_unknown_asset_exit_business_as_usual_kwh
building_energy_provenance_carbon_unknown_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_asset_exit_kwh
building_energy_provenance_carbon_unknown_curtailment_business_as_usual_kwh
building_energy_provenance_carbon_unknown_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_curtailment_kwh
building_energy_provenance_carbon_unknown_external_reset_business_as_usual_kwh
building_energy_provenance_carbon_unknown_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_external_reset_kwh
building_energy_provenance_carbon_unknown_grid_export_business_as_usual_kwh
building_energy_provenance_carbon_unknown_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_grid_export_kwh
building_energy_provenance_carbon_unknown_load_business_as_usual_kwh
building_energy_provenance_carbon_unknown_load_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_load_kwh
building_energy_provenance_carbon_unknown_loss_business_as_usual_kwh
building_energy_provenance_carbon_unknown_loss_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_loss_kwh
building_energy_provenance_carbon_unknown_mobility_business_as_usual_kwh
building_energy_provenance_carbon_unknown_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_mobility_kwh
building_energy_provenance_carbon_unknown_stored_business_as_usual_kwh
building_energy_provenance_carbon_unknown_stored_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_stored_kwh
building_energy_provenance_external_import_business_as_usual_kwh
building_energy_provenance_external_import_delta_to_business_as_usual_kwh
building_energy_provenance_external_import_kwh
building_energy_provenance_external_purchase_emissions_business_as_usual_kgco2
building_energy_provenance_external_purchase_emissions_delta_to_business_as_usual_kgco2
building_energy_provenance_external_purchase_emissions_kgco2
building_energy_provenance_external_purchase_unknown_carbon_business_as_usual_kwh
building_energy_provenance_external_purchase_unknown_carbon_delta_to_business_as_usual_kwh
building_energy_provenance_external_purchase_unknown_carbon_kwh
building_energy_provenance_grid_asset_exit_business_as_usual_kwh
building_energy_provenance_grid_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_grid_asset_exit_kwh
building_energy_provenance_grid_curtailment_business_as_usual_kwh
building_energy_provenance_grid_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_grid_curtailment_kwh
building_energy_provenance_grid_external_reset_business_as_usual_kwh
building_energy_provenance_grid_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_grid_external_reset_kwh
building_energy_provenance_grid_grid_export_business_as_usual_kwh
building_energy_provenance_grid_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_grid_grid_export_kwh
building_energy_provenance_grid_load_business_as_usual_kwh
building_energy_provenance_grid_load_delta_to_business_as_usual_kwh
building_energy_provenance_grid_load_kwh
building_energy_provenance_grid_local_export_business_as_usual_kwh
building_energy_provenance_grid_local_export_delta_to_business_as_usual_kwh
building_energy_provenance_grid_local_export_kwh
building_energy_provenance_grid_local_import_business_as_usual_kwh
building_energy_provenance_grid_local_import_delta_to_business_as_usual_kwh
building_energy_provenance_grid_local_import_kwh
building_energy_provenance_grid_loss_business_as_usual_kwh
building_energy_provenance_grid_loss_delta_to_business_as_usual_kwh
building_energy_provenance_grid_loss_kwh
building_energy_provenance_grid_mobility_business_as_usual_kwh
building_energy_provenance_grid_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_grid_mobility_kwh
building_energy_provenance_grid_stored_business_as_usual_kwh
building_energy_provenance_grid_stored_delta_to_business_as_usual_kwh
building_energy_provenance_grid_stored_kwh
building_energy_provenance_local_export_business_as_usual_kwh
building_energy_provenance_local_export_delta_to_business_as_usual_kwh
building_energy_provenance_local_export_kwh
building_energy_provenance_local_import_business_as_usual_kwh
building_energy_provenance_local_import_delta_to_business_as_usual_kwh
building_energy_provenance_local_import_kwh
building_energy_provenance_pv_asset_exit_business_as_usual_kwh
building_energy_provenance_pv_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_pv_asset_exit_kwh
building_energy_provenance_pv_curtailment_business_as_usual_kwh
building_energy_provenance_pv_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_pv_curtailment_kwh
building_energy_provenance_pv_external_reset_business_as_usual_kwh
building_energy_provenance_pv_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_pv_external_reset_kwh
building_energy_provenance_pv_generated_business_as_usual_kwh
building_energy_provenance_pv_generated_delta_to_business_as_usual_kwh
building_energy_provenance_pv_generated_kwh
building_energy_provenance_pv_grid_export_business_as_usual_kwh
building_energy_provenance_pv_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_pv_grid_export_kwh
building_energy_provenance_pv_load_after_storage_business_as_usual_kwh
building_energy_provenance_pv_load_after_storage_delta_to_business_as_usual_kwh
building_energy_provenance_pv_load_after_storage_kwh
building_energy_provenance_pv_load_business_as_usual_kwh
building_energy_provenance_pv_load_delta_to_business_as_usual_kwh
building_energy_provenance_pv_load_direct_business_as_usual_kwh
building_energy_provenance_pv_load_direct_delta_to_business_as_usual_kwh
building_energy_provenance_pv_load_direct_kwh
building_energy_provenance_pv_load_kwh
building_energy_provenance_pv_local_export_business_as_usual_kwh
building_energy_provenance_pv_local_export_delta_to_business_as_usual_kwh
building_energy_provenance_pv_local_export_kwh
building_energy_provenance_pv_local_import_business_as_usual_kwh
building_energy_provenance_pv_local_import_delta_to_business_as_usual_kwh
building_energy_provenance_pv_local_import_kwh
building_energy_provenance_pv_loss_business_as_usual_kwh
building_energy_provenance_pv_loss_delta_to_business_as_usual_kwh
building_energy_provenance_pv_loss_kwh
building_energy_provenance_pv_mobility_business_as_usual_kwh
building_energy_provenance_pv_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_pv_mobility_kwh
building_energy_provenance_pv_stored_business_as_usual_kwh
building_energy_provenance_pv_stored_delta_to_business_as_usual_kwh
building_energy_provenance_pv_stored_kwh
building_energy_provenance_unknown_asset_exit_business_as_usual_kwh
building_energy_provenance_unknown_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_asset_exit_kwh
building_energy_provenance_unknown_curtailment_business_as_usual_kwh
building_energy_provenance_unknown_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_curtailment_kwh
building_energy_provenance_unknown_external_reset_business_as_usual_kwh
building_energy_provenance_unknown_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_external_reset_kwh
building_energy_provenance_unknown_grid_export_business_as_usual_kwh
building_energy_provenance_unknown_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_grid_export_kwh
building_energy_provenance_unknown_input_business_as_usual_kwh
building_energy_provenance_unknown_input_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_input_kwh
building_energy_provenance_unknown_load_business_as_usual_kwh
building_energy_provenance_unknown_load_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_load_kwh
building_energy_provenance_unknown_loss_business_as_usual_kwh
building_energy_provenance_unknown_loss_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_loss_kwh
building_energy_provenance_unknown_mobility_business_as_usual_kwh
building_energy_provenance_unknown_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_mobility_kwh
building_energy_provenance_unknown_stored_business_as_usual_kwh
building_energy_provenance_unknown_stored_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_stored_kwh
district_energy_provenance_bus_max_residual_business_as_usual_kwh
district_energy_provenance_bus_max_residual_delta_to_business_as_usual_kwh
district_energy_provenance_bus_max_residual_kwh
district_energy_provenance_carbon_asset_exit_business_as_usual_kgco2
district_energy_provenance_carbon_asset_exit_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_asset_exit_kgco2
district_energy_provenance_carbon_balance_residual_business_as_usual_kgco2
district_energy_provenance_carbon_balance_residual_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_balance_residual_kgco2
district_energy_provenance_carbon_curtailment_business_as_usual_kgco2
district_energy_provenance_carbon_curtailment_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_curtailment_kgco2
district_energy_provenance_carbon_external_reset_business_as_usual_kgco2
district_energy_provenance_carbon_external_reset_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_external_reset_kgco2
district_energy_provenance_carbon_grid_export_business_as_usual_kgco2
district_energy_provenance_carbon_grid_export_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_grid_export_kgco2
district_energy_provenance_carbon_load_business_as_usual_kgco2
district_energy_provenance_carbon_load_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_load_kgco2
district_energy_provenance_carbon_loss_business_as_usual_kgco2
district_energy_provenance_carbon_loss_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_loss_kgco2
district_energy_provenance_carbon_mobility_business_as_usual_kgco2
district_energy_provenance_carbon_mobility_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_mobility_kgco2
district_energy_provenance_carbon_stored_business_as_usual_kgco2
district_energy_provenance_carbon_stored_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_stored_kgco2
district_energy_provenance_carbon_unknown_asset_exit_business_as_usual_kwh
district_energy_provenance_carbon_unknown_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_asset_exit_kwh
district_energy_provenance_carbon_unknown_curtailment_business_as_usual_kwh
district_energy_provenance_carbon_unknown_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_curtailment_kwh
district_energy_provenance_carbon_unknown_external_reset_business_as_usual_kwh
district_energy_provenance_carbon_unknown_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_external_reset_kwh
district_energy_provenance_carbon_unknown_grid_export_business_as_usual_kwh
district_energy_provenance_carbon_unknown_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_grid_export_kwh
district_energy_provenance_carbon_unknown_load_business_as_usual_kwh
district_energy_provenance_carbon_unknown_load_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_load_kwh
district_energy_provenance_carbon_unknown_loss_business_as_usual_kwh
district_energy_provenance_carbon_unknown_loss_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_loss_kwh
district_energy_provenance_carbon_unknown_mobility_business_as_usual_kwh
district_energy_provenance_carbon_unknown_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_mobility_kwh
district_energy_provenance_carbon_unknown_stored_business_as_usual_kwh
district_energy_provenance_carbon_unknown_stored_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_stored_kwh
district_energy_provenance_external_import_business_as_usual_kwh
district_energy_provenance_external_import_delta_to_business_as_usual_kwh
district_energy_provenance_external_import_kwh
district_energy_provenance_external_purchase_emissions_business_as_usual_kgco2
district_energy_provenance_external_purchase_emissions_delta_to_business_as_usual_kgco2
district_energy_provenance_external_purchase_emissions_kgco2
district_energy_provenance_external_purchase_unknown_carbon_business_as_usual_kwh
district_energy_provenance_external_purchase_unknown_carbon_delta_to_business_as_usual_kwh
district_energy_provenance_external_purchase_unknown_carbon_kwh
district_energy_provenance_grid_asset_exit_business_as_usual_kwh
district_energy_provenance_grid_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_grid_asset_exit_kwh
district_energy_provenance_grid_balance_residual_business_as_usual_kwh
district_energy_provenance_grid_balance_residual_delta_to_business_as_usual_kwh
district_energy_provenance_grid_balance_residual_kwh
district_energy_provenance_grid_curtailment_business_as_usual_kwh
district_energy_provenance_grid_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_grid_curtailment_kwh
district_energy_provenance_grid_external_reset_business_as_usual_kwh
district_energy_provenance_grid_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_grid_external_reset_kwh
district_energy_provenance_grid_grid_export_business_as_usual_kwh
district_energy_provenance_grid_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_grid_grid_export_kwh
district_energy_provenance_grid_load_business_as_usual_kwh
district_energy_provenance_grid_load_delta_to_business_as_usual_kwh
district_energy_provenance_grid_load_kwh
district_energy_provenance_grid_local_export_business_as_usual_kwh
district_energy_provenance_grid_local_export_delta_to_business_as_usual_kwh
district_energy_provenance_grid_local_export_kwh
district_energy_provenance_grid_local_import_business_as_usual_kwh
district_energy_provenance_grid_local_import_delta_to_business_as_usual_kwh
district_energy_provenance_grid_local_import_kwh
district_energy_provenance_grid_loss_business_as_usual_kwh
district_energy_provenance_grid_loss_delta_to_business_as_usual_kwh
district_energy_provenance_grid_loss_kwh
district_energy_provenance_grid_mobility_business_as_usual_kwh
district_energy_provenance_grid_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_grid_mobility_kwh
district_energy_provenance_grid_stored_business_as_usual_kwh
district_energy_provenance_grid_stored_delta_to_business_as_usual_kwh
district_energy_provenance_grid_stored_kwh
district_energy_provenance_local_export_business_as_usual_kwh
district_energy_provenance_local_export_delta_to_business_as_usual_kwh
district_energy_provenance_local_export_kwh
district_energy_provenance_local_import_business_as_usual_kwh
district_energy_provenance_local_import_delta_to_business_as_usual_kwh
district_energy_provenance_local_import_kwh
district_energy_provenance_pv_asset_exit_business_as_usual_kwh
district_energy_provenance_pv_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_pv_asset_exit_kwh
district_energy_provenance_pv_balance_residual_business_as_usual_kwh
district_energy_provenance_pv_balance_residual_delta_to_business_as_usual_kwh
district_energy_provenance_pv_balance_residual_kwh
district_energy_provenance_pv_curtailment_business_as_usual_kwh
district_energy_provenance_pv_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_pv_curtailment_kwh
district_energy_provenance_pv_external_reset_business_as_usual_kwh
district_energy_provenance_pv_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_pv_external_reset_kwh
district_energy_provenance_pv_generated_business_as_usual_kwh
district_energy_provenance_pv_generated_delta_to_business_as_usual_kwh
district_energy_provenance_pv_generated_kwh
district_energy_provenance_pv_grid_export_business_as_usual_kwh
district_energy_provenance_pv_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_pv_grid_export_kwh
district_energy_provenance_pv_load_after_storage_business_as_usual_kwh
district_energy_provenance_pv_load_after_storage_delta_to_business_as_usual_kwh
district_energy_provenance_pv_load_after_storage_kwh
district_energy_provenance_pv_load_business_as_usual_kwh
district_energy_provenance_pv_load_delta_to_business_as_usual_kwh
district_energy_provenance_pv_load_direct_business_as_usual_kwh
district_energy_provenance_pv_load_direct_delta_to_business_as_usual_kwh
district_energy_provenance_pv_load_direct_kwh
district_energy_provenance_pv_load_kwh
district_energy_provenance_pv_local_export_business_as_usual_kwh
district_energy_provenance_pv_local_export_delta_to_business_as_usual_kwh
district_energy_provenance_pv_local_export_kwh
district_energy_provenance_pv_local_import_business_as_usual_kwh
district_energy_provenance_pv_local_import_delta_to_business_as_usual_kwh
district_energy_provenance_pv_local_import_kwh
district_energy_provenance_pv_loss_business_as_usual_kwh
district_energy_provenance_pv_loss_delta_to_business_as_usual_kwh
district_energy_provenance_pv_loss_kwh
district_energy_provenance_pv_mobility_business_as_usual_kwh
district_energy_provenance_pv_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_pv_mobility_kwh
district_energy_provenance_pv_stored_business_as_usual_kwh
district_energy_provenance_pv_stored_delta_to_business_as_usual_kwh
district_energy_provenance_pv_stored_kwh
district_energy_provenance_pv_useful_building_business_as_usual_ratio
district_energy_provenance_pv_useful_building_delta_to_business_as_usual_ratio
district_energy_provenance_pv_useful_building_ratio
district_energy_provenance_pv_useful_with_mobility_business_as_usual_ratio
district_energy_provenance_pv_useful_with_mobility_delta_to_business_as_usual_ratio
district_energy_provenance_pv_useful_with_mobility_ratio
district_energy_provenance_storage_max_residual_business_as_usual_kwh
district_energy_provenance_storage_max_residual_delta_to_business_as_usual_kwh
district_energy_provenance_storage_max_residual_kwh
district_energy_provenance_unknown_asset_exit_business_as_usual_kwh
district_energy_provenance_unknown_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_asset_exit_kwh
district_energy_provenance_unknown_balance_residual_business_as_usual_kwh
district_energy_provenance_unknown_balance_residual_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_balance_residual_kwh
district_energy_provenance_unknown_curtailment_business_as_usual_kwh
district_energy_provenance_unknown_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_curtailment_kwh
district_energy_provenance_unknown_external_reset_business_as_usual_kwh
district_energy_provenance_unknown_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_external_reset_kwh
district_energy_provenance_unknown_grid_export_business_as_usual_kwh
district_energy_provenance_unknown_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_grid_export_kwh
district_energy_provenance_unknown_input_business_as_usual_kwh
district_energy_provenance_unknown_input_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_input_kwh
district_energy_provenance_unknown_load_business_as_usual_kwh
district_energy_provenance_unknown_load_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_load_kwh
district_energy_provenance_unknown_loss_business_as_usual_kwh
district_energy_provenance_unknown_loss_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_loss_kwh
district_energy_provenance_unknown_mobility_business_as_usual_kwh
district_energy_provenance_unknown_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_mobility_kwh
district_energy_provenance_unknown_stored_business_as_usual_kwh
district_energy_provenance_unknown_stored_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_stored_kwh
```

</details>

## Dynamic topology

Lifecycle bookkeeping for members of a dynamic topology; the row appears only with `topology_mode='dynamic'`.

Equations and rules: [Dynamic topology](kpis_reference.md#dynamic-topology).

| Names | Levels | Unit | Meaning |
|---|---|---|---|
| `topology_lifecycle_presence` | building | none | Placeholder, always NaN: one row per lifecycle member with no other building row (never active in the episode), so its lifecycle columns appear. It has no level prefix because it is added after the KPI naming step. |

<details>
<summary>All 1 names</summary>

```text
topology_lifecycle_presence
```

</details>
