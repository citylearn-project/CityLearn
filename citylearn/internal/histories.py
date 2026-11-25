"""Per-step histories kept in preallocated float64 buffers.

A list of floats costs about 32 bytes per value (pointer plus float object) and grows for the whole
episode. The classes here store the same values in a NumPy buffer sized for the episode (8 bytes per
value). When a caller reads :meth:`to_list` (for example ``CityLearnEnv.rewards``), a tracked ``list``
view is built on demand and extended incrementally as new steps execute so per-step ``[-1]`` monitoring
runs in constant time per step; any in-place mutation detaches that cached list before editing so caller
changes never alter the stored history or subsequent reads. :meth:`last` returns only the latest value
without materializing any public list. Every value that the buffer cannot reproduce (custom list
subclasses, other element types, non-list rows, out-of-order writes) moves the history to a plain list
built from the authoritative buffer values while preserving row types and defensive isolation.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from typing import Any

import numpy as np

_FLOAT = float
_NP_FLOAT = np.float64
_IMMUTABLE_SCALARS = (int, float, bool, str, bytes, complex, type(None), np.generic)
_CITYLEARN_ENV_CLS: type | None = None


def _to_plain_list(value: Any) -> Any:
    if type(value) is _TrackedList:
        return [_to_plain_list(v) for v in value]

    return value


class _TrackedList(list):
    """Public ``list`` view that detaches its owning history cache before any in-place mutation."""

    __slots__ = ('_owner',)

    def __init__(self, iterable=(), owner: Any = None):
        super().__init__(iterable)
        self._owner = owner

    def _detach(self) -> None:
        owner = getattr(self, '_owner', None)
        if owner is not None:
            self._owner = None
            owner._detach_child(self)

    def _detach_child(self, _child: Any) -> None:
        self._detach()

    def __copy__(self) -> list[Any]:
        return list(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> list[Any]:
        return [copy.deepcopy(v, memo) for v in self]

    def __reduce__(self):
        return list, (), None, (_to_plain_list(v) for v in self)

    def __reduce_ex__(self, _protocol: int):
        return self.__reduce__()

    def __setitem__(self, key, value) -> None:
        self._detach()
        super().__setitem__(key, value)

    def __delitem__(self, key) -> None:
        self._detach()
        super().__delitem__(key)

    def append(self, value: Any) -> None:
        self._detach()
        super().append(value)

    def extend(self, iterable) -> None:
        self._detach()
        super().extend(iterable)

    def insert(self, index: int, value: Any) -> None:
        self._detach()
        super().insert(index, value)

    def pop(self, index: int = -1) -> Any:
        self._detach()
        return super().pop(index)

    def remove(self, value: Any) -> None:
        self._detach()
        super().remove(value)

    def clear(self) -> None:
        self._detach()
        super().clear()

    def reverse(self) -> None:
        self._detach()
        super().reverse()

    def sort(self, *, key=None, reverse: bool = False) -> None:
        self._detach()
        super().sort(key=key, reverse=reverse)

    def __iadd__(self, value):
        self._detach()
        return super().__iadd__(value)

    def __imul__(self, value):
        self._detach()
        return super().__imul__(value)


def _is_flat_plain_list(row: Any) -> bool:
    return type(row) is list and all(isinstance(v, _IMMUTABLE_SCALARS) for v in row)


def _copy_row(row: Any) -> Any:
    if isinstance(row, _IMMUTABLE_SCALARS):
        return row

    if type(row) is list or type(row) is _TrackedList:
        return [v if isinstance(v, _IMMUTABLE_SCALARS) else _copy_row(v) for v in row]

    if isinstance(row, list):
        cls = type(row)
        cloned_items = [v if isinstance(v, _IMMUTABLE_SCALARS) else _copy_row(v) for v in row]
        if not getattr(row, '__dict__', None) and not getattr(cls, '__slots__', ()):
            try:
                return cls(cloned_items)
            except TypeError:
                pass
        return copy.deepcopy(row)

    if isinstance(row, np.ndarray):
        return row.copy()

    return copy.deepcopy(row)


def default_history(target: Any, attr: str) -> _History | None:
    """Return ``target._<attr>_history`` only when ``target.<attr>`` resolves to ``CityLearnEnv``'s default getter."""

    global _CITYLEARN_ENV_CLS
    env_cls = _CITYLEARN_ENV_CLS
    if env_cls is None:
        from citylearn.citylearn import CityLearnEnv

        _CITYLEARN_ENV_CLS = env_cls = CityLearnEnv

    cls = type(target)
    if (
        not issubclass(cls, env_cls)
        or getattr(cls, attr, None) is not getattr(env_cls, attr, None)
        or cls.__getattribute__ is not env_cls.__getattribute__
        or attr in getattr(target, '__dict__', ())
    ):
        return None

    history = getattr(target, f'_{attr}_history', None)
    return history if isinstance(history, _History) else None


