==================
Entity v1 Contract
==================

CityLearn provides two interfaces:

* ``interface="flat"``: legacy fixed-size vectors (backward compatible).
* ``interface="entity"``: canonical table/edge payload for graph, hierarchical and transformer agents.

Entity mode contract
--------------------

At each step, ``reset()`` and ``step()`` return:

.. code-block:: python

   {
       "tables": {
           "district": np.ndarray,  # [n_district, n_features]
           "building": np.ndarray,  # [n_buildings, n_features]
           "charger": np.ndarray,   # [n_chargers, n_features]
           "ev": np.ndarray,        # [n_evs, n_features]
           "storage": np.ndarray,   # [n_storage, n_features]
           "pv": np.ndarray,        # [n_pv, n_features]
       },
       "edges": {
           "district_to_building": np.ndarray,      # [n_buildings, 2]
           "building_to_charger": np.ndarray,       # [n_chargers, 2]
           "building_to_storage": np.ndarray,       # [n_storage, 2]
           "building_to_pv": np.ndarray,            # [n_pv, 2]
           "charger_to_ev_connected": np.ndarray,   # [n_chargers, 2]
           "charger_to_ev_connected_mask": np.ndarray,
           "charger_to_ev_incoming": np.ndarray,    # [n_chargers, 2]
           "charger_to_ev_incoming_mask": np.ndarray,
       },
       "meta": {
           "time_step": int,
           "endogenous_time_step": int,
           "spec_version": "entity_v1",
           "temporal_semantics": {
               "exogenous": "t",
               "endogenous": "t_minus_1_settled",
           },
           "topology_version": int,
           "runtime_status": {
               "version": "runtime_status_v1",
               "emits_health_state": False,
               "active_events": list,
               "asset_connections": list,
               "asset_availability": list,
               "sensor_channels": list,
               "actuator_channels": list,
               "communication_links": list,
               "value_quality": list,
           },
       },
   }

``entity_specs`` provides stable metadata for tooling/model builders:

* table IDs and feature names,
* per-feature unit/bundle/legacy tags,
* action schemas,
* edge schemas,
* topology metadata,
* normalization/encoding policy.
* the optional runtime-status and action-execution subcontracts.

Runtime status and fault evidence
---------------------------------

``runtime_status_v1`` is an additive facts-only extension. It reports current
entity connections, availability, channel quality, event duration, freshness
and the original ``fault_mode``. It does not emit policy health states such as
``HEALTHY``, ``STALE`` or ``FAILED``.

Fault cause and health classification are intentionally separate. For
example, ``fault_mode="stuck"`` says that a value is frozen; the consumer must
use its age, semantic type and criticality to decide whether it is degraded or
stale.

The contract keeps these domains separate:

* asset connection (from actual entity relations),
* asset availability,
* sensor channels,
* actuator channels,
* community/cloud communication links, and
* value-quality perturbations.

Normal charger/EV disconnection is a relation state, not an equipment failure.
Sparse status collections use the defaults declared by
``entity_specs["runtime_status_contract"]``.

Action execution evidence
-------------------------

In entity mode, ``step()`` adds ``info["entity_action_execution"]`` with the
``entity_action_execution_v1`` contract. Each entry preserves, where
observable, the requested, post-channel, equipment-limited and physically
applied command. Unobservable values are ``None`` rather than inferred.

``info["topology_events_applied"]`` lists topology events applied between the
current action and returned observation.

Temporal semantics
------------------

In ``entity_v1``:

* Exogenous observations are read at current control index ``t``.
* Endogenous observations are read from settled transition ``t-1`` (clamped at 0 on reset).
* In dynamic topology mode, events at ``time_step=k`` apply after transition ``k-1 -> k`` and before observation ``k``.

Dynamic topology notes
----------------------

When ``topology_mode="dynamic"`` (entity mode only), table sizes can grow/shrink during the episode.

* IDs are canonical and stable while entities are active.
* Relation masks identify valid EV-charger relations each step.
* Simulator outputs raw values; normalization should be handled externally (running stats per feature).
