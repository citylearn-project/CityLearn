# KPIs Reference

O simulador tem duas APIs de KPIs:

| API | Estado | Formato | Uso recomendado |
|---|---|---|---|
| `evaluate()` | legacy | DataFrame com nomes historicos | Compatibilidade com workflows antigos. |
| `evaluate_v2()` | principal | DataFrame com nomes estruturados | Produção, dashboards, comparacao cientifica. |

Para a arvore completa de nomes v2, ver tambem [`KPI_V2_TREE.md`](../KPI_V2_TREE.md).

## Contrato de Unidades

| Unidade no nome | Significado |
|---|---|
| `eur` | Custo monetario. Pode representar outra currency se o dataset usar outra moeda. |
| `kwh` | Energia acumulada. |
| `kgco2` | Emissoes acumuladas. |
| `kw` | Potencia de pico/media. |
| `ratio` | Razao adimensional. |
| `percent` | Percentagem. |
| `count` | Contagem de eventos/ciclos. |
| `hours` | Horas. |
| `c` | Temperatura em Celsius. |

## Convencao KPI v2

```text
level_family_subfamily_metric_variant_unit
```

| Parte | Exemplos |
|---|---|
| `level` | `building`, `district`. |
| `family` | `cost`, `energy_grid`, `emissions`, `solar_self_consumption`, `ev`, `battery`, `electrical_service_phase`, `equity`, `comfort_resilience`, `deferrable_appliance`, `demand_response`, `robustness`. |
| `subfamily` | `total`, `daily_average`, `ratio_to_baseline`, `ratio_to_business_as_usual`, `shape_quality`, `service`. |
| `metric` | `import`, `export`, `charge`, `completed_cycles`. |
| `variant` | `control`, `baseline`, `business_as_usual`, `delta`, `delta_to_business_as_usual`, `total`, `average`, `l1`. |
| `unit` | `eur`, `kwh`, `ratio`, etc. |

Exemplos:

| KPI | Significado |
|---|---|
| `district_cost_total_control_eur` | Custo total do controlo. |
| `district_cost_total_business_as_usual_eur` | Custo total da baseline nativa business-as-usual. |
| `building_energy_grid_total_import_control_kwh` | Import total do building. |
| `building_energy_grid_ratio_to_business_as_usual_import_total_ratio` | Import do building relativo a baseline nativa business-as-usual. |
| `district_energy_grid_shape_quality_ramping_average_to_baseline_ratio` | Ramping medio relativo ao baseline. |
| `district_solar_self_consumption_ratio_self_consumption_ratio` | Self-consumption solar do distrito/comunidade depois de balancear imports e exports dos membros no mesmo timestep. |
| `building_deferrable_appliance_service_completed_cycles_count` | Ciclos deferiveis completados. |
| `district_demand_response_compliance_ratio` | Delivery DR creditado dividido pela energia pedida valida. |
| `district_robustness_action_dropout_count` | Numero de action dropouts aplicados por eventos de robustez. |

## Equacoes Base

Para uma serie net `net_t`, onde import e positivo e export e negativo:

```text
total_import_kwh = sum(max(net_t, 0))
total_export_kwh = sum(max(-net_t, 0))
total_net_exchange_kwh = sum(net_t)
daily_average_x = total_x / simulated_days
delta_x = control_x - baseline_x
ratio_to_baseline_x = control_x / baseline_x
delta_to_business_as_usual_x = control_x - business_as_usual_x
ratio_to_business_as_usual_x = control_x / business_as_usual_x
self_consumption = (solar_generation_total - export_total) / solar_generation_total
```

Safe division devolve `None`/placeholder quando o denominador nao e fisicamente valido.

Os ratios continuam lower-is-better quando o total de referencia e negativo. O net exchange (legacy `zero_net_energy`) e os totais de custo podem ser negativos, para um exportador liquido ou depois de receitas do community market. Os seus ratios ao baseline e ao BAU usam

```text
ratio_x = control_x / reference_x                        se reference_x > 0
ratio_x = 1 + (control_x - reference_x) / |reference_x|  se reference_x < 0
```

Assim 1 continua a significar sem alteracao e um total control maior da um ratio maior. Para uma referencia positiva e o ratio simples. Import, export e emissoes nunca sao negativos e usam o ratio simples.

## Familias Principais

