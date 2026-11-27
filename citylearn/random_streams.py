"""Versioned derivation of the simulator's random streams.

CityLearn draws random values for unspecified device parameters, the state of charge of electric
vehicles away from their charger, occupant set-point interactions and stochastic power outages.
``random_stream_version`` names how those streams are derived from ``random_seed``:

``'v2'``
    The only version. Each stream comes from :class:`numpy.random.SeedSequence` with the seed as
    entropy and the purpose, entity and episode as its spawn key, so streams for different purposes,
    objects and episodes are independent. Each object keeps one generator per stream.

An environment built with a ``random_stream_namespace`` adds ``('namespace', <namespace>)`` to the key of
every stream it derives from its seed, so two environments with the same seed and the same building and
EV names still draw independently. :class:`~citylearn.multi_community.MultiCommunityEnv` gives each
community its ``community_id`` as namespace. Without a namespace the keys are unchanged.

Version ``'v1'``, the derivation of CityLearn 3.6.0, was removed in CityLearn 3.8.1 (#466); CityLearn
3.7 reproduces it. The setting accepts ``'v2'``, ``2`` and ``"2"``, as parsed by
:py:func:`citylearn.internal.versions.parse_version`.

Agents follow the version of their environment: :class:`~citylearn.agents.q_learning.TabularQLearning`
and :class:`~citylearn.agents.marlisa.MARLISA` keep one generator per purpose and episode.
:class:`~citylearn.end_use_load_profiles.neighborhood.Neighborhood` derives the seed of each
partial-load simulation from the neighborhood seed, the building and the simulation index.
"""

import hashlib
import json
from typing import Any, Hashable, Tuple, Union

import numpy as np

from citylearn.internal.versions import parse_version

RANDOM_STREAM_VERSIONS: Tuple[str, ...] = ('v2',)
DEFAULT_RANDOM_STREAM_VERSION = 'v2'

# Stream purposes. A purpose is part of every spawn key, so two purposes never share a stream.
DEVICE_PARAMETERS = 'device_parameters'
EV_AWAY_SOC_DRIFT = 'ev_away_soc_drift'
EV_SUSPENDED_SOC_DRIFT = 'ev_suspended_soc_drift'
OCCUPANT_SETPOINT_INTERACTION = 'occupant_setpoint_interaction'
POWER_OUTAGE = 'power_outage'
AGENT_EXPLORATION = 'agent_exploration'
AGENT_COORDINATION_ORDER = 'agent_coordination_order'
PARTIAL_LOAD_SIMULATION = 'partial_load_simulation'


def parse_random_stream_version(value: Union[str, int, None], path: str = 'random_stream_version') -> str:
    """Return the canonical random-stream version for `value`, ``'v2'``; None gives the default.

    Raises
    ------
    ValueError
        If `value` is not ``'v2'``, ``2`` or ``"2"``. The error for ``'v1'`` says it was removed in
        CityLearn 3.8.1.
    """

    return parse_version(value, (2,), path, removed=(1,), prefix='v')


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


def namespace_parts(namespace: Union[str, None]) -> Tuple[str, ...]:
    """Key parts that separate the streams of `namespace`: empty without one."""

    return () if namespace is None else ('namespace', str(namespace))


def namespaced_key(key: Tuple[Any, ...], namespace: Union[str, None]) -> Tuple[Any, ...]:
    """`key` followed by the parts of `namespace`, or `key` itself without one."""

    return (*tuple(key), *namespace_parts(namespace))


def parse_random_stream_namespace(value: Any, path: str = 'random_stream_namespace') -> Union[str, None]:
    """Return `value` as a namespace: None, or a non-empty string without surrounding spaces."""

    if value is None:
        return None

    if not isinstance(value, str) or value.strip() == '':
        raise ValueError(f'{path} must be None or a non-empty string, got {value!r}.')

    return value.strip()


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


def derived_seed(seed: int, purpose: str, *parts: Hashable) -> int:
    """32-bit integer seed for a consumer that only accepts an integer, derived like :func:`generator`.

    Use it where the stream is created by code that takes a plain seed, such as a simulator that builds
    its own ``RandomState``; otherwise prefer :func:`generator`.
    """

    return int(seed_sequence(seed, purpose, *parts).generate_state(1, dtype=np.uint32)[0])


def partial_load_simulation_seed(
    seed: int, building_id: Union[int, str], simulation_index: int, random_stream_version: Union[str, int, None] = None
) -> int:
    """Seed of partial-load simulation `simulation_index` of building `building_id` in a generated neighborhood.

    It is derived from `seed`, the building and the simulation index. `random_stream_version` is checked
    with :py:func:`parse_random_stream_version`.
    """

    parse_random_stream_version(random_stream_version)

    return derived_seed(seed, PARTIAL_LOAD_SIMULATION, int(building_id), int(simulation_index))
