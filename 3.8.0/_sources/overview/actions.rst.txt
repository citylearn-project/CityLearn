=======
Actions
=======

An action requests an equipment operation for the next transition. Its meaning
depends on the device: it may request charging power, thermal-device operation,
a flexible-appliance start, or an escalator state.

Storage and EV charging actions are positive for charging and negative for
discharging when supported. Flexible-appliance actions request a cycle start.
HVAC and thermal-storage actions have their own conversion rules. Read
:doc:`../guides/actions_reference` for signs, ranges and physical units.

.. code-block:: python

   for names, space in zip(env.action_names, env.flat_action_space):
       print(list(zip(names, space.low, space.high)))

The action bounds describe valid requests. Device availability, SOC, efficiency
and connection limits determine what is physically applied. Entity mode can
report requested and applied actions separately.

Use the :doc:`../guides/interfaces_flat_entity` guide for table/map payloads,
or :doc:`../usage/custom_controller` to implement a flat-interface controller.
