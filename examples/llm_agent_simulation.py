"""Run a generative LLM agent episode in CityLearn (Generative-Traffic-Agents style).

Examples
--------
Offline out-of-the-box run (deterministic mock LLM, no API keys or GPU required):
    python examples/llm_agent_simulation.py --steps 24 --storage-dir outputs/llm_demo

Local Ollama / vLLM / OpenAI-compatible server:
    python examples/llm_agent_simulation.py --backend openai_compatible \\
        --base-url http://localhost:11434/v1 --model-id qwen2.5:7b-instruct --steps 24

Local HuggingFace Transformers model (matching Generative-Traffic-Agents):
    python examples/llm_agent_simulation.py --backend huggingface \\
        --model-id Qwen/Qwen3-4B-Instruct-2507 --steps 24
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "citylearn").is_dir() and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citylearn.agents.llm import LLMAgent  # noqa: E402
from citylearn.citylearn import CityLearnEnv  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default="citylearn_challenge_2022_phase_all_plus_evs",
        help="Dataset name or path to schema.json.",
    )
    parser.add_argument(
        "--backend",
        choices=["mock", "openai_compatible", "huggingface"],
        default="mock",
        help="LLM backend to use.",
    )
    parser.add_argument(
        "--model-id",
        default=None,
        help="Model identifier (e.g., Qwen/Qwen3-4B-Instruct-2507 or qwen2.5:7b-instruct).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint URL (e.g., http://localhost:11434/v1).",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=12,
        help="Number of episode time steps to simulate.",
    )
    parser.add_argument(
        "--decision-interval",
        type=int,
        default=1,
        help="Query LLM every N control steps and hold bounded actions in between.",
    )
    parser.add_argument(
        "--buildings",
        nargs="*",
        default=["Building_1", "Building_2"],
        help="Subset of buildings to include for fast interactive experimentation.",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=Path("outputs/llm_agent_demo"),
        help="Directory for 1_descriptions.json, 2_day_schedules.json, and 3_decisions.json.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    local_dataset = ROOT / "data" / "datasets" / str(args.dataset) / "schema.json"
    schema_arg = str(local_dataset) if local_dataset.is_file() else args.dataset

    env = CityLearnEnv(
        schema_arg,
        buildings=args.buildings if args.buildings else None,
        episode_time_steps=args.steps,
        interface="flat",
        render_mode="none",
    )
    agent = LLMAgent(
        env,
        backend=args.backend,
        model_id=args.model_id,
        base_url=args.base_url,
        decision_interval_steps=args.decision_interval,
        storage_dir=args.storage_dir,
    )

    observations, _ = env.reset(seed=0)
    terminated = truncated = False

    while not (terminated or truncated):
        actions = agent.predict(observations)
        observations, _, terminated, truncated, _ = env.step(actions)

    agent.storage.flush()
    summary = agent.storage.summarize_decisions()
    print("=== Generative LLM Agent Summary ===")
    print(f"Artifacts directory : {args.storage_dir.resolve()}")
    print(f"Buildings profiled  : {summary['buildings_profiled']} (1_descriptions.json)")
    print(f"Day plans generated : {summary['day_schedules_recorded']} (2_day_schedules.json)")
    print(f"Step records logged : {summary['step_records_recorded']} (3_decisions.json)")

    if summary["sample_rationales"]:
        first = summary["sample_rationales"][0]
        print(
            f"Sample rationale    : [{first['building_name']} t={first['time_step']} "
            f"{first['action_name']}={first['value']:.3f}] {first['reasoning']}"
        )

    kpis = env.evaluate_v2()
    selected = [
        "district_cost_total_control_eur",
        "district_energy_grid_total_import_control_kwh",
        "district_ev_performance_departure_min_acceptable_feasible_ratio",
        "district_electrical_service_phase_violations_energy_total_kwh",
    ]
    print("\n=== District KPIs ===")
    print(
        kpis.loc[
            (kpis["level"] == "district") & kpis["cost_function"].isin(selected),
            ["cost_function", "value"],
        ].to_string(index=False)
    )
    env.close()


if __name__ == "__main__":
    main()
