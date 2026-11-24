#!/usr/bin/env python3
"""Reference EV controller rollout exporting the entire dataset horizon."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController as Agent  # noqa: E402
from citylearn.citylearn import CityLearnEnv  # noqa: E402

SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"


def main() -> None:
    logging.getLogger().setLevel(logging.WARNING)

    render_root = ROOT / "SimulationData"
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=8760,  # consume the full simulation horizon
        render_mode="end",
        render_directory=render_root,
        render_session_name="rbc_export_full_horizon",
        random_seed=0,
    )

    try:
        controller = Agent(env)
        observations, _ = env.reset()

        while not env.terminated:
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
