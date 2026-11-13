# Running Simulations

This page is the operational reference for installing the simulator, creating environments, running episodes, using the CLI and understanding the main execution parameters.

Portuguese version: [pt/running_simulations.md](pt/running_simulations.md).

## Installation

| Case | Command | Notes |
|---|---|---|
| Standard install | `pip install citylearn` | The Python import path is `citylearn`. |
| Parquet datasets | `pip install "citylearn[parquet]"` | Required when schemas or exports use Parquet. |
| CLI and Stable Baselines3 | `pip install "stable-baselines3==2.3.2"` | The current CLI imports this library; use Python 3.11+ for CLI train/evaluate. |
| PV autosizing | `pip install "citylearn[pysam]"` | Required only for EPW/PySAM autosizing. |
| Local development | `.venv/bin/pip install -e .` | Use the repo `.venv` when available. |

## Python Quickstart

```python
import numpy as np
from citylearn.citylearn import CityLearnEnv

schema = "citylearn_challenge_2022_phase_all_plus_evs"
env = CityLearnEnv(schema, interface="flat", episode_time_steps=24, render_mode="none")

observations, info = env.reset()
terminated = truncated = False

while not (terminated or truncated):
    actions = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
    observations, reward, terminated, truncated, info = env.step(actions)

kpis_v2 = env.evaluate_v2()
```

## Entity Interface Quickstart

```python
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv(
    "citylearn_three_phase_dynamic_topology_demo",
    interface="entity",
    topology_mode="dynamic",
)

obs, info = env.reset()
specs = env.entity_specs

actions = {
    "tables": {
        "building": env.action_space["tables"]["building"].sample(),
        "charger": env.action_space["tables"]["charger"].sample(),
        "deferrable_appliance": env.action_space["tables"]["deferrable_appliance"].sample(),
    }
}

obs, reward, terminated, truncated, info = env.step(actions)
```

## Multi-Community Quickstart

Use `MultiCommunityEnv` when one training loop should step several independent communities in lockstep. Each child keeps its own physics, KPIs and demand-response files.

```python
from citylearn.multi_community import MultiCommunityEnv

env = MultiCommunityEnv(
    communities=[
        {
            "community_id": "community_a",
            "schema": "citylearn_challenge_2022_phase_all_plus_evs",
            "env_kwargs": {"interface": "entity", "episode_time_steps": 48},
            "weight": 1.0,
        },
        {
            "community_id": "community_b",
            "schema": "citylearn_challenge_2022_phase_all",
            "env_kwargs": {"interface": "entity", "episode_time_steps": 48},
            "weight": 1.0,
        },
    ]
)

observations, info = env.reset(seed=0)
```

All communities must share `seconds_per_time_step`, effective episode length, `interface` and `central_agent` mode. `evaluate_v2()` returns local rows with `community_id` plus portfolio rows with `level="portfolio"`. See [multi_community_reference.md](multi_community_reference.md).

## `CityLearnEnv` Parameters

