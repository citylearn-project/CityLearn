"""Occupant tree classifiers evaluated with NumPy, without unpickling scikit-learn objects."""

import json
import os
import pickle
from pathlib import Path

import numpy as np
import pytest

from citylearn.internal.occupant_models import TreeClassifierModel, UnsupportedModelError, load_occupant_model

DATASET = Path(__file__).resolve().parents[2]/'data'/'datasets'/'quebec_neighborhood_with_demand_response_set_points'
MODEL = 'resstock-amy2018-2021-release-1-199613_setpoint_{}.pkl'
# Tiny models pickled by scikit-learn 1.2.2, 1.3 and a current release, with the predictions of the
# release that wrote them; see tests/data/occupant_models/make_fixtures.py.
FIXTURES = Path(__file__).resolve().parents[1]/'data'/'occupant_models'
EXPECTED = json.loads((FIXTURES/'expected.json').read_text(encoding='utf-8'))

# Inputs and outputs of scikit-learn 1.2.2 (the version the bundled pickles were last loadable with).
# The first rows put a feature exactly on a split threshold.
FROZEN = {
    'decrease': dict(
        x=[[19.58333206, -18.622, -1.779], [29.257, 19.58333206, -1.426], [18.47222137, 6.907, 1.502],
           [29.23, -3.513, -1.318], [19.677, 19.421, -0.089], [21.35, -4.84, 2.884], [27.416, 2.675, 2.77],
           [21.138, -13.298, 1.349], [23.244, 0.156, 0.247]],
        predict=[0, 0, 1, 0, 0, 1, 0, 1, 0],
        proba=[0.4209479251685091, 0.4595127763121018, 0.5818348250671012, 0.4661242627514074, 0.2826977352084767,
               0.5249616627354494, 0.4577690642198599, 0.5022497397160998, 0.43834713062923364],
    ),
    'increase': dict(
        x=[[22.677, -18.622, 0.58333337], [22.25, 17.676, -1.426], [17.162, 20.08333206, 1.502], [29.23, -3.513, -1.318],
           [19.677, 19.421, -0.089], [21.35, -4.84, 2.884], [27.416, 2.675, 2.77], [21.138, -13.298, 1.349],
           [23.244, 0.156, 0.247]],
        predict=[1, 1, 0, 1, 0, 1, 1, 1, 1],
        proba=[0.7965109463623379, 0.8102129432803262, 0.2956343089163401, 0.8178157894736843, 0.132358454582459,
               0.7916956612856343, 0.9240138782785842, 0.7930511509077168, 0.9551781802407452],
    ),
}


@pytest.mark.parametrize('direction', list(FROZEN))
def test_bundled_occupant_model_reproduces_scikit_learn_1_2_2(direction):
    model = TreeClassifierModel.from_pickle(DATASET/MODEL.format(direction))
    frozen = FROZEN[direction]

    assert model.classes_.tolist() == [0, 1]
    np.testing.assert_array_equal(model.predict(frozen['x']), frozen['predict'])
    np.testing.assert_allclose(model.predict_proba(frozen['x'])[:, 1], frozen['proba'], rtol=0.0, atol=1.0e-15)


@pytest.mark.parametrize('name', sorted(EXPECTED))
def test_fixture_reproduces_the_scikit_learn_that_wrote_it(name):
    expected = EXPECTED[name]
    model = load_occupant_model(FIXTURES/f'{name}.pkl')
    x = np.array(expected['x'], dtype='float64')  # null marks a missing value

    assert isinstance(model, TreeClassifierModel)  # read without scikit-learn, not by the pickle fallback
    np.testing.assert_array_equal(model.predict(x), expected['predict'])
    np.testing.assert_array_equal(model.predict_proba(x), expected['predict_proba'])


@pytest.mark.parametrize('name', sorted(EXPECTED))
def test_fixture_accepts_missing_values_only_where_its_scikit_learn_did(name):
    model = load_occupant_model(FIXTURES/f'{name}.pkl')

    if EXPECTED[name]['nan_rejected']:
        for predict in (model.predict, model.predict_proba):
            with pytest.raises(ValueError, match='NaN'):
                predict([[np.nan, 1.0, 1.0]])
    else:
        assert model.predict([[np.nan, 1.0, 1.0]]).shape == (1,)


@pytest.mark.parametrize('value', [np.inf, -np.inf, 1.0e39])
@pytest.mark.parametrize('name', ['legacy_forest_seed_protocol5', 'missing_forest_randomstate_protocol5'])
def test_rejects_infinite_inputs_like_scikit_learn(name, value):
    model = load_occupant_model(FIXTURES/f'{name}.pkl')

    with pytest.raises(ValueError, match='infinity'), np.errstate(over='ignore'):
        model.predict([[value, 1.0, 1.0]])


