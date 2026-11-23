# Referência de datasets

Esta página explica como construir datasets compatíveis com o simulador, incluindo CSV, Parquet, dados reais de potência em kW, VE, FV absoluto, aparelhos diferíveis normalizados e pedidos de resposta à procura.

Versão em inglês: [../dataset_reference.md](../dataset_reference.md).

## Formatos de ficheiro suportados

| Formato | Extensões | Leitor | Quando usar |
|---|---|---|---|
| CSV | `.csv` | `pandas.read_csv` com `skiprows/nrows` para janelas | Datasets pequenos/médios e inspeção fácil. |
| Parquet | `.parquet`, `.pq`, `.parq` | Lotes de `pyarrow.parquet` para janelas | Datasets grandes, dados a 15s, muitos ativos ou execuções de um ano completo. |

CSV e Parquet são intercambiáveis quando o caminho no schema é atualizado e as colunas, unidades e tipos se mantêm equivalentes.

## Datasets públicos e dados locais

Obtenha os nomes disponíveis com `DataSet().get_dataset_names()` ou use a CLI depois
de instalar as suas dependências. Passe um nome de dataset ao `CityLearnEnv` para
descarga e cache automáticas, ou passe o caminho do seu próprio `schema.json` local. Use
`offline=True` com ficheiros disponíveis localmente para desativar os recursos à rede.
`CITYLEARN_OFFLINE=1` torna o modo offline o valor predefinido de `DataSet` e
`CityLearnEnv`, e `CITYLEARN_DATASET_GITHUB_ACCOUNT`, `CITYLEARN_DATASET_REPOSITORY`
e `CITYLEARN_DATASET_TAG` escolhem de onde o `DataSet` descarrega. Cada objeto lê-as
quando é criado; os argumentos explícitos têm prioridade.
Cada primeira descarga usa dois pedidos à API do GitHub; os clientes anónimos têm 60 por
hora. Defina `CITYLEARN_GITHUB_TOKEN` ou `GITHUB_TOKEN` para aumentar esse limite.
Um dataset em cache só é usado quando o seu `schema.json` e todos os ficheiros de
entrada que o schema carrega existem: os ficheiros dos edifícios carregados e os ficheiros
de eventos, tarifas e calendário. Caso contrário, é substituído de uma só vez por uma cópia
local completa ou, com rede, por uma nova descarga; em modo offline sem cópia completa,
`OfflineDataError` indica os ficheiros em falta.

Os [datasets REC de Portugal](portugal_rec_datasets.md) disponibilizam quatro
comunidades a 15 minutos, de 4 a 100 membros, cada uma com cenários de avaliação.

## Contrato de unidades

| Dado | Unidade esperada |
|---|---:|
| Séries de carga e consumo | kWh/passo |
| FV com `generation_mode="absolute"` | kWh/passo |
| FV com `generation_mode="per_kw"` | W/kW |
| Limites de potência de BESS e carregadores | kW |
| SOC requerido/estimado dos VE nos ficheiros de carregadores | percentagem no ficheiro original, convertida internamente para rácio |
| Preços | moeda/kWh |
| Potência alvo dos pedidos de DR | kW |
| Preços e penalizações dos pedidos de DR | moeda/kWh |
| Intensidade carbónica | kgCO2/kWh |
| Temperatura meteorológica | C |
| Irradiância | W/m2 |

Os dados reais de potência têm de ser convertidos antes de escrever colunas de energia:

```text
kWh_per_step = kW * seconds_per_time_step / 3600
kW = kWh_per_step * 3600 / seconds_per_time_step
```

Para 15 segundos:

```text
1 kW during 15s = 1 * 15 / 3600 = 0.0041666667 kWh
```

## Colunas de `energy_simulation`

