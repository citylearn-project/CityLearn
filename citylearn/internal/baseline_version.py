"""Versioned definitions of the default KPI baseline.

The baseline version fixes what the ``*_without_storage`` counterfactual series keep from the
controlled run. They are the default ``baseline`` of :py:meth:`citylearn.citylearn.CityLearnEnv.evaluate`
and :py:meth:`citylearn.citylearn.CityLearnEnv.evaluate_v2`, so the version changes every
``*_baseline_*``, ``*_delta_*`` (not ``*_delta_to_business_as_usual_*``) and ``*_ratio_to_baseline_*``
value on datasets with EV chargers, the equity KPIs built on them, and the legacy ``evaluate()`` table.
The version also fixes how the native BAU runs the HVAC, so on datasets with HVAC actions it changes every
``*_business_as_usual`` row and every ``*_delta_to_business_as_usual_*`` and ``*_ratio_to_business_as_usual_*``
value as well (below).
A run selects a version with the ``baseline_version`` schema key or the
:py:class:`citylearn.citylearn.CityLearnEnv` argument of the same name; the argument takes precedence.
Runs record it in their metadata.

Versions
--------
2
    The only version. Version 1, the baseline of CityLearn 3.6.0, was removed in CityLearn 3.8.1 (#466);
    CityLearn 3.7 reproduces it.

    The baseline removes the battery, the thermal storage and the EV charging of the
    controlled run, and adds back the EV charging of the native BAU of the same scenario with the
    ``'full'`` target: each car is charged on arrival at maximum power until it is full, and never
    discharged. The cars get the energy they need, without V2G, and the baseline is the same whatever the
    controller does with the cars or the storage, so a controller that leaves the cars short does not
    lower its own baseline (#365). The deferrable appliances stay as the controller ran them. So does the
    HVAC, except in buildings with temperature dynamics (LSTM), where the default condition uses the
    dataset's ideal-load heating and cooling demand. With dynamic topology, a battery removed or replaced
    by an event keeps what it moved before the event in the building's series, so the baseline removes it.

    The BAU charging comes from the BAU sidecar
    (:py:meth:`citylearn.citylearn.CityLearnEnv.run_business_as_usual_baseline`), which is therefore run
    for every evaluation of a dataset with EV chargers, also by the legacy ``evaluate()`` and by
    ``evaluate_v2(include_business_as_usual=False)``, and it uses the ``'full'`` target whatever
    ``business_as_usual_ev_charge_target`` is. Where the sidecar cannot run (inputs, buildings or
    devices changed after loading), evaluating raises.
    Datasets without chargers need no sidecar for the baseline.

    In addition, the native BAU (:py:class:`citylearn.agents.baseline.BusinessAsUsualAgent` and the BAU
    sidecar that gives the ``*_business_as_usual`` rows) runs the HVAC as a building without optimisation
    does (#362): each step its ``heating_device``, ``cooling_device`` or ``cooling_or_heating_device`` action is
    the one that delivers the dataset's own heating or cooling demand (the as-simulated ``heating_demand`` and
    ``cooling_demand`` of the building files), clipped to the action bounds and device limits. On datasets with
    HVAC actions the BAU definition gets the suffix ``+hvac-dataset-demand-v1``. On datasets without HVAC
    actions the BAU sends no HVAC action, and its definition has no suffix. The controlled run is never changed.
"""

from typing import Any

from citylearn.internal.versions import parse_version

BASELINE_VERSIONS = (2,)
#: Versions removed in CityLearn 3.8.1 (#466).
REMOVED_BASELINE_VERSIONS = (1,)
LATEST_BASELINE_VERSION = 2
DEFAULT_BASELINE_VERSION = 2


def resolve_baseline_version(value: Any = None, path: str = 'baseline_version') -> int:
    """Return the baseline version selected by `value`, or the default when `value` is ``None``.

    Parsed by :py:func:`citylearn.internal.versions.parse_version`.

    Raises
    ------
    ValueError
        If `value` is not one of :py:data:`BASELINE_VERSIONS`.
    """

    return parse_version(
        value, BASELINE_VERSIONS, path, default=DEFAULT_BASELINE_VERSION, removed=REMOVED_BASELINE_VERSIONS,
    )
