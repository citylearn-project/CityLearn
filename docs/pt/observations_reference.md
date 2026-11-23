# Referência de observações

Esta página é o dicionário de observações do simulador. Serve de contrato legível por pessoas e por máquinas para wrappers, Offline RL, GraphRL e políticas Transformer.

Versão em inglês: [../observations_reference.md](../observations_reference.md).

## Contrato de unidades

| Padrão do nome | Unidade | Exemplo |
|---|---:|---|
| `_power_kw`, `_kw`, `headroom_kw` | kW | `generation_power_kw`, `charging_slack_kw`. |
| `_energy_kwh_step`, `_kwh_step` | kWh/step | `net_energy_kwh_step`. |
| `_kwh` | kWh | `capacity_kwh`, `energy_to_full_kwh`. |
| `_soc`, `_soc_ratio`, `_ratio` | rácio | `electrical_storage_soc`, `service_level_ratio`. |
| `_time_step` | índice do passo | `deadline_time_step`. |
| `hours_until_*` | horas | `hours_until_departure`. |
| `*_count` | contagem | `active_buildings_count`. |
| `electricity_pricing` | moeda/kWh | Moeda definida pelo dataset. |
| `carbon_intensity` | kgCO2/kWh | Fator de emissões da rede. |
| Temperaturas | C | `outdoor_dry_bulb_temperature`. |
| Irradiância | W/m2 | `direct_solar_irradiance`. |

Valores sentinela comuns:

| Valor | Significado |
|---:|---|
| `-1` | Tempo, ID ou quantidade indisponível. |
| `-0.1` | SOC desconhecido ou sem VE. |
| `0` | Não aplicável quando zero é fisicamente válido, ou linha de entidade ausente. |

## Observações flat

As observações flat são controladas por `schema["observations"]`. Com `central_agent=True`, as observações marcadas com `shared_in_central_agent=true` aparecem apenas uma vez no vetor central.

### Calendário

| Observação | Unidade | Significado |
|---|---:|---|
| `month` | 1-12 | Mês. |
| `day_type` | 1-8 | Dia da semana ou dia especial. |
| `hour` | 1-24 | Hora. |
| `minutes` | 0-59 | Minuto, apenas se existir no dataset. |
| `seconds` | 0-59 | Segundo, necessário para datasets com resolução inferior ao minuto. |
| `daylight_savings_status` | binário | Estado da hora de verão. |

### Meteorologia

| Observação | Unidade | Significado |
|---|---:|---|
| `outdoor_dry_bulb_temperature` | C | Temperatura exterior. |
| `outdoor_relative_humidity` | percentagem | Humidade relativa exterior. |
| `diffuse_solar_irradiance` | W/m2 | Irradiância difusa. |
| `direct_solar_irradiance` | W/m2 | Irradiância direta. |
| `*_predicted_1/2/3` | mesma unidade | Horizontes de previsão tal como codificados pelo dataset. |

O simulador não assume horizontes de previsão fixos. São os que o dataset fornecer.

### Preço e carbono

| Observação | Unidade | Significado |
|---|---:|---|
| `electricity_pricing` | moeda/kWh | Preço atual de importação da rede. |
| `electricity_pricing_predicted_1/2/3` | moeda/kWh | Previsões de preço. |
| `carbon_intensity` | kgCO2/kWh | Intensidade carbónica da rede. |

### Cargas, conforto e AVAC

