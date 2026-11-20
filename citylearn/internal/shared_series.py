"""Share bit-identical calendar and default time series between the buildings of one environment.

Every building holds its own full copy of each energy-simulation series for the whole simulation window.
The calendar columns, and the series a dataset leaves at their defaults, are usually the same in every
building: with 17 buildings of a year at 15 s, they are about 1.4 GB of copies. Buildings loaded by the same
loader therefore share one array per distinct series. A shared array is made read-only, so an in-place write
raises instead of changing the other buildings; the simulator only ever reads these series.
"""

from typing import Any, Dict, Iterable, List, MutableMapping, Tuple

import numpy as np

ENERGY_SIMULATION_SHARED_SERIES = (
    'month',
    'hour',
    'minutes',
    'seconds',
    'day_type',
    'daylight_savings_status',
    'hvac_mode',
    'power_outage',
    'comfort_band',
    'occupant_count',
    'average_unmet_cooling_setpoint_difference',
)

# The pool lives in the loader's per-load time-series cache, so it is reset with it.
_POOL_KEY = ('__shared_series_pool__',)
_SAMPLE_SIZE = 64


def _fingerprint(array: np.ndarray) -> bytes:
    stride = max(1, array.shape[0] // _SAMPLE_SIZE)
    return array[::stride].tobytes()


def _same_bits(left: np.ndarray, right: np.ndarray) -> bool:
    # Bitwise, not numeric, equality: NaN payloads and signed zeros must match too.
    unsigned = f'u{left.dtype.itemsize}'
    return bool(np.array_equal(left.view(unsigned), right.view(unsigned)))


def share_identical_series(
    cache: MutableMapping[Any, Any], data: Any, names: Iterable[str] = ENERGY_SIMULATION_SHARED_SERIES,
) -> None:
    """Replace each named full series of `data` with a bit-identical array already loaded, if there is one."""

    pool: Dict[Tuple[Any, ...], List[np.ndarray]] = cache.setdefault(_POOL_KEY, {})

    for name in names:
        array = data.__dict__.get(f'_{name}')

        if (
            not isinstance(array, np.ndarray) or array.ndim != 1 or array.dtype.kind not in 'biuf'
            or not array.flags.c_contiguous or array.base is not None
        ):
            continue

        candidates = pool.setdefault((name, array.dtype.str, array.shape, _fingerprint(array)), [])

        for candidate in candidates:
            if _same_bits(candidate, array):
                setattr(data, name, candidate)
                break

        else:
            array.flags.writeable = False
            candidates.append(array)
