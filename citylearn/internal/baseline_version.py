"""Versioned definitions of the default KPI baseline.

The baseline version fixes what the ``*_without_storage`` counterfactual series keep from the
controlled run. They are the default ``baseline`` of :py:meth:`citylearn.citylearn.CityLearnEnv.evaluate`
and :py:meth:`citylearn.citylearn.CityLearnEnv.evaluate_v2`, so the version changes every
``*_baseline_*``, ``*_delta_*`` (not ``*_delta_to_business_as_usual_*``) and ``*_ratio_to_baseline_*``
value on datasets with EV chargers, the equity KPIs built on them, and the legacy ``evaluate()`` table.
Nothing simulated changes.
A run selects a version with the ``baseline_version`` schema key or the
:py:class:`citylearn.citylearn.CityLearnEnv` argument of the same name; the argument takes precedence.

Versions
--------
1
    The baseline of CityLearn 3.6.0 and earlier: it removes the battery, the thermal storage and the
    EV charging, and adds nothing back, so on EV datasets it is a community whose cars never charge (#365).
2
    The baseline removes the battery, the thermal storage and the EV charging of the controlled run,
    and adds back the EV charging of the native BAU of the same scenario with the ``'full'`` target:
    each car is charged on arrival at maximum power until it is full, and never discharged. The cars
    get the energy they need, without V2G, and the baseline is the same whatever the controller does
    with the cars or the storage, so a controller that leaves the cars short does not lower its own
    baseline. The deferrable appliances and the HVAC stay as the controller ran them.

    The BAU charging comes from the BAU sidecar
    (:py:meth:`citylearn.citylearn.CityLearnEnv.run_business_as_usual_baseline`), which is therefore run
    for every evaluation of a dataset with EV chargers, also by the legacy ``evaluate()`` and by
    ``evaluate_v2(include_business_as_usual=False)``, and it uses the ``'full'`` target whatever
    ``business_as_usual_ev_charge_target`` is. Where the sidecar cannot run (inputs, buildings or
    devices changed after loading), evaluating with version 2 raises; version 1 needs no sidecar.
    Datasets without chargers give the same values under both versions.
"""

from typing import Any

BASELINE_VERSIONS = (1, 2)
LATEST_BASELINE_VERSION = 2
DEFAULT_BASELINE_VERSION = LATEST_BASELINE_VERSION


def resolve_baseline_version(value: Any = None, path: str = 'baseline_version') -> int:
    """Return the baseline version selected by `value`, or the default when `value` is ``None``.

    Raises
    ------
    ValueError
        If `value` is not one of :py:data:`BASELINE_VERSIONS`. Booleans and non-integral numbers are
        rejected rather than coerced.
    """

    if value is None:
        return DEFAULT_BASELINE_VERSION

    version = None

    if isinstance(value, bool):
        version = None
    elif isinstance(value, int):
        version = value
    elif isinstance(value, float) and value.is_integer():
        version = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        version = int(value.strip())
    else:
        import numpy as np

        if isinstance(value, np.integer):
            version = int(value)

    if version not in BASELINE_VERSIONS:
        raise ValueError(f'{path} must be one of {list(BASELINE_VERSIONS)}, got {value!r}.')

    return version


def baseline_version_of(owner: Any) -> int:
    """Baseline version of a building or environment; the default when it has none."""

    version = getattr(owner, 'baseline_version', None)
    return DEFAULT_BASELINE_VERSION if version is None else int(version)
