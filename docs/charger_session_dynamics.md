# Charger Session Dynamics

By default an EV charger delivers the commanded power for the whole time a vehicle is connected,
from the first second of a session to the last. Real sessions are slower: a vehicle has to be
coupled and the charger and vehicle negotiate before power flows, a new set-point takes effect only
after a delay, power changes at a limited rate and the transfer stops before the vehicle leaves.
Five optional charger attributes model these phases. With short control steps (a minute or less)
they change the energy of a session noticeably; with hourly steps they matter mainly for short stops.

Portuguese version: [pt/charger_session_dynamics.md](pt/charger_session_dynamics.md).

## Attributes

Set them in `buildings.<building>.chargers.<charger>.attributes`. Omitted attributes keep today's
behaviour: no delay and an unlimited ramp.

| Attribute | Unit | Meaning |
|---|---:|---|
| `start_delay_seconds` | s | Time after a vehicle connects before energy flows: coupling plus the communication start-up. |
| `setpoint_delay_seconds` | s | Time after the start of a step before that step's command takes effect; the previous set-point holds meanwhile. A delay longer than the step carries the command into a later step. |
| `ramp_up_kw_per_second` | kW/s | Largest rate at which the magnitude of the power rises. |
| `ramp_down_kw_per_second` | kW/s | Largest rate at which the magnitude of the power falls. A reversal between charging and discharging passes through zero: down at this rate, then up at the ramp-up rate. |
| `stop_delay_seconds` | s | Time before a known departure at which the charger stops the transfer: the set-point becomes zero and the power ramps down. |

```json
"chargers": {
  "hub_1": {
    "type": "citylearn.electric_vehicle_charger.Charger",
    "charger_simulation": "chargers/hub_1.csv",
    "attributes": {
      "max_charging_power": 11.0,
      "max_discharging_power": 10.0,
      "start_delay_seconds": 51.0,
      "setpoint_delay_seconds": 4.0,
      "ramp_up_kw_per_second": 3.35,
      "ramp_down_kw_per_second": 3.31,
      "stop_delay_seconds": 22.0
    }
  }
}
```

## Measured values

The example uses measured values. They describe particular hardware; choose values for the
chargers you model.

| Phase | Value | Source |
|---|---:|---|
| Automated (robotic) coupling | 24 s | Walzel, Hirz, Brunner and Kreutzer (2019), *Robot-Based Fast Charging of Electric Vehicles*, SAE Technical Paper 2019-01-0869, doi:10.4271/2019-01-0869: robotic plug-in about 24 s, plug-out about 22 s. |
| Communication start-up (DC, ISO 15118-2 / DIN SPEC 70121) | 27 s median (quartiles 12.05 s and 43.08 s) | Watt, Bani Shamseh and Gadamsetty (2025), *Quantifying Time to Charge*, National Charging Experience Consortium (ChargeX), NREL, July 2025: time from the start of SLAC to Power Delivery in 162 test sessions (median 26.99 s). |
| Set-point activation delay | 4 s local, 7 s remote | Zecchino, Thingvad, Andersen and Marinelli (2019), *Test and Modelling of Commercial V2G CHAdeMO Chargers to Assess the Suitability for Grid Services*, World Electric Vehicle Journal 10(2):21, doi:10.3390/wevj10020021. |
| Ramp rates up / down | 3.35 / 3.31 kW/s (about 1.8 to 9.2 kW/s across tests) | Zecchino et al. (2019), as above. |
| Automated (robotic) decoupling | 22 s | Walzel et al. (2019), as above. |

`start_delay_seconds = 24 + 27 = 51` covers robotic coupling and the DC start-up; `stop_delay_seconds = 22`
covers robotic decoupling. A manually plugged session would use only the start-up time.

## Model

Times are measured from the start of a control step of length `seconds_per_time_step`.

- A session starts when the vehicle connects, at the start of its first step. A [mobility
  provider](mobility_provider.md) can pass `connected_since_seconds` when it starts a session: a positive
  value means the vehicle plugged in that long before the step (the elapsed time counts towards the
  start delay), a negative value that it plugs in that long into the step (no energy before it does).
  A session that is already running when an episode starts is treated as starting at the episode start.
- The command of a step is issued at the start of the step and takes effect `setpoint_delay_seconds`
  later. The first command of a session takes effect at the same delay; until then the set-point is zero.
- Energy flows from `start_delay_seconds` after the connection. The power follows the set-point within
  the ramp limits.
- The departure is known from the departure countdown (a countdown of 1 means the vehicle leaves at the
  end of the step) or from a connection that ends within the step (`connected_seconds`). A mobility
  provider can give the exact time with `departure_seconds`; the whole-step countdown rounds the
  departure up to the end of its step, so only the exact time places a stop that falls in an earlier
  step than the departure. The transfer stops `stop_delay_seconds` before the departure. The power is
  zero once the vehicle is disconnected.

The AC power is therefore piecewise linear in time. The energy of a step is its exact integral, a sum
of trapezoids over the linear pieces, computed in closed form without sub-stepping
(`citylearn.internal.charger_dynamics.integrate_step`). The charging and discharging parts of a step
are applied to the battery in time order. Each part's efficiency is read from the charger's efficiency
curve at the part's average power, and the battery's power limits and power-dependent efficiency refer
to the time the part lasts. Battery limits (full battery, depth of discharge, a session's
`discharge_soc_floor`, the battery's power curve) can reduce the energy further; they do not feed back
into the charger's ramp state, which follows the commanded profile.

The EV departure audit and the departure feasibility KPIs replay a maximum-charge command with the
same profile, so a target that is out of reach because of the start-up or the stop counts as infeasible.

## What the controller observes

Nothing new. The observations and action spaces do not change. The controller sees the usual charger
observations (connection state, departure countdown, required SOC, connected vehicle SOC) and the
energy actually delivered in the last interval (`last_charged_kwh` in the flat interface, the applied
energy in the entity action feedback). The ramp state, the pending set-point and the remaining
start-up time are not observed, but they follow from the documented parameters, the controller's own
past commands and the observed connection history, so no information about the future is exposed.
`connected_seconds`, `connected_since_seconds` and `departure_seconds`, which a mobility provider may
know before the controller acts, constrain the energy but are not observations: the controller sees
the whole-step departure countdown, as without session dynamics.

With session dynamics enabled, a charger without a connected vehicle records zero commanded energy
for the step.
