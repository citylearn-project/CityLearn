# Dataset Reference

Esta pagina descreve como construir datasets compativeis com o simulador, incluindo CSV, Parquet, dados reais em kW, EVs, PV absoluto, deferrable appliances e pedidos demand response.

## Formatos Aceites

| Formato | Extensoes | Leitura | Quando usar |
|---|---|---|---|
| CSV | `.csv` | `pandas.read_csv` com `skiprows/nrows` para janelas | Datasets pequenos/medios, facil de inspecionar. |
| Parquet | `.parquet`, `.pq`, `.parq` | `pyarrow.parquet` por batches para janelas | Datasets grandes, 15s, muitos anos/assets. |

CSV e Parquet sao intercambiaveis se:

1. O schema aponta para o novo ficheiro.
2. As colunas tem os mesmos nomes.
3. As unidades sao as mesmas.
4. Os tipos conseguem ser convertidos para os construtores do simulador.

## Datasets públicos e dados locais

Use `DataSet().get_dataset_names()` para consultar o catálogo público. Pode passar
um nome público ao `CityLearnEnv` ou indicar o caminho do seu próprio `schema.json`.
As [notas dos datasets retirados](retired_datasets.md) ficam separadas do guia atual.

## Contrato de Unidades

| Dado | Unidade esperada |
|---|---:|
| Cargas e consumos por step | kWh/step |
| PV em `generation_mode="absolute"` | kWh/step |
| PV em `generation_mode="per_kw"` | W/kW |
| BESS/charger power limits | kW |
| EV required/estimated SOC no ficheiro charger | percent no CSV original, convertido para ratio internamente |
| Precos | currency/kWh |
| Target de pedidos DR | kW |
| Precos e penalizacoes DR | currency/kWh |
| Carbon intensity | kgCO2/kWh |
| Weather temperature | C |
| Irradiance | W/m2 |

Dados reais em potencia devem ser convertidos:

```text
kWh_per_step = kW * seconds_per_time_step / 3600
kW = kWh_per_step * 3600 / seconds_per_time_step
```

Para 15 segundos:

```text
1 kW durante 15s = 1 * 15 / 3600 = 0.0041666667 kWh
```

## `energy_simulation` Columns

| Coluna | Obrigatoria | Unidade | O que e |
|---|---:|---:|---|
| `month` | sim | 1-12 | Mes. |
| `hour` | sim | 1-24 | Hora. |
| `day_type` | sim | 1-8 | Dia da semana/especial. |
| `minutes` | recomendada sub-hora | 0-59 | Minuto. |
| `seconds` | recomendada sub-minuto | 0-59 | Segundo. |
| `indoor_dry_bulb_temperature` | sim | C | Temperatura interior. |
| `non_shiftable_load` | sim | kWh/step | Load nao flexivel. |
| `dhw_demand` | sim | kWh/step | Demanda DHW. |
| `cooling_demand` | sim | kWh/step | Demanda cooling. |
| `heating_demand` | sim | kWh/step | Demanda heating. |
| `solar_generation` | sim | depende PV mode | Input PV. |
| `daylight_savings_status` | nao | 0/1 | DST. |
| `average_unmet_cooling_setpoint_difference` | nao | C | Desconforto cooling. |
| `indoor_relative_humidity` | nao | percent | Humidade interior. |
| `occupant_count` | nao | pessoas | Ocupacao. |
| `indoor_dry_bulb_temperature_cooling_set_point` | nao | C | Setpoint cooling. |
| `indoor_dry_bulb_temperature_heating_set_point` | nao | C | Setpoint heating. |
| `hvac_mode` | nao | enum | 0 off, 1 cooling, 2 heating, 3 auto. |
| `power_outage` | nao | 0/1 | Outage. |
| `comfort_band` | nao | C | Banda conforto. |

Cooling e heating demand nao podem ser positivos no mesmo timestep.

## `weather` Columns

| Coluna | Unidade |
|---|---:|
| `outdoor_dry_bulb_temperature` | C |
| `outdoor_relative_humidity` | percent |
| `diffuse_solar_irradiance` | W/m2 |
| `direct_solar_irradiance` | W/m2 |
| `outdoor_dry_bulb_temperature_predicted_1/2/3` | C |
| `outdoor_relative_humidity_predicted_1/2/3` | percent |
| `diffuse_solar_irradiance_predicted_1/2/3` | W/m2 |
| `direct_solar_irradiance_predicted_1/2/3` | W/m2 |

## `pricing` Columns

| Coluna | Unidade |
|---|---:|
| `electricity_pricing` | currency/kWh |
| `electricity_pricing_predicted_1` | currency/kWh |
| `electricity_pricing_predicted_2` | currency/kWh |
| `electricity_pricing_predicted_3` | currency/kWh |

