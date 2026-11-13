"""Helpers that keep NumPy 1 promotion results under NumPy 2 (NEP 50)."""

import numpy as np
import pytest

from citylearn.internal.scalars import as_float, numpy1_scalar


@pytest.mark.parametrize('value', [np.float32(1.1), np.float64(1.1), np.array(1.1, dtype='float32')])
def test_as_float_converts_numpy_floating_scalars(value):
    assert type(as_float(value)) is float
    assert as_float(value) == float(value)


@pytest.mark.parametrize('value', [1.1, 3, np.int64(3), np.array([1.1], dtype='float32'), None, 'x'])
def test_as_float_leaves_other_values(value):
    assert as_float(value) is value


def test_numpy1_scalar_wraps_only_python_numbers():
    assert type(numpy1_scalar(1.1)) is np.float64
    assert type(numpy1_scalar(2)) is np.float64
    assert numpy1_scalar(True) is True
    value = np.float32(1.1)
    assert numpy1_scalar(value) is value


def test_float32_scalar_with_python_float_gives_numpy1_result():
    """NumPy 1 computed float32_scalar * python_float in float64; NEP 50 would use float32."""
    soc = np.float32(0.123456789)
    expected = float(soc)*1.1  # float64 arithmetic, the NumPy 1 result

    assert as_float(soc)*1.1 == expected
    assert soc*numpy1_scalar(1.1) == expected
    assert (soc*numpy1_scalar(1.1)).dtype == np.float64


def test_float32_scalars_together_stay_float32():
    """NumPy 1 kept arithmetic between two float32 scalars in float32; numpy1_scalar must not change that."""
    a, b = np.float32(21.7), np.float32(0.3)

    assert (a - numpy1_scalar(b)).dtype == np.float32
    assert a - numpy1_scalar(b) == a - b
