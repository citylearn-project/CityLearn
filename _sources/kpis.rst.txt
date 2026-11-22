====
KPIs
====

KPIs measure the completed simulation: energy, cost, emissions, service,
comfort and electrical performance. They are available from Python and CSV
exports; using the UI is optional.

Choose what to read
*******************

* :doc:`guides/kpis_reference` — definitions, units, equations and metric families.
* :doc:`guides/KPI_V2_TREE` — names grouped by district/building and family.
* :doc:`guides/baselines` — the reference behind normalized results.
* :doc:`guides/scorecard` — a compact set for comparing controllers.
* :doc:`guides/scorecard_kpi_names` — the simulator's exact default selection.

List the KPIs in your run
*************************

After completing an episode:

.. code-block:: python

   kpis = env.evaluate_v2()
   names = kpis[["cost_function", "level"]].drop_duplicates()
   print(names.sort_values("cost_function").to_string(index=False))
   kpis.to_csv("kpis.csv", index=False)

The table contains ``cost_function``, ``value``, ``name`` and ``level``.
``name`` identifies the building or district; ``level`` identifies the scope.
Feature-specific rows follow the scenario configuration.

Main families
*************

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Family
     - Measures
   * - Cost and grid energy
     - Operating cost, imports, exports, net exchange, peaks and ramping.
   * - Emissions and PV
     - Carbon emissions, generation and local solar self-consumption.
   * - EVs and batteries
     - Departure service, target accuracy, charging, V2G, throughput and degradation.
   * - Electrical service
     - Residual violations, requested pressure and phase indicators.
   * - Flexible loads and escalators
     - Completed/missed cycles, delays, energy and passenger service.
   * - Comfort and resilience
     - Thermal discomfort and service during outages.
   * - Community market and equity
     - Local exchange, settlement costs, savings and their distribution.
   * - Demand response
     - Requested, delivered and credited response, shortfall and settlement.
   * - Robustness
     - Measurement, action and availability perturbation counters.

``evaluate()`` retains historical cost-function names. ``evaluate_v2()`` is the
structured KPI API used by CityLearn v3; its method name is not a software
version number.

To explore the same exported results graphically, continue to :doc:`ui`.
