# Generative LLM Agents in CityLearn

CityLearn includes a first-class generative Large Language Model (LLM) agent framework (`citylearn.llm` and `citylearn.agents.llm.LLMAgent`) modeled after the modular cognitive architecture introduced in [ciao-group/Generative-Traffic-Agents](https://github.com/ciao-group/Generative-Traffic-Agents).

## Architecture Overview

Each active building is controlled through a three-stage generative pipeline with persistent JSON artifacts for inspection, auditing, and replay:

| Stage | Module | Artifact File | Purpose |
| --- | --- | --- | --- |
| **1. Grounded Persona Synthesis** | `BuildingSeedGenerator` + `ProfileModule` | `1_descriptions.json` | Extracts static equipment capacities (PV kWp, battery kWh/kW, reserve SoC, thermal storage, EV chargers, deferrable loads, annual demand estimates) and synthesizes a natural-language prosumer persona and priority list. |
| **2. Daily Energy Schedule** | `PlanningModule.plan_day_schedule` | `2_day_schedules.json` | Generates a 24-hour energy operating schedule (`description_of_today`, solar charging window, peak avoidance plan, EV readiness plan) at episode start and each day rollover. |
| **3. Step Action Selection** | `PlanningModule.select_actions` | `3_decisions.json` | Prompts the LLM with unnormalized active observations, daily plan context, physical action bounds, and EV charger deadbands; parses noisy or `<think>`-wrapped outputs via `extract_json_from_polluted_string` and clamps actions to `[low, high]`. |

## Installation

Core HTTP (`OpenAICompatibleChatAPI`) and offline (`RuleGuidedMockChatAPI`) backends work with a standard CityLearn installation:

```bash
pip install -e .
```

To run local open-weight models via HuggingFace `transformers` (`HuggingfaceChatAPI`, defaulting to `Qwen/Qwen3-4B-Instruct-2507` as in Generative-Traffic-Agents):

```bash
pip install -e ".[llm]"
```

## Quickstart

### 1. Python API (Offline, Local HuggingFace, or Ollama / vLLM / OpenAI)

```python
from citylearn.agents.llm import LLMAgent
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv(
    "citylearn_challenge_2022_phase_all_plus_evs",
    buildings=["Building_1", "Building_2"],
    episode_time_steps=24,
    interface="flat",
    render_mode="none",
)

# Choose backend="mock" (offline), "huggingface", or "openai_compatible":
agent = LLMAgent(
    env,
    backend="mock",
    storage_dir="outputs/llm_run",
    enable_day_planning=True,
    decision_interval_steps=1,
)

observations, info = env.reset(seed=0)
terminated = truncated = False
while not (terminated or truncated):
    actions = agent.predict(observations)
    observations, rewards, terminated, truncated, info = env.step(actions)

print(agent.storage.summarize_decisions())
print(env.evaluate_v2().head())
env.close()
```

### 2. Local Open-Weight Models via HuggingFace (`Qwen/Qwen3-4B-Instruct-2507`)

```python
from citylearn.agents.llm import LLMAgent
from citylearn.llm import HuggingfaceChatAPI

llm_client = HuggingfaceChatAPI(
    model_id="Qwen/Qwen3-4B-Instruct-2507",
    n_predict=700,
    gpu_id=0,
    temperature=0.2,
)
agent = LLMAgent(env, llm_client=llm_client, storage_dir="outputs/qwen_run")
```

### 3. Ollama, vLLM, LiteLLM, OpenRouter, or OpenAI Endpoints

```python
from citylearn.agents.llm import LLMAgent
from citylearn.llm import OpenAICompatibleChatAPI

llm_client = OpenAICompatibleChatAPI(
    base_url="http://localhost:11434/v1",  # or https://api.openai.com/v1
    model_id="qwen2.5:7b-instruct",        # or gpt-4o-mini
    api_key="",                            # or set CITYLEARN_LLM_API_KEY / OPENAI_API_KEY
    temperature=0.2,
)
agent = LLMAgent(env, llm_client=llm_client, storage_dir="outputs/ollama_run")
```

### 4. Schema / CLI Configuration

`LLMAgent` works directly with `env.load_agent()` and `citylearn simulate` by configuring the `"agent"` section in `schema.json`:

```json
{
  "agent": {
    "type": "citylearn.agents.llm.LLMAgent",
    "attributes": {
      "backend": "openai_compatible",
      "base_url": "http://localhost:11434/v1",
      "model_id": "qwen2.5:7b-instruct",
      "storage_dir": "outputs/cli_llm_agent",
      "enable_day_planning": true,
      "decision_interval_steps": 1
    }
  }
}
```

## Compatibility & Safety Guarantees

- **Flat, Entity & Dynamic Topology**: `LLMAgent` works in `central_agent=True` and `central_agent=False`, `interface="flat"` and `interface="entity"`, and `topology_mode="dynamic"` (lazily synthesizing personas and daily schedules when new buildings join mid-episode).
- **Benchmark Fairness**: By default (`include_all_observations=False`), prompts receive only active building observations (`observation_access="active_only"`) in physical units alongside static equipment ratings.
- **Bounded Fallback & Deadband Awareness**: Every LLM output is parsed through `extract_json_from_polluted_string`, validated for finiteness, and clamped to `[low, high]`. Missing or malformed JSON safely falls back to neutral bounded actions without crashing long simulations.
- **Sub-hourly Cadence Control**: Set `decision_interval_steps > 1` on minute-resolution datasets to query the LLM every $N$ control steps while holding bounded actions on intermediate steps.
