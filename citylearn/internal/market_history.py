"""Lossless, append-oriented storage for community market settlements."""
from array import array
from collections.abc import MutableSequence
from copy import deepcopy
import math
import operator


FIELDS = (
    'local_import_kwh', 'local_export_kwh', 'grid_import_kwh', 'grid_export_kwh',
    'local_price', 'local_buy_price', 'local_sell_price', 'operator_balance_eur',
    'grid_import_price', 'grid_export_price', 'counterfactual_cost_eur',
    'settled_cost_eur', 'market_savings_eur',
)
TOTAL_FIELDS = {
    'community_local_import_total_kwh': 'local_import_kwh',
    'community_local_export_total_kwh': 'local_export_kwh',
    'community_grid_import_after_local_total_kwh': 'grid_import_kwh',
    'community_grid_export_after_local_total_kwh': 'grid_export_kwh',
    'community_settled_cost_total_eur': 'settled_cost_eur',
    'community_counterfactual_cost_total_eur': 'counterfactual_cost_eur',
    'community_market_savings_total_eur': 'market_savings_eur',
}


def _scalar(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


class MarketSettlementHistory(MutableSequence):
    """Binary64 columns, interned member IDs and per-step row offsets.

    Indexing, slicing and iteration return ordinary lists of dictionaries for the
    requested steps only. These are detached snapshots: assign a changed step
    back to the history to persist edits. Nonstandard/legacy rows are retained
    verbatim in a sparse side table, rather than dropping unknown fields.

    Arrays grow amortized, without retaining per-row Python objects. Totals use
    the legacy chronological addition order; edits invalidate them and the next
    query rebuilds them once. No prices, flows or physical state are recomputed.
    """

    def __init__(self, steps=()):
        self._columns = {field: array('d') for field in FIELDS}
        self._member_ids = array('I')
        self._members = []
        self._member_lookup = {}
        self._offsets = array('Q', [0])
        self._legacy_steps = {}
        self._totals = {}
        self.extend(steps)

    def __len__(self):
        return len(self._offsets) - 1

    def _index(self, index):
        index = operator.index(index)
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError('settlement history index out of range')
        return index

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        index = self._index(index)
        if index in self._legacy_steps:
            return deepcopy(self._legacy_steps[index])
        rows = []
        for row in range(self._offsets[index], self._offsets[index + 1]):
            record = {'building': self._members[self._member_ids[row]]}
            record.update((field, column[row]) for field, column in self._columns.items())
            rows.append(record)
        return rows

    def __iter__(self):
        for index in range(len(self)):
            yield self[index]

    def __eq__(self, other):
        if not isinstance(other, (list, MarketSettlementHistory)):
            return NotImplemented
        return len(self) == len(other) and all(a == b for a, b in zip(self, other))

    @staticmethod
    def _compactable(rows):
        keys = {'building', *FIELDS}
        return all(isinstance(row, dict) and set(row) == keys
                   and type(row['building']) is str
                   and all(type(row[field]) is float for field in FIELDS)
                   for row in rows)

    def append(self, rows):
        rows = list(rows)
        if self._compactable(rows):
            for record in rows:
                member = record['building']
                if member not in self._member_lookup:
                    self._member_lookup[member] = len(self._members)
                    self._members.append(member)
                self._member_ids.append(self._member_lookup[member])
            for field, column in self._columns.items():
                column.extend(record[field] for record in rows)
        else:
            self._legacy_steps[len(self)] = deepcopy(rows)
        self._offsets.append(len(self._member_ids))
        if self._totals is not None:
            for record in rows:
                self._add_total(record)

    def _truncate(self, start):
        row = self._offsets[start]
        del self._member_ids[row:]
        for column in self._columns.values():
            del column[row:]
        del self._offsets[start + 1:]
        for index in list(self._legacy_steps):
            if index >= start:
                del self._legacy_steps[index]
        self._totals = {} if start == 0 else None

    def __setitem__(self, index, rows):
        if not isinstance(index, slice) and self._index(index) == len(self) - 1:
            # Repeated settlement of the current step is the runtime's edit path.
            rows = list(rows)
            self._truncate(len(self) - 1)
            self.append(rows)
        else:
            steps = list(self)
            steps[index] = rows
            self.__init__(steps)

    def __delitem__(self, index):
        if isinstance(index, slice):
            start, stop, stride = index.indices(len(self))
            if stride == 1 and stop == len(self):
                self._truncate(start)
                return
        elif self._index(index) == len(self) - 1:
            self._truncate(len(self) - 1)
            return
        steps = list(self)
        del steps[index]
        self.__init__(steps)

    def insert(self, index, rows):
        index = operator.index(index)
        if index >= len(self):
            self.append(rows)
        else:
            steps = list(self)
            steps.insert(index, rows)
            self.__init__(steps)

    def clear(self):
        self.__init__()

    def _add_total(self, record):
        name = record.get('building')
        if name not in self._totals:
            self._totals[name] = dict.fromkeys(TOTAL_FIELDS, 0.0)
        target = self._totals[name]
        for key, field in TOTAL_FIELDS.items():
            value = record.get(field, record.get('settled_cost')) if field == 'settled_cost_eur' else record.get(field)
            target[key] += _scalar(value)

    def market_totals(self, building_names):
        """Return independent KPI totals, including historical/removed members."""
        if self._totals is None:
            self._totals = {}
            for rows in self:
                for record in rows:
                    self._add_total(record)
        by_building = {name: self._totals.get(name, dict.fromkeys(TOTAL_FIELDS, 0.0)).copy()
                       for name in building_names}
        district = {key: float(sum(values[key] for values in by_building.values()))
                    for key in TOTAL_FIELDS}
        return by_building, district
