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
