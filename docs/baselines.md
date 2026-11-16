# Baselines

A baseline makes the reference behind a result explicit. CityLearn uses an
operational business-as-usual controller for controller comparisons, a
conventional counterfactual for legacy normalized KPIs, and a pre-event power
reference for demand-response settlement. They answer different questions.

## Business as usual: the operational reference

`BusinessAsUsualAgent` represents day-to-day equipment operation without
learning, forecasts or price optimization. It runs the configured community,
including its demand, generation, devices, schedules and electrical constraints.
It is not a scenario with all equipment switched off.

| Equipment or service | BAU behaviour |
|---|---|
| EVs | Requests maximum charging power as soon as an EV is connected, until it reaches the user's requested departure SOC. The last command is limited to the remaining energy gap. If that command would fall below the charger's minimum power, the EV stops slightly below the target rather than overshooting it. Ignores deadlines, prices and solar forecasts and never requests V2G. Electrical limits share the available power proportionally between simultaneous requests. |
| Stationary batteries | Charges from local PV surplus and discharges to serve local import (self-consumption). EV charging is considered first, so the battery does not discharge into an EV that is already full. |
| Flexible appliances | Requests the next pending cycle at its first feasible start opportunity. |
| Electrical connection | The simulator applies the configured total and per-phase import/export limits; equipment and simulator constraints determine the applied energy. |
| Local sharing | The scenario's settlement rules value the resulting trajectory. BAU does not optimize the allocation or local-market price. |
| Demand response | Runs under the scenario, but has no policy that optimizes an activation target, payment or penalty. |
| Other active actions | Requests zero, clipped to the action bounds. This is not a dedicated HVAC, thermal-storage or escalator policy; the effect of zero follows each device's action contract. |

All baselines in `citylearn.agents.baseline` read the same named, unnormalized
entity observations (current state, schedules and the simulator's published
forecasts). They work with the flat and the entity interface and return flat
action vectors in `env.action_names` order.

`NormalPolicy` and `NormalTargetPolicy` are other names of `BusinessAsUsualAgent`.

### Default parameters

Keyword arguments override the policy hyperparameters. Unknown names raise a
`ValueError`. The main BAU parameters are:

| Parameter | Default | Meaning |
|---|---:|---|
| `ev_normal_charge_rate` | `1.0` | EV charge command while below the target, as a fraction of maximum charger power. |
| `storage_min_soc` | `0.20` | Stop requesting battery discharge below this SOC. |
| `storage_max_soc` | `0.90` | Stop requesting battery charge above this SOC. |
| `storage_charge_rate` | `1.0` | Maximum battery charge command for PV surplus. |
| `storage_discharge_rate` | `1.0` | Maximum battery discharge command for local import. |
| `pv_surplus_threshold_kw` | `0.05` | PV surplus that triggers battery charging. |
| `normal_storage_discharge_import_threshold_kw` | `0.05` | Local import that triggers battery discharge. |
| `deferrable_start_action` | `1.0` | Start command for a ready flexible appliance. |

The storage thresholds decide whether to request charge or discharge; they are
not hard SOC constraints. Physical battery limits are applied by the simulator.

See the [first simulation](https://www.citylearn.net/quickstart.html) for a
complete run using these defaults. A customized BAU is created explicitly:

```python
from citylearn.agents.baseline import BusinessAsUsualAgent

agent = BusinessAsUsualAgent(env, storage_min_soc=0.10, storage_max_soc=0.95)
```

Label customized runs with their parameter values. The automatic comparison
described below instantiates the native default BAU; it does not inherit
parameters from a separate agent created by the user.

## Rule-based baselines

Three rule-based controllers give progressively better-informed references
between BAU and a learned controller. Run them on the same members, files,
windows, seeds and market conditions as the candidate.

| Agent | Policy |
|---|---|
| `RBCBasicPolicy` | Uses the current price and service urgency for EVs and flexible appliances. EVs receive the minimum charge that meets their departure target, raised when the price is cheap. Appliances start when urgent or cheap. The battery performs self-consumption. |
| `RBCSmartPolicy` | Uses price forecasts and the forecast local PV surplus to schedule EV charging and appliance starts. The battery combines self-consumption, price arbitrage and a service reserve. It uses only building-local and public observations. |
| `RBCCommunityPolicy` | Adds energy shareable between community members. When the community market is enabled, the batteries can support expensive periods once community import reaches `community_import_threshold_kw` (15 kW by default). This value triggers an action; the observed peak can exceed it. Without a community market it uses the same local dispatch as `RBCSmartPolicy`. |

`RBCBasicPolicy` compares the current price with fixed thresholds,
`basic_cheap_price_eur_kwh=0.0765` and `basic_expensive_price_eur_kwh=0.1078`.
They are the terciles of the 2023 Portuguese day-ahead price used to calibrate
the policy. For another tariff, set both thresholds in the dataset's price unit,
or use `basic_price_policy='forecast_relative'` to compare the current price
with the price forecast:

```python
from citylearn.agents.baseline import RBCBasicPolicy, RBCCommunityPolicy

basic = RBCBasicPolicy(env, basic_cheap_price_eur_kwh=0.20, basic_expensive_price_eur_kwh=0.35)
community = RBCCommunityPolicy(env, community_import_threshold_kw=10.0)
```

These policies are ported from the Soft-CPS Algorithms baselines (commit
`725a72a`). With the same defaults and observations they request the same
actions at every step. `agent.comparison_identity()` records the class, the
definition version and the resolved parameters for experiment manifests.

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
Choose the same evaluation condition when comparing controllers. During a
simulated power outage the counterfactual, like the controlled run, exchanges
no energy with the grid: its net, cost and emission values are zero at those
time steps.

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

From 3.4.0, BAU uses `immediate-user-target-v1`: it charges EVs only up to
the requested departure SOC, where 3.1–3.3 charged them to 100%. BAU references
computed with earlier versions are not comparable with 3.4.0 results; rerun both
the controller and its reference.
