# Referência de KPIs

Esta página define todos os KPIs que o CityLearn calcula: o que cada família
mede, as suas equações, como os membros são agregados ao distrito e ao
portefólio, e quando um valor é indefinido. Cada equação está aqui e em mais
nenhum lado. O [catálogo de KPIs](KPI_V2_TREE.md) lista todos os nomes com um
significado de uma linha e remete para estas secções.

Versão em inglês: [../kpis_reference.md](../kpis_reference.md).

| API | Estado | Formato | Uso recomendado |
|---|---|---|---|
| `evaluate()` | legacy | DataFrame com os nomes históricos das cost functions | Compatibilidade com workflows antigos. |
| `evaluate_v2()` | principal | DataFrame com nomes estruturados | Comparação científica, dashboards e exports. |

Para uma seleção compacta e a sua interpretação, começar pelo guia do
[scorecard](scorecard.md); `env.scorecard()` devolve as linhas predefinidas. O
nome `v2` do método designa a interface de KPIs, não a versão 2 do CityLearn.

Para listar os nomes disponíveis numa execução:

```python
kpis = env.evaluate_v2()
names = kpis[["cost_function", "level"]].drop_duplicates().sort_values("cost_function")
print(names.to_string(index=False))
```

As linhas presentes dependem dos equipamentos e serviços do cenário. Um valor
em falta não é uma medição de zero; deve manter-se em falta ao exportar ou
comparar.

## Unidades

| Sufixo | Significado |
|---|---|
| `eur` | Custo monetário, na moeda dos preços do dataset. |
| `kwh` | Energia acumulada nos steps avaliados. |
| `kgco2` | Emissões acumuladas nos steps avaliados. |
| `kw` | Potência. |
| `ratio` | Razão adimensional. |
| `percent` | Percentagem. |
| `count` | Contagem de eventos, ciclos, steps ou membros. |
| `hours` | Horas; no conforto térmico, graus-hora (°C·h) quando a secção o indica. |
| `c` | Graus Celsius. |

## Níveis

`evaluate_v2()` devolve uma linha por KPI e âmbito; a coluna `level` indica o
âmbito, e o nome começa por ele.

| Nível | Linhas | Construído a partir de |
|---|---|---|
| `building` | Uma linha por membro (`name` é o edifício). | As séries do próprio membro. |
| `district` | Uma linha para a comunidade (`name` é `District`). | As séries do distrito ou os valores dos membros, como indica a secção de cada família. |
| `portfolio` | Uma linha para um portefólio de `MultiCommunityEnv` (`community_id` é `__portfolio__`). | As linhas de distrito das comunidades, segundo as regras abaixo. |

`MultiCommunityEnv.evaluate_v2()` devolve as linhas de edifício e de distrito de
cada comunidade, com o seu `community_id`, e as linhas de portefólio. Um nome de
portefólio substitui o prefixo `district_` por `portfolio_`. Cada KPI de distrito
é agregado pela primeira regra que se aplica:

