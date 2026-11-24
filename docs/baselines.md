# Baselines

A baseline makes the reference behind a result explicit. CityLearn uses an
operational business-as-usual controller for controller comparisons, a
conventional counterfactual for legacy normalized KPIs, and a pre-event power
reference for demand-response settlement. They answer different questions.

Portuguese version: [pt/baselines.md](pt/baselines.md).

## Business as usual: the operational reference

`BusinessAsUsualAgent` represents day-to-day equipment operation without
learning, forecasts or price optimization. It runs the configured community,
including its demand, generation, devices, schedules and electrical constraints.
It is not a scenario with all equipment switched off.

| Equipment or service | BAU behaviour |
|---|---|
| EVs | Requests maximum charging power as soon as an EV is connected, until 100% SOC by default, or until the user's requested departure SOC (see below). Ignores deadlines, prices and solar forecasts and never requests V2G. Electrical limits share the available power proportionally between simultaneous requests. |
| Stationary batteries | Requests charging from estimated local PV surplus and discharging to cover estimated local demand. The dispatch budget accounts for EV charging and appliance starts before the stationary battery. |
| Flexible appliances | Requests the next pending cycle at its first feasible start opportunity. |
| Electrical connection | The simulator applies the configured total and per-phase import/export limits; equipment and simulator constraints determine the applied energy. |
| Local sharing | The scenario's settlement rules value the resulting trajectory. BAU does not optimize the allocation or local-market price. |
| Demand response | Runs under the scenario, but has no policy that optimizes an activation target, payment or penalty. |
| HVAC (`heating_device`, `cooling_device`, `cooling_or_heating_device`) | With `baseline_version` 1 or 2 (default): requests zero, so in buildings with temperature dynamics the BAU neither heats nor cools. With `baseline_version=3`: requests the action that delivers the dataset's own heating or cooling demand at each step (see [HVAC and the baseline version](#hvac-and-the-baseline-version)). |
| Other active actions | Requests zero, clipped to the action bounds. This is not a dedicated thermal-storage or escalator policy; the effect of zero follows each device's action contract. |

### Choosing the BAU charging target

`BusinessAsUsualAgent` has two EV charging targets:

| `ev_charge_target` | Definition | EV behaviour |
|---|---|---|
| `'full'` (default) | `immediate-full-charge-v4` | Charges to 100%, as the BAU of CityLearn 3.1–3.3. |
| `'requested'` | `immediate-user-target-v3` | Charges up to the user's requested departure SOC. The last command is limited to the remaining energy gap; if that command would fall below the charger's minimum power, the EV stops slightly below the target rather than overshooting it. Its difference from the default excludes the extra energy delivered above the requested SOC. |

Everything else is the same. Select the BAU used as the KPI reference by
`evaluate_v2()` with the environment setting
`business_as_usual_ev_charge_target`, as a constructor argument or a schema key:

```python
env = CityLearnEnv(schema, business_as_usual_ev_charge_target='requested')
agent = BusinessAsUsualAgent(env, ev_charge_target='requested')
```

The exported metadata records the selected definition. Compare results only
against references with the same definition.

All baselines in `citylearn.agents.baseline` read the same named, unnormalized
entity observations (current state, schedules and the simulator's published
forecasts). They work with the flat and the entity interface and return flat
action vectors in `env.action_names` order.

With [robustness](robustness_reference.md) observation events, a baseline run as
a controller reads the corrupted observations under both interfaces and takes the
same actions. Under the flat interface the env corrupts only the flat vectors, so
`predict(observations)` applies the step's events to the entity observations the
baseline reads, as the entity interface does. `predict([])`, which the native BAU
reference of `evaluate_v2()` uses, reads them uncorrupted.

### HVAC and the baseline version

