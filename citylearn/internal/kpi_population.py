"""Evaluation-local membership masks; never cache physical values or KPI results."""
from functools import wraps

import numpy as np


def _identity(env):
    topology = env._topology_service
    tracker = getattr(env, 'episode_tracker', None)
    return (id(env), getattr(tracker, 'episode', None),
            getattr(tracker, 'episode_start_time_step', None),
            getattr(tracker, 'episode_end_time_step', None),
            getattr(env, 'time_step', None), getattr(env, 'topology_mode', None),
            id(topology._active_member_history), getattr(topology, '_topology_version', None))


class ActivePopulation:
    """Snapshot sparse topology transitions once; construct masks lazily.

    Thermal/condition queries carry the current membership backwards before the
    first recorded transition, matching active_member_ids_at. Energy masking
    instead leaves that prefix zero, matching its established interval loop.
    Arrays are read-only and keyed by member, actual series horizon and semantics.
    """

    def __init__(self, env):
        self.identity = _identity(env)
        topology = env._topology_service
        self.transitions = tuple((step, frozenset(names))
                                 for step, names in sorted(topology._active_member_history.items()))
        self.default_members = frozenset(topology._active_member_ids)
        self.lifecycle = getattr(env, 'topology_member_lifecycle', {})
        self._active_masks = {}
        self._energy_masks = {}

    def mask(self, name, length, *, energy=False):
        cache = self._energy_masks if energy else self._active_masks
        key = (name, length)
        if key not in cache:
            mask = np.full(length, False if energy else name in self.default_members, dtype=bool)
            for i, (start, names) in enumerate(self.transitions):
                end = self.transitions[i + 1][0] if i + 1 < len(self.transitions) else length
                if energy:
                    # Preserve the original energy slice bounds exactly.
                    if name in names:
                        mask[start:min(end, length)] = True
                else:
                    mask[max(start, 0):max(0, min(end, length))] = name in names
            mask.flags.writeable = False
            cache[key] = mask
        return cache[key]

    @property
    def mask_bytes(self):
        return sum(mask.nbytes for cache in (self._active_masks, self._energy_masks)
                   for mask in cache.values())


def current_population(service):
    population = getattr(service, '_evaluation_population', None)
    if population is not None and population.identity != _identity(service.env):
        population = ActivePopulation(service.env)
        service._evaluation_population = population
    return population


def population_scope(function):
    """Share nested KPI readers, release the snapshot on success or failure."""
    @wraps(function)
    def evaluate(service, *args, **kwargs):
        if getattr(service.env, 'topology_mode', 'static') != 'dynamic':
            return function(service, *args, **kwargs)
        previous = getattr(service, '_evaluation_population', None)
        population = current_population(service)
        if population is None:
            population = ActivePopulation(service.env)
        service._evaluation_population = population
        try:
            return function(service, *args, **kwargs)
        finally:
            if previous is None:
                del service._evaluation_population
            else:
                service._evaluation_population = previous
    return evaluate
