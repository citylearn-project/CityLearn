"""Occupant set-point models stored as scikit-learn tree pickles, evaluated with NumPy.

The bundled Quebec datasets ship ``RandomForestClassifier`` pickles written by scikit-learn
1.0.2. scikit-learn 1.3 changed the tree node layout and cannot unpickle them, which used to
pin scikit-learn to <=1.2.2 and, through it, NumPy to <2 and Python to <3.12.

These files are read by a restricted unpickler, whichever pickle protocol (0 to 5) wrote them.
It rebuilds only NumPy arrays and records the state of the three scikit-learn classes involved,
so no scikit-learn installation is needed and no other callable named in the file can run. A
``numpy.random.RandomState`` passed as ``random_state`` is recorded as an inert placeholder,
since prediction never draws from it.

Predictions reproduce ``predict`` and ``predict_proba`` of single-output
``RandomForestClassifier`` and ``DecisionTreeClassifier`` as the scikit-learn release that wrote
the file computes them: inputs are cast to float32, trees are traversed with the stored
thresholds, and leaf values are averaged in estimator order. Releases before 1.4 store weighted
class counts in the leaves and normalise them per tree; later releases store class fractions and
use them as stored. Releases before 1.3 reject missing (NaN) inputs; later ones store at each
split which child receives them (``missing_go_to_left``), and NaN inputs follow it as in
``Tree.apply`` (only 1.3's forests still rejected NaN on input). Infinite inputs are rejected, as
in scikit-learn. Trees whose nodes hold other fields are left to the installed scikit-learn.
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Any, List, Mapping, Union

import numpy as np

try:  # NumPy >= 2
    from numpy._core import multiarray as _multiarray, numeric as _numeric
except ImportError:  # pragma: no cover - NumPy 1.x
    from numpy.core import multiarray as _multiarray, numeric as _numeric


class _PickledObject:
    """State of a scikit-learn object, recorded without importing scikit-learn."""

    def __init__(self, *args):
        self.args = args

    def __setstate__(self, state: Mapping[str, Any]):
        self.state = state


class _RandomForestClassifier(_PickledObject):
    pass


class _DecisionTreeClassifier(_PickledObject):
    pass


class _Tree(_PickledObject):
    pass


class _RandomState(_PickledObject):
    """Stands in for a pickled ``numpy.random.RandomState`` and its bit generator; never draws."""


class UnsupportedModelError(pickle.UnpicklingError):
    """The file holds something other than a scikit-learn decision tree or random forest."""


def _latin1_bytes(text: str, encoding: str) -> bytes:
    # Protocols 0 to 2 store bytes as _codecs.encode(text, 'latin1').
    if encoding != 'latin1':
        raise UnsupportedModelError(f"'_codecs.encode' to {encoding!r} is not part of a tree classifier pickle.")

    return text.encode('latin1')


def _reconstructor(cls, base, state):
    # Protocols 0 and 1 rebuild Python objects with copyreg._reconstructor(cls, object, None).
    if base is not object or state is not None or not (isinstance(cls, type) and issubclass(cls, _PickledObject)):
        raise UnsupportedModelError("'copyreg._reconstructor' only rebuilds scikit-learn tree objects here.")

    return cls.__new__(cls)


_ALLOWED_GLOBALS = {
    ('numpy', 'ndarray'): np.ndarray,
    ('numpy', 'dtype'): np.dtype,
    ('numpy.core.multiarray', '_reconstruct'): _multiarray._reconstruct,
    ('numpy._core.multiarray', '_reconstruct'): _multiarray._reconstruct,
    ('numpy.core.multiarray', 'scalar'): _multiarray.scalar,
    ('numpy._core.multiarray', 'scalar'): _multiarray.scalar,
    # Pickle protocol 5 stores contiguous arrays as raw buffers.
    ('numpy.core.numeric', '_frombuffer'): _numeric._frombuffer,
    ('numpy._core.numeric', '_frombuffer'): _numeric._frombuffer,
    # Protocols 0 to 2; find_class receives the Python 2 module names they are written with.
    ('_codecs', 'encode'): _latin1_bytes,
    ('copy_reg', '_reconstructor'): _reconstructor,
    ('copyreg', '_reconstructor'): _reconstructor,
    ('__builtin__', 'object'): object,
    ('builtins', 'object'): object,
    ('numpy.random._pickle', '__randomstate_ctor'): _RandomState,
    ('numpy.random._pickle', '__bit_generator_ctor'): _RandomState,
    ('numpy.random._mt19937', 'MT19937'): _RandomState,
    ('sklearn.ensemble._forest', 'RandomForestClassifier'): _RandomForestClassifier,
    ('sklearn.tree._classes', 'DecisionTreeClassifier'): _DecisionTreeClassifier,
    ('sklearn.tree._tree', 'Tree'): _Tree,
}


class _RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        try:
            return _ALLOWED_GLOBALS[(module, name)]
        except KeyError:
            raise UnsupportedModelError(f"'{module}.{name}' is not part of a tree classifier pickle.") from None


_NODE_FIELDS = ('left_child', 'right_child', 'feature', 'threshold', 'impurity', 'n_node_samples', 'weighted_n_node_samples')
# Node layouts evaluated here: scikit-learn < 1.3, and >= 1.3 with missing-value routing.
_NODE_LAYOUTS = (frozenset(_NODE_FIELDS), frozenset(_NODE_FIELDS + ('missing_go_to_left',)))


def _sklearn_release(state: Mapping[str, Any]) -> tuple:
    version = re.match(r'(\d+)\.(\d+)', str(state.get('_sklearn_version', '')))
    return tuple(map(int, version.groups())) if version is not None else ()


class _TreeArrays:
    def __init__(self, tree: _Tree, normalize: bool):
        state = tree.state
        nodes = state['nodes']
        values = np.asarray(state['values'], dtype='float64')

        if values.ndim != 3 or values.shape[1] != 1:
            raise UnsupportedModelError('Only single-output tree classifiers are supported.')

        fields = frozenset(nodes.dtype.names or ())
        if fields not in _NODE_LAYOUTS:
            raise UnsupportedModelError(f'Tree nodes with fields {sorted(fields)} are not supported.')

        self.left = np.asarray(nodes['left_child'], dtype='int64')
        self.right = np.asarray(nodes['right_child'], dtype='int64')
        self.feature = np.asarray(nodes['feature'], dtype='int64')
        self.threshold = np.asarray(nodes['threshold'], dtype='float64')
        # The child that receives a missing (NaN) input; None before scikit-learn 1.3.
        self.missing_go_to_left = (
            np.asarray(nodes['missing_go_to_left'], dtype=bool) if 'missing_go_to_left' in fields else None
        )
        self.value = values[:, 0, :]
        self.normalize = normalize

    def leaves(self, x: np.ndarray) -> np.ndarray:
        rows = np.arange(x.shape[0])
        node = np.zeros(x.shape[0], dtype='int64')

        while True:
            internal = self.left[node] != -1

            if not internal.any():
                return node

            feature = np.maximum(self.feature[node], 0)
            value = x[rows, feature]
            go_left = value <= self.threshold[node]

            if self.missing_go_to_left is not None:
                go_left = np.where(np.isnan(value), self.missing_go_to_left[node], go_left)

            child = np.where(go_left, self.left[node], self.right[node])
            node = np.where(internal, child, node)

    def proba(self, x: np.ndarray, n_classes: int) -> np.ndarray:
        proba = self.value[self.leaves(x), :n_classes].copy()

        if self.normalize:
            normalizer = proba.sum(axis=1)[:, np.newaxis]
            normalizer[normalizer == 0.0] = 1.0
            proba /= normalizer

        return proba


class TreeClassifierModel:
    """NumPy evaluation of a pickled scikit-learn ``RandomForestClassifier`` or ``DecisionTreeClassifier``."""

    def __init__(self, classes: np.ndarray, trees: List[_TreeArrays], n_features: int, forest: bool, *,
                 accepts_missing: bool = True):
        self.classes_ = np.asarray(classes)
        self.trees = trees
        self.n_features_in_ = n_features
        self.forest = forest
        self._accepts_missing = accepts_missing and all(tree.missing_go_to_left is not None for tree in trees)

    @classmethod
    def from_pickle(cls, filepath: Union[str, Path]) -> 'TreeClassifierModel':
        with open(filepath, 'rb') as stream:
            model = _RestrictedUnpickler(stream).load()

        if isinstance(model, _RandomForestClassifier):
            estimators = model.state['estimators_']
            forest = True
        elif isinstance(model, _DecisionTreeClassifier):
            estimators = [model]
            forest = False
        else:
            raise UnsupportedModelError(f'{filepath} does not hold a tree classifier.')

        state = model.state
        if int(state.get('n_outputs_', 1)) != 1:
            raise UnsupportedModelError('Only single-output tree classifiers are supported.')

        # scikit-learn 1.4 switched from weighted class counts to class fractions.
        trees = [
            _TreeArrays(estimator.state['tree_'], normalize=_sklearn_release(estimator.state) < (1, 4))
            for estimator in estimators
        ]
        n_features = int(state.get('n_features_in_', state.get('n_features_', -1)))
        # Stored routes do not imply that the writing estimator accepts NaN.
        release = _sklearn_release(state)
        legacy_random_split = not forest and state.get('splitter') == 'random' and bool(release) and release < (1, 6)
        legacy_monotonic = (1, 4) <= release < (1, 9) and state.get('monotonic_cst') is not None
        requires_finite = (forest and release == (1, 3)) or legacy_random_split or legacy_monotonic
        accepts_missing = not requires_finite
        return cls(state['classes_'], trees, n_features, forest, accepts_missing=accepts_missing)

    def _validate(self, x) -> np.ndarray:
        # scikit-learn evaluates trees on float32 inputs against float64 thresholds.
        x = np.asarray(x, dtype='float32')

        if x.ndim != 2:
            raise ValueError(f'Expected a 2D array of inputs, got shape {x.shape}.')

        if self.n_features_in_ >= 0 and x.shape[1] != self.n_features_in_:
            raise ValueError(f'X has {x.shape[1]} features, but the model expects {self.n_features_in_}.')

        if np.isinf(x).any():
            raise ValueError("Input X contains infinity or a value too large for dtype('float32').")

        if not self._accepts_missing and np.isnan(x).any():
            raise ValueError('Input X contains NaN.')

        return x.astype('float64')

    def predict_proba(self, x) -> np.ndarray:
        x = self._validate(x)
        n_classes = len(self.classes_)

        if not self.forest:
            return self.trees[0].proba(x, n_classes)

        proba = np.zeros((x.shape[0], n_classes), dtype='float64')

        for tree in self.trees:
            proba += tree.proba(x, n_classes)

        proba /= len(self.trees)
        return proba

    def predict(self, x) -> np.ndarray:
        if self.forest:
            scores = self.predict_proba(x)
        else:
            # DecisionTreeClassifier.predict takes the argmax of the stored leaf values, not of predict_proba.
            tree = self.trees[0]
            scores = tree.value[tree.leaves(self._validate(x))]

        return self.classes_.take(np.argmax(scores, axis=1), axis=0)


def load_occupant_model(filepath: Union[str, Path]):
    """Load an occupant model; tree classifiers never need scikit-learn or run code from the file.

    Other pickled models still load through :py:mod:`pickle` and need a compatible library.
    """

    try:
        return TreeClassifierModel.from_pickle(filepath)
    except UnsupportedModelError as reason:
        with open(filepath, 'rb') as stream:
            try:
                return pickle.load(stream)
            except Exception as error:
                raise UnsupportedModelError(
                    f'{filepath} is not a tree classifier CityLearn reads without scikit-learn ({reason}), and '
                    f'unpickling it failed: {error!r}. Install the library release that saved the model, or refit '
                    'and save it with the installed one.'
                ) from error
