# Migrar um projeto existente para o CityLearn v3

O nome da distribuição e o nome de importação são ambos `citylearn`. Instale-o a
partir do PyPI, ou consulte o [guia de desenvolvimento](developer_guide.md) para
usar uma cópia do repositório.

Versão em inglês: [../migration.md](../migration.md).

## Mantenha explícito o ciclo do controlador

```python
observations, info = env.reset(seed=0)
observations, rewards, terminated, truncated, info = env.step(actions)
```

Pare quando `terminated or truncated`. `info` é o último valor devolvido, não o
terceiro. A interface flat mantém um vetor de observações/ações por edifício, ou
um único vetor combinado com `central_agent=True`. Leia a ordem das ações e das
observações a partir do ambiente, em vez de fixar posições no código.

## Escolha a interface e o passo de tempo

Comece os controladores de membros fixos com `interface="flat"`. Use
`interface="entity"` para tabelas de entidades identificadas, arestas relacionais
e membros dinâmicos. As observações entity são uma representação de entrada; uma
política GNN ou Transformer tem de ser fornecida pelo utilizador.

Faça corresponder `seconds_per_time_step` à cadência dos dados. As colunas de
energia usam `kWh/step`; os limites de potência usam `kW`. Consulte o
[contrato de unidades](data_unit_contract.md).

## Escolha a API de avaliação

`evaluate()` mantém os nomes legados das funções de custo. `evaluate_v2()` devolve
os nomes estruturados de KPIs usados pelos exports atuais e pelo scorecard. O `v2`
no nome do método designa a interface de KPIs, não a versão 2 do CityLearn.

O [scorecard](scorecard.md) distingue a referência contrafactual convencional do
controlador business-as-usual nativo e explica os indicadores de serviço, de
exatidão face ao alvo e de limites elétricos pedidos/aplicados.

## Resolva separadamente os dados públicos e os locais

Os nomes dos datasets públicos são resolvidos face à tag da versão do pacote
instalado. Use `DataSet().get_dataset_names()` para ver o catálogo dessa versão
(importe `DataSet` de `citylearn.data`). Forneça o seu próprio schema e ficheiros
locais para dados que não estão no catálogo público; um caminho relativo ao
repositório não é criado por `pip install`.

O [histórico de versões](releases.md) mantém as alterações específicas de cada
versão e o histórico da linha de desenvolvimento.

## Por publicar

### Carregamento dos VE na baseline por omissão

