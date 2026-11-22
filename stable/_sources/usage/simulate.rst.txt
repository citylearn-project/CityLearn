==========================
How to set up a simulation
==========================

Begin with :doc:`../quickstart` for a complete runnable episode. To configure a
study, choose the following in order:

1. **Data and timestep:** select a public dataset or local schema, then check
   the energy units and time window.
2. **Members and equipment:** select buildings, PV, storage, EVs and flexible loads.
3. **Services and constraints:** set deadlines, electrical limits, local settlement
   and any demand-response or robustness events.
4. **Controller interface:** choose flat vectors or entity tables, observations,
   actions, controller and reward.
5. **Evaluation:** run the episode, inspect raw and normalized KPIs, and export
   results for the scorecard or UI.

The :doc:`../guides/features` guide explains each choice. Use
:doc:`../guides/running_simulations` for executable examples and
:doc:`../guides/schema_reference` for exact configuration fields.
