# Funcionalidades do simulador

Configure os equipamentos e serviços no [schema](schema_reference.md), escolha
as [ações](actions_reference.md) e as [observações](observations_reference.md),
e execute a simulação pelo [guia de utilização](running_simulations.md).

## Edifícios, produção e armazenamento

| Componente | Funcionalidade |
|---|---|
| Edifícios | Comunidades com vários edifícios, controlo por agente ou centralizado e API Gymnasium `reset/step`. |
| Sistemas térmicos | Arrefecimento, aquecimento e água quente com armazenamento térmico. |
| Baterias | SOC, eficiência, curvas de potência e degradação. |
| Fotovoltaico | Perfil por kW instalado ou produção medida em `kWh/step`. |
| Veículos elétricos | Calendários por carregador, veículos ligados ou previstos, eficiência e V2G. |
| Máquinas diferíveis | Ciclos normalizados, janelas de início, prazos e indicadores de serviço. |

## Tempo e unidades

A duração dos passos é configurada por `seconds_per_time_step`, incluindo
1 h, 15 min, 5 min, 1 min e 15 s. Os dados de energia usam `kWh/step`; os limites
e potências usam `kW`. A conversão das ações considera a duração do passo.
As verificações físicas opcionais e os testes de baixa energia ajudam a detetar
erros de escala e arredondamento. Consultar o [contrato de unidades](data_unit_contract.md).

## Observações e interfaces

A interface vetorial devolve observações por edifício ou para um agente central.
A interface de entidades fornece tabelas `district`, `building`, `charger`, `ev`,
`storage`, `pv` e `deferrable_appliance`, com relações e identificadores estáveis.
`env.entity_specs` descreve os campos, unidades e grupos de observações.
As cópias devolvidas impedem a alteração acidental do estado interno pelo agente.

Os grupos opcionais permitem selecionar previsões, pedidos de resposta à procura
e informação de robustez. O grupo de resposta à procura inclui o pedido ativo,
a referência, os preços e o serviço ou défice anterior. O de robustez inclui o
estado e os contadores de perturbações. Ver o [guia de interfaces](interfaces_flat_entity.md).

## Topologia dinâmica

`add_member` e `remove_member` alteram os membros. `add_asset` e `remove_asset`
alteram carregadores, PV, baterias e máquinas durante o episódio. Os espaços de
ações e observações acompanham a versão da topologia; `born_at`, `removed_at` e
`active` registam o ciclo de vida das entidades. A remoção de máquinas cancela os
ciclos futuros sem deixar consumo pendente.

## Limites elétricos e fases

Carregadores e baterias podem ligar-se a `L1`, `L2`, `L3` ou `all_phases`.
As observações e os KPIs expõem potência, margem de importação/exportação,
violações residuais, desequilíbrio e picos por fase. Estes são limites de potência
ativa na ligação; não representam um cálculo de tensão ou fluxo de potência AC.

## Mercado local e indicadores

O mercado faz a correspondência entre excedentes e procura no mesmo intervalo,
com repartição por pesos dos membros. Os resultados incluem custos liquidados,
poupança face à referência sem partilha e autoconsumo comunitário.
Os KPIs v2 têm nomes estruturados por nível, família, métrica e unidade;
os testes de referência incluem valores calculados à mão.
Ver as [definições dos KPIs](kpis_reference.md).

## Resposta à procura e várias comunidades

Pedidos DSO/TSO definidos nos dados expõem objetivos de flexibilidade,
remuneração, entrega e défice através da interface de entidades.
Cada comunidade mantém os seus pedidos, liquidação e indicadores.

`MultiCommunityEnv`, em `citylearn.multi_community`, sincroniza comunidades
independentes com a mesma duração de passo, episódio, interface e modo
`central_agent`. `evaluate_v2()` acrescenta linhas `level="portfolio"` com somas
e rácios ponderados. Os exports incluem subpastas locais e
`exported_kpis_multi_community.csv`. Consultar o [guia de várias comunidades](multi_community_reference.md).

## Eventos de robustez

Ficheiros CSV/Parquet configuram perturbações determinísticas nas observações,
previsões, ações e disponibilidade lógica dos equipamentos. Cada grupo é opcional.
Perturbar observações ou previsões não altera o estado físico usado nos KPIs,
recompensas e liquidação. Falhas no canal de ação podem alterar o comando aplicado.
Um equipamento logicamente indisponível mantém a sua identidade na topologia.
Os indicadores distinguem eventos, dados ausentes e ações afetadas.
Consultar o [guia de robustez](robustness_reference.md).

## Dados, desempenho e visualização

CSV e Parquet partilham o contrato de dados. O carregamento por janela e a cache
comum de meteorologia, preços e carbono reduzem carregamento repetido.
Os modos de renderização `none`, `during` e `end` controlam quando são escritos
os resultados. Os exports de séries temporais e KPIs permitem a análise na
CityLearn UI; a data inicial configura os timestamps apresentados.

O [guia de validação e desempenho](../validation.md), em inglês, reúne as
verificações físicas, de KPIs e de interfaces, os testes de topologia e os
resultados medidos. Os testes cobrem os cenários executados, sem substituir a
calibração com equipamentos reais.
