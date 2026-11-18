===============
Reward Function
===============

A reward is returned at every ``step()``. It defines the learning signal,
whereas :doc:`../kpis` assess the completed episode. A reward and a reported
KPI do not have to be the same quantity.

The default :py:class:`citylearn.reward_function.RewardFunction` penalizes
positive grid imports. Other supplied rewards cover objectives such as thermal
comfort and EV charging. See :py:mod:`citylearn.reward_function` for constructors
and formulas.

Choose a reward
***************

Pass the reward class through ``CityLearnEnv(reward_function=...)`` or select an
importable class in the schema:

.. code-block:: json

   {
     "reward_function": {
       "type": "citylearn.reward_function.RewardFunction"
     }
   }

This is the reward section of a schema, not a complete dataset definition.

Define a custom reward
**********************

Subclass ``RewardFunction`` and implement ``calculate(observations)``.
Return one reward per building for decentralized control, or one aggregate
reward for centralized control. The inherited ``central_agent`` property
exposes the environment setting.

The existing emissions-based example is:

.. literalinclude:: ../../../examples/custom_reward_function.py
   :language: python
   :start-at: from typing

A reward can declare ``required_observation_names`` to receive a smaller
observation payload. The :doc:`../usage/custom_controller` tutorial demonstrates
this together with a complete simulation.

Penalize unserved energy during power outages
*********************************************

When ``simulate_power_outage`` is on, a building cannot import from the grid during an outage, so its net
electricity consumption is zero and rewards built on grid imports give no signal about load left unserved.
:py:class:`citylearn.reward_function.OutageUnservedEnergyReward` wraps a base reward and subtracts a penalty for
that shortfall. It reads the ``power_outage_unserved_energy`` observation, which uses the same definition as the
``power_outage_normalized_unserved_energy_total`` KPI, so it can be set in the schema like any other reward:

.. code-block:: json

   {
     "reward_function": {
       "type": "citylearn.reward_function.OutageUnservedEnergyReward",
       "attributes": {
         "coefficient": 1.0,
         "base_reward": {"type": "citylearn.reward_function.ComfortReward"}
       }
     }
   }

``coefficient`` is the penalty per unserved kWh in the units of the base reward. Without ``base_reward`` the
penalty is added to :py:class:`citylearn.reward_function.RewardFunction`.
