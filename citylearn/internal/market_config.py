"""Validation of the schema's `community_market` section.

Every key is checked when the env is built. A misspelt key, a value of the wrong type or a value
out of range raises `ValueError` instead of being ignored or replaced by a default (CityLearn #366).
"""
import difflib
import hashlib
import math
from numbers import Real
from typing import Any, Iterable, Mapping

import numpy as np

DEFAULT_LOCAL_PRICE_RATIO = 0.8
SETTLEMENT_VERSIONS = (1, 2)
KNOWN_KEYS = (
    'enabled', 'local_price_ratio_to_grid_import', 'intra_community_sell_ratio', 'settlement_version',
    'grid_export_price', 'tariff_files', 'local_trading_enabled', 'import_member_weights', 'kpis',
    'matching_granularity', 'counterfactual',
)
KNOWN_KPI_KEYS = ('community_local_traded_enabled', 'community_self_consumption_enabled')
MATCHING_GRANULARITIES = ('aggregate_building',)
# The settlement compares each member with buying and selling on the grid alone; the generated
# annual suites record this as `counterfactual`.
COUNTERFACTUALS = ('grid_only',)


def _unknown(keys: Iterable[Any], known: Iterable[str], path: str):
    known = list(known)
    details = []
    for key in keys:
        if key in known:
            continue
        match = difflib.get_close_matches(str(key), known, n=1)
        details.append(f"'{key}'" + (f" (did you mean '{match[0]}'?)" if match else ''))
    if details:
        raise ValueError(
            f"{path} has unknown key(s): {', '.join(details)}. Accepted keys: {', '.join(known)}."
        )


def _mapping(value: Any, path: str) -> Mapping:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f'{path} must be a mapping, got {type(value).__name__}.')
    return value


def _number(value: Any, path: str) -> float:
    # bool is an int subclass, and strings such as "0,7" used to fall back to a default.
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (Real, np.integer, np.floating)):
        raise ValueError(f'{path} must be a number, got {value!r}.')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{path} must be finite, got {value!r}.')
    return value


def _members(value: Any, path: str, building_names) -> Mapping:
    value = _mapping(value, path)
    if building_names is not None:
        unknown = [str(k) for k in value if str(k) not in building_names]
        if unknown:
            raise ValueError(
                f"{path} names building(s) that are not in the schema: {', '.join(repr(k) for k in unknown)}."
            )
    return value


def parse_community_market(config: Any, building_names=None) -> dict:
    """Validated `community_market` settings.

    `building_names` are the schema's building names; when given, member weights and tariff files
    must name one of them. Returns the resolved ratio, settlement version, grid export price, member
    weights and KPI switches. `enabled` and `local_trading_enabled` are parsed by their callers.
    """
    config = _mapping(config, 'community_market')
    _unknown(config, KNOWN_KEYS, 'community_market')
    building_names = None if building_names is None else {str(n) for n in building_names}

    ratios = {
        key: _number(config[key], f'community_market.{key}')
        for key in ('local_price_ratio_to_grid_import', 'intra_community_sell_ratio') if key in config
    }
    if len(set(ratios.values())) > 1:
        raise ValueError(
            'community_market.local_price_ratio_to_grid_import and its legacy alias intra_community_sell_ratio '
            f"disagree ({ratios['local_price_ratio_to_grid_import']!r} vs {ratios['intra_community_sell_ratio']!r}); "
            'set only local_price_ratio_to_grid_import.'
        )
    ratio = next(iter(ratios.values()), DEFAULT_LOCAL_PRICE_RATIO)
    if not 0.0 <= ratio <= 1.0:
        raise ValueError(
            f'community_market.local_price_ratio_to_grid_import must be between 0 and 1, got {ratio!r}: '
            'a member cannot pay more for local energy than for grid energy.'
        )

    version = config.get('settlement_version', 1)
    # 2.0 selected version 2 before validation (the check was `== 2`), so integral floats are kept.
    if isinstance(version, (bool, np.bool_)) or not isinstance(version, (Real, np.integer, np.floating)) \
            or version not in SETTLEMENT_VERSIONS:
        raise ValueError(
            f'community_market.settlement_version must be 1 or 2, got {version!r}.'
        )
    version = int(version)

    export_price = _number(config.get('grid_export_price', 0.0), 'community_market.grid_export_price')
    if version != 2 and export_price != 0.0:
        raise ValueError(
            f'community_market.grid_export_price is {export_price!r}, but residual grid exports are paid only '
            'with "settlement_version": 2; settlement version 1 pays nothing for them. Add "settlement_version": 2 '
            'or set grid_export_price to 0.'
        )

    weights = {}
    for key, value in _members(config.get('import_member_weights'), 'community_market.import_member_weights',
                               building_names).items():
        value = _number(value, f'community_market.import_member_weights.{key}')
        if value < 0.0:
            raise ValueError(f'community_market.import_member_weights.{key} must not be negative, got {value!r}.')
        weights[str(key)] = value

    _members(config.get('tariff_files'), 'community_market.tariff_files', building_names)
    kpis = _mapping(config.get('kpis'), 'community_market.kpis')
    _unknown(kpis, KNOWN_KPI_KEYS, 'community_market.kpis')

    for key, accepted in (('matching_granularity', MATCHING_GRANULARITIES), ('counterfactual', COUNTERFACTUALS)):
        value = config.get(key, accepted[0])
        if value not in accepted:
            raise ValueError(f"community_market.{key} must be one of {', '.join(accepted)}, got {value!r}.")

    return dict(
        local_price_ratio_to_grid_import=ratio, settlement_version=version, grid_export_price=export_price if
        version == 2 else 0.0, import_member_weights=weights, kpis=kpis,
    )


def market_configuration(env) -> dict:
    """The settlement settings an env uses now, for comparing it with its native BAU reference.

    The reference is rebuilt from the schema, so it cannot follow market attributes set on the env
    after construction; comparing these values detects that.
    """
    tariffs = getattr(env, 'community_tariffs', None) or {}
    return dict(
        enabled=bool(getattr(env, 'community_market_enabled', False)),
        local_price_ratio_to_grid_import=getattr(env, 'community_market_sell_ratio', None),
        grid_export_price=getattr(env, 'community_market_grid_export_price', None),
        local_trading_enabled=getattr(env, 'community_market_local_enabled', True),
        import_member_weights=dict(sorted((getattr(env, 'community_market_import_member_weights', None) or {}).items())),
        tariffs={str(name): hashlib.sha256(np.ascontiguousarray(values, dtype='float64').tobytes()).hexdigest()
                 for name, values in sorted(tariffs.items())},
    )


def market_differences(left: dict, right: dict):
    """`setting (left vs right)` for each :func:`market_configuration` entry that differs."""
    return [f'community_market {key} ({left.get(key)!r} vs {right.get(key)!r})'
            for key in sorted(set(left) | set(right)) if left.get(key) != right.get(key)]
