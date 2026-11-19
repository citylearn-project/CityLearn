"""JSON output of FileHandler.write_json for NumPy values, namedtuples, Decimal and NaN."""

from collections import namedtuple
from decimal import Decimal
import json

import numpy as np
import pytest

from citylearn.utilities import FileHandler as LegacyFileHandler
from citylearn.utils.file_handler import FileHandler

HANDLERS = pytest.mark.parametrize('handler', [FileHandler, LegacyFileHandler], ids=['utils', 'utilities'])
Pair = namedtuple('Pair', 'a b')


def _write(handler, tmp_path, value, **kwargs):
    path = tmp_path / 'value.json'
    handler.write_json(str(path), {'value': value}, **kwargs)
    text = path.read_text(encoding='utf-8')
    return text, json.loads(text)['value']


@HANDLERS
@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (np.float32(2.5), 2.5),
        (np.int64(7), 7),
        (np.uint8(255), 255),
        (np.bool_(True), True),
        (np.array([1.0, np.nan]), [1.0, None]),
        (np.array([[1, 2], [3, 4]], dtype=np.int32), [[1, 2], [3, 4]]),
        (np.array([True, False]), [True, False]),
        (np.float32(np.inf), None),
    ],
    ids=['float32', 'int64', 'uint8', 'bool', 'array_nan', 'array_2d', 'array_bool', 'float32_inf'],
)
def test_numpy_values_are_written_as_json_values(handler, tmp_path, value, expected):
    _, written = _write(handler, tmp_path, value)
    assert written == expected
    assert type(written) is type(expected)


@HANDLERS
def test_float32_is_written_with_its_exact_value(handler, tmp_path):
    _, written = _write(handler, tmp_path, np.float32(0.1))
    assert written == float(np.float32(0.1))
    assert np.float32(written) == np.float32(0.1)


@HANDLERS
def test_namedtuple_is_written_as_object(handler, tmp_path):
    _, written = _write(handler, tmp_path, Pair(np.float32(1.5), [Pair(1, 2)]))
    assert written == {'a': 1.5, 'b': [{'a': 1, 'b': 2}]}


@HANDLERS
def test_decimal_is_written_as_number_with_its_text(handler, tmp_path):
    text, _ = _write(handler, tmp_path, Decimal('1.10'))
    assert '"value": 1.10' in text


@HANDLERS
@pytest.mark.parametrize('value', [float('nan'), np.float32('nan')], ids=['float', 'float32'])
def test_nan_without_ignore_nan_raises(handler, tmp_path, value):
    with pytest.raises(ValueError, match='Out of range float values'):
        _write(handler, tmp_path, value, ignore_nan=False)


@HANDLERS
@pytest.mark.parametrize(
    'value',
    [np.array(['a', 'b']), np.datetime64('2020-01-01T00:00'), np.complex64(1 + 2j)],
    ids=['str_array', 'datetime64', 'complex64'],
)
def test_other_values_are_written_as_text(handler, tmp_path, value):
    _, written = _write(handler, tmp_path, value)
    assert written == str(value)


def test_numpy_scalar_without_python_equivalent_is_written_as_text(tmp_path):
    value = np.longdouble('2.5')
    _, written = _write(FileHandler, tmp_path, value)
    expected = str(value) if isinstance(value.item(), np.generic) else value.item()
    assert written == expected