| Familia | Nivel | O que mede |
|---|---|---|
| `cost` | building, district | Custo control/baseline/business-as-usual/delta/ratio. |
| `energy_grid` | building, district | Import, export, net exchange e shape quality. |
| `emissions` | building, district | Emissoes control/baseline/business-as-usual/delta/ratio. |
| `solar_self_consumption` | building, district | Geracao, export e self-consumption. No distrito, export e o export PV-backed net para fora da comunidade. |
| `ev` | building, district | Departures, success rate, deficits, charge e V2G. |
| `battery` | building, district | Charge, discharge, throughput, cycles, capacity fade. |
| `electrical_service_phase` | building, district | Violacoes, imbalance e peaks por fase. |
| `equity` | building, district | Beneficios relativos e distribuicao. |
| `comfort_resilience` | building, district | Discomfort e eventos de outage/resilience. |
| `deferrable_appliance` | building, district | Ciclos completed/missed, service level e energia servida. |
| `demand_response` | building, district | Pedidos de flexibilidade, entrega, shortfall e economia de settlement. |
| `robustness` | building, district | Contadores de perturbacoes de observations, forecasts, actions e assets. |

## KPIs EV

| KPI conceptual | Unidade | O que mede |
|---|---:|---|
| departure count | count | Numero de departures observadas. |
| departure met count | count | Departures em que SOC requerido foi cumprido. |
| departure minimum acceptable count | count | Departures em que o SOC e pelo menos `target_soc - ev_departure_service_tolerance`. |
| departure within tolerance count | count | Departures dentro da tolerancia simetrica configurada. |
| departure target feasible/infeasible count | count | Departures em que o target SOC estrito era/nao era alcancavel carregando sempre na potencia maxima durante o intervalo ligado, depois de eficiencia do charger/bateria e headroom eletrico configurado. |
| departure minimum acceptable feasible/infeasible count | count | Departures em que o SOC minimo aceitavel era/nao era alcancavel sob os mesmos limites de potencia maxima, eficiencia e servico eletrico. |
| departure within tolerance feasible/infeasible count | count | Departures em que o limite inferior da banda de tolerancia simetrica era/nao era alcancavel sob os mesmos limites de potencia maxima, eficiencia e servico eletrico. |
| departure success ratio | ratio | `met / departures`. |
| departure minimum acceptable ratio | ratio | `minimum_acceptable / departures`. Este e o KPI principal de conforto/servico EV. |
| departure within tolerance ratio | ratio | `within_symmetric_tolerance / departures`. |
| departure success feasible ratio | ratio | Cumprimento estrito apenas sobre departures em que o target estrito era fisicamente alcancavel. |
| departure minimum acceptable feasible ratio | ratio | Cumprimento do servico minimo apenas sobre departures em que o minimo era fisicamente alcancavel. Este e o KPI principal de qualidade do controlador. |
| departure within tolerance feasible ratio | ratio | Accuracy simetrica apenas sobre departures em que a banda de tolerancia era fisicamente alcancavel. |
| departure SOC deficit mean | ratio | Deficit medio nao-negativo de SOC por departure. |
| departure shortfall beyond tolerance mean | ratio | Deficit medio abaixo de `target_soc - ev_departure_service_tolerance`. |
| departure SOC surplus mean | ratio | Excesso medio nao-negativo de SOC por departure. |
| departure SOC absolute error mean | ratio | Erro absoluto medio de SOC face ao target pedido. |
| departure tolerance | ratio | Tolerancia de servico configurada para o minimo aceitavel no departure. |
| charge total | kWh | Energia carregada em EVs. |
| V2G export total | kWh | Energia exportada por EVs. |

Semantica das tolerancias EV no departure:

- `ev_departure_success_rate` mede cumprimento estrito: `actual_soc >= target_soc`.
- `ev_departure_min_acceptable_rate` mede servico minimo: `actual_soc >= target_soc - ev_departure_service_tolerance`.
- `ev_departure_within_tolerance_rate` mede proximidade simetrica ao target: `abs(actual_soc - target_soc) <= ev_departure_within_tolerance`.
- As variantes `*_feasible_rate` usam os mesmos numeradores, mas excluem departures em que esse limiar nao era fisicamente alcancavel desde o SOC de chegada, carregando sempre na potencia maxima do charger/bateria durante o intervalo ligado, limitada pelo headroom de importacao do building/fase e pelas eficiencias do charger/bateria.
- Os contadores de feasibility sao diagnosticos da qualidade/cenario do schedule; se faltarem dados de charger, bateria ou SOC de chegada, o departure e tratado como feasible para preservar comportamento legacy.
- As duas tolerancias fazem default para `0.05`.

## KPIs BESS

| KPI conceptual | Unidade | O que mede |
|---|---:|---|
| charge total | kWh | Energia carregada na BESS. |
| discharge total | kWh | Energia descarregada. |
| throughput total | kWh | Charge + discharge absolutos. |
| equivalent full cycles | count | Throughput relativo a capacidade. |
| capacity fade | ratio | Degradacao relativa da capacidade. |

