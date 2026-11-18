# Versões

Alterações, compatibilidade, validação e medições da versão atual do CityLearn.
O [guia de publicação](publishing.md) descreve o procedimento para mantenedores.

## Por publicar

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
- Os ficheiros de entrada e os resultados de simulação não mudam; não é
  necessária migração.

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
