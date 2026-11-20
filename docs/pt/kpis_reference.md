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
| `degree_hours` | Graus-hora: desvio de temperatura em Celsius vezes horas. |
| `c` | Temperatura em Celsius. |
| `none` | Sem unidade: linha de substituição sem valor medido. |

Um KPI por dia simulado mantém a unidade do total: a energia `daily_average` está
em `kwh` por dia e o custo `daily_average` em `eur` por dia.

## Colunas da Tabela

O `evaluate_v2()` devolve uma linha por KPI e âmbito, com estas colunas, por esta
ordem. Com topologia dinâmica seguem-se `topology_born_at`, `topology_removed_at`
e `topology_active`, e o `MultiCommunityEnv.evaluate_v2()` acrescenta
`community_id` no fim.

| Coluna | Significado |
|---|---|
| `cost_function` | Nome do KPI, `level_family_subfamily_metric_variant_unit`. |
| `value` | Valor do KPI; em falta quando o KPI é indefinido na corrida. |
| `name` | Nome do building, `District` ou `Portfolio`. |
| `level` | `building`, `district` ou `portfolio`. |
| `unit` | Uma das unidades acima. É o sufixo de unidade do nome, exceto `none`. |
| `description` | Uma linha que define o KPI e, numa variante de referência, a corrida a que se refere. |

`unit` e `description` vêm de um único registo, `citylearn/internal/kpi_registry.py`,
que associa cada nome de KPI, sem o prefixo de nível, a uma unidade e a uma
descrição. O mesmo texto vale para as linhas `building`, `district` e `portfolio`
de um KPI. A descrição está em inglês, como os nomes. `tests/test_kpi_registry.py`
falha para um nome de KPI sem entrada no registo.

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

