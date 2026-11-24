#!/usr/bin/env python3
"""EV reference controller run exporting both mid-episode and at the end."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController as Agent  # noqa: E402
from citylearn.citylearn import CityLearnEnv  # noqa: E402

SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def main() -> None:
    render_root = ROOT / "SimulationData"
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=96,
        render_mode="during",
        render_directory=render_root,
        random_seed=0,
    )

    try:
        controller = Agent(env)
        observations, _ = env.reset()

        for _ in range(env.episode_tracker.episode_time_steps):
            actions = controller.predict(observations, deterministic=True)
            observations, _, terminated, truncated, _ = env.step(actions)

            if terminated or truncated:
                break

        outputs_path = Path(env.new_folder_path)
        print(f"Exports written to: {outputs_path}")
    finally:
        env.close()


if __name__ == "__main__":
    main()
