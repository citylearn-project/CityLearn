"""Write the scikit-learn tree pickles and predictions used by tests/unit/test_occupant_tree_model.py.

CityLearn reads occupant models from tree-classifier pickles without scikit-learn
(citylearn/internal/occupant_models.py). Each fixture here is a tiny model pickled by one
scikit-learn release, and expected.json stores that release's ``predict`` and ``predict_proba``
for fixed inputs, so the tests can compare CityLearn's reader with it under any scikit-learn and
NumPy, or without scikit-learn.

Run the script once in each environment; a run replaces only its own set:

- ``legacy``: scikit-learn 1.2.2 with NumPy < 2, the release CityLearn 3.2.0 pinned and the last
  one whose node layout has no ``missing_go_to_left``. Forests and trees pickled with protocols
  1, 2, 4 and 5 and fitted with an integer seed or a ``numpy.random.RandomState``. scikit-learn
  1.2.2 rejects missing values, so only finite inputs are recorded.
- ``missing_counts``: scikit-learn 1.3.x, a tree fitted on data with missing values. Its nodes
  store ``missing_go_to_left`` and its leaves still hold class counts.
- ``missing``: scikit-learn >= 1.4, a tree and a forest fitted on data with missing values. The
  leaves hold class fractions.

In the last two sets, NaN inputs go left at some splits and right at others.

    python tests/data/occupant_models/make_fixtures.py
"""

import json
import pickle
import platform
import re
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.tree import DecisionTreeClassifier

HERE = Path(__file__).resolve().parent
EXPECTED = HERE/'expected.json'


def _legacy_data():
    rng = np.random.RandomState(0)
    x = rng.normal(size=(120, 3))
    y = np.where(x[:, 0] + 0.5*x[:, 1] > 0.2, 2, np.where(x[:, 2] > 0.5, 1, 0))
    return x, y


def _missing_data():
    """Missing x0 is labelled like the left branch of the x0 split and missing x1 like the right
    branch of the x1 split. x2 never misses, so NaN follows the larger child at an x2 split."""

    rng = np.random.RandomState(0)
    x = rng.uniform(0.0, 10.0, size=(300, 3))
    y = np.where(x[:, 0] <= 5.0, np.where(x[:, 2] <= 7.0, 0, 1), np.where(x[:, 1] <= 5.0, 1, 2))
    x[np.flatnonzero(x[:, 0] <= 5.0)[:25], 0] = np.nan
    x[np.flatnonzero((x[:, 0] > 5.0) & (x[:, 1] > 5.0))[:20], 1] = np.nan
    return x, y


def _inputs(model, x, missing):
    """Training rows, values on and one float32 step either side of each split of the first tree,
    and, for models fitted with missing values, rows with NaN."""

    finite = x[np.isfinite(x).all(axis=1)]
    rows = list(x[:8])
    tree = (model.estimators_[0] if hasattr(model, 'estimators_') else model).tree_

    for node in np.flatnonzero(tree.children_left != -1):
        feature, threshold = tree.feature[node], np.float32(tree.threshold[node])
        for value in (np.nextafter(threshold, np.float32(-np.inf)), threshold, np.nextafter(threshold, np.float32(np.inf))):
            row = finite[len(rows) % len(finite)].copy()
            row[feature] = value
            rows.append(row)

    if missing:
        nan = np.nan
        rows += [[nan, 3.0, 3.0], [2.0, 3.0, nan], [8.0, nan, 3.0], [8.0, 3.0, nan], [nan, nan, nan], [nan, 8.0, 9.0]]

    return np.asarray(rows, dtype='float64')


def _nan_rejected(model, row):
    try:
        model.predict(row)
    except ValueError:
        return True

    return False


