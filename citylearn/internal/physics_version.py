"""Versioned physics definitions.

A physics version fixes the device and building physics a simulation uses, so that results stay
reproducible when a correction changes simulated values. A run selects a version with the
``physics_version`` schema key or the :py:class:`citylearn.citylearn.CityLearnEnv` argument of the
same name; the argument takes precedence.

Versions
--------
1
    The physics of CityLearn 3.6.0 and earlier.
2
    Corrected physics (tracking issue #226, theme 4):

    * the away-from-charger SOC drift of an EV keeps that step's standby loss (#236);
    * HVAC demand caps convert the requested energy to power before comparing it with the device's
      available power, which matters for steps longer than one hour (#235);
    * storage-tank autosizing covers one hour of peak demand power, and PV autosizing groups years
      and resamples the PVWatts output at the dataset resolution, which matters for sub-hourly
      data (#233).

    Datasets at a resolution of one hour or finer whose EVs have no standby loss and that do not
    autosize at sub-hourly resolution simulate identically under versions 1 and 2.
"""

from typing import Any

PHYSICS_VERSIONS = (1, 2)
LATEST_PHYSICS_VERSION = 2
DEFAULT_PHYSICS_VERSION = LATEST_PHYSICS_VERSION


def resolve_physics_version(value: Any = None, path: str = 'physics_version') -> int:
    """Return the physics version selected by `value`, or the default when `value` is ``None``.

    Raises
    ------
    ValueError
        If `value` is not one of :py:data:`PHYSICS_VERSIONS`. Booleans and non-integral numbers are
        rejected rather than coerced.
    """

    if value is None:
        return DEFAULT_PHYSICS_VERSION

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
        try:
            import numpy as np

            if isinstance(value, np.integer):
                version = int(value)
        except ImportError:  # pragma: no cover - numpy is a hard dependency
            pass

    if version not in PHYSICS_VERSIONS:
        raise ValueError(f'{path} must be one of {list(PHYSICS_VERSIONS)}, got {value!r}.')

    return version


def physics_version_of(owner: Any) -> int:
    """Physics version of a building, device or environment; the default when it has none."""

    version = getattr(owner, 'physics_version', None)
    return DEFAULT_PHYSICS_VERSION if version is None else int(version)
