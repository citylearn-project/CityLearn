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
    * battery discharge is limited by `Battery.discharge_power_curve`, flat at the nominal power by
      default, instead of the charging curve `capacity_power_curve` (#227);
    * during an outage the battery discharges after the step's thermal demand and thermal storage
      discharges and only up to the islanded load that PV leaves (#229);
    * electrical-service headroom is shared among the powers devices can draw, not the raw requests
      (#231), after the thermal and non-shiftable updates, and the recorded power, headroom and
      violation come from the settled import (#230);
    * a deferrable cycle starts on the current step's information only, and an outage that later
      cuts its supply stops it (#232);
    * the entity observations of a battery's energy to full and charge headroom stop at its degraded
      capacity, where `Battery.charge` stops, instead of at its nominal capacity;
    * occupant set-point changes stop at
      `LogisticRegressionOccupantInteractionBuilding.set_point_limits`, [15, 30] C by default (#352);
    * each SOC column of a charger file has one unit, percent if any value is above 1, decided
      from the whole column, so 1 in a percent column is 1 % and not 100 % (#368);
    * a charger without `max_discharging_power` cannot discharge (V2G off), and one without
      `max_charging_power` charges up to its `nominal_power`; version 1 gives both 50 kW (#369);
    * flat actions outside the action space, and flat vectors sent to an entity environment, are
      clipped to the space, as entity table and map payloads always were; version 1 applies them as
      given;
    * the flat deferrable `*_kwh` observations are bounded by the appliances' cycle energies instead
      of the placeholder [-1, 1e6], which normalisation turned into constants.
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