def _record(name, model, protocol, random_state, x, kind, expected):
    path = HERE/f'{name}.pkl'
    path.write_bytes(pickle.dumps(model, protocol=protocol))
    missing = kind != 'legacy'
    inputs = _inputs(model, x, missing)
    expected[name] = {
        'set': kind,
        'written_with': {'python': platform.python_version(), 'numpy': np.__version__, 'scikit-learn': sklearn.__version__},
        'estimator': type(model).__name__,
        'random_state': random_state,
        'protocol': protocol,
        'nan_rejected': _nan_rejected(model, np.array([[np.nan, 1.0, 1.0]])),
        'x': [[None if np.isnan(v) else float(v) for v in row] for row in inputs],
        'predict': model.predict(inputs).tolist(),
        'predict_proba': model.predict_proba(inputs).tolist(),
    }

    if missing:
        trees = model.estimators_ if hasattr(model, 'estimators_') else [model]
        routing = {bool(t.tree_.missing_go_to_left[n]) for t in trees for n in np.flatnonzero(t.tree_.children_left != -1)}
        assert routing == {False, True}, 'the fixture must route missing values both ways'
        assert not expected[name]['nan_rejected']

    print(f'{path.name}: {path.stat().st_size} bytes')


def main():
    version = tuple(int(v) for v in re.match(r'(\d+)\.(\d+)', sklearn.__version__).groups())
    expected = json.loads(EXPECTED.read_text(encoding='utf-8')) if EXPECTED.exists() else {}

    if version == (1, 2):
        if sklearn.__version__ != '1.2.2' or not np.__version__.startswith('1.'):
            raise SystemExit(f'The legacy set needs scikit-learn 1.2.2 and NumPy < 2, not {np.__version__}.')

        kind = 'legacy'
        x, y = _legacy_data()
        models = [
            ('legacy_forest_seed_protocol5', RandomForestClassifier(n_estimators=3, max_depth=3, random_state=0), 5, '0'),
            ('legacy_forest_randomstate_protocol4', RandomForestClassifier(n_estimators=3, max_depth=3, random_state=np.random.RandomState(0)), 4, 'RandomState(0)'),
            ('legacy_tree_randomstate_protocol5', DecisionTreeClassifier(max_depth=3, random_state=np.random.RandomState(0)), 5, 'RandomState(0)'),
            ('legacy_forest_seed_protocol2', RandomForestClassifier(n_estimators=3, max_depth=3, random_state=0), 2, '0'),
            ('legacy_tree_seed_protocol1', DecisionTreeClassifier(max_depth=3, random_state=0), 1, '0'),
        ]
    elif version == (1, 3):
        kind = 'missing_counts'
        x, y = _missing_data()
        models = [('missing_counts_tree_seed_protocol5', DecisionTreeClassifier(max_depth=3, random_state=0), 5, '0')]
    elif version >= (1, 4):
        kind = 'missing'
        x, y = _missing_data()
        tree = DecisionTreeClassifier(max_depth=3, random_state=0)
        models = [
            ('missing_tree_seed_protocol4', tree, 4, '0'),
            ('missing_tree_seed_protocol5', tree, 5, '0'),
            ('missing_forest_randomstate_protocol5', RandomForestClassifier(n_estimators=3, max_depth=3, random_state=np.random.RandomState(0)), 5, 'RandomState(0)'),
        ]
    else:
        raise SystemExit(f'Run with scikit-learn 1.2.2, 1.3.x or >= 1.4, not {sklearn.__version__}.')

    for name in [name for name, entry in expected.items() if entry['set'] == kind]:
        (HERE/f'{name}.pkl').unlink(missing_ok=True)
        del expected[name]

    fitted = set()
    for name, model, protocol, random_state in models:
        if id(model) not in fitted:
            model.fit(x, y)
            fitted.add(id(model))

        _record(name, model, protocol, random_state, x, kind, expected)

    lines = [f' {json.dumps(name)}: {json.dumps(entry)}' for name, entry in sorted(expected.items())]
    EXPECTED.write_text('{\n' + ',\n'.join(lines) + '\n}\n', encoding='utf-8')
    print(f'wrote {EXPECTED}')


if __name__ == '__main__':
    main()
