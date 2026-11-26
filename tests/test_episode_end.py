"""The end of an episode is a time limit, reported as truncation by default (#435)."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from citylearn.agents.base import Agent
from citylearn.citylearn import CityLearnEnv
from citylearn.multi_community import MultiCommunityEnv

SCHEMA = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"


def _env(**kwargs) -> CityLearnEnv:
    return CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=4, random_seed=0, **kwargs)


def _zero(env: CityLearnEnv):
    return [np.zeros(env.action_space[0].shape[0], dtype="float32")]


def _run(env: CityLearnEnv):
    env.reset(seed=0)
    flags = []
    terminated = truncated = False
    while not (terminated or truncated):
        _, _, terminated, truncated, _ = env.step(_zero(env))
        flags.append((terminated, truncated))
    return flags


def test_default_episode_end_is_reported_as_truncation():
    env = _env()
    try:
        assert env.episode_end == "truncated"
        flags = _run(env)
        assert flags[:-1] == [(False, False)] * (len(flags) - 1)
        assert flags[-1] == (False, True)
        # The properties: `done` and the legacy `terminated` say the episode is over; `truncated` says why.
        assert env.done and env.terminated and env.truncated
        with pytest.raises(RuntimeError, match="reset"):
            env.step(_zero(env))
    finally:
        env.close()


def test_terminated_episode_end_restores_the_3_7_0_flags():
    env = _env(episode_end="terminated")
    try:
        flags = _run(env)
        assert flags[-1] == (True, False)
        assert env.done and env.terminated and not env.truncated
    finally:
        env.close()


def test_episode_end_from_the_schema_and_invalid_values(tmp_path):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["root_directory"] = str(SCHEMA.parent)
    schema["episode_end"] = "TERMINATED"
    env = CityLearnEnv(schema, central_agent=True, episode_time_steps=4, random_seed=0)
    try:
        assert env.episode_end == "terminated"
        # The constructor argument wins over the schema key.
        assert CityLearnEnv(schema, episode_end="truncated", episode_time_steps=4).episode_end == "truncated"
    finally:
        env.close()

    for value in ("done", "", 1, True):
        with pytest.raises(ValueError, match="episode_end"):
            _env(episode_end=value)


def test_episode_end_changes_no_simulation_result_and_is_recorded():
    tables = {}
    for episode_end in ("truncated", "terminated"):
        env = _env(episode_end=episode_end)
        try:
            _run(env)
            assert env.get_metadata()["episode_end"] == episode_end
            tables[episode_end] = env.evaluate_v2(include_business_as_usual=False)[["cost_function", "level", "name", "value"]]
        finally:
            env.close()

    pd.testing.assert_frame_equal(tables["truncated"], tables["terminated"])


def test_step_many_reports_the_same_end_flags():
    env = _env()
    try:
        env.reset(seed=0)
        _, _, terminated, truncated, _ = env.step_many(_zero(env), repeat_steps=10)
        assert (terminated, truncated) == (False, True)
    finally:
        env.close()


class _RecordingAgent(Agent):
    def __init__(self, env, **kwargs):
        super().__init__(env, **kwargs)
        self.flags = []

    def update(self, *args, terminated=None, truncated=None, **kwargs):
        self.flags.append((terminated, truncated))


def test_agent_learn_passes_the_truncation_to_update():
    env = _env()
    try:
        agent = _RecordingAgent(env)
        agent.learn(episodes=1)
        assert agent.flags[-1] == (False, True)
        assert all(flag == (False, False) for flag in agent.flags[:-1])
    finally:
        env.close()


def _community(community_id, **env_kwargs):
    kwargs = {"central_agent": True, "episode_time_steps": 2, "render_mode": "none", "random_seed": 0}
    kwargs.update(env_kwargs)
    return {"community_id": community_id, "schema": str(SCHEMA), "env_kwargs": kwargs}


def test_multi_community_follows_the_children_and_requires_one_episode_end():
    env = MultiCommunityEnv(communities=[_community("a"), _community("b")])
    try:
        env.reset(seed=0)
        actions = {
            community_id: [np.zeros(child.action_space[0].shape[0], dtype="float32")]
            for community_id, child in env.envs.items()
        }
        _, _, terminated, truncated, info = env.step(actions)
        assert (terminated, truncated) == (False, True)
        assert env.done and env.terminated and env.truncated
        assert info["truncated_by_community"] == {"a": True, "b": True}
    finally:
        env.close()

    with pytest.raises(ValueError, match="episode_end"):
        MultiCommunityEnv(communities=[_community("a"), _community("b", episode_end="terminated")])
