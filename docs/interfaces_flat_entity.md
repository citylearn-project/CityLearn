# Flat and Entity Interfaces

CityLearn supports two I/O contracts: `flat` for classic Gymnasium-style RL workflows and `entity` for ORL, GraphRL, Transformers and dynamic topology.

Portuguese version: [pt/interfaces_flat_entity.md](pt/interfaces_flat_entity.md).

## Quick Comparison

| Topic | Flat | Entity |
|---|---|---|
| Observation | List of vectors per building or one central vector. | Dict with entity tables and relational edges. |
| Action | List/array ordered by `env.action_names`. | Dict with action tables or an ID-keyed map. |
| Best for | RBC, MARL, wrappers, SB3-style workflows. | GNNs, transformers, dynamic input/output networks. |
| Dynamic topology | Not supported. | Supported. |
| Stable IDs | Implicit through vector order. | Explicit in `env.entity_specs`. |
| EV/charger relation | Expanded flat names. | Separate tables plus `charger_to_ev_*` edges. |

## Flat Mode

```python
env = CityLearnEnv(schema, interface="flat")
```

With `central_agent=False`, observations are one vector per building:

```python
observations = [
    [building_1_feature_1, building_1_feature_2],
    [building_2_feature_1, building_2_feature_2],
]
```

With `central_agent=True`, observations are concatenated into a single vector:

```python
observations = [[all_active_features_for_all_buildings]]
```

`shared_observations` are included once in the central vector to avoid repeated weather, pricing and calendar features.

Flat actions follow the same convention:

```python
actions = [
    [building_1_action_1, building_1_action_2],
    [building_2_action_1, building_2_action_2],
]
```

The exact order is available through:

```python
env.observation_names
env.action_names
```

## Entity Mode

```python
env = CityLearnEnv(schema, interface="entity")
```

Dynamic topology requires entity mode:

```python
env = CityLearnEnv(schema, interface="entity", topology_mode="dynamic")
```

Entity observations have this structure:

```python
{
  "tables": {
    "district": np.ndarray,
    "building": np.ndarray,
    "charger": np.ndarray,
    "ev": np.ndarray,
    "storage": np.ndarray,
    "pv": np.ndarray,
    "deferrable_appliance": np.ndarray
  },
  "edges": {
    "district_to_building": np.ndarray,
    "building_to_charger": np.ndarray,
    "building_to_storage": np.ndarray,
    "building_to_pv": np.ndarray,
    "building_to_deferrable_appliance": np.ndarray,
    "charger_to_ev_connected": np.ndarray,
    "charger_to_ev_connected_mask": np.ndarray,
    "charger_to_ev_incoming": np.ndarray,
    "charger_to_ev_incoming_mask": np.ndarray
  },
  "meta": {
    "time_step": int,
    "endogenous_time_step": int,
    "spec_version": "entity_v1",
    "topology_version": int,
    "runtime_status": {
      "version": "runtime_status_v1",
      "emits_health_state": false,
      "active_events": [],
      "asset_connections": [],
      "asset_availability": [],
      "sensor_channels": [],
      "actuator_channels": [],
      "communication_links": [],
      "value_quality": []
    }
  }
}
```

`runtime_status_v1` reports simulator facts, not an RL-policy health
classification. `fault_mode` is preserved as the original cause. In
particular, a `stuck` event is not automatically labelled stale: a consumer
must derive that state from freshness, duration, semantic type and criticality.

Asset connection, asset availability, sensor-channel state,
actuator-channel state and community/cloud communication state are independent
parts of the contract. A normally disconnected EV is not a failed charger.

## `entity_specs`

`env.entity_specs` is the machine-readable schema for tables, columns, IDs, units, bundles and edges:

```python
specs = env.entity_specs
building_features = specs["tables"]["building"]["features"]
charger_ids = specs["tables"]["charger"]["ids"]
charger_units = specs["tables"]["charger"]["units"]
```

