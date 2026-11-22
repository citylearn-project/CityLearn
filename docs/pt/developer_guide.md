# Guia de desenvolvimento

Configure um ambiente de desenvolvimento, execute verificações de regressão e
analise o desempenho em tempo de execução. Para verificações ao nível da
simulação e medições publicadas, comece por
[Validação e desempenho](validation.md).

Versão em inglês: [../developer_guide.md](../developer_guide.md).

## Ambiente local

Crie um ambiente isolado a partir de um checkout do repositório:

```console
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r test_requirements.txt
python -m pip install -e .
```

O `test_requirements.txt` instala o PyTorch e o scikit-learn, de que precisam os
testes da dinâmica térmica LSTM e dos controladores SAC e MARLISA. Sem GPU,
execute primeiro `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu`
para evitar vários GB de bibliotecas CUDA. O Ray RLlib não é uma dependência dos
testes: os wrappers RLlib só o importam quando está instalado.

Dependências opcionais:

| Funcionalidade | Comando |
|---|---|
| Datasets Parquet | `.venv/bin/pip install -e ".[parquet]"` |
| Dimensionamento automático FV | `.venv/bin/pip install -e ".[pysam]"` |
| Testes em paralelo | `.venv/bin/pip install pytest-xdist` |
| Relatório de cobertura (`--cov=citylearn`) e limite de 600 s por teste do `pytest.ini` | `.venv/bin/pip install pytest-cov pytest-timeout` (ambos estão em `test_requirements.txt`) |
| Testes de conservação de energia baseados em propriedades | `.venv/bin/pip install hypothesis` (em `test_requirements.txt`; `tests/test_property_energy_conservation.py` é ignorado sem ele) |
| Verificação dos notebooks | `.venv/bin/pip install nbclient nbformat ipykernel` |
| Wrappers RLlib | `.venv/bin/pip install "ray[rllib]"` (testado com Ray 2.60.0; `tests/test_rllib_wrappers.py` é ignorado sem ele) |
| Verificações de build | `.venv/bin/pip install build twine` |

## Evidência portátil de experiências

