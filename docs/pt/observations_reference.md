# Observations Reference

Esta pagina e o dicionario de observacoes do simulador. O objetivo e ser legivel para humanos e tambem servir como contrato para wrappers, ORL, GraphRL e Transformers.

## Contrato de Unidades

| Sufixo/nome | Unidade | Exemplo |
|---|---:|---|
| `_power_kw`, `_kw`, `headroom_kw` | kW | `generation_power_kw`, `charging_slack_kw`. |
| `_energy_kwh_step`, `_kwh_step` | kWh/step | `net_energy_kwh_step`. |
| `_kwh` | kWh | `capacity_kwh`, `energy_to_full_kwh`. |
| `_soc`, `_soc_ratio`, `_ratio` | ratio | `electrical_storage_soc`, `service_level_ratio`. |
| `_time_step` | indice global/local conforme contexto | `deadline_time_step`. |
| `hours_until_*` | horas | `hours_until_departure`. |
| `*_count` | contagem | `active_buildings_count`. |
| `electricity_pricing` | EUR/kWh ou currency/kWh | Depende do dataset. |
| `carbon_intensity` | kgCO2/kWh | Emissoes grid. |
| Temperaturas | C | `outdoor_dry_bulb_temperature`. |
| Irradiancia | W/m2 | `direct_solar_irradiance`. |

Valores sentinela comuns:

| Valor | Significado |
|---:|---|
| `-1` | Tempo/ID/quantidade indisponivel. |
| `-0.1` | SOC desconhecido/EV ausente. |
| `0` | Feature nao aplicavel quando zero e fisicamente valido ou entidade inexistente na tabela. |

## Flat Observations

Flat observations sao controladas por `schema["observations"]`. Em `central_agent=True`, as observacoes com `shared_in_central_agent=true` aparecem apenas uma vez no vetor central.

### Calendario

| Observacao | Unidade | O que e | Notas |
|---|---:|---|---|
| `month` | indice 1-12 | Mes. | Pode ser normalizado por wrappers externos. |
| `day_type` | indice 1-8 | Dia da semana ou dia especial. | 1-7 segunda-domingo, 8 especial. |
| `hour` | indice 1-24 | Hora. | Mantem contrato original CityLearn. |
| `minutes` | indice 0-59 | Minuto. | So aparece se a coluna existir. |
| `seconds` | indice 0-59 | Segundo. | Necessario para datasets sub-minuto. |
| `daylight_savings_status` | binario | DST ativo/inativo. | 0/1. |

### Weather

| Observacao | Unidade | O que e |
|---|---:|---|
| `outdoor_dry_bulb_temperature` | C | Temperatura exterior. |
| `outdoor_relative_humidity` | percent | Humidade relativa exterior. |
| `diffuse_solar_irradiance` | W/m2 | Irradiancia difusa. |
| `direct_solar_irradiance` | W/m2 | Irradiancia direta. |
| `*_predicted_1` | mesma unidade | Forecast horizonte 1 do dataset. |
| `*_predicted_2` | mesma unidade | Forecast horizonte 2 do dataset. |
| `*_predicted_3` | mesma unidade | Forecast horizonte 3 do dataset. |

O simulador nao assume que os horizontes sejam sempre 6/12/24h. Eles sao o que o dataset codifica.

### Pricing e Carbon

| Observacao | Unidade | O que e |
|---|---:|---|
| `electricity_pricing` | currency/kWh | Preco atual de import grid. |
| `electricity_pricing_predicted_1` | currency/kWh | Forecast de preco. |
| `electricity_pricing_predicted_2` | currency/kWh | Forecast de preco. |
| `electricity_pricing_predicted_3` | currency/kWh | Forecast de preco. |
| `carbon_intensity` | kgCO2/kWh | Intensidade carbonica da grid. |

### Loads, Comfort e HVAC

