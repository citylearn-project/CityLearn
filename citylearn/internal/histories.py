"""Per-step histories kept in preallocated float64 buffers.

A list of floats costs about 32 bytes per value (pointer plus float object) and grows for the whole
episode. The classes here store the same values in a NumPy buffer sized for the episode (8 bytes per
value) and build the public ``list`` on demand with :meth:`to_list`, so attributes such as
``CityLearnEnv.rewards`` keep their list type, element types and contents. Every value that the buffer
cannot reproduce exactly (other element types, non-list rows, out-of-order writes) moves the history to
a plain list, which is the previous behaviour.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import numpy as np

_FLOAT = float
_NP_FLOAT = np.float64


class _History:
    """Common state: executed length, growth, list cache and the plain-list fallback."""

    def __init__(self, capacity: int = 0):
        self._capacity = max(int(capacity), 1)
        self._n = 0
        self._items: list[Any] | None = None  # set once the history is no longer buffer-representable
        self._cache: list[Any] | None = None

    def __len__(self) -> int:
        return len(self._items) if self._items is not None else self._n

    def __getitem__(self, key):
        if isinstance(key, (int, np.integer)):
            n = len(self)
            index = int(key) + n if key < 0 else int(key)

            if not 0 <= index < n:
                raise IndexError('history index out of range')

            return self._items[index] if self._items is not None else self._get(index)

        return self.to_list()[key]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._items) if self._items is not None else (self._get(i) for i in range(self._n))

    def to_list(self) -> list[Any]:
        """Return the history as a list; the same object until the next write.

        The list is a copy of the buffer, so changing it does not change the history.
        """

        if self._items is not None:
            return self._items

        if self._cache is None:
            self._cache = [self._get(i) for i in range(self._n)]

        return self._cache

    def _fallback(self) -> list[Any]:
        if self._items is None:
            self._items = list(self.to_list())
            self._cache = None
            self._release()

        return self._items

    def _release(self) -> None:
        raise NotImplementedError

    def _get(self, index: int) -> Any:
        raise NotImplementedError


class ScalarHistory(_History):
    """One ``np.float64`` per step, written by index (district net consumption, cost and emissions)."""

    def __init__(self, capacity: int = 0):
        super().__init__(capacity)
        self._buffer = np.empty(self._capacity, dtype='float64')

    def _release(self) -> None:
        self._buffer = None

    def _get(self, index: int) -> Any:
        return self._buffer[index]

    def put(self, index: int, value: Any) -> None:
        """Set the value of step ``index`` with the append, overwrite and truncate rules of a list."""

        if self._items is None and type(value) is _NP_FLOAT and index in (self._n, self._n - 1) and index >= 0:
            if index == self._n:
                if index == self._capacity:
                    self._capacity *= 2
                    self._buffer = np.resize(self._buffer, self._capacity)

                self._n += 1

            self._buffer[index] = value
            self._cache = None
            return

        items = self._fallback()

        if len(items) == index:
            items.append(value)
        elif len(items) == index + 1:
            items[index] = value
        else:
            del items[index + 1:]

            if len(items) < index:
                items.extend([0.0] * (index - len(items)))

            items.append(value)


class RowHistory(_History):
    """Append-only rows of floats, one row per step (``CityLearnEnv.rewards``).

    Rows may differ in length, for example when the topology changes. A row is stored in the buffer
    only if it is a ``list`` whose elements are all ``float`` or all ``np.float64``; the kind is kept
    per row so :meth:`to_list` returns the same element types that were appended.
    """

    def __init__(self, capacity: int = 0):
        super().__init__(capacity)
        self._buffer: np.ndarray | None = None  # allocated with the width of the first non-empty row
        self._lengths = np.zeros(self._capacity, dtype='int64')
        self._numpy_kind = np.zeros(self._capacity, dtype=bool)

    def _release(self) -> None:
        self._buffer = self._lengths = self._numpy_kind = None

    def _get(self, index: int) -> list[Any]:
        values = self._buffer[index, :self._lengths[index]] if self._lengths[index] else ()
        return list(values) if self._numpy_kind[index] else (values.tolist() if len(values) else [])

    def append(self, row: Any) -> None:
        if self._items is None and type(row) is list:
            kinds = set(map(type, row))

            if kinds <= {_FLOAT, _NP_FLOAT} and len(kinds) <= 1:
                self._store(row, _NP_FLOAT in kinds)
                return

        self._fallback().append(row)

    def _store(self, row: list[Any], numpy_kind: bool) -> None:
        index, width = self._n, len(row)

        if index == self._capacity:
            self._capacity *= 2
            self._lengths = np.resize(self._lengths, self._capacity)
            self._numpy_kind = np.resize(self._numpy_kind, self._capacity)

        old = self._buffer
        columns = max(width, 0 if old is None else old.shape[1])

        if columns and (old is None or old.shape != (self._capacity, columns)):
            self._buffer = np.empty((self._capacity, columns), dtype='float64')

            if old is not None:
                self._buffer[:old.shape[0], :old.shape[1]] = old

        if width:
            self._buffer[index, :width] = row

        self._lengths[index] = width
        self._numpy_kind[index] = numpy_kind
        self._n += 1
        self._cache = None

    def rows(self, start: int = 0) -> Iterator[list[Any]]:
        """Yield rows from ``start`` without building and caching the full list."""

        return (self._get(i) if self._items is None else self._items[i] for i in range(start, len(self)))
