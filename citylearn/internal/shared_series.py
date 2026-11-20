"""Share bit-identical calendar series between the buildings of one environment.

Every building holds its own full copy of each energy-simulation series for the whole simulation window.
The calendar columns are usually the same in every building: with 17 buildings of a year at 15 s, the six of
them are about 0.8 GB of copies. Buildings loaded by the same loader therefore share one array per distinct
calendar series. A shared array is made read-only, so an in-place write raises instead of changing the other
buildings; the simulator only reads the calendar. Series that users or the simulator may write in place, such
as `hvac_mode` or `power_outage`, stay building-specific.
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
            or not array.flags.c_contiguous or (array.base is not None and array.flags.writeable)
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
