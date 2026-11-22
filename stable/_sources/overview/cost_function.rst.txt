=============
Cost Function
=============

The :py:class:`citylearn.cost_function.CostFunction` utilities calculate common
time-series metrics such as cost, emissions, peaks, ramping, discomfort and
unserved energy. They are useful when implementing or inspecting an evaluation.

For a completed environment, use ``env.evaluate_v2()`` to obtain named
building/district KPIs. Start with :doc:`../kpis`, then consult
:doc:`../guides/kpis_reference` for definitions and :doc:`../guides/baselines`
for the reference conditions.

The cost-function API remains available in :py:mod:`citylearn.cost_function`.
