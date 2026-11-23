# Notas sobre formatos de datasets retirados

Versão em inglês: [../retired_datasets.md](../retired_datasets.md).

## Suite REC anual de 2023 retirada

As versões 1.8.0 a 3.0.1 incluíam uma escada anual híbrida e reprodutível de
cenários para experiências de tese e de algoritmos. Todas as famílias usam a
linha temporal completa de 2023 em UTC, 35,040 passos de 15 minutos, atributos
do calendário local de Lisboa e ficheiros Parquet autocontidos. O antigo cenário
horário de 17 edifícios continua disponível para reprodução histórica, mas não
faz parte desta suite.

Estes cinco datasets `rec_2023_*` foram removidos do repositório público e do
registo predefinido de datasets no CityLearn 3.0.2. Esta secção é mantida apenas
como documentação histórica do formato; os utilizadores têm de fornecer os seus
próprios ficheiros de dados locais.

Os horários das rotinas são construídos como horas civis de `Europe/Lisbon`
antes da conversão para UTC. A hora em falta da primavera é avançada uma hora e,
na hora repetida do outono, é escolhida de forma determinística a primeira
ocorrência. Isto preserva as rotinas locais pretendidas nos dois dias de mudança
de hora, mantendo uma linha temporal física UTC sem ambiguidades.

| Família | Membros | FV | BESS | Membros com carregamento | Carregadores | Aparelhos diferíveis | Variantes |
|---|---:|---:|---:|---:|---:|---:|---|
| `rec_2023_micro_4_q` | 4 | 2 | 1 | 2 | 2 | 1 | `MICRO-4-Q` |
| `rec_2023_core_15_stripped` | 15 | 7 | 3 | 6 | 7 | 4 | `CORE-15-STRIPPED` |
| `rec_2023_core_30` | 30 | 15 | 6 | 12 | 15 | 8 | Nominal, Safety, Health, Dynamic e Combined |
| `rec_2023_premium_100` | 100 | 55 | 22 | 45 | 80 | 30 | Clean e AllIn |

Cada família tem um `schema.json` predefinido; as variantes alternativas estão
em `schemas/`. As variantes apontam para os mesmos ficheiros físicos, o que faz
das comparações Safety, Health, Dynamic e AllIn gémeos limpos. `catalogs/`
separa as identidades de membro, carregador físico, VE e sessão de carregamento.
Isto permite vários carregadores num membro e diferentes sessões de VE no mesmo
carregador partilhado, sem confundir infraestrutura e mobilidade.

O contrato `2023-q15-v1.9` estratifica também os ativos instalados, em vez de
concentrar todos os ativos flexíveis nos membros FV com os números mais baixos.
Em Core-15, Core-30 e Premium, os membros com carregamento incluem anfitriões
com e sem FV; o caso Micro também inclui um de cada. As baterias continuam
acopladas a FV, mas são distribuídas por rotinas e índices de membro. Isto
mantém a composição declarada e reduz a confusão entre a atribuição de FV e de
VE. Os schemas das variantes usam uma raiz explícita relativa ao diretório pai,
para poderem ser abertos diretamente a partir de `schemas/`.

As formas da procura são sintéticas, mas os seus totais anuais estão ancorados
nas classes portuguesas de consumo por consumidor de 2023: residencial, não
doméstico e industrial. Cinco arquétipos de rotina estratificados por categoria
completa alteram os horários de funcionamento, os picos, a ocupação, os dias de
atividade reduzida, as janelas dos VE e os pedidos de carga diferível. A
capacidade FV está acoplada à procura anual do anfitrião e varia com a
orientação e o derating. O armazenamento estacionário usa classes de
capacidade/potência semelhantes a produtos comerciais, dimensionadas a partir da
autonomia diária estratificada da carga, com um mínimo associado ao FV do
anfitrião; o SOC, a eficiência e os parâmetros de degradação variam por membro.
As previsões meteorológicas têm um erro reprodutível que depende do horizonte.
As previsões derivadas de carga e FV usam persistência causal do dia anterior,
com um arranque a frio no passo atual durante o primeiro dia, pelo que os
algoritmos não podem observar os valores reais futuros de carga/FV através deste
bundle. Os horizontes de preço OMIE respeitam a publicação: os valores
realizados só são usados depois da hora de fecho day-ahead declarada, com
persistência diária causal antes dela. Estas são distribuições de cenário
controladas, não uma amostra estatisticamente ajustada das REC portuguesas.