| Parameter | Type | Default | Purpose | Notes |
|---|---:|---:|---|---|
| `schema` | `str`, `Path`, `Mapping` | required | Dataset name, schema path or preloaded dict. | Relative paths are resolved from `root_directory`. |
| `root_directory` | path | schema | Base folder for dataset files. | Overrides schema value. |
| `buildings` | list | schema | Subset of buildings to load. | Names or indices. |
| `electric_vehicles` | list | schema | Subset of EVs to load. | Usually from `electric_vehicles_def`. |
| `simulation_start_time_step` | int | schema | First global timestep. | Inclusive. |
| `simulation_end_time_step` | int | schema | Last global timestep. | Inclusive. |
| `episode_time_steps` | int/list | schema | Episode size or explicit windows. | Can be used with rolling/random splits. |
| `rolling_episode_split` | bool | schema | Sequential window episodes. | Useful for training. |
| `random_episode_split` | bool | schema | Random window episodes. | Uses `random_seed`. |
| `seconds_per_time_step` | float | schema | Physical duration of each step. | Examples: 15, 60, 300, 900, 3600. |
| `time_step_ratio` | int/float | inferred | Ratio between control step and dataset spacing. | Normally dataset and schema should match. |
| `reward_function` | class/path | schema | Reward used by `step`. | Supports `reward_function_kwargs`. |
| `reward_function_kwargs` | dict | `{}` | Constructor kwargs for the reward. | Pass-through. |
| `central_agent` | bool | schema | Single controller for all buildings. | `False` returns one vector per building. |
| `shared_observations` | list | schema | Shared observations in central mode. | Included once in central vectors. |
| `active_observations` | list/list[list] | schema | Enable only these observations. | Global or per-building override. |
| `inactive_observations` | list/list[list] | schema/building | Disable observations. | Applied after active selection. |
| `active_actions` | list/list[list] | schema | Enable only these actions. | Global or per-building override. |
| `inactive_actions` | list/list[list] | schema/building | Disable actions. | Applied after active selection. |
| `simulate_power_outage` | bool | schema/building | Enable outage simulation. | Uses data series or stochastic model. |
| `solar_generation` | bool | schema | Compatibility switch for solar generation. | Kept for original CityLearn compatibility. |
| `random_seed` | int | schema | Random seed. | Affects splits and stochastic attributes. |
| `offline` | bool | `False` | Disable network fallbacks. | Requires local datasets. |
| `interface` | `flat`/`entity` | schema/flat | Observation/action contract. | Entity returns tables and edges. |
| `topology_mode` | `static`/`dynamic` | schema/static | Enable dynamic topology events. | Dynamic requires `interface="entity"`. |
| `start_date` | date/string | schema/2024-01-01 | Base date for render/export timestamps. | Does not change physics. |
| `render_mode` | `none`/`during`/`end` | `none` | CSV export policy. | `end` is preferred for performance. |
| `render_session_name` | string | schema/None | Export session subfolder. | Must be relative. |
| `export_kpis_on_episode_end` | bool | render flag | Export KPIs at episode end. | Can be enabled without full render. |

## Extra `**kwargs`

| Parameter | Type | Default | Purpose |
|---|---:|---:|---|
| `render_directory` | path | internal output | Base export folder. |
| `render_directory_name` | string | `render_logs` | Legacy export folder name. |
| `render` | bool | derived | Legacy render switch. |
| `debug_timing` | bool | schema/False | Runtime timing logs. |
| `check_observation_limits` | bool | schema/False | Validate observations against estimated bounds. |
| `physics_invariant_checks` | bool | schema/False | Run physical invariant checks at runtime. |
| `metrics_log_interval` | int | schema/0 | Runtime metric log cadence. |

## Reward Observation Payloads

`step()` builds a smaller reward observation payload when the reward function declares which observation names it needs. Built-in rewards already do this. Custom rewards can opt in with one of these compatible forms:

```python
class MyReward:
    required_observation_names = ("net_electricity_consumption",)

    def calculate(self, observations):
        return [-sum(o["net_electricity_consumption"] for o in observations)]
```

The alias `required_observations` and method `get_required_observation_names()` are also supported. If a custom reward does not declare requirements, CityLearn falls back to full `include_all` observations for backward compatibility.

## Macro-Steps / Action Repeat

`step_many()` repeats one selected action across multiple internal simulator steps and returns one macro transition for RL replay buffers:

```python
obs, rewards, terminated, truncated, info = env.step_many(
    action,
    repeat_steps=20,
    stop_on_done=True,
    return_substeps=False,
)
```

The simulator still advances every internal step at `seconds_per_time_step` resolution. Constraints, EV charging/departures, batteries, deferrables, phases/headroom, rewards, KPIs and render/export time series are updated exactly as they are for repeated `step()` calls. The returned observation is only the final observation after the executed substeps, and `rewards` is the per-agent reward sum.

`info["executed_steps"]` is always present so RL code can discount macro transitions correctly:

```python
gamma_macro = gamma ** info["executed_steps"]
```

When `return_substeps=True`, `info` also includes `substep_rewards`, `substep_infos` and `substep_actions_applied` for debugging. Keep it disabled in long training runs.

## CLI

The current CLI requires Stable Baselines3 even for its listing commands:
install `stable-baselines3==2.3.2` alongside CityLearn. Use Python 3.11 or newer
for `simulate ... train/evaluate`, whose timestamp code uses `datetime.UTC`.
The Python simulation loop above works on supported earlier Python versions
without Stable Baselines3.

```bash
citylearn --version
citylearn list_datasets
citylearn list_default_time_series_variables
citylearn simulate data/datasets/my_dataset/schema.json train -e 3
citylearn simulate data/datasets/my_dataset/schema.json evaluate
```