| Observacao | Unidade | O que e |
|---|---:|---|
| `indoor_dry_bulb_temperature` | C | Temperatura interior. |
| `average_unmet_cooling_setpoint_difference` | C | Desvio medio face ao setpoint cooling. |
| `indoor_relative_humidity` | percent | Humidade interior. |
| `occupant_count` | pessoas | Ocupacao. |
| `indoor_dry_bulb_temperature_cooling_set_point` | C | Setpoint cooling. |
| `indoor_dry_bulb_temperature_heating_set_point` | C | Setpoint heating. |
| `indoor_dry_bulb_temperature_cooling_delta` | C | Delta controlado por occupant/dynamics. |
| `indoor_dry_bulb_temperature_heating_delta` | C | Delta controlado por occupant/dynamics. |
| `comfort_band` | C | Banda de conforto. |
| `hvac_mode` | enum | 0 off, 1 cooling, 2 heating, 3 auto. |
| `cooling_demand` | kWh/step | Demanda termica cooling. |
| `heating_demand` | kWh/step | Demanda termica heating. |
| `dhw_demand` | kWh/step | Demanda DHW. |
| `non_shiftable_load` | kWh/step | Consumo nao flexivel. |
| `cooling_device_efficiency` | COP/ratio | Eficiencia instantanea cooling. |
| `heating_device_efficiency` | COP/ratio | Eficiencia instantanea heating. |
| `dhw_device_efficiency` | COP/ratio | Eficiencia instantanea DHW. |

### Storage e Net Energy

