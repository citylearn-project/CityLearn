====
KPIs
====

KPIs measure the completed simulation: energy, cost, emissions, service,
comfort and electrical performance. They are available from Python and CSV
exports; using the UI is optional. This page is the entry point to every KPI
page.

Choose what to read
*******************

* :doc:`guides/scorecard` — start here: how to read a compact set of KPIs and
  compare controllers.
* :doc:`guides/scorecard_kpi_names` — the default selection, returned by
  ``env.scorecard()``.
* :doc:`guides/kpis_reference` — definitions, units, equations and metric families.
* :doc:`guides/KPI_V2_TREE` — every name, grouped by district/building and family.
* :doc:`guides/baselines` — the references behind ``baseline`` and
  ``business_as_usual`` values.
* :doc:`overview/cost_function` — the legacy cost functions of ``evaluate()``.

.. toctree::
   :hidden:
   :maxdepth: 1

   guides/scorecard
   guides/scorecard_kpi_names
   guides/kpis_reference
   guides/KPI_V2_TREE

List the KPIs in your run
*************************

After completing an episode:

.. code-block:: python

   kpis = env.evaluate_v2()
   names = kpis[["cost_function", "level"]].drop_duplicates()
   print(names.sort_values("cost_function").to_string(index=False))
   kpis.to_csv("kpis.csv", index=False)

The table contains ``cost_function``, ``value``, ``name``, ``level``, ``unit``
and ``description``. ``name`` identifies the building or district; ``level``
identifies the scope; ``unit`` (``kwh``, ``kw``, ``eur``, ``kgco2``, ``ratio``...)
is also the last part of the KPI name, and ``description`` defines the KPI in one
line. Feature-specific rows follow the scenario configuration, and a
KPI that is undefined for the run, such as a service ratio without any event to
serve, is missing (NaN) rather than 0 or 1.

To keep only the default scorecard rows:

.. code-block:: python

   scorecard = env.scorecard(kpis)

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
