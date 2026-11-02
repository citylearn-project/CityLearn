"""Lossless sparse journal of robustness applications, with compact sealed steps."""
from array import array
from collections.abc import Mapping
from copy import deepcopy


COUNTERS = ('observation', 'forecast', 'action', 'asset', 'missing', 'dropout')
SET_FIELDS = ('event_ids', 'modules', *COUNTERS)
APPLICATION_FIELDS = ('event_id', 'module', 'kind', 'mode', 'target_key', 'building')
KPI_COUNTERS = (
    'robustness_observation_corruption_count',
    'robustness_forecast_corruption_count',
    'robustness_action_corruption_count',
    'robustness_asset_unavailable_time_step_count',
    'robustness_missing_observation_count',
    'robustness_action_dropout_count',
)


def _empty_stats():
    return {'counts': [0] * len(COUNTERS), 'events': set(), 'steps': 0}


def _accumulate(district, buildings, record):
    for i, key in enumerate(COUNTERS):
        district['counts'][i] += len(record[key])
    district['events'].update(record['event_ids'])
    district['steps'] += int(any(record[key] for key in COUNTERS[:4]))
    present = set()
    for app in record['applications']:
        name = app['building']
        if name is None:
            continue
        if name not in buildings:
            buildings[name] = _empty_stats()
        stats = buildings[name]
        stats['events'].add(app['event_id'])
        present.add(name)
        kind, mode, module = app['kind'], app['mode'], app['module']
        if kind in COUNTERS[:4]:
            stats['counts'][COUNTERS.index(kind)] += 1
        stats['counts'][4] += int(mode == 'missing' or (module == 'asset' and kind == 'observation'))
        stats['counts'][5] += int(mode == 'dropout' or (module == 'asset' and kind == 'action'))
    for name in present:
        buildings[name]['steps'] += 1


def _public_stats(stats):
    return {
        'robustness_events_count': float(len(stats['events'])),
        'robustness_active_time_step_count': float(stats['steps']),
        **{key: float(value) for key, value in zip(KPI_COUNTERS, stats['counts'])},
    }


class _StepRecord(Mapping):
    """Decode only a requested field of a sealed step."""
    __slots__ = ('_owner', '_data')

    def __init__(self, owner, data):
        self._owner, self._data = owner, data

    def __len__(self):
        return len(SET_FIELDS) + 1

    def __iter__(self):
        return iter((*SET_FIELDS, 'applications'))

    def __getitem__(self, key):
        if key == 'applications':
            return [dict(zip(APPLICATION_FIELDS, self._owner._applications[index]))
                    for index in self._data[-1]]
        try:
            column = SET_FIELDS.index(key)
        except ValueError:
            raise KeyError(key) from None
        return {self._owner._values[index] for index in self._data[column]}


class RobustnessHistory(Mapping):
    """Keep actual step membership/order; share repeated strings and descriptors.

    One step remains writable using the legacy sets/dictionaries for identical
    deduplication semantics. Advancing seals it into integer arrays. Descriptors
    are interned only when an application actually occurred; event definitions or
    RNG seeds never stand in for the journal. Older steps decode on demand.

    Counts are accumulated when a step is sealed. Summaries add the open step
    without sealing/mutating it. Reopening a historical step invalidates totals;
    they are rebuilt once before reuse. Arbitrary earlier cutoffs use a bounded
    step-by-step scan, so terminal telemetry and completed intervals stay distinct.
    """

    def __init__(self):
        self._records = {}
        self._values, self._value_ids = [], {}
        self._applications, self._application_ids = [], {}
        self._open_step, self._open_record = None, None
        self._district, self._buildings = _empty_stats(), {}
        self._stats_valid = True
        self._max_sealed_step = None

    def __len__(self):
        return len(self._records)

    def __iter__(self):
        return iter(self._records)

    def __getitem__(self, step):
        data = self._records[step]
        return self._open_record if step == self._open_step else _StepRecord(self, data)

    @staticmethod
    def _intern(value, values, lookup):
        index = lookup.get(value)
        if index is None:
            index = len(values)
            lookup[value] = index
            values.append(value)
        return index

    def _seal(self):
        if self._open_step is None:
            return
        record = self._open_record
        columns = [array('I', (self._intern(value, self._values, self._value_ids)
                               for value in sorted(record[field]))) for field in SET_FIELDS]
        columns.append(array('I', (
            self._intern(tuple(app[field] for field in APPLICATION_FIELDS),
                         self._applications, self._application_ids)
            for app in record['applications'])))
        self._records[self._open_step] = tuple(columns)
        if self._stats_valid:
            _accumulate(self._district, self._buildings, record)
        if self._max_sealed_step is None or self._open_step > self._max_sealed_step:
            self._max_sealed_step = self._open_step
        self._open_step, self._open_record = None, None

    def writable_record(self, step):
        if step != self._open_step:
            self._seal()
            if step in self._records:
                self._open_record = dict(self[step])
                self._stats_valid = False
            else:
                self._open_record = {key: set() for key in SET_FIELDS}
                self._open_record['applications'] = []
            self._records[step] = None
            self._open_step = step
        return self._open_record

    def counts(self, step):
        if step not in self._records:
            return dict.fromkeys(COUNTERS, 0)
        if step == self._open_step:
            return {key: len(self._open_record[key]) for key in COUNTERS}
        columns = self._records[step]
        return {key: len(columns[i + 2]) for i, key in enumerate(COUNTERS)}

    def summary(self, building_names, *, executed_before=None):
        complete_prefix = (executed_before is None or self._max_sealed_step is None
                           or executed_before > self._max_sealed_step)
        if complete_prefix:
            if not self._stats_valid:
                self._district, self._buildings = _empty_stats(), {}
                for step in self:
                    if step != self._open_step:
                        _accumulate(self._district, self._buildings, self[step])
                self._stats_valid = True
            district, buildings = deepcopy((self._district, self._buildings))
            if self._open_step is not None and (executed_before is None or self._open_step < executed_before):
                _accumulate(district, buildings, self._open_record)
        else:
            district, buildings = _empty_stats(), {}
            for step in self:
                if step < executed_before:
                    _accumulate(district, buildings, self[step])
        return ({name: _public_stats(buildings.get(name, _empty_stats())) for name in building_names},
                _public_stats(district))

    def application_scopes(self):
        """Stream actual (step, event, kind, building) applications in log order."""
        for step, data in self._records.items():
            if step == self._open_step:
                for app in self._open_record['applications']:
                    yield step, app['event_id'], app['kind'], app['building']
            else:
                for index in data[-1]:
                    app = self._applications[index]
                    yield step, app[0], app[2], app[5]
