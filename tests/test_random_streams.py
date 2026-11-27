"""Regression tests for the versioned random streams (issue #248).

Each sub-problem of #248 has a test that the 'v2' streams fix it. Version 'v1', the streams of
CityLearn 3.6.0, was removed in CityLearn 3.8.1 (#466).
"""

import numpy as np
import pytest

from citylearn import random_streams
from citylearn.citylearn import CityLearnEnv
from citylearn.data import DataSet
from citylearn.energy_model import Battery, StorageTank
from citylearn.power_outage import PowerOutage, ReliabilityMetricsPowerOutage
from private_access import ev_drift_seed, runtime_service, topology_service


def _capacity_power_curve_quantiles(battery):
    """Quantiles of the four drawn values of the default capacity-power curve."""

    curve = battery.capacity_power_curve
    drawn = [(curve[1][0], 0.95, 1.0), (curve[0][1], 0.75, 0.85), (curve[1][1], 0.90, 0.95), (curve[1][2], 0.20, 0.30)]

    return np.array([(value - low)/(high - low) for value, low, high in drawn])


# --- the setting -----------------------------------------------------------------------------

@pytest.mark.parametrize('value', [None, 'v2', 'V2', ' v2 ', 2, '2', np.int64(2)])
def test_random_stream_version_parsing(value):
    assert random_streams.parse_random_stream_version(value) == 'v2'


@pytest.mark.parametrize('value', ['v3', 'legacy', True, 0, 2.0, 'v2.0', 'vv2'])
def test_random_stream_version_rejects_unknown_values(value):
    with pytest.raises(ValueError, match="random_stream_version must be 'v2'"):
        random_streams.parse_random_stream_version(value)


@pytest.mark.parametrize('value', ['v1', 1, '1'])
def test_random_stream_version_v1_was_removed(value):
    with pytest.raises(ValueError, match="Version 'v1' was removed in CityLearn 3.8.1; CityLearn 3.7 reproduces"):
        random_streams.parse_random_stream_version(value)


def test_spawn_keys_are_unambiguous_and_purpose_specific():
    assert random_streams.spawn_key('p', 'a', 'bc') != random_streams.spawn_key('p', 'ab', 'c')
    assert random_streams.spawn_key('p', 1) != random_streams.spawn_key('p', '1')
    assert random_streams.spawn_key('p', 'x') != random_streams.spawn_key('q', 'x')
    assert len(random_streams.spawn_key('p')) == 8


def test_negative_seed_is_rejected():
    with pytest.raises(ValueError, match='non-negative'):
        random_streams.seed_sequence(-1, 'p')


# --- 1. the same quantile for every random parameter -----------------------------------------
# 3.6.0 drew every device parameter as the first value of a new RandomState(random_seed).

def test_v2_device_parameters_are_successive_draws_of_one_persistent_stream():
    battery = Battery(capacity=5.0, nominal_power=5.0, random_seed=1234, random_stream_version='v2')
    quantiles = _capacity_power_curve_quantiles(battery)
    assert len(np.unique(np.round(quantiles, 9))) == quantiles.size
    assert battery.numpy_random_state is battery.numpy_random_state

    again = Battery(capacity=5.0, nominal_power=5.0, random_seed=1234, random_stream_version='v2')
    np.testing.assert_array_equal(again.capacity_power_curve, battery.capacity_power_curve)
    np.testing.assert_array_equal(again.power_efficiency_curve, battery.power_efficiency_curve)


def test_v2_devices_with_one_seed_draw_independently_by_stream_key():
    a = Battery(capacity=5.0, nominal_power=5.0, random_seed=7, random_stream_key=('building', 'B1', 'electrical_storage'))
    b = Battery(capacity=5.0, nominal_power=5.0, random_seed=7, random_stream_key=('building', 'B2', 'electrical_storage'))
    assert not np.allclose(a.capacity_power_curve, b.capacity_power_curve)

    tank_a = StorageTank(capacity=1.0, random_seed=7, random_stream_key=('building', 'B1', 'dhw_storage'))
    tank_b = StorageTank(capacity=1.0, random_seed=7, random_stream_key=('building', 'B2', 'dhw_storage'))
    assert tank_a.loss_coefficient != tank_b.loss_coefficient


def test_v2_reseeding_restarts_the_stream():
    battery = Battery(capacity=5.0, nominal_power=5.0, random_seed=3)
    battery.random_seed = 4
    battery.random_seed = 3
    expected = random_streams.generator(3, random_streams.DEVICE_PARAMETERS).uniform()
    assert battery.numpy_random_state.uniform() == expected


