# Como Correr Simulacoes

Esta pagina e a referencia pratica para instalar, criar um ambiente, correr episodios, usar a CLI e controlar todos os parametros principais de execucao.

## Instalacao

| Caso | Comando | Notas |
|---|---|---|
| Instalacao normal | `pip install citylearn` | O import Python e `citylearn`. |
| Datasets Parquet | `pip install pyarrow` | Necessario apenas se o schema apontar para `.parquet`, `.pq` ou `.parq`. |
| PV autosizing | `pip install "citylearn[pysam]"` | Necessario apenas para autosizing via EPW/PySAM. |
| Desenvolvimento local | `.venv/bin/pip install -e .` | Usar a `.venv` do repo quando existir. |

## Quickstart Python

```python
import numpy as np
from citylearn.citylearn import CityLearnEnv

schema = "citylearn_challenge_2022_phase_all_plus_evs"
env = CityLearnEnv(schema, interface="flat", episode_time_steps=24, render_mode="none")

observations, info = env.reset()
terminated = False
truncated = False

while not (terminated or truncated):
    actions = [np.zeros(space.shape, dtype="float32") for space in env.action_space]
    observations, reward, terminated, truncated, info = env.step(actions)

kpis_v2 = env.evaluate_v2()
```

## Quickstart Entity Interface

```python
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv(
    "citylearn_three_phase_dynamic_topology_demo",
    interface="entity",
    topology_mode="dynamic",
)

obs, info = env.reset()
specs = env.entity_specs

action_payload = {
    "tables": {
        "building": env.action_space["tables"]["building"].sample(),
        "charger": env.action_space["tables"]["charger"].sample(),
        "deferrable_appliance": env.action_space["tables"]["deferrable_appliance"].sample(),
    }
}

obs, reward, terminated, truncated, info = env.step(action_payload)
```

## Quickstart Multi-Comunidade

Usa `MultiCommunityEnv` quando um loop de treino deve avancar varias comunidades independentes em lockstep. Cada filho mantem a sua propria fisica, KPIs e ficheiros de demand response.

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

Todas as comunidades tem de partilhar `seconds_per_time_step`, episode length efetivo, `interface` e modo `central_agent`. `evaluate_v2()` devolve linhas locais com `community_id` e linhas portfolio com `level="portfolio"`. Ver [multi_community_reference.md](multi_community_reference.md).

## Parametros de `CityLearnEnv`

| Parametro | Tipo | Default | O que faz | Notas |
|---|---:|---:|---|---|
| `schema` | `str`, `Path`, `Mapping` | requerido | Nome de dataset, caminho para `schema.json` ou dict ja carregado. | Caminhos relativos sao resolvidos com `root_directory`. |
| `root_directory` | `str`, `Path` | schema | Pasta base dos ficheiros do dataset. | Override do valor no schema. |
| `buildings` | lista | schema | Subconjunto de buildings a carregar. | Pode usar nomes ou indices. |
| `electric_vehicles` | lista | schema | Subconjunto de EVs a carregar. | Normalmente vem de `electric_vehicles_def`. |
| `simulation_start_time_step` | `int` | schema | Primeiro timestep global usado. | Inclusivo. |
| `simulation_end_time_step` | `int` | schema | Ultimo timestep global usado. | Inclusivo. |
| `episode_time_steps` | `int` ou lista | schema | Tamanho do episodio ou janelas explicitas. | Pode ser combinado com split rolling/random. |
| `rolling_episode_split` | `bool` | schema | Cria episodios em janelas sequenciais. | Usado para treino em janelas. |
| `random_episode_split` | `bool` | schema | Escolhe episodios aleatorios dentro da janela. | Usa `random_seed`. |
| `seconds_per_time_step` | `float` | schema | Duracao fisica de cada step. | Ex.: 15, 60, 300, 900, 3600. |
| `time_step_ratio` | `int`, `float` | inferido | Razao entre step do agente e resolucao do dataset. | Normalmente dataset e schema devem ter a mesma resolucao. |
| `reward_function` | classe ou path | schema | Reward usado no `step`. | Pode receber `reward_function_kwargs`. |
| `reward_function_kwargs` | `dict` | `{}` | Parametros do reward. | Pass-through para o construtor. |
| `central_agent` | `bool` | schema | Um agente controla todos os buildings. | `False` retorna uma action/obs por building. |
| `shared_observations` | lista | schema | Observacoes partilhadas no modo central. | Incluidas so uma vez no vetor central. |
| `active_observations` | lista ou lista de listas | schema | Liga apenas estas observacoes. | Override global ou por building. |
| `inactive_observations` | lista ou lista de listas | schema/building | Desliga observacoes. | Tem precedencia depois de `active_observations`. |
| `active_actions` | lista ou lista de listas | schema | Liga apenas estas acoes. | Override global ou por building. |
| `inactive_actions` | lista ou lista de listas | schema/building | Desliga acoes. | Tem precedencia depois de `active_actions`. |
| `simulate_power_outage` | `bool` | schema/building | Ativa outage simulada. | Pode usar serie do dataset ou modelo estocastico. |
| `solar_generation` | `bool` | schema | Controla uso de geracao solar. | Compatibilidade com CityLearn original. |
| `random_seed` | `int` | schema | Semente de aleatoriedade. | Afeta splits e parametros estocasticos. |
| `offline` | `bool` | `False` | Desativa fallback por rede. | Requer datasets locais. |
| `interface` | `flat` ou `entity` | schema/flat | Formato de observacao/acao. | `entity` retorna tabelas e edges. |
| `topology_mode` | `static` ou `dynamic` | schema/static | Permite add/remove members/assets. | `dynamic` requer `interface="entity"`. |
| `start_date` | data/string | schema/2024-01-01 | Data inicial usada em export/render. | Nao muda a fisica, apenas timestamps de saida. |
| `render_mode` | `none`, `during`, `end` | `none` | Politica de export CSV. | `end` e preferivel para performance. |
| `render_session_name` | `str` | schema/None | Subpasta da sessao de export. | Tem de ser relativo. |
| `export_kpis_on_episode_end` | `bool` | `render_enabled` | Exporta KPIs no fim do episodio. | Pode ser ativado sem render completo. |