Os ratios district dividem totais district: `district_..._ratio_to_baseline_x` e o total control do distrito sobre o total baseline do distrito, como todos os ratios `ratio_to_business_as_usual`. Uma media dos ratios dos buildings nao e um ratio district; a API legacy `evaluate()` mantem essa media como linha district, e `evaluate_v2()` publica-a com a variante `building_mean` (ver [Definicoes alteradas depois da 3.6.0](#definicoes-alteradas-depois-da-360)).

As emissoes district sao as emissoes do import da rede do distrito, `max(sum_membros(net_t), 0)` em cada step, por isso a energia que um membro exporta e outro importa no mesmo step nao tem carbono da rede. Cada kWh importado usa a intensidade carbonica do membro que o importa; quando os membros que importam tem intensidades diferentes, a parte de cada import coberta localmente segue a alocacao ponderada do ledger de proveniencia de energia, e o total control iguala `district_energy_provenance_external_purchase_emissions_kgco2`. As emissoes de um building sao o import do proprio membro vezes a sua intensidade carbonica, por isso nao somam ao total district quando os membros partilham energia.

Safe division devolve `None` (indefinido) quando o control ou a referencia falta ou nao e finito; um valor indefinido nunca e lido como zero. Para uma referencia dentro da tolerancia numerica de zero devolve `1.0` ("sem alteracao") se o control tambem for praticamente zero, e `None` caso contrario. A excecao sao os ratios de servico dos deferrable appliances ao BAU: quando nenhum ciclo era devido em nenhum dos runs (os dois totais sao zero), sao indefinidos.

Os ratios continuam lower-is-better quando o total de referencia e negativo. O net exchange (legacy `zero_net_energy`) e os totais de custo podem ser negativos, para um exportador liquido ou depois de receitas do community market. Os seus ratios ao baseline e ao BAU usam

```text
ratio_x = control_x / reference_x                        se reference_x > 0
ratio_x = 1 + (control_x - reference_x) / |reference_x|  se reference_x < 0
```

Assim 1 continua a significar sem alteracao e um total control maior da um ratio maior. Para uma referencia positiva e o ratio simples. Import, export e emissoes nunca sao negativos e usam o ratio simples.

Os KPIs de forma da rede usam potencia, `net_t / step_hours`:

```text
load_factor_penalty = media nas janelas de (1 - mean(import_w) / max(import_w))
ramping_average     = sum_t max(net_t - net_(t-1), 0) / transicoes
```

com `import = max(net, 0)` e janelas diarias (24 h) ou mensais (730 h). Uma janela cujo pico de import e zero nao tem load factor e fica fora da media; o KPI e indefinido quando nenhuma janela esta definida. `ramping_average` e uma media por transicao de step, por isso nao cresce com o comprimento do episodio.

O counterfactual `baseline` segue o outage da rede do run controlado: nos time steps de power outage as series net `*_without_storage*`, e as suas series de custo e emissoes, sao zero. Nenhum dos runs troca energia com a rede enquanto ela esta em baixo.

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
| average start delay | hours | Media de `start - earliest_start` nos ciclos completados; indefinido quando nenhum ciclo foi completado. |

O service level e o average start delay sao indefinidos, e nao 0 ou 1, nas janelas em que nenhum ciclo era devido ou nenhum foi completado; os seus deltas e ratios ao BAU tambem. Preserve os valores em falta ao exportar ou comparar.

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
| `demand_response_uncapped_contribution_total_kwh` | building | kWh | Diagnostico: a contribuicao positiva do proprio membro, sem a tolerancia e o limite do distrito. Nao soma ao distrito. |

Os nomes levam prefixo `district_` ou `building_`, por exemplo `district_demand_response_net_revenue_total_eur`.

As linhas building repartem o settlement district de cada step. O pedido e repartido em partes iguais pelos membros ativos. A energia creditada e a receita do distrito sao alocadas pelos pesos de receita (a parte de cada membro nas contribuicoes positivas), e o shortfall e a penalizacao do distrito pelos pesos de penalizacao (a parte de cada membro nas contribuicoes negativas ou, sem estas, na baseline pre-evento). A energia creditada, o shortfall, o delivery, a receita e a penalizacao dos buildings somam assim aos valores district e respeitam a tolerancia e o limite do distrito ao target. A compliance de um building e a sua energia creditada sobre a sua parte igual do pedido, limitada a 1, por isso a media das compliance dos buildings nunca excede o ratio district.

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

## Definicoes alteradas depois da 3.6.0

A versao das definicoes de KPIs (`kpi_definition_version` nos metadados `energy_accounting` de `evaluate_v2()`) e `2.0.0`. Estas linhas de `evaluate_v2()` mudaram de definicao. Onde um valor da 3.6.0 pode ter sido usado em comparacoes publicadas, fica com um nome proprio, e as linhas legacy de `evaluate()` mantem as suas definicoes da 3.6.0.

| KPI | Nova definicao | Valor da 3.6.0 mantido como |
|---|---|---|
| `district_energy_grid_ratio_to_baseline_import_total_ratio` | Total de import do distrito sobre o total baseline do distrito. | `district_energy_grid_ratio_to_baseline_import_total_building_mean_ratio`; legacy `electricity_consumption_total` |
| `district_energy_grid_ratio_to_baseline_net_exchange_total_ratio` | Ratio com sinal dos totais de net exchange do distrito. | `district_energy_grid_ratio_to_baseline_net_exchange_total_building_mean_ratio`; legacy `zero_net_energy` |
| `district_emissions_ratio_to_baseline_total_ratio` | Total de emissoes do distrito sobre o total baseline do distrito. | `district_emissions_ratio_to_baseline_total_building_mean_ratio`; legacy `carbon_emissions_total` |
| `district_emissions_total_{control,baseline,business_as_usual}_kgco2` e os seus deltas, medias diarias e ratios | Emissoes do import liquido do distrito. | `district_emissions_total_{control,baseline,business_as_usual}_member_sum_kgco2` |
| `district_energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average_to_baseline_ratio` | Load factor da potencia importada; janelas sem import sao indefinidas. | `..._to_baseline_signed_net_ratio`; legacy `daily_one_minus_load_factor_average`, `monthly_one_minus_load_factor_average` |
| `district_energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average_{business_as_usual,delta_to_business_as_usual}_ratio`, `..._to_business_as_usual_ratio` | Como acima. | `district_energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average_signed_net_*` |
| `district_energy_grid_shape_quality_ramping_average_{business_as_usual,delta_to_business_as_usual}_kw` | Rampa ascendente media por transicao de step. O ratio ao BAU nao muda. | `district_energy_grid_shape_quality_ramping_total_{business_as_usual,delta_to_business_as_usual}_kw` |
| `*_deferrable_appliance_service_average_start_delay_hours` | Indefinido quando nenhum ciclo foi completado (era 0). | nenhum |
| Ratios com control ou referencia indefinidos | Indefinidos (eram lidos como 0, ou 1 quando ambos eram indefinidos). | nenhum |
| `*_deferrable_appliance_ratio_to_business_as_usual_*_ratio` com os dois totais a zero | Indefinido (era 1). | nenhum |
| `building_demand_response_{shortfall_total_kwh,compliance_ratio}` | Alocados a partir do settlement district. | `building_demand_response_uncapped_contribution_total_kwh` (diagnostico) |
| Taxas e medias EV de departure, service levels dos deferrable appliances e das escadas rolantes, start delay e self-consumption solar do portfolio (`MultiCommunityEnv`) | Agregadas a partir dos seus denominadores aditivos. | nenhum |

Nas linhas legacy, uma janela de load factor cujo pico com sinal nao e positivo passa a ser indefinida; antes dava uma penalizacao infinita ou negativa, que a safe division reportava como um 0 perfeito.

## Export

| Modo | Como obter |
|---|---|
| Em memoria | `env.evaluate_v2()` |
| Export no fim | `CityLearnEnv(..., export_kpis_on_episode_end=True)` |
| Com render | `render_mode="end"` ou `render_mode="during"` |

O `exported_kpis.csv` e o ficheiro Parquet exportados são largos: `KPI` seguido de
uma coluna por building e `District`, sem `unit` e `description`, porque a UI do
CityLearn lê todas as colunas depois de `KPI` como entidades. A unidade e a
descrição de cada KPI exportado estão na entrada `kpi_catalogue` de
`exported_kpis.manifest.json`. O `MultiCommunityEnv.export_final_kpis()` escreve a
tabela longa do `evaluate_v2()`, com `unit` e `description`, em
`exported_kpis_multi_community.csv`.

Para releases novas, qualquer KPI novo precisa de uma entrada em `kpi_registry.py`, deve ser registado em [`releases.md`](releases.md) e, se fizer parte do contrato v2, tambem em [`KPI_V2_TREE.md`](../KPI_V2_TREE.md).
