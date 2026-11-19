"""The CLI runs on the minimum supported Python.

`datetime.UTC` exists only from Python 3.11, so the evaluation and training
timestamps of `citylearn.__main__.Simulator` raised an AttributeError on
Python 3.10.
"""

import datetime
from pathlib import Path

from citylearn.__main__ import Simulator

SCHEMA = Path(__file__).resolve().parent/'data'/'minute_ev_demo'/'schema.json'


def test_evaluation_records_utc_timestamps(tmp_path):
    simulator = Simulator(
        schema=str(SCHEMA), agent_name='citylearn.agents.base.Agent', env_kwargs={'episode_time_steps': [[0, 3]]},
        output_directory=str(tmp_path), simulation_id='floor', random_seed=0,
    )
    simulator._Simulator__evaluate()
    start = simulator._Simulator__evaluation_start_timestamp
    end = simulator._Simulator__evaluation_end_timestamp
    assert start.utcoffset() == datetime.timedelta(0)
    assert start <= end
