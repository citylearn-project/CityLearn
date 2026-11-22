"""A copied environment continues exactly like the original, KPIs included (CityLearn #307).

Look-ahead controllers, parallel rollouts and checkpoints copy a stepped environment with
``copy.deepcopy`` or ``pickle``. The copy must keep simulating the same trajectory, and its
``evaluate_v2()`` table, energy-provenance rows included, must equal an uncopied run's.
"""

import copy
import pickle

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv


def _actions(env, t, non_negative=False):
    """A deterministic schedule that charges and discharges storage."""

    value = np.float32(0.4*np.sin(t/3.0))
    return [
        np.clip(np.full(space.shape, value, dtype='float32'), np.maximum(space.low, 0.0) if non_negative else space.low,
                space.high)
        for space in env.action_space
    ]


def _run(env, t, non_negative):
    while not env.terminated:
        env.step(_actions(env, t, non_negative))
        t += 1

    return env.evaluate_v2(include_business_as_usual=False)


def _copy(env, mode):
    return copy.deepcopy(env) if mode == 'deepcopy' else pickle.loads(pickle.dumps(env))


def _assert_copy_matches(dataset, end, copy_at, mode, non_negative=False):
    def make():
        env = CityLearnEnv(dataset, simulation_start_time_step=0, simulation_end_time_step=end)
        env.reset()
        return env

    expected = _run(make(), 0, non_negative)
    original = make()

    for t in range(copy_at):
        original.step(_actions(original, t, non_negative))

    copied = _copy(original, mode)
    actual = _run(copied, copy_at, non_negative)

    merged = expected.merge(actual, on=['cost_function', 'name'], suffixes=('_expected', '_actual'), how='outer')
    assert len(merged) == len(expected) == len(actual)
    differ = ~np.isclose(
        merged['value_expected'].astype(float), merged['value_actual'].astype(float), rtol=1e-9, atol=1e-9,
        equal_nan=True,
    )
    assert not differ.any(), merged.loc[differ, ['cost_function', 'name', 'value_expected', 'value_actual']].head(10)
    assert merged['cost_function'].str.contains('energy_provenance').any()


@pytest.mark.parametrize('mode', ['deepcopy', 'pickle'])
@pytest.mark.parametrize('copy_at', [0, 10])
def test_copied_env_kpis_match_uncopied_run(mode, copy_at):
    _assert_copy_matches('citylearn_challenge_2022_phase_all_plus_evs', 23, copy_at, mode)


@pytest.mark.parametrize('mode', ['deepcopy', 'pickle'])
def test_copied_lstm_env_kpis_match_uncopied_run(mode):
    pytest.importorskip('torch')
    # The deepcopy failed once the LSTM had run a prediction, after its lookback warm-up.
    _assert_copy_matches('citylearn_challenge_2023_phase_1', 29, 16, mode, non_negative=True)



def _lstm_temperatures(steps=40):
    env = CityLearnEnv('citylearn_challenge_2023_phase_1', buildings=[0], simulation_start_time_step=0,
                       simulation_end_time_step=steps, random_seed=0)
    env.reset()

    for t in range(steps):
        value = 0.6 if (t // 4) % 2 == 0 else 0.1
        env.step([np.full(space.shape, value, dtype='float32') for space in env.action_space])

    temperatures = [float(x) for x in env.buildings[0].indoor_dry_bulb_temperature[:steps + 1]]
    hidden_state = env.buildings[0].dynamics._hidden_state
    env.close()
    return temperatures, hidden_state


def test_uncopied_lstm_temperatures_are_unchanged(monkeypatch):
    torch = pytest.importorskip('torch')
    from citylearn.dynamics import LSTMDynamics

    grad_enabled = []
    forward = LSTMDynamics.forward

    def recording_forward(self, x, h):
        grad_enabled.append(torch.is_grad_enabled())
        return forward(self, x, h)

    monkeypatch.setattr(LSTMDynamics, 'forward', recording_forward)
    temperatures, hidden_state = _lstm_temperatures()

    # The forward pass runs as before #307, with autograd enabled; only the stored hidden state is detached.
    assert grad_enabled and all(grad_enabled)
    assert all(h.grad_fn is None for h in hidden_state)

    # Before #307 the forward's hidden state was stored as returned. With detach() as a no-op the current code
    # does exactly that, in the same process and torch build, so the comparison does not depend on the platform.
    # Running the forward under torch.no_grad() changed some of these temperatures in the last bits.
    with monkeypatch.context() as patch:
        patch.setattr(torch.Tensor, 'detach', lambda self: self)
        before, before_hidden_state = _lstm_temperatures()

    assert any(h.grad_fn is not None for h in before_hidden_state)
    assert temperatures == before
