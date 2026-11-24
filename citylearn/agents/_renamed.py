"""Deprecated aliases of renamed agent classes."""

import warnings

REASON = (
    "In CityLearn, 'baseline' names the KPI counterfactual (the same buildings without storage, with PV), so the "
    "agent classes no longer use the word."
)


def renamed(module: str, old: str, new: str, cls: type) -> type:
    """Return ``cls`` for the deprecated name ``old`` and warn that it is now ``new``."""

    warnings.warn(
        f'{module}.{old} is deprecated and will be removed in a later release; use {module}.{new}, the same class. '
        f'{REASON} {new} describes what the agent does.',
        DeprecationWarning,
        stacklevel=3,
    )

    return cls