In the datasets whose buildings have temperature dynamics (an LSTM model), the
HVAC is an action: `heating_device`, `cooling_device` or
`cooling_or_heating_device`, the fraction of the device's nominal power made
available. The bundled datasets with an active HVAC action are
`quebec_neighborhood_with_demand_response_set_points`,
`quebec_neighborhood_without_demand_response_set_points`,
`tx_travis_county_neighborhood`, `vt_chittenden_county_neighborhood`,
`ca_alameda_county_neighborhood`, `baeda_3dem` and the
`citylearn_challenge_2023_*` datasets.

Up to `baseline_version=2` the BAU requests zero for those actions, so once the
LSTM warm-up ends its buildings are neither heated nor cooled: indoor
temperatures drift away from the set points and every `*_business_as_usual`
row compares the controller with unheated (or uncooled) houses
([#362](https://github.com/citylearn-project/CityLearn/issues/362)).

`baseline_version=3` makes the BAU run the HVAC as a building without
optimisation does. At each step it requests the action that delivers the
dataset's own heating or cooling demand, the as-simulated `heating_demand` and
`cooling_demand` of the building file (the energy simulation's
`*_demand_without_control` series):

    action = device input energy for the demand / (nominal power × dataset step in hours)

clipped to the action bounds. The device limits apply as for any other action:
the nominal power, the heat pump COP at the outdoor temperature and, during an
outage, the local supply. A service is used only in the steps whose `hvac_mode`
allows it; with `cooling_or_heating_device` the larger of the two demands sets
the sign. The BAU does not pre-heat, pre-cool, follow prices or use the thermal
storage, which still receives zero. Everything else (EVs, battery, appliances)
is the BAU of version 2, and the KPI baseline (`*_baseline_*` rows) is also the
one of version 2.

| `baseline_version` | KPI baseline | BAU HVAC | BAU definition |
|---|---|---|---|
| `1` | 3.6.0: no EV charging added back | zero | `immediate-full-charge-v4` |
| `2` (default) | EV charging of the `'full'` BAU added back | zero | `immediate-full-charge-v4` |
| `3` (opt-in) | as `2` | delivers the dataset heating and cooling demand | `immediate-full-charge-v4+hvac-dataset-demand-v1` |

(With `business_as_usual_ev_charge_target='requested'` the definition starts
with `immediate-user-target-v3` instead.)

Use version 3 when you compare controllers with the BAU on a dataset with HVAC
actions and want the BAU to keep the houses heated and cooled as the dataset
did; the `*_business_as_usual` rows and the `*_delta_to_business_as_usual_*` and
`*_ratio_to_business_as_usual_*` values change on those datasets. On datasets
without HVAC actions version 3 gives exactly the results of version 2. Version 2
stays the default so that existing results do not change; comparisons report
runs with different baseline versions as incompatible.

```python
env = CityLearnEnv('quebec_neighborhood_without_demand_response_set_points', baseline_version=3)
agent = BusinessAsUsualAgent(env)  # hvac='dataset_demand', from the env
```

`BusinessAsUsualAgent(env, hvac=...)` overrides the environment for that agent:
`'off'` sends zero, `'dataset_demand'` delivers the dataset demand. The native
BAU of `evaluate_v2()` always follows the environment's `baseline_version`.

**The rule-based baselines run the HVAC the same way.** `RBCBasicPolicy`,
`RBCSmartPolicy` and `RBCCommunityPolicy` deliver the dataset heating and
cooling demand with the same rule as the version 3 BAU, whatever the
`baseline_version` (see [HVAC of the rule-based baselines](#hvac-of-the-rule-based-baselines)),
so under version 3 their ratios to the BAU compare houses that are heated and
cooled alike. Under the default version 2 the BAU does not heat or cool, so
their ratios to the BAU compare heated houses with unheated ones: use version 3
on these datasets. `ZeroActionAgent` still sends zero, and so does any controller of
your own that does not drive the HVAC: under version 3 its
`*_ratio_to_business_as_usual_*` values look much better only because the BAU
pays for heating and cooling and it does not. Read the ratios to the BAU together
with the comfort KPIs (`*_comfort_resilience_discomfort_*`). `evaluate_v2()` has
no `*_business_as_usual` comfort rows, so to see the BAU comfort, run
`BusinessAsUsualAgent` as the controller and read its comfort KPIs.

### Known limits

The BAU estimates the battery's starting dispatch budget using the observed
non-shiftable demand, PV and already-running appliance load for the step being
planned. If a required input is unavailable, it uses the existing estimate
based on settled observations. Thermal device electricity is determined as the
step is applied. Using the previous thermal load as current demand would
introduce another time lag. Actual PV surplus can therefore be smaller than
the estimate on a step with thermal demand, and a charge request can increase
grid import. The simulator still enforces the configured electrical limits.

The BAU battery serves only the EV power the
EV can still accept: the `available_charge_power_kw` observation of the
`entity_core_electrical` bundle, or, without that bundle, an estimate from the
observed SOC, battery capacity, charger power and charger efficiency and the
step length, computed as the simulator computes that observation. Neither
includes the EV battery's capacity-power curve, so at steps of a few seconds
near 100% SOC the battery can still discharge more than the EV takes. The
estimate also omits the electrical-service import limit, which the bundle
includes, and capacity fade: under physics version 2 the observation stops at
the EV battery's degraded capacity, where charging stops, but without the bundle
no observation shows the fade, so the estimate stops at the nominal capacity and
can reserve power for a faded EV that is already full. The rule-based baselines
reserve the EV power they command.

Without that bundle the baselines also do not observe the building's import and
export, so they take PV generation above the observed load as the surplus the
battery may store. Export alone is not counted as surplus, because it can come
from a battery discharge that overshot the load in the last step; counting it
made the battery recharge from the grid in the next step.

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
| `RBCCommunityPolicy` | Adds energy shareable between community members. When the community market is enabled, the batteries can support expensive periods once community import reaches `community_import_threshold_kw` (15 kW by default). This value triggers an action; the observed peak can exceed it. Without a community market it shares no energy and follows Smart's economic rules, but, unlike Smart, it is not restricted to building-local observations. |

### HVAC of the rule-based baselines

The engines dispatch the batteries, EV chargers and flexible appliances. The
HVAC actions (`heating_device`, `cooling_device`, `cooling_or_heating_device`)
follow `hvac`:

| `hvac` | HVAC actions |
|---|---|
| `'dataset_demand'` (default) | Deliver the dataset's own heating and cooling demand at each step, with the rule of the version 3 BAU (see [HVAC and the baseline version](#hvac-and-the-baseline-version)): a thermostat that meets the load, without optimisation. |
| `'off'` | Zero, as before. On datasets with temperature dynamics the houses are neither heated nor cooled. |

On datasets without HVAC actions both give the same results, bit for bit, and
the same `comparison_identity()`. On datasets with HVAC actions the identity
records `hvac='dataset_demand'` and the definition version gets the suffix
`+hvac-dataset-demand-v1`, so these runs are not mixed with runs from earlier
releases. Thermal storage still receives zero.

On Quebec (`quebec_neighborhood_without_demand_response_set_points`, steps
0–335), the three rule-based baselines heat the houses as the version 3 BAU
does. The mean indoor temperature is 20.6 °C instead of 3.4 °C, the minimum
17.2 °C instead of −12.8 °C, and
`district_comfort_resilience_discomfort_overall_ratio` goes from 0.183 to
0.026. Quebec has no batteries or EVs, so they then run exactly as the version
3 BAU: cost 4,403.8 EUR and a cost ratio of 1.000. With `hvac='off'` they cost
631.8 EUR, a ratio of 0.143. Against the default version 2 BAU, which does not
heat, their cost ratio is 6.970, so on datasets with HVAC actions compare them
with the version 3 BAU.

```python
smart = RBCSmartPolicy(env)               # HVAC meets the dataset demand
legacy = RBCSmartPolicy(env, hvac='off')  # HVAC at zero, as before
```

Smart and Community use the entity observation bundles when the schema enables
them: `entity_core_electrical` for measured import and export,
`entity_forecasts_existing` and `entity_forecasts_derived` for price and PV
forecasts, and `entity_community_operational` for community import and surplus.
The simulator leaves them off unless the schema turns them on; some bundled
datasets do (for example `citylearn_challenge_2022_phase_all_plus_evs` and the
dynamic-topology demo), others do not (for example
`citylearn_three_phase_electrical_service_demo`). Without the community bundle, Community cannot
observe community import or surplus; without the forecast bundles, Smart and
Community fall back to the current price and PV.
Enable them in the schema, for example
`"observation_bundles": {"entity_community_operational": true}`.

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
storage, EV and appliance actions at every step; the HVAC rule above is
CityLearn's own (`hvac='off'` gives the zero HVAC of the port). `agent.comparison_identity()` records the class, the
definition version and the resolved parameters for experiment manifests.

The rule baselines can also guide the exploration of `SACRBC` and
`MARLISARBC`. Pass an instance built on the same environment, the class or its
import path as `rbc`. With a class or an import path, the learner's own
hyperparameters stay with the learner, and the remaining keyword arguments go to
the baseline:

```python
from citylearn.agents.baseline import RBCBasicPolicy
from citylearn.agents.sac import SACRBC

agent = SACRBC(env, rbc=RBCBasicPolicy, lr=3e-4, batch_size=256, basic_price_policy='forecast_relative')
agent = SACRBC(env, rbc=RBCBasicPolicy(env, basic_price_policy='forecast_relative'), lr=3e-4)
```

The reinforcement learning controllers (`SAC`, `SACRBC`, `MARLISA`,
`MARLISARBC`, `TabularQLearning`) read flat observation vectors and require
`interface='flat'`; on the entity interface they raise a `ValueError`. The rule
baselines, `ZeroActionAgent` and the random `Agent` work with both
interfaces.

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

"Without storage" removes the battery, the thermal storage and the EV charging
of the controlled run, and adds back the EV charging of the native BAU with the
`'full'` target: each car is charged on arrival at maximum power until it is
full, and never discharged. The cars get the energy they need, without V2G, and
the baseline does not depend on how the controller charged them, so a controller
that leaves the cars short does not lower its own baseline. The deferrable
appliances and the HVAC stay as the controller ran them. The `baseline` rows
therefore credit the controller with its storage dispatch, its EV charging and
its V2G against charging on arrival. With `baseline_version=1` nothing is added
back, as in CityLearn 3.6.0, so on EV datasets the baseline is a community whose
cars never charge.

Apart from that EV charging, this is a counterfactual calculation from the run's
own series, not a second `BusinessAsUsualAgent` run. On datasets with EV
chargers the charging comes from the BAU sidecar, which every evaluation then
runs, also the legacy `evaluate()` and `evaluate_v2(include_business_as_usual=False)`,
with the `'full'` target whatever `business_as_usual_ev_charge_target` is. Like
the BAU rows, it cannot be built when inputs, buildings or devices changed after
loading; evaluate such runs with `baseline_version=1`.
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
[DR KPIs](kpis_reference.md#demand-response).

## A reference run selected in the UI

When comparing imported runs, the UI labels the first included simulation
in its imported list as **Compare baseline**. That is a user-selected run; it need not be the native
BAU. The `business_as_usual` columns inside each exported KPI table retain
their simulator-defined meaning.

Read [the scorecard](scorecard.md) for matched-controller comparisons and
[the UI guide](https://www.citylearn.net/ui.html) for the visual workflow.

From 3.4.0, the BAU still charges EVs to 100% by default, now decided from the
entity observations like the other baselines; `ev_charge_target='requested'`
charges only to the requested departure SOC. The definition version, recorded
with every native reference, changes whenever the baseline's actions change.
References computed with another definition version are not comparable;
rerun both the controller and its reference.
