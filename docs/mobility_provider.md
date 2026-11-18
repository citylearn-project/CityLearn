# External Mobility Providers

A mobility provider drives electric vehicle (EV) connections while an episode runs. It
connects for example a traffic simulator such as SUMO or CARLA to CityLearn: the traffic
simulator decides where and when vehicles park, CityLearn computes the charging and
vehicle-to-building energy and the controller decides the charger set-points.

Portuguese version: [pt/mobility_provider.md](pt/mobility_provider.md).

## How it works

A charger normally reads its schedule (connected, incoming or away, EV, departure countdown,
required departure SOC, estimated arrival) from a file. An external charger has the same schedule
rows, but they start "away" and the provider writes them during the episode. Everything that reads
the rows is unchanged: the charger-EV association, the arrival SOC, the flat and entity
observations, the KPIs, the EV departure audit and the business-as-usual (BAU) reference.

## Schema

Declare a charger external by replacing the schedule file name:

```json
"chargers": {
  "hub_1": {
    "type": "citylearn.electric_vehicle_charger.Charger",
    "charger_simulation": {"source": "external"},
    "attributes": {"max_charging_power": 11.0, "max_discharging_power": 11.0}
  }
}
```

Declare a vehicle whose state of charge (SOC) the provider reports:

```json
"electric_vehicles_def": {
  "EV_1": {"external": true, "battery": {"attributes": {"capacity": 60.0, "nominal_power": 11.0}}}
}
```

CityLearn adds no random SOC drift to an external vehicle while it is away. Its SOC changes only
through charging, the battery's standby loss and the provider. Vehicles without `external` can also
be connected through external chargers; they keep the random drift while away, except at the time
steps where the provider sets their SOC. External chargers are not supported with
`topology_mode="dynamic"`.

## Provider

A provider is any object with two methods (`citylearn.mobility.MobilityProvider`):

| Method | Called |
|---|---|
| `reset(env)` | In every `env.reset()`, after the buildings and vehicles are reset and before the chargers are associated for time step 0. The constructor runs `reset()` too, so a provider passed to it is reset during construction. |
| `update(env, time_step)` | In `env.step()`, after the energy of interval `time_step - 1` is computed and the environment has advanced to `time_step`, before the chargers are associated for `time_step`. Not called for the terminal transition, after which no action follows. |

Pass it as `CityLearnEnv(..., mobility_provider=provider)` or assign `env.mobility_provider` before
`env.reset()`. Because `update` runs before the association, the observations that `step()`
returns already show the connections written for the new time step. `step_many()` and the BAU
reference use the same path; observation and topology refreshes never call the provider.

## Writing the schedule

Inside `reset` and `update`, the provider writes through `env.mobility`. Writes outside these calls
raise `RuntimeError`. Each write applies to the current time step at once.

| Call | Effect |
|---|---|
| `connect(charger_id, ev_id, *, soc=None, departure_steps=None, required_soc=None, session_id=None, connected_seconds=None, discharge_soc_floor=None)` | Plugs the vehicle in. |
| `incoming(charger_id, ev_id, *, arrival_steps=None, soc_on_arrival=None)` | Announces a vehicle on its way to the charger; the estimates are observations only. A schedule row holds one state per step, so announcing the vehicle that is connected to this charger means it has left at this step: its session ends as with `away()`. |
| `away(charger_id)` | Frees the charger. |
| `set_vehicle_soc(ev_id, soc)` | Sets the SOC of a vehicle that is not continuing a charging session, e.g. after driving. |

A connection persists from one time step to the next until `away()` or another write changes it.
The departure and arrival countdowns decrease by one per step and stop at 0; the vehicle leaves at
the end of the step where the departure countdown is 1. Countdowns beyond the episode are stored as
the episode length, the upper bound of the observation space.

| `connect` argument | Meaning |
|---|---|
| `soc` | SOC on arrival, in [0, 1]. Only when the call starts a session; it sets the vehicle's SOC. Without it the session starts from the SOC the vehicle has in CityLearn. Either way the value is the session's arrival SOC for the runtime, the KPIs and the departure audit. |
| `departure_steps` | Time steps until departure. Unknown when omitted at session start; kept when omitted later. |
| `required_soc` | SOC the user requires at departure. Unknown when omitted at session start; kept when omitted later. |
| `session_id` | Session identity; generated when omitted. A new ID for the vehicle already connected starts a back-to-back session. |
| `connected_seconds` | Seconds of the current step the vehicle is plugged in, in [0, `seconds_per_time_step`]. The step's energy is the commanded power over that time; battery power limits and efficiency refer to it. Applies to one step only. |
| `discharge_soc_floor` | Discharging in this session never takes the battery below this SOC, e.g. the energy needed for the next trip. Charging is unaffected. |

