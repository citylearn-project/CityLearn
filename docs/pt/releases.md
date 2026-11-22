# Versões

Alterações, compatibilidade, validação e medições da versão atual do CityLearn.
O [guia de publicação](publishing.md) descreve o procedimento para mantenedores.

## Por publicar

- **Atraso na resposta da bateria na BAU.** A referência usa a carga e a produção solar observadas no passo atual para decidir a ação da bateria estacionária. Os resultados face à BAU podem mudar, e o manifesto de exportação regista a nova definição. Consulte o [guia de migração](../migration.md#the-native-bau-uses-current-step-load-and-solar) e o [#190](https://github.com/citylearn-project/CityLearn/issues/190).
- **Wrappers do RLlib com o Ray atual.** `RLlibSingleAgentWrapper` e
  `RLlibMultiAgentEnv` são testados com o Ray 2.60.0 (nova API stack, Python 3.10
  a 3.14, gymnasium 1.2.2): o PPO e o SAC treinam durante algumas iterações num
  dia de `citylearn_challenge_2023_phase_2_local_evaluation` e o `RLModule`
  treinado produz ações (`tests/test_rllib_wrappers.py`, ignorado sem o Ray e
  executado no job de CI que instala o Ray). O `RLlibMultiAgentEnv` falhava
  nessa versão no primeiro `reset()`, porque não definia `agents` nem
  `possible_agents`; passa a definir ambos e os `observation_spaces` e
  `action_spaces` de cada agente. O `RLlibMultiAgentActionWrapper` ordena as
  ações pelo ID do agente e não pela ordem do dicionário. Um novo tutorial,
  [Train a controller with RLlib](https://www.citylearn.net/usage/rllib_training.html),
  treina controladores PPO de agente único e multiagente e avalia-os com
  `evaluate_v2()`; o CI executa-o. Os resultados das simulações não mudam
  ([#293](https://github.com/citylearn-project/CityLearn/issues/293)).
- **Unidades e descrições dos KPIs.** `evaluate_v2()` e o CSV de várias comunidades em formato longo incluem `unit` e `description` do catálogo. Os CSV e Parquet em formato largo mantêm as suas colunas e incluem as definições no manifesto ([#298](https://github.com/citylearn-project/CityLearn/issues/298)).
- **Ciclos das baterias no portefólio.** Os ciclos completos equivalentes usam a energia movimentada total e a capacidade nominal total das baterias. A diferença e o rácio face à execução BAU comparam os valores do portefólio. Volte a exportar os resultados anteriores do portefólio para comparar estes KPIs ([#330](https://github.com/citylearn-project/CityLearn/issues/330)).
- **Catálogo de KPIs e referência de KPIs completa.** O
  [catálogo de KPIs](KPI_V2_TREE.md) lista todos os nomes que `evaluate_v2()`
  emite, agrupados em 21 famílias, com o seu significado em inglês e português.
  É gerado a partir de `citylearn/misc/kpi_catalogue.yml`, e um teste falha quando falta
  nele um nome emitido. A [referência de KPIs](kpis_reference.md) passa a
  explicar todas as famílias, incluindo as auditorias, a proveniência da energia,
  o mercado comunitário, o conforto e a equidade. Dá as suas equações, a
  agregação ao distrito e ao portefólio e os valores indefinidos, e indica os
  KPIs canónicos de desconforto, de Gini e de share local. Os valores não mudam.
  ([#326](https://github.com/citylearn-project/CityLearn/issues/326))
- **Valores do controlo dos KPIs de forma da carga.** Com a comparação BAU,
  `evaluate_v2()` emite também o valor do controlo por trás de cada diferença de
  forma: `district_energy_grid_shape_quality_{peak_daily_average,peak_all_time_average,ramping_average,ramping_total}_control_kw`
  e `district_energy_grid_shape_quality_load_factor_penalty_{daily,monthly}_average{,_signed_net}_control_ratio`.
  As linhas existentes não mudam.
  ([#326](https://github.com/citylearn-project/CityLearn/issues/326))
- **Documentação por versão.** A raiz do site (`/` e `/stable/`) abre por omissão a última versão final,
  preservando as ligações existentes para páginas partilhadas e redirecionando para `/dev/<página>` os URLs na raiz
  que existem apenas em `master`; cada tag `v*` é publicada em `/<versão>/` e o ramo `master` em `/dev/`. Cada página
  inclui um seletor no topo e a secção **Other versions** na barra lateral esquerda a partir de `/versions.json`,
  mantendo a página equivalente aberta ao mudar de versão ou abrindo a página inicial dessa versão quando a página não
  existe nela ([`docs/pt/publishing.md`](publishing.md),
  [#296](https://github.com/citylearn-project/CityLearn/issues/296)).
- **Lint e CI (engenharia, sem alteração de resultados).** O `ruff` usa as
  regras de `pyproject.toml`: F401 (imports não usados removidos mantendo
  reexportações explícitas `as` nos módulos públicos), F841 (variáveis não
  usadas), B006 (os valores por omissão mutáveis `hidden_dim` e `hidden_size` em
  `citylearn/rl.py`, agora `None`), E722 (`except` simples) e as anteriores E9,
  F821 e NPY201. As ações de terceiros do GitHub ficam fixadas a SHAs de commit
  e o Dependabot propõe atualizações semanais. Um workflow separado
  (`.github/workflows/coverage.yml`) reporta a cobertura de testes (`pytest-cov`,
  sem bloquear) fora dos checks de pull request e o `pytest.ini` define um
  limite de 600 s por teste (`pytest-timeout`). Os resultados das simulações não
  mudam ([#289](https://github.com/citylearn-project/CityLearn/issues/289)).
- **Agentes genéricos na interface de entidades.** Na interface de entidades os
  espaços de ações e de observações são dicionários de tabelas de entidades, pelo
  que `Agent` e `ZeroActionBaselineAgent` falhavam com `AttributeError` no
  primeiro `predict()`. Passam a usar os espaços planos e a devolver vetores de
  ações no formato plano, que a interface de entidades aceita, também com
  topologia dinâmica. `SAC`, `SACRBC`, `MARLISA`, `MARLISARBC` e
  `TabularQLearning` leem vetores de observações planos e passam a levantar um
  `ValueError` que indica a interface plana. As execuções na interface plana não
  mudam ([#250](https://github.com/citylearn-project/CityLearn/issues/250)).
- **Baselines de regras como controlador de exploração do SACRBC e do
  MARLISARBC.** `rbc` aceita qualquer instância de agente, classe de agente ou
  caminho de importação, incluindo `RBCBasicPolicy`, `RBCSmartPolicy`,
  `RBCCommunityPolicy` e `BusinessAsUsualAgent`. Um controlador criado a partir
  de uma classe ou de um caminho deixa de receber os hiperparâmetros do agente
  de aprendizagem (`lr`, `batch_size`, `hidden_dimension`, ...); os restantes
  argumentos continuam a chegar-lhe. As classes `RBC` incluídas ignoravam esses
  hiperparâmetros, pelo que as suas execuções não mudam
  ([#250](https://github.com/citylearn-project/CityLearn/issues/250)).
- **Versões de recompensas.** `Electric_Vehicles_Reward_Function`,
  `ComfortReward` e `SolarPenaltyAndComfortReward` aceitam `version`, e a versão
  2 segue a definição documentada
  ([#249](https://github.com/citylearn-project/CityLearn/issues/249)). Na versão
  1, um edifício com carregadores de VE recebia apenas os termos de VE, um
  edifício sem carregadores recebia 0, e sair 0,25 ou mais abaixo do SOC de
  partida pedido somava `weights['soc_under'] ** 2`, um bónus de +25 com os pesos
  por omissão. A versão 2 soma a recompensa base MARL em todos os edifícios e
  substitui o bónus por `min(2 * w, -(w ** 2))` (-25). No modo de arrefecimento
  ou de aquecimento, a recompensa de conforto da versão 1 escolhia o serviço pela
  maior procura no passo; a versão 2 usa `hvac_mode`. A versão 2 é a versão por
  omissão, e todos os esquemas incluídos que usam estas recompensas definem
  `"version": 2`, pelo que as recompensas dos datasets
  `citylearn_challenge_2022_phase_all_plus_evs`, das demos trifásicas, do desafio
  2023, de Quebec e `baeda_3dem` mudam; as simulações e os KPIs não mudam
  ([#278](https://github.com/citylearn-project/CityLearn/issues/278)). A versão 1 fica obsoleta: existe apenas para reproduzir
  corridas feitas com o CityLearn 3.6.0 ou anterior, selecioná-la levanta um
  `DeprecationWarning`, e será removida numa versão futura. Uma única definição
  atual evita comparar políticas treinadas com recompensas diferentes. A
  evidência da recompensa nos metadados do ambiente e nos manifestos de exportação
  regista a versão.
- **Funções de recompensa por edifício.** Com `reward_function.type` definido por
  edifício, a função de cada edifício lia os metadados do primeiro edifício e as
  funções eram associadas aos edifícios pela posição. Com `SolarPenaltyReward`, um
  edifício com uma bateria de 10 kWh ao lado de um sem bateria recebia 0 em vez
  de -7,5. Cada função passa a ler os metadados do seu edifício e a ser associada
  pelo nome do edifício, também quando membros entram ou saem numa topologia
  dinâmica. Nenhum conjunto de dados incluído usa funções de recompensa por
  edifício.
- **Agentes renomeados: `NoControlAgent` e `ZeroActionAgent`.** No CityLearn,
  "baseline" designa o contrafactual dos KPIs, os mesmos edifícios sem
  armazenamento e com PV, que os KPIs `*_baseline_*` reportam. Duas classes de
  agentes usavam a palavra para outra coisa, pelo que passam a ter o nome do que
  fazem: `citylearn.agents.base.BaselineAgent`, que desativa todas as ações
  ativas, passa a `NoControlAgent`, e
  `citylearn.agents.baseline.ZeroActionBaselineAgent`, que pede zero em todas as
  ações, passa a `ZeroActionAgent` ([#297](https://github.com/citylearn-project/CityLearn/issues/297)). Os nomes antigos ficam como
  aliases obsoletos das mesmas classes até uma versão futura, pelo que imports,
  caminhos de agente na CLI e nos esquemas e agentes guardados com pickle
  continuam a funcionar, com um `DeprecationWarning` que indica a nova classe e o
  motivo. Os resultados não mudam.
- **Ações não finitas.** Uma ação NaN passava por todos os limites `min`/`max`, pelo que uma ação NaN de armazenamento se tornava a maior descarga possível (a bateria do `minute_ev_demo` ia de 50% a 0% num passo de 15 minutos, o dobro do limite de potência). O `env.step()` passa a dar `ValueError` para ações NaN ou infinitas nas duas interfaces, e o `charge()` dos armazenamentos rejeita energia não finita ([#228](https://github.com/citylearn-project/CityLearn/issues/228)).
- **Verificação de invariantes físicos.** Com `physics_invariant_checks=True`, um estado NaN ou infinito passa a ser uma violação em vez de ser lido como 0, e as verificações lançam `PhysicsInvariantError` (subclasse de `AssertionError`), pelo que o `python -O` deixa de as desligar ([#228](https://github.com/citylearn-project/CityLearn/issues/228)).
- **Identidades físicas independentes do balanço líquido.** A verificação do balanço líquido reconstrói o consumo líquido a partir das séries dos equipamentos que o produziram, pelo que um erro de contabilização dentro do modelo de um equipamento passava: no `tests/data/minute_ev_demo`, 100 kWh somados ao consumo de uma carga não deslocável de 1,0 kWh não levantavam nenhum erro. O `physics_invariant_checks` passa a verificar também identidades que comparam cada série com as entradas e os estados do modelo. A eletricidade de cada bomba de calor e de cada aquecedor elétrico tem de igualar o calor produzido, incluindo a carga do armazenamento, dividido pelo COP ou pela eficiência. O arrefecimento, o aquecimento, as AQS e a carga não deslocável servidos não podem exceder a procura. A energia armazenada numa bateria tem de variar com a energia nos terminais à sua eficiência, e uma descarga tem de parar na reserva da profundidade de descarga. Cada identidade lança `PhysicsInvariantError`. As verificações são cumpridas em todos os datasets incluídos nas duas versões da física, e os resultados não mudam ([#277](https://github.com/citylearn-project/CityLearn/issues/277)).
- **Features de prazo dos VE.** No passo em que um VE parte com energia em falta, cinco features chegavam a cerca de 1e7, muito acima dos limites de observação. Passam a saturar nos limites, mantendo o significado; as baselines e os KPIs não mudam ([#242](https://github.com/citylearn-project/CityLearn/issues/242)).
- **CLI.** `citylearn list_datasets` e `list_default_time_series_variables` escrevem um item por linha no stdout e saem com 0; `run_work_order` sai com 1 quando um trabalho falha ([#252](https://github.com/citylearn-project/CityLearn/issues/252)).
- **Configuração inválida falha cedo.** Argumentos desconhecidos do `CityLearnEnv` dão `TypeError` com sugestão; eventos de topologia com membros desconhecidos e overrides com chaves desconhecidas falham na construção; valores de override inválidos dão erro; `local_trading_enabled` aceita `"false"`, `"no"` e `"0"`; janelas de episódio malformadas ou invertidas dão um erro claro ([#253](https://github.com/citylearn-project/CityLearn/issues/253)).
- **Episódios explícitos e janela de simulação reduzida.** Só são carregadas as linhas da janela de simulação, mas uma lista explícita `episode_time_steps` só era verificada quanto a `0 <= start <= end`. Nos datasets do Quebec, cujos esquemas listam três episódios, reduzir a janela com `simulation_start_time_step`/`simulation_end_time_step` mantinha o episódio `[0, 2159]` do esquema: uma janela de 0 a 96 falhava no passo 97 com `IndexError`, e uma janela de 2200 a 2296 simulava janeiro em vez das linhas pedidas. Quando quem chama reduz a janela sem passar `episode_time_steps`, a lista do esquema passa a ser recortada à janela, e os episódios sem nenhum intervalo dentro dela são descartados; uma lista explícita, do chamador ou do esquema, que saia da janela dá `ValueError` na construção. As execuções cujos episódios estão dentro da janela não mudam ([#308](https://github.com/citylearn-project/CityLearn/issues/308)).
- **Logging e NumPy.** Importar o CityLearn deixa de chamar `logging.basicConfig` e `np.seterr`; o pacote regista através de loggers `citylearn.*`. Os avisos continuam a aparecer no stderr; configure o logging na aplicação para ver as mensagens INFO. O CLI fá-lo, e `DataSet`/`Agent.learn()` só mudam o nível do logger `citylearn` quando se passa `logging_level` ([#251](https://github.com/citylearn-project/CityLearn/issues/251)).
- **Pasta de exportação.** A pasta por omissão e os `render_directory` relativos resolvem a partir da pasta de trabalho (`./render_logs`), e não da pasta do pacote instalado ([#254](https://github.com/citylearn-project/CityLearn/issues/254)).
- **Checkpoints LSTM** carregam com `weights_only=True` no CPU (seguro a partir do torch 1.13) ([#255](https://github.com/citylearn-project/CityLearn/issues/255)).
- Os resultados e KPIs de corridas válidas não mudam: o BAU e o `RBCSmartPolicy` dão ações e tabelas do `evaluate_v2()` bit-idênticas à 3.6.0. Ver o [guia de migração](../migration.md#unreleased).
- **Saldo do operador do mercado comunitário.** Com tarifas diferentes entre membros, os importadores podem pagar um valor diferente do que os exportadores recebem pela mesma energia. Esse resíduo era registado em cada passo mas não aparecia nos KPIs; passa a ser reportado no KPI de distrito `community_operator_balance_total_eur`. Os custos dos membros não mudam e o KPI é zero com uma tarifa única, como em todos os datasets incluídos ([#239](https://github.com/citylearn-project/CityLearn/issues/239)).
- **Engenharia.** Os testes copiam os datasets para uma cache temporária própria de cada processo, e não para a cache do utilizador, o que evitava corridas concorrentes a falhar com `FileNotFoundError`; novos testes do COP da bomba de calor e do saldo do operador; o workflow de publicação pode usar a publicação confiável do PyPI (OIDC), preparada mas desligada; documentação do mercado (`settlement_version`, `grid_export_price`, `tariff_files`, `local_trading_enabled`) e correções de fórmulas e docstrings ([#256](https://github.com/citylearn-project/CityLearn/issues/256)).

### Topologia dinâmica e alinhamento de dados

Pacote de trabalho 3 da auditoria da 3.6.0 ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), em [#274](https://github.com/citylearn-project/CityLearn/pull/274). Os resultados mudam em execuções com topologia dinâmica e ficheiros de janela de membro, e em splits consecutivos de episódios; o [guia de migração](../migration.md#unreleased) indica as opções que repõem o comportamento da 3.6.0.

- **Splits consecutivos partilham a linha de fronteira.** Os splits consecutivos avançavam `episode_time_steps` linhas, pelo que o intervalo entre dois episódios nunca era simulado. Passam a avançar `episode_time_steps - 1` linhas, e todos os intervalos até ao último split completo são simulados uma vez; `episode_split_boundary='disjoint'` mantém os splits da 3.6.0. ([#247](https://github.com/citylearn-project/CityLearn/issues/247))
- **Os membros da topologia dinâmica ficam alinhados com a janela de simulação.** Um ficheiro de membro mais curto que o dataset é lido como começando no timestep do seu `add_member`, para qualquer `simulation_start_time_step` e comprimento de janela, o que também corrige as entradas do BAU nativo em episódios dinâmicos que não começam na linha 0. Um membro que volta a entrar precisa de um ficheiro full-horizon, os membros que entram a meio do episódio começam o armazenamento térmico em `initial_soc`, e as séries públicas do distrito mantêm os membros que saíram e só contam os que entram a partir da sua ativação. ([#246](https://github.com/citylearn-project/CityLearn/issues/246))
- **Um evento de topologia no step terminal** deixa de acrescentar um intervalo não executado às séries dos edifícios.
- **Um step de controlo diferente do step do dataset é recusado.** O CityLearn lê uma linha de dados por step de controlo e não reamostra, pelo que essa execução avançava o calendário, os preços e os horários dos VE ao ritmo errado. Passa a levantar um `ValueError`; `time_step_ratio_mode='compress'` mantém o comportamento da 3.6.0. O step do dataset é inferido de todas as linhas em vez das duas primeiras, e o argumento `time_step_ratio` tem de coincidir com ele. Os datasets incluídos não são afetados. ([#234](https://github.com/citylearn-project/CityLearn/issues/234))

### Definições dos KPIs

Estas alterações mudam valores de KPIs, não as simulações. A versão das definições
de KPIs passa a `2.0.0`; o [guia de migração](../migration.md#kpi-definitions)
indica o que repetir, e a [referência de KPIs](kpis_reference.md#definicoes-alteradas-depois-da-360)
lista cada linha alterada e o nome que guarda o seu valor da 3.6.0.

- **Ratios do distrito à baseline.** Os ratios de import, net exchange e
  emissões do distrito à baseline eram a média simples dos ratios dos
  edifícios, por isso dominados pelos edifícios pequenos com ratios extremos.
  Passam a ser ratios dos totais do distrito, como os ratios de custo, export
  e ao BAU. Os valores da 3.6.0 ficam em `*_building_mean_ratio`.
  ([#237](https://github.com/citylearn-project/CityLearn/issues/237))
- **Emissões do distrito.** As emissões do distrito somavam as emissões de
  cada membro, enquanto o import do distrito é líquido, por isso a partilha
  local nunca reduzia as emissões. Passam a ser as emissões do import líquido
  do distrito e coincidem com `external_purchase_emissions` da proveniência. A
  soma pelos membros fica em `district_emissions_total_*_member_sum_kgco2`.
  ([#238](https://github.com/citylearn-project/CityLearn/issues/238))
- **Settlement de demand response por edifício.** A energia creditada e o
  shortfall de cada edifício eram uma contribuição sem limite e uma parte
  igual do pedido sem tolerância, por isso não somavam ao distrito e um
  edifício podia reportar compliance total quando o pedido falhava. Passam a
  ser os valores do distrito alocados com os pesos de receita e de
  penalização. Os KPIs do distrito e os fluxos monetários não mudam; a
  contribuição sem limite fica como diagnóstico. A versão da definição passa a
  `demand-response-audit-v2`.
  ([#240](https://github.com/citylearn-project/CityLearn/issues/240))
- **Penalizações de load factor.** Eram calculadas sobre a série net com
  sinal, por isso uma janela cujo pico não era positivo dava uma penalização
  infinita ou negativa, reportada como um 0 perfeito. `evaluate_v2()` usa
  agora a potência importada e deixa indefinidas as janelas sem import; os
  valores com sinal ficam em `*_signed_net_*`, e as linhas legacy de
  `evaluate()` mantêm a série com sinal.
  ([#241](https://github.com/citylearn-project/CityLearn/issues/241))
- **KPIs de serviço indefinidos.** O atraso de arranque dos equipamentos
  diferíveis sem ciclos completados, os ratios com um operando em falta e cada
  ratio dos equipamentos diferíveis ao BAU cujos dois totais são zero (por
  exemplo, o ratio de ciclos falhados quando nenhuma das execuções falhou um
  ciclo, mesmo que tenha havido ciclos devidos) passam a ficar em falta, em vez
  de 0 ou 1.
  ([#243](https://github.com/citylearn-project/CityLearn/issues/243))
- **Taxas do portfolio.** `MultiCommunityEnv` agrega as taxas e médias de
  partida dos VE, os níveis de serviço, o atraso de arranque e o
  autoconsumo do portfolio a partir dos seus denominadores aditivos, em vez de
  os ponderar por comunidade.
  ([#244](https://github.com/citylearn-project/CityLearn/issues/244))
- **Shares do mercado comunitário e compliance de demand response no
  portfolio.** As shares locais da procura e do export do mercado comunitário
  no portfolio eram médias ponderadas pelo `weight` das comunidades. Passam a
  ser agregadas a partir da energia local e da rede. O compliance e os ratios
  de cobertura das auditorias de demand response passam a ser agregados a
  partir da energia pedida. As novas linhas de distrito
  `district_demand_response_valid_requested_total_kwh` e
  `district_demand_response_credited_total_kwh` exportam as componentes do
  compliance ratio; os valores de distrito e de edifício não mudam.
  ([#285](https://github.com/citylearn-project/CityLearn/issues/285))
- **Média de ramping do BAU.**
  `district_energy_grid_shape_quality_ramping_average_business_as_usual_kw` era
  a soma das rampas ascendentes no episódio. Passa a ser a média por transição
  de passo; a soma fica em `*_ramping_total_*_kw`.
  ([#245](https://github.com/citylearn-project/CityLearn/issues/245))

### Física

Pacote de trabalho 4 da auditoria da 3.6.0 ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), em [#279](https://github.com/citylearn-project/CityLearn/pull/279).

- **Física versionada.** `physics_version` (chave do schema e argumento do
  `CityLearnEnv`) escolhe a física de uma execução: `1` é a física da 3.6.0 e
  anteriores, e `2`, a predefinida, contém as correções do pacote de trabalho de
  física da auditoria da 3.6.0
  ([#226](https://github.com/citylearn-project/CityLearn/issues/226)). A
  referência BAU do `evaluate_v2()` usa a versão do ambiente avaliado, e os
  metadados das exportações registam-na. Ver o
  [guia de migração](../migration.md#physics-version).
- **Perdas em standby de EVs fora do carregador.** Na versão 2 da física, a
  deriva do SOC de um EV ausente parte do SOC depois da perda desse step, como
  já acontecia com EVs suspensos
  ([#236](https://github.com/citylearn-project/CityLearn/issues/236)).
- **Limites de procura AVAC em steps superiores a uma hora.** Na versão 2 da
  física, a bomba de calor e o aquecedor elétrico comparam energia com energia e
  deixam de limitar a produção a uma hora de potência nominal por step
  ([#235](https://github.com/citylearn-project/CityLearn/issues/235)).
- **Autodimensionamento com resolução inferior a uma hora.** Na versão 2 da
  física, os tanques guardam uma hora de potência de pico (o atributo `duration`
  altera-o), e o autodimensionamento do PV agrupa os anos pela resolução dos
  dados e repete o perfil horário do PVWatts
  ([#233](https://github.com/citylearn-project/CityLearn/issues/233)).
- **Potência de descarga das baterias.** Na versão 2 da física, um novo
  atributo da bateria, `discharge_power_curve`, limita a descarga (por omissão,
  plana na potência nominal), e `capacity_power_curve` passa a limitar apenas a
  carga ([#227](https://github.com/citylearn-project/CityLearn/issues/227)).
- **Descarga das baterias durante falhas de energia.** Na versão 2 da física, a
  bateria descarrega depois da procura térmica e das descargas do armazenamento
  térmico do step, e apenas até à carga isolada que o PV não cobre
  ([#229](https://github.com/citylearn-project/CityLearn/issues/229)).
- **Folga do limite de ligação.** Na versão 2 da física, cada pedido de
  carregador ou de bateria é limitado à potência que o equipamento consegue
  absorver antes de a folga ser repartida
  ([#231](https://github.com/citylearn-project/CityLearn/issues/231)).
- **Armazenamento térmico sob limite de ligação.** Na versão 2 da física, a
  folga é repartida depois das atualizações térmicas e da carga não deslocável, e
  a potência, a folga e a violação registadas vêm da importação liquidada do
  step ([#230](https://github.com/citylearn-project/CityLearn/issues/230)).
- **Arranque de equipamentos deslocáveis.** Na versão 2 da física, o arranque é
  decidido com a informação do step atual; um ciclo que depois encontra uma
  falha de energia é servido pela alimentação local que as outras cargas deixam
  e, se esta não chegar, para e é contado como falhado
  ([#232](https://github.com/citylearn-project/CityLearn/issues/232)).
- **Energia até cheio em baterias degradadas.** `Battery.charge` para na
  capacidade degradada, que a perda de capacidade baixa abaixo da nominal, mas
  as observações de entidades calculavam a energia que a bateria ainda aceita a
  partir da capacidade nominal. Uma bateria cheia por degradação era assim
  observada como podendo carregar: num ano de
  `citylearn_challenge_2022_phase_all_plus_evs` com o BAU, os carregadores
  indicaram `can_charge` 1 e `available_charge_power_kw` positivo em 35 208
  steps de carregador em que o EV não aceitava nada. O BAU reservava essa
  potência, e a bateria da casa descarregava para ela e exportava a energia. Na
  versão 2 da física, `energy_to_full_kwh`, `connected_ev_energy_to_full_kwh`,
  `flexible_energy_to_full_kwh` e as features de carga derivadas param no menor
  entre o limite de SOC e a capacidade degradada, para baterias de EV e
  estacionárias. A física simulada não muda, e baterias sem degradação, incluindo
  todas as dos `pt_rec_*`, dão as mesmas observações. Sem o bundle
  `entity_core_electrical`, nenhuma observação mostra a degradação, pelo que o
  BAU continua a estimar a folga do EV com a capacidade nominal.
- **Eficiência num sentido.** `one_way_efficiency` passa a conter a raiz
  quadrada de `efficiency`, que `round_trip_efficiency` devolvia;
  `round_trip_efficiency` mantém o valor com um `DeprecationWarning`.
  `Battery.efficiency_history` ganha uma entrada por operação em vez de duas
  ([#226](https://github.com/citylearn-project/CityLearn/issues/226)). A
  versão 1 da física reproduz a 3.6.0 bit a bit; na versão 2, a curva de
  descarga altera ligeiramente os datasets dos challenges (por exemplo, menos
  0,05% de importação do BAU em quatro semanas de
  `citylearn_challenge_2022_phase_all_plus_evs`). A correção da energia até
  cheio altera o BAU nos datasets com degradação das baterias dos EVs e com o
  bundle `entity_core_electrical`: num ano de
  `citylearn_challenge_2022_phase_all_plus_evs`, as baterias das casas exportam
  menos 51 kWh do que descarregavam para EVs cheios, a importação dos membros
  desce 46 kWh e o custo 0,03%, e a importação do distrito sobe 0,03%, porque
  essa exportação deixa de compensar a importação de outros membros; os KPIs
  de partida dos EVs não mudam. Num dia dos demos trifásicos de 15 segundos,
  essa exportação desce de 3,10 kWh para menos de 0,01 kWh e o custo do BAU sobe
  0,08 a 0,09%. Os `pt_rec_*` e
  `citylearn_three_phase_electrical_service_demo` não mudam.
- **Referências congeladas para as duas versões da física.** A auditoria de
  paridade do refactor (`scripts/audit/audit_refactor_parity.py`) e o teste de
  versões do NumPy (`tests/test_numpy_version_independence.py`) só comparavam
  execuções com referências gravadas na versão 1 da física, pelo que uma
  alteração da física por omissão passava nas duas verificações. Cada
  verificação corre agora nas duas versões e compara cada execução com a
  referência da sua versão: `scripts/audit/snapshots/refactor_parity_physics_v2.json`
  e `tests/data/numpy_version_reference_physics_v2.json` guardam a versão 2, com
  os fluxos aleatórios `v2` por omissão no teste do NumPy, e as referências da
  versão 1 não mudam. Os jobs de CI com NumPy 1.x e 2.x têm de reproduzir as duas
  referências
  ([#292](https://github.com/citylearn-project/CityLearn/issues/292)).

### Fluxos aleatórios e sementes

Pacote de trabalho 5 da auditoria da 3.6.0 ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), em [#281](https://github.com/citylearn-project/CityLearn/pull/281). Os resultados mudam em simulações com parâmetros aleatórios de equipamentos, veículos elétricos fora do carregador, ocupantes ou falhas de energia estocásticas; `random_stream_version='v1'` repõe os fluxos aleatórios da 3.6.0.

- **Os fluxos aleatórios são derivados por finalidade, objeto e episódio.** Os parâmetros aleatórios dos equipamentos, o estado de carga dos veículos elétricos fora do carregador, as interações dos ocupantes com o set-point e as falhas de energia estocásticas reutilizavam ou partilhavam fluxos aleatórios ([#248](https://github.com/citylearn-project/CityLearn/issues/248)). Cada parâmetro não especificado era o primeiro valor de um novo `RandomState`, pelo que todos ficavam no mesmo quantil; a semente da deriva dos VE era `random_seed + episode`, pelo que a semente `s` no episódio 1 repetia a semente `s + 1` no episódio 0, e um só fluxo era partilhado por todos os VE; cada ocupante usava `RandomState(max(random_seed, 1) + time_step)`, o mesmo valor em todos os edifícios e episódios; e `ReliabilityMetricsPowerOutage` ignorava o dia 0 e o último dia parcial e truncava as durações. A nova opção `random_stream_version` (chave do esquema e argumento do construtor) escolhe a derivação. A predefinição, `v2`, deriva um fluxo `numpy.random.SeedSequence` por finalidade, objeto e episódio, mantém um gerador por fluxo e gera falhas em todos os dias, com durações arredondadas ao passo mais próximo. `v1` reproduz a 3.6.0 para a mesma semente. Simulações sem estas funcionalidades aleatórias não mudam.
- **Fluxos dos agentes e da geração de bairros.** O `TabularQLearning` decidia a exploração, e o MARLISA com partilha de informação baralhava a ordem de coordenação, com `RandomState(random_seed + time_step)`, e o gerador de bairros usava `b + i` como semente da simulação de cargas parciais `i` do edifício `b`, pelo que os fluxos se sobrepunham entre sementes, passos e edifícios ([#287](https://github.com/citylearn-project/CityLearn/issues/287)). Com `v2`, os agentes mantêm um gerador `SeedSequence` por finalidade e episódio e seguem o `random_stream_version` do seu ambiente, e o `Neighborhood` aceita um argumento `random_stream_version` que deriva a semente de cada simulação de cargas parciais da semente do bairro, do edifício e do índice da simulação. A exploração dos agentes e os datasets gerados de novo mudam; as simulações e os datasets incluídos não mudam, e `v1` repõe os fluxos da 3.6.0.
- **O `TabularQLearning` passa a semear os seus espaços de ações.** As ações aleatórias de exploração, e a ação de recurso para uma observação cujos valores Q ainda são todos NaN, eram amostradas dos espaços de ações gymnasium do `TabularQLearningWrapper`, que nada semeava, pelo que o gymnasium os semeava com a entropia do sistema operativo e duas execuções com a mesma `random_seed` não se repetiam. O agente passa a semear a partir de `random_seed` cada espaço de ações que ainda não tenha semente, como o `SAC` já fazia, e um espaço que quem chama já semeou mantém o seu fluxo. Aplica-se com os dois valores de `random_stream_version`: estas ações nunca foram reprodutíveis, pelo que `v1` não tem fluxo a preservar.

### Documentação e referência da API

Parte do pacote de trabalho 9 da auditoria da 3.6.0 ([#226](https://github.com/citylearn-project/CityLearn/issues/226)). Os resultados das simulações e os KPIs não mudam.

- **`CityLearnEnv.scorecard()`** devolve as linhas do scorecard predefinido de uma tabela de `evaluate_v2()`, pela ordem do novo `CityLearnEnv.SCORECARD_DEFAULT_KPIS`, que antes só era acessível através de uma classe interna ([#263](https://github.com/citylearn-project/CityLearn/issues/263)).
- **Quickstart.** Um único quickstart com o output esperado e um segundo passo que compara `RBCBasicPolicy` com o BAU; o BAU passa a ser descrito como carregando os VE até 100% por omissão ([#260](https://github.com/citylearn-project/CityLearn/issues/260)).
- **Glossário e conceitos.** Um glossário dá a "baseline" e aos restantes termos centrais um único significado, e os conceitos centrais passam para "Getting started" ([#261](https://github.com/citylearn-project/CityLearn/issues/261)).
- **Catálogo de datasets.** Uma tabela de todos os datasets públicos, gerada a partir dos schemas: edifícios, VE, passo, janela, formato, tamanho e funcionalidades ([#262](https://github.com/citylearn-project/CityLearn/issues/262)).
- **Referência da API.** A docstring de `CityLearnEnv` foi corrigida e documenta todos os argumentos, `evaluate_v2()` documenta os argumentos e as colunas devolvidas, uma página Python API lista os módulos públicos, `citylearn.internal` deixa de ser publicado, e as chaves de calendário e de metadados dos schemas `pt_rec_*` ficam documentadas ([#263](https://github.com/citylearn-project/CityLearn/issues/263), [#264](https://github.com/citylearn-project/CityLearn/issues/264)).
- **Navegação.** Uma página de entrada dos KPIs leva às restantes páginas de KPIs, o guia de migração passa para "Project", as páginas do challenge para "History", e os comandos de validação que precisam do repositório dizem-no ([#271](https://github.com/citylearn-project/CityLearn/issues/271), [#272](https://github.com/citylearn-project/CityLearn/issues/272)).
- **Ligações e versões.** As ligações mortas foram corrigidas, um job semanal verifica as ligações externas, e cada página indica que o site documenta o `master` e onde ler a documentação de uma versão publicada ([#270](https://github.com/citylearn-project/CityLearn/issues/270), [#271](https://github.com/citylearn-project/CityLearn/issues/271)).

### Instalação, documentação e CLI

Pacote de trabalho 9 da auditoria da 3.6.0 ([#226](https://github.com/citylearn-project/CityLearn/issues/226)), parte B. As
simulações e os KPIs não mudam.

- **PyTorch e scikit-learn passam a opcionais.** Uma instalação por omissão
  ocupava cerca de 5,7 GB, sobretudo o PyTorch com as bibliotecas CUDA, embora só
  a dinâmica térmica LSTM e os controladores SAC e MARLISA o usem
  ([#259](https://github.com/citylearn-project/CityLearn/issues/259)). O `pip install citylearn` passa a instalar cerca de 200 MB.
  Os novos extras `citylearn[dynamics]` (PyTorch, para a dinâmica térmica LSTM
  dos datasets do desafio 2023, Quebec, `baeda_3dem` e bairros EULP) e
  `citylearn[rl]` (PyTorch e scikit-learn, para o SAC e o MARLISA) juntam-nos, e
  o `end_use_load_profiles` inclui ambos. Sem eles, carregar um desses datasets
  ou controladores levanta um `ImportError` que indica o extra e o comando do
  PyTorch apenas CPU. A página de instalação começa pelos passos de instalação,
  lista os extras e documenta a cache de datasets, o uso offline e todas as
  variáveis `CITYLEARN_*`.
- **Erros de dados acionáveis.** Um nome de dataset desconhecido sugere os nomes
  mais próximos e indica `DataSet().get_dataset_names()`. Um dataset Parquet sem
  pyarrow falha antes do download e indica `citylearn[parquet]`. Os erros offline
  com a cache vazia indicam a pasta da cache, `CITYLEARN_LOCAL_DATASETS_PATH` e
  como desativar o modo offline ([#268](https://github.com/citylearn-project/CityLearn/issues/268)).
- **Os notebooks de exemplo correm no CI.** A célula do agente passivo do
  notebook de controladores falhava; passa a avaliar sem a referência BAU
  ([#265](https://github.com/citylearn-project/CityLearn/issues/265)). Os notebooks simulam uma semana, instalam `citylearn[rl]` e o
  Stable Baselines3 2.4 ou mais recente em vez do pin 2.3.2, que baixava o
  gymnasium para 0.29.1, e deixam de correr o RLlib 2.10, sem wheels para Python
  3.12 ou mais recente ([#266](https://github.com/citylearn-project/CityLearn/issues/266)). Um novo job de CI executa todos os
  notebooks publicados. Um novo tutorial treina um controlador SAC do Stable
  Baselines3, avalia-o numa semana não vista e compara-o com o BAU; o notebook do
  tutorial da versão 2.1.2 é removido ([#267](https://github.com/citylearn-project/CityLearn/issues/267)).
- **Saídas dos notebooks.** As páginas dos notebooks (`usage/agents`, `usage/load_environment`,
  `usage/cli`, `usage/rl_training`) mostram as saídas de uma execução do CI: o workflow do Sphinx
  executa os notebooks com `scripts/ci/run_notebooks.py --output-dir examples` antes da compilação, e
  `check_docs.py --require-notebook-outputs` falha se uma página não tiver saídas. Os notebooks do
  repositório continuam sem saídas ([#299](https://github.com/citylearn-project/CityLearn/issues/299)).
- **CLI.** O `train --evaluate` avalia na janela do primeiro episódio de treino em
  vez do dataset inteiro. O resumo do treino só regista o nome da máquina e do
  utilizador com `--record_host`. O `simulate` mostra o caminho de cada ficheiro
  que escreve, e um agente Stable Baselines3 sem política levanta um `TypeError`
  que mostra `-ka '{"policy": "MlpPolicy"}'`. Avaliar um ambiente embrulhado
  falhava com `AttributeError` no gymnasium 1.x e passa a funcionar
  ([#269](https://github.com/citylearn-project/CityLearn/issues/269)).
- **Contribuições.** O `CONTRIBUTING.md` cobre a instalação, um subconjunto
  rápido de testes, a verificação da documentação e dos notebooks e a checklist
  de pull requests; os templates de issues passam a ser atribuídos ao maintainer
  atual, junta-se um template de perguntas, e o `ray[rllib]` deixa de ser
  dependência dos testes ([#273](https://github.com/citylearn-project/CityLearn/issues/273)).

## v3.6.0 - 2026-11-19

A 3.6.0 reúne 26 pull requests: correções da física, dos KPIs, das baselines, dos
agentes, do carregamento de dados e dos exports, passos de simulação mais rápidos,
três funcionalidades opcionais e Python 3.10 como versão mínima, com um CI mais
amplo. Os resultados só mudam onde se aplica uma correção; o
[guia de migração](../migration.md#upgrade-from-350-to-360) indica que corridas
repetir.

### Correções

Física e KPIs:

- **Potência e energia em passos inferiores a uma hora.** Vários limites
  comparavam uma potência em kW com uma energia por passo em kWh, que só
  coincidem a 3600 s. `available_nominal_power` é agora uma potência em qualquer
  duração de passo; as bombas de calor e os aquecedores elétricos já não
  excedem `nominal_power` ao carregar o armazenamento térmico; com dados
  nativos inferiores a uma hora, um equipamento fornece no máximo
  `nominal_power` x duração do passo; durante um corte, a produção local
  disponível para os equipamentos e para a carga não deslocável é convertida
  em potência e para a resolução do dataset; e as observações `cooling_demand`,
  `heating_demand` e `dhw_demand` convertem a descarga do armazenamento para a
  resolução do dataset quando `time_step_ratio` é diferente de 1.
  ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Equipamentos subdimensionados.** Um equipamento que não satisfaz a procura
  já não lança `AssertionError: demand is greater than ..._device max output`. A
  sua produção é limitada, é emitido um `RuntimeWarning` uma vez por
  equipamento e episódio, e a diferença é contabilizada como energia de serviço
  térmico não servida.
  ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Estimativa da potência de base.** A estimativa usada na margem do serviço
  elétrico e nos KPI de viabilidade já não subtrai duas vezes a descarga do
  armazenamento térmico e inclui a potência das escadas rolantes, incluindo um
  estado pedido no próprio passo.
  ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Motivos de limitação.** `clip_reason_phase_headroom` e
  `clip_reason_export_headroom` indicam apenas as fases do próprio equipamento e
  o sentido limitado.
  ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Observações normalizadas.** `observations(normalize=True,
  periodic_normalization=False)` já não lança `KeyError: 'month'`.
  ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Retenção do set point do ocupante.** `set_point_hold_time_steps` no schema
  de um edifício chega agora a `LogisticRegressionOccupantInteractionBuilding`.
  Nos datasets do bairro do Quebec (4 passos), as alterações do set point pelo
  ocupante voltam ao horário após 4 passos sem interação, em vez de se manterem
  até ao fim do episódio.
  ([#185](https://github.com/citylearn-project/CityLearn/pull/185))
- **Baseline do distrito com topologia dinâmica.** As séries de referência do
  distrito somavam só os membros ativos no momento da avaliação, enquanto as
  séries de controlo guardam o consumo passado de todos os membros; um membro que
  saía contava só do lado do controlo. Passam a somar todos os membros que
  estiveram ativos, cada um nos passos em que foi membro ([#182](https://github.com/citylearn-project/CityLearn/pull/182)).
- **Históricos do serviço elétrico em eventos de topologia.** Os históricos de
  pressão pedida e de potência total e por fase de um membro já não se apagam
  quando ele volta a entrar ou quando um dos seus equipamentos muda ([#182](https://github.com/citylearn-project/CityLearn/pull/182)).
- **Ruído de robustez.** Com `noise_std > 0`, o ruído gaussiano podia tornar
  negativas a produção solar, as irradiâncias solares e a intensidade
  carbónica, acrescentar produção durante a noite e levar a humidade relativa
  exterior para fora de [0, 100] %. Uma regra limita agora os valores com ruído:
  as grandezas solares ficam `>= 0` e sem ruído à noite, a humidade fica em
  [0, 100] % e a intensidade carbónica fica `>= 0`. O ruído gerado não muda,
  por isso os valores dentro do intervalo são idênticos bit a bit.
  ([#204](https://github.com/citylearn-project/CityLearn/pull/204))
- **Capacidade de descarga da bateria durante cortes.** Durante um corte de
  energia, a tabela entity `storage` indicava `can_discharge = 0` e
  `available_discharge_power_kw = 0`, embora a bateria possa descarregar para o
  edifício isolado até à sua carga local
  ([#220](https://github.com/citylearn-project/CityLearn/issues/220)). Estas
  features indicam agora a capacidade de descarga da bateria sem a margem de
  exportação da rede, como a #205 faz para a descarga do veículo para o
  edifício; o simulador continua a limitar a descarga à carga local. As baselines
  baseadas em regras leem `can_discharge`, pelo que passam a usar a bateria
  durante os cortes. Na semana com mais cortes de
  `pt_rec_30/evaluation/rec_30_robustness.json` e `rec_30_combined.json`, o BAU
  descarrega mais 1,2 kWh e a energia não servida normalizada durante os cortes
  desce de 0,0015 para 0,0007 e de 0,0017 para 0,0008; o custo e as emissões não
  mudam. Em `pt_rec_100/evaluation/rec_100_allin.json` as observações mudam, mas
  os KPIs do BAU dessa semana não. Os datasets sem cortes e a interface flat não
  mudam. Ver o [guia de migração](../migration.md#upgrade-from-350-to-360).
  Fecha a [#220](https://github.com/citylearn-project/CityLearn/issues/220).
  ([#221](https://github.com/citylearn-project/CityLearn/pull/221))

Baselines:

- **Baselines sem o bundle `entity_core_electrical`.** Duas alterações aplicam-se
  apenas aos datasets cujo schema não ativa esse bundle; os `pt_rec_*` e o
  `citylearn_challenge_2022_phase_all_plus_evs` ativam-no e não mudam. Primeiro,
  a bateria do BAU reservava a potência nominal do carregador para um VE ligado
  mesmo quando o VE aceitava muito menos, por exemplo no último passo antes de
  100% de SOC, e descarregava para essa procura; passa a reservar a potência que
  o VE pode aceitar, estimada a partir do SOC, da capacidade da bateria e da
  potência e eficiência do carregador observados, como o simulador calcula
  `available_charge_power_kw`
  ([#190](https://github.com/citylearn-project/CityLearn/issues/190)). Segundo,
  todas as baselines tomavam a exportação do intervalo anterior como excedente
  PV, pelo que, quando uma descarga da bateria ultrapassava a carga e era
  exportada, a bateria voltava a carregar da rede no passo seguinte (22,8 kWh
  nas primeiras 48 horas do `citylearn_three_phase_electrical_service_demo` com
  o BAU); passa a contar como excedente apenas o PV acima da carga observada. As
  versões de definição passam a `immediate-full-charge-v3`,
  `immediate-user-target-v2`, `basic-v3`, `smart-local-v3` e `community-v3`. Em
  30 dias, o custo de controlo varia entre −0,2% e −2,4% e as emissões entre
  −0,8% e −2,5% para todas as baselines no `citylearn_challenge_2022_phase_all`,
  no `citylearn_challenge_2023_phase_2_local_evaluation` e no
  `citylearn_three_phase_electrical_service_demo`, exceto o BAU por omissão neste
  último, que custa mais 0,4% porque a bateria guarda agora PV que antes ia para
  o mercado da comunidade. Ver o [guia de migração](../migration.md#upgrade-from-350-to-360).
  A primeira alteração resolve a consequência 2 da [#190](https://github.com/citylearn-project/CityLearn/issues/190); a consequência 1, o atraso de um passo da bateria, mantém-se, e a [#190](https://github.com/citylearn-project/CityLearn/issues/190) continua aberta.
  ([#213](https://github.com/citylearn-project/CityLearn/pull/213))
- **Baselines leem observações corrompidas na interface flat.** Na interface
  flat, o env corrompe apenas os vetores flat, e as baselines, que leem
  observações entity, decidiam a partir de valores sem corrupção; na interface
  entity liam os valores corrompidos
  ([#192](https://github.com/citylearn-project/CityLearn/issues/192)). Usadas
  como controladores (`predict(observations)`), recebem agora os eventos de
  observação de robustez do timestep aplicados às suas observações entity, tal
  como a interface entity os aplica, e tomam as mesmas ações nas duas
  interfaces. Nenhum gerador aleatório é consumido, e as observações flat e o
  histórico de robustez do env não mudam; os KPIs do controlador em execuções
  flat com eventos de observação podem mudar. A referência BAU nativa de
  `evaluate_v2()` (`predict([])`) continua sem corrupção.
  ([#212](https://github.com/citylearn-project/CityLearn/pull/212))

Agentes e wrappers ([#208](https://github.com/citylearn-project/CityLearn/pull/208)):

- **`TabularQLearning`** deixa de usar o estado seguinte nas transições terminais;
  **`MARLISARBC`** explora com o seu RBC em vez de ações aleatórias; **`MARLISA`**
  com `pca_compression < 1` dimensiona as redes para a saída da PCA.
- **Wrappers discretos** declaram exatamente os estados que codificam e
  funcionam sobre os wrappers normalizados; `ClippedObservationWrapper` já não
  altera as observações em cache do ambiente; **`OnehotEncoding`** dá `ValueError`
  para um valor fora das classes.

Carregamento de dados ([#209](https://github.com/citylearn-project/CityLearn/pull/209)):

- **Ficheiros de carregadores com estados vazios ou decimais** são lidos como
  números; uma célula vazia tornava ilegíveis todos os estados do carregador.
- **VE `InventoryBattery`** carregam sem `nominal_power`, e o **SOC inicial
  aleatório** dos VE respeita `min_soc` e `max_soc`.
- **Observações de entidades com `max_soc < 1`** contam a energia e a potência de
  carga disponíveis até `max_soc`.

Datasets e cache de datasets:

- **Caches incompletas.** Um dataset em cache passa a estar completo só quando
  existem todos os ficheiros que o `CityLearnEnv` lê do schema; uma cache
  incompleta é substituída de uma vez e o modo offline indica os ficheiros em
  falta ([#176](https://github.com/citylearn-project/CityLearn/issues/176), [#181](https://github.com/citylearn-project/CityLearn/pull/181)).
- **Variáveis de ambiente.** `CITYLEARN_OFFLINE`, `CITYLEARN_DATASET_GITHUB_ACCOUNT`,
  `CITYLEARN_DATASET_REPOSITORY` e `CITYLEARN_DATASET_TAG` são lidas quando o
  `CityLearnEnv` ou o `DataSet` é criado, e não só na importação ([#198](https://github.com/citylearn-project/CityLearn/pull/198)).
- **Nomes dos datasets.** `DataSet.get_dataset_names()` já não descarta um dataset
  cujo nome aparece no caminho pai e aceita `datasets_path` com barra final;
  chamadas simultâneas listam o GitHub uma só vez ([#199](https://github.com/citylearn-project/CityLearn/pull/199)).
- **Datasets Parquet de 15 s carregam a partir da cache.** Os schemas de
  `citylearn_three_phase_electrical_service_demo_15s_parquet`,
  `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet` e
  `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet` definiam um
  `root_directory` relativo ao repositório. O `CityLearnEnv` com o caminho do
  schema devolvido por `DataSet().get_dataset(name)` procurava os ficheiros
  dentro da pasta da cache e falhava com `FileNotFoundError`
  ([#194](https://github.com/citylearn-project/CityLearn/issues/194)). Os três
  schemas definem agora `"root_directory": null`, como os restantes datasets. O
  `CityLearnEnv(name)` e os caminhos de schema num clone do repositório já
  encontravam os ficheiros e continuam a ler a mesma pasta.
  ([#197](https://github.com/citylearn-project/CityLearn/pull/197))

Exports, CLI e ficheiros ([#207](https://github.com/citylearn-project/CityLearn/pull/207), [#202](https://github.com/citylearn-project/CityLearn/pull/202), [#203](https://github.com/citylearn-project/CityLearn/pull/203)):

- **Export do BAU** escreve só os passos executados, como os exports de controlo;
  o **export dos carregadores** sem VE escreve `-1.00` em `EV SOC-%` em vez de
  acrescentar a coluna `EV SOC`.
- **CLI.** `citylearn simulate ... evaluate` e `train --evaluate` deixam de
  falhar, e `train --evaluate` avalia o agente treinado. `load_agent()` mantém os
  atributos do agente no schema.
- **Windows.** Os ficheiros JSON e YAML são lidos e escritos em UTF-8 e
  `run_work_order()` ativa ambientes virtuais com `activate.bat`.
- **Comparação de KPIs de várias comunidades.** `load_kpis()` e `compare_exports()`
  leem exports com nomes repetidos por comunidade.
- **JSON com valores NumPy.** `FileHandler.write_json` escreve booleanos, números e
  arrays NumPy como booleanos, números e listas JSON, em vez de texto.
- **pandas 3.** Os exports deixam de emitir os dois avisos de descontinuação do
  pandas 3, e uma coluna Parquet que mistura texto e números é escrita sem erro.

### Desempenho

Nenhuma destas alterações muda resultados; cada PR comparou trajetórias e KPIs bit
a bit com o master.

- **Passos individuais.** O código de cada passo lê um único passo das séries dos
  equipamentos e do armazenamento em vez de reconstruir a série toda, e o
  `evaluate_v2()` constrói os registos sem varrer DataFrames ([#183](https://github.com/citylearn-project/CityLearn/pull/183)).
- **Janelas das séries temporais.** O `TimeSeriesData` guarda a janela de cada
  variável como atributo simples, sem `__getattribute__` em Python nem nova cópia
  em cada leitura ([#210](https://github.com/citylearn-project/CityLearn/pull/210)).
- **Contrafactuais do distrito.** As doze séries `*_without_storage*` do distrito
  somam uma matriz NumPy em vez de construir um DataFrame ([#206](https://github.com/citylearn-project/CityLearn/pull/206)).
- **Reinícios das baselines.** As baselines constroem o motor de políticas uma vez
  por agente; o primeiro `predict()` depois de um reset passa de 81 para 48 ms
  (flat) e de 54 para 22 ms (entity) em
  `citylearn_challenge_2022_phase_all_plus_evs` ([#211](https://github.com/citylearn-project/CityLearn/pull/211)).

### Novas funcionalidades opcionais

Estão desligadas por omissão; os schemas e resultados existentes não mudam.

- **Reward para a carga não servida durante falhas de energia.** Durante uma
  falha de energia o edifício não pode importar, por isso o consumo líquido é
  zero e as rewards baseadas na importação da rede não penalizam a carga que o
  PV e o armazenamento deixam por servir. `OutageUnservedEnergyReward(coefficient,
  base_reward)` subtrai `coefficient` vezes essa energia não servida a uma reward
  base, e a nova observação flat `power_outage_unserved_energy` (kWh por
  timestep, último timestep liquidado) dá-a por edifício com a definição do KPI
  `power_outage_normalized_unserved_energy_total`
  ([#188](https://github.com/citylearn-project/CityLearn/issues/188)). A reward
  funciona nas duas interfaces; a observação existe apenas na interface flat.
  Ambas são opcionais, pelo que os schemas e resultados existentes não mudam.
  ([#195](https://github.com/citylearn-project/CityLearn/pull/195))
- **Potência de rede disponível variável no tempo.** O campo
  `buildings.<name>.electrical_service.available_grid_power` aponta para uma
  série, por timestep, da potência que o edifício pode importar, em kW, num
  ficheiro com uma coluna por edifício ou numa coluna indicada
  ([#119](https://github.com/citylearn-project/CityLearn/issues/119)). O limite
  de importação em vigor num timestep é o menor entre o `limits.total.import_kw`
  estático e o valor da série, e todos os que leem o limite total de importação
  o usam: a alocação do serviço elétrico (os carregadores de EV e a bateria são
  reduzidos primeiro; a carga fixa continua servida e conta como violação), a
  viabilidade do arranque de cargas deferíveis, as observações de margem, o KPI
  de viabilidade dos EVs e o KPI de violação do serviço elétrico. Um limite de
  0 kW não isola o edifício; as falhas de energia continuam em `power_outage`.
  A nova observação flat `available_grid_power` indica o limite do próximo
  intervalo quando há série, e as baselines baseadas em regras limitam com ela
  a margem de importação planeada. Os edifícios sem série não mudam. Ver a
  [referência do schema](schema_reference.md#potencia-de-rede-disponivel).
  ([#216](https://github.com/citylearn-project/CityLearn/pull/216))
- **Apoio do veículo ao edifício durante cortes (opcional).** Com
  `power_outage.vehicle_to_building: true`, um VE ligado pode descarregar para o
  seu edifício enquanto a rede está em falha, como apoio vehicle-to-home. A
  descarga limita-se à carga não deslocável e à carga dos equipamentos térmicos
  que o PV e a bateria não cobrem, pelo que o edifício não exporta para a rede em
  falha. Na interface entity, `can_discharge` e `available_discharge_power_kw` do
  carregador indicam a capacidade de descarga do veículo durante o corte. A
  descarga pode deixar o veículo abaixo do SOC pedido para a partida; isso fica a
  cargo do controlador e aparece nos KPIs de partida dos VEs. A opção está
  desligada por omissão e, sem ela, os resultados não mudam. Ver o
  [guia de migração](../migration.md#upgrade-from-350-to-360).
  ([#205](https://github.com/citylearn-project/CityLearn/pull/205))

### Build e CI

- **Python 3.10 ou mais recente.** O CityLearn passa a exigir Python 3.10 e é
  testado em Python 3.10 a 3.14, com NumPy 1.x em 3.10. O Python 3.9 chegou ao
  fim de vida em outubro de 2025. Em Python 3.9, o `pip` continua a instalar o
  CityLearn 3.5.0. Os comandos `simulate train` e `simulate evaluate` da CLI usavam
  `datetime.UTC`, que só existe a partir do Python 3.11, e falhavam em Python
  3.10; usam agora `datetime.timezone.utc`.
  ([#218](https://github.com/citylearn-project/CityLearn/pull/218))
- **Metadados em `pyproject.toml`.** Os metadados do pacote passam do `setup.py`
  para uma tabela PEP 621 `[project]` e o `setup.py` é removido; o wheel contém os
  mesmos ficheiros ([#201](https://github.com/citylearn-project/CityLearn/pull/201)).
- **Teste de instalação e tabela de compatibilidade.** O CI constrói o wheel,
  instala-o com as dependências do PyPI e corre um teste de simulação e export em
  macOS (arm64) e Windows com Python 3.10 e 3.14; o build em Ubuntu já o corria
  sobre o wheel instalado ([#138](https://github.com/citylearn-project/CityLearn/issues/138)). O guia de instalação ganha uma tabela de
  compatibilidade das versões de Python e das dependências desde a 1.5.0
  ([#150](https://github.com/citylearn-project/CityLearn/issues/150)), e as GitHub Actions são atualizadas ([#217](https://github.com/citylearn-project/CityLearn/pull/217)).
- **Caminhos em Windows nos testes.** Os testes de descarga de datasets com
  subpastas comparam caminhos em formato POSIX ([#200](https://github.com/citylearn-project/CityLearn/pull/200)).

### Validação

No master, no commit da versão, com Python 3.10 e NumPy 2: o conjunto completo de
testes passou (1 897 testes, 2 ignorados) e a auditoria estrita passou (física,
contratos de entidades, os 41 datasets incluídos e as referências de comandos
fixos). O sdist e o wheel foram construídos e passaram o `twine check`. O wheel,
instalado com as dependências num ambiente virtual limpo, passou o `pip check` e o
teste de simulação e export do pacote instalado. Os exports CSV e Parquet do
`pt_rec_4` feitos com a 3.6.0 abriram no importador de resultados da CityLearn UI
com as mesmas 1 036 linhas de KPIs e 15 séries, e os testes da UI passaram. O CI da
versão cobriu Python 3.10 a 3.14, NumPy 1 em 3.10, as auditorias e o teste de
instalação em macOS e Windows.

### Contribuidores

- **Mark Colley** ([@M-Colley](https://github.com/M-Colley)): as correções da
  física, KPIs, baselines, agentes, carregamento de dados, cache de datasets,
  exports e build, o trabalho de desempenho e o apoio do veículo ao edifício em
  [#181](https://github.com/citylearn-project/CityLearn/pull/181), [#182](https://github.com/citylearn-project/CityLearn/pull/182), [#183](https://github.com/citylearn-project/CityLearn/pull/183), [#185](https://github.com/citylearn-project/CityLearn/pull/185), [#197](https://github.com/citylearn-project/CityLearn/pull/197), [#198](https://github.com/citylearn-project/CityLearn/pull/198), [#199](https://github.com/citylearn-project/CityLearn/pull/199), [#200](https://github.com/citylearn-project/CityLearn/pull/200), [#201](https://github.com/citylearn-project/CityLearn/pull/201), [#202](https://github.com/citylearn-project/CityLearn/pull/202), [#203](https://github.com/citylearn-project/CityLearn/pull/203), [#204](https://github.com/citylearn-project/CityLearn/pull/204), [#205](https://github.com/citylearn-project/CityLearn/pull/205), [#206](https://github.com/citylearn-project/CityLearn/pull/206), [#207](https://github.com/citylearn-project/CityLearn/pull/207), [#208](https://github.com/citylearn-project/CityLearn/pull/208), [#209](https://github.com/citylearn-project/CityLearn/pull/209), [#210](https://github.com/citylearn-project/CityLearn/pull/210), [#211](https://github.com/citylearn-project/CityLearn/pull/211), [#212](https://github.com/citylearn-project/CityLearn/pull/212), [#213](https://github.com/citylearn-project/CityLearn/pull/213),
  e a potência de rede disponível variável, o teste de instalação, a tabela de
  compatibilidade e a versão mínima de Python da #196, integrados como [#216](https://github.com/citylearn-project/CityLearn/pull/216),
  [#217](https://github.com/citylearn-project/CityLearn/pull/217) e [#218](https://github.com/citylearn-project/CityLearn/pull/218).
- **Prawal Pokharel** ([@prawalpokharel](https://github.com/prawalpokharel)): a
  reward e a observação da energia não servida durante cortes em [#195](https://github.com/citylearn-project/CityLearn/pull/195).
- **Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)): revisão,
  validação e integração da versão, divisão da #196 em [#216](https://github.com/citylearn-project/CityLearn/pull/216), [#217](https://github.com/citylearn-project/CityLearn/pull/217) e
  [#218](https://github.com/citylearn-project/CityLearn/pull/218) com a versão mínima Python 3.10, e correção da capacidade de descarga
  da bateria durante cortes em [#221](https://github.com/citylearn-project/CityLearn/pull/221).

[Alterações completas](https://github.com/citylearn-project/CityLearn/compare/v3.5.0...v3.6.0)

## v3.5.0 - 2026-11-17

- **Datasets REC de Portugal.** Quatro comunidades de energia renovável
  portuguesas sintéticas, com 4, 15, 30 e 100 membros residenciais e comerciais,
  em 2023-2024 com passo de 15 minutos: `pt_rec_4`, `pt_rec_15`, `pt_rec_30` e
  `pt_rec_100`. Nove cenários principais acrescentam alterações de membros,
  limites de importação restritos, interrupções da rede, falhas de equipamentos,
  observações em falta e resposta da procura. Seis cenários de comparação retiram
  condições individuais. São a edição v3.4 do artigo de dados *Synthetic electricity
  demand and flexibility datasets for Portuguese energy communities* (Fonseca et al.),
  publicados sob CC BY 4.0; as séries calculadas a partir de fontes públicas mantêm a
  atribuição de cada fonte. Consultar o guia dos
  [datasets REC de Portugal](portugal_rec_datasets.md).
- **Pastas de datasets com subpastas.** O `DataSet.get_dataset()` passa a
  descarregar as subpastas de um dataset; antes só trazia os ficheiros da raiz.
  Uma descarga custa dois pedidos à API do GitHub, qualquer que seja a
  profundidade, e os ficheiros vêm de raw.githubusercontent.com. Defina
  `CITYLEARN_GITHUB_TOKEN` ou `GITHUB_TOKEN` para ultrapassar o limite anónimo de
  60 pedidos por hora.
- Não é necessária migração de datasets, schemas, exports ou BAU; os datasets e
  KPIs existentes não mudam. Consultar o
  [guia de migração](../migration.md#upgrade-from-340-to-350).

## v3.4.0 - 2026-11-16

- **Dois BAU selecionáveis.** O `BusinessAsUsualAgent` carrega o EV assim que
  chega, à potência máxima, até 100% por defeito. Com
  `ev_charge_target='requested'` carrega só até ao SOC pedido pelo utilizador; a
  última ordem fica limitada à energia em falta e, abaixo da potência mínima do
  carregador, o EV fica ligeiramente abaixo do alvo em vez de o ultrapassar. O
  `business_as_usual_ev_charge_target` (construtor ou schema) escolhe o BAU que o
  `evaluate_v2()` usa como referência. Os controladores Basic,
  Smart e Community anteriores foram removidos, assim como
  os nomes `NormalPolicy`, `NormalNoBatteryPolicy`, `ServiceOnlyBaselineAgent`,
  `GridAwareBaselineAgent` e `CommunityAwareBaselineAgent`.
- **Controladores Basic, Smart e Community.** `RBCBasicPolicy`, `RBCSmartPolicy`
  e `RBCCommunityPolicy` passam a ser os controladores validados no repositório
  Algorithms da Soft-CPS. O Basic usa o preço atual e a urgência do serviço. O
  Smart agenda EVs e aparelhos com previsões de preço e de excedente solar local
  e combina autoconsumo, arbitragem e reserva na bateria. O Community acrescenta
  a energia partilhável entre membros e, com mercado comunitário, usa as baterias
  em períodos caros quando a importação comunitária atinge 15 kW.
- **Margem sem limite deixa de ser 0 kW.** Nas tabelas de entidades, um edifício
  sem limite de ligação publica a margem como 1 000 000 kW (o limite do espaço
  de observação) em vez de 0 kW, que se lia como "sem capacidade" e impedia a
  carga dos EVs nos controladores por regras.
- Todos usam as observações da interface de entidades e funcionam com as
  interfaces flat e entity, incluindo topologia dinâmica. Os KPIs relativos ao
  BAU mudam; consultar o [guia de migração](../migration.md#upgrade-from-33-to-340).

## v3.3.1 - 2026-11-16

- O `evaluate_v2()` com a referência BAU nativa deixou de falhar com
  `ValueError: robustness event ... target does not match any declared
  observation target` em schemas entity com topologia estática cujos eventos de
  robustez de observação visam as tabelas `ev`, `storage` ou `pv`. O ambiente de
  referência BAU usa agora a interface entity sempre que o ambiente avaliado a usa.
- O agente BAU lê diretamente o estado do simulador, pelo que as ações e os KPIs
  não dependem da interface. Em 13 schemas de Portugal os KPIs foram idênticos
  bit a bit. Não é necessária migração de datasets, schemas ou exports.
  Consultar o [guia de migração](../migration.md#upgrade-from-330-to-331).

## v3.3.0 - 2026-11-13

**Mark Colley** ([@M-Colley](https://github.com/M-Colley)) contribuiu com
correções de compatibilidade, BAU, KPIs, chegadas dos EVs, agentes e cache.
**Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)) e a equipa
do CityLearn fizeram a revisão e integração e acrescentaram as correções de
conservação das baterias e do ciclo de vida dos EVs.

- A reserva limita a descarga. Na ativação, a bateria parte do SOC configurado.
- O mesmo EV mantém a identidade e a evolução do SOC quando sai e volta a
  ligar-se. Os exports CSV e Parquet identificam o carregador efetivo.
- A referência BAU usa o mesmo equipamento, PV e cortes de rede que o
  controlador. Foram corrigidos rácios, custos e agregação de KPIs.
- O CI validou Python 3.9, 3.10 e 3.12, NumPy 1 e 2, as auditorias do motor
  e os exports do pacote instalado. Os ficheiros dos datasets foram preservados.
  Consultar o [guia de migração](../migration.md#upgrade-from-320-to-330).

## v3.2.0 - 2026-11-06

Responsável pela versão: **Tiago Fonseca**. Contribuição de **Mark Colley** no
[PR #169](https://github.com/citylearn-project/CityLearn/pull/169).

- Suporta Gymnasium 1.x e mantém compatibilidade com 0.28.1.
- Corrige as observações de temperatura, a inferência LSTM, a reposição do
  estado entre episódios e as conversões físicas em passos sub-horários.
- Mantém a proveniência ativa por defeito. Quando é desligada, os indicadores
  opcionais são omitidos e a configuração é aplicada ao BAU e ao manifesto.
- As recompensas por edifício passam a ser uma lista de valores simples.
  Ver o [guia de migração](../migration.md#upgrade-from-311-to-320).
- Passaram a CI, 16 cenários físicos e as verificações dos 32 datasets. Os
  seis exports abriram na UI e coincidiram os 10.274 registos de KPI comparados.
  As [notas em inglês](../releases.md#v320---2026-11-06) incluem as medições.

## v3.1.1 - 2026-11-04

Responsável: **Tiago Fonseca** ([@calofonseca](https://github.com/calofonseca)).

- Corrige as opções explícitas `True`/`False` de `random_episode_split`; `None`
  continua a herdar o schema (PR #166).
- Aplica perdas em repouso por composição da fração horária, usando a duração
  física do passo, independentemente da cadência dos dados (PR #164).
- Dimensiona bombas de calor, aquecedores e baterias a partir da potência média;
  os picos diários da bateria passam a usar períodos físicos de 24 horas.
  Os depósitos térmicos mantêm capacidade em energia para um passo de controlo.
- Mantém interfaces de energia, equipamentos explícitos, lógica BAU, definições
  dos KPIs, datasets e exports. SOC, KPIs derivados e equipamentos dimensionados
  automaticamente podem diferir devido às correções; não há migração de ficheiros.
- Simplifica a documentação e corrige o texto do tutorial (PR #154), sem alterar
  a lógica executável, os resultados guardados ou os metadados do notebook.

O runtime corrigido passou 1.249 testes, 16 cenários físicos, 32 verificações
limitadas dos datasets oficiais, contratos de entidades e seis referências de
ações fixas. A atualização da referência foi verificada contra a fórmula antiga;
o caso horário mantém os resultados. O CI da release e os comprovativos do pacote
instalado acompanham a release GitHub. Não se reivindicam uma nova campanha anual,
calibração real ou novos ganhos de desempenho nesta atualização.

## v3.1.0 - 2026-11-02

Responsável pela integração e manutenção: **Tiago Fonseca**
([@calofonseca](https://github.com/calofonseca)).

Integra as correções de física, KPIs, robustez e organização interna e as
otimizações validadas no SoftCPS Simulator 2.0.0. Mantém o nome `citylearn`, o
registo oficial `citylearn-project/CityLearn` e os 32 datasets existentes.
Nenhum dataset de produção CPS é importado; 1.254 ficheiros protegidos de dados,
fixtures e imagens permanecem iguais por SHA-256.

### Correções e compatibilidade

- Orçamento partilhado durante cortes de rede com vários carregadores,
  conservação de energia nas reservas das baterias e limites elétricos aplicados.
- Auditorias independentes de balanço, serviço EV/máquinas diferíveis,
  populações e janelas efetivamente executadas dos KPIs, robustez e proveniência.
- Caminhos dos schemas locais independentes da pasta de execução, incluindo os
  Parquet oficiais com caminhos relativos ao repositório.
- Exports CSV/Parquet e manifestos de contexto/serviço mantidos. Os históricos
  compactos permitem reconstruir os valores públicos quando necessário.
- BAU explícito `immediate-full-charge-v1`: carga imediata até 100%, com potência
  disponível partilhada proporcionalmente, sem gestão por PV/preços/partida.
  A ordem dos argumentos mantém-se; opções EV com alvos/prazos personalizados
  passam a ser rejeitadas e devem usar políticas RBC configuráveis. Os pedidos
  BAU antigos e alguns KPIs corrigidos podem diferir de 3.0.2; comparar versões
  equivalentes. Ver o [guia de migração](../migration.md#upgrade-from-302-to-310).

### Medições de desempenho

Medianas de três repetições em janelas de 1.200/1.400/1.200 transições dos casos
oficiais estático, topologia dinâmica e robustez. Verificações físicas ativas,
ações zero, mercado ativado e eventos prolongados apenas em ficheiros temporários.
Comparação com a integração funcional corrigida **antes das otimizações**:

| Caso | ms por step antes → depois | s de KPIs antes → depois | RAM após KPIs, MiB antes → depois |
|---|---:|---:|---:|
| Estático | 6,304 → 6,162 | 2,241 → 1,168 (−47,9%) | 658 → 641 |
| Dinâmico | 9,965 → 9,235 | 7,225 → 1,653 (−77,1%) | 668 → 646 |
| Robustez prolongada | 15,449 → 13,442 | 1,683 → 0,724 (−57,0%) | 1.365 → 662 (−51,5%) |

O armazenamento do mercado diminui cerca de 87%; o da robustez prolongada,
98,0% (699,61 → 13,72 MB). As 16.737 linhas de KPI e todas as trajetórias de
energia/custo coincidem exatamente antes/depois em cada uma das três repetições.
O protocolo e as medições brutas acompanham a release GitHub.

A comparação direta com 3.0.2 dá 5,298 → 6,162, 8,885 → 9,235 e
14,548 → 13,442 ms por step. As novas verificações e a cobertura adicional dos
KPIs têm custo; não há aceleração em todos os casos face a 3.0.2. Estas medições
locais não substituem campanhas anuais de todo o catálogo nem calibração real.
A RAM é medida antes da inspeção profunda ou reconstrução dos históricos públicos.

### Validação

- Suite completa: **1.138 testes passaram**, sem falhas nem skips; 44 avisos de precisão float32 do Gymnasium.
- Auditorias estritas: 16 cenários físicos, 32 datasets oficiais em sondagens
  curtas, contratos de entidades e seis referências de ações fixas passaram.
  As referências existentes não foram atualizadas para acomodar diferenças.
- Lint crítico, wheel/sdist, `twine check` e export do pacote instalado passaram.
- Documentação: 208 páginas HTML e 19.096 ligações/recursos locais, zero erros
  de ligação (40 avisos Sphinx retidos).
- Medições: 27 execuções, 34.200 transições, física ativa e equivalência exata
  de KPIs e trajetórias entre a versão funcional corrigida e a otimizada.

Os incumprimentos de SOC fisicamente inviáveis continuam visíveis. Não se
promete que todos os alvos de partida sejam atingíveis.

Versões anteriores, com as notas de validação originais: [arquivo de versões](releases_archive.md).
