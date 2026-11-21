"""Expected and served service energy, shared by the KPIs and the `power_outage_unserved_energy` observation."""

from typing import Any, Callable, Iterable, List, Tuple

import numpy as np
import pandas as pd

# (expected demand, energy from the device, energy from storage) for each end use.
SERVICE_ENERGY_COMPONENTS = (
    ('cooling_demand', 'energy_from_cooling_device', 'energy_from_cooling_storage'),
    ('heating_demand', 'energy_from_heating_device', 'energy_from_heating_storage'),
    ('dhw_demand', 'energy_from_dhw_device', 'energy_from_dhw_storage'),
    ('non_shiftable_load', 'energy_to_non_shiftable_load', None),
)


def validate_power_outage_signal(values: Iterable[Any], *, source: str = 'power_outage') -> np.ndarray:
    """Convert `values` to a 1-D `float32` array and reject NaN, blank, or infinite flags."""

    try:
        arr = np.array(values, dtype='float32')
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f'{source} must contain finite numeric outage flags (0 for grid-connected, non-zero for outage).'
        ) from exc

    if not np.all(np.isfinite(arr)):
        bad = np.flatnonzero(~np.isfinite(arr))[:5].tolist()
        raise ValueError(
            f'{source} contains non-finite value(s) (NaN, blank cell, or inf) at row index(es) {bad}. '
            'Use 0 for grid-connected steps and a finite non-zero value for power outages.'
        )

    return arr


def is_power_outage_value(value: Any) -> bool:
    """Whether scalar `value` is a finite non-zero outage flag."""

    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return False

    return bool(np.isfinite(scalar) and scalar != 0.0)


def power_outage_mask(values: Any) -> np.ndarray:
    """Boolean mask of finite non-zero outage flags in 1-D sequence `values`."""

    try:
        arr = np.asarray(values, dtype='float64')
    except (TypeError, ValueError):
        arr = pd.to_numeric(pd.Series(values), errors='coerce').to_numpy(dtype='float64', na_value=np.nan)

    return np.isfinite(arr) & (arr != 0.0)


def service_energy_components(building, take: Callable[[str], object]) -> Tuple[List[object], List[object]]:
    """Expected and served cooling, heating, DHW and non-shiftable load energy of `building`, in kWh.

    `take(name)` returns the values of the building attribute `name`: a series for the KPIs or one time step for
    observations. Demand and device histories are in dataset energy and are scaled by `time_step_ratio`; storage
    balances are already in control-step kWh.
    """

    scale = float(getattr(building, 'time_step_ratio', 1.0) or 1.0)
    expected, served = [], []

    for demand, device, storage in SERVICE_ENERGY_COMPONENTS:
        expected.append(take(demand)*scale)
        value = take(device)*scale

        if storage is not None:
            value = value + take(storage)

        served.append(value)

    return expected, served


def unserved_energy(building, time_step: int) -> float:
    """Energy `building` left unserved at `time_step` during a power outage, in kWh, and 0.0 without an outage.

    Uses the definition of the `power_outage_normalized_unserved_energy_total` KPI: expected minus served energy,
    where each end use counts at most its own demand, with non-finite and negative totals treated as 0.
    """

    if not building.simulate_power_outage or not is_power_outage_value(building.power_outage_signal[time_step]):
        return 0.0

    expected, served = service_energy_components(building, lambda name: getattr(building, name)[time_step])
    expected = np.asarray(expected, dtype='float64')
    served = np.minimum(expected, np.asarray(served, dtype='float64'))
    total_expected, total_served = float(expected.sum()), float(served.sum())
    total_expected = max(total_expected, 0.0) if np.isfinite(total_expected) else 0.0
    total_served = max(total_served, 0.0) if np.isfinite(total_served) else 0.0

    return max(total_expected - total_served, 0.0)
