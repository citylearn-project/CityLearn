# Como ler o scorecard

Versão em inglês: [../scorecard.md](../scorecard.md).

Um scorecard põe lado a lado um pequeno conjunto de indicadores de energia,
custo, serviço e limites elétricos. É uma vista de `evaluate_v2()`, não uma nova
recompensa nem uma pontuação ponderada única. Guarde o export completo dos KPIs,
para que cada resultado possa ser rastreado.

## Comece por estas perguntas

| Pergunta | Métrica | Como ler |
|---|---|---|
| Quanto custou a operação? | Custo total, custo BAU e diferença | Um custo menor é favorável quando se aplicam os mesmos serviços e regras tarifárias. Uma diferença controlo menos BAU negativa é uma poupança. |
| Os VE estavam prontos a partir? | Serviço mínimo aceitável à partida | Mais alto é melhor; a variante viável avalia as partidas cujo limiar de serviço era atingível. |
| Com que exatidão foi seguido o alvo dos VE? | Rácio de partidas dentro da tolerância simétrica | Mais alto significa um seguimento do alvo mais próximo. Carregar acima da banda pode cumprir o serviço mínimo e falhar esta medida de exatidão. |
| Os limites elétricos foram respeitados? | Energia de violação residual | Mais baixo é melhor. Mede o excesso depois do tratamento das restrições. |
| Quanto intervieram as restrições? | Energia de pressão pedida | Excesso associado ao pedido antes da projeção; não é o mesmo que uma violação da potência aplicada. |
| Quanta atividade de armazenamento foi usada? | Energia movimentada pelas baterias e exportação V2G | Reporte com custos, serviço e degradação; mais alto ou mais baixo não é sempre melhor. |
| Quanta energia solar ficou na comunidade? | Rácio de autoconsumo solar | Mais alto significa mais produção FV consumida localmente. Leia com a produção total e as importações. |
| Quanta energia atravessou a fronteira com a rede? | Importação, exportação e net exchange | Leia as três: o net exchange sozinho pode esconder grandes importações e exportações. |
| Quão exigente foi o perfil de importação? | Rácios de pico e de penalização do fator de carga face ao BAU | Abaixo de 1 é mais baixo do que o BAU e acima de 1 é mais alto. As penalizações do fator de carga usam a potência importada; os picos usam a potência líquida com sinal, pelo que uma comunidade que exporta em todos os passos tem um pico nulo ou negativo (ver [energia da rede e forma da carga](kpis_reference.md#energia-da-rede-e-forma-da-carga)). |

O simulador define uma seleção predefinida para as linhas de edifício e de
distrito, que `env.scorecard()` devolve. Os
[nomes exatos](https://www.citylearn.net/guides/scorecard_kpi_names.html) são
gerados a partir dessa seleção quando a documentação é construída.

## Construir um scorecard compacto

Depois do ciclo de simulação, selecione as linhas relevantes da tabela devolvida:

```python
kpis = env.evaluate_v2()
selected = [
    "district_cost_total_control_eur",
    "district_cost_total_business_as_usual_eur",
    "district_energy_grid_total_import_control_kwh",
    "district_ev_performance_departure_min_acceptable_feasible_ratio",
    "district_ev_performance_departure_within_tolerance_feasible_ratio",
    "district_electrical_service_phase_violations_energy_total_kwh",
    "district_electrical_service_phase_requested_pressure_energy_total_kwh",
]
scorecard = kpis.loc[
    (kpis["level"] == "district") & kpis["cost_function"].isin(selected),
    ["cost_function", "value"],
]
print(scorecard.to_string(index=False))
scorecard.to_csv("scorecard.csv", index=False)
```

Para comparar vários controladores, use o mesmo cenário, janela e configuração
de serviços em cada um, identifique as suas tabelas de KPIs e cruze
`cost_function` com o nome do controlador. Use as mesmas sementes aleatórias em
cenários estocásticos emparelhados. Mantenha os valores em falta ou não
aplicáveis em falta, e não como zero.

## Duas referências diferentes

O guia de [Baselines](baselines.md) explica a política BAU nativa, os seus
parâmetros por omissão e as referências separadas usadas na avaliação e no
settlement de demand response.

Os nomes com `baseline` referem-se ao contrafactual convencional de avaliação
configurado, normalmente sem armazenamento nem controlo de carga parcial, com
PV. Usa as séries contrafactuais do próprio simulador.

Os nomes com `business_as_usual` referem-se a uma execução BAU nativa separada,
nas condições do cenário e do episódio. O agente BAU carrega os VE até à carga
completa por omissão, arranca os equipamentos flexíveis prontos e opera o
armazenamento estacionário para autoconsumo FV. `evaluate_v2()` executa ou
reutiliza essa comparação, salvo com `include_business_as_usual=False`.

Não misture colunas `ratio_to_baseline` e `ratio_to_business_as_usual` numa
comparação sem identificar a referência. Um rácio é adimensional. Com
denominador zero, a divisão segura devolve 1 quando os dois valores são
praticamente zero, e um valor em falta quando o numerador não é zero. Os rácios
dos equipamentos flexíveis ao BAU são a exceção: ficam em falta quando os seus
dois totais são zero (ver [regras comuns](kpis_reference.md#regras-comuns)).

## Serviço dos VE versus exatidão do alvo

Com um SOC alvo de 80 % e uma tolerância de 5 pontos percentuais:

- 76 % cumpre o serviço mínimo e está dentro da banda simétrica do alvo.
- 90 % cumpre o serviço mínimo, mas está fora dessa banda.
- 70 % não cumpre nenhum dos dois.

`minimum_acceptable` usa o limiar inferior de serviço; `within_tolerance` usa os
limites inferior e superior. As variantes viáveis restringem a população às
partidas em que o limiar respetivo era fisicamente atingível. Reporte as
contagens de partidas e de viabilidade juntamente com estes rácios.

## Alargar o scorecard para a sua experiência

As comparações das aplicações REC usam também emissões, conclusão das cargas
flexíveis, importação e exportação residuais depois da troca local, e poupanças
do settlement. Complementam a seleção predefinida:

| Indicador | Nome do KPI ou cálculo |
|---|---|
| Emissões | `district_emissions_total_control_kgco2` |
| Serviço das cargas flexíveis | `district_deferrable_appliance_service_service_level_ratio` |
| Importação depois da partilha local | `district_energy_grid_community_market_grid_import_after_local_total_kwh` |
| Exportação depois da partilha local | `district_energy_grid_community_market_grid_export_after_local_total_kwh` |
| Poupança do settlement | `district_cost_community_market_savings_total_eur` |
| Pico face ao BAU | `district_energy_grid_shape_quality_peak_all_time_average_to_business_as_usual_ratio` |

Os picos absolutos são `district_energy_grid_shape_quality_peak_all_time_average_control_kw`
e o correspondente `_business_as_usual_kw`; não rotule um rácio de pico como kW.
Em experiências de demand response, acrescente pedido, entrega, cumprimento,
shortfall e receita líquida; em estudos térmicos, acrescente
`district_thermal_service_audit_discomfort_ratio`, o KPI de desconforto canónico,
com as suas contagens de cobertura; em estudos de falhas, acrescente os
contadores de robustez.

Use a [referência de KPIs](kpis_reference.md) para unidades e definições, o
[catálogo de KPIs](KPI_V2_TREE.md) para todos os outros nomes e o
[guia da UI](https://www.citylearn.net/ui.html) para comparações visuais.