## Parametros extras aceites por `**kwargs`

| Parametro | Tipo | Default | O que faz |
|---|---:|---:|---|
| `render_directory` | path | cwd/output interno | Pasta base absoluta ou relativa para exports. |
| `render_directory_name` | string | `render_logs` | Nome legacy quando `render_directory` nao e dado. |
| `render` | bool | derivado de `render_mode` | Flag legacy para ligar/desligar export. |
| `debug_timing` | bool | schema/False | Mede tempos de partes do `step`. |
| `check_observation_limits` | bool | schema/False | Valida observacoes contra os limites estimados. |
| `physics_invariant_checks` | bool | schema/False | Ativa checks de invariantes fisicos por step. |
| `metrics_log_interval` | int | schema/0 | Frequencia de logs de metricas runtime. |

## Payload de Observacoes para Reward

O `step()` constroi um payload de observacoes mais pequeno para o reward quando a reward function declara que nomes de observacao precisa. Os rewards built-in ja fazem isto. Rewards externos podem optar por um destes formatos compativeis:

```python
class MyReward:
    required_observation_names = ("net_electricity_consumption",)

    def calculate(self, observations):
        return [-sum(o["net_electricity_consumption"] for o in observations)]
```

Tambem sao aceites o alias `required_observations` e o metodo `get_required_observation_names()`. Se um reward externo nao declarar requisitos, o CityLearn volta a usar observacoes completas com `include_all` para manter compatibilidade.

## Macro-Steps / Action Repeat

`step_many()` repete uma acao escolhida durante varios steps internos do simulador e devolve uma unica transicao macro para replay buffers de RL:

```python
obs, rewards, terminated, truncated, info = env.step_many(
    action,
    repeat_steps=20,
    stop_on_done=True,
    return_substeps=False,
)
```

O simulador continua a avancar cada step interno com a resolucao de `seconds_per_time_step`. Constraints, EV charging/departures, baterias, deferrables, fases/headroom, rewards, KPIs e series de render/export sao atualizados exatamente como em chamadas repetidas a `step()`. A observacao devolvida e apenas a observacao final depois dos substeps executados, e `rewards` e a soma de reward por agente.

`info["executed_steps"]` vem sempre preenchido para o codigo RL descontar transicoes macro corretamente:

```python
gamma_macro = gamma ** info["executed_steps"]
```

Quando `return_substeps=True`, o `info` tambem inclui `substep_rewards`, `substep_infos` e `substep_actions_applied` para debug. Manter desligado em treinos longos.

## CLI

Na versão 3.0.2, a CLI requer `python -m pip install stable-baselines3==2.3.2`.
Para os comandos de treino e avaliação, usar Python 3.11 ou mais recente.
A primeira simulação pela API Python não exige esta dependência.

