# Referência do schema

Esta página documenta todas as chaves de `schema.json` que o CityLearn lê: onde ficam, o que
aceitam, a predefinição e a unidade, o que fazem, de que dependem, que versão as altera e que
argumento de `CityLearnEnv` se sobrepõe a elas. Comece por [Encontrar o que precisa](#encontrar-o-que-precisa)
quando sabe o que quer modelar, ou por [Organização de um schema](#organização-de-um-schema)
quando escreve um schema de raiz.

Um schema completo que define todas as opções é distribuído em
[`examples/schema_full_reference.json`](https://github.com/citylearn-project/CityLearn/blob/master/examples/schema_full_reference.json),
e o [guia do schema de referência completo](schema_full_reference.md) explica-o chave a chave.

Versão em inglês: [../schema_reference.md](../schema_reference.md).

## Encontrar o que precisa

| Quero | Defina | Secção |
|---|---|---|
| Simular um período mais curto | `simulation_start_time_step`, `simulation_end_time_step` | [Janela temporal](#janela-temporal-e-passo-de-controlo) |
| Treinar em muitos episódios curtos | `episode_time_steps`, `rolling_episode_split`, `random_episode_split` | [Episódios](#episódios) |
| Usar dados de 15 minutos ou de 15 segundos | `seconds_per_time_step` igual ao passo dos dados | [Janela temporal](#janela-temporal-e-passo-de-controlo) |
| Reproduzir um resultado do CityLearn 3.6.0 | `physics_version: 1`, `baseline_version: 1`, `random_stream_version: "v1"`, `episode_split_boundary: "disjoint"`, `time_step_ratio_mode: "compress"` | [Versões](#versões) |
| Repetir execuções com os mesmos resultados | `random_seed` | [Sementes e fluxos aleatórios](#sementes-e-fluxos-aleatórios) |
| Controlar todos os edifícios com um só agente | `central_agent: true`, `shared_in_central_agent` | [Observações](#observações) |
| Escolher o que o agente vê | `observations.<name>.active`, `buildings.<b>.inactive_observations` | [Observações e ações](#observações-e-ações) |
| Escolher o que o agente controla | `actions.<name>.active`, `buildings.<b>.inactive_actions` | [Ações](#ações) |
| Usar observações em grafo ou em tabelas | `interface: "entity"`, `observation_bundles` | [Interface entity](#interface-entity-bundles-de-observação-e-previsões-derivadas) |
| Dar ao agente previsões causais | `derived_forecasts.load_pv_method: "daily_persistence"`, `price_source` | [Previsões derivadas](#interface-entity-bundles-de-observação-e-previsões-derivadas) |
| Mudar a recompensa | `reward_function.type`, `reward_function.attributes` | [Função de recompensa](#função-de-recompensa) |
| Acrescentar uma bateria | `buildings.<b>.electrical_storage` | [Bateria](#bateria) |
| Acrescentar FV a partir de energia medida | `pv.attributes.generation_mode: "absolute"` | [FV](#fv) |
| Acrescentar uma bomba de calor e um depósito de água quente | `cooling_device`, `heating_device`, `dhw_device`, `*_storage` | [Dispositivos AVAC](#dispositivos-avac), [Armazenamento térmico](#armazenamento-térmico) |
| Dimensionar equipamento a partir dos dados | `autosize: true`, `autosize_attributes` | [Dimensionamento automático](#dimensionamento-automático) |
| Acrescentar carregadores e VE | `buildings.<b>.chargers`, `electric_vehicles_def` | [VE e carregadores](#veículos-elétricos-e-carregadores) |
| Permitir vehicle-to-grid | `chargers.<id>.attributes.max_discharging_power` acima de 0 | [Atributos do carregador](#atributos-do-carregador) |
| Limitar a ligação à rede ou uma fase | `buildings.<b>.electrical_service.limits` | [Serviço elétrico](#serviço-elétrico) |
| Limitar a importação ao longo do tempo | `electrical_service.available_grid_power` | [Potência de rede disponível](#potência-de-rede-disponível) |
| Acrescentar um aparelho deslocável | `buildings.<b>.deferrable_appliances` | [Aparelhos diferíveis](#aparelhos-diferíveis) |
| Simular falhas da rede | `buildings.<b>.power_outage` | [Falhas de energia](#falhas-de-energia) |
| Alimentar uma casa com o seu VE durante uma falha | `power_outage.vehicle_to_building: true` e um carregador V2G | [Falhas de energia](#falhas-de-energia) |
| Partilhar energia dentro da comunidade | `community_market.enabled: true` | [Mercado comunitário](#mercado-comunitário-e-liquidação) |
| Pagar as exportações | `community_market.settlement_version: 2`, `grid_export_price` | [Mercado comunitário](#mercado-comunitário-e-liquidação) |
| Usar tarifas por membro | `community_market.tariff_files` | [Mercado comunitário](#mercado-comunitário-e-liquidação) |
| Responder a pedidos de flexibilidade do DSO/TSO | `demand_response` | [Resposta à procura](#resposta-à-procura) |
| Testar falhas de sensores, atuadores ou ativos | `robustness` | [Robustez](#robustez) |
| Acrescentar ou retirar membros e ativos durante um episódio | `topology_mode: "dynamic"`, `topology_events` | [Topologia dinâmica](#topologia-dinâmica) |
| Correr várias comunidades em conjunto | `MultiCommunityEnv` (não é uma chave do schema) | [Várias comunidades](#várias-comunidades) |
| Escolher o alvo de carregamento dos VE no BAU | `business_as_usual_ev_charge_target` | [Avaliação dos VE](#definições-da-avaliação-dos-ve) |
| Exportar séries temporais | `render_mode`, `render_file_format` | [Saídas e exportações](#saídas-render-e-exportações) |

## Organização de um schema

### Níveis

```text
schema.json
├── raiz: localização dos dados, sementes, janela temporal, episódios, versões, interface, recompensa, saídas
├── observations: {nome: {active, shared_in_central_agent}}        (catálogo para todos os edifícios)
├── actions: {nome: {active}}                                      (catálogo para todos os edifícios)
├── observation_bundles, derived_forecasts                         (só na interface entity)
├── buildings
│   └── <edifício>: ficheiros de dados, type, inactive_observations/actions, equity_group
│       ├── cooling_device, heating_device, dhw_device              (dispositivos AVAC)
│       ├── cooling_storage, heating_storage, dhw_storage           (armazenamento térmico)
│       ├── electrical_storage, pv                                  (bateria, FV)
│       ├── chargers: {<charger_id>: type, charger_simulation, attributes, ...}
│       ├── deferrable_appliances, escalators
│       ├── electrical_service | charging_constraints              (limites da ligação à rede)
│       └── power_outage, dynamics, occupant, set_point_*
├── electric_vehicles_def: {<ev_id>: type, include, battery}
├── community_market, demand_response, robustness                  (serviços da comunidade)
└── topology_mode, topology_events                                 (membros e ativos que mudam)
```

### Onde fica cada definição

| Nível | Coloque aqui | Exemplos |
|---|---|---|
| Raiz | Tudo o que é igual para toda a simulação: relógio, episódios, versões, sementes, interface, recompensa, exportações, tolerâncias de avaliação. | `seconds_per_time_step`, `physics_version`, `reward_function` |
| `observations`, `actions` | O catálogo: que nomes existem e quais estão ligados para todos os edifícios. Desligue um nome num só edifício com `inactive_observations` / `inactive_actions` ao nível do edifício. | `"electrical_storage_soc": {"active": true}` |
| `buildings.<b>` | Um membro da comunidade: os seus ficheiros de dados e tudo o que lhe pertence. | `energy_simulation`, `electrical_service` |
| `buildings.<b>.<dispositivo>` | Um dispositivo: a classe, os atributos do construtor e o dimensionamento automático. | `electrical_storage.attributes.capacity` |
| `buildings.<b>.chargers.<id>` | Um carregador: o ficheiro de horário e os limites de potência. | `max_charging_power` |
| `electric_vehicles_def.<ev>` | Um veículo, partilhado por todos os carregadores. Os ficheiros dos carregadores indicam o veículo ligado. | `battery.attributes.capacity` |
| `community_market`, `demand_response`, `robustness` | Serviços que atuam sobre toda a comunidade. | `settlement_version` |
| `topology_events` | Mudanças durante um episódio. | `add_member` |

Cada chave é lida num só nível. Uma definição de edifício colocada na raiz (por exemplo um `power_outage` ou um
`noise_std` na raiz) não é lida, e uma definição da raiz repetida dentro de um edifício também não.

### Carregar um schema

`CityLearnEnv(schema)` aceita três formas, que tratam `root_directory` de maneira diferente.

| Forma | Exemplo | `root_directory` |
|---|---|---|
| Caminho para um ficheiro JSON ou para uma pasta com `schema.json` | `CityLearnEnv("data/my_dataset/schema.json")` | Opcional. `null` ou ausente: a pasta do schema. Absoluto: usado tal como está. Relativo: resolvido a partir da pasta do schema e, depois, das pastas acima dela. |
| Nome de um dataset público | `CityLearnEnv("citylearn_challenge_2022_phase_all_plus_evs")` | Substituído pela pasta que `DataSet().get_dataset(name)` devolve, seja qual for o valor do schema: uma cópia local completa, em cache sob o digest dos seus ficheiros, ou então uma descarga da versão publicada. |
| `dict` de Python | `CityLearnEnv(schema_dict)` | **Chave obrigatória.** `null` significa a pasta de trabalho atual, pelo que os nomes de ficheiro relativos são lidos a partir daí. |

Todos os nomes de ficheiro do schema (`energy_simulation`, `charger_simulation`, `requests_file`, ...) são resolvidos a
partir de `root_directory`, salvo se forem absolutos. O argumento `root_directory` de `CityLearnEnv` substitui o valor
do schema para todos os ficheiros exceto `community_market.tariff_files`, que são sempre resolvidos a partir do
`root_directory` do próprio schema.

### Chaves do schema e argumentos do construtor

Um argumento de `CityLearnEnv` que não seja `None` substitui o valor do schema com o mesmo nome, e o valor do schema
substitui a predefinição. [Argumentos do construtor](#argumentos-do-construtor-que-se-sobrepõem-a-chaves-do-schema)
lista todos os pares. Exceções:

- `render_mode` e `render`: um valor no schema prevalece sobre o argumento.
- `topology_mode="static"` não se pode sobrepor a um schema que declara topologia dinâmica ou que contém `topology_events`; lança `ValueError`.
- Um `start_date` indicado no schema é ignorado quando o dataset tem calendário (`time_axis.calendar_file`); o argumento não é.
- O construtor altera uma cópia do schema: `env.schema` mantém os valores do ficheiro, não os valores efetivos.
  Leia os valores efetivos no ambiente (`env.physics_version`, `env.seconds_per_time_step`, ...) ou em `env.get_metadata()`.

Um argumento do construtor desconhecido lança `TypeError` com o nome válido mais próximo. Uma chave desconhecida na
raiz do schema é ignorada sem aviso.

### Validação das chaves

| Secção | Chave desconhecida | Valor inválido |
|---|---|---|
| Raiz | ignorada | a maioria das chaves lança `ValueError` na construção |
| `community_market`, `community_market.kpis` | `ValueError` com o nome válido mais próximo | `ValueError` |
| Chaves de `chargers.<id>` | `UserWarning` com a chave mais próxima, e depois ignorada | |
| `chargers.<id>.attributes` | `ValueError` com o nome válido mais próximo | |
| `attributes` dos dispositivos (bateria, FV, bomba de calor, depósito) | `TypeError` | `AssertionError` ou `ValueError` |
| `electric_vehicles_def.<ev>.battery.attributes` | ignorada | |
| `observations` | `KeyError` na construção, mesmo quando inativa (os nomes de modelo por dispositivo não são verificados) | `ValueError` para um `active` que não seja booleano |
| `actions` | um nome ativo desconhecido lança erro na construção | `ValueError` para um `active` que não seja booleano |
| `electrical_service.available_grid_power` | `ValueError` | `ValueError` |
| `demand_response`, `robustness`, `derived_forecasts`, `observation_bundles`, `topology_events` | ignorada | `ValueError` para a maioria dos valores |
| Entradas de `MultiCommunityEnv` | `ValueError` | `ValueError` |

### Regras gerais

| Regra | Contrato |
|---|---|
| Caminhos | Os caminhos relativos são resolvidos a partir de `root_directory`; os caminhos absolutos são permitidos (os ficheiros de tarifas têm de estar dentro do dataset). |
| Ficheiros tabulares | CSV e Parquet (`.parquet`, `.pq`, `.parq`) são intercambiáveis quando as colunas e as unidades são as mesmas. Os ficheiros de tarifas da comunidade só podem ser CSV. |
| Energia | As séries de energia do dataset estão em `kWh` por passo do dataset. |
| Potência e limites | As potências nominais e os limites estão em `kW`. |
| Preços | Os preços são por `kWh`, na moeda do dataset (EUR nos KPIs do mercado). |
| Emissões | A intensidade carbónica está em `kgCO2/kWh`. |
| Passos de tempo | As janelas, os prazos e os instantes dos eventos são índices globais de linha dos dados (a linha 0 é a primeira linha dos ficheiros), inclusivos nas duas pontas. |
| `null` | Nos `attributes` de dispositivos e carregadores, `null` significa "usar a predefinição" (incluindo as predefinições sorteadas). |
| Booleanos | Escreva `true` / `false` em JSON. A maioria das chaves aceita também `0`/`1` e as strings `"true"`/`"false"`, mas algumas tratam qualquer string não vazia como verdadeira; consulte [Erros comuns](#erros-comuns-e-o-que-evitar). |
| Intervalos | Os atributos de dispositivos indicados como "sorteados" aceitam um número ou `null`. Um intervalo `[mínimo, máximo]` lança `TypeError`. |
| Máquinas de lavar antigas | `washing_machines` não é lido (um schema com esta chave carrega sem os aparelhos). Use `deferrable_appliances`. |

## Nível da raiz

### Chaves obrigatórias

| Chave | Tipo | Notas |
|---|---|---|
| `root_directory` | string ou `null` | Obrigatória num schema `dict`; consulte [Carregar um schema](#carregar-um-schema). |
| `central_agent` | bool | Salvo se o argumento `central_agent` for indicado. |
| `seconds_per_time_step` | número | Salvo se o argumento `seconds_per_time_step` for indicado. |
| `simulation_start_time_step`, `simulation_end_time_step` | int | Salvo se os argumentos forem indicados. |
| `observations`, `actions` | objeto | Podem ser objetos vazios. |
| `reward_function` | objeto | Obrigatória mesmo quando é indicado um argumento `reward_function`. |
| `buildings` | objeto | Pelo menos um edifício. |

Uma chave obrigatória em falta lança `KeyError`.

### Janela temporal e passo de controlo

| Chave | Tipo | Predefinição | Unidade / valores | Efeito | Argumento | Desde |
|---|---|---|---|---|---|---|
| `seconds_per_time_step` | número | obrigatória | s, pelo menos 1 | Duração de um passo de controlo. Tem de ser igual ao passo do dataset, salvo se `time_step_ratio_mode` for `compress`. | `seconds_per_time_step` | original |
| `simulation_start_time_step` | int | obrigatória | linha dos dados | Primeira linha lida de cada ficheiro de séries temporais. | `simulation_start_time_step` | original |
| `simulation_end_time_step` | int | obrigatória | linha dos dados | Última linha lida, inclusive. A janela tem `end - start + 1` linhas; as linhas fora dela não são carregadas. | `simulation_end_time_step` | original |
| `time_step_ratio_mode` | string | `reject` | `reject`, `compress` | O que fazer quando `seconds_per_time_step` difere do passo do dataset. `reject` lança `ValueError`. `compress` mantém o comportamento da 3.6.0: uma linha de dados por passo de controlo, energias escaladas pela razão, e é impresso um aviso. | `time_step_ratio_mode` | depois da 3.6.0 |

O passo do dataset é lido, por esta ordem, de `dataset_seconds_per_time_step`, do ficheiro de calendário, ou das
colunas `hour`, `minutes` e `seconds` de `energy_simulation` (pelo menos 90 % dos intervalos têm de concordar).
`time_step_ratio` é só um argumento do construtor: se for indicado, tem de coincidir com a razão inferida.

Para controlo de 15 minutos sobre dados de 15 minutos, defina `"seconds_per_time_step": 900`. Para simular uma semana de
um dataset horário, defina `"simulation_start_time_step": 0` e `"simulation_end_time_step": 168` (169 linhas, 168
passos de controlo).

### Episódios

| Chave | Tipo | Predefinição | Valores | Efeito | Argumento | Desde |
|---|---|---|---|---|---|---|
| `episode_time_steps` | int, lista de `[start, end]`, `null` | `null` | | `null`: um episódio que cobre toda a janela. Um int `N`: episódios de `N` linhas (`N - 1` passos de controlo). Uma lista: episódios explícitos, com as duas pontas inclusivas. | `episode_time_steps` | original |
| `rolling_episode_split` | bool | `false` | | Com um `episode_time_steps` inteiro, qualquer linha entre o início da janela e `end + 1 - N` pode iniciar um episódio (janelas sobrepostas). Ignorada para uma lista. | `rolling_episode_split` | original |
| `random_episode_split` | bool | `false` | | Escolhe o episódio ao acaso em cada reset (com reposição), com semente em `random_seed` e no número do episódio. Sem ela, os episódios são usados por ordem e em ciclo. Aplica-se a episódios inteiros e a listas. | `random_episode_split` | original |
| `episode_split_boundary` | string | `shared` | `shared`, `disjoint` | Para episódios inteiros sem `rolling`. `shared`: a última linha de um episódio é a primeira do seguinte, pelo que todos os intervalos são simulados (passo `N - 1`). `disjoint`: as divisões da 3.6.0 (passo `N`), que saltam o intervalo entre dois episódios. | `episode_split_boundary` | depois da 3.6.0 |
| `ev_soc_carryover` | bool | `false` | | Começa cada VE de um episódio que continua o anterior no tempo (na última linha dele com `shared`, na linha seguinte com `disjoint`) com o SOC que tinha no fim desse episódio, em vez do SOC do calendário. As divisões sequenciais e as listas explícitas transportam o SOC; as aleatórias e as `rolling` nunca o fazem. Só o SOC dos VE é transportado. Consulte o [guia de migração](migration.md#soc-dos-ve-transportado-entre-divisões-de-episódios). | `ev_soc_carryover` | depois da 3.6.0 |

Regras:

- Um episódio de `N` linhas tem `N - 1` passos de controlo: a última linha é só a observação terminal.
- Um int `N` tem de estar entre 1 e o comprimento da janela; uma janela final mais curta do que `N` é descartada. Com `shared`, `N` tem de ser pelo menos 2 quando há mais do que um episódio.
- Cada `[start, end]` tem de cumprir `0 <= start <= end` e ficar dentro da janela de simulação; caso contrário, `ValueError`. Escreva uma lista de listas em JSON: um tuplo de pares em Python lança `TypeError`.
- Se um argumento `simulation_*_time_step` estreitar a janela, a lista de episódios do schema é cortada por ela e os episódios que ficam vazios são descartados.
- `env.reset(options={"episode_index": k})` escolhe diretamente o episódio `k`.

Receitas:

```json
{"episode_time_steps": 169, "rolling_episode_split": false, "random_episode_split": true}
```

dá episódios de uma semana (168 passos) que partilham as linhas de fronteira, sorteados em cada reset.

```json
{"episode_time_steps": [[0, 2159], [2160, 4319], [4320, 6479]]}
```

dá três episódios fixos usados à vez.

### Calendário e relógio do dataset

Estas chaves descrevem o relógio do dataset. Mudam a forma como os instantes e o passo do dataset são lidos, não a física.

| Chave | Tipo | Predefinição | Efeito | Desde |
|---|---|---|---|---|
| `time_axis.calendar_file` | caminho | nenhuma | Calendário com as colunas `time_step` (exatamente `0..n-1`) e `timestamp_utc` (legível, estritamente crescente, regular, com pelo menos 2 linhas) e, opcionalmente, `timestamp_local` (os mesmos instantes). O seu espaçamento passa a ser o passo do dataset de todos os edifícios, e os instantes exportados vêm dele, salvo se `start_date` for passado a `CityLearnEnv`. Lido como Parquet quando o nome termina em `.parquet` ou `.pq` (minúsculas); caso contrário, como CSV. | 3.1.0 |
| `timezone` | string | nenhuma | Nome IANA, por exemplo `Europe/Lisbon`. Converte os instantes do calendário a partir de UTC; um nome desconhecido lança erro no carregamento. Sem calendário, só é registado. | 3.1.0 |
| `dataset_seconds_per_time_step` | número | inferida | Passo declarado do dataset em segundos, finito e positivo. Tem de concordar com o calendário quando ele existe. | 3.1.0 |
| `dataset_contract_version` | string | nenhuma | Um valor começado por `portugal-native` faz de `shared/calendar.parquet` o calendário quando `time_axis` está ausente e esse ficheiro existe. Caso contrário, é um metadado. | 3.1.0 |
| `terminal_observation_padding` | bool | `false` | Permite que cada ficheiro de séries temporais termine exatamente uma linha antes da janela: a última linha é repetida apenas como observação terminal (os campos de calendário avançam um passo e um VE ligado que parte aparece como já saído). Nunca é simulada. Um ficheiro com mais do que uma linha em falta continua a lançar `ValueError`. | 3.0.0 |
| `start_date` | `YYYY-MM-DD` | `2024-01-01` | Data da linha global 0 nos instantes de render e de exportação quando não há calendário. Não altera a simulação. | 2.5.0 |

### Versões

Três chaves de versão escolhem comportamentos que mudaram depois do CityLearn 3.6.0. Cada uma aceita um int, um float
inteiro ou uma string de dígitos (`2`, `2.0`, `"2"`); um booleano lança `ValueError`. O argumento do construtor com o
mesmo nome prevalece. [O que cada versão altera](#o-que-cada-versão-altera) lista todas as diferenças.

| Chave | Valores | Predefinição | Escolhe | Desde |
|---|---|---|---|---|
| `physics_version` | `1`, `2` | `2` | Física dos dispositivos e do despacho. `1` reproduz o CityLearn 3.6.0. | depois da 3.6.0 |
| `baseline_version` | `1`, `2` | `2` | Definição da baseline dos KPIs (séries `*_without_storage`) e do AVAC do BAU. `1` como na 3.6.0: não volta a somar nada, e o BAU envia zero às ações de AVAC. `2` volta a somar o carregamento dos VE do BAU e, nos datasets com ações de AVAC, o BAU fornece a procura de aquecimento e de arrefecimento do dataset. Qualquer outro valor lança `ValueError`. `env.baseline_version = v` também funciona depois da construção. | depois da 3.6.0 |
| `random_stream_version` | `v1`, `v2` (também `1`, `2`, `"V2"`) | `v2` | Como os números aleatórios são tirados de `random_seed`. `v1` reproduz a 3.6.0. | depois da 3.6.0 |

O mercado comunitário tem a sua própria `settlement_version`; consulte [Mercado comunitário](#mercado-comunitário-e-liquidação).
Para reproduzir um resultado da 3.6.0, defina `physics_version: 1`, `baseline_version: 1`, `random_stream_version: "v1"`,
`episode_split_boundary: "disjoint"` e, para dados cujo passo difere do passo de controlo,
`time_step_ratio_mode: "compress"`. Consulte o [guia de migração](migration.md#versão-da-física).

### Sementes e fluxos aleatórios

| Chave | Tipo | Predefinição | Efeito | Argumento |
|---|---|---|---|---|
| `random_seed` | int | uma semente aleatória nova em cada construção | Semente dos parâmetros sorteados dos dispositivos, do SOC inicial dos VE, da deriva dos VE ausentes, dos sorteios dos ocupantes, das falhas estocásticas, do ruído dos dados, da escolha aleatória de episódios e do ruído de robustez. Defina-a para execuções repetíveis. `env.reset(seed=s)` substitui-a. | `random_seed` |
| `random_stream_version` | string | `v2` | `v2`: um fluxo independente por finalidade, objeto e episódio. `v1`: o esquema da 3.6.0 (um gerador por sorteio, partilhado entre edifícios). A escolha aleatória de episódios, o ruído dos dados e o SOC inicial dos VE não dependem dela. | `random_stream_version` |

### Função de recompensa

```json
{"reward_function": {"type": "citylearn.reward_function.ComfortReward", "attributes": {"band": 2.0, "version": 2}}}
```

| Chave | Tipo | Predefinição | Efeito |
|---|---|---|---|
| `reward_function.type` | caminho de importação, ou objeto por edifício | obrigatória | Classe da recompensa. Indicar a secção inteira como string lança `TypeError`. |
| `reward_function.attributes` | objeto, `null`, ou objeto por edifício | `{}` | Argumentos nomeados do construtor. |

Forma por edifício: indique `type` (e, opcionalmente, `attributes`) como objetos com o nome de cada edifício como chave,
mais `"default"` para os restantes. Sem `"default"`, a primeira entrada é usada para os edifícios não listados. Nesta
forma, `attributes` tem de ser um objeto (não `null`).

```json
{"reward_function": {
  "type": {"default": "citylearn.reward_function.RewardFunction", "Building_3": "citylearn.reward_function.ComfortReward"},
  "attributes": {"default": {}, "Building_3": {"band": 1.5}}
}}
```

O argumento `reward_function` (instância, classe ou caminho de importação) substitui a recompensa do schema.
`reward_function_kwargs` substitui os atributos do schema; não é usado na forma por edifício. Com um agente central, as
recompensas dos edifícios são somadas.

| Classe | Atributos e predefinições | Recompensa |
|---|---|---|
| `citylearn.reward_function.RewardFunction` | `exponent` (1,0), `charging_constraint_penalty_coefficient` (1,0) | `-(max(consumo líquido, 0) ** exponent)` por edifício. |
| `citylearn.reward_function.MARL` | nenhum | Penalização do consumo do edifício ligada ao consumo líquido do distrito. |
| `citylearn.reward_function.IndependentSACReward` | nenhum | `min(-consumo líquido, 0)`. |
| `citylearn.reward_function.SolarPenaltyReward` | nenhum | Penaliza a importação, mais quando o armazenamento não absorve a FV. |
| `citylearn.reward_function.ComfortReward` | `band` (`null`: a coluna `comfort_band`), `lower_exponent` (2,0), `higher_exponent` (2,0), `version` (2) | Penaliza a distância para fora da banda de conforto. `version: 1` (obsoleta) segue o sinal da procura em vez do modo AVAC. |
| `citylearn.reward_function.SolarPenaltyAndComfortReward` | `band`, `lower_exponent` (2,0), `higher_exponent` (2,0), `coefficients` (`[1.0, 1.0]`), `version` (2) | Soma ponderada das duas recompensas anteriores. |
| `citylearn.reward_function.Electric_Vehicles_Reward_Function` | `weights` (objeto com as sete chaves `no_car_charging`, `battery_limits`, `soc_impossible`, `soc_under`, `close_soc`, `self_ev_consumption`, `extra_self_production`), `version` (2) | Recompensa com VE. Um objeto `weights` parcial substitui as predefinições, por isso indique as sete chaves. |
| `citylearn.reward_function.OutageUnservedEnergyReward` | `coefficient` (1,0), `base_reward` (caminho de importação ou `{type, attributes}`, predefinição `RewardFunction`), outras chaves passadas à recompensa base | Recompensa base menos `coefficient` vezes a energia não servida durante falhas. |

Consulte a [visão geral das funções de recompensa](https://www.citylearn.net/overview/reward_function.html) para as fórmulas.

### Agente

| Chave | Tipo | Predefinição | Efeito |
|---|---|---|---|
| `agent.type` | caminho de importação | nenhuma | Classe do agente carregada por `env.load_agent()` chamado sem o argumento `agent` e por `Simulator(agent_name=None)`. O comando `citylearn simulate` não a lê: usa a opção `-a` (predefinição `citylearn.agents.baseline.BusinessAsUsualAgent`). |
| `agent.attributes` | objeto | `{}` | Argumentos nomeados do agente; os argumentos de `load_agent()` prevalecem. |

### Interface e modo de topologia

| Chave | Valores | Predefinição | Efeito | Argumento | Desde |
|---|---|---|---|---|---|
| `interface` | `flat`, `entity` | `flat` | `flat`: um vetor por edifício (ou um para o agente central). `entity`: tabelas e arestas; obrigatória para resposta à procura, topologia dinâmica e `hidden_faults`. As escadas rolantes só funcionam em flat. Consulte [Interfaces flat e entity](interfaces_flat_entity.md). | `interface` | 3.0.0 |
| `topology_mode` | `static`, `dynamic` | `static` | `dynamic` aplica `topology_events` e precisa de `interface: "entity"`. | `topology_mode` | 3.0.0 |

### Saídas, render e exportações

| Chave | Tipo | Predefinição | Efeito | Argumento |
|---|---|---|---|---|
| `render_mode` | `none`, `during`, `end` | `none` | `during` escreve as séries temporais em cada passo; `end` escreve-as no fim do episódio. **O valor do schema prevalece sobre o argumento.** | `render_mode` |
| `render` | bool | segue `render_mode` | Interruptor antigo do render. **O valor do schema prevalece sobre o argumento.** | `render` |
| `render_file_format` | `csv`, `parquet` | `csv` | Formato das exportações de render, KPIs e séries temporais BAU. `parquet` precisa de `pyarrow`. | `render_file_format` |
| `render_chunk_size` | int | 100000 (CSV), 50000 (Parquet) | Linhas acumuladas antes de cada escrita; valores abaixo de 1 passam a 1. | `render_chunk_size` |
| `render_session_name` | string | data e hora | Subpasta dentro da pasta de render. Tem de ser relativa, sem `..`. | `render_session_name` |
| `export_kpis_on_episode_end` | bool | segue o render | Escreve `exported_kpis.csv` no fim do episódio. | `export_kpis_on_episode_end` |
| `export_only_final_episode` | bool | `true` | Quando uma execução planeia os episódios (CLI, `agent.learn`), exporta apenas o último. | `export_only_final_episode` |

`render_directory` e `render_directory_name` são apenas argumentos do construtor.

### Diagnóstico e contabilização

| Chave | Tipo | Predefinição | Efeito | Desde |
|---|---|---|---|---|
| `debug_timing` | bool | `false` | Acrescenta campos de tempos (`step_total_time`, ...) ao dicionário `info` de `step()`. Não escreve registos. | 3.0.0 |
| `check_observation_limits` | bool | `false` | Interface flat: regista, ao nível DEBUG, as observações fora do espaço de observação. Nunca lança erro e torna `step_many` mais lento. | 3.0.0 |
| `physics_invariant_checks` | bool | `false` | Verifica os balanços de energia em cada passo e lança `PhysicsInvariantError` numa violação. Mais lento. | 3.0.0 |
| `energy_provenance` | bool | `true` | Mantém o registo por passo da proveniência da energia e os seus KPIs. `false` é mais rápido e não altera nenhum valor simulado; as auditorias de proveniência passam a lançar erro. | 3.2.0 |
| `metrics_log_interval` | int | `0` | A cada N passos, e no fim, regista uma linha INFO com energia, custo e emissões. `0` desliga-o. | 3.0.0 |

As cinco têm um argumento do construtor com o mesmo nome.

### Definições da avaliação dos VE

| Chave | Tipo | Predefinição | Efeito | Argumento | Desde |
|---|---|---|---|---|---|
| `ev_departure_within_tolerance` | número, fração de SOC | `0.05` | Uma partida está dentro da tolerância quando `abs(SOC - alvo) <= tolerância`. Finito e pelo menos 0. | sim | 2.6.0 |
| `ev_departure_service_tolerance` | número, fração de SOC | `0.05` | Uma partida tem serviço aceitável quando `SOC + tolerância >= alvo`. Finito e pelo menos 0. Também limita a margem fixa (`EV_SERVICE_SOC_TOLERANCE`, 0,005) dos KPIs de alvo cumprido e de viabilidade do alvo, que contam uma partida como cumprida quando `SOC >= alvo - min(0,005, tolerância)`; consulte [Partidas](kpis_reference.md#partidas). | sim | 3.0.0 |
| `business_as_usual_ev_charge_target` | `full`, `requested` | `full` | Política de carregamento do BAU nativo usado por `evaluate_v2()`: `full` carrega até 100 % à chegada, `requested` para no SOC pedido para a partida. Distingue maiúsculas. A baseline dos KPIs da `baseline_version` 2 usa sempre `full`. Consulte [Referências](baselines.md#escolher-o-alvo-de-carregamento-do-bau). | sim | 3.4.0 |

### Chaves de metadados

Estas chaves não são lidas pelo simulador. Documentam a origem de um dataset:
`dataset_id`, `dataset_family`, `experimental_design`, `native_compatibility`, `_derived_from`, `_derivation`.
As chaves da raiz que não são definições de observações, recompensa ou saídas e que não começam por `_` entram no
`physical_configuration_sha256` das comparações exportadas, pelo que duas execuções cujos schemas diferem só nos
metadados podem ser dadas como incompatíveis. Comece por `_` o nome de uma chave de comentário ou de nota para a manter
fora desse hash.

### Argumentos do construtor que se sobrepõem a chaves do schema

| Argumento | Chave do schema | Notas |
|---|---|---|
| `root_directory` | `root_directory` | Não é usado para `community_market.tariff_files`. |
| `buildings` | `buildings.<b>.include` | Nomes, índices ou objetos `Building`; substitui a seleção por `include`. |
| `simulation_start_time_step`, `simulation_end_time_step`, `episode_time_steps`, `rolling_episode_split`, `random_episode_split`, `episode_split_boundary`, `ev_soc_carryover`, `seconds_per_time_step`, `time_step_ratio_mode` | a mesma | |
| `central_agent`, `interface`, `topology_mode`, `random_seed`, `random_stream_version`, `physics_version`, `baseline_version` | a mesma | |
| `reward_function`, `reward_function_kwargs` | `reward_function.type`, `reward_function.attributes` | Consulte [Função de recompensa](#função-de-recompensa). |
| `shared_observations` | `observations.<name>.shared_in_central_agent` | Substitui a lista construída a partir do schema. |
| `active_observations`, `inactive_observations`, `active_actions`, `inactive_actions` | `observations`, `actions`, `buildings.<b>.inactive_*` | Uma lista para todos os edifícios ou uma lista de listas, uma por edifício. Substituem as listas do schema; não se juntam a elas. |
| `simulate_power_outage` | `buildings.<b>.power_outage.simulate_power_outage` | Bool, ou um bool por edifício. |
| `start_date` | `start_date` | Também se sobrepõe ao calendário nos instantes exportados. |
| `render_mode`, `render` | a mesma | O valor do schema prevalece. |
| `render_file_format`, `render_chunk_size`, `render_session_name`, `export_kpis_on_episode_end`, `export_only_final_episode`, `debug_timing`, `check_observation_limits`, `physics_invariant_checks`, `energy_provenance`, `metrics_log_interval` | a mesma | |
| `ev_departure_within_tolerance`, `ev_departure_service_tolerance`, `business_as_usual_ev_charge_target` | a mesma | |

Opções só do construtor, sem chave no schema: `offline` (ou a variável de ambiente `CITYLEARN_OFFLINE`),
`solar_generation` (`false`, ou um bool por edifício, retira a FV), `time_step_ratio`, `render_directory`,
`render_directory_name`. O argumento `electric_vehicles` é aceite mas não escolhe VE: use
`electric_vehicles_def.<ev>.include`.

## Observações e ações

### Observações

```json
{"observations": {
  "hour": {"active": true, "shared_in_central_agent": true},
  "electrical_storage_soc": {"active": true, "shared_in_central_agent": false}
}}
```

| Campo | Tipo | Predefinição | Efeito |
|---|---|---|---|
| `active` | bool | `false` | A observação é devolvida para todos os edifícios que a conseguem produzir. |
| `shared_in_central_agent` | bool | `false` | Com `central_agent: true`, a observação aparece uma só vez no vetor central (tirada do primeiro edifício) em vez de uma vez por edifício. Use-a para valores iguais em todos os edifícios (calendário, meteorologia, uma tarifa partilhada). Ignorada para observações de carregadores, aparelhos diferíveis e escadas rolantes. |

Um nome que um edifício não consegue produzir lança `KeyError` na construção, **mesmo quando não está ativo**, por isso
liste apenas os nomes que existem nos seus edifícios (por exemplo
`occupant_interaction_indoor_dry_bulb_temperature_set_point_delta` só com o tipo de edifício com ocupantes). Os nomes
que começam por `deferrable_appliance_` ou `escalator_`, ou que contêm `electric_vehicle_`, são tratados como modelos por
dispositivo (ver abaixo): use apenas os nomes de modelo listados aqui.

Nomes das observações, por grupo. As definições completas, as unidades e as linhas temporais estão na
[referência das observações](observations_reference.md#observações-flat); os limites estão em
[Limites das observações](interfaces_flat_entity.md#limites-das-observações).

| Grupo | Nomes | Precisa de |
|---|---|---|
| Calendário | `month`, `day_type` (1-7, 8 = feriado), `hour` (1-24), `minutes`, `seconds`, `daylight_savings_status` | `minutes` e `seconds` só quando as colunas existem |
| Meteorologia | `outdoor_dry_bulb_temperature`, `outdoor_dry_bulb_temperature_predicted_1`, `outdoor_dry_bulb_temperature_predicted_2`, `outdoor_dry_bulb_temperature_predicted_3`, `outdoor_relative_humidity`, `outdoor_relative_humidity_predicted_1`, `outdoor_relative_humidity_predicted_2`, `outdoor_relative_humidity_predicted_3`, `diffuse_solar_irradiance`, `diffuse_solar_irradiance_predicted_1`, `diffuse_solar_irradiance_predicted_2`, `diffuse_solar_irradiance_predicted_3`, `direct_solar_irradiance`, `direct_solar_irradiance_predicted_1`, `direct_solar_irradiance_predicted_2`, `direct_solar_irradiance_predicted_3` | ficheiro `weather` |
| Preço e carbono | `electricity_pricing`, `electricity_pricing_predicted_1`, `electricity_pricing_predicted_2`, `electricity_pricing_predicted_3`, `carbon_intensity` | ficheiros `pricing`, `carbon_intensity` (zeros sem eles) |
| Cargas e conforto | `non_shiftable_load`, `cooling_demand`, `heating_demand`, `dhw_demand`, `indoor_dry_bulb_temperature`, `indoor_relative_humidity`, `average_unmet_cooling_setpoint_difference`, `occupant_count`, `indoor_dry_bulb_temperature_cooling_set_point`, `indoor_dry_bulb_temperature_heating_set_point`, `indoor_dry_bulb_temperature_cooling_delta`, `indoor_dry_bulb_temperature_heating_delta`, `comfort_band`, `hvac_mode` | colunas de `energy_simulation` |
| Ocupantes | `occupant_interaction_indoor_dry_bulb_temperature_set_point_delta` | tipo de edifício `LogisticRegressionOccupantInteractionBuilding` |
| Eficiência dos dispositivos | `cooling_device_efficiency`, `heating_device_efficiency`, `dhw_device_efficiency` | o dispositivo |
| Consumo dos dispositivos | `cooling_electricity_consumption`, `heating_electricity_consumption`, `dhw_electricity_consumption`, `cooling_storage_electricity_consumption`, `heating_storage_electricity_consumption`, `dhw_storage_electricity_consumption`, `electrical_storage_electricity_consumption` | o dispositivo |
| Armazenamento | `cooling_storage_soc`, `heating_storage_soc`, `dhw_storage_soc`, `electrical_storage_soc` | o armazenamento |
| FV e saldo | `solar_generation` (kWh por passo de controlo), `net_electricity_consumption` | |
| Falhas | `power_outage`, `power_outage_unserved_energy` | `power_outage.simulate_power_outage` |

Os modelos por dispositivo são expandidos para cada dispositivo do edifício:

| Modelo | Nome expandido | Valores |
|---|---|---|
| `electric_vehicle_charger_connected_state` | `electric_vehicle_charger_<charger>_connected_state` | 1 quando há um VE ligado, senão 0 |
| `connected_electric_vehicle_at_charger_departure_time` | `connected_electric_vehicle_at_charger_<charger>_departure_time` | passos do dataset até à partida, -1 sem VE |
| `connected_electric_vehicle_at_charger_required_soc_departure` | `connected_electric_vehicle_at_charger_<charger>_required_soc_departure` | fração de SOC, -0,1 sem VE |
| `connected_electric_vehicle_at_charger_soc` | `connected_electric_vehicle_at_charger_<charger>_soc` | fração de SOC, -0,1 sem VE |
| `connected_electric_vehicle_at_charger_battery_capacity` | `connected_electric_vehicle_at_charger_<charger>_battery_capacity` | kWh, -1 sem VE |
| `electric_vehicle_charger_incoming_state` | `electric_vehicle_charger_<charger>_incoming_state` | 1 quando um VE está a caminho, senão 0 |
| `incoming_electric_vehicle_at_charger_estimated_arrival_time` | `incoming_electric_vehicle_at_charger_<charger>_estimated_arrival_time` | passos do dataset até à chegada, -1 sem VE |
| `incoming_electric_vehicle_at_charger_estimated_soc_arrival` | `incoming_electric_vehicle_at_charger_<charger>_estimated_soc_arrival` | fração de SOC, -0,1 sem VE |
| `deferrable_appliance_<feature>` | `deferrable_appliance_<appliance>_<feature>` | `<feature>` é um de `pending`, `running`, `can_start`, `deadline_missed`, `earliest_start_time_step`, `latest_start_time_step`, `deadline_time_step`, `hours_until_latest_start`, `hours_until_deadline`, `slack_steps`, `slack_ratio`, `urgency_ratio`, `cycle_duration_steps`, `cycle_energy_kwh`, `remaining_energy_kwh`, `current_step_energy_kwh`, `priority`, `must_run`, `cycle_average_power_kw`, `cycle_peak_power_kw`, `cycle_load_factor_ratio`, `cycle_peak_step_offset_ratio`, `remaining_duration_steps`, `remaining_average_power_kw`, `current_step_power_kw` |
| `escalator_<feature>` | `escalator_<escalator>_<feature>` | `<feature>` é um de `passengers_from_trains_15min`, `background_pedestrians_15min`, `passengers_expected_15min`, `people_detected`, `passing_trains`, `minutes_to_next_train`, `available`, `state`, `requested_state`, `power_kw`, `service_required`, `service_met`, `unserved_passengers_15min` |

Observações acrescentadas pelo [serviço elétrico](#serviço-elétrico) (não listadas em `observations`):
`charging_building_headroom_kw`, `charging_building_export_headroom_kw`, `charging_phase_<phase>_headroom_kw`,
`charging_phase_<phase>_export_headroom_kw`, `charging_constraint_violation_kwh`,
`charging_phase_one_hot_<charger>_<phase>` e `available_grid_power`. Ligue-as ou desligue-as com
`electrical_service.observations`. As características do mercado comunitário, da resposta à procura, das previsões e
temporais existem só na interface entity; consulte [bundles de observação](#interface-entity-bundles-de-observação-e-previsões-derivadas).

### Ações

```json
{"actions": {"electrical_storage": {"active": true}, "electric_vehicle_storage": {"active": true}}}
```

| Campo | Tipo | Predefinição | Efeito |
|---|---|---|---|
| `active` | bool | `false` | A ação é esperada para todos os edifícios que têm o dispositivo. |

| Ação | Nome expandido | Intervalo | 1,0 significa | Precisa de |
|---|---|---|---|---|
| `electrical_storage` | o mesmo | [-1, 1] | carregar `nominal_power` durante um passo (negativo descarrega) | uma bateria com `capacity` e `nominal_power` acima de 0; caso contrário `ValueError`, salvo se o edifício listar a ação em `inactive_actions` |
| `cooling_storage`, `heating_storage`, `dhw_storage` | o mesmo | [-limite, limite], limite = `min(nominal_power do dispositivo / capacity do armazenamento, 1)` | carregar uma capacidade completa por hora | o armazenamento e o seu dispositivo |
| `cooling_device`, `heating_device` | o mesmo | [0, 1] | o dispositivo à potência nominal | um tipo de edifício com dinâmica; em `Building` a ação não tem efeito |
| `cooling_or_heating_device` | o mesmo | [-1, 1] | negativo arrefece, positivo aquece | um tipo de edifício com dinâmica; não combinar com `cooling_device`/`heating_device` |
| `electric_vehicle_storage` | `electric_vehicle_storage_<charger>` | [-1, 1], ou [0, 1] quando `max_discharging_power` é 0 | `max_charging_power` (negativo: `max_discharging_power`) | carregadores |
| `deferrable_appliance` | `deferrable_appliance_<appliance>` | [0, 1] | arrancar o próximo ciclo viável quando o valor excede `trigger_threshold` | aparelhos diferíveis |
| `escalator` | `escalator_<escalator>` | [0, 1] | abaixo de 1/3 espera, abaixo de 2/3 lento, senão normal | escadas rolantes (interface flat) |

Consulte a [referência das ações](actions_reference.md#conversão-física) para a conversão em energia e a ordem pela qual
as ações são aplicadas.

### Escolher observações e ações por edifício

- `buildings.<b>.inactive_observations` e `buildings.<b>.inactive_actions` desligam nomes do catálogo num só edifício.
  Use os nomes dos modelos (`electric_vehicle_storage`, `deferrable_appliance_pending`), não os nomes expandidos por
  dispositivo.
- Os argumentos do construtor `active_observations` / `active_actions` substituem todas as flags `active` (um nome só
  fica ativo se for listado); `inactive_observations` / `inactive_actions` substituem as listas dos edifícios. Indique
  uma lista para todos os edifícios, ou uma lista de listas pela ordem dos edifícios carregados. Não passe uma lista
  vazia em `active_observations`, `inactive_observations` ou `active_actions` (lança `IndexError`): passe `None`.
- Ordem das observações: a ordem de `observations` no schema e, depois, os nomes por carregador, por aparelho e por
  escada rolante. Leia `env.observation_names` em vez de depender de posições.

## Edifícios

```json
{"buildings": {"Building_1": {
  "include": true,
  "type": "citylearn.building.Building",
  "energy_simulation": "Building_1.csv",
  "weather": "weather.csv",
  "pricing": "pricing.csv",
  "carbon_intensity": "carbon_intensity.csv"
}}}
```

| Chave | Tipo | Predefinição | Efeito | Argumento / notas |
|---|---|---|---|---|
| `include` | bool | `true` | Carrega o edifício. Na topologia dinâmica todos os edifícios são carregados e `include: false` faz dele um membro inativo que pode entrar mais tarde. | argumento `buildings` |
| `type` | caminho de importação | `citylearn.building.Building` | Classe do edifício; consulte [Tipos de edifício](#tipos-de-edifício). | |
| `energy_simulation` | caminho | obrigatória | Cargas, procuras, calendário e perfil FV. | [colunas](dataset_reference.md#colunas-de-energy_simulation) |
| `weather` | caminho | obrigatória | 16 colunas de meteorologia. | |
| `pricing` | caminho | zeros | 4 colunas de preço. Com preços a zero, os dois totais de custo são 0 e os KPIs `*_cost_ratio_to_*_total_ratio` são NaN. | |
| `carbon_intensity` | caminho | zeros | Coluna `carbon_intensity`. Com intensidade carbónica a zero, os dois totais de emissões são 0 e os KPIs `*_emissions_ratio_to_*_total_ratio` são NaN. | |
| `noise_std` | número | `0.0` | Desvio-padrão do ruído gaussiano somado à temperatura interior, à humidade, ao perfil FV, a todas as colunas de meteorologia, aos preços e à intensidade carbónica deste edifício, na unidade de cada série. Os ficheiros com ruído não são partilhados entre edifícios. Mantenha `0` quando um edifício não tem ficheiro `pricing` ou `carbon_intensity`; caso contrário, as séries de zeros também recebem ruído. | |
| `inactive_observations` | lista de nomes | `[]` | Observações desligadas neste edifício. | substituída pelo argumento |
| `inactive_actions` | lista de nomes | `[]` | Ações desligadas neste edifício. | substituída pelo argumento |
| `equity_group` | string | nenhuma | `asset_rich` ou `asset_poor`. O KPI `equity_bpr_asset_poor_over_rich` só é calculado quando todos os edifícios têm um dos dois. | |
| `cooling_device`, `heating_device`, `dhw_device` | dispositivo | nenhum | [Dispositivos AVAC](#dispositivos-avac). | |
| `cooling_storage`, `heating_storage`, `dhw_storage` | dispositivo | nenhum | [Armazenamento térmico](#armazenamento-térmico). | |
| `electrical_storage` | dispositivo | nenhum | [Bateria](#bateria). | |
| `pv` | dispositivo | nenhum | [FV](#fv). | `solar_generation=False` retira-a |
| `chargers` | objeto | `{}` | [Carregadores](#carregadores). | |
| `deferrable_appliances` | objeto | `{}` | [Aparelhos diferíveis](#aparelhos-diferíveis). | |
| `escalators` | objeto | `{}` | [Escadas rolantes](#escadas-rolantes). | |
| `electrical_service` | objeto | nenhum | [Serviço elétrico](#serviço-elétrico). | |
| `charging_constraints` | objeto | nenhum | [Restrições de carregamento antigas](#restrições-de-carregamento-antigas). Ignorado quando `electrical_service` está definido. | |
| `power_outage` | objeto | `{}` | [Falhas de energia](#falhas-de-energia). | `simulate_power_outage` |
| `dynamics` | objeto | nenhum | [Dinâmica térmica](#dinâmica-térmica). | |
| `occupant` | objeto | nenhum | [Modelo de ocupantes](#modelo-de-ocupantes). | |
| `set_point_hold_time_steps` | int, pelo menos 0, ou `null` | `null` (mantém até o horário mudar) | Passos de controlo durante os quais uma alteração de set point de um ocupante se mantém. | só tipo de edifício com ocupantes |
| `set_point_limits` | `[mínimo, máximo]`, °C | `[15, 30]` | Intervalo para onde um ocupante pode mover um set point; `mínimo < máximo`. Não é aplicado na versão 1 da física. | só tipo de edifício com ocupantes; depois da 3.6.0 |

Uma secção de dispositivo ausente passa a um marcador de tamanho 0, pelo que o edifício não tem esse dispositivo.

### Tipos de edifício

| `type` | Uso | Precisa de |
|---|---|---|
| `citylearn.building.Building` | Predefinição. A procura térmica vem do dataset e os dispositivos AVAC servem-na. | |
| `citylearn.building.DynamicsBuilding` | Classe base para edifícios cuja temperatura interior responde às ações AVAC. | uma subclasse |
| `citylearn.building.LSTMDynamicsBuilding` | Temperatura interior prevista por uma LSTM; as ações `cooling_device`, `heating_device` e `cooling_or_heating_device` definem a energia térmica. | `dynamics`, PyTorch |
| `citylearn.building.OccupantInteractionBuilding` | Edifício com dinâmica cujos ocupantes alteram set points. | `dynamics`, `occupant` |
| `citylearn.building.LogisticRegressionOccupantInteractionBuilding` | Ocupantes modelados por regressão logística; lê `set_point_hold_time_steps` e `set_point_limits`. | `dynamics`, `occupant`, scikit-learn |

`dynamics`, `occupant`, `set_point_hold_time_steps` e `set_point_limits` são ignorados, sem aviso, num tipo que não os
usa.

### Ficheiros de séries temporais

A [referência dos datasets](dataset_reference.md) lista todas as colunas. Em resumo:

- `energy_simulation`: obrigatórias `month`, `hour`, `day_type`, `indoor_dry_bulb_temperature`, `non_shiftable_load`,
  `dhw_demand`, `cooling_demand`, `heating_demand`, `solar_generation`; opcionais `minutes`, `seconds`,
  `daylight_savings_status`, `average_unmet_cooling_setpoint_difference`, `indoor_relative_humidity`, `occupant_count`,
  `indoor_dry_bulb_temperature_cooling_set_point`, `indoor_dry_bulb_temperature_heating_set_point` (ambas 0 °C quando
  ausentes, para a física e as observações; sem as duas colunas, os KPIs de conforto do edifício são NaN, consulte
  [Conforto e resiliência](kpis_reference.md#conforto-e-resiliência)), `hvac_mode` (1 = arrefecimento quando ausente), `power_outage`, `comfort_band` (2 °C quando ausente). Uma
  coluna desconhecida lança `TypeError`.
- `weather`: as quatro variáveis de meteorologia, cada uma com `_predicted_1`, `_predicted_2` e `_predicted_3`; as 16
  são obrigatórias.
- `pricing`: `electricity_pricing` e as suas três previsões.
- `carbon_intensity`: `carbon_intensity`.

### Dinâmica térmica

```json
{"dynamics": {"type": "citylearn.dynamics.LSTMDynamics", "attributes": {
  "filename": "Building_1.pth", "input_observation_names": ["indoor_dry_bulb_temperature", "hour_sin"],
  "input_normalization_minimum": [0.0, -1.0], "input_normalization_maximum": [40.0, 1.0],
  "hidden_size": 8, "num_layers": 2, "lookback": 12
}}}
```

| Atributo | Obrigatório | Efeito |
|---|---|---|
| `filename` | sim | State dict do PyTorch, relativo a `root_directory`. |
| `input_observation_names` | sim | Entradas do modelo; tem de incluir `indoor_dry_bulb_temperature`. São permitidos `<nome>_sin` / `<nome>_cos` de observações periódicas. |
| `input_normalization_minimum`, `input_normalization_maximum` | sim | Um valor por entrada. |
| `hidden_size`, `num_layers`, `lookback` | sim | Forma da LSTM; as ações AVAC só têm efeito ao fim de `lookback` passos. |
| `input_size` | não | Número de entradas (predefinição: o número de nomes). |
| `dropout` | não | `0.0`; inativo durante a simulação. |

### Modelo de ocupantes

```json
{"occupant": {"type": "citylearn.occupant.LogisticRegressionOccupant", "parameters_filename": "occupant_parameters.csv",
  "attributes": {"setpoint_increase_model_filename": "increase.pkl", "setpoint_decrease_model_filename": "decrease.pkl",
                 "delta_output_map": {"0": -1.0, "1": 0.0, "2": 1.0}}}}
```

| Chave | Efeito |
|---|---|
| `type` | Classe do ocupante, `citylearn.occupant.LogisticRegressionOccupant`. |
| `parameters_filename` | CSV com `a_increase`, `b_increase`, `a_decrease`, `b_decrease`, uma linha por passo global. |
| `attributes.setpoint_increase_model_filename`, `setpoint_decrease_model_filename` | Classificadores em pickle, relativos a `root_directory`. Carregue apenas ficheiros em que confia. |
| `attributes.delta_output_map` | Classe para alteração de set point em °C. |

## Dispositivos

Todas as secções de dispositivo têm a mesma forma:

```json
{"electrical_storage": {
  "type": "citylearn.energy_model.Battery",
  "autosize": false,
  "autosize_attributes": {},
  "attributes": {"capacity": 50.0, "nominal_power": 25.0}
}}
```

| Campo | Tipo | Predefinição | Efeito |
|---|---|---|---|
| `type` | caminho de importação | obrigatório | Classe do dispositivo. `cooling_device` tem de ser uma `HeatPump`; `heating_device` e `dhw_device` podem ser `HeatPump` ou `ElectricHeater`. |
| `attributes` | objeto | `{}` | Argumentos do construtor. Um nome desconhecido lança `TypeError`; `null` escolhe a predefinição. |
| `autosize` | bool | `false` | Dimensiona o dispositivo a partir dos dados; consulte [Dimensionamento automático](#dimensionamento-automático). Substitui os atributos dimensionados. |
| `autosize_attributes` | objeto | `{}` | Argumentos do dimensionamento. |

`seconds_per_time_step` e `time_step_ratio` em `attributes` são substituídos pelos valores do ambiente. Um atributo
`random_seed` dá a semente das predefinições sorteadas do dispositivo em vez do fluxo do ambiente.

### Dispositivos AVAC

| Classe | Atributo | Predefinição | Unidade | Efeito |
|---|---|---|---|---|
| `citylearn.energy_model.HeatPump` | `nominal_power` | `0` | kW elétricos | Potência elétrica máxima. |
| | `efficiency` | sorteada em [0,2, 0,3] | fração de Carnot | COP = efficiency × T_alvo / (T_alvo - T_exterior), em kelvin, limitado a 20. |
| | `target_heating_temperature` | sorteada em [45, 50] | °C | Temperatura de ida para aquecimento e água quente. |
| | `target_cooling_temperature` | sorteada em [7, 10] | °C | Temperatura de ida para arrefecimento. |
| `citylearn.energy_model.ElectricHeater` | `nominal_power` | `0` | kW | Potência elétrica máxima. |
| | `efficiency` | sorteada em [0,9, 0,99] | rácio | Calor por kWh consumido. |

Em `citylearn.building.Building`, os dispositivos servem a procura do dataset. Na versão 2 da física, o limite de
energia de um dispositivo é a sua potência vezes a duração do passo; a versão 1 compara a energia do passo com kW (um
limite de uma hora).

### Armazenamento térmico

`cooling_storage`, `heating_storage` e `dhw_storage` usam `citylearn.energy_model.StorageTank`.

| Atributo | Predefinição | Unidade | Efeito |
|---|---|---|---|
| `capacity` | `0` | kWh térmicos | Dimensão do armazenamento. |
| `efficiency` | sorteada em [0,90, 0,98] | ida e volta | Cada sentido usa a raiz quadrada. |
| `loss_coefficient` | sorteado em [0,001, 0,009] | por hora | Perda em repouso, composta por passo: `1 - (1 - loss) ** (seconds_per_time_step / 3600)`. |
| `initial_soc` | `0` | fração | SOC no início de um episódio. |
| `max_input_power`, `max_output_power` | `null` (sem limite) | kW | Limites de potência de carga e de descarga. |

### Bateria

```json
{"electrical_storage": {
  "type": "citylearn.energy_model.Battery",
  "attributes": {
    "capacity": 6.4,
    "nominal_power": 5.0,
    "efficiency": 0.9,
    "depth_of_discharge": 0.9,
    "initial_soc": 0.1,
    "capacity_loss_coefficient": 1e-5,
    "loss_coefficient": 0.0,
    "power_efficiency_curve": [[0, 0.83], [0.3, 0.83], [0.7, 0.9], [0.8, 0.9], [1, 0.85]],
    "capacity_power_curve": [[0.0, 1.0], [0.8, 1.0], [1.0, 0.2]]
  }
}}
```

O modelo da bateria estacionária trabalha com a energia por passo de controlo nos terminais
da bateria, do lado do edifício. O estado de carga (SOC) é uma fração de `capacity`.

| Atributo | Unidade | Predefinição | Significado |
|---|---:|---|---|
| `capacity` | kWh | 0 | Capacidade nominal de armazenamento, antes da degradação. |
| `nominal_power` | kW | 0 | Potência pela qual as curvas são escaladas. |
| `efficiency` | rácio | sorteada em [0,90, 0,98] | Eficiência de ida e volta. Uma `power_efficiency_curve` gerada é construída à volta dela; durante a simulação, a curva dá a eficiência em cada passo. |
| `power_efficiency_curve` | `[[x, y], ...]` | sorteada, ver abaixo | Eficiência de ida e volta `y` em função da potência nos terminais dividida por `nominal_power` (`x` em [0, 1]). |
| `capacity_power_curve` | `[[x, y], ...]` | sorteada, ver abaixo | Potência máxima de carregamento como fração de `nominal_power` (`y`) em função do SOC (`x`). |
| `discharge_power_curve` | `[[x, y], ...]` | `[[0, 1], [1, 1]]` | Potência máxima de descarga como fração de `nominal_power` em função do SOC. A versão da física 1 usa `capacity_power_curve` em vez desta. |
| `depth_of_discharge` | rácio | 1,0 | Fração de `capacity` que pode ser descarregada. |
| `initial_soc` | rácio | `1 - depth_of_discharge` | SOC no início do episódio, em [0, 1]. |
| `capacity_loss_coefficient` | rácio | sorteado em [1e-5, 1e-4] | Fração de `capacity` perdida por ciclo completo equivalente. |
| `loss_coefficient` | rácio por hora | sorteado em [0,001, 0,009] | Perda em repouso da energia armazenada, composta por passo como no armazenamento térmico. |
| `phase_connection` | `L1`, `L2`, `L3`, `all_phases` | `L1` (serviço monofásico), `all_phases` (trifásico) | Fase da bateria sob um [serviço elétrico](#serviço-elétrico). |

Uma predefinição indicada como "sorteada" é tirada do fluxo aleatório do ambiente quando o
atributo é omitido ou `null`, pelo que depende da semente e de `random_stream_version`. Os datasets do
desafio de 2022 omitem as duas curvas, pelo que cada semente obtém curvas diferentes. Defina os
atributos explicitamente para as fixar.

- **Eficiência.** `efficiency` e todos os valores de `power_efficiency_curve` são eficiências
  de ida e volta: a energia carregada e depois descarregada conserva `efficiency` do seu
  valor. Cada conversão usa a raiz quadrada. Carregar `E` kWh nos terminais armazena
  `E * sqrt(eta)`, e entregar `E` kWh retira `E / sqrt(eta)` do armazenamento, em que `eta` é
  lido de `power_efficiency_curve` à potência aplicada nos terminais. Uma eficiência num só
  sentido de 0,95 numa ficha técnica deve ser introduzida como 0,95² = 0,9025; introduzida
  como 0,95, dá uma eficiência num só sentido de cerca de 0,975.
- **Curvas de potência.** `capacity_power_curve` e `discharge_power_curve` são avaliadas no SOC
  do início do passo, e os seus valores são multiplicados por `nominal_power`. Entre pontos,
  as curvas são interpoladas linearmente.
- **Profundidade de descarga.** A descarga para num SOC de `1 - depth_of_discharge`, um
  mínimo medido sobre a `capacity` nominal. O carregamento para na capacidade degradada.
- **Degradação da capacidade.** Depois de cada carga ou descarga, a capacidade desce
  `capacity_loss_coefficient * capacity * |energia nos terminais| / (2 * capacidade degradada)`.
  Uma carga e descarga completas da capacidade degradada são um ciclo completo equivalente e
  perdem `capacity_loss_coefficient * capacity`.
- **Curvas geradas.** Sem `power_efficiency_curve`, são sorteados cinco pontos com `x` perto
  de 0, 0,3, 0,7, 0,8 e 1, com valores entre 0,85 e 1,0 vezes `efficiency` (o ponto perto de
  0,8 é igual a `efficiency`). Sem `capacity_power_curve`, são sorteados três pontos: 0,95 a
  1,0 com SOC 0, 0,90 a 0,95 com um SOC perto de 0,8, e 0,20 a 0,30 com SOC 1.
- Com o `initial_soc` predefinido, uma bateria começa na sua reserva: vazia quando
  `depth_of_discharge` é 1. Defina `initial_soc` para começar noutro ponto.
- **Falhas.** Na versão 2 da física, a bateria descarrega durante uma falha depois do armazenamento térmico, e só até à
  carga em ilha que a FV deixa por cobrir.

### FV

```json
{"pv": {
  "type": "citylearn.energy_model.PV",
  "attributes": {
    "nominal_power": 120.0,
    "generation_mode": "absolute"
  }
}}
```

| Atributo | Predefinição | Unidade | Efeito |
|---|---|---|---|
| `nominal_power` | `0` | kW DC | Potência instalada. Ignorada no modo `absolute`. |
| `generation_mode` | `per_kw` | | Como `energy_simulation.solar_generation` é lida; ver abaixo. |

| `generation_mode` | Sinónimos | Interpreta `energy_simulation.solar_generation` como | Fórmula |
|---|---|---|---|
| `per_kw` | `profile`, `w_per_kw` | Perfil normalizado por kW instalado, em `W/kW`. | `generation_kwh = nominal_power * value / 1000 * seconds_per_time_step / 3600`. |
| `absolute` | `absolute_kwh`, `kwh`, `kwh_step`, `energy` | Produção absoluta já em `kWh/step`. | `generation_kwh = value`. |

Use `absolute` para produção medida ou para séries de energia geradas por um conversor. Use `per_kw` para perfis FV
normalizados. Por exemplo, `nominal_power=4.0` e um valor de 1000 W/kW dão 4,0 kWh por passo horário e 1,0 kWh por
passo de 900 s. O modo não distingue maiúsculas; outro valor lança `AssertionError`.

### Dimensionamento automático

Com `"autosize": true`, o dispositivo é dimensionado a partir dos dados do edifício na janela de simulação, e os
atributos dimensionados são substituídos.

| Dispositivo | Define | `autosize_attributes` |
|---|---|---|
| `HeatPump` | `nominal_power` = procura máxima / COP × `safety_factor` | `safety_factor` (1,0) |
| `ElectricHeater` | `nominal_power` = procura máxima / eficiência × `safety_factor` | `safety_factor` (1,0) |
| `StorageTank` | `capacity`: versão 2 = potência máxima da procura × `duration` × `safety_factor`; versão 1 = procura máxima de um passo × `safety_factor` | `safety_factor` (sorteado em [1, 2]), `duration` (h, 1,0) |
| `Battery` | `capacity`, `nominal_power`, `depth_of_discharge`, `efficiency`, `loss_coefficient`, `capacity_loss_coefficient` a partir de um catálogo de baterias | `duration` (h, sorteada em [1,5, 3,5]), `parallel` (`false`), `safety_factor` (1,0) |
| `PV` | `nominal_power` e o perfil `solar_generation` a partir do PVWatts; força `generation_mode: per_kw` | `epw_filepath` (obrigatório), `use_sample_target` (`false`), `zero_net_energy_proportion` (sorteada em [0,7, 1,0]), `roof_area` (m², sem limite), `safety_factor` (1,0) |

O dimensionamento da bateria e da FV descarrega dados de dimensionamento se não estiverem em cache (`offline=True`
impede a descarga); a FV precisa de `pip install nrel-pysam`. Na versão 1 da física, o dimensionamento da FV assume
dados horários.

## Serviço elétrico

`buildings.<name>.electrical_service` define os limites da ligação do edifício à rede. Os
limites são potência ativa em kW; uma chave ausente significa sem limite (`null` e `Infinity` também, na simulação, mas
consulte [Erros comuns](#erros-comuns-e-o-que-evitar)).

```json
{"electrical_service": {
  "mode": "single_phase",
  "limits": {
    "total": {"import_kw": 17.25, "export_kw": 6.9},
    "per_phase": {"L1": {"import_kw": 17.25, "export_kw": 6.9}}
  },
  "available_grid_power": {"filename": "available_grid_power.csv", "column": "Building_1"},
  "observations": {"available_grid_power": true}
}}
```

| Campo | Tipo | Predefinição | Finalidade |
|---|---:|---|---|
| `mode` | `single_phase`, `three_phase` | `single_phase` | Tipo de serviço. Os serviços monofásicos só têm `L1`. |
| `default_split` | `balanced`, `L1`, `L2`, `L3` | `balanced` | Repartição por fases da carga sem ligação a uma fase. Um serviço monofásico aceita `balanced` e `L1`. |
| `limits.total.import_kw`, `limits.total.export_kw` | kW | sem limite | Capacidade estática da ligação. Um valor negativo ou NaN lança `ValueError`. |
| `limits.per_phase.<L1/L2/L3>.import_kw`, `export_kw` | kW | sem limite | Limites estáticos por fase. `phase_1` e `l1` são aceites para `L1`. |
| `available_grid_power` | caminho ou objeto | nenhum | Série opcional da importação disponível em cada passo; ver abaixo. |
| `observations.headroom` | bool | `true` | Expõe `charging_building_headroom_kw` (quando há um limite total de importação ou uma série) e `charging_phase_<phase>_headroom_kw` (fases com limite de importação). |
| `observations.headroom_export` | bool | `true` | Expõe `charging_building_export_headroom_kw` e `charging_phase_<phase>_export_headroom_kw` para os limites de exportação. |
| `observations.violation` | bool | `true` | Expõe `charging_constraint_violation_kwh`. É esta flag que decide, não o catálogo `observations`. |
| `observations.phase_encoding` | bool | `false` | Expõe a atribuição de fase dos carregadores em codificação one-hot, `charging_phase_one_hot_<charger>_<phase>`. |
| `observations.available_grid_power` | bool | `true` | Expõe a observação `available_grid_power` quando há uma série definida. |
| `expose_observations` | bool | `true` | Valor de recurso para `observations.headroom` quando essa chave está ausente. |

Os carregadores e a bateria são colocados numa fase com `phase_connection` nos respetivos `attributes` (`L1`, `L2`, `L3`
ou `all_phases`; predefinição `L1` nos serviços monofásicos e `all_phases` nos trifásicos). As observações das margens
descrevem o último intervalo executado. Na versão 2 da física, a margem é repartida pelas potências que os dispositivos
conseguem de facto absorver, depois das cargas térmicas e não deslocáveis; a versão 1 reparte os pedidos em bruto.

### Potência de rede disponível

`available_grid_power` indica um ficheiro CSV ou Parquet com uma linha por passo de tempo,
alinhado com `energy_simulation`. Indique-o como nome de ficheiro ou como
`{"filename": ..., "column": ...}`. Sem `column`, é usada a coluna com o nome do edifício e,
depois, uma coluna chamada `available_grid_power`, pelo que um só ficheiro pode ter uma coluna
por edifício. Os valores são a potência que o edifício pode importar da rede nesse passo, em
kW (potência, não energia por passo).

O limite de importação em vigor num passo é o menor entre `limits.total.import_kw` e o valor
da série. Um valor em branco aplica apenas o limite estático; é um erro quando `import_kw` não
está definido. Os valores têm de ser finitos e não negativos. Use-o para limitações abaixo da
capacidade da ligação, como um operador da rede de distribuição que reduz a potência de
dispositivos controláveis (§14a EnWG alemão) ou uma redução de capacidade durante um período
de stress da rede.

O limite atua como o estático: os carregadores de VE e o armazenamento elétrico são limitados
primeiro, e a carga que não pode ser limitada continua a ser servida e conta como violação do
serviço elétrico. Um limite de 0 kW não coloca o edifício em ilha; use
[`power_outage`](#falhas-de-energia) para um apagão. Os limites por fase continuam estáticos. A
observação `available_grid_power` indica o limite do intervalo seguinte; as observações das
margens descrevem o último intervalo executado, pelo que refletem o limite então em vigor.

### Restrições de carregamento antigas

`buildings.<name>.charging_constraints` é o limite antigo para o carregamento dos VE. Só é lido quando o edifício não
tem `electrical_service`.

```json
{"charging_constraints": {
  "building_limit_kw": 22.0,
  "phases": [{"name": "phase_1", "limit_kw": 11.0, "chargers": ["charger_4_1"]}],
  "observations": {"headroom": true, "violation": true, "phase_encoding": false}
}}
```

| Campo | Predefinição | Efeito |
|---|---|---|
| `building_limit_kw` | sem limite | Limite da soma dos pedidos de carregamento do edifício, em kW. A carga base não conta. |
| `phases[].name` | `phase_<n>` | Nome usado nos nomes das observações. |
| `phases[].limit_kw` | sem limite | Limite da soma dos pedidos de carregamento dos carregadores listados. |
| `phases[].chargers` | `[]` | IDs dos carregadores da fase. IDs desconhecidos são ignorados. |
| `expose_observations` | `true` | Valor de recurso para `observations.headroom`. |
| `observations.headroom`, `observations.violation`, `observations.phase_encoding` | `true`, `true`, `false` | Como no serviço elétrico. |
| `observations.headroom_export` | `false` | Sem efeito: aqui não há limites de exportação. |

Só o carregamento é limitado; a descarga (V2G) não é. Os pedidos acima de um limite são reduzidos proporcionalmente.

## Veículos elétricos e carregadores

Um VE é definido uma vez em `electric_vehicles_def`. Cada carregador lê um ficheiro de horário cuja coluna
`electric_vehicle_id` indica o VE ligado ou a chegar em cada passo.

### Carregadores

```json
{"chargers": {
  "AC001": {
    "type": "citylearn.electric_vehicle_charger.Charger",
    "charger_simulation": "chargers/AC001.parquet",
    "attributes": {
      "max_charging_power": 7.4,
      "min_charging_power": 1.4,
      "max_discharging_power": 0.0,
      "min_discharging_power": 0.0,
      "efficiency": 0.95,
      "phase_connection": "L1"
    }
  }
}}
```

| Chave | Tipo | Predefinição | Efeito | Desde |
|---|---|---|---|---|
| (ID do carregador) | string | | Usado nos nomes das observações e das ações e em `charging_constraints.phases[].chargers`. | |
| `type` | caminho de importação | obrigatório | Classe do carregador, normalmente `citylearn.electric_vehicle_charger.Charger`. | |
| `charger_simulation` | caminho | obrigatório | Ficheiro de horário do carregador; consulte as [colunas dos carregadores](dataset_reference.md#colunas-da-simulação-de-carregadores). | |
| `attributes` | objeto | `{}` | Consulte [Atributos do carregador](#atributos-do-carregador). | |
| `soc_unit` | `percent`, `fraction` | inferida por coluna | Unidade das colunas de SOC do ficheiro de horário. Omitida, é inferida uma vez por coluna a partir de todo o ficheiro (versão 2 da física) ou valor a valor (versão 1); consulte [Unidade do SOC](dataset_reference.md#unidade-do-soc). | depois da 3.6.0 |
| `noise_std` | número | `0.0` | Ruído gaussiano, em pontos percentuais de SOC, somado ao SOC pedido para a partida e ao SOC estimado à chegada. Altera os alvos usados pelos KPIs, não só as observações. | 2.x |
| `autosize` | | | Aceite e ignorado: os carregadores não têm dimensionamento automático. | |

Outra chave dá um `UserWarning` que sugere a chave mais próxima e é ignorada.

#### Atributos do carregador

| Atributo | Unidade | Predefinição (física 2) | Predefinição (física 1) | Efeito |
|---|---|---|---|---|
| `nominal_power` | kW | nenhuma | não usada | Potência nominal; predefinição de `max_charging_power`. |
| `max_charging_power` | kW | `nominal_power`, senão 50 com aviso | 50 com aviso | Potência para uma ação de 1,0. |
| `min_charging_power` | kW | 0 | 0 | Pedidos abaixo dela dão 0; pedidos acima dela são pelo menos este valor. |
| `max_discharging_power` | kW | **0** (sem V2G) com aviso | 50 com aviso | Potência para uma ação de -1,0. Com 0, o intervalo da ação é [0, 1]. |
| `min_discharging_power` | kW | 0 | 0 | Potência mínima de descarga, como no carregamento. |
| `efficiency` | rácio, (0, 1] | 1,0, com aviso quando é usada | igual | O carregamento armazena `AC × efficiency` no VE; a descarga entrega `energia da bateria × efficiency`. Usada no sentido sem curva. |
| `charge_efficiency_curve` | `[[fração de potência, eficiência], ...]` | nenhuma | nenhuma | Eficiência em função da potência de carga / `max_charging_power`, interpolada linearmente. |
| `discharge_efficiency_curve` | igual | nenhuma | nenhuma | O mesmo para a descarga, em relação a `max_discharging_power`. |
| `phase_connection` | `L1`, `L2`, `L3`, `all_phases` | `L1` / `all_phases` | igual | Fase sob um [serviço elétrico](#serviço-elétrico); não é usada por `charging_constraints`. |
| `charger_type` | qualquer | nenhuma | nenhuma | Só uma etiqueta (por exemplo 0 para AC, 1 para DC). |

Outro nome de atributo lança `ValueError`, que indica o carregador e sugere o nome válido mais próximo. Não defina
`seconds_per_time_step` nem `time_step_ratio` em `attributes`: são definidos ao carregar o schema, e um valor indicado
aí lança `TypeError` (`got multiple values`) na construção.

Receitas:

- **Carregamento num só sentido (predefinição):** defina apenas `max_charging_power` (ou `nominal_power`).
- **V2G:** defina `"max_discharging_power": 7.2` e ative `electric_vehicle_storage`.
- **Carregador na fase L2 de uma casa trifásica:** `"mode": "three_phase"` em `electrical_service` e
  `"phase_connection": "L2"` nos atributos do carregador.

### Definições dos VE

```json
{"electric_vehicles_def": {
  "EV_1": {
    "type": "citylearn.electric_vehicle.ElectricVehicle",
    "include": true,
    "battery": {
      "type": "citylearn.energy_model.Battery",
      "attributes": {
        "capacity": 60.0,
        "nominal_power": 50.0,
        "initial_soc": 0.4,
        "depth_of_discharge": 0.9
      }
    }
  }
}}
```

| Chave | Tipo | Predefinição | Efeito |
|---|---|---|---|
| (ID do VE) | string | | Tem de coincidir exatamente, como texto, com os valores de `electric_vehicle_id` dos ficheiros dos carregadores. Uma linha que indica um VE desconhecido ou excluído é ignorada sem aviso, tal como os IDs escritos como números. |
| `type` | caminho de importação | `citylearn.electric_vehicle.ElectricVehicle` | Classe do VE. |
| `include` | bool | `true` | Inclui o VE. Sempre verdadeiro na topologia dinâmica. |
| `battery.type` | caminho de importação | `citylearn.energy_model.Battery` | Tem de ser uma subclasse de `Battery`. |
| `battery.attributes` | objeto | obrigatório | Ver abaixo. |

| `battery.attributes` | Predefinição | Efeito |
|---|---|---|
| `capacity` | obrigatória | kWh. |
| `nominal_power` | obrigatória | kW; limite de potência do lado da bateria, juntamente com `capacity_power_curve`. |
| `initial_soc` | sorteado uniformemente em [0, 1] a partir de `random_seed` e do nome do VE | SOC no início de um episódio. O sorteio ignora `depth_of_discharge`. |
| `depth_of_discharge` | `1.0` | Mínimo de descarga `1 - depth_of_discharge`. |
| `loss_coefficient` | **`0.0`** nos VE | Perda em repouso por hora, composta por passo. |
| `efficiency`, `capacity_loss_coefficient`, `power_efficiency_curve`, `capacity_power_curve`, `discharge_power_curve` | como na [Bateria](#bateria) | |
| `random_seed` | fluxo do ambiente | Semente das predefinições sorteadas do VE. |

Com `"battery": {"type": "citylearn.community_dataset.InventoryBattery"}`, são lidos também os atributos
`max_charge_kw`, `max_discharge_kw` (que substituem `nominal_power`), `min_soc`, `max_soc` (também os limites do sorteio
de `initial_soc`), `charging_efficiency` e `discharging_efficiency`; com uma `Battery` simples lançam `TypeError`.
Qualquer outra chave em `battery.attributes` é ignorada sem aviso.

Enquanto um VE não está ligado, o seu SOC varia aleatoriamente em cada passo. Na versão 1 da física, essa variação
ignora a perda em repouso.

### Resumo do ficheiro do carregador

O ficheiro de horário tem uma linha por passo dos dados com `electric_vehicle_charger_state` (1 ligado, 2 a chegar,
outros valores sem VE), `electric_vehicle_id`, `electric_vehicle_departure_time`, `electric_vehicle_required_soc_departure`,
`electric_vehicle_estimated_arrival_time`, `electric_vehicle_estimated_soc_arrival` e, opcionalmente,
`electric_vehicle_session_id` e `electric_vehicle_current_soc`. Um `electric_vehicle_current_soc` válido na linha da
ligação define o SOC do VE que chega. Consulte as [colunas dos carregadores](dataset_reference.md#colunas-da-simulação-de-carregadores).

## Aparelhos diferíveis

```json
{"deferrable_appliances": {
  "washer_1": {
    "type": "citylearn.energy_model.DeferrableAppliance",
    "cycle_profiles_file": "deferrables/washer_profiles.csv",
    "flexibility_schedule_file": "deferrables/washer_schedule.csv",
    "attributes": {
      "trigger_threshold": 0.5
    }
  }
}}
```

| Campo | Obrigatório | Predefinição | Finalidade |
|---|---:|---|---|
| `type` | não | `citylearn.energy_model.DeferrableAppliance` | Classe do aparelho. |
| `cycle_profiles_file` | sim | | Perfis dos ciclos em kWh por passo de controlo; consulte [`cycle_profiles_file`](dataset_reference.md#cycle_profiles_file). |
| `flexibility_schedule_file` | sim | | Ciclos com as janelas e os prazos em passos globais; os ciclos de um aparelho não se podem sobrepor. Consulte [`flexibility_schedule_file`](dataset_reference.md#flexibility_schedule_file). |
| `attributes.trigger_threshold` | não | `0.5` | Uma ação acima deste valor arranca o próximo ciclo viável. Limitado a [0, 1]. |
| `attributes.nominal_power` | não | `0` (sem verificação) | kW. Quando é positivo, o pico de potência de cada ciclo tem de ficar igual ou abaixo dele. |

Na versão 2 da física, um ciclo arranca só com a informação do passo atual, e uma falha de energia suspende um ciclo em
curso.

## Escadas rolantes

As escadas rolantes só funcionam com a interface flat.

```json
{"escalators": {
  "EscadaRolante_1": {
    "type": "citylearn.energy_model.Escalator",
    "simulation": "EscadaRolante_1.csv",
    "attributes": {
      "standby_power": 0.08,
      "slow_power": 0.42,
      "normal_power": 2.10,
      "minimum_state_steps": 1,
      "service_threshold_passengers": 0.5
    }
  }
}}
```

| Campo | Obrigatório | Predefinição | Finalidade |
|---|---:|---|---|
| `type` | não | `citylearn.energy_model.Escalator` | Classe da escada rolante. |
| `simulation` | sim | | CSV com uma linha por passo de simulação (também é aceite `simulation_file`). |
| `attributes.standby_power`, `slow_power`, `normal_power` | não | `0` | kW, finitos e não negativos, com espera ≤ lento ≤ normal. |
| `attributes.minimum_state_steps` | não | `1` | Permanência mínima num estado. |
| `attributes.service_threshold_passengers` | não | `0.5` | Procura de passageiros acima da qual o serviço é necessário. |

O CSV exige `time_step`, `passengers_from_trains_15min`,
`background_pedestrians_15min`, `passengers_expected_15min`, `people_detected`,
`arriving_trains`, `departing_trains`, `minutes_to_next_train` e `available`.
`passengers_expected_15min` tem de ser igual à soma das duas componentes de passageiros, e `time_step` tem de contar as
linhas carregadas a partir de 0.

## Falhas de energia

```json
{"power_outage": {
  "simulate_power_outage": true,
  "stochastic_power_outage": false,
  "vehicle_to_building": false
}}
```

| Chave | Tipo | Predefinição | Finalidade | Argumento |
|---|---:|---|---|---|
| `simulate_power_outage` | bool | `false` | Simula falhas da rede neste edifício. Sem ela, a observação `power_outage` é sempre 0. | `simulate_power_outage` |
| `stochastic_power_outage` | bool | `false` | Sorteia as falhas com `stochastic_power_outage_model` em vez de usar a coluna `power_outage`. | |
| `stochastic_power_outage_model.type` | caminho de importação | `citylearn.power_outage.PowerOutage` | O modelo predefinido torna cada passo uma falha com probabilidade 0,5. Use `citylearn.power_outage.ReliabilityMetricsPowerOutage` para falhas realistas. | |
| `stochastic_power_outage_model.attributes` | objeto | `{}` | Para `ReliabilityMetricsPowerOutage`: `saifi` (interrupções por ano, 1,436), `caidi` (minutos por interrupção, 331,2), `start_time_steps` (passos do dia em que uma falha pode começar, por omissão todos), `random_seed`. | |
| `vehicle_to_building` | bool | `false` | Permite que um VE ligado descarregue para o edifício durante uma falha, até à carga em ilha que a FV e a bateria deixam por cobrir. O carregador precisa de `max_discharging_power` acima de 0. A descarga pode deixar o veículo abaixo do SOC pedido para a partida. | |

Durante uma falha o edifício fica em ilha: é alimentado pela FV, pela bateria, pelo armazenamento térmico e (com
`vehicle_to_building`) pelos VE; a energia não servida é indicada em `power_outage_unserved_energy`. Na versão 2 da
física, a bateria e os VE descarregam depois do armazenamento térmico e antes de as cargas serem servidas; consulte
[O que cada versão altera](#o-que-cada-versão-altera).

## Mercado comunitário e liquidação

```json
{"community_market": {
  "enabled": true,
  "local_price_ratio_to_grid_import": 0.8,
  "settlement_version": 2,
  "grid_export_price": 0.05,
  "import_member_weights": {"Building_1": 1.0, "Building_2": 2.0},
  "kpis": {"community_local_traded_enabled": true, "community_self_consumption_enabled": true}
}}
```

| Campo | Predefinição | Finalidade |
|---|---:|---|
| `enabled` | `false` | Ativa a liquidação local. |
| `local_price_ratio_to_grid_import` | `0.8` | Preço local em relação ao preço de importação da rede do membro. Um número de 0 a 1. |
| `intra_community_sell_ratio` | sinónimo | Nome antigo da mesma razão. Se as duas chaves forem definidas, têm de ser iguais. |
| `settlement_version` | `1` | `1` ou `2`, como número (`2.0` é aceite, a string `"2"` não). `2` ativa `grid_export_price`; com `1`, as exportações residuais para a rede não recebem nada. |
| `grid_export_price` | `0.0` | EUR/kWh pagos pelas exportações residuais para a rede. Um número finito; um valor diferente de zero exige `"settlement_version": 2`. |
| `tariff_files` | `{}` | Tarifas CSV por membro, `{"<edifício>": "<ficheiro dentro do dataset>"}`. Cada ficheiro tem uma linha por passo global com `grid_export_price`, `community_buy_price` e `community_sell_price` (EUR/kWh) e tem de cobrir o episódio. Um membro com ficheiro usa estes preços em vez da razão e de `grid_export_price`, nas duas versões de liquidação. Resolvido a partir do `root_directory` do schema. |
| `local_trading_enabled` | `true` | `false` mantém a liquidação e os KPIs do mercado mas não troca energia localmente. Booleanos ou `"true"`/`"false"`; `null` significa `false`. |
| `import_member_weights` | `{}` | Pesos para repartir a energia local entre os importadores, `{"<edifício>": peso}`. Cada edifício tem de estar no schema e cada peso tem de ser um número finito, pelo menos 0. |
| `kpis.community_local_traded_enabled` | `true` | Indica `district_energy_grid_community_market_local_traded_total_kwh` e a sua média diária. |
| `kpis.community_self_consumption_enabled` | `true` | Indica `district_solar_self_consumption_community_market_import_share_ratio`. |
| `matching_granularity` | `"aggregate_building"` | O único valor suportado; fica registado nos metadados. |
| `counterfactual` | `"grid_only"` | O único valor suportado: as poupanças comparam cada membro com comprar e vender só à rede. |

Os outros KPIs `community_*` são sempre indicados (zero sem mercado).

### Liquidação em cada passo

Para os membros ativos no passo `t`, com `n_i` o consumo líquido do membro `i`:

- `import_i = max(n_i, 0)`, `export_i = max(-n_i, 0)`; `traded = min(soma das importações, soma das exportações)`, ou 0
  sem troca local.
- Importação local de cada membro: `traded` é repartida entre os importadores na proporção de `import_member_weights`
  (predefinição 1), nunca acima da importação de um membro; o que um membro saturado não absorve vai para os outros. Um
  peso 0 é servido em último lugar. Exportação local: proporcional à exportação de cada exportador.
- Preços: preço de importação `p_imp` do ficheiro `pricing` do membro; preço local de compra e de venda `razão × p_imp`;
  preço da exportação residual `grid_export_price` (0 na versão de liquidação 1). Um ficheiro de tarifas fornece os três
  preços em vez destes.
- `custo_i = (import_i - importação_local_i) × p_imp + importação_local_i × p_buy - exportação_local_i × p_sell - (export_i - exportação_local_i) × p_export`.
- Contrafactual: `max(n_i, 0) × p_imp - export_i × p_export`; as poupanças são o contrafactual menos o custo.
- Saldo do operador: `importação_local_i × p_buy - exportação_local_i × p_sell`, somado em
  `community_operator_balance_total_eur` (positivo quando o mercado retém dinheiro; zero com uma só tarifa partilhada).

Cada lado de uma troca local é valorizado com a tarifa do seu membro, pelo que, com tarifas diferentes, os importadores
podem pagar um valor diferente do que os exportadores recebem. A liquidação altera custos, não o despacho físico.
Consulte os [KPIs do mercado comunitário](kpis_reference.md#mercado-comunitário).

### Validação

As definições são verificadas quando o ambiente é construído, mesmo com `enabled: false`.
Uma chave desconhecida (por exemplo `enable`), uma razão que não seja um número ou que esteja fora de `[0, 1]`, uma
`settlement_version` diferente de `1` ou `2` (incluindo a string `"2"`), um `grid_export_price` diferente de zero sem
`"settlement_version": 2`, e um peso ou ficheiro de tarifas de um edifício que não está no schema lançam `ValueError`.
Os ficheiros de tarifas também são carregados quando o mercado está desativado.

As definições são lidas do schema na construção. Alterar depois os atributos do mercado no ambiente
(`community_market_enabled`, `community_market_sell_ratio`, `community_market_grid_export_price`,
`community_market_import_member_weights`, `community_market_local_enabled`, `community_tariffs`) não é suportado: a
referência BAU nativa é reconstruída a partir do schema, pelo que `evaluate_v2()` com a comparação BAU lança
`ValueError` quando diferem. Para mudar o mercado, edite `schema['community_market']` e construa um ambiente novo.

## Resposta à procura

A resposta à procura é definida pelo dataset e exige `interface: "entity"`. O agente observa pedidos de flexibilidade
ao nível do distrito e responde através das ações físicas que já existem, como armazenamento, VE e cargas flexíveis.

```json
{"demand_response": {
  "enabled": true,
  "requests_file": "demand_response_requests.csv",
  "baseline_method": "rolling_pre_event_average",
  "baseline_window_seconds": 3600,
  "allow_overlapping_requests": false
}}
```

| Campo | Predefinição | Finalidade |
|---|---:|---|
| `enabled` | `false` | Ativa o carregamento dos pedidos, as observações, a liquidação e os KPIs. Com a interface flat lança `ValueError`. |
| `requests_file` | obrigatório quando ativo | Ficheiro CSV ou Parquet, absoluto ou relativo a `root_directory`. |
| `baseline_method` | `rolling_pre_event_average` | O único método: a média do consumo líquido dos membros ativos na janela antes do pedido. |
| `baseline_window_seconds` | `3600` | Duração dessa janela, arredondada para cima a passos inteiros (pelo menos um passo). |
| `allow_overlapping_requests` | `false` | Pedidos sobrepostos lançam `ValueError`; com `true` lançam `NotImplementedError`. Mantenha os pedidos separados. |
| `request_purposes` | `{}` | `{"<request_id>": "service"}` (ou `"stress"`, `"unspecified"`); sobrepõe-se à coluna `purpose` e divide os KPIs de auditoria da resposta à procura. |

Colunas do ficheiro de pedidos:

| Coluna | Unidade/domínio | Significado |
|---|---:|---|
| `request_id` | string | ID único do pedido. Exposto em `meta` das observações. |
| `issuer` | `dso`/`tso` | Entidade que emitiu o pedido. |
| `direction` | `up`/`down` | Perspetiva da carga: `up` aumenta a carga líquida, `down` reduz a carga líquida. |
| `start_time_step`, `end_time_step` | passo global | Janela de ativação inclusiva. |
| `target_power_kw` | kW | Potência alvo do distrito, pelo menos 0. |
| `activation_price_eur_per_kwh` | moeda/kWh | Preço creditado pela entrega. |
| `shortfall_penalty_eur_per_kwh` | moeda/kWh | Penalização pela falta. |
| `tolerance_power_kw` | kW | Coluna opcional; `0` quando a coluna não existe. Uma célula vazia lança erro. |
| `purpose` | `service`/`stress`/`unspecified` | Coluna opcional para os KPIs de auditoria. |

Liquidação em cada passo ativo: potência entregue = real menos baseline (`up`) ou baseline menos real (`down`); falta =
`max(alvo - entregue - tolerância, 0)`; creditado = entregue limitado a [0, alvo]. A receita é a energia creditada ×
preço de ativação; a penalização é a energia em falta × preço de penalização. Um pedido cuja janela de baseline começa
antes do episódio, ou durante o qual entram ou saem membros, é liquidado com zeros.

O bundle `entity_demand_response` acrescenta o pedido à tabela entity `district` (`dr_active`, `dr_direction`,
`dr_target_power_kw`, `dr_baseline_power_kw`, ...). O bundle só acrescenta observações: a liquidação corre sem ele. O
`request_id` ativo está em `observations["meta"]["demand_response"]`.

## Robustez

Os eventos de robustez são definidos pelo dataset e são opcionais. Os eventos de observação e de previsão corrompem
apenas os dados devolvidos ao agente. As recompensas, os KPIs físicos e a liquidação da resposta à procura continuam a
usar o estado real do simulador. Os eventos de ação e de controlo de ativos alteram a ação efetivamente aplicada.

```json
{"robustness": {
  "enabled": true,
  "events_file": "robustness_events.csv",
  "random_seed": 0,
  "missing_replacement_value": -9999.0,
  "modules": {
    "observations": {"enabled": true},
    "forecasts": {"enabled": true},
    "actions": {"enabled": true},
    "assets": {"enabled": true}
  }
}}
```

| Campo | Predefinição | Finalidade |
|---|---:|---|
| `enabled` | `false` | Ativa o carregamento e a aplicação dos eventos. |
| `events_file` | obrigatório quando ativo | Ficheiro CSV ou Parquet, absoluto ou relativo a `root_directory`. |
| `random_seed` | o `random_seed` do ambiente | Semente do ruído dos eventos. Defina-a, ou o `random_seed` da raiz, para ruído repetível. |
| `missing_replacement_value` | `-9999.0` | Valor escrito nos eventos `missing` e na telemetria indisponível. |
| `modules.<observations/forecasts/actions/assets>` | `true` cada | Ativa cada módulo; `{"enabled": bool}` ou um bool. |
| `agent_observation_contract.mode` | `known_faults` | `known_faults`: o agente vê as etiquetas das falhas. `hidden_faults`: todas as características entity não listadas em `features` ficam mascaradas com `-9999.0` e as etiquetas das falhas ficam escondidas; precisa da interface entity. |
| `agent_observation_contract.features` | `{}` | `{"<tabela>": ["<característica>", ...]}`: as características que o agente vê com `hidden_faults`. No máximo uma característica por grandeza medida, e sem nomes `robustness_*` ou `fault_*`. |

Colunas do ficheiro de eventos:

| Coluna | Unidade/domínio | Significado |
|---|---:|---|
| `event_id` | string | ID único do evento, exposto nos metadados. |
| `module` | `observation`/`forecast`/`action`/`asset` | Módulo de perturbação. |
| `target_type` | tipo de entidade | `district`, `building`, `storage`, `charger`, `ev`, `pv` ou `deferrable_appliance`. |
| `target_id` | id ou `*` | Nome/id da entidade alvo, ou todos os alvos compatíveis (vazio significa `*`). |
| `target_feature` | característica/ação | Para ativos use `telemetry`, `control` ou `both` (vazio significa `*`). |
| `start_time_step`, `end_time_step` | passo global | Janela de ativação inclusiva, pelo menos 0. |
| `mode` | enum | Observação/previsão: `missing`, `noise`, `bias`, `stuck`, `clip`; ação: `dropout`, `noise`, `bias`, `stuck`, `delay`, `clip`; ativo: `unavailable`. |
| `value`, `std`, `min_value`, `max_value` | numérico | Parâmetros opcionais do modo (`std` pelo menos 0, `min_value <= max_value`). |
| `replacement_value` | numérico | Valor sentinela opcional para dados em falta/telemetria. |
| `delay_steps` | contagem | Horizonte opcional do atraso das ações, predefinição 1. |
| `event_domain` | enum | Opcional: `ASSET_AVAILABILITY`, `SENSOR_CHANNEL`, `ACTUATOR_CHANNEL`, `COMMUNICATION_LINK`, `VALUE_QUALITY`. |

Com observações entity, o bundle `entity_robustness` acrescenta o diagnóstico à tabela do distrito. Os metadados ficam
em `observations["meta"]["robustness"]`. Consulte a [referência de robustez](robustness_reference.md).

## Interface entity: bundles de observação e previsões derivadas

### `observation_bundles`

Chave da raiz lida apenas com `interface: "entity"`. Cada valor é um bool ou `{"active": bool}`. Um nome de bundle mal
escrito é ignorado, por isso verifique `env.observation_space` depois da construção.

```json
{"observation_bundles": {
  "entity_core_electrical": true,
  "entity_community_operational": true,
  "entity_forecasts_existing": false,
  "entity_forecasts_derived": false,
  "entity_demand_response": false,
  "entity_robustness": false,
  "entity_action_feedback": false,
  "entity_temporal_derived": true
}}
```

| Bundle | Predefinição | Acrescenta |
|---|---:|---|
| `entity_base` | sempre ativo | Características essenciais de carregadores, armazenamento, fases e aparelhos diferíveis. |
| `entity_core_electrical` | `false` | Potência, energia do passo, FV, BESS, VE, eficiência e métricas elétricas dos edifícios. |
| `entity_community_operational` | `false` | Agregados do distrito/comunidade, margens, contagens e versão da topologia. |
| `entity_forecasts_existing` | `false` | Previsões já presentes no dataset. |
| `entity_forecasts_derived` | `false` | Previsões pontuais compactas de preço, carga, FV e procura líquida; consulte `derived_forecasts`. |
| `entity_demand_response` | `false` | Campos do pedido de RP ativo no distrito, baseline congelada e entrega/falta do passo anterior. |
| `entity_robustness` | `false` | Estado de robustez ativo e contadores de corrupção do passo anterior na tabela do distrito. |
| `entity_temporal_derived` | `false` | Desfasamentos curtos, médias móveis e características de calendário em seno/cosseno. |
| `entity_action_feedback` | `false` | Ação pedida, limitada e aplicada, mais as flags do motivo do corte. |

### `derived_forecasts`

Chave da raiz (ao lado de `observation_bundles`, não dentro dela) que configura as características de
`entity_forecasts_derived`.

```json
{"derived_forecasts": {
  "load_pv_method": "daily_persistence",
  "persistence_period_seconds": 86400,
  "cold_start": "current_step",
  "price_source": "publication_aware_day_ahead_market_input",
  "price_horizon_steps": [4, 24, 96]
}}
```

| Chave | Predefinição | Valores | Efeito |
|---|---|---|---|
| `load_pv_method` | `actual_future` | `actual_future`, `daily_persistence` | `actual_future` dá ao agente a carga e a FV futuras reais. `daily_persistence` usa o valor de um período antes (o valor atual quando esse ainda não existe). Use-a em benchmarks causais. `method` é um nome antigo. |
| `persistence_period_seconds` | `86400` | número acima de 0 | Período da persistência, arredondado a passos inteiros. |
| `cold_start` | `current_step` | `current_step` | Recurso quando o histórico é curto demais. |
| `price_source` | `known_future_market_input` | `known_future_market_input`, `publication_aware_day_ahead_market_input`, `daily_persistence` | `known_future_market_input` lê o preço futuro real. `publication_aware_day_ahead_market_input` usa as colunas `electricity_pricing_predicted_*` tal como foram publicadas, e a persistência diária quando um preço ainda não foi publicado. |
| `price_horizon_steps` | `[1, 2, 3]` | três inteiros positivos crescentes | Antecedência, em passos, de `electricity_pricing_predicted_1`, `_2` e `_3`. |

As chaves desconhecidas são ignoradas: um `load_pv_method` mal escrito volta a `actual_future`. As chaves
`price_publication_time_local` e `price_unpublished_fallback`, escritas por alguns geradores de datasets, não são lidas.

## Topologia dinâmica

`topology_mode: "dynamic"` exige `interface: "entity"`. No modo dinâmico todos os edifícios do schema são carregados;
`include: false` torna um edifício um membro inativo até um evento `add_member` (se todos os edifícios estiverem
inativos, o primeiro é ativado).

```json
{"topology_events": [
  {
    "id": "add_pv_b2_t100",
    "time_step": 100,
    "operation": "add_asset",
    "target_member_id": "Building_2",
    "target_asset_type": "pv",
    "target_asset_id": "pv_1",
    "source_member_id": "Building_1",
    "source_asset_id": "pv_1",
    "overrides": {"nominal_power": 80.0}
  }
]}
```

| Campo | Obrigatório | Finalidade |
|---|---|---|
| `id` | não | ID do evento, único; predefinição `topology_event_<índice>`. |
| `time_step` | sim | Passo global em que o evento é aplicado. Os eventos anteriores ao início do episódio são aplicados no seu primeiro passo. |
| `operation` | sim | `add_member`, `remove_member`, `add_asset`, `remove_asset`. |
| `target_member_id` | sim | Edifício alvo. `add_member` com um nome que não está no schema clona `source_member_id` com esse nome. Os carregadores do clone recebem ids próprios. O nome do membro de origem no id passa a ser o do alvo; caso contrário, o identificador que termina o nome do membro (`1` em `Building_1`, `001` em `Member_001`) é substituído pelo do alvo na sua primeira ocorrência isolada, pelo que `charger_1_1` de `Building_1` passa a `charger_19_1` em `Building_19`. Um id que não contenha nenhum dos dois, ou que não mudaria, recebe `_<membro alvo>` no fim; um conflito com outro carregador acrescenta `_2`, `_3`, ... Os eventos de robustez têm de indicar os carregadores do clone pelo novo id. |
| `target_asset_type` | operações de ativos | `charger`, `deferrable_appliance`, `pv`, `electrical_storage`. |
| `target_asset_id` | operações de carregadores e aparelhos diferíveis | Ativo alvo. Não é usado para `pv` e `electrical_storage` (um por edifício). |
| `source_member_id` | não | Edifício de onde se clona; predefinição: o membro alvo nas operações de ativos. |
| `source_asset_id` | não | Ativo a clonar; predefinição `target_asset_id`. |
| `overrides` | não | Atributos definidos no objeto clonado; cada um tem de existir nele. Ignorado nas operações de remoção. |

Acrescentar FV ou armazenamento substitui o que o edifício já tem. Remover um aparelho diferível cancela os ciclos
pendentes/em curso e limpa o consumo futuro. Remover a FV cria uma FV nula. Remover o armazenamento cria uma BESS nula.
Um schema com `topology_events` lança `ValueError` salvo se `topology_mode` for `dynamic`.

Os ficheiros de séries temporais de um membro (simulação energética, carregadores, escadas rolantes) cobrem o horizonte completo, com uma linha por passo do dataset, ou a janela do membro, mais curtos do que o dataset e com a primeira linha no passo do evento `add_member` do membro. Um ficheiro da janela do membro deve cobrir os passos ativos do membro na janela de simulação (caso contrário a última linha é repetida, com um aviso), e um membro que volta a entrar depois de sair precisa de ficheiros do horizonte completo. Um membro que entra a meio do episódio começa a bateria e o armazenamento térmico em `initial_soc`.

## Várias comunidades

`MultiCommunityEnv` não tem chaves próprias no schema. Recebe uma lista de comunidades, cada uma
`{"community_id": ..., "schema": ..., "env_kwargs": {...}, "weight": 1.0}`; outras chaves numa entrada lançam
`ValueError`. Todas as comunidades têm de usar a mesma `interface`, `central_agent`, `seconds_per_time_step`, duração de
episódio, `physics_version`, `random_stream_version` e `baseline_version`. `render_directory` e `render_session_name` em
`env_kwargs` são substituídos pelos do invólucro. Consulte a [referência de várias comunidades](multi_community_reference.md).

## O que cada versão altera

### `physics_version`

| Área | Versão 1 (CityLearn 3.6.0) | Versão 2 (predefinição) |
|---|---|---|
| Potência de descarga da bateria e dos VE | limitada por `capacity_power_curve` | limitada por `discharge_power_curve` |
| Limite dos dispositivos AVAC | energia do passo comparada com kW (limite de uma hora) | potência × duração do passo |
| Dimensionamento do armazenamento térmico | um passo da procura máxima × `safety_factor` | potência máxima da procura × `duration` × `safety_factor` |
| Dimensionamento da FV | assume 8760 linhas horárias | segue a resolução do dataset |
| Bateria durante falhas | estimativa antes do passo | depois do armazenamento térmico, até à carga em ilha que a FV deixa |
| Ordem de alimentação em falha | ordem vehicle-to-building só com `vehicle_to_building` | bateria e VE depois do armazenamento térmico, antes das cargas |
| Margem do serviço elétrico | repartida pelos pedidos em bruto, antes das cargas térmicas | repartida pelas potências viáveis, depois das cargas térmicas e não deslocáveis; a importação liquidada é registada |
| Arranque dos ciclos diferíveis | verifica todo o ciclo com dados futuros | só o passo atual; uma falha suspende o ciclo |
| Predefinições de potência dos carregadores | 50 kW de carga e de descarga | carga = `nominal_power`; descarga 0 |
| Unidade do SOC dos carregadores | inferida valor a valor | inferida por coluna |
| Deriva dos VE ausentes | ignora a perda em repouso | mantém a perda em repouso |
| `set_point_limits` dos ocupantes | não aplicado | aplicado, predefinição `[15, 30]` |
| Características entity de energia até à carga completa | capacidade nominal | capacidade degradada |

### `baseline_version`

| Versão | Baseline dos KPIs (`*_without_storage`) | AVAC do BAU nativo |
|---|---|---|
| 1 | retira a bateria, o armazenamento térmico e o carregamento dos VE; não volta a somar nada | desligado |
| 2 (predefinição) | como a 1 e, depois, volta a somar o carregamento dos VE do BAU com o alvo `full` | fornece a procura de aquecimento e de arrefecimento do dataset nos datasets com ações de AVAC |

Nos datasets sem ações de AVAC, o BAU, a sua definição e a sua identidade são os mesmos nas duas versões. Qualquer outro
valor lança `ValueError`. Com a versão 2, avaliar um dataset com carregadores corre o BAU nativo; se não puder correr, um `ValueError`
sugere `baseline_version=1`. Consulte [Referências](baselines.md#avac-e-a-versão-da-baseline).

### `random_stream_version`

`v1` sorteia os parâmetros dos dispositivos, a deriva dos VE, o comportamento dos ocupantes e as falhas estocásticas
como o CityLearn 3.6.0 (as mesmas falhas em todos os episódios, os mesmos sorteios de ocupantes em todos os edifícios).
`v2` dá a cada objeto, finalidade e episódio o seu próprio fluxo. Consulte o [guia de migração](migration.md#fluxos-aleatórios).

### `settlement_version`

`community_market.settlement_version: 2` só permite um `grid_export_price` diferente de zero; as fórmulas da liquidação
são as mesmas.

## Erros comuns e o que evitar

| Erro | O que acontece | Faça antes |
|---|---|---|
| Um erro de escrita numa chave da raiz (`seconds_per_timestep`) ou em `demand_response`, `robustness`, `derived_forecasts`, `observation_bundles` | Ignorado; é usada a predefinição. | Verifique `env.get_metadata()` e os nomes das observações depois da construção. |
| Escrever booleanos como strings | `"false"` conta como verdadeiro em `rolling_episode_split`, `random_episode_split`, `power_outage.simulate_power_outage`, `stochastic_power_outage` e `vehicle_to_building`. | Use `true` / `false` em JSON. |
| Omitir `random_seed` | Uma semente nova em cada construção; o ruído de robustez e os parâmetros sorteados dos dispositivos mudam. | Defina `random_seed`. |
| Esperar predefinições sorteadas iguais para sementes diferentes | As curvas, as eficiências e os coeficientes de perda das baterias são sorteados. | Defina os atributos. |
| Um intervalo `[mínimo, máximo]` como atributo | `TypeError`. | Indique um número. |
| Ativar `electrical_storage` num edifício sem bateria | `ValueError` na construção. | Liste a ação em `inactive_actions` desse edifício. |
| Ações `cooling_device` / `heating_device` em `citylearn.building.Building` | A ação existe mas não faz nada. | Use um tipo de edifício com dinâmica. |
| Omitir `max_discharging_power` e esperar V2G | A versão 2 da física define-o como 0. | Defina-o explicitamente. |
| Ficheiros de carregadores com valores numéricos em `electric_vehicle_id` | O VE nunca se liga. | Use IDs de texto iguais aos de `electric_vehicles_def`. |
| Uma chave mal escrita em `battery.attributes` de um VE | Ignorada. | Compare `env.electric_vehicles[i].battery` com o schema. |
| Definir `stochastic_power_outage: true` sem modelo | Metade dos passos são falhas. | Use `ReliabilityMetricsPowerOutage`. |
| `electrical_service` e `charging_constraints` ao mesmo tempo | `charging_constraints` é ignorado. | Use `electrical_service`. |
| `set_point_limits`, `dynamics` ou `occupant` em `citylearn.building.Building` | Ignorados. | Use o tipo de edifício correspondente. |
| `null` num limite de `electrical_service` | A simulação trata-o como sem limite, mas o BAU nativo usado por `evaluate()` e `evaluate_v2()` lança `TypeError`. | Deixe a chave de fora para não ter limite. |
| `render_mode` no schema e outro valor como argumento | Prevalece o schema. | Defina-o num só sítio. |
| Alterar `env.community_market_*` depois da construção | `evaluate_v2()` lança erro. | Edite `schema["community_market"]` e construa um ambiente novo. |
| `price_source` ou `load_pv_method` na predefinição num benchmark | O agente lê preços ou cargas futuros. | Use `daily_persistence` ou `publication_aware_day_ahead_market_input`. |
| `noise_std` diferente de zero num edifício sem `pricing` ou `carbon_intensity` | Aparecem preços ou emissões aleatórios. | Acrescente os ficheiros ou mantenha `noise_std` em 0. |
| Passar `electric_vehicles=[...]` para escolher VE | Ignorado. | Use `electric_vehicles_def.<ev>.include`. |
| Baterias de VE acima de 100 kWh com `connected_electric_vehicle_at_charger_battery_capacity` | A observação ultrapassa o limite do espaço. | Normalize pela capacidade, ou deixe-a inativa. |
| `charging_constraint_penalty_coefficient` nos atributos de `Electric_Vehicles_Reward_Function` | `TypeError` na construção: esta recompensa só aceita `weights` e `version`. | Não o indique; o coeficiente mantém a predefinição de 1,0. |
| `request_purposes` escrito como lista | `AttributeError` ao carregar os pedidos. | Escreva um objeto, `{"<request_id>": "service"}`. |
| `start_time_step` / `end_time_step` não inteiros ou negativos num ficheiro de pedidos de resposta à procura | As casas decimais são truncadas com `int()` (3,7 passa a 3), e os valores negativos são aceites. | Escreva índices de linhas de dados inteiros e não negativos. |
| Nomes por dispositivo (`electric_vehicle_storage_<carregador>`, observações por carregador) em `inactive_actions` ou nos argumentos `active_/inactive_observations` | As topologias estática e dinâmica tratam-nos de forma diferente. A topologia estática ignora nomes por dispositivo expandidos em `inactive_actions`; a dinâmica respeita-os, mas recalcula as flags das observações de carregadores, aparelhos diferíveis e baterias a partir do schema, ignorando os argumentos `active_/inactive_observations` e as `inactive_observations` do edifício. | Ative ou desative as características dos dispositivos com os nomes do catálogo em `observations` e `actions`, e verifique `env.observation_names` e `env.action_names`. |

## Schema de referência completo

[`examples/schema_full_reference.json`](https://github.com/citylearn-project/CityLearn/blob/master/examples/schema_full_reference.json)
define todas as opções desta página numa comunidade de dois edifícios do dataset
`citylearn_challenge_2022_phase_all_plus_evs`. Copie-o e altere só o que precisa. O
[guia](schema_full_reference.md) explica cada chave e as alternativas.