def test_unknown_node_layout_is_left_to_scikit_learn(tmp_path):
    """A future node field could change how a tree routes its inputs; such trees are not evaluated."""
    data = (FIXTURES/'legacy_tree_seed_protocol1.pkl').read_bytes()
    path = tmp_path/'model.pkl'
    path.write_bytes(data.replace(b'impurity', b'category'))  # same length, so the pickle stays valid

    with pytest.raises(UnsupportedModelError, match='category'):
        TreeClassifierModel.from_pickle(path)


def _release(version: str) -> tuple:
    return tuple(int(part) for part in version.split('.')[:2])


@pytest.mark.parametrize('estimator', ['forest', 'tree'])
def test_models_with_monotonic_constraints_match_missing_value_validation(tmp_path, estimator):
    sklearn = pytest.importorskip('sklearn')
    release = _release(sklearn.__version__)
    if release < (1, 4):
        pytest.skip('scikit-learn 1.4 introduced monotonic constraints')

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.tree import DecisionTreeClassifier

    model_type = RandomForestClassifier if estimator == 'forest' else DecisionTreeClassifier
    training = [[-2.0], [-1.0], [1.0], [2.0]]
    reference = model_type(monotonic_cst=[1], random_state=0).fit(training, [0, 0, 1, 1])
    path = tmp_path / 'monotonic.pkl'
    path.write_bytes(pickle.dumps(reference, protocol=5))
    model = TreeClassifierModel.from_pickle(path)
    np.testing.assert_array_equal(model.predict(training), reference.predict(training))
    for name in ('predict', 'predict_proba'):
        expected = getattr(reference, name)
        actual = getattr(model, name)
        missing = [[np.nan]]
        if release < (1, 9):
            with pytest.raises(ValueError, match='NaN'):
                expected(missing)
            with pytest.raises(ValueError, match='NaN'):
                actual(missing)
        else:
            np.testing.assert_array_equal(actual(missing), expected(missing))


@pytest.mark.parametrize('random_state', ['seed', 'RandomState'])
@pytest.mark.parametrize('protocol', [0, 2, 4, 5])
@pytest.mark.parametrize('estimator', ['forest', 'tree'])
def test_matches_installed_scikit_learn(tmp_path, estimator, protocol, random_state):
    sklearn = pytest.importorskip('sklearn')
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.tree import DecisionTreeClassifier

    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 3))
    y = np.where(x[:, 0] + 0.5*x[:, 1] > 0.2, 'up', np.where(x[:, 2] > 0.8, 'hold', 'down'))
    test = np.vstack([rng.normal(size=(300, 3)), x[:50]])

    if _release(sklearn.__version__) >= (1, 4):  # trees and forests fit and predict with missing values
        x[rng.random(x.shape) < 0.1] = np.nan
        test[rng.random(test.shape) < 0.1] = np.nan

    seed = 0 if random_state == 'seed' else np.random.RandomState(0)
    reference = (RandomForestClassifier(n_estimators=15, max_depth=6, random_state=seed) if estimator == 'forest'
                 else DecisionTreeClassifier(max_depth=6, random_state=seed)).fit(x, y)
    path = tmp_path/'model.pkl'
    path.write_bytes(pickle.dumps(reference, protocol=protocol))
    model = TreeClassifierModel.from_pickle(path)

    np.testing.assert_array_equal(model.predict(test), reference.predict(test))
    np.testing.assert_array_equal(model.predict_proba(test), reference.predict_proba(test))


class _Payload:
    def __reduce__(self):
        return os.system, ('echo should-not-run',)


def test_tree_loader_never_calls_other_globals(tmp_path):
    path = tmp_path/'payload.pkl'
    path.write_bytes(pickle.dumps(_Payload()))

    with pytest.raises(UnsupportedModelError, match='system'):
        TreeClassifierModel.from_pickle(path)


def test_other_models_fall_back_to_pickle(tmp_path):
    path = tmp_path/'custom.pkl'
    path.write_bytes(pickle.dumps({'kind': 'custom'}))

    assert load_occupant_model(path) == {'kind': 'custom'}


def test_unreadable_model_reports_both_failures(tmp_path):
    path = tmp_path/'custom.pkl'
    path.write_bytes(b'cmissing_citylearn_test_module\nModel\n.')  # protocol 0: GLOBAL, STOP

    with pytest.raises(UnsupportedModelError, match=r'missing_citylearn_test_module\.Model.*ModuleNotFoundError'):
        load_occupant_model(path)


def test_rejects_wrong_feature_count():
    model = TreeClassifierModel.from_pickle(DATASET/MODEL.format('increase'))

    with pytest.raises(ValueError, match='features'):
        model.predict([[1.0, 2.0]])
