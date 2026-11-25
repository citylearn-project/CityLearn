"""The EV SOC unit detection (#368) converts numeric columns without `pd.to_numeric`.

The unit of each SOC column is decided from every row of the charger file. Converting a 2.1 M-row column to
objects and through `pd.to_numeric` made building an environment on the 15 s datasets about 4 s slower. A
numeric column is now converted directly; other values keep the `pd.to_numeric` path, with the same result.
"""

import numpy as np
import pandas as pd
import pytest

from citylearn.data import ChargerSimulation


def _reference(values) -> np.ndarray:
    """The conversion used before the fast path."""

    raw = pd.to_numeric(pd.Series(np.ravel(np.asarray(values, dtype=object))), errors='coerce')
    return raw.to_numpy(dtype='float64')


VALUES = {
    'float64': np.array([0.2, 1.0, 1.0000000000000013, 55.5, -0.1, -1.0, np.nan, np.inf, -np.inf, 0.0]),
    'float32': np.array([0.2, 1.0, 55.5, -0.1, np.nan, np.inf], dtype='float32'),
    'int64': np.array([0, 1, 50, 100, -1], dtype='int64'),
    'uint8': np.array([0, 1, 50, 100], dtype='uint8'),
    'bool': np.array([True, False]),
    '2d': np.array([[0.5, 60.0], [np.nan, -0.1]]),
    'series_float': pd.Series([0.5, 60.0, np.nan]),
    'series_nullable': pd.Series([0.5, None, 60.0], dtype='Float64'),
    'object': np.array([0.5, '60', None, 'x', 1], dtype=object),
    'strings': np.array(['0.5', '60', 'nan', '']),
    'list': [0.5, 60, None, 'x'],
    'empty': np.array([], dtype='float64'),
}


@pytest.mark.parametrize('name', VALUES)
def test_soc_values_convert_as_before(name):
    values = VALUES[name]
    np.testing.assert_array_equal(ChargerSimulation._soc_float_values(values), _reference(values))


@pytest.mark.parametrize('name', VALUES)
def test_soc_unit_and_percent_fractions_are_unchanged(name):
    values = VALUES[name]
    reference = _reference(values)
    valid = np.isfinite(reference) & (reference >= 0.0) & (reference != -0.1)
    unit = 'percent' if np.any(reference[valid] > 1.0 + ChargerSimulation._SOC_FRACTION_TOLERANCE) else 'fraction'
    assert ChargerSimulation._soc_series_unit(values) == unit
    fractions = reference[np.isfinite(reference) & (reference != -0.1) & (reference > 0.0) & (reference < 1.0)]
    np.testing.assert_array_equal(ChargerSimulation._soc_fraction_values_in_percent(values), fractions)


def test_numeric_soc_columns_skip_pd_to_numeric(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError('pd.to_numeric was called for a numeric column')

    column = np.concatenate([np.full(1000, 0.3), [55.0, np.nan, -0.1]])
    monkeypatch.setattr(pd, 'to_numeric', fail)
    assert ChargerSimulation._soc_series_unit(column) == 'percent'
    np.testing.assert_array_equal(ChargerSimulation._soc_fraction_values_in_percent(column), np.full(1000, 0.3))