def _bundled_device_parameters(version, seed=0):
    schema = DataSet().get_schema('citylearn_challenge_2022_phase_all')
    for name in list(schema['buildings'])[3:]:
        schema['buildings'][name]['include'] = False

    env = CityLearnEnv(schema, central_agent=True, random_seed=seed, random_stream_version=version, episode_time_steps=4,
                       simulation_end_time_step=7)
    try:
        return env, {b.name: np.asarray(b.electrical_storage.capacity_power_curve) for b in env.buildings}
    finally:
        env.close()


def test_v2_bundled_buildings_draw_different_device_parameters_and_repeat_with_the_seed():
    env, first = _bundled_device_parameters('v2')
    assert env.random_stream_version == 'v2'
    assert all(b.electrical_storage.random_stream_version == 'v2' for b in env.buildings)
    curves = list(first.values())
    assert not np.allclose(curves[0], curves[1])
    _, second = _bundled_device_parameters('v2')
    for name in first:
        np.testing.assert_array_equal(first[name], second[name])
    _, other_seed = _bundled_device_parameters('v2', seed=1)
    assert any(not np.array_equal(first[name], other_seed[name]) for name in first)


def test_schema_random_stream_version_is_read_and_recorded():
    schema = DataSet().get_schema('citylearn_challenge_2022_phase_all')
    for name in list(schema['buildings'])[1:]:
        schema['buildings'][name]['include'] = False
    schema['random_stream_version'] = '2'
    env = CityLearnEnv(schema, central_agent=True, random_seed=0, episode_time_steps=4, simulation_end_time_step=7)
    try:
        assert env.random_stream_version == 'v2'
        assert env.buildings[0].electrical_storage.random_stream_version == 'v2'
        env.reset()
        assert env.get_metadata()['random_stream_version'] == 'v2'
        assert env.get_metadata()['temporal_reproducibility']['random_stream_version'] == 'v2'
    finally:
        env.close()

    with pytest.raises(ValueError, match='random_stream_version'):
        CityLearnEnv(schema, central_agent=True, random_stream_version='v9', episode_time_steps=4, simulation_end_time_step=7)
    with pytest.raises(TypeError, match="did you mean 'random_stream_version'"):
        CityLearnEnv(schema, central_agent=True, random_streams_version='v2', episode_time_steps=4, simulation_end_time_step=7)
    schema['random_stream_version'] = 'v1'
    with pytest.raises(ValueError, match="Version 'v1' was removed in CityLearn 3.8.1"):
        CityLearnEnv(schema, central_agent=True, episode_time_steps=4, simulation_end_time_step=7)


# --- 2. additive seeds that overlap across episodes --------------------------------------------

def test_v2_episode_streams_do_not_overlap_with_the_next_seed():
    s = 7
    episode_1 = random_streams.generator(s, random_streams.EV_AWAY_SOC_DRIFT, 'electric_vehicle', 'EV_1', 1).normal(1.0, 0.1, 5)
    next_seed = random_streams.generator(s + 1, random_streams.EV_AWAY_SOC_DRIFT, 'electric_vehicle', 'EV_1', 0).normal(1.0, 0.1, 5)
    assert not np.allclose(episode_1, next_seed)
    # 3.6.0 overlap: seed s, episode 1 is seed s + 1, episode 0.
    np.testing.assert_array_equal(
        np.random.RandomState(s + 1).normal(1.0, 0.1, 5), np.random.RandomState(s + 1 + 0).normal(1.0, 0.1, 5),
    )


def _ev_env(version, seed=7):
    schema = DataSet().get_schema('citylearn_challenge_2022_phase_all_plus_evs')
    return CityLearnEnv(schema, central_agent=True, random_seed=seed, random_stream_version=version,
                        episode_time_steps=24, simulation_end_time_step=71)


def _run_zero(env, **reset):
    env.reset(**reset)
    while not env.terminated:
        env.step([[0.0]*env.action_space[0].shape[0]])
    return np.array([ev.battery.soc for ev in env.electric_vehicles])


def test_v2_ev_drift_is_per_ev_and_episode_and_repeats_with_the_seed():
    env_a, env_b, env_next = _ev_env('v2'), _ev_env('v2'), _ev_env('v2', seed=8)
    try:
        a0 = _run_zero(env_a)
        a1 = _run_zero(env_a)
        b0 = _run_zero(env_b)
        n0 = _run_zero(env_next)
        np.testing.assert_array_equal(a0, b0)
        assert ev_drift_seed(env_a) != ev_drift_seed(env_next)
        # Episode 1 of seed 7 is not episode 0 of seed 8.
        assert not np.array_equal(a1, n0)
        # Every EV holds its own stream.
        keys = {key[1] for key in env_a._ev_drift_generators}
        assert len(keys) >= 2
        streams = [runtime_service(env_a).ev_drift_generator(name, random_streams.EV_AWAY_SOC_DRIFT) for name in sorted(keys)]
        assert len({id(s) for s in streams}) == len(streams)
        # An explicit reset seed repeats the first episode of an env built with that seed.
        explicit = _run_zero(env_a, seed=7, options={'episode_index': 0})
        np.testing.assert_array_equal(explicit, a0)
    finally:
        for env in (env_a, env_b, env_next):
            env.close()


