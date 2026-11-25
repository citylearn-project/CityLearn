# Referência do schema

Esta página documenta o contrato do `schema.json`. O schema é a fonte de verdade para edifícios, dispositivos, VE, aparelhos diferíveis, escadas rolantes, interfaces, bundles de observação, resposta à procura, robustez, topologia dinâmica e configuração do mercado local.

Versão em inglês: [../schema_reference.md](../schema_reference.md).

## Regras gerais

| Regra | Contrato |
|---|---|
| Caminhos | Os caminhos relativos são resolvidos a partir de `root_directory`; os caminhos absolutos são permitidos. |
| Ficheiros tabulares | CSV e Parquet são intercambiáveis quando as colunas e as unidades são equivalentes. |
| Energia | As séries de energia do dataset estão em `kWh/step`. |
| Potência e limites | As potências nominais e os limites estão em `kW`. |
| Preços | Os preços são por `kWh`. |
| Emissões | A intensidade carbónica está em `kgCO2/kWh`. |
| Passos de tempo | As janelas, os prazos e os eventos de topologia usam índices globais de passo de tempo da simulação. |
| Máquinas de lavar antigas | `washing_machines` e `washing_machine_energy_simulation` não são o formato oficial. Use `deferrable_appliances`. |

## Chaves de nível superior

