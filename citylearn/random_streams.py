"""Versioned derivation of the simulator's random streams.

CityLearn draws random values for unspecified device parameters, the state of charge of electric
vehicles away from their charger, occupant set-point interactions and stochastic power outages.
``random_stream_version`` selects how those streams are derived from ``random_seed``:

``'v1'``
    The derivation of CityLearn 3.6.0 and earlier, kept so that an existing seed reproduces
    earlier results. Every device parameter is the first draw of a new ``RandomState``, so all
    of them sit at the same quantile; the electric-vehicle drift seed is ``seed + episode``, so
    seed ``s`` in episode 1 repeats seed ``s + 1`` in episode 0; every occupant draws
    ``RandomState(seed + time_step)``, the same value in every building and episode; and
    stochastic outages skip day 0 and the partial last day and floor their durations.
``'v2'`` (default)
    Each stream comes from :class:`numpy.random.SeedSequence` with the seed as entropy and the
    purpose, entity and episode as its spawn key, so streams for different purposes, objects
    and episodes are independent. Each object keeps one generator per stream.
"""

import hashlib
import json
from typing import Any, Hashable, Tuple, Union

import numpy as np

RANDOM_STREAM_VERSIONS: Tuple[str, ...] = ('v1', 'v2')
DEFAULT_RANDOM_STREAM_VERSION = 'v2'
LEGACY_RANDOM_STREAM_VERSION = 'v1'

# Stream purposes. A purpose is part of every spawn key, so two purposes never share a stream.
DEVICE_PARAMETERS = 'device_parameters'
EV_AWAY_SOC_DRIFT = 'ev_away_soc_drift'
EV_SUSPENDED_SOC_DRIFT = 'ev_suspended_soc_drift'
OCCUPANT_SETPOINT_INTERACTION = 'occupant_setpoint_interaction'
POWER_OUTAGE = 'power_outage'


def parse_random_stream_version(value: Union[str, int, None], path: str = 'random_stream_version') -> str:
    """Return the canonical random-stream version for `value`; None gives the default."""

    if value is None:
        return DEFAULT_RANDOM_STREAM_VERSION

    if isinstance(value, bool):
        raise ValueError(f'{path} must be one of {RANDOM_STREAM_VERSIONS}, got {value!r}.')

    text = str(value).strip().lower()
    text = text if text.startswith('v') else f'v{text}'

    if text not in RANDOM_STREAM_VERSIONS:
        raise ValueError(f'{path} must be one of {RANDOM_STREAM_VERSIONS}, got {value!r}.')

    return text


def _canonical(part: Any) -> Any:
    if isinstance(part, (bool, np.bool_)):
        return bool(part)
    if isinstance(part, (int, np.integer)):
        return int(part)
    if isinstance(part, (str, float)):
        return part
    if isinstance(part, np.floating):
        return float(part)
    if isinstance(part, (list, tuple)):
        return [_canonical(p) for p in part]
    if part is None:
        return None
    raise TypeError(f'Random stream key parts must be str, int, float, None or sequences, got {type(part).__name__}.')


def spawn_key(purpose: str, *parts: Hashable) -> Tuple[int, ...]:
    """Fixed-width spawn key for a purpose and its parts.

    The parts are serialised as JSON before hashing, so keys such as ``('a', 'bc')`` and
    ``('ab', 'c')`` stay distinct. The result is eight 32-bit words of SHA-256.
    """

    payload = json.dumps([str(purpose), *[_canonical(p) for p in parts]], separators=(',', ':')).encode('utf-8')
    digest = hashlib.sha256(payload).digest()

    return tuple(int.from_bytes(digest[i:i + 4], 'big') for i in range(0, 32, 4))


def seed_sequence(seed: int, purpose: str, *parts: Hashable) -> np.random.SeedSequence:
    """:class:`numpy.random.SeedSequence` for `seed`, `purpose` and the entity/episode `parts`."""

    if isinstance(seed, (bool, np.bool_)) or int(seed) != seed or int(seed) < 0:
        raise ValueError(f'random_seed must be a non-negative integer, got {seed!r}.')

    return np.random.SeedSequence(entropy=int(seed), spawn_key=spawn_key(purpose, *parts))


def generator(seed: int, purpose: str, *parts: Hashable) -> np.random.Generator:
    """New :class:`numpy.random.Generator` (PCG64) for `seed`, `purpose` and `parts`."""

    return np.random.Generator(np.random.PCG64(seed_sequence(seed, purpose, *parts)))


def stream_id(seed: int, purpose: str, *parts: Hashable) -> int:
    """A 32-bit identifier of the stream, for metadata and comparisons; not a seed to draw from."""

    return int(seed_sequence(seed, purpose, *parts).generate_state(1, dtype=np.uint32)[0])