O `.gitattributes` torna cada checkout idêntico ao repositório byte a byte: os
ficheiros de texto usam LF e os ficheiros em `data/` e `tests/data/` nunca são
convertidos, mesmo com o `core.autocrlf=true` predefinido do Git for Windows. Os
manifestos de experiências calculam hashes destes ficheiros, que assim coincidem
em todas as plataformas. Um checkout feito antes de existir o `.gitattributes`
pode ainda conter cópias CRLF; o `git status` mostra os ficheiros de dados
convertidos como modificados. Faça um clone novo e configure-o como em
[Ambiente local](#ambiente-local): o clone aplica as novas regras de checkout e
deixa intacta a cópia de trabalho existente, incluindo as alterações não
registadas em commit. Depois, limpe a cache de datasets, que pode conter cópias
feitas a partir do checkout antigo:

```console
git clone https://github.com/citylearn-project/CityLearn.git
python -c "from citylearn.data import DataSet; DataSet().clear_cache()"
```

Os manifestos registam cada ficheiro de entrada pelo seu caminho abaixo da raiz
do dataset, com separadores `/`, pelo que um dataset movido ou copiado mantém a
sua evidência. No Windows, onde `\` e `/` são ambos separadores e os nomes de
ficheiros não distinguem maiúsculas de minúsculas, uma referência que só difere
do caminho do ficheiro nos separadores ou nas maiúsculas regista a grafia do
ficheiro no disco: com a raiz do dataset `C:\data\demo` e o ficheiro
`C:\data\demo\sub\weather.csv`, as referências `sub\Weather.csv`,
`SUB/weather.csv` e `C:\Data\Demo\sub\WEATHER.csv` registam todas
`sub/weather.csv`. As outras grafias de um ficheiro de entrada mantêm o seu
texto, com `/` em vez de `\` no Windows: componentes `.` ou `..`, separadores
repetidos, ligações (links), nomes curtos 8.3 e ficheiros fora da raiz do
dataset. As strings que não são ficheiros de entrada com hash (ver `FILE_TYPES`
em `citylearn/internal/temporal.py`) mantêm o seu texto sem a raiz do dataset.
No Linux e no macOS todas as referências mantêm o seu texto, sem a raiz do
dataset; por omissão, os nomes de ficheiros no macOS não distinguem maiúsculas
de minúsculas, mas a evidência distingue. Se duas execuções escreverem o mesmo
ficheiro de formas que não são normalizadas, a comparação indica `incompatible`
e não um par.

## Validação principal

| Verificação | Comando |
|---|---|
| Subconjunto rápido (cerca de um minuto) | `.venv/bin/pytest -q tests/unit` |
| Suite de testes completa (vários minutos; `-n 4` com pytest-xdist) | `.venv/bin/pytest -q` |
| Notebooks de exemplo | `.venv/bin/python scripts/ci/run_notebooks.py` |
| Lint (regras em `pyproject.toml`, como no CI) | `.venv/bin/python -m ruff check citylearn tests scripts/manual scripts/ci` |
| Auditoria do contrato de entidades | `.venv/bin/python scripts/audit/audit_entity_contract.py --strict` |
| Auditoria física | `.venv/bin/python scripts/audit/audit_physics.py` |
| Verificação de espaços em branco no diff | `git diff --check` |

A auditoria física exercita de propósito os caminhos de conversão de resolução,
pelo que são de esperar avisos de conversão de unidades quando a fixture da
auditoria força diferenças entre o dataset e o schema.

## Scripts manuais de simulação

Os scripts utilitários manuais estão em `scripts/manual` e ficam excluídos da
recolha predefinida do pytest.

```console
.venv/bin/python scripts/manual/demo_ev_rbc.py
.venv/bin/python scripts/manual/demo_ev_rbc_export_end.py
```

Benchmark do tempo de execução:

```console
.venv/bin/python scripts/manual/bench_runtime.py --seconds 5 60 --render-modes none end --episode-steps 1200
```

Verificação rápida de desempenho do CI:

```console
.venv/bin/python scripts/ci/perf_smoke.py --episode-steps 600 --seconds 60 --baseline-file scripts/ci/perf_baseline.json
```

Profiling por passo e por componente:

```console
.venv/bin/python scripts/audit/profile_step_breakdown.py --episode-steps 300 --seconds 60 --agent rbc --interface flat --render-mode none --no-write --table-limit 14
```

Profiling do ciclo de vida e de KPI/BAU:

```console
.venv/bin/python scripts/audit/profile_lifecycle.py --episode-steps 300 --seconds 60 --skip-exports --no-write
```

Retire `--skip-exports` quando for preciso medir também os caminhos de exportação
CSV.

Para código ad hoc, passe `debug_timing=True` ao `CityLearnEnv` e consulte as
chaves de `info` como `apply_actions_time`, `reward_observations_time`,
`next_observations_time`, `terminal_export_time` e `step_total_time`.

## Arquitetura interna

As APIs públicas continuam centradas em `CityLearnEnv` e `Building`. A
orquestração interna está dividida em módulos de serviço em `citylearn/internal`.

| Módulo | Responsabilidade |
|---|---|
| `loading.py` | Carregamento a partir do schema e montagem dos edifícios. |
| `runtime.py` | Orquestração do episódio em execução, `step`, interpretação das ações, progressão temporal e associação entre VE e carregadores. |
| `building_ops.py` | Orquestração das observações e ações dos edifícios. |
| `kpi.py` | Pipeline de KPIs e avaliação. |
| `entity_interface.py` | Tabelas de entidades, arestas, especificações de ações e bundles de observação. |

## Construir e verificar a documentação

Os guias canónicos em inglês são `docs/*.md`. A extensão Sphinx copia-os para o
diretório gerado `docs/source/guides/` durante o build, preservando as ligações
cruzadas e publicando o mesmo texto do repositório. Não edite o diretório gerado.
A lista de nomes do scorecard é gerada a partir da seleção em tempo de execução.
As versões históricas aparecem em Project, não no README.

```console
python -m pip install -r docs/requirements.txt
sphinx-apidoc citylearn -o docs/source/api -e -M
sphinx-build -b html docs/source docs/build/html
python scripts/ci/check_docs.py docs/build/html
python -m pytest -q tests/test_documentation_examples.py
```

Instale o Pandoc para os tutoriais em notebook que se mantêm. Use o executável
`sphinx-build`: a referência atual da CLI deteta esse executável quando devolve o
seu parser de argumentos. Os exemplos da documentação são testados à parte.

Os notebooks em `examples/` são guardados sem outputs. O workflow do Sphinx
executa-os antes do build (`python scripts/ci/run_notebooks.py --output-dir examples`,
que substitui as fontes apenas nesse checkout) e executa
`check_docs.py --require-notebook-outputs`, pelo que as páginas publicadas dos
notebooks mostram os outputs dessa execução, incluindo um treino curto de RL.
Para o reproduzir localmente, execute estes dois comandos e descarte depois as
alterações em `examples/` (`git checkout examples`). Sem o passo de execução, as
páginas mostram apenas o código.

## Regras de desenvolvimento

| Regra | Motivo |
|---|---|
| Documente as alterações de schema/API na mesma alteração. | Os algoritmos e os datasets dependem de contratos explícitos. |
| Acrescente testes para física ou observações novas. | O comportamento sub-horário e das entidades regride facilmente sem dar sinal. |
| Prefira observações aditivas em versões de patch. | Evita quebrar algoritmos treinados e wrappers. |
| Execute as auditorias antes de criar a tag. | Apanham desvios de contrato fora dos testes unitários normais. |

## Verificação e módulos internos na 3.1

Execute `python scripts/audit/run_full_audit.py --strict --output-dir /tmp/citylearn-audit`
para verificar a física, os contratos de entidades, os datasets oficiais e seis
trajetórias de referência com comandos fixos. Dependências ou scripts em falta,
falhas dos processos filhos e desvios das referências fazem falhar a verificação;
as execuções normais não reescrevem snapshots. As auditorias de algoritmos
continuam a ser ferramentas explícitas e opcionais. Os testes de referência geram
pequenos casos temporários a partir das fixtures existentes; não é incluído nenhum
dataset de produção do SoftCPS.

A CI corre a auditoria de física, a dos datasets oficiais e as do contrato de
entidades e da paridade da refatoração em três jobs paralelos (`audit (physics)`,
`audit (datasets)`, `audit (entity-contract-and-refactor-parity)`), cada um com
`--strict` e a sua seleção `--audits`. Cada job envia a sua evidência JSON como
`citylearn-runtime-audits-<nome>` e o job `runtime-audits` falha se algum dos três
não passar.

As fachadas públicas delegam em módulos internos especializados para os KPIs de
energia/equipamentos/serviço/comunidade, a preparação das observações e do layout
das entidades, as entradas e componentes do carregamento e os contratos e a
auditoria de robustez. A alocação do serviço elétrico é partilhada pelo controlo e
pelo runtime. As importações públicas, os exemplos executáveis e o registo oficial
mantêm a identidade CityLearn; os módulos internos não são APIs de extensão
estáveis.

### Progresso da avaliação

`env.evaluate_v2(progress_callback=callback)` reporta, opcionalmente, eventos
escalares de etapa sem acrescentar tempos à tabela de KPIs nem aos seus
atributos. Cada evento inclui um número de sequência, a etapa, o estado e os
segundos decorridos. As etapas por membro e as respetivas famílias de
equipamentos incluem também o ID do membro, o índice e o total. As etapas
concluídas ou falhadas incluem a duração da etapa. Os observadores recebem
dicionários novos; devem evitar I/O lento e não podem alterar o ambiente. Um
observador que falhe é registado no log e desativado; os erros reais da avaliação
continuam a propagar-se, com eventos de etapa falhada.

O auditor de execuções longas escreve `phase` em `summary.json`, a etapa de KPI
mais recente em `evaluation-progress.json` e o histórico de eventos em
`evaluation-progress.jsonl`. Distingue carregamento, despacho, avaliação final,
exportação de KPIs, reconciliação e exportação de evidência.
`kpi_evaluation_seconds` exclui a exportação e a reconciliação;
`final_kpi_and_export_seconds` mantém o seu significado combinado atual. O
progresso é reportado nas fronteiras entre etapas, pelo que uma família
individual longa pode ficar ativa durante algum tempo. O reporte de KPIs não
instala nenhuma thread em segundo plano nem nenhum callback por passo.

### Histórico de liquidação do mercado

O histórico interno de liquidação guarda colunas numéricas binary64 e IDs de
membros, com offsets para cada intervalo executado. Nenhuma linha é amostrada ou
arredondada. A indexação, o slicing e a iteração expõem listas comuns de
dicionários por passo, como snapshots independentes; atribua de volta um passo
editado para o persistir. Use um slice para ler uma janela ou itere para ler o
histórico em fluxo, em vez de materializar uma execução longa inteira. Os
esquemas de liquidação do passo atual e de exportação não mudam. As linhas
legadas com campos adicionais ou em falta são mantidas na íntegra. Os totais dos
KPIs do mercado são acumulados por ordem cronológica e reconstruídos após edições
históricas. O reset limpa o histórico e os totais.

### Diário de aplicação da robustez

O diário esparso de robustez mantém todas as aplicações registadas e a sua
ordem. Os passos concluídos usam referências inteiras para descrições
partilhadas; o passo atual mantém conjuntos editáveis para a deduplicação de
entradas idênticas. Os resumos acumulam os passos concluídos e tratam à parte a
telemetria terminal não executada. Não são alterados valores de canais
numéricos, o estado do RNG, as regras de aplicação dos eventos nem o estado
físico. `env._robustness_service.history` mantém o seu contrato público completo
de dicionário. Para leituras limitadas, use `history_window(start, stop)` ou
`iter_history(start, stop)` nesse serviço; os limites são índices globais de
passo, com início inclusivo e fim exclusivo. Estes registos de janela/fluxo são
snapshots independentes. O reset limpa o diário e os contadores do resumo em
conjunto. O buffer limitado de atraso das ações mantém-se inalterado.

### Populações ativas dos KPIs

A avaliação dinâmica dos KPIs regista uma única vez as transições esparsas de
pertença e os metadados do ciclo de vida. As famílias de KPIs aninhadas
reutilizam máscaras só de leitura indexadas por membro, horizonte da série e
semântica. A máscara de energia mantém os intervalos de ausência como zero; a
seleção térmica remove as amostras ausentes. Os intervalos concluídos continuam a
excluir a observação terminal, e os ativos históricos continuam a usar os seus
leitores atuais. O âmbito inclui o ambiente, a janela do episódio, o horizonte
executado, a identidade do histórico e a versão da topologia. É atualizado se
algum destes mudar e liberta as máscaras após cada avaliação, incluindo em caso
de exceção; não são guardados em cache valores físicos nem resultados de KPIs. As
consultas públicas à topologia continuam a devolver listas independentes com as
suas regras originais.

### Reutilização do replay de partida dos VE

A viabilidade à partida compara os limiares do alvo, do mínimo aceitável e da
tolerância com um único replay de carregamento máximo por partida/contexto. A
função auxiliar de limiar único continua disponível. Os lotes legados e
auditados ficam separados: as fronteiras de chegada e as regras de corte de
energia podem diferir. O replay continua a percorrer todo o intervalo de ligação,
incluindo as perdas depois de o alvo poder ter sido atingido. As regras físicas
de carregamento, eficiência, redução progressiva (taper), capacidade, banda
morta e limite de serviço não mudam. Os resultados legados permissivos com
entradas em falta e as classificações auditadas desconhecidas mantêm os seus
contratos atuais. Nenhuma memória ou bateria de replay é mantida entre lotes,
sessões, avaliações ou episódios; só o ponto final da partida é partilhado
entre as três comparações. As ações BAU nativas e os históricos reais das
baterias não são tocados.
