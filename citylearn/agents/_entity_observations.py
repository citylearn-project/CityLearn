"""Per-building named observations for the rule-based baselines.

The baseline engines in :mod:`citylearn.agents._baseline_engine` read raw
observations by name. They were developed against the Soft-CPS Algorithms
runtime, which flattens CityLearn's entity observation payload into one named
vector per building. This module reproduces that naming so that the same
decisions are taken here on the same payload:

* district features: ``district__<feature>``
* building features: ``<feature>``
* assets: ``storage::<id>::<feature>``, ``pv::<id>::<feature>``,
  ``deferrable_appliance::<id>::<feature>`` and ``charger::<id>::<feature>``
* EVs at a charger: ``charger::<id>::connected_ev::<feature>`` and
  ``charger::<id>::incoming_ev::<feature>``
* asset counts and the first charger's legacy single-EV aliases.

The payload is produced by the entity interface service, which every
:class:`citylearn.citylearn.CityLearnEnv` builds, so the baselines use the same
observations under the flat and the entity interface.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

_LEGACY_CHARGER_ALIASES = {
    'electric_vehicle_charger_state': 'connected_state',
    'electric_vehicle_soc': 'connected_ev_soc',
    'electric_vehicle_required_soc_departure': 'connected_ev_required_soc_departure',
    'electric_vehicle_departure_time': 'connected_ev_departure_time_step',
}
_ASSET_TABLES = ('storage', 'pv', 'deferrable_appliance', 'charger')


def _safe_scalar(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _as_2d(values: Any) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 1:
        return array.reshape(1, -1) if array.size else np.zeros((0, 0))
    return array if array.ndim == 2 else np.zeros((0, 0))


def _edge_targets(edges: Any, source_index: int) -> List[int]:
    array = np.asarray(edges, dtype=np.int64)
    if array.ndim != 2 or array.shape[1] < 2 or array.size == 0:
        return []
    return sorted(int(v) for v in array[array[:, 0] == int(source_index), 1].tolist())


def _charger_ev_rows(pairs: Any, mask: Any) -> Dict[int, int]:
    pairs = np.asarray(pairs, dtype=np.int64)
    mask = np.asarray(mask, dtype=np.float64).reshape(-1)
    if pairs.ndim != 2 or pairs.shape[1] < 2:
        return {}
    return {
        int(pairs[i, 0]): int(pairs[i, 1])
        for i in range(min(pairs.shape[0], mask.shape[0]))
        if mask[i] > 0.5
    }


def _cell(table: np.ndarray, row: Optional[int], col: Optional[int]) -> float:
    if row is None or col is None or table.shape[0] <= row or table.shape[1] <= col:
        return 0.0
    return _safe_scalar(table[row, col], 0.0)


class EntityObservationFlattener:
    """Flatten an entity payload into per-building ``(names, values)``."""

    def __init__(self, specs: Mapping[str, Any]):
        tables = specs.get('tables', {}) or {}
        self.building_ids = list((tables.get('building') or {}).get('ids', []))
        self.features = {
            name: list((tables.get(name) or {}).get('features', []))
            for name in ('district', 'building', 'ev', *_ASSET_TABLES)
        }
        self.ids = {name: list((tables.get(name) or {}).get('ids', [])) for name in _ASSET_TABLES}
        self._charger_col = {name: i for i, name in enumerate(self.features['charger'])}

    def flatten(
        self, payload: Mapping[str, Any], unlimited_buildings: Sequence[bool] = (),
    ) -> Tuple[List[List[str]], List[np.ndarray]]:
        """Return names and values per building.

        ``unlimited_buildings[b]`` marks a building without electrical service
        limits. The entity tables publish its headroom as 0 kW, which would read
        as "no capacity"; its headroom features are returned as NaN (unknown).
        """
        tables = {name: _as_2d(values) for name, values in (payload.get('tables', {}) or {}).items()}
        edges = payload.get('edges', {}) or {}
        empty = np.zeros((0, 0))
        asset_rows = {
            name: [_edge_targets(edges.get(f'building_to_{name}', []), b) for b in range(len(self.building_ids))]
            for name in _ASSET_TABLES
        }
        connected = _charger_ev_rows(edges.get('charger_to_ev_connected', []), edges.get('charger_to_ev_connected_mask', []))
        incoming = _charger_ev_rows(edges.get('charger_to_ev_incoming', []), edges.get('charger_to_ev_incoming_mask', []))
        all_names: List[List[str]] = []
        all_values: List[np.ndarray] = []

        for b, _building_id in enumerate(self.building_ids):
            names: List[str] = []
            values: List[float] = []

            def add(name: str, value: float):
                values.append(_safe_scalar(value, 0.0))
                names.append(str(name))

            district = tables.get('district', empty)
            for col, feature in enumerate(self.features['district']):
                add(f'district__{feature}', _cell(district, 0, col))

            building = tables.get('building', empty)
            for col, feature in enumerate(self.features['building']):
                add(feature, _cell(building, b, col))

            for table_name in ('storage', 'pv', 'deferrable_appliance'):
                table = tables.get(table_name, empty)
                ids = self.ids[table_name]
                for row in asset_rows[table_name][b]:
                    entity_id = ids[row] if row < len(ids) else f'{table_name}_{row}'
                    for col, feature in enumerate(self.features[table_name]):
                        add(f'{table_name}::{entity_id}::{feature}', _cell(table, row, col))

            chargers = tables.get('charger', empty)
            evs = tables.get('ev', empty)
            charger_ids = self.ids['charger']
            for row in asset_rows['charger'][b]:
                charger_id = charger_ids[row] if row < len(charger_ids) else f'charger_{row}'
                for col, feature in enumerate(self.features['charger']):
                    add(f'charger::{charger_id}::{feature}', _cell(chargers, row, col))
                for label, mapping in (('connected_ev', connected), ('incoming_ev', incoming)):
                    ev_row = mapping.get(row)
                    for col, feature in enumerate(self.features['ev']):
                        add(f'charger::{charger_id}::{label}::{feature}', _cell(evs, ev_row, col))

            add('active_chargers_count', float(len(asset_rows['charger'][b])))
            add('active_storages_count', float(len(asset_rows['storage'][b])))
            add('active_pvs_count', float(len(asset_rows['pv'][b])))
            add('active_deferrable_appliances_count', float(len(asset_rows['deferrable_appliance'][b])))

            if asset_rows['charger'][b]:
                first = asset_rows['charger'][b][0]
                for legacy_name, source in _LEGACY_CHARGER_ALIASES.items():
                    col = self._charger_col.get(source)
                    if col is not None:
                        add(legacy_name, _cell(chargers, first, col))
            else:
                for legacy_name in _LEGACY_CHARGER_ALIASES:
                    add(legacy_name, 0.0)

            add('electric_vehicle_is_flexible', 1.0)
            if 'minute' not in names and 'minutes' in names:
                add('minute', values[names.index('minutes')])
            if 'solar_generation' not in names and 'pv_power_kw' in names:
                add('solar_generation', values[names.index('pv_power_kw')])

            all_names.append(names)
            vector = np.asarray(values, dtype=np.float64)
            if b < len(unlimited_buildings) and unlimited_buildings[b]:
                for i, name in enumerate(names):
                    if 'headroom' in name and '::' not in name:
                        vector[i] = np.nan
            all_values.append(vector)

        return all_names, all_values


__all__: Sequence[str] = ('EntityObservationFlattener',)
