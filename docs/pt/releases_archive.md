# Versões anteriores

Notas históricas, com a validação e os limites registados em cada versão.
Os comandos e os datasets mencionados referem-se à versão descrita.
Consultar as [versões atuais](releases.md) antes de executar os exemplos.

## v3.0.2 - 2026-09-09

Responsavel pela release: [@calofonseca](https://github.com/calofonseca).

### Alterado

- Removidos do registry publico os 19 datasets `ALADI`, os cinco datasets
  `rec_2023_*` e `EC_Ermesinde`.
- As capacidades do simulador mantem-se disponiveis; foram retirados apenas os
  dados publicos e o teste de integracao dependente de EC Ermesinde.

### Impacto em datasets

- A descoberta por defeito passa a devolver 32 datasets publicos.
- Utilizadores dos datasets retirados devem fornecer localmente o schema e os
  respetivos ficheiros.

### Compatibilidade

- Sem alteracoes na API Python. O pacote e o import continuam a chamar-se
  `citylearn`.

### Validacao

- Suite local completa: 457 testes passaram.
- Regras criticas de lint: passaram.
- Build de wheel e source archive e `twine check`: passaram.
- Verificacao do repositorio: 32 datasets e nenhum nome retirado.

## v1.8.0 - 2026-08-22

Responsável pela release: [@calofonseca](https://github.com/calofonseca).

### Resumo

- Minor release que introduz a suite canónica anual de benchmarks REC e os
  contratos de runtime, topologia e KPIs necessários para a avaliar de forma
  reprodutível.
- Separa a pressão do pedido do controlador da violação residual após projeção,
  evitando que a ativação do limitador seja reportada como falha de segurança
  da potência aplicada.

### Adicionado

- Quatro famílias determinísticas de datasets REC de 2023 a 15 minutos:
  `MICRO-4-Q`, `CORE-15-STRIPPED`, `CORE-30` e `PREMIUM-100`, num total de nove
  schemas clean, safety, health, dynamic e combined.
- Gerador reprodutível da suite anual com preços oficiais do mercado diário
  OMIE Portugal de 2023 e auditorias estrutural, científica, de diversidade,
  regeneração determinística e smoke de execução.
- Identidades separadas para membro, charger físico, EV e sessão; vários
  chargers por membro; contratos de deferrables; limites de potência contratada
  e margem por fase; settlement e contrafactual grid-only.
- Forecasts causais de load/PV por persistência diária e forecasts OMIE que
  respeitam a publicação do mercado diário.
- Opção `terminal_observation_padding`, que fornece uma fronteira final apenas
  de observação após os intervalos de controlo pedidos para completar a
  contabilização de serviço terminal.
- Agregação histórica de assets dinâmicos nos KPIs de chargers, baterias
  estacionárias e deferrables, incluindo ciclos de remoção e reinstalação.
- KPIs v2 `*_electrical_service_phase_requested_pressure_energy_total_kwh` e
  `*_electrical_service_phase_requested_pressure_event_count`.
- Evidência de ganho de SOC ligado e de défice na contabilização energética dos
  EVs.
- Testes causais para um pedido controlável limitado e para carga não
  controlável estruturalmente acima do limite.
- Cobertura de regressão que exige uma única contagem por identidade física e
  passo temporal, independentemente do número de features e portas de ação que
  expõem a indisponibilidade.

### Alterado

- A topologia dinâmica passa a repetir eventos anteriores à janela na fronteira
  do episódio, inicializa novos membros e assets sem simular o histórico omitido,
  ignora pedidos deferrable já expirados e preserva instâncias anteriores para
  os KPIs finais.
- A contabilização de chegada e partida dos EVs passa a respeitar a identidade
  da sessão, sessões consecutivas e partidas terminais. O current SOC é uma
  referência de fronteira e não substitui a trajetória de SOC controlada.
- Os forecasts derivados podem usar persistência causal em vez de valores
  futuros perfeitos de load/PV. Os schemas existentes mantêm o default anterior.
- `*_electrical_service_phase_violations_*` mede agora a excedência residual nos
  históricos de potência ativa total e por fase após projeção.
- A observação e penalização legadas `charging_constraint_violation_kwh`
  mantêm a semântica de pressão antes da projeção por compatibilidade.
- `robustness_asset_unavailable_time_step_count` conta agora pares únicos de
  identidade do asset e passo temporal, em vez de aplicações por feature.

### Impacto no Dataset/Schema

- A suite anual contém 35 040 passos de 900 segundos ao longo de 2023, com
  timestamps UTC e atributos de calendário/DST `Europe/Lisbon`.
- Os schemas variantes partilham os dados físicos congelados e diferem apenas
  na dimensão experimental declarada. `file_checksums.sha256` fixa todos os
  ficheiros gerados de cada família.
- Estes são benchmarks híbridos calibrados, não amostras estatisticamente
  ajustadas de comunidades portuguesas. Safety cobre potência ativa, ligação e
  margem por fase, não tensão, potência reativa, proteção ou power flow.

### Compatibilidade

- Os schemas flat e entity existentes continuam funcionais; os novos forecasts
  e a fronteira terminal são opt-in.
- Quem interpretava `*_electrical_service_phase_violations_*` como pressão de
  clipping do pedido deve migrar para os novos KPIs `*_requested_pressure_*`.
- Os datasets anuais são assets de benchmark do repositório. Utilizadores do
  pacote PyPI devem fornecer um checkout ou path montado para os utilizar.

### Validação

- `.venv/bin/pytest -q`: aprovado, `457 passed, 18 warnings`.
- Lint crítico, compatibilidade sintática com Python 3.9 e smoke de desempenho
  do CI: aprovados.
- Auditorias estrutural, de diversidade, científica e de regeneração
  determinística da suite anual REC: aprovadas.
- Smoke das nove schemas: aprovado, com `6 048` transições regulares, os `120`
  efeitos topológicos e `31 565` features causais de preço verificados.

### Notas de Migração

- Não é necessária migração para cenários existentes que não ativem as novas
  funcionalidades.
- Ambientes de algoritmos que usem os novos contratos de fronteira terminal,
  histórico dinâmico ou KPIs devem fixar `softcpsrecsimulator==1.8.0`.

## v1.6.1 - 2026-08-06

Responsavel pela release: [@calofonseca](https://github.com/calofonseca).

### Resumo

Patch que adiciona controlo agregado de escadas rolantes para simulacoes energeticas de estacoes e
o cenario final EC_Ermesinde a 15 minutos.

### Adicionado

- Adicionados `EscalatorSimulation` e `Escalator` com acoes normalizadas standby/slow/normal.
- Adicionadas observacoes flat de procura, contexto de comboios, estado, potencia e servico.
- Adicionados KPIs v2 de energia, servico de passageiros e mudancas de estado das escadas.
- Adicionado o dataset anual `EC_Ermesinde`, o respetivo gerador reprodutivel e testes de integracao.

### Alterado

- O consumo eletrico liquido do edificio passa a incluir as escadas rolantes.
- O loader expande observacoes `escalator_*` e a acao `escalator` para cada ativo configurado.

### Impacto no Dataset/Schema

- `EC_Ermesinde` usa passos de 900 segundos e seis CSVs de escadas rolantes.
- Os schemas existentes nao sao afetados. O suporte e aditivo e, por agora, usa a interface flat.

### Compatibilidade

- Patch compativel com schemas existentes e utilizadores da interface flat.
- Novos cenarios devem fornecer as colunas obrigatorias do CSV de escadas documentadas no schema reference.

### Validacao

- `.venv/bin/pytest -q tests/test_escalator_integration.py tests/test_deferrable_appliance_integration.py tests/test_scenario_smoke.py`: pass, `19 passed`.
- Smoke simulation anual EC_Ermesinde: pass, `35 039` transicoes concluidas.
- Comparacao standby/slow/normal: pass; slow e normal servem a procura com consumos distintos.

### Notas de Migracao

- Nao e necessaria migracao. Para ativar, adicionar `buildings.<id>.escalators`, os helpers de
  observacao `escalator_*` e o helper de acao `escalator`.

## v1.5.6 - 2026-07-29

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release que corrige a semantica de reset da topologia dinamica entre episodios. Ambientes
dinamicos passam a restaurar o pool de membros e a composicao de assets carregados do schema antes
de repetir os eventos, impedindo que treino multi-episodio herde mutacoes estruturais anteriores.

### Added

- Adicionada regressao multi-episodio para timelines completas de membros, chargers, PV e BESS.
- Adicionada cobertura de reset para aparelhos diferiveis removidos e membros clonados em runtime.

### Changed

- `CityLearnTopologyService` passa a manter um snapshot estrutural leve dos edificios carregados.
- O reset dinamico restaura ordem e pool de membros, chargers, aparelhos diferiveis, PV, armazenamento
  eletrico e metadata de topologia sem copiar as series temporais completas dos edificios.

### Fixed

- Corrigidos chargers adicionados que permaneciam ligados depois de `reset()` e tornavam `add_asset` um no-op.
- Corrigidos chargers e aparelhos diferiveis removidos que continuavam ausentes nos episodios seguintes.
- Corrigidos PV e armazenamento eletrico adicionados/removidos que transitavam para o estado inicial seguinte.
- Corrigidos membros clonados em runtime que permaneciam no pool entre episodios.
- Corrigida a divergencia de event logs e da timeline de `topology_version` depois do primeiro episodio.

### Dataset/Schema Impact

- Nao exige migracao de schema nem datasets.
- As definicoes de eventos e a semantica de time steps mantem-se.

### Compatibility

- Patch compativel para ambientes static e execucoes de um unico episodio.
- Ambientes dinamicos multi-episodio passam a seguir o comportamento de clean reset pretendido. Deixa
  de ser necessario reconstruir `CityLearnEnv` em cada episodio como workaround.

### Validation

- `.venv/bin/python -m pytest -q`: pass, `426 passed, 18 warnings`.
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass.
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` cenarios.
- `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci --select E9,F821`: pass.
- Build do pacote e `twine check`: pass.

### Migration Notes

- Nao e necessaria migracao. Algorithms deve usar `softcpsrecsimulator>=1.5.6` quando reutiliza um
  ambiente dinamico entre episodios.

## v1.5.5 - 2026-06-29

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release que adiciona ao simulador os baselines usados nos exemplos aplicacionais do CityLearn v3 e reforca o replay dos KPIs de settlement do mercado comunitario. A release mantem compativeis os contratos existentes de ambiente, schema e actions, tornando a API de baselines mais facil de reutilizar fora dos scripts do paper.

### Added

- Adicionados `ZeroActionBaselineAgent`, `ServiceOnlyBaselineAgent`, `NormalPolicy`, `NormalNoBatteryPolicy`, `RBCBasicPolicy`, `RBCSmartPolicy` e `RBCCommunityPolicy` a `citylearn.agents.baseline`.
- Adicionados exports publicos explicitos ao modulo de baselines.
- Adicionados os nomes retrocompativeis `GridAwareBaselineAgent` e `CommunityAwareBaselineAgent`, mapeados para os RBCs smart e community-aware.

### Changed

- `BusinessAsUsualAgent` passa a suportar targets de servico EV por deadline de partida quando estes existem, preservando o comportamento default de carregamento.
- BAU e baselines derivados passam a respeitar clipping de `electrical_service` quando o dataset ativa essas constraints.
- O replay de KPIs de settlement do mercado comunitario passa a pre-carregar series de net load e preco por edificio e a lidar defensivamente com series de preco mais curtas.
- Pastas locais de trabalho do paper/Overleaf passam a ser ignoradas pelo Git.

### Fixed

- Removidas definicoes duplicadas de `GridAwareBaselineAgent` e `CommunityAwareBaselineAgent` que podiam tornar ambigua a API publica de baselines.
- Corrigidas chamadas diretas da acao EV no baseline para passar o contexto do edificio ao charger.

### Dataset/Schema Impact

- Nao exige migracao de schema nem datasets.
- Os nomes existentes de actions e observations mantem-se.

### Compatibility

- Patch release compativel para utilizadores existentes de `CityLearnEnv`.
- As novas classes de baseline sao aditivas. Os imports legacy `GridAwareBaselineAgent` e `CommunityAwareBaselineAgent` continuam disponiveis.

### Validation

- `.venv/bin/python -m pytest tests/unit/test_business_as_usual_baseline.py tests/test_kpi_golden.py tests/test_electrical_service_and_market.py tests/test_market_phase_invariants.py`: pass, `39 passed, 10 warnings`.
- `.venv/bin/python -m pytest`: pass, `423 passed, 18 warnings`.
- `python3 -m py_compile citylearn/__init__.py citylearn/agents/baseline.py citylearn/internal/kpi.py`: pass.
- `git diff --check`: pass.

### Migration Notes

- Nao e necessaria migracao.
- Codigo downstream pode importar diretamente as novas classes RBC, em vez de depender de controllers locais aos scripts do paper.

## v1.5.4 - 2026-06-10

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focada na semantica das observacoes de carregamento EV, na correcao do reward EV e na contabilizacao de constraints de `electrical_service`. As observacoes `available_*` de EV/BESS passam a representar setpoints absolutos admissiveis para o proximo comando, nao apenas headroom incremental residual, permitindo manter uma carga ja limitada sem oscilar entre carga e zero.

### Added

- Cobertura de regressao para reward EV `soc_impossible` e penalizacoes de comando em charger sem carro ligado.
- Cobertura por cadencia para janelas entity `prev_15m`, offsets de forecast e disponibilidade de storage em 15s, 60s, 900s e 3600s.
- Cobertura de containment da observation space para headroom de `electrical_service`.

### Changed

- `available_*_power_kw` e `available_*_action_normalized` de chargers EV e storage passam a considerar a potencia atualmente aplicada ao converter headroom residual em limite absoluto do proximo setpoint.
- `charging_constraint_violation_kwh` em `electrical_service` passa a contar over-requests pre-clipping alem de violacoes fisicas residuais, alinhando pedidos clipped com a semantica legacy de penalty.
- Headroom default e bounds de observacoes de `electrical_service` passam a incluir carga base estimada do edificio e margem dos assets controlaveis.
- Features temporais entity `prev_1` e `prev_3` passam a usar a ultima transicao consolidada, em vez do timestep anterior ao anterior.

### Fixed

- Corrigido reward EV `soc_impossible` para penalizar deficits SOC inalcancaveis, nao excesso de SOC acima do target de partida.
- Corrigidas observacoes de charger EV desconectado para expor a energia comandada, tornando a penalizacao `no_car_charging` alcancavel via `env.step`.
- Corrigida viabilidade KPI de partidas EV para aplicar `min_charging_power` depois dos limites de SOC e headroom.
- Corrigidos forecasts PV derivados para ler inputs futuros do dataset em vez da propriedade do edificio limitada ao tempo atual.
- Corrigidos bounds de headroom legacy/`electrical_service` que podiam marcar observacoes negativas validas como fora da `Box`.

### Dataset/Schema Impact

- Nao exige migracao de schema nem datasets.
- Os nomes das observacoes mantem-se, mas a semantica de potencia disponivel fica clarificada como setpoint absoluto do proximo comando.
- Totais de KPI/reward de violacao de `electrical_service` podem aumentar para agentes que pedem potencia acima dos limites, porque over-requests clipped passam a contar.

### Compatibility

- Patch release compativel para APIs, actions, schemas e ficheiros de dataset.
- Controllers que usavam `available_charge_action_normalized == 0` como "tenho de parar a carga atual" devem adotar a interpretacao clarificada de setpoint.

### Validation

- `.venv/bin/pytest tests/unit/test_ev_reward_function.py tests/test_entity_observation_bundles.py tests/test_kpi_v2.py tests/test_electrical_service_and_market.py tests/test_market_phase_invariants.py tests/unit/test_charging_constraints.py tests/test_charging_constraints_e2e.py -q`: pass, `91 passed, 8 warnings`.
- `.venv/bin/pytest -q`: pass, `423 passed, 18 warnings`.
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass.
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16 executed, 16 passed`.
- `git diff --check`: pass.

### Migration Notes

- Nao e necessaria migracao de codigo para agentes CityLearn standard.
- Se analises downstream compararem totais de violacao de `electrical_service` entre versoes, esperar uma descontinuidade quando o agente faz over-request e o simulador clipped o comando.

## v1.5.3 - 2026-06-05

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focada no custo de inicializacao dinamica full-year a 15 segundos que ainda sobrava depois da `v1.5.2`. O loader passa a evitar materializacao por listas Python para dados parquet full-year, reutiliza series partilhadas full-horizon entre janelas dinamicas de membros e ignora scans desnecessarios de schedules de chargers quando nao existe EV pool.

### Added

- Notas de benchmark de inicializacao representativo para `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`.

### Changed

- O loader passa a entregar colunas de dataframes como arrays NumPy aos construtores, em vez de converter dados parquet full-year via `DataFrame.to_dict('list')`.
- Series partilhadas full-horizon de weather, pricing e carbon podem agora ser reutilizadas entre janelas dinamicas de membros.
- O alinhamento de dataframes dinamicos evita copias extra quando a fonte ja cobre todo o horizonte configurado com `RangeIndex` default.
- O reset de topologia dinamica passa a ignorar scans completos de schedules de chargers quando o ambiente nao tem EV pool.

### Fixed

- Reduzido o tempo de inicializacao dinamica full-year a 15 segundos causado por boxing pandas para listas e materializacao repetida de series partilhadas.

### Dataset/Schema Impact

- Nao exige migracao de schema nem datasets.
- Chamadas explicitas a `env.reset()` em full-year continuam a alocar historicos densos full-horizon; usar `simulation_start_time_step` e `simulation_end_time_step` para janelas de treino com limite de memoria.

### Compatibility

- Patch release compativel para APIs, actions, observations, KPIs e ficheiros de dataset.
- Os outputs numericos devem manter-se iguais; a patch muda a estrategia de loading/materializacao, nao as equacoes fisicas.

### Validation

- `.venv/bin/pytest tests/test_15_second_power_fixture.py tests/test_dynamic_topology_entity_mode.py tests/test_scenario_smoke.py -q`: pass, `19 passed`.
- `.venv/bin/pytest -q`: pass, `398 passed, 18 warnings`.
- `git diff --check`: pass.
- Check manual de performance em `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`: inicializacao full-year `~24 s` e `~6.4 GB` RSS antes do reset explicito; check local anterior estava em `~90 s` e `~7.1 GB` RSS. O reset explicito ainda subiu RSS para `~10.7 GB` porque os historicos densos full-horizon continuam alocados.

### Migration Notes

- Nao e necessaria migracao de codigo. Para reduzir memoria full-year a 15 segundos para alem da inicializacao, o trabalho restante e uma mudanca maior de `history_mode="training"` ou reutilizacao de buffers no reset.

## v1.5.2 - 2026-06-05

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focada no stall de runtime do dataset dinamico full-year a 15 segundos. Runs full-year em entity/dynamic deixam de fazer trabalho de arrays full-horizon dentro de acessores comuns de energia por step, trazendo o throughput dos primeiros steps para perto das janelas curtas. A inicializacao e memoria de runs full-year a 15 segundos continuam altas porque o simulador ainda materializa historicos densos full-horizon.

### Added

- Notas de benchmark local representativo para `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`, comparando janela de 10k steps com run dinamica full-year.

### Changed

- `ElectricDevice.available_nominal_power` passa a ler apenas o timestep atual em vez de materializar o vetor completo de electricity consumption.
- `ElectricDevice.electricity_consumption` devolve o array guardado diretamente quando `time_step_ratio == 1.0`, evitando uma multiplicacao full-array desnecessaria.
- Properties auxiliares de energia de storage em buildings passam a cortar o historico simulado antes de aplicar `clip`, evitando trabalho em arrays full-year durante timesteps iniciais.

### Fixed

- Corrigido o principal stall por step observado em datasets entity/dynamic full-year a 15 segundos, onde operacoes vetoriais full-horizon repetidas tornavam os primeiros timesteps muito mais lentos que runs equivalentes em janela curta.

### Dataset/Schema Impact

- Nao exige migracao de schema nem datasets.
- Datasets full-year a 15 segundos continuam a alocar estado e historicos de observacao densos para o horizonte completo. Usar `simulation_start_time_step` e `simulation_end_time_step` para treino em janelas menores quando a memoria for o limite.

### Compatibility

- Patch release compativel para APIs, actions, observations, KPIs e ficheiros de dataset.
- Os outputs numericos devem manter-se iguais; a patch muda quando os arrays sao cortados/materializados, nao as equacoes fisicas.

### Validation

- `.venv/bin/pytest tests/test_15_second_power_fixture.py tests/test_kpis.py::test_histories_and_kpi_consistency_with_subhour_steps tests/test_scenario_smoke.py -q`: pass, `9 passed`.
- `.venv/bin/pytest -q`: pass, `398 passed, 18 warnings`.
- `git diff --check`: pass.
- Check manual de performance em `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`: janela de 10k steps nos primeiros 100 steps `~0.010 s/step`, full-year nos primeiros 100 steps apos patch `~0.010 s/step`; antes da patch o full-year estava em `~0.161 s/step` no mesmo check local.

### Migration Notes

- Nao e necessaria migracao de codigo. Para treino a 15 segundos com limite de memoria, preferir janelas explicitas ate existir um futuro `history_mode="training"` ou modo de KPIs online que remova os historicos densos full-horizon.

## v1.5.1 - 2026-06-04

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release da auditoria final aos KPIs de custo e solar. O settlement do mercado comunitario deixa de dar receita a energia exportada para fora da comunidade, o self-consumption solar distrital passa a contar PV consumido dentro da comunidade como autoconsumo, e os totais EV/BESS/PV deixam de virar `NaN` por causa de uma amostra nao finita isolada.

### Added

- Testes de regressao para preco zero de export para a rede externa no settlement do mercado comunitario.
- Testes de regressao para self-consumption PV distrital quando um membro exporta PV e outro membro consome no mesmo timestep.
- Testes de regressao que provam que totais EV/V2G, BESS e PV ignoram amostras nao finitas.

### Changed

- `district_solar_self_consumption_total_export_kwh` passa a ser export PV-backed net do distrito para fora da comunidade, em vez da soma de exports PV por membro.
- `district_solar_self_consumption_ratio_self_consumption_ratio` passa a contar transferencias PV intra-comunidade no mesmo timestep como self-consumption distrital/comunitario.

### Fixed

- KPIs de custo e settlement runtime do mercado comunitario deixam de creditar energia exportada para fora da comunidade.
- Totais de custo por building e district passam a cobrar apenas import net positivo da rede quando o mercado comunitario esta desativado.
- Totais de EV charge/V2G, bateria estacionaria charge/discharge e PV generation/export usam soma de valores finitos para evitar propagacao de `NaN` a partir de uma amostra em falta.
- Replay KPI para condicoes control/baseline com mercado ativo aplica a mesma regra de preco zero para export externo que o runtime settlement.

### Dataset/Schema Impact

- Nao exige migracao de schema nem datasets.
- Datasets existentes com mercado comunitario ativo podem reportar valores diferentes em KPIs de custo e self-consumption solar distrital, porque a receita de export externo foi removida e o export PV distrital passa a ser community-net.

### Compatibility

- Patch release compativel para APIs, actions, observations e ficheiros de dataset.
- Consumidores de KPI que interpretavam self-consumption solar distrital como soma do self-consumption individual dos buildings devem migrar para a nova interpretacao community-net.

### Validation

- `.venv/bin/pytest -q`: pass, `398 passed, 18 warnings`.
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict --output-dir /tmp/citylearn_audit_final`: pass.
- `.venv/bin/python scripts/audit/audit_physics.py --output /tmp/citylearn_audit_final/physics_audit.json`: pass, `16 passed`.
- `git diff --check`: pass.
- Auditoria manual de KPIs de cost settlement, market replay, agregacao PV distrital, soma finita EV/BESS/PV e scorecard rows: pass.

### Migration Notes

- Nao e necessaria migracao de codigo. Regerar baselines de dashboards ou golden KPIs que incluam custos de mercado comunitario ou self-consumption solar distrital.

## v1.5.0 - 2026-06-01

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release que alinha os exports do simulador com o scorecard de jobs do EnergAIze e reduz overhead em treinos multi-episodio. Runs planeadas passam a exportar apenas o ultimo episodio por default, e os KPIs v2 passam a incluir as linhas de scorecard necessarias para comparacao direta contra BAU.

### Added

- `CityLearnKPIService.SCORECARD_DEFAULT_KPIS`, contrato explicito dos KPIs consumidos pelo scorecard de jobs.
- Linhas business-as-usual e delta para o ratio de solar self-consumption em district e building.
- Linhas business-as-usual e delta para totais e medias diarias de solar generation/export.
- Setting de ambiente `export_only_final_episode`, com default `true`, e planeamento do export final para `Agent.learn(episodes=...)` e treino via CLI.
- Teste de regressao que garante que `evaluate_v2()` default exporta o contrato KPI do scorecard.
- Teste de regressao que garante que um treino planeado de dois episodios exporta apenas timeseries, KPIs e auditoria BAU do episodio final.

### Changed

- Exports automaticos de render, KPIs finais e timeseries BAU sao ignorados nos episodios nao finais em runs multi-episodio planeadas.
- Episodios intermedios ignorados deixam de calcular ou escrever KPIs finais/BAU, reduzindo runtime e uso de disco em jobs de treino.
- `export_final_kpis()` manual, chamadas diretas a `evaluate_v2()` e ciclos reset/step nao planeados mantem o comportamento anterior.

### Fixed

- Solar self-consumption passa a poder ser comparado contra BAU quando o simulador exporta linhas BAU, em vez de expor apenas o valor da policy.

### Dataset/Schema Impact

- Novo setting top-level opcional: `export_only_final_episode`.
- Datasets existentes nao precisam de alteracoes; o default e `true`.
- Output KPI v2 e aditivo: nomes KPI existentes mantem-se, e sao adicionadas novas linhas BAU/delta para solar self-consumption.

### Compatibility

- Treino multi-episodio planeado com exports automaticos passa a escrever apenas o episodio final por default. Definir `export_only_final_episode=false` para voltar a exports automaticos por episodio.
- Jobs de episodio unico, exports manuais e avaliacao manual mantem compatibilidade.

### Validation

- `.venv/bin/pytest -q`: pass, `395 passed, 18 warnings`
- `git diff --check`: pass
- `.venv/bin/python -m compileall -q citylearn/__main__.py citylearn/agents/base.py citylearn/citylearn.py citylearn/exporter.py citylearn/internal/runtime.py citylearn/internal/kpi.py citylearn/__init__.py`: pass

### Migration Notes

- Em jobs de treino, consumir `exported_kpis.csv` e `exported_data_*_epN.*` do ultimo episodio planeado.
- Se tooling downstream esperar export de todos os episodios, definir `export_only_final_episode=false` no schema ou nos kwargs do ambiente.

## v1.4.0 - 2026-05-28

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Adiciona robustez v1 opcional e orientada por dataset ao `CityLearnEnv`. Datasets existentes mantem o comportamento anterior salvo se `robustness.enabled=true`.

### Added

- Servico interno `CityLearnRobustnessService` com leitura esparsa de eventos CSV/Parquet, ordem deterministica e ruido reprodutivel.
- Modulos de robustez para observations, forecasts, actions e disponibilidade logica de assets.
- Bundle `entity_robustness` com diagnostico district e `observations["meta"]["robustness"]`.
- KPIs de robustez district/building.
- Dataset incluido sem EVs em `data/datasets/citylearn_challenge_2022_phase_all_robustness/schema.json`, copiado do 2022 phase-all com ficheiros locais e eventos esparsos de robustez.
- Documentacao bilingue de referencia para robustez.
- Testes unitarios para comportamento desligado, CSV/Parquet, toggles de modulos, erros de validacao, observations flat/entity, forecasts, modos de action, outages de assets, KPIs, agregacao multi-comunidade e carregamento do dataset incluido.

### Changed

- Snapshots do contrato entity passam a incluir `entity_robustness` como bundle default inativo.
- Metadata de `CityLearnEnv` passa a incluir a secao `robustness`.

### Dataset/Schema Impact

- Nova secao top-level opcional `robustness`.
- Novo bundle opcional `entity_robustness`.
- Sem alteracao de comportamento para datasets existentes quando robustez esta ausente ou desligada.

### Compatibility

- Aditivo para utilizadores existentes de `CityLearnEnv`.
- Corrupcao de observation/forecast afeta apenas o que o agente ve; estado fisico real, reward, settlement DR e KPIs normais continuam baseados no estado nao corrompido.
- Eventos de action e asset-control alteram intencionalmente a acao fisica aplicada.

### Validation

- `.venv/bin/pytest -q`: pass, `393 passed, 17 warnings`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` cenarios
- `git diff --check`: pass

### Migration Notes

- Datasets existentes nao precisam de alteracoes.
- Adicionar `robustness.enabled=true` e um `events_file` apenas para experiencias de robustez.

## v1.3.0 - 2026-05-28

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release que adiciona orquestracao multi-comunidade v1 atraves do novo `MultiCommunityEnv` publico. O wrapper corre varias comunidades `CityLearnEnv` independentes em lockstep sincronizado, preserva fisica, rewards, demand response e KPIs de cada comunidade, e adiciona linhas KPI de portfolio para reporting entre comunidades.

### Added

- Wrapper publico `citylearn.multi_community.MultiCommunityEnv`.
- Payloads `reset()` e `step()` por comunidade, indexados por `community_id`.
- `action_space`, `observation_space` e `entity_specs` por comunidade.
- Validacao de sincronizacao para `seconds_per_time_step`, episode length efetivo, `interface` e `central_agent`.
- Info de reward portfolio com soma finita dos rewards filhos, reward total ponderado e media ponderada.
- Output `evaluate_v2()` multi-comunidade com `community_id` nas linhas locais e linhas `level="portfolio"` agregadas a partir dos KPIs district.
- Layout de export multi-comunidade com subpastas por comunidade e CSV global `exported_kpis_multi_community.csv`.
- Documentacao bilingue de referencia e quickstarts multi-comunidade.
- Testes unitarios para validacao do constructor, routing de reset/step, agregacao de rewards, entity mode, demand response independente, KPIs portfolio, layout de export e regressao single-community.

### Changed

- README e documentacao de features/running passam a incluir uso multi-comunidade e links.
- `citylearn.__init__` expoe `MultiCommunityEnv` de forma lazy sem importar o simulador durante package import.

### Fixed

- Sem fixes nao relacionados.

### Dataset/Schema Impact

- Sem novos ficheiros de dataset e sem alteracoes de schema.
- `MultiCommunityEnv` usa os schemas filhos passados em `communities[*].schema`.
- Demand response continua configurado por dataset filho; a v1 nao introduz coordenacao DSO/TSO global nem ficheiro de pedidos DR de portfolio.

### Compatibility

- Minor release aditiva para utilizadores existentes de `CityLearnEnv`.
- Imports single-community, datasets, KPIs e contratos flat/entity existentes ficam inalterados salvo quando o utilizador instancia explicitamente `MultiCommunityEnv`.
- A v1 multi-comunidade rejeita mistura de interfaces, mistura de modos `central_agent`, resolucoes temporais diferentes e episode lengths efetivos diferentes.

### Validation

- `.venv/bin/pytest -q tests/test_multi_community_env.py`: pass, `15 passed`
- `.venv/bin/pytest -q tests/test_multi_community_env.py tests/test_demand_response.py tests/test_kpis.py tests/unit/test_export_logic.py`: pass, `33 passed`
- `.venv/bin/pytest -q`: pass, `371 passed, 17 warnings`
- `git diff --check`: pass

### Migration Notes

- Utilizadores existentes nao precisam de alterar nada.
- Para correr um portfolio, instanciar `MultiCommunityEnv` com um schema filho por comunidade e passar actions indexadas por `community_id`.
- Linhas KPI de portfolio so aparecem em `MultiCommunityEnv.evaluate_v2()` e nao aparecem no output normal de `CityLearnEnv.evaluate_v2()`.

## v1.2.0 - 2026-05-28

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release que adiciona demand response v1 orientado por dataset para simulacoes em entity mode. Pedidos DSO/TSO sao lidos de ficheiros do dataset, expostos nas observacoes district entity, liquidados depois de cada step fisico e reportados em KPIs district/building.

### Added

- Secao `demand_response` no schema com suporte a `requests_file` CSV/Parquet.
- Bundle `entity_demand_response` com estado do pedido DR no district, baseline, precos e delivery/shortfall do step anterior.
- Servico interno `CityLearnDemandResponseService` com leitura sparse dos pedidos, ativacao por cursor temporal, baseline rolling pre-event e settlement apenas nos steps ativos.
- KPIs demand response district e building para eventos, active steps, energia pedida/entregue/shortfall, compliance, revenue, penalty, net revenue e steps com baseline invalido.
- Dataset incluido sem EVs em `data/datasets/citylearn_challenge_2022_phase_all_demand_response/schema.json`, copiado do 2022 phase-all com ficheiros locais e todos os observation bundles entity ativos.
- Testes unitarios para CSV/Parquet, observacoes entity, erro em flat interface, rejeicao de overlaps, semantica up/down, KPIs/economia, baseline invalido e carregamento do dataset incluido.

### Changed

- A sidecar nativa business-as-usual para KPIs passa a usar entity interface quando demand response esta ativo, mantendo o contrato DR entity-only.

### Fixed

- Sem fixes nao relacionados.

### Dataset/Schema Impact

- Nova chave opcional top-level `demand_response`:
  `enabled`, `requests_file`, `baseline_method`, `baseline_window_seconds` e `allow_overlapping_requests`.
- Demand response v1 requer `interface="entity"` quando ativo.
- Ficheiros de pedidos devem definir `request_id`, `issuer`, `direction`, `start_time_step`, `end_time_step`, `target_power_kw`, `activation_price_eur_per_kwh`, `shortfall_penalty_eur_per_kwh` e opcionalmente `tolerance_power_kw`.
- `entity_demand_response` adiciona apenas features na tabela district; o `request_id` ativo fica em `meta`, nao numa feature numerica.

### Compatibility

- Minor release aditiva para datasets flat/entity existentes que nao ativem demand response.
- Schemas com `demand_response.enabled=true` e `interface="flat"` falham cedo com erro claro.
- Pedidos DR sobrepostos sao rejeitados na v1 ate existir suporte explicito.

### Validation

- `.venv/bin/pytest -q tests/test_demand_response.py`: pass, `9 passed`
- `.venv/bin/pytest -q`: pass, `356 passed, 17 warnings`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` cenarios
- Smoke run do dataset demand response incluido por 30 entity steps mais `evaluate_v2(include_business_as_usual=False)`: pass, `180` linhas KPI DR
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.2.0-dist`: pass, gerou sdist e wheel
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.2.0-dist/*`: pass

### Migration Notes

- Datasets existentes nao precisam de alteracoes se nao usarem demand response.
- Para treinar com DR, usar `interface="entity"`, `demand_response.enabled=true`, fornecer request file e ativar `observation_bundles.entity_demand_response`.
- Agentes entity fixed-width devem refrescar `env.entity_specs` quando ativam `entity_demand_response`.

## v1.1.0 - 2026-05-26

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Minor release focada em tornar simulacoes entity-mode de 15 segundos praticas com todos os bundles de observacao ativos. O trabalho principal remove a fuga de memoria de `entity_action_feedback`, substitui o contrato demasiado grande de forecasts derivados por point forecasts compactos, reduz overhead recorrente de observacoes entity e passa exports longos para Parquet em chunks.

### Added

- Suporte para `render_file_format="parquet"` e `render_chunk_size` em exports de render/KPI/BAU. O render em Parquet escreve ficheiros chunked `*_partNNNNN.parquet`.
- Campos de timing entity mais finos quando `debug_timing=True`, incluindo `entity_observation_building_time`, `entity_observation_charger_time`, `entity_observation_storage_time`, `entity_observation_district_time`, `entity_observation_copy_time` e secoes relacionadas por tabela.
- Limpeza de chunks Parquet antigos no diretorio de output da sessao.

### Changed

- `entity_forecasts_derived` mantem o mesmo nome de bundle mas passa a expor apenas point forecasts compactos:
  - building: `forecast_{load,pv,net}_next_{15m,1h,3h,6h,24h}_kw`
  - district: `forecast_price_next_*` e `forecast_community_{load,pv,net}_next_*_kw`
- Removida a grelha antiga de features mean/sum/peak/headroom/surplus/bucket dos derived forecasts e a cache de forecasts em reset/init.
- A montagem de observacoes entity passa a usar colunas de features precomputadas, escrita direta/sparse de linhas, linhas estaticas por asset e offsets de forecast precomputados.
- O historico de topologia dinamica passa a guardar snapshots apenas quando membros/assets ativos ou `topology_version` mudam.
- Os historicos de capacidade/eficiencia da bateria passam a usar arrays numericos compactos em vez de listas Python de floats.
- Flags booleanas de action feedback e clipping reasons passam a ser guardadas como arrays booleanos em vez de `float32`.
- Series agregadas para KPI/export no `CityLearnEnv` passam a usar somas numpy em streaming em vez de DataFrames pandas temporarios.

### Fixed

- Corrigido o crescimento dominante de RSS em `entity_action_feedback`, causado por uma cache indexada por objetos temporarios de series de storage.
- Corrigido overhead excessivo de init/reset causado pelos derived forecasts em datasets de 15 segundos.
- Corrigida retencao evitavel de memoria no historico de topologia dinamica quando nao ha eventos de topologia.
- Corrigidos picos evitaveis de memoria em KPI/export causados por DataFrames temporarios sobre todas as series dos buildings.

### Benchmark Notes

Medicoes locais representativas em `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet`, interface entity, topologia dinamica, todos os bundles de observacao, `render_mode="none"`, `export_kpis_on_episode_end=False`:

| Area | Antes | Depois | Impacto |
|---|---:|---:|---:|
| Colunas entity com todos os bundles | ~732 | ~322 | ~56% menos colunas |
| Caminho init/reset dos derived forecasts | ~15.0s init / ~12.8s reset | ~2.0s init / ~0.15s reset | ~87% menos init, ~99% menos reset |
| Crescimento RSS de `entity_action_feedback` em 700 steps | ~+2071 MiB | ~+5 MiB | fuga removida |
| Tamanho da cache de action feedback em 700 steps | 11,224 entradas / 3.9M valores cached | 24-25 entradas | cache estavel por asset |
| RSS pos-reset numa janela 15s de 40,320 steps | ~658.7 MiB | ~630.4 MiB | ~28 MiB menos no reset apos flags booleanas |
| `next_observations` em smoke debug de 1k steps | ~6.49 ms/step | ~5.80 ms/step | ~11% mais rapido |
| Smoke de 5k steps sem debug | n/a | ~12.4 ms/step, ~718 MiB RSS aos 5k | ponto operacional atual |

Em datasets full-year de 15 segundos, os historicos retidos pelo simulador continuam a escalar linearmente com numero de steps, assets e necessidades de KPI/export. Esta release remove o crescimento patologico de cache, mas nao transforma uma run full-year all-bundles em memoria constante.

### Dataset/Schema Impact

- Nenhum ficheiro de dataset incluido ou chave de schema e renomeado.
- O contrato de features das observacoes entity muda quando `entity_forecasts_derived` esta ativo, porque a grelha antiga de derived forecasts e removida de forma intencional.
- Export Parquet requer um engine Parquet do pandas como `pyarrow`; CSV continua a ser o formato default.

### Compatibility

- Minor release com mudanca intencional no contrato de observacoes entity para `entity_forecasts_derived`.
- Equacoes fisicas, aplicacao de acoes, semantica de eventos de topologia dinamica, formulas KPI e observacoes flat devem manter-se inalteradas.
- Agentes RL fixed-width ou normalizers guardados contra observacoes entity all-bundles v1.0.x devem refrescar `entity_specs`, colunas de features e estatisticas de input antes de usar v1.1.0.

### Validation

- `.venv/bin/pytest tests/test_entity_observation_bundles.py tests/test_dynamic_topology_entity_mode.py tests/test_dynamic_topology_full_timeline.py tests/test_dynamic_topology_assets_only_dataset.py tests/unit/test_physics_units_refactor.py tests/unit/test_physics_invariants.py tests/unit/test_subhour_scaling.py tests/unit/test_rendering_behaviour.py::test_parquet_render_format_writes_chunked_exports_and_kpis -q`: pass, `71 passed`
- `.venv/bin/pytest tests/test_deferrable_appliance_integration.py::test_entity_action_feedback_for_deferrable_start tests/test_deferrable_appliance_integration.py::test_entity_action_feedback_for_blocked_deferrable_start tests/test_kpis.py tests/test_kpi_v2.py tests/test_kpi_golden.py tests/test_series_integrity.py tests/unit/test_export_logic.py tests/unit/test_ui_export_contract.py -q`: pass, `57 passed, 17 warnings`
- `.venv/bin/pytest tests/unit/test_step_many.py -q`: pass, `5 passed`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` cenarios
- `.venv/bin/pytest -q`: pass, `347 passed, 17 warnings`
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.1.0-dist`: pass, gerou sdist e wheel
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.1.0-dist/*`: pass

### Migration Notes

- Refrescar `env.entity_specs` e retreinar ou remapear inputs fixed-width que usavam `entity_forecasts_derived`.
- Para usar exports Parquet em chunks, configurar `render_file_format="parquet"` e opcionalmente `render_chunk_size`.
- Em runs longas de 15 segundos, manter render/KPI exports desligados salvo quando necessarios, ou exportar em Parquet chunked.

## v1.0.2 - 2026-05-23

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release para corrigir o gate de performance smoke do GitHub Actions para o contrato v1 de observacoes entity. O codigo do simulador, comportamento fisico, schemas e outputs de observacao ficam iguais a v1.0.1.

### Added

- Nenhum novo contrato publico de observacao, acao, KPI ou dataset.

### Changed

- O job de performance smoke em CI passa a usar um limite explicito de latencia entity para a configuracao entity com todos os bundles.
- O ratio entity/flat e a margem de regressao contra baseline em CI passam a estar alinhados com o contrato entity v1 atual e com a variancia dos runners GitHub-hosted.

### Fixed

- Corrigida a falha falsa do CI `run_tests`, onde a latencia entity all-bundles em `ubuntu-24.04` excedia um gate antigo pre-v1 apesar da performance estar dentro do envelope otimizado v1.

### Dataset/Schema Impact

- Sem alteracoes de schema ou conteudo de datasets face a v1.0.1.

### Compatibility

- Patch release compativel.
- Logica runtime do simulador, constraints fisicas, formulas KPI, nomes de tabelas entity e contrato de features ficam iguais a v1.0.1.

### Validation

- `.venv/bin/ruff check citylearn tests scripts/manual scripts/ci --select E9,F821`: pass
- `.venv/bin/pytest tests/unit/test_perf_smoke_thresholds.py -q`: pass
- `.venv/bin/pytest -q --ignore=scripts/manual`: pass, `346 passed, 17 warnings`
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --none-max-ms 30 --end-max-ms 45 --entity-max-ms 50 --ratio-max 2.0 --entity-overhead-ratio-max 3.75 --baseline-file scripts/ci/perf_baseline.json --baseline-regression-ratio 4.5 --baseline-slack-ms 15.0`: pass
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.0.2-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.0.2-dist/*`: pass

### Migration Notes

- Sem migracao necessaria face a v1.0.1.

## v1.0.1 - 2026-05-23

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release para o contrato v1 de observacoes entity para RL. Esta release mantem intacto o contrato de schema e fisica da v1.0.0, reduzindo o overhead das observacoes entity quando todos os bundles orientados a RL estao ativos.

### Added

- Nenhum novo contrato publico de observacao, acao, KPI ou dataset.

### Changed

- A geracao de forecasts derivados em entity passa a reutilizar estatisticas precomputadas de horizontes/janelas em vez de recalcular slices futuros equivalentes a cada step.
- A montagem das observacoes entity evita lookups repetidos de nomes e pede apenas as observacoes base usadas pelas tabelas entity.
- O bookkeeping de action feedback reutiliza arrays por episodio em vez de redescobrir ou realocar esses arrays repetidamente.
- O preenchimento de linhas entity e as metricas de action-feedback em janelas curtas usam caminhos em cache/vetorizados sem alterar o contrato de saida.

### Fixed

- Falha de CI lint de typing/import no caminho de preparacao da v1.0.0.
- O performance smoke passa a medir latencia recorrente de rollout separadamente do trabalho terminal de export/KPI.

### Dataset/Schema Impact

- Sem alteracoes de schema ou conteudo de datasets face a v1.0.0.
- Os schemas de 15 segundos e `citylearn_challenge_2022_phase_all_plus_evs` continuam com todos os bundles de observacoes entity ativos por default.

### Compatibility

- Patch release compativel.
- Observacoes flat, nomes de tabelas entity, nomes legacy, dynamic topology, constraints fisicas e formulas de KPI ficam inalterados.
- Modelos entity de largura fixa nao precisam de mudar feature lists face a v1.0.0.

### Validation

- `.venv/bin/ruff check citylearn tests scripts/manual scripts/ci --select E9,F821`: pass
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py --strict`: pass, `16/16` cenarios
- `.venv/bin/pytest -q`: pass, `346 passed, 17 warnings`
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --none-max-ms 30 --end-max-ms 45 --ratio-max 2.0 --entity-overhead-ratio-max 1.08 --baseline-file scripts/ci/perf_baseline.json --baseline-regression-ratio 3.0 --baseline-slack-ms 10.0`: pass
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.0.1-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.0.1-dist/*`: pass

### Performance Notes

Benchmark local representativo, 600 steps, `seconds_per_time_step=60`, render desligado:

| Caso | avg ms/step | p95 ms | vs flat |
|---|---:|---:|---:|
| flat | 4.7270 | 4.9251 | 1.000x |
| entity_base | 5.2227 | 5.4199 | 1.105x |
| entity_all | 14.7545 | 17.5723 | 3.121x |

### Migration Notes

- Sem migracao necessaria face a v1.0.0.
- Utilizadores devem continuar a refrescar `env.entity_specs` quando mudam datasets ou topology modes.

## v1.0.0 - Contrato Entity para RL

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Primeira release estavel do contrato do simulador para workflows RL em modo entity. Esta release promove o contrato aditivo de observacoes entity para forecasts, deadlines fisicos, feedback de acao, diagnostico de clipping e capacidade de acao factivel por asset.

### Added

- Bundle entity-only `entity_forecasts_derived` com horizontes fisicos `15m`, `1h`, `3h`, `6h`, `24h` e grid de buckets de 15 minutos ate 6h.
- Bundle `entity_action_feedback` com acoes EV/BESS/deferrable pedidas, limitadas e aplicadas, mais flags de clipping.
- Observacoes de pressao de deadline EV, incluindo `departure_feasibility_ratio`, `departure_energy_margin_kwh`, `max_deliverable_energy_until_departure_kwh` e `min_required_action_normalized`.
- Observacoes de capacidade de acao factivel para chargers e BESS, incluindo `can_charge`, `can_discharge`, potencia disponivel e magnitude normalizada disponivel.
- Observacoes BESS de energia por step separadas entre `max_*_energy_kwh_step` nominal e `available_*_energy_kwh_step` limitado por constraints.
- Capacidade flexivel agregada por building e community para carga/descarga e folga energetica.
- Observacoes de deadline para deferrables, incluindo `remaining_duration_hours`, `cycle_remaining_fraction_ratio`, `start_energy_kwh_step`, `start_power_kw` e `must_start_now`.
- Observacoes temporais robustas em entity, mantendo `time_step` cru apenas em `meta`.

### Changed

- Datasets entity a 15 segundos e `citylearn_challenge_2022_phase_all_plus_evs` passam a declarar todos os bundles de observacoes entity ativos nos schemas.
- `meta` entity expoe `seconds_per_time_step` e a configuracao de forecast usada pelos forecasts derivados.
- Documentacao atualizada com bundles entity, features de pressao de deadline para RL e defaults dos datasets.

### Fixed

- Sem quebra intencional de fisica ou KPIs. Countdowns EV continuam relativos em steps, enquanto `hours_until_departure` e tempo fisico em horas calculado com `seconds_per_time_step`.

### Dataset/Schema Impact

- Schemas atualizados:
  - `citylearn_challenge_2022_phase_all_plus_evs`
  - `citylearn_three_phase_dynamic_asset_changes_demo_15s_parquet`
  - `citylearn_three_phase_dynamic_assets_only_demo_15s`
  - `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet`
  - `citylearn_three_phase_electrical_service_demo_15s`
  - `citylearn_three_phase_electrical_service_demo_15s_parquet`
- Novos bundles continuam desligados por default em schemas que nao fazem opt-in.

### Compatibility

- Observacoes flat, nomes legacy e comportamento default de bundles existentes ficam preservados.
- Algoritmos que usam os schemas entity afetados vao ver tabelas entity mais largas porque todos os bundles ficam ativos por default nesses datasets.
- Adapters reais devem preencher o mesmo contrato de forecasts derivados com forecasts reais, nao com valores `actual_future` do simulador.

### Validation

- `.venv/bin/python -m pytest -q`: pass, `346 passed, 17 warnings`
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass, `16/16` cenarios
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-1.0.0-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-1.0.0-dist/*`: pass

### Migration Notes

- Policies RL devem preferir features fisicas e de pressao, como `hours_until_departure`, `departure_feasibility_ratio`, `departure_energy_margin_kwh`, `available_*_power_kw` e feedback de acao, em vez de indices crus em steps.
- Modelos entity de largura fixa treinados com schemas anteriores devem refrescar as feature lists a partir de `env.entity_specs` antes de carregar/re-treinar.

## v0.6.9 - Action Repeat com Macro-Step

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release que adiciona a API nativa `step_many()` para treino RL com action-repeat/macro-step, mantendo fisica interna e exports em substeps.

### Added

- `CityLearnEnv.step_many(action, repeat_steps=..., stop_on_done=True, return_substeps=False)` para repetir uma acao fixa durante varias transicoes internas do simulador.
- Metadata de transicao macro no `info`: `executed_steps`, `seconds_per_time_step` e `macro_seconds`.
- Payloads opcionais de debug quando `return_substeps=True`: `substep_rewards`, `substep_infos` e `substep_actions_applied`.
- Testes de paridade para modo flat, modo entity, fim antecipado de episodio, soma de rewards e debug opcional de substeps.

### Changed

- O runtime de `step()` passa a usar um core interno partilhado para `step_many()` e `step()` executarem o mesmo caminho de fisica/acao/reward.
- `step_many()` evita montar observacoes finais e infos em substeps intermedios por defeito, mas continua a correr constraints, EVs, baterias, deferrables, fases/headroom, rewards, KPIs e estado de render/export em cada step interno.
- Layouts estaticos de acao fazem parse da acao repetida uma vez por macro-step; em dynamic topology o parse e repetido por substep para suportar mudancas de layout.
- A documentacao de simulacoes descreve action repeat e o padrao `gamma ** executed_steps` para algoritmos RL.

### Fixed

- Sem mudancas intencionais de fisica ou KPIs. Os testes de paridade de `step_many()` comparam observacoes finais, rewards acumuladas, estado terminal, timestep e KPIs contra chamadas repetidas a `step()`.

### Dataset/Schema Impact

- Sem alteracoes de schema ou dataset.

### Compatibility

- Patch compativel. Callers existentes de `step()` nao mudam.
- `stop_on_done=False` e aceite por simetria de API, mas o CityLearn continua a parar quando o episodio chega a terminal/truncated porque o ambiente nao pode avancar depois de done sem `reset()`.

### Validation

- `.venv/bin/python -m pytest tests/unit/test_step_many.py -q`: pass (`5 passed`)
- `.venv/bin/python -m pytest tests/unit/test_rendering_behaviour.py tests/test_entity_interface_contract.py tests/unit/test_step_many.py -q`: pass (`33 passed`)
- `.venv/bin/python -m pytest -q`: pass (`338 passed`, `17 warnings`)
- `.venv/bin/python -m compileall -q citylearn tests/unit/test_step_many.py`: pass
- `.venv/bin/python -m ruff check citylearn tests/unit/test_step_many.py --select E9,F821`: pass
- `git diff --check`: pass
- Smoke de step-many: pass (`step_many` mediu `3.3377 ms/internal-step` vs `step()` repetido `3.8041 ms/internal-step`, `1.14x` mais rapido em 200 substeps internos)

### Migration Notes

- Replay buffers RL podem guardar `(obs_t, action_t, reward_sum, obs_t_plus_n, done, executed_steps)` e usar `gamma ** executed_steps`.
- Manter `return_substeps=False` em treinos longos; ligar apenas para debug de rewards ou infos por substep.

## v0.6.8 - Profiling de Runtime e Otimizacoes do Step

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focada na latencia recorrente do `step`, observabilidade de BAU/export e controlo mais seguro de exports apenas no episodio final.

### Added

- `scripts/audit/profile_step_breakdown.py` para medir custos internos do `step()`, incluindo aplicacao de acoes, payload de reward, calculo de reward e proximas observacoes.
- `scripts/audit/profile_lifecycle.py` para medir reset, rollout, KPIs, render e export BAU separadamente.
- Reward functions podem declarar o payload minimo de observacoes com `required_observation_names`, `required_observations` ou `get_required_observation_names()`.

### Changed

- Rewards built-in passam a usar payloads de observacao reduzidos em vez de observacoes completas com `include_all` durante chamadas normais a `step()`.
- `Building.observations()` e a montagem interna de observacoes conseguem calcular apenas campos pedidos, mantendo fallback para observacoes completas.
- `apply_actions` evita caminhos inativos de outage/constraints quando possivel e reutiliza caches de acoes e assets.
- Caminhos escalares de heat pump, storage e battery evitam trabalho repetido de propriedades e NumPy, preservando os outputs fisicos.
- O runtime passa a reportar chaves `info` mais granulares para aplicacao de acoes, observacoes do reward, calculo do reward, proximas observacoes e exports terminais.
- A documentacao clarifica como desligar render/KPI/BAU export durante treino e ligar apenas no episodio final.

### Fixed

- Sem mudancas fisicas intencionais. Um check deterministico contra o codigo pre-otimizacao coincidiu em 179 steps e 220 series fisicas com `max_abs_diff=0.0`.

### Dataset/Schema Impact

- Sem alteracoes de schema ou dataset.

### Compatibility

- Patch compativel. Rewards externos sem requisitos declarados continuam a receber dicionarios completos de observacao.
- APIs de KPI/export mantidas; callers continuam a escolher linhas KPI BAU e serie temporal BAU pelas flags existentes de `export_final_kpis()`.

### Validation

- `.venv/bin/python -m pytest -q`: pass (`333 passed`, `17 warnings`)
- `.venv/bin/python -m compileall -q citylearn scripts`: pass
- `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci scripts/audit --select E9,F821`: pass
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass (`16 passed`)
- `git diff --check`: pass
- Equivalencia fisica contra commit pre-otimizacao: pass (`179 steps`, `220 series`, `max_abs_diff=0.0`)
- `.venv/bin/python scripts/audit/profile_step_breakdown.py --episode-steps 300 --seconds 60 --agent rbc --interface flat --render-mode none --no-write --table-limit 14`: pass (`3.8973 ms/step`, `apply_actions_time=2.4688 ms`)
- `.venv/bin/python scripts/audit/profile_lifecycle.py --episode-steps 300 --seconds 60 --skip-exports --no-write`: pass (`3.8735 ms/step`, `evaluate_v2_with_bau_cold=2.2838 s`, `evaluate_v2_with_bau_cached=0.4336 s`)
- Smoke com reward externo sem declaracao: pass (`5.2452 ms/step` com observacoes completas de reward)
- `.venv/bin/python -m build --outdir /tmp/softcpsrecsimulator-0.6.8-dist`: pass
- `.venv/bin/python -m twine check /tmp/softcpsrecsimulator-0.6.8-dist/*`: pass

### Migration Notes

- Para rewards externos mais rapidos, expor `required_observation_names` com os campos minimos usados por `calculate()`.
- Em treino, manter `render_enabled` e `export_kpis_on_episode_end` desligados salvo nos episodios em que CSV seja mesmo necessario.

## v0.6.6 - Feasibility EV com Servico Eletrico

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release que faz os KPIs de feasibility no departure EV usarem os mesmos limites de headroom eletrico que o simulador aplica as acoes de carregamento.

### Fixed

- A feasibility no departure EV passa a considerar headroom total de importacao, headroom por fase, fase do charger, power outages e eficiencia charger/bateria antes de marcar um target estrito, SOC minimo aceitavel ou limite inferior da tolerancia como alcancavel.
- O Building 15 em cenarios three-phase/electrical-service deixa de ser contado como feasible quando os limites de L1/L2 ou headroom do building tornam o SOC de departure fisicamente impossivel.

### Dataset/Schema Impact

- Sem alteracoes de schema. A feasibility passa a usar a configuracao existente de electrical service, phase connection, headroom, eficiencia do charger e eficiencia da bateria, alem do schedule do charger, capacidade da bateria EV, potencia do charger e SOC de chegada.

### Compatibility

- Nomes de KPI e formato dos exports ficam iguais. So a classificacao feasible/infeasible fica mais estrita quando os limites eletricos ou eficiencia reduzem a potencia fisicamente disponivel para carregar.

### Validation

- `.venv/bin/python -m pytest tests/test_kpi_v2.py -q`: pass (`30 passed`)
- `.venv/bin/python -m pytest tests/unit/test_charging_constraints.py -q`: pass (`5 passed`)
- `.venv/bin/python -m pytest tests/test_kpi_golden.py tests/test_charging_constraints_dataset.py tests/test_charging_constraints_e2e.py -q`: pass (`13 passed`)
- `git diff --check`: pass

### Migration Notes

- Usar os mesmos KPIs EV feasible-only de antes. Em cenarios com headroom apertado por building/fase, alguns departures antes contados como feasible podem agora passar corretamente para infeasible.

## v0.6.5 - KPIs EV Fair por Feasibility no Departure

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release que separa resultados EV brutos no departure de resultados justos para avaliar o controlador quando o SOC pedido era fisicamente impossivel durante o intervalo ligado.

### Added

- Contadores de feasibility para departures EV em que o target estrito, o limiar minimo aceitavel ou o limite inferior da tolerancia simetrica eram/nao eram alcancaveis carregando sempre na potencia maxima do charger/bateria.
- Racios EV feasible-only:
  - `*_ev_performance_departure_success_feasible_ratio`
  - `*_ev_performance_departure_min_acceptable_feasible_ratio`
  - `*_ev_performance_departure_within_tolerance_feasible_ratio`

### Changed

- Os racios EV existentes continuam brutos sobre todos os departures validos.
- O KPI recomendado para qualidade do controlador passa a ser `*_ev_performance_departure_min_acceptable_feasible_ratio`; usar racios brutos mais contadores infeasible para perceber experiencia do utilizador e feasibility do schedule.
- O smoke de performance do CI passa a reportar o tempo terminal de export render/KPI/BAU separado da latencia recorrente de step, para `render_mode=end` nao inflacionar `avg_step_ms` enquanto o export continua validado contra a baseline.

### Dataset/Schema Impact

- Sem alteracoes de schema. A feasibility usa o schedule do charger, capacidade da bateria EV, potencia do charger e SOC de chegada ja existentes.
- Se faltarem dados de charger, bateria ou SOC de chegada, o departure e tratado como feasible para compatibilidade.

### Compatibility

- Linhas KPI aditivas em `evaluate_v2()` e exports. Nomes e semantica dos KPIs existentes ficam preservados.

### Validation

- `.venv/bin/python -m pytest tests/test_kpi_v2.py -q`: pass (`28 passed`)
- `.venv/bin/python -m pytest tests/test_kpi_golden.py tests/unit/test_subhour_scaling.py::test_15_second_charge_immediately_meets_ev_departure_kpis -q`: pass (`11 passed`)
- `.venv/bin/python -m pytest tests/test_ev_arrivals.py::test_ev_kpi_evaluation_with_evs_and_chargers -q`: pass (`1 passed`)
- `.venv/bin/python -m pytest tests/unit/test_rendering_behaviour.py::test_auto_kpi_export_reports_debug_timing -q`: pass (`1 passed`)
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --none-max-ms 30 --end-max-ms 45 --ratio-max 2.0 --entity-overhead-ratio-max 1.08 --baseline-file scripts/ci/perf_baseline.json --baseline-regression-ratio 3.0 --baseline-slack-ms 10.0 --metrics-output /tmp/perf_smoke_report.json`: pass
- `.venv/bin/python -m compileall citylearn/internal/kpi.py`: pass

### Migration Notes

- Avaliar servico do controlador com `*_ev_performance_departure_min_acceptable_feasible_ratio`.
- Usar `*_ev_events_departure_*_infeasible_count` como diagnostico do cenario/dados, nao como falha do controlador.

## v0.6.4 - Fixes de Auditoria de Readiness

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release da auditoria final de readiness a EVs, BESS estacionaria, deferrable appliances, observacoes, acoes, KPIs, topologia dinamica e todos os datasets incluidos.

### Changed

- Bounds grandes de observation space passam a usar reducoes vetorizadas e robustas a valores nao finitos, melhorando runtime/auditoria em datasets CSV e parquet de 15 segundos.
- Smoke actions em entity mode passam a cobrir todas as tabelas de acao anunciadas, incluindo deferrable appliances.
- Checks de regressao de performance aceitam `render_mode=end` quando a latencia absoluta fica dentro do budget configurado.
- Snapshots KPI do SAC passam a semear tambem os action spaces do agente para output deterministico.

### Fixed

- Cargas eletricas de devices populadas pelo reset no primeiro step sao limpas antes de aplicar acoes, evitando falsos failures de demand limit em datasets de neighborhood.
- Auditoria de datasets resolve corretamente `root_directory` relativo ao repositorio.
- Auditorias de datasets libertam ambientes fechados antes de continuar, reduzindo retencao de memoria em checks grandes segmentados.

### Dataset/Schema Impact

- Sem migracao de schema obrigatoria.
- Todos os schemas de datasets incluidos foram validados com rollouts default, flat/entity quando aplicavel, e dynamic probe.

### Compatibility

- Patch compativel para schemas e agentes validos.
- Baselines de auditoria foram atualizadas para refletir o contrato KPI/export hardenizado do v0.6.3 e o fix fisico do primeiro step.

### Validation

- `.venv/bin/python -m compileall -q citylearn scripts`: pass
- `.venv/bin/python -m pytest -q tests/unit/test_subhour_scaling.py tests/test_15_second_power_fixture.py tests/unit/test_physics_units_refactor.py tests/test_dynamic_topology_entity_mode.py tests/test_dataset_loader_window_parquet.py`: pass (`53 passed`)
- `.venv/bin/python -m pytest -q`: pass (`326 passed`)
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py --max-scenarios 32`: pass (`16 passed`)
- `.venv/bin/python scripts/audit/audit_performance_results.py --strict`: pass
- Auditoria segmentada a todos os schemas incluidos: pass (`31 passed`, `0 failed`, `0 timeout`)
- `.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 240 --seconds 60 --seed 0`: pass
- `.venv/bin/pip check`: pass

### Migration Notes

- Nenhuma.

## v0.6.3 - Hardening de Fisica, Bounds e Topologia Dinamica

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release da segunda auditoria profunda a EVs, BESS estacionaria, deferrable appliances, observacoes, KPIs e exports com topologia dinamica.

### Changed

- Bounds de observacao passam a considerar schedules reais de EV/deferrables, perfis sub-hour e minutos zero-based.
- Caminhos de KPI/export em topologia dinamica usam membership ativo por timestep para buildings, chargers, storage estacionario e deferrable appliances.
- Medias diarias de KPI para buildings dinamicos usam a janela ativa de cada building, nao a janela global do episodio.
- KPIs BAU de peak e ramping passam a usar potencia em kW em vez de kWh/step bruto.
- Export CSV de KPIs preserva precisao raw por defeito; arredondamento passa a ser opt-in.

### Fixed

- Standby loss da BESS estacionaria e aplicada uma vez por timestep e nao pode empurrar SOC abaixo do minimo fisico de DoD.
- Descarga da BESS em outage fica limitada a carga local que pode ser servida de facto.
- Cargas iniciais em outage sao clipped a oferta local PV/BESS em vez de dispararem assert de flexibilidade negativa.
- SOC required/arrival de EV aceita fracoes e percentagens, preservando sentinels negativos de missing value.
- `can_start` e constraints de acoes deferrable validam o perfil multi-step inteiro contra outages e headroom do electrical service.
- Perfis de ciclo deferrable acima de `nominal_power` sao rejeitados.
- KPIs de mercado comunitario settled, counterfactual e savings ficam expostos no contrato KPI v2/export.
- Peaks por fase em topologia dinamica sao acumulados numa timeline distrital alinhada em vez de janelas locais truncadas.

### Dataset/Schema Impact

- Sem migracao de schema obrigatoria.
- Observacoes de minuto passam a usar `0..59`, alinhado com semantica normal de relogio.
- Bounds de observation space podem ficar mais largos para schedules EV/deferrable longos e perfis sub-hour.

### Compatibility

- Patch compativel para schemas validos.
- Battery efficiencies acima de `1.0`, DoD invalido e perfis deferrable fisicamente impossiveis passam a falhar cedo.
- Exported KPIs podem sair com mais casas decimais salvo uso explicito de `kpi_round_decimals`.

### Validation

- `.venv/bin/python -m compileall -q citylearn`: pass
- `.venv/bin/python -m pytest -q`: pass
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py --max-scenarios 32`: pass (`16 passed`)
- `.venv/bin/python scripts/manual/demo_ev_rbc.py`: pass
- `.venv/bin/python scripts/manual/demo_ev_rbc_export_minutes.py`: pass
- `.venv/bin/python scripts/manual/demo_charging_constraints_export_end.py`: pass
- Smoke de topologia dinamica entity com acoes zero e avaliacao BAU KPI: pass (`95 steps`, `2937 KPI rows`)
- `git diff --check`: pass

### Migration Notes

- Algoritmos que tenham bounds de minuto hard-coded como `1..61` devem passar para `0..59`.
- Consumidores que esperem KPIs exportados arredondados devem chamar `kpi_round_decimals=3`.

## v0.6.0 - Baseline Business-As-Usual Nativa

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Adiciona uma baseline operacional business-as-usual nativa, separada da baseline contrafactual atual dos KPIs. A nova referencia BAU modela comportamento normal do dia a dia: EVs ligados carregam para 100%, deferrables arrancam assim que possivel, e baterias estacionarias fazem autoconsumo PV simples.

### Added

- `citylearn.agents.baseline.BusinessAsUsualAgent`, sem dependencia do repo externo `Algorithms`.
- Simulacao sidecar lazy/cacheada em `CityLearnEnv.run_business_as_usual_baseline(force=False)`.
- Linhas `evaluate_v2(include_business_as_usual=True)` para totais, deltas e ratios BAU em custo, emissoes, import/export/net exchange, EVs, BESS, deferrables e shape-quality distrital.
- `exported_data_business_as_usual_ep{episode}.csv`, uma serie temporal compacta para auditar BAU por building e distrito.
- Cobertura unit/integration para comportamento BAU em EV, deferrables, BESS, KPI, export e CLI.

### Changed

- `citylearn simulate` passa a usar `citylearn.agents.baseline.BusinessAsUsualAgent` por defeito.
- `export_final_kpis(...)` passa a incluir KPIs BAU e a exportar a serie temporal BAU por defeito.
- A documentacao de `BaselineAgent` passa a descreve-lo como baseline legacy passiva/no-control.

### Dataset/Schema Impact

- Sem migracao de schema e sem novas chaves no schema.
- BAU usa a mesma janela de dataset/schema, buildings/EVs selecionados e timestep fisico do ambiente avaliado.

### Compatibility

- Minor release com mudancas comportamentais intencionais nos defaults de simulacao, KPI e export.
- Mudanca comportamental no CLI: simulacoes sem `--agent_name` passam a correr BAU operacional em vez do `BaselineAgent` passivo/no-control.
- Os nomes KPI v2 existentes com `baseline` sao preservados; BAU usa os novos nomes `business_as_usual`, `delta_to_business_as_usual` e `ratio_to_business_as_usual`.
- `evaluate_v2(include_business_as_usual=False)` e `export_final_kpis(include_business_as_usual=False)` preservam o shape antigo e evitam o custo da simulacao sidecar.

### Validation

- `.venv/bin/python -m pytest tests/unit/test_business_as_usual_baseline.py -q`: pass (`9 passed`)
- `.venv/bin/python -m pytest tests/test_kpi_v2.py tests/unit/test_ui_export_contract.py tests/unit/test_rendering_behaviour.py -q`: pass (`43 passed`)
- `.venv/bin/python -m pytest tests/test_deferrable_appliance_integration.py tests/test_ev_arrivals.py tests/unit/test_electric_vehicle.py tests/unit/test_battery.py -q`: pass (`41 passed`)
- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`308 passed`)
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/audit/audit_physics.py`: pass (`16 passed`)
- `.venv/bin/python scripts/manual/demo_ev_rbc.py`: pass
- `../Algorithms/.venv/bin/python -m pytest tests/test_rbc_agent.py tests/test_baseline_policies.py tests/test_benchmark_agents.py tests/test_wrapper_action_clipping.py tests/test_entity_adapter.py tests/test_wrapper_entity_mode.py -q`: pass (`45 passed`)
- `git diff --check`: pass

### Migration Notes

- Usar `citylearn.agents.base.BaselineAgent` explicitamente se for necessario o comportamento CLI antigo passivo/no-control.
- Consumidores que enumeram nomes KPI v2 devem aceitar as novas linhas BAU em `evaluate_v2()` e `exported_kpis.csv`.

## v0.5.4 - Semantica Fisica EV/BESS/Deferrables e Hardening de Outage

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release da auditoria profunda ao simulador, focada em tornar EVs, baterias estacionarias, deferrable appliances, outages, sinais raw de dataset e bounds de observacao fisicamente consistentes em timesteps desde segundos ate horas.

### Added

- Invariante runtime de balanco local em outage, que valida que as cargas locais durante outage nao excedem as fontes locais.
- Testes de regressao para precos/carbon raw, bloqueio de EV/deferrables sem surplus local em outage, e bounds de storage em kWh por control step.
- Snapshots do contrato entity atualizados para o naming normalizado `deferrable_appliance_*`.

### Changed

- Mismatch entre timestep do dataset e `seconds_per_time_step` continua responsabilidade do utilizador: o simulador imprime aviso explicito de conversao de unidades, mas nao faz resampling automatico.
- Series de pricing e carbon intensity preservam os valores raw do dataset em vez de fazer clipping para `[0, 1]`; precos negativos de eletricidade sao suportados.
- Bounds de observacao para consumo eletrico de devices e storage usam agora kWh por control step, nao kW nominal.
- Starts de deferrable appliances entram no calculo de headroom do electrical service antes de escalar acoes EV/BESS.
- Durante power outages, charging EV e starts deferrable ficam limitados ao surplus local disponivel. EV discharge e bloqueado no caminho de outage porque o modelo atual nao encaminha descarga EV para alimentar cargas locais do building.

### Fixed

- Arrival EV ja nao faz fallback para required departure SOC quando falta current/arrival SOC; o SOC existente da bateria e carregado para a frente.
- Atributos do schema da bateria EV, como efficiency, degradation e power curves, passam a ser carregados na bateria EV real.
- SOC de EV e bateria estacionaria passa a ser carregado para a frente nas observacoes do timestep atual quando nao ha energia pedida.
- Carry-forward da BESS estacionaria aplica standby loss de forma consistente pelo caminho comum de storage.
- KPIs de normalized unserved energy ignoram surplus como unserved negativo, mascaram steps sem outage nos KPIs de outage, e devolvem zero em vez de NaN quando o denominador de expected energy e zero.

### Dataset/Schema Impact

- Sem migracao obrigatoria de schema.
- Autores de dataset continuam responsaveis por alinhar `seconds_per_time_step` com a cadencia dos dados ou por usar `time_step_ratio` intencionalmente.
- Algoritmos que assumiam pricing ou carbon intensity codificados em `[0, 1]` devem normalizar externamente.
- Bounds Gym de observacao podem mudar para observacoes de consumo eletrico em runs sub-hourly e multi-hour, porque agora os bounds usam kWh por step.

### Compatibility

- Patch compativel para schemas validos.
- Mudanca comportamental para comandos fisicamente impossiveis em outage: cargas EV/deferrable ja nao podem consumir energia da rede indisponivel durante outages.
- Mudanca comportamental para datasets com precos negativos ou valores acima de um: os valores raw passam a ser expostos a algoritmos e KPIs.

### Validation

- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`299 passed`)
- `.venv/bin/python scripts/audit/audit_physics.py`: pass (`16 passed`)
- `.venv/bin/python scripts/audit/audit_entity_contract.py --strict`: pass
- `.venv/bin/python scripts/manual/demo_ev_rbc.py`: pass
- `../Algorithms/.venv/bin/python -m pytest tests/test_rbc_agent.py tests/test_baseline_policies.py tests/test_benchmark_agents.py tests/test_wrapper_action_clipping.py tests/test_entity_adapter.py tests/test_wrapper_entity_mode.py -q`: pass (`45 passed`)
- `git diff --check`: pass

### Migration Notes

- Manter normalizacao de pricing/carbon no layer de algoritmo/preprocessamento, nao no simulador.
- Em experiencias de outage, usar storage estacionario/PV como fontes locais; EV discharge nao deve ser tratado como V2B ate esse routing existir explicitamente.
- Rever agentes treinados que dependam dos bounds antigos dimensionados em kW ou de sinais de mercado clipados.

## v0.5.3 - Hardening de Fisica Sub-Hour em Storage/EV

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release que corrige a fisica de timestep em storage para datasets sub-hourly e multi-hour, e impede baterias EV de herdarem standby loss implicito de storage estacionario quando o schema EV nao configura explicitamente `loss_coefficient`.

### Fixed

- Baterias EV passam a usar `loss_coefficient=0.0` quando `electric_vehicles_def.*.battery.attributes.loss_coefficient` esta ausente ou `null`.
- `StorageDevice.loss_coefficient` passa a ser interpretado como ratio horario e convertido para perda efetiva por step com `loss_coefficient * seconds_per_time_step / 3600`.
- `Battery.charge(...)` passa a aplicar limites de carga/descarga em kWh fisicos por control step, em vez de tratar comandos kWh como kW.
- Curvas de eficiencia de `Battery` passam a usar potencia media no step fisico, nao energia bruta do step.
- `StorageTank` passa a preservar o `time_step_ratio` recebido no construtor; antes podia ser sobrescrito pelo init base de `Device`.
- Acoes de BESS estacionario passam a ser clipped para `[-1, 1]` antes da conversao para kWh fisicos.
- Datasets sub-hourly nativos, incluindo 15 segundos, deixam de perder SOC EV artificialmente ao longo de milhares de steps ligados por causa do default de storage estacionario.

### Dataset/Schema Impact

- Schemas EV existentes continuam validos.
- `battery.attributes.loss_coefficient` em EVs e opcional e normalmente deve ficar omitido.
- Se `loss_coefficient` EV for configurado, e um ratio de perda por hora. O modelo de storage converte para perda efetiva por step fisico.
- Ranges default de parametros de storage estacionario ficam inalterados, mas `loss_coefficient` passa a ter semantica horaria fisica em timesteps sub-hour, hourly e multi-hour.

### Compatibility

- Backward compatible para schemas que nao definem `loss_coefficient` em EVs.
- Schemas EV que definem explicitamente `loss_coefficient` passam a ter semantica horaria corrigida para sub-hourly; isto e intencional.
- Observacoes, rewards e nomes dos KPIs EV de departure ficam inalterados.
- Simulacoes com storage estacionario que dependiam explicitamente do comportamento antigo de standby loss por ratio em datasets nao horarios passam a ver perdas fisicas corrigidas.

### Validation

- `.venv/bin/python -m pytest -q tests/unit/test_subhour_scaling.py tests/unit/test_battery.py tests/unit/test_electric_vehicle_charger.py tests/test_ev_soc_behavior.py tests/unit/test_physics_units_refactor.py tests/unit/test_physics_invariants.py tests/test_kpi_v2.py tests/test_kpi_golden.py tests/unit/test_deferrable_appliance.py tests/test_deferrable_appliance_integration.py`: pass (`113 passed`)
- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`286 passed`)

### Migration Notes

- Nao configurar `loss_coefficient` em EV salvo necessidade explicita de standby loss.
- Para EVs, se o campo for usado, fornecer um ratio horario; o simulador trata do scaling sub-hourly.
- Para storage estacionario, manter valores horarios existentes de `loss_coefficient`. O simulador passa a escalar esses valores pela duracao real do timestep.

## v0.5.2 - KPIs EV de Servico no Departure

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release que separa cumprimento estrito do target SOC, servico minimo aceitavel para o utilizador e accuracy simetrica face ao target no departure EV.

### Added

- Configuracao ambiente/schema `ev_departure_service_tolerance`, default `0.05`.
- KPIs por building e district para departures EV com minimo aceitavel.
- KPIs por building e district para shortfall de SOC alem da tolerancia de servico.
- Diagnosticos EV de SOC surplus, erro absoluto e tolerancia configurada.

### Changed

- Nomes e semantica dos KPIs EV existentes de success, within-tolerance e deficit ficam preservados.
- `ev_departure_within_tolerance` continua a ser a tolerancia simetrica de proximidade ao target.

### Dataset/Schema Impact

- Schemas existentes continuam validos.
- Nova chave top-level opcional: `ev_departure_service_tolerance`.
- A chave opcional `ev_departure_within_tolerance` configura a tolerancia simetrica de accuracy.

### Compatibility

- Release aditiva e compativel.
- Consumidores que enumeram todos os nomes KPI v2 devem aceitar as novas linhas EV em `evaluate_v2()` e `exported_kpis.csv`.

### Validation

- `.venv/bin/python -m pytest -q tests/test_kpi_v2.py -q`: pass
- `.venv/bin/python -m pytest -q tests/test_kpi_golden.py -q`: pass
- `.venv/bin/python -m pytest -q tests/unit/test_export_logic.py tests/unit/test_ui_export_contract.py -q`: pass
- `.venv/bin/python -m pytest -q --ignore=scripts/manual`: pass (`276 passed`)
- `.venv/bin/python -m compileall -q citylearn tests/test_kpi_v2.py`: pass

### Migration Notes

- Usar `*_ev_performance_departure_min_acceptable_ratio` como KPI principal de conforto/servico EV.
- Usar `*_ev_performance_departure_success_ratio` para cumprimento estrito do target.
- Usar `*_ev_performance_departure_within_tolerance_ratio` e erro absoluto para accuracy/eficiencia.

## v0.5.1 - Hardening do Comando de Start dos Deferrables

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Patch release focada em tornar o controlo de deferrable appliances mais seguro para treino RL, tratando a acao de start como comando ON/OFF explicito e evitando arranques precoces causados por valores continuos pequenos e positivos.

### Changed

| Area | Mudancas |
|---|---|
| Semantica da acao deferrable | O default de `DeferrableAppliance.trigger_threshold` passou de `0.0` para `0.5`. |
| Robustez do comando | Valores nao finitos (`nan`, `inf`) passam a OFF e nao arrancam ciclos. |
| Contrato para controladores | A documentacao passa a explicitar intencao binaria (`0` off, `1` on) e recomenda usar `deferrable_appliance_can_start` como sinal de disponibilidade. |

### Dataset/Schema Impact

- Sem mudanca estrutural de schema.
- `attributes.trigger_threshold` continua suportado.
- Schemas que dependiam do default implicito `0.0` passam a usar default mais seguro `0.5`, exceto quando houver override explicito.

### Compatibility

Mudanca comportamental de patch:
- com configuracao default, acoes positivas pequenas deixam de arrancar ciclos.
- para manter comportamento legacy, configurar `deferrable_appliances.<id>.attributes.trigger_threshold: 0.0`.

### Validation

| Comando | Resultado |
|---|---|
| `.venv/bin/pytest -q tests/unit/test_deferrable_appliance.py tests/test_deferrable_appliance_integration.py` | Pass (`10 passed`). |
| `.venv/bin/pytest -q tests/test_dynamic_topology_entity_mode.py -k deferrable` | Pass (`1 passed`, `13 deselected`). |

### Migration Notes

- Se o controlador emitia valores continuos arbitrarios em `[0, 1]`, mapear agora para ON/OFF explicito (por exemplo, `0.0` ou `1.0`).
- Se precisares intencionalmente do comportamento antigo mais permissivo, configura `trigger_threshold=0.0` por appliance.

## v0.5.0 - Hardening de Consistencia Acao-Asset (Breaking)

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Release breaking que remove mismatches silenciosos entre acoes e devices para controlo de storage, impoe compatibilidade estrita entre schema dinamico e modo de topologia e consolida o contrato publico de datasets deferrable.

### Added

| Area | Mudancas |
|---|---|
| Datasets 15s Parquet | Foram adicionados e versionados os datasets de 15 segundos em parquet `citylearn_three_phase_dynamic_assets_only_demo_15s_parquet` e `citylearn_three_phase_electrical_service_demo_15s_parquet`. |
| Normalizacao de naming em datasets | Migracao de ficheiros/IDs legacy `washing_machine_*` para `deferrable_appliance_*` em `citylearn_three_phase_electrical_service_demo`, `citylearn_three_phase_dynamic_topology_demo` e `citylearn_challenge_2022_phase_all_plus_evs`. |

### Changed

| Area | Mudancas |
|---|---|
| Validacao de topology mode | Schemas que declaram topologia dinamica (`topology_mode: dynamic` ou `topology_events`) passam a rejeitar `topology_mode='static'` no arranque. |
| Consistencia em static | Em modo static, se `electrical_storage` estiver ativa para building sem storage efetivo e sem opt-out em `inactive_actions`, o arranque falha de forma explicita. |
| Exposicao de acoes em dynamic | A sincronizacao dinamica agora mantem precedencia de `inactive_actions` para `electrical_storage`, acoes de chargers EV e acoes de deferrables. |

### Dataset/Schema Impact

- Datasets dinamicos devem correr com `topology_mode='dynamic'` e `interface='entity'`.
- Em datasets static com `actions.electrical_storage.active=true`, cada building deve:
  - declarar um `electrical_storage` efetivo, ou
  - fazer opt-out explicito com `inactive_actions: ["electrical_storage"]`.
- O naming oficial de deferrables nos datasets fornecidos passa a ser `deferrable_appliance_*`; o naming legacy `washing_machine_*` foi removido de `data/datasets`.
- Os schemas 15 segundos em parquet passam a ser artefactos oficiais versionados para uso direto em smoke/regression.

### Compatibility

Breaking change intencional:
- deixa de existir fallback silencioso para inconsistencias storage-action em static;
- deixa de ser permitido correr schemas dinamicos em static.

### Validation

| Comando | Resultado |
|---|---|
| `tests/test_dynamic_topology_entity_mode.py` com testes direcionados de consistencia | Pass. |
| `.venv/bin/pytest -q tests/test_dynamic_topology_entity_mode.py tests/test_dynamic_topology_assets_only_dataset.py` | Pass (`15 passed`). |
| `.venv/bin/pytest -q tests/test_dynamic_topology_entity_mode.py tests/test_15_second_power_fixture.py tests/test_dataset_loader_window_parquet.py` | Pass (`17 passed`). |
| Smoke 15s (`CityLearnEnv` reset + step) para variantes CSV e parquet de dynamic-assets-only e electrical-service | Pass (`4/4`). |
| Smoke do catalogo completo com carregamento por janela (`31` schemas) | `27` pass; `4` falhas conhecidas pre-existentes de sizing HVAC fora do ambito da migracao EV/deferrable. |

### Migration Notes

- Se antes corrias schemas dinamicos em static, atualiza configuracoes para `topology_mode='dynamic'` e `interface='entity'`.
- Se um run static falhar com erro de consistencia de storage, explicita a intencao no schema (declarar storage ou usar `inactive_actions` por building).

## v0.4.3 - Contrato de Documentacao e Preparacao de Release

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Release focada em tornar o simulador mais facil de adotar, auditar e integrar, transformando o README num portal de documentacao e adicionando documentacao bilingue.

### Added

| Area | Mudancas |
|---|---|
| README | Mapa de documentacao em ingles por default com links para portugues. |
| Como correr simulacoes | Instalacao, quickstarts, CLI, parametros de `CityLearnEnv`, render/export e validacao. |
| Schema | Referencia de buildings, devices, modos PV, EVs, chargers, deferrables, topology e community market. |
| Interfaces | Contratos flat/entity, entity specs, tabelas, edges e dynamic topology. |
| Acoes | Nomes, ranges, conversoes fisicas e payloads entity. |
| Observacoes | Dicionario com unidades, sentinels, bundles, tabelas entity e edges. |
| Datasets | Contrato CSV/Parquet, conversao de dados reais, 15s e formato de deferrables. |
| KPIs | Explicacao v1/v2, unidades, equacoes e familias EV/BESS/deferrable/community/fases. |
| Features | Inventario de capacidades do simulador. |
| Releases | Checklist, politica de versao e template de changelog. |
| Developer guide | Testes, auditorias, checks de performance e arquitetura interna. |
| Publishing guide | Workflow PyPI e checks locais de build. |
| Docs PT | Mirror completo em portugues em `docs/pt/`. |

### Compatibility

Nao introduz breaking changes de runtime. A release mantem as mudancas aditivas do simulador documentadas em `v0.4.2`.

### Validation

| Check | Resultado |
|---|---|
| Links Markdown locais | Pass. |
| `git diff --check` | Pass. |
| Smoke simulation flat | Pass. |
| Smoke simulation entity | Pass. |
| Smoke simulation 15s Parquet | Pass. |

## v0.4.2 - Expansao Aditiva de Observacoes Fisicas

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Release aditiva focada em melhorar a informacao fisica disponivel para algoritmos sem remover observacoes antigas.

### Added

| Area | Mudancas |
|---|---|
| Chargers | `min_charging_power_kw`, `min_discharging_power_kw`, `charger_efficiency_ratio`. |
| Chargers core | `charge_efficiency_at_max_ratio`, `discharge_efficiency_at_max_ratio`, incoming EV required/departure/hours/ratio. |
| Storage | `min_charge_power_kw`, `min_discharge_power_kw`, `efficiency_ratio`, `round_trip_efficiency_ratio`. |
| Storage core | `current_efficiency_ratio`, `degraded_capacity_kwh`, `soc_min_ratio`. |
| Storage phases | `phase_connection_L1/L2/L3`. |
| Deferrables | `must_run`, average/peak/load factor, peak offset, remaining duration/power, current step power. |
| Building core | `charging_total_service_power_kw`, `charging_phase_L1/L2/L3_power_kw`. |
| PV | `generation_capacity_factor_ratio`. |

### Compatibility

Compatibilidade aditiva. Observacoes antigas e duplicacoes EV/charger foram mantidas.

### Validation

| Comando | Resultado |
|---|---|
| Focused tests de entity/bundles/deferrables/parquet | Pass. |
| Broader simulator tests | Pass. |
| Full suite | Pass. |
| `audit_entity_contract.py --strict` | Pass. |
| `audit_physics.py` | Pass. |

## v0.4.0 - Deferrable Appliances Normalizados

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Introduziu o modelo oficial de `deferrable_appliances` com catalogo de ciclos e schedule de flexibilidade, substituindo o formato antigo de washing machines.

### Added

| Area | Mudancas |
|---|---|
| Schema | `deferrable_appliances` com `cycle_profiles_file` e `flexibility_schedule_file`. |
| Modelo | `DeferrableAppliance` com ciclo pendente/running/missed/completed. |
| Actions | `deferrable_appliance_{id}` no flat e `start` na entity table. |
| Observations | Pending, running, can_start, deadlines, slack, priority, energia restante. |
| KPIs | Completed/missed cycles, service level, served/unserved energy, delay medio. |
| Dynamic topology | Add/remove `deferrable_appliance`. |

### Compatibility

Breaking change de schema: `washing_machines` deixou de ser o formato oficial.

## v0.3.2 - Performance, 15s e Parquet

Release owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Consolidou suporte sub-horario e melhorou performance para datasets grandes, especialmente 15 segundos.

### Added/Changed

| Area | Mudancas |
|---|---|
| Loader | Leitura por janela em CSV e Parquet. |
| Cache | Partilha weather/pricing/carbon quando o ficheiro e igual e sem noise. |
| Parquet | Datasets 15s podem usar `.parquet`. |
| Sub-hourly | Fixtures/testes para 15s, 1min, 5min, 15min e 1h. |
| PV | Modo `absolute` para datasets reais em `kWh/step`. |
| Unit contract | Documentacao formal de kWh/step, kW, preco e emissoes. |

## Pre-v0.3 - EVs e Washing Machines Iniciais

Fork owner: [@calofonseca](https://github.com/calofonseca).

### Summary

Antes da consolidacao dos deferrables normalizados, o fork introduziu EVs/chargers e washing machines iniciais no simulador.

### Added

| Area | Mudancas |
|---|---|
| EVs | EV definitions, charger schedules, connected/incoming EV observations. |
| Chargers | Acoes de charging/discharging e schedules por charger. |
| Washing machines | Primeira versao de appliances flexiveis. |
| Algorithms integration | Preparacao para RBC/MADDPG e repos externos. |