A baseline por omissão dos KPIs (`EvaluationCondition.WITHOUT_STORAGE_BUT_WITH_PV`,
as séries `*_without_storage`) subtraía o consumo dos carregadores de VE
juntamente com a bateria e o armazenamento térmico e não voltava a somar nada,
pelo que nos datasets com VE as linhas `*_baseline_*`, `*_delta_*` e
`*_ratio_to_baseline_*`, e todos os valores da tabela do `evaluate()` antigo,
comparavam a execução com uma comunidade cujos carros nunca carregam: qualquer
controlador que carregasse os carros parecia pior do que a baseline
([#365](https://github.com/citylearn-project/CityLearn/issues/365)).

- A baseline passa a somar o carregamento dos VE do BAU nativo com o alvo
  `'full'`: cada carro é carregado quando chega, à potência máxima, até ficar
  cheio, e nunca é descarregado. Os carros recebem a energia de que precisam,
  sem V2G, e a baseline é a mesma para todos os controladores, pelo que as
  linhas `baseline` creditam ao controlador o despacho do armazenamento, o
  carregamento dos VE e o V2G, face a carregar à chegada. Os aparelhos
  diferíveis e o AVAC ficam como o controlador os operou.
- Nos datasets com carregadores de VE, cada avaliação executa o sidecar do BAU
  para obter esse carregamento, também o `evaluate()` antigo e
  `evaluate_v2(include_business_as_usual=False)`, e usa o alvo `'full'` qualquer
  que seja `business_as_usual_ev_charge_target`. Quando o sidecar não pode ser
  executado, porque as entradas, os edifícios ou os equipamentos mudaram depois
  do carregamento, a avaliação lança `ValueError`; use aí `baseline_version=1`.
  O manifesto dessa execução regista a referência do BAU como avaliada.
- Só mudam os datasets com carregadores de VE: `citylearn_challenge_2022_phase_all_plus_evs`,
  os datasets `pt_rec_*` e os demos trifásicos. A simulação, as linhas do
  controlo, as linhas do BAU e as recompensas não mudam. Os KPIs de equidade,
  calculados a partir do benefício de cada membro face à baseline, mudam com ela.
- Defina `baseline_version` como `1` (argumento do construtor ou chave do
  schema) para reproduzir a baseline do CityLearn 3.6.0. A versão fica em
  `env.get_metadata()` e no manifesto de exportação, no nível de topo e em
  `comparison_context`; `compare_exports()` dá como `incompatible` duas
  execuções com versões diferentes. O `MultiCommunityEnv` exige que todas as
  comunidades usem a mesma versão.

### AVAC no BAU (`baseline_version=3`, opcional)

Nos datasets com ações de AVAC (dinâmica de temperatura), o BAU envia zero a
`heating_device`, `cooling_device` e `cooling_or_heating_device`, pelo que os
seus edifícios não são aquecidos nem arrefecidos e as linhas
`*_business_as_usual` comparam o controlador com casas sem aquecimento ou sem
arrefecimento ([#362](https://github.com/citylearn-project/CityLearn/issues/362)).

- Por omissão nada muda: `baseline_version=2` continua a ser a predefinida, e as
  versões 1 e 2 dão os mesmos resultados de antes.
- Defina `baseline_version=3` para o BAU fornecer, em cada passo, a procura de
  aquecimento e de arrefecimento do próprio dataset, limitada aos limites da
  ação e do equipamento. As linhas do BAU e os deltas e rácios face ao BAU
  mudam nos datasets com ações de AVAC; nos outros datasets a versão 3 é igual
  à versão 2. A definição do BAU passa a
  `immediate-full-charge-v4+hvac-dataset-demand-v1` (ou
  `immediate-user-target-v3+hvac-dataset-demand-v1`). Consulte
  [AVAC e a versão da baseline](baselines.md#avac-e-a-versão-da-baseline).
- Um `BusinessAsUsualAgent` executado por si segue a versão do ambiente;
  `hvac='off'` ou `hvac='dataset_demand'` substitui-a.

### As referências baseadas em regras usam o AVAC

`RBCBasicPolicy`, `RBCSmartPolicy` e `RBCCommunityPolicy` passam a fornecer a
procura de aquecimento e de arrefecimento do dataset através das ações de AVAC,
com a regra do BAU de `baseline_version=3`.

- Datasets sem ações de AVAC: nada muda, bit a bit, incluindo a
  `comparison_identity()`.
- Datasets com ações de AVAC: as referências baseadas em regras aquecem e
  arrefecem, pelo que os seus KPIs de energia, custo e conforto mudam.
  Compare-as com o BAU de `baseline_version=3`; face ao BAU da versão 2,
  predefinida, que não aquece nem arrefece, os seus rácios face ao BAU comparam
  casas aquecidas com casas sem aquecimento. A sua identidade regista
  `hvac='dataset_demand'` e a definição ganha o sufixo `+hvac-dataset-demand-v1`.
- `RBCSmartPolicy(env, hvac='off')` (e o mesmo para as outras duas) dá o AVAC a
  zero das versões anteriores, para reproduzir resultados anteriores. Consulte
  [AVAC das referências baseadas em regras](baselines.md#avac-das-referências-baseadas-em-regras).

### Emissões do distrito com a troca local desligada

Com um mercado comunitário ativo e `community_market.local_trading_enabled`
definido como `false`, `district_emissions_total_*_kgco2` e os KPIs dele
derivados passam a contar cada importação de um membro à sua intensidade de
carbono, porque não há energia trocada localmente. Antes, compensavam as
exportações dos membros com as importações de outros membros, como se a troca
estivesse ligada. O novo valor é igual à linha `member_sum` e a
`district_energy_provenance_external_purchase_emissions_kgco2`. As execuções com a
troca local ligada, as execuções sem mercado e todos os datasets incluídos não
mudam, e o rácio de preço local não afeta as emissões. Para comparar com uma
execução anterior feita com a troca local desligada, reavalie-a com a versão
atual. Consulte [#327](https://github.com/citylearn-project/CityLearn/issues/327).

### As definições do mercado comunitário são validadas

O `CityLearnEnv` verifica agora a secção `community_market` quando é construído
e dá `ValueError` para definições que as versões anteriores ignoravam ou
substituíam: chaves desconhecidas (`enable` em vez de `enabled`), um rácio que
não é um número ou está fora de `[0, 1]`, aliases do rácio com valores
diferentes, um `settlement_version` que não seja `1` ou `2` (incluindo uma string como `"2"`), um
`grid_export_price` diferente de zero sem `"settlement_version": 2`, e pesos ou
ficheiros de tarifa de edifícios que não estão no schema. A mensagem nomeia a
chave e a correção. Um schema que carregava antes e agora dá erro não simulava o
que dizia: por exemplo, um rácio de 1,5 era liquidado a 1,0 e um
`grid_export_price` sem a versão 2 da liquidação não pagava nada. Escreva o
valor que era aplicado (rácio 1, `grid_export_price: 0`) para manter os
resultados anteriores, ou corrija a definição para obter o que era pretendido.
Todos os datasets incluídos são válidos e os seus resultados não mudam.

Alterar os atributos do mercado no env depois da construção
(`community_market_enabled`, `community_market_sell_ratio`,
`community_market_grid_export_price`,
`community_market_import_member_weights`, `community_market_local_enabled`,
`community_tariffs`) não é suportado. A referência BAU nativa é reconstruída a
partir do schema, por isso `evaluate_v2()` com a comparação BAU dá agora erro
quando diferem dela. Altere `schema['community_market']` e construa um novo env.
Consulte o [#366](https://github.com/citylearn-project/CityLearn/issues/366).

### Linhas de mercado do portefólio com e sem mercados

Num `MultiCommunityEnv` em que umas comunidades têm mercado comunitário e outras
não, as linhas `portfolio_*_community_market_*` passam a incluir as comunidades
sem mercado com a sua liquidação simples com a rede: sem troca local, a
importação e a exportação dos seus membros como importação e exportação da rede
depois da troca local, o seu `cost_total_control_eur` como custo liquidado e
contrafactual, e poupança e saldo do operador nulos. Antes, estas linhas
somavam os zeros que essas comunidades reportam, pelo que descreviam só as
comunidades com mercado. Os seus valores, e as quotas agregadas de troca local,
mudam apenas nesses portefólios. As linhas de distrito, as simulações, os nomes
dos KPIs e os portefólios em que todas as comunidades têm mercado, ou nenhuma
tem, não mudam. Reavalie com a versão atual os portefólios mistos anteriores
antes de comparar as suas linhas de mercado do portefólio. Consulte
[#373](https://github.com/citylearn-project/CityLearn/issues/373).

### Limites dos set points dos ocupantes

Na versão 2 da física, um ocupante de um
`LogisticRegressionOccupantInteractionBuilding` deixa de poder mover um set point
de aquecimento ou de arrefecimento para lá de `set_point_limits`, uma chave do
schema do edifício (e argumento do construtor) que por omissão vale `[15, 30]` °C.
Antes, cada alteração do ocupante era somada ao set point atual sem limite, e com
um controlo AVAC arbitrário o ocupante continuava a interagir: no primeiro
episódio do Quebec o set point de aquecimento chegava a -2323 °C com ações
aleatórias e a 3230 °C com o `BusinessAsUsualAgent`, muito fora dos limites da
sua observação
([#352](https://github.com/citylearn-project/CityLearn/issues/352),
[#357](https://github.com/citylearn-project/CityLearn/issues/357)).

- Uma alteração para no limite que atravessaria. Um valor do horário que já está
  fora do intervalo mantém-se, e o ocupante pode ainda trazer o set point de volta
  em direção ao intervalo.
- `occupant_interaction_indoor_dry_bulb_temperature_set_point_delta` continua a
  indicar a alteração que o ocupante pediu, também quando o limite a parou.
- Os limites das observações dos set points de arrefecimento e de aquecimento
  destes edifícios passam a ser o intervalo do horário alargado a
  `set_point_limits`, de onde os set points já não podem sair. Nos dois bairros do
  Quebec passam a ser [15, 30] °C em vez dos limites da temperatura interior
  (cerca de -1 a 42 °C), por isso a normalização destas features pelos limites
  muda: os agentes treinados aí com a versão 2 da física devem ser treinados de
  novo.
- Com o `NoControlAgent` nada muda: os set points do Quebec ficam entre 16,6 e
  26,6 °C no primeiro episódio. Com o `BusinessAsUsualAgent` a simulação e os KPIs
  do `evaluate()` não mudam, porque os set points muito altos caem em passos sem
  ocupantes, mas mudam as observações dos set points e as recompensas que as leem
  (como a `ComfortReward`). Com ações aleatórias mudam também os KPIs de
  desconforto; a energia, o custo e as emissões não, porque é a ação AVAC, e não o
  set point, que define o aquecimento fornecido.
- `set_point_limits` aplica-se apenas na versão 2 da física e seguintes. Defina
  `physics_version` como `1` para reproduzir os set points sem limite do
  CityLearn 3.6.0. Para alargar ou estreitar o intervalo, defina
  `set_point_limits` em cada edifício do schema, por exemplo
  `"set_point_limits": [16, 28]`.

Os limites não limitam a temperatura interior LSTM: com ações de aquecimento
aleatórias a temperatura interior do Quebec chega ainda a cerca de 60 °C, porque a
ação AVAC define o aquecimento fornecido seja qual for o set point. Essa
temperatura está fora do intervalo com que os modelos LSTM foram treinados, por
isso trate essas execuções com cuidado.

### Unidade do SOC dos VE nos ficheiros de carregadores

Na versão 2 da física, as colunas de SOC de um ficheiro de carregador
(`electric_vehicle_required_soc_departure`, `electric_vehicle_estimated_soc_arrival`
e `electric_vehicle_current_soc`) têm cada uma uma unidade, decidida uma vez a partir
da coluna inteira do ficheiro: percentagem se algum valor for superior a 1, rácio caso
contrário. Antes, a unidade era adivinhada valor a valor, pelo que um SOC de
chegada de 1 (1 %) num ficheiro em percentagem era lido como 100 %: o VE chegava
cheio e não era carregado
([#368](https://github.com/citylearn-project/CityLearn/issues/368)).

- Dados incluídos: os ficheiros dos carregadores de
  `citylearn_challenge_2022_phase_all_plus_evs`, das três demos trifásicas horárias
  e das demos a 15 segundos `citylearn_three_phase_electrical_service_demo_15s_parquet`
  e `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet` estão em
  percentagem e têm essas linhas. No ano simulado, 8 de cerca de 2800 chegadas
  dos datasets horários e 8 chegadas de cada uma dessas duas demos a 15 segundos
  partem de uma dessas linhas. `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet`
  não tem nenhuma e não muda.
  Os ficheiros `pt_rec_*` estão em rácio e não mudam.
- Os resultados desses datasets mudam. Com o `BusinessAsUsualAgent`, no ano
  completo de `citylearn_challenge_2022_phase_all_plus_evs`, o carregamento dos
  VE sobe 534 kWh (0,58 %), a importação do distrito 0,31 % e o custo 0,33 %
  (de 31 412,62 para 31 515,25 EUR); nas três demos trifásicas horárias a
  importação sobe entre 0,31 e 0,34 % e o custo entre 0,35 e 0,38 %. Na demo a
  15 segundos `citylearn_three_phase_electrical_service_demo_15s_parquet`, o
  dia em torno de uma dessas chegadas (passos 79 200 a 84 959) carrega 474 kWh
  em vez de 377 kWh. Os KPIs de partida dos VE quase não mudam (a média do
  excedente muda na quinta casa decimal), porque esses VE chegavam cheios.
- Uma coluna com todos os valores entre 0 e 1 é lida como rácio. Se estiver em
  percentagem, declare `"soc_unit": "percent"` no carregador, ao lado de
  `charger_simulation`; `"fraction"` força o rácio. Uma chave de carregador mal
  escrita, como `soc_units`, é indicada com um aviso.
- Uma coluna lida em percentagem que também tem valores entre 0 e 1 dá um aviso:
  um valor perdido acima de 1 (1,00001, por exemplo) numa coluna em rácio torna
  toda a coluna em percentagem, e 0,3 passaria a 0,3 %. Corrija esse valor ou
  declare `"soc_unit": "fraction"`.
- Defina `physics_version` como `1` para reproduzir a regra valor a valor do
  CityLearn 3.6.0.

### Valores predefinidos e nomes dos atributos dos carregadores

Os `attributes` dos carregadores são verificados pelo nome: um nome que o
carregador não aceita lança um `ValueError` que indica o carregador e sugere o
nome válido mais próximo. Antes, um nome mal escrito como `max_discharge_power`
era descartado e o limite caía no valor predefinido. `nominal_power` e
`charger_type`, que os schemas incluídos definem, passam a ser aceites
explicitamente: `nominal_power` é o valor predefinido de `max_charging_power`, e
`charger_type` é uma etiqueta sem efeito
([#369](https://github.com/citylearn-project/CityLearn/issues/369)).

Na versão 2 da física, um limite omitido deixa de dar um carregador
bidirecional de 50 kW:

- um `max_discharging_power` omitido vale 0, pelo que o carregador não pode
  descarregar (V2G desligado) e o seu espaço de ações começa em 0 em vez de -1.
  Defina `max_discharging_power` para permitir V2G;
- um `max_charging_power` omitido vale `nominal_power`, ou 50 kW quando este
  também falta;
- um aviso indica cada limite que cai num valor assumido
  (`max_charging_power`, `max_discharging_power`, `efficiency`); `efficiency`
  só quando é usado, isto é, quando nenhuma curva de eficiência o substitui.

Todos os carregadores incluídos definem todos os seus limites, pelo que os
resultados incluídos não mudam. Um schema que omite `max_discharging_power` e
contava com os 50 kW de V2G tem de o definir explicitamente, ou usar
`physics_version=1`, que mantém os 50 kW do CityLearn 3.6.0 (a verificação dos
nomes aplica-se às duas versões).

### Os espaços de observação seguem as observações

Os valores das observações, a sua ordem e `observation_names` não mudam, nem as
simulações ou os KPIs, exceto nas execuções com falhas de robustez na interface
flat dos `pt_rec_*` ou da demo de serviço elétrico trifásico: essas falhas passam
a atingir a característica que indicam. Os espaços de observação mudam, e também
tudo o que lê limites a partir deles: os agentes treinados nos datasets abaixo
devem ser retreinados, e os seus resultados anteriores não são comparáveis.

- **Ordem flat.** `env.observation_space` segue agora `env.observation_names`.
  Cada edifício lista primeiro as suas próprias características, pela ordem de
  `active_observations`, e depois as características dos seus carregadores de VE,
  aparelhos diferíveis e escadas rolantes, agrupadas por dispositivo
  (`Building.flat_observation_order`). O espaço seguia `active_observations`, pelo
  que, nos edifícios com carregadores de VE ou aparelhos diferíveis cujas
  características não estão já no fim de `active_observations`, algumas posições
  tinham os limites de outra característica. Isto afeta a interface flat de
  `pt_rec_4`, `pt_rec_15`, `pt_rec_30`, `pt_rec_100` e um edifício da demo de
  serviço elétrico trifásico (horária e de 15 s).
- **`meta` entity.** `env.observation_space['meta']` é um `EntityMetaSpace`.
  Aceita um mapeamento com `time_step`, `endogenous_time_step`,
  `seconds_per_time_step` e `spec_version`, não é achatável e não deve ser dado a
  uma rede. O código que itera sobre `observation_space.spaces` deve ignorá-lo,
  tal como ignora `observations['meta']`.
- **Limites estimados mais largos**, nas duas interfaces: margem de carregamento
  por fase (`charging_phase_*_headroom_kw` e `charging_phase_*_export_headroom_kw`)
  nos `pt_rec_*`; `cooling_demand` e `heating_demand` dos edifícios LSTM cuja ação
  de AVAC está ativa, nos datasets do desafio de 2023 e nas duas vizinhanças do
  Quebec; e os setpoints de arrefecimento e de aquecimento dos edifícios com
  interação dos ocupantes, nas duas vizinhanças do Quebec, que agora cobrem os
  limites da temperatura interior.

Estes limites continuam a ser estimativas onde o modelo não tem um limite rígido.
Sob um controlo arbitrário, por exemplo ações aleatórias ao longo de um episódio
completo do Quebec, a temperatura interior LSTM e, na versão 1 da física, os setpoints dos
ocupantes podem sair deles; `ClippedObservationWrapper` mantém esses valores
dentro do espaço. Na versão 2 da física os set points dos ocupantes ficam dentro
de `set_point_limits` (ver
[limites dos set points dos ocupantes](#limites-dos-set-points-dos-ocupantes)).

O que lê os limites:

| Consumidor | Usa | Afetado por |
|---|---|---|
| Codificadores de `RLC`, `SAC`, `MARLISA` | `observation_space` por posição | ordem e limites |
| `ClippedObservationWrapper` | `observation_space` por posição | ordem e limites |
| `DiscreteObservationWrapper`, `TabularQLearningWrapper` | intervalos (bins) a partir de `observation_space` por posição | ordem e limites |
| `NormalizedObservationWrapper` | limites do edifício por nome | apenas limites |
| `StableBaselines3Wrapper`, `RLlibSingleAgentWrapper`, `RLlibMultiAgentEnv` | declaram o espaço, não reescalam | só através de um wrapper de normalização ou do uso que o próprio algoritmo faz do espaço |
| Falhas de robustez na interface flat | característica por posição | ordem (as falhas passam a atingir a característica indicada) |

### O BAU nativo usa a carga e a produção solar do passo atual

O BAU nativo usa agora a carga e a produção FV observadas do passo que está a
planear quando pede carregamento ou descarga da bateria. Isto pode alterar os KPIs
relativos ao BAU. Reavalie as duas execuções com a versão atual e o mesmo alvo de
carregamento dos VE antes de as comparar. Para reproduzir um resultado com o BAU
anterior, use a versão ou o commit do CityLearn registado no seu manifesto
original. Consulte a [referência do BAU](baselines.md#limitações-conhecidas).

### Higiene numérica e de configuração

Estas alterações não exigem migração de datasets, schemas ou KPIs. As execuções válidas dão os mesmos resultados; alguns erros silenciosos passam a gerar exceções.

- **Ações não finitas geram exceção.** `env.step()` gera `ValueError` para ações NaN ou infinitas. Um ciclo de treino que antes continuava com uma política divergente para agora na primeira ação inválida; verifique a saída da política ou substitua os valores não finitos antes de avançar o passo.
- **Argumentos desconhecidos do construtor geram exceção.** `CityLearnEnv(..., **kwargs)` gera `TypeError` para um argumento nomeado desconhecido, com o nome válido mais próximo. Remova ou corrija os argumentos que antes eram ignorados em silêncio.
- **Os eventos de topologia são validados na construção.** Um evento que indica um membro ausente do schema, ou uma substituição de ativo com uma chave desconhecida ou um valor inválido, gera uma exceção quando o ambiente é construído. Os membros declarados no schema mas não carregados (`buildings=[...]`) continuam a ser aceites.
- **Registo (logging).** O CityLearn já não configura o logger raiz. Os avisos continuam a ser impressos; para ver as mensagens INFO, configure o registo no seu script, por exemplo `logging.basicConfig(level=logging.INFO)`. `learn(logging_level=...)` e `DataSet(logging_level=...)` definem o nível do logger `citylearn` apenas quando são passados.
- **Localização dos exports.** Por omissão, os exports vão para `./render_logs` no diretório de trabalho, e os valores relativos de `render_directory` são resolvidos face ao diretório de trabalho. Passe um `render_directory` absoluto para manter a localização anterior.
- **Invariantes físicos** geram `PhysicsInvariantError`, que é um `AssertionError`, pelo que os handlers existentes continuam a funcionar.

### Definições registadas

As definições acrescentadas desde a 3.6.0 são registadas com cada execução.
`env.get_metadata()`, o seu bloco `temporal_reproducibility` e o manifesto de
export guardam `physics_version`, `episode_split_boundary` e
`time_step_ratio_mode`; o manifesto guarda também `random_stream_version`. Com
funções de recompensa por edifício, a evidência da recompensa lista a classe e os
parâmetros da recompensa de cada edifício, incluindo `version`, em
`per_building`, porque a `MultiBuildingRewardFunction` que as combina não tem
versão própria. Valores inválidos destas definições geram `ValueError` que
indica os valores aceites, quer sejam definidos no schema quer como argumento do
construtor, e um argumento `physics_version` mal escrito recebe uma sugestão. Os
resultados da simulação não mudam
([#301](https://github.com/citylearn-project/CityLearn/issues/301),
[#302](https://github.com/citylearn-project/CityLearn/issues/302)).

### Divisões consecutivas de episódios partilham a linha de fronteira

Um episódio de N linhas de dados executa N - 1 passos de controlo: a sua última
linha é apenas a observação terminal. As divisões consecutivas (não deslizantes)
de um `episode_time_steps` inteiro avançavam N linhas, pelo que o intervalo entre
a última linha de um episódio e a primeira linha do seguinte nunca era simulado
em nenhum episódio; os episódios diários sobre dados horários nunca simulavam
23:00-24:00.

As divisões consecutivas avançam agora N - 1 linhas
(`episode_split_boundary='shared'`, o valor predefinido): cada episódio começa na
linha terminal do anterior, e todos os intervalos até à última divisão completa
são simulados uma vez. Os episódios mantêm N linhas e N - 1 passos. O primeiro
episódio não muda; os episódios seguintes começam mais cedo, pelo que os seus
resultados mudam. As divisões deslizantes, as divisões explícitas
`[(start, end), ...]` e os episódios que cobrem a janela inteira não mudam.

- Para manter episódios alinhados com o dia que cobrem todas as horas de dados
  horários, use `episode_time_steps=25`: cada episódio decorre então das 00:00 às
  00:00 seguintes.
- `episode_time_steps=1` com mais do que uma divisão gera agora um `ValueError`;
  um episódio de uma linha não tem intervalo para simular.
- `episode_split_boundary='disjoint'` (argumento do construtor ou chave do schema)
  repõe as divisões da 3.6.0.

### Topologia dinâmica: entrada de membros, armazenamento e séries do distrito

Estas alterações afetam apenas `topology_mode='dynamic'`:

- Um ficheiro de membro mais curto do que o dataset é lido como começando no passo
  de tempo `add_member` do membro. Ficava desalinhado quando
  `simulation_start_time_step` não era 0, o que também afetava a referência BAU
  nativa de todos os episódios dinâmicos que não começam na linha 0 (o sidecar do
  BAU carrega a janela do episódio). Um membro que volta a entrar depois de sair
  precisa de um ficheiro que cubra todo o horizonte e, caso contrário, gera agora
  um `ValueError`, em vez de reutilizar linhas congeladas. Um ficheiro que termina
  antes de o membro sair continua a repetir a sua última linha nos passos
  restantes, mas agora com um `UserWarning`.
- Um membro que entra (ou reentra) a meio do episódio começa o seu armazenamento
  de arrefecimento, de aquecimento e de AQS em `initial_soc`, como já acontecia
  com a sua bateria, em vez de vazio.
- `env.non_shiftable_load`, `env.solar_generation`, `env.power_outage` e as outras
  somas de distrito das séries dos edifícios mantêm os valores passados de um
  membro que saiu e só contam um membro a partir do passo em que entra, como
  `net_electricity_consumption`. Este ponto não altera os KPIs.
- Um evento no passo terminal já não move os edifícios para a linha terminal não
  executada, pelo que as suas séries guardam apenas intervalos executados.

### Passo de controlo diferente do passo do dataset

O CityLearn lê uma linha de dados por passo de controlo e não reamostra. Um
`seconds_per_time_step` diferente do passo do dataset fazia, por isso, correr o
calendário, os preços e os horários dos VE ao ritmo errado, enquanto escalava as
energias por `time_step_ratio`. Essa configuração gera agora um `ValueError`.
Defina `seconds_per_time_step` igual ao passo do dataset ou reamostre o dataset;
passe `time_step_ratio_mode='compress'` (argumento do construtor ou chave do
schema) para manter o comportamento da 3.6.0.

O passo do dataset é agora inferido a partir de todas as linhas (o intervalo
mediano) e não das duas primeiras linhas, pelo que uma linha irregular já não
reescala todas as energias. As linhas que misturam cadências, em que menos de
90 % dos intervalos coincidem com essa mediana, geram um `ValueError`; declare o
passo com `dataset_seconds_per_time_step` se as colunas de calendário não puderem
ser corrigidas. O argumento do construtor `time_step_ratio`, antes ignorado, tem
de coincidir com o rácio inferido. Todos os datasets incluídos usam o seu passo
nativo e não são afetados.

### Funções de recompensa por edifício e versões da recompensa

Quando o `reward_function.type` do schema associa edifícios a funções de
recompensa, cada função lê agora os metadados do seu próprio edifício e é
emparelhada com o seu edifício pelo nome. As funções por edifício que leem
metadados do edifício, como `SolarPenaltyReward`, usavam as capacidades de
armazenamento do primeiro edifício para todos os edifícios, pelo que as suas
recompensas mudam; as funções que leem apenas observações, como `RewardFunction`,
dão as mesmas recompensas. Retreine as políticas treinadas com um schema destes.
Nenhum dataset incluído usa funções de recompensa por edifício.

`Electric_Vehicles_Reward_Function`, `ComfortReward` e
`SolarPenaltyAndComfortReward` aceitam um atributo `version`, e a versão 2 é a
predefinida. A versão 2 corrige a penalização da partida dos VE, acrescenta a
recompensa de base e segue o modo de AVAC no termo de conforto, como descreve a
visão geral das funções de recompensa da documentação. Todos os schemas incluídos
que usam estas recompensas definem `"version": 2`, pelo que as recompensas de
`citylearn_challenge_2022_phase_all_plus_evs`, das demos trifásicas, dos datasets
do desafio de 2023, das duas vizinhanças do Quebec e de `baeda_3dem` diferem da
3.6.0; as suas simulações e KPIs não. Retreine as políticas treinadas com estas
recompensas antes de as comparar com novas execuções, e compare políticas apenas
dentro de uma mesma versão.

A versão 1, a recompensa da 3.6.0, está obsoleta e existe apenas para reproduzir
execuções feitas com o CityLearn 3.6.0 ou anterior. Selecione-a com
`"version": 1` nos atributos da recompensa (ou
`reward_function_kwargs={"version": 1}`); gera um `DeprecationWarning` e será
removida numa versão futura. Os objetos de recompensa serializados (pickle) pela
3.6.0, por exemplo dentro de um agente ou ambiente guardado, mantêm a versão 1 sem
aviso. A evidência da recompensa nos metadados do ambiente e nos manifestos de
export regista a versão.

### Definições dos KPIs

Vários KPIs de `evaluate_v2()` mudam de definição, e a versão das definições dos
KPIs (`kpi_definition_version`) passa a `2.0.0`. As simulações não mudam; volte a
executar `evaluate_v2()` sobre os ambientes guardados, ou volte a executar os
episódios, antes de comparar com tabelas da 3.6.0. A
[referência de KPIs](kpis_reference.md#definicoes-alteradas-depois-da-360) lista
todas as linhas alteradas e o nome que mantém o seu valor da 3.6.0.

- **Os rácios do distrito face à referência** de importação, troca líquida e
  emissões são rácios dos totais do distrito em vez de médias dos rácios dos
  edifícios ([#237](https://github.com/citylearn-project/CityLearn/issues/237)).
  Os valores da 3.6.0 são publicados como `*_building_mean_ratio`, e as linhas de
  distrito do `evaluate()` legado continuam a guardá-los; nos datasets com
  carregadores de VE, com `baseline_version=1` (ver [Carregamento dos VE na baseline por omissão](#carregamento-dos-ve-na-baseline-por-omissão)).
- **As emissões do distrito** são as da importação líquida do distrito, pelo que
  a partilha local entre membros as reduz, de forma coerente com a importação e
  o custo do distrito
  ([#238](https://github.com/citylearn-project/CityLearn/issues/238)). A soma
  sobre os membros é publicada como
  `district_emissions_total_*_member_sum_kgco2`. As emissões dos edifícios não
  mudam.
- **A liquidação da resposta à procura por edifício** reparte a energia creditada
  e o défice do distrito pelos edifícios com os pesos de receita e de
  penalização, pelo que o défice e o cumprimento de cada edifício seguem a
  tolerância e o limite do distrito
  ([#240](https://github.com/citylearn-project/CityLearn/issues/240)). Os KPIs do
  distrito e todos os fluxos de caixa não mudam. A versão da definição da
  resposta à procura passa a `demand-response-audit-v2`.
- **As penalizações do fator de carga** em `evaluate_v2()` usam a potência
  importada, e as janelas sem importação ficam indefinidas em vez de um 0
  perfeito ([#241](https://github.com/citylearn-project/CityLearn/issues/241)).
  Os valores líquidos com sinal são publicados como `*_signed_net_*`; as linhas
  do `evaluate()` legado mantêm a série líquida com sinal.
- **Os valores indefinidos continuam indefinidos**: um rácio com um controlo ou
  uma referência em falta, o atraso de arranque dos aparelhos diferíveis sem
  ciclos completados e cada rácio de aparelhos diferíveis face ao BAU cujos dois
  totais são nulos (por exemplo, o rácio de ciclos falhados quando nenhuma das
  execuções falhou um ciclo, mesmo que houvesse ciclos devidos) ficam agora em
  falta em vez de 0 ou 1
  ([#243](https://github.com/citylearn-project/CityLearn/issues/243)). O código
  que lê estas células tem de tratar `None`/NaN.
- **As taxas de portefólio** de `MultiCommunityEnv` (taxas e médias de partida dos
  VE, níveis de serviço, atraso de arranque, autoconsumo) são agregadas a partir
  dos seus denominadores aditivos em vez de ponderadas por comunidade
  ([#244](https://github.com/citylearn-project/CityLearn/issues/244)). As quotas
  locais da procura e da exportação do mercado comunitário e os rácios de
  cumprimento e de cobertura da auditoria da resposta à procura são agregados da
  mesma forma, a partir da energia local mais a da rede e a partir da energia
  pedida; as novas linhas de distrito
  `district_demand_response_valid_requested_total_kwh` e
  `district_demand_response_credited_total_kwh` são as componentes do rácio de
  cumprimento ([#285](https://github.com/citylearn-project/CityLearn/issues/285)).
  Os valores do distrito e dos edifícios não mudam; volte a executar as avaliações
  de `MultiCommunityEnv` cujas linhas de portefólio compare.
- **A rampa média do BAU** é a rampa ascendente média por passo em vez da soma ao
  longo do episódio; a soma é publicada como `*_ramping_total_*_kw`
  ([#245](https://github.com/citylearn-project/CityLearn/issues/245)). O rácio
  face ao BAU não muda.

### Versão da física

As correções à física simulada estão agrupadas em definições versionadas da
física, selecionadas com a chave de schema `physics_version` ou com o argumento
`CityLearnEnv(physics_version=...)`, que tem precedência. A versão `1` é a física
do CityLearn 3.6.0 e anteriores; a versão `2`, a predefinida, contém as correções
abaixo. A referência BAU nativa de `evaluate_v2()` usa a versão do ambiente
avaliado. A versão resolvida está em `env.get_metadata()`, no seu bloco temporal e
no manifesto de exportação, tanto no nível de topo como em `comparison_context`.
`compare_manifests()` e `compare_exports()` reportam duas execuções com versões
da física diferentes como `incompatible`, com `physics_version` entre as
divergências, e um manifesto escrito antes de a versão ser registada como
`unknown`, com `physics_version` entre a evidência em falta; exporte de novo
essas execuções para as emparelhar. Para reproduzir um resultado da 3.6.0, defina
`physics_version` como `1`, e também `baseline_version` como `1` para os KPIs dos
datasets com carregadores de VE; para comparar controladores, execute-os com as
mesmas versões.

`MultiCommunityEnv` exige que todas as comunidades usem a mesma
`physics_version` e a mesma `random_stream_version`, porque os KPIs de portefólio
somam os totais das comunidades; versões misturadas geram `ValueError` na
construção. O seu `get_metadata()` regista ambas.

A versão 2 altera o seguinte nos datasets incluídos:

- **Potência de descarga da bateria.** `capacity_power_curve` descreve como a
  potência de carregamento diminui perto da carga completa, mas a versão 1
  aplicava-a também à descarga, pelo que uma bateria cheia podia descarregar
  apenas a uma fração da sua potência nominal
  ([#227](https://github.com/citylearn-project/CityLearn/issues/227)). A versão 2
  limita a descarga com um atributo separado da bateria, `discharge_power_curve`,
  que por omissão é uma curva plana em `nominal_power` e pode reduzir a potência
  com um estado de carga baixo. `InventoryBattery` mantém o seu
  `max_discharge_kw`. Isto altera todas as baterias e baterias de VE cuja
  `capacity_power_curve` diminui, o que inclui a curva predefinida, sempre que
  descarregam acima do ponto de redução: os datasets dos desafios de 2022 e 2023,
  as demos trifásicas, os datasets de vizinhanças e a maioria das baterias dos
  `pt_rec_*`.
- **Descarga da bateria durante cortes de energia.** A versão 1 limitava a
  descarga de uma bateria em ilha com uma estimativa da carga anterior ao passo,
  que ignorava a descarga do armazenamento térmico e os limites dos
  dispositivos, pelo que a bateria podia descarregar mais do que o edifício
  consumia e o excedente era reportado como corte de produção FV, mesmo sem FV
  ([#229](https://github.com/citylearn-project/CityLearn/issues/229)). A versão 2
  descarrega a bateria depois de conhecidas a procura térmica e as descargas do
  armazenamento térmico do passo e limita-a à carga em ilha que o FV deixa por
  cobrir. Com `physics_invariant_checks`, uma descarga acima dessa carga gera
  `PhysicsInvariantError`. Isto altera os cenários com cortes de energia e
  baterias, como os datasets `citylearn_challenge_2023_*` com cortes de energia
  estocásticos e os cenários de robustez, combinados e all-in dos `pt_rec_*`.
- **Energia até à carga completa de baterias degradadas.** O carregamento para na
  capacidade degradada de uma bateria, que a perda de capacidade reduz abaixo da
  sua capacidade nominal, mas a versão 1 calculava as observações entity da
  energia que uma bateria ainda pode receber a partir da capacidade nominal, pelo
  que uma bateria que a degradação tinha tornado cheia era observada com
  `can_charge` 1 e com potência de carregamento disponível. A versão 2 limita
  `energy_to_full_kwh`, `connected_ev_energy_to_full_kwh`,
  `flexible_energy_to_full_kwh` e as características de carregamento delas
  derivadas à capacidade degradada (consulte
  [energia até à carga completa](observations_reference.md#energia-até-à-carga-completa)).
  A física simulada não muda, mas os controladores que leem estas observações
  agem de forma diferente: o BAU já não reserva potência para um VE degradado que
  já está cheio, pelo que a bateria da casa já não descarrega para ele e exporta a
  energia. Isto altera o BAU nos datasets cujas baterias de VE se degradam e que
  publicam o bundle `entity_core_electrical`:
  `citylearn_challenge_2022_phase_all_plus_evs`, as demos trifásicas de ativos
  dinâmicos e de topologia dinâmica e as demos trifásicas de 15 segundos. As
  baterias sem degradação, incluindo todas as baterias dos `pt_rec_*`, e
  `citylearn_three_phase_electrical_service_demo`, que não publica o bundle, não
  mudam.

- **Margem do serviço elétrico.** O limite de importação de um edifício com
  `electrical_service` era repartido entre os carregadores de VE e a bateria na
  proporção da potência pedida, incluindo pedidos que o dispositivo não podia
  absorver, como um pedido de carregamento a uma bateria cheia ou a um
  carregador sem VE, pelo que os outros dispositivos eram limitados
  ([#231](https://github.com/citylearn-project/CityLearn/issues/231)). A versão 2
  começa por limitar cada pedido à potência que o dispositivo pode absorver nesse
  passo e reparte a margem entre essas potências; as observações de margem e a
  penalização de violação pedida usam as mesmas potências. Um controlador deixa
  assim de ser penalizado por um pedido sem efeito físico.
- **Armazenamento térmico sob um limite de serviço elétrico.** A margem era
  atribuída antes do carregamento do armazenamento térmico do passo, pelo que a
  importação podia exceder o limite enquanto a potência, a margem e a violação
  registadas ficavam dentro dele
  ([#230](https://github.com/citylearn-project/CityLearn/issues/230)). A versão 2
  atribui a margem aos carregadores de VE e à bateria depois das atualizações
  térmicas, de água quente sanitária e das cargas não deslocáveis, e regista a
  potência, a margem e a violação a partir da importação apurada do passo.
- **Arranques dos aparelhos diferíveis.** A versão 1 só permitia um arranque se o
  ciclo inteiro coubesse no sinal futuro realizado de cortes de energia, na carga,
  no FV e nos limites, que um controlador não pode conhecer, e reportava essa
  decisão através da observação `can_start`, do feedback da ação e da recusa do
  arranque pelo simulador
  ([#232](https://github.com/citylearn-project/CityLearn/issues/232)). A versão 2
  decide um arranque com base no passo atual e em o ciclo terminar ou não dentro
  do episódio. Um ciclo que mais tarde encontre um corte de energia é servido pelo
  abastecimento em ilha que as outras cargas deixam, depois delas; quando esse
  abastecimento não cobre o passo, o ciclo para e é reportado como falhado. Um
  ciclo que mais tarde encontre um pico de carga sob um limite de serviço
  elétrico continua, e qualquer excesso acima do limite é registado como
  violação, como para as outras cargas que o controlador não define.

Estas três alterações afetam os datasets `pt_rec_*`, em que todos os membros têm
um limite de serviço elétrico, e o `Building_15` das demos trifásicas.

Altera também as execuções que usam o seguinte:

- **Ficheiros de carregadores em percentagem.** A unidade do SOC é decidida uma
  vez por coluna, pelo que um SOC de 1 num ficheiro em percentagem é 1 % e não
  100 % ([#368](https://github.com/citylearn-project/CityLearn/issues/368), ver
  [unidade do SOC dos VE nos ficheiros de carregadores](#unidade-do-soc-dos-ve-nos-ficheiros-de-carregadores)).
- **Carregadores sem `max_discharging_power`.** Não podem descarregar; a versão 1
  dava-lhes 50 kW de V2G
  ([#369](https://github.com/citylearn-project/CityLearn/issues/369), ver
  [valores predefinidos e nomes dos atributos dos carregadores](#valores-predefinidos-e-nomes-dos-atributos-dos-carregadores)).
- **Set points dos ocupantes sob controlo arbitrário.** Uma alteração do ocupante
  para em `set_point_limits`, [15, 30] °C por omissão; a versão 1 não tinha limite
  ([#352](https://github.com/citylearn-project/CityLearn/issues/352), ver
  [limites dos set points dos ocupantes](#limites-dos-set-points-dos-ocupantes)).
- **VE com perda em repouso.** Um VE longe do seu carregador mantém agora a perda
  em repouso de cada passo; a versão 1 descartava-a, pelo que um
  `loss_coefficient` da bateria não nulo não tinha efeito enquanto o VE estava
  ausente ([#236](https://github.com/citylearn-project/CityLearn/issues/236)).
- **Passos com mais de uma hora.** Os limites da procura de arrefecimento e de
  aquecimento comparavam uma energia por passo com uma potência, o que limitava
  a produção de AVAC a uma hora de potência nominal por passo
  ([#235](https://github.com/citylearn-project/CityLearn/issues/235)).
- **Dimensionamento automático com resolução sub-horária.** Os depósitos de
  armazenamento são dimensionados para guardar uma hora de potência de procura de
  pico (o atributo de dimensionamento automático `duration`, em horas, altera-o)
  em vez da maior procura por passo, pelo que os dados horários são dimensionados
  como antes e os dados de 15 minutos recebem os mesmos depósitos que os dados
  horários. O dimensionamento automático do FV agrupa os anos pela resolução do
  dataset e repete a produção horária do PVWatts nos passos sub-horários; com
  resolução sub-horária falhava ou dimensionava o FV para um quarto da procura
  ([#233](https://github.com/citylearn-project/CityLearn/issues/233)).

`StorageDevice.round_trip_efficiency` devolvia a eficiência num só sentido, a raiz
quadrada de `efficiency`. Use `one_way_efficiency` para esse valor, ou
`efficiency` para a eficiência de ida e volta; `round_trip_efficiency` mantém o
seu valor, avisa com `DeprecationWarning` e será removido. Os metadados dos
dispositivos acrescentam `one_way_efficiency` e mantêm `round_trip_efficiency`
com o mesmo valor. A característica entity `round_trip_efficiency_ratio` mantém o
seu nome e valor, que é a eficiência num só sentido.
`Battery.efficiency_history` ganha agora uma entrada por carregamento ou descarga
em vez de duas. Nenhum valor simulado muda.

### Fluxos aleatórios

O CityLearn sorteia valores aleatórios para parâmetros de dispositivos não
especificados (por exemplo, a `power_efficiency_curve`, a `capacity_power_curve`
ou o `capacity_loss_coefficient` de uma bateria, ou um intervalo dado como tuplo
para um parâmetro), o estado de carga dos veículos elétricos longe do seu
carregador, as interações dos ocupantes com os setpoints e os cortes de energia
estocásticos. A nova chave de schema de nível de topo e argumento do construtor
`random_stream_version` seleciona como estes fluxos são derivados de
`random_seed` ([#248](https://github.com/citylearn-project/CityLearn/issues/248)).

`v2`, o novo valor predefinido, deriva cada fluxo com
`numpy.random.SeedSequence`, com a semente como entropia e o propósito, o objeto
e o episódio como chave de spawn, e mantém um gerador por fluxo:

- cada dispositivo sorteia os seus parâmetros como valores sucessivos do seu
  próprio fluxo, identificado pelo nome do edifício e do dispositivo; na 3.6.0,
  cada sorteio era o primeiro valor de um novo `RandomState`, pelo que todos os
  parâmetros de um dispositivo ficavam no mesmo quantil. Uma `random_seed` dada
  nos atributos de um dispositivo ou de uma bateria de VE é o fluxo próprio desse
  objeto, pelo que dispositivos com a mesma semente sorteiam os mesmos
  parâmetros, tal como um dispositivo construído isoladamente;
- cada veículo elétrico tem o seu próprio fluxo de deriva longe do carregador por
  episódio; na 3.6.0, um fluxo com a semente `random_seed + episode` era partilhado
  por todos os VE, pelo que a semente `s` no episódio 1 repetia a semente `s + 1`
  no episódio 0;
- cada ocupante tem o seu próprio fluxo por episódio; na 3.6.0, todos os
  ocupantes sorteavam `RandomState(max(random_seed, 1) + time_step)`, o mesmo
  valor em todos os edifícios e episódios, e as sementes 0 e 1 eram idênticas;
- os cortes de energia estocásticos de cada edifício são sorteados por episódio,
  incluindo o dia 0 e um último dia parcial, com durações arredondadas ao passo
  mais próximo; a 3.6.0 saltava o dia 0 e o último dia parcial, arredondava as
  durações por defeito e repetia os mesmos cortes em todos os episódios com a
  mesma janela. Uma semente dada ao modelo de cortes de energia é agora a raiz do
  fluxo desse edifício, em vez de um fluxo partilhado por todos os edifícios que
  o usam.
- um membro que uma topologia dinâmica clona a partir de `source_member_id` é
  identificado pelo seu próprio nome, pelo que sorteia os seus próprios fluxos de
  ocupantes e de dispositivos; antes mantinha as chaves da sua origem e sorteava
  exatamente o mesmo que a sua origem
  ([#304](https://github.com/citylearn-project/CityLearn/issues/304)). Nenhum
  dataset incluído clona um membro. `v1` não identifica os seus fluxos por objeto
  e não muda.

`reset(seed=s)` define `random_seed` como `s` e reinicia os fluxos por episódio
(deriva dos VE, interações dos ocupantes e cortes de energia estocásticos) na
chave de episódio 0, a chave do primeiro episódio de um ambiente construído com
`random_seed=s`. Não reconstrói o ambiente, pelo que só repete esse primeiro
episódio num ambiente novo construído com `random_seed=s`:

- a janela do episódio continua a avançar, pelo que um segundo `reset(seed=s)`
  simula a janela seguinte; `reset(seed=s, options={'episode_index': k})` simula a
  janela `k` com os fluxos do episódio 0;
- os parâmetros dos dispositivos e das baterias de VE sorteados na construção, e
  o estado de carga inicial dos VE, mantêm os valores sorteados com a semente de
  construção.

Para repetir uma execução com outra semente, construa um ambiente novo com essa
`random_seed`. `reset(options={'episode_index': k})` sem semente repete o
episódio `k` do mesmo ambiente, ou de outro construído com a mesma semente. Como
o Gymnasium recomenda, passe uma semente apenas ao primeiro reset: uma semente em
cada reset dá a todos os episódios os mesmos fluxos por episódio. A referência
BAU nativa usa os fluxos do episódio que avalia.

As execuções que não usam nenhuma destas funcionalidades aleatórias não mudam.
Para reproduzir resultados obtidos com a 3.6.0 ou anterior para a mesma semente,
defina `random_stream_version` como `v1`:

```python
env = CityLearnEnv(schema, random_seed=0, random_stream_version='v1')
```

ou acrescente `"random_stream_version": "v1"` ao schema. A versão usada é
registada em `get_metadata()['random_stream_version']`, nos metadados
`temporal_reproducibility` e no manifesto da experiência; as comparações entre
execuções com versões diferentes reportam uma divergência temporal.

Medido com as mesmas ações pseudoaleatórias e as restantes definições nos seus
valores predefinidos, `v1` reproduz os fluxos aleatórios da 3.6.0 bit a bit em
todas as execuções abaixo; `v2` altera:

- `citylearn_challenge_2022_phase_all` (168 h, curvas de bateria aleatórias):
  custo do controlo 1,171.0 → 1,171.1 EUR (+0.01%) e consumo líquido +0.1%;
- `citylearn_challenge_2022_phase_all_plus_evs` (dois episódios de 168 h, curvas
  de bateria aleatórias e deriva dos VE): consumo líquido −1.6% nos dois
  episódios, custo do controlo −0.2% e −0.1%;
- `citylearn_challenge_2023_phase_2_local_evaluation` (720 h): com o SAIFI
  incluído, os três edifícios já não partilham um único corte de energia de 15
  passos, pelo que o episódio não tem nenhum e a energia não servida normalizada
  durante cortes passa de 0.72 para 0; com SAIFI 36.5/ano, os cortes por edifício
  passam de 23/23/23 passos nos dois episódios (idênticos em todos os edifícios e
  episódios) para 9/9/34 e 5/1/4;
- `quebec_neighborhood_with_demand_response_set_points` (3 edifícios, dois
  episódios de 168 h): os sorteios dos ocupantes diferem agora por edifício e por
  episódio; os KPIs de energia, temperatura e conforto destas execuções não
  mudam.

Volte a executar as experiências estocásticas, e retreine as políticas cujos
resultados compare entre sementes, com `v2`; mantenha `v1` apenas para reproduzir
números publicados da 3.6.0.

Os agentes e as vizinhanças geradas seguem a mesma definição
([#287](https://github.com/citylearn-project/CityLearn/issues/287)).
`TabularQLearning` decidia entre exploração e aproveitamento com
`RandomState(random_seed + time_step)`, e o MARLISA com partilha de informação
baralhava a ordem pela qual os seus edifícios agem com a mesma semente, pelo que
a semente `s` no passo de tempo `t + 1` repetia a semente `s + 1` no passo de
tempo `t`. Com `v2`, um agente mantém um gerador por propósito e por episódio,
derivado da sua semente e do episódio, e adota a versão do seu ambiente, pelo que
um ambiente construído com `random_stream_version='v1'` dá aos seus agentes os
fluxos da 3.6.0. O gerador de vizinhanças
(`citylearn.end_use_load_profiles.neighborhood.Neighborhood`) usava como semente
da simulação de carga parcial `i` do edifício `b` o valor `b + i`, o que ignorava
a semente da vizinhança e repetia a simulação `i - 1` do edifício `b + 1`. O seu
novo argumento `random_stream_version`, `v2` por omissão, deriva essa semente da
semente da vizinhança, do edifício e do índice da simulação:

```python
Neighborhood(random_seed=0, random_stream_version='v1')  # 3.6.0 partial-load seeds
```

Estas alterações mudam a exploração destes agentes e, por isso, as políticas que
aprendem, e os datasets gerados de novo; as simulações e os datasets incluídos
não mudam.

### PyTorch e scikit-learn opcionais

`pip install citylearn` já não instala o PyTorch nem o scikit-learn. Instale o
extra de que o seu estudo precisa:

- `pip install "citylearn[dynamics]"` para datasets com dinâmica térmica LSTM:
  os datasets do desafio de 2023, as duas vizinhanças do Quebec, `baeda_3dem` e
  os datasets de vizinhanças EULP (`ca_alameda_county_neighborhood`,
  `tx_travis_county_neighborhood`, `vt_chittenden_county_neighborhood`);
- `pip install "citylearn[rl]"` para os controladores incluídos `SAC`, `SACRBC`,
  `MARLISA` e `MARLISARBC` (cobre também a dinâmica térmica LSTM);
- `pip install "citylearn[end_use_load_profiles]"`, que agora inclui ambos, para
  construir datasets a partir dos End-Use Load Profiles.

Sem o extra, construir um ambiente destes ou importar estes controladores gera um
`ImportError` que o indica; antes, os controladores geravam uma `Exception`
genérica. Os ambientes que já têm o PyTorch e o scikit-learn instalados continuam
a funcionar sem alterações. Para evitar as bibliotecas CUDA, instale primeiro o
PyTorch só para CPU com
`pip install torch --index-url https://download.pytorch.org/whl/cpu`. O Stable
Baselines3 não é um extra: instale `stable-baselines3>=2.4`, que suporta o
gymnasium 1.x.

### Janela de avaliação da CLI e informação do anfitrião

`citylearn simulate ... train --evaluate` avalia na janela do primeiro episódio
de treino quando `-te` não é dado; antes avaliava em toda a janela de simulação.
As execuções sem `episode_time_steps` avaliam a mesma janela que antes. Passe
`-te start end` para avaliar numa janela à escolha. O JSON de resumo do treino
regista `hostname` e `username` apenas com `--record_host`; os scripts que leem
estas chaves precisam da flag.

### Classes de agentes renomeadas

`citylearn.agents.base.BaselineAgent` passa a ser `NoControlAgent`, e
`citylearn.agents.baseline.ZeroActionBaselineAgent` passa a ser `ZeroActionAgent`.
No CityLearn, "baseline" designa o contrafactual dos KPIs, os mesmos edifícios sem
armazenamento e com FV, que os KPIs `*_baseline_*` reportam; os dois agentes são
um controlador sem controlo e um controlador de ação nula, pelo que os seus nomes
passam a dizê-lo. Os nomes antigos são aliases obsoletos das mesmas classes, pelo
que as importações existentes, os caminhos `-a` da CLI, os valores `agent.type`
do schema e os agentes serializados continuam a funcionar e apenas geram um
`DeprecationWarning`. Substitua os nomes antigos antes de uma versão futura os
remover:

```python
from citylearn.agents.base import NoControlAgent        # was BaselineAgent
from citylearn.agents.baseline import ZeroActionAgent  # was ZeroActionBaselineAgent
```

Os schemas incluídos das vizinhanças EULP e o agente predefinido dos schemas EULP
gerados usam `citylearn.agents.base.NoControlAgent`. Os resultados não mudam.

## Atualizar da 3.5.0 para a 3.6.0

### Características de descarga da bateria durante cortes de energia

Durante um corte de energia, as características entity de `storage`
`can_discharge` e `available_discharge_power_kw` reportam agora a capacidade de
descarga da bateria em vez de zero. Os controladores que as leem, incluindo o BAU
e as referências baseadas em regras, podem tomar ações diferentes durante os
cortes, pelo que a referência BAU nativa muda nos cenários com cortes de energia
sob a interface entity, como `pt_rec_30/evaluation/rec_30_robustness.json`,
`rec_30_combined.json` e `pt_rec_100/evaluation/rec_100_allin.json`. Esta
alteração pertence às mesmas definições de referência da 3.6.0 que a alteração
para datasets sem `entity_core_electrical` (`immediate-full-charge-v3` e as
restantes). Volte a executar o controlador e a sua referência nesses cenários. Os
agentes treinados com estas características podem precisar de ser retreinados.

### Referências sem o bundle `entity_core_electrical`

Nos datasets cujo schema não ativa `entity_core_electrical`, o BAU e as
referências baseadas em regras tomam ações diferentes: o BAU reserva apenas a
potência de VE que o VE pode aceitar, e nenhuma referência conta a exportação do
último intervalo como excedente FV. As versões das suas definições passam a
`immediate-full-charge-v3`, `immediate-user-target-v2`, `basic-v3`,
`smart-local-v3` e `community-v3`, e a referência BAU nativa de `evaluate_v2()`
muda com elas. Volte a executar o controlador e a sua referência antes de
comparar com resultados anteriores. Os datasets com o bundle, incluindo os
`pt_rec_*` e `citylearn_challenge_2022_phase_all_plus_evs`, não mudam.

### Referências sob a interface flat com eventos de observação de robustez

`BusinessAsUsualAgent`, `RBCBasicPolicy`, `RBCSmartPolicy` e
`RBCCommunityPolicy`, executados como controladores sob a interface flat, leem
agora as observações corrompidas, como já faziam sob a interface entity
([#192](https://github.com/citylearn-project/CityLearn/issues/192)). As suas ações
e os KPIs do controlador destas execuções podem mudar. A referência BAU nativa de
`evaluate_v2()`, as execuções sem eventos de observação e as execuções sob a
interface entity não mudam.

### O ruído de robustez fica dentro dos intervalos físicos

As execuções com `noise_std = 0`, o que inclui todos os datasets incluídos, não
mudam. Com `noise_std > 0`, a produção solar e a irradiância solar com ruído (e as
suas previsões) deixam de ser negativas e ficam a zero durante a noite, a
humidade relativa exterior fica dentro de [0, 100] % e a intensidade de carbono
deixa de ser negativa. Os sorteios do ruído são os mesmos, pelo que todos os
outros valores, e as séries de outros edifícios e sementes, não mudam. As
execuções cujas séries solares ou de carbono ficavam negativas com ruído mudam;
os agentes treinados com essas séries podem precisar de ser retreinados.
Consulte o [contrato de unidades de dados](data_unit_contract.md#ruído-de-robustez).
### Python 3.10 ou mais recente

O CityLearn exige Python 3.10 ou mais recente. Os ambientes em Python 3.9
continuam a resolver o CityLearn 3.5.0; atualize o interpretador para usar
versões posteriores.
### Apoio do veículo ao edifício durante cortes de energia

Novo e desligado por omissão: `power_outage.vehicle_to_building` no schema de um
edifício (`Building.outage_vehicle_to_building`). Sem ele nada muda: um VE não
pode descarregar enquanto a rede está em baixo. Com ele, uma ação negativa de VE
durante um corte de energia descarrega o veículo para o edifício, até à carga em
ilha que o FV e a bateria não cobrem. Os resultados só mudam para os edifícios
que ativam a opção e pedem descarga de VE durante um corte de energia.

### Ficheiros JSON com valores NumPy

Não é necessária nenhuma migração de datasets, schemas ou simulações. As
trajetórias simuladas, os KPIs e os manifestos de exportação não mudam.

- **Ficheiros JSON com valores NumPy.** `FileHandler.write_json` (em
  `citylearn.utilities` e `citylearn.utils.file_handler`) escreve os booleanos,
  inteiros e floats NumPy como booleanos e números JSON, e os arrays NumPy de
  booleanos e números como listas. Antes eram escritos como texto:
  `np.float32(2.5)` como `"2.5"`, `np.bool_(True)` como `"True"` e
  `np.array([1.0, np.nan])` como `"[ 1. nan]"`; agora são `2.5`, `true` e
  `[1.0, null]`. Um `np.float32` é escrito com o seu valor exato, pelo que
  `np.float32(0.1)` passa a `0.10000000149011612`. O código que interpretava
  estas strings tem de passar a ler números. Com `ignore_nan=False`, um float
  NumPy NaN ou infinito gera agora `ValueError`, como já acontecia com um float
  Python; antes era escrito como `"nan"`. Os namedtuples (escritos como objetos),
  os valores `Decimal` (escritos como números com o seu texto exato) e todos os
  outros valores são escritos como antes.

### Export do BAU, exports dos carregadores, CLI e codificação de ficheiros

Não é necessária nenhuma migração de datasets ou schemas. As trajetórias
simuladas e os KPIs não mudam.

- **Export das séries temporais do BAU.** `exported_data_business_as_usual_ep<N>.csv`
  tem uma linha por edifício e uma linha de distrito por cada passo de tempo
  executado, como os exports do controlo. Antes acrescentava o passo de tempo
  terminal, cujos valores repetiam o último passo executado, pelo que os totais
  somados a partir do ficheiro contavam esse passo duas vezes.
- **Exports dos carregadores.** Um carregador sem VE ligado ou a chegar escreve
  `-1.00` em `EV SOC-%`, a coluna usada quando há um VE presente. Os ficheiros de
  export dos carregadores deixam de ter uma coluna `EV SOC` separada.
- **Atributos do agente no schema.** `CityLearnEnv.load_agent()` chamado sem
  `agent` constrói o agente do schema a partir de `schema['agent']['attributes']`
  atualizado com os argumentos nomeados. Qualquer argumento nomeado, como o
  `env=` que o `Simulator` passa sempre, descartava os atributos do schema, pelo
  que `Simulator(..., agent_name=None)` construía o agente do schema com os seus
  parâmetros predefinidos. Essas execuções usam agora os parâmetros do schema;
  passe argumentos nomeados para os substituir. `"attributes": null` é lido como
  ausência de atributos. Um agente indicado explicitamente, incluindo o
  `BusinessAsUsualAgent` predefinido da CLI, continua a receber apenas os
  argumentos nomeados.
- **CLI.** `citylearn simulate ... evaluate` e `train --evaluate` terminam e
  escrevem o JSON de avaliação, também com `-te`; `train --evaluate` avalia o
  agente treinado em vez de um novo. As séries temporais da avaliação têm uma
  linha por passo de tempo executado, e uma variável que um edifício não tem é
  reportada vazia em vez de repetir a variável anterior. A CLI funciona em Python
  3.9 e 3.10.
- **Windows.** `run_work_order(..., virtual_environment_path=...)` ativa o
  ambiente com `Scripts\activate.bat` no Windows, detetado automaticamente quando
  `windows_system` não é dado. Os ficheiros JSON e YAML são lidos e escritos em
  UTF-8 em vez da página de código da configuração regional.

### Agentes e wrappers

Não é necessária nenhuma migração de datasets, schemas ou ficheiros de exportação. As
trajetórias do ambiente e os KPIs para uma dada sequência de ações não mudam; os
resultados dos agentes e wrappers abaixo mudam.

- **`TabularQLearning`.** Uma transição com `terminated=True` já não faz
  bootstrap a partir dos valores Q do estado seguinte, como no `SAC`; as
  transições truncadas continuam a fazê-lo. As tabelas Q e as ações aprendidas a
  partir delas mudam.
- **`MARLISARBC`.** A exploração usa agora o RBC passado como `rbc`. Antes
  descartava as ações do RBC e explorava com ações aleatórias enquanto continuava
  a avançar o RBC, pelo que a sua exploração e tudo o que dela é aprendido mudam.
- **`MARLISA` com `pca_compression < 1`.** As redes leem a saída da PCA
  (`int(pca_compression*(observations + coordination variables))`
  características). Estas execuções falhavam na primeira atualização da rede;
  `pca_compression=1` (o valor predefinido) não muda.
- **Wrappers discretos e tabulares.** `DiscreteObservationWrapper` coloca os
  valores acima do limite superior do espaço de observação no intervalo (bin) de
  topo; antes recebiam um índice uma posição para lá do espaço `MultiDiscrete`.
  `TabularQLearningObservationWrapper` numera os `prod(bins)` estados do seu
  espaço `Discrete` com `itertools.product` sobre os intervalos; antes enumerava
  um valor a mais por observação, declarava `prod(bins + 1) - 1` estados e dava ao
  último estado um índice fora do espaço. As tabelas Q guardadas ficam, por isso,
  indexadas de forma diferente e com outro tamanho; retreine-as. Os episódios
  cujas observações ficam dentro do espaço de observação aprendem, de resto, os
  mesmos valores Q.
- **Espaços envolvidos.** `DiscreteObservationWrapper` discretiza as observações
  e os limites do ambiente que envolve, pelo que, sobre
  `NormalizedObservationWrapper`, discretiza as características normalizadas,
  incluindo o cosseno e o seno das observações periódicas.
  `DiscreteActionWrapper` discretiza o espaço de ações do ambiente que envolve.
  `ClippedObservationWrapper` devolve listas novas em vez de recortar no próprio
  sítio as listas de observações em cache do ambiente.
- **`OnehotEncoding`.** Um valor que não é uma das classes gera `ValueError` que
  indica o valor, em vez de `IndexError`.

### Casos-limite no carregamento de dados

Não é necessária nenhuma migração de datasets, schemas ou ficheiros de exportação. Os
datasets distribuídos com o CityLearn carregam e simulam como antes: nenhum dos
seus 455 ficheiros de carregadores é interpretado de forma diferente, e nenhum dos
seus VE usa `InventoryBattery`.

- **Estados dos carregadores.** `electric_vehicle_charger_state` é interpretado
  como número. Uma célula vazia faz o pandas ler a coluna inteira como floats
  (`1.0`, `2.0`), o que transformava todos os estados desse carregador em "sem
  estado", pelo que nenhum VE chegava a ligar-se. Os valores que não são inteiros
  não negativos continuam a ser "sem estado".
- **VE com `InventoryBattery`.** `nominal_power` pode ser omitido numa bateria de
  VE do tipo `InventoryBattery`, que o deriva de `max_charge_kw` e
  `max_discharge_kw`. Uma `Battery` continua a exigi-lo.
- **SOC inicial aleatório.** Uma bateria de VE sem `initial_soc` sorteia-o
  uniformemente entre o seu `min_soc` e o seu `max_soc` (0 e 1 quando não são
  declarados, o que dá os mesmos valores que antes). Uma `InventoryBattery` com
  limites declarados recebia um sorteio em [0, 1], e a execução falhava quando
  este ficava fora deles; quando ficava dentro, o SOC inicial é agora diferente.
- **Limites de SOC entity.** Para uma `InventoryBattery` com `max_soc < 1`, as
  observações entity reportam `soc_max_ratio` como `max_soc`, e a energia e a
  potência que uma bateria ainda pode receber (`energy_to_full_kwh`,
  `connected_ev_energy_to_full_kwh`, `flexible_energy_to_full_kwh`, margem de
  carregamento e potência de carregamento disponível) param em `max_soc` em vez de
  numa bateria cheia; `usable_soc_ratio` é relativo a `max_soc`. As baterias sem
  `max_soc` dão os mesmos valores que antes.

### KPIs do distrito com topologia dinâmica

Não é necessária nenhuma migração de datasets, schemas ou ficheiros de exportação. Os
resultados com topologia estática não mudam. Com topologia dinâmica, os KPIs mudam
em dois casos; volte a executar o controlador e a sua referência antes de comparar
com resultados anteriores.

- **As séries de referência do distrito mantêm os membros que saíram.** As séries
  do distrito `net_electricity_consumption*_without_storage*` (a referência
  convencional) somavam apenas os membros ativos no momento em que eram lidas,
  enquanto as séries do controlo mantêm o consumo de cada membro nos passos em
  que pertencia ao distrito. Um membro que tinha saído desaparecia, por isso,
  apenas do lado da referência. As séries de referência somam agora todos os
  membros que estiveram ativos, cada um nos passos em que foi membro, pelo que um
  membro que entra tarde também deixa de acrescentar a sua série sem FV antes de
  entrar. Isto altera os totais de referência e de diferença do distrito
  (importação, exportação, troca líquida, emissões e custo sem o mercado
  comunitário), o rácio de exportação do distrito face à referência e os rácios de
  rampa, fator de carga e pico do distrito dos cenários com alterações de
  membros.
- **Os históricos do serviço elétrico sobrevivem aos eventos de topologia.** Os
  históricos de pressão pedida, potência total e potência por fase de um membro
  eram apagados quando este reentrava ou quando um dos seus ativos era
  acrescentado ou removido. Agora são mantidos, pelo que os KPIs de violação e de
  pressão pedida `electrical_service_*` e os KPIs de pico e de desequilíbrio por
  fase incluem os passos anteriores ao evento.

### Unidades de potência e de energia sub-horárias

Estas correções deixam inalteradas as execuções cujo passo do dataset e passo de
controlo são ambos de 3600 s. As execuções com um `seconds_per_time_step`
sub-horário, ou cuja resolução do dataset difere do passo de controlo
(`time_step_ratio` diferente de 1), podem mudar:

- As bombas de calor e os aquecedores elétricos já não excedem `nominal_power`
  quando carregam o armazenamento térmico em passos sub-horários, e
  `available_nominal_power` é uma potência em kW em qualquer duração de passo.
- Em dados sub-horários nativos (`time_step_ratio` 1), um dispositivo fornece no
  máximo `nominal_power` x duração do passo por passo. Antes podia fornecer
  3600 / `seconds_per_time_step` vezes essa energia. Os dispositivos
  dimensionados automaticamente não são afetados, porque o dimensionamento
  automático já converte a procura por linha em potência; um dispositivo cujo
  `nominal_power` foi definido como a maior procura por linha (kWh lidos como kW)
  fica agora subdimensionado.
- Durante um corte de energia, o abastecimento local disponível para os
  dispositivos e para a carga não deslocável é convertido de energia por passo em
  potência e para a resolução do dataset; com dados horários num passo de 900 s,
  as cargas recebiam antes um quarto desse abastecimento.
- As observações `cooling_demand`, `heating_demand` e `dhw_demand` convertem a
  descarga do armazenamento para a resolução do dataset, a unidade do termo do
  dispositivo e dos limites da observação.

**Dispositivos subdimensionados.** Um dispositivo que não consegue satisfazer a
procura deixada depois do seu armazenamento já não gera
`AssertionError: demand is greater than ..._device max output`. O CityLearn
limita a produção do dispositivo ao seu limite, como já fazia durante os cortes de
energia, e avisa uma vez por dispositivo e por episódio com um `RuntimeWarning`.
O défice é energia térmica não servida: é reportado por
`building_thermal_service_audit_unserved_service_energy_kwh` e
`..._unserved_service_ratio` (e pelos equivalentes do distrito) e por
`env.get_kpi_family_audit()`. Se um dataset reetiquetado de linhas horárias para
sub-horárias passar a emitir avisos, os seus dispositivos ou as suas séries de
procura não correspondem ao novo passo: dimensione automaticamente ou aumente os
dispositivos, ou reescale a procura para energia por passo.

### Estimativas, diagnósticos e opções do schema

- A estimativa da potência de base usada pela margem do serviço elétrico, pelas
  verificações de arranque dos aparelhos diferíveis, pelo limite da bateria
  durante cortes de energia e pelos KPIs de viabilidade já não subtrai duas vezes
  a descarga do armazenamento térmico, e conta a potência das escadas rolantes.
  Um estado de escada rolante pedido reduz agora a margem de importação deixada
  para as ações de VE e de bateria no mesmo passo. Isto aplica-se a qualquer
  duração de passo, mas apenas a edifícios com um limite de serviço elétrico e com
  armazenamento térmico ou escadas rolantes; nenhum dataset incluído os combina.
- `clip_reason_phase_headroom` e `clip_reason_export_headroom` só são definidos
  para as fases que transportam o ativo e para a direção limitada.
- `observations(normalize=True, periodic_normalization=False)` já não gera
  `KeyError: 'month'`.
- `set_point_hold_time_steps` no schema de um edifício chega agora aos tipos de
  edifício cujo construtor o aceita
  (`LogisticRegressionOccupantInteractionBuilding`). Os datasets das vizinhanças
  do Quebec definem-no como 4: as alterações de setpoint dos ocupantes voltam ao
  horário depois de 4 passos sem interação, em vez de se manterem até ao fim do
  episódio, o que altera os seus resultados horários. Os outros tipos de edifício
  ignoram a chave como antes.

## Atualizar da 3.4.0 para a 3.5.0

Não é necessária nenhuma migração de datasets, schemas, ficheiros de exportação ou do
BAU; os datasets e KPIs existentes não mudam. A 3.5.0 acrescenta os
[datasets REC de Portugal](portugal_rec_datasets.md) e descarrega pastas de
datasets aninhadas. Se descarregar vários datasets dentro de uma hora, defina
`CITYLEARN_GITHUB_TOKEN` (ou `GITHUB_TOKEN`) com um token do GitHub para elevar o
limite anónimo de 60 pedidos à API por hora.

## Atualizar da 3.3 para a 3.4.0

Não é necessária nenhuma migração de datasets, schemas ou ficheiros de exportação.

- **BAU.** `BusinessAsUsualAgent` continua a carregar os VE de imediato até 100%
  por omissão (`immediate-full-charge-v2`), mas agora decide a partir das
  observações entity, com as regras de bateria e de aparelhos do BAU dos
  Algorithms. A referência BAU nativa acrescentada por `evaluate_v2()` muda com
  ele, pelo que todos os KPIs `business_as_usual`, `delta_to_business_as_usual` e
  `ratio_to_business_as_usual` podem diferir da 3.3. Volte a executar o
  controlador e a sua referência; não misture valores do BAU da 3.3 e da 3.4.
  Para carregar apenas até ao SOC de partida pedido pelo utilizador, defina
  `business_as_usual_ev_charge_target='requested'` no ambiente (ou no schema) e
  use `BusinessAsUsualAgent(env, ev_charge_target='requested')`.
- **Margem ilimitada.** Nas tabelas entity, um edifício sem limite de serviço
  elétrico (ou sem limite numa fase ou direção) publica agora as suas
  características de margem (`charging_*headroom_kw`, `building_*_headroom_kw`,
  `*_phase_headroom_kw`) como 1,000,000 kW, o limite superior do seu espaço de
  observação, em vez de 0 kW. 0 kW era lido como "sem capacidade restante". Os
  modelos treinados com observações entity da 3.3 destes edifícios viam aí 0;
  retreine-os ou reavalie-os.
- **Parâmetros do BAU.** Os argumentos do construtor da 3.3 `ev_target_soc`,
  `ev_follow_required_soc`, `ev_service_margin_rate`, `ev_service_floor_rate` e
  `storage_deadband_kw` deixam de existir; os argumentos nomeados desconhecidos
  geram `ValueError`. `storage_min_soc`, `storage_max_soc` e
  `deferrable_start_action` mantêm os seus nomes e valores predefinidos. Consulte
  o [guia das referências](baselines.md#parâmetros-predefinidos).
- **Nomes removidos.** `NormalPolicy`, `NormalNoBatteryPolicy` e
  `ServiceOnlyBaselineAgent` foram removidos; use `BusinessAsUsualAgent`.
  `GridAwareBaselineAgent` e `CommunityAwareBaselineAgent` foram removidos; use
  `RBCSmartPolicy` e `RBCCommunityPolicy`. O código que importa estes nomes tem de
  ser atualizado antes de passar para a 3.4.0.
- **Referências baseadas em regras.** `RBCBasicPolicy`, `RBCSmartPolicy` e
  `RBCCommunityPolicy` são substituídas pelas referências Basic, Smart e Community
  validadas no repositório Soft-CPS Algorithms. As suas decisões, parâmetros e
  resultados diferem da 3.3. Passe os parâmetros como argumentos nomeados, por
  exemplo `RBCCommunityPolicy(env, community_import_threshold_kw=10.0)`.
- **Observações.** Todas as referências decidem agora a partir das observações
  entity com nome, e não a partir de objetos do simulador. O código que altera
  uma série de um edifício ou um dispositivo depois do carregamento só é visto
  pelas referências através das observações que o simulador publica para esse
  passo.
- **Identidade da experiência.** `comparison_identity()` e os metadados da
  referência BAU reportam `observation_access='entity_observations'` e incluem a
  versão da definição e os parâmetros resolvidos.

## Atualizar da 3.3.0 para a 3.3.1

Não é necessária nenhuma migração de datasets, schemas ou ficheiros de exportação. A
referência BAU nativa construída por `evaluate_v2()` usa agora a interface entity
sempre que o ambiente avaliado a usa, pelo que os schemas entity com topologia
estática e eventos de robustez nas observações `ev`, `storage` ou `pv` já não
falham. As ações e os KPIs do BAU não mudam, porque o agente BAU lê o estado do
simulador e não as observações.

## Atualizar da 3.2.0 para a 3.3.0

Não é necessária nenhuma migração de datasets, schemas ou ficheiros de exportação.

- **NumPy 2 e Python 3.12+:** `numpy<2` e `scikit-learn<=1.2.2` deixam de estar
  fixados. Os modelos de ocupantes dos datasets do Quebec são lidos a partir dos
  seus pickles sem o scikit-learn e avaliados com o NumPy, dando previsões
  idênticas bit a bit às do scikit-learn 1.2.2; carregá-los já não executa código
  do ficheiro. A aritmética cujo tipo mudou no NumPy 2 (promoção NEP 50 de
  escalares float32 com números Python) está escrita para dar o resultado do
  NumPy 1, pelo que as observações, as recompensas e as séries temporais
  simuladas são idênticas nas duas versões. Os KPIs podem diferir nos últimos
  dígitos binários (diferenças relativas da ordem de 1e-15): o NumPy 2.3 e
  posteriores somam mais de 8,192 valores por outra ordem, o que afeta os totais
  em episódios com mais de 8,192 passos de tempo e o rácio de Gini do distrito com
  mais de 90 membros, e o rácio de Gini da auditoria de equidade usa um produto
  interno BLAS, cujo último dígito depende da compilação do BLAS e do CPU.
- **Modelos de ocupantes personalizados:** os pickles de `RandomForestClassifier`
  e `DecisionTreeClassifier` são lidos da mesma forma, com qualquer protocolo de
  pickle (0 a 5) e quando o modelo foi ajustado com um
  `numpy.random.RandomState` como `random_state`. As previsões são as da versão do
  scikit-learn que guardou o modelo. As árvores de decisão best-split a partir da
  1.3, as random forests a partir da 1.4 e as árvores de decisão random-split a
  partir da 1.6 encaminham entradas em falta (NaN) com `missing_go_to_left`. As
  versões mais antigas de cada estimador rejeitam essas entradas, tal como os
  modelos com restrições monótonas guardados com o scikit-learn 1.4 a 1.8.
  Os outros modelos serializados são lidos com o scikit-learn instalado. Se este
  não conseguir ler um modelo guardado com o scikit-learn 1.2.2 ou anterior,
  instale `scikit-learn==1.2.2` com `numpy<2` (Python 3.11 ou anterior), ou volte
  a ajustar o modelo e guarde-o com a versão instalada.
- **Evidência das experiências:** os manifestos de exportação de KPIs escritos em
  Windows registam os ficheiros de entrada e o código-fonte do motor como em
  Linux e macOS (caminhos de ficheiros abaixo da raiz do dataset com `/`,
  código-fonte do motor com hash calculado com fins de linha LF), pelo que os
  exports Windows de um dataset emparelham entre localizações e os seus hashes
  podem ser verificados face aos ficheiros guardados no repositório. A evidência
  de Linux e macOS não muda. As execuções em sistemas operativos diferentes
  continuam a não emparelhar: `engine.runtime_versions` regista o SO.
  [Evidência portátil de experiências](developer_guide.md#evidência-portátil-de-experiências)
  lista as grafias de referências a ficheiros que são normalizadas e como
  atualizar uma cópia do repositório feita antes de `.gitattributes`.
- **Argumento nomeado dos agentes RL:** passe `action_scaling_coefficient=` ao
  `SAC`, ao `MARLISA` e a outros agentes `RLC`. A grafia errada
  `action_scaling_coefficienct=` continua a funcionar com um
  `DeprecationWarning`; antes, só a grafia errada tinha efeito.
- **Verificação da referência BAU nativa:** `evaluate_v2()` gera um `ValueError`
  que indica a definição quando a referência, reconstruída a partir do schema e
  dos argumentos do construtor, difere do ambiente avaliado tal como estava no seu
  último `reset()`: a ordem dos edifícios, o `simulate_power_outage` ou as ações
  ativas de um edifício, ou qualquer parâmetro dos seus dispositivos (bombas de
  calor, aquecedores, depósitos de armazenamento, FV, baterias, carregadores,
  aparelhos e baterias de VE), e não apenas as capacidades das baterias. Antes, a
  referência simulava em silêncio os valores do schema. Uma alteração feita depois
  de `reset()` não é detetada. Nesse caso, avalie com
  `include_business_as_usual=False`.

- **Descarga de datasets:** `DataSet.get_dataset(name, directory=...)` copia o
  dataset para `directory/<name>` e devolve esse caminho do schema. As descargas
  falhadas geram uma exceção em vez de ficarem em cache, e as primeiras descargas
  em simultâneo já não interferem entre si, incluindo quando substituem uma pasta
  de cache sem `schema.json`. `filelock`, já instalado com o `torch`, passa a ser
  um requisito declarado.
- **SAC e MARLISA:** os calendários predefinidos funcionam agora em episódios
  mais curtos do que o batch predefinido; valores dados inconsistentes geram
  `ValueError` em vez de `assert False`. As execuções são repetíveis a partir da
  semente do ambiente. Os agentes guardados com a 3.2.0 retomam o treino: os
  fluxos aleatórios que lhes faltam são derivados da sua semente. O MARLISA
  preenche os parâmetros do scikit-learn em falta com os valores predefinidos
  instalados e volta a ajustar o seu modelo de procura sobre todo o buffer na
  primeira atualização.

Correções que **alteram resultados** onde se aplicam:

- Ativação do armazenamento e topologia dos VE: a reserva de descarga limita a
  energia que sai de uma bateria. Uma bateria acabada de ativar usa o SOC inicial
  configurado, incluindo abaixo da reserva. Remover ou mover um carregador
  preserva a identidade do VE. Enquanto o VE está ausente, as perdas em repouso e
  a mobilidade com semente continuam a aplicar-se. Um VE acabado de ativar começa
  no SOC configurado, e uma estimativa explícita de chegada é contabilizada como
  energia externa. Os exports identificam o carregador que efetivamente serviu o
  VE.

- Cortes de energia estocásticos: os modelos incluídos sem semente explícita
  derivam agora uma a partir da semente do ambiente, da janela do episódio e do
  nome do edifício. A referência BAU nativa usa a mesma semente e o mesmo sinal de
  cortes de energia.
- Agentes: as ações coordenadas do MARLISA usam a política de cada edifício;
  `TabularQLearning` faz bootstrap com o melhor valor do estado seguinte; um
  `action_scaling_coefficient` explícito passa a ter efeito (o valor predefinido
  continua a ser 0.5).
- Referências dos KPIs: a referência BAU nativa volta a aplicar
  `simulate_power_outage`, `solar_generation` e as substituições de ações e
  observações ativas/inativas aos mesmos edifícios quando `buildings=` os lista
  noutra ordem que a do schema; com o mercado comunitário ativo, o custo legado e
  a auditoria de equidade liquidam também o contrafactual. O equipamento
  dimensionado automaticamente na referência é dimensionado sobre os mesmos dados
  que o ambiente avaliado, e não apenas sobre o episódio atual: `evaluate_v2()`
  já não falha nos datasets das vizinhanças tx, vt e ca quando os episódios são
  mais curtos do que os dados, e os KPIs do BAU dos datasets dos desafios de 2020
  e 2021 mudam porque as bombas de calor e o armazenamento da sua referência
  passam a corresponder.
- Equipamento: as baterias dimensionadas automaticamente simulam a eficiência da
  sua ficha técnica (datasets das vizinhanças tx, vt e ca), e um VE liga-se no
  máximo a um carregador por passo, o que afeta os clones de carregadores nas
  demos de topologia dinâmica.

- Datasets de VE: cada VE sorteia os seus próprios parâmetros de bateria não
  especificados (eficiência, curvas, perda de capacidade) em vez de todos
  partilharem um único conjunto. Um VE que chega começa no estado de carga de
  chegada mais recente das linhas de chegada da sua própria sessão, também quando
  só uma linha de chegada anterior o contém, ou, caso contrário, no da sua linha
  de ligação. Nunca usa uma estimativa através de uma mudança de
  `electric_vehicle_session_id`, e as referências de chegada dos KPIs e da
  auditoria de partida usam o mesmo valor.
- SAC/MARLISA: as características ou recompensas constantes durante o
  aquecimento (warm-up) são centradas, mas já não escaladas por ~1e5; a
  exploração, a amostragem do replay e o ruído da política usam geradores com
  semente; o MARLISA guarda cada transição com as suas próprias variáveis de
  coordenação e volta a ajustar o seu modelo de procura à medida que os dados se
  acumulam.
- KPIs: os rácios de troca líquida e de custo com uma referência negativa (com
  exportação líquida ou creditada pelo mercado) usam
  `1 + (control - reference) / |reference|`, pelo que um valor mais baixo continua
  a ser melhor; a referência contrafactual não troca energia com a rede durante os
  cortes de energia; os rácios multi-comunidade face a uma referência são rácios
  de totais somados.
- Controlo sub-horário com dados horários: o complemento de carga parcial da
  referência é convertido para o passo de controlo.
- Robustez: um evento `unavailable` de `asset` FV com a parte `control` ou `both`
  para a produção, e não apenas a sua telemetria.
- Observação terminal: o calendário, a meteorologia e os preços vêm da linha
  terminal, e os valores endógenos do último passo executado, como para todas as
  outras observações. A duração do episódio e a terminação não mudam.

Alterações que **preservam as trajetórias e os valores dos KPIs**: os marcadores
de tamanho zero para dispositivos ausentes, e os carregadores de VE, têm semente,
pelo que os parâmetros não usados dos marcadores são reprodutíveis e construir um
ambiente já não avança o fluxo global `random` do Python; a cache do BAU nativo
mantém apenas a referência mais recente e liberta-a antes de construir a seguinte,
pelo que chamadas repetidas a `evaluate_v2()` a meio do episódio mantêm no máximo
um ambiente de referência; e a referência carrega apenas o episódio, e não a
janela de dados inteira, quando o único dispositivo marcado para dimensionamento
automático é um FV que `solar_generation` desativa.

## Atualizar da 3.1.1 para a 3.2.0

O CityLearn suporta o Gymnasium a partir da 0.28.1 até à 2.0, exclusive. Os
nomes dos datasets são agora resolvidos face à tag `v3.2.0`. Os ficheiros de
datasets e os formatos de export existentes continuam compatíveis.

Instale `citylearn[end_use_load_profiles]` quando gerar datasets com as
ferramentas EULP/EnergyPlus. As simulações normais usam a instalação base.

- **Funções de recompensa por edifício:** `MultiBuildingRewardFunction.calculate()`
  (usada quando o `reward_function.type` do schema associa edifícios a funções)
  devolve agora um float por edifício, por exemplo `[-1.0, -2.0]` em vez do
  aninhado `[[-1.0], [-2.0]]`, como todas as outras funções de recompensa. Com
  `central_agent=True` devolve a sua soma como `[total]`. Substitua indexações
  como `reward[i][0]` por `reward[i]`.
- **Exports de KPIs:** o manifesto regista `energy_provenance`. Com
  `energy_provenance=False`, o seu `provenance_summary` e `source_destinations`
  são `null` em vez de fazerem falhar o export, e a referência BAU nativa usa a
  mesma definição.

Correções que **alteram resultados** onde se aplicam:

- Observações: os edifícios com dinâmica LSTM reportam a temperatura interior
  simulada (#165); as características de minuto e de segundo baseadas em zero
  usam um ciclo de 60 passos; os deltas de setpoint dos ocupantes e os limites de
  consumo de VE/aparelhos diferíveis foram corrigidos.
- Dinâmica: o dropout das LSTM está desativado na inferência, pelo que as
  trajetórias do modelo do Quebec são determinísticas para uma semente e diferem
  das execuções anteriores, com ruído.
- Controlo sub-horário com dados horários (`time_step_ratio` diferente de 1): as
  ações de aquecimento e de arrefecimento LSTM pedem a fração indicada da potência
  nominal, convertida em energia uma única vez; os limites de carregamento e de
  descarga do armazenamento térmico usam a mesma conversão, e o dimensionamento
  automático usa o rácio dataset/controlo de cada edifício.
- Episódios: a descarga do armazenamento térmico no primeiro passo é contada uma
  vez, e o feedback das ações, as penalizações das restrições e as séries
  dinâmicas são reiniciados em cada episódio, o que altera o segundo episódio e os
  seguintes.

Alterações que **preservam as trajetórias e os valores dos KPIs**: a opção
`energy_provenance` (ligada por omissão), o corte das entradas LSTM e os caminhos
rápidos escalares; o suporte do gymnasium 1.x; e as correções de falhas para
`hvac_mode` 0, sinais de cortes de energia de dias parciais e a CLI sem
stable-baselines3.

## Atualizar da 3.1.0 para a 3.1.1

Não é necessária nenhuma migração de datasets, schemas ou ficheiros de exportação. Os
nomes dos datasets são resolvidos por omissão face à tag `v3.1.1`; os seus
ficheiros de datasets não mudaram desde a 3.1.0.

- Os valores explícitos de `random_episode_split` no construtor têm agora
  precedência sobre o schema. Passe `None` para manter a definição do schema.
- A perda em repouso é uma fração horária composta ao longo do tempo físico
  decorrido. As trajetórias de SOC sub-horárias e os KPIs delas derivados podem,
  por isso, diferir ligeiramente.
- O dimensionamento automático converte a procura de energia em potência antes de
  dimensionar os dispositivos especificados em potência e as baterias. Verifique
  de novo o equipamento escolhido automaticamente nas experiências sub-horárias;
  o equipamento configurado explicitamente e a capacidade térmica em kWh por
  passo mantêm-se.
- As interfaces públicas de comandos de energia e a lógica de controlo do BAU
  nativo não mudam. Compare experiências com versões e definições de equipamento
  resolvidas correspondentes; os resultados corrigidos não devem ser rotulados
  como idênticos às referências sub-horárias antigas.

## Atualizar da 3.0.2 para a 3.1.0

A distribuição, o namespace de importação e o registo predefinido de datasets
continuam a ser `citylearn`, `citylearn` e `citylearn-project/CityLearn` em
`v3.1.0`. Os 32 datasets públicos mantêm-se byte a byte; não são importados
datasets de produção do CPS, e os datasets retirados na 3.0.2 continuam
retirados.

- **Comportamento do BAU:** o `BusinessAsUsualAgent` nativo pede agora
  carregamento imediato à potência máxima até 100% para os VE ligados. Os
  veículos em simultâneo partilham proporcionalmente a capacidade elétrica
  disponível. Não agenda o carregamento em função do FV, dos preços ou dos alvos
  de partida. A ordem existente do construtor mantém-se, mas as opções não
  predefinidas de alvo/prazo dos VE são rejeitadas explicitamente; use as
  políticas RBC configuráveis para essas experiências. As trajetórias do BAU
  guardadas da 3.0.2 não devem servir silenciosamente de referências da 3.1.0.
- **Contabilização corrigida:** o despacho durante cortes de energia partilha um
  único orçamento de energia entre as cargas servidas, as reservas de
  armazenamento conservam a energia, os limites elétricos usam as ações aplicadas
  e os denominadores de serviço/KPIs usam os intervalos e eventos executados.
  Alguns valores de KPIs guardados anteriormente podem, por isso, mudar. Use
  execuções com versões correspondentes ao comparar experiências; guarde a
  evidência bruta de energia, custo e serviço.
- **Exports:** os exports apenas de KPIs continuam a omitir as séries temporais
  dos episódios, mas incluem os sidecars JSON do manifesto e do serviço dos
  aparelhos diferíveis. As saídas CSV e Parquet particionado continuam a ser
  suportadas. Guarde os sidecars junto do ficheiro de KPIs exportado.
- **Históricos compactos:** o acesso público aos históricos do mercado e da
  robustez mantém os seus valores e estrutura legados, reconstruídos a pedido. Um
  registo de mercado devolvido é uma cópia instantânea: volte a atribuir um
  registo editado através do mapeamento do histórico, em vez de contar com
  mutações aninhadas no próprio objeto. Materializar repetidamente os históricos
  públicos completos pode alocar muita memória; mantenha os históricos compactos
  durante a simulação e reconstrua-os quando forem necessários.
- **Schemas locais:** as raízes são resolvidas a partir da localização do schema.
  As raízes relativas ao repositório existentes também são aceites quando
  encontradas sob um diretório ascendente; uma raiz existente relativa ao schema
  tem precedência. A resolução não depende do diretório de trabalho do processo, e
  os ficheiros de entrada não são reescritos.

As alterações de desempenho preservam as trajetórias e os valores dos KPIs face à
implementação funcional corrigida. Não implicam igualdade com todos os resultados
históricos da 3.0.2. Consulte as [notas da versão 3.1.0](releases.md#v310---2026-11-02)
para o âmbito medido e as limitações.