1. **Ratios de um total control sobre um total de referência** (os ratios
   `ratio_to_baseline` e `ratio_to_business_as_usual` de custo, emissões,
   importação, exportação e net exchange, e os ratios `ratio_to_business_as_usual`
   de geração e exportação solar, carga dos VE e exportação V2G, carga, descarga
   e throughput das baterias, e ciclos e energia dos equipamentos flexíveis) são
   o ratio dos totais somados nas comunidades que reportam ambos, com as regras
   das [regras comuns](#regras-comuns).
2. **Taxas e médias com um denominador aditivo** são agregadas (pooled): a média
   dos valores das comunidades ponderada por esse denominador, igual ao ratio
   entre o numerador e o denominador agregados. As secções de cada família
   indicam cada linha agregada e o seu peso; os deltas e ratios ao BAU das linhas
   agregadas são calculados entre os valores agregados.
3. **Nomes terminados em `_kwh`, `_eur`, `_kgco2` ou `_count`** são somados.
4. **Os restantes `_ratio` e `_percent`** são médias ponderadas pelo `weight` da
   comunidade.
5. **Tudo o resto** (`_kw`, `_c`, `_hours` e outros valores pontuais) não tem
   linha de portefólio, exceto `energy_grid_window_average_power_*_kw`, que soma
   as médias na janela das comunidades sincronizadas quando `evaluation_window`
   está ativo.

Uma taxa agregada mantém a linha de portefólio qualquer que seja a unidade, pelo
que o atraso de arranque agregado dos equipamentos flexíveis (`_hours`) tem uma.
A [referência multi-comunidade](multi_community_reference.md#agregação-dos-kpis) explica o
portefólio.

## Contrato de nomes

```text
level_family_subfamily_metric_variant_unit
```

| Parte | Exemplos |
|---|---|
| `level` | `building`, `district`, `portfolio`. |
| `family` | `cost`, `energy_grid`, `emissions`, `solar_self_consumption`, `battery`, `electrical_service_phase`, `ev`, `deferrable_appliance`, `escalator`, `comfort_resilience`, `thermal_service_audit`, `equity`, `equity_audit`, `demand_response`, `demand_response_audit`, `robustness`, `energy_provenance`. |
| `subfamily` | `total`, `daily_average`, `ratio_to_baseline`, `ratio_to_business_as_usual`, `shape_quality`, `service`, `community_market`, `departure_audit`. |
| `metric` | `import`, `export`, `charge`, `completed_cycles`. |
| `variant` | `control`, `baseline`, `business_as_usual`, `delta`, `delta_to_business_as_usual`, `building_mean`, `signed_net`. |
| `unit` | Ver [Unidades](#unidades). |

As famílias principais seguem o contrato. As linhas de auditoria, de
proveniência e de demand response colocam os seus qualificadores depois da
família e nem sempre usam as cinco partes, e a posição da variante varia entre
famílias; o [catálogo](KPI_V2_TREE.md) dá todos os nomes exatos. Uma linha não
tem prefixo de nível: `topology_lifecycle_presence` (ver
[Topologia dinâmica](#topologia-dinâmica)).

O [catálogo de KPIs](KPI_V2_TREE.md) agrupa os nomes nestas famílias, cada uma
explicada na sua secção:

- [Custo](#custo): Custo da eletricidade de cada membro e do distrito ao longo do episódio avaliado; as linhas aparecem em todas as execuções.
- [Energia da rede e forma da carga](#energia-da-rede-e-forma-da-carga): Energia trocada com a rede por cada membro e pelo distrito, e a forma da carga do distrito (picos, rampas, fator de carga); as linhas aparecem em todas as execuções, as de forma só ao nível do distrito.
- [Emissões](#emissões): Emissões de carbono da eletricidade importada da rede por cada membro e pelo distrito; as linhas aparecem em todas as execuções.
- [Autoconsumo solar](#autoconsumo-solar): Produção fotovoltaica (FV) e quanto dela é usado dentro de cada membro ou do distrito em vez de ser exportado ou cortado; as linhas aparecem em todas as execuções e são nulas ou indefinidas sem FV.
- [Mercado comunitário](#mercado-comunitário): Troca local de energia entre os membros de uma comunidade e a respetiva liquidação. As linhas aparecem em todas as simulações (a zero, ou com quotas indefinidas, quando `community_market.enabled` é falso), exceto `local_traded` e `import_share`, que exigem o mercado e os respetivos interruptores de KPI.
- [Baterias](#baterias): Atividade e desgaste das baterias estacionárias; as linhas aparecem em todas as execuções, com energia nula e ciclos e perda de capacidade indefinidos para membros sem bateria.
- [Serviço elétrico e fases](#serviço-elétrico-e-fases): Cumprimento dos limites de potência total e por fase declarados para o serviço elétrico, e o equilíbrio e os picos das fases; os valores são nulos ou indefinidos se o esquema não configurar um serviço elétrico.
- [Veículos elétricos](#veículos-elétricos): Serviço à partida, energia de carregamento e V2G dos veículos elétricos (VE) nos carregadores dos membros, e saúde e desgaste opt-in das baterias dos VE (`evaluate_v2(include_battery_health_audit=True)`). Todos os membros emitem as linhas de partida e energia; sem carregadores, as contagens e energias são 0 e as taxas ficam indefinidas.
- [Auditoria das partidas dos VE](#auditoria-das-partidas-dos-ve): Serviço auditado às partidas dos VE, com uma população explícita, um estado de viabilidade com três classes e o motivo de cada caso desconhecido. Todos os membros emitem estas linhas.
- [Equipamentos flexíveis](#equipamentos-flexíveis): Serviço dos ciclos dos equipamentos flexíveis (diferíveis) a partir dos estados dos ciclos e das energias nominais dos ciclos. Todos os membros emitem estas linhas; sem equipamentos, as contagens e energias são 0 e as taxas ficam indefinidas.
- [Auditoria dos equipamentos flexíveis](#auditoria-dos-equipamentos-flexíveis): Serviço auditado dos ciclos dos equipamentos flexíveis a partir da energia medida nos intervalos executados, com uma população explícita e estados exclusivos. Todos os membros emitem estas linhas.
- [Escadas rolantes](#escadas-rolantes): Serviço aos passageiros, mudanças de estado de funcionamento e consumo de eletricidade das escadas rolantes. Todos os membros emitem estas linhas; sem escadas rolantes, os totais são 0 e o nível de serviço fica indefinido.
- [Conforto e resiliência](#conforto-e-resiliência): Linhas legadas de conforto térmico e de resiliência a cortes de energia de cada edifício, sempre emitidas; o valor do distrito é a média simples dos edifícios, e o KPI de desconforto canónico é `district_thermal_service_audit_discomfort_ratio`.
- [Auditoria do serviço térmico](#auditoria-do-serviço-térmico): Contagens de intervalos, horas, energia e razões que auditam o conforto térmico e a energia de serviço de cada edifício, sempre emitidas; o distrito soma as contagens, e `district_thermal_service_audit_discomfort_ratio` é o KPI de desconforto canónico.
- [Equidade](#equidade): Benefício relativo de custo de cada edifício face à referência convencional e a sua distribuição no distrito, sempre emitidos; o KPI de Gini canónico é `district_equity_audit_positive_benefit_gini_ratio`.
- [Auditoria de equidade](#auditoria-de-equidade): Linhas de equidade do distrito com a respetiva população de membros, sempre emitidas; `district_equity_audit_positive_benefit_gini_ratio` é o KPI de Gini canónico.
- [Demand response](#demand-response): Resposta aos pedidos de demand response do dataset, medida face a uma baseline pré-evento, e a respetiva liquidação; as linhas aparecem quando `demand_response.enabled` é verdadeiro.
- [Auditoria de demand response](#auditoria-de-demand-response): Totais, cobertura e exclusões de demand response do distrito, separados pelo propósito declarado do pedido (`all`, `service`, `stress`, `unspecified`); as linhas aparecem quando o demand response está ativo, para os quatro propósitos.
- [Robustez](#robustez): Contadores das perturbações de observações, previsões, ações e ativos aplicadas pelos eventos de robustez do dataset; as linhas aparecem quando `robustness.enabled` é verdadeiro.
- [Proveniência da energia](#proveniência-da-energia): Segue cada kWh de eletricidade desde a origem (produção FV própria ou de vizinhos, importação da rede, ou energia armazenada de origem desconhecida) até ao destino (consumo, armazenamento, mobilidade, exportação, perdas e outros), com o carbono da rede que transporta; as linhas existem sempre que o ambiente mantém o registo de proveniência (`energy_provenance=True`, valor por omissão).
- [Topologia dinâmica](#topologia-dinâmica): Registo do ciclo de vida dos membros de uma topologia dinâmica; a linha só aparece com `topology_mode='dynamic'`.

## Regras comuns

### Séries de energia

Para a eletricidade líquida de um membro ou do distrito no step `t`, `net_t`,
positiva quando importa:

```text
import_kwh       = sum_t max(net_t, 0)
export_kwh       = sum_t max(-net_t, 0)
net_exchange_kwh = sum_t net_t
```

As somas percorrem os steps executados do episódio; a observação terminal não é
um step. Com topologia dinâmica, um membro só conta enquanto está ativo.

### Control, baseline e business as usual

| Variante | Significado |
|---|---|
| `control` | A execução avaliada. |
| `baseline` | O contrafactual convencional da mesma execução: os membros sem a bateria e o armazenamento térmico (e sem controlo de carga parcial nos edifícios com dinâmica LSTM), com PV, lido das próprias séries do simulador. O carregamento dos VE da execução é substituído pelo do BAU nativo com o alvo `'full'` (carregados à chegada até ficarem cheios, sem V2G), igual para todos os controladores; os aparelhos diferíveis ficam como o controlador os operou, e o AVAC também, exceto nos edifícios com dinâmica LSTM, que usam a procura de aquecimento e de arrefecimento de carga ideal do dataset. `baseline_version=1` não volta a somar carregamento dos VE, como no CityLearn 3.6.0. `evaluate_v2(baseline_condition=...)` escolhe outra condição. Nos steps com falha de energia, as suas séries de net, custo e emissões são zero, como as da execução controlada. |
| `business_as_usual` | A execução business-as-usual nativa do mesmo cenário e janela (ver [Baselines](baselines.md)). Com `baseline_version=2` (predefinida), o seu AVAC fornece a procura de aquecimento e de arrefecimento do dataset; com `baseline_version=1` pede zero, como no CityLearn 3.6.0 ([AVAC e a versão da baseline](baselines.md#avac-e-a-versão-da-baseline)). |
| `delta` | `control - baseline`. |
| `delta_to_business_as_usual` | `control - business_as_usual`. |

```text
ratio_to_baseline_x          = control_x / baseline_x
ratio_to_business_as_usual_x = control_x / business_as_usual_x
```

Os ratios de distrito dividem totais de distrito; uma média de ratios dos
edifícios não é um ratio de distrito. Onde um valor da 3.6.0 era uma média de
ratios dos edifícios, fica disponível como variante `building_mean` (ver
[Definições alteradas depois da 3.6.0](#definicoes-alteradas-depois-da-360)).

### Divisão segura e valores indefinidos

Todos os ratios usam divisão segura:

- é indefinido (em falta, `NaN`) quando o control ou a referência está em falta
  ou não é finito;
- quando a referência está dentro da tolerância numérica de zero, é `1.0` ("sem
  alteração") se o control também for praticamente zero, e indefinido caso
  contrário;
- **exceção:** cada `*_deferrable_appliance_ratio_to_business_as_usual_*_ratio`
  é indefinido quando os seus dois totais são zero, mesmo que tenha havido ciclos
  devidos. Por exemplo, o ratio de ciclos falhados é indefinido quando nenhuma das
  execuções falhou um ciclo.
- **exceção:** os ratios de custo e de emissões
  (`*_cost_ratio_to_*_total_ratio`, `*_emissions_ratio_to_*_total_ratio`) são
  indefinidos quando os dois totais são zero. Nada foi faturado nem emitido, como
  num dataset com intensidade carbónica nula, pelo que não há nada a comparar. As
  variantes `*_building_mean_ratio` mantêm o valor da 3.6.0.

Os ratios mantêm-se lower-is-better quando o total de referência é negativo. Os
totais de net exchange e de custo podem ser negativos, para um exportador
líquido ou depois das receitas do mercado comunitário; os seus ratios usam

```text
ratio_x = control_x / reference_x                        se reference_x > 0
ratio_x = 1 + (control_x - reference_x) / |reference_x|  se reference_x < 0
```

pelo que 1 continua a significar sem alteração e um total control maior dá um
ratio maior. Os totais de importação, exportação e emissões nunca são negativos
e usam o ratio simples.

Um valor indefinido nunca é lido como zero. Taxas sem eventos a avaliar (por
exemplo, uma taxa de sucesso dos VE sem partidas) são indefinidas, não 0 nem 1.

### Médias diárias

```text
daily_average_x = total_x / days
```

Ao nível do edifício, `days` é a duração da janela ativa do membro, em dias: o
episódio inteiro numa comunidade estática, o tempo em que o membro esteve
presente com topologia dinâmica. Ao nível do distrito é a duração do episódio
avaliado, `steps * seconds_per_time_step / 86400`.

## Custo

O custo da eletricidade de cada membro e do distrito ao longo do episódio avaliado. As linhas aparecem em todas as execuções.

```text
custo_t  = max(net_t, 0) · preço_t
total    = Σ_t custo_t
net_t    = eletricidade líquida do membro no passo t, em kWh (importação > 0, exportação < 0)
preço_t  = preço da eletricidade no passo t
```

Sem mercado comunitário, só a importação é paga: a energia exportada não é remunerada, pelo que os totais nunca são negativos. Com mercado comunitário, a execução controlada e o contrafactual convencional são ambos liquidados com as regras de mercado do cenário, e os totais podem ser negativos. `control` usa as séries da execução controlada, e `baseline` usa as séries do contrafactual convencional (por omissão, sem armazenamento e, nos modelos dinâmicos de edifício, sem controlo de carga parcial). `delta = control − baseline`.

Os rácios ao contrafactual e à execução BAU usam o rácio com sinal:

```text
rácio = controlo / referência                         se referência ≥ 0
rácio = 1 + (controlo − referência) / |referência|    se referência < 0
```

Assim, 1 significa ausência de alteração, e um custo do controlo mais alto dá sempre um rácio mais alto. As médias diárias dividem o total de um membro pelos dias ativos desse membro, e o total do distrito pelos dias simulados ([regras comuns](#regras-comuns)).

**Distrito.** O custo do distrito é a soma dos custos dos membros: não é o custo da importação compensada do distrito, ao contrário das emissões do distrito. Os rácios do distrito dividem os totais do distrito.

**Portefólio.** Os totais e as médias diárias são somados sobre as comunidades. Os rácios são rácios com sinal entre os totais somados do controlo e da referência, nas comunidades que reportam ambos.

**Que KPI usar.** Use `cost_total_control_eur` com `cost_total_business_as_usual_eur` e a respetiva diferença para comparar controladores com a execução BAU nativa. Use as linhas `baseline` apenas para comparar com o contrafactual convencional, e não misture as duas referências.

**Limitações conhecidas.**
- Sem mercado comunitário, a exportação não é creditada, pelo que o controlador não obtém valor ao exportar.
- Um custo total em falta é reportado como 0, e não como indefinido.

## Energia da rede e forma da carga

A energia trocada com a rede por cada membro e pelo distrito, e a forma da carga do distrito. Os totais aparecem em todas as execuções, ao nível do edifício e do distrito. As linhas de forma (`shape_quality`) aparecem apenas ao nível do distrito.

### Totais de energia

```text
importação     = Σ_t max(net_t, 0)
exportação     = Σ_t max(−net_t, 0)
troca líquida  = Σ_t net_t
```

`net_t` está em kWh por passo, e os passos não finitos são ignorados. Um edifício usa a sua própria série líquida. O distrito usa a série líquida do distrito `N_t = Σ_b net_b,t`, pelo que a energia que um membro exporta e outro importa no mesmo passo não entra na importação nem na exportação do distrito. Por isso, a importação do distrito é menor ou igual à soma das importações dos edifícios.

Os rácios ao contrafactual e à execução BAU dividem os totais do controlo pelos totais da referência. A troca líquida usa o rácio com sinal (ver [Custo](#custo)), e a importação e a exportação usam o rácio simples. Os rácios do distrito dividem os totais do distrito. As médias diárias dividem o total de um membro pelos dias ativos desse membro, e o total do distrito pelos dias simulados ([regras comuns](#regras-comuns)).

### Forma da carga

As janelas são blocos consecutivos de `round(W / Δt)` passos a partir do primeiro passo do episódio: `W` = 24 h (diária), 730 h (mensal) ou o episódio inteiro (`all_time`). Não estão alinhadas com dias ou meses do calendário, e a última janela pode ser incompleta. A potência é `p_t = N_t / Δh`, sendo `Δh` a duração do passo em horas.

```text
pico         P = média sobre as janelas w de max_{t∈w} p_t              (potência líquida com sinal, sem corte)
rampa        R_total = Σ_{t≥1} max(p_t − p_{t−1}, 0)
             R_média = R_total / (número de transições com p_t e p_{t−1} ambos finitos)
penalização  L = média sobre as janelas w de (1 − média_{t∈w} x_t / max_{t∈w} x_t)
             x_t = max(p_t, 0) (importação),   ou x_t = p_t nas linhas _signed_net
```

- Os passos não finitos são excluídos de cada janela. Uma janela de pico sem nenhum valor finito é ignorada.
- Uma janela do fator de carga cujo máximo seja ≤ 1e-6 não tem penalização e é ignorada. `L` é indefinida quando nenhuma janela está definida. Com `_signed_net`, uma janela de média negativa dá uma penalização superior a 1.
- `R_média` é indefinida quando não há nenhuma transição finita.
- Um exportador líquido pode ter um pico negativo, pelo que os rácios de pico podem ser negativos ou indefinidos.

Dois conjuntos de linhas usam séries diferentes:

- **Rácios ao contrafactual** (`*_to_baseline_ratio`, `*_to_baseline_signed_net_ratio`) comparam as séries do distrito das condições `control_condition` e `baseline_condition` da avaliação. `ramping_average_to_baseline_ratio` é `R_total(controlo) / R_total(contrafactual)`, a definição da versão 3.6.0; só é igual ao rácio das médias quando as duas séries têm o mesmo número de transições finitas.
- **Linhas BAU** comparam a potência do distrito na execução controlada (a série de controlo por omissão, seja qual for `control_condition`; [#331](https://github.com/citylearn-project/CityLearn/issues/331)) com a da execução BAU nativa. Cada métrica publica `_control` (o valor do controlo), `_business_as_usual` (o valor BAU), `_delta_to_business_as_usual` (controlo − BAU) e `*_to_business_as_usual_ratio`; estas linhas existem quando `evaluate_v2()` inclui a comparação com o BAU. `ramping_total` não tem linha de rácio.

Note a ordem das palavras nos nomes com sinal: `load_factor_penalty_daily_average_to_baseline_signed_net_ratio`, mas `load_factor_penalty_daily_average_signed_net_to_business_as_usual_ratio`.

**Portefólio.** Os totais de energia e as médias diárias são somados sobre as comunidades. Os rácios de importação, exportação e troca líquida são rácios dos totais somados (com sinal para a troca líquida). Os rácios de forma e os rácios `building_mean` são médias ponderadas pelo `weight` de cada comunidade. As linhas de forma em kW não passam para o portefólio. As energias (`_kwh`) e contagens de passos (`_count`) de excesso no alimentador são somadas sobre as comunidades, enquanto os picos (`_kw`) não passam para o portefólio ([excessos nos limites do alimentador do distrito](kpis_reference.md#excessos-nos-limites-do-alimentador-do-distrito)). Quando `evaluation_window` está ativo, `energy_grid_window_average_power_*_kw` soma com sinal as comunidades que partilham essa janela e fica indefinido quando algum valor de comunidade é indefinido ([janela de avaliação recorrente](kpis_reference.md#janela-de-avaliação-recorrente)).

**Que KPI usar.**
- Use o rácio do distrito `ratio_to_baseline_import_total_ratio`. `*_building_mean_ratio` é a média dos rácios dos edifícios, mantida apenas para comparar com resultados até à versão 3.6.0.
- Use a penalização do fator de carga baseada na importação. As linhas `_signed_net` mantêm a definição da versão 3.6.0.
- Use `ramping_average`, que não cresce com a duração do episódio. `ramping_total` mantém o valor da versão 3.6.0.
- Leia em conjunto a importação, a exportação e a troca líquida: a troca líquida, sozinha, pode esconder grandes importações e exportações.

**Limitações conhecidas.**
- As linhas de forma BAU ignoram `control_condition`; os rácios ao contrafactual respeitam-na.
- `ramping_average_to_baseline_ratio` é um rácio de rampas totais, apesar do nome.
- Não é calculado nenhum pico mensal.
- As janelas de forma contam-se a partir do início do episódio, e não da meia-noite ou do início do mês.

### Excessos nos limites do alimentador do distrito

Quando `district_electrical_service.enabled` é verdadeiro (ver a [referência do esquema](schema_reference.md#servico-eletrico-do-distrito)), `evaluate_v2()` mede e reporta os excessos face aos limites do alimentador na potência líquida do distrito sem impor cortes nem alterar o despacho dos equipamentos:

```text
Δh = duração do passo em horas
P_t = N_t / Δh                             potência líquida do distrito no passo executado t, em kW
excesso importação_t = max(P_t − limite_importação,t, 0)
excesso exportação_t = max(−P_t − limite_exportação,t, 0)
excesso ≤ 1e-5 kW é posto a 0

exceedance_energy_total_control_kwh = Σ_t Δh · excesso_t
exceedance_peak_control_kw          = max_t excesso_t
exceedance_step_control_count       = número de passos executados com Δh · excesso_t > 1e-9 kWh
```

As séries por passo ficam expostas em `env.feeder_import_exceedance_kw` e `env.feeder_export_exceedance_kw` (vazias logo após `reset()` até `step()` correr, e `0.0` nos passos sem limite nessa direção). Cada métrica publica `_control`, `_business_as_usual` e `_delta_to_business_as_usual` (`control − business_as_usual`); com `evaluate_v2(include_business_as_usual=False)`, apenas `_control` é emitido. Se `district_electrical_service` estiver ativo com apenas uma direção configurada, a direção não configurada fica indefinida (`NaN`). Quando `district_electrical_service` está desativado, estas linhas não são emitidas.

### Janela de avaliação recorrente

Quando `evaluation_window.enabled` é verdadeiro (ver a [referência do esquema](schema_reference.md#janela-de-avaliacao)), `evaluate_v2()` e as exportações de KPIs incluem linhas de potência na janela local recorrente aos níveis de edifício, distrito e portefólio:

```text
w_t = τ_t / Δt                                fração de sobreposição do passo t em [0, 1]
H_W = Σ_t w_t · Δh                            horas efetivas na janela nos passos finitos
energy_grid_window_average_power_control_kw            = (Σ_t w_t · net_t) / H_W
energy_grid_window_average_power_business_as_usual_kw  = (Σ_t w_t · net_bau,t) / H_W
energy_grid_window_average_power_delta_to_business_as_usual_kw = control − business_as_usual
```

`τ_t` é a sobreposição em segundos entre o passo executado `[s_t, s_t + Δt)` em hora local e a janela diária configurada (`16:00:00` a `19:00:00` quando ativada sem limites explícitos). Com um calendário canónico `time_axis`, `s_t` é convertido de `timestamp_utc` para `evaluation_window.timezone`; sem ficheiro de calendário, a coluna `hour` do conjunto de dados varia de `1` a `24` e `s_t` usa `(hour − 1) mod 24` (`hour = 1, minutes = 0` começa às `00:00:00`), coincidindo com as variáveis temporais da interface de entidades. Janelas com `start > end` atravessam a meia-noite em `[start, 24:00)` e `[00:00, end)`. Os passos que intersetam uma fronteira recebem peso parcial `0 < w_t < 1`. Quando `H_W = 0`, todas as linhas da janela ficam indefinidas (`NaN`). Com `evaluate_v2(include_business_as_usual=False)`, apenas `_control_kw` é emitido.

Para explorar outras janelas após a simulação sem voltar a correr o episódio, pondere as séries temporais exportadas de uma sessão renderizada (`exported_data_community_ep0.csv` escreve `timestamp` a partir de `time_axis`, ou a partir de `start_date` `00:00:00` quando o episódio começa à meia-noite):

```python
from pathlib import Path
import json
import numpy as np
import pandas as pd


def step_weight(t0: float, dt: float, segments: list[tuple[float, float]]) -> float:
    parts = [(t0, min(t0 + dt, 86400.0))] + ([(0.0, t0 + dt - 86400.0)] if t0 + dt > 86400.0 else [])
    return sum(max(0.0, min(s1, w1) - max(s0, w0)) for s0, s1 in parts for w0, w1 in segments) / dt


export_dir = Path("render_logs/my_session")
manifest = json.loads((export_dir / "exported_kpis.manifest.json").read_text(encoding="utf-8"))
dt = float(manifest["effective_schema"]["seconds_per_time_step"])

community = pd.read_csv(export_dir / "exported_data_community_ep0.csv")
ts = pd.to_datetime(community["timestamp"])
sec_of_day = (ts.dt.hour * 3600 + ts.dt.minute * 60 + ts.dt.second).to_numpy(dtype=float)

start_s, end_s = 16 * 3600, 19 * 3600
segments = [(start_s, end_s)] if start_s < end_s else [(start_s, 86400.0), (0.0, end_s)]
weights = np.array([step_weight(float(t0), dt, segments) for t0 in sec_of_day], dtype=float)
hours = float(weights.sum() * (dt / 3600.0))

control_kw = float((weights * community["Net Electricity Consumption-kWh"]).sum() / hours)
bau = pd.read_csv(export_dir / "exported_data_business_as_usual_ep0.csv")
bau_net = bau.loc[bau["level"] == "district", "net_electricity_consumption_kwh"].to_numpy(dtype=float)
bau_kw = float((weights * bau_net).sum() / hours)
delta_kw = control_kw - bau_kw

ev_net_kwh = 0.0
for path in sorted(export_dir.glob("exported_data_*_ep0.csv")):
    cols = pd.read_csv(path, nrows=0).columns
    if {"Charger Consumption-kWh", "Charger Production-kWh"} <= set(cols):
        df = pd.read_csv(path)
        ac = np.maximum(df["Charger Consumption-kWh"], 0.0) - np.maximum(df["Charger Production-kWh"], 0.0)
        ev_net_kwh += float((weights * ac).sum())
```

## Emissões

As emissões de carbono da eletricidade importada da rede. As linhas aparecem em todas as execuções.

As emissões de um edifício são as da sua própria importação:

```text
E_b = Σ_t max(0, net_b,t · CI_b,t)
CI_b,t = intensidade carbónica do membro b no passo t, em kgCO2/kWh
```

As emissões do distrito são as da importação compensada do distrito, pelo que a energia que um membro exporta e outro importa no mesmo passo não tem carbono da rede. Em cada passo, sendo `i_b = max(net_b, 0)` a importação do membro b, `D = max(Σ_b net_b, 0)` a importação do distrito, e importadores os membros com `i_b > 1e-6`:

```text
e_t = 0                         se nenhum membro importa
e_t = D · CI                    se todos os importadores têm a mesma intensidade carbónica CI
e_t = Σ_b (i_b − l_b) · CI_b    caso contrário
l_b = parte da energia trocada localmente min(Σ_b i_b, Σ_b max(−net_b, 0)) atribuída ao importador b,
      proporcional aos pesos de importação dos membros (1 por omissão), limitada a i_b e redistribuída até se esgotar
E_distrito = Σ_t e_t
```

Quando um mercado comunitário está ativo com `local_trading_enabled` falso, não há troca local de energia, pelo que toda a importação de cada membro vem da rede e `e_t = Σ_b i_b · CI_b`, a soma dos membros. O rácio do preço local só define o preço da troca e nunca entra nas emissões ([#327](https://github.com/citylearn-project/CityLearn/issues/327)).

Um valor líquido ou uma intensidade carbónica não finitos contam como zero. O total do controlo é igual a `energy_provenance_external_purchase_emissions_kgco2` em qualquer configuração do mercado.

Por causa da compensação, o total do distrito é menor ou igual à soma dos totais dos edifícios. A definição do distrito da versão 3.6.0, a soma das emissões próprias dos membros, é mantida em `emissions_total_{control,baseline,business_as_usual}_member_sum_kgco2`.

Os rácios usam o rácio simples (as emissões nunca são negativas). O rácio do distrito ao contrafactual divide os totais compensados do distrito. `emissions_ratio_to_baseline_total_building_mean_ratio` mantém o valor da versão 3.6.0, a média simples dos rácios dos edifícios. As médias diárias dividem o total de um membro pelos dias ativos desse membro, e o total do distrito pelos dias simulados ([regras comuns](#regras-comuns)).

**Portefólio.** Os totais, os totais `member_sum` e as médias diárias são somados. Os rácios ao contrafactual e à execução BAU são rácios dos totais somados. O rácio `building_mean` é uma média ponderada pelo `weight` de cada comunidade.

**Que KPI usar.** Use os totais compensados do distrito, `emissions_total_control_kgco2` e as respetivas referências. Use as linhas `member_sum` e `building_mean` apenas para comparar com resultados até à versão 3.6.0. Não some as emissões dos edifícios para obter um valor do distrito.

**Limitações conhecidas.**
- As emissões do contrafactual de um edifício são postas a 0 quando a intensidade carbónica soma 0 na sua janela; as do controlo não são.

## Autoconsumo solar

A produção fotovoltaica (FV) e quanto dela é usado dentro de cada membro ou do distrito, em vez de ser exportado ou cortado. As linhas aparecem em todas as execuções; sem FV, as energias são 0 e o rácio é indefinido. Descrevem sempre a execução controlada: as condições de avaliação não se aplicam.

```text
g_t = max(−solar_t, 0)     produção FV disponível no passo t (solar_t é negativo)
c_t = corte FV no passo t: max(g_t − carga servida_t, 0) durante um corte de energia em ilha, 0 nos restantes passos
G = Σ_t g_t,  C = Σ_t c_t

edifício:  E = Σ_t min(g_t, max(−net_t, 0))
distrito:  G_t = Σ_b g_b,t,  C_t = Σ_b c_b,t,  N_t = Σ_b net_b,t
           E = Σ_t min(max(G_t − C_t, 0), max(−N_t, 0))

autoconsumo = (G − E − C) / G      indefinido quando G ≤ 0
```

A exportação do edifício é a exportação que a FV do membro pode suportar. A exportação do distrito é a exportação suportada por FV que sai do distrito depois de os membros partilharem energia no mesmo passo, pelo que o autoconsumo do distrito inclui a FV usada por outros membros. O distrito soma cada membro nos seus passos ativos. As médias diárias dividem o total de um membro pelos dias ativos desse membro, e o total do distrito pelos dias simulados ([regras comuns](#regras-comuns)). O corte não tem linha de média diária nem linha BAU.

**Portefólio.** A produção, a exportação e o corte são somados. O autoconsumo, do controlo e BAU, é a média dos valores das comunidades ponderada pela sua produção, o que é igual a `(ΣG − ΣE − ΣC) / ΣG`. A sua diferença e o seu rácio à execução BAU calculam-se entre estes valores agregados. Os rácios da produção e da exportação à execução BAU são rácios dos totais somados.

**Que KPI usar.** Use o rácio de autoconsumo do distrito para um resultado da comunidade. Não faça a média dos rácios dos edifícios: estes ignoram a energia partilhada entre membros. Leia-o com a produção total e a importação da rede.

**Limitações conhecidas.**
- O corte só é registado durante cortes de energia em ilha; fora deles, toda a FV conta como produção.

## Mercado comunitário

Em cada passo executado, o mercado comunitário liquida a energia que os membros trocam entre si antes de o restante ir para a rede ou vir dela. A liquidação só corre quando `community_market.enabled` é verdadeiro. Mesmo assim, as linhas de edifício e de distrito são emitidas em todas as simulações: sem mercado, as linhas de energia e de custo valem 0 e as quotas ficam indefinidas. Duas linhas do distrito são condicionais:
- `local_traded` exige o mercado e `community_market.kpis.community_local_traded_enabled`;
- `import_share` exige o mercado e `community_market.kpis.community_self_consumption_enabled`.

Ambos os interruptores são verdadeiros por omissão.

Liquidação no passo t, sobre os membros ativos nesse passo:

```text
n_i      = consumo líquido de eletricidade do membro i na simulação controlada (kWh; importação > 0)
imp_i    = max(n_i, 0)          exp_i = max(-n_i, 0)
traded   = min(soma_i imp_i, soma_i exp_i)    (0 quando community_market.local_trading_enabled é falso)
li_i     = importação local de i: traded repartido pelos importadores na proporção de
           community_market.import_member_weights (1 por omissão; partes iguais se todos os pesos forem 0),
           nunca acima de imp_i, redistribuído até traded estar todo atribuído
le_i     = exportação local de i = exp_i * traded / soma_j exp_j
gi_i     = max(imp_i - li_i, 0)   importação da rede depois da troca local
ge_i     = max(exp_i - le_i, 0)   exportação para a rede depois da troca local
```

No distrito, as somas de `li_i` e de `le_i` são ambas iguais a `traded`.

Preços do membro i no passo t:
- `p_imp` é o preço de importação da rede do membro.
- `p_exp`, `p_buy` e `p_sell` vêm da série `tariff_files` do membro, quando existe.
- Caso contrário, `p_exp` é `community_market.grid_export_price` quando `settlement_version` é 2, e 0 nos restantes casos.
- Caso contrário, `p_buy = p_sell = r * p_imp`, onde r é `community_market.local_price_ratio_to_grid_import` (chave antiga `intra_community_sell_ratio`), limitado a [0, 1] (0,8 por omissão).

```text
settled_i        = gi_i*p_imp + li_i*p_buy - le_i*p_sell - ge_i*p_exp
counterfactual_i = imp_i*p_imp - exp_i*p_exp
savings_i        = counterfactual_i - settled_i
operator_i       = li_i*p_buy - le_i*p_sell
```

Todos os totais de energia e de custo são somas nos passos executados. O custo liquidado também substitui o custo do membro na simulação controlada. O custo contrafactual é o custo só com a rede dos mesmos fluxos controlados. Não é a condição de avaliação `baseline`: essa é um contrafactual diferente, cujo custo a família de custo também liquida com as regras do mercado.

Saldo do operador, só no distrito (#239):

```text
operator_balance = soma_t soma_i operator_i
soma_i settled_i = soma_i (gi_i*p_imp - ge_i*p_exp) + operator_balance
```

O saldo do operador é positivo quando o mercado retém dinheiro. É zero quando todos os membros têm o mesmo preço local em cada passo. Não é zero quando os membros têm preços de importação da rede ou séries tarifárias diferentes, porque cada lado de uma troca local é então valorizado ao preço do seu membro.

Quotas:

```text
import_share          = soma li / (soma li + soma gi)        indefinida se o denominador <= 1e-6
local_share_of_demand = soma li / (soma li + soma gi)        indefinida se o denominador <= 0
local_share_of_export = soma le / (soma le + soma ge)        indefinida se o denominador <= 0
```

As somas percorrem os passos executados e, para o valor do distrito, os membros. O denominador da quota da procura é a importação bruta dos membros (a soma dos consumos líquidos positivos), não o seu consumo.

Distrito e portefólio:
- Os totais de energia e de custo do distrito são somas sobre os membros que participaram no episódio, incluindo os que depois saíram. As quotas do distrito são rácios desses totais.
- As médias diárias seguem as [regras comuns](#regras-comuns): as linhas de edifício dividem pelos dias ativos do membro, as de distrito pelos dias simulados.
- No portefólio, as linhas de energia e de custo, incluindo as médias diárias, são somadas pelas comunidades. As comunidades partilham a duração do passo e do episódio, por isso a soma das médias diárias é igual ao total agregado por dia.
- As quotas do portefólio são agregadas (#312), o que dá a quota dos totais somados:
  - `import_share` e `local_share_of_demand` são ponderadas pela importação local mais a importação da rede depois da troca local;
  - `local_share_of_export` pela exportação local mais a exportação para a rede depois da troca local.
- Portefólio com e sem mercados (#373): quando umas comunidades têm mercado comunitário e outras não, uma comunidade sem mercado entra nas linhas de mercado do portefólio com a sua liquidação simples com a rede. Não troca nada localmente; a sua importação e exportação da rede depois da troca local são a importação e a exportação dos seus próprios membros, as somas dos seus consumos líquidos positivos e negativos; os seus custos liquidado e contrafactual são o seu `cost_total_control_eur`, porque sem mercado os membros pagam à rede; a sua poupança e o saldo do operador são 0. As suas quotas contam por isso como 0, agregadas pelos seus fluxos com a rede. O custo liquidado do portefólio fica então igual ao `cost_total_control_eur` do portefólio, porque o custo de controlo de cada comunidade com mercado é o seu custo liquidado, e as quotas descrevem todo o portefólio. As linhas de distrito da própria comunidade mantêm os seus zeros. Quando nenhuma comunidade tem mercado, as linhas do portefólio são as somas desses zeros.

Que KPI usar:
- Para a parte da procura coberta localmente, use `district_solar_self_consumption_community_market_import_share_ratio`.
- `local_share_of_demand_ratio` é um alias obsoleto com a mesma fórmula, mantido por compatibilidade. Difere de `import_share` em dois pontos: é emitido em todas as simulações, e só fica indefinido com denominador nulo, não com denominador até 1e-6. Ao nível do edifício é a única quota da procura, porque `import_share` não é emitido para edifícios.
- `local_traded` repete a importação local do distrito.
- Nenhuma destas quotas é o rácio de autoconsumo solar da família `solar_self_consumption`.

Limitações conhecidas:
- As linhas existem com o mercado desativado: os zeros não medem troca local. Num portefólio que junta comunidades com e sem mercado, esses zeros são substituídos pela liquidação simples com a rede (ver acima).
- O nome `local_share_of_demand` refere a procura, mas o seu denominador é a importação bruta dos membros.
- As quotas e o saldo do operador não têm variante BAU.

## Baterias

A atividade e o desgaste das baterias estacionárias; as baterias dos VE não estão incluídas. As linhas aparecem em todas as execuções. Os membros sem bateria têm energia nula e ciclos e perda de capacidade indefinidos.

```text
carga        = Σ_t carga_t           energia que entra nos terminais da bateria, em kWh
descarga     = Σ_t descarga_t        energia que sai dos terminais da bateria, em kWh
T            = carga + descarga      (energia movimentada)
EFC          = T / (2 · capacidade)                                       indefinido quando capacidade ≤ 0
perda        = limitar((capacidade − capacidade_deg) / capacidade, 0, 1)   indefinida quando capacidade ≤ 0
capacidade      = capacidade nominal, somada sobre as baterias do membro com capacidade > 0
capacidade_deg  = capacidade degradada no momento da avaliação
```

**Distrito.** As energias são somas sobre os membros. Os ciclos e a perda de capacidade são agregados pela capacidade:

```text
EFC_distrito   = Σ_b T_b / (2 · Σ_b capacidade_b)
perda_distrito = Σ_b max(capacidade_b − capacidade_deg_b, 0) / Σ_b capacidade_b
```

**Portefólio.** A carga, a descarga e a energia movimentada são somadas, e os seus rácios à execução BAU são rácios dos totais somados. Os ciclos completos equivalentes obtêm-se dividindo a energia movimentada total pelo dobro da capacidade nominal total das baterias, separadamente para o controlo e para a execução BAU. O resultado é indefinido quando a capacidade nominal total é zero. A diferença e o rácio face à execução BAU comparam esses dois valores do portefólio. A perda de capacidade e o seu rácio à execução BAU são médias ponderadas pelo `weight` de cada comunidade.

**Que KPI usar.** Use a energia movimentada para medir a energia que passou pelas baterias e os ciclos completos equivalentes para medir a atividade das baterias em relação à capacidade nominal. Apresente a atividade das baterias juntamente com o custo e o serviço.

**Limitações conhecidas.**
- A capacidade degradada é lida no momento da avaliação, e não no fim da janela ativa do membro.

## Serviço elétrico e fases

O cumprimento dos limites de potência total e por fase declarados para o serviço elétrico, e o equilíbrio e os picos das fases. Se o esquema não configurar um serviço elétrico, as energias e as contagens são 0, o desequilíbrio é indefinido e o edifício não tem linhas de picos de fase.

```text
Δh = duração do passo em horas
P_t = potência aplicada na grandeza verificada (total, ou uma fase), em kW
excesso de importação_t = max(P_t − limite_importação, 0)
excesso de exportação_t = max(−P_t − limite_exportação, 0)
excesso ≤ 1e-5 kW é posto a 0
v_t = soma dos excessos sobre todos os limites declarados (importação total, exportação total, importação e exportação de cada fase)

energia de violação  = Σ_t Δh · v_t
contagem de violação = número de passos com Δh · v_t > 1e-9 kWh
```

O limite de importação total segue a série de disponibilidade da rede quando esta está configurada; um passo sem valor não tem limite de importação. A pressão pedida `r_t` é a energia em que o pedido do controlador, antes de ser projetado nos limites, os teria excedido:

```text
energia de pressão pedida  = Σ_t max(r_t, 0)
contagem de pressão pedida = número de passos com r_t > 1e-9 kWh
```

O desequilíbrio de fases aplica-se aos edifícios trifásicos com históricos de potência em L1, L2 e L3:

```text
u_t = (max_f |P_f,t| − min_f |P_f,t|) / média_f |P_f,t|      f ∈ {L1, L2, L3}
u_t = 0 quando média_f |P_f,t| ≤ 1e-9 kW
desequilíbrio_edifício = média de u_t sobre os passos da janela do membro
desequilíbrio_distrito = Σ_b Σ_t u_b,t / Σ_b n_b       n_b = passos contados no edifício b
```

Assim, o valor do distrito é a média sobre todos os passos de todos os edifícios trifásicos, e não a média dos valores dos edifícios. É indefinido quando nenhum edifício é trifásico.

Os picos de fase são `max_t max(P_f,t, 0)` (importação) e `max_t max(−P_f,t, 0)` (exportação), e 0 se a potência nunca tiver esse sinal. Um edifício tem uma linha por cada fase presente no seu histórico. O distrito toma o pico da potência da fase somada sobre os seus membros, para cada fase que pelo menos um membro tenha.

**Distrito.** As energias e as contagens são somas sobre os edifícios; uma contagem é um número de passos de edifícios.

**Portefólio.** As energias e as contagens são somadas. O desequilíbrio é uma média ponderada pelo `weight` de cada comunidade. Os picos de fase em kW não passam para o portefólio.

**Que KPI usar.** Use a energia de violação para avaliar se a potência aplicada respeitou os limites. A pressão pedida mede com que frequência e em que medida o controlador pediu mais do que os limites permitem; não é uma violação.

**Limitações conhecidas.**
- O desequilíbrio só está definido para edifícios trifásicos.

## Veículos elétricos

Estas linhas medem o estado de carga (SOC) com que os VE partem, a energia que os carregadores trocam com eles e (quando se passa `evaluate_v2(include_battery_health_audit=True)`) o estado de saúde, a perda de capacidade e os ciclos completos equivalentes das baterias dos VE. Todos os membros emitem as linhas de partida e energia. Um membro sem carregadores reporta 0 nas contagens e energias, e taxas indefinidas. Todos os valores cobrem a janela ativa do membro. As unidades, os nomes e as variantes BAU seguem as [regras comuns](#regras-comuns).

### Partidas

Regista-se uma partida no passo `t` quando há um VE ligado em `t` e se verifica uma das condições seguintes:
- em `t + 1` o carregador fica livre;
- o identificador da sessão ou do VE muda;
- o calendário não tem identificadores de sessão e a contagem decrescente até à partida reinicia: é no máximo 1 em `t` e aumenta em `t + 1`;
- `t` é o último passo da janela do membro (o último passo de controlo do episódio, ou o passo antes de o membro sair) e a contagem decrescente está em [0, 1], ou em [0, 2] quando outra divisão `episode_split_boundary='disjoint'` da simulação se segue ao episódio. São as sessões que partem antes do passo de controlo seguinte, que vem uma linha depois do último passo, ou duas linhas depois antes de uma divisão `'disjoint'` seguinte, cuja linha intermédia nunca é controlada. A última janela de uma simulação, um episódio único, as divisões rolantes e em lista explícita, e uma janela que termina antes do seu episódio usam todas [0, 1], pelo que uma execução não dividida não depende da fronteira. O último passo avalia-as com o SOC que o controlador atingiu. Com `evaluate_v2()` a meio de um episódio, a janela termina no passo atual.

Cada sessão é contada uma vez ao longo de episódios consecutivos. Uma partida no passo 0 de um episódio não é contada quando a mesma sessão já estava ligada na linha antes do passo 0: o mesmo identificador de sessão ou de VE nessa linha e, sem identificadores, sem reinício da contagem decrescente a partir de [0, 1]. Entre episódios consecutivos, essa linha é o último passo de controlo do episódio anterior com `'shared'`, e a linha entre os dois episódios com `'disjoint'`, pelo que o episódio anterior já contou a sessão no seu último passo, e o passo 0 apenas avaliaria o SOC definido no reset. A regra olha apenas para essa linha, pelo que também se aplica com `rolling_episode_split` ou com uma lista explícita de `episode_time_steps`, em que a linha antes do passo 0 pode não pertencer a nenhum episódio simulado e a sessão não é então contada. O primeiro episódio de uma simulação não tem linha antes do passo 0.

Com `ev_soc_carryover=True`, um episódio que continua o anterior no tempo começa cada VE com o SOC que atingiu no fim desse episódio, pelo que uma sessão ligada através da fronteira mantém a sua carga e é avaliada onde realmente parte. As divisões que transportam dependem do modo de divisão. As divisões sequenciais transportam. As divisões aleatórias e rolantes nunca transportam, mesmo quando uma escolha aleatória segue o episódio anterior, e o ambiente avisa uma vez que a definição não tem efeito nesse caso. Uma lista explícita de `episode_time_steps` só transporta quando uma janela começa exatamente na última linha da janela anterior com `'shared'`, ou na linha seguinte com `'disjoint'`. Assim, com o `'shared'` por omissão, uma lista sem intervalo, como `[(1900, 1949), (1950, 1999)]`, não transporta, enquanto `[(1900, 1949), (1949, 1999)]` transporta; com `'disjoint'`, a lista sem intervalo transporta. Só a sessão ligada através da fronteira recebe o SOC transportado em vez do SOC do calendário, no primeiro passo do novo episódio. Todas as chegadas seguintes no episódio, incluindo uma nova chegada do mesmo VE, usam o SOC de chegada do ficheiro. Uma chegada sem SOC de chegada no ficheiro mantém o SOC simulado do VE, tal como na execução única, e no passo 0 de um episódio transportado esse é o SOC transportado. Só o SOC dos VE é transportado: as baterias, o armazenamento térmico e as temperaturas interiores continuam a começar cada episódio no seu estado inicial. A definição é um compromisso. Desligada, cada episódio é independente dos anteriores, mas uma sessão que atravessa uma fronteira perde a carga que recebeu. Ligada, essa carga mantém-se, mas um episódio que continua o anterior depende do que o controlador anterior fez, pelo que os seus KPIs deixam de ser os de um episódio independente. As duas regras acima mudam em conformidade. Quando o episódio seguinte começa na última linha deste (divisões `'shared'` consecutivas), o último passo só conta uma contagem decrescente de 0, e uma sessão ainda ligada nessa linha é contada pelo episódio seguinte. Quando começa na linha seguinte (divisões `'disjoint'` consecutivas), o último passo conta uma contagem decrescente em [0, 1]. O passo 0 de um episódio que começou com SOC transportado não ignora uma sessão ligada na linha antes dele. O SOC transportado, ou o SOC simulado de uma chegada no passo 0 sem SOC no ficheiro, é o SOC inicial da sessão no novo episódio para todos os KPIs de VE: as partidas cumpridas, a viabilidade e o ganho de SOC ligado da contabilidade energética partem todos dele, pelo que a carga do episódio anterior não é contada de novo. Somadas sobre os episódios, as partidas, as partidas cumpridas e as classes de viabilidade coincidem então com a execução única, exceto numa sessão cujo SOC de chegada a execução única não consegue determinar e indica como desconhecido, que a divisão determina a partir do SOC transportado. O ganho de SOC ligado é o ganho de cada episódio: uma sessão que carrega antes da fronteira e parte depois dela não tem essa carga em nenhum dos episódios, pelo que a soma sobre os episódios é menor do que na execução única (2412 contra 6120 kWh para divisões `'shared'` 30 × 24 no dataset abaixo) e não é comparável com ela. Com `'shared'`, uma sessão chega à linha de fronteira com o mesmo SOC que numa execução única; o controlador pode ainda agir no passo 0 de forma diferente da execução única nessa linha, pelo que os totais de energia podem diferir ligeiramente. Com `'disjoint'`, a linha entre dois episódios nunca é controlada, pelo que uma sessão ligada através dela chega ao passo 0 até um passo de carregamento atrás da execução única (entre 0 e 0,086 de SOC neste dataset). Em `citylearn_challenge_2022_phase_all_plus_evs` com a BAU a partir do passo 1900, as partidas cumpridas de divisões `'disjoint'` 2 × 100 e 30 × 24 são 70 e 224, tal como na execução única, enquanto sem transporte são 70 e 168.

O SOC alvo é lido em `t`. Um alvo em (1, 100] é tratado como percentagem e dividido por 100. Um alvo fora de [0, 1] depois disso, ou em falta, é inválido.

As linhas `ev_events` e `ev_performance` só contam uma partida quando se verificam todas estas condições:
- há um VE com bateria ligado;
- o alvo é válido;
- o SOC da bateria em `t` é finito.

`ev_events_departure_count` é o número dessas partidas. As restantes linhas usam estes símbolos:

```text
s      = SOC da bateria no passo de partida (fração 0-1)
s*     = SOC alvo
tol_s  = ev_departure_service_tolerance   (por omissão 0,05, >= 0)
tol_w  = ev_departure_within_tolerance    (por omissão 0,05, >= 0)
tol_t  = min(0,005, tol_s)
eps    = 1e-6

met              : s* - s <= tol_t + eps
min_acceptable   : s + tol_s + eps >= s*
within_tolerance : |s - s*| <= tol_w + eps

deficit   = max(s* - s, 0)
shortfall = max(s* - tol_s - s, 0)
surplus   = max(s - s*, 0)
abs_error = |s - s*|
```

- **Taxas:** `ev_performance_departure_{success,min_acceptable,within_tolerance}_ratio` é o número de partidas que cumprem a condição a dividir por `ev_events_departure_count`.
- **Médias:** as linhas `*_mean_ratio` são as médias do défice, da insuficiência, do excesso e do erro absoluto sobre as mesmas partidas, em fração de SOC.
- **Valores indefinidos:** as taxas e as médias ficam indefinidas sem partidas.

`tol_t` é a tolerância de serviço do alvo do VE, 0,005 de SOC (0,5 %), guardada na constante
`EV_SERVICE_SOC_TOLERANCE` em `citylearn.electric_vehicle`. As baselines baseadas em regras param de
carregar 0,001 abaixo do alvo, pelo que os seus carros contam como tendo cumprido o alvo. Está limitada por
`tol_s`, para que met nunca exceda min_acceptable. As médias do défice, do excesso, do erro
absoluto e da insuficiência continuam exatas.

As contagens estão ordenadas: met ≤ min_acceptable ≤ partidas, e within_tolerance ≤ partidas. Met e within_tolerance não estão ordenadas entre si: um VE carregado acima da banda cumpre o alvo mas fica fora da tolerância.

### Viabilidade antiga

As linhas `ev_events_departure_{target,min_acceptable,within_tolerance}_{feasible,infeasible}_count` indicam se cada limiar podia ser atingido. Um limiar é viável quando uma simulação isolada o atinge. Os limiares são:

```text
threshold_target         = max(s* - tol_t, 0)
threshold_min_acceptable = max(s* - tol_s, 0)
threshold_within         = max(s* - tol_w, 0)
viável                   : s_simulado + eps >= limiar
```

A simulação funciona assim:
- **Início.** Parte do SOC de chegada do VE no início da sessão ligada. Esse SOC é o valor do conjunto de dados ou, na sua falta, o SOC simulado no início da sessão.
- **Carga.** Carrega à potência máxima do carregador em todos os passos ligados, através da eficiência do carregador e de uma cópia do modelo da bateria.
- **Limites de potência.** Quando o edifício impõe restrições de carregamento, a potência é limitada pela margem de importação do edifício e da fase do carregador, e é nula nos passos com corte de energia. A zona morta de potência mínima do carregador aplica-se sempre.
- **Casos permissivos.** Um limiar igual a 0 conta como viável. Também conta uma partida cuja capacidade da bateria, potência do carregador, duração do passo ou SOC de chegada falte ou seja inválido.
- **Identidade.** Em consequência, viáveis + inviáveis = `ev_events_departure_count` para cada limiar.

As linhas `ev_performance_*_feasible_ratio` dividem as partidas que cumpriram o limiar entre as viáveis pelo número de viáveis. Ficam indefinidas quando esse número é 0.

### Linha da tolerância

`ev_performance_departure_tolerance_ratio` é um eco da configuração. Reporta o parâmetro `ev_departure_service_tolerance`, com o mesmo valor em todos os edifícios e no distrito, seja qual for o resultado da simulação. Não é uma medição. O parâmetro `ev_departure_within_tolerance` não tem linha. Ambos os parâmetros constam também dos metadados do ambiente.

### Totais de carga e de V2G

Os totais são energias brutas do lado AC do carregador, somadas por carregador e por passo:

```text
ac_t = variação de energia da bateria em t / eta_c   em carga
ac_t = variação de energia da bateria em t * eta_c   em descarga   (negativa)

ev_total_charge_kwh     = soma_t max(ac_t, 0)
ev_total_v2g_export_kwh = soma_t max(-ac_t, 0)
```

`eta_c` é a eficiência do carregador.
- **Bruto:** a carga e a descarga num mesmo passo acumulam-se em separado e nunca se compensam.
- **Perdas:** o total de carga inclui as perdas do carregador.
- **Não é exportação para a rede:** o total de V2G é a energia que os VE fornecem através do carregador, seja qual for o seu uso. Não é exportação para a rede: o membro pode consumir ele próprio a energia V2G, e só a troca líquida do membro mostra o que atravessa a fronteira com a rede.
- **Alternativa:** um carregador sem registos brutos usa as partes positiva e negativa do seu consumo de eletricidade.

### Troca líquida na janela

Quando `evaluation_window.enabled` é verdadeiro, `ev_window_net_exchange_control_kwh` reporta a energia AC líquida com sinal nos carregadores dentro da janela local recorrente:

```text
ev_window_net_exchange_control_kwh = Σ_t w_t · ac_net,t
```

`w_t` é o peso de sobreposição do passo definido em [Energia da rede e forma da carga](#janela-de-avaliação-recorrente), e `ac_net,t` é o consumo elétrico AC com sinal dos carregadores ativos no passo `t` (positivo ao carregar VE, negativo ao fornecer energia V2X ao edifício ou à rede). Membros sem carregadores de VE reportam `0.0` quando `H_W > 0`. Quando `H_W = 0`, o valor fica indefinido (`NaN`). Os valores de distrito e de portefólio somam com sinal os valores dos membros e das comunidades, ficando o portefólio indefinido se alguma comunidade estiver indefinida.

### Balanço de energia

```text
connected_soc_gain_kwh = soma, nas partidas contadas, de max(s - s_chegada, 0) * C
shortfall_kwh (membro) = max(connected_soc_gain_kwh - ev_total_charge_kwh, 0)
```

- **Entradas:** `s_chegada` é o SOC de chegada usado pela simulação antiga, e `C` é a capacidade nominal da bateria, não a capacidade degradada.
- **Significado:** a insuficiência assinala ganho de SOC que a carga medida não explica.
- **Cobertura:** o total de carga cobre todos os passos da janela, incluindo sessões sem partida contada, pelo que a verificação é unilateral.

### Saúde e desgaste das baterias

Cada instância de `Battery` (armazenamento estacionário e `ElectricVehicle.battery`) expõe quatro propriedades só de leitura de saúde e desgaste: `current_state_of_health` (rácio adimensional em `[0, 1]`, `clip(degraded_capacity / capacity, 0, 1)`, devolvendo `1.0` quando `capacity <= 0` ou antes do primeiro passo), `state_of_health` (vetor `float64` de rácios adimensionais em `[0, 1]` até `time_step + 1`, devolvendo uns quando `capacity <= 0` e `[1.0]` antes do primeiro passo), `equivalent_full_cycles` (contagem adimensional de ciclos `(Σ carga + Σ descarga) / (2 · capacity)`, devolvendo `0.0` antes do primeiro passo e `0.0` quando `capacity <= 0`, enquanto os KPIs de ciclos `*_battery_health_equivalent_full_cycles_count` e `*_ev_battery_health_equivalent_full_cycles_count` ficam indefinidos quando a capacidade nominal é zero) e `capacity_fade_kwh` (capacidade acumulada perdida por degradação em `kWh`, `máx(0, capacity − degraded_capacity)`, devolvendo `0.0` quando `capacity <= 0` ou antes do primeiro passo). Os KPIs de desgaste das baterias estacionárias são reportados pela família [Baterias](#baterias).

Quando se passa `evaluate_v2(include_battery_health_audit=True)` (por omissão `False`), são emitidas quatro linhas opt-in `ev_battery_health_*` para as baterias dos VE:

```text
C_i      = capacidade nominal da bateria de VE i (> 0), em kWh
T_i      = Σ_t (carga_i,t + descarga_i,t), energia bruta aceite nos terminais da bateria em kWh
C_deg,i  = clip(capacidade degradada da bateria de VE i, 0, C_i), em kWh
perda_i  = máx(0, C_i − C_deg,i), em kWh

ev_battery_health_terminal_soh_ratio             = clip(Σ_i C_deg,i / Σ_i C_i, 0, 1)      indefinido quando Σ_i C_i ≤ 0
ev_battery_health_capacity_fade_kwh              = Σ_i perda_i                            0 quando Σ_i C_i ≤ 0
ev_battery_health_capacity_fade_ratio            = clip(Σ_i perda_i / Σ_i C_i, 0, 1)      indefinido quando Σ_i C_i ≤ 0
ev_battery_health_equivalent_full_cycles_count   = Σ_i T_i / (2 · Σ_i C_i)                indefinido quando Σ_i C_i ≤ 0
```

Ao nível do edifício, `building_ev_battery_health_*` usa apenas ligações efetivas (`past_connected_evs[t]`) e transferências executadas durante os passos ativos executados do membro (`0 ≤ t < time_step`). A energia movimentada e a perda de capacidade são atribuídas estritamente ao edifício cujo carregador executou cada transferência, `Σ C_i` conta uma única vez cada VE único (`capacity > 0`) que efetivamente se ligou nesse edifício, e `building_ev_battery_health_terminal_soh_ratio` lê a capacidade degradada de cada VE ligado no fim da sua última ligação efetiva nesse edifício. Os VE listados apenas em horários de carregadores desligados (ou apenas em passos não executados) são excluídos (`capacity_fade_kwh = 0`, rácios e ciclos indefinidos quando nenhum VE se liga efetivamente).

Como `building_ev_battery_health_terminal_soh_ratio` reflete o estado acumulado da bateria na última ligação do VE nesse edifício (incluindo o desgaste recebido noutros edifícios), enquanto `building_ev_battery_health_capacity_fade_ratio` contabiliza apenas o desgaste resultante das transferências executadas nesse edifício, o SOH do edifício pode ser inferior a `1 − building_ev_battery_health_capacity_fade_ratio` (ao passo que no distrito e no portefólio o SOH é igual a `1 − capacity_fade_ratio`). Por exemplo, quando um VE de `60 kWh` (`capacity_loss_coefficient = 1e-3`) carrega `6 kWh` em `Building_1` no passo `0` (`0.05` ciclos completos equivalentes, `0.003 kWh` de perda, rácio de perda `0.00005`, SOH terminal `59.997 / 60 = 0.99995`) e depois se liga em `Building_2` no passo `1` com `0 kWh` trocados, `Building_2` reporta `0.0` ciclos completos equivalentes, `0.0 kWh` de perda, rácio de perda `0.0` e SOH terminal `0.99995` devido ao desgaste acumulado trazido de `Building_1`. Se o mesmo VE carregar mais `6 kWh` em `Building_2` no passo `2` (degradando até `59.994 kWh`), `Building_1` mantém o SOH terminal `0.99995` da sua última ligação efetiva no passo `0`, enquanto `Building_2` passa para `59.994 / 60 = 0.99990`.

### Distrito e portefólio

**Distrito:**
- as contagens, as energias e o ganho de SOC são somas dos membros;
- as taxas e as médias são recalculadas a partir dos numeradores e denominadores somados;
- a insuficiência é a soma das insuficiências dos membros, cada uma já limitada a 0, e não o limite dos totais do distrito;
- a linha da tolerância é o valor configurado;
- as linhas opt-in `ev_battery_health_*` agregam a população da frota de VE do distrito, definida como os VE elegíveis únicos com `capacity > 0` (`electric_vehicles` em topologia estática, ou os VE que entraram em participação durante o episódio, `electric_vehicles` união com os VE suspensos, em topologia dinâmica), contando cada VE elegível uma única vez independentemente do número de edifícios onde se liga (os VE elegíveis da frota que nunca se ligam contribuem com a sua capacidade nominal com energia movimentada nula, perda nula e SOH terminal `1.0`).

**Portfolio:**
- as contagens, as energias e `portfolio_ev_battery_health_capacity_fade_kwh` somam-se;
- as taxas e as médias de partida são agregadas: ponderadas por `ev_events_departure_count` ou, nas taxas viáveis, pelo `*_feasible_count` correspondente;
- `portfolio_ev_battery_health_terminal_soh_ratio`, `portfolio_ev_battery_health_capacity_fade_ratio` e `portfolio_ev_battery_health_equivalent_full_cycles_count` são agregados pela capacidade nominal das baterias dos VE a partir dos totais de capacidade e de perda/ciclos das comunidades (indefinido quando a capacidade nominal total dos VE é zero);
- os ratios ao BAU são ratios dos totais somados;
- a linha da tolerância é a média dos parâmetros das comunidades ponderada pelo `weight` de cada comunidade.

### Que KPI usar

Para comparar controladores quanto ao serviço à partida, use os ratios da [auditoria das partidas dos VE](#auditoria-das-partidas-dos-ve), que o scorecard por omissão reporta:
- `ev_departure_audit_min_acceptable_service_feasible_ratio` para o serviço;
- `ev_departure_audit_within_tolerance_service_feasible_ratio` para a precisão face ao alvo.

Para avaliar o desgaste das baterias dos VE devido ao carregamento e ao despacho V2G, passe `include_battery_health_audit=True` e reporte `ev_battery_health_terminal_soh_ratio` e `ev_battery_health_capacity_fade_kwh` juntamente com `ev_battery_health_equivalent_full_cycles_count`.

As taxas viáveis antigas contam como viáveis as partidas com dados em falta e não reportam quantas partidas puderam ser avaliadas. Mantenha as linhas `ev_performance` por continuidade com resultados anteriores.

`ev_performance_departure_min_acceptable_ratio` e `ev_departure_audit_min_acceptable_service_observed_ratio` são iguais numa topologia estática quando todos os SOC à partida estão em [0, 1].

### Limitações conhecidas

- Como o BAU nunca usa V2G, `ev_ratio_to_business_as_usual_v2g_export_total_ratio` fica indefinido sempre que o controlador descarrega um VE.
- Com topologia dinâmica, as linhas `ev_events` contam também partidas em carregadores históricos inativos nesse passo, que a auditoria ignora.
- A simulação de viabilidade antiga só aplica os limites do edifício e das fases quando o edifício impõe restrições de carregamento.

## Auditoria das partidas dos VE

A auditoria reporta o serviço à partida com uma população explícita, e separa a viabilidade que não pôde ser avaliada da viabilidade que falhou. Todos os membros emitem as linhas. Um membro sem partidas reporta contagens 0 e ratios indefinidos. Usa a deteção de partidas, a normalização do alvo, as tolerâncias e os testes de cumprimento de [Veículos elétricos](#veículos-elétricos), aplicados a três limiares:

```text
target           : tolerância tol_t
min_acceptable   : tolerância tol_s
within_tolerance : tolerância tol_w   (teste simétrico: |s - s*| <= tol_w + eps)
```

### População

- **Partidas.** `ev_departure_audit_departures_count` conta todas as partidas detetadas, sejam ou não conhecidos o VE, a bateria, o alvo ou o SOC. Com topologia dinâmica, uma partida num carregador que não está ativo nesse passo é ignorada.
- **Serviço observado.** O serviço de uma partida é observado quando o alvo é válido e o SOC à partida é finito e está em [0, 1]. Caso contrário, é desconhecido:

```text
service_observed_count + service_unknown_count = departures_count
service_coverage_ratio = service_observed_count / departures_count
```

### Viabilidade

A auditoria atribui a cada limiar o estado viável, inviável ou desconhecido, pelo que viáveis + inviáveis + desconhecidas = partidas, para cada limiar.

**Motivos de desconhecimento.** Uma partida é desconhecida quando se aplica o primeiro pré-requisito que falha, por esta ordem:
1. missing_target;
2. missing_ev;
3. missing_battery;
4. invalid_capacity (não finita ou ≤ 0);
5. invalid_charger_power (não finita ou < 0);
6. invalid_charger_efficiency (fora de [0, 1]);
7. invalid_time_step (≤ 0);
8. missing_arrival_soc;
9. unsupported_battery_model (não é o modelo de bateria nativo);
10. invalid_battery_parameters (potência nominal < 0, ou eficiência, coeficiente de perdas ou SOC máximo fora de [0, 1]).

**Simulação.** Quando todos os pré-requisitos se verificam, uma única simulação avalia os três limiares:
- **Início.** O intervalo ligado começa no início da sessão e avança para além de qualquer passo em que este VE não estava efetivamente ligado. O SOC de chegada é o SOC de ligação da topologia ou, na sua falta, o SOC atual do conjunto de dados no início, o SOC de chegada estimado do conjunto de dados, ou o SOC inicial no passo 0. Nunca usa o histórico de SOC simulado.
- **Carga.** A simulação carrega uma cópia da bateria à potência máxima do carregador, com as mesmas margens e a mesma zona morta da regra antiga.
- **Cortes de energia.** A potência é nula em todos os passos com corte de energia.

```text
viável : s_simulado + eps >= max(s* - tolerância, 0)
```

**Desconhecido após a simulação.** Há mais dois casos que tornam um limiar desconhecido:
- invalid_battery_parameters, quando o SOC simulado não é finito;
- outage_supply_not_replayed, quando o limiar não é atingido e algum passo do intervalo teve corte de energia. A carga nula durante o corte é apenas um teste suficiente: o PV local ou o armazenamento poderiam ter abastecido o VE.

Os motivos de um limiar somam o número de desconhecidas desse limiar.

### Ratios

```text
coverage_ratio          = (viáveis + inviáveis) / partidas
service_observed_ratio  = service_met / service_observed
service_feasible_ratio  = feasible_service_met / feasible_service_observed
```

- `service_met` conta as partidas observadas que cumpriram o limiar, viáveis ou não.
- `feasible_service_observed` conta as partidas viáveis e observadas, e `feasible_service_met` conta as que, entre elas, cumpriram o limiar.
- Cada ratio fica indefinido quando o denominador é 0.

### Diferenças face às linhas antigas

| | `ev_events` / `ev_performance` | Auditoria |
|---|---|---|
| População | Partidas com VE, bateria, alvo válido e SOC finito | Todas as partidas detetadas em carregadores ativos |
| Dados em falta | Contam como viáveis | Desconhecidas, com motivo |
| Passos com corte de energia | Potência nula só com restrições de carregamento | Potência sempre nula; inviável com corte passa a desconhecida |
| Denominador da taxa viável | Todas as partidas contadas viáveis | Partidas viáveis com serviço observado |
| Cobertura | Não reportada | Ratios de cobertura do serviço e da viabilidade |

### Distrito e portefólio

**Distrito:** as contagens são somas dos membros, e os ratios são recalculados a partir das contagens somadas.

**Portfolio:**
- as contagens somam-se;
- os ratios são médias dos ratios dos distritos ponderadas pelo `weight` de cada comunidade;
- os ratios não são agregados a partir das contagens, embora os seus denominadores sejam contagens.

### Que KPI usar

Para comparar controladores, use as linhas seguintes, como no scorecard por omissão:
- `ev_departure_audit_min_acceptable_service_feasible_ratio` para o serviço;
- `ev_departure_audit_within_tolerance_service_feasible_ratio` para a precisão face ao alvo.

Reporte sempre com elas `ev_departure_audit_service_coverage_ratio`, o `coverage_ratio` do limiar e o seu número de desconhecidas. Um ratio viável elevado com cobertura baixa abrange poucas partidas. As linhas `service_observed_ratio` incluem partidas que nenhum controlador poderia ter servido.

### Limitações conhecidas

- Cada partida é simulada isoladamente, sem os outros VE que partilham os mesmos limites, pelo que a viabilidade conjunta não é testada.
- A margem usa a carga de base da própria execução, pelo que, com limites elétricos, a população viável pode diferir entre controladores no mesmo cenário.
- Os ratios do portefólio são ponderados pelo `weight` das comunidades e não agregados a partir das contagens.

## Equipamentos flexíveis

Estas linhas medem se os ciclos pedidos aos equipamentos diferíveis (flexíveis) foram executados. Usam os estados dos ciclos e as energias nominais dos ciclos. Todos os membros emitem as linhas. Um membro sem equipamentos reporta 0 nas contagens e energias, e taxas indefinidas. Com topologia dinâmica, os equipamentos removidos durante o episódio continuam a contar.

### Estados dos ciclos

Cada ciclo pedido tem um arranque mais cedo, um arranque mais tarde, um prazo, uma duração e um perfil de carga com uma energia total. Um ciclo só pode arrancar num passo entre o seu arranque mais cedo e o mais tarde, e só se terminar antes do prazo e antes do último passo do episódio.

- **Concluído:** o ciclo executou até ao último passo do perfil.
- **Falhado:** o arranque mais tarde passou com o ciclo ainda pendente, ou o ciclo estava em curso quando um corte de energia o interrompeu. Um ciclo interrompido para, e a sua energia restante é retirada.
- **Fora das duas contagens:** os ciclos cancelados por uma remoção da topologia, os ciclos ainda pendentes ou em curso no momento da avaliação, e os ciclos expirados antes do episódio ou antes de o equipamento ficar ativo.

### Equações

```text
completed  = número de ciclos concluídos
missed     = número de ciclos falhados
service_level             = completed / (completed + missed)
served_energy_total_kwh   = soma, nos ciclos concluídos, de E_c
unserved_energy_total_kwh = soma, nos ciclos falhados, de E_c
average_start_delay_hours = média, nos ciclos concluídos, de max(arranque - arranque_mais_cedo, 0) * horas_por_passo
```

- **Energia nominal.** `E_c` é a energia total pedida para o ciclo, pelo que a energia servida e a não servida são nominais, não medidas. Um ciclo interrompido por um corte de energia conta toda a sua energia como não servida, incluindo a parte consumida antes da interrupção.
- **Valores indefinidos.** O nível de serviço fica indefinido quando completed + missed = 0. O atraso de arranque fica indefinido quando nenhum ciclo foi concluído. Um delta ao BAU fica indefinido quando um dos lados o está.

**Ratios ao BAU.** Cada `deferrable_appliance_ratio_to_business_as_usual_*_ratio` divide o valor do controlo pelo valor BAU:
- fica indefinido quando os seus próprios dois totais são zero, mesmo que houvesse ciclos devidos (#305): por exemplo, o ratio de ciclos falhados de duas execuções que concluíram todos os ciclos;
- fica também indefinido quando o valor BAU é zero e o do controlo não é, ou quando um dos valores é indefinido.

É a exceção à regra de zero sobre zero das [regras comuns](#regras-comuns).

### Distrito e portefólio

**Distrito:**
- as contagens e as energias são somas dos membros;
- o nível de serviço é recalculado a partir das contagens somadas;
- o atraso de arranque é a média sobre todos os ciclos concluídos: o atraso médio de cada equipamento é ponderado pelos seus ciclos concluídos.

**Portfolio:**
- as contagens e as energias somam-se;
- o nível de serviço é agregado, ponderado pelos ciclos concluídos + falhados, tanto para o controlo como para o BAU;
- o atraso de arranque é agregado, ponderado pelos ciclos concluídos. Passa para o portefólio apesar de a unidade ser horas;
- os deltas ao BAU são calculados entre os valores agregados do controlo e do BAU;
- os ratios ao BAU são ratios dos totais somados nas contagens e energias, e ratios dos valores agregados no nível de serviço e no atraso de arranque. A regra de indefinição acima continua a aplicar-se.

### Que KPI usar

**Para avaliar o serviço,** prefira a [auditoria dos equipamentos flexíveis](#auditoria-dos-equipamentos-flexíveis). Só conta um ciclo como concluído se a sua energia foi entregue, usa energia medida e exclui pedidos que não podiam ser servidos dentro do episódio.

**Para comparar com o BAU,** use estas linhas: só elas têm variantes BAU.

**Energia:** `deferrable_appliance_audit_served_energy_kwh` é o equivalente medido de `deferrable_appliance_service_served_energy_total_kwh`.

### Limitações conhecidas

- Um ciclo que não cabe antes do fim do episódio passa a falhado quando o seu arranque mais tarde passa, para qualquer controlador.
- A energia servida e a não servida são energias nominais dos perfis, não energia medida.

## Auditoria dos equipamentos flexíveis

A auditoria reporta o serviço dos ciclos a partir da energia efetivamente consumida pelos equipamentos nos intervalos executados, com uma população explícita e estados exclusivos. Todos os membros emitem as linhas. Os pedidos são identificados por membro, equipamento e identificador de ciclo. Quando um equipamento é reinstalado, mantém-se o primeiro registo incluído de cada pedido, e cada cópia incluída adicional soma 1 a `duplicate_offered_count`.

### Atribuição de energia

Em cada passo executado `k` antes do passo terminal do episódio, a energia medida `E_k` do equipamento é repartida pelos ciclos em curso, em proporção ao valor do perfil de cada um nesse passo:

```text
served_c += E_k * w_c,k / soma_j w_j,k      (w = valor do perfil no desfasamento atual do ciclo)
physical_energy_kwh = soma_k E_k
```

Um ciclo termina quando o passo do último valor do seu perfil foi executado.

### População

Um pedido é oferecido (incluído) quando um ciclo completo podia ter arrancado num intervalo ativo executado:

```text
valid_first = max(arranque_mais_cedo, passo_de_ativação)
valid_last  = min(arranque_mais_tarde, prazo - duração + 1, passo_terminal - duração)
```

Caso contrário, é excluído com o primeiro motivo aplicável:
1. **already_accounted_previous_instance:** uma instância anterior do equipamento já ofereceu o pedido.
2. **expired_before_episode:** o arranque mais tarde é anterior ao início do episódio.
3. **expired_before_activation:** o arranque mais tarde é anterior à ativação do equipamento.
4. **outside_episode_service_horizon:** valid_first > valid_last.
5. **removed_before_available** (se o equipamento foi removido) ou **not_yet_available** (caso contrário): nenhum passo executado cai em [valid_first, valid_last].

### Estados

Cada pedido oferecido toma o primeiro estado aplicável:
1. **completed** (profile_delivered): terminado e |pedida − servida| ≤ 1e-6 · max(1, pedida).
2. **missed** (profile_energy_shortfall): terminado nos restantes casos, por exemplo após uma interrupção por corte de energia.
3. **missed** (start_window_elapsed): nunca arrancou e o arranque mais tarde já foi executado.
4. **cancelled** (asset_removed ou member_removed): o equipamento ou o membro foi removido.
5. **running** (profile_in_progress): arrancou.
6. **pending** (window_open): nenhum dos anteriores.

### Equações

```text
remanescente           = max(pedida - servida, 0)
final_unserved_energy  = remanescente dos pedidos falhados e cancelados
outstanding_energy     = remanescente dos pedidos pendentes e em curso
resolved               = completed + missed + cancelled

observed_completion_ratio = completed / offered
resolved_completion_ratio = completed / resolved
resolved_coverage_ratio   = resolved / offered

physical_balance_residual = physical_energy - served_energy
service_balance_residual  = requested - served - final_unserved - outstanding
```

- **Somas de energia.** As energias são somas sobre os pedidos oferecidos. `excluded_requested_energy_kwh` soma a energia pedida dos pedidos excluídos.
- **Resíduos.** O resíduo físico é energia medida que nenhum pedido oferecido explica. O resíduo de serviço é próximo de 0 por construção e serve de verificação de consistência.
- **Valores indefinidos.** Um ratio com denominador 0 fica indefinido.

### Distrito e portefólio

**Distrito:** todas as contagens e energias são somas dos membros, e os ratios são recalculados a partir delas.

**Portfolio:**
- as contagens e as energias somam-se;
- os ratios são médias dos ratios dos distritos ponderadas pelo `weight` de cada comunidade;
- os ratios não são agregados a partir das contagens.

### Que KPI usar

**Para comparar controladores:**
- use `deferrable_appliance_audit_resolved_completion_ratio` com `deferrable_appliance_audit_resolved_coverage_ratio`;
- ou use `observed_completion_ratio` quando os pedidos pendentes e em curso no fim do episódio devam penalizar o controlador.

As linhas de serviço de [Equipamentos flexíveis](#equipamentos-flexíveis) contam como falhados os pedidos excluídos que expiraram dentro do episódio, e usam energia nominal.

### Limitações conhecidas

- A energia do passo terminal não é registada: a observação terminal não é um intervalo executado.
- Os ratios do portefólio são ponderados pelo `weight` das comunidades e não agregados a partir das contagens.

## Escadas rolantes

Estas linhas medem o serviço aos passageiros, as mudanças de estado de funcionamento e o consumo de eletricidade das escadas rolantes. Todos os membros emitem as linhas. Um membro sem escadas rolantes reporta totais 0 e um nível de serviço indefinido. Só contam os passos em que foi aplicada uma ação à escada. As linhas leem as escadas rolantes associadas a cada edifício no momento da avaliação.

### Equações

Uma escada rolante funciona em standby, lento ou normal. Em cada passo contado `t`:

```text
p_t        = max(passengers_expected_15min_t, 0)
required_t = p_t > service_threshold_passengers           (por omissão 0,5)
met_t      = não required_t ou (estado_t em {lento, normal} e disponível_t)
unserved_t = p_t se não met_t, caso contrário 0

requested_passengers_total = soma_t p_t
unserved_passengers_total  = soma_t unserved_t
served_passengers_total    = max(requested - unserved, 0)
service_level              = served / requested
```

- **Sem reescalonamento.** Os valores de passageiros são somados tal como são dados, sem reescalonamento para a duração do passo.
- **Abaixo do limiar.** Os passageiros iguais ou inferiores ao limiar contam como servidos em qualquer estado.
- **Valores indefinidos.** O nível de serviço fica indefinido quando requested ≤ 0.

As outras duas linhas são as seguintes:
- `escalator_energy_electricity_consumption_total_kwh` soma o consumo de eletricidade da escada, que é a potência do estado aplicado vezes a duração do passo.
- `escalator_operation_state_changes_count` conta os passos em que o estado aplicado mudou. A mudança só acontece depois do tempo mínimo de permanência, ou quando a escada é forçada para standby por estar indisponível.

### Distrito e portefólio

**Distrito:** os totais são somas das escadas e dos membros, e o nível de serviço é recalculado a partir dos passageiros somados.

**Portfolio:** os totais somam-se, e o nível de serviço é agregado, ponderado pelos passageiros pedidos.

### Limitações conhecidas

- Um valor de passageiros não finito torna o total pedido não finito, enquanto o teste de serviço por passo o trata como 0.
- Com topologia dinâmica, as linhas usam apenas as escadas rolantes associadas no momento da avaliação.

## Conforto e resiliência

As linhas `comfort_resilience` medem, por edifício, o conforto térmico dos ocupantes e o serviço perdido
durante cortes de energia. São sempre emitidas. Mantêm as definições das funções de custo legadas de
`evaluate()` (`discomfort_*`, `one_minus_thermal_resilience_proportion`,
`*_normalized_unserved_energy_total`), para que os valores continuem comparáveis com versões anteriores.
Para comparar controladores, use antes a [auditoria do serviço térmico](#auditoria-do-serviço-térmico)
(ver a escolha canónica abaixo). As unidades, os nomes e o tratamento de valores indefinidos seguem as
[regras comuns](#regras-comuns). Nenhuma destas linhas tem variante business-as-usual.

**Banda de conforto e passos.** Todas as séries abrangem os passos executados do edifício:

```text
T_t       temperatura interior de bolbo seco                           [degC]
T_heat,t  ponto de consigna de aquecimento,  T_cool,t  de arrefecimento [degC]
banda_t   banda de conforto: a série comfort_band do edifício (coluna comfort_band do conjunto de
          dados, 2.0 degC quando ausente), ou o argumento comfort_band de evaluate_v2(), que a substitui
N_t       número de ocupantes
corte_t   sinal de corte de energia

avaliado_t = N_t finito e N_t > 0
             e T_t, T_heat,t, T_cool,t, banda_t finitos
             e banda_t >= 0 e T_heat,t <= T_cool,t
frio_t     = avaliado_t e T_t < T_heat,t - banda_t
quente_t   = avaliado_t e T_t > T_cool,t + banda_t
```

Só os passos ocupados são avaliados. Um passo é confortável quando
`T_heat - banda <= T <= T_cool + banda`.

**Edifícios sem set points.** Quando o dataset de um edifício não tem a coluna
`indoor_dry_bulb_temperature_cooling_set_point` ou a coluna
`indoor_dry_bulb_temperature_heating_set_point`, a simulação e as observações usam um set point de 0 °C.
Os KPIs de conforto não avaliam o conforto contra esse valor por omissão: leem `T_heat` e `T_cool` como
indefinidos, pelo que nenhum passo do edifício é avaliado. Todas as razões, deltas e razões de falha de
energia do desconforto desse edifício ficam então indefinidas, no `evaluate_v2()`, no `evaluate()` e na
auditoria do serviço térmico, e o distrito ignora o
edifício. Entre os datasets incluídos, os `pt_rec_*` não têm colunas de set points e têm ocupantes, pelo
que os seus KPIs de conforto ficam indefinidos. Os datasets dos desafios de 2020 a 2022 e as demos
trifásicas também não têm colunas de set points, mas os seus edifícios não têm ocupantes, pelo que os
seus KPIs de conforto já eram indefinidos.

**Razões de desconforto.**

```text
discomfort_overall_ratio = contagem(frio ou quente) / contagem(avaliado)
discomfort_cold_ratio    = contagem(frio)           / contagem(avaliado)
discomfort_hot_ratio     = contagem(quente)         / contagem(avaliado)
```

São indefinidas quando nenhum passo é avaliado.

**Desvios de desconforto.** Os desvios são distâncias ao ponto de consigna, e não ao limite da banda.
Ambos são positivos, e cada desvio é maior do que a banda:

```text
desvio frio_t   = T_heat,t - T_t   nos passos frios     (> banda_t > 0)
desvio quente_t = T_t - T_cool,t   nos passos quentes   (> banda_t > 0)
discomfort_{cold,hot}_delta_{min,max,average}_c = mínimo, máximo e média do desvio nesses passos
```

São indefinidos quando não há passos frios (ou quentes).

**Variantes de corte.**

```text
passo de corte_t = corte_t finito e corte_t > 0
one_minus_thermal_ratio = contagem(avaliado e passo de corte e (frio ou quente))
                        / contagem(avaliado e passo de corte)
```

É indefinida quando nenhum passo ocupado com corte é avaliado.

As razões de energia não servida abrangem quatro usos finais: i = arrefecimento, aquecimento, águas quentes
sanitárias (AQS) e carga não deslocável. Para o uso final i, `e_i,t` é a energia esperada (a procura) e
`s_i,t` a energia servida (pelo equipamento e pelo armazenamento), em kWh:

```text
E_t = soma_i e_i,t
S_t = soma_i min(e_i,t, s_i,t)         (servir um uso final nunca compensa a falta noutro)
E_t, S_t := 0 quando não finitos; ambos truncados em 0
U_t = max(E_t - S_t, 0)

unserved_energy_annual_normalized_ratio = soma_t U_t / soma_t E_t
unserved_energy_outage_normalized_ratio = soma_{corte_t != 0} U_t / soma_{corte_t != 0} E_t
```

Ambas as razões valem 0, e não indefinido, quando o denominador é 0. A razão de corte é, por isso, 0 em
qualquer corrida sem cortes.

**Distrito e portefólio.** O valor do distrito de cada linha `comfort_resilience` é a média simples dos
valores dos edifícios; os edifícios com valor indefinido são ignorados. Cada edifício conta uma vez,
qualquer que seja o seu número de passos ocupados. O desvio `max` do distrito é, por isso, a média dos
máximos dos edifícios, e não o maior desvio do distrito. No portefólio, as razões são médias dos valores
das comunidades ponderadas pelo peso (`weight`) de cada comunidade, e os desvios `_c` não passam ao
portefólio.

**Escolha canónica.** Por edifício, `comfort_resilience_discomfort_overall_ratio` e
`thermal_service_audit_discomfort_ratio` são iguais. O mesmo acontece com `resilience_one_minus_thermal_ratio`
e `thermal_service_audit_outage_discomfort_ratio`. No distrito diferem: aqui é a média das razões dos
edifícios, ali a razão das contagens somadas. O KPI de desconforto canónico é
`district_thermal_service_audit_discomfort_ratio`. As linhas `comfort_resilience` continuam úteis para
manter a continuidade com resultados legados e para os desvios mínimo, máximo e médio, que a auditoria não
fornece.

Limitações conhecidas:
- Um edifício com poucos passos ocupados pesa tanto na média do distrito como um edifício sempre ocupado.
- As razões de energia não servida valem 0 quando não havia energia de serviço esperada, o que não se distingue de um serviço completo.
- Um intervalo com energia servida inválida conta aqui como não servido, mas fica de fora da auditoria.

## Auditoria do serviço térmico

As linhas `thermal_service_audit` reportam o conforto térmico e a energia de serviço de cada edifício.
Junto de cada taxa publicam as contagens que a originam, para que se possa verificar a população e a sua
cobertura. São sempre emitidas. Usam a banda de conforto, os passos ocupados avaliados e as condições de frio
e de calor de [Conforto e resiliência](#conforto-e-resiliência). As unidades e os valores indefinidos seguem
as [regras comuns](#regras-comuns). Nenhuma destas linhas tem variante business-as-usual.

**Intervalos.** A auditoria conta os intervalos executados de cada edifício (`executed`). Em topologias
dinâmicas, conta apenas os intervalos em que o edifício esteve ativo.

```text
ocupação conhecida_t = N_t finito e N_t >= 0
ocupado_t            = ocupação conhecida_t e N_t > 0
avaliado_t           = ocupado_t e termicamente conhecido (como em Conforto e resiliência)
excluído_t           = ocupado_t e não avaliado_t
corte_t              = sinal de corte finito e > 0
corte desconhecido_t = sinal de corte não finito ou < 0
energia avaliada_t   = e_i,t e s_i,t finitos e >= 0 nos quatro usos finais
```

As linhas `*_intervals_count` contam estes intervalos. Os intervalos com desconforto são `frio ou quente`.
As contagens de corte combinam a condição de corte com os intervalos ocupados, avaliados e com
desconforto. `occupied_hours`, `evaluated_occupied_hours` e `discomfort_hours` são as contagens
correspondentes multiplicadas pela duração do passo `dt`, em horas.

**Graus-hora.** Medem-se a partir do ponto de consigna, como os desvios de conforto:

```text
cold_degree_hours = dt * soma_{t frio}   (T_heat,t - T_t)        [degC·h]
hot_degree_hours  = dt * soma_{t quente} (T_t - T_cool,t)        [degC·h]
```

**Energia de serviço.** Usa os mesmos quatro usos finais das razões de energia não servida. Um intervalo
sem energia avaliada não contribui para nenhum total.

```text
expected_service_energy_kwh = soma_{t com energia avaliada} soma_i e_i,t
served_service_energy_kwh   = soma_{t com energia avaliada} soma_i s_i,t               (não limitada à procura)
unserved_service_energy_kwh = soma_{t com energia avaliada} soma_i max(e_i,t - s_i,t, 0)
outage_expected_service_energy_kwh, outage_unserved_service_energy_kwh: o mesmo nos intervalos de corte
```

**Razões.** Cada razão é `numerador / denominador`, indefinida (nunca 0 ou 1) quando o denominador é 0:

```text
discomfort_ratio               = intervalos com desconforto              / intervalos ocupados avaliados
outage_discomfort_ratio        = intervalos de corte com desconforto     / intervalos de corte ocupados avaliados
thermal_coverage_ratio         = intervalos ocupados avaliados           / intervalos ocupados
outage_thermal_coverage_ratio  = intervalos de corte ocupados avaliados  / intervalos de corte ocupados
occupancy_coverage_ratio       = intervalos com ocupação conhecida       / intervalos executados
energy_coverage_ratio          = intervalos com energia avaliada         / intervalos executados
unserved_service_ratio         = unserved_service_energy_kwh        / expected_service_energy_kwh
outage_unserved_service_ratio  = outage_unserved_service_energy_kwh / outage_expected_service_energy_kwh
```

**Distrito e portefólio.** O distrito soma todas as contagens, horas e kWh dos edifícios e recalcula cada
razão a partir das somas. Por exemplo:

```text
discomfort_ratio do distrito = soma_b intervalos com desconforto_b / soma_b intervalos ocupados avaliados_b
```

É uma taxa ponderada pela exposição ocupada. No portefólio, as linhas `_count` e `_kwh` são somadas entre
comunidades. As linhas `_hours` e `_degree_hours` não passam ao portefólio. As razões são médias das razões
das comunidades ponderadas pelo peso (`weight`) de cada comunidade; não são recalculadas a partir das
contagens somadas do portefólio. Obtém-se uma taxa agregada do portefólio dividindo as contagens somadas,
por exemplo
`portfolio_thermal_service_audit_discomfort_intervals_count / portfolio_thermal_service_audit_evaluated_occupied_intervals_count`.

**Escolha canónica.** `district_thermal_service_audit_discomfort_ratio` é o KPI de desconforto canónico
para comparar controladores, por quatro razões:
- É a fração do tempo ocupado e avaliado com desconforto, pelo que os edifícios raramente ocupados não a dominam.
- É indefinido, e nunca um 0 artificial, quando nada pôde ser avaliado.
- O numerador, o denominador e a cobertura são publicados com ele.
- Faz parte do scorecard por omissão.

Reporte-o com `thermal_coverage_ratio` e `evaluated_occupied_intervals_count`, e use os graus-hora de frio
e de calor para a severidade. Pelos mesmos motivos, prefira `outage_discomfort_ratio` a
`resilience_one_minus_thermal_ratio`, e `unserved_service_ratio` às razões legadas de energia não servida.

Limitações conhecidas:
- As razões do portefólio são médias ponderadas pelo peso das razões das comunidades, e não razões das contagens somadas do portefólio.
- Os graus-hora e as condições de conforto não consideram se havia aquecimento ou arrefecimento disponível (modo AVAC).

## Equidade

As linhas `equity` medem como se reparte entre os edifícios o benefício de custo do controlador. São sempre
emitidas. O benefício de cada edifício está ao nível do edifício. A sua distribuição (Gini, fração dos 20 %
com maior benefício, perdedores, razão de paridade de benefício) está ao nível do distrito. As unidades e os
valores indefinidos seguem as [regras comuns](#regras-comuns).

**Benefício relativo.** Para o edifício b:

```text
C_b = soma, nos passos executados, do custo do edifício com controlo                  [EUR]
B_b = o mesmo na condição de avaliação de referência convencional                      [EUR]
      (por omissão: sem armazenamento, com PV; nos edifícios com dinâmica térmica, também sem
       controlo de carga parcial). É a referência contrafactual, e não a corrida BAU.

benefício_b = 100 * (B_b - C_b) / B_b        [percent]; indefinido quando B_b <= 0
```

Sem o mercado comunitário, o custo de cada passo é `preço_t * max(net_t, 0)`: as importações são pagas e as
exportações não geram receita. Com o mercado ativo, C_b e B_b são ambos liquidados com as regras do mercado:
as importações da rede e locais são pagas, e as exportações locais e para a rede geram receita. As poupanças
da troca local não são, por isso, creditadas ao controlador, e um custo total pode ser negativo. Os totais
nunca são truncados. Os passos com custo não finito contam 0. A série de referência não troca energia com a
rede nos passos de corte, pelo que o seu custo é 0 nesses passos.

**Distribuição.** Seja E o conjunto dos edifícios com benefício definido, n = |E|, e
`x_b = max(benefício_b, 0)`. Os edifícios que perdem dinheiro entram no Gini e na fração dos 20 % com 0.

```text
losers_percent = 100 * contagem(b em E com benefício_b < 0) / n                (indefinido se n = 0)
gini_benefit   = soma_{b em E} soma_{c em E} |x_b - x_c| / (2 * n * soma_{b em E} x_b)
top20_benefit  = (soma dos k maiores x_b) / soma_{b em E} x_b,  k = max(1, ceil(0.2 * n))
```

O coeficiente de Gini e a fração dos 20 % são indefinidos quando n = 0 ou quando a soma de x é 0. A
percentagem de perdedores continua definida no segundo caso.

**Razão de paridade de benefício.**

```text
bpr_asset_poor_over_rich = média_{b em E, asset_poor} x_b / média_{b em E, asset_rich} x_b
```

Todos os edifícios têm de ter o campo de esquema `equity_group` com o valor `asset_rich` ou `asset_poor`.
Caso contrário, a razão é indefinida. Também é indefinida quando um dos grupos não tem edifícios em E, ou
quando a média `asset_rich` é 0.

**Distrito e portefólio.** As linhas de distribuição são calculadas a partir dos benefícios dos edifícios do
distrito. No portefólio, são médias dos valores das comunidades ponderadas pelo peso (`weight`) de cada
comunidade. O Gini do portefólio não é, por isso, o Gini de todos os edifícios do portefólio.

**Escolha canónica.** `equity_distribution_gini_benefit_ratio` é igual a
`district_equity_audit_positive_benefit_gini_ratio`: ambos usam os mesmos custos, os mesmos edifícios
elegíveis e a mesma truncagem. O KPI de Gini canónico é a linha da [auditoria de equidade](#auditoria-de-equidade).
As linhas `equity` continuam úteis para o benefício relativo de cada edifício e para a razão de paridade de
benefício, que a auditoria não fornece.

Limitações conhecidas:
- A truncagem em 0 esconde as perdas no Gini; leia-o com a percentagem de perdedores.
- O benefício é relativo à referência convencional, e não à corrida BAU.

## Auditoria de equidade

As linhas `equity_audit` repetem a distribuição de equidade do distrito, acompanhada da população sobre a
qual foi calculada. São sempre emitidas, ao nível do distrito. O benefício relativo, a regra de
elegibilidade e a truncagem são os de [Equidade](#equidade). As unidades e os valores indefinidos seguem as
[regras comuns](#regras-comuns).

```text
population_members_count             = número de edifícios do KPI
eligible_members_count               = n = edifícios com custos finitos e B_b > 0
excluded_nonpositive_reference_count = edifícios com B_b <= 0
excluded_unknown_cost_count          = edifícios com custo total não finito
coverage_ratio                       = n / population_members_count     (indefinido sem edifícios)
losers_percent                       = 100 * contagem(b elegível com benefício_b < 0) / n   (indefinido se n = 0)
positive_benefit_gini_ratio          = soma_{i=1..n} (2i - n - 1) * x_(i) / (n * soma x)
positive_benefit_top20_ratio         = (soma dos k maiores x) / soma x,  k = max(1, ceil(0.2 * n))
```

Na fórmula do Gini, `x_(1) <= ... <= x_(n)` são os benefícios truncados por ordem crescente. Esta forma é
igual à fórmula por pares de [Equidade](#equidade). O coeficiente de Gini e a fração dos 20 % são
indefinidos quando a soma de x é 0. As condições de avaliação usadas em cada edifício ficam guardadas nos
metadados `kpi_family_audit` da tabela devolvida.

**Portefólio.** As linhas `_count` são somadas entre comunidades. A razão e a percentagem são médias
ponderadas pelo peso (`weight`) de cada comunidade; não são recalculadas a partir das contagens somadas.

**Escolha canónica.** `district_equity_audit_positive_benefit_gini_ratio` é o KPI de Gini canónico para
comparar controladores. Tem o mesmo valor que `equity_distribution_gini_benefit_ratio`. O seu nome indica
que as perdas são truncadas em 0, e as contagens de elegibilidade são publicadas com ele, pelo que se
reconhece um Gini calculado sobre poucos edifícios. Reporte-o com `losers_percent`,
`eligible_members_count` e `coverage_ratio`.

Limitações conhecidas:
- Os custos de passo não finitos são somados como 0, pelo que `excluded_unknown_cost_count` é sempre 0.
- A cobertura e o Gini do portefólio são médias ponderadas pelo peso dos valores das comunidades.

## Demand response

O demand response mede como o distrito segue os pedidos do dataset em `demand_response.requests_file`, e liquida receitas e penalizações. As linhas aparecem quando `demand_response.enabled` é verdadeiro, o que exige a interface entity. Os pedidos não se podem sobrepor.

Um pedido está ativo no passo local t quando `start_time_step <= episode_start + t <= end_time_step`. Cada passo ativo é liquidado depois da atualização física desse passo.

Baseline de um pedido que começa no passo local s (fixa depois de calculada):

```text
h          = seconds_per_time_step / 3600
w          = max(1, ceil(baseline_window_seconds / seconds_per_time_step))     (3600 s por omissão)
P_base,i   = média(n_i nos passos locais s-w .. s-1) / h       (kW, membro i)
P_base     = soma_i P_base,i
```

Os membros são os ativos quando a baseline é calculada pela primeira vez. A baseline é inválida num passo por um de quatro motivos:
- `insufficient_history`: o pedido começa antes do episódio, ou `s - w < 0`;
- `nonfinite_history`: o consumo líquido de um membro na janela falta ou não é finito;
- `no_members`: não há membros ativos;
- `topology_changed`: com topologia dinâmica, a versão da topologia muda entre `s - w` e o passo atual. Todos os passos seguintes desse pedido ficam então também inválidos.

Liquidação num passo ativo t, com `target` e `tolerance` em kW, do pedido:

```text
R_t = target * h                                     energia pedida (todos os passos ativos)
V_t = R_t se a baseline for válida, senão 0          energia pedida válida
P_t = consumo líquido do distrito em t / h
d_t = P_t - P_base   (direção up)    ou   P_base - P_t   (direção down)
D_t = d_t * h                                        entregue, com sinal, sem limite
C_t = min(max(d_t, 0), target) * h                   creditada
S_t = max(target - d_t - tolerance, 0) * h           défice
receita_t      = C_t * activation_price_eur_per_kwh
penalização_t  = S_t * shortfall_penalty_eur_per_kwh
```

A energia creditada está limitada ao alvo. A tolerância aplica-se só ao défice, não ao crédito. Num passo com baseline inválida, V, D, C, S, a receita e a penalização valem 0, mas R continua a contar. Os totais somam estes valores pelos passos ativos; um valor não finito conta como 0.

Taxa de cumprimento:

```text
compliance = clip(soma_t C_t / soma_t V_t, 0, 1)      indefinida se soma_t V_t <= 1e-12
```

No distrito o limite nunca atua, porque `C_t <= R_t = V_t` em cada passo válido.

Membros. Em cada passo ativo, a liquidação do distrito é repartida pelos n membros ativos. Seja `c_i = P_i - P_base,i` para um pedido up e `P_base,i - P_i` para um pedido down, com `P_i` a potência líquida do membro (um valor não finito conta como 0).

```text
pedida_i, pedida válida_i = R_t / n, V_t / n
entregue_i                = c_i * h
w+_i = max(c_i,0) / soma_j max(c_j,0)          (1/n se essa soma <= 1e-12)
w-_i = max(-c_i,0) / soma_j max(-c_j,0);  senão |P_base,i| / soma_j |P_base,j|;  senão 1/n
creditada_i = C_t * w+_i     receita_i = receita_t * w+_i
défice_i    = S_t * w-_i     penalização_i = penalização_t * w-_i
contribuição sem limite_i = max(c_i, 0) * h
cumprimento do edifício = clip(soma creditada_i / soma pedida válida_i, 0, 1)
```

A energia pedida, entregue, creditada e em défice, a receita, a penalização e a receita líquida dos membros somam os valores do distrito. As contagens não somam: um edifício conta cada evento e cada passo ativo ou inválido em que era membro. A contribuição sem limite é um diagnóstico só de edifício e não soma para nada. A energia pedida válida e a energia creditada só são emitidas ao nível do distrito; são as componentes aditivas da taxa de cumprimento.

Portefólio:
- A energia, os valores monetários e as contagens são somados pelas comunidades. Um identificador de pedido usado em duas comunidades conta duas vezes.
- A taxa de cumprimento é agregada com o peso `valid_requested_total_kwh` (#312), por isso o valor do portefólio é a energia creditada somada sobre a energia pedida válida somada.
- As linhas de edifício não passam para o portefólio.

Que KPI usar:
- Para o desempenho, use a taxa de cumprimento do distrito; para a parte económica, `net_revenue_total_eur`.
- Para saber que parte do pedido pôde ser avaliada, use os rácios de cobertura da [auditoria de demand response](#auditoria-de-demand-response).
- O cumprimento de um edifício é a parte creditada do membro sobre a sua parte igual do pedido, limitada a 1. Todos os membros que entregaram mais do que a sua parte igual valem por isso 1. Para comparar o desvio próprio dos membros, use `uncapped_contribution_total_kwh`.

Limitações conhecidas:
- A baseline é medida na própria simulação controlada. Um controlador que altera o consumo antes de um evento altera também a sua baseline.
- Com membros estáveis, a média do cumprimento dos edifícios não pode exceder a do distrito. Com topologia dinâmica, este limite não se verifica, porque os membros têm energia pedida válida diferente.
- Se o consumo líquido do distrito não for finito num passo ativo, a energia entregue, creditada e em défice e os valores monetários contam como 0, mas a energia pedida válida continua a contar.

## Auditoria de demand response

A auditoria separa a liquidação de demand response do distrito pelo propósito declarado de cada pedido. O propósito vem de `demand_response.request_purposes`, senão da coluna `purpose` do ficheiro de pedidos, senão é `unspecified`. Nunca é inferido do desempenho. As linhas aparecem quando o demand response está ativo, para `all` e para cada um de `service`, `stress` e `unspecified`, mesmo um propósito sem pedidos. São só de distrito.

Para um propósito, seja A o seu conjunto de passos liquidados (todos os passos liquidados para `all`). Todas as grandezas por passo são as de [Demand response](#demand-response).

```text
requested, valid_requested, delivered, credited, shortfall = soma em A de R_t, V_t, D_t, C_t, S_t
revenue, penalty, net_revenue                              = soma em A
events_count            = número de identificadores de pedido distintos em A
active_intervals        = |A|
valid_intervals         = número de passos de A com baseline válida
excluded_<motivo>       = número de passos de A cuja baseline é inválida por <motivo>
baseline_coverage       = valid_intervals / active_intervals         indefinida se |A| = 0
requested_energy_coverage = valid_requested / requested              indefinida se requested <= 0
compliance              = clip(credited / valid_requested, 0, 1)     indefinida se valid_requested <= 0
```

As quatro contagens `excluded_*` somam `active_intervals - valid_intervals`. Para `all`, os totais são iguais às linhas de demand response do distrito: `active_intervals` é igual à contagem de passos ativos, e `active - valid` à contagem de passos com baseline inválida.

Portefólio:
- As contagens, a energia e os valores monetários são somados.
- Os três rácios são agregados (#312), por isso cada valor do portefólio é o rácio dos totais somados:
  - o cumprimento com o peso `valid_requested_kwh`;
  - a cobertura da energia pedida com o peso `requested_kwh`;
  - a cobertura da baseline com o peso `active_intervals_count`.

Que KPI usar: o cumprimento de `all` repete `district_demand_response_compliance_ratio`, exceto no limiar de zero. Use a auditoria para a separação por propósito e para as contagens de cobertura e de exclusão.

Limitações conhecidas:
- O cumprimento da auditoria só fica indefinido quando a energia pedida válida é exatamente 0, enquanto a taxa de cumprimento principal usa o limiar 1e-12.
- Não existe auditoria ao nível do edifício.

## Robustez

A robustez conta as perturbações que os eventos do dataset aplicam a observações, previsões, ações e ativos. As linhas aparecem quando `robustness.enabled` é verdadeiro. A corrupção de observações e de previsões só altera o que o agente vê. Os eventos de ações e de ativos alteram a ação aplicada e, por isso, a física e os restantes KPI.

Cada aplicação é registada num passo global k (início do episódio mais o passo local), com uma chave:
- `evento:tipo:alvo` para aplicações a observações, previsões e ações;
- `evento:asset:ativo` para uma aplicação a um ativo, pelo que um ativo conta uma vez por passo, independentemente de quantos campos e portas oculta.

Cada chave conta uma vez por passo. Seja K_k(tipo) o conjunto de chaves de um tipo registadas no passo k.

```text
contagem de corrupções (tipo)  = soma_k |K_k(tipo)|          tipo = observation, forecast, action
asset_unavailable_time_step    = soma_k |K_k(asset)|
missing_observation            = soma_k |K_k(missing)|       modo missing, mais aplicações a observações de eventos de ativos
action_dropout                 = soma_k |K_k(dropout)|       modo dropout, mais aplicações a ações de eventos de ativos
active_time_step (distrito)    = número de k com alguma chave observation, forecast, action ou asset
events_count                   = número de identificadores de evento distintos com pelo menos uma aplicação
```

As linhas de edifício contam só as aplicações atribuídas a esse edifício. Os seus passos ativos são os passos com pelo menos uma dessas aplicações. As linhas de distrito contam todas as aplicações, incluindo as que não têm edifício. Por isso, os valores dos edifícios podem não somar o valor do distrito.

A população contada inclui:
- todas as observações consultadas, incluindo a observação terminal depois do último passo executado;
- aplicações que o contrato de observação com falhas ocultas mascara depois.

As contagens restritas aos intervalos executados só são reportadas nos metadados `robustness_audit` do resultado de `evaluate_v2()` (`attrs['robustness_audit']['executed_intervals']`).

Portefólio: todas as linhas terminam em `_count` e são somadas pelas comunidades.

Que KPI usar:
- `asset_unavailable_time_step_count` mede a duração das indisponibilidades, em passos por ativo.
- `missing_observation_count` e `action_dropout_count` sobrepõem-se às contagens de corrupções: são subconjuntos por modo, não eventos adicionais.

Limitações conhecidas:
- Os contadores incluem a observação terminal, por isso podem exceder o número de passos executados.
- As contagens são feitas antes do mascaramento.

## Proveniência da energia

O registo de proveniência da energia segue a eletricidade desde o local de onde veio (a sua **origem**) até ao local onde terminou (o seu **destino**), juntamente com o carbono da rede que transporta. Responde a perguntas a que a importação e a exportação líquidas, por si só, não respondem. Quanta energia FV chegou a um consumo? Quanta passou primeiro por uma bateria? Quanta saiu num VE? Para onde foi o carbono comprado à rede?

As linhas `*_energy_provenance_*` aparecem em `evaluate_v2()` sempre que o ambiente mantém o registo. É o comportamento por omissão: `CityLearnEnv(energy_provenance=True)`. Com `energy_provenance=False` não é emitida nenhuma linha; a física simulada é a mesma nos dois casos. O registo é passivo: lê a simulação executada e nunca a altera. Os totais abrangem todos os intervalos simulados desde `reset()`. Não dependem dos argumentos `control_condition` nem `baseline_condition` de `evaluate_v2()`. As linhas BAU vêm da simulação BAU nativa, que mantém o mesmo registo. As regras de `_business_as_usual` e `_delta_to_business_as_usual` estão nas [regras comuns](#regras-comuns). A família não tem linhas `ratio_to_business_as_usual`.

### Fronteira e mistura

O registo tem dois tipos de nós:

- **Barramentos dos membros.** O barramento elétrico de cada membro ativo (edifício) em cada intervalo.
- **Armazenamentos.** Cada bateria estacionária com capacidade positiva, e cada bateria de VE enquanto está ligada a um carregador.

O armazenamento térmico não é um armazenamento do registo: a eletricidade usada para aquecimento ou arrefecimento, incluindo a que carrega depósitos térmicos, faz parte do consumo do membro.

Cada nó guarda quantos kWh contém de cada origem e quanto carbono transportam. Duas regras movem a energia no registo:

- **Mistura no barramento.** Dentro de um intervalo, cada barramento está perfeitamente misturado. Cada kWh que sai do barramento tem a mesma composição de origens que o barramento no seu conjunto.
- **Armazenamento proporcional.** A energia que sai de um armazenamento leva uma parte proporcional de cada origem presente, e não pela ordem de entrada. As operações de armazenamento são aplicadas pela ordem em que ocorreram no intervalo.

### Origens

| Origem | Significado | Carbono |
|---|---|---|
| `pv` | Energia FV produzida por um membro. | 0 |
| `grid` | Importação da rede de um membro após a partilha local. As linhas `grid_*` incluem também a importação de carbono desconhecido. | Importação × intensidade carbónica do membro nesse intervalo |
| `unknown` | Energia armazenada cuja história o registo não viu (ver abaixo). | 0 |

A importação da rede num intervalo com intensidade carbónica não finita é guardada como uma origem separada, com carbono nulo. Conta nas linhas de energia `grid_*`, em `external_purchase_unknown_carbon_kwh` e nas linhas `carbon_unknown_*`.

**Energia desconhecida.** A energia é desconhecida quando o registo a encontra pela primeira vez dentro de um armazenamento, em vez de a ver entrar. Isto acontece em dois casos:

- **Armazenamentos novos.** Quando o registo encontra um armazenamento pela primeira vez, a energia nele contida entra como `unknown`. Isto abrange cada bateria no reset, uma bateria que surge a meio do episódio e **cada VE no momento da ligação**: todo o estado de carga à chegada é energia desconhecida.
- **Estados de carga impostos.** Por vezes o estado de carga é definido de fora da simulação: o estado de carga à chegada de um VE vindo dos dados, a deriva de um VE ligado mas suspenso, ou uma bateria ativada por uma alteração de topologia. A energia então armazenada sai como `external_reset`, e o novo conteúdo entra como `unknown`.

A energia desconhecida não transporta carbono e nunca conta como FV, mesmo que historicamente fosse renovável. `unknown_input_kwh` é o total que entrou desta forma.

### Destinos

As linhas de destino são contadas pelo **membro que recebe** a energia, seja quem for que a produziu.

| Destino | Significado |
|---|---|
| `load` | Consumo de eletricidade do membro, excluindo o carregamento de baterias estacionárias e de VE. |
| `stored` | Energia ainda armazenada no membro quando `evaluate_v2()` é executado. |
| `mobility` | Conteúdo da bateria de um VE que se desligou de um carregador que continua num edifício ativo. É energia que saiu com o veículo, não uma estimativa da energia usada na condução. |
| `grid_export` | Exportação para a rede após a partilha local. |
| `loss` | Perdas de conversão de baterias e carregadores na carga e na descarga, e perdas em repouso. |
| `asset_exit` | Conteúdo de um armazenamento que saiu da fronteira de outra forma: bateria removida ou com capacidade nula, carregador ou membro removido, ou VE que passou para outro membro. |
| `external_reset` | Conteúdo substituído por um estado de carga imposto. |
| `curtailment` | Energia FV que não pôde ser usada durante um corte de energia. Só a energia FV é cortada, pelo que as linhas `grid_curtailment`, `unknown_curtailment` e `carbon_curtailment` valem sempre 0. |

As transferências locais entre membros não são destinos. `local_import_kwh` e `local_export_kwh`, com as suas parcelas `pv_` e `grid_`, mostram o que cada membro recebeu dos outros ou lhes enviou no mesmo intervalo. Essa energia volta a ser contada nos destinos do membro que a recebe. Não existe parcela `unknown_` nas transferências locais.

### Um intervalo

Para o membro `m` no intervalo `t`:

```text
pv_generated(m,t) = max(-solar_generation(m,t), 0)
pv_bus(m,t)       = max(pv_generated(m,t) - curtailment(m,t), 0)
grid_in(m,t)      = max(net(m,t), 0) - local_in(m,t)
supply(m,t)       = pv_bus + discharge + max(net, 0)
load(m,t)         = max(net + pv_bus + discharge - charge, 0)
mix(m,t)          = known(m,t) / (supply - recycle)
```

- `net` é o consumo líquido de eletricidade do membro.
- `pv_generated` inclui a parte cortada.
- `charge` e `discharge` são as energias AC que entram e saem dos armazenamentos do membro. Nos VE são medidas no carregador, pelo que incluem as perdas do carregador.
- `known` é a energia que entrou no barramento com composição conhecida: FV, importação da rede, energia descarregada dos armazenamentos (com as origens que tinha no armazenamento) e importações locais.
- `recycle` é a energia carregada num armazenamento e de novo descarregada no mesmo intervalo. A sua composição é a própria mistura do barramento; por isso, a divisão por `supply - recycle` resolve os ciclos de armazenamento dentro do intervalo sem criar energia FV.
- `mix` tem uma entrada por origem e produtor, em kWh por kWh de fornecimento.

Cada fluxo que sai do barramento leva `mix` vezes a sua energia:

```text
destino load        = mix × load
grid_export         = mix × (max(-net, 0) - local_out)
local_export        = mix × local_out
carga armazenada    = mix × energia armazenada no intervalo
perda na carga      = mix × (carga AC - energia armazenada)
```

`grid_in` é registado como `external_import_kwh`. `grid_in × intensidade carbónica`, somado sobre os intervalos com intensidade finita, é registado como `external_purchase_emissions_kgco2`.

**Partilha local.** `local_in` e `local_out` são a importação e a exportação locais do membro no intervalo `t`.

- **Com mercado comunitário.** São as quantidades da liquidação do mercado. São nulas quando a troca local está desativada.
- **Sem mercado comunitário.** O registo compensa os membros entre si:

```text
traded       = min(Σ_m max(net(m), 0), Σ_m max(-net(m), 0))
local_out(m) = max(-net(m), 0) × traded / Σ_m max(-net(m), 0)
```

Sem mercado, `local_in` reparte `traded` pelos importadores na proporção de `community_market_import_member_weights` (1 por omissão). Nenhum membro recebe mais do que a sua própria importação: uma parcela que a exceda é limitada, e o excesso é repartido de novo pelos restantes importadores.

As misturas dos exportadores são resolvidas primeiro, e a sua exportação local conjunta é passada aos importadores na proporção de `local_in`.

**FV direta.**

```text
direct(m,t)           = (pv_bus + FV recebida diretamente dos exportadores) / supply
pv_load_direct        = Σ_t direct × load
pv_load_after_storage = max(pv_load - pv_load_direct, 0)
```

A `FV recebida diretamente dos exportadores` é a parte da exportação local de cada exportador que veio diretamente da sua produção FV nesse intervalo.

### Energia armazenada que sai mais tarde

As operações de armazenamento são aplicadas a cada armazenamento por ordem:

- **Carga.** A energia armazenada junta-se ao armazenamento com a mistura do barramento nesse intervalo. A perda na carga é contada como `loss` com a mesma mistura.
- **Descarga.** Retirar `removed` kWh leva a fração `removed / armazenado` de cada origem presente. Dessa parcela, a fração `AC entregue / removed` entra no barramento do membro, mantendo a origem, o produtor e o carbono. O resto é `loss`.
- **Repouso.** A fração de energia armazenada perdida leva a mesma parte proporcional de cada origem e é `loss`.

A energia que volta ao barramento é repartida com a mistura do barramento, como qualquer outro fornecimento. Por exemplo, a energia FV armazenada e depois descarregada para o consumo conta em `pv_load` e em `pv_load_after_storage`, e não em `pv_load_direct`. A energia da rede armazenada e depois usada conta em `grid_load` e em `carbon_load`.

A energia ainda armazenada no momento da avaliação conta como `stored`. A energia num VE que parte conta como `mobility`, com as origens que tinha à partida.

### Linhas de carbono

- `carbon_<destino>_kgco2` é o carbono da rede transportado pela energia que chegou ao destino. Só a energia da rede transporta carbono.
- `carbon_unknown_<destino>_kwh` é uma energia, não uma massa de carbono. São os kWh nesse destino cujo carbono é desconhecido: energia de origem desconhecida mais importação da rede com intensidade não finita. Um valor elevado indica que a linha `carbon_*` correspondente é um limite inferior.
- `external_purchase_unknown_carbon_kwh` é a importação da rede de carbono desconhecido no momento da compra.
- As exportações não dão crédito de carbono.

### Distrito e portefólio

O valor de distrito de cada linha que também existe ao nível do edifício é a **soma das linhas dos membros**.

As linhas abaixo existem **apenas ao nível do distrito**. Verificam ou resumem o registo completo, que só fecha para o distrito no seu conjunto: as linhas de destino de um edifício contam energia recebida dos vizinhos, enquanto o seu `pv_generated` conta apenas a sua própria produção.

- **Resíduos de balanço.** Um por origem e um para o carbono. Espera-se que sejam próximos de 0:

  ```text
  pv_balance_residual      = pv_generated                - Σ_d pv_d
  grid_balance_residual    = external_import             - Σ_d grid_d
  unknown_balance_residual = unknown_input               - Σ_d unknown_d
  carbon_balance_residual  = external_purchase_emissions - Σ_d carbon_d
  ```

  `d` percorre os oito destinos: load, mobility, grid_export, loss, asset_exit, external_reset, curtailment e stored.

- **Rácios de FV útil.** Calculados sobre os totais do distrito:

  ```text
  pv_useful_building      = pv_load / pv_generated
  pv_useful_with_mobility = (pv_load + pv_mobility) / pv_generated
  ```

  Ambos são indefinidos quando o `pv_generated` do distrito é ≤ 1e-10 kWh. A energia FV ainda armazenada no momento da avaliação (`pv_stored`) não conta como útil.

- **Diagnósticos.** Máximos acumulados sobre todos os membros e intervalos desde o reset. Espera-se que sejam próximos de 0:

  ```text
  bus_max_residual     = máximo sobre m,t de max(-(net + pv_bus + discharge - charge), 0)
  storage_max_residual = máximo sobre armazenamentos e intervalos de |armazenado no registo - energia armazenada na bateria|
  ```

  `bus_max_residual` só é diferente de zero quando os dados do barramento implicam um consumo negativo, que o registo limita a 0.

**Portefólio.**

- As linhas `_kwh` e `_kgco2`, incluindo as suas linhas BAU e delta, são somadas sobre as comunidades.
- Os rácios `pv_useful_*`, com as suas linhas BAU e delta, são a **média ponderada pelo `weight` de cada comunidade**, sobre as comunidades com valor definido. Não são recalculados a partir dos totais somados de `pv_load`, `pv_mobility` e `pv_generated`.
- `bus_max_residual_kwh` e `storage_max_residual_kwh` são **somados** sobre as comunidades, como qualquer linha `_kwh`. São, portanto, uma soma de máximos das comunidades, e não um máximo.

### Leitura das linhas do scorecard por omissão

O scorecard por omissão inclui seis linhas de proveniência:

| Linha | Como ler |
|---|---|
| `district_energy_provenance_pv_useful_building_ratio` | Fração da energia FV da comunidade que chegou a um consumo dos edifícios. Um valor mais alto significa mais energia FV usada nos edifícios. |
| `district_energy_provenance_pv_useful_with_mobility_ratio` | Como acima, mais a energia FV que saiu em VE que partiram. Um valor mais alto significa mais energia FV numa utilização final. |
| `district_energy_provenance_pv_stored_kwh` | Energia FV ainda em baterias e VE ligados no momento da avaliação. Não está perdida nem é ainda útil; leia-se com os dois rácios acima. |
| `district_energy_provenance_pv_grid_export_kwh` | Energia FV que saiu da comunidade por exportação para a rede após a partilha local. |
| `district_energy_provenance_external_purchase_emissions_kgco2` | Carbono da rede comprado pela comunidade após a partilha local. Quanto mais baixo, melhor. |
| `district_energy_provenance_external_purchase_emissions_business_as_usual_kgco2` | A mesma grandeza na simulação BAU. Compare-se diretamente com a anterior. |

### Que linha usar

- **Emissões do distrito.** Para o total de emissões, use-se a família [Emissões](#emissões). O total de controlo dessa família no distrito é igual a `district_energy_provenance_external_purchase_emissions_kgco2`, também quando um mercado comunitário está configurado com a troca local desativada. Use-se a linha de proveniência quando é preciso saber para onde foi esse carbono.
- **Emissões dos edifícios.** Ao nível do edifício, `external_purchase_emissions` conta a importação após a partilha local, enquanto as emissões do edifício contam a importação própria de cada membro. As duas diferem sempre que os membros partilham energia.
- **Autoconsumo solar ou FV útil.** O autoconsumo solar conta toda a energia FV que não foi exportada nem cortada, incluindo a perdida no armazenamento ou ainda armazenada. `pv_useful_building_ratio` conta apenas a energia FV que chegou a um consumo. Use-se este último quando a pergunta é quanta energia FV serviu a procura.
- **FV no consumo.** `pv_load` é o total de energia FV no consumo de um membro. `pv_load_direct` e `pv_load_after_storage` dividem-no em energia FV usada sem armazenamento e energia FV usada depois de armazenada. Use-se a divisão apenas para avaliar o contributo do armazenamento.

### Limitações conhecidas

- O armazenamento é misturado proporcionalmente, e não pela ordem de entrada. É uma convenção contabilística, não uma medição.
- A energia de um VE no momento da ligação, e qualquer estado de carga imposto, é desconhecida e sem carbono no registo. As linhas `carbon_*` ficam, por isso, por defeito; as linhas `carbon_unknown_*` mostram em quanta energia.
- As linhas dos edifícios são contadas pelo membro que recebe e não fecham por membro. Só o distrito fecha.
- O registo não tem janela de avaliação: abrange todos os intervalos simulados desde o reset.
- Ao nível do portefólio, os rácios `pv_useful_*` são médias ponderadas pelo `weight` das comunidades, e os dois diagnósticos de resíduo máximo são somas dos máximos das comunidades.

## Topologia dinâmica

Com `topology_mode='dynamic'`, os membros entram e saem da comunidade durante o episódio. Cada linha de edifício de um membro do ciclo de vida tem três colunas adicionais: `topology_born_at`, `topology_removed_at` e `topology_active`.

`topology_lifecycle_presence` é uma linha marcadora, e o seu valor é sempre NaN. É acrescentada uma linha, ao nível do edifício, por cada membro do ciclo de vida sem outra linha de edifício. Esse membro nunca ficou ativo no episódio, por isso as funções de KPI ignoram-no. A linha faz com que esses membros apareçam na tabela com as suas colunas de ciclo de vida. O nível é `building` porque a linha descreve um membro, cujo identificador está em `name`. O nome não tem o prefixo `building_` porque a linha é acrescentada depois da etapa de nomeação dos KPI. Não é agregada ao distrito nem ao portefólio.

Os membros que participaram são avaliados só nos seus passos ativos:
- a energia pertence aos passos em que o membro estava ativo;
- as médias diárias do edifício dividem pelos dias ativos do membro (ver as [regras comuns](#regras-comuns));
- os totais do distrito incluem os membros que saíram.

Limitações conhecidas: o marcador não contém qualquer medição; use as colunas de ciclo de vida, não o seu valor.

## Definicoes alteradas depois da 3.6.0

A versao das definicoes de KPIs (`kpi_definition_version` nos metadados `energy_accounting` de `evaluate_v2()`) e `2.0.0`. Estas linhas de `evaluate_v2()` mudaram de definicao. Onde um valor da 3.6.0 pode ter sido usado em comparacoes publicadas, fica com um nome proprio, e as linhas legacy de `evaluate()` mantem as suas definicoes da 3.6.0, exceto a baseline dos datasets com carregadores de VE (a linha dos carregadores de VE), que `baseline_version=1` repoe.

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
| `*_ev_events_departure_met_count` (antigo `ev_departure_met_events_count`), `*_ev_performance_departure_success_ratio`, `*_ev_performance_departure_success_feasible_ratio`, `*_ev_events_departure_target_{feasible,infeasible}_count`, `*_ev_departure_audit_target_*` | Uma partida cumpre o alvo a menos de 0,005 de SOC (era 1e-6), pelo que um carro que as baselines baseadas em regras param 0,001 abaixo do alvo conta como servido. | nenhum |
| Linhas de conforto (`*_comfort_resilience_*`, linhas de desconforto `*_thermal_service_audit_*`, `discomfort_*` e `one_minus_thermal_resilience_proportion` antigos) de um edifício sem colunas de set points | Indefinidas (eram avaliadas contra um set point de arrefecimento de 0 °C). | nenhum |
| `*_{cost,emissions}_ratio_to_{baseline,business_as_usual}_total_ratio` com os dois totais a zero, e os seus valores de portfólio | Indefinido (era 1). | nenhum |
| `building_demand_response_{shortfall_total_kwh,compliance_ratio}` | Alocados a partir do settlement district. | `building_demand_response_uncapped_contribution_total_kwh` (diagnostico) |
| Taxas e medias EV de departure, service levels dos deferrable appliances e das escadas rolantes, start delay e self-consumption solar do portefólio (`MultiCommunityEnv`) | Agregadas a partir dos seus denominadores aditivos. | nenhum |
| Shares locais do mercado comunitário, compliance de demand response e ratios de cobertura das auditorias de demand response do portefólio (`MultiCommunityEnv`, #285) | Agregados a partir da energia local mais a da rede, da energia pedida válida, da energia pedida e dos intervalos ativos. | nenhum |
| Ciclos completos equivalentes das baterias estacionárias do portefólio e comparações com a execução BAU (`MultiCommunityEnv`, #330) | Energia movimentada total sobre o dobro da capacidade nominal total. A diferença e o rácio face à execução BAU usam os dois valores do portefólio. | nenhum |
| Nos datasets com carregadores de VE: todas as linhas `*_baseline_*`, `*_delta_*` (exceto `*_delta_to_business_as_usual_*`) e `*_ratio_to_baseline_*`, os KPIs de equidade calculados a partir delas, e toda a tabela legacy de `evaluate()` (#365) | A baseline carrega os VE como o BAU nativo com o alvo `'full'`, em vez de nao os carregar (`baseline_version=2`). | `baseline_version=1` |
| Nos datasets com ações de AVAC: todas as linhas `*_business_as_usual` e todos os valores `*_delta_to_business_as_usual_*` e `*_ratio_to_business_as_usual_*` (#362) | O BAU nativo fornece a procura de aquecimento e de arrefecimento do dataset, em vez de enviar zero às ações de AVAC (`baseline_version=2`). | `baseline_version=1` |

Nas linhas legacy, uma janela de load factor cujo pico com sinal nao e positivo passa a ser indefinida; antes dava uma penalizacao infinita ou negativa, que a safe division reportava como um 0 perfeito.

## Auditoria de Resiliencia por Evento de Outage

Para inspecionar interrupcoes da rede evento a evento em cenarios de topologia estatica sem alterar `evaluate_v2()`, usar `env.evaluate_outage_events()` (devolve `(events_df, summary_df)`) ou `env.get_outage_resilience_audit()` (devolve um dicionario pronto para JSON incluindo `district_windows`).

Um evento de corte de um edificio e uma sequencia maxima de timesteps executados consecutivos em que `building.simulate_power_outage` esta ativo e `building.power_outage_signal` e finito e diferente de zero, seguindo a mesma regra do simulador e de `citylearn/internal/service_energy.py` (quando `simulate_power_outage` esta ativo, valores nao finitos em `power_outage`, como celulas em branco, `NaN`, `inf` ou `-inf`, levantam `ValueError` antes da simulacao; quando esta desativado, a coluna e ignorada). Uma janela de corte do distrito (`district_windows`) abrange timesteps executados consecutivos com pelo menos um edificio afetado. A energia de servico esperada, servida e nao servida vem de `citylearn/internal/service_energy.py` (usos finais `cooling`, `heating`, `dhw` e `non_shiftable`, limitados individualmente para que excessos num uso final nunca compensem falhas noutro), coincidindo com o numerador e denominador de `..._resilience_unserved_energy_outage_normalized_ratio`.

| Campo | Nivel | Unidade | O que mede |
|---|---|---:|---|
| `start_time_step`, `end_time_step` | evento, janela do distrito | step | Limites inclusivos (base 0 no episodio) da interrupcao. |
| `duration_steps`, `duration_hours` | evento, janela do distrito | count / hours | Duracao em steps e em horas (`duration_steps * seconds_per_time_step / 3600`). |
| `expected_energy_kwh`, `served_energy_kwh`, `unserved_energy_kwh` | evento, janela do distrito, building, district | kWh | Energia esperada, servida e nao servida durante cortes, mais divisao `<end_use>_*_energy_kwh`. |
| `peak_unserved_power_kw` | evento, janela do distrito, building, district | kW | Maior potencia nao servida num unico step (`max_step_unserved_kwh * 3600 / seconds_per_time_step`); no distrito, coincidente entre edificios simultaneamente afetados. |
| `fully_served` | evento, janela do distrito | bool | Indica se a energia por servir e nula dentro da tolerancia (`<= 1e-9` kWh). |
| `building_events_count`, `building_outage_steps_count`, `building_outage_hours`, `worst_building_event_unserved_energy_kwh`, `fully_served_building_events_ratio` | building, district | count / steps / hours / kWh / ratio | Contagem de eventos de edificio, duracao em steps/horas de edificio, pior energia nao servida num evento de edificio e fracao de eventos totalmente servidos (`None` quando `building_events_count == 0`). Na linha `District` agregam os eventos dos edificios membros. |
| `district_windows_count`, `district_window_steps_count`, `district_window_hours`, `worst_district_window_unserved_energy_kwh`, `fully_served_district_windows_ratio` | district (`NaN` nas linhas building) | count / steps / hours / kWh / ratio | Contagem, duracao contigua em steps/horas, pior energia nao servida e fracao totalmente servida das janelas de corte do distrito com pelo menos um edificio afetado (`None` quando `district_windows_count == 0`). |

## Export

| Modo | Como obter |
|---|---|
| Em memoria | `env.evaluate_v2()` |
| Export no fim | `CityLearnEnv(..., export_kpis_on_episode_end=True)` |
| Com render | `render_mode="end"` ou `render_mode="during"` |

A tabela em formato longo começa por `cost_function`, `value`, `name` e
`level`, seguidos de `unit` e de uma breve `description` em inglês, ambas
retiradas do catálogo de KPIs.

O CSV de várias comunidades em formato longo inclui as colunas de metadados. Na exportação
de uma só comunidade em CSV ou Parquet em formato largo, o ficheiro adjacente
`exported_kpis.manifest.json` contém `kpi_definitions` por nome de KPI.
O ficheiro de KPIs continua a ter uma coluna numérica por âmbito.

Um KPI novo tem de ser acrescentado a `citylearn/misc/kpi_catalogue.yml`, que gera o [catálogo de KPIs](KPI_V2_TREE.md) (`python scripts/docs/kpi_catalogue.py`), e as suas equações à secção da família nesta página; `tests/test_kpi_catalogue.py` falha enquanto um nome emitido faltar no catálogo. As alterações de definição ficam registadas em [releases.md](releases.md).