## KPIs Deferrable Appliances

| KPI conceptual | Unidade | O que mede |
|---|---:|---|
| completed cycles | count | Ciclos terminados com sucesso. |
| missed cycles | count | Ciclos que passaram a janela sem start valido. |
| service level | ratio | `completed / (completed + missed)`. |
| served energy | kWh | Energia dos ciclos completados. |
| unserved energy | kWh | Energia dos ciclos falhados. |
| average start delay | hours | Media de `start - earliest_start`. |

## KPIs Demand Response

Disponiveis quando `demand_response.enabled=true`.

| Sufixo KPI | Nivel | Unidade | O que mede |
|---|---|---:|---|
| `demand_response_events_count` | building/district | count | Eventos DR unicos com linhas de settlement ativas. |
| `demand_response_active_time_step_count` | building/district | count | Numero de timesteps DR ativos. |
| `demand_response_requested_total_kwh` | building/district | kWh | Energia pedida a partir de `target_power_kw` nos steps ativos. |
| `demand_response_delivered_total_kwh` | building/district | kWh | Delivery assinado, positivo quando o controlo segue a direcao pedida. |
| `demand_response_shortfall_total_kwh` | building/district | kWh | Energia pedida nao entregue depois da tolerancia. |
| `demand_response_compliance_ratio` | building/district | ratio | Delivery creditado dividido pela energia pedida valida. |
| `demand_response_revenue_total_eur` | building/district | eur | Receita por delivery creditado. |
| `demand_response_penalty_total_eur` | building/district | eur | Penalizacao por shortfall. |
| `demand_response_net_revenue_total_eur` | building/district | eur | Receita menos penalizacao. |
| `demand_response_invalid_baseline_time_step_count` | building/district | count | Steps ativos excluidos da economia porque a baseline pre-evento era invalida. |

Os nomes levam prefixo `district_` ou `building_`, por exemplo `district_demand_response_net_revenue_total_eur`.

## KPIs Robustez

Disponiveis quando `robustness.enabled=true`.

| Sufixo KPI | Nivel | Unidade | O que mede |
|---|---|---:|---|
| `robustness_events_count` | building/district | count | Eventos de robustez unicos que afetaram esse nivel. |
| `robustness_active_time_step_count` | building/district | count | Timesteps com pelo menos uma perturbacao aplicada. |
| `robustness_observation_corruption_count` | building/district | count | Corrupcoes agent-facing em observations. |
| `robustness_forecast_corruption_count` | building/district | count | Corrupcoes agent-facing em forecasts. |
| `robustness_action_corruption_count` | building/district | count | Corrupcoes no canal de acao antes da aplicacao fisica. |
| `robustness_asset_unavailable_time_step_count` | building/district | count | Aplicacoes de asset unavailable. |
| `robustness_missing_observation_count` | building/district | count | Observations ou telemetria substituidas pela sentinela missing. |
| `robustness_action_dropout_count` | building/district | count | Acoes forcadas a zero por dropout ou outage de controlo. |

Os nomes levam prefixo `district_` ou `building_`, por exemplo `district_robustness_missing_observation_count`.

## KPIs Electrical Service e Fases

| KPI conceptual | Unidade | O que mede |
|---|---:|---|
| violation total | kWh | Energia acima dos limites de servico/fase. |
| violation time step count | count | Numero de steps com violacao. |
| phase imbalance average | ratio | Desequilibrio medio entre fases. |
| phase import peak L1/L2/L3 | kW | Pico de import por fase. |
| phase export peak L1/L2/L3 | kW | Pico de export por fase. |

## KPIs Community Market

Condicionais a `community_market.enabled=true`.

| KPI conceptual | Nivel | Unidade | O que mede |
|---|---|---:|---|
| local traded total | district | kWh | Energia local transacionada. |
| local traded daily average | district | kWh/day | Media diaria local. |
| community import share | district | ratio | Share da demanda servida localmente. |
| settled cost | building/district | eur | Custo apos settlement local. |
| counterfactual cost | building/district | eur | Custo sem mercado local. |
| market savings | building/district | eur | Diferenca entre counterfactual e settled. |

## Export

| Modo | Como obter |
|---|---|
| Em memoria | `env.evaluate_v2()` |
| Export no fim | `CityLearnEnv(..., export_kpis_on_episode_end=True)` |
| Com render | `render_mode="end"` ou `render_mode="during"` |

Para releases novas, qualquer KPI novo deve ser registado em [`releases.md`](releases.md) e, se fizer parte do contrato v2, tambem em [`KPI_V2_TREE.md`](../KPI_V2_TREE.md).
