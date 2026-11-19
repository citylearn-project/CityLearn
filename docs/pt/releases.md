# Versões

Alterações, compatibilidade, validação e medições da versão atual do CityLearn.
O [guia de publicação](publishing.md) descreve o procedimento para mantenedores.

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