| Option | Example | Purpose |
|---|---|---|
| `schema` | dataset name or `schema.json` path | Dataset to run. |
| `-a`, `--agent_name` | `citylearn.agents.baseline.BusinessAsUsualAgent` | Agent class path. |
| `-ke`, `--env_kwargs` | `'{"interface":"entity"}'` | JSON kwargs for `CityLearnEnv`. |
| `-ka`, `--agent_kwargs` | `'{"x":1}'` | JSON kwargs for the agent. |
| `-w`, `--wrappers` | wrapper class paths | Gymnasium wrappers. |
| `-tv`, `--time_series_variables` | `net_electricity_consumption` | Series stored after evaluation. |
| `-sid`, `--simulation_id` | `run_001` | Output naming ID. |
| `-fa`, `--agent_filepath` | `outputs/agent.pkl` | Load/save agent path. |
| `-d`, `--output_directory` | `outputs/run_001` | Output folder. |
| `-te`, `--evaluation_episode_time_steps` | `0 2879` | Evaluation window. Can repeat. |
| `-p`, `--append` | flag | Do not overwrite existing output. |
| `-rs`, `--random_seed` | `42` | Seed. |
| `--offline` | flag | Require local files. |
| `train -e` | `train -e 10` | Number of training episodes. |
| `train --save_agent` | flag | Save agent at the end. |
| `train --evaluate` | flag | Evaluate after training. |
| `evaluate` | subcommand | Deterministic evaluation. |

## Render and Export

| `render_mode` | Runtime cost | Output | Use case |
|---|---:|---|---|
| `none` | lowest | No render CSV | Training. |
| `during` | high | Writes rows each step | Short debugging runs. |
| `end` | medium | Writes full episode at end | Long episodes with final CSV output. |

Set `render_file_format="parquet"` to write render, KPI and BAU time-series exports as chunked parquet part files instead of CSV. `render_chunk_size` controls the number of rows per parquet part; the default is `50000` for parquet and `100000` for CSV.

KPI and BAU exports are episode-scoped, so training loops can keep export disabled and turn it on only for the final episode. If normal time-series outputs are needed on that final episode, create the environment with `render_mode="end"` and toggle `render_enabled`; for KPI-only output, leave render disabled and call `export_final_kpis()` manually after the final episode.

```python
for episode in range(episodes):
    last_episode = episode == episodes - 1
    env.render_enabled = last_episode
    env.export_kpis_on_episode_end = last_episode
    observations, info = env.reset()
    # run episode...
```

`export_final_kpis()` controls the BAU cost separately:

| Call | Output | BAU sidecar cost |
|---|---|---:|
| `env.export_final_kpis(include_business_as_usual=False)` | KPI file and audit metadata | no |
| `env.export_final_kpis(include_business_as_usual=True, export_business_as_usual_timeseries=False)` | KPI file with BAU rows and audit metadata | yes |
| `env.export_final_kpis(include_business_as_usual=True, export_business_as_usual_timeseries=True)` | KPI file with BAU rows and BAU time-series file | yes |

Normal episode time series are controlled by `render_mode`/`render_enabled`, not by `export_final_kpis()`.

For exact final-episode choices, keep `export_kpis_on_episode_end=False` and call `export_final_kpis()` yourself after the episode terminates.

## Recommended Validation

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/audit/audit_entity_contract.py --strict
.venv/bin/python scripts/audit/audit_physics.py
.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci --select E9,F821
```

For large 15s datasets, always smoke-test a short window first:

```bash
.venv/bin/python - <<'PY'
import numpy as np
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv(
    "citylearn_three_phase_electrical_service_demo_15s_parquet",
    simulation_start_time_step=0,
    simulation_end_time_step=120,
    episode_time_steps=120,
)
obs, info = env.reset()
for _ in range(100):
    if isinstance(env.action_space, list):
        actions = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
    else:
        actions = {
            "tables": {
                name: np.zeros(space.shape, dtype="float32")
                for name, space in env.action_space["tables"].spaces.items()
            }
        }
    obs, reward, terminated, truncated, info = env.step(actions)
    if terminated or truncated:
        break
print(env.evaluate_v2().head())
PY
```

KPI-only exports include a manifest and service-audit JSON sidecars. They do not
enable episode time-series output; CityLearn UI can load the folder as before.
The manifest identifies input files by their path below the dataset root;
[Portable experiment evidence](developer_guide.md#portable-experiment-evidence)
lists which spellings of a file reference record the same evidence.
