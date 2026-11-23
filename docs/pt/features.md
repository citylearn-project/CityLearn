# Funcionalidades e configuração

Comece pela [primeira simulação](https://www.citylearn.net/quickstart.html) e
depois escolha as condições que o seu controlador deve tratar. As
funcionalidades são configuradas no schema ou nos argumentos do ambiente; o mesmo
ciclo de simulação executa o episódio.

Versão em inglês: [../features.md](../features.md).

## Edifícios, sistemas térmicos e armazenamento

Uma comunidade contém edifícios com procura de eletricidade e sistemas opcionais
de arrefecimento, aquecimento e água quente sanitária. O armazenamento térmico
desloca o momento em que a energia é fornecida; os modelos de edifício com
temperatura dinâmica permitem que o controlo do AVAC afete a temperatura
interior. Os indicadores de conforto e de cortes de energia reportam o serviço
resultante.

Escolha os equipamentos na entrada do schema de cada edifício e ative as suas
ações. A [configuração dos equipamentos](schema_reference.md#secções-de-dispositivos),
o [significado das ações](actions_reference.md#ações-flat) e os
[KPIs de conforto](kpis_reference.md#conforto-e-resiliência) dão os pormenores.

## Fotovoltaico e baterias

![A produção FV, o carregamento/descarga da bateria, a procura do edifício e a troca com a rede partilham a ligação do edifício.](../../assets/images/pv-storage-flow.svg)

O FV pode usar um perfil de produção normalizado por kW ou a produção medida em
`kWh/step` com `generation_mode="absolute"`. As baterias estacionárias têm
parâmetros de capacidade, SOC, potência de carregamento/descarga, eficiência e
degradação. Ações de armazenamento positivas carregam e negativas descarregam;
os limites físicos e da ligação determinam a energia aplicada.

Consulte a [configuração do FV](schema_reference.md#fv), o
[contrato de unidades](data_unit_contract.md) e as
[ações de armazenamento](actions_reference.md#conversão-física).

## Veículos elétricos e carregadores

![A janela de ligação de um VE vai do SOC de chegada a um SOC de partida exigido, com ações de carregamento enquanto está ligado.](../../assets/images/ev-service-window.svg)

Os calendários dos carregadores identificam os VE ligados e a chegar, as horas de
chegada/partida e o SOC de partida exigido. As ações centradas no carregador
controlam o VE ligado; ações negativas permitem V2G quando há potência de
descarga disponível. As identidades dos VE e dos carregadores mantêm-se
separadas, para que veículos diferentes possam usar o mesmo carregador.

Configure os [carregadores](schema_reference.md#carregadores) e as
[definições dos VE](schema_reference.md#definições-dos-ve). Leia separadamente o
serviço mínimo à partida e a exatidão simétrica do alvo no
[scorecard](scorecard.md). Um exemplo público executável é
`citylearn_challenge_2022_phase_all_plus_evs`.

## Aparelhos flexíveis

Um catálogo de ciclos normalizados descreve o consumo ao longo de um ciclo. Um
calendário separado dá o arranque mais cedo, o arranque mais tarde e o prazo de
conclusão. A ação pede um arranque; o simulador verifica que o ciclo completo
cabe na janela e no episódio antes de o aplicar. A conclusão, os ciclos falhados
e o atraso são registados como indicadores de serviço.

Consulte a [configuração](schema_reference.md#aparelhos-diferíveis) e a
[lógica de arranque](actions_reference.md#lógica-de-arranque-dos-aparelhos-diferíveis).
O exemplo público de VE acima inclui a configuração de aparelhos flexíveis.

## Escadas rolantes

A interface flat suporta um modelo agregado de escadas rolantes com os estados
standby/lento/normal. Uma ação normalizada seleciona um desses estados; as
entradas de procura e disponibilidade determinam os indicadores de serviço aos
passageiros e o consumo de energia. É um modelo de estados e procura, não uma
simulação de passageiros individuais ou de filas.

Forneça o seu próprio calendário com o
[schema das escadas rolantes](schema_reference.md#escadas-rolantes-interface-flat).
O [guia de ações](actions_reference.md#controlo-das-escadas-rolantes) explica os limiares
dos estados.

## Serviço elétrico e limites por fase

Os edifícios podem ter limites de importação/exportação de potência ativa totais
e por fase. O armazenamento e os carregadores podem ser atribuídos a ligações de
fase. O simulador regista as ações pedidas, limitadas e aplicadas juntamente com
a margem e a potência por fase, o que permite a um estudo distinguir um pedido
excessivo de uma ultrapassagem residual depois do tratamento das restrições.

Configure `buildings.<name>.electrical_service` com a
[referência do schema](schema_reference.md#buildings). Comece com
`citylearn_three_phase_electrical_service_demo`. Estas são restrições de potência
ativa na ligação; não calculam a tensão no alimentador nem o fluxo de potência
AC. Consulte os [KPIs elétricos](kpis_reference.md#serviço-elétrico-e-fases).

O limite de importação também pode variar no tempo. Uma série de
[potência de rede disponível](schema_reference.md#potência-de-rede-disponível)
reduz-o abaixo da capacidade da ligação em cada passo, por exemplo quando um
operador da rede de distribuição limita equipamentos controláveis ou reduz a
capacidade durante situações de stress da rede. Os controladores podem observar
o limite do próximo intervalo como `available_grid_power`.

## Partilha local de energia e liquidação

Ative `community_market.enabled` para fazer corresponder o excedente e a procura
do mesmo passo entre membros. Os preços locais e os pesos dos importadores
determinam a repartição financeira; os exports expõem os custos liquidados, o
contrafactual só com a rede e as poupanças de cada membro e da comunidade. A
liquidação valoriza a trajetória física registada.

Configure o [mercado comunitário](schema_reference.md#mercado-comunitário). As
exportações residuais para a rede recebem atualmente remuneração nula. A
liquidação local é feita dentro de uma comunidade; os resultados de várias
comunidades são descritos abaixo.

## Pedidos de resposta à procura

Um ficheiro de pedidos fornece as janelas de ativação do DSO/TSO, a direção, a
potência alvo, o pagamento, a tolerância e a penalização por défice. Use o modo de
entidades e ative o grupo de observações `entity_demand_response` para expor os
pedidos ativos. Os controladores respondem através das ações existentes de
armazenamento, VE e cargas flexíveis.

A referência é a potência líquida média na janela de histórico anterior ao evento
configurada, fixada para esse pedido. A energia entregue, a resposta creditada e o
défice penalizado são grandezas separadas. Consulte o
[formato dos pedidos e a referência](schema_reference.md#resposta-à-procura) e os
[KPIs de liquidação](kpis_reference.md#demand-response).
Use `citylearn_challenge_2022_phase_all_demand_response` como exemplo público.

## Alteração de membros e ativos

Com `interface="entity"` e `topology_mode="dynamic"`, eventos agendados
acrescentam ou removem membros, carregadores, FV, armazenamento e aparelhos
flexíveis. Identificadores estáveis, metadados de ciclo de vida e
espaços/especificações atualizados permitem aos controladores acompanhar estas
alterações. O reset reconstrói o cenário inicial para o episódio seguinte.

Consulte os [eventos de topologia](schema_reference.md#topologia-dinâmica) e as
[especificações das entidades](interfaces_flat_entity.md).
Os exemplos públicos incluem `citylearn_three_phase_dynamic_topology_demo` e
`citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet`.

## Falhas de dados e de equipamentos

Eventos de robustez opcionais alteram as medições ou previsões visíveis pelo
controlador, descartam/atrasam/corrompem ações ou tornam canais de ativos
indisponíveis. O ficheiro de eventos define os alvos, as janelas temporais e as
perturbações. A corrupção de medições mantém o estado físico intacto; as
alterações no canal de ação podem afetar o consumo real.

Consulte o [guia de robustez](robustness_reference.md) para todos os modos
suportados e para a distinção entre valores em falta e zero físico. O exemplo
público é `citylearn_challenge_2022_phase_all_robustness`.

## Resolução temporal e formatos de dataset

Use cenários horários ou sub-horários, incluindo dados a 15 minutos, 5 minutos,
1 minuto e 15 segundos. Faça corresponder o passo de tempo do schema à cadência
das entradas e forneça as colunas de energia em `kWh/step`. Alterar apenas o
passo de tempo não cria pormenor medido de alta frequência a partir de dados
horários.

CSV e Parquet usam o mesmo contrato de colunas; o Parquet é útil para datasets
grandes. Consulte o [guia de datasets](dataset_reference.md) e o
[contrato de unidades](data_unit_contract.md). Comece as simulações grandes com
uma janela curta.

Os [datasets REC de Portugal](portugal_rec_datasets.md) são comunidades em
Parquet a 15 minutos, com 4, 15, 30 e 100 membros, em 2023-2024. Os seus cenários
de avaliação acrescentam alterações de topologia, limites elétricos, falhas de
ativos, cortes de energia e resposta à procura.

## Vetores flat e tabelas de entidades

O modo flat fornece vetores por edifício, ou um vetor combinado no modo de agente
central. O modo de entidades fornece tabelas identificadas, atributos, máscaras e
arestas relacionais. Os grupos de observações selecionam previsões, margem
elétrica, prazos de serviço e feedback das ações. Estas entradas podem ser usadas
por controladores de grafos ou Transformer fornecidos pelo investigador.

O [guia de interfaces](interfaces_flat_entity.md), a
[referência de observações](observations_reference.md) e a
[referência de ações](actions_reference.md) definem os contratos.

## Várias comunidades

`MultiCommunityEnv` avança comunidades independentes em sincronia e reporta
resultados locais e de portefólio. As comunidades filhas partilham o passo de
tempo, a duração do episódio, a interface e o modo de agente central. Cada uma
mantém o seu próprio estado físico, pedidos de DR e liquidação. O wrapper agrega
os resultados; não transfere fisicamente energia entre comunidades nem otimiza o
despacho entre comunidades.

O [guia de várias comunidades](multi_community_reference.md) inclui um exemplo
completo com datasets públicos disponíveis.

## Controladores, recompensas e ações repetidas

Use os agentes business-as-usual e baseados em regras incluídos, implemente um
controlador próprio ou integre um algoritmo de aprendizagem. Uma recompensa
orienta o treino; os KPIs avaliam a execução concluída. Não têm de otimizar a
mesma grandeza. Verifique a interface suportada por cada controlador/wrapper; os
RBC clássicos e os wrappers de RL padrão usam o modo flat.

`step_many()` repete uma ação continuando a avançar a física e os serviços em
cada passo interno. Devolve as recompensas acumuladas e o número de passos
executados. Consulte as [opções de simulação](running_simulations.md) e os
[tutoriais de controladores](https://www.citylearn.net/usage/agents.html).

## Avaliação, exports e desempenho

`evaluate_v2()` fornece KPIs estruturados de edifício/comunidade. O
[scorecard](scorecard.md) apresenta uma seleção compacta; a
[referência de KPIs](kpis_reference.md) e o [catálogo de nomes](KPI_V2_TREE.md)
cobrem a saída mais alargada. Os rácios normalizados acompanham as grandezas
brutas de energia, custo e serviço, em vez de as substituírem.

Use `render_mode="none"` durante o treino, ou `"end"` para exports no fim do
episódio. O carregamento por janela, as caches de entradas partilhadas, o Parquet
e os grupos de observações selecionáveis ajudam a controlar os custos de tempo de
execução e de memória. Consulte as
[opções de exportação](running_simulations.md#render-e-exportação), a
[CityLearn UI](https://www.citylearn.net/ui.html) e o
[guia de desenvolvimento](developer_guide.md) para validação e profiling.
