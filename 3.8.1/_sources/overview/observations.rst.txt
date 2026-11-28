============
Observations
============

Observations are the information available to a controller at a timestep.
They combine calendar and weather inputs, building/asset state, and configured
forecasts or service signals. Some come from the dataset; others depend on the
actions already applied.

In flat mode, each vector follows ``env.observation_names``. Central-agent mode
combines buildings and includes shared observations once. In entity mode,
identified tables and edges describe buildings, chargers, EVs and other assets.

.. code-block:: python

   observations, info = env.reset(seed=0)
   print(env.observation_names)  # Flat-vector names.
   # In entity mode, inspect env.entity_specs for IDs, columns, units and edges.

Choose active observations in the schema or constructor. Observation bundles
can add forecasts, electrical headroom, service deadlines and action feedback.
Robustness events can alter what the controller sees.

See :doc:`../guides/observations_reference` for available signals,
:doc:`../guides/interfaces_flat_entity` for payloads, and
:doc:`entity_v1_contract` for timing and lifecycle semantics.
