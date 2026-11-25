# Executar simulações

Esta página é a referência operacional para instalar o simulador, criar ambientes, executar episódios, usar a CLI e compreender os principais parâmetros de execução.

Versão em inglês: [../running_simulations.md](../running_simulations.md).

## Instalação

| Caso | Comando | Notas |
|---|---|---|
| Instalação normal | `pip install citylearn` | O caminho de importação Python é `citylearn`. |
| Dinâmica térmica LSTM | `pip install "citylearn[dynamics]"` | Acrescenta o PyTorch; necessário para os datasets do desafio de 2023, do Quebec, `baeda_3dem` e dos bairros EULP. |
| SAC e MARLISA | `pip install "citylearn[rl]"` | Acrescenta o PyTorch e o scikit-learn. Para um PyTorch só para CPU, execute primeiro `pip install torch --index-url https://download.pytorch.org/whl/cpu`. |
| Datasets Parquet | `pip install "citylearn[parquet]"` | Necessário quando os schemas ou as exportações usam Parquet. |
| Stable Baselines3 | `pip install "stable-baselines3>=2.4"` | Necessário apenas para agentes Stable Baselines3, em Python ou na CLI. |
| Dimensionamento automático FV | `pip install "citylearn[pysam]"` | Necessário apenas para o dimensionamento automático com EPW/PySAM. |
| Desenvolvimento local | `.venv/bin/pip install -e .` | Use a `.venv` do repositório quando existir. |

## Ciclo de episódio sem controlador

