# Running Simulations

This page is the operational reference for installing the simulator, creating environments, running episodes, using the CLI and understanding the main execution parameters.

Portuguese version: [pt/running_simulations.md](pt/running_simulations.md).

## Installation

| Case | Command | Notes |
|---|---|---|
| Standard install | `pip install citylearn` | The Python import path is `citylearn`. |
| LSTM thermal dynamics | `pip install "citylearn[dynamics]"` | Adds PyTorch; required by the 2023 challenge, Quebec, `baeda_3dem` and EULP neighbourhood datasets. |
| SAC and MARLISA | `pip install "citylearn[rl]"` | Adds PyTorch and scikit-learn. For a CPU-only PyTorch, first run `pip install torch --index-url https://download.pytorch.org/whl/cpu`. |
| Parquet datasets | `pip install "citylearn[parquet]"` | Required when schemas or exports use Parquet. |
| Stable Baselines3 | `pip install "stable-baselines3>=2.4"` | Required only for Stable Baselines3 agents, in Python or in the CLI. |
| PV autosizing | `pip install "citylearn[pysam]"` | Required only for EPW/PySAM autosizing. |
| Local development | `.venv/bin/pip install -e .` | Use the repo `.venv` when available. |

## Episode Loop Without a Controller

For a first run with its expected output, and a comparison with the
business-as-usual controller, follow the
[quickstart](https://www.citylearn.net/quickstart.html). The loop below is the
smallest possible episode: it sends zero for every action, whose effect
follows each device's action contract.

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

## Entity Interface Example

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

## Multi-Community Example

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

All communities must share `seconds_per_time_step`, effective episode length, `interface`, `central_agent` mode, `physics_version`, `random_stream_version` and `baseline_version`. `evaluate_v2()` returns local rows with `community_id` plus portfolio rows with `level="portfolio"`. See [multi_community_reference.md](multi_community_reference.md).

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
| `episode_split_boundary` | str | `shared` | How consecutive (non-rolling) splits meet. | `shared` shares the boundary row so every interval is simulated; `disjoint` restores the 3.6.0 splits. |
| `ev_soc_carryover` | bool | `False` | Start each EV of an episode that continues the previous one in time from its SOC at the end of that episode. | Only the EV SOC is carried. Off, episodes are independent but a session across a boundary loses its charge; on, consecutive episodes depend on the previous controller. See the [KPI reference](kpis_reference.md#departures). |
| `seconds_per_time_step` | float | schema | Physical duration of each step. | Examples: 15, 60, 300, 900, 3600. |
| `time_step_ratio` | int/float | inferred | Ratio between control step and dataset spacing. | Inferred from the data; a value passed here must match it. |
| `time_step_ratio_mode` | str | `reject` | What to do when the control step differs from the dataset step. | `reject` raises an error; `compress` keeps the 3.6.0 behaviour (one data row per step, energies scaled). |
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
| `render_directory` | path | `./render_logs` | Base export folder; relative paths resolve against the working directory. |
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

## Reading Latest Step Values

`CityLearnEnv` stores episode rewards and the three district net-consumption series in preallocated `float64` buffers. Accessing a full-history list property (`env.rewards`, `env.net_electricity_consumption`, `env.net_electricity_consumption_cost`, `env.net_electricity_consumption_emission`) lazily materializes a tracked Python `list` that extends incrementally per step and detaches before any in-place mutation, so existing `[-1]` monitoring loops remain `O(1)` per step while caller edits stay isolated.

Read the latest value with `[-1]`. Each read takes constant time per step.

```python
latest_reward_row = env.rewards[-1]
latest_net_kwh = env.net_electricity_consumption[-1]
latest_cost_eur = env.net_electricity_consumption_cost[-1]
latest_emission_kgco2 = env.net_electricity_consumption_emission[-1]
```

## CLI

The CLI needs only CityLearn for its listing commands and for the default
agent, the business-as-usual `BusinessAsUsualAgent`. Training or evaluating a
Stable Baselines3 agent also needs `stable-baselines3>=2.4`, and the bundled
`SAC` and `MARLISA` agents need the `rl` extra. Every command works on Python
3.10 or newer.

```bash
citylearn --version
citylearn list_datasets
citylearn list_default_time_series_variables
citylearn simulate data/datasets/my_dataset/schema.json train -e 3
citylearn simulate data/datasets/my_dataset/schema.json evaluate
```

`simulate` writes a training summary (`<simulation_id>-train.json`), the
evaluation files and, with `--save_agent`, the agent to the output directory,
and prints the path of each file it writes. `evaluate` and `train --evaluate`
write two evaluation files:

- `<simulation_id>-evaluation_v2.csv`: the `evaluate_v2()` table, with the
  columns `cost_function`, `value`, `name`, `level`, `unit` and `description`,
  one row per KPI and scope. It holds the community market rows when the
  scenario has a market, and the `*_business_as_usual_*` rows. This is the table
  that the [KPI reference](kpis_reference.md) and the scorecard describe; read
  it with `pandas.read_csv`.
- `<simulation_id>-evaluation.json`: the evaluation window and timestamps, the
  rewards, the actions and the time series, plus the legacy `evaluate()` KPIs
  under `evaluation`. Its format does not change, so existing parsers keep
  working, but compare controllers with the `evaluate_v2()` file.

The business-as-usual rows need a second rollout of `BusinessAsUsualAgent` on the
evaluation window, as `evaluate_v2()` does in Python. `--no_business_as_usual`
skips it and writes the table without those rows.

### Stable Baselines3 agent

A Stable Baselines3 agent needs its policy in the agent arguments and the
environment wrapped into one flat observation and action vector, which requires
a central agent. This command trains SAC for five daily episodes on the first
week and evaluates it on the first training episode:

```bash
citylearn simulate citylearn_challenge_2022_phase_all_plus_evs \
  -a stable_baselines3.SAC -ka '{"policy": "MlpPolicy"}' \
  -w citylearn.wrappers.NormalizedObservationWrapper citylearn.wrappers.StableBaselines3Wrapper \
  -ke '{"central_agent": true, "episode_time_steps": 24, "simulation_end_time_step": 167}' \
  -rs 0 -d outputs/sb3_sac -sid sb3_sac train -e 5 --evaluate --save_agent
```

Without `"policy"`, the CLI raises a `TypeError` that shows the argument to add.
Use `-te start end` to evaluate on other windows, such as unseen days.

To evaluate or keep training a saved model, pass it with `-fa` and name the
algorithm that saved it with `-a`, for example `-a stable_baselines3.SAC -fa
outputs/sb3_sac/sb3_sac-agent.zip`. Write to another directory with `-d`:
`simulate` empties its output directory first, so it refuses to run when that
directory holds the model to load.

What the Stable Baselines3 integration supports:

- **Central agent, flat interface.** `StableBaselines3Wrapper` turns the central
  agent's observation and action vectors into one `Box` each. With
  `central_agent=False` there is one vector per building, and the wrapper raises
  an error; for one policy per building, use `RLlibMultiAgentEnv`.
- **No entity interface.** The entity observations are dictionaries of tables
  whose sizes can change, which the SB3 policies cannot take. The `pt_rec_*`,
  three-phase, demand-response and robustness datasets default to the entity
  interface, so pass `"interface": "flat"` in `-ke` (or `interface="flat"` in
  Python). Dynamic topology and demand response need the entity interface and
  cannot be used with SB3.
- **Action bounds.** The action space keeps each device's bounds, for example
  [-1, 1] for storage and EV chargers and [0, 1] for others, so `check_env`
  warns that it is not symmetric. SAC rescales its actions to the bounds and PPO
  clips them, so both work as they are.
- **Robustness faults.** A missing sensor reading is replaced by
  `missing_replacement_value` (-9999 in `citylearn_challenge_2022_phase_all_robustness`),
  which normalises far outside [0, 1]. SB3 does not check observation bounds,
  but the policy sees that value as it is.

`tests/test_stable_baselines3_integration.py` runs `check_env`, a few SAC and PPO
updates, `predict` over one episode with every observation inside its space,
`evaluate_v2()`, and the CLI saving and loading a model.

### Evaluation window

`evaluate` runs one episode of the environment's episode windows, or the
windows that `-te` gives. `train --evaluate` evaluates on the first training
episode window: with `-ke '{"episode_time_steps": 24}'` it evaluates 24 time
steps, not the whole dataset. Without `episode_time_steps`, the episode, and so
the evaluation, covers the whole simulation window.

### Host information

The training summary records the machine host name and the user name only with
`--record_host`, so results can be shared without them.

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
| `--record_host` | flag | Record the host and user names in the training summary. |
| `--no_business_as_usual` | flag | Write the `evaluate_v2()` table without the business-as-usual rows. |
| `train -e` | `train -e 10` | Number of training episodes. |
| `train --save_agent` | flag | Save agent at the end. |
| `train --evaluate` | flag | Evaluate after training, on the first training episode window unless `-te` is given. |
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

## Smoke-Test a Large Dataset

For large 15s datasets, always run a short window first:

```bash
python - <<'PY'
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

## Validation from a Source Checkout

The test suite and the audit scripts are in the repository, not in the package
that `pip install citylearn` installs. Run them from a clone, with the test
requirements installed (see the [developer guide](developer_guide.md) and the
[validation guide](validation.md)):

```bash
python -m pytest -q
python scripts/audit/audit_entity_contract.py --strict
python scripts/audit/audit_physics.py
python -m ruff check citylearn tests scripts/manual scripts/ci
```

KPI-only exports include a manifest and service-audit JSON sidecars. They do not
enable episode time-series output; CityLearn UI can load the folder as before.
The manifest identifies input files by their path below the dataset root;
[Portable experiment evidence](developer_guide.md#portable-experiment-evidence)
lists which spellings of a file reference record the same evidence.
