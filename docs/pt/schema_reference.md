# Schema Reference

Esta pagina documenta o contrato do `schema.json`. O schema e a fonte oficial para construir buildings, dispositivos, EVs, appliances, modos de interface, demand response, robustez, topology dynamic, bundles e mercado.

## Regras Gerais

| Regra | Contrato |
|---|---|
| Caminhos | Sao relativos a `root_directory`, exceto quando sao absolutos. |
| Ficheiros tabulares | CSV e Parquet sao aceites de forma intercambiavel quando as colunas sao equivalentes. |
| Energia | Series energeticas sao `kWh/step`. |
| Potencia e limites | Potencias e limites sao `kW`. |
| Precos | Precos sao por `kWh`. |
| Emissoes | Carbon intensity e `kgCO2/kWh`. |
| Timesteps | Campos de janela, deadline e topology usam indices globais da simulacao. |
| Legacy washing machines | `washing_machines` e `washing_machine_energy_simulation` nao sao o formato oficial. Usar `deferrable_appliances`. |

## Top Level

| Chave | Tipo | Obrigatoria | O que faz |
|---|---:|---:|---|
| `root_directory` | string | sim | Pasta base dos ficheiros do dataset. |
| `random_seed` | int/null | nao | Semente global. |
| `random_stream_version` | string | nao | Como os fluxos aleatórios são derivados de `random_seed`: `v2` (predefinição, um fluxo `SeedSequence` independente por finalidade, objeto e episódio) ou `v1` (CityLearn 3.6.0 e anteriores). O argumento `random_stream_version` do construtor sobrepõe-se. |
| `central_agent` | bool | sim | Controlador unico ou multi-agent por building. |
| `seconds_per_time_step` | number | sim | Duracao fisica de cada step. |
| `simulation_start_time_step` | int | sim | Primeiro timestep global. |
| `simulation_end_time_step` | int | sim | Ultimo timestep global. |
| `episode_time_steps` | int/list/null | nao | Tamanho ou janelas de episodio. |
| `rolling_episode_split` | bool/null | nao | Episodios sequenciais. |
| `random_episode_split` | bool/null | nao | Episodios aleatorios. |
| `time_step_ratio_mode` | `reject`/`compress`/null | nao | `reject` (por omissao) recusa um `seconds_per_time_step` diferente do step do dataset; `compress` mantem o comportamento da 3.6.0 (uma linha de dados por step de controlo, energias escaladas). |
| `episode_split_boundary` | `shared`/`disjoint`/null | nao | Como se ligam splits consecutivos. `shared` (por omissao) comeca cada split na linha terminal do anterior, pelo que todos os intervalos sao simulados; `disjoint` mantem os splits da 3.6.0, que saltam o intervalo entre dois episodios. |
| `reward_function` | object/string | sim | Classe do reward e kwargs. |
| `observations` | object | sim | Catalogo flat de observacoes e flags. |
| `actions` | object | sim | Catalogo flat de acoes e flags. |
| `buildings` | object | sim | Definicao de cada building. |
| `agent` | object/string | nao | Configuracao de agente para CLI. |
| `electric_vehicles_def` | object | se houver EVs | Catalogo de EVs. |
| `interface` | `flat`/`entity` | nao | Modo de I/O do ambiente. |
| `observation_bundles` | object | nao | Bundles adicionais da entity interface. |
| `topology_mode` | `static`/`dynamic` | nao | Ativa eventos dinamicos. |
| `topology_events` | list | se dynamic | Eventos add/remove. |
| `demand_response` | object | nao | Pedidos DSO/TSO de flexibilidade e settlement orientados por dataset. |
| `robustness` | object | nao | Perturbacoes orientadas por dataset para observacoes, forecasts, acoes e assets. |
| `community_market` | object | nao | Mercado local e KPIs associados. |
| `evaluation_window` | bool/object | nao | Janela local recorrente opt-in para `evaluate_v2()` e exportacao de KPIs; ver [Janela de Avaliacao](#janela-de-avaliacao). |
| `ev_departure_within_tolerance` | float | nao | Tolerancia simetrica de accuracy do SOC no departure, default `0.05`. |
| `ev_departure_service_tolerance` | float | nao | Tolerancia inferior de servico EV minimo no departure, default `0.05`. |
| `render_mode` | string | nao | `none`, `during`, `end`. |
| `render_file_format` | `csv`/`parquet` | nao | Formato dos exports de render, KPIs e serie temporal BAU. |
| `render_chunk_size` | int | nao | Linhas por chunk de export; default `50000` para parquet e `100000` para CSV. |
| `export_kpis_on_episode_end` | bool | nao | Export de KPIs no fim do episodio. |
| `start_date` | string | nao | Data base de render/export. |
| `debug_timing` | bool | nao | Logs de tempo runtime. |
| `check_observation_limits` | bool | nao | Valida bounds de observacoes. |
| `physics_invariant_checks` | bool | nao | Checks de invariantes fisicos. |
| `physics_version` | int | nao | Versao da fisica, `1` ou `2` (predefinida). `1` reproduz a fisica do CityLearn 3.6.0; ver o [guia de migracao](../migration.md#physics-version). O argumento `physics_version` do `CityLearnEnv` tem precedencia. |
| `metrics_log_interval` | int | nao | Periodicidade de logs. |

### Chaves de calendario e metadados do dataset

Estas chaves descrevem o relogio do dataset e a sua proveniencia; os schemas
das REC portuguesas (`pt_rec_*`) usam varias delas. As cinco primeiras mudam a forma como o relogio do dataset e lido; as restantes
sao metadados descritivos que o simulador nao le, mantidos para que um dataset
possa ser rastreado ate a sua origem.

| Chave | Tipo | Efeito |
|---|---:|---|
| `time_axis.calendar_file` | string | Calendario canonico com as colunas `time_step` e `timestamp_utc` (e opcionalmente `timestamp_local`), uma linha regular por linha do dataset. Define o step do dataset e os timestamps das series renderizadas e exportadas, salvo se `start_date` for passado ao `CityLearnEnv`. |
| `timezone` | string | Fuso horario IANA do calendario, p. ex. `Europe/Lisbon`. Os timestamps exportados sao convertidos de UTC para este fuso; um nome desconhecido da erro no carregamento. Sem calendario, apenas fica registado. |
| `dataset_seconds_per_time_step` | number | Step do dataset declarado em segundos, para dados cujas colunas de calendario nao o permitem obter. Tem de coincidir com o calendario. |
| `dataset_contract_version` | string | Versao do contrato de dados do dataset. Um valor que comece por `portugal-native` faz de `shared/calendar.parquet` o calendario quando `time_axis` nao existe; caso contrario, e metadado. |
| `terminal_observation_padding` | bool | Permite que os ficheiros terminem uma linha antes da janela e repete a ultima linha apenas como observacao terminal, que nunca e simulada. Predefinido `false`. |
| `dataset_id`, `dataset_family` | string | Metadados: identificadores do dataset. |
| `experimental_design` | object | Metadados: o desenho de avaliacao para que o dataset foi construido (fatores, objetivo, etiquetas). |
| `native_compatibility` | object | Metadados: o commit do motor e as verificacoes com que o dataset foi validado. |
| `_derivation`, `_derived_from` | object/string | Metadados: como um dataset derivado foi produzido a partir da origem. |

## `observations`

Cada entrada tem o formato:

```json
"hour": {
  "active": true,
  "shared_in_central_agent": true
}
```

| Campo | Tipo | Default | O que faz |
|---|---:|---:|---|
| `active` | bool | `false` | Liga a observacao no flat mode. |
| `shared_in_central_agent` | bool | `false` | Se `central_agent=true`, a observacao aparece uma vez no vetor central quando e comum. |

Observacoes especiais com prefixo `electric_vehicle_` sao expandidas por charger. Observacoes com prefixo `deferrable_appliance_` sao expandidas por appliance.

## `actions`

Cada entrada tem o formato:

```json
"electrical_storage": {
  "active": true
}
```

| Campo | Tipo | Default | O que faz |
|---|---:|---:|---|
| `active` | bool | `false` | Liga a acao. |

A acao `electric_vehicle_storage` e expandida para `electric_vehicle_storage_{charger_id}`. A acao `deferrable_appliance` e expandida para `deferrable_appliance_{appliance_id}`.

## `observation_bundles`

Usado apenas na entity interface.

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

| Bundle | Default | O que adiciona |
|---|---:|---|
| `entity_base` | sempre ativo | Features estaticas/essenciais de charger, storage, phases e deferrables. |
| `entity_core_electrical` | `false` | Potencias, energia por step, PV, BESS, EV, eficiencia e metricas eletricas por building. |
| `entity_community_operational` | `false` | Agregados district/community, headrooms, counts e topology version. |
| `entity_forecasts_existing` | `false` | Forecasts ja existentes no dataset. |
| `entity_forecasts_derived` | `false` | Forecasts pontuais compactos para preco, load, PV e net demand. |
| `entity_demand_response` | `false` | Estado do pedido DR district, baseline congelado e delivery/shortfall do step anterior. |
| `entity_robustness` | `false` | Estado de robustez e contadores de corrupcao do step anterior na tabela district. |
| `entity_temporal_derived` | `false` | Lags, medias curtas e calendario sin/cos. |
| `entity_action_feedback` | `false` | Acao pedida, limitada e aplicada, mais flags de clipping. |

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

| Chave | Tipo | Obrigatoria | O que faz |
|---|---:|---:|---|
| `include` | bool | nao | Inclui building inicialmente. Em topology dynamic pode comecar inativo. |
| `type` | string | nao | Classe do building. Ex.: `citylearn.building.Building`, `LSTMDynamicsBuilding`. |
| `energy_simulation` | string | sim | Ficheiro principal de cargas, calendario e PV input. |
| `weather` | string/object | sim | Ficheiro meteorologico. |
| `pricing` | string/object | sim | Ficheiro de precos. |
| `carbon_intensity` | string/object | nao | Ficheiro de emissoes. |
| `inactive_observations` | list | nao | Desliga observacoes neste building. |
| `inactive_actions` | list | nao | Desliga acoes neste building. |
| `cooling_device` | object | sim em datasets HVAC | Dispositivo de cooling. |
| `heating_device` | object | sim em datasets HVAC | Dispositivo de heating. |
| `dhw_device` | object | sim em datasets HVAC | Dispositivo de hot water. |
| `cooling_storage` | object | sim em datasets HVAC | Storage termico cooling. |
| `heating_storage` | object | sim em datasets HVAC | Storage termico heating. |
| `dhw_storage` | object | sim em datasets HVAC | Storage termico DHW. |
| `electrical_storage` | object | nao | BESS do building. |
| `pv` | object | nao | PV do building. |
| `chargers` | object | nao | Chargers associados ao building. |
| `deferrable_appliances` | object | nao | Appliances deferiveis normalizados. |
| `charging_constraints` | object | nao | Limites de charging por building/fase. |
| `electrical_service` | object | nao | Limites de import/export por fase e total; ver [Servico eletrico](#servico-eletrico). |
| `equity_group` | string | nao | Grupo usado nos KPIs de equity. |
| `dynamics` | object | nao | Modelo dinamico para indoor temperature. |
| `occupant` | object | nao | Modelo occupant interaction. |
| `power_outage` | object | nao | Config de outage. |
| `set_point_hold_time_steps` | int | nao | Hold time para occupant interaction. |

Chaves de `power_outage`:

| Chave | Tipo | Padrao | O que faz |
|---|---:|---|---|
| `simulate_power_outage` | bool | `false` | Simula falhas da rede neste edificio. |
| `stochastic_power_outage` | bool | `false` | Gera as falhas com `stochastic_power_outage_model` em vez da coluna `power_outage`. |
| `stochastic_power_outage_model` | object | `PowerOutage` | Classe e atributos do modelo de falhas. |
| `vehicle_to_building` | bool | `false` | Deixa um VE ligado descarregar para o edificio durante uma falha (apoio vehicle-to-building), ate a carga isolada que o PV e a bateria nao cobrem. As features entity do carregador `can_discharge` e `available_discharge_power_kw` indicam a capacidade de descarga do veiculo durante a falha. A descarga pode deixar o veiculo abaixo do SOC pedido para a partida. |

## Secoes de Dispositivo

Padrao comum:

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

| Campo | Tipo | O que faz |
|---|---:|---|
| `type` | string | Classe Python a instanciar. |
| `attributes` | object | Kwargs do construtor. |
| `autosize` | bool | Se `true`, chama autosizer do building quando existir. |
| `autosize_attributes` | object | Parametros do autosizer. |

### Classes comuns

| Classe | Atributos principais |
|---|---|
| `citylearn.energy_model.HeatPump` | `nominal_power`, `efficiency`, `target_heating_temperature`, `target_cooling_temperature`. |
| `citylearn.energy_model.ElectricHeater` | `nominal_power`, `efficiency`. |
| `citylearn.energy_model.StorageTank` | `capacity`, `efficiency`, `loss_coefficient`, `initial_soc`, `max_output_power`, `max_input_power`. |
| `citylearn.energy_model.Battery` | `capacity`, `nominal_power`, `capacity_loss_coefficient`, `power_efficiency_curve`, `capacity_power_curve` (carga), `discharge_power_curve` (descarga, versao da fisica 2), `depth_of_discharge`. |
| `citylearn.energy_model.PV` | `nominal_power`, `generation_mode`. |

## PV

```json
"pv": {
  "type": "citylearn.energy_model.PV",
  "attributes": {
    "nominal_power": 120.0,
    "generation_mode": "absolute"
  }
}
```

| `generation_mode` | Aliases | Interpreta `energy_simulation.solar_generation` como | Formula |
|---|---|---|---|
| `per_kw` | `profile`, `w_per_kw` | Perfil por 1 kW instalado em `W/kW`. | `generation_kwh = nominal_power * value / 1000`. |
| `absolute` | `absolute_kwh`, `kwh`, `kwh_step`, `energy` | Geracao absoluta ja em `kWh/step`. | `generation_kwh = value`. |

Usa `absolute` quando o dataset vem de medicao real ou de conversor externo ja em energia por step. Usa `per_kw` quando o dataset contem perfil normalizado por capacidade instalada.

## Servico eletrico

`buildings.<name>.electrical_service` define os limites da ligacao a rede do edificio. Os
limites sao potencia ativa em kW; `null`, chave ausente ou `Infinity` significa sem limite.
Campos: `mode` (`single_phase`/`three_phase`), `default_split`, `limits.total`,
`limits.per_phase`, `available_grid_power` e `observations` (`headroom`,
`headroom_export`, `violation`, `phase_encoding`, `available_grid_power`).

### Potencia de rede disponivel

`available_grid_power` indica um ficheiro CSV ou Parquet com uma linha por timestep,
alinhado com `energy_simulation`, como nome de ficheiro ou `{"filename": ..., "column": ...}`.
Sem `column`, usa a coluna com o nome do edificio e depois `available_grid_power`. Os valores
sao a potencia (kW, nao energia por step) que o edificio pode importar nesse timestep.

O limite de importacao em vigor e o menor entre `limits.total.import_kw` e o valor da serie.
Um valor vazio aplica so o limite estatico; sem `import_kw` e um erro. Os valores devem ser
finitos e nao negativos. Os carregadores de EV e a bateria sao limitados primeiro; a carga
nao controlavel continua servida e conta como violacao do servico eletrico. 0 kW nao isola o
edificio; use `power_outage` para um apagao. A observacao `available_grid_power` indica o
limite do proximo intervalo; o headroom descreve o ultimo intervalo executado.

## Chargers

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

| Campo | Unidade | O que faz |
|---|---:|---|
| `charger_simulation` | path | Schedule temporal do charger. |
| `max_charging_power` | kW | Limite superior de carga. |
| `min_charging_power` | kW | Minimo tecnico de carga. |
| `max_discharging_power` | kW | Limite V2G. |
| `min_discharging_power` | kW | Minimo tecnico V2G. |
| `efficiency` | ratio | Eficiencia fixa. |
| `charge_efficiency_curve` | ratio vs potencia normalizada | Curva opcional de eficiencia de carga. |
| `discharge_efficiency_curve` | ratio vs potencia normalizada | Curva opcional de eficiencia de descarga. |
| `phase_connection` | `L1`, `L2`, `L3`, `all_phases` | Fase eletrica do charger. |

## EV Definitions

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

| Campo | O que faz |
|---|---|
| `type` | Classe EV. |
| `include` | Inclui EV no pool inicial. |
| `battery.attributes` | Kwargs de `Battery`. |

O standby loss das baterias EV fica isolado dos defaults de storage estacionario:

- `battery.attributes.loss_coefficient` ausente ou `null` usa default `0.0` em EVs.
- Valores EV explicitos de `loss_coefficient` sao interpretados como ratios de perda horaria.
- Todas as implementacoes de `StorageDevice`, incluindo `Battery` estacionaria e `StorageTank`, convertem valores horarios de `loss_coefficient` para perda efetiva por step com `loss_coefficient * seconds_per_time_step / 3600`.
- Os ranges default de parametros de storage estacionario ficam inalterados.

## Deferrable Appliances

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

| Campo | Obrigatorio | O que faz |
|---|---:|---|
| `type` | nao | Classe appliance. Default: `citylearn.energy_model.DeferrableAppliance`. |
| `cycle_profiles_file` | sim | Catalogo de perfis fisicos dos ciclos. |
| `flexibility_schedule_file` | sim | Pedidos/janelas de flexibilidade. |
| `attributes.trigger_threshold` | nao | Threshold de start (default `0.5`; `action > threshold` e interpretado como ON). |

## Dynamic Topology

`topology_mode="dynamic"` requer `interface="entity"`.

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

| Campo | Tipo | O que faz |
|---|---:|---|
| `id` | string | ID do evento. |
| `time_step` | int | Timestep global onde o evento e aplicado. |
| `operation` | enum | `add_member`, `remove_member`, `add_asset`, `remove_asset`. |
| `target_member_id` | string | Building alvo. |
| `target_asset_type` | enum | `charger`, `deferrable_appliance`, `pv`, `electrical_storage`. |
| `target_asset_id` | string | Asset alvo. |
| `source_member_id` | string | Building fonte para clones. |
| `source_asset_id` | string | Asset fonte para clones. |
| `overrides` | object | Atributos a aplicar depois do clone. |

Remover `deferrable_appliance` cancela ciclos pendentes/running e limpa consumo futuro. Remover PV cria PV zero. Remover storage cria BESS zero.

Os ficheiros de series temporais de um membro (energy simulation, chargers, escalators) sao full-horizon, com uma linha por timestep do dataset, ou ficheiros de janela do membro, mais curtos que o dataset, cuja primeira linha e o timestep do evento `add_member`. Um ficheiro de janela deve cobrir os steps ativos do membro na janela de simulacao (caso contrario a ultima linha e repetida, com um aviso), e um membro que volta a entrar depois de sair precisa de ficheiros full-horizon. Um membro que entra a meio do episodio comeca a bateria e o armazenamento termico em `initial_soc`.

## Demand Response

Demand response v1 e orientado por dataset e entity-only. O agente observa pedidos de flexibilidade ao nivel district e responde atraves das acoes fisicas existentes, como storage, EVs e cargas flexiveis.

```json
"demand_response": {
  "enabled": true,
  "requests_file": "demand_response_requests.csv",
  "baseline_method": "rolling_pre_event_average",
  "baseline_window_seconds": 3600,
  "allow_overlapping_requests": false
}
```

| Campo | Default | O que faz |
|---|---:|---|
| `enabled` | `false` | Ativa leitura de pedidos DR, observacoes, settlement e KPIs. |
| `requests_file` | obrigatorio quando ativo | Ficheiro CSV ou Parquet relativo a `root_directory` ou a pasta do schema. |
| `baseline_method` | `rolling_pre_event_average` | Metodo de baseline. Este e o unico metodo v1. |
| `baseline_window_seconds` | `3600` | Janela historica pre-evento usada para calcular baseline congelado. |
| `allow_overlapping_requests` | `false` | Pedidos sobrepostos sao rejeitados na v1. |

Colunas do ficheiro de pedidos:

| Coluna | Unidade/dominio | O que e |
|---|---:|---|
| `request_id` | string | ID unico do pedido. Exposto em `meta`. |
| `issuer` | `dso`/`tso` | Entidade que emitiu o pedido. |
| `direction` | `up`/`down` | Perspetiva da carga: `up` aumenta net load, `down` reduz net load. |
| `start_time_step`, `end_time_step` | timestep global | Janela inclusiva de ativacao. |
| `target_power_kw` | kW | Target positivo ao nivel district. |
| `activation_price_eur_per_kwh` | currency/kWh | Preco creditado pela entrega. |
| `shortfall_penalty_eur_per_kwh` | currency/kWh | Penalizacao por shortfall. |
| `tolerance_power_kw` | kW | Tolerancia opcional; default `0`. |

Quando ativo, ativar tambem o bundle:

```json
"observation_bundles": {
  "entity_demand_response": true
}
```

As features numericas entram na tabela entity `district`. O `request_id` ativo fica em `observations["meta"]["demand_response"]`, nao numa matriz numerica.

## Robustez

Robustez v1 e orientada por dataset e totalmente opcional. Eventos de observation e forecast degradam apenas o payload recebido pelo agente. Rewards, KPIs fisicos e settlement de demand response continuam a usar o estado real do simulador. Eventos de action e asset-control alteram a acao efetivamente aplicada.

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

| Campo | Default | O que faz |
|---|---:|---|
| `enabled` | `false` | Ativa leitura e aplicacao de eventos de robustez. |
| `events_file` | obrigatorio quando ativo | Ficheiro CSV ou Parquet relativo a `root_directory` ou a pasta do schema. |
| `random_seed` | `0` | Semente deterministica para ruido dos eventos. |
| `missing_replacement_value` | `-9999.0` | Sentinela default para observacoes/telemetria em falta. |
| `modules.*.enabled` | `true` quando robustez ativa | Liga separadamente observations, forecasts, actions e assets. |

Colunas do ficheiro de eventos:

| Coluna | Unidade/dominio | O que e |
|---|---:|---|
| `event_id` | string | ID unico exposto em metadata. |
| `module` | `observation`/`forecast`/`action`/`asset` | Modulo perturbado. |
| `target_type` | tipo de entidade | `district`, `building`, `storage`, `charger`, `ev`, `pv` ou `deferrable_appliance`. |
| `target_id` | id ou `*` | Nome/id da entidade, ou todos os targets compativeis. |
| `target_feature` | feature/acao | Para assets usar `telemetry`, `control` ou `both`. |
| `start_time_step`, `end_time_step` | timestep global | Janela inclusiva de ativacao. |
| `mode` | enum | Observation/forecast: `missing`, `noise`, `bias`, `stuck`, `clip`; action: `dropout`, `noise`, `bias`, `stuck`, `delay`, `clip`; asset: `unavailable`. |
| `value`, `std`, `min_value`, `max_value` | numerico | Parametros opcionais do modo. |
| `replacement_value` | numerico | Sentinela opcional para missing/telemetry. |
| `delay_steps` | count | Atraso opcional de acao. |

Em entity observations, ativar diagnostico se necessario:

```json
"observation_bundles": {
  "entity_robustness": true
}
```

Metadata fica em `observations["meta"]["robustness"]`.

## Community Market

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

| Campo | Default | O que faz |
|---|---:|---|
| `enabled` | `false` | Ativa settlement local. |
| `local_price_ratio_to_grid_import` | `0.8` | Preco local relativo ao preco de import grid. |
| `intra_community_sell_ratio` | alias | Nome legacy para o mesmo ratio. |
| `settlement_version` | `1` | `2` ativa o `grid_export_price`; com `1`, a exportação residual não é remunerada. |
| `grid_export_price` | `0.0` | EUR/kWh pagos pela exportação residual quando `settlement_version` é `2`. Tem de ser finito. |
| `tariff_files` | `{}` | Tarifas CSV por membro, `{"<edifício>": "<ficheiro no dataset>"}`, com uma linha por passo global e as colunas `grid_export_price`, `community_buy_price` e `community_sell_price` (EUR/kWh), cobrindo o episódio. Substituem o rácio e o `grid_export_price` para esse membro. |
| `local_trading_enabled` | `true` | `false` mantém a liquidação e os KPIs do mercado mas não troca energia localmente. Aceita booleanos ou `"true"`/`"false"`. |
| `import_member_weights` | `{}` | Pesos para repartir energia local entre importadores. |
| `kpis.community_local_traded_enabled` | `true` | Ativa KPI v2 de energia local transacionada. |
| `kpis.community_self_consumption_enabled` | `true` | Ativa KPI v2 de import share local. |

Cada lado de uma troca local usa a tarifa do seu membro. Com tarifas diferentes entre
membros, os importadores podem pagar um valor diferente do que os exportadores
recebem pela mesma energia; a diferença aparece em
`community_operator_balance_total_eur` (positiva quando o mercado retém dinheiro) e é
zero com uma tarifa única.

## Janela de Avaliacao

`evaluation_window` ativa KPIs opt-in numa janela local recorrente (`*_energy_grid_window_average_power_*_kw` e `*_ev_window_net_exchange_control_kwh`; ver [referencia de KPIs](kpis_reference.md#janela-de-avaliação-recorrente)) sem alterar a fisica da simulacao nem os nomes dos KPIs quando os limites mudam.

```json
"evaluation_window": {
  "enabled": true,
  "start": "16:00",
  "end": "19:00",
  "timezone": "scenario_local"
}
```

| Campo | Default | O que faz |
|---|---:|---|
| `enabled` | `false` (`true` quando `start` ou `end` e definido) | Ativa os KPIs da janela recorrente em `evaluate_v2()` e nos exports. Passar `"evaluation_window": true` ativa a janela inicial `16:00:00` a `19:00:00`. |
| `start` | `"16:00:00"` | Inicio da janela em formato 24h `"HH:MM"` ou `"HH:MM:SS"`, incluindo fronteiras sub-horarias. |
| `end` | `"19:00:00"` | Fim da janela em formato 24h `"HH:MM"` ou `"HH:MM:SS"`. Quando `start > end` (por exemplo `"22:00"` a `"06:00"`), a janela atravessa a meia-noite. |
| `timezone` | `schema.timezone` ou `"scenario_local"` | Fuso horario IANA usado ao converter um calendario UTC `TimeAxis`, ou `"scenario_local"` para colunas de calendario locais do dataset. |

Os valores resolvidos de `start`, `end` e `timezone` ficam registados em `exported_kpis.manifest.json`. Quando ambas as execucoes ativam `evaluation_window` com limites ou fusos horarios diferentes, `compare_manifests()` adiciona `'evaluation_window'` a `mismatches` (`status='incompatible'`). Quando apenas uma execucao ativa `evaluation_window`, `compare_manifests()` mantem `status='paired'` para todos os KPIs partilhados, regista `'evaluation_window_one_sided'` em `declared_differences` (`evaluation_window.status == 'one_sided'`), e `compare_exports()` assinala apenas as linhas da janela em `unpaired_window_kpis`.

## Combinacoes Importantes

| Caso | Configuracao |
|---|---|
| Treino flat classico | `interface` omitido ou `flat`, `topology_mode` omitido ou `static`. |
| Entity para GNN/Transformer | `interface="entity"`, bundles conforme necessidade. |
| Topologia dinamica | `interface="entity"`, `topology_mode="dynamic"`, `topology_events`. |
| Demand response | `interface="entity"`, `demand_response.enabled=true`, bundle `entity_demand_response`. |
| Robustez | Qualquer interface, `robustness.enabled=true`; adicionar `entity_robustness` para diagnostico entity. |
| Datasets reais PV absoluto | `pv.attributes.generation_mode="absolute"`. |
| 15 segundos | `seconds_per_time_step=15` e ficheiros ja nessa cadencia. |
| Parquet pesado | Trocar paths `.csv` por `.parquet` mantendo colunas. |