Para uma primeira execução com o output esperado, e uma comparação com o
controlador business-as-usual, siga o
[quickstart](https://www.citylearn.net/quickstart.html). O ciclo abaixo é o
episódio mais pequeno possível: envia zero em todas as ações, cujo efeito segue
o contrato de ação de cada equipamento.

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

## Exemplo da interface entity

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

## Exemplo multicomunidade

Use `MultiCommunityEnv` quando um único ciclo de treino deve avançar várias comunidades independentes em simultâneo, passo a passo. Cada comunidade filha mantém a sua própria física, os seus KPIs e os seus ficheiros de resposta à procura.

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

Todas as comunidades têm de partilhar `seconds_per_time_step`, a duração efetiva do episódio, a `interface`, o modo `central_agent`, `physics_version`, `random_stream_version` e `baseline_version`. `evaluate_v2()` devolve linhas locais com `community_id` e linhas de portefólio com `level="portfolio"`. Consulte [multi_community_reference.md](multi_community_reference.md).

## Parâmetros de `CityLearnEnv`

| Parâmetro | Tipo | Predefinição | Finalidade | Notas |
|---|---:|---:|---|---|
| `schema` | `str`, `Path`, `Mapping` | obrigatório | Nome do dataset, caminho do schema ou dict já carregado. | Os caminhos relativos são resolvidos a partir de `root_directory`. |
| `root_directory` | caminho | schema | Pasta base dos ficheiros do dataset. | Substitui o valor do schema. |
| `buildings` | lista | schema | Subconjunto de edifícios a carregar. | Nomes ou índices. |
| `electric_vehicles` | lista | schema | Aceite, mas não escolhe VE. | Use `electric_vehicles_def.<ev>.include` no schema. |
| `simulation_start_time_step` | int | schema | Primeiro passo de tempo global. | Inclusivo. |
| `simulation_end_time_step` | int | schema | Último passo de tempo global. | Inclusivo. |
| `episode_time_steps` | int/lista | schema | Tamanho do episódio ou janelas explícitas. | Pode ser usado com divisões sequenciais (rolling) ou aleatórias. |
| `rolling_episode_split` | bool | schema | Qualquer linha pode iniciar um episódio (janelas sobrepostas). | Útil para treino. |
| `random_episode_split` | bool | schema | Episódios em janelas aleatórias. | Usa `random_seed`. |
| `episode_split_boundary` | str | `shared` | Como se ligam divisões consecutivas (não rolling). | `shared` partilha a linha de fronteira, pelo que todos os intervalos são simulados; `disjoint` repõe as divisões da 3.6.0. |
| `ev_soc_carryover` | bool | `False` | Começa cada VE de um episódio que continua o anterior no tempo com o SOC que tinha no fim desse episódio. | Só o SOC dos VE é transportado. Desligado, os episódios são independentes mas uma sessão através de uma fronteira perde a carga; ligado, episódios consecutivos dependem do controlador anterior. Ver [Partidas](kpis_reference.md#partidas). |
| `seconds_per_time_step` | float | schema | Duração física de cada passo. | Exemplos: 15, 60, 300, 900, 3600. |
| `time_step_ratio` | int/float | inferido | Razão entre o passo de controlo e o espaçamento do dataset. | Inferido a partir dos dados; um valor passado aqui tem de coincidir com ele. |
| `time_step_ratio_mode` | str | `reject` | O que fazer quando o passo de controlo difere do passo do dataset. | `reject` gera um erro; `compress` mantém o comportamento da 3.6.0 (uma linha de dados por passo, energias escaladas). |
| `reward_function` | classe/caminho | schema | Recompensa usada por `step`. | Suporta `reward_function_kwargs`. |
| `reward_function_kwargs` | dict | `{}` | Kwargs do construtor da recompensa. | Passados sem alteração. |
| `central_agent` | bool | schema | Um único controlador para todos os edifícios. | `False` devolve um vetor por edifício. |
| `shared_observations` | lista | schema | Observações partilhadas no modo central. | Incluídas uma só vez nos vetores centrais. |
| `active_observations` | list/list[list] | schema | Ativa apenas estas observações. | Substituição global ou por edifício. |
| `inactive_observations` | list/list[list] | schema/building | Desativa observações. | Aplicado depois da seleção das ativas. |
| `active_actions` | list/list[list] | schema | Ativa apenas estas ações. | Substituição global ou por edifício. |
| `inactive_actions` | list/list[list] | schema/building | Desativa ações. | Aplicado depois da seleção das ativas. |
| `simulate_power_outage` | bool | schema/building | Ativa a simulação de cortes de energia. | Usa séries de dados ou um modelo estocástico. |
| `solar_generation` | bool/lista | `True` | `False` (ou um bool por edifício) retira a FV. | Só no construtor; não há chave no schema. |
| `random_seed` | int | schema | Semente aleatória. | Afeta as divisões e os atributos estocásticos. |
| `offline` | bool | `False` | Desativa os recursos de rede alternativos. | Requer datasets locais. |
| `interface` | `flat`/`entity` | schema/flat | Contrato de observações/ações. | Entity devolve tabelas e arestas. |
| `topology_mode` | `static`/`dynamic` | schema/static | Ativa os eventos de topologia dinâmica. | Dynamic requer `interface="entity"`. |
| `start_date` | data/string | schema/2024-01-01 | Data base dos timestamps de render/exportação. | Não altera a física. |
| `render_mode` | `none`/`during`/`end` | `none` | Política de exportação CSV. | `end` é preferível para o desempenho. |
| `render_session_name` | string | schema/None | Subpasta da sessão de exportação. | Tem de ser relativa. |
| `export_kpis_on_episode_end` | bool | flag de render | Exporta os KPIs no fim do episódio. | Pode ser ativado sem render completo. |

## `**kwargs` adicionais

| Parâmetro | Tipo | Predefinição | Finalidade |
|---|---:|---:|---|
| `render_directory` | caminho | `./render_logs` | Pasta base das exportações; os caminhos relativos são resolvidos a partir do diretório de trabalho. |
| `render_directory_name` | string | `render_logs` | Nome legado da pasta de exportação. |
| `render` | bool | derivado | Interruptor legado de render. |
| `debug_timing` | bool | schema/False | Registos de tempos de execução. |
| `check_observation_limits` | bool | schema/False | Valida as observações face aos limites estimados. |
| `physics_invariant_checks` | bool | schema/False | Executa verificações de invariantes físicos durante a execução. |
| `metrics_log_interval` | int | schema/0 | Cadência dos registos de métricas de execução. |

## Payloads de observações para a recompensa

`step()` constrói um payload de observações mais pequeno para a recompensa quando a função de recompensa declara de que nomes de observações precisa. As recompensas incluídas já o fazem. As recompensas personalizadas podem aderir com uma destas formas compatíveis:

```python
class MyReward:
    required_observation_names = ("net_electricity_consumption",)

    def calculate(self, observations):
        return [-sum(o["net_electricity_consumption"] for o in observations)]
```

O alias `required_observations` e o método `get_required_observation_names()` também são suportados. Se uma recompensa personalizada não declarar requisitos, o CityLearn recorre às observações completas `include_all`, por compatibilidade com versões anteriores.

## Macro-passos / repetição de ações

`step_many()` repete uma ação escolhida ao longo de vários passos internos do simulador e devolve uma única transição macro para os replay buffers de RL:

```python
obs, rewards, terminated, truncated, info = env.step_many(
    action,
    repeat_steps=20,
    stop_on_done=True,
    return_substeps=False,
)
```

O simulador continua a avançar cada passo interno à resolução de `seconds_per_time_step`. As restrições, o carregamento e as partidas dos VE, as baterias, os aparelhos diferíveis, as fases e a margem disponível (headroom), as recompensas, os KPIs e as séries temporais de render/exportação são atualizados exatamente como em chamadas repetidas a `step()`. A observação devolvida é apenas a observação final depois dos subpassos executados, e `rewards` é a soma das recompensas por agente.

`info["executed_steps"]` está sempre presente, para que o código de RL possa descontar corretamente as transições macro:

```python
gamma_macro = gamma ** info["executed_steps"]
```

Quando `return_substeps=True`, `info` inclui também `substep_rewards`, `substep_infos` e `substep_actions_applied` para depuração. Mantenha esta opção desativada em treinos longos.

## Leitura dos Últimos Valores por Passo

O `CityLearnEnv` guarda os rewards do episódio e as três séries agregadas do distrito em buffers `float64` pré-alocados. O acesso às propriedades de lista completa (`env.rewards`, `env.net_electricity_consumption`, `env.net_electricity_consumption_cost`, `env.net_electricity_consumption_emission`) materializa uma `list` Python na primeira leitura, acrescenta apenas os novos passos em `O(1)` por passo e desliga a cache antes de qualquer edição in-place, para que ciclos existentes com `[-1]` continuem lineares e isolados.

Leia o último valor com `[-1]`. Cada leitura demora tempo constante por passo.

```python
latest_reward_row = env.rewards[-1]
latest_net_kwh = env.net_electricity_consumption[-1]
latest_cost_eur = env.net_electricity_consumption_cost[-1]
latest_emission_kgco2 = env.net_electricity_consumption_emission[-1]
```

## CLI

A CLI precisa apenas do CityLearn para os comandos de listagem e para o agente
predefinido, o agente business-as-usual `BusinessAsUsualAgent`. Treinar ou
avaliar um agente Stable Baselines3 precisa também de `stable-baselines3>=2.4`,
e os agentes `SAC` e `MARLISA` incluídos precisam do extra `rl`. Todos os
comandos funcionam com Python 3.10 ou mais recente.

```bash
citylearn --version
citylearn list_datasets
citylearn list_default_time_series_variables
citylearn simulate data/datasets/my_dataset/schema.json train -e 3
citylearn simulate data/datasets/my_dataset/schema.json evaluate
```

O `simulate` escreve na pasta de saída um resumo do treino
(`<simulation_id>-train.json`), os ficheiros de avaliação e, com `--save_agent`,
o agente, e mostra o caminho de cada ficheiro que escreve. O `evaluate` e o
`train --evaluate` escrevem dois ficheiros de avaliação:

- `<simulation_id>-evaluation_v2.csv`: a tabela do `evaluate_v2()`, com as
  colunas `cost_function`, `value`, `name`, `level`, `unit` e `description`, uma
  linha por KPI e âmbito. Inclui as linhas do mercado comunitário quando o
  cenário tem mercado e as linhas `*_business_as_usual_*`. É a tabela que a
  [referência dos KPIs](kpis_reference.md) e o scorecard descrevem; leia-a com
  `pandas.read_csv`.
- `<simulation_id>-evaluation.json`: a janela e as horas da avaliação, as
  recompensas, as ações e as séries temporais, e os KPIs antigos do `evaluate()`
  em `evaluation`. O formato não muda, por isso os parsers existentes continuam
  a funcionar, mas compare controladores com o ficheiro do `evaluate_v2()`.

As linhas business-as-usual exigem uma segunda execução do `BusinessAsUsualAgent`
na janela de avaliação, tal como o `evaluate_v2()` em Python. A opção
`--no_business_as_usual` dispensa-a e escreve a tabela sem essas linhas.

### Agente Stable Baselines3

Um agente Stable Baselines3 precisa da sua política nos argumentos do agente e
do ambiente envolvido num único vetor plano de observações e de ações, o que
exige um agente central. Este comando treina o SAC durante cinco episódios
diários na primeira semana e avalia-o no primeiro episódio de treino:

```bash
citylearn simulate citylearn_challenge_2022_phase_all_plus_evs \
  -a stable_baselines3.SAC -ka '{"policy": "MlpPolicy"}' \
  -w citylearn.wrappers.NormalizedObservationWrapper citylearn.wrappers.StableBaselines3Wrapper \
  -ke '{"central_agent": true, "episode_time_steps": 24, "simulation_end_time_step": 167}' \
  -rs 0 -d outputs/sb3_sac -sid sb3_sac train -e 5 --evaluate --save_agent
```

Sem `"policy"`, a CLI gera um `TypeError` que indica o argumento a acrescentar.
Use `-te start end` para avaliar noutras janelas, por exemplo em dias não vistos.

Para avaliar ou continuar a treinar um modelo guardado, passe-o com `-fa` e
indique com `-a` o algoritmo que o guardou, por exemplo `-a stable_baselines3.SAC
-fa outputs/sb3_sac/sb3_sac-agent.zip`. Escreva noutra pasta com `-d`: o
`simulate` esvazia primeiro a pasta de saída, por isso recusa executar quando
essa pasta contém o modelo a carregar.

O que a integração com o Stable Baselines3 suporta:

- **Agente central, interface flat.** O `StableBaselines3Wrapper` transforma os
  vetores de observações e de ações do agente central num único `Box` cada. Com
  `central_agent=False` há um vetor por edifício e o wrapper lança um erro; para
  uma política por edifício, use o `RLlibMultiAgentEnv`.
- **Sem interface entity.** As observações entity são dicionários de tabelas
  cujo tamanho pode mudar, que as políticas do SB3 não aceitam. Os datasets
  `pt_rec_*`, trifásicos, de resposta à procura e de robustez usam por omissão a
  interface entity, por isso passe `"interface": "flat"` em `-ke` (ou
  `interface="flat"` em Python). A topologia dinâmica e a resposta à procura
  precisam da interface entity e não podem ser usadas com o SB3.
- **Limites das ações.** O espaço de ações mantém os limites de cada
  equipamento, por exemplo [-1, 1] para o armazenamento e os carregadores de VE
  e [0, 1] para os restantes, por isso o `check_env` avisa que não é simétrico. O
  SAC reescala as ações para os limites e o PPO corta-as, por isso ambos
  funcionam tal como estão.
- **Falhas de robustez.** Uma leitura de sensor em falta é substituída por
  `missing_replacement_value` (-9999 em `citylearn_challenge_2022_phase_all_robustness`),
  que, normalizada, fica muito fora de [0, 1]. O SB3 não verifica os limites das
  observações, mas a política recebe esse valor tal como está.

O `tests/test_stable_baselines3_integration.py` executa o `check_env`, algumas
atualizações do SAC e do PPO, o `predict` ao longo de um episódio com cada
observação dentro do seu espaço, o `evaluate_v2()` e a CLI a guardar e a carregar
um modelo.

### Janela de avaliação

`evaluate` executa um episódio das janelas de episódio do ambiente, ou das
janelas indicadas por `-te`. `train --evaluate` avalia na janela do primeiro
episódio de treino: com `-ke '{"episode_time_steps": 24}'` avalia 24 passos de
tempo, não o dataset inteiro. Sem `episode_time_steps`, o episódio, e portanto
a avaliação, cobre toda a janela de simulação.

### Informação da máquina

O resumo do treino só regista o nome da máquina e o nome do utilizador com
`--record_host`, para que os resultados possam ser partilhados sem eles.

| Opção | Exemplo | Finalidade |
|---|---|---|
| `schema` | nome do dataset ou caminho de `schema.json` | Dataset a executar. |
| `-a`, `--agent_name` | `citylearn.agents.baseline.BusinessAsUsualAgent` | Caminho da classe do agente. |
| `-ke`, `--env_kwargs` | `'{"interface":"entity"}'` | Kwargs JSON para `CityLearnEnv`. |
| `-ka`, `--agent_kwargs` | `'{"x":1}'` | Kwargs JSON para o agente. |
| `-w`, `--wrappers` | caminhos das classes dos wrappers | Wrappers Gymnasium. |
| `-tv`, `--time_series_variables` | `net_electricity_consumption` | Séries guardadas após a avaliação. |
| `-sid`, `--simulation_id` | `run_001` | ID usado nos nomes dos outputs. |
| `-fa`, `--agent_filepath` | `outputs/agent.pkl` | Caminho para carregar/guardar o agente. |
| `-d`, `--output_directory` | `outputs/run_001` | Pasta de saída. |
| `-te`, `--evaluation_episode_time_steps` | `0 2879` | Janela de avaliação. Pode ser repetida. |
| `-p`, `--append` | flag | Não substitui o output existente. |
| `-rs`, `--random_seed` | `42` | Semente. |
| `--offline` | flag | Exige ficheiros locais. |
| `--record_host` | flag | Regista o nome da máquina e do utilizador no resumo do treino. |
| `--no_business_as_usual` | flag | Escreve a tabela do `evaluate_v2()` sem as linhas business-as-usual. |
| `train -e` | `train -e 10` | Número de episódios de treino. |
| `train --save_agent` | flag | Guarda o agente no fim. |
| `train --evaluate` | flag | Avalia depois do treino, na janela do primeiro episódio de treino, salvo se for indicado `-te`. |
| `evaluate` | subcomando | Avaliação determinística. |

## Render e exportação

| `render_mode` | Custo de execução | Output | Caso de uso |
|---|---:|---|---|
| `none` | mínimo | Sem CSV de render | Treino. |
| `during` | alto | Escreve linhas em cada passo | Execuções curtas de depuração. |
| `end` | médio | Escreve o episódio completo no fim | Episódios longos com output CSV final. |

Defina `render_file_format="parquet"` para escrever as exportações de render, de KPIs e de séries temporais BAU como ficheiros parquet em partes, em vez de CSV. `render_chunk_size` controla o número de linhas por parte parquet; a predefinição é `50000` para parquet e `100000` para CSV.

As exportações de KPIs e BAU são por episódio, pelo que os ciclos de treino podem manter a exportação desativada e ativá-la apenas no último episódio. Se forem precisos os outputs normais de séries temporais nesse episódio final, crie o ambiente com `render_mode="end"` e alterne `render_enabled`; para um output só de KPIs, deixe o render desativado e chame `export_final_kpis()` manualmente depois do episódio final.

```python
for episode in range(episodes):
    last_episode = episode == episodes - 1
    env.render_enabled = last_episode
    env.export_kpis_on_episode_end = last_episode
    observations, info = env.reset()
    # run episode...
```

`export_final_kpis()` controla o custo BAU em separado:

| Chamada | Output | Custo do sidecar BAU |
|---|---|---:|
| `env.export_final_kpis(include_business_as_usual=False)` | Ficheiro de KPIs e metadados de auditoria | não |
| `env.export_final_kpis(include_business_as_usual=True, export_business_as_usual_timeseries=False)` | Ficheiro de KPIs com linhas BAU e metadados de auditoria | sim |
| `env.export_final_kpis(include_business_as_usual=True, export_business_as_usual_timeseries=True)` | Ficheiro de KPIs com linhas BAU e ficheiro de séries temporais BAU | sim |

As séries temporais normais do episódio são controladas por `render_mode`/`render_enabled`, não por `export_final_kpis()`.

Para escolhas exatas no episódio final, mantenha `export_kpis_on_episode_end=False` e chame `export_final_kpis()` depois de o episódio terminar.

## Teste rápido de um dataset grande

Para datasets grandes de 15 s, execute sempre primeiro uma janela curta:

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

## Validação a partir de um checkout do código-fonte

A suite de testes e os scripts de auditoria estão no repositório, não no pacote
que `pip install citylearn` instala. Execute-os a partir de um clone, com os
requisitos de teste instalados (consulte o
[guia de desenvolvimento](developer_guide.md) e o
[guia de validação](validation.md)):

```bash
python -m pytest -q
python scripts/audit/audit_entity_contract.py --strict
python scripts/audit/audit_physics.py
python -m ruff check citylearn tests scripts/manual scripts/ci
```

As exportações só de KPIs incluem um manifesto e sidecars JSON de auditoria do
serviço. Não ativam o output de séries temporais do episódio; a CityLearn UI
pode carregar a pasta como antes. O manifesto identifica os ficheiros de entrada
pelo seu caminho abaixo da raiz do dataset; a secção
[Evidência portátil de experiências](developer_guide.md#evidência-portátil-de-experiências)
indica que grafias de uma referência a um ficheiro registam a mesma evidência.
