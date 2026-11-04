import math

import numpy as np
import pytest

from citylearn.internal.scalars import clip_scalar

VALUES = [
    -2.0, -1.0, -0.5, -0.0, 0.0, 0.25, 1.0, 1.5, 1.0e-300, -1.0e-300,
    float('inf'), float('-inf'), float('nan'), np.float32(0.3), np.float32(-1.7), np.float64(0.9999999),
]
BOUNDS = [(-1.0, 1.0), (0.0, 1.0), (0.0, None), (None, 0.0)]


@pytest.mark.parametrize(('low', 'high'), BOUNDS)
@pytest.mark.parametrize('value', VALUES)
def test_clip_scalar_matches_numpy_including_nan_and_signed_zero(value, low, high):
    expected = float(np.clip(value, low, high))
    actual = clip_scalar(value, low, high)

    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == expected

        # NumPy 2 changed which signed zero np.clip returns; the helper follows the pinned NumPy 1.x.
        if int(np.__version__.split('.')[0]) < 2:
            assert math.copysign(1.0, actual) == math.copysign(1.0, expected)
