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
* :doc:`guides/kpis_reference` — what each family measures, its equations,
  district and portfolio aggregation, and undefined values.
* :doc:`guides/KPI_V2_TREE` — the KPI catalogue: every name the simulator emits,
  with its meaning, grouped by family. A test fails when an emitted name is
  missing from it.
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

The table contains ``cost_function``, ``value``, ``name`` and ``level``.
``level`` is ``building`` (one row per member, ``name`` is the building) or
``district`` (one row for the community, ``name`` is ``District``).
``MultiCommunityEnv.evaluate_v2()`` adds a ``community_id`` column and
``portfolio`` rows that aggregate the communities' district rows; the
:doc:`guides/kpis_reference` gives the aggregation rules.
The last part of each KPI name is its unit (``kwh``, ``kw``, ``eur``, ``kgco2``,
``ratio``...). Feature-specific rows follow the scenario configuration, and a
KPI that is undefined for the run, such as a service ratio without any event to
serve, is missing (NaN) rather than 0 or 1.

To keep only the default scorecard rows:

.. code-block:: python

   scorecard = env.scorecard(kpis)

Families
********

Every KPI belongs to one of these families. The :doc:`guides/KPI_V2_TREE` lists
their names and the :doc:`guides/kpis_reference` explains each one.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Family
     - Measures
   * - Cost
     - Operating cost, against the conventional baseline and the BAU.
   * - Grid energy and load shape
     - Imports, exports, net exchange, peaks, load factor and ramping.
   * - Emissions
     - Carbon emissions of the grid import.
   * - Solar self-consumption
     - PV generation, export, curtailment and the share used locally.
   * - Community market
     - Local trading, settled and counterfactual costs, savings and local shares.
   * - Batteries
     - Charge, discharge, throughput, equivalent full cycles and capacity fade.
   * - Electrical service and phases
     - Limit violations, requested pressure, phase imbalance and phase peaks.
   * - Electric vehicles
     - Departure service, target accuracy, charging and V2G.
   * - EV departure audit
     - Departure service by feasibility class, with population and coverage counts.
   * - Flexible appliances
     - Completed and missed cycles, start delay and served energy.
   * - Flexible-appliance audit
     - Cycle service from metered energy, with admissibility and coverage counts.
   * - Escalators
     - Passenger service, operating-state changes and electricity use.
   * - Comfort and resilience
     - Thermal discomfort and service during outages, per building.
   * - Thermal-service audit
     - Discomfort and unserved thermal energy pooled over occupied steps.
   * - Equity
     - The distribution of cost benefits between members.
   * - Equity audit
     - The same distribution, with population and coverage counts.
   * - Demand response
     - Requested, delivered and credited response, shortfall and settlement.
   * - Demand-response audit
     - Request service and baseline coverage by request purpose.
   * - Robustness
     - Observation, forecast, action and asset perturbation counters.
   * - Energy provenance
     - Where PV, grid and stored energy went, and the carbon it carried.
   * - Dynamic topology
     - A placeholder row for members that never joined.

Which KPI to use
****************

Some quantities have more than one row. Use these for comparisons:

* **Discomfort:** ``district_thermal_service_audit_discomfort_ratio``, which pools
  occupied steps over the members. ``district_comfort_resilience_*`` rows are
  plain means of the building values.
* **Benefit inequality:** ``district_equity_audit_positive_benefit_gini_ratio``.
  It has the same value as ``district_equity_distribution_gini_benefit_ratio``, but its name
  states that negative benefits are clipped, and its coverage counts are reported
  with it.
* **Local share of demand:** ``district_solar_self_consumption_community_market_import_share_ratio``.
  ``district_solar_self_consumption_community_market_local_share_of_demand_ratio``
  has the same formula and is kept as an alias; at building level,
  ``local_share_of_demand`` is the only demand-share row.
* **EV and flexible-appliance service:** the audit rows count every departure or
  cycle and classify its feasibility; the :doc:`guides/kpis_reference` explains
  when to read the service rows instead.

``evaluate()`` retains historical cost-function names. ``evaluate_v2()`` is the
structured KPI API used by CityLearn v3; its method name is not a software
version number.

To explore the same exported results graphically, continue to :doc:`ui`.
