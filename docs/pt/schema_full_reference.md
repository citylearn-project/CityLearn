# Schema de referência completo

[`examples/schema_full_reference.json`](https://github.com/citylearn-project/CityLearn/blob/master/examples/schema_full_reference.json)
é um schema completo que escreve todas as opções que o CityLearn lê. Corre tal como está a partir de uma cópia do
código-fonte: usa dois edifícios (`Building_1` e `Building_4`) e dois VE do dataset
`citylearn_challenge_2022_phase_all_plus_evs`. Copie-o, aponte `root_directory` para os seus dados e altere só o que
precisa.

```python
from citylearn.citylearn import CityLearnEnv

env = CityLearnEnv("examples/schema_full_reference.json")
```

O JSON não tem comentários, por isso esta página percorre o ficheiro secção a secção. Cada bloco abaixo é uma parte do
ficheiro (juntos formam o ficheiro inteiro), seguido do que cada chave faz, da sua predefinição e das alternativas. A
[referência do schema](schema_reference.md) tem as regras completas.

Como ler os valores:

- Quando uma chave tem predefinição, o ficheiro usa-a. Um `null` nos `attributes` dos dispositivos, carregadores e VE
  significa "usar a predefinição", incluindo as predefinições sorteadas do fluxo aleatório.
- As chaves obrigatórias sem predefinição (nomes de ficheiros, dimensões, janela temporal) usam os valores do dataset.
- As funcionalidades desligadas por predefinição (mercado comunitário, resposta à procura, robustez, falhas de energia,
  topologia dinâmica) aparecem com `enabled: false` ou listas vazias, para que se veja a sua forma e se possam ligar.
- A seleção de observações e ações ativas é um exemplo; por predefinição todos os nomes estão a `false`.

Versão em inglês: [../schema_full_reference.md](../schema_full_reference.md).

## Localização dos dados, sementes e versões

```json
{
  "root_directory": "../data/datasets/citylearn_challenge_2022_phase_all_plus_evs",
  "random_seed": 2022,
  "random_stream_version": "v2",
  "physics_version": 2,
  "baseline_version": 2
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `root_directory` | pasta do dataset, relativa ao ficheiro do schema | a pasta do schema | Todos os nomes de ficheiro abaixo são lidos a partir daqui. Um schema `dict` tem de a definir. O argumento `root_directory` sobrepõe-se a ela. |
| `random_seed` | `2022` | uma semente aleatória nova em cada construção | Defina-a para execuções repetíveis: os parâmetros sorteados dos dispositivos, o SOC inicial e a deriva dos VE, o ruído e os episódios aleatórios dependem dela. |
| `random_stream_version` | `"v2"` | `"v2"` | `"v1"` reproduz os sorteios do CityLearn 3.6.0. |
| `physics_version` | `2` | `2` | `1` reproduz a física da 3.6.0; consulte [O que cada versão altera](schema_reference.md#o-que-cada-versão-altera). |
| `baseline_version` | `2` | `2` | `1`: a baseline dos KPIs não volta a somar o carregamento dos VE, e o BAU envia zero às ações de AVAC, como na 3.6.0. Este dataset não tem ações de AVAC, pelo que o seu BAU é o mesmo nas duas versões. |

## Organização do agente, janela temporal e episódios

```json
{
  "central_agent": false,
  "interface": "flat",
  "seconds_per_time_step": 3600,
  "time_step_ratio_mode": "reject",
  "simulation_start_time_step": 0,
  "simulation_end_time_step": 8759,
  "episode_time_steps": null,
  "rolling_episode_split": false,
  "random_episode_split": false,
  "episode_split_boundary": "shared",
  "ev_soc_carryover": false
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `central_agent` | `false` | obrigatória | `true`: um só vetor de observações e de ações para todos os edifícios. |
| `interface` | `"flat"` | `"flat"` | `"entity"`: tabelas e arestas, necessária para a resposta à procura e a topologia dinâmica. |
| `seconds_per_time_step` | `3600` | obrigatória | Tem de ser igual ao passo dos dados (aqui, horário). |
| `time_step_ratio_mode` | `"reject"` | `"reject"` | `"compress"` lê uma linha de dados por passo de controlo quando os passos diferem, como a 3.6.0. |
| `simulation_start_time_step`, `simulation_end_time_step` | `0`, `8759` | obrigatórias | Linhas dos dados, ambas inclusivas: um ano, 8759 passos de controlo. |
| `episode_time_steps` | `null` | `null` | `null`: um episódio. Um int `N`: episódios de `N` linhas. Uma lista de `[start, end]`: episódios fixos. |
| `rolling_episode_split` | `false` | `false` | `true`: qualquer linha pode iniciar um episódio. |
| `random_episode_split` | `false` | `false` | `true`: sorteia o episódio em cada reset. |
| `episode_split_boundary` | `"shared"` | `"shared"` | `"disjoint"`: as divisões da 3.6.0, que saltam um intervalo entre episódios. |
| `ev_soc_carryover` | `false` | `false` | `true`: um episódio que continua o anterior no tempo começa cada VE com o SOC que tinha no fim desse episódio. |

## Calendário e relógio do dataset

```json
{
  "time_axis": {"calendar_file": null},
  "timezone": null,
  "dataset_seconds_per_time_step": null,
  "dataset_contract_version": null,
  "terminal_observation_padding": false,
  "start_date": "2024-01-01"
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `time_axis.calendar_file` | `null` | nenhuma | Um calendário CSV ou Parquet com `time_step` e `timestamp_utc`; define o passo do dataset e os instantes exportados. |
| `timezone` | `null` | nenhuma | Nome IANA, como `"Europe/Lisbon"`, para os instantes do calendário. |
| `dataset_seconds_per_time_step` | `null` | inferida das colunas de calendário | Declare o passo dos dados quando `hour`/`minutes`/`seconds` não o permitem obter. |
| `dataset_contract_version` | `null` | nenhuma | Metadado; um valor começado por `portugal-native` escolhe `shared/calendar.parquet` como calendário. |
| `terminal_observation_padding` | `false` | `false` | `true` permite ficheiros com uma linha a menos do que a janela. |
| `start_date` | `"2024-01-01"` | `"2024-01-01"` | Data da linha 0 nos instantes exportados. Não altera a simulação. |

## Recompensa e agente

```json
{
  "reward_function": {
    "type": "citylearn.reward_function.RewardFunction",
    "attributes": {"exponent": 1.0, "charging_constraint_penalty_coefficient": 1.0}
  },
  "agent": {"type": "citylearn.agents.baseline.BusinessAsUsualAgent", "attributes": {}}
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `reward_function.type` | `RewardFunction` | obrigatória | Outras classes: `ComfortReward`, `SolarPenaltyReward`, `SolarPenaltyAndComfortReward`, `Electric_Vehicles_Reward_Function`, `OutageUnservedEnergyReward`, `MARL`, `IndependentSACReward`; ou um objeto por edifício com `"default"`. |
| `reward_function.attributes` | as duas predefinições de `RewardFunction` | `{}` | `exponent` eleva a importação a uma potência; `charging_constraint_penalty_coefficient` pondera as violações dos limites de carregamento. |
| `agent.type`, `agent.attributes` | `BusinessAsUsualAgent` | nenhuma | Usado por `env.load_agent()` sem argumentos. O comando `citylearn simulate` usa antes a opção `-a`. |

## Observações

Estão listados todos os nomes de observação que o CityLearn aceita no catálogo, exceto
`occupant_interaction_indoor_dry_bulb_temperature_set_point_delta`, que só existe no tipo de edifício com ocupantes:
um nome que um edifício não consegue produzir lança `KeyError` na construção, mesmo quando não está ativo. `active` (predefinição `false`) liga um
nome em todos os edifícios que o conseguem produzir; `shared_in_central_agent` (predefinição `false`) põe-no uma só vez
no vetor central quando `central_agent` é `true`. Este ficheiro liga um pequeno conjunto de exemplo e marca como
partilhados os nomes de calendário, meteorologia, preço e carbono, porque são iguais em todos os edifícios.

Os nomes começados por `electric_vehicle_`, `connected_electric_vehicle_at_charger_` e
`incoming_electric_vehicle_at_charger_` são expandidos por carregador, `deferrable_appliance_*` por aparelho e
`escalator_*` por escada rolante (por exemplo `electric_vehicle_charger_charger_1_1_connected_state`). As observações
do serviço elétrico não estão aqui: são ligadas por `electrical_service.observations`.

```json
{
  "observations": {
    "month": {"active": true, "shared_in_central_agent": true},
    "day_type": {"active": true, "shared_in_central_agent": true},
    "hour": {"active": true, "shared_in_central_agent": true},
    "minutes": {"active": false, "shared_in_central_agent": true},
    "seconds": {"active": false, "shared_in_central_agent": true},
    "daylight_savings_status": {"active": false, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature": {"active": true, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature_predicted_1": {"active": false, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature_predicted_2": {"active": false, "shared_in_central_agent": true},
    "outdoor_dry_bulb_temperature_predicted_3": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity_predicted_1": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity_predicted_2": {"active": false, "shared_in_central_agent": true},
    "outdoor_relative_humidity_predicted_3": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance_predicted_1": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance_predicted_2": {"active": false, "shared_in_central_agent": true},
    "diffuse_solar_irradiance_predicted_3": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance_predicted_1": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance_predicted_2": {"active": false, "shared_in_central_agent": true},
    "direct_solar_irradiance_predicted_3": {"active": false, "shared_in_central_agent": true},
    "electricity_pricing": {"active": true, "shared_in_central_agent": true},
    "electricity_pricing_predicted_1": {"active": false, "shared_in_central_agent": true},
    "electricity_pricing_predicted_2": {"active": false, "shared_in_central_agent": true},
    "electricity_pricing_predicted_3": {"active": false, "shared_in_central_agent": true},
    "carbon_intensity": {"active": true, "shared_in_central_agent": true},
    "non_shiftable_load": {"active": true, "shared_in_central_agent": false},
    "cooling_demand": {"active": false, "shared_in_central_agent": false},
    "heating_demand": {"active": false, "shared_in_central_agent": false},
    "dhw_demand": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature": {"active": false, "shared_in_central_agent": false},
    "indoor_relative_humidity": {"active": false, "shared_in_central_agent": false},
    "average_unmet_cooling_setpoint_difference": {"active": false, "shared_in_central_agent": false},
    "occupant_count": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_cooling_set_point": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_heating_set_point": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_cooling_delta": {"active": false, "shared_in_central_agent": false},
    "indoor_dry_bulb_temperature_heating_delta": {"active": false, "shared_in_central_agent": false},
    "comfort_band": {"active": false, "shared_in_central_agent": false},
    "hvac_mode": {"active": false, "shared_in_central_agent": false},
    "cooling_device_efficiency": {"active": false, "shared_in_central_agent": false},
    "heating_device_efficiency": {"active": false, "shared_in_central_agent": false},
    "dhw_device_efficiency": {"active": false, "shared_in_central_agent": false},
    "cooling_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "heating_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "dhw_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "cooling_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "heating_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "dhw_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "electrical_storage_electricity_consumption": {"active": false, "shared_in_central_agent": false},
    "cooling_storage_soc": {"active": false, "shared_in_central_agent": false},
    "heating_storage_soc": {"active": false, "shared_in_central_agent": false},
    "dhw_storage_soc": {"active": false, "shared_in_central_agent": false},
    "electrical_storage_soc": {"active": true, "shared_in_central_agent": false},
    "solar_generation": {"active": true, "shared_in_central_agent": false},
    "net_electricity_consumption": {"active": true, "shared_in_central_agent": false},
    "power_outage": {"active": false, "shared_in_central_agent": false},
    "power_outage_unserved_energy": {"active": false, "shared_in_central_agent": false},
    "electric_vehicle_charger_connected_state": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_departure_time": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_required_soc_departure": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_soc": {"active": true, "shared_in_central_agent": false},
    "connected_electric_vehicle_at_charger_battery_capacity": {"active": false, "shared_in_central_agent": false},
    "electric_vehicle_charger_incoming_state": {"active": false, "shared_in_central_agent": false},
    "incoming_electric_vehicle_at_charger_estimated_arrival_time": {"active": false, "shared_in_central_agent": false},
    "incoming_electric_vehicle_at_charger_estimated_soc_arrival": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_pending": {"active": true, "shared_in_central_agent": false},
    "deferrable_appliance_running": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_can_start": {"active": true, "shared_in_central_agent": false},
    "deferrable_appliance_deadline_missed": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_earliest_start_time_step": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_latest_start_time_step": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_deadline_time_step": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_hours_until_latest_start": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_hours_until_deadline": {"active": true, "shared_in_central_agent": false},
    "deferrable_appliance_slack_steps": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_slack_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_urgency_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_duration_steps": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_energy_kwh": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_remaining_energy_kwh": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_current_step_energy_kwh": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_priority": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_must_run": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_average_power_kw": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_peak_power_kw": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_load_factor_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_cycle_peak_step_offset_ratio": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_remaining_duration_steps": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_remaining_average_power_kw": {"active": false, "shared_in_central_agent": false},
    "deferrable_appliance_current_step_power_kw": {"active": false, "shared_in_central_agent": false},
    "escalator_passengers_from_trains_15min": {"active": false, "shared_in_central_agent": false},
    "escalator_background_pedestrians_15min": {"active": false, "shared_in_central_agent": false},
    "escalator_passengers_expected_15min": {"active": false, "shared_in_central_agent": false},
    "escalator_people_detected": {"active": false, "shared_in_central_agent": false},
    "escalator_passing_trains": {"active": false, "shared_in_central_agent": false},
    "escalator_minutes_to_next_train": {"active": false, "shared_in_central_agent": false},
    "escalator_available": {"active": false, "shared_in_central_agent": false},
    "escalator_state": {"active": false, "shared_in_central_agent": false},
    "escalator_requested_state": {"active": false, "shared_in_central_agent": false},
    "escalator_power_kw": {"active": false, "shared_in_central_agent": false},
    "escalator_service_required": {"active": false, "shared_in_central_agent": false},
    "escalator_service_met": {"active": false, "shared_in_central_agent": false},
    "escalator_unserved_passengers_15min": {"active": false, "shared_in_central_agent": false}
  }
}
```

Consulte o [catálogo das observações](schema_reference.md#observações) para o significado de cada nome, e
[Limites das observações](interfaces_flat_entity.md#limites-das-observações) para os seus limites.

## Ações

```json
{
  "actions": {
    "cooling_or_heating_device": {"active": false},
    "cooling_device": {"active": false},
    "heating_device": {"active": false},
    "cooling_storage": {"active": false},
    "heating_storage": {"active": false},
    "dhw_storage": {"active": false},
    "electrical_storage": {"active": true},
    "electric_vehicle_storage": {"active": true},
    "deferrable_appliance": {"active": true},
    "escalator": {"active": false}
  }
}
```

| Ação | Aqui | Intervalo e significado |
|---|---|---|
| `cooling_or_heating_device`, `cooling_device`, `heating_device` | desligada | Controlo AVAC; só tem efeito nos tipos de edifício com dinâmica. |
| `cooling_storage`, `heating_storage`, `dhw_storage` | desligada | Carrega (positivo) ou descarrega (negativo) o armazenamento térmico. |
| `electrical_storage` | ligada | [-1, 1] × `nominal_power` da bateria. |
| `electric_vehicle_storage` | ligada | Uma ação por carregador: [-1, 1] × `max_charging_power` / `max_discharging_power`. |
| `deferrable_appliance` | ligada | Uma ação por aparelho: arranca o próximo ciclo acima de `trigger_threshold`. |
| `escalator` | desligada | Uma ação por escada rolante: espera, lento ou normal. |

## Bundles entity e previsões derivadas

Estas chaves só são lidas com `"interface": "entity"`.

```json
{
  "observation_bundles": {
    "entity_core_electrical": false,
    "entity_community_operational": false,
    "entity_forecasts_existing": false,
    "entity_forecasts_derived": false,
    "entity_temporal_derived": false,
    "entity_action_feedback": false,
    "entity_demand_response": false,
    "entity_robustness": false
  },
  "derived_forecasts": {
    "load_pv_method": "actual_future",
    "persistence_period_seconds": 86400,
    "cold_start": "current_step",
    "price_source": "known_future_market_input",
    "price_horizon_steps": [1, 2, 3]
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `observation_bundles.<bundle>` | todos `false` | `false` | Ligue os grupos de características de que precisa; `entity_base` está sempre ligado. |
| `derived_forecasts.load_pv_method` | `"actual_future"` | `"actual_future"` | `"daily_persistence"` dá previsões causais de carga e FV. |
| `derived_forecasts.persistence_period_seconds` | `86400` | `86400` | Período da persistência. |
| `derived_forecasts.cold_start` | `"current_step"` | `"current_step"` | O único valor. |
| `derived_forecasts.price_source` | `"known_future_market_input"` | `"known_future_market_input"` | `"publication_aware_day_ahead_market_input"` ou `"daily_persistence"` para preços causais. |
| `derived_forecasts.price_horizon_steps` | `[1, 2, 3]` | `[1, 2, 3]` | Antecedência, em passos, das três colunas `electricity_pricing_predicted_*`. |

## Topologia

```json
{"topology_mode": "static", "topology_events": []}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `topology_mode` | `"static"` | `"static"` | `"dynamic"` (com `"interface": "entity"`) aplica `topology_events`. |
| `topology_events` | `[]` | `[]` | Eventos `add_member`, `remove_member`, `add_asset`, `remove_asset`; consulte [Topologia dinâmica](schema_reference.md#topologia-dinâmica). |

## Building_1: dados e seleção

```json
{
  "buildings": {
    "Building_1": {
      "include": true,
      "type": "citylearn.building.Building",
      "energy_simulation": "Building_1.csv",
      "weather": "weather.csv",
      "pricing": "pricing.csv",
      "carbon_intensity": "carbon_intensity.csv",
      "noise_std": 0.0,
      "inactive_observations": [],
      "inactive_actions": [],
      "equity_group": null
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `include` | `true` | `true` | `false` deixa o edifício de fora (um membro inativo na topologia dinâmica). |
| `type` | `citylearn.building.Building` | a mesma | `LSTMDynamicsBuilding` e os tipos com ocupantes para a dinâmica da temperatura interior. |
| `energy_simulation`, `weather` | ficheiros do dataset | obrigatórias | |
| `pricing`, `carbon_intensity` | ficheiros do dataset | séries de zeros | |
| `noise_std` | `0.0` | `0.0` | Ruído gaussiano na meteorologia, nos preços, no carbono, no perfil FV e nas condições interiores. |
| `inactive_observations`, `inactive_actions` | `[]` | `[]` | Nomes de modelo desligados só neste edifício. |
| `equity_group` | `null` | nenhuma | `"asset_rich"` ou `"asset_poor"` em todos os edifícios ativa o KPI de rácio de equidade. |

## Building_1: dispositivos AVAC

O `Building_1` não tem procura térmica neste dataset, por isso estes dispositivos só mostram a forma. Num edifício com
procura, dimensione-os ou use `"autosize": true`.

```json
{
  "buildings": {
    "Building_1": {
      "cooling_device": {
        "type": "citylearn.energy_model.HeatPump",
        "autosize": false,
        "autosize_attributes": {"safety_factor": 1.0},
        "attributes": {
          "nominal_power": 4.0,
          "efficiency": null,
          "target_heating_temperature": null,
          "target_cooling_temperature": null
        }
      },
      "heating_device": {
        "type": "citylearn.energy_model.HeatPump",
        "autosize": false,
        "autosize_attributes": {"safety_factor": 1.0},
        "attributes": {
          "nominal_power": 4.0,
          "efficiency": null,
          "target_heating_temperature": null,
          "target_cooling_temperature": null
        }
      },
      "dhw_device": {
        "type": "citylearn.energy_model.ElectricHeater",
        "autosize": false,
        "autosize_attributes": {"safety_factor": 1.0},
        "attributes": {"nominal_power": 2.0, "efficiency": null}
      }
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `type` | `HeatPump` (arrefecimento, aquecimento), `ElectricHeater` (água quente) | obrigatória | `cooling_device` tem de ser uma `HeatPump`. |
| `nominal_power` | 4 kW, 4 kW, 2 kW | `0` | Potência elétrica. |
| `efficiency` | `null` | sorteada: 0,2-0,3 (fração de Carnot) nas bombas de calor, 0,9-0,99 nos aquecedores | |
| `target_heating_temperature`, `target_cooling_temperature` | `null` | sorteadas: 45-50 °C e 7-10 °C | Temperaturas de ida usadas no COP. |
| `autosize` | `false` | `false` | `true` dimensiona `nominal_power` a partir da procura máxima. |
| `autosize_attributes.safety_factor` | `1.0` | `1.0` | Multiplica a potência dimensionada. |

## Building_1: armazenamento térmico

```json
{
  "buildings": {
    "Building_1": {
      "cooling_storage": {
        "type": "citylearn.energy_model.StorageTank",
        "autosize": false,
        "autosize_attributes": {"safety_factor": null, "duration": 1.0},
        "attributes": {
          "capacity": 4.0,
          "efficiency": null,
          "loss_coefficient": null,
          "initial_soc": null,
          "max_input_power": null,
          "max_output_power": null
        }
      },
      "heating_storage": {
        "type": "citylearn.energy_model.StorageTank",
        "autosize": false,
        "autosize_attributes": {"safety_factor": null, "duration": 1.0},
        "attributes": {
          "capacity": 4.0,
          "efficiency": null,
          "loss_coefficient": null,
          "initial_soc": null,
          "max_input_power": null,
          "max_output_power": null
        }
      },
      "dhw_storage": {
        "type": "citylearn.energy_model.StorageTank",
        "autosize": false,
        "autosize_attributes": {"safety_factor": null, "duration": 1.0},
        "attributes": {
          "capacity": 2.0,
          "efficiency": null,
          "loss_coefficient": null,
          "initial_soc": null,
          "max_input_power": null,
          "max_output_power": null
        }
      }
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `type` | `StorageTank` | obrigatória | |
| `capacity` | 4, 4 e 2 kWh | `0` | Energia térmica. |
| `efficiency` | `null` | sorteada em 0,90-0,98 | Ida e volta. |
| `loss_coefficient` | `null` | sorteado em 0,001-0,009 por hora | Perda em repouso. |
| `initial_soc` | `null` | `0` | |
| `max_input_power`, `max_output_power` | `null` | sem limite | kW. |
| `autosize_attributes.safety_factor` | `null` | sorteado em 1-2 | |
| `autosize_attributes.duration` | `1.0` | `1.0` hora | Horas de procura máxima (versão 2 da física). |

## Building_1: bateria e FV

```json
{
  "buildings": {
    "Building_1": {
      "electrical_storage": {
        "type": "citylearn.energy_model.Battery",
        "autosize": false,
        "autosize_attributes": {"duration": null, "parallel": false, "safety_factor": 1.0},
        "attributes": {
          "capacity": 6.4,
          "nominal_power": 5.0,
          "efficiency": null,
          "depth_of_discharge": null,
          "initial_soc": null,
          "loss_coefficient": null,
          "capacity_loss_coefficient": null,
          "power_efficiency_curve": null,
          "capacity_power_curve": null,
          "discharge_power_curve": null,
          "phase_connection": null
        }
      },
      "pv": {
        "type": "citylearn.energy_model.PV",
        "autosize": false,
        "autosize_attributes": {
          "epw_filepath": null,
          "use_sample_target": false,
          "zero_net_energy_proportion": null,
          "roof_area": null,
          "safety_factor": 1.0
        },
        "attributes": {"nominal_power": 12.0, "generation_mode": "per_kw", "efficiency": null}
      }
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `electrical_storage.attributes.capacity`, `nominal_power` | 6,4 kWh, 5 kW | `0` | Uma bateria de tamanho 0 não pode receber a ação `electrical_storage`. |
| `efficiency` | `null` | sorteada em 0,90-0,98 | Ida e volta; introduza ao quadrado um valor num só sentido da ficha técnica. |
| `depth_of_discharge` | `null` | `1.0` | Mínimo de descarga `1 - depth_of_discharge`. |
| `initial_soc` | `null` | `1 - depth_of_discharge` | Começa vazia por predefinição. |
| `loss_coefficient` | `null` | sorteado em 0,001-0,009 por hora | |
| `capacity_loss_coefficient` | `null` | sorteado em 1e-5-1e-4 | Degradação da capacidade por ciclo completo equivalente. |
| `power_efficiency_curve`, `capacity_power_curve` | `null` | curvas sorteadas | Indique-as para que a bateria não dependa da semente. |
| `discharge_power_curve` | `null` | `[[0, 1], [1, 1]]` | A versão 1 da física usa também `capacity_power_curve` na descarga. |
| `phase_connection` | `null` | `L1` (monofásico) | Fase sob o serviço elétrico. |
| `autosize_attributes` | `duration` sorteada em 1,5-3,5 h, `parallel` `false`, `safety_factor` `1.0` | | Só usados com `"autosize": true`. |
| `pv.attributes.nominal_power` | 12 kW | `0` | |
| `pv.attributes.generation_mode` | `"per_kw"` | `"per_kw"` | `"absolute"` quando `solar_generation` já está em kWh por passo. |
| `pv.attributes.efficiency` | `null` | sorteada, não usada | |
| `pv.autosize_attributes` | `epw_filepath`, `use_sample_target`, `zero_net_energy_proportion`, `roof_area`, `safety_factor` | | O dimensionamento da FV precisa de um ficheiro meteorológico EPW e de `nrel-pysam`. |

## Building_1: carregador

```json
{
  "buildings": {
    "Building_1": {
      "chargers": {
        "charger_1_1": {
          "type": "citylearn.electric_vehicle_charger.Charger",
          "charger_simulation": "charger_1_1.csv",
          "soc_unit": null,
          "noise_std": 0.0,
          "attributes": {
            "nominal_power": 11.0,
            "max_charging_power": 11.0,
            "min_charging_power": 1.4,
            "max_discharging_power": 7.2,
            "min_discharging_power": 0.0,
            "efficiency": 0.95,
            "charge_efficiency_curve": null,
            "discharge_efficiency_curve": null,
            "phase_connection": null,
            "charger_type": 0
          }
        }
      }
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `type` | `Charger` | obrigatória | |
| `charger_simulation` | `charger_1_1.csv` | obrigatória | Horário dos VE ligados e a chegar. |
| `soc_unit` | `null` | inferida por coluna | `"percent"` ou `"fraction"` para declarar a unidade das colunas de SOC. |
| `noise_std` | `0.0` | `0.0` | Ruído, em pontos percentuais de SOC, no SOC pedido e no SOC à chegada. |
| `nominal_power`, `max_charging_power` | 11 kW | `max_charging_power` = `nominal_power` | |
| `min_charging_power` | 1,4 kW | `0` | Pedidos abaixo dela dão 0. |
| `max_discharging_power` | 7,2 kW | `0` (sem V2G) | Defina acima de 0 para V2G ou vehicle-to-building. |
| `min_discharging_power` | `0.0` | `0` | |
| `efficiency` | 0,95 | `1.0` | Usada onde não há curva. |
| `charge_efficiency_curve`, `discharge_efficiency_curve` | `null` | nenhuma | `[[fração de potência, eficiência], ...]`. |
| `phase_connection` | `null` | `L1` | |
| `charger_type` | `0` | nenhuma | Só uma etiqueta. |

## Building_1: aparelho diferível e escadas rolantes

```json
{
  "buildings": {
    "Building_1": {
      "deferrable_appliances": {
        "deferrable_appliance_1": {
          "type": "citylearn.energy_model.DeferrableAppliance",
          "cycle_profiles_file": "deferrable_appliance_1_cycle_profiles.csv",
          "flexibility_schedule_file": "deferrable_appliance_1_flexibility_schedule.csv",
          "attributes": {"trigger_threshold": 0.5, "nominal_power": 0.0, "efficiency": null}
        }
      },
      "escalators": {}
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `type` | `DeferrableAppliance` | a mesma | |
| `cycle_profiles_file`, `flexibility_schedule_file` | ficheiros do dataset | obrigatórias | Ciclos e as suas janelas. |
| `attributes.trigger_threshold` | `0.5` | `0.5` | Uma ação acima deste valor arranca o próximo ciclo. |
| `attributes.nominal_power` | `0.0` | `0.0` | Acima de 0, o pico de potência de cada ciclo tem de caber abaixo dela. |
| `attributes.efficiency` | `null` | sorteada, não usada | |
| `escalators` | `{}` | `{}` | As escadas rolantes precisam de um ficheiro de passageiros e da interface flat; consulte [Escadas rolantes](schema_reference.md#escadas-rolantes). |

## Building_1: serviço elétrico

```json
{
  "buildings": {
    "Building_1": {
      "electrical_service": {
        "mode": "single_phase",
        "default_split": "balanced",
        "limits": {
          "total": {"import_kw": 17.25, "export_kw": 6.9},
          "per_phase": {
            "L1": {"import_kw": 17.25, "export_kw": 6.9}
          }
        },
        "available_grid_power": null,
        "observations": {
          "headroom": true,
          "headroom_export": true,
          "violation": true,
          "phase_encoding": false,
          "available_grid_power": true
        }
      }
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `mode` | `"single_phase"` | `"single_phase"` | `"three_phase"` acrescenta `L2` e `L3`. |
| `default_split` | `"balanced"` | `"balanced"` | Fase da carga sem ligação a uma fase. |
| `limits.total.import_kw`, `export_kw` | 17,25 kW, 6,9 kW | sem limite | Uma ligação monofásica de 25 A com um limite de exportação de 6,9 kW. Deixe uma chave de fora para não ter limite. |
| `limits.per_phase.L1.import_kw`, `export_kw` | 17,25 kW, 6,9 kW | sem limite | |
| `available_grid_power` | `null` | nenhuma | Um ficheiro (ou `{filename, column}`) com o limite de importação em cada passo. |
| `observations.headroom`, `headroom_export`, `violation`, `available_grid_power` | `true` | `true` | Acrescenta às observações `charging_building_headroom_kw`, as margens de exportação e de `L1` e `charging_constraint_violation_kwh`. |
| `observations.phase_encoding` | `false` | `false` | Fase de cada carregador em one-hot. |

## Building_1: falhas, dinâmica e ocupantes

```json
{
  "buildings": {
    "Building_1": {
      "power_outage": {
        "simulate_power_outage": false,
        "stochastic_power_outage": false,
        "stochastic_power_outage_model": {
          "type": "citylearn.power_outage.ReliabilityMetricsPowerOutage",
          "attributes": {"saifi": 1.436, "caidi": 331.2, "start_time_steps": null, "random_seed": null}
        },
        "vehicle_to_building": false
      },
      "dynamics": null,
      "occupant": null,
      "set_point_hold_time_steps": null,
      "set_point_limits": [15.0, 30.0]
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `power_outage.simulate_power_outage` | `false` | `false` | `true` lê a coluna `power_outage`, ou o modelo abaixo. |
| `power_outage.stochastic_power_outage` | `false` | `false` | `true` sorteia as falhas com o modelo. |
| `power_outage.stochastic_power_outage_model` | `ReliabilityMetricsPowerOutage` com as suas predefinições | `PowerOutage` (cada passo uma falha com probabilidade 0,5) | `saifi` interrupções por ano, `caidi` minutos cada. |
| `power_outage.vehicle_to_building` | `false` | `false` | `true` deixa o VE ligado alimentar a casa durante uma falha. |
| `dynamics`, `occupant` | `null` | nenhuma | Só para tipos de edifício com dinâmica e com ocupantes. |
| `set_point_hold_time_steps` | `null` | `null` | Só para tipos de edifício com ocupantes. |
| `set_point_limits` | `[15.0, 30.0]` | `[15, 30]` | Só para tipos de edifício com ocupantes; versão 2 da física. |

## Building_4: a forma curta

O `Building_4` mostra as mesmas secções escritas apenas com as chaves que não têm predefinição, e as
`charging_constraints` antigas (lidas só porque o edifício não tem `electrical_service`).

```json
{
  "buildings": {
    "Building_4": {
      "include": true,
      "type": "citylearn.building.Building",
      "energy_simulation": "Building_4.csv",
      "weather": "weather.csv",
      "pricing": "pricing.csv",
      "carbon_intensity": "carbon_intensity.csv",
      "electrical_storage": {
        "type": "citylearn.energy_model.Battery",
        "autosize": false,
        "attributes": {"capacity": 6.4, "nominal_power": 5.0}
      },
      "pv": {
        "type": "citylearn.energy_model.PV",
        "autosize": false,
        "attributes": {"nominal_power": 8.0}
      },
      "chargers": {
        "charger_4_1": {
          "type": "citylearn.electric_vehicle_charger.Charger",
          "charger_simulation": "charger_4_1.csv",
          "attributes": {
            "nominal_power": 22.0,
            "max_charging_power": 22.0,
            "min_charging_power": 3.7,
            "max_discharging_power": 22.0,
            "min_discharging_power": 3.7,
            "efficiency": 0.95
          }
        }
      },
      "charging_constraints": {
        "building_limit_kw": null,
        "phases": [{"name": "phase_1", "limit_kw": null, "chargers": ["charger_4_1"]}],
        "expose_observations": true,
        "observations": {"headroom": true, "headroom_export": false, "violation": true, "phase_encoding": false}
      }
    }
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `charging_constraints.building_limit_kw` | `null` | sem limite | Limite da potência total de carregamento do edifício. |
| `charging_constraints.phases` | uma fase com `charger_4_1` e sem limite | `[]` | `limit_kw` limita os carregadores listados em conjunto. |
| `charging_constraints.expose_observations` | `true` | `true` | Valor de recurso para `observations.headroom`. |
| `charging_constraints.observations` | `headroom` `true`, `headroom_export` `false`, `violation` `true`, `phase_encoding` `false` | as mesmas | |

## Veículos elétricos e avaliação dos VE

```json
{
  "electric_vehicles_def": {
    "Electric_Vehicle_7": {
      "type": "citylearn.electric_vehicle.ElectricVehicle",
      "include": true,
      "battery": {
        "type": "citylearn.energy_model.Battery",
        "attributes": {
          "capacity": 40.0,
          "nominal_power": 50.0,
          "initial_soc": null,
          "depth_of_discharge": 1.0,
          "loss_coefficient": 0.0,
          "efficiency": null,
          "capacity_loss_coefficient": null,
          "power_efficiency_curve": null,
          "capacity_power_curve": null,
          "discharge_power_curve": null,
          "random_seed": null
        }
      }
    },
    "Electric_Vehicle_8": {
      "type": "citylearn.electric_vehicle.ElectricVehicle",
      "include": true,
      "battery": {
        "type": "citylearn.energy_model.Battery",
        "attributes": {
          "capacity": 40.0,
          "nominal_power": 50.0,
          "initial_soc": null,
          "depth_of_discharge": 1.0,
          "loss_coefficient": 0.0,
          "efficiency": null,
          "capacity_loss_coefficient": null,
          "power_efficiency_curve": null,
          "capacity_power_curve": null,
          "discharge_power_curve": null,
          "random_seed": null
        }
      }
    }
  },
  "ev_departure_within_tolerance": 0.05,
  "ev_departure_service_tolerance": 0.05,
  "business_as_usual_ev_charge_target": "full"
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| (ID do VE) | `Electric_Vehicle_7`, `Electric_Vehicle_8` | | Tem de coincidir com o texto de `electric_vehicle_id` nos ficheiros dos carregadores. |
| `type` | `ElectricVehicle` | a mesma | |
| `include` | `true` | `true` | `false` deixa o VE de fora; os carregadores nunca o veem ligado. |
| `battery.type` | `Battery` | a mesma | |
| `battery.attributes.capacity`, `nominal_power` | 40 kWh, 50 kW | obrigatórias | |
| `battery.attributes.initial_soc` | `null` | sorteado em [0, 1] por VE a partir de `random_seed` | |
| `battery.attributes.depth_of_discharge` | `1.0` | `1.0` | |
| `battery.attributes.loss_coefficient` | `0.0` | `0.0` nos VE | |
| outros `battery.attributes` | `null` | como na bateria estacionária | |
| `ev_departure_within_tolerance`, `ev_departure_service_tolerance` | `0.05` | `0.05` | Tolerâncias de SOC dos KPIs de partida. |
| `business_as_usual_ev_charge_target` | `"full"` | `"full"` | `"requested"`: o BAU para no SOC pedido para a partida. |

## Mercado comunitário

```json
{
  "community_market": {
    "enabled": false,
    "local_price_ratio_to_grid_import": 0.8,
    "settlement_version": 1,
    "grid_export_price": 0.0,
    "tariff_files": {},
    "local_trading_enabled": true,
    "import_member_weights": {},
    "kpis": {"community_local_traded_enabled": true, "community_self_consumption_enabled": true},
    "matching_granularity": "aggregate_building",
    "counterfactual": "grid_only"
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `enabled` | `false` | `false` | `true` liquida as importações e exportações dentro da comunidade em cada passo. |
| `local_price_ratio_to_grid_import` | `0.8` | `0.8` | Preço local como fração do preço de importação da rede. |
| `settlement_version` | `1` | `1` | `2` permite um `grid_export_price` diferente de zero. |
| `grid_export_price` | `0.0` | `0.0` | EUR/kWh pelas exportações residuais. |
| `tariff_files` | `{}` | `{}` | Ficheiros de preços por membro. |
| `local_trading_enabled` | `true` | `true` | `false` mantém a liquidação mas não troca nada localmente. |
| `import_member_weights` | `{}` | todos os membros 1,0 | Prioridade dos importadores na energia local. |
| `kpis.*` | `true` | `true` | Indica os KPIs da energia trocada localmente e da quota de importação. |
| `matching_granularity`, `counterfactual` | os únicos valores | os mesmos | |

## Resposta à procura

```json
{
  "demand_response": {
    "enabled": false,
    "requests_file": null,
    "baseline_method": "rolling_pre_event_average",
    "baseline_window_seconds": 3600,
    "allow_overlapping_requests": false,
    "request_purposes": {}
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `enabled` | `false` | `false` | `true` precisa de `"interface": "entity"` e de um `requests_file`. |
| `requests_file` | `null` | nenhum | Ficheiro CSV ou Parquet com os pedidos do DSO/TSO. |
| `baseline_method` | `"rolling_pre_event_average"` | o mesmo | O único método. |
| `baseline_window_seconds` | `3600` | `3600` | Janela antes de cada pedido para a baseline. |
| `allow_overlapping_requests` | `false` | `false` | Os pedidos não se podem sobrepor. |
| `request_purposes` | `{}` | `{}` | `service`, `stress` ou `unspecified` por ID de pedido, para os KPIs de auditoria. |

## Robustez

```json
{
  "robustness": {
    "enabled": false,
    "events_file": null,
    "random_seed": null,
    "missing_replacement_value": -9999.0,
    "modules": {
      "observations": {"enabled": true},
      "forecasts": {"enabled": true},
      "actions": {"enabled": true},
      "assets": {"enabled": true}
    },
    "agent_observation_contract": {"mode": "known_faults", "features": {}}
  }
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `enabled` | `false` | `false` | `true` aplica os eventos de `events_file`. |
| `events_file` | `null` | nenhum | Ficheiro CSV ou Parquet com eventos de observação, previsão, ação e ativos. |
| `random_seed` | `null` | o `random_seed` da raiz | Semente do ruído dos eventos. |
| `missing_replacement_value` | `-9999.0` | `-9999.0` | Valor das observações em falta. |
| `modules.*.enabled` | `true` | `true` | Desliga um módulo sem editar os eventos. |
| `agent_observation_contract.mode` | `"known_faults"` | `"known_faults"` | `"hidden_faults"` esconde as etiquetas das falhas e mascara as características entity não listadas. |
| `agent_observation_contract.features` | `{}` | `{}` | Características visíveis com `hidden_faults`. |

## Saídas e diagnóstico

```json
{
  "render_mode": "none",
  "render": false,
  "render_file_format": "csv",
  "render_chunk_size": null,
  "render_session_name": null,
  "export_kpis_on_episode_end": false,
  "export_only_final_episode": true,
  "debug_timing": false,
  "check_observation_limits": false,
  "physics_invariant_checks": false,
  "energy_provenance": true,
  "metrics_log_interval": 0
}
```

| Chave | Aqui | Predefinição | Notas e alternativas |
|---|---|---|---|
| `render_mode` | `"none"` | `"none"` | `"during"` ou `"end"` para escrever séries temporais. Prevalece sobre o argumento do construtor. |
| `render` | `false` | segue `render_mode` | Interruptor antigo; prevalece sobre o argumento do construtor. |
| `render_file_format` | `"csv"` | `"csv"` | `"parquet"` precisa de `pyarrow`. |
| `render_chunk_size` | `null` | 100000 linhas em CSV, 50000 em Parquet | |
| `render_session_name` | `null` | data e hora | Subpasta das exportações. |
| `export_kpis_on_episode_end` | `false` | segue o render | `true` escreve `exported_kpis.csv` no fim de cada episódio. |
| `export_only_final_episode` | `true` | `true` | Para execuções planeadas com vários episódios. |
| `debug_timing` | `false` | `false` | Campos de tempos em `info` do passo. |
| `check_observation_limits` | `false` | `false` | Registos DEBUG das observações fora dos limites. |
| `physics_invariant_checks` | `false` | `false` | Lança erro numa violação do balanço de energia. |
| `energy_provenance` | `true` | `true` | `false` é mais rápido e retira os KPIs de proveniência. |
| `metrics_log_interval` | `0` | `0` | Regista uma linha de resumo a cada N passos. |

## Ligar funcionalidades

| Para | Altere |
|---|---|
| Treinar em episódios aleatórios de uma semana | `"episode_time_steps": 169`, `"random_episode_split": true` |
| Reproduzir o CityLearn 3.6.0 | `"physics_version": 1`, `"baseline_version": 1`, `"random_stream_version": "v1"`, `"episode_split_boundary": "disjoint"` |
| Controlar os dois edifícios com um só agente | `"central_agent": true` |
| Usar tabelas entity | `"interface": "entity"` e os `observation_bundles` de que precisa |
| Liquidar a energia localmente e pagar as exportações | `community_market`: `"enabled": true`, `"settlement_version": 2`, `"grid_export_price": 0.05` |
| Limitar a ligação à rede de `Building_1` | `electrical_service.limits.total.import_kw` |
| Permitir V2G só em `charger_4_1` | `max_discharging_power` a `0.0` em `charger_1_1` |
| Simular falhas realistas | `"simulate_power_outage": true`, `"stochastic_power_outage": true` |
| Exportar séries temporais no fim de cada episódio | `"render_mode": "end"` |
| Verificar os balanços de energia em cada passo | `"physics_invariant_checks": true` |
