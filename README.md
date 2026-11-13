# CityLearn

CityLearn is an open-source Gymnasium environment for building energy coordination, demand response and reinforcement learning. Use it to configure renewable energy communities, run controllers and compare energy, cost and service outcomes.

CityLearn v3 brings together buildings and thermal systems, PV, batteries, EVs and flexible loads with electrical limits, local energy sharing, changing members and assets, and data or equipment failures. It builds on the CityLearn community's work and the extensions developed by the Soft-CPS Research Group.

[Documentation](https://www.citylearn.net/) · [Features](https://www.citylearn.net/guides/features.html) · [KPIs and scorecard](https://www.citylearn.net/guides/scorecard.html) · [CityLearn UI](https://citylearnui.netlify.app/)

## Install

```console
python -m pip install citylearn
```

Use Python 3.9 or newer in a virtual environment. See the [installation guide](https://www.citylearn.net/installation.html) for setup and optional dependencies, including Parquet support.

## Configure your community

<p align="center">
  <a href="https://raw.githubusercontent.com/citylearn-project/CityLearn/master/assets/images/citylearn-v3-overview.png">
    <img src="https://raw.githubusercontent.com/citylearn-project/CityLearn/master/assets/images/citylearn-v3-overview.png" alt="CityLearn v3: configurable renewable energy communities with buildings, PV, storage, EVs, flexible loads, controllers, electrical limits, demand response and community KPIs." width="680">
  </a>
</p>

The figure illustrates community configurations and services available in CityLearn. Individual scenarios can use different time resolutions; synchronized multi-community runs use a common timestep.

## Run your first simulation

This example downloads a public dataset on first use, runs a short episode with the built-in business-as-usual controller and prints community KPIs. It works outside a repository checkout.

```python
from citylearn.agents.baseline import BusinessAsUsualAgent
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv(
    "citylearn_challenge_2022_phase_all_plus_evs",
    episode_time_steps=24,
    interface="flat",
    render_mode="none",
)
agent = BusinessAsUsualAgent(env)
observations, info = env.reset(seed=0)
terminated = truncated = False

while not (terminated or truncated):
    actions = agent.predict(observations)
    observations, rewards, terminated, truncated, info = env.step(actions)

kpis = env.evaluate_v2()
selected = [
    "district_cost_total_control_eur",
    "district_energy_grid_total_import_control_kwh",
    "district_ev_performance_departure_min_acceptable_feasible_ratio",
    "district_electrical_service_phase_violations_energy_total_kwh",
]
print(kpis.loc[
    (kpis["level"] == "district") & kpis["cost_function"].isin(selected),
    ["cost_function", "value"],
].to_string(index=False))
env.close()
```

The [first-simulation guide](https://www.citylearn.net/quickstart.html) explains the loop, outputs and next steps. A runnable copy is in [examples/first_simulation.py](https://github.com/citylearn-project/CityLearn/blob/master/examples/first_simulation.py).

## Learn more

- [Features and configuration](https://www.citylearn.net/guides/features.html): choose assets, services, interfaces and scenario conditions.
- [Running simulations](https://www.citylearn.net/guides/running_simulations.html): Python, CLI, datasets, exports and advanced examples.
- [Baselines](https://www.citylearn.net/guides/baselines.html), [KPIs](https://www.citylearn.net/kpis.html) and [scorecard](https://www.citylearn.net/guides/scorecard.html): understand the reference controllers, metrics and comparisons.
- [Generative LLM agents](docs/llm_agents.md) and [examples/llm_agent_simulation.py](examples/llm_agent_simulation.py): run persona-grounded, schedule-driven LLM controllers (`citylearn[llm]`, Ollama/vLLM, or OpenAI-compatible APIs).
- [CityLearn UI](https://citylearnui.netlify.app/): inspect exported time series and compare results.
- [Contributing](https://www.citylearn.net/contributing.html): report issues, contribute code and find the developer guide.

## Cite and contribute

See [Publications and applications](https://www.citylearn.net/publications.html) and [Cite CityLearn](https://www.citylearn.net/#cite-citylearn) for studies and the published reference. CityLearn is distributed under the [MIT license](https://github.com/citylearn-project/CityLearn/blob/master/LICENSE); its development is supported by the [project contributors](https://github.com/citylearn-project/CityLearn/graphs/contributors).