| Chave | Tipo | Obrigatória | Finalidade |
|---|---:|---:|---|
| `root_directory` | string | sim | Pasta base dos ficheiros do dataset. |
| `random_seed` | int/null | não | Semente aleatória global. |
| `random_stream_version` | string | não | Como os fluxos aleatórios são derivados de `random_seed`: `v2` (predefinido, um fluxo `SeedSequence` independente por finalidade, objeto e episódio) ou `v1` (CityLearn 3.6.0 e anteriores). O argumento `random_stream_version` do construtor sobrepõe-se a esta chave. Consulte o [guia de migração](migration.md#fluxos-aleatórios). |
| `central_agent` | bool | sim | Controlador único ou um agente por edifício. |
| `seconds_per_time_step` | number | sim | Duração física de cada passo. |
| `simulation_start_time_step` | int | sim | Primeiro passo de tempo global. |
| `simulation_end_time_step` | int | sim | Último passo de tempo global. |
| `episode_time_steps` | int/list/null | não | Duração do episódio ou janelas de episódio explícitas. |
| `rolling_episode_split` | bool/null | não | Janelas de episódio sequenciais. |
| `random_episode_split` | bool/null | não | Janelas de episódio aleatórias. |
| `time_step_ratio_mode` | `reject`/`compress`/null | não | `reject` (predefinido) recusa um `seconds_per_time_step` diferente do passo do dataset; `compress` mantém o comportamento da 3.6.0, que lê uma linha de dados por passo de controlo e escala as energias. |
| `episode_split_boundary` | `shared`/`disjoint`/null | não | Como se ligam divisões de episódio consecutivas. `shared` (predefinido) começa cada divisão na linha terminal da anterior, pelo que todos os intervalos são simulados; `disjoint` mantém as divisões da 3.6.0, que saltam o intervalo entre dois episódios. |
| `ev_soc_carryover` | bool/null | não | Começa cada VE de um episódio que continua o anterior no tempo (começa na última linha do episódio anterior, ou na linha seguinte) com o SOC que tinha no fim desse episódio, em vez do SOC do calendário. Por omissão `false`. |
| `reward_function` | object/string | sim | Classe da recompensa e kwargs. |
| `observations` | object | sim | Catálogo flat de observações e flags. |
| `actions` | object | sim | Catálogo flat de ações e flags. |
| `buildings` | object | sim | Definições dos edifícios. |
| `agent` | object/string | não | Configuração do agente da CLI. |
| `electric_vehicles_def` | object | se existirem VE | Catálogo de VE. |
| `interface` | `flat`/`entity` | não | Modo de entrada/saída do ambiente. |
| `observation_bundles` | object | não | Bundles adicionais de observações entity. |
| `topology_mode` | `static`/`dynamic` | não | Ativa os eventos de topologia. |
| `topology_events` | list | se dinâmica | Eventos de adição/remoção. |
| `demand_response` | object | não | Pedidos de flexibilidade DSO/TSO e liquidação definidos pelo dataset. |
| `robustness` | object | não | Perturbações de observações, previsões, ações e disponibilidade de ativos definidas pelo dataset. |
| `community_market` | object | não | Mercado local e KPIs do mercado. |
| `ev_departure_within_tolerance` | float | não | Tolerância simétrica de exatidão do SOC à partida, predefinida `0.05`. |
| `ev_departure_service_tolerance` | float | não | Tolerância inferior do SOC à partida para o serviço mínimo aceitável dos VE, predefinida `0.05`. |
| `render_mode` | string | não | `none`, `during` ou `end`. |
| `render_file_format` | `csv`/`parquet` | não | Formato de exportação dos ficheiros de render, KPIs e séries temporais BAU. |
| `render_chunk_size` | int | não | Linhas por bloco de exportação; predefinido `50000` para parquet e `100000` para CSV. |
| `export_kpis_on_episode_end` | bool | não | Exporta os KPIs no fim do episódio. |
| `start_date` | string | não | Data base para render/exportação. |
| `debug_timing` | bool | não | Registos de tempos de execução. |
| `check_observation_limits` | bool | não | Valida os limites das observações. |
| `physics_invariant_checks` | bool | não | Verificações de invariantes físicos em tempo de execução. |
| `physics_version` | int | não | Versão da física, `1` ou `2` (predefinida). `1` reproduz a física do CityLearn 3.6.0; consulte o [guia de migração](migration.md#versão-da-física). O argumento `physics_version` de `CityLearnEnv` tem precedência. |
| `baseline_version` | int | não | Definição da baseline por omissão dos KPIs e do AVAC do BAU nativo, `1` ou `2` (predefinida). `2` retira a bateria, o armazenamento térmico e o carregamento dos VE da execução controlada e volta a somar o carregamento dos VE do BAU nativo com o alvo `'full'`, e o seu BAU nativo fornece a procura de aquecimento e de arrefecimento do dataset; `1` não volta a somar nada e o seu BAU envia zero às ações de AVAC, como no CityLearn 3.6.0. Consulte o [guia de migração](migration.md#carregamento-dos-ve-na-baseline-por-omissão) e [AVAC e a versão da baseline](baselines.md#avac-e-a-versão-da-baseline). O argumento `baseline_version` de `CityLearnEnv` tem precedência. |
| `metrics_log_interval` | int | não | Cadência de registo das métricas de execução. |

### Chaves de calendário e metadados do dataset

Estas chaves descrevem o relógio do dataset e a sua proveniência; os schemas das
REC portuguesas (`pt_rec_*`) usam várias delas. As cinco primeiras mudam a forma
como o relógio do dataset é lido; as restantes são metadados descritivos que o
simulador não lê, mantidos para que um dataset possa ser rastreado até à sua
origem.

| Chave | Tipo | Efeito |
|---|---:|---|
| `time_axis.calendar_file` | string | Calendário canónico com as colunas `time_step` e `timestamp_utc` (e, opcionalmente, `timestamp_local`), uma linha regular por linha do dataset. Define o passo do dataset e os carimbos temporais das séries renderizadas e exportadas, salvo se `start_date` for passado a `CityLearnEnv`. |
| `timezone` | string | Fuso horário IANA do calendário, por exemplo `Europe/Lisbon`. Os carimbos temporais exportados são convertidos de UTC para este fuso; um nome desconhecido dá erro no carregamento. Sem calendário, fica apenas registado. |
| `dataset_seconds_per_time_step` | number | Passo declarado do dataset, em segundos, para dados cujas colunas de calendário não o permitem obter. Tem de coincidir com o calendário. |
| `dataset_contract_version` | string | Versão do contrato de dados do dataset. Um valor que comece por `portugal-native` faz de `shared/calendar.parquet` o calendário quando `time_axis` está ausente; caso contrário, é metadado. |
| `terminal_observation_padding` | bool | Permite que os ficheiros terminem uma linha antes da janela e repete a última linha apenas como observação terminal, que nunca é simulada. Predefinido `false`. |
| `dataset_id`, `dataset_family` | string | Metadados: identificadores do dataset. |
| `experimental_design` | object | Metadados: o desenho de avaliação para o qual o dataset foi construído (fatores, finalidade, etiquetas). |
| `native_compatibility` | object | Metadados: o commit do motor e as verificações com que o dataset foi validado. |
| `_derivation`, `_derived_from` | object/string | Metadados: como um dataset derivado foi produzido a partir da sua origem. |

## `observations`

```json
"hour": {
  "active": true,
  "shared_in_central_agent": true
}
```

| Campo | Tipo | Predefinido | Finalidade |
|---|---:|---:|---|
| `active` | bool | `false` | Ativa a observação flat. |
| `shared_in_central_agent` | bool | `false` | Inclui uma observação comum uma única vez nos vetores do agente central. |

Os nomes de observações com o prefixo `electric_vehicle_` são expandidos por carregador. Os nomes com o prefixo `deferrable_appliance_` são expandidos por aparelho diferível. Os nomes com o prefixo `escalator_` são expandidos por escada rolante.

## `actions`

```json
"electrical_storage": {
  "active": true
}
```

| Campo | Tipo | Predefinido | Finalidade |
|---|---:|---:|---|
| `active` | bool | `false` | Ativa a ação. |

`electric_vehicle_storage` expande para `electric_vehicle_storage_{charger_id}`. `deferrable_appliance` expande para `deferrable_appliance_{appliance_id}`. `escalator` expande para `escalator_{escalator_id}`.

## `observation_bundles`

Configuração exclusiva da interface entity:

```json
"observation_bundles": {
  "entity_core_electrical": true,
  "entity_community_operational": true,
  "entity_forecasts_existing": false,
  "entity_forecasts_derived": false,
  "entity_demand_response": false,
  "entity_robustness": false,
  "entity_action_feedback": false,
  "entity_temporal_derived": true
}
```

| Bundle | Predefinido | Adiciona |
|---|---:|---|
| `entity_base` | sempre ativo | Features essenciais de carregadores, armazenamento, fases e aparelhos diferíveis. |
| `entity_core_electrical` | `false` | Potência, energia por passo, FV, BESS, VE, eficiência e métricas elétricas dos edifícios. |
| `entity_community_operational` | `false` | Agregados do distrito/comunidade, margens, contagens e versão da topologia. |
| `entity_forecasts_existing` | `false` | Previsões já presentes no dataset. |
| `entity_forecasts_derived` | `false` | Previsões pontuais compactas de preço, carga, FV e procura líquida. |
| `entity_demand_response` | `false` | Campos do pedido DR atual do distrito, referência congelada e entrega/défice do passo anterior. |
| `entity_robustness` | `false` | Estado de robustez ativo e contadores de corrupção do passo anterior na tabela do distrito. |
| `entity_temporal_derived` | `false` | Atrasos curtos, médias móveis e features de calendário sin/cos. |
| `entity_action_feedback` | `false` | Feedback da ação pedida, limitada e aplicada, mais flags com a razão do corte. |

As fontes de carga/FV do bundle derivado são configuráveis:

```json
"derived_forecasts": {
  "load_pv_method": "daily_persistence",
  "persistence_period_seconds": 86400,
  "cold_start": "current_step",
  "price_source": "publication_aware_day_ahead_market_input",
  "price_publication_time_local": "13:00",
  "price_unpublished_fallback": "daily_persistence",
  "price_horizon_steps": [4, 24, 96]
}
```

`actual_future` continua a ser o valor predefinido de carga/FV, por
compatibilidade com versões anteriores. Use `daily_persistence` em benchmarks de
algoritmos causais que não podem expor os valores futuros reais da carga ou do FV.

## `buildings`

```json
"buildings": {
  "Building_1": {
    "include": true,
    "type": "citylearn.building.Building",
    "energy_simulation": "Building_1.csv",
    "weather": "weather.parquet",
    "pricing": "pricing.csv",
    "carbon_intensity": "carbon.csv"
  }
}
```

| Chave | Tipo | Obrigatória | Finalidade |
|---|---:|---:|---|
| `include` | bool | não | Inclui o edifício inicialmente. Na topologia dinâmica pode começar inativo. |
| `type` | string | não | Caminho da classe do edifício, por exemplo `citylearn.building.Building`. |
| `energy_simulation` | string | sim | Ficheiro principal de entrada de cargas, calendário e FV. |
| `weather` | string/object | sim | Ficheiro meteorológico. |
| `pricing` | string/object | sim | Ficheiro de preços. |
| `carbon_intensity` | string/object | não | Ficheiro de intensidade carbónica. |
| `inactive_observations` | list | não | Desativa observações neste edifício. |
| `inactive_actions` | list | não | Desativa ações neste edifício. |
| `cooling_device`, `heating_device`, `dhw_device` | object | datasets AVAC | Dispositivos de utilização final. |
| `cooling_storage`, `heating_storage`, `dhw_storage` | object | datasets AVAC | Armazenamentos térmicos. |
| `electrical_storage` | object | não | BESS do edifício. |
| `pv` | object | não | FV do edifício. |
| `chargers` | object | não | Carregadores de VE. |
| `deferrable_appliances` | object | não | Aparelhos diferíveis normalizados. |
| `charging_constraints` | object | não | Limites de carregamento por edifício/fase. |
| `electrical_service` | object | não | Limites de importação/exportação do serviço; consulte [Serviço elétrico](#serviço-elétrico). |
| `equity_group` | string | não | Grupo usado pelos KPIs de equidade. |
| `dynamics` | object | não | Modelo da dinâmica da temperatura interior. |
| `occupant` | object | não | Modelo de interação dos ocupantes. |
| `power_outage` | object | não | Configuração das falhas de energia. |
| `set_point_hold_time_steps` | int | não | Tempo de manutenção para a interação dos ocupantes. |
| `set_point_limits` | [float, float] | não | Intervalo, em °C, para onde um ocupante pode mover um set point de aquecimento ou arrefecimento; por omissão `[15, 30]`. Versão 2 da física e seguintes; ver o [guia de migração](../migration.md#occupant-set-point-limits). |

Chaves de `power_outage`:

| Chave | Tipo | Predefinido | Finalidade |
|---|---:|---|---|
| `simulate_power_outage` | bool | `false` | Simula falhas da rede neste edifício. |
| `stochastic_power_outage` | bool | `false` | Gera as falhas a partir de `stochastic_power_outage_model` em vez da coluna `power_outage`. |
| `stochastic_power_outage_model` | object | `PowerOutage` | Classe e atributos do modelo de falhas. |
| `vehicle_to_building` | bool | `false` | Permite que um VE ligado descarregue para o edifício durante uma falha (apoio vehicle-to-building), até à carga em ilha que o FV e a bateria deixam por cobrir. As features entity do carregador `can_discharge` e `available_discharge_power_kw` indicam a capacidade de descarga do veículo durante a falha. A descarga pode deixar o veículo abaixo do SOC exigido à partida. |

## Secções de dispositivos

Forma comum:

```json
"electrical_storage": {
  "type": "citylearn.energy_model.Battery",
  "attributes": {
    "capacity": 50.0,
    "nominal_power": 25.0,
    "depth_of_discharge": 0.9
  },
  "autosize": false,
  "autosize_attributes": {}
}
```

| Campo | Tipo | Finalidade |
|---|---:|---|
| `type` | string | Caminho da classe Python. |
| `attributes` | object | Kwargs do construtor. |
| `autosize` | bool | Chama o dimensionamento automático do edifício, quando disponível. |
| `autosize_attributes` | object | Kwargs do dimensionamento automático. |

Classes comuns:

| Classe | Atributos principais |
|---|---|
| `citylearn.energy_model.HeatPump` | `nominal_power`, `efficiency`, `target_heating_temperature`, `target_cooling_temperature`. |
| `citylearn.energy_model.ElectricHeater` | `nominal_power`, `efficiency`. |
| `citylearn.energy_model.StorageTank` | `capacity`, `efficiency`, `loss_coefficient`, `initial_soc`, `max_output_power`, `max_input_power`. |
| `citylearn.energy_model.Battery` | `capacity`, `nominal_power`, `capacity_loss_coefficient`, `power_efficiency_curve`, `capacity_power_curve` (carregamento), `discharge_power_curve` (descarga, versão da física 2), `depth_of_discharge`. |
| `citylearn.energy_model.PV` | `nominal_power`, `generation_mode`. |

## FV

```json
"pv": {
  "type": "citylearn.energy_model.PV",
  "attributes": {
    "nominal_power": 120.0,
    "generation_mode": "absolute"
  }
}
```

| `generation_mode` | Aliases | Interpreta `energy_simulation.solar_generation` como | Fórmula |
|---|---|---|---|
| `per_kw` | `profile`, `w_per_kw` | Perfil normalizado por kW instalado, em `W/kW`. | `generation_kwh = nominal_power * value / 1000 * seconds_per_time_step / 3600`. |
| `absolute` | `absolute_kwh`, `kwh`, `kwh_step`, `energy` | Produção absoluta já em `kWh/step`. | `generation_kwh = value`. |

Use `absolute` para produção real medida ou para séries de energia geradas por um conversor. Use `per_kw` para perfis FV normalizados.

Por exemplo, `nominal_power=4.0` e um valor de 1000 W/kW dão 4,0 kWh num passo horário e
1,0 kWh num passo de 900 s.

## Bateria

```json
"electrical_storage": {
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
}
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
| `loss_coefficient` | rácio por hora | sorteado em [0,001, 0,009] | Perda em repouso da energia armazenada; a fórmula por passo está nas [definições dos VE](#definições-dos-ve). |

Uma predefinição indicada como "sorteada" é tirada do fluxo aleatório do ambiente quando o
atributo é omitido, pelo que depende da semente e de `random_stream_version`. Os datasets do
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

## Serviço elétrico

`buildings.<name>.electrical_service` define os limites da ligação do edifício à rede. Os
limites são potência ativa em kW; `null`, uma chave ausente ou `Infinity` significa sem limite.

```json
"electrical_service": {
  "mode": "single_phase",
  "limits": {
    "total": {"import_kw": 17.25, "export_kw": 6.9},
    "per_phase": {"L1": {"import_kw": 17.25, "export_kw": 6.9}}
  },
  "available_grid_power": {"filename": "available_grid_power.csv", "column": "Building_1"},
  "observations": {"available_grid_power": true}
}
```

| Campo | Tipo | Finalidade |
|---|---:|---|
| `mode` | `single_phase`, `three_phase` | Tipo de serviço. Os serviços monofásicos só têm `L1`. |
| `default_split` | `balanced`, `L1`, `L2`, `L3` | Repartição por fases da carga sem ligação a uma fase. |
| `limits.total.import_kw`, `limits.total.export_kw` | kW | Capacidade estática da ligação. |
| `limits.per_phase.<L1/L2/L3>.import_kw`, `export_kw` | kW | Limites estáticos por fase. |
| `available_grid_power` | caminho ou objeto | Série opcional da importação disponível em cada passo; ver abaixo. |
| `observations.headroom`, `observations.headroom_export` | bool | Expõe as observações das margens de importação/exportação. Predefinido true. |
| `observations.violation` | bool | Expõe `charging_constraint_violation_kwh`. Predefinido true. |
| `observations.phase_encoding` | bool | Expõe a atribuição de fase dos carregadores em codificação one-hot. Predefinido false. |
| `observations.available_grid_power` | bool | Expõe a observação `available_grid_power` quando há uma série definida. Predefinido true. |

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
[`power_outage`](#buildings) para um apagão. Os limites por fase continuam estáticos. A
observação `available_grid_power` indica o limite do intervalo seguinte; as observações das
margens descrevem o último intervalo executado, pelo que refletem o limite então em vigor.

## Carregadores

```json
"chargers": {
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
}
```

| Campo | Unidade | Finalidade |
|---|---:|---|
| `charger_simulation` | path ou `{"source": "external"}` | Schedule temporal do charger, ou `{"source": "external"}` para um schedule escrito em runtime por um [fornecedor de mobilidade](mobility_provider.md). |
| `soc_unit` | `percent`, `fraction` | Opcional, ao lado de `charger_simulation`: a unidade das colunas de SOC do ficheiro de horário. Se for omitido, é inferido uma vez por coluna a partir do ficheiro inteiro (ver [unidade do SOC](dataset_reference.md#unidade-do-soc)). |
| `attributes.nominal_power` | kW | Potência nominal. Valor predefinido de `max_charging_power`. |
| `attributes.charger_type` | qualquer | Etiqueta descritiva (por exemplo 0 para AC, 1 para DC). Não tem efeito na simulação. |
| `attributes.max_charging_power` | kW | Limite superior de carregamento. Por omissão é `nominal_power`, ou 50 kW com um aviso. |
| `attributes.min_charging_power` | kW | Potência mínima técnica de carregamento. Por omissão 0. |
| `attributes.max_discharging_power` | kW | Limite superior de V2G. Por omissão 0: o carregador não descarrega a menos que este campo seja definido (um aviso indica-o). |
| `attributes.min_discharging_power` | kW | Potência mínima técnica de V2G. Por omissão 0. |
| `attributes.efficiency` | rácio | Eficiência fixa/predefinida, usada num sentido sem curva de eficiência. Por omissão 1.0, com um aviso quando é usada. |
| `attributes.charge_efficiency_curve` | rácio vs potência normalizada | Curva opcional de eficiência de carregamento. |
| `attributes.discharge_efficiency_curve` | rácio vs potência normalizada | Curva opcional de eficiência de descarga. |
| `attributes.phase_connection` | `L1`, `L2`, `L3`, `all_phases` | Atribuição da fase elétrica. |

Qualquer outro nome em `attributes` lança um `ValueError` que indica o carregador e sugere o
nome válido mais próximo, pelo que um `max_discharge_power` mal escrito deixa de cair num valor
predefinido ([#369](https://github.com/citylearn-project/CityLearn/issues/369)). Uma chave do
carregador que não seja `type`, `charger_simulation`, `attributes`, `autosize`, `noise_std` ou
`soc_unit` é ignorada com um aviso que sugere a chave mais próxima. Com a versão
de física 1, um `max_charging_power` ou `max_discharging_power` omitido vale 50 kW, como no
CityLearn 3.6.0, e `nominal_power` não é usado.
| `start_delay_seconds` | s | Opcional. Tempo após a ligação do veículo antes de a energia fluir. |
| `setpoint_delay_seconds` | s | Opcional. Atraso até o comando de um passo ter efeito. |
| `ramp_up_kw_per_second` | kW/s | Opcional. Taxa máxima de subida do valor absoluto da potência. |
| `ramp_down_kw_per_second` | kW/s | Opcional. Taxa máxima de descida do valor absoluto da potência. |
| `stop_delay_seconds` | s | Opcional. A transferência termina este tempo antes de uma partida conhecida. |

Os últimos cinco atributos modelam a [dinâmica das sessões de carga](charger_session_dynamics.md); omitidos,
a potência comandada aplica-se durante todo o tempo de ligação.

O schedule de um charger externo começa ausente durante todo o episódio; o fornecedor liga, anuncia e
liberta veículos enquanto o episódio corre. Chargers externos não são suportados com `topology_mode="dynamic"`.
Ver [fornecedores externos de mobilidade](mobility_provider.md).

## Definições dos VE

```json
"electric_vehicles_def": {
  "EV_1": {
    "type": "citylearn.electric_vehicle.ElectricVehicle",
    "include": true,
    "battery": {
      "attributes": {
        "capacity": 60.0,
        "nominal_power": 50.0,
        "initial_soc": 0.4,
        "depth_of_discharge": 0.9
      }
    }
  }
}
```

| Campo | Finalidade |
|---|---|
| `type` | Caminho da classe do VE. |
| `include` | Inclui o VE no conjunto inicial. |
| `external` | `true` quando um [fornecedor de mobilidade](mobility_provider.md) comunica o SOC do EV: sem deriva aleatória de SOC enquanto está ausente. Default `false`. |
| `battery.attributes` | Kwargs de `Battery`. |

A perda em repouso da bateria dos VE está intencionalmente isolada dos valores predefinidos do armazenamento estacionário:

- Um `battery.attributes.loss_coefficient` ausente ou `null` assume `0.0` nos VE.
- Os valores explícitos de `loss_coefficient` dos VE são interpretados como rácios de perda horária.
- Todas as implementações de `StorageDevice`, incluindo `Battery` estacionária e `StorageTank`, convertem os valores horários de `loss_coefficient` numa perda efetiva por passo, composta ao longo do passo: `1 - (1 - loss_coefficient) ** (seconds_per_time_step / 3600)`.
- As gamas predefinidas dos parâmetros do armazenamento estacionário não mudam.

## Aparelhos diferíveis

```json
"deferrable_appliances": {
  "washer_1": {
    "type": "citylearn.energy_model.DeferrableAppliance",
    "cycle_profiles_file": "deferrables/washer_profiles.csv",
    "flexibility_schedule_file": "deferrables/washer_schedule.csv",
    "attributes": {
      "trigger_threshold": 0.5
    }
  }
}
```

| Campo | Obrigatório | Finalidade |
|---|---:|---|
| `type` | não | Classe do aparelho. Predefinida: `citylearn.energy_model.DeferrableAppliance`. |
| `cycle_profiles_file` | sim | Catálogo dos perfis físicos dos ciclos. |
| `flexibility_schedule_file` | sim | Pedidos/janelas de flexibilidade. |
| `attributes.trigger_threshold` | não | Limiar da ação de arranque (predefinido `0.5`; `action > threshold` é interpretado como ON). |

## Escadas rolantes (interface flat)

```json
"escalators": {
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
}
```

| Campo | Obrigatório | Finalidade |
|---|---:|---|
| `type` | não | Classe da escada rolante. Predefinida: `citylearn.energy_model.Escalator`. |
| `simulation` | sim | CSV com uma linha por passo de simulação. |
| `attributes.standby_power`, `slow_power`, `normal_power` | sim | Potências em kW, não negativas; têm de ser não decrescentes. |
| `attributes.minimum_state_steps` | não | Permanência mínima num estado; predefinida `1`. |
| `attributes.service_threshold_passengers` | não | Procura de passageiros acima da qual o serviço é exigido; predefinida `0.5`. |

O CSV exige `time_step`, `passengers_from_trains_15min`,
`background_pedestrians_15min`, `passengers_expected_15min`, `people_detected`,
`arriving_trains`, `departing_trains`, `minutes_to_next_train` e `available`.
`passengers_expected_15min` tem de ser igual à soma das duas componentes de
passageiros. O suporte das escadas rolantes está atualmente exposto através da
interface flat.

## Topologia dinâmica

`topology_mode="dynamic"` exige `interface="entity"`.

```json
"topology_events": [
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
]
```

| Campo | Tipo | Finalidade |
|---|---:|---|
| `id` | string | ID do evento. |
| `time_step` | int | Passo de tempo global em que o evento é aplicado. |
| `operation` | enum | `add_member`, `remove_member`, `add_asset`, `remove_asset`. |
| `target_member_id` | string | Edifício alvo. |
| `target_asset_type` | enum | `charger`, `deferrable_appliance`, `pv`, `electrical_storage`. |
| `target_asset_id` | string | Ativo alvo. |
| `source_member_id` | string | Edifício de origem para a clonagem. |
| `source_asset_id` | string | Ativo de origem para a clonagem. |
| `overrides` | object | Atributos aplicados depois da clonagem. |

Remover um aparelho diferível cancela os ciclos pendentes/em curso e limpa o consumo futuro. Remover o FV cria um FV nulo. Remover o armazenamento cria um BESS nulo.

Os ficheiros de séries temporais de um membro (energy simulation, carregadores, escadas rolantes) são de horizonte completo, com uma linha por passo de tempo do dataset, ou ficheiros de janela do membro, mais curtos do que o dataset, cuja primeira linha é o passo de tempo do evento `add_member` do membro. Um ficheiro de janela do membro deve cobrir os passos ativos do membro na janela de simulação (caso contrário, a última linha é repetida, com um aviso), e um membro que volta a entrar depois de ter saído precisa de ficheiros de horizonte completo. Um membro que entra a meio do episódio começa a bateria e o armazenamento térmico em `initial_soc`.

## Resposta à procura

A resposta à procura v1 é definida pelo dataset e exclusiva da interface entity. O agente observa pedidos de flexibilidade ao nível do distrito e responde através das ações físicas que já existem, como armazenamento, VE e cargas flexíveis.

```json
"demand_response": {
  "enabled": true,
  "requests_file": "demand_response_requests.csv",
  "baseline_method": "rolling_pre_event_average",
  "baseline_window_seconds": 3600,
  "allow_overlapping_requests": false
}
```

| Campo | Predefinido | Finalidade |
|---|---:|---|
| `enabled` | `false` | Ativa o carregamento dos pedidos de resposta à procura, as observações, a liquidação e os KPIs. |
| `requests_file` | obrigatório quando ativo | Ficheiro CSV ou Parquet relativo a `root_directory` ou à pasta do schema. |
| `baseline_method` | `rolling_pre_event_average` | Método da referência. É o único método da v1. |
| `baseline_window_seconds` | `3600` | Janela de histórico anterior ao evento usada para calcular a referência congelada do evento. |
| `allow_overlapping_requests` | `false` | Os pedidos sobrepostos são rejeitados na v1. |

Colunas do ficheiro de pedidos:

| Coluna | Unidade/domínio | Significado |
|---|---:|---|
| `request_id` | string | ID único do pedido. Exposto no `meta` das observações. |
| `issuer` | `dso`/`tso` | Entidade que emitiu o pedido. |
| `direction` | `up`/`down` | Perspetiva da carga: `up` aumenta a carga líquida, `down` reduz a carga líquida. |
| `start_time_step`, `end_time_step` | passo de tempo global | Janela de ativação inclusiva. |
| `target_power_kw` | kW | Potência alvo positiva do distrito. |
| `activation_price_eur_per_kwh` | moeda/kWh | Preço creditado pela entrega. |
| `shortfall_penalty_eur_per_kwh` | moeda/kWh | Penalização pelo défice. |
| `tolerance_power_kw` | kW | Tolerância opcional; predefinida `0`. |

Quando estiver ativa, ative o bundle de observação:

```json
"observation_bundles": {
  "entity_demand_response": true
}
```

As features numéricas são adicionadas à tabela entity `district`. O `request_id` ativo fica em `observations["meta"]["demand_response"]`, e não na matriz numérica.

## Robustez

A robustez v1 é definida pelo dataset e totalmente opcional. Os eventos de observação e de previsão corrompem apenas o payload devolvido ao agente. As recompensas, os KPIs físicos e a liquidação da resposta à procura continuam a usar o estado real do simulador. Os eventos de ação e de controlo de ativos alteram a ação efetivamente aplicada.

```json
"robustness": {
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
}
```

| Campo | Predefinido | Finalidade |
|---|---:|---|
| `enabled` | `false` | Ativa o carregamento e a aplicação dos eventos de robustez. |
| `events_file` | obrigatório quando ativo | Ficheiro CSV ou Parquet relativo a `root_directory` ou à pasta do schema. |
| `random_seed` | `0` | Semente determinística para o ruído dos eventos. |
| `missing_replacement_value` | `-9999.0` | Sentinela predefinida para valores de observação/telemetria em falta. |
| `modules.*.enabled` | `true` quando a robustez está ativa | Ativa individualmente observações, previsões, ações e ativos. |

Colunas do ficheiro de eventos:

| Coluna | Unidade/domínio | Significado |
|---|---:|---|
| `event_id` | string | ID único do evento, exposto nos metadados. |
| `module` | `observation`/`forecast`/`action`/`asset` | Módulo de perturbação. |
| `target_type` | tipo de entidade | `district`, `building`, `storage`, `charger`, `ev`, `pv` ou `deferrable_appliance`. |
| `target_id` | id ou `*` | Nome/id da entidade alvo, ou todos os alvos compatíveis. |
| `target_feature` | feature/ação | Para ativos, use `telemetry`, `control` ou `both`. |
| `start_time_step`, `end_time_step` | passo de tempo global | Janela de ativação inclusiva. |
| `mode` | enum | Observação/previsão: `missing`, `noise`, `bias`, `stuck`, `clip`; ação: `dropout`, `noise`, `bias`, `stuck`, `delay`, `clip`; ativo: `unavailable`. |
| `value`, `std`, `min_value`, `max_value` | numérico | Parâmetros opcionais do modo. |
| `replacement_value` | numérico | Sentinela opcional para valores em falta/telemetria. |
| `delay_steps` | contagem | Horizonte opcional do atraso da ação. |

Com observações entity, ative os diagnósticos, se necessário:

```json
"observation_bundles": {
  "entity_robustness": true
}
```

Os metadados ficam expostos em `observations["meta"]["robustness"]`.

## Mercado comunitário

```json
"community_market": {
  "enabled": true,
  "local_price_ratio_to_grid_import": 0.8,
  "import_member_weights": {
    "Building_1": 1.0,
    "Building_2": 2.0
  },
  "kpis": {
    "community_local_traded_enabled": true,
    "community_self_consumption_enabled": true
  }
}
```

| Campo | Predefinido | Finalidade |
|---|---:|---|
| `enabled` | `false` | Ativa a liquidação local. |
| `local_price_ratio_to_grid_import` | `0.8` | Preço local relativo ao preço de importação da rede. Um número de 0 a 1. |
| `intra_community_sell_ratio` | alias | Nome antigo do mesmo rácio. Se as duas chaves estiverem definidas, têm de ser iguais. |
| `settlement_version` | `1` | `1` ou `2`, como número (`2.0` é aceite, a string `"2"` não). `2` ativa `grid_export_price`; com `1`, as exportações residuais para a rede não são remuneradas. |
| `grid_export_price` | `0.0` | EUR/kWh pagos pelas exportações residuais para a rede. Um número finito; um valor diferente de zero exige `"settlement_version": 2`. |
| `tariff_files` | `{}` | Tarifas CSV por membro, `{"<building>": "<file inside the dataset>"}`. Cada ficheiro tem uma linha por passo de tempo global com `grid_export_price`, `community_buy_price` e `community_sell_price` (EUR/kWh) e tem de cobrir o episódio. Um membro com ficheiro usa estes preços em vez do rácio e de `grid_export_price`. |
| `local_trading_enabled` | `true` | `false` mantém a liquidação e os KPIs do mercado, mas não troca energia localmente. Aceita booleanos ou `"true"`/`"false"`. |
| `import_member_weights` | `{}` | Pesos para repartir a energia local entre os importadores, `{"<building>": peso}`. Cada edifício tem de estar no schema e cada peso tem de ser um número finito maior ou igual a 0. |
| `kpis.community_local_traded_enabled` | `true` | Ativa o KPI de energia transacionada localmente. |
| `kpis.community_self_consumption_enabled` | `true` | Ativa o KPI da quota de importação local. |
| `matching_granularity` | `"aggregate_building"` | O único valor suportado; fica registado nos metadados. |
| `counterfactual` | `"grid_only"` | O único valor suportado: as poupanças comparam cada membro com comprar e vender só à rede. Escrito pelo gerador das suites anuais de REC. |

## Combinações importantes

As definições são verificadas quando o env é construído, mesmo com
`enabled: false`. Uma chave desconhecida (por exemplo `enable`), um rácio que
não é um número ou está fora de `[0, 1]`, um `settlement_version` que não seja o
valor `1` ou `2` (incluindo a string `"2"`), um `grid_export_price` diferente
de zero sem `"settlement_version": 2`, e um peso ou ficheiro de tarifa de um
edifício que não está no schema dão `ValueError`. As versões anteriores
ignoravam estas definições ou substituíam-nas por valores predefinidos. A chave
antiga `intra_community_sell_ratio` é um alias.

As definições são lidas do schema na construção. Alterar depois os atributos do
mercado no env (`community_market_enabled`,
`community_market_sell_ratio`,
`community_market_grid_export_price`, `community_market_import_member_weights`,
`community_market_local_enabled`, `community_tariffs`) não é suportado: a
referência BAU nativa é reconstruída a partir do schema, por isso
`evaluate_v2()` com a comparação BAU dá `ValueError` quando diferem. Para mudar
o mercado, altere `schema['community_market']` e construa um novo env. A liquidação local valoriza as
importações e exportações dos membros no mesmo passo de tempo; não altera o
despacho físico dos dispositivos.

Cada lado de uma troca local é valorizado com a tarifa do respetivo membro.
Quando os membros têm tarifas de rede ou `tariff_files` diferentes, os
importadores podem pagar um valor diferente do que os exportadores recebem pela
mesma energia. A diferença é reportada como `community_operator_balance_total_eur`
(positiva quando o mercado retém dinheiro); é zero com uma única tarifa partilhada.

| Caso | Configuração |
|---|---|
| Treino flat clássico | Omita `interface` ou use `interface="flat"`; topologia estática. |
| Entity/GNN/Transformer | `interface="entity"` mais os bundles de observação pretendidos. |
| Topologia dinâmica | `interface="entity"`, `topology_mode="dynamic"`, `topology_events`. |
| Resposta à procura | `interface="entity"`, `demand_response.enabled=true`, bundle `entity_demand_response`. |
| Robustez | Qualquer interface, `robustness.enabled=true`; adicione `entity_robustness` para diagnósticos entity. |
| Medições FV reais | `pv.attributes.generation_mode="absolute"`. |
| Dados de 15 segundos | `seconds_per_time_step=15` e ficheiros já nessa cadência. |
| Datasets grandes | Prefira caminhos Parquet com as mesmas colunas. |