def test_seeded_reset_restarts_the_episode_streams_but_not_the_window_or_construction_draws():
    """What ``reset(seed=s)`` repeats (#303): the episode-0 streams, not the window or construction draws."""

    env_7, env_8 = _ev_env('v2', seed=7), _ev_env('v2', seed=8)
    try:
        first_7 = _run_zero(env_7)
        efficiencies_7 = [ev.battery.efficiency for ev in env_7.electric_vehicles]
        efficiencies_8 = [ev.battery.efficiency for ev in env_8.electric_vehicles]
        assert efficiencies_7 != efficiencies_8

        # A seeded reset of the seed-8 env takes the episode-0 streams of seed 7 ...
        env_8.reset(seed=7)
        assert env_8.random_seed == 7
        assert env_8.episode_tracker.random_stream_episode == 0
        assert ev_drift_seed(env_8) == ev_drift_seed(env_7)
        # ... but keeps the parameters drawn at construction with seed 8.
        assert [ev.battery.efficiency for ev in env_8.electric_vehicles] == efficiencies_8

        # The window still advances; the streams restart at episode 0 at every seeded reset.
        start = env_7.episode_tracker.episode_start_time_step
        env_7.reset(seed=7)
        assert env_7.episode_tracker.episode == 1
        assert env_7.episode_tracker.episode_start_time_step != start
        assert env_7.episode_tracker.random_stream_episode == 0

        # Without a seed, episode_index replays both the window and the streams of that episode.
        env_7.reset(options={'episode_index': 1})
        assert env_7.episode_tracker.random_stream_episode == 1
        np.testing.assert_array_equal(_run_zero(env_7, options={'episode_index': 0}), first_7)
    finally:
        env_7.close()
        env_8.close()


# --- 3. shared occupant draws ------------------------------------------------------------------

def _occupant_draws(version, seed=0, episodes=2):
    schema = DataSet().get_schema('quebec_neighborhood_with_demand_response_set_points')
    for name in list(schema['buildings'])[3:]:
        schema['buildings'][name]['include'] = False
    env = CityLearnEnv(schema, central_agent=True, random_seed=seed, random_stream_version=version,
                       simulation_start_time_step=0, simulation_end_time_step=47, episode_time_steps=24)
    draws = []
    try:
        for _ in range(episodes):
            env.reset()
            while not env.terminated:
                env.step([[0.0]*env.action_space[0].shape[0]])
            draws.append(np.array([b.occupant.probabilities['random'][:-1] for b in env.buildings], dtype='float64'))
    finally:
        env.close()
    return np.array(draws)


def test_v2_occupant_draws_differ_by_building_and_episode_and_repeat_with_the_seed():
    draws = _occupant_draws('v2')
    assert draws.shape[1] == 3
    both = (draws[0, 0] != 0) & (draws[0, 1] != 0)
    assert both.sum() > 5 and not np.allclose(draws[0, 0][both], draws[0, 1][both])
    both = (draws[0, 0] != 0) & (draws[1, 0] != 0)
    assert both.sum() > 5 and not np.allclose(draws[0, 0][both], draws[1, 0][both])
    np.testing.assert_array_equal(draws, _occupant_draws('v2'))
    # Seeds 0 and 1 no longer collapse to the same stream.
    other = _occupant_draws('v2', seed=1)
    both = (draws != 0) & (other != 0)
    assert both.sum() > 5 and not np.allclose(draws[both], other[both])


def _cloned_member_env(version='v2'):
    schema = DataSet().get_schema('quebec_neighborhood_without_demand_response_set_points')
    names = list(schema['buildings'])
    for name in names[2:]:
        schema['buildings'][name]['include'] = False
    schema.update(interface='entity', topology_mode='dynamic', topology_events=[{
        'id': 'clone', 'time_step': 1, 'operation': 'add_member',
        'target_member_id': 'Clone_1', 'source_member_id': names[0],
    }])
    env = CityLearnEnv(schema, random_seed=0, random_stream_version=version, episode_time_steps=24,
                       simulation_start_time_step=0, simulation_end_time_step=47)
    return env, names[0]


def _zero_entity_actions(env):
    tables = env.action_space['tables']
    return {'tables': {
        name: np.zeros(space.shape, dtype='float32') for name, space in tables.items()
        if name in {'building', 'charger', 'deferrable_appliance'}
    }}


