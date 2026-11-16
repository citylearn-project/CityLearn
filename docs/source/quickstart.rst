=====================
Your first simulation
=====================

Install CityLearn as described in :doc:`installation`, save the following
code as ``first_simulation.py``, and run ``python first_simulation.py``.

.. literalinclude:: ../../examples/first_simulation.py
   :language: python

What happens in this example?
*****************************

1. The environment resolves a public dataset by name. On first use it downloads
   the data from the official repository at the installed package's version tag
   and caches it locally. Internet access is needed for that download;
   no repository clone or private dataset is required.
2. ``reset(seed=0)`` starts the episode and returns observations plus information.
3. The built-in ``BusinessAsUsualAgent`` selects actions. It charges connected EVs
   at once up to the user's requested departure SOC, starts ready flexible
   appliances and uses stationary storage for PV self-consumption.
4. ``step`` returns observations, rewards, termination, truncation and information,
   in that order. The loop stops when either termination flag is true.
5. ``evaluate_v2()`` returns a table with ``cost_function``, ``value``, ``name`` and
   ``level`` columns. The example prints four district/community indicators: cost, imported energy,
   feasible EV minimum service and residual phase-limit violation energy.

This dataset uses hourly timesteps. The 24-state episode has 23 control
transitions: the final state is the observation after the last action.
Increase the episode window for a study covering more EV departures or service
events.

Read the results
****************

Start with total cost, imported energy, minimum EV departure service and
electrical-limit violations. The :doc:`guides/scorecard` explains these together,
including the distinction between service and target-SOC accuracy. The
:doc:`guides/kpis_reference` explains KPI families, units and baselines.

To save the full KPI table:

.. code-block:: python

   kpis.to_csv("kpis.csv", index=False)

``evaluate_v2()`` includes a native business-as-usual comparison by default.
Use ``include_business_as_usual=False`` when you only need the current run and
the conventional baseline; see :doc:`guides/scorecard` for the difference.

Next steps
**********

* :doc:`guides/features`: choose assets and services.
* :doc:`guides/baselines`: understand the default controller and references.
* :doc:`guides/running_simulations`: use a local schema, the CLI or result exports.
* :doc:`guides/interfaces_flat_entity`: choose flat vectors or entity tables.
* :doc:`usage/agents`: explore RBC and reinforcement-learning tutorials.
* :doc:`ui`: inspect exported simulation data in CityLearn UI.