| Observação | Unidade | Significado |
|---|---:|---|
| `indoor_dry_bulb_temperature` | C | Temperatura interior. |
| `average_unmet_cooling_setpoint_difference` | C | Violação média do setpoint de arrefecimento. |
| `indoor_relative_humidity` | percentagem | Humidade relativa interior. |
| `occupant_count` | pessoas | Ocupação. |
| `indoor_dry_bulb_temperature_cooling_set_point` | C | Setpoint de arrefecimento. |
| `indoor_dry_bulb_temperature_heating_set_point` | C | Setpoint de aquecimento. |
| `indoor_dry_bulb_temperature_cooling_delta` | C | Delta de arrefecimento controlado. |
| `indoor_dry_bulb_temperature_heating_delta` | C | Delta de aquecimento controlado. |
| `comfort_band` | C | Banda de conforto. |
| `hvac_mode` | enum | 0 desligado, 1 arrefecimento, 2 aquecimento, 3 automático. |
| `cooling_demand` | kWh/step | Procura térmica de arrefecimento. |
| `heating_demand` | kWh/step | Procura térmica de aquecimento. |
| `dhw_demand` | kWh/step | Procura de água quente sanitária. |
| `non_shiftable_load` | kWh/step | Carga elétrica não flexível. |
| `cooling_device_efficiency` | COP/rácio | Eficiência do equipamento de arrefecimento. |
| `heating_device_efficiency` | COP/rácio | Eficiência do equipamento de aquecimento. |
| `dhw_device_efficiency` | COP/rácio | Eficiência do equipamento de AQS. |

### Armazenamento, FV e energia líquida

