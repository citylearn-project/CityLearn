"""Scalar helpers for per-step hot paths."""

from typing import Any, Optional

import numpy as np


def as_float(value: Any) -> Any:
    """Return a Python float for a NumPy floating scalar or 0-d array; anything else unchanged.

    NumPy 1 evaluated ``float32_scalar <op> python_float`` in float64; NumPy 2 (NEP 50) keeps it in
    float32. Reading float32 storage through this helper keeps such arithmetic in float64 under both,
    so results do not depend on the installed NumPy version.
    """

    if isinstance(value, np.floating) or (isinstance(value, np.ndarray) and value.ndim == 0 and value.dtype.kind == 'f'):
        return float(value)

    return value


def numpy1_scalar(value: Any) -> Any:
    """Return a Python int or float as ``np.float64``; anything else unchanged.

    NumPy 1 promoted ``float32_scalar <op> python_number`` to float64, but kept arithmetic between
    two float32 scalars in float32. NumPy 2 (NEP 50) treats the Python number as weak and stays in
    float32. Wrapping only the Python operand reproduces NumPy 1 under both versions without
    changing arithmetic between two NumPy scalars.
    """

    if type(value) in (float, int):
        return np.float64(value)

    return value


def clip_scalar(value: float, low: Optional[float] = None, high: Optional[float] = None) -> float:
    """Return ``float(np.clip(value, low, high))`` for a single value without NumPy call overhead.

    Follows NumPy's ``min(max(x, low), high)`` order, so NaN propagates and ``-0.0`` clipped at
    ``low=0.0`` becomes ``0.0`` exactly as ``np.clip`` does.
    """

    x = float(value)

    if low is not None and not (x > low or x != x):
        x = float(low)

    if high is not None and not (x < high or x != x):
        x = float(high)

    return x
