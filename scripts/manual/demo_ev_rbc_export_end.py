#!/usr/bin/env python3
"""EV reference controller run with exports at the end of the episode."""

from __future__ import annotations

import sys
import logging
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.agents.rbc import BasicElectricVehicleRBC_ReferenceController as Agent  # noqa: E402
from citylearn.citylearn import CityLearnEnv  # noqa: E402

SCHEMA = ROOT / "data/datasets/citylearn_challenge_2022_phase_all_plus_evs/schema.json"

def main(step=96):
    logging.getLogger().setLevel(logging.WARNING)

    print(f"TIMESTEPS ==>\t{step}\n\n")

    render_root = ROOT / "SimulationData"
    start = time.time();
    env_creation_start = time.time();
    env = CityLearnEnv(
        str(SCHEMA),
        central_agent=True,
        episode_time_steps=step,
        render_mode="end",
        render_directory=render_root,
        render_session_name="rbc_export_end_example5",
        random_seed=0,
        debug_timing=True,
    )
    env_creation_end = time.time();
    try:
        print("running");
        agent_creation_start = time.time();
        controller = Agent(env)
        agent_creation_end = time.time();

        env_reset_start = time.time();
        observations, _ = env.reset()
        env_reset_end = time.time();

        total_retrieval_time = 0.0;
        total_retrievals = 0;
        total_render_time = .0;

        while not env.terminated:
            actions = controller.predict(observations, deterministic=True)
            observations, _, terminated, truncated, info = env.step(actions)
            total_retrieval_time += float(info.get('building_observations_retrieval_time', 0.0))
            total_render_time += float(info.get('partial_render_time', 0.0))
            total_retrievals += 1;
            if terminated or truncated:
                break

        
        outputs_path = Path(env.new_folder_path)
        print(f"Exports written to: {outputs_path}")
    finally:
        env.close()
    end = time.time();

    env_creation = env_creation_end - env_creation_start
    agent_creation = agent_creation_end - agent_creation_start
    env_reset = env_reset_end - env_reset_start
    total_time = end - start
    
    return env_creation, agent_creation, env_reset, total_render_time, total_retrieval_time, total_time

if __name__ == "__main__":
    
    main()
