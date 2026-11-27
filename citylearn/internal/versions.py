"""One rule for the versioned settings (#469).

``physics_version``, ``baseline_version``, ``random_stream_version``, the reward ``version`` and
``community_market.settlement_version`` are small integer versions, and all of them are parsed by
:py:func:`parse_version` with the same rule:

* an integer (Python or NumPy) or a string of digits, such as ``2`` or ``"2"``, selects that version;
* ``random_stream_version`` also accepts its names, ``'v2'``, and returns the name;
* booleans, floats (``2.0`` too) and any other value are rejected.

A version outside the supported ones raises :py:class:`ValueError`. A version that existed only to
reproduce CityLearn 3.6.0 was removed in CityLearn 3.8.1, and its error says so: CityLearn 3.7
reproduces CityLearn 3.6.0.
"""

from typing import Any, Iterable, Optional

import numpy as np

#: Release that removed the versions kept to reproduce CityLearn 3.6.0 (#466).
REMOVAL_RELEASE = '3.8.1'


def _as_int(value: Any, prefix: Optional[str]) -> Optional[int]:
    if isinstance(value, (bool, np.bool_)):
        return None

    if isinstance(value, (int, np.integer)):
        return int(value)

    if isinstance(value, str):
        text = value.strip()

        if prefix is not None and text.lower().startswith(prefix):
            text = text[len(prefix):]

        if text.isdigit() and text.isascii():
            return int(text)

    return None


def parse_version(
    value: Any, supported: Iterable[int], path: str, default: int = None, removed: Iterable[int] = (),
    prefix: str = None,
):
    """Return the version `value` selects; `default`, else the latest supported version, when it is ``None``.

    Parameters
    ----------
    value : Any
        The setting as given: an integer or a string of digits (with `prefix`, also ``f'{prefix}{n}'``).
    supported : Iterable[int]
        Supported versions, oldest first.
    path : str
        Name of the setting, for the error message.
    default : int, optional
        Version selected by ``None``. Defaults to the latest supported version.
    removed : Iterable[int], optional
        Versions removed in CityLearn 3.8.1; the error names the release.
    prefix : str, optional
        Name prefix of the versions, ``'v'`` for random streams. With a prefix the result is the name,
        for example ``'v2'``; without one it is the integer.

    Raises
    ------
    ValueError
        If `value` is not a supported version under the rule of this module.
    """

    supported = tuple(int(v) for v in supported)
    removed = tuple(int(v) for v in removed)
    version = (supported[-1] if default is None else int(default)) if value is None else _as_int(value, prefix)

    if version not in supported:
        name = (lambda v: repr(f'{prefix}{v}')) if prefix is not None else str
        allowed = name(supported[0]) if len(supported) == 1 else 'one of ' + ', '.join(name(v) for v in supported)
        message = f'{path} must be {allowed}, got {value!r}.'

        if removed:
            names = ' and '.join(name(v) for v in removed)
            message += (
                f' Version {names} was removed in CityLearn {REMOVAL_RELEASE}; '
                'CityLearn 3.7 reproduces CityLearn 3.6.0.'
            )

        raise ValueError(message)

    return f'{prefix}{version}' if prefix is not None else version