| Coluna | Obrigatória | Unidade | Significado |
|---|---:|---:|---|
| `month` | sim | 1-12 | Mês. |
| `hour` | sim | 1-24 | Hora. |
| `day_type` | sim | 1-8 | Dia da semana ou dia especial. |
| `minutes` | recomendada abaixo da hora | 0-59 | Minuto. |
| `seconds` | recomendada abaixo do minuto | 0-59 | Segundo. |
| `indoor_dry_bulb_temperature` | sim | C | Temperatura interior. |
| `non_shiftable_load` | sim | kWh/passo | Carga não flexível. |
| `dhw_demand` | sim | kWh/passo | Procura de água quente sanitária. |
| `cooling_demand` | sim | kWh/passo | Procura de arrefecimento. |
| `heating_demand` | sim | kWh/passo | Procura de aquecimento. |
| `solar_generation` | sim | depende do modo FV | Entrada FV. |
| `daylight_savings_status` | não | 0/1 | Hora de verão. |
| `average_unmet_cooling_setpoint_difference` | não | C | Desconforto de arrefecimento. |
| `indoor_relative_humidity` | não | percentagem | Humidade interior. |
| `occupant_count` | não | pessoas | Ocupação. |
| `indoor_dry_bulb_temperature_cooling_set_point` | não | C | Setpoint de arrefecimento. |
| `indoor_dry_bulb_temperature_heating_set_point` | não | C | Setpoint de aquecimento. |
| `hvac_mode` | não | enum | 0 desligado, 1 arrefecimento, 2 aquecimento, 3 automático. |
| `power_outage` | não | 0/1 | Indicador de corte de energia. |
| `comfort_band` | não | C | Banda de conforto. |

A procura de arrefecimento e a de aquecimento não podem ser ambas positivas no mesmo passo de tempo.

## Ficheiros de meteorologia, preços e carbono

| Ficheiro | Colunas obrigatórias | Unidades |
|---|---|---|
| `weather` | `outdoor_dry_bulb_temperature`, `outdoor_relative_humidity`, `diffuse_solar_irradiance`, `direct_solar_irradiance`, mais `*_predicted_1/2/3` | C, percentagem, W/m2 |
| `pricing` | `electricity_pricing`, `electricity_pricing_predicted_1/2/3` | moeda/kWh |
| `carbon_intensity` | `carbon_intensity` | kgCO2/kWh |

## Colunas da simulação de carregadores

| Coluna | Unidade/formato | Significado |
|---|---:|---|
| `electric_vehicle_charger_state` | enum | 1 ligado, 2 a chegar, 3 ausente/em deslocação. |
| `electric_vehicle_id` | string | ID do VE. |
| `electric_vehicle_session_id` | string | ID opcional da sessão de carregamento. Uma mudança separa duas sessões do mesmo VE, incluindo sessões consecutivas. Valores em falta ou vazios não contam como mudança. |
| `electric_vehicle_departure_time` | passos | Passos até à partida. Valor interno predefinido `-1`. |
| `electric_vehicle_required_soc_departure` | percentagem | SOC requerido à partida. Convertido para rácio. |
| `electric_vehicle_estimated_arrival_time` | passos | Passos até à chegada. Valor interno predefinido `-1`. |
| `electric_vehicle_estimated_soc_arrival` | percentagem | SOC estimado à chegada nas linhas a chegar (estado 2). Convertido para rácio. Na ligação, o VE parte da estimativa mais recente na linha imediatamente anterior e nas linhas a chegar contíguas do mesmo VE e da mesma sessão antes dessa linha, normalmente a última linha a chegar. A procura não atravessa uma linha ausente (estado 3), outro VE nem uma mudança de `electric_vehicle_session_id`. Sem essa estimativa, o VE parte da estimativa na sua linha de ligação, se existir, e caso contrário mantém o SOC simulado. As referências de chegada do KPI e da auditoria de partidas usam o mesmo valor. |
| `electric_vehicle_current_soc` | percentagem ou rácio | Telemetria opcional do SOC atual. Na suite REC anual é uma referência neutra de inicialização de fronteira a taxa constante, usada apenas quando um episódio começa dentro de uma sessão ocupada; não substitui o SOC durante uma execução ininterrupta. |

Em datasets abaixo da hora, os campos de contagem decrescente têm de ser expressos em passos de tempo da resolução do dataset. Exemplo: 1 hora a 15s são 240 passos.

## Bundles de observação de entidades nos datasets incluídos

Os datasets de entidades a 15 segundos incluídos e `citylearn_challenge_2022_phase_all_plus_evs` ativam todos os bundles de observação de entidades:

| Bundle | Finalidade |
|---|---|
| `entity_core_electrical` | Potência física, energia, SOC e descritores de capacidade dos ativos. |
| `entity_community_operational` | Agregados de potência, margem e capacidade flexível da comunidade. |
| `entity_forecasts_existing` | Observações `*_predicted_*` existentes no dataset. |
| `entity_forecasts_derived` | Previsões pontuais compactas; a suite REC anual usa persistência diária causal para carga/FV e preços OMIE que respeitam a hora de publicação. |
| `entity_temporal_derived` | Variáveis de calendário robustas e desfasamentos curtos. |
| `entity_action_feedback` | Retorno da ação pedida, limitada e aplicada, com os motivos de corte. |
| `entity_demand_response` | Pedido atual de resposta à procura do distrito, referência e entrega/défice do passo anterior. |
| `entity_robustness` | Estado de robustez ativo e contadores de corrupção do passo anterior. |

Os outros schemas mantêm o comportamento compatível com a predefinição, salvo se declararem `observation_bundles`.

## Ficheiros de pedidos de resposta à procura

Os datasets de resposta à procura definem `schema["demand_response"]["enabled"] = true`, apontam `requests_file` para um ficheiro CSV ou Parquet, usam `interface="entity"` e normalmente ativam `observation_bundles.entity_demand_response`.

| Coluna | Unidade/domínio | Significado |
|---|---:|---|
| `request_id` | string | ID único do pedido. |
| `issuer` | `dso`/`tso` | Emissor do pedido. |
| `direction` | `up`/`down` | Perspetiva da carga: `up` aumenta a carga líquida, `down` reduz a carga líquida. |
| `start_time_step`, `end_time_step` | passo de tempo global | Janela de ativação inclusiva. |
| `target_power_kw` | kW | Potência alvo positiva da comunidade/distrito. |
| `activation_price_eur_per_kwh` | moeda/kWh | Pagamento pela energia entregue creditada. |
| `shortfall_penalty_eur_per_kwh` | moeda/kWh | Penalização pela energia em défice. |
| `tolerance_power_kw` | kW | Tolerância opcional; por omissão `0`. |

O simulador v1 calcula uma referência congelada no início do evento a partir dos `baseline_window_seconds` anteriores, liquida apenas os passos de pedidos ativos e mantém um histórico esparso em vez de escrever arrays densos por passo de tempo.

## Ficheiros de eventos de robustez

Os datasets de robustez definem `schema["robustness"]["enabled"] = true`, apontam `events_file` para um ficheiro CSV ou Parquet e ativam apenas os módulos que pretendem estudar. As interfaces flat e entity são suportadas; os datasets de entidades podem acrescentar `observation_bundles.entity_robustness` para diagnóstico.

| Coluna | Unidade/domínio | Significado |
|---|---:|---|
| `event_id` | string | ID único do evento. |
| `module` | enum | `observation`, `forecast`, `action` ou `asset`. |
| `target_type` | tipo de entidade | `district`, `building`, `storage`, `charger`, `ev`, `pv` ou `deferrable_appliance`. |
| `target_id` | id ou `*` | ID/nome da entidade ou todos os alvos compatíveis. |
| `target_feature` | variável/ação | Para ativos, use `telemetry`, `control` ou `both`. |
| `start_time_step`, `end_time_step` | passo de tempo global | Janela inclusiva do evento. |
| `mode` | enum | Modo suportado pelo módulo selecionado. |
| `value`, `std`, `min_value`, `max_value`, `replacement_value`, `delay_steps` | opcional | Parâmetros do modo. |

## Aparelhos diferíveis

O formato oficial é esparso: um catálogo de perfis de ciclo e um calendário de pedidos de flexibilidade. Não repita o `load_profile` completo em cada passo de tempo.

### `cycle_profiles_file`

| Coluna | Unidade | Significado |
|---|---:|---|
| `profile_id` | string | ID do perfil. |
| `duration_steps` | passos | Duração do ciclo. |
| `total_energy_kwh` | kWh | Soma do perfil. |
| `load_profile` | lista de kWh/passo | Perfil de energia por passo. |