| Field | Contents |
|---|---|
| `ids` | Stable canonical row IDs. |
| `features` | Column names. |
| `units` | Inferred units. |
| `feature_metadata` | Unit, bundle and legacy flag per feature. |
| `actions` | Action table IDs, columns and units. |
| `edges` | Source/target table metadata. |
| `topology` | Active IDs, lifecycle and topology version. |
| `runtime_status_contract` | Status vocabulary, sparse defaults and explicit no-health-state boundary. |
| `action_execution_contract` | Requested/post-channel/limited/applied action stages. |

## Temporal Semantics

| Field | Meaning |
|---|---|
| Exogenous observations | Read at timestep `t`. Examples: weather, pricing, schedules. |
| Endogenous observations | Read at settled `t-1`. Examples: previous consumption and SOC after the last action. |
| Terminal observation | Same rule at the final `t`: exogenous and calendar features from the last data row, endogenous ones from the last executed interval. Building series still hold only executed intervals. Charger, deferrable-appliance and escalator states are not advanced and stay at the last executed interval. |
| Topology events | Events at `k` are applied after interval `k-1` and before EV association and observation at `k`. |

## Entity Bundles

| Bundle | Default | Tables | Purpose |
|---|---:|---|---|
| `entity_base` | always on | charger, storage, deferrable | Essential static and service features. |
| `entity_core_electrical` | off | building, charger, ev, storage, pv | Power, step energy, efficiency, derived SOC and PV. |
| `entity_community_operational` | off | district | Aggregates, headroom, counts and topology version. |
| `entity_forecasts_existing` | off | district | Forecasts already present in the dataset. |
| `entity_temporal_derived` | off | district, building | Short lags and rolling means. |

## Entity Actions

Recommended table payload:

```python
actions = {
    "tables": {
        "building": building_action_array,
        "charger": charger_action_array,
        "deferrable_appliance": deferrable_action_array
    }
}
```

ID-keyed overrides are also supported:

```python
actions = {
    "map": {
        "building:Building_1": {"electrical_storage": 0.2},
        "charger:Building_1:AC001": {"electric_vehicle_storage": 0.5},
        "deferrable_appliance:Building_1:washer_1": {"start": 1.0}
    }
}
```

Use prefixed IDs for robust GraphRL and Transformer integrations.

After an entity-mode step, `info["entity_action_execution"]` contains stable-ID
entries for the requested command, the value after channel perturbations, the
equipment-limited value and the physically applied power where observable.
Unavailable quantities are `None`. `info["topology_events_applied"]` identifies
events applied before the returned observation.

## Dynamic Topology Guidance

For every dynamic-topology `reset()`, the environment first restores the member pool and structural
asset composition loaded from the schema, then applies any events scheduled at time step `0`.
Added or removed chargers, deferrable appliances, PV systems, electrical storage and runtime-cloned
members therefore do not leak into the next episode. Reusing one environment across training episodes
has the same topology event timeline as recreating the environment for each episode.

When a stationary battery is added or recommissioned, its configured initial
SOC defines the opening stock. An initial SOC below the discharge reserve stays
at that value. The battery can charge immediately and can discharge once its
SOC exceeds the reserve.

| Element | Agent guidance |
|---|---|
| `topology_version` | Re-read `entity_specs` when it changes. |
| EV masks | Use `charger_to_ev_connected_mask` and `charger_to_ev_incoming_mask`. |
| Running statistics | Maintain stats per feature, not per fixed row. |
| Removed assets | Ignore IDs that disappear from `active_ids`. |
| Added assets | Initialize model memory/hidden state for new IDs. |

EV IDs identify vehicles independently of their chargers. Removing the last
charger that references an EV suspends its participation in the community.
The same EV continues to experience standby loss and the seeded away-mobility
model while suspended, with no charging from the community. Reinstalling a
charger brings back that EV and its evolved SOC. A valid arrival SOC from the
dataset is an external adjustment. A catalogue EV first activated mid-episode
opens at its configured initial SOC, and its opening stock enters the energy
accounting when it connects. The EV can connect to one charger at a time.
Departure metrics start a topology-induced connection at its observed opening
SOC and count charging opportunities from that connection onwards.
Charger exports show the connection that actually took place. An incoming
vehicle appears as incoming until it connects.