class _History:
    """Common state: executed length, incremental public list cache and plain-list fallback."""

    def __init__(self, capacity: int = 0):
        self._capacity = max(int(capacity), 1)
        self._n = 0
        self._items: list[Any] | None = None  # set once the history is no longer buffer-representable
        self._cacheable_fallback = True
        self._cache: _TrackedList | None = None
        self._cached_len = 0

    def _invalidate_cache(self) -> None:
        cache = self._cache
        if cache is not None:
            cache._owner = None
            self._cache = None
            self._cached_len = 0

    def _detach_child(self, child: Any) -> None:
        if self._cache is child:
            self._cache = None
            self._cached_len = 0

    def __len__(self) -> int:
        return len(self._items) if self._items is not None else self._n

    def __getitem__(self, key):
        if isinstance(key, (int, np.integer)):
            n = len(self)
            index = int(key) + n if key < 0 else int(key)

            if not 0 <= index < n:
                raise IndexError('history index out of range')

            return self._get_fallback(index) if self._items is not None else self._get(index)

        if isinstance(key, slice):
            indices = range(*key.indices(len(self)))
            if self._items is not None:
                return [self._get_fallback(i) for i in indices]

            return [self._get(i) for i in indices]

        return self.to_list()[key]

    def __iter__(self) -> Iterator[Any]:
        if self._items is not None:
            return (self._get_fallback(i) for i in range(len(self._items)))

        return (self._get(i) for i in range(self._n))

    def last(self) -> Any:
        """Return the latest stored entry without building the full list, or ``None`` when empty."""

        n = len(self)
        if n == 0:
            return None

        return self._get_fallback(n - 1) if self._items is not None else self._get(n - 1)

    def to_list(self) -> list[Any]:
        """Return an isolated public ``list`` view of the history."""

        raise NotImplementedError

    def _fallback(self) -> list[Any]:
        if self._items is None:
            self._invalidate_cache()
            self._items = self._materialize_authoritative()
            self._release()

        return self._items

    def _materialize_authoritative(self) -> list[Any]:
        raise NotImplementedError

    def _release(self) -> None:
        raise NotImplementedError

    def _get(self, index: int) -> Any:
        raise NotImplementedError

    def _get_fallback(self, index: int) -> Any:
        raise NotImplementedError