Validação:

| Verificação | Regra |
|---|---|
| `profile_id` | Não vazio e único. |
| `duration_steps` | Inteiro > 0. |
| `load_profile` | Não vazio, finito e não negativo. |
| Soma | `sum(load_profile) == total_energy_kwh` dentro da tolerância. |

### `flexibility_schedule_file`

| Coluna | Unidade | Significado |
|---|---:|---|
| `cycle_id` | string | ID único do pedido/ciclo. |
| `profile_id` | string | Referência ao catálogo de perfis. |
| `earliest_start_time_step` | passo de tempo global | Primeiro início permitido. |
| `latest_start_time_step` | passo de tempo global | Último início permitido. |
| `deadline_time_step` | passo de tempo global | Prazo de conclusão. |
| `priority` | rácio | Prioridade 0-1, limitada a esse intervalo. |
| `must_run` | bool | Indicador de pedido obrigatório. |

Validação:

| Verificação | Regra |
|---|---|
| `cycle_id` | Único e não vazio. |
| `profile_id` | Tem de existir no catálogo. |
| Janelas | `earliest <= latest`. |
| Prazo | `latest + duration_steps - 1 <= deadline`. |
| Passos de tempo | Índices inteiros globais >= 0. |

## Datasets FV

| Caso | Schema | Coluna `solar_generation` |
|---|---|---|
| Produção real/medida | `"generation_mode": "absolute"` | `kWh/step`. |
| Perfil normalizado | `"generation_mode": "per_kw"` | `W/kW` por 1 kW instalado. |

Em datasets de produção real, o modo recomendado é `absolute`.

## Datasets a 15 segundos

| Tema | Recomendação |
|---|---|
| `seconds_per_time_step` | `15`. |
| Dados reais de potência | Converta kW para kWh/passo antes de escrever as colunas de energia do dataset. |
| FV real | Escreva kWh/passo e use `generation_mode="absolute"`. |
| Contagens decrescentes dos VE | Exprima `*_departure_time` e `*_arrival_time` em passos de 15s. |
| Ficheiros grandes | Prefira Parquet. |
| Teste rápido antes do treino | Execute uma janela curta e chame `evaluate_v2()`. |
| Exemplo compacto de ativos dinâmicos | `data/datasets/citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet/schema.json` contém 7 dias a 15s com eventos de adição/remoção de carregadores, FV e BESS. |
| Exemplo de resposta à procura | `data/datasets/citylearn_challenge_2022_phase_all_demand_response/schema.json` contém os edifícios de 2022 phase-all sem VE, mais pedidos de DR do distrito. |
| Exemplo de robustez | `data/datasets/citylearn_challenge_2022_phase_all_robustness/schema.json` contém os edifícios de 2022 phase-all sem VE, mais eventos de robustez esparsos. |

## Desempenho e comportamento do leitor

| Otimização | Efeito |
|---|---|
| CSV por janelas | Usa `skiprows/nrows` para carregar apenas a janela pedida. |
| Parquet por janelas | Lê por lotes e recorta as linhas. |
| Cache partilhada | Reutiliza meteorologia/preços/carbono quando vários edifícios apontam para o mesmo ficheiro e `noise_std=0`. |
| Parquet | Ficheiros mais pequenos, leituras tipadas e melhor comportamento com datasets grandes. |

## Lista de verificação para um dataset novo

1. Defina `seconds_per_time_step`.
2. Converta a potência medida para `kWh/step` onde o simulador espera energia.
3. Escolha FV `absolute` ou `per_kw`.
4. Garanta que os horários dos VE usam contagens decrescentes em passos de tempo do dataset.
5. Escreva os aparelhos diferíveis como catálogo mais calendário.
6. Para resposta à procura, escreva um ficheiro de pedidos esparso e ative o modo entity mais `entity_demand_response`.
7. Para robustez, escreva ficheiros de eventos esparsos e ative apenas os módulos necessários.
8. Prefira Parquet para datasets anuais ou abaixo do minuto.
9. Execute um episódio de teste rápido e `evaluate_v2()`.
10. Execute `audit_physics.py` para novos datasets críticos.