| Observação | Unidade | Significado |
|---|---:|---|
| `cooling_storage_soc` | rácio | SOC do armazenamento de arrefecimento. |
| `heating_storage_soc` | rácio | SOC do armazenamento de aquecimento. |
| `dhw_storage_soc` | rácio | SOC do armazenamento de AQS. |
| `electrical_storage_soc` | rácio | SOC do BESS. |
| `*_electricity_consumption` | kWh/step | Consumo de eletricidade por uso final. |
| `electrical_storage_electricity_consumption` | kWh/step | Consumo do BESS, positivo no carregamento e negativo na descarga. |
| `solar_generation` | kWh/step | Produção FV depois da conversão do modo FV. |
| `net_electricity_consumption` | kWh/step | Importação positiva, exportação negativa. |
| `power_outage` | binário | Estado de corte de energia. |
| `power_outage_unserved_energy` | kWh/step | Carga não servida durante um corte de energia, como no KPI `power_outage_normalized_unserved_energy_total`. Zero sem corte. Apenas na interface flat; a tabela entity `building` não a inclui. |
| `available_grid_power` | kW | Limite de importação da rede para o intervalo seguinte: o menor entre o `import_kw` estático e a série de [potência de rede disponível](schema_reference.md#potência-de-rede-disponível). Apenas com uma série. Apenas na interface flat; na interface entity, as features de margem (headroom) do edifício seguem o limite. |

### Observações flat de VE e carregadores

As chaves auxiliares do schema são expandidas por carregador.

| Chave do schema | Chave expandida | Unidade | Significado |
|---|---|---:|---|
| `electric_vehicle_charger_connected_state` | `electric_vehicle_charger_{id}_connected_state` | binário | VE ligado e pronto. |
| `connected_electric_vehicle_at_charger_departure_time` | `connected_electric_vehicle_at_charger_{id}_departure_time` | passos | Passos até à partida. |
| `connected_electric_vehicle_at_charger_required_soc_departure` | `connected_electric_vehicle_at_charger_{id}_required_soc_departure` | rácio | SOC exigido à partida. |
| `connected_electric_vehicle_at_charger_soc` | `connected_electric_vehicle_at_charger_{id}_soc` | rácio | SOC do VE ligado. |
| `connected_electric_vehicle_at_charger_battery_capacity` | `connected_electric_vehicle_at_charger_{id}_battery_capacity` | kWh | Capacidade da bateria do VE ligado. |
| `electric_vehicle_charger_incoming_state` | `electric_vehicle_charger_{id}_incoming_state` | binário | Existe um VE a chegar. |
| `incoming_electric_vehicle_at_charger_estimated_arrival_time` | `incoming_electric_vehicle_at_charger_{id}_estimated_arrival_time` | passos | Passos até à chegada estimada. |
| `incoming_electric_vehicle_at_charger_estimated_soc_arrival` | `incoming_electric_vehicle_at_charger_{id}_estimated_soc_arrival` | rácio | SOC estimado à chegada. |

### Observações flat de aparelhos diferíveis

As chaves auxiliares `deferrable_appliance_*` são expandidas por aparelho. Os mesmos campos aparecem na tabela entity `deferrable_appliance`.

| Feature | Unidade | Significado |
|---|---:|---|
| `pending`, `running`, `can_start`, `deadline_missed` | binário | Indicadores do estado do ciclo. |
| `earliest_start_time_step`, `latest_start_time_step`, `deadline_time_step` | passo global | Janela de flexibilidade e prazo. |
| `hours_until_latest_start`, `hours_until_deadline` | horas | Tempo restante. |
| `slack_steps` | passos | Folga restante até ao último arranque. |
| `slack_ratio`, `urgency_ratio` | rácio | Folga e urgência normalizadas. |
| `cycle_duration_steps` | passos | Duração do ciclo. |
| `cycle_energy_kwh` | kWh | Energia total do ciclo. |
| `remaining_energy_kwh` | kWh | Energia ainda por servir. |
| `current_step_energy_kwh` | kWh/step | Energia do ciclo no passo atual. |
| `priority` | rácio | Prioridade externa. |
| `must_run` | binário | Pedido de serviço obrigatório. |
| `cycle_average_power_kw`, `cycle_peak_power_kw` | kW | Potência média e de pico do ciclo. |
| `cycle_load_factor_ratio`, `cycle_peak_step_offset_ratio` | rácio | Descritores do perfil do ciclo. |
| `remaining_duration_steps` | passos | Duração restante do ciclo. |
| `remaining_average_power_kw`, `current_step_power_kw` | kW | Potência média restante e potência do passo atual. |

### Observações flat de escadas rolantes

As chaves auxiliares `escalator_*` são expandidas por escada rolante na interface flat.

| Feature | Unidade | Significado |
|---|---:|---|
| `passengers_from_trains_15min`, `background_pedestrians_15min`, `passengers_expected_15min` | passageiros/passo | Fontes de procura agregada e procura total. |
| `people_detected`, `available`, `service_required`, `service_met` | binário | Indicadores simples de procura, disponibilidade e serviço. |
| `passing_trains` | contagem | Comboios de passagem; duplicados de chegada/partida na fonte não são contados duas vezes. |
| `minutes_to_next_train` | minutos | Tempo até ao próximo comboio relevante. |
| `state`, `requested_state` | enum `0–2` | Estado de standby, lento ou normal. |
| `power_kw` | kW | Potência de funcionamento aplicada. |
| `unserved_passengers_15min` | passageiros/passo | Procura deixada por servir em standby. |

## Tabelas entity

O modo entity devolve `tables`, `edges` e `meta`. As features disponíveis dependem do schema, dos ativos em serviço e dos bundles ativados.

### `district`

| Grupo de features | Bundle | Unidade | Significado |
|---|---|---:|---|
| Observações flat partilhadas | legacy | varia | Observações partilhadas do primeiro edifício. |
| Previsões `*_predicted_*` | `entity_forecasts_existing` | varia | Previsões do dataset. |
| `community_*_power_kw` | `entity_community_operational` | kW | Agregados de potência do distrito/comunidade. |
| `community_*_energy_kwh_step` | `entity_community_operational` | kWh/step | Agregados de energia por passo do distrito/comunidade. |
| `community_*_headroom_kw` | `entity_community_operational` | kW | Agregados da margem de importação/exportação. |
| `community_flexible_*_capacity_kw`, `community_flexible_*_capacity_kwh_step`, `community_flexible_energy_*_kwh` | `entity_community_operational` | misto | Potência flexível agregada de carregamento/descarga e folga de energia. |
| `active_buildings_count`, `active_chargers_count`, `active_evs_count` | `entity_community_operational` | contagem | Contagens da topologia ativa. |
| `topology_version` | `entity_community_operational` | contagem | Versão atual da topologia. |
| `dr_active` | `entity_demand_response` | binário | Se está ativo um pedido de resposta à procura neste passo. |
| `dr_issuer_code` | `entity_demand_response` | enum | Código do emissor do pedido: `1=dso`, `2=tso`, `0=none/unknown`. |
| `dr_direction` | `entity_demand_response` | enum | Direção na perspetiva da carga: `1=up`, `-1=down`, `0=none`. |
| `dr_target_power_kw` | `entity_demand_response` | kW | Potência alvo ativa do distrito. |
| `dr_baseline_power_kw` | `entity_demand_response` | kW | Potência líquida de referência congelada para o pedido ativo, quando válida. |
| `dr_time_remaining_hours` | `entity_demand_response` | horas | Tempo restante na janela de ativação inclusiva. |
| `dr_activation_price_eur_per_kwh` | `entity_demand_response` | moeda/kWh | Preço creditado pela energia entregue. |
| `dr_shortfall_penalty_eur_per_kwh` | `entity_demand_response` | moeda/kWh | Preço de penalização pela energia em falta (shortfall). |
| `dr_previous_delivered_power_kw` | `entity_demand_response` | kW | Potência entregue liquidada no passo DR ativo anterior. |
| `dr_previous_shortfall_power_kw` | `entity_demand_response` | kW | Potência em falta liquidada no passo DR ativo anterior. |
| `community_net_prev_1_kwh_step`, `community_net_prev_3_mean_kwh_step` | `entity_temporal_derived` | kWh/step | Features de desfasamento (lag) do distrito. |
| `hour_sin/cos`, `day_type_sin/cos`, `month_sin/cos`, `seconds_of_day_sin/cos`, `is_weekend` | `entity_temporal_derived` | rácio/binário | Features de calendário; o `time_step` em bruto fica apenas no `meta` do payload. |
| `forecast_price_next_*`, `forecast_community_{load,pv,net}_next_*` | `entity_forecasts_derived` | misto | Previsões pontuais a 15m/1h/3h/6h/24h; a sua origem é declarada em `meta.forecast_config`. |

O `request_id` da resposta à procura e a validade da referência são expostos em `observations["meta"]["demand_response"]`, e não como colunas numéricas da tabela.

### `building`

| Grupo de features | Bundle | Unidade | Significado |
|---|---|---:|---|
| Observações flat do edifício ativo | legacy | varia | Features flat não partilhadas e não específicas de ativos. |
| `net/import/export/load/pv/bess/ev_*_power_kw` | `entity_core_electrical` | kW | Potência elétrica por componente. |
| `net/import/export/load/pv/bess/ev_*_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia por passo por componente. |
| `electrical_storage_soc_ratio` | `entity_core_electrical` | rácio | SOC do BESS do edifício. |
| `charging_total_service_power_kw` | `entity_core_electrical` | kW | Potência total do serviço de carregamento. |
| `charging_phase_{L}_power_kw` | `entity_core_electrical` | kW | Potência de carregamento atual por fase. |
| `pv_surplus_power_kw`, `pv_surplus_energy_kwh_step` | `entity_core_electrical` | kW/kWh | Excedente FV local depois da carga não flexível. |
| `building_import/export_headroom_kw`, `import/export_phase_headroom_kw` | `entity_core_electrical` | kW | Margem elétrica local atual. |
| `flexible_*_capacity_kw`, `flexible_*_capacity_kwh_step`, `flexible_energy_*_kwh` | `entity_core_electrical` | misto | Capacidade agregada de carregamento/descarga e folga de energia do BESS e dos VE ligados. |
| `net_energy_prev_1_kwh_step`, `net_energy_prev_3_mean_kwh_step` | `entity_temporal_derived` | kWh/step | Features de desfasamento do edifício. |
| `import_energy_prev_1_kwh_step`, `export_energy_prev_1_kwh_step` | `entity_temporal_derived` | kWh/step | Features de desfasamento de importação/exportação. |
| `hour_sin/cos`, `day_type_sin/cos`, `month_sin/cos`, `seconds_of_day_sin/cos`, `is_weekend` | `entity_temporal_derived` | rácio/binário | Features de calendário. |
| `forecast_{load,pv,net}_next_*` | `entity_forecasts_derived` | kW | Previsões pontuais do edifício a 15m/1h/3h/6h/24h. |

### `charger`

| Feature | Bundle | Unidade | Significado |
|---|---|---:|---|
| `connected_state`, `incoming_state` | legacy | binário | Estado atual de ligação/chegada do VE. |
| `connected_ev_soc`, `connected_ev_required_soc_departure` | legacy | rácio | Campos de SOC do VE ligado. |
| `connected_ev_battery_capacity_kwh` | legacy | kWh | Capacidade do VE ligado. |
| `connected_ev_departure_time_step` | legacy | passos | Passos até à partida. |
| `incoming_ev_estimated_soc_arrival` | legacy | rácio | SOC à chegada do VE que vai chegar. |
| `incoming_ev_estimated_arrival_time_step` | legacy | passos | Passos até à chegada. |
| `last_charged_kwh` | legacy | kWh/step | Última energia comandada. |
| `max_charging_power_kw`, `max_discharging_power_kw` | legacy | kW | Limites de potência do carregador. |
| `min_charging_power_kw`, `min_discharging_power_kw` | `entity_base` | kW | Potências mínimas técnicas. |
| `charger_efficiency_ratio` | `entity_base` | rácio | Eficiência fixa/predefinida. |
| `phase_connection_L1/L2/L3` | `entity_base` | one-hot | Ligação de fase; `all_phases` marca todas as fases. |
| `commanded_power_kw`, `applied_power_kw` | `entity_core_electrical` | kW | Potência comandada e aplicada do carregador. |
| `applied_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia aplicada. |
| `hours_until_departure`, `time_until_departure_ratio` | `entity_core_electrical` | horas/rácio | Pressão temporal do VE ligado. |
| `energy_to_required_soc_kwh`, `required_average_power_kw` | `entity_core_electrical` | kWh/kW | Energia e potência média necessárias para atingir o SOC de partida. |
| `charging_slack_kw`, `charging_priority_ratio` | `entity_core_electrical` | kW/rácio | Descritores da urgência de carregamento. |
| `connected_ev_soc_min_ratio`, `connected_ev_energy_available_kwh`, `connected_ev_energy_to_full_kwh` | `entity_core_electrical` | misto | Energia de descarga utilizável do VE ligado e margem de carregamento restante ([energia até à carga completa](#energia-até-à-carga-completa)). |
| `can_charge`, `can_discharge`, `available_charge/discharge_power_kw`, `available_charge/discharge_action_normalized` | `entity_core_electrical` | misto | Capacidade de ação viável atual do carregador depois dos limites de SOC, disponibilidade, corte de energia e margem. |
| `max_deliverable_energy_until_departure_kwh`, `departure_energy_margin_kwh` | `entity_core_electrical` | kWh | Energia ainda entregável até à partida com os limites atuais e a sua margem sobre a energia exigida. |
| `departure_feasibility_ratio`, `min_required_action_normalized` | `entity_core_electrical` | rácio | Pressão do prazo; valores acima de `1` indicam que o alvo precisa de mais do que a ação viável/máxima atual. |
| `charge_efficiency_at_max_ratio`, `discharge_efficiency_at_max_ratio` | `entity_core_electrical` | rácio | Valores da curva de eficiência à potência máxima. |
| `incoming_ev_required_soc_departure`, `incoming_ev_departure_time_step` | `entity_core_electrical` | rácio/passos | Requisito de partida do VE que vai chegar, quando conhecido. |
| `incoming_ev_hours_until_departure`, `incoming_ev_time_until_departure_ratio` | `entity_core_electrical` | horas/rácio | Pressão temporal do VE que vai chegar. |
| `last_requested_*`, `last_limited_*`, `last_applied_power_kw`, `last_projection_error_kw` | `entity_action_feedback` | misto | Pedido bruto anterior da política, comando depois das restrições e potência do carregador fisicamente aplicada. |
| `applied_energy_prev_15m_kwh`, `applied_power_mean_prev_15m_kw`, `time_since_last_nonzero_action_hours` | `entity_action_feedback` | misto | Histórico curto de ações e da sua aplicação. |
| `clip_reason_*` | `entity_action_feedback` | binário | Causas de corte (clipping) em one-hot: disponibilidade, potência/banda morta, SOC, margem do edifício/fase/exportação, corte de energia ou janela do aparelho diferível. |

### `ev`

| Feature | Bundle | Unidade | Significado |
|---|---|---:|---|
| `soc` | legacy | rácio | SOC do VE. |
| `battery_capacity_kwh` | legacy | kWh | Capacidade da bateria do VE. |
| `depth_of_discharge_ratio` | legacy | rácio | Profundidade de descarga permitida. |
| `soc_ratio`, `soc_min_ratio`, `soc_max_ratio` | `entity_core_electrical` | rácio | Limites canónicos de SOC. |
| `energy_available_kwh`, `energy_to_full_kwh` | `entity_core_electrical` | kWh | Energia utilizável e [energia até à carga completa](#energia-até-à-carga-completa). |

### `storage`

| Feature | Bundle | Unidade | Significado |
|---|---|---:|---|
| `soc`, `capacity_kwh`, `nominal_power_kw`, `electricity_consumption_kwh` | legacy | misto | Estado do BESS e consumo liquidado. |
| `min_charge_power_kw`, `min_discharge_power_kw` | `entity_base` | kW | Potências mínimas técnicas. |
| `efficiency_ratio` | `entity_base` | rácio | Eficiência nominal de ida e volta (round-trip). |
| `round_trip_efficiency_ratio` | `entity_base` | rácio | Eficiência num sentido na última operação, a raiz quadrada da eficiência de ida e volta atual. O nome mantém-se por causa dos layouts de observação existentes. |
| `phase_connection_L1/L2/L3` | `entity_base` | one-hot | Ligação de fase do armazenamento. |
| `electrical_storage_soc_ratio` | `entity_core_electrical` | rácio | SOC canónico do BESS. |
| `max_charge_power_kw`, `max_discharge_power_kw` | `entity_core_electrical` | kW | Potências máximas atuais. |
| `energy_to_full_kwh`, `energy_available_kwh` | `entity_core_electrical` | kWh | Margem de energia ([energia até à carga completa](#energia-até-à-carga-completa)) e energia disponível. |
| `can_charge`, `can_discharge`, `available_charge/discharge_power_kw`, `available_charge/discharge_action_normalized` | `entity_core_electrical` | misto | Capacidade de ação viável atual do BESS depois dos limites de SOC, corte de energia e margem. |
| `available_charge_energy_kwh_step`, `available_discharge_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia viável do BESS neste passo depois dos limites de SOC/margem/corte de energia. |
| `max_charge_energy_kwh_step`, `max_discharge_energy_kwh_step` | `entity_core_electrical` | kWh/step | Limite de potência nominal do BESS convertido para a duração deste passo. |
| `charge_headroom_ratio`, `discharge_available_ratio`, `usable_soc_ratio` | `entity_core_electrical` | rácio | Margem de carregamento, energia de descarga e SOC dentro da gama utilizável do BESS, normalizados. |
| `current_efficiency_ratio`, `degraded_capacity_kwh`, `soc_min_ratio` | `entity_core_electrical` | misto | Eficiência atual, capacidade degradada e SOC mínimo. |
| `last_requested_*`, `last_limited_*`, `last_applied_power_kw`, `last_projection_error_kw`, `clip_reason_*` | `entity_action_feedback` | misto | Pedido de ação anterior do BESS, comando limitado, potência aplicada e causas de corte. |

### Energia até à carga completa

O SOC é relativo à capacidade nominal (`capacity_kwh`, `battery_capacity_kwh`).
A perda de capacidade reduz a capacidade degradada de uma bateria
(`degraded_capacity_kwh` no armazenamento), onde `Battery.charge` para, pelo
que uma bateria degradada fica cheia abaixo de um SOC de 1. Na versão 2 da
física, a predefinida, `energy_to_full_kwh`, `connected_ev_energy_to_full_kwh`
e `flexible_energy_to_full_kwh` são a energia que a bateria ainda aceita: o
menor entre `soc_max_ratio` vezes a capacidade e a capacidade degradada, menos
a energia armazenada. As features de carregamento derivadas delas (`can_charge`,
`available_charge_power_kw`, `available_charge_action_normalized`,
`available_charge_energy_kwh_step`, `charge_headroom_ratio`,
`max_deliverable_energy_until_departure_kwh`, `departure_energy_margin_kwh`,
`departure_feasibility_ratio` e as somas `flexible_charge_*` e
`community_flexible_*`) acompanham-nas. Na versão 1 da física são calculadas a
partir da capacidade nominal, como no CityLearn 3.6.0, e indicam que uma
bateria degradada cheia ainda pode carregar. As baterias sem perda de
capacidade (`capacity_loss_coefficient` 0) dão os mesmos valores nas duas
versões.

### `pv`

Presente apenas quando `entity_core_electrical` está ativado. Tal como as outras features elétricas do bundle core, estes são valores endógenos do último intervalo liquidado, e não entradas exógenas do intervalo seguinte.

| Feature | Unidade | Significado |
|---|---:|---|
| `generation_power_kw` | kW | Produção FV como potência, no último intervalo liquidado (linha t). |
| `generation_energy_kwh_step` | kWh/step | Produção FV no último intervalo liquidado (linha t quando a observação é para t+1); `building.solar_generation` é o intervalo seguinte (linha t+1). |
| `installed_power_kw` | kW | Potência FV instalada. |
| `generation_capacity_factor_ratio` | rácio | `generation_power_kw / installed_power_kw`. |

### `deferrable_appliance`

As features base dos aparelhos diferíveis estão em `entity_base`; as definições estão na tabela flat de aparelhos diferíveis acima. Os aparelhos diferíveis entity incluem também `remaining_duration_hours`, `cycle_remaining_fraction_ratio`, `hours_until_earliest_start`, `start_window_width_hours`, `start_energy_kwh_step`, `start_power_kw` e `must_start_now`, para a pressão de prazo em RL. Com `entity_action_feedback`, os aparelhos diferíveis expõem também `last_start_requested`, `last_start_applied`, `start_blocked` e `clip_reason_*`.

As previsões derivadas usam por omissão os valores futuros do dataset, por
compatibilidade com versões anteriores (`load_pv_method = "actual_future"`).
Um schema pode antes definir `derived_forecasts.load_pv_method = "daily_persistence"`;
a carga e o FV usam então apenas a observação correspondente do dia anterior,
com um arranque a frio (cold start) no passo atual. O preço respeita a
fronteira de publicação declarada do mercado do dia seguinte: os valores OMIE
realizados só são expostos depois da publicação e, caso contrário, é usado o
fallback causal do schema (persistência diária na suite REC anual). As origens
exatas são expostas em `meta.forecast_config`; os adaptadores para o mundo real
devem preencher campos equivalentes a partir de previsões operacionais.

## Arestas entity

| Aresta | Forma | Liga |
|---|---:|---|
| `district_to_building` | `(n_buildings, 2)` | Linha 0 do distrito a cada edifício. |
| `building_to_charger` | `(n_chargers, 2)` | Edifício ao carregador. |
| `building_to_storage` | `(n_storage, 2)` | Edifício ao BESS. |
| `building_to_pv` | `(n_pv, 2)` | Edifício ao FV. |
| `building_to_deferrable_appliance` | `(n_appliances, 2)` | Edifício ao aparelho diferível. |
| `charger_to_ev_connected` | `(n_chargers, 2)` | Carregador ao VE ligado; linha `-1` quando ausente. |
| `charger_to_ev_connected_mask` | `(n_chargers,)` | Máscara das arestas de ligação válidas. |
| `charger_to_ev_incoming` | `(n_chargers, 2)` | Carregador ao VE que vai chegar. |
| `charger_to_ev_incoming_mask` | `(n_chargers,)` | Máscara das arestas de chegada válidas. |
