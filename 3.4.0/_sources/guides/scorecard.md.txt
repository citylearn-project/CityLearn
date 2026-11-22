# How to read the scorecard

A scorecard puts a small set of energy, cost, service and electrical indicators
side by side. It is a view of `evaluate_v2()`, not a new reward or a single
weighted score. Keep the full KPI export so each headline result can be traced.

## Start with these questions

| Question | Metric | How to read it |
|---|---|---|
| What did operation cost? | Total cost, BAU cost and delta | Lower cost is favourable when the same services and tariff rules apply. A negative control-minus-BAU delta is a saving. |
| Were EVs ready to leave? | Minimum acceptable departure service | Higher is better; the feasible variant evaluates departures whose service threshold was reachable. |
| How accurately was the EV target followed? | Symmetric within-tolerance departure ratio | Higher means closer target tracking. Charging above the band can meet minimum service but fail this accuracy measure. |
| Were electrical limits respected? | Residual violation energy | Lower is better. This measures excess after constraint handling. |
| How much did constraints intervene? | Requested-pressure energy | Excess associated with the unprojected request; it is not the same as an applied-power violation. |
| How much storage activity was used? | Battery throughput and V2G export | Report with costs, service and degradation; higher or lower is not universally better. |
| How much solar energy stayed local? | Solar self-consumption ratio | Higher means more PV-backed generation consumed locally. Read alongside total generation and imports. |
| How much energy crossed the grid boundary? | Import, export and net exchange | Read all three: net exchange alone can hide large imports and exports. |
| How demanding was the import profile? | Peak and load-factor-penalty ratios to BAU | For these non-negative penalty/peak ratios, below 1 is lower than BAU and above 1 is higher. |

The simulator defines a default selection for both building and district rows.
The [exact default names](https://www.citylearn.net/guides/scorecard_kpi_names.html)
are generated from that selection when the documentation is built.

## Build a compact scorecard

After the simulation loop, select meaningful rows from the returned table:

```python
kpis = env.evaluate_v2()
selected = [
    "district_cost_total_control_eur",
    "district_cost_total_business_as_usual_eur",
    "district_energy_grid_total_import_control_kwh",
    "district_ev_performance_departure_min_acceptable_feasible_ratio",
    "district_ev_performance_departure_within_tolerance_feasible_ratio",
    "district_electrical_service_phase_violations_energy_total_kwh",
    "district_electrical_service_phase_requested_pressure_energy_total_kwh",
]
scorecard = kpis.loc[
    (kpis["level"] == "district") & kpis["cost_function"].isin(selected),
    ["cost_function", "value"],
]
print(scorecard.to_string(index=False))
scorecard.to_csv("scorecard.csv", index=False)
```

To compare multiple controllers, run the same scenario, window and service
settings for each one, label their KPI tables, and pivot `cost_function` against
controller name. Use the same random seeds for matched stochastic scenarios.
Keep missing/not-applicable values as missing, not as zero.

## Two different baselines

The [Baselines guide](baselines.md) explains the native BAU policy, its default
parameters and the separate references used for evaluation and DR settlement.

Names containing `baseline` refer to the configured conventional evaluation
counterfactual, normally without storage and partial-load control, with PV
retained. This uses the simulator's counterfactual series.

Names containing `business_as_usual` refer to a separate native BAU rollout
under the scenario and episode conditions. The BAU agent charges EVs toward full
charge by default, starts ready flexible loads and operates stationary storage
for PV self-consumption. `evaluate_v2()` runs or reuses that comparison unless
`include_business_as_usual=False`.

Do not mix `ratio_to_baseline` and `ratio_to_business_as_usual` columns in a
comparison without identifying the reference. A ratio is dimensionless.
For a zero denominator the safe division rule returns 1 when both values are
effectively zero, and a missing value when the numerator is non-zero.

## EV service versus target accuracy

At a target SOC of 80% and tolerance of 5 percentage points:

- 76% satisfies minimum service and lies within the symmetric target band.
- 90% satisfies minimum service but is outside that band.
- 70% satisfies neither.

`minimum_acceptable` uses the lower service threshold; `within_tolerance` uses
both the lower and upper bounds. Feasible variants restrict the population to
departures where the relevant threshold was physically reachable. Report the
departure counts and feasibility counts together with these ratios.

## Extend the scorecard for your experiment

The REC application comparisons also use emissions, flexible-load completion,
residual import/export after local exchange and settlement savings. These
complement the default selection:

| Indicator | KPI name or calculation |
|---|---|
| Emissions | `district_emissions_total_control_kgco2` |
| Flexible-load service | `district_deferrable_appliance_service_service_level_ratio` |
| Import after local sharing | `district_energy_grid_community_market_grid_import_after_local_total_kwh` |
| Export after local sharing | `district_energy_grid_community_market_grid_export_after_local_total_kwh` |
| Settlement savings | `district_cost_community_market_savings_total_eur` |
| Peak relative to BAU | `district_energy_grid_shape_quality_peak_all_time_average_to_business_as_usual_ratio` |

An absolute peak in kW can be calculated from the recorded step energy divided
by the timestep duration in hours. Do not label a normalized peak ratio as kW.
For DR experiments add request, delivery, compliance, shortfall and net revenue;
for thermal studies add comfort; for failure studies add the robustness counters.

Use the [KPI reference](kpis_reference.md) for units and definitions, the
[naming catalogue](KPI_V2_TREE.md) for further names and the
[UI guide](https://www.citylearn.net/ui.html) for visual comparisons.