## `carbon_intensity` Columns

| Coluna | Unidade |
|---|---:|
| `carbon_intensity` | kgCO2/kWh |

## Charger Simulation Columns

| Coluna | Unidade/formato | O que e |
|---|---:|---|
| `electric_vehicle_charger_state` | enum | 1 connected, 2 incoming, 3 away/commuting. |
| `electric_vehicle_id` | string | ID do EV. |
| `electric_vehicle_departure_time` | steps | Steps ate departure. Default interno `-1`. |
| `electric_vehicle_required_soc_departure` | percent | SOC requerido. Convertido para ratio. Default interno `-0.1`. |
| `electric_vehicle_estimated_arrival_time` | steps | Steps ate chegada. Default interno `-1`. |
| `electric_vehicle_estimated_soc_arrival` | percent | SOC estimado na chegada, nas linhas incoming (estado 2). Convertido para ratio. Na ligacao o EV parte da estimativa mais recente nas linhas incoming do mesmo EV imediatamente anteriores, normalmente a ultima; uma estimativa antes de um intervalo away (estado 3) nao e usada. |
| `electric_vehicle_current_soc` | percent ou ratio | Opcional. Telemetria de SOC atual. Na suite REC anual é uma referência neutra de inicialização de fronteira, com serviço a taxa constante, usada apenas quando um episódio começa dentro de uma sessão ocupada; não substitui a evolução do SOC num rollout ininterrupto. |

Para datasets sub-horarios, os campos `*_time` devem estar em numero de timesteps da resolucao do dataset. Ex.: 1 hora em 15s = 240 steps.

## Deferrable Appliances

O formato oficial e esparso: um catalogo de perfis e um schedule de pedidos. Nao repetir o `load_profile` em todas as linhas temporais.

### `cycle_profiles_file`

| Coluna | Unidade | O que e |
|---|---:|---|
| `profile_id` | string | ID do perfil. |
| `duration_steps` | steps | Duracao do ciclo. |
| `total_energy_kwh` | kWh | Soma do perfil. |
| `load_profile` | lista kWh/step | Perfil de energia por step. |

Validacoes:

| Validacao | Regra |
|---|---|
| `profile_id` | Nao vazio e unico. |
| `duration_steps` | Inteiro > 0. |
| `load_profile` | Lista nao vazia, finita, nao negativa. |
| Soma | `sum(load_profile) == total_energy_kwh` dentro de tolerancia. |

### `flexibility_schedule_file`

| Coluna | Unidade | O que e |
|---|---:|---|
| `cycle_id` | string | ID unico do pedido/ciclo. |
| `profile_id` | string | Referencia ao catalogo. |
| `earliest_start_time_step` | timestep global | Primeiro start permitido. |
| `latest_start_time_step` | timestep global | Ultimo start permitido. |
| `deadline_time_step` | timestep global | Deadline de conclusao. |
| `priority` | ratio | Prioridade 0-1, clipped. |
| `must_run` | bool | Se o pedido e obrigatorio. |

Validacoes:

| Validacao | Regra |
|---|---|
| `cycle_id` | Unico e nao vazio. |
| `profile_id` | Tem de existir no catalogo. |
| Janelas | `earliest <= latest`. |
| Deadline | `latest + duration_steps - 1 <= deadline`. |
| Timesteps | Inteiros >= 0 e globais. |

## PV Datasets

| Caso | Schema | Coluna `solar_generation` |
|---|---|---|
| Medicao real/absoluta | `"generation_mode": "absolute"` | `kWh/step`. |
| Perfil normalizado | `"generation_mode": "per_kw"` | `W/kW` por 1 kW instalado. |

Em datasets reais, recomenda-se `absolute`.

## 15 Segundos

Para datasets a 15s:

| Tema | Recomendacao |
|---|---|
| `seconds_per_time_step` | `15`. |
| Cargas em kW | Converter para kWh/step antes de escrever dataset. |
| PV real | Escrever kWh/step e usar `generation_mode="absolute"`. |
| EV countdowns | `*_departure_time` e `*_arrival_time` em steps de 15s. |
| Ficheiros grandes | Preferir Parquet. |
| Teste antes de treino | Correr smoke episode pequeno e `evaluate_v2()`. |
| Exemplo compacto com assets dinamicos | `data/datasets/citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet/schema.json` tem 7 dias a 15s com eventos add/remove de chargers, PV e BESS. |
| Exemplo demand response | `data/datasets/citylearn_challenge_2022_phase_all_demand_response/schema.json` tem buildings 2022 phase-all sem EVs e pedidos DR district. |
| Exemplo robustez | `data/datasets/citylearn_challenge_2022_phase_all_robustness/schema.json` tem buildings 2022 phase-all sem EVs e eventos esparsos de robustez. |

