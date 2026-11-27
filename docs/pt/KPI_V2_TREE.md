# Catálogo de KPIs

Esta página lista todos os nomes de KPI que `evaluate_v2()` emite, agrupados por família, com
uma definição curta. É gerada a partir de `citylearn/misc/kpi_catalogue.yml` por
`scripts/docs/kpi_catalogue.py`, e um teste verifica que todos os nomes que o simulador emite
constam daqui. As equações, a agregação ao distrito e as regras de valores indefinidos de cada
família estão na [referência de KPIs](kpis_reference.md), para a qual cada família remete.

Os nomes seguem `<nível>_<família>_<subfamília>_<métrica>[_<variante>]_<unidade>`. O nível é
`building` ou `district`; `MultiCommunityEnv` acrescenta linhas `portfolio` construídas a
partir das linhas de distrito (ver [Níveis](kpis_reference.md#níveis)). Nas tabelas, `{a,b}`
representa cada alternativa e `{,_x}` uma parte opcional; os nomes completos seguem cada tabela.
As linhas presentes dependem dos equipamentos e serviços do cenário.

As linhas marcadas **Legada** mantêm uma definição anterior para que resultados antigos continuem
comparáveis, e as marcadas **Obsoleta** devolvem o mesmo valor que outra linha; ambas indicam a linha
canónica a reportar. `evaluate_v2()` dá a cada linha o seu `status` (`current`, `canonical`, `legacy`
ou `deprecated`) e `replacement`, e os manifestos das exportações registam-nos em `kpi_definitions`.

| Família | Nomes |
|---|---:|
| [Custo](#custo) | 24 |
| [Energia da rede e forma da carga](#energia-da-rede-e-forma-da-carga) | 136 |
| [Emissões](#emissões) | 28 |
| [Autoconsumo solar](#autoconsumo-solar) | 38 |
| [Mercado comunitário](#mercado-comunitário) | 36 |
| [Baterias](#baterias) | 40 |
| [Serviço elétrico e fases](#serviço-elétrico-e-fases) | 22 |
| [Veículos elétricos](#veículos-elétricos) | 72 |
| [Auditoria das partidas dos VE](#auditoria-das-partidas-dos-ve) | 128 |
| [Equipamentos flexíveis](#equipamentos-flexíveis) | 48 |
| [Auditoria dos equipamentos flexíveis](#auditoria-dos-equipamentos-flexíveis) | 68 |
| [Escadas rolantes](#escadas-rolantes) | 12 |
| [Conforto e resiliência](#conforto-e-resiliência) | 24 |
| [Auditoria do serviço térmico](#auditoria-do-serviço-térmico) | 64 |
| [Equidade](#equidade) | 5 |
| [Auditoria de equidade](#auditoria-de-equidade) | 8 |
| [Demand response](#demand-response) | 23 |
| [Auditoria de demand response](#auditoria-de-demand-response) | 72 |
| [Robustez](#robustez) | 16 |
| [Proveniência da energia](#proveniência-da-energia) | 342 |
| [Topologia dinâmica](#topologia-dinâmica) | 1 |

## Custo

Custo da eletricidade de cada membro e do distrito ao longo do episódio avaliado; as linhas aparecem em todas as execuções.

Equações e regras: [Custo](kpis_reference.md#custo).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `cost_{total,daily_average}_{control,baseline,delta}_eur` | building, district | EUR | Custo da eletricidade da execução controlada (`control`), do contrafactual convencional (`baseline`) e controlo menos contrafactual (`delta`), como total do episódio ou média diária. |
| `cost_ratio_to_baseline_total_ratio` | building, district | ratio | Rácio com sinal entre o custo total do controlo e o do contrafactual; continua a ser «menor é melhor» quando os totais são negativos. |
| `cost_{total,daily_average}_{business_as_usual,delta_to_business_as_usual}_eur` | building, district | EUR | Custo da eletricidade; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `cost_ratio_to_business_as_usual_total_ratio` | building, district | ratio | Rácio com sinal entre o custo total do controlo e o custo total BAU. |

<details>
<summary>Todos os 24 nomes</summary>

```text
building_cost_daily_average_baseline_eur
building_cost_daily_average_business_as_usual_eur
building_cost_daily_average_control_eur
building_cost_daily_average_delta_eur
building_cost_daily_average_delta_to_business_as_usual_eur
building_cost_ratio_to_baseline_total_ratio
building_cost_ratio_to_business_as_usual_total_ratio
building_cost_total_baseline_eur
building_cost_total_business_as_usual_eur
building_cost_total_control_eur
building_cost_total_delta_eur
building_cost_total_delta_to_business_as_usual_eur
district_cost_daily_average_baseline_eur
district_cost_daily_average_business_as_usual_eur
district_cost_daily_average_control_eur
district_cost_daily_average_delta_eur
district_cost_daily_average_delta_to_business_as_usual_eur
district_cost_ratio_to_baseline_total_ratio
district_cost_ratio_to_business_as_usual_total_ratio
district_cost_total_baseline_eur
district_cost_total_business_as_usual_eur
district_cost_total_control_eur
district_cost_total_delta_eur
district_cost_total_delta_to_business_as_usual_eur
```

</details>

## Energia da rede e forma da carga

Energia trocada com a rede por cada membro e pelo distrito, e a forma da carga do distrito (picos, rampas, fator de carga); as linhas aparecem em todas as execuções, as de forma só ao nível do distrito.

Equações e regras: [Energia da rede e forma da carga](kpis_reference.md#energia-da-rede-e-forma-da-carga).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `energy_grid_{total,daily_average}_{import,export,net_exchange}_{control,baseline,delta}_kwh` | building, district | kWh | Importação Σ max(net, 0), exportação Σ max(−net, 0) e troca líquida com sinal Σ net da execução controlada, do contrafactual convencional e controlo menos contrafactual; o distrito compensa os membros em cada passo. |
| `energy_grid_{total,daily_average}_{import,export,net_exchange}_{business_as_usual,delta_to_business_as_usual}_kwh` | building, district | kWh | Importação, exportação e troca líquida com a rede; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `energy_grid_ratio_to_baseline_{import,export,net_exchange}_total_ratio` | building, district | ratio | Total do controlo sobre o total do contrafactual; rácio com sinal para a troca líquida. O rácio do distrito divide os totais do distrito. |
| `energy_grid_ratio_to_baseline_{import,net_exchange}_total_building_mean_ratio` | district | ratio | Definição da versão 3.6.0, mantida para comparação: a média simples dos rácios dos edifícios, não um rácio do distrito. |
| `energy_grid_ratio_to_business_as_usual_{import,export,net_exchange}_total_ratio` | building, district | ratio | Total do controlo sobre o total BAU; rácio com sinal para a troca líquida. |
| `energy_grid_shape_quality_peak_{daily,all_time}_average_to_baseline_ratio` | district | ratio | Pico do controlo sobre o pico do contrafactual, sendo o pico a média, sobre janelas diárias (ou a janela única do episódio), do máximo da potência líquida com sinal do distrito. |
| `energy_grid_shape_quality_peak_{daily,all_time}_average_{control,business_as_usual,delta_to_business_as_usual}_kw` | district | kW | Pico da potência líquida com sinal do distrito na execução controlada, na execução BAU, e controlo menos BAU. |
| `energy_grid_shape_quality_peak_{daily,all_time}_average_to_business_as_usual_ratio` | district | ratio | Pico do controlo sobre o pico BAU, na potência líquida com sinal do distrito. |
| `energy_grid_shape_quality_ramping_average_to_baseline_ratio` | district | ratio | Soma das rampas ascendentes da série líquida do distrito no controlo sobre a do contrafactual (um rácio de totais, mantido da versão 3.6.0). |
| `energy_grid_shape_quality_ramping_{average,total}_{control,business_as_usual,delta_to_business_as_usual}_kw` | district | kW | Rampa ascendente da potência líquida do distrito na execução controlada, na execução BAU, e controlo menos BAU: `average` por transição entre passos, `total` somada no episódio (valor da versão 3.6.0). |
| `energy_grid_shape_quality_ramping_average_to_business_as_usual_ratio` | district | ratio | Rampa ascendente média do controlo sobre a da execução BAU; `ramping_total` não tem linha de rácio. |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average_to_baseline_ratio` | district | ratio | Penalização do fator de carga do controlo sobre a do contrafactual, na potência de importação do distrito e em janelas diárias (24 h) ou mensais (730 h). |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average_to_baseline_signed_net_ratio` | district | ratio | Como o rácio de importação acima, na série líquida com sinal (definição da versão 3.6.0). |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average{,_signed_net}_{control,business_as_usual,delta_to_business_as_usual}_ratio` | district | ratio | Penalização do fator de carga da execução controlada, da execução BAU, e controlo menos BAU, na potência de importação ou, com `_signed_net`, na potência líquida com sinal (3.6.0). |
| `energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average{,_signed_net}_to_business_as_usual_ratio` | district | ratio | Penalização do fator de carga do controlo sobre a da execução BAU, na mesma série. |
| `energy_grid_feeder_limit_{import,export}_exceedance_energy_total_{control,business_as_usual,delta_to_business_as_usual}_kwh` | district | kWh | Energia da importação ou exportação líquida do distrito acima do limite declarado em `district_electrical_service` (excessos até 1e-5 kW ignorados; monitorizada sem corte), na execução controlada, na execução BAU, e controlo menos BAU; só é emitida quando `district_electrical_service.enabled` é verdadeiro e fica indefinida numa direção não configurada. |
| `energy_grid_feeder_limit_{import,export}_exceedance_peak_{control,business_as_usual,delta_to_business_as_usual}_kw` | district | kW | Maior excesso de potência de importação ou de exportação líquida do distrito acima do limite declarado em `district_electrical_service`, na execução controlada, na execução BAU, e controlo menos BAU; só é emitida quando `district_electrical_service.enabled` é verdadeiro e fica indefinida numa direção não configurada. |
| `energy_grid_feeder_limit_{import,export}_exceedance_step_{control,business_as_usual,delta_to_business_as_usual}_count` | district | count | Número de passos executados com excesso de importação ou de exportação líquida do distrito acima de 1e-9 kWh, na execução controlada, na execução BAU, e controlo menos BAU; só é emitida quando `district_electrical_service.enabled` é verdadeiro e fica indefinida numa direção não configurada. |
| `energy_grid_window_average_power_{control,business_as_usual,delta_to_business_as_usual}_kw` | building, district | kW | Potência líquida média com sinal na rede dentro da janela local recorrente `evaluation_window` na execução controlada, na execução BAU, e controlo menos BAU; só é emitida quando `evaluation_window.enabled` é verdadeiro. |

<details>
<summary>Todos os 136 nomes</summary>

```text
building_energy_grid_daily_average_export_baseline_kwh
building_energy_grid_daily_average_export_business_as_usual_kwh
building_energy_grid_daily_average_export_control_kwh
building_energy_grid_daily_average_export_delta_kwh
building_energy_grid_daily_average_export_delta_to_business_as_usual_kwh
building_energy_grid_daily_average_import_baseline_kwh
building_energy_grid_daily_average_import_business_as_usual_kwh
building_energy_grid_daily_average_import_control_kwh
building_energy_grid_daily_average_import_delta_kwh
building_energy_grid_daily_average_import_delta_to_business_as_usual_kwh
building_energy_grid_daily_average_net_exchange_baseline_kwh
building_energy_grid_daily_average_net_exchange_business_as_usual_kwh
building_energy_grid_daily_average_net_exchange_control_kwh
building_energy_grid_daily_average_net_exchange_delta_kwh
building_energy_grid_daily_average_net_exchange_delta_to_business_as_usual_kwh
building_energy_grid_ratio_to_baseline_export_total_ratio
building_energy_grid_ratio_to_baseline_import_total_ratio
building_energy_grid_ratio_to_baseline_net_exchange_total_ratio
building_energy_grid_ratio_to_business_as_usual_export_total_ratio
building_energy_grid_ratio_to_business_as_usual_import_total_ratio
building_energy_grid_ratio_to_business_as_usual_net_exchange_total_ratio
building_energy_grid_total_export_baseline_kwh
building_energy_grid_total_export_business_as_usual_kwh
building_energy_grid_total_export_control_kwh
building_energy_grid_total_export_delta_kwh
building_energy_grid_total_export_delta_to_business_as_usual_kwh
building_energy_grid_total_import_baseline_kwh
building_energy_grid_total_import_business_as_usual_kwh
building_energy_grid_total_import_control_kwh
building_energy_grid_total_import_delta_kwh
building_energy_grid_total_import_delta_to_business_as_usual_kwh
building_energy_grid_total_net_exchange_baseline_kwh
building_energy_grid_total_net_exchange_business_as_usual_kwh
building_energy_grid_total_net_exchange_control_kwh
building_energy_grid_total_net_exchange_delta_kwh
building_energy_grid_total_net_exchange_delta_to_business_as_usual_kwh
building_energy_grid_window_average_power_business_as_usual_kw
building_energy_grid_window_average_power_control_kw
building_energy_grid_window_average_power_delta_to_business_as_usual_kw
district_energy_grid_daily_average_export_baseline_kwh
district_energy_grid_daily_average_export_business_as_usual_kwh
district_energy_grid_daily_average_export_control_kwh
district_energy_grid_daily_average_export_delta_kwh
district_energy_grid_daily_average_export_delta_to_business_as_usual_kwh
district_energy_grid_daily_average_import_baseline_kwh
district_energy_grid_daily_average_import_business_as_usual_kwh
district_energy_grid_daily_average_import_control_kwh
district_energy_grid_daily_average_import_delta_kwh
district_energy_grid_daily_average_import_delta_to_business_as_usual_kwh
district_energy_grid_daily_average_net_exchange_baseline_kwh
district_energy_grid_daily_average_net_exchange_business_as_usual_kwh
district_energy_grid_daily_average_net_exchange_control_kwh
district_energy_grid_daily_average_net_exchange_delta_kwh
district_energy_grid_daily_average_net_exchange_delta_to_business_as_usual_kwh
district_energy_grid_feeder_limit_export_exceedance_energy_total_business_as_usual_kwh
district_energy_grid_feeder_limit_export_exceedance_energy_total_control_kwh
district_energy_grid_feeder_limit_export_exceedance_energy_total_delta_to_business_as_usual_kwh
district_energy_grid_feeder_limit_export_exceedance_peak_business_as_usual_kw
district_energy_grid_feeder_limit_export_exceedance_peak_control_kw
district_energy_grid_feeder_limit_export_exceedance_peak_delta_to_business_as_usual_kw
district_energy_grid_feeder_limit_export_exceedance_step_business_as_usual_count
district_energy_grid_feeder_limit_export_exceedance_step_control_count
district_energy_grid_feeder_limit_export_exceedance_step_delta_to_business_as_usual_count
district_energy_grid_feeder_limit_import_exceedance_energy_total_business_as_usual_kwh
district_energy_grid_feeder_limit_import_exceedance_energy_total_control_kwh
district_energy_grid_feeder_limit_import_exceedance_energy_total_delta_to_business_as_usual_kwh
district_energy_grid_feeder_limit_import_exceedance_peak_business_as_usual_kw
district_energy_grid_feeder_limit_import_exceedance_peak_control_kw
district_energy_grid_feeder_limit_import_exceedance_peak_delta_to_business_as_usual_kw
district_energy_grid_feeder_limit_import_exceedance_step_business_as_usual_count
district_energy_grid_feeder_limit_import_exceedance_step_control_count
district_energy_grid_feeder_limit_import_exceedance_step_delta_to_business_as_usual_count
district_energy_grid_ratio_to_baseline_export_total_ratio
district_energy_grid_ratio_to_baseline_import_total_building_mean_ratio
district_energy_grid_ratio_to_baseline_import_total_ratio
district_energy_grid_ratio_to_baseline_net_exchange_total_building_mean_ratio
district_energy_grid_ratio_to_baseline_net_exchange_total_ratio
district_energy_grid_ratio_to_business_as_usual_export_total_ratio
district_energy_grid_ratio_to_business_as_usual_import_total_ratio
district_energy_grid_ratio_to_business_as_usual_net_exchange_total_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_signed_net_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_baseline_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_baseline_signed_net_ratio
district_energy_grid_shape_quality_load_factor_penalty_daily_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_control_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_delta_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_signed_net_to_business_as_usual_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_to_baseline_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_to_baseline_signed_net_ratio
district_energy_grid_shape_quality_load_factor_penalty_monthly_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_peak_all_time_average_business_as_usual_kw
district_energy_grid_shape_quality_peak_all_time_average_control_kw
district_energy_grid_shape_quality_peak_all_time_average_delta_to_business_as_usual_kw
district_energy_grid_shape_quality_peak_all_time_average_to_baseline_ratio
district_energy_grid_shape_quality_peak_all_time_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_peak_daily_average_business_as_usual_kw
district_energy_grid_shape_quality_peak_daily_average_control_kw
district_energy_grid_shape_quality_peak_daily_average_delta_to_business_as_usual_kw
district_energy_grid_shape_quality_peak_daily_average_to_baseline_ratio
district_energy_grid_shape_quality_peak_daily_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_ramping_average_business_as_usual_kw
district_energy_grid_shape_quality_ramping_average_control_kw
district_energy_grid_shape_quality_ramping_average_delta_to_business_as_usual_kw
district_energy_grid_shape_quality_ramping_average_to_baseline_ratio
district_energy_grid_shape_quality_ramping_average_to_business_as_usual_ratio
district_energy_grid_shape_quality_ramping_total_business_as_usual_kw
district_energy_grid_shape_quality_ramping_total_control_kw
district_energy_grid_shape_quality_ramping_total_delta_to_business_as_usual_kw
district_energy_grid_total_export_baseline_kwh
district_energy_grid_total_export_business_as_usual_kwh
district_energy_grid_total_export_control_kwh
district_energy_grid_total_export_delta_kwh
district_energy_grid_total_export_delta_to_business_as_usual_kwh
district_energy_grid_total_import_baseline_kwh
district_energy_grid_total_import_business_as_usual_kwh
district_energy_grid_total_import_control_kwh
district_energy_grid_total_import_delta_kwh
district_energy_grid_total_import_delta_to_business_as_usual_kwh
district_energy_grid_total_net_exchange_baseline_kwh
district_energy_grid_total_net_exchange_business_as_usual_kwh
district_energy_grid_total_net_exchange_control_kwh
district_energy_grid_total_net_exchange_delta_kwh
district_energy_grid_total_net_exchange_delta_to_business_as_usual_kwh
district_energy_grid_window_average_power_business_as_usual_kw
district_energy_grid_window_average_power_control_kw
district_energy_grid_window_average_power_delta_to_business_as_usual_kw
```

</details>

## Emissões

Emissões de carbono da eletricidade importada da rede por cada membro e pelo distrito; as linhas aparecem em todas as execuções.

Equações e regras: [Emissões](kpis_reference.md#emissões).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `emissions_{total,daily_average}_{control,baseline,delta}_kgco2` | building, district | kgCO2 | Emissões da importação da rede na execução controlada, no contrafactual convencional e controlo menos contrafactual; o valor do distrito é o da importação compensada do distrito, não a soma dos edifícios. |
| `emissions_total_{control,baseline,business_as_usual}_member_sum_kgco2` | district | kgCO2 | Definição do distrito da versão 3.6.0, mantida para comparação: a soma das emissões próprias dos membros na execução controlada, no contrafactual ou na execução BAU. |
| `emissions_ratio_to_baseline_total_ratio` | building, district | ratio | Total de emissões do controlo sobre o do contrafactual; o rácio do distrito divide os totais compensados do distrito. |
| `emissions_ratio_to_baseline_total_building_mean_ratio` | district | ratio | Definição da versão 3.6.0, mantida para comparação: a média simples dos rácios dos edifícios. |
| `emissions_{total,daily_average}_{business_as_usual,delta_to_business_as_usual}_kgco2` | building, district | kgCO2 | Emissões da importação da rede; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `emissions_ratio_to_business_as_usual_total_ratio` | building, district | ratio | Total de emissões do controlo sobre o total BAU. |

<details>
<summary>Todos os 28 nomes</summary>

```text
building_emissions_daily_average_baseline_kgco2
building_emissions_daily_average_business_as_usual_kgco2
building_emissions_daily_average_control_kgco2
building_emissions_daily_average_delta_kgco2
building_emissions_daily_average_delta_to_business_as_usual_kgco2
building_emissions_ratio_to_baseline_total_ratio
building_emissions_ratio_to_business_as_usual_total_ratio
building_emissions_total_baseline_kgco2
building_emissions_total_business_as_usual_kgco2
building_emissions_total_control_kgco2
building_emissions_total_delta_kgco2
building_emissions_total_delta_to_business_as_usual_kgco2
district_emissions_daily_average_baseline_kgco2
district_emissions_daily_average_business_as_usual_kgco2
district_emissions_daily_average_control_kgco2
district_emissions_daily_average_delta_kgco2
district_emissions_daily_average_delta_to_business_as_usual_kgco2
district_emissions_ratio_to_baseline_total_building_mean_ratio
district_emissions_ratio_to_baseline_total_ratio
district_emissions_ratio_to_business_as_usual_total_ratio
district_emissions_total_baseline_kgco2
district_emissions_total_baseline_member_sum_kgco2
district_emissions_total_business_as_usual_kgco2
district_emissions_total_business_as_usual_member_sum_kgco2
district_emissions_total_control_kgco2
district_emissions_total_control_member_sum_kgco2
district_emissions_total_delta_kgco2
district_emissions_total_delta_to_business_as_usual_kgco2
```

</details>

## Autoconsumo solar

Produção fotovoltaica (FV) e quanto dela é usado dentro de cada membro ou do distrito em vez de ser exportado ou cortado; as linhas aparecem em todas as execuções e são nulas ou indefinidas sem FV.

Equações e regras: [Autoconsumo solar](kpis_reference.md#autoconsumo-solar).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `solar_self_consumption_{total,daily_average}_{generation,export}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Produção FV disponível e exportação para a rede suportada por FV, como total ou média diária; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `solar_self_consumption_total_curtailment_kwh` | building, district | kWh | Energia FV que não pôde ser usada enquanto o membro esteve isolado por um corte de energia; nula fora dos cortes. Sem linha BAU. |
| `solar_self_consumption_ratio_self_consumption{,_business_as_usual,_delta_to_business_as_usual}_ratio` | building, district | ratio | Fração da produção FV usada localmente, (produção − exportação − corte) / produção, indefinida sem produção; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `solar_self_consumption_ratio_to_business_as_usual_{generation_total,export_total,self_consumption}_ratio` | building, district | ratio | Valor do controlo sobre o valor BAU da produção total, da exportação total ou do rácio de autoconsumo. |

<details>
<summary>Todos os 38 nomes</summary>

```text
building_solar_self_consumption_daily_average_export_business_as_usual_kwh
building_solar_self_consumption_daily_average_export_delta_to_business_as_usual_kwh
building_solar_self_consumption_daily_average_export_kwh
building_solar_self_consumption_daily_average_generation_business_as_usual_kwh
building_solar_self_consumption_daily_average_generation_delta_to_business_as_usual_kwh
building_solar_self_consumption_daily_average_generation_kwh
building_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio
building_solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio
building_solar_self_consumption_ratio_self_consumption_ratio
building_solar_self_consumption_ratio_to_business_as_usual_export_total_ratio
building_solar_self_consumption_ratio_to_business_as_usual_generation_total_ratio
building_solar_self_consumption_ratio_to_business_as_usual_self_consumption_ratio
building_solar_self_consumption_total_curtailment_kwh
building_solar_self_consumption_total_export_business_as_usual_kwh
building_solar_self_consumption_total_export_delta_to_business_as_usual_kwh
building_solar_self_consumption_total_export_kwh
building_solar_self_consumption_total_generation_business_as_usual_kwh
building_solar_self_consumption_total_generation_delta_to_business_as_usual_kwh
building_solar_self_consumption_total_generation_kwh
district_solar_self_consumption_daily_average_export_business_as_usual_kwh
district_solar_self_consumption_daily_average_export_delta_to_business_as_usual_kwh
district_solar_self_consumption_daily_average_export_kwh
district_solar_self_consumption_daily_average_generation_business_as_usual_kwh
district_solar_self_consumption_daily_average_generation_delta_to_business_as_usual_kwh
district_solar_self_consumption_daily_average_generation_kwh
district_solar_self_consumption_ratio_self_consumption_business_as_usual_ratio
district_solar_self_consumption_ratio_self_consumption_delta_to_business_as_usual_ratio
district_solar_self_consumption_ratio_self_consumption_ratio
district_solar_self_consumption_ratio_to_business_as_usual_export_total_ratio
district_solar_self_consumption_ratio_to_business_as_usual_generation_total_ratio
district_solar_self_consumption_ratio_to_business_as_usual_self_consumption_ratio
district_solar_self_consumption_total_curtailment_kwh
district_solar_self_consumption_total_export_business_as_usual_kwh
district_solar_self_consumption_total_export_delta_to_business_as_usual_kwh
district_solar_self_consumption_total_export_kwh
district_solar_self_consumption_total_generation_business_as_usual_kwh
district_solar_self_consumption_total_generation_delta_to_business_as_usual_kwh
district_solar_self_consumption_total_generation_kwh
```

</details>

## Mercado comunitário

Troca local de energia entre os membros de uma comunidade e a respetiva liquidação. As linhas aparecem em todas as simulações (a zero, ou com quotas indefinidas, quando `community_market.enabled` é falso), exceto `local_traded` e `import_share`, que exigem o mercado e os respetivos interruptores de KPI.

Equações e regras: [Mercado comunitário](kpis_reference.md#mercado-comunitário).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `energy_grid_community_market_local_{import,export}_{total,daily_average}_kwh` | building, district | kWh | Energia comprada a (importação) ou vendida a (exportação) outros membros através da troca local, somada nos passos executados; médias diárias como nas regras comuns. |
| `energy_grid_community_market_grid_{import,export}_after_local_{total,daily_average}_kwh` | building, district | kWh | Importação da rede ainda necessária, ou excedente ainda exportado para a rede, de cada membro depois da troca local, somada pelos membros sem nova compensação; médias diárias como nas regras comuns. |
| `energy_grid_community_market_local_traded_{total,daily_average}_kwh` | district | kWh | Energia trocada localmente; igual à importação local do distrito. Só é emitida com o mercado ativo e `community_market.kpis.community_local_traded_enabled` verdadeiro. |
| `cost_community_market_settled_{total,daily_average}_eur` | building, district | EUR | Custo depois da liquidação local: importação da rede e compras locais menos vendas locais e receita de exportação para a rede; pode ser negativo. |
| `cost_community_market_counterfactual_{total,daily_average}_eur` | building, district | EUR | Custo só com a rede dos mesmos fluxos controlados sem troca local, `importação · preço de importação − exportação · preço de exportação`; não é a condição de avaliação `baseline`. |
| `cost_community_market_savings_{total,daily_average}_eur` | building, district | EUR | Custo contrafactual menos custo liquidado; positivo quando a troca local baixou o custo. |
| `cost_community_market_operator_balance_total_eur` | district | EUR | Dinheiro que o mercado retém (positivo) ou paga (negativo): pagamentos locais dos importadores menos receitas locais dos exportadores. É zero quando todos os membros têm o mesmo preço local em cada passo. |
| `solar_self_consumption_community_market_import_share_ratio` | district | ratio | Quota local da procura canónica: `importação local / (importação local + importação da rede depois da troca local)`, a parte da importação bruta dos membros coberta pela troca local. Só é emitida com o mercado ativo e `community_market.kpis.community_self_consumption_enabled` verdadeiro. |
| `solar_self_consumption_community_market_local_share_of_demand_ratio` | building | ratio | Importação local sobre importação local mais importação da rede depois da troca local (emitido em todas as simulações, indefinido só quando o denominador é 0); a única quota da procura ao nível do edifício. |
| `solar_self_consumption_community_market_local_share_of_demand_ratio` | district | ratio | **Obsoleta**, alias de `solar_self_consumption_community_market_import_share_ratio`. Alias obsoleto, mantido por compatibilidade: a mesma fórmula de `import_share` (emitido em todas as simulações, indefinido só quando o denominador é 0). |
| `solar_self_consumption_community_market_local_share_of_export_ratio` | building, district | ratio | `exportação local / (exportação local + exportação para a rede depois da troca local)`: a parte da exportação bruta dos membros vendida a outros membros. |

<details>
<summary>Todos os 36 nomes</summary>

```text
building_cost_community_market_counterfactual_daily_average_eur
building_cost_community_market_counterfactual_total_eur
building_cost_community_market_savings_daily_average_eur
building_cost_community_market_savings_total_eur
building_cost_community_market_settled_daily_average_eur
building_cost_community_market_settled_total_eur
building_energy_grid_community_market_grid_export_after_local_daily_average_kwh
building_energy_grid_community_market_grid_export_after_local_total_kwh
building_energy_grid_community_market_grid_import_after_local_daily_average_kwh
building_energy_grid_community_market_grid_import_after_local_total_kwh
building_energy_grid_community_market_local_export_daily_average_kwh
building_energy_grid_community_market_local_export_total_kwh
building_energy_grid_community_market_local_import_daily_average_kwh
building_energy_grid_community_market_local_import_total_kwh
building_solar_self_consumption_community_market_local_share_of_demand_ratio
building_solar_self_consumption_community_market_local_share_of_export_ratio
district_cost_community_market_counterfactual_daily_average_eur
district_cost_community_market_counterfactual_total_eur
district_cost_community_market_operator_balance_total_eur
district_cost_community_market_savings_daily_average_eur
district_cost_community_market_savings_total_eur
district_cost_community_market_settled_daily_average_eur
district_cost_community_market_settled_total_eur
district_energy_grid_community_market_grid_export_after_local_daily_average_kwh
district_energy_grid_community_market_grid_export_after_local_total_kwh
district_energy_grid_community_market_grid_import_after_local_daily_average_kwh
district_energy_grid_community_market_grid_import_after_local_total_kwh
district_energy_grid_community_market_local_export_daily_average_kwh
district_energy_grid_community_market_local_export_total_kwh
district_energy_grid_community_market_local_import_daily_average_kwh
district_energy_grid_community_market_local_import_total_kwh
district_energy_grid_community_market_local_traded_daily_average_kwh
district_energy_grid_community_market_local_traded_total_kwh
district_solar_self_consumption_community_market_import_share_ratio
district_solar_self_consumption_community_market_local_share_of_demand_ratio
district_solar_self_consumption_community_market_local_share_of_export_ratio
```

</details>

## Baterias

Atividade e desgaste das baterias estacionárias; as linhas aparecem em todas as execuções, com energia nula e ciclos e perda de capacidade indefinidos para membros sem bateria.

Equações e regras: [Baterias](kpis_reference.md#baterias).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `battery_total_{charge,discharge,throughput}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia carregada e descarregada nos terminais das baterias, e energia movimentada = carga + descarga; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `battery_health_equivalent_full_cycles{,_business_as_usual,_delta_to_business_as_usual}_count` | building, district | count | Ciclos completos equivalentes, energia movimentada / (2 · capacidade nominal), agregados pela capacidade no distrito e no portefólio. `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `battery_health_capacity_fade{,_business_as_usual,_delta_to_business_as_usual}_ratio` | building, district | ratio | Fração da capacidade nominal perdida por degradação, (capacidade − capacidade degradada) / capacidade, limitada a [0, 1]; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `battery_ratio_to_business_as_usual_{charge,discharge,throughput,equivalent_full_cycles,capacity_fade}_ratio` | building, district | ratio | Valor do controlo sobre o valor BAU da carga, descarga, energia movimentada, ciclos completos equivalentes ou perda de capacidade. |

<details>
<summary>Todos os 40 nomes</summary>

```text
building_battery_health_capacity_fade_business_as_usual_ratio
building_battery_health_capacity_fade_delta_to_business_as_usual_ratio
building_battery_health_capacity_fade_ratio
building_battery_health_equivalent_full_cycles_business_as_usual_count
building_battery_health_equivalent_full_cycles_count
building_battery_health_equivalent_full_cycles_delta_to_business_as_usual_count
building_battery_ratio_to_business_as_usual_capacity_fade_ratio
building_battery_ratio_to_business_as_usual_charge_ratio
building_battery_ratio_to_business_as_usual_discharge_ratio
building_battery_ratio_to_business_as_usual_equivalent_full_cycles_ratio
building_battery_ratio_to_business_as_usual_throughput_ratio
building_battery_total_charge_business_as_usual_kwh
building_battery_total_charge_delta_to_business_as_usual_kwh
building_battery_total_charge_kwh
building_battery_total_discharge_business_as_usual_kwh
building_battery_total_discharge_delta_to_business_as_usual_kwh
building_battery_total_discharge_kwh
building_battery_total_throughput_business_as_usual_kwh
building_battery_total_throughput_delta_to_business_as_usual_kwh
building_battery_total_throughput_kwh
district_battery_health_capacity_fade_business_as_usual_ratio
district_battery_health_capacity_fade_delta_to_business_as_usual_ratio
district_battery_health_capacity_fade_ratio
district_battery_health_equivalent_full_cycles_business_as_usual_count
district_battery_health_equivalent_full_cycles_count
district_battery_health_equivalent_full_cycles_delta_to_business_as_usual_count
district_battery_ratio_to_business_as_usual_capacity_fade_ratio
district_battery_ratio_to_business_as_usual_charge_ratio
district_battery_ratio_to_business_as_usual_discharge_ratio
district_battery_ratio_to_business_as_usual_equivalent_full_cycles_ratio
district_battery_ratio_to_business_as_usual_throughput_ratio
district_battery_total_charge_business_as_usual_kwh
district_battery_total_charge_delta_to_business_as_usual_kwh
district_battery_total_charge_kwh
district_battery_total_discharge_business_as_usual_kwh
district_battery_total_discharge_delta_to_business_as_usual_kwh
district_battery_total_discharge_kwh
district_battery_total_throughput_business_as_usual_kwh
district_battery_total_throughput_delta_to_business_as_usual_kwh
district_battery_total_throughput_kwh
```

</details>

## Serviço elétrico e fases

Cumprimento dos limites de potência total e por fase declarados para o serviço elétrico, e o equilíbrio e os picos das fases; os valores são nulos ou indefinidos se o esquema não configurar um serviço elétrico.

Equações e regras: [Serviço elétrico e fases](kpis_reference.md#serviço-elétrico-e-fases).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `electrical_service_phase_violations_energy_total_kwh` | building, district | kWh | Energia da potência aplicada acima dos limites declarados de importação e exportação, totais e por fase, depois do tratamento das restrições; excessos até 1e-5 kW são ignorados. |
| `electrical_service_phase_violations_event_count` | building, district | count | Número de passos com violação acima de 1e-9 kWh, somado sobre os edifícios ao nível do distrito. |
| `electrical_service_phase_requested_pressure_energy_total_kwh` | building, district | kWh | Energia em que o pedido do controlador, antes da projeção nos limites, os teria excedido; não é uma violação aplicada. |
| `electrical_service_phase_requested_pressure_event_count` | building, district | count | Número de passos com pressão pedida acima de 1e-9 kWh, somado sobre os edifícios ao nível do distrito. |
| `electrical_service_phase_imbalance_phase_average_ratio` | building, district | ratio | Média sobre os passos de (máx \|P\| − mín \|P\|) / média \|P\| nas três fases, 0 quando média \|P\| ≤ 1e-9 kW; só edifícios trifásicos, e o valor do distrito é a média sobre todos os passos de todos os edifícios. |
| `electrical_service_phase_phase_peaks_{import,export}_peak_{l1,l2,l3}_kw` | building, district | kW | Maior potência de importação ou de exportação em cada fase; o valor do distrito é o pico da soma da potência dessa fase dos membros. |

<details>
<summary>Todos os 22 nomes</summary>

```text
building_electrical_service_phase_imbalance_phase_average_ratio
building_electrical_service_phase_phase_peaks_export_peak_l1_kw
building_electrical_service_phase_phase_peaks_export_peak_l2_kw
building_electrical_service_phase_phase_peaks_export_peak_l3_kw
building_electrical_service_phase_phase_peaks_import_peak_l1_kw
building_electrical_service_phase_phase_peaks_import_peak_l2_kw
building_electrical_service_phase_phase_peaks_import_peak_l3_kw
building_electrical_service_phase_requested_pressure_energy_total_kwh
building_electrical_service_phase_requested_pressure_event_count
building_electrical_service_phase_violations_energy_total_kwh
building_electrical_service_phase_violations_event_count
district_electrical_service_phase_imbalance_phase_average_ratio
district_electrical_service_phase_phase_peaks_export_peak_l1_kw
district_electrical_service_phase_phase_peaks_export_peak_l2_kw
district_electrical_service_phase_phase_peaks_export_peak_l3_kw
district_electrical_service_phase_phase_peaks_import_peak_l1_kw
district_electrical_service_phase_phase_peaks_import_peak_l2_kw
district_electrical_service_phase_phase_peaks_import_peak_l3_kw
district_electrical_service_phase_requested_pressure_energy_total_kwh
district_electrical_service_phase_requested_pressure_event_count
district_electrical_service_phase_violations_energy_total_kwh
district_electrical_service_phase_violations_event_count
```

</details>

## Veículos elétricos

Serviço à partida, energia de carregamento e V2G dos veículos elétricos (VE) nos carregadores dos membros, e saúde e desgaste opt-in das baterias dos VE (`evaluate_v2(include_battery_health_audit=True)`). Todos os membros emitem as linhas de partida e energia; sem carregadores, as contagens e energias são 0 e as taxas ficam indefinidas.

Equações e regras: [Veículos elétricos](kpis_reference.md#veículos-elétricos).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `ev_events_departure_count` | building, district | count | Partidas com VE e bateria ligados, SOC alvo válido e SOC finito à partida; é o denominador das taxas e médias `ev_performance`. |
| `ev_events_departure_{met,min_acceptable,within_tolerance}_count` | building, district | count | **Legada**; linha canónica: `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_met_count`. Partidas contadas cujo SOC cumpriu o alvo, o SOC mínimo aceitável (alvo menos a tolerância de serviço) ou a banda simétrica de tolerância em torno do alvo. |
| `ev_events_departure_{target,min_acceptable,within_tolerance}_{feasible,infeasible}_count` | building, district | count | **Legada**; linha canónica: `ev_departure_audit_{target,min_acceptable,within_tolerance}_{feasible,infeasible}_count`. Partidas contadas cujo limiar era ou não alcançável carregando à potência máxima durante a ligação; regra antiga, em que dados em falta contam como viáveis, pelo que viáveis + inviáveis igualam o número de partidas. |
| `ev_performance_departure_{success,min_acceptable,within_tolerance}_ratio` | building, district | ratio | **Legada**; linha canónica: `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_observed_ratio`. Fração das partidas contadas que cumpriram o alvo, o SOC mínimo aceitável ou a banda de tolerância; indefinida sem partidas. |
| `ev_performance_departure_{success,min_acceptable,within_tolerance}_feasible_ratio` | building, district | ratio | **Legada**; linha canónica: `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_feasible_ratio`. A mesma fração sobre as partidas viáveis para esse limiar segundo a regra antiga; indefinida quando nenhuma é viável. |
| `ev_performance_departure_{soc_deficit,shortfall_beyond_tolerance,soc_surplus,soc_absolute_error}_mean_ratio` | building, district | ratio | Média sobre as partidas contadas, em fração de SOC, de max(alvo − SOC, 0), max(alvo − tolerância − SOC, 0), max(SOC − alvo, 0) ou \|SOC − alvo\|; indefinida sem partidas. |
| `ev_performance_departure_tolerance_ratio` | building, district | ratio | Eco da configuração: o parâmetro `ev_departure_service_tolerance` (por omissão 0,05), não uma medição. |
| `ev_total_charge{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia AC bruta absorvida pelos carregadores para carregar os VE, incluindo as perdas do carregador; `_business_as_usual` e `_delta_to_business_as_usual` conforme as regras comuns. |
| `ev_total_v2g_export{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia AC bruta fornecida pelos carregadores a partir da descarga dos VE, após as perdas do carregador; não é exportação para a rede. `_business_as_usual` e `_delta_to_business_as_usual` conforme as regras comuns. |
| `ev_ratio_to_business_as_usual_{charge,v2g_export}_total_ratio` | building, district | ratio | Total de carga ou de V2G do controlo sobre o do BAU, conforme as regras comuns; como o BAU nunca usa V2G, o ratio V2G fica indefinido sempre que o controlador descarrega. |
| `ev_energy_accounting_connected_soc_gain_kwh` | building, district | kWh | Soma, sobre as partidas contadas, de max(SOC à partida − SOC à chegada, 0) vezes a capacidade nominal da bateria. |
| `ev_energy_accounting_shortfall_kwh` | building, district | kWh | Por membro, max(ganho de SOC − total de carga, 0): ganho de SOC não explicado pela carga medida; o valor do distrito é a soma dos valores dos membros. |
| `ev_window_net_exchange_control_kwh` | building, district | kWh | Energia AC líquida com sinal nos carregadores de VE dentro da janela local recorrente `evaluation_window` (positiva no carregamento, negativa na entrega V2X); só é emitida quando `evaluation_window.enabled` é verdadeiro. |
| `ev_battery_health_terminal_soh_ratio` | building, district | ratio | Estado de saúde terminal opt-in das baterias dos VE ponderado pela capacidade em [0, 1] (`include_battery_health_audit=True`). Ao nível do edifício, é lido no fim da última ligação efetiva de cada VE ligado e inclui o desgaste recebido noutros edifícios, pelo que o SOH do edifício pode ser inferior a 1 − ev_battery_health_capacity_fade_ratio; no distrito e no portefólio, é agregado sobre os VE elegíveis únicos da frota pela capacidade nominal (igual a 1 − rácio de perda); indefinido quando a capacidade nominal ≤ 0. |
| `ev_battery_health_capacity_fade_kwh` | building, district | kWh | Capacidade acumulada opt-in das baterias dos VE perdida por degradação em [kWh] (`include_battery_health_audit=True`), atribuída às transferências executadas nos carregadores do membro ao nível do edifício e somada sobre os VE elegíveis únicos da frota no distrito e no portefólio. |
| `ev_battery_health_capacity_fade_ratio` | building, district | ratio | Fração opt-in da capacidade nominal das baterias dos VE perdida por degradação em [0, 1] (`include_battery_health_audit=True`), a partir das transferências executadas sobre a capacidade dos VE efetivamente ligados no edifício e agregada pela capacidade nominal dos VE elegíveis únicos da frota no distrito e no portefólio; indefinida quando a capacidade nominal ≤ 0. |
| `ev_battery_health_equivalent_full_cycles_count` | building, district | count | Ciclos completos equivalentes opt-in das baterias dos VE a partir da energia bruta aceite nos terminais da bateria sobre (2 · capacidade nominal) (`include_battery_health_audit=True`), atribuídos às transferências executadas sobre a capacidade dos VE efetivamente ligados no edifício e agregados pela capacidade nominal dos VE elegíveis únicos da frota no distrito e no portefólio; indefinido quando a capacidade nominal ≤ 0 (enquanto `Battery.equivalent_full_cycles` devolve `0.0`). |

<details>
<summary>Todos os 72 nomes</summary>

```text
building_ev_battery_health_capacity_fade_kwh
building_ev_battery_health_capacity_fade_ratio
building_ev_battery_health_equivalent_full_cycles_count
building_ev_battery_health_terminal_soh_ratio
building_ev_energy_accounting_connected_soc_gain_kwh
building_ev_energy_accounting_shortfall_kwh
building_ev_events_departure_count
building_ev_events_departure_met_count
building_ev_events_departure_min_acceptable_count
building_ev_events_departure_min_acceptable_feasible_count
building_ev_events_departure_min_acceptable_infeasible_count
building_ev_events_departure_target_feasible_count
building_ev_events_departure_target_infeasible_count
building_ev_events_departure_within_tolerance_count
building_ev_events_departure_within_tolerance_feasible_count
building_ev_events_departure_within_tolerance_infeasible_count
building_ev_performance_departure_min_acceptable_feasible_ratio
building_ev_performance_departure_min_acceptable_ratio
building_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio
building_ev_performance_departure_soc_absolute_error_mean_ratio
building_ev_performance_departure_soc_deficit_mean_ratio
building_ev_performance_departure_soc_surplus_mean_ratio
building_ev_performance_departure_success_feasible_ratio
building_ev_performance_departure_success_ratio
building_ev_performance_departure_tolerance_ratio
building_ev_performance_departure_within_tolerance_feasible_ratio
building_ev_performance_departure_within_tolerance_ratio
building_ev_ratio_to_business_as_usual_charge_total_ratio
building_ev_ratio_to_business_as_usual_v2g_export_total_ratio
building_ev_total_charge_business_as_usual_kwh
building_ev_total_charge_delta_to_business_as_usual_kwh
building_ev_total_charge_kwh
building_ev_total_v2g_export_business_as_usual_kwh
building_ev_total_v2g_export_delta_to_business_as_usual_kwh
building_ev_total_v2g_export_kwh
building_ev_window_net_exchange_control_kwh
district_ev_battery_health_capacity_fade_kwh
district_ev_battery_health_capacity_fade_ratio
district_ev_battery_health_equivalent_full_cycles_count
district_ev_battery_health_terminal_soh_ratio
district_ev_energy_accounting_connected_soc_gain_kwh
district_ev_energy_accounting_shortfall_kwh
district_ev_events_departure_count
district_ev_events_departure_met_count
district_ev_events_departure_min_acceptable_count
district_ev_events_departure_min_acceptable_feasible_count
district_ev_events_departure_min_acceptable_infeasible_count
district_ev_events_departure_target_feasible_count
district_ev_events_departure_target_infeasible_count
district_ev_events_departure_within_tolerance_count
district_ev_events_departure_within_tolerance_feasible_count
district_ev_events_departure_within_tolerance_infeasible_count
district_ev_performance_departure_min_acceptable_feasible_ratio
district_ev_performance_departure_min_acceptable_ratio
district_ev_performance_departure_shortfall_beyond_tolerance_mean_ratio
district_ev_performance_departure_soc_absolute_error_mean_ratio
district_ev_performance_departure_soc_deficit_mean_ratio
district_ev_performance_departure_soc_surplus_mean_ratio
district_ev_performance_departure_success_feasible_ratio
district_ev_performance_departure_success_ratio
district_ev_performance_departure_tolerance_ratio
district_ev_performance_departure_within_tolerance_feasible_ratio
district_ev_performance_departure_within_tolerance_ratio
district_ev_ratio_to_business_as_usual_charge_total_ratio
district_ev_ratio_to_business_as_usual_v2g_export_total_ratio
district_ev_total_charge_business_as_usual_kwh
district_ev_total_charge_delta_to_business_as_usual_kwh
district_ev_total_charge_kwh
district_ev_total_v2g_export_business_as_usual_kwh
district_ev_total_v2g_export_delta_to_business_as_usual_kwh
district_ev_total_v2g_export_kwh
district_ev_window_net_exchange_control_kwh
```

</details>

## Auditoria das partidas dos VE

Serviço auditado às partidas dos VE, com uma população explícita, um estado de viabilidade com três classes e o motivo de cada caso desconhecido. Todos os membros emitem estas linhas.

Equações e regras: [Auditoria das partidas dos VE](kpis_reference.md#auditoria-das-partidas-dos-ve).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `ev_departure_audit_departures_count` | building, district | count | Todas as partidas detetadas num carregador ativo nesse passo, sejam ou não conhecidos o VE, o alvo ou o SOC. |
| `ev_departure_audit_service_{observed,unknown}_count` | building, district | count | Partidas cujo serviço foi observado (alvo válido e SOC à partida em [0, 1]) ou não; as duas somam o número de partidas. |
| `ev_departure_audit_service_coverage_ratio` | building, district | ratio | Partidas observadas sobre todas as partidas; indefinido sem partidas. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_{feasible,infeasible,unknown}_count` | building, district | count | Partidas cujo limiar era alcançável, não alcançável, ou não pôde ser avaliado pela simulação da auditoria; as três somam o número de partidas. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_unknown_{missing_target,missing_ev,missing_battery,invalid_capacity,invalid_charger_power,invalid_charger_efficiency,invalid_time_step,missing_arrival_soc,unsupported_battery_model,invalid_battery_parameters,outage_supply_not_replayed}_count` | building, district | count | Partidas desconhecidas pelo primeiro motivo aplicável; os motivos somam o número de desconhecidas do limiar. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_met_count` | building, district | count | Partidas observadas que cumpriram o limiar, independentemente da viabilidade. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_feasible_service_{observed,met}_count` | building, district | count | Partidas viáveis cujo serviço foi observado, e as que entre elas cumpriram o limiar. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_coverage_ratio` | building, district | ratio | (Viáveis + inviáveis) sobre todas as partidas: a fração cuja viabilidade é conhecida; indefinido sem partidas. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_observed_ratio` | building, district | ratio | Partidas que cumpriram o limiar sobre as partidas observadas, viáveis ou não; indefinido sem partidas observadas. |
| `ev_departure_audit_{target,min_acceptable,within_tolerance}_service_feasible_ratio` | building, district | ratio | Partidas viáveis e observadas que cumpriram o limiar sobre as partidas viáveis e observadas; é o ratio canónico para comparar controladores, indefinido quando o denominador é 0. |

<details>
<summary>Todos os 128 nomes</summary>

```text
building_ev_departure_audit_departures_count
building_ev_departure_audit_min_acceptable_coverage_ratio
building_ev_departure_audit_min_acceptable_feasible_count
building_ev_departure_audit_min_acceptable_feasible_service_met_count
building_ev_departure_audit_min_acceptable_feasible_service_observed_count
building_ev_departure_audit_min_acceptable_infeasible_count
building_ev_departure_audit_min_acceptable_service_feasible_ratio
building_ev_departure_audit_min_acceptable_service_met_count
building_ev_departure_audit_min_acceptable_service_observed_ratio
building_ev_departure_audit_min_acceptable_unknown_count
building_ev_departure_audit_min_acceptable_unknown_invalid_battery_parameters_count
building_ev_departure_audit_min_acceptable_unknown_invalid_capacity_count
building_ev_departure_audit_min_acceptable_unknown_invalid_charger_efficiency_count
building_ev_departure_audit_min_acceptable_unknown_invalid_charger_power_count
building_ev_departure_audit_min_acceptable_unknown_invalid_time_step_count
building_ev_departure_audit_min_acceptable_unknown_missing_arrival_soc_count
building_ev_departure_audit_min_acceptable_unknown_missing_battery_count
building_ev_departure_audit_min_acceptable_unknown_missing_ev_count
building_ev_departure_audit_min_acceptable_unknown_missing_target_count
building_ev_departure_audit_min_acceptable_unknown_outage_supply_not_replayed_count
building_ev_departure_audit_min_acceptable_unknown_unsupported_battery_model_count
building_ev_departure_audit_service_coverage_ratio
building_ev_departure_audit_service_observed_count
building_ev_departure_audit_service_unknown_count
building_ev_departure_audit_target_coverage_ratio
building_ev_departure_audit_target_feasible_count
building_ev_departure_audit_target_feasible_service_met_count
building_ev_departure_audit_target_feasible_service_observed_count
building_ev_departure_audit_target_infeasible_count
building_ev_departure_audit_target_service_feasible_ratio
building_ev_departure_audit_target_service_met_count
building_ev_departure_audit_target_service_observed_ratio
building_ev_departure_audit_target_unknown_count
building_ev_departure_audit_target_unknown_invalid_battery_parameters_count
building_ev_departure_audit_target_unknown_invalid_capacity_count
building_ev_departure_audit_target_unknown_invalid_charger_efficiency_count
building_ev_departure_audit_target_unknown_invalid_charger_power_count
building_ev_departure_audit_target_unknown_invalid_time_step_count
building_ev_departure_audit_target_unknown_missing_arrival_soc_count
building_ev_departure_audit_target_unknown_missing_battery_count
building_ev_departure_audit_target_unknown_missing_ev_count
building_ev_departure_audit_target_unknown_missing_target_count
building_ev_departure_audit_target_unknown_outage_supply_not_replayed_count
building_ev_departure_audit_target_unknown_unsupported_battery_model_count
building_ev_departure_audit_within_tolerance_coverage_ratio
building_ev_departure_audit_within_tolerance_feasible_count
building_ev_departure_audit_within_tolerance_feasible_service_met_count
building_ev_departure_audit_within_tolerance_feasible_service_observed_count
building_ev_departure_audit_within_tolerance_infeasible_count
building_ev_departure_audit_within_tolerance_service_feasible_ratio
building_ev_departure_audit_within_tolerance_service_met_count
building_ev_departure_audit_within_tolerance_service_observed_ratio
building_ev_departure_audit_within_tolerance_unknown_count
building_ev_departure_audit_within_tolerance_unknown_invalid_battery_parameters_count
building_ev_departure_audit_within_tolerance_unknown_invalid_capacity_count
building_ev_departure_audit_within_tolerance_unknown_invalid_charger_efficiency_count
building_ev_departure_audit_within_tolerance_unknown_invalid_charger_power_count
building_ev_departure_audit_within_tolerance_unknown_invalid_time_step_count
building_ev_departure_audit_within_tolerance_unknown_missing_arrival_soc_count
building_ev_departure_audit_within_tolerance_unknown_missing_battery_count
building_ev_departure_audit_within_tolerance_unknown_missing_ev_count
building_ev_departure_audit_within_tolerance_unknown_missing_target_count
building_ev_departure_audit_within_tolerance_unknown_outage_supply_not_replayed_count
building_ev_departure_audit_within_tolerance_unknown_unsupported_battery_model_count
district_ev_departure_audit_departures_count
district_ev_departure_audit_min_acceptable_coverage_ratio
district_ev_departure_audit_min_acceptable_feasible_count
district_ev_departure_audit_min_acceptable_feasible_service_met_count
district_ev_departure_audit_min_acceptable_feasible_service_observed_count
district_ev_departure_audit_min_acceptable_infeasible_count
district_ev_departure_audit_min_acceptable_service_feasible_ratio
district_ev_departure_audit_min_acceptable_service_met_count
district_ev_departure_audit_min_acceptable_service_observed_ratio
district_ev_departure_audit_min_acceptable_unknown_count
district_ev_departure_audit_min_acceptable_unknown_invalid_battery_parameters_count
district_ev_departure_audit_min_acceptable_unknown_invalid_capacity_count
district_ev_departure_audit_min_acceptable_unknown_invalid_charger_efficiency_count
district_ev_departure_audit_min_acceptable_unknown_invalid_charger_power_count
district_ev_departure_audit_min_acceptable_unknown_invalid_time_step_count
district_ev_departure_audit_min_acceptable_unknown_missing_arrival_soc_count
district_ev_departure_audit_min_acceptable_unknown_missing_battery_count
district_ev_departure_audit_min_acceptable_unknown_missing_ev_count
district_ev_departure_audit_min_acceptable_unknown_missing_target_count
district_ev_departure_audit_min_acceptable_unknown_outage_supply_not_replayed_count
district_ev_departure_audit_min_acceptable_unknown_unsupported_battery_model_count
district_ev_departure_audit_service_coverage_ratio
district_ev_departure_audit_service_observed_count
district_ev_departure_audit_service_unknown_count
district_ev_departure_audit_target_coverage_ratio
district_ev_departure_audit_target_feasible_count
district_ev_departure_audit_target_feasible_service_met_count
district_ev_departure_audit_target_feasible_service_observed_count
district_ev_departure_audit_target_infeasible_count
district_ev_departure_audit_target_service_feasible_ratio
district_ev_departure_audit_target_service_met_count
district_ev_departure_audit_target_service_observed_ratio
district_ev_departure_audit_target_unknown_count
district_ev_departure_audit_target_unknown_invalid_battery_parameters_count
district_ev_departure_audit_target_unknown_invalid_capacity_count
district_ev_departure_audit_target_unknown_invalid_charger_efficiency_count
district_ev_departure_audit_target_unknown_invalid_charger_power_count
district_ev_departure_audit_target_unknown_invalid_time_step_count
district_ev_departure_audit_target_unknown_missing_arrival_soc_count
district_ev_departure_audit_target_unknown_missing_battery_count
district_ev_departure_audit_target_unknown_missing_ev_count
district_ev_departure_audit_target_unknown_missing_target_count
district_ev_departure_audit_target_unknown_outage_supply_not_replayed_count
district_ev_departure_audit_target_unknown_unsupported_battery_model_count
district_ev_departure_audit_within_tolerance_coverage_ratio
district_ev_departure_audit_within_tolerance_feasible_count
district_ev_departure_audit_within_tolerance_feasible_service_met_count
district_ev_departure_audit_within_tolerance_feasible_service_observed_count
district_ev_departure_audit_within_tolerance_infeasible_count
district_ev_departure_audit_within_tolerance_service_feasible_ratio
district_ev_departure_audit_within_tolerance_service_met_count
district_ev_departure_audit_within_tolerance_service_observed_ratio
district_ev_departure_audit_within_tolerance_unknown_count
district_ev_departure_audit_within_tolerance_unknown_invalid_battery_parameters_count
district_ev_departure_audit_within_tolerance_unknown_invalid_capacity_count
district_ev_departure_audit_within_tolerance_unknown_invalid_charger_efficiency_count
district_ev_departure_audit_within_tolerance_unknown_invalid_charger_power_count
district_ev_departure_audit_within_tolerance_unknown_invalid_time_step_count
district_ev_departure_audit_within_tolerance_unknown_missing_arrival_soc_count
district_ev_departure_audit_within_tolerance_unknown_missing_battery_count
district_ev_departure_audit_within_tolerance_unknown_missing_ev_count
district_ev_departure_audit_within_tolerance_unknown_missing_target_count
district_ev_departure_audit_within_tolerance_unknown_outage_supply_not_replayed_count
district_ev_departure_audit_within_tolerance_unknown_unsupported_battery_model_count
```

</details>

## Equipamentos flexíveis

Serviço dos ciclos dos equipamentos flexíveis (diferíveis) a partir dos estados dos ciclos e das energias nominais dos ciclos. Todos os membros emitem estas linhas; sem equipamentos, as contagens e energias são 0 e as taxas ficam indefinidas. As contagens, o nível de serviço e as energias do controlo são linhas legadas; a auditoria dos equipamentos flexíveis (`deferrable_appliance_audit_*`) é a canónica. Estas linhas guardam a única comparação com o BAU.

Equações e regras: [Equipamentos flexíveis](kpis_reference.md#equipamentos-flexíveis).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `deferrable_appliance_service_completed_cycles_count` | building, district | count | **Legada**; linha canónica: `deferrable_appliance_audit_completed_count`. Ciclos que executaram o perfil completo. Linha legada; a contagem auditada é `deferrable_appliance_audit_completed_count`. |
| `deferrable_appliance_service_completed_cycles{_business_as_usual,_delta_to_business_as_usual}_count` | building, district | count | Ciclos que executaram o perfil completo; `_business_as_usual` e `_delta_to_business_as_usual` conforme as regras comuns. |
| `deferrable_appliance_service_missed_cycles_count` | building, district | count | **Legada**; linha canónica: `deferrable_appliance_audit_missed_count`. Ciclos não iniciados até ao último passo de arranque, mais os ciclos em curso interrompidos por um corte de energia. Linha legada; a contagem auditada é `deferrable_appliance_audit_missed_count`. |
| `deferrable_appliance_service_missed_cycles{_business_as_usual,_delta_to_business_as_usual}_count` | building, district | count | Ciclos não iniciados até ao último passo de arranque, mais os ciclos em curso interrompidos por um corte de energia; variantes BAU conforme as regras comuns. |
| `deferrable_appliance_service_service_level_ratio` | building, district | ratio | **Legada**; linha canónica: `deferrable_appliance_audit_resolved_completion_ratio`. concluídos / (concluídos + falhados), indefinido quando ambos são 0. Linha legada; a taxa auditada é `deferrable_appliance_audit_resolved_completion_ratio`, que conta também os ciclos cancelados. |
| `deferrable_appliance_service_service_level{_business_as_usual,_delta_to_business_as_usual}_ratio` | building, district | ratio | concluídos / (concluídos + falhados), indefinido quando ambos são 0; o delta fica indefinido quando um dos lados o está. |
| `deferrable_appliance_service_served_energy_total_kwh` | building, district | kWh | **Legada**; linha canónica: `deferrable_appliance_audit_served_energy_kwh`. Energia nominal dos ciclos concluídos, a partir dos perfis pedidos, não medida. Linha legada; a energia auditada, medida, é `deferrable_appliance_audit_served_energy_kwh`. |
| `deferrable_appliance_service_served_energy_total{_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia nominal dos ciclos concluídos, a partir dos perfis pedidos, não medida; variantes BAU conforme as regras comuns. |
| `deferrable_appliance_service_unserved_energy_total_kwh` | building, district | kWh | **Legada**; linha canónica: `deferrable_appliance_audit_final_unserved_energy_kwh`. Energia nominal completa dos ciclos falhados, incluindo a parte consumida antes de uma interrupção. Linha legada; a energia auditada é `deferrable_appliance_audit_final_unserved_energy_kwh`. |
| `deferrable_appliance_service_unserved_energy_total{_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia nominal completa dos ciclos falhados, incluindo a parte consumida antes de uma interrupção; variantes BAU conforme as regras comuns. |
| `deferrable_appliance_service_average_start_delay{,_business_as_usual,_delta_to_business_as_usual}_hours` | building, district | hours | Média, sobre os ciclos concluídos, de (arranque − arranque mais cedo) em horas; indefinida quando nenhum ciclo foi concluído. |
| `deferrable_appliance_ratio_to_business_as_usual_{completed_cycles,missed_cycles,service_level,served_energy_total,unserved_energy_total,average_start_delay}_ratio` | building, district | ratio | Valor do controlo sobre o do BAU; indefinido quando os seus próprios dois totais são zero, mesmo que houvesse ciclos devidos (#305), e quando o valor BAU é zero ou um dos valores é indefinido. |

<details>
<summary>Todos os 48 nomes</summary>

```text
building_deferrable_appliance_ratio_to_business_as_usual_average_start_delay_ratio
building_deferrable_appliance_ratio_to_business_as_usual_completed_cycles_ratio
building_deferrable_appliance_ratio_to_business_as_usual_missed_cycles_ratio
building_deferrable_appliance_ratio_to_business_as_usual_served_energy_total_ratio
building_deferrable_appliance_ratio_to_business_as_usual_service_level_ratio
building_deferrable_appliance_ratio_to_business_as_usual_unserved_energy_total_ratio
building_deferrable_appliance_service_average_start_delay_business_as_usual_hours
building_deferrable_appliance_service_average_start_delay_delta_to_business_as_usual_hours
building_deferrable_appliance_service_average_start_delay_hours
building_deferrable_appliance_service_completed_cycles_business_as_usual_count
building_deferrable_appliance_service_completed_cycles_count
building_deferrable_appliance_service_completed_cycles_delta_to_business_as_usual_count
building_deferrable_appliance_service_missed_cycles_business_as_usual_count
building_deferrable_appliance_service_missed_cycles_count
building_deferrable_appliance_service_missed_cycles_delta_to_business_as_usual_count
building_deferrable_appliance_service_served_energy_total_business_as_usual_kwh
building_deferrable_appliance_service_served_energy_total_delta_to_business_as_usual_kwh
building_deferrable_appliance_service_served_energy_total_kwh
building_deferrable_appliance_service_service_level_business_as_usual_ratio
building_deferrable_appliance_service_service_level_delta_to_business_as_usual_ratio
building_deferrable_appliance_service_service_level_ratio
building_deferrable_appliance_service_unserved_energy_total_business_as_usual_kwh
building_deferrable_appliance_service_unserved_energy_total_delta_to_business_as_usual_kwh
building_deferrable_appliance_service_unserved_energy_total_kwh
district_deferrable_appliance_ratio_to_business_as_usual_average_start_delay_ratio
district_deferrable_appliance_ratio_to_business_as_usual_completed_cycles_ratio
district_deferrable_appliance_ratio_to_business_as_usual_missed_cycles_ratio
district_deferrable_appliance_ratio_to_business_as_usual_served_energy_total_ratio
district_deferrable_appliance_ratio_to_business_as_usual_service_level_ratio
district_deferrable_appliance_ratio_to_business_as_usual_unserved_energy_total_ratio
district_deferrable_appliance_service_average_start_delay_business_as_usual_hours
district_deferrable_appliance_service_average_start_delay_delta_to_business_as_usual_hours
district_deferrable_appliance_service_average_start_delay_hours
district_deferrable_appliance_service_completed_cycles_business_as_usual_count
district_deferrable_appliance_service_completed_cycles_count
district_deferrable_appliance_service_completed_cycles_delta_to_business_as_usual_count
district_deferrable_appliance_service_missed_cycles_business_as_usual_count
district_deferrable_appliance_service_missed_cycles_count
district_deferrable_appliance_service_missed_cycles_delta_to_business_as_usual_count
district_deferrable_appliance_service_served_energy_total_business_as_usual_kwh
district_deferrable_appliance_service_served_energy_total_delta_to_business_as_usual_kwh
district_deferrable_appliance_service_served_energy_total_kwh
district_deferrable_appliance_service_service_level_business_as_usual_ratio
district_deferrable_appliance_service_service_level_delta_to_business_as_usual_ratio
district_deferrable_appliance_service_service_level_ratio
district_deferrable_appliance_service_unserved_energy_total_business_as_usual_kwh
district_deferrable_appliance_service_unserved_energy_total_delta_to_business_as_usual_kwh
district_deferrable_appliance_service_unserved_energy_total_kwh
```

</details>

## Auditoria dos equipamentos flexíveis

Serviço auditado dos ciclos dos equipamentos flexíveis a partir da energia medida nos intervalos executados, com uma população explícita e estados exclusivos. Todos os membros emitem estas linhas.

Equações e regras: [Auditoria dos equipamentos flexíveis](kpis_reference.md#auditoria-dos-equipamentos-flexíveis).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `deferrable_appliance_audit_{catalogue,offered,excluded}_count` | building, district | count | Pedidos de ciclo no catálogo, os incluídos na população auditada (oferecidos) e os restantes (excluídos = catálogo − oferecidos). |
| `deferrable_appliance_audit_duplicate_offered_count` | building, district | count | Pedidos oferecidos que voltam a surgir numa instância posterior do mesmo equipamento, por exemplo após uma reinstalação; só o primeiro é mantido. |
| `deferrable_appliance_audit_{pending,running,completed,missed,cancelled}_count` | building, district | count | Pedidos oferecidos por estado final exclusivo. |
| `deferrable_appliance_audit_resolved_count` | building, district | count | concluídos + falhados + cancelados. |
| `deferrable_appliance_audit_excluded_{expired_before_episode,expired_before_activation,not_yet_available,removed_before_available,outside_episode_service_horizon,already_accounted_previous_instance}_count` | building, district | count | Pedidos excluídos pelo primeiro motivo de exclusão aplicável; os motivos somam o número de excluídos. |
| `deferrable_appliance_audit_reason_{profile_delivered,profile_energy_shortfall,start_window_elapsed,asset_removed,member_removed,window_open,profile_in_progress}_count` | building, district | count | Pedidos oferecidos pelo motivo do seu estado. |
| `deferrable_appliance_audit_{requested,served,final_unserved,outstanding}_energy_kwh` | building, district | kWh | Sobre os pedidos oferecidos: energia pedida, energia medida atribuída aos ciclos, o remanescente dos pedidos falhados e cancelados, e o remanescente dos pendentes e em curso. |
| `deferrable_appliance_audit_excluded_requested_energy_kwh` | building, district | kWh | Energia pedida dos pedidos excluídos. |
| `deferrable_appliance_audit_physical_energy_kwh` | building, district | kWh | Energia medida dos equipamentos em todos os intervalos executados, antes da atribuição aos ciclos. |
| `deferrable_appliance_audit_physical_balance_residual_kwh` | building, district | kWh | Energia física − energia servida: energia medida que nenhum pedido oferecido explica. |
| `deferrable_appliance_audit_service_balance_residual_kwh` | building, district | kWh | Pedida − servida − não servida final − em aberto; cerca de 0 por construção, é uma verificação de consistência. |
| `deferrable_appliance_audit_observed_completion_ratio` | building, district | ratio | concluídos / oferecidos; indefinido quando nada foi oferecido. |
| `deferrable_appliance_audit_resolved_completion_ratio` | building, district | ratio | concluídos / resolvidos; indefinido quando nada foi resolvido. |
| `deferrable_appliance_audit_resolved_coverage_ratio` | building, district | ratio | resolvidos / oferecidos; indefinido quando nada foi oferecido. |

<details>
<summary>Todos os 68 nomes</summary>

```text
building_deferrable_appliance_audit_cancelled_count
building_deferrable_appliance_audit_catalogue_count
building_deferrable_appliance_audit_completed_count
building_deferrable_appliance_audit_duplicate_offered_count
building_deferrable_appliance_audit_excluded_already_accounted_previous_instance_count
building_deferrable_appliance_audit_excluded_count
building_deferrable_appliance_audit_excluded_expired_before_activation_count
building_deferrable_appliance_audit_excluded_expired_before_episode_count
building_deferrable_appliance_audit_excluded_not_yet_available_count
building_deferrable_appliance_audit_excluded_outside_episode_service_horizon_count
building_deferrable_appliance_audit_excluded_removed_before_available_count
building_deferrable_appliance_audit_excluded_requested_energy_kwh
building_deferrable_appliance_audit_final_unserved_energy_kwh
building_deferrable_appliance_audit_missed_count
building_deferrable_appliance_audit_observed_completion_ratio
building_deferrable_appliance_audit_offered_count
building_deferrable_appliance_audit_outstanding_energy_kwh
building_deferrable_appliance_audit_pending_count
building_deferrable_appliance_audit_physical_balance_residual_kwh
building_deferrable_appliance_audit_physical_energy_kwh
building_deferrable_appliance_audit_reason_asset_removed_count
building_deferrable_appliance_audit_reason_member_removed_count
building_deferrable_appliance_audit_reason_profile_delivered_count
building_deferrable_appliance_audit_reason_profile_energy_shortfall_count
building_deferrable_appliance_audit_reason_profile_in_progress_count
building_deferrable_appliance_audit_reason_start_window_elapsed_count
building_deferrable_appliance_audit_reason_window_open_count
building_deferrable_appliance_audit_requested_energy_kwh
building_deferrable_appliance_audit_resolved_completion_ratio
building_deferrable_appliance_audit_resolved_count
building_deferrable_appliance_audit_resolved_coverage_ratio
building_deferrable_appliance_audit_running_count
building_deferrable_appliance_audit_served_energy_kwh
building_deferrable_appliance_audit_service_balance_residual_kwh
district_deferrable_appliance_audit_cancelled_count
district_deferrable_appliance_audit_catalogue_count
district_deferrable_appliance_audit_completed_count
district_deferrable_appliance_audit_duplicate_offered_count
district_deferrable_appliance_audit_excluded_already_accounted_previous_instance_count
district_deferrable_appliance_audit_excluded_count
district_deferrable_appliance_audit_excluded_expired_before_activation_count
district_deferrable_appliance_audit_excluded_expired_before_episode_count
district_deferrable_appliance_audit_excluded_not_yet_available_count
district_deferrable_appliance_audit_excluded_outside_episode_service_horizon_count
district_deferrable_appliance_audit_excluded_removed_before_available_count
district_deferrable_appliance_audit_excluded_requested_energy_kwh
district_deferrable_appliance_audit_final_unserved_energy_kwh
district_deferrable_appliance_audit_missed_count
district_deferrable_appliance_audit_observed_completion_ratio
district_deferrable_appliance_audit_offered_count
district_deferrable_appliance_audit_outstanding_energy_kwh
district_deferrable_appliance_audit_pending_count
district_deferrable_appliance_audit_physical_balance_residual_kwh
district_deferrable_appliance_audit_physical_energy_kwh
district_deferrable_appliance_audit_reason_asset_removed_count
district_deferrable_appliance_audit_reason_member_removed_count
district_deferrable_appliance_audit_reason_profile_delivered_count
district_deferrable_appliance_audit_reason_profile_energy_shortfall_count
district_deferrable_appliance_audit_reason_profile_in_progress_count
district_deferrable_appliance_audit_reason_start_window_elapsed_count
district_deferrable_appliance_audit_reason_window_open_count
district_deferrable_appliance_audit_requested_energy_kwh
district_deferrable_appliance_audit_resolved_completion_ratio
district_deferrable_appliance_audit_resolved_count
district_deferrable_appliance_audit_resolved_coverage_ratio
district_deferrable_appliance_audit_running_count
district_deferrable_appliance_audit_served_energy_kwh
district_deferrable_appliance_audit_service_balance_residual_kwh
```

</details>

## Escadas rolantes

Serviço aos passageiros, mudanças de estado de funcionamento e consumo de eletricidade das escadas rolantes. Todos os membros emitem estas linhas; sem escadas rolantes, os totais são 0 e o nível de serviço fica indefinido.

Equações e regras: [Escadas rolantes](kpis_reference.md#escadas-rolantes).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `escalator_service_requested_passengers_total_count` | building, district | count | Soma dos valores de passageiros esperados nos passos com ação aplicada. |
| `escalator_service_{served,unserved}_passengers_total_count` | building, district | count | Não servidos: passageiros nos passos em que o serviço era exigido mas a escada estava em standby ou indisponível; servidos: pedidos − não servidos. |
| `escalator_service_service_level_ratio` | building, district | ratio | passageiros servidos / pedidos; indefinido quando não houve pedidos. |
| `escalator_energy_electricity_consumption_total_kwh` | building, district | kWh | Consumo de eletricidade das escadas rolantes nos passos com ação aplicada. |
| `escalator_operation_state_changes_count` | building, district | count | Passos em que o estado de funcionamento aplicado (standby, lento, normal) mudou. |

<details>
<summary>Todos os 12 nomes</summary>

```text
building_escalator_energy_electricity_consumption_total_kwh
building_escalator_operation_state_changes_count
building_escalator_service_requested_passengers_total_count
building_escalator_service_served_passengers_total_count
building_escalator_service_service_level_ratio
building_escalator_service_unserved_passengers_total_count
district_escalator_energy_electricity_consumption_total_kwh
district_escalator_operation_state_changes_count
district_escalator_service_requested_passengers_total_count
district_escalator_service_served_passengers_total_count
district_escalator_service_service_level_ratio
district_escalator_service_unserved_passengers_total_count
```

</details>

## Conforto e resiliência

Linhas legadas de conforto térmico e de resiliência a cortes de energia de cada edifício, sempre emitidas; o valor do distrito é a média simples dos edifícios, e o KPI de desconforto canónico é `district_thermal_service_audit_discomfort_ratio`.

Equações e regras: [Conforto e resiliência](kpis_reference.md#conforto-e-resiliência).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `comfort_resilience_discomfort_overall_ratio` | building, district | ratio | **Legada**; linha canónica: `thermal_service_audit_discomfort_ratio`. Fração dos passos ocupados avaliados demasiado frios (T < T_heat − banda) ou demasiado quentes (T > T_cool + banda); indefinida sem passos ocupados avaliados. O valor do distrito é a média dos edifícios; para comparar controladores use `thermal_service_audit_discomfort_ratio`. |
| `comfort_resilience_discomfort_{cold,hot}_ratio` | building, district | ratio | Fração dos passos ocupados avaliados demasiado frios (T < T_heat − banda) ou demasiado quentes (T > T_cool + banda); indefinida sem passos ocupados avaliados. O valor do distrito é a média dos edifícios. |
| `comfort_resilience_discomfort_{cold,hot}_delta_{min,max,average}_c` | building, district | degC | Distância mínima, máxima e média ao ponto de consigna nos passos demasiado frios (T_heat − T) ou demasiado quentes (T − T_cool); sempre positiva e maior do que a banda, indefinida sem tais passos. O valor do distrito é a média dos edifícios, não um mínimo ou máximo do distrito. |
| `comfort_resilience_resilience_one_minus_thermal_ratio` | building, district | ratio | **Legada**; linha canónica: `thermal_service_audit_outage_discomfort_ratio`. Razão de desconforto global restrita aos passos ocupados durante um corte de energia; indefinida sem passos ocupados em corte avaliados. Igual, por edifício, a `thermal_service_audit_outage_discomfort_ratio`, mas média simples no distrito. |
| `comfort_resilience_resilience_unserved_energy_{outage,annual}_normalized_ratio` | building, district | ratio | **Legada**; linha canónica: `thermal_service_audit_{outage_unserved_service,unserved_service}_ratio`. Energia de serviço não servida (arrefecimento, aquecimento, AQS e carga não deslocável) sobre a energia de serviço esperada, nos passos com corte (`outage`) ou em todos os passos (`annual`). Vale 0, e não indefinido, quando a energia esperada é nula; a variante de corte é 0 em corridas sem cortes. |

<details>
<summary>Todos os 24 nomes</summary>

```text
building_comfort_resilience_discomfort_cold_delta_average_c
building_comfort_resilience_discomfort_cold_delta_max_c
building_comfort_resilience_discomfort_cold_delta_min_c
building_comfort_resilience_discomfort_cold_ratio
building_comfort_resilience_discomfort_hot_delta_average_c
building_comfort_resilience_discomfort_hot_delta_max_c
building_comfort_resilience_discomfort_hot_delta_min_c
building_comfort_resilience_discomfort_hot_ratio
building_comfort_resilience_discomfort_overall_ratio
building_comfort_resilience_resilience_one_minus_thermal_ratio
building_comfort_resilience_resilience_unserved_energy_annual_normalized_ratio
building_comfort_resilience_resilience_unserved_energy_outage_normalized_ratio
district_comfort_resilience_discomfort_cold_delta_average_c
district_comfort_resilience_discomfort_cold_delta_max_c
district_comfort_resilience_discomfort_cold_delta_min_c
district_comfort_resilience_discomfort_cold_ratio
district_comfort_resilience_discomfort_hot_delta_average_c
district_comfort_resilience_discomfort_hot_delta_max_c
district_comfort_resilience_discomfort_hot_delta_min_c
district_comfort_resilience_discomfort_hot_ratio
district_comfort_resilience_discomfort_overall_ratio
district_comfort_resilience_resilience_one_minus_thermal_ratio
district_comfort_resilience_resilience_unserved_energy_annual_normalized_ratio
district_comfort_resilience_resilience_unserved_energy_outage_normalized_ratio
```

</details>

## Auditoria do serviço térmico

Contagens de intervalos, horas, energia e razões que auditam o conforto térmico e a energia de serviço de cada edifício, sempre emitidas; o distrito soma as contagens, e `district_thermal_service_audit_discomfort_ratio` é o KPI de desconforto canónico.

Equações e regras: [Auditoria do serviço térmico](kpis_reference.md#auditoria-do-serviço-térmico).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `thermal_service_audit_{executed,known_occupancy,occupied,evaluated_occupied,excluded_occupied}_intervals_count` | building, district | count | Intervalos executados; intervalos com número de ocupantes conhecido (finito, ≥ 0); intervalos ocupados (número > 0); intervalos ocupados com temperatura, pontos de consigna e banda válidos (avaliados); intervalos ocupados sem eles (excluídos). |
| `thermal_service_audit_{discomfort,cold,hot}_intervals_count` | building, district | count | Intervalos ocupados avaliados demasiado frios (T < T_heat − banda), demasiado quentes (T > T_cool + banda) ou qualquer dos dois. |
| `thermal_service_audit_{outage,unknown_outage,outage_occupied,evaluated_outage_occupied,outage_discomfort}_intervals_count` | building, district | count | Intervalos com corte de energia (sinal > 0) e com sinal de corte desconhecido, qualquer que seja a ocupação; e intervalos de corte ocupados, ocupados e avaliados, e com desconforto. |
| `thermal_service_audit_energy_evaluated_intervals_count` | building, district | count | Intervalos cuja energia esperada e servida é finita e não negativa nos quatro usos finais; os restantes ficam fora dos totais de energia de serviço. |
| `thermal_service_audit_{occupied,evaluated_occupied,discomfort}_hours` | building, district | hours | A contagem de intervalos correspondente multiplicada pela duração do passo em horas. Não passa ao portefólio. |
| `thermal_service_audit_{cold,hot}_degree_hours` | building, district | degC_h | Graus-hora (°C·h) de desconforto: soma nos intervalos demasiado frios de (T_heat − T), ou nos demasiado quentes de (T − T_cool), vezes a duração do passo em horas; medidos a partir do ponto de consigna, não do limite da banda. Não passam ao portefólio. |
| `thermal_service_audit_{expected,served,unserved,outage_expected,outage_unserved}_service_energy_kwh` | building, district | kWh | Energia de serviço esperada, servida e não servida nos intervalos com energia avaliada, e a energia esperada e não servida durante cortes; a não servida é a soma, por uso final, de max(esperada − servida, 0). |
| `thermal_service_audit_discomfort_ratio` | building, district | ratio | KPI de desconforto canónico: intervalos com desconforto sobre intervalos ocupados avaliados, indefinido quando não os há. O valor do distrito é a razão das contagens somadas dos edifícios. |
| `thermal_service_audit_outage_discomfort_ratio` | building, district | ratio | Intervalos de corte com desconforto sobre intervalos de corte ocupados avaliados; indefinido quando não os há. |
| `thermal_service_audit_{thermal,outage_thermal}_coverage_ratio` | building, district | ratio | Intervalos ocupados avaliados sobre intervalos ocupados, no total ou durante cortes; indefinido sem intervalos ocupados. |
| `thermal_service_audit_{occupancy,energy}_coverage_ratio` | building, district | ratio | Intervalos com ocupação conhecida, ou com energia de serviço válida, sobre intervalos executados. |
| `thermal_service_audit_{unserved,outage_unserved}_service_ratio` | building, district | ratio | Energia de serviço não servida sobre esperada, no total ou durante cortes; indefinida, e não 0, quando a energia esperada é nula (por exemplo sem cortes). |

<details>
<summary>Todos os 64 nomes</summary>

```text
building_thermal_service_audit_cold_degree_hours
building_thermal_service_audit_cold_intervals_count
building_thermal_service_audit_discomfort_hours
building_thermal_service_audit_discomfort_intervals_count
building_thermal_service_audit_discomfort_ratio
building_thermal_service_audit_energy_coverage_ratio
building_thermal_service_audit_energy_evaluated_intervals_count
building_thermal_service_audit_evaluated_occupied_hours
building_thermal_service_audit_evaluated_occupied_intervals_count
building_thermal_service_audit_evaluated_outage_occupied_intervals_count
building_thermal_service_audit_excluded_occupied_intervals_count
building_thermal_service_audit_executed_intervals_count
building_thermal_service_audit_expected_service_energy_kwh
building_thermal_service_audit_hot_degree_hours
building_thermal_service_audit_hot_intervals_count
building_thermal_service_audit_known_occupancy_intervals_count
building_thermal_service_audit_occupancy_coverage_ratio
building_thermal_service_audit_occupied_hours
building_thermal_service_audit_occupied_intervals_count
building_thermal_service_audit_outage_discomfort_intervals_count
building_thermal_service_audit_outage_discomfort_ratio
building_thermal_service_audit_outage_expected_service_energy_kwh
building_thermal_service_audit_outage_intervals_count
building_thermal_service_audit_outage_occupied_intervals_count
building_thermal_service_audit_outage_thermal_coverage_ratio
building_thermal_service_audit_outage_unserved_service_energy_kwh
building_thermal_service_audit_outage_unserved_service_ratio
building_thermal_service_audit_served_service_energy_kwh
building_thermal_service_audit_thermal_coverage_ratio
building_thermal_service_audit_unknown_outage_intervals_count
building_thermal_service_audit_unserved_service_energy_kwh
building_thermal_service_audit_unserved_service_ratio
district_thermal_service_audit_cold_degree_hours
district_thermal_service_audit_cold_intervals_count
district_thermal_service_audit_discomfort_hours
district_thermal_service_audit_discomfort_intervals_count
district_thermal_service_audit_discomfort_ratio
district_thermal_service_audit_energy_coverage_ratio
district_thermal_service_audit_energy_evaluated_intervals_count
district_thermal_service_audit_evaluated_occupied_hours
district_thermal_service_audit_evaluated_occupied_intervals_count
district_thermal_service_audit_evaluated_outage_occupied_intervals_count
district_thermal_service_audit_excluded_occupied_intervals_count
district_thermal_service_audit_executed_intervals_count
district_thermal_service_audit_expected_service_energy_kwh
district_thermal_service_audit_hot_degree_hours
district_thermal_service_audit_hot_intervals_count
district_thermal_service_audit_known_occupancy_intervals_count
district_thermal_service_audit_occupancy_coverage_ratio
district_thermal_service_audit_occupied_hours
district_thermal_service_audit_occupied_intervals_count
district_thermal_service_audit_outage_discomfort_intervals_count
district_thermal_service_audit_outage_discomfort_ratio
district_thermal_service_audit_outage_expected_service_energy_kwh
district_thermal_service_audit_outage_intervals_count
district_thermal_service_audit_outage_occupied_intervals_count
district_thermal_service_audit_outage_thermal_coverage_ratio
district_thermal_service_audit_outage_unserved_service_energy_kwh
district_thermal_service_audit_outage_unserved_service_ratio
district_thermal_service_audit_served_service_energy_kwh
district_thermal_service_audit_thermal_coverage_ratio
district_thermal_service_audit_unknown_outage_intervals_count
district_thermal_service_audit_unserved_service_energy_kwh
district_thermal_service_audit_unserved_service_ratio
```

</details>

## Equidade

Benefício relativo de custo de cada edifício face à referência convencional e a sua distribuição no distrito, sempre emitidos; o KPI de Gini canónico é `district_equity_audit_positive_benefit_gini_ratio`.

Equações e regras: [Equidade](kpis_reference.md#equidade).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `equity_benefit_relative_percent` | building | percent | 100 · (B − C) / B, sendo C e B os custos totais do edifício, sem truncagem, com controlo e na condição de referência convencional (não o BAU), liquidados pelo mercado comunitário quando este está ativo; positivo é poupança, indefinido quando B ≤ 0. Só ao nível do edifício. |
| `equity_distribution_gini_benefit_ratio` | district | ratio | **Obsoleta**, alias de `equity_audit_positive_benefit_gini_ratio`. Coeficiente de Gini dos benefícios dos edifícios truncados em 0; indefinido sem benefícios definidos ou com todos os benefícios truncados nulos. Mesmo valor que o canónico `equity_audit_positive_benefit_gini_ratio`. |
| `equity_distribution_top20_benefit_ratio` | district | ratio | **Obsoleta**, alias de `equity_audit_positive_benefit_top20_ratio`. Fração do benefício truncado total detida pelos ceil(20 %) edifícios com maior benefício (pelo menos um); mesma regra de indefinição que o Gini. |
| `equity_distribution_losers_percent` | district | percent | **Obsoleta**, alias de `equity_audit_losers_percent`. Percentagem dos edifícios com benefício definido cujo benefício é negativo (custo acima da referência). |
| `equity_distribution_bpr_asset_poor_over_rich_ratio` | district | ratio | Benefício truncado médio dos edifícios `asset_poor` sobre o dos edifícios `asset_rich`; indefinido salvo se todos os edifícios tiverem `equity_group` com uma destas duas etiquetas, ambos os grupos tiverem benefício definido e a média `asset_rich` for positiva. |

<details>
<summary>Todos os 5 nomes</summary>

```text
building_equity_benefit_relative_percent
district_equity_distribution_bpr_asset_poor_over_rich_ratio
district_equity_distribution_gini_benefit_ratio
district_equity_distribution_losers_percent
district_equity_distribution_top20_benefit_ratio
```

</details>

## Auditoria de equidade

Linhas de equidade do distrito com a respetiva população de membros, sempre emitidas; `district_equity_audit_positive_benefit_gini_ratio` é o KPI de Gini canónico.

Equações e regras: [Auditoria de equidade](kpis_reference.md#auditoria-de-equidade).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `equity_audit_{population_members,eligible_members,excluded_nonpositive_reference,excluded_unknown_cost}_count` | district | count | Edifícios do KPI; edifícios com custos finitos e custo de referência positivo (elegíveis); edifícios excluídos por custo de referência ≤ 0; edifícios excluídos por custo total não finito, que as somas de custo atuais nunca produzem, pelo que esta contagem é sempre 0. |
| `equity_audit_coverage_ratio` | district | ratio | Edifícios elegíveis sobre edifícios do KPI; indefinido sem edifícios. |
| `equity_audit_losers_percent` | district | percent | Percentagem dos edifícios elegíveis com benefício negativo; mesmo valor que `equity_distribution_losers_percent`. |
| `equity_audit_positive_benefit_gini_ratio` | district | ratio | KPI de Gini canónico: coeficiente de Gini dos benefícios dos edifícios elegíveis truncados em 0; indefinido quando a soma dos benefícios truncados é 0. Reportar com a percentagem de perdedores e a razão de cobertura. |
| `equity_audit_positive_benefit_top20_ratio` | district | ratio | Fração do benefício truncado total detida pelos ceil(20 %) edifícios elegíveis com maior benefício (pelo menos um); mesmo valor que `equity_distribution_top20_benefit_ratio`. |

<details>
<summary>Todos os 8 nomes</summary>

```text
district_equity_audit_coverage_ratio
district_equity_audit_eligible_members_count
district_equity_audit_excluded_nonpositive_reference_count
district_equity_audit_excluded_unknown_cost_count
district_equity_audit_losers_percent
district_equity_audit_population_members_count
district_equity_audit_positive_benefit_gini_ratio
district_equity_audit_positive_benefit_top20_ratio
```

</details>

## Demand response

Resposta aos pedidos de demand response do dataset, medida face a uma baseline pré-evento, e a respetiva liquidação; as linhas aparecem quando `demand_response.enabled` é verdadeiro.

Equações e regras: [Demand response](kpis_reference.md#demand-response).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `demand_response_events_count` | building, district | count | Pedidos distintos com pelo menos um passo liquidado; num edifício, os pedidos ativos enquanto era membro. |
| `demand_response_active_time_step_count` | building, district | count | Passos executados com um pedido ativo, incluindo passos com baseline inválida; num edifício, os passos em que era membro. |
| `demand_response_invalid_baseline_time_step_count` | building, district | count | Passos ativos cuja baseline pré-evento era inválida, excluídos da entrega e dos valores monetários. |
| `demand_response_requested_total_kwh` | building, district | kWh | Energia pedida, `potência alvo · horas do passo`, em todos os passos ativos; repartida igualmente pelos membros ativos ao nível do edifício. |
| `demand_response_valid_requested_total_kwh` | district | kWh | Energia pedida nos passos ativos com baseline válida: o denominador da taxa de cumprimento. |
| `demand_response_delivered_total_kwh` | building, district | kWh | Desvio assinado face à baseline na direção pedida, sem limite nem tolerância, nos passos válidos; ao nível do edifício, o desvio do próprio membro. |
| `demand_response_credited_total_kwh` | district | kWh | Entrega creditada face aos pedidos: entrega positiva limitada ao alvo, sem a tolerância; o numerador da taxa de cumprimento. |
| `demand_response_shortfall_total_kwh` | building, district | kWh | Energia `max(alvo − entrega − tolerância, 0)` nos passos válidos; ao nível do edifício, o défice do distrito repartido pelo peso de penalização. |
| `demand_response_compliance_ratio` | building, district | ratio | Energia creditada sobre a energia pedida válida, limitada a [0, 1]; indefinida sem energia pedida válida. Ao nível do edifício, a parte creditada do membro sobre a sua parte igual do pedido. |
| `demand_response_{revenue,penalty,net_revenue}_total_eur` | building, district | EUR | Receita (energia creditada · preço de ativação), penalização (défice · preço de penalização) e a sua diferença. |
| `demand_response_uncapped_contribution_total_kwh` | building | kWh | Diagnóstico: o desvio positivo do próprio membro na direção pedida, sem tolerância nem limite; não soma para nenhum valor do distrito. |

<details>
<summary>Todos os 23 nomes</summary>

```text
building_demand_response_active_time_step_count
building_demand_response_compliance_ratio
building_demand_response_delivered_total_kwh
building_demand_response_events_count
building_demand_response_invalid_baseline_time_step_count
building_demand_response_net_revenue_total_eur
building_demand_response_penalty_total_eur
building_demand_response_requested_total_kwh
building_demand_response_revenue_total_eur
building_demand_response_shortfall_total_kwh
building_demand_response_uncapped_contribution_total_kwh
district_demand_response_active_time_step_count
district_demand_response_compliance_ratio
district_demand_response_credited_total_kwh
district_demand_response_delivered_total_kwh
district_demand_response_events_count
district_demand_response_invalid_baseline_time_step_count
district_demand_response_net_revenue_total_eur
district_demand_response_penalty_total_eur
district_demand_response_requested_total_kwh
district_demand_response_revenue_total_eur
district_demand_response_shortfall_total_kwh
district_demand_response_valid_requested_total_kwh
```

</details>

## Auditoria de demand response

Totais, cobertura e exclusões de demand response do distrito, separados pelo propósito declarado do pedido (`all`, `service`, `stress`, `unspecified`); as linhas aparecem quando o demand response está ativo, para os quatro propósitos.

Equações e regras: [Auditoria de demand response](kpis_reference.md#auditoria-de-demand-response).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `demand_response_audit_{all,service,stress,unspecified}_{requested,valid_requested,delivered,credited,shortfall}_kwh` | district | kWh | Energia pedida, pedida válida, entregue, creditada e em défice nos passos liquidados do propósito, definidas como no demand response. |
| `demand_response_audit_{all,service,stress,unspecified}_{revenue,penalty,net_revenue}_eur` | district | EUR | Receita, penalização e receita líquida dos passos liquidados do propósito. |
| `demand_response_audit_{all,service,stress,unspecified}_events_count` | district | count | Pedidos distintos do propósito com pelo menos um passo liquidado. |
| `demand_response_audit_{all,service,stress,unspecified}_{active,valid}_intervals_count` | district | count | Passos liquidados do propósito (active) e os que têm baseline válida (valid). |
| `demand_response_audit_{all,service,stress,unspecified}_excluded_{insufficient_history,nonfinite_history,no_members,topology_changed}_intervals_count` | district | count | Passos do propósito com baseline inválida, por motivo; as quatro contagens somam os passos ativos menos os válidos. |
| `demand_response_audit_{all,service,stress,unspecified}_baseline_coverage_ratio` | district | ratio | Passos válidos sobre passos ativos; indefinida quando o propósito não tem passos liquidados. |
| `demand_response_audit_{all,service,stress,unspecified}_requested_energy_coverage_ratio` | district | ratio | Energia pedida válida sobre energia pedida; indefinida quando não foi pedida energia. |
| `demand_response_audit_{all,service,stress,unspecified}_compliance_ratio` | district | ratio | Energia creditada sobre energia pedida válida, limitada a [0, 1]; indefinida quando a energia pedida válida é 0. |

<details>
<summary>Todos os 72 nomes</summary>

```text
district_demand_response_audit_all_active_intervals_count
district_demand_response_audit_all_baseline_coverage_ratio
district_demand_response_audit_all_compliance_ratio
district_demand_response_audit_all_credited_kwh
district_demand_response_audit_all_delivered_kwh
district_demand_response_audit_all_events_count
district_demand_response_audit_all_excluded_insufficient_history_intervals_count
district_demand_response_audit_all_excluded_no_members_intervals_count
district_demand_response_audit_all_excluded_nonfinite_history_intervals_count
district_demand_response_audit_all_excluded_topology_changed_intervals_count
district_demand_response_audit_all_net_revenue_eur
district_demand_response_audit_all_penalty_eur
district_demand_response_audit_all_requested_energy_coverage_ratio
district_demand_response_audit_all_requested_kwh
district_demand_response_audit_all_revenue_eur
district_demand_response_audit_all_shortfall_kwh
district_demand_response_audit_all_valid_intervals_count
district_demand_response_audit_all_valid_requested_kwh
district_demand_response_audit_service_active_intervals_count
district_demand_response_audit_service_baseline_coverage_ratio
district_demand_response_audit_service_compliance_ratio
district_demand_response_audit_service_credited_kwh
district_demand_response_audit_service_delivered_kwh
district_demand_response_audit_service_events_count
district_demand_response_audit_service_excluded_insufficient_history_intervals_count
district_demand_response_audit_service_excluded_no_members_intervals_count
district_demand_response_audit_service_excluded_nonfinite_history_intervals_count
district_demand_response_audit_service_excluded_topology_changed_intervals_count
district_demand_response_audit_service_net_revenue_eur
district_demand_response_audit_service_penalty_eur
district_demand_response_audit_service_requested_energy_coverage_ratio
district_demand_response_audit_service_requested_kwh
district_demand_response_audit_service_revenue_eur
district_demand_response_audit_service_shortfall_kwh
district_demand_response_audit_service_valid_intervals_count
district_demand_response_audit_service_valid_requested_kwh
district_demand_response_audit_stress_active_intervals_count
district_demand_response_audit_stress_baseline_coverage_ratio
district_demand_response_audit_stress_compliance_ratio
district_demand_response_audit_stress_credited_kwh
district_demand_response_audit_stress_delivered_kwh
district_demand_response_audit_stress_events_count
district_demand_response_audit_stress_excluded_insufficient_history_intervals_count
district_demand_response_audit_stress_excluded_no_members_intervals_count
district_demand_response_audit_stress_excluded_nonfinite_history_intervals_count
district_demand_response_audit_stress_excluded_topology_changed_intervals_count
district_demand_response_audit_stress_net_revenue_eur
district_demand_response_audit_stress_penalty_eur
district_demand_response_audit_stress_requested_energy_coverage_ratio
district_demand_response_audit_stress_requested_kwh
district_demand_response_audit_stress_revenue_eur
district_demand_response_audit_stress_shortfall_kwh
district_demand_response_audit_stress_valid_intervals_count
district_demand_response_audit_stress_valid_requested_kwh
district_demand_response_audit_unspecified_active_intervals_count
district_demand_response_audit_unspecified_baseline_coverage_ratio
district_demand_response_audit_unspecified_compliance_ratio
district_demand_response_audit_unspecified_credited_kwh
district_demand_response_audit_unspecified_delivered_kwh
district_demand_response_audit_unspecified_events_count
district_demand_response_audit_unspecified_excluded_insufficient_history_intervals_count
district_demand_response_audit_unspecified_excluded_no_members_intervals_count
district_demand_response_audit_unspecified_excluded_nonfinite_history_intervals_count
district_demand_response_audit_unspecified_excluded_topology_changed_intervals_count
district_demand_response_audit_unspecified_net_revenue_eur
district_demand_response_audit_unspecified_penalty_eur
district_demand_response_audit_unspecified_requested_energy_coverage_ratio
district_demand_response_audit_unspecified_requested_kwh
district_demand_response_audit_unspecified_revenue_eur
district_demand_response_audit_unspecified_shortfall_kwh
district_demand_response_audit_unspecified_valid_intervals_count
district_demand_response_audit_unspecified_valid_requested_kwh
```

</details>

## Robustez

Contadores das perturbações de observações, previsões, ações e ativos aplicadas pelos eventos de robustez do dataset; as linhas aparecem quando `robustness.enabled` é verdadeiro.

Equações e regras: [Robustez](kpis_reference.md#robustez).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `robustness_events_count` | building, district | count | Eventos de robustez distintos com pelo menos uma aplicação registada (num edifício, atribuída a ele). |
| `robustness_active_time_step_count` | building, district | count | Passos com pelo menos uma aplicação registada, incluindo a observação terminal. |
| `robustness_{observation,forecast,action}_corruption_count` | building, district | count | Corrupções distintas (evento, alvo) de observações, previsões ou ações, somadas pelos passos. |
| `robustness_asset_unavailable_time_step_count` | building, district | count | Passos de indisponibilidade de ativos: cada par (evento, ativo) conta uma vez por passo. |
| `robustness_missing_observation_count` | building, district | count | Aplicações a observações ou previsões no modo `missing`, mais as observações ocultadas por eventos de ativos. |
| `robustness_action_dropout_count` | building, district | count | Aplicações a ações no modo `dropout`, mais as ações bloqueadas por eventos de ativos. |

<details>
<summary>Todos os 16 nomes</summary>

```text
building_robustness_action_corruption_count
building_robustness_action_dropout_count
building_robustness_active_time_step_count
building_robustness_asset_unavailable_time_step_count
building_robustness_events_count
building_robustness_forecast_corruption_count
building_robustness_missing_observation_count
building_robustness_observation_corruption_count
district_robustness_action_corruption_count
district_robustness_action_dropout_count
district_robustness_active_time_step_count
district_robustness_asset_unavailable_time_step_count
district_robustness_events_count
district_robustness_forecast_corruption_count
district_robustness_missing_observation_count
district_robustness_observation_corruption_count
```

</details>

## Proveniência da energia

Segue cada kWh de eletricidade desde a origem (produção FV própria ou de vizinhos, importação da rede, ou energia armazenada de origem desconhecida) até ao destino (consumo, armazenamento, mobilidade, exportação, perdas e outros), com o carbono da rede que transporta; as linhas existem sempre que o ambiente mantém o registo de proveniência (`energy_provenance=True`, valor por omissão).

Equações e regras: [Proveniência da energia](kpis_reference.md#proveniência-da-energia).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `energy_provenance_pv_generated{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia FV produzida pelo membro, incluindo a parte depois cortada; `_business_as_usual` e `_delta_to_business_as_usual` como nas regras comuns. |
| `energy_provenance_{pv,grid,unknown}_{load,mobility,grid_export,loss,asset_exit,external_reset,curtailment,stored}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia de origem FV, rede (incluindo importação de carbono desconhecido) ou desconhecida que chegou ao destino indicado neste membro, contada pelo membro que a recebe; `stored` é a energia ainda armazenada no membro no momento da avaliação, e só a energia FV pode ser cortada, pelo que as linhas de corte da rede e de origem desconhecida valem sempre 0. Variantes BAU como nas regras comuns. |
| `energy_provenance_pv_load_{direct,after_storage}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Divisão da energia FV que chega ao consumo do membro: `direct` não passou por armazenamento nesse intervalo, e `after_storage` é `max(pv_load - pv_load_direct, 0)`. Variantes BAU como nas regras comuns. |
| `energy_provenance_unknown_input{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia que entrou no registo com origem desconhecida: o conteúdo inicial de cada armazenamento quando o registo o encontra pela primeira vez (incluindo toda a energia de cada VE no momento da ligação) e cada estado de carga imposto externamente. Variantes BAU como nas regras comuns. |
| `energy_provenance_{,pv_,grid_}{local_import,local_export}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia recebida de (`local_import`) ou enviada para (`local_export`) outros membros no mesmo intervalo, no total e por origem; são transferências internas, já contadas nos destinos do membro que recebe. Variantes BAU como nas regras comuns. |
| `energy_provenance_external_import{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Importação da rede do membro após a partilha local, `max(net, 0) - local_import` somado sobre os intervalos, incluindo intervalos com intensidade carbónica desconhecida. Variantes BAU como nas regras comuns. |
| `energy_provenance_external_purchase_emissions{,_business_as_usual,_delta_to_business_as_usual}_kgco2` | building, district | kgCO2 | Emissões da importação da rede do membro após a partilha local, à intensidade carbónica do membro; intervalos com intensidade não finita não somam nada, e as exportações não dão crédito. Variantes BAU como nas regras comuns. |
| `energy_provenance_external_purchase_unknown_carbon{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Parte de `external_import` importada em intervalos cuja intensidade carbónica não é finita, e que por isso falta nas emissões. Variantes BAU como nas regras comuns. |
| `energy_provenance_carbon_{load,mobility,grid_export,loss,asset_exit,external_reset,curtailment,stored}{,_business_as_usual,_delta_to_business_as_usual}_kgco2` | building, district | kgCO2 | Carbono da rede transportado pela energia que chegou ao destino indicado neste membro; só a energia da rede transporta carbono, pelo que `carbon_curtailment` vale sempre 0. Variantes BAU como nas regras comuns. |
| `energy_provenance_carbon_unknown_{load,mobility,grid_export,loss,asset_exit,external_reset,curtailment,stored}{,_business_as_usual,_delta_to_business_as_usual}_kwh` | building, district | kWh | Energia (não carbono) no destino indicado cujo carbono é desconhecido: energia de origem desconhecida mais importação da rede com intensidade não finita; mostra quanta energia a linha `carbon_*_kgco2` correspondente deixa por contar. Variantes BAU como nas regras comuns. |
| `energy_provenance_{pv,grid,unknown}_balance_residual{,_business_as_usual,_delta_to_business_as_usual}_kwh` | district | kWh | Verificação de fecho por origem: entrada (`pv_generated`, `external_import` ou `unknown_input`) menos a soma dos seus oito destinos; esperado próximo de 0. Só no distrito, porque os membros trocam energia. Variantes BAU como nas regras comuns. |
| `energy_provenance_carbon_balance_residual{,_business_as_usual,_delta_to_business_as_usual}_kgco2` | district | kgCO2 | Verificação de fecho do carbono: `external_purchase_emissions` menos a soma dos oito destinos `carbon_*`; esperado próximo de 0. Variantes BAU como nas regras comuns. |
| `energy_provenance_pv_useful_{building,with_mobility}{,_business_as_usual,_delta_to_business_as_usual}_ratio` | district | ratio | Fração da produção FV do distrito que chegou a um consumo dos edifícios (`building`), ou a um consumo ou a um VE que parte (`with_mobility`); indefinida quando a produção FV do distrito é nula. Variantes BAU como nas regras comuns. |
| `energy_provenance_{bus,storage}_max_residual{,_business_as_usual,_delta_to_business_as_usual}_kwh` | district | kWh | Diagnósticos, não medidas de desempenho: o maior desequilíbrio de barramento num intervalo (`bus`) ou a maior diferença entre a energia armazenada no registo e a física (`storage`), sobre todos os membros e intervalos; esperado próximo de 0. Variantes BAU como nas regras comuns. |

<details>
<summary>Todos os 342 nomes</summary>

```text
building_energy_provenance_carbon_asset_exit_business_as_usual_kgco2
building_energy_provenance_carbon_asset_exit_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_asset_exit_kgco2
building_energy_provenance_carbon_curtailment_business_as_usual_kgco2
building_energy_provenance_carbon_curtailment_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_curtailment_kgco2
building_energy_provenance_carbon_external_reset_business_as_usual_kgco2
building_energy_provenance_carbon_external_reset_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_external_reset_kgco2
building_energy_provenance_carbon_grid_export_business_as_usual_kgco2
building_energy_provenance_carbon_grid_export_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_grid_export_kgco2
building_energy_provenance_carbon_load_business_as_usual_kgco2
building_energy_provenance_carbon_load_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_load_kgco2
building_energy_provenance_carbon_loss_business_as_usual_kgco2
building_energy_provenance_carbon_loss_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_loss_kgco2
building_energy_provenance_carbon_mobility_business_as_usual_kgco2
building_energy_provenance_carbon_mobility_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_mobility_kgco2
building_energy_provenance_carbon_stored_business_as_usual_kgco2
building_energy_provenance_carbon_stored_delta_to_business_as_usual_kgco2
building_energy_provenance_carbon_stored_kgco2
building_energy_provenance_carbon_unknown_asset_exit_business_as_usual_kwh
building_energy_provenance_carbon_unknown_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_asset_exit_kwh
building_energy_provenance_carbon_unknown_curtailment_business_as_usual_kwh
building_energy_provenance_carbon_unknown_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_curtailment_kwh
building_energy_provenance_carbon_unknown_external_reset_business_as_usual_kwh
building_energy_provenance_carbon_unknown_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_external_reset_kwh
building_energy_provenance_carbon_unknown_grid_export_business_as_usual_kwh
building_energy_provenance_carbon_unknown_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_grid_export_kwh
building_energy_provenance_carbon_unknown_load_business_as_usual_kwh
building_energy_provenance_carbon_unknown_load_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_load_kwh
building_energy_provenance_carbon_unknown_loss_business_as_usual_kwh
building_energy_provenance_carbon_unknown_loss_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_loss_kwh
building_energy_provenance_carbon_unknown_mobility_business_as_usual_kwh
building_energy_provenance_carbon_unknown_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_mobility_kwh
building_energy_provenance_carbon_unknown_stored_business_as_usual_kwh
building_energy_provenance_carbon_unknown_stored_delta_to_business_as_usual_kwh
building_energy_provenance_carbon_unknown_stored_kwh
building_energy_provenance_external_import_business_as_usual_kwh
building_energy_provenance_external_import_delta_to_business_as_usual_kwh
building_energy_provenance_external_import_kwh
building_energy_provenance_external_purchase_emissions_business_as_usual_kgco2
building_energy_provenance_external_purchase_emissions_delta_to_business_as_usual_kgco2
building_energy_provenance_external_purchase_emissions_kgco2
building_energy_provenance_external_purchase_unknown_carbon_business_as_usual_kwh
building_energy_provenance_external_purchase_unknown_carbon_delta_to_business_as_usual_kwh
building_energy_provenance_external_purchase_unknown_carbon_kwh
building_energy_provenance_grid_asset_exit_business_as_usual_kwh
building_energy_provenance_grid_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_grid_asset_exit_kwh
building_energy_provenance_grid_curtailment_business_as_usual_kwh
building_energy_provenance_grid_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_grid_curtailment_kwh
building_energy_provenance_grid_external_reset_business_as_usual_kwh
building_energy_provenance_grid_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_grid_external_reset_kwh
building_energy_provenance_grid_grid_export_business_as_usual_kwh
building_energy_provenance_grid_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_grid_grid_export_kwh
building_energy_provenance_grid_load_business_as_usual_kwh
building_energy_provenance_grid_load_delta_to_business_as_usual_kwh
building_energy_provenance_grid_load_kwh
building_energy_provenance_grid_local_export_business_as_usual_kwh
building_energy_provenance_grid_local_export_delta_to_business_as_usual_kwh
building_energy_provenance_grid_local_export_kwh
building_energy_provenance_grid_local_import_business_as_usual_kwh
building_energy_provenance_grid_local_import_delta_to_business_as_usual_kwh
building_energy_provenance_grid_local_import_kwh
building_energy_provenance_grid_loss_business_as_usual_kwh
building_energy_provenance_grid_loss_delta_to_business_as_usual_kwh
building_energy_provenance_grid_loss_kwh
building_energy_provenance_grid_mobility_business_as_usual_kwh
building_energy_provenance_grid_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_grid_mobility_kwh
building_energy_provenance_grid_stored_business_as_usual_kwh
building_energy_provenance_grid_stored_delta_to_business_as_usual_kwh
building_energy_provenance_grid_stored_kwh
building_energy_provenance_local_export_business_as_usual_kwh
building_energy_provenance_local_export_delta_to_business_as_usual_kwh
building_energy_provenance_local_export_kwh
building_energy_provenance_local_import_business_as_usual_kwh
building_energy_provenance_local_import_delta_to_business_as_usual_kwh
building_energy_provenance_local_import_kwh
building_energy_provenance_pv_asset_exit_business_as_usual_kwh
building_energy_provenance_pv_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_pv_asset_exit_kwh
building_energy_provenance_pv_curtailment_business_as_usual_kwh
building_energy_provenance_pv_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_pv_curtailment_kwh
building_energy_provenance_pv_external_reset_business_as_usual_kwh
building_energy_provenance_pv_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_pv_external_reset_kwh
building_energy_provenance_pv_generated_business_as_usual_kwh
building_energy_provenance_pv_generated_delta_to_business_as_usual_kwh
building_energy_provenance_pv_generated_kwh
building_energy_provenance_pv_grid_export_business_as_usual_kwh
building_energy_provenance_pv_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_pv_grid_export_kwh
building_energy_provenance_pv_load_after_storage_business_as_usual_kwh
building_energy_provenance_pv_load_after_storage_delta_to_business_as_usual_kwh
building_energy_provenance_pv_load_after_storage_kwh
building_energy_provenance_pv_load_business_as_usual_kwh
building_energy_provenance_pv_load_delta_to_business_as_usual_kwh
building_energy_provenance_pv_load_direct_business_as_usual_kwh
building_energy_provenance_pv_load_direct_delta_to_business_as_usual_kwh
building_energy_provenance_pv_load_direct_kwh
building_energy_provenance_pv_load_kwh
building_energy_provenance_pv_local_export_business_as_usual_kwh
building_energy_provenance_pv_local_export_delta_to_business_as_usual_kwh
building_energy_provenance_pv_local_export_kwh
building_energy_provenance_pv_local_import_business_as_usual_kwh
building_energy_provenance_pv_local_import_delta_to_business_as_usual_kwh
building_energy_provenance_pv_local_import_kwh
building_energy_provenance_pv_loss_business_as_usual_kwh
building_energy_provenance_pv_loss_delta_to_business_as_usual_kwh
building_energy_provenance_pv_loss_kwh
building_energy_provenance_pv_mobility_business_as_usual_kwh
building_energy_provenance_pv_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_pv_mobility_kwh
building_energy_provenance_pv_stored_business_as_usual_kwh
building_energy_provenance_pv_stored_delta_to_business_as_usual_kwh
building_energy_provenance_pv_stored_kwh
building_energy_provenance_unknown_asset_exit_business_as_usual_kwh
building_energy_provenance_unknown_asset_exit_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_asset_exit_kwh
building_energy_provenance_unknown_curtailment_business_as_usual_kwh
building_energy_provenance_unknown_curtailment_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_curtailment_kwh
building_energy_provenance_unknown_external_reset_business_as_usual_kwh
building_energy_provenance_unknown_external_reset_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_external_reset_kwh
building_energy_provenance_unknown_grid_export_business_as_usual_kwh
building_energy_provenance_unknown_grid_export_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_grid_export_kwh
building_energy_provenance_unknown_input_business_as_usual_kwh
building_energy_provenance_unknown_input_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_input_kwh
building_energy_provenance_unknown_load_business_as_usual_kwh
building_energy_provenance_unknown_load_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_load_kwh
building_energy_provenance_unknown_loss_business_as_usual_kwh
building_energy_provenance_unknown_loss_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_loss_kwh
building_energy_provenance_unknown_mobility_business_as_usual_kwh
building_energy_provenance_unknown_mobility_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_mobility_kwh
building_energy_provenance_unknown_stored_business_as_usual_kwh
building_energy_provenance_unknown_stored_delta_to_business_as_usual_kwh
building_energy_provenance_unknown_stored_kwh
district_energy_provenance_bus_max_residual_business_as_usual_kwh
district_energy_provenance_bus_max_residual_delta_to_business_as_usual_kwh
district_energy_provenance_bus_max_residual_kwh
district_energy_provenance_carbon_asset_exit_business_as_usual_kgco2
district_energy_provenance_carbon_asset_exit_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_asset_exit_kgco2
district_energy_provenance_carbon_balance_residual_business_as_usual_kgco2
district_energy_provenance_carbon_balance_residual_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_balance_residual_kgco2
district_energy_provenance_carbon_curtailment_business_as_usual_kgco2
district_energy_provenance_carbon_curtailment_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_curtailment_kgco2
district_energy_provenance_carbon_external_reset_business_as_usual_kgco2
district_energy_provenance_carbon_external_reset_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_external_reset_kgco2
district_energy_provenance_carbon_grid_export_business_as_usual_kgco2
district_energy_provenance_carbon_grid_export_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_grid_export_kgco2
district_energy_provenance_carbon_load_business_as_usual_kgco2
district_energy_provenance_carbon_load_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_load_kgco2
district_energy_provenance_carbon_loss_business_as_usual_kgco2
district_energy_provenance_carbon_loss_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_loss_kgco2
district_energy_provenance_carbon_mobility_business_as_usual_kgco2
district_energy_provenance_carbon_mobility_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_mobility_kgco2
district_energy_provenance_carbon_stored_business_as_usual_kgco2
district_energy_provenance_carbon_stored_delta_to_business_as_usual_kgco2
district_energy_provenance_carbon_stored_kgco2
district_energy_provenance_carbon_unknown_asset_exit_business_as_usual_kwh
district_energy_provenance_carbon_unknown_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_asset_exit_kwh
district_energy_provenance_carbon_unknown_curtailment_business_as_usual_kwh
district_energy_provenance_carbon_unknown_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_curtailment_kwh
district_energy_provenance_carbon_unknown_external_reset_business_as_usual_kwh
district_energy_provenance_carbon_unknown_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_external_reset_kwh
district_energy_provenance_carbon_unknown_grid_export_business_as_usual_kwh
district_energy_provenance_carbon_unknown_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_grid_export_kwh
district_energy_provenance_carbon_unknown_load_business_as_usual_kwh
district_energy_provenance_carbon_unknown_load_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_load_kwh
district_energy_provenance_carbon_unknown_loss_business_as_usual_kwh
district_energy_provenance_carbon_unknown_loss_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_loss_kwh
district_energy_provenance_carbon_unknown_mobility_business_as_usual_kwh
district_energy_provenance_carbon_unknown_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_mobility_kwh
district_energy_provenance_carbon_unknown_stored_business_as_usual_kwh
district_energy_provenance_carbon_unknown_stored_delta_to_business_as_usual_kwh
district_energy_provenance_carbon_unknown_stored_kwh
district_energy_provenance_external_import_business_as_usual_kwh
district_energy_provenance_external_import_delta_to_business_as_usual_kwh
district_energy_provenance_external_import_kwh
district_energy_provenance_external_purchase_emissions_business_as_usual_kgco2
district_energy_provenance_external_purchase_emissions_delta_to_business_as_usual_kgco2
district_energy_provenance_external_purchase_emissions_kgco2
district_energy_provenance_external_purchase_unknown_carbon_business_as_usual_kwh
district_energy_provenance_external_purchase_unknown_carbon_delta_to_business_as_usual_kwh
district_energy_provenance_external_purchase_unknown_carbon_kwh
district_energy_provenance_grid_asset_exit_business_as_usual_kwh
district_energy_provenance_grid_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_grid_asset_exit_kwh
district_energy_provenance_grid_balance_residual_business_as_usual_kwh
district_energy_provenance_grid_balance_residual_delta_to_business_as_usual_kwh
district_energy_provenance_grid_balance_residual_kwh
district_energy_provenance_grid_curtailment_business_as_usual_kwh
district_energy_provenance_grid_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_grid_curtailment_kwh
district_energy_provenance_grid_external_reset_business_as_usual_kwh
district_energy_provenance_grid_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_grid_external_reset_kwh
district_energy_provenance_grid_grid_export_business_as_usual_kwh
district_energy_provenance_grid_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_grid_grid_export_kwh
district_energy_provenance_grid_load_business_as_usual_kwh
district_energy_provenance_grid_load_delta_to_business_as_usual_kwh
district_energy_provenance_grid_load_kwh
district_energy_provenance_grid_local_export_business_as_usual_kwh
district_energy_provenance_grid_local_export_delta_to_business_as_usual_kwh
district_energy_provenance_grid_local_export_kwh
district_energy_provenance_grid_local_import_business_as_usual_kwh
district_energy_provenance_grid_local_import_delta_to_business_as_usual_kwh
district_energy_provenance_grid_local_import_kwh
district_energy_provenance_grid_loss_business_as_usual_kwh
district_energy_provenance_grid_loss_delta_to_business_as_usual_kwh
district_energy_provenance_grid_loss_kwh
district_energy_provenance_grid_mobility_business_as_usual_kwh
district_energy_provenance_grid_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_grid_mobility_kwh
district_energy_provenance_grid_stored_business_as_usual_kwh
district_energy_provenance_grid_stored_delta_to_business_as_usual_kwh
district_energy_provenance_grid_stored_kwh
district_energy_provenance_local_export_business_as_usual_kwh
district_energy_provenance_local_export_delta_to_business_as_usual_kwh
district_energy_provenance_local_export_kwh
district_energy_provenance_local_import_business_as_usual_kwh
district_energy_provenance_local_import_delta_to_business_as_usual_kwh
district_energy_provenance_local_import_kwh
district_energy_provenance_pv_asset_exit_business_as_usual_kwh
district_energy_provenance_pv_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_pv_asset_exit_kwh
district_energy_provenance_pv_balance_residual_business_as_usual_kwh
district_energy_provenance_pv_balance_residual_delta_to_business_as_usual_kwh
district_energy_provenance_pv_balance_residual_kwh
district_energy_provenance_pv_curtailment_business_as_usual_kwh
district_energy_provenance_pv_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_pv_curtailment_kwh
district_energy_provenance_pv_external_reset_business_as_usual_kwh
district_energy_provenance_pv_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_pv_external_reset_kwh
district_energy_provenance_pv_generated_business_as_usual_kwh
district_energy_provenance_pv_generated_delta_to_business_as_usual_kwh
district_energy_provenance_pv_generated_kwh
district_energy_provenance_pv_grid_export_business_as_usual_kwh
district_energy_provenance_pv_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_pv_grid_export_kwh
district_energy_provenance_pv_load_after_storage_business_as_usual_kwh
district_energy_provenance_pv_load_after_storage_delta_to_business_as_usual_kwh
district_energy_provenance_pv_load_after_storage_kwh
district_energy_provenance_pv_load_business_as_usual_kwh
district_energy_provenance_pv_load_delta_to_business_as_usual_kwh
district_energy_provenance_pv_load_direct_business_as_usual_kwh
district_energy_provenance_pv_load_direct_delta_to_business_as_usual_kwh
district_energy_provenance_pv_load_direct_kwh
district_energy_provenance_pv_load_kwh
district_energy_provenance_pv_local_export_business_as_usual_kwh
district_energy_provenance_pv_local_export_delta_to_business_as_usual_kwh
district_energy_provenance_pv_local_export_kwh
district_energy_provenance_pv_local_import_business_as_usual_kwh
district_energy_provenance_pv_local_import_delta_to_business_as_usual_kwh
district_energy_provenance_pv_local_import_kwh
district_energy_provenance_pv_loss_business_as_usual_kwh
district_energy_provenance_pv_loss_delta_to_business_as_usual_kwh
district_energy_provenance_pv_loss_kwh
district_energy_provenance_pv_mobility_business_as_usual_kwh
district_energy_provenance_pv_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_pv_mobility_kwh
district_energy_provenance_pv_stored_business_as_usual_kwh
district_energy_provenance_pv_stored_delta_to_business_as_usual_kwh
district_energy_provenance_pv_stored_kwh
district_energy_provenance_pv_useful_building_business_as_usual_ratio
district_energy_provenance_pv_useful_building_delta_to_business_as_usual_ratio
district_energy_provenance_pv_useful_building_ratio
district_energy_provenance_pv_useful_with_mobility_business_as_usual_ratio
district_energy_provenance_pv_useful_with_mobility_delta_to_business_as_usual_ratio
district_energy_provenance_pv_useful_with_mobility_ratio
district_energy_provenance_storage_max_residual_business_as_usual_kwh
district_energy_provenance_storage_max_residual_delta_to_business_as_usual_kwh
district_energy_provenance_storage_max_residual_kwh
district_energy_provenance_unknown_asset_exit_business_as_usual_kwh
district_energy_provenance_unknown_asset_exit_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_asset_exit_kwh
district_energy_provenance_unknown_balance_residual_business_as_usual_kwh
district_energy_provenance_unknown_balance_residual_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_balance_residual_kwh
district_energy_provenance_unknown_curtailment_business_as_usual_kwh
district_energy_provenance_unknown_curtailment_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_curtailment_kwh
district_energy_provenance_unknown_external_reset_business_as_usual_kwh
district_energy_provenance_unknown_external_reset_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_external_reset_kwh
district_energy_provenance_unknown_grid_export_business_as_usual_kwh
district_energy_provenance_unknown_grid_export_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_grid_export_kwh
district_energy_provenance_unknown_input_business_as_usual_kwh
district_energy_provenance_unknown_input_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_input_kwh
district_energy_provenance_unknown_load_business_as_usual_kwh
district_energy_provenance_unknown_load_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_load_kwh
district_energy_provenance_unknown_loss_business_as_usual_kwh
district_energy_provenance_unknown_loss_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_loss_kwh
district_energy_provenance_unknown_mobility_business_as_usual_kwh
district_energy_provenance_unknown_mobility_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_mobility_kwh
district_energy_provenance_unknown_stored_business_as_usual_kwh
district_energy_provenance_unknown_stored_delta_to_business_as_usual_kwh
district_energy_provenance_unknown_stored_kwh
```

</details>

## Topologia dinâmica

Registo do ciclo de vida dos membros de uma topologia dinâmica; a linha só aparece com `topology_mode='dynamic'`.

Equações e regras: [Topologia dinâmica](kpis_reference.md#topologia-dinâmica).

| Nomes | Níveis | Unidade | Significado |
|---|---|---|---|
| `topology_lifecycle_presence` | building | none | Marcador, sempre NaN: uma linha por membro do ciclo de vida sem outra linha de edifício (nunca ativo no episódio), para que as suas colunas de ciclo de vida apareçam. Não tem prefixo de nível porque é acrescentada depois da etapa de nomeação dos KPI. |

<details>
<summary>Todos os 1 nomes</summary>

```text
topology_lifecycle_presence
```

</details>
