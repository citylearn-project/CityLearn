# Baselines

A baseline makes the reference behind a result explicit. CityLearn uses an
operational business-as-usual controller for controller comparisons, a
conventional counterfactual for legacy normalized KPIs, and a pre-event power
reference for demand-response settlement. They answer different questions.

## Business as usual: the operational reference

`BusinessAsUsualAgent` represents day-to-day equipment operation without
learning or price optimization. It runs the configured community, including
its demand, generation, devices, schedules and electrical constraints.
It is not a scenario with all equipment switched off.

| Equipment or service | BAU behaviour |
|---|---|
| EVs | Requests maximum charging power immediately while connected, until 100% SOC. It ignores departure targets, deadlines, prices and solar forecasts, and never requests V2G. Electrical limits share available power proportionally; equal requests receive equal shares. |
| Stationary batteries | Charges from PV surplus and discharges to serve local demand, including prospective EV and appliance demand. SOC thresholds and a power deadband control when this rule acts. |
| Flexible appliances | Requests the next pending cycle at its first feasible start opportunity. |
| Electrical connection | Scales EV and battery requests against configured total and per-phase import/export limits. Equipment and simulator constraints still determine the applied energy. |
| Local sharing | The scenario's settlement rules value the resulting trajectory. BAU does not optimize the allocation or local-market price. |
| Demand response | Runs under the scenario, but has no policy that optimizes an activation target, payment or penalty. |
| Other active actions | Requests zero, clipped to the action bounds. This is not a dedicated HVAC, thermal-storage or escalator policy; the effect of zero follows each device's action contract. |

The controller uses current equipment state and schedule information from the
environment. It does not train a model, forecast prices, perform tariff
arbitrage, optimize a planning horizon or coordinate communities.

### Default parameters

| Parameter | Default | Meaning |
|---|---:|---|
| `ev_target_soc` | `1.0` | EV charging target/cap, as a SOC ratio. |
| `ev_follow_required_soc` | `False` | With the default, charge towards full SOC rather than a lower requested departure target. |
| `ev_service_margin_rate` | `0.02` | Compatibility spelling for the fixed legacy default; target scheduling uses an RBC. |
| `ev_service_floor_rate` | `0.0` | Compatibility spelling for the fixed legacy default; equipment minimum power still applies. |
| `storage_min_soc` | `0.20` | Stop requesting discharge below this SOC threshold. |
| `storage_max_soc` | `0.90` | Stop requesting charge above this SOC threshold. |
| `storage_deadband_kw` | `0.05` | Ignore small net-load differences around zero. |
| `deferrable_start_action` | `1.0` | Start command for a ready flexible appliance. |

The storage thresholds decide whether to request charge/discharge; they are
not additional hard SOC constraints on the final timestep. Physical battery
limits are applied by the simulator.

See the [first simulation](https://www.citylearn.net/quickstart.html) for a
complete run using these defaults. A different operational policy can be
created explicitly:

```python
from citylearn.agents.baseline import BusinessAsUsualAgent

agent = BusinessAsUsualAgent(
    env,
    ev_follow_required_soc=True,
    storage_min_soc=0.20,
    storage_max_soc=0.90,
)
```

Label customized runs with their parameter values. The automatic comparison
described below instantiates the native default BAU; it does not inherit
parameters from a separate agent created by the user.

### Automatic BAU evaluation

`env.evaluate_v2()` runs or reuses a separate BAU simulation up to the current
evaluation timestep. That simulation is rebuilt from the source schema, selected
members/EVs, episode window, timestep, topology mode and seed. It also re-applies
the environment's constructor overrides `simulate_power_outage`,
`solar_generation`, `active_actions`/`inactive_actions` and
`active_observations`/`inactive_observations`, so the reference simulates the
same equipment, generation and outages. It loads the buildings in the evaluated
environment's order, so per-building override lists reach the same buildings
when `buildings=[1, 0]` selects them in another order than the schema. It uses
entity mode when dynamic topology or demand response requires it. Rendering is
disabled for this internal comparison.

The reference reproduces what the schema and these constructor arguments define.
It cannot follow buildings, devices or chargers changed after loading, for
example a new charger `max_charging_power` or building `simulate_power_outage`.
Before it runs, it is compared with the evaluated environment as captured at its
last `reset()`: the building order, each building's `simulate_power_outage` and
active actions, the sizes and parameters of every device (heat pumps, heaters,
storage tanks, PV, batteries, chargers, appliances and EV batteries), and the
capacity and initial energy of batteries and EVs. A difference raises a
`ValueError` that names the setting; evaluate with
`include_business_as_usual=False` in that case. A change made after `reset()`
is not detected: the comparison covers the configuration captured at reset.

For stochastic power outages, CityLearn uses the model's explicit
`random_seed` when provided. Otherwise the built-in models derive their
seed from the environment seed, episode window and building name. The
controller and its native BAU reference therefore face the same outages
when they use the same model configuration.

Results are cached for the current episode and timestep. The output adds
`business_as_usual` values, `delta_to_business_as_usual` differences and
`ratio_to_business_as_usual` ratios for supported metrics:

```python
kpis = env.evaluate_v2()
reference_rows = kpis.loc[
    (kpis["level"] == "district")
    & kpis["cost_function"].str.contains("business_as_usual"),
    ["cost_function", "value"],
]
print(reference_rows.to_string(index=False))
```

Use `include_business_as_usual=False` to evaluate only the current run and
conventional counterfactual. `env.run_business_as_usual_baseline(force=True)`
recomputes the cached BAU reference.

## Conventional evaluation counterfactual

Names containing `baseline` rather than `business_as_usual` refer to the
evaluation conditions selected through `baseline_condition`. The default uses
the simulator's counterfactual series without storage and, for dynamic building
models, without partial-load control, while retaining PV.

This is a counterfactual calculation, not a second `BusinessAsUsualAgent` run.
`EvaluationCondition` also exposes alternatives, including removing PV.
Choose the same evaluation condition when comparing controllers.

With the community market enabled, both the control and the counterfactual
costs are settled with the scenario's market rules, in the legacy, v2 and
equity-audit KPIs alike. Savings from local trading are then not credited to
the controller.

For example, `district_cost_ratio_to_baseline_total_ratio` and
`district_cost_ratio_to_business_as_usual_total_ratio` have different
denominators. A value below one means lower cost than the named reference.

## Demand-response baseline

DR delivery is measured against mean net power in the configured pre-event
history window. The reference is frozen for each request, then used to measure
movement in the requested direction during its activation.

This reference is neither the conventional counterfactual nor a BAU rollout.
Configure `demand_response.baseline_window_seconds` and inspect baseline
validity alongside requested, delivered and credited response. See the
[DR schema](schema_reference.md#demand-response) and
[DR KPIs](kpis_reference.md#demand-response-kpis).

## A reference run selected in the UI

When comparing imported runs, the UI labels the first included simulation
in its imported list as **Compare baseline**. That is a user-selected run; it need not be the native
BAU. The `business_as_usual` columns inside each exported KPI table retain
their simulator-defined meaning.

Read [the scorecard](scorecard.md) for matched-controller comparisons and
[the UI guide](https://www.citylearn.net/ui.html) for the visual workflow.

From 3.1, BAU uses `immediate-full-charge-v1`. Explicit departure-target scheduling
settings belong to `RBCBasicPolicy` or its variants; configure those instead of BAU.
The public BAU parameter names and positional signature remain available, with
the fixed EV defaults shown above. Historical BAU results may differ after corrected
charging and shared electrical limits; compare experiments with matching versions.
