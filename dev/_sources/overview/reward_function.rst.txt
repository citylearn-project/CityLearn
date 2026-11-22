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

Reward versions
***************

The EV and comfort rewards have two definitions. Version 2, the default, follows
the documented definitions. Version 1 is the reward of CityLearn 3.6.0 and
earlier, which had the defects listed below. It is deprecated and exists only to
reproduce runs made with those releases: selecting it raises a
``DeprecationWarning``, and it will be removed in a later release. Keeping a single
current definition avoids comparing policies that were trained on different
rewards. The environment metadata, and the manifest of every export, record the
version in ``reward_evidence.effective_public_parameters``, so the definition
behind a run stays identifiable.

.. list-table::
   :header-rows: 1

   * - Reward
     - Version 1 (deprecated)
     - Version 2 (default)
   * - :py:class:`citylearn.reward_function.Electric_Vehicles_Reward_Function`
     - The reward of CityLearn 3.6.0 and earlier. A building with chargers gets only its EV terms, and a
       building without chargers gets 0. Leaving 0.25 or more below the required departure SOC adds
       ``weights['soc_under'] ** 2`` (+25 with the default weights), so it scores better than a moderate
       deficit (-10).
     - Each building gets its MARL base reward plus its EV terms. A deficit of 0.25 or more adds
       ``min(2 * w, -(w ** 2))`` (-25 with the default weights). The EV terms are scaled by the building's
       own base reward, with or without a central agent.
   * - :py:class:`citylearn.reward_function.ComfortReward` and the comfort term of
       :py:class:`citylearn.reward_function.SolarPenaltyAndComfortReward`
     - The reward of CityLearn 3.6.0 and earlier. In cooling and heating mode, the side of the set point
       penalized within the comfort band, and the exponent above it, follow whether the heating demand exceeds
       the cooling demand at that step.
     - Follow the HVAC mode: heating when ``hvac_mode`` is 2, cooling when it is 1. In heating mode at
       21.5 C with a 20 C set point the reward is -1.5 whether the heater runs or not; version 1 gives 0
       while the heater is off.

The bundled schemas that use these rewards set ``"version": 2``. To reproduce
a run made with CityLearn 3.6.0 or earlier, select version 1 explicitly:

.. code-block:: json

   {
     "reward_function": {
       "type": "citylearn.reward_function.Electric_Vehicles_Reward_Function",
       "attributes": {"version": 1}
     }
   }

Simulated energy flows and KPIs do not depend on the reward, so the version
changes only the learning signal.

Per-building reward functions
*****************************

The schema's ``reward_function.type`` can map building names to reward
classes, with an optional ``default`` entry, and ``attributes`` can do the same:

.. code-block:: json

   {
     "reward_function": {
       "type": {
         "default": "citylearn.reward_function.RewardFunction",
         "Building_1": "citylearn.reward_function.SolarPenaltyReward"
       },
       "attributes": {}
     }
   }

Each building's function receives that building's observations and the
environment metadata with ``buildings`` reduced to that building, so rewards
that read building metadata, such as
:py:class:`citylearn.reward_function.SolarPenaltyReward`, use that building's
storage capacities. Functions are paired with buildings by name, also when
members join or leave under a dynamic topology. Up to CityLearn 3.6.0 every
function read the first building's metadata and the functions were paired by
position, so per-building rewards that read metadata differ from earlier runs.

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