Invalid writes raise `ValueError` with the reason: an unknown charger or vehicle, a charger ID used
by several buildings (write `"<building>/<charger>"`), a charger with a schedule file, a vehicle
connected to another charger at the same step, a charger connected to another vehicle (free it with
`away()` first), `soc` on a running session or
`set_vehicle_soc` for a vehicle continuing its session, an SOC outside [0, 1], a negative or
fractional countdown, and `connected_seconds` outside [0, `seconds_per_time_step`].

## Reading results

| Call | Value |
|---|---|
| `env.mobility.vehicle_soc(ev_id)` | The SOC CityLearn holds now. In `update` it is the SOC the vehicle starts the new interval with, after the charging of the finished interval and the standby loss. |
| `env.mobility.charger_energy_kwh(charger_id)` | Signed AC energy of the last finished interval in kWh: positive charging, negative vehicle-to-building. Any charger. |
| `env.mobility.charger_power_kw(charger_id)` | Average AC power of the last finished interval. |
| `env.mobility.external_charger_ids`, `external_vehicle_ids`, `vehicle_ids` | Identifiers. |

Read vehicle SOCs with `vehicle_soc`. The battery's `soc` array also holds them, indexed by time step,
but its last slot stays 0 after an episode: the terminal transition takes no action, so CityLearn does
not advance the batteries into it. This holds for every EV, with or without a provider.

## Battery parameters

The simulation uses the parameters held by the vehicle objects, e.g.
`env.electric_vehicles[i].battery.efficiency`, `.power_efficiency_curve`, `.capacity_power_curve`,
`.nominal_power` and `.capacity` (all of them in `battery.get_metadata()`). Read them there when a
mobility model needs the same battery. Parameters the schema leaves out are drawn when the
environment is built, from a seed derived from the schema's `random_seed` and the vehicle name, so
each EV has its own values; for example the power-efficiency curve is drawn around the battery's
efficiency, and the default curve in the `Battery` docstring only shows its form. To use known
values, set them under `electric_vehicles_def.<EV>.battery.attributes`.

## What the controller observes

The rows written by the provider feed the usual charger observations: connected and incoming
state, departure countdown, required SOC, battery capacity, estimated arrival time and SOC, and the
connected vehicle's SOC. That SOC is the settled value of the previous interval, or the arrival or
reported SOC of the current step when the provider wrote it before the action. `connected_seconds`
and `discharge_soc_floor` constrain the energy but are not observed.

## Business-as-usual reference

`evaluate_v2()` rebuilds a BAU reference from the schema. With a provider, the reference replays
this episode's external schedule rows and the SOCs the provider set. A reported SOC is applied as
the same value when the reference vehicle had the same SOC before the write, and otherwise as the
same change (clipped to [0, 1]): the reference keeps its own charging history and sees the same
driving consumption.

## Example

```python
from citylearn.citylearn import CityLearnEnv


class Scripted:
    def reset(self, env):
        env.mobility.connect('charger_1_1', 'EV_1', soc=0.4, departure_steps=2, required_soc=0.9)

    def update(self, env, time_step):
        mobility = env.mobility
        if time_step == 2:  # the vehicle left after interval 1 and drives
            mobility.away('charger_1_1')
            mobility.set_vehicle_soc('EV_1', mobility.vehicle_soc('EV_1') - 0.1)
        elif time_step == 3:  # it arrives at another building, plugged in for 450 s of 900 s
            mobility.connect('charger_2_1', 'EV_1', departure_steps=3, required_soc=0.8,
                             connected_seconds=450, discharge_soc_floor=0.3)


env = CityLearnEnv(schema, central_agent=True, mobility_provider=Scripted())
observations, info = env.reset()
while not env.terminated:
    observations, reward, terminated, truncated, info = env.step(policy(observations))
```

`schema` declares the two external chargers and the external vehicle above; `policy` is the
controller.
