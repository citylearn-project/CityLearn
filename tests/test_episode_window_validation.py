"""Explicit episode splits must lie inside the simulation window (CityLearn #308).

Only the rows of the simulation window are loaded. A schema's explicit ``episode_time_steps``
list that reaches outside a window narrowed by the caller used to read past the loaded rows
(``IndexError`` mid-episode) or simulate the wrong rows. The schema's list is now restricted to
the narrowed window, and an explicit list outside the window raises a clear ``ValueError``.
"""

import json
from pathlib import Path

import pytest

from citylearn.base import EpisodeTracker
from citylearn.citylearn import CityLearnEnv

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT/'tests'/'data'/'minute_ev_demo'/'schema.json'


def _schema(episode_time_steps):
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    schema['root_directory'] = str(SCHEMA.parent)
    schema['episode_time_steps'] = episode_time_steps
    return schema


def _run_episode(env):
    env.reset()
    steps = 0

    while not env.terminated:
        # flat_action_space also gives the flat-like vectors that the entity interface accepts.
        env.step([[0.0]*s.shape[0] for s in env.flat_action_space])
        steps += 1

    tracker = env.episode_tracker
    return (tracker.episode_start_time_step, tracker.episode_end_time_step), steps


@pytest.mark.parametrize('interface', ['flat', 'entity'])
def test_schema_episodes_are_restricted_to_a_narrowed_window(interface):
    env = CityLearnEnv(
        _schema([[0, 3], [4, 7]]), simulation_start_time_step=2, simulation_end_time_step=5, interface=interface,
    )

    assert env.episode_time_steps == [[2, 3], [4, 5]]
    assert _run_episode(env) == ((2, 3), 1)
    assert _run_episode(env) == ((4, 5), 1)
    env.close()


def test_schema_episodes_outside_a_narrowed_window_are_dropped():
    env = CityLearnEnv(_schema([[0, 3], [4, 7]]), simulation_start_time_step=0, simulation_end_time_step=3)

    assert env.episode_time_steps == [[0, 3]]
    # On master the second reset selected [4, 7] and stepped past the four loaded rows.
    assert _run_episode(env) == ((0, 3), 3)
    assert _run_episode(env) == ((0, 3), 3)
    env.close()


def test_schema_episode_longer_than_a_narrowed_window_is_clipped():
    env = CityLearnEnv(_schema([[0, 7]]), simulation_start_time_step=2, simulation_end_time_step=5)

    assert env.episode_time_steps == [[2, 5]]
    assert _run_episode(env) == ((2, 5), 3)
    env.close()


def test_schema_episodes_are_unchanged_without_a_window_override():
    env = CityLearnEnv(_schema([[0, 3], [4, 7]]))

    assert env.episode_time_steps == [[0, 3], [4, 7]]
    env.close()


def test_schema_episodes_without_an_interval_in_the_window_raise():
    with pytest.raises(ValueError, match='overlaps the simulation window'):
        CityLearnEnv(_schema([[0, 3], [4, 7]]), simulation_start_time_step=3, simulation_end_time_step=4)


@pytest.mark.parametrize('episodes', [[[0, 7]], [[2, 3], [4, 6]]])
def test_explicit_episodes_outside_the_window_raise_at_construction(episodes):
    with pytest.raises(ValueError, match='outside the simulation window'):
        CityLearnEnv(
            _schema(None), simulation_start_time_step=2, simulation_end_time_step=5, episode_time_steps=episodes,
        )


def test_schema_episodes_outside_the_schema_window_raise():
    schema = _schema([[0, 3], [4, 9]])

    with pytest.raises(ValueError, match=r'Episode window \(4, 9\) lies outside the simulation window \(0, 7\)'):
        CityLearnEnv(schema)


def test_tracker_rejects_episodes_outside_the_window():
    tracker = EpisodeTracker(10, 20)

    assert tracker.validate_episode_splits([(10, 15), [15, 20]]) == [[10, 15], [15, 20]]

    for split in ([9, 15], [15, 21]):
        with pytest.raises(ValueError, match='outside the simulation window'):
            tracker.next_episode([split], False, False, 0)


def test_quebec_narrowed_window_simulates_the_requested_rows():
    pytest.importorskip('torch')
    env = CityLearnEnv(
        'quebec_neighborhood_without_demand_response_set_points', simulation_start_time_step=2200,
        simulation_end_time_step=2296,
    )

    assert env.episode_time_steps == [[2200, 2296]]
    # On master the episode stayed the schema's [0, 2159] and stepped past the 97 loaded rows (IndexError at step 97).
    assert _run_episode(env) == ((2200, 2296), 96)
    env.close()


