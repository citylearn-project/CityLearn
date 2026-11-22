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


# Indoor temperatures of an uncopied LSTM run on master before #307 (citylearn_challenge_2023_phase_1, first building,
# 40 steps, actions 0.6 and 0.1 alternating every 4 steps). Making the hidden state copyable must not change them.
LSTM_REFERENCE_TEMPERATURES = [
    23.098651885986328, 22.234743118286133, 22.223060607910156, 22.22224998474121,
    22.22223663330078, 22.22223663330078, 22.222230911254883, 22.332555770874023,
    22.77179718017578, 23.266788482666016, 24.406890869140625, 24.444318771362305,
    24.659706115722656, 26.751262664794922, 27.600814819335938, 28.559246063232422,
    23.4744873046875, 24.05577850341797, 23.418136596679688, 22.251605987548828,
    24.948606491088867, 25.229276657104492, 25.41000747680664, 25.23574447631836,
    17.92530632019043, 18.011262893676758, 16.59043312072754, 15.904638290405273,
    18.34335708618164, 18.858064651489258, 19.668304443359375, 20.420150756835938,
    16.918733596801758, 17.754247665405273, 17.818761825561523, 18.368370056152344,
    21.927770614624023, 23.71963882446289, 25.293119430541992, 26.318931579589844,
]


def test_uncopied_lstm_temperatures_are_unchanged():
    pytest.importorskip('torch')
    env = CityLearnEnv('citylearn_challenge_2023_phase_1', buildings=[0], simulation_start_time_step=0,
                       simulation_end_time_step=40, random_seed=0)
    env.reset()

    for t in range(40):
        value = 0.6 if (t // 4) % 2 == 0 else 0.1
        env.step([np.full(space.shape, value, dtype='float32') for space in env.action_space])

    temperatures = [float(x) for x in env.buildings[0].indoor_dry_bulb_temperature[:41]]
    # Bit-identical: running the LSTM under torch.no_grad() changed some of these in the last bits.
    assert temperatures == LSTM_REFERENCE_TEMPERATURES
    env.close()
