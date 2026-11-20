from __future__ import annotations

from datetime import datetime
import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("gymnasium")

from citylearn.citylearn import CityLearnEnv


DATASET = Path(__file__).resolve().parents[2] / "tests/data/minute_ev_demo/schema.json"


def test_minute_level_export(tmp_path):
    env = CityLearnEnv(
        str(DATASET),
        central_agent=True,
        render_mode="during",
        render_directory=tmp_path,
        random_seed=0,
    )

    try:
        env.reset()
        zeros = [np.zeros(env.action_space[0].shape[0], dtype="float32")]

        while not (env.terminated or env.truncated):
            _, _, terminated, truncated, _ = env.step(zeros)
            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        community_export = outputs_path / "exported_data_community_ep0.csv"
        assert community_export.exists()

        with community_export.open() as f:
            next(f)  # header
            first_row = next(f).strip()
            second_row = next(f).strip()

        first_ts = first_row.split(",")[0]
        second_ts = second_row.split(",")[0]

        delta = datetime.fromisoformat(second_ts) - datetime.fromisoformat(first_ts)
        assert delta.total_seconds() == pytest.approx(env.seconds_per_time_step)
    finally:
        outputs_root = getattr(env, "new_folder_path", None)
        env.close()
        if outputs_root is not None:
            shutil.rmtree(outputs_root, ignore_errors=True)