## Bundles de Observacao Entity nos Datasets Incluidos

Os datasets entity a 15 segundos e `citylearn_challenge_2022_phase_all_plus_evs`
ativam todos os bundles de observacoes entity:

| Bundle | Objetivo |
|---|---|
| `entity_core_electrical` | Potencia, energia, SOC e capacidade fisica por asset. |
| `entity_community_operational` | Agregados de potencia, headroom e flexibilidade da comunidade. |
| `entity_forecasts_existing` | Observacoes `*_predicted_*` existentes no dataset. |
| `entity_forecasts_derived` | Forecasts pontuais compactos perfeitos para preco, load, PV e net demand. |
| `entity_temporal_derived` | Calendario robusto e lags curtos. |
| `entity_action_feedback` | Feedback de acao pedida, limitada e aplicada com motivos de clipping. |
| `entity_demand_response` | Pedido demand response district atual, baseline e delivery/shortfall anterior. |
| `entity_robustness` | Estado de robustez ativo e contadores de corrupcao do step anterior. |

Outros schemas mantem o comportamento compativel por default salvo se declararem
`observation_bundles`.

## Ficheiros de Pedidos Demand Response

Datasets de demand response definem `schema["demand_response"]["enabled"] = true`, apontam `requests_file` para CSV ou Parquet, usam `interface="entity"` e normalmente ativam `observation_bundles.entity_demand_response`.

| Coluna | Unidade/dominio | O que e |
|---|---:|---|
| `request_id` | string | ID unico do pedido. |
| `issuer` | `dso`/`tso` | Emissor do pedido. |
| `direction` | `up`/`down` | Perspetiva da carga: `up` aumenta net load, `down` reduz net load. |
| `start_time_step`, `end_time_step` | timestep global | Janela inclusiva de ativacao. |
| `target_power_kw` | kW | Target positivo da comunidade/district. |
| `activation_price_eur_per_kwh` | currency/kWh | Pagamento pela energia entregue creditada. |
| `shortfall_penalty_eur_per_kwh` | currency/kWh | Penalizacao por energia em shortfall. |
| `tolerance_power_kw` | kW | Tolerancia opcional; default `0`. |

Na v1 o simulador calcula uma baseline congelada no inicio do evento a partir dos `baseline_window_seconds` anteriores, liquida apenas steps ativos e guarda historico esparso em vez de arrays densos por timestep.

## Ficheiros de Eventos de Robustez

Datasets de robustez definem `schema["robustness"]["enabled"] = true`, apontam `events_file` para CSV ou Parquet e ligam apenas os modulos que querem estudar. Flat e entity sao suportados; em entity pode ativar-se `observation_bundles.entity_robustness` para diagnostico.

| Coluna | Unidade/dominio | O que e |
|---|---:|---|
| `event_id` | string | ID unico do evento. |
| `module` | enum | `observation`, `forecast`, `action` ou `asset`. |
| `target_type` | tipo de entidade | `district`, `building`, `storage`, `charger`, `ev`, `pv` ou `deferrable_appliance`. |
| `target_id` | id ou `*` | ID/nome da entidade ou todos os targets compativeis. |
| `target_feature` | feature/acao | Para assets usar `telemetry`, `control` ou `both`. |
| `start_time_step`, `end_time_step` | timestep global | Janela inclusiva do evento. |
| `mode` | enum | Modo suportado pelo modulo selecionado. |
| `value`, `std`, `min_value`, `max_value`, `replacement_value`, `delay_steps` | opcional | Parametros do modo. |

## Performance e Loader

| Otimizacao | O que faz |
|---|---|
| Windowed CSV | Usa `skiprows/nrows` para carregar apenas a janela. |
| Windowed Parquet | Le por batches e corta por rows. |
| Shared cache | Reusa weather/pricing/carbon quando varios buildings apontam para o mesmo ficheiro e `noise_std=0`. |
| Parquet | Menos disco, leitura tipada, melhor para 15s. |

## Checklist de Dataset Novo

1. Definir `seconds_per_time_step`.
2. Converter todas as potencias medidas para `kWh/step` onde o simulador espera energia.
3. Decidir PV `absolute` ou `per_kw`.
4. Garantir que EV schedule usa countdowns em timesteps da resolucao.
5. Escrever deferrables em catalogo + schedule.
6. Para demand response, escrever ficheiro esparso de pedidos e ativar entity mode mais `entity_demand_response`.
7. Para robustez, escrever ficheiro esparso de eventos e ativar apenas os modulos necessarios.
8. Preferir Parquet para datasets anuais/sub-minuto.
9. Correr smoke run e `evaluate_v2()`.
10. Correr `audit_physics.py` quando o dataset for novo ou critico.
