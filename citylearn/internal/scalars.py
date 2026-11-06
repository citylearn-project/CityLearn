"""Scalar helpers for per-step hot paths."""

from typing import Optional


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