```bash
citylearn --version
citylearn list_datasets
citylearn list_default_time_series_variables
citylearn simulate data/datasets/my_dataset/schema.json train -e 3
citylearn simulate data/datasets/my_dataset/schema.json evaluate
```

| Opcao CLI | Exemplo | O que faz |
|---|---|---|
| `schema` | `citylearn_challenge_2020_climate_zone_2` ou path | Dataset ou ficheiro de schema. |
| `-a`, `--agent_name` | `citylearn.agents.baseline.BusinessAsUsualAgent` | Classe do agente. |
| `-ke`, `--env_kwargs` | `'{"interface":"entity"}'` | JSON com kwargs de `CityLearnEnv`. |
| `-ka`, `--agent_kwargs` | `'{"some_arg":1}'` | JSON passado ao agente. |
| `-w`, `--wrappers` | `citylearn.wrappers.ClippedObservationWrapper` | Wrappers Gymnasium. |
| `-tv`, `--time_series_variables` | `net_electricity_consumption` | Series exportadas no JSON pos-avaliacao. |
| `-sid`, `--simulation_id` | `run_001` | ID usado nos nomes de outputs. |
| `-fa`, `--agent_filepath` | `outputs/agent.pkl` | Agente salvo para load/evaluate. |
| `-d`, `--output_directory` | `outputs/run_001` | Pasta de saida. |
| `-te`, `--evaluation_episode_time_steps` | `0 2879` | Janela de avaliacao. Pode repetir. |
| `-p`, `--append` | flag | Nao apaga saida existente. |
| `-rs`, `--random_seed` | `42` | Semente. |
| `--offline` | flag | Obriga dados locais. |
| `train -e` | `train -e 10` | Numero de episodios. |
| `train --save_agent` | flag | Guarda o agente no fim. |
| `train --evaluate` | flag | Avalia depois do treino. |
| `evaluate` | subcomando | Avaliacao deterministica. |

## Export e Render

| `render_mode` | Custo runtime | Saidas | Quando usar |
|---|---:|---|---|
| `none` | minimo | Sem CSV de render | Treino normal. |
| `during` | alto | Escreve por step | Debug curto, inspecao em tempo real. |
| `end` | medio | Bufferiza e escreve no fim | Episodios longos em que queres CSV final. |

Usa `render_file_format="parquet"` para escrever exports de render, KPIs e serie temporal BAU como ficheiros parquet em partes, em vez de CSV. `render_chunk_size` controla o numero de linhas por parte parquet; o default e `50000` para parquet e `100000` para CSV.

KPIs e exports BAU sao por episodio, portanto um loop de treino pode manter export desligado e ligar apenas no ultimo episodio. Se forem precisas series temporais normais nesse episodio final, criar o ambiente com `render_mode="end"` e alternar `render_enabled`; para output so de KPIs, deixar render desligado e chamar `export_final_kpis()` manualmente depois do episodio final.

```python
for episode in range(episodes):
    last_episode = episode == episodes - 1
    env.render_enabled = last_episode
    env.export_kpis_on_episode_end = last_episode
    observations, info = env.reset()
    # correr episodio...
```

`export_final_kpis()` controla o custo BAU separadamente:

| Chamada | Output | Custo BAU sidecar |
|---|---|---:|
| `env.export_final_kpis(include_business_as_usual=False)` | So ficheiro de KPIs | nao |
| `env.export_final_kpis(include_business_as_usual=True, export_business_as_usual_timeseries=False)` | Ficheiro de KPIs com linhas BAU | sim |
| `env.export_final_kpis(include_business_as_usual=True, export_business_as_usual_timeseries=True)` | Ficheiro de KPIs com linhas BAU e serie temporal BAU | sim |

As series temporais normais do episodio sao controladas por `render_mode`/`render_enabled`, nao por `export_final_kpis()`.

Para escolher exatamente o output do episodio final, manter `export_kpis_on_episode_end=False` e chamar `export_final_kpis()` manualmente depois de o episodio terminar.

## Comandos de validacao recomendados

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/audit/audit_entity_contract.py --strict
.venv/bin/python scripts/audit/audit_physics.py
.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci --select E9,F821
```

Para datasets de 15 segundos, valida pelo menos um episodio pequeno antes de treino anual:

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

Os exports apenas de KPIs incluem o manifesto e os metadados JSON de auditoria
de serviço. Estes ficheiros não ativam séries temporais do episódio; a pasta
continua compatível com a CityLearn UI.