| Observacao | Unidade | O que e |
|---|---:|---|
| `cooling_storage_soc` | ratio | SOC storage cooling. |
| `heating_storage_soc` | ratio | SOC storage heating. |
| `dhw_storage_soc` | ratio | SOC storage DHW. |
| `electrical_storage_soc` | ratio | SOC BESS. |
| `cooling_electricity_consumption` | kWh/step | Eletricidade do cooling device. |
| `heating_electricity_consumption` | kWh/step | Eletricidade do heating device. |
| `dhw_electricity_consumption` | kWh/step | Eletricidade DHW. |
| `cooling_storage_electricity_consumption` | kWh/step | Eletricidade associada ao storage cooling. |
| `heating_storage_electricity_consumption` | kWh/step | Eletricidade associada ao storage heating. |
| `dhw_storage_electricity_consumption` | kWh/step | Eletricidade associada ao storage DHW. |
| `electrical_storage_electricity_consumption` | kWh/step | Consumo BESS. Positivo carrega, negativo descarrega. |
| `solar_generation` | kWh/step | Geracao PV ja convertida pelo modo PV. |
| `net_electricity_consumption` | kWh/step | Import positivo, export negativo. |
| `power_outage` | binario | Outage no timestep. |
| `power_outage_unserved_energy` | kWh/step | Carga nao atendida durante o outage, como no KPI `power_outage_normalized_unserved_energy_total`. Zero sem outage. Apenas na interface flat; a tabela entity `building` não a inclui. |
| `available_grid_power` | kW | Limite de importacao do proximo intervalo: o menor entre o `import_kw` estatico e a serie [available_grid_power](schema_reference.md#potencia-de-rede-disponivel). So com serie. Apenas na interface flat; na interface entity as margens do edificio seguem o limite. |

### EV e Charger Flat

As chaves base no schema sao expandidas por charger.

| Chave schema | Chave expandida | Unidade | O que e |
|---|---|---:|---|
| `electric_vehicle_charger_connected_state` | `electric_vehicle_charger_{id}_connected_state` | binario | EV ligado e pronto a carregar. |
| `connected_electric_vehicle_at_charger_departure_time` | `connected_electric_vehicle_at_charger_{id}_departure_time` | steps | Steps ate departure do EV ligado. |
| `connected_electric_vehicle_at_charger_required_soc_departure` | `connected_electric_vehicle_at_charger_{id}_required_soc_departure` | ratio | SOC requerido no departure. |
| `connected_electric_vehicle_at_charger_soc` | `connected_electric_vehicle_at_charger_{id}_soc` | ratio | SOC atual do EV ligado. |
| `connected_electric_vehicle_at_charger_battery_capacity` | `connected_electric_vehicle_at_charger_{id}_battery_capacity` | kWh | Capacidade do EV ligado. |
| `electric_vehicle_charger_incoming_state` | `electric_vehicle_charger_{id}_incoming_state` | binario | EV incoming para esse charger. |
| `incoming_electric_vehicle_at_charger_estimated_arrival_time` | `incoming_electric_vehicle_at_charger_{id}_estimated_arrival_time` | steps | Steps ate chegada estimada. |
| `incoming_electric_vehicle_at_charger_estimated_soc_arrival` | `incoming_electric_vehicle_at_charger_{id}_estimated_soc_arrival` | ratio | SOC estimado na chegada. |

### Deferrable Flat

As chaves base `deferrable_appliance_*` sao expandidas por appliance.

| Feature | Unidade | O que e |
|---|---:|---|
| `pending` | binario | Ha ciclo pendente exposto. |
| `running` | binario | Ciclo atual esta em execucao. |
| `can_start` | binario | Start seria aceito neste step. |
| `deadline_missed` | binario | Ciclo exposto falhou deadline/latest start. |
| `earliest_start_time_step` | timestep global | Primeiro start permitido. |
| `latest_start_time_step` | timestep global | Ultimo start permitido. |
| `deadline_time_step` | timestep global | Deadline de conclusao. |
| `hours_until_latest_start` | h | Horas ate ultimo start. |
| `hours_until_deadline` | h | Horas ate deadline. |
| `slack_steps` | steps | Folga ate latest start. |
| `slack_ratio` | ratio | Folga normalizada na janela. |
| `urgency_ratio` | ratio | `1 - slack_ratio`. |
| `cycle_duration_steps` | steps | Duracao do ciclo. |
| `cycle_energy_kwh` | kWh | Energia total do ciclo. |
| `remaining_energy_kwh` | kWh | Energia ainda por servir. |
| `current_step_energy_kwh` | kWh/step | Energia do perfil no step atual. |
| `priority` | ratio | Prioridade do pedido. |
| `must_run` | binario | Pedido obrigatorio. |
| `cycle_average_power_kw` | kW | Energia total / duracao. |
| `cycle_peak_power_kw` | kW | Pico do perfil. |
| `cycle_load_factor_ratio` | ratio | Average/peak. |
| `cycle_peak_step_offset_ratio` | ratio | Posicao normalizada do pico no ciclo. |
| `remaining_duration_steps` | steps | Steps restantes do ciclo. |
| `remaining_average_power_kw` | kW | Energia restante / duracao restante. |
| `current_step_power_kw` | kW | Potencia equivalente do step atual. |

## Entity Observations

Entity mode retorna tabelas. As features disponiveis dependem do schema, dos assets presentes e dos bundles ativos.

## Tabela `district`

| Feature | Bundle | Unidade | O que e |
|---|---|---:|---|
| Shared flat observations | legacy | varia | Observacoes partilhadas do primeiro building, como calendario/weather/pricing. |
| Forecasts `*_predicted_*` | `entity_forecasts_existing` | varia | Forecasts existentes no dataset. |
| `community_net_power_kw` | `entity_community_operational` | kW | Net power agregada da comunidade. |
| `community_net_energy_kwh_step` | `entity_community_operational` | kWh/step | Net energy agregada. |
| `community_import_power_kw` | `entity_community_operational` | kW | Import positivo agregado. |
| `community_import_energy_kwh_step` | `entity_community_operational` | kWh/step | Import agregado. |
| `community_export_power_kw` | `entity_community_operational` | kW | Export agregado. |
| `community_export_energy_kwh_step` | `entity_community_operational` | kWh/step | Export agregado. |
| `community_pv_power_kw` | `entity_community_operational` | kW | PV agregado. |
| `community_pv_energy_kwh_step` | `entity_community_operational` | kWh/step | Energia PV agregada. |
| `community_bess_power_kw` | `entity_community_operational` | kW | Potencia BESS agregada. |
| `community_bess_energy_kwh_step` | `entity_community_operational` | kWh/step | Energia BESS agregada. |
| `community_ev_power_kw` | `entity_community_operational` | kW | Potencia EV agregada. |
| `community_ev_energy_kwh_step` | `entity_community_operational` | kWh/step | Energia EV agregada. |
| `community_building_headroom_kw` | `entity_community_operational` | kW | Headroom import total dos buildings. |
| `community_building_export_headroom_kw` | `entity_community_operational` | kW | Headroom export total. |
| `community_phase_headroom_kw` | `entity_community_operational` | kW | Headroom import por fases agregado. |
| `community_phase_export_headroom_kw` | `entity_community_operational` | kW | Headroom export por fases agregado. |
| `community_flexible_*_capacity_kw`, `community_flexible_*_capacity_kwh_step`, `community_flexible_energy_*_kwh` | `entity_community_operational` | varia | Flexibilidade agregada da comunidade para carga/descarga e folga energetica. |
| `active_buildings_count` | `entity_community_operational` | count | Buildings ativos. |
| `active_chargers_count` | `entity_community_operational` | count | Chargers ativos. |
| `active_evs_count` | `entity_community_operational` | count | EVs ativos. |
| `topology_version` | `entity_community_operational` | count | Versao da topologia. |
| `dr_active` | `entity_demand_response` | binario | Se existe pedido demand response ativo neste timestep. |
| `dr_issuer_code` | `entity_demand_response` | enum | Codigo do issuer: `1=dso`, `2=tso`, `0=nenhum/desconhecido`. |
| `dr_direction` | `entity_demand_response` | enum | Direcao na perspetiva da carga: `1=up`, `-1=down`, `0=nenhuma`. |
| `dr_target_power_kw` | `entity_demand_response` | kW | Target district do pedido ativo. |
| `dr_baseline_power_kw` | `entity_demand_response` | kW | Baseline net power congelado do pedido ativo quando valido. |
| `dr_time_remaining_hours` | `entity_demand_response` | h | Tempo restante na janela inclusiva de ativacao. |
| `dr_activation_price_eur_per_kwh` | `entity_demand_response` | currency/kWh | Preco creditado por energia entregue. |
| `dr_shortfall_penalty_eur_per_kwh` | `entity_demand_response` | currency/kWh | Penalizacao por energia em shortfall. |
| `dr_previous_delivered_power_kw` | `entity_demand_response` | kW | Potencia entregue liquidada no step DR ativo anterior. |
| `dr_previous_shortfall_power_kw` | `entity_demand_response` | kW | Shortfall liquidado no step DR ativo anterior. |
| `community_net_prev_1_kwh_step` | `entity_temporal_derived` | kWh/step | Lag 1 da net community. |
| `community_net_prev_3_mean_kwh_step` | `entity_temporal_derived` | kWh/step | Media curta da net community. |
| `hour_sin/cos`, `day_type_sin/cos`, `month_sin/cos`, `seconds_of_day_sin/cos`, `is_weekend` | `entity_temporal_derived` | ratio/binario | Calendario robusto; `time_step` cru fica apenas em `meta`. |
| `forecast_price_next_*`, `forecast_community_{load,pv,net}_next_*` | `entity_forecasts_derived` | varia | Forecasts pontuais a 15m/1h/3h/6h/24h; a origem e declarada em `meta.forecast_config`. |

O `request_id` e validade da baseline de demand response ficam em `observations["meta"]["demand_response"]`, nao como colunas numericas.

## Tabela `building`

| Feature | Bundle | Unidade | O que e |
|---|---|---:|---|
| Active flat building observations | legacy | varia | Observacoes flat nao partilhadas e nao especificas de assets. |
| `net_power_kw` | `entity_core_electrical` | kW | Net do building em potencia. |
| `net_energy_kwh_step` | `entity_core_electrical` | kWh/step | Net do building no step. |
| `import_power_kw` | `entity_core_electrical` | kW | Import do building. |
| `import_energy_kwh_step` | `entity_core_electrical` | kWh/step | Import no step. |
| `export_power_kw` | `entity_core_electrical` | kW | Export do building. |
| `export_energy_kwh_step` | `entity_core_electrical` | kWh/step | Export no step. |
| `load_power_kw` | `entity_core_electrical` | kW | Carga agregada. |
| `load_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia de carga agregada. |
| `pv_power_kw` | `entity_core_electrical` | kW | PV do building. |
| `pv_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia PV. |
| `pv_surplus_power_kw` | `entity_core_electrical` | kW | Excedente PV local depois da carga nao flexivel. |
| `pv_surplus_energy_kwh_step` | `entity_core_electrical` | kWh/step | Excedente PV local no step. |
| `bess_power_kw` | `entity_core_electrical` | kW | Potencia BESS. |
| `bess_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia BESS. |
| `ev_charging_power_kw` | `entity_core_electrical` | kW | Potencia EV charging. |
| `ev_charging_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia EV charging. |
| `electrical_storage_soc_ratio` | `entity_core_electrical` | ratio | SOC BESS. |
| `charging_total_service_power_kw` | `entity_core_electrical` | kW | Potencia charging total a passar no servico. |
| `charging_phase_{L}_power_kw` | `entity_core_electrical` | kW | Potencia atual por fase. |
| `building_import/export_headroom_kw`, `import/export_phase_headroom_kw` | `entity_core_electrical` | kW | Headroom eletrico local atual. |
| `flexible_*_capacity_kw`, `flexible_*_capacity_kwh_step`, `flexible_energy_*_kwh` | `entity_core_electrical` | varia | Capacidade agregada BESS + EVs ligados para carga/descarga e folga energetica. |
| `net_energy_prev_1_kwh_step` | `entity_temporal_derived` | kWh/step | Net lag 1. |
| `net_energy_prev_3_mean_kwh_step` | `entity_temporal_derived` | kWh/step | Media net lag 3. |
| `import_energy_prev_1_kwh_step` | `entity_temporal_derived` | kWh/step | Import lag 1. |
| `export_energy_prev_1_kwh_step` | `entity_temporal_derived` | kWh/step | Export lag 1. |
| `hour_sin/cos`, `day_type_sin/cos`, `month_sin/cos`, `seconds_of_day_sin/cos`, `is_weekend` | `entity_temporal_derived` | ratio/binario | Calendario robusto. |
| `forecast_{load,pv,net}_next_*` | `entity_forecasts_derived` | kW | Forecasts pontuais por building a 15m/1h/3h/6h/24h. |

## Tabela `charger`

| Feature | Bundle | Unidade | O que e |
|---|---|---:|---|
| `connected_state` | legacy | binario | EV ligado. |
| `incoming_state` | legacy | binario | EV incoming. |
| `connected_ev_soc` | legacy | ratio | SOC do EV ligado. |
| `connected_ev_required_soc_departure` | legacy | ratio | SOC requerido no departure. |
| `connected_ev_battery_capacity_kwh` | legacy | kWh | Capacidade do EV ligado. |
| `connected_ev_departure_time_step` | legacy | steps | Steps ate departure. |
| `incoming_ev_estimated_soc_arrival` | legacy | ratio | SOC estimado na chegada. |
| `incoming_ev_estimated_arrival_time_step` | legacy | steps | Steps ate chegada. |
| `last_charged_kwh` | legacy | kWh/step | Comando de energia anterior. |
| `max_charging_power_kw` | legacy | kW | Limite max charging. |
| `max_discharging_power_kw` | legacy | kW | Limite max discharging. |
| `min_charging_power_kw` | `entity_base` | kW | Minimo tecnico charging. |
| `min_discharging_power_kw` | `entity_base` | kW | Minimo tecnico discharging. |
| `charger_efficiency_ratio` | `entity_base` | ratio | Eficiencia fixa/default. |
| `phase_connection_L1/L2/L3` | `entity_base` | one-hot | Ligacao de fase. `all_phases` marca L1/L2/L3 como 1. |
| `commanded_power_kw` | `entity_core_electrical` | kW | Potencia comandada pelo agente. |
| `applied_power_kw` | `entity_core_electrical` | kW | Potencia efetivamente aplicada. |
| `applied_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia aplicada. |
| `hours_until_departure` | `entity_core_electrical` | h | Tempo ate departure do EV ligado. |
| `time_until_departure_ratio` | `entity_core_electrical` | ratio | Horas ate departure / 24, clipped. |
| `energy_to_required_soc_kwh` | `entity_core_electrical` | kWh | Energia necessaria para SOC requerido. |
| `required_average_power_kw` | `entity_core_electrical` | kW | Energia necessaria / horas ate departure. |
| `avg_power_to_departure_kw` | `entity_core_electrical` | kW | Alias operacional do anterior. |
| `charging_slack_kw` | `entity_core_electrical` | kW | `max_charging_power - required_average_power`. |
| `charging_priority_ratio` | `entity_core_electrical` | ratio | Urgencia energetica normalizada. |
| `connected_ev_soc_min_ratio` | `entity_core_electrical` | ratio | SOC minimo descarregavel do EV ligado. |
| `connected_ev_energy_available_kwh` | `entity_core_electrical` | kWh | Energia V2G disponivel acima do SOC minimo. |
| `connected_ev_energy_to_full_kwh` | `entity_core_electrical` | kWh | Energia que ainda cabe no EV ligado. |
| `can_charge`, `can_discharge` | `entity_core_electrical` | binario | Se ha capacidade factivel de carga/descarga agora. |
| `available_charge/discharge_power_kw` | `entity_core_electrical` | kW | Potencia factivel agora depois de SOC, availability, outage e headroom. |
| `available_charge/discharge_action_normalized` | `entity_core_electrical` | ratio | Magnitude normalizada da acao ainda factivel. |
| `max_deliverable_energy_until_departure_kwh` | `entity_core_electrical` | kWh | Energia ainda entregavel ate departure sob limites atuais. |
| `departure_energy_margin_kwh` | `entity_core_electrical` | kWh | Margem entre energia entregavel e energia requerida. |
| `departure_feasibility_ratio` | `entity_core_electrical` | ratio | Pressao de deadline; acima de 1 indica target acima do entregavel atual. |
| `min_required_action_normalized` | `entity_core_electrical` | ratio | Acao minima media normalizada necessaria; acima de 1 indica impossibilidade pelo max power atual. |
| `charge_efficiency_at_max_ratio` | `entity_core_electrical` | ratio | Eficiencia da curva em potencia maxima de carga. |
| `discharge_efficiency_at_max_ratio` | `entity_core_electrical` | ratio | Eficiencia da curva em potencia maxima de descarga. |
| `incoming_ev_required_soc_departure` | `entity_core_electrical` | ratio | Required SOC do EV incoming se conhecido. |
| `incoming_ev_departure_time_step` | `entity_core_electrical` | steps | Departure do EV incoming se conhecido. |
| `incoming_ev_hours_until_departure` | `entity_core_electrical` | h | Horas ate departure do EV incoming. |
| `incoming_ev_time_until_departure_ratio` | `entity_core_electrical` | ratio | Horas ate departure / 24. |
| `last_requested_*`, `last_limited_*`, `last_applied_power_kw`, `last_projection_error_kw` | `entity_action_feedback` | varia | Pedido bruto da policy, comando apos constraints e potencia fisicamente aplicada. |
| `applied_energy_prev_15m_kwh`, `applied_power_mean_prev_15m_kw`, `time_since_last_nonzero_action_hours` | `entity_action_feedback` | varia | Historico curto de acao/aplicacao. |
| `clip_reason_*` | `entity_action_feedback` | binario | Motivos de clipping: availability, power/deadband, SOC, headroom building/fase/export, outage ou janela deferrable. |

## Tabela `ev`

| Feature | Bundle | Unidade | O que e |
|---|---|---:|---|
| `soc` | legacy | ratio | SOC atual. |
| `battery_capacity_kwh` | legacy | kWh | Capacidade da bateria. |
| `depth_of_discharge_ratio` | legacy | ratio | Profundidade de descarga permitida. |
| `soc_ratio` | `entity_core_electrical` | ratio | SOC canonico. |
| `soc_min_ratio` | `entity_core_electrical` | ratio | SOC minimo derivado de depth of discharge. |
| `soc_max_ratio` | `entity_core_electrical` | ratio | SOC maximo, normalmente 1. |
| `energy_available_kwh` | `entity_core_electrical` | kWh | Energia descarregavel acima de `soc_min`. |
| `energy_to_full_kwh` | `entity_core_electrical` | kWh | Energia ate 100%. |

## Tabela `storage`

| Feature | Bundle | Unidade | O que e |
|---|---|---:|---|
| `soc` | legacy | ratio | SOC BESS. |
| `capacity_kwh` | legacy | kWh | Capacidade nominal. |
| `nominal_power_kw` | legacy | kW | Potencia nominal. |
| `electricity_consumption_kwh` | legacy | kWh/step | Consumo BESS no step settled. |
| `min_charge_power_kw` | `entity_base` | kW | Minimo tecnico de carga. |
| `min_discharge_power_kw` | `entity_base` | kW | Minimo tecnico de descarga. |
| `efficiency_ratio` | `entity_base` | ratio | Eficiencia base. |
| `round_trip_efficiency_ratio` | `entity_base` | ratio | Eficiencia round-trip. |
| `phase_connection_L1/L2/L3` | `entity_base` | one-hot | Ligacao de fase do storage. |
| `electrical_storage_soc_ratio` | `entity_core_electrical` | ratio | SOC canonico. |
| `max_charge_power_kw` | `entity_core_electrical` | kW | Potencia maxima de carga no estado atual. |
| `max_discharge_power_kw` | `entity_core_electrical` | kW | Potencia maxima de descarga no estado atual. |
| `energy_to_full_kwh` | `entity_core_electrical` | kWh | Energia ate capacidade cheia. |
| `energy_available_kwh` | `entity_core_electrical` | kWh | Energia acima do SOC minimo. |
| `can_charge`, `can_discharge` | `entity_core_electrical` | binario | Se o BESS pode carregar/descarregar agora. |
| `available_charge/discharge_power_kw` | `entity_core_electrical` | kW | Potencia BESS factivel agora depois de SOC, outage e headroom. |
| `available_charge/discharge_action_normalized` | `entity_core_electrical` | ratio | Magnitude normalizada de acao BESS ainda factivel. |
| `available_charge_energy_kwh_step`, `available_discharge_energy_kwh_step` | `entity_core_electrical` | kWh/step | Energia BESS factivel neste step apos limites de SOC/headroom/outage. |
| `max_charge_energy_kwh_step`, `max_discharge_energy_kwh_step` | `entity_core_electrical` | kWh/step | Limite nominal de potencia BESS convertido para a duracao do step. |
| `charge_headroom_ratio`, `discharge_available_ratio`, `usable_soc_ratio` | `entity_core_electrical` | ratio | Headroom de carga, energia descarregavel e SOC dentro da faixa usavel. |
| `current_efficiency_ratio` | `entity_core_electrical` | ratio | Eficiencia corrente. |
| `degraded_capacity_kwh` | `entity_core_electrical` | kWh | Capacidade apos degradacao. |
| `soc_min_ratio` | `entity_core_electrical` | ratio | SOC minimo derivado de DoD. |
| `last_requested_*`, `last_limited_*`, `last_applied_power_kw`, `last_projection_error_kw`, `clip_reason_*` | `entity_action_feedback` | varia | Pedido, comando limitado, aplicacao real e motivos de clipping BESS. |

## Tabela `pv`

So aparece com `entity_core_electrical`.

| Feature | Unidade | O que e |
|---|---:|---|
| `generation_power_kw` | kW | Geracao PV equivalente em potencia. |
| `generation_energy_kwh_step` | kWh/step | Energia PV no step. |
| `installed_power_kw` | kW | Potencia PV instalada. |
| `generation_capacity_factor_ratio` | ratio | `generation_power_kw / installed_power_kw`. |

## Tabela `deferrable_appliance`

Todas as features pertencem a `entity_base` e sao sempre por appliance.

| Feature | Unidade | O que e |
|---|---:|---|
| `pending` | binario | Ciclo pendente. |
| `running` | binario | Ciclo em execucao. |
| `can_start` | binario | Start seria aceito neste step. |
| `deadline_missed` | binario | Ciclo falhado. |
| `earliest_start_time_step` | timestep global | Primeiro start permitido. |
| `latest_start_time_step` | timestep global | Ultimo start permitido. |
| `deadline_time_step` | timestep global | Deadline de conclusao. |
| `hours_until_latest_start` | h | Tempo ate ultimo start. |
| `hours_until_deadline` | h | Tempo ate deadline. |
| `slack_steps` | steps | Folga ate latest start. |
| `slack_ratio` | ratio | Folga normalizada. |
| `urgency_ratio` | ratio | Urgencia normalizada. |
| `cycle_duration_steps` | steps | Duracao do ciclo. |
| `cycle_energy_kwh` | kWh | Energia total. |
| `remaining_energy_kwh` | kWh | Energia restante. |
| `current_step_energy_kwh` | kWh/step | Energia do ciclo neste step. |
| `priority` | ratio | Prioridade externa. |
| `must_run` | binario | Pedido obrigatorio. |
| `cycle_average_power_kw` | kW | Potencia media do ciclo. |
| `cycle_peak_power_kw` | kW | Potencia pico do ciclo. |
| `cycle_load_factor_ratio` | ratio | Potencia media / pico. |
| `cycle_peak_step_offset_ratio` | ratio | Posicao do pico dentro do ciclo. |
| `remaining_duration_steps` | steps | Duracao restante. |
| `remaining_duration_hours` | h | Duracao restante em tempo fisico. |
| `cycle_remaining_fraction_ratio` | ratio | Fracao de energia do ciclo ainda por executar. |
| `hours_until_earliest_start` | h | Tempo ate primeiro start permitido. |
| `start_window_width_hours` | h | Largura da janela de start. |
| `start_energy_kwh_step`, `start_power_kw` | kWh/kW | Energia/potencia se arrancar agora. |
| `must_start_now` | binario | Deadline de start esta no step atual ou ja passou. |
| `remaining_average_power_kw` | kW | Potencia media necessaria restante. |
| `current_step_power_kw` | kW | Potencia equivalente do step atual. |
| `last_start_requested`, `last_start_applied`, `start_blocked`, `clip_reason_*` | entity_action_feedback | varia | Feedback curto do ultimo comando de start. |

Por compatibilidade, forecasts derivados usam por defeito valores futuros do
dataset (`load_pv_method = "actual_future"`). Um schema pode escolher
`daily_persistence`; nesse caso carga e PV usam apenas o ponto correspondente
do dia anterior, com cold start no step atual. O preco respeita a fronteira de
publicacao declarada para o mercado do dia seguinte: os valores OMIE realizados
so sao expostos depois da publicacao e, antes disso, e usado o fallback causal
do schema (persistencia diaria na suite REC anual). `meta.forecast_config`
expoe a origem efetiva; em uso real, adapters externos devem preencher campos
equivalentes com forecasts operacionais.

## Edges Entity

| Edge | Shape | O que liga |
|---|---:|---|
| `district_to_building` | `(n_buildings, 2)` | district row 0 para cada building. |
| `building_to_charger` | `(n_chargers, 2)` | building para charger. |
| `building_to_storage` | `(n_storage, 2)` | building para BESS. |
| `building_to_pv` | `(n_pv, 2)` | building para PV. |
| `building_to_deferrable_appliance` | `(n_appliances, 2)` | building para appliance. |
| `charger_to_ev_connected` | `(n_chargers, 2)` | charger para EV ligado. Row `-1` se ausente. |
| `charger_to_ev_connected_mask` | `(n_chargers,)` | 1 se edge connected valida. |
| `charger_to_ev_incoming` | `(n_chargers, 2)` | charger para EV incoming. |
| `charger_to_ev_incoming_mask` | `(n_chargers,)` | 1 se edge incoming valida. |
