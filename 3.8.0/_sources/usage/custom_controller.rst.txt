=========================
Custom agents and rewards
=========================

An agent selects actions; a reward evaluates each transition during learning.
The end-of-episode KPIs evaluate the outcome independently of that reward.

This complete example defines both. Save it as ``custom_controller.py`` and run
``python custom_controller.py``. It uses a public dataset and the flat interface.

.. literalinclude:: ../../../examples/custom_controller.py
   :language: python

Adapt the action rule
*********************

``ZeroActionAgent`` supplies one action vector per action space and preserves
the base agent's action history and timestep. Replace its rule with your
controller, using ``env.action_names`` and ``env.observation_names`` to locate
signals. Read bounds from the spaces, rather than assuming all actions use
the same range.

Zero actions make this a small coding example, not the operational BAU policy.
Use :doc:`../guides/baselines` for that reference. For identified tables and
changing asset populations, use :doc:`../guides/interfaces_flat_entity`.

Adapt the reward
****************

``GridImportReward`` penalizes positive grid imports. It returns one value per
building in decentralized mode, or their sum in centralized mode. The
``required_observation_names`` attribute lets CityLearn supply only the
observations this reward needs.

Pass a reward class directly to ``CityLearnEnv`` as shown above, or put an
importable class path under ``reward_function.type`` in the schema. The module
must be importable in the Python environment running the simulation.

Next, inspect :doc:`../overview/agents`, :doc:`../overview/reward_function`
and :doc:`../guides/kpis_reference`.