class ScalarHistory(_History):
    """One ``np.float64`` per step, written by index (district net consumption, cost and emissions)."""

    def __init__(self, capacity: int = 0):
        super().__init__(capacity)
        self._buffer = np.empty(self._capacity, dtype='float64')

    def __getstate__(self) -> dict[str, Any]:
        if self._items is not None:
            return {
                'capacity': self._capacity,
                'n': self._n,
                'items': [_copy_row(v) for v in self._items],
                'cacheable_fallback': self._cacheable_fallback,
            }

        return {
            'capacity': self._capacity,
            'n': self._n,
            'buffer_prefix': self._buffer[:self._n].copy(),
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        self._capacity = int(state['capacity'])
        self._n = int(state['n'])
        self._cache = None
        self._cached_len = 0

        if 'items' in state:
            self._items = list(state['items'])
            self._cacheable_fallback = bool(state['cacheable_fallback'])
            self._buffer = None
        else:
            self._items = None
            self._cacheable_fallback = True
            self._buffer = np.empty(self._capacity, dtype='float64')
            if self._n:
                self._buffer[:self._n] = state['buffer_prefix']

    def _release(self) -> None:
        self._buffer = None

    def _get(self, index: int) -> Any:
        return self._buffer[index]

    def _get_fallback(self, index: int) -> Any:
        return _copy_row(self._items[index])

    def _materialize_authoritative(self) -> list[Any]:
        return list(self._buffer[:self._n])

    def to_list(self) -> list[Any]:
        if self._items is not None and not self._cacheable_fallback:
            return [_copy_row(v) for v in self._items]

        n = len(self)
        cache = self._cache
        if cache is None:
            source = self._buffer[:n] if self._items is None else self._items
            cache = _TrackedList(source, owner=self)
            self._cache = cache
            self._cached_len = n
            return cache

        cached_len = self._cached_len
        if cached_len < n:
            if self._items is None:
                if n - cached_len == 1:
                    list.append(cache, self._buffer[cached_len])
                else:
                    list.extend(cache, self._buffer[cached_len:n])
            else:
                if n - cached_len == 1:
                    list.append(cache, self._items[cached_len])
                else:
                    list.extend(cache, self._items[cached_len:n])
            self._cached_len = n

        return cache

    def as_array(self) -> np.ndarray:
        """Return a 1D float64 NumPy view (when buffered) or array of the stored values."""

        if self._items is None:
            return self._buffer[:self._n]

        return np.asarray(self._items, dtype='float64')

    def put(self, index: int, value: Any) -> None:
        """Set the value of step ``index`` with the append, overwrite and truncate rules of a list."""

        if self._items is None and type(value) is _NP_FLOAT and index in (self._n, self._n - 1) and index >= 0:
            if index == self._n:
                if index == self._capacity:
                    self._capacity *= 2
                    grown = np.empty(self._capacity, dtype='float64')
                    grown[:index] = self._buffer[:index]
                    self._buffer = grown

                self._n += 1
            elif index < self._cached_len:
                self._invalidate_cache()

            self._buffer[index] = value
            return

        items = self._fallback()
        if not isinstance(value, _IMMUTABLE_SCALARS):
            self._cacheable_fallback = False
            self._invalidate_cache()

        if len(items) == index:
            items.append(_copy_row(value))
        elif len(items) == index + 1:
            self._invalidate_cache()
            items[index] = _copy_row(value)
        else:
            self._invalidate_cache()
            del items[index + 1:]

            if len(items) < index:
                items.extend([0.0] * (index - len(items)))

            items.append(_copy_row(value))


class RowHistory(_History):
    """Append-only rows of floats, one row per step (``CityLearnEnv.rewards``).

    Rows may differ in length, for example when the topology changes. A row is stored in the buffer
    only if it is a plain ``list`` whose elements are all ``float`` or all ``np.float64``; the kind
    is kept per row so :meth:`to_list` returns the same element types that were appended.
    """

    def __init__(self, capacity: int = 0):
        super().__init__(capacity)
        self._buffer: np.ndarray | None = None  # allocated with the width of the first non-empty row
        self._lengths = np.empty(self._capacity, dtype='int64')
        self._numpy_kind = np.empty(self._capacity, dtype=bool)

    def __getstate__(self) -> dict[str, Any]:
        if self._items is not None:
            return {
                'capacity': self._capacity,
                'n': self._n,
                'items': [_copy_row(item) for item in self._items],
                'cacheable_fallback': self._cacheable_fallback,
            }

        return {
            'capacity': self._capacity,
            'n': self._n,
            'columns': 0 if self._buffer is None else int(self._buffer.shape[1]),
            'buffer_prefix': None if self._buffer is None else self._buffer[:self._n].copy(),
            'lengths_prefix': self._lengths[:self._n].copy(),
            'numpy_kind_prefix': self._numpy_kind[:self._n].copy(),
        }

    def __setstate__(self, state: dict[str, Any]) -> None:
        self._capacity = int(state['capacity'])
        self._n = int(state['n'])
        self._cache = None
        self._cached_len = 0

        if 'items' in state:
            self._items = list(state['items'])
            self._cacheable_fallback = bool(state['cacheable_fallback'])
            self._buffer = self._lengths = self._numpy_kind = None
        else:
            self._items = None
            self._cacheable_fallback = True
            columns = int(state['columns'])
            self._lengths = np.empty(self._capacity, dtype='int64')
            self._numpy_kind = np.empty(self._capacity, dtype=bool)
            if self._n:
                self._lengths[:self._n] = state['lengths_prefix']
                self._numpy_kind[:self._n] = state['numpy_kind_prefix']
            if columns:
                self._buffer = np.empty((self._capacity, columns), dtype='float64')
                if self._n and state['buffer_prefix'] is not None:
                    self._buffer[:self._n, :columns] = state['buffer_prefix']
            else:
                self._buffer = None

    def _release(self) -> None:
        self._buffer = self._lengths = self._numpy_kind = None

    def _get(self, index: int) -> list[Any]:
        width = int(self._lengths[index])
        if width == 0:
            return []

        values = self._buffer[index, :width]
        return list(values) if self._numpy_kind[index] else values.tolist()

    def _tracked_row(self, index: int, owner: _TrackedList) -> _TrackedList:
        if self._items is not None:
            return _TrackedList(self._items[index], owner=owner)

        width = int(self._lengths[index])
        if width == 0:
            return _TrackedList(owner=owner)

        values = self._buffer[index, :width]
        return _TrackedList(values if self._numpy_kind[index] else values.tolist(), owner=owner)

    def _get_fallback(self, index: int) -> Any:
        return _copy_row(self._items[index])

    def _materialize_authoritative(self) -> list[Any]:
        return [self._get(i) for i in range(self._n)]

    def to_list(self) -> list[Any]:
        if self._items is not None and not self._cacheable_fallback:
            return [_copy_row(item) for item in self._items]

        n = len(self)
        cache = self._cache
        if cache is None:
            cache = _TrackedList(owner=self)
            if n:
                list.extend(cache, (self._tracked_row(i, cache) for i in range(n)))
            self._cache = cache
            self._cached_len = n
            return cache

        cached_len = self._cached_len
        if cached_len < n:
            if n - cached_len == 1:
                list.append(cache, self._tracked_row(cached_len, cache))
            else:
                list.extend(cache, (self._tracked_row(i, cache) for i in range(cached_len, n)))
            self._cached_len = n

        return cache

    def append(self, row: Any) -> None:
        if self._items is None and type(row) is list:
            kinds = set(map(type, row))

            if kinds <= {_FLOAT, _NP_FLOAT} and len(kinds) <= 1:
                self._store(row, _NP_FLOAT in kinds)
                return

        items = self._fallback()
        if not _is_flat_plain_list(row):
            self._cacheable_fallback = False
            self._invalidate_cache()

        items.append(_copy_row(row))

    def _store(self, row: list[Any], numpy_kind: bool) -> None:
        index, width = self._n, len(row)

        if index == self._capacity:
            self._capacity *= 2
            grown_lengths = np.empty(self._capacity, dtype='int64')
            grown_lengths[:index] = self._lengths[:index]
            self._lengths = grown_lengths
            grown_kinds = np.empty(self._capacity, dtype=bool)
            grown_kinds[:index] = self._numpy_kind[:index]
            self._numpy_kind = grown_kinds

        old = self._buffer
        old_columns = 0 if old is None else old.shape[1]
        columns = max(width, old_columns)

        if columns and (old is None or old.shape != (self._capacity, columns)):
            self._buffer = np.empty((self._capacity, columns), dtype='float64')

            if old is None:
                if index > 0:
                    self._buffer[:index, :] = np.nan
            elif index > 0:
                self._buffer[:index, :old_columns] = old[:index, :old_columns]
                if columns > old_columns:
                    self._buffer[:index, old_columns:] = np.nan

        if width:
            self._buffer[index, :width] = row
        if width < columns and self._buffer is not None:
            self._buffer[index, width:] = np.nan

        self._lengths[index] = width
        self._numpy_kind[index] = numpy_kind
        self._n += 1

    def rows(self, start: int = 0) -> Iterator[Any]:
        """Yield row copies from ``start`` without building the full list."""

        return (self._get(i) if self._items is None else _copy_row(self._items[i]) for i in range(start, len(self)))