# The simulation window itself must lie inside the data (audit of 2026-11). minute_ev_demo has 8 rows
# (dataset time steps 0 to 7). A later end step used to build and then fail with an IndexError at the
# last step, because the terminal observation reads the row at the end step.

def _window_schema(**overrides):
    schema = json.loads(SCHEMA.read_text(encoding='utf-8'))
    schema['root_directory'] = str(SCHEMA.parent)
    schema.pop('episode_time_steps', None)
    schema.update(overrides)
    return schema


@pytest.mark.parametrize('start, end', [(0, 8), (0, 9), (2, 40)])
def test_simulation_end_past_the_data_raises_at_construction(start, end):
    with pytest.raises(ValueError, match=r'simulation_end_time_step=\d+ is past the end of the data.*has 8 rows.*'
                                         r'last valid simulation_end_time_step is 7\.'):
        CityLearnEnv(_window_schema(), simulation_start_time_step=start, simulation_end_time_step=end)

    # The same values from the schema.
    with pytest.raises(ValueError, match='last valid simulation_end_time_step is 7'):
        CityLearnEnv(_window_schema(simulation_start_time_step=start, simulation_end_time_step=end))


def test_simulation_start_past_the_data_raises_at_construction():
    with pytest.raises(ValueError, match=r'simulation_start_time_step=8 is past the end of the data.*'
                                         r'last valid simulation_start_time_step is 7'):
        CityLearnEnv(_window_schema(), simulation_start_time_step=8, simulation_end_time_step=9)


@pytest.mark.parametrize('start', [0, 5, 7])
def test_simulation_window_ending_on_the_last_row_runs_to_the_end(start):
    env = CityLearnEnv(_window_schema(), simulation_start_time_step=start, simulation_end_time_step=7, central_agent=True)
    try:
        window, steps = _run_episode(env)
        assert window == (start, 7)
        assert steps == 7 - start
    finally:
        env.close()


def test_terminal_observation_padding_allows_one_step_past_the_data():
    schema = _window_schema(terminal_observation_padding=True)
    env = CityLearnEnv(schema, simulation_start_time_step=0, simulation_end_time_step=8, central_agent=True)
    try:
        assert _run_episode(env) == ((0, 8), 8)
    finally:
        env.close()

    with pytest.raises(ValueError, match='last valid simulation_end_time_step is 8 with terminal_observation_padding'):
        CityLearnEnv(schema, simulation_start_time_step=0, simulation_end_time_step=9)


def test_explicit_episodes_past_the_data_raise_at_construction():
    # Episodes must lie inside the simulation window, and the window inside the data.
    with pytest.raises(ValueError, match='last valid simulation_end_time_step is 7'):
        CityLearnEnv(_window_schema(), simulation_end_time_step=10, episode_time_steps=[[0, 3], [4, 10]])

    with pytest.raises(ValueError, match='outside the simulation window'):
        CityLearnEnv(_window_schema(), episode_time_steps=[[0, 3], [4, 10]])


def test_window_past_the_data_raises_with_a_different_control_step():
    # time_step_ratio scales energy, not the number of rows, so the same last row applies.
    kwargs = dict(seconds_per_time_step=300, time_step_ratio_mode='compress')
    env = CityLearnEnv(_window_schema(), simulation_end_time_step=7, central_agent=True, **kwargs)
    try:
        assert env.time_step_ratio != 1.0
        assert _run_episode(env) == ((0, 7), 7)
    finally:
        env.close()

    with pytest.raises(ValueError, match='last valid simulation_end_time_step is 7'):
        CityLearnEnv(_window_schema(), simulation_end_time_step=8, **kwargs)


def test_dynamic_topology_window_past_the_data_raises_at_construction():
    kwargs = dict(interface='entity', topology_mode='dynamic')
    env = CityLearnEnv(_window_schema(), simulation_end_time_step=7, **kwargs)
    env.close()

    with pytest.raises(ValueError, match=r'past the end of the data: the dataset \(longest building '
                                         r'energy_simulation file\) has 8 rows.*last valid simulation_end_time_step is 7'):
        CityLearnEnv(_window_schema(), simulation_end_time_step=8, **kwargs)


def test_dynamic_topology_template_member_may_have_a_shorter_file():
    # Building_18 of this demo is never active (include false, only a source for add_asset events) and
    # its files have 2200 rows; only the dataset length bounds the window in dynamic topology.
    schema = ROOT/'data'/'datasets'/'citylearn_three_phase_dynamic_assets_only_demo'/'schema.json'
    env = CityLearnEnv(str(schema), simulation_start_time_step=0, simulation_end_time_step=8759)
    env.close()

    with pytest.raises(ValueError, match='has 8760 rows.*last valid simulation_end_time_step is 8759'):
        CityLearnEnv(str(schema), simulation_start_time_step=0, simulation_end_time_step=8760)
