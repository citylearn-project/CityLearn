#!/usr/bin/env python3
"""Minimal EV simulation using the reference RBC controller.

Run from the repository root:

    python scripts/manual/demo_ev_rbc.py
"""

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
    env = CityLearnEnv(str(SCHEMA), central_agent=True, episode_time_steps=96, random_seed=0)

    try:
        controller = Agent(env)
        observations, _ = env.reset()

        while not env.terminated:
            actions = controller.predict(observations, deterministic=True)
            observations, _, terminated, truncated, _ = env.step(actions)
            if terminated or truncated:
                break

        df = env.evaluate()
        summary = df.pivot(index="cost_function", columns="name", values="value").round(3)
        print(summary.fillna(""))
    finally:
        env.close()


if __name__ == "__main__":
    main()
