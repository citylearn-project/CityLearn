"""Constructor precedence for random episode selection, including actual resets."""

import json
from pathlib import Path

import numpy as np
import pytest

from citylearn.citylearn import CityLearnEnv


SCHEMA = Path(__file__).resolve().parent / "data/minute_ev_demo/schema.json"


@pytest.mark.parametrize("interface", ["flat", "entity"])
@pytest.mark.parametrize(
    "schema_value, override, expected",
    [
        pytest.param(False, True, True, id="enable-over-schema"),
        pytest.param(True, False, False, id="disable-over-schema"),
        pytest.param(False, None, False, id="inherit-sequential-schema"),
        pytest.param(True, None, True, id="inherit-random-schema"),
        pytest.param(False, False, False, id="explicit-sequential"),
        pytest.param(True, True, True, id="explicit-random"),
    ],
)
def test_random_episode_split_constructor_precedence(
    interface, schema_value, override, expected
):
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["root_directory"] = str(SCHEMA.parent)
    schema["random_episode_split"] = schema_value
    env = CityLearnEnv(
        schema,
        random_episode_split=override,
        rolling_episode_split=False,
        episode_time_steps=2,
        random_seed=7,
        interface=interface,
        render_mode="none",
        offline=True,
        physics_invariant_checks=True,
    )
    try:
        assert env.random_episode_split is expected
        starts = []
        for episode in range(4):
            env.reset(seed=7, options={"episode_index": episode})
            start = env.episode_tracker.episode_start_time_step
            starts.append(start)
            assert start in (0, 2, 4, 6)
            assert env.episode_tracker.episode_end_time_step == start + 1
            if interface == "flat":
                actions = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
            else:
                actions = {}
            _, _, terminated, truncated, _ = env.step(actions)
            assert terminated or truncated

        if expected:
            # With this fixed seed, random selection differs from the four ordered windows.
            assert starts != [0, 2, 4, 6]
        else:
            assert starts == [0, 2, 4, 6]

        env.reset(seed=7, options={"episode_index": 0})
        assert env.episode_tracker.episode_start_time_step == starts[0]
        assert schema["random_episode_split"] is schema_value
    finally:
        env.close()