def test_v2_cloned_member_draws_its_own_streams():
    """A member cloned from ``source_member_id`` is keyed by its own name, not its source's (#304)."""

    env, source_name = _cloned_member_env()
    try:
        env.reset()
        for _ in range(3):
            env.step(_zero_entity_actions(env))
        pool = topology_service(env)._member_pool
        source, clone = pool[source_name], pool['Clone_1']
        assert clone.random_stream_key == ('building', 'Clone_1')
        assert clone.occupant.random_stream_key == ('building', 'Clone_1', 'occupant')
        assert clone.non_shiftable_load_device.random_stream_key == ('building', 'Clone_1', 'non_shiftable_load_device')
        # The source keeps its own keys and draws.
        assert source.occupant.random_stream_key == ('building', source_name, 'occupant')
        assert not np.array_equal(clone.occupant._interaction_draws, source.occupant._interaction_draws)
        expected = random_streams.generator(
            0, random_streams.OCCUPANT_SETPOINT_INTERACTION, 'building', 'Clone_1', 'occupant',
            env.episode_tracker.random_stream_episode,
        ).random(env.episode_tracker.episode_time_steps)
        np.testing.assert_array_equal(clone.occupant._interaction_draws, expected)
    finally:
        env.close()


# --- 4. stochastic outages ---------------------------------------------------------------------

def test_v2_outages_include_day_zero_and_the_partial_last_day():
    # 3.6.0 dropped day 0 and the partial last day.
    # Every day has an outage starting at hour 0; a 10-hour mean keeps every drawn duration above half a step.
    model = ReliabilityMetricsPowerOutage(saifi=365.0, caidi=600.0, random_seed=3, start_time_steps=[0])
    signals = model.get_signals(72, seconds_per_time_step=3600.0)
    assert all(day.sum() > 0 for day in signals.reshape(3, 24))
    assert model.get_signals(23, seconds_per_time_step=3600.0)[0] == 1


def test_v2_outage_durations_are_rounded_not_floored():
    caidi = 90.0
    durations = []
    for seed in range(400):
        model = ReliabilityMetricsPowerOutage(saifi=365.0, caidi=caidi, random_seed=seed, start_time_steps=[0])
        signals = model.get_signals(24*4, seconds_per_time_step=3600.0)
        # One outage per day starting at hour 0: count its steps (exponential tail truncated at a day).
        durations.extend(day.sum() for day in signals.reshape(4, 24)[:3])
    # E[round(X)] for X ~ Exp(1.5 h) is 1.5 h; flooring, as in 3.6.0, loses about half a step.
    assert abs(np.mean(durations) - caidi/60.0) < 0.15


def test_v2_outage_streams_differ_by_building_and_episode_and_repeat():
    model = ReliabilityMetricsPowerOutage(saifi=200.0, caidi=300.0, random_seed=5)
    signals = {}
    for building in ('B1', 'B2'):
        for episode in (0, 1):
            model._set_episode_seed(11, building, 0, 239, random_stream_version='v2', random_stream_episode=episode)
            signals[building, episode] = model.get_signals(240, seconds_per_time_step=3600.0)
    assert not np.array_equal(signals['B1', 0], signals['B2', 0])
    assert not np.array_equal(signals['B1', 0], signals['B1', 1])
    model._set_episode_seed(11, 'B1', 0, 239, random_stream_version='v2', random_stream_episode=0)
    np.testing.assert_array_equal(model.get_signals(240, seconds_per_time_step=3600.0), signals['B1', 0])


def test_base_power_outage_model_repeats_with_its_seed():
    v2 = PowerOutage(random_seed=4).get_signals(16)
    np.testing.assert_array_equal(v2, PowerOutage(random_seed=4).get_signals(16))


def _outage_env(seed=2023):
    schema = DataSet().get_schema('citylearn_challenge_2023_phase_2_local_evaluation')
    for building in schema['buildings'].values():
        model = building['power_outage']['stochastic_power_outage_model']['attributes']
        model['saifi'] = 120.0
    return CityLearnEnv(schema, central_agent=True, random_seed=seed, episode_time_steps=[(0, 167), (0, 167)])


def _outage_signals(env):
    env.reset()
    # `power_outage_signal` holds the elapsed steps only; redraw the episode's full signal from its stream.
    return np.array([b.reset_power_outage_signal() for b in env.buildings])


def test_outages_in_an_env_differ_by_episode_and_building():
    env = _outage_env()
    try:
        first, second = _outage_signals(env), _outage_signals(env)
        # 3.6.0 repeated the same outages in every episode of the same window, and in every building sharing the
        # schema's outage seed.
        assert not np.array_equal(first, second)
        assert first.shape == (3, 168) and first.sum() > 0
        assert not np.array_equal(first[0], first[1])
    finally:
        env.close()
