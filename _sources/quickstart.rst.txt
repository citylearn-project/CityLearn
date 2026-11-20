=====================
Your first simulation
=====================

This page is the quickstart: two short scripts, about a minute each including
the first dataset download. Install CityLearn as described in
:doc:`installation`. Terms in *italics* are defined in the :doc:`glossary`.

Step 1: run one day with the reference controller
*************************************************

Save the following code as ``first_simulation.py`` and run
``python first_simulation.py``.

.. literalinclude:: ../../examples/first_simulation.py
   :language: python

Expected output:

.. literalinclude:: ../../examples/first_simulation.out
   :language: text

Values may differ in the last digits on other platforms.

What happens in this example?
-----------------------------

1. The environment resolves a public *dataset* by name. On first use it downloads
   the data from the official repository at the installed package's version tag
   and caches it locally. Internet access is needed for that download;
   no repository clone or private dataset is required. The :doc:`guides/dataset_catalogue`
   lists every public dataset.
2. ``reset(seed=0)`` starts the *episode* and returns observations plus information.
3. The built-in ``BusinessAsUsualAgent`` selects actions. It is the *business as
   usual* (BAU) controller: it charges connected EVs at full power until 100% SOC
   (``ev_charge_target='requested'`` stops at the user's requested departure SOC
   instead), starts ready flexible appliances and uses stationary storage for PV
   self-consumption.
4. ``step`` returns observations, rewards, termination, truncation and information,
   in that order. The loop stops when either termination flag is true.
5. ``evaluate_v2()`` returns the KPI table, with ``cost_function``, ``value``,
   ``name`` and ``level`` columns. The example prints four district indicators:
   cost, imported energy, feasible EV minimum service and residual phase-limit
   violation energy.

This dataset uses hourly time steps. The 24-state episode has 23 control
transitions: the final state is the observation after the last action.

Because this run uses the BAU controller itself, it is also its own reference:
every difference to the BAU in its KPI table is zero. Step 2 shows what a
different controller changes.

Step 2: compare a controller with the BAU
*****************************************

Save the following code as ``compare_with_business_as_usual.py`` and run it. It
runs the same day with ``RBCBasicPolicy``, a rule-based controller that charges
EVs only as much as their departure target needs and starts appliances when they
are urgent or cheap.

.. literalinclude:: ../../examples/compare_with_business_as_usual.py
   :language: python

Expected output:

.. literalinclude:: ../../examples/compare_with_business_as_usual.out
   :language: text

``evaluate_v2()``, which ``scorecard()`` calls, runs the BAU on the same day and
reports it next to the controller: ``*_control_*`` rows are this run,
``*_business_as_usual_*`` rows the BAU and ``*_delta_to_business_as_usual_*`` rows
their difference. Here the controller imports less energy and costs about 25%
less than the BAU, while every EV still leaves with its minimum acceptable charge.

``env.scorecard()`` returns the default selection of the KPI table
(``CityLearnEnv.SCORECARD_DEFAULT_KPIS``); pass ``level="building"`` for the
building rows.

Read the results
****************

Start with total cost, imported energy, minimum EV departure service and
electrical-limit violations. The :doc:`guides/scorecard` explains these together,
including the distinction between service and target-SOC accuracy. The
:doc:`kpis` page leads to the definitions, units and references of every KPI.

To save the full KPI table:

.. code-block:: python

   kpis = env.evaluate_v2()
   kpis.to_csv("kpis.csv", index=False)

``evaluate_v2()`` includes the BAU comparison by default. Use
``include_business_as_usual=False`` when you only need the current run and the
conventional *baseline*; the :doc:`glossary` explains the difference.

Next steps
**********

* :doc:`overview/index`: the model behind the simulation.
* :doc:`guides/features`: choose assets and services.
* :doc:`guides/baselines`: understand the default controller and references.
* :doc:`guides/running_simulations`: use a local schema, the CLI or result exports.
* :doc:`guides/interfaces_flat_entity`: choose flat vectors or entity tables.
* :doc:`usage/agents`: explore RBC and reinforcement-learning tutorials.
* :doc:`ui`: inspect exported simulation data in CityLearn UI.