Cada sessão normal de VE é individualmente realizável com a potência declarada
do carregador e 95% de eficiência. Os pedidos residenciais usam no máximo 85% da
energia da janela do carregador; os pedidos de serviço partilhado usam no máximo
72%, o que reserva pelo menos um passo de controlo mesmo para as sessões normais
mais curtas. Safety e AllIn podem ainda tornar o serviço conjunto inviável
através da procura simultânea, dos limites totais/por fase, dos prazos e das
falhas. As variantes Dynamic exercitam separadamente o ciclo de vida dos membros
e a remoção/reposição independente de carregadores, FV, armazenamento
estacionário e aparelhos diferíveis. Os membros que entram não herdam falhas de
serviço de pedidos que expiraram antes do início da sua participação. As saídas
são permanentes dentro do ano do benchmark, evitando uma reposição implícita do
estado acumulado do participante. Os carregadores residenciais com ligação a uma
fase individual são atribuídos por uma rotação determinística ao nível da
família, cujas contagens L1/L2/L3 diferem no máximo em um.

Um ativo com estado que seja reinstalado é uma nova instância de execução,
inicializada no estado de fronteira declarado; não herda de forma silenciosa o
SoC nem o serviço pendente da instância removida. A instância anterior à remoção
continua disponível para a agregação dos KPIs. A energia trazida para a REC numa
fronteira de ativação deste tipo é uma condição inicial exógena, não energia da
rede criada dentro de um passo de controlo.

`catalogs/electrical_services.parquet` regista, para cada membro, o substituto
da ligação ao nível BTN/BTE portuguesa, a atribuição monofásica/trifásica e os
limites totais e por fase de importação/exportação. O kVA é convertido em kW com
um fator de potência unitário explícito; isto testa a margem da ligação, não o
fluxo de potência no alimentador nem as proteções. O gerador verifica o
envelope nativo de carga não deslocável/FV antes de os ativos flexíveis atuarem
e, quando necessário, passa o membro para o nível BTE declarado seguinte, com
uma margem nativa de 2%. Assim, uma violação de segurança normal tem de resultar
de simultaneidade controlável ou de um evento identificado, não de uma
referência exógena impossível. `file_checksums.sha256` fixa todos os ficheiros
gerados da família.

Os preços da eletricidade vêm do arquivo oficial do mercado diário OMIE para
Portugal. Cada período horário físico do mercado de 2023 é repetido nos seus
quatro passos de simulação de um quarto de hora, sem interpolação, e convertido
de EUR/MWh para EUR/kWh. Os URLs diários das fontes, os números de revisão e os
hashes SHA-256 ficam guardados em `sources/`. A liquidação usa correspondência
local no mesmo passo, um preço local igual a 80% do OMIE, pesos iguais entre
importadores, remuneração nula da exportação residual e um contrafactual só com
a rede.

Gere e valide a suite completa com:

```console
.venv/bin/python scripts/generate_annual_rec_suite.py --families all
.venv/bin/python scripts/audit/audit_annual_rec_suite.py
.venv/bin/python scripts/audit/audit_annual_rec_suite_diversity.py
.venv/bin/python scripts/audit/audit_annual_rec_suite_scientific.py
.venv/bin/python scripts/audit/smoke_annual_rec_suite.py
```

A auditoria verifica o contrato temporal comum, a expansão e a proveniência dos
dados OMIE, as identidades dos ativos e das sessões, a viabilidade individual dos
VE, os prazos dos aparelhos diferíveis, os níveis de ligação portugueses e as
somas por fase, a pertença com vários carregadores, a cobertura dos ativos
dinâmicos, as somas de verificação completas dos ficheiros, os invariantes dos
cenários gémeos e o subconjunto Core-15 de Core-30, idêntico byte a byte. A
auditoria de diversidade mede ainda os traços duplicados exatos, as correlações
de perfis entre pares e entre arquétipos, as horas de pico, as distribuições de
FV/BESS, as distribuições de chegada/duração/folga dos VE e a duplicação dos
horários dos aparelhos diferíveis.
